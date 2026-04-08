#!/usr/bin/env python3
"""
歌詞生成LLM用 データセットビルダー

データセット構築の3つのソース:
  1. テンプレート: style_templates.py の手作り例 (核となる高品質データ)
  2. Self-instruct: ローカルLLMで生成 → 品質フィルタ → 学習データ化
  3. DB既存データ: Django DBからエクスポートした既存歌詞 (export_training_data.py)

全てローカルで完結 (Gemini API不要)。

使い方:
  # テンプレートのみで学習データ生成
  python -m lyrics_generation.dataset_builder --template --output data/lyrics_dataset.json

  # 重要度スコアリング結果からシード生成
  python -m lyrics_generation.dataset_builder --seeds --input data/importance_dataset.jsonl --output data/lyrics_seeds.json

  # Gemini APIで歌詞生成 (開発中はこちらが主力)
  python -m lyrics_generation.dataset_builder generate --input data/lyrics_seeds.json --output data/lyrics_dataset.json --use-gemini

  # ローカルLLMでself-instruct生成 (要GPU、将来移行用)
  python -m lyrics_generation.dataset_builder generate --input data/lyrics_seeds.json --output data/lyrics_dataset.json

  # DB既存データとテンプレートをマージ
  python -m lyrics_generation.dataset_builder merge --inputs data/lyrics_dataset.json data/lyrics_from_db.json --output data/lyrics_final.json
"""

import argparse
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# lyrics_generation パッケージ内のインポート
from .style_templates import (
    SYSTEM_PROMPT,
    GENRES,
    STYLE_EXAMPLES,
    build_user_prompt,
    build_training_record,
    get_all_template_records,
)
from .evaluate import evaluate_lyrics


def generate_template_dataset(output_path: str):
    """テンプレートからSFT学習データを生成 (GPU不要)"""
    records = get_all_template_records()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logger.info(f"テンプレートデータ {len(records)}件を保存: {output_path}")
    return records


def create_seeds_from_importance(input_path: str, output_path: str, genres: list[str] = None):
    """
    重要度スコアリング結果(JSONL) → 歌詞生成用のシードデータに変換。
    シード = (input_text, keywords, genre) のセット。lyricsフィールドは空。
    次のステップで --generate を使ってローカルLLMで歌詞を埋める。
    """
    if genres is None:
        genres = ["pop", "hip-hop"]  # デフォルトは2ジャンルに絞る

    seeds = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            text = data.get("text", "")[:1500]
            keywords_raw = data.get("ranked_keywords", data.get("keywords", []))

            # キーワード抽出
            keywords = []
            for k in keywords_raw[:10]:
                if isinstance(k, dict):
                    term = k.get("term", "")
                    score = k.get("score", k.get("final_score", 0))
                    if score > 0.3 and term:
                        keywords.append(term)
                elif isinstance(k, str):
                    keywords.append(k)

            if len(keywords) < 3:
                continue

            for genre in genres:
                seeds.append({
                    "input_text": text,
                    "genre": genre,
                    "keywords": keywords,
                    "source_file": data.get("source_file", f"line_{line_no}"),
                    "lyrics": "",  # ← --generate で埋める
                })

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(seeds, f, ensure_ascii=False, indent=2)
    logger.info(f"歌詞シード {len(seeds)}件を保存: {output_path}")
    logger.info("次のステップ: --generate で歌詞を生成してください")
    return seeds


def generate_with_local_llm(
    input_path: str,
    output_path: str,
    model_name: str = "Qwen/Qwen2.5-7B-Instruct",
    max_new_tokens: int = 512,
    temperature: float = 0.8,
    min_quality: float = 0.3,
    use_gemini: bool = False,
    gemini_key: str = None,
):
    """
    シードから歌詞を生成してデータセットを構築。

    2つのモード:
      - use_gemini=True: Gemini APIで生成 (開発中の主力、高品質)
      - use_gemini=False: ローカルLLMで生成 (将来移行用、GPU必要)
    """
    with open(input_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    records = []
    skipped = 0
    total = len([s for s in seeds if not s.get("lyrics")])

    if use_gemini:
        records, skipped = _generate_with_gemini(seeds, gemini_key, min_quality)
    else:
        records, skipped = _generate_with_local(seeds, model_name, max_new_tokens, temperature, min_quality)

    # テンプレートデータもマージ
    template_records = get_all_template_records()
    all_records = template_records + records

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    logger.info(
        f"学習データ {len(all_records)}件を保存 "
        f"(テンプレート: {len(template_records)}, 生成: {len(records)}, "
        f"スキップ: {skipped}): {output_path}"
    )
    return all_records


def _generate_with_gemini(seeds, gemini_key=None, min_quality=0.3):
    """Gemini APIで歌詞生成 (開発中の主力)"""
    import os
    api_key = gemini_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEYが必要です (環境変数 or --gemini-key)")

    try:
        import google.generativeai as genai
    except ImportError:
        raise SystemExit("pip install google-generativeai")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    records = []
    skipped = 0
    total = len(seeds)

    for i, seed in enumerate(seeds):
        if seed.get("lyrics"):
            score = evaluate_lyrics(seed["lyrics"], seed["keywords"])
            if score["total"] >= min_quality:
                records.append(build_training_record(seed))
            continue

        user_prompt = build_user_prompt(seed["input_text"], seed["genre"], seed["keywords"])
        prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

        try:
            response = model.generate_content(prompt)
            generated = response.text

            score = evaluate_lyrics(generated, seed["keywords"])
            if score["total"] >= min_quality:
                seed["lyrics"] = generated
                records.append(build_training_record(seed))
                logger.info(f"[{i+1}/{total}] Gemini生成OK (quality={score['total']:.2f})")
            else:
                skipped += 1
                logger.info(f"[{i+1}/{total}] 品質不足でスキップ (quality={score['total']:.2f})")
        except Exception as e:
            skipped += 1
            logger.warning(f"[{i+1}/{total}] Gemini生成失敗: {e}")

    return records, skipped


def _generate_with_local(seeds, model_name, max_new_tokens, temperature, min_quality):
    """ローカルLLMで歌詞生成 (将来移行用)"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    records = []
    skipped = 0
    total = len([s for s in seeds if not s.get("lyrics")])

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    logger.info(f"モデルをロード: {model_name}")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.eval()
    logger.info("モデルロード完了")

    for i, seed in enumerate(seeds):
        if seed.get("lyrics"):
            score = evaluate_lyrics(seed["lyrics"], seed["keywords"])
            if score["total"] >= min_quality:
                records.append(build_training_record(seed))
            continue

        user_prompt = build_user_prompt(
            seed["input_text"], seed["genre"], seed["keywords"]
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        input_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=True,
                top_p=0.9,
                repetition_penalty=1.2,
            )

        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )

        score = evaluate_lyrics(generated, seed["keywords"])
        if score["total"] >= min_quality:
            seed["lyrics"] = generated
            records.append(build_training_record(seed))
            logger.info(
                f"[{i+1}/{total}] ローカル生成OK (quality={score['total']:.2f}, "
                f"genre={seed['genre']})"
            )
        else:
            skipped += 1
            logger.info(
                f"[{i+1}/{total}] 品質不足でスキップ "
                f"(quality={score['total']:.2f} < {min_quality})"
            )

    return records, skipped


def merge_datasets(input_paths: list[str], output_path: str):
    """複数の学習データJSONをマージ (重複除去)"""
    all_records = []
    seen_lyrics = set()

    for path in input_paths:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for record in data:
            # assistant の歌詞テキストで重複チェック
            lyrics = ""
            for msg in record.get("messages", []):
                if msg.get("role") == "assistant":
                    lyrics = msg.get("content", "")
            if lyrics and lyrics not in seen_lyrics:
                seen_lyrics.add(lyrics)
                all_records.append(record)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    logger.info(f"マージ完了: {len(all_records)}件 → {output_path}")
    return all_records


def main():
    parser = argparse.ArgumentParser(
        description="歌詞生成LLM用 データセットビルダー (Track B)"
    )
    sub = parser.add_subparsers(dest="command")

    # テンプレート
    p_tmpl = sub.add_parser("template", help="テンプレートのみで学習データ生成")
    p_tmpl.add_argument("--output", required=True)

    # シード生成
    p_seed = sub.add_parser("seeds", help="重要度結果からシード生成")
    p_seed.add_argument("--input", required=True)
    p_seed.add_argument("--output", required=True)
    p_seed.add_argument("--genres", nargs="+", default=None)

    # ローカルLLM or Gemini生成
    p_gen = sub.add_parser("generate", help="歌詞生成 (Gemini or ローカルLLM)")
    p_gen.add_argument("--input", required=True)
    p_gen.add_argument("--output", required=True)
    p_gen.add_argument("--use-gemini", action="store_true", help="Gemini APIで生成 (デフォルト推奨)")
    p_gen.add_argument("--gemini-key", type=str, help="Gemini APIキー (未指定時は環境変数)")
    p_gen.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct", help="ローカルLLMモデル名")
    p_gen.add_argument("--min-quality", type=float, default=0.3)
    p_gen.add_argument("--temperature", type=float, default=0.8)

    # マージ
    p_merge = sub.add_parser("merge", help="複数データセットをマージ")
    p_merge.add_argument("--inputs", nargs="+", required=True)
    p_merge.add_argument("--output", required=True)

    args = parser.parse_args()

    if args.command == "template":
        generate_template_dataset(args.output)
    elif args.command == "seeds":
        create_seeds_from_importance(args.input, args.output, genres=args.genres)
    elif args.command == "generate":
        generate_with_local_llm(
            args.input, args.output,
            model_name=args.model,
            min_quality=args.min_quality,
            temperature=args.temperature,
            use_gemini=args.use_gemini,
            gemini_key=getattr(args, "gemini_key", None),
        )
    elif args.command == "merge":
        merge_datasets(args.inputs, args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

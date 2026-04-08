#!/usr/bin/env python3
"""
歌詞生成LLM専用 学習スクリプト (Track B)

汎用 train.py のラッパー。歌詞生成に特化した設定・評価を追加。
note_importance の学習とは独立して実行・管理される。

出力先: output/lyrics-lora/ (重要度スコアリングは output/importance-lora/)

使い方:
  # テンプレートデータで学習 (初回・動作確認用)
  python -m lyrics_generation.train_lyrics --template-only --epochs 5

  # 本番データで学習
  python -m lyrics_generation.train_lyrics --data data/lyrics_dataset.json

  # マルチGPU
  accelerate launch -m lyrics_generation.train_lyrics --data data/lyrics_dataset.json

  # 学習後に品質評価
  python -m lyrics_generation.train_lyrics --evaluate --model output/lyrics-lora/
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# training/ をパスに追加
TRAINING_DIR = Path(__file__).resolve().parent.parent
if str(TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(TRAINING_DIR))

# 歌詞生成専用のデフォルト設定
LYRICS_OUTPUT_DIR = str(TRAINING_DIR / "output" / "lyrics-lora")
LYRICS_LOG_PATH = str(TRAINING_DIR / "output" / "lyrics-training.log")

# 歌詞生成に推奨のモデル (日本語が強いモデルを優先)
LYRICS_RECOMMENDED_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",      # 推奨: 日本語性能◎、VRAM ~8GB
    "Qwen/Qwen2.5-14B-Instruct",      # 高品質: 4060Ti 16GBでギリギリ
    "meta-llama/Meta-Llama-3-8B-Instruct",  # 汎用、英語寄り
    "google/gemma-2-9b-it",            # バランス型
]


def train_lyrics(args):
    """歌詞生成LoRA学習を実行"""
    from .style_templates import get_all_template_records
    from .evaluate import evaluate_batch

    # データ準備
    if args.template_only:
        records = get_all_template_records()
        data_path = str(TRAINING_DIR / "data" / "lyrics_template_data.json")
        Path(data_path).parent.mkdir(parents=True, exist_ok=True)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"テンプレートデータ {len(records)}件で学習します")
    else:
        data_path = args.data
        if not data_path or not Path(data_path).exists():
            logger.error(f"データファイルが見つかりません: {data_path}")
            logger.info("まず --template-only で動作確認するか、")
            logger.info("python -m lyrics_generation.dataset_builder template --output data/lyrics_dataset.json")
            sys.exit(1)

        with open(data_path, "r", encoding="utf-8") as f:
            records = json.load(f)

    # 学習前の品質チェック
    stats = evaluate_batch(records)
    logger.info(f"学習データ品質: {stats}")
    if stats.get("count", 0) < 3:
        logger.warning("学習データが少なすぎます (最低3件推奨)")

    # train.py を呼び出し (汎用学習スクリプト)
    train_args = [
        sys.executable, str(TRAINING_DIR / "train.py"),
        "--data_path", data_path,
        "--model_name", args.model,
        "--output_dir", args.output_dir,
        "--epochs", str(args.epochs),
        "--learning_rate", str(args.learning_rate),
    ]

    if args.lora_rank:
        train_args.extend(["--lora_rank", str(args.lora_rank)])
    if args.batch_size:
        train_args.extend(["--batch_size", str(args.batch_size)])

    logger.info(f"学習開始: {' '.join(train_args)}")
    logger.info(f"タスク: 歌詞生成 (Track B)")
    logger.info(f"モデル: {args.model}")
    logger.info(f"出力先: {args.output_dir}")

    import subprocess
    result = subprocess.run(train_args, cwd=str(TRAINING_DIR))
    if result.returncode != 0:
        logger.error(f"学習失敗 (exit code: {result.returncode})")
        sys.exit(result.returncode)

    logger.info("学習完了!")


def evaluate_model(args):
    """学習済みモデルの歌詞生成品質を評価"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    from .style_templates import SYSTEM_PROMPT, STYLE_EXAMPLES, build_user_prompt
    from .evaluate import evaluate_lyrics

    model_path = args.model_path
    base_model = args.base_model

    logger.info(f"評価: base={base_model}, lora={model_path}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    # LoRAがあれば適用
    if model_path and Path(model_path).exists():
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, model_path)
        logger.info("LoRA適用済み")

    model.eval()

    # テンプレート例で生成テスト
    results = []
    for example in STYLE_EXAMPLES[:3]:  # 最初の3例でテスト
        user_prompt = build_user_prompt(
            example["input_text"], example["genre"], example["keywords"]
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
                max_new_tokens=512,
                temperature=0.8,
                do_sample=True,
                top_p=0.9,
                repetition_penalty=1.2,
            )
        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )

        score = evaluate_lyrics(generated, example["keywords"])
        results.append({
            "subject": example.get("subject", ""),
            "genre": example["genre"],
            "score": score,
            "generated_preview": generated[:200] + "..." if len(generated) > 200 else generated,
        })

        logger.info(
            f"[{example.get('subject', '?')}/{example['genre']}] "
            f"total={score['total']:.3f} kw={score['keyword_coverage']:.3f} "
            f"struct={score['structure']:.3f} rhyme={score['rhyme']:.3f}"
        )

    # サマリー
    avg_total = sum(r["score"]["total"] for r in results) / len(results) if results else 0
    logger.info(f"\n平均品質スコア: {avg_total:.3f}")
    if avg_total >= 0.6:
        logger.info("✅ 良好 — 本番利用可能レベル")
    elif avg_total >= 0.4:
        logger.info("⚠ 改善の余地あり — データ追加 or エポック増加を推奨")
    else:
        logger.info("❌ 品質不足 — データの質・量を見直してください")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="歌詞生成LLM 学習 & 評価 (Track B)"
    )
    sub = parser.add_subparsers(dest="command")

    # 学習
    p_train = sub.add_parser("train", help="歌詞生成LoRA学習")
    p_train.add_argument("--data", type=str, help="学習データJSONパス")
    p_train.add_argument("--template-only", action="store_true", help="テンプレートのみで学習")
    p_train.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    p_train.add_argument("--output-dir", default=LYRICS_OUTPUT_DIR)
    p_train.add_argument("--epochs", type=int, default=5)
    p_train.add_argument("--learning-rate", type=float, default=2e-4)
    p_train.add_argument("--lora-rank", type=int, default=None)
    p_train.add_argument("--batch-size", type=int, default=None)

    # 評価
    p_eval = sub.add_parser("evaluate", help="学習済みモデルの品質評価")
    p_eval.add_argument("--model-path", default=LYRICS_OUTPUT_DIR, help="LoRAパス")
    p_eval.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")

    args = parser.parse_args()

    if args.command == "train":
        train_lyrics(args)
    elif args.command == "evaluate":
        evaluate_model(args)
    else:
        parser.print_help()
        print("\n推奨モデル:")
        for m in LYRICS_RECOMMENDED_MODELS:
            print(f"  - {m}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
学習済みLoRAモデルのテストスクリプト

使い方:
  python test_model.py
  python test_model.py --prompt "三角関数 sin cos tan の定義と単位円"
"""

import argparse
import torch

# Windows WDDM環境での Access Violation / OOM を回避（import前に適用）
try:
    import transformers.modeling_utils as _mu_early
    if hasattr(_mu_early, 'caching_allocator_warmup'):
        _mu_early.caching_allocator_warmup = lambda *a, **kw: None
except Exception:
    pass

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

DEFAULT_LORA_PATH = "./output/utamemo-lyrics-lora"
DEFAULT_BASE_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"


def parse_args():
    parser = argparse.ArgumentParser(
        description="UTAMEMO 歌詞生成モデル テスト",
        epilog=(
            "対応モデル: Llama 3, Gemma 2, Phi 3.5, Qwen 2.5 等\n"
            "例: python test_model.py --base_model google/gemma-2-9b-it --no_lora"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base_model", type=str, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--lora_path", type=str, default=DEFAULT_LORA_PATH)
    parser.add_argument("--no_lora", action="store_true",
                        help="LoRA無しでベースモデルのみテスト")
    parser.add_argument("--prompt", type=str, default=None, help="テスト用の学習テキスト")
    parser.add_argument("--genre", type=str, default="pop")
    parser.add_argument("--hf_token", type=str, default=None)
    return parser.parse_args()


def generate_lyrics(model, tokenizer, study_text, genre="pop"):
    """学習テキストから歌詞を生成
    
    tokenizer.apply_chat_template() を使用するため、
    Llama 3 / Gemma 2 / Phi / Qwen 等どのモデルでも動作する。
    """
    system_prompt = (
        "あなたは暗記学習用の歌詞を作成する専門AIです。"
        "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"
        "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
    )

    user_prompt = (
        f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
        f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
        f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
        f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
        f"■ 学習テキスト\n{study_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        input_ids = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        )
    except Exception:
        # system role 非対応モデル → system をユーザーに統合
        messages_no_sys = [
            {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
        ]
        input_ids = tokenizer.apply_chat_template(
            messages_no_sys, add_generation_prompt=True, return_tensors="pt"
        )

    # apply_chat_template が dict (BatchEncoding) を返す場合の対応
    if hasattr(input_ids, 'keys'):
        input_ids = input_ids["input_ids"]
    input_ids = input_ids.to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            input_ids=input_ids,
            max_new_tokens=1024,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            repetition_penalty=1.1,
            eos_token_id=tokenizer.eos_token_id,
        )

    # 入力部分を除去して出力のみ取得
    response = tokenizer.decode(outputs[0][input_ids.shape[-1]:], skip_special_tokens=True)
    return response.strip()


def main():
    args = parse_args()

    print("=" * 60)
    print("UTAMEMO 歌詞生成モデル テスト")
    print("=" * 60)

    # モデルロード
    print(f"ベースモデル: {args.base_model}")
    if args.no_lora:
        print("LoRA: 無し (ベースモデルのみ)")
    else:
        print(f"LoRAアダプタ: {args.lora_path}")
    print("モデルをロード中...")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, token=args.hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        max_memory={0: "14GiB", "cpu": "1GiB"},
        token=args.hf_token,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )

    if args.no_lora:
        model = base_model
    else:
        model = PeftModel.from_pretrained(base_model, args.lora_path)
    model.eval()

    print("✅ モデルロード完了\n")

    # テストケース
    test_cases = [
        {
            "text": "水の電気分解: 水に電流を流すと、陽極から酸素、陰極から水素が発生する。水素と酸素の体積比は2:1。化学式: 2H2O → 2H2 + O2",
            "genre": "pop"
        },
        {
            "text": "関ヶ原の戦い 1600年 徳川家康（東軍）vs 石田三成（西軍）天下分け目の戦い。小早川秀秋の寝返りで東軍勝利。家康は1603年に征夷大将軍となり江戸幕府を開く。",
            "genre": "rock"
        },
    ]

    if args.prompt:
        test_cases = [{"text": args.prompt, "genre": args.genre}]

    for i, case in enumerate(test_cases):
        print(f"--- テスト {i + 1} ---")
        print(f"テーマ: {case['text'][:60]}...")
        print(f"ジャンル: {case['genre']}")
        print()

        lyrics = generate_lyrics(model, tokenizer, case["text"], case["genre"])
        print(lyrics)
        print()
        print("=" * 60)
        print()


if __name__ == "__main__":
    main()

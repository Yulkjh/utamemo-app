#!/usr/bin/env python3
"""
重要度スコアリングモデルの学習スクリプト

ルールベーススコアをLLMに学習させ、文脈を考慮した重要度判定を行えるようにする。
ノートOCRテキスト → 重要ワード + スコア のペアデータでQLoRA学習。

前提: build_importance_dataset.py または手動で作成したJSONLデータ

データ形式 (JSONL):
  {"text": "OCRテキスト全文", "keywords": [{"term": "織田信長", "score": 0.95}, ...]}

使い方:
  # 自宅PC (4060 Ti 16GB)
  python -m note_importance.train_scorer --data_path data/importance_train.jsonl

  # 学校PC (4080 x2, accelerateで)
  accelerate launch -m note_importance.train_scorer --data_path data/importance_train.jsonl

  # 小さいモデルでテスト
  python -m note_importance.train_scorer --data_path data/importance_train.jsonl --model_name Qwen/Qwen2.5-1.5B-Instruct --epochs 3
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
OUTPUT_DIR = "./output/utamemo-importance-lora"
MAX_SEQ_LENGTH = 1024


def build_training_prompt(text: str, keywords: list[dict]) -> dict:
    """学習データ1件をプロンプト形式に変換"""
    system = (
        "あなたは教育コンテンツの重要度分析AIです。"
        "与えられたノートのテキストから、テストに出る重要ワードを抽出し、"
        "各ワードに0.0〜1.0の重要度スコアを付けてJSON形式で返してください。"
    )
    user = f"以下のノートテキストの重要ワードをスコア付けしてください:\n\n{text[:1500]}"
    assistant = json.dumps(keywords[:30], ensure_ascii=False)

    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


def load_dataset(data_path: str) -> list[dict]:
    """JSONL形式のデータを読み込んでプロンプト形式に変換"""
    records = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            text = data.get("text", "")
            keywords = data.get("keywords") or data.get("ranked_keywords", [])

            # build_importance_dataset.py 形式への対応
            if keywords and isinstance(keywords[0], dict) and "term" in keywords[0]:
                if "score" not in keywords[0] and "importance" not in keywords[0]:
                    # スコアがない場合はルールベースで付ける
                    max_s = max((k.get("score", 1) for k in keywords), default=1)
                    for k in keywords:
                        k["score"] = round(k.get("score", 1) / max(max_s, 1), 3)

            prompt = build_training_prompt(text, keywords)
            records.append(prompt)

    logger.info(f"学習データ: {len(records)}件 from {data_path}")
    return records


def train(args):
    """QLoRA学習を実行"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer, DataCollatorForCompletionOnlyLM
    from datasets import Dataset

    # データ読み込み
    records = load_dataset(args.data_path)
    if not records:
        raise SystemExit("学習データが空です")

    # 検証データ分割
    if args.eval_split > 0 and len(records) > 5:
        split_idx = max(1, int(len(records) * (1 - args.eval_split)))
        train_data = records[:split_idx]
        eval_data = records[split_idx:]
    else:
        train_data = records
        eval_data = None

    logger.info(f"学習: {len(train_data)}件, 検証: {len(eval_data) if eval_data else 0}件")

    # モデルロード
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    logger.info(f"モデルロード: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model)

    # LoRA設定
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_rank * 2,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # データセット変換
    def format_messages(example):
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    train_dataset = Dataset.from_list(train_data).map(format_messages)
    eval_dataset = Dataset.from_list(eval_data).map(format_messages) if eval_data else None

    # 学習設定
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset else "no",
        fp16=False,
        bf16=True,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        report_to="none",
        save_total_limit=2,
    )

    # トレーナー
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        max_seq_length=MAX_SEQ_LENGTH,
    )

    logger.info("学習開始!")
    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    logger.info(f"学習完了! 保存先: {args.output_dir}")


def main():
    parser = argparse.ArgumentParser(description="重要度スコアリングモデル学習")
    parser.add_argument("--model_name", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--data_path", type=str, required=True, help="学習データ (JSONL)")
    parser.add_argument("--output_dir", type=str, default=OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--gradient_accumulation", type=int, default=8)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument("--lora_rank", type=int, default=32)
    parser.add_argument("--eval_split", type=float, default=0.1)
    args = parser.parse_args()

    train(args)


if __name__ == "__main__":
    main()

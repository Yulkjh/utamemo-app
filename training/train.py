#!/usr/bin/env python3
"""
UTAMEMO 歌詞生成LoRA学習スクリプト

ベースモデル: meta-llama/Meta-Llama-3-8B-Instruct
学習方法: QLoRA (4bit量子化 + LoRA)
必要VRAM: ~16GB (RTX 4090 1台で実行可能)

使い方 (学校のGPU PCで実行):
  pip install -r requirements_training.txt
  python train.py --data_path data/lyrics_training_data.json

学習データが少ない場合はサンプルデータで動作確認:
  python train.py --data_path data/sample_training_data.json --epochs 5
"""

import argparse
import json
import logging
import os
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTTrainer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# 設定
# =============================================================================
DEFAULT_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
OUTPUT_DIR = "./output/utamemo-lyrics-lora"
MAX_SEQ_LENGTH = 2048


def parse_args():
    parser = argparse.ArgumentParser(description="UTAMEMO LoRA学習")
    parser.add_argument(
        "--model_name", type=str, default=DEFAULT_MODEL,
        help="ベースモデル名 (Hugging Face Hub)"
    )
    parser.add_argument(
        "--data_path", type=str, required=True,
        help="学習データJSONファイルのパス"
    )
    parser.add_argument(
        "--output_dir", type=str, default=OUTPUT_DIR,
        help="学習済みLoRAアダプタの保存先"
    )
    parser.add_argument(
        "--epochs", type=int, default=3,
        help="学習エポック数"
    )
    parser.add_argument(
        "--batch_size", type=int, default=2,
        help="バッチサイズ (VRAM不足なら1に下げる)"
    )
    parser.add_argument(
        "--learning_rate", type=float, default=2e-4,
        help="学習率"
    )
    parser.add_argument(
        "--lora_rank", type=int, default=32,
        help="LoRAのランク (8, 16, 32, 64)"
    )
    parser.add_argument(
        "--lora_alpha", type=int, default=64,
        help="LoRAのalpha (通常rankの2倍)"
    )
    parser.add_argument(
        "--gradient_accumulation", type=int, default=4,
        help="勾配蓄積ステップ数"
    )
    parser.add_argument(
        "--hf_token", type=str, default=None,
        help="Hugging Faceのアクセストークン (Llamaモデルのダウンロードに必要)"
    )
    return parser.parse_args()


def format_training_example(example):
    """学習データを Llama 3 Instruct のチャットフォーマットに変換"""
    instruction = example["instruction"]
    input_text = example.get("input", "")
    output_text = example["output"]

    if input_text:
        user_message = f"{instruction}\n\n■ 学習テキスト\n{input_text}"
    else:
        user_message = instruction

    # Llama 3 Instruct フォーマット
    formatted = (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n"
        "あなたは暗記学習用の歌詞を作成する専門AIです。"
        "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"
        "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
        "<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{user_message}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
        f"{output_text}<|eot_id|>"
    )
    return formatted


def load_training_data(data_path):
    """学習データを読み込み"""
    logger.info(f"学習データを読み込み: {data_path}")

    with open(data_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    logger.info(f"  {len(raw_data)} 件のデータを読み込みました")

    # フォーマット変換
    formatted_texts = []
    for example in raw_data:
        text = format_training_example(example)
        formatted_texts.append({"text": text})

    dataset = Dataset.from_list(formatted_texts)
    logger.info(f"  Dataset作成完了: {len(dataset)} 件")

    return dataset


def setup_model_and_tokenizer(model_name, hf_token=None):
    """4bit量子化でモデルとトークナイザーをロード"""
    logger.info(f"モデルをロード: {model_name}")

    # 4bit量子化設定 (QLoRA)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # トークナイザー
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        token=hf_token,
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # モデル
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        token=hf_token,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )

    model = prepare_model_for_kbit_training(model)

    # GPU情報を表示
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            gpu_name = torch.cuda.get_device_name(i)
            gpu_mem = torch.cuda.get_device_properties(i).total_mem / 1024**3
            logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f} GB)")

    logger.info(f"  モデルロード完了")
    return model, tokenizer


def setup_lora(model, lora_rank, lora_alpha):
    """LoRAアダプタを設定"""
    logger.info(f"LoRA設定: rank={lora_rank}, alpha={lora_alpha}")

    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )

    model = get_peft_model(model, lora_config)

    # 学習可能パラメータを表示
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    logger.info(
        f"  学習可能パラメータ: {trainable_params:,} / {total_params:,} "
        f"({100 * trainable_params / total_params:.2f}%)"
    )

    return model


def train(args):
    """メイン学習処理"""
    logger.info("=" * 60)
    logger.info("UTAMEMO 歌詞生成LoRA学習 開始")
    logger.info("=" * 60)

    # データ読み込み
    dataset = load_training_data(args.data_path)

    # モデル & トークナイザー
    model, tokenizer = setup_model_and_tokenizer(args.model_name, args.hf_token)

    # LoRA設定
    model = setup_lora(model, args.lora_rank, args.lora_alpha)

    # 学習引数
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=3,
        bf16=True,
        optim="paged_adamw_32bit",
        max_grad_norm=0.3,
        report_to="none",
        seed=42,
    )

    # SFTTrainer (Supervised Fine-Tuning)
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_text_field="text",
        packing=True,
    )

    # 学習実行
    logger.info("学習を開始します...")
    logger.info(f"  エポック数: {args.epochs}")
    logger.info(f"  バッチサイズ: {args.batch_size}")
    logger.info(f"  勾配蓄積: {args.gradient_accumulation}")
    logger.info(f"  実効バッチサイズ: {args.batch_size * args.gradient_accumulation}")
    logger.info(f"  学習率: {args.learning_rate}")

    trainer.train()

    # 保存
    logger.info(f"LoRAアダプタを保存: {args.output_dir}")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    logger.info("=" * 60)
    logger.info("✅ 学習完了!")
    logger.info(f"   LoRAアダプタ: {args.output_dir}")
    logger.info("")
    logger.info("次のステップ:")
    logger.info("  1. python test_model.py でテスト")
    logger.info("  2. python serve.py で推論サーバー起動")
    logger.info("=" * 60)


if __name__ == "__main__":
    args = parse_args()
    train(args)

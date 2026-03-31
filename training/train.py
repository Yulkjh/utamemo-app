#!/usr/bin/env python3#!/usr/bin/env python3

""""""

UTAMEMO 歌詞生成LoRA学習スクリプトUTAMEMO 歌詞生成LoRA学習スクリプト



ベースモデル: meta-llama/Meta-Llama-3-8B-Instruct (デフォルト)ベースモデル: meta-llama/Meta-Llama-3-8B-Instruct

学習方法: QLoRA (4bit量子化 + LoRA)学習方法: QLoRA (4bit量子化 + LoRA)

マルチGPU: RTX 4080 x2 対応 (accelerate / device_map="auto")必要VRAM: ~16GB (RTX 4090 1台で実行可能)



使い方 (学校のGPU PCで実行):使い方 (学校のGPU PCで実行):

  # シングルGPU  pip install -r requirements_training.txt

  python train.py --data_path data/lyrics_training_data.json  python train.py --data_path data/lyrics_training_data.json



  # マルチGPU (RTX 4080 x2)学習データが少ない場合はサンプルデータで動作確認:

  accelerate launch train.py --data_path data/lyrics_training_data.json  python train.py --data_path data/sample_training_data.json --epochs 5

"""

  # サンプルデータで動作確認

  python train.py --data_path data/sample_training_data.json --epochs 5import argparse

import json

  # 対応モデル一覧import logging

  python train.py --list_modelsimport os

"""from pathlib import Path



import argparseimport torch

import jsonfrom datasets import Dataset

import loggingfrom peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType

import osfrom transformers import (

from pathlib import Path    AutoModelForCausalLM,

    AutoTokenizer,

import torch    BitsAndBytesConfig,

from datasets import Dataset    TrainingArguments,

from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType)

from transformers import (from trl import SFTTrainer

    AutoModelForCausalLM,

    AutoTokenizer,logging.basicConfig(level=logging.INFO)

    BitsAndBytesConfig,logger = logging.getLogger(__name__)

    TrainingArguments,

    EarlyStoppingCallback,# =============================================================================

)# 設定

from trl import SFTTrainer# =============================================================================

DEFAULT_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"

logging.basicConfig(level=logging.INFO)OUTPUT_DIR = "./output/utamemo-lyrics-lora"

logger = logging.getLogger(__name__)MAX_SEQ_LENGTH = 2048



# =============================================================================# 対応モデル一覧 (--model_name にどれでも指定可能)

# 設定SUPPORTED_MODELS = {

# =============================================================================    # Llama 3 系

DEFAULT_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"    "meta-llama/Meta-Llama-3-8B-Instruct":    "Llama 3 8B (推奨, ~16GB VRAM)",

OUTPUT_DIR = "./output/utamemo-lyrics-lora"    "meta-llama/Meta-Llama-3-70B-Instruct":   "Llama 3 70B (高品質, ~40GB VRAM)",

MAX_SEQ_LENGTH = 2048    # Gemma 2 系

    "google/gemma-2-2b-it":                    "Gemma 2 2B (軽量, ~6GB VRAM)",

# 対応モデル一覧 (--model_name にどれでも指定可能)    "google/gemma-2-9b-it":                    "Gemma 2 9B (バランス, ~12GB VRAM)",

SUPPORTED_MODELS = {    "google/gemma-2-27b-it":                   "Gemma 2 27B (高品質, ~20GB VRAM)",

    # Llama 3 系    # Phi 系

    "meta-llama/Meta-Llama-3-8B-Instruct":    "Llama 3 8B (推奨, ~16GB VRAM)",    "microsoft/Phi-3.5-mini-instruct":         "Phi 3.5 Mini 3.8B (~8GB VRAM)",

    "meta-llama/Meta-Llama-3-70B-Instruct":   "Llama 3 70B (高品質, ~40GB VRAM x2)",    # Qwen 2.5 系

    # Gemma 2 系    "Qwen/Qwen2.5-7B-Instruct":               "Qwen 2.5 7B (~12GB VRAM)",

    "google/gemma-2-2b-it":                    "Gemma 2 2B (軽量, ~6GB VRAM)",    "Qwen/Qwen2.5-14B-Instruct":              "Qwen 2.5 14B (~16GB VRAM)",

    "google/gemma-2-9b-it":                    "Gemma 2 9B (バランス, ~12GB VRAM)",}

    "google/gemma-2-27b-it":                   "Gemma 2 27B (高品質, ~20GB VRAM)",

    # Phi 系

    "microsoft/Phi-3.5-mini-instruct":         "Phi 3.5 Mini 3.8B (~8GB VRAM)",def parse_args():

    # Qwen 2.5 系    parser = argparse.ArgumentParser(description="UTAMEMO LoRA学習")

    "Qwen/Qwen2.5-7B-Instruct":               "Qwen 2.5 7B (~12GB VRAM)",    parser.add_argument(

    "Qwen/Qwen2.5-14B-Instruct":              "Qwen 2.5 14B (~16GB VRAM)",        "--model_name", type=str, default=DEFAULT_MODEL,

    "Qwen/Qwen2.5-32B-Instruct":              "Qwen 2.5 32B (~24GB VRAM, 2GPU推奨)",        help="ベースモデル名 (Hugging Face Hub). --list_models で一覧表示"

}    )

    parser.add_argument(

# モデルファミリー別 LoRA target_modules        "--list_models", action="store_true",

# モデルアーキテクチャが異なるため、レイヤー名が異なる        help="対応モデル一覧を表示して終了"

MODEL_TARGET_MODULES = {    )

    "llama": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],    parser.add_argument(

    "gemma": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],        "--data_path", type=str, required=True,

    "phi":   ["q_proj", "k_proj", "v_proj", "dense", "fc1", "fc2"],        help="学習データJSONファイルのパス"

    "qwen":  ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],    )

}    parser.add_argument(

        "--output_dir", type=str, default=OUTPUT_DIR,

        help="学習済みLoRAアダプタの保存先"

def detect_model_family(model_name):    )

    """モデル名からファミリーを判定"""    parser.add_argument(

    name_lower = model_name.lower()        "--epochs", type=int, default=3,

    if "llama" in name_lower:        help="学習エポック数"

        return "llama"    )

    elif "gemma" in name_lower:    parser.add_argument(

        return "gemma"        "--batch_size", type=int, default=2,

    elif "phi" in name_lower:        help="バッチサイズ (VRAM不足なら1に下げる)"

        return "phi"    )

    elif "qwen" in name_lower:    parser.add_argument(

        return "qwen"        "--learning_rate", type=float, default=2e-4,

    else:        help="学習率"

        logger.warning(f"Unknown model family for '{model_name}', using llama defaults")    )

        return "llama"    parser.add_argument(

        "--lora_rank", type=int, default=32,

        help="LoRAのランク (8, 16, 32, 64)"

def parse_args():    )

    parser = argparse.ArgumentParser(description="UTAMEMO LoRA学習")    parser.add_argument(

    parser.add_argument(        "--lora_alpha", type=int, default=64,

        "--model_name", type=str, default=DEFAULT_MODEL,        help="LoRAのalpha (通常rankの2倍)"

        help="ベースモデル名 (Hugging Face Hub). --list_models で一覧表示"    )

    )    parser.add_argument(

    parser.add_argument(        "--gradient_accumulation", type=int, default=4,

        "--list_models", action="store_true",        help="勾配蓄積ステップ数"

        help="対応モデル一覧を表示して終了"    )

    )    parser.add_argument(

    parser.add_argument(        "--hf_token", type=str, default=None,

        "--data_path", type=str, default=None,        help="Hugging Faceのアクセストークン (Llamaモデルのダウンロードに必要)"

        help="学習データJSONファイルのパス"    )

    )    return parser.parse_args()

    parser.add_argument(

        "--output_dir", type=str, default=OUTPUT_DIR,

        help="学習済みLoRAアダプタの保存先"SYSTEM_PROMPT = (

    )    "あなたは暗記学習用の歌詞を作成する専門AIです。"

    parser.add_argument(    "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"

        "--epochs", type=int, default=3,    "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"

        help="学習エポック数")

    )

    parser.add_argument(

        "--batch_size", type=int, default=2,def format_training_example(example, tokenizer):

        help="バッチサイズ (VRAM不足なら1に下げる)"    """学習データをモデルのチャットフォーマットに変換

    )    

    parser.add_argument(    tokenizer.apply_chat_template() を使うため、

        "--learning_rate", type=float, default=2e-4,    Llama 3 / Gemma 2 / Phi / Qwen 等どのモデルでも正しいフォーマットになる。

        help="学習率"    """

    )    instruction = example["instruction"]

    parser.add_argument(    input_text = example.get("input", "")

        "--lora_rank", type=int, default=32,    output_text = example["output"]

        help="LoRAのランク (8, 16, 32, 64)"

    )    if input_text:

    parser.add_argument(        user_message = f"{instruction}\n\n■ 学習テキスト\n{input_text}"

        "--lora_alpha", type=int, default=64,    else:

        help="LoRAのalpha (通常rankの2倍)"        user_message = instruction

    )

    parser.add_argument(    messages = [

        "--gradient_accumulation", type=int, default=4,        {"role": "system", "content": SYSTEM_PROMPT},

        help="勾配蓄積ステップ数"        {"role": "user", "content": user_message},

    )        {"role": "assistant", "content": output_text},

    parser.add_argument(    ]

        "--eval_split", type=float, default=0.1,

        help="検証データの割合 (0.0で検証なし, 0.1で10%%を検証用)"    # tokenizer のチャットテンプレートで自動フォーマット

    )    try:

    parser.add_argument(        formatted = tokenizer.apply_chat_template(

        "--early_stopping_patience", type=int, default=3,            messages, tokenize=False, add_generation_prompt=False

        help="Early Stoppingの忍耐回数 (0で無効)"        )

    )    except Exception:

    parser.add_argument(        # system role 非対応のモデル (一部の古いモデル) → system をユーザーに統合

        "--wandb_project", type=str, default="",        messages_no_sys = [

        help="W&Bプロジェクト名 (空で無効, 例: 'utamemo-lyrics')"            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_message}"},

    )            {"role": "assistant", "content": output_text},

    parser.add_argument(        ]

        "--hf_token", type=str, default=None,        formatted = tokenizer.apply_chat_template(

        help="Hugging Faceのアクセストークン (Llamaモデルのダウンロードに必要)"            messages_no_sys, tokenize=False, add_generation_prompt=False

    )        )

    parser.add_argument(

        "--resume_from_checkpoint", type=str, default=None,    return formatted

        help="チェックポイントから学習再開 (パスを指定)"

    )

    return parser.parse_args()def load_training_data(data_path, tokenizer):

    """学習データを読み込み"""

    logger.info(f"学習データを読み込み: {data_path}")

SYSTEM_PROMPT = (

    "あなたは暗記学習用の歌詞を作成する専門AIです。"    with open(data_path, 'r', encoding='utf-8') as f:

    "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"        raw_data = json.load(f)

    "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"

)    logger.info(f"  {len(raw_data)} 件のデータを読み込みました")



    # フォーマット変換

def format_training_example(example, tokenizer):    formatted_texts = []

    """学習データをモデルのチャットフォーマットに変換    for example in raw_data:

        text = format_training_example(example, tokenizer)

    tokenizer.apply_chat_template() を使うため、        formatted_texts.append({"text": text})

    Llama 3 / Gemma 2 / Phi / Qwen 等どのモデルでも正しいフォーマットになる。

    """    dataset = Dataset.from_list(formatted_texts)

    instruction = example["instruction"]    logger.info(f"  Dataset作成完了: {len(dataset)} 件")

    input_text = example.get("input", "")

    output_text = example["output"]    return dataset



    if input_text:

        user_message = f"{instruction}\n\n■ 学習テキスト\n{input_text}"def setup_model_and_tokenizer(model_name, hf_token=None):

    else:    """4bit量子化でモデルとトークナイザーをロード"""

        user_message = instruction    logger.info(f"モデルをロード: {model_name}")



    messages = [    # 4bit量子化設定 (QLoRA)

        {"role": "system", "content": SYSTEM_PROMPT},    bnb_config = BitsAndBytesConfig(

        {"role": "user", "content": user_message},        load_in_4bit=True,

        {"role": "assistant", "content": output_text},        bnb_4bit_quant_type="nf4",

    ]        bnb_4bit_compute_dtype=torch.bfloat16,

        bnb_4bit_use_double_quant=True,

    # tokenizer のチャットテンプレートで自動フォーマット    )

    try:

        formatted = tokenizer.apply_chat_template(    # トークナイザー

            messages, tokenize=False, add_generation_prompt=False    tokenizer = AutoTokenizer.from_pretrained(

        )        model_name,

    except Exception:        token=hf_token,

        # system role 非対応のモデル → system をユーザーに統合        trust_remote_code=True,

        messages_no_sys = [    )

            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_message}"},    tokenizer.pad_token = tokenizer.eos_token

            {"role": "assistant", "content": output_text},    tokenizer.padding_side = "right"

        ]

        formatted = tokenizer.apply_chat_template(    # モデル

            messages_no_sys, tokenize=False, add_generation_prompt=False    model = AutoModelForCausalLM.from_pretrained(

        )        model_name,

        quantization_config=bnb_config,

    return formatted        device_map="auto",

        token=hf_token,

        trust_remote_code=True,

def load_training_data(data_path, tokenizer, eval_split=0.1):        torch_dtype=torch.bfloat16,

    """学習データを読み込み、train/eval分割"""    )

    logger.info(f"学習データを読み込み: {data_path}")

    model = prepare_model_for_kbit_training(model)

    with open(data_path, 'r', encoding='utf-8') as f:

        raw_data = json.load(f)    # GPU情報を表示

    if torch.cuda.is_available():

    logger.info(f"  {len(raw_data)} 件のデータを読み込みました")        for i in range(torch.cuda.device_count()):

            gpu_name = torch.cuda.get_device_name(i)

    # 品質フィルタリング: _meta.quality >= 0.3 のみ使用 (低品質除外)            gpu_mem = torch.cuda.get_device_properties(i).total_mem / 1024**3

    filtered = []            logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f} GB)")

    for example in raw_data:

        quality = example.get("_meta", {}).get("quality", 1.0)    logger.info(f"  モデルロード完了")

        if quality >= 0.3:    return model, tokenizer

            filtered.append(example)

        else:

            logger.debug(f"  低品質データをスキップ (quality={quality})")def setup_lora(model, lora_rank, lora_alpha):

    """LoRAアダプタを設定"""

    if len(filtered) < len(raw_data):    logger.info(f"LoRA設定: rank={lora_rank}, alpha={lora_alpha}")

        logger.info(f"  品質フィルタ: {len(raw_data)} → {len(filtered)} 件 ({len(raw_data) - len(filtered)} 件除外)")

    raw_data = filtered    lora_config = LoraConfig(

        r=lora_rank,

    # フォーマット変換        lora_alpha=lora_alpha,

    formatted_texts = []        lora_dropout=0.05,

    for example in raw_data:        bias="none",

        text = format_training_example(example, tokenizer)        task_type=TaskType.CAUSAL_LM,

        formatted_texts.append({"text": text})        target_modules=[

            "q_proj", "k_proj", "v_proj", "o_proj",

    dataset = Dataset.from_list(formatted_texts)            "gate_proj", "up_proj", "down_proj",

        ],

    # train/eval 分割    )

    if eval_split > 0 and len(dataset) >= 10:

        split = dataset.train_test_split(test_size=eval_split, seed=42)    model = get_peft_model(model, lora_config)

        train_dataset = split["train"]

        eval_dataset = split["test"]    # 学習可能パラメータを表示

        logger.info(f"  Train: {len(train_dataset)} 件, Eval: {len(eval_dataset)} 件")    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

        return train_dataset, eval_dataset    total_params = sum(p.numel() for p in model.parameters())

    else:    logger.info(

        logger.info(f"  Dataset: {len(dataset)} 件 (検証データなし)")        f"  学習可能パラメータ: {trainable_params:,} / {total_params:,} "

        return dataset, None        f"({100 * trainable_params / total_params:.2f}%)"

    )



def setup_model_and_tokenizer(model_name, hf_token=None):    return model

    """4bit量子化でモデルとトークナイザーをロード"""

    logger.info(f"モデルをロード: {model_name}")

def train(args):

    # 4bit量子化設定 (QLoRA)    """メイン学習処理"""

    bnb_config = BitsAndBytesConfig(    logger.info("=" * 60)

        load_in_4bit=True,    logger.info("UTAMEMO 歌詞生成LoRA学習 開始")

        bnb_4bit_quant_type="nf4",    logger.info(f"  ベースモデル: {args.model_name}")

        bnb_4bit_compute_dtype=torch.bfloat16,    logger.info("=" * 60)

        bnb_4bit_use_double_quant=True,

    )    # モデル & トークナイザー (先にロードしてチャットテンプレートを確定)

    model, tokenizer = setup_model_and_tokenizer(args.model_name, args.hf_token)

    # トークナイザー

    tokenizer = AutoTokenizer.from_pretrained(    # データ読み込み (tokenizer のチャットテンプレートでフォーマット)

        model_name,    dataset = load_training_data(args.data_path, tokenizer)

        token=hf_token,

        trust_remote_code=True,    # LoRA設定

    )    model = setup_lora(model, args.lora_rank, args.lora_alpha)

    tokenizer.pad_token = tokenizer.eos_token

    tokenizer.padding_side = "right"    # 学習引数

    training_args = TrainingArguments(

    # モデル (マルチGPU対応: device_map="auto" で自動分散)        output_dir=args.output_dir,

    model = AutoModelForCausalLM.from_pretrained(        num_train_epochs=args.epochs,

        model_name,        per_device_train_batch_size=args.batch_size,

        quantization_config=bnb_config,        gradient_accumulation_steps=args.gradient_accumulation,

        device_map="auto",        learning_rate=args.learning_rate,

        token=hf_token,        weight_decay=0.01,

        trust_remote_code=True,        warmup_ratio=0.03,

        torch_dtype=torch.bfloat16,        lr_scheduler_type="cosine",

    )        logging_steps=5,

        save_strategy="epoch",

    model = prepare_model_for_kbit_training(model)        save_total_limit=3,

        bf16=True,

    # GPU情報を表示        optim="paged_adamw_32bit",

    if torch.cuda.is_available():        max_grad_norm=0.3,

        for i in range(torch.cuda.device_count()):        report_to="none",

            gpu_name = torch.cuda.get_device_name(i)        seed=42,

            gpu_mem = torch.cuda.get_device_properties(i).total_mem / 1024**3    )

            logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f} GB)")

        if torch.cuda.device_count() > 1:    # SFTTrainer (Supervised Fine-Tuning)

            logger.info(f"  → マルチGPU検出: {torch.cuda.device_count()}台で自動分散")    trainer = SFTTrainer(

    else:        model=model,

        logger.warning("  ⚠️ GPUが検出されません！CPUモードで動作します（非常に遅い）")        tokenizer=tokenizer,

        train_dataset=dataset,

    logger.info("  モデルロード完了")        args=training_args,

    return model, tokenizer        max_seq_length=MAX_SEQ_LENGTH,

        dataset_text_field="text",

        packing=True,

def setup_lora(model, model_name, lora_rank, lora_alpha):    )

    """LoRAアダプタを設定（モデルファミリー自動判定）"""

    family = detect_model_family(model_name)    # 学習実行

    target_modules = MODEL_TARGET_MODULES.get(family, MODEL_TARGET_MODULES["llama"])    logger.info("学習を開始します...")

    logger.info(f"  エポック数: {args.epochs}")

    logger.info(f"LoRA設定: rank={lora_rank}, alpha={lora_alpha}, family={family}")    logger.info(f"  バッチサイズ: {args.batch_size}")

    logger.info(f"  target_modules: {target_modules}")    logger.info(f"  勾配蓄積: {args.gradient_accumulation}")

    logger.info(f"  実効バッチサイズ: {args.batch_size * args.gradient_accumulation}")

    lora_config = LoraConfig(    logger.info(f"  学習率: {args.learning_rate}")

        r=lora_rank,

        lora_alpha=lora_alpha,    trainer.train()

        lora_dropout=0.05,

        bias="none",    # 保存

        task_type=TaskType.CAUSAL_LM,    logger.info(f"LoRAアダプタを保存: {args.output_dir}")

        target_modules=target_modules,    model.save_pretrained(args.output_dir)

    )    tokenizer.save_pretrained(args.output_dir)



    model = get_peft_model(model, lora_config)    logger.info("=" * 60)

    logger.info("✅ 学習完了!")

    # 学習可能パラメータを表示    logger.info(f"   LoRAアダプタ: {args.output_dir}")

    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)    logger.info("")

    total_params = sum(p.numel() for p in model.parameters())    logger.info("次のステップ:")

    logger.info(    logger.info("  1. python test_model.py でテスト")

        f"  学習可能パラメータ: {trainable_params:,} / {total_params:,} "    logger.info("  2. python serve.py で推論サーバー起動")

        f"({100 * trainable_params / total_params:.2f}%)"    logger.info("=" * 60)

    )



    return modelif __name__ == "__main__":

    args = parse_args()

    if args.list_models:

def train(args):        print("\n対応モデル一覧 (--model_name に指定可能):\n")

    """メイン学習処理"""        for model_id, desc in SUPPORTED_MODELS.items():

    logger.info("=" * 60)            marker = " ← デフォルト" if model_id == DEFAULT_MODEL else ""

    logger.info("UTAMEMO 歌詞生成LoRA学習 開始")            print(f"  {model_id:<50} {desc}{marker}")

    logger.info(f"  ベースモデル: {args.model_name}")        print(f"\n例: python train.py --model_name google/gemma-2-9b-it --data_path data/sample_training_data.json\n")

    if torch.cuda.is_available():    else:

        logger.info(f"  GPU数: {torch.cuda.device_count()}")        train(args)

    logger.info("=" * 60)

    # W&B連携
    report_to = "none"
    if args.wandb_project:
        try:
            import wandb  # noqa: F401
            os.environ["WANDB_PROJECT"] = args.wandb_project
            report_to = "wandb"
            logger.info(f"  W&B: {args.wandb_project}")
        except ImportError:
            logger.warning("wandbがインストールされていません。pip install wandb")

    # モデル & トークナイザー
    model, tokenizer = setup_model_and_tokenizer(args.model_name, args.hf_token)

    # データ読み込み
    train_dataset, eval_dataset = load_training_data(args.data_path, tokenizer, args.eval_split)

    # LoRA設定（モデルファミリー自動判定）
    model = setup_lora(model, args.model_name, args.lora_rank, args.lora_alpha)

    # 学習引数
    eval_strategy = "epoch" if eval_dataset else "no"
    load_best = eval_dataset is not None

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        logging_steps=5,
        eval_strategy=eval_strategy,
        save_strategy="epoch",
        save_total_limit=3,
        load_best_model_at_end=load_best,
        metric_for_best_model="eval_loss" if eval_dataset else None,
        greater_is_better=False if eval_dataset else None,
        bf16=True,
        optim="paged_adamw_32bit",
        max_grad_norm=0.3,
        report_to=report_to,
        seed=42,
        # マルチGPU: gradient_checkpointing でVRAM節約
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        # データローダー最適化
        dataloader_num_workers=2,
        dataloader_pin_memory=True,
    )

    # コールバック
    callbacks = []
    if eval_dataset and args.early_stopping_patience > 0:
        callbacks.append(
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience)
        )
        logger.info(f"  Early Stopping: patience={args.early_stopping_patience}")

    # SFTTrainer (Supervised Fine-Tuning)
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        args=training_args,
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_text_field="text",
        packing=True,
        callbacks=callbacks if callbacks else None,
    )

    # 学習実行
    logger.info("学習を開始します...")
    logger.info(f"  エポック数: {args.epochs}")
    logger.info(f"  バッチサイズ: {args.batch_size}")
    logger.info(f"  勾配蓄積: {args.gradient_accumulation}")
    logger.info(f"  実効バッチサイズ: {args.batch_size * args.gradient_accumulation}")
    logger.info(f"  学習率: {args.learning_rate}")
    if eval_dataset:
        logger.info(f"  検証: {len(eval_dataset)} 件 (毎エポック)")

    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    # 保存
    logger.info(f"LoRAアダプタを保存: {args.output_dir}")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    # 学習ログをJSONに保存
    log_history = trainer.state.log_history
    log_path = os.path.join(args.output_dir, "training_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_history, f, ensure_ascii=False, indent=2)
    logger.info(f"学習ログを保存: {log_path}")

    # 学習結果サマリー
    final_loss = None
    final_eval_loss = None
    for entry in reversed(log_history):
        if "loss" in entry and final_loss is None:
            final_loss = entry["loss"]
        if "eval_loss" in entry and final_eval_loss is None:
            final_eval_loss = entry["eval_loss"]

    logger.info("=" * 60)
    logger.info("✅ 学習完了!")
    logger.info(f"   LoRAアダプタ: {args.output_dir}")
    if final_loss:
        logger.info(f"   最終Train Loss: {final_loss:.4f}")
    if final_eval_loss:
        logger.info(f"   最終Eval Loss:  {final_eval_loss:.4f}")
    logger.info("")
    logger.info("次のステップ:")
    logger.info("  1. python test_model.py でテスト")
    logger.info("  2. python serve.py で推論サーバー起動")
    logger.info("=" * 60)


if __name__ == "__main__":
    args = parse_args()
    if args.list_models:
        print("\n対応モデル一覧 (--model_name に指定可能):\n")
        for model_id, desc in SUPPORTED_MODELS.items():
            marker = " ← デフォルト" if model_id == DEFAULT_MODEL else ""
            print(f"  {model_id:<50} {desc}{marker}")
        print(f"\n例: python train.py --model_name google/gemma-2-9b-it --data_path data/sample_training_data.json\n")
        print("マルチGPU (RTX 4080 x2):")
        print("  accelerate launch train.py --data_path data/lyrics_training_data.json\n")
    else:
        if not args.data_path:
            print("エラー: --data_path を指定してください")
            print("例: python train.py --data_path data/sample_training_data.json")
            exit(1)
        train(args)

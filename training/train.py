#!/usr/bin/env python3
"""
UTAMEMO 歌詞生成LoRA学習スクリプト

ベースモデル: meta-llama/Meta-Llama-3-8B-Instruct (デフォルト)
学習方法: QLoRA (4bit量子化 + LoRA)
マルチGPU: RTX 4080 x2 対応 (accelerate / device_map="auto")
自宅GPU: RTX 4060 Ti 16GB でも Llama 3 8B が学習・推論可能

使い方:
  # シングルGPU (RTX 4060 Ti 16GB / 4080 / 4090)
  python train.py --data_path data/lyrics_training_data.json

  # マルチGPU (RTX 4080 x2)
  accelerate launch train.py --data_path data/lyrics_training_data.json

  # サンプルデータで動作確認
  python train.py --data_path data/sample_training_data.json --epochs 5

  # 対応モデル一覧
  python train.py --list_models
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Windows WDDM環境での Access Violation を回避（import前に適用）
try:
    import transformers.modeling_utils as _mu_early
    if hasattr(_mu_early, 'caching_allocator_warmup'):
        _mu_early.caching_allocator_warmup = lambda *a, **kw: None
except Exception:
    pass

import torch

# 注意: peft, trl, datasets, transformers のモデル系クラスは
# メモリ節約のため関数内で遅延importする (ページングファイルエラー対策)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_file_logging(log_path):
    """ファイルへのログ出力を設定（リアルタイム監視用）"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(file_handler)
    logger.info(f"ログファイル: {log_path}")
    logger.info(f"リアルタイム監視: Get-Content -Wait -Tail 30 '{log_path}'")
    return log_path

# =============================================================================
# 設定
# =============================================================================
DEFAULT_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
OUTPUT_DIR = "./output/utamemo-lyrics-lora"
MAX_SEQ_LENGTH = 1024

# 対応モデル一覧 (--model_name にどれでも指定可能)
SUPPORTED_MODELS = {
    # Llama 3 系
    "meta-llama/Meta-Llama-3-8B-Instruct":    "Llama 3 8B (推奨, ~10GB VRAM)",
    "meta-llama/Meta-Llama-3.1-8B-Instruct":  "Llama 3.1 8B (~10GB VRAM)",
    "meta-llama/Meta-Llama-3-70B-Instruct":   "Llama 3 70B (高品質, ~40GB VRAM x2)",
    # Gemma 2 系
    "google/gemma-2-2b-it":                    "Gemma 2 2B (軽量テスト用, ~4GB VRAM)",
    "google/gemma-2-9b-it":                    "Gemma 2 9B (バランス, ~12GB VRAM)",
    "google/gemma-2-27b-it":                   "Gemma 2 27B (高品質, ~20GB VRAM)",
    # Phi 系
    "microsoft/Phi-3.5-mini-instruct":         "Phi 3.5 Mini 3.8B (軽量テスト用, ~5GB VRAM)",
    # Qwen 2.5 系
    "Qwen/Qwen2.5-7B-Instruct":               "Qwen 2.5 7B (~8GB VRAM)",
    "Qwen/Qwen2.5-14B-Instruct":              "Qwen 2.5 14B (~16GB VRAM) ★4060Ti16GB向け",
    "Qwen/Qwen2.5-32B-Instruct":              "Qwen 2.5 32B (~24GB VRAM, 2GPU推奨)",
}

# モデルファミリー別 LoRA target_modules
MODEL_TARGET_MODULES = {
    "llama": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "gemma": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "phi":   ["q_proj", "k_proj", "v_proj", "dense", "fc1", "fc2"],
    "qwen":  ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
}

# GPU別推奨設定
GPU_PRESETS = {
    "4060ti": {
        "description": "RTX 4060 Ti (16GB VRAM)",
        "recommended_models": [
            "meta-llama/Meta-Llama-3-8B-Instruct",
            "google/gemma-2-9b-it",
            "Qwen/Qwen2.5-7B-Instruct",
        ],
        "batch_size": 2,
        "lora_rank": 32,
        "gradient_accumulation": 4,
    },
    "4080": {
        "description": "RTX 4080 (16GB VRAM)",
        "recommended_models": [
            "meta-llama/Meta-Llama-3-8B-Instruct",
            "google/gemma-2-9b-it",
            "Qwen/Qwen2.5-14B-Instruct",
        ],
        "batch_size": 2,
        "lora_rank": 32,
        "gradient_accumulation": 4,
    },
}


def detect_model_family(model_name):
    """モデル名からファミリーを判定"""
    name_lower = model_name.lower()
    if "llama" in name_lower:
        return "llama"
    elif "gemma" in name_lower:
        return "gemma"
    elif "phi" in name_lower:
        return "phi"
    elif "qwen" in name_lower:
        return "qwen"
    else:
        logger.warning(f"Unknown model family for '{model_name}', using llama defaults")
        return "llama"


def detect_gpu_preset():
    """接続中のGPUから推奨プリセットを判定"""
    if not torch.cuda.is_available():
        return None
    gpu_name = torch.cuda.get_device_name(0).lower()
    if "4060" in gpu_name:
        return "4060ti"
    elif "4080" in gpu_name:
        return "4080"
    return None


def parse_args():
    parser = argparse.ArgumentParser(description="UTAMEMO LoRA学習")
    parser.add_argument(
        "--model_name", type=str, default=DEFAULT_MODEL,
        help="ベースモデル名 (Hugging Face Hub). --list_models で一覧表示"
    )
    parser.add_argument(
        "--list_models", action="store_true",
        help="対応モデル一覧を表示して終了"
    )
    parser.add_argument(
        "--data_path", type=str, default=None,
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
        "--batch_size", type=int, default=None,
        help="バッチサイズ (未指定時はGPUに応じて自動設定)"
    )
    parser.add_argument(
        "--learning_rate", type=float, default=2e-4,
        help="学習率"
    )
    parser.add_argument(
        "--lora_rank", type=int, default=None,
        help="LoRAのランク (未指定時はGPUに応じて自動設定: 4060Ti=16, 4080=32)"
    )
    parser.add_argument(
        "--lora_alpha", type=int, default=None,
        help="LoRAのalpha (未指定時はrankの2倍)"
    )
    parser.add_argument(
        "--gradient_accumulation", type=int, default=None,
        help="勾配蓄積ステップ数 (未指定時はGPUに応じて自動設定)"
    )
    parser.add_argument(
        "--eval_split", type=float, default=0.1,
        help="検証データの割合 (0.0で検証なし, 0.1で10%%を検証用)"
    )
    parser.add_argument(
        "--early_stopping_patience", type=int, default=3,
        help="Early Stoppingの忍耐回数 (0で無効)"
    )
    parser.add_argument(
        "--wandb_project", type=str, default="",
        help="W&Bプロジェクト名 (空で無効, 例: 'utamemo-lyrics')"
    )
    parser.add_argument(
        "--hf_token", type=str, default=None,
        help="Hugging Faceのアクセストークン (Llamaモデルのダウンロードに必要)"
    )
    parser.add_argument(
        "--resume_from_checkpoint", type=str, default=None,
        help="チェックポイントから学習再開 (パスを指定)"
    )
    parser.add_argument(
        "--report_url", type=str, default=None,
        help="UTAMEMOダッシュボードへの進捗通知URL (例: https://utamemo.com/api/training/update/)"
    )
    parser.add_argument(
        "--api_key", type=str, default=None,
        help="トレーニング監視APIキー (環境変数 UTAMEMO_TRAINING_API_KEY でも可)"
    )
    return parser.parse_args()


# =============================================================================
# リモート監視レポーター
# =============================================================================

class TrainingReporter:
    """UTAMEMOダッシュボードへトレーニング進捗を送信"""

    def __init__(self, report_url=None, api_key=None):
        self.report_url = report_url
        self.api_key = api_key or os.getenv('UTAMEMO_TRAINING_API_KEY', '')
        self.enabled = bool(self.report_url and self.api_key)
        self._log_lines = []
        self._max_log_lines = 50

        if self.enabled:
            logger.info(f"リモート監視: {self.report_url}")
        else:
            logger.info("リモート監視: 無効 (--report_url と --api_key を設定で有効化)")

    def _get_machine_info(self):
        import platform
        import socket
        hostname = platform.node()
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = None
        return hostname, ip

    def _get_gpu_info(self):
        if not torch.cuda.is_available():
            return {}, {}
        try:
            name = torch.cuda.get_device_name(0)
            used = torch.cuda.memory_allocated(0) / 1024**3
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            return {'gpu_name': name, 'gpu_memory_used': round(used, 1), 'gpu_memory_total': round(total, 1)}, {}
        except Exception:
            return {}, {}

    def add_log(self, message):
        self._log_lines.append(message)
        if len(self._log_lines) > self._max_log_lines:
            self._log_lines = self._log_lines[-self._max_log_lines:]

    def send(self, **kwargs):
        """サーバーに進捗を送信し、コマンドを返す (poll=True)"""
        if not self.enabled:
            return 'none'
        import urllib.request
        import urllib.error

        hostname, ip = self._get_machine_info()
        gpu_info, _ = self._get_gpu_info()

        payload = {
            'machine_name': hostname,
            'machine_ip': ip,
            'poll': True,
            'log_tail': '\n'.join(self._log_lines[-30:]),
            **gpu_info,
            **kwargs,
        }

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.report_url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'X-Training-Api-Key': self.api_key,
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                cmd = result.get('command', 'none')
                if cmd == 'stop':
                    logger.info("停止コマンドを受信しました")
                return cmd
        except Exception as e:
            logger.debug(f"レポート送信失敗: {e}")
            return 'none'


# =============================================================================
# システムプロンプト
# =============================================================================
SYSTEM_PROMPT = (
    "あなたは暗記学習用の歌詞を作成する専門AIです。"
    "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"
    "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
)


def format_training_example(example, tokenizer):
    """学習データをモデルのチャットフォーマットに変換

    tokenizer.apply_chat_template() を使うため、
    Llama 3 / Gemma 2 / Phi / Qwen 等どのモデルでも正しいフォーマットになる。
    """
    instruction = example["instruction"]
    input_text = example.get("input", "")
    output_text = example["output"]

    if input_text:
        user_message = f"{instruction}\n\n■ 学習テキスト\n{input_text}"
    else:
        user_message = instruction

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": output_text},
    ]

    try:
        formatted = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
    except Exception:
        messages_no_sys = [
            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_message}"},
            {"role": "assistant", "content": output_text},
        ]
        formatted = tokenizer.apply_chat_template(
            messages_no_sys, tokenize=False, add_generation_prompt=False
        )

    return formatted


def load_training_data(data_path, tokenizer, eval_split=0.1):
    """学習データを読み込み、train/eval分割"""
    from datasets import Dataset
    logger.info(f"学習データを読み込み: {data_path}")

    with open(data_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    logger.info(f"  {len(raw_data)} 件のデータを読み込みました")

    # 品質フィルタリング
    filtered = []
    for example in raw_data:
        quality = example.get("_meta", {}).get("quality", 1.0)
        if quality >= 0.3:
            filtered.append(example)
        else:
            logger.debug(f"  低品質データをスキップ (quality={quality})")

    if len(filtered) < len(raw_data):
        logger.info(f"  品質フィルタ: {len(raw_data)} -> {len(filtered)} 件 ({len(raw_data) - len(filtered)} 件除外)")
    raw_data = filtered

    formatted_texts = []
    for example in raw_data:
        text = format_training_example(example, tokenizer)
        formatted_texts.append({"text": text})

    dataset = Dataset.from_list(formatted_texts)

    if eval_split > 0 and len(dataset) >= 10:
        split = dataset.train_test_split(test_size=eval_split, seed=42)
        train_dataset = split["train"]
        eval_dataset = split["test"]
        logger.info(f"  Train: {len(train_dataset)} 件, Eval: {len(eval_dataset)} 件")
        return train_dataset, eval_dataset
    else:
        logger.info(f"  Dataset: {len(dataset)} 件 (検証データなし)")
        return dataset, None


def setup_model_and_tokenizer(model_name, hf_token=None):
    """4bit量子化でモデルとトークナイザーをロード"""
    import gc
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import prepare_model_for_kbit_training

    # モデルロード前にメモリを最大限解放
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    logger.info(f"モデルをロード: {model_name}")

    # Windows WDDM環境でのAccess Violationを回避
    try:
        import transformers.modeling_utils as _mu
        if hasattr(_mu, 'caching_allocator_warmup'):
            _mu.caching_allocator_warmup = lambda *a, **kw: None
            logger.info("  caching_allocator_warmup をパッチ済み (Windows WDDM対策)")
    except Exception:
        pass

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        token=hf_token,
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        max_memory={0: "14GiB", "cpu": "1GiB"},
        token=hf_token,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        offload_folder="offload",
        low_cpu_mem_usage=True,
    )

    model = prepare_model_for_kbit_training(model)

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            gpu_name = torch.cuda.get_device_name(i)
            gpu_mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
            logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f} GB)")
        if torch.cuda.device_count() > 1:
            logger.info(f"  -> マルチGPU検出: {torch.cuda.device_count()}台で自動分散")
    else:
        logger.warning("  GPUが検出されません！CPUモードで動作します")

    logger.info("  モデルロード完了")
    return model, tokenizer


def setup_lora(model, model_name, lora_rank, lora_alpha):
    """LoRAアダプタを設定（モデルファミリー自動判定）"""
    from peft import LoraConfig, get_peft_model, TaskType

    family = detect_model_family(model_name)
    target_modules = MODEL_TARGET_MODULES.get(family, MODEL_TARGET_MODULES["llama"])

    logger.info(f"LoRA設定: rank={lora_rank}, alpha={lora_alpha}, family={family}")
    logger.info(f"  target_modules: {target_modules}")

    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=target_modules,
    )

    model = get_peft_model(model, lora_config)

    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    logger.info(
        f"  学習可能パラメータ: {trainable_params:,} / {total_params:,} "
        f"({100 * trainable_params / total_params:.2f}%%)"
    )

    return model


def train(args):
    """メイン学習処理"""
    from trl import SFTTrainer, SFTConfig
    from transformers import TrainerCallback

    logger.info("=" * 60)
    logger.info("UTAMEMO 歌詞生成LoRA学習 開始")
    logger.info(f"  ベースモデル: {args.model_name}")
    if torch.cuda.is_available():
        logger.info(f"  GPU数: {torch.cuda.device_count()}")
    logger.info("=" * 60)

    # GPU自動検出
    gpu_preset = detect_gpu_preset()
    if gpu_preset:
        preset = GPU_PRESETS[gpu_preset]
        logger.info(f"  GPU検出: {preset['description']}")

    # GPU別デフォルト値の適用
    if args.batch_size is None:
        args.batch_size = GPU_PRESETS.get(gpu_preset, {}).get("batch_size", 2)
    if args.lora_rank is None:
        args.lora_rank = GPU_PRESETS.get(gpu_preset, {}).get("lora_rank", 32)
    if args.lora_alpha is None:
        args.lora_alpha = args.lora_rank * 2
    if args.gradient_accumulation is None:
        args.gradient_accumulation = GPU_PRESETS.get(gpu_preset, {}).get("gradient_accumulation", 4)

    # W&B連携
    report_to = "none"
    if args.wandb_project:
        try:
            import wandb
            os.environ["WANDB_PROJECT"] = args.wandb_project
            report_to = "wandb"
            logger.info(f"  W&B: {args.wandb_project}")
        except ImportError:
            logger.warning("wandbがインストールされていません。pip install wandb")

    # リモート監視
    reporter = TrainingReporter(
        report_url=args.report_url,
        api_key=args.api_key,
    )
    reporter.add_log("モデルをロード中...")
    reporter.send(
        status='loading',
        model_name=args.model_name,
        total_epochs=args.epochs,
        training_config={
            'batch_size': args.batch_size,
            'learning_rate': args.learning_rate,
            'lora_rank': args.lora_rank,
            'lora_alpha': args.lora_alpha,
            'gradient_accumulation': args.gradient_accumulation,
            'max_seq_length': MAX_SEQ_LENGTH,
        },
    )

    model, tokenizer = setup_model_and_tokenizer(args.model_name, args.hf_token)
    train_dataset, eval_dataset = load_training_data(args.data_path, tokenizer, args.eval_split)
    model = setup_lora(model, args.model_name, args.lora_rank, args.lora_alpha)

    eval_strategy = "epoch" if eval_dataset else "no"

    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        warmup_steps=10,
        lr_scheduler_type="cosine",
        logging_steps=5,
        eval_strategy=eval_strategy,
        save_strategy="no",
        load_best_model_at_end=False,
        bf16=True,
        optim="adamw_torch",
        max_grad_norm=0.3,
        report_to=report_to,
        seed=42,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_num_workers=0,
        dataloader_pin_memory=False,
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_text_field="text",
        packing=True,
    )

    # ログファイル設定
    log_file = os.path.join(args.output_dir, "training_progress.log")
    setup_file_logging(log_file)

    class ProgressCallback(TrainerCallback):
        """エポック完了時にログファイル・リモートダッシュボードへ書き出すコールバック"""
        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                parts = []
                for k, v in logs.items():
                    if isinstance(v, float):
                        parts.append(f"{k}={v:.4f}")
                    else:
                        parts.append(f"{k}={v}")
                msg = "  ".join(parts)
                logger.info(msg)
                reporter.add_log(msg)

                # ログ送信時に停止コマンドをチェック
                cmd = reporter.send(
                    status='training',
                    train_loss=logs.get('loss'),
                )
                if cmd == 'stop':
                    logger.info("停止コマンド受信: 学習を中断します...")
                    reporter.add_log("停止コマンドで学習中断")
                    control.should_training_stop = True

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            if metrics:
                epoch = metrics.get("epoch", "?")
                eval_loss = metrics.get("eval_loss", 0)
                accuracy = metrics.get("eval_mean_token_accuracy", 0)
                msg = f"[Epoch {epoch}] eval_loss={eval_loss:.4f}  accuracy={accuracy*100:.1f}%"
                logger.info(msg)
                reporter.add_log(msg)
                try:
                    epoch_int = int(float(epoch))
                except (ValueError, TypeError):
                    epoch_int = 0
                cmd = reporter.send(
                    status='training',
                    current_epoch=epoch_int,
                    eval_loss=eval_loss,
                    accuracy=round(accuracy * 100, 1),
                )
                if cmd == 'stop':
                    logger.info("停止コマンド受信: 学習を中断します...")
                    reporter.add_log("停止コマンドで学習中断")
                    control.should_training_stop = True

        def on_train_end(self, args, state, control, **kwargs):
            logger.info("学習ループ完了。モデル保存に進みます...")
            reporter.add_log("学習ループ完了。モデル保存中...")
            reporter.send(status='saving')

    callbacks = [ProgressCallback()]

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        args=training_args,
        callbacks=callbacks if callbacks else None,
    )

    logger.info("学習を開始します...")
    logger.info(f"  エポック数: {args.epochs}")
    logger.info(f"  バッチサイズ: {args.batch_size}")
    logger.info(f"  勾配蓄積: {args.gradient_accumulation}")
    logger.info(f"  実効バッチサイズ: {args.batch_size * args.gradient_accumulation}")
    logger.info(f"  学習率: {args.learning_rate}")
    logger.info(f"  LoRA rank: {args.lora_rank}, alpha: {args.lora_alpha}")
    if eval_dataset:
        logger.info(f"  検証: {len(eval_dataset)} 件 (毎エポック)")

    reporter.add_log(f"学習開始: {args.epochs}エポック, batch={args.batch_size}")
    reporter.send(status='training', current_epoch=0)

    try:
        trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"学習中にエラー: {error_msg}")
        reporter.add_log(f"ERROR: {error_msg}")
        reporter.send(status='failed', error_message=error_msg[:1000])
        raise

    # trainerからログを先に退避
    log_history = trainer.state.log_history

    # trainer・optimizer等を削除してメモリ解放
    import gc
    del trainer
    gc.collect()
    torch.cuda.empty_cache()
    gc.collect()

    # モデルをCPUに移動してGPUメモリを完全解放
    model = model.cpu()
    torch.cuda.empty_cache()
    gc.collect()

    logger.info(f"LoRAアダプタを保存: {args.output_dir}")
    model.save_pretrained(args.output_dir, safe_serialization=False)
    tokenizer.save_pretrained(args.output_dir)
    log_path = os.path.join(args.output_dir, "training_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_history, f, ensure_ascii=False, indent=2)
    logger.info(f"学習ログを保存: {log_path}")

    final_loss = None
    final_eval_loss = None
    for entry in reversed(log_history):
        if "loss" in entry and final_loss is None:
            final_loss = entry["loss"]
        if "eval_loss" in entry and final_eval_loss is None:
            final_eval_loss = entry["eval_loss"]

    logger.info("=" * 60)
    logger.info("学習完了!")
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

    reporter.add_log(f"学習完了! Train Loss={final_loss}, Eval Loss={final_eval_loss}")
    reporter.send(
        status='completed',
        train_loss=final_loss,
        eval_loss=final_eval_loss,
    )


if __name__ == "__main__":
    args = parse_args()
    if args.list_models:
        print("\n対応モデル一覧 (--model_name に指定可能):\n")
        for model_id, desc in SUPPORTED_MODELS.items():
            marker = " <- デフォルト" if model_id == DEFAULT_MODEL else ""
            print(f"  {model_id:<50} {desc}{marker}")
        print()
        print("GPU別おすすめ:")
        print("  RTX 4060 Ti 16GB: Llama 3 8B, Gemma 2 9B, Qwen 2.5 7B")
        print("  RTX 4080 (16GB):  Llama 3 8B, Gemma 2 9B, Qwen 2.5 14B")
        print("  RTX 4080 x2:      Qwen 2.5 32B, Gemma 2 27B")
        print()
        print("例:")
        print("  # 自宅 RTX 4060 Ti 16GB (デフォルト設定でOK)")
        print("  python train.py --data_path data/lyrics_training_data.json")
        print()
        print("  # 学校 RTX 4080 x2")
        print("  accelerate launch train.py --data_path data/lyrics_training_data.json")
        print()
    else:
        if not args.data_path:
            print("エラー: --data_path を指定してください")
            print("例: python train.py --data_path data/sample_training_data.json")
            exit(1)
        log_file = os.path.join(args.output_dir, "training_progress.log")
        print(f"\n📊 トレーニング進捗をリアルタイム確認するには、別ターミナルで:")
        print(f"   Get-Content -Wait -Tail 30 '{log_file}'\n")
        train(args)

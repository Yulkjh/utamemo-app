#!/usr/bin/env python3
"""
UTAMEMO 歌詞生成 推論サーバー

学習済みLoRAモデルを使って歌詞生成APIを提供する。
UTAMEMOのRender.comサーバーからHTTP APIで呼び出される。

推論エンジン:
  1. transformers (デフォルト) - QLoRA + PEFT
  2. vLLM (--engine vllm) - 高速推論 (連続バッチ処理、PagedAttention)

使い方 (学校のGPU PCで):
  # transformers (デフォルト)
  python serve.py
  python serve.py --port 8000 --host 0.0.0.0

  # vLLM 高速推論モード (LoRAマージ済みモデルが必要)
  python serve.py --engine vllm --base_model ./output/merged-model

エンドポイント:
  POST /generate
    Body: {"text": "学習テキスト", "genre": "pop", "language_mode": "japanese"}
    Response: {"lyrics": "生成された歌詞", "status": "success"}

  GET /health
    Response: {"status": "ok", "model": "utamemo-lyrics-lora", "gpu": "..."}
"""

import argparse
import json
import logging
import sys
import time

import torch

# PyTorchがimport時に警告ハンドラを上書きするため、torch importの後に設定
import warnings
warnings.filterwarnings("ignore", message=".*triton.*")

from flask import Flask, request, jsonify
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# グローバル変数 (起動時にロード)
model = None
tokenizer = None
vllm_engine = None  # vLLMエンジン (--engine vllm 時のみ)
inference_engine = "transformers"  # "transformers" or "vllm"

DEFAULT_LORA_PATH = "./output/utamemo-lyrics-lora"
DEFAULT_BASE_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"

# 対応モデル例 (--base_model にどれでも指定可能)
# Llama 3:  meta-llama/Meta-Llama-3-8B-Instruct
# Gemma 2:  google/gemma-2-2b-it, google/gemma-2-9b-it, google/gemma-2-27b-it
# Phi 3.5:  microsoft/Phi-3.5-mini-instruct
# Qwen 2.5: Qwen/Qwen2.5-7B-Instruct

# 起動中のモデル名 (health エンドポイントで表示用)
loaded_base_model = ""
loaded_lora_path = ""

# APIキー (環境変数 UTAMEMO_API_KEY で設定、未設定なら起動時にエラー)
import os
API_KEY = os.environ.get("UTAMEMO_API_KEY", "")


def load_model(base_model_name, lora_path, hf_token=None, no_lora=False):
    """モデルをロード
    
    Args:
        base_model_name: ベースモデル (Llama 3 / Gemma 2 / Phi / Qwen 等)
        lora_path: LoRAアダプタのパス
        hf_token: Hugging Face トークン
        no_lora: True の場合、LoRA無しでベースモデルのみ起動
    """
    global model, tokenizer, loaded_base_model, loaded_lora_path

    logger.info(f"モデルをロード: {base_model_name}")
    if not no_lora:
        logger.info(f"  LoRA: {lora_path}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model_name, token=hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        max_memory={0: "14GiB", "cpu": "1GiB"},
        token=hf_token,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )

    if no_lora:
        model = base_model
        loaded_lora_path = "(none)"
        logger.info("✅ ベースモデルのみロード完了 (LoRA無し)")
    else:
        model = PeftModel.from_pretrained(base_model, lora_path)
        loaded_lora_path = lora_path
        logger.info("✅ モデル + LoRA ロード完了")

    model.eval()
    loaded_base_model = base_model_name


def load_vllm_model(model_path, hf_token=None):
    """vLLMエンジンでモデルをロード (高速推論)
    
    vLLMを使う場合はLoRAをマージ済みのモデルが必要。
    マージ方法: python -c "
        from peft import PeftModel
        from transformers import AutoModelForCausalLM
        base = AutoModelForCausalLM.from_pretrained('meta-llama/Meta-Llama-3-8B-Instruct')
        model = PeftModel.from_pretrained(base, './output/utamemo-lyrics-lora')
        merged = model.merge_and_unload()
        merged.save_pretrained('./output/merged-model')
    "
    """
    global vllm_engine, tokenizer, loaded_base_model, loaded_lora_path, inference_engine

    try:
        from vllm import LLM, SamplingParams  # noqa: F401
    except ImportError:
        logger.error("vLLMがインストールされていません。pip install vllm")
        sys.exit(1)

    logger.info(f"vLLMでモデルをロード: {model_path}")
    
    from transformers import AutoTokenizer as AT
    tokenizer = AT.from_pretrained(model_path, token=hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # vLLMエンジン初期化 (マルチGPU自動検出)
    gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 1
    vllm_engine = LLM(
        model=model_path,
        tokenizer=model_path,
        tensor_parallel_size=min(gpu_count, 2),  # 最大2GPU
        dtype="bfloat16",
        max_model_len=2048,
        gpu_memory_utilization=0.85,
    )
    
    inference_engine = "vllm"
    loaded_base_model = model_path
    loaded_lora_path = "(vllm-merged)"
    logger.info(f"✅ vLLMモデルロード完了 (GPU: {gpu_count}台)")


# =============================================================================
# 言語モード別システムプロンプト
# =============================================================================

SYSTEM_PROMPTS = {
    "japanese": (
        "あなたは暗記学習用の歌詞を作成する専門AIです。"
        "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい日本語の歌詞を生成します。"
        "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
        "内容を詰め込み情報量を最優先します。(ヘイ！)(Yeah!)等の無意味な掛け声や内容と無関係なフレーズは使いません。"
        "「歌で覚えよう」「覚えよう」「暗記しよう」等の学習行為を促すメタ的な表現は使わず、学習内容そのものを歌詞にしてください。"
        "「全てが大事」「忘れずに」「大切だよ」「テストに出る」等の励ましや心構えのフレーズも禁止です。"
    ),
    "english_vocab": (
        "You are an expert AI that creates study song lyrics for memorization. "
        "Given English vocabulary or text, create Japanese lyrics that help memorize English words. "
        "Include the English words directly in the lyrics with Japanese meanings. "
        "Format: 'English word 日本語の意味' pattern for easy memorization."
    ),
    "english": (
        "You are an expert AI that creates study song lyrics in English for memorization. "
        "Given study material, create catchy English lyrics with rhymes. "
        "Include key terms, names, dates, and formulas accurately in the lyrics."
    ),
    "chinese": (
        "你是一位专业的学习歌词创作AI。"
        "根据给定的学习文本，创作押韵、朗朗上口、便于记忆的中文歌词。"
        "重要的术语、人名、年份、化学式等必须准确地包含在歌词中。"
    ),
    "chinese_vocab": (
        "你是一位专业的学习歌词创作AI。"
        "根据给定的中文词汇，创作帮助记忆中文单词的日语歌词。"
        "在歌词中直接使用中文词汇并附上日语解释。"
    ),
}

DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPTS["japanese"]


def _get_user_prompt(study_text, genre, language_mode, custom_request=""):
    """言語モードに応じたユーザープロンプトを生成"""
    
    custom_section = ""
    if custom_request:
        custom_section = f"\n\n■ ユーザーからの追加リクエスト（重要！必ず反映してください）\n{custom_request}"
    
    if language_mode == "english_vocab":
        return (
            f"以下の英語テキストから{genre}ジャンルの日本語歌詞を作成してください。\n"
            f"英単語をそのまま歌詞に入れ、直後に日本語の意味を添えてください。\n"
            f"例：「apple りんご」「beautiful 美しい」\n"
            f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
            f"■ 学習テキスト\n{study_text}"
            f"{custom_section}"
        )
    elif language_mode == "english":
        return (
            f"Create {genre} genre study song lyrics in English from the following text.\n"
            f"Make it rhyme, catchy and easy to memorize.\n"
            f"Include key terms, names, dates accurately.\n"
            f"Output only lyrics with section labels [Verse 1], [Chorus], [Verse 2] etc.\n\n"
            f"■ Study Text\n{study_text}"
            f"{custom_section}"
        )
    elif language_mode == "chinese":
        return (
            f"请根据以下学习文本创作{genre}风格的中文歌词。\n"
            f"要押韵、朗朗上口、便于记忆。\n"
            f"重要术语、人名、年份必须准确包含。\n"
            f"输出格式：[Verse 1], [Chorus], [Verse 2] 等。\n\n"
            f"■ 学习文本\n{study_text}"
            f"{custom_section}"
        )
    elif language_mode == "chinese_vocab":
        return (
            f"以下の中国語テキストから{genre}ジャンルの日本語歌詞を作成してください。\n"
            f"中国語の単語をそのまま歌詞に入れ、日本語の意味を添えてください。\n"
            f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
            f"■ 学習テキスト\n{study_text}"
            f"{custom_section}"
        )
    else:  # japanese (default)
        return (
            f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
            f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
            f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
            f"「歌で覚えよう」「覚えよう」等の学習を促す表現は使わず、学習内容そのものを歌詞にしてください。\n"
            f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
            f"■ 学習テキスト\n{study_text}"
            f"{custom_section}"
        )


def generate_lyrics(study_text, genre="pop", language_mode="japanese", custom_request=""):
    """歌詞を生成 — 言語モード対応、推論エンジン自動選択"""
    system_prompt = SYSTEM_PROMPTS.get(language_mode, DEFAULT_SYSTEM_PROMPT)
    user_prompt = _get_user_prompt(study_text, genre, language_mode, custom_request)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if inference_engine == "vllm":
        return _generate_with_vllm(messages)
    else:
        return _generate_with_transformers(messages)


def _generate_with_transformers(messages):
    """transformers + PEFT で推論"""
    input_ids = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            input_ids,
            max_new_tokens=1024,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            repetition_penalty=1.1,
            eos_token_id=tokenizer.eos_token_id,
        )

    response = tokenizer.decode(outputs[0][input_ids.shape[-1]:], skip_special_tokens=True)
    return response.strip()


def _generate_with_vllm(messages):
    """vLLMエンジンで高速推論"""
    from vllm import SamplingParams

    prompt = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=False
    )

    sampling_params = SamplingParams(
        max_tokens=1024,
        temperature=0.7,
        top_p=0.9,
        repetition_penalty=1.1,
    )

    outputs = vllm_engine.generate([prompt], sampling_params)
    return outputs[0].outputs[0].text.strip()


# =============================================================================
# API エンドポイント
# =============================================================================

@app.before_request
def check_api_key():
    """APIキー認証 (healthチェック以外)"""
    if request.endpoint == 'health_check':
        return None

    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing Authorization header"}), 401

    token = auth_header[7:]
    if token != API_KEY:
        return jsonify({"error": "Invalid API key"}), 403


@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェック"""
    gpu_info = "N/A"
    if torch.cuda.is_available():
        gpu_info = torch.cuda.get_device_name(0)
        gpu_mem_used = torch.cuda.memory_allocated(0) / 1024**3
        gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        gpu_info = f"{gpu_info} ({gpu_mem_used:.1f}/{gpu_mem_total:.1f} GB)"

    return jsonify({
        "status": "ok",
        "engine": inference_engine,
        "base_model": loaded_base_model,
        "lora": loaded_lora_path,
        "gpu": gpu_info,
    })


@app.route('/generate', methods=['POST'])
def generate():
    """歌詞生成API"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        study_text = data.get('text', '')
        if not study_text:
            return jsonify({"error": "'text' field required"}), 400

        genre = data.get('genre', 'pop')
        language_mode = data.get('language_mode', 'japanese')
        custom_request = data.get('custom_request', '')

        logger.info(f"歌詞生成リクエスト: {len(study_text)} 文字, genre={genre}")

        start_time = time.time()
        lyrics = generate_lyrics(study_text, genre, language_mode, custom_request)
        elapsed = time.time() - start_time

        logger.info(f"歌詞生成完了: {len(lyrics)} 文字, {elapsed:.1f}秒")

        return jsonify({
            "status": "success",
            "lyrics": lyrics,
            "generation_time": round(elapsed, 2),
        })

    except Exception as e:
        logger.error(f"歌詞生成エラー: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": str(e),
        }), 500


# =============================================================================
# メイン
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="UTAMEMO 歌詞生成 推論サーバー",
        epilog=(
            "対応モデル例:\n"
            "  Llama 3:  meta-llama/Meta-Llama-3-8B-Instruct\n"
            "  Gemma 2:  google/gemma-2-2b-it, google/gemma-2-9b-it\n"
            "  Phi 3.5:  microsoft/Phi-3.5-mini-instruct\n"
            "  Qwen 2.5: Qwen/Qwen2.5-7B-Instruct\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base_model", type=str, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--lora_path", type=str, default=DEFAULT_LORA_PATH)
    parser.add_argument("--no_lora", action="store_true",
                        help="LoRA無しでベースモデルのみ起動 (ファインチューン前のテスト用)")
    parser.add_argument("--engine", type=str, default="transformers",
                        choices=["transformers", "vllm"],
                        help="推論エンジン: transformers (デフォルト) or vllm (高速)")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--hf_token", type=str, default=None)
    args = parser.parse_args()

    # APIキー必須チェック
    if not API_KEY:
        logger.error("❌ UTAMEMO_API_KEY 環境変数が設定されていません！")
        logger.error("   export UTAMEMO_API_KEY='ランダムな文字列' を実行してください")
        sys.exit(1)

    # モデルロード
    if args.engine == "vllm":
        load_vllm_model(args.base_model, args.hf_token)
    else:
        load_model(args.base_model, args.lora_path, args.hf_token, no_lora=args.no_lora)

    # サーバー起動
    lora_info = "無し (ベースモデルのみ)" if args.no_lora else args.lora_path
    if args.engine == "vllm":
        lora_info = "(vLLM merged)"
    logger.info(f"推論サーバー起動: http://{args.host}:{args.port}")
    logger.info(f"  エンジン:       {args.engine}")
    logger.info(f"  ベースモデル:   {args.base_model}")
    logger.info(f"  LoRA:          {lora_info}")
    logger.info(f"  POST /generate  - 歌詞生成 (language_mode対応: japanese/english/english_vocab/chinese/chinese_vocab)")
    logger.info(f"  GET  /health    - ヘルスチェック")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
UTAMEMO 歌詞生成 推論サーバー

学習済みLoRAモデルを使って歌詞生成APIを提供する。
UTAMEMOのRender.comサーバーからHTTP APIで呼び出される。

使い方 (学校のGPU PCで):
  python serve.py
  python serve.py --port 8000 --host 0.0.0.0

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
import time

import torch
from flask import Flask, request, jsonify
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# グローバル変数 (起動時にロード)
model = None
tokenizer = None

DEFAULT_LORA_PATH = "./output/utamemo-lyrics-lora"
DEFAULT_BASE_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"

# APIキー (環境変数 UTAMEMO_API_KEY で設定)
import os
API_KEY = os.environ.get("UTAMEMO_API_KEY", "change-me-in-production")


def load_model(base_model_name, lora_path, hf_token=None):
    """モデルをロード"""
    global model, tokenizer

    logger.info(f"モデルをロード: {base_model_name} + {lora_path}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model_name, token=hf_token)
    tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        token=hf_token,
        torch_dtype=torch.bfloat16,
    )

    model = PeftModel.from_pretrained(base_model, lora_path)
    model.eval()

    logger.info("✅ モデルロード完了")


def generate_lyrics(study_text, genre="pop", language_mode="japanese", custom_request=""):
    """歌詞を生成"""
    system_prompt = (
        "あなたは暗記学習用の歌詞を作成する専門AIです。"
        "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい歌詞を生成します。"
        "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
    )

    custom_section = ""
    if custom_request:
        custom_section = f"\n\n■ ユーザーからの追加リクエスト\n{custom_request}"

    user_prompt = (
        f"あなたは暗記学習用の歌詞作成の専門家です。"
        f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
        f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
        f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
        f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
        f"■ 学習テキスト\n{study_text}"
        f"{custom_section}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

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
        gpu_mem_total = torch.cuda.get_device_properties(0).total_mem / 1024**3
        gpu_info = f"{gpu_info} ({gpu_mem_used:.1f}/{gpu_mem_total:.1f} GB)"

    return jsonify({
        "status": "ok",
        "model": "utamemo-lyrics-lora",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--base_model", type=str, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--lora_path", type=str, default=DEFAULT_LORA_PATH)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--hf_token", type=str, default=None)
    args = parser.parse_args()

    # モデルロード
    load_model(args.base_model, args.lora_path, args.hf_token)

    # サーバー起動
    logger.info(f"推論サーバー起動: http://{args.host}:{args.port}")
    logger.info(f"  POST /generate  - 歌詞生成")
    logger.info(f"  GET  /health    - ヘルスチェック")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

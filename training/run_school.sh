#!/bin/bash
# =============================================================================
#   UTAMEMO Training - 学校Linux PC (RTX 4080 x2)
# =============================================================================
#
# 使い方:
#   chmod +x run_school.sh
#   ./run_school.sh
#
# SSH経由で実行する場合:
#   ssh user@school-pc "cd ~/utamemo-training && ./run_school.sh"
#
# バックグラウンドで実行 (SSH切断しても継続):
#   nohup ./run_school.sh > run.log 2>&1 &
#   # もしくは
#   tmux new -s train './run_school.sh'
#
# =============================================================================

set -e

# ── 色付きログ ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================================"
echo "  UTAMEMO Training - 学校Linux PC (RTX 4080 x2)"
echo "============================================================"
echo ""

# ── 設定 ──────────────────────────────────────────────────────────
# ダッシュボードURL (Render.comのURL)
REPORT_URL="${REPORT_URL:-https://utamemo.onrender.com/api/training/update/}"

# APIキー (環境変数 or ここに直接設定)
UTAMEMO_TRAINING_API_KEY="${UTAMEMO_TRAINING_API_KEY:-ここにAPIキーを貼る}"
export UTAMEMO_TRAINING_API_KEY

# モデル (4080 x2 なら 14B or 32B がおすすめ)
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-14B-Instruct}"

# 出力先
OUTPUT_DIR="${OUTPUT_DIR:-./output/utamemo-lyrics-lora}"

# エポック数
EPOCHS="${EPOCHS:-5}"

# バッチサイズ (4080 SUPER x2 なら 1 が安定)
BATCH_SIZE="${BATCH_SIZE:-1}"

# 勾配蓄積 (実効バッチ = BATCH_SIZE x GRAD_ACCUM = 8)
GRAD_ACCUM="${GRAD_ACCUM:-8}"

# LoRAランク (4080 SUPER x2 なら 64 推奨)
LORA_RANK="${LORA_RANK:-64}"

# Hugging Face トークン (Llamaモデル使用時に必要)
HF_TOKEN="${HF_TOKEN:-}"

# ── GPU確認 ──────────────────────────────────────────────────────
log_info "GPU確認中..."
if command -v nvidia-smi &> /dev/null; then
    echo ""
    nvidia-smi --query-gpu=index,name,memory.total,memory.free,driver_version \
               --format=csv,noheader
    echo ""

    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)
    log_info "検出GPU数: ${GPU_COUNT}"

    if [ "$GPU_COUNT" -ge 2 ]; then
        log_info "マルチGPU検出! device_map=auto で自動分散します"
    fi
else
    log_error "nvidia-smi が見つかりません。NVIDIAドライバを確認してください"
    exit 1
fi

# ── Python環境 ───────────────────────────────────────────────────
if [ -f "venv/bin/activate" ]; then
    log_info "venv を使用します"
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    log_info ".venv を使用します"
    source .venv/bin/activate
elif command -v conda &> /dev/null && conda info --envs | grep -q utamemo; then
    log_info "conda utamemo 環境を使用します"
    conda activate utamemo
else
    log_warn "仮想環境が見つかりません。システムPythonを使用します"
fi

PYTHON=$(which python3 || which python)
log_info "Python: $($PYTHON --version)"

# ── 学習データ同期 (双方向) ───────────────────────────────────────
log_info "utamemo.com と学習データを双方向同期中..."
BASE_URL="${REPORT_URL%/api/training/update/}"
$PYTHON sync_data.py sync \
    --api_key "$UTAMEMO_TRAINING_API_KEY" \
    --base_url "$BASE_URL"

if [ $? -eq 0 ]; then
    log_info "データ同期完了!"
else
    log_warn "データ同期に失敗しました。ローカルデータで続行します。"
fi

# ── 学習データ確認 ───────────────────────────────────────────────
if [ ! -f "data/lyrics_training_data.json" ]; then
    log_error "data/lyrics_training_data.json が見つかりません"
    log_error "training/ フォルダに移動して実行してください"
    exit 1
fi

DATA_COUNT=$(python3 -c "import json; print(len(json.load(open('data/lyrics_training_data.json'))))")
log_info "学習データ: ${DATA_COUNT} 件"

# ── 設定表示 ─────────────────────────────────────────────────────
echo ""
echo "┌────────────────────────────────────────────┐"
echo "│  モデル:     ${MODEL_NAME}"
echo "│  出力先:     ${OUTPUT_DIR}"
echo "│  エポック:   ${EPOCHS}"
echo "│  バッチ:     ${BATCH_SIZE} x ${GRAD_ACCUM} = 実効$((BATCH_SIZE * GRAD_ACCUM))"
echo "│  LoRAランク: ${LORA_RANK}"
echo "│  GPU数:      ${GPU_COUNT}"
echo "│  データ:     ${DATA_COUNT} 件"
echo "│  ダッシュ:   ${REPORT_URL}"
echo "└────────────────────────────────────────────┘"
echo ""

# ── 学習実行 ─────────────────────────────────────────────────────
log_info "学習を開始します... (Ctrl+C で中断)"
echo ""

EXTRA_ARGS=""
if [ -n "$HF_TOKEN" ]; then
    EXTRA_ARGS="$EXTRA_ARGS --hf_token $HF_TOKEN"
fi

$PYTHON -u train.py \
    --data_path data/lyrics_training_data.json \
    --model_name "$MODEL_NAME" \
    --epochs "$EPOCHS" \
    --batch_size "$BATCH_SIZE" \
    --gradient_accumulation "$GRAD_ACCUM" \
    --lora_rank "$LORA_RANK" \
    --output_dir "$OUTPUT_DIR" \
    --report_url "$REPORT_URL" \
    --api_key "$UTAMEMO_TRAINING_API_KEY" \
    $EXTRA_ARGS

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "============================================================"
    log_info "学習完了!"
    log_info "LoRA: ${OUTPUT_DIR}"

    # 学習後: ローカルデータをサーバーに同期
    log_info "学習後データをサーバーにアップロード中..."
    $PYTHON sync_data.py push \
        --api_key "$UTAMEMO_TRAINING_API_KEY" \
        --base_url "$BASE_URL" || log_warn "アップロード失敗 (学習結果は保存済み)"

    echo "============================================================"
else
    echo "============================================================"
    log_error "エラーが発生しました (コード: ${EXIT_CODE})"
    echo "============================================================"
fi

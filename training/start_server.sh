#!/bin/bash
# =============================================================================
# UTAMEMO 推論サーバー + Cloudflare Tunnel 起動スクリプト
#
# 学校のGPU PCでこのスクリプトを実行するだけで
# serve.py + Cloudflare Tunnel が両方起動する。
#
# 初回セットアップ:
#   1. chmod +x start_server.sh
#   2. ./start_server.sh --setup
#
# 通常起動:
#   ./start_server.sh
#
# 停止:
#   Ctrl+C (両方まとめて停止)
# =============================================================================

set -e

# ---------------------
# 設定 (必要に応じて変更、.env ファイルでも上書き可能)
# ---------------------
PORT=${PORT:-8000}
TUNNEL_NAME=${TUNNEL_NAME:-"utamemo-llm"}
LORA_PATH=${LORA_PATH:-"./output/utamemo-lyrics-lora"}
# ベースモデル (Llama 3 / Gemma 2 / Phi / Qwen 等)
# 例: google/gemma-2-9b-it, microsoft/Phi-3.5-mini-instruct
BASE_MODEL=${BASE_MODEL:-"meta-llama/Meta-Llama-3-8B-Instruct"}
# LoRA無しで起動する場合: NO_LORA=1
NO_LORA=${NO_LORA:-""}

# 色付きログ
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ---------------------
# 初回セットアップ
# ---------------------
setup() {
    echo "============================================"
    echo " UTAMEMO 推論サーバー 初回セットアップ"
    echo "============================================"
    echo ""

    # 1. cloudflared インストール確認
    log_step "1/5 cloudflared のインストール確認..."
    if command -v cloudflared &> /dev/null; then
        log_info "cloudflared は既にインストール済み: $(cloudflared --version)"
    else
        log_info "cloudflared をインストール中..."
        
        if [[ "$(uname)" == "Darwin" ]]; then
            # macOS
            brew install cloudflared
        elif [[ "$(uname)" == "Linux" ]]; then
            # Linux (学校GPU PC)
            ARCH=$(uname -m)
            if [[ "$ARCH" == "x86_64" ]]; then
                curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
            elif [[ "$ARCH" == "aarch64" ]]; then
                curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /tmp/cloudflared
            fi
            chmod +x /tmp/cloudflared
            sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
        fi
        
        log_info "cloudflared インストール完了: $(cloudflared --version)"
    fi

    # 2. Cloudflare ログイン
    log_step "2/5 Cloudflare にログイン..."
    echo "ブラウザが開きます。Cloudflareアカウントでログインしてください。"
    echo "(アカウントがない場合: https://dash.cloudflare.com/sign-up で無料作成)"
    echo ""
    cloudflared tunnel login
    log_info "ログイン完了"

    # 3. トンネル作成
    log_step "3/5 トンネル '${TUNNEL_NAME}' を作成..."
    if cloudflared tunnel list | grep -q "${TUNNEL_NAME}"; then
        log_info "トンネル '${TUNNEL_NAME}' は既に存在します"
    else
        cloudflared tunnel create "${TUNNEL_NAME}"
        log_info "トンネル作成完了"
    fi

    # 4. APIキー設定
    log_step "4/5 APIキー設定..."
    if [[ -f ".env" ]]; then
        log_info ".env ファイルが既に存在します"
    else
        # ランダムなAPIキーを生成
        API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        echo "UTAMEMO_API_KEY=${API_KEY}" > .env
        log_info ".env ファイルを作成しました"
        echo ""
        echo "============================================"
        echo -e " ${YELLOW}重要: 以下のAPIキーをRender.comに設定${NC}"
        echo "============================================"
        echo ""
        echo -e "  LOCAL_LLM_API_KEY=${GREEN}${API_KEY}${NC}"
        echo ""
        echo "  Render.com → Environment → Add Environment Variable"
        echo "============================================"
    fi

    # 5. HF_TOKEN確認
    log_step "5/5 Hugging Face トークン確認..."
    if [[ -n "${HF_TOKEN}" ]]; then
        log_info "HF_TOKEN が設定されています"
    else
        log_warn "HF_TOKEN が未設定です"
        echo "  Llama 3のダウンロードに必要です。"
        echo "  export HF_TOKEN='hf_xxxxx' を .env に追加するか、"
        echo "  https://huggingface.co/settings/tokens で取得してください。"
        echo ""
        read -p "  HF_TOKENを入力 (後でやるならEnter): " HF_INPUT
        if [[ -n "${HF_INPUT}" ]]; then
            echo "HF_TOKEN=${HF_INPUT}" >> .env
            log_info "HF_TOKEN を .env に保存しました"
        fi
    fi

    echo ""
    echo "============================================"
    echo -e " ${GREEN}✅ セットアップ完了!${NC}"
    echo "============================================"
    echo ""
    echo " 次のステップ:"
    echo "   1. 学習データを準備 (まだなら)"
    echo "   2. python train.py --data_path data/sample_training_data.json"
    echo "   3. ./start_server.sh  ← サーバー起動"
    echo ""
}

# ---------------------
# トンネルURL取得
# ---------------------
get_tunnel_url() {
    # cloudflared tunnel infoからURLを取得
    TUNNEL_ID=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json, sys
tunnels = json.load(sys.stdin)
for t in tunnels:
    if t.get('name') == '${TUNNEL_NAME}':
        print(t['id'])
        break
" 2>/dev/null || echo "")
    
    if [[ -n "${TUNNEL_ID}" ]]; then
        echo "https://${TUNNEL_ID}.cfargotunnel.com"
    else
        echo ""
    fi
}

# ---------------------
# メイン起動
# ---------------------
start() {
    echo "============================================"
    echo " UTAMEMO 推論サーバー 起動"
    echo "============================================"
    echo ""

    # .env 読み込み
    if [[ -f ".env" ]]; then
        log_info ".env を読み込み中..."
        set -a
        source .env
        set +a
    fi

    # 必須チェック
    if [[ -z "${UTAMEMO_API_KEY}" ]]; then
        log_error "UTAMEMO_API_KEY が設定されていません"
        log_error "./start_server.sh --setup を実行してください"
        exit 1
    fi

    # cloudflared チェック
    if ! command -v cloudflared &> /dev/null; then
        log_error "cloudflared が見つかりません"
        log_error "./start_server.sh --setup を実行してください"
        exit 1
    fi

    # LoRAモデルの存在確認 (NO_LORA 時はスキップ)
    if [[ -z "${NO_LORA}" ]] && [[ ! -d "${LORA_PATH}" ]]; then
        log_warn "LoRAモデルが見つかりません: ${LORA_PATH}"
        log_warn "先に学習を実行してください:"
        log_warn "  python train.py --data_path data/sample_training_data.json"
        log_warn ""
        log_warn "LoRA無しで起動する場合: NO_LORA=1 ./start_server.sh"
        echo ""
        read -p "それでも起動しますか？ (y/N): " CONFIRM
        if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
            exit 0
        fi
    fi

    # GPU確認
    log_info "GPU 確認中..."
    python3 -c "
import torch
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_mem / 1024**3
        print(f'  GPU {i}: {name} ({mem:.1f} GB)')
else:
    print('  ⚠️  CUDA が利用できません (CPUで実行します)')
" 2>/dev/null || log_warn "PyTorchが未インストール"

    echo ""
    log_info "推論サーバーを起動中 (port ${PORT})..."
    log_info "  ベースモデル: ${BASE_MODEL}"
    if [[ -n "${NO_LORA}" ]]; then
        log_info "  LoRA: 無し (ベースモデルのみ)"
    else
        log_info "  LoRA: ${LORA_PATH}"
    fi
    log_info "Cloudflare Tunnel を起動中..."
    echo ""

    # serve.py をバックグラウンドで起動
    python3 serve.py \
        --port "${PORT}" \
        --host "127.0.0.1" \
        --lora_path "${LORA_PATH}" \
        --base_model "${BASE_MODEL}" \
        ${HF_TOKEN:+--hf_token "${HF_TOKEN}"} \
        ${NO_LORA:+--no_lora} &
    SERVE_PID=$!

    # serve.pyが起動するまで待つ
    log_info "モデルロード中... (初回は数分かかります)"
    for i in $(seq 1 120); do
        if curl -s "http://127.0.0.1:${PORT}/health" > /dev/null 2>&1; then
            log_info "推論サーバー起動完了 ✅"
            break
        fi
        if ! kill -0 ${SERVE_PID} 2>/dev/null; then
            log_error "推論サーバーが異常終了しました"
            exit 1
        fi
        sleep 2
    done

    # Cloudflare Tunnel を起動
    echo ""
    echo "============================================"
    log_info "Cloudflare Tunnel 起動中..."
    echo "============================================"
    echo ""
    
    cloudflared tunnel --url "http://127.0.0.1:${PORT}" run "${TUNNEL_NAME}" &
    TUNNEL_PID=$!

    # URL表示
    sleep 3
    echo ""
    echo "============================================"
    echo -e " ${GREEN}✅ サーバー起動完了!${NC}"
    echo "============================================"
    echo ""
    echo " 推論サーバー:   http://127.0.0.1:${PORT}"
    echo ""
    echo " Cloudflare URL は上のログに表示されています。"
    echo " (例: https://xxxx-xxxx.trycloudflare.com)"
    echo ""
    echo " Render.comに設定する環境変数:"
    echo "   LOCAL_LLM_URL=<上のCloudflare URL>"
    echo "   LOCAL_LLM_API_KEY=${UTAMEMO_API_KEY}"
    echo "   LYRICS_BACKEND=auto"
    echo ""
    echo " 停止: Ctrl+C"
    echo "============================================"

    # Ctrl+Cで両方停止
    trap "log_info 'シャットダウン中...'; kill ${SERVE_PID} ${TUNNEL_PID} 2>/dev/null; exit 0" SIGINT SIGTERM

    # 待機
    wait
}

# ---------------------
# エントリポイント
# ---------------------
case "${1}" in
    --setup|-s)
        setup
        ;;
    --help|-h)
        echo "使い方:"
        echo "  ./start_server.sh          サーバー + トンネル起動"
        echo "  ./start_server.sh --setup   初回セットアップ"
        echo "  ./start_server.sh --help    このヘルプ"
        ;;
    *)
        start
        ;;
esac

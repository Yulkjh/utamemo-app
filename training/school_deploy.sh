#!/bin/bash
# ============================================================================
# UTAMEMO 学校GPU学習デプロイスクリプト
# ============================================================================
# 
# 使い方:
#   cd ~/Desktop/utamemo-app/training
#   bash school_deploy.sh            # データ送信 + 学習開始（デフォルト）
#   bash school_deploy.sh sync       # データ送信のみ
#   bash school_deploy.sh train      # 学習開始のみ（データは送信済み前提）
#   bash school_deploy.sh status     # 学習状況を確認
#   bash school_deploy.sh stop       # 学習を停止
#   bash school_deploy.sh log        # ログをリアルタイム表示
#   bash school_deploy.sh export     # DBからデータ抽出 → 送信 → 学習開始
#
# 前提:
#   - SSH鍵認証が設定済み (ssh Yu@10.3.0.199 でパスワードなし接続)
#   - 学校PCに ~/utamemo-training/venv が構築済み
# ============================================================================

set -e

# === 設定 ===
SSH_USER="Yu"
SSH_HOST="10.3.0.199"
SSH_PORT=22
REMOTE_DIR="~/utamemo-training"
REMOTE_VENV="source ~/utamemo-training/venv/bin/activate"

LOCAL_TRAINING_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_DATA="$LOCAL_TRAINING_DIR/data/lyrics_training_data.json"
LOCAL_PROJECT="$LOCAL_TRAINING_DIR/../myproject"

# 学習パラメータ（学校PC: RTX 4080 SUPER x2）
MODEL="Qwen/Qwen2.5-14B-Instruct"
EPOCHS=5
BATCH_SIZE=1
LORA_RANK=64
GRAD_ACCUM=8

SSH_CMD="ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST}"
SCP_CMD="scp -o ConnectTimeout=10"

# === 色付き出力 ===
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }
step()  { echo -e "${BLUE}[→]${NC} $1"; }

# === 関数: SSH接続テスト ===
test_connection() {
    step "SSH接続テスト..."
    if $SSH_CMD "echo ok" >/dev/null 2>&1; then
        info "SSH接続OK"
        $SSH_CMD "nvidia-smi --query-gpu=name,memory.used,memory.free --format=csv,noheader" 2>/dev/null
        return 0
    else
        error "SSH接続失敗。学校のネットワークに接続していますか？"
        return 1
    fi
}

# === 関数: DBからデータ抽出 ===
export_from_db() {
    step "DBから学習データを抽出中..."
    cd "$LOCAL_PROJECT"
    
    # .venvがあればそれを使う、なければシステムPython
    if [ -f "$LOCAL_TRAINING_DIR/../.venv/bin/python" ]; then
        PYTHON="$LOCAL_TRAINING_DIR/../.venv/bin/python"
    else
        PYTHON="python3"
    fi
    
    $PYTHON manage.py shell <<'DJANGO_SCRIPT'
import json, os, re, sys

from songs.models import Song, Lyrics

training_data = []
skipped = 0

songs = Song.objects.filter(lyrics__isnull=False).select_related('lyrics').prefetch_related('tags').all()

for song in songs:
    lyrics = song.lyrics
    content = (lyrics.content or '').strip()
    original_text = (lyrics.original_text or '').strip()

    if len(content) < 50 or '[' not in content:
        skipped += 1
        continue

    genre = song.genre or 'pop'
    tags = list(song.tags.values_list('name', flat=True))

    if original_text and len(original_text) > 10:
        tag_hint = f"（教科/トピック: {', '.join(tags[:3])}）\n" if tags else ""
        instruction = (
            f"あなたは暗記学習用の歌詞作成の専門家です。"
            f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
            f"{tag_hint}"
            f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
            f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
            f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
        )
        entry = {"instruction": instruction, "input": original_text, "output": content}
    else:
        instruction = (
            f"あなたは暗記学習用の歌詞作成の専門家です。"
            f"「{song.title}」というタイトルで{genre}ジャンルの学習ソングの歌詞を作成してください。\n"
            f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
            f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
        )
        entry = {"instruction": instruction, "input": "", "output": content}

    training_data.append(entry)

output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'training', 'data', 'lyrics_training_data.json')
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(training_data, f, ensure_ascii=False, indent=2)

print(f"✅ DB抽出完了: {len(training_data)}件 (スキップ: {skipped}件)")
print(f"   → {output_path}")
DJANGO_SCRIPT
    
    cd "$LOCAL_TRAINING_DIR"
}

# === 関数: データ＆コードを学校PCに送信 ===
sync_data() {
    step "学校PCにデータを送信中..."
    
    if [ ! -f "$LOCAL_DATA" ]; then
        error "学習データが見つかりません: $LOCAL_DATA"
        error "先に 'bash school_deploy.sh export' でDBから抽出してください"
        exit 1
    fi
    
    LOCAL_COUNT=$(python3 -c "import json; print(len(json.load(open('$LOCAL_DATA'))))")
    info "送信するデータ: ${LOCAL_COUNT}件"
    
    # データファイルを送信
    $SCP_CMD "$LOCAL_DATA" "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/data/lyrics_training_data.json"
    info "データ送信完了"
    
    # 学習スクリプトも同期（更新があるかもしれない）
    for f in train.py serve.py requirements_training.txt; do
        if [ -f "$LOCAL_TRAINING_DIR/$f" ]; then
            $SCP_CMD "$LOCAL_TRAINING_DIR/$f" "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}/$f" 2>/dev/null
        fi
    done
    info "スクリプト同期完了"
    
    # リモートで件数確認
    REMOTE_COUNT=$($SSH_CMD "python3 -c \"import json; print(len(json.load(open('${REMOTE_DIR}/data/lyrics_training_data.json'))))\"" 2>/dev/null)
    info "リモート確認: ${REMOTE_COUNT}件"
}

# === 関数: 学習を開始 ===
start_training() {
    step "学習を開始..."
    
    # 既に学習中か確認
    RUNNING=$($SSH_CMD "pgrep -f 'python.*train\.py' 2>/dev/null | wc -l" 2>/dev/null || echo "0")
    if [ "$RUNNING" -gt 0 ]; then
        warn "既に学習プロセスが実行中です (${RUNNING}プロセス)"
        echo ""
        show_status
        echo ""
        read -p "停止して新しい学習を開始しますか？ (y/N): " answer
        if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
            info "中止しました"
            return
        fi
        stop_training
        sleep 3
    fi
    
    # GPU空き確認
    step "GPU状態を確認..."
    $SSH_CMD "nvidia-smi --query-gpu=name,memory.used,memory.free --format=csv,noheader"
    echo ""
    
    # 学習開始
    step "Qwen2.5-14B + QLoRA 学習を開始..."
    $SSH_CMD "bash -c '${REMOTE_VENV} && cd ${REMOTE_DIR} && PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True nohup python3 train.py --data_path data/lyrics_training_data.json --model_name ${MODEL} --epochs ${EPOCHS} --batch_size ${BATCH_SIZE} --lora_rank ${LORA_RANK} --gradient_accumulation ${GRAD_ACCUM} > train.log 2>&1 & echo PID: \$!'"
    
    sleep 2
    
    # プロセス確認
    PID=$($SSH_CMD "pgrep -f 'python.*train\.py' | head -1" 2>/dev/null)
    if [ -n "$PID" ]; then
        info "学習開始! PID: ${PID}"
        info "モデル: ${MODEL}"
        info "エポック: ${EPOCHS}, バッチ: ${BATCH_SIZE}, LoRAランク: ${LORA_RANK}"
        echo ""
        info "進捗確認: bash school_deploy.sh status"
        info "ログ監視: bash school_deploy.sh log"
    else
        error "学習プロセスが見つかりません。ログを確認:"
        $SSH_CMD "tail -20 ${REMOTE_DIR}/train.log 2>/dev/null"
    fi
}

# === 関数: 学習状況を表示 ===
show_status() {
    echo "========================================"
    echo " UTAMEMO 学習ステータス"
    echo "========================================"
    
    # プロセス
    RUNNING=$($SSH_CMD "pgrep -f 'python.*train\.py' 2>/dev/null | head -1" || true)
    if [ -n "$RUNNING" ]; then
        info "学習実行中 (PID: ${RUNNING})"
    else
        warn "学習プロセスなし"
    fi
    echo ""
    
    # GPU
    step "GPU状態:"
    $SSH_CMD "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader" 2>/dev/null
    echo ""
    
    # ログ末尾
    step "最新ログ:"
    $SSH_CMD "tail -10 ${REMOTE_DIR}/train.log 2>/dev/null || echo '(ログなし)'"
    echo ""
    
    # データ件数
    REMOTE_COUNT=$($SSH_CMD "python3 -c \"import json; print(len(json.load(open('${REMOTE_DIR}/data/lyrics_training_data.json'))))\" 2>/dev/null" || echo "不明")
    info "学習データ: ${REMOTE_COUNT}件"
}

# === 関数: 学習を停止 ===
stop_training() {
    step "学習プロセスを停止中..."
    $SSH_CMD "pkill -f 'python.*train\.py'" 2>/dev/null || true
    sleep 1
    REMAINING=$($SSH_CMD "pgrep -f 'python.*train\.py' 2>/dev/null | wc -l" || echo "0")
    if [ "$REMAINING" -eq 0 ]; then
        info "停止完了"
    else
        warn "まだプロセスが残っています。強制停止..."
        $SSH_CMD "pkill -9 -f 'python.*train\.py'" 2>/dev/null || true
        info "強制停止完了"
    fi
}

# === 関数: ログをリアルタイム表示 ===
show_log() {
    step "ログをリアルタイム表示中... (Ctrl+Cで終了)"
    $SSH_CMD "tail -f ${REMOTE_DIR}/train.log"
}

# === メイン ===
ACTION="${1:-all}"

case "$ACTION" in
    export)
        test_connection
        export_from_db
        sync_data
        start_training
        ;;
    sync)
        test_connection
        sync_data
        ;;
    train)
        test_connection
        start_training
        ;;
    status)
        test_connection
        show_status
        ;;
    stop)
        test_connection
        stop_training
        ;;
    log)
        show_log
        ;;
    all)
        test_connection
        sync_data
        start_training
        ;;
    *)
        echo "使い方: bash school_deploy.sh [export|sync|train|status|stop|log|all]"
        echo ""
        echo "  export  - DBからデータ抽出 → 学校に送信 → 学習開始"
        echo "  sync    - データを学校PCに送信のみ"
        echo "  train   - 学習開始のみ"
        echo "  status  - 学習状況を確認"
        echo "  stop    - 学習を停止"
        echo "  log     - ログをリアルタイム表示"
        echo "  all     - データ送信 + 学習開始（デフォルト）"
        ;;
esac

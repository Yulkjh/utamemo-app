#!/bin/bash
# =============================================================================
#  学習完了監視スクリプト
#  - train_new.log に "学習完了!" が現れたら:
#    1. used_hashes.json をサーバーに送信 (trained_at マーク)
#    2. Mac に osascript 通知 (SSH経由)
#    3. utamemo.com の training status を completed に更新
# =============================================================================

LOG_FILE="${LOG_FILE:-/home/Yu/utamemo-training/train_new.log}"
OUTPUT_DIR="${OUTPUT_DIR:-/home/Yu/utamemo-training/output/utamemo-lyrics-lora}"
API_KEY="${UTAMEMO_TRAINING_API_KEY:-19e8f1429d75e36f3491cf93bf43b846c504988d4f719e0a86f44527c3c8e5fa}"
BASE_URL="${BASE_URL:-https://utamemo.com}"
NOTIFY_HOST="${NOTIFY_HOST:-}"   # Mac の IP (SSH逆通知用、空なら省略)
NOTIFY_USER="${NOTIFY_USER:-}"

REVIEWED_API="${BASE_URL}/api/training/reviewed/"
POLL_SEC=30

echo "[WATCHER] 学習完了を監視中: $LOG_FILE"
echo "[WATCHER] 終了したら used_hashes を ${BASE_URL} に送信します"

while true; do
    if [ ! -f "$LOG_FILE" ]; then
        echo "[WATCHER] ログファイル待機中..."
        sleep "$POLL_SEC"
        continue
    fi

    # 学習完了チェック
    if grep -q "学習完了!" "$LOG_FILE" 2>/dev/null; then
        echo "[WATCHER] ✅ 学習完了を検出!"

        # used_hashes.json を探す
        HASHES_FILE="${OUTPUT_DIR}/used_hashes.json"
        if [ ! -f "$HASHES_FILE" ]; then
            # output 配下を再帰的に探す
            HASHES_FILE=$(find /home/Yu/utamemo-training/output -name "used_hashes.json" 2>/dev/null | head -1)
        fi

        if [ -n "$HASHES_FILE" ] && [ -f "$HASHES_FILE" ]; then
            HASH_COUNT=$(python3 -c "import json; d=json.load(open('$HASHES_FILE')); print(len(d))")
            echo "[WATCHER] used_hashes: ${HASH_COUNT}件 -> サーバーに送信中..."

            # trained_at マーク API呼び出し
            PAYLOAD=$(python3 -c "
import json
hashes = json.load(open('$HASHES_FILE'))
print(json.dumps({'trained_hashes': hashes}))
")
            RESULT=$(curl -s -X POST \
                -H "Content-Type: application/json" \
                -H "X-Training-Api-Key: ${API_KEY}" \
                -d "$PAYLOAD" \
                "${REVIEWED_API}")
            echo "[WATCHER] サーバー応答: $RESULT"
            MARKED=$(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('marked','?'))" 2>/dev/null)
            echo "[WATCHER] ✅ trained_at マーク完了: ${MARKED}件"
        else
            echo "[WATCHER] ⚠️  used_hashes.json が見つかりません"
        fi

        # 最終loss取得
        FINAL_LOSS=$(grep "学習完了!" "$LOG_FILE" | tail -1 | grep -oP "Train Loss=[\d.]+" | head -1)

        # Mac への通知 (NOTIFY_HOST が設定されている場合)
        if [ -n "$NOTIFY_HOST" ] && [ -n "$NOTIFY_USER" ]; then
            MSG="✅ 学習完了! ${FINAL_LOSS} trained_at: ${MARKED}件 マーク済み"
            ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no \
                "${NOTIFY_USER}@${NOTIFY_HOST}" \
                "osascript -e 'display notification \"${MSG}\" with title \"UTAMEMO Training\" sound name \"Glass\"'" 2>/dev/null || true
        fi

        echo "[WATCHER] 🎉 全処理完了。終了します。"
        exit 0
    fi

    # まだ学習中 - 進捗表示
    PROGRESS=$(grep -oP "\d+%\|" "$LOG_FILE" 2>/dev/null | tail -1)
    LOSS=$(grep "loss=" "$LOG_FILE" 2>/dev/null | tail -1 | grep -oP "loss=[\d.]+" | head -1)
    echo "[WATCHER] 進捗: ${PROGRESS:-不明} | ${LOSS:-} | $(date '+%H:%M:%S')"

    sleep "$POLL_SEC"
done

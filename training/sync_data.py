#!/usr/bin/env python3
"""
UTAMEMO Training Data Sync (双方向)

Render.com のサーバーとローカルの学習データを双方向で同期する。
utamemo.com が常にハブ (中継) として機能する。

  自宅PC ←→ utamemo.com (Render) ←→ 学校PC

使い方:
  # サーバーからダウンロード (pull)
  python sync_data.py pull --api_key YOUR_KEY

  # ローカルからサーバーへアップロード (push) ※マージ
  python sync_data.py push --api_key YOUR_KEY

  # 双方向同期 (pull → push の順)
  python sync_data.py sync --api_key YOUR_KEY

  # 確認のみ (保存/送信しない)
  python sync_data.py sync --api_key YOUR_KEY --dry_run

環境変数でも指定可能:
  UTAMEMO_TRAINING_API_KEY=xxx python sync_data.py sync
"""

import argparse
import json
import logging
import os
import shutil
import sys
import urllib.request
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://utamemo.onrender.com"
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_FILE = DATA_DIR / "lyrics_training_data.json"
BACKUP_FILE = DATA_DIR / "lyrics_training_data.json.bak"


# ─── Pull (ダウンロード) ─────────────────────────────────────────

def fetch_training_data(base_url: str, api_key: str, timeout: int = 60) -> dict:
    """サーバーから学習データを取得する"""
    url = f"{base_url.rstrip('/')}/api/training/data/download/"
    logger.info("データ取得中: %s", url)

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-Training-Api-Key": api_key,
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error("HTTPエラー %d: %s", e.code, error_body)
        raise
    except urllib.error.URLError as e:
        logger.error("接続エラー: %s", e.reason)
        raise


def save_training_data(records: list, backup: bool = True) -> int:
    """学習データをローカルに保存する"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if backup and DATA_FILE.exists():
        shutil.copy2(DATA_FILE, BACKUP_FILE)
        logger.info("バックアップ: %s", BACKUP_FILE)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("保存完了: %s (%d 件)", DATA_FILE, len(records))
    return len(records)


def pull(base_url: str, api_key: str, dry_run: bool = False, timeout: int = 60) -> dict:
    """サーバーからダウンロードしてローカルを更新。結果情報を返す。

    pull はサーバーの状態を正として取得する。
    ローカルにしかないデータが消えるのを防ぐため、差分を警告表示するが、
    サーバー側のデータで上書きする（ローカル独自データが必要なら先に push すること）。
    """
    result = fetch_training_data(base_url, api_key, timeout)

    if not result.get("ok"):
        logger.error("サーバーエラー: %s", result.get("error", "不明"))
        return {"ok": False, "error": result.get("error")}

    server_records = result["records"]
    total = result.get("total", len(server_records))
    prompt = result.get("prompt_template", "")

    logger.info("サーバー上のデータ: %d 件", total)
    if prompt:
        logger.info("プロンプトテンプレートも取得しました")

    # ローカルとの差分を表示
    local_count = 0
    local_only_count = 0
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            local_records = json.load(f)
        local_count = len(local_records)

        # ローカルにしかないデータを検出（警告用）
        server_keys = {r.get("input", "")[:50] for r in server_records}
        local_only = [r for r in local_records if r.get("input", "")[:50] not in server_keys]
        local_only_count = len(local_only)

        if local_only_count > 0:
            logger.warning(
                "ローカルのみのデータが %d 件あります。サーバーに反映するには先に push してください。",
                local_only_count
            )

    diff = total - local_count
    logger.info("結果: ローカル %d → サーバー %d (%+d)", local_count, total, diff)

    if dry_run:
        logger.info("[DRY RUN] 保存をスキップしました")
        return {"ok": True, "total": total, "diff": diff, "local_only": local_only_count, "prompt": prompt}

    save_training_data(server_records)

    # プロンプトテンプレートも保存 (generate_history_data.py 等で使用可能)
    if prompt:
        prompt_path = DATA_DIR / "prompt_template.txt"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        logger.info("プロンプト保存: %s", prompt_path)

    return {"ok": True, "total": total, "diff": diff, "local_only": local_only_count, "prompt": prompt}


# ─── Push (アップロード) ─────────────────────────────────────────

def upload_training_data(base_url: str, api_key: str, records: list,
                         mode: str = "merge", timeout: int = 60) -> dict:
    """ローカルデータをサーバーにアップロードする"""
    url = f"{base_url.rstrip('/')}/api/training/data/upload/"
    logger.info("データアップロード中: %s (%d 件, mode=%s)", url, len(records), mode)

    payload = json.dumps({
        "records": records,
        "mode": mode,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "X-Training-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error("HTTPエラー %d: %s", e.code, error_body)
        raise
    except urllib.error.URLError as e:
        logger.error("接続エラー: %s", e.reason)
        raise


def push(base_url: str, api_key: str, dry_run: bool = False, timeout: int = 60) -> dict:
    """ローカルデータをサーバーにアップロード（マージ）。結果情報を返す。"""
    if not DATA_FILE.exists():
        logger.error("ローカルデータが見つかりません: %s", DATA_FILE)
        return {"ok": False, "error": "ローカルデータなし"}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        local_records = json.load(f)

    logger.info("ローカルデータ: %d 件", len(local_records))

    if dry_run:
        logger.info("[DRY RUN] アップロードをスキップしました")
        return {"ok": True, "local": len(local_records), "added": 0}

    result = upload_training_data(base_url, api_key, local_records, "merge", timeout)

    if result.get("ok"):
        added = result.get("added", 0)
        total = result.get("total", 0)
        logger.info("アップロード完了: +%d 件 (サーバー合計 %d 件)", added, total)
        return {"ok": True, "added": added, "total": total}
    else:
        logger.error("アップロード失敗: %s", result.get("error", "不明"))
        return {"ok": False, "error": result.get("error")}


# ─── Sync (双方向) ───────────────────────────────────────────────

def sync(base_url: str, api_key: str, dry_run: bool = False, timeout: int = 60) -> dict:
    """双方向同期: push → pull の順。

    1. push: ローカルの新規データをサーバーに送信
    2. pull: サーバーから全データをダウンロードしてローカルを更新

    この順序で実行することで、最終的にサーバーとローカルが一致する。
    """
    logger.info("=" * 50)
    logger.info("双方向同期を開始します")
    logger.info("=" * 50)

    # Step 1: Push (ローカル → サーバー)
    logger.info("")
    logger.info("--- Step 1/2: Push (ローカル → サーバー) ---")
    if DATA_FILE.exists():
        push_result = push(base_url, api_key, dry_run, timeout)
        if not push_result.get("ok"):
            logger.warning("Push 失敗、Pull のみ実行します")
    else:
        logger.info("ローカルデータなし、Push をスキップ")
        push_result = {"ok": True, "added": 0}

    # Step 2: Pull (サーバー → ローカル)
    logger.info("")
    logger.info("--- Step 2/2: Pull (サーバー → ローカル) ---")
    pull_result = pull(base_url, api_key, dry_run, timeout)

    logger.info("")
    logger.info("=" * 50)
    push_added = push_result.get("added", 0)
    pull_total = pull_result.get("total", 0)
    logger.info("同期完了! Push: +%d, 最終データ: %d 件", push_added, pull_total)
    logger.info("=" * 50)

    return {
        "ok": pull_result.get("ok", False),
        "push_added": push_added,
        "pull_total": pull_total,
    }


# ─── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UTAMEMO 学習データ双方向同期ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python sync_data.py pull   --api_key KEY   # サーバー → ローカル
  python sync_data.py push   --api_key KEY   # ローカル → サーバー
  python sync_data.py sync   --api_key KEY   # 双方向 (push→pull)
  python sync_data.py sync   --dry_run       # 確認のみ
        """,
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="sync",
        choices=["pull", "push", "sync"],
        help="実行アクション (default: sync)",
    )
    parser.add_argument(
        "--api_key",
        default=os.environ.get("UTAMEMO_TRAINING_API_KEY", ""),
        help="トレーニングAPIキー (env: UTAMEMO_TRAINING_API_KEY)",
    )
    parser.add_argument(
        "--base_url",
        default=os.environ.get("UTAMEMO_BASE_URL", DEFAULT_BASE_URL),
        help=f"サーバーURL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="ダウンロード/アップロードするが保存/送信しない",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="タイムアウト秒数 (default: 60)",
    )
    args = parser.parse_args()

    if not args.api_key:
        logger.error("APIキーが指定されていません。--api_key または環境変数 UTAMEMO_TRAINING_API_KEY を設定してください。")
        sys.exit(1)

    try:
        if args.action == "pull":
            result = pull(args.base_url, args.api_key, args.dry_run, args.timeout)
        elif args.action == "push":
            result = push(args.base_url, args.api_key, args.dry_run, args.timeout)
        else:  # sync
            result = sync(args.base_url, args.api_key, args.dry_run, args.timeout)

        if result.get("ok"):
            logger.info("完了!")
        else:
            logger.error("失敗: %s", result.get("error", "不明"))
            sys.exit(1)
    except Exception as e:
        logger.error("エラー: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

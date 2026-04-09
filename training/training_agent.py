#!/usr/bin/env python3
"""
UTAMEMO トレーニングエージェント

ローカルPCで常駐し、サイトのダッシュボードからのコマンドを待ち受けて
トレーニングを自動開始する。

使い方:
  python training_agent.py --api_key YOUR_KEY --report_url https://utamemo.onrender.com/api/training/update/
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 10  # 秒


def send_status(report_url, api_key, **kwargs):
    """サーバーにステータスを送信し、コマンドを受け取る"""
    import platform
    import socket

    hostname = platform.node()
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = None

    payload = {
        'machine_name': hostname,
        'machine_ip': ip,
        'poll': True,
        **kwargs,
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            report_url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'X-Training-Api-Key': api_key,
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result.get('command', 'none')
    except Exception as e:
        logger.warning(f"通信失敗: {e}")
        return 'none'


def get_python_exe():
    """Python実行ファイルを決定"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    # .venv (プロジェクトルート) → training/venv → sys.executable
    for venv_dir in [
        os.path.join(project_root, '.venv', 'Scripts', 'python.exe'),
        os.path.join(script_dir, 'venv', 'Scripts', 'python.exe'),
    ]:
        if os.path.exists(venv_dir):
            return venv_dir
    return sys.executable


def run_subprocess(cmd, label="process"):
    """サブプロセスを実行し出力をログに流す"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logger.info(f"{label} 開始: {' '.join(cmd)}")
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    process = subprocess.Popen(
        cmd,
        cwd=script_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        encoding='utf-8',
        errors='replace',
    )

    for line in process.stdout:
        line = line.rstrip()
        if line:
            logger.info(f"  [{label}] {line}")

    process.wait()
    return process.returncode


def run_data_generation(args):
    """Geminiで学習データを自動生成"""
    if not args.gemini_key:
        logger.warning("Gemini APIキー未設定、データ生成をスキップ")
        return -1

    script_dir = os.path.dirname(os.path.abspath(__file__))
    gen_script = os.path.join(script_dir, 'generate_history_data.py')
    python_exe = get_python_exe()

    cmd = [
        python_exe, '-u', gen_script,
        '--gemini-key', args.gemini_key,
        '--random-count', str(args.gen_count),
    ]

    return run_subprocess(cmd, label="datagen")


def run_training(args):
    """トレーニングを実行 (subprocess)"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    train_script = os.path.join(script_dir, 'train.py')
    python_exe = get_python_exe()

    cmd = [
        python_exe, '-u', train_script,
        '--data_path', args.data_path,
        '--model_name', args.model_name,
        '--epochs', str(args.epochs),
        '--batch_size', str(args.batch_size),
        '--gradient_accumulation', str(args.gradient_accumulation),
        '--output_dir', args.output_dir,
        '--report_url', args.report_url,
        '--api_key', args.api_key,
    ]

    logger.info(f"トレーニング開始: {' '.join(cmd)}")
    return run_subprocess(cmd, label="train")


def main():
    parser = argparse.ArgumentParser(description="UTAMEMO トレーニングエージェント")
    parser.add_argument('--report_url', type=str, required=True,
                        help='ダッシュボードAPI URL')
    parser.add_argument('--api_key', type=str,
                        default=os.getenv('UTAMEMO_TRAINING_API_KEY', ''),
                        help='APIキー')
    parser.add_argument('--data_path', type=str,
                        default='data/lyrics_training_data.json',
                        help='学習データパス')
    parser.add_argument('--model_name', type=str,
                        default='Qwen/Qwen2.5-7B-Instruct',
                        help='モデル名')
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--batch_size', type=int, default=1)
    parser.add_argument('--gradient_accumulation', type=int, default=8)
    parser.add_argument('--output_dir', type=str,
                        default=os.getenv('UTAMEMO_OUTPUT_DIR', 'C:\\temp\\utamemo-lora'))
    parser.add_argument('--gemini_key', type=str,
                        default=os.getenv('GEMINI_API_KEY', ''),
                        help='Gemini APIキー (データ自動生成用)')
    parser.add_argument('--gen_count', type=int, default=5,
                        help='各サイクルで生成する新規テーマ数 (デフォルト: 5)')
    args = parser.parse_args()

    if not args.api_key:
        logger.error("APIキーが必要です (--api_key または UTAMEMO_TRAINING_API_KEY)")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("UTAMEMO Training Agent 起動")
    logger.info(f"  サーバー: {args.report_url}")
    logger.info(f"  ポーリング間隔: {POLL_INTERVAL}秒")
    logger.info(f"  モデル: {args.model_name}")
    if args.gemini_key:
        logger.info(f"  データ自動生成: 有効 ({args.gen_count}件/サイクル)")
    else:
        logger.info("  データ自動生成: 無効 (--gemini_key 未設定)")
    logger.info("  ダッシュボードから「トレーニング開始」で実行されます")
    logger.info("  開始後は自動で無限サイクルします (停止コマンドで中断)")
    logger.info("  Ctrl+C で終了")
    logger.info("=" * 50)

    # 初回: idle状態を送信
    send_status(args.report_url, args.api_key, status='idle')

    training_running = False
    auto_loop = False  # 一度開始されたら自動ループ

    while True:
        try:
            if not training_running:
                # サーバーにポーリング → コマンド取得
                cmd = send_status(args.report_url, args.api_key, status='idle')

                if cmd == 'stop':
                    # 停止コマンドは常に最優先
                    if auto_loop:
                        logger.info("停止コマンド受信: 自動ループを停止します")
                        auto_loop = False
                    else:
                        logger.info("停止コマンド受信 (既にアイドル状態)")

                elif cmd == 'start' or auto_loop:
                    if auto_loop:
                        logger.info(">>> 自動ループ: 次のサイクルを開始します")
                    else:
                        logger.info(">>> 開始コマンド受信! トレーニングを開始します")
                        auto_loop = True

                    training_running = True

                    try:
                        # Step 1: Geminiで学習データを自動生成
                        if args.gemini_key:
                            logger.info("--- Step 1/2: 学習データ生成 ---")
                            gen_code = run_data_generation(args)
                            if gen_code != 0:
                                logger.warning(f"データ生成に問題 (exit code: {gen_code}), 学習は既存データで続行")
                        else:
                            logger.info("データ生成スキップ (Gemini APIキー未設定)")

                        # Step 1.5: 停止コマンドが来ていないかチェック
                        check_cmd = send_status(args.report_url, args.api_key, status='training')
                        if check_cmd == 'stop':
                            logger.info("停止コマンド受信: 学習をスキップしてアイドルに戻ります")
                            auto_loop = False
                            training_running = False
                            continue

                        # Step 2: LoRA学習
                        logger.info("--- Step 2/2: LoRA学習 ---")
                        exit_code = run_training(args)

                        if exit_code == 0:
                            logger.info("トレーニング完了! 次のサイクルに進みます...")
                        else:
                            logger.error(f"トレーニング失敗 (exit code: {exit_code})")
                            logger.info("10秒後にリトライします...")

                    except Exception as e:
                        logger.error(f"サイクル中にエラー: {e}")
                        send_status(args.report_url, args.api_key,
                                    status='error', error_message=str(e)[:500])
                        logger.info("次のポーリングでリトライします...")
                    finally:
                        training_running = False

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("エージェント停止")
            send_status(args.report_url, args.api_key, status='idle')
            break


if __name__ == '__main__':
    main()

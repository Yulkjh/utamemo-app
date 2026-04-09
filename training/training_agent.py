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
            return result.get('command', 'none'), result.get('training_type', 'lyrics')
    except Exception as e:
        logger.warning(f"通信失敗: {e}")
        return 'none', 'lyrics'


def get_python_exe():
    """Python実行ファイルを決定"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    # training/venv (torch入り) → .venv (プロジェクトルート) → sys.executable
    for venv_dir in [
        os.path.join(script_dir, 'venv', 'Scripts', 'python.exe'),
        os.path.join(project_root, '.venv', 'Scripts', 'python.exe'),
    ]:
        if os.path.exists(venv_dir):
            return venv_dir
    return sys.executable


def run_subprocess(cmd, label="process", stop_checker=None):
    """サブプロセスを実行し出力をログに流す
    
    stop_checker: 呼ぶと停止すべきかを返す callable (True=停止)
    Windows対応: スレッドで stdout を読み取り、メインスレッドで停止チェック
    """
    import threading
    import queue

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

    # スレッドで stdout を読み取り、キューに入れる
    output_queue = queue.Queue()

    def reader_thread():
        try:
            for line in process.stdout:
                output_queue.put(line)
        except Exception:
            pass
        finally:
            output_queue.put(None)  # 終了シグナル

    t = threading.Thread(target=reader_thread, daemon=True)
    t.start()

    last_stop_check = time.time()

    while True:
        # キューから出力を読む (最大1秒待機)
        try:
            line = output_queue.get(timeout=1.0)
            if line is None:
                break  # reader_thread 終了
            line = line.rstrip()
            if line:
                logger.info(f"  [{label}] {line}")
        except queue.Empty:
            pass

        # プロセスが終了していたらキューを空にして抜ける
        if process.poll() is not None:
            while not output_queue.empty():
                line = output_queue.get_nowait()
                if line is None:
                    break
                line = line.rstrip()
                if line:
                    logger.info(f"  [{label}] {line}")
            break

        # 5秒ごとに停止チェック
        now = time.time()
        if stop_checker and now - last_stop_check >= 5:
            last_stop_check = now
            if stop_checker():
                logger.info(f"停止コマンド検出: {label} プロセスを終了します")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning(f"{label} プロセスが応答しません。強制終了します")
                    process.kill()
                    process.wait()
                return -99  # 停止による終了

    process.wait()
    return process.returncode


def run_data_generation(args, stop_checker=None):
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

    return run_subprocess(cmd, label="datagen", stop_checker=stop_checker)


def run_training(args, stop_checker=None):
    """歌詞LLMトレーニングを実行 (subprocess)"""
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
    return run_subprocess(cmd, label="train", stop_checker=stop_checker)


def run_importance_training(args, stop_checker=None):
    """ノート重要度LLMトレーニングを実行 (subprocess)"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    train_script = os.path.join(script_dir, 'note_importance', 'train_scorer.py')
    python_exe = get_python_exe()

    data_path = os.path.join(script_dir, 'data', 'importance_dataset.jsonl')
    output_dir = os.path.join(
        os.path.dirname(args.output_dir) if args.output_dir else 'output',
        'utamemo-importance-lora'
    )

    cmd = [
        python_exe, '-u', '-m', 'note_importance.train_scorer',
        '--data_path', data_path,
        '--model_name', args.model_name,
        '--epochs', str(args.epochs),
        '--batch_size', str(args.batch_size),
    ]

    logger.info(f"ノート重要度トレーニング開始: {' '.join(cmd)}")
    return run_subprocess(cmd, label="importance-train", stop_checker=stop_checker)


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
                        default='Qwen/Qwen2.5-14B-Instruct',
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
    current_training_type = 'lyrics'  # 現在の学習タイプ
    consecutive_errors = 0  # 連続エラー回数
    MAX_CONSECUTIVE_ERRORS = 3  # この回数連続失敗したら自動ループを停止

    def check_stop():
        """サブプロセス実行中に停止コマンドをチェック (5秒ごとに呼ばれる)"""
        try:
            check_cmd, _ = send_status(args.report_url, args.api_key, status='training')
            return check_cmd == 'stop'
        except Exception:
            return False

    while True:
        try:
            if not training_running:
                # サーバーにポーリング → コマンド取得
                cmd, ttype = send_status(args.report_url, args.api_key, status='idle')

                if cmd == 'stop':
                    # 停止コマンドは常に最優先
                    if auto_loop:
                        logger.info("停止コマンド受信: 自動ループを停止します")
                        auto_loop = False
                    else:
                        logger.info("停止コマンド受信 (既にアイドル状態)")

                elif cmd == 'start' or auto_loop:
                    if not auto_loop:
                        current_training_type = ttype
                        logger.info(f">>> 開始コマンド受信! 学習タイプ: {current_training_type}")
                        auto_loop = True
                    else:
                        logger.info(f">>> 自動ループ: 次のサイクルを開始します (タイプ: {current_training_type})")

                    training_running = True

                    try:
                        if current_training_type == 'importance':
                            # ノート重要度LLM: データ生成なしで直接学習
                            logger.info("--- ノート重要度LLM 学習 ---")
                            exit_code = run_importance_training(args, stop_checker=check_stop)
                        else:
                            # 歌詞LLM: データ生成 → 学習
                            # Step 1: Geminiで学習データを自動生成
                            if args.gemini_key:
                                logger.info("--- Step 1/2: 学習データ生成 ---")
                                gen_code = run_data_generation(args, stop_checker=check_stop)
                                if gen_code == -99:
                                    logger.info("停止コマンドでデータ生成を中断しました")
                                    auto_loop = False
                                    training_running = False
                                    continue
                                if gen_code != 0:
                                    logger.warning(f"データ生成に問題 (exit code: {gen_code}), 学習は既存データで続行")
                            else:
                                logger.info("データ生成スキップ (Gemini APIキー未設定)")

                            # Step 1.5: 停止コマンドが来ていないかチェック
                            check_cmd, _ = send_status(args.report_url, args.api_key, status='training')
                            if check_cmd == 'stop':
                                logger.info("停止コマンド受信: 学習をスキップしてアイドルに戻ります")
                                auto_loop = False
                                training_running = False
                                continue

                            # Step 2: LoRA学習
                            logger.info("--- Step 2/2: LoRA学習 ---")
                            exit_code = run_training(args, stop_checker=check_stop)

                        if exit_code == -99:
                            # 停止コマンドでプロセスが終了された
                            logger.info("停止コマンドで学習を中断しました")
                            auto_loop = False
                            consecutive_errors = 0
                        elif exit_code == 0:
                            consecutive_errors = 0
                            # 学習完了後、停止コマンドが来ていたかチェック
                            check_cmd, _ = send_status(args.report_url, args.api_key, status='idle')
                            if check_cmd == 'stop':
                                logger.info("停止コマンド受信: 自動ループを停止します")
                                auto_loop = False
                            else:
                                logger.info("トレーニング完了! 次のサイクルに進みます...")
                        else:
                            consecutive_errors += 1
                            logger.error(f"トレーニング失敗 (exit code: {exit_code}) [{consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}]")
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                logger.error(f"{MAX_CONSECUTIVE_ERRORS}回連続失敗 → 自動ループを停止してアイドルに戻ります")
                                auto_loop = False
                                consecutive_errors = 0
                                send_status(args.report_url, args.api_key,
                                            status='failed', error_message=f'{MAX_CONSECUTIVE_ERRORS}回連続失敗で自動停止')
                            else:
                                wait_time = 10 * (2 ** (consecutive_errors - 1))  # 10s, 20s, 40s...
                                logger.info(f"{wait_time}秒後にリトライします...")
                                time.sleep(wait_time)

                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(f"サイクル中にエラー: {e} [{consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}]")
                        send_status(args.report_url, args.api_key,
                                    status='error', error_message=str(e)[:500])
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            logger.error(f"{MAX_CONSECUTIVE_ERRORS}回連続エラー → 自動ループを停止してアイドルに戻ります")
                            auto_loop = False
                            consecutive_errors = 0
                            send_status(args.report_url, args.api_key,
                                        status='failed', error_message=f'{MAX_CONSECUTIVE_ERRORS}回連続エラーで自動停止: {str(e)[:300]}')
                        else:
                            wait_time = 10 * (2 ** (consecutive_errors - 1))
                            logger.info(f"{wait_time}秒後にリトライします...")
                            time.sleep(wait_time)
                    finally:
                        training_running = False

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("エージェント停止")
            send_status(args.report_url, args.api_key, status='idle')
            break


if __name__ == '__main__':
    main()

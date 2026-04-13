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
import re
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error

import io

# Windows環境のUTF-8対応
_log_stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=_log_stream,
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


def fetch_reviewed_indices(report_url, api_key):
    """サーバーからレビュー済み（未学習）データインデックスを取得"""
    if not report_url or not api_key:
        return None
    try:
        base_url = report_url.rsplit('/api/training/update', 1)[0]
        url = f"{base_url}/api/training/reviewed/"
        req = urllib.request.Request(
            url,
            headers={'X-Training-Api-Key': api_key},
            method='GET',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            indices = frozenset(data.get('reviewed_indices', []))
            return indices
    except Exception as e:
        logger.warning(f"レビュー済みインデックス取得失敗: {e}")
        return None


def mark_trained(report_url, api_key, indices):
    """学習完了後、使用したインデックスを学習済みとしてサーバーに通知"""
    if not report_url or not api_key or not indices:
        return False
    try:
        base_url = report_url.rsplit('/api/training/update', 1)[0]
        url = f"{base_url}/api/training/reviewed/"
        payload = json.dumps({'trained_indices': sorted(indices)}).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                'X-Training-Api-Key': api_key,
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            marked = data.get('marked', 0)
            logger.info(f"学習済みマーク完了: {marked} 件")
            return True
    except Exception as e:
        logger.warning(f"学習済みマーク失敗: {e}")
        return False


def sync_training_data(report_url, api_key, action='sync'):
    """sync_data.py を使って学習データを同期する

    action: 'pull' | 'push' | 'sync'
    """
    if not report_url or not api_key:
        logger.warning("同期スキップ: URL/APIキー未設定")
        return False

    base_url = report_url.rsplit('/api/training/update', 1)[0]

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import sync_data
        import importlib
        importlib.reload(sync_data)

        if action == 'pull':
            result = sync_data.pull(base_url, api_key, dry_run=False, timeout=60)
        elif action == 'push':
            result = sync_data.push(base_url, api_key, dry_run=False, timeout=60)
        else:  # sync
            result = sync_data.sync(base_url, api_key, dry_run=False, timeout=60)

        if result.get('ok'):
            logger.info(f"データ同期完了 ({action})")
            return True
        else:
            logger.warning(f"データ同期失敗 ({action}): {result.get('error', '不明')}")
            return False
    except Exception as e:
        logger.warning(f"データ同期エラー ({action}): {e}")
        return False


def get_python_exe():
    """Python実行ファイルを決定"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    candidates = [
        os.path.join(script_dir, 'venv', 'bin', 'python'),
        os.path.join(script_dir, 'venv', 'Scripts', 'python.exe'),
        os.path.join(project_root, '.venv', 'bin', 'python'),
        os.path.join(project_root, '.venv', 'Scripts', 'python.exe'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return sys.executable


def run_subprocess(cmd, label="process", stop_checker=None):
    """サブプロセスを実行し出力をログに流す"""
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
        try:
            line = output_queue.get(timeout=1.0)
            if line is None:
                break
            line = line.rstrip()
            if line:
                logger.info(f"  [{label}] {line}")
        except queue.Empty:
            pass

        if process.poll() is not None:
            while not output_queue.empty():
                line = output_queue.get_nowait()
                if line is None:
                    break
                line = line.rstrip()
                if line:
                    logger.info(f"  [{label}] {line}")
            break

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
                return -99

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


# ── 推論サーバー + Cloudflare Tunnel ──

CLOUDFLARED_PATH = r'C:\Program Files (x86)\cloudflared\cloudflared.exe'
SERVE_PORT = 8000


def start_inference_server():
    """serve.py をバックグラウンドで起動し、プロセスを返す"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = get_python_exe()
    serve_script = os.path.join(script_dir, 'serve.py')

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    if 'HF_HOME' not in env and os.path.exists('B:\\huggingface_cache'):
        env['HF_HOME'] = 'B:\\huggingface_cache'

    cmd = [
        python_exe, '-u', serve_script,
        '--base_model', 'Qwen/Qwen2.5-7B-Instruct',
        '--port', str(SERVE_PORT),
        '--host', '127.0.0.1',
        '--no_lora',
    ]
    logger.info(f"推論サーバー起動: {' '.join(cmd)}")
    proc = subprocess.Popen(
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

    def _log_output():
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.info(f"  [serve] {line}")
        except Exception:
            pass

    t = threading.Thread(target=_log_output, daemon=True)
    t.start()
    return proc


def start_cloudflare_tunnel(port=SERVE_PORT):
    """cloudflared quick tunnel を起動し、(プロセス, トンネルURL) を返す"""
    if not os.path.exists(CLOUDFLARED_PATH):
        logger.warning(f"cloudflared が見つかりません: {CLOUDFLARED_PATH}")
        return None, ''

    cmd = [CLOUDFLARED_PATH, 'tunnel', '--url', f'http://127.0.0.1:{port}']
    logger.info(f"Cloudflare Tunnel 起動: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
    )

    tunnel_url = ''
    url_pattern = re.compile(r'(https://[a-z0-9-]+\.trycloudflare\.com)')

    deadline = time.time() + 60

    def _read_and_find_url():
        nonlocal tunnel_url
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.info(f"  [tunnel] {line}")
                m = url_pattern.search(line)
                if m and not tunnel_url:
                    tunnel_url = m.group(1)
        except Exception:
            pass

    t = threading.Thread(target=_read_and_find_url, daemon=True)
    t.start()

    while time.time() < deadline:
        if tunnel_url:
            break
        if proc.poll() is not None:
            break
        time.sleep(1)

    if tunnel_url:
        logger.info(f"トンネルURL取得: {tunnel_url}")
    else:
        logger.warning("トンネルURLを取得できませんでした")

    return proc, tunnel_url


def wait_for_server_ready(port=SERVE_PORT, timeout=300):
    """推論サーバーの /health が応答するまで待機"""
    deadline = time.time() + timeout
    url = f'http://127.0.0.1:{port}/health'
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info("推論サーバー準備完了")
                    return True
        except Exception:
            pass
        time.sleep(5)
    logger.warning(f"推論サーバーが {timeout}秒以内に応答しませんでした")
    return False


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
                        default=os.getenv('UTAMEMO_OUTPUT_DIR',
                                          '/tmp/utamemo-lora' if os.name != 'nt' else 'C:\\temp\\utamemo-lora'))
    parser.add_argument('--gemini_key', type=str,
                        default=os.getenv('GEMINI_API_KEY', ''),
                        help='Gemini APIキー (データ自動生成用)')
    parser.add_argument('--gen_count', type=int, default=5,
                        help='各サイクルで生成する新規テーマ数 (デフォルト: 5)')
    parser.add_argument('--no_serve', action='store_true',
                        help='推論サーバー+トンネルの自動起動を無効化')
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

    # ── 推論サーバー + Cloudflare Tunnel 自動起動 ──
    serve_proc = None
    tunnel_proc = None
    tunnel_url = ''

    if not args.no_serve:
        logger.info("推論サーバーを自動起動します...")
        serve_proc = start_inference_server()
        if serve_proc and serve_proc.poll() is None:
            logger.info("推論サーバーのモデル読込を待機中 (最大5分)...")
            if wait_for_server_ready(SERVE_PORT, timeout=300):
                tunnel_proc, tunnel_url = start_cloudflare_tunnel(SERVE_PORT)
            else:
                logger.warning("推論サーバー起動失敗、トンネルなしで続行します")
        else:
            logger.warning("推論サーバープロセスが即終了しました")

    # 初回idle送信
    status_kwargs = {'status': 'idle', 'error_message': ''}
    if tunnel_url:
        status_kwargs['tunnel_url'] = tunnel_url
    send_status(args.report_url, args.api_key, **status_kwargs)
    logger.info("初回ステータス送信完了 → ダッシュボードからの開始コマンドを待機します")

    training_running = False
    auto_loop = False
    current_training_type = 'lyrics'
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3
    last_tunnel_check = time.time()
    TUNNEL_CHECK_INTERVAL = 120
    tunnel_fail_count = 0
    last_trained_indices = None

    def check_stop():
        """停止コマンドをチェック"""
        try:
            check_cmd, _ = send_status(args.report_url, args.api_key, status='training')
            return check_cmd == 'stop'
        except Exception:
            return False

    idle_poll_count = 0

    while True:
        try:
            if not training_running:
                cmd, ttype = send_status(args.report_url, args.api_key, status='idle', error_message='')

                idle_poll_count += 1
                if idle_poll_count % 30 == 1:
                    logger.info(f"ポーリング中... (コマンド待機中, 応答: {cmd})")

                if cmd == 'stop':
                    if auto_loop:
                        logger.info("停止コマンド受信: 自動ループを停止します")
                        auto_loop = False
                    else:
                        logger.info("停止コマンド受信 (既にアイドル状態)")

                elif cmd == 'start_serve':
                    if serve_proc and serve_proc.poll() is None:
                        logger.info("推論サーバーは既に起動中です")
                    else:
                        logger.info(">>> start_serve コマンド受信: 推論サーバーを起動します")
                        serve_proc = start_inference_server()
                        if serve_proc and serve_proc.poll() is None:
                            logger.info("推論サーバーのモデル読込を待機中 (最大5分)...")
                            if wait_for_server_ready(SERVE_PORT, timeout=300):
                                tunnel_proc, tunnel_url = start_cloudflare_tunnel(SERVE_PORT)
                                if tunnel_url:
                                    send_status(args.report_url, args.api_key,
                                                status='idle', tunnel_url=tunnel_url)
                                    logger.info(f"推論サーバー起動完了: {tunnel_url}")
                                else:
                                    logger.warning("トンネル起動失敗")
                            else:
                                logger.warning("推論サーバー起動タイムアウト")
                        else:
                            logger.warning("推論サーバープロセスが即終了しました")

                elif cmd == 'start' or auto_loop:
                    if not auto_loop:
                        current_training_type = ttype
                        logger.info(f">>> 開始コマンド受信! 学習タイプ: {current_training_type}")
                        auto_loop = True
                        last_trained_indices = None
                    else:
                        logger.info(f">>> 自動ループ: 次のサイクルを開始します (タイプ: {current_training_type})")

                    training_running = True
                    idle_poll_count = 0

                    if serve_proc and serve_proc.poll() is None:
                        logger.info("学習開始: 推論サーバーを一時停止してGPUメモリを解放します")
                        serve_proc.terminate()
                        try:
                            serve_proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            serve_proc.kill()
                            serve_proc.wait()
                        if tunnel_proc and tunnel_proc.poll() is None:
                            tunnel_proc.terminate()
                            try:
                                tunnel_proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                tunnel_proc.kill()
                        import gc
                        gc.collect()
                        logger.info("推論サーバー停止完了")

                    try:
                        if auto_loop and current_training_type == 'lyrics':
                            current_indices = fetch_reviewed_indices(args.report_url, args.api_key)
                            if current_indices is not None and current_indices == last_trained_indices:
                                logger.info("レビュー済みデータに変化なし → 自動ループを停止します")
                                auto_loop = False
                                training_running = False
                                send_status(args.report_url, args.api_key,
                                            status='idle', error_message='レビュー済みデータ消費完了 (新しいレビューを追加してください)')
                                continue

                        if current_training_type == 'importance':
                            logger.info("--- ノート重要度LLM 学習 ---")
                            exit_code = run_importance_training(args, stop_checker=check_stop)
                        else:
                            check_cmd, _ = send_status(args.report_url, args.api_key, status='training')
                            if check_cmd == 'stop':
                                logger.info("停止コマンド受信: 学習をスキップしてアイドルに戻ります")
                                auto_loop = False
                                training_running = False
                                continue

                            logger.info("--- LoRA学習 ---")
                            logger.info("--- データ同期 (Pull) ---")
                            sync_training_data(args.report_url, args.api_key, action='pull')

                            pre_train_indices = fetch_reviewed_indices(args.report_url, args.api_key)
                            exit_code = run_training(args, stop_checker=check_stop)

                            if exit_code == 0:
                                if pre_train_indices is not None:
                                    last_trained_indices = pre_train_indices
                                    mark_trained(args.report_url, args.api_key, pre_train_indices)
                                logger.info("--- データ同期 (Push) ---")
                                sync_training_data(args.report_url, args.api_key, action='push')

                        if exit_code == -99:
                            logger.info("停止コマンドで学習を中断しました")
                            auto_loop = False
                            consecutive_errors = 0
                        elif exit_code == 0:
                            consecutive_errors = 0
                            check_cmd, _ = send_status(args.report_url, args.api_key, status='idle', error_message='')
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
                        if not args.no_serve:
                            logger.info("学習完了: 推論サーバーを再起動します...")
                            serve_proc = start_inference_server()
                            if serve_proc and serve_proc.poll() is None:
                                if wait_for_server_ready(SERVE_PORT, timeout=300):
                                    tunnel_proc, tunnel_url = start_cloudflare_tunnel(SERVE_PORT)
                                    if tunnel_url:
                                        send_status(args.report_url, args.api_key,
                                                    status='idle', tunnel_url=tunnel_url)
                                        tunnel_fail_count = 0
                                        logger.info(f"推論サーバー再起動完了: {tunnel_url}")
                                    else:
                                        logger.warning("トンネル再起動失敗")
                                else:
                                    logger.warning("推論サーバー再起動タイムアウト")

            # トンネル健全性チェック
            now = time.time()
            if not args.no_serve and tunnel_url and now - last_tunnel_check >= TUNNEL_CHECK_INTERVAL:
                last_tunnel_check = now
                if serve_proc and serve_proc.poll() is not None:
                    logger.warning("推論サーバーが停止しています。再起動します...")
                    serve_proc = start_inference_server()
                    if serve_proc and serve_proc.poll() is None:
                        if wait_for_server_ready(SERVE_PORT, timeout=300):
                            if tunnel_proc and tunnel_proc.poll() is None:
                                tunnel_proc.terminate()
                            tunnel_proc, tunnel_url = start_cloudflare_tunnel(SERVE_PORT)
                            if tunnel_url:
                                send_status(args.report_url, args.api_key,
                                            status='idle', tunnel_url=tunnel_url)
                                tunnel_fail_count = 0
                elif tunnel_proc:
                    tunnel_dead = tunnel_proc.poll() is not None
                    tunnel_unreachable = False
                    if not tunnel_dead and tunnel_url:
                        try:
                            req = urllib.request.Request(f'{tunnel_url}/health', method='GET')
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                if resp.status == 200:
                                    tunnel_fail_count = 0  # 正常
                        except Exception:
                            tunnel_unreachable = True
                    if tunnel_dead or tunnel_unreachable:
                        tunnel_fail_count += 1
                        reason = "プロセス停止" if tunnel_dead else "到達不能"
                        logger.warning(f"トンネル{reason} (連続{tunnel_fail_count}回)")
                        if tunnel_fail_count >= 2:
                            logger.info("トンネルを再起動します...")
                            if tunnel_proc.poll() is None:
                                tunnel_proc.terminate()
                                try:
                                    tunnel_proc.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    tunnel_proc.kill()
                            tunnel_proc, tunnel_url = start_cloudflare_tunnel(SERVE_PORT)
                            if tunnel_url:
                                send_status(args.report_url, args.api_key,
                                            status='idle', tunnel_url=tunnel_url)
                                tunnel_fail_count = 0
                                logger.info(f"トンネル再起動完了: {tunnel_url}")
                            else:
                                logger.warning("トンネル再起動失敗")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("エージェント停止")
            for name, proc in [('tunnel', tunnel_proc), ('serve', serve_proc)]:
                if proc and proc.poll() is None:
                    logger.info(f"{name} プロセスを終了します...")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            send_status(args.report_url, args.api_key, status='idle',
                        error_message='', tunnel_url='')
            break


if __name__ == '__main__':
    main()

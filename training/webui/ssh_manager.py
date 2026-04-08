#!/usr/bin/env python3
"""
SSH経由で学校GPUマシンにジョブを投げるマネージャー

学校のLinux (RTX 4080 x2) にSSH接続し、学習・推論を実行する。
SSHトンネルでポートフォワードし、自宅からサーバーにアクセスも可能。

前提:
  - 学校PCにSSH公開鍵を登録済み
  - 学校PCにconda/venv環境 + training/のコードが配備済み

使い方:
  from webui.ssh_manager import SSHJobManager
  mgr = SSHJobManager(host="192.168.x.x", user="student", key_path="~/.ssh/id_rsa")
  mgr.test_connection()
  mgr.start_training(data_path="data/lyrics.json", model="Qwen/Qwen2.5-7B-Instruct")
  mgr.get_status()
"""

import json
import logging
import os
import subprocess
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SSHConfig:
    """SSH接続設定"""
    host: str = ""
    port: int = 22
    user: str = ""
    key_path: str = ""
    remote_project_dir: str = "~/utamemo-training"
    remote_venv_activate: str = "source ~/utamemo-training/venv/bin/activate"
    # SSHトンネル設定
    tunnel_local_port: int = 8000
    tunnel_remote_port: int = 8000

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "SSHConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: str = "ssh_config.json"):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        logger.info(f"SSH設定を保存: {path}")

    @classmethod
    def load(cls, path: str = "ssh_config.json") -> "SSHConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


class SSHJobManager:
    """学校GPUへのSSHジョブ管理"""

    def __init__(self, config: Optional[SSHConfig] = None):
        self.config = config or SSHConfig()
        self._tunnel_process: Optional[subprocess.Popen] = None

    def _ssh_base_cmd(self) -> list[str]:
        """SSH基本コマンド構築"""
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        if self.config.key_path:
            cmd += ["-i", os.path.expanduser(self.config.key_path)]
        if self.config.port != 22:
            cmd += ["-p", str(self.config.port)]
        cmd.append(f"{self.config.user}@{self.config.host}")
        return cmd

    def _run_remote(self, command: str, timeout: int = 30) -> tuple[int, str, str]:
        """リモートコマンドを実行して結果を返す"""
        ssh_cmd = self._ssh_base_cmd() + [command]
        logger.info(f"リモート実行: {command[:80]}...")
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "タイムアウト"
        except FileNotFoundError:
            return -1, "", "sshコマンドが見つかりません。OpenSSHをインストールしてください。"

    def test_connection(self) -> dict:
        """SSH接続テスト & GPU情報取得"""
        code, out, err = self._run_remote("nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader")
        if code != 0:
            return {"connected": False, "error": err}

        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gpus.append({
                    "name": parts[0],
                    "total_memory": parts[1],
                    "free_memory": parts[2],
                })

        return {"connected": True, "gpus": gpus}

    def sync_code(self, local_dir: str = ".") -> bool:
        """ローカルのtraining/コードを学校PCに同期"""
        remote = f"{self.config.user}@{self.config.host}:{self.config.remote_project_dir}"
        rsync_cmd = [
            "rsync", "-avz", "--delete",
            "--exclude", "venv/", "--exclude", "__pycache__/",
            "--exclude", "output/", "--exclude", ".git/",
            "--exclude", "*.pyc",
        ]
        if self.config.key_path:
            rsync_cmd += ["-e", f"ssh -i {os.path.expanduser(self.config.key_path)} -p {self.config.port}"]
        elif self.config.port != 22:
            rsync_cmd += ["-e", f"ssh -p {self.config.port}"]

        rsync_cmd += [f"{local_dir}/", remote + "/"]

        logger.info(f"コード同期中: {local_dir} → {remote}")
        try:
            result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info("コード同期完了")
                return True
            logger.error(f"rsync失敗: {result.stderr}")
            return False
        except FileNotFoundError:
            # Windows: rsyncが無い場合はscpフォールバック
            logger.warning("rsyncが見つかりません。scpで必須ファイルのみ転送します。")
            return self._scp_fallback(local_dir)

    def _scp_fallback(self, local_dir: str) -> bool:
        """rsyncが無い場合のscpフォールバック"""
        essential_files = [
            "train.py", "serve.py", "build_importance_dataset.py",
            "requirements_training.txt",
        ]
        scp_base = ["scp"]
        if self.config.key_path:
            scp_base += ["-i", os.path.expanduser(self.config.key_path)]
        if self.config.port != 22:
            scp_base += ["-P", str(self.config.port)]

        remote_base = f"{self.config.user}@{self.config.host}:{self.config.remote_project_dir}/"

        # リモートディレクトリ作成
        self._run_remote(f"mkdir -p {self.config.remote_project_dir}")

        success = True
        for f in essential_files:
            local_path = os.path.join(local_dir, f)
            if os.path.exists(local_path):
                cmd = scp_base + [local_path, remote_base]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    logger.error(f"scp失敗 ({f}): {result.stderr}")
                    success = False
            else:
                logger.warning(f"ファイルが見つかりません: {local_path}")
        return success

    def start_training(
        self,
        data_path: str,
        model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        epochs: int = 5,
        task: str = "lyrics",
        extra_args: str = "",
    ) -> dict:
        """学校GPUで学習を開始 (バックグラウンド, nohup)"""
        remote_dir = self.config.remote_project_dir
        activate = self.config.remote_venv_activate

        if task == "lyrics":
            train_cmd = (
                f"cd {remote_dir} && {activate} && "
                f"nohup python train.py "
                f"--model_name {shlex.quote(model_name)} "
                f"--data_path {shlex.quote(data_path)} "
                f"--epochs {epochs} "
                f"{extra_args} "
                f"> train.log 2>&1 &"
            )
        elif task == "importance":
            train_cmd = (
                f"cd {remote_dir} && {activate} && "
                f"nohup python -m note_importance.train_scorer "
                f"--model_name {shlex.quote(model_name)} "
                f"--data_path {shlex.quote(data_path)} "
                f"--epochs {epochs} "
                f"{extra_args} "
                f"> train_importance.log 2>&1 &"
            )
        else:
            return {"started": False, "error": f"不明なタスク: {task}"}

        code, out, err = self._run_remote(train_cmd, timeout=15)
        if code == 0:
            return {"started": True, "task": task, "model": model_name}
        return {"started": False, "error": err}

    def get_status(self, task: str = "lyrics") -> dict:
        """学習の進捗を取得 (ログの末尾を取得)"""
        log_file = "train.log" if task == "lyrics" else "train_importance.log"
        remote_dir = self.config.remote_project_dir

        # プロセス確認
        code, out, _ = self._run_remote(f"pgrep -f 'python.*train' | head -5")
        is_running = code == 0 and out.strip() != ""

        # ログ末尾取得
        _, log_tail, _ = self._run_remote(
            f"tail -20 {remote_dir}/{log_file} 2>/dev/null || echo '(ログなし)'"
        )

        # GPU使用状況
        _, gpu_info, _ = self._run_remote("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader")

        return {
            "running": is_running,
            "log_tail": log_tail.strip(),
            "gpu_info": gpu_info.strip(),
        }

    def stop_training(self) -> bool:
        """学習プロセスを停止"""
        code, _, _ = self._run_remote("pkill -f 'python.*train'")
        return code == 0

    def download_model(self, remote_path: str = "output/utamemo-lyrics-lora", local_path: str = "./output/") -> bool:
        """学習済みモデルをダウンロード"""
        remote = f"{self.config.user}@{self.config.host}:{self.config.remote_project_dir}/{remote_path}"
        os.makedirs(local_path, exist_ok=True)

        scp_cmd = ["scp", "-r"]
        if self.config.key_path:
            scp_cmd += ["-i", os.path.expanduser(self.config.key_path)]
        if self.config.port != 22:
            scp_cmd += ["-P", str(self.config.port)]
        scp_cmd += [remote, local_path]

        logger.info(f"モデルダウンロード: {remote} → {local_path}")
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            logger.info("ダウンロード完了")
            return True
        logger.error(f"ダウンロード失敗: {result.stderr}")
        return False

    def start_tunnel(self) -> bool:
        """SSHトンネルを開始 (学校PCのserve.pyに自宅からアクセス)"""
        if self._tunnel_process and self._tunnel_process.poll() is None:
            logger.info("トンネルは既に稼働中")
            return True

        cmd = ["ssh", "-N", "-L",
               f"{self.config.tunnel_local_port}:localhost:{self.config.tunnel_remote_port}",
               "-o", "StrictHostKeyChecking=no"]
        if self.config.key_path:
            cmd += ["-i", os.path.expanduser(self.config.key_path)]
        if self.config.port != 22:
            cmd += ["-p", str(self.config.port)]
        cmd.append(f"{self.config.user}@{self.config.host}")

        logger.info(f"SSHトンネル開始: localhost:{self.config.tunnel_local_port} → 学校PC:{self.config.tunnel_remote_port}")
        self._tunnel_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        if self._tunnel_process.poll() is not None:
            _, err = self._tunnel_process.communicate()
            logger.error(f"トンネル開始失敗: {err.decode()}")
            return False
        logger.info("SSHトンネル稼働中")
        return True

    def stop_tunnel(self):
        """SSHトンネルを停止"""
        if self._tunnel_process and self._tunnel_process.poll() is None:
            self._tunnel_process.terminate()
            self._tunnel_process.wait(timeout=5)
            logger.info("SSHトンネル停止")
        self._tunnel_process = None

    def start_serve(self, model_name: str = "Qwen/Qwen2.5-7B-Instruct", port: int = 8000) -> dict:
        """学校GPUで推論サーバーを起動"""
        remote_dir = self.config.remote_project_dir
        activate = self.config.remote_venv_activate

        cmd = (
            f"cd {remote_dir} && {activate} && "
            f"UTAMEMO_API_KEY=$UTAMEMO_API_KEY "
            f"nohup python serve.py "
            f"--base_model {shlex.quote(model_name)} "
            f"--port {port} --host 0.0.0.0 "
            f"> serve.log 2>&1 &"
        )
        code, out, err = self._run_remote(cmd, timeout=15)
        if code == 0:
            return {"started": True, "port": port}
        return {"started": False, "error": err}

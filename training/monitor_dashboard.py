#!/usr/bin/env python3
"""
UTAMEMO ローカル監視ダッシュボード

このPCから以下をまとめて確認できる:
- ローカル推論APIの生存確認
- 学校PCを含む任意ターゲットのHTTP確認
- SSH経由コマンドなど任意コマンド確認

使い方:
  python monitor_dashboard.py

設定ファイル:
  training/monitor_targets.json (無ければ training/monitor_targets.example.json を使用)
"""

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

HTML_TEMPLATE = """
<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>UTAMEMO Monitor</title>
  <style>
    :root {
      --bg1: #0f172a;
      --bg2: #111827;
      --card: rgba(255, 255, 255, 0.06);
      --text: #e5e7eb;
      --muted: #9ca3af;
      --ok: #22c55e;
      --ng: #ef4444;
      --warn: #f59e0b;
      --accent: #38bdf8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", sans-serif;
      color: var(--text);
      background: radial-gradient(circle at 0% 0%, #1d4ed8 0%, transparent 28%),
                  radial-gradient(circle at 100% 100%, #0ea5e9 0%, transparent 24%),
                  linear-gradient(135deg, var(--bg1), var(--bg2));
      min-height: 100vh;
      padding: 24px;
    }
    .wrap { max-width: 1100px; margin: 0 auto; }
    .title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }
    .title h1 { margin: 0; font-size: 28px; }
    .meta { color: var(--muted); font-size: 14px; }
    .card {
      background: var(--card);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 14px;
      padding: 14px;
      backdrop-filter: blur(8px);
      margin-bottom: 14px;
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      vertical-align: top;
    }
    th { color: #cbd5e1; font-weight: 600; }
    .status {
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
    }
    .ok { background: rgba(34, 197, 94, 0.18); color: #86efac; }
    .ng { background: rgba(239, 68, 68, 0.18); color: #fca5a5; }
    .warn { background: rgba(245, 158, 11, 0.18); color: #fcd34d; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-word;
      color: #bfdbfe;
    }
    .muted { color: var(--muted); }
    .btn {
      border: 1px solid rgba(56, 189, 248, 0.5);
      color: #bae6fd;
      background: rgba(2, 132, 199, 0.2);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 600;
    }
    .btn:hover { background: rgba(2, 132, 199, 0.32); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"title\">
      <h1>UTAMEMO Monitor</h1>
      <div>
        <button class=\"btn\" onclick=\"refreshNow()\">今すぐ更新</button>
      </div>
    </div>
    <div class=\"meta\" id=\"meta\">読み込み中...</div>

    <div class=\"card\">
      <table>
        <thead>
          <tr>
            <th>ターゲット</th>
            <th>種別</th>
            <th>状態</th>
            <th>応答時間</th>
            <th>概要</th>
            <th>詳細</th>
          </tr>
        </thead>
        <tbody id=\"rows\"></tbody>
      </table>
    </div>
  </div>

  <script>
    let timer = null;
    let refreshSec = 15;

    function statusClass(s) {
      if (s === 'ok') return 'status ok';
      if (s === 'warn') return 'status warn';
      return 'status ng';
    }

    function safe(s) {
      return (s || '').toString()
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
    }

    async function fetchStatus() {
      const res = await fetch('/api/status', { cache: 'no-store' });
      const data = await res.json();
      refreshSec = data.refresh_sec || 15;

      const meta = document.getElementById('meta');
      meta.textContent = `最終更新: ${data.generated_at}  /  自動更新: ${refreshSec}秒`;

      const rows = document.getElementById('rows');
      rows.innerHTML = '';

      for (const t of data.targets) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${safe(t.name)}</td>
          <td class=\"muted\">${safe(t.type)}</td>
          <td><span class=\"${statusClass(t.status)}\">${safe(t.status.toUpperCase())}</span></td>
          <td>${safe(t.elapsed_ms)} ms</td>
          <td>${safe(t.summary || '')}</td>
          <td><div class=\"mono\">${safe(t.detail || '')}</div></td>
        `;
        rows.appendChild(tr);
      }

      if (timer) clearTimeout(timer);
      timer = setTimeout(fetchStatus, Math.max(3, refreshSec) * 1000);
    }

    function refreshNow() {
      if (timer) clearTimeout(timer);
      fetchStatus().catch((e) => {
        document.getElementById('meta').textContent = `更新失敗: ${e}`;
      });
    }

    refreshNow();
  </script>
</body>
</html>
"""


def _truncate(text: str, max_len: int = 240) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _load_config(config_path: str) -> Dict[str, Any]:
    default_path = os.path.join(os.path.dirname(__file__), "monitor_targets.example.json")

    path = config_path if os.path.exists(config_path) else default_path
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if "targets" not in cfg:
        cfg["targets"] = []
    if "refresh_sec" not in cfg:
        cfg["refresh_sec"] = 15
    return cfg


def _check_http(target: Dict[str, Any]) -> Dict[str, Any]:
    url = target.get("url", "")
    timeout_sec = float(target.get("timeout_sec", 6))
    headers = target.get("headers", {})

    req = urllib.request.Request(url=url, headers=headers, method="GET")
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            detail = body
            summary = f"HTTP {resp.status}"
            try:
                parsed = json.loads(body)
                detail = json.dumps(parsed, ensure_ascii=False, indent=2)
                if isinstance(parsed, dict):
                    if parsed.get("status") == "ok":
                        summary = f"HTTP {resp.status} / status=ok"
                    elif parsed.get("status"):
                        summary = f"HTTP {resp.status} / status={parsed.get('status')}"
            except Exception:
                pass

            return {
                "status": "ok" if resp.status < 400 else "ng",
                "elapsed_ms": elapsed_ms,
                "summary": summary,
                "detail": _truncate(detail, 800),
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ng",
            "elapsed_ms": elapsed_ms,
            "summary": f"HTTP {e.code}",
            "detail": _truncate(str(e), 800),
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ng",
            "elapsed_ms": elapsed_ms,
            "summary": "HTTP check failed",
            "detail": _truncate(str(e), 800),
        }


def _check_command(target: Dict[str, Any]) -> Dict[str, Any]:
    command = target.get("command", "")
    timeout_sec = float(target.get("timeout_sec", 10))

    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        out = (completed.stdout or "").strip()
        err = (completed.stderr or "").strip()
        detail = out if out else err
        if out and err:
            detail = f"STDOUT:\n{out}\n\nSTDERR:\n{err}"

        if completed.returncode == 0:
            status = "ok"
            summary = "command ok"
        else:
            status = "warn"
            summary = f"exit code {completed.returncode}"

        return {
            "status": status,
            "elapsed_ms": elapsed_ms,
            "summary": summary,
            "detail": _truncate(detail or "(no output)", 1000),
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ng",
            "elapsed_ms": elapsed_ms,
            "summary": "command timeout",
            "detail": f"timeout: {timeout_sec} sec",
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ng",
            "elapsed_ms": elapsed_ms,
            "summary": "command failed",
            "detail": _truncate(str(e), 800),
        }


def _evaluate_targets(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    for target in config.get("targets", []):
        target_type = target.get("type", "http")
        name = target.get("name", "(unnamed)")

        if target_type == "http":
            checked = _check_http(target)
        elif target_type == "command":
            checked = _check_command(target)
        else:
            checked = {
                "status": "ng",
                "elapsed_ms": 0,
                "summary": "unknown type",
                "detail": f"type={target_type}",
            }

        checked["name"] = name
        checked["type"] = target_type
        results.append(checked)

    return results


CONFIG_PATH = os.environ.get(
    "UTAMEMO_MONITOR_CONFIG",
    os.path.join(os.path.dirname(__file__), "monitor_targets.json"),
)


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def api_status():
    config = _load_config(CONFIG_PATH)
    targets = _evaluate_targets(config)
    return jsonify(
        {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "refresh_sec": int(config.get("refresh_sec", 15)),
            "targets": targets,
        }
    )


def main():
    parser = argparse.ArgumentParser(description="UTAMEMO Monitor Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8765, help="bind port")
    args = parser.parse_args()

    print(f"[monitor] config: {CONFIG_PATH}")
    print(f"[monitor] open:   http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

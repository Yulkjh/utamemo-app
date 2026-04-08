#!/usr/bin/env python3
"""
UTAMEMO ローカルLLM学習プラットフォーム (Gradio UI)

知識がない人でも簡易的にLLM学習・推論を操作できるWebUI。
自宅PCでUI起動 → 学校GPUにSSHで学習ジョブを投げる。

起動方法:
  cd training
  python -m platform.app

  # ポート指定
  python -m platform.app --port 7860

機能:
  1. データ管理: ノートOCRテキストのアップロード・プレビュー
  2. 重要度スコアリング: アップロードしたテキストの重要ワード抽出
  3. 歌詞生成LLM学習: 学習データ管理・学習開始/停止・進捗監視
  4. SSH接続: 学校GPUへの接続設定・状態確認
  5. 推論テスト: 学習済みモデルで歌詞生成テスト
"""

import argparse
import json
import logging
import os
import sys
import threading
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# training/ ディレクトリをパスに追加
TRAINING_DIR = Path(__file__).resolve().parent.parent
if str(TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(TRAINING_DIR))


def launch_app(port: int = 7860, share: bool = False):
    """Gradio UIを起動"""
    try:
        import gradio as gr
    except ImportError:
        logger.error("gradioがインストールされていません: pip install gradio")
        sys.exit(1)

    from note_importance.scorer import score_text, ScoredWord
    from platform.ssh_manager import SSHJobManager, SSHConfig

    # 状態管理
    ssh_manager = SSHJobManager()
    config_path = TRAINING_DIR / "ssh_config.json"
    if config_path.exists():
        try:
            ssh_manager.config = SSHConfig.load(str(config_path))
            logger.info("SSH設定を読み込みました")
        except Exception as e:
            logger.warning(f"SSH設定の読み込み失敗: {e}")

    # =====================================================================
    # Tab 1: 重要度スコアリング
    # =====================================================================
    def analyze_importance(text, mode, max_keywords):
        if not text.strip():
            return "テキストを入力またはファイルをアップロードしてください", ""
        words = score_text(text, mode=mode, max_keywords=int(max_keywords))
        if not words:
            return "重要ワードが見つかりませんでした", ""

        # テーブル形式で表示
        table = "| 順位 | ワード | スコア | 特徴 |\n|---:|:---|:---|:---|\n"
        for i, w in enumerate(words[:30], 1):
            markers = ", ".join(w.markers) if w.markers else "-"
            table += f"| {i} | **{w.term}** | {w.final_score:.3f} | {markers} |\n"

        # JSON出力
        json_out = json.dumps(
            [{"term": w.term, "score": w.final_score, "markers": w.markers} for w in words],
            ensure_ascii=False, indent=2
        )
        return table, json_out

    def load_file_text(file):
        if file is None:
            return ""
        try:
            return Path(file.name).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"ファイル読み込みエラー: {e}"

    # =====================================================================
    # Tab 2: SSH接続
    # =====================================================================
    def save_ssh_config(host, port, user, key_path, remote_dir, venv_cmd):
        ssh_manager.config = SSHConfig(
            host=host, port=int(port), user=user,
            key_path=key_path, remote_project_dir=remote_dir,
            remote_venv_activate=venv_cmd,
        )
        ssh_manager.config.save(str(config_path))
        return "✅ SSH設定を保存しました"

    def test_ssh():
        result = ssh_manager.test_connection()
        if result["connected"]:
            gpu_info = "\n".join(
                f"  - {g['name']}: {g['total_memory']} (空き: {g['free_memory']})"
                for g in result["gpus"]
            )
            return f"✅ 接続成功!\n\nGPU情報:\n{gpu_info}"
        return f"❌ 接続失敗: {result.get('error', '不明なエラー')}"

    def sync_code():
        success = ssh_manager.sync_code(str(TRAINING_DIR))
        return "✅ コード同期完了" if success else "❌ 同期失敗 (ログを確認)"

    # =====================================================================
    # Tab 3: 学習管理
    # =====================================================================
    def start_training_job(task, model_name, data_path, epochs, extra_args):
        result = ssh_manager.start_training(
            data_path=data_path,
            model_name=model_name,
            epochs=int(epochs),
            task=task,
            extra_args=extra_args,
        )
        if result.get("started"):
            return f"✅ 学習開始!\nタスク: {task}\nモデル: {model_name}"
        return f"❌ 学習開始失敗: {result.get('error', '不明')}"

    def check_training_status(task):
        status = ssh_manager.get_status(task=task)
        state = "🟢 実行中" if status["running"] else "⚪ 停止中"
        return f"状態: {state}\n\nGPU:\n{status['gpu_info']}\n\nログ (末尾):\n{status['log_tail']}"

    def stop_training_job():
        success = ssh_manager.stop_training()
        return "✅ 停止しました" if success else "❌ 停止失敗"

    def download_trained_model(remote_path):
        success = ssh_manager.download_model(remote_path=remote_path)
        return "✅ ダウンロード完了" if success else "❌ ダウンロード失敗"

    # =====================================================================
    # Tab 4: 歌詞生成テスト
    # =====================================================================
    def generate_lyrics_local(text, genre, model_path):
        """ローカルモデルで歌詞生成テスト"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            return "transformersがインストールされていません"

        if not text.strip():
            return "テキストを入力してください"

        try:
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float16,
                device_map="auto",
            )
            model.eval()

            system_prompt = (
                "あなたは暗記学習用の歌詞を作成する専門AIです。"
                "エグスプロージョン「本能寺の変」のようなスタイルで、"
                "学習内容をキャッチーでリズミカルな歌詞にしてください。"
                "韻を踏み、繰り返しのフレーズを使い、覚えやすくしてください。"
            )
            user_prompt = f"以下の学習テキストを{genre}ジャンルの覚えやすい歌詞にしてください:\n\n{text}"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

            import torch
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.8,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.2,
                )
            result = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            return result

        except Exception as e:
            return f"生成エラー: {e}"

    # =====================================================================
    # UI構築
    # =====================================================================
    with gr.Blocks(
        title="UTAMEMO LLM学習プラットフォーム",
        theme=gr.themes.Soft(primary_hue="orange"),
    ) as app:
        gr.Markdown("# 🎵 UTAMEMO ローカルLLM学習プラットフォーム")
        gr.Markdown("ノート重要度スコアリング & 歌詞生成LLMの学習・推論を管理")

        with gr.Tabs():
            # ----- Tab 1: 重要度スコアリング -----
            with gr.TabItem("📝 重要度スコアリング"):
                gr.Markdown("### ノートOCRテキストから重要ワードを抽出・スコアリング")
                with gr.Row():
                    with gr.Column(scale=2):
                        input_file = gr.File(label="テキストファイルをアップロード", file_types=[".txt"])
                        input_text = gr.Textbox(
                            label="テキスト入力",
                            placeholder="ここにOCRテキストを貼り付け...\n\n視覚マーカー例:\n[red]赤字テキスト[/red]\n[bold]太字テキスト[/bold]\n【重要ワード】",
                            lines=12,
                        )
                        with gr.Row():
                            mode = gr.Radio(
                                ["rule", "hybrid"],
                                value="rule",
                                label="モード",
                                info="rule=ルールベースのみ(高速), hybrid=ルール+LLM(高精度)",
                            )
                            max_kw = gr.Slider(10, 100, value=50, step=5, label="最大キーワード数")
                        analyze_btn = gr.Button("🔍 スコアリング実行", variant="primary")
                    with gr.Column(scale=2):
                        result_table = gr.Markdown(label="結果")
                        result_json = gr.Code(label="JSON出力", language="json")

                input_file.change(load_file_text, inputs=[input_file], outputs=[input_text])
                analyze_btn.click(
                    analyze_importance,
                    inputs=[input_text, mode, max_kw],
                    outputs=[result_table, result_json],
                )

            # ----- Tab 2: SSH接続 -----
            with gr.TabItem("🔌 SSH接続 (学校GPU)"):
                gr.Markdown("### 学校のLinux GPU (RTX 4080 x2) への接続設定")
                with gr.Row():
                    with gr.Column():
                        ssh_host = gr.Textbox(label="ホスト (IPアドレス)", value=ssh_manager.config.host, placeholder="192.168.x.x")
                        ssh_port = gr.Number(label="ポート", value=ssh_manager.config.port)
                        ssh_user = gr.Textbox(label="ユーザー名", value=ssh_manager.config.user, placeholder="student")
                        ssh_key = gr.Textbox(label="秘密鍵パス", value=ssh_manager.config.key_path, placeholder="~/.ssh/id_rsa")
                        ssh_remote_dir = gr.Textbox(label="リモートプロジェクトディレクトリ", value=ssh_manager.config.remote_project_dir)
                        ssh_venv = gr.Textbox(label="venv起動コマンド", value=ssh_manager.config.remote_venv_activate)
                    with gr.Column():
                        ssh_save_btn = gr.Button("💾 設定保存")
                        ssh_save_msg = gr.Textbox(label="", interactive=False)
                        ssh_test_btn = gr.Button("🔗 接続テスト", variant="primary")
                        ssh_test_msg = gr.Textbox(label="接続結果", lines=5, interactive=False)
                        ssh_sync_btn = gr.Button("📤 コード同期")
                        ssh_sync_msg = gr.Textbox(label="", interactive=False)

                ssh_save_btn.click(
                    save_ssh_config,
                    inputs=[ssh_host, ssh_port, ssh_user, ssh_key, ssh_remote_dir, ssh_venv],
                    outputs=[ssh_save_msg],
                )
                ssh_test_btn.click(test_ssh, outputs=[ssh_test_msg])
                ssh_sync_btn.click(sync_code, outputs=[ssh_sync_msg])

            # ----- Tab 3: 学習管理 -----
            with gr.TabItem("🎓 学習管理"):
                gr.Markdown("### 学校GPUで学習ジョブを管理")
                with gr.Row():
                    with gr.Column():
                        train_task = gr.Radio(
                            ["lyrics", "importance"],
                            value="lyrics",
                            label="タスク",
                            info="lyrics=歌詞生成モデル, importance=重要度スコアリングモデル",
                        )
                        train_model = gr.Dropdown(
                            choices=[
                                "Qwen/Qwen2.5-7B-Instruct",
                                "Qwen/Qwen2.5-14B-Instruct",
                                "meta-llama/Meta-Llama-3-8B-Instruct",
                                "google/gemma-2-9b-it",
                                "Qwen/Qwen2.5-1.5B-Instruct",
                            ],
                            value="Qwen/Qwen2.5-7B-Instruct",
                            label="ベースモデル",
                        )
                        train_data = gr.Textbox(
                            label="データパス (リモート)",
                            value="data/lyrics_training_data.json",
                            placeholder="data/lyrics_training_data.json",
                        )
                        train_epochs = gr.Slider(1, 30, value=5, step=1, label="エポック数")
                        train_extra = gr.Textbox(label="追加引数", placeholder="--lora_rank 32 --batch_size 2")
                        with gr.Row():
                            train_start_btn = gr.Button("🚀 学習開始", variant="primary")
                            train_stop_btn = gr.Button("⏹ 学習停止", variant="stop")
                        train_msg = gr.Textbox(label="結果", interactive=False)

                    with gr.Column():
                        train_status_btn = gr.Button("🔄 状態更新")
                        train_status = gr.Textbox(label="学習状態", lines=15, interactive=False)
                        gr.Markdown("---")
                        dl_path = gr.Textbox(label="モデルパス (リモート)", value="output/utamemo-lyrics-lora")
                        dl_btn = gr.Button("📥 モデルダウンロード")
                        dl_msg = gr.Textbox(label="", interactive=False)

                train_start_btn.click(
                    start_training_job,
                    inputs=[train_task, train_model, train_data, train_epochs, train_extra],
                    outputs=[train_msg],
                )
                train_stop_btn.click(stop_training_job, outputs=[train_msg])
                train_status_btn.click(check_training_status, inputs=[train_task], outputs=[train_status])
                dl_btn.click(download_trained_model, inputs=[dl_path], outputs=[dl_msg])

            # ----- Tab 4: 歌詞生成テスト -----
            with gr.TabItem("🎤 歌詞生成テスト"):
                gr.Markdown("### 本能寺の変スタイル！学習内容をキャッチーな歌詞に")
                gr.Markdown("エグスプロージョンのように、学習テキストを面白くリズミカルな歌詞に変換します。")
                with gr.Row():
                    with gr.Column():
                        lyrics_text = gr.Textbox(
                            label="学習テキスト",
                            placeholder="1582年、本能寺の変。織田信長は家臣の明智光秀に討たれた...",
                            lines=8,
                        )
                        lyrics_genre = gr.Dropdown(
                            choices=["pop", "rock", "hip-hop", "EDM", "R&B", "演歌"],
                            value="pop",
                            label="ジャンル",
                        )
                        lyrics_model = gr.Textbox(
                            label="モデルパス",
                            value="Qwen/Qwen2.5-1.5B-Instruct",
                            info="学習済みLoRAパス or ベースモデル名",
                        )
                        lyrics_btn = gr.Button("🎵 歌詞生成", variant="primary")
                    with gr.Column():
                        lyrics_output = gr.Textbox(label="生成された歌詞", lines=15, interactive=False)

                lyrics_btn.click(
                    generate_lyrics_local,
                    inputs=[lyrics_text, lyrics_genre, lyrics_model],
                    outputs=[lyrics_output],
                )

            # ----- Tab 5: ヘルプ -----
            with gr.TabItem("❓ ヘルプ"):
                gr.Markdown("""
### 使い方ガイド

#### 1. 初回セットアップ
1. **SSH接続**タブで学校PCの接続情報を入力して保存
2. **接続テスト**でGPUが見えることを確認
3. **コード同期**でtraining/のコードを学校PCに転送

#### 2. 重要度スコアリング
- **ルールベースモード**: LLM不要、すぐに使える
- **ハイブリッドモード**: ルール + LLMで高精度 (GPUが必要)
- OCRテキストに `[red]...[/red]`, `[bold]...[/bold]` 等のマーカーを付けると精度UP

#### 3. 歌詞生成LLM学習
1. 学習データ (JSON) を準備して学校PCに配置
2. **学習管理**タブでモデル・エポック数を選択して学習開始
3. 学習完了後、モデルをダウンロード
4. **歌詞生成テスト**タブで試す

#### 4. ハードウェア構成
| マシン | GPU | VRAM | 用途 |
|:---|:---|:---|:---|
| 自宅PC | RTX 4060 Ti | 16GB | UI・テスト・小モデル学習 |
| 学校PC | RTX 4080 x2 | 16GB x2 | 本格学習・大モデル推論 |

#### 5. 推奨モデル
| モデル | VRAM目安 | 用途 |
|:---|:---|:---|
| Qwen2.5-1.5B | ~4GB | テスト・デバッグ |
| Qwen2.5-7B | ~8GB | 歌詞生成 (4060Ti OK) |
| Qwen2.5-14B | ~16GB | 高品質生成 (4060Ti ギリギリ) |
| Llama 3 8B | ~10GB | 歌詞生成 (4080 推奨) |

#### 6. OCRマーカー形式
```
[red]赤字 (最重要)[/red]
[bold]太字[/bold]
[underline]下線[/underline]
[highlight]蛍光ペン[/highlight]
[box]枠囲み[/box]
[star]★マーク[/star]
【括弧で囲まれた用語】
```
                """)

    app.launch(server_port=port, share=share)


def main():
    parser = argparse.ArgumentParser(description="UTAMEMO LLM学習プラットフォーム")
    parser.add_argument("--port", type=int, default=7860, help="UIのポート番号")
    parser.add_argument("--share", action="store_true", help="Gradio公開リンクを生成")
    args = parser.parse_args()
    launch_app(port=args.port, share=args.share)


if __name__ == "__main__":
    main()

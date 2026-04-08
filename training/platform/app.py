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
    from ocr_processor import get_ocr, SUPPORTED_EXTENSIONS, DEFAULT_MODEL
    from build_importance_dataset import score_keywords

    # 状態管理
    ssh_manager = SSHJobManager()
    notebook_ocr = None  # 遅延初期化 (OCRタブ利用時にロード)
    config_path = TRAINING_DIR / "ssh_config.json"
    if config_path.exists():
        try:
            ssh_manager.config = SSHConfig.load(str(config_path))
            logger.info("SSH設定を読み込みました")
        except Exception as e:
            logger.warning(f"SSH設定の読み込み失敗: {e}")

    # =====================================================================
    # Tab 0: ノート画像アップロード → OCR → スコアリング → データセット
    # =====================================================================
    def process_notebook_images(files, ocr_model_name, progress=gr.Progress()):
        """画像ファイルを一括 OCR → スコアリング → JSONL に追加"""
        nonlocal notebook_ocr
        if not files:
            return "画像を選択してください", "", ""

        try:
            progress(0, desc=f"モデルをロード中: {ocr_model_name}")
            notebook_ocr = get_ocr(ocr_model_name)
        except Exception as e:
            return f"❌ モデルのロードに失敗: {e}", "", ""

        # 出力先
        ocr_dir = TRAINING_DIR / "data" / "ocr_texts"
        ocr_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = TRAINING_DIR / "data" / "importance_dataset.jsonl"

        results = []
        all_records = []
        total = len(files)

        for idx, file_path in enumerate(files):
            fname = Path(file_path).name
            progress((idx) / total, desc=f"OCR処理中: {fname}")

            # 拡張子チェック
            ext = Path(file_path).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                results.append(f"⚠ {fname}: 非対応形式 ({ext})")
                continue

            # OCR
            text = notebook_ocr.extract_text(str(file_path))
            if not text:
                results.append(f"❌ {fname}: OCR失敗")
                continue

            # テキスト保存
            txt_path = ocr_dir / f"{Path(file_path).stem}.txt"
            txt_path.write_text(text, encoding="utf-8")

            # スコアリング
            keywords = score_keywords(text, max_keywords=20)
            record = {
                "source_file": fname,
                "char_count": len(text),
                "ranked_keywords": [{"term": t, "score": s} for t, s in keywords],
                "text": text,
            }
            all_records.append(record)
            top3 = ", ".join(f"{t}({s})" for t, s in keywords[:3]) if keywords else "なし"
            results.append(f"✅ {fname}: {len(text)}文字, 上位キーワード: {top3}")

        # JSONL に追記
        if all_records:
            with dataset_path.open("a", encoding="utf-8") as f:
                for rec in all_records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        progress(1.0, desc="完了")

        # サマリー
        ok = sum(1 for r in results if r.startswith("✅"))
        summary = f"## 処理結果: {ok}/{total} 成功\n\n"
        summary += f"- OCRテキスト保存先: `data/ocr_texts/`\n"
        summary += f"- データセット追記先: `data/importance_dataset.jsonl`\n"
        summary += f"- データセット累計: {_count_jsonl_records(dataset_path)} レコード\n"

        log = "\n".join(results)

        # 最後に処理した画像のOCR結果をプレビュー
        preview = all_records[-1]["text"][:2000] if all_records else ""

        return summary, log, preview

    def _count_jsonl_records(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(1 for _ in path.open(encoding="utf-8"))

    def get_dataset_status():
        """現在のデータセット状況を返す"""
        dataset_path = TRAINING_DIR / "data" / "importance_dataset.jsonl"
        ocr_dir = TRAINING_DIR / "data" / "ocr_texts"

        count = _count_jsonl_records(dataset_path)
        txt_count = len(list(ocr_dir.glob("*.txt"))) if ocr_dir.exists() else 0

        status = f"データセット: {count} レコード\n"
        status += f"OCRテキスト: {txt_count} ファイル\n"
        status += f"保存先: data/importance_dataset.jsonl"
        return status

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
    # Tab 4: 歌詞生成テスト (Track B: lyrics_generation モジュール使用)
    # =====================================================================
    def generate_lyrics_local(text, genre, model_path, keywords_str):
        """ローカルモデルで歌詞生成テスト (lyrics_generation モジュール統合)"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError:
            return "transformersがインストールされていません", ""

        if not text.strip():
            return "テキストを入力してください", ""

        try:
            from lyrics_generation.style_templates import SYSTEM_PROMPT, build_user_prompt
            from lyrics_generation.evaluate import evaluate_lyrics

            # キーワード処理
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()] if keywords_str else []

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                quantization_config=bnb_config,
                device_map="auto",
                torch_dtype=torch.bfloat16,
            )
            model.eval()

            user_prompt = build_user_prompt(text, genre, keywords)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

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

            # 品質評価
            score = evaluate_lyrics(result, keywords)
            eval_text = (
                f"## 品質スコア: {score['total']:.3f}\n\n"
                f"| 項目 | スコア |\n|:---|:---|\n"
                f"| キーワード含有率 | {score['keyword_coverage']:.3f} |\n"
                f"| 構造品質 | {score['structure']:.3f} |\n"
                f"| 韻スコア | {score['rhyme']:.3f} |\n"
                f"| NGワード | {score['ng_words']:.3f} |"
            )

            return result, eval_text

        except Exception as e:
            return f"生成エラー: {e}", ""

    def evaluate_existing_lyrics(lyrics_text, keywords_str):
        """既存の歌詞テキストを品質評価"""
        if not lyrics_text.strip():
            return "歌詞テキストを入力してください"
        try:
            from lyrics_generation.evaluate import evaluate_lyrics
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()] if keywords_str else []
            score = evaluate_lyrics(lyrics_text, keywords)
            result = (
                f"## 品質スコア: {score['total']:.3f}\n\n"
                f"| 項目 | スコア | 説明 |\n|:---|:---|:---|\n"
                f"| キーワード含有率 | {score['keyword_coverage']:.3f} | 重要キーワードが歌詞に含まれているか |\n"
                f"| 構造品質 | {score['structure']:.3f} | [Verse][Chorus]等のセクション構造 |\n"
                f"| 韻スコア | {score['rhyme']:.3f} | 行末の母音パターンの一致 |\n"
                f"| NGワード | {score['ng_words']:.3f} | 禁止表現が含まれていないか |\n"
            )
            if score['total'] >= 0.6:
                result += "\n✅ **良好** — 学習データとして利用可能"
            elif score['total'] >= 0.4:
                result += "\n⚠ **改善の余地あり** — 韻やセクション構造を強化"
            else:
                result += "\n❌ **品質不足** — 大幅な修正が必要"
            return result
        except Exception as e:
            return f"評価エラー: {e}"

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
            # ----- Tab 0: ノート画像アップロード -----
            with gr.TabItem("📸 ノート画像 → データ化"):
                gr.Markdown("### ノート写真をアップロード → OCR → スコアリング → データセット自動追加")
                gr.Markdown("完全ローカル実行 (Qwen2.5-VL)。対応形式: JPG, PNG, WEBP, HEIC, GIF, BMP, TIFF")
                with gr.Row():
                    with gr.Column(scale=2):
                        upload_files = gr.File(
                            label="ノート画像 (複数可)",
                            file_count="multiple",
                            file_types=["image"],
                        )
                        ocr_model = gr.Dropdown(
                            choices=[
                                "Qwen/Qwen2.5-VL-7B-Instruct",
                                "Qwen/Qwen2.5-VL-3B-Instruct",
                            ],
                            value=DEFAULT_MODEL,
                            label="OCRモデル",
                            info="7B=高精度(4080推奨), 3B=軽量(4060Ti OK)",
                        )
                        upload_btn = gr.Button("🚀 一括処理開始", variant="primary", size="lg")
                        dataset_status = gr.Textbox(label="データセット状況", interactive=False, lines=3)
                        refresh_btn = gr.Button("🔄 状況更新")
                    with gr.Column(scale=2):
                        upload_summary = gr.Markdown(label="サマリー")
                        upload_log = gr.Textbox(label="処理ログ", lines=10, interactive=False)
                with gr.Accordion("OCRプレビュー (最後の画像)", open=False):
                    ocr_preview = gr.Textbox(label="抽出テキスト", lines=15, interactive=False)

                upload_btn.click(
                    process_notebook_images,
                    inputs=[upload_files, ocr_model],
                    outputs=[upload_summary, upload_log, ocr_preview],
                )
                refresh_btn.click(get_dataset_status, outputs=[dataset_status])
                app.load(get_dataset_status, outputs=[dataset_status])

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

            # ----- Tab 4: 歌詞生成テスト (Track B) -----
            with gr.TabItem("🎤 歌詞生成テスト"):
                gr.Markdown("### 本能寺の変スタイル！学習内容をキャッチーな歌詞に (Track B)")
                gr.Markdown("エグスプロージョンのように、学習テキストを面白くリズミカルな歌詞に変換します。")
                with gr.Row():
                    with gr.Column():
                        lyrics_text = gr.Textbox(
                            label="学習テキスト",
                            placeholder="1582年、本能寺の変。織田信長は家臣の明智光秀に討たれた...",
                            lines=8,
                        )
                        lyrics_keywords = gr.Textbox(
                            label="重要キーワード (カンマ区切り)",
                            placeholder="1582年, 本能寺の変, 織田信長, 明智光秀",
                            info="空欄の場合は自動抽出扱い",
                        )
                        lyrics_genre = gr.Dropdown(
                            choices=["pop", "rock", "hip-hop", "EDM", "R&B", "演歌"],
                            value="pop",
                            label="ジャンル",
                        )
                        lyrics_model = gr.Textbox(
                            label="モデルパス",
                            value="Qwen/Qwen2.5-7B-Instruct",
                            info="学習済みLoRAパス or ベースモデル名",
                        )
                        lyrics_btn = gr.Button("🎵 歌詞生成", variant="primary")
                    with gr.Column():
                        lyrics_output = gr.Textbox(label="生成された歌詞", lines=15, interactive=False)
                        lyrics_eval = gr.Markdown(label="品質評価")

                with gr.Accordion("既存歌詞の品質評価", open=False):
                    gr.Markdown("生成済みの歌詞テキストを貼り付けて品質スコアを確認")
                    eval_lyrics_input = gr.Textbox(label="歌詞テキスト", lines=10)
                    eval_kw_input = gr.Textbox(label="キーワード (カンマ区切り)")
                    eval_btn = gr.Button("📊 品質評価")
                    eval_result = gr.Markdown()

                lyrics_btn.click(
                    generate_lyrics_local,
                    inputs=[lyrics_text, lyrics_genre, lyrics_model, lyrics_keywords],
                    outputs=[lyrics_output, lyrics_eval],
                )
                eval_btn.click(
                    evaluate_existing_lyrics,
                    inputs=[eval_lyrics_input, eval_kw_input],
                    outputs=[eval_result],
                )

            # ----- Tab 5: ヘルプ -----
            with gr.TabItem("❓ ヘルプ"):
                gr.Markdown("""
### 使い方ガイド

#### 0. ノート画像アップロード (一番簡単)
1. **ノート画像 → データ化**タブを開く
2. OCRモデルを選択 (4080→7B推奨, 4060Ti→3B)
3. ノートの写真をドラッグ&ドロップ (複数可)
4. **一括処理開始** → 自動で OCR → スコアリング → データセット追加
5. `data/ocr_texts/` にテキスト、`data/importance_dataset.jsonl` にスコア付きデータが保存される

> 初回はモデルのダウンロードに数分かかります (自動)

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

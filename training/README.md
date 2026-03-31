# UTAMEMO ローカルLLM 歌詞生成モデル

学校のGPU PC (RTX 4080 × 2) を使って、Gemini APIの代わりに歌詞を生成するローカルLLMをセットアップする手順。

## 📁 ファイル構成

```
training/
├── README.md                    # このファイル
├── requirements_training.txt    # GPU PCにインストールするパッケージ
├── export_training_data.py      # DBから学習データを抽出するスクリプト
├── train.py                     # LoRA学習スクリプト (マルチGPU / 評価 / W&B対応)
├── test_model.py                # 学習済みモデルのテスト
├── serve.py                     # 推論サーバー (Flask API / vLLM対応)
├── start_server.sh              # ワンコマンド起動 (serve.py + Cloudflare Tunnel)
└── data/
    └── sample_training_data.json # サンプル学習データ (3件)
```

## 🚀 セットアップ手順

### 1. 学校のGPU PCにSSH接続

```bash
# Mac から学校PCにSSH
ssh ユーザー名@学校PCのIPアドレス

# VS Code Remote SSHでも可
# VS Code → Ctrl+Shift+P → "Remote-SSH: Connect to Host"
```

### 2. リポジトリをclone

```bash
git clone https://github.com/Yulkjh/utamemo-app.git
cd utamemo-app/training
```

### 3. Python環境セットアップ

```bash
# Python 3.10+ を確認
python3 --version

# 仮想環境を作成
python3 -m venv venv
source venv/bin/activate

# パッケージインストール
pip install -r requirements_training.txt

# CUDA確認 (2枚のGPU両方が見えること)
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPUs: {torch.cuda.device_count()}'); [print(f'  GPU {i}: {torch.cuda.get_device_name(i)}') for i in range(torch.cuda.device_count())]"
```

**オプション: vLLM (高速推論)**

推論サーバーでvLLMエンジンを使う場合（2x〜5x高速化）:

```bash
pip install vllm
```

**オプション: W&B (学習ログ可視化)**

学習ログをWeb上で確認したい場合:

```bash
pip install wandb
wandb login
```

### 4. Hugging Face トークン取得

Llama 3 のダウンロードには Hugging Face のアクセストークンが必要:

1. https://huggingface.co/settings/tokens でトークンを作成
2. https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct でライセンスに同意

```bash
# トークンを環境変数に設定
export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxx"
```

### 5. 学習データを準備

**方法A: 既存のUTAMEMOデータベースから抽出**

```bash
# 本番DBからデータをエクスポート (Render.comのDBに接続する場合)
cd ../myproject
DATABASE_URL="postgresql://..." python manage.py shell < ../training/export_training_data.py
```

**方法B: サンプルデータで動作確認**

```bash
# data/sample_training_data.json (3件) で動作確認
# 本番では最低100件以上推奨
```

**方法C: Geminiで大量生成してフィルタリング**

良い学習データを増やすには:
1. 様々な教科 (理科/社会/英語/数学) のテキストを用意
2. Geminiで歌詞を生成
3. 質の良いものを手動で選別
4. JSONに追加

### 6. LoRA学習実行

```bash
cd /path/to/utamemo-app/training

# サンプルデータで動作確認 (数分)
python train.py \
  --data_path data/sample_training_data.json \
  --epochs 5 \
  --hf_token $HF_TOKEN

# 本番学習 (数時間)
python train.py \
  --data_path data/lyrics_training_data.json \
  --epochs 3 \
  --batch_size 2 \
  --lora_rank 32 \
  --hf_token $HF_TOKEN
```

学習が完了すると `output/utamemo-lyrics-lora/` にLoRAアダプタが保存される。

#### 学習オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--data_path` | `data/sample_training_data.json` | 学習データのパス |
| `--model_name` | `meta-llama/Meta-Llama-3-8B-Instruct` | ベースモデル |
| `--output_dir` | `output/utamemo-lyrics-lora` | LoRA保存先 |
| `--epochs` | `3` | エポック数 |
| `--batch_size` | `1` | バッチサイズ |
| `--lora_rank` | `16` | LoRAランク (8/16/32/64) |
| `--lora_alpha` | `32` | LoRAアルファ |
| `--eval_split` | `0.1` | 検証データの割合 (0で無効) |
| `--early_stopping_patience` | `0` | Early Stopping (0で無効、3推奨) |
| `--wandb_project` | なし | W&Bプロジェクト名 (指定でW&B有効) |
| `--resume_from_checkpoint` | なし | チェックポイントから学習再開 |
| `--hf_token` | なし | Hugging Faceトークン |

#### マルチGPU学習 (RTX 4080 × 2)

```bash
# accelerate で2枚のGPUを使った学習
accelerate launch --num_processes 2 train.py \
  --data_path data/lyrics_training_data.json \
  --epochs 3 \
  --batch_size 2 \
  --lora_rank 32 \
  --eval_split 0.1 \
  --early_stopping_patience 3 \
  --hf_token $HF_TOKEN
```

#### W&B (Weights & Biases) で学習ログを可視化

```bash
python train.py \
  --data_path data/lyrics_training_data.json \
  --wandb_project utamemo-lyrics \
  --hf_token $HF_TOKEN
```

学習後 https://wandb.ai で loss カーブ、eval loss、GPU使用量などを確認可能。

#### 対応モデル

train.py はモデルファミリーを自動検出し、最適なLoRAターゲットモジュールを設定:

| モデル | パラメータ | VRAM (QLoRA) | 備考 |
|--------|----------|-------------|------|
| `meta-llama/Meta-Llama-3-8B-Instruct` | 8B | ~10GB | デフォルト、推奨 |
| `meta-llama/Meta-Llama-3.1-8B-Instruct` | 8B | ~10GB | Llama 3.1 |
| `google/gemma-2-9b-it` | 9B | ~12GB | 日本語良好 |
| `microsoft/Phi-3-mini-4k-instruct` | 3.8B | ~5GB | 軽量、テスト向け |
| `Qwen/Qwen2.5-7B-Instruct` | 7B | ~8GB | 中国語/日本語に強い |
| `Qwen/Qwen2.5-32B-Instruct` | 32B | ~20GB | 高品質、2枚必要 |

### 7. モデルテスト

```bash
python test_model.py --hf_token $HF_TOKEN

# カスタムテスト
python test_model.py \
  --prompt "三角形の面積の公式 底辺×高さ÷2 平行四辺形の面積 底辺×高さ" \
  --genre pop \
  --hf_token $HF_TOKEN
```

### 8. 推論サーバー + Cloudflare Tunnel 起動

Cloudflare Tunnel を使って、学校LAN内のGPU PCをインターネットに安全に公開する。
ファイアウォール/ポート開放不要、HTTPS自動。

#### 推論エンジンの選択

serve.py は2つの推論エンジンに対応:

| エンジン | 特徴 | いつ使う |
|---------|------|---------|
| `transformers` (デフォルト) | 標準的、追加インストール不要 | テスト・少量リクエスト |
| `vllm` | 2x〜5x高速、マルチGPU対応 | 本番運用・高速化したい時 |

#### 初回セットアップ（1回だけ）

```bash
cd /path/to/utamemo-app/training

# セットアップウィザード（cloudflaredインストール + Cloudflareログイン + APIキー生成）
./start_server.sh --setup
```

セットアップで表示される **APIキー** を控えておく（Render.comに設定する）。

#### 通常起動

```bash
cd /path/to/utamemo-app/training

# serve.py + Cloudflare Tunnel をまとめて起動
./start_server.sh
```

起動後にログに表示される **Cloudflare URL**（`https://xxxx.cfargotunnel.com`）を控える。

#### 手動で起動する場合

```bash
# 1. APIキーを設定
export UTAMEMO_API_KEY="ランダムな文字列を設定"

# 2. 推論サーバー起動 (transformers エンジン)
python serve.py \
  --host 127.0.0.1 \
  --port 8000 \
  --hf_token $HF_TOKEN &

# 2b. または vLLM エンジンで高速起動 (2枚のGPUで並列推論)
python serve.py \
  --host 127.0.0.1 \
  --port 8000 \
  --engine vllm \
  --hf_token $HF_TOKEN &

# 3. Cloudflare Tunnel 起動
cloudflared tunnel --url http://127.0.0.1:8000 run utamemo-llm
```

ヘルスチェック（ローカル）:
```bash
curl http://127.0.0.1:8000/health
```

ヘルスチェック（Cloudflare経由）:
```bash
curl https://あなたのトンネルURL/health
```

歌詞生成テスト:
```bash
curl -X POST https://あなたのトンネルURL/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $UTAMEMO_API_KEY" \
  -d '{"text": "光合成とは植物が光エネルギーを使って水と二酸化炭素から酸素とデンプンを作る反応", "genre": "pop"}'
```

### 9. UTAMEMOアプリと接続

Render.comの環境変数に以下を追加:

```
LOCAL_LLM_URL=https://あなたのトンネルURL
LOCAL_LLM_API_KEY=start_server.shのsetupで生成されたAPIキー
LYRICS_BACKEND=auto
```

`LYRICS_BACKEND` の設定:
- `gemini` (デフォルト): Geminiのみ使用
- `local`: ローカルLLMのみ使用
- `auto`: ローカルLLM優先、ダウン時はGeminiにフォールバック

## ⚠️ 注意事項

### ネットワーク（Cloudflare Tunnel）
- Cloudflare Tunnel を使うのでポート開放やファイアウォール設定は不要
- HTTPS は Cloudflare が自動で提供
- トンネルが切れた場合は `./start_server.sh` で再起動
- Cloudflareの無料プランで十分（商用利用OK）

### セキュリティ
- `UTAMEMO_API_KEY` は必ず設定する（推論サーバーへの不正アクセス防止）
- serve.py は `127.0.0.1` にバインド（Cloudflare Tunnel経由のみアクセス可）
- APIキーなしのリクエストは401/403で拒否される

### GPU利用許可
- 学校のGPUを商用プロジェクトに使う許可を先生に確認すること
- 学習済みモデルの持ち出し可否も確認

## 📊 リソース目安 (RTX 4080 × 2, 16GB VRAM × 2)

| 作業 | GPU | VRAM | 時間 |
|------|-----|------|------|
| LoRA学習 8Bモデル (100件) | 4080 x1 | ~10GB | 1〜2時間 |
| LoRA学習 8Bモデル (1000件) | 4080 x1 | ~10GB | 4〜8時間 |
| LoRA学習 32Bモデル (100件) | 4080 x2 | ~20GB | 3〜5時間 |
| 推論サーバー (transformers) | 4080 x1 | ~10GB | 常時 |
| 推論サーバー (vLLM, 8B) | 4080 x1 | ~10GB | 常時、2x〜5x高速 |
| 推論サーバー (vLLM, 32B) | 4080 x2 | ~20GB | 常時、高品質 |

## 🔄 Geminiからの移行チェックリスト

- [ ] 学校GPU PCにSSH接続できる
- [ ] CUDA / PyTorch が動作する
- [ ] Hugging Face トークン取得済み
- [ ] 学習データ 100件以上準備
- [ ] LoRA学習完了
- [ ] テストで品質確認
- [ ] `./start_server.sh --setup` 完了
- [ ] `./start_server.sh` でサーバー + トンネル起動
- [ ] Cloudflare URL でヘルスチェック通る
- [ ] Render.com に `LOCAL_LLM_URL` / `LOCAL_LLM_API_KEY` 設定
- [ ] `LYRICS_BACKEND=auto` に変更
- [ ] UTAMEMOから接続テスト（歌詞生成して確認）
- [ ] Geminiと品質比較 → 同等以上なら `LYRICS_BACKEND=local` に変更

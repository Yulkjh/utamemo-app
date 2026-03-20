# UTAMEMO ローカルLLM 歌詞生成モデル

学校のGPU PC (RTX 4090) を使って、Gemini APIの代わりに歌詞を生成するローカルLLMをセットアップする手順。

## 📁 ファイル構成

```
training/
├── README.md                    # このファイル
├── requirements_training.txt    # GPU PCにインストールするパッケージ
├── export_training_data.py      # DBから学習データを抽出するスクリプト
├── train.py                     # LoRA学習スクリプト
├── test_model.py                # 学習済みモデルのテスト
├── serve.py                     # 推論サーバー (Flask API)
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

# CUDA確認
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')"
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

### 7. モデルテスト

```bash
python test_model.py --hf_token $HF_TOKEN

# カスタムテスト
python test_model.py \
  --prompt "三角形の面積の公式 底辺×高さ÷2 平行四辺形の面積 底辺×高さ" \
  --genre pop \
  --hf_token $HF_TOKEN
```

### 8. 推論サーバー起動

```bash
# APIキーを設定
export UTAMEMO_API_KEY="ランダムな文字列を設定"

# サーバー起動
python serve.py \
  --host 0.0.0.0 \
  --port 8000 \
  --hf_token $HF_TOKEN
```

ヘルスチェック:
```bash
curl http://localhost:8000/health
```

歌詞生成テスト:
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $UTAMEMO_API_KEY" \
  -d '{"text": "光合成とは植物が光エネルギーを使って水と二酸化炭素から酸素とデンプンを作る反応", "genre": "pop"}'
```

### 9. UTAMEMOアプリと接続

Render.comの環境変数に以下を追加:

```
LOCAL_LLM_URL=http://学校PCのIPアドレス:8000
LOCAL_LLM_API_KEY=上で設定したAPIキー
LYRICS_BACKEND=auto
```

`LYRICS_BACKEND` の設定:
- `gemini` (デフォルト): Geminiのみ使用
- `local`: ローカルLLMのみ使用
- `auto`: ローカルLLM優先、ダウン時はGeminiにフォールバック

## ⚠️ 注意事項

### ネットワーク
- 学校のGPU PCがRender.comからアクセスできる必要がある
- 学校のファイアウォールでポート8000を開放する必要があるかも
- ngrok や Cloudflare Tunnel を使う方法もある

### セキュリティ
- `UTAMEMO_API_KEY` は必ず設定する (推論サーバーへの不正アクセス防止)
- 本番では HTTPS を使う (ngrok / Cloudflare Tunnel)

### GPU利用許可
- 学校のGPUを商用プロジェクトに使う許可を先生に確認すること
- 学習済みモデルの持ち出し可否も確認

## 📊 リソース目安

| 作業 | GPU | VRAM | 時間 |
|------|-----|------|------|
| LoRA学習 (100件) | 4090 x1 | ~16GB | 1〜2時間 |
| LoRA学習 (1000件) | 4090 x1 | ~16GB | 4〜8時間 |
| 推論サーバー | 4090 x1 | ~10GB | 常時 |

## 🔄 Geminiからの移行チェックリスト

- [ ] 学校GPU PCにSSH接続できる
- [ ] CUDA / PyTorch が動作する
- [ ] Hugging Face トークン取得済み
- [ ] 学習データ 100件以上準備
- [ ] LoRA学習完了
- [ ] テストで品質確認
- [ ] 推論サーバー起動 & ヘルスチェック通る
- [ ] UTAMEMOから接続テスト
- [ ] `LYRICS_BACKEND=auto` に変更
- [ ] Geminiと品質比較 → 同等以上なら `LYRICS_BACKEND=local` に変更

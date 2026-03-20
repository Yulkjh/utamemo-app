# UTAMEMO - 学習支援AIアプリケーション

## アプリ名
UTAMEMO（ウタメモ）  
ノートや教科書の内容を「歌」で覚える学習支援 Web アプリケーション

**https://utamemo.com**

## 概要
教科書やノートの画像をアップロードすると、AI が内容を読み取り、覚えやすい歌詞を自動生成します。  
さらに、AI がその歌詞から楽曲を生成することで、音楽を聞きながら楽しく暗記・復習ができるアプリです。

## 主な機能

### 楽曲生成
- 画像からのテキスト抽出（OCR）
- 学習内容を歌詞に変換（暗記に最適化した歌詞生成）
- 漢字・数字の自動ひらがな変換
- AI による楽曲生成（ジャンル・ボーカルスタイル選択可能）
- 12種のボーカルスタイル（女性4種 / 男性4種 / 特殊スタイル4種 + ボカロ風2種）
- 毎回異なる声質のランダム生成（864通りの声の組み合わせ）
- 手動での歌詞入力モード
- 音楽スタイルプロンプトによるカスタマイズ（辞書ベース高速翻訳）

### 暗記カード（フラッシュカード）
- 楽曲の元テキストから AI が自動で用語を抽出
- 重要度付き用語選択（赤字・太字・マーカーで強調された語句を自動判別）
- フィルタリング機能（重要/通常/全て）で効率的に選別
- 楽曲詳細ページから直接作成（楽曲と連動）

### カラオケモード
- 手動スクロール型の歌詞表示（楽曲再生中に歌詞を見ながら練習）

### ユーザー管理
- ユーザー登録・ログイン機能
- プロフィール画像設定（Base64 で DB 保存、サーバー再起動後も維持）
- 自己紹介（bio）
- ユーザー名のコンテンツフィルタリング（不適切な名前・メールアドレス形式をブロック）

### 楽曲管理
- マイページでの楽曲一覧・管理
- 楽曲の公開 / 非公開設定
- 楽曲詳細ページでの削除機能（PC / スマートフォン両対応）
- タグ機能
- コメント機能

### クラスルーム
- クラスルーム作成・参加（招待コード）
- クラスルームへの楽曲共有
- クラスメンバー管理

### ソーシャル機能
- 総再生回数の表示（全ユーザーの再生数をカウント）
- いいね・お気に入り機能（ソングリストからも操作可能）
- クリエイターアバター表示（ソングリストでプロフィールへリンク）

### セキュリティ・プライバシー
- ユーザーデータの暗号化（Fernet 対称鍵暗号）
- 非公開楽曲はサーバー管理者も閲覧不可
- アップロード画像の自動削除（楽曲生成完了後にサーバー容量を節約）
- 不適切コンテンツフィルター（歌詞・ユーザー名）

### 多言語・レスポンシブ
- 多言語対応（日本語 / English / Español / Deutsch / Português / 中文）
- レスポンシブデザイン（PC / スマートフォン対応）
- SEO 対応（サイトマップ生成）

### 法務・コンプライアンス
- 利用規約 / プライバシーポリシー / 特定商取引法に基づく表記
- 各国法規対応（EU GDPR、ドイツ Impressum 等）

---

## 技術スタック

### バックエンド
- Python 3.11（本番） / 3.14（開発）
- Django 5.2.7
- PostgreSQL（本番） / SQLite（開発）
- Gunicorn + WhiteNoise

### AI サービス（歌詞生成 — 3 バックエンド切替対応）

| バックエンド | 説明 | 用途 |
|-------------|------|------|
| **Google Gemini API** (gemini-2.5-flash) | OCR + 歌詞生成 + ひらがな変換 | デフォルト（本番） |
| **クラウド LLM** | OpenAI 互換 API (Together AI / Groq / Fireworks / OpenRouter) | Gemini 代替・高速推論 |
| **ローカル LLM** | 自前 GPU サーバー + QLoRA ファインチューニング | Gemini 完全代替（将来） |

- **Mureka AI API**（楽曲生成 / V8・O2・V7.6・V7.5 モデル対応）

### AI サービス構成図

```
ユーザー
  │
  ▼
┌──────────────────────────────────┐
│  UTAMEMO (Render.com)            │
│  Django 5.x                      │
│                                  │
│  LYRICS_BACKEND 設定:            │
│  ┌────────────────────────────┐  │
│  │ "gemini" → Gemini API     │  │
│  │ "cloud"  → Cloud LLM     │  │
│  │ "local"  → Local LLM     │  │
│  │ "auto"   → Cloud → Local │  │
│  │            → Gemini       │  │
│  │           (フォールバック) │  │
│  └────────────────────────────┘  │
└──────┬──────────┬──────────┬─────┘
       │          │          │
       ▼          ▼          ▼
  ┌─────────┐ ┌────────┐ ┌──────────────────────┐
  │ Gemini  │ │Together│ │ GPU PC (RTX 4090)    │
  │ API     │ │AI/Groq │ │ serve.py + LoRA      │
  │         │ │etc.    │ │ Cloudflare Tunnel    │
  └─────────┘ └────────┘ └──────────────────────┘
```

### 対応 LLM モデル（ローカル / クラウド共通）

| モデル | VRAM | 備考 |
|--------|------|------|
| Llama 3 8B Instruct | ~16GB | 推奨 |
| Llama 3 70B Instruct | ~40GB | 高品質 |
| Gemma 2 2B/9B/27B | 6~20GB | Google 製、軽量〜高品質 |
| Phi 3.5 Mini 3.8B | ~8GB | Microsoft 製、軽量 |
| Qwen 2.5 7B/14B | 12~16GB | Alibaba 製 |

### 主要パッケージ
- google-generativeai（Gemini AI）
- cryptography（暗号化）
- Pillow（画像処理）
- requests（HTTP 通信）
- fugashi + unidic-lite（日本語形態素解析）
- PyMuPDF（PDF 処理）
- channels / daphne（WebSocket）

### デプロイ
- Render（Python 3.11.0 / PostgreSQL）
- HTTPS 通信
- カスタムドメイン（utamemo.com）

---

## プロジェクト構成
```
UTAMEMO/
├── myproject/
│   ├── myproject/              # Django 設定
│   │   ├── settings.py         # 各種設定 (LLM バックエンド設定含む)
│   │   ├── urls.py             # URL ルーティング
│   │   ├── sitemaps.py         # SEO サイトマップ
│   │   ├── security.py         # セキュリティ設定
│   │   ├── context_processors.py
│   │   └── wsgi.py / asgi.py
│   ├── songs/                  # 楽曲管理アプリ
│   │   ├── models.py           # データモデル (Song, Lyrics, Tag, Classroom, FlashcardDeck 等)
│   │   ├── views.py            # ビュー
│   │   ├── ai_services.py      # AI 統合 (Gemini / Cloud LLM / Local LLM / Mureka)
│   │   ├── content_filter.py   # コンテンツフィルタリング
│   │   ├── encryption.py       # 暗号化機能
│   │   └── urls.py
│   ├── users/                  # ユーザー管理アプリ
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── forms.py            # バリデーション
│   │   └── urls.py
│   ├── templates/              # HTML テンプレート
│   ├── static/                 # 静的ファイル
│   ├── media/                  # アップロード画像（一時）
│   └── manage.py
├── training/                   # ローカル LLM 学習 & 推論
│   ├── train.py                # QLoRA 学習スクリプト
│   ├── serve.py                # Flask 推論サーバー
│   ├── test_model.py           # 学習済みモデルのテスト
│   ├── export_training_data.py # DB → 学習データ JSON 変換
│   ├── start_server.sh         # ワンコマンド起動 (serve.py + Cloudflare Tunnel)
│   ├── requirements_training.txt
│   └── data/
│       └── sample_training_data.json
├── requirements.txt            # 依存パッケージ (Web アプリ)
├── Procfile                    # Render デプロイ設定
├── build.sh                    # ビルドスクリプト
└── README.md
```

---

## 歌詞生成 LLM のセットアップ

UTAMEMO は歌詞生成バックエンドとして **3 種類の LLM** を切り替えて利用できます。  
環境変数 `LYRICS_BACKEND` で制御します。

### バックエンド切替（環境変数）

| `LYRICS_BACKEND` | 動作 |
|-------------------|------|
| `gemini`（デフォルト） | Gemini API のみ使用 |
| `cloud` | クラウド LLM のみ使用 |
| `local` | ローカル LLM のみ使用 |
| `auto` | Cloud → Local → Gemini の順にフォールバック |

---

### 方法 1: Gemini API（デフォルト）

追加設定不要。`.env` に `GEMINI_API_KEY` を設定するだけで動作します。

```bash
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxx
LYRICS_BACKEND=gemini
```

---

### 方法 2: クラウド LLM（Together AI / Groq / Fireworks / OpenRouter）

OpenAI 互換 API を提供するクラウドサービスを利用します。Gemini の代替・高速推論に最適。

#### 対応プロバイダー

| プロバイダー | デフォルトモデル | 特徴 |
|-------------|-----------------|------|
| **Together AI** | `meta-llama/Llama-3-8b-chat-hf` | 豊富なモデル選択肢 |
| **Groq** | `llama3-8b-8192` | 超高速推論 |
| **Fireworks AI** | `accounts/fireworks/models/llama-v3-8b-instruct` | 安定・高速 |
| **OpenRouter** | `meta-llama/llama-3-8b-instruct` | 多プロバイダー統合 |

#### 環境変数の設定

```bash
# Render.com → Environment Variables に追加
LYRICS_BACKEND=cloud           # または auto (フォールバック有効)

# --- Together AI の場合 ---
CLOUD_LLM_PROVIDER=together
CLOUD_LLM_API_KEY=xxxxxxxxxxxxx

# --- Groq の場合 ---
CLOUD_LLM_PROVIDER=groq
CLOUD_LLM_API_KEY=gsk_xxxxxxxxxxxxx

# --- オプション ---
CLOUD_LLM_MODEL=              # 空ならプロバイダー別デフォルト
CLOUD_LLM_URL=                # 空ならプロバイダー別デフォルト
CLOUD_LLM_TIMEOUT=90          # タイムアウト秒数
```

---

### 方法 3: ローカル LLM（GPU サーバー + QLoRA ファインチューニング）

自前の GPU サーバーで推論サーバーを起動し、Cloudflare Tunnel 経由で Render.com と接続します。  
詳細な手順は [`training/README.md`](training/README.md) を参照してください。

#### 必要なハードウェア

| 作業 | GPU | VRAM | 時間 |
|------|-----|------|------|
| QLoRA 学習 (100 件) | RTX 4090 ×1 | ~16GB | 1〜2 時間 |
| QLoRA 学習 (1000 件) | RTX 4090 ×1 | ~16GB | 4〜8 時間 |
| 推論サーバー | RTX 4060 Ti 以上 | ~10GB | 常時稼働 |

#### クイックスタート（GPU PC 側）

```bash
# 1. リポジトリをクローン
git clone https://github.com/Yulkjh/utamemo-app.git
cd utamemo-app/training

# 2. Python 環境セットアップ
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_training.txt

# 3. Hugging Face トークンを設定（Llama 3 のダウンロードに必要）
export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxx"
```

#### 学習データの準備

```bash
# 方法 A: 既存の UTAMEMO DB から抽出
cd ../myproject
DATABASE_URL="postgresql://..." python manage.py shell < ../training/export_training_data.py

# 方法 B: サンプルデータで動作確認
# training/data/sample_training_data.json (3 件) をそのまま使用
```

#### QLoRA 学習の実行

```bash
cd /path/to/utamemo-app/training

# サンプルデータで動作確認（数分）
python train.py --data_path data/sample_training_data.json --epochs 5 --hf_token $HF_TOKEN

# 本番学習（数時間）
python train.py \
  --data_path data/lyrics_training_data.json \
  --epochs 3 \
  --batch_size 2 \
  --lora_rank 32 \
  --hf_token $HF_TOKEN

# 対応モデル一覧を表示
python train.py --list_models --data_path dummy

# Gemma 2 で学習する場合
python train.py \
  --model_name google/gemma-2-9b-it \
  --data_path data/lyrics_training_data.json \
  --hf_token $HF_TOKEN
```

学習完了後、`output/utamemo-lyrics-lora/` に LoRA アダプタが保存されます。

#### 学習済みモデルのテスト

```bash
# デフォルト（Llama 3 + LoRA）
python test_model.py --hf_token $HF_TOKEN

# カスタムプロンプト
python test_model.py \
  --prompt "三角形の面積の公式 底辺×高さ÷2" \
  --genre pop \
  --hf_token $HF_TOKEN

# LoRA なしでベースモデルのみテスト
python test_model.py --base_model google/gemma-2-9b-it --no_lora
```

#### 推論サーバーの起動

**ワンコマンド起動（推奨）: serve.py + Cloudflare Tunnel をまとめて起動**

```bash
cd /path/to/utamemo-app/training

# 初回セットアップ（1 回だけ: cloudflared インストール + ログイン + API キー生成）
./start_server.sh --setup

# 通常起動
./start_server.sh

# Gemma 2 で LoRA なし起動
BASE_MODEL=google/gemma-2-9b-it NO_LORA=1 ./start_server.sh
```

起動後、ログに表示される **Cloudflare URL**（`https://xxxx.cfargotunnel.com`）を控えます。

**手動で起動する場合:**

```bash
# 1. API キー設定
export UTAMEMO_API_KEY="ランダムな文字列"

# 2. 推論サーバー起動
python serve.py --host 127.0.0.1 --port 8000 --hf_token $HF_TOKEN &

# 3. Cloudflare Tunnel 起動
cloudflared tunnel --url http://127.0.0.1:8000 run utamemo-llm

# LoRA なし・Gemma 2 で起動
python serve.py --base_model google/gemma-2-9b-it --no_lora --port 8000 &
```

#### 動作確認

```bash
# ヘルスチェック
curl http://127.0.0.1:8000/health

# 歌詞生成テスト
curl -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $UTAMEMO_API_KEY" \
  -d '{"text": "光合成とは植物が光エネルギーを使って水と二酸化炭素から酸素とデンプンを作る反応", "genre": "pop"}'
```

#### UTAMEMO アプリとの接続（Render.com 環境変数）

```bash
# Render.com → Environment Variables に追加
LOCAL_LLM_URL=https://あなたのCloudflare-URL
LOCAL_LLM_API_KEY=start_server.sh --setup で生成された API キー
LOCAL_LLM_TIMEOUT=60
LYRICS_BACKEND=auto    # auto: Cloud → Local → Gemini のフォールバック
```

---

### API ステータスダッシュボード

管理画面（`/api-status/`）で各 LLM バックエンドの接続状態を確認できます:
- 現在のバックエンド設定（`LYRICS_BACKEND`）
- Gemini API の接続状態
- クラウド LLM のプロバイダー・モデル・API キーステータス
- ローカル LLM の URL・接続状態

---

## セキュリティ機能
- ユーザーデータの暗号化（Fernet 対称鍵暗号 / AES-128-CBC + HMAC-SHA256）
- 非公開楽曲のタイトル・歌詞・原文を暗号化保存
- 公開時のみ復号化して平文保存
- プロフィール画像は Base64 エンコードで DB に直接保存
- アップロード画像は楽曲生成完了後に自動削除（個人情報保護）
- 環境変数での秘密情報管理（`.env`）
- HTTPS 通信（本番環境）
- ローカル LLM: API キー認証 + Cloudflare Tunnel 経由のみアクセス可

---

## 環境変数一覧

### Web アプリ（Render.com）

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `SECRET_KEY` | ✅ | Django シークレットキー |
| `DATABASE_URL` | ✅ | PostgreSQL 接続 URL |
| `GEMINI_API_KEY` | ✅ | Google Gemini API キー |
| `MUREKA_API_KEY` | ✅ | Mureka 楽曲生成 API キー |
| `STRIPE_SECRET_KEY` | ✅ | Stripe 決済キー |
| `STRIPE_WEBHOOK_SECRET` | ✅ | Stripe Webhook 署名シークレット |
| `ENCRYPTION_KEY` | ✅ | データ暗号化キー（Fernet） |
| `LYRICS_BACKEND` | ❌ | 歌詞バックエンド (`gemini` / `cloud` / `local` / `auto`) |
| `CLOUD_LLM_PROVIDER` | ❌ | クラウド LLM プロバイダー (`together` / `groq` / `fireworks` / `openrouter`) |
| `CLOUD_LLM_API_KEY` | ❌ | クラウド LLM API キー |
| `CLOUD_LLM_MODEL` | ❌ | クラウド LLM モデル名（空ならデフォルト） |
| `CLOUD_LLM_URL` | ❌ | クラウド LLM エンドポイント URL（空ならデフォルト） |
| `CLOUD_LLM_TIMEOUT` | ❌ | クラウド LLM タイムアウト秒（デフォルト: 90） |
| `LOCAL_LLM_URL` | ❌ | ローカル LLM サーバー URL |
| `LOCAL_LLM_API_KEY` | ❌ | ローカル LLM API キー |
| `LOCAL_LLM_TIMEOUT` | ❌ | ローカル LLM タイムアウト秒（デフォルト: 60） |

### GPU サーバー（training/）

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `UTAMEMO_API_KEY` | ✅ | 推論サーバー認証キー |
| `HF_TOKEN` | ✅ | Hugging Face アクセストークン |
| `PORT` | ❌ | サーバーポート（デフォルト: 8000） |
| `BASE_MODEL` | ❌ | ベースモデル（デフォルト: Llama 3 8B） |
| `NO_LORA` | ❌ | `1` で LoRA なし起動 |
| `TUNNEL_NAME` | ❌ | Cloudflare Tunnel 名（デフォルト: utamemo-llm） |

---

## 動作確認環境

### 必須要件
- Python 3.11.x
- Django 5.x
- macOS / Windows 10 / 11

### 推奨ブラウザ
- Google Chrome（最新版）
- Microsoft Edge（最新版）
- Firefox（最新版）

---

## デプロイメント関連ドキュメント

- **[ドメイン設定と DNS レコードの確認（日本語）](DOMAIN_SETUP.md)**
- **[Domain Setup and DNS Records (English)](DOMAIN_SETUP_EN.md)**
- **[ローカル LLM 学習 & 推論サーバー](training/README.md)**

---

## 使い方

1. アカウント登録（https://utamemo.com）
2. 教材の写真をアップロード（または手動で歌詞入力）
3. AI が歌詞を生成 → ジャンル・ボーカルスタイルを選択
4. 楽曲が自動生成されます
5. マイページで楽曲を聴いたり管理できます
6. 楽曲詳細ページから暗記カードを作成（AI が重要用語を自動抽出）
7. カラオケモードで歌詞を見ながら練習

---

## プライバシー・倫理・安全性への配慮

### ① 個人情報やプライバシーへの配慮

- **最小限のデータ収集**: ユーザー名、メールアドレス、パスワードのみを必須情報として収集
- **非公開楽曲の暗号化**: Fernet 対称鍵暗号を使用し、非公開設定の楽曲データを暗号化保存
- **サーバー管理者も閲覧不可**: 暗号化されたデータは復号鍵なしでは読み取り不可能
- **アップロード画像の自動削除**: 教科書・ノート画像は楽曲生成完了後に自動的にサーバーから削除
- **プロフィール画像の DB 保存**: 外部ファイル参照ではなく Base64 で DB に直接保存し、ファイルアクセスリスクを排除
- **ユーザー主導の削除**: ユーザーは自分の楽曲・アカウントをいつでも削除可能
- **公開 / 非公開の選択権**: 楽曲ごとに設定でき、プライバシーをユーザー自身がコントロール

### ② 著作権・ライセンスの扱い

- **オリジナルコンテンツの生成**: AI が生成する歌詞・楽曲は、既存の楽曲をコピーするのではなく、ユーザーの学習内容に基づいてオリジナルで生成
- **学習目的の利用**: 教科書・ノートの内容を「暗記用の歌」に変換する教育目的での利用を想定
- **API 利用規約の遵守**: Google Gemini API、Mureka AI API の利用規約に従って使用
- **Mureka 有料プランでの商用利用**: Mureka API は有料プランで利用し、Output の所有権はユーザーに帰属（Mureka ToS Section 3(e)）
- **ライセンスバック条項の告知**: 生成楽曲に対し Mureka へのライセンスバック（取消不能・ロイヤリティフリー）が発生する旨をユーザーに明示
- **AIGC 著作権の限界**: AI 生成コンテンツの著作権登録可能性は法的に不確実であることを認識
- **ユーザーへの責任明示**: アップロードするコンテンツの著作権についてはユーザー自身の責任であることを前提

### ③ データの扱い

- **暗号化技術**: Fernet 対称鍵暗号（AES-128-CBC + HMAC-SHA256）
- **安全な通信**: HTTPS 通信による暗号化（Render 本番環境）
- **環境変数での秘密情報管理**: API キー、SECRET_KEY は `.env` ファイルで管理
- **データベースセキュリティ**: PostgreSQL（本番環境）でのセキュアなデータ保存
- **一時ファイルの適切な処理**: アップロード画像は処理完了後に自動削除
- **セッション管理**: Django 標準のセッション管理機能を使用

### ④ AI・センサー等を使う場合の倫理配慮

- **透明性**: AI による歌詞生成・楽曲生成であることをユーザーに明示。使用 AI サービス（Gemini / Cloud LLM / Local LLM / Mureka）を明記
- **ユーザーの編集権**: AI 生成後もユーザーが歌詞を自由に編集可能
- **目的の明確化**: 教育・学習支援という明確な目的での AI 利用
- **過度なデータ収集の回避**: AI 処理に必要な最小限のデータのみを送信
- **バイアスへの配慮**: 学習コンテンツをそのまま歌詞化するため、AI 独自の偏見が入りにくい設計
- **人間の判断の尊重**: 最終的な公開・利用判断はユーザーが行う

### ⑤ 利用者や社会にとって安心できる工夫

- **教育目的の明確化**: 「勉強を楽しくする」という前向きな目的を明示
- **多言語対応**: 6 言語に対応し、多様なユーザーが利用可能
- **直感的な UI**: 複雑な操作なしで利用でき、デジタルリテラシーに関わらず使用可能
- **レスポンシブデザイン**: PC・スマートフォン両方で快適に利用可能
- **エラーハンドリング**: 処理中のエラーを適切に通知
- **再試行機能**: 楽曲生成に失敗した場合の自動再試行（最大 3 回）
- **コンテンツフィルタリング**: 不適切な歌詞・ユーザー名を自動検出・ブロック
- **コミュニティ機能の適切な制限**: 公開楽曲のみ他ユーザーが閲覧可能

---

## 開発者
Yu

## バージョン
2.1.0（2026 年 3 月 20 日）

## 更新履歴
- **v2.1.0** (2026/3/20)
  - ローカル LLM 学習・推論パイプライン追加（QLoRA / Llama 3 / Gemma 2 / Phi / Qwen 対応）
  - クラウド LLM バックエンド追加（Together AI / Groq / Fireworks AI / OpenRouter）
  - 歌詞生成バックエンド切替機能（`LYRICS_BACKEND`: gemini / cloud / local / auto）
  - auto モード: Cloud → Local → Gemini のフォールバック
  - Cloudflare Tunnel ワンコマンド起動スクリプト（`start_server.sh`）
  - API ステータスダッシュボードに LLM バックエンド状態表示追加
  - Mureka ToS 著作権条項に基づくユーザー告知対応
- **v2.0.0** (2026/2/25)
  - ユーザー名にメールアドレス形式が使われた場合のバリデーション追加
  - カラオケモードを手動スクロール型にリファクタリング（LLM タイミング推定を廃止）
  - 楽曲詳細ページに削除ボタン追加（PC 対応）
  - アップロードページのローディング UX 改善
  - ボカロ風ボーカルスタイル追加（女性 / 男性）
  - 管理画面の強化（全モデル登録、フィルタ・検索）
  - ユーザー名コンテンツフィルター追加
  - 各国法規対応（ES / DE / PT / ZH）
  - 法務ページ拡充（特定商取引法、利用規約 AI 著作権条項）
- **v1.2.0** (2026/1/14)
  - プロフィール画像の Base64 保存（Render 再起動後も維持）
  - 総再生回数表示
  - アップロード画像の自動削除
  - クリエイターアバター表示（ソングリスト）
  - ソングリストからのいいね・お気に入り機能
  - モバイル UI/UX の改善
- **v1.1.0** (2026/1/14)
  - 多言語対応（日本語 / English / 中文）
  - プロフィール画像機能
  - 楽曲削除機能
  - リファレンス楽曲機能
  - UI/UX 全体的な改善

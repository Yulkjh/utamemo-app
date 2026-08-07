# UTAMEMO — AIが「歌」に変換する教育系音楽プラットフォーム

> **教科書やノートをAIで歌にして、歌って覚える。**

[![Django](https://img.shields.io/badge/Django-5.2-green)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![Deploy](https://img.shields.io/badge/deploy-Render.com-orange)](https://render.com/)

---

## 概要

UTAMEMO（ウタメモ）は、教科書や勉強ノートを「歌」に変換して覚える学習支援アプリです。ユーザーが教材を撮影（またはPDFをアップロード）すると、OCR/AIパイプラインがテキストを抽出し、LLMが歌詞に変換し、AI音楽生成モデルがボーカル入りの楽曲としてレンダリングします。生成した楽曲はフラッシュカードデッキに変換して間隔反復学習に使えるほか、教師がクラスに共有したり、自動生成したカラオケ（インスト）音源で歌いながら再生したりできます。

このリポジトリは、以下を含む単一のDjangoモノレポです。

- **`myproject/`** — 本番稼働中のDjango Webアプリケーション（プロダクト本体）
- **`training/`** — チーム所有のGPUで自前運用する、歌詞生成専用のLoRA/QLoRAファインチューニング＋推論パイプライン（クラウドLLMのコスト削減用オプション）
- **`docs/`** — 日本語のアーキテクチャ・ソフトウェア設計ドキュメント
- **`UtaMemo/`** — 独立したSwiftUI製iOSアプリの初期プロトタイプ（独自のXcodeプロジェクト・独自のgitリポジトリを持ち、Djangoバックエンドとは未連携）

### 主な機能

| 機能 | 説明 |
|------|------|
| 写真/PDF → 楽曲 | 教科書の写真やPDFをアップロード。Gemini OCR（画像）またはPyMuPDF（PDF）がテキストを抽出 |
| マルチバックエンド歌詞AI | 歌詞生成のバックエンドを差し替え可能：Google Gemini（デフォルト）、自前ホストのローカルLLM、OpenAI互換の任意のクラウドLLM（Together AI / Fireworks / Groq / OpenRouter / vLLM）、Ollama。`LYRICS_BACKEND` 環境変数でデプロイごとに選択可能。`auto` モードは クラウドLLM → Ollama → ローカルLLM → Gemini の順にフェイルオーバー |
| 楽曲生成 | Google の **Lyria**（`lyria-3-pro-preview`、Google GenAI SDK経由）が歌詞をボーカル入りの楽曲としてレンダリング。ジャンル・ボーカルスタイル（女性/男性/ボーカロイド風/デュエット/合唱/ウィスパー/子供など、多数のプリセット）をプロンプトに反映 |
| カラオケトラック | Demucsによる音源分離で、インスト（ボーカル抜き）音源を自動生成し、一緒に歌える機能を提供 |
| フラッシュカード機能 | 楽曲の歌詞や元画像からGeminiが用語・定義ペアを自動抽出。重要度タグ付けと4段階の習熟度トラッキングで間隔反復学習をサポート |
| クラス機能 | 教師が参加コード付きのクラスを作成し、楽曲を共有したり、締切付きの課題として割り当てたりできる |
| サブスクリプションプラン | Free / Starter（¥780/月）/ Pro（¥1,900/月）/ School（生徒1人あたり¥450/月）をStripe Checkout + Webhookで運用。プランごとに月間生成数の上限あり |
| コンテンツモデレーション | 日本語・英語・中国語の3言語対応ルールベースフィルタ。歴史用語や詩的表現など正当な語彙の誤検知を避けるための学術/歌詞文脈アローリスト付き |
| 信頼・安全対策 | 管理画面のメールベース2段階認証、IP制限付き管理アクセス、強制ログアウト付きBANシステム、未成年の決済に対する年齢確認＋保護者同意ゲート |
| 自前ホストLLM学習基盤 | チーム所有GPU上で動くLoRA/QLoRAファインチューニングパイプライン（学習/配信/監視）。クラウドバックエンドと同じ歌詞生成インターフェースに接続可能（歌詞生成専用、音楽生成は非対応） |
| データ提携先コンプライアンス | 外部企業とのデータ提供契約（MOU）を管理する仕組み。提供元の記録、アクセス権限の管理、監査ログ、削除リクエスト対応などをDBモデルで管理 |
| 7言語対応 | 日本語・英語・中国語・スペイン語・ドイツ語・ポルトガル語・オランダ語 — Django標準のi18nではなく、独自のセッションベース言語切替を使用 |
| 「UNITE CINEMA MINATO」 | 本体アプリとは無関係な、映画館風の座席予約ミニ機能（予約＋アンケート）が同じDjangoプロジェクトに同居 |

---

## アーキテクチャ

```
+-----------+     +--------------+     +---------------+
|  GitHub   |---->|  Render.com  |---->|  PostgreSQL   |
|  (main)   |     |  (Web Svc)   |     |  (Render DB)  |
+-----------+     +------+-------+     +---------------+
                         |
        +----------------+-----------------+
        v                v                 v
  +------------+  +----------------+  +--------------------+
  | Gemini API |  | Lyria API      |  |  Cloudflare R2 /    |
  | (OCR/歌詞) |  | (Google GenAI  |  |  Django Storage     |
  |            |  |  SDK, 楽曲生成) |  |  (音声ファイル)      |
  +------------+  +----------------+  +--------------------+
        |
        v  （任意, LYRICS_BACKEND=local/cloud/auto）
+-------------------------------------------+
|  自宅 / 学校 GPUサーバー                     |
|  RTX 4060 Ti（自宅）/ RTX 4080 x2（学校）    |
|  LoRA学習 + Flask/Gradio 推論サーバー         |
|  <-- Cloudflare Tunnel 経由で公開 -->        |
+-------------------------------------------+
```

> かつては音楽生成にMureka APIを使用していましたが、現在はGoogleのLyria（`google-genai` SDK経由）に完全移行済みです。Mureka関連のコードはレガシーDBフィールドやCSPのCDN許可リストとしてのみ残存しています（詳細は[開発タスク・技術的負債](#開発タスク--技術的負債)を参照）。

### 技術スタック

| レイヤー | 技術 |
|---------|------|
| **バックエンド** | Django 5.2 + Python 3.11+、Django Channels/Daphne（ASGI、WebSocketによる進捗更新） |
| **フロントエンド** | Bootstrap 5 + Vanilla JS、サーバーサイドレンダリングテンプレート |
| **データベース** | PostgreSQL（本番、`dj-database-url` 経由）/ SQLite（開発） |
| **キャッシュ / チャネルレイヤー** | 本番はRedis（`channels-redis`、キャッシュ、セッション）、未設定時はインメモリ |
| **ストレージ** | Cloudflare R2（音声ファイル）、WhiteNoise（静的ファイル） |
| **AIサービス** | Google Gemini（OCR＋歌詞＋フラッシュカード）、Google Lyria（楽曲生成、`google-genai` SDK）、自前ホストLoRAモデル、任意のOpenAI互換クラウドLLM |
| **決済** | Stripe Checkout ＋ Webhook署名検証によるサブスクリプション更新 |
| **デプロイ** | Render.com（`render.yaml`、`build.sh`）＋ gunicorn（本番のエントリーポイント。Channels/Daphneはローカル開発とWebSocketルーティング用） |
| **ML学習** | PyTorch、Transformers、PEFT（LoRA）、bitsandbytes（QLoRA 4bit）、TRL（SFTTrainer）、Flask（推論API）、Gradio（学習WebUI） |

---

## クイックスタート

### 前提条件

- Python 3.11以上
- Git
- （任意）Gemini / Stripe のAPIキー。Lyria利用にはGeminiのAPIキーと `google-genai` パッケージが必要

### インストール手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/Yulkjh/utamemo-app.git
cd utamemo-app

# 2. Python仮想環境をセットアップ
cd myproject
python3 -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate

# 3. 依存関係をインストール
pip install -r ../requirements.txt

# 4. 環境変数を設定
cp .env.example .env
# .env を編集してAPIキーや設定値を入力
# 注意: 現在 myproject/.env.example は空ファイルです。
# 下記「環境変数」セクションを参照して手動で設定してください。

# 5. データベースを初期化
python manage.py migrate

# 6. 管理者ユーザーを作成（任意）
python manage.py createsuperuser

# 7. 開発サーバーを起動
python manage.py runserver
# http://127.0.0.1:8000 にアクセス
```

### 環境変数

> **注意**: `myproject/.env.example` は現在空ファイルのため、下記を参考に手動で `.env` を作成してください（技術的負債として記録済み、[開発タスク・技術的負債](#開発タスク--技術的負債)参照）。

```bash
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# AIサービス（任意 — 未設定でも動作はするがAI機能は無効化される）
GEMINI_API_KEY=your-gemini-key

# 楽曲生成（Lyria）
DEFAULT_SONG_GENERATION_PROVIDER=lyria
LYRIA_MODEL=lyria-3-pro-preview
USE_LYRIA_API=True

# 歌詞バックエンド選択: gemini | cloud | local | ollama | auto
LYRICS_BACKEND=gemini

# Stripe（任意、決済機能を使う場合）
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_STARTER_PRICE_ID=price_xxx
STRIPE_PRO_PRICE_ID=price_xxx
```

その他の主な環境変数: `REDIS_URL`（Redisキャッシュ/チャネルレイヤー/セッション、未設定時はインメモリ）、`DATABASE_URL`（本番PostgreSQL接続先）、`LOCAL_LLM_URL` / `LOCAL_LLM_API_KEY`（自前ホストGPUサーバー）、`CLOUD_LLM_PROVIDER` / `CLOUD_LLM_URL` / `CLOUD_LLM_MODEL`（Together AI / Fireworks / Groq / OpenRouter / vLLM）、`OLLAMA_URL` / `OLLAMA_MODEL`（ローカルOllama）、`ADMIN_ALLOWED_IPS`（管理画面IP許可リスト）、`SITE_BASE_URL` / `PUBLIC_ALLOWED_HOSTS`、`EMAIL_*`（管理者2FAメール送信用）。

---

## プロジェクト構成

```
utamemo-app/
├── myproject/
│   ├── myproject/                # Djangoプロジェクト設定
│   │   ├── settings.py           # 設定全般（DB、AI、セキュリティ、Stripe料金）
│   │   ├── urls.py                # ルートURLルーティング
│   │   ├── security.py            # カスタムSecurityMiddleware / 管理画面2FA
│   │   ├── context_processors.py  # 言語切替・料金プラン表示用コンテキスト
│   │   ├── legal_views.py         # プライバシー/利用規約/お問い合わせページ
│   │   └── queue_manager.py       # 未使用の残置ファイル（下記「技術的負債」参照）
│   ├── songs/                     # メインアプリ：楽曲、歌詞、フラッシュカード、クラス、AI連携
│   │   ├── models.py              # 23モデル：Song, Lyrics, Classroom, FlashcardDeck,
│   │   │                          #   TrainingSession, DataPartner, TrainingData 他
│   │   ├── views/                 # ビューパッケージ（機能ごとに分割）
│   │   │   ├── song_crud.py       # 楽曲のCRUD（作成・一覧・削除・タイトル更新・公開設定・タグ）
│   │   │   ├── generation.py      # アップロード/OCR、歌詞確認、生成API
│   │   │   ├── home.py            # ホーム、楽曲一覧/詳細、"UNITE CINEMA MINATO"劇場機能
│   │   │   ├── classroom.py       # クラスCRUD、参加/退出、課題
│   │   │   ├── flashcard.py       # フラッシュカードCRUD/学習
│   │   │   ├── training.py        # スタッフ限定LLM学習ダッシュボード＋API
│   │   │   ├── staff.py           # スタッフツール、品質チェック
│   │   │   ├── social.py          # いいね/お気に入り/コメント/再生履歴
│   │   │   ├── utility.py         # 言語切替、音声プロキシ、違反ページ
│   │   │   └── core.py            # ※未使用の残置ファイル（下記「技術的負債」参照）
│   │   ├── services/               # AI連携レイヤー
│   │   │   ├── lyria.py           # LyriaAIGenerator（楽曲生成、google-genai SDK）
│   │   │   ├── song_generation.py # プロバイダ非依存の楽曲生成ヘルパー（現状Lyriaのみ対応）
│   │   │   ├── gemini_lyrics.py   # GeminiLyricsGenerator
│   │   │   ├── gemini_ocr.py      # GeminiOCR
│   │   │   ├── local_llm.py       # LocalLLM/CloudLLM歌詞生成、バックエンド選択ファクトリ
│   │   │   ├── ollama.py          # OllamaLyricsGenerator
│   │   │   ├── pdf_extractor.py   # PyMuPDFによるテキスト抽出
│   │   │   ├── hiragana.py        # 歌詞のふりがな変換
│   │   │   ├── flashcard_extractor.py  # GeminiFlashcardExtractor
│   │   │   ├── text_processing.py # Gemini共通ヘルパー（旧google-generativeai SDK使用）
│   │   │   └── cache.py           # APIレスポンスキャッシュ
│   │   ├── ai_services.py         # services/ への後方互換re-exportシム
│   │   ├── content_filter.py      # 日英中3言語対応ルールベースコンテンツモデレーション
│   │   ├── queue_manager.py       # ThreadPoolExecutorベースの生成キュー＋WebSocket進捗通知
│   │   ├── consumers.py / routing.py  # Django Channels WebSocketハンドラ
│   │   ├── forms.py, admin.py, apps.py
│   │   ├── templatetags/          # カスタムテンプレートフィルタ
│   │   ├── management/commands/   # 定期実行コマンド（アンケート送信、パートナーデータ削除等）
│   │   ├── migrations/            # 45マイグレーション
│   │   └── tests.py                # 約80テスト
│   ├── users/                      # ユーザー管理アプリ
│   │   ├── models.py               # カスタムUser（プラン/BAN/年齢確認フィールド）、
│   │   │                           #   StaffReviewObligation, TrainingDataReview,
│   │   │                           #   TrainingDataEditLog, StaffMessage, ReviewBackup 他
│   │   ├── views.py                 # 認証、プロフィール、Stripe決済/Webhook
│   │   ├── middleware.py            # BanCheckMiddleware, StaffReviewLockMiddleware
│   │   ├── forms.py
│   │   └── tests.py                 # 約23テスト
│   ├── templates/                   # HTMLテンプレート
│   │   ├── base.html                 # Bootstrap 5ベーステンプレート
│   │   ├── songs/                    # 楽曲、フラッシュカード、クラス、スタッフツール、劇場機能テンプレート
│   │   ├── users/                    # 認証、プロフィール、アップグレード/請求テンプレート
│   │   ├── admin/                    # 管理画面2FA、監視テンプレート
│   │   └── legal/                    # プライバシー、利用規約、お問い合わせ
│   ├── static/                       # CSS、JS、画像
│   ├── .env.example                  # ※現在空ファイル（技術的負債）
│   └── manage.py
├── training/                        # 自前ホストLoRA学習＋推論パイプライン（歌詞生成専用）
│   ├── train.py                     # QLoRAファインチューニングスクリプト（argparse CLI、マルチGPU対応）
│   ├── serve.py                     # Flask REST推論サーバー（/health, /generate）
│   ├── training_agent.py            # オーケストレーションエージェント：Djangoをポーリングし train.py/serve.py を起動
│   ├── webui/app.py                 # 学習基盤用のGradio WebUI
│   ├── export_training_data.py      # 本番DBから学習データをエクスポート
│   ├── generate_history_data.py     # Geminiによる学習データの合成生成
│   ├── build_lyrics_dataset.py / build_importance_dataset.py  # データセット構築
│   ├── quality_check.py             # 生成データの品質チェック
│   ├── lyrics_generation/, note_importance/  # 2種のモデルのデータセットビルダー/トレーナー
│   ├── requirements_training.txt
│   └── README.md
├── docs/                             # 設計ドキュメント（日本語）
│   ├── SOFTWARE_DESIGN.md           # 詳細ソフトウェア設計、シーケンス図、技術的負債ログ
│   ├── ARCHITECTURE.md              # システム構成、ER図、URLルーティング表
│   ├── CUSTOM_LLM_ROADMAP.md        # 自前ホストLLM構想のロードマップ
│   ├── DATA_PARTNER_COMPLIANCE.md   # 外部データ提携先（Clearnote/Kokuyo等）のコンプライアンス管理
│   └── meeting_pitch_*.md           # 事業提携ピッチ資料（Clearnote、Kokuyo向け）
├── UtaMemo/                          # 独立したSwiftUI iOSプロトタイプ（独自gitリポジトリ、バックエンド未連携）
├── requirements.txt                  # 本番依存関係（Djangoアプリ）
├── render.yaml                       # Render.comデプロイ設定
├── build.sh                          # Renderビルドスクリプト
├── Procfile
├── DOMAIN_SETUP.md / DOMAIN_SETUP_EN.md  # ドメイン/DNS設定ガイド
└── CONTRIBUTING.md                   # 共同開発ガイド
```

---

## コアワークフロー

### 1. 楽曲生成パイプライン

```
ユーザーが写真またはPDFをアップロード
       |
       v
Gemini OCR（画像）または PyMuPDF（PDF）でテキストを抽出
       |
       v
ContentFilterが抽出テキストを検証
       |
       v
LYRICS_BACKEND に従って歌詞を生成
  （gemini | cloud | local | ollama | auto）
  autoモードは クラウドLLM → Ollama → ローカルLLM → Gemini の順に試行
       |
       v
ユーザーが歌詞を確認・編集して確定
       |
       v
songs/queue_manager.py のキューに投入
  （ThreadPoolExecutor、並列数制限、リトライ＋バックオフ）
       |
       v
Lyria API（Google GenAI SDK）が楽曲を生成
       |
       v
任意: Demucsベースのカラオケ（インスト）音源抽出
       |
       v
音声をストレージに保存。Django ChannelsのWebSocketで
  進捗をリアルタイム配信
       |
       v
生成完了 -> 一意のshare_idで共有可能に
```

### 2. フラッシュカード生成

```
楽曲の歌詞または元画像
       |
       v
Geminiが用語・定義ペアを抽出（GeminiFlashcardExtractor）
       |
       v
FlashcardDeckを作成、重要度でカードにタグ付け（高/通常）
       |
       v
ユーザーが学習。カードごとに4段階の習熟度を記録
  （未学習 / 学習中 / もう少し / 覚えた）
```

### 3. サブスクリプションフロー

```
ユーザーがアップグレードをクリック
       |
       v
年齢確認（18歳未満は保護者同意が決済前に必須）
       |
       v
Stripe Checkoutセッションを作成（プラン別の価格ID）
       |
       v
決済完了
       |
       v
Stripe Webhookの署名を検証
       |
       v
User.planを更新（starter / pro / school）、
  月間生成上限を再計算
```

### 4. クラス機能（School プラン）

```
教師がClassroomを作成 -> 一意の参加コードを発行
       |
       v
生徒に参加コードを共有
       |
       v
生徒が参加コードで参加（Schoolプランが必要）
       |
       v
教師が楽曲をクラスに共有、または
  ClassroomAssignment（楽曲＋締切＋メモ）を作成
       |
       v
生徒は自動生成されたフラッシュカードで課題楽曲を学習
```

### 5. 自前ホストLLM学習ループ（歌詞生成専用）

```
DjangoでTrainingSessionレコードが作成 / スタッフが
  pending_command を発行（start / stop / start_serve）
       |
       v
training_agent.py（GPUマシン上で稼働）がDjangoのAPIを
  ポーリングし、コマンドを取得
       |
       v
train.py がQLoRAファインチューニングを実行し、
  損失/ステップ/GPU使用率などをTrainingSessionに
  リアルタイム報告
       |
       v
serve.py（Flask）または webui/app.py（Gradio）が
  ファインチューニング済みモデルをHTTPで公開。
  Cloudflare Tunnel経由でインターネットに接続
       |
       v
本番環境で LOCAL_LLM_URL / LYRICS_BACKEND=local（またはauto）
  を設定し、歌詞生成を自前ホストモデルにルーティング
```

> このパイプラインは**歌詞生成専用**です。楽曲（音声）生成には一切関与せず、音楽生成は常にLyria（`songs/services/lyria.py`）が担当します。

---

## データモデル（抜粋）

**`songs` アプリ** — `Song`（タイトル、ジャンル、ボーカルスタイル、生成ステータス/キュー位置/リトライ回数、暗号化フラグ、share_id、いいね/再生カウンタ、カラオケステータス。`mureka_model` フィールドはMureka提供終了に伴いレガシー参照としてのみ残存）、`Lyrics`（本文、OCR元テキスト、LRCタイミングデータ）、`Tag`、`Like` / `Favorite` / `Comment` / `PlayHistory`、`UploadedImage`、`Classroom` / `ClassroomMembership` / `ClassroomSong` / `ClassroomAssignment`、`FlashcardDeck` / `Flashcard`、`TrainingSession`（GPU/損失/ステップ指標、Wake-on-LANフィールド、ハートビート）、`PromptTemplate`（DB管理の歌詞プロンプト、再デプロイ後も保持）、`TrainingData`（SHA-256ハッシュで重複排除、`DataPartner`への任意の外部キーを保持）、`DataPartner` / `DataPartnerAuthorization` / `PartnerDataAccessLog`（外部データ提携先とのMOU管理・アクセス権限・監査ログ）、そして本体とは無関係な `TheaterReservation` / `TheaterSurveyResponse`（劇場予約機能用）。

**`users` アプリ** — プラン（`free`/`starter`/`pro`/`school`）、Stripe顧客/サブスクリプションID、BANフィールド（`is_banned`, `ban_reason`, `banned_at`）、教師フラグ、生年月日＋保護者同意フィールドと `is_minor`/`can_purchase()` ヘルパー、`get_monthly_song_limit()` などプラン別ヘルパーを持つカスタム `User(AbstractUser)`。加えて `StaffReviewObligation`（スタッフに課される学習データレビュー義務。自動的に蓄積し、滞留すると他の管理ページをロックする）、`TrainingDataReview`（ソフトデリート可能なレビューキュー、ハッシュで重複排除）、`TrainingDataEditLog`、`StaffMessage`、`ReviewBackup`。

---

## セキュリティ機能

| 脅威 | 対策 | 実装箇所 |
|------|------|----------|
| 不正/有害な入力 | 日英中3言語対応のルールベース `ContentFilter`（学術/歌詞文脈アローリスト付き） | `songs/content_filter.py` |
| SSRF | 音声プロキシのドメイン許可リスト | `songs/views/utility.py: audio_proxy()` |
| CSRF | DjangoのCSRFミドルウェア | `settings.py` |
| 権限昇格 | `@login_required` ＋ オブジェクト単位の所有者チェック | 該当する全ビュー |
| 管理画面アクセス | メールベースの2段階認証 ＋ IP許可リスト | `myproject/security.py` |
| BAN回避 | `BanCheckMiddleware` がBANされたユーザーを全リクエストで強制ログアウト | `users/middleware.py` |
| 決済偽造 | Stripe Webhook署名検証 | `users/views.py` |
| 未成年の決済 | 生年月日の取得＋決済前の保護者同意ゲート | `users/models.py`, `users/views.py` |
| シークレット漏えい | 環境変数のみで管理、`.env` はgit除外 | — |
| スタッフのデータレビュー回避 | `StaffReviewLockMiddleware` がレビュー義務の滞留がしきい値を超えたスタッフをレビューキューにロック | `users/middleware.py` |

### 暗号化

楽曲はFernet対称鍵暗号で暗号化保存できます。
- AES-128-CBC暗号モード
- Django `SECRET_KEY` ＋ 楽曲ごとのソルトから導出した256ビット鍵
- 完全性検証用のHMAC認証

---

## サブスクリプションプラン

| プラン | 価格 | 月間生成上限 | クラス機能 |
|--------|------|--------------|-----------|
| **Free** | ¥0 | 5曲/月 | なし |
| **Starter** | ¥780/月 | 70曲/月 | なし |
| **Pro** | ¥1,900/月 | 無制限 | なし |
| **School** | ¥450 / 生徒 / 月 | 100曲/月 | あり |
| **Staff** | 無料（招待制） | 無制限 | あり |

> スタッフ/スーパーユーザーアカウントは、割り当てプランに関わらず全機能を自動的に利用できます。

---

## AI連携の詳細

- **歌詞生成**は共通インターフェースの背後でプロバイダ非依存に実装されており、`LYRICS_BACKEND` で選択します（デフォルトは `gemini`）:
  - `gemini`（デフォルト） — Google Gemini
  - `cloud` — OpenAI互換の任意のエンドポイント（Together AI、Fireworks AI、Groq、OpenRouter、または独自のvLLMサーバー）
  - `local` — チーム自前ホストのGPU推論サーバー（`training/serve.py`）
  - `ollama` — 開発用のローカルOllama
  - `auto` — 実際の稼働状況チェックに基づき、クラウドLLM → Ollama → ローカルLLM → Gemini の順に試行
- **楽曲生成**はGoogleの **Lyria**（`lyria-3-pro-preview`）を、`google-genai` SDK（`client.interactions.create()`）経由で利用します。ジャンル・ボーカルスタイル固有のプロンプトエンジニアリング（日本語→英語のジャンル変換辞書、固定ボイスプリセット、ランダムなトーン/年齢バリエーション）を実装。生成された音声はDjangoのストレージに保存されます。
  - 旧来使用していたMureka APIは提供終了に伴い完全に廃止され、現行コードでは `SUPPORTED_SONG_PROVIDERS = ('lyria',)` のみがサポートされています。
- **OCR**は写真にGemini、PDFにPyMuPDFを使用します。
- **フラッシュカード抽出**はGeminiで歌詞や元テキストから用語・定義ペアを重要度タグ付きで生成します。
- **カラオケトラック**はDemucsによる音源分離で、生成済み楽曲のインストのみのバージョンを作成します。

---

## 自前ホストLLM学習基盤

UTAMEMOには、チーム所有ハードウェア上で歌詞生成専用のカスタムLLMをファインチューニング・配信するための一連のパイプライン（`training/` 配下）が含まれています。クラウドLLM APIを常時呼び出す代わりのコスト削減策として位置づけられています。

- **ハードウェア**: 自宅のRTX 4060 Ti（16GB）と、学校のRTX 4080 ×2（各16GB）
- **ベースモデル**: デフォルトはLlama 3 8B。Gemma 2 9B、Qwen2.5（7B/14B/32B）などにも対応、GPUが2台以上の場合は自動でマルチGPUメモリ分割
- **ファインチューニング手法**: QLoRA（4bit、`bitsandbytes` + `peft`）。ランク/エポック数などは `train.py` のCLI引数で設定可能
- **オーケストレーション**: `training_agent.py` がGPUマシン上で稼働し、Djangoの `TrainingSession` モデルの保留コマンド（`start`/`stop`/`start_serve`）をポーリングして実行。損失・ステップ・GPU/VRAM使用率・ETAなどのライブ指標をWebアプリに報告
- **配信**: `serve.py` は `transformers` と `vllm` の両推論バックエンドに対応したFlask REST API（`/health`, `/generate`、APIキー認証）。`webui/app.py` は別途Gradioベースの管理WebUIを提供
- **接続**: 推論サーバーはCloudflare Tunnel経由でインターネットに公開され、Render（本番）が `LOCAL_LLM_URL` として到達可能
- **データパイプライン**: 学習データは本番からエクスポート（`export_training_data.py`）、サンプリング、またはGeminiによる合成生成（`generate_history_data.py`）で用意。SHA-256ハッシュで重複排除され、学習に使う前にスタッフレビュー（`StaffReviewObligation`/`TrainingDataReview`）が必要
- **2つのモデルトラック**: `lyrics_generation/`（メインの歌詞モデル）と `note_importance/`（抽出テキストの重要度をスコアリングする補助モデル）
- **音楽生成は非対応**: このパイプラインは歌詞生成のみを対象とし、楽曲（音声）生成はLyriaが単独で担当します

セットアップの詳細は [training/README.md](training/README.md) を参照してください。

---

## テスト

```bash
# 全テストを実行
python manage.py test --verbosity=2

# 特定アプリのテストを実行
python manage.py test songs --verbosity=2
python manage.py test users --verbosity=2
```

**現在のテストカバレッジ:** 約103テスト（`songs` に約80、`users` に約23）。AIサービス呼び出しはまだモック化/テストされていません（技術的負債として記録、下記参照）。

---

## 多言語対応

UTAMEMOはDjango標準のi18nフレームワークではなく、独自の**セッションベース**言語切替を使用しています。

対応言語: `ja`（日本語）、`en`（英語）、`zh`（中国語）、`es`（スペイン語）、`de`（ドイツ語）、`pt`（ポルトガル語）、`nl`（オランダ語）

テンプレート分岐の例:
```html
{% if app_language == 'en' %}
  <h1>My Songs</h1>
{% elif app_language == 'ja' %}
  <h1>マイソング</h1>
{% endif %}
```

---

## ブランチ戦略

```
main                 <- 本番（直接pushは禁止）
├── feature/xxx      <- 新機能
├── fix/xxx          <- バグ修正
├── docs/xxx         <- ドキュメント更新
└── refactor/xxx     <- リファクタリング
```

### コミットメッセージ規約

| プレフィックス | 目的 | 例 |
|--------|------|------|
| `feat:` | 新機能 | `feat: フラッシュカードのフィルタ機能追加` |
| `fix:` | バグ修正 | `fix: ログイン時のリダイレクトエラーを修正` |
| `docs:` | ドキュメント | `docs: README にセットアップ手順追加` |
| `style:` | UI/CSS | `style: ソングカードのレスポンシブ対応` |
| `refactor:` | リファクタリング | `refactor: views.py の重複コードを統合` |
| `test:` | テスト | `test: Song モデルのユニットテスト追加` |
| `chore:` | その他 | `chore: requirements.txt 更新` |

---

## 開発タスク・技術的負債

[docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md) で詳細に管理:

| ID | 優先度 | タスク | 状態 |
|----|--------|------|------|
| D-1 | 高 | `ai_services.py` のモノリスを `services/` モジュールへ分割 | **完了** — `songs/services/` へのre-exportシムに置き換え済み |
| D-2 | 高 | `views/core.py`（`song_crud.py`/`home.py`等に機能移管済みだが、ファイル自体は未削除で残置） | 削除待ち |
| D-3 | 高 | `myproject/myproject/queue_manager.py` の削除 — 存在しない `MurekaAIGenerator` をimportしており、実行されればcrashする未使用の残置ファイル | 削除待ち |
| D-4 | 高 | `myproject/.env.example` が空ファイル。実際に必要な環境変数（`GEMINI_API_KEY`, `LYRIA_*`, `LYRICS_BACKEND`, `STRIPE_*` 等）を反映して再作成 | 未着手 |
| D-5 | 中 | `songs/models.py`（23モデル）を複数モジュールに分割 | 計画中 |
| D-6 | 中 | サービス層の明確化 — 一部のビジネスロジックがまだビューに残存 | 計画中 |
| D-7 | 中 | AIサービスのモックテストを追加（現状ゼロ） | 計画中 |
| D-8 | 低 | `training/README.md` の `auto` バックエンド説明（「local優先」）が実際のコード（クラウド→Ollama→ローカル→Gemini）と乖離しているため修正 | 未着手 |
| D-9 | 低 | セッションベースi18nからDjango標準のi18nフレームワークへの移行 | 将来対応 |
| D-10 | 低 | フロントエンドのテストカバレッジ追加（現状なし） | 将来対応 |

---

## 管理者・スタッフ機能

### 管理ツール
- **2段階認証**: 管理画面アクセス用のメールベース2FA（コード有効期限あり、8時間の検証済みセッションウィンドウ）、任意のIP許可リスト
- **監視ダッシュボード**（`staff_monitor.html`）: リアルタイムのシステム/キュー監視
- **コンテンツモデレーション**: ユーザー生成コンテンツの通報とフィルタ違反の閲覧・管理
- **BAN管理**: ユーザーのBAN/解除、次回リクエスト時の強制ログアウト

### スタッフ向けLLMツール
- **学習ダッシュボード**: LoRA学習セッション（損失、GPU使用率、ETA）をリアルタイム監視
- **データレビューキュー**: 学習データを使用前にスタッフがレビュー/承認/却下する必要あり（レビュー義務が蓄積し、滞留するとスタッフを他ページから締め出す仕組み付き）
- **プロンプトテンプレートエディタ**: DB永続化された歌詞生成用プロンプトテンプレートを管理（ファイルベースと異なり再デプロイ後も保持）
- **LLM/Lyriaテストツール**（`test_llm.html` 等）: AIバックエンドの手動テスト用UI
- **品質チェックツール**: 学習データが学習実行に投入される前の品質レビュー

---

## APIエンドポイント（内部、抜粋）

`songs/urls.py` が約74ルート、`users/urls.py` が約21ルートを定義。主なものを抜粋:

| URLパターン | ビュー | 認証 | 説明 |
|-------------|--------|------|------|
| `/songs/create/` | CreateSongView | ログイン必須 | 楽曲作成ページ |
| `/songs/generate/` | UploadImageView | ログイン必須 | 教科書写真/PDFのアップロード |
| `/songs/lyrics/generate/`（API） | generate_lyrics_api | ログイン必須 | 現在有効なAIバックエンドで歌詞生成 |
| `/songs/<id>/` | SongDetailView | 公開 | 楽曲詳細ページ |
| `/songs/my/` | MySongsView | ログイン必須 | ユーザーの楽曲一覧 |
| `/songs/classroom/` | ClassroomListView | Schoolプラン | クラス管理 |
| `/songs/flashcard/` | FlashcardDeckListView | ログイン必須 | フラッシュカードデッキ |
| `/accounts/register/` | RegistrationView | 未ログインのみ | ユーザー登録 |
| `/accounts/upgrade/` | upgrade_plan | ログイン必須 | サブスクリプションのアップグレード |
| `/api/stripe/create-session/` | create_checkout_session | ログイン必須 | Stripe Checkoutセッションの作成 |
| `/stripe/webhook/` | stripe_webhook | Webhookシークレット | Stripe Webhookハンドラ |

完全なルート一覧は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

---

## ドキュメント

- [CONTRIBUTING.md](CONTRIBUTING.md) — 共同開発ガイド
- [docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md) — 詳細ソフトウェア設計、シーケンス図、技術的負債ログ
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — システム構成、ER図、URLルーティング全表
- [docs/CUSTOM_LLM_ROADMAP.md](docs/CUSTOM_LLM_ROADMAP.md) — 自前ホストLLM構想のロードマップ
- [docs/DATA_PARTNER_COMPLIANCE.md](docs/DATA_PARTNER_COMPLIANCE.md) — 外部データ提携先（Clearnote、Kokuyo等）とのMOUコンプライアンス管理
- [DOMAIN_SETUP.md](DOMAIN_SETUP.md) / [DOMAIN_SETUP_EN.md](DOMAIN_SETUP_EN.md) — ドメイン/DNS設定ガイド（日本語版/英語版）
- [training/README.md](training/README.md) — 自前ホストLLM学習サーバーのセットアップガイド

> 注: `docs/SOFTWARE_DESIGN.md` と `docs/ARCHITECTURE.md` は2026-04-17時点の内容から更新されておらず、一部の最近のコード変更（例: Mureka → Lyriaへの音楽生成基盤の移行、`views/core.py` の分割）に追いついていません。

---

## コントリビューション

コントリビューションを歓迎します！セットアップ手順と開発ルールは [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

### はじめに

1. リポジトリをフォーク
2. フィーチャーブランチを作成: `git checkout -b feature/your-feature-name`
3. 変更を実装
4. コミット規約に従ってコミット
5. push してプルリクエストを作成

---

## 謝辞

- **Django** — 締め切りに追われる完璧主義者のためのWebフレームワーク
- **Bootstrap 5** — フロントエンドフレームワーク
- **Google Gemini** — OCR、歌詞生成、フラッシュカード抽出
- **Google Lyria** — AI楽曲生成（`google-genai` SDK）
- **Stripe** — 決済処理
- **Cloudflare R2 / Tunnel** — オブジェクトストレージと自前ホストサーバーとの接続
- **PEFT / bitsandbytes / TRL** — 自前ホスト歌詞モデルのLoRA/QLoRAファインチューニング

---

UTAMEMO開発チーム制作

# UTAMEMO ソフトウェア設計書

> 最終更新: 2026-04-17  
> 関連: [ARCHITECTURE.md](./ARCHITECTURE.md) — システム構成・ルーティング・API一覧

---

## 1. 設計思想

### 1.1 コンセプト
UTAMEMO は「**暗記ソングで楽しく学ぶ**」教育×音楽 AI アプリケーション。  
教科書やノートの写真 → AI歌詞生成 → AI楽曲生成 のパイプラインを提供する。

### 1.2 設計原則

| 原則 | 内容 | 現状 |
|------|------|------|
| **責務の分離** | ドメインごとにモジュールを分割 | △ views分割済、models/ai_services未分割 |
| **薄いビュー** | ビジネスロジックはモデル/サービス層に | △ views/core.pyに一部残存 |
| **外部依存の隔離** | AI/決済APIはサービスクラスでラップ | ○ ai_services.py, Stripe views |
| **テスト容易性** | モック可能な設計、依存注入 | △ 78テスト、AI系未カバー |
| **セキュリティ優先** | 入力検証、権限チェック、SSRF防止 | ○ content_filter, whitelist |

---

## 2. ドメインモデル

### 2.1 境界づけられたコンテキスト (Bounded Contexts)

```
┌─────────────────────────────────────────────────────────────────┐
│                        UTAMEMO System                           │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  🎵 楽曲      │  │  📚 教育      │  │  🤖 AI サービス       │ │
│  │  コンテキスト  │  │  コンテキスト  │  │  コンテキスト          │ │
│  │              │  │              │  │                       │ │
│  │  Song        │  │  Classroom   │  │  GeminiLyricsGen      │ │
│  │  Lyrics      │  │  Membership  │  │  MurekaAIGen          │ │
│  │  Tag         │  │  ClassroomSong│ │  GeminiOCR            │ │
│  │  Like        │  │  FlashcardDeck│ │  LocalLLMLyricsGen    │ │
│  │  Favorite    │  │  Flashcard   │  │  CloudLLMLyricsGen    │ │
│  │  Comment     │  │              │  │  FlashcardExtractor   │ │
│  │  PlayHistory │  │              │  │  ContentFilter        │ │
│  │  UploadedImage│ │              │  │  PDFTextExtractor     │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘ │
│         │                 │                       │             │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌───────────┴───────────┐ │
│  │  👤 ユーザー  │  │  💳 決済      │  │  🧪 LLM学習           │ │
│  │  コンテキスト  │  │  コンテキスト  │  │  コンテキスト          │ │
│  │              │  │              │  │                       │ │
│  │  User        │  │  Stripe連携  │  │  TrainingSession      │ │
│  │  Profile     │  │  Checkout    │  │  TrainingData         │ │
│  │  Plan/Limits │  │  Webhook     │  │  PromptTemplate       │ │
│  │  BAN管理     │  │  Subscription│  │  TrainingDataReview   │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 コンテキスト間の依存関係

```
楽曲 ──depends──▶ ユーザー (created_by, owner権限)
楽曲 ──depends──▶ AI サービス (歌詞生成, 楽曲生成)
教育 ──depends──▶ ユーザー (is_school判定)
教育 ──depends──▶ 楽曲 (ClassroomSong, FlashcardDeck.source_song)
教育 ──depends──▶ AI サービス (FlashcardExtractor)
決済 ──depends──▶ ユーザー (plan更新)
LLM学習 ──depends──▶ ユーザー (staff権限)
LLM学習 ──depends──▶ AI サービス (データ生成にGemini使用)
```

---

## 3. レイヤーアーキテクチャ

```
┌─────────────────────────────────────────────┐
│              プレゼンテーション層              │
│  templates/ (Bootstrap 5 + vanilla JS)       │
│  views/ (Django CBV/FBV)                     │
│  forms.py (入力バリデーション)                 │
├─────────────────────────────────────────────┤
│              ビジネスロジック層                │
│  models.py (ドメインモデル + クエリ)           │
│  ai_services.py (AIサービスクラス)            │
│  content_filter.py (コンテンツ検証)            │
│  queue_manager.py (非同期処理)                │
├─────────────────────────────────────────────┤
│              インフラ層                       │
│  settings.py (設定)                          │
│  middleware.py (BAN, 言語)                    │
│  security.py (Admin 2FA)                     │
│  外部API連携 (Gemini, Mureka, Stripe, R2)    │
├─────────────────────────────────────────────┤
│              データ層                         │
│  PostgreSQL (Render) / SQLite (開発)          │
│  Cloudflare R2 (音声ストレージ)               │
│  Django ORM + migrations                     │
└─────────────────────────────────────────────┘
```

### 3.1 現在のファイル→レイヤー対応

| ファイル | 行数 | レイヤー | 責務 |
|---------|-----:|---------|------|
| `views/core.py` | 2,140 | プレゼンテーション+ビジネス | 楽曲CRUD, 歌詞フロー, いいね, 再生, タグ |
| `views/classroom.py` | 365 | プレゼンテーション | クラスCRUD, 参加/退出, 共有 |
| `views/flashcard.py` | 223 | プレゼンテーション | フラッシュカードCRUD, 学習 |
| `views/training.py` | 865 | プレゼンテーション+ビジネス | LLM学習ダッシュボード, API |
| `views/staff.py` | 699 | プレゼンテーション | スタッフツール, モニタリング |
| `ai_services.py` | 2,966 | ビジネス | AI全般 (歌詞, 楽曲, OCR, カード) |
| `songs/models.py` | 915 | ドメイン | 16モデル (楽曲+教育+学習) |
| `users/models.py` | 472 | ドメイン | User + レビュー + スタッフ管理 |
| `users/views.py` | 705 | プレゼンテーション+ビジネス | 認証, プロフ, 決済, Webhook |
| `content_filter.py` | 906 | ビジネス | 不適切コンテンツ検出 |

---

## 4. 主要ユースケースフロー

### 4.1 楽曲生成フロー (コア機能)

```
ユーザー                    Django                       外部API
  │                         │                            │
  ├─ 画像アップロード ──────▶ UploadImageView              │
  │                         ├─ validate_uploaded_file()   │
  │                         ├──────────────────────────▶ GeminiOCR.extract()
  │                         │◀─────────────────────────── テキスト抽出結果
  │◀─ OCR結果表示 ──────────┤                             │
  │                         │                            │
  ├─ 歌詞生成リクエスト ────▶ generate_lyrics_api          │
  │                         ├─ ContentFilter.check()      │
  │                         ├──────────────────────────▶ GeminiLyricsGen.generate()
  │                         │                            │  (or LocalLLM / CloudLLM)
  │                         │◀─────────────────────────── 歌詞テキスト
  │◀─ 歌詞確認画面 ────────┤                             │
  │                         │                            │
  ├─ 楽曲生成確定 ──────────▶ LyricsConfirmationView.post  │
  │                         ├─ Song.objects.create()      │
  │                         ├──────────────────────────▶ MurekaAIGen.submit_generation()
  │                         │   (非同期: generation_status='pending')
  │◀─ 生成中画面 ──────────┤                             │
  │                         │                            │
  ├─ ポーリング ────────────▶ check_song_status            │
  │                         ├──────────────────────────▶ MurekaAIGen.poll_status()
  │                         │◀─────────────────────────── audio_url
  │                         ├─ Song.save(status='completed')
  │◀─ 完成画面リダイレクト ─┤                             │
```

### 4.2 決済フロー (Stripe)

```
ユーザー              Django                    Stripe
  │                   │                         │
  ├─ アップグレード ─▶ create_checkout_session    │
  │                   ├─ 年齢確認 (未成年→同意)   │
  │                   ├───────────────────────▶ Checkout Session作成
  │◀─ Stripe画面 ────┤                          │
  │                   │                         │
  ├─ 決済完了 ────────┼─────────────────────────▶│
  │                   │                         │
  │                   │◀── Webhook ─────────────┤
  │                   ├─ 署名検証                │
  │                   ├─ checkout.session.completed:
  │                   │   user.plan = 'starter'
  │                   │   user.stripe_subscription_id = ...
  │                   │                         │
  │                   │◀── Webhook (将来) ──────┤
  │                   ├─ customer.subscription.deleted:
  │                   │   user.plan = 'free'
```

### 4.3 クラス機能フロー (教育コンテキスト)

```
教師                    Django                    生徒
  │                      │                        │
  ├─ クラス作成 ────────▶ classroom_create         │
  │  (is_school必須)      ├─ code自動生成           │
  │◀─ コード表示 ───────┤                         │
  │                      │                        │
  │   コードを生徒に共有 ─────────────────────────▶│
  │                      │                        │
  │                      │◀── classroom_join ─────┤
  │                      │   (is_school必須)       │
  │                      │   code照合 → Membership作成
  │                      │                        │
  ├─ 曲を共有 ──────────▶ classroom_share_song     │
  │                      ├─ ClassroomSong作成      │
  │                      │                        │
  │                      │◀── classroom_detail ───┤
  │                      │   共有楽曲一覧表示       │
```

---

## 5. データフロー図

### 5.1 全体データフロー

```
                    ┌─────────────┐
                    │   ブラウザ    │
                    └──────┬──────┘
                           │ HTTP
                    ┌──────▼──────┐
                    │   Django     │
                    │   Views      │
                    └──┬──┬──┬────┘
                       │  │  │
          ┌────────────┘  │  └────────────┐
          ▼               ▼               ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │  Models     │  │ AI Services│  │  External   │
   │  (ORM)      │  │            │  │  (Stripe)   │
   └──────┬─────┘  └──┬─────┬──┘  └────────────┘
          │            │     │
          ▼            ▼     ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │ PostgreSQL  │  │ Gemini API │  │ Mureka API │
   └────────────┘  └────────────┘  └──────┬─────┘
                                          │
                                   ┌──────▼─────┐
                                   │ Cloudflare  │
                                   │ R2 (音声)    │
                                   └────────────┘
```

---

## 6. 権限モデル

### 6.1 ユーザー種別と権限マトリクス

| 操作 | anonymous | free | starter | pro | school | staff | superuser |
|------|:---------:|:----:|:-------:|:---:|:------:|:-----:|:---------:|
| 楽曲閲覧 | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| 楽曲生成 | × | ○(制限) | ○(制限) | ○(無制限) | ○(カスタム) | ○(無制限) | ○(無制限) |
| V8モデル | × | ○ | ○ | ○ | ○ | ○ | ○ |
| 全モデル | × | × | × | ○ | ○ | ○ | ○ |
| いいね/お気に入り | × | ○ | ○ | ○ | ○ | ○ | ○ |
| クラス機能 | × | × | × | × | ○ | ○ | ○ |
| フラッシュカード | × | ○ | ○ | ○ | ○ | ○ | ○ |
| スタッフツール | × | × | × | × | × | ○ | ○ |
| Django Admin | × | × | × | × | × | ○ | ○ |
| モニタリング | × | × | × | × | × | × | ○ |

### 6.2 権限判定ロジック

```python
# User モデルのプロパティ (users/models.py)
User.is_pro        # staff/superuser → True, plan in (starter,pro,school) + 期限内 → True
User.is_pro_plan   # plan in (starter, pro, school) のみ (staff除外)
User.is_school     # plan == 'school' + 期限内, or staff/superuser
User.is_banned     # True → middleware でブロック
```

### 6.3 権限チェック箇所

| デコレータ/チェック | 使用場所 |
|------------------|---------|
| `@login_required` | 楽曲作成, マイページ, いいね, お気に入り, フラッシュカード |
| `@staff_member_required` | スタッフツール全般, 学習ダッシュボード |
| `request.user.is_school` | クラス機能 (ビュー内チェック → upgrade リダイレクト) |
| `request.user.is_superuser` | モニタリング, 一部Admin機能 |
| `BanMiddleware` | 全リクエスト (is_banned → 403) |

---

## 7. 状態遷移図

### 7.1 楽曲生成ステータス (Song.generation_status)

```
                 create
                   │
                   ▼
            ┌─────────────┐
            │   pending    │ ← 初期状態 (Mureka送信待ち)
            └──────┬──────┘
                   │ Mureka API submit
                   ▼
            ┌─────────────┐
            │  processing  │ ← Mureka生成中
            └──────┬──────┘
                   │
          ┌────────┼────────┐
          ▼                 ▼
   ┌─────────────┐   ┌──────────┐
   │  completed   │   │  failed   │
   │  (audio_url) │   │  (error)  │
   └─────────────┘   └──────┬───┘
                             │ retry
                             ▼
                      ┌─────────────┐
                      │   pending    │ (再試行)
                      └─────────────┘
```

### 7.2 LLM学習セッション (TrainingSession.status)

```
   idle ──▶ starting ──▶ generating_data ──▶ training ──▶ completed
     ▲                                                       │
     └───────────────────── (自動ループ) ────────────────────┘
                    │
                    ▼
                  error
```

### 7.3 クラスルーム (Classroom.is_active)

```
   作成 (is_active=True) ──▶ ソフトデリート (is_active=False)
                                   │
                                   × 復元不可 (現状)
```

---

## 8. 外部API統合パターン

### 8.1 AIサービスの Strategy パターン

```python
# 歌詞生成器のファクトリ (ai_services.py)
def get_lyrics_generator():
    """設定に応じた歌詞生成器を返す"""
    # LocalLLM → CloudLLM → Gemini の優先度で選択

# 各生成器は同じインターフェースを持つ:
class BaseLyricsGenerator:
    def generate(self, text, genre, custom_request, ...) -> str
```

| 生成器 | 対象 | フォールバック |
|--------|------|-------------|
| `LocalLLMLyricsGenerator` | 自作LoRA推論サーバー | → CloudLLM or Gemini |
| `CloudLLMLyricsGenerator` | クラウドLLM | → Gemini |
| `GeminiLyricsGenerator` | Google Gemini API | 最終フォールバック |
| `OllamaLyricsGenerator` | Ollama (開発用) | — |

### 8.2 Mureka API の非同期パターン

```
submit → task_id取得 → ポーリング (check_song_status) → 完了 or タイムアウト
```

- **タイムアウト**: ポーリングは最大数分
- **リトライ**: `retry_song_generation` で再送信
- **エラーハンドリング**: `generation_status = 'failed'` + エラーログ

### 8.3 Stripe Webhook の検証パターン

```python
# users/views.py stripe_webhook()
1. request.body + HTTP_STRIPE_SIGNATURE を取得
2. stripe.Webhook.construct_event() で署名検証
3. イベントタイプで分岐処理
4. 失敗時 400 返却
```

---

## 9. セキュリティ設計

### 9.1 脅威モデル

| 脅威 | 対策 | 実装箇所 |
|------|------|---------|
| **不正入力** | ContentFilter (禁止ワード + 文脈判定) | `content_filter.py` |
| **SSRF** | audio_proxy ドメインホワイトリスト | `views/core.py audio_proxy()` |
| **CSRF** | Django CSRF middleware (Webhookは`@csrf_exempt`) | `settings.py` |
| **権限昇格** | `@login_required`, `@staff_member_required`, ownership確認 | 各ビュー |
| **Admin侵入** | TOTP 2FA | `security.py` |
| **BAN回避** | `BanMiddleware` (全リクエスト) | `users/middleware.py` |
| **決済偽装** | Stripe署名検証 | `users/views.py` |
| **未成年課金** | `birth_date` + 保護者同意フロー | `users/views.py` |
| **秘密情報漏洩** | `os.getenv()` + 環境変数管理 | `settings.py` |

### 9.2 audio_proxy ホワイトリスト

```python
ALLOWED_DOMAINS = ['mureka.io', 'r2.cloudflarestorage.com', ...]
# URL のドメインを検証してからプロキシ
```

---

## 10. 現在の設計課題と改善計画

### 10.1 課題一覧

| ID | 重要度 | 課題 | 現状 | 改善案 |
|----|:------:|------|------|--------|
| D-1 | 🔴 高 | `ai_services.py` が巨大 (2,966行) | 6クラス+12関数が1ファイル | サービスごとにモジュール分割 |
| D-2 | 🔴 高 | `views/core.py` が巨大 (2,140行) | views分割の第1段階 | さらに song_crud / generation / social に分割 |
| D-3 | 🟡 中 | `songs/models.py` が多責務 (16モデル) | 楽曲+教育+学習が混在 | ドメイン別に分割 |
| D-4 | 🟡 中 | ビジネスロジックがビューに混在 | 特にcore.py, training.py | サービス層を明確化 |
| D-5 | 🟡 中 | AI系テストがない | Gemini/Mureka/LoRAのモックテスト0件 | AI系モックテスト追加 |
| D-6 | 🟢 低 | Django i18n 未使用 | 独自セッションベースi18n | 将来的にDjango i18n移行検討 |
| D-7 | 🟢 低 | フロントエンドがテンプレートベース | vanilla JS + Bootstrap | 将来的にSPA化検討 (不急) |

### 10.2 リファクタリングロードマップ

#### Phase 1: ai_services.py 分割 (D-1) — 優先度最高

```
ai_services.py (2,966行)
  ↓ 分割
songs/services/
  __init__.py          # re-exports
  gemini.py            # GeminiLyricsGenerator, GeminiOCR, GeminiFlashcardExtractor
  mureka.py            # MurekaAIGenerator
  local_llm.py         # LocalLLMLyricsGenerator, CloudLLMLyricsGenerator, OllamaLyricsGenerator
  text_processing.py   # extract_bracketed_terms, hiragana変換, 言語検出
  cache.py             # _get_cache_key, _get_cached_response, _set_cached_response
  pdf_extractor.py     # PDFTextExtractor
```

#### Phase 2: views/core.py 再分割 (D-2)

```
views/core.py (2,140行)
  ↓ 分割
views/
  home.py              # HomeView, SongListView, SongDetailView
  song_crud.py         # CreateSongView, MySongsView, delete_song, update_song_title
  generation.py        # UploadImageView, LyricsConfirmation, generate_lyrics_api, retry
  social.py            # like_song, favorite_song, add_comment, record_play
  utility.py           # set_language, audio_proxy, content_violation_view
```

#### Phase 3: models.py 分割 (D-3)

```
songs/models.py (915行, 16モデル)
  ↓ 分割
songs/models/
  __init__.py          # re-exports
  song.py              # Song, Lyrics, Tag, UploadedImage
  social.py            # Like, Favorite, Comment, PlayHistory
  classroom.py         # Classroom, ClassroomMembership, ClassroomSong
  flashcard.py         # FlashcardDeck, Flashcard
  training.py          # TrainingSession, TrainingData, PromptTemplate
```

#### Phase 4: サービス層の明確化 (D-4)

```
songs/services/
  song_service.py      # 楽曲生成ワークフロー (ビューから移動)
  classroom_service.py # クラス招待・参加ロジック
  flashcard_service.py # カード抽出・学習ロジック
```

#### Phase 5: テスト拡充 (D-5)

| テスト | 対象 | 手法 |
|-------|------|------|
| AI歌詞生成 | GeminiLyricsGenerator | `@patch` でGemini API モック |
| 楽曲生成 | MurekaAIGenerator | `@patch` でMureka API モック |
| OCR | GeminiOCR | モック + サンプル画像 |
| コンテンツフィルター | ContentFilter | 禁止ワード・文脈テスト |
| 決済フロー全体 | Checkout→Webhook | Stripe モック (一部済) |

---

## 11. デプロイアーキテクチャ

```
┌──────────┐     ┌──────────────┐     ┌───────────────┐
│  GitHub   │────▶│  Render.com  │────▶│  PostgreSQL   │
│  (main)   │     │  (Web Svc)   │     │  (Render DB)  │
└──────────┘     └──────┬───────┘     └───────────────┘
                        │
         ┌──────────────┼──────────────────┐
         ▼              ▼                  ▼
  ┌────────────┐ ┌────────────┐  ┌────────────────────┐
  │ Gemini API │ │ Mureka API │  │ Cloudflare R2      │
  │            │ │            │  │ (音声ストレージ)     │
  └────────────┘ └────────────┘  └────────────────────┘

         ┌────────────────────────────┐
         │  自宅 / 学校PC              │
         │  RTX 4060Ti / 4080S ×2     │
         │  LoRA学習 + 推論サーバー     │
         │  ← Cloudflare Tunnel →     │
         └────────────────────────────┘
```

### 11.1 デプロイフロー

```
git push origin main
  → GitHub Actions (なし, Render直接連携)
  → Render: build.sh 実行
  → collectstatic + migrate
  → gunicorn 起動
```

### 11.2 環境変数管理

| 変数 | 用途 | 管理場所 |
|------|------|---------|
| `DATABASE_URL` | PostgreSQL接続 | Render |
| `GEMINI_API_KEY` | Gemini API | Render |
| `MUREKA_API_KEY` | Mureka API | Render |
| `STRIPE_SECRET_KEY` | Stripe決済 | Render |
| `STRIPE_WEBHOOK_SECRET` | Webhook署名検証 | Render |
| `AWS_*` (R2) | Cloudflare R2 | Render |
| `LOCAL_LLM_URL` | LoRA推論サーバー | Render |
| `SECRET_KEY` | Django secret | Render |

---

## 12. テスト戦略

### 12.1 現状 (2026-04-17)

| ファイル | テスト数 | カバー範囲 |
|---------|-------:|-----------|
| `songs/tests.py` | 55 | モデルCRUD, ビュー, フィルター, クラス (11), フラッシュカード (10) |
| `users/tests.py` | 23 | プラン, 制限, BAN, 認証, Stripe Webhook (3) |
| **合計** | **78** | |

### 12.2 テストピラミッド目標

```
        ╱╲          E2E (0件 → 将来 Selenium/Playwright)
       ╱  ╲
      ╱ 統合 ╲       ビュー + DB + テンプレート (現在の主力)
     ╱────────╲
    ╱  ユニット  ╲    モデル, サービス, フィルター (拡充予定)
   ╱──────────────╲
```

---

## 付録A: 命名規則

| 対象 | 規則 | 例 |
|------|------|-----|
| モデル | PascalCase, 単数形 | `Song`, `FlashcardDeck` |
| ビュー (CBV) | PascalCase + View | `CreateSongView`, `HomeView` |
| ビュー (FBV) | snake_case | `like_song`, `audio_proxy` |
| URL名 | snake_case | `songs:song_detail`, `users:login` |
| テンプレート | snake_case.html | `song_detail.html` |
| サービスクラス | PascalCase + 用途 | `GeminiLyricsGenerator` |
| 定数 | UPPER_SNAKE_CASE | `ALLOWED_DOMAINS` |

## 付録B: 技術的負債リスト

| 項目 | 影響 | 見積もり |
|------|------|---------|
| `views/core.py` 2,140行 | 可読性・テスト性低下 | 4h (Phase 2) |
| `ai_services.py` 2,966行 | 変更影響範囲が広い | 6h (Phase 1) |
| 独自i18nシステム | テンプレート肥大化 | 大 (Phase未定) |
| WebSocket未使用 (consumers.py存在) | 死コード | 1h (削除 or 実装) |
| フロントエンドテストなし | UI回帰バグリスク | 中 (Phase未定) |
| CI/CDパイプラインなし | テスト自動化されていない | 3h (GitHub Actions) |

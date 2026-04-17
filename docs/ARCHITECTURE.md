# UTAMEMO アーキテクチャ設計書

> 最終更新: 2026-04-17  
> 詳細設計: [SOFTWARE_DESIGN.md](./SOFTWARE_DESIGN.md) — ドメインモデル・レイヤー構成・リファクタリング計画

## 1. システム概要

UTAMEMO は、ユーザーが教科書やノートの写真から歌詞を生成し、AI で楽曲化する Web アプリケーション。
「暗記ソングで楽しく学ぶ」をコンセプトに、教育×音楽 AI を融合。

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│   ブラウザ    │───▶│  Django App  │───▶│  PostgreSQL  │
│ (Bootstrap5) │◀───│  (Render)    │◀───│  (Render DB) │
└─────────────┘    └──────┬───────┘    └──────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ┌────────────┐  ┌────────────┐  ┌──────────────┐
   │ Gemini API │  │ Mureka API │  │ Cloudflare   │
   │ (歌詞生成/ │  │ (楽曲生成) │  │ R2 (音声     │
   │  OCR/カード)│  │            │  │  ストレージ)  │
   └────────────┘  └────────────┘  └──────────────┘
          ▲
          │
   ┌────────────┐
   │ 自宅/学校PC │
   │ (LoRA学習+  │
   │  推論サーバ) │
   └────────────┘
```

## 2. Django アプリ構成

| アプリ | 役割 |
|--------|------|
| `myproject/` | プロジェクト設定 (settings, urls, middleware, security) |
| `songs/` | メインアプリ — 楽曲・歌詞・タグ・AI生成・フラッシュカード・クラス・スタッフツール |
| `users/` | ユーザー認証・プロフィール・プラン管理・Stripe決済 |

## 3. モデル関係図

```
User (users.User - AbstractUser拡張)
 ├── 1:N ── Song (楽曲)
 │            ├── 1:1 ── Lyrics (歌詞)
 │            ├── N:M ── Tag (タグ)
 │            ├── 1:N ── Like (いいね)      [unique: user+song]
 │            ├── 1:N ── Favorite (お気に入り) [unique: user+song]
 │            ├── 1:N ── Comment (コメント)
 │            ├── 1:N ── PlayHistory (再生履歴) [unique: user+song]
 │            ├── 1:N ── ClassroomSong (クラス共有)
 │            └── N:1 ── UploadedImage (元画像)
 ├── 1:N ── UploadedImage (アップロード画像)
 ├── 1:N ── FlashcardDeck (フラッシュカードデッキ)
 │            └── 1:N ── Flashcard (カード)
 ├── 1:N ── Classroom (クラス - ホスト)
 │            ├── N:M ── User (メンバー, through=ClassroomMembership)
 │            └── 1:N ── ClassroomSong
 └── N:M ── Classroom (参加クラス)

TrainingSession (LLM学習監視 - 独立)
TrainingData (学習データレコード - PostgreSQL永続化)
PromptTemplate (プロンプトテンプレート - 独立)
```

### 主要モデル属性

| モデル | 主要フィールド | インデックス |
|--------|--------------|-------------|
| Song | title, genre, vocal_style, audio_url, generation_status, share_id, likes_count, total_plays | (is_public, -created_at), (generation_status), (created_by, -created_at) |
| Lyrics | content, original_text, lrc_data | — |
| Like | user, song | unique(user, song), (song, created_at) |
| Favorite | user, song | unique(user, song), (user, -created_at) |
| Comment | user, song, content | (song, -created_at) |
| PlayHistory | user, song, play_count | unique(user, song), (user, -last_played_at), (song, -play_count) |
| FlashcardDeck | title, card_count | (user, -updated_at) |
| User | plan, plan_expires_at, is_banned, stripe_customer_id | — |

## 4. URL ルーティング一覧

### 4.1 公開エンドポイント (songs/)

| パス | ビュー | HTTPメソッド | 説明 |
|------|--------|:----------:|------|
| `/` | HomeView | GET | ホームページ |
| `/songs/` | SongListView | GET | 楽曲一覧 (→ホームにリダイレクト) |
| `/songs/<pk>/` | SongDetailView | GET | 楽曲詳細 |
| `/s/<share_id>/` | song_share_redirect | GET | シェアURL短縮リダイレクト |
| `/set-language/<lang>/` | set_language | GET | 言語切替 (ja/en/zh/es/de/pt) |
| `/content-violation/` | content_violation_view | GET | コンテンツ違反ページ |

### 4.2 認証必須エンドポイント (songs/)

| パス | ビュー | HTTPメソッド | 説明 |
|------|--------|:----------:|------|
| `/create/` | CreateSongView | GET/POST | 楽曲作成 |
| `/upload/` | UploadImageView | GET/POST | 画像アップロード (OCR) |
| `/extraction-result/` | TextExtractionResultView | GET | OCR結果確認 |
| `/lyrics-confirmation/` | LyricsConfirmationView | GET/POST | 歌詞確認 |
| `/lyrics-generating/` | LyricsGeneratingView | GET | 歌詞生成待機 |
| `/my-songs/` | MySongsView | GET | マイ楽曲一覧 |
| `/songs/<pk>/like/` | like_song | POST | いいね |
| `/songs/<pk>/favorite/` | favorite_song | POST | お気に入り |
| `/songs/<pk>/delete/` | delete_song | POST | 楽曲削除 |
| `/songs/<pk>/comment/` | add_comment | POST | コメント追加 |
| `/songs/<pk>/play/` | record_play | POST | 再生記録 |
| `/songs/<pk>/toggle-privacy/` | toggle_song_privacy | POST | 公開/非公開切替 |
| `/songs/<pk>/tags/add/` | add_tag_to_song | POST | タグ追加 |
| `/songs/<pk>/tags/remove/` | remove_tag_from_song | POST | タグ削除 |
| `/songs/<pk>/update-title/` | update_song_title | POST | タイトル変更 |
| `/songs/<pk>/retry/` | retry_song_generation | POST | 楽曲再生成 |
| `/songs/<pk>/generating/` | song_generating | GET | 生成中画面 |
| `/songs/<pk>/status/` | check_song_status | GET | 生成ステータス確認 (JSON) |
| `/songs/<pk>/recreate/` | recreate_with_lyrics | POST | 歌詞変更して再生成 |
| `/songs/<pk>/audio-proxy/` | audio_proxy | GET | 音声プロキシ (CORS対策) |

### 4.3 API エンドポイント

| パス | ビュー | 説明 |
|------|--------|------|
| `/api/generate-lyrics/` | generate_lyrics_api | 歌詞生成 (非同期) |
| `/api/llm/health/` | test_llm_health | LLM ヘルスチェック |
| `/api/llm/generate/` | test_llm_generate | LLM テスト生成 |
| `/api/mureka/test-submit/` | test_mureka_submit | Mureka テスト投稿 |
| `/api/mureka/test-poll/` | test_mureka_poll | Mureka ポーリング |
| `/api/training/update/` | training_api_update | 学習状態更新 (エージェント→サーバー) |
| `/api/training/reviewed/` | training_reviewed_indices | レビュー済みデータ取得/更新 |
| `/api/training/data/download/` | training_data_download | 学習データDL |
| `/api/training/data/upload/` | training_data_upload | 学習データUP |
| `/api/training/status/` | training_api_status_json | 学習ステータスJSON |
| `/api/training/command/` | training_send_command | 学習コマンド送信 |
| `/api/training/data/` | training_data_api | 学習データCRUD |
| `/api/training/data/generate/` | training_data_generate | 学習データ自動生成 |
| `/api/training/prompt/` | training_prompt_api | プロンプトテンプレート |

### 4.4 スタッフ専用 (@staff_member_required)

| パス | ビュー | 説明 |
|------|--------|------|
| `/staff/llm-guide/` | llm_guide | ハブページ (全ツールナビ) |
| `/staff/api-status/` | api_status_view | API ステータス確認 |
| `/staff/mureka-debug/` | mureka_api_debug | Mureka API デバッグ |
| `/staff/quality-check/` | quality_check | 楽曲品質チェック |
| `/staff/training/` | training_dashboard | LLM学習ダッシュボード |
| `/staff/training-data/` | training_data_viewer | 学習データ確認・検索 |
| `/staff/test-llm/` | test_llm_page | LLM テストページ |
| `/staff/test-mureka/` | test_mureka_page | Mureka テストページ |
| `/staff/monitor/` | staff_monitor | サーバー監視 (superuser) |

### 4.5 ユーザー (users/)

| パス | ビュー | 説明 |
|------|--------|------|
| `/users/register/` | RegisterView | ユーザー登録 |
| `/users/login/` | LoginView | ログイン |
| `/users/logout/` | LogoutView | ログアウト |
| `/users/favorites/` | FavoritesView | お気に入り一覧 |
| `/users/profile/edit/` | ProfileEditView | プロフィール編集 |
| `/users/profile/delete-account/` | delete_account | アカウント削除 |
| `/users/profile/update-image/` | update_profile_image | プロフ画像更新 |
| `/users/profile/delete-image/` | delete_profile_image | プロフ画像削除 |
| `/users/upgrade/` | UpgradeView | プランアップグレード |
| `/users/upgrade/checkout/` | create_checkout_session | Stripe Checkout |
| `/users/upgrade/success/` | upgrade_success | 決済成功 |
| `/users/upgrade/parental-consent/` | record_parental_consent | 保護者同意 |
| `/users/webhook/stripe/` | stripe_webhook | Stripe Webhook |
| `/users/school-inquiry/` | SchoolInquiryView | 学校問い合わせ |
| `/users/profile/<username>/` | ProfileView | 公開プロフィール |
| `/users/password-reset/` | CustomPasswordResetView | パスワードリセット |

### 4.6 その他 (myproject/urls.py)

| パス | 説明 |
|------|------|
| `/admin/` | Django Admin |
| `/admin/2fa/` | Admin 2FA認証 |
| `/robots.txt` | robots.txt |
| `/sitemap.xml` | サイトマップ |
| `/terms/` | 利用規約 |
| `/privacy/` | プライバシーポリシー |
| `/contact/` | お問い合わせ |
| `/tokushoho/` | 特定商取引法 |
| `/classroom/` | クラス一覧・参加・作成・詳細 |
| `/flashcards/` | フラッシュカード一覧・学習 |

## 5. 外部サービス連携

| サービス | 用途 | 認証 |
|---------|------|------|
| **Google Gemini API** | 歌詞生成、OCR、フラッシュカード抽出、ひらがな変換 | API Key (env) |
| **Mureka API** | 楽曲生成 (音声) | API Key (env) |
| **Stripe** | サブスクリプション決済 (Starter/Pro) | Secret Key + Webhook署名 |
| **Cloudflare R2** | 音声ファイルストレージ | S3互換キー (env) |
| **自作LoRA推論サーバー** | 歌詞生成 (ローカルLLM) | API Key + Cloudflare Tunnel |

## 6. プラン体系

| プラン | 月間生成数 | モデル | 価格 |
|--------|----------|-------|------|
| free | 制限あり | V8のみ | ¥0 |
| starter | 制限あり (多め) | V8 | 月額課金 |
| pro | 無制限 | 全モデル | 月額課金 |
| school | カスタム | カスタム | 学校契約 |
| staff/superuser | 無制限 | 全モデル | — |

## 7. セキュリティ対策

- **認証**: Django AbstractUser + セッション認証
- **CSRF**: Django 標準 CSRF ミドルウェア
- **Admin 2FA**: TOTP ベースの 2 段階認証
- **コンテンツフィルター**: 禁止ワード + 文脈判定 (`content_filter.py`)
- **SSRF 防止**: audio_proxy のドメインホワイトリスト (mureka.io, r2.cloudflarestorage.com)
- **Stripe Webhook**: 署名検証
- **BAN 機能**: is_banned フラグ + middleware でブロック
- **年齢確認**: birth_date + 保護者同意フロー (未成年課金対策)

## 8. AI サービスクラス構成 (ai_services.py)

| クラス/関数 | 役割 |
|------------|------|
| `GeminiLyricsGenerator` | Gemini API で歌詞生成 (メイン) |
| `LocalLLMLyricsGenerator` | 自作LoRA推論サーバーで歌詞生成 |
| `CloudLLMLyricsGenerator` | クラウドLLMで歌詞生成 |
| `OllamaLyricsGenerator` | Ollama経由の歌詞生成 |
| `MurekaAIGenerator` | Mureka API で楽曲生成 |
| `GeminiOCR` | Gemini Vision で画像テキスト抽出 |
| `PDFTextExtractor` | PyMuPDF で PDF テキスト抽出 |
| `GeminiFlashcardExtractor` | テキスト→フラッシュカード抽出 |
| `convert_lyrics_to_hiragana_with_context()` | Gemini でひらがな変換 |
| `detect_lyrics_language()` | 歌詞の言語自動判定 |
| `ContentFilter` | 不適切コンテンツ検出 (content_filter.py) |

## 9. ローカル LLM 学習システム (training/)

### 概要
- **ベースモデル**: Qwen2.5-14B-Instruct
- **手法**: QLoRA (rank=64, 3 epoch)
- **ハードウェア**: 自宅 RTX 4060 Ti 16GB / 学校 RTX 4080 SUPER ×2

### コンポーネント

| ファイル | 役割 |
|---------|------|
| `train.py` | LoRA 学習スクリプト |
| `serve.py` | 推論サーバー (FastAPI) |
| `training_agent.py` | Web ダッシュボード連携エージェント |
| `generate_history_data.py` | Gemini で学習データ自動生成 |
| `quality_check.py` | 学習データ品質チェック |
| `validate_data.py` | データ検証 |

### データフロー
```
Gemini API → 学習データ生成 → スタッフ手動レビュー → LoRA学習 → 推論サーバー
                                   ↑                      ↓
                            Webダッシュボード ←── Cloudflare Tunnel
```

## 10. テスト

| ファイル | テスト数 | カバー範囲 |
|---------|---------|-----------|
| `songs/tests.py` | 55件 | モデル CRUD、ビューGET/POST、コンテンツフィルター、言語切替、再生記録、音声プロキシ、クラス(11)、フラッシュカード(10) |
| `users/tests.py` | 23件 | プラン判定、有効期限、制限、BAN、登録、ログイン、Stripe Webhook(3) |

### 未カバー (今後の課題)
- AI サービス系 (Gemini/Mureka/LoRA) のモックテスト
- 負荷テスト / パフォーマンステスト
- フロントエンド E2E テスト

> 詳細なテスト戦略・リファクタリング計画は [SOFTWARE_DESIGN.md](./SOFTWARE_DESIGN.md) §10, §12 を参照

## 11. 多言語対応

セッションベースの独自 i18n (`app_language`)。Django i18n は未使用。

- 対応言語: `ja`, `en`, `zh`, `es`, `de`, `pt`
- テンプレート内分岐: `{% if app_language == 'en' %}`
- context_processor でテンプレートに `app_language` を注入

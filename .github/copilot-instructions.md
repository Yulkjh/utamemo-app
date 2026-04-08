# Copilot Instructions - utamemo-app

## プロジェクト概要
AI楽曲生成Webアプリケーション (Django 5.x)。ユーザーが歌詞を入力またはAI生成し、Mureka APIで楽曲を生成する。

## 技術スタック
- **バックエンド**: Django 5.x / Python 3.12+
- **データベース**: PostgreSQL (本番) / SQLite (開発)
- **フロントエンド**: Bootstrap 5.3 + vanilla JavaScript
- **AI**: Google Gemini API (歌詞生成/OCR) + Mureka API (楽曲生成)
- **決済**: Stripe (サブスクリプション)
- **デプロイ**: Render.com
- **ストレージ**: Cloudflare R2

## プロジェクト構成
```
myproject/
  myproject/    # Djangoプロジェクト設定
  songs/        # メインアプリ (曲・歌詞・タグ・AI生成)
  users/        # ユーザーアプリ (認証・プラン・課金)
  templates/    # HTMLテンプレート
  static/       # 静的ファイル
```

## コーディング規約

### Python / Django
- print() は使わず logging モジュールを使う
- ビューのHTTPメソッド制限: `@require_POST`, `@require_http_methods` を適切に使う
- 競合状態の防止: カウンター更新には `F()` 式を使う
- データ整合性: 複数のDB操作には `transaction.atomic()` を使う
- 秘密情報はハードコードせず `os.getenv()` + `settings.py` で管理
- セキュリティ: SSRF対策としてURL/ドメインのホワイトリスト検証を行う

### テンプレート
- URLはハードコードせず `{% url %}` テンプレートタグを使う
- テーマカラー: オレンジグラデーション (#ff7940)
- フォント: Inter (Google Fonts)

### テスト
- テストは `songs/tests.py` と `users/tests.py` に記述
- テスト実行: `python manage.py test --verbosity=2`
- モデルテスト、ビューテスト、ユニットテストを網羅

## 多言語対応
- Django i18n ではなくセッションベースの独自i18n (`app_language`)
- 対応言語: ja, en, zh, es, de, pt
- テンプレート内で `{% if app_language == 'en' %}` のように分岐

## プラン体系
- **free**: 月間生成制限あり、基本モデルのみ
- **starter**: 月間生成制限あり (freeより多い)、追加モデル利用可
- **pro**: 無制限、全モデル利用可
- **staff/superuser**: 常にPro扱い

## 重要なモデル
- `Song`: 楽曲 (タイトル, ジャンル, audio_url, generation_status, likes_count, total_plays)
- `Lyrics`: 歌詞 (content, original_text, language)
- `Tag`: タグ (ユニーク制約)
- `Like` / `Favorite`: いいね・お気に入り (ユーザー+曲のユニーク制約)
- `User`: カスタムユーザー (plan, plan_expires_at, is_banned, stripe_customer_id)
- `FlashcardDeck` / `Flashcard`: 学習カード機能

## セキュリティ注意事項
- `content_filter.py`: 不適切コンテンツフィルター (禁止ワード + 文脈判定)
- `encryption.py`: 将来の暗号化機能用 (現在プレースホルダー)
- audio_proxy: ドメインホワイトリスト (mureka.io, r2.cloudflarestorage.com)
- Stripe Webhook: 署名検証必須

## Admin カスタマイズ
- `songs/admin.py`: 全モデルにカスタムAdmin (list_per_page, date_hierarchy, raw_id_fields, admin actions)
- `users/admin.py`: ユーザー管理 (プラン情報, BAN管理, 曲数表示, reset_to_free_plan アクション)

## スタッフポータル
- `/staff/llm-guide/` - ハブページ (全管理ツールのナビ + LLMガイド)
- `/staff/api-status/` - API ステータス確認
- `/staff/mureka-debug/` - Mureka API デバッグ
- `/staff/quality-check/` - 楽曲品質チェック
- `/staff/training/` - LLM学習ダッシュボード (リモート制御)
- `/staff/training-data/` - 学習データ確認・検索
- すべて `@staff_member_required` デコレータ付き

## ローカルLLM学習システム (training/)
- **2つのLLM開発中**:
  - LLM-1: ノート重要度スコアリング (OCRテキスト → 重要ワードスコア付け)
  - LLM-2: 歌詞生成 (教育内容 → エグスプロージョン「本能寺の変」スタイル暗記歌詞)
- **ベースモデル**: Qwen2.5-7B-Instruct (QLoRA)
- **学習データ**: `training/data/lyrics_training_data.json` (79件、9教科)
- **データ生成**: `training/generate_history_data.py` で Gemini API から自動生成
- **学習エージェント**: `training/training_agent.py` がWebダッシュボードと連携して学習を自動制御
- **推論サーバー**: `training/serve.py` + Cloudflare Tunnel で本番接続
- **ハードウェア**: 自宅 RTX 4060 Ti 16GB / 学校 RTX 4080 x2

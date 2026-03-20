# UTAMEMO 共同開発ガイド

このドキュメントは UTAMEMO の共同開発に参加する方向けのセットアップ手順とルールです。

---

## 🚀 開発環境のセットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/Yulkjh/utamemo-app.git
cd utamemo-app
```

### 2. Python 環境を構築

```bash
cd myproject

# 仮想環境を作成（Python 3.11+ 推奨）
python3 -m venv venv

# 有効化
# macOS / Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# パッケージインストール
pip install -r ../requirements.txt
```

### 3. 環境変数を設定

```bash
# テンプレートをコピー
cp .env.example .env
```

`.env` を開いて、最低限以下を設定してください:

```bash
# 開発用の最低限設定
DEBUG=True
SECRET_KEY=django-insecure-dev-only-key-do-not-use-in-production
ALLOWED_HOSTS=localhost,127.0.0.1

# AI 機能を使う場合（任意）
GEMINI_API_KEY=your-gemini-api-key      # Google AI Studio で取得
MUREKA_API_KEY=your-mureka-api-key      # Mureka Platform で取得

# Stripe 決済をテストする場合（任意）
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
```

> **⚠️ `.env` には秘密情報が入るので、絶対に Git にコミットしないでください。**  
> `.gitignore` で除外済みですが念のため注意。

### 4. データベースを初期化

```bash
# マイグレーション実行（SQLite が自動生成される）
python manage.py migrate

# 管理者アカウント作成（任意）
python manage.py createsuperuser
```

### 5. 開発サーバーを起動

```bash
python manage.py runserver
# → http://127.0.0.1:8000 でアクセス
```

---

## 🌿 ブランチ運用ルール

### ブランチの作り方

```
main                 ← 本番（直接プッシュ禁止）
├── feature/xxx      ← 新機能
├── fix/xxx          ← バグ修正
├── docs/xxx         ← ドキュメント修正
└── refactor/xxx     ← リファクタリング
```

### 作業の流れ

```bash
# 1. main を最新に更新
git checkout main
git pull origin main

# 2. 作業ブランチを作成
git checkout -b feature/your-feature-name

# 3. コーディング & コミット
git add .
git commit -m "feat: 〇〇機能を追加"

# 4. リモートにプッシュ
git push origin feature/your-feature-name

# 5. GitHub で Pull Request を作成
#    → レビュー後に main にマージ
```

### コミットメッセージの書き方

日本語・英語どちらでもOKですが、プレフィックスを付けてください:

| プレフィックス | 用途 | 例 |
|---------------|------|-----|
| `feat:` | 新機能 | `feat: 暗記カードのフィルタ機能追加` |
| `fix:` | バグ修正 | `fix: ログイン時のリダイレクトエラーを修正` |
| `docs:` | ドキュメント | `docs: README にセットアップ手順追加` |
| `style:` | UI / CSS | `style: ソングカードのレスポンシブ対応` |
| `refactor:` | リファクタリング | `refactor: views.py の重複コードを統合` |
| `test:` | テスト | `test: Song モデルのユニットテスト追加` |
| `chore:` | その他 | `chore: requirements.txt 更新` |

---

## 📁 プロジェクト構成の概要

```
myproject/
├── myproject/          # Django プロジェクト設定
│   ├── settings.py     # 全体設定（環境変数・DB・AI設定）
│   ├── urls.py         # URL ルーティング
│   └── ...
├── songs/              # メインアプリ（楽曲・歌詞・タグ・AI生成）
│   ├── models.py       # Song, Lyrics, Tag, Classroom, FlashcardDeck
│   ├── views.py        # ビュー（画面表示・API処理）
│   ├── ai_services.py  # AI統合（Gemini / Cloud LLM / Local LLM / Mureka）
│   ├── forms.py        # フォーム
│   ├── urls.py         # songs アプリの URL
│   └── tests.py        # テスト
├── users/              # ユーザー管理アプリ（認証・プラン・課金）
│   ├── models.py       # User（カスタム）
│   ├── views.py        # 認証・プロフィール
│   └── tests.py        # テスト
├── templates/          # HTML テンプレート
├── static/             # CSS / JS / 画像
└── manage.py
```

---

## 📝 コーディング規約

### Python / Django

- **`print()` は使わない** → `logging` モジュールを使う
  ```python
  import logging
  logger = logging.getLogger(__name__)
  logger.info("楽曲生成開始: song_id=%s", song.id)
  ```
- **ビューの HTTP メソッド制限**: `@require_POST`, `@require_http_methods` を適切に使う
- **競合状態の防止**: カウンター更新には `F()` 式を使う
  ```python
  Song.objects.filter(pk=song.pk).update(total_plays=F('total_plays') + 1)
  ```
- **データ整合性**: 複数の DB 操作には `transaction.atomic()` を使う
- **秘密情報**: ハードコードせず `os.getenv()` + `settings.py` で管理

### テンプレート

- URL は `{% url 'name' %}` テンプレートタグを使う（ハードコード禁止）
- テーマカラー: オレンジグラデーション (#ff7940)
- フォント: Inter (Google Fonts)

### テスト

```bash
# テスト実行
python manage.py test --verbosity=2

# 特定のアプリだけ
python manage.py test songs --verbosity=2
python manage.py test users --verbosity=2
```

---

## 🌐 多言語対応のルール

Django の i18n ではなく、セッションベースの独自 i18n (`app_language`) を使用しています。

テンプレートでの分岐例:
```html
{% if app_language == 'en' %}
  <h1>My Songs</h1>
{% elif app_language == 'ja' %}
  <h1>マイソング</h1>
{% endif %}
```

対応言語: `ja`, `en`, `zh`, `es`, `de`, `pt`

---

## ⚠️ 注意事項

### やってはいけないこと

- ❌ **`.env` をコミットする**（秘密情報漏洩）
- ❌ **`main` に直接プッシュ**（Pull Request を使う）
- ❌ **他人の作業ブランチを勝手にリベース**
- ❌ **`db.sqlite3` をコミットする**（各自のローカルDB）
- ❌ **API キーをコードにハードコード**

### 困ったら

- マイグレーションエラー → `python manage.py migrate --run-syncdb`
- パッケージ不足 → `pip install -r ../requirements.txt`
- `.env` の設定漏れ → `.env.example` と比較

---

## 🔗 関連ドキュメント

- [README.md](README.md) — プロジェクト全体の説明
- [training/README.md](training/README.md) — ローカル LLM 学習・推論サーバー
- [DOMAIN_SETUP.md](DOMAIN_SETUP.md) — ドメイン・DNS 設定

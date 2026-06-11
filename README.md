# UTAMEMO — AI-Powered Educational Music Platform

> **Learn textbooks through AI-generated songs and flashcards.**

[![Django](https://img.shields.io/badge/Django-4.2+-green)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Deploy](https://img.shields.io/badge/deploy-Render.com-orange)](https://render.com/)

---

## Overview

UTAMEMO is an AI-powered educational music application that transforms textbooks and study materials into engaging musical learning experiences. Take photos of your textbook pages, and our AI will generate original songs with lyrics to help you memorize the content.

### Key Features

| Feature | Description |
|---------|-------------|
| Photo to Song | Upload textbook/notes photos, AI extracts text, generates original songs |
| Multi-Model AI | Supports Local LLM (LoRA), Cloud LLM, and Google Gemini for lyrics generation |
| Music Generation | Mureka API for high-quality AI music production |
| Flashcard System | Auto-generate flashcards from song content for spaced repetition learning |
| Classroom Feature | Teachers can create classes, share songs, and manage student progress |
| Subscription Plans | Free, Starter ($400/mo), Pro ($2,000/mo), School (custom pricing) via Stripe |
| Enterprise Security | Fernet encryption, HTTPS, Admin 2FA, Content filtering, BAN management |
| 6 Languages | Japanese, English, Chinese, Spanish, German, Portuguese |

---

## Architecture

```
+----------+     +--------------+     +---------------+
|  GitHub   |---->|  Render.com  |---->|  PostgreSQL   |
|  (main)   |     |  (Web Svc)   |     |  (Render DB)  |
+----------+     +------+-------+     +---------------+
                       |
         +-------------+---------------+
         v                             v
   +------------+             +--------------------+
   | Gemini API | | Mureka API |  | Cloudflare R2    |
   |            | |            |  | (Audio Storage)  |
   +------------+ +------------+ +--------------------+

         +-------------------------------+
         |  Home / School PC              |
         |  RTX 4060Ti / 4080S x2        |
         |  LoRA Training Server          |
         |  <-- Cloudflare Tunnel -->     |
         +-------------------------------+
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Django 4.2 + Python 3.11+ |
| **Frontend** | Bootstrap 5 + vanilla JS |
| **Database** | PostgreSQL (production) / SQLite (development) |
| **Storage** | Cloudflare R2 (audio files) |
| **AI Services** | Google Gemini, Mureka API, Local LoRA models |
| **Payments** | Stripe Checkout + Webhooks |
| **Deployment** | Render.com + gunicorn |

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Git
- (Optional) API keys for Gemini, Mureka, Stripe

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Yulkjh/utamemo-app.git
cd utamemo-app

# 2. Set up Python virtual environment
cd myproject
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r ../requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your API keys and settings

# 5. Initialize database
python manage.py migrate

# 6. Create admin user (optional)
python manage.py createsuperuser

# 7. Start development server
python manage.py runserver
# Visit http://127.0.0.1:8000
```

### Environment Variables

See `.env.example` for all available options. Minimum required:

```bash
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# AI Services (optional)
GEMINI_API_KEY=your-gemini-key
MUREKA_API_KEY=your-mureka-key

# Stripe (optional for payments)
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

---

## Project Structure

```
utamemo-app/
├── myproject/
│   ├── myproject/              # Django project settings
│   │   ├── settings.py         # Configuration (DB, AI, security)
│   │   ├── urls.py             # Root URL routing
│   │   ├── legal_views.py      # Privacy/Terms/Contact pages
│   │   ├── security_views.py   # Admin 2FA authentication
│   │   └── queue_manager.py    # Background task queue
│   ├── songs/                  # Main app (songs, lyrics, AI)
│   │   ├── models.py           # Song, Lyrics, Tag, Classroom, FlashcardDeck
│   │   ├── views.py            # All view functions
│   │   ├── ai_services.py      # AI integration (Gemini/Mureka/LocalLLM)
│   │   ├── content_filter.py   # Inappropriate content detection
│   │   ├── forms.py            # Django forms
│   │   ├── services/           # Service layer (in progress)
│   │   ├── templatetags/       # Custom template filters
│   │   ├── migrations/         # Database migrations (42 files)
│   │   └── tests.py            # 55 tests
│   ├── users/                  # User management app
│   │   ├── models.py           # Custom User, Plan, BAN management
│   │   ├── views.py            # Auth, Profile, Stripe payments
│   │   ├── forms.py            # Registration/Edit forms
│   │   ├── middleware.py       # BAN check, language preference
│   │   └── tests.py            # 23 tests
│   ├── templates/              # HTML templates
│   │   ├── base.html           # Base template with Bootstrap 5
│   │   ├── songs/              # Song-related templates (16 files)
│   │   ├── users/              # User-related templates
│   │   ├── admin/              # Admin templates (2FA, monitoring)
│   │   └── legal/              # Privacy, Terms, Contact
│   ├── static/                 # CSS, JS, images
│   └── manage.py
├── training/                   # Local LLM training server
│   ├── train.py                # LoRA training script
│   ├── training_agent.py       # Automated training pipeline
│   ├── serve.py                # Gradio WebUI server
│   ├── requirements_training.txt
│   └── README.md
├── docs/                       # Design documents
│   ├── SOFTWARE_DESIGN.md      # Detailed software design (Japanese)
│   ├── ARCHITECTURE.md         # System configuration & routing
│   └── meeting_pitch_kokuyo_data.md
├── requirements.txt            # Production dependencies
├── render.yaml                 # Render.com deployment config
├── build.sh                    # Render build script
└── CONTRIBUTING.md             # Contributor guide (Japanese)
```

---

## Core Workflows

### 1. Song Generation Pipeline

```
User uploads photo
       |
       v
Gemini OCR extracts text from image
       |
       v
ContentFilter validates content
       |
       v
AI generates lyrics (LocalLLM -> CloudLLM -> Gemini fallback chain)
       |
       v
User confirms lyrics
       |
       v
Mureka API generates music (async)
       |
       v
Audio stored in Cloudflare R2
       |
       v
Song completed
```

### 2. Subscription Flow

```
User clicks upgrade
       |
       v
Age verification (if under 18 -> guardian consent required)
       |
       v
Stripe Checkout session created
       |
       v
Payment completed
       |
       v
Stripe webhook validates signature
       |
       v
User plan updated (starter/pro/school)
```

### 3. Classroom Feature (School Users Only)

```
Teacher creates class -> gets unique join code
       |
       v
Shares code with students
       |
       v
Students join with code (requires school plan)
       |
       v
Teacher shares songs with the class
       |
       v
Auto-generated flashcards for studying
```

---

## Security Features

| Threat | Countermeasure | Implementation |
|--------|---------------|----------------|
| Invalid input | ContentFilter (blocked words + context-based) | `content_filter.py` |
| SSRF | Domain whitelist for audio proxy | `views.py:audio_proxy()` |
| CSRF | Django CSRF middleware | `settings.py` |
| Privilege escalation | `@login_required`, ownership checks | Each view |
| Admin access | TOTP 2FA | `security.py` |
| BAN bypass | BanMiddleware (all requests) | `users/middleware.py` |
| Payment forgery | Stripe signature verification | `users/views.py` |
| Minor payments | Birth date + guardian consent flow | `users/views.py` |
| Secret leakage | Environment variables only | `.env` (gitignored) |

### Encryption

All user songs are encrypted with Fernet symmetric encryption:
- AES-128-CBC cipher mode
- 256-bit derived key from Django SECRET_KEY + per-song salt
- HMAC authentication for integrity verification

---

## Subscription Plans

| Plan | Price | Generation Limit | V8 Model | All Models | Classroom |
|------|-------|------------------|----------|------------|-----------|
| **Free** | ¥0 | Limited | No | No | No |
| **Starter** | ¥400/mo | Limited | Yes | No | No |
| **Pro** | ¥2,000/mo | Unlimited | Yes | Yes | No |
| **School** | Custom | Custom | Yes | Yes | Yes |
| **Staff** | Free (invited) | Unlimited | Yes | Yes | Yes |

> Staff/Superuser accounts get all features automatically regardless of plan.

---

## Testing

```bash
# Run all tests
python manage.py test --verbosity=2

# Run specific app tests
python manage.py test songs --verbosity=2
python manage.py test users --verbosity=2
```

**Current test coverage:** 78 tests (55 for songs + 23 for users)

---

## Multi-Language Support

UTAMEMO uses session-based language switching (not Django i18n):

Supported languages: `ja` (Japanese), `en` (English), `zh` (Chinese), `es` (Spanish), `de` (German), `pt` (Portuguese)

Template branching example:
```html
{% if app_language == 'en' %}
  <h1>My Songs</h1>
{% elif app_language == 'ja' %}
  <h1>マイソング</h1>
{% endif %}
```

---

## Branching Strategy

```
main                 <- Production (direct push prohibited)
├── feature/xxx      <- New features
├── fix/xxx          <- Bug fixes
├── docs/xxx         <- Documentation updates
└── refactor/xxx     <- Refactoring
```

### Commit Message Convention

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat:` | New feature | `feat: フラッシュカードのフィルタ機能追加` |
| `fix:` | Bug fix | `fix: ログイン時のリダイレクトエラーを修正` |
| `docs:` | Documentation | `docs: README にセットアップ手順追加` |
| `style:` | UI/CSS | `style: ソングカードのレスポンシブ対応` |
| `refactor:` | Refactoring | `refactor: views.py の重複コードを統合` |
| `test:` | Tests | `test: Song モデルのユニットテスト追加` |
| `chore:` | Other | `chore: requirements.txt 更新` |

---

## Development Tasks & Technical Debt

### Priority Refactoring Plan

| ID | Priority | Task | Current Lines | Status |
|----|----------|------|---------------|--------|
| D-1 | High | Split `ai_services.py` (2,966 lines) | 1 file -> 7 modules | Planned Phase 1 |
| D-2 | High | Split `views/core.py` (2,140 lines) | 1 file -> 5 modules | Planned Phase 2 |
| D-3 | Medium | Split `songs/models.py` (16 models) | 1 file -> 5 modules | Planned Phase 3 |
| D-4 | Medium | Clarify service layer | Business logic in views | Planned Phase 4 |
| D-5 | Medium | Add AI tests | 0 AI mock tests | Planned Phase 5 |
| D-6 | Low | Migrate to Django i18n | Session-based i18n | Future |
| D-7 | Low | Frontend test coverage | No frontend tests | Future |

---

## Admin & Staff Features

### Admin Tools
- **2FA Authentication**: TOTP-based two-factor authentication for admin access
- **Monitoring Dashboard**: Real-time system monitoring
- **Content Moderation**: View and manage user reports
- **BAN Management**: Ban/unban users

### Training Dashboard (Staff Only)
- **LLM Training Status**: Monitor LoRA training sessions
- **Data Review**: Approve/reject training data samples
- **Prompt Template Editor**: Manage prompt templates for lyrics generation

---

## API Endpoints (Internal)

| URL Pattern | View | Authentication | Description |
|-------------|------|----------------|-------------|
| `/songs/create/` | CreateSongView | Login required | Song creation page |
| `/songs/generate/` | UploadImageView | Login required | Upload textbook photo |
| `/songs/lyrics/generate/` (API) | generate_lyrics_api | Login required | Generate lyrics via AI |
| `/songs/<id>/` | SongDetailView | Public | Song detail page |
| `/songs/my/` | MySongsView | Login required | User's song list |
| `/songs/classroom/` | ClassroomListView | School plan | Classroom management |
| `/songs/flashcard/` | FlashcardDeckListView | Login required | Flashcard decks |
| `/songs/theater/` | TheaterView | Login required | AI theater (V8 model) |
| `/accounts/register/` | RegistrationView | Anonymous only | User registration |
| `/accounts/upgrade/` | upgrade_plan | Login required | Subscription upgrade |
| `/api/stripe/create-session/` | create_checkout_session | Login required | Create Stripe session |
| `/stripe/webhook/` | stripe_webhook | Webhook secret | Stripe webhook handler |

---

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributor guide (Japanese)
- [docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md) — Detailed software design (Japanese)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System configuration & routing (Japanese)
- [DOMAIN_SETUP.md](DOMAIN_SETUP.md) — Domain/DNS setup guide (Japanese)
- [training/README.md](training/README.md) — Local LLM training server guide

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and development rules.

### Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Commit with conventional commit messages
5. Push and create a Pull Request

---

## License

This project is licensed under the MIT License.

---

## Acknowledgments

- **Django** — The web framework for perfectionists with deadlines
- **Bootstrap 5** — Frontend framework
- **Google Gemini** — OCR and lyrics generation API
- **Mureka** — AI music generation API
- **Stripe** — Payment processing
- **Cloudflare R2** — Object storage for audio files

---

Built by the UTAMEMO Team
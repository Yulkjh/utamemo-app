# UTAMEMO — AI-Powered Educational Music Platform

> **Learn textbooks through AI-generated songs and flashcards.**

[![Django](https://img.shields.io/badge/Django-5.2-green)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![Deploy](https://img.shields.io/badge/deploy-Render.com-orange)](https://render.com/)

---

## Overview

UTAMEMO is an AI-powered educational music application that turns textbooks and study notes into songs. Users photograph (or upload a PDF of) their study material, an OCR/vision pipeline extracts the text, an LLM turns it into lyrics, and an AI music-generation API renders those lyrics as a full song with vocals. Songs can then be converted into flashcard decks for spaced-repetition style review, shared into classrooms by teachers, and played back with an optional auto-generated karaoke (instrumental-only) track.

The repository is a single Django monorepo containing:

- **`myproject/`** — the production Django web application (the product itself)
- **`training/`** — a self-hosted LoRA/QLoRA fine-tuning + inference pipeline that runs on the team's own GPUs at home/school, used as an optional lower-cost alternative to cloud LLMs for lyrics generation
- **`docs/`** — Japanese-language architecture and software-design documentation
- **`UtaMemo/`** — an early, separate SwiftUI iOS app prototype (its own Xcode project and git repo, not integrated with the Django backend)

### Key Features

| Feature | Description |
|---------|-------------|
| Photo/PDF → Song | Upload a textbook photo or PDF; Gemini OCR (or PyMuPDF for PDFs) extracts the text |
| Multi-Backend Lyrics AI | Pluggable lyrics generation: Google Gemini, a self-hosted Local LLM, any OpenAI-compatible Cloud LLM (Together AI / Fireworks / Groq / OpenRouter / vLLM), or Ollama — selectable per-deployment via `LYRICS_BACKEND`, with an `auto` mode that fails over Cloud → Ollama → Local → Gemini |
| Music Generation | Mureka API renders lyrics into full vocal songs; supports the V9 (default) and V8 model tiers, dozens of vocal-style presets (female/male/vocaloid/duet/choir/whisper/child, each with sub-variants), and genre/reference-song prompting |
| Karaoke Track | Automatic instrumental-only track extraction (Demucs-based source separation) for sing-along playback |
| Flashcard System | Auto-generate term/definition flashcards from song lyrics or source images via Gemini, with importance tagging and a 4-level mastery tracker for spaced repetition |
| Classroom Feature | Teachers create classes with a join code, share songs into the class, and assign songs as homework with due dates |
| Subscription Plans | Free / Starter (¥780/mo) / Pro (¥1,900/mo) / School (¥450 per student/mo) via Stripe Checkout + webhooks, with monthly generation-count limits per plan |
| Content Moderation | Rule-based bilingual (JA/EN) content filter with academic/lyrical-context allowlisting to avoid false positives on legitimate historical or poetic vocabulary |
| Trust & Safety | Admin TOTP 2FA, IP-restricted admin access, BAN system with forced logout, age verification + guardian-consent gating for payments by minors |
| Self-Hosted LLM Training | A full LoRA/QLoRA fine-tuning pipeline (train/serve/monitor) that runs on team-owned GPUs and plugs into the same lyrics-generation interface as the cloud backends |
| 6+ Languages | Japanese, English, Chinese, Spanish, German, Portuguese, Dutch — via a custom session-based (non-Django-i18n) language switcher |
| "UNITE CINEMA MINATO" | A separate, unrelated movie-theater seat-reservation micro-feature (booking + survey) bolted onto the same Django project |

---

## Architecture

```
+-----------+     +--------------+     +---------------+
|  GitHub   |---->|  Render.com  |---->|  PostgreSQL   |
|  (main)   |     |  (Web Svc)   |     |  (Render DB)  |
+-----------+     +------+-------+     +---------------+
                         |
        +----------------+-----------------+
        v                v                 v
  +------------+  +------------+   +--------------------+
  | Gemini API |  | Mureka API |   |  Cloudflare R2      |
  | (OCR/LLM)  |  | (V8 / V9)  |   |  (Audio Storage)    |
  +------------+  +------------+   +--------------------+
        |
        v  (optional, LYRICS_BACKEND=local/cloud/auto)
+-------------------------------------------+
|  Home / School GPU Server                  |
|  RTX 4060 Ti (home) / RTX 4080 SUPER x2   |
|  (school) — LoRA training + Flask/Gradio  |
|  inference server <-- Cloudflare Tunnel --|
+-------------------------------------------+
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Django 5.2 + Python 3.11+, Django Channels/Daphne (ASGI, WebSocket progress updates) |
| **Frontend** | Bootstrap 5 + vanilla JS, server-rendered templates |
| **Database** | PostgreSQL (production, via `dj-database-url`) / SQLite (development) |
| **Cache / Channel layer** | Redis in production (`channels-redis`, cache, sessions), in-memory locally |
| **Storage** | Cloudflare R2 (audio files), WhiteNoise (static files) |
| **AI Services** | Google Gemini (OCR + lyrics + flashcards), Mureka (music generation), self-hosted LoRA models, any OpenAI-compatible cloud LLM |
| **Payments** | Stripe Checkout + webhook-verified subscription updates |
| **Deployment** | Render.com (`render.yaml`, `build.sh`) + gunicorn/daphne |
| **ML Training** | PyTorch, Transformers, PEFT (LoRA), bitsandbytes (QLoRA 4-bit), TRL (SFTTrainer), Flask (inference API), Gradio (training WebUI) |

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

See `myproject/.env.example` for the full list. Minimum required:

```bash
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# AI services (optional — falls back gracefully if unset)
GEMINI_API_KEY=your-gemini-key
MUREKA_API_KEY=your-mureka-key
USE_MUREKA_API=True

# Lyrics backend selection: gemini | cloud | local | ollama | auto
LYRICS_BACKEND=gemini

# Stripe (optional, for payments)
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

Other notable env vars: `MUREKA_V9_URL` / `MUREKA_V9_LOCAL_URL` (Mureka V9 endpoint), `LOCAL_LLM_URL` / `LOCAL_LLM_API_KEY` (self-hosted GPU server), `CLOUD_LLM_PROVIDER` / `CLOUD_LLM_URL` / `CLOUD_LLM_MODEL` (Together AI / Fireworks / Groq / OpenRouter / vLLM), `ADMIN_ALLOWED_IPS` (admin IP allowlist), `MAX_CONCURRENT_GENERATIONS` / `STUCK_TIMEOUT_MINUTES` (generation queue tuning), `MAX_IMAGE_SIZE` / `MAX_PDF_SIZE` / `MAX_LYRICS_LENGTH`.

---

## Project Structure

```
utamemo-app/
├── myproject/
│   ├── myproject/                # Django project settings
│   │   ├── settings.py           # Configuration (DB, AI, security, Stripe pricing)
│   │   ├── urls.py                # Root URL routing
│   │   ├── security.py            # Custom SecurityMiddleware / Admin 2FA
│   │   ├── legal_views.py         # Privacy/Terms/Contact pages
│   │   └── queue_manager.py       # (see songs/queue_manager.py)
│   ├── songs/                     # Main app: songs, lyrics, flashcards, classrooms, AI
│   │   ├── models.py              # 17 models: Song, Lyrics, Classroom, FlashcardDeck, TrainingSession, ...
│   │   ├── views/                 # View package, split by domain (7,100+ lines total)
│   │   │   ├── core.py            # Song CRUD, lyrics flow, likes, playback, tags
│   │   │   ├── generation.py      # Upload/OCR, lyrics confirmation, generation API
│   │   │   ├── home.py            # Home, song list/detail
│   │   │   ├── classroom.py       # Classroom CRUD, join/leave, assignments
│   │   │   ├── flashcard.py       # Flashcard CRUD/study
│   │   │   ├── training.py        # Staff-only LLM training dashboard + API
│   │   │   ├── staff.py           # Staff tools, monitoring
│   │   │   ├── social.py          # Like/favorite/comment/play tracking
│   │   │   └── utility.py         # Language switch, audio proxy, content-violation page
│   │   ├── services/               # AI integration layer (split from ai_services.py)
│   │   │   ├── mureka.py          # MurekaAIGenerator (music generation, V8/V9)
│   │   │   ├── gemini_lyrics.py   # GeminiLyricsGenerator
│   │   │   ├── gemini_ocr.py      # GeminiOCR
│   │   │   ├── local_llm.py       # LocalLLMLyricsGenerator, CloudLLMLyricsGenerator, backend factory
│   │   │   ├── ollama.py          # OllamaLyricsGenerator
│   │   │   ├── pdf_extractor.py   # PyMuPDF text extraction
│   │   │   ├── hiragana.py        # Furigana/hiragana conversion for lyrics
│   │   │   └── flashcard_extractor.py  # GeminiFlashcardExtractor
│   │   ├── ai_services.py         # Backward-compat shim re-exporting services/
│   │   ├── content_filter.py      # Bilingual rule-based content moderation
│   │   ├── queue_manager.py       # ThreadPoolExecutor-based generation queue + WebSocket progress
│   │   ├── consumers.py / routing.py  # Django Channels WebSocket handlers
│   │   ├── forms.py, admin.py, apps.py
│   │   ├── templatetags/          # Custom template filters
│   │   ├── migrations/            # 46 migrations
│   │   └── tests.py                # ~55 tests
│   ├── users/                      # User management app
│   │   ├── models.py               # Custom User (plan/BAN/age-verification fields),
│   │   │                           #   StaffReviewObligation, TrainingDataReview, StaffMessage, ...
│   │   ├── views.py                 # Auth, profile, Stripe checkout/webhook
│   │   ├── middleware.py            # BanCheckMiddleware, StaffReviewLockMiddleware
│   │   ├── forms.py
│   │   └── tests.py                 # ~23 tests
│   ├── templates/                   # HTML templates
│   │   ├── base.html                 # Base template with Bootstrap 5
│   │   ├── songs/                    # Song, flashcard, classroom, staff-tool, theater templates
│   │   ├── users/                    # Auth, profile, upgrade/billing templates
│   │   ├── admin/                    # Admin 2FA, monitoring templates
│   │   └── legal/                    # Privacy, Terms, Contact
│   ├── static/                       # CSS, JS, images
│   └── manage.py
├── training/                        # Self-hosted LoRA training + inference pipeline
│   ├── train.py                     # QLoRA fine-tuning script (argparse CLI, multi-GPU aware)
│   ├── serve.py                     # Flask REST inference server (/health, /generate)
│   ├── training_agent.py            # Orchestration agent: polls Django, drives train.py/serve.py
│   ├── webui/app.py                 # Gradio WebUI for the training platform
│   ├── generate_history_data.py     # Gemini-based synthetic training-data generation
│   ├── lyrics_generation/, note_importance/  # Dataset builders/trainers for two model types
│   ├── requirements_training.txt
│   └── README.md
├── docs/                            # Design documents (Japanese)
│   ├── SOFTWARE_DESIGN.md           # Detailed software design, sequence diagrams, tech-debt log
│   ├── ARCHITECTURE.md              # System configuration, ER diagram, URL routing table
│   ├── CUSTOM_LLM_ROADMAP.md        # Roadmap for the self-hosted LLM initiative
│   └── meeting_pitch_*.md           # Business/partner pitch notes (Clearnote, Kokuyo)
├── UtaMemo/                          # Separate SwiftUI iOS prototype (own git repo, not wired to backend)
├── requirements.txt                  # Production dependencies (Django app)
├── render.yaml                       # Render.com deployment config
├── build.sh                          # Render build script
├── Procfile
├── DOMAIN_SETUP.md / DOMAIN_SETUP_EN.md  # Domain/DNS setup guide
└── CONTRIBUTING.md                   # Contributor guide (Japanese)
```

---

## Core Workflows

### 1. Song Generation Pipeline

```
User uploads photo or PDF
       |
       v
Gemini OCR (image) or PyMuPDF (PDF) extracts text
       |
       v
ContentFilter validates extracted text
       |
       v
Lyrics generated via LYRICS_BACKEND
  (gemini | cloud | local | ollama | auto)
  auto mode tries: Cloud LLM -> Ollama -> Local LLM -> Gemini
       |
       v
User reviews/edits lyrics, confirms
       |
       v
Queued in songs/queue_manager.py (ThreadPoolExecutor,
  concurrency-limited, retries with backoff)
       |
       v
Mureka API generates the song (async, polled to completion)
       |
       v
Optional: Demucs-based karaoke (instrumental) extraction
       |
       v
Audio stored in Cloudflare R2; progress pushed live via
  Django Channels WebSocket
       |
       v
Song completed -> shareable via unique share_id
```

### 2. Flashcard Generation

```
Song lyrics or source image
       |
       v
Gemini extracts term/definition pairs (GeminiFlashcardExtractor)
       |
       v
FlashcardDeck created, cards tagged by importance (high/normal)
       |
       v
User studies cards; each tracks a 4-level mastery score
  (未学習 / 学習中 / もう少し / 覚えた)
```

### 3. Subscription Flow

```
User clicks upgrade
       |
       v
Age verification (if under 18 -> guardian consent required
  before any payment can proceed)
       |
       v
Stripe Checkout session created (plan-specific price ID)
       |
       v
Payment completed
       |
       v
Stripe webhook signature verified
       |
       v
User.plan updated (starter / pro / school), monthly
  generation limits recalculated
```

### 4. Classroom Feature (School Plan)

```
Teacher creates a Classroom -> gets a unique join code
       |
       v
Shares the code with students
       |
       v
Students join with the code (requires school plan)
       |
       v
Teacher shares songs into the class, or creates a
  ClassroomAssignment (song + due date + note)
       |
       v
Students study assigned songs via auto-generated flashcards
```

### 5. Self-Hosted LLM Training Loop

```
Django TrainingSession row created / staff issues a
  pending_command (start / stop / start_serve)
       |
       v
training_agent.py (running on the GPU machine) polls the
  Django API, picks up the command
       |
       v
train.py runs QLoRA fine-tuning (base model: Qwen2.5-14B-Instruct,
  auto multi-GPU memory split), reports live loss/step/GPU
  metrics back to TrainingSession
       |
       v
serve.py (Flask) or webui/app.py (Gradio) exposes the
  fine-tuned model over HTTP, tunneled to the internet via
  Cloudflare Tunnel
       |
       v
Production sets LOCAL_LLM_URL / LYRICS_BACKEND=local (or auto)
  to route lyrics generation to the self-hosted model
```

---

## Data Model (Highlights)

**`songs` app** — `Song` (title, genre, vocal style, `mureka_model` V8/V9, generation status/queue position/retry count, encryption flag, share_id, like/play counters, karaoke status), `Lyrics` (content, OCR source text, LRC timing data), `Tag`, `Like` / `Favorite` / `Comment` / `PlayHistory`, `UploadedImage`, `Classroom` / `ClassroomMembership` / `ClassroomSong` / `ClassroomAssignment`, `FlashcardDeck` / `Flashcard`, `TrainingSession` (GPU/loss/step metrics, Wake-on-LAN fields, heartbeat), `PromptTemplate` (DB-managed lyric prompts, survives redeploys), `TrainingData` (deduplicated via SHA-256 hash), plus the standalone `TheaterReservation` / `TheaterSurveyResponse` pair for the unrelated cinema-booking feature.

**`users` app** — a custom `User(AbstractUser)` with plan (`free`/`starter`/`pro`/`school`), Stripe customer/subscription IDs, BAN fields (`is_banned`, `ban_reason`, `banned_at`), teacher flag, birth date + guardian-consent fields with `is_minor`/`can_purchase()` helpers, and plan-based helpers like `get_monthly_song_limit()`. Also: `StaffReviewObligation` (mandatory training-data review workload for staff, auto-accrues and can lock staff out of other admin pages), `TrainingDataReview` (soft-deletable review queue, hash-deduplicated), `StaffMessage`, `ReviewBackup`.

---

## Security Features

| Threat | Countermeasure | Implementation |
|--------|---------------|----------------|
| Invalid/harmful input | Bilingual rule-based `ContentFilter` with academic/lyrical-context allowlisting | `songs/content_filter.py` |
| SSRF | Domain allowlist for the audio proxy | `songs/views/utility.py: audio_proxy()` |
| CSRF | Django CSRF middleware | `settings.py` |
| Privilege escalation | `@login_required` + per-object ownership checks | Every relevant view |
| Admin access | TOTP-based two-factor authentication + IP allowlist | `myproject/security.py` |
| BAN bypass | `BanCheckMiddleware` forces logout on every request for banned users | `users/middleware.py` |
| Payment forgery | Stripe webhook signature verification | `users/views.py` |
| Minor payments | Birth date capture + guardian-consent gate before checkout | `users/models.py`, `users/views.py` |
| Secret leakage | Environment variables only, `.env` gitignored | — |
| Staff data-review evasion | `StaffReviewLockMiddleware` locks staff to the review queue once their obligation backlog crosses a threshold | `users/middleware.py` |

### Encryption

Songs can be stored encrypted with Fernet symmetric encryption:
- AES-128-CBC cipher mode
- 256-bit derived key from Django `SECRET_KEY` + a per-song salt
- HMAC authentication for integrity verification

---

## Subscription Plans

| Plan | Price | Monthly Generation Limit | V9/V8 Models | Classroom |
|------|-------|--------------------------|---------------|-----------|
| **Free** | ¥0 | 5 songs/mo | Limited | No |
| **Starter** | ¥780/mo | 70 songs/mo | Yes | No |
| **Pro** | ¥1,900/mo | Unlimited | Yes | No |
| **School** | ¥450 / student / mo | 100 songs/mo | Yes | Yes |
| **Staff** | Free (invited) | Unlimited | Yes | Yes |

> Staff/superuser accounts get all features automatically regardless of assigned plan.

---

## AI Integration Details

- **Lyrics generation** is provider-agnostic behind a common interface, selected via `LYRICS_BACKEND`:
  - `gemini` (default) — Google Gemini
  - `cloud` — any OpenAI-compatible endpoint (Together AI, Fireworks AI, Groq, OpenRouter, or a custom vLLM server)
  - `local` — the team's self-hosted GPU inference server (`training/serve.py`)
  - `ollama` — local Ollama for development
  - `auto` — tries Cloud LLM → Ollama → Local LLM → Gemini, in that order, based on live availability checks
- **Music generation** uses the Mureka API, with a `mureka_model` choice of `mureka-v9` (default) or `mureka-v8` per song; generation is asynchronous (submit → poll `/v1/song/query/{task_id}`) with retry/backoff for rate limits and transient errors, plus a dictionary-based Japanese→English music-style prompt translator and vocal-style-specific prompt engineering.
- **OCR** uses Gemini for photos and PyMuPDF for PDFs.
- **Flashcard extraction** uses Gemini to turn lyrics or source text into term/definition pairs with importance tagging.
- **Karaoke tracks** use Demucs-based source separation to produce an instrumental-only version of a generated song.

---

## Self-Hosted LLM Training Platform

UTAMEMO includes a full pipeline (under `training/`) for fine-tuning and serving a custom lyrics-generation LLM on team-owned hardware, as a cost-control alternative to always calling cloud LLM APIs:

- **Hardware**: home RTX 4060 Ti (16GB) and school dual RTX 4080 SUPER (32GB total)
- **Base model**: `Qwen/Qwen2.5-14B-Instruct` by default (auto multi-GPU memory splitting when 2+ GPUs are detected), with prior support for Llama 3 (8B/3.1 8B), Gemma 2 9B, Phi-3-mini, and Qwen2.5-32B
- **Fine-tuning method**: QLoRA (4-bit, via `bitsandbytes` + `peft`), configurable rank/epochs via CLI args in `train.py`
- **Orchestration**: `training_agent.py` runs on the GPU machine, polls the Django `TrainingSession` model for pending commands (`start`/`stop`/`start_serve`), and reports live metrics (loss, step, GPU/VRAM usage, ETA) back to the web app
- **Serving**: `serve.py` is a Flask REST API (`/health`, `/generate`, API-key authenticated) supporting both `transformers` and `vllm` inference backends; `webui/app.py` provides a separate Gradio-based management WebUI
- **Connectivity**: the inference server is exposed to the internet via a Cloudflare Tunnel so Render (production) can reach it as `LOCAL_LLM_URL`
- **Data pipeline**: training data can be exported from production, sampled, or synthetically generated via Gemini (`generate_history_data.py`); data is deduplicated by a SHA-256 hash and requires staff review (`StaffReviewObligation`/`TrainingDataReview`) before being used for training
- **Two model tracks**: `lyrics_generation/` (main lyrics model) and `note_importance/` (a secondary model for scoring which extracted text is important enough to include)

See [training/README.md](training/README.md) for the full setup guide.

---

## Testing

```bash
# Run all tests
python manage.py test --verbosity=2

# Run specific app tests
python manage.py test songs --verbosity=2
python manage.py test users --verbosity=2
```

**Current test coverage:** ~78 tests (~55 in `songs`, ~23 in `users`). AI service calls are not yet mocked/tested (tracked as tech debt, see below).

---

## Multi-Language Support

UTAMEMO uses a custom **session-based** language switcher (not Django's built-in i18n framework):

Supported languages: `ja` (Japanese), `en` (English), `zh` (Chinese), `es` (Spanish), `de` (German), `pt` (Portuguese), `nl` (Dutch)

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

Tracked in detail in [docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md):

| ID | Priority | Task | Status |
|----|----------|------|--------|
| D-1 | High | Split `ai_services.py` monolith into `services/` modules | **Done** — now a re-export shim over `songs/services/` |
| D-2 | High | Split `views/core.py` (still 2,140 lines) into smaller modules | Planned |
| D-3 | Medium | Split `songs/models.py` (17 models, ~1,100 lines) into modules | Planned |
| D-4 | Medium | Clarify service layer — some business logic still lives in views | Planned |
| D-5 | Medium | Add AI-service mock tests (currently zero) | Planned |
| D-6 | Low | Migrate from session-based i18n to Django's i18n framework | Future |
| D-7 | Low | Add frontend test coverage (currently none) | Future |

---

## Admin & Staff Features

### Admin Tools
- **2FA Authentication**: TOTP-based two-factor authentication for admin access, plus optional IP allowlisting
- **Monitoring Dashboard** (`staff_monitor.html`): real-time system/queue monitoring
- **Content Moderation**: view and manage user-generated content reports and filter violations
- **BAN Management**: ban/unban users, force logout on next request

### Staff LLM Tools
- **Training Dashboard**: monitor LoRA training sessions (loss, GPU usage, ETA) in real time
- **Data Review Queue**: staff must review/approve or reject training-data samples before they're used (with an accruing review-obligation system that can lock staff out of other pages if backlog builds up)
- **Prompt Template Editor**: manage DB-persisted prompt templates for lyrics generation (survives redeploys, unlike file-based prompts)
- **LLM/Mureka Test Tools** (`test_llm.html`, `test_mureka.html`): manual testing UIs for the AI backends
- **Quality Check Tool**: review generated training data quality before it enters a training run

---

## API Endpoints (Internal, Selected)

`songs/urls.py` defines ~78 routes and `users/urls.py` ~20; highlights:

| URL Pattern | View | Authentication | Description |
|-------------|------|----------------|-------------|
| `/songs/create/` | CreateSongView | Login required | Song creation page |
| `/songs/generate/` | UploadImageView | Login required | Upload textbook photo/PDF |
| `/songs/lyrics/generate/` (API) | generate_lyrics_api | Login required | Generate lyrics via the active AI backend |
| `/songs/<id>/` | SongDetailView | Public | Song detail page |
| `/songs/my/` | MySongsView | Login required | User's song list |
| `/songs/classroom/` | ClassroomListView | School plan | Classroom management |
| `/songs/flashcard/` | FlashcardDeckListView | Login required | Flashcard decks |
| `/accounts/register/` | RegistrationView | Anonymous only | User registration |
| `/accounts/upgrade/` | upgrade_plan | Login required | Subscription upgrade |
| `/api/stripe/create-session/` | create_checkout_session | Login required | Create Stripe Checkout session |
| `/stripe/webhook/` | stripe_webhook | Webhook secret | Stripe webhook handler |

Full route tables are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributor guide (Japanese)
- [docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md) — Detailed software design, sequence diagrams, tech-debt log (Japanese)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System configuration, ER diagram, full URL routing table (Japanese)
- [docs/CUSTOM_LLM_ROADMAP.md](docs/CUSTOM_LLM_ROADMAP.md) — Roadmap for the self-hosted LLM initiative (Japanese)
- [DOMAIN_SETUP.md](DOMAIN_SETUP.md) / [DOMAIN_SETUP_EN.md](DOMAIN_SETUP_EN.md) — Domain/DNS setup guide
- [training/README.md](training/README.md) — Local LLM training server guide

> Note: `docs/SOFTWARE_DESIGN.md` and `docs/ARCHITECTURE.md` were last updated 2026-04-17 and lag behind some recent code changes (e.g. the `ai_services.py` → `services/` split and the Mureka V9 rollout are more advanced in code than in the docs).

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

## Acknowledgments

- **Django** — The web framework for perfectionists with deadlines
- **Bootstrap 5** — Frontend framework
- **Google Gemini** — OCR, lyrics generation, and flashcard extraction
- **Mureka** — AI music generation API
- **Stripe** — Payment processing
- **Cloudflare R2 / Tunnel** — Object storage and self-hosted-server connectivity
- **PEFT / bitsandbytes / TRL** — LoRA/QLoRA fine-tuning of the self-hosted lyrics model

---

Built by the UTAMEMO Team

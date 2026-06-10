# CareMate — Intelligent Vaccination Platform

[![CI](https://github.com/poilvetcarl-svg/CareMate/actions/workflows/ci.yml/badge.svg)](https://github.com/poilvetcarl-svg/CareMate/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Tests](https://img.shields.io/badge/tests-35%20passing-brightgreen)

Personalised adult-vaccination platform for the Indonesian market: a clinical
rule engine grounded in **PAPDI 2025 / CDC ACIP / WHO** guidelines, AI-generated
patient summaries, live AI-doctor video consultations, clinic booking, and
WhatsApp dose reminders.

**Stack:** Flask · SQLAlchemy · OpenAI · Tavus CVI · Twilio · Docker

---

## Why this project is interesting (engineering-wise)

1. **The core is a deterministic clinical rule engine, not an LLM.**
   Vaccine recommendations and risk scores are computed by auditable,
   unit-tested Python rules sourced from published guidelines. The LLM only
   *narrates* results it is handed — it can never invent a recommendation.
   In a medical context, "the AI said so" is not an acceptable audit trail.

2. **Every external dependency degrades gracefully.**
   No OpenAI key → deterministic summary text. Tavus video stream drops →
   automatic fallback to text chat + TTS with a retry path. The test suite
   pins these fallback paths so they can't silently rot.

3. **The risk model encodes clinical interactions, not just additive scores.**
   Age ≥ 65 with a chronic condition compounds (immune senescence), overdue
   vaccination at high-risk age adds urgency. Tests assert monotonicity
   (adding a condition can never *lower* your risk) and calibration bands.

## Architecture

```
                ┌──────────────────────────────────────────────┐
                │                   Flask app                  │
                │                                              │
 Browser ──────▶│  Jinja2 pages     /api/recommend  ◀── rule   │
   │            │  (SSR, no SPA)    /api/chat           engine │
   │            │                   /api/consult (SSE)    │    │
   │            │                   /api/tts              │    │
   │            │                        │            data/    │
   │            │                        ▼         vaccines.json
   │            │                   OpenAI GPT-4o-mini          │
   │            │                   (narration only)            │
   │            └──────┬───────────────┬───────────────┬───────┘
   │                   │               │               │
   ▼                   ▼               ▼               ▼
 Tavus CVI         SQLAlchemy       Twilio         APScheduler
 (WebRTC AI        (SQLite dev /    (WhatsApp      (daily reminder
  doctor video)     Postgres prod)   reminders)     job, 09:00 WIB)
```

**Key decisions & trade-offs**

| Decision | Why | Trade-off accepted |
|---|---|---|
| Server-rendered Jinja2, no React | One deployable artifact, no build step, SEO out of the box | Less interactive state management; fine at this scope |
| Rule engine in JSON + Python, not LLM | Auditability, determinism, testability — non-negotiable for medical advice | Guideline updates require code/data changes, not prompt edits |
| SQLite dev → Postgres prod via `DATABASE_URL` | Zero-config local development | Migrations are simplistic (`create_all`); Alembic is the next step |
| In-memory rate limiting (flask-limiter) | Protects paid OpenAI/Tavus endpoints from abuse | Resets on restart; Redis storage when scaling beyond one process |
| LLM temperature 0.85 for patient-facing text | Natural, non-robotic voice | Slight variability; acceptable because clinical content is rule-driven |

## What would break at 1M users (and the fix)

- **In-process APScheduler** → would fire once per gunicorn worker. Fix: extract to a worker queue (Celery/RQ) or cron-triggered job.
- **In-memory rate limits** → per-process, reset on deploy. Fix: `storage_uri="redis://..."` — one line.
- **SQLite writes** → single-writer lock. Fix: already env-switchable to Postgres; add Alembic migrations.
- **OpenAI calls block workers** → switch to async workers (gevent) or queue the narration and stream it.
- **Tavus conversations are expensive** → pool/queue sessions; the text+TTS fallback already absorbs overflow.

## Testing

```bash
python -m pytest tests/ -v        # 35 tests, <1s
```

- `test_risk_engine.py` — calibration bands, monotonicity, interaction bonuses
- `test_vaccine_recommendations.py` — clinical safety (live vaccines blocked in pregnancy), age gating, condition triggers, travel logic
- `test_api.py` — endpoint contracts, input validation (400s), graceful AI fallback (a test in this suite caught a real empty-summary bug)

CI runs the suite on Python 3.11 + 3.12 and verifies the Docker image builds on every push.

## Security & operations

- Input validation on the assessment API (age bounds, condition/region allow-lists)
- Rate limiting on all AI-backed endpoints (`flask-limiter`, headers enabled)
- CSRF protection on forms; API routes exempted explicitly and deliberately
- Secrets via environment only — `.env` is git-ignored, no keys in the repo
- `/health` endpoint reporting DB/AI/video status for uptime monitors
- Structured request logging with latency per request

## Features

- **3-step assessment** → risk score (animated gauge) + prioritised vaccine plan for 15 vaccines, with per-condition clinical explanations
- **AI doctor teleconsultation** — live Tavus video avatars with per-doctor personas, language switch (EN/ID), automatic prescription generation (ICD-10 coded)
- **Clinic finder** — 8 partner clinics, vaccine filtering, booking with WhatsApp reminders (7d / 1d / same-day)
- **User & corporate dashboards** — vaccination history, certificates with QR verification, HR coverage analytics
- **Assistant chatbot** — guideline-grounded Q&A with conversation memory

## Run it

```bash
git clone https://github.com/poilvetcarl-svg/CareMate.git && cd CareMate
pip install -r requirements.txt
cp .env.example .env              # add OPENAI_API_KEY (optional — degrades gracefully)
python3 app.py                    # http://127.0.0.1:5050
```

Docker: `docker build -t caremate . && docker run -p 8080:8080 -e PORT=8080 caremate`

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | Optional | AI summaries, chatbot, doctor chat, TTS (falls back without) |
| `TAVUS_API_KEY` | Optional | Live AI-doctor video (falls back to text + TTS) |
| `SECRET_KEY` | Recommended | Flask sessions |
| `DATABASE_URL` | Optional | Postgres in production (SQLite by default) |
| `TWILIO_*` | Optional | WhatsApp reminders |

## Accessibility & performance

- Skip-to-content link, ARIA labels on icon controls, `main` landmark, `prefers-reduced-motion` respected
- Font preconnect, lazy video metadata, no JS framework payload (vanilla JS)

## Medical disclaimer

CareMate is a portfolio/prototype project. It is **not** a medical device and
does not replace professional medical advice. Recommendation logic follows
published PAPDI 2025 / CDC / WHO guidelines — see the in-app **References**
page for the full evidence base.

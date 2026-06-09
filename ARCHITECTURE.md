# VaxAI — Architecture Document

## System Overview

```
Browser (User)
     │
     │  HTTP / JSON
     ▼
┌─────────────────────────────┐
│       Flask App (app.py)     │
│                              │
│  Routes:                     │
│  ├── GET  /                  │  → index.html
│  ├── POST /api/recommend     │  → vaccine engine + OpenAI
│  ├── POST /api/chat          │  → OpenAI chatbot
│  ├── GET  /teleconsultation  │  → teleconsultation.html
│  └── GET  /api/doctors       │  → doctor list (JSON)
│                              │
│  Engine:                     │
│  ├── calculate_risk_score()  │  → multi-factor scoring
│  ├── get_recommended_vaccines│  → rule-based + age/condition logic
│  └── VACCINE_DATA (JSON)     │  → data/vaccines.json
└──────────┬──────────────────┘
           │
           │  HTTPS (optional)
           ▼
    ┌─────────────┐
    │  OpenAI API  │
    │  gpt-4o-mini │
    └─────────────┘
```

## Frontend Architecture

```
index.html
├── Navbar (fixed, blur-on-scroll)
├── Hero Section
│   ├── Animated orb backgrounds
│   ├── Hero content (title, CTA buttons, stats counters)
│   └── Phone mockup (CSS animation)
├── Video Section (3 cards)
├── Feature Images (3-col grid)
├── Assessment Form (multi-step)
│   ├── Step 1: Age slider, sex, pregnancy, vaccination history
│   ├── Step 2: Medical conditions grid (12 conditions)
│   └── Step 3: Travel destinations
├── Results Section (rendered dynamically)
│   ├── AI Summary card (typing animation)
│   ├── Risk gauge (SVG animated arc)
│   ├── Risk factor breakdown list
│   └── Vaccine cards grid (click → modal)
├── Trust logos bar
├── Footer
├── Floating Chatbot widget
└── Modals (vaccine detail, loading overlay)
```

## Data Flow

### Vaccine Recommendation
```
User fills form
  → collectFormData() [main.js]
  → POST /api/recommend [app.py]
  → calculate_risk_score(data)     → risk object
  → get_recommended_vaccines(data) → vaccine list
  → OpenAI API (optional)          → ai_summary string
  → JSON response
  → renderResults(result) [main.js]
    → renderRiskScore() → SVG gauge animation
    → renderVaccines()  → card grid with modals
```

### Chatbot
```
User types message
  → sendMessage() [main.js]
  → POST /api/chat with history array
  → OpenAI messages array (system + history + user)
  → reply string
  → appendMessage('bot', reply)
```

## Vaccine Rule Engine

Rules are evaluated in `get_recommended_vaccines()`:

| Rule | Logic |
|---|---|
| Age range | `vaccine.age_range[0] <= age <= vaccine.age_range[1]` |
| Universal | `"all" in vaccine.conditions` |
| Pregnancy | `pregnant == "yes" and "pregnancy" in conditions` |
| Age-gated | `age >= 50` for Zoster, `age <= 45` for HPV |
| Condition-specific | Loop: `condition in vaccine.conditions` |
| Travel | `travel_region in travel_regions` |
| Contraindication | Exclude live vaccines (MMR, Varicella, Zoster) if pregnant |

## Risk Score Formula

```
score = age_points + condition_points + pregnancy_bonus + travel_bonus + unvaccinated_bonus

Age:          18–49 = 1pt, 50–64 = 2pt, 65+ = 3pt
Each condition: 1–4 pts (from vaccines.json risk_factors[].weight)
Pregnancy:    +3pt
Travel:       +2pt
Not vaccinated: +2pt

percentage = min(100, (score / 25) * 100)
Low:    < 40%
Moderate: 40–69%
High:   ≥ 70%
```

## File Responsibilities

| File | Responsibility |
|---|---|
| `app.py` | All server logic: routing, vaccine engine, risk scoring, OpenAI calls, doctor data |
| `data/vaccines.json` | Static vaccine definitions, risk factor weights, condition mappings |
| `templates/index.html` | Main SPA — form, results section, modals, chatbot markup |
| `templates/teleconsultation.html` | Doctor listings, booking modal, map, filter controls |
| `static/css/style.css` | Full design system — ~900 lines, CSS custom properties, animations |
| `static/js/main.js` | Form wizard, results rendering, chatbot, counter animations, API calls |

## Extension Points

To add a new vaccine:
1. Add entry to `data/vaccines.json` under `vaccines`
2. Add conditions/triggers (matches `conditions` field)
3. Add disease relationship explanations to `VACCINE_DISEASE_RELATIONS` in `app.py`

To add a new doctor:
1. Append to `DOCTORS` list in `app.py`

To add a new language:
1. Duplicate `templates/index.html` → `templates/index_id.html`
2. Add `/id/` route in `app.py`
3. Translate all text content

To connect a real payment system:
1. Add `/api/book` endpoint in `app.py`
2. Integrate Midtrans (Indonesia) or Stripe
3. Replace WhatsApp link in `bookConsultation()` with payment flow

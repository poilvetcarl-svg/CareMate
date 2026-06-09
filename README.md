# 💉 VaxAI — AI-Powered Vaccination Recommendation Platform

> A full-stack web application that delivers personalized vaccine recommendations, risk assessment scoring, AI-powered explanations, teleconsultation with Indonesian doctors, and an integrated chatbot — built with Python Flask, OpenAI, and modern Apple-inspired UI.

---

## 🎯 What This Is

VaxAI is a prototype vaccination platform designed to be sold to hospitals, clinics, or health-tech companies. It combines:

- **Clinical intelligence** — CDC/WHO vaccination guidelines encoded in a rule engine
- **Generative AI** — OpenAI GPT-4o-mini for personalized clinical summaries and chatbot
- **Healthcare UX** — Apple-inspired dark UI with animations, glassmorphism, and responsive design
- **Business model** — Teleconsultation booking (WhatsApp integration), doctor listings, commercial-ready structure

---

## 🚀 Features

### 1. AI Vaccine Recommendation Engine
- 3-step assessment form: Profile → Health Conditions → Travel
- Covers **13 vaccines**: Influenza, COVID-19, Tdap, MMR, Varicella, Zoster/Shingrix, HPV, Pneumococcal, Hepatitis A, Hepatitis B, Meningococcal, Typhoid, Yellow Fever, Japanese Encephalitis
- Rules based on age, sex, pregnancy, 12 medical conditions, travel destinations
- OpenAI generates a warm, personalized clinical summary paragraph

### 2. Risk Assessment Score
- Multi-factor scoring (age + conditions + pregnancy + travel + vaccination history)
- Animated SVG gauge (0–100%) with color tiers: 🟢 Low / 🟡 Moderate / 🔴 High
- Itemized breakdown of each risk factor and its point weight

### 3. Disease–Vaccine Relationship Explanations
- Clicking any vaccine card opens a detail modal
- Clinical explanation of WHY your specific condition makes that vaccine critical
- Examples: diabetes → pneumococcal connection, HIV → shingles risk, pregnancy → Tdap importance

### 4. AI Chatbot (VaxAI Assistant)
- Floating widget persistent on every page
- Powered by OpenAI GPT-4o-mini (with smart fallback responses offline)
- Pre-suggested questions, typing animation, full conversation context
- Topics: vaccine schedules, side effects, pregnancy safety, travel vaccines, COVID-19

### 5. Teleconsultation Page (`/teleconsultation`)
- 8 Indonesian vaccine specialists with realistic profiles, ratings, consultation fees, available time slots
- Browser geolocation detection to show nearest doctors
- Filter by city / specialty / availability / name search
- Interactive Indonesia coverage map with animated pins
- WhatsApp booking integration (pre-filled message with patient details)

### 6. Apple-Inspired UI
- Dark glassmorphism design system with CSS custom properties
- Animated gradient orbs, grid overlay background, Inter font
- Animated hero stats counter, phone mockup with floating animation
- Video cards with hover effects, feature image trio
- Fully responsive (mobile, tablet, desktop)

---

## 🗂 Project Structure

```
vaccination-tool/
├── app.py                          # Flask backend — routes, AI logic, vaccine engine
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── README.md                       # This file
│
├── data/
│   └── vaccines.json               # Vaccine definitions, risk factors, metadata
│
├── templates/
│   ├── index.html                  # Main page — hero, form, results, chatbot
│   └── teleconsultation.html       # Doctor listings, booking modal
│
└── static/
    ├── css/
    │   └── style.css               # Full design system (~900 lines)
    └── js/
        └── main.js                 # Frontend logic — form steps, results rendering, chatbot
```

---

## ⚙️ Installation & Setup

### Prerequisites
- Python 3.9+
- pip
- An OpenAI API key (optional — fallback responses work without one)

### 1. Clone / unzip the project
```bash
cd vaccination-tool
```

### 2. Create a virtual environment (recommended)
```bash
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
cp .env.example .env
```

Edit `.env`:
```env
OPENAI_API_KEY=sk-your-key-here
SECRET_KEY=any-random-secret-string
```

> **Without an OpenAI key:** The vaccine recommendation engine, risk scoring, and all rule-based logic still work fully. The AI clinical summary and chatbot fall back to pre-written responses.

### 5. Run the application
```bash
python3 app.py
```

Open: **http://localhost:5050**

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Optional | GPT-4o-mini key for AI summaries and chatbot |
| `SECRET_KEY` | Recommended | Flask session secret (any random string) |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Main assessment page |
| `POST` | `/api/recommend` | Submit health profile → returns vaccines + risk score + AI summary |
| `POST` | `/api/chat` | Send chatbot message → returns AI reply |
| `GET` | `/teleconsultation` | Doctor listing page |
| `GET` | `/api/doctors` | JSON doctor list (supports `?city=`, `?specialty=`, `?available=true`) |

### `POST /api/recommend` — Request body
```json
{
  "age": 65,
  "sex": "male",
  "pregnant": "no",
  "vaccinated_recently": "no",
  "conditions": ["diabetes", "heart_disease"],
  "travel_regions": ["Southeast Asia"]
}
```

### `POST /api/recommend` — Response
```json
{
  "risk": {
    "score": 13,
    "percentage": 52,
    "level": "Moderate Risk",
    "color": "#FFA502",
    "emoji": "🟡",
    "advice": "Several vaccines are overdue or strongly recommended.",
    "factors": [...]
  },
  "vaccines": [
    {
      "key": "influenza",
      "name": "Influenza (Flu)",
      "schedule": "Annually",
      "description": "...",
      "reasons": ["Recommended for all adults by CDC/WHO"],
      "priority": "routine",
      "icon": "🦠",
      "color": "#FF6B6B",
      "disease_relations": {
        "diabetes": "People with diabetes have impaired immune responses..."
      }
    }
  ],
  "ai_summary": "Based on your profile as a 65-year-old male with diabetes...",
  "total_vaccines": 9
}
```

---

## 🧬 Vaccine Coverage

| Vaccine | Triggers |
|---|---|
| Influenza | All adults (annual) |
| COVID-19 | All adults |
| Tdap / Td | All adults; pregnancy (3rd trimester) |
| MMR | Age 18–64 if not immune; NOT in pregnancy |
| Varicella | Age 18–64 if not immune |
| Zoster/Shingrix | Age 50+; immunocompromised |
| HPV | Age 18–45 |
| Pneumococcal | Age 65+; diabetes, heart disease, lung disease, smoking, asplenia |
| Hepatitis A | Travel, liver disease, HIV |
| Hepatitis B | All adults; diabetes, kidney disease, liver disease |
| Meningococcal | Asplenia, HIV, college, travel |
| Typhoid | Travel to endemic regions |
| Yellow Fever | Travel to Africa/South America (legally required) |
| Japanese Encephalitis | Travel to rural Asia |

---

## 🏥 Supported Medical Conditions

| Condition | Risk Weight | Vaccines triggered |
|---|---|---|
| Diabetes | +3 | Influenza, Pneumococcal, Hepatitis B, COVID-19 |
| Heart Disease | +3 | Influenza, Pneumococcal, COVID-19 |
| Chronic Lung Disease | +3 | Influenza, Pneumococcal, COVID-19 |
| Cancer / Chemotherapy | +4 | Influenza, Pneumococcal, Zoster, Hepatitis B |
| HIV/AIDS | +4 | Influenza, Pneumococcal, Hepatitis B, Zoster, Meningococcal |
| Kidney Disease | +3 | Influenza, Hepatitis B, Pneumococcal |
| Liver Disease | +3 | Hepatitis A, Hepatitis B, Pneumococcal |
| Immunocompromised | +4 | Influenza, Pneumococcal, Zoster, Meningococcal |
| Asplenia | +4 | Pneumococcal, Meningococcal |
| Smoking | +2 | Pneumococcal |
| Obesity | +2 | Influenza, COVID-19 |
| Pregnancy | +3 | Influenza, Tdap, COVID-19 |

---

## 🗺 Teleconsultation — Indonesian Doctors

The platform includes 8 mock specialists across:
- **Jakarta Selatan** — RS Pondok Indah, RS Medistra
- **Jakarta Pusat** — RSUP Cipto Mangunkusumo
- **Jakarta Timur** — RS Hermina Jatinegara
- **Tangerang** — RS Siloam, RS Premier Bintaro
- **Bekasi** — Klinik Pratama SehatKu
- **Surabaya** — Klinik Vaksin Indonesia

To add real doctors: edit the `DOCTORS` list in `app.py`.

---

## 🤖 AI / OpenAI Integration

Two AI features use `gpt-4o-mini`:

**1. Clinical Summary** (`/api/recommend`):
- Builds a prompt with patient age, conditions, risk level, and top vaccines
- Returns a 3–4 sentence empathetic clinical summary
- Fallback: pre-written generic summary

**2. Chatbot** (`/api/chat`):
- System prompt defines "VaxAI Assistant" persona following CDC/WHO guidelines
- Maintains last 10 messages of conversation history
- Fallback: keyword-matched pre-written responses

---

## 🎨 Design System

| Token | Value |
|---|---|
| Background | `#0a0a0f` |
| Card background | `rgba(255,255,255,0.04)` |
| Accent purple | `#7c3aed` |
| Accent blue | `#3b82f6` |
| Success green | `#10b981` |
| Warning orange | `#f59e0b` |
| Danger red | `#ef4444` |
| Font | Inter (Google Fonts) |
| Border radius | `20px` (cards), `12px` (elements) |

---

## 📦 Dependencies

```
flask==3.0.0          # Web framework
openai==1.12.0        # GPT-4o-mini API client
python-dotenv==1.0.0  # .env file loading
flask-cors==4.0.0     # Cross-origin headers
requests==2.31.0      # HTTP client
```

---

## 🚀 Deployment Options

### Render (free tier)
1. Push to GitHub
2. Create new Web Service on render.com
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add `OPENAI_API_KEY` as environment variable

### Railway
```bash
railway login && railway up
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .
EXPOSE 5050
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "app:app"]
```

---

## 💼 Business Model / Commercialization

This prototype is designed to be pitched to:

1. **Hospital chains** — White-label the platform, integrate their doctor roster
2. **Health insurance companies** — Offer as a digital preventive health tool
3. **Vaccine manufacturers** — Patient education and demand generation
4. **Corporate HR / Occupational health** — Employee vaccination programs
5. **Government health agencies** — Population-level screening tool

**Revenue streams:**
- SaaS license per hospital/clinic
- Teleconsultation commission (10–20% per booking)
- Vaccine booking/fulfillment fee
- Premium AI features subscription

---

## 🔒 Disclaimer

> VaxAI is for informational and demonstration purposes only. Vaccine recommendations are based on publicly available CDC and WHO guidelines. This platform does not replace professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider for personalized medical decisions.

---

## 👤 Author

Built as a healthcare AI prototype demonstrating:
- Full-stack Python/Flask + JavaScript development
- OpenAI API integration (tool use, prompt engineering)
- Clinical rule engine design
- Modern Apple-inspired UI/UX
- Indonesian healthcare market adaptation

---

*© 2025 VaxAI Platform — Prototype v1.0*

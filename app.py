from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from openai import OpenAI
import os
import json
import math
import base64
import requests as http_req
import string
import random
from datetime import date, datetime
from dotenv import load_dotenv
import logging
import time

load_dotenv()

APP_VERSION = "1.0.0"

# ── Structured logging ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s :: %(message)s',
)
logger = logging.getLogger("caremate")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vacc-dev-secret-2024")
CORS(app)

# ── Rate limiting — protects the OpenAI/Tavus-backed endpoints from abuse ──
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],                      # only opt-in limits below
    storage_uri="memory://",
    headers_enabled=True,                   # X-RateLimit-* response headers
)


@app.before_request
def _start_timer():
    request._start_time = time.perf_counter()


@app.after_request
def _log_request(response):
    # Skip static assets to keep logs signal-dense
    if not request.path.startswith("/static"):
        duration_ms = (time.perf_counter() - getattr(request, "_start_time", time.perf_counter())) * 1000
        logger.info("%s %s → %s (%.1fms)", request.method, request.path,
                    response.status_code, duration_ms)
    return response

# Flask-Mail — SMTP relay (Resend: server smtp.resend.com, username "resend", password = API key)
app.config["MAIL_SERVER"]   = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"]     = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"]  = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
# Sender must be a verified domain address — separate from the SMTP username
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER") \
    or os.environ.get("MAIL_USERNAME") or "noreply@caremate.id"

# ── Extensions ──
csrf = CSRFProtect(app)

# Database — use a persistent Postgres in production (Vercel/Neon inject one of the
# env vars below). On Vercel the filesystem is read-only except /tmp, and /tmp is
# ephemeral, so SQLite there is NOT durable — only used as a local-dev fallback.
_default_sqlite = "sqlite:////tmp/caremate.db" if os.environ.get("VERCEL") else "sqlite:///caremate.db"
# Accept the various names Vercel Postgres / Neon use, preferring an unpooled URL
# (better for create_all / migrations) when available.
_db_url = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("POSTGRES_URL_NON_POOLING")
    or os.environ.get("DATABASE_URL_UNPOOLED")
    or os.environ.get("POSTGRES_URL")
    or os.environ.get("POSTGRES_PRISMA_URL")
    or _default_sqlite
)
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Recycle pooled connections so serverless cold starts don't reuse dead sockets.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}

from models import db, User, Assessment, VaccinationRecord, VaccineReminder, Company, Clinic, Booking, Child, LabResult, seed_clinics
db.init_app(app)

from flask_mail import Mail, Message as MailMessage
mail = Mail(app)

# Login manager
login_manager = LoginManager(app)
login_manager.login_view  = "login"
login_manager.login_message = "Please sign in to access that page."
login_manager.login_message_category = "error"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Jinja2 helpers
import json as _json
app.jinja_env.filters['from_json'] = lambda s: _json.loads(s) if s else []

def _gen_code(n=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

# Initialise DB + seed clinics on first run
with app.app_context():
    db.create_all()
    # Lightweight migration: add clinic columns introduced after the first schema
    from sqlalchemy import text as _sql_text
    for _ddl in ("ALTER TABLE clinic ADD COLUMN website VARCHAR(200)",
                 "ALTER TABLE clinic ADD COLUMN home_service BOOLEAN DEFAULT 0",
                 "ALTER TABLE vaccination_record ADD COLUMN child_id INTEGER"):
        try:
            db.session.execute(_sql_text(_ddl))
            db.session.commit()
        except Exception:
            db.session.rollback()   # column already exists
    seed_clinics()

_api_key = os.environ.get("OPENAI_API_KEY", "")
client = OpenAI(api_key=_api_key) if _api_key.startswith("sk-") else None

# D-ID Streaming Avatar (legacy — kept as fallback)
_did_key = os.environ.get("D_ID_API_KEY", "")
DID_ENABLED = bool(_did_key)
_did_active_streams = {}

def _did_headers():
    encoded = base64.b64encode(_did_key.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def _did_close_stream(stream_id, session_id):
    try:
        http_req.delete(
            f"https://api.d-id.com/talks/streams/{stream_id}",
            headers=_did_headers(),
            json={"session_id": session_id},
            timeout=8
        )
        print(f"[D-ID] Closed stream {stream_id}")
    except Exception as e:
        print(f"[D-ID] Could not close stream {stream_id}: {e}")

# ── Tavus CVI (Conversational Video Interface) ──
_tavus_key        = os.environ.get("TAVUS_API_KEY", "")
_tavus_replica_id = os.environ.get("TAVUS_REPLICA_ID", "")   # override / fallback
TAVUS_ENABLED     = bool(_tavus_key)

# Dedicated doctor stock replicas — both phoenix-4 (most photorealistic) for a real-person feel
TAVUS_MALE_REPLICA   = "r621a6013477"   # Raj - Doctor (phoenix-4)
TAVUS_FEMALE_REPLICA = "rf4e9d9790f0"   # Anna - Professional (phoenix-4)

TAVUS_BASE = "https://tavusapi.com/v2"

def _tavus_headers():
    return {"x-api-key": _tavus_key, "Content-Type": "application/json"}

# ── Condition-specific clinical questions the doctor should ask ──
# Two language variants so the doctor can use the right one
_COND_Q_ID = {   # Bahasa Indonesia
    "diabetes": (
        "Seberapa terkontrol kadar gula darah Anda? Berapa nilai HbA1c terakhir Anda? "
        "Apakah Anda menggunakan insulin atau obat minum? "
        "Sudahkah Anda mendapat vaksin influenza dan pneumokokus tahun ini?"
    ),
    "heart_disease": (
        "Apa jenis kondisi jantung yang Anda miliki — gagal jantung, penyakit arteri koroner, atau aritmia? "
        "Apakah Anda menggunakan obat pengencer darah seperti warfarin atau aspirin? "
        "Kapan terakhir Anda kontrol ke dokter jantung?"
    ),
    "lung_disease": (
        "Apakah diagnosis Anda PPOK, asma, atau kondisi paru lainnya? "
        "Seberapa sering Anda mengalami serangan atau eksaserbasi dalam setahun terakhir? "
        "Apakah Anda menggunakan inhaler setiap hari?"
    ),
    "cancer": (
        "Apa jenis kanker yang Anda miliki dan bagaimana stadium atau statusnya saat ini? "
        "Apakah Anda sedang menjalani kemoterapi, radioterapi, atau imunoterapi? "
        "Ini sangat penting karena beberapa vaksin hidup dikontraindikasikan selama pengobatan."
    ),
    "hiv": (
        "Berapa jumlah CD4 Anda yang terakhir? "
        "Apakah Anda sedang dalam terapi antiretroviral (ARV)? "
        "Ini menentukan vaksin mana yang aman untuk Anda."
    ),
    "kidney_disease": (
        "Apakah Anda sedang menjalani dialisis? Pada stadium berapa penyakit ginjal Anda? "
        "Sudahkah Anda mendapat vaksin hepatitis B sebelumnya? "
        "Pasien dengan gangguan ginjal membutuhkan dosis vaksin hepatitis B yang lebih tinggi."
    ),
    "liver_disease": (
        "Apa penyebab penyakit hati Anda — hepatitis B, hepatitis C, sirosis, atau perlemakan hati? "
        "Sudahkah Anda divaksin hepatitis A dan hepatitis B? "
        "Apakah Anda mengonsumsi alkohol secara rutin?"
    ),
    "immunocompromised": (
        "Apa yang menyebabkan kondisi imunosupresi Anda — obat kortikosteroid, transplant organ, atau penyakit autoimun? "
        "Berapa dosis dan sudah berapa lama Anda menggunakan imunosupresan? "
        "Ini sangat menentukan vaksin mana yang aman untuk Anda."
    ),
    "asplenia": (
        "Apakah limpa Anda diangkat melalui operasi, atau tidak berfungsi karena kondisi tertentu? "
        "Tanpa limpa, Anda berisiko sangat tinggi terhadap infeksi bakteri tertentu. "
        "Sudahkah Anda mendapat vaksin meningokokus, pneumokokus, dan Hib?"
    ),
    "smoking": (
        "Sudah berapa lama Anda merokok, dan berapa banyak per hari? "
        "Apakah Anda pernah mengalami pneumonia atau bronkitis berulang? "
        "Perokok memiliki risiko tinggi terhadap infeksi pneumokokus dan influenza."
    ),
    "obesity": (
        "Apakah Anda memiliki kondisi lain yang berkaitan seperti tekanan darah tinggi atau diabetes? "
        "Pasien dengan obesitas memiliki respons imun yang berbeda terhadap beberapa vaksin. "
        "Sudahkah Anda mendapat vaksin influenza tahun ini?"
    ),
}

_COND_Q_EN = {   # English
    "diabetes": (
        "How well controlled is your blood sugar — do you know your last HbA1c reading? "
        "Are you on insulin or oral medication? "
        "Have you received your influenza and pneumococcal vaccines this year?"
    ),
    "heart_disease": (
        "What type of heart condition do you have — heart failure, coronary artery disease, or arrhythmia? "
        "Are you on blood thinners such as warfarin or aspirin? "
        "When did you last see your cardiologist?"
    ),
    "lung_disease": (
        "Is your diagnosis COPD, asthma, or another lung condition? "
        "How often have you had attacks or exacerbations in the past year? "
        "Are you using a daily inhaler?"
    ),
    "cancer": (
        "What type of cancer do you have and what is its current status? "
        "Are you currently undergoing chemotherapy, radiotherapy, or immunotherapy? "
        "This is important because some live vaccines are contraindicated during treatment."
    ),
    "hiv": (
        "What is your most recent CD4 count? "
        "Are you currently on antiretroviral therapy? "
        "This determines which vaccines are safe for you."
    ),
    "kidney_disease": (
        "Are you currently on dialysis? What stage is your kidney disease? "
        "Have you received the hepatitis B vaccine before? "
        "Patients with kidney disease need a higher dose of hepatitis B vaccine."
    ),
    "liver_disease": (
        "What is the cause of your liver disease — hepatitis B, hepatitis C, cirrhosis, or fatty liver? "
        "Have you been vaccinated against hepatitis A and B? "
        "Do you consume alcohol regularly?"
    ),
    "immunocompromised": (
        "What is causing your immunosuppression — corticosteroid medications, organ transplant, or autoimmune disease? "
        "What dose and for how long have you been on immunosuppressants? "
        "This determines which vaccines are safe for you."
    ),
    "asplenia": (
        "Was your spleen surgically removed, or is it non-functional due to a condition? "
        "Without a spleen you face very high risk from certain bacterial infections. "
        "Have you received meningococcal, pneumococcal, and Hib vaccines?"
    ),
    "smoking": (
        "How long have you smoked and how many cigarettes per day? "
        "Have you experienced recurrent pneumonia or bronchitis? "
        "Smokers are at high risk for pneumococcal disease and influenza complications."
    ),
    "obesity": (
        "Do you have related conditions such as high blood pressure or diabetes? "
        "Patients with obesity can have different immune responses to some vaccines. "
        "Have you had your influenza vaccine this year?"
    ),
}

def _doctor_tavus_context(doctor, lang_override=None):
    """Build the conversational_context (system prompt) for a given doctor."""
    langs = ", ".join(doctor.get("languages", ["English"]))
    speaks_indonesian = "Bahasa Indonesia" in doctor.get("languages", [])
    # lang_override: 'indonesian' | 'english' | None (auto from doctor profile)
    use_indonesian = (lang_override == "indonesian") or (lang_override is None and speaks_indonesian)
    if use_indonesian:
        lang_instruction = (
            "LANGUAGE: Anda HARUS berbicara dalam Bahasa Indonesia. "
            "Mulai dan lanjutkan percakapan dalam Bahasa Indonesia sepanjang waktu. "
            "Jika pasien berbicara dalam bahasa Inggris, tetap jawab dalam Bahasa Indonesia kecuali pasien secara eksplisit meminta beralih ke bahasa Inggris. "
            "Untuk istilah medis, gunakan istilah Indonesia terlebih dahulu, baru istilah Inggris dalam tanda kurung jika perlu. "
        )
    else:
        lang_instruction = (
            "LANGUAGE: Speak in English throughout the consultation. "
            "If the patient speaks Indonesian, you may respond in English and offer to switch if needed. "
        )
    interruption_protocol = (
        "INTERRUPTION PROTOCOL (CRITICAL): If you detect that the patient has started speaking "
        "while you are still talking, IMMEDIATELY stop mid-sentence and say something warm like "
        "'Silakan, saya mendengarkan.' (in Indonesian) or 'Please go ahead — I'm listening.' (in English). "
        "Do NOT continue your previous sentence. Wait for the patient to finish completely before speaking again. "
        "Never talk over the patient. Their words always take priority. "
    )
    return (
        f"You are {doctor['name']}, a {doctor['specialty']} specialist at "
        f"{doctor['hospital']} in {doctor['city']}, Indonesia. "
        f"You work for the CareMate platform, a digital health tool "
        f"that helps patients in Indonesia understand their vaccination needs. "
        f"You speak {langs}. "
        f"You have {doctor.get('experience','extensive')} of clinical experience. "
        + lang_instruction
        + interruption_protocol +
        "Your expertise covers: Indonesian Ministry of Health (Kemenkes) vaccination programs; "
        "WHO and CDC vaccination guidelines; vaccine safety, efficacy, and side effects; "
        "travel vaccinations for Southeast Asia and international destinations; "
        "childhood and adult immunization schedules; vaccine interactions and contraindications; "
        "common vaccines including Hepatitis A/B, Typhoid, Influenza, COVID-19, HPV, Pneumococcal, "
        "Meningococcal, Japanese Encephalitis, Rabies, and Yellow Fever. "
        "Speak warmly and professionally. Keep answers concise and clear. "
        "For emergencies, direct patients to call 119 (Indonesian emergency services). "
        "Do not fabricate medical data — if unsure, say so and recommend consulting official guidelines."
    )

def _doctor_greeting(doctor, lang_override=None):
    """Personalised opening line for each doctor (no assessment context available)."""
    speaks_indonesian = "Bahasa Indonesia" in doctor.get("languages", [])
    use_id = (lang_override == "indonesian") or (lang_override is None and speaks_indonesian)
    if use_id:
        return (
            f"Halo! Saya {doctor['name']}, spesialis {doctor['specialty']} di platform CareMate. "
            f"Saya siap membantu Anda dengan pertanyaan seputar vaksinasi dan imunisasi hari ini. "
            f"Apa yang ingin Anda diskusikan?"
        )
    return (
        f"Hello! I'm {doctor['name']}, your {doctor['specialty']} specialist at CareMate. "
        f"I'm happy to help you with any questions about vaccinations today. "
        f"What would you like to discuss?"
    )

with open("data/vaccines.json") as f:
    VACCINE_DATA = json.load(f)

# Tavus avatar thumbnail videos (used as doctor photos in the UI)
_TAVUS_VIDEO_MALE   = "https://cdn.replica.tavus.io/39476/8558b349.mp4"    # Raj - Doctor (phoenix-4)
_TAVUS_VIDEO_FEMALE = "https://cdn.replica.tavus.io/39895/8c44fce6.mp4"  # Anna - Professional (phoenix-4)

DOCTORS = [
    {"id": 1, "did_photo": "https://images.unsplash.com/photo-1622902046580-2b47f47f5471?w=512&q=85&auto=format&fit=facearea&facepad=2.8", "name": "Dr. Budi Santoso", "specialty": "Internal Medicine & Infectious Disease", "hospital": "RS Pondok Indah", "city": "Jakarta Selatan", "lat": -6.2615, "lng": 106.7890, "rating": 4.9, "reviews": 312, "fee": "Free", "available": True, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "15 years", "slots": ["09:00", "10:30", "14:00", "15:30"], "gender": "male", "tts_voice": "onyx"},
    {"id": 2, "did_photo": "https://images.unsplash.com/photo-1594824476967-48c8b964273f?w=512&q=85&auto=format&fit=facearea&facepad=2.8", "name": "Dr. Sari Dewi, Sp.PD", "specialty": "Vaccinology & Travel Medicine", "hospital": "RSUP Cipto Mangunkusumo", "city": "Jakarta Pusat", "lat": -6.1924, "lng": 106.8455, "rating": 4.8, "reviews": 487, "fee": "Free", "available": True, "languages": ["Bahasa Indonesia", "English", "Dutch"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "18 years", "slots": ["08:00", "11:00", "13:00"], "gender": "female", "tts_voice": "nova"},
    {"id": 3, "name": "Dr. Ahmad Fauzi, Sp.A", "specialty": "Pediatric & Adult Immunization", "hospital": "RS Siloam Hospitals", "city": "Tangerang", "lat": -6.2388, "lng": 106.6402, "rating": 4.7, "reviews": 256, "fee": "Rp 200.000", "available": False, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "12 years", "slots": ["10:00", "14:30", "16:00"], "gender": "male", "tts_voice": "echo"},
    {"id": 4, "name": "Dr. Maya Kusuma, M.D.", "specialty": "Family Medicine & Preventive Health", "hospital": "Klinik Pratama SehatKu", "city": "Bekasi", "lat": -6.2349, "lng": 106.9896, "rating": 4.6, "reviews": 198, "fee": "Rp 150.000", "available": False, "languages": ["Bahasa Indonesia"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "8 years", "slots": ["09:30", "11:30", "15:00", "17:00"], "gender": "female", "tts_voice": "shimmer"},
    {"id": 5, "name": "Dr. Hendro Wibowo, Sp.PD", "specialty": "Internal Medicine & Immunology", "hospital": "RS Medistra", "city": "Jakarta Selatan", "lat": -6.2297, "lng": 106.8261, "rating": 4.9, "reviews": 541, "fee": "Rp 350.000", "available": False, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "22 years", "slots": ["Next week"], "gender": "male", "tts_voice": "onyx"},
    {"id": 6, "name": "Dr. Ratna Puspita, Sp.MK", "specialty": "Clinical Microbiology & Vaccines", "hospital": "RS Hermina Jatinegara", "city": "Jakarta Timur", "lat": -6.2131, "lng": 106.8703, "rating": 4.7, "reviews": 173, "fee": "Rp 200.000", "available": False, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "10 years", "slots": ["08:30", "12:00", "16:30"], "gender": "female", "tts_voice": "nova"},
    {"id": 7, "name": "Dr. Irwan Prasetyo, PhD", "specialty": "Epidemiology & Travel Medicine", "hospital": "RS Premier Bintaro", "city": "Tangerang Selatan", "lat": -6.3013, "lng": 106.7312, "rating": 4.8, "reviews": 329, "fee": "Rp 280.000", "available": False, "languages": ["Bahasa Indonesia", "English", "German"], "photo": _TAVUS_VIDEO_MALE, "experience": "14 years", "slots": ["09:00", "13:30", "15:00"], "gender": "male", "tts_voice": "echo"},
    {"id": 8, "name": "Dr. Dian Rahayu, Sp.KK", "specialty": "Dermatology & HPV Specialist", "hospital": "Klinik Vaksin Indonesia", "city": "Surabaya", "lat": -7.2574, "lng": 112.7521, "rating": 4.6, "reviews": 215, "fee": "Rp 175.000", "available": False, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "9 years", "slots": ["10:30", "14:00", "16:00"], "gender": "female", "tts_voice": "shimmer"}
]

# ── Rich clinical interaction data: condition → vaccine → structured fields ──
# Used to power the "How Your Condition Interacts" cards on the results page
VACCINE_CLINICAL_DETAIL = {
    "diabetes": {
        "influenza": {
            "condition_causes": "Chronic hyperglycaemia impairs neutrophil chemotaxis and phagocytosis, reducing the first-line defence against influenza A/B viruses in the upper airway.",
            "disease_worsens": "Influenza triggers a surge in counter-regulatory hormones (cortisol, glucagon) causing acute hyperglycaemia; hospitalisation rates for diabetics with flu are 3× the non-diabetic baseline.",
            "plain_language": "Diabetics face 3× the normal flu hospitalisation risk. A flu episode then makes blood sugar harder to control — vaccination breaks this dangerous cycle.",
            "if_not_vaccinated": "Unvaccinated diabetics risk flu-induced hyperglycaemic crises, potentially progressing to diabetic ketoacidosis (DKA) requiring ICU care. Cardiovascular events during flu illness are also significantly elevated.",
            "why_now": "Annual flu vaccination reduces diabetes-related hospitalisations by up to 79% (NEJM data). Every missed season represents cumulative, avoidable risk in a population already managing a chronic condition."
        },
        "pneumococcal": {
            "condition_causes": "Elevated blood glucose directly impairs macrophage oxidative burst and reduces complement-mediated bacterial clearance, leaving the lower respiratory tract vulnerable to S. pneumoniae.",
            "disease_worsens": "Invasive pneumococcal disease triggers systemic inflammation and bacteraemia that destabilises glycaemic control; sepsis-related insulin resistance can persist for weeks post-recovery.",
            "plain_language": "Diabetics are 3–5× more likely to develop invasive pneumococcal pneumonia. The infection then makes glucose control significantly harder — a vicious cycle.",
            "if_not_vaccinated": "Without vaccination, S. pneumoniae can progress from lobar pneumonia to septicaemia and meningitis. For diabetics, post-sepsis insulin resistance and multi-organ involvement are well-documented outcomes.",
            "why_now": "PCV20 provides lifelong protection in a single dose. Kemenkes RI and ADA both list it as mandatory for all diabetics from age 19. There is no benefit to delaying."
        },
        "hepatitis_b": {
            "condition_causes": "Diabetics on insulin face repeated percutaneous exposures. Impaired T-cell responses also reduce the ability to clear HBV once infected.",
            "disease_worsens": "HBV-related liver damage impairs gluconeogenesis regulation, worsening glycaemic variability. Cirrhosis from HBV dramatically complicates diabetes management.",
            "plain_language": "Insulin use creates direct HBV exposure risk. HBV infection then makes blood sugar regulation significantly harder — vaccination eliminates the first step entirely.",
            "if_not_vaccinated": "Unvaccinated diabetics on insulin have documented outbreaks of HBV transmission. Chronic HBV leads to cirrhosis in ~20% of cases, creating an irreversible secondary burden.",
            "why_now": "WHO and ACIP mandate HBV vaccination for all adults with diabetes under 60. A 3-dose series over 6 months eliminates a highly preventable, serious risk."
        },
        "zoster": {
            "condition_causes": "Diabetes weakens T-cell-mediated immune surveillance, allowing the latent varicella-zoster virus (dormant in dorsal root ganglia) to reactivate as shingles.",
            "disease_worsens": "Shingles-associated acute pain triggers cortisol release that directly raises blood glucose; post-herpetic neuralgia (lasting months) creates chronic physiological stress that destabilises HbA1c.",
            "plain_language": "Diabetics face 1.84× the normal risk of shingles reactivation. A shingles episode then makes diabetes harder to control — vaccination breaks this clinical cycle.",
            "if_not_vaccinated": "Without vaccination the dormant varicella-zoster virus may reactivate as shingles, potentially causing severe burning nerve pain for months (post-herpetic neuralgia), deteriorating glycaemic control and potentially leading to CVD events.",
            "why_now": "The recombinant herpes zoster vaccine provides >90% protection — the highest efficacy of any adult vaccine. Comorbidities increase reactivation risk; delay is unnecessary exposure to one of the most painful vaccine-preventable diseases."
        },
        "covid19": {
            "condition_causes": "Hyperglycaemia enhances ACE2 receptor expression and facilitates viral replication in pulmonary and vascular tissue, while blunting the innate antiviral cytokine response.",
            "disease_worsens": "SARS-CoV-2 directly attacks pancreatic beta cells, worsening insulin secretion. Post-COVID insulin resistance has been documented in previously well-controlled patients for up to 12 months.",
            "plain_language": "Diabetics face 3× higher ICU admission risk from COVID-19. The virus can also directly damage the pancreas, making diabetes worse even after recovery.",
            "if_not_vaccinated": "Unvaccinated diabetics with COVID-19 face substantially higher mortality, cytokine storm risk, and new-onset hyperglycaemic crises requiring intensive insulin management.",
            "why_now": "Updated booster formulations match current circulating variants. Vaccination reduces severe COVID-19 mortality by >85% in diabetics (Lancet 2023). No clinical reason to delay."
        },
        "rsv": {
            "condition_causes": "Hyperglycaemia impairs innate immune cell function (neutrophil phagocytosis, NK cell activity) that normally contains RSV infection at the upper airway before it progresses to the lower respiratory tract.",
            "disease_worsens": "RSV lower respiratory tract infection causes systemic stress responses — fever, hypoxia, inflammatory cytokines — that drive acute hyperglycaemic crises and make diabetes control erratic for weeks after recovery.",
            "plain_language": "Diabetes slows the immune system's ability to stop RSV spreading to the lungs. When that happens, the infection makes blood sugar control much harder and can land a diabetic patient in hospital.",
            "if_not_vaccinated": "Diabetic adults hospitalised for RSV pneumonia face 3× higher rates of acute hyperglycaemic complications, extended hospital stays, and secondary infections. Recovery and glucose stabilisation can take weeks.",
            "why_now": "PAPDI Kartu Vaksinasi Dewasa 2025 lists RSV as a priority vaccine for adults with diabetes melitus alongside Herpes Zoster, Influenza, and Pneumococcal. Vaccination is most effective when given before respiratory season, ideally alongside flu vaccination."
        }
    },
    "heart_disease": {
        "influenza": {
            "condition_causes": "Inflammatory cytokines from influenza (IL-6, TNF-α) destabilise atherosclerotic plaques and promote thrombosis. Tachycardia from fever increases myocardial oxygen demand in already-compromised hearts.",
            "disease_worsens": "Influenza triggers acute myocardial infarction (AMI) in patients with coronary artery disease; the risk of AMI is 6× higher in the week following flu diagnosis.",
            "plain_language": "Flu is a cardiac trigger. Heart disease patients face 6× AMI risk in the week after flu infection — vaccination dramatically reduces this acute threat.",
            "if_not_vaccinated": "Unvaccinated heart disease patients risk flu-precipitated acute MI, decompensated heart failure requiring hospitalisation, and cardiogenic shock. Winter flu seasons show measurable peaks in cardiac mortality.",
            "why_now": "Flu vaccination reduces cardiovascular mortality by 15–45% in cardiac patients (Cochrane 2023). It is among the most cost-effective cardiac interventions available."
        },
        "pneumococcal": {
            "condition_causes": "Cardiac dysfunction reduces pulmonary perfusion and mucociliary clearance, creating ideal conditions for S. pneumoniae colonisation and progression to invasive disease.",
            "disease_worsens": "Pneumococcal bacteraemia causes direct myocardial inflammation, worsens existing heart failure through volume overload and hypoxia, and triggers fatal arrhythmias.",
            "plain_language": "Heart failure reduces the lungs' ability to fight bacterial infection. Pneumonia then directly stresses the heart — this bidirectional risk is why vaccination is listed as cardiac standard of care.",
            "if_not_vaccinated": "Pneumococcal pneumonia is a leading precipitant of acute decompensated heart failure hospitalisation. Sepsis-related haemodynamic stress carries high mortality in cardiac patients.",
            "why_now": "ESC and AHA cardiac guidelines list pneumococcal vaccination as Class I recommendation. It is a single dose with lifelong protection — the risk-benefit ratio is unambiguous."
        },
        "zoster": {
            "condition_causes": "Cardiovascular disease is associated with chronic low-grade inflammation that impairs T-cell-mediated immunity — the primary defence against VZV reactivation from dorsal root ganglia.",
            "disease_worsens": "Shingles triggers a strong systemic inflammatory response (elevated IL-6, CRP) that destabilises atherosclerotic plaques, increasing the 1-year risk of myocardial infarction and stroke by up to 2.4×.",
            "plain_language": "Heart disease weakens the immune defences that keep shingles dormant. If shingles reactivates, the inflammation it triggers can in turn cause a heart attack or stroke.",
            "if_not_vaccinated": "Unvaccinated heart disease patients face both the direct pain and neuralgia of shingles and an elevated risk of a cardiac event in the weeks following an outbreak.",
            "why_now": "PAPDI Satgas Imunisasi Dewasa 2025 recommends Herpes Zoster Rekombinan (2 doses) for all adults with penyakit jantung regardless of age. Vaccinate now before an episode occurs."
        },
        "rsv": {
            "condition_causes": "Cardiac dysfunction — reduced cardiac output, pulmonary congestion — impairs immune cell trafficking to the lungs, while the inflammatory response to RSV infection triggers systemic cytokine release that destabilises cardiac function.",
            "disease_worsens": "RSV-triggered inflammation elevates troponin, worsens heart failure, and increases thrombotic risk. Studies show a 2–3× increased risk of acute cardiac events in the 30 days following RSV lower respiratory tract infection.",
            "plain_language": "RSV causes severe lung inflammation that directly stresses the heart. In patients with existing heart disease, an RSV infection can trigger heart failure decompensation or even a heart attack.",
            "if_not_vaccinated": "Adults with cardiovascular disease hospitalised for RSV have 30-day mortality rates of 6–8% — comparable to influenza. Heart failure patients face the highest risk of requiring ICU admission.",
            "why_now": "PAPDI Kartu Vaksinasi Dewasa 2025 lists RSV as a priority vaccine for adults with penyakit kardiovaskular. A single dose provides protection for the season — vaccinate before respiratory virus season (April–August in Indonesia)."
        }
    },
    "lung_disease": {
        "influenza": {
            "condition_causes": "COPD and asthma patients have heightened airway inflammation at baseline. Influenza compounds this with acute bronchospasm and mucus hypersecretion, reducing FEV1 by up to 40%.",
            "disease_worsens": "Flu-triggered COPD exacerbations are the leading cause of acute respiratory failure hospitalisation; exacerbations also accelerate the irreversible lung function decline characteristic of COPD.",
            "plain_language": "Flu in a COPD patient is like throwing fuel on an already burning fire. Each exacerbation permanently worsens lung capacity — vaccination reduces exacerbation rate by ~60%.",
            "if_not_vaccinated": "Unvaccinated COPD patients face near-certain annual exacerbations that accelerate disease progression, require systemic steroids (which worsen bone density and glucose control), and can necessitate ventilatory support.",
            "why_now": "GOLD COPD guidelines mandate annual flu vaccination as the single most effective pharmacological intervention for reducing exacerbations. No patient with COPD should be unvaccinated."
        },
        "pneumococcal": {
            "condition_causes": "Structural lung damage in COPD allows S. pneumoniae to colonise the lower airways more easily. Impaired mucociliary clearance prevents bacterial expulsion before infection takes hold.",
            "disease_worsens": "Pneumococcal pneumonia causes cavitation and alveolar destruction in already-damaged lungs, accelerating transition to respiratory failure and oxygen dependence.",
            "plain_language": "COPD patients have physical lung damage that gives pneumococcal bacteria a foothold. Pneumonia then destroys more lung tissue — vaccination protects irreplaceable pulmonary reserve.",
            "if_not_vaccinated": "Pneumococcal pneumonia in COPD patients carries 30-day mortality of 10–15%. Survivors often have permanently reduced lung function and increased oxygen dependence.",
            "why_now": "GINA and GOLD both mandate pneumococcal vaccination. PCV20 covers the 20 most virulent serotypes in a single lifelong dose. Delay has no clinical justification."
        },
        "zoster": {
            "condition_causes": "Chronic lung disease (COPD, asthma) requires repeated or long-term corticosteroid use, which suppresses T-cell immunity and allows latent VZV to reactivate.",
            "disease_worsens": "Thoracic shingles (T4–T6 dermatomes) causes severe chest-wall pain that restricts breathing and can precipitate acute exacerbations in COPD patients. Systemic illness further depletes pulmonary reserve.",
            "plain_language": "Many lung disease patients use inhalers with steroids, which lower the immune barrier that keeps shingles dormant. A shingles episode on the chest wall can make breathing much harder.",
            "if_not_vaccinated": "A shingles exacerbation in a COPD patient can require hospitalisation and oxygen therapy. Post-herpetic neuralgia causes chronic thoracic pain limiting effective respiration long-term.",
            "why_now": "PAPDI Satgas Imunisasi Dewasa 2025 recommends Herpes Zoster Rekombinan (2 doses) for all adults with penyakit paru kronik regardless of age. The vaccine is non-live and safe with inhaled corticosteroids."
        },
        "rsv": {
            "condition_causes": "Chronic lung disease (COPD, asthma) involves persistent airway inflammation and impaired mucociliary clearance — the first line of defence against RSV. The virus exploits damaged epithelium to establish deep lower respiratory tract infection.",
            "disease_worsens": "RSV is the leading viral cause of COPD exacerbations in adults, comparable to influenza in severity. A single RSV exacerbation accelerates lung function decline (FEV₁ loss) and increases the risk of further exacerbations for up to 6 months.",
            "plain_language": "RSV is a major trigger of the flare-ups that lung disease patients fear. It can make COPD or asthma dramatically worse for weeks — sometimes requiring oxygen, steroids, or hospitalisation.",
            "if_not_vaccinated": "Adults with COPD who get RSV face hospitalisation rates 5× higher than healthy adults. Many require ICU-level respiratory support. Those who recover often have permanently worsened lung function.",
            "why_now": "PAPDI Kartu Vaksinasi Dewasa 2025 lists RSV as a priority vaccine for adults with penyakit paru alongside Herpes Zoster, Influenza, and Pneumococcal. Vaccinate during a stable period — not during an active exacerbation."
        }
    },
    "hiv": {
        "zoster": {
            "condition_causes": "HIV-induced CD4+ T-cell depletion removes the primary immune brake on VZV reactivation. At CD4 counts below 200 cells/μL, risk of shingles approaches 30% annually.",
            "disease_worsens": "Shingles in HIV patients can disseminate to involve internal organs (visceral zoster), the eye (zoster ophthalmicus causing blindness), and the brain (varicella encephalitis).",
            "plain_language": "HIV leaves the immune system unable to keep the dormant shingles virus suppressed. A shingles episode in HIV can spread internally in ways that are life-threatening — vaccination provides critical protection.",
            "if_not_vaccinated": "Unvaccinated HIV patients with CD4 >200 face high risk of recurrent, painful shingles. Below CD4 200, disseminated VZV carries significant mortality and can cause permanent neurological damage.",
            "why_now": "The recombinant herpes zoster vaccine is recommended for HIV+ adults regardless of CD4 count. It provides >85% protection and does not contain live virus, making it safe even in immunocompromised patients."
        },
        "pneumococcal": {
            "condition_causes": "HIV depletes the splenic memory B-cells responsible for anti-pneumococcal antibody production, creating a 40× higher risk of invasive pneumococcal disease versus the general population.",
            "disease_worsens": "Pneumococcal bacteraemia triggers a cytokine cascade that drives HIV replication, potentially causing a transient but significant CD4 count drop and measurable viral load spike.",
            "plain_language": "HIV essentially removes the immune memory that normally protects against pneumococcal bacteria. Infection then directly worsens HIV control — a medically documented two-way harm.",
            "if_not_vaccinated": "HIV-positive adults have 40× the risk of invasive pneumococcal disease. Bacteraemia progresses faster and is harder to treat due to compromised immune function.",
            "why_now": "All major HIV treatment guidelines (DHHS, EACS, WHO) mandate PCV vaccination immediately upon HIV diagnosis. Early vaccination is more immunogenic before further CD4 decline."
        }
    },
    "cancer": {
        "influenza": {
            "condition_causes": "Chemotherapy depletes neutrophils and lymphocytes, eliminating the immune cells that normally contain influenza infection at the mucosal surface before dissemination.",
            "disease_worsens": "Flu in a chemotherapy patient can delay treatment cycles, cause irreversible lung damage, and trigger secondary bacterial superinfection — all of which directly impact cancer prognosis.",
            "plain_language": "Chemotherapy wipes out the immune cells that fight flu. A flu infection can pause cancer treatment for weeks — vaccination protects both the patient's health and their treatment timeline.",
            "if_not_vaccinated": "Flu in an immunocompromised cancer patient carries case fatality rates up to 40% when complicated by pneumonia. Treatment interruptions caused by flu-related hospitalisation worsen oncological outcomes.",
            "why_now": "ASCO and ESMO mandate annual flu vaccination for all cancer patients on systemic therapy. Timing around chemotherapy cycles matters — a clinical pharmacist can advise on the optimal window."
        },
        "zoster": {
            "condition_causes": "Chemotherapy and radiation-induced lymphocyte depletion remove the immune control keeping latent VZV dormant in dorsal root ganglia, triggering reactivation as shingles.",
            "disease_worsens": "Shingles in cancer patients can disseminate to internal organs (lungs, liver, CNS), become haemorrhagic, and cause fatal complications — all while delaying cancer treatment.",
            "plain_language": "Cancer treatment suppresses exactly the immune cells that prevent shingles. A shingles outbreak can hospitalise a patient, interrupt chemotherapy, and cause permanent nerve damage.",
            "if_not_vaccinated": "Disseminated varicella-zoster in haematological malignancy patients carries mortality rates of 5–10%. Visceral involvement requires IV antivirals and intensive care — entirely preventable.",
            "why_now": "PAPDI 2025 and ASCO recommend the recombinant herpes zoster vaccine (non-live) for oncology patients at any age. Ideally vaccinate before starting immunosuppressive therapy for best immune response."
        }
    },
    "kidney_disease": {
        "zoster": {
            "condition_causes": "Chronic kidney disease causes uraemia-related immune dysfunction — reduced lymphocyte count and impaired T-cell responses — proportional to GFR decline, allowing VZV dormancy to break.",
            "disease_worsens": "Shingles in CKD patients can cause disseminated skin lesions, visceral involvement, and VZV nephritis that accelerates renal function decline. Antiviral dosing must be adjusted for eGFR.",
            "plain_language": "As the kidneys lose function, so does the immune system. Shingles is more frequent and more severe in kidney disease patients, and the antivirals used to treat it require careful dose adjustment.",
            "if_not_vaccinated": "CKD patients who develop shingles face longer duration of acute pain, higher rates of post-herpetic neuralgia, and potential worsening of renal function from viral nephritis.",
            "why_now": "PAPDI Satgas Imunisasi Dewasa 2025 recommends Herpes Zoster Rekombinan (2 doses) for all adults with gagal ginjal / penyakit ginjal kronik regardless of age. The vaccine is safe with all renal replacement therapies."
        }
    },
    "liver_disease": {
        "zoster": {
            "condition_causes": "Chronic liver disease (cirrhosis, viral hepatitis) impairs Kupffer cell function and depletes NK cells and CD4+ T lymphocytes — key components of anti-VZV surveillance.",
            "disease_worsens": "Hepatic impairment reduces antiviral drug metabolism; treatment of shingles requires adjusted dosing. VZV can also cause hepatitis flares in already compromised livers.",
            "plain_language": "A diseased liver cannot process antivirals normally and cannot maintain the immune cells that keep shingles dormant. Shingles in liver disease can be more difficult to treat and more prolonged.",
            "if_not_vaccinated": "Shingles in chronic liver disease can trigger immune-mediated hepatitis flares. If antiviral therapy is required, hepatotoxicity risk limits options. Post-herpetic neuralgia is more frequent and more severe.",
            "why_now": "PAPDI Satgas Imunisasi Dewasa 2025 recommends Herpes Zoster Rekombinan (2 doses) for all adults with penyakit hati kronik regardless of age. Vaccinate while liver function is still adequate for immunogenicity."
        }
    },
    "immunocompromised": {
        "zoster": {
            "condition_causes": "Immunosuppression — whether from medications (corticosteroids, biologics, DMARDs), organ transplant, or primary immune deficiency — directly removes the T-cell surveillance that prevents VZV reactivation.",
            "disease_worsens": "In immunocompromised patients, shingles can disseminate beyond dermatomes to involve the lungs (VZV pneumonitis), liver (VZV hepatitis), brain (VZV encephalitis), and eyes — each potentially fatal.",
            "plain_language": "When the immune system is suppressed by medication or disease, the chickenpox virus hiding in your nerves can wake up and cause severe, widespread shingles affecting multiple organs.",
            "if_not_vaccinated": "Disseminated zoster in severely immunocompromised patients has mortality rates of up to 10–15%. Recombinant vaccination reduces this risk by >90% even in this population.",
            "why_now": "PAPDI Satgas Imunisasi Dewasa 2025 specifically recommends Herpes Zoster Rekombinan (2 doses) for all immunocompromised adults. Because the vaccine is non-live, it is safe even during active immunosuppression."
        },
        "rsv": {
            "condition_causes": "Immunosuppression eliminates the CD8+ cytotoxic T-cell response that normally clears RSV from the lower respiratory tract within 1–2 weeks, allowing prolonged viral replication and severe pneumonitis.",
            "disease_worsens": "RSV in immunocompromised patients can cause protracted lower respiratory tract disease lasting weeks, requiring supplemental oxygen, hospitalisation, and in severe cases mechanical ventilation. Secondary bacterial pneumonia is common.",
            "plain_language": "A suppressed immune system cannot fight off RSV quickly. What is a mild cold in healthy adults can become a serious lung infection requiring hospital care in immunocompromised patients.",
            "if_not_vaccinated": "RSV is one of the leading causes of respiratory hospitalisation and death in transplant recipients and patients on long-term immunosuppression. Mortality from RSV lower respiratory tract disease in this population approaches 30–40%.",
            "why_now": "PAPDI Kartu Vaksinasi Dewasa 2025 lists RSV as a priority vaccine for immunocompromised adults alongside Herpes Zoster, Influenza, and Pneumococcal. Vaccinate before initiating or during stable immunosuppression for best protection."
        }
    }
}

VACCINE_DISEASE_RELATIONS = {
    "diabetes": {
        "influenza": "People with diabetes have impaired immune responses and are 3x more likely to be hospitalized from flu complications. Flu can cause dangerous blood sugar spikes.",
        "pneumococcal": "Diabetes significantly increases susceptibility to invasive pneumococcal disease. High glucose levels impair white blood cell function, enabling bacterial spread.",
        "hepatitis_b": "Diabetes patients on insulin needles face higher hepatitis B exposure risk. Additionally, liver damage from HBV can worsen glucose metabolism.",
        "covid19": "Diabetes is a major risk factor for severe COVID-19. Hyperglycemia enhances viral replication and causes cytokine storms.",
        "zoster": "Diabetes weakens T-cell surveillance, allowing the latent varicella-zoster virus to reactivate as shingles. PAPDI 2025 recommends herpes zoster vaccine for all diabetic adults regardless of age.",
        "rsv": "Diabetes impairs neutrophil and macrophage function, slowing viral clearance in the lower respiratory tract. RSV infection in diabetics can trigger acute hyperglycaemic crises and pneumonia requiring hospitalisation."
    },
    "heart_disease": {
        "influenza": "Influenza can trigger myocardial infarction. Inflammatory cytokines from flu destabilize atherosclerotic plaques and increase clot formation.",
        "pneumococcal": "Pneumococcal bacteria can directly infect cardiac tissue and worsen existing heart failure through sepsis-induced hemodynamic stress.",
        "covid19": "COVID-19 causes myocarditis and thromboembolism. Patients with existing heart disease face 5x higher mortality risk.",
        "zoster": "Cardiac dysfunction reduces immune surveillance. Shingles in heart disease patients can trigger systemic inflammation and acute cardiac events. PAPDI 2025 recommends herpes zoster vaccine for all adults with heart disease.",
        "rsv": "RSV triggers intense airway inflammation and systemic cytokine release that stresses an already compromised cardiovascular system. Heart failure decompensation and acute coronary events following RSV infection are well documented in adults with cardiac disease."
    },
    "lung_disease": {
        "influenza": "COPD and asthma patients experience severe flu exacerbations requiring hospitalization. The airway inflammation compounds existing bronchospasm.",
        "pneumococcal": "Lung disease patients have colonized airways that allow S. pneumoniae to cause severe pneumonia with inadequate clearance.",
        "covid19": "Pre-existing lung damage leaves less pulmonary reserve. COVID-19 pneumonia can be life-threatening.",
        "zoster": "Chronic lung disease reduces respiratory reserve; a shingles episode involving thoracic nerves or causing systemic illness can precipitate pulmonary exacerbations. PAPDI 2025 recommends herpes zoster vaccine for all adults with chronic lung disease.",
        "rsv": "RSV is a primary trigger of COPD and asthma exacerbations in adults. Airway inflammation from RSV compounds pre-existing bronchospasm and mucus hypersecretion, often requiring hospitalization and mechanical ventilation in severe cases."
    },
    "hiv": {
        "influenza": "HIV-induced CD4+ T-cell depletion dramatically weakens antiviral immunity, making flu complications highly dangerous.",
        "pneumococcal": "HIV patients have 40x higher risk of invasive pneumococcal disease due to impaired opsonophagocytosis.",
        "hepatitis_b": "HIV/HBV co-infection accelerates progression to cirrhosis and liver failure due to shared transmission routes and immune suppression.",
        "zoster": "HIV reactivates latent varicella-zoster virus. Shingles in HIV patients can cause severe, disseminated, and vision-threatening disease. PAPDI 2025 recommends herpes zoster vaccine whether or not the patient is on ARV."
    },
    "kidney_disease": {
        "influenza": "Kidney disease causes uremia-induced immune dysfunction. Flu can trigger acute kidney injury on chronic kidney disease.",
        "hepatitis_b": "Hemodialysis patients face high HBV exposure. Kidney disease also impairs the liver's role in viral clearance.",
        "pneumococcal": "Nephrotic syndrome and CKD impair antibody production, making bacterial infections particularly dangerous.",
        "zoster": "Chronic kidney disease impairs cellular immunity proportional to GFR decline, increasing VZV reactivation risk. PAPDI 2025 recommends herpes zoster vaccine for all adults with kidney disease."
    },
    "liver_disease": {
        "influenza": "Liver disease impairs immune clearance; flu can precipitate acute-on-chronic liver failure.",
        "hepatitis_a": "Superimposed hepatitis A infection in chronic liver disease patients carries 70× higher mortality than in healthy adults.",
        "hepatitis_b": "Chronic liver disease from any cause is worsened by HBV co-infection. Vaccination prevents additional hepatic insult.",
        "zoster": "Chronic liver disease impairs T-cell-mediated immunity, enabling VZV reactivation. PAPDI 2025 recommends herpes zoster vaccine for all adults with chronic liver disease."
    },
    "pregnancy": {
        "influenza": "Pregnancy alters immune tolerance. Flu in pregnancy increases preterm birth risk by 4x and maternal ICU admission.",
        "tdap": "Maternal Tdap vaccination transfers protective antibodies to the newborn before they can be immunized at 2 months.",
        "covid19": "Pregnancy is a risk factor for severe COVID-19. Preterm delivery rates double with COVID-19 infection during pregnancy."
    },
    "cancer": {
        "influenza": "Chemotherapy destroys immune cells. Flu can be life-threatening in immunocompromised cancer patients.",
        "pneumococcal": "Cancer treatment eliminates protective antibodies. Bacterial pneumonia is a leading cause of cancer treatment-related death.",
        "zoster": "Cancer and chemotherapy reactivate latent VZV. Shingles can disseminate to internal organs in immunocompromised patients. PAPDI 2025 recommends herpes zoster vaccine for oncology patients.",
        "hepatitis_b": "Immunosuppressive chemotherapy can reactivate HBV, causing fulminant hepatitis and liver failure."
    },
    "immunocompromised": {
        "influenza": "Any degree of immune suppression markedly increases the risk of severe influenza and secondary bacterial pneumonia.",
        "pneumococcal": "Immunocompromised patients cannot mount adequate antibody responses to encapsulated bacteria like S. pneumoniae.",
        "zoster": "Immune suppression allows latent VZV to reactivate. The recombinant herpes zoster vaccine is safe for immunocompromised patients and is specifically recommended by PAPDI 2025."
    },
    "asplenia": {
        "pneumococcal": "The spleen filters encapsulated bacteria from blood. Asplenia leads to overwhelming post-splenectomy infection (OPSI) — pneumococcal sepsis with 50–70% mortality.",
        "meningococcal": "Without splenic filtration, Neisseria meningitidis causes fulminant meningococcaemia rapidly. Vaccination is mandatory post-splenectomy.",
        "zoster": "Asplenic patients have impaired cellular and humoral immunity, increasing susceptibility to disseminated VZV infections. PAPDI 2025 recommends herpes zoster vaccine."
    }
}


def calculate_risk_score(data):
    """
    Clinically calibrated risk scoring based on CDC/WHO immunization priority guidelines.
    Denominator is set to 14 (realistic worst-case for a single-condition patient) so that
    high-risk profiles like 65+ with diabetes score in the 70-85% range rather than 32%.
    Interaction bonuses reflect known multiplicative risk relationships.
    """
    score = 0
    factors = []

    age = int(data.get("age", 30))
    if age >= 65:
        score += 5   # CDC/WHO place 65+ in highest-priority immunization group
        factors.append({"factor": "Age ≥ 65", "points": 5, "icon": "👴"})
    elif age >= 50:
        score += 3
        factors.append({"factor": "Age 50–64", "points": 3, "icon": "🧑"})
    else:
        score += 1
        factors.append({"factor": "Age 18–49", "points": 1, "icon": "🧑"})

    conditions = data.get("conditions", [])
    condition_map = VACCINE_DATA["risk_factors"]
    for cond in conditions:
        if cond in condition_map:
            w = condition_map[cond]["weight"]
            score += w
            factors.append({"factor": condition_map[cond]["label"], "points": w, "icon": "⚠️"})

    if data.get("pregnant") == "yes":
        score += 4
        factors.append({"factor": "Pregnancy", "points": 4, "icon": "🤰"})

    travel = data.get("travel_regions", [])
    if len(travel) > 0:
        score += 2
        factors.append({"factor": "International Travel", "points": 2, "icon": "✈️"})

    if data.get("vaccinated_recently") == "no":
        score += 3   # Outdated vaccination is an independent urgent risk factor
        factors.append({"factor": "No recent vaccinations", "points": 3, "icon": "💉"})

    # ── Clinical interaction bonuses ──
    # Age 65+ with ANY chronic condition → immune senescence compounds vaccine-preventable risk
    high_risk_conditions = {"diabetes","heart_disease","lung_disease","cancer","hiv",
                            "kidney_disease","liver_disease","immunocompromised","asplenia"}
    has_chronic = bool(high_risk_conditions & set(conditions))

    if age >= 65 and has_chronic:
        score += 3
        factors.append({"factor": "Age + chronic condition (compounded risk)", "points": 3, "icon": "🔺"})
    elif age >= 50 and has_chronic:
        score += 1
        factors.append({"factor": "Age 50+ with chronic condition", "points": 1, "icon": "🔺"})

    # No vaccination + age 65+ = urgent catch-up needed
    if data.get("vaccinated_recently") == "no" and age >= 65:
        score += 2
        factors.append({"factor": "Overdue vaccines at high-risk age", "points": 2, "icon": "⏰"})

    # Denominator: calibrated so that 65+ + one chronic condition + no vacc hits ~75-80%
    max_score = 18
    pct = min(100, int((score / max_score) * 100))

    if pct >= 65:
        level = "High Risk"
        color = "#FF4757"
        emoji = "🔴"
        advice = "Immediate vaccination consultation strongly recommended. Several vaccines are urgently needed."
    elif pct >= 38:
        level = "Moderate Risk"
        color = "#FFA502"
        emoji = "🟡"
        advice = "Multiple vaccines are overdue or strongly recommended for your profile."
    else:
        level = "Low Risk"
        color = "#2ED573"
        emoji = "🟢"
        advice = "Stay up to date with routine vaccines. Annual flu shot recommended for all adults."

    # Prevention Score — same math, positive framing (higher = better protected)
    prevention_score = 100 - pct
    if prevention_score >= 63:
        prevention_label, prevention_color = "Good", "#2ED573"
    elif prevention_score >= 36:
        prevention_label, prevention_color = "Fair", "#FFA502"
    else:
        prevention_label, prevention_color = "Needs Attention", "#FF4757"

    return {
        "score": score,
        "percentage": pct,
        "level": level,
        "color": color,
        "emoji": emoji,
        "advice": advice,
        "factors": factors,
        "prevention_score": prevention_score,
        "prevention_label": prevention_label,
        "prevention_color": prevention_color
    }


def get_recommended_vaccines(data):
    age = int(data.get("age", 30))
    conditions = data.get("conditions", [])
    pregnant = data.get("pregnant") == "yes"
    travel_regions = data.get("travel_regions", [])
    all_vaccines = VACCINE_DATA["vaccines"]
    recommended = []

    for key, v in all_vaccines.items():
        include = False
        reasons = []
        priority = v.get("priority", "routine")

        age_min, age_max = v["age_range"]
        if not (age_min <= age <= age_max):
            continue

        if "all" in v["conditions"]:
            include = True
            if key == "influenza":
                reasons.append("Annual priority for all adults — PAPDI, CDC, WHO")
            else:
                reasons.append("Recommended for all adults by CDC/WHO")

        if pregnant and "pregnancy" in v["conditions"]:
            include = True
            reasons.append("Critical during pregnancy to protect mother and newborn")

        if not pregnant and key == "mmr":
            include = True
            reasons.append("Recommended if not previously immune")

        if age >= 50 and "age_50_plus" in v["conditions"]:
            include = True
            reasons.append("Recommended for all adults ≥50 (PAPDI 2025)" if key == "zoster" else "Strongly recommended for adults 50+")

        if age >= 65 and "age_65_plus" in v["conditions"]:
            include = True
            reasons.append("Essential for adults 65+")

        if age >= 60 and "age_60_plus" in v["conditions"]:
            include = True
            reasons.append("Recommended for adults ≥60 (PAPDI 2025)" if key == "rsv" else "Recommended for adults 60+")

        if age <= 45 and "age_under_45" in v["conditions"]:
            include = True
            reasons.append("Recommended up to age 45 for cancer prevention")

        for cond in conditions:
            if cond in v["conditions"]:
                include = True
                cond_label = VACCINE_DATA['risk_factors'].get(cond, {}).get('label', cond)
                if key in ("zoster", "rsv"):
                    reasons.append(f"Recommended at any adult age due to {cond_label} — PAPDI Satgas Imunisasi Dewasa 2025")
                else:
                    reasons.append(f"Strongly recommended due to {cond_label}")

        if len(travel_regions) > 0:
            if "travel" in v["conditions"] or "travel_endemic" in v["conditions"]:
                include = True
                reasons.append(f"Recommended for international travel to {', '.join(travel_regions)}")
            if "travel_asia" in v["conditions"] and any(r in ["Southeast Asia", "East Asia", "South Asia"] for r in travel_regions):
                include = True
                reasons.append("Required for travel to rural Asia")
            if "travel_yellow_fever" in v["conditions"] and any(r in ["Sub-Saharan Africa", "South America"] for r in travel_regions):
                include = True
                reasons.append("Required by law for entry to some countries")

        if pregnant and key in ["mmr", "varicella", "zoster"]:
            include = False

        if include:
            disease_explanations = {}
            clinical_details = {}   # enriched interaction data per condition
            for cond in conditions:
                if cond in VACCINE_DISEASE_RELATIONS and key in VACCINE_DISEASE_RELATIONS[cond]:
                    disease_explanations[cond] = VACCINE_DISEASE_RELATIONS[cond][key]
                if cond in VACCINE_CLINICAL_DETAIL and key in VACCINE_CLINICAL_DETAIL[cond]:
                    clinical_details[cond] = VACCINE_CLINICAL_DETAIL[cond][key]

            recommended.append({
                "key": key,
                "name": v["name"],
                "schedule": v["schedule"],
                "description": v["description"],
                "reasons": reasons,
                "priority": priority,
                "icon": v["icon"],
                "color": v["color"],
                "image": v["image"],
                "sources": v.get("sources", []),
                "disease_relations": disease_explanations,
                "clinical_details": clinical_details   # new rich data
            })

    priority_order = {"high": 0, "routine": 1, "recommended": 2, "catch_up": 3, "travel": 4}
    recommended.sort(key=lambda x: priority_order.get(x["priority"], 5))
    return recommended


# ── PREVENTIVE SCREENINGS ENGINE ──
with open(os.path.join(os.path.dirname(__file__), "data", "screenings.json")) as _f:
    SCREENING_DATA = json.load(_f)


def get_recommended_screenings(data):
    """Guideline-backed health checks for this profile — same inputs as the vaccine engine."""
    age = int(data.get("age", 30))
    sex = data.get("sex", "")
    conditions = set(data.get("conditions", []))
    results = []

    for s in SCREENING_DATA["screenings"]:
        # Sex gating
        if s.get("sex", "any") != "any" and s["sex"] != sex:
            continue
        # Hard condition requirement (e.g. lung CT only for smokers)
        if s.get("require_conditions") and not (set(s["require_conditions"]) & conditions):
            continue
        # Profile that already has the condition doesn't need the screening for it
        if s.get("exclude_conditions") and (set(s["exclude_conditions"]) & conditions):
            continue
        # Age gating — risk conditions can lower the entry age
        age_min = s["age_min"]
        boosted = bool(s.get("conditions_boost") and (set(s["conditions_boost"]) & conditions))
        if boosted and s.get("conditions_min_age") is not None:
            age_min = s["conditions_min_age"]
        if not (age_min <= age <= s["age_max"]):
            continue

        reasons = []
        if s.get("require_conditions"):
            trigger = (set(s["require_conditions"]) & conditions)
            labels = [VACCINE_DATA["risk_factors"].get(c, {}).get("label", c) for c in trigger]
            reasons.append(f"Because of {', '.join(labels)}")
        elif boosted:
            trigger = set(s["conditions_boost"]) & conditions
            labels = [VACCINE_DATA["risk_factors"].get(c, {}).get("label", c) for c in trigger]
            reasons.append(f"Earlier than usual due to {', '.join(labels)}")
        else:
            reasons.append(f"Recommended at your age ({age})")

        results.append({
            "key": s["key"], "name": s["name"], "why": s["why"],
            "frequency": s["frequency"], "priority": s["priority"],
            "icon": s["icon"], "sources": s["sources"], "reasons": reasons,
        })

    order = {"high": 0, "routine": 1, "recommended": 2}
    results.sort(key=lambda x: order.get(x["priority"], 3))
    return results


@app.route("/")
def index():
    return render_template("index.html", current_user=current_user)


@app.route("/health")
def health():
    """Liveness/readiness probe for load balancers and uptime monitors."""
    from sqlalchemy import text as _sql_text
    try:
        db.session.execute(_sql_text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    status_code = 200 if db_status == "ok" else 503
    return jsonify({
        "status": "ok" if db_status == "ok" else "degraded",
        "version": APP_VERSION,
        "database": db_status,
        "ai_configured": bool(client),
        "video_configured": TAVUS_ENABLED,
    }), status_code


# ══════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("auth.html", mode="login", page_title="Sign In")


# ── GOOGLE SIGN-IN (OAuth 2.0, no extra dependencies) ──
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


@app.context_processor
def _inject_oauth_flag():
    return {"google_oauth_enabled": GOOGLE_OAUTH_ENABLED}


def _google_redirect_uri():
    # Behind Vercel's proxy the request scheme is http — force https there
    scheme = "https" if os.environ.get("VERCEL") else request.scheme
    return url_for("google_callback", _external=True, _scheme=scheme)


@app.route("/auth/google")
def google_login():
    if not GOOGLE_OAUTH_ENABLED:
        flash("Google sign-in isn't configured yet.", "error")
        return redirect(url_for("login"))
    state = _gen_code(24)
    session["oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@app.route("/auth/google/callback")
def google_callback():
    if not GOOGLE_OAUTH_ENABLED:
        return redirect(url_for("login"))
    if request.args.get("state") != session.pop("oauth_state", None):
        flash("Sign-in session expired — please try again.", "error")
        return redirect(url_for("login"))
    code = request.args.get("code")
    if not code:
        flash("Google sign-in was cancelled.", "error")
        return redirect(url_for("login"))

    try:
        token_resp = http_req.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": _google_redirect_uri(),
            "grant_type": "authorization_code",
        }, timeout=10).json()
        userinfo = http_req.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token_resp['access_token']}"},
            timeout=10).json()
        email = userinfo["email"].strip().lower()
        name = userinfo.get("name") or email.split("@")[0]
    except Exception:
        logger.warning("Google OAuth exchange failed", exc_info=True)
        flash("Google sign-in failed — please try again or use email.", "error")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()
    is_new = user is None
    if is_new:
        user = User(email=email, name=name)
        # OAuth accounts have no usable password; they can set one via reset later
        user.set_password(_gen_code(32))
        db.session.add(user)
        db.session.commit()
    login_user(user)
    if is_new:
        flash("Welcome to CareMate! 🎉", "success")
        return redirect(url_for("onboarding"))
    return redirect(url_for("dashboard"))


# ── PASSWORD RESET ──
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

def _reset_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="password-reset")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = _reset_serializer().dumps(user.email)
            reset_url = url_for("reset_password", token=token, _external=True)
            sent = False
            if app.config.get("MAIL_USERNAME"):
                try:
                    msg = MailMessage(
                        subject="Reset your CareMate password",
                        recipients=[user.email],
                        body=(f"Hi {user.name or 'there'},\n\n"
                              f"Someone requested a password reset for your CareMate account. "
                              f"Use the link below within 1 hour:\n\n{reset_url}\n\n"
                              f"If this wasn't you, you can safely ignore this email."))
                    mail.send(msg)
                    sent = True
                except Exception:
                    logger.warning("Reset email failed for %s", email, exc_info=True)
            if not sent:
                # No SMTP configured — surface the link in server logs for the operator
                logger.info("Password reset link for %s: %s", email, reset_url)
        # Same message whether or not the account exists — prevents email enumeration
        flash("If an account exists with that email, we've sent a password reset link.", "success")
        return redirect(url_for("login"))
    return render_template("auth.html", mode="forgot", page_title="Reset Password")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    try:
        email = _reset_serializer().loads(token, max_age=3600)
    except SignatureExpired:
        flash("That reset link has expired — please request a new one.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "error")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Invalid reset link.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords don't match.", "error")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Password updated — you can sign in now.", "success")
            return redirect(url_for("login"))
    return render_template("auth.html", mode="reset", page_title="Choose New Password", reset_token=token)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        name     = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        phone    = request.form.get("phone", "").strip() or None
        dob_str  = request.form.get("dob", "")
        wa_opt   = request.form.get("whatsapp_opt_in") == "on"

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("auth.html", mode="register", page_title="Create Account")

        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        user = User(
            email=email, name=name, phone=phone,
            date_of_birth=dob, whatsapp_opt_in=wa_opt
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Welcome to CareMate! 🎉", "success")
        return redirect(url_for("onboarding"))

    return render_template("auth.html", mode="register", page_title="Create Account")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ══════════════════════════════════════════════════════════
#  USER DASHBOARD ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    vaccination_records = VaccinationRecord.query.filter_by(user_id=current_user.id)\
        .order_by(VaccinationRecord.date_given.desc()).all()
    pending_reminders = VaccineReminder.query.filter_by(user_id=current_user.id, sent=False)\
        .filter(VaccineReminder.reminder_date >= today)\
        .order_by(VaccineReminder.reminder_date).all()
    assessments = Assessment.query.filter_by(user_id=current_user.id).all()
    last_assessment = Assessment.query.filter_by(user_id=current_user.id)\
        .order_by(Assessment.created_at.desc()).first()
    bookings = Booking.query.filter_by(user_id=current_user.id)\
        .order_by(Booking.appointment_date.desc()).all()

    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.date_of_birth.desc()).all()
    family = [{"child": c, "schedule": compute_child_schedule(c)} for c in children]
    lab_results = LabResult.query.filter_by(user_id=current_user.id)\
        .order_by(LabResult.date_taken.desc(), LabResult.created_at.desc()).all()
    # Heal rows saved before a test existed in the reference table: re-match + re-flag
    _healed = False
    for lab in lab_results:
        if not lab.test_key:
            k = match_lab_test(lab.test_name)
            if k:
                lab.test_key = k
                lab.flag = flag_lab_value(k, lab.value)
                _healed = True
    if _healed:
        db.session.commit()

    return render_template(
        "user_dashboard.html",
        vaccination_records=vaccination_records,
        pending_reminders=pending_reminders,
        assessments=assessments,
        last_assessment=last_assessment,
        bookings=bookings,
        today=today,
        vaccines=VACCINE_DATA["vaccines"],
        family=family,
        lab_results=lab_results,
        lab_reference=LAB_REFERENCE
    )


# ══════════════════════════════════════════════════════════
#  LAB RESULTS — photo extraction + manual entry
# ══════════════════════════════════════════════════════════

with open(os.path.join(os.path.dirname(__file__), "data", "lab_reference.json")) as _f:
    LAB_REFERENCE = json.load(_f)["tests"]

with open(os.path.join(os.path.dirname(__file__), "data", "lab_recommendations.json")) as _f:
    LAB_RECOMMENDATIONS = json.load(_f)["rules"]


def match_lab_test(name):
    """Match a free-text test name to a known reference key, or None."""
    n = name.strip().lower()
    for key, ref in LAB_REFERENCE.items():
        if n == key or n == ref["name"].lower() or n in [a.lower() for a in ref.get("aliases", [])]:
            return key
    return None


def flag_lab_value(test_key, value):
    """normal | high | low | unknown — informational only, never a diagnosis."""
    ref = LAB_REFERENCE.get(test_key)
    if not ref:
        return "unknown"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if v < ref["low"]:
        return "low"
    if v > ref["high"]:
        return "high"
    return "normal"


@app.route("/labs/add", methods=["POST"])
@login_required
def add_lab_result():
    test_name = request.form.get("test_name", "").strip()
    try:
        value = float(request.form.get("value", ""))
    except ValueError:
        flash("Please enter a numeric value.", "error")
        return redirect(url_for("dashboard"))
    date_s = request.form.get("date_taken", "")
    try:
        taken = datetime.strptime(date_s, "%Y-%m-%d").date() if date_s else date.today()
    except ValueError:
        taken = date.today()

    key = request.form.get("test_key") or match_lab_test(test_name)
    ref = LAB_REFERENCE.get(key)
    db.session.add(LabResult(
        user_id=current_user.id, test_key=key,
        test_name=ref["name"] if ref else test_name,
        value=value, unit=request.form.get("unit") or (ref["unit"] if ref else ""),
        flag=flag_lab_value(key, value), date_taken=taken, source="manual"))
    db.session.commit()
    flash("Lab result saved.", "success")
    return redirect(url_for("dashboard"))


@app.route("/labs/upload", methods=["POST"])
@login_required
def upload_lab_photo():
    if not client:
        flash("AI extraction needs an OpenAI key — you can still add results manually.", "error")
        return redirect(url_for("dashboard"))
    f = request.files.get("lab_photo")
    if not f or not f.filename:
        flash("Please choose a photo of your lab report.", "error")
        return redirect(url_for("dashboard"))
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "webp"):
        flash("Please upload a JPG, PNG or WebP photo.", "error")
        return redirect(url_for("dashboard"))

    # Processed in memory only — the image itself is never stored
    img_b64 = base64.b64encode(f.read()).decode()
    mime = "image/png" if ext == "png" else ("image/webp" if ext == "webp" else "image/jpeg")

    prompt = (
        "This is a photo of a medical lab report. Extract every test result you can read. "
        "Return ONLY a JSON array, no other text: "
        '[{"name": "test name in English", "value": numeric value only, "unit": "unit as printed"}] '
        "Skip reference ranges, dates and patient details. If a value is unreadable, skip it."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            ]}],
            max_tokens=900, temperature=0)
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("["):raw.rindex("]") + 1]   # tolerate stray prose/code fences
        rows = json.loads(raw)
    except Exception:
        logger.warning("Lab photo extraction failed", exc_info=True)
        flash("Couldn't read that photo — try a sharper, well-lit picture, or add values manually.", "error")
        return redirect(url_for("dashboard"))

    saved = 0
    for r in rows[:25]:
        try:
            value = float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(r.get("name", "")).strip()[:120]
        if not name:
            continue
        key = match_lab_test(name)
        ref = LAB_REFERENCE.get(key)
        db.session.add(LabResult(
            user_id=current_user.id, test_key=key,
            test_name=ref["name"] if ref else name,
            value=value, unit=str(r.get("unit", ""))[:30] or (ref["unit"] if ref else ""),
            flag=flag_lab_value(key, value), source="photo"))
        saved += 1
    db.session.commit()
    if saved:
        flash(f"Read {saved} value(s) from your report. Review them below — and discuss anything flagged with your doctor.", "success")
    else:
        flash("No readable values found in that photo — try a clearer picture or add them manually.", "error")
    return redirect(url_for("dashboard"))


@app.route("/labs/delete/<int:lab_id>", methods=["POST"])
@login_required
def delete_lab_result(lab_id):
    row = LabResult.query.filter_by(id=lab_id, user_id=current_user.id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/api/labs/recommendations")
@login_required
def lab_recommendations_api():
    """Return follow-up tests + vaccines for the user's flagged lab results."""
    lab_results = LabResult.query.filter_by(user_id=current_user.id)\
        .order_by(LabResult.date_taken.desc()).all()

    # Deduplicate by test_key: keep only the most recent per test
    seen = {}
    for lab in lab_results:
        key = lab.test_key
        if key and key not in seen:
            seen[key] = lab

    flagged = [lab for lab in seen.values() if lab.flag in ("high", "low")]
    if not flagged:
        return jsonify({"has_flags": False, "flags": [], "follow_up_tests": [], "vaccines": []})

    follow_up_map = {}   # name → reason (deduplicated)
    vaccine_map = {}     # key → {key, reason, names}
    flag_summaries = []

    for lab in flagged:
        rule = LAB_RECOMMENDATIONS.get(lab.test_key, {}).get(lab.flag, {})
        if not rule:
            continue
        flag_summaries.append({
            "test_name": lab.test_name,
            "value": lab.value,
            "unit": lab.unit,
            "flag": lab.flag,
            "date": lab.date_taken.strftime("%d %b %Y"),
            "urgency": rule.get("urgency", "check"),
            "message": rule.get("message", "")
        })
        for ft in rule.get("follow_up_tests", []):
            name = ft["name"]
            if name not in follow_up_map:
                follow_up_map[name] = ft["reason"]
        for v in rule.get("vaccines", []):
            vkey = v["key"]
            if vkey not in vaccine_map:
                vaccine_map[vkey] = {"key": vkey, "reasons": []}
            vaccine_map[vkey]["reasons"].append(v["reason"])

    # Resolve vaccine display names
    vaccines_out = []
    for vkey, vdata in vaccine_map.items():
        ref = VACCINE_DATA["vaccines"].get(vkey, {})
        vaccines_out.append({
            "key": vkey,
            "name": ref.get("name", vkey.replace("_", " ").title()),
            "reasons": vdata["reasons"]
        })

    follow_up_out = [{"name": n, "reason": r} for n, r in follow_up_map.items()]

    # Build teleconsult context string for Tavus
    flag_lines = []
    for f in flag_summaries:
        flag_lines.append(
            f"  • {f['test_name']}: {f['value']} {f['unit']} ({f['flag'].upper()}) — {f['message']}"
        )
    vacc_lines = [f"  • {v['name']}: {v['reasons'][0]}" for v in vaccines_out]
    ft_lines = [f"  • {ft['name']}: {ft['reason']}" for ft in follow_up_out[:6]]

    lab_context = (
        "--- PATIENT LAB RESULTS (from CareMate) ---\n"
        + "\n".join(flag_lines)
        + "\n\nRecommended Follow-up Tests:\n" + "\n".join(ft_lines)
        + "\n\nVaccines Indicated by Lab Results:\n" + "\n".join(vacc_lines)
        + "\n---\n"
        "INSTRUCTION: Open the consultation by summarising these lab findings in plain language. "
        "Explain each flagged value and what it means clinically. Then go through the recommended "
        "follow-up tests one by one and explain why each is needed. Then explain the vaccine "
        "recommendations. Use a warm, clear, doctor-patient tone. Invite questions after."
    )

    return jsonify({
        "has_flags": True,
        "flags": flag_summaries,
        "follow_up_tests": follow_up_out,
        "vaccines": vaccines_out,
        "lab_context_for_tavus": lab_context
    })


# ══════════════════════════════════════════════════════════
#  FAMILY — PEDIATRIC IMMUNIZATION (IDAI 2024)
# ══════════════════════════════════════════════════════════

with open(os.path.join(os.path.dirname(__file__), "data", "pediatric_schedule.json")) as _f:
    PEDIATRIC_SCHEDULE = json.load(_f)


def compute_child_schedule(child):
    """Build the child's IDAI schedule with a status per dose.

    Statuses: done | overdue | due (within 30 days) | upcoming
    Returns dict with the full timeline plus convenience slices for the UI.
    """
    from datetime import timedelta
    today = date.today()
    given = {(r.vaccine_key, r.dose_number) for r in
             VaccinationRecord.query.filter_by(child_id=child.id).all()}

    timeline = []
    for d in PEDIATRIC_SCHEDULE["doses"]:
        if d.get("sex") and child.sex and d["sex"] != child.sex:
            continue
        # due date = DOB shifted by due_month months
        m = child.date_of_birth.month - 1 + d["due_month"]
        due = child.date_of_birth.replace(
            year=child.date_of_birth.year + m // 12,
            month=m % 12 + 1,
            day=min(child.date_of_birth.day, 28))
        if (d["key"], d["dose"]) in given:
            status = "done"
        elif due < today - timedelta(days=30):
            status = "overdue"
        elif due <= today + timedelta(days=30):
            status = "due"
        else:
            status = "upcoming"
        timeline.append({**d, "due_date": due, "status": status})

    timeline.sort(key=lambda x: x["due_date"])
    pending = [t for t in timeline if t["status"] != "done"]
    return {
        "timeline": timeline,
        "overdue":  [t for t in timeline if t["status"] == "overdue"],
        "due":      [t for t in timeline if t["status"] == "due"],
        "next_up":  pending[:3],
        "done_count": sum(1 for t in timeline if t["status"] == "done"),
        "total": len(timeline),
    }


@app.route("/family/add-child", methods=["POST"])
@login_required
def add_child():
    name = request.form.get("name", "").strip()
    dob_str = request.form.get("date_of_birth", "")
    sex = request.form.get("sex", "")
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Please provide a valid date of birth.", "error")
        return redirect(url_for("dashboard"))
    if not name or dob > date.today():
        flash("Please provide your child's name and a valid date of birth.", "error")
        return redirect(url_for("dashboard"))

    child = Child(user_id=current_user.id, name=name, date_of_birth=dob, sex=sex or None)
    db.session.add(child)
    db.session.commit()

    # Schedule a WhatsApp/email reminder for the next pending dose
    _ensure_child_reminder(child)
    flash(f"{name} added — full IDAI immunization schedule generated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/family/record-dose", methods=["POST"])
@login_required
def record_child_dose():
    child = Child.query.filter_by(id=request.form.get("child_id", type=int),
                                  user_id=current_user.id).first()
    if not child:
        flash("Child not found.", "error")
        return redirect(url_for("dashboard"))
    rec = VaccinationRecord(
        user_id=current_user.id, child_id=child.id,
        vaccine_key=request.form.get("vaccine_key", ""),
        vaccine_name=request.form.get("vaccine_name", ""),
        dose_number=request.form.get("dose_number", 1, type=int),
        date_given=date.today())
    db.session.add(rec)
    db.session.commit()
    _ensure_child_reminder(child)
    flash(f"Recorded {rec.vaccine_name} dose {rec.dose_number} for {child.name}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/family/delete-child/<int:child_id>", methods=["POST"])
@login_required
def delete_child(child_id):
    child = Child.query.filter_by(id=child_id, user_id=current_user.id).first()
    if child:
        VaccinationRecord.query.filter_by(child_id=child.id).delete()
        db.session.delete(child)
        db.session.commit()
        flash("Child profile removed.", "success")
    return redirect(url_for("dashboard"))


def _ensure_child_reminder(child):
    """Keep exactly one pending reminder per child: the next non-done dose."""
    from datetime import timedelta
    schedule = compute_child_schedule(child)
    pending = schedule["overdue"] + schedule["due"] + \
              [t for t in schedule["timeline"] if t["status"] == "upcoming"]
    if not pending:
        return
    nxt = pending[0]
    tag = f"[child:{child.id}]"
    # Replace any previous unsent reminder for this child
    VaccineReminder.query.filter_by(user_id=child.user_id, sent=False)\
        .filter(VaccineReminder.message.like(f"%{tag}%")).delete(synchronize_session=False)
    remind_on = max(nxt["due_date"] - timedelta(days=7), date.today())
    db.session.add(VaccineReminder(
        user_id=child.user_id,
        vaccine_key=nxt["key"],
        vaccine_name=f"{nxt['name']} (dose {nxt['dose']}) — {child.name}",
        reminder_date=remind_on,
        message=f"{tag} {child.name}'s {nxt['name']} dose {nxt['dose']} is due on {nxt['due_date'].strftime('%d %b %Y')} (IDAI schedule).",
        channel="whatsapp" if child.parent.whatsapp_opt_in else "email"))
    db.session.commit()


@app.route("/dashboard/log-vaccine", methods=["POST"])
@login_required
def log_vaccine():
    vaccine_key  = request.form.get("vaccine_key", "")
    vaccine_name = request.form.get("vaccine_name", "").strip()
    date_str     = request.form.get("date_given", "")
    dose_num     = int(request.form.get("dose_number", 1))
    clinic_name  = request.form.get("clinic_name", "").strip() or None
    next_date_s  = request.form.get("next_dose_date", "")
    set_reminder = request.form.get("set_reminder", "no") == "yes"

    try:
        date_given = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("dashboard"))

    next_dose_date = None
    if next_date_s:
        try:
            next_dose_date = datetime.strptime(next_date_s, "%Y-%m-%d").date()
        except ValueError:
            pass

    rec = VaccinationRecord(
        user_id=current_user.id,
        vaccine_key=vaccine_key,
        vaccine_name=vaccine_name,
        date_given=date_given,
        dose_number=dose_num,
        clinic_name=clinic_name,
        next_dose_date=next_dose_date
    )
    db.session.add(rec)
    db.session.commit()

    if set_reminder and next_dose_date:
        from reminders import schedule_vaccine_reminders
        schedule_vaccine_reminders(
            current_user, vaccine_key, vaccine_name, next_dose_date
        )

    flash(f"✅ {vaccine_name} (Dose {dose_num}) logged successfully!", "success")
    return redirect(url_for("dashboard"))


@app.route("/dashboard/reminders")
@login_required
def dashboard_reminders():
    today = date.today()
    pending = VaccineReminder.query.filter_by(user_id=current_user.id, sent=False)\
        .filter(VaccineReminder.reminder_date >= today)\
        .order_by(VaccineReminder.reminder_date).all()
    past = VaccineReminder.query.filter_by(user_id=current_user.id)\
        .filter(VaccineReminder.reminder_date < today)\
        .order_by(VaccineReminder.reminder_date.desc()).limit(20).all()
    return render_template("dashboard_reminders.html",
                           pending=pending, past=past, today=today)


@app.route("/dashboard/history")
@login_required
def dashboard_history():
    records = VaccinationRecord.query.filter_by(user_id=current_user.id)\
        .order_by(VaccinationRecord.date_given.desc()).all()
    return render_template("dashboard_history.html", records=records,
                           today=date.today(), vaccines=VACCINE_DATA["vaccines"])


@app.route("/dashboard/settings", methods=["GET", "POST"])
@login_required
def dashboard_settings():
    if request.method == "POST":
        current_user.name  = request.form.get("name", current_user.name).strip()
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.whatsapp_opt_in = request.form.get("whatsapp_opt_in") == "on"
        db.session.commit()
        flash("Settings saved.", "success")
    return render_template("dashboard_settings.html")


# ══════════════════════════════════════════════════════════
#  CLINIC BOOKING ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/references")
def references():
    return render_template("references.html")


@app.route("/terms")
def terms():
    return render_template("legal.html", doc="terms")


@app.route("/privacy")
def privacy():
    return render_template("legal.html", doc="privacy")


@app.route("/clinics")
def clinics():
    all_clinics = Clinic.query.order_by(Clinic.rating.desc()).all()
    booking_confirmed = request.args.get("booking_confirmed")
    return render_template(
        "clinics.html",
        clinics=all_clinics,
        vaccines=VACCINE_DATA["vaccines"],
        booking_confirmed=booking_confirmed
    )


@app.route("/clinics/book", methods=["POST"])
@login_required
def book_clinic():
    clinic_id    = int(request.form.get("clinic_id", 0))
    vaccine_key  = request.form.get("vaccine_key", "")
    vaccine_name = request.form.get("vaccine_name", "").strip()
    appt_str     = request.form.get("appointment_date", "")
    notes        = request.form.get("notes", "").strip() or None

    clinic = Clinic.query.get_or_404(clinic_id)

    try:
        appt_dt = datetime.strptime(appt_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Invalid appointment date.", "error")
        return redirect(url_for("clinics"))

    code = _gen_code(8)
    booking = Booking(
        user_id=current_user.id,
        clinic_id=clinic_id,
        vaccine_key=vaccine_key,
        vaccine_name=vaccine_name,
        appointment_date=appt_dt,
        status="confirmed",
        confirmation_code=code,
        referral_fee=25000,
        notes=notes
    )
    db.session.add(booking)
    db.session.commit()

    # Schedule reminders for the booking date
    from reminders import schedule_vaccine_reminders
    schedule_vaccine_reminders(
        current_user, vaccine_key, vaccine_name, appt_dt.date()
    )

    return redirect(url_for("clinics", booking_confirmed=code))


# ══════════════════════════════════════════════════════════
#  CORPORATE ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/corporate/login", methods=["GET", "POST"])
def corporate_login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        company  = Company.query.filter_by(contact_email=email).first()
        if company and company.check_password(password):
            session["corp_id"] = company.id
            return redirect(url_for("corporate_dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("corporate_auth.html", mode="login",
                           page_title="Corporate Sign In")


@app.route("/corporate/register", methods=["GET", "POST"])
def corporate_register():
    if request.method == "POST":
        email        = request.form.get("email", "").strip().lower()
        company_name = request.form.get("company_name", "").strip()
        contact_name = request.form.get("contact_name", "").strip()
        industry     = request.form.get("industry", "")
        emp_size     = request.form.get("employee_size", "")
        password     = request.form.get("password", "")

        if Company.query.filter_by(contact_email=email).first():
            flash("A company account with that email already exists.", "error")
            return render_template("corporate_auth.html", mode="register",
                                   page_title="Register Company")

        company = Company(
            name=company_name,
            contact_email=email,
            contact_name=contact_name,
            industry=industry,
            employee_size=emp_size,
            plan="starter"
        )
        company.set_password(password)
        db.session.add(company)
        db.session.commit()
        session["corp_id"] = company.id
        flash(f"Welcome, {company_name}! Your corporate account is ready. 🎉", "success")
        return redirect(url_for("corporate_dashboard"))

    return render_template("corporate_auth.html", mode="register",
                           page_title="Register Company")


def _get_corp():
    """Get logged-in company from session, or None."""
    corp_id = session.get("corp_id")
    return Company.query.get(corp_id) if corp_id else None


@app.route("/corporate/logout")
def corporate_logout():
    session.pop("corp_id", None)
    return redirect(url_for("corporate_login"))


@app.route("/corporate/dashboard")
def corporate_dashboard():
    company = _get_corp()
    if not company:
        return redirect(url_for("corporate_login"))

    employees = company.employees
    coverage  = company.vaccination_coverage

    total_pending = sum(len(e.pending_reminders()) for e in employees)
    total_assess  = sum(len(e.assessments) for e in employees)

    return render_template(
        "corporate_dashboard.html",
        company=company,
        employees=employees,
        coverage=coverage,
        vaccines=VACCINE_DATA["vaccines"],
        total_pending_reminders=total_pending,
        total_assessments=total_assess
    )


@app.route("/corporate/dashboard/remind/<vaccine_key>")
def corporate_send_reminder(vaccine_key):
    company = _get_corp()
    if not company:
        return redirect(url_for("corporate_login"))

    from reminders import send_whatsapp, build_reminder_message
    needing = company.employees_needing(vaccine_key)
    vac_name = VACCINE_DATA["vaccines"].get(vaccine_key, {}).get("name", vaccine_key)
    sent = 0
    for emp in needing:
        if emp.phone and emp.whatsapp_opt_in:
            msg = build_reminder_message(vac_name, emp.name, 0)
            result = send_whatsapp(emp.phone, msg)
            if result["ok"]:
                sent += 1
    flash(f"Reminder sent to {sent} employee(s) for {vac_name}.", "success")
    return redirect(url_for("corporate_dashboard"))


@app.route("/corporate/dashboard/reminders/send-all")
def corporate_send_all():
    company = _get_corp()
    if not company:
        return redirect(url_for("corporate_login"))
    from reminders import send_whatsapp, build_reminder_message
    sent = 0
    for emp in company.employees:
        pending = emp.pending_reminders()
        if pending and emp.phone and emp.whatsapp_opt_in:
            msg = build_reminder_message(pending[0].vaccine_name, emp.name, 0)
            result = send_whatsapp(emp.phone, msg)
            if result["ok"]:
                sent += 1
    flash(f"Reminders sent to {sent} employee(s).", "success")
    return redirect(url_for("corporate_dashboard"))


VALID_REGIONS = {"Southeast Asia", "South Asia", "East Asia", "Sub-Saharan Africa",
                 "Latin America", "South America", "Middle East", "Europe", "North America"}


def _validate_assessment(data):
    """Validate the assessment payload. Returns an error string or None."""
    if not isinstance(data, dict):
        return "Request body must be a JSON object"
    try:
        age = int(data.get("age", 0))
    except (TypeError, ValueError):
        return "Age must be a number"
    if not 18 <= age <= 120:
        return "Age must be between 18 and 120"
    valid_conditions = set(VACCINE_DATA["risk_factors"].keys()) | {"none"}
    conditions = data.get("conditions", [])
    if not isinstance(conditions, list) or any(c not in valid_conditions for c in conditions):
        return "Unknown condition key"
    regions = data.get("travel_regions", [])
    if not isinstance(regions, list) or any(r not in VALID_REGIONS for r in regions):
        return "Unknown travel region"
    return None


@app.route("/api/recommend", methods=["POST"])
@limiter.limit("20 per minute")
def recommend():
    data = request.json
    error = _validate_assessment(data)
    if error:
        return jsonify({"error": error}), 400
    risk = calculate_risk_score(data)
    vaccines = get_recommended_vaccines(data)
    screenings = get_recommended_screenings(data)

    # Deterministic fallback — used when no AI key is configured or the call fails
    fallback_summary = (
        f"Based on your health profile, we have identified {len(vaccines)} vaccines "
        f"recommended for you. Your Prevention Score is {risk['prevention_score']}/100 — completing them raises it. "
        f"Please consult with "
        f"a healthcare provider to discuss your personalized immunization schedule."
    )
    ai_summary = fallback_summary
    if client:
        try:
            conditions_text = ", ".join(data.get("conditions", [])) or "none reported"
            travel_text = ", ".join(data.get("travel_regions", [])) or "no international travel"
            vaccine_names = ", ".join([v["name"] for v in vaccines[:6]])
            screening_names = ", ".join([s["name"] for s in screenings[:4]]) or "none specific"

            prompt = f"""You're a friendly doctor reviewing a patient's vaccination profile. Here's what you know about them:
- Age: {data.get('age')} years old
- Medical conditions: {conditions_text}
- Pregnancy: {data.get('pregnant', 'no')}
- Travel plans: {travel_text}
- Prevention Score: {risk['prevention_score']}/100 ({risk['prevention_label']})
- Vaccines they need: {vaccine_names}
- Health checks due at their age: {screening_names}

Write a personal, warm 3-4 sentence message directly to this patient — like a doctor talking to someone they genuinely care about. Mention their specific situation (age, conditions, travel), explain what their Prevention Score means in plain terms and what would raise it, and highlight the one or two vaccines that matter most for *them*. Sound like a real person, not a medical report. Use "you" and "your". No bullet points, no clinical jargon, no generic advice. Make it feel like it was written specifically for this person."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.85
            )
            ai_summary = response.choices[0].message.content or fallback_summary
        except Exception:
            logger.warning("AI summary generation failed — using fallback", exc_info=True)
            ai_summary = fallback_summary

    # Persist assessment if a user is logged in
    if current_user.is_authenticated:
        try:
            asmt = Assessment(
                user_id=current_user.id,
                age=int(data.get("age", 0)),
                sex=data.get("sex", ""),
                conditions=json.dumps(data.get("conditions", [])),
                travel_regions=json.dumps(data.get("travel_regions", [])),
                pregnant=data.get("pregnant") == "yes",
                risk_score=risk["percentage"],
                risk_level=risk["level"],
                vaccines_recommended=json.dumps([v["key"] for v in vaccines])
            )
            db.session.add(asmt)
            db.session.commit()
        except Exception as e:
            print(f"[Assessment save] {e}")

    return jsonify({
        "risk": risk,
        "vaccines": vaccines,
        "screenings": screenings,
        "ai_summary": ai_summary,
        "total_vaccines": len(vaccines)
    })


@app.route("/api/chat", methods=["POST"])
@limiter.limit("15 per minute")
def chat():
    data = request.json
    user_message = data.get("message", "")
    conversation_history = data.get("history", [])

    if not client:
        return jsonify({"reply": "⚠️ AI assistant not configured. Please add your OPENAI_API_KEY to the .env file to enable the chatbot.", "error": True})

    system_prompt = """You're the CareMate assistant — a warm, knowledgeable companion for preventive health. CareMate helps people get ahead of disease, so you cover the whole picture of prevention: vaccines, health screenings and check-ups (which tests to do at what age), reading lab results in plain language, children's immunization schedules, and everyday prevention like nutrition, lifestyle and mental wellbeing. You're warm, straight-talking, and genuinely helpful — never a textbook.

How you talk:
- Conversational and direct. Say "you'll probably want to..." instead of "it is recommended that patients consider..."
- Give real answers. If someone asks about a side effect or a lab value, tell them what it actually means — not just "consult your doctor"
- It's fine to show a little personality. A light touch of warmth goes a long way
- Short paragraphs, natural rhythm. Mix short punchy sentences with longer ones
- Use actual numbers when they help ("about 1 in 10 people get a sore arm")
- Don't open every message with "Great question!" — just answer
- For diagnosing symptoms or big personal medical decisions, point them to a doctor — but still give the real information they came for, and you can suggest they try CareMate's free assessment for a personalised plan or book a teleconsultation
- Only step back if a question is truly unrelated to health or prevention

When someone asks "what tests/screenings do I need at my age?", actually answer it. General guidance for adults:
- Everyone: blood pressure yearly; cholesterol from ~35; blood sugar (HbA1c) from ~35 (earlier if overweight or family history)
- Around 35: a good baseline — blood pressure, cholesterol panel, blood sugar, and a one-time hepatitis B/C and HIV screen (especially relevant in Indonesia)
- Women: cervical cancer screening (Pap/HPV) from 21–25; mammograms from 40
- Men: discuss prostate (PSA) screening from ~55
- From 45: colorectal cancer screening
- Smokers 50+: lung cancer screening
- Tailor to conditions: diabetics need yearly eye and kidney checks
Encourage them to run CareMate's free assessment for a plan personalised to their exact age, sex, conditions and lifestyle.

You also know vaccines inside out: Influenza, COVID-19, Tdap/Td, MMR, Varicella, Herpes Zoster, HPV, Pneumococcal, RSV, Hepatitis A & B, Meningococcal, Typhoid, Yellow Fever, Japanese Encephalitis, Rabies, Cholera, plus the IDAI children's schedule — schedules, catch-up timing, contraindications, pregnancy safety, and Indonesia-specific availability. Always educational, never a diagnosis."""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-14:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=350,
            temperature=0.82
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = f"I encountered an error: {str(e)}. Please try again."

    return jsonify({"reply": reply})


@app.route("/consultation/<int:doctor_id>")
def consultation(doctor_id):
    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])
    # Pass logged-in user's name so JS can pre-fill Tavus without asking
    user_name = current_user.name if current_user.is_authenticated else ""
    return render_template("consultation.html", doctor=doctor, user_name=user_name)


@app.route("/api/consult", methods=["POST"])
@limiter.limit("20 per minute")
def consult():
    """Streaming AI doctor consultation endpoint."""
    data = request.json
    user_message = data.get("message", "")
    history = data.get("history", [])
    doctor_id = data.get("doctor_id", 1)
    patient_name = data.get("patient_name", "")

    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])

    if not client:
        def no_key():
            yield "AI doctor not available — please configure OPENAI_API_KEY in your .env file."
        return Response(stream_with_context(no_key()), content_type="text/plain; charset=utf-8")

    name_line = f"The patient's name is {patient_name}. " if patient_name else ""

    system_prompt = f"""You are {doctor['name']}, a {doctor['specialty']} specialist with {doctor['experience']} of experience at {doctor['hospital']} in {doctor['city']}, Indonesia. You're having a live teleconsultation right now.
{name_line}

You're the kind of doctor patients love — you actually listen, you explain things in plain language, and you treat the person in front of you like an intelligent adult. You don't talk down to people, you don't hide behind jargon, and you don't make them feel rushed.

How you speak in this consultation:
- Talk like a real doctor in a real appointment. Natural, flowing sentences — not bullet points or numbered lists
- React to what the patient actually says. If they seem worried, acknowledge it. If they're asking about something specific, go there with them
- Share your clinical opinion directly: "Honestly, for someone your age with diabetes, I'd prioritise the pneumococcal vaccine first" — not "it may be considered appropriate"
- It's okay to think out loud a little: "That's a good question, actually — the short answer is yes, but there's a nuance worth knowing..."
- Keep each turn to 3-5 sentences. This is a conversation, not a lecture
- On your very first message, greet them warmly and naturally — don't just launch into medical content
- Remember what they've told you earlier in the conversation and refer back to it naturally
- You follow CDC, WHO, and Kemenkes guidelines and know Indonesian vaccine availability and pricing cold

You speak {'Indonesian and English naturally' if 'Bahasa Indonesia' in doctor['languages'] else 'English'}."""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-20:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    def generate():
        try:
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=400,
                temperature=0.85,
                stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f"I apologize, there was a connection issue: {str(e)}"

    return Response(stream_with_context(generate()), content_type="text/plain; charset=utf-8")


@app.route("/teleconsultation")
def teleconsultation():
    return render_template("teleconsultation.html", doctors=DOCTORS)


@app.route("/api/doctors", methods=["GET"])
def get_doctors():
    city = request.args.get("city", "").lower()
    specialty = request.args.get("specialty", "").lower()
    available_only = request.args.get("available", "false") == "true"

    filtered = DOCTORS
    if city:
        filtered = [d for d in filtered if city in d["city"].lower()]
    if specialty:
        filtered = [d for d in filtered if specialty in d["specialty"].lower()]
    if available_only:
        filtered = [d for d in filtered if d["available"]]

    return jsonify(filtered)


@app.route("/api/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts():
    """OpenAI Text-to-Speech — returns MP3 audio bytes."""
    if not client:
        return jsonify({"error": "TTS not available — configure OPENAI_API_KEY"}), 503
    data = request.json
    text = data.get("text", "")[:4096]   # OpenAI TTS max 4096 chars
    voice = data.get("voice", "nova")     # nova, shimmer, echo, onyx, alloy, fable
    if not text:
        return jsonify({"error": "No text provided"}), 400
    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        return Response(response.content, content_type="audio/mpeg",
                        headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── D-ID REAL-TIME WEBRTC STREAMING AVATAR ──────────────────────────────────

@app.route("/api/did/enabled", methods=["GET"])
def did_enabled():
    return jsonify({"enabled": DID_ENABLED})

@app.route("/api/did/cleanup", methods=["POST"])
def did_cleanup():
    """Force-close all tracked D-ID sessions."""
    closed = []
    for sid, sess in list(_did_active_streams.items()):
        _did_close_stream(sid, sess)
        _did_active_streams.pop(sid, None)
        closed.append(sid)
    return jsonify({"closed": closed})

# ──────────────────────────────────────────────
# TAVUS CVI ROUTES
# ──────────────────────────────────────────────

@app.route("/api/tavus/enabled")
def tavus_enabled():
    return jsonify({"enabled": TAVUS_ENABLED})

@app.route("/api/tavus/conversation", methods=["POST"])
@limiter.limit("5 per minute")
def tavus_create_conversation():
    """Create a Tavus CVI conversation for the selected doctor."""
    if not TAVUS_ENABLED:
        return jsonify({"error": "Tavus not configured — add TAVUS_API_KEY and TAVUS_REPLICA_ID to .env"}), 503

    data       = request.json or {}
    doctor_id  = data.get("doctor_id", 1)
    doctor     = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])

    # Per-doctor replica → env override → gender-based doctor replica
    gender     = doctor.get("gender", "female")
    auto       = TAVUS_MALE_REPLICA if gender == "male" else TAVUS_FEMALE_REPLICA
    replica_id = doctor.get("tavus_replica_id") or _tavus_replica_id or auto

    # Language override from frontend (patient selected English or Indonesian via toggle)
    lang_override = data.get("language_override", None)  # 'english' | 'indonesian' | None

    # Optional assessment results passed from the frontend
    patient_ctx = data.get("patient_context", {})
    # Optional lab results context (from /api/labs/recommendations flow)
    lab_ctx_str = data.get("lab_context", "")
    base_context = _doctor_tavus_context(doctor, lang_override)

    if patient_ctx:
        risk        = patient_ctx.get("risk", {})
        vaccines    = patient_ctx.get("vaccines", [])
        form        = patient_ctx.get("form", {})
        age         = form.get("age", "unknown")
        conditions  = form.get("conditions", [])
        travel      = form.get("travel_regions", [])
        summary     = patient_ctx.get("ai_summary", "")
        p_name      = patient_ctx.get("patient_name") or form.get("patient_name", "")

        name_line = f"Patient Name: {p_name}\n" if p_name else ""
        vaccines_str  = ", ".join(vaccines) if vaccines else "standard adult vaccines"
        conditions_str = ", ".join(conditions) if conditions else "no specific conditions reported"

        # Determine effective language (override beats doctor profile)
        speaks_id_eff = (lang_override == "indonesian") or \
                        (lang_override is None and "Bahasa Indonesia" in doctor.get("languages", []))
        cond_q_bank = _COND_Q_ID if speaks_id_eff else _COND_Q_EN

        # Build per-condition questions for conditions the patient reported
        cond_questions = []
        condition_map = VACCINE_DATA["risk_factors"]
        for cond in conditions:
            if cond in cond_q_bank:
                label = condition_map.get(cond, {}).get("label", cond)
                cond_questions.append(f"  • {label}: {cond_q_bank[cond]}")

        cond_question_section = ""
        if cond_questions:
            if speaks_id_eff:
                cond_question_section = (
                    "\n\nPERTANYAAN KLINIS PER KONDISI (tanyakan SETELAH selesai menjelaskan semua vaksin, "
                    "satu kondisi per giliran, secara percakapan alami):\n"
                    + "\n".join(cond_questions)
                )
            else:
                cond_question_section = (
                    "\n\nCONDITION-SPECIFIC CLINICAL QUESTIONS (ask these AFTER finishing the vaccine explanation, "
                    "one condition at a time, conversationally):\n"
                    + "\n".join(cond_questions)
                )

        if speaks_id_eff:
            greeting_instr = (
                f"INSTRUKSI PENTING — JANGAN BERTANYA DI AWAL. "
                f"{'Sapa pasien dengan nama ' + p_name + ' sepanjang percakapan. ' if p_name else ''}"
                "Langsung berikan penjelasan lengkap dan terstruktur tentang hasil asesmen pasien. "
                "Monolog pembuka Anda harus mencakup SEMUA hal berikut:\n"
                "1. SEBUTKAN skor risiko yang tepat dan artinya bagi pasien secara personal.\n"
                "2. JELASKAN setiap vaksin yang direkomendasikan satu per satu — nama vaksin, mengapa dibutuhkan berdasarkan usia dan kondisi pasien, dan penyakit apa yang dilindungi.\n"
                "3. SAMPAIKAN tingkat urgensi dan langkah selanjutnya.\n"
                "4. BARU SETELAH ITU, tanyakan pertanyaan klinis spesifik per kondisi secara percakapan alami.\n"
                "Jika pasien memotong pembicaraan Anda, SEGERA berhenti dan katakan 'Silakan, saya mendengarkan.' "
                "Jangan pernah berbicara melewati pasien."
                + cond_question_section
            )
        else:
            greeting_instr = (
                f"CRITICAL INSTRUCTION — DO NOT ASK QUESTIONS AT THE START. "
                f"{'Address the patient as ' + p_name + ' throughout. ' if p_name else ''}"
                "Immediately deliver a complete, structured explanation of the patient's assessment. "
                "Your opening monologue must cover ALL of the following:\n"
                "1. STATE their exact risk score and what it means personally.\n"
                "2. EXPLAIN each recommended vaccine one by one — name, why needed for their specific conditions, what it prevents.\n"
                "3. STATE urgency and next steps.\n"
                "4. THEN ask condition-specific clinical questions conversationally, one at a time.\n"
                "If the patient interrupts you at any point, IMMEDIATELY stop and say 'Please go ahead — I'm listening.' "
                "Never speak over the patient."
                + cond_question_section
            )

        patient_section = (
            "\n\n--- PATIENT ASSESSMENT DATA (from Immunization Assistant) ---\n"
            f"{name_line}"
            f"Risk Level: {risk.get('level','Unknown')} ({risk.get('percentage','?')}%)\n"
            f"Risk Advice: {risk.get('advice','')}\n"
            f"Age: {age}\n"
            f"Health Conditions: {conditions_str}\n"
            f"Travel Regions: {', '.join(travel) if travel else 'None'}\n"
            f"Recommended Vaccines: {vaccines_str}\n"
            f"AI Summary: {summary}\n"
            "---\n\n"
            + greeting_instr
        )
        full_context = base_context + patient_section

        # Build a rich opening greeting that delivers the full result immediately
        name_part = f"{p_name}! " if p_name else ""
        risk_pct   = risk.get("percentage", "?")
        risk_level = risk.get("level", "Unknown")
        risk_advice = risk.get("advice", "")
        top_vaccines = vaccines[:4] if vaccines else []
        vacc_list  = ", ".join(top_vaccines) if top_vaccines else "beberapa vaksin penting"

        speaks_id = speaks_id_eff   # already computed above

        if speaks_id:
            greeting = (
                f"Halo {name_part}Saya {doctor['name']}. "
                f"Saya baru saja selesai meninjau hasil asesmen CareMate Anda, "
                f"jadi izinkan saya menjelaskan hasilnya sekarang. "
                f"Skor risiko Anda adalah {risk_pct}%, yang menempatkan Anda dalam kategori {risk_level}. "
                f"{risk_advice} "
                f"Berdasarkan profil kesehatan Anda, saya merekomendasikan vaksin-vaksin berikut: {vacc_list}. "
                f"Saya akan menjelaskan masing-masing vaksin dan alasannya secara spesifik untuk Anda — "
                f"silakan tanyakan apa saja setelah saya selesai menjelaskan."
            )
        else:
            greeting = (
                f"Hello {name_part}I'm {doctor['name']}. "
                f"I've just finished reviewing your CareMate assessment, so let me walk you through your results right now. "
                f"Your risk score is {risk_pct}%, which places you in the {risk_level} category. "
                f"{risk_advice} "
                f"Based on your profile, the vaccines I'm recommending for you are: {vacc_list}. "
                f"I'll explain each one and why it's important for you specifically — then please feel free to ask me anything."
            )
    else:
        full_context = base_context
        # No assessment context — greet by name if we have one, and ask how to help
        p_name = (data.get("patient_name") or "").strip()
        if p_name:
            speaks_id = (lang_override == "indonesian") or \
                        (lang_override is None and "Bahasa Indonesia" in doctor.get("languages", []))
            if speaks_id:
                greeting = (f"Halo {p_name}! Saya {doctor['name']}. "
                            f"Senang bertemu dengan Anda. Apa yang bisa saya bantu hari ini?")
            else:
                greeting = (f"Hi {p_name}! I'm {doctor['name']}. "
                            f"It's good to meet you. How can I help you today?")
            full_context = base_context + (
                f"\n\nThe patient's name is {p_name}. Greet them warmly by name and ask "
                f"how you can help. They have not completed an assessment yet, so let them "
                f"lead the conversation."
            )
        else:
            greeting = _doctor_greeting(doctor, lang_override)

    # Append lab context if provided (from lab results panel)
    if lab_ctx_str:
        full_context = full_context + "\n\n" + lab_ctx_str
        # Override greeting to open with lab results
        speaks_id_lab = (lang_override == "indonesian") or \
                        (lang_override is None and "Bahasa Indonesia" in doctor.get("languages", []))
        if speaks_id_lab:
            greeting = (
                f"Halo, saya {doctor['name']}. Saya sudah melihat hasil lab Anda yang baru masuk dan ada beberapa hal penting yang ingin saya diskusikan dengan Anda. "
                "Mari kita bahas bersama."
            )
        else:
            greeting = (
                f"Hello, I'm {doctor['name']}. I've just reviewed your latest lab results and there are some important findings I want to walk you through. "
                "Let's go through them together."
            )

    # Determine Tavus language: override > doctor profile
    if lang_override in ("indonesian", "english"):
        tavus_language = lang_override
    else:
        tavus_language = "indonesian" if "Bahasa Indonesia" in doctor.get("languages", []) else "english"

    payload = {
        "replica_id":             replica_id,
        "conversation_name":      f"CareMate Consult — {doctor['name']}",
        "conversational_context": full_context,
        "custom_greeting":        greeting,
        "properties": {
            "max_call_duration":        3600,
            "participant_left_timeout": 60,
            "enable_recording":         False,
            "apply_greenscreen":        False,
            "language":                 tavus_language
        }
    }

    try:
        resp = http_req.post(
            f"{TAVUS_BASE}/conversations",
            headers=_tavus_headers(),
            json=payload,
            timeout=20
        )
        result = resp.json()
        print(f"[Tavus] Conversation created: {result.get('conversation_id')} status={resp.status_code}")
        return jsonify(result), resp.status_code
    except Exception as e:
        print(f"[Tavus] Error creating conversation: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/tavus/conversation/<conversation_id>", methods=["DELETE"])
def tavus_end_conversation(conversation_id):
    """End / clean up a Tavus conversation."""
    if not TAVUS_ENABLED:
        return jsonify({"error": "Tavus not configured"}), 503
    try:
        resp = http_req.delete(
            f"{TAVUS_BASE}/conversations/{conversation_id}",
            headers=_tavus_headers(),
            timeout=10
        )
        print(f"[Tavus] Ended conversation {conversation_id}: {resp.status_code}")
        return jsonify({"status": "ended", "code": resp.status_code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/prescription", methods=["POST"])
@limiter.limit("5 per minute")
def generate_prescription():
    """Generate a clinical vaccination prescription from the consultation history."""
    from datetime import date as _date
    data        = request.json or {}
    doctor_id   = data.get("doctor_id", 1)
    doctor      = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])
    patient_name = data.get("patient_name", "Pasien")
    history     = data.get("history", [])          # text-chat conversation turns
    assessment  = data.get("assessment", {})       # localStorage assessment snapshot
    language    = data.get("language", "indonesian")

    risk        = assessment.get("risk", {})
    vaccines    = assessment.get("vaccines", [])
    form        = assessment.get("form", {})
    conditions  = form.get("conditions", [])
    age         = form.get("age", "unknown")
    today       = _date.today().strftime("%d %B %Y")

    # Condense conversation to a readable transcript
    convo_lines = []
    for m in history[-40:]:
        role  = "Dokter" if m.get("role") == "assistant" else "Pasien"
        convo_lines.append(f"{role}: {m.get('content','')}")
    convo_text = "\n".join(convo_lines) if convo_lines else "(Belum ada percakapan teks)"

    cond_str    = ', '.join(conditions) if conditions else ('Tidak ada kondisi khusus' if language == 'indonesian' else 'No specific conditions')
    vacc_str    = ', '.join(vaccines)   if vaccines   else ('Tidak ada' if language == 'indonesian' else 'None')

    if language == "indonesian":
        prompt = f"""Anda adalah {doctor['name']}, {doctor['specialty']} di {doctor['hospital']}, {doctor['city']}.
Tanggal: {today}. Pasien: {patient_name}, usia {age} tahun.
Kondisi penyerta: {cond_str}.
Tingkat risiko imunisasi: {risk.get('level','?')} ({risk.get('percentage','?')}%).
Vaksin yang direkomendasikan sistem: {vacc_str}.

Riwayat percakapan konsultasi:
{convo_text}

Buatlah resep vaksinasi klinis yang lengkap dan profesional seperti yang akan ditulis oleh dokter spesialis untuk rekam medis resmi.
Untuk setiap vaksin, sertakan nama dagang (brand name) yang tersedia di Indonesia, kode ICD-10 yang relevan, dan dosis yang tepat.
Kembalikan HANYA JSON valid (tidak ada teks di luar JSON):
{{
  "clinical_notes": "Catatan klinis singkat 1-2 kalimat tentang profil risiko pasien ini",
  "diagnosis_codes": ["kode ICD-10 relevan, mis. Z23, Z24, dll."],
  "vaccines": [
    {{
      "name": "Nama vaksin lengkap (nama dagang di Indonesia)",
      "generic_name": "nama generik",
      "icd10": "kode ICD-10 untuk vaksin ini",
      "dose": "mis. 0,5 mL IM deltoid",
      "route": "Intramuskular / Subkutan / Oral",
      "schedule": "jadwal spesifik mis. Dosis 1 hari ini, Dosis 2 dalam 6-12 bulan",
      "brand_options": "nama dagang tersedia di Indonesia",
      "indication": "indikasi klinis spesifik untuk pasien ini",
      "contraindications": "kontraindikasi jika ada, atau 'Tidak ada'",
      "priority": "urgent atau routine"
    }}
  ],
  "instructions": "Instruksi pasca-vaksinasi terperinci (observasi 15-30 menit, efek samping yang diharapkan, dll.)",
  "follow_up": "Jadwal kontrol ulang dan vaksinasi lanjutan",
  "warnings": "Peringatan klinis berdasarkan kondisi penyerta pasien, atau kosong jika tidak ada",
  "prescriber_note": "Catatan singkat untuk apoteker / tenaga kesehatan yang memberikan vaksin"
}}"""
    else:
        prompt = f"""You are {doctor['name']}, {doctor['specialty']} at {doctor['hospital']}, {doctor['city']}.
Date: {today}. Patient: {patient_name}, age {age}.
Comorbidities: {cond_str}.
Immunisation risk level: {risk.get('level','?')} ({risk.get('percentage','?')}%).
System-recommended vaccines: {vacc_str}.

Consultation transcript:
{convo_text}

Generate a complete, professional clinical vaccination prescription as a specialist would write for an official medical record.
For each vaccine include the trade name available in Indonesia, relevant ICD-10 code, and precise dosing.
Return ONLY valid JSON (no text outside JSON):
{{
  "clinical_notes": "Brief 1-2 sentence clinical note on this patient's risk profile",
  "diagnosis_codes": ["relevant ICD-10 codes e.g. Z23, Z24, etc."],
  "vaccines": [
    {{
      "name": "Full vaccine name (trade name available in Indonesia)",
      "generic_name": "generic name",
      "icd10": "ICD-10 code for this vaccination",
      "dose": "e.g. 0.5 mL IM deltoid",
      "route": "Intramuscular / Subcutaneous / Oral",
      "schedule": "specific schedule e.g. Dose 1 today, Dose 2 in 6-12 months",
      "brand_options": "available trade names in Indonesia",
      "indication": "clinical indication specific to this patient",
      "contraindications": "contraindications if any, or 'None'",
      "priority": "urgent or routine"
    }}
  ],
  "instructions": "Detailed post-vaccination instructions (observe 15-30 min, expected side effects, etc.)",
  "follow_up": "Follow-up schedule and subsequent vaccinations",
  "warnings": "Clinical warnings based on patient comorbidities, or empty if none",
  "prescriber_note": "Brief note for pharmacist / vaccinating healthcare worker"
}}"""

    if not client:
        # Fallback: build a basic prescription from assessment data alone
        fallback_vaccines = [
            {"name": v, "dose": "1 dosis IM", "schedule": "Sesegera mungkin",
             "reason": "Direkomendasikan berdasarkan profil kesehatan", "priority": "routine"}
            for v in (vaccines[:6] if vaccines else ["Influenza", "Pneumococcal"])
        ]
        prescription = {
            "vaccines": fallback_vaccines,
            "instructions": "Istirahat setelah vaksinasi. Tetap di klinik 15-30 menit untuk observasi.",
            "follow_up": "Kontrol ulang dalam 4 minggu",
            "warnings": ""
        }
    else:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=900,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            prescription = json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"[Prescription] GPT error: {e}")
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "doctor":   {"name": doctor["name"], "specialty": doctor["specialty"],
                     "hospital": doctor["hospital"], "city": doctor["city"]},
        "patient":  patient_name,
        "date":     today,
        "language": language,
        "prescription": prescription
    })


@app.route("/api/did/stream/start", methods=["POST"])
def did_stream_start():
    if not DID_ENABLED:
        return jsonify({"error": "D-ID not configured"}), 503
    data = request.json
    doctor_id = data.get("doctor_id", 1)
    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])

    # Close any previously tracked streams to avoid "Max sessions" error
    for sid, sess in list(_did_active_streams.items()):
        _did_close_stream(sid, sess)
        _did_active_streams.pop(sid, None)

    try:
        resp = http_req.post(
            "https://api.d-id.com/talks/streams",
            headers=_did_headers(),
            json={"source_url": doctor.get("did_photo") or doctor["photo"]},
            timeout=15
        )
        result = resp.json()
        if result.get("id"):
            _did_active_streams[result["id"]] = result.get("session_id", "")
        # Pass auth token so browser can call D-ID directly for SDP/ICE
        result["auth"] = "Basic " + base64.b64encode(_did_key.encode()).decode()
        return jsonify(result), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/did/stream/sdp", methods=["POST"])
def did_stream_sdp():
    if not DID_ENABLED:
        return jsonify({"error": "D-ID not configured"}), 503
    data = request.json
    stream_id = data["stream_id"]
    try:
        resp = http_req.post(
            f"https://api.d-id.com/talks/streams/{stream_id}/sdp",
            headers=_did_headers(),
            json={"answer": data["answer"], "session_id": data["session_id"]},
            timeout=10
        )
        return (resp.text or "{}", resp.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/did/stream/ice", methods=["POST"])
def did_stream_ice():
    if not DID_ENABLED:
        return jsonify({"error": "D-ID not configured"}), 503
    data = request.json
    stream_id = data["stream_id"]
    try:
        resp = http_req.post(
            f"https://api.d-id.com/talks/streams/{stream_id}/ice",
            headers=_did_headers(),
            json={
                "candidate":     data.get("candidate", ""),
                "sdpMid":        data.get("sdpMid", ""),
                "sdpMLineIndex": data.get("sdpMLineIndex", 0),
                "session_id":    data["session_id"]
            },
            timeout=10
        )
        return (resp.text or "{}", resp.status_code, {"Content-Type": "application/json"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/did/stream/talk", methods=["POST"])
def did_stream_talk():
    if not DID_ENABLED:
        return jsonify({"error": "D-ID not configured"}), 503
    data = request.json
    try:
        resp = http_req.post(
            f"https://api.d-id.com/talks/streams/{data['stream_id']}",
            headers=_did_headers(),
            json={
                "session_id": data["session_id"],
                "script": {
                    "type": "text",
                    "input": data.get("text", "")[:2000],
                    "provider": {"type": "microsoft", "voice_id": data.get("voice_id", "en-US-JennyNeural")}
                },
                "config": {"stitch": True}
            },
            timeout=15
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/did/stream/stop", methods=["POST"])
def did_stream_stop():
    if not DID_ENABLED:
        return jsonify({"error": "D-ID not configured"}), 503
    data = request.json
    stream_id = data.get("stream_id", "")
    _did_close_stream(stream_id, data.get("session_id", ""))
    _did_active_streams.pop(stream_id, None)
    return jsonify({"status": "closed"})


# ══════════════════════════════════════════════════════════
#  VACCINE CERTIFICATE
# ══════════════════════════════════════════════════════════

@app.route("/dashboard/certificate/<int:record_id>")
@login_required
def download_certificate(record_id):
    record = VaccinationRecord.query.filter_by(
        id=record_id, user_id=current_user.id
    ).first_or_404()
    from certificate import generate_certificate_pdf
    pdf_bytes = generate_certificate_pdf(record, current_user)
    resp = Response(pdf_bytes, content_type="application/pdf")
    safe_name = record.vaccine_name.replace(" ", "_").replace("/", "-")[:30]
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="CareMate-Certificate-{safe_name}.pdf"'
    )
    return resp


@app.route("/verify/<cert_id>")
def verify_certificate(cert_id):
    """Public verification page — anyone can scan the QR code to verify."""
    try:
        record_id = int(cert_id.replace("CM-", ""))
    except ValueError:
        return render_template("certificate_verify.html", record=None, user=None)
    record = VaccinationRecord.query.get(record_id)
    owner  = User.query.get(record.user_id) if record else None
    return render_template("certificate_verify.html", record=record, user=owner)


# ══════════════════════════════════════════════════════════
#  ONBOARDING FLOW
# ══════════════════════════════════════════════════════════

def _onboarding_context(user):
    has_profile    = bool(user.date_of_birth and user.sex)
    has_assessment = Assessment.query.filter_by(user_id=user.id).first() is not None
    has_vaccine    = (VaccinationRecord.query.filter_by(user_id=user.id).first() is not None or
                      Booking.query.filter_by(user_id=user.id).first() is not None)
    steps_done = sum([True, has_profile, has_assessment, has_vaccine])
    progress   = int(steps_done / 4 * 100)
    return dict(has_profile=has_profile, has_assessment=has_assessment,
                has_vaccine=has_vaccine, steps_done=steps_done,
                steps_total=4, progress=progress)


@app.route("/onboarding")
@login_required
def onboarding():
    ctx = _onboarding_context(current_user)
    if ctx["progress"] == 100:
        return redirect(url_for("dashboard"))
    return render_template("onboarding.html", **ctx)


@app.route("/onboarding/profile", methods=["POST"])
@login_required
def onboarding_profile():
    dob_str = request.form.get("dob", "")
    sex     = request.form.get("sex", "")
    phone   = request.form.get("phone", "").strip() or None
    wa_opt  = request.form.get("whatsapp_opt_in") == "on"

    if dob_str:
        try:
            current_user.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    if sex:
        current_user.sex = sex
    current_user.phone = phone
    current_user.whatsapp_opt_in = wa_opt
    db.session.commit()

    ctx = _onboarding_context(current_user)
    if ctx["has_assessment"]:
        return redirect(url_for("dashboard"))
    return redirect(url_for("onboarding"))


# ══════════════════════════════════════════════════════════
#  REFERRAL / REVENUE TRACKING
# ══════════════════════════════════════════════════════════

@app.route("/dashboard/referrals")
@login_required
def referral_dashboard():
    """Personal referral tracking — bookings made, estimated revenue."""
    bookings = Booking.query.filter_by(user_id=current_user.id)\
        .order_by(Booking.appointment_date.desc()).all()
    total_referral = sum(b.referral_fee or 0 for b in bookings)

    # Per-clinic breakdown
    clinic_stats = {}
    for b in bookings:
        cname = b.clinic.name + " " + (b.clinic.branch or "")
        if cname not in clinic_stats:
            clinic_stats[cname] = {"bookings": 0, "revenue": 0}
        clinic_stats[cname]["bookings"] += 1
        clinic_stats[cname]["revenue"]  += b.referral_fee or 0

    return render_template("referral_dashboard.html",
                           bookings=bookings,
                           total_referral=total_referral,
                           clinic_stats=clinic_stats)


@app.route("/admin/referrals")
def admin_referrals():
    """Admin-level view: all bookings and referral revenue across all users."""
    # Simple admin check via secret param — replace with proper admin auth in prod
    if request.args.get("key") != os.environ.get("ADMIN_KEY", "caremate-admin"):
        return "Unauthorised", 403

    all_bookings = Booking.query.order_by(Booking.created_at.desc()).all()
    total = sum(b.referral_fee or 0 for b in all_bookings)

    # Per-clinic breakdown
    clinic_stats = {}
    for b in all_bookings:
        key = b.clinic.name + " " + (b.clinic.branch or "")
        if key not in clinic_stats:
            clinic_stats[key] = {"bookings": 0, "revenue": 0, "confirmed": 0}
        clinic_stats[key]["bookings"] += 1
        clinic_stats[key]["revenue"]  += b.referral_fee or 0
        if b.status == "confirmed":
            clinic_stats[key]["confirmed"] += 1

    return render_template("referral_dashboard.html",
                           bookings=all_bookings,
                           total_referral=total,
                           clinic_stats=clinic_stats,
                           is_admin=True)


# ══════════════════════════════════════════════════════════
#  EMAIL REMINDER SEND (manual trigger for testing)
# ══════════════════════════════════════════════════════════

def send_email_reminder(to_email, user_name, vaccine_name, reminder_date, days_until):
    """Send an HTML vaccination reminder email. No-ops gracefully if MAIL not configured."""
    if not app.config.get("MAIL_USERNAME"):
        print(f"[Email MOCK] → {to_email} | {vaccine_name} in {days_until} days")
        return True
    try:
        html = render_template(
            "email/reminder.html",
            user_name=user_name,
            vaccine_name=vaccine_name,
            reminder_date=reminder_date.strftime("%d %B %Y"),
            days_until=days_until
        )
        subject = {0: f"⏰ Hari Ini — Jadwal Vaksin {vaccine_name}",
                   1: f"🔔 Besok — Vaksin {vaccine_name}",
                  }.get(days_until, f"📅 {days_until} Hari Lagi — Vaksin {vaccine_name}")

        msg = MailMessage(subject=subject, recipients=[to_email], html=html)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[Email ERROR] {e}")
        return False


# Expose email helper to reminders module
app.send_email_reminder = send_email_reminder


# Exempt all /api/* routes from CSRF — they're called via fetch() with JSON,
# not HTML form submissions. Must be done after all routes are registered.
for _rule in app.url_map.iter_rules():
    if _rule.rule.startswith('/api/'):
        csrf.exempt(app.view_functions[_rule.endpoint])

if __name__ == "__main__":
    from reminders import start_scheduler
    start_scheduler(app)
    app.run(debug=True, port=5050)
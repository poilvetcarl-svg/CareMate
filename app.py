from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context
from flask_cors import CORS
from openai import OpenAI
import os
import json
import math
import base64
import requests as http_req
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vacc-dev-secret-2024")
CORS(app)

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

# Dedicated doctor stock replicas (phoenix-3/4) — auto-selected by doctor gender
TAVUS_MALE_REPLICA   = "r621a6013477"   # Raj - Doctor (phoenix-4)
TAVUS_FEMALE_REPLICA = "rd3ba0f30551"   # Olivia - Doctor (phoenix-3)

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
_TAVUS_VIDEO_FEMALE = "https://cdn.replica.tavus.io/20310/f5d5455f_normalized.mp4"  # Olivia - Doctor (phoenix-3)

DOCTORS = [
    {"id": 1, "name": "Dr. Budi Santoso", "specialty": "Internal Medicine & Infectious Disease", "hospital": "RS Pondok Indah", "city": "Jakarta Selatan", "lat": -6.2615, "lng": 106.7890, "rating": 4.9, "reviews": 312, "fee": "Rp 250.000", "available": True, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "15 years", "slots": ["09:00", "10:30", "14:00", "15:30"], "gender": "male", "tts_voice": "onyx"},
    {"id": 2, "name": "Dr. Sari Dewi, Sp.PD", "specialty": "Vaccinology & Travel Medicine", "hospital": "RSUP Cipto Mangunkusumo", "city": "Jakarta Pusat", "lat": -6.1924, "lng": 106.8455, "rating": 4.8, "reviews": 487, "fee": "Rp 300.000", "available": True, "languages": ["Bahasa Indonesia", "English", "Dutch"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "18 years", "slots": ["08:00", "11:00", "13:00"], "gender": "female", "tts_voice": "nova"},
    {"id": 3, "name": "Dr. Ahmad Fauzi, Sp.A", "specialty": "Pediatric & Adult Immunization", "hospital": "RS Siloam Hospitals", "city": "Tangerang", "lat": -6.2388, "lng": 106.6402, "rating": 4.7, "reviews": 256, "fee": "Rp 200.000", "available": True, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "12 years", "slots": ["10:00", "14:30", "16:00"], "gender": "male", "tts_voice": "echo"},
    {"id": 4, "name": "Dr. Maya Kusuma, M.D.", "specialty": "Family Medicine & Preventive Health", "hospital": "Klinik Pratama SehatKu", "city": "Bekasi", "lat": -6.2349, "lng": 106.9896, "rating": 4.6, "reviews": 198, "fee": "Rp 150.000", "available": True, "languages": ["Bahasa Indonesia"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "8 years", "slots": ["09:30", "11:30", "15:00", "17:00"], "gender": "female", "tts_voice": "shimmer"},
    {"id": 5, "name": "Dr. Hendro Wibowo, Sp.PD", "specialty": "Internal Medicine & Immunology", "hospital": "RS Medistra", "city": "Jakarta Selatan", "lat": -6.2297, "lng": 106.8261, "rating": 4.9, "reviews": 541, "fee": "Rp 350.000", "available": False, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_MALE, "experience": "22 years", "slots": ["Next week"], "gender": "male", "tts_voice": "onyx"},
    {"id": 6, "name": "Dr. Ratna Puspita, Sp.MK", "specialty": "Clinical Microbiology & Vaccines", "hospital": "RS Hermina Jatinegara", "city": "Jakarta Timur", "lat": -6.2131, "lng": 106.8703, "rating": 4.7, "reviews": 173, "fee": "Rp 200.000", "available": True, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "10 years", "slots": ["08:30", "12:00", "16:30"], "gender": "female", "tts_voice": "nova"},
    {"id": 7, "name": "Dr. Irwan Prasetyo, PhD", "specialty": "Epidemiology & Travel Medicine", "hospital": "RS Premier Bintaro", "city": "Tangerang Selatan", "lat": -6.3013, "lng": 106.7312, "rating": 4.8, "reviews": 329, "fee": "Rp 280.000", "available": True, "languages": ["Bahasa Indonesia", "English", "German"], "photo": _TAVUS_VIDEO_MALE, "experience": "14 years", "slots": ["09:00", "13:30", "15:00"], "gender": "male", "tts_voice": "echo"},
    {"id": 8, "name": "Dr. Dian Rahayu, Sp.KK", "specialty": "Dermatology & HPV Specialist", "hospital": "Klinik Vaksin Indonesia", "city": "Surabaya", "lat": -7.2574, "lng": 112.7521, "rating": 4.6, "reviews": 215, "fee": "Rp 175.000", "available": True, "languages": ["Bahasa Indonesia", "English"], "photo": _TAVUS_VIDEO_FEMALE, "experience": "9 years", "slots": ["10:30", "14:00", "16:00"], "gender": "female", "tts_voice": "shimmer"}
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

    return {
        "score": score,
        "percentage": pct,
        "level": level,
        "color": color,
        "emoji": emoji,
        "advice": advice,
        "factors": factors
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/recommend", methods=["POST"])
def recommend():
    data = request.json
    risk = calculate_risk_score(data)
    vaccines = get_recommended_vaccines(data)

    ai_summary = ""
    if client:
        try:
            conditions_text = ", ".join(data.get("conditions", [])) or "none reported"
            travel_text = ", ".join(data.get("travel_regions", [])) or "no international travel"
            vaccine_names = ", ".join([v["name"] for v in vaccines[:6]])

            prompt = f"""You are a clinical vaccination expert. A patient has:
- Age: {data.get('age')} years old
- Medical conditions: {conditions_text}
- Pregnancy: {data.get('pregnant', 'no')}
- Travel plans: {travel_text}
- Risk level: {risk['level']} ({risk['percentage']}%)
- Recommended vaccines: {vaccine_names}

Write a warm, professional 3-4 sentence clinical summary explaining:
1. Their overall vaccine-preventable disease risk
2. The most important vaccines for their profile
3. A brief motivating statement about the importance of vaccination

Be empathetic, clear, and avoid medical jargon. Do not use bullet points."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.7
            )
            ai_summary = response.choices[0].message.content
        except Exception as e:
            ai_summary = f"Based on your health profile, we have identified {len(vaccines)} vaccines recommended for you. Your {risk['level'].lower()} classification indicates that timely vaccination is important for protecting your health. Please consult with a healthcare provider to discuss your personalized immunization schedule."

    return jsonify({
        "risk": risk,
        "vaccines": vaccines,
        "ai_summary": ai_summary,
        "total_vaccines": len(vaccines)
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    conversation_history = data.get("history", [])

    if not client:
        return jsonify({"reply": "⚠️ AI assistant not configured. Please add your OPENAI_API_KEY to the .env file to enable the chatbot.", "error": True})

    system_prompt = """You are an Immunization Assistant, a highly knowledgeable vaccination specialist assistant. You have deep expertise in immunology, vaccinology, and public health following CDC, WHO, and Indonesian Ministry of Health (Kemenkes) guidelines.

Your knowledge covers:
- All adult vaccines: Influenza, COVID-19, Tdap/Td, MMR, Varicella, Herpes Zoster (Recombinant), HPV, Pneumococcal, RSV, Hepatitis A & B, Meningococcal (MenACWY, MenB), Typhoid, Yellow Fever, Japanese Encephalitis, Rabies, Cholera
- Vaccine schedules, catch-up schedules, and booster timing
- Contraindications and precautions for each vaccine
- Immunocompromised patients, pregnancy, elderly, and other special populations
- Vaccine mechanisms (mRNA, live-attenuated, inactivated, subunit, conjugate, toxoid)
- Common and rare adverse events — rates, management, reporting
- Cold chain, storage requirements, and administration
- Travel medicine and destination-specific requirements
- Indonesia-specific vaccination programs and availability
- Drug interactions and timing between vaccines
- Vaccine hesitancy: addressing myths with evidence

Response rules:
- Give specific, accurate, evidence-based answers to EVERY question
- Never give the same generic response twice — tailor every reply to what was asked
- Be concise but complete (3-5 sentences for most questions)
- Use numbers and statistics when helpful (e.g., "91% efficacy", "1 in 1 million risk")
- If a question is outside vaccines/immunization, politely redirect
- Acknowledge uncertainty when it exists rather than guessing
- For personal medical decisions, recommend consulting a doctor — but still answer the question
- Do NOT add unnecessary disclaimers to every message"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-14:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=350,
            temperature=0.6
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = f"I encountered an error: {str(e)}. Please try again."

    return jsonify({"reply": reply})


@app.route("/consultation/<int:doctor_id>")
def consultation(doctor_id):
    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), DOCTORS[0])
    return render_template("consultation.html", doctor=doctor)


@app.route("/api/consult", methods=["POST"])
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

    system_prompt = f"""You are {doctor['name']}, a {doctor['specialty']} specialist at {doctor['hospital']} in {doctor['city']}, Indonesia.
You are conducting a live video teleconsultation through the Immunization Assistant platform.
{name_line}

Your clinical persona:
- You are warm, professional, and speak naturally as in a real consultation
- You have {doctor['experience']} of clinical experience in vaccinology and preventive medicine
- You speak {'Indonesian and English' if 'Bahasa Indonesia' in doctor['languages'] else 'English'}
- You follow CDC, WHO, and Indonesian Kemenkes vaccination guidelines

Consultation flow:
1. Greet the patient warmly (first message only)
2. Ask about their health concerns, medical history, or vaccine questions
3. Provide thorough, personalized advice based on what they share
4. Discuss specific vaccines, timing, what to expect, preparation
5. End each turn with one focused follow-up question to gather more information

Clinical knowledge you must demonstrate:
- Vaccine-disease relationships for conditions like diabetes, heart disease, HIV, cancer, kidney disease
- Exact vaccine schedules, doses, intervals
- Side effect management and what's normal vs concerning
- Contraindications based on patient profile
- Indonesian vaccine availability, pricing, and clinic recommendations

Style rules:
- Speak in first person as the doctor ("I recommend...", "In my experience...")
- Keep responses to 3-5 sentences — this is a live conversation, not an essay
- Be warm and specific, not generic
- Never repeat the same phrases across turns
- Reference what the patient told you in previous turns to show you're listening"""

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
                temperature=0.7,
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
        greeting = _doctor_greeting(doctor, lang_override)

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
            json={"source_url": doctor["photo"]},
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


if __name__ == "__main__":
    app.run(debug=True, port=5050)
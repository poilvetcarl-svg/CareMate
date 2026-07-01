"""
CareMate, Database Models
SQLite + SQLAlchemy ORM
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

db = SQLAlchemy()

# ── USER ──────────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name          = db.Column(db.String(100))
    phone         = db.Column(db.String(25))          # WhatsApp number e.g. +628123456789
    date_of_birth = db.Column(db.Date)
    sex           = db.Column(db.String(10))
    company_id    = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    role          = db.Column(db.String(20), default='user')   # user | corporate_admin
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    whatsapp_opt_in = db.Column(db.Boolean, default=False)

    assessments         = db.relationship('Assessment',        backref='user', lazy=True, cascade='all, delete-orphan')
    vaccination_records = db.relationship('VaccinationRecord', backref='user', lazy=True, cascade='all, delete-orphan')
    reminders           = db.relationship('VaccineReminder',   backref='user', lazy=True, cascade='all, delete-orphan')
    bookings            = db.relationship('Booking',           backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def age(self):
        if self.date_of_birth:
            today = date.today()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None

    def latest_assessment(self):
        return Assessment.query.filter_by(user_id=self.id)\
               .order_by(Assessment.created_at.desc()).first()

    def pending_reminders(self):
        return VaccineReminder.query.filter_by(user_id=self.id, sent=False)\
               .order_by(VaccineReminder.reminder_date).all()

    def __repr__(self):
        return f'<User {self.email}>'


# ── ASSESSMENT ────────────────────────────────────────────────────────────────
class Assessment(db.Model):
    id                   = db.Column(db.Integer, primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    age                  = db.Column(db.Integer)
    sex                  = db.Column(db.String(10))
    conditions           = db.Column(db.Text)    # JSON list
    travel_regions       = db.Column(db.Text)    # JSON list
    pregnant             = db.Column(db.Boolean, default=False)
    risk_score           = db.Column(db.Float)
    risk_level           = db.Column(db.String(20))
    vaccines_recommended = db.Column(db.Text)    # JSON list of vaccine keys
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)


# ── CHILD (family immunization tracking) ─────────────────────────────────────
class Child(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    sex           = db.Column(db.String(10))   # male | female
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    parent  = db.relationship('User', backref=db.backref('children', lazy=True, cascade='all, delete-orphan'))
    records = db.relationship('VaccinationRecord', backref='child', lazy=True)

    @property
    def age_months(self):
        today = date.today()
        return (today.year - self.date_of_birth.year) * 12 + (today.month - self.date_of_birth.month) \
               - (1 if today.day < self.date_of_birth.day else 0)

    @property
    def age_label(self):
        m = self.age_months
        if m < 1:  return "newborn"
        if m < 24: return f"{m} mo"
        return f"{m // 12} yr"


# ── LAB RESULT (photo-extracted or manually entered) ─────────────────────────
class LabResult(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    test_key   = db.Column(db.String(50))            # matches lab_reference.json, or None for custom
    test_name  = db.Column(db.String(120), nullable=False)
    value      = db.Column(db.Float, nullable=False)
    unit       = db.Column(db.String(30))
    flag       = db.Column(db.String(10), default='unknown')   # normal | high | low | unknown
    date_taken = db.Column(db.Date, default=date.today)
    source     = db.Column(db.String(10), default='manual')    # manual | photo
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('lab_results', lazy=True, cascade='all, delete-orphan'))


# ── CONSULTATION SUMMARY (saved after each AI teleconsultation) ───────────────
class ConsultationSummary(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_name      = db.Column(db.String(120))
    doctor_specialty = db.Column(db.String(160))
    summary          = db.Column(db.Text, nullable=False)
    transcript       = db.Column(db.Text)            # JSON of the last messages
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('consultations', lazy=True, cascade='all, delete-orphan'))


# ── TAVUS VIDEO SESSION (maps a Tavus conversation to the user so we can save its
#    transcript/summary when Tavus delivers it via webhook after the call) ──────
class TavusSession(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    conversation_id  = db.Column(db.String(120), unique=True, index=True, nullable=False)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_name      = db.Column(db.String(120))
    doctor_specialty = db.Column(db.String(160))
    saved            = db.Column(db.Boolean, default=False)   # transcript already turned into a ConsultationSummary
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)


# ── OUTBOUND LINK CLICK (partner referral tracking, for proving click-through) ─
class LinkClick(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    partner    = db.Column(db.String(80), index=True)    # network / partner name
    clinic_id  = db.Column(db.Integer)                    # nullable
    kind       = db.Column(db.String(20))                 # book | whatsapp | partner
    dest       = db.Column(db.String(300))
    user_id    = db.Column(db.Integer)                    # nullable (anonymous ok)
    referrer   = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


# ── WEARABLE / SMARTWATCH CONNECTION (demo: simulated metrics) ────────────────
class WearableDevice(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    provider     = db.Column(db.String(60))            # e.g. "Apple Watch", "Fitbit Sense"
    connected_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('wearable', uselist=False, cascade='all, delete-orphan'))


# ── DAILY WELLBEING CHECK-IN (the companion "how do you feel today") ──────────
class DailyCheckin(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day        = db.Column(db.Date, default=date.today, index=True)
    body       = db.Column(db.Integer)   # 1 (unwell) .. 5 (great)
    mind       = db.Column(db.Integer)   # 1 (exhausted) .. 5 (great)
    note       = db.Column(db.String(280))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('checkins', lazy=True, cascade='all, delete-orphan'))


# ── VACCINATION RECORD ────────────────────────────────────────────────────────
class VaccinationRecord(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    child_id       = db.Column(db.Integer, db.ForeignKey('child.id'), nullable=True)  # set when the dose belongs to a child
    vaccine_key    = db.Column(db.String(50),  nullable=False)
    vaccine_name   = db.Column(db.String(120), nullable=False)
    date_given     = db.Column(db.Date,        nullable=False)
    dose_number    = db.Column(db.Integer,     default=1)
    clinic_name    = db.Column(db.String(150))
    batch_number   = db.Column(db.String(60))
    notes          = db.Column(db.Text)
    next_dose_date = db.Column(db.Date)        # for multi-dose vaccines
    created_at     = db.Column(db.DateTime,    default=datetime.utcnow)


# ── VACCINE REMINDER ──────────────────────────────────────────────────────────
class VaccineReminder(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vaccine_key   = db.Column(db.String(50),  nullable=False)
    vaccine_name  = db.Column(db.String(120), nullable=False)
    reminder_date = db.Column(db.Date,        nullable=False)
    message       = db.Column(db.Text)
    channel       = db.Column(db.String(20),  default='whatsapp')  # whatsapp | email
    sent          = db.Column(db.Boolean,     default=False)
    sent_at       = db.Column(db.DateTime)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)


# ── COMPANY (B2B) ─────────────────────────────────────────────────────────────
class Company(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(200), nullable=False)
    industry      = db.Column(db.String(100))
    employee_size = db.Column(db.String(50))   # "1-50" | "50-200" | "200-500" | "500+"
    contact_email = db.Column(db.String(120), unique=True, nullable=False)
    contact_name  = db.Column(db.String(100))
    password_hash = db.Column(db.String(256))
    plan          = db.Column(db.String(30), default='starter')  # starter | pro | enterprise
    logo_url      = db.Column(db.String(300))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    employees = db.relationship('User', backref='company', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def vaccination_coverage(self):
        """Returns dict: vaccine_key -> % employees with that vaccine recorded"""
        total = len(self.employees)
        if total == 0:
            return {}
        result = {}
        for emp in self.employees:
            for rec in emp.vaccination_records:
                result[rec.vaccine_key] = result.get(rec.vaccine_key, 0) + 1
        return {k: round(v / total * 100) for k, v in result.items()}

    def employees_needing(self, vaccine_key):
        """Returns users who have NOT recorded this vaccine"""
        vaccinated_ids = set(
            r.user_id for r in VaccinationRecord.query
            .filter_by(vaccine_key=vaccine_key).all()
        )
        return [e for e in self.employees if e.id not in vaccinated_ids]

    def __repr__(self):
        return f'<Company {self.name}>'


# ── CLINIC ────────────────────────────────────────────────────────────────────
class Clinic(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(200), nullable=False)
    branch           = db.Column(db.String(100))
    address          = db.Column(db.Text)
    city             = db.Column(db.String(80), default='Jakarta')
    phone            = db.Column(db.String(25))
    latitude         = db.Column(db.Float)
    longitude        = db.Column(db.Float)
    vaccines_offered = db.Column(db.Text)   # JSON list of vaccine keys
    price_range      = db.Column(db.String(60))  # e.g. "Rp 150.000 – 850.000"
    opening_hours    = db.Column(db.String(100))  # e.g. "Mon–Sat 08:00–20:00"
    rating           = db.Column(db.Float, default=4.5)
    logo             = db.Column(db.String(20))   # emoji or brand code
    network          = db.Column(db.String(60))   # e.g. "Prodia", "Kimia Farma"
    website          = db.Column(db.String(200))  # official site, opened directly from the card
    home_service     = db.Column(db.Boolean, default=False)  # offers at-home vaccination

    bookings = db.relationship('Booking', backref='clinic', lazy=True)


# ── BOOKING ───────────────────────────────────────────────────────────────────
class Booking(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'),   nullable=False)
    clinic_id        = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    vaccine_key      = db.Column(db.String(50),  nullable=False)
    vaccine_name     = db.Column(db.String(120), nullable=False)
    appointment_date = db.Column(db.DateTime,    nullable=False)
    status           = db.Column(db.String(20),  default='confirmed')  # confirmed | completed | cancelled
    referral_fee     = db.Column(db.Integer,     default=25000)        # Rp 25.000 per booking
    confirmation_code = db.Column(db.String(12))
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime,    default=datetime.utcnow)


# ── SEED CLINIC DATA ──────────────────────────────────────────────────────────
SEED_CLINICS = [
    dict(name="Prodia", branch="Sudirman", address="Jl. Jend. Sudirman Kav. 26, Jakarta Pusat",
         city="Jakarta", phone="+62215210476", latitude=-6.2088, longitude=106.8228,
         vaccines_offered='["influenza","pneumococcal","zoster","rsv","hepatitis_b","hepatitis_a","typhoid","covid19","hpv","tdap","meningococcal"]',
         price_range="Rp 150.000 – 850.000", opening_hours="Sen–Sab 07:00–21:00", rating=4.7,
         logo="🔬", network="Prodia", website="https://www.prodia.co.id"),
    dict(name="Prodia", branch="Kemang", address="Jl. Kemang Raya No. 2, Jakarta Selatan",
         city="Jakarta", phone="+62217196619", latitude=-6.2608, longitude=106.8144,
         vaccines_offered='["influenza","pneumococcal","zoster","rsv","hepatitis_b","hepatitis_a","typhoid","covid19","hpv","tdap"]',
         price_range="Rp 150.000 – 850.000", opening_hours="Sen–Sab 07:00–20:00", rating=4.6,
         logo="🔬", network="Prodia", website="https://www.prodia.co.id"),
    dict(name="Kimia Farma", branch="Melawai", address="Jl. Melawai III No.5, Kebayoran Baru, Jakarta Selatan",
         city="Jakarta", phone="+62217203131", latitude=-6.2434, longitude=106.7974,
         vaccines_offered='["influenza","hepatitis_b","typhoid","covid19","tdap","mmr","varicella"]',
         price_range="Rp 85.000 – 650.000", opening_hours="Sen–Min 08:00–22:00", rating=4.3,
         logo="💊", network="Kimia Farma", website="https://www.kimiafarma.co.id"),
    dict(name="Kimia Farma", branch="Tebet", address="Jl. Dr. Saharjo No.45, Tebet, Jakarta Selatan",
         city="Jakarta", phone="+62218290234", latitude=-6.2408, longitude=106.8510,
         vaccines_offered='["influenza","hepatitis_b","typhoid","covid19","tdap","mmr"]',
         price_range="Rp 85.000 – 650.000", opening_hours="Sen–Min 08:00–21:00", rating=4.2,
         logo="💊", network="Kimia Farma", website="https://www.kimiafarma.co.id"),
    dict(name="RS Pondok Indah", branch="Pondok Indah", address="Jl. Metro Duta Kav. UE, Pondok Indah, Jakarta Selatan",
         city="Jakarta", phone="+62217657525", latitude=-6.2847, longitude=106.7889,
         vaccines_offered='["influenza","pneumococcal","zoster","rsv","hepatitis_b","hepatitis_a","typhoid","covid19","hpv","tdap","meningococcal","yellow_fever","japanese_encephalitis"]',
         price_range="Rp 250.000 – 1.500.000", opening_hours="Sen–Min 07:00–21:00", rating=4.8,
         logo="🏥", network="RSPI", website="https://www.rspondokindah.co.id"),
    dict(name="Siloam Hospitals", branch="Semanggi", address="Jl. Jend. Sudirman Kav. 76, Jakarta Selatan",
         city="Jakarta", phone="+622129662000", latitude=-6.2237, longitude=106.8097,
         vaccines_offered='["influenza","pneumococcal","zoster","rsv","hepatitis_b","hepatitis_a","typhoid","covid19","hpv","tdap","meningococcal","yellow_fever"]',
         price_range="Rp 200.000 – 1.200.000", opening_hours="Sen–Min 07:00–20:00", rating=4.7,
         logo="🏥", network="Siloam", website="https://www.siloamhospitals.com"),
    dict(name="Pramita Lab", branch="Kuningan", address="Jl. HR Rasuna Said Kav. C11-14, Kuningan, Jakarta Selatan",
         city="Jakarta", phone="+622152963939", latitude=-6.2271, longitude=106.8375,
         vaccines_offered='["influenza","hepatitis_b","hepatitis_a","typhoid","covid19","tdap","mmr","varicella"]',
         price_range="Rp 100.000 – 750.000", opening_hours="Sen–Sab 07:00–20:00", rating=4.4,
         logo="🧪", network="Pramita", website="https://pramita.co.id"),
    dict(name="Klinik Vaksin Satgas PAPDI", branch="FKUI", address="Jl. Diponegoro No.71, Kenari, Jakarta Pusat",
         city="Jakarta", phone="+622131930216", latitude=-6.1960, longitude=106.8450,
         vaccines_offered='["influenza","pneumococcal","zoster","rsv","hepatitis_b","hepatitis_a","typhoid","covid19","hpv","tdap","meningococcal"]',
         price_range="Rp 120.000 – 900.000", opening_hours="Sen–Jum 08:00–16:00", rating=4.9,
         logo="⚕️", network="PAPDI", website="https://www.papdi.or.id"),
    # ── At-home vaccination providers (verified real services, Jabodetabek) ──
    dict(name="Halodoc Homecare", branch="Jabodetabek-wide", address="Service area: Jakarta, Bogor, Depok, Tangerang, Bekasi",
         city="Jakarta", phone="+628880999226", latitude=-6.2088, longitude=106.8456,
         vaccines_offered='["influenza","pneumococcal","zoster","hepatitis_b","hepatitis_a","typhoid","hpv","tdap","mmr","varicella"]',
         price_range="Rp 300.000 – 2.500.000", opening_hours="Sen–Min 06:00–22:00", rating=4.8,
         logo="🏠", network="Halodoc", website="https://www.halodoc.com/kesehatan/layanan-vaksinasi-halodoc", home_service=True),
    dict(name="Kavacare", branch="Home Vaccination", address="Service area: Jabodetabek",
         city="Jakarta", phone="+628111446777", latitude=-6.2297, longitude=106.8253,
         vaccines_offered='["influenza","pneumococcal","hepatitis_b","hepatitis_a","typhoid","tdap","mmr","varicella"]',
         price_range="Rp 350.000 – 2.000.000", opening_hours="Sen–Min 07:00–21:00", rating=4.7,
         logo="🏠", network="Kavacare", website="https://www.kavacare.id/vaksinasi-di-rumah/", home_service=True),
    dict(name="Vaxine Care", branch="Home Service Jakarta", address="Service area: Jakarta & surroundings",
         city="Jakarta", phone="+6281388883993", latitude=-6.2441, longitude=106.8006,
         vaccines_offered='["influenza","pneumococcal","zoster","hepatitis_b","hepatitis_a","typhoid","hpv","tdap"]',
         price_range="Rp 250.000 – 1.800.000", opening_hours="Sen–Min 08:00–20:00", rating=4.6,
         logo="🏠", network="Vaxine Care", website="https://vaxinecare.com", home_service=True),
    dict(name="Imuni", branch="Vaksinasi di Rumah", address="Service area: Jabodetabek, Bandung, Surabaya & Bali",
         city="Jakarta", phone="+6282120097800", latitude=-6.1457, longitude=106.8606,
         vaccines_offered='["influenza","pneumococcal","zoster","hepatitis_b","hepatitis_a","typhoid","hpv","tdap","mmr","varicella","rotavirus"]',
         price_range="Rp 200.000 – 2.500.000", opening_hours="Sen–Min 08:00–20:00", rating=4.9,
         logo="🏠", network="Imuni", website="https://imuni.id", home_service=True),
    dict(name="InHarmony", branch="Klinik Vaksinasi", address="Service area: Jakarta, clinic & home service",
         city="Jakarta", phone="+62214220214", latitude=-6.1846, longitude=106.8540,
         vaccines_offered='["influenza","pneumococcal","zoster","hepatitis_b","hepatitis_a","typhoid","hpv","tdap","mmr","varicella","meningococcal","yellow_fever"]',
         price_range="Rp 200.000 – 3.000.000", opening_hours="Sen–Jum 09:00–20:00", rating=4.8,
         logo="🏠", network="InHarmony", website="https://inharmonyclinic.com", home_service=True),
]

def seed_clinics():
    """Upsert seed data: refresh existing rows by (name, branch), insert new ones."""
    changed = False
    for c in SEED_CLINICS:
        row = Clinic.query.filter_by(name=c["name"], branch=c["branch"]).first()
        if row:
            for k, v in c.items():
                setattr(row, k, v)
        else:
            db.session.add(Clinic(**c))
        changed = True
    if changed:
        db.session.commit()

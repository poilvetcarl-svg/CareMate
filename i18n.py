"""
CareMate, lightweight i18n.
English is the default; Bahasa Indonesia is one click away via the ENG | IDN
selector. Short shared strings live here; long paragraphs are written per
language directly in templates with {% if LANG == 'id' %} blocks.
"""

DEFAULT_LANG = "en"

STRINGS = {
    # navbar
    "nav.assessment":   {"id": "Penilaian", "en": "Assessment"},
    "nav.how":          {"id": "Cara Kerja", "en": "How It Works"},
    "nav.clinics":      {"id": "Klinik", "en": "Clinics"},
    "nav.doctors":      {"id": "Dokter", "en": "Doctors"},
    "nav.business":     {"id": "Untuk Perusahaan", "en": "For Companies"},
    "nav.about":        {"id": "Tentang Kami", "en": "About"},
    "nav.signin":       {"id": "Masuk", "en": "Sign In"},
    "nav.signup":       {"id": "Daftar Gratis", "en": "Sign Up Free"},
    "nav.dashboard":    {"id": "Dasbor", "en": "Dashboard"},
    "nav.signout":      {"id": "Keluar", "en": "Sign Out"},

    # hero
    "hero.badge":       {"id": "Kesehatan preventif, dibuat untuk Indonesia", "en": "Preventive care, made for Indonesia"},
    "hero.title.1":     {"id": "Rencana Pencegahan", "en": "Your Family's"},
    "hero.title.2":     {"id": "Keluarga Anda", "en": "Prevention Plan"},
    "hero.title.3":     {"id": "dalam 60 Detik", "en": "in 60 Seconds"},
    "hero.subtitle":    {"id": "Dapatkan rencana pencegahan pribadi untuk vaksinasi, skrining, dan cek kesehatan, berdasarkan pedoman Kemenkes, PAPDI, dan IDAI, disesuaikan dengan usia, kondisi, gaya hidup, dan risiko keluarga Anda.",
                         "en": "Get a personalized prevention plan for vaccines, screenings, and health checks, built on Indonesian guidelines from Kemenkes, PAPDI and IDAI, tailored to your age, health profile, lifestyle and family risks."},
    "hero.cta":         {"id": "Buat Rencana Saya", "en": "Get My Prevention Plan"},
    "hero.cta2":        {"id": "Konsultasi Dokter", "en": "Talk to a Doctor"},
    "hero.stat.free":   {"id": "Gratis, selamanya", "en": "Free, always"},
    "hero.stat.time":   {"id": "Rata-rata penilaian", "en": "Average assessment"},
    "hero.stat.ai":     {"id": "Akses dokter AI", "en": "AI doctor access"},
    "trust.label":      {"id": "Mengikuti pedoman dari", "en": "Following guidelines from"},

    # how it works
    "how.badge":        {"id": "Cara Kerja", "en": "How It Works"},
    "how.title.1":      {"id": "Dari Profil ke", "en": "From Profile to"},
    "how.title.2":      {"id": "Perlindungan", "en": "Protection"},
    "how.subtitle":     {"id": "Empat langkah sederhana menuju rencana pencegahan pribadi Anda, didukung pedoman CDC & WHO dan analisis AI.",
                         "en": "Four simple steps to your personalised prevention plan, powered by CDC & WHO guidelines and AI analysis."},

    # footer
    "footer.tagline":   {"id": "Kesehatan preventif berbasis AI, dibuat untuk Indonesia.", "en": "AI-powered preventive health, made for Indonesia."},
    "footer.platform":  {"id": "Platform", "en": "Platform"},
    "footer.assessment":{"id": "Penilaian Gratis", "en": "Free Assessment"},
    "footer.findclinic":{"id": "Cari Klinik", "en": "Find a Clinic"},
    "footer.telecon":   {"id": "Telekonsultasi", "en": "Teleconsultation"},
    "footer.how":       {"id": "Cara Kerja", "en": "How It Works"},
    "footer.account":   {"id": "Akun Saya", "en": "My Account"},
    "footer.create":    {"id": "Buat Akun", "en": "Create Account"},
    "footer.signin":    {"id": "Masuk", "en": "Sign In"},
    "footer.dashboard": {"id": "Dasbor Saya", "en": "My Dashboard"},
    "footer.history":   {"id": "Riwayat Vaksinasi", "en": "Vaccination History"},
    "footer.company":   {"id": "Perusahaan", "en": "Company"},
    "footer.about":     {"id": "Tentang Kami", "en": "About Us"},
    "footer.privacy":   {"id": "Kebijakan Privasi", "en": "Privacy Policy"},
    "footer.terms":     {"id": "Syarat Penggunaan", "en": "Terms of Use"},
    "footer.corporate": {"id": "Portal Perusahaan", "en": "Corporate Portal"},
    "footer.disclaimer":{"id": "CareMate bersifat informatif dan tidak menggantikan saran medis profesional.",
                         "en": "CareMate is for informational purposes only and does not replace professional medical advice."},
    "footer.madefor":   {"id": "Dibuat untuk Indonesia", "en": "Made for Indonesia"},

    # clinics
    "clinics.title":    {"id": "Direktori Klinik & Layanan Kesehatan", "en": "Clinic & Health Service Directory"},
    "clinics.visit":    {"id": "Kunjungi", "en": "Visit"},
    "clinics.website":  {"id": "Situs Resmi", "en": "Official Site"},
    "clinics.map":      {"id": "Peta", "en": "Map"},
    "clinics.book":     {"id": "Buat Janji", "en": "Book Appointment"},
    "clinics.signin":   {"id": "Masuk untuk Buat Janji", "en": "Sign in to Book"},
    "clinics.disclaimer": {"id": "CareMate adalah direktori independen. Semua merek dan logo adalah milik pemiliknya masing-masing dan tidak menandakan afiliasi atau kemitraan. Pemesanan dilakukan melalui kanal resmi masing-masing penyedia.",
                           "en": "CareMate is an independent directory. All brands and logos belong to their respective owners and do not imply affiliation or partnership. Bookings happen through each provider's official channels."},

    # teleconsultation
    "tc.title.1":       {"id": "Bicara dengan", "en": "Talk to a"},
    "tc.title.2":       {"id": "Dokter Virtual", "en": "Virtual Doctor"},
    "tc.subtitle":      {"id": "Dokter pencegahan berbasis AI untuk membahas vaksinasi, skrining, hasil lab, dan kesehatan sehari-hari, dari mana saja, kapan saja.",
                         "en": "An AI prevention doctor you can talk to about vaccines, screenings, lab results, and everyday prevention, from anywhere, anytime."},

    # b2b
    "b2b.badge":        {"id": "Untuk Perusahaan", "en": "For Companies"},
    "b2b.title":        {"id": "Program pencegahan untuk karyawan Anda", "en": "A prevention program for your employees"},
    "b2b.cta":          {"id": "Ajukan Pilot Gratis", "en": "Request a Free Pilot"},

    # misc
    "lang.switch":      {"id": "EN", "en": "ID"},
    "about.title":      {"id": "Tentang CareMate", "en": "About CareMate"},
}

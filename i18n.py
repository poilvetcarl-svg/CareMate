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
    "nav.doctors":      {"id": "Asisten AI", "en": "AI Assistant"},
    "nav.business":     {"id": "Untuk Perusahaan", "en": "For Companies"},
    "nav.about":        {"id": "Tentang Kami", "en": "About"},
    "nav.signin":       {"id": "Masuk", "en": "Sign In"},
    "nav.signup":       {"id": "Daftar Gratis", "en": "Sign Up Free"},
    "nav.dashboard":    {"id": "Dasbor", "en": "Dashboard"},
    "nav.signout":      {"id": "Keluar", "en": "Sign Out"},

    # hero
    "hero.badge":       {"id": "Kesehatan preventif, dibuat untuk Indonesia", "en": "Preventive care, made for Indonesia"},
    "hero.title.1":     {"id": "Langkah Pencegahan", "en": "Know What to"},
    "hero.title.2":     {"id": "Berikutnya untuk Anda", "en": "Prevent Next"},
    "hero.title.3":     {"id": "dalam 60 Detik", "en": "in 60 Seconds"},
    "hero.subtitle":    {"id": "CareMate memberi tahu apa yang perlu Anda cegah berikutnya: vaksinasi, skrining, dan cek kesehatan, berdasarkan pedoman Kemenkes, PAPDI, dan IDAI, disesuaikan dengan usia, kondisi, hasil lab, dan risiko Anda.",
                         "en": "CareMate tells you what to prevent next: the vaccines, screenings and check-ups you actually need, built on Indonesian guidelines from Kemenkes, PAPDI and IDAI, tailored to your age, health profile, lab results and risks."},
    "hero.cta":         {"id": "Buat Rencana Saya", "en": "Get My Prevention Plan"},
    "hero.cta2":        {"id": "Tanya Asisten AI", "en": "Ask the AI Assistant"},
    "hero.stat.free":   {"id": "Gratis, selamanya", "en": "Free, always"},
    "hero.stat.time":   {"id": "Rata-rata penilaian", "en": "Average assessment"},
    "hero.stat.ai":     {"id": "Akses asisten AI", "en": "AI assistant access"},
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
    "footer.telecon":   {"id": "Asisten Pencegahan AI", "en": "AI Prevention Assistant"},
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
    "tc.title.1":       {"id": "Asisten Pencegahan", "en": "Your AI Prevention"},
    "tc.title.2":       {"id": "AI Anda", "en": "Assistant"},
    "tc.subtitle":      {"id": "Asisten AI yang menjelaskan hasil lab, vaksinasi, dan skrining dalam bahasa sederhana, lalu menyiapkan Anda untuk dokter sungguhan. Bukan diagnosis, kapan saja, dari mana saja.",
                         "en": "An AI assistant that explains your lab results, vaccines and screenings in plain language, then prepares you for your real doctor. Never a diagnosis, anytime, anywhere."},

    # b2b
    "b2b.badge":        {"id": "Untuk Perusahaan", "en": "For Companies"},
    "b2b.title":        {"id": "Ketahui kebutuhan kesehatan karyawan Anda sebelum mereka sakit", "en": "Know what your employees need before they get sick"},
    "b2b.cta":          {"id": "Ajukan Pilot Gratis", "en": "Request a Free Pilot"},

    # misc
    "lang.switch":      {"id": "EN", "en": "ID"},
    "about.title":      {"id": "Tentang CareMate", "en": "About CareMate"},

    # dashboard chrome
    "side.overview":    {"id": "Ringkasan", "en": "Overview"},
    "side.assessment":  {"id": "Penilaian Kesehatan", "en": "Health Assessment"},
    "side.records":     {"id": "Rekam Kesehatan Saya", "en": "My Health Records"},
    "side.doctor":      {"id": "Asisten AI", "en": "AI Assistant"},
    "side.findcare":    {"id": "Cari Layanan", "en": "Find Care"},
    "side.reminders":   {"id": "Pengingat", "en": "Reminders"},
    "side.signout":     {"id": "Keluar", "en": "Sign Out"},
    "dash.sub":         {"id": "Ringkasan pencegahan Anda: vaksinasi, skrining, lab, dan kesehatan sehari-hari.",
                         "en": "Here's your prevention overview: vaccines, screenings, labs and everyday health."},
    "dash.stat.vax":    {"id": "Vaksin Tercatat", "en": "Vaccines Recorded"},
    "dash.stat.rem":    {"id": "Pengingat Mendatang", "en": "Upcoming Reminders"},
    "dash.stat.assess": {"id": "Penilaian Selesai", "en": "Assessments Done"},
    "dash.stat.book":   {"id": "Janji Klinik", "en": "Clinic Bookings"},
}

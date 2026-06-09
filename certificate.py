"""
CareMate — Vaccine Certificate PDF Generator
Uses fpdf2 + qrcode to produce professional A4 landscape certificates.
"""
from fpdf import FPDF
import qrcode
import io
import os
import tempfile
from datetime import date as _date


def generate_certificate_pdf(record, user) -> bytes:
    """Return raw PDF bytes for a vaccination certificate."""

    # ── QR code (verify URL) ─────────────────────────────────────────────────
    cert_id = f"CM-{record.id:06d}"
    verify_url = f"http://localhost:5050/verify/{cert_id}"
    qr = qrcode.QRCode(version=1, box_size=4, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=(5, 100, 70), back_color="white")

    tmp_qr = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    qr_img.save(tmp_qr.name)
    tmp_qr.close()

    try:
        pdf = _build_pdf(record, user, cert_id, tmp_qr.name)
    finally:
        os.unlink(tmp_qr.name)

    return bytes(pdf.output())


def _build_pdf(record, user, cert_id, qr_path):
    W, H = 297, 210   # A4 landscape mm

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(False)

    # ── Page background ──────────────────────────────────────────────────────
    pdf.set_fill_color(249, 255, 252)
    pdf.rect(0, 0, W, H, "F")

    # ── Outer border ─────────────────────────────────────────────────────────
    pdf.set_draw_color(5, 150, 105)
    pdf.set_line_width(2.5)
    pdf.rect(8, 8, W - 16, H - 16)
    pdf.set_line_width(0.4)
    pdf.rect(11, 11, W - 22, H - 22)

    # ── Header band ──────────────────────────────────────────────────────────
    pdf.set_fill_color(5, 150, 105)
    pdf.rect(8, 8, W - 16, 22, "F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(18, 12)
    pdf.cell(0, 8, "CareMate  |  Vaccination Certificate", ln=False)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(18, 21)
    pdf.cell(0, 5, "Kesehatan Preventif untuk Semua  |  caremate.id", ln=False)

    # ── Main title ───────────────────────────────────────────────────────────
    pdf.set_text_color(5, 100, 70)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_xy(0, 40)
    pdf.cell(W, 12, "CERTIFICATE OF VACCINATION", align="C", ln=True)

    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(0, 53)
    pdf.cell(W, 6, "This is to certify that the following individual has received a vaccination",
             align="C", ln=True)

    # ── Name ─────────────────────────────────────────────────────────────────
    name = (user.name or "Unknown").upper()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_xy(0, 62)
    pdf.cell(W, 12, name, align="C", ln=True)

    # Underline the name
    nw = pdf.get_string_width(name)
    cx = (W - nw) / 2
    pdf.set_draw_color(5, 150, 105)
    pdf.set_line_width(0.8)
    pdf.line(cx, 75, cx + nw, 75)

    # ── Details box ──────────────────────────────────────────────────────────
    box_x, box_y, box_w, box_h = 30, 82, 210, 78
    pdf.set_fill_color(240, 252, 246)
    pdf.set_draw_color(5, 150, 105)
    pdf.set_line_width(0.4)
    pdf.rect(box_x, box_y, box_w, box_h, "FD")

    # Column widths inside box
    col = box_w / 3

    # Labels row
    pdf.set_text_color(100, 130, 115)
    pdf.set_font("Helvetica", "B", 8)
    labels = ["VACCINE", "DOSE NUMBER", "DATE ADMINISTERED"]
    for i, lbl in enumerate(labels):
        pdf.set_xy(box_x + 6 + i * col, box_y + 8)
        pdf.cell(col - 6, 5, lbl)

    # Values row
    pdf.set_text_color(15, 15, 15)
    pdf.set_font("Helvetica", "B", 13)
    values = [
        record.vaccine_name[:26],
        f"Dose {record.dose_number}",
        record.date_given.strftime("%d %B %Y"),
    ]
    for i, val in enumerate(values):
        pdf.set_xy(box_x + 6 + i * col, box_y + 16)
        pdf.cell(col - 6, 8, val)

    # Divider
    pdf.set_draw_color(200, 230, 215)
    pdf.set_line_width(0.3)
    pdf.line(box_x + 6, box_y + 30, box_x + box_w - 6, box_y + 30)

    # Clinic row
    pdf.set_text_color(100, 130, 115)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(box_x + 6, box_y + 34)
    pdf.cell(col * 2 - 6, 5, "CLINIC / LOCATION")

    if record.next_dose_date:
        pdf.set_xy(box_x + 6 + col * 2, box_y + 34)
        pdf.cell(col - 6, 5, "NEXT DOSE DATE")

    pdf.set_text_color(15, 15, 15)
    pdf.set_font("Helvetica", "B", 12)
    clinic = record.clinic_name or "Not specified"
    pdf.set_xy(box_x + 6, box_y + 42)
    pdf.cell(col * 2 - 6, 8, clinic[:30])

    if record.next_dose_date:
        pdf.set_xy(box_x + 6 + col * 2, box_y + 42)
        pdf.cell(col - 6, 8, record.next_dose_date.strftime("%d %B %Y"))

    # Certificate ID + date
    pdf.set_text_color(140, 160, 150)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(box_x + 6, box_y + 64)
    pdf.cell(box_w - 12, 5,
             f"Certificate ID: {cert_id}   |   Issued: {_date.today().strftime('%d %B %Y')}")

    # ── QR code ──────────────────────────────────────────────────────────────
    qr_x, qr_y, qr_size = W - 60, 82, 42
    pdf.image(qr_path, x=qr_x, y=qr_y, w=qr_size)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(qr_x - 2, qr_y + qr_size + 2)
    pdf.cell(qr_size + 4, 4, "Scan to verify", align="C")

    # ── Official seal text ───────────────────────────────────────────────────
    pdf.set_text_color(5, 100, 70)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(30, 168)
    pdf.cell(100, 5, "Verified by CareMate Health Platform")
    pdf.set_text_color(140, 140, 140)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(30, 174)
    pdf.cell(200, 4,
             "This certificate is generated automatically based on self-reported vaccination records. "
             "It does not replace official government vaccination cards.")

    # ── Footer band ──────────────────────────────────────────────────────────
    pdf.set_fill_color(5, 150, 105)
    pdf.rect(8, H - 20, W - 16, 12, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(18, H - 17)
    pdf.cell(W - 36, 6,
             f"Verify online: caremate.id/verify/{cert_id}   |   "
             f"© 2025 CareMate   |   For informational purposes only",
             align="C")

    return pdf

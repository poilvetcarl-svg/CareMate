"""
CareMate — WhatsApp Reminder Service
Uses Twilio WhatsApp API + APScheduler
"""
import os
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = None

def send_whatsapp(to_number: str, message: str) -> dict:
    """Send a WhatsApp message via Twilio. Returns {ok, sid/error}."""
    sid   = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_ = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio sandbox

    if not sid or not token:
        # Dev mode — just log
        print(f"[WhatsApp MOCK] → {to_number}\n  {message}")
        return {"ok": True, "sid": "MOCK_SID"}

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msg = client.messages.create(
            from_=from_,
            to=f"whatsapp:{to_number}",
            body=message
        )
        return {"ok": True, "sid": msg.sid}
    except Exception as e:
        print(f"[WhatsApp ERROR] {e}")
        return {"ok": False, "error": str(e)}


def build_reminder_message(vaccine_name: str, user_name: str, days_until: int) -> str:
    if days_until == 0:
        time_str = "hari ini"
    elif days_until == 1:
        time_str = "besok"
    else:
        time_str = f"dalam {days_until} hari"

    name_str = user_name or "Anda"
    return (
        f"💉 *Pengingat Vaksin CareMate*\n\n"
        f"Halo {name_str},\n\n"
        f"Waktunya vaksin *{vaccine_name}* — jadwal {time_str}!\n\n"
        f"Segera booking ke klinik terdekat atau kunjungi "
        f"caremate.id untuk menemukan tempat vaksinasi.\n\n"
        f"_CareMate · Kesehatan Preventif untuk Semua_"
    )


def check_and_send_reminders(app):
    """
    Called by scheduler daily at 09:00 WIB.
    Sends WhatsApp messages for reminders due today, tomorrow, or in 7 days.
    """
    from models import db, VaccineReminder, User
    REMIND_DAYS = [0, 1, 7]   # send on day-of, 1 day before, 7 days before

    with app.app_context():
        today = date.today()
        sent_count = 0

        for days in REMIND_DAYS:
            target_date = today + timedelta(days=days)
            due = VaccineReminder.query.filter_by(
                reminder_date=target_date, sent=False
            ).all()

            for reminder in due:
                user = User.query.get(reminder.user_id)
                if not user:
                    continue

                sent_ok = False

                # Try WhatsApp first
                if user.phone and user.whatsapp_opt_in:
                    msg = build_reminder_message(reminder.vaccine_name, user.name, days)
                    result = send_whatsapp(user.phone, msg)
                    sent_ok = result["ok"]

                # Fallback: email reminder
                if not sent_ok and user.email:
                    try:
                        from flask import current_app
                        fn = current_app.send_email_reminder
                        sent_ok = fn(
                            user.email, user.name,
                            reminder.vaccine_name, reminder.reminder_date, days
                        )
                    except Exception as e:
                        print(f"[Email fallback error] {e}")

                if sent_ok:
                    from datetime import datetime
                    reminder.sent = True
                    reminder.sent_at = datetime.utcnow()
                    db.session.commit()
                    sent_count += 1

        if sent_count:
            print(f"[Reminders] Sent {sent_count} WhatsApp reminder(s).")


def start_scheduler(app):
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    _scheduler.add_job(
        lambda: check_and_send_reminders(app),
        CronTrigger(hour=9, minute=0),   # 09:00 WIB daily
        id="daily_reminders",
        replace_existing=True
    )
    _scheduler.start()
    print("[Scheduler] Daily WhatsApp reminder job started (09:00 WIB).")
    return _scheduler


def schedule_vaccine_reminders(user, vaccine_key, vaccine_name, due_date):
    """
    Create standard reminders for a vaccine:
    - 7 days before due_date
    - 1 day before due_date
    - on due_date itself
    """
    from models import db, VaccineReminder
    from datetime import timedelta

    intervals = [7, 1, 0]
    created = []
    for days_before in intervals:
        remind_on = due_date - timedelta(days=days_before)
        if remind_on >= date.today():
            r = VaccineReminder(
                user_id=user.id,
                vaccine_key=vaccine_key,
                vaccine_name=vaccine_name,
                reminder_date=remind_on,
                message=build_reminder_message(vaccine_name, user.name, days_before),
                channel='whatsapp' if (user.phone and user.whatsapp_opt_in) else 'dashboard'
            )
            db.session.add(r)
            created.append(r)

    db.session.commit()
    return created

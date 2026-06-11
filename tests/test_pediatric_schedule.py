"""Tests for the IDAI 2024 pediatric immunization schedule engine.

The schedule is medical data — these tests pin the clinically important
properties: birth doses exist, statuses reflect the child's age, sex-gated
vaccines (HPV) only appear for girls, and recording a dose marks it done.
"""
from datetime import date, timedelta

import pytest

from app import app as flask_app, db, Child, VaccinationRecord, User, compute_child_schedule


@pytest.fixture()
def ctx(app):
    import uuid
    with app.app_context():
        db.create_all()
        user = User(email=f"parent-{uuid.uuid4().hex[:10]}@test.com", name="Parent")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        yield user
        db.session.rollback()


def make_child(user, months_old, sex="female"):
    today = date.today()
    m = today.month - 1 - months_old
    dob = today.replace(year=today.year + m // 12, month=m % 12 + 1,
                        day=min(today.day, 28))
    child = Child(user_id=user.id, name="Test Child", date_of_birth=dob, sex=sex)
    db.session.add(child)
    db.session.commit()
    return child


class TestScheduleGeneration:
    def test_newborn_has_birth_doses_due(self, ctx):
        child = make_child(ctx, months_old=0)
        sched = compute_child_schedule(child)
        due_now = {(d["key"], d["dose"]) for d in sched["timeline"]
                   if d["due_month"] == 0}
        assert ("hep_b", 1) in due_now
        assert ("bcg", 1) in due_now
        assert ("polio", 1) in due_now

    def test_three_month_old_has_overdue_two_month_doses(self, ctx):
        child = make_child(ctx, months_old=3)
        sched = compute_child_schedule(child)
        overdue_keys = {(d["key"], d["dose"]) for d in sched["overdue"]}
        assert ("dtp", 1) in overdue_keys      # was due at 2 months
        assert ("pcv", 1) in overdue_keys

    def test_future_doses_are_upcoming(self, ctx):
        child = make_child(ctx, months_old=1)
        sched = compute_child_schedule(child)
        mr1 = next(d for d in sched["timeline"] if d["key"] == "mr" and d["dose"] == 1)
        assert mr1["status"] == "upcoming"     # due at 9 months

    def test_timeline_sorted_by_due_date(self, ctx):
        child = make_child(ctx, months_old=6)
        dates = [d["due_date"] for d in compute_child_schedule(child)["timeline"]]
        assert dates == sorted(dates)


class TestSexGating:
    def test_hpv_included_for_girls(self, ctx):
        child = make_child(ctx, months_old=12, sex="female")
        keys = {d["key"] for d in compute_child_schedule(child)["timeline"]}
        assert "hpv" in keys

    def test_hpv_excluded_for_boys(self, ctx):
        child = make_child(ctx, months_old=12, sex="male")
        keys = {d["key"] for d in compute_child_schedule(child)["timeline"]}
        assert "hpv" not in keys


class TestDoseRecording:
    def test_recorded_dose_marked_done(self, ctx):
        child = make_child(ctx, months_old=3)
        db.session.add(VaccinationRecord(
            user_id=ctx.id, child_id=child.id,
            vaccine_key="dtp", vaccine_name="DTP", dose_number=1,
            date_given=date.today()))
        db.session.commit()
        sched = compute_child_schedule(child)
        dtp1 = next(d for d in sched["timeline"] if d["key"] == "dtp" and d["dose"] == 1)
        assert dtp1["status"] == "done"
        assert sched["done_count"] == 1

    def test_done_dose_leaves_others_pending(self, ctx):
        child = make_child(ctx, months_old=3)
        db.session.add(VaccinationRecord(
            user_id=ctx.id, child_id=child.id,
            vaccine_key="dtp", vaccine_name="DTP", dose_number=1,
            date_given=date.today()))
        db.session.commit()
        sched = compute_child_schedule(child)
        dtp2 = next(d for d in sched["timeline"] if d["key"] == "dtp" and d["dose"] == 2)
        assert dtp2["status"] != "done"

"""Tests for lab result tracking: reference flags, name matching, manual entry."""
import uuid
from datetime import date

import pytest

from app import app as flask_app, db, User, LabResult, match_lab_test, flag_lab_value


@pytest.fixture()
def user(app):
    with app.app_context():
        db.create_all()
        u = User(email=f"lab-{uuid.uuid4().hex[:10]}@test.com", name="Lab Tester")
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        yield u
        db.session.rollback()


class TestFlagging:
    def test_normal_hba1c(self):
        assert flag_lab_value("hba1c", 5.2) == "normal"

    def test_high_hba1c(self):
        assert flag_lab_value("hba1c", 7.8) == "high"

    def test_low_hdl(self):
        assert flag_lab_value("hdl", 30) == "low"

    def test_unknown_test_never_flags(self):
        assert flag_lab_value(None, 42) == "unknown"
        assert flag_lab_value("not_a_test", 42) == "unknown"

    def test_non_numeric_value_unknown(self):
        assert flag_lab_value("hba1c", "abc") == "unknown"


class TestNameMatching:
    def test_exact_and_alias_matching(self):
        assert match_lab_test("HbA1c") == "hba1c"
        assert match_lab_test("a1c") == "hba1c"
        assert match_lab_test("SGPT") == "alt"
        assert match_lab_test("gula darah puasa") == "fasting_glucose"   # Indonesian report

    def test_unknown_name_returns_none(self):
        assert match_lab_test("Mystery Biomarker 3000") is None


class TestManualEntry:
    def _login(self, client, user):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)

    def test_add_known_test_flags_and_fills_unit(self, app, client, user):
        self._login(client, user)
        resp = client.post("/labs/add", data={
            "test_key": "hba1c", "test_name": "", "value": "8.1",
            "unit": "", "date_taken": date.today().isoformat()},
            follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            row = LabResult.query.filter_by(user_id=user.id).first()
            assert row.flag == "high"
            assert row.unit == "%"
            assert row.test_name == "HbA1c"

    def test_rejects_non_numeric_value(self, app, client, user):
        self._login(client, user)
        client.post("/labs/add", data={"test_key": "hba1c", "value": "not-a-number"},
                    follow_redirects=True)
        with app.app_context():
            assert LabResult.query.filter_by(user_id=user.id).count() == 0

    def test_upload_requires_login(self, client):
        resp = client.post("/labs/upload", data={})
        assert resp.status_code == 302  # redirected to login

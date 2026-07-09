"""Integration tests for the public API surface using the Flask test client."""
import json


class TestPages:
    def test_homepage_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"CareMate" in resp.data

    def test_references_page_renders(self, client):
        resp = client.get("/references")
        assert resp.status_code == 200
        assert b"PAPDI" in resp.data

    def test_teleconsultation_renders_assistant(self, client):
        resp = client.get("/teleconsultation")
        assert resp.status_code == 200
        assert b"AI prevention assistant" in resp.data

    def test_404_for_unknown_route(self, client):
        resp = client.get("/this-page-does-not-exist")
        assert resp.status_code == 404


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "version" in body
        assert body["database"] == "ok"


class TestRecommendAPI:
    def _post(self, client, payload):
        return client.post(
            "/api/recommend",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_valid_assessment_returns_risk_and_vaccines(self, client):
        resp = self._post(client, {
            "age": 45, "sex": "male", "conditions": ["diabetes"],
            "pregnant": "no", "travel_regions": [], "vaccinated_recently": "no",
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert "risk" in body and "vaccines" in body
        assert 0 <= body["risk"]["percentage"] <= 100
        assert body["total_vaccines"] == len(body["vaccines"])

    def test_rejects_age_below_18(self, client):
        resp = self._post(client, {"age": 5, "sex": "male"})
        assert resp.status_code == 400

    def test_rejects_age_above_120(self, client):
        resp = self._post(client, {"age": 500, "sex": "male"})
        assert resp.status_code == 400

    def test_rejects_non_numeric_age(self, client):
        resp = self._post(client, {"age": "abc", "sex": "male"})
        assert resp.status_code == 400

    def test_rejects_unknown_condition_keys(self, client):
        resp = self._post(client, {
            "age": 30, "sex": "male",
            "conditions": ["<script>alert(1)</script>"],
        })
        assert resp.status_code == 400

    def test_ai_summary_fallback_without_api_key(self, client):
        """Without OPENAI_API_KEY the endpoint must degrade gracefully, not 500."""
        resp = self._post(client, {
            "age": 70, "sex": "female", "conditions": ["heart_disease"],
            "pregnant": "no", "travel_regions": [], "vaccinated_recently": "no",
        })
        assert resp.status_code == 200
        assert len(resp.get_json()["ai_summary"]) > 0


class TestChatAPI:
    def test_chat_without_key_returns_friendly_error(self, client):
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        assert resp.get_json().get("error") is True

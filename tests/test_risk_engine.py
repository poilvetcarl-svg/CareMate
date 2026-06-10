"""Unit tests for the clinical risk-scoring engine.

The risk engine is pure logic (no I/O), so these tests pin down the
clinical calibration: a healthy young adult must score Low, a 70-year-old
diabetic with no recent vaccines must score High, and the interaction
bonuses must only fire when their preconditions hold.
"""
from app import calculate_risk_score


def make_profile(**overrides):
    base = {
        "age": 30,
        "sex": "male",
        "conditions": [],
        "pregnant": "no",
        "travel_regions": [],
        "vaccinated_recently": "yes",
    }
    base.update(overrides)
    return base


class TestRiskLevels:
    def test_healthy_young_adult_is_low_risk(self):
        result = calculate_risk_score(make_profile())
        assert result["level"] == "Low Risk"
        assert result["percentage"] < 38

    def test_elderly_diabetic_unvaccinated_is_high_risk(self):
        result = calculate_risk_score(make_profile(
            age=70, conditions=["diabetes"], vaccinated_recently="no"))
        assert result["level"] == "High Risk"
        assert result["percentage"] >= 65

    def test_percentage_never_exceeds_100(self):
        result = calculate_risk_score(make_profile(
            age=80,
            conditions=["diabetes", "heart_disease", "cancer", "hiv",
                        "immunocompromised", "asplenia"],
            vaccinated_recently="no",
            travel_regions=["Sub-Saharan Africa"],
        ))
        assert result["percentage"] <= 100

    def test_score_is_monotonic_in_conditions(self):
        """Adding a condition must never lower the score."""
        without = calculate_risk_score(make_profile(age=55))
        with_db = calculate_risk_score(make_profile(age=55, conditions=["diabetes"]))
        assert with_db["score"] > without["score"]


class TestRiskFactors:
    def test_age_bands(self):
        young = calculate_risk_score(make_profile(age=25))
        middle = calculate_risk_score(make_profile(age=55))
        senior = calculate_risk_score(make_profile(age=70))
        assert young["score"] < middle["score"] < senior["score"]

    def test_pregnancy_adds_points(self):
        not_pregnant = calculate_risk_score(make_profile(sex="female"))
        pregnant = calculate_risk_score(make_profile(sex="female", pregnant="yes"))
        assert pregnant["score"] - not_pregnant["score"] == 4

    def test_travel_adds_flat_bonus_regardless_of_region_count(self):
        one = calculate_risk_score(make_profile(travel_regions=["Europe"]))
        many = calculate_risk_score(make_profile(
            travel_regions=["Europe", "South Asia", "Latin America"]))
        assert one["score"] == many["score"]

    def test_factor_labels_returned_for_ui(self):
        result = calculate_risk_score(make_profile(age=70, conditions=["diabetes"]))
        labels = [f["factor"] for f in result["factors"]]
        assert "Age ≥ 65" in labels
        assert any("Diabetes" in lbl for lbl in labels)


class TestInteractionBonuses:
    def test_age_plus_chronic_condition_compounds(self):
        """65+ with a chronic condition gets a +3 interaction bonus."""
        base_parts = (
            calculate_risk_score(make_profile(age=70))["score"]
            + calculate_risk_score(make_profile(conditions=["diabetes"]))["score"]
            - 2 * calculate_risk_score(make_profile())["score"]
        )
        combined = calculate_risk_score(
            make_profile(age=70, conditions=["diabetes"]))["score"]
        baseline = calculate_risk_score(make_profile())["score"]
        # combined > sum of individual increments → interaction bonus fired
        assert combined - baseline > base_parts

    def test_smoking_alone_does_not_trigger_chronic_interaction(self):
        """Smoking is moderate-risk, not in the chronic set — no compound bonus."""
        result = calculate_risk_score(make_profile(age=70, conditions=["smoking"]))
        labels = [f["factor"] for f in result["factors"]]
        assert not any("compounded" in lbl for lbl in labels)

    def test_overdue_at_high_risk_age_bonus(self):
        result = calculate_risk_score(make_profile(age=70, vaccinated_recently="no"))
        labels = [f["factor"] for f in result["factors"]]
        assert any("Overdue" in lbl for lbl in labels)

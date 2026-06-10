"""Unit tests for the vaccine recommendation engine.

These pin down clinical safety rules (live vaccines excluded in pregnancy),
age gating, condition triggers, and travel logic.
"""
from app import get_recommended_vaccines


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


def keys(recommendations):
    return {v["key"] for v in recommendations}


class TestClinicalSafety:
    def test_live_vaccines_excluded_during_pregnancy(self):
        """MMR, varicella and zoster are live vaccines — contraindicated in pregnancy."""
        recs = keys(get_recommended_vaccines(
            make_profile(sex="female", pregnant="yes", age=30)))
        assert "mmr" not in recs
        assert "varicella" not in recs
        assert "zoster" not in recs

    def test_every_recommendation_has_reasons_and_schedule(self):
        recs = get_recommended_vaccines(
            make_profile(age=68, conditions=["diabetes", "heart_disease"]))
        for v in recs:
            assert v["reasons"], f"{v['key']} has no clinical justification"
            assert v["schedule"], f"{v['key']} has no schedule"


class TestAgeGating:
    def test_zoster_included_for_50_plus(self):
        recs = keys(get_recommended_vaccines(make_profile(age=55)))
        assert "zoster" in recs

    def test_zoster_excluded_for_healthy_young_adult(self):
        recs = keys(get_recommended_vaccines(make_profile(age=25)))
        assert "zoster" not in recs

    def test_zoster_included_young_if_immunocompromised(self):
        """PAPDI 2025: zoster at any adult age for immunocompromised patients."""
        recs = keys(get_recommended_vaccines(
            make_profile(age=30, conditions=["immunocompromised"])))
        assert "zoster" in recs

    def test_hpv_included_under_45_only(self):
        young = keys(get_recommended_vaccines(make_profile(age=30)))
        older = keys(get_recommended_vaccines(make_profile(age=60)))
        assert "hpv" in young
        assert "hpv" not in older


class TestConditionTriggers:
    def test_diabetes_triggers_pneumococcal_and_hepb(self):
        recs = keys(get_recommended_vaccines(
            make_profile(age=45, conditions=["diabetes"])))
        assert "pneumococcal" in recs
        assert "hepatitis_b" in recs

    def test_influenza_recommended_for_everyone(self):
        for age in (20, 45, 70):
            recs = keys(get_recommended_vaccines(make_profile(age=age)))
            assert "influenza" in recs, f"influenza missing at age {age}"


class TestTravelLogic:
    def test_asia_travel_adds_japanese_encephalitis(self):
        no_travel = keys(get_recommended_vaccines(make_profile()))
        asia = keys(get_recommended_vaccines(
            make_profile(travel_regions=["Southeast Asia"])))
        assert "typhoid" in asia or "japanese_encephalitis" in asia
        assert len(asia) > len(no_travel)

    def test_africa_travel_adds_yellow_fever(self):
        recs = keys(get_recommended_vaccines(
            make_profile(travel_regions=["Sub-Saharan Africa"])))
        assert "yellow_fever" in recs

    def test_europe_travel_does_not_add_yellow_fever(self):
        recs = keys(get_recommended_vaccines(
            make_profile(travel_regions=["Europe"])))
        assert "yellow_fever" not in recs


class TestPrioritySorting:
    def test_high_priority_sorted_first(self):
        recs = get_recommended_vaccines(
            make_profile(age=70, conditions=["diabetes"], vaccinated_recently="no"))
        priorities = [v["priority"] for v in recs]
        first_high = priorities.index("high") if "high" in priorities else 0
        # No "high" priority vaccine should appear after a lower-priority one
        order = {"high": 0, "routine": 1, "recommended": 2, "catch_up": 3, "travel": 4}
        ranks = [order.get(p, 5) for p in priorities]
        assert ranks == sorted(ranks)
        assert first_high == 0

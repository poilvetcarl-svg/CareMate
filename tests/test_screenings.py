"""Tests for the preventive screening recommendations engine (USPSTF/WHO-backed)."""
from app import get_recommended_screenings


def make_profile(**overrides):
    base = {"age": 30, "sex": "male", "conditions": [],
            "pregnant": "no", "travel_regions": [], "vaccinated_recently": "yes"}
    base.update(overrides)
    return base


def keys(profile):
    return {s["key"] for s in get_recommended_screenings(profile)}


class TestUniversalScreenings:
    def test_blood_pressure_for_every_adult(self):
        for age in (18, 45, 80):
            assert "blood_pressure" in keys(make_profile(age=age)), f"missing at {age}"

    def test_results_carry_reason_frequency_sources(self):
        for s in get_recommended_screenings(make_profile(age=50, sex="female")):
            assert s["reasons"] and s["frequency"] and s["sources"]


class TestAgeGating:
    def test_colorectal_starts_at_45(self):
        assert "colorectal_cancer" not in keys(make_profile(age=40))
        assert "colorectal_cancer" in keys(make_profile(age=45))

    def test_mammogram_women_40_to_74(self):
        assert "breast_cancer" in keys(make_profile(age=45, sex="female"))
        assert "breast_cancer" not in keys(make_profile(age=35, sex="female"))
        assert "breast_cancer" not in keys(make_profile(age=80, sex="female"))

    def test_osteoporosis_women_65_plus(self):
        assert "osteoporosis" in keys(make_profile(age=68, sex="female"))
        assert "osteoporosis" not in keys(make_profile(age=50, sex="female"))


class TestSexGating:
    def test_cervical_and_breast_screening_women_only(self):
        male = keys(make_profile(age=45, sex="male"))
        assert "cervical_cancer" not in male
        assert "breast_cancer" not in male

    def test_prostate_men_only(self):
        assert "prostate" in keys(make_profile(age=60, sex="male"))
        assert "prostate" not in keys(make_profile(age=60, sex="female"))


class TestConditionRules:
    def test_lung_ct_requires_smoking(self):
        assert "lung_cancer" not in keys(make_profile(age=60))
        assert "lung_cancer" in keys(make_profile(age=60, conditions=["smoking"]))

    def test_diabetic_gets_eye_and_kidney_checks(self):
        diabetic = keys(make_profile(age=40, conditions=["diabetes"]))
        assert "eye_exam_diabetic" in diabetic
        assert "kidney_function" in diabetic

    def test_diabetic_not_offered_diabetes_screening(self):
        assert "diabetes_screen" not in keys(make_profile(age=40, conditions=["diabetes"]))

    def test_obesity_lowers_diabetes_screening_age(self):
        assert "diabetes_screen" not in keys(make_profile(age=25))
        assert "diabetes_screen" in keys(make_profile(age=25, conditions=["obesity"]))

    def test_high_priority_sorted_first(self):
        results = get_recommended_screenings(
            make_profile(age=55, sex="female", conditions=["diabetes", "smoking"]))
        order = {"high": 0, "routine": 1, "recommended": 2}
        ranks = [order.get(s["priority"], 3) for s in results]
        assert ranks == sorted(ranks)

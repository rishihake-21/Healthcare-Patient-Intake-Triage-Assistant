from pathlib import Path

from src.rule_engine import RuleEngine


ROOT = Path(__file__).resolve().parent.parent


def test_chest_pain_red_flag_maps_to_emergency():
    engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")

    result = engine.check_immediate_escalation(
        "chest_pain",
        ["sweating", "pain radiating to arm"],
    )

    assert result is not None
    assert result.rule_id == "CP-01"
    assert result.urgency_level == "EMERGENCY"
    assert result.department == "Emergency Department"


def test_missing_slots_are_union_for_category():
    engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")

    missing = engine.missing_slots("injury", {"age": 44, "associated_symptoms": ["cut"]})

    assert missing == ["mechanism", "onset", "severity_0_10"]


def test_baseline_rule_cites_real_rule():
    engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")

    result = engine.evaluate(
        "fever",
        {
            "onset": "today",
            "duration": "one day",
            "severity_0_10": 4,
            "associated_symptoms": [],
            "age": 30,
        },
    )

    assert result is not None
    assert result.rule_id == "FV-02"
    assert result.urgency_level == "ROUTINE"

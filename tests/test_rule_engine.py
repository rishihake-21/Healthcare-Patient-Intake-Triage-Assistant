from pathlib import Path

from src.rule_engine import RuleEngine


ROOT = Path(__file__).resolve().parent.parent


def load_engine() -> RuleEngine:
    return RuleEngine.load(ROOT / "data" / "triage_rules.json")


def test_chest_pain_red_flag_maps_to_emergency():
    engine = load_engine()

    result = engine.check_immediate_escalation(
        "chest_pain",
        ["sweating", "pain radiating to arm"],
    )

    assert result is not None
    assert result.rule_id == "CP-01"
    assert result.urgency_level == "EMERGENCY"
    assert result.department == "Emergency Department"


def test_missing_slots_for_each_category():
    engine = load_engine()

    expected = {
        "fever": ["age", "associated_symptoms", "duration", "onset", "severity_0_10"],
        "injury": ["age", "associated_symptoms", "mechanism", "onset", "severity_0_10"],
        "chest_pain": ["age", "associated_symptoms", "onset", "severity_0_10"],
        "breathing_difficulty": ["age", "associated_symptoms", "onset", "severity_0_10"],
        "abdominal_pain": ["age", "associated_symptoms", "duration", "onset", "severity_0_10"],
    }

    for category, missing in expected.items():
        assert engine.missing_slots(category, {}) == missing


def test_baseline_rule_cites_real_rule():
    engine = load_engine()

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


def test_evaluate_returns_none_when_category_has_no_baseline():
    engine = RuleEngine(
        [
            {
                "rule_id": "X-01",
                "category": "custom",
                "required_slots": [],
                "escalate_immediately_if": {"any_of_associated_symptoms": ["red"]},
                "decision": {"urgency_level": "URGENT", "department": "Human Review"},
                "rationale_template": "Red flag.",
            }
        ]
    )

    assert engine.evaluate("custom", {"associated_symptoms": []}) is None

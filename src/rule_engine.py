import json
from pathlib import Path

from src.schemas import RuleResult


RED_FLAG_ALIASES = {
    "shortness of breath": ["hard to breathe", "trouble breathing", "difficulty breathing", "difficult to breathe", "cannot breathe"],
    "sweating": ["sweating a lot", "sweaty", "cold sweat", "clammy"],
    "pain radiating to arm": ["radiating arm pain", "pain spreading to arm", "pain spreading to my arm", "pain going to arm", "pain going to my arm"],
    "pressure": ["chest pressure", "crushing pain", "chest tightness"],
    "unable to speak full sentences": ["cannot speak full sentences", "can't speak full sentences", "too breathless to speak"],
    "loss of consciousness": ["passed out", "blackout", "blacked out"],
    "unable to bear weight": ["cannot bear weight", "can't bear weight", "cannot stand", "can't stand"],
    "uncontrolled bleeding": ["bleeding won't stop", "bleeding will not stop", "heavy bleeding"],
}


class RuleEngine:
    def __init__(self, rules: list[dict]):
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> "RuleEngine":
        with path.open("r", encoding="utf-8") as handle:
            return cls(json.load(handle)["rules"])

    def categories(self) -> list[str]:
        return sorted({rule["category"] for rule in self.rules})

    def _rules_for(self, category: str) -> list[dict]:
        return [rule for rule in self.rules if rule["category"] == category]

    def check_immediate_escalation(self, category: str, symptoms: list[str]) -> RuleResult | None:
        symptom_texts = [symptom.lower() for symptom in symptoms]
        for rule in self._rules_for(category):
            flags = rule.get("escalate_immediately_if", {}).get("any_of_associated_symptoms", [])
            matched = [
                flag for flag in flags
                if any(red_flag_matches(flag, symptom) for symptom in symptom_texts)
            ]
            if matched:
                decision = rule["decision"]
                return RuleResult(
                    rule_id=rule["rule_id"],
                    urgency_level=decision["urgency_level"],
                    department=decision["department"],
                    matched_red_flags=matched,
                    rationale_template=rule["rationale_template"],
                    rule_label=rule.get("label"),
                )
        return None

    def red_flags_for(self, category: str) -> list[str]:
        flags: list[str] = []
        for rule in self._rules_for(category):
            flags.extend(rule.get("escalate_immediately_if", {}).get("any_of_associated_symptoms", []))
        return sorted(set(flags))

    def missing_slots(self, category: str, slots: dict) -> list[str]:
        required: set[str] = set()
        for rule in self._rules_for(category):
            required.update(rule["required_slots"])
        return sorted(slot for slot in required if not slots.get(slot))

    def evaluate(self, category: str, slots: dict) -> RuleResult | None:
        escalation = self.check_immediate_escalation(category, slots.get("associated_symptoms") or [])
        if escalation:
            return escalation

        baseline_rules = [
            rule for rule in self._rules_for(category)
            if not rule.get("escalate_immediately_if")
        ]
        if not baseline_rules:
            return None

        rule = baseline_rules[0]
        decision = rule["decision"]
        return RuleResult(
            rule_id=rule["rule_id"],
            urgency_level=decision["urgency_level"],
            department=decision["department"],
            matched_red_flags=[],
            rationale_template=rule["rationale_template"],
            rule_label=rule.get("label"),
        )


def red_flag_matches(flag: str, symptom: str) -> bool:
    canonical = _normalize(flag)
    normalized_symptom = _normalize(symptom)
    variants = [canonical, *(_normalize(alias) for alias in RED_FLAG_ALIASES.get(flag.lower(), []))]
    return any(variant and (variant == normalized_symptom or variant in normalized_symptom) for variant in variants)


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("'", "").split())

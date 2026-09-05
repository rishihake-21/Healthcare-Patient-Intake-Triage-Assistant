import json
from pathlib import Path

from src.schemas import RuleResult


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
        symptom_text = " | ".join(symptoms).lower()
        for rule in self._rules_for(category):
            flags = rule.get("escalate_immediately_if", {}).get("any_of_associated_symptoms", [])
            matched = [flag for flag in flags if flag.lower() in symptom_text]
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

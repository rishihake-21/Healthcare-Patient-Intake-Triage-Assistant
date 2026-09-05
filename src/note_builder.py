from src.schemas import ExtractedSlots, RuleResult, TriageNote


def build_note(result: RuleResult, slots: ExtractedSlots, unknowns: list[str]) -> TriageNote:
    flags = ", ".join(result.matched_red_flags) if result.matched_red_flags else "no listed red flags"
    rationale = (result.rationale_template or "Case requires human review.").format(
        matched_red_flags=flags
    )
    established = slots.model_dump(exclude_none=True)
    return TriageNote(
        urgency_level=result.urgency_level,
        department=result.department,
        matched_rule_id=result.rule_id,
        rationale=rationale,
        reported_vs_established=f"Structured facts established so far: {established}",
        remaining_unknowns=unknowns,
    )


def build_uncertain_note(slots: ExtractedSlots, unknowns: list[str]) -> TriageNote:
    return TriageNote(
        urgency_level="ESCALATE_UNCERTAIN",
        department=None,
        matched_rule_id=None,
        rationale="The assistant could not confidently match the case to a rule. A human triage reviewer should assess it.",
        reported_vs_established=f"Structured facts established so far: {slots.model_dump(exclude_none=True)}",
        remaining_unknowns=unknowns,
    )

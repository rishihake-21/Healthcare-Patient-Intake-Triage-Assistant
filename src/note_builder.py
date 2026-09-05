from src.gemini_client import GeminiClient, fallback_uncertain_narrative, sanitize_clinical_text
from src.schemas import ExtractedSlots, NoteNarrative, RuleResult, TriageNote


def build_note(
    result: RuleResult,
    slots: ExtractedSlots,
    unknowns: list[str],
    slot_sources: dict[str, str],
    gemini: GeminiClient,
) -> TriageNote:
    reported, established_by_followup = split_slots_by_source(slots, slot_sources)
    narrative = gemini.draft_narrative(
        rule_label=result.rule_label,
        rationale_template=result.rationale_template,
        matched_red_flags=result.matched_red_flags,
        reported=reported,
        established_by_followup=established_by_followup,
        unknowns=unknowns,
    )
    return assemble_note(result, narrative)


def build_uncertain_note(
    slots: ExtractedSlots,
    unknowns: list[str],
    slot_sources: dict[str, str],
    gemini: GeminiClient,
) -> TriageNote:
    reported, established_by_followup = split_slots_by_source(slots, slot_sources)
    narrative = fallback_uncertain_narrative(reported, established_by_followup, unknowns)
    return TriageNote(
        urgency_level="ESCALATE_UNCERTAIN",
        department=None,
        matched_rule_id=None,
        rationale=sanitize_clinical_text(narrative.rationale),
        reported_vs_established=sanitize_clinical_text(narrative.reported_vs_established),
        remaining_unknowns=narrative.remaining_unknowns,
    )


def assemble_note(result: RuleResult, narrative: NoteNarrative) -> TriageNote:
    return TriageNote(
        urgency_level=result.urgency_level,
        department=result.department,
        matched_rule_id=result.rule_id,
        rationale=sanitize_clinical_text(narrative.rationale),
        reported_vs_established=sanitize_clinical_text(narrative.reported_vs_established),
        remaining_unknowns=narrative.remaining_unknowns,
    )


def split_slots_by_source(slots: ExtractedSlots, slot_sources: dict[str, str]) -> tuple[dict, dict]:
    reported = {}
    followup = {}
    for key, value in slots.model_dump().items():
        if value in (None, "", "unclear", 0.0):
            continue
        if value == [] and key not in slot_sources:
            continue
        source = slot_sources.get(key, "reported")
        if source == "followup":
            followup[key] = value
        else:
            reported[key] = value
    return reported, followup

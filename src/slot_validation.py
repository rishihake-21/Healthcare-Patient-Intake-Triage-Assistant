from pydantic import ValidationError

from src.schemas import ExtractedSlots


def validate_slots(slots: ExtractedSlots | dict) -> ExtractedSlots:
    """
    Keep model output and deterministic extraction inside the backend's slot
    contract before anything reaches the rule engine.
    """
    try:
        validated = (
            slots
            if isinstance(slots, ExtractedSlots)
            else ExtractedSlots.model_validate(slots)
        )
    except ValidationError:
        return ExtractedSlots()

    cleaned = validated.model_dump()
    cleaned["associated_symptoms"] = [
        symptom.strip()
        for symptom in cleaned.get("associated_symptoms") or []
        if isinstance(symptom, str) and symptom.strip()
    ]

    try:
        return ExtractedSlots.model_validate(cleaned)
    except ValidationError:
        return ExtractedSlots()


def has_confident_category(slots: ExtractedSlots) -> bool:
    return slots.complaint_category != "unclear" and slots.confidence >= 0.7


def has_target_slot_value(slots: ExtractedSlots, target_slot: str | None) -> bool:
    if not target_slot:
        return any(
            value not in (None, [], "unclear", 0.0)
            for key, value in slots.model_dump().items()
            if key != "confidence"
        )
    return getattr(slots, target_slot, None) not in (None, [], "unclear", 0.0)

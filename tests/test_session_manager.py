from src.gemini_client import fallback_extract_slots, sanitize_clinical_text
from src.gemini_client import fallback_followup
from src.session_manager import SessionManager
from src.schemas import ExtractedSlots


def test_immediate_escalation_short_circuits_with_unknowns():
    manager = SessionManager()

    response = manager.create_session(
        "I am 58 with chest pressure, sweating, shortness of breath, and pain radiating to arm."
    )

    assert response.status == "completed"
    assert response.triage_note is not None
    assert response.triage_note.urgency_level == "EMERGENCY"
    assert response.triage_note.matched_rule_id == "CP-01"
    assert "onset" in response.triage_note.remaining_unknowns


def test_unclear_second_turn_escalates_to_human():
    manager = SessionManager()

    first = manager.create_session("I do not feel good.")
    second = manager.reply(first.session_id, "Still not sure what to say.")

    assert first.status == "awaiting_answer"
    assert second.status == "escalated"
    assert second.triage_note is not None
    assert second.triage_note.urgency_level == "ESCALATE_UNCERTAIN"
    assert second.triage_note.matched_rule_id is None


def test_sanitizer_removes_diagnostic_language():
    text = sanitize_clinical_text("This could be a heart attack diagnosis.")

    assert "heart attack" not in text.lower()
    assert "diagnosis" not in text.lower()


def test_bare_age_answer_uses_target_slot_context():
    slots = fallback_extract_slots("56", target_slot="age")

    assert slots.age == 56
    assert slots.onset is None
    assert slots.duration is None


def test_natural_language_age_answer_uses_target_slot_context():
    slots = fallback_extract_slots("I'm 56", target_slot="age")

    assert slots.age == 56


def test_age_followup_does_not_pollute_existing_temporal_slots():
    manager = SessionManager()
    current = ExtractedSlots(complaint_category="fever", confidence=0.75, onset="today", duration="today")
    update = fallback_extract_slots("56", target_slot="age")
    sources = {"complaint_category": "reported", "onset": "reported", "duration": "reported"}

    manager._merge_slots(current, update, sources, "followup", "56", target_slot="age")

    assert current.age == 56
    assert current.onset == "today"
    assert current.duration == "today"
    assert sources["age"] == "followup"


def test_associated_symptom_followup_preserves_all_reported_symptoms():
    slots = fallback_extract_slots("fainting and severe joint pain", target_slot="associated_symptoms")

    assert slots.associated_symptoms == ["fainting", "severe joint pain"]


def test_reproduced_fever_flow_does_not_repeat_age_question():
    manager = SessionManager()

    first = manager.create_session("hi, i have 102°F fever today")
    second = manager.reply(first.session_id, "9")
    third = manager.reply(first.session_id, "fainting and severe joint pain")
    fourth = manager.reply(first.session_id, "56")

    assert first.next_question == "On a scale from 0 to 10, how severe is it right now?"
    assert second.next_question == (
        "Are there any other symptoms, such as confusion, non-blanching rash, seizure, stiff neck?"
    )
    assert "fainting" not in second.next_question
    assert third.next_question == "How old is the patient?"
    assert fourth.next_question != "How old is the patient?"
    assert fourth.slots.age == 56
    assert fourth.slots.onset == "today"
    assert fourth.slots.duration == "today"
    assert fourth.slots.associated_symptoms == ["fainting", "severe joint pain"]
    assert fourth.status == "completed"
    assert fourth.triage_note is not None
    assert fourth.triage_note.matched_rule_id == "FV-02"


def test_category_specific_followup_uses_configured_red_flags_only():
    manager = SessionManager()

    response = manager.create_session("I have fever since yesterday")

    assert response.next_question == "On a scale from 0 to 10, how severe is it right now?"
    second = manager.reply(response.session_id, "10")

    assert second.next_question == (
        "Are there any other symptoms, such as confusion, non-blanching rash, seizure, stiff neck?"
    )
    assert "fainting" not in second.next_question


def test_followup_fallback_uses_passed_red_flag_examples():
    question = fallback_followup("associated_symptoms", ["sweating", "fainting"])

    assert question == "Are there any other symptoms, such as sweating, fainting?"


def test_null_extraction_does_not_erase_existing_values():
    manager = SessionManager()
    current = ExtractedSlots(
        complaint_category="fever",
        confidence=0.75,
        onset="today",
        duration="today",
        age=56,
    )
    sources = {"complaint_category": "reported", "onset": "reported", "duration": "reported", "age": "followup"}

    manager._merge_slots(current, ExtractedSlots(), sources, "followup", "", target_slot="age")

    assert current.age == 56
    assert current.onset == "today"
    assert current.duration == "today"


def test_later_targeted_correction_overwrites_previous_value():
    manager = SessionManager()
    current = ExtractedSlots(complaint_category="fever", confidence=0.75, age=56)
    sources = {"complaint_category": "reported", "age": "followup"}
    update = fallback_extract_slots("57", target_slot="age")

    manager._merge_slots(current, update, sources, "followup", "57", target_slot="age")

    assert current.age == 57
    assert sources["age"] == "followup"

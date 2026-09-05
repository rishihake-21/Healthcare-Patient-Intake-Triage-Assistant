from src.gemini_client import fallback_extract_slots, sanitize_clinical_text
from src.gemini_client import fallback_followup
from src.session_manager import SessionManager
from src.schemas import ExtractedSlots, Session


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
    assert second.triage_note.department is None
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


def test_vague_followup_answers_stay_unknown():
    slots = fallback_extract_slots("I don't know what's wrong", target_slot="associated_symptoms")

    assert slots.associated_symptoms == []


def test_unsupported_complaint_stays_unsupported():
    manager = SessionManager()

    response = manager.create_session("I have a cold.")

    assert response.slots.complaint_category == "unclear"
    assert response.next_question == (
        "Can you describe the main symptom: fever, injury, chest pain, breathing difficulty, or abdominal pain?"
    )


def test_followup_source_attribution_is_per_slot():
    manager = SessionManager()
    current = ExtractedSlots(complaint_category="chest_pain", confidence=0.75)
    update = ExtractedSlots(
        age=29,
        duration="two days",
        associated_symptoms=["chest tightness"],
    )
    sources = {}

    manager._merge_slots(current, update, sources, "followup", "I'm 29 and I've also had chest tightness for two days.", target_slot="age")

    assert current.age == 29
    assert current.duration == "two days"
    assert current.associated_symptoms == ["chest tightness"]
    assert sources["age"] == "followup"
    assert sources["duration"] == "reported"
    assert sources["associated_symptoms"] == "reported"


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


def test_unknown_followup_answer_does_not_repeat_same_question():
    manager = SessionManager()

    first = manager.create_session("hi, i have 102°F fever today")
    second = manager.reply(first.session_id, "9")
    third = manager.reply(first.session_id, "I don't know")

    assert second.next_question is not None
    assert "confusion" in second.next_question.lower()
    assert "stiff neck" in second.next_question.lower()
    assert "seizure" in second.next_question.lower()
    assert "non-blanching rash" in second.next_question.lower()
    assert third.next_question is not None
    assert third.next_question != second.next_question


def test_asked_slot_remains_after_valid_answer():
    manager = SessionManager()
    session = Session(
        session_id="test",
        asked_slots=["severity_0_10"],
        slots=ExtractedSlots(complaint_category="fever", confidence=0.75),
    )

    manager._merge_slots(
        session.slots,
        ExtractedSlots(severity_0_10=8),
        {},
        "followup",
        "8",
        target_slot="severity_0_10",
    )

    assert session.slots.severity_0_10 == 8
    assert "severity_0_10" in session.asked_slots


def test_asked_slot_remains_after_unknown_answer():
    manager = SessionManager()
    session = Session(
        session_id="test",
        asked_slots=["associated_symptoms"],
        slots=ExtractedSlots(complaint_category="fever", confidence=0.75),
    )

    manager._merge_slots(
        session.slots,
        fallback_extract_slots("I don't know", target_slot="associated_symptoms"),
        {},
        "followup",
        "I don't know",
        target_slot="associated_symptoms",
    )

    assert session.slots.associated_symptoms == []
    assert "associated_symptoms" in session.asked_slots


def test_same_slot_is_never_selected_twice():
    manager = SessionManager()
    session = Session(session_id="test", asked_slots=["age"])

    assert manager._next_unasked_missing(session, ["age"]) is None


def test_next_missing_unasked_slot_is_selected_after_answering_previous_slot():
    manager = SessionManager()
    session = Session(
        session_id="test",
        asked_slots=["severity_0_10"],
        slots=ExtractedSlots(complaint_category="fever", confidence=0.75, severity_0_10=8),
    )

    assert manager._next_unasked_missing(session, ["severity_0_10", "associated_symptoms", "age"]) == "associated_symptoms"


def test_correction_overwrites_without_removing_asked_slot():
    manager = SessionManager()
    session = Session(
        session_id="test",
        asked_slots=["age"],
        slots=ExtractedSlots(complaint_category="fever", confidence=0.75, age=29),
    )
    sources = {"age": "followup"}

    manager._merge_slots(
        session.slots,
        fallback_extract_slots("39", target_slot="age"),
        sources,
        "followup",
        "39",
        target_slot="age",
    )

    assert session.slots.age == 39
    assert sources["age"] == "followup"
    assert "age" in session.asked_slots


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


def test_later_targeted_severity_correction_overwrites_previous_value():
    manager = SessionManager()
    current = ExtractedSlots(complaint_category="fever", confidence=0.75, severity_0_10=5)
    sources = {"complaint_category": "reported", "severity_0_10": "followup"}
    update = fallback_extract_slots("8", target_slot="severity_0_10")

    manager._merge_slots(current, update, sources, "followup", "8", target_slot="severity_0_10")

    assert current.severity_0_10 == 8
    assert sources["severity_0_10"] == "followup"


def test_keyword_classification_avoids_gemini_extraction_and_followup():
    manager = SessionManager()
    manager.gemini = NoGeminiCalls()

    response = manager.create_session("I have fever today")

    assert response.slots.complaint_category == "fever"
    assert response.next_question == "On a scale from 0 to 10, how severe is it right now?"


def test_gemini_extraction_is_last_resort_after_keyword_and_embedding_fail():
    manager = SessionManager()
    manager.embedding_index = NoEmbeddingMatch()
    manager.gemini = LastResortGemini()

    response = manager.create_session("Everything feels wrong and I cannot explain it.")

    assert manager.gemini.extract_calls == 1
    assert response.slots.complaint_category == "fever"
    assert response.next_question == "On a scale from 0 to 10, how severe is it right now?"


class NoGeminiCalls:
    def extract_slots(self, *args, **kwargs):
        raise AssertionError("Gemini extraction should not be called.")

    def generate_followup(self, *args, **kwargs):
        raise AssertionError("Gemini follow-up generation should not be called.")

    def draft_narrative(self, *args, **kwargs):
        raise AssertionError("This test should not finalize a note.")


class NoEmbeddingMatch:
    def classify(self, text):
        return None


class LastResortGemini:
    def __init__(self):
        self.extract_calls = 0

    def extract_slots(self, *args, **kwargs):
        self.extract_calls += 1
        return ExtractedSlots(complaint_category="fever", confidence=0.9)

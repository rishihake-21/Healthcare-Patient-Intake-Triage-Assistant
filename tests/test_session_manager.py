from src.gemini_client import sanitize_clinical_text
from src.session_manager import SessionManager


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

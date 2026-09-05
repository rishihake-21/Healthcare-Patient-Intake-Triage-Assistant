from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from src.db import save_session
from src.gemini_client import GeminiClient
from src.note_builder import build_note, build_uncertain_note
from src.rule_engine import RuleEngine
from src.schemas import ExtractedSlots, SessionResponse, TriageNote


MAX_FOLLOWUPS = 4
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SessionState:
    session_id: str
    status: str = "active"
    followup_count: int = 0
    transcript: list[dict] = field(default_factory=list)
    slots: ExtractedSlots = field(default_factory=ExtractedSlots)
    note: TriageNote | None = None


class SessionManager:
    def __init__(self) -> None:
        self.rule_engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")
        self.gemini = GeminiClient()
        self.sessions: dict[str, SessionState] = {}

    def create_session(self, description: str) -> SessionResponse:
        session = SessionState(session_id=str(uuid4()))
        self.sessions[session.session_id] = session
        return self._handle_turn(session, description)

    def reply(self, session_id: str, answer: str) -> SessionResponse:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status in {"completed", "escalated"}:
            return self._response(session)
        return self._handle_turn(session, answer)

    def _handle_turn(self, session: SessionState, patient_text: str) -> SessionResponse:
        session.transcript.append({"role": "patient", "content": patient_text})
        extracted = self.gemini.extract_slots(patient_text)
        self._merge_slots(session.slots, extracted)

        if session.slots.complaint_category == "unclear":
            return self._ask(session, "Can you describe the main symptom: fever, injury, chest pain, breathing difficulty, or abdominal pain?")

        escalation = self.rule_engine.check_immediate_escalation(
            session.slots.complaint_category,
            session.slots.associated_symptoms,
        )
        if escalation is not None:
            return self._finalize(session, escalation)

        missing = self.rule_engine.missing_slots(
            session.slots.complaint_category,
            session.slots.model_dump(),
        )
        if missing and session.followup_count < MAX_FOLLOWUPS:
            session.followup_count += 1
            return self._ask(session, self.gemini.generate_followup(missing[0]))

        if missing:
            session.note = build_uncertain_note(session.slots, missing)
            session.status = "escalated"
            self._persist(session)
            return self._response(session)

        result = self.rule_engine.evaluate(session.slots.complaint_category, session.slots.model_dump())
        if result is None:
            session.note = build_uncertain_note(session.slots, [])
            session.status = "escalated"
            self._persist(session)
            return self._response(session)

        return self._finalize(session, result)

    def _ask(self, session: SessionState, question: str) -> SessionResponse:
        session.status = "awaiting_answer"
        session.transcript.append({"role": "assistant", "content": question})
        self._persist(session)
        return self._response(session, next_question=question)

    def _finalize(self, session: SessionState, result) -> SessionResponse:
        unknowns = self.rule_engine.missing_slots(session.slots.complaint_category, session.slots.model_dump())
        session.note = build_note(result, session.slots, unknowns)
        session.status = "completed"
        self._persist(session)
        return self._response(session)

    def _merge_slots(self, current: ExtractedSlots, update: ExtractedSlots) -> None:
        data = update.model_dump()
        for key, value in data.items():
            if key == "associated_symptoms" and value:
                current.associated_symptoms = sorted(set(current.associated_symptoms + value))
            elif value not in (None, [], "unclear", 0.0):
                setattr(current, key, value)

    def _persist(self, session: SessionState) -> None:
        save_session(
            session.session_id,
            session.status,
            session.slots.model_dump(),
            session.transcript,
            session.note.model_dump() if session.note else None,
        )

    def _response(self, session: SessionState, next_question: str | None = None) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            status=session.status,
            next_question=next_question,
            triage_note=session.note,
            slots=session.slots,
        )

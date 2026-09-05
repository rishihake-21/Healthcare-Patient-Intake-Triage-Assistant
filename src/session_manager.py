import json
from pathlib import Path
from uuid import uuid4

from src.db import append_message, get_session_record, save_full_session
from src.embedding_index import EmbeddingIndex
from src.gemini_client import GeminiClient
from src.note_builder import build_note, build_uncertain_note
from src.rule_engine import RuleEngine
from src.schemas import ExtractedSlots, Message, Session, SessionResponse, TriageNote


MAX_FOLLOWUPS = 4
ROOT = Path(__file__).resolve().parent.parent

SLOT_DESCRIPTIONS = {
    "age": "patient age in years",
    "associated_symptoms": "other symptoms or red flags reported with the main complaint",
    "duration": "how long the symptom has been present",
    "mechanism": "how an injury happened",
    "onset": "when the symptom started",
    "severity_0_10": "current severity on a 0 to 10 scale",
}
SLOT_ORDER = ["onset", "duration", "mechanism", "severity_0_10", "associated_symptoms", "age"]


class SessionManager:
    def __init__(self) -> None:
        self.rule_engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")
        self.gemini = GeminiClient()
        self.embedding_index = EmbeddingIndex.build_or_load(
            ROOT / "data" / "category_embeddings.json",
            self.rule_engine.categories(),
            self.gemini,
        )
        self.sessions: dict[str, Session] = {}

    def create_session(self, description: str) -> SessionResponse:
        session = Session(session_id=str(uuid4()))
        self.sessions[session.session_id] = session
        return self._handle_turn(session, description)

    def reply(self, session_id: str, answer: str) -> SessionResponse:
        session = self._get_session(session_id)
        if session.status in {"completed", "escalated"}:
            return self._response(session)
        return self._handle_turn(session, answer)

    def get(self, session_id: str) -> SessionResponse:
        return self._response(self._get_session(session_id))

    def _handle_turn(self, session: Session, patient_text: str) -> SessionResponse:
        source = "reported" if not any(message.role == "patient" for message in session.transcript) else "followup"
        target_slot = session.pending_slot if source == "followup" else None
        self._add_message(session, "patient", patient_text)

        extracted = self.gemini.extract_slots(
            render_transcript(session.transcript),
            target_slot=target_slot,
            latest_answer=patient_text,
        )
        self._merge_slots(session.slots, extracted, session.slot_sources, source, patient_text, target_slot)

        if session.slots.complaint_category == "unclear" or session.slots.confidence < 0.5:
            guessed = self.embedding_index.classify(patient_text)
            if guessed:
                session.slots.complaint_category = guessed
                session.slots.confidence = max(session.slots.confidence, 0.55)
                session.slot_sources["complaint_category"] = "fallback"

        if session.slots.complaint_category == "unclear":
            session.unclear_count += 1
            if session.unclear_count >= 2:
                return self._escalate_uncertain(session, ["complaint_category"])
            return self._ask(
                session,
                "Can you describe the main symptom: fever, injury, chest pain, breathing difficulty, or abdominal pain?",
            )

        escalation = self.rule_engine.check_immediate_escalation(
            session.slots.complaint_category,
            session.slots.associated_symptoms,
        )
        if escalation is not None:
            return self._finalize(session, escalation)

        missing = self._ordered_missing(session)
        target_slot = self._next_unasked_missing(session, missing)
        if target_slot and session.followup_count < MAX_FOLLOWUPS:
            session.followup_count += 1
            red_flag_examples = []
            if target_slot == "associated_symptoms":
                red_flag_examples = self.rule_engine.red_flags_for(session.slots.complaint_category)
            question = self.gemini.generate_followup(
                target_slot,
                SLOT_DESCRIPTIONS.get(target_slot, target_slot),
                render_transcript(session.transcript),
                red_flag_examples=red_flag_examples,
            )
            return self._ask(session, question.question_text, target_slot=target_slot)

        if missing:
            return self._escalate_uncertain(session, missing)

        result = self.rule_engine.evaluate(session.slots.complaint_category, session.slots.model_dump())
        if result is None:
            return self._escalate_uncertain(session, [])
        return self._finalize(session, result)

    def _ask(self, session: Session, question: str, target_slot: str | None = None) -> SessionResponse:
        session.status = "awaiting_answer"
        session.pending_slot = target_slot
        if target_slot and target_slot not in session.asked_slots:
            session.asked_slots.append(target_slot)
        self._add_message(session, "assistant", question)
        self._persist(session)
        return self._response(session, next_question=question)

    def _finalize(self, session: Session, result) -> SessionResponse:
        unknowns = self._ordered_missing(session)
        session.note = build_note(result, session.slots, unknowns, session.slot_sources, self.gemini)
        session.status = "completed"
        session.pending_slot = None
        self._persist(session)
        return self._response(session)

    def _escalate_uncertain(self, session: Session, unknowns: list[str]) -> SessionResponse:
        session.note = build_uncertain_note(session.slots, unknowns, session.slot_sources, self.gemini)
        session.status = "escalated"
        session.pending_slot = None
        self._persist(session)
        return self._response(session)

    def _merge_slots(
        self,
        current: ExtractedSlots,
        update: ExtractedSlots,
        slot_sources: dict[str, str],
        source: str,
        patient_text: str,
        target_slot: str | None = None,
    ) -> None:
        for key, value in update.model_dump().items():
            slot_source = "followup" if key == target_slot else "reported"
            if key == "associated_symptoms":
                if value:
                    current.associated_symptoms = sorted(set(current.associated_symptoms + value))
                    slot_sources[key] = slot_source
                elif mentions_no_associated_symptoms(patient_text):
                    current.associated_symptoms = []
                    slot_sources[key] = slot_source
                continue
            if value not in (None, [], "unclear", 0.0):
                setattr(current, key, value)
                slot_sources[key] = slot_source

    def _ordered_missing(self, session: Session) -> list[str]:
        missing = self.rule_engine.missing_slots(session.slots.complaint_category, session.slots.model_dump())
        return sorted(missing, key=lambda slot: SLOT_ORDER.index(slot) if slot in SLOT_ORDER else len(SLOT_ORDER))

    def _next_unasked_missing(self, session: Session, missing: list[str]) -> str | None:
        for slot in missing:
            if slot not in session.asked_slots:
                return slot
        return None

    def _add_message(self, session: Session, role: str, content: str) -> None:
        message = Message(role=role, content=content)
        session.transcript.append(message)
        try:
            append_message(session.session_id, role, content)
        except RuntimeError:
            pass

    def _persist(self, session: Session) -> None:
        try:
            save_full_session(
                session.session_id,
                session.status,
                session.followup_count,
                session.unclear_count,
                session.pending_slot,
                session.asked_slots,
                session.slots.model_dump(),
                session.slot_sources,
                session.note.model_dump() if session.note else None,
            )
        except RuntimeError:
            pass

    def _response(self, session: Session, next_question: str | None = None) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            status=session.status,
            next_question=next_question,
            triage_note=session.note,
            slots=session.slots,
            slot_sources=session.slot_sources,
        )

    def _get_session(self, session_id: str) -> Session:
        if session_id in self.sessions:
            return self.sessions[session_id]

        record = get_session_record(session_id)
        if record is None:
            raise KeyError(session_id)

        session_row = record["session"]
        note = TriageNote.model_validate(record["note"]) if record["note"] else None
        session = Session(
            session_id=session_id,
            status=session_row["status"],
            followup_count=session_row["followup_count"],
            unclear_count=session_row["unclear_count"],
            pending_slot=session_row["pending_slot"] if "pending_slot" in session_row.keys() else None,
            asked_slots=json.loads(session_row["asked_slots_json"]) if "asked_slots_json" in session_row.keys() else [],
            transcript=[Message.model_validate(message) for message in record["messages"]],
            slots=ExtractedSlots.model_validate_json(session_row["slots_json"]),
            slot_sources=dict(json.loads(session_row["slot_sources_json"])),
            note=note,
        )
        self.sessions[session_id] = session
        return session


def render_transcript(transcript: list[Message]) -> str:
    return "\n".join(f"{message.role.title()}: {message.content}" for message in transcript)


def mentions_no_associated_symptoms(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in ["no other symptoms", "no red flags", "nothing else", "none"])

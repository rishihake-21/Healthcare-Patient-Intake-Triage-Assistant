from typing import Any, Literal

from pydantic import BaseModel, Field


ComplaintCategory = Literal[
    "fever",
    "injury",
    "chest_pain",
    "breathing_difficulty",
    "abdominal_pain",
    "unclear",
]
UrgencyLevel = Literal["EMERGENCY", "URGENT", "SEMI_URGENT", "ROUTINE", "ESCALATE_UNCERTAIN"]
SessionStatus = Literal["active", "awaiting_answer", "completed", "escalated"]
SlotSource = Literal["reported", "followup", "fallback"]


class ExtractedSlots(BaseModel):
    complaint_category: ComplaintCategory = "unclear"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    onset: str | None = None
    duration: str | None = None
    severity_0_10: int | None = Field(default=None, ge=0, le=10)
    associated_symptoms: list[str] = Field(default_factory=list)
    age: int | None = Field(default=None, ge=0, le=130)
    mechanism: str | None = None
    relevant_history: str | None = None


class FollowUpQuestion(BaseModel):
    target_slot: str
    question_text: str


class NoteNarrative(BaseModel):
    rationale: str
    reported_vs_established: str
    remaining_unknowns: list[str] = Field(default_factory=list)


class Message(BaseModel):
    role: Literal["patient", "assistant", "system"]
    content: str


class SlotState(BaseModel):
    value: Any
    source: SlotSource


class RuleResult(BaseModel):
    rule_id: str | None
    urgency_level: UrgencyLevel
    department: str | None
    matched_red_flags: list[str] = Field(default_factory=list)
    rationale_template: str | None = None
    rule_label: str | None = None


class TriageNote(BaseModel):
    urgency_level: UrgencyLevel
    department: str | None
    matched_rule_id: str | None
    rationale: str
    reported_vs_established: str
    remaining_unknowns: list[str]
    disclaimer: str = "Hackathon prototype only. This does not diagnose or replace clinical judgment."


class Session(BaseModel):
    session_id: str
    status: SessionStatus = "active"
    followup_count: int = 0
    unclear_count: int = 0
    pending_slot: str | None = None
    asked_slots: list[str] = Field(default_factory=list)
    transcript: list[Message] = Field(default_factory=list)
    slots: ExtractedSlots = Field(default_factory=ExtractedSlots)
    slot_sources: dict[str, SlotSource] = Field(default_factory=dict)
    note: TriageNote | None = None


class SessionResponse(BaseModel):
    session_id: str
    status: SessionStatus
    next_question: str | None = None
    triage_note: TriageNote | None = None
    slots: ExtractedSlots
    slot_sources: dict[str, SlotSource] = Field(default_factory=dict)

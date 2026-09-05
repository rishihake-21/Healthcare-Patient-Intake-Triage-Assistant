from pydantic import BaseModel, Field


ComplaintCategory = str
UrgencyLevel = str


class ExtractedSlots(BaseModel):
    complaint_category: ComplaintCategory = "unclear"
    confidence: float = 0.0
    onset: str | None = None
    duration: str | None = None
    severity_0_10: int | None = Field(default=None, ge=0, le=10)
    associated_symptoms: list[str] = Field(default_factory=list)
    age: int | None = Field(default=None, ge=0, le=130)
    mechanism: str | None = None
    relevant_history: str | None = None


class RuleResult(BaseModel):
    rule_id: str | None
    urgency_level: UrgencyLevel
    department: str | None
    matched_red_flags: list[str] = Field(default_factory=list)
    rationale_template: str | None = None


class TriageNote(BaseModel):
    urgency_level: UrgencyLevel
    department: str | None
    matched_rule_id: str | None
    rationale: str
    reported_vs_established: str
    remaining_unknowns: list[str]
    disclaimer: str = "Hackathon prototype only. This does not diagnose or replace clinical judgment."


class SessionResponse(BaseModel):
    session_id: str
    status: str
    next_question: str | None = None
    triage_note: TriageNote | None = None
    slots: ExtractedSlots

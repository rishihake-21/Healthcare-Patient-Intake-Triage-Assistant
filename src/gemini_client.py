import json
import logging
import os
import re
import time
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from src.schemas import ExtractedSlots, FollowUpQuestion, NoteNarrative


load_dotenv()

LOGGER = logging.getLogger(__name__)
GEN_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
EMBED_MODEL = "gemini-embedding-001"
T = TypeVar("T", bound=BaseModel)

CATEGORIES = {
    "fever": ["fever", "temperature", "chills", "hot"],
    "injury": ["injury", "hurt", "fall", "cut", "bleeding", "sprain", "fracture", "twisted"],
    "chest_pain": ["chest pain", "chest", "tightness", "pressure"],
    "breathing_difficulty": ["breathing", "breath", "shortness of breath", "wheezing", "cannot breathe"],
    "abdominal_pain": ["abdomen", "abdominal", "stomach", "belly", "gut"],
}

RED_FLAG_PHRASES = [
    "stiff neck",
    "confusion",
    "non-blanching rash",
    "seizure",
    "visible deformity",
    "uncontrolled bleeding",
    "unable to bear weight",
    "loss of consciousness",
    "shortness of breath",
    "sweating",
    "pain radiating to arm",
    "fainting",
    "pressure",
    "blue lips",
    "unable to speak full sentences",
    "severe wheezing",
    "blood in stool",
    "vomiting blood",
    "rigid abdomen",
    "pregnant",
]

DIAGNOSTIC_TERMS = [
    "appendicitis",
    "asthma attack",
    "cardiac arrest",
    "heart attack",
    "meningitis",
    "pneumonia",
    "sepsis",
    "stroke",
]


class GeminiClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = None
        if self.api_key:
            try:
                from google import genai

                self.client = genai.Client(api_key=self.api_key)
            except Exception:
                LOGGER.exception("Gemini SDK initialization failed; using deterministic fallbacks.")

    @property
    def available(self) -> bool:
        return self.client is not None

    def extract_slots(self, transcript: str) -> ExtractedSlots:
        system = (
            "You extract structured intake facts for a hackathon triage-note assistant. "
            "Return JSON only. Do not diagnose. Use complaint_category only from: fever, "
            "injury, chest_pain, breathing_difficulty, abdominal_pain, unclear. "
            "Use null for unknown fields. Extract associated_symptoms as plain patient-reported phrases."
        )
        contents = f"{system}\n\nTranscript:\n{transcript}"
        try:
            return self._call_structured(contents, ExtractedSlots)
        except Exception:
            LOGGER.info("Falling back to deterministic slot extraction.", exc_info=True)
            return fallback_extract_slots(transcript)

    def generate_followup(self, target_slot: str, slot_description: str, transcript: str) -> FollowUpQuestion:
        system = (
            "Write exactly one short, plain-language follow-up question for a patient. "
            "Ask only for the target slot. Do not diagnose or mention disease names."
        )
        contents = (
            f"{system}\nTarget slot: {target_slot}\nSlot meaning: {slot_description}\n"
            f"Transcript:\n{transcript}"
        )
        try:
            question = self._call_structured(contents, FollowUpQuestion)
            return FollowUpQuestion(
                target_slot=target_slot,
                question_text=sanitize_clinical_text(question.question_text),
            )
        except Exception:
            LOGGER.info("Falling back to templated follow-up.", exc_info=True)
            return FollowUpQuestion(target_slot=target_slot, question_text=fallback_followup(target_slot))

    def draft_narrative(
        self,
        rule_label: str | None,
        rationale_template: str | None,
        matched_red_flags: list[str],
        reported: dict,
        established_by_followup: dict,
        unknowns: list[str],
    ) -> NoteNarrative:
        system = (
            "Draft only narrative fields for a triage note. Do not set urgency, department, "
            "or rule id. Do not diagnose or name possible diseases. Be concise and cite only "
            "the supplied rule rationale in ordinary language."
        )
        contents = (
            f"{system}\nRule label: {rule_label or 'Human review'}\n"
            f"Rationale template: {rationale_template or 'Needs human review.'}\n"
            f"Matched red flags: {matched_red_flags}\nReported initially: {reported}\n"
            f"Established by follow-up: {established_by_followup}\nUnknowns: {unknowns}"
        )
        try:
            narrative = self._call_structured(contents, NoteNarrative)
            return sanitize_narrative(narrative)
        except Exception:
            LOGGER.info("Falling back to templated narrative.", exc_info=True)
            return fallback_narrative(rationale_template, matched_red_flags, reported, established_by_followup, unknowns)

    def embed(self, text: str) -> list[float]:
        if not self.client:
            return lexical_vector(text)
        result = self.client.models.embed_content(model=EMBED_MODEL, contents=text)
        return list(result.embeddings[0].values)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.client:
            return [lexical_vector(text) for text in texts]
        result = self.client.models.embed_content(model=EMBED_MODEL, contents=texts)
        return [list(embedding.values) for embedding in result.embeddings]

    def _call_structured(self, contents: str, schema: type[T]) -> T:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self.client.models.generate_content(
                    model=GEN_MODEL,
                    contents=contents,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": schema,
                        "temperature": 0.1,
                    },
                )
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                if parsed is not None:
                    return schema.model_validate(parsed)
                return schema.model_validate(json.loads(response.text))
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.5)
        raise RuntimeError("Gemini structured call failed.") from last_error


def fallback_extract_slots(text: str) -> ExtractedSlots:
    patient_text = "\n".join(
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith("patient:") and ":" in line
    ) or text
    lowered = patient_text.lower()
    category = "unclear"
    for candidate, keywords in CATEGORIES.items():
        if any(keyword in lowered for keyword in keywords):
            category = candidate
            break

    severity = None
    severity_match = re.search(r"\b([0-9]|10)\s*(?:/10|out of 10)?\b", lowered)
    if severity_match:
        severity = int(severity_match.group(1))

    age = None
    age_match = re.search(r"\b(?:age|aged|i am|i'm|patient is)\s*(\d{1,3})\b", lowered)
    if age_match:
        age = int(age_match.group(1))

    symptoms = [phrase for phrase in RED_FLAG_PHRASES if phrase in lowered]
    if "no red flags" in lowered or "no other symptoms" in lowered:
        symptoms = []

    return ExtractedSlots(
        complaint_category=category,
        confidence=0.75 if category != "unclear" else 0.0,
        onset=patient_text if any(word in lowered for word in ["today", "yesterday", "since", "started", "sudden"]) else None,
        duration=patient_text if any(word in lowered for word in ["day", "hour", "week", "since", "yesterday"]) else None,
        severity_0_10=severity,
        associated_symptoms=symptoms,
        age=age,
        mechanism=patient_text if category == "injury" and any(word in lowered for word in ["fall", "cut", "twisted", "hit"]) else None,
    )


def fallback_followup(target_slot: str) -> str:
    questions = {
        "age": "How old is the patient?",
        "associated_symptoms": "Are there any other symptoms or red flags, such as fainting, confusion, severe breathing trouble, unusual bleeding, or pain spreading elsewhere?",
        "duration": "How long has this been going on?",
        "mechanism": "How did the injury happen?",
        "onset": "When did this start?",
        "severity_0_10": "On a scale from 0 to 10, how severe is it right now?",
    }
    return questions.get(target_slot, "Can you share one more detail about the main symptom?")


def fallback_narrative(
    rationale_template: str | None,
    matched_red_flags: list[str],
    reported: dict,
    established_by_followup: dict,
    unknowns: list[str],
) -> NoteNarrative:
    flags = ", ".join(matched_red_flags) if matched_red_flags else "no listed red flags"
    rationale = (rationale_template or "The case could not be confidently matched and needs human review.").format(
        matched_red_flags=flags
    )
    return sanitize_narrative(
        NoteNarrative(
            rationale=rationale,
            reported_vs_established=(
                f"Initial report: {compact_dict(reported)}. "
                f"Follow-up established: {compact_dict(established_by_followup)}."
            ),
            remaining_unknowns=unknowns,
        )
    )


def compact_dict(data: dict) -> str:
    cleaned = {key: value for key, value in data.items() if value not in (None, [], "", "unclear", 0.0)}
    return str(cleaned or "none recorded")


def sanitize_narrative(narrative: NoteNarrative) -> NoteNarrative:
    return NoteNarrative(
        rationale=sanitize_clinical_text(narrative.rationale),
        reported_vs_established=sanitize_clinical_text(narrative.reported_vs_established),
        remaining_unknowns=[sanitize_clinical_text(item) for item in narrative.remaining_unknowns],
    )


def sanitize_clinical_text(text: str) -> str:
    cleaned = text
    for term in DIAGNOSTIC_TERMS:
        cleaned = re.sub(re.escape(term), "a serious condition", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(diagnosed|diagnosis|diagnose)\b", "assessed", cleaned, flags=re.IGNORECASE)
    return cleaned


def lexical_vector(text: str) -> list[float]:
    lowered = text.lower()
    return [
        float(sum(1 for keyword in keywords if keyword in lowered))
        for keywords in CATEGORIES.values()
    ]

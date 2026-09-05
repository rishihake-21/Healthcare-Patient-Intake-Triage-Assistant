import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from src.rule_engine import RED_FLAG_ALIASES
from src.schemas import ExtractedSlots, FollowUpQuestion, NoteNarrative


load_dotenv()

LOGGER = logging.getLogger(__name__)
GEN_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
EMBED_MODEL = "gemini-embedding-001"
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "8"))
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

RED_FLAG_VOCABULARY = "\n".join(
    [
        "Canonical red-flag vocabulary for associated_symptoms:",
        "- fever: stiff neck, confusion, non-blanching rash, seizure",
        "- injury: visible deformity, uncontrolled bleeding, unable to bear weight, loss of consciousness",
        "- chest_pain: shortness of breath, sweating, pain radiating to arm, fainting, pressure",
        "- breathing_difficulty: blue lips, unable to speak full sentences, severe wheezing, confusion",
        "- abdominal_pain: fainting, blood in stool, vomiting blood, rigid abdomen, pregnant",
        "When patient wording is clearly equivalent, include the canonical phrase in associated_symptoms.",
    ]
)

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

VAGUE_ANSWER_PHRASES = [
    "i don't know",
    "im not sure",
    "i'm not sure",
    "nothing specific",
    "nothing else",
    "i just feel terrible",
    "i dont know what's wrong",
    "i don't know what's wrong",
    "i do not know what's wrong",
    "not sure",
]


class GeminiClient:
    def __init__(self) -> None:
        testing = "pytest" in sys.modules
        disabled = os.getenv("GEMINI_DISABLE_API") == "1"
        self.api_key = None if testing or disabled else os.getenv("GEMINI_API_KEY")
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

    def extract_slots(
        self,
        transcript: str,
        target_slot: str | None = None,
        latest_answer: str | None = None,
    ) -> ExtractedSlots:
        system = (
            "You extract structured intake facts for a hackathon triage-note assistant. "
            "Return JSON only. Do not diagnose. Use complaint_category only from: fever, "
            "injury, chest_pain, breathing_difficulty, abdominal_pain, unclear. "
            "Use null for unknown fields. Extract associated_symptoms as plain patient-reported phrases. "
            f"{RED_FLAG_VOCABULARY} "
            "When a target slot is supplied, interpret the latest patient answer primarily as that slot "
            "and do not fill unrelated fields from the older conversation."
        )
        if target_slot:
            contents = (
                f"{system}\n\nTarget slot: {target_slot}\n"
                f"Latest patient answer:\n{latest_answer or ''}\n\nConversation so far:\n{transcript}"
            )
        else:
            contents = f"{system}\n\nTranscript:\n{transcript}"
        try:
            return self._call_structured(contents, ExtractedSlots)
        except Exception:
            LOGGER.info("Falling back to deterministic slot extraction.", exc_info=True)
            return fallback_extract_slots(latest_answer or transcript, target_slot=target_slot)

    def generate_followup(
        self,
        target_slot: str,
        slot_description: str,
        transcript: str,
        red_flag_examples: list[str] | None = None,
    ) -> FollowUpQuestion:
        system = (
            "Write exactly one short, plain-language follow-up question for a patient. "
            "Ask only for the target slot. Do not diagnose or mention disease names. "
            "If red-flag examples are supplied, use only those examples; do not add other examples."
        )
        examples_text = ", ".join(red_flag_examples or [])
        contents = (
            f"{system}\nTarget slot: {target_slot}\nSlot meaning: {slot_description}\n"
            f"Configured red-flag examples for this complaint: {examples_text or 'none'}\n"
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
            return FollowUpQuestion(
                target_slot=target_slot,
                question_text=fallback_followup(target_slot, red_flag_examples),
            )

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

    def draft_narrative_uncertain(
        self,
        reported: dict,
        established_by_followup: dict,
        unknowns: list[str],
    ) -> NoteNarrative:
        system = (
            "Draft narrative sections for a triage note where the assistant could not "
            "confidently match the case to a deterministic triage rule. State plainly "
            "that a human triage reviewer must assess it. Do not suggest a diagnosis, "
            "urgency level, or clinical department."
        )
        contents = (
            f"{system}\nReported initially: {reported}\n"
            f"Established by follow-up: {established_by_followup}\nUnknowns: {unknowns}"
        )
        try:
            narrative = self._call_structured(contents, NoteNarrative)
            return sanitize_narrative(narrative)
        except Exception:
            LOGGER.info("Falling back to templated uncertain narrative.", exc_info=True)
            return fallback_uncertain_narrative(reported, established_by_followup, unknowns)

    def embed(self, text: str) -> list[float]:
        if not self.client:
            return lexical_vector(text)
        try:
            result = run_with_timeout(
                lambda: self.client.models.embed_content(model=EMBED_MODEL, contents=text)
            )
            return list(result.embeddings[0].values)
        except Exception:
            LOGGER.info("Falling back to lexical embedding.", exc_info=True)
            return lexical_vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.client:
            return [lexical_vector(text) for text in texts]
        try:
            result = run_with_timeout(
                lambda: self.client.models.embed_content(model=EMBED_MODEL, contents=texts)
            )
            return [list(embedding.values) for embedding in result.embeddings]
        except Exception:
            LOGGER.info("Falling back to lexical category embeddings.", exc_info=True)
            return [lexical_vector(text) for text in texts]

    def _call_structured(self, contents: str, schema: type[T]) -> T:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = run_with_timeout(
                    lambda: self.client.models.generate_content(
                        model=GEN_MODEL,
                        contents=contents,
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": schema,
                            "temperature": 0.1,
                        },
                    )
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


def run_with_timeout(callable_obj):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=GEMINI_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        future.cancel()
        raise RuntimeError("Gemini call timed out.") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def fallback_extract_slots(text: str, target_slot: str | None = None) -> ExtractedSlots:
    patient_text = "\n".join(
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith("patient:") and ":" in line
    ) or text
    lowered = patient_text.lower()

    if target_slot:
        return fallback_extract_target_slot(patient_text, target_slot)

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

    temporal_phrase = extract_temporal_phrase(patient_text)

    return ExtractedSlots(
        complaint_category=category,
        confidence=0.75 if category != "unclear" else 0.0,
        onset=temporal_phrase if any(word in lowered for word in ["today", "yesterday", "since", "started", "sudden"]) else None,
        duration=temporal_phrase if any(word in lowered for word in ["day", "hour", "week", "since", "yesterday"]) else None,
        severity_0_10=severity,
        associated_symptoms=symptoms,
        age=age,
        mechanism=patient_text if category == "injury" and any(word in lowered for word in ["fall", "cut", "twisted", "hit"]) else None,
    )


def fallback_extract_target_slot(text: str, target_slot: str) -> ExtractedSlots:
    lowered = text.lower()
    values: dict = {}

    if target_slot == "age":
        age = extract_number(text)
        if age is not None:
            values["age"] = age
    elif target_slot == "severity_0_10":
        severity = extract_number(text)
        if severity is not None and 0 <= severity <= 10:
            values["severity_0_10"] = severity
    elif target_slot in {"onset", "duration", "mechanism", "relevant_history"}:
        if text.strip():
            values[target_slot] = text.strip()
    elif target_slot == "associated_symptoms":
        if is_vague_answer(lowered) or "no red flags" in lowered or "no other symptoms" in lowered or lowered.strip() in {"none", "nothing else"}:
            values["associated_symptoms"] = []
        else:
            values["associated_symptoms"] = extract_symptom_phrases(text)

    return ExtractedSlots(**values)


def extract_number(text: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\b", text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 130 else None


def extract_temporal_phrase(text: str) -> str:
    lowered = text.lower()
    for phrase in ["today", "yesterday", "this morning", "this evening", "sudden"]:
        if phrase in lowered:
            return phrase
    since_match = re.search(r"\bsince\s+([^,.]+)", text, flags=re.IGNORECASE)
    if since_match:
        return since_match.group(0).strip()
    duration_match = re.search(
        r"\b(?:\d+\s+)?(?:hour|hours|day|days|week|weeks|month|months)\b",
        text,
        flags=re.IGNORECASE,
    )
    return duration_match.group(0).strip() if duration_match else text.strip()


def extract_symptom_phrases(text: str) -> list[str]:
    lowered = text.lower()
    if is_vague_answer(lowered) or "no red flags" in lowered or "no other symptoms" in lowered:
        return []

    phrases: list[str] = []
    for part in re.split(r"\s*(?:,|;|\band\b)\s*", lowered):
        cleaned = part.strip(" .")
        if not cleaned:
            continue
        cleaned = re.sub(r"^(?:i have|i am having|having|with|and)\s+", "", cleaned)
        cleaned = cleaned.strip(" .")
        if cleaned:
            phrases.append(cleaned)

    for phrase in RED_FLAG_PHRASES:
        if phrase in lowered and phrase not in phrases:
            phrases.append(phrase)
    for phrase, aliases in RED_FLAG_ALIASES.items():
        if any(alias in lowered for alias in aliases) and phrase not in phrases:
            phrases.append(phrase)

    return sorted(set(phrases))


def is_vague_answer(text: str) -> bool:
    lowered = text.lower().strip()
    return any(phrase in lowered for phrase in VAGUE_ANSWER_PHRASES)


def fallback_followup(target_slot: str, red_flag_examples: list[str] | None = None) -> str:
    examples = ", ".join(red_flag_examples or [])
    symptom_question = "Are there any other symptoms?"
    if examples:
        symptom_question = f"Are there any other symptoms, such as {examples}?"
    questions = {
        "age": "How old is the patient?",
        "associated_symptoms": symptom_question,
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


def fallback_uncertain_narrative(
    reported: dict,
    established_by_followup: dict,
    unknowns: list[str],
) -> NoteNarrative:
    return sanitize_narrative(
        NoteNarrative(
            rationale="The assistant could not confidently match the case to a deterministic triage rule. A human triage reviewer must assess it.",
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

import os
import re

from src.schemas import ExtractedSlots


CATEGORIES = {
    "fever": ["fever", "temperature", "chills", "hot"],
    "injury": ["injury", "hurt", "fall", "cut", "bleeding", "sprain", "fracture"],
    "chest_pain": ["chest pain", "chest", "tightness", "pressure"],
    "breathing_difficulty": ["breathing", "breath", "shortness of breath", "wheezing"],
    "abdominal_pain": ["abdomen", "abdominal", "stomach", "belly"],
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


class GeminiClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")

    def extract_slots(self, text: str) -> ExtractedSlots:
        # Initial scaffold fallback. Live Gemini extraction will replace this method next.
        lowered = text.lower()
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
        age_match = re.search(r"\b(?:age|aged|i am|i'm)\s*(\d{1,3})\b", lowered)
        if age_match:
            age = int(age_match.group(1))

        symptoms = [phrase for phrase in RED_FLAG_PHRASES if phrase in lowered]
        if "no red flags" in lowered or "no other symptoms" in lowered:
            symptoms = []

        return ExtractedSlots(
            complaint_category=category,
            confidence=0.7 if category != "unclear" else 0.0,
            onset=text if any(word in lowered for word in ["today", "yesterday", "since", "started"]) else None,
            duration=text if any(word in lowered for word in ["day", "hour", "week", "since"]) else None,
            severity_0_10=severity,
            associated_symptoms=symptoms,
            age=age,
            mechanism=text if category == "injury" else None,
        )

    def generate_followup(self, target_slot: str) -> str:
        questions = {
            "age": "How old is the patient?",
            "associated_symptoms": "Are there any other symptoms or red flags, such as fainting, confusion, severe trouble breathing, unusual bleeding, or pain spreading elsewhere?",
            "duration": "How long has this been going on?",
            "mechanism": "How did the injury happen?",
            "onset": "When did this start?",
            "severity_0_10": "On a scale from 0 to 10, how severe is it right now?",
        }
        return questions.get(target_slot, "Can you share one more detail about the main symptom?")

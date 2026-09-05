import json
from pathlib import Path

import numpy as np

from src.gemini_client import GeminiClient, lexical_vector


CANONICAL = {
    "fever": "Fever, elevated body temperature, chills, feeling hot or feverish",
    "injury": "Physical injury, cut, fall, sprain, fracture, trauma to the body",
    "chest_pain": "Chest pain, tightness, or pressure in the chest area",
    "breathing_difficulty": "Difficulty breathing, shortness of breath, wheezing",
    "abdominal_pain": "Abdominal pain, stomach ache, pain in the belly or gut",
}


class EmbeddingIndex:
    def __init__(self, categories: list[str], vectors: np.ndarray, vectorizer: str, client: GeminiClient):
        self.categories = categories
        self.vectors = vectors
        self.vectorizer = vectorizer
        self.client = client

    @classmethod
    def build_or_load(cls, cache_path: Path, categories: list[str], client: GeminiClient | None = None) -> "EmbeddingIndex":
        client = client or GeminiClient()
        if cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return cls(data["categories"], np.array(data["vectors"], dtype=float), data.get("vectorizer", "gemini"), client)

        vectorizer = "gemini" if client.available else "lexical"
        texts = [CANONICAL[category] for category in categories]
        vectors = client.embed_batch(texts) if client.available else [lexical_vector(text) for text in texts]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {"categories": categories, "vectors": vectors, "vectorizer": vectorizer},
                handle,
                indent=2,
            )
        return cls(categories, np.array(vectors, dtype=float), vectorizer, client)

    def classify(self, text: str, threshold: float = 0.55) -> str | None:
        if self.vectorizer == "gemini" and self.client.available:
            vector = np.array(self.client.embed(text), dtype=float)
        else:
            vector = np.array(lexical_vector(text), dtype=float)
            threshold = 0.1

        if vector.shape[0] != self.vectors.shape[1]:
            return None

        denominators = np.linalg.norm(self.vectors, axis=1) * np.linalg.norm(vector)
        similarities = self.vectors @ vector / (denominators + 1e-9)
        best = int(np.argmax(similarities))
        return self.categories[best] if similarities[best] >= threshold else None

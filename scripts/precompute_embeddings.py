from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.embedding_index import EmbeddingIndex
from src.gemini_client import GeminiClient
from src.rule_engine import RuleEngine


if __name__ == "__main__":
    engine = RuleEngine.load(ROOT / "data" / "triage_rules.json")
    client = GeminiClient()
    index = EmbeddingIndex.build_or_load(ROOT / "data" / "category_embeddings.json", engine.categories(), client)
    print(f"Saved {len(index.categories)} category vectors using {index.vectorizer}.")

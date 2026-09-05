from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.gemini_client import GeminiClient


if __name__ == "__main__":
    client = GeminiClient()
    scenario = "I am 58 with chest pressure, sweating, shortness of breath, and pain radiating to arm."
    print(client.extract_slots(scenario).model_dump_json(indent=2))

TRACK_ID=PS01

# Patient Intake Triage Assistant

Hackathon prototype for walk-in patient intake triage. It accepts free-text patient descriptions, asks focused follow-up questions when required information is missing, evaluates deterministic triage rules, and produces a structured triage note with a cited rule.

This is not a medical device and does not diagnose. In an emergency, call your local emergency number.

## How to run

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8000.

Set `GEMINI_API_KEY` to enable live Gemini extraction and note drafting. Without a key, the app uses deterministic fallback extraction so the skeleton remains demoable during development.

## Structure

- `app.py` starts FastAPI and serves the frontend on port 8000.
- `api/routes.py` exposes `/api/health`, `/api/sessions`, and `/api/sessions/{session_id}/reply`.
- `src/rule_engine.py` contains pure deterministic triage logic.
- `src/gemini_client.py` is the only module intended to call Gemini.
- `data/triage_rules.json` stores the hand-authored rule set.
- `frontend/dist/` contains the no-build-step browser UI.

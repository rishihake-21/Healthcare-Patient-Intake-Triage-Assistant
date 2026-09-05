from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.session_manager import SessionManager
from src.schemas import SessionResponse


router = APIRouter()
manager = SessionManager()


class StartSessionRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)


class ReplyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "track": "PS01"}


@router.post("/sessions", response_model=SessionResponse)
def start_session(payload: StartSessionRequest) -> SessionResponse:
    return manager.create_session(payload.description)


@router.post("/sessions/{session_id}/reply", response_model=SessionResponse)
def reply(session_id: str, payload: ReplyRequest) -> SessionResponse:
    try:
        return manager.reply(session_id, payload.answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

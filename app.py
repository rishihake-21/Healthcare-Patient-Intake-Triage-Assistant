from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as api_router
from src.db import init_db


ROOT = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Patient Intake Triage Assistant")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_db(ROOT / "triage_audit.db")
    app.include_router(api_router, prefix="/api")
    app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="frontend")
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)

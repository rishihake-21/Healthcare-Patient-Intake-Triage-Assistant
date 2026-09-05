import json
import sqlite3
from pathlib import Path
from typing import Any


DB_PATH: Path | None = None


def init_db(path: Path) -> None:
    global DB_PATH
    DB_PATH = path
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                followup_count INTEGER NOT NULL DEFAULT 0,
                unclear_count INTEGER NOT NULL DEFAULT 0,
                pending_slot TEXT,
                slots_json TEXT NOT NULL,
                slot_sources_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _ensure_column(conn, "sessions", "followup_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sessions", "unclear_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sessions", "pending_slot", "TEXT")
        _ensure_column(conn, "sessions", "slot_sources_json", "TEXT NOT NULL DEFAULT '{}'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS triage_notes (
                session_id TEXT PRIMARY KEY,
                note_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        has_old_notes = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'"
        ).fetchone()
        if has_old_notes:
            conn.execute(
                """
                INSERT OR IGNORE INTO triage_notes (session_id, note_json, created_at)
                SELECT session_id, note_json, created_at FROM notes
                """
            )


def upsert_session(
    session_id: str,
    status: str,
    followup_count: int,
    unclear_count: int,
    pending_slot: str | None,
    slots: dict[str, Any],
    slot_sources: dict[str, str],
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, status, followup_count, unclear_count, pending_slot, slots_json, slot_sources_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status=excluded.status,
                followup_count=excluded.followup_count,
                unclear_count=excluded.unclear_count,
                pending_slot=excluded.pending_slot,
                slots_json=excluded.slots_json,
                slot_sources_json=excluded.slot_sources_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                session_id,
                status,
                followup_count,
                unclear_count,
                pending_slot,
                json.dumps(slots),
                json.dumps(slot_sources),
            ),
        )


def append_message(session_id: str, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )


def write_triage_note(session_id: str, note: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO triage_notes (session_id, note_json)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                note_json=excluded.note_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (session_id, json.dumps(note)),
        )


def get_session_record(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if session is None:
            return None
        messages = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        note = conn.execute(
            "SELECT note_json FROM triage_notes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return {
        "session": dict(session),
        "messages": [dict(message) for message in messages],
        "note": json.loads(note["note_json"]) if note else None,
    }


def save_full_session(
    session_id: str,
    status: str,
    followup_count: int,
    unclear_count: int,
    pending_slot: str | None,
    slots: dict[str, Any],
    slot_sources: dict[str, str],
    note: dict[str, Any] | None,
) -> None:
    upsert_session(session_id, status, followup_count, unclear_count, pending_slot, slots, slot_sources)
    if note is not None:
        write_triage_note(session_id, note)


def _connect() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("Database has not been initialized.")
    return sqlite3.connect(DB_PATH)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

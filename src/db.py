import json
import sqlite3
from pathlib import Path


DB_PATH: Path | None = None


def init_db(path: Path) -> None:
    global DB_PATH
    DB_PATH = path
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                slots_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
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
            CREATE TABLE IF NOT EXISTS notes (
                session_id TEXT PRIMARY KEY,
                note_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def save_session(session_id: str, status: str, slots: dict, transcript: list[dict], note: dict | None) -> None:
    if DB_PATH is None:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, status, slots_json)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status=excluded.status,
                slots_json=excluded.slots_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (session_id, status, json.dumps(slots)),
        )
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.executemany(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            [(session_id, item["role"], item["content"]) for item in transcript],
        )
        if note is not None:
            conn.execute(
                """
                INSERT INTO notes (session_id, note_json)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET note_json=excluded.note_json
                """,
                (session_id, json.dumps(note)),
            )

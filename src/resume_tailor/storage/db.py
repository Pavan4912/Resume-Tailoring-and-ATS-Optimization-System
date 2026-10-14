from __future__ import annotations
import sqlite3
from pathlib import Path


def _conn(path: Path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path))
    c.execute("""CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created_at TEXT, company TEXT, title TEXT,
                 folder TEXT, master_sha256 TEXT, score REAL)""")
    return c


def save_session(path, s) -> None:
    with _conn(path) as c:
        c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                  (s.id, s.created_at, s.company, s.title, s.folder, s.master_sha256, s.score))


def list_sessions(path) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("SELECT id,created_at,company,title,folder,master_sha256,score FROM sessions ORDER BY created_at DESC").fetchall()
    return [dict(zip(["id", "created_at", "company", "title", "folder", "master_sha256", "score"], r)) for r in rows]


def delete_session(path, sid: str) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))

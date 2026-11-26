"""Local SQLite storage for research sessions (optional, can be disabled).

Stores only conversation data the operator chose to record. Browser cookies,
tokens, passwords or profile data are never stored here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.events import Event, EventBus, EventType

from .transcript import SessionEvent, SessionMeta, Transcript, TranscriptEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT, started_at TEXT, ended_at TEXT, end_state TEXT,
    host_name TEXT, guest_name TEXT, guest_provider TEXT, transfer_mode TEXT,
    demo INTEGER, experiment TEXT, condition TEXT,
    meta_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL,
    entry_json TEXT NOT NULL,
    PRIMARY KEY (session_id, turn)
);
CREATE TABLE IF NOT EXISTS events (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
"""


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- writes ------------------------------------------------------------------------
    def upsert_meta(self, meta: SessionMeta | dict[str, Any]) -> None:
        m = meta if isinstance(meta, dict) else meta.as_dict()
        with self._lock:
            self._db.execute(
                """INSERT INTO sessions (id, title, started_at, ended_at, end_state, host_name, guest_name,
                       guest_provider, transfer_mode, demo, experiment, condition, meta_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, ended_at=excluded.ended_at,
                       end_state=excluded.end_state, experiment=excluded.experiment,
                       condition=excluded.condition, meta_json=excluded.meta_json""",
                (m["session_id"], m.get("title"), m.get("started_at"), m.get("ended_at"), m.get("end_state"),
                 m.get("host_name"), m.get("guest_name"), m.get("guest_provider"), m.get("transfer_mode"),
                 int(bool(m.get("demo"))), m.get("experiment"), m.get("condition"),
                 json.dumps(m, ensure_ascii=False)))
            self._db.commit()

    def upsert_entry(self, session_id: str, entry: TranscriptEntry | dict[str, Any]) -> None:
        e = entry if isinstance(entry, dict) else entry.as_dict()
        with self._lock:
            self._db.execute(
                "INSERT INTO messages (session_id, turn, entry_json) VALUES (?,?,?) "
                "ON CONFLICT(session_id, turn) DO UPDATE SET entry_json=excluded.entry_json",
                (session_id, int(e["turn"]), json.dumps(e, ensure_ascii=False)))
            self._db.commit()

    def replace_events(self, session_id: str, events: list[SessionEvent | dict[str, Any]]) -> None:
        with self._lock:
            self._db.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            self._db.executemany(
                "INSERT INTO events (session_id, seq, event_json) VALUES (?,?,?)",
                [(session_id, i, json.dumps(ev if isinstance(ev, dict) else ev.as_dict(), ensure_ascii=False))
                 for i, ev in enumerate(events)])
            self._db.commit()

    def save_transcript(self, t: Transcript) -> None:
        self.upsert_meta(t.meta)
        for e in t.entries:
            self.upsert_entry(t.meta.session_id, e)
        self.replace_events(t.meta.session_id, t.events)

    # --- reads -------------------------------------------------------------------------------
    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT s.id, s.title, s.started_at, s.ended_at, s.end_state, s.host_name, s.guest_name,
                          s.guest_provider, s.transfer_mode, s.demo, s.experiment, s.condition,
                          (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id)
                   FROM sessions s ORDER BY s.started_at DESC""").fetchall()
        keys = ("session_id", "title", "started_at", "ended_at", "end_state", "host_name", "guest_name",
                "guest_provider", "transfer_mode", "demo", "experiment", "condition", "message_count")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def load(self, session_id: str) -> Transcript | None:
        """Load a transcript for viewing/export. Loading never resumes or replays a conversation."""
        with self._lock:
            row = self._db.execute("SELECT meta_json FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                return None
            msgs = self._db.execute("SELECT entry_json FROM messages WHERE session_id=? ORDER BY turn",
                                    (session_id,)).fetchall()
            evs = self._db.execute("SELECT event_json FROM events WHERE session_id=? ORDER BY seq",
                                   (session_id,)).fetchall()
        return Transcript(
            meta=SessionMeta.from_dict(json.loads(row[0])),
            entries=[TranscriptEntry.from_dict(json.loads(m[0])) for m in msgs],
            events=[SessionEvent(**json.loads(e[0])) for e in evs])

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._db.commit()

    def delete_all(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM events")
            self._db.execute("DELETE FROM messages")
            self._db.execute("DELETE FROM sessions")
            self._db.commit()
            self._db.execute("VACUUM")


class SessionRecorder:
    """Writes engine events to the store while recording is enabled."""

    def __init__(self, bus: EventBus, store: SessionStore | None) -> None:
        self.store = store
        self.enabled = store is not None
        self._session_id: str | None = None
        bus.subscribe(self._on_event)

    def _on_event(self, ev: Event) -> None:
        if not self.enabled or self.store is None:
            return
        if ev.type == EventType.SESSION_STARTED:
            meta = ev.data["meta"]
            self._session_id = meta["session_id"]
            self.store.upsert_meta(meta)
        elif ev.type in (EventType.ENTRY_ADDED, EventType.ENTRY_UPDATED) and self._session_id:
            self.store.upsert_entry(self._session_id, ev.data["entry"])
        elif ev.type == EventType.SESSION_ENDED and self._session_id:
            self.store.upsert_meta(ev.data["meta"])
            self.store.replace_events(self._session_id, ev.data.get("events", []))

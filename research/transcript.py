"""In-memory transcript model shared by the engine, recorder and exporters."""

from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Provenance:
    OBSERVED = "observed"            # read by the application from the browser/page/clock
    USER_REPORTED = "user_reported"  # typed in by the operator
    UNAVAILABLE = "unavailable"      # not observable and not reported


def fact(value: Any, provenance: str) -> dict[str, Any]:
    if value in (None, ""):
        return {"value": None, "provenance": Provenance.UNAVAILABLE}
    return {"value": value, "provenance": provenance}


class EntryKind:
    INITIAL_PROMPT = "initial_prompt"
    RESPONSE = "response"
    HUMAN = "human_intervention"


@dataclass
class TranscriptEntry:
    turn: int
    round: int
    kind: str
    speaker_role: str            # host | guest | human | operator
    speaker_name: str
    provider: str
    timestamp: str
    original_text: str
    destination: str | None = None            # role the text was / will be sent to
    destination_name: str | None = None
    forwarded_text: str | None = None
    transfer_status: str = "not_forwarded"    # pending | sent | skipped | discarded | not_forwarded | uncertain
    edited: bool = False
    duration_s: float | None = None
    message_hash: str = ""
    message_id: str | None = None
    confidence: str | None = None
    simulated: bool = False
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptEntry":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SessionEvent:
    timestamp: str
    level: str      # info | warning | error
    code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionMeta:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Untitled session"
    research_question: str = ""
    topic: str = ""
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    end_state: str | None = None
    host_name: str = "Cameron"
    host_provider: str = "ChatGPT"
    guest_name: str = ""
    guest_provider: str = ""
    transfer_mode: str = "manual"
    template_mode: str = "attributed"
    transfer_template: str = ""
    initial_prompt: str = ""
    first_speaker: str = "host"
    max_rounds: int = 10
    demo: bool = False
    notes: str = ""
    experiment: str = ""
    condition: str = ""
    #: provenance-tagged facts (model names, memory settings, conversation ids …)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Transcript:
    meta: SessionMeta = field(default_factory=SessionMeta)
    entries: list[TranscriptEntry] = field(default_factory=list)
    events: list[SessionEvent] = field(default_factory=list)

    def add(self, entry: TranscriptEntry) -> TranscriptEntry:
        self.entries.append(entry)
        return entry

    def by_turn(self, turn: int) -> TranscriptEntry | None:
        for e in reversed(self.entries):
            if e.turn == turn:
                return e
        return None

    def responses(self) -> list[TranscriptEntry]:
        return [e for e in self.entries if e.kind == EntryKind.RESPONSE]

    def add_event(self, level: str, code: str, message: str) -> SessionEvent:
        ev = SessionEvent(now_iso(), level, code, message)
        self.events.append(ev)
        return ev

    def snapshot(self) -> "Transcript":
        return copy.deepcopy(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.as_dict(),
            "entries": [e.as_dict() for e in self.entries],
            "events": [e.as_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(
            meta=SessionMeta.from_dict(data.get("meta", {})),
            entries=[TranscriptEntry.from_dict(e) for e in data.get("entries", [])],
            events=[SessionEvent(**e) for e in data.get("events", [])],
        )

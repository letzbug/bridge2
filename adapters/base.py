"""Common provider adapter interface, capability flags and result types."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from app.security import text_hash

from .errors import CapabilityNotSupportedError


@dataclass
class Capabilities:
    send: bool = True
    read_response: bool = True
    detect_generation: bool = False
    stop_generation: bool = False
    completion_indicator: bool = False
    conversation_id: bool = False
    #: automated transfer is supported by this adapter (permission is checked separately)
    automatic_mode: bool = False
    #: every message FROM this participant must be shown to the operator before forwarding
    requires_confirmation: bool = False
    requires_live_validation: bool = True
    simulated: bool = False
    human_in_the_loop: bool = False
    audio: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass
class ConversationSnapshot:
    """Baseline captured before each outgoing message."""

    url: str = ""
    conversation_id: str | None = None
    assistant_count: int = 0
    user_count: int = 0
    last_assistant_id: str | None = None
    last_assistant_hash: str | None = None
    completion_count: int = 0
    generating: bool = False
    input_ready: bool = False
    logged_in: bool | None = None
    captured_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubmissionReceipt:
    status: str                    # "confirmed" | "uncertain"
    signals: list[str] = field(default_factory=list)
    final_text: str = ""
    detail: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass
class ResponseResult:
    text: str
    message_id: str | None = None
    text_hash: str = ""
    #: high: completion confirmed by generation/completion signals
    #: low: only a stable-text period was observed (needs manual confirmation)
    #: user: provided by the human (clipboard / audio transcript)
    #: simulated: demo mode
    confidence: str = "high"
    signals: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    speaker_override: str | None = None   # clipboard import identified another speaker

    def __post_init__(self) -> None:
        if not self.text_hash:
            self.text_hash = text_hash(self.text)


@dataclass
class DiagnosticItem:
    key: str
    label: str
    status: str            # found | missing | not_configured | idle | error | n/a
    selector: str | None = None
    count: int = 0
    detail: str = ""


@dataclass
class DiagnosticReport:
    provider_id: str
    url: str = ""
    items: list[DiagnosticItem] = field(default_factory=list)
    auth: str = "unknown"
    notes: list[str] = field(default_factory=list)
    latest_preview: str = ""
    passed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseProviderAdapter(ABC):
    """Every provider (browser, clipboard, audio, demo) implements this interface."""

    provider_id = "base"
    provider_label = "Base"

    def __init__(self, participant_name: str = "") -> None:
        self.participant_name = participant_name
        self.capabilities = Capabilities()
        self.gate = None  # app.gate.SendGate, bound by the engine
        self.not_ready_reason: str = ""

    # --- gate -----------------------------------------------------------------
    def bind_gate(self, gate) -> None:
        self.gate = gate

    def _check_gate(self) -> None:
        if self.gate is not None:
            self.gate.check()

    # --- required interface -------------------------------------------------------
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def is_ready(self) -> bool: ...

    @abstractmethod
    async def get_conversation_state(self) -> ConversationSnapshot: ...

    @abstractmethod
    async def send_message(self, text: str) -> SubmissionReceipt: ...

    @abstractmethod
    async def wait_for_response(self, timeout: float) -> ResponseResult: ...

    @abstractmethod
    async def get_latest_response(self) -> str | None: ...

    async def stop_generation(self) -> bool:
        raise CapabilityNotSupportedError(f"{self.provider_label}: stopping generation is not supported")

    async def disconnect(self) -> None:
        return None

    async def diagnose(self) -> DiagnosticReport:
        return DiagnosticReport(self.provider_id, notes=["This adapter has no browser diagnostics."], passed=True)

    async def check_auth(self) -> str:
        """'logged_in' | 'login_required' | 'unknown'"""
        return "unknown"

    def describe(self) -> str:
        return f"{self.participant_name} ({self.provider_label})"

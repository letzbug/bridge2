"""Provider-independent clipboard adapter (human-in-the-loop).

Works with ANY chat website and needs no browser automation at all, so it keeps
working when every automated adapter fails or when a provider's terms do not
allow automated interaction.

    send_message      -> the operator copies the prepared text, pastes it into the
                         participant's window, sends it there and confirms
    wait_for_response -> the operator copies the reply in the browser and imports it
"""

from __future__ import annotations

import asyncio

from app.clipboard_workflow import ClipboardCoordinator
from app.security import clean_extracted_text

from .base import BaseProviderAdapter, ConversationSnapshot, ResponseResult, SubmissionReceipt
from .errors import AdapterError, ResponseTimeoutError


class ClipboardAdapter(BaseProviderAdapter):
    provider_id = "clipboard"

    def __init__(self, role: str, participant_name: str, provider_label: str,
                 coordinator: ClipboardCoordinator, min_wait_seconds: float = 1800.0) -> None:
        super().__init__(participant_name)
        self.role = role
        self.provider_label = f"{provider_label} · clipboard"
        self.coordinator = coordinator
        self.min_wait_seconds = min_wait_seconds
        c = self.capabilities
        c.human_in_the_loop = True
        c.automatic_mode = False
        c.requires_live_validation = False
        c.detect_generation = False
        self._last_import: str | None = None
        self._imports = 0

    async def connect(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return True

    async def get_conversation_state(self) -> ConversationSnapshot:
        return ConversationSnapshot(url="", assistant_count=self._imports, input_ready=True)

    async def send_message(self, text: str) -> SubmissionReceipt:
        self._check_gate()
        final = await self.coordinator.request("paste", self.role, self.participant_name, text)
        self._check_gate()
        if not isinstance(final, str) or not final.strip():
            raise AdapterError("Clipboard transfer was not confirmed")
        return SubmissionReceipt("confirmed", ["operator_confirmed_paste"], final_text=final)

    async def wait_for_response(self, timeout: float) -> ResponseResult:
        wait = max(timeout, self.min_wait_seconds)
        while True:
            try:
                value = await asyncio.wait_for(
                    self.coordinator.request("import", self.role, self.participant_name), wait)
            except asyncio.TimeoutError as exc:
                raise ResponseTimeoutError(
                    f"No reply from {self.participant_name} was imported within {wait / 60:.0f} minutes.") from exc
            if isinstance(value, dict):
                text, speaker = value.get("text", ""), value.get("speaker")
            else:
                text, speaker = str(value or ""), None
            text = clean_extracted_text(text)
            if text:
                break
        self._last_import = text
        self._imports += 1
        override = speaker if speaker in ("host", "guest") and speaker != self.role else None
        return ResponseResult(text, confidence="user", flags=["clipboard_import"], speaker_override=override)

    async def get_latest_response(self) -> str | None:
        return self._last_import

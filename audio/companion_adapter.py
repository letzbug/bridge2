"""Animated Companion adapter (EXPERIMENTAL – validate with a real companion).

Outgoing: text is spoken with local TTS to the selected output device (e.g. a
virtual cable feeding the companion's microphone input).
Incoming: the companion's voice is captured from the selected input, segmented
by voice activity and transcribed locally. Every transcript must be confirmed by
the operator before it is forwarded (requires_confirmation).
"""

from __future__ import annotations

from adapters.base import BaseProviderAdapter, ConversationSnapshot, ResponseResult, SubmissionReceipt

from .audio_manager import AudioManager


class AudioCompanionAdapter(BaseProviderAdapter):
    provider_id = "companion"
    provider_label = "Animated Companion (audio)"

    def __init__(self, role: str, participant_name: str, manager: AudioManager) -> None:
        super().__init__(participant_name)
        self.role = role
        self.manager = manager
        c = self.capabilities
        c.audio = True
        c.requires_confirmation = True
        c.automatic_mode = False
        c.detect_generation = False
        c.requires_live_validation = True
        self._last: str | None = None
        self._count = 0

    async def connect(self) -> None:
        return None

    async def is_ready(self) -> bool:
        if not self.manager.authorized:
            self.not_ready_reason = "audio capture not armed – click 'Arm microphone' in the guest panel"
            return False
        return True

    async def get_conversation_state(self) -> ConversationSnapshot:
        speaking = self.manager.state in (AudioManager.SPEAKING,)
        return ConversationSnapshot(url="audio://companion", assistant_count=self._count, generating=speaking,
                                    input_ready=True)

    async def send_message(self, text: str) -> SubmissionReceipt:
        self._check_gate()
        duration = await self.manager.speak(text, gate_check=self._check_gate)
        return SubmissionReceipt("confirmed", ["spoken_via_tts"], final_text=text, detail=f"{duration:.1f}s audio")

    async def wait_for_response(self, timeout: float) -> ResponseResult:
        text, lang = await self.manager.listen(timeout)
        self._last = text
        self._count += 1
        return ResponseResult(text, confidence="transcript",
                              flags=["audio_transcript"] + ([f"language:{lang}"] if lang else []))

    async def get_latest_response(self) -> str | None:
        return self._last

    async def stop_generation(self) -> bool:
        self.manager.stop_manual_recording()
        return True

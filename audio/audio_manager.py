"""Half-duplex audio controller for the Animated Companion mode (EXPERIMENTAL).

Rules enforced here:
* Recording requires explicit operator authorisation (arm button) – an AI message
  can never activate capture.
* Half duplex: while Cameron's speech is playing, and for a guard interval after
  it, incoming audio is ignored (unless isolated routing was explicitly validated
  in the setup wizard).
* Feedback prevention: a transcript that mostly repeats Cameron's last spoken text
  is discarded as echo.
* Only the input device the operator selected is captured – never the whole
  desktop audio by default.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol

from adapters.errors import AdapterError, DependencyMissingError, ResponseTimeoutError
from app.events import EventBus, EventType
from app.loop_detection import containment

from .voice_activity import UtteranceSegmenter, VadConfig

log = logging.getLogger(__name__)


@dataclass
class AudioSettings:
    tts_engine: str = "sapi"            # sapi | piper
    voice: str = ""
    speed: float = 1.0
    language: str = "auto"              # auto | de | en | fr
    output_device: str = ""             # device NAME (indices change)
    input_device: str = ""
    piper_executable: str = ""
    piper_model: str = ""
    whisper_model: str = "base"
    guard_ms: int = 700
    manual_recording: bool = False
    isolated_routing_validated: bool = False
    echo_threshold: float = 0.6
    vad: VadConfig = field(default_factory=VadConfig)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AudioSettings":
        d = dict(d or {})
        vad = VadConfig(**{k: v for k, v in (d.pop("vad", None) or {}).items() if k in VadConfig.__dataclass_fields__})
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(vad=vad, **known)


class AudioSource(Protocol):
    rate: int

    def frames(self) -> AsyncIterator[tuple[float, Any]]: ...
    async def close(self) -> None: ...


class SoundDeviceSource:
    """Captures ONE selected input device in ~30 ms frames."""

    def __init__(self, device_name: str, frame_ms: int = 30) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001
            raise DependencyMissingError("Audio capture needs install_audio.bat (sounddevice, numpy).") from exc
        from .device_manager import find
        dev = find(device_name, "input")
        if dev is None:
            raise AdapterError(f"Input device '{device_name}' not found – select it in the audio setup wizard.")
        self._np, self._sd = np, sd
        self.rate = int(dev.default_rate) or 48000
        self._block = max(1, int(self.rate * frame_ms / 1000))
        self._index = dev.index
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stream = None

    async def frames(self) -> AsyncIterator[tuple[float, Any]]:
        loop = asyncio.get_running_loop()
        np = self._np

        def callback(indata, _frames, _time, _status):
            loop.call_soon_threadsafe(self._queue.put_nowait, indata[:, 0].copy())

        self._stream = self._sd.InputStream(device=self._index, channels=1, samplerate=self.rate,
                                            blocksize=self._block, dtype="float32", callback=callback)
        self._stream.start()
        while True:
            chunk = await self._queue.get()
            rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
            yield (20.0 * math.log10(rms) if rms > 1e-6 else -120.0), chunk

    async def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class AudioManager:
    IDLE, SPEAKING, GUARD, LISTENING, TRANSCRIBING = "idle", "speaking", "guard", "listening", "transcribing"

    def __init__(self, bus: EventBus, settings: AudioSettings,
                 synthesize: Callable[[str], Any] | None = None,
                 play: Callable[[Any], float] | None = None,
                 transcribe: Callable[[list, int], Any] | None = None,
                 source_factory: Callable[[], AudioSource] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.bus = bus
        self.settings = settings
        self._synthesize = synthesize or self._default_synthesize
        self._play = play or self._default_play
        self._transcribe = transcribe or self._default_transcribe
        self._source_factory = source_factory or (lambda: SoundDeviceSource(settings.input_device,
                                                                            settings.vad.frame_ms))
        self.clock = clock
        self.state = self.IDLE
        self.authorized = False
        self.last_spoken = ""
        self._speaking_until = 0.0
        self._manual_stop: asyncio.Event | None = None   # created inside the engine loop when listening
        self._stt = None
        self.last_level_db = -120.0

    # --- operator-only controls -------------------------------------------------------
    def authorize(self, allowed: bool) -> None:
        """Called only from a GUI action by the operator."""
        self.authorized = bool(allowed)
        self._emit("armed" if allowed else "disarmed")

    def stop_manual_recording(self) -> None:
        if self._manual_stop is not None:
            self._manual_stop.set()

    # --- helpers -----------------------------------------------------------------------------
    def _emit(self, status: str, **detail: Any) -> None:
        self.bus.emit(EventType.AUDIO, status=status, state=self.state, **detail)

    def _set(self, state: str) -> None:
        self.state = state
        self._emit("state")

    def _default_synthesize(self, text: str):
        from .tts_engine import PiperTTS, WindowsSapiTTS
        s = self.settings
        engine = PiperTTS(s.piper_executable, s.piper_model) if s.tts_engine == "piper" else WindowsSapiTTS()
        return engine.synthesize(text, s.voice, s.speed)

    def _default_play(self, wav) -> float:
        from .device_manager import find
        from .tts_engine import play_wav
        dev = find(self.settings.output_device, "output")
        return play_wav(wav, dev.index if dev else None)

    def _default_transcribe(self, chunks: list, rate: int):
        import numpy as np

        from .stt_engine import WhisperSTT, resample_to_16k
        if self._stt is None or self._stt.model_size != self.settings.whisper_model:
            self._stt = WhisperSTT(self.settings.whisper_model)
        audio = resample_to_16k(np.concatenate(chunks), rate)
        return self._stt.transcribe(audio, self.settings.language)

    # --- speaking ----------------------------------------------------------------------------
    async def speak(self, text: str, gate_check: Callable[[], None] | None = None) -> float:
        self._set(self.SPEAKING)
        try:
            wav = await asyncio.to_thread(self._synthesize, text)
            if gate_check:
                gate_check()      # emergency stop is checked right before playback
            self._speaking_until = float("inf")
            duration = await asyncio.to_thread(self._play, wav)
            self.last_spoken = text
            return duration
        finally:
            self._speaking_until = self.clock() + self.settings.guard_ms / 1000.0
            self._set(self.GUARD)
            asyncio.get_running_loop().call_later(self.settings.guard_ms / 1000.0, self._guard_over)

    def _guard_over(self) -> None:
        if self.state == self.GUARD:
            self._set(self.IDLE)

    def _speech_active(self) -> bool:
        return self.clock() < self._speaking_until

    # --- listening ------------------------------------------------------------------------------
    async def listen(self, timeout: float) -> tuple[str, str]:
        """Capture one companion utterance and return (transcript, language)."""
        if not self.authorized:
            raise AdapterError("Audio capture is not authorised. Arm the microphone in the companion panel "
                               "(only the operator can do this).")
        deadline = self.clock() + timeout
        while self._speech_active() and not self.settings.isolated_routing_validated:
            if self.clock() > deadline:
                raise ResponseTimeoutError("Timed out while Cameron's speech was still playing.")
            await asyncio.sleep(0.05)
        self._manual_stop = asyncio.Event()
        while True:
            chunks, rate = await self._capture(deadline)
            self._set(self.TRANSCRIBING)
            result = await asyncio.to_thread(self._transcribe, chunks, rate)
            text = (getattr(result, "text", None) if result is not None else "") or ""
            lang = getattr(result, "language", "") or ""
            if not text.strip():
                self._emit("discarded", reason="empty transcript")
                continue
            if self.last_spoken and containment(text, self.last_spoken) >= self.settings.echo_threshold:
                self._emit("discarded", reason="echo of Cameron's own speech (feedback prevention)")
                log.info("discarded transcript as echo")
                continue
            self._set(self.IDLE)
            return text.strip(), lang

    async def _capture(self, deadline: float) -> tuple[list, int]:
        cfg = self.settings.vad
        seg = UtteranceSegmenter(cfg)
        pre_roll: collections.deque = collections.deque(maxlen=max(1, 300 // cfg.frame_ms))
        chunks: list = []
        source = self._source_factory()
        self._set(self.LISTENING)
        self._emit("recording", device=self.settings.input_device)
        last_meter = 0.0
        try:
            agen = source.frames()
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise ResponseTimeoutError("No complete companion utterance was captured in time.")
                try:
                    level, chunk = await asyncio.wait_for(agen.__anext__(), timeout=min(remaining, 1.0))
                except asyncio.TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                self.last_level_db = level
                now = self.clock()
                if now - last_meter > 0.1:
                    last_meter = now
                    self._emit("level", level_db=round(level, 1))
                if self._speech_active() and not self.settings.isolated_routing_validated:
                    continue  # half duplex: never capture while Cameron is speaking
                if self.settings.manual_recording:
                    chunks.append(chunk)
                    if self._manual_stop is not None and self._manual_stop.is_set():
                        break
                    continue
                status = seg.feed(level)
                if seg.started:
                    if not chunks:
                        chunks.extend(pre_roll)
                    chunks.append(chunk)
                else:
                    pre_roll.append(chunk)
                if status in ("complete", "too_long"):
                    break
        finally:
            await source.close()
            self._emit("recording_stopped")
        if not chunks:
            raise ResponseTimeoutError("No speech was detected on the selected input.")
        return chunks, getattr(source, "rate", 16000)

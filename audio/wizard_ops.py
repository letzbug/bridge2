"""Blocking audio test operations for the setup wizard (run in a worker thread)."""

from __future__ import annotations

import math
import threading
from typing import Any

from adapters.errors import AdapterError, DependencyMissingError

from .audio_manager import AudioSettings
from .device_manager import audio_available, find


def _deps():
    ok, msg = audio_available()
    if not ok:
        raise DependencyMissingError(msg)
    import numpy as np
    import sounddevice as sd
    return np, sd


def _db(x) -> float:
    import numpy as np
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return 20 * math.log10(rms) if rms > 1e-6 else -120.0


def record(device_name: str, seconds: float) -> tuple[Any, int]:
    np, sd = _deps()
    dev = find(device_name, "input")
    if dev is None:
        raise AdapterError("Select an input device first.")
    rate = int(dev.default_rate) or 48000
    data = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="float32", device=dev.index)
    sd.wait()
    return data[:, 0], rate


def play(samples, rate: int, device_name: str) -> None:
    _, sd = _deps()
    dev = find(device_name, "output")
    sd.play(samples, rate, device=dev.index if dev else None)
    sd.wait()


def mic_test(input_name: str, output_name: str, seconds: float = 3.0) -> dict[str, float]:
    samples, rate = record(input_name, seconds)
    play(samples, rate, output_name)
    return {"peak_db": round(_db(samples), 1)}


def companion_input_test(input_name: str, seconds: float = 5.0) -> dict[str, float]:
    np, _ = _deps()
    samples, rate = record(input_name, seconds)
    frame = max(1, int(rate * 0.03))
    levels = [_db(samples[i:i + frame]) for i in range(0, len(samples), frame)]
    loud = [lv for lv in levels if lv > -42]
    return {"average_db": round(_db(samples), 1), "max_frame_db": round(max(levels) if levels else -120, 1),
            "speech_ratio": round(len(loud) / max(1, len(levels)), 2)}


def tts_test(settings: AudioSettings, phrase: str) -> float:
    from .tts_engine import PiperTTS, WindowsSapiTTS, play_wav
    engine = PiperTTS(settings.piper_executable, settings.piper_model) if settings.tts_engine == "piper" \
        else WindowsSapiTTS()
    wav = engine.synthesize(phrase, settings.voice, settings.speed)
    dev = find(settings.output_device, "output")
    return play_wav(wav, dev.index if dev else None)


def stt_test(settings: AudioSettings, seconds: float = 5.0) -> dict[str, Any]:
    from .stt_engine import WhisperSTT, resample_to_16k
    samples, rate = record(settings.input_device, seconds)
    stt = WhisperSTT(settings.whisper_model)
    t = stt.transcribe(resample_to_16k(samples, rate), settings.language)
    return {"text": t.text, "language": t.language, "probability": round(t.probability, 2)}


def download_model(model_size: str) -> None:
    from .stt_engine import WhisperSTT
    WhisperSTT(model_size).load(allow_download=True)


def routing_test(output_name: str, input_name: str) -> dict[str, Any]:
    """Plays a 1 kHz tone on Cameron's output and listens on the companion input.

    If the tone is clearly audible on the input, outgoing speech would be picked up
    again (feedback path) and strict half-duplex must stay on.
    """
    np, sd = _deps()
    out_dev, in_dev = find(output_name, "output"), find(input_name, "input")
    if out_dev is None or in_dev is None:
        raise AdapterError("Select both the output and the companion input device first.")
    rate = int(in_dev.default_rate) or 48000
    baseline = sd.rec(int(1.0 * rate), samplerate=rate, channels=1, dtype="float32", device=in_dev.index)
    sd.wait()
    out_rate = int(out_dev.default_rate) or 48000
    t = np.arange(int(1.5 * out_rate)) / out_rate
    tone = (0.25 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32).reshape(-1, 1)
    # separate output stream so playback and recording run at the same time
    out_stream = sd.OutputStream(samplerate=out_rate, channels=1, dtype="float32", device=out_dev.index)
    out_stream.start()
    try:
        rec = sd.rec(int(1.5 * rate), samplerate=rate, channels=1, dtype="float32", device=in_dev.index)
        out_stream.write(tone)
        sd.wait()
    finally:
        out_stream.stop()
        out_stream.close()
    base_db, tone_db = _db(baseline[:, 0]), _db(rec[:, 0])
    leaked = tone_db > base_db + 10
    return {"baseline_db": round(base_db, 1), "during_tone_db": round(tone_db, 1), "leaked": leaked}


class LevelMeter:
    """Live input level for the wizard meter (only while the operator keeps it running)."""

    def __init__(self) -> None:
        self.level_db = -120.0
        self._stream = None
        self._lock = threading.Lock()

    def start(self, device_name: str) -> None:
        np, sd = _deps()
        dev = find(device_name, "input")
        if dev is None:
            raise AdapterError("Select an input device first.")

        def cb(indata, _f, _t, _s):
            with self._lock:
                self.level_db = _db(indata[:, 0])

        self.stop()
        self._stream = sd.InputStream(device=dev.index, channels=1, samplerate=int(dev.default_rate) or 48000,
                                      dtype="float32", callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level_db = -120.0

    @property
    def running(self) -> bool:
        return self._stream is not None

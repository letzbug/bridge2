"""Text-to-speech engines.

* WindowsSapiTTS – built-in Windows speech synthesis (System.Speech via PowerShell).
  No Python dependency. The text is passed on STDIN, never interpolated into the
  PowerShell script, so message content cannot inject commands.
* PiperTTS – optional local neural TTS (piper executable + .onnx voice) configured by path.

Playback goes to a selectable output device via sounddevice when installed
(needed for routing into a virtual audio cable); otherwise the default device
is used via winsound (Windows only).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from adapters.errors import AdapterError, DependencyMissingError

_PS_SPEAK = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:EL_VOICE) { $s.SelectVoice($env:EL_VOICE) }
$s.Rate = [int]$env:EL_RATE
$s.SetOutputToWaveFile($env:EL_OUT)
$text = [Console]::In.ReadToEnd()
$s.Speak($text)
$s.Dispose()
"""

_PS_VOICES = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($v in $s.GetInstalledVoices()) { if ($v.Enabled) { $v.VoiceInfo.Name + '|' + $v.VoiceInfo.Culture.Name } }
"""

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Voice:
    name: str
    language: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.language})"


def _powershell(script: str, stdin: str | None = None, env: dict[str, str] | None = None, timeout: float = 120) -> str:
    if sys.platform != "win32":
        raise DependencyMissingError("Windows speech synthesis is only available on Windows.")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            input=(stdin or "").encode("utf-8"), capture_output=True, timeout=timeout,
            env={**os.environ, **(env or {})}, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError(f"Windows speech synthesis failed: {exc}") from exc
    if proc.returncode != 0:
        raise AdapterError("Windows speech synthesis failed: " + proc.stderr.decode("utf-8", "replace")[:300])
    return proc.stdout.decode("utf-8", "replace")


class WindowsSapiTTS:
    name = "Windows speech (SAPI)"

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def voices(self) -> list[Voice]:
        out = []
        for line in _powershell(_PS_VOICES, timeout=30).splitlines():
            if "|" in line:
                name, lang = line.strip().split("|", 1)
                out.append(Voice(name, lang))
        return out

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> Path:
        rate = max(-10, min(10, round((speed - 1.0) * 10)))
        fd, path = tempfile.mkstemp(prefix="el_tts_", suffix=".wav")
        os.close(fd)
        _powershell(_PS_SPEAK, stdin=text, env={"EL_VOICE": voice or "", "EL_RATE": str(rate), "EL_OUT": path})
        return Path(path)


class PiperTTS:
    name = "Piper (local, optional)"

    def __init__(self, executable: str = "", model: str = "") -> None:
        self.executable = executable
        self.model = model

    def available(self) -> bool:
        return bool(self.executable and Path(self.executable).is_file() and self.model and Path(self.model).is_file())

    def voices(self) -> list[Voice]:
        return [Voice(Path(self.model).stem, "model")] if self.available() else []

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> Path:
        if not self.available():
            raise DependencyMissingError("Piper is not configured (set the executable and voice model paths).")
        fd, path = tempfile.mkstemp(prefix="el_piper_", suffix=".wav")
        os.close(fd)
        length_scale = f"{1.0 / max(0.25, speed):.2f}"
        try:
            proc = subprocess.run([self.executable, "--model", self.model, "--output_file", path,
                                   "--length_scale", length_scale],
                                  input=text.encode("utf-8"), capture_output=True, timeout=180,
                                  creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdapterError(f"Piper failed: {exc}") from exc
        if proc.returncode != 0:
            raise AdapterError("Piper failed: " + proc.stderr.decode("utf-8", "replace")[:300])
        return Path(path)


def read_wav(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    data = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if width == 1:
        data = (data - 128.0) / 128.0
    else:
        data /= float(2 ** (8 * width - 1))
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate


def play_wav(path: Path, output_device: int | None = None) -> float:
    """Blocking playback. Returns the duration in seconds."""
    try:
        import sounddevice as sd
        data, rate = read_wav(path)
        sd.play(data, rate, device=output_device)
        sd.wait()
        return len(data) / float(rate)
    except ImportError:
        pass
    if sys.platform == "win32":
        import winsound
        with wave.open(str(path), "rb") as w:
            duration = w.getnframes() / float(w.getframerate())
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return duration
    raise DependencyMissingError("Audio playback needs the optional audio dependencies (install_audio.bat).")

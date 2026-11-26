"""Audio device enumeration (optional dependency: sounddevice)."""

from __future__ import annotations

from dataclasses import dataclass


def audio_available() -> tuple[bool, str]:
    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
        return True, ""
    except Exception as exc:  # ImportError or PortAudio OSError
        return False, (f"Audio dependencies are not installed or unavailable ({type(exc).__name__}). "
                       "Run install_audio.bat. Text mode keeps working without them.")


@dataclass
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_rate: float

    @property
    def label(self) -> str:
        return f"{self.name}  [{self.hostapi}]"


def list_devices() -> list[AudioDevice]:
    ok, _ = audio_available()
    if not ok:
        return []
    import sounddevice as sd
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append(AudioDevice(i, d["name"], apis[d["hostapi"]]["name"], int(d["max_input_channels"]),
                               int(d["max_output_channels"]), float(d["default_samplerate"])))
    return out


def inputs() -> list[AudioDevice]:
    return [d for d in list_devices() if d.max_input > 0]


def outputs() -> list[AudioDevice]:
    return [d for d in list_devices() if d.max_output > 0]


def find(name: str, kind: str) -> AudioDevice | None:
    """Find a device by its exact name (names are stored in settings, indices change)."""
    if not name:
        return None
    for d in (inputs() if kind == "input" else outputs()):
        if d.name == name:
            return d
    return None


VIRTUAL_CABLE_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual")


def looks_virtual(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in VIRTUAL_CABLE_HINTS)

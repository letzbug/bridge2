"""Local speech-to-text with faster-whisper (optional).

Models are downloaded only after explicit confirmation (wizard button or
`python -m audio.stt_engine --download base`). Approximate sizes:

    tiny ~75 MB · base ~145 MB · small ~465 MB · medium ~1.5 GB · large-v3 ~3 GB

Transcription runs locally on the CPU (int8). Supported languages for this
application: German (de), English (en), French (fr) or automatic detection.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from adapters.errors import DependencyMissingError
from app import paths

MODEL_SIZES = {"tiny": "~75 MB", "base": "~145 MB", "small": "~465 MB", "medium": "~1.5 GB", "large-v3": "~3 GB"}
LANGUAGES = {"auto": "Automatic detection", "de": "German", "en": "English", "fr": "French"}

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


@dataclass
class Transcription:
    text: str
    language: str
    probability: float
    duration_s: float


def stt_available() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"faster-whisper is not installed ({type(exc).__name__}). Run install_audio.bat."


class WhisperSTT:
    def __init__(self, model_size: str = "base", download_root: Path | None = None) -> None:
        self.model_size = model_size if model_size in MODEL_SIZES else "base"
        self.download_root = download_root or paths.audio_models_dir()
        self._model = None

    def is_downloaded(self) -> bool:
        root = self.download_root
        return root.exists() and any(self.model_size in p.name for p in root.glob("models--*"))

    def load(self, allow_download: bool = False) -> None:
        ok, msg = stt_available()
        if not ok:
            raise DependencyMissingError(msg)
        if not allow_download and not self.is_downloaded():
            raise DependencyMissingError(
                f"The Whisper model '{self.model_size}' ({MODEL_SIZES[self.model_size]}) is not downloaded yet. "
                "Download it from the audio setup wizard.")
        from faster_whisper import WhisperModel
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8",
                                   download_root=str(self.download_root), local_files_only=not allow_download)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_16k, language: str = "auto") -> Transcription:
        """audio_16k: float32 numpy array, mono, 16 kHz."""
        if self._model is None:
            self.load(allow_download=False)
        lang = None if language in ("", "auto") else language
        segments, info = self._model.transcribe(audio_16k, language=lang, vad_filter=False, beam_size=5)
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcription(text, info.language, float(info.language_probability), float(info.duration))


def resample_to_16k(samples, rate: int):
    import numpy as np
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float32)
    if rate == 16000:
        return samples
    n = int(round(len(samples) * 16000 / rate))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a faster-whisper model for local transcription")
    parser.add_argument("--download", choices=list(MODEL_SIZES), required=True)
    args = parser.parse_args(argv)
    print(f"Downloading Whisper model '{args.download}' ({MODEL_SIZES[args.download]}) to {paths.audio_models_dir()}")
    stt = WhisperSTT(args.download)
    stt.load(allow_download=True)
    print("Model ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

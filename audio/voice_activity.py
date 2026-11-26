"""Energy-based voice activity detection and utterance segmentation (no dependencies).

Works on per-frame levels in dBFS so the logic is testable without audio
hardware. The capture code computes the level of each ~30 ms frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def rms_dbfs(samples: Sequence[float]) -> float:
    """Level of float samples in [-1, 1] as dBFS (silence -> -120)."""
    n = len(samples)
    if n == 0:
        return -120.0
    acc = 0.0
    for s in samples:
        acc += float(s) * float(s)
    rms = math.sqrt(acc / n)
    return 20.0 * math.log10(rms) if rms > 1e-6 else -120.0


@dataclass
class VadConfig:
    threshold_db: float = -42.0      # absolute speech threshold
    adaptive_margin_db: float = 12.0 # speech must also exceed the noise floor by this margin
    min_speech_ms: int = 250         # ignore clicks shorter than this
    end_silence_ms: int = 1200       # silence that ends an utterance
    max_utterance_s: float = 120.0
    frame_ms: int = 30


class UtteranceSegmenter:
    """Feed frame levels; reports when an utterance (speech followed by silence) is complete."""

    def __init__(self, cfg: VadConfig | None = None) -> None:
        self.cfg = cfg or VadConfig()
        self.noise_floor = -70.0
        self.reset()

    def reset(self) -> None:
        self.speech_ms = 0
        self.silence_ms = 0
        self.total_ms = 0
        self.in_speech = False
        self.started = False

    def is_speech(self, level_db: float) -> bool:
        return level_db >= self.cfg.threshold_db and level_db >= self.noise_floor + self.cfg.adaptive_margin_db

    def feed(self, level_db: float) -> str:
        """Returns 'silence' | 'speech' | 'complete' | 'too_long'."""
        f = self.cfg.frame_ms
        if self.started:
            self.total_ms += f
        speech = self.is_speech(level_db)
        if not speech and not self.started:
            # track the background level while nobody speaks
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * level_db
        if speech:
            self.speech_ms += f
            self.silence_ms = 0
            if self.speech_ms >= self.cfg.min_speech_ms:
                self.started = True
                self.in_speech = True
            return "speech" if self.started else "silence"
        if not self.started:
            self.speech_ms = 0
            return "silence"
        self.silence_ms += f
        self.in_speech = False
        if self.total_ms >= self.cfg.max_utterance_s * 1000:
            return "too_long"
        if self.silence_ms >= self.cfg.end_silence_ms:
            return "complete"
        return "silence"

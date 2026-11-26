"""Duplicate, near-duplicate and echo detection.

Deterministic and dependency-free: exact matches use a hash of normalised text,
near matches use the Jaccard similarity of word 3-gram shingles.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(_WORD_RE.findall(text))


def norm_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _shingles(words: list[str], n: int) -> set[tuple[str, ...]]:
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a: str, b: str, n: int = 3, max_words: int = 4000) -> float:
    wa = normalize(a).split()[:max_words]
    wb = normalize(b).split()[:max_words]
    if not wa or not wb:
        return 0.0
    sa, sb = _shingles(wa, n), _shingles(wb, n)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def containment(a: str, b: str, n: int = 3, max_words: int = 4000) -> float:
    """Share of a's shingles that also occur in b (1.0 = a is fully contained in b)."""
    wa = normalize(a).split()[:max_words]
    wb = normalize(b).split()[:max_words]
    if not wa or not wb:
        return 0.0
    sa, sb = _shingles(wa, n), _shingles(wb, n)
    return len(sa & sb) / len(sa) if sa else 0.0


@dataclass(frozen=True)
class HistoryItem:
    turn: int
    role: str
    text: str


@dataclass(frozen=True)
class LoopVerdict:
    kind: str = "none"            # none | exact_duplicate | near_duplicate | echo
    similarity: float = 0.0
    matched_turn: int | None = None
    matched_role: str | None = None

    @property
    def triggered(self) -> bool:
        return self.kind != "none"

    def describe(self) -> str:
        if self.kind == "exact_duplicate":
            return f"Response is identical to turn {self.matched_turn} ({self.matched_role})."
        if self.kind == "near_duplicate":
            return (f"Response is nearly identical ({self.similarity:.0%}) to turn "
                    f"{self.matched_turn} ({self.matched_role}).")
        if self.kind == "echo":
            return (f"Response closely repeats the message it just received ({self.similarity:.0%}). "
                    "The participant may be echoing, or the adapter may have extracted the wrong element.")
        return "No repetition detected."


class LoopDetector:
    def __init__(self, near_threshold: float = 0.85, echo_threshold: float = 0.90,
                 same_speaker_window: int = 4, other_speaker_window: int = 2, min_words: int = 6) -> None:
        self.near_threshold = near_threshold
        self.echo_threshold = echo_threshold
        self.same_window = same_speaker_window
        self.other_window = other_speaker_window
        self.min_words = min_words

    def check(self, role: str, text: str, history: Iterable[HistoryItem],
              received_text: str | None = None) -> LoopVerdict:
        history = list(history)
        h = norm_hash(text)
        if normalize(text):
            for item in reversed(history):
                if norm_hash(item.text) == h:
                    return LoopVerdict("exact_duplicate", 1.0, item.turn, item.role)

        words = len(normalize(text).split())
        if words < self.min_words:
            return LoopVerdict()

        if received_text:
            sim = containment(text, received_text)
            if sim >= self.echo_threshold:
                return LoopVerdict("echo", sim, None, None)

        same = [i for i in history if i.role == role][-self.same_window:]
        other = [i for i in history if i.role != role][-self.other_window:]
        best: LoopVerdict = LoopVerdict()
        for item in same + other:
            sim = similarity(text, item.text)
            if sim >= self.near_threshold and sim > best.similarity:
                best = LoopVerdict("near_duplicate", sim, item.turn, item.role)
        return best

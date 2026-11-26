"""Untrusted-text policy.

Every AI response is untrusted data. The application only ever:

* stores it,
* displays it (escaped),
* exports it (escaped / neutralised per format),
* passes it as a *value* to a browser input or to TTS.

It is never parsed for commands, never evaluated, never interpolated into code
(JavaScript is always called with the text as an argument, never by string
concatenation), and it can never change settings, providers, round limits,
audio capture or the emergency stop. Those controls are only reachable from
GUI actions performed by the human operator.
"""

from __future__ import annotations

import hashlib
import html
import re

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_extracted_text(text: str | None) -> str:
    """Minimal, lossless-as-possible clean-up of text read from a page.

    Only normalises line endings, removes C0 control characters (except tab and
    newline) and strips leading/trailing blank space. Content is never
    summarised, rewritten or truncated.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL_RE.sub("", text)
    text = text.replace(" ", " ")
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip("\n").strip()


def text_hash(text: str) -> str:
    collapsed = " ".join((text or "").split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def escape_html(text: str) -> str:
    return html.escape(text or "", quote=True)


def html_paragraphs(text: str) -> str:
    """Escaped text with line breaks preserved (for Qt rich text and HTML export)."""
    return escape_html(text).replace("\n", "<br>")


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_csv_cell(value: str) -> str:
    """Prevent spreadsheet formula injection in CSV exports."""
    if value and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_filename(name: str, default: str = "session") -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name or "", flags=re.UNICODE).strip(" ._")
    return (name or default)[:80]

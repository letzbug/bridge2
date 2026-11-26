"""Live conversation monitor. All message text is escaped before display."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QTextBrowser

from app.security import escape_html

from . import styles

STATUS_TEXT = {
    "pending": "pending", "skipped": "skipped by operator", "discarded": "not forwarded (intervention)",
    "uncertain": "submission uncertain", "not_forwarded": "",
}


def _time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ts or ""


def entry_html(e: dict[str, Any]) -> str:
    pal = styles.palette()
    role = e.get("speaker_role", "operator")
    accent = {"host": pal["teal"], "guest": pal["blue"], "human": pal["amber"]}.get(role, pal["muted"])
    bg = {"host": pal["host_bg"], "guest": pal["guest_bg"], "human": pal["human_bg"]}.get(role, pal["panel"])
    meta = [escape_html(e.get("provider", "")) if e.get("provider") not in ("", "—") else "",
            f"Turn {e.get('turn')}", f"Round {e.get('round')}", _time(e.get("timestamp", ""))]
    if e.get("duration_s") is not None and e.get("kind") == "response":
        meta.append(f"{e['duration_s']:.1f}s")
    meta_html = " · ".join(m for m in meta if m)
    status = e.get("transfer_status", "")
    dest = escape_html(e.get("destination_name") or "")
    tags = []
    if status == "sent" and dest:
        tags.append((f"→ {dest} ✓" + (" (edited)" if e.get("edited") else ""), pal["teal"]))
    elif STATUS_TEXT.get(status):
        label = STATUS_TEXT[status] + (f" → {dest}" if dest and status == "pending" else "")
        tags.append((label, pal["amber"] if status in ("uncertain", "skipped") else pal["muted"]))
    flags = e.get("flags", []) or []
    if any(f.startswith("possible_loop") for f in flags):
        tags.append(("⚠ possible loop", pal["amber"]))
    if "oversize" in flags:
        tags.append(("⚠ long message", pal["amber"]))
    if "generation_cancelled_by_operator" in flags:
        tags.append(("generation cancelled", pal["amber"]))
    if e.get("confidence") == "low":
        tags.append(("completion uncertain", pal["amber"]))
    if e.get("simulated"):
        tags.append(("SIMULATED", pal["amber"]))
    if e.get("kind") == "initial_prompt":
        tags.insert(0, ("initial prompt", pal["muted"]))
    tag_html = "".join(f'&nbsp;&nbsp;<span style="color:{c}; font-size:8pt;">{escape_html(t)}</span>' for t, c in tags)
    name = escape_html(str(e.get("speaker_name", "")).upper())
    body = escape_html(e.get("original_text", ""))
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:7px;">'
        f'<tr><td width="3" bgcolor="{accent}"></td><td bgcolor="{bg}">'
        f'<table width="100%" cellspacing="0" cellpadding="8"><tr><td>'
        f'<span style="color:{accent}; font-weight:600; font-size:8.5pt;">{name}</span>'
        f'&nbsp;&nbsp;<span style="color:{pal["muted"]}; font-size:8pt;">{meta_html}</span>{tag_html}'
        f'<div style="white-space:pre-wrap; color:{pal["text"]}; margin-top:4px;">{body}</div>'
        f"</td></tr></table></td></tr></table>")


def system_html(text: str, tone: str, ts: str) -> str:
    pal = styles.palette()
    color = {"error": pal["red"], "warning": pal["amber"]}.get(tone, pal["system"])
    return (f'<p style="margin-top:6px; margin-bottom:0; color:{color}; font-size:8pt;">'
            f"{escape_html(ts)} · {escape_html(text)}</p>")


class TranscriptView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self._entries: dict[int, dict[str, Any]] = {}
        self._order: list[tuple] = []
        self.placeholder = ("No conversation yet. Open the browsers, log in manually, configure the session and "
                            "press Start – or enable Demo mode to try the workflow offline.")
        self.render()

    def clear_all(self) -> None:
        self._entries.clear()
        self._order.clear()
        self.render()

    def upsert(self, entry: dict[str, Any]) -> None:
        turn = int(entry["turn"])
        if turn not in self._entries:
            self._order.append(("entry", turn))
        self._entries[turn] = entry
        self.render()

    def add_system(self, text: str, tone: str = "info") -> None:
        self._order.append(("sys", text, tone, datetime.now().strftime("%H:%M:%S")))
        self.render()

    def load(self, entries: list[dict[str, Any]], events: list[dict[str, Any]] | None = None) -> None:
        self.clear_all()
        for e in entries:
            self._order.append(("entry", int(e["turn"])))
            self._entries[int(e["turn"])] = e
        for ev in events or []:
            self._order.append(("sys", f"{ev.get('code')}: {ev.get('message')}",
                                {"error": "error", "warning": "warning"}.get(ev.get("level"), "info"),
                                _time(ev.get("timestamp", ""))))
        self.render()

    def render(self) -> None:
        sb = self.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 6
        old = sb.value()
        pal = styles.palette()
        if not self._order:
            html = (f'<p style="color:{pal["faint"]}; margin-top:24px;" align="center">'
                    f"{escape_html(self.placeholder)}</p>")
        else:
            parts = []
            for item in self._order:
                if item[0] == "entry":
                    parts.append(entry_html(self._entries[item[1]]))
                else:
                    parts.append(system_html(item[1], item[2], item[3]))
            html = "".join(parts)
        self.setHtml(f'<body style="background:{pal["input"]};">{html}</body>')
        sb.setValue(sb.maximum() if at_bottom else old)

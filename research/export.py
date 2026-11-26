"""Transcript exports: TXT, Markdown, JSON, CSV and standalone HTML.

* Every export names speakers and timestamps.
* HTML exports escape all message content and carry a Content-Security-Policy
  that forbids scripts – embedded <script> in an AI response is shown as text.
* Markdown exports put each message in a fence longer than any backtick run it
  contains, so message content cannot inject markup.
* CSV cells are neutralised against spreadsheet formula injection.
* No cookies, tokens, passwords or browser data exist in the transcript model, so
  none can be exported.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from app import APP_FULL_NAME, BRANDING, __version__
from app.security import escape_html, neutralize_csv_cell

from .transcript import Transcript, TranscriptEntry

FORMATS = {"txt": "Plain text", "md": "Markdown", "json": "JSON", "csv": "CSV", "html": "Standalone HTML"}

KIND_LABEL = {"initial_prompt": "Initial prompt", "response": "Response", "human_intervention": "Human intervention"}


def _who(e: TranscriptEntry) -> str:
    role = {"host": "host", "guest": "guest", "human": "human", "operator": "operator"}.get(e.speaker_role, "")
    provider = f", {e.provider}" if e.provider and e.provider != "—" else ""
    return f"{e.speaker_name} ({role}{provider})"


def _demo_notice(t: Transcript) -> str:
    return ("DEMO MODE – all participant messages in this transcript are SIMULATED, deterministic fictional "
            "responses. They are not responses from ChatGPT or any other AI provider.") if t.meta.demo else ""


def _facts_lines(t: Transcript) -> list[str]:
    out = []
    for key, f in sorted(t.meta.facts.items()):
        val = f.get("value")
        out.append(f"{key}: {val if val is not None else '—'} [{f.get('provenance', 'unavailable')}]")
    return out


def _forward_note(e: TranscriptEntry) -> str:
    if e.kind == "response":
        if e.transfer_status == "sent":
            return f"forwarded to {e.destination_name}" + (" (edited)" if e.edited else "")
        return {"pending": "pending", "skipped": "skipped by operator", "discarded": "not forwarded (human intervention)",
                "not_forwarded": "not forwarded", "uncertain": "submission uncertain"}.get(e.transfer_status,
                                                                                        e.transfer_status)
    if e.destination_name:
        return f"sent to {e.destination_name}" if e.transfer_status == "sent" else f"to {e.destination_name}: {e.transfer_status}"
    return ""


def _header_pairs(t: Transcript) -> list[tuple[str, str]]:
    m = t.meta
    return [
        ("Session", m.title), ("Session ID", m.session_id), ("Research question", m.research_question or "—"),
        ("Topic", m.topic or "—"), ("Started", m.started_at), ("Ended", m.ended_at or "—"),
        ("End state", m.end_state or "—"), ("Host", f"{m.host_name} ({m.host_provider})"),
        ("Guest", f"{m.guest_name} ({m.guest_provider})"), ("Transfer mode", m.transfer_mode),
        ("Template mode", m.template_mode), ("Max rounds", str(m.max_rounds)),
        ("Experiment", m.experiment or "—"), ("Condition", m.condition or "—"),
    ]


# --- TXT ----------------------------------------------------------------------------------

def to_txt(t: Transcript) -> str:
    lines = [f"{APP_FULL_NAME} {__version__} – transcript", "=" * 72]
    if t.meta.demo:
        lines += [_demo_notice(t), ""]
    lines += [f"{k}: {v}" for k, v in _header_pairs(t)]
    if t.meta.facts:
        lines += ["", "Recorded facts (provenance in brackets):"] + [f"  {x}" for x in _facts_lines(t)]
    if t.meta.notes:
        lines += ["", "Notes:", t.meta.notes]
    lines.append("=" * 72)
    for e in t.entries:
        lines += ["", f"[{e.timestamp}] Turn {e.turn} · Round {e.round} · {KIND_LABEL.get(e.kind, e.kind)} · {_who(e)}"]
        note = _forward_note(e)
        if note:
            lines.append(f"  ({note})")
        lines += ["-" * 72, e.original_text]
        if e.forwarded_text is not None and e.forwarded_text != e.original_text and e.kind == "response":
            lines += ["", f">>> Text actually sent to {e.destination_name}:", e.forwarded_text]
    if t.events:
        lines += ["", "=" * 72, "Events"] + [f"[{ev.timestamp}] {ev.level.upper()} {ev.code}: {ev.message}"
                                            for ev in t.events]
    lines += ["", BRANDING]
    return "\n".join(lines) + "\n"


# --- Markdown ----------------------------------------------------------------------------------

def _fence(text: str) -> tuple[str, str]:
    longest = max((len(m) for m in re.findall(r"`+|~+", text or "")), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + "text", fence


def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>()#+\-.!|])", r"\\\1", text or "")


def to_markdown(t: Transcript) -> str:
    out = [f"# {_md_escape(t.meta.title)}", ""]
    if t.meta.demo:
        out += [f"> **{_demo_notice(t)}**", ""]
    out += ["| Field | Value |", "|---|---|"]
    out += [f"| {k} | {_md_escape(v)} |" for k, v in _header_pairs(t)]
    if t.meta.facts:
        out += ["", "**Recorded facts** (provenance: observed / user_reported / unavailable)", ""]
        out += [f"- {_md_escape(x)}" for x in _facts_lines(t)]
    out.append("")
    for e in t.entries:
        out += [f"## Turn {e.turn} · Round {e.round} · {_md_escape(_who(e))}",
                f"*{e.timestamp} · {KIND_LABEL.get(e.kind, e.kind)}*" + (f" · {_forward_note(e)}" if _forward_note(e) else ""),
                ""]
        o, c = _fence(e.original_text)
        out += [o, e.original_text, c, ""]
        if e.forwarded_text is not None and e.forwarded_text != e.original_text and e.kind == "response":
            o, c = _fence(e.forwarded_text)
            out += [f"Text actually sent to {_md_escape(e.destination_name or '')}:", "", o, e.forwarded_text, c, ""]
    if t.events:
        out += ["## Events", ""] + [f"- `{ev.timestamp}` **{ev.level}** {ev.code}: {_md_escape(ev.message)}"
                                    for ev in t.events]
    out += ["", f"*{BRANDING}*", ""]
    return "\n".join(out)


# --- JSON ----------------------------------------------------------------------------------------

def to_json(t: Transcript) -> str:
    data = {"format": "emergence-lab-transcript", "schema_version": 1, "generator": f"{APP_FULL_NAME} {__version__}",
            "simulated": t.meta.demo, **t.as_dict()}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --- CSV ------------------------------------------------------------------------------------------

CSV_COLUMNS = ["session_id", "turn", "round", "timestamp", "kind", "speaker_role", "speaker_name", "provider",
               "destination_name", "transfer_status", "edited", "duration_s", "confidence", "simulated", "flags",
               "original_text", "forwarded_text"]


def to_csv(t: Transcript) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(CSV_COLUMNS)
    for e in t.entries:
        d = e.as_dict()
        row = [t.meta.session_id] + [d.get(c) for c in CSV_COLUMNS[1:]]
        row = ["; ".join(v) if isinstance(v, list) else ("" if v is None else str(v)) for v in row]
        w.writerow([neutralize_csv_cell(v) for v in row])
    return buf.getvalue()


# --- HTML ---------------------------------------------------------------------------------------------

_CSS = """
body{margin:0;background:#0f1418;color:#d7dee4;font:14px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:32px 24px}
h1{font-size:13px;letter-spacing:.16em;color:#46d3b6;margin:0}
h2{font-size:22px;font-weight:600;margin:6px 0 18px}
.demo{border:1px solid #e8b04b;color:#e8b04b;padding:10px 12px;margin:0 0 18px}
table.meta{border-collapse:collapse;width:100%;font-size:12.5px;margin-bottom:22px}
table.meta td{border-bottom:1px solid #222c34;padding:5px 8px;vertical-align:top}
table.meta td:first-child{color:#8796a3;width:200px}
.msg{border-left:3px solid #3a4651;background:#141b21;padding:10px 14px;margin:12px 0}
.msg.host{border-color:#46d3b6}.msg.guest{border-color:#7ea6ff}.msg.human{border-color:#e8b04b}.msg.operator{border-color:#8796a3}
.head{font-size:12px;color:#8796a3;margin-bottom:6px}.head b{color:#d7dee4}
.text{white-space:pre-wrap;word-wrap:break-word}
.fwd{margin-top:8px;padding-top:8px;border-top:1px dashed #2a353f;font-size:12.5px}
.ev{font-size:12px;color:#8796a3;font-family:Consolas,monospace}
footer{margin-top:28px;font-size:12px;color:#66737e}
"""


def to_html(t: Transcript) -> str:
    esc = escape_html
    parts = [
        "<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
        "img-src 'none'; script-src 'none'; form-action 'none'; base-uri 'none'\">",
        '<meta name="referrer" content="no-referrer">',
        f"<title>{esc(t.meta.title)} – EMERGENCE LAB transcript</title>", f"<style>{_CSS}</style></head><body>",
        '<div class="wrap"><h1>EMERGENCE LAB · AI CONVERSATION BRIDGE</h1>', f"<h2>{esc(t.meta.title)}</h2>",
    ]
    if t.meta.demo:
        parts.append(f'<div class="demo">{esc(_demo_notice(t))}</div>')
    parts.append('<table class="meta">')
    parts += [f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in _header_pairs(t)]
    for line in _facts_lines(t):
        k, _, v = line.partition(": ")
        parts.append(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>")
    if t.meta.notes:
        parts.append(f'<tr><td>Notes</td><td class="text">{esc(t.meta.notes)}</td></tr>')
    parts.append("</table>")
    for e in t.entries:
        role = e.speaker_role if e.speaker_role in ("host", "guest", "human", "operator") else "operator"
        note = _forward_note(e)
        parts.append(f'<div class="msg {role}"><div class="head"><b>{esc(e.speaker_name)}</b> · '
                     f"{esc(e.provider)} · Turn {e.turn} · Round {e.round} · {esc(KIND_LABEL.get(e.kind, e.kind))} · "
                     f"{esc(e.timestamp)}" + (f" · {esc(note)}" if note else "") + "</div>")
        parts.append(f'<div class="text">{esc(e.original_text)}</div>')
        if e.forwarded_text is not None and e.forwarded_text != e.original_text and e.kind == "response":
            parts.append(f'<div class="fwd">Text actually sent to {esc(e.destination_name or "")}:'
                         f'<div class="text">{esc(e.forwarded_text)}</div></div>')
        parts.append("</div>")
    if t.events:
        parts.append("<h3>Events</h3>")
        parts += [f'<div class="ev">{esc(ev.timestamp)} {esc(ev.level.upper())} {esc(ev.code)}: {esc(ev.message)}</div>'
                  for ev in t.events]
    parts.append(f"<footer>{esc(BRANDING)} · {esc(APP_FULL_NAME)} {esc(__version__)}</footer></div></body></html>")
    return "\n".join(parts) + "\n"


EXPORTERS = {"txt": to_txt, "md": to_markdown, "json": to_json, "csv": to_csv, "html": to_html}


def export_transcript(t: Transcript, fmt: str) -> str:
    try:
        return EXPORTERS[fmt](t)
    except KeyError as exc:
        raise ValueError(f"unsupported export format '{fmt}'") from exc


def export_to_file(t: Transcript, path: Path, fmt: str | None = None) -> Path:
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    content = export_transcript(t, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = "" if fmt == "csv" else None
    with open(path, "w", encoding="utf-8-sig" if fmt == "csv" else "utf-8", newline=newline) as fh:
        fh.write(content)
    return path

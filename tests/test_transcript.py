"""Transcript model, SQLite storage, exports and sanitisation."""

import asyncio
import csv
import io
import json
import re

from app.events import EventBus
from research.experiments import compare
from research.export import FORMATS, export_to_file, export_transcript
from research.session_manager import SessionRecorder, SessionStore
from research.transcript import Provenance, SessionMeta, Transcript, TranscriptEntry, fact

from .fakes import ScriptedAdapter, make_engine, numbered

MALICIOUS = ('<script>alert("x")</script><img src=x onerror="alert(1)"> [click](javascript:alert(1)) '
             '``` </div><iframe src="https://evil.example"></iframe> =HYPERLINK("http://evil","x")')


def sample(demo: bool = False) -> Transcript:
    t = Transcript(meta=SessionMeta(title="Dreams & <memory>", host_name="Cameron", host_provider="ChatGPT",
                                    guest_name="Gem", guest_provider="Gemini", demo=demo, topic="dreaming"))
    t.meta.facts["guest_model"] = fact("Gemini 3 (user-reported)", Provenance.USER_REPORTED)
    t.meta.facts["host_conversation_id"] = fact("abc", Provenance.OBSERVED)
    t.meta.facts["guest_memory"] = fact(None, Provenance.USER_REPORTED)
    t.add(TranscriptEntry(1, 1, "initial_prompt", "operator", "Operator", "—", "2026-11-25T14:00:00+01:00",
                          "Hello", destination="host", destination_name="Cameron", transfer_status="sent",
                          forwarded_text="Hello"))
    t.add(TranscriptEntry(2, 1, "response", "host", "Cameron", "ChatGPT", "2026-11-25T14:00:10+01:00", MALICIOUS,
                          destination="guest", destination_name="Gem", transfer_status="sent",
                          forwarded_text="Message from Cameron:\n\n" + MALICIOUS, duration_s=3.2))
    t.add(TranscriptEntry(3, 1, "human_intervention", "human", "Human researcher", "—",
                          "2026-11-25T14:01:00+01:00", "Please slow down.", destination="guest",
                          destination_name="Gem", transfer_status="sent", forwarded_text="Please slow down."))
    t.add_event("warning", "loop_detected", "Turn 2: <b>near duplicate</b>")
    return t


def test_all_formats_identify_speakers_and_timestamps():
    t = sample()
    for fmt in FORMATS:
        out = export_transcript(t, fmt)
        assert "Cameron" in out and "Gem" in out and "Human researcher" in out, fmt
        assert "2026-11-25T14:00:10+01:00" in out, fmt


def test_html_export_is_sanitized():
    out = export_transcript(sample(), "html")
    assert "<script" not in out.lower()
    assert "<iframe" not in out.lower()
    assert "<img" not in out.lower()
    assert 'onerror="' not in out
    assert "&lt;script&gt;" in out and "&lt;iframe" in out
    assert "script-src 'none'" in out
    assert "<b>near duplicate</b>" not in out          # event text escaped too
    assert "Dreams &amp; &lt;memory&gt;" in out


def test_markdown_fences_contain_injection():
    out = export_transcript(sample(), "md")
    # the message contains ``` – the fence around it must be longer
    m = re.search(r"\n(`{4,})text\n<script>", out)
    assert m, out[:800]


def test_csv_formula_injection_neutralized():
    t = sample()
    t.entries[2].original_text = "=cmd|' /C calc'!A0"
    rows = list(csv.reader(io.StringIO(export_transcript(t, "csv"))))
    header, data = rows[0], rows[1:]
    col = header.index("original_text")
    assert data[2][col].startswith("'=")


def test_json_roundtrip_and_provenance():
    t = sample()
    data = json.loads(export_transcript(t, "json"))
    assert data["meta"]["facts"]["host_conversation_id"]["provenance"] == "observed"
    assert data["meta"]["facts"]["guest_model"]["provenance"] == "user_reported"
    assert data["meta"]["facts"]["guest_memory"]["provenance"] == "unavailable"
    assert set(data) == {"format", "schema_version", "generator", "simulated", "meta", "entries", "events"}
    back = Transcript.from_dict(data)
    assert back.entries[1].original_text == MALICIOUS     # original preserved exactly


def test_original_and_forwarded_kept_separately_in_exports():
    out = export_transcript(sample(), "txt")
    assert "Text actually sent to Gem" in out


def test_demo_exports_are_labelled():
    for fmt in ("txt", "md", "html"):
        assert "SIMULATED" in export_transcript(sample(demo=True), fmt)
    assert json.loads(export_transcript(sample(demo=True), "json"))["simulated"] is True


def test_sqlite_store_save_load_delete(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    t = sample()
    store.save_transcript(t)
    listed = store.list_sessions()
    assert listed[0]["session_id"] == t.meta.session_id and listed[0]["message_count"] == 3
    loaded = store.load(t.meta.session_id)
    assert loaded.entries[1].original_text == MALICIOUS and loaded.events[0].code == "loop_detected"
    export_to_file(loaded, tmp_path / "out.html")
    assert (tmp_path / "out.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    store.delete(t.meta.session_id)
    assert store.list_sessions() == []
    store.save_transcript(sample())
    store.save_transcript(sample())
    store.delete_all()
    assert store.list_sessions() == []


def test_recorder_writes_engine_session_and_can_be_disabled(tmp_path):
    async def scenario(record: bool):
        store = SessionStore(tmp_path / f"r{record}.sqlite3")
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=2)
        rec = SessionRecorder(engine.bus, store)
        rec.enabled = record
        await engine.start()
        await engine.wait_finished(10)
        return store, engine
    store, engine = asyncio.run(scenario(True))
    loaded = store.load(engine.transcript.meta.session_id)
    assert loaded is not None and len(loaded.entries) == 5 and loaded.meta.end_state == "COMPLETED"
    metrics = compare([loaded])[0]
    assert metrics["completed_rounds"] == 2 and metrics["host_responses"] == 2
    store2, _ = asyncio.run(scenario(False))
    assert store2.list_sessions() == []


def test_loading_never_resumes(tmp_path):
    store = SessionStore(tmp_path / "x.sqlite3")
    store.save_transcript(sample())
    loaded = store.load(store.list_sessions()[0]["session_id"])
    assert isinstance(loaded, Transcript)      # pure data object – no engine, no adapters
    _ = EventBus()


def test_fixture_transcript_loads_and_reexports():
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "fixtures" / "sample_transcript.json").read_text(encoding="utf-8"))
    t = Transcript.from_dict(data)
    assert t.entries[1].original_text == MALICIOUS
    assert "&lt;script&gt;" in export_transcript(t, "html")

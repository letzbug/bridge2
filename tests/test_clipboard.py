"""Clipboard fallback: a full conversation without any browser automation."""

import asyncio

from adapters.clipboard import ClipboardAdapter
from app.clipboard_workflow import ClipboardCoordinator
from app.engine import ConversationConfig, ConversationEngine, Participant, Role, TransferMode
from app.events import EventBus, EventType
from app.gate import SendGate
from app.state_machine import ConversationState as S

from .fakes import wait_for


def build(max_rounds=2):
    bus = EventBus()
    coord = ClipboardCoordinator(bus)
    host = ClipboardAdapter("host", "Cameron", "ChatGPT", coord)
    guest = ClipboardAdapter("guest", "Gem", "Gemini", coord)
    cfg = ConversationConfig(session_name="clip", topic="t", max_rounds=max_rounds,
                             transfer_mode=TransferMode.CLIPBOARD, min_interval_seconds=0)
    engine = ConversationEngine(Participant(Role.HOST, "Cameron", host.provider_label, host),
                                Participant(Role.GUEST, "Gem", guest.provider_label, guest), cfg, bus=bus,
                                gate=SendGate())
    return engine, coord, bus


def test_full_clipboard_conversation():
    async def scenario():
        engine, coord, bus = build(max_rounds=2)
        requests = []
        bus.subscribe(lambda ev: requests.append(ev) if ev.type == EventType.CLIPBOARD_REQUEST else None)
        pasted = []
        await engine.start()
        replies = iter([("host", "Cameron reply one, quite distinct words alpha"),
                        ("guest", "Gem reply one, different vocabulary beta gamma"),
                        ("host", "Cameron reply two with delta epsilon zeta"),
                        ("guest", "Gem reply two closing with eta theta iota")])
        done = 0
        while engine.state != S.COMPLETED:
            await wait_for(lambda: coord.pending() or engine.state == S.COMPLETED)
            if engine.state == S.COMPLETED:
                break
            req = coord.pending()[0]
            if req.action == "paste":
                text = req.text if done != 1 else req.text + "\n(edited by operator)"
                pasted.append((req.role, text))
                coord.resolve(req.request_id, text)          # operator pasted & sent
            else:
                role, reply = next(replies)
                assert role == req.role                      # engine asks for the expected speaker
                coord.resolve(req.request_id, {"text": reply, "speaker": req.role})
                done += 1
            await asyncio.sleep(0.01)
        assert [r for r, _ in pasted] == ["host", "guest", "host", "guest"]
        responses = engine.transcript.responses()
        assert [r.speaker_role for r in responses] == ["host", "guest", "host", "guest"]
        assert responses[0].forwarded_text.endswith("(edited by operator)") and responses[0].edited
        assert all(r.confidence == "user" and "clipboard_import" in r.flags for r in responses)
        assert requests and all(ev.data["action"] in ("paste", "import") for ev in requests)
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_clipboard_import_can_identify_other_speaker():
    async def scenario():
        engine, coord, _ = build(max_rounds=3)
        await engine.start()
        await wait_for(lambda: coord.find("paste") is not None)
        coord.resolve(coord.find("paste").request_id, "hi")
        await wait_for(lambda: coord.find("import") is not None)
        req = coord.find("import")
        assert req.role == "host"
        coord.resolve(req.request_id, {"text": "This one was actually written by Gem", "speaker": "guest"})
        await wait_for(lambda: coord.find("paste") is not None)
        assert coord.find("paste").role == "host"            # Gem's text goes to Cameron
        assert engine.transcript.responses()[0].speaker_role == "guest"
        await engine.stop()
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_clipboard_works_when_no_browser_adapter_is_available():
    async def scenario():
        engine, coord, _ = build(max_rounds=1)
        await engine.start()                                   # no browser, no automation at all
        assert engine.state != S.ERROR
        await wait_for(lambda: coord.find("paste") is not None)
        await engine.emergency_stop()
        await wait_for(lambda: not coord.pending())
        assert engine.state == S.STOPPED
    asyncio.run(asyncio.wait_for(scenario(), 20))

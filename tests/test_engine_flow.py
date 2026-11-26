"""Conversation engine flows with fake adapters."""

import asyncio

from adapters.demo import DemoAdapter
from app.engine import ConfirmStep, TransferMode
from app.events import EventType
from app.state_machine import ConversationState as S

from .fakes import ScriptedAdapter, make_engine, numbered, wait_for


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def test_complete_round_and_alternating_speakers():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, rec = make_engine(host, guest, max_rounds=3)
        await engine.start()
        assert await engine.wait_finished(10)
        assert engine.state == S.COMPLETED
        speakers = [e.speaker_role for e in engine.transcript.entries]
        assert speakers == ["operator", "host", "guest", "host", "guest", "host", "guest"]
        assert engine.completed_rounds == 3
        # round limit: exactly 3 messages to each side (initial + 2 forwards to host, 3 forwards to guest)
        assert len(host.sent) == 3 and len(guest.sent) == 3
        rounds = rec.of(EventType.ROUND)
        assert rounds[-1].data["completed_rounds"] == 3
        # attribution mode by default
        assert guest.sent[0].startswith("Message from Cameron:")
        assert host.sent[1].startswith("Message from Gem:")
        # original and forwarded text are stored separately
        first = engine.transcript.responses()[0]
        assert first.original_text in first.forwarded_text and first.original_text != first.forwarded_text
    run(scenario())


def test_guest_first_speaker_and_raw_mode():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=2, first_speaker="guest", attribution=False)
        await engine.start()
        assert await engine.wait_finished(10)
        speakers = [e.speaker_role for e in engine.transcript.responses()]
        assert speakers == ["guest", "host", "guest", "host"]
        assert host.sent[0] == engine.transcript.responses()[0].original_text   # raw transfer
    run(scenario())


def test_manual_confirmation_with_edit_and_skip():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, rec = make_engine(host, guest, max_rounds=2, transfer_mode=TransferMode.MANUAL)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        req = rec.of(EventType.CONFIRMATION_REQUIRED)[-1]
        assert req.data["alternatives"][0]["destination"] == "guest"
        assert len(guest.sent) == 0                              # nothing forwarded before confirmation
        assert engine.confirm("EDITED TEXT for Gem")
        await wait_for(lambda: len(guest.sent) == 1)
        assert guest.sent[0] == "EDITED TEXT for Gem"
        entry = engine.transcript.responses()[0]
        assert entry.edited and entry.forwarded_text == "EDITED TEXT for Gem"
        assert "host reply number 0" in entry.original_text      # original kept
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        assert engine.skip()
        await wait_for(lambda: engine.state == S.HUMAN_INTERVENTION)
        assert engine.transcript.responses()[1].transfer_status == "skipped"
        engine.resume_previous()                                  # re-offers the skipped transfer
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        engine.confirm(None)
        await wait_for(lambda: len(host.sent) == 2)
        assert host.sent[1].startswith("Message from Gem:")
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        engine.confirm(None)
        assert await engine.wait_finished(10)
        assert engine.state == S.COMPLETED
    run(scenario())


def test_pause_during_generation_and_resume():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), generation_seconds=0.3)
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=2)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_HOST)
        engine.pause()
        assert engine.state == S.PAUSED
        await wait_for(lambda: len(engine.transcript.responses()) == 1)   # response still recorded
        await asyncio.sleep(0.2)
        assert len(guest.sent) == 0                                      # ...but not forwarded
        assert engine.state == S.PAUSED
        await engine.resume()
        await wait_for(lambda: len(guest.sent) == 1)
        assert await engine.wait_finished(10)
        assert engine.state == S.COMPLETED
    run(scenario())


def test_timeout_then_keep_waiting_without_resend():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), timeout_once_on={0})
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, rec = make_engine(host, guest, max_rounds=1, max_wait_seconds=1)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED)
        issue = rec.of(EventType.ISSUE)[-1]
        assert issue.data["code"] == "timeout"
        assert host.submissions == 1
        await engine.resume()
        assert await engine.wait_finished(10)
        assert host.submissions == 1                       # never resent
        assert engine.state == S.COMPLETED
    run(scenario())


def test_uncertain_submission_requires_manual_verification():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"))
        guest = ScriptedAdapter("Gem", numbered("guest"), uncertain_on={0})
        engine, rec = make_engine(host, guest, max_rounds=2)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        req = rec.of(EventType.CONFIRMATION_REQUIRED)[-1]
        assert req.data["kind"] == "verify"
        await asyncio.sleep(0.1)
        assert guest.submissions == 1                      # no automatic resend
        assert engine.resolve_verification(True)
        assert await engine.wait_finished(10)
        assert guest.submissions == 2                      # second message is the next normal transfer
        assert engine.state == S.COMPLETED
    run(scenario())


def test_uncertain_submission_operator_requests_resend():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), uncertain_on={0})
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=1)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        engine.resolve_verification(False)
        await wait_for(lambda: host.submissions == 2)
        assert await engine.wait_finished(10)
    run(scenario())


def test_browser_disconnection_enters_error_and_does_not_retry():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"))
        guest = ScriptedAdapter("Gem", numbered("guest"), close_on_send={0})
        engine, rec = make_engine(host, guest, max_rounds=3)
        await engine.start()
        await wait_for(lambda: engine.state == S.ERROR)
        assert rec.of(EventType.ISSUE)[-1].data["code"] == "browser_closed"
        await asyncio.sleep(0.2)
        assert engine.state == S.ERROR                    # no silent continuation, no retry loop
        await engine.resume()                             # browser still closed -> stays in ERROR
        assert engine.state == S.ERROR
        await engine.stop()
        assert engine.state == S.STOPPED
    run(scenario())


def test_duplicate_response_pauses_session():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"))
        guest = ScriptedAdapter("Gem", ["I keep saying exactly the same thing in every single reply here."])
        engine, rec = make_engine(host, guest, max_rounds=5)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED)
        issue = rec.of(EventType.ISSUE)[-1]
        assert issue.data["code"] == "loop_detected"
        assert isinstance(engine.pending_step, ConfirmStep)
        flagged = [e for e in engine.transcript.responses() if any(f.startswith("possible_loop") for f in e.flags)]
        assert flagged and flagged[0].speaker_role == "guest"
        await engine.stop()
    run(scenario())


def test_human_intervention_to_guest_and_resume_flow():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=3, transfer_mode=TransferMode.MANUAL)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        assert engine.begin_human_intervention()
        assert engine.state == S.HUMAN_INTERVENTION
        assert await engine.human_send("guest", "Please answer in German from now on.")
        human = [e for e in engine.transcript.entries if e.kind == "human_intervention"]
        assert human and human[0].destination == "guest" and human[0].speaker_role == "human"
        assert guest.sent == ["Please answer in German from now on."]
        # the pending host->guest transfer was discarded, not silently sent
        assert engine.transcript.responses()[0].transfer_status == "discarded"
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        assert engine.pending_step.alternatives[0].destination.value == "host"
        await engine.stop()
    run(scenario())


def test_human_send_to_both_waits_for_pending_and_is_sequential():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), generation_seconds=0.2)
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=4)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_HOST)
        engine.begin_human_intervention()
        ok = await engine.human_send("both", "A note for both of you.")
        assert ok
        assert host.sent[-1] == "A note for both of you." and guest.sent[-1] == "A note for both of you."
        # host's pending response was recorded before the human message was sent
        assert engine.transcript.responses()[0].speaker_role == "host"
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        alts = engine.pending_step.alternatives
        assert len(alts) == 2                              # operator chooses which reply to forward
        engine.confirm(None, alternative=1)
        await wait_for(lambda: len(guest.sent) == 2)
        await engine.stop()
    run(scenario())


def test_cancel_generation_is_explicit():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), generation_seconds=5)
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=2)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_HOST)
        assert await engine.cancel_generation("host")
        await wait_for(lambda: len(engine.transcript.responses()) == 1)
        assert "generation_cancelled_by_operator" in engine.transcript.responses()[0].flags
        await engine.stop()
    run(scenario())


def test_rate_limit_hourly_cap_pauses():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, rec = make_engine(host, guest, max_rounds=5, max_messages_per_hour=1)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED)
        assert rec.of(EventType.ISSUE)[-1].data["code"] == "rate_limited"
        assert len(host.sent) == 1
        await engine.stop()
    run(scenario())


def test_demo_mode_runs_offline_and_is_labelled():
    async def scenario():
        host = DemoAdapter("host", "Cameron (simulated)", "dreams", think_seconds=0.01, stream_seconds=0.05)
        guest = DemoAdapter("guest", "Guest (simulated)", "dreams", think_seconds=0.01, stream_seconds=0.05)
        engine, _ = make_engine(host, guest, max_rounds=2, demo=True)
        await engine.start()
        assert await engine.wait_finished(10)
        for e in engine.transcript.responses():
            assert e.simulated and e.original_text.startswith("[SIMULATED")
        assert engine.transcript.meta.demo
    run(scenario())


def test_demo_loop_scenario_triggers_loop_detection():
    async def scenario():
        host = DemoAdapter("host", "Cameron (simulated)", think_seconds=0.01, stream_seconds=0.02)
        guest = DemoAdapter("guest", "Guest (simulated)", scenario="loop", think_seconds=0.01, stream_seconds=0.02)
        engine, rec = make_engine(host, guest, max_rounds=5)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED, timeout=10)
        assert rec.of(EventType.ISSUE)[-1].data["code"] == "loop_detected"
        await engine.stop()
    run(scenario())


def test_demo_timeout_scenario_resume_keeps_waiting():
    async def scenario():
        host = DemoAdapter("host", "Cameron (simulated)", think_seconds=0.01, stream_seconds=0.02)
        guest = DemoAdapter("guest", "Guest (simulated)", scenario="timeout", think_seconds=0.01, stream_seconds=0.02)
        engine, rec = make_engine(host, guest, max_rounds=3, max_wait_seconds=1)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED, timeout=10)
        assert rec.of(EventType.ISSUE)[-1].data["code"] == "timeout"
        sent_before = len([m for m in guest._messages if m[0] == "user"])
        await engine.resume()
        assert await engine.wait_finished(10)
        assert engine.state == S.COMPLETED
        user_msgs = [m for m in guest._messages if m[0] == "user"]
        assert len(user_msgs) == 3 and sent_before == 2     # nothing resent after the timeout
    run(scenario())


def test_next_turn_steps_exactly_one_response():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=4)
        await engine.start()
        await wait_for(lambda: len(engine.transcript.responses()) >= 1)
        engine.pause()
        await asyncio.sleep(0.2)
        count = len(engine.transcript.responses())
        await engine.next_turn()
        await wait_for(lambda: len(engine.transcript.responses()) == count + 1)
        await asyncio.sleep(0.2)
        assert len(engine.transcript.responses()) == count + 1
        assert engine.state == S.PAUSED
        await engine.stop()
    run(scenario())


def test_message_over_destination_input_limit_requires_edit():
    async def scenario():
        host = ScriptedAdapter("Cameron", lambda n, r: "word " * 400 + str(n))
        guest = ScriptedAdapter("Gem", numbered("guest"))
        guest.max_input_chars = 500
        engine, rec = make_engine(host, guest, max_rounds=2)
        await engine.start()
        await wait_for(lambda: engine.state == S.PAUSED)
        assert rec.of(EventType.ISSUE)[-1].data["code"] == "oversize"
        assert guest.submissions == 0
        await engine.resume()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        engine.confirm("A shortened version written by the operator.")
        await wait_for(lambda: guest.submissions == 1)
        assert guest.sent[0] == "A shortened version written by the operator."
        await engine.stop()
    run(scenario())

import asyncio
import threading

from adapters.errors import SubmissionBlockedError
from app.engine import TransferMode
from app.gate import SendGate
from app.state_machine import ConversationState as S

from .fakes import ScriptedAdapter, make_engine, numbered, wait_for


def test_emergency_stop_blocks_all_further_submissions():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"), delay=0.05)
        guest = ScriptedAdapter("Gem", numbered("guest"), delay=0.05)
        engine, _ = make_engine(host, guest, max_rounds=50, delay_seconds=0.05)
        await engine.start()
        await wait_for(lambda: len(guest.sent) >= 1)
        await engine.emergency_stop()
        assert engine.state == S.STOPPED
        before = (host.submissions, guest.submissions)
        await asyncio.sleep(0.4)
        assert (host.submissions, guest.submissions) == before
        assert not engine.gate.armed
        assert any(e.code == "emergency_stop" for e in engine.transcript.events)
        # adapters themselves refuse to submit while the gate is closed
        try:
            await host.send_message("should never be sent")
            raise AssertionError("expected SubmissionBlockedError")
        except SubmissionBlockedError:
            pass
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_emergency_stop_from_another_thread_is_immediate():
    async def scenario():
        host = ScriptedAdapter("Cameron", numbered("host"))
        guest = ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=3, transfer_mode=TransferMode.MANUAL)
        await engine.start()
        await wait_for(lambda: engine.state == S.WAITING_FOR_CONFIRMATION)
        t = threading.Thread(target=engine.emergency_stop_threadsafe)
        t.start()
        t.join()
        assert not engine.gate.armed            # closed synchronously, before the loop runs again
        await wait_for(lambda: engine.state == S.STOPPED)
        assert engine.confirm("late click") is False
        assert guest.submissions == 0
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_stop_does_not_close_browsers_and_cannot_restart_itself():
    async def scenario():
        host, guest = ScriptedAdapter("Cameron", numbered("host")), ScriptedAdapter("Gem", numbered("guest"))
        engine, _ = make_engine(host, guest, max_rounds=10)
        await engine.start()
        await wait_for(lambda: len(engine.transcript.responses()) >= 2)
        await engine.stop()
        assert engine.state == S.STOPPED
        assert not host.closed and not guest.closed
        n = host.submissions + guest.submissions
        await asyncio.sleep(0.3)
        assert host.submissions + guest.submissions == n
        await engine.resume()                        # resume after stop does nothing
        assert engine.state == S.STOPPED
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_gate_basics():
    gate = SendGate()
    gate.check()
    gate.disarm("test")
    try:
        gate.check()
        raise AssertionError
    except SubmissionBlockedError as exc:
        assert "test" in str(exc)
    gate.arm()
    gate.check()

"""Controller: adapter selection, permission gating, demo/clipboard start, export."""

import asyncio

import pytest

from adapters.clipboard import ClipboardAdapter
from adapters.demo import DemoAdapter
from app.controller import BridgeController, StartError
from app.engine import Role
from app.events import EventBus
from app.settings import Settings
from app.state_machine import ConversationState as S
from research.session_manager import SessionStore

from .fakes import wait_for


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("EMERGENCE_LAB_HOME", str(tmp_path / "data"))
    settings = Settings(path=tmp_path / "settings.json")
    return BridgeController(settings, EventBus(), store=SessionStore(tmp_path / "s.sqlite3"))


def test_defaults(controller):
    assert controller.provider_id("host") == "chatgpt"
    assert controller.name("host") == "Cameron"
    assert controller.settings.get("conversation.max_rounds") == 10
    assert controller.settings.get("conversation.transfer_mode") == "manual"
    assert controller.settings.get("conversation.attribution") is True


def test_automation_requires_acknowledgement(controller):
    allowed, reason = controller.automation_allowed("host")
    assert not allowed and "Clipboard" in reason
    controller.settings.set("automation_acknowledged", {"chatgpt": "2026-11-25"})
    assert controller.automation_allowed("host")[0]
    with pytest.raises(StartError, match="browser is not open"):
        controller.build_adapter("host", controller.build_config())


def test_start_without_permission_is_refused(controller):
    async def scenario():
        with pytest.raises(StartError, match="not enabled"):
            await controller.start_conversation()
    asyncio.run(scenario())


def test_automatic_mode_needs_passed_diagnostics(controller):
    controller.settings.set("automation_acknowledged", {"chatgpt": "x", "gemini": "x"})
    controller.settings.set("conversation.transfer_mode", "automatic")
    controller.browsers.is_open = lambda role: True
    with pytest.raises(StartError, match="diagnostic"):
        controller.build_adapter("host", controller.build_config())
    controller.diagnostics_passed["host"] = True
    adapter, _ = controller.build_adapter("host", controller.build_config())
    assert adapter.provider_id == "chatgpt"


def test_standard_firefox_backend_uses_clipboard(controller):
    controller.settings.set("guest.browser_backend", "standard")
    adapter, label = controller.build_adapter("guest", controller.build_config())
    assert isinstance(adapter, ClipboardAdapter) and "clipboard" in label


def test_demo_session_runs_and_exports(controller, tmp_path):
    controller.settings.set("demo_mode", True)
    controller.settings.set("conversation.max_rounds", 2)
    controller.settings.set("conversation.transfer_mode", "automatic")
    controller.settings.set("conversation.delay_seconds", 0)
    controller.settings.set("limits.min_interval_seconds", 0)

    async def scenario():
        host, _ = controller.build_adapter("host", controller.build_config())
        assert isinstance(host, DemoAdapter) and "simulated" in host.participant_name
        await controller.start_conversation()
        for p in controller.engine.participants.values():
            p.adapter.think_seconds, p.adapter.stream_seconds = 0.01, 0.02
        assert await controller.engine.wait_finished(20)
        assert controller.engine.state == S.COMPLETED
        out = await controller.export(str(tmp_path / "demo.html"))
        html = open(out, encoding="utf-8").read()
        assert "SIMULATED" in html and "DEMO MODE" in html
        sessions = await controller.list_sessions()
        assert sessions and sessions[0]["demo"] == 1
        await controller.new_session()
        assert controller.engine is None and (await controller.get_transcript()) is not None
        await controller.shutdown()
    asyncio.run(asyncio.wait_for(scenario(), 30))


def test_clipboard_mode_start_without_any_browser(controller, tmp_path):
    controller.settings.set("conversation.transfer_mode", "clipboard")

    async def scenario():
        await controller.start_conversation()
        eng = controller.engine
        assert isinstance(eng.participants[Role.HOST].adapter, ClipboardAdapter)
        await wait_for(lambda: controller.coordinator.find("paste") is not None)
        controller.emergency_stop_threadsafe()
        await wait_for(lambda: eng.state == S.STOPPED)
        assert not controller.gate.armed
        with pytest.raises(ValueError):
            await controller.export(str(tmp_path / "x.unknown"), "nope")
        await controller.shutdown()
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_second_start_while_running_is_refused(controller):
    controller.settings.set("conversation.transfer_mode", "clipboard")

    async def scenario():
        await controller.start_conversation()
        with pytest.raises(StartError, match="already running"):
            await controller.start_conversation()
        await controller.stop()
        await controller.shutdown()
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_export_without_transcript_is_refused(controller, tmp_path):
    async def scenario():
        with pytest.raises(StartError, match="no transcript"):
            await controller.export(str(tmp_path / "x.txt"))
    asyncio.run(scenario())


def test_diagnostics_require_automation_permission(controller):
    async def scenario():
        report = await controller.diagnose("host")
        assert not report.passed and any("form of automation" in n for n in report.notes)
        assert await controller.refresh_auth("host") == "unknown"
    asyncio.run(scenario())

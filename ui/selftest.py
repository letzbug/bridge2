"""GUI self-test – a real PySide6 smoke test of the complete desktop application.

Runs inside the application (source or portable build):

    EmergenceLab.exe --gui-selftest --report gui.json
    python main.py --gui-selftest

It builds the main window, every dialog and the compact bar, feeds every event type
through the handlers, runs a demo conversation and a clipboard conversation through the
real controller/engine thread, exercises human intervention and the emergency stop,
exports a transcript and shuts down. No provider is contacted and no modal dialog is
shown (warnings are collected in the report). Uses a temporary data directory.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from app.events import Event, EventType
from app.selftest import _step, base_report, write_report


def _sample_events() -> list[Event]:
    entry = {"turn": 2, "round": 1, "kind": "response", "speaker_role": "host", "speaker_name": "Cameron",
             "provider": "ChatGPT", "timestamp": "2026-11-25T14:00:00+01:00", "original_text": "<b>hi</b>\nthere",
             "destination": "guest", "destination_name": "Gem", "transfer_status": "sent", "edited": True,
             "duration_s": 2.5, "flags": ["possible_loop:near_duplicate", "oversize"], "confidence": "low",
             "simulated": True}
    alts = [{"source_turn": 2, "source_name": "Cameron", "destination": "guest", "destination_name": "Gem",
             "text": "Message from Cameron: hi", "original": "hi"},
            {"source_turn": 3, "source_name": "Gem", "destination": "host", "destination_name": "Cameron",
             "text": "Message from Gem: yo", "original": "yo"}]
    return [
        Event(EventType.SESSION_STARTED, {"meta": {"title": "t", "transfer_mode": "manual", "demo": True, "max_rounds": 5}}),
        Event(EventType.STATE, {"state": "WAITING_FOR_HOST"}),
        Event(EventType.ENTRY_ADDED, {"entry": entry}),
        Event(EventType.ENTRY_UPDATED, {"entry": {**entry, "transfer_status": "skipped"}}),
        Event(EventType.ROUND, {"current_round": 2, "completed_rounds": 1, "max_rounds": 5, "turn": 3}),
        Event(EventType.TRANSFER, {"status": "sending", "destination": "guest", "destination_name": "Gem"}),
        Event(EventType.WAITING, {"role": "guest", "name": "Gem", "active": True, "timeout": 60}),
        Event(EventType.ISSUE, {"code": "timeout", "severity": "warning", "message": "timeout", "actions": ["keep_waiting"]}),
        Event(EventType.ISSUE_CLEARED, {}),
        Event(EventType.CONFIRMATION_REQUIRED, {"kind": "transfer", "warnings": ["w"], "alternatives": alts}),
        Event(EventType.CONFIRMATION_CLEARED, {}),
        Event(EventType.CONFIRMATION_REQUIRED, {"kind": "verify", "role": "guest", "name": "Gem", "text": "x", "message": "m"}),
        Event(EventType.CONFIRMATION_CLEARED, {}),
        Event(EventType.HUMAN, {"status": "open", "pending": {"kind": "await", "name": "Gem"}}),
        Event(EventType.HUMAN, {"status": "waiting_for_pending", "detail": "d"}),
        Event(EventType.HUMAN, {"status": "closed"}),
        Event(EventType.CLIPBOARD_REQUEST, {"request_id": "r1", "action": "paste", "role": "guest", "name": "Gem", "text": "x"}),
        Event(EventType.CLIPBOARD_CLEARED, {"request_id": "r1"}),
        Event(EventType.CLIPBOARD_REQUEST, {"request_id": "r2", "action": "import", "role": "host", "name": "Cameron", "text": ""}),
        Event(EventType.CLIPBOARD_CLEARED, {"request_id": "r2"}),
        Event(EventType.PARTICIPANT, {"role": "host", "field": "browser", "value": "open", "detail": ""}),
        Event(EventType.PARTICIPANT, {"role": "guest", "field": "auth", "value": "login_required"}),
        Event(EventType.PARTICIPANT, {"role": "guest", "field": "diagnostics", "value": "passed"}),
        Event(EventType.LOG, {"level": "warning", "message": "log line"}),
        Event(EventType.AUDIO, {"status": "recording"}),
        Event(EventType.AUDIO, {"status": "recording_stopped"}),
        Event(EventType.SESSION_ENDED, {"end_state": "STOPPED", "reason": "x"}),
        Event(EventType.STATE, {"state": "STOPPED"}),
    ]


def run_gui_selftest(app: Any, report_path: str | None = None) -> int:
    import PySide6

    from app.settings import Settings

    from . import styles
    from .main_window import MainWindow
    from .qt_bridge import QtBridge

    stub = bool(getattr(PySide6, "STUB", False))
    report = base_report("gui-selftest")
    report["qt_platform"] = os.environ.get("QT_QPA_PLATFORM", "native")
    report["qt_stub"] = stub
    try:
        from PySide6.QtCore import qVersion
        report["qt_version"] = "stub" if stub else str(qVersion())
    except Exception:  # noqa: BLE001
        report["qt_version"] = "unknown"
    print(f"GUI self-test · Qt {report['qt_version']} · platform {report['qt_platform']}"
          + (" · STRUCTURAL STUB (no rendering)" if stub else ""), flush=True)
    ok = True
    bridge = None
    win = None
    try:
        settings = Settings()
        settings.update("demo", {"think_seconds": 0.01, "stream_seconds": 0.04})
        styles.set_theme("dark")
        app.setStyleSheet(styles.stylesheet())
        bridge = QtBridge(settings)
        win = MainWindow(bridge, settings)
        win.dialog_sink = []
        win.show()

        def pump(cond=lambda: False, timeout: float = 0.3) -> bool:
            end = time.time() + timeout
            while time.time() < end:
                app.processEvents()
                if cond():
                    return True
                time.sleep(0.02)
            return bool(cond())

        pump(timeout=0.5)
        ok &= _step(report, "main window created", True, f"{type(win).__name__}")

        for ev in _sample_events():
            win.on_event(ev)
        pump()
        ok &= _step(report, "all event types handled", True, f"{len(_sample_events())} events")

        from .audio_wizard import AudioWizard
        from .diagnostics_dialog import DiagnosticsDialog
        from .runtime_dialog import RuntimeDialog
        from .sessions_dialog import SessionsDialog
        from .settings_dialog import SettingsDialog
        dialogs = [SettingsDialog(win, settings, bridge.controller, bridge, "providers", "gemini"),
                   DiagnosticsDialog(win, bridge, "host", "Cameron"), SessionsDialog(win, bridge),
                   AudioWizard(win, settings, bridge), RuntimeDialog(win, bridge)]
        for d in dialogs:
            d.show()
        pump(timeout=0.6)
        for d in dialogs:
            d.close()
        win.show_control_bar({"x": 0, "y": 0, "width": 420, "height": 520})
        win.toggle_theme()
        pump()
        win.toggle_theme()
        pump()
        ok &= _step(report, "dialogs, compact control bar, theme switch", True, f"{len(dialogs)} dialogs")

        # demo conversation through the bridge and the engine thread
        win.monitor.clear_all()
        settings.update("conversation", {"transfer_mode": "automatic", "max_rounds": 2, "delay_seconds": 0,
                                         "max_wait_seconds": 20, "topic": "gui self-test"})
        settings.set("limits.min_interval_seconds", 0)
        win.session_panel.load()
        win.apply_demo(True)
        win.start()
        done = pump(lambda: win.state == "COMPLETED", 40)
        transcript = bridge.runner.run_sync(bridge.controller.get_transcript())
        n = len(transcript.responses()) if transcript else 0
        ok &= _step(report, "demo conversation via GUI", done and n == 4, f"state {win.state}, {n} responses")
        out = Path(os.environ.get("EMERGENCE_LAB_HOME", ".")) / "gui-selftest-demo.html"
        if transcript:
            bridge.runner.run_sync(bridge.controller.export(str(out), "html"))
        ok &= _step(report, "HTML export labelled as simulated",
                    out.exists() and "SIMULATED" in out.read_text(encoding="utf-8"), str(out))

        # clipboard conversation driven through the panel handlers
        win.new_session()
        pump(timeout=0.4)
        win.apply_demo(False)
        settings.update("conversation", {"transfer_mode": "clipboard", "max_rounds": 1})
        win.session_panel.load()
        win.start()
        replies = iter(["Cameron says hello in a distinct way", "Gem answers with different words entirely"])
        clip_ok = True
        coord = bridge.controller.coordinator
        for _ in range(4):
            if not pump(lambda: bool(coord.pending()) and win.clip_panel.request_id != "", 8):
                clip_ok = False
                break
            req = coord.pending()[0]
            if req.action == "paste":
                win.clip_panel.mark_sent.emit(req.request_id, req.text)
            else:
                win._accept_import(req.request_id, next(replies), req.role)
            pump(lambda: not any(r.request_id == req.request_id for r in coord.pending()), 8)
        clip_ok &= pump(lambda: win.state == "COMPLETED", 15)
        ok &= _step(report, "clipboard conversation via GUI panels", clip_ok, f"state {win.state}")

        # human intervention + emergency stop
        win.new_session()
        pump(timeout=0.4)
        settings.update("conversation", {"max_rounds": 3})
        win.session_panel.load()
        win.start()
        human_ok = pump(lambda: bool(coord.pending()), 8)
        win.human()
        human_ok &= pump(lambda: win.state == "HUMAN_INTERVENTION", 8)
        human_state = win.state
        win.emergency()
        stop_ok = pump(lambda: win.state == "STOPPED", 8) and not bridge.controller.gate.armed
        ok &= _step(report, "human intervention", human_ok, human_state)
        ok &= _step(report, "emergency stop blocks submissions", stop_ok, win.state)
        report["collected_warnings"] = list(win.dialog_sink)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        import traceback
        ok = _step(report, "exception", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}") and False
    finally:
        try:
            if win is not None:
                if stub:
                    from PySide6.QtCore import QObject
                    win.closeEvent(QObject())
                else:
                    win.close()
            elif bridge is not None:
                bridge.shutdown()
            _step(report, "shutdown", True)
        except Exception as exc:  # noqa: BLE001
            ok = _step(report, "shutdown", False, f"{type(exc).__name__}: {exc}") and False
    report["passed"] = bool(ok)
    label = "STRUCTURAL STUB – no rendering" if stub else f"REAL QT {report['qt_version']}, {report['qt_platform']}"
    print(f"GUI SELF-TEST ({label}) " + ("PASSED" if ok else "FAILED"), flush=True)
    write_report(report_path, report)
    return 0 if ok else 1

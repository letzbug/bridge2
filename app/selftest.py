"""Built-in self-tests (also used by the Windows CI on the frozen executable).

    EmergenceLab-console.exe --self-check         core: config, providers, demo run, exports
    EmergenceLab-console.exe --browser-selftest   managed Firefox + bundled Playwright driver against the
                                                  local mock chat page (needs the optional runtime)
    EmergenceLab.exe --gui-selftest               see ui/selftest.py

Self-tests never contact an AI provider and never use real accounts. GUI and browser
self-tests run in a temporary data directory unless --data-dir is given.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import APP_FULL_NAME, __version__, paths


def write_report(path: str | None, report: dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def base_report(kind: str) -> dict[str, Any]:
    return {"kind": kind, "app": APP_FULL_NAME, "version": __version__, "frozen": paths.FROZEN,
            "python": sys.version.split()[0], "platform": platform.platform(),
            "install_dir": str(paths.INSTALL_DIR), "resource_dir": str(paths.RESOURCE_DIR),
            "data_dir": str(paths.data_dir()), "data_location": paths.data_location_description(),
            "data_outside_install_dir": not paths.is_inside(paths.data_dir(), paths.INSTALL_DIR) or not paths.FROZEN,
            "steps": [], "passed": False}


def _step(report: dict[str, Any], name: str, ok: bool, detail: str = "") -> bool:
    report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" – {detail}" if detail else ""), flush=True)
    return bool(ok)


def self_check(report_path: str | None = None) -> int:
    """Core check without GUI, browsers, accounts or network."""
    from adapters.demo import DemoAdapter
    from adapters.registry import ProviderRegistry
    from audio.device_manager import audio_available
    from audio.stt_engine import stt_available
    from research.export import FORMATS, export_transcript

    from .engine import ConversationConfig, ConversationEngine, Participant, Role, TransferMode
    from .events import EventBus

    report = base_report("self-check")
    print(f"{APP_FULL_NAME} {__version__} – self-check ({'portable build' if paths.FROZEN else 'source'})")
    ok = True
    ok &= _step(report, "resources", (paths.CONFIG_DIR / "providers.json").is_file()
                and (paths.ASSETS_DIR / "mock_chat.html").is_file(), str(paths.RESOURCE_DIR))
    reg = ProviderRegistry(user_path=Path(tempfile.gettempdir()) / "el-selfcheck-none.json")
    ok &= _step(report, "provider registry", len(reg.ids()) >= 9, ", ".join(reg.ids()))
    ok &= _step(report, "data directory outside application folder", report["data_outside_install_dir"],
                str(paths.data_dir()))

    async def demo() -> ConversationEngine:
        host = DemoAdapter("host", "Cameron (simulated)", "self-check", think_seconds=0.01, stream_seconds=0.02)
        guest = DemoAdapter("guest", "Guest (simulated)", "self-check", think_seconds=0.01, stream_seconds=0.02)
        cfg = ConversationConfig(session_name="self-check", topic="self-check", max_rounds=2, demo=True,
                                 transfer_mode=TransferMode.AUTOMATIC, min_interval_seconds=0, max_wait_seconds=10)
        engine = ConversationEngine(Participant(Role.HOST, host.participant_name, "DEMO", host),
                                    Participant(Role.GUEST, guest.participant_name, "DEMO", guest), cfg, bus=EventBus())
        await engine.start()
        await engine.wait_finished(20)
        return engine

    engine = asyncio.run(demo())
    ok &= _step(report, "demo conversation", engine.state.value == "COMPLETED",
                f"{engine.state.value}, {len(engine.transcript.responses())} simulated responses")
    for fmt in FORMATS:
        out = export_transcript(engine.transcript, fmt)
        ok &= _step(report, f"export {fmt}", "SIMULATED" in out or fmt == "csv", f"{len(out)} chars")
    modules = {}
    for mod in ("PySide6", "playwright"):
        try:
            __import__(mod)
            modules[mod] = True
        except Exception:  # noqa: BLE001
            modules[mod] = False
        print(f"  {mod}: {'available' if modules[mod] else 'NOT available'}")
    from browser import runtime
    rt = runtime.status()
    report.update({"modules": modules, "browser_runtime": rt, "audio_available": audio_available()[0],
                   "stt_available": stt_available()[0]})
    print(f"  Playwright Firefox runtime (optional): {'installed' if rt['firefox_installed'] else 'not installed'}"
          f" – {rt['path']}")
    print(f"  optional audio: {'available' if report['audio_available'] else 'not included'} · "
          f"local transcription: {'available' if report['stt_available'] else 'not included'}")
    report["passed"] = bool(ok)
    print("SELF-CHECK " + ("PASSED" if ok else "FAILED"), flush=True)
    write_report(report_path, report)
    return 0 if ok else 1


async def _browser_selftest(report: dict[str, Any]) -> bool:
    from browser import runtime

    from .controller import BridgeController
    from .engine import TransferMode
    from .events import EventBus
    from .settings import Settings

    if not _step(report, "Playwright package", runtime.playwright_available()[0], runtime.playwright_available()[1]):
        return False
    if not _step(report, "Playwright Firefox runtime installed", runtime.firefox_installed(), str(runtime.browsers_path())):
        return False
    settings = Settings()
    settings.set("browser.pipeline_test", True)
    settings.set("window.apply_layout_on_open", False)
    for role in ("host", "guest"):
        settings.set(f"{role}.browser_backend", "managed")
    settings.update("conversation", {"transfer_mode": TransferMode.AUTOMATIC.value, "max_rounds": 2,
                                     "delay_seconds": 0, "max_wait_seconds": 45, "topic": "browser self-test"})
    settings.set("limits.min_interval_seconds", 0)
    ctrl = BridgeController(settings, EventBus())
    ok = True
    try:
        for role in ("host", "guest"):
            await ctrl.open_browser(role)
            ok &= _step(report, f"managed Firefox opened ({role}, dedicated profile)", ctrl.browsers.is_open(role),
                        str(paths.managed_profile_dir(role, "mock")))
        for role in ("host", "guest"):
            await asyncio.sleep(1.0)
            rep = await ctrl.diagnose(role)
            detail = ", ".join(f"{i.key}={i.status}" for i in rep.items)
            ok &= _step(report, f"adapter diagnostics on mock page ({role})", rep.passed, detail)
        if not ok:
            return False
        started = time.monotonic()
        await ctrl.start_conversation()
        await ctrl.engine.wait_finished(120)
        responses = ctrl.engine.transcript.responses()
        ok &= _step(report, "automated conversation between two mock pages",
                    ctrl.engine.state.value == "COMPLETED" and len(responses) == 4,
                    f"{ctrl.engine.state.value}, {len(responses)} responses, {time.monotonic() - started:.1f}s")
        ok &= _step(report, "extracted text", all(r.original_text.startswith("Mock reply #") for r in responses),
                    responses[0].original_text[:60] if responses else "")
    finally:
        await ctrl.shutdown()
    return bool(ok)


def browser_selftest(report_path: str | None = None) -> int:
    report = base_report("browser-selftest")
    print(f"{APP_FULL_NAME} {__version__} – browser self-test (local mock page, no provider contact)")
    try:
        report["passed"] = asyncio.run(asyncio.wait_for(_browser_selftest(report), 300))
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        _step(report, "exception", False, f"{type(exc).__name__}: {exc}")
        report["passed"] = False
    print("BROWSER SELF-TEST " + ("PASSED" if report["passed"] else "FAILED"), flush=True)
    write_report(report_path, report)
    return 0 if report["passed"] else 1


def install_browser(report_path: str | None = None) -> int:
    from browser import runtime
    report = base_report("install-browser")
    try:
        rc = runtime.install_firefox(lambda line: print(line, flush=True))
    except Exception as exc:  # noqa: BLE001
        print(f"Installation failed: {exc}", flush=True)
        rc = 1
    report["passed"] = rc == 0 and runtime.firefox_installed()
    report["browser_runtime"] = runtime.status()
    write_report(report_path, report)
    return 0 if report["passed"] else 1

"""Application controller (Qt-independent; all async methods run in the engine loop thread).

Owns settings, provider registry, browser sessions, the clipboard coordinator,
the audio manager, the session store and the current conversation engine. It
decides which adapter each participant gets and enforces the operator-only
controls: automation permissions, diagnostics before automatic mode, emergency stop.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.base import BaseProviderAdapter, DiagnosticReport
from adapters.clipboard import ClipboardAdapter
from adapters.demo import DemoAdapter
from adapters.errors import AdapterError
from adapters.registry import ProviderConfig, ProviderRegistry, adapter_class_for
from browser.browser_manager import BrowserManager
from browser.window_manager import Geometry
from research.export import export_to_file
from research.session_manager import SessionRecorder, SessionStore
from research.transcript import Transcript

from . import paths
from .clipboard_workflow import ClipboardCoordinator
from .engine import ConversationConfig, ConversationEngine, Participant, Role, TransferMode
from .events import EventBus, EventType
from .gate import SendGate
from .settings import Settings
from .state_machine import ConversationState

log = logging.getLogger(__name__)


class StartError(RuntimeError):
    """A readable reason why an operator action cannot be performed."""


class BridgeController:
    def __init__(self, settings: Settings, bus: EventBus, registry: ProviderRegistry | None = None,
                 store: SessionStore | None = None) -> None:
        from audio.audio_manager import AudioManager, AudioSettings

        self.settings = settings
        self.bus = bus
        self.registry = registry or ProviderRegistry()
        self.gate = SendGate()
        self.coordinator = ClipboardCoordinator(bus)
        self.browsers = BrowserManager(bus, settings.get("browser.firefox_path", ""))
        self.store = store
        self.recorder = SessionRecorder(bus, None)
        self.audio = AudioManager(bus, AudioSettings.from_dict(settings.get("audio", {})))
        self.engine: ConversationEngine | None = None
        self.last_transcript: Transcript | None = None
        self.diagnostics_passed: dict[str, bool] = {}
        bus.subscribe(self._on_event)

    # =========================================================================
    # participants & providers
    # =========================================================================
    @property
    def demo(self) -> bool:
        return bool(self.settings.get("demo_mode", False))

    def provider_id(self, role: str) -> str:
        if self.settings.get("browser.pipeline_test", False):
            return "mock"
        return "chatgpt" if role == "host" else self.settings.get("guest.provider", "gemini")

    def provider(self, role: str) -> ProviderConfig:
        return self.registry.get(self.provider_id(role))

    def name(self, role: str) -> str:
        if role == "host":
            return self.settings.get("host.name") or "Cameron"
        return self.settings.get("guest.name") or self.provider("guest").label

    def backend(self, role: str) -> str:
        return self.settings.get(f"{role}.browser_backend", "managed")

    def url(self, role: str) -> str:
        cfg = self.provider(role)
        url = cfg.url
        if role == "guest" and cfg.url_editable:
            url = (self.settings.get("guest.url") or "").strip() or cfg.url
        if self.settings.get("browser.reopen_last_url", False):
            last = (self.settings.get("browser.last_urls", {}) or {}).get(f"{role}-{cfg.id}")
            if last:
                url = last
        return paths.resolve_app_url(url) if url else ""

    def automation_allowed(self, role: str) -> tuple[bool, str]:
        cfg = self.provider(role)
        if cfg.automation_policy == "allowed" or cfg.kind == "audio":
            return True, ""
        if (self.settings.get("automation_acknowledged", {}) or {}).get(cfg.id):
            return True, ""
        return False, (f"Automated browser interaction with {cfg.label} is not enabled. "
                       f"{cfg.automation.get('note', '')} After reviewing the provider's terms you can enable it "
                       "under Settings → Providers, or use the Clipboard transfer mode.")

    def participant_summary(self, role: str) -> dict[str, Any]:
        cfg = self.provider(role)
        allowed, _ = self.automation_allowed(role)
        return {"role": role, "name": self.name(role), "provider": cfg.label, "provider_id": cfg.id,
                "backend": self.backend(role), "validated": cfg.validated, "kind": cfg.kind,
                "automation_allowed": allowed, "url": self.url(role),
                "validation": cfg.validation.get("status", "unvalidated")}

    # =========================================================================
    # browsers
    # =========================================================================
    async def open_browser(self, role: str, geometry: dict[str, int] | None = None) -> None:
        cfg = self.provider(role)
        url = self.url(role)
        backend = self.backend(role)
        if cfg.kind == "browser" and not url and backend != "none":
            raise StartError(f"Enter the website URL for {self.name(role)} in the guest panel first.")
        try:
            await self.browsers.open(role, cfg.id, url, backend, cfg.host_patterns, Geometry.from_dict(geometry),
                                     apply_layout=bool(self.settings.get("window.apply_layout_on_open", True)))
        except AdapterError as exc:
            raise StartError(str(exc)) from exc
        self.diagnostics_passed.pop(role, None)
        if backend == "managed" and cfg.kind == "browser":
            asyncio.get_running_loop().call_later(4.0, lambda: asyncio.ensure_future(self.refresh_auth(role)))

    async def open_both(self, layout: dict[str, dict[str, int]] | None = None) -> None:
        errors = []
        for role in ("host", "guest"):
            try:
                await self.open_browser(role, (layout or {}).get(role))
            except StartError as exc:
                errors.append(f"{self.name(role)}: {exc}")
        if errors:
            raise StartError("\n".join(errors))

    async def focus(self, role: str) -> bool:
        return await self.browsers.focus(role)

    async def close_browser(self, role: str) -> None:
        await self.browsers.close(role)

    def _selector_adapter(self, role: str):
        cfg = self.provider(role)
        return adapter_class_for(cfg.id)(cfg, self.browsers.page_getter(role), self.name(role))

    async def diagnose(self, role: str) -> DiagnosticReport:
        cfg = self.provider(role)
        if cfg.kind != "browser":
            return DiagnosticReport(cfg.id, notes=["Audio companion: use the audio setup wizard."], passed=False)
        allowed, reason = self.automation_allowed(role)
        if not allowed:
            return DiagnosticReport(cfg.id, notes=[
                "Diagnostics read the page programmatically, which is a form of automation. " + reason])
        if self.backend(role) != "managed" or not self.browsers.is_open(role):
            return DiagnosticReport(cfg.id, notes=[
                "Diagnostics inspect the page through the Playwright-managed browser. Open it with the "
                "'Managed Firefox' backend first. (Standard Firefox windows are never inspected or automated.)"])
        report = await self._selector_adapter(role).diagnose()
        self.diagnostics_passed[role] = report.passed
        self.bus.emit(EventType.PARTICIPANT, role=role, field="diagnostics", value="passed" if report.passed else "failed")
        self.bus.emit(EventType.PARTICIPANT, role=role, field="auth", value=report.auth)
        return report

    async def highlight(self, role: str, key: str) -> int:
        if not self.browsers.is_open(role) or self.backend(role) != "managed" or not self.automation_allowed(role)[0]:
            return 0
        return await self._selector_adapter(role).highlight(key)

    async def refresh_auth(self, role: str) -> str:
        cfg = self.provider(role)
        if cfg.kind != "browser" or self.backend(role) != "managed" or not self.browsers.is_open(role) \
                or not self.automation_allowed(role)[0]:
            return "unknown"
        try:
            state = await self._selector_adapter(role).check_auth()
        except AdapterError:
            state = "unknown"
        self.bus.emit(EventType.PARTICIPANT, role=role, field="auth", value=state)
        return state

    async def fetch_latest_response(self, role: str) -> str | None:
        if not self.browsers.is_open(role) or self.backend(role) != "managed":
            return None
        allowed, reason = self.automation_allowed(role)
        if not allowed:
            raise StartError(reason)
        return await self._selector_adapter(role).get_latest_response()

    # =========================================================================
    # conversation
    # =========================================================================
    def build_config(self) -> ConversationConfig:
        s = self.settings
        c, t, lim, r = s.get("conversation", {}), s.get("templates", {}), s.get("limits", {}), s.get("research", {})
        user_reported = {k: r.get(k) for k in ("conversation_context", "memory_setting") if r.get(k)}
        return ConversationConfig(
            session_name=(c.get("session_name") or "").strip() or f"Session {datetime.now():%Y-%m-%d %H:%M}",
            topic=c.get("topic", ""), research_question=c.get("research_question", ""),
            initial_prompt=c.get("initial_prompt", ""), first_speaker=Role(c.get("first_speaker", "host")),
            max_rounds=int(c.get("max_rounds", 10)), delay_seconds=float(c.get("delay_seconds", 0)),
            max_wait_seconds=float(c.get("max_wait_seconds", 180)),
            transfer_mode=TransferMode(c.get("transfer_mode", "manual")), attribution=bool(c.get("attribution", True)),
            transfer_template=t.get("transfer", "Message from [speaker]:\n\n[original_message]"),
            human_template=t.get("human", "[original_message]"), human_name=t.get("human_name", "Human researcher"),
            record_transcript=bool(c.get("record_transcript", True)),
            max_message_chars=int(lim.get("max_message_chars", 20000)),
            min_interval_seconds=float(lim.get("min_interval_seconds", 2)),
            max_messages_per_hour=int(lim.get("max_messages_per_hour", 60)),
            near_duplicate_threshold=float(lim.get("near_duplicate_threshold", 0.85)),
            demo=self.demo, notes=r.get("notes", ""), experiment=r.get("experiment", ""),
            condition=r.get("condition", ""), user_reported=user_reported)

    def build_adapter(self, role: str, config: ConversationConfig) -> tuple[BaseProviderAdapter, str]:
        cfg = self.provider(role)
        name = self.name(role)
        if config.demo:
            scenario = self.settings.get("demo.scenario", "normal")
            return DemoAdapter(role, f"{name} (simulated)", config.topic, scenario,
                               think_seconds=float(self.settings.get("demo.think_seconds", 0.8)),
                               stream_seconds=float(self.settings.get("demo.stream_seconds", 1.6))), "DEMO simulator"
        if cfg.kind == "audio":
            from audio.companion_adapter import AudioCompanionAdapter
            from audio.device_manager import audio_available
            ok, msg = audio_available()
            if not ok:
                raise StartError(msg)
            from audio.audio_manager import AudioSettings
            self.audio.settings = AudioSettings.from_dict(self.settings.get("audio", {}))
            return AudioCompanionAdapter(role, name, self.audio), f"{cfg.label} · audio"
        if config.transfer_mode is TransferMode.CLIPBOARD or self.backend(role) in ("standard", "none"):
            return ClipboardAdapter(role, name, cfg.label, self.coordinator), f"{cfg.label} · clipboard"
        allowed, reason = self.automation_allowed(role)
        if not allowed:
            raise StartError(reason)
        if not self.browsers.is_open(role):
            raise StartError(f"{name}'s browser is not open. Click 'Open browser', log in manually, then start.")
        if config.transfer_mode is TransferMode.AUTOMATIC and not self.diagnostics_passed.get(role):
            raise StartError(f"Automatic transfer needs a passed adapter diagnostic for {name} in this session. "
                             "Click 'Diagnose' first, or use manual confirmation.")
        return self._selector_adapter(role), cfg.label

    async def start_conversation(self) -> None:
        if self.engine is not None and not self.engine.sm.is_terminal:
            raise StartError("A conversation is already running. Stop it before starting a new one.")
        config = self.build_config()
        host_adapter, host_label = self.build_adapter("host", config)
        guest_adapter, guest_label = self.build_adapter("guest", config)
        participants = []
        for role, adapter, label in (("host", host_adapter, host_label), ("guest", guest_adapter, guest_label)):
            participants.append(Participant(Role(role), adapter.participant_name, label, adapter,
                                            provider_id=self.provider_id(role),
                                            model_name=self.settings.get(f"{role}.model_name", "")))
        store = self.ensure_store() if config.record_transcript else None
        self.recorder.store, self.recorder.enabled = store, store is not None
        self.engine = ConversationEngine(participants[0], participants[1], config, bus=self.bus, gate=self.gate)
        await self.engine.start()

    def ensure_store(self) -> SessionStore | None:
        if not self.settings.get("research.recording_enabled", True):
            return None
        if self.store is None:
            self.store = SessionStore(paths.sessions_db_path())
        return self.store

    # --- operator controls (pass-through) ---------------------------------------------------
    def _engine(self) -> ConversationEngine | None:
        return self.engine

    async def pause(self) -> None:
        if self.engine:
            self.engine.pause()

    async def resume(self) -> None:
        if self.engine:
            await self.engine.resume()

    async def stop(self) -> None:
        if self.engine:
            await self.engine.stop()

    async def next_turn(self) -> None:
        if self.engine:
            await self.engine.next_turn()

    async def confirm(self, text: str | None, alternative: int = 0) -> bool:
        return bool(self.engine and self.engine.confirm(text, alternative))

    async def skip(self) -> bool:
        return bool(self.engine and self.engine.skip())

    async def verify(self, submitted: bool) -> bool:
        return bool(self.engine and self.engine.resolve_verification(submitted))

    async def human_begin(self) -> bool:
        return bool(self.engine and self.engine.begin_human_intervention())

    async def human_send(self, target: str, text: str) -> bool:
        return bool(self.engine and await self.engine.human_send(target, text))

    async def human_resume(self) -> None:
        if self.engine:
            self.engine.resume_previous()

    async def cancel_generation(self, role: str) -> bool:
        return bool(self.engine and await self.engine.cancel_generation(role))

    async def clipboard_resolve(self, request_id: str, value: Any) -> bool:
        return self.coordinator.resolve(request_id, value)

    def emergency_stop_threadsafe(self) -> None:
        """Called directly from the GUI thread: closes the gate immediately, then stops the engine."""
        self.gate.disarm("emergency stop")
        try:
            import sounddevice as sd  # stop any TTS playback in progress
            sd.stop()
        except Exception:  # noqa: BLE001 - audio is optional
            pass
        if self.engine is not None:
            self.engine.emergency_stop_threadsafe()

    async def new_session(self) -> None:
        if self.engine is not None and not self.engine.sm.is_terminal:
            raise StartError("Stop the current conversation before starting a new session.")
        if self.engine is not None:
            self.last_transcript = self.engine.transcript_copy()
        self.engine = None
        self.bus.emit(EventType.STATE, state=ConversationState.IDLE.value, previous="", reason="new session",
                      hold=None)

    async def get_transcript(self) -> Transcript | None:
        if self.engine is not None:
            return self.engine.transcript_copy()
        return self.last_transcript

    async def export(self, path: str, fmt: str | None = None, transcript: Transcript | None = None) -> str:
        t = transcript or await self.get_transcript()
        if t is None or not t.entries:
            raise StartError("There is no transcript to export yet.")
        return str(export_to_file(t, Path(path), fmt))

    # --- research data ------------------------------------------------------------------------
    async def list_sessions(self) -> list[dict[str, Any]]:
        store = self.ensure_store() if self.settings.get("research.recording_enabled", True) else self.store
        return store.list_sessions() if store else []

    async def load_session(self, session_id: str) -> Transcript | None:
        store = self.store or self.ensure_store()
        return store.load(session_id) if store else None

    async def delete_session(self, session_id: str) -> None:
        if self.store:
            self.store.delete(session_id)

    async def delete_all_research_data(self) -> None:
        store = self.store or (SessionStore(paths.sessions_db_path()) if paths.sessions_db_path().exists() else None)
        if store:
            store.delete_all()
            self.store = store
        exports = paths.exports_dir()
        if exports.exists():
            for p in exports.iterdir():
                if p.is_file():
                    p.unlink()
        self.last_transcript = None

    async def delete_browser_profiles(self) -> None:
        if any(self.browsers.is_open(r) for r in ("host", "guest")):
            raise StartError("Close both browser windows before deleting the dedicated profiles.")
        target = paths.profiles_dir()
        if target.exists():
            shutil.rmtree(target)

    # --- optional Playwright browser runtime ---------------------------------------------------------
    def runtime_status(self) -> dict[str, Any]:
        from browser import runtime
        return runtime.status()

    async def install_browser_runtime(self) -> int:
        """Explicit operator action: download Playwright's Firefox build (progress goes to the log)."""
        from browser import runtime

        loop = asyncio.get_running_loop()

        def line(text: str) -> None:
            loop.call_soon_threadsafe(lambda: self.bus.emit(EventType.LOG, level="info", message=text,
                                                            source="runtime"))
        rc = await asyncio.to_thread(runtime.install_firefox, line)
        if rc != 0:
            raise StartError(f"The browser runtime could not be installed (exit code {rc}). See the output above.")
        return rc

    async def remove_browser_runtime(self) -> int:
        from browser import runtime
        if any(self.browsers.backend_of(r) == "managed" and self.browsers.is_open(r) for r in ("host", "guest")):
            raise StartError("Close the managed browser windows first.")
        try:
            return await asyncio.to_thread(runtime.remove_firefox)
        except RuntimeError as exc:
            raise StartError(str(exc)) from exc

    # --- lifecycle ------------------------------------------------------------------------------
    async def _remember_urls(self) -> None:
        last = self.settings.get("browser.last_urls", {}) or {}
        for role in ("host", "guest"):
            if self.browsers.backend_of(role) == "managed":
                url = await self.browsers.current_url(role)
                if url.startswith("http"):
                    last[f"{role}-{self.provider_id(role)}"] = url
        self.settings.set("browser.last_urls", last)
        self.settings.save()

    def _on_event(self, ev) -> None:
        if ev.type == EventType.SESSION_ENDED:
            try:
                asyncio.get_running_loop()
                asyncio.ensure_future(self._remember_urls())
            except RuntimeError:
                pass

    async def shutdown(self) -> None:
        if self.engine is not None and not self.engine.sm.is_terminal:
            await self.engine.stop("Application closed")
        try:
            await self._remember_urls()
        except Exception:  # noqa: BLE001
            log.exception("could not remember URLs")
        await self.browsers.shutdown()
        if self.store is not None:
            self.store.close()

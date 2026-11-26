"""Main research dashboard."""

from __future__ import annotations

import base64
import time
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from app import APP_NAME, APP_SUBTITLE, BRANDING, __version__, paths
from app.events import Event, EventType
from app.settings import Settings
from browser.window_manager import Geometry, side_by_side
from research.export import FORMATS

from . import icons, styles
from .action_panels import ClipboardPanel, ConfirmPanel, HumanPanel, VerifyPanel
from .participant_card import ParticipantCard
from .qt_bridge import QtBridge
from .session_panel import SessionPanel
from .transcript_view import TranscriptView
from .widgets import Banner, Card, repolish, spaced_font

STATE_TONE = {
    "IDLE": "", "CONNECTING": "active", "READY": "active", "WAITING_FOR_HOST": "active",
    "WAITING_FOR_GUEST": "active", "WAITING_FOR_CONFIRMATION": "warning", "TRANSFERRING": "active",
    "PAUSED": "warning", "HUMAN_INTERVENTION": "warning", "ERROR": "error", "STOPPED": "", "COMPLETED": "ok",
}
STATE_TEXT = {
    "IDLE": "Idle", "CONNECTING": "Connecting", "READY": "Ready", "WAITING_FOR_HOST": "Waiting for host",
    "WAITING_FOR_GUEST": "Waiting for guest", "WAITING_FOR_CONFIRMATION": "Waiting for confirmation",
    "TRANSFERRING": "Transferring", "PAUSED": "Paused", "HUMAN_INTERVENTION": "Human intervention",
    "ERROR": "Error", "STOPPED": "Stopped", "COMPLETED": "Completed",
}
RUNNING = {"CONNECTING", "READY", "WAITING_FOR_HOST", "WAITING_FOR_GUEST", "WAITING_FOR_CONFIRMATION",
           "TRANSFERRING", "PAUSED", "HUMAN_INTERVENTION", "ERROR"}
MODE_TEXT = {"manual": "Manual confirmation", "automatic": "Automatic transfer", "clipboard": "Clipboard transfer"}


class MainWindow(QMainWindow):
    def __init__(self, bridge: QtBridge, settings: Settings) -> None:
        super().__init__()
        self.bridge = bridge
        self.settings = settings
        self.ctrl = bridge.controller
        self.registry = self.ctrl.registry
        self.state = "IDLE"
        self.has_entries = False
        self.round_info = (1, 0, int(settings.get("conversation.max_rounds", 10)))
        self.turn = 0
        self.transfer_text = "—"
        self.wait: dict[str, Any] | None = None
        self.pending_confirm = False
        self.control_bar = None
        self._closing = False
        self.dialog_sink: list[tuple[str, str]] | None = None   # set by the self-test: no modal dialogs
        self.setWindowTitle(f"{APP_NAME} – AI Conversation Bridge {__version__}")
        self.setMinimumSize(1100, 720)
        self._build()
        self.bridge.event.connect(self.on_event)
        self._install_shortcuts()
        self._restore_geometry()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.apply_demo(bool(settings.get("demo_mode", False)), save=False)
        self._names_changed()
        self._update_controls()
        if settings.load_error:
            QTimer.singleShot(300, lambda: self._warn("Settings", settings.load_error))
        if self.registry.load_error:
            QTimer.singleShot(400, lambda: self._warn("Provider overrides", "Local provider overrides were ignored: "
                                                      + self.registry.load_error))

    # =========================================================================
    # layout
    # =========================================================================
    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 12, 8, 12)
        ll.setSpacing(10)
        self.host_card = ParticipantCard("host", self.settings, self.registry)
        self.guest_card = ParticipantCard("guest", self.settings, self.registry)
        self.session_panel = SessionPanel(self.settings)
        for w in (self.host_card, self.guest_card, self.session_panel):
            ll.addWidget(w)
        ll.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(410)
        split.addWidget(scroll)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 12, 14, 12)
        rl.setSpacing(8)
        rl.addWidget(self._status_strip())
        self.banner = Banner()
        self.banner_resume = QPushButton("Resume")
        self.banner_human = QPushButton("Human intervention")
        self.banner_stop = QPushButton("Stop")
        for b in (self.banner_resume, self.banner_human, self.banner_stop):
            self.banner.buttons.addWidget(b)
        self.banner_resume.clicked.connect(self.resume)
        self.banner_human.clicked.connect(self.human)
        self.banner_stop.clicked.connect(self.stop)
        rl.addWidget(self.banner)
        self.monitor = TranscriptView()
        rl.addWidget(self.monitor, 3)
        self.confirm_panel = ConfirmPanel()
        self.verify_panel = VerifyPanel()
        self.clip_panel = ClipboardPanel()
        self.human_panel = HumanPanel()
        for p in (self.verify_panel, self.confirm_panel, self.clip_panel, self.human_panel):
            rl.addWidget(p, 2)
        rl.addWidget(self._controls())
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("Flat")
        self.log_toggle.setText("▸  Technical activity log")
        self.log_toggle.setCheckable(True)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setMaximumHeight(170)
        self.log_view.hide()
        self.log_toggle.toggled.connect(self._toggle_log)
        rl.addWidget(self.log_toggle)
        rl.addWidget(self.log_view)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([440, 900])
        outer.addWidget(split, 1)
        outer.addWidget(self._footer())
        self.setCentralWidget(root)
        self._wire()

    def _header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("HeaderBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        self.glyph = QLabel()
        self.glyph.setPixmap(icons.app_glyph(styles.palette()["teal"], 26))
        lay.addWidget(self.glyph)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("AppTitle")
        t.setFont(spaced_font(spacing=1.6, size=12.5, bold=True))
        st = QLabel(APP_SUBTITLE)
        st.setObjectName("AppSubtitle")
        st.setFont(spaced_font(spacing=1.4, size=8))
        titles.addWidget(t)
        titles.addWidget(st)
        lay.addLayout(titles)
        lay.addStretch(1)
        self.demo_badge = QLabel("DEMO MODE · SIMULATED")
        self.demo_badge.setObjectName("Badge")
        self.demo_badge.setProperty("tone", "demo")
        lay.addWidget(self.demo_badge)
        local = QLabel("LOCAL")
        local.setObjectName("Badge")
        local.setToolTip("Local-first: no telemetry, no analytics, no cloud storage.")
        lay.addWidget(local)
        lay.addSpacing(10)
        self.demo_btn = QPushButton("Demo mode")
        self.demo_btn.setCheckable(True)
        lay.addWidget(self.demo_btn)
        self.hdr_buttons = {}
        for key, ic, tip in (("sessions", "sessions", "Research sessions"), ("settings", "settings", "Settings"),
                             ("compact", "compact", "Compact control bar (always on top)"),
                             ("theme", "theme", "Toggle light / dark")):
            b = QToolButton()
            b.setObjectName("Icon")
            b.setIcon(icons.icon(ic))
            b.setToolTip(tip)
            lay.addWidget(b)
            self.hdr_buttons[key] = b
        return bar

    def _status_strip(self) -> QFrame:
        card = Card(name="Panel", margins=10, spacing=4)
        row = QHBoxLayout()
        self.state_badge = QLabel("IDLE")
        self.state_badge.setObjectName("StateBadge")
        row.addWidget(self.state_badge)
        self.round_label = QLabel("ROUND 01 / 10")
        self.round_label.setFont(spaced_font(spacing=1.0, size=8.5, bold=True))
        row.addSpacing(8)
        row.addWidget(self.round_label)
        self.turn_label = QLabel("TURN 0")
        self.turn_label.setObjectName("Muted")
        row.addSpacing(8)
        row.addWidget(self.turn_label)
        row.addStretch(1)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("Muted")
        row.addWidget(self.mode_label)
        card.body.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        card.body.addWidget(self.progress)
        row2 = QHBoxLayout()
        self.transfer_label = QLabel("—")
        self.wait_label = QLabel("")
        self.wait_label.setObjectName("Muted")
        row2.addWidget(self.transfer_label, 1)
        row2.addWidget(self.wait_label)
        card.body.addLayout(row2)
        return card

    def _controls(self) -> QFrame:
        card = Card(name="Panel", margins=8, spacing=6)
        row = QHBoxLayout()
        row.setSpacing(6)

        def btn(text: str, ic: str = "", name: str = "") -> QPushButton:
            b = QPushButton(text)
            if ic:
                b.setIcon(icons.icon(ic))
            if name:
                b.setObjectName(name)
            row.addWidget(b)
            return b

        self.b_open = btn("Open both browsers", "browser")
        self.b_start = btn("Start", "play", "Primary")
        self.b_pause = btn("Pause", "pause")
        self.b_resume = btn("Resume", "play")
        self.b_next = btn("Next turn", "next")
        self.b_human = btn("Human intervention", "human")
        self.b_stop = btn("Stop", "stop")
        row.addStretch(1)
        self.b_export = btn("Export", "export")
        self.b_new = btn("New session", "new")
        self.b_emergency = btn("EMERGENCY STOP", "emergency", "Emergency")
        self.b_emergency.setToolTip("Immediately cancels pending transfers and blocks all automated submissions. "
                                    "Browser windows stay open.")
        card.body.addLayout(row)
        return card

    def _footer(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Footer")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 6)
        b = QLabel(BRANDING)
        b.setObjectName("Muted")
        lay.addWidget(b)
        lay.addStretch(1)
        edition = "Portable" if paths.FROZEN else "Source"
        self.footer_info = QLabel(f"{edition} · data: {paths.data_dir()}")
        self.footer_info.setToolTip(f"Data location: {paths.data_location_description()}. The application folder "
                                    "is never written to.")
        self.footer_info.setObjectName("Faint")
        lay.addWidget(self.footer_info)
        lay.addSpacing(12)
        about = QToolButton()
        about.setObjectName("Flat")
        about.setText("About & privacy")
        about.clicked.connect(self.about)
        lay.addWidget(about)
        v = QLabel(f"v{__version__}")
        v.setObjectName("Muted")
        lay.addWidget(v)
        return bar

    def _wire(self) -> None:
        for card in (self.host_card, self.guest_card):
            card.open_requested.connect(self.open_browser)
            card.focus_requested.connect(self.focus)
            card.diagnose_requested.connect(self.diagnose)
            card.adapter_settings_requested.connect(self.adapter_settings)
            card.changed.connect(self._names_changed)
        self.guest_card.arm_audio.connect(self.arm_audio)
        self.guest_card.audio_setup_requested.connect(self.audio_setup)
        self.b_open.clicked.connect(self.open_both)
        self.b_start.clicked.connect(self.start)
        self.b_pause.clicked.connect(self.pause)
        self.b_resume.clicked.connect(self.resume)
        self.b_next.clicked.connect(self.next_turn)
        self.b_human.clicked.connect(self.human)
        self.b_stop.clicked.connect(self.stop)
        self.b_export.clicked.connect(self.export)
        self.b_new.clicked.connect(self.new_session)
        self.b_emergency.clicked.connect(self.emergency)
        self.demo_btn.toggled.connect(self.apply_demo)
        self.hdr_buttons["sessions"].clicked.connect(self.sessions)
        self.hdr_buttons["settings"].clicked.connect(lambda: self.open_settings())
        self.hdr_buttons["compact"].clicked.connect(lambda: self.show_control_bar())
        self.hdr_buttons["theme"].clicked.connect(self.toggle_theme)
        self.confirm_panel.send.connect(lambda text, alt: self._call(lambda: self.ctrl.confirm(text, alt)))
        self.confirm_panel.skip.connect(lambda: self._call(self.ctrl.skip))
        self.confirm_panel.copy.connect(self._copy_text)
        self.verify_panel.resolved.connect(lambda ok: self._call(lambda: self.ctrl.verify(ok)))
        self.verify_panel.focus.connect(self.focus)
        self.human_panel.send_to.connect(self._human_send)
        self.human_panel.resume_previous.connect(lambda: self._call(self.ctrl.human_resume))
        self.human_panel.cancel_generation.connect(
            lambda role: self._call(lambda: self.ctrl.cancel_generation(role), title="Cancel generation"))
        self.clip_panel.copy.connect(self._copy_text)
        self.clip_panel.mark_sent.connect(lambda rid, text: self._call(lambda: self.ctrl.clipboard_resolve(rid, text)))
        self.clip_panel.import_clipboard.connect(self._import_clipboard)
        self.clip_panel.accept.connect(self._accept_import)
        self.clip_panel.focus.connect(self.focus)

    # =========================================================================
    # helpers
    # =========================================================================
    def _call(self, factory, done=None, title: str = "Action failed") -> None:
        self.bridge.call(factory, on_done=done, on_error=lambda msg: self._warn(title, msg))

    def _warn(self, title: str, message: str) -> None:
        self._log(f"{title}: {message}", "warning")
        if self.dialog_sink is not None:
            self.dialog_sink.append((title, message))
            return
        if "managed Firefox build is not installed" in message:
            ans = QMessageBox.question(self, title, message + "\n\nOpen the browser runtime manager now?")
            if ans == QMessageBox.StandardButton.Yes:
                self.runtime_manager()
            return
        QMessageBox.warning(self, title, message)

    def runtime_manager(self) -> None:
        from .runtime_dialog import RuntimeDialog
        RuntimeDialog(self, self.bridge).exec()
        self.host_card.refresh()
        self.guest_card.refresh()

    def show_startup_notes(self, notes: list[str]) -> None:
        for note in notes:
            self.monitor.add_system(note, "info")
            self._log(note)

    def _log(self, message: str, level: str = "info") -> None:
        prefix = {"warning": "WARN ", "error": "ERROR", "debug": "debug"}.get(level, "info ")
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {prefix}  {message}")

    def _toggle_log(self, on: bool) -> None:
        self.log_view.setVisible(on)
        self.log_toggle.setText(("▾" if on else "▸") + "  Technical activity log")

    def _store_inputs(self) -> None:
        self.host_card.store()
        self.guest_card.store()
        self.session_panel.store()
        self.settings.save()

    def names(self) -> dict[str, str]:
        suffix = " (simulated)" if self.settings.get("demo_mode") else ""
        return {"host": self.ctrl.name("host") + suffix, "guest": self.ctrl.name("guest") + suffix}

    def _names_changed(self) -> None:
        n = self.names()
        self.human_panel.set_names(n["host"], n["guest"])
        self.host_card.refresh()
        self.guest_card.refresh()
        self._sync_bar()

    def _layout(self) -> dict[str, dict[str, int]]:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        geo = side_by_side(Geometry(screen.x(), screen.y(), screen.width(), screen.height()),
                           self.settings.get("window.layout", "with_panel"))
        return {k: v.as_dict() for k, v in geo.items()}

    def _card(self, role: str) -> ParticipantCard:
        return self.host_card if role == "host" else self.guest_card

    # =========================================================================
    # actions
    # =========================================================================
    def open_browser(self, role: str) -> None:
        self._store_inputs()
        layout = self._layout() if self.settings.get("window.apply_layout_on_open", True) else {}
        self._call(lambda: self.ctrl.open_browser(role, layout.get(role)), title="Open browser")

    def open_both(self) -> None:
        self._store_inputs()
        layout = self._layout()

        def done(_):
            if self.settings.get("window.apply_layout_on_open", True):
                self.show_control_bar(layout.get("panel"))
        self._call(lambda: self.ctrl.open_both(layout), done, title="Open browsers")

    def focus(self, role: str) -> None:
        self._call(lambda: self.ctrl.focus(role),
                   lambda ok: None if ok else self._log(f"{self.names()[role]}: no open browser window to focus",
                                                        "warning"))

    def diagnose(self, role: str) -> None:
        from .diagnostics_dialog import DiagnosticsDialog
        self._store_inputs()
        DiagnosticsDialog(self, self.bridge, role, self.names()[role]).show()

    def adapter_settings(self, role: str) -> None:
        self.open_settings("providers", self.ctrl.provider_id(role))

    def open_settings(self, tab: str = "", provider: str = "") -> None:
        from .settings_dialog import SettingsDialog
        self._store_inputs()
        dlg = SettingsDialog(self, self.settings, self.ctrl, self.bridge, tab, provider)
        if dlg.exec():
            self.settings.save()
            self.apply_theme()
            self._install_shortcuts()
            self.host_card.load()
            self.guest_card.load()
            self._names_changed()

    def sessions(self) -> None:
        from .sessions_dialog import SessionsDialog
        SessionsDialog(self, self.bridge).exec()

    def audio_setup(self) -> None:
        from .audio_wizard import AudioWizard
        self._store_inputs()
        AudioWizard(self, self.settings, self.bridge).exec()
        self.settings.save()

    def arm_audio(self, on: bool) -> None:
        self.bridge.runner.call_soon(self.ctrl.audio.authorize, on)
        self._log("Microphone armed by operator" if on else "Microphone disarmed")

    def start(self) -> None:
        self._store_inputs()
        if not self.settings.get("demo_mode") and self.settings.get("conversation.transfer_mode") != "clipboard":
            for role in ("host", "guest"):
                allowed, _ = self.ctrl.automation_allowed(role)
                backend = self.settings.get(f"{role}.browser_backend")
                if not allowed and backend == "managed" and self.ctrl.provider(role).kind == "browser":
                    ans = QMessageBox.question(
                        self, "Automation not enabled",
                        f"Automated interaction with {self.ctrl.provider(role).label} is not enabled.\n\n"
                        f"{self.ctrl.provider(role).automation.get('note', '')}\n\n"
                        "Start this session in Clipboard mode instead (no automation)?")
                    if ans != QMessageBox.StandardButton.Yes:
                        return
                    self.settings.set("conversation.transfer_mode", "clipboard")
                    self.session_panel.load()
                    self.settings.save()
                    break
        self.monitor.clear_all()
        self._call(self.ctrl.start_conversation, title="Cannot start")

    def start_or_resume(self) -> None:
        if self.state in ("PAUSED", "ERROR", "HUMAN_INTERVENTION"):
            self.resume()
        elif self.state not in RUNNING:
            self.start()

    def pause(self) -> None:
        self._call(self.ctrl.pause)

    def resume(self) -> None:
        self._call(self.ctrl.resume)

    def next_turn(self) -> None:
        self._call(self.ctrl.next_turn)

    def human(self) -> None:
        self._call(self.ctrl.human_begin)

    def _human_send(self, target: str, text: str) -> None:
        self._call(lambda: self.ctrl.human_send(target, text),
                   lambda ok: self.human_panel.editor.clear() if ok else None, title="Human intervention")

    def stop(self) -> None:
        self._call(self.ctrl.stop)

    def emergency(self) -> None:
        self.bridge.emergency_stop()          # synchronous gate close
        for p in (self.confirm_panel, self.verify_panel, self.clip_panel, self.human_panel):
            p.hide()
        self._log("EMERGENCY STOP – automated submissions blocked", "error")
        self.monitor.add_system("EMERGENCY STOP by operator – pending transfers cancelled", "error")

    def new_session(self) -> None:
        def done(_):
            self.monitor.clear_all()
            self.has_entries = False
            self.round_info = (1, 0, int(self.settings.get("conversation.max_rounds", 10)))
            self.turn = 0
            self._render_status()
        self._call(self.ctrl.new_session, done, title="New session")

    def export(self) -> None:
        self._call(self.ctrl.get_transcript, self._export_dialog)

    def _export_dialog(self, transcript) -> None:
        if transcript is None or not transcript.entries:
            self._warn("Export", "There is no transcript to export yet.")
            return
        filters = ";;".join(f"{label} (*.{ext})" for ext, label in FORMATS.items())
        from app.security import safe_filename
        default = str(paths.exports_dir() / f"{safe_filename(transcript.meta.title)}.html")
        paths.exports_dir().mkdir(parents=True, exist_ok=True)
        path, chosen = QFileDialog.getSaveFileName(self, "Export transcript", default, filters)
        if not path:
            return
        fmt = next((ext for ext, label in FORMATS.items() if chosen.startswith(label)), None)
        if fmt and not path.lower().endswith("." + fmt):
            path += "." + fmt
        self._call(lambda: self.ctrl.export(path, fmt, transcript),
                   lambda p: self._log(f"Transcript exported to {p}"), title="Export")

    def _copy_text(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._log(f"Copied {len(text)} characters to the clipboard (operator action)")

    def _import_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()      # read only on explicit operator action
        self.clip_panel.set_text(text)
        self._log(f"Imported {len(text)} characters from the clipboard (operator action)")

    def _accept_import(self, rid: str, text: str, speaker: str) -> None:
        if not text.strip():
            self._warn("Clipboard", "The reply is empty. Copy the reply in the browser and import it first.")
            return
        self._call(lambda: self.ctrl.clipboard_resolve(rid, {"text": text, "speaker": speaker}))

    def apply_demo(self, on: bool, save: bool = True) -> None:
        if self.state in RUNNING and save:
            self.demo_btn.blockSignals(True)
            self.demo_btn.setChecked(not on)
            self.demo_btn.blockSignals(False)
            self._warn("Demo mode", "Stop the running conversation before switching demo mode.")
            return
        self.settings.set("demo_mode", on)
        self.demo_btn.blockSignals(True)
        self.demo_btn.setChecked(on)
        self.demo_btn.blockSignals(False)
        self.demo_badge.setVisible(on)
        self.session_panel.set_demo(on)
        if save:
            self.session_panel.store()
            self.settings.save()
        self._names_changed()
        self._render_status()

    def toggle_theme(self) -> None:
        self.settings.set("theme", "light" if styles.theme() == "dark" else "dark")
        self.settings.save()
        self.apply_theme()

    def apply_theme(self) -> None:
        styles.set_theme(self.settings.get("theme", "dark"))
        QApplication.instance().setStyleSheet(styles.stylesheet())
        self.glyph.setPixmap(icons.app_glyph(styles.palette()["teal"], 26))
        self.monitor.render()
        self.host_card.refresh()
        self.guest_card.refresh()
        if self.control_bar is not None:
            self.control_bar.restyle()

    def show_control_bar(self, geometry: dict[str, int] | None = None) -> None:
        from .control_bar import ControlBar
        if self.control_bar is None:
            self.control_bar = ControlBar(self)
            raw = self.settings.get("window.control_bar_geometry", "")
            if raw and not geometry:
                self.control_bar.restoreGeometry(QByteArray(base64.b64decode(raw)))
        if geometry and isinstance(geometry, dict):
            self.control_bar.setGeometry(geometry["x"], geometry["y"], min(geometry["width"], 520),
                                         min(geometry["height"], 560))
        self._sync_bar()
        self.control_bar.show()
        self.control_bar.raise_()

    def about(self) -> None:
        QMessageBox.about(self, "About EMERGENCE LAB", (
            f"<b>{APP_NAME} – AI Conversation Bridge</b> v{__version__}<br>{BRANDING}<br><br>"
            "A local research environment that relays messages between two AI assistants through their native "
            "browser interfaces.<br><br><b>Privacy:</b> no telemetry, no analytics, no cloud storage. Data stays in "
            f"<code>{paths.data_dir()}</code>. Passwords are never requested; you log in manually in the dedicated "
            "browser profiles.<br><br><b>Research note:</b> this tool records observable conversation behaviour. It "
            "cannot establish consciousness, subjective experience or hidden model states."))

    # =========================================================================
    # events
    # =========================================================================
    def on_event(self, ev: Event) -> None:
        t, d = ev.type, ev.data
        if t == EventType.STATE:
            self.state = d["state"]
            if self.state in ("STOPPED", "COMPLETED", "IDLE"):
                for p in (self.confirm_panel, self.verify_panel, self.clip_panel, self.human_panel):
                    p.hide()
                self.wait = None
                self.pending_confirm = False
            if self.state == "COMPLETED":
                self.monitor.add_system("Session completed – round limit reached", "info")
            self._update_controls()
            self._render_status()
        elif t == EventType.SESSION_STARTED:
            meta = d["meta"]
            self.monitor.clear_all()
            self.has_entries = False
            self.monitor.add_system(f"Session “{meta['title']}” started · {MODE_TEXT.get(meta['transfer_mode'], '')}"
                                    + (" · DEMO MODE – simulated participants" if meta.get("demo") else ""),
                                    "warning" if meta.get("demo") else "info")
            self.round_info = (1, 0, meta.get("max_rounds", 10))
        elif t in (EventType.ENTRY_ADDED, EventType.ENTRY_UPDATED):
            e = d["entry"]
            self.monitor.upsert(e)
            self.has_entries = True
            if e.get("kind") == "response" and t == EventType.ENTRY_ADDED:
                card = self._card(e["speaker_role"])
                card.set_status("conversation", f"Responded · turn {e['turn']}", "ok")
            self._update_controls()
        elif t == EventType.ROUND:
            self.round_info = (d["current_round"], d["completed_rounds"], d["max_rounds"])
            self.turn = d["turn"]
            self._render_status()
        elif t == EventType.TRANSFER:
            status = d.get("status")
            dest = d.get("destination_name", "")
            text = {"sending": f"Transferring → {dest}", "sent": f"Transfer completed → {dest}",
                    "uncertain": f"Submission to {dest} uncertain – verification required",
                    "delay": f"Delay before sending to {dest}", "rate_wait": f"Rate limit pause → {dest}",
                    "waiting_idle": f"Waiting for {dest} to finish generating"}.get(status, status)
            self.transfer_text = text
            if status == "sending":
                self._card(d["destination"]).set_status("conversation", "Receiving message", "active")
            self._log(text + (f" ({d['detail']})" if d.get("detail") else ""))
            self._render_status()
        elif t == EventType.WAITING:
            role = d["role"]
            if d.get("active"):
                self.wait = {"role": role, "name": d.get("name"), "start": time.monotonic(),
                             "timeout": d.get("timeout", 0)}
                self._card(role).set_status("conversation", "Generating / waiting for response", "active")
            else:
                self.wait = None
            self._render_status()
        elif t == EventType.ISSUE:
            tone = "error" if d.get("severity") == "error" else "warning"
            self.banner.show_message(d.get("message", ""), tone)
            actions = d.get("actions", [])
            self.banner_resume.setText("Keep waiting" if "keep_waiting" in actions else "Resume")
            self.banner_human.setVisible("human" in actions)
            self.monitor.add_system(d.get("message", ""), tone)
        elif t == EventType.ISSUE_CLEARED:
            self.banner.hide()
        elif t == EventType.CONFIRMATION_REQUIRED:
            if d.get("kind") == "verify":
                self.verify_panel.present(d)
            else:
                self.confirm_panel.present(d)
                self.pending_confirm = True
            self._sync_bar()
        elif t == EventType.CONFIRMATION_CLEARED:
            self.confirm_panel.hide()
            self.verify_panel.hide()
            self.pending_confirm = False
            self._sync_bar()
        elif t == EventType.HUMAN:
            status = d.get("status")
            if status == "open":
                self.human_panel.open(d.get("pending"))
            elif status == "closed":
                self.human_panel.hide()
            elif status in ("waiting_for_pending", "blocked"):
                self.human_panel.set_status(d.get("detail", ""))
                if status == "blocked":
                    self._warn("Human intervention", d.get("detail", ""))
        elif t == EventType.CLIPBOARD_REQUEST:
            self.clip_panel.present(d, self.names())
            self._log(f"Clipboard step: {d['action']} for {d['name']}")
        elif t == EventType.CLIPBOARD_CLEARED:
            if self.clip_panel.request_id == d.get("request_id"):
                self.clip_panel.hide()
        elif t == EventType.PARTICIPANT:
            card = self._card(d["role"])
            field, value = d.get("field"), d.get("value")
            if field == "browser":
                tone = {"open": "ok", "launching": "active", "closed": "idle", "error": "error", "none": "info"}.get(value, "idle")
                text = {"open": "Open", "launching": "Launching…", "closed": "Closed", "error": "Error",
                        "none": "Not managed (clipboard)"}.get(value, value)
                card.set_status("browser", text, tone, d.get("detail", ""))
                if value == "error":
                    self._log(f"{d['role']} browser error: {d.get('detail', '')}", "error")
            elif field == "auth":
                text = {"logged_in": "Logged in (detected)", "login_required": "Login required (detected)",
                        "unknown": "Unknown"}.get(value, value)
                card.set_status("auth", text, {"logged_in": "ok", "login_required": "warning"}.get(value, "idle"))
            elif field == "diagnostics":
                self._log(f"{d['role']} adapter diagnostics {value}")
        elif t == EventType.LOG:
            self._log(d.get("message", ""), d.get("level", "info"))
        elif t == EventType.AUDIO:
            status = d.get("status")
            if status == "recording":
                self.guest_card.set_recording(True)
            elif status in ("recording_stopped", "disarmed"):
                self.guest_card.set_recording(False)
            elif status == "discarded":
                self._log(f"Audio transcript discarded: {d.get('reason', '')}")
            if self.control_bar is not None:
                self.control_bar.set_recording(self.guest_card.rec_badge.isVisible())
        elif t == EventType.SESSION_ENDED:
            self._log(f"Session ended: {d.get('end_state')} – {d.get('reason')}")

    # =========================================================================
    # status rendering
    # =========================================================================
    def _render_status(self) -> None:
        cur, done, mx = self.round_info
        self.state_badge.setText(STATE_TEXT.get(self.state, self.state).upper())
        self.state_badge.setProperty("tone", STATE_TONE.get(self.state, ""))
        repolish(self.state_badge)
        self.round_label.setText(f"ROUND {cur:02d} / {mx:02d}")
        self.progress.setRange(0, max(1, mx))
        self.progress.setValue(done)
        self.turn_label.setText(f"TURN {self.turn}")
        mode = self.settings.get("conversation.transfer_mode", "manual")
        self.mode_label.setText(("DEMO · " if self.settings.get("demo_mode") else "") + MODE_TEXT.get(mode, mode))
        self.transfer_label.setText(self.transfer_text)
        self._tick()
        self._sync_bar()

    def _tick(self) -> None:
        if self.wait:
            el = int(time.monotonic() - self.wait["start"])
            to = int(self.wait.get("timeout") or 0)
            self.wait_label.setText(f"Waiting for {self.wait['name']} · {el // 60:02d}:{el % 60:02d}"
                                    + (f" / {to // 60:02d}:{to % 60:02d}" if to else ""))
        else:
            self.wait_label.setText("")

    def _update_controls(self) -> None:
        st = self.state
        running = st in RUNNING
        self.b_start.setEnabled(not running)
        self.b_pause.setEnabled(st in ("READY", "WAITING_FOR_HOST", "WAITING_FOR_GUEST", "TRANSFERRING",
                                       "WAITING_FOR_CONFIRMATION"))
        self.b_resume.setEnabled(st in ("PAUSED", "ERROR", "HUMAN_INTERVENTION"))
        self.b_next.setEnabled(st in ("PAUSED", "WAITING_FOR_CONFIRMATION"))
        self.b_human.setEnabled(running and st != "HUMAN_INTERVENTION")
        self.b_stop.setEnabled(running)
        self.b_new.setEnabled(not running)
        self.b_export.setEnabled(self.has_entries)
        self.b_emergency.setEnabled(True)
        self.session_panel.setEnabled(not running)
        for card in (self.host_card, self.guest_card):
            for w in (card.provider, card.display_name, card.url, card.backend):
                w.setEnabled(not running and (w is not card.url or card.url.isEnabled()))
        self.demo_btn.setEnabled(not running)
        self._sync_bar()

    def _sync_bar(self) -> None:
        if self.control_bar is None or not hasattr(self, "state_badge"):
            return
        self.control_bar.update_view({
            "state": self.state, "state_text": STATE_TEXT.get(self.state, self.state), "round": self.round_info,
            "names": self.names(), "providers": {r: self.ctrl.provider(r).label for r in ("host", "guest")},
            "topic": self.settings.get("conversation.topic", "") or "—",
            "title": self.settings.get("conversation.session_name", "") or "Research session",
            "mode": MODE_TEXT.get(self.settings.get("conversation.transfer_mode", "manual"), ""),
            "transfer": self.transfer_text, "demo": bool(self.settings.get("demo_mode")),
            "pending_confirm": self.pending_confirm, "running": self.state in RUNNING,
        })

    # =========================================================================
    # shortcuts, geometry, close
    # =========================================================================
    def _install_shortcuts(self) -> None:
        for sc in getattr(self, "_shortcuts", []):
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        actions = {
            "emergency_stop": self.emergency,
            "pause": self.pause,
            "human": self.human,
            "next_turn": self.next_turn,
            "import_clipboard": lambda: self._import_clipboard() if self.clip_panel.isVisible()
            and self.clip_panel.action == "import" else None,
            "copy_outgoing": lambda: self._copy_text(self.clip_panel.editor.toPlainText())
            if self.clip_panel.isVisible() and self.clip_panel.action == "paste" else None,
            "mark_sent": self._shortcut_send,
        }
        for key, fn in actions.items():
            seq = self.settings.get(f"shortcuts.{key}", "")
            if not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)

    def _shortcut_send(self) -> None:
        if self.clip_panel.isVisible() and self.clip_panel.action == "paste":
            self.clip_panel.sent_btn.click()
        elif self.clip_panel.isVisible() and self.clip_panel.action == "import":
            self.clip_panel.accept_btn.click()
        elif self.confirm_panel.isVisible():
            self.confirm_panel.send_btn.click()

    def confirm_from_bar(self) -> None:
        if self.confirm_panel.isVisible():
            self.confirm_panel.send_btn.click()

    def _restore_geometry(self) -> None:
        raw = self.settings.get("window.main_geometry", "")
        if raw:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(raw)))
                return
            except Exception:  # noqa: BLE001
                pass
        self.resize(1360, 860)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.state in RUNNING and not self._closing:
            ans = QMessageBox.question(self, "Quit", "A conversation is still running. Stop it and quit?\n\n"
                                       "Playwright-managed browser windows close with the application; "
                                       "installed-Firefox windows stay open.")
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._closing = True
        try:
            self._store_inputs()
        except Exception:  # noqa: BLE001
            pass
        self.settings.set("window.main_geometry", base64.b64encode(bytes(self.saveGeometry().data())).decode("ascii"))
        if self.control_bar is not None:
            self.settings.set("window.control_bar_geometry",
                              base64.b64encode(bytes(self.control_bar.saveGeometry().data())).decode("ascii"))
            self.control_bar.close()
        self.settings.save()
        self.bridge.shutdown()
        event.accept()

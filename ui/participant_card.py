"""Host and guest cards."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from adapters.registry import GUEST_CHOICES, ProviderRegistry
from app.settings import Settings
from browser import runtime
from browser.browser_manager import BACKENDS

from . import icons, styles
from .widgets import Card, StatusRow, repolish, section_label

BACKEND_SHORT = {"managed": "Managed Firefox", "standard": "Installed Firefox", "none": "No browser"}


class ParticipantCard(Card):
    open_requested = Signal(str)
    focus_requested = Signal(str)
    diagnose_requested = Signal(str)
    adapter_settings_requested = Signal(str)
    audio_setup_requested = Signal()
    arm_audio = Signal(bool)
    changed = Signal()

    def __init__(self, role: str, settings: Settings, registry: ProviderRegistry, parent=None) -> None:
        super().__init__(parent)
        self.role = role
        self.settings = settings
        self.registry = registry
        head = QHBoxLayout()
        head.addWidget(section_label("01 / Host" if role == "host" else "02 / Guest"))
        head.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        head.addWidget(self.badge)
        self.body.addLayout(head)

        ident = QHBoxLayout()
        self.mark = QLabel()
        ident.addWidget(self.mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = QLabel()
        self.name_label.setObjectName("Title")
        self.sub_label = QLabel()
        self.sub_label.setObjectName("Subtitle")
        names.addWidget(self.name_label)
        names.addWidget(self.sub_label)
        ident.addLayout(names, 1)
        self.body.addLayout(ident)

        form = QFormLayout()
        form.setContentsMargins(0, 2, 0, 2)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(5)
        self.provider = QComboBox()
        self.display_name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.mode = QComboBox()
        self.mode.addItem("Text", "text")
        self.mode.addItem("Audio", "audio")
        self.backend = QComboBox()
        for key, text in BACKENDS.items():
            self.backend.addItem(text, key)
        if role == "guest":
            for pid in GUEST_CHOICES:
                self.provider.addItem(registry.get(pid).label, pid)
            form.addRow("Guest", self.provider)
            form.addRow("Display name", self.display_name)
            form.addRow("Website URL", self.url)
            form.addRow("Mode", self.mode)
        form.addRow("Browser", self.backend)
        self.body.addLayout(form)

        self.rows = {k: StatusRow(c) for k, c in (("browser", "Browser"), ("auth", "Authentication"),
                                                    ("connection", "Connection"), ("conversation", "Conversation"))}
        for r in self.rows.values():
            self.body.addWidget(r)

        btns = QHBoxLayout()
        self.open_btn = QPushButton("Open browser")
        self.open_btn.setIcon(icons.icon("browser"))
        self.focus_btn = QPushButton("Focus")
        self.focus_btn.setIcon(icons.icon("focus"))
        self.diag_btn = QPushButton("Diagnose")
        self.diag_btn.setIcon(icons.icon("diagnose"))
        self.adapter_btn = QPushButton("Adapter…")
        for b in (self.open_btn, self.focus_btn, self.diag_btn, self.adapter_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        self.body.addLayout(btns)

        self.audio_row = QHBoxLayout()
        self.arm_btn = QPushButton("Arm microphone")
        self.arm_btn.setCheckable(True)
        self.arm_btn.setIcon(icons.icon("mic"))
        self.rec_badge = QLabel("● REC")
        self.rec_badge.setObjectName("Badge")
        self.rec_badge.setProperty("tone", "rec")
        self.rec_badge.hide()
        self.audio_btn = QPushButton("Audio setup…")
        self.audio_row.addWidget(self.arm_btn)
        self.audio_row.addWidget(self.rec_badge)
        self.audio_row.addWidget(self.audio_btn)
        self.audio_row.addStretch(1)
        self.body.addLayout(self.audio_row)

        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.role))
        self.focus_btn.clicked.connect(lambda: self.focus_requested.emit(self.role))
        self.diag_btn.clicked.connect(lambda: self.diagnose_requested.emit(self.role))
        self.adapter_btn.clicked.connect(lambda: self.adapter_settings_requested.emit(self.role))
        self.audio_btn.clicked.connect(self.audio_setup_requested.emit)
        self.arm_btn.toggled.connect(self._armed)
        self.load()
        self.provider.currentIndexChanged.connect(self._edited)
        self.display_name.editingFinished.connect(self._edited)
        self.url.editingFinished.connect(self._edited)
        self.mode.currentIndexChanged.connect(self._edited)
        self.backend.currentIndexChanged.connect(self._edited)

    # ---------------------------------------------------------------------------------
    def provider_id(self) -> str:
        if self.settings.get("browser.pipeline_test", False):
            return "mock"
        return "chatgpt" if self.role == "host" else (self.provider.currentData() or "gemini")

    def load(self) -> None:
        widgets = (self.provider, self.display_name, self.url, self.mode, self.backend)
        for w in widgets:
            w.blockSignals(True)
        if self.role == "guest":
            idx = self.provider.findData(self.settings.get("guest.provider", "gemini"))
            self.provider.setCurrentIndex(max(0, idx))
            self.display_name.setText(self.settings.get("guest.name", ""))
            self.url.setText(self.settings.get("guest.url", ""))
            self.mode.setCurrentIndex(max(0, self.mode.findData(self.settings.get("guest.mode", "text"))))
        self.backend.setCurrentIndex(max(0, self.backend.findData(self.settings.get(f"{self.role}.browser_backend",
                                                                                    "managed"))))
        for w in widgets:
            w.blockSignals(False)
        self.refresh()

    def store(self) -> None:
        if self.role == "guest":
            pid = self.provider.currentData()
            self.settings.set("guest.provider", pid)
            name = self.display_name.text().strip() or self.registry.get(pid).label
            self.settings.set("guest.name", name)
            self.settings.set("guest.url", self.url.text().strip())
            mode = "audio" if pid == "companion" else self.mode.currentData()
            self.settings.set("guest.mode", mode)
        self.settings.set(f"{self.role}.browser_backend", self.backend.currentData())

    def _edited(self, *_args) -> None:
        if self.role == "guest" and self.sender() is self.provider:
            pid = self.provider.currentData()
            cfg = self.registry.get(pid)
            if not self.display_name.text().strip() or self.display_name.text() in [
                    self.registry.get(p).label for p in GUEST_CHOICES]:
                self.display_name.setText(cfg.label)
        self.store()
        self.refresh()
        self.changed.emit()

    def _armed(self, on: bool) -> None:
        self.arm_btn.setText("Microphone armed" if on else "Arm microphone")
        self.arm_audio.emit(on)

    def refresh(self) -> None:
        pal = styles.palette()
        pid = self.provider_id()
        cfg = self.registry.get(pid)
        name = self.settings.get("host.name", "Cameron") if self.role == "host" else \
            (self.display_name.text().strip() or cfg.label)
        accent = pal["teal"] if self.role == "host" else pal["blue"]
        self.mark.setPixmap(icons.monogram(name[:1], accent, 34))
        self.name_label.setText(name.upper())
        self.sub_label.setText(f"{cfg.label} · {BACKEND_SHORT.get(self.backend.currentData(), '')}")
        status = cfg.validation.get("status", "unvalidated")
        self.badge.setText(status.upper())
        self.badge.setProperty("tone", "ok" if status == "validated" else "")
        repolish(self.badge)
        self.badge.setToolTip(cfg.validation.get("notes", ""))
        is_guest = self.role == "guest"
        self.url.setEnabled(is_guest and cfg.url_editable)
        if is_guest and not cfg.url_editable:
            self.url.setPlaceholderText(cfg.url or "")
        is_audio = cfg.kind == "audio"
        self.mode.setEnabled(False)
        self.mode.setCurrentIndex(1 if is_audio else 0)
        self.arm_btn.setVisible(is_audio)
        self.audio_btn.setVisible(is_audio)
        if not is_audio:
            self.rec_badge.hide()
        self.diag_btn.setEnabled(not is_audio)
        backend = self.backend.currentData()
        allowed = (self.settings.get("automation_acknowledged", {}) or {}).get(pid) or \
            cfg.automation_policy == "allowed"
        if is_audio:
            self.rows["connection"].set("Audio companion (experimental)", "info")
        elif backend != "managed":
            self.rows["connection"].set("Clipboard workflow (no automation)", "info")
        elif cfg.kind == "browser" and not runtime.firefox_installed():
            self.rows["connection"].set("Playwright Firefox runtime not installed → Settings → Browser runtime",
                                        "warning", runtime.missing_runtime_hint())
        elif allowed:
            self.rows["connection"].set("Automated browser adapter", "active")
        else:
            self.rows["connection"].set("Automation not enabled → clipboard or enable in Settings", "warning",
                                        cfg.automation.get("note", ""))

    def set_status(self, key: str, value: str, tone: str = "idle", tooltip: str = "") -> None:
        if key in self.rows:
            self.rows[key].set(value, tone, tooltip)

    def set_recording(self, on: bool) -> None:
        self.rec_badge.setVisible(on)

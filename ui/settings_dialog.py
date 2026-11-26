"""Settings: general, templates & limits, providers (selectors + automation permission), browser, shortcuts."""

from __future__ import annotations

import json
from datetime import date

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from adapters.registry import ProviderConfigError, SELECTOR_KEYS
from app import paths
from app.templates import TemplateError, validate_transfer_template

SHORTCUT_LABELS = {
    "emergency_stop": "Emergency stop", "pause": "Pause", "human": "Human intervention", "next_turn": "Next turn",
    "import_clipboard": "Clipboard: import reply", "copy_outgoing": "Clipboard: copy outgoing text",
    "mark_sent": "Send / confirm pasted",
}


def _form(w: QWidget) -> QFormLayout:
    f = QFormLayout(w)
    f.setContentsMargins(12, 12, 12, 12)
    f.setVerticalSpacing(7)
    return f


class SettingsDialog(QDialog):
    def __init__(self, parent, settings, ctrl, bridge, tab: str = "", provider: str = "") -> None:
        super().__init__(parent)
        self.settings, self.ctrl, self.bridge = settings, ctrl, bridge
        self.setWindowTitle("Settings")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self._general()
        self._templates()
        self._providers()
        self._browser()
        self._shortcuts()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        index = {"general": 0, "templates": 1, "providers": 2, "browser": 3, "shortcuts": 4}.get(tab, 0)
        self.tabs.setCurrentIndex(index)
        if provider:
            i = self.provider.findData(provider)
            if i >= 0:
                self.provider.setCurrentIndex(i)

    # --- general ------------------------------------------------------------------------
    def _general(self) -> None:
        w = QWidget()
        f = _form(w)
        self.theme = QComboBox()
        self.theme.addItem("Dark graphite", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(0 if self.settings.get("theme", "dark") == "dark" else 1)
        self.recording = QCheckBox("Record research sessions locally (SQLite)")
        self.recording.setChecked(bool(self.settings.get("research.recording_enabled", True)))
        f.addRow("Theme", self.theme)
        f.addRow("", self.recording)
        path_row = QHBoxLayout()
        p = QLineEdit(str(paths.data_dir()))
        p.setReadOnly(True)
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir()))))
        path_row.addWidget(p, 1)
        path_row.addWidget(open_btn)
        f.addRow("Local data", path_row)
        del_data = QPushButton("Delete all local research data…")
        del_data.setObjectName("Danger")
        del_data.clicked.connect(self._delete_data)
        del_prof = QPushButton("Delete dedicated browser profiles (logs you out)…")
        del_prof.setObjectName("Danger")
        del_prof.clicked.connect(self._delete_profiles)
        f.addRow("", del_data)
        f.addRow("", del_prof)
        info = QLabel("No telemetry, no analytics, no cloud storage. The only network traffic is what the selected "
                      "AI websites load in their browser windows, plus dependency downloads you start yourself.")
        info.setObjectName("Faint")
        info.setWordWrap(True)
        f.addRow(info)
        self.tabs.addTab(w, "General")

    def _delete_data(self) -> None:
        if QMessageBox.question(self, "Delete research data",
                                "Delete ALL recorded sessions and files in the exports folder? This cannot be undone."
                                ) == QMessageBox.StandardButton.Yes:
            self.bridge.call(self.ctrl.delete_all_research_data,
                             lambda _: QMessageBox.information(self, "Deleted", "All local research data was deleted."),
                             lambda m: QMessageBox.warning(self, "Delete", m))

    def _delete_profiles(self) -> None:
        if QMessageBox.question(self, "Delete browser profiles",
                                "Delete the dedicated automation/standard browser profiles? You will have to log in "
                                "again. Your normal Firefox profile is not affected.") == QMessageBox.StandardButton.Yes:
            self.bridge.call(self.ctrl.delete_browser_profiles,
                             lambda _: QMessageBox.information(self, "Deleted", "Dedicated profiles deleted."),
                             lambda m: QMessageBox.warning(self, "Delete", m))

    # --- templates & limits ------------------------------------------------------------------
    def _templates(self) -> None:
        w = QWidget()
        f = _form(w)
        self.tpl = QPlainTextEdit(self.settings.get("templates.transfer", ""))
        self.tpl.setMaximumHeight(80)
        self.human_tpl = QPlainTextEdit(self.settings.get("templates.human", "[original_message]"))
        self.human_tpl.setMaximumHeight(60)
        self.human_name = QLineEdit(self.settings.get("templates.human_name", "Human researcher"))
        f.addRow("Attributed transfer template", self.tpl)
        hint = QLabel("Placeholders: [speaker] [destination] [round] [turn] [topic] [host] [guest] and the required "
                      "[original_message]. Raw mode (unchecked attribution) forwards the message without any text.")
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        f.addRow("", hint)
        f.addRow("Human message template", self.human_tpl)
        f.addRow("Human name (transcript)", self.human_name)
        self.max_chars = QSpinBox()
        self.max_chars.setRange(500, 500000)
        self.max_chars.setValue(int(self.settings.get("limits.max_message_chars", 20000)))
        self.min_interval = QDoubleSpinBox()
        self.min_interval.setRange(0, 600)
        self.min_interval.setSuffix(" s")
        self.min_interval.setValue(float(self.settings.get("limits.min_interval_seconds", 2)))
        self.per_hour = QSpinBox()
        self.per_hour.setRange(0, 10000)
        self.per_hour.setSpecialValueText("unlimited")
        self.per_hour.setValue(int(self.settings.get("limits.max_messages_per_hour", 60)))
        self.near = QDoubleSpinBox()
        self.near.setRange(0.5, 1.0)
        self.near.setSingleStep(0.01)
        self.near.setValue(float(self.settings.get("limits.near_duplicate_threshold", 0.85)))
        f.addRow("Message size warning (chars)", self.max_chars)
        f.addRow("Min. interval per participant", self.min_interval)
        f.addRow("Max. messages per hour / participant", self.per_hour)
        f.addRow("Near-duplicate threshold", self.near)
        self.tabs.addTab(w, "Templates & limits")

    # --- providers ---------------------------------------------------------------------------------
    def _providers(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.provider = QComboBox()
        for pid in self.ctrl.registry.ids():
            self.provider.addItem(self.ctrl.registry.get(pid).label, pid)
        top.addWidget(QLabel("Provider"))
        top.addWidget(self.provider, 1)
        lay.addLayout(top)
        self.policy = QLabel()
        self.policy.setWordWrap(True)
        lay.addWidget(self.policy)
        self.ack = QCheckBox("I have reviewed this provider's current terms of use and accept responsibility for "
                             "automated interaction with my own account.")
        lay.addWidget(self.ack)
        lay.addWidget(QLabel("Effective configuration (shipped defaults + local overrides, read-only):"))
        self.effective = QPlainTextEdit()
        self.effective.setReadOnly(True)
        lay.addWidget(self.effective, 2)
        lay.addWidget(QLabel(f"Local override (JSON object; selector keys: {', '.join(SELECTOR_KEYS)}):"))
        self.override = QPlainTextEdit()
        self.override.setPlaceholderText('{\n  "selectors": {"input": ["#my-input"]},\n  "stability_ms": 2000\n}')
        lay.addWidget(self.override, 1)
        row = QHBoxLayout()
        self.validate_btn = QPushButton("Validate")
        self.save_ov_btn = QPushButton("Save override")
        self.reset_ov_btn = QPushButton("Reset to shipped defaults")
        self.ov_status = QLabel()
        for b in (self.validate_btn, self.save_ov_btn, self.reset_ov_btn):
            row.addWidget(b)
        row.addWidget(self.ov_status, 1)
        lay.addLayout(row)
        self.provider.currentIndexChanged.connect(self._load_provider)
        self.validate_btn.clicked.connect(lambda: self._override_value(show=True))
        self.save_ov_btn.clicked.connect(self._save_override)
        self.reset_ov_btn.clicked.connect(self._reset_override)
        self._acks = dict(self.settings.get("automation_acknowledged", {}) or {})
        self.ack.toggled.connect(self._ack_toggled)
        self.tabs.addTab(w, "Providers")
        self._load_provider()

    def _load_provider(self) -> None:
        pid = self.provider.currentData()
        cfg = self.ctrl.registry.get(pid)
        val = cfg.validation
        self.policy.setText(f"<b>Validation:</b> {val.get('status', 'unvalidated')} – {val.get('notes', '')}<br>"
                            f"<b>Automation:</b> {cfg.automation.get('note', '')}")
        needs_ack = cfg.automation_policy not in ("allowed", "user_controlled")
        self.ack.setVisible(needs_ack)
        self.ack.blockSignals(True)
        self.ack.setChecked(bool(self._acks.get(pid)))
        self.ack.blockSignals(False)
        eff = {k: v for k, v in cfg.__dict__.items() if k not in ("overridden",)}
        self.effective.setPlainText(json.dumps(eff, indent=2, ensure_ascii=False))
        ov = self.ctrl.registry.raw_override(pid)
        self.override.setPlainText(json.dumps(ov, indent=2, ensure_ascii=False) if ov else "")
        self.ov_status.setText("local override active" if ov else "")

    def _ack_toggled(self, on: bool) -> None:
        pid = self.provider.currentData()
        if on:
            self._acks[pid] = date.today().isoformat()
        else:
            self._acks.pop(pid, None)

    def _override_value(self, show: bool = False) -> dict | None:
        text = self.override.toPlainText().strip()
        try:
            data = json.loads(text) if text else {}
            if not isinstance(data, dict):
                raise ValueError("the override must be a JSON object")
            from adapters.registry import validate_provider_dict
            validate_provider_dict(self.provider.currentData(), data)
        except (ValueError, ProviderConfigError) as exc:
            self.ov_status.setText(f"✗ {exc}")
            return None
        if show:
            self.ov_status.setText("✓ valid")
        return data

    def _save_override(self) -> None:
        data = self._override_value()
        if data is None:
            return
        self.ctrl.registry.save_override(self.provider.currentData(), data)
        self._load_provider()
        self.ov_status.setText("✓ saved – used from the next diagnostic / session")

    def _reset_override(self) -> None:
        self.ctrl.registry.reset_override(self.provider.currentData())
        self._load_provider()
        self.ov_status.setText("shipped defaults restored")

    # --- browser -------------------------------------------------------------------------------------
    def _browser(self) -> None:
        w = QWidget()
        f = _form(w)
        row = QHBoxLayout()
        self.ff_path = QLineEdit(self.settings.get("browser.firefox_path", ""))
        self.ff_path.setPlaceholderText("auto-detect (only used by the 'Installed Firefox' backend)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_ff)
        row.addWidget(self.ff_path, 1)
        row.addWidget(browse)
        f.addRow("Installed Firefox", row)
        self.layout_mode = QComboBox()
        self.layout_mode.addItem("Side by side + control panel column (wide screens)", "with_panel")
        self.layout_mode.addItem("Side by side (half/half) + floating compact bar", "split")
        self.layout_mode.setCurrentIndex(0 if self.settings.get("window.layout", "with_panel") == "with_panel" else 1)
        self.apply_layout = QCheckBox("Position browsers when opening (otherwise Firefox restores the remembered "
                                      "position of each dedicated profile)")
        self.apply_layout.setChecked(bool(self.settings.get("window.apply_layout_on_open", True)))
        self.on_top = QCheckBox("Compact control bar always on top")
        self.on_top.setChecked(bool(self.settings.get("window.control_bar_on_top", True)))
        self.reopen = QCheckBox("Reopen the last conversation URL (for 'existing conversation' experiments)")
        self.reopen.setChecked(bool(self.settings.get("browser.reopen_last_url", False)))
        self.pipeline = QCheckBox("Pipeline test: use the local mock chat page for BOTH participants")
        self.pipeline.setChecked(bool(self.settings.get("browser.pipeline_test", False)))
        rt_row = QHBoxLayout()
        self.rt_status = QLabel()
        self.rt_status.setWordWrap(True)
        rt_btn = QPushButton("Manage…")
        rt_btn.clicked.connect(self._runtime)
        rt_row.addWidget(self.rt_status, 1)
        rt_row.addWidget(rt_btn)
        f.addRow("Browser runtime", rt_row)
        self._refresh_runtime()
        f.addRow("Window layout", self.layout_mode)
        f.addRow("", self.apply_layout)
        f.addRow("", self.on_top)
        f.addRow("", self.reopen)
        f.addRow("", self.pipeline)
        info = QLabel("Managed Firefox = Playwright's own Firefox build with a dedicated persistent profile per "
                      "participant (automation possible). Installed Firefox = your Firefox program with a separate "
                      "dedicated profile and NO automation (clipboard workflow). Your normal Firefox profile is "
                      "never used or modified, and the application cannot attach to Firefox windows you opened "
                      "yourself.")
        info.setObjectName("Faint")
        info.setWordWrap(True)
        f.addRow(info)
        self.tabs.addTab(w, "Browser & windows")

    def _refresh_runtime(self) -> None:
        st = self.ctrl.runtime_status()
        self.rt_status.setText("Playwright Firefox: installed" if st["firefox_installed"] else
                               "Playwright Firefox: not installed (optional – needed only for automation)")

    def _runtime(self) -> None:
        from .runtime_dialog import RuntimeDialog
        RuntimeDialog(self, self.bridge).exec()
        self._refresh_runtime()

    def _browse_ff(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select firefox.exe", "", "Firefox (firefox.exe firefox);;All (*)")
        if path:
            self.ff_path.setText(path)

    # --- shortcuts ---------------------------------------------------------------------------------------
    def _shortcuts(self) -> None:
        w = QWidget()
        f = _form(w)
        self.seq_edits = {}
        for key, text in SHORTCUT_LABELS.items():
            e = QKeySequenceEdit(QKeySequence(self.settings.get(f"shortcuts.{key}", "")))
            self.seq_edits[key] = e
            f.addRow(text, e)
        note = QLabel("Shortcuts work while an EMERGENCE LAB window is focused. They are not global system hooks.")
        note.setObjectName("Faint")
        f.addRow(note)
        self.tabs.addTab(w, "Shortcuts")

    # --- save ----------------------------------------------------------------------------------------------
    def _save(self) -> None:
        try:
            validate_transfer_template(self.tpl.toPlainText())
            validate_transfer_template(self.human_tpl.toPlainText())
        except TemplateError as exc:
            self.tabs.setCurrentIndex(1)
            QMessageBox.warning(self, "Template", str(exc))
            return
        s = self.settings
        s.set("theme", self.theme.currentData())
        s.set("research.recording_enabled", self.recording.isChecked())
        s.update("templates", {"transfer": self.tpl.toPlainText(), "human": self.human_tpl.toPlainText(),
                               "human_name": self.human_name.text().strip() or "Human researcher"})
        s.update("limits", {"max_message_chars": self.max_chars.value(), "min_interval_seconds": self.min_interval.value(),
                            "max_messages_per_hour": self.per_hour.value(), "near_duplicate_threshold": self.near.value()})
        s.set("automation_acknowledged", self._acks)
        s.set("browser.firefox_path", self.ff_path.text().strip())
        self.ctrl.browsers.firefox_path = self.ff_path.text().strip()
        s.set("window.layout", self.layout_mode.currentData())
        s.set("window.apply_layout_on_open", self.apply_layout.isChecked())
        s.set("window.control_bar_on_top", self.on_top.isChecked())
        s.set("browser.reopen_last_url", self.reopen.isChecked())
        s.set("browser.pipeline_test", self.pipeline.isChecked())
        for key, e in self.seq_edits.items():
            s.set(f"shortcuts.{key}", e.keySequence().toString())
        self.accept()

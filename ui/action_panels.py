"""Operator action panels: confirmation, verification, human intervention, clipboard."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from . import icons
from .widgets import repolish, section_label


class _Panel(QFrame):
    def __init__(self, tone: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActionPanel")
        self.setProperty("tone", tone)
        repolish(self)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(7)
        head = QHBoxLayout()
        self.title = section_label(title)
        head.addWidget(self.title)
        head.addStretch(1)
        self.head_right = head
        self.lay.addLayout(head)
        self.hide()

    @staticmethod
    def _button(text: str, name: str = "", icon: str = "") -> QPushButton:
        b = QPushButton(text)
        if name:
            b.setObjectName(name)
        if icon:
            b.setIcon(icons.icon(icon))
        return b


class ConfirmPanel(_Panel):
    send = Signal(str, int)
    skip = Signal()
    copy = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("confirm", "Transfer ready", parent)
        self.alts = QComboBox()
        self.alts.currentIndexChanged.connect(self._alt_changed)
        self.lay.addWidget(self.alts)
        self.warnings = QLabel()
        self.warnings.setObjectName("Warning")
        self.warnings.setWordWrap(True)
        self.lay.addWidget(self.warnings)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(110)
        self.lay.addWidget(self.editor, 1)
        note = QLabel("The original response stays unchanged in the transcript; edits are stored separately as "
                      "the forwarded text.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        row = QHBoxLayout()
        self.send_btn = self._button("Send", "Primary", "send")
        self.skip_btn = self._button("Skip")
        self.copy_btn = self._button("Copy", icon="copy")
        self.reset_btn = self._button("Reset text")
        for b in (self.send_btn, self.skip_btn, self.copy_btn, self.reset_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.send_btn.clicked.connect(lambda: self.send.emit(self.editor.toPlainText(), max(0, self.alts.currentIndex())))
        self.skip_btn.clicked.connect(self.skip.emit)
        self.copy_btn.clicked.connect(lambda: self.copy.emit(self.editor.toPlainText()))
        self.reset_btn.clicked.connect(self._reset)
        self._data: list[dict[str, Any]] = []

    def present(self, data: dict[str, Any]) -> None:
        self._data = data.get("alternatives", [])
        self.alts.blockSignals(True)
        self.alts.clear()
        for a in self._data:
            self.alts.addItem(f"Forward {a['source_name']}'s reply → {a['destination_name']}")
        self.alts.setVisible(len(self._data) > 1)
        self.alts.blockSignals(False)
        warnings = data.get("warnings") or []
        self.warnings.setText("\n".join(f"⚠ {w}" for w in warnings))
        self.warnings.setVisible(bool(warnings))
        self._alt_changed(0)
        self.show()
        self.editor.setFocus()

    def _alt_changed(self, index: int) -> None:
        if 0 <= index < len(self._data):
            a = self._data[index]
            self.title.setText(f"TRANSFER READY · {a['source_name']} → {a['destination_name']}".upper())
            self.editor.setPlainText(a["text"])

    def _reset(self) -> None:
        self._alt_changed(max(0, self.alts.currentIndex()))


class VerifyPanel(_Panel):
    resolved = Signal(bool)
    focus = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("confirm", "Manual verification required", parent)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.lay.addWidget(self.message)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(90)
        self.lay.addWidget(self.preview)
        row = QHBoxLayout()
        self.yes = self._button("It was submitted – keep waiting", "Primary")
        self.no = self._button("It was NOT submitted – send again")
        self.focus_btn = self._button("Focus window", icon="focus")
        for b in (self.yes, self.no, self.focus_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.yes.clicked.connect(lambda: self.resolved.emit(True))
        self.no.clicked.connect(lambda: self.resolved.emit(False))
        self.focus_btn.clicked.connect(lambda: self.focus.emit(self._role))
        self._role = "host"

    def present(self, data: dict[str, Any]) -> None:
        self._role = data.get("role", "host")
        self.title.setText(f"MANUAL VERIFICATION · {data.get('name', '')}".upper())
        self.message.setText(data.get("message", ""))
        self.preview.setPlainText(data.get("text", ""))
        self.show()


class HumanPanel(_Panel):
    send_to = Signal(str, str)       # target, text
    resume_previous = Signal()
    cancel_generation = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("human", "Human intervention · automatic forwarding paused", parent)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.lay.addWidget(self.status)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Your message as the human researcher …")
        self.editor.setMinimumHeight(80)
        self.lay.addWidget(self.editor)
        row = QHBoxLayout()
        self.to_host = self._button("Send to Cameron", "Primary", "send")
        self.to_guest = self._button("Send to Guest", "Primary", "send")
        self.to_both = self._button("Send to both")
        self.resume_btn = self._button("Resume previous conversation", icon="play")
        for b in (self.to_host, self.to_guest, self.to_both, self.resume_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        row2 = QHBoxLayout()
        self.cancel_host = self._button("Cancel Cameron's generation", "Danger")
        self.cancel_guest = self._button("Cancel Guest's generation", "Danger")
        row2.addWidget(self.cancel_host)
        row2.addWidget(self.cancel_guest)
        row2.addStretch(1)
        self.lay.addLayout(row2)
        self.to_host.clicked.connect(lambda: self._send("host"))
        self.to_guest.clicked.connect(lambda: self._send("guest"))
        self.to_both.clicked.connect(lambda: self._send("both"))
        self.resume_btn.clicked.connect(self.resume_previous.emit)
        self.cancel_host.clicked.connect(lambda: self.cancel_generation.emit("host"))
        self.cancel_guest.clicked.connect(lambda: self.cancel_generation.emit("guest"))

    def set_names(self, host: str, guest: str) -> None:
        self.to_host.setText(f"Send to {host}")
        self.to_guest.setText(f"Send to {guest}")
        self.cancel_host.setText(f"Cancel {host}'s generation")
        self.cancel_guest.setText(f"Cancel {guest}'s generation")

    def _send(self, target: str) -> None:
        text = self.editor.toPlainText().strip()
        if text:
            self.send_to.emit(target, text)

    def open(self, pending: dict[str, Any] | None = None) -> None:
        kind = (pending or {}).get("kind")
        name = (pending or {}).get("name", "")
        info = {"await": f"Pending: {name}'s response. It will be recorded before your message is sent.",
                "confirm": f"Pending: a transfer to {name} (Resume previous re-offers it).",
                "send": f"Pending: a message to {name}."}.get(kind or "", "No pending step.")
        self.status.setText(info)
        self.show()
        self.editor.setFocus()

    def set_status(self, text: str) -> None:
        self.status.setText(text)


class ClipboardPanel(_Panel):
    copy = Signal(str)
    mark_sent = Signal(str, str)              # request_id, final text
    import_clipboard = Signal()
    accept = Signal(str, str, str)            # request_id, text, speaker role
    focus = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("clipboard", "Clipboard", parent)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.lay.addWidget(self.info)
        self.speaker_row = QHBoxLayout()
        self.speaker_label = QLabel("Speaker")
        self.speaker = QComboBox()
        self.speaker_row.addWidget(self.speaker_label)
        self.speaker_row.addWidget(self.speaker)
        self.speaker_row.addStretch(1)
        self.lay.addLayout(self.speaker_row)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(100)
        self.lay.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.copy_btn = self._button("Copy to clipboard", "Primary", "copy")
        self.sent_btn = self._button("I pasted and sent it")
        self.import_btn = self._button("Import from clipboard", "Primary", "import")
        self.accept_btn = self._button("Accept reply")
        self.focus_btn = self._button("Focus window", icon="focus")
        for b in (self.copy_btn, self.sent_btn, self.import_btn, self.accept_btn, self.focus_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        note = QLabel("The clipboard is only read or written when you click these buttons or press the "
                      "configured shortcut – it is never monitored.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.copy_btn.clicked.connect(lambda: self.copy.emit(self.editor.toPlainText()))
        self.sent_btn.clicked.connect(lambda: self.mark_sent.emit(self.request_id, self.editor.toPlainText()))
        self.import_btn.clicked.connect(self.import_clipboard.emit)
        self.accept_btn.clicked.connect(
            lambda: self.accept.emit(self.request_id, self.editor.toPlainText(), self.speaker.currentData() or self.role))
        self.focus_btn.clicked.connect(lambda: self.focus.emit(self.role))
        self.request_id = ""
        self.action = ""
        self.role = "host"

    def present(self, data: dict[str, Any], names: dict[str, str]) -> None:
        self.request_id = data["request_id"]
        self.action = data["action"]
        self.role = data["role"]
        name = data.get("name", "")
        paste = self.action == "paste"
        self.title.setText((f"CLIPBOARD · PASTE INTO {name}'S WINDOW" if paste else f"CLIPBOARD · IMPORT {name}'S REPLY").upper())
        if paste:
            self.info.setText(f"1. Copy the text below.  2. Paste it into {name}'s chat window and send it there.  "
                              "3. Click “I pasted and sent it”. You may edit the text first.")
            self.editor.setPlainText(data.get("text", ""))
        else:
            self.info.setText(f"Wait until {name} has finished. Copy the COMPLETE reply in the browser, then click "
                              "“Import from clipboard” (or paste it below) and accept it.")
            self.editor.clear()
            self.editor.setPlaceholderText(f"{name}'s reply …")
        self.speaker.clear()
        for role in ("host", "guest"):
            self.speaker.addItem(names.get(role, role), role)
        self.speaker.setCurrentIndex(0 if self.role == "host" else 1)
        for w in (self.speaker_label, self.speaker):
            w.setVisible(not paste)
        self.copy_btn.setVisible(paste)
        self.sent_btn.setVisible(paste)
        self.import_btn.setVisible(not paste)
        self.accept_btn.setVisible(not paste)
        self.show()

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)

"""Conversation configuration (session, transfer, research, demo)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QTabWidget,
    QWidget,
)

from adapters.demo import DEMO_SCENARIOS
from app.settings import Settings
from research.experiments import CONDITION_FIELDS

from .widgets import Card, section_label

TRANSFER_MODES = [("manual", "Manual confirmation (default)"), ("automatic", "Automatic transfer"),
                  ("clipboard", "Clipboard (no automation)")]


def _form(widget: QWidget) -> QFormLayout:
    f = QFormLayout(widget)
    f.setContentsMargins(10, 10, 10, 10)
    f.setHorizontalSpacing(10)
    f.setVerticalSpacing(6)
    return f


class SessionPanel(Card):
    changed = Signal()

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.body.addWidget(section_label("03 / Conversation configuration"))
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs)

        # session
        w = QWidget()
        f = _form(w)
        self.session_name = QLineEdit()
        self.session_name.setPlaceholderText("Session <date/time>")
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("e.g. Can artificial dreaming transform memory into empathy?")
        self.initial_prompt = QPlainTextEdit()
        self.initial_prompt.setMinimumHeight(110)
        self.first_speaker = QComboBox()
        self.first_speaker.addItem("Cameron (host)", "host")
        self.first_speaker.addItem("Guest", "guest")
        f.addRow("Session name", self.session_name)
        f.addRow("Research topic", self.topic)
        f.addRow("Initial prompt", self.initial_prompt)
        hint = QLabel("Placeholders: [topic] [recipient] [other] [host] [guest]")
        hint.setObjectName("Faint")
        f.addRow("", hint)
        f.addRow("First speaker", self.first_speaker)
        self.tabs.addTab(w, "Session")

        # transfer
        w = QWidget()
        f = _form(w)
        self.transfer_mode = QComboBox()
        for key, text in TRANSFER_MODES:
            self.transfer_mode.addItem(text, key)
        self.attribution = QCheckBox("Attributed transfer – label every forwarded message with its sender")
        self.max_rounds = QSpinBox()
        self.max_rounds.setRange(1, 1000)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0, 600)
        self.delay.setDecimals(1)
        self.delay.setSuffix(" s")
        self.max_wait = QSpinBox()
        self.max_wait.setRange(10, 7200)
        self.max_wait.setSuffix(" s")
        self.record = QCheckBox("Record transcript automatically (local SQLite)")
        f.addRow("Transfer mode", self.transfer_mode)
        f.addRow("", self.attribution)
        f.addRow("Maximum rounds", self.max_rounds)
        f.addRow("Delay between messages", self.delay)
        f.addRow("Max. response wait", self.max_wait)
        f.addRow("", self.record)
        note = QLabel("A round = one completed response from each participant. Automatic transfer requires "
                      "automation to be enabled for the provider and a passed adapter diagnostic.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        f.addRow(note)
        self.tabs.addTab(w, "Transfer")

        # research
        w = QWidget()
        f = _form(w)
        self.research_question = QLineEdit()
        self.host_model = QLineEdit()
        self.host_model.setPlaceholderText("user-reported, e.g. the model selected in ChatGPT")
        self.guest_model = QLineEdit()
        self.guest_model.setPlaceholderText("user-reported")
        self.context = QComboBox()
        self.memory = QComboBox()
        for combo, key in ((self.context, "conversation_context"), (self.memory, "memory_setting")):
            for v in CONDITION_FIELDS[key]:
                combo.addItem(v or "— not reported —", v)
        self.experiment = QLineEdit()
        self.condition = QLineEdit()
        self.condition.setPlaceholderText("e.g. A: attributed / existing conversation")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)
        f.addRow("Research question", self.research_question)
        f.addRow("Cameron model", self.host_model)
        f.addRow("Guest model", self.guest_model)
        f.addRow("Conversation context", self.context)
        f.addRow("Memory setting", self.memory)
        f.addRow("Experiment", self.experiment)
        f.addRow("Condition", self.condition)
        f.addRow("Notes", self.notes)
        note = QLabel("Model names, memory settings and context are recorded as USER-REPORTED. The application "
                      "never changes provider settings and never infers hidden model states.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        f.addRow(note)
        self.tabs.addTab(w, "Research")

        # demo
        self.demo_tab = QWidget()
        f = _form(self.demo_tab)
        self.scenario = QComboBox()
        for key, text in DEMO_SCENARIOS.items():
            self.scenario.addItem(text, key)
        f.addRow("Scenario", self.scenario)
        info = QLabel("DEMO MODE simulates both participants with deterministic fictional responses. Nothing is "
                      "sent to ChatGPT or any other provider, and simulated messages are labelled as such in the "
                      "monitor and in every export.")
        info.setWordWrap(True)
        info.setObjectName("Warning")
        f.addRow(info)
        self.demo_index = self.tabs.addTab(self.demo_tab, "Demo")
        self.load()

    # ---------------------------------------------------------------------------------
    def load(self) -> None:
        s = self.settings
        c = s.get("conversation", {})
        r = s.get("research", {})
        self.session_name.setText(c.get("session_name", ""))
        self.topic.setText(c.get("topic", ""))
        self.initial_prompt.setPlainText(c.get("initial_prompt", ""))
        self.first_speaker.setCurrentIndex(0 if c.get("first_speaker", "host") == "host" else 1)
        self.transfer_mode.setCurrentIndex(max(0, self.transfer_mode.findData(c.get("transfer_mode", "manual"))))
        self.attribution.setChecked(bool(c.get("attribution", True)))
        self.max_rounds.setValue(int(c.get("max_rounds", 10)))
        self.delay.setValue(float(c.get("delay_seconds", 2)))
        self.max_wait.setValue(int(c.get("max_wait_seconds", 180)))
        self.record.setChecked(bool(c.get("record_transcript", True)))
        self.research_question.setText(c.get("research_question", ""))
        self.host_model.setText(s.get("host.model_name", ""))
        self.guest_model.setText(s.get("guest.model_name", ""))
        self.context.setCurrentIndex(max(0, self.context.findData(r.get("conversation_context", ""))))
        self.memory.setCurrentIndex(max(0, self.memory.findData(r.get("memory_setting", ""))))
        self.experiment.setText(r.get("experiment", ""))
        self.condition.setText(r.get("condition", ""))
        self.notes.setPlainText(r.get("notes", ""))
        self.scenario.setCurrentIndex(max(0, self.scenario.findData(s.get("demo.scenario", "normal"))))
        self.set_demo(bool(s.get("demo_mode", False)))

    def store(self) -> None:
        s = self.settings
        s.update("conversation", {
            "session_name": self.session_name.text().strip(), "topic": self.topic.text().strip(),
            "research_question": self.research_question.text().strip(),
            "initial_prompt": self.initial_prompt.toPlainText(), "first_speaker": self.first_speaker.currentData(),
            "transfer_mode": self.transfer_mode.currentData(), "attribution": self.attribution.isChecked(),
            "max_rounds": self.max_rounds.value(), "delay_seconds": self.delay.value(),
            "max_wait_seconds": self.max_wait.value(), "record_transcript": self.record.isChecked()})
        s.set("host.model_name", self.host_model.text().strip())
        s.set("guest.model_name", self.guest_model.text().strip())
        s.update("research", {"conversation_context": self.context.currentData(),
                              "memory_setting": self.memory.currentData(), "experiment": self.experiment.text().strip(),
                              "condition": self.condition.text().strip(), "notes": self.notes.toPlainText()})
        s.set("demo.scenario", self.scenario.currentData())

    def set_demo(self, on: bool) -> None:
        self.tabs.setTabVisible(self.demo_index, on)
        if on and self.max_wait.value() > 60:
            self.max_wait.setValue(20)
        if on and self.delay.value() > 2:
            self.delay.setValue(0.5)

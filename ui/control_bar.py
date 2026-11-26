"""Compact always-on-top control bar (sits beside the two browser windows)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout, QWidget

from app import APP_NAME, BRANDING, __version__

from . import icons, styles
from .widgets import Card, repolish, section_label, spaced_font


class ControlBar(QWidget):
    def __init__(self, main) -> None:
        super().__init__(None)
        self.main = main
        on_top = bool(main.settings.get("window.control_bar_on_top", True))
        flags = Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowTitleHint
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle(f"{APP_NAME} · control bar")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(10)

        head = QHBoxLayout()
        self.glyph = QLabel()
        head.addWidget(self.glyph)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("AppTitle")
        t.setFont(spaced_font(spacing=1.4, size=11, bold=True))
        self.subtitle = QLabel("CONVERSATION BRIDGE")
        self.subtitle.setObjectName("AppSubtitle")
        titles.addWidget(t)
        titles.addWidget(self.subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        self.mode_badge = QLabel("LOCAL")
        self.mode_badge.setObjectName("Badge")
        head.addWidget(self.mode_badge)
        lay.addLayout(head)

        cards = QHBoxLayout()
        self.cards = {}
        for role, label in (("host", "01 / Host"), ("guest", "02 / Guest")):
            c = Card(margins=10, spacing=4)
            c.body.addWidget(section_label(label))
            mark = QLabel()
            name = QLabel()
            name.setObjectName("Title")
            sub = QLabel()
            sub.setObjectName("Subtitle")
            c.body.addWidget(mark)
            c.body.addWidget(name)
            c.body.addWidget(sub)
            cards.addWidget(c)
            self.cards[role] = (mark, name, sub)
        lay.addLayout(cards)

        box = Card(name="Panel", margins=10, spacing=5)
        self.session_label = section_label("Research session")
        box.body.addWidget(self.session_label)
        self.topic = QLabel()
        self.topic.setWordWrap(True)
        box.body.addWidget(self.topic)
        r = QHBoxLayout()
        self.round = QLabel("Round 01 / 10")
        self.round.setObjectName("Muted")
        self.mode = QLabel()
        self.mode.setObjectName("Muted")
        r.addWidget(self.round)
        r.addStretch(1)
        r.addWidget(self.mode)
        box.body.addLayout(r)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        box.body.addWidget(self.progress)
        lay.addWidget(box)

        st = QHBoxLayout()
        self.dot = QLabel()
        self.flow = QLabel()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        st.addWidget(self.dot)
        st.addWidget(self.flow)
        st.addStretch(1)
        st.addWidget(self.status)
        lay.addLayout(st)

        bar = Card(name="Panel", margins=6, spacing=0)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons: dict[str, QToolButton] = {}
        for key, _ic, tip, fn in (
                ("start", "play", "Start / resume", main.start_or_resume),
                ("pause", "pause", "Pause", main.pause),
                ("stop", "stop", "Stop", main.stop),
                ("send", "send", "Send pending transfer", main.confirm_from_bar),
                ("human", "human", "Human intervention", lambda: (main.human(), main.showNormal(), main.raise_())),
                ("mic", "mic", "Microphone status (armed in the guest panel)", lambda: None),
                ("export", "export", "Export transcript", main.export),
                ("emergency", "emergency", "EMERGENCY STOP", main.emergency),
                ("main", "compact", "Show main window", lambda: (main.showNormal(), main.raise_(), main.activateWindow()))):
            b = QToolButton()
            b.setObjectName("Icon")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        bar.body.addLayout(row)
        lay.addWidget(bar)

        foot = QHBoxLayout()
        f1 = QLabel(BRANDING)
        f1.setObjectName("Faint")
        f2 = QLabel(f"v{__version__}")
        f2.setObjectName("Faint")
        foot.addWidget(f1)
        foot.addStretch(1)
        foot.addWidget(f2)
        lay.addLayout(foot)
        self._recording = False
        self.restyle()

    def restyle(self) -> None:
        pal = styles.palette()
        self.glyph.setPixmap(icons.app_glyph(pal["teal"], 22))
        colors = {"stop": pal["red"], "emergency": pal["red"], "start": pal["teal"], "send": pal["teal"],
                  "mic": pal["red"] if self._recording else pal["muted"]}
        for key, ic in (("start", "play"), ("pause", "pause"), ("stop", "stop"), ("send", "send"), ("human", "human"),
                        ("mic", "mic"), ("export", "export"), ("emergency", "emergency"), ("main", "compact")):
            self.buttons[key].setIcon(icons.icon(ic, colors.get(key), 20))

    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.restyle()

    def update_view(self, v: dict[str, Any]) -> None:
        pal = styles.palette()
        for role, accent in (("host", pal["teal"]), ("guest", pal["blue"])):
            mark, name, sub = self.cards[role]
            n = v["names"][role]
            mark.setPixmap(icons.monogram(n[:1], accent, 28))
            name.setText(n.upper())
            sub.setText(v["providers"][role] + (" · simulated" if v["demo"] else ""))
        self.mode_badge.setText("DEMO MODE" if v["demo"] else "LOCAL")
        self.mode_badge.setProperty("tone", "demo" if v["demo"] else "")
        repolish(self.mode_badge)
        self.session_label.setText(f"RESEARCH SESSION / {v['title']}".upper())
        self.topic.setText(v["topic"])
        cur, done, mx = v["round"]
        self.round.setText(f"Round {cur:02d} / {mx:02d}")
        self.progress.setRange(0, max(1, mx))
        self.progress.setValue(done)
        self.mode.setText(v["mode"])
        tone = {"ERROR": "error", "PAUSED": "warning", "HUMAN_INTERVENTION": "warning",
                "WAITING_FOR_CONFIRMATION": "warning", "COMPLETED": "ok"}.get(v["state"], "active" if v["running"] else "idle")
        self.dot.setPixmap(icons.dot(styles.tone_color(tone), 12))
        self.flow.setText(v["transfer"] if v["transfer"] != "—" else v["state_text"])
        self.status.setText(v["state_text"])
        self.buttons["send"].setEnabled(v["pending_confirm"])
        self.buttons["pause"].setEnabled(v["running"])
        self.buttons["stop"].setEnabled(v["running"])

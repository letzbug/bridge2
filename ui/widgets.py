"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import icons, styles


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def spaced_font(base: QFont | None = None, spacing: float = 1.2, size: float | None = None,
                bold: bool = False) -> QFont:
    f = QFont(base) if base is not None else QFont()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if size:
        f.setPointSizeF(size)
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


def section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Section")
    lbl.setFont(spaced_font(spacing=1.1, size=8))
    return lbl


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def rule() -> QFrame:
    f = QFrame()
    f.setObjectName("Rule")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, name: str = "Card", margins: int = 12, spacing: int = 8) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class StatusRow(QWidget):
    """'Label  ● value' line with a coloured status dot."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.caption = QLabel(caption)
        self.caption.setObjectName("Muted")
        self.caption.setMinimumWidth(96)
        self.dot = QLabel()
        self.value = QLabel("—")
        self.value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.value.setWordWrap(True)
        lay.addWidget(self.caption)
        lay.addWidget(self.dot)
        lay.addWidget(self.value, 1)
        self.set("—", "idle")

    def set(self, value: str, tone: str = "idle", tooltip: str = "") -> None:
        self.value.setText(value)
        self.dot.setPixmap(icons.dot(styles.tone_color(tone)))
        self.setToolTip(tooltip)


class Banner(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 10, 6)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.lay.addWidget(self.text, 1)
        self.buttons = QHBoxLayout()
        self.lay.addLayout(self.buttons)
        self.hide()

    def show_message(self, message: str, tone: str = "warning") -> None:
        self.setProperty("tone", tone)
        repolish(self)
        self.text.setText(message)
        self.show()

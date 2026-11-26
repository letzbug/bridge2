"""Design system: graphite surfaces, restrained teal/blue accents, compact controls."""

from __future__ import annotations

from string import Template

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0c1115", "panel": "#11171c", "card": "#161d23", "input": "#0f1519", "btn": "#1a2229",
        "border": "#232d35", "border2": "#2f3b45", "text": "#d8dfe5", "muted": "#8593a0", "faint": "#56636e",
        "teal": "#3fcfb2", "teal_bg": "#123630", "teal_text": "#7fe6d1", "blue": "#7ea6ff", "blue_bg": "#18264a",
        "amber": "#e3ad4f", "amber_bg": "#2e2412", "red": "#ef6b6b", "red_bg": "#341719", "green": "#5ccf8c",
        "human_bg": "#1d1a12", "host_bg": "#121e1c", "guest_bg": "#131a28", "system": "#6f7d89",
    },
    "light": {
        "bg": "#f3f5f7", "panel": "#ffffff", "card": "#ffffff", "input": "#fbfcfd", "btn": "#f1f4f6",
        "border": "#d8dee3", "border2": "#c3ccd3", "text": "#1a2228", "muted": "#5b6872", "faint": "#9aa5ae",
        "teal": "#0e9b83", "teal_bg": "#dff4ef", "teal_text": "#0b7a67", "blue": "#3b6bd6", "blue_bg": "#e3ebfb",
        "amber": "#b0760f", "amber_bg": "#fbf0dc", "red": "#c63d3d", "red_bg": "#fbe3e3", "green": "#1f9d55",
        "human_bg": "#fdf7ea", "host_bg": "#effaf7", "guest_bg": "#eff3fd", "system": "#7b8790",
    },
}

_current = {"theme": "dark"}


def palette() -> dict[str, str]:
    return PALETTES[_current["theme"]]


def set_theme(theme: str) -> None:
    _current["theme"] = theme if theme in PALETTES else "dark"


def theme() -> str:
    return _current["theme"]


TONES = {"ok": "green", "active": "teal", "info": "blue", "warning": "amber", "error": "red", "idle": "faint",
         "demo": "amber"}


def tone_color(tone: str) -> str:
    return palette()[TONES.get(tone, "faint")]


_QSS = Template("""
QWidget { background: $bg; color: $text; font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif; font-size: 9.5pt; }
QMainWindow, QDialog { background: $bg; }
QLabel { background: transparent; }
QFrame#Card { background: $card; border: 1px solid $border; border-radius: 3px; }
QFrame#Panel { background: $panel; border: 1px solid $border; border-radius: 3px; }
QFrame#Rule { background: $border; max-height: 1px; min-height: 1px; border: none; }
QFrame#HeaderBar { background: $bg; border-bottom: 1px solid $border; }
QFrame#Footer { background: $bg; border-top: 1px solid $border; }
QLabel#Section { color: $muted; font-size: 8pt; }
QLabel#Title { font-size: 11pt; font-weight: 600; }
QLabel#Subtitle, QLabel#Muted { color: $muted; }
QLabel#Faint { color: $faint; font-size: 8.5pt; }
QLabel#AppTitle { font-size: 12.5pt; font-weight: 700; }
QLabel#AppSubtitle { color: $muted; font-size: 8pt; }
QLabel#Badge { border: 1px solid $border2; color: $muted; padding: 1px 8px; border-radius: 2px; font-size: 8pt; }
QLabel#Badge[tone="demo"] { border-color: $amber; color: $amber; font-weight: 700; }
QLabel#Badge[tone="rec"] { border-color: $red; color: $red; font-weight: 700; }
QLabel#Badge[tone="ok"] { border-color: $teal; color: $teal; }
QLabel#StateBadge { padding: 2px 8px; border-radius: 2px; font-size: 8pt; font-weight: 600; background: $btn; color: $muted; }
QLabel#StateBadge[tone="active"] { background: $teal_bg; color: $teal_text; }
QLabel#StateBadge[tone="warning"] { background: $amber_bg; color: $amber; }
QLabel#StateBadge[tone="error"] { background: $red_bg; color: $red; }
QLabel#StateBadge[tone="ok"] { background: $teal_bg; color: $teal_text; }
QLabel#Warning { color: $amber; }
QLabel#Error { color: $red; }
QPushButton, QToolButton { background: $btn; border: 1px solid $border2; padding: 4px 10px; border-radius: 3px; min-height: 18px; }
QPushButton:hover, QToolButton:hover { border-color: $teal; }
QPushButton:pressed, QToolButton:pressed { background: $teal_bg; }
QPushButton:disabled, QToolButton:disabled { color: $faint; border-color: $border; }
QPushButton:checked, QToolButton:checked { background: $teal_bg; border-color: $teal; color: $teal_text; }
QPushButton#Primary { background: $teal_bg; border-color: $teal; color: $teal_text; font-weight: 600; }
QPushButton#Primary:disabled { background: $btn; color: $faint; border-color: $border; }
QPushButton#Danger { color: $red; border-color: $border2; }
QPushButton#Danger:hover { border-color: $red; }
QPushButton#Emergency { background: $red_bg; border: 1px solid $red; color: $red; font-weight: 700; }
QPushButton#Emergency:hover { background: $red; color: #ffffff; }
QToolButton#Flat { background: transparent; border: none; color: $muted; padding: 3px 4px; }
QToolButton#Flat:hover { color: $text; }
QToolButton#Icon { background: transparent; border: 1px solid transparent; padding: 4px; }
QToolButton#Icon:hover { border-color: $border2; }
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {
    background: $input; border: 1px solid $border; border-radius: 3px; padding: 3px 6px;
    selection-background-color: $teal_bg; selection-color: $text; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $teal; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $faint; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: $panel; border: 1px solid $border2; selection-background-color: $teal_bg; outline: 0; }
QTabWidget::pane { border: 1px solid $border; top: -1px; background: $card; }
QTabBar::tab { background: transparent; color: $muted; padding: 6px 12px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $teal; }
QTabBar::tab:hover { color: $text; }
QProgressBar { background: $border; border: none; border-radius: 2px; max-height: 5px; min-height: 5px; text-align: center; }
QProgressBar::chunk { background: $teal; border-radius: 2px; }
QProgressBar#Meter { max-height: 10px; min-height: 10px; }
QCheckBox { spacing: 6px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: $border2; min-height: 28px; border-radius: 4px; }
QScrollBar:horizontal { background: transparent; height: 9px; }
QScrollBar::handle:horizontal { background: $border2; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QHeaderView::section { background: $panel; color: $muted; border: none; border-bottom: 1px solid $border; padding: 4px 6px; }
QTableWidget, QListWidget { background: $input; border: 1px solid $border; gridline-color: $border; }
QTableWidget::item:selected, QListWidget::item:selected { background: $teal_bg; color: $text; }
QToolTip { background: $panel; color: $text; border: 1px solid $border2; padding: 4px; }
QFrame#Banner { border-radius: 3px; }
QFrame#Banner[tone="warning"] { background: $amber_bg; border: 1px solid $amber; }
QFrame#Banner[tone="error"] { background: $red_bg; border: 1px solid $red; }
QFrame#Banner[tone="info"] { background: $blue_bg; border: 1px solid $blue; }
QFrame#Banner QLabel { background: transparent; }
QFrame#ActionPanel { background: $panel; border: 1px solid $border2; border-radius: 3px; }
QFrame#ActionPanel[tone="human"] { border-color: $amber; }
QFrame#ActionPanel[tone="clipboard"] { border-color: $blue; }
QFrame#ActionPanel[tone="confirm"] { border-color: $teal; }
QSplitter::handle { background: $border; }
QGroupBox { border: 1px solid $border; border-radius: 3px; margin-top: 14px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: $muted; }
QMenu { background: $panel; border: 1px solid $border2; }
QMenu::item:selected { background: $teal_bg; }
""")


def stylesheet() -> str:
    return _QSS.substitute(palette())

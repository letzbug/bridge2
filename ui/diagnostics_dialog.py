"""Visual adapter diagnostics: which page elements can be detected."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from PySide6.QtGui import QBrush, QColor

from . import styles

STATUS = {"found": ("✓ detected", "green"), "missing": ("✗ not found", "red"), "idle": ("○ idle", "faint"),
          "not_configured": ("– not configured", "faint"), "error": ("! error", "red"), "n/a": ("– n/a", "faint")}


class DiagnosticsDialog(QDialog):
    def __init__(self, parent, bridge, role: str, name: str) -> None:
        super().__init__(parent)
        self.bridge, self.role = bridge, role
        self.ctrl = bridge.controller
        self.setWindowTitle(f"Adapter diagnostics – {name}")
        self.resize(860, 560)
        lay = QVBoxLayout(self)
        self.info = QLabel("Running diagnostics …")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Element", "Status", "Matched selector", "Count", "Detail"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        lay.addWidget(self.table, 2)
        lay.addWidget(QLabel("Latest completed assistant response (preview, extracted text):"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        lay.addWidget(self.preview, 1)
        self.notes = QLabel()
        self.notes.setObjectName("Faint")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run again")
        self.hl_btn = QPushButton("Highlight selected element in browser")
        self.edit_btn = QPushButton("Edit selectors…")
        close = QPushButton("Close")
        for b in (self.run_btn, self.hl_btn, self.edit_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.run_btn.clicked.connect(self.run)
        self.hl_btn.clicked.connect(self.highlight)
        self.edit_btn.clicked.connect(self.edit)
        close.clicked.connect(self.accept)
        self._keys: list[str] = []
        self.run()

    def run(self) -> None:
        self.run_btn.setEnabled(False)
        self.info.setText("Running diagnostics …")
        self.bridge.call(lambda: self.ctrl.diagnose(self.role), self._show, self._error)

    def _error(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.info.setText(f"Diagnostics failed: {msg}")

    def _show(self, report) -> None:
        self.run_btn.setEnabled(True)
        pal = styles.palette()
        auth = {"logged_in": "logged in (detected)", "login_required": "LOGIN REQUIRED (detected)"}.get(report.auth, "unknown")
        verdict = "PASSED – the adapter can operate on this page." if report.passed else \
            "NOT PASSED – automatic transfer stays disabled for this participant."
        self.info.setText(f"<b>{verdict}</b><br>URL: {report.url or '—'} · Authentication: {auth}")
        self.table.setRowCount(len(report.items))
        self._keys = []
        for r, it in enumerate(report.items):
            text, color = STATUS.get(it.status, (it.status, "muted"))
            cells = [it.label, text, it.selector or "—", str(it.count) if it.count else "", it.detail]
            for c, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if c == 1:
                    item.setForeground(QBrush(QColor(pal[color])))
                self.table.setItem(r, c, item)
            self._keys.append(it.key)
        self.preview.setPlainText(report.latest_preview or "")
        self.notes.setText("\n".join(report.notes))

    def highlight(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._keys):
            return
        key = self._keys[row]
        if key == "latest_response":
            key = "assistant_message"
        self.bridge.call(lambda: self.ctrl.highlight(self.role, key),
                         lambda n: self.info.setText(f"Highlighted {n} element(s) in the browser for 4 seconds."),
                         self._error)

    def edit(self) -> None:
        self.accept()
        self.parent().open_settings("providers", self.ctrl.provider_id(self.role))

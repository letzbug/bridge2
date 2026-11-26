"""Research session browser: view, export, delete, compare. Loading never resumes a conversation."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PySide6.QtCore import Qt

from app import paths
from app.security import safe_filename
from research.experiments import compare
from research.export import FORMATS

from .transcript_view import TranscriptView

COLUMNS = [("title", "Session"), ("started_at", "Started"), ("guest_name", "Guest"), ("transfer_mode", "Mode"),
           ("message_count", "Messages"), ("end_state", "End"), ("experiment", "Experiment"),
           ("condition", "Condition"), ("demo", "Demo")]


class SessionsDialog(QDialog):
    def __init__(self, parent, bridge) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.ctrl = bridge.controller
        self.setWindowTitle("Research sessions (local)")
        self.resize(1100, 700)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        split.addWidget(self.table)
        self.view = TranscriptView()
        self.view.placeholder = "Select a session and click View. Viewing never resumes or replays a conversation."
        self.view.render()
        split.addWidget(self.view)
        self.compare_table = QTableWidget(0, 0)
        self.compare_table.hide()
        split.addWidget(self.compare_table)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        self.b_view = QPushButton("View")
        self.b_export = QPushButton("Export selected…")
        self.b_compare = QPushButton("Compare selected")
        self.b_delete = QPushButton("Delete selected")
        self.b_delete.setObjectName("Danger")
        self.b_delete_all = QPushButton("Delete all…")
        self.b_delete_all.setObjectName("Danger")
        close = QPushButton("Close")
        for b in (self.b_view, self.b_export, self.b_compare, self.b_delete, self.b_delete_all):
            row.addWidget(b)
        row.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        row.addWidget(self.status)
        row.addWidget(close)
        lay.addLayout(row)
        self.b_view.clicked.connect(self.view_selected)
        self.b_export.clicked.connect(self.export_selected)
        self.b_compare.clicked.connect(self.compare_selected)
        self.b_delete.clicked.connect(self.delete_selected)
        self.b_delete_all.clicked.connect(self.delete_all)
        self.table.doubleClicked.connect(lambda *_: self.view_selected())
        close.clicked.connect(self.accept)
        self.rows: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        self.bridge.call(self.ctrl.list_sessions, self._fill, lambda m: self.status.setText(m))

    def _fill(self, rows: list[dict]) -> None:
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (key, _) in enumerate(COLUMNS):
                val = row.get(key)
                if key == "demo":
                    val = "simulated" if val else ""
                self.table.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        self.status.setText(f"{len(rows)} session(s)" if self.ctrl.settings.get("research.recording_enabled", True)
                            else "Local recording is disabled in Settings.")

    def _selected(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.rows[r]["session_id"] for r in rows if r < len(self.rows)]

    def view_selected(self) -> None:
        ids = self._selected()
        if not ids:
            return
        self.compare_table.hide()
        self.view.show()
        self.bridge.call(lambda: self.ctrl.load_session(ids[0]),
                         lambda t: self.view.load([e.as_dict() for e in t.entries], [e.as_dict() for e in t.events])
                         if t else None)

    def export_selected(self) -> None:
        ids = self._selected()
        if not ids:
            return

        def got(t):
            if t is None:
                return
            filters = ";;".join(f"{label} (*.{ext})" for ext, label in FORMATS.items())
            default = str(paths.exports_dir() / f"{safe_filename(t.meta.title)}.html")
            paths.exports_dir().mkdir(parents=True, exist_ok=True)
            path, chosen = QFileDialog.getSaveFileName(self, "Export session", default, filters)
            if not path:
                return
            fmt = next((ext for ext, label in FORMATS.items() if chosen.startswith(label)), None)
            if fmt and not path.lower().endswith("." + fmt):
                path += "." + fmt
            self.bridge.call(lambda: self.ctrl.export(path, fmt, t), lambda p: self.status.setText(f"Exported: {p}"),
                             lambda m: QMessageBox.warning(self, "Export", m))
        self.bridge.call(lambda: self.ctrl.load_session(ids[0]), got)

    def compare_selected(self) -> None:
        ids = self._selected()
        if len(ids) < 1:
            return

        async def load_all():
            return [t for t in [await self.ctrl.load_session(i) for i in ids] if t is not None]

        def show(transcripts):
            metrics = compare(transcripts)
            keys = [k for k in metrics[0] if k not in ("session_id", "user_reported")] if metrics else []
            self.compare_table.setColumnCount(len(metrics))
            self.compare_table.setRowCount(len(keys) + 1)
            self.compare_table.setHorizontalHeaderLabels([m["title"] for m in metrics])
            self.compare_table.setVerticalHeaderLabels(keys + ["user-reported"])
            for c, m in enumerate(metrics):
                for r, k in enumerate(keys):
                    self.compare_table.setItem(r, c, QTableWidgetItem("" if m[k] is None else str(m[k])))
                ur = "; ".join(f"{k}={v}" for k, v in m["user_reported"].items() if v)
                self.compare_table.setItem(len(keys), c, QTableWidgetItem(ur))
            self.view.hide()
            self.compare_table.show()
            self.status.setText("Metrics are computed from observed transcript data only.")
        self.bridge.call(load_all, show)

    def delete_selected(self) -> None:
        ids = self._selected()
        if not ids or QMessageBox.question(self, "Delete", f"Delete {len(ids)} session(s)?") != QMessageBox.StandardButton.Yes:
            return

        async def run():
            for i in ids:
                await self.ctrl.delete_session(i)
        self.bridge.call(run, lambda _: self.refresh())

    def delete_all(self) -> None:
        if QMessageBox.question(self, "Delete all", "Delete ALL local research sessions and exports? "
                                "This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        self.bridge.call(self.ctrl.delete_all_research_data, lambda _: self.refresh())

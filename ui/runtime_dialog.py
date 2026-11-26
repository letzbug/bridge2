"""Manage the optional Playwright browser runtime (download only on explicit request)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout

from app.events import EventType
from browser import runtime


class RuntimeDialog(QDialog):
    def __init__(self, parent, bridge) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.ctrl = bridge.controller
        self.setWindowTitle("Browser runtime (optional)")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Automated browser adapters use <b>Playwright's own Firefox build</b>. It is optional: demo mode, "
            "clipboard mode and your installed Firefox work without it. The download comes from Playwright's "
            f"official servers ({runtime.DOWNLOAD_SIZE}) and is stored outside the application folder. "
            "Your installed Firefox and its profiles are not touched.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        lay.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.install_btn = QPushButton("Install Firefox runtime")
        self.install_btn.setObjectName("Primary")
        self.remove_btn = QPushButton("Remove runtime")
        self.remove_btn.setObjectName("Danger")
        close = QPushButton("Close")
        row.addWidget(self.install_btn)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.install_btn.clicked.connect(self.install)
        self.remove_btn.clicked.connect(self.remove)
        close.clicked.connect(self.accept)
        self.bridge.event.connect(self._on_event)
        self.refresh()

    def refresh(self) -> None:
        st = self.ctrl.runtime_status()
        if not st["playwright"]:
            text = f"✗ {st['playwright_error']}"
        elif st["firefox_installed"]:
            text = f"✓ Installed: {', '.join(st['builds'])}<br>Location: <code>{st['path']}</code>"
        else:
            text = f"Not installed.<br>Location after installation: <code>{st['path']}</code>"
        self.status.setText(text)
        self.install_btn.setEnabled(bool(st["playwright"]))
        self.install_btn.setText("Reinstall / update Firefox runtime" if st["firefox_installed"] else
                                 "Install Firefox runtime")
        self.remove_btn.setEnabled(bool(st["firefox_installed"] and st["managed_by_app"]))

    def _on_event(self, ev) -> None:
        if ev.type == EventType.LOG and ev.data.get("source") == "runtime":
            self.output.appendPlainText(ev.data.get("message", ""))

    def install(self) -> None:
        if QMessageBox.question(self, "Download browser runtime",
                                f"Download Playwright's Firefox build ({runtime.DOWNLOAD_SIZE}) now?"
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.install_btn.setEnabled(False)
        self.output.appendPlainText("Starting download …")

        def done(_rc) -> None:
            self.refresh()
            QMessageBox.information(self, "Browser runtime", "The Firefox runtime is installed. Select the "
                                    "'Playwright-managed Firefox' backend in a participant card to use it.")

        def failed(msg: str) -> None:
            self.refresh()
            self.output.appendPlainText(msg)
        self.bridge.call(self.ctrl.install_browser_runtime, done, failed)

    def remove(self) -> None:
        if QMessageBox.question(self, "Remove browser runtime", "Remove the downloaded Firefox runtime? "
                                "Dedicated profiles and logins are kept.") != QMessageBox.StandardButton.Yes:
            return
        self.bridge.call(self.ctrl.remove_browser_runtime,
                         lambda n: (self.output.appendPlainText(f"Removed {n} build(s)."), self.refresh()),
                         lambda m: (self.output.appendPlainText(m), self.refresh()))

    def done(self, r: int) -> None:  # noqa: D401 - Qt override
        try:
            self.bridge.event.disconnect(self._on_event)
        except (RuntimeError, TypeError):
            pass
        super().done(r)

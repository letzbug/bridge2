"""EMERGENCE LAB – AI Conversation Bridge v0.1.1

Built by Frank G – IBM Certified AI Developer

Usage (portable build: EmergenceLab.exe; from source: python main.py):
    (no arguments)            start the desktop application
    --demo                    start with DEMO MODE enabled
    --data-dir FOLDER         use another data folder (must be outside the application folder)
Diagnostics (use EmergenceLab-console.exe to see the output):
    --self-check              core check: no GUI, no browser, no network
    --gui-selftest            real GUI smoke test (temporary data folder, no provider contact)
    --browser-selftest        managed Firefox + Playwright driver against the local mock page
    --install-browser         download the optional Playwright Firefox runtime
    --report FILE             write a JSON report for the commands above
    --smoke-test SECONDS      open the GUI and close it after SECONDS
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _install_crash_handlers(log_dir: Path) -> None:
    import faulthandler
    import logging

    try:
        crash = open(log_dir / "crash.log", "a", encoding="utf-8")  # noqa: SIM115 - kept open for the process
        faulthandler.enable(file=crash)
    except OSError:
        pass

    def hook(exc_type, exc, tb):
        logging.getLogger("emergence-lab").critical("unhandled exception", exc_info=(exc_type, exc, tb))
        if sys.stderr is not None:
            traceback.print_exception(exc_type, exc, tb)
    sys.excepthook = hook


def run_gui(args: argparse.Namespace) -> int:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("PySide6 is not installed. Run install.bat first (or: pip install -r requirements.txt).",
              file=sys.stderr if sys.stderr else None)
        return 2
    from app.first_run import apply_first_run_defaults
    from app.settings import Settings
    from ui import icons, styles
    from ui.main_window import MainWindow
    from ui.qt_bridge import QtBridge

    QApplication.setApplicationName("EMERGENCE LAB")
    QApplication.setOrganizationName("frankG")
    app = QApplication(sys.argv)
    if args.gui_selftest:
        from ui.selftest import run_gui_selftest
        return run_gui_selftest(app, args.report)
    try:
        settings = Settings()
        notes = apply_first_run_defaults(settings)
        if args.demo:
            settings.set("demo_mode", True)
        styles.set_theme(settings.get("theme", "dark"))
        app.setStyleSheet(styles.stylesheet())
        app.setWindowIcon(QIcon(icons.app_glyph(styles.palette()["teal"], 64)))
        bridge = QtBridge(settings)
        win = MainWindow(bridge, settings)
        win.show()
        win.show_startup_notes(notes)
    except Exception:  # noqa: BLE001 - shown to the user, never silently ignored
        QMessageBox.critical(None, "EMERGENCE LAB – startup error", traceback.format_exc())
        raise

    previous_hook = sys.excepthook

    def gui_hook(exc_type, exc, tb):
        previous_hook(exc_type, exc, tb)
        QMessageBox.warning(win, "EMERGENCE LAB – unexpected error",
                            "".join(traceback.format_exception_only(exc_type, exc)).strip()
                            + "\n\nDetails are in the log file. The conversation engine keeps its last safe state.")
    sys.excepthook = gui_hook
    if args.smoke_test:
        def finish() -> None:
            print("GUI SMOKE TEST: window created and event loop running – closing", flush=True)
            win.close()
        QTimer.singleShot(int(args.smoke_test * 1000), finish)
    return app.exec()


def _robust_console() -> None:
    """Console output must never crash the program (e.g. Playwright progress bars on a cp1252 console)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _robust_console()
    parser = argparse.ArgumentParser(description="EMERGENCE LAB – AI Conversation Bridge")
    parser.add_argument("--demo", action="store_true", help="start with demo mode enabled")
    parser.add_argument("--self-check", action="store_true", help="core self-check (no GUI, no network)")
    parser.add_argument("--gui-selftest", action="store_true", help="real GUI smoke test")
    parser.add_argument("--browser-selftest", action="store_true", help="managed Firefox pipeline test (mock page)")
    parser.add_argument("--install-browser", action="store_true", help="download the optional Playwright Firefox")
    parser.add_argument("--headless", action="store_true", help="self-tests only: headless managed browser")
    parser.add_argument("--report", metavar="FILE", help="write a JSON report (self-tests)")
    parser.add_argument("--smoke-test", type=float, default=0, metavar="SECONDS",
                        help="open the GUI and close it after SECONDS")
    parser.add_argument("--data-dir", help="use another local data directory")
    parser.add_argument("--verbose", action="store_true")
    args, _qt_args = parser.parse_known_args(argv)
    if args.data_dir:
        os.environ["EMERGENCE_LAB_HOME"] = str(Path(args.data_dir).resolve())

    from app import paths
    paths.configure_runtime_environment()        # browser runtime location follows the REAL data folder
    if (args.gui_selftest or args.browser_selftest) and not args.data_dir:
        os.environ["EMERGENCE_LAB_HOME"] = tempfile.mkdtemp(prefix="emergence-lab-selftest-")
    if args.headless:
        os.environ["EMERGENCE_LAB_HEADLESS"] = "1"

    from app.logging_setup import setup_logging
    log_file = setup_logging(args.verbose)
    _install_crash_handlers(paths.logs_dir())
    try:
        from app import selftest
        if args.self_check:
            return selftest.self_check(args.report)
        if args.browser_selftest:
            return selftest.browser_selftest(args.report)
        if args.install_browser:
            return selftest.install_browser(args.report)
        return run_gui(args)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print(f"\nStartup failed. Details are in the log file: {log_file}",
              file=sys.stderr if sys.stderr else None)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

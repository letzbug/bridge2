"""GUI smoke test wrapper around ui.selftest.

    python tests/gui_smoke.py          real PySide6 (QT_QPA_PLATFORM decides: native window or offscreen)
    python tests/gui_smoke.py stub     structural check with the PySide6 stand-in (no rendering)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MODE = sys.argv[1] if len(sys.argv) > 1 else "real"
if MODE == "stub":
    sys.path.insert(0, str(ROOT / "tests" / "qt_stub"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EMERGENCE_LAB_HOME"] = tempfile.mkdtemp(prefix="el-gui-")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.selftest import run_gui_selftest  # noqa: E402

if __name__ == "__main__":
    app = QApplication(sys.argv)
    raise SystemExit(run_gui_selftest(app, os.environ.get("EL_GUI_REPORT")))

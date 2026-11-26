"""GUI smoke test (subprocess).

With real PySide6 installed this runs the window offscreen (QT_QPA_PLATFORM=offscreen).
Without PySide6 it runs the structural check with the stand-in in tests/qt_stub
(executes all GUI Python code paths, but renders nothing).
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _real_pyside() -> bool:
    spec = importlib.util.find_spec("PySide6")
    return spec is not None and "qt_stub" not in (spec.origin or "")


def test_gui_smoke(tmp_path):
    mode = "real" if _real_pyside() else "stub"
    report = tmp_path / "gui.json"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8", "EL_GUI_REPORT": str(report)}
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / "gui_smoke.py"), mode], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    print(proc.stdout)
    print(proc.stderr[-3000:])
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    assert "GUI SELF-TEST" in proc.stdout and "PASSED" in proc.stdout
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] and data["qt_stub"] == (mode == "stub")
    assert all(step["ok"] for step in data["steps"])

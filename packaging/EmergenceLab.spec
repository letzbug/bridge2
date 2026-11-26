# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec – EMERGENCE LAB portable Windows x64 distribution (one-folder mode).

    pyinstaller --noconfirm --clean packaging/EmergenceLab.spec      (or packaging/build_portable.ps1)

Variant via environment variable EL_VARIANT:
    core  (default)  GUI, engine, research, exports, clipboard mode, Playwright package + driver.
                     The ~80–100 MB Playwright Firefox build is NOT bundled (optional download).
    audio            core + numpy, sounddevice (PortAudio), faster-whisper (CTranslate2) for the
                     experimental Animated Companion mode. Whisper models are downloaded on request.

Output: dist/<variant>/EmergenceLab-<version>-win-x64[-audio]/
            EmergenceLab.exe            windowed application (double-click)
            EmergenceLab-console.exe    same program with a console, for diagnostics/self-tests
            _internal/                  bundled Python runtime, Qt, Playwright driver, config, assets
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VARIANT = os.environ.get("EL_VARIANT", "core").strip().lower()
if VARIANT not in ("core", "audio"):
    raise SystemExit(f"EL_VARIANT must be 'core' or 'audio', not {VARIANT!r}")

from app import __version__  # noqa: E402

DIST_NAME = f"EmergenceLab-{__version__}-win-x64" + ("-audio" if VARIANT == "audio" else "")
AUDIO_PACKAGES = ["numpy", "sounddevice", "_sounddevice", "_sounddevice_data", "faster_whisper", "ctranslate2",
                  "av", "onnxruntime", "tokenizers", "huggingface_hub"]


def local_modules(*packages):
    """All modules of the application's own packages (belt and braces for lazy imports)."""
    mods = []
    for pkg in packages:
        for py in sorted((ROOT / pkg).rglob("*.py")):
            parts = list(py.relative_to(ROOT).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            mods.append(".".join(parts))
    return mods


def optional(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - optional collection, logged by PyInstaller
        print(f"[EmergenceLab.spec] optional collection skipped: {fn.__name__}{args}: {exc}")
        return []


hiddenimports = local_modules("app", "adapters", "browser", "audio", "research", "ui")
datas = [
    (str(ROOT / "config"), "config"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "README.md"), "."),
]
binaries = []

# Playwright: the Python package plus its driver (driver/node.exe + driver/package). The driver brings its
# own Node.js runtime, so nothing has to be installed on the target computer.
datas += collect_data_files("playwright")
hiddenimports += collect_submodules("playwright")

excludes = ["tkinter", "matplotlib", "IPython", "pytest", "PIL",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"]

if VARIANT == "audio":
    datas += optional(collect_data_files, "faster_whisper")
    datas += optional(collect_data_files, "_sounddevice_data")
    binaries += optional(collect_dynamic_libs, "ctranslate2")
    binaries += optional(collect_dynamic_libs, "_sounddevice_data")
    hiddenimports += optional(collect_submodules, "faster_whisper")
    hiddenimports += optional(collect_submodules, "ctranslate2")
    hiddenimports += ["sounddevice", "_sounddevice", "numpy"]
else:
    excludes += AUDIO_PACKAGES

version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(parents=True, exist_ok=True)
vt = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={vt}, prodvers={vt}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Frank G'),
      StringStruct('FileDescription', 'EMERGENCE LAB - AI Conversation Bridge'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'EmergenceLab'),
      StringStruct('LegalCopyright', 'Frank G - frankG x cameron'),
      StringStruct('OriginalFilename', 'EmergenceLab.exe'),
      StringStruct('ProductName', 'EMERGENCE LAB'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('Comments', 'Built by Frank G - IBM Certified AI Developer')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

common = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # no UPX: avoids broken Qt DLLs and antivirus false positives
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "EmergenceLab.ico"),
    version=str(version_file),
)

gui_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EmergenceLab", console=False, **common)
console_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EmergenceLab-console", console=True, **common)

coll = COLLECT(
    gui_exe,
    console_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=DIST_NAME,
)

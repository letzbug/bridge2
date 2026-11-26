# Changelog

## 0.1.1 – portable Windows distribution

**New**
* Portable Windows x64 edition built with PyInstaller (one-folder): extract the ZIP and double-click
  `EmergenceLab.exe`. No installation, no administrator rights, no Python, no Node.js.
  The Python runtime, PySide6/Qt and the Playwright driver (with its own Node.js runtime) are bundled.
* `EmergenceLab-console.exe` – the same program with a console for diagnostics.
* Two variants: `win-x64` (core) and `win-x64-audio` (adds numpy, sounddevice, faster-whisper).
* Optional Playwright browser runtime: status, install and removal from the app
  (Settings → Browser & windows → Browser runtime) or with `--install-browser`. Stored in the data folder,
  never inside the application folder.
* First-run defaults: without the browser runtime, participants start with the installed Firefox
  (dedicated profiles, clipboard workflow) or with *No browser*.
* Portable data mode: an `EmergenceLab.portable` file next to the exe puts all data into `EmergenceLab-Data`
  next to the application folder. Data locations inside the application folder are rejected.
* Built-in self-tests: `--gui-selftest` (real PySide6 GUI smoke test), `--browser-selftest` (managed Firefox
  pipeline against the local mock page), `--self-check`, all with `--report <file.json>`.
* GitHub Actions workflow on a Windows runner: source tests with real PySide6 and Playwright Firefox, frozen build,
  tests of the frozen executables with Python/Node.js removed from PATH, a check that the application folder is
  unchanged, ZIP artifacts, and a draft release on `v*` tags.
* Application icon, Windows version information, `build_portable.bat` / `packaging/build_portable.ps1`.

**Changed**
* `app/paths.py` separates read-only resources, the program folder and the data folder.
* Demo timings are configurable (`demo.think_seconds`, `demo.stream_seconds`).
* Console output can no longer crash on characters the Windows code page cannot encode.
* Unhandled GUI exceptions are logged and shown; hard crashes go to `logs/crash.log`.

**Unchanged**
* All v0.1.0 functionality, defaults, safety rules (no CAPTCHA/stealth workarounds, per-provider automation
  permission, existing Firefox profiles never touched) and tests.

## 0.1.0

Initial release: conversation engine, demo mode, clipboard workflow, Playwright-managed and installed-Firefox
backends, provider adapters (unvalidated candidates), research recording and exports, experimental audio companion
mode, PySide6 dashboard, install/start scripts, test-suite.

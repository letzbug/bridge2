# Portable Windows distribution – build, CI and layout

## Goal
Extract `EmergenceLab-<version>-win-x64.zip`, double-click `EmergenceLab.exe`, done. There is no installer, and no
administrator rights, Python or Node.js are needed on the target computer.

## Layout

```
EmergenceLab-0.1.1-win-x64\
  EmergenceLab.exe            windowed application
  EmergenceLab-console.exe    same program with console (diagnostics, self-tests)
  _internal\                  bundled CPython, PySide6/Qt, Playwright package + driver (node.exe), config, assets, docs
  READ-ME-FIRST.txt  README.md  CHANGELOG.md  BUILD-INFO.txt
```

Nothing is ever written into this folder. Data locations, in order of priority:

| | Location |
|---|---|
| `--data-dir <folder>` / `EMERGENCE_LAB_HOME` | that folder, unless it is inside the application folder (then rejected) |
| `EmergenceLab.portable` file next to the exe | `..\EmergenceLab-Data` (sibling of the application folder) |
| default | `%LOCALAPPDATA%\EmergenceLab` |

The data folder holds `settings.json`, `providers.user.json`, `research\sessions.sqlite3`, `logs\`, `exports\`,
`profiles\` (dedicated browser profiles) and `browser-runtime\` (optional Playwright Firefox) plus `audio-models\`.

## What is and is not bundled

| Component | Core ZIP | Audio ZIP |
|---|---|---|
| Python runtime, PySide6/Qt | bundled | bundled |
| Playwright package + driver (own Node.js) | bundled | bundled |
| Playwright Firefox build (~80–100 MB) | optional download | optional download |
| numpy, sounddevice/PortAudio, faster-whisper/CTranslate2 | not included | bundled |
| Whisper speech models | – | downloaded on request |

The installed Firefox is used as-is for the clipboard workflow, always with dedicated profiles. Your normal
Firefox profile is never read or modified.

## Building locally (Windows)

```
build_portable.bat            core variant
build_portable.bat audio      audio variant
```
or `powershell -ExecutionPolicy Bypass -File packaging\build_portable.ps1 -Variant core [-SkipZip] [-ZipOnly]`.

The script creates `build\venv-<variant>`, installs `packaging\requirements-build.txt` plus the runtime
requirements, runs `pyinstaller packaging\EmergenceLab.spec` (variant via `EL_VARIANT`), adds the top-level
documents and `BUILD-INFO.txt`, verifies the layout (exes, config, mock page, `playwright\driver\node.exe`, no user
data) and writes `dist\EmergenceLab-<version>-win-x64[-audio].zip`.

## GitHub Actions (`.github/workflows/windows-portable.yml`)

1. **source-tests** (`windows-latest`): installs the requirements, installs Playwright Firefox *for the test machine
   only*, runs the full pytest suite with real PySide6 (offscreen) and real Firefox, then the GUI self-test on the
   runner's native Windows desktop.
2. **build** (matrix `core`, `audio`): builds the one-folder app, takes a SHA-256 snapshot of every file, then tests
   the **frozen** executables with Python and Node.js removed from `PATH` and all `PYTHON*` variables unset:
   * `EmergenceLab-console.exe --self-check` (asserts: frozen, data outside the app folder; the audio build also
     asserts working audio + transcription packages)
   * `EmergenceLab.exe --gui-selftest`: a real PySide6 GUI smoke test on the native desktop, with the Qt
     offscreen platform as fallback (reported as a warning)
   * core only: `--install-browser` through the bundled driver, then `--browser-selftest`. Two managed Firefox
     windows with dedicated profiles run an automated conversation between two local mock pages (headless retry
     as fallback)
   * verifies that the application folder is byte-for-byte unchanged and that logs and the browser runtime are in
     `%LOCALAPPDATA%\EmergenceLab`
   * creates the ZIP and uploads it as artifact `EmergenceLab-<version>-win-x64[-audio]`; reports and logs go to
     `reports-<variant>`
3. **release** (tags `v*`): draft GitHub release with both ZIPs.

GitHub wraps every artifact in its own ZIP: the download `EmergenceLab-0.1.1-win-x64.zip` contains the portable
ZIP. The release assets are the plain portable ZIPs.

## Not covered by CI
* Real provider websites and accounts – never contacted by any automated step.
* Code signing – the executables are unsigned.
* Real audio hardware – the audio build is checked for importable packages only.

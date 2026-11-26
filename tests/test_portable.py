"""Portable distribution: frozen paths, data separation, optional browser runtime, first run,
PyInstaller spec (dry run with a stand-in PyInstaller API) and the Windows CI workflow."""

import asyncio
import importlib
import json
import os
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------------- frozen paths
@pytest.fixture
def frozen(tmp_path, monkeypatch):
    install = tmp_path / "Apps" / "EmergenceLab-0.1.1-win-x64"
    internal = install / "_internal"
    internal.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "EmergenceLab.exe"))
    for var in ("EMERGENCE_LAB_HOME", "PLAYWRIGHT_BROWSERS_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "LocalAppData"))
    from app import paths
    importlib.reload(paths)
    yield paths, install, internal
    monkeypatch.undo()
    importlib.reload(paths)


def test_frozen_layout_separates_resources_program_and_data(frozen):
    paths, install, internal = frozen
    assert paths.FROZEN
    assert paths.RESOURCE_DIR == internal.resolve()
    assert paths.INSTALL_DIR == install.resolve()
    assert paths.CONFIG_DIR == internal.resolve() / "config"
    assert not paths.is_inside(paths.data_dir(), install)
    assert paths.data_dir() == paths.default_data_dir()
    assert paths.resolve_app_url("@app/assets/mock_chat.html").startswith("file://")
    assert "_internal" in paths.resolve_app_url("@app/assets/mock_chat.html")


def test_portable_marker_puts_data_next_to_not_inside_the_app_folder(frozen):
    paths, install, _ = frozen
    (install / paths.PORTABLE_MARKER).write_text("")
    assert paths.portable_mode()
    assert paths.data_dir() == (install.parent / "EmergenceLab-Data").resolve()
    assert not paths.is_inside(paths.data_dir(), install)
    assert "portable" in paths.data_location_description()


def test_data_dir_inside_app_folder_is_rejected(frozen, monkeypatch):
    paths, install, _ = frozen
    monkeypatch.setenv("EMERGENCE_LAB_HOME", str(install / "data"))
    assert paths.data_dir() == paths.default_data_dir()


def test_frozen_runtime_environment_points_into_data_dir(frozen, monkeypatch):
    paths, _, _ = frozen
    paths.configure_runtime_environment()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(paths.data_dir() / "browser-runtime")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "D:/my-browsers")
    paths.configure_runtime_environment()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "D:/my-browsers"     # explicit user choice wins


def test_source_mode_keeps_playwright_default(monkeypatch):
    from app import paths
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert not paths.FROZEN
    paths.configure_runtime_environment()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


# --------------------------------------------------------------------------------------------- runtime
def _fake_build(root: Path, name: str) -> Path:
    d = root / name / "firefox"
    d.mkdir(parents=True)
    (d / ("firefox.exe" if sys.platform == "win32" else "firefox")).write_text("")
    return root / name


def test_runtime_detection_and_removal_only_inside_own_data_dir(tmp_path, monkeypatch):
    from browser import runtime
    data = tmp_path / "data"
    monkeypatch.setenv("EMERGENCE_LAB_HOME", str(data))
    browsers = data / "browser-runtime"
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    assert not runtime.firefox_installed()
    _fake_build(browsers, "firefox-1490")
    (browsers / "chromium-1200").mkdir()
    assert runtime.firefox_installed() and runtime.status()["builds"] == ["firefox-1490"]
    assert runtime.removable()
    assert runtime.remove_firefox() == 1
    assert not runtime.firefox_installed() and (browsers / "chromium-1200").exists()   # others untouched
    shared = tmp_path / "shared-ms-playwright"
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(shared))
    _fake_build(shared, "firefox-1490")
    assert not runtime.removable()
    with pytest.raises(RuntimeError):
        runtime.remove_firefox()
    assert runtime.firefox_installed()


def test_runtime_install_uses_bundled_driver(tmp_path, monkeypatch):
    from browser import runtime
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "rt"))
    calls = {}

    class FakeProc:
        stdout = iter(["Downloading Firefox 140 ...\n", "|■■■■■■| 100% of 90 MiB\n", "\n"])

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        calls["cmd"], calls["env"] = cmd, kwargs.get("env", {})
        return FakeProc()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    lines = []
    assert runtime.install_firefox(lines.append) == 0
    assert calls["cmd"][-2:] == ["install", "firefox"]
    assert calls["cmd"][0].endswith(("node", "node.exe")) and calls["cmd"][1].endswith("cli.js")
    assert "playwright" in calls["cmd"][0].replace("\\", "/")            # node from the Playwright package
    assert calls["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "rt")
    assert any("100%" in ln for ln in lines) and lines[-1] == "Firefox runtime installed."


def test_missing_runtime_hint_depends_on_edition(frozen):
    from browser import runtime
    assert "Settings" in runtime.missing_runtime_hint()
    assert "install.bat" not in runtime.missing_runtime_hint()


# --------------------------------------------------------------------------------------------- first run
@pytest.mark.parametrize("firefox_found, expected", [(True, "standard"), (False, "none")])
def test_first_run_defaults_without_runtime(tmp_path, monkeypatch, firefox_found, expected):
    from app import first_run
    from app.settings import Settings
    from browser import manual_backend, runtime
    monkeypatch.setattr(runtime, "firefox_installed", lambda: False)
    monkeypatch.setattr(manual_backend, "find_firefox", lambda _p="": Path("firefox.exe") if firefox_found else None)
    s = Settings(path=tmp_path / "settings.json")
    assert s.is_new
    notes = first_run.apply_first_run_defaults(s)
    assert notes and s.get("host.browser_backend") == expected == s.get("guest.browser_backend")
    again = Settings(path=tmp_path / "settings.json")
    assert not again.is_new and first_run.apply_first_run_defaults(again) == []


def test_first_run_keeps_managed_backend_when_runtime_installed(tmp_path, monkeypatch):
    from app import first_run
    from app.settings import Settings
    from browser import runtime
    monkeypatch.setattr(runtime, "firefox_installed", lambda: True)
    s = Settings(path=tmp_path / "settings.json")
    first_run.apply_first_run_defaults(s)
    assert s.get("host.browser_backend") == "managed"


# --------------------------------------------------------------------------------------------- self-tests
def test_core_self_check_report(tmp_path, monkeypatch):
    monkeypatch.setenv("EMERGENCE_LAB_HOME", str(tmp_path / "data"))
    import main
    report = tmp_path / "r.json"
    assert main.main(["--self-check", "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] and data["data_outside_install_dir"] and data["frozen"] is False
    assert {s["step"] for s in data["steps"]} >= {"resources", "provider registry", "demo conversation"}


def test_browser_selftest_logic_with_chromium_standing_in(tmp_path, monkeypatch):
    pytest.importorskip("playwright.async_api")
    from app import selftest
    from browser import firefox_backend, runtime
    monkeypatch.setenv("EMERGENCE_LAB_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("EMERGENCE_LAB_HEADLESS", "1")
    real_ff = runtime.firefox_installed()
    if not real_ff:
        monkeypatch.setattr(runtime, "firefox_installed", lambda: True)
        original = firefox_backend.PlaywrightHub.get

        async def chromium_get(self):
            pw = await original(self)
            return types.SimpleNamespace(firefox=pw.chromium)
        monkeypatch.setattr(firefox_backend.PlaywrightHub, "get", chromium_get)
    report = selftest.base_report("browser-selftest")
    try:
        ok = asyncio.run(asyncio.wait_for(selftest._browser_selftest(report), 180))
    except Exception as exc:  # noqa: BLE001
        if "Executable doesn't exist" in str(exc) or "Host system is missing" in str(exc):
            pytest.skip(f"no usable Playwright browser: {exc}")
        raise
    assert ok, json.dumps(report["steps"], indent=1)
    assert any("automated conversation" in s["step"] and s["ok"] for s in report["steps"])


# --------------------------------------------------------------------------------------------- spec dry run
class _Recorder:
    def __init__(self):
        self.exes, self.collect, self.analysis = [], None, None


def _run_spec(variant: str, monkeypatch) -> _Recorder:
    rec = _Recorder()
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda pkg, **k: [(f"/site-packages/{pkg}/data", pkg)]
    hooks.collect_dynamic_libs = lambda pkg, **k: [(f"/site-packages/{pkg}/x.dll", pkg)]
    hooks.collect_submodules = lambda pkg, **k: [pkg, f"{pkg}.sub"]
    for name, mod in (("PyInstaller", types.ModuleType("PyInstaller")),
                      ("PyInstaller.utils", types.ModuleType("PyInstaller.utils")), ("PyInstaller.utils.hooks", hooks)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setenv("EL_VARIANT", variant)

    class Analysis:
        def __init__(self, scripts, **kw):
            rec.analysis = {"scripts": scripts, **kw}
            self.pure, self.scripts, self.binaries, self.datas = [], scripts, kw["binaries"], kw["datas"]

    def EXE(*args, **kw):  # noqa: N802 - PyInstaller API name
        rec.exes.append(kw)
        return kw

    def COLLECT(*args, **kw):  # noqa: N802
        rec.collect = {"args": args, **kw}

    spec = ROOT / "packaging" / "EmergenceLab.spec"
    code = compile(spec.read_text(encoding="utf-8"), str(spec), "exec")
    exec(code, {"SPECPATH": str(spec.parent), "Analysis": Analysis, "PYZ": lambda pure: "pyz", "EXE": EXE,
                "COLLECT": COLLECT, "__file__": str(spec)})
    return rec


@pytest.mark.parametrize("variant", ["core", "audio"])
def test_pyinstaller_spec_dry_run(variant, monkeypatch):
    from app import __version__
    rec = _run_spec(variant, monkeypatch)
    names = {e["name"]: e for e in rec.exes}
    assert set(names) == {"EmergenceLab", "EmergenceLab-console"}
    assert names["EmergenceLab"]["console"] is False and names["EmergenceLab-console"]["console"] is True
    for e in rec.exes:
        assert e["exclude_binaries"] is True and e["upx"] is False         # one-folder mode, no UPX
        assert Path(e["icon"]).is_file() and Path(e["version"]).is_file()
        assert __version__ in Path(e["version"]).read_text(encoding="utf-8")
    expected = f"EmergenceLab-{__version__}-win-x64" + ("-audio" if variant == "audio" else "")
    assert rec.collect["name"] == expected
    datas = rec.analysis["datas"]
    for src, _dest in datas:
        if not src.startswith("/site-packages"):
            assert Path(src).exists(), src
    assert ("playwright" in {d for _, d in datas})                         # driver bundled
    hidden = rec.analysis["hiddenimports"]
    for mod in ("app.engine", "adapters.chatgpt", "browser.runtime", "ui.selftest", "research.export"):
        assert mod in hidden
    for mod in hidden:
        if mod.split(".")[0] in ("app", "adapters", "browser", "audio", "research", "ui"):
            rel = Path(*mod.split("."))
            assert (ROOT / rel).with_suffix(".py").exists() or (ROOT / rel / "__init__.py").exists(), mod
    excludes = rec.analysis["excludes"]
    if variant == "core":
        assert "numpy" in excludes and "faster_whisper" in excludes
    else:
        assert "numpy" not in excludes and "faster_whisper" in hidden


def test_spec_rejects_unknown_variant(monkeypatch):
    with pytest.raises(SystemExit):
        _run_spec("everything", monkeypatch)


# --------------------------------------------------------------------------------------------- CI workflow
def test_windows_workflow_structure():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "windows-portable.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    assert "workflow_dispatch" in triggers and "push" in triggers
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    assert jobs["source-tests"]["runs-on"] == "windows-latest"
    build = jobs["build"]
    assert build["runs-on"] == "windows-latest" and build["needs"] == "source-tests"
    assert build["strategy"]["matrix"]["variant"] == ["core", "audio"]
    for job in jobs.values():
        assert "runner." not in json.dumps(job.get("env", {})), "runner context is not allowed in job env"
    text = json.dumps(build["steps"])
    for needle in ("build_portable.ps1", "--self-check", "--gui-selftest", "--browser-selftest",
                   "--install-browser", "snapshot-before", "upload-artifact", "-ZipOnly", "SystemRoot"):
        assert needle in text, needle
    uploads = [s for s in build["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert any(".zip" in s["with"]["path"] for s in uploads)
    src = json.dumps(jobs["source-tests"]["steps"])
    assert "pytest" in src and "gui_smoke.py real" in src and "playwright install firefox" in src
    assert jobs["release"]["permissions"] == {"contents": "write"}


def test_scripts_are_ascii_and_batch_files_crlf():
    for f in ["install.bat", "start.bat", "install_audio.bat", "build_portable.bat", "packaging/build_portable.ps1"]:
        data = (ROOT / f).read_bytes()
        assert all(b < 128 for b in data), f"{f} must be ASCII (Windows PowerShell 5.1 / cmd)"
        if f.endswith(".bat"):
            assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), f"{f} must use CRLF"

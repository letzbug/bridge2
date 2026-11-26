"""First-run defaults.

If the optional Playwright browser runtime is not installed, new installations start
with the installed-Firefox backend (clipboard workflow) – or with no managed browser at
all when no Firefox is found – so the application is usable immediately.
"""

from __future__ import annotations

from .settings import Settings


def apply_first_run_defaults(settings: Settings) -> list[str]:
    if not settings.is_new:
        return []
    from browser import runtime
    from browser.manual_backend import find_firefox

    notes: list[str] = []
    if not runtime.firefox_installed():
        has_firefox = find_firefox(settings.get("browser.firefox_path", "")) is not None
        backend = "standard" if has_firefox else "none"
        for role in ("host", "guest"):
            settings.set(f"{role}.browser_backend", backend)
        notes.append("The optional Playwright browser runtime is not installed, so both participants start with "
                     + ("your installed Firefox (dedicated profiles, clipboard workflow)." if has_firefox else
                        "the clipboard workflow (no Firefox was found – use any browser window).")
                     + " Automation can be added later: Settings → Browser & windows → Browser runtime.")
    settings.save()
    settings.is_new = False
    return notes

"""Provider configuration loading (shipped defaults + local user overrides).

Selectors are data, not code: users update them in
<data dir>/providers.user.json (Settings > Providers) without editing Python.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import paths

log = logging.getLogger(__name__)

SELECTOR_KEYS = ("input", "send_button", "assistant_message", "user_message", "generating", "stop_button",
                 "completion_indicator", "login_required", "error_banner")

SELECTOR_LABELS = {
    "input": "Message input",
    "send_button": "Send control",
    "assistant_message": "Assistant message container",
    "user_message": "User message container",
    "generating": "Generation status",
    "stop_button": "Stop control",
    "completion_indicator": "Completion indicator",
    "login_required": "Login-required indicator",
    "error_banner": "Error / rate-limit banner",
}

GUEST_CHOICES = ["gemini", "claude", "grok", "mistral", "vibe", "companion", "custom"]
FALLBACK_APPEND_KEYS = ("input", "send_button", "error_banner")


class ProviderConfigError(ValueError):
    pass


@dataclass
class ProviderConfig:
    id: str
    label: str
    kind: str = "browser"                 # browser | audio
    url: str = ""
    url_editable: bool = False
    host_patterns: list[str] = field(default_factory=list)
    selectors: dict[str, list[str]] = field(default_factory=dict)
    message_id_attributes: list[str] = field(default_factory=list)
    extract_exclude: list[str] = field(default_factory=list)
    extract_mode: str = "markdown"        # markdown | innertext
    rate_limit_text_patterns: list[str] = field(default_factory=list)
    login_url_patterns: list[str] = field(default_factory=list)
    conversation_id_patterns: list[str] = field(default_factory=list)
    input_method: str = "fill"            # fill | insert_text
    send_method: str = "click_or_enter"   # click | enter | click_or_enter
    stability_ms: int = 1500
    poll_ms: int = 300
    submit_verify_seconds: float = 8.0
    max_input_chars: int = 30000
    newness_by_hash: bool = False
    automation: dict[str, str] = field(default_factory=dict)
    validation: dict[str, str] = field(default_factory=dict)
    overridden: bool = False

    def candidates(self, key: str) -> list[str]:
        return list(self.selectors.get(key, []))

    @property
    def validated(self) -> bool:
        return self.validation.get("status") == "validated"

    @property
    def automation_policy(self) -> str:
        return self.automation.get("policy", "review_terms")


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        if isinstance(it, str) and it.strip() and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def validate_provider_dict(pid: str, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ProviderConfigError(f"{pid}: provider entry must be an object")
    sel = data.get("selectors", {})
    if not isinstance(sel, dict):
        raise ProviderConfigError(f"{pid}: 'selectors' must be an object")
    for key, val in sel.items():
        if key not in SELECTOR_KEYS:
            raise ProviderConfigError(f"{pid}: unknown selector key '{key}' (allowed: {', '.join(SELECTOR_KEYS)})")
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise ProviderConfigError(f"{pid}: selectors.{key} must be a list of strings")
    for key in ("stability_ms", "poll_ms", "max_input_chars"):
        if key in data and (not isinstance(data[key], int) or data[key] <= 0):
            raise ProviderConfigError(f"{pid}: {key} must be a positive integer")
    if data.get("input_method", "fill") not in ("fill", "insert_text"):
        raise ProviderConfigError(f"{pid}: input_method must be 'fill' or 'insert_text'")
    if data.get("send_method", "click_or_enter") not in ("click", "enter", "click_or_enter"):
        raise ProviderConfigError(f"{pid}: send_method must be click, enter or click_or_enter")


class ProviderRegistry:
    def __init__(self, defaults_path: Path | None = None, user_path: Path | None = None) -> None:
        self.defaults_path = defaults_path or (paths.CONFIG_DIR / "providers.json")
        self.user_path = user_path or paths.user_providers_path()
        self.reload()

    def reload(self) -> None:
        self._defaults = json.loads(self.defaults_path.read_text(encoding="utf-8"))
        self._user: dict[str, Any] = {"providers": {}}
        if self.user_path.exists():
            try:
                loaded = json.loads(self.user_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("providers"), dict):
                    for pid, entry in loaded["providers"].items():
                        validate_provider_dict(pid, entry)
                    self._user = loaded
            except (ValueError, ProviderConfigError) as exc:
                log.error("ignoring invalid local provider overrides %s: %s", self.user_path, exc)
                self.load_error = str(exc)
                return
        self.load_error = ""

    # ------------------------------------------------------------------------------
    def ids(self) -> list[str]:
        return list(self._defaults["providers"].keys())

    def raw_default(self, pid: str) -> dict[str, Any]:
        return copy.deepcopy(self._defaults["providers"][pid])

    def raw_override(self, pid: str) -> dict[str, Any]:
        return copy.deepcopy(self._user.get("providers", {}).get(pid, {}))

    def get(self, pid: str) -> ProviderConfig:
        if pid not in self._defaults["providers"]:
            raise KeyError(f"unknown provider '{pid}'")
        base = self.raw_default(pid)
        override = self.raw_override(pid)
        generic = self._defaults.get("generic", {})
        merged = {**base, **{k: v for k, v in override.items() if k != "selectors"}}
        selectors: dict[str, list[str]] = {}
        base_sel = base.get("selectors", {})
        over_sel = override.get("selectors", {})
        inherit = merged.get("inherit_generic", False)
        generic_sel = generic.get("selectors", {})
        for key in SELECTOR_KEYS:
            own = over_sel[key] if key in over_sel else base_sel.get(key, [])
            if inherit:
                # Harmless fallbacks are appended; status-type selectors (generating, stop, …) are
                # only used when the provider defines none, to avoid false "still generating" signals.
                if key in FALLBACK_APPEND_KEYS:
                    own = own + generic_sel.get(key, [])
                elif not own:
                    own = generic_sel.get(key, [])
            selectors[key] = _dedupe(own)
        exclude = merged.get("extract_exclude") or generic.get("extract_exclude", [])
        patterns = merged.get("rate_limit_text_patterns") or generic.get("rate_limit_text_patterns", [])
        known = set(ProviderConfig.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in merged.items() if k in known and k not in ("selectors",)}
        cfg = ProviderConfig(id=pid, selectors=selectors, **{k: v for k, v in kwargs.items() if k != "id"})
        cfg.extract_exclude = list(exclude)
        cfg.rate_limit_text_patterns = [p.lower() for p in patterns]
        cfg.overridden = bool(override)
        cfg.url = paths.resolve_app_url(cfg.url) if cfg.url else ""
        return cfg

    def save_override(self, pid: str, override: dict[str, Any]) -> None:
        validate_provider_dict(pid, override)
        data = {"schema_version": 1, "providers": dict(self._user.get("providers", {}))}
        if override:
            data["providers"][pid] = override
        else:
            data["providers"].pop(pid, None)
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.user_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.user_path)
        self.reload()

    def reset_override(self, pid: str) -> None:
        self.save_override(pid, {})


def adapter_class_for(pid: str):
    """Map provider ids to their independent adapter classes."""
    from . import chatgpt, claude, custom, gemini, grok, mistral, mock, vibe

    return {
        "chatgpt": chatgpt.ChatGPTAdapter,
        "gemini": gemini.GeminiAdapter,
        "claude": claude.ClaudeAdapter,
        "grok": grok.GrokAdapter,
        "mistral": mistral.MistralAdapter,
        "vibe": vibe.VibeAdapter,
        "custom": custom.CustomAdapter,
        "mock": mock.MockPageAdapter,
    }[pid]

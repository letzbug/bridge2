"""JSON settings: shipped defaults (config/defaults.json) merged with local settings.json."""

from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Settings:
    def __init__(self, path: Path | None = None, defaults_path: Path | None = None) -> None:
        self.path = path or paths.settings_path()
        self.defaults_path = defaults_path or (paths.CONFIG_DIR / "defaults.json")
        self._lock = threading.RLock()
        self.defaults = json.loads(self.defaults_path.read_text(encoding="utf-8"))
        self.load_error = ""
        self.is_new = not self.path.exists()
        user: dict[str, Any] = {}
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(user, dict):
                    raise ValueError("settings root must be an object")
            except ValueError as exc:
                self.load_error = f"Local settings could not be read and were ignored: {exc}"
                log.error(self.load_error)
                user = {}
        self.data = deep_merge(self.defaults, user)

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted: str, value: Any) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = copy.deepcopy(value)

    def update(self, section: str, values: dict[str, Any]) -> None:
        with self._lock:
            node = self.data.setdefault(section, {})
            node.update(copy.deepcopy(values))

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

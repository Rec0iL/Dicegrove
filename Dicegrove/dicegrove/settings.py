"""Persistent settings (JSON in ~/.config/Dicegrove)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core import OPTION_DEFAULTS

if os.name == "nt":  # Windows: %APPDATA%\Dicegrove
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Dicegrove"
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Dicegrove"

DEFAULTS: dict[str, Any] = {
    "outputMode": "source",     # source (next to the original) | custom
    "customDir": "",
    "overwrite": "rename",      # rename | overwrite
    "theme": "auto",            # auto (follow system) | light | dark
    "lowPower": False,          # calmer background animation
    "lastDir": "",              # last folder something was dropped from
    **OPTION_DEFAULTS,
}



def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


class Store:
    def __init__(self) -> None:
        self.settings_path = CONFIG_DIR / "settings.json"
        self.data: dict[str, Any] = {**DEFAULTS}
        loaded = _read(self.settings_path, {})
        if isinstance(loaded, dict):
            self.data.update({k: v for k, v in loaded.items() if k in DEFAULTS})

    def set(self, key: str, value: Any) -> bool:
        if key not in DEFAULTS or self.data.get(key) == value:
            return False
        self.data[key] = value
        _write(self.settings_path, self.data)
        return True


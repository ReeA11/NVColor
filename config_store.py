"""Load / save config.json next to the app."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_PRESET = {
    "brightness": 0.5,
    "contrast": 0.5,
    "gamma": 1.0,
    "vibrance": 50,
    "hue": 0,
}

# Minimal bootstrap for first launch only. User presets live in config.json.
DEFAULT_CONFIG: dict[str, Any] = {
    "apply_all_displays": False,
    "start_minimized_to_tray": True,
    "notify_on_switch": True,
    "ui_theme": "dark",
    "ui_language": "en",
    "watch": {
        "enabled": False,
        "process_names": [],
        "preset": "Default",
        "on_exit_preset": "Default",
        "poll_ms": 1500,
    },
    "hotkeys": {},
    "presets": {
        "Default": dict(DEFAULT_PRESET),
    },
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        cfg = deepcopy(DEFAULT_CONFIG)
        save_config(cfg)
        return cfg
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return normalize_config(data)


def save_config(cfg: dict[str, Any]) -> None:
    write_config_file(config_path(), cfg)


def write_config_file(path: Path, cfg: dict[str, Any]) -> None:
    """Atomic write — same JSON shape as dist/config.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix="nvcolor_cfg_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_config_file(path: Path) -> dict[str, Any]:
    """Load and validate a config.json (import / external file)."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    presets = data.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise ValueError("Config must include a non-empty 'presets' object")
    for name, raw in presets.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Preset names must be non-empty strings")
        if not isinstance(raw, dict):
            raise ValueError(f"Preset '{name}' must be an object")
        for key in ("brightness", "contrast", "gamma", "vibrance", "hue"):
            if key in raw and not isinstance(raw[key], (int, float)):
                raise ValueError(f"Preset '{name}.{key}' must be a number")
    if "hotkeys" in data and not isinstance(data["hotkeys"], dict):
        raise ValueError("'hotkeys' must be an object")
    if "watch" in data and not isinstance(data["watch"], dict):
        raise ValueError("'watch' must be an object")
    return normalize_config(data)


def normalize_config(data: dict[str, Any]) -> dict[str, Any]:
    """
    Build runtime config from file data.

    presets / hotkeys come only from the file (not merged with sample presets).
    Missing Default is always ensured. Other missing top-level keys come from
    DEFAULT_CONFIG scaffold.
    """
    cfg = deepcopy(DEFAULT_CONFIG)

    for key in ("apply_all_displays", "start_minimized_to_tray", "notify_on_switch", "ui_theme", "ui_language"):
        if key in data:
            cfg[key] = data[key]

    lang = str(cfg.get("ui_language") or "en").lower()
    cfg["ui_language"] = "ru" if lang.startswith("ru") else "en"

    watch = data.get("watch")
    if isinstance(watch, dict):
        cfg["watch"] = _merge(deepcopy(DEFAULT_CONFIG["watch"]), watch)

    presets = data.get("presets")
    cleaned: dict[str, Any] = {}
    if isinstance(presets, dict):
        for name, raw in presets.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(raw, dict):
                continue
            cleaned[name.strip()] = {
                "brightness": float(raw.get("brightness", 0.5)),
                "contrast": float(raw.get("contrast", 0.5)),
                "gamma": float(raw.get("gamma", 1.0)),
                "vibrance": max(0, min(100, int(round(float(raw.get("vibrance", 50)))))),
                "hue": max(0, min(360, int(round(float(raw.get("hue", 0)))))),
            }
    if "Default" not in cleaned:
        cleaned["Default"] = dict(DEFAULT_PRESET)
    cfg["presets"] = cleaned

    # Point watch presets at something that exists
    if cfg["watch"].get("preset") not in cleaned:
        cfg["watch"]["preset"] = "Default"
    if cfg["watch"].get("on_exit_preset") not in cleaned:
        cfg["watch"]["on_exit_preset"] = "Default"

    hotkeys = data.get("hotkeys")
    if isinstance(hotkeys, dict):
        from hotkeys import format_hotkey

        cleaned_hk: dict[str, str] = {}
        for k, v in hotkeys.items():
            if not isinstance(k, str) or not k.strip() or v is None or not str(v).strip():
                continue
            # Drop hotkeys for presets that no longer exist
            if k.strip() not in cleaned:
                continue
            try:
                cleaned_hk[k.strip()] = format_hotkey(str(v))
            except Exception:
                continue
        cfg["hotkeys"] = cleaned_hk
    else:
        cfg["hotkeys"] = {}

    return cfg


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge(base[key], value)
        else:
            base[key] = value
    return base

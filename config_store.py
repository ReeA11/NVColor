"""Load / save config.json next to the app."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
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
        "poll_ms": 1500,
        "rules": [],
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


def _new_rule_id() -> str:
    return f"rule_{int(time.time() * 1000) % 10_000_000_000}"


def normalize_watch_rule(raw: dict[str, Any], *, presets: set[str], fallback_id: str | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    procs_raw = raw.get("process_names") or []
    if isinstance(procs_raw, str):
        procs_raw = [p.strip() for p in procs_raw.replace(";", ",").split(",") if p.strip()]
    process_names = []
    if isinstance(procs_raw, list):
        for p in procs_raw:
            if isinstance(p, str) and p.strip():
                process_names.append(p.strip())
    name = str(raw.get("name") or "").strip()
    if not name:
        name = process_names[0] if process_names else "App"
    on_start = str(raw.get("on_start") or raw.get("preset") or "Default").strip() or "Default"
    on_exit = str(raw.get("on_exit") or raw.get("on_exit_preset") or "Default").strip() or "Default"
    if on_start not in presets:
        on_start = "Default"
    if on_exit not in presets:
        on_exit = "Default"
    rid = str(raw.get("id") or fallback_id or _new_rule_id()).strip() or _new_rule_id()
    return {
        "id": rid,
        "name": name,
        "enabled": bool(raw.get("enabled", True)),
        "process_names": process_names,
        "on_start": on_start,
        "on_exit": on_exit,
    }


def normalize_watch(watch: dict[str, Any] | None, *, presets: set[str]) -> dict[str, Any]:
    base = deepcopy(DEFAULT_CONFIG["watch"])
    if not isinstance(watch, dict):
        return base

    base["enabled"] = bool(watch.get("enabled", False))
    try:
        base["poll_ms"] = max(300, int(watch.get("poll_ms", 1500)))
    except Exception:
        base["poll_ms"] = 1500

    rules_out: list[dict[str, Any]] = []
    raw_rules = watch.get("rules")
    if isinstance(raw_rules, list):
        for i, item in enumerate(raw_rules):
            if not isinstance(item, dict):
                continue
            rule = normalize_watch_rule(item, presets=presets, fallback_id=f"rule_{i+1}")
            if rule:
                rules_out.append(rule)
    elif watch.get("process_names"):
        # Legacy single-watch → one rule
        legacy = {
            "id": "rule_legacy",
            "name": "App",
            "enabled": True,
            "process_names": watch.get("process_names") or [],
            "on_start": watch.get("preset") or "Default",
            "on_exit": watch.get("on_exit_preset") or "Default",
        }
        rule = normalize_watch_rule(legacy, presets=presets, fallback_id="rule_legacy")
        if rule and rule["process_names"]:
            rules_out.append(rule)

    # Dedupe ids
    seen: set[str] = set()
    for rule in rules_out:
        rid = rule["id"]
        if rid in seen:
            rule["id"] = _new_rule_id()
        seen.add(rule["id"])

    base["rules"] = rules_out
    return base


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

    cfg["watch"] = normalize_watch(data.get("watch") if isinstance(data.get("watch"), dict) else None, presets=set(cleaned))

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

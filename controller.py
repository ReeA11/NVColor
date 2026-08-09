"""Shared runtime controller: presets, live apply, hotkeys, process watch."""

from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from config_store import (
    config_path,
    load_config,
    normalize_watch_rule,
    read_config_file,
    save_config,
    write_config_file,
)
from gamma_control import ColorPreset, apply_preset
from gamma_control import hard_reset as apply_hard_reset
from hotkeys import HotkeyListener, format_hotkey, parse_hotkey
from nvapi_color import apply_nv_color, clamp_hue, clamp_vibrance, reset_nv_color
from process_watch import ProcessWatcher


def _preset_values(raw: dict[str, Any] | None = None) -> dict[str, float | int]:
    raw = raw or {}
    return {
        "brightness": float(raw.get("brightness", 0.5)),
        "contrast": float(raw.get("contrast", 0.5)),
        "gamma": float(raw.get("gamma", 1.0)),
        "vibrance": clamp_vibrance(raw.get("vibrance", 50)),
        "hue": clamp_hue(raw.get("hue", 0)),
    }


class AppController:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.current = "Default"
        self._lock = threading.RLock()
        self.hotkeys = HotkeyListener()
        self.watcher: ProcessWatcher | None = None
        self._listeners: list[Callable[[], None]] = []
        self._hotkeys_started = False
        self._stopped = False
        self.notify_cb: Callable[[str], None] | None = None

    # ----- observers (UI refresh) -----

    def on_change(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def _emit(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def _notify(self, text: str) -> None:
        print(f"[NVColor] {text}", flush=True)
        if self.cfg.get("notify_on_switch") and self.notify_cb:
            try:
                self.notify_cb(text)
            except Exception:
                pass

    # ----- config helpers -----

    @property
    def presets(self) -> dict[str, dict[str, float]]:
        return self.cfg.setdefault("presets", {})

    @property
    def hotkey_map(self) -> dict[str, str]:
        return self.cfg.setdefault("hotkeys", {})

    @property
    def watch(self) -> dict[str, Any]:
        return self.cfg.setdefault("watch", {})

    @property
    def all_displays(self) -> bool:
        return bool(self.cfg.get("apply_all_displays", False))

    def reload(self) -> None:
        with self._lock:
            self.cfg = load_config()
        self._restart_services()
        self._emit()
        self._notify("Config reloaded")

    def persist(self) -> None:
        with self._lock:
            save_config(self.cfg)
        # Quiet persist on shutdown — avoid tray spam; still log to console
        print(f"[NVColor] Config saved -> {config_path()}", flush=True)

    def export_config(self, path: str | Path) -> None:
        """Write current config to path (same JSON format as config.json)."""
        with self._lock:
            write_config_file(Path(path), deepcopy(self.cfg))
        self._notify(f"Config exported -> {Path(path).name}")

    def import_config(self, path: str | Path) -> None:
        """Replace active config from a config.json file and restart services."""
        imported = read_config_file(Path(path))
        with self._lock:
            self.cfg = imported
            save_config(self.cfg)
            if "Default" not in self.presets:
                self.presets["Default"] = _preset_values()
                save_config(self.cfg)
            self.current = "Default"
        self._restart_services()
        self._emit()
        self._notify(f"Config imported <- {Path(path).name}")

    def _apply_values(
        self,
        name: str,
        brightness: float,
        contrast: float,
        gamma: float,
        vibrance: int,
        hue: int,
    ) -> None:
        apply_preset(
            ColorPreset(name, brightness, contrast, gamma),
            all_displays=self.all_displays,
        )
        apply_nv_color(vibrance, hue, all_displays=self.all_displays)

    # ----- apply -----

    def apply_named(self, name: str, *, reason: str = "") -> None:
        with self._lock:
            raw = self.presets.get(name)
            if raw is None:
                self._notify(f"Unknown preset: {name}")
                return
            vals = _preset_values(raw)
            self._apply_values(
                name,
                float(vals["brightness"]),
                float(vals["contrast"]),
                float(vals["gamma"]),
                int(vals["vibrance"]),
                int(vals["hue"]),
            )
            self.current = name
            suffix = f" ({reason})" if reason else ""
            self._notify(
                f"{name}: B={vals['brightness']:.2f} C={vals['contrast']:.2f} "
                f"G={vals['gamma']:.2f} V={vals['vibrance']} H={vals['hue']}{suffix}"
            )
        self._emit()

    def apply_live(
        self,
        brightness: float,
        contrast: float,
        gamma: float,
        vibrance: int = 50,
        hue: int = 0,
    ) -> None:
        """Realtime slider preview — does not change current preset name."""
        with self._lock:
            self._apply_values(
                "Live",
                float(brightness),
                float(contrast),
                float(gamma),
                clamp_vibrance(vibrance),
                clamp_hue(hue),
            )

    def hard_reset(self) -> None:
        with self._lock:
            apply_hard_reset(all_displays=True)
            reset_nv_color(all_displays=True)
            self.current = "Default"
        self._notify("Hard reset -> neutral")
        self._emit()

    # ----- presets CRUD -----

    def save_preset_values(
        self,
        name: str,
        brightness: float,
        contrast: float,
        gamma: float,
        vibrance: int = 50,
        hue: int = 0,
        *,
        make_current: bool = True,
        rebind_hotkeys: bool = False,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Preset name is empty")
        vals = _preset_values(
            {
                "brightness": brightness,
                "contrast": contrast,
                "gamma": gamma,
                "vibrance": vibrance,
                "hue": hue,
            }
        )
        with self._lock:
            self.presets[name] = {
                "brightness": round(float(vals["brightness"]), 3),
                "contrast": round(float(vals["contrast"]), 3),
                "gamma": round(float(vals["gamma"]), 3),
                "vibrance": int(vals["vibrance"]),
                "hue": int(vals["hue"]),
            }
            save_config(self.cfg)
            if make_current:
                self.current = name
                self._apply_values(
                    name,
                    float(vals["brightness"]),
                    float(vals["contrast"]),
                    float(vals["gamma"]),
                    int(vals["vibrance"]),
                    int(vals["hue"]),
                )
        if rebind_hotkeys:
            self._restart_hotkeys()
        self._notify(f"Saved preset '{name}'")
        self._emit()

    def _retarget_watch_presets(self, old: str, new: str) -> None:
        rules = self.watch.get("rules")
        if not isinstance(rules, list):
            return
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if rule.get("on_start") == old:
                rule["on_start"] = new
            if rule.get("on_exit") == old:
                rule["on_exit"] = new

    def save_preset_with_hotkey(
        self,
        name: str,
        brightness: float,
        contrast: float,
        gamma: float,
        hotkey: str,
        vibrance: int = 50,
        hue: int = 0,
        *,
        old_name: str | None = None,
    ) -> None:
        """Atomic save used by UI — one hotkey rebind at the end (outside lock)."""
        name = name.strip()
        if not name:
            raise ValueError("Preset name is empty")
        hotkey = format_hotkey(hotkey or "")
        if hotkey:
            parse_hotkey(hotkey)

        vals = _preset_values(
            {
                "brightness": brightness,
                "contrast": contrast,
                "gamma": gamma,
                "vibrance": vibrance,
                "hue": hue,
            }
        )

        with self._lock:
            if old_name and old_name != name and old_name in self.presets:
                if old_name != "Default":
                    self.presets[name] = self.presets.pop(old_name)
                    if old_name in self.hotkey_map:
                        self.hotkey_map[name] = self.hotkey_map.pop(old_name)
                    self._retarget_watch_presets(old_name, name)
                    if self.current == old_name:
                        self.current = name

            self.presets[name] = {
                "brightness": round(float(vals["brightness"]), 3),
                "contrast": round(float(vals["contrast"]), 3),
                "gamma": round(float(vals["gamma"]), 3),
                "vibrance": int(vals["vibrance"]),
                "hue": int(vals["hue"]),
            }

            for other, existing in list(self.hotkey_map.items()):
                if hotkey and existing == hotkey and other != name:
                    del self.hotkey_map[other]
            if hotkey:
                self.hotkey_map[name] = hotkey
            else:
                self.hotkey_map.pop(name, None)

            save_config(self.cfg)
            self.current = name
            self._apply_values(
                name,
                float(vals["brightness"]),
                float(vals["contrast"]),
                float(vals["gamma"]),
                int(vals["vibrance"]),
                int(vals["hue"]),
            )

        # Rebind outside lock — avoids deadlock with hotkey callbacks
        self._restart_hotkeys()
        self._notify(f"Saved '{name}'" + (f" [{hotkey}]" if hotkey else ""))
        self._emit()

    def delete_preset(self, name: str) -> None:
        if name == "Default":
            raise ValueError("Cannot delete Default")
        with self._lock:
            self.presets.pop(name, None)
            self.hotkey_map.pop(name, None)
            self._retarget_watch_presets(name, "Default")
            save_config(self.cfg)
        self._restart_hotkeys()
        self._notify(f"Deleted preset '{name}'")
        self._emit()

    def rename_preset(self, old: str, new: str) -> None:
        new = new.strip()
        if not new:
            raise ValueError("Empty name")
        if old == "Default":
            raise ValueError("Cannot rename Default")
        with self._lock:
            if old not in self.presets:
                raise ValueError(f"Unknown preset: {old}")
            if new in self.presets and new != old:
                raise ValueError(f"Preset already exists: {new}")
            self.presets[new] = self.presets.pop(old)
            if old in self.hotkey_map:
                self.hotkey_map[new] = self.hotkey_map.pop(old)
            self._retarget_watch_presets(old, new)
            if self.current == old:
                self.current = new
            save_config(self.cfg)
        self._restart_hotkeys()
        self._notify(f"Renamed '{old}' -> '{new}'")
        self._emit()

    def set_hotkey(self, preset: str, spec: str) -> None:
        spec = format_hotkey(spec)
        if preset not in self.presets:
            raise ValueError(f"Unknown preset: {preset}")
        if spec:
            parse_hotkey(spec)
        with self._lock:
            for name, existing in list(self.hotkey_map.items()):
                if existing == spec and name != preset:
                    del self.hotkey_map[name]
            if spec:
                self.hotkey_map[preset] = spec
            else:
                self.hotkey_map.pop(preset, None)
            save_config(self.cfg)
        self._restart_hotkeys()
        self._notify(f"Hotkey {spec or '(none)'} -> {preset}")
        self._emit()

    def set_watch_config(
        self,
        *,
        enabled: bool,
        rules: list[dict[str, Any]] | None = None,
        poll_ms: int | None = None,
    ) -> None:
        with self._lock:
            self.watch["enabled"] = bool(enabled)
            if poll_ms is not None:
                self.watch["poll_ms"] = max(300, int(poll_ms))
            if rules is not None:
                cleaned: list[dict[str, Any]] = []
                preset_names = set(self.presets.keys())
                for i, raw in enumerate(rules):
                    if not isinstance(raw, dict):
                        continue
                    rule = normalize_watch_rule(
                        raw, presets=preset_names, fallback_id=f"rule_{i+1}"
                    )
                    if rule:
                        cleaned.append(rule)
                self.watch["rules"] = cleaned
            # Drop legacy keys if present
            self.watch.pop("process_names", None)
            self.watch.pop("preset", None)
            self.watch.pop("on_exit_preset", None)
            save_config(self.cfg)
            self._restart_watcher()
        self._emit()

    def update_watch(self, **kwargs: Any) -> None:
        """Backward-compatible shim — prefer set_watch_config."""
        enabled = kwargs.get("enabled")
        poll_ms = kwargs.get("poll_ms")
        if "process_names" in kwargs or "preset" in kwargs or "on_exit_preset" in kwargs:
            # Convert legacy single-rule update into rules list
            with self._lock:
                rules = list(self.watch.get("rules") or [])
                if not rules:
                    rules = [
                        {
                            "id": "rule_1",
                            "name": "App",
                            "enabled": True,
                            "process_names": kwargs.get("process_names")
                            or self.watch.get("process_names")
                            or [],
                            "on_start": kwargs.get("preset")
                            or self.watch.get("preset")
                            or "Default",
                            "on_exit": kwargs.get("on_exit_preset")
                            or self.watch.get("on_exit_preset")
                            or "Default",
                        }
                    ]
                elif rules:
                    if kwargs.get("process_names") is not None:
                        rules[0]["process_names"] = kwargs["process_names"]
                    if kwargs.get("preset") is not None:
                        rules[0]["on_start"] = kwargs["preset"]
                    if kwargs.get("on_exit_preset") is not None:
                        rules[0]["on_exit"] = kwargs["on_exit_preset"]
            self.set_watch_config(
                enabled=bool(enabled) if enabled is not None else bool(self.watch.get("enabled")),
                rules=rules,
                poll_ms=poll_ms,
            )
            return
        self.set_watch_config(
            enabled=bool(enabled) if enabled is not None else bool(self.watch.get("enabled")),
            poll_ms=poll_ms,
        )

    def set_apply_all_displays(self, value: bool) -> None:
        with self._lock:
            self.cfg["apply_all_displays"] = bool(value)
            save_config(self.cfg)
        self._emit()

    def set_notify(self, value: bool) -> None:
        with self._lock:
            self.cfg["notify_on_switch"] = bool(value)
            save_config(self.cfg)

    def set_ui_language(self, language: str) -> str:
        lang = "ru" if str(language or "").lower().startswith("ru") else "en"
        with self._lock:
            self.cfg["ui_language"] = lang
            save_config(self.cfg)
        self._emit()
        return lang

    # ----- services -----

    def start_services(self) -> None:
        with self._lock:
            self._stopped = False
            apply_hard_reset(all_displays=True)
            reset_nv_color(all_displays=True)
            self.current = "Default"
        self._restart_hotkeys()
        self._restart_watcher()

    def stop_services(self, *, reset: bool = True) -> None:
        """Stop watcher/hotkeys. If reset=True, hard-reset gamma FIRST (while alive)."""
        # Gamma reset before teardown — do not hold lock across thread joins
        if reset:
            try:
                apply_hard_reset(all_displays=True)
                reset_nv_color(all_displays=True)
                with self._lock:
                    self.current = "Default"
                print("[NVColor] stop_services: hard reset applied", flush=True)
            except Exception as exc:
                print(f"[NVColor] stop_services: hard reset FAILED: {exc}", flush=True)

        with self._lock:
            if self._stopped and not reset:
                return
            watcher = self.watcher
            self.watcher = None
            self._hotkeys_started = False
            self._stopped = True
            hotkeys = self.hotkeys

        if watcher:
            try:
                watcher.stop()
            except Exception:
                pass
        try:
            hotkeys.stop()
        except Exception:
            pass

    def _restart_services(self) -> None:
        self._restart_hotkeys()
        self._restart_watcher()

    def _restart_hotkeys(self) -> None:
        """Rebuild hotkey table on the existing listener thread (no stop/recreate)."""
        mapping = deepcopy(self.hotkey_map)
        bindings: dict[int, tuple[str, Callable[[], None]]] = {}
        idx = 1
        for preset_name, spec in mapping.items():
            if preset_name not in self.presets or not spec:
                continue
            try:
                parse_hotkey(spec)
            except Exception as exc:
                print(f"[NVColor] Bad hotkey {spec!r}: {exc}", flush=True)
                continue
            bindings[idx] = (
                spec,
                lambda n=preset_name: self.apply_named(n, reason="hotkey"),
            )
            print(f"[NVColor] Hotkey {spec} -> {preset_name}", flush=True)
            idx += 1

        try:
            self.hotkeys.clear_bindings()
            for hid, (spec, cb) in bindings.items():
                self.hotkeys.bind(hid, spec, cb)
            self.hotkeys.start_or_rebind()
            self._hotkeys_started = True
        except Exception as exc:
            print(f"[NVColor] Hotkey rebind failed: {exc}", flush=True)
            self._hotkeys_started = False

    def _restart_watcher(self) -> None:
        if self.watcher:
            try:
                self.watcher.stop()
            except Exception:
                pass
            self.watcher = None
        w = self.watch
        if not w.get("enabled"):
            return
        rules = [r for r in (w.get("rules") or []) if isinstance(r, dict)]
        active = [r for r in rules if r.get("enabled", True) and r.get("process_names")]
        if not active:
            return

        def on_apply(preset: str, reason: str) -> None:
            self.apply_named(preset, reason=reason)

        self.watcher = ProcessWatcher(
            rules=active,
            on_apply=on_apply,
            poll_ms=int(w.get("poll_ms", 1500)),
        )
        self.watcher.start()
        labels = [f"{r.get('name') or r.get('id')}({','.join(r.get('process_names') or [])})" for r in active]
        print(f"[NVColor] Watching rules: {'; '.join(labels)}", flush=True)

    def snapshot_for_ui(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self.cfg) | {"current": self.current}

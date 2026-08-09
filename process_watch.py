"""Watch multiple app rules and apply/restore presets with an active stack."""

from __future__ import annotations

import threading
from typing import Any, Callable

import psutil


WatchRule = dict[str, Any]
ApplyCb = Callable[[str, str], None]  # (preset_name, reason)


class ProcessWatcher:
    """
    Poll running processes and map them to watch rules.

    Active rules are tracked in a stack (most recently started on top).
    - Rule starts  -> push + apply on_start
    - Rule stops   -> pop; if stack empty apply its on_exit, else apply top on_start
    """

    def __init__(
        self,
        rules: list[WatchRule],
        on_apply: ApplyCb,
        poll_ms: int = 1500,
    ) -> None:
        self.rules = [r for r in rules if r.get("enabled", True) and r.get("process_names")]
        self.on_apply = on_apply
        self.poll_s = max(poll_ms, 300) / 1000.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stack: list[str] = []  # rule ids, top = last
        self._by_id = {str(r["id"]): r for r in self.rules}

    @property
    def active(self) -> bool:
        return bool(self._stack)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self.rules:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ProcessWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self._stack.clear()

    def _running_rule_ids(self) -> set[str]:
        if not self.rules:
            return set()
        wanted: dict[str, str] = {}  # process lower -> rule id
        for rule in self.rules:
            rid = str(rule["id"])
            for name in rule.get("process_names") or []:
                wanted[str(name).lower()] = rid

        found: set[str] = set()
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            rid = wanted.get(name)
            if rid:
                found.add(rid)
        return found

    def _apply(self, preset: str, reason: str) -> None:
        try:
            self.on_apply(str(preset), reason)
        except Exception:
            pass

    def _on_rule_start(self, rid: str) -> None:
        rule = self._by_id.get(rid)
        if not rule:
            return
        if rid in self._stack:
            self._stack.remove(rid)
        self._stack.append(rid)
        self._apply(str(rule.get("on_start") or "Default"), f"{rule.get('name') or rid} started")

    def _on_rule_stop(self, rid: str) -> None:
        rule = self._by_id.get(rid)
        if not rule:
            return
        was_top = bool(self._stack) and self._stack[-1] == rid
        if rid in self._stack:
            self._stack.remove(rid)
        if not was_top:
            # Closed a background app — leave current top preset alone
            return
        if self._stack:
            top = self._by_id.get(self._stack[-1])
            if top:
                self._apply(
                    str(top.get("on_start") or "Default"),
                    f"restore {top.get('name') or self._stack[-1]}",
                )
        else:
            self._apply(str(rule.get("on_exit") or "Default"), f"{rule.get('name') or rid} exited")

    def _run(self) -> None:
        running = self._running_rule_ids()
        # Seed stack without reordering arbitrarily — stable by rules order
        self._stack = [str(r["id"]) for r in self.rules if str(r["id"]) in running]
        if self._stack:
            top = self._by_id.get(self._stack[-1])
            if top:
                self._apply(str(top.get("on_start") or "Default"), f"{top.get('name') or self._stack[-1]} started")

        prev = set(self._stack)
        while not self._stop.wait(self.poll_s):
            now = self._running_rule_ids()
            started = now - prev
            stopped = prev - now
            # Start first so a fast restart still pushes
            for rid in started:
                self._on_rule_start(rid)
            for rid in stopped:
                self._on_rule_stop(rid)
            prev = now

"""Watch for game process and apply/restore presets."""

from __future__ import annotations

import threading
import time
from typing import Callable

import psutil


class ProcessWatcher:
    def __init__(
        self,
        process_names: list[str],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        poll_ms: int = 1500,
    ) -> None:
        self.process_names = {n.lower() for n in process_names}
        self.on_start = on_start
        self.on_stop = on_stop
        self.poll_s = max(poll_ms, 300) / 1000.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ProcessWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _is_running(self) -> bool:
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name in self.process_names:
                return True
        return False

    def _run(self) -> None:
        # Detect current state without firing callbacks on first tick if already running
        was_running = self._is_running()
        self._active = was_running
        if was_running:
            try:
                self.on_start()
            except Exception:
                pass

        while not self._stop.wait(self.poll_s):
            running = self._is_running()
            if running and not self._active:
                self._active = True
                try:
                    self.on_start()
                except Exception:
                    pass
            elif not running and self._active:
                self._active = False
                try:
                    self.on_stop()
                except Exception:
                    pass

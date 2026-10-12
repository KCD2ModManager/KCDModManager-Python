"""Management of the game's ``mod_order.txt`` / ``mod_order_backup.txt``.

When the "create mod order file" setting is off, the order is kept in ``mod_order_backup.txt``
so the game ignores it; switching the setting moves the file back and forth.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from kcd_mod_manager.domain.mod_order import OrderEntry, parse_mod_order, serialize_mod_order
from kcd_mod_manager.domain.models import Mod
from kcd_mod_manager.infrastructure.fs import atomic_write_lines, read_text

log = logging.getLogger(__name__)

MOD_ORDER_FILE = "mod_order.txt"
MOD_ORDER_BACKUP_FILE = "mod_order_backup.txt"

RetryPrompt = Callable[[Path, Path, OSError], bool]
"""Asked after a failed move attempt; return True to retry."""


def read_order_file(path: Path) -> list[OrderEntry]:
    if not path.is_file():
        return []
    try:
        return parse_mod_order(read_text(path).splitlines())
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return []


def write_order_file(path: Path, mods: Iterable[Mod]) -> None:
    atomic_write_lines(path, serialize_mod_order(mods))


class OrderFileManager:
    def __init__(
        self,
        safety_dir: Path,
        retry_prompt: RetryPrompt | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._safety_dir = safety_dir
        self._retry_prompt = retry_prompt
        self._sleep = sleep
        self._lock = threading.Lock()

    def set_retry_prompt(self, prompt: RetryPrompt | None) -> None:
        self._retry_prompt = prompt

    @staticmethod
    def active_file(mods_dir: Path, mod_order_enabled: bool) -> Path:
        return mods_dir / (MOD_ORDER_FILE if mod_order_enabled else MOD_ORDER_BACKUP_FILE)

    def read(self, mods_dir: Path, mod_order_enabled: bool) -> list[OrderEntry]:
        return read_order_file(self.active_file(mods_dir, mod_order_enabled))

    def write(self, mods_dir: Path, mods: Iterable[Mod], mod_order_enabled: bool) -> Path:
        """Write the order to the active file; with the setting off, ``mod_order.txt`` is removed."""
        with self._lock:
            mods_dir.mkdir(parents=True, exist_ok=True)
            target = self.active_file(mods_dir, mod_order_enabled)
            write_order_file(target, mods)
            if not mod_order_enabled:
                main = mods_dir / MOD_ORDER_FILE
                if main.exists():
                    main.unlink()
            return target

    def apply_setting(self, enabled: bool, mods_dir: Path) -> None:
        """Move the order file when the user toggles the setting. Raises on failure."""
        with self._lock:
            main = mods_dir / MOD_ORDER_FILE
            backup = mods_dir / MOD_ORDER_BACKUP_FILE
            if enabled:
                if backup.exists():
                    self._move(backup, main)
                elif not main.exists():
                    mods_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write_lines(main, [])
            elif main.exists():
                self._move(main, backup)

    def consolidate(self, enabled: bool, mods_dir: Path) -> None:
        """Repair inconsistent states on startup. Failures are logged, never raised."""
        with self._lock:
            main = mods_dir / MOD_ORDER_FILE
            backup = mods_dir / MOD_ORDER_BACKUP_FILE
            try:
                main_exists, backup_exists = main.exists(), backup.exists()
                if enabled and not main_exists and backup_exists:
                    self._move(backup, main)
                elif not enabled and main_exists and not backup_exists:
                    self._move(main, backup)
                elif not enabled and main_exists and backup_exists:
                    self._save_safety_copy(main)
                    main.unlink()
            except OSError as exc:
                log.error("Consolidating mod order files failed: %s", exc)

    def _save_safety_copy(self, path: Path) -> None:
        self._safety_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self._safety_dir / f"{path.stem}_{stamp}{path.suffix}"
        shutil.copy2(path, target)
        log.info("Saved a copy of %s to %s before removing it", path.name, target)

    def _move(self, source: Path, target: Path, attempts: int = 3) -> None:
        for attempt in range(1, attempts + 1):
            if not source.exists():
                raise FileNotFoundError(f"Source file not found: {source}")
            try:
                source.replace(target)
                return
            except OSError as exc:
                if attempt == attempts:
                    raise
                log.warning("Move attempt %d/%d %s -> %s failed: %s", attempt, attempts, source, target, exc)
                if self._retry_prompt is not None and not self._retry_prompt(source, target, exc):
                    raise
                self._sleep(0.1 * attempt)

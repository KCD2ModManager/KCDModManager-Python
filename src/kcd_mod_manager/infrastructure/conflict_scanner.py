"""Detects files provided by more than one mod. ``.pak`` files are zip archives."""

from __future__ import annotations

import logging
import threading
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kcd_mod_manager.domain.models import ConflictGroup
from kcd_mod_manager.infrastructure.fs import files_with_suffix

log = logging.getLogger(__name__)


class ScanCancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ScanTarget:
    mod_id: str
    path: Path


ProgressCallback = Callable[[int], None]


class ConflictScanner:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, int], frozenset[str]] = {}
        self._lock = threading.Lock()

    def _pak_entries(self, pak: Path) -> frozenset[str]:
        try:
            stat = pak.stat()
        except OSError:
            return frozenset()
        key = (str(pak), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            with zipfile.ZipFile(pak) as zf:
                entries = frozenset(
                    name.replace("\\", "/") for name in zf.namelist() if not name.endswith(("/", "\\"))
                )
        except (zipfile.BadZipFile, OSError) as exc:
            log.warning("Cannot read pak %s: %s", pak, exc)
            entries = frozenset()
        with self._lock:
            self._cache[key] = entries
        return entries

    def scan(
        self,
        targets: Sequence[ScanTarget],
        progress: ProgressCallback | None = None,
        cancelled: threading.Event | None = None,
    ) -> list[ConflictGroup]:
        owners: dict[str, list[str]] = {}
        display: dict[str, str] = {}
        total = max(len(targets), 1)
        for index, target in enumerate(targets, start=1):
            if cancelled is not None and cancelled.is_set():
                raise ScanCancelled
            seen_in_mod: set[str] = set()
            if target.path.is_dir():
                for pak in files_with_suffix(target.path, ".pak"):
                    for entry in self._pak_entries(pak):
                        key = entry.casefold()
                        if key not in seen_in_mod:
                            seen_in_mod.add(key)
                            display.setdefault(key, entry)
                            owners.setdefault(key, []).append(target.mod_id)
            if progress is not None:
                progress(int(index * 100 / total))
        groups = [ConflictGroup(display[key], tuple(mods)) for key, mods in owners.items() if len(mods) > 1]
        return sorted(groups, key=lambda g: g.file_path.casefold())

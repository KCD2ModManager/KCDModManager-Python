"""JSON-backed repositories for per-mod metadata.

* ``mod_versions.json`` and ``mod_notes.json`` live in the game's ``Mods`` folder.
* ``user_mod_data.json`` lives in the application data directory.

All files keep the original manager's PascalCase layout. A file that cannot be parsed is copied
aside (``*.corrupt-<timestamp>``) before anything is written back, so user data is never lost to
a parse failure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kcd_mod_manager.domain.models import HighlightColor, ModVersionInfo, UserModData
from kcd_mod_manager.domain.profiles import now_iso
from kcd_mod_manager.infrastructure.fs import (
    CorruptFileError,
    atomic_write_json,
    load_json,
    preserve_corrupt_file,
)
from kcd_mod_manager.infrastructure.json_fields import as_bool, as_int, as_str, pop_ci

log = logging.getLogger(__name__)

MOD_VERSIONS_FILE = "mod_versions.json"
MOD_NOTES_FILE = "mod_notes.json"


class _JsonDictFile:
    """A JSON object file with read-modify-write updates."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_raw(self) -> dict[str, Any]:
        try:
            data = load_json(self.path)
        except CorruptFileError as exc:
            log.error("Cannot parse %s: %s", self.path, exc.reason)
            return {}
        return data if isinstance(data, dict) else {}

    def write_raw(self, data: dict[str, Any]) -> None:
        try:
            load_json(self.path)
        except CorruptFileError:
            preserve_corrupt_file(self.path)
        atomic_write_json(self.path, data)


class ModVersionsRepository(_JsonDictFile):
    def __init__(self, mods_dir: Path) -> None:
        super().__init__(mods_dir / MOD_VERSIONS_FILE)

    @staticmethod
    def _decode(raw: Any) -> ModVersionInfo:
        data = dict(raw) if isinstance(raw, dict) else {}
        return ModVersionInfo(
            version=as_str(pop_ci(data, "Version")) or "",
            mod_number=as_int(pop_ci(data, "ModNumber"), -1),
            file_name=as_str(pop_ci(data, "FileName")) or "",
            update_checks_enabled=as_bool(pop_ci(data, "UpdateChecksEnabled"), True),
            extra=data,
        )

    @staticmethod
    def _encode(info: ModVersionInfo) -> dict[str, Any]:
        return {
            "Version": info.version,
            "ModNumber": info.mod_number,
            "FileName": info.file_name,
            "UpdateChecksEnabled": info.update_checks_enabled,
            **info.extra,
        }

    def load(self) -> dict[str, ModVersionInfo]:
        return {key: self._decode(value) for key, value in self.read_raw().items()}

    def update(self, mutate: Callable[[dict[str, ModVersionInfo]], None]) -> None:
        entries = self.load()
        mutate(entries)
        self.write_raw({key: self._encode(value) for key, value in entries.items()})

    def set(self, mod_id: str, info: ModVersionInfo) -> None:
        self.update(lambda entries: entries.__setitem__(mod_id, info))


class ModNotesRepository(_JsonDictFile):
    def __init__(self, mods_dir: Path) -> None:
        super().__init__(mods_dir / MOD_NOTES_FILE)

    def load(self) -> dict[str, str]:
        return {k: v for k, v in self.read_raw().items() if isinstance(v, str)}

    def update(self, mutate: Callable[[dict[str, str]], None]) -> None:
        notes = self.load()
        mutate(notes)
        self.write_raw(dict(notes))


def _decode_highlight(raw: Any) -> HighlightColor | None:
    if not isinstance(raw, dict):
        return None
    data = dict(raw)
    light, dark = as_str(pop_ci(data, "Light")), as_str(pop_ci(data, "Dark"))
    if not light and not dark:
        return None
    return HighlightColor(light or "", dark or "")


class UserModDataRepository(_JsonDictFile):
    @staticmethod
    def _decode(mod_id: str, raw: Any) -> UserModData:
        data = dict(raw) if isinstance(raw, dict) else {}
        stored_id = as_str(pop_ci(data, "ModId"))
        return UserModData(
            mod_id=stored_id or mod_id,
            custom_version=as_str(pop_ci(data, "CustomVersion")),
            last_detected_version=as_str(pop_ci(data, "LastDetectedVersion")),
            last_updated=as_str(pop_ci(data, "LastUpdated")),
            custom_note=as_str(pop_ci(data, "CustomNote")),
            custom_name=as_str(pop_ci(data, "CustomName")),
            category_id=as_str(pop_ci(data, "CategoryId")),
            ignored_in_conflict_detector=as_bool(pop_ci(data, "IgnoredInConflictDetector"), False),
            highlight=_decode_highlight(pop_ci(data, "HighlightColor")),
            extra=data,
        )

    @staticmethod
    def _encode(entry: UserModData) -> dict[str, Any]:
        return {
            "ModId": entry.mod_id,
            "CustomVersion": entry.custom_version,
            "LastDetectedVersion": entry.last_detected_version,
            "LastUpdated": entry.last_updated or now_iso(),
            "CustomNote": entry.custom_note,
            "CustomName": entry.custom_name,
            "CategoryId": entry.category_id,
            "IgnoredInConflictDetector": entry.ignored_in_conflict_detector,
            "HighlightColor": (
                {"Light": entry.highlight.light, "Dark": entry.highlight.dark} if entry.highlight else None
            ),
            **entry.extra,
        }

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, UserModData]:
        return {key: self._decode(key, value) for key, value in self.read_raw().items()}

    def update(self, mutate: Callable[[dict[str, UserModData]], None]) -> None:
        entries = self.load()
        mutate(entries)
        self.write_raw({key: self._encode(value) for key, value in entries.items()})

    def update_entry(self, mod_id: str, mutate: Callable[[UserModData], None]) -> None:
        def apply(entries: dict[str, UserModData]) -> None:
            entry = entries.get(mod_id) or UserModData(mod_id=mod_id)
            mutate(entry)
            entry.last_updated = now_iso()
            entries[mod_id] = entry

        self.update(apply)

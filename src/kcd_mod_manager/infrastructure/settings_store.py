"""JSON persistence for :class:`AppSettings`."""

from __future__ import annotations

import logging
from dataclasses import fields
from pathlib import Path
from typing import Any

from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.infrastructure.fs import (
    CorruptFileError,
    atomic_write_json,
    load_json,
    preserve_corrupt_file,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def coerce_value(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return default
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value


def settings_from_dict(data: dict[str, Any]) -> AppSettings:
    settings = AppSettings()
    known = {f.name for f in fields(AppSettings)} - {"extra"}
    for key, value in data.items():
        if key == "schema_version":
            continue
        if key in known:
            setattr(settings, key, coerce_value(value, getattr(settings, key)))
        else:
            settings.extra[key] = value
    return settings


def settings_to_dict(settings: AppSettings) -> dict[str, Any]:
    data: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for f in fields(AppSettings):
        if f.name != "extra":
            data[f.name] = getattr(settings, f.name)
    data.update(settings.extra)
    return data


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.recovered_from_corruption = False

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> AppSettings:
        try:
            data = load_json(self.path)
        except CorruptFileError as exc:
            log.error("Settings file unreadable (%s); a copy is kept and defaults are used", exc.reason)
            preserve_corrupt_file(self.path)
            self.recovered_from_corruption = True
            return AppSettings()
        if not isinstance(data, dict):
            return AppSettings()
        return settings_from_dict(data)

    def save(self, settings: AppSettings) -> None:
        atomic_write_json(self.path, settings_to_dict(settings))

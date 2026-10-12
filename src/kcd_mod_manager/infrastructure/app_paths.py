"""Locations of application data.

The data directory is shared with the original Windows manager so profiles, categories and
per-mod user data carry over without migration:

* Windows: ``%APPDATA%\\KCDModManager``
* Linux:   ``$XDG_CONFIG_HOME/KCDModManager`` (default ``~/.config/KCDModManager``), which is
  where .NET's ``SpecialFolder.ApplicationData`` points on Linux as well.

``KCDMM_DATA_DIR`` overrides the location (used by tests and portable setups).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_NAME = "KCDModManager"
DATA_DIR_ENV = "KCDMM_DATA_DIR"


def default_data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / DATA_DIR_NAME


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path

    @classmethod
    def default(cls) -> AppPaths:
        return cls(default_data_dir())

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def user_mod_data_file(self) -> Path:
        return self.data_dir / "user_mod_data.json"

    @property
    def categories_file(self) -> Path:
        return self.data_dir / "categories.json"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def safety_dir(self) -> Path:
        """Copies of files the manager had to remove (e.g. a stale ``mod_order.txt``)."""
        return self.data_dir / "safety-backups"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

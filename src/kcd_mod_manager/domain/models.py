"""Core domain objects. Pure data, no I/O and no Qt."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class GameType(StrEnum):
    KCD1 = "KCD1"
    KCD2 = "KCD2"

    @property
    def nexus_domain(self) -> str:
        return "kingdomcomedeliverance" if self is GameType.KCD1 else "kingdomcomedeliverance2"

    @property
    def steam_app_id(self) -> int:
        return 379430 if self is GameType.KCD1 else 1771300

    @property
    def steam_folder_name(self) -> str:
        return "KingdomComeDeliverance" if self is GameType.KCD1 else "KingdomComeDeliverance2"

    @property
    def gog_folder_name(self) -> str:
        return "Kingdom Come Deliverance" if self is GameType.KCD1 else "Kingdom Come Deliverance II"

    @property
    def display_key(self) -> str:
        """Translation key of the human readable game name."""
        return "KCD1DisplayName" if self is GameType.KCD1 else "KCD2DisplayName"


@dataclass(frozen=True, slots=True)
class HighlightColor:
    light: str
    dark: str

    def for_theme(self, dark_mode: bool) -> str:
        return self.dark if dark_mode else self.light


@dataclass(slots=True)
class Mod:
    id: str
    name: str
    version: str = ""
    path: Path | None = None
    is_enabled: bool = False
    note: str = ""
    number: int = 0
    has_update: bool = False
    latest_version: str = ""
    mod_number: int = -1
    is_workshop_mod: bool = False
    workshop_id: str = ""
    category_id: str | None = None
    category_name: str | None = None
    ignored_in_conflict_detector: bool = False
    highlight: HighlightColor | None = None
    has_separator_after: bool = False
    update_checks_enabled: bool = True
    is_compatible: bool = True
    game_version: str | None = None

    @property
    def has_category(self) -> bool:
        return bool(self.category_id)


@dataclass(slots=True)
class ModCategory:
    id: str
    name: str
    order: int = 0


@dataclass(slots=True)
class ModProfile:
    profile_name: str
    active_mods: list[str] = field(default_factory=list)
    load_order: list[str] = field(default_factory=list)
    mod_categories: dict[str, list[str]] = field(default_factory=dict)
    separators_after_mod_ids: list[str] = field(default_factory=list)
    last_modified: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    """Unknown JSON keys preserved verbatim when the profile is written back."""


@dataclass(slots=True)
class ModVersionInfo:
    version: str = ""
    mod_number: int = -1
    file_name: str = ""
    update_checks_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserModData:
    mod_id: str
    custom_version: str | None = None
    last_detected_version: str | None = None
    last_updated: str | None = None
    custom_note: str | None = None
    custom_name: str | None = None
    category_id: str | None = None
    ignored_in_conflict_detector: bool = False
    highlight: HighlightColor | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ManifestInfo:
    mod_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    game_version: str | None = None
    has_explicit_mod_id: bool = True


@dataclass(frozen=True, slots=True)
class GameInstall:
    game: GameType
    root_path: Path
    executable_path: Path
    mods_path: Path
    """Mods live in <root>/Mods (not Bin/Mods)."""
    game_version: str | None = None

    @property
    def bin_path(self) -> Path:
        return self.executable_path.parent


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    file_path: str
    mod_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NexusFile:
    file_id: int
    version: str
    uploaded_timestamp: int
    name: str = ""
    mod_version: str = ""

    @property
    def effective_version(self) -> str:
        return self.mod_version or self.version


@dataclass(frozen=True, slots=True)
class NexusUser:
    user_id: int
    name: str
    email: str
    is_premium: bool

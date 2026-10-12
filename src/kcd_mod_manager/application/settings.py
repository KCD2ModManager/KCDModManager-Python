"""User settings. Defaults match the original manager's ``Settings.settings``."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from kcd_mod_manager.domain.models import GameType

SUPPORTED_LANGUAGES = ("en", "de", "fr")


@dataclass(slots=True)
class AppSettings:
    ask_on_delete: bool = True
    game_launch_args: str = ""
    is_dark_mode: bool = False
    is_dev_mode: bool = False
    window_width: int = 800
    window_height: int = 600
    window_left: int = 0
    window_top: int = 0
    window_state: str = "Normal"
    window_geometry: str = ""
    """Qt-encoded geometry (base64). Preferred over the individual values when present."""
    monitor_index: int = -1
    create_backup: bool = True
    enable_update_notifications: bool = True
    dont_ask_for_nexus_login: bool = False
    nexus_username: str = ""
    nexus_is_premium: bool = False
    nexus_user_email: str = ""
    nexus_user_id: int = 0
    backup_on_change: bool = False
    backup_max_count: int = 20
    backup_on_startup: bool = True
    mod_order_enabled: bool = True
    enable_file_renaming: bool = True
    allow_workshop_mod_actions: bool = False
    allow_workshop_actions_warning_shown: bool = False
    conflict_detector_only_enabled_mods: bool = True
    language: str = "en"
    game_path_kcd1: str = ""
    game_path_kcd2: str = ""
    last_used_profile_kcd1: str = ""
    last_used_profile_kcd2: str = ""
    imported_from_legacy: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def game_path(self, game: GameType) -> str:
        return self.game_path_kcd1 if game is GameType.KCD1 else self.game_path_kcd2

    def set_game_path(self, game: GameType, value: str) -> None:
        if game is GameType.KCD1:
            self.game_path_kcd1 = value
        else:
            self.game_path_kcd2 = value

    def last_used_profile(self, game: GameType) -> str:
        return self.last_used_profile_kcd1 if game is GameType.KCD1 else self.last_used_profile_kcd2

    def set_last_used_profile(self, game: GameType, value: str) -> None:
        if game is GameType.KCD1:
            self.last_used_profile_kcd1 = value
        else:
            self.last_used_profile_kcd2 = value

    def clear_nexus_account(self) -> None:
        self.nexus_username = ""
        self.nexus_user_email = ""
        self.nexus_user_id = 0
        self.nexus_is_premium = False


def setting_names() -> list[str]:
    return [f.name for f in fields(AppSettings) if f.name != "extra"]

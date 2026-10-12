"""One-time, read-only import of settings from the original WPF manager.

The WPF app stored settings in ``%LOCALAPPDATA%\\KCD2_mod_manager\\<exe>_<hash>\\<version>\\user.config``.
Several such folders can exist (one per install location/version); the most recently written
file wins. Nothing in those folders is modified.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from kcd_mod_manager.application.settings import SUPPORTED_LANGUAGES, AppSettings
from kcd_mod_manager.infrastructure.settings_store import coerce_value

log = logging.getLogger(__name__)

LEGACY_COMPANY_DIR = "KCD2_mod_manager"
SETTINGS_SECTION = "KCD2_mod_manager.Settings"

_NAME_MAP: dict[str, str] = {
    "AskOnDelete": "ask_on_delete",
    "GameLaunchArgs": "game_launch_args",
    "IsDarkMode": "is_dark_mode",
    "IsDevMode": "is_dev_mode",
    "WindowWidth": "window_width",
    "WindowHeight": "window_height",
    "WindowLeft": "window_left",
    "WindowTop": "window_top",
    "WindowState": "window_state",
    "MonitorIndex": "monitor_index",
    "CreateBackup": "create_backup",
    "EnableUpdateNotifications": "enable_update_notifications",
    "DontAskForNexusLogin": "dont_ask_for_nexus_login",
    "NexusUsername": "nexus_username",
    "NexusIsPremium": "nexus_is_premium",
    "NexusUserEmail": "nexus_user_email",
    "NexusUserID": "nexus_user_id",
    "BackupOnChange": "backup_on_change",
    "BackupMaxCount": "backup_max_count",
    "BackupOnStartup": "backup_on_startup",
    "ModOrderEnabled": "mod_order_enabled",
    "EnableFileRenaming": "enable_file_renaming",
    "AllowWorkshopModActions": "allow_workshop_mod_actions",
    "AllowWorkshopActionsWarningShown": "allow_workshop_actions_warning_shown",
    "ConflictDetector_OnlyEnabledMods": "conflict_detector_only_enabled_mods",
    "Language": "language",
    "GamePath_KCD1": "game_path_kcd1",
    "GamePath_KCD2": "game_path_kcd2",
}


@dataclass(frozen=True, slots=True)
class LegacyImport:
    source: Path
    settings: AppSettings
    nexus_token: str | None
    """The Nexus API key found in the legacy file; callers move it into the credential store."""


def legacy_config_root() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / LEGACY_COMPANY_DIR if base else None


def find_legacy_config(root: Path | None = None) -> Path | None:
    root = root if root is not None else legacy_config_root()
    if root is None or not root.is_dir():
        return None
    candidates = [p for p in root.glob("*/*/user.config") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_legacy_values(path: Path) -> dict[str, str]:
    tree = ET.parse(path)
    section = tree.getroot().find(f"userSettings/{SETTINGS_SECTION}")
    values: dict[str, str] = {}
    if section is None:
        return values
    for setting in section.findall("setting"):
        name = setting.get("name")
        value = setting.find("value")
        if name:
            values[name] = "" if value is None or value.text is None else value.text
    return values


def import_legacy_settings(root: Path | None = None) -> LegacyImport | None:
    path = find_legacy_config(root)
    if path is None:
        return None
    try:
        values = read_legacy_values(path)
    except (ET.ParseError, OSError) as exc:
        log.warning("Could not read legacy settings %s: %s", path, exc)
        return None

    settings = AppSettings()
    for legacy_name, attr in _NAME_MAP.items():
        if legacy_name in values:
            setattr(settings, attr, coerce_value(values[legacy_name], getattr(settings, attr)))
    if settings.language not in SUPPORTED_LANGUAGES:
        settings.language = "en"
    if settings.backup_max_count <= 0:
        settings.backup_max_count = AppSettings().backup_max_count
    settings.imported_from_legacy = True
    token = values.get("NexusUserToken") or None
    log.info("Imported settings from legacy manager (%s)", path.parent.name)
    return LegacyImport(source=path, settings=settings, nexus_token=token)

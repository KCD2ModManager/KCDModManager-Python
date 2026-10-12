"""Mod id generation and filename sanitising."""

from __future__ import annotations

import hashlib
import re

_INVALID_ID_CHARS = re.compile(r'[<>:"/\\|?*]')
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MOD_NUMBER = re.compile(r"\b(\d+)\b")
_NEXUS_FILENAME_VERSION = re.compile(r"^(.*?)-\d+-(\d+)-(\d+)-.*$")
_INT32_MAX = 2**31 - 1


def normalize_name(name: str, renaming_enabled: bool) -> str:
    if not renaming_enabled:
        return name
    return _INVALID_ID_CHARS.sub("", name)


def generate_mod_id(name: str, renaming_enabled: bool) -> str:
    """Derive a mod id from a display name.

    With renaming enabled characters invalid in file names are stripped. If nothing usable remains
    (or renaming is disabled and the name is blank) the first 8 hex chars of the MD5 of the name
    are used, with ``moddefault`` as the last resort.
    """
    normalized = normalize_name(name, renaming_enabled)
    if normalized.strip():
        return normalized
    digest = hashlib.md5(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return digest or "moddefault"


def safe_file_name(name: str) -> str:
    """Replace characters that are invalid in Windows file names (used on every platform)."""
    return _INVALID_FILENAME_CHARS.sub("_", name)


def extract_mod_number(file_stem: str) -> int:
    """First standalone number in an archive name (Nexus: ``Name-187-1-2-1700000000``) or -1."""
    match = _MOD_NUMBER.search(file_stem)
    if not match:
        return -1
    try:
        value = int(match.group(1))
    except ValueError:
        return -1
    return value if value <= _INT32_MAX else -1


def version_from_nexus_folder_name(folder_name: str) -> str:
    """``Name-187-1-2-1700000000`` -> ``1.2``; ``N/A`` when the pattern does not match."""
    match = _NEXUS_FILENAME_VERSION.match(folder_name)
    if match:
        return f"{match.group(2)}.{match.group(3)}"
    return "N/A"


def version_from_file_name(file_name: str) -> str:
    """Legacy helper of the original installer: third dash-separated part, else ``0``."""
    parts = file_name.split("-")
    return parts[2] if len(parts) >= 4 else "0"

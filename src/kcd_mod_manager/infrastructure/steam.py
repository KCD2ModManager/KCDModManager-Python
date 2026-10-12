"""Steam library discovery for Windows and Linux (native, Flatpak and Snap Steam)."""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from kcd_mod_manager.infrastructure.fs import read_text
from kcd_mod_manager.infrastructure.paths import find_child_ci

log = logging.getLogger(__name__)

_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)
_ACF_INSTALLDIR = re.compile(r'"installdir"\s+"([^"]+)"', re.IGNORECASE)
_ACF_APPID = re.compile(r'"appid"\s+"(\d+)"', re.IGNORECASE)


def _unescape_vdf(value: str) -> str:
    return value.replace("\\\\", "\\")


def parse_library_folders(text: str) -> list[Path]:
    return [Path(_unescape_vdf(match)) for match in _VDF_PATH.findall(text)]


def parse_app_manifest(text: str) -> tuple[int | None, str | None]:
    app_id = _ACF_APPID.search(text)
    install_dir = _ACF_INSTALLDIR.search(text)
    return (
        int(app_id.group(1)) if app_id else None,
        _unescape_vdf(install_dir.group(1)) if install_dir else None,
    )


def _windows_registry_steam_roots() -> list[Path]:
    if sys.platform != "win32":
        return []
    import winreg

    roots: list[Path] = []
    for hive, key, value in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                data, _ = winreg.QueryValueEx(handle, value)
                if isinstance(data, str) and data:
                    roots.append(Path(data))
        except OSError:
            continue
    return roots


def candidate_steam_roots() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates.extend(_windows_registry_steam_roots())
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Steam")
    else:
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        candidates.extend(
            [
                home / ".steam" / "steam",
                home / ".steam" / "root",
                xdg_data / "Steam",
                home / ".local" / "share" / "Steam",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",
                home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
            ]
        )
    return _dedupe(p for p in candidates if p.is_dir())


def _dedupe(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        key = key.casefold() if sys.platform == "win32" else key
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def steamapps_dir(library: Path) -> Path | None:
    found = find_child_ci(library, "steamapps")
    return found if found is not None and found.is_dir() else None


def library_folders(steam_roots: Iterable[Path] | None = None) -> list[Path]:
    """All Steam library roots (each containing ``steamapps``)."""
    roots = list(steam_roots) if steam_roots is not None else candidate_steam_roots()
    libraries: list[Path] = []
    for root in roots:
        libraries.append(root)
        apps = steamapps_dir(root)
        vdf = apps / "libraryfolders.vdf" if apps else None
        if vdf is None or not vdf.is_file():
            continue
        try:
            libraries.extend(parse_library_folders(read_text(vdf)))
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("Could not read %s: %s", vdf, exc)
    return _dedupe(p for p in libraries if p.is_dir() and steamapps_dir(p) is not None)


def find_steamapps_for_install(game_root: Path) -> Path | None:
    """Walk up from a game folder to the ``steamapps`` directory that contains it."""
    for parent in [game_root, *game_root.parents]:
        if parent.name.casefold() == "steamapps":
            return parent
        if parent.name.casefold() == "common" and parent.parent.name.casefold() == "steamapps":
            return parent.parent
    return None


def find_app_id_for_install(steamapps: Path, game_root: Path) -> int | None:
    """Match ``appmanifest_*.acf`` whose ``installdir`` equals the game folder name."""
    wanted = game_root.name.casefold()
    try:
        manifests = list(steamapps.glob("appmanifest_*.acf"))
    except OSError:
        return None
    for manifest in manifests:
        try:
            app_id, install_dir = parse_app_manifest(read_text(manifest))
        except (OSError, UnicodeDecodeError):
            continue
        if install_dir and install_dir.casefold() == wanted:
            if app_id is not None:
                return app_id
            match = re.search(r"appmanifest_(\d+)\.acf$", manifest.name, re.IGNORECASE)
            if match:
                return int(match.group(1))
    return None


def workshop_content_dir(game_root: Path, fallback_app_id: int | None = None) -> Path | None:
    steamapps = find_steamapps_for_install(game_root)
    if steamapps is None:
        return None
    app_id = find_app_id_for_install(steamapps, game_root) or fallback_app_id
    if app_id is None:
        return None
    directory = steamapps / "workshop" / "content" / str(app_id)
    return directory if directory.is_dir() else None


def is_workshop_path(path: Path) -> bool:
    parts = [p.casefold() for p in path.parts]
    for index in range(len(parts) - 2):
        if parts[index : index + 3] == ["steamapps", "workshop", "content"]:
            return True
    return False

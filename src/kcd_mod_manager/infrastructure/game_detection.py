"""Detection of KCD1/KCD2 installations on Windows and Linux.

Search order per game: saved path -> Steam libraries (registry on Windows, well-known
directories on Linux incl. Flatpak/Snap, plus ``libraryfolders.vdf``) -> GOG Galaxy (Windows)
-> standard locations on all fixed drives (Windows). On Linux the game runs through Proton, so the
Windows build with ``KingdomCome.exe`` is what we look for.
"""

from __future__ import annotations

import json
import logging
import os
import re
import string
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from kcd_mod_manager.domain.models import GameInstall, GameType, LaunchStore
from kcd_mod_manager.infrastructure.fs import read_text
from kcd_mod_manager.infrastructure.paths import find_child_ci, resolve_ci
from kcd_mod_manager.infrastructure.pe_version import read_file_version, read_product_version
from kcd_mod_manager.infrastructure.steam import find_steamapps_for_install, library_folders, steamapps_dir

log = logging.getLogger(__name__)

EXECUTABLE_NAME = "KingdomCome.exe"
_BIN_CANDIDATES: dict[GameType, tuple[tuple[str, ...], ...]] = {
    GameType.KCD1: (("Bin", "Win64"),),
    GameType.KCD2: (
        ("Bin", "Win64MasterMasterSteamPGO"),
        ("Bin", "Win64MasterMasterEpicPGO"),
        ("Bin", "Win64MasterMasterEGSPGO"),
        ("Bin", "Win64"),
    ),
}
_BOGUS_VERSIONS = frozenset({"", "0.0.0.0", "1.0.0.0", "0.0.0", "1.0.0"})
# Warhorse WHDL presets look like ``release_1_5`` / ``kcd2_release_1_5_game_pc`` (branch only).
_WHDL_RELEASE = re.compile(r"release_(\d+(?:_\d+){1,3})", re.IGNORECASE)
# Full patch version lives in system.cfg, e.g. ``wh_sys_version = "1.5.6"``.
_SYS_VERSION = re.compile(r'^\s*wh_sys_version\s*=\s*"([^"]+)"\s*$', re.IGNORECASE | re.MULTILINE)


def _find_executable_recursive(directory: Path, depth: int, max_depth: int) -> Path | None:
    if depth >= max_depth:
        return None
    direct = find_child_ci(directory, EXECUTABLE_NAME)
    if direct is not None and direct.is_file():
        return direct
    try:
        children = sorted(p for p in directory.iterdir() if p.is_dir())
    except OSError:
        return None
    for child in children:
        found = _find_executable_recursive(child, depth + 1, max_depth)
        if found is not None:
            return found
    return None


def find_executable(root: Path, game: GameType) -> Path | None:
    for parts in _BIN_CANDIDATES[game]:
        folder = resolve_ci(root, *parts)
        if folder is not None:
            exe = find_child_ci(folder, EXECUTABLE_NAME)
            if exe is not None and exe.is_file():
                return exe
    bin_dir = find_child_ci(root, "Bin")
    if bin_dir is not None and bin_dir.is_dir():
        found = _find_executable_recursive(bin_dir, 0, 3)
        if found is not None:
            return found
    root_exe = find_child_ci(root, EXECUTABLE_NAME)
    return root_exe if root_exe is not None and root_exe.is_file() else None


def is_valid_game_folder(root: Path, game: GameType) -> bool:
    return root.is_dir() and find_executable(root, game) is not None


def is_usable_game_version(version: str | None) -> bool:
    """False for empty / placeholder PE stubs like ``1.0.0.0`` that break Update Manifests."""
    if version is None:
        return False
    text = version.strip()
    return bool(text) and text not in _BOGUS_VERSIONS


def resolve_game_version(detected: str | None, override: str | None = None) -> str | None:
    """Prefer a usable auto-detected version; otherwise a manual override from settings."""
    for candidate in (detected, override):
        if is_usable_game_version(candidate) and candidate is not None:
            return candidate.strip()
    return None


def _version_from_whdl_text(text: str) -> str | None:
    match = _WHDL_RELEASE.search(text)
    if match is None:
        return None
    return match.group(1).replace("_", ".")


def read_system_cfg_game_version(root: Path) -> str | None:
    """Read ``wh_sys_version`` from ``system.cfg`` (full patch, e.g. ``1.5.6``)."""
    path = find_child_ci(root, "system.cfg")
    if path is None or not path.is_file():
        return None
    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        log.debug("Could not read %s: %s", path, exc)
        return None
    match = _SYS_VERSION.search(text)
    return match.group(1).strip() if match else None


def read_whdl_game_version(root: Path) -> str | None:
    """Fallback from ``whdlversions.json`` branch name (often only major.minor, e.g. ``1.5``)."""
    path = find_child_ci(root, "whdlversions.json")
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(read_text(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.debug("Could not read %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    preset = data.get("Preset")
    needles: list[str] = []
    if isinstance(preset, dict):
        branch = preset.get("Branch")
        if isinstance(branch, dict) and isinstance(branch.get("Name"), str):
            needles.append(branch["Name"])
        if isinstance(preset.get("Name"), str):
            needles.append(preset["Name"])
    for needle in needles:
        version = _version_from_whdl_text(needle)
        if is_usable_game_version(version):
            return version
    return _version_from_whdl_text(json.dumps(data))


def read_game_version(root: Path, executable: Path) -> str | None:
    candidates: list[str] = []
    version_file = find_child_ci(root, "version.txt")
    if version_file is not None and version_file.is_file():
        try:
            text = read_text(version_file).strip()
            if text:
                candidates.append(text)
        except (OSError, UnicodeDecodeError):
            pass
    sys_ver = read_system_cfg_game_version(root)
    if sys_ver:
        candidates.append(sys_ver)
    whdl = read_whdl_game_version(root)
    if whdl:
        candidates.append(whdl)
    for reader in (read_file_version, read_product_version):
        value = reader(executable)
        if value:
            candidates.append(value)
    for value in candidates:
        if is_usable_game_version(value):
            return value.strip()
    return None


def detect_launch_store(root: Path, executable: Path) -> LaunchStore:
    if find_steamapps_for_install(root) is not None:
        return LaunchStore.STEAM
    if (root / ".egstore").is_dir() or any(part for part in executable.parts if "epic" in part.casefold()):
        return LaunchStore.EPIC
    # GOG Galaxy often leaves a goggame-*.info next to the root.
    try:
        if any(p.name.lower().startswith("goggame-") for p in root.iterdir() if p.is_file()):
            return LaunchStore.GOG
    except OSError:
        pass
    parent = str(root).casefold()
    if "epic games" in parent or "epicgames" in parent:
        return LaunchStore.EPIC
    if "gog" in parent:
        return LaunchStore.GOG
    return LaunchStore.UNKNOWN


def path_volume_missing(path: Path | str) -> bool:
    """True when the path's drive/root is not mounted (stale secondary-drive install)."""
    raw = Path(path)
    if not raw.parts:
        return False
    try:
        anchor = raw.anchor or raw.drive
        if not anchor:
            # Relative path — treat as present; caller resolves against cwd.
            return False
        root = Path(anchor)
        return not root.exists()
    except OSError:
        return True


def make_install(
    game: GameType, root: Path, executable: Path, *, create_mods_dir: bool = True
) -> GameInstall:
    mods = find_child_ci(root, "Mods") or root / "Mods"
    if create_mods_dir and not mods.exists():
        mods.mkdir(parents=True, exist_ok=True)
        log.info("Created mods folder %s", mods)
    return GameInstall(
        game=game,
        root_path=root,
        executable_path=executable,
        mods_path=mods,
        game_version=read_game_version(root, executable),
        launch_store=detect_launch_store(root, executable),
    )


def game_root_from_executable(executable: Path) -> Path:
    """Derive the game folder from a selected ``KingdomCome.exe``."""
    parent = executable.parent
    if (
        parent.name.casefold() in ("win64", "win64mastermastersteampgo")
        and parent.parent.name.casefold() == "bin"
    ):
        return parent.parent.parent
    for ancestor in executable.parents:
        if find_child_ci(ancestor, "Bin") is not None and resolve_ci(ancestor, "Data") is not None:
            return ancestor
    for ancestor in executable.parents:
        name = ancestor.name.casefold().replace(" ", "")
        if name.startswith("kingdomcome"):
            return ancestor
    return parent


def _gog_roots() -> list[Path]:
    if sys.platform != "win32":
        return []
    roots: list[Path] = []
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            roots.append(Path(base) / "GOG Galaxy" / "Games")
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com") as key:
            value, _ = winreg.QueryValueEx(key, "path")
            if isinstance(value, str) and value:
                roots.append(Path(value) / "Games")
    except OSError:
        pass
    return [r for r in roots if r.is_dir()]


def _fixed_drives() -> list[Path]:
    if sys.platform != "win32":
        return []
    import ctypes

    drives: list[Path] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for index, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << index):
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                drives.append(Path(root))
    return drives


def _standard_paths(game: GameType) -> list[Path]:
    relative = (
        ("Program Files (x86)", "Steam", "steamapps", "common", game.steam_folder_name),
        ("Program Files", "Steam", "steamapps", "common", game.steam_folder_name),
        ("Program Files (x86)", "GOG Galaxy", "Games", game.steam_folder_name),
        ("Program Files", "GOG Galaxy", "Games", game.steam_folder_name),
    )
    return [drive.joinpath(*parts) for drive in _fixed_drives() for parts in relative]


class GameDetector:
    def __init__(
        self,
        steam_libraries: Callable[[], Iterable[Path]] = library_folders,
        gog_roots: Callable[[], Iterable[Path]] = _gog_roots,
        standard_paths: Callable[[GameType], Iterable[Path]] = _standard_paths,
    ) -> None:
        self._steam_libraries = steam_libraries
        self._gog_roots = gog_roots
        self._standard_paths = standard_paths

    def candidates(self, game: GameType) -> Iterable[Path]:
        for library in self._steam_libraries():
            apps = steamapps_dir(library)
            common = find_child_ci(apps, "common") if apps else None
            if common is not None:
                folder = find_child_ci(common, game.steam_folder_name)
                if folder is not None:
                    yield folder
        for root in self._gog_roots():
            for name in (game.gog_folder_name, game.steam_folder_name):
                folder = find_child_ci(root, name)
                if folder is not None:
                    yield folder
        yield from self._standard_paths(game)

    def find_root(self, game: GameType, saved_path: str = "") -> Path | None:
        if saved_path:
            saved = Path(saved_path)
            if is_valid_game_folder(saved, game):
                return saved
            log.warning("Saved path for %s is not valid right now: %s", game.value, saved_path)
        for candidate in self.candidates(game):
            if is_valid_game_folder(candidate, game):
                log.info("Found %s at %s", game.value, candidate)
                return candidate
        return None

    def detect(self, game: GameType, saved_path: str = "") -> GameInstall | None:
        root = self.find_root(game, saved_path)
        if root is None:
            return None
        executable = find_executable(root, game)
        return make_install(game, root, executable) if executable else None

"""Detection of KCD1/KCD2 installations on Windows and Linux.

Search order per game: saved path -> Steam libraries (registry on Windows, well-known
directories on Linux incl. Flatpak/Snap, plus ``libraryfolders.vdf``) -> GOG Galaxy (Windows)
-> standard locations on all fixed drives (Windows). On Linux the game runs through Proton, so the
Windows build with ``KingdomCome.exe`` is what we look for.
"""

from __future__ import annotations

import logging
import os
import string
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from kcd_mod_manager.domain.models import GameInstall, GameType
from kcd_mod_manager.infrastructure.fs import read_text
from kcd_mod_manager.infrastructure.paths import find_child_ci, resolve_ci
from kcd_mod_manager.infrastructure.pe_version import read_file_version
from kcd_mod_manager.infrastructure.steam import library_folders, steamapps_dir

log = logging.getLogger(__name__)

EXECUTABLE_NAME = "KingdomCome.exe"
_BIN_CANDIDATES: dict[GameType, tuple[tuple[str, ...], ...]] = {
    GameType.KCD1: (("Bin", "Win64"),),
    GameType.KCD2: (("Bin", "Win64MasterMasterSteamPGO"), ("Bin", "Win64")),
}


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


def read_game_version(root: Path, executable: Path) -> str | None:
    version_file = find_child_ci(root, "version.txt")
    if version_file is not None and version_file.is_file():
        try:
            text = read_text(version_file).strip()
            if text:
                return text
        except (OSError, UnicodeDecodeError):
            pass
    return read_file_version(executable)


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

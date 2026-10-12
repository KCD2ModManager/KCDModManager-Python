"""Shared fixtures. Every test runs against temporary directories only - never real user data
or a real game installation."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kcd_mod_manager.application.library import ModLibrary
from kcd_mod_manager.application.session import ManagerSession
from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.categories_store import CategoryStore
from kcd_mod_manager.infrastructure.conflict_scanner import ConflictScanner
from kcd_mod_manager.infrastructure.game_detection import GameDetector, make_install
from kcd_mod_manager.infrastructure.order_files import OrderFileManager
from kcd_mod_manager.infrastructure.profiles_store import ProfileStore
from kcd_mod_manager.infrastructure.repositories import UserModDataRepository
from kcd_mod_manager.infrastructure.settings_store import SettingsStore


@pytest.fixture(autouse=True)
def _isolate_user_dirs(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every user-data location at a temp directory."""
    root = tmp_path_factory.mktemp("userdirs")
    monkeypatch.setenv("KCDMM_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("APPDATA", str(root / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(root / "localappdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "xdg"))


def write_manifest(folder: Path, name: str, version: str, mod_id: str | None = None, extra: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    modid = f"<modid>{mod_id}</modid>" if mod_id is not None else ""
    path = folder / "mod.manifest"
    path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n<kcd_mod><info><name>{name}</name>'
        f"<description>d</description><author>a</author><version>{version}</version>{modid}{extra}"
        "</info></kcd_mod>\n",
        encoding="utf-8",
    )
    return path


def write_pak(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def make_mod(
    mods_dir: Path, mod_id: str, version: str = "1.0", paks: dict[str, dict[str, bytes]] | None = None
) -> Path:
    folder = mods_dir / mod_id
    write_manifest(folder, mod_id.replace("_", " ").title(), version, mod_id)
    for pak_name, entries in (paks or {"data/data.pak": {f"{mod_id}.xml": b"x"}}).items():
        write_pak(folder / pak_name, entries)
    return folder


def make_zip(path: Path, files: dict[str, str | bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


MANIFEST_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8"?>\n<kcd_mod><info><name>{name}</name><description>d</description>'
    "<author>a</author><version>{version}</version>{modid}</info></kcd_mod>\n"
)


def manifest_xml(name: str, version: str, mod_id: str | None = None) -> str:
    return MANIFEST_TEMPLATE.format(
        name=name, version=version, modid=f"<modid>{mod_id}</modid>" if mod_id else ""
    )


@pytest.fixture
def game_root(tmp_path: Path) -> Path:
    root = tmp_path / "library" / "steamapps" / "common" / "KingdomComeDeliverance2"
    exe_dir = root / "Bin" / "Win64MasterMasterSteamPGO"
    exe_dir.mkdir(parents=True)
    (exe_dir / "KingdomCome.exe").write_bytes(b"MZ fake executable")
    (root / "Data").mkdir()
    (root / "Mods").mkdir()
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    return root


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    p = AppPaths(tmp_path / "appdata")
    p.ensure()
    return p


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings()


@pytest.fixture
def session(paths: AppPaths, settings: AppSettings, game_root: Path) -> Iterator[ManagerSession]:
    order_files = OrderFileManager(paths.safety_dir, sleep=lambda _s: None)
    s = ManagerSession(
        paths=paths,
        settings_store=SettingsStore(paths.settings_file),
        settings=settings,
        library=ModLibrary(order_files),
        order_files=order_files,
        profiles=ProfileStore(paths.profiles_dir),
        categories=CategoryStore(paths.categories_file),
        user_data=UserModDataRepository(paths.user_mod_data_file),
        scanner=ConflictScanner(),
        detector=GameDetector(steam_libraries=lambda: [], gog_roots=lambda: [], standard_paths=lambda _g: []),
    )
    install = make_install(
        GameType.KCD2, game_root, game_root / "Bin" / "Win64MasterMasterSteamPGO" / "KingdomCome.exe"
    )
    s.installs[GameType.KCD2] = install
    s.select_game(GameType.KCD2)
    yield s

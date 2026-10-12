from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.infrastructure import steam
from kcd_mod_manager.infrastructure.app_paths import AppPaths, default_data_dir
from kcd_mod_manager.infrastructure.credentials import FileCredentialStore, MemoryCredentialStore
from kcd_mod_manager.infrastructure.game_detection import (
    GameDetector,
    find_executable,
    game_root_from_executable,
    read_game_version,
)
from kcd_mod_manager.infrastructure.logging_setup import RedactingFilter
from kcd_mod_manager.infrastructure.pe_version import read_file_version
from kcd_mod_manager.infrastructure.platform_actions import build_arguments, open_url

VDF = r""""libraryfolders"
{
	"0"
	{
		"path"		"C:\\Program Files (x86)\\Steam"
		"apps" { "228980" "1" }
	}
	"1"
	{
		"path"		"D:\\SteamLibrary"
	}
}"""


def test_parse_library_folders() -> None:
    assert steam.parse_library_folders(VDF) == [
        Path("C:\\Program Files (x86)\\Steam"),
        Path("D:\\SteamLibrary"),
    ]


def test_parse_app_manifest() -> None:
    text = '"AppState"\n{\n\t"appid"\t\t"1771300"\n\t"installdir"\t\t"KingdomComeDeliverance2"\n}'
    assert steam.parse_app_manifest(text) == (1771300, "KingdomComeDeliverance2")


def test_workshop_path_detection() -> None:
    assert steam.is_workshop_path(Path("/home/u/.steam/steam/steamapps/workshop/content/1771300/1"))
    assert steam.is_workshop_path(Path("C:/Steam/SteamApps/Workshop/Content/1/2"))
    assert not steam.is_workshop_path(Path("/games/Mods/x"))


def test_library_folders_from_fake_steam(tmp_path: Path) -> None:
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    second = tmp_path / "Lib2"
    (second / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "1" {{ "path" "{second.as_posix()}" }} }}'
    )
    assert steam.library_folders([root]) == [root, second]


def test_detector_finds_game_in_steam_library(game_root: Path) -> None:
    library = game_root.parent.parent.parent
    detector = GameDetector(
        steam_libraries=lambda: [library], gog_roots=lambda: [], standard_paths=lambda _g: []
    )
    install = detector.detect(GameType.KCD2)
    assert install is not None
    assert install.root_path == game_root
    assert install.mods_path == game_root / "Mods"
    assert install.game_version == "1.2.3"
    assert detector.detect(GameType.KCD1) is None


def test_saved_path_wins_and_invalid_saved_path_is_skipped(game_root: Path, tmp_path: Path) -> None:
    detector = GameDetector(steam_libraries=lambda: [], gog_roots=lambda: [], standard_paths=lambda _g: [])
    assert detector.find_root(GameType.KCD2, str(game_root)) == game_root
    assert detector.find_root(GameType.KCD2, str(tmp_path / "gone")) is None


def test_case_insensitive_executable_lookup(tmp_path: Path) -> None:
    root = tmp_path / "kcd"
    exe_dir = root / "bin" / "win64"
    exe_dir.mkdir(parents=True)
    (exe_dir / "kingdomcome.exe").write_bytes(b"MZ")
    found = find_executable(root, GameType.KCD1)
    assert found is not None and found.name.lower() == "kingdomcome.exe"


def test_root_from_executable(game_root: Path, tmp_path: Path) -> None:
    exe = game_root / "Bin" / "Win64MasterMasterSteamPGO" / "KingdomCome.exe"
    assert game_root_from_executable(exe) == game_root
    odd = tmp_path / "Kingdom Come Deliverance II" / "x" / "y" / "KingdomCome.exe"
    assert game_root_from_executable(odd) == tmp_path / "Kingdom Come Deliverance II"


def test_pe_version(tmp_path: Path) -> None:
    exe = tmp_path / "KingdomCome.exe"
    blob = (
        b"MZ"
        + b"\0" * 100
        + struct.pack("<IIII", 0xFEEF04BD, 0x10000, (1 << 16) | 2, (3 << 16) | 4)
        + b"\0" * 64
    )
    exe.write_bytes(blob)
    assert read_file_version(exe) == "1.2.3.4"
    (tmp_path / "plain.exe").write_bytes(b"MZ")
    assert read_file_version(tmp_path / "plain.exe") is None
    assert read_game_version(tmp_path, exe) == "1.2.3.4"


def test_data_dir_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KCDMM_DATA_DIR")
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / "KCDModManager"
    paths = AppPaths(tmp_path / "KCDModManager")
    assert paths.user_mod_data_file.name == "user_mod_data.json"
    assert paths.profiles_dir.name == "profiles"


def test_build_arguments() -> None:
    assert build_arguments("", True) == ["-devmode"]
    assert build_arguments("-skip intro", False) == ["-skip", "intro"]
    assert build_arguments("-devmode", True) == ["-devmode"]


def test_open_url_rejects_unknown_schemes() -> None:
    with pytest.raises(ValueError):
        open_url("file:///etc/passwd")


def test_credential_stores(tmp_path: Path) -> None:
    memory = MemoryCredentialStore()
    memory.set("k")
    assert memory.get() == "k"
    memory.delete()
    assert memory.get() is None

    store = FileCredentialStore(tmp_path / "key")
    assert store.get() is None and not store.is_secure
    store.set("secret")
    assert store.get() == "secret"
    if sys.platform != "win32":
        assert (tmp_path / "key").stat().st_mode & 0o777 == 0o600
    store.delete()
    assert store.get() is None


def test_redacting_filter() -> None:
    import logging

    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "sending apikey=%s", ("abcdefghijklmnopqrstuvwxyz",), None
    )
    RedactingFilter().filter(record)
    assert "abcdefghijklmnop" not in record.getMessage()
    assert "***" in record.getMessage()

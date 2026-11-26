"""Store-aware launch routing and game-version hardening."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kcd_mod_manager.domain.models import GameInstall, GameType, LaunchStore
from kcd_mod_manager.domain.naming import sanitize_folder_name
from kcd_mod_manager.infrastructure import platform_actions as pa
from kcd_mod_manager.infrastructure.game_detection import (
    detect_launch_store,
    is_usable_game_version,
    path_volume_missing,
    read_game_version,
)


def _install(tmp_path: Path, store: LaunchStore = LaunchStore.UNKNOWN) -> GameInstall:
    exe = tmp_path / "Bin" / "Win64" / "KingdomCome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return GameInstall(
        game=GameType.KCD2,
        root_path=tmp_path,
        executable_path=exe,
        mods_path=tmp_path / "Mods",
        game_version="1.5.6.0",
        launch_store=store,
    )


def test_sanitize_folder_name_replaces_spaces() -> None:
    assert sanitize_folder_name("My Cool Mod") == "My_Cool_Mod"
    assert sanitize_folder_name("  a  ") == "a"


def test_bogus_versions_rejected() -> None:
    assert not is_usable_game_version("1.0.0.0")
    assert not is_usable_game_version("")
    assert is_usable_game_version("1.5.6.0")


def test_read_game_version_prefers_version_txt_over_bogus_pe(tmp_path: Path) -> None:
    (tmp_path / "version.txt").write_text("1.5.6.0\n", encoding="utf-8")
    exe = tmp_path / "KingdomCome.exe"
    exe.write_bytes(b"MZ")
    assert read_game_version(tmp_path, exe) == "1.5.6.0"


def test_detect_epic_from_egstore(tmp_path: Path) -> None:
    (tmp_path / ".egstore").mkdir()
    exe = tmp_path / "Bin" / "Win64MasterMasterEpicPGO" / "KingdomCome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert detect_launch_store(tmp_path, exe) is LaunchStore.EPIC


def test_path_volume_missing_relative_is_false(tmp_path: Path) -> None:
    assert path_volume_missing(tmp_path / "game") is False


def test_launch_steam_uses_applaunch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install(tmp_path, LaunchStore.STEAM)
    calls: list[list[str]] = []
    monkeypatch.setattr(pa, "is_game_running", lambda _i: False)
    monkeypatch.setattr(pa.shutil, "which", lambda _n: "C:/Steam/steam.exe")
    monkeypatch.setattr(
        pa.subprocess,
        "Popen",
        lambda cmd, **_k: calls.append(list(cmd)) or MagicMock(),
    )
    result = pa.launch_game(install, "", False)
    assert result.method == "steam"
    assert calls and calls[0][:3] == ["C:/Steam/steam.exe", "-applaunch", "1771300"]


def test_launch_epic_uses_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install(tmp_path, LaunchStore.EPIC)
    opened: list[str] = []
    monkeypatch.setattr(pa, "is_game_running", lambda _i: False)
    monkeypatch.setattr(pa, "open_url", lambda url: opened.append(url))
    result = pa.launch_game(install, "-devmode", True)
    assert result.method == "epic"
    assert not result.arguments_applied
    assert opened and opened[0].startswith("com.epicgames.launcher://apps/")
    assert "action=launch" in opened[0]


def test_launch_via_store_off_runs_exe_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install(tmp_path, LaunchStore.STEAM)
    calls: list[list[str]] = []
    monkeypatch.setattr(pa, "is_game_running", lambda _i: False)
    monkeypatch.setattr(
        pa.subprocess,
        "Popen",
        lambda cmd, **_k: calls.append(list(cmd)) or MagicMock(),
    )
    result = pa.launch_game(install, "-devmode", True, via_store=False)
    assert result.method == "direct"
    assert calls and calls[0][0].endswith("KingdomCome.exe")
    assert "-devmode" in calls[0]


def test_unknown_install_always_direct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install(tmp_path, LaunchStore.UNKNOWN)
    calls: list[list[str]] = []
    monkeypatch.setattr(pa, "is_game_running", lambda _i: False)
    monkeypatch.setattr(
        pa.subprocess,
        "Popen",
        lambda cmd, **_k: calls.append(list(cmd)) or MagicMock(),
    )
    result = pa.launch_game(install, "", True, via_store=True)
    assert result.method == "direct"
    assert "-devmode" in calls[0]

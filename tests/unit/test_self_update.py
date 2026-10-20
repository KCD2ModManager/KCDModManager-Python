from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from kcd_mod_manager.domain.models import GameInstall, GameType
from kcd_mod_manager.infrastructure.platform_actions import is_game_running
from kcd_mod_manager.infrastructure.self_update import (
    InstallKind,
    SelfUpdateError,
    asset_name,
    detect_install_kind,
    parse_checksums,
    prepare_update,
)


def test_game_running_matches_the_exact_executable(tmp_path: Path) -> None:
    root = tmp_path / "KingdomComeDeliverance2"
    exe = root / "Bin" / "KingdomCome.exe"
    other = tmp_path / "other" / "KingdomCome.exe"
    install = GameInstall(GameType.KCD2, root, exe, root / "Mods")
    assert is_game_running(install, [other, exe])
    assert not is_game_running(install, [other])
    assert not is_game_running(install, [])


def test_detect_install_kind() -> None:
    exe = Path("C:/Games/KCDModManager/KCDModManager.exe")
    assert detect_install_kind(exe, frozen=False, platform="win32") is InstallKind.SOURCE
    assert detect_install_kind(exe, frozen=True, platform="win32") is InstallKind.WINDOWS_PORTABLE
    linux = Path("/home/user/KCDModManager/KCDModManager")
    assert detect_install_kind(linux, frozen=True, platform="linux", environ={}) is InstallKind.LINUX_PORTABLE
    appimage = {"APPIMAGE": "/home/user/KCDModManager.AppImage"}
    assert (
        detect_install_kind(linux, frozen=True, platform="linux", environ=appimage)
        is InstallKind.LINUX_APPIMAGE
    )


def test_asset_names_and_checksums() -> None:
    assert asset_name("5.3.0", InstallKind.WINDOWS_PORTABLE) == "KCDModManager-5.3.0-windows-x64-portable.zip"
    assert asset_name("5.3.0", InstallKind.LINUX_APPIMAGE) == "KCDModManager-5.3.0-x86_64.AppImage"
    assert asset_name("5.3.0", InstallKind.SOURCE) is None
    sums = parse_checksums("abc  KCDModManager-5.3.0-windows-x64-portable.zip\n")
    assert sums == {"KCDModManager-5.3.0-windows-x64-portable.zip": "abc"}


def _release_transport(asset: bytes, sums: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("SHA256SUMS-windows.txt"):
            return httpx.Response(200, text=sums)
        return httpx.Response(200, content=asset)

    return httpx.MockTransport(handler)


def test_prepare_portable_update_verifies_checksum(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("KCDModManager/KCDModManager.exe", b"new")
    asset = buffer.getvalue()
    sums = f"{hashlib.sha256(asset).hexdigest()}  KCDModManager-9.9.9-windows-x64-portable.zip\n"
    apply_update = prepare_update(
        "9.9.9",
        InstallKind.WINDOWS_PORTABLE,
        transport=_release_transport(asset, sums),
        executable=tmp_path / "KCDModManager" / "KCDModManager.exe",
        work_dir=tmp_path / "update",
    )
    assert callable(apply_update)
    script = (tmp_path / "update" / "apply-update.ps1").read_text(encoding="utf-8")
    assert "robocopy" in script and str(tmp_path / "KCDModManager") in script


def test_prepare_update_rejects_a_bad_checksum(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("KCDModManager/KCDModManager.exe", b"new")
    sums = f"{'0' * 64}  KCDModManager-9.9.9-windows-x64-portable.zip\n"
    with pytest.raises(SelfUpdateError):
        prepare_update(
            "9.9.9",
            InstallKind.WINDOWS_PORTABLE,
            transport=_release_transport(buffer.getvalue(), sums),
            executable=tmp_path / "KCDModManager" / "KCDModManager.exe",
            work_dir=tmp_path / "update",
        )

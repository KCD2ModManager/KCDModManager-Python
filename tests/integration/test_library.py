from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kcd_mod_manager.application.library import InstallStatus, ModLibrary, replace_directory
from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain.models import GameType, Mod
from kcd_mod_manager.infrastructure.archives import ArchiveError, extract_archive
from kcd_mod_manager.infrastructure.game_detection import make_install
from kcd_mod_manager.infrastructure.order_files import OrderFileManager
from kcd_mod_manager.infrastructure.repositories import ModVersionsRepository
from tests.conftest import make_mod, make_zip, manifest_xml, write_manifest, write_pak


@pytest.fixture
def library(tmp_path: Path) -> ModLibrary:
    return ModLibrary(OrderFileManager(tmp_path / "safety", sleep=lambda _s: None))


def install_for(root: Path):
    return make_install(GameType.KCD2, root, root / "Bin" / "Win64MasterMasterSteamPGO" / "KingdomCome.exe")


def test_install_archive_preserves_nested_structure(
    library: ModLibrary, game_root: Path, tmp_path: Path
) -> None:
    archive = make_zip(
        tmp_path / "Better Swords-187-1-2-1700000000.zip",
        {
            "BetterSwords/mod.manifest": manifest_xml("Better Swords", "1.2", "better_swords"),
            "BetterSwords/Data/better_swords.pak": b"pak",
            "BetterSwords/Data/Localization/english_xml.pak": b"loc",
        },
    )
    result = library.install_archive(archive, game_root / "Mods", AppSettings(), 187)
    assert result.status is InstallStatus.INSTALLED and result.mod is not None
    target = game_root / "Mods" / "better_swords"
    assert (target / "mod.manifest").is_file()
    assert (target / "Data" / "Localization" / "english_xml.pak").is_file()
    assert result.mod.is_enabled is False
    info = ModVersionsRepository(game_root / "Mods").load()["better_swords"]
    assert (info.version, info.mod_number, info.file_name) == ("1.2", 187, archive.name)


def test_install_archive_refuses_same_or_older(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    make_mod(game_root / "Mods", "sword", "2.0")
    archive = make_zip(
        tmp_path / "sword.zip", {"mod.manifest": manifest_xml("Sword", "1.5", "sword"), "a.pak": b""}
    )
    result = library.install_archive(archive, game_root / "Mods", AppSettings(), -1)
    assert result.status is InstallStatus.NOT_NEWER
    assert "2.0" in (game_root / "Mods" / "sword" / "mod.manifest").read_text()


def test_install_archive_upgrades_existing(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    folder = make_mod(game_root / "Mods", "sword", "1.0")
    (folder / "old_only.txt").write_text("x")
    archive = make_zip(
        tmp_path / "sword.zip", {"mod.manifest": manifest_xml("Sword", "1.1", "sword"), "b.pak": b""}
    )
    result = library.install_archive(archive, game_root / "Mods", AppSettings(), 1)
    assert result.status is InstallStatus.INSTALLED
    assert not (folder / "old_only.txt").exists()
    assert (folder / "b.pak").exists()
    assert not [p for p in (game_root / "Mods").iterdir() if p.name.startswith(".")]


def test_install_archive_generates_manifest_for_pak_only(
    library: ModLibrary, game_root: Path, tmp_path: Path
) -> None:
    archive = make_zip(tmp_path / "Cool Mod-55-2-1-1700000000.zip", {"Data/cool.pak": b""})
    result = library.install_archive(archive, game_root / "Mods", AppSettings(), 55)
    assert result.status is InstallStatus.INSTALLED and result.mod is not None
    assert result.mod.version == "2.1"
    assert result.mod.id == "Cool Mod-55-2-1-1700000000"


def test_install_archive_invalid_manifest_requires_confirmation(
    library: ModLibrary, game_root: Path, tmp_path: Path
) -> None:
    archive = make_zip(tmp_path / "bad.zip", {"mod.manifest": "<kcd_mod><info/></kcd_mod>", "x.pak": b""})
    assert (
        library.install_archive(archive, game_root / "Mods", AppSettings(), 1).status
        is InstallStatus.INVALID_MANIFEST
    )
    assert not (game_root / "Mods" / "bad").exists()
    result = library.install_archive(
        archive, game_root / "Mods", AppSettings(), 1, allow_generated_manifest=True
    )
    assert result.status is InstallStatus.INSTALLED


def test_install_archive_without_renaming_keeps_folder_name(
    library: ModLibrary, game_root: Path, tmp_path: Path
) -> None:
    archive = make_zip(
        tmp_path / "pack.zip",
        {"Original Folder/mod.manifest": manifest_xml("N", "1.0", "nid"), "Original Folder/a.pak": b""},
    )
    result = library.install_archive(archive, game_root / "Mods", AppSettings(enable_file_renaming=False), 1)
    assert result.status is InstallStatus.INSTALLED
    assert (game_root / "Mods" / "Original Folder" / "mod.manifest").exists()


def test_not_a_mod(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "readme.zip", {"readme.txt": "hi"})
    assert (
        library.install_archive(archive, game_root / "Mods", AppSettings(), 1).status
        is InstallStatus.NOT_A_MOD
    )


def test_zip_slip_is_blocked(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "x")
        zf.writestr("/abs.txt", "x")
        zf.writestr("ok/file.txt", "x")
    extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()
    assert (tmp_path / "out" / "ok" / "file.txt").exists()
    assert (tmp_path / "out" / "abs.txt").exists()


def test_7z_extraction(tmp_path: Path) -> None:
    import py7zr

    src = tmp_path / "src" / "Mod"
    write_manifest(src, "Seven", "1.0", "seven")
    archive = tmp_path / "seven.7z"
    with py7zr.SevenZipFile(archive, "w") as sz:
        sz.writeall(src, arcname="Mod")
    extract_archive(archive, tmp_path / "out")
    assert (tmp_path / "out" / "Mod" / "mod.manifest").exists()


def test_corrupt_archive(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ArchiveError):
        extract_archive(bad, tmp_path / "out")


def test_install_folder(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    source = tmp_path / "Downloads" / "SomeMod"
    write_manifest(source, "Some Mod", "3.0", None)
    write_pak(source / "Data" / "x.pak", {"a.xml": b""})
    result = library.install_folder(source, game_root / "Mods", AppSettings())
    assert result.status is InstallStatus.INSTALLED and result.mod is not None
    assert result.mod.id == "Some Mod"
    assert (game_root / "Mods" / "Some Mod" / "Data" / "x.pak").exists()
    assert "<modid>" not in (source / "mod.manifest").read_text()  # source untouched


def test_install_workshop_folder_marks_sidecar(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    source = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "1771300" / "3141592"
    write_manifest(source, "Workshop Thing", "1.0", None)
    result = library.install_folder(source, game_root / "Mods", AppSettings())
    assert result.mod is not None and result.mod.is_workshop_mod and result.mod.workshop_id == "3141592"
    assert (game_root / "Mods" / "3141592" / "mod.meta.json").exists()
    assert "<modid>" not in (source / "mod.manifest").read_text()


def test_load_mods_order_metadata_and_rename(library: ModLibrary, game_root: Path) -> None:
    mods_dir = game_root / "Mods"
    make_mod(mods_dir, "alpha")
    make_mod(mods_dir, "beta")
    folder = mods_dir / "Gamma Folder"
    write_manifest(folder, "Gamma", "1.0", "gamma")
    write_pak(folder / "g.pak", {"g": b""})
    write_pak(mods_dir / "PakOnly" / "p.pak", {"p": b""})
    (mods_dir / "not_a_mod").mkdir()
    (mods_dir / "mod_order.txt").write_text("beta\n# alpha\n", encoding="utf-8")
    (mods_dir / "mod_versions.json").write_text(
        '{"beta": {"Version": "9", "ModNumber": 42, "UpdateChecksEnabled": false}}'
    )
    (mods_dir / "mod_notes.json").write_text('{"alpha": "remember"}')

    mods = library.load_mods(install_for(game_root), AppSettings())
    ids = [m.id for m in mods]
    assert ids[:2] == ["beta", "alpha"]
    assert set(ids[2:]) == {"gamma", "PakOnly"}
    beta, alpha = mods[0], mods[1]
    assert beta.is_enabled and not alpha.is_enabled
    assert beta.mod_number == 42 and not beta.update_checks_enabled and beta.version == "1.0"
    assert alpha.note == "remember"
    assert all(m.is_enabled for m in mods[2:])
    assert (mods_dir / "gamma").is_dir() and not folder.exists()
    assert (mods_dir / "PakOnly" / "mod.manifest").exists()


def test_load_mods_never_deletes_on_rename_collision(library: ModLibrary, game_root: Path) -> None:
    mods_dir = game_root / "Mods"
    make_mod(mods_dir, "dup")
    other = mods_dir / "Other Folder"
    write_manifest(other, "Other", "1.0", "dup")
    (other / "precious.txt").write_text("keep")
    library.load_mods(install_for(game_root), AppSettings())
    assert (mods_dir / "dup" / "mod.manifest").exists()
    assert (other / "precious.txt").read_text() == "keep"


def test_load_mods_without_renaming_leaves_folders(library: ModLibrary, game_root: Path) -> None:
    folder = game_root / "Mods" / "Gamma Folder"
    write_manifest(folder, "Gamma", "1.0", None)
    mods = library.load_mods(install_for(game_root), AppSettings(enable_file_renaming=False))
    assert folder.exists() and mods[0].path == folder
    assert "<modid>" not in (folder / "mod.manifest").read_text()


def test_load_workshop_mods_in_memory(library: ModLibrary, game_root: Path) -> None:
    steamapps = game_root.parent.parent
    (steamapps / "appmanifest_1771300.acf").write_text(
        '"AppState"\n{\n "appid" "1771300"\n "installdir" "KingdomComeDeliverance2"\n}'
    )
    ws = steamapps / "workshop" / "content" / "1771300" / "998877"
    write_manifest(ws, "From Workshop", "1.0", None)
    (game_root / "Mods" / "mod_order.txt").write_text("# From Workshop\n")
    mods = library.load_mods(install_for(game_root), AppSettings())
    assert len(mods) == 1 and mods[0].is_workshop_mod and mods[0].id == "From Workshop"
    assert mods[0].is_enabled is False
    assert "<modid>" not in (ws / "mod.manifest").read_text()


def test_compatibility_flag(library: ModLibrary, game_root: Path) -> None:
    write_manifest(game_root / "Mods" / "old", "Old", "1.0", "old", extra="<gameVersion>1.1</gameVersion>")
    write_manifest(game_root / "Mods" / "ok", "Ok", "1.0", "ok", extra="<gameVersion>1.2</gameVersion>")
    mods = {m.id: m for m in library.load_mods(install_for(game_root), AppSettings())}
    assert not mods["old"].is_compatible and mods["ok"].is_compatible


def test_apply_update_keeps_old_copy_on_failure(library: ModLibrary, game_root: Path, tmp_path: Path) -> None:
    folder = make_mod(game_root / "Mods", "sword", "1.0")
    mod = Mod("sword", "Sword", "1.0", path=folder)
    bad = tmp_path / "update.zip"
    bad.write_bytes(b"corrupt")
    with pytest.raises(ArchiveError):
        library.apply_update(bad, mod, AppSettings())
    assert (folder / "mod.manifest").exists()

    good = make_zip(
        tmp_path / "good.zip",
        {"Sword/mod.manifest": manifest_xml("Sword", "1.1", "sword"), "Sword/new.pak": b""},
    )
    info = library.apply_update(good, mod, AppSettings())
    assert info.version == "1.1" and (folder / "new.pak").exists()


def test_replace_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "new.txt").write_text("n")
    target = tmp_path / "target"
    target.mkdir()
    (target / "old.txt").write_text("o")
    replace_directory(src, target)
    assert (target / "new.txt").exists() and not (target / "old.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["src", "target"]


def test_backup_and_prune(library: ModLibrary, game_root: Path) -> None:
    from datetime import datetime, timedelta

    make_mod(game_root / "Mods", "a")
    start = datetime(2026, 1, 1, 12, 0, 0)
    created = []
    for i in range(3):
        stamp = start + timedelta(seconds=i)
        created.append(library.create_backup(game_root / "Mods", 2, now=lambda stamp=stamp: stamp))
    backups = sorted(p.name for p in (game_root / "Mods_Backup").iterdir())
    assert len(backups) == 2
    assert (game_root / "Mods_Backup" / "unrelated").exists() is False
    assert created[-1] is not None and (created[-1] / "a" / "mod.manifest").exists()

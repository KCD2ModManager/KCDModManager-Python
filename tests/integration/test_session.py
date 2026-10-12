from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from kcd_mod_manager.application.library import InstallStatus
from kcd_mod_manager.application.session import ManagerSession, SessionError
from kcd_mod_manager.domain.highlight import preset
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.infrastructure.conflict_scanner import ScanCancelled
from kcd_mod_manager.infrastructure.repositories import ModVersionsRepository
from tests.conftest import make_mod, make_zip, manifest_xml


def order_lines(session: ManagerSession) -> list[str]:
    return (session.mods_dir / "mod_order.txt").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def loaded(session: ManagerSession) -> ManagerSession:
    for mod_id in ("alpha", "beta", "gamma"):
        make_mod(session.mods_dir, mod_id)
    (session.mods_dir / "mod_order.txt").write_text("alpha\nbeta\n# gamma\n")
    session.reload()
    session.load_profiles()
    name = session.initial_profile_name()
    assert name is not None
    session.apply_profile(name)
    return session


def test_first_start_creates_default_profile_from_current_state(loaded: ManagerSession) -> None:
    assert [p.profile_name for p in loaded.profiles] == ["Default"]
    assert loaded.selected_profile == "Default"
    assert order_lines(loaded) == ["alpha", "beta", "# gamma"]
    assert loaded.settings.last_used_profile(GameType.KCD2) == "Default"


def test_toggle_and_reorder_persist_to_profile_and_game(loaded: ManagerSession) -> None:
    gamma = loaded.mods[2]
    loaded.set_enabled(gamma, True)
    loaded.move(gamma, list(loaded.mods), 0)
    assert order_lines(loaded) == ["gamma", "alpha", "beta"]
    profile = loaded.profile_store.load(GameType.KCD2, "Default")
    assert profile is not None and profile.load_order == ["gamma", "alpha", "beta"]
    assert set(profile.active_mods) == {"gamma", "alpha", "beta"}


def test_profiles_create_switch_duplicate_delete(loaded: ManagerSession) -> None:
    loaded.create_profile("Vanilla")
    assert loaded.selected_profile == "Vanilla"
    loaded.set_all_enabled(False)  # auto-saves into the active profile only
    with pytest.raises(SessionError):
        loaded.create_profile("Vanilla")

    loaded.apply_profile("Default")
    assert [m.is_enabled for m in loaded.mods] == [True, True, False]
    loaded.apply_profile("Vanilla")
    assert not any(m.is_enabled for m in loaded.mods)
    assert order_lines(loaded) == ["# alpha", "# beta", "# gamma"]

    copy = loaded.duplicate_profile("Default", "Default copy")
    assert copy.active_mods == ["alpha", "beta"]
    assert loaded.selected_profile == "Vanilla"  # duplicating must not switch or modify the live state

    assert loaded.delete_profile("Vanilla") == "Default"
    assert [p.profile_name for p in loaded.profiles] == ["Default", "Default copy"]


def test_mod_order_disabled_writes_backup_file(loaded: ManagerSession) -> None:
    loaded.settings.mod_order_enabled = False
    loaded.order_files.apply_setting(False, loaded.mods_dir)
    loaded.set_enabled(loaded.mods[0], False)
    assert not (loaded.mods_dir / "mod_order.txt").exists()
    assert (loaded.mods_dir / "mod_order_backup.txt").read_text().splitlines()[0] == "# alpha"


def test_install_archive_adds_disabled_mod_at_end(loaded: ManagerSession, tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "Delta-77-1-0-1.zip", {"mod.manifest": manifest_xml("Delta", "1.0", "delta"), "d.pak": b""}
    )
    result = loaded.install_archive(archive, 77)
    assert result.status is InstallStatus.INSTALLED
    assert loaded.mods[-1].id == "delta" and not loaded.mods[-1].is_enabled
    assert order_lines(loaded)[-1] == "# delta"
    profile = loaded.profile_store.load(GameType.KCD2, "Default")
    assert profile is not None and profile.load_order[-1] == "delta"


def test_delete_mod(loaded: ManagerSession) -> None:
    beta = loaded.mods[1]
    assert beta.path is not None
    path = beta.path
    loaded.delete_mod(beta)
    assert not path.exists()
    assert order_lines(loaded) == ["alpha", "# gamma"]


def test_user_data_merge_on_reload(loaded: ManagerSession) -> None:
    alpha = loaded.mods[0]
    loaded.rename_display(alpha, "Alpha Renamed")
    loaded.set_custom_version(alpha, "9.9")
    loaded.set_highlight(alpha, preset("green"))
    loaded.set_ignored_in_conflicts(alpha, True)
    loaded.set_note(alpha, "a note")

    loaded.reload()
    alpha = next(m for m in loaded.mods if m.id == "alpha")
    assert (alpha.name, alpha.version, alpha.note) == ("Alpha Renamed", "9.9", "a note")
    assert alpha.highlight == preset("green") and alpha.ignored_in_conflict_detector

    loaded.set_custom_version(alpha, "")
    assert alpha.version == "1.0"
    loaded.reload()
    assert next(m for m in loaded.mods if m.id == "alpha").version == "1.0"


def test_rename_id_updates_all_references(loaded: ManagerSession) -> None:
    beta = loaded.mods[1]
    loaded.set_note(beta, "keep")
    loaded.set_mod_number(beta, 321)
    loaded.create_profile("Other")
    new_id = loaded.rename_id(beta, "Beta Two")
    assert new_id == "Beta Two"
    assert (loaded.mods_dir / "Beta Two" / "mod.manifest").exists()
    assert not (loaded.mods_dir / "beta").exists()
    notes = json.loads((loaded.mods_dir / "mod_notes.json").read_text())
    assert notes == {"Beta Two": "keep"}
    assert ModVersionsRepository(loaded.mods_dir).load()["Beta Two"].mod_number == 321
    for name in ("Default", "Other"):
        profile = loaded.profile_store.load(GameType.KCD2, name)
        assert profile is not None and profile.load_order[1] == "Beta Two"


def test_rename_id_requires_renaming_setting(loaded: ManagerSession) -> None:
    loaded.settings.enable_file_renaming = False
    with pytest.raises(SessionError):
        loaded.rename_id(loaded.mods[0], "x")


def test_mod_number_and_update_toggle_persist(loaded: ManagerSession) -> None:
    alpha = loaded.mods[0]
    loaded.set_mod_number(alpha, 555)
    loaded.toggle_update_checks(alpha)
    info = ModVersionsRepository(loaded.mods_dir).load()["alpha"]
    assert info.mod_number == 555 and info.update_checks_enabled is False
    loaded.reload()
    alpha = loaded.mods[0]
    assert alpha.mod_number == 555 and not alpha.update_checks_enabled


def test_separator_saved_in_profile(loaded: ManagerSession) -> None:
    loaded.toggle_separator(loaded.mods[0])
    profile = loaded.profile_store.load(GameType.KCD2, "Default")
    assert profile is not None and profile.separators_after_mod_ids == ["alpha"]
    loaded.mods[0].has_separator_after = False
    loaded.apply_profile("Default")
    assert loaded.mods[0].has_separator_after


def test_categories_assign_and_delete(loaded: ManagerSession) -> None:
    weapons = loaded.create_category("Weapons")
    armor = loaded.create_category("Armor")
    loaded.set_category(loaded.mods[0], weapons.id)
    loaded.set_category(loaded.mods[1], weapons.id)
    assert loaded.mods[0].category_name == "Weapons"

    remaining = [c for c in loaded.categories if c.id != weapons.id]
    loaded.save_categories(remaining, {weapons.id: armor.id})
    assert loaded.mods[0].category_id == armor.id
    loaded.reload()
    assert loaded.mods[1].category_name == "Armor"


def test_conflict_scan(loaded: ManagerSession) -> None:
    make_mod(loaded.mods_dir, "one", paks={"a.pak": {"Libs/Shared.xml": b"1"}})
    make_mod(loaded.mods_dir, "two", paks={"sub/b.pak": {"libs\\shared.xml": b"2", "own.xml": b""}})
    loaded.reload()
    for mod in loaded.mods:
        mod.is_enabled = True
    progress: list[int] = []
    groups = loaded.scan_conflicts(progress.append)
    assert [(g.file_path, sorted(g.mod_ids)) for g in groups] == [("Libs/Shared.xml", ["one", "two"])]
    assert progress[-1] == 100

    next(m for m in loaded.mods if m.id == "two").ignored_in_conflict_detector = True
    assert loaded.scan_conflicts() == []

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ScanCancelled):
        loaded.scan_conflicts(cancelled=cancelled)


def test_update_manifest_game_version(loaded: ManagerSession) -> None:
    count = loaded.update_manifest_game_version(loaded.mods[:2])
    assert count == 2
    assert "<gameVersion>1.2.3</gameVersion>" in (loaded.mods_dir / "alpha" / "mod.manifest").read_text()


def test_startup_backup(loaded: ManagerSession) -> None:
    path = loaded.startup_maintenance()
    assert path is not None and (path / "alpha" / "mod.manifest").exists()
    loaded.settings.backup_on_startup = False
    assert loaded.startup_maintenance() is None


def test_manual_install_selection(session: ManagerSession, game_root: Path) -> None:
    exe = game_root / "Bin" / "Win64MasterMasterSteamPGO" / "KingdomCome.exe"
    install = session.set_manual_install(GameType.KCD2, exe)
    assert install.root_path == game_root
    assert session.settings.game_path_kcd2 == str(game_root)
    with pytest.raises(SessionError):
        session.set_manual_install(GameType.KCD2, game_root / "version.txt")

"""Migration regressions: data written by the WPF manager keeps working, and the deliberate
behaviour fixes documented in docs/MIGRATION.md stay fixed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kcd_mod_manager.application.session import ManagerSession, SessionError
from kcd_mod_manager.domain.highlight import PRESETS
from kcd_mod_manager.domain.models import GameType, HighlightColor, NexusFile
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.order_files import MOD_ORDER_BACKUP_FILE, MOD_ORDER_FILE
from kcd_mod_manager.infrastructure.settings_store import SettingsStore
from tests.conftest import make_mod, make_zip, manifest_xml, write_manifest, write_pak


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def start(session: ManagerSession) -> None:
    """What the window does after selecting a game."""
    session.startup_maintenance()
    session.reload()
    session.load_profiles()
    name = session.initial_profile_name()
    if name:
        session.apply_profile(name)


def write_wpf_data(paths: AppPaths, mods_dir: Path) -> None:
    for mod_id in ("alpha", "beta", "gamma"):
        make_mod(mods_dir, mod_id)
    (mods_dir / MOD_ORDER_FILE).write_text("beta\n# alpha\ngamma\n", encoding="utf-8")
    (mods_dir / "mod_versions.json").write_text(
        '{"alpha": {"Version": "1.0", "ModNumber": 187, "FileName": "alpha-187-1-0.zip"}}', encoding="utf-8"
    )
    paths.user_mod_data_file.write_text(
        "\ufeff"
        + json.dumps(
            {
                "alpha": {
                    "ModId": "alpha",
                    "CustomVersion": None,
                    "LastDetectedVersion": "1.0",
                    "LastUpdated": "2026-03-03T19:56:41.5165210Z",
                    "CustomNote": None,
                    "CustomName": "Custom Alpha",
                    "CategoryId": "cat-1",
                    "IgnoredInConflictDetector": False,
                    "HighlightColor": {"Light": "#E8F2FF", "Dark": "#223246"},
                    "FutureField": 42,
                },
                "beta": {"ModId": "beta", "CustomVersion": "9.9", "LastDetectedVersion": "1.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    paths.categories_file.write_text(
        '{"SchemaVersion": 1, "Categories": [{"Id": "cat-1", "Name": "Weapons", "Order": 0}]}',
        encoding="utf-8",
    )
    default = paths.profiles_dir / "KCD2" / "Default"
    default.mkdir(parents=True)
    (default / "profile.json").write_text(
        json.dumps(
            {
                "ProfileName": "Default",
                "ActiveMods": ["beta", "gamma"],
                "LoadOrder": ["beta", "alpha", "gamma"],
                "ModCategories": {},
                "SeparatorsAfterModIds": [],
                "LastModified": "2026-03-03T19:56:41.5165210Z",
                "UnknownWpfField": "keep me",
            }
        ),
        encoding="utf-8",
    )
    (default / MOD_ORDER_FILE).write_text("beta\n# alpha\ngamma\n", encoding="utf-8")


def test_wpf_data_snapshot_loads_and_round_trips(session: ManagerSession, paths: AppPaths) -> None:
    write_wpf_data(paths, session.mods_dir)
    start(session)

    mods = {m.id: m for m in session.mods}
    assert [m.id for m in session.mods] == ["beta", "alpha", "gamma"]
    assert [m.is_enabled for m in session.mods] == [True, False, True]
    assert session.selected_profile == "Default"
    assert mods["alpha"].name == "Custom Alpha"
    assert mods["alpha"].category_name == "Weapons"
    assert mods["alpha"].mod_number == 187
    assert mods["alpha"].highlight == HighlightColor("#E8F2FF", "#223246")
    assert mods["beta"].version == "9.9"

    session.set_enabled(mods["alpha"], True)

    user_data = json.loads(paths.user_mod_data_file.read_text(encoding="utf-8-sig"))
    assert user_data["alpha"]["FutureField"] == 42
    assert user_data["alpha"]["CustomName"] == "Custom Alpha"
    assert user_data["beta"]["CustomVersion"] == "9.9"
    profile = json.loads(
        (paths.profiles_dir / "KCD2" / "Default" / "profile.json").read_text(encoding="utf-8")
    )
    assert profile["UnknownWpfField"] == "keep me"
    assert profile["LoadOrder"] == ["beta", "alpha", "gamma"]
    assert set(profile["ActiveMods"]) == {"alpha", "beta", "gamma"}
    assert profile["LastModified"].endswith("Z")
    order = (session.mods_dir / MOD_ORDER_FILE).read_text(encoding="utf-8").splitlines()
    assert order == ["beta", "alpha", "gamma"]


def test_workshop_folders_are_never_written(session: ManagerSession, game_root: Path) -> None:
    steamapps = game_root.parent.parent
    (steamapps / "appmanifest_1771300.acf").write_text(
        '"AppState"\n{\n "appid" "1771300"\n "installdir" "KingdomComeDeliverance2"\n}'
    )
    workshop_root = steamapps / "workshop" / "content" / "1771300"
    ws = workshop_root / "998877"
    write_manifest(ws, "From Workshop", "1.0", None, extra="<gameVersion>1.0</gameVersion>")
    write_pak(ws / "data" / "ws.pak", {"Libs/shared.xml": b"ws"})
    make_mod(session.mods_dir, "local", paks={"data/l.pak": {"libs/Shared.xml": b"local"}})
    before = snapshot(workshop_root)

    start(session)
    workshop = next(m for m in session.mods if m.is_workshop_mod)
    category = session.create_category("Steam")
    session.set_enabled(workshop, True)
    session.move(workshop, list(session.mods), 0)
    session.set_category(workshop, category.id)
    session.rename_display(workshop, "Renamed In Manager")
    session.set_note(workshop, "note")
    session.set_highlight(workshop, PRESETS["blue"])
    session.toggle_separator(workshop)
    session.update_manifest_game_version(session.mods)
    session.scan_conflicts()
    with pytest.raises(SessionError):
        session.delete_mod(workshop)
    with pytest.raises(SessionError):
        session.rename_id(workshop, "New Id")
    session.reload()

    assert snapshot(workshop_root) == before
    assert len(session.conflicts) == 1
    reloaded = next(m for m in session.mods if m.is_workshop_mod)
    assert reloaded.name == "Renamed In Manager"
    assert reloaded.category_name == "Steam"


def test_saved_game_path_is_kept_when_temporarily_invalid(
    session: ManagerSession, paths: AppPaths, tmp_path: Path
) -> None:
    missing = str(tmp_path / "unplugged-drive" / "KCD2")
    session.settings.game_path_kcd2 = missing
    installs = session.detect_games()
    assert installs[GameType.KCD2] is None
    assert session.settings.game_path_kcd2 == missing
    assert SettingsStore(paths.settings_file).load().game_path_kcd2 == missing


def test_clearing_custom_version_restores_detected(session: ManagerSession) -> None:
    make_mod(session.mods_dir, "alpha", "1.0")
    start(session)
    mod = session.mods[0]
    session.set_custom_version(mod, "5.0-custom")
    assert mod.version == "5.0-custom"
    session.set_custom_version(mod, "")
    assert mod.version == "1.0"
    session.reload()
    assert session.mods[0].version == "1.0"


def test_last_used_profile_is_persisted_per_game(session: ManagerSession, paths: AppPaths) -> None:
    make_mod(session.mods_dir, "alpha")
    start(session)
    session.create_profile("Hardcore")
    stored = SettingsStore(paths.settings_file).load()
    assert stored.last_used_profile_kcd2 == "Hardcore"
    assert stored.last_used_profile_kcd1 == ""

    session.select_game(GameType.KCD2)
    session.reload()
    session.load_profiles()
    assert session.initial_profile_name() == "Hardcore"


def test_profile_names_must_be_unique(session: ManagerSession) -> None:
    make_mod(session.mods_dir, "alpha")
    start(session)
    with pytest.raises(SessionError):
        session.create_profile("Default")
    with pytest.raises(SessionError):
        session.duplicate_profile("Default", "Default")


def test_duplicate_profile_does_not_touch_live_state(session: ManagerSession, paths: AppPaths) -> None:
    write_wpf_data(paths, session.mods_dir)
    start(session)
    live_order = (session.mods_dir / MOD_ORDER_FILE).read_bytes()
    session.duplicate_profile("Default", "Copy")
    assert session.selected_profile == "Default"
    assert (session.mods_dir / MOD_ORDER_FILE).read_bytes() == live_order
    copy_dir = paths.profiles_dir / "KCD2" / "Copy"
    assert (copy_dir / MOD_ORDER_FILE).read_bytes() == (
        paths.profiles_dir / "KCD2" / "Default" / MOD_ORDER_FILE
    ).read_bytes()


def test_corrupt_profile_is_preserved_not_silently_replaced(session: ManagerSession, paths: AppPaths) -> None:
    make_mod(session.mods_dir, "alpha")
    default = paths.profiles_dir / "KCD2" / "Default"
    default.mkdir(parents=True)
    (default / "profile.json").write_text("{ broken", encoding="utf-8")
    start(session)
    backups = list(default.glob("profile.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{ broken"
    assert json.loads((default / "profile.json").read_text(encoding="utf-8"))["ProfileName"] == "Default"


def test_stale_mod_order_file_gets_safety_copy(session: ManagerSession, paths: AppPaths) -> None:
    mods_dir = session.mods_dir
    (mods_dir / MOD_ORDER_FILE).write_text("stale\n", encoding="utf-8")
    (mods_dir / MOD_ORDER_BACKUP_FILE).write_text("current\n", encoding="utf-8")
    session.settings.mod_order_enabled = False
    session.startup_maintenance()
    assert not (mods_dir / MOD_ORDER_FILE).exists()
    assert (mods_dir / MOD_ORDER_BACKUP_FILE).read_text(encoding="utf-8") == "current\n"
    copies = list(paths.safety_dir.glob("mod_order_*.txt"))
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == "stale\n"


class _StubNexus:
    def __init__(self, archive: Path) -> None:
        self.archive = archive

    def mod_files(self, domain: str, mod_number: int) -> list[NexusFile]:
        return [NexusFile(1, "2.0", 100, "Alpha 2.0", "2.0")]

    def download_link(self, domain: str, mod_number: int, file_id: int) -> str:
        return "https://cdn.example/alpha.zip"

    def download(self, url: str, mod_number: int, progress: object = None) -> Path:
        return self.archive


def test_update_install_keeps_enabled_state_and_mod_number(session: ManagerSession, tmp_path: Path) -> None:
    write_manifest(session.mods_dir / "alpha", "Alpha", "1.0", "alpha")
    (session.mods_dir / "mod_versions.json").write_text('{"alpha": {"Version": "1.0", "ModNumber": 187}}')
    (session.mods_dir / MOD_ORDER_FILE).write_text("alpha\n", encoding="utf-8")
    start(session)
    mod = session.mods[0]
    assert mod.is_enabled and mod.mod_number == 187
    archive = make_zip(
        tmp_path / "alpha-187-2-0.zip", {"alpha/mod.manifest": manifest_xml("Alpha", "2.0", "alpha")}
    )
    session.nexus = _StubNexus(archive)  # type: ignore[assignment]

    session.install_update(mod)

    assert mod.version == "2.0" and mod.is_enabled and mod.mod_number == 187
    versions = json.loads((session.mods_dir / "mod_versions.json").read_text(encoding="utf-8"))
    assert versions["alpha"]["ModNumber"] == 187 and versions["alpha"]["Version"] == "2.0"
    assert (session.mods_dir / MOD_ORDER_FILE).read_text(encoding="utf-8").splitlines() == ["alpha"]
    assert "2.0" in (session.mods_dir / "alpha" / "mod.manifest").read_text(encoding="utf-8")
    assert not archive.exists()

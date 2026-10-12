"""Persistence must stay byte-compatible with the files the WPF manager wrote."""

from __future__ import annotations

import json
from pathlib import Path

from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain.models import GameType, HighlightColor, Mod, ModProfile, ModVersionInfo
from kcd_mod_manager.infrastructure.categories_store import CategoryStore, ModSidecar
from kcd_mod_manager.infrastructure.fs import CorruptFileError, atomic_write_text, load_json
from kcd_mod_manager.infrastructure.legacy_import import import_legacy_settings
from kcd_mod_manager.infrastructure.order_files import (
    MOD_ORDER_BACKUP_FILE,
    MOD_ORDER_FILE,
    OrderFileManager,
)
from kcd_mod_manager.infrastructure.profiles_store import ProfileStore
from kcd_mod_manager.infrastructure.repositories import (
    ModNotesRepository,
    ModVersionsRepository,
    UserModDataRepository,
)
from kcd_mod_manager.infrastructure.settings_store import SettingsStore

WPF_USER_DATA = """\ufeff{
  "z_dragonborn_longsword": {
    "ModId": "z_dragonborn_longsword",
    "CustomVersion": null,
    "LastDetectedVersion": "1.2",
    "LastUpdated": "2026-03-03T19:56:41.5165210Z",
    "CustomNote": null,
    "CustomName": "Dragonborn Longsword",
    "CategoryId": "cat-1",
    "IgnoredInConflictDetector": true,
    "HighlightColor": { "Light": "#E8F2FF", "Dark": "#223246" },
    "FutureField": 42
  }
}"""

WPF_PROFILE = """{
  "ProfileName": "Default",
  "ActiveMods": ["a", "c"],
  "LoadOrder": ["c", "a", "b"],
  "ModCategories": {},
  "SeparatorsAfterModIds": ["a"],
  "LastModified": "2026-03-03T19:56:41.5165210Z"
}"""

WPF_USER_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <userSettings>
    <KCD2_mod_manager.Settings>
      <setting name="AskOnDelete" serializeAs="String"><value>False</value></setting>
      <setting name="IsDarkMode" serializeAs="String"><value>True</value></setting>
      <setting name="BackupMaxCount" serializeAs="String"><value>7</value></setting>
      <setting name="Language" serializeAs="String"><value>de</value></setting>
      <setting name="NexusUsername" serializeAs="String"><value>henry</value></setting>
      <setting name="NexusUserToken" serializeAs="String"><value>SECRET-TOKEN-VALUE</value></setting>
      <setting name="NexusUserID" serializeAs="String"><value>12345</value></setting>
      <setting name="GamePath_KCD2" serializeAs="String"><value>D:\\Games\\KCD2</value></setting>
      <setting name="ConflictDetector_OnlyEnabledMods" serializeAs="String"><value>False</value></setting>
    </KCD2_mod_manager.Settings>
  </userSettings>
</configuration>"""


def test_atomic_write_and_corrupt_detection(tmp_path: Path) -> None:
    target = tmp_path / "a" / "data.json"
    atomic_write_text(target, '{"x": 1}')
    assert load_json(target) == {"x": 1}
    assert not list(target.parent.glob("*.tmp"))
    target.write_text("{broken", encoding="utf-8")
    try:
        load_json(target)
    except CorruptFileError as exc:
        assert exc.path == target
    else:  # pragma: no cover
        raise AssertionError("expected CorruptFileError")


def test_user_mod_data_round_trip_preserves_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "user_mod_data.json"
    path.write_text(WPF_USER_DATA, encoding="utf-8")
    repo = UserModDataRepository(path)
    entry = repo.load()["z_dragonborn_longsword"]
    assert entry.custom_name == "Dragonborn Longsword"
    assert entry.ignored_in_conflict_detector
    assert entry.highlight == HighlightColor("#E8F2FF", "#223246")

    repo.update_entry("z_dragonborn_longsword", lambda e: setattr(e, "custom_note", "hi"))
    raw = json.loads(path.read_text(encoding="utf-8"))["z_dragonborn_longsword"]
    assert raw["FutureField"] == 42
    assert raw["CustomNote"] == "hi"
    assert raw["HighlightColor"] == {"Light": "#E8F2FF", "Dark": "#223246"}
    assert set(raw) >= {"ModId", "CustomVersion", "LastDetectedVersion", "LastUpdated", "CategoryId"}


def test_corrupt_user_data_is_preserved_before_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "user_mod_data.json"
    path.write_text("{ not json", encoding="utf-8")
    repo = UserModDataRepository(path)
    assert repo.load() == {}
    repo.update_entry("m", lambda e: setattr(e, "custom_note", "n"))
    backups = list(tmp_path.glob("user_mod_data.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{ not json"
    assert "m" in json.loads(path.read_text(encoding="utf-8"))


def test_mod_versions_and_notes(tmp_path: Path) -> None:
    (tmp_path / "mod_versions.json").write_text(
        '{"a": {"Version": "1.0", "ModNumber": 187, "FileName": "a.zip"}}', encoding="utf-8"
    )
    versions = ModVersionsRepository(tmp_path)
    info = versions.load()["a"]
    assert (info.version, info.mod_number, info.update_checks_enabled) == ("1.0", 187, True)
    versions.set("b", ModVersionInfo("2.0", 5, "b.zip", False))
    raw = json.loads((tmp_path / "mod_versions.json").read_text(encoding="utf-8"))
    assert raw["b"] == {"Version": "2.0", "ModNumber": 5, "FileName": "b.zip", "UpdateChecksEnabled": False}
    assert raw["a"]["ModNumber"] == 187

    notes = ModNotesRepository(tmp_path)
    notes.update(lambda n: n.__setitem__("a", "line1\nline2"))
    assert notes.load() == {"a": "line1\nline2"}


def test_categories_store(tmp_path: Path) -> None:
    store = CategoryStore(tmp_path / "categories.json")
    assert store.load() == []
    assert json.loads((tmp_path / "categories.json").read_text()) == {"SchemaVersion": 1, "Categories": []}
    (tmp_path / "categories.json").write_text(
        '{"SchemaVersion":1,"Categories":[{"Id":"cat-b","Name":"B","Order":1},{"Id":"cat-a","Name":"A","Order":0}]}'
    )
    assert [c.id for c in store.load()] == ["cat-a", "cat-b"]
    (tmp_path / "categories.json").write_text("garbage")
    assert store.load() == []
    assert len(list(tmp_path.glob("categories.json.corrupt-*"))) == 1


def test_sidecar_keeps_workshop_flag(tmp_path: Path) -> None:
    sidecar = ModSidecar(tmp_path)
    sidecar.mark_workshop()
    sidecar.set_category("cat-1")
    assert sidecar.category_id == "cat-1" and sidecar.is_workshop
    sidecar.set_category(None)
    assert sidecar.is_workshop and sidecar.category_id is None
    plain = ModSidecar(tmp_path / "other")
    (tmp_path / "other").mkdir()
    plain.set_category("x")
    plain.set_category(None)
    assert not plain.path.exists()


def test_profile_store_reads_wpf_profiles(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    folder = tmp_path / "KCD2" / "Default"
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text(WPF_PROFILE, encoding="utf-8")
    (folder / "mod_order.txt").write_text("c\na\n# b\n", encoding="utf-8")
    (tmp_path / "KCD2" / "Broken").mkdir()
    (tmp_path / "KCD2" / "Broken" / "profile.json").write_text("{", encoding="utf-8")

    profiles = store.list(GameType.KCD2)
    assert [p.profile_name for p in profiles] == ["Default"]
    assert profiles[0].separators_after_mod_ids == ["a"]
    assert [e.mod_id for e in store.read_order(GameType.KCD2, "Default")] == ["c", "a", "b"]

    copy = store.duplicate(GameType.KCD2, "Default", "Copy: 1")
    assert copy.load_order == ["c", "a", "b"]
    assert (tmp_path / "KCD2" / "Copy_ 1" / "mod_order.txt").read_text(encoding="utf-8") == "c\na\n# b\n"
    assert store.load(GameType.KCD2, "Copy: 1") is not None
    store.delete(GameType.KCD2, "Copy: 1")
    assert not (tmp_path / "KCD2" / "Copy_ 1").exists()

    store.save(GameType.KCD2, ModProfile("New", load_order=["x"], extra={"Custom": True}))
    raw = json.loads((tmp_path / "KCD2" / "New" / "profile.json").read_text(encoding="utf-8"))
    assert raw["ProfileName"] == "New" and raw["Custom"] is True and raw["LastModified"].endswith("Z")


class TestOrderFiles:
    """Ported from the original ModOrderFileManagerTests."""

    def manager(self, tmp_path: Path) -> OrderFileManager:
        return OrderFileManager(tmp_path / "safety", sleep=lambda _s: None)

    def test_enable_with_backup_restores(self, tmp_path: Path) -> None:
        (tmp_path / MOD_ORDER_BACKUP_FILE).write_text("mod1\nmod2\n")
        self.manager(tmp_path).apply_setting(True, tmp_path)
        assert (tmp_path / MOD_ORDER_FILE).read_text().splitlines() == ["mod1", "mod2"]
        assert not (tmp_path / MOD_ORDER_BACKUP_FILE).exists()

    def test_disable_moves_to_backup(self, tmp_path: Path) -> None:
        (tmp_path / MOD_ORDER_FILE).write_text("mod1\nmod2\n")
        (tmp_path / MOD_ORDER_BACKUP_FILE).write_text("old\n")
        self.manager(tmp_path).apply_setting(False, tmp_path)
        assert not (tmp_path / MOD_ORDER_FILE).exists()
        assert (tmp_path / MOD_ORDER_BACKUP_FILE).read_text().splitlines() == ["mod1", "mod2"]

    def test_enable_without_backup_creates_empty(self, tmp_path: Path) -> None:
        self.manager(tmp_path).apply_setting(True, tmp_path)
        assert (tmp_path / MOD_ORDER_FILE).read_text() == ""

    def test_consolidate_enabled_restores(self, tmp_path: Path) -> None:
        (tmp_path / MOD_ORDER_BACKUP_FILE).write_text("mod1\n")
        self.manager(tmp_path).consolidate(True, tmp_path)
        assert (tmp_path / MOD_ORDER_FILE).read_text().splitlines() == ["mod1"]
        assert not (tmp_path / MOD_ORDER_BACKUP_FILE).exists()

    def test_consolidate_disabled_moves(self, tmp_path: Path) -> None:
        (tmp_path / MOD_ORDER_FILE).write_text("mod1\n")
        self.manager(tmp_path).consolidate(False, tmp_path)
        assert not (tmp_path / MOD_ORDER_FILE).exists()
        assert (tmp_path / MOD_ORDER_BACKUP_FILE).read_text().splitlines() == ["mod1"]

    def test_consolidate_disabled_both_keeps_backup_and_safety_copy(self, tmp_path: Path) -> None:
        (tmp_path / MOD_ORDER_FILE).write_text("mod1\n")
        (tmp_path / MOD_ORDER_BACKUP_FILE).write_text("mod2\n")
        self.manager(tmp_path).consolidate(False, tmp_path)
        assert not (tmp_path / MOD_ORDER_FILE).exists()
        assert (tmp_path / MOD_ORDER_BACKUP_FILE).read_text().splitlines() == ["mod2"]
        copies = list((tmp_path / "safety").iterdir())
        assert len(copies) == 1 and copies[0].read_text().splitlines() == ["mod1"]

    def test_write_respects_setting(self, tmp_path: Path) -> None:
        manager = self.manager(tmp_path)
        mods = [Mod("a", "A", number=2, is_enabled=True), Mod("b", "B", number=1)]
        manager.write(tmp_path, mods, True)
        assert (tmp_path / MOD_ORDER_FILE).read_text().splitlines() == ["# b", "a"]
        manager.write(tmp_path, mods, False)
        assert not (tmp_path / MOD_ORDER_FILE).exists()
        assert (tmp_path / MOD_ORDER_BACKUP_FILE).read_text().splitlines() == ["# b", "a"]


def test_settings_store_round_trip_and_corruption(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings(is_dark_mode=True, backup_max_count=3)
    settings.extra["future"] = "kept"
    store.save(settings)
    loaded = store.load()
    assert loaded.is_dark_mode and loaded.backup_max_count == 3 and loaded.extra == {"future": "kept"}
    (tmp_path / "settings.json").write_text("{oops")
    assert store.load() == AppSettings()
    assert store.recovered_from_corruption
    assert len(list(tmp_path.glob("settings.json.corrupt-*"))) == 1


def test_legacy_import_picks_newest_config(tmp_path: Path) -> None:
    root = tmp_path / "KCD2_mod_manager"
    old = root / "KCD2_mod_manager_Url_a" / "1.0.0.0" / "user.config"
    new = root / "KCD2_mod_manager_Path_b" / "1.0.0.0" / "user.config"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text(WPF_USER_CONFIG.replace("<value>de</value>", "<value>fr</value>"), encoding="utf-8")
    new.write_text(WPF_USER_CONFIG, encoding="utf-8")
    import os

    os.utime(old, (1_000_000, 1_000_000))
    before = new.read_bytes()

    result = import_legacy_settings(root)
    assert result is not None
    s = result.settings
    assert (s.ask_on_delete, s.is_dark_mode, s.backup_max_count, s.language) == (False, True, 7, "de")
    assert s.game_path_kcd2 == "D:\\Games\\KCD2" and s.nexus_user_id == 12345
    assert not s.conflict_detector_only_enabled_mods
    assert result.nexus_token == "SECRET-TOKEN-VALUE"
    assert s.imported_from_legacy
    assert new.read_bytes() == before  # read-only


def test_legacy_import_absent(tmp_path: Path) -> None:
    assert import_legacy_settings(tmp_path / "missing") is None

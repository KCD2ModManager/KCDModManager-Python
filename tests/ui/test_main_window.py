"""Main window behaviour, driven headless (QT_QPA_PLATFORM=offscreen) against temp data only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QModelIndex, QObject
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from kcd_mod_manager import __version__
from kcd_mod_manager.bootstrap import AppContext, build_context
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.i18n import tr
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.credentials import MemoryCredentialStore
from kcd_mod_manager.infrastructure.game_detection import GameDetector
from kcd_mod_manager.infrastructure.order_files import MOD_ORDER_BACKUP_FILE, MOD_ORDER_FILE
from kcd_mod_manager.ui import dialogs
from kcd_mod_manager.ui.main_window import MainWindow
from kcd_mod_manager.ui.mod_list import MIME_TYPE
from kcd_mod_manager.ui.settings_dialog import SettingsDialog
from tests.conftest import make_mod, make_zip, manifest_xml

pytestmark = pytest.mark.ui


@pytest.fixture
def ctx(paths: AppPaths, game_root: Path) -> AppContext:
    context = build_context(paths, credentials=MemoryCredentialStore())
    context.session.detector = GameDetector(lambda: [], lambda: [], lambda _g: [])
    context.settings.set_game_path(GameType.KCD2, str(game_root))
    return context


@pytest.fixture
def no_dialogs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record message boxes instead of blocking on them."""
    shown: list[str] = []
    for name in ("info", "warn", "error"):
        monkeypatch.setattr(
            dialogs, name, lambda _p, message, _t=None, n=name: shown.append(f"{n}:{message}")
        )
    monkeypatch.setattr(
        dialogs, "confirm", lambda _p, message, _t=None: shown.append(f"confirm:{message}") or True
    )
    return shown


def wait_idle(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: not window.tasks.busy and window._scan_cancel is None, timeout=15000)


@pytest.fixture
def window(qtbot: QtBot, ctx: AppContext, game_root: Path, no_dialogs: list[str]) -> Iterator[MainWindow]:
    mods = game_root / "Mods"
    make_mod(mods, "alpha", paks={"data/a.pak": {"Libs/Shared.xml": b"1"}})
    make_mod(mods, "beta", paks={"data/b.pak": {"libs/shared.xml": b"2"}})
    make_mod(mods, "gamma")
    w = MainWindow(ctx, online=False)
    qtbot.addWidget(w)
    assert w.start()
    wait_idle(qtbot, w)
    yield w
    wait_idle(qtbot, w)


def order_lines(game_root: Path, name: str = MOD_ORDER_FILE) -> list[str]:
    return (game_root / "Mods" / name).read_text(encoding="utf-8").splitlines()


def test_startup_loads_mods_profile_and_conflicts(window: MainWindow, game_root: Path) -> None:
    assert [m.id for m in window.model.mods] == ["alpha", "beta", "gamma"]
    assert window.session.selected_profile == "Default"
    assert window.profile_combo.currentText() == "Default"
    assert window.game_label.text() == "Kingdom Come: Deliverance II"
    assert window.enabled_label.text().endswith("/3")
    assert len(window.session.conflicts) == 1
    assert window.conflict_badge.text() == "1"
    assert window.conflict_badge.isVisibleTo(window)
    assert window.page_subtitle.text() == tr("ModsPageSubtitle", 3, 3)
    assert not window.scan_row.isVisibleTo(window)
    assert not window.category_row.isVisibleTo(window)
    window.list_view.viewport().grab()  # exercises the delegate painting


def test_conflicts_button_only_shown_with_conflicts(window: MainWindow) -> None:
    window.session.conflicts = []
    window.refresh_view()
    assert not window.conflict_badge.isVisibleTo(window)
    assert window.conflicts_button.isVisibleTo(window)
    window.session.create_category("Gameplay")
    window.refresh_view()
    assert window.category_row.isVisibleTo(window)


def test_toggle_and_enable_all_persist_order_file(window: MainWindow, game_root: Path) -> None:
    beta = window.model.mods[1]
    was = beta.is_enabled
    window.toggle_mod(beta)
    assert beta.is_enabled is not was
    window.set_all_enabled(False)
    assert order_lines(game_root) == ["# alpha", "# beta", "# gamma"]
    window.set_all_enabled(True)
    assert order_lines(game_root) == ["alpha", "beta", "gamma"]
    assert window.enabled_label.text().endswith("3/3")


def test_drag_and_drop_reorders_and_saves(qtbot: QtBot, window: MainWindow, game_root: Path) -> None:
    data = QMimeData()
    data.setData(MIME_TYPE, b"gamma")
    assert window.model.dropMimeData(data, window.model.supportedDropActions(), 0, 0, QModelIndex()) is False
    qtbot.waitUntil(lambda: window.model.mods[0].id == "gamma")
    assert [m.id for m in window.session.mods] == ["gamma", "alpha", "beta"]
    assert [line.lstrip("# ") for line in order_lines(game_root)] == ["gamma", "alpha", "beta"]


def test_search_disables_reordering_and_sort(window: MainWindow, no_dialogs: list[str]) -> None:
    window.search_edit.setText("bet")
    assert [m.id for m in window.model.mods] == ["beta"]
    assert not window.reorder_allowed
    assert not window.model.reorder_allowed
    assert not window.sort_button.isEnabled()
    window.move_mod(window.model.mods[0], 0)
    assert any("load order" in s for s in no_dialogs)
    window.search_edit.clear()
    window.cycle_sort()
    assert window.sort_mode.value == "Title"
    assert not window.reorder_allowed


def test_install_archive_and_delete(
    qtbot: QtBot, window: MainWindow, game_root: Path, tmp_path: Path, no_dialogs: list[str]
) -> None:
    archive = make_zip(
        tmp_path / "Cool Mod-123-1-0-1700000000.zip",
        {"cool/mod.manifest": manifest_xml("Cool Mod", "1.0", "cool_mod"), "cool/data/cool.pak": b"PK"},
    )
    window.install_paths([archive])
    qtbot.waitUntil(lambda: any(m.id == "cool_mod" for m in window.session.mods), timeout=15000)
    wait_idle(qtbot, window)
    mod = next(m for m in window.session.mods if m.id == "cool_mod")
    assert mod.mod_number == 123
    assert window.session.mods[-1] is mod and not mod.is_enabled
    assert (game_root / "Mods" / "cool_mod" / "data" / "cool.pak").exists()

    window.settings.ask_on_delete = False
    window.delete_mod(mod)
    assert not (game_root / "Mods" / "cool_mod").exists()
    assert all(m.id != "cool_mod" for m in window.session.mods)


def test_workshop_mods_are_protected(window: MainWindow) -> None:
    mod = window.session.mods[0]
    mod.is_workshop_mod = True
    assert not window._button_enabled(mod, "delete")
    menu = window._mod_menu(mod)
    actions = {a.text(): a for a in menu.actions()}
    assert not actions["Visit website"].isEnabled()
    assert not actions["Delete Mod"].isEnabled()
    window.settings.allow_workshop_mod_actions = True
    actions = {a.text(): a for a in window._mod_menu(mod).actions()}
    assert actions["Visit website"].isEnabled()
    assert not actions["Delete Mod"].isEnabled()
    window.delete_mod(mod)
    assert mod.path is not None and mod.path.exists()


def test_profiles_create_and_switch(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dialogs, "ask_text", lambda *_a, **_k: "Vanilla")
    window.set_all_enabled(False)
    window.create_profile()
    assert window.session.selected_profile == "Vanilla"
    assert window.profile_combo.currentText() == "Vanilla"
    window.profile_combo.setCurrentIndex(window.profile_combo.findText("Default"))
    assert window.session.selected_profile == "Default"
    assert window.settings.last_used_profile(GameType.KCD2) == "Default"


def test_settings_dialog_applies_changes(qtbot: QtBot, window: MainWindow, game_root: Path) -> None:
    window.session.save_mod_order()
    dialog = SettingsDialog(
        window,
        window.settings,
        window.session.installs,
        hooks=window_hooks(window),
    )
    qtbot.addWidget(dialog)
    dialog.toggles["mod_order_enabled"].setChecked(False)
    assert not window.settings.mod_order_enabled
    assert not (game_root / "Mods" / MOD_ORDER_FILE).exists()
    assert (game_root / "Mods" / MOD_ORDER_BACKUP_FILE).exists()
    dialog.toggles["mod_order_enabled"].setChecked(True)
    assert (game_root / "Mods" / MOD_ORDER_FILE).exists()

    dialog.toggles["is_dark_mode"].setChecked(True)
    assert window.settings.is_dark_mode and window.delegate.dark
    dialog.launch_args.setText("-devmode")
    dialog.launch_args.editingFinished.emit()
    stored = window.ctx.session.settings_store.load()
    assert stored.is_dark_mode and stored.game_launch_args == "-devmode"


def test_settings_pages_navigate(qtbot: QtBot, window: MainWindow) -> None:
    dialog = SettingsDialog(window, window.settings, window.session.installs, hooks=window_hooks(window))
    qtbot.addWidget(dialog)
    assert len(dialog.page_titles()) == len(SettingsDialog.PAGES) == 6
    dialog.show_page("backups")
    assert dialog.pages.currentIndex() == 5
    dialog.nav.setCurrentRow(1)
    assert dialog.pages.currentIndex() == 1
    assert set(dialog.toggles) >= {"is_dark_mode", "mod_order_enabled", "create_backup"}
    dialog.grab()


class _WindowShowSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.shown: list[QWidget] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            self.shown.append(watched)
        return False


def test_opening_settings_shows_no_stray_windows(qtbot: QtBot, window: MainWindow) -> None:
    app = QApplication.instance()
    assert app is not None
    spy = _WindowShowSpy()
    app.installEventFilter(spy)
    try:
        dialog = SettingsDialog(window, window.settings, window.session.installs, hooks=window_hooks(window))
        qtbot.addWidget(dialog)
        dialog.show()
        for key, _icon, _title in SettingsDialog.PAGES:
            dialog.show_page(key)
    finally:
        app.removeEventFilter(spy)
    assert spy.shown == [dialog]


def test_mod_order_toggle_reverts_when_apply_fails(qtbot: QtBot, window: MainWindow) -> None:
    hooks = window_hooks(window)
    hooks.mod_order_changed = lambda _enabled: False
    dialog = SettingsDialog(window, window.settings, window.session.installs, hooks=hooks)
    qtbot.addWidget(dialog)
    dialog.toggles["mod_order_enabled"].setChecked(False)
    assert window.settings.mod_order_enabled
    assert dialog.toggles["mod_order_enabled"].isChecked()


def window_hooks(window: MainWindow):  # type: ignore[no-untyped-def]
    from kcd_mod_manager.ui.settings_dialog import SettingsHooks

    return SettingsHooks(
        save=window._save_settings,
        theme_changed=lambda _d: window.apply_theme(),
        mod_order_changed=window._apply_mod_order_setting,
        set_executable=window._set_executable,
        ignored_mods=lambda: [m for m in window.session.mods if m.ignored_in_conflict_detector],
        unignore=lambda m: window.session.set_ignored_in_conflicts(m, False),
        create_backup=window.create_backup,
        language_changed=lambda _l: None,
        view_changed=window.refresh_view,
    )


def test_context_menu_edits(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = window.session.mods[2]
    monkeypatch.setattr(dialogs, "ask_multiline", lambda *_a, **_k: "remember me")
    window.change_note(mod)
    assert mod.note == "remember me"
    monkeypatch.setattr(dialogs, "ask_text", lambda *_a, **_k: "9.9-custom")
    window.override_version(mod)
    assert mod.version == "9.9-custom"
    from kcd_mod_manager.domain.highlight import PRESETS

    window._set_highlight(mod, PRESETS["red"])
    window._toggle_separator(mod)
    assert mod.highlight == PRESETS["red"] and mod.has_separator_after
    window.list_view.viewport().grab()


def test_geometry_is_saved_on_close(window: MainWindow) -> None:
    window.close()
    assert window.ctx.session.settings_store.load().window_geometry


def test_compact_view_halves_the_rows_and_is_saved(window: MainWindow) -> None:
    window.resize(1100, 700)
    window.show()
    index = window.model.index(0)
    standard = window.list_view.visualRect(index).height()
    window.compact_button.click()
    assert window.settings.compact_mod_list
    assert window.ctx.session.settings_store.load().compact_mod_list
    compact = window.list_view.visualRect(index).height()
    assert compact < standard * 0.6
    mod = window.model.mod_at(0)
    assert mod is not None
    lay = window.delegate.layout(window.list_view.visualRect(index), mod)
    assert lay.version.right() < lay.category.left() < lay.buttons["up"].left()
    window.list_view.viewport().grab()
    window.compact_button.click()
    assert not window.settings.compact_mod_list
    assert window.list_view.visualRect(index).height() == standard


def test_drag_auto_scroll_speeds_up_towards_the_edges(window: MainWindow) -> None:
    window.resize(1100, 700)
    window.show()
    view = window.list_view
    height = view.viewport().height()
    assert height > 4 * view.EDGE
    assert not view.hasAutoScroll()
    assert view.edge_step(height // 2) == 0
    near_top, at_top, above = view.edge_step(view.EDGE - 5), view.edge_step(0), view.edge_step(-200)
    assert 0 > near_top > at_top == above == -view.MAX_STEP
    assert view.edge_step(height) == view.MAX_STEP
    assert 0 < view.edge_step(height - view.EDGE + 5) < view.MAX_STEP


def test_endorse_prompt_without_login_opens_the_mod_page_once(
    window: MainWindow, no_dialogs: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kcd_mod_manager.ui import main_window

    opened: list[str] = []
    monkeypatch.setattr(main_window, "open_url", opened.append)
    window.settings.launch_count = 50
    window.settings.first_launch_date = "2020-01-01"
    window.maybe_ask_for_endorsement()
    assert no_dialogs == [f"confirm:{tr('EndorsePromptBrowser')}"]
    assert opened == ["https://www.nexusmods.com/kingdomcomedeliverance2/mods/187"]
    assert window.ctx.session.settings_store.load().endorse_prompt_done
    window.maybe_ask_for_endorsement()
    assert len(no_dialogs) == 1


def test_start_counts_launches(window: MainWindow) -> None:
    saved = window.ctx.session.settings_store.load()
    assert saved.launch_count == 1 and saved.first_launch_date


def test_empty_conflict_dialog_does_not_crash(window: MainWindow) -> None:
    from kcd_mod_manager.ui.dialogs import ConflictDialog

    dialog = ConflictDialog(window, [], {}, set())
    assert dialog.summary_label.text() == tr("ConflictCheckerEmpty")
    dialog.close()


def test_conflict_button_disabled_without_conflicts(window: MainWindow) -> None:
    assert window.conflicts_button.isEnabled()
    window.session.conflicts = []
    window.refresh_view()
    assert not window.conflicts_button.isEnabled()
    assert window.conflicts_button.toolTip() == tr("ConflictCheckerEmpty")


def test_conflict_dialog_can_disable_a_mod(window: MainWindow) -> None:
    from kcd_mod_manager.ui.dialogs import ConflictActions, ConflictDialog

    dialog = ConflictDialog(
        window,
        list(window.session.conflicts),
        {m.id: m.name for m in window.session.mods},
        set(),
        actions=ConflictActions(window._conflict_action),
        mods=list(window.session.mods),
    )
    group = dialog.tree.topLevelItem(0)
    assert group is not None and group.childCount() == 2
    winner = group.child(1)
    loser = group.child(0)
    assert winner is not None and loser is not None
    assert tr("ConflictWinner") in winner.text(1)
    dialog.tree.setCurrentItem(loser)
    assert dialog.disable_button.isEnabled()
    dialog.disable_button.click()
    assert not window.session.mods[0].is_enabled
    assert dialog.tree.topLevelItemCount() == 0
    dialog.close()


def test_start_button_reflects_a_running_game(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    from kcd_mod_manager.ui import main_window

    monkeypatch.setattr(main_window, "is_game_running", lambda _install: True)
    window._refresh_game_running()
    assert window._game_running
    assert window.start_button.isEnabled()
    assert window.start_button.text() == tr("ButtonStopGame")


def test_conflict_dialog_filter_and_disable_losers(window: MainWindow) -> None:
    from kcd_mod_manager.ui.dialogs import ConflictActions, ConflictDialog

    dialog = ConflictDialog(
        window,
        list(window.session.conflicts),
        {m.id: m.name for m in window.session.mods},
        set(),
        actions=ConflictActions(window._conflict_action),
        mods=list(window.session.mods),
    )
    group = dialog.tree.topLevelItem(0)
    assert group is not None
    dialog.filter_edit.setText("does-not-exist")
    assert group.isHidden()
    dialog.filter_edit.setText("")
    assert not group.isHidden()
    dialog.tree.setCurrentItem(group)
    assert dialog.losers_button.isEnabled()
    dialog.losers_button.click()
    assert not window.session.mods[0].is_enabled
    assert dialog.tree.topLevelItemCount() == 0
    dialog.close()


def test_game_running_locks_mod_actions(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    from kcd_mod_manager.ui import main_window

    monkeypatch.setattr(main_window, "is_game_running", lambda _install: True)
    window._refresh_game_running()
    assert not window.add_button.isEnabled()
    assert not window.enable_all_button.isEnabled()
    assert window.start_button.text() == tr("ButtonStopGame")
    mod = window.session.mods[0]
    was = mod.is_enabled
    window.toggle_mod(mod)
    assert mod.is_enabled is was
    assert window.status_label.text() == tr("ModActionsLockedWhileRunning")


def test_multi_select_bulk_actions(window: MainWindow) -> None:
    from PySide6.QtCore import QItemSelectionModel

    selection = window.list_view.selectionModel()
    for row in (0, 1):
        selection.select(window.model.index(row), QItemSelectionModel.SelectionFlag.Select)
    mods = window.selected_mods()
    assert [m.id for m in mods] == ["alpha", "beta"]
    window.set_selected_enabled(mods, False)
    assert not any(m.is_enabled for m in mods)
    category = window.session.create_category("Bulk")
    window.set_selected_category(mods, category.id)
    assert all(m.category_id == category.id for m in mods)
    menu = window._mod_menu(mods[0])
    assert any(str(len(mods)) in action.text() for action in menu.actions())


def test_manual_app_update_check_reports_up_to_date(window: MainWindow, no_dialogs: list[str]) -> None:
    window.check_app_update()
    assert no_dialogs == [f"info:{tr('UpdateCheckNoUpdate', __version__)}"]

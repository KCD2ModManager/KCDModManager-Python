"""Main window: mod list, profiles, categories, conflicts, Nexus account and game launch."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager import __version__
from kcd_mod_manager.application.library import BACKUP_ROOT_NAME, InstallResult, InstallStatus
from kcd_mod_manager.application.session import SessionError, UpdateCheckSummary
from kcd_mod_manager.bootstrap import AppContext
from kcd_mod_manager.domain.highlight import PRESETS
from kcd_mod_manager.domain.library_view import UNCATEGORIZED, SortMode, next_sort_mode, visible_mods
from kcd_mod_manager.domain.models import ConflictGroup, GameInstall, GameType, Mod
from kcd_mod_manager.domain.naming import extract_mod_number
from kcd_mod_manager.i18n import tr
from kcd_mod_manager.infrastructure.app_updates import AppUpdate, check_for_app_update
from kcd_mod_manager.infrastructure.archives import is_supported_archive, rar_support_available
from kcd_mod_manager.infrastructure.conflict_scanner import ScanCancelled
from kcd_mod_manager.infrastructure.nexus import (
    NexusError,
    NexusPremiumRequired,
    NexusRateLimited,
    mod_files_page_url,
    mod_page_url,
)
from kcd_mod_manager.infrastructure.nexus_sso import SsoCancelled
from kcd_mod_manager.infrastructure.platform_actions import LaunchError, launch_game, open_path, open_url
from kcd_mod_manager.resources import resource_path
from kcd_mod_manager.ui import dialogs, icons
from kcd_mod_manager.ui.dialogs import (
    AssignCategoryDialog,
    BusyDialog,
    CategoryManagerDialog,
    ConflictDialog,
    GameSelectionDialog,
)
from kcd_mod_manager.ui.icons import swatch
from kcd_mod_manager.ui.mod_list import ModDelegate, ModListModel
from kcd_mod_manager.ui.settings_dialog import SettingsDialog, SettingsHooks
from kcd_mod_manager.ui.tasks import GuiInvoker, TaskRunner
from kcd_mod_manager.ui.theme import apply_theme, current_palette, palette_for
from kcd_mod_manager.ui.widgets import (
    Card,
    LoadingOverlay,
    Pill,
    RoundedMenu,
    SearchBox,
    ThemedIcon,
    label,
    primary_button,
    refresh_theme,
    secondary_button,
    vline,
)

log = logging.getLogger(__name__)

SORT_LABELS = {
    SortMode.LOAD_ORDER: "ButtonSortLoadOrder",
    SortMode.TITLE: "ButtonSortTitle",
    SortMode.CATEGORY: "ButtonSortCategory",
}
ARCHIVE_FILTER = "*.zip *.7z *.rar"


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, *, online: bool = True) -> None:
        super().__init__()
        self.ctx = ctx
        self.session = ctx.session
        self.settings = ctx.settings
        self.online = online
        self.tasks = TaskRunner(self)
        self.invoker = GuiInvoker(self)
        ctx.order_files.set_retry_prompt(self._retry_prompt)
        self.restart_requested = False

        self.search = ""
        self.category_filter: str | None = None
        self.sort_mode = SortMode.LOAD_ORDER
        self._updating = False
        self._scan_cancel: threading.Event | None = None
        self._install_queue: list[tuple[Path, int, bool]] = []

        self.setWindowTitle(f"KCD Mod Manager {__version__}")
        icon = resource_path("images", "logo.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setAcceptDrops(True)
        self.resize(max(self.settings.window_width, 1000), max(self.settings.window_height, 640))
        self._build_ui()
        self.tasks.busy_changed.connect(self._set_busy)
        self._restore_geometry()
        self.apply_theme()

    # ================================================================== construction
    def _build_ui(self) -> None:
        menu = self.menuBar()
        self.settings_action = QAction(tr("MenuSettings"), self)
        self.settings_action.triggered.connect(self.open_settings)
        menu.addAction(self.settings_action)
        tools = RoundedMenu(tr("MenuTools"), menu)
        tools.addAction(tr("MenuCheckUpdates"), self.check_all_updates)
        tools.addAction(tr("ConflictsButtonText"), self.show_conflicts)
        tools.addSeparator()
        tools.addAction(tr("MenuOpenModsFolder"), self._open_mods_folder)
        tools.addAction(tr("MenuOpenDataFolder"), lambda: self._open(self.ctx.paths.data_dir))
        tools.addAction(tr("MenuOpenLogFolder"), lambda: self._open(self.ctx.paths.logs_dir))
        menu.addMenu(tools)
        self.login_action = QAction(tr("MenuLogin"), self)
        self.login_action.triggered.connect(self.login)
        menu.addAction(self.login_action)
        self.logout_action = QAction(tr("MenuLogout"), self)
        self.logout_action.triggered.connect(self.logout)
        menu.addAction(self.logout_action)

        corner = QWidget(menu)
        self._account_widget = corner
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 2, 8, 2)
        account = QFrame()
        account.setObjectName("accountBox")
        account_layout = QHBoxLayout(account)
        account_layout.setContentsMargins(8, 3, 8, 3)
        account_layout.setSpacing(6)
        self.account_icon = QLabel()
        account_layout.addWidget(self.account_icon)
        self.account_label = QLabel()
        self.account_label.setObjectName("username")
        account_layout.addWidget(self.account_label)
        self.premium_badge = Pill(tr("PremiumBadge"), "premium")
        account_layout.addWidget(self.premium_badge)
        corner_layout.addWidget(account)
        menu.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 6)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(label(tr("ProfilesText"), "fieldLabel"))
        top.addSpacing(4)
        self.profile_combo = QComboBox()
        self.profile_combo.setFixedSize(150, 28)
        self.profile_combo.currentIndexChanged.connect(self._profile_selected)
        top.addWidget(self.profile_combo)
        top.addSpacing(2)
        self.profile_buttons: list[QPushButton] = []
        for key, slot in (
            ("CreateProfileText", self.create_profile),
            ("DuplicateProfileText", self.duplicate_profile),
            ("DeleteProfileText", self.delete_profile),
            ("SaveProfileText", self.save_profile),
            ("ManageCategoriesText", self.manage_categories),
        ):
            button = secondary_button(tr(key))
            button.clicked.connect(slot)
            top.addWidget(button)
            self.profile_buttons.append(button)
        top.addSpacing(14)
        top.addWidget(vline())
        top.addSpacing(14)
        top.addWidget(label(tr("GameText"), "fieldLabel"))
        top.addSpacing(4)
        self.game_label = label("-", "gameName")
        top.addWidget(self.game_label)
        top.addSpacing(8)
        self.switch_game_button = secondary_button(tr("SwitchGameText"))
        self.switch_game_button.clicked.connect(self.switch_game)
        top.addWidget(self.switch_game_button)
        top.addStretch(1)

        self.conflicts_box = QWidget()
        conflicts_layout = QHBoxLayout(self.conflicts_box)
        conflicts_layout.setContentsMargins(0, 0, 0, 0)
        conflicts_layout.setSpacing(6)
        self.conflicts_button = secondary_button(tr("ConflictsButtonText"))
        ThemedIcon(self.conflicts_button, "warning_filled", "warning", 14)
        self.conflicts_button.clicked.connect(self.show_conflicts)
        conflicts_layout.addWidget(self.conflicts_button)
        self.conflict_badge = Pill("0", "warning")
        self.conflict_badge.clicked.connect(self.show_conflicts)
        conflicts_layout.addWidget(self.conflict_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.conflicts_box.hide()
        top.addWidget(self.conflicts_box)
        self.scan_progress = QProgressBar()
        self.scan_progress.setFixedSize(120, 6)
        self.scan_progress.hide()
        top.addSpacing(6)
        top.addWidget(self.scan_progress, 0, Qt.AlignmentFlag.AlignVCenter)
        self.scan_cancel_button = secondary_button(tr("CancelButton"))
        self.scan_cancel_button.clicked.connect(self.cancel_scan)
        self.scan_cancel_button.hide()
        top.addWidget(self.scan_cancel_button)
        root.addLayout(top)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.enable_all_button = secondary_button(tr("EnableAllModsText"), "checkmark")
        self.enable_all_button.clicked.connect(lambda: self.set_all_enabled(True))
        self.disable_all_button = secondary_button(tr("DisableAllModsText"), "dismiss")
        self.disable_all_button.clicked.connect(lambda: self.set_all_enabled(False))
        self.update_manifests_button = secondary_button(tr("UpdateAllManifestsText"), "update")
        self.update_manifests_button.clicked.connect(self.update_all_manifests)
        bar.addWidget(self.enable_all_button)
        bar.addWidget(self.disable_all_button)
        bar.addStretch(1)
        bar.addWidget(self.update_manifests_button)
        root.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.list_card = Card()
        list_layout = QVBoxLayout(self.list_card)
        list_layout.setContentsMargins(1, 1, 1, 1)
        self.model = ModListModel(self)
        self.model.move_requested.connect(self._drop_move)
        self.list_view = QListView()
        self.list_view.setObjectName("modList")
        self.list_view.setModel(self.model)
        self.list_view.setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_view.setDragEnabled(True)
        self.list_view.setAcceptDrops(True)
        self.list_view.setDropIndicatorShown(True)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.verticalScrollBar().setSingleStep(16)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._context_menu_at)
        self.delegate = ModDelegate(
            self.list_view, palette_for(self.settings.is_dark_mode), self.settings.is_dark_mode
        )
        self.delegate.button_enabled = self._button_enabled
        self.delegate.toggled.connect(self.toggle_mod)
        self.delegate.action.connect(self._row_action)
        self.list_view.setItemDelegate(self.delegate)
        list_layout.addWidget(self.list_view)
        self.loading_overlay = LoadingOverlay(self.list_card, tr("LoadingModsText"))
        body.addWidget(self.list_card, 2)

        side = Card()
        side.setMinimumWidth(250)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(10, 10, 10, 10)
        side_layout.setSpacing(10)
        self.enabled_label = Pill("", "success")
        side_layout.addWidget(self.enabled_label, 0, Qt.AlignmentFlag.AlignLeft)
        self.search_edit = SearchBox(tr("SearchPlaceholder"), tr("ToolTipClearSearch"))
        self.search_edit.textChanged.connect(self._search_changed)
        side_layout.addWidget(self.search_edit)
        self.category_row = QWidget()
        category_layout = QVBoxLayout(self.category_row)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.setSpacing(4)
        category_layout.addWidget(label(tr("FilterCategoryText"), "secondary"))
        self.category_combo = QComboBox()
        self.category_combo.setMinimumHeight(28)
        self.category_combo.currentIndexChanged.connect(self._category_filter_changed)
        category_layout.addWidget(self.category_combo)
        side_layout.addWidget(self.category_row)
        side_layout.addStretch(1)
        self.start_button = primary_button(tr("ButtonStartGame"), "play_filled")
        self.start_button.clicked.connect(self.start_game)
        self.add_button = primary_button(tr("ButtonAddMod"), "add")
        self._add_menu = RoundedMenu("", self.add_button)
        self._add_menu.addAction(tr("ButtonAddMod") + "...", self.add_mod)
        self._add_menu.addAction(tr("AddModFolder") + "...", self.add_mod_folder)
        self.add_button.clicked.connect(self._show_add_menu)
        self.sort_button = primary_button("", "sort")
        self.sort_button.clicked.connect(self.cycle_sort)
        self.reload_button = primary_button(tr("ButtonReloadMods"), "reload")
        self.reload_button.clicked.connect(self.reload)
        for button in (self.start_button, self.add_button, self.sort_button, self.reload_button):
            side_layout.addWidget(button)
        body.addWidget(side, 1)
        root.addLayout(body, 1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 0, 2, 0)
        status_row.addStretch(1)
        self.status_progress = QProgressBar()
        self.status_progress.setFixedSize(160, 6)
        self.status_progress.hide()
        status_row.addWidget(self.status_progress, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addSpacing(8)
        self.status_label = label(tr("StatusReady"), "statusText")
        status_row.addWidget(self.status_label)
        root.addLayout(status_row)
        self.setCentralWidget(central)

        self._busy_widgets: list[QWidget] = [
            self.profile_combo,
            *self.profile_buttons,
            self.switch_game_button,
            self.enable_all_button,
            self.disable_all_button,
            self.update_manifests_button,
            self.list_view,
            self.start_button,
            self.add_button,
            self.sort_button,
            self.reload_button,
            self.settings_action,  # type: ignore[list-item]
        ]

    def _show_add_menu(self) -> None:
        p = current_palette()
        archive, folder = self._add_menu.actions()
        archive.setIcon(icons.icon("archive", p.text_secondary))
        folder.setIcon(icons.icon("folder_add", p.text_secondary))
        self._add_menu.setMinimumWidth(self.add_button.width())
        self._add_menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))

    def _show_loading(self, visible: bool) -> None:
        if visible:
            self.loading_overlay.show_overlay(tr("LoadingModsText"))
        else:
            self.loading_overlay.hide()

    # ================================================================== theme & geometry
    def apply_theme(self) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            palette = apply_theme(app, self.settings.is_dark_mode)
            self.delegate.set_theme(palette, self.settings.is_dark_mode)
            refresh_theme(self)
            self.account_icon.setPixmap(icons.pixmap("person", palette.text_secondary, 16))
            self.list_view.viewport().update()

    def _restore_geometry(self) -> None:
        if self.settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(self.settings.window_geometry.encode("ascii")))
        elif self.settings.window_state == "Maximized":
            self.setWindowState(Qt.WindowState.WindowMaximized)

    def _save_geometry(self) -> None:
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        self.settings.window_state = "Maximized" if self.isMaximized() else "Normal"
        if not self.isMaximized():
            self.settings.window_width, self.settings.window_height = self.width(), self.height()
            self.settings.window_left, self.settings.window_top = self.x(), self.y()
        self._save_settings()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scan_cancel is not None:
            self._scan_cancel.set()
        self._save_geometry()
        self.tasks.wait(15000)
        super().closeEvent(event)

    # ================================================================== helpers
    def status(self, text: str) -> None:
        self.status_label.setText(text)
        log.info("Status: %s", text)

    def _save_settings(self) -> None:
        try:
            self.session.save_settings()
        except OSError as exc:
            dialogs.error(self, f"settings.json: {exc}")

    def _set_busy(self, busy: bool) -> None:
        for widget in self._busy_widgets:
            widget.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        else:
            QApplication.restoreOverrideCursor()
            self.refresh_view()

    def _retry_prompt(self, source: Path, target: Path, exc: OSError) -> bool:
        return bool(
            self.invoker.call(
                lambda: dialogs.confirm(self, tr("FileMoveFailedRetryPrompt", source, target, exc))
            )
        )

    def _guard(self, fn: Callable[[], object], message_key: str | None = None) -> bool:
        """Run a quick session call on the GUI thread, reporting user-facing failures."""
        try:
            fn()
        except SessionError as exc:
            dialogs.error(self, tr(message_key, exc) if message_key else str(exc))
            return False
        except OSError as exc:
            log.exception("Operation failed")
            dialogs.error(self, tr(message_key, exc) if message_key else str(exc))
            return False
        return True

    def _open(self, path: Path) -> None:
        try:
            open_path(path)
        except OSError as exc:
            dialogs.error(self, str(exc))

    def _open_url(self, url: str) -> None:
        try:
            open_url(url)
        except (OSError, ValueError) as exc:
            dialogs.error(self, str(exc))

    def _open_mods_folder(self) -> None:
        if self.session.install is not None:
            self._open(self.session.mods_dir)

    def _workshop_allowed(self, mod: Mod) -> bool:
        return not mod.is_workshop_mod or self.settings.allow_workshop_mod_actions

    @property
    def reorder_allowed(self) -> bool:
        return self.sort_mode is SortMode.LOAD_ORDER and not self.search.strip()

    def _button_enabled(self, mod: Mod, name: str) -> bool:
        if name in ("up", "down"):
            return self.reorder_allowed
        if name == "delete":
            return not mod.is_workshop_mod
        if name == "update":
            return self._workshop_allowed(mod)
        return True

    def visible(self) -> list[Mod]:
        return visible_mods(
            self.session.mods, self.search, self.category_filter, self.sort_mode, self.session.categories
        )

    # ================================================================== view refresh
    def refresh_view(self) -> None:
        self._updating = True
        try:
            selected = self._selected_mod()
            self.model.reorder_allowed = self.reorder_allowed
            self.model.set_mods(self.visible())
            if selected is not None:
                row = self.model.row_of(selected)
                if row >= 0:
                    self.list_view.setCurrentIndex(self.model.index(row))
            enabled = sum(1 for m in self.session.mods if m.is_enabled)
            self.enabled_label.setText(tr("ModsEnabled", f"{enabled}/{len(self.session.mods)}"))
            searching = bool(self.search.strip())
            self.sort_button.setText(
                tr("ButtonSortDisabled") if searching else tr(SORT_LABELS[self.sort_mode])
            )
            self.sort_button.setEnabled(not searching and not self.tasks.busy)
            self._refresh_categories_combo()
            self._refresh_profiles_combo()
            game = self.session.game
            self.game_label.setText(tr(game.display_key) if game else "-")
            self._refresh_account()
            count = len(self.session.conflicts)
            self.conflict_badge.setText(str(count))
            self.conflicts_box.setVisible(count > 0)
            self.category_row.setVisible(bool(self.session.categories))
        finally:
            self._updating = False

    def _refresh_categories_combo(self) -> None:
        combo = self.category_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("FilterCategoryAll"), None)
        combo.addItem(tr("FilterCategoryUncategorized"), UNCATEGORIZED)
        for category in self.session.categories:
            combo.addItem(category.name, category.id)
        index = combo.findData(self.category_filter) if self.category_filter is not None else 0
        if index < 0:
            self.category_filter = None
            index = 0
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _refresh_profiles_combo(self) -> None:
        combo = self.profile_combo
        combo.blockSignals(True)
        combo.clear()
        for profile in self.session.profiles:
            combo.addItem(profile.profile_name)
        if self.session.selected_profile:
            combo.setCurrentIndex(max(0, combo.findText(self.session.selected_profile)))
        else:
            combo.setCurrentIndex(-1)
        combo.blockSignals(False)

    def _refresh_account(self) -> None:
        nexus = self.ctx.nexus
        logged_in = nexus.is_logged_in
        self.login_action.setVisible(not logged_in)
        self.logout_action.setVisible(logged_in)
        self.account_label.setText((nexus.username or "?") if logged_in else tr("InfoNotLoggedIn"))
        self.account_label.setToolTip(tr("InfoLoggedInAs", nexus.username or "?") if logged_in else "")
        self.premium_badge.setVisible(logged_in and nexus.is_premium)

    def _selected_mod(self) -> Mod | None:
        index = self.list_view.currentIndex()
        return self.model.mod_at(index.row()) if index.isValid() else None

    # ================================================================== startup & game
    def start(self) -> bool:
        """Detect games, ask which one to manage and load it. False means "exit the app"."""
        self.status(tr("LoadingModsText"))
        installs = self.session.detect_games()
        found = [g for g, i in installs.items() if i is not None]
        game = found[0] if len(found) == 1 else self.choose_game()
        if game is None:
            dialogs.info(self, tr("NoGameSelectedMessage"))
            return False
        self.load_game(game)
        if self.ctx.imported_legacy:
            QTimer.singleShot(0, lambda: self.status(tr("LegacyImportDone")))
        if self.ctx.settings_recovered:
            QTimer.singleShot(0, lambda: dialogs.warn(self, tr("SettingsRecovered")))
        if not self.ctx.credentials.is_secure and self.ctx.nexus.is_logged_in:
            log.warning("Nexus API key is stored in a file because no keyring is available")
        if self.online:
            self._startup_online_checks()
        return True

    def choose_game(self) -> GameType | None:
        dialog = GameSelectionDialog(self, dict(self.session.installs), self.session.set_manual_install)
        dialog.exec()
        return dialog.selected

    def switch_game(self) -> None:
        game = self.choose_game()
        if game is not None:
            self.load_game(game)

    def load_game(self, game: GameType) -> None:
        if not self._guard(lambda: self.session.select_game(game)):
            return
        self.session.conflicts = []
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.search, self.category_filter, self.sort_mode = "", None, SortMode.LOAD_ORDER
        self.refresh_view()
        self.status(tr("LoadingModsText"))
        self._show_loading(True)

        def work() -> None:
            self.session.startup_maintenance()
            self.session.reload()
            self.session.load_profiles()
            name = self.session.initial_profile_name()
            if name:
                self.session.apply_profile(name)

        def done(_: object) -> None:
            self._show_loading(False)
            self.refresh_view()
            self.status(tr("StatusReady"))
            self.scan_conflicts()

        def failed(exc: BaseException) -> None:
            self._show_loading(False)
            self._task_failed(exc, "ErrorFailedToLoadMods")

        self.tasks.run(work, done, failed)

    def _task_failed(self, exc: BaseException, key: str | None = None) -> None:
        log.error("Task failed: %s", exc, exc_info=exc)
        prefix = tr(key) if key else tr("DialogTitleError")
        self.status(prefix)
        dialogs.error(self, f"{prefix}\n\n{exc}")

    def reload(self) -> None:
        self.status(tr("LoadingModsText"))
        self._show_loading(True)

        def work() -> None:
            self.session.reload()

        def done(_: object) -> None:
            self._show_loading(False)
            self.status(tr("StatusReady"))

        def failed(exc: BaseException) -> None:
            self._show_loading(False)
            self._task_failed(exc, "ErrorFailedToLoadMods")

        self.tasks.run(work, done, failed)

    # ================================================================== profiles
    def _profile_selected(self, index: int) -> None:
        if self._updating or index < 0:
            return
        name = self.profile_combo.itemText(index)
        if name and name != self.session.selected_profile:
            self._guard(lambda: self.session.apply_profile(name), "ErrorLoadingProfile")
            self.refresh_view()

    def create_profile(self) -> None:
        name = dialogs.ask_text(self, tr("CreateProfileText"), tr("EnterProfileName"))
        if name and self._guard(lambda: self.session.create_profile(name), "ErrorCreatingProfile"):
            self.refresh_view()

    def duplicate_profile(self) -> None:
        source = self.session.selected_profile
        if not source:
            return
        name = dialogs.ask_text(
            self, tr("DuplicateProfileTitle"), tr("EnterDuplicateProfileName"), f"{source} (2)"
        )
        if name and self._guard(
            lambda: self.session.duplicate_profile(source, name), "ErrorDuplicatingProfile"
        ):
            self.refresh_view()

    def delete_profile(self) -> None:
        name = self.session.selected_profile
        if not name or not dialogs.confirm(self, tr("DeleteProfileConfirm", name)):
            return
        result: list[str | None] = []
        if not self._guard(lambda: result.append(self.session.delete_profile(name)), "ErrorDeletingProfile"):
            return
        next_profile = result[0] if result else None
        if next_profile is None and not self.session.profiles:
            self.session.load_profiles()
            next_profile = self.session.initial_profile_name()
        if next_profile:
            self._guard(lambda: self.session.apply_profile(next_profile), "ErrorLoadingProfile")
        self.refresh_view()

    def save_profile(self) -> None:
        if self._guard(self.session.save_profile, "ErrorSavingProfile"):
            self.status(tr("InfoModOrderSaved", self.session.selected_profile or ""))

    # ================================================================== categories
    def manage_categories(self) -> None:
        usage: dict[str, int] = {}
        for mod in self.session.mods:
            if mod.category_id:
                usage[mod.category_id] = usage.get(mod.category_id, 0) + 1
        dialog = CategoryManagerDialog(self, self.session.categories, usage)
        if dialog.exec() != CategoryManagerDialog.DialogCode.Accepted:
            return
        self._guard(lambda: self.session.save_categories(dialog.result_categories, dialog.reassign))
        self.refresh_view()

    def assign_category(self, mod: Mod) -> None:
        dialog = AssignCategoryDialog(
            self, self.session.categories, mod.category_id, self.session.create_category
        )
        if dialog.exec() == AssignCategoryDialog.DialogCode.Accepted:
            self.set_category(mod, dialog.category_id())

    def set_category(self, mod: Mod, category_id: str | None) -> None:
        self._guard(lambda: self.session.set_category(mod, category_id))
        self.refresh_view()

    # ================================================================== list operations
    def _search_changed(self, text: str) -> None:
        self.search = text
        self.refresh_view()

    def _category_filter_changed(self, index: int) -> None:
        if self._updating:
            return
        data = self.category_combo.itemData(index)
        self.category_filter = None if data is None else str(data)
        self.refresh_view()

    def cycle_sort(self) -> None:
        if self.search.strip():
            self.status(tr("ErrorSortingDisabled"))
            return
        self.sort_mode = next_sort_mode(self.sort_mode, bool(self.session.categories))
        self.refresh_view()

    def toggle_mod(self, mod: Mod) -> None:
        self._guard(lambda: self.session.set_enabled(mod, not mod.is_enabled))
        self.refresh_view()

    def set_all_enabled(self, enabled: bool) -> None:
        self._guard(lambda: self.session.set_all_enabled(enabled))
        self.refresh_view()

    def move_mod(self, mod: Mod, target: int) -> None:
        if not self.reorder_allowed:
            dialogs.warn(self, tr("ErrorActionNotAllowed"))
            return
        visible = self.visible()
        self._guard(lambda: self.session.move(mod, visible, target))
        self.refresh_view()

    def _drop_move(self, mod_id: str, target: int) -> None:
        mod = next((m for m in self.model.mods if m.id == mod_id), None)
        if mod is not None:
            QTimer.singleShot(0, lambda: self.move_mod(mod, target))

    def delete_mod(self, mod: Mod) -> None:
        if mod.is_workshop_mod:
            return
        if self.settings.ask_on_delete:
            ok, dont_ask = dialogs.confirm_delete(self, mod.name)
            if not ok:
                return
            if dont_ask:
                self.settings.ask_on_delete = False
                self._save_settings()
        if self._guard(lambda: self.session.delete_mod(mod), "FailedToDeleteMod"):
            self.status(tr("StatusModDeleted", mod.name))
        self.refresh_view()

    def _row_action(self, name: str, mod: Mod, pos: QPoint) -> None:
        if name == "up":
            self.move_mod(mod, self.visible().index(mod) - 1)
        elif name == "down":
            self.move_mod(mod, self.visible().index(mod) + 1)
        elif name == "delete":
            self.delete_mod(mod)
        elif name == "folder":
            if mod.path is not None:
                self._open(mod.path)
            else:
                dialogs.error(self, tr("ErrorModFolderNotExists"))
        elif name == "more":
            self._mod_menu(mod).exec(pos)
        elif name == "update":
            self.update_mod(mod)

    def _context_menu_at(self, pos: QPoint) -> None:
        index = self.list_view.indexAt(pos)
        mod = self.model.mod_at(index.row()) if index.isValid() else None
        if mod is not None:
            self.list_view.setCurrentIndex(index)
            self._mod_menu(mod).exec(self.list_view.viewport().mapToGlobal(pos))

    def _mod_menu(self, mod: Mod) -> RoundedMenu:
        menu = RoundedMenu("", self)
        allowed = self._workshop_allowed(mod)
        local = not mod.is_workshop_mod

        def add(key: str, slot: Callable[[], None], enabled: bool = True) -> QAction:
            action = menu.addAction(tr(key))
            action.triggered.connect(slot)
            action.setEnabled(enabled)
            return action

        add("ContextMenuChangeModName", lambda: self.rename_mod(mod))
        add("ContextMenuChangeNote", lambda: self.change_note(mod))
        add("ContextMenuOverrideVersion", lambda: self.override_version(mod), allowed)
        add("ContextMenuChangeModNumber", lambda: self.change_mod_number(mod), allowed)
        menu.addSeparator()
        add("ContextMenuAssignCategory", lambda: self.assign_category(mod))
        category_menu = menu.add_submenu(tr("ContextMenuSetCategory"))
        category_menu.setEnabled(bool(self.session.categories))
        for category in self.session.categories:
            action = category_menu.addAction(category.name)
            action.setCheckable(True)
            action.setChecked(category.id == mod.category_id)
            action.triggered.connect(lambda _=False, c=category.id: self.set_category(mod, c))
        add("ContextMenuClearCategory", lambda: self.set_category(mod, None), mod.has_category)
        highlight_menu = menu.add_submenu(tr("ContextMenuSetHighlightColor"))
        dark = self.settings.is_dark_mode
        for preset_name, color in PRESETS.items():
            action = highlight_menu.addAction(
                swatch(color.for_theme(dark), current_palette().separator),
                tr(f"Highlight{preset_name.capitalize()}"),
            )
            action.triggered.connect(lambda _=False, c=color: self._set_highlight(mod, c))
        add("ContextMenuRemoveHighlight", lambda: self._set_highlight(mod, None), mod.highlight is not None)
        add("ContextMenuToggleSeparator", lambda: self._toggle_separator(mod), local)
        ignore = add("ContextMenuIgnoreConflicts", lambda: self._toggle_ignore(mod))
        ignore.setCheckable(True)
        ignore.setChecked(mod.ignored_in_conflict_detector)
        menu.addSeparator()
        checks = add("ContextMenuToggleUpdateCheck", lambda: self._toggle_update_checks(mod), allowed)
        checks.setCheckable(True)
        checks.setChecked(mod.update_checks_enabled)
        add("ContextMenuCheckForUpdate", lambda: self.check_mod_update(mod), allowed)
        add("ContextMenuEndorseMod", lambda: self.endorse(mod), allowed)
        add("ContextMenuVisitWebsite", lambda: self.visit_website(mod), allowed)
        menu.addSeparator()
        reorder = self.reorder_allowed
        add("ContextMenuMoveToTop", lambda: self.move_mod(mod, 0), reorder)
        add("ContextMenuMoveToBottom", lambda: self.move_mod(mod, len(self.visible()) - 1), reorder)
        add("ContextMenuMoveToPosition", lambda: self.move_to_position(mod), reorder)
        menu.addSeparator()
        add("UpdateManifestText", lambda: self.update_manifests([mod]), local)
        add("ToolTipOpenFolder", lambda: self._row_action("folder", mod, QPoint()), mod.path is not None)
        add("ToolTipDeleteMod", lambda: self.delete_mod(mod), local)
        return menu

    # ================================================================== per-mod edits
    def rename_mod(self, mod: Mod) -> None:
        name = dialogs.ask_text(self, tr("TitleChangeModName"), tr("EnterModName"), mod.name)
        if not name or not name.strip() or name.strip() == mod.name:
            return
        rename_id = (
            self.settings.enable_file_renaming
            and not mod.is_workshop_mod
            and dialogs.confirm(self, tr("RenameModIdPrompt"))
            and dialogs.confirm(self, tr("RenameModIdConfirmPrompt"))
        )
        action = (
            (lambda: self.session.rename_id(mod, name))
            if rename_id
            else (lambda: self.session.rename_display(mod, name))
        )
        if self._guard(action):
            self.status(tr("ModNameUpdated", mod.name))
        self.refresh_view()

    def change_note(self, mod: Mod) -> None:
        note = dialogs.ask_multiline(self, tr("TitleChangeModNote"), tr("PromptEnterNote"), mod.note)
        if note is not None:
            self._guard(lambda: self.session.set_note(mod, note))
            self.refresh_view()

    def override_version(self, mod: Mod) -> None:
        version = dialogs.ask_text(self, tr("SetModVersionTitle"), tr("EnterModVersion"), mod.version)
        if version is not None:
            self._guard(lambda: self.session.set_custom_version(mod, version))
            self.refresh_view()

    def change_mod_number(self, mod: Mod) -> None:
        number = dialogs.ask_int(
            self,
            tr("TitleChangeModNumber"),
            tr("PromptChangeModNumber"),
            max(mod.mod_number, 1),
            1,
            2**31 - 1,
        )
        if number is not None:
            self._guard(lambda: self.session.set_mod_number(mod, number))

    def move_to_position(self, mod: Mod) -> None:
        visible = self.visible()
        position = dialogs.ask_int(
            self,
            tr("MoveToPositionTitle"),
            tr("MoveToPositionPrompt"),
            visible.index(mod) + 1,
            1,
            len(visible),
        )
        if position is not None:
            self.move_mod(mod, position - 1)

    def _set_highlight(self, mod: Mod, color: object) -> None:
        self._guard(lambda: self.session.set_highlight(mod, color))  # type: ignore[arg-type]
        self.refresh_view()

    def _toggle_separator(self, mod: Mod) -> None:
        self._guard(lambda: self.session.toggle_separator(mod))
        self.refresh_view()

    def _toggle_ignore(self, mod: Mod) -> None:
        self._guard(lambda: self.session.set_ignored_in_conflicts(mod, not mod.ignored_in_conflict_detector))

    def _toggle_update_checks(self, mod: Mod) -> None:
        self._guard(lambda: self.session.toggle_update_checks(mod))

    def update_all_manifests(self) -> None:
        install = self.session.install
        if install is None or not install.game_version:
            dialogs.error(self, tr("CouldNotDetectGameVersion"))
            return
        if dialogs.confirm(self, tr("UpdateAllManifestsMessage", install.game_version)):
            self.update_manifests(list(self.session.mods))

    def update_manifests(self, mods: list[Mod]) -> None:
        result: list[int] = []
        if self._guard(lambda: result.append(self.session.update_manifest_game_version(mods))):
            self.status(tr("UpdatedManifestsCount", result[0]))
        self.refresh_view()

    # ================================================================== install
    def add_mod(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("ButtonAddMod"), "", f"{tr('SelectArchivesFilter')} ({ARCHIVE_FILTER})"
        )
        self.install_paths([Path(f) for f in files])

    def add_mod_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("AddModFolder"))
        if folder:
            self.install_paths([Path(folder)])

    def install_paths(self, paths: list[Path]) -> None:
        if self.session.install is None:
            return
        for path in paths:
            if path.is_dir():
                self._install_queue.append((path, -1, False))
            elif is_supported_archive(path):
                if path.suffix.lower() == ".rar" and not rar_support_available():
                    dialogs.error(self, tr("RarUnsupported"))
                    continue
                number = extract_mod_number(path.stem)
                if number == -1:
                    asked = dialogs.ask_int(
                        self, tr("TitleModNumber"), tr("PromptEnterModNumber"), 1, 1, 2**31 - 1
                    )
                    if asked is None:
                        continue
                    number = asked
                self._install_queue.append((path, number, False))
            else:
                dialogs.error(self, f"{tr('StatusModInstallFailed')}: {path.name}")
        if self._install_queue and not self.tasks.busy:
            self._install_next()

    def _install_next(self) -> None:
        if not self._install_queue:
            return
        path, number, generate = self._install_queue.pop(0)
        self.status(tr("StatusInstallingModFromFolder" if path.is_dir() else "StatusInstallingMod"))

        def work() -> InstallResult:
            if path.is_dir():
                return self.session.install_folder(path)
            return self.session.install_archive(path, number, generate)

        def done(result: InstallResult) -> None:
            if result.status is InstallStatus.INVALID_MANIFEST and not generate and not path.is_dir():
                if dialogs.confirm(self, tr("InvalidManifestPrompt"), tr("InvalidManifestTitle")):
                    self._install_queue.insert(0, (path, number, True))
            elif result.status is InstallStatus.INSTALLED and result.mod is not None:
                self.status(tr("StatusModAdded", result.mod.name, result.mod.version))
            else:
                self.status(tr("StatusModInstallFailed"))
                dialogs.error(
                    self,
                    f"{tr('StatusModInstallFailed')}: {path.name}\n\n{result.message or result.status.name}",
                )
            self.refresh_view()
            QTimer.singleShot(0, self._install_next)

        def failed(exc: BaseException) -> None:
            self._task_failed(exc, "StatusModInstallFailed")
            QTimer.singleShot(0, self._install_next)

        self.tasks.run(work, done, failed)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self.session.install is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.install_paths(paths))

    # ================================================================== game launch
    def start_game(self) -> None:
        install = self.session.install
        if install is None:
            dialogs.error(self, tr("ErrorGameInstallationNotFound"))
            return
        if not self._guard(self.session.save_mod_order):
            return
        self.status(tr("StatusStartingGame"))
        try:
            result = launch_game(install, self.settings.game_launch_args, self.settings.is_dev_mode)
        except (LaunchError, OSError) as exc:
            self.status(tr("StatusFailedToStartGame"))
            dialogs.error(self, tr("FailedToStartGame", exc))
            return
        self.status(tr("StatusGameStarted"))
        if not result.arguments_applied:
            dialogs.info(self, tr("SteamUrlNoArgs"))

    # ================================================================== conflicts
    def scan_conflicts(self, then_show: bool = False) -> None:
        if self._scan_cancel is not None or self.session.install is None:
            return
        cancel = threading.Event()
        self._scan_cancel = cancel
        self.scan_progress.setValue(0)
        self.scan_progress.show()
        self.scan_cancel_button.show()
        self.conflicts_button.setEnabled(False)

        def work(progress: Callable[[object], None]) -> list[ConflictGroup]:
            return self.session.scan_conflicts(lambda value: progress(value), cancel)

        def finish() -> None:
            self._scan_cancel = None
            self.scan_progress.hide()
            self.scan_cancel_button.hide()
            self.conflicts_button.setEnabled(True)

        def done(conflicts: list[ConflictGroup]) -> None:
            finish()
            self.refresh_view()
            if conflicts:
                self.status(tr("ConflictsDetected", len(conflicts)))
            if then_show:
                self._show_conflict_dialog()

        def failed(exc: BaseException) -> None:
            finish()
            if isinstance(exc, ScanCancelled):
                self.status(tr("ConflictScanCanceled"))
            else:
                self._task_failed(exc)

        self.tasks.run(
            work, done, failed, lambda value: self.scan_progress.setValue(int(value)), serial=False
        )  # type: ignore[call-overload]

    def cancel_scan(self) -> None:
        if self._scan_cancel is not None:
            self._scan_cancel.set()

    def show_conflicts(self) -> None:
        self.scan_conflicts(then_show=True)

    def _show_conflict_dialog(self) -> None:
        names = {m.id: m.name for m in self.session.mods}
        workshop = {m.id for m in self.session.mods if m.is_workshop_mod}
        ConflictDialog(self, self.session.conflicts, names, workshop).exec()

    # ================================================================== Nexus
    def _startup_online_checks(self) -> None:
        if self.ctx.nexus.is_logged_in:
            self.tasks.run(
                self.ctx.nexus.refresh, lambda _: self._after_account_refresh(), lambda _e: None, serial=False
            )
        if self.settings.enable_update_notifications:
            self.tasks.run(check_for_app_update, self._app_update_found, lambda _e: None, serial=False)

    def _after_account_refresh(self) -> None:
        self._refresh_account()
        if self.settings.enable_update_notifications and self.ctx.nexus.is_logged_in:
            self.check_all_updates(quiet=True)

    def _app_update_found(self, update: AppUpdate | None) -> None:
        if update is not None and dialogs.confirm(self, tr("AppUpdateAvailable", update.latest_version)):
            self._open_url(update.download_page)

    def login(self) -> None:
        cancel = threading.Event()
        busy = BusyDialog(self, tr("MenuLogin"), tr("NexusLoginWaiting"))
        busy.cancelled.connect(cancel.set)

        def done(user: object) -> None:
            busy.accept()
            self._refresh_account()
            self.status(tr("InfoLoggedInAs", self.ctx.nexus.username))
            if not self.ctx.credentials.is_secure:
                dialogs.warn(self, tr("InsecureCredentialWarning"))

        def failed(exc: BaseException) -> None:
            busy.accept()
            if not isinstance(exc, SsoCancelled):
                self._task_failed(exc)

        self.tasks.run(lambda: self.ctx.nexus.login(open_url, cancel), done, failed, serial=False)
        busy.exec()

    def logout(self) -> None:
        self.ctx.nexus.logout()
        self._refresh_account()
        self.status(tr("InfoNotLoggedIn"))

    def _require_nexus(self, mod: Mod) -> bool:
        if not self.ctx.nexus.is_logged_in:
            dialogs.error(self, tr("ErrorNexusApiKeyMissing"))
            return False
        if mod.mod_number <= 0:
            dialogs.error(self, tr("UpdateCheckNoModNumber"))
            return False
        return True

    def check_all_updates(self, quiet: bool = False) -> None:
        if not self.ctx.nexus.is_logged_in or self.session.game is None:
            if not quiet:
                dialogs.error(self, tr("ErrorNexusApiKeyMissing"))
            return
        self.status(tr("UpdateCheckInProgress"))

        def done(summary: UpdateCheckSummary) -> None:
            self.refresh_view()
            if summary.rate_limited:
                self.status(tr("UpdatesCheckRateLimited"))
            else:
                self.status(tr("ModUpdatesAvailable", len(summary.updates)))

        self.tasks.run(self.session.check_all_updates, done, lambda e: self._task_failed(e), serial=False)

    def check_mod_update(self, mod: Mod) -> None:
        if not self._require_nexus(mod):
            return
        self.status(tr("UpdateCheckInProgress"))

        def done(latest: str | None) -> None:
            self.refresh_view()
            self.status(tr("StatusReady"))
            if latest:
                self.update_mod(mod)
            else:
                dialogs.info(self, tr("UpdateCheckNoUpdate", mod.version))

        def failed(exc: BaseException) -> None:
            self.status(tr("StatusReady"))
            if isinstance(exc, NexusRateLimited):
                dialogs.warn(self, tr("UpdatesCheckRateLimited"))
            else:
                dialogs.error(self, tr("UpdateCheckError", exc))

        self.tasks.run(lambda: self.session.check_mod_update(mod), done, failed, serial=False)

    def update_mod(self, mod: Mod) -> None:
        game = self.session.game
        if game is None or not self._require_nexus(mod):
            return
        if not self.ctx.nexus.is_premium or mod.is_workshop_mod:
            self._open_url(mod_files_page_url(game.nexus_domain, mod.mod_number))
            return
        if not dialogs.confirm(
            self, tr("UpdateAvailableMessage", mod.latest_version or "?"), tr("ConfirmUpdateTitle")
        ):
            return
        self.status(tr("UpdateInstalling"))
        self.status_progress.setValue(0)
        self.status_progress.show()

        def progress(value: object) -> None:
            done_bytes, total = value  # type: ignore[misc]
            if total:
                self.status_progress.setValue(int(done_bytes * 100 / total))

        def work(report: Callable[[object], None]) -> None:
            self.session.install_update(mod, lambda d, t: report((d, t)))

        def done(_: object) -> None:
            self.status_progress.hide()
            self.status(tr("UpdateInstalledSuccess", mod.name))

        def failed(exc: BaseException) -> None:
            self.status_progress.hide()
            self.status(tr("UpdateInstallFailed"))
            if isinstance(exc, NexusPremiumRequired):
                self._open_url(mod_files_page_url(game.nexus_domain, mod.mod_number))
            elif isinstance(exc, NexusError):
                dialogs.error(self, f"{tr('UpdateDownloadLinkFailed')}\n\n{exc}")
            else:
                dialogs.error(self, f"{tr('UpdateInstallFailed')}\n\n{exc}")

        self.tasks.run(work, done, failed, progress)

    def endorse(self, mod: Mod) -> None:
        game = self.session.game
        if game is None or not self._require_nexus(mod):
            return
        self.tasks.run(
            lambda: self.ctx.nexus.client.endorse(game.nexus_domain, mod.mod_number),
            lambda _: dialogs.info(self, tr("EndorseSuccess")),
            lambda exc: dialogs.error(self, str(exc)),
            serial=False,
        )

    def visit_website(self, mod: Mod) -> None:
        game = self.session.game
        if game is None:
            return
        if mod.mod_number <= 0:
            dialogs.error(self, tr("ErrorModNumberMissing"))
            return
        self._open_url(mod_page_url(game.nexus_domain, mod.mod_number))

    # ================================================================== settings
    def open_settings(self) -> None:
        hooks = SettingsHooks(
            save=self._save_settings,
            theme_changed=lambda _dark: self.apply_theme(),
            mod_order_changed=self._apply_mod_order_setting,
            set_executable=self._set_executable,
            ignored_mods=lambda: [m for m in self.session.mods if m.ignored_in_conflict_detector],
            unignore=lambda mod: self.session.set_ignored_in_conflicts(mod, False),
            create_backup=self.create_backup,
            language_changed=self._language_changed,
            view_changed=self.refresh_view,
            open_backups=self._open_backups,
        )
        SettingsDialog(self, self.settings, self.session.installs, hooks).exec()
        self.refresh_view()

    def _open_backups(self) -> None:
        if self.session.install is None:
            return
        folder = self.session.mods_dir.parent / BACKUP_ROOT_NAME
        if folder.is_dir():
            self._open(folder)
        else:
            dialogs.info(self, tr("SettingsNoBackups"))

    def _set_executable(self, game: GameType, path: Path) -> GameInstall:
        install = self.session.set_manual_install(game, path)
        if game is self.session.game:
            QTimer.singleShot(0, lambda: self.load_game(game))
        return install

    def _apply_mod_order_setting(self, enabled: bool) -> bool:
        if self.session.install is None:
            return True
        try:
            self.ctx.order_files.apply_setting(enabled, self.session.mods_dir)
            self.session.save_mod_order()
        except OSError as exc:
            dialogs.error(self, str(exc))
            return False
        return True

    def create_backup(self) -> None:
        if self.session.install is None:
            return

        def done(path: Path | None) -> None:
            if path is not None:
                self.status(tr("BackupCreated", path))
                dialogs.info(self, tr("BackupCreated", path))

        self.tasks.run(self.session.create_backup, done, lambda e: self._task_failed(e))

    def _language_changed(self, _language: str) -> None:
        if dialogs.confirm(self, tr("DialogMessageLanguageChanged"), tr("DialogTitleLanguageChanged")):
            self.restart_requested = True
            QTimer.singleShot(0, self._close_for_restart)

    def _close_for_restart(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget is not self and widget.isVisible() and widget.isModal():
                widget.close()
        self.close()

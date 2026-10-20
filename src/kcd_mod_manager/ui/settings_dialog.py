"""Settings window. Like the original, every change is applied and saved immediately."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager import __version__
from kcd_mod_manager.application.settings import SUPPORTED_LANGUAGES, AppSettings
from kcd_mod_manager.domain.models import GameInstall, GameType, Mod
from kcd_mod_manager.i18n import LANGUAGE_NAMES, tr
from kcd_mod_manager.ui import dialogs, icons
from kcd_mod_manager.ui.theme import current_palette
from kcd_mod_manager.ui.widgets import Card, ToggleSwitch, footer_bar, label, secondary_button

MOD_ID_ROLE = Qt.ItemDataRole.UserRole


@dataclass(slots=True)
class SettingsHooks:
    save: Callable[[], None]
    theme_changed: Callable[[bool], None]
    mod_order_changed: Callable[[bool], bool]
    """Apply the order-file setting now; returns False (and reports) if it failed."""
    set_executable: Callable[[GameType, Path], GameInstall]
    ignored_mods: Callable[[], list[Mod]]
    unignore: Callable[[Mod], None]
    create_backup: Callable[[], None]
    language_changed: Callable[[str], None]
    view_changed: Callable[[], None]
    open_backups: Callable[[], None] | None = None


class SettingRow(Card):
    """A card with an optional glyph, a title, a one-line description and a control on the right."""

    def __init__(
        self,
        title: str,
        description: str = "",
        control: QWidget | None = None,
        icon_name: str | None = None,
    ) -> None:
        super().__init__()
        self.setMinimumHeight(64)
        self._icon_name = icon_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(14)
        # Children get ``self`` as parent up front: setVisible() on a parentless widget opens a window.
        self.icon = QLabel(self)
        self.icon.setFixedSize(20, 20)
        self.icon.setVisible(icon_name is not None)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "cardTitle", self, wrap=True)
        text.addWidget(self.title)
        self.description = label(description, "cardDescription", self, wrap=True)
        self.description.setVisible(bool(description))
        text.addWidget(self.description)
        layout.addLayout(text, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        if self._icon_name:
            self.icon.setPixmap(icons.pixmap(self._icon_name, current_palette().text_secondary, 20))


class SettingsDialog(QDialog):
    PAGES = (
        ("general", "settings", "SettingsPageGeneral"),
        ("mods", "apps_list", "SettingsPageMods"),
        ("conflicts", "warning", "SettingsPageConflicts"),
        ("game", "games", "SettingsPageGame"),
        ("language", "language", "SettingsPageLanguage"),
        ("backups", "history", "SettingsPageBackups"),
    )

    def __init__(
        self,
        parent: QWidget | None,
        settings: AppSettings,
        installs: dict[GameType, GameInstall | None],
        hooks: SettingsHooks,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("MenuSettings"))
        self.resize(900, 600)
        self.setMinimumSize(760, 480)
        self.settings = settings
        self.hooks = hooks
        self._installs = installs
        self.toggles: dict[str, ToggleSwitch] = {}
        self.path_labels: dict[GameType, QLabel] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 20, 12, 12)
        side_layout.setSpacing(12)
        heading = label(tr("MenuSettings"), "sectionTitle")
        heading.setContentsMargins(8, 0, 0, 0)
        side_layout.addWidget(heading)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_layout.addWidget(self.nav, 1)
        outer.addWidget(sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        bar, footer = footer_bar()
        footer.addStretch(1)
        close = QPushButton(tr("SettingsClose"))
        close.setObjectName("dialogPrimary")
        close.setMinimumSize(100, 32)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        right.addWidget(bar)
        outer.addLayout(right, 1)

        builders = {
            "general": self._general_page,
            "mods": self._mods_page,
            "conflicts": self._conflicts_page,
            "game": self._game_page,
            "language": self._language_page,
            "backups": self._backups_page,
        }
        for key, icon_name, title_key in self.PAGES:
            item = QListWidgetItem(tr(title_key))
            item.setData(Qt.ItemDataRole.UserRole, icon_name)
            item.setSizeHint(QSize(0, 38))
            self.nav.addItem(item)
            self.pages.addWidget(self._page(tr(title_key), builders[key]))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.refresh_theme()

    # ------------------------------------------------------------------ structure
    def refresh_theme(self) -> None:
        color = current_palette().text_secondary
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            item.setIcon(icons.icon(str(item.data(Qt.ItemDataRole.UserRole)), color))

    def page_titles(self) -> list[str]:
        return [self.nav.item(i).text() for i in range(self.nav.count())]

    def show_page(self, key: str) -> None:
        self.nav.setCurrentRow([p[0] for p in self.PAGES].index(key))

    def _page(self, title: str, build: Callable[[QVBoxLayout], None]) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(6)
        layout.addWidget(label(title, "pageTitle"))
        layout.addSpacing(10)
        build(layout)
        layout.addStretch(1)
        scroll.setWidget(body)
        return scroll

    @staticmethod
    def _section(layout: QVBoxLayout, title: str) -> None:
        layout.addSpacing(10)
        caption = label(title, "fieldLabel")
        caption.setContentsMargins(2, 0, 0, 2)
        layout.addWidget(caption)

    def _toggle_row(
        self, layout: QVBoxLayout, name: str, title: str, description: str, icon_name: str | None = None
    ) -> SettingRow:
        switch = ToggleSwitch()
        switch.setChecked(bool(getattr(self.settings, name)))
        switch.setAccessibleName(title)
        switch.toggled.connect(lambda checked, n=name: self._toggled(n, checked))
        self.toggles[name] = switch
        row = SettingRow(title, description, switch, icon_name)
        layout.addWidget(row)
        return row

    # ------------------------------------------------------------------ pages
    def _general_page(self, layout: QVBoxLayout) -> None:
        self._section(layout, tr("SettingsSectionAppearance"))
        self._toggle_row(
            layout, "is_dark_mode", tr("SettingsDarkModeTitle"), tr("SettingsDarkModeDesc"), "dark_theme"
        )
        self._section(layout, tr("SettingsSectionBehavior"))
        self._toggle_row(
            layout, "ask_on_delete", tr("SettingsAskDeleteTitle"), tr("SettingsAskDeleteDesc"), "delete"
        )
        self._toggle_row(
            layout,
            "enable_update_notifications",
            tr("SettingsUpdatesTitle"),
            tr("SettingsUpdatesDesc"),
            "update",
        )
        self._toggle_row(
            layout, "is_dev_mode", tr("SettingsDevModeTitle"), tr("SettingsDevModeDesc"), "wrench"
        )
        self._section(layout, tr("SettingsSectionAbout"))
        layout.addWidget(
            SettingRow(tr("SettingsVersionTitle"), f"KCD Mod Manager {__version__}", None, "info")
        )

    def _mods_page(self, layout: QVBoxLayout) -> None:
        self._toggle_row(
            layout,
            "compact_mod_list",
            tr("SettingsCompactListTitle"),
            tr("SettingsCompactListDesc"),
            "apps_list",
        )
        self._toggle_row(
            layout, "mod_order_enabled", tr("SettingsModOrderTitle"), tr("SettingsModOrderDesc"), "sort"
        )
        self._toggle_row(
            layout,
            "enable_file_renaming",
            tr("EnableFileRenaming"),
            tr("EnableFileRenamingTooltip"),
            "rename",
        )
        self._toggle_row(
            layout,
            "allow_workshop_mod_actions",
            tr("AllowWorkshopActionsText"),
            tr("AllowWorkshopActionsTooltip"),
            "shield",
        )

    def _conflicts_page(self, layout: QVBoxLayout) -> None:
        self._toggle_row(
            layout,
            "conflict_detector_only_enabled_mods",
            tr("ConflictDetectorOnlyEnabledModsText"),
            tr("ConflictDetectorOnlyEnabledModsTooltip"),
            "checkmark",
        )
        self._section(layout, tr("IgnoredConflictsListTitleText"))
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)
        card_layout.addWidget(label(tr("SettingsIgnoredDesc"), "cardDescription", wrap=True))
        self.ignored_list = QListWidget()
        self.ignored_list.setMinimumHeight(120)
        card_layout.addWidget(self.ignored_list)
        self.ignored_empty = label(tr("SettingsIgnoredEmpty"), "hint")
        card_layout.addWidget(self.ignored_empty)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.unignore_button = secondary_button(tr("RemoveIgnoredConflictText"), "dismiss")
        self.unignore_button.clicked.connect(self._unignore)
        buttons.addWidget(self.unignore_button)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        self.ignored_list.currentRowChanged.connect(lambda row: self.unignore_button.setEnabled(row >= 0))
        self._fill_ignored()

    def _game_page(self, layout: QVBoxLayout) -> None:
        self.launch_args = QLineEdit(self.settings.game_launch_args)
        self.launch_args.setPlaceholderText("-devmode +exec user.cfg")
        self.launch_args.setMinimumWidth(260)
        self.launch_args.editingFinished.connect(self._launch_args_changed)
        layout.addWidget(
            SettingRow(tr("SettingsLaunchArgsTitle"), tr("SettingsLaunchArgsDesc"), self.launch_args, "play")
        )
        self._section(layout, tr("SettingsSectionInstallations"))
        for game in GameType:
            button = secondary_button(tr("SelectFolderButton"), "folder")
            button.setToolTip(tr("SelectFolderTooltip"))
            button.clicked.connect(lambda _=False, g=game: self._browse(g))
            row = SettingRow(tr(game.display_key), self._path_text(game), button, "games")
            row.description.setVisible(True)
            row.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.path_labels[game] = row.description
            layout.addWidget(row)

    def _language_page(self, layout: QVBoxLayout) -> None:
        self.language = QComboBox()
        self.language.setMinimumSize(150, 28)
        for code in SUPPORTED_LANGUAGES:
            self.language.addItem(LANGUAGE_NAMES.get(code, code), code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.settings.language)))
        self.language.currentIndexChanged.connect(self._language_changed)
        layout.addWidget(
            SettingRow(tr("SettingsLanguageTitle"), tr("SettingsLanguageDesc"), self.language, "language")
        )

    def _backups_page(self, layout: QVBoxLayout) -> None:
        self._toggle_row(layout, "create_backup", tr("SettingsBackupTitle"), tr("SettingsBackupDesc"), "save")
        self._toggle_row(
            layout,
            "backup_on_startup",
            tr("SettingsBackupStartupTitle"),
            tr("SettingsBackupStartupDesc"),
            "history",
        )
        self.max_backups = QSpinBox()
        self.max_backups.setRange(1, 999)
        self.max_backups.setValue(max(1, self.settings.backup_max_count))
        self.max_backups.setMinimumWidth(90)
        self.max_backups.valueChanged.connect(self._max_backups_changed)
        layout.addWidget(
            SettingRow(tr("SettingsMaxBackupsTitle"), tr("SettingsMaxBackupsDesc"), self.max_backups, "copy")
        )
        backup_now = QPushButton(tr("CreateBackupNow"))
        backup_now.setObjectName("dialogPrimary")
        backup_now.setMinimumHeight(30)
        backup_now.clicked.connect(self.hooks.create_backup)
        layout.addWidget(
            SettingRow(tr("CreateBackupNow"), tr("SettingsBackupNowDesc"), backup_now, "archive")
        )
        if self.hooks.open_backups is not None:
            open_button = secondary_button(tr("SettingsOpenFolder"), "folder")
            open_button.clicked.connect(self.hooks.open_backups)
            layout.addWidget(
                SettingRow(
                    tr("SettingsBackupFolderTitle"), tr("SettingsBackupFolderDesc"), open_button, "folder"
                )
            )

    # ------------------------------------------------------------------ behaviour
    def _set_checked_silently(self, name: str, value: bool) -> None:
        switch = self.toggles[name]
        switch.blockSignals(True)
        switch.setChecked(value)
        switch.blockSignals(False)
        switch.update()

    def _toggled(self, name: str, checked: bool) -> None:
        if name == "mod_order_enabled":
            previous = self.settings.mod_order_enabled
            self.settings.mod_order_enabled = checked
            if not self.hooks.mod_order_changed(checked):
                self.settings.mod_order_enabled = previous
                self._set_checked_silently(name, previous)
                return
        elif name == "allow_workshop_mod_actions" and checked:
            if not self.settings.allow_workshop_actions_warning_shown:
                dialogs.warn(self, tr("WorkshopActionsWarning"))
                self.settings.allow_workshop_actions_warning_shown = True
            self.settings.allow_workshop_mod_actions = True
        else:
            setattr(self.settings, name, checked)
        self.hooks.save()
        if name == "is_dark_mode":
            self.hooks.theme_changed(checked)
            self.refresh_theme()
        elif name in ("allow_workshop_mod_actions", "enable_file_renaming", "compact_mod_list"):
            self.hooks.view_changed()

    def _launch_args_changed(self) -> None:
        value = self.launch_args.text().strip()
        if value != self.settings.game_launch_args:
            self.settings.game_launch_args = value
            self.hooks.save()

    def _max_backups_changed(self, value: int) -> None:
        self.settings.backup_max_count = value
        self.hooks.save()

    def _language_changed(self) -> None:
        code = str(self.language.currentData())
        if code != self.settings.language:
            self.settings.language = code
            self.hooks.save()
            self.hooks.language_changed(code)

    def _path_text(self, game: GameType) -> str:
        install = self._installs.get(game)
        if install is not None:
            return str(install.executable_path)
        return self.settings.game_path(game) or tr("GameFolderNotFound")

    def _browse(self, game: GameType) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("TitleSelectGameExecutable"), "", "KingdomCome.exe (KingdomCome.exe);;*.exe (*.exe)"
        )
        if not path:
            return
        try:
            self._installs[game] = self.hooks.set_executable(game, Path(path))
        except Exception as exc:
            dialogs.error(self, str(exc), tr("DialogTitleInvalidPath"))
            return
        self.path_labels[game].setText(self._path_text(game))
        dialogs.info(self, tr("GameFolderSaved", path))

    def _fill_ignored(self) -> None:
        self.ignored_list.clear()
        for mod in self.hooks.ignored_mods():
            item = QListWidgetItem(mod.name)
            item.setData(MOD_ID_ROLE, mod.id)
            self.ignored_list.addItem(item)
        empty = self.ignored_list.count() == 0
        self.ignored_list.setVisible(not empty)
        self.ignored_empty.setVisible(empty)
        self.unignore_button.setEnabled(False)
        self.unignore_button.setVisible(not empty)

    def _unignore(self) -> None:
        item = self.ignored_list.currentItem()
        if item is None:
            return
        mod_id = item.data(MOD_ID_ROLE)
        mod = next((m for m in self.hooks.ignored_mods() if m.id == mod_id), None)
        if mod is not None:
            self.hooks.unignore(mod)
        self._fill_ignored()

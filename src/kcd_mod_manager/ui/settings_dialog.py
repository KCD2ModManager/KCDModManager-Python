"""Settings window. Like the original, every change is applied and saved immediately."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager.application.settings import SUPPORTED_LANGUAGES, AppSettings
from kcd_mod_manager.domain.models import GameInstall, GameType, Mod
from kcd_mod_manager.i18n import LANGUAGE_NAMES, tr
from kcd_mod_manager.ui import dialogs


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


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        settings: AppSettings,
        installs: dict[GameType, GameInstall | None],
        hooks: SettingsHooks,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("MenuSettings"))
        self.resize(620, 720)
        self.settings = settings
        self.hooks = hooks
        self._installs = installs

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        general = QGroupBox(tr("GeneralSettings"))
        form = QFormLayout(general)
        self.toggles: dict[str, QCheckBox] = {}
        self._toggle(form, "ask_on_delete", tr("ToggleDeleteConfirmation"))
        self._toggle(form, "is_dark_mode", tr("ToggleDarkMode"))
        self._toggle(form, "is_dev_mode", tr("ToggleDevMode"))
        self._toggle(form, "enable_update_notifications", tr("ToggleUpdateNotifications"))
        self._toggle(form, "mod_order_enabled", tr("ToggleModOrderCreation"))
        self._toggle(form, "enable_file_renaming", tr("EnableFileRenaming"), tr("EnableFileRenamingTooltip"))
        self._toggle(
            form,
            "allow_workshop_mod_actions",
            tr("AllowWorkshopActionsText"),
            tr("AllowWorkshopActionsTooltip"),
        )
        self._toggle(
            form,
            "conflict_detector_only_enabled_mods",
            tr("ConflictDetectorOnlyEnabledModsText"),
            tr("ConflictDetectorOnlyEnabledModsTooltip"),
        )
        self.launch_args = QLineEdit(settings.game_launch_args)
        self.launch_args.setPlaceholderText("-devmode +exec user.cfg")
        self.launch_args.editingFinished.connect(self._launch_args_changed)
        form.addRow(tr("LaunchArgsLabel"), self.launch_args)
        layout.addWidget(general)

        games = QGroupBox(tr("SetGamePath"))
        games_form = QFormLayout(games)
        self.path_labels: dict[GameType, QLabel] = {}
        for game in GameType:
            row = QHBoxLayout()
            label = QLabel(self._path_text(game))
            label.setObjectName("secondary")
            label.setWordWrap(True)
            self.path_labels[game] = label
            row.addWidget(label, 1)
            button = QPushButton(tr("SelectFolderButton"))
            button.setToolTip(tr("SelectFolderTooltip"))
            button.clicked.connect(lambda _=False, g=game: self._browse(g))
            row.addWidget(button)
            games_form.addRow(tr(game.display_key), row)
        layout.addWidget(games)

        ignored = QGroupBox(tr("IgnoredConflictsListTitleText"))
        ignored_layout = QVBoxLayout(ignored)
        self.ignored_list = QListWidget()
        self.ignored_list.setMaximumHeight(140)
        ignored_layout.addWidget(self.ignored_list)
        remove = QPushButton(tr("RemoveIgnoredConflictText"))
        remove.clicked.connect(self._unignore)
        ignored_layout.addWidget(remove)
        layout.addWidget(ignored)
        self._fill_ignored()

        language = QGroupBox(tr("LanguageSettings"))
        language_form = QFormLayout(language)
        self.language = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self.language.addItem(LANGUAGE_NAMES.get(code, code), code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.language.currentIndexChanged.connect(self._language_changed)
        language_form.addRow(tr("SelectLanguage"), self.language)
        layout.addWidget(language)

        backup = QGroupBox(tr("BackupSettings"))
        backup_form = QFormLayout(backup)
        self._toggle(backup_form, "create_backup", tr("ToggleBackupCreation"))
        self._toggle(backup_form, "backup_on_startup", tr("BackupOnStartup"))
        self.max_backups = QSpinBox()
        self.max_backups.setRange(1, 999)
        self.max_backups.setValue(max(1, settings.backup_max_count))
        self.max_backups.valueChanged.connect(self._max_backups_changed)
        backup_form.addRow(tr("SetMaxBackups"), self.max_backups)
        backup_now = QPushButton(tr("CreateBackupNow"))
        backup_now.clicked.connect(hooks.create_backup)
        backup_form.addRow("", backup_now)
        layout.addWidget(backup)
        layout.addStretch(1)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("OKButton"))
        close.rejected.connect(self.accept)
        outer.addWidget(close)

    # ------------------------------------------------------------------ helpers
    def _toggle(self, form: QFormLayout, name: str, label: str, tooltip: str = "") -> None:
        box = QCheckBox()
        box.setChecked(bool(getattr(self.settings, name)))
        if tooltip:
            box.setToolTip(tooltip)
        box.toggled.connect(lambda checked, n=name: self._toggled(n, checked))
        caption = QLabel(label)
        caption.setWordWrap(True)
        if tooltip:
            caption.setToolTip(tooltip)
        form.addRow(caption, box)
        self.toggles[name] = box

    def _set_checked_silently(self, name: str, value: bool) -> None:
        box = self.toggles[name]
        box.blockSignals(True)
        box.setChecked(value)
        box.blockSignals(False)

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
        elif name in ("allow_workshop_mod_actions", "enable_file_renaming"):
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
            item.setData(256, mod.id)
            self.ignored_list.addItem(item)

    def _unignore(self) -> None:
        item = self.ignored_list.currentItem()
        if item is None:
            return
        mod_id = item.data(256)
        mod = next((m for m in self.hooks.ignored_mods() if m.id == mod_id), None)
        if mod is not None:
            self.hooks.unignore(mod)
        self._fill_ignored()

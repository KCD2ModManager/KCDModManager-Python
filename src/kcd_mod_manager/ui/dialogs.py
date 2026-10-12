"""Small dialogs: prompts, confirmations, game selection, categories, conflicts."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager.domain import categories as cat
from kcd_mod_manager.domain.models import ConflictGroup, GameInstall, GameType, ModCategory
from kcd_mod_manager.i18n import tr
from kcd_mod_manager.resources import resource_path

# --------------------------------------------------------------------------- message helpers


def info(parent: QWidget | None, message: str, title: str | None = None) -> None:
    QMessageBox.information(parent, title or tr("DialogTitleInformation"), message)


def warn(parent: QWidget | None, message: str, title: str | None = None) -> None:
    QMessageBox.warning(parent, title or tr("DialogTitleWarning"), message)


def error(parent: QWidget | None, message: str, title: str | None = None) -> None:
    QMessageBox.critical(parent, title or tr("DialogTitleError"), message)


def confirm(parent: QWidget | None, message: str, title: str | None = None) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, title or tr("DialogTitleQuestion"), message, parent=parent)
    yes = box.addButton(tr("YesButton"), QMessageBox.ButtonRole.YesRole)
    box.addButton(tr("NoButton"), QMessageBox.ButtonRole.NoRole)
    box.exec()
    return box.clickedButton() is yes


def ask_text(parent: QWidget | None, title: str, prompt: str, text: str = "") -> str | None:
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(prompt)
    dialog.setTextValue(text)
    dialog.setOkButtonText(tr("OKButton"))
    dialog.setCancelButtonText(tr("CancelButton"))
    dialog.resize(380, dialog.sizeHint().height())
    return dialog.textValue() if dialog.exec() == QDialog.DialogCode.Accepted else None


def ask_int(
    parent: QWidget | None, title: str, prompt: str, value: int, minimum: int, maximum: int
) -> int | None:
    dialog = QInputDialog(parent)
    dialog.setInputMode(QInputDialog.InputMode.IntInput)
    dialog.setWindowTitle(title)
    dialog.setLabelText(prompt)
    dialog.setIntRange(minimum, maximum)
    dialog.setIntValue(value)
    dialog.setOkButtonText(tr("OKButton"))
    dialog.setCancelButtonText(tr("CancelButton"))
    return dialog.intValue() if dialog.exec() == QDialog.DialogCode.Accepted else None


def _buttons(dialog: QDialog, ok_text: str | None = None) -> QDialogButtonBox:
    box = QDialogButtonBox()
    ok = box.addButton(ok_text or tr("OKButton"), QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setObjectName("primary")
    box.addButton(tr("CancelButton"), QDialogButtonBox.ButtonRole.RejectRole)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class MultilineDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, prompt: str, text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.editor = QPlainTextEdit(text)
        layout.addWidget(self.editor)
        layout.addWidget(_buttons(self))

    def value(self) -> str:
        return self.editor.toPlainText()


def ask_multiline(parent: QWidget | None, title: str, prompt: str, text: str = "") -> str | None:
    dialog = MultilineDialog(parent, title, prompt, text)
    return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None


class DeleteConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, mod_name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("DeleteModTitle"))
        layout = QVBoxLayout(self)
        label = QLabel(f"{tr('DeleteModMessage')}\n\n{mod_name}")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.dont_ask = QCheckBox(tr("DontAskAgain"))
        layout.addWidget(self.dont_ask)
        box = QDialogButtonBox()
        yes = box.addButton(tr("YesButton"), QDialogButtonBox.ButtonRole.AcceptRole)
        yes.setObjectName("primary")
        box.addButton(tr("NoButton"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)


def confirm_delete(parent: QWidget | None, mod_name: str) -> tuple[bool, bool]:
    """Returns (confirmed, don't ask again)."""
    dialog = DeleteConfirmDialog(parent, mod_name)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return ok, ok and dialog.dont_ask.isChecked()


# --------------------------------------------------------------------------- game selection


class _GameCard(QFrame):
    clicked = Signal()

    def __init__(self, game: GameType, install: GameInstall | None) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setCursor(Qt.CursorShape.PointingHandCursor if install else Qt.CursorShape.ArrowCursor)
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        image = QLabel()
        pixmap = QPixmap(str(resource_path("images", "kcd1.jpg" if game is GameType.KCD1 else "kcd2.jpg")))
        if not pixmap.isNull():
            image.setPixmap(
                pixmap.scaled(
                    280,
                    158,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image)
        title = QLabel(tr(game.display_key))
        title.setStyleSheet("font-weight: bold; font-size: 11pt;")
        title.setWordWrap(True)
        layout.addWidget(title)
        status = QLabel(tr("GameFolderFound") if install else tr("GameFolderNotFound"))
        status.setObjectName("secondary")
        layout.addWidget(status)
        if install is not None:
            path = QLabel(str(install.root_path))
            path.setObjectName("secondary")
            path.setWordWrap(True)
            layout.addWidget(path)
        self.select_button = QPushButton(tr("SelectFolderButton"))
        self.select_button.setToolTip(tr("SelectFolderTooltip"))
        layout.addWidget(self.select_button)
        self.selectable = install is not None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.selectable:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class GameSelectionDialog(QDialog):
    """Choose the game; each card can also point the manager at an executable manually."""

    def __init__(
        self,
        parent: QWidget | None,
        installs: dict[GameType, GameInstall | None],
        set_executable: Callable[[GameType, Path], GameInstall],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("SelectGameTitle"))
        self.selected: GameType | None = None
        self._installs = installs
        self._set_executable = set_executable
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("SelectGameMessage")))
        self._cards_layout = QHBoxLayout()
        layout.addLayout(self._cards_layout)
        hint = QLabel(tr("ClickCardToSelect"))
        hint.setObjectName("secondary")
        layout.addWidget(hint)
        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("CancelButton"))
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)
        self._build_cards()

    def _build_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        for game in GameType:
            card = _GameCard(game, self._installs.get(game))
            card.clicked.connect(lambda g=game: self._choose(g))
            card.select_button.clicked.connect(lambda _=False, g=game: self._browse(g))
            self._cards_layout.addWidget(card)

    def _choose(self, game: GameType) -> None:
        self.selected = game
        self.accept()

    def _browse(self, game: GameType) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("TitleSelectGameExecutable"), "", "KingdomCome.exe (KingdomCome.exe);;*.exe (*.exe)"
        )
        if not path:
            return
        try:
            self._installs[game] = self._set_executable(game, Path(path))
        except Exception as exc:
            error(self, str(exc), tr("DialogTitleInvalidPath"))
            return
        self._choose(game)


# --------------------------------------------------------------------------- categories


class AssignCategoryDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        categories: Sequence[ModCategory],
        current: str | None,
        create: Callable[[str], ModCategory],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("AssignCategoryTitle"))
        self._create = create
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("AssignCategoryLabel")))
        self.combo = QComboBox()
        self.combo.addItem(tr("UncategorizedText"), None)
        for category in categories:
            self.combo.addItem(category.name, category.id)
        index = self.combo.findData(current) if current else 0
        self.combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.combo)
        layout.addWidget(QLabel(tr("AssignCategoryCreateLabel")))
        row = QHBoxLayout()
        self.new_name = QLineEdit()
        row.addWidget(self.new_name)
        create_button = QPushButton(tr("AssignCategoryCreateButton"))
        create_button.clicked.connect(self._create_category)
        row.addWidget(create_button)
        layout.addLayout(row)
        layout.addWidget(_buttons(self, tr("AssignCategorySaveButton")))

    def _create_category(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            return
        try:
            category = self._create(name)
        except Exception as exc:
            warn(self, str(exc))
            return
        self.combo.addItem(category.name, category.id)
        self.combo.setCurrentIndex(self.combo.count() - 1)
        self.new_name.clear()

    def category_id(self) -> str | None:
        value = self.combo.currentData()
        return str(value) if value else None


class CategoryDeleteDialog(QDialog):
    def __init__(self, parent: QWidget | None, category: ModCategory, others: Sequence[ModCategory]) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("CategoryDeleteTitle"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{category.name}\n\n{tr('CategoryDeleteMessage')}"))
        self.unassign = QRadioButton(tr("CategoryDeleteUnassign"))
        self.unassign.setChecked(True)
        layout.addWidget(self.unassign)
        self.move_to = QRadioButton(tr("CategoryDeleteMoveTo"))
        layout.addWidget(self.move_to)
        self.target = QComboBox()
        for other in others:
            self.target.addItem(other.name, other.id)
        self.target.setEnabled(False)
        self.move_to.setEnabled(bool(others))
        self.move_to.toggled.connect(self.target.setEnabled)
        layout.addWidget(self.target)
        layout.addWidget(_buttons(self, tr("CategoryDeleteConfirm")))

    def target_id(self) -> str | None:
        return str(self.target.currentData()) if self.move_to.isChecked() and self.target.count() else None


class CategoryManagerDialog(QDialog):
    """Edit a copy of the category list; ``result_categories``/``reassign`` are read after accept."""

    def __init__(
        self, parent: QWidget | None, categories: Sequence[ModCategory], usage: dict[str, int]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("CategoryManagerTitle"))
        self.resize(420, 420)
        self.result_categories = [copy.copy(c) for c in cat.sorted_categories(categories)]
        self.reassign: dict[str, str | None] = {}
        self._usage = usage
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.empty = QLabel(tr("CategoryManagerEmpty"))
        self.empty.setObjectName("secondary")
        layout.addWidget(self.empty)
        row = QHBoxLayout()
        for text, slot in (
            (tr("CategoryManagerCreate"), self._create),
            (tr("CategoryManagerRename"), self._rename),
            (tr("CategoryManagerDelete"), self._delete),
            ("\u25b2", lambda: self._shift(-1)),
            ("\u25bc", lambda: self._shift(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(_buttons(self, tr("CategoryManagerSave")))
        self._refresh()

    def _refresh(self, select: int | None = None) -> None:
        self.list.clear()
        for category in self.result_categories:
            count = self._usage.get(category.id, 0)
            item = QListWidgetItem(f"{category.name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, category.id)
            self.list.addItem(item)
        self.empty.setVisible(not self.result_categories)
        if select is not None and 0 <= select < self.list.count():
            self.list.setCurrentRow(select)

    def _current(self) -> int:
        return self.list.currentRow()

    def _create(self) -> None:
        name = ask_text(self, tr("CategoryCreateTitle"), tr("CategoryCreatePrompt"))
        if name is None:
            return
        try:
            cat.create_category(self.result_categories, name)
        except cat.CategoryError:
            warn(self, tr("CategoryNameDuplicate"))
            return
        self._refresh(len(self.result_categories) - 1)

    def _rename(self) -> None:
        row = self._current()
        if row < 0:
            return
        category = self.result_categories[row]
        name = ask_text(self, tr("CategoryRenameTitle"), tr("CategoryRenamePrompt"), category.name)
        if name is None:
            return
        try:
            cat.rename_category(self.result_categories, category.id, name)
        except cat.CategoryError:
            warn(self, tr("CategoryNameDuplicate"))
            return
        self._refresh(row)

    def _delete(self) -> None:
        row = self._current()
        if row < 0:
            return
        category = self.result_categories[row]
        others = [c for c in self.result_categories if c.id != category.id]
        target: str | None = None
        if self._usage.get(category.id, 0) > 0:
            dialog = CategoryDeleteDialog(self, category, others)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            target = dialog.target_id()
        cat.delete_category(self.result_categories, category.id)
        for old, new in list(self.reassign.items()):
            if new == category.id:
                self.reassign[old] = target
        self.reassign[category.id] = target
        if target:
            self._usage[target] = self._usage.get(target, 0) + self._usage.pop(category.id, 0)
        self._refresh(min(row, len(self.result_categories) - 1))

    def _shift(self, delta: int) -> None:
        row = self._current()
        target = row + delta
        if row < 0 or not 0 <= target < len(self.result_categories):
            return
        items = self.result_categories
        items[row], items[target] = items[target], items[row]
        cat.normalize_orders(items)
        self._refresh(target)


# --------------------------------------------------------------------------- conflicts


class ConflictDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        conflicts: Sequence[ConflictGroup],
        mod_names: dict[str, str],
        workshop_ids: set[str],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ConflictCheckerTitle"))
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        if not conflicts:
            layout.addWidget(QLabel(tr("ConflictCheckerEmpty")))
        tree = QTreeWidget()
        tree.setHeaderLabels([tr("ConflictFileHeader"), tr("ConflictModsHeader")])
        tree.setColumnWidth(0, 420)
        for group in conflicts:
            names = [mod_names.get(i, i) for i in group.mod_ids]
            item = QTreeWidgetItem([group.file_path, ", ".join(names)])
            for mod_id in group.mod_ids:
                label = mod_names.get(mod_id, mod_id)
                if mod_id in workshop_ids:
                    label += f"  [{tr('WorkshopBadgeText')}] {tr('WorkshopConflictNote')}"
                item.addChild(QTreeWidgetItem(["", label]))
            tree.addTopLevelItem(item)
        layout.addWidget(tree)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)


# --------------------------------------------------------------------------- progress


class BusyDialog(QDialog):
    """Modal "please wait" with a cancel button (used for Nexus login)."""

    cancelled = Signal()

    def __init__(self, parent: QWidget | None, title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        box = QDialogButtonBox()
        box.addButton(tr("CancelButton"), QDialogButtonBox.ButtonRole.RejectRole)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.rejected.connect(self.cancelled.emit)

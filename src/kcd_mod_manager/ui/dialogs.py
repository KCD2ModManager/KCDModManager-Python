"""Small dialogs: prompts, confirmations, game selection, categories, conflicts."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager.domain import categories as cat
from kcd_mod_manager.domain.models import ConflictGroup, GameInstall, GameType, ModCategory
from kcd_mod_manager.i18n import tr
from kcd_mod_manager.resources import resource_path
from kcd_mod_manager.ui import icons
from kcd_mod_manager.ui.theme import current_palette
from kcd_mod_manager.ui.widgets import Card, IconButton, label, secondary_button

DIALOG_MARGIN = 20

# --------------------------------------------------------------------------- building blocks


def _dialog_layout(dialog: QDialog, spacing: int = 12) -> QVBoxLayout:
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
    layout.setSpacing(spacing)
    return layout


def _dialog_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumSize(80, 30)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        button.setObjectName("dialogPrimary")
        button.setDefault(True)
    return button


def _button_row(*buttons: QPushButton, leading: QWidget | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    if leading is not None:
        row.addWidget(leading)
    row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    return row


def _ok_cancel(dialog: QDialog, ok_text: str | None = None) -> QHBoxLayout:
    ok = _dialog_button(ok_text or tr("OKButton"), primary=True)
    ok.clicked.connect(dialog.accept)
    cancel = _dialog_button(tr("CancelButton"))
    cancel.clicked.connect(dialog.reject)
    return _button_row(ok, cancel)


KIND_ICONS = {
    "info": ("info_filled", "accent_text"),
    "warning": ("warning_filled", "warning"),
    "error": ("error_filled", "error"),
    "question": ("question_filled", "accent_text"),
}


def _kind_icon(kind: str, size: int = 32) -> QLabel:
    name, role = KIND_ICONS[kind]
    widget = QLabel()
    widget.setFixedSize(size, size)
    widget.setPixmap(icons.pixmap(name, str(getattr(current_palette(), role)), size))
    return widget


# --------------------------------------------------------------------------- message helpers


class MessageDialog(QDialog):
    """Themed replacement for QMessageBox (WPF CustomMessageBoxWindow)."""

    def __init__(
        self,
        parent: QWidget | None,
        kind: str,
        title: str,
        message: str,
        buttons: Sequence[str] = ("OKButton",),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setMaximumWidth(640)
        self.clicked_index = -1
        layout = _dialog_layout(self, 20)
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(_kind_icon(kind), 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = text.font()
        font.setPixelSize(14)
        text.setFont(font)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.addWidget(text, 1)
        layout.addLayout(body)
        widgets = []
        for index, key in enumerate(buttons):
            button = _dialog_button(tr(key), primary=index == 0)
            button.clicked.connect(lambda _=False, i=index: self._clicked(i))
            widgets.append(button)
        layout.addLayout(_button_row(*widgets))

    def _clicked(self, index: int) -> None:
        self.clicked_index = index
        self.accept()


def info(parent: QWidget | None, message: str, title: str | None = None) -> None:
    MessageDialog(parent, "info", title or tr("DialogTitleInformation"), message).exec()


def warn(parent: QWidget | None, message: str, title: str | None = None) -> None:
    MessageDialog(parent, "warning", title or tr("DialogTitleWarning"), message).exec()


def error(parent: QWidget | None, message: str, title: str | None = None) -> None:
    MessageDialog(parent, "error", title or tr("DialogTitleError"), message).exec()


def confirm(parent: QWidget | None, message: str, title: str | None = None) -> bool:
    dialog = MessageDialog(
        parent, "question", title or tr("DialogTitleQuestion"), message, ("YesButton", "NoButton")
    )
    dialog.exec()
    return dialog.clicked_index == 0


class PromptDialog(QDialog):
    """Caption + single input + OK/Cancel (WPF NameInputDialog)."""

    def __init__(self, parent: QWidget | None, title: str, prompt: str, editor: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        layout = _dialog_layout(self, 10)
        caption = label(prompt, wrap=True)
        font = caption.font()
        font.setPixelSize(14)
        caption.setFont(font)
        layout.addWidget(caption)
        editor.setMinimumHeight(32)
        layout.addWidget(editor)
        layout.addSpacing(8)
        layout.addLayout(_ok_cancel(self))
        editor.setFocus()


def ask_text(parent: QWidget | None, title: str, prompt: str, text: str = "") -> str | None:
    editor = QLineEdit(text)
    editor.selectAll()
    dialog = PromptDialog(parent, title, prompt, editor)
    editor.returnPressed.connect(dialog.accept)
    return editor.text() if dialog.exec() == QDialog.DialogCode.Accepted else None


def ask_int(
    parent: QWidget | None, title: str, prompt: str, value: int, minimum: int, maximum: int
) -> int | None:
    editor = QSpinBox()
    editor.setRange(minimum, maximum)
    editor.setValue(value)
    editor.selectAll()
    dialog = PromptDialog(parent, title, prompt, editor)
    return editor.value() if dialog.exec() == QDialog.DialogCode.Accepted else None


class MultilineDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, prompt: str, text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 300)
        layout = _dialog_layout(self, 10)
        layout.addWidget(label(prompt, wrap=True))
        self.editor = QPlainTextEdit(text)
        layout.addWidget(self.editor, 1)
        layout.addLayout(_ok_cancel(self))

    def value(self) -> str:
        return self.editor.toPlainText()


def ask_multiline(parent: QWidget | None, title: str, prompt: str, text: str = "") -> str | None:
    dialog = MultilineDialog(parent, title, prompt, text)
    return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None


class DeleteConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, mod_name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("DeleteModTitle"))
        self.setMinimumWidth(440)
        layout = _dialog_layout(self, 16)
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(_kind_icon("warning"), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        message = label(tr("DeleteModMessage"), wrap=True)
        font = message.font()
        font.setPixelSize(14)
        message.setFont(font)
        text.addWidget(message)
        name = label(mod_name, "fieldLabel", wrap=True)
        text.addWidget(name)
        body.addLayout(text, 1)
        layout.addLayout(body)
        self.dont_ask = QCheckBox(tr("DontAskAgain"))
        yes = _dialog_button(tr("YesButton"), primary=True)
        yes.clicked.connect(self.accept)
        no = _dialog_button(tr("NoButton"))
        no.clicked.connect(self.reject)
        layout.addLayout(_button_row(yes, no, leading=self.dont_ask))


def confirm_delete(parent: QWidget | None, mod_name: str) -> tuple[bool, bool]:
    """Returns (confirmed, don't ask again)."""
    dialog = DeleteConfirmDialog(parent, mod_name)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return ok, ok and dialog.dont_ask.isChecked()


# --------------------------------------------------------------------------- game selection


class _GameImage(QWidget):
    """Cover image cropped to fill (UniformToFill) with a found/not-found strip across the top."""

    def __init__(self, image: Path, found: bool, status: str) -> None:
        super().__init__()
        self._pixmap = QPixmap(str(image))
        self._found = found
        self._status = status
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.setFillRule(Qt.FillRule.WindingFill)
        radius = 6.0
        clip.addRoundedRect(rect, radius, radius)
        clip.addRect(rect.adjusted(0, radius, 0, 0))
        painter.setClipPath(clip.simplified())
        painter.fillRect(rect, QColor(current_palette().panel))
        if not self._pixmap.isNull():
            scaled = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            x = (self.width() - scaled.width()) / 2
            y = (self.height() - scaled.height()) / 2
            painter.drawPixmap(QRectF(x, y, scaled.width(), scaled.height()).toRect(), self._pixmap)
        strip = QRectF(rect.left(), rect.top(), rect.width(), 40)
        painter.fillRect(strip, QColor(0, 170, 0, 170) if self._found else QColor(170, 0, 0, 170))
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(strip, Qt.AlignmentFlag.AlignCenter, self._status)
        painter.end()


class _GameCard(QFrame):
    clicked = Signal()

    def __init__(self, game: GameType, install: GameInstall | None) -> None:
        super().__init__()
        self.setObjectName("gameCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor if install else Qt.CursorShape.ArrowCursor)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        image = resource_path("images", "kcd1.jpg" if game is GameType.KCD1 else "kcd2.jpg")
        status = tr("GameFolderFound") if install else tr("GameFolderNotFound")
        layout.addWidget(_GameImage(image, install is not None, status), 1)
        info_box = QVBoxLayout()
        info_box.setContentsMargins(15, 12, 15, 15)
        info_box.setSpacing(5)
        title = label(tr(game.display_key), wrap=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPixelSize(18)
        font.setBold(True)
        title.setFont(font)
        info_box.addWidget(title)
        if install is not None:
            path = label(str(install.root_path), "secondary", wrap=True)
            path.setAlignment(Qt.AlignmentFlag.AlignCenter)
            small = path.font()
            small.setPixelSize(11)
            path.setFont(small)
            info_box.addWidget(path)
        info_box.addSpacing(5)
        self.select_button = secondary_button(tr("SelectFolderButton"), "folder")
        self.select_button.setMinimumHeight(35)
        self.select_button.setToolTip(tr("SelectFolderTooltip"))
        info_box.addWidget(self.select_button)
        layout.addLayout(info_box)
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
        self.resize(800, 520)
        self.setMinimumSize(720, 480)
        self.selected: GameType | None = None
        self._installs = installs
        self._set_executable = set_executable
        layout = _dialog_layout(self, 16)
        header = label(tr("SelectGameMessage"), "dialogHeader", wrap=True)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(20)
        layout.addLayout(self._cards_layout, 1)
        hint = label(tr("ClickCardToSelect"), "hint")
        cancel = _dialog_button(tr("CancelButton"))
        cancel.setMinimumSize(100, 35)
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(hint)
        footer.addSpacing(15)
        footer.addWidget(cancel)
        layout.addLayout(footer)
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
            self._cards_layout.addWidget(card, 1)

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
        self.setMinimumWidth(420)
        self._create = create
        layout = _dialog_layout(self, 8)
        layout.addWidget(label(tr("AssignCategoryLabel"), "fieldLabel"))
        self.combo = QComboBox()
        self.combo.setMinimumHeight(30)
        self.combo.addItem(tr("UncategorizedText"), None)
        for category in categories:
            self.combo.addItem(category.name, category.id)
        index = self.combo.findData(current) if current else 0
        self.combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.combo)
        layout.addSpacing(8)
        layout.addWidget(label(tr("AssignCategoryCreateLabel"), "fieldLabel"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.new_name = QLineEdit()
        self.new_name.returnPressed.connect(self._create_category)
        row.addWidget(self.new_name, 1)
        create_button = secondary_button(tr("AssignCategoryCreateButton"), "add")
        create_button.setMinimumHeight(32)
        create_button.clicked.connect(self._create_category)
        row.addWidget(create_button)
        layout.addLayout(row)
        layout.addSpacing(12)
        layout.addLayout(_ok_cancel(self, tr("AssignCategorySaveButton")))

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
        self.setMinimumWidth(420)
        layout = _dialog_layout(self, 10)
        layout.addWidget(label(category.name, "dialogHeader", wrap=True))
        layout.addWidget(label(tr("CategoryDeleteMessage"), wrap=True))
        layout.addSpacing(4)
        self.unassign = QRadioButton(tr("CategoryDeleteUnassign"))
        self.unassign.setChecked(True)
        layout.addWidget(self.unassign)
        self.move_to = QRadioButton(tr("CategoryDeleteMoveTo"))
        layout.addWidget(self.move_to)
        self.target = QComboBox()
        self.target.setMinimumHeight(30)
        for other in others:
            self.target.addItem(other.name, other.id)
        self.target.setEnabled(False)
        self.move_to.setEnabled(bool(others))
        self.move_to.toggled.connect(self.target.setEnabled)
        layout.addWidget(self.target)
        layout.addSpacing(10)
        layout.addLayout(_ok_cancel(self, tr("CategoryDeleteConfirm")))

    def target_id(self) -> str | None:
        return str(self.target.currentData()) if self.move_to.isChecked() and self.target.count() else None


class CategoryManagerDialog(QDialog):
    """Edit a copy of the category list; ``result_categories``/``reassign`` are read after accept."""

    def __init__(
        self, parent: QWidget | None, categories: Sequence[ModCategory], usage: dict[str, int]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("CategoryManagerTitle"))
        self.resize(480, 460)
        self.result_categories = [copy.copy(c) for c in cat.sorted_categories(categories)]
        self.reassign: dict[str, str | None] = {}
        self._usage = usage
        layout = _dialog_layout(self, 10)
        layout.addWidget(label(tr("CategoryManagerTitle"), "dialogHeader"))
        body = QHBoxLayout()
        body.setSpacing(8)
        list_box = QVBoxLayout()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._rename())
        list_box.addWidget(self.list, 1)
        self.empty = label(tr("CategoryManagerEmpty"), "hint")
        list_box.addWidget(self.empty)
        body.addLayout(list_box, 1)
        order = QVBoxLayout()
        order.setSpacing(4)
        up = IconButton("up", "success", tr("ToolTipMoveUp"))
        up.clicked.connect(lambda: self._shift(-1))
        down = IconButton("down", "accent_text", tr("ToolTipMoveDown"))
        down.clicked.connect(lambda: self._shift(1))
        order.addWidget(up)
        order.addWidget(down)
        order.addStretch(1)
        body.addLayout(order)
        layout.addLayout(body, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, icon_name, slot in (
            (tr("CategoryManagerCreate"), "add", self._create),
            (tr("CategoryManagerRename"), "rename", self._rename),
            (tr("CategoryManagerDelete"), "delete", self._delete),
        ):
            button = secondary_button(text, icon_name)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(6)
        layout.addLayout(_ok_cancel(self, tr("CategoryManagerSave")))
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
        self.resize(820, 520)
        layout = _dialog_layout(self, 12)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_kind_icon("warning" if conflicts else "info", 24))
        header.addWidget(label(tr("ConflictCheckerTitle"), "dialogHeader"))
        header.addStretch(1)
        layout.addLayout(header)
        if not conflicts:
            layout.addWidget(label(tr("ConflictCheckerEmpty"), "secondary", wrap=True))
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        tree = QTreeWidget()
        tree.setObjectName("conflictTree")
        tree.setHeaderLabels([tr("ConflictFileHeader"), tr("ConflictModsHeader")])
        tree.setColumnWidth(0, 440)
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        warning_icon = icons.icon("warning_filled", current_palette().warning)
        for group in conflicts:
            names = [mod_names.get(i, i) for i in group.mod_ids]
            item = QTreeWidgetItem([group.file_path, ", ".join(names)])
            item.setIcon(0, warning_icon)
            for mod_id in group.mod_ids:
                text = mod_names.get(mod_id, mod_id)
                if mod_id in workshop_ids:
                    text += f"  [{tr('WorkshopBadgeText')}] {tr('WorkshopConflictNote')}"
                item.addChild(QTreeWidgetItem(["", text]))
            tree.addTopLevelItem(item)
        tree.setIconSize(QSize(14, 14))
        card_layout.addWidget(tree)
        layout.addWidget(card, 1)
        close = _dialog_button(tr("SettingsClose"), primary=True)
        close.clicked.connect(self.reject)
        layout.addLayout(_button_row(close))


# --------------------------------------------------------------------------- progress


class BusyDialog(QDialog):
    """Modal "please wait" with a cancel button (used for Nexus login)."""

    cancelled = Signal()

    def __init__(self, parent: QWidget | None, title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = _dialog_layout(self, 14)
        text = label(message, wrap=True)
        font = text.font()
        font.setPixelSize(14)
        text.setFont(font)
        layout.addWidget(text)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(6)
        layout.addWidget(bar)
        cancel = _dialog_button(tr("CancelButton"))
        cancel.clicked.connect(self.reject)
        layout.addLayout(_button_row(cancel))
        self.rejected.connect(self.cancelled.emit)

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
from kcd_mod_manager.ui.widgets import Card, IconButton, footer_bar, label, secondary_button

DIALOG_MARGIN_X, DIALOG_MARGIN_Y = 28, 22

# --------------------------------------------------------------------------- building blocks


def _dialog_layout(
    dialog: QDialog,
    title: str | None = None,
    *,
    subtitle: str | None = None,
    kind: str | None = None,
    spacing: int = 10,
    title_style: str = "pageTitle",
) -> tuple[QVBoxLayout, QHBoxLayout]:
    """Settings-style frame: title (+ subtitle) and body on top, footer bar below; returns both layouts."""
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    body = QVBoxLayout()
    body.setContentsMargins(DIALOG_MARGIN_X, DIALOG_MARGIN_Y, DIALOG_MARGIN_X, DIALOG_MARGIN_Y)
    body.setSpacing(spacing)
    if title is not None:
        header = QHBoxLayout()
        header.setSpacing(12)
        if kind is not None:
            header.addWidget(_kind_icon(kind, 28 if title_style == "pageTitle" else 24))
        header.addWidget(label(title, title_style, dialog, wrap=True), 1)
        body.addLayout(header)
        if subtitle:
            body.addWidget(label(subtitle, "secondary", dialog, wrap=True))
        body.addSpacing(6)
    outer.addLayout(body, 1)
    bar, footer = footer_bar(dialog)
    outer.addWidget(bar)
    return body, footer


def _dialog_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumSize(96, 32)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        button.setObjectName("dialogPrimary")
        button.setDefault(True)
    return button


def _add_buttons(footer: QHBoxLayout, *buttons: QPushButton, leading: QWidget | None = None) -> None:
    if leading is not None:
        footer.addWidget(leading)
    footer.addStretch(1)
    for button in buttons:
        footer.addWidget(button)


def _ok_cancel(dialog: QDialog, footer: QHBoxLayout, ok_text: str | None = None) -> None:
    ok = _dialog_button(ok_text or tr("OKButton"), primary=True)
    ok.clicked.connect(dialog.accept)
    cancel = _dialog_button(tr("CancelButton"))
    cancel.clicked.connect(dialog.reject)
    _add_buttons(footer, ok, cancel)


def _body_text(text: str, parent: QWidget | None = None) -> QLabel:
    widget = label(text, "", parent, wrap=True)
    font = widget.font()
    font.setPixelSize(14)
    widget.setFont(font)
    return widget


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
        layout, footer = _dialog_layout(self, title, kind=kind, title_style="sectionTitle")
        text = _body_text(message, self)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.setContentsMargins(36, 0, 0, 6)
        layout.addWidget(text)
        widgets = []
        for index, key in enumerate(buttons):
            button = _dialog_button(tr(key), primary=index == 0)
            button.clicked.connect(lambda _=False, i=index: self._clicked(i))
            widgets.append(button)
        _add_buttons(footer, *widgets)

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
        self.setMinimumWidth(440)
        layout, footer = _dialog_layout(self, title, title_style="sectionTitle")
        layout.addWidget(_body_text(prompt, self))
        editor.setMinimumHeight(34)
        layout.addWidget(editor)
        _ok_cancel(self, footer)
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
        self.resize(520, 340)
        layout, footer = _dialog_layout(self, title, title_style="sectionTitle")
        layout.addWidget(_body_text(prompt, self))
        self.editor = QPlainTextEdit(text)
        layout.addWidget(self.editor, 1)
        _ok_cancel(self, footer)

    def value(self) -> str:
        return self.editor.toPlainText()


def ask_multiline(parent: QWidget | None, title: str, prompt: str, text: str = "") -> str | None:
    dialog = MultilineDialog(parent, title, prompt, text)
    return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None


class DeleteConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, mod_name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("DeleteModTitle"))
        self.setMinimumWidth(460)
        layout, footer = _dialog_layout(
            self, tr("DeleteModTitle"), kind="warning", title_style="sectionTitle"
        )
        layout.addWidget(_body_text(tr("DeleteModMessage"), self))
        card = Card(self)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        icon = QLabel(card)
        icon.setFixedSize(20, 20)
        icon.setPixmap(icons.pixmap("archive", current_palette().text_secondary, 20))
        row.addWidget(icon)
        row.addWidget(label(mod_name, "cardTitle", card, wrap=True), 1)
        layout.addWidget(card)
        self.dont_ask = QCheckBox(tr("DontAskAgain"))
        yes = _dialog_button(tr("YesButton"), primary=True)
        yes.clicked.connect(self.accept)
        no = _dialog_button(tr("NoButton"))
        no.clicked.connect(self.reject)
        _add_buttons(footer, yes, no, leading=self.dont_ask)


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
        layout, footer = _dialog_layout(self, tr("SelectGameTitle"), subtitle=tr("SelectGameMessage"))
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(20)
        layout.addLayout(self._cards_layout, 1)
        cancel = _dialog_button(tr("CancelButton"))
        cancel.clicked.connect(self.reject)
        _add_buttons(footer, cancel, leading=label(tr("ClickCardToSelect"), "hint", self))
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
        self.setMinimumWidth(460)
        self._create = create
        layout, footer = _dialog_layout(
            self, tr("AssignCategoryTitle"), title_style="sectionTitle", spacing=6
        )
        layout.addWidget(label(tr("AssignCategoryLabel"), "fieldLabel", self))
        self.combo = QComboBox()
        self.combo.setMinimumHeight(34)
        self.combo.addItem(tr("UncategorizedText"), None)
        for category in categories:
            self.combo.addItem(category.name, category.id)
        index = self.combo.findData(current) if current else 0
        self.combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.combo)
        layout.addSpacing(12)
        layout.addWidget(label(tr("AssignCategoryCreateLabel"), "fieldLabel", self))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.new_name = QLineEdit()
        self.new_name.setMinimumHeight(34)
        self.new_name.returnPressed.connect(self._create_category)
        row.addWidget(self.new_name, 1)
        create_button = secondary_button(tr("AssignCategoryCreateButton"), "add")
        create_button.setMinimumHeight(34)
        create_button.clicked.connect(self._create_category)
        row.addWidget(create_button)
        layout.addLayout(row)
        _ok_cancel(self, footer, tr("AssignCategorySaveButton"))

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
        self.setMinimumWidth(460)
        layout, footer = _dialog_layout(
            self,
            tr("CategoryDeleteTitle"),
            subtitle=category.name,
            kind="warning",
            title_style="sectionTitle",
        )
        layout.addWidget(_body_text(tr("CategoryDeleteMessage"), self))
        card = Card(self)
        options = QVBoxLayout(card)
        options.setContentsMargins(14, 12, 14, 12)
        options.setSpacing(8)
        self.unassign = QRadioButton(tr("CategoryDeleteUnassign"), card)
        self.unassign.setChecked(True)
        options.addWidget(self.unassign)
        self.move_to = QRadioButton(tr("CategoryDeleteMoveTo"), card)
        options.addWidget(self.move_to)
        self.target = QComboBox(card)
        self.target.setMinimumHeight(34)
        for other in others:
            self.target.addItem(other.name, other.id)
        self.target.setEnabled(False)
        self.move_to.setEnabled(bool(others))
        self.move_to.toggled.connect(self.target.setEnabled)
        options.addWidget(self.target)
        layout.addWidget(card)
        _ok_cancel(self, footer, tr("CategoryDeleteConfirm"))

    def target_id(self) -> str | None:
        return str(self.target.currentData()) if self.move_to.isChecked() and self.target.count() else None


class CategoryManagerDialog(QDialog):
    """Edit a copy of the category list; ``result_categories``/``reassign`` are read after accept."""

    def __init__(
        self, parent: QWidget | None, categories: Sequence[ModCategory], usage: dict[str, int]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("CategoryManagerTitle"))
        self.resize(560, 520)
        self.setMinimumSize(480, 420)
        self.result_categories = [copy.copy(c) for c in cat.sorted_categories(categories)]
        self.reassign: dict[str, str | None] = {}
        self._usage = usage
        layout, footer = _dialog_layout(self, tr("CategoryManagerTitle"), subtitle=tr("CategoryManagerHint"))
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for text, icon_name, slot in (
            (tr("CategoryManagerCreate"), "add", self._create),
            (tr("CategoryManagerRename"), "rename", self._rename),
            (tr("CategoryManagerDelete"), "delete", self._delete),
        ):
            button = secondary_button(text, icon_name, self)
            button.setMinimumHeight(32)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        up = IconButton("up", "success", tr("ToolTipMoveUp"), self)
        up.clicked.connect(lambda: self._shift(-1))
        down = IconButton("down", "accent_text", tr("ToolTipMoveDown"), self)
        down.clicked.connect(lambda: self._shift(1))
        toolbar.addWidget(up)
        toolbar.addWidget(down)
        layout.addLayout(toolbar)
        card = Card(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(0)
        self.list = QListWidget(card)
        self.list.setObjectName("cardList")
        self.list.setIconSize(QSize(18, 18))
        self.list.itemDoubleClicked.connect(lambda _item: self._rename())
        card_layout.addWidget(self.list, 1)
        self.empty = label(tr("CategoryManagerEmpty"), "hint", card, wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(12, 24, 12, 24)
        card_layout.addWidget(self.empty)
        layout.addWidget(card, 1)
        _ok_cancel(self, footer, tr("CategoryManagerSave"))
        self._refresh()

    def _refresh(self, select: int | None = None) -> None:
        self.list.clear()
        tag = icons.icon("tag", current_palette().text_secondary)
        for category in self.result_categories:
            count = self._usage.get(category.id, 0)
            item = QListWidgetItem(tag, f"{category.name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, category.id)
            item.setSizeHint(QSize(0, 40))
            self.list.addItem(item)
        self.list.setVisible(bool(self.result_categories))
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
        self.resize(860, 560)
        layout, footer = _dialog_layout(
            self,
            tr("ConflictCheckerTitle"),
            subtitle=tr("ConflictCheckerSubtitle", len(conflicts))
            if conflicts
            else tr("ConflictCheckerEmpty"),
            kind="warning" if conflicts else "success",
        )
        card = Card(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        tree = QTreeWidget(card)
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
        _add_buttons(footer, close)


# --------------------------------------------------------------------------- progress


class BusyDialog(QDialog):
    """Modal "please wait" with a cancel button (used for Nexus login)."""

    cancelled = Signal()

    def __init__(self, parent: QWidget | None, title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        layout, footer = _dialog_layout(self, title, title_style="sectionTitle", spacing=14)
        layout.addWidget(_body_text(message, self))
        bar = QProgressBar(self)
        bar.setRange(0, 0)
        bar.setFixedHeight(6)
        layout.addWidget(bar)
        cancel = _dialog_button(tr("CancelButton"))
        cancel.clicked.connect(self.reject)
        _add_buttons(footer, cancel)
        self.rejected.connect(self.cancelled.emit)

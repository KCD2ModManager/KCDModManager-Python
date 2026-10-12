"""Mod list: item model (with internal drag & drop) and the painted row delegate."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)

from kcd_mod_manager.domain.models import Mod
from kcd_mod_manager.i18n import tr
from kcd_mod_manager.ui import icons
from kcd_mod_manager.ui.theme import Palette

MOD_ROLE = Qt.ItemDataRole.UserRole + 1
MIME_TYPE = "application/x-kcdmm-mod-id"

ModelIndex = QModelIndex | QPersistentModelIndex


class ModListModel(QAbstractListModel):
    move_requested = Signal(str, int)
    """(mod id, target row among the visible mods)"""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._mods: list[Mod] = []
        self.reorder_allowed = True

    @property
    def mods(self) -> list[Mod]:
        return self._mods

    def set_mods(self, mods: Sequence[Mod]) -> None:
        self.beginResetModel()
        self._mods = list(mods)
        self.endResetModel()

    def refresh_rows(self) -> None:
        if self._mods:
            self.dataChanged.emit(self.index(0), self.index(len(self._mods) - 1))

    def mod_at(self, row: int) -> Mod | None:
        return self._mods[row] if 0 <= row < len(self._mods) else None

    def row_of(self, mod: Mod) -> int:
        try:
            return self._mods.index(mod)
        except ValueError:
            return -1

    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._mods)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        mod = self.mod_at(index.row()) if index.isValid() else None
        if mod is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return mod.name
        if role == MOD_ROLE:
            return mod
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{mod.name} {mod.version}"
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not index.isValid():
            return base | Qt.ItemFlag.ItemIsDropEnabled if self.reorder_allowed else base
        if self.reorder_allowed:
            base |= Qt.ItemFlag.ItemIsDragEnabled
        return base

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [MIME_TYPE]

    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        data = QMimeData()
        mod = self.mod_at(indexes[0].row()) if indexes else None
        if mod is not None:
            data.setData(MIME_TYPE, mod.id.encode("utf-8"))
        return data

    def canDropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: ModelIndex
    ) -> bool:
        return self.reorder_allowed and data.hasFormat(MIME_TYPE)

    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: ModelIndex
    ) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        mod_id = bytes(data.data(MIME_TYPE).data()).decode("utf-8")
        source = next((i for i, m in enumerate(self._mods) if m.id == mod_id), -1)
        if source < 0:
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._mods)
        target = row - 1 if row > source else row
        if target != source:
            self.move_requested.emit(mod_id, target)
        # The move is applied by the window (persisted, then the model is reset); returning False
        # keeps Qt from removing the source row itself.
        return False


# --------------------------------------------------------------------------- delegate
ROW_HEIGHT = 60
ROW_MARGIN_X, ROW_MARGIN_Y = 0, 3
PAD_X = 14
SELECTION_BAR = 3
BUTTON_SIZE = 28
BUTTON_GAP = 2
ICON_SIZE = 16
VERSION_WIDTH = 72
DISABLED_OPACITY = 0.6

BUTTON_COLORS = {
    "update": "accent_text",
    "up": "success",
    "down": "accent_text",
    "delete": "error",
    "folder": "text_secondary",
    "more": "text_secondary",
}
BUTTON_ICONS = {
    "update": "update",
    "up": "up",
    "down": "down",
    "delete": "delete",
    "folder": "folder",
    "more": "more",
}


@dataclass(slots=True)
class RowLayout:
    card: QRect
    checkbox: QRect
    warning: QRect
    text: QRect
    version: QRect
    buttons: dict[str, QRect] = field(default_factory=dict)


ButtonPredicate = Callable[[Mod, str], bool]


def _font(base: QFont, pixels: int, *, bold: bool = False, italic: bool = False) -> QFont:
    font = QFont(base)
    font.setPixelSize(pixels)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    font.setItalic(italic)
    return font


class ModDelegate(QStyledItemDelegate):
    toggled = Signal(object)
    action = Signal(str, object, QPoint)
    """(action name, mod, global position for menus)"""

    BUTTONS = ("update", "up", "down", "delete", "folder", "more")

    def __init__(self, view: QListView, palette: Palette, dark: bool) -> None:
        super().__init__(view)
        self._view = view
        self.palette = palette
        self.dark = dark
        self.button_enabled: ButtonPredicate = lambda _mod, _name: True
        self._pressed: tuple[int, str] | None = None

    def set_theme(self, palette: Palette, dark: bool) -> None:
        self.palette, self.dark = palette, dark

    # ------------------------------------------------------------------ geometry
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        return QSize(400, ROW_HEIGHT)

    def layout(self, rect: QRect, mod: Mod) -> RowLayout:
        card = rect.adjusted(ROW_MARGIN_X, ROW_MARGIN_Y, -ROW_MARGIN_X, -ROW_MARGIN_Y)
        cy = card.center().y()
        checkbox = QRect(card.left() + PAD_X, cy - 9, 18, 18)
        warning = QRect(checkbox.right() + 7, cy - 9, 18 if not mod.is_compatible else 0, 18)
        buttons: dict[str, QRect] = {}
        x = card.right() - PAD_X + 3
        for name in reversed(self.BUTTONS):
            if name == "update" and not mod.has_update:
                continue
            x -= BUTTON_SIZE
            buttons[name] = QRect(x, cy - BUTTON_SIZE // 2, BUTTON_SIZE, BUTTON_SIZE)
            x -= BUTTON_GAP
        version = QRect(x - VERSION_WIDTH - 6, card.top(), VERSION_WIDTH, card.height())
        text_left = (warning.right() if warning.width() else checkbox.right()) + 9
        text = QRect(text_left, card.top() + 5, max(10, version.left() - text_left - 10), card.height() - 10)
        return RowLayout(card, checkbox, warning, text, version, buttons)

    # ------------------------------------------------------------------ painting
    def _background(self, mod: Mod, state: QStyle.StateFlag) -> QColor:
        p = self.palette
        if state & QStyle.StateFlag.State_Selected:
            return QColor(p.menu_highlight)
        if state & QStyle.StateFlag.State_MouseOver:
            return QColor(p.row_hover)
        if mod.highlight is not None:
            return QColor(mod.highlight.for_theme(self.dark))
        return QColor(p.panel)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        mod = index.data(MOD_ROLE)
        if not isinstance(mod, Mod):
            return
        p = self.palette
        rect: QRect = option.rect  # type: ignore[attr-defined]
        state = option.state  # type: ignore[attr-defined]
        base_font = QFont(option.font)  # type: ignore[attr-defined]
        lay = self.layout(rect, mod)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        selected = bool(state & QStyle.StateFlag.State_Selected)
        card = QRectF(lay.card).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(p.accent_text if selected else p.separator), 1))
        painter.setBrush(self._background(mod, state))
        painter.drawRoundedRect(card, 4, 4)
        if selected:
            bar = QPainterPath()
            bar.addRoundedRect(card, 4, 4)
            painter.save()
            painter.setClipPath(bar)
            painter.fillRect(
                QRectF(card.left(), card.top(), SELECTION_BAR, card.height()), QColor(p.accent_text)
            )
            painter.restore()

        content_opacity = 1.0 if mod.is_enabled else DISABLED_OPACITY
        painter.setOpacity(content_opacity)
        self._paint_checkbox(painter, lay.checkbox, mod.is_enabled)
        if not mod.is_compatible:
            icons.paint(painter, "warning_filled", lay.warning, p.warning, ICON_SIZE)
        self._paint_text(painter, lay, mod, base_font)

        version_font = _font(base_font, 12, italic=True)
        painter.setFont(version_font)
        painter.setPen(QColor(p.text_secondary))
        painter.drawText(
            lay.version,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(version_font).elidedText(
                mod.version or "", Qt.TextElideMode.ElideLeft, lay.version.width()
            ),
        )
        painter.setOpacity(1.0)
        self._paint_buttons(painter, lay, mod, index.row(), selected)

        if mod.has_separator_after:
            painter.setPen(QPen(QColor(p.accent_text), 2))
            y = rect.bottom()
            painter.drawLine(rect.left() + 12, y, rect.right() - 12, y)
        painter.restore()

    def _paint_text(self, painter: QPainter, lay: RowLayout, mod: Mod, base_font: QFont) -> None:
        p = self.palette
        name_font = _font(base_font, 14)
        small = _font(base_font, 12)
        badge_font = _font(base_font, 10)
        fm = QFontMetrics(name_font)
        has_subtitle = bool(mod.category_name)
        name_height = fm.height()
        block = name_height + (QFontMetrics(small).height() + 1 if has_subtitle else 0)
        top = lay.text.top() + (lay.text.height() - block) // 2
        name_rect = QRect(lay.text.left(), top, lay.text.width(), name_height)

        badge_text = tr("WorkshopBadgeText")
        badge_fm = QFontMetrics(badge_font)
        badge_width = badge_fm.horizontalAdvance(badge_text) + 12 if mod.is_workshop_mod else 0
        elided = fm.elidedText(
            mod.name, Qt.TextElideMode.ElideRight, max(10, name_rect.width() - badge_width - 8)
        )
        painter.setFont(name_font)
        painter.setPen(QColor(p.text if mod.is_enabled else p.text_disabled))
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        if mod.is_workshop_mod:
            badge_height = badge_fm.height() + 4
            badge = QRectF(
                name_rect.left() + fm.horizontalAdvance(elided) + 8,
                name_rect.center().y() - badge_height / 2 + 1,
                badge_width,
                badge_height,
            )
            painter.setPen(QPen(QColor(p.separator), 1))
            painter.setBrush(QColor(p.panel))
            painter.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), badge_height / 2, badge_height / 2)
            painter.setPen(QColor(p.text_secondary))
            painter.setFont(badge_font)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, badge_text)

        if has_subtitle:
            sub_rect = QRect(lay.text.left(), name_rect.bottom() + 1, lay.text.width(), lay.text.height())
            painter.setFont(small)
            painter.setPen(QColor(p.text_secondary))
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                QFontMetrics(small).elidedText(
                    mod.category_name or "", Qt.TextElideMode.ElideRight, sub_rect.width()
                ),
            )

    def _paint_buttons(self, painter: QPainter, lay: RowLayout, mod: Mod, row: int, selected: bool) -> None:
        p = self.palette
        cursor = self._view.viewport().mapFromGlobal(QCursor.pos())
        for name, button in lay.buttons.items():
            enabled = self.button_enabled(mod, name)
            if enabled and button.contains(cursor):
                fill = QColor(p.row_hover if selected else p.selected)
                if self._pressed == (row, name):
                    fill = fill.darker(112)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(button), 4, 4)
            color = str(getattr(p, BUTTON_COLORS[name]))
            icons.paint(painter, BUTTON_ICONS[name], button, color, ICON_SIZE, 1.0 if enabled else 0.35)

    def _paint_checkbox(self, painter: QPainter, rect: QRect, checked: bool) -> None:
        p = self.palette
        box = QRectF(rect).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setPen(QPen(QColor(p.primary if checked else p.input_border), 1.5))
        painter.setBrush(QColor(p.primary if checked else p.input_bg))
        painter.drawRoundedRect(box, 3, 3)
        if checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2, c=Qt.PenCapStyle.RoundCap, j=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ox, oy = rect.left() + 1, rect.top() + 2
            path = QPainterPath(QPointF(ox + 3, oy + 7))
            path.lineTo(QPointF(ox + 7, oy + 11))
            path.lineTo(QPointF(ox + 13, oy + 3))
            painter.drawPath(path)

    # ------------------------------------------------------------------ interaction
    def editorEvent(
        self, event: QEvent, model: object, option: QStyleOptionViewItem, index: ModelIndex
    ) -> bool:
        mod = index.data(MOD_ROLE)
        if not isinstance(mod, Mod):
            return False
        if event.type() == QEvent.Type.MouseMove:
            self._view.viewport().update()
            return False
        if not isinstance(event, QMouseEvent) or event.button() != Qt.MouseButton.LeftButton:
            return False
        pos = event.position().toPoint()
        lay = self.layout(option.rect, mod)  # type: ignore[attr-defined]
        if event.type() == QEvent.Type.MouseButtonPress:
            for name, button in lay.buttons.items():
                if button.contains(pos) and self.button_enabled(mod, name):
                    self._pressed = (index.row(), name)
                    self._view.viewport().update(option.rect)  # type: ignore[attr-defined]
                    return True
            return False
        if event.type() not in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return False
        self._pressed = None
        self._view.viewport().update(option.rect)  # type: ignore[attr-defined]
        if lay.checkbox.adjusted(-4, -4, 4, 4).contains(pos):
            if event.type() == QEvent.Type.MouseButtonRelease:
                self.toggled.emit(mod)
            return True
        for name, button in lay.buttons.items():
            if button.contains(pos):
                if event.type() == QEvent.Type.MouseButtonRelease and self.button_enabled(mod, name):
                    global_pos = self._view.viewport().mapToGlobal(button.bottomLeft())
                    self.action.emit(name, mod, global_pos)
                return True
        return False

    def helpEvent(
        self, event: QHelpEvent, view: QAbstractItemView, option: QStyleOptionViewItem, index: ModelIndex
    ) -> bool:
        mod = index.data(MOD_ROLE)
        if not isinstance(mod, Mod) or event.type() != QEvent.Type.ToolTip:
            return super().helpEvent(event, view, option, index)
        lay = self.layout(option.rect, mod)  # type: ignore[attr-defined]
        pos = event.pos()
        tips = {
            "update": tr("ToolTipUpdateAvailable")
            + (f" ({mod.latest_version})" if mod.latest_version else ""),
            "up": tr("ToolTipMoveUp"),
            "down": tr("ToolTipMoveDown"),
            "delete": tr("ToolTipDeleteMod"),
            "folder": tr("ToolTipOpenFolder"),
            "more": tr("ToolTipMoreOptions"),
        }
        text = ""
        for name, button in lay.buttons.items():
            if button.contains(pos):
                text = tips[name]
        if not text and not mod.is_compatible and lay.warning.contains(pos):
            text = f"gameVersion: {mod.game_version or '?'}"
        if not text and lay.text.contains(pos):
            parts = [mod.name]
            if mod.is_workshop_mod:
                parts.append(tr("WorkshopBadgeTooltip"))
            if mod.note:
                parts.append(mod.note)
            text = "\n".join(parts)
        if text:
            QToolTip.showText(event.globalPos(), text, view)
            return True
        QToolTip.hideText()
        return True

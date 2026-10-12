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
ROW_HEIGHT = 50
BUTTON_SIZE = 26
BUTTON_GAP = 3
VERSION_WIDTH = 120


@dataclass(slots=True)
class RowLayout:
    checkbox: QRect
    warning: QRect
    text: QRect
    version: QRect
    buttons: dict[str, QRect] = field(default_factory=dict)


ButtonPredicate = Callable[[Mod, str], bool]


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

    def set_theme(self, palette: Palette, dark: bool) -> None:
        self.palette, self.dark = palette, dark

    # ------------------------------------------------------------------ geometry
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        return QSize(400, ROW_HEIGHT)

    def layout(self, rect: QRect, mod: Mod) -> RowLayout:
        cy = rect.center().y()
        checkbox = QRect(rect.left() + 10, cy - 9, 18, 18)
        warning = QRect(checkbox.right() + 6, cy - 9, 18, 18)
        buttons: dict[str, QRect] = {}
        x = rect.right() - 8
        for name in reversed(self.BUTTONS):
            if name == "update" and not mod.has_update:
                continue
            x -= BUTTON_SIZE
            buttons[name] = QRect(x, cy - BUTTON_SIZE // 2, BUTTON_SIZE, BUTTON_SIZE)
            x -= BUTTON_GAP
        version = QRect(x - VERSION_WIDTH, rect.top(), VERSION_WIDTH - 8, rect.height())
        text_left = warning.right() + 6
        text = QRect(text_left, rect.top() + 4, max(10, version.left() - text_left - 8), rect.height() - 8)
        return RowLayout(checkbox, warning, text, version, buttons)

    # ------------------------------------------------------------------ painting
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        mod = index.data(MOD_ROLE)
        if not isinstance(mod, Mod):
            return
        p = self.palette
        rect: QRect = option.rect  # type: ignore[attr-defined]
        state = option.state  # type: ignore[attr-defined]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if state & QStyle.StateFlag.State_Selected:
            background = QColor(p.selected)
        elif mod.highlight is not None:
            background = QColor(mod.highlight.for_theme(self.dark))
        elif state & QStyle.StateFlag.State_MouseOver:
            background = QColor(p.row_hover)
        else:
            background = QColor(p.row_even if index.row() % 2 == 0 else p.row_odd)
        painter.fillRect(rect, background)

        lay = self.layout(rect, mod)
        self._paint_checkbox(painter, lay.checkbox, mod.is_enabled)
        if not mod.is_compatible:
            painter.setPen(QColor(p.warning))
            font = QFont(option.font)  # type: ignore[attr-defined]
            font.setPointSizeF(font.pointSizeF() + 2)
            painter.setFont(font)
            painter.drawText(lay.warning, Qt.AlignmentFlag.AlignCenter, "\u26a0")

        base_font = QFont(option.font)  # type: ignore[attr-defined]
        name_font = QFont(base_font)
        name_font.setPointSizeF(base_font.pointSizeF() + 1)
        name_font.setBold(mod.is_enabled)
        fm = QFontMetrics(name_font)
        has_subtitle = bool(mod.category_name)
        name_rect = QRect(lay.text)
        if has_subtitle:
            name_rect.setHeight(lay.text.height() // 2 + 2)
        painter.setFont(name_font)
        painter.setPen(QColor(p.text if mod.is_enabled else p.text_secondary))
        badge_width = 0
        badge_text = tr("WorkshopBadgeText")
        small = QFont(base_font)
        small.setPointSizeF(max(6.0, base_font.pointSizeF() - 1))
        if mod.is_workshop_mod:
            badge_width = QFontMetrics(small).horizontalAdvance(badge_text) + 14
        flags = Qt.AlignmentFlag.AlignLeft | (
            Qt.AlignmentFlag.AlignBottom if has_subtitle else Qt.AlignmentFlag.AlignVCenter
        )
        elided = fm.elidedText(
            mod.name, Qt.TextElideMode.ElideRight, max(10, name_rect.width() - badge_width)
        )
        painter.drawText(name_rect, flags, elided)
        if mod.is_workshop_mod:
            text_width = fm.horizontalAdvance(elided)
            badge_height = QFontMetrics(small).height() + 2
            top = (
                name_rect.bottom() - badge_height - 1
                if has_subtitle
                else name_rect.center().y() - badge_height // 2
            )
            badge = QRect(name_rect.left() + text_width + 8, top, badge_width - 6, badge_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.primary))
            painter.drawRoundedRect(badge, badge_height / 2, badge_height / 2)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(small)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, badge_text)
        if has_subtitle:
            sub_rect = QRect(
                lay.text.left(), name_rect.bottom() + 2, lay.text.width(), lay.text.height() // 2
            )
            painter.setFont(small)
            painter.setPen(QColor(p.text_secondary))
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                QFontMetrics(small).elidedText(
                    mod.category_name or "", Qt.TextElideMode.ElideRight, sub_rect.width()
                ),
            )

        version_font = QFont(base_font)
        version_font.setItalic(True)
        painter.setFont(version_font)
        painter.setPen(QColor(p.text_secondary))
        version = mod.version or ""
        painter.drawText(
            lay.version,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(version_font).elidedText(version, Qt.TextElideMode.ElideLeft, lay.version.width()),
        )

        cursor = self._view.viewport().mapFromGlobal(QCursor.pos())
        for name, button in lay.buttons.items():
            enabled = self.button_enabled(mod, name)
            hovered = enabled and button.contains(cursor)
            if hovered:
                painter.setPen(QPen(QColor(p.primary), 1))
                painter.setBrush(QColor(p.row_hover))
                painter.drawRoundedRect(button, 4, 4)
            color = QColor(p.text if enabled else p.text_disabled)
            if name == "update":
                color = QColor(p.success)
            if name == "delete" and enabled and hovered:
                color = QColor(p.error)
            draw_icon(painter, name, button, color)

        if mod.has_separator_after:
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawLine(rect.left() + 6, rect.bottom() - 1, rect.right() - 6, rect.bottom() - 1)
        else:
            painter.setPen(QPen(QColor(p.separator), 1))
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.restore()

    def _paint_checkbox(self, painter: QPainter, rect: QRect, checked: bool) -> None:
        p = self.palette
        painter.setPen(QPen(QColor(p.primary if checked else p.input_border), 1.5))
        painter.setBrush(QColor(p.primary if checked else p.input_bg))
        painter.drawRoundedRect(rect, 3, 3)
        if checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.2, c=Qt.PenCapStyle.RoundCap))
            path = QPainterPath()
            path.moveTo(QPointF(rect.left() + 4, rect.center().y()))
            path.lineTo(QPointF(rect.left() + 7.5, rect.bottom() - 4))
            path.lineTo(QPointF(rect.right() - 3.5, rect.top() + 4.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    # ------------------------------------------------------------------ interaction
    def editorEvent(
        self, event: QEvent, model: object, option: QStyleOptionViewItem, index: ModelIndex
    ) -> bool:
        mod = index.data(MOD_ROLE)
        if not isinstance(mod, Mod):
            return False
        if event.type() == QEvent.Type.MouseMove:
            self._view.viewport().update(option.rect)  # type: ignore[attr-defined]
            return False
        if event.type() not in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return False
        if not isinstance(event, QMouseEvent) or event.button() != Qt.MouseButton.LeftButton:
            return False
        pos = event.position().toPoint()
        lay = self.layout(option.rect, mod)  # type: ignore[attr-defined]
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


def draw_icon(painter: QPainter, name: str, rect: QRect, color: QColor) -> None:
    """Small vector glyphs so icons follow the theme colours on every platform."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QPointF(rect.center())
    s = rect.width() / 2 - 7
    pen = QPen(color, 1.8, c=Qt.PenCapStyle.RoundCap, j=Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if name == "up":
        path.moveTo(c.x() - s, c.y() + s / 2)
        path.lineTo(c.x(), c.y() - s / 2)
        path.lineTo(c.x() + s, c.y() + s / 2)
    elif name == "down":
        path.moveTo(c.x() - s, c.y() - s / 2)
        path.lineTo(c.x(), c.y() + s / 2)
        path.lineTo(c.x() + s, c.y() - s / 2)
    elif name == "delete":
        path.moveTo(c.x() - s, c.y() - s)
        path.lineTo(c.x() + s, c.y() + s)
        path.moveTo(c.x() + s, c.y() - s)
        path.lineTo(c.x() - s, c.y() + s)
    elif name == "folder":
        path.moveTo(c.x() - s - 1, c.y() + s)
        path.lineTo(c.x() - s - 1, c.y() - s + 1)
        path.lineTo(c.x() - 1, c.y() - s + 1)
        path.lineTo(c.x() + 1, c.y() - s + 3)
        path.lineTo(c.x() + s + 1, c.y() - s + 3)
        path.lineTo(c.x() + s + 1, c.y() + s)
        path.closeSubpath()
    elif name == "more":
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        for dx in (-s, 0.0, s):
            painter.drawEllipse(QPointF(c.x() + dx, c.y()), 1.8, 1.8)
    elif name == "update":
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(c, s + 3, s + 3)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.8, c=Qt.PenCapStyle.RoundCap, j=Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path.moveTo(c.x(), c.y() - s + 1)
        path.lineTo(c.x(), c.y() + s - 1)
        path.moveTo(c.x() - s / 1.5, c.y() + 1)
        path.lineTo(c.x(), c.y() + s - 1)
        path.lineTo(c.x() + s / 1.5, c.y() + 1)
    painter.drawPath(path)
    painter.restore()

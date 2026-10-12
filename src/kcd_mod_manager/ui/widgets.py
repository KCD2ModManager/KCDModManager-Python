"""Reusable themed widgets that reproduce the controls of the original WPF manager."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kcd_mod_manager.ui import icons
from kcd_mod_manager.ui.theme import Palette, current_palette


def resolve(color: str, palette: Palette | None = None) -> str:
    """A literal ``#rrggbb`` or the name of a :class:`Palette` field."""
    if color.startswith("#"):
        return color
    return str(getattr(palette or current_palette(), color))


# --------------------------------------------------------------------------- themed icons
class ThemedIcon(QObject):
    """Keeps a button's icon in the current theme's colour (re-applied on every theme switch)."""

    def __init__(
        self,
        target: QAbstractButton,
        name: str,
        color: str = "text",
        size: int = 16,
        disabled: str = "text_disabled",
    ) -> None:
        super().__init__(target)
        self._target = target
        self.name, self.color, self.size, self.disabled = name, color, size, disabled
        target.setIconSize(QSize(size, size))
        target.installEventFilter(self)
        self.apply()

    def set(self, name: str | None = None, color: str | None = None) -> None:
        self.name = name or self.name
        self.color = color or self.color
        self.apply()

    def apply(self) -> None:
        p = current_palette()
        self._target.setIcon(
            icons.icon(self.name, resolve(self.color, p), resolve(self.disabled, p), self.size)
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.apply()
        return False


def themed_icon(button: QAbstractButton, name: str, color: str = "text", size: int = 16) -> ThemedIcon:
    existing = button.findChild(ThemedIcon)
    if existing is not None:
        existing.set(name, color)
        return existing
    return ThemedIcon(button, name, color, size)


def refresh_theme(root: QWidget) -> None:
    """Re-apply theme-dependent icons and repaint custom-painted widgets below ``root``."""
    for binder in root.findChildren(ThemedIcon):
        binder.apply()
    for widget in root.findChildren(QWidget):
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            refresh()
        widget.update()


# --------------------------------------------------------------------------- buttons
class IconButton(QToolButton):
    """Transparent 28x28 action button with a coloured 16px Fluent glyph (WPF ActionButtonStyle)."""

    def __init__(
        self, name: str, color: str = "text_secondary", tooltip: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("iconButton")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAutoRaise(True)
        self.binder = ThemedIcon(self, name, color)


def primary_button(text: str, icon_name: str | None = None, parent: QWidget | None = None) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName("primary")
    button.setMinimumHeight(40)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        ThemedIcon(button, icon_name, "#FFFFFF", 18)
    return button


def secondary_button(text: str, icon_name: str | None = None, parent: QWidget | None = None) -> QPushButton:
    button = QPushButton(text, parent)
    button.setMinimumHeight(28)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        ThemedIcon(button, icon_name, "text", 14)
    return button


class ToggleSwitch(QAbstractButton):
    """50x25 pill switch with a sliding knob (WPF ModernToggleSwitchStyle)."""

    WIDTH, HEIGHT, KNOB = 50, 25, 19

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._offset = 0.0
        self._hover = False
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, self.HEIGHT)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        if self.isVisible():
            self._animation.start()
        else:
            self._set_offset(1.0 if checked else 0.0)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        target = 1.0 if self.isChecked() else 0.0
        if self._animation.state() != QPropertyAnimation.State.Running and self._offset != target:
            self._offset = target
        p = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off, on = QColor(p.toggle_off), QColor(p.toggle_on)
        t = self._offset
        color = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
        )
        if self._hover and self.isEnabled():
            color = color.lighter(108) if t < 0.5 else color.darker(106)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.accent_text), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius = track.height() / 2
            painter.drawRoundedRect(track.adjusted(-0.5, -0.5, 0.5, 0.5), radius, radius)
        margin = (self.height() - self.KNOB) / 2
        x = margin + t * (self.width() - 2 * margin - self.KNOB)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(x, margin + 0.8, self.KNOB, self.KNOB))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, margin, self.KNOB, self.KNOB))
        painter.end()


# --------------------------------------------------------------------------- badges
class Pill(QWidget):
    """Rounded badge: ``success`` (mods counter), ``warning`` (conflicts), ``premium``, ``neutral``."""

    clicked = Signal()

    STYLES: dict[str, tuple[int, int, int, float, int]] = {
        # variant: (horizontal padding, vertical padding, pixel size, radius (<1: fraction of height), weight)
        "success": (12, 6, 13, 0.5, QFont.Weight.DemiBold),
        "warning": (7, 1, 11, 0.5, QFont.Weight.Bold),
        "premium": (6, 2, 10, 4, QFont.Weight.Bold),
        "neutral": (6, 2, 10, 0.5, QFont.Weight.Normal),
    }

    def __init__(self, text: str = "", variant: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.variant = variant
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if variant == "premium":
            glow = QGraphicsDropShadowEffect(self)
            glow.setColor(QColor(255, 165, 0, 150))
            glow.setBlurRadius(10)
            glow.setOffset(0, 0)
            self.setGraphicsEffect(glow)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def _font(self) -> QFont:
        *_, pixel, _radius, weight = self.STYLES[self.variant]
        font = QFont(self.font())
        font.setPixelSize(pixel)
        font.setWeight(QFont.Weight(weight))
        return font

    def sizeHint(self) -> QSize:
        pad_x, pad_y, *_ = self.STYLES[self.variant]
        fm = QFontMetrics(self._font())
        height = fm.height() + 2 * pad_y
        return QSize(max(fm.horizontalAdvance(self._text) + 2 * pad_x, height), height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def colors(self, p: Palette) -> tuple[str, str, str | None]:
        if self.variant == "success":
            return p.success, "#FFFFFF" if p.success == "#107C10" else "#0F2E1C", None
        if self.variant == "warning":
            return p.warning, "#1A1A1A", None
        if self.variant == "premium":
            return "#FFD700", "#1A1A1A", "#FF8C00"
        return p.panel, p.text_secondary, p.separator

    def mouseReleaseEvent(self, event: object) -> None:
        self.clicked.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = current_palette()
        background, foreground, border = self.colors(p)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius_spec = self.STYLES[self.variant][3]
        radius = rect.height() * radius_spec if radius_spec < 1 else radius_spec
        if self.variant == "premium":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, QColor("#FFD700"))
            gradient.setColorAt(1, QColor("#FFA500"))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 1) if border else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QColor(foreground))
        painter.setFont(self._font())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


# --------------------------------------------------------------------------- inputs
class SearchBox(QLineEdit):
    """Search field with a leading magnifier and a clear glyph shown only while text is present."""

    def __init__(self, placeholder: str = "", clear_tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("search")
        self.setPlaceholderText(placeholder)
        self._search_action = QAction(self)
        self.addAction(self._search_action, QLineEdit.ActionPosition.LeadingPosition)
        self.clear_action = QAction(self)
        self.clear_action.setToolTip(clear_tooltip)
        self.clear_action.triggered.connect(self.clear)
        self.addAction(self.clear_action, QLineEdit.ActionPosition.TrailingPosition)
        self.textChanged.connect(lambda text: self.clear_action.setVisible(bool(text)))
        self.clear_action.setVisible(False)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        p = current_palette()
        self._search_action.setIcon(icons.icon("search", p.text_secondary))
        self.clear_action.setIcon(icons.icon("dismiss", p.text_secondary))

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.StyleChange:
            self.refresh_theme()
        return super().event(event)


# --------------------------------------------------------------------------- menus
class RoundedMenu(QMenu):
    """Context menu with rounded corners (frameless + translucent so the QSS radius shows)."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def add_submenu(self, title: str) -> RoundedMenu:
        menu = RoundedMenu(title, self)
        self.addMenu(menu)
        return menu


# --------------------------------------------------------------------------- containers
class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")


def hline(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("hline")
    line.setFixedHeight(1)
    return line


def footer_bar(parent: QWidget | None = None, margin: int = 24) -> tuple[QFrame, QHBoxLayout]:
    """Panel-coloured bottom bar with a top separator, shared by the main window and all dialogs."""
    bar = QFrame(parent)
    bar.setObjectName("footerBar")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(margin, 12, margin, 12)
    layout.setSpacing(10)
    return bar, layout


def vline(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("vline")
    line.setFixedWidth(1)
    return line


def label(text: str, object_name: str = "", parent: QWidget | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text, parent)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


class LoadingOverlay(QWidget):
    """Covers its parent with a translucent panel, an indeterminate bar and a caption."""

    def __init__(self, parent: QWidget, text: str) -> None:
        super().__init__(parent)
        self._host = parent
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedSize(200, 6)
        self.caption = QLabel(text)
        self.caption.setObjectName("secondary")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.caption.font()
        font.setPixelSize(14)
        self.caption.setFont(font)
        layout.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return False

    def show_overlay(self, text: str | None = None) -> None:
        if text is not None:
            self.caption.setText(text)
        self.setGeometry(self._host.rect())
        self.raise_()
        self.show()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        color = QColor(current_palette().panel)
        color.setAlphaF(0.95)
        painter.fillRect(self.rect(), color)
        painter.end()

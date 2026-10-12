"""Fluent UI System Icons (MIT, bundled as SVG) rendered in any colour and size."""

from __future__ import annotations

import atexit
import shutil
import tempfile
from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from kcd_mod_manager.resources import resource_path

ICON_DIR = resource_path("icons")
_SOURCE_FILL = "#212121"


def available() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


@cache
def _svg(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise KeyError(f"unknown icon: {name}")
    return path.read_text(encoding="utf-8")


def svg_data(name: str, color: str) -> bytes:
    return _svg(name).replace(_SOURCE_FILL, color).encode("utf-8")


def _device_ratio() -> float:
    app = QGuiApplication.instance()
    screen = QGuiApplication.primaryScreen() if app is not None else None
    return max(1.0, screen.devicePixelRatio()) if screen is not None else 1.0


@cache
def _pixmap(name: str, color: str, size: int, ratio: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_data(name, color)))
    pixel = round(size * ratio)
    pixmap = QPixmap(pixel, pixel)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pixel, pixel))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def pixmap(name: str, color: str | QColor, size: int = 16, ratio: float | None = None) -> QPixmap:
    hex_color = color.name() if isinstance(color, QColor) else color
    return _pixmap(name, hex_color, size, ratio if ratio is not None else _device_ratio())


def icon(name: str, color: str | QColor, disabled: str | QColor | None = None, size: int = 16) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Active)
    if disabled is not None:
        result.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled)
    return result


def paint(
    painter: QPainter, name: str, rect: QRect, color: str | QColor, size: int = 16, opacity: float = 1.0
) -> None:
    """Draw an icon centred in ``rect`` (used by the painted mod list)."""
    ratio = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
    pm = pixmap(name, color, size, max(1.0, ratio))
    target = QRect(0, 0, size, size)
    target.moveCenter(rect.center())
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.drawPixmap(target, pm)
    painter.restore()


def swatch(fill: str, border: str, size: int = 14) -> QIcon:
    ratio = _device_ratio()
    pm = QPixmap(round(size * ratio), round(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(border))
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 3, 3)
    painter.end()
    return QIcon(pm)


@cache
def _stylesheet_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="kcdmm-qss-"))
    atexit.register(shutil.rmtree, path, True)
    return path


def stylesheet_url(name: str, color: str) -> str:
    """Write a recoloured SVG for use as a QSS ``url()`` (QSS cannot recolour images itself)."""
    target = _stylesheet_dir() / f"{name}-{color.lstrip('#')}.svg"
    if not target.exists():
        target.write_bytes(svg_data(name, color))
    return target.as_posix()


def icon_size(size: int = 16) -> QSize:
    return QSize(size, size)

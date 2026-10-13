"""Render ``packaging/icon/logo.svg`` into the Windows ``logo.ico`` and the Linux PNG.

    uv run python scripts/make_icon.py

The ICO holds PNG-compressed images (supported since Windows Vista) in the sizes Windows
uses for the taskbar, Explorer and the installer.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packaging" / "icon" / "logo.svg"
ICO = ROOT / "src" / "kcd_mod_manager" / "resources" / "images" / "logo.ico"
LINUX_PNG = ROOT / "packaging" / "linux" / "kcd-mod-manager.png"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def ico(images: dict[int, bytes]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, offset = b"", 6 + 16 * len(images)
    for size, png in images.items():
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + entries + b"".join(images.values())


def main() -> int:
    _app = QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise SystemExit(f"cannot read {SOURCE}")
    ICO.write_bytes(ico({size: render(renderer, size) for size in ICO_SIZES}))
    LINUX_PNG.write_bytes(render(renderer, 256))
    print(f"wrote {ICO.relative_to(ROOT)} and {LINUX_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

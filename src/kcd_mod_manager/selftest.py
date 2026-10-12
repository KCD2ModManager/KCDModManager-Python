"""``--self-test``: verify a (frozen) build can load Qt, its resources and optional backends.

Used by the build script and CI after PyInstaller ran; touches no user data and opens no window.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def run_self_test(report: Path | None = None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    results: dict[str, str] = {}

    def check(name: str, fn: object) -> None:
        try:
            value = fn()  # type: ignore[operator]
            results[name] = f"ok {value}" if value not in (None, True) else "ok"
        except Exception as exc:
            results[name] = f"FAIL {type(exc).__name__}: {exc}"

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from kcd_mod_manager import __version__
    from kcd_mod_manager.i18n import Translator
    from kcd_mod_manager.resources import resource_path

    _app = QApplication.instance() or QApplication(sys.argv[:1])  # must stay alive while checking

    def image(name: str) -> str:
        loaded = QImage(str(resource_path("images", name)))
        if loaded.isNull():
            raise RuntimeError(f"cannot load {name}")
        return f"{loaded.width()}x{loaded.height()}"

    def translations() -> str:
        counts = []
        for language in ("en", "de", "fr"):
            t = Translator(language)
            if t("ButtonStartGame") == "ButtonStartGame":
                raise RuntimeError(f"{language} translations missing")
            counts.append(language)
        return ",".join(counts)

    check("version", lambda: __version__)
    check("qt", lambda: QApplication.platformName())
    check("logo.ico", lambda: image("logo.ico"))
    check("kcd1.jpg", lambda: image("kcd1.jpg"))
    check("kcd2.jpg", lambda: image("kcd2.jpg"))
    check("translations", translations)

    def svg_icons() -> str:
        from kcd_mod_manager.ui import icons

        names = icons.available()
        if not names:
            raise RuntimeError("no icons bundled")
        for name in names:
            if icons.pixmap(name, "#0078D4", 16, 1.0).toImage().isNull():
                raise RuntimeError(f"cannot render {name}")
        # QSS url() images go through the SVG image-format plugin, not QtSvg directly.
        if QImage(icons.stylesheet_url("checkmark_filled", "#FFFFFF")).isNull():
            raise RuntimeError("SVG image-format plugin missing")
        return str(len(names))

    check("icons", svg_icons)
    for module in ("py7zr", "rarfile", "httpx", "keyring", "websockets", "kcd_mod_manager.ui.main_window"):
        check(module, lambda m=module: bool(importlib.import_module(m)))

    def keyring_backend() -> str:
        import keyring

        return type(keyring.get_keyring()).__name__

    check("keyring backend", keyring_backend)
    failed = {k: v for k, v in results.items() if v.startswith("FAIL") and k != "keyring backend"}
    text = json.dumps({"ok": not failed, "results": results}, indent=2)
    if report is not None:
        report.write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        print(text)
    return 1 if failed else 0

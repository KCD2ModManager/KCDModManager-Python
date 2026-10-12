"""Qt application bootstrap."""

from __future__ import annotations

import logging
import subprocess
import sys
import traceback
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from kcd_mod_manager import APP_NAME, __version__
from kcd_mod_manager.bootstrap import build_context
from kcd_mod_manager.i18n import set_language, tr
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.logging_setup import configure_logging
from kcd_mod_manager.resources import resource_path

log = logging.getLogger(__name__)


def _install_excepthook() -> None:
    def hook(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
        log.critical("Unhandled exception", exc_info=(kind, value, tb))
        if QApplication.instance() is not None:
            details = "".join(traceback.format_exception_only(kind, value)).strip()
            QMessageBox.critical(None, tr("DialogTitleError"), details)

    sys.excepthook = hook


def restart_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, "-m", "kcd_mod_manager", *sys.argv[1:]]


def run(data_dir: Path | None = None, online: bool = True) -> int:
    paths = AppPaths(data_dir) if data_dir else AppPaths.default()
    paths.ensure()
    configure_logging(paths.logs_dir)
    log.info("Starting %s %s (data: %s)", APP_NAME, __version__, paths.data_dir)
    _install_excepthook()

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("KCDModManager")
    app.setDesktopFileName("kcd-mod-manager")
    icon = resource_path("images", "logo.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from kcd_mod_manager.ui.main_window import MainWindow

    try:
        ctx = build_context(paths)
    except Exception as exc:
        log.exception("Initialization failed")
        QMessageBox.critical(None, tr("DialogTitleError"), tr("ErrorInitialization", exc))
        return 1
    set_language(ctx.settings.language)

    window = MainWindow(ctx, online=online)
    if not window.start():
        return 0
    window.show()
    code = app.exec()
    if window.restart_requested:
        log.info("Restarting for language change")
        subprocess.Popen(restart_command(), close_fds=True)
    return code

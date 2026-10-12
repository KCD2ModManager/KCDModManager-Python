"""OS integration: opening folders/URLs and launching the game.

Launching:

* Windows: ``KingdomCome.exe`` is started directly with the configured arguments (as before).
* Linux: the game is a Windows build running under Proton, so it is started through Steam
  (``steam -applaunch <appid> <args>``), falling back to the ``steam://rungameid/<appid>`` URL
  (launch arguments cannot be passed that way). Non-Steam installs (Heroic, Lutris, ...) must
  be launched from their own launcher.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from kcd_mod_manager.domain.models import GameInstall
from kcd_mod_manager.infrastructure.steam import find_steamapps_for_install

log = logging.getLogger(__name__)

ALLOWED_URL_SCHEMES = ("https://", "http://", "steam://")


class LaunchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LaunchResult:
    method: str
    arguments_applied: bool = True


def _clean_env() -> dict[str, str]:
    """Environment for child processes without PyInstaller's library overrides."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            original = env.pop(f"{key}_ORIG", None)
            if original is not None:
                env[key] = original
            else:
                env.pop(key, None)
    return env


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], env=_clean_env())
    else:
        subprocess.Popen(["xdg-open", str(path)], env=_clean_env())


def open_url(url: str) -> None:
    if not url.startswith(ALLOWED_URL_SCHEMES):
        raise ValueError(f"Refusing to open URL with unsupported scheme: {url}")
    if sys.platform.startswith("linux") and shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], env=_clean_env())
        return
    webbrowser.open(url)


def build_arguments(launch_args: str, dev_mode: bool) -> list[str]:
    args = shlex.split(launch_args, posix=sys.platform != "win32") if launch_args.strip() else []
    if dev_mode and "-devmode" not in args:
        args.append("-devmode")
    return args


def launch_game(install: GameInstall, launch_args: str, dev_mode: bool) -> LaunchResult:
    exe = install.executable_path
    if exe.suffix.lower() != ".exe":
        raise LaunchError("Only .exe files can be executed.")
    args = build_arguments(launch_args, dev_mode)
    if sys.platform == "win32":
        if not exe.is_file():
            raise LaunchError(f"Executable not found: {exe}")
        subprocess.Popen([str(exe), *args], cwd=str(exe.parent), close_fds=True)
        return LaunchResult("direct")

    in_steam_library = find_steamapps_for_install(install.root_path) is not None
    steam = shutil.which("steam")
    app_id = str(install.game.steam_app_id)
    if steam and in_steam_library:
        subprocess.Popen([steam, "-applaunch", app_id, *args], env=_clean_env(), start_new_session=True)
        return LaunchResult("steam")
    if in_steam_library:
        open_url(f"steam://rungameid/{app_id}")
        return LaunchResult("steam-url", arguments_applied=not args)
    raise LaunchError(
        "This installation is not in a Steam library. Start the game from the launcher you installed it with "
        "(e.g. Heroic or Lutris)."
    )

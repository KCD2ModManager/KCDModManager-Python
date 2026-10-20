"""OS integration: opening folders/URLs and launching the game.

Launching:

* Windows: ``KingdomCome.exe`` is started directly with the configured arguments (as before).
* Linux: the game is a Windows build running under Proton, so it is started through Steam
  (``steam -applaunch <appid> <args>``), falling back to the ``steam://rungameid/<appid>`` URL
  (launch arguments cannot be passed that way). Non-Steam installs (Heroic, Lutris, ...) must
  be launched from their own launcher.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shlex
import shutil
import signal
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


def _same_path(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def running_processes() -> list[tuple[int, Path]]:
    """(pid, executable path) of running processes (best effort, no third-party dependency)."""
    processes: list[tuple[int, Path]] = []
    if sys.platform == "win32":
        processes.extend(_running_processes_windows())
    elif sys.platform.startswith("linux"):
        proc = Path("/proc")
        if proc.is_dir():
            for entry in proc.iterdir():
                if not entry.name.isdigit():
                    continue
                pid = int(entry.name)
                with contextlib.suppress(OSError):
                    processes.append((pid, (entry / "exe").readlink()))
                try:  # Proton: the exe appears in the command line, not as /proc exe
                    for token in (entry / "cmdline").read_bytes().split(b"\0"):
                        text = token.decode("utf-8", "ignore")
                        if text.lower().endswith(".exe"):
                            processes.append((pid, Path(text)))
                except OSError:
                    continue
    return processes


def running_executables() -> list[Path]:
    return [path for _pid, path in running_processes()]


def _running_processes_windows() -> list[tuple[int, Path]]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]
    process_ids = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(process_ids, ctypes.sizeof(process_ids), ctypes.byref(needed)):
        return []
    count = needed.value // ctypes.sizeof(wintypes.DWORD)
    processes: list[tuple[int, Path]] = []
    buffer = ctypes.create_unicode_buffer(32768)
    for pid in process_ids[:count]:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                processes.append((int(pid), Path(buffer.value)))
        finally:
            kernel32.CloseHandle(handle)
    return processes


def game_process_ids(install: GameInstall, processes: list[tuple[int, Path]] | None = None) -> list[int]:
    candidates = running_processes() if processes is None else processes
    return [pid for pid, path in candidates if _same_path(path, install.executable_path)]


def stop_game(install: GameInstall, processes: list[tuple[int, Path]] | None = None) -> bool:
    """Terminate the running game processes of this installation. True if any were signalled."""
    stopped = False
    for pid in game_process_ids(install, processes):
        try:
            if sys.platform == "win32":
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
                handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
                if not handle:
                    continue
                try:
                    stopped = bool(kernel32.TerminateProcess(handle, 1)) or stopped
                finally:
                    kernel32.CloseHandle(handle)
            else:
                os.kill(pid, signal.SIGTERM)
                stopped = True
        except OSError:
            continue
    return stopped


def is_game_running(install: GameInstall, executables: list[Path] | None = None) -> bool:
    """True if a process runs exactly this installation's executable."""
    candidates = running_executables() if executables is None else executables
    return any(_same_path(path, install.executable_path) for path in candidates)


def launch_game(install: GameInstall, launch_args: str, dev_mode: bool) -> LaunchResult:
    if is_game_running(install):
        raise LaunchError("The game is already running.")
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

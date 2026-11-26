"""OS integration: opening folders/URLs and launching the game.

Launching:

* Steam installs: started through Steam (``steam -applaunch`` / ``steam://``) so the overlay works.
* Epic installs: started via ``com.epicgames.launcher://`` so EOS licensing works.
* Other Windows installs (GOG / manual): ``KingdomCome.exe`` is started directly.
* Linux non-Steam: must be launched from Heroic/Lutris/etc.
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
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from kcd_mod_manager.domain.models import GameInstall, LaunchStore
from kcd_mod_manager.infrastructure.steam import find_steamapps_for_install

log = logging.getLogger(__name__)

ALLOWED_URL_SCHEMES = ("https://", "http://", "steam://", "com.epicgames.launcher://")


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
    if sys.platform == "win32" and url.startswith("com.epicgames.launcher://"):
        os.startfile(url)  # type: ignore[attr-defined]
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


def _resolve_store(install: GameInstall) -> LaunchStore:
    if install.launch_store is not LaunchStore.UNKNOWN:
        return install.launch_store
    if find_steamapps_for_install(install.root_path) is not None:
        return LaunchStore.STEAM
    return LaunchStore.UNKNOWN


def _launch_steam(install: GameInstall, args: list[str]) -> LaunchResult:
    steam = shutil.which("steam")
    app_id = str(install.game.steam_app_id)
    if steam:
        cmd = [steam, "-applaunch", app_id, *args]
        kwargs: dict = {"env": _clean_env()}
        if sys.platform == "win32":
            kwargs["close_fds"] = True
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
        return LaunchResult("steam")
    open_url(f"steam://rungameid/{app_id}")
    return LaunchResult("steam-url", arguments_applied=not args)


def _launch_epic(install: GameInstall) -> LaunchResult:
    # Path-based URI works across Artifact IDs (Epic protocol activation docs).
    encoded = urllib.parse.quote(str(install.root_path).replace("\\", "/"), safe="")
    url = f"com.epicgames.launcher://apps/{encoded}?action=launch&silent=true"
    try:
        open_url(url)
    except OSError as exc:
        raise LaunchError(
            "Could not start the Epic Games Launcher. Start Kingdom Come from Epic directly."
        ) from exc
    return LaunchResult("epic", arguments_applied=False)


def _launch_direct(install: GameInstall, args: list[str]) -> LaunchResult:
    exe = install.executable_path
    if not exe.is_file():
        raise LaunchError(f"Executable not found: {exe}")
    kwargs: dict = {"cwd": str(exe.parent)}
    if sys.platform == "win32":
        kwargs["close_fds"] = True
    else:
        kwargs["env"] = _clean_env()
        kwargs["start_new_session"] = True
    subprocess.Popen([str(exe), *args], **kwargs)
    return LaunchResult("direct")


def launch_game(
    install: GameInstall,
    launch_args: str,
    dev_mode: bool,
    *,
    via_store: bool = True,
) -> LaunchResult:
    """Start the game.

    * ``via_store=True`` (default): Steam/Epic installs go through their launcher (overlay / EOS).
    * ``via_store=False``: always run ``KingdomCome.exe`` directly — for custom/dev builds or when
      you want ``-devmode`` / launch args without the store launcher.
    * Manual / unknown installs always use direct launch.
    """
    if is_game_running(install):
        raise LaunchError("The game is already running.")
    exe = install.executable_path
    if exe.suffix.lower() != ".exe":
        raise LaunchError("Only .exe files can be executed.")
    args = build_arguments(launch_args, dev_mode)

    if not via_store:
        return _launch_direct(install, args)

    store = _resolve_store(install)
    if store is LaunchStore.STEAM or find_steamapps_for_install(install.root_path) is not None:
        return _launch_steam(install, args)
    if store is LaunchStore.EPIC:
        return _launch_epic(install)
    if sys.platform == "win32" or store is LaunchStore.UNKNOWN:
        return _launch_direct(install, args)

    raise LaunchError(
        "This installation is not in a Steam library. Start the game from the launcher you installed it with "
        "(e.g. Heroic or Lutris), or enable direct launch in Settings."
    )

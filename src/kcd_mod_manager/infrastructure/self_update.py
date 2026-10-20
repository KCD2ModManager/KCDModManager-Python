"""Download and apply a newer manager release from GitHub.

Supported installs:

* Windows installer: run the new setup silently; Inno Setup replaces the files.
* Windows portable / Linux tarball: a small helper script waits for this process to exit,
  copies the extracted update over the installation and restarts the manager.
* Linux AppImage: the helper replaces the AppImage file and restarts it.

Anything else (running from source, unknown layout) is reported as unsupported, and the UI
falls back to opening the download page. Downloads are verified against the release's
SHA256SUMS file before anything is executed or replaced.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import httpx

from kcd_mod_manager import __version__
from kcd_mod_manager.infrastructure.app_updates import RELEASES_REPOSITORY

log = logging.getLogger(__name__)

APP_ID = "{0A5AD17F-6487-4C6E-8817-D2792CA62251}"
Progress = Callable[[int], None]


class SelfUpdateError(Exception):
    pass


class InstallKind(StrEnum):
    SOURCE = "source"
    WINDOWS_INSTALLER = "windows-installer"
    WINDOWS_PORTABLE = "windows-portable"
    LINUX_APPIMAGE = "linux-appimage"
    LINUX_PORTABLE = "linux-portable"
    UNKNOWN = "unknown"

    @property
    def supported(self) -> bool:
        return self not in (InstallKind.SOURCE, InstallKind.UNKNOWN)


def asset_name(version: str, kind: InstallKind) -> str | None:
    if kind in (InstallKind.WINDOWS_INSTALLER,):
        return f"KCDModManager-{version}-windows-x64-setup.exe"
    if kind is InstallKind.WINDOWS_PORTABLE:
        return f"KCDModManager-{version}-windows-x64-portable.zip"
    if kind is InstallKind.LINUX_APPIMAGE:
        return f"KCDModManager-{version}-x86_64.AppImage"
    if kind is InstallKind.LINUX_PORTABLE:
        return f"KCDModManager-{version}-linux-x86_64.tar.gz"
    return None


def sums_name(kind: InstallKind) -> str:
    return "SHA256SUMS-windows.txt" if kind.value.startswith("windows") else "SHA256SUMS-linux-x86_64.txt"


def download_url(version: str, name: str) -> str:
    return f"https://github.com/{RELEASES_REPOSITORY}/releases/download/v{version}/{name}"


def _windows_install_location(executable: Path) -> bool:
    try:
        import winreg
    except ImportError:
        return False
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(
                hive, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
            ) as key:
                location, _ = winreg.QueryValueEx(key, "InstallLocation")
        except OSError:
            continue
        if location and os.path.normcase(str(Path(location))) == os.path.normcase(str(executable.parent)):
            return True
    return False


def detect_install_kind(
    executable: Path | None = None,
    *,
    frozen: bool | None = None,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
) -> InstallKind:
    executable = executable or Path(sys.executable)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    platform = sys.platform if platform is None else platform
    environ = dict(os.environ) if environ is None else environ
    if not frozen:
        return InstallKind.SOURCE
    if platform == "win32":
        return (
            InstallKind.WINDOWS_INSTALLER
            if _windows_install_location(executable)
            else InstallKind.WINDOWS_PORTABLE
        )
    if platform.startswith("linux"):
        return InstallKind.LINUX_APPIMAGE if environ.get("APPIMAGE") else InstallKind.LINUX_PORTABLE
    return InstallKind.UNKNOWN


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            result[Path(parts[-1]).name] = parts[0].lower()
    return result


def _download(
    url: str, target: Path, progress: Progress | None, transport: httpx.BaseTransport | None
) -> None:
    try:
        with (
            httpx.Client(timeout=60.0, transport=transport, follow_redirects=True) as client,
            client.stream("GET", url, headers={"User-Agent": f"KCDModManager/{__version__}"}) as response,
            target.open("wb") as handle,
        ):
            if response.status_code != 200:
                raise SelfUpdateError(f"Download failed (HTTP {response.status_code})")
            total = int(response.headers.get("content-length") or 0)
            done = 0
            for chunk in response.iter_bytes(256 * 1024):
                handle.write(chunk)
                done += len(chunk)
                if progress is not None and total:
                    progress(min(99, int(done * 100 / total)))
    except httpx.HTTPError as exc:
        raise SelfUpdateError(f"Download failed: {type(exc).__name__}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            original = env.pop(f"{key}_ORIG", None)
            if original is not None:
                env[key] = original
            else:
                env.pop(key, None)
    return env


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def prepare_update(
    version: str,
    kind: InstallKind,
    progress: Progress | None = None,
    transport: httpx.BaseTransport | None = None,
    executable: Path | None = None,
    work_dir: Path | None = None,
) -> Callable[[], None]:
    """Download + verify the release asset. Returns a callable that applies it and exits the app."""
    name = asset_name(version, kind)
    if name is None or not kind.supported:
        raise SelfUpdateError(f"Self-update is not supported for this installation ({kind}).")
    executable = executable or Path(sys.executable)
    install_dir = executable.parent
    root = work_dir or Path(tempfile.mkdtemp(prefix="kcdmm-update-"))
    root.mkdir(parents=True, exist_ok=True)
    asset = root / name
    _download(download_url(version, name), asset, progress, transport)
    sums = root / sums_name(kind)
    _download(download_url(version, sums.name), sums, None, transport)
    expected = parse_checksums(sums.read_text(encoding="utf-8", errors="replace")).get(name)
    if expected is None or _sha256(asset) != expected:
        raise SelfUpdateError("The downloaded update failed its checksum verification.")
    if progress is not None:
        progress(100)

    if kind is InstallKind.WINDOWS_INSTALLER:

        def apply_installer() -> None:
            subprocess.Popen(
                [str(asset), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                env=_clean_env(),
                close_fds=True,
            )

        return apply_installer

    if kind is InstallKind.LINUX_APPIMAGE:
        target = Path(os.environ.get("APPIMAGE") or executable)
        script = root / "apply-update.sh"
        script.write_text(
            "#!/bin/sh\n"
            f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done\n"
            f"cp {_sh_quote(asset)} {_sh_quote(target)} && chmod +x {_sh_quote(target)}\n"
            f"{_sh_quote(target)} >/dev/null 2>&1 &\n",
            encoding="utf-8",
        )
        script.chmod(0o755)

        def apply_appimage() -> None:
            subprocess.Popen(
                ["/bin/sh", str(script)], env=_clean_env(), start_new_session=True, close_fds=True
            )

        return apply_appimage

    staging = root / "staging"
    staging.mkdir(exist_ok=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(asset) as archive:
            archive.extractall(staging)
        sources = [p for p in staging.iterdir() if p.is_dir()]
        source = sources[0] if sources else staging
    else:
        with tarfile.open(asset, "r:gz") as archive:
            archive.extractall(staging, filter="data")
        sources = [p for p in staging.iterdir() if p.is_dir()]
        source = sources[0] if sources else staging

    if kind is InstallKind.WINDOWS_PORTABLE:
        script = root / "apply-update.ps1"
        script.write_text(
            f"while (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) "
            "{ Start-Sleep -Milliseconds 300 }\n"
            f"robocopy {_ps_quote(source)} {_ps_quote(install_dir)} /MIR /R:3 /W:1 | Out-Null\n"
            f"Start-Process {_ps_quote(executable)}\n",
            encoding="utf-8",
        )

        def apply_portable_windows() -> None:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                env=_clean_env(),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        return apply_portable_windows

    script = root / "apply-update.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done\n"
        f"cp -a {_sh_quote(source)}/. {_sh_quote(install_dir)}/\n"
        f"chmod +x {_sh_quote(executable)} 2>/dev/null\n"
        f"{_sh_quote(executable)} >/dev/null 2>&1 &\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    def apply_portable_linux() -> None:
        subprocess.Popen(["/bin/sh", str(script)], env=_clean_env(), start_new_session=True, close_fds=True)

    return apply_portable_linux


def _sh_quote(value: object) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"

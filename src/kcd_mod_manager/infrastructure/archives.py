"""Extraction of mod archives (.zip, .7z, .rar) with path-traversal protection.

* ``.zip`` uses the standard library.
* ``.7z`` uses ``py7zr`` (pure Python).
* ``.rar`` uses ``rarfile``, which needs an external extractor: ``unrar``, ``unar``, ``7z`` or
  ``bsdtar``. Windows 10+ ships ``bsdtar`` as ``tar.exe``, so RAR works out of the box there;
  on Linux one of those tools must be installed.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

SUPPORTED_ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z")


class ArchiveError(Exception):
    pass


def is_supported_archive(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES


def _safe_target(destination: Path, member: str) -> Path | None:
    """Resolve an archive member below ``destination``; ``None`` for unsafe or empty names."""
    normalized = member.replace("\\", "/")
    parts = [p for p in PurePosixPath(normalized).parts if p not in ("", ".", "/")]
    if not parts or any(p == ".." for p in parts) or ":" in parts[0]:
        return None
    target = destination.joinpath(*parts)
    try:
        target.resolve().relative_to(destination.resolve())
    except ValueError:
        return None
    return target


def _extract_zip(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                target = _safe_target(destination, info.filename)
                if target is None:
                    log.warning("Skipping unsafe archive entry %r", info.filename)
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ArchiveError(f"Invalid zip archive: {exc}") from exc


def _extract_7z(archive: Path, destination: Path) -> None:
    import py7zr
    from py7zr.exceptions import Bad7zFile

    try:
        with py7zr.SevenZipFile(archive, mode="r") as sz:
            names = sz.getnames()
            unsafe = [n for n in names if _safe_target(destination, n) is None]
            if unsafe:
                raise ArchiveError(f"Archive contains unsafe paths: {unsafe[:3]}")
            sz.extractall(path=destination)
    except Bad7zFile as exc:
        raise ArchiveError(f"Invalid 7z archive: {exc}") from exc


def rar_support_available() -> bool:
    return any(shutil.which(tool) for tool in ("unrar", "unar", "7z", "7zz", "bsdtar", "tar"))


def _configure_rarfile() -> None:
    import rarfile

    if not shutil.which("bsdtar") and shutil.which("tar"):
        # Windows ships libarchive's bsdtar as tar.exe.
        rarfile.BSDTAR_TOOL = "tar"
    rarfile.tool_setup(force=True)


def _extract_rar(archive: Path, destination: Path) -> None:
    import rarfile

    try:
        _configure_rarfile()
    except rarfile.RarCannotExec as exc:
        raise ArchiveError("RAR extraction needs 'unrar', 'unar', '7z' or 'bsdtar' to be installed.") from exc
    try:
        with rarfile.RarFile(archive) as rf:
            for info in rf.infolist():
                target = _safe_target(destination, info.filename)
                if target is None:
                    log.warning("Skipping unsafe archive entry %r", info.filename)
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with rf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except rarfile.RarCannotExec as exc:
        raise ArchiveError("RAR extraction needs 'unrar', 'unar', '7z' or 'bsdtar' to be installed.") from exc
    except rarfile.Error as exc:
        raise ArchiveError(f"Invalid rar archive: {exc}") from exc


def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        _extract_zip(archive, destination)
    elif suffix == ".7z":
        _extract_7z(archive, destination)
    elif suffix == ".rar":
        _extract_rar(archive, destination)
    else:
        raise ArchiveError(f"Unsupported archive type: {archive.suffix}")

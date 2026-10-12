"""Filesystem primitives: atomic writes, corruption-safe JSON, retrying moves, tree copies."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class CorruptFileError(Exception):
    """A data file exists but could not be parsed; it must not be overwritten blindly."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def read_text(path: Path) -> str:
    """Read UTF-8 text, tolerating a BOM (files written by .NET may contain one)."""
    return path.read_text(encoding="utf-8-sig")


def atomic_write_text(path: Path, content: str, *, newline: str | None = None) -> None:
    """Write via a temp file in the same directory and replace the target in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def atomic_write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write lines with the platform line separator, like .NET ``File.WriteAllLines``."""
    atomic_write_text(path, "".join(f"{line}\n" for line in lines), newline=None)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _replace_with_retry(source: Path, target: Path, attempts: int = 5) -> None:
    for attempt in range(1, attempts + 1):
        try:
            source.replace(target)
            return
        except PermissionError:
            # Windows: target may be briefly locked by antivirus or the game.
            if attempt == attempts:
                raise
            time.sleep(0.05 * attempt)


def corrupt_backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
        counter += 1
    return candidate


def preserve_corrupt_file(path: Path) -> Path | None:
    """Copy an unreadable data file aside before it gets replaced. Returns the backup path."""
    if not path.exists():
        return None
    backup = corrupt_backup_path(path)
    shutil.copy2(path, backup)
    log.warning("Preserved unreadable file %s as %s", path, backup.name)
    return backup


def load_json(path: Path) -> Any | None:
    """Return parsed JSON, ``None`` if the file does not exist, raise ``CorruptFileError`` if unreadable."""
    if not path.exists():
        return None
    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise CorruptFileError(path, str(exc)) from exc
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptFileError(path, str(exc)) from exc


def _on_rm_error(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    # Read-only files (common for Steam/extracted content on Windows) block deletion.
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path, onexc=_on_rm_error)


def copy_tree(source: Path, target: Path) -> None:
    """Copy a directory tree, preserving relative paths, merging into ``target``."""
    shutil.copytree(source, target, dirs_exist_ok=True)


def find_first(root: Path, file_name: str) -> Path | None:
    """Shallowest file named ``file_name`` (case-insensitive) below ``root``."""
    wanted = file_name.casefold()
    best: Path | None = None
    best_depth = 1 << 30
    for dirpath, _dirnames, filenames in os.walk(root):
        depth = Path(dirpath).relative_to(root).parts.__len__()
        if depth >= best_depth:
            continue
        for name in filenames:
            if name.casefold() == wanted:
                best, best_depth = Path(dirpath) / name, depth
                break
    return best


def has_file_with_suffix(root: Path, suffix: str) -> bool:
    wanted = suffix.casefold()
    for _dirpath, _dirnames, filenames in os.walk(root):
        if any(name.casefold().endswith(wanted) for name in filenames):
            return True
    return False


def files_with_suffix(root: Path, suffix: str) -> list[Path]:
    wanted = suffix.casefold()
    result: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        result.extend(Path(dirpath) / n for n in filenames if n.casefold().endswith(wanted))
    return sorted(result)

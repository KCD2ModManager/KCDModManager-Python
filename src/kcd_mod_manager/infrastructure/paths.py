"""Path helpers that behave the same on case-sensitive (Linux) and case-insensitive (Windows) filesystems."""

from __future__ import annotations

from pathlib import Path


def find_child_ci(directory: Path, name: str) -> Path | None:
    """Return the existing child of ``directory`` whose name matches ``name`` ignoring case.

    An exact match wins over a case-insensitive one.
    """
    exact = directory / name
    if exact.exists():
        return exact
    try:
        lowered = name.casefold()
        for child in directory.iterdir():
            if child.name.casefold() == lowered:
                return child
    except OSError:
        return None
    return None


def resolve_ci(base: Path, *parts: str) -> Path | None:
    """Resolve a relative path below ``base`` segment by segment, ignoring case."""
    current = base
    for part in parts:
        found = find_child_ci(current, part)
        if found is None:
            return None
        current = found
    return current


def same_path(a: Path, b: Path) -> bool:
    """Compare paths the way the host filesystem would."""
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    return str(a.absolute()).casefold() == str(b.absolute()).casefold()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True

"""Version parsing compatible with the semantics of .NET ``System.Version``.

The original application compared mod versions with ``Version.TryParse``: 2 to 4 non-negative
integer components; missing build/revision components rank lower than ``0``
(so ``1.0 < 1.0.0``). Anything else is "not comparable".
"""

from __future__ import annotations

import re

_INT32_MAX = 2**31 - 1

DotNetVersion = tuple[int, int, int, int]


def parse_version(text: str | None) -> DotNetVersion | None:
    if text is None:
        return None
    parts = text.strip().split(".")
    if not 2 <= len(parts) <= 4:
        return None
    values: list[int] = []
    for part in parts:
        part = part.strip()
        if not part or not (part.isascii() and part.isdigit()):
            return None
        value = int(part)
        if value > _INT32_MAX:
            return None
        values.append(value)
    while len(values) < 4:
        values.append(-1)
    return values[0], values[1], values[2], values[3]


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True if ``candidate`` parses and is strictly greater than ``current``.

    Mirrors the original update check: unparsable versions never report an update.
    """
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def is_not_newer(candidate: str | None, existing: str | None) -> bool:
    """True if both versions parse and ``candidate <= existing`` (install would be a downgrade)."""
    new, old = parse_version(candidate), parse_version(existing)
    return new is not None and old is not None and new <= old


def normalize_major_minor(version: str) -> str:
    """Reduce ``1.2.3.4`` to ``1.2`` for game compatibility checks; other text is kept as is."""
    match = re.search(r"(\d+)\.(\d+)", version)
    return f"{match.group(1)}.{match.group(2)}" if match else version.strip()


def is_game_version_compatible(mod_game_version: str | None, installed_version: str | None) -> bool:
    """A mod is compatible when its declared game version matches the installed major.minor.

    Unknown versions on either side are treated as compatible.
    """
    if not mod_game_version or not installed_version:
        return True
    mod_norm = normalize_major_minor(mod_game_version)
    game_norm = normalize_major_minor(installed_version)
    if not mod_norm or not game_norm:
        return True
    return mod_norm.startswith(game_norm) or game_norm.startswith(mod_norm)


def compare_app_versions(latest_tag: str, current: str) -> bool:
    """True if the release tag (``v4.4``, ``5.0.1``) is newer than the running version."""

    def as_tuple(text: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", text.lstrip("vV"))
        return tuple(int(n) for n in numbers) or (0,)

    latest, now = as_tuple(latest_tag), as_tuple(current)
    width = max(len(latest), len(now))
    return latest + (0,) * (width - len(latest)) > now + (0,) * (width - len(now))

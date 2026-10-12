"""Helpers for reading the PascalCase JSON written by the original .NET manager."""

from __future__ import annotations

from typing import Any


def pop_ci(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """Pop ``key`` matching case-insensitively (exact match preferred)."""
    if key in data:
        return data.pop(key)
    lowered = key.lower()
    for existing in list(data):
        if existing.lower() == lowered:
            return data.pop(existing)
    return default


def as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def as_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]

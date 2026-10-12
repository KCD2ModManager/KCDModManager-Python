"""Profile snapshot/apply logic (pure)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from kcd_mod_manager.domain.models import Mod, ModProfile

DEFAULT_PROFILE_NAME = "Default"


def now_iso() -> str:
    """UTC timestamp in .NET round-trip format (``2026-03-03T19:56:41.5165210Z``)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"


def snapshot(name: str, mods: Sequence[Mod], base: ModProfile | None = None) -> ModProfile:
    """Capture enabled mods, load order and separators. Unknown fields of ``base`` are kept."""
    ordered = sorted(mods, key=lambda m: m.number)
    return ModProfile(
        profile_name=name,
        active_mods=[m.id for m in mods if m.is_enabled],
        load_order=[m.id for m in ordered],
        mod_categories=dict(base.mod_categories) if base else {},
        separators_after_mod_ids=[m.id for m in mods if m.has_separator_after],
        last_modified=now_iso(),
        extra=dict(base.extra) if base else {},
    )


def apply_profile(mods: Sequence[Mod], profile: ModProfile) -> list[Mod]:
    """Enable exactly the profile's active mods and number them in the profile's load order.

    Mods unknown to the profile are disabled and appended after the profile's order.
    Returns the mods sorted by their new number.
    """
    active = set(profile.active_mods)
    separators = set(profile.separators_after_mod_ids)
    by_id = {m.id: m for m in mods}
    number = 1
    placed: set[str] = set()
    for mod_id in profile.load_order:
        mod = by_id.get(mod_id)
        if mod is None or mod_id in placed:
            continue
        mod.number = number
        number += 1
        placed.add(mod_id)
    for mod in mods:
        mod.is_enabled = mod.id in active
        mod.has_separator_after = mod.id in separators and not mod.is_workshop_mod
        if mod.id not in placed:
            mod.number = number
            number += 1
    return sorted(mods, key=lambda m: m.number)


def rename_mod_id(profile: ModProfile, old_id: str, new_id: str) -> bool:
    """Replace a mod id in place, keeping its position. Returns True if anything changed."""
    changed = False
    for attr in ("active_mods", "load_order", "separators_after_mod_ids"):
        values: list[str] = getattr(profile, attr)
        for index, value in enumerate(values):
            if value == old_id:
                values[index] = new_id
                changed = True
    for ids in profile.mod_categories.values():
        for index, value in enumerate(ids):
            if value == old_id:
                ids[index] = new_id
                changed = True
    return changed

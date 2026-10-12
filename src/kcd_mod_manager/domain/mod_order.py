"""The ``mod_order.txt`` format and load-order manipulation.

Format (shared with the game and the original manager): one mod id per line in load order.
Enabled mods are written as ``id``, disabled ones as ``# id``. Blank lines are ignored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from kcd_mod_manager.domain.models import Mod


@dataclass(frozen=True, slots=True)
class OrderEntry:
    mod_id: str
    enabled: bool


def parse_mod_order(lines: Iterable[str]) -> list[OrderEntry]:
    entries: list[OrderEntry] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        enabled = not line.startswith("#")
        mod_id = line if enabled else line[1:].strip()
        if mod_id:
            entries.append(OrderEntry(mod_id, enabled))
    return entries


def serialize_mod_order(mods: Iterable[Mod]) -> list[str]:
    """Lines for ``mod_order.txt``, ordered by ``Mod.number`` (stable for equal numbers)."""
    ordered = sorted(mods, key=lambda m: m.number)
    return [m.id if m.is_enabled else f"# {m.id}" for m in ordered]


def renumber(mods: Sequence[Mod]) -> None:
    """Assign load-order numbers 1..n following the sequence order."""
    for index, mod in enumerate(mods, start=1):
        mod.number = index


def apply_order_entries(mods: list[Mod], entries: Sequence[OrderEntry]) -> list[Mod]:
    """Order mods by the entries of an order file and apply their enabled state.

    Listed mods come first (numbered from 1) in file order; unlisted mods keep their relative order,
    are appended with ``number = 0`` and enabled - matching the original loader.
    """
    by_id = {m.id: m for m in mods}
    ordered: list[Mod] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        mod = by_id.get(entry.mod_id)
        if mod is None or entry.mod_id in seen:
            continue
        mod.number = index
        mod.is_enabled = entry.enabled
        ordered.append(mod)
        seen.add(entry.mod_id)
    for mod in mods:
        if mod.id not in seen:
            mod.number = 0
            mod.is_enabled = True
            ordered.append(mod)
    return ordered


def move_within(items: list[Mod], mod: Mod, target_index: int) -> bool:
    """Move ``mod`` to ``target_index`` (clamped). Returns True if the position changed."""
    try:
        current = items.index(mod)
    except ValueError:
        return False
    target = max(0, min(target_index, len(items) - 1))
    if target == current:
        return False
    items.pop(current)
    items.insert(target, mod)
    return True


def move_in_scope(all_mods: list[Mod], visible: Sequence[Mod], mod: Mod, visible_target: int) -> bool:
    """Move ``mod`` to position ``visible_target`` among the currently visible mods.

    The mod is placed directly before/after the visible neighbour it should end up next to,
    so hidden (filtered) mods keep their relative positions.
    """
    if mod not in visible:
        return False
    scope = list(visible)
    current = scope.index(mod)
    target = max(0, min(visible_target, len(scope) - 1))
    if target == current:
        return False
    anchor = scope[target]
    all_mods.remove(mod)
    anchor_index = all_mods.index(anchor)
    all_mods.insert(anchor_index + 1 if target > current else anchor_index, mod)
    return True

"""The ``mod_order.txt`` format and load-order manipulation.

Format (shared with the game and the original manager): one entry per line in load order.
Enabled mods are written as the **mod folder name**, disabled ones as ``# folder``. Blank lines
are ignored. Older files that listed ``<modid>`` instead of the folder name are still accepted
when applying an order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from kcd_mod_manager.domain.models import Mod


@dataclass(frozen=True, slots=True)
class OrderEntry:
    mod_id: str
    enabled: bool


def order_key(mod: Mod) -> str:
    """Identity written to ``mod_order.txt``: on-disk folder name, else ``Mod.id``."""
    if mod.path is not None:
        return mod.path.name
    return mod.id


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
    return [order_key(m) if m.is_enabled else f"# {order_key(m)}" for m in ordered]


def renumber(mods: Sequence[Mod]) -> None:
    """Assign load-order numbers 1..n following the sequence order."""
    for index, mod in enumerate(mods, start=1):
        mod.number = index


def _match_entry(mods: Sequence[Mod], key: str, seen: set[int]) -> Mod | None:
    """Resolve an order-file key to a mod: folder name first, then ``Mod.id`` (legacy)."""
    for mod in mods:
        if id(mod) in seen:
            continue
        if mod.path is not None and mod.path.name == key:
            return mod
    key_cf = key.casefold()
    for mod in mods:
        if id(mod) in seen:
            continue
        if mod.path is not None and mod.path.name.casefold() == key_cf:
            return mod
    for mod in mods:
        if id(mod) in seen:
            continue
        if mod.id == key or mod.id.casefold() == key_cf:
            return mod
    return None


def apply_order_entries(mods: list[Mod], entries: Sequence[OrderEntry]) -> list[Mod]:
    """Order mods by the entries of an order file and apply their enabled state.

    Listed mods come first (numbered from 1) in file order; unlisted mods keep their relative order,
    are appended with ``number = 0`` and enabled - matching the original loader.
    """
    ordered: list[Mod] = []
    seen: set[int] = set()
    for index, entry in enumerate(entries, start=1):
        mod = _match_entry(mods, entry.mod_id, seen)
        if mod is None:
            continue
        mod.number = index
        mod.is_enabled = entry.enabled
        ordered.append(mod)
        seen.add(id(mod))
    for mod in mods:
        if id(mod) not in seen:
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

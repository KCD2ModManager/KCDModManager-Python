"""Filtering and sorting of the mod list as shown in the main window."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from kcd_mod_manager.domain.models import Mod, ModCategory

UNCATEGORIZED = ""
"""Category filter value selecting mods without a category (``None`` means "all")."""


class SortMode(StrEnum):
    LOAD_ORDER = "LoadOrder"
    TITLE = "Title"
    CATEGORY = "Category"


def next_sort_mode(current: SortMode, has_categories: bool) -> SortMode:
    if current is SortMode.LOAD_ORDER:
        return SortMode.TITLE
    if current is SortMode.TITLE and has_categories:
        return SortMode.CATEGORY
    return SortMode.LOAD_ORDER


def matches(mod: Mod, search: str, category_filter: str | None) -> bool:
    if category_filter is not None:
        if category_filter == UNCATEGORIZED:
            if mod.category_id:
                return False
        elif (mod.category_id or "").casefold() != category_filter.casefold():
            return False
    term = search.strip().lower()
    if not term:
        return True
    return term in (mod.name or "").lower() or term in (mod.version or "").lower()


def sort_mods(mods: Iterable[Mod], mode: SortMode, categories: Sequence[ModCategory]) -> list[Mod]:
    items = list(mods)
    if mode is SortMode.TITLE:
        return sorted(items, key=lambda m: (m.name or "").casefold())
    if mode is SortMode.CATEGORY:
        order = {c.id.casefold(): i for i, c in enumerate(sorted(categories, key=lambda c: c.order))}
        uncategorized = len(order) + 1

        def key(m: Mod) -> tuple[int, str]:
            rank = order.get(m.category_id.casefold(), uncategorized) if m.category_id else uncategorized
            return rank, (m.name or "").casefold()

        return sorted(items, key=key)
    return items


def visible_mods(
    mods: Sequence[Mod],
    search: str,
    category_filter: str | None,
    mode: SortMode,
    categories: Sequence[ModCategory],
) -> list[Mod]:
    return sort_mods((m for m in mods if matches(m, search, category_filter)), mode, categories)

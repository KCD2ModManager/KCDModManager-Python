"""Category list operations (pure; persistence lives in the infrastructure layer)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from kcd_mod_manager.domain.models import ModCategory


class CategoryError(ValueError):
    pass


def new_category_id() -> str:
    return f"cat-{uuid.uuid4().hex}"


def sorted_categories(categories: Iterable[ModCategory]) -> list[ModCategory]:
    return sorted(categories, key=lambda c: (c.order, c.name.casefold()))


def normalize_orders(categories: list[ModCategory]) -> None:
    for index, category in enumerate(categories):
        category.order = index


def name_exists(categories: Iterable[ModCategory], name: str, exclude_id: str | None = None) -> bool:
    wanted = name.strip().casefold()
    return any(c.name.strip().casefold() == wanted and c.id != exclude_id for c in categories)


def create_category(categories: list[ModCategory], name: str) -> ModCategory:
    clean = name.strip()
    if not clean:
        raise CategoryError("Category name must not be empty.")
    if name_exists(categories, clean):
        raise CategoryError("Category name already exists.")
    order = max((c.order for c in categories), default=-1) + 1
    category = ModCategory(new_category_id(), clean, order)
    categories.append(category)
    return category


def rename_category(categories: list[ModCategory], category_id: str, new_name: str) -> None:
    clean = new_name.strip()
    if not clean:
        raise CategoryError("Category name must not be empty.")
    if name_exists(categories, clean, exclude_id=category_id):
        raise CategoryError("Category name already exists.")
    for category in categories:
        if category.id == category_id:
            category.name = clean
            return
    raise CategoryError(f"Unknown category {category_id}")


def delete_category(categories: list[ModCategory], category_id: str) -> list[ModCategory]:
    remaining = [c for c in sorted_categories(categories) if c.id != category_id]
    normalize_orders(remaining)
    return remaining

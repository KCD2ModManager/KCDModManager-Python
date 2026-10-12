"""``categories.json`` persistence and the ``mod.meta.json`` sidecar."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from kcd_mod_manager.domain.categories import sorted_categories
from kcd_mod_manager.domain.models import ModCategory
from kcd_mod_manager.infrastructure.fs import (
    CorruptFileError,
    atomic_write_json,
    load_json,
    preserve_corrupt_file,
)
from kcd_mod_manager.infrastructure.json_fields import as_bool, as_int, as_str, pop_ci

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SIDECAR_FILE = "mod.meta.json"


class CategoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[ModCategory]:
        """Load categories; a missing file is created empty, a corrupt one is preserved and reset."""
        try:
            data = load_json(self.path)
            if data is None:
                self.save([])
                return []
            if not isinstance(data, dict) or as_int(pop_ci(dict(data), "SchemaVersion"), 0) <= 0:
                raise CorruptFileError(self.path, "invalid category schema")
        except CorruptFileError as exc:
            log.error("categories.json unreadable (%s); keeping a copy and starting empty", exc.reason)
            preserve_corrupt_file(self.path)
            self.save([])
            return []

        raw_items = pop_ci(dict(data), "Categories", [])
        categories: list[ModCategory] = []
        for raw in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            category_id = as_str(pop_ci(item, "Id"))
            name = as_str(pop_ci(item, "Name"))
            if category_id and name is not None:
                categories.append(ModCategory(category_id, name, as_int(pop_ci(item, "Order"), 0)))
        return sorted_categories(categories)

    def save(self, categories: list[ModCategory]) -> None:
        atomic_write_json(
            self.path,
            {
                "SchemaVersion": SCHEMA_VERSION,
                "Categories": [
                    {"Id": c.id, "Name": c.name, "Order": c.order} for c in sorted_categories(categories)
                ],
            },
        )


class ModSidecar:
    """``mod.meta.json`` inside a mod folder: ``{"CategoryId": ..., "IsWorkshopMod": ...}``."""

    def __init__(self, mod_dir: Path) -> None:
        self.path = mod_dir / SIDECAR_FILE

    def read(self) -> dict[str, Any]:
        try:
            data = load_json(self.path)
        except CorruptFileError as exc:
            log.warning("Ignoring unreadable %s: %s", self.path, exc.reason)
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def category_id(self) -> str | None:
        value = as_str(pop_ci(self.read(), "CategoryId"))
        return value if value and value.strip() else None

    @property
    def is_workshop(self) -> bool:
        return as_bool(pop_ci(self.read(), "IsWorkshopMod"), False)

    def _write(self, category_id: str | None, is_workshop: bool) -> None:
        if not category_id and not is_workshop:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            return
        payload: dict[str, Any] = {"CategoryId": category_id or None}
        if is_workshop:
            payload["IsWorkshopMod"] = True
        atomic_write_json(self.path, payload)

    def set_category(self, category_id: str | None) -> None:
        self._write(category_id, self.is_workshop)

    def mark_workshop(self) -> None:
        self._write(self.category_id, True)

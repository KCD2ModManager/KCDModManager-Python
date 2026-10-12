"""Profile storage: ``<data>/profiles/<KCD1|KCD2>/<safe name>/{profile.json, mod_order.txt}``."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kcd_mod_manager.domain.mod_order import OrderEntry
from kcd_mod_manager.domain.models import GameType, Mod, ModProfile
from kcd_mod_manager.domain.naming import safe_file_name
from kcd_mod_manager.domain.profiles import now_iso
from kcd_mod_manager.infrastructure.fs import (
    CorruptFileError,
    atomic_write_json,
    load_json,
    preserve_corrupt_file,
    remove_tree,
)
from kcd_mod_manager.infrastructure.json_fields import as_str, as_str_list, pop_ci
from kcd_mod_manager.infrastructure.order_files import read_order_file, write_order_file

log = logging.getLogger(__name__)

PROFILE_FILE = "profile.json"
PROFILE_ORDER_FILE = "mod_order.txt"


def decode_profile(raw: dict[str, Any], fallback_name: str) -> ModProfile:
    data = dict(raw)
    categories_raw = pop_ci(data, "ModCategories", {})
    categories: dict[str, list[str]] = {}
    if isinstance(categories_raw, dict):
        categories = {str(k): as_str_list(v) for k, v in categories_raw.items()}
    return ModProfile(
        profile_name=as_str(pop_ci(data, "ProfileName")) or fallback_name,
        active_mods=as_str_list(pop_ci(data, "ActiveMods")),
        load_order=as_str_list(pop_ci(data, "LoadOrder")),
        mod_categories=categories,
        separators_after_mod_ids=as_str_list(pop_ci(data, "SeparatorsAfterModIds")),
        last_modified=as_str(pop_ci(data, "LastModified")) or "",
        extra=data,
    )


def encode_profile(profile: ModProfile) -> dict[str, Any]:
    return {
        "ProfileName": profile.profile_name,
        "ActiveMods": list(profile.active_mods),
        "LoadOrder": list(profile.load_order),
        "ModCategories": {k: list(v) for k, v in profile.mod_categories.items()},
        "SeparatorsAfterModIds": list(profile.separators_after_mod_ids),
        "LastModified": profile.last_modified,
        **profile.extra,
    }


class ProfileStore:
    def __init__(self, profiles_root: Path) -> None:
        self.root = profiles_root

    def game_dir(self, game: GameType) -> Path:
        return self.root / game.value

    def profile_dir(self, game: GameType, name: str) -> Path:
        return self.game_dir(game) / safe_file_name(name)

    def exists(self, game: GameType, name: str) -> bool:
        return (self.profile_dir(game, name) / PROFILE_FILE).is_file()

    def list(self, game: GameType) -> list[ModProfile]:
        directory = self.game_dir(game)
        if not directory.is_dir():
            return []
        profiles: list[ModProfile] = []
        for child in directory.iterdir():
            file = child / PROFILE_FILE
            if not file.is_file():
                continue
            try:
                data = load_json(file)
            except CorruptFileError as exc:
                log.error("Skipping unreadable profile %s: %s", child.name, exc.reason)
                continue
            if isinstance(data, dict):
                profiles.append(decode_profile(data, child.name))
        return sorted(profiles, key=lambda p: p.profile_name.casefold())

    def load(self, game: GameType, name: str) -> ModProfile | None:
        file = self.profile_dir(game, name) / PROFILE_FILE
        try:
            data = load_json(file)
        except CorruptFileError as exc:
            log.error("Profile %s unreadable: %s", name, exc.reason)
            return None
        return decode_profile(data, name) if isinstance(data, dict) else None

    def save(self, game: GameType, profile: ModProfile) -> None:
        profile.last_modified = now_iso()
        file = self.profile_dir(game, profile.profile_name) / PROFILE_FILE
        try:
            load_json(file)
        except CorruptFileError:
            preserve_corrupt_file(file)
        atomic_write_json(file, encode_profile(profile))

    def read_order(self, game: GameType, name: str) -> list[OrderEntry]:
        return read_order_file(self.profile_dir(game, name) / PROFILE_ORDER_FILE)

    def write_order(self, game: GameType, name: str, mods: Iterable[Mod]) -> None:
        write_order_file(self.profile_dir(game, name) / PROFILE_ORDER_FILE, mods)

    def delete(self, game: GameType, name: str) -> None:
        directory = self.profile_dir(game, name)
        if directory.exists():
            remove_tree(directory)

    def duplicate(self, game: GameType, source_name: str, new_name: str) -> ModProfile:
        source = self.load(game, source_name)
        if source is None:
            raise FileNotFoundError(f"Profile '{source_name}' not found")
        copy = ModProfile(
            profile_name=new_name,
            active_mods=list(source.active_mods),
            load_order=list(source.load_order),
            mod_categories={k: list(v) for k, v in source.mod_categories.items()},
            separators_after_mod_ids=list(source.separators_after_mod_ids),
            extra=dict(source.extra),
        )
        self.save(game, copy)
        source_order = self.profile_dir(game, source_name) / PROFILE_ORDER_FILE
        if source_order.is_file():
            target = self.profile_dir(game, new_name) / PROFILE_ORDER_FILE
            target.write_bytes(source_order.read_bytes())
        return copy

"""Reading and writing ``mod.manifest`` files on disk."""

from __future__ import annotations

import logging
from pathlib import Path

from kcd_mod_manager.domain import manifest as m
from kcd_mod_manager.domain.models import ManifestInfo
from kcd_mod_manager.infrastructure.fs import atomic_write_text, read_text

log = logging.getLogger(__name__)


def _read_fixed(path: Path) -> str:
    """Read a manifest; rewrite it once if it carries the invalid ``version="2.0"`` declaration."""
    text = read_text(path)
    fixed, changed = m.fix_xml_version(text)
    if changed:
        atomic_write_text(path, fixed)
    return fixed


def parse_manifest_file(
    path: Path, *, renaming_enabled: bool, allow_write_mod_id: bool
) -> ManifestInfo | None:
    """Parse a manifest; returns ``None`` if it is missing or invalid."""
    try:
        parsed = m.parse_manifest(
            _read_fixed(path), renaming_enabled=renaming_enabled, allow_write_mod_id=allow_write_mod_id
        )
    except (OSError, UnicodeDecodeError, m.ManifestError) as exc:
        log.warning("Invalid manifest %s: %s", path, exc)
        return None
    if parsed.rewritten_text is not None:
        try:
            atomic_write_text(path, parsed.rewritten_text)
        except OSError as exc:
            log.warning("Could not store generated mod id in %s: %s", path, exc)
    return parsed.info


def generate_manifest_file(folder: Path, *, renaming_enabled: bool) -> Path:
    path = folder / m.MANIFEST_FILE_NAME
    atomic_write_text(path, m.generate_manifest(folder.name, renaming_enabled=renaming_enabled))
    return path


def update_manifest_fields(path: Path, fields: dict[str, str]) -> bool:
    try:
        atomic_write_text(path, m.update_info_fields(_read_fixed(path), fields))
    except (OSError, UnicodeDecodeError, m.ManifestError) as exc:
        log.error("Updating manifest %s failed: %s", path, exc)
        return False
    return True


def ensure_manifest_mod_id(path: Path, mod_id: str) -> bool:
    try:
        current = m.read_info_field(_read_fixed(path), "modid")
    except (OSError, UnicodeDecodeError, m.ManifestError) as exc:
        log.error("Reading manifest %s failed: %s", path, exc)
        return False
    if current is not None and current.casefold() == mod_id.casefold():
        return True
    return update_manifest_fields(path, {"modid": mod_id})


def find_manifest(mod_dir: Path) -> Path | None:
    """Top-level ``mod.manifest`` of a mod folder (case-insensitive)."""
    from kcd_mod_manager.infrastructure.paths import find_child_ci

    found = find_child_ci(mod_dir, m.MANIFEST_FILE_NAME)
    return found if found is not None and found.is_file() else None

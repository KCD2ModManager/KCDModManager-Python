"""Mod discovery, installation, update and removal on disk.

Differences to the original manager (deliberate fixes, see docs/MIGRATION.md):

* Installs preserve the archive's folder structure (the original flattened nested folders).
* A mod is replaced via staging + swap, so a failed extraction never leaves the mod half-deleted.
* When folder renaming would collide with another existing folder, nothing is deleted.
* Steam Workshop folders are never written to (generated ids/manifests stay in memory).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain import manifest as manifest_text
from kcd_mod_manager.domain.manifest import MANIFEST_FILE_NAME
from kcd_mod_manager.domain.mod_order import apply_order_entries
from kcd_mod_manager.domain.models import GameInstall, ManifestInfo, Mod, ModVersionInfo
from kcd_mod_manager.domain.naming import generate_mod_id, safe_file_name
from kcd_mod_manager.domain.versioning import is_game_version_compatible, is_not_newer
from kcd_mod_manager.infrastructure import manifest_files as mf
from kcd_mod_manager.infrastructure.archives import ArchiveError, extract_archive
from kcd_mod_manager.infrastructure.categories_store import ModSidecar
from kcd_mod_manager.infrastructure.fs import (
    copy_tree,
    find_first,
    has_file_with_suffix,
    read_text,
    remove_tree,
)
from kcd_mod_manager.infrastructure.order_files import OrderFileManager
from kcd_mod_manager.infrastructure.paths import same_path
from kcd_mod_manager.infrastructure.repositories import ModNotesRepository, ModVersionsRepository
from kcd_mod_manager.infrastructure.steam import is_workshop_path, workshop_content_dir

log = logging.getLogger(__name__)

BACKUP_ROOT_NAME = "Mods_Backup"
BACKUP_PREFIX = "Mods_Backup_"


class InstallStatus(Enum):
    INSTALLED = auto()
    INVALID_MANIFEST = auto()
    NOT_A_MOD = auto()
    NOT_NEWER = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class InstallResult:
    status: InstallStatus
    mod: Mod | None = None
    message: str = ""


def _staging_dir(name: str) -> Path:
    """Fresh ``<tmp>/kcdmm_xxx/<name>`` directory; the folder name matters for generated manifests."""
    base = Path(tempfile.mkdtemp(prefix="kcdmm_"))
    staging = base / (safe_file_name(name).strip() or "mod")
    staging.mkdir()
    return staging


def _cleanup_staging(staging: Path) -> None:
    try:
        remove_tree(staging.parent)
    except OSError as exc:
        log.warning("Could not remove temporary folder %s: %s", staging.parent, exc)


def replace_directory(source: Path, target: Path) -> None:
    """Replace ``target`` with a copy of ``source`` without a window where neither exists."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    incoming = target.with_name(f".{target.name}.incoming-{stamp}")
    previous = target.with_name(f".{target.name}.previous-{stamp}")
    copy_tree(source, incoming)
    try:
        if target.exists():
            target.rename(previous)
        try:
            incoming.rename(target)
        except OSError:
            if previous.exists() and not target.exists():
                previous.rename(target)
            raise
    finally:
        if incoming.exists():
            remove_tree(incoming)
    if previous.exists():
        try:
            remove_tree(previous)
        except OSError as exc:
            log.warning("Could not remove old mod copy %s: %s", previous, exc)


def _manifest_info_in_memory(manifest: Path, folder_name: str, renaming: bool) -> ManifestInfo | None:
    """Parse a (possibly missing) manifest without touching the file - used for Workshop content."""
    try:
        text = (
            read_text(manifest)
            if manifest.is_file()
            else manifest_text.generate_manifest(folder_name, renaming_enabled=renaming)
        )
        return manifest_text.parse_manifest(text, renaming_enabled=renaming, allow_write_mod_id=False).info
    except (OSError, UnicodeDecodeError, manifest_text.ManifestError) as exc:
        log.warning("Invalid workshop manifest %s: %s", manifest, exc)
        return None


def workshop_mod_id(info: ManifestInfo, workshop_id: str, renaming: bool) -> str:
    if info.has_explicit_mod_id:
        return info.mod_id
    candidate = info.name if info.name.strip() else workshop_id
    return generate_mod_id(candidate, renaming)


class ModLibrary:
    def __init__(self, order_files: OrderFileManager) -> None:
        self.order_files = order_files

    # ------------------------------------------------------------------ discovery
    def load_mods(self, install: GameInstall, settings: AppSettings) -> list[Mod]:
        mods_dir = install.mods_path
        mods_dir.mkdir(parents=True, exist_ok=True)
        renaming = settings.enable_file_renaming
        entries = self.order_files.read(mods_dir, settings.mod_order_enabled)

        by_id: dict[str, Mod] = {}
        for directory in sorted(p for p in mods_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            mod = self._load_local_mod(directory, mods_dir, renaming)
            if mod is None:
                continue
            if mod.id in by_id:
                log.warning("Duplicate mod id %s in %s and %s", mod.id, by_id[mod.id].path, mod.path)
            by_id[mod.id] = mod

        known = {key.casefold() for key in by_id}
        for mod in self._load_workshop_mods(install, renaming):
            if mod.id.casefold() not in known:
                known.add(mod.id.casefold())
                by_id[mod.id] = mod

        ordered = apply_order_entries(list(by_id.values()), entries)
        self._map_metadata(ordered, mods_dir)
        for mod in ordered:
            mod.is_compatible = is_game_version_compatible(mod.game_version, install.game_version)
        return ordered

    def _load_local_mod(self, directory: Path, mods_dir: Path, renaming: bool) -> Mod | None:
        manifest = mf.find_manifest(directory)
        if manifest is None:
            if not has_file_with_suffix(directory, ".pak"):
                return None
            if is_workshop_path(directory):
                info = _manifest_info_in_memory(directory / MANIFEST_FILE_NAME, directory.name, renaming)
                return self._workshop_mod(directory, info, renaming) if info else None
            manifest = mf.generate_manifest_file(directory, renaming_enabled=renaming)

        if is_workshop_path(directory):
            info = _manifest_info_in_memory(manifest, directory.name, renaming)
            return self._workshop_mod(directory, info, renaming) if info else None

        info = mf.parse_manifest_file(manifest, renaming_enabled=renaming, allow_write_mod_id=renaming)
        if info is None:
            return None
        path = directory
        if renaming and directory.name != info.mod_id and safe_file_name(info.mod_id) == info.mod_id:
            path = self._rename_to_mod_id(directory, mods_dir / info.mod_id)
        return Mod(
            id=info.mod_id,
            name=info.name,
            version=info.version,
            path=path,
            is_enabled=True,
            game_version=info.game_version,
        )

    @staticmethod
    def _rename_to_mod_id(directory: Path, expected: Path) -> Path:
        if expected.exists() and not same_path(expected, directory):
            log.warning("Not renaming %s: %s already exists", directory.name, expected.name)
            return directory
        try:
            directory.rename(expected)
            return expected
        except OSError as exc:
            log.error("Renaming %s to %s failed: %s", directory, expected, exc)
            return directory

    @staticmethod
    def _workshop_mod(directory: Path, info: ManifestInfo, renaming: bool) -> Mod:
        return Mod(
            id=workshop_mod_id(info, directory.name, renaming),
            name=info.name,
            version=info.version,
            path=directory,
            is_enabled=True,
            is_workshop_mod=True,
            workshop_id=directory.name,
            game_version=info.game_version,
        )

    def _load_workshop_mods(self, install: GameInstall, renaming: bool) -> list[Mod]:
        content = workshop_content_dir(install.root_path, install.game.steam_app_id)
        if content is None:
            return []
        mods: list[Mod] = []
        for directory in sorted(p for p in content.iterdir() if p.is_dir()):
            manifest = mf.find_manifest(directory) or directory / MANIFEST_FILE_NAME
            if not manifest.is_file() and not has_file_with_suffix(directory, ".pak"):
                continue
            info = _manifest_info_in_memory(manifest, directory.name, renaming)
            if info is not None:
                mods.append(self._workshop_mod(directory, info, renaming))
        return mods

    @staticmethod
    def _map_metadata(mods: list[Mod], mods_dir: Path) -> None:
        versions = ModVersionsRepository(mods_dir).load()
        notes = ModNotesRepository(mods_dir).load()
        for mod in mods:
            info = versions.get(mod.id)
            if info is not None:
                mod.mod_number = info.mod_number
                if not mod.version and info.version:
                    mod.version = info.version
                mod.update_checks_enabled = info.update_checks_enabled
            note = notes.get(mod.id)
            if note is not None:
                mod.note = note

    # ------------------------------------------------------------------ installation
    def install_archive(
        self,
        archive: Path,
        mods_dir: Path,
        settings: AppSettings,
        mod_number: int,
        allow_generated_manifest: bool = False,
    ) -> InstallResult:
        renaming = settings.enable_file_renaming
        staging = _staging_dir(archive.stem)
        try:
            try:
                extract_archive(archive, staging)
            except ArchiveError as exc:
                return InstallResult(InstallStatus.FAILED, message=str(exc))

            manifest = find_first(staging, MANIFEST_FILE_NAME)
            if manifest is None:
                if not has_file_with_suffix(staging, ".pak"):
                    return InstallResult(
                        InstallStatus.NOT_A_MOD, message="No mod.manifest and no .pak files found."
                    )
                manifest = mf.generate_manifest_file(staging, renaming_enabled=renaming)

            info = mf.parse_manifest_file(manifest, renaming_enabled=renaming, allow_write_mod_id=renaming)
            if info is None:
                if not allow_generated_manifest:
                    return InstallResult(InstallStatus.INVALID_MANIFEST)
                manifest = mf.generate_manifest_file(staging, renaming_enabled=renaming)
                info = mf.parse_manifest_file(
                    manifest, renaming_enabled=renaming, allow_write_mod_id=renaming
                )
                if info is None:
                    return InstallResult(
                        InstallStatus.FAILED, message="Generated manifest could not be parsed."
                    )

            source = manifest.parent
            if renaming:
                target = mods_dir / safe_file_name(info.mod_id)
            elif not same_path(source, staging):
                target = mods_dir / source.name
            else:
                target = mods_dir / staging.name

            if target.exists():
                existing_manifest = mf.find_manifest(target)
                existing = (
                    mf.parse_manifest_file(
                        existing_manifest, renaming_enabled=renaming, allow_write_mod_id=False
                    )
                    if existing_manifest
                    else None
                )
                if existing is not None and is_not_newer(info.version, existing.version):
                    return InstallResult(
                        InstallStatus.NOT_NEWER,
                        message=f"{info.name} {existing.version} is already installed "
                        f"(archive: {info.version}).",
                    )

            replace_directory(source, target)
            ModVersionsRepository(mods_dir).set(
                info.mod_id,
                ModVersionInfo(version=info.version, mod_number=mod_number, file_name=archive.name),
            )
            mod = Mod(
                id=info.mod_id,
                name=info.name,
                version=info.version,
                path=target,
                is_enabled=False,
                mod_number=mod_number,
                game_version=info.game_version,
            )
            log.info("Installed %s %s from %s", info.name, info.version, archive.name)
            return InstallResult(InstallStatus.INSTALLED, mod)
        except OSError as exc:
            log.exception("Installing %s failed", archive)
            return InstallResult(InstallStatus.FAILED, message=str(exc))
        finally:
            _cleanup_staging(staging)

    def install_folder(self, folder: Path, mods_dir: Path, settings: AppSettings) -> InstallResult:
        renaming = settings.enable_file_renaming
        workshop = is_workshop_path(folder)
        staging = _staging_dir(folder.name)
        try:
            copy_tree(folder, staging)
            manifest = find_first(staging, MANIFEST_FILE_NAME)
            if manifest is None:
                if not has_file_with_suffix(staging, ".pak"):
                    return InstallResult(
                        InstallStatus.NOT_A_MOD, message="No mod.manifest and no .pak files found."
                    )
                manifest = mf.generate_manifest_file(staging, renaming_enabled=renaming)

            info = mf.parse_manifest_file(
                manifest, renaming_enabled=renaming, allow_write_mod_id=renaming and not workshop
            )
            if info is None:
                return InstallResult(InstallStatus.INVALID_MANIFEST)
            mod_id = info.mod_id
            if workshop and not info.has_explicit_mod_id:
                mod_id = workshop_mod_id(info, folder.name, renaming)
                mf.ensure_manifest_mod_id(manifest, mod_id)

            target_name = folder.name if workshop or not renaming else safe_file_name(mod_id)
            target = mods_dir / target_name
            if same_path(target, folder) or folder in target.parents:
                return InstallResult(
                    InstallStatus.FAILED, message="The folder is already inside the mods folder."
                )

            replace_directory(staging, target)
            mod = Mod(
                id=mod_id,
                name=info.name,
                version=info.version,
                path=target,
                is_enabled=False,
                is_workshop_mod=workshop,
                workshop_id=folder.name if workshop else "",
                game_version=info.game_version,
            )
            if workshop:
                ModSidecar(target).mark_workshop()
            return InstallResult(InstallStatus.INSTALLED, mod)
        except OSError as exc:
            log.exception("Installing folder %s failed", folder)
            return InstallResult(InstallStatus.FAILED, message=str(exc))
        finally:
            _cleanup_staging(staging)

    def apply_update(self, archive: Path, mod: Mod, settings: AppSettings) -> ManifestInfo:
        """Replace an installed mod with the archive content, keeping its id. Raises on failure."""
        if mod.path is None:
            raise ValueError("Mod has no folder")
        renaming = settings.enable_file_renaming
        staging = _staging_dir(mod.path.name)
        try:
            extract_archive(archive, staging)
            manifest = find_first(staging, MANIFEST_FILE_NAME)
            if manifest is None:
                manifest = mf.generate_manifest_file(staging, renaming_enabled=renaming)
            info = mf.parse_manifest_file(manifest, renaming_enabled=renaming, allow_write_mod_id=renaming)
            if info is None:
                raise ArchiveError("The update does not contain a valid mod.manifest.")
            replace_directory(manifest.parent, mod.path)
            return info
        finally:
            _cleanup_staging(staging)

    # ------------------------------------------------------------------ removal & backup
    @staticmethod
    def delete_mod_files(mod: Mod) -> None:
        if mod.path is not None and mod.path.exists():
            remove_tree(mod.path)

    @staticmethod
    def create_backup(
        mods_dir: Path, max_count: int, now: Callable[[], datetime] = datetime.now
    ) -> Path | None:
        if not mods_dir.is_dir():
            return None
        backup_root = mods_dir.parent / BACKUP_ROOT_NAME
        target = backup_root / f"{BACKUP_PREFIX}{now().strftime('%Y%m%d_%H%M%S')}"
        suffix = 1
        while target.exists():
            target = backup_root / f"{BACKUP_PREFIX}{now().strftime('%Y%m%d_%H%M%S')}_{suffix}"
            suffix += 1
        shutil.copytree(mods_dir, target)
        backups = sorted(
            (p for p in backup_root.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX)),
            key=lambda p: p.stat().st_ctime,
            reverse=True,
        )
        for old in backups[max(max_count, 1) :]:
            try:
                remove_tree(old)
            except OSError as exc:
                log.warning("Could not prune backup %s: %s", old, exc)
        log.info("Created mods backup %s", target)
        return target

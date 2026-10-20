"""The manager session: current game, mod list, profiles and categories, plus every user operation.

The session is UI-agnostic and synchronous. The Qt layer runs slow calls on a worker thread and
asks the user for input before calling in (confirmation, names, ...).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from kcd_mod_manager.application.library import InstallResult, InstallStatus, ModLibrary
from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain import categories as cat
from kcd_mod_manager.domain import profiles as prof
from kcd_mod_manager.domain.mod_order import move_in_scope, renumber
from kcd_mod_manager.domain.models import (
    ConflictGroup,
    GameInstall,
    GameType,
    HighlightColor,
    Mod,
    ModCategory,
    ModProfile,
    ModVersionInfo,
    UserModData,
)
from kcd_mod_manager.domain.naming import generate_mod_id, safe_file_name
from kcd_mod_manager.domain.versioning import is_game_version_compatible, is_newer
from kcd_mod_manager.infrastructure import manifest_files as mf
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.categories_store import CategoryStore, ModSidecar
from kcd_mod_manager.infrastructure.conflict_scanner import ConflictScanner, ScanTarget
from kcd_mod_manager.infrastructure.fs import files_with_suffix
from kcd_mod_manager.infrastructure.game_detection import (
    EXECUTABLE_NAME,
    GameDetector,
    game_root_from_executable,
    make_install,
)
from kcd_mod_manager.infrastructure.nexus import NexusClient, NexusError, NexusRateLimited, latest_file
from kcd_mod_manager.infrastructure.order_files import OrderFileManager
from kcd_mod_manager.infrastructure.paths import same_path
from kcd_mod_manager.infrastructure.profiles_store import ProfileStore
from kcd_mod_manager.infrastructure.repositories import (
    ModNotesRepository,
    ModVersionsRepository,
    UserModDataRepository,
)
from kcd_mod_manager.infrastructure.settings_store import SettingsStore

log = logging.getLogger(__name__)


class SessionError(Exception):
    """A user-facing failure (message is shown to the user)."""


@dataclass(slots=True)
class UpdateCheckSummary:
    checked: int = 0
    updates: list[Mod] = field(default_factory=list)
    rate_limited: bool = False
    errors: int = 0


class ManagerSession:
    def __init__(
        self,
        paths: AppPaths,
        settings_store: SettingsStore,
        settings: AppSettings,
        library: ModLibrary,
        order_files: OrderFileManager,
        profiles: ProfileStore,
        categories: CategoryStore,
        user_data: UserModDataRepository,
        scanner: ConflictScanner,
        detector: GameDetector,
        nexus: NexusClient | None = None,
    ) -> None:
        self.paths = paths
        self.settings_store = settings_store
        self.settings = settings
        self.library = library
        self.order_files = order_files
        self.profile_store = profiles
        self.category_store = categories
        self.user_data = user_data
        self.scanner = scanner
        self.detector = detector
        self.nexus = nexus

        self.installs: dict[GameType, GameInstall | None] = {GameType.KCD1: None, GameType.KCD2: None}
        self.game: GameType | None = None
        self.mods: list[Mod] = []
        self.categories: list[ModCategory] = []
        self.profiles: list[ModProfile] = []
        self.selected_profile: str | None = None
        self.conflicts: list[ConflictGroup] = []

    # ------------------------------------------------------------------ settings
    def save_settings(self) -> None:
        self.settings_store.save(self.settings)

    # ------------------------------------------------------------------ games
    def detect_games(self) -> dict[GameType, GameInstall | None]:
        for game in GameType:
            install = self.detector.detect(game, self.settings.game_path(game))
            self.installs[game] = install
            if install is not None and self.settings.game_path(game) != str(install.root_path):
                self.settings.set_game_path(game, str(install.root_path))
        self.save_settings()
        return dict(self.installs)

    def set_manual_install(self, game: GameType, executable: Path) -> GameInstall:
        if executable.name.casefold() != EXECUTABLE_NAME.casefold() or not executable.is_file():
            raise SessionError(f"Please select {EXECUTABLE_NAME}.")
        root = game_root_from_executable(executable)
        install = make_install(game, root, executable)
        self.installs[game] = install
        self.settings.set_game_path(game, str(root))
        self.save_settings()
        return install

    @property
    def install(self) -> GameInstall | None:
        return self.installs.get(self.game) if self.game else None

    @property
    def mods_dir(self) -> Path:
        install = self.install
        if install is None:
            raise SessionError("No game selected.")
        return install.mods_path

    def select_game(self, game: GameType) -> None:
        if self.installs.get(game) is None:
            raise SessionError("Game installation not found")
        self.game = game
        self.mods, self.profiles, self.conflicts = [], [], []
        self.selected_profile = None

    # ------------------------------------------------------------------ loading
    def startup_maintenance(self) -> Path | None:
        """Repair order files and create the startup backup (if enabled). Returns the backup path."""
        mods_dir = self.mods_dir
        self.order_files.consolidate(self.settings.mod_order_enabled, mods_dir)
        if self.settings.backup_on_startup and self.settings.create_backup:
            try:
                return self.library.create_backup(mods_dir, self.settings.backup_max_count)
            except OSError as exc:
                log.error("Startup backup failed: %s", exc)
        return None

    def reload(self) -> None:
        install = self.install
        if install is None:
            raise SessionError("No game selected.")
        self.categories = self.category_store.load()
        mods = self.library.load_mods(install, self.settings)
        self._merge_user_data(mods)
        self._apply_categories(mods)
        self.mods = mods

    def _merge_user_data(self, mods: list[Mod]) -> None:
        entries = self.user_data.load()
        changed = False
        for mod in mods:
            entry = entries.get(mod.id)
            if entry is None:
                entries[mod.id] = UserModData(mod_id=mod.id, last_detected_version=mod.version)
                changed = True
                continue
            if entry.last_detected_version != mod.version:
                entry.last_detected_version = mod.version
                entry.last_updated = prof.now_iso()
                changed = True
            if entry.custom_version:
                mod.version = entry.custom_version
            if entry.custom_note:
                mod.note = entry.custom_note
            if entry.custom_name:
                mod.name = entry.custom_name
            mod.ignored_in_conflict_detector = entry.ignored_in_conflict_detector
            mod.highlight = entry.highlight
        if self.install is not None:
            notes = ModNotesRepository(self.install.mods_path).load()
            for mod in mods:
                if notes.get(mod.id):
                    mod.note = notes[mod.id]
        if changed:

            def apply(current: dict[str, UserModData]) -> None:
                for key, value in entries.items():
                    existing = current.get(key)
                    if existing is None:
                        value.last_updated = value.last_updated or prof.now_iso()
                        current[key] = value
                    elif existing.last_detected_version != value.last_detected_version:
                        existing.last_detected_version = value.last_detected_version
                        existing.last_updated = prof.now_iso()

            self.user_data.update(apply)

    def _apply_categories(self, mods: list[Mod]) -> None:
        valid = {c.id.casefold(): c for c in self.categories}
        entries = self.user_data.load()
        for mod in mods:
            category_id = None
            entry = entries.get(mod.id)
            if entry is not None and entry.category_id and entry.category_id.strip():
                category_id = entry.category_id
            elif mod.path is not None:
                sidecar = ModSidecar(mod.path)
                category_id = sidecar.category_id
                if sidecar.is_workshop:
                    mod.is_workshop_mod = True
            category = valid.get(category_id.casefold()) if category_id else None
            mod.category_id = category.id if category else None
            mod.category_name = category.name if category else None

    def refresh_category_names(self) -> None:
        self._apply_categories(self.mods)

    # ------------------------------------------------------------------ profiles
    def load_profiles(self) -> None:
        if self.game is None:
            return
        self.profiles = self.profile_store.list(self.game)
        if not self.profiles:
            default = prof.snapshot(prof.DEFAULT_PROFILE_NAME, self.mods)
            self.profile_store.save(self.game, default)
            self.profile_store.write_order(self.game, default.profile_name, self.mods)
            self.profiles = [default]

    def initial_profile_name(self) -> str | None:
        if not self.profiles or self.game is None:
            return None
        last = self.settings.last_used_profile(self.game)
        names = [p.profile_name for p in self.profiles]
        return last if last in names else names[0]

    def profile(self, name: str) -> ModProfile | None:
        return next((p for p in self.profiles if p.profile_name == name), None)

    def apply_profile(self, name: str) -> None:
        if self.game is None:
            raise SessionError("No game selected.")
        profile = self.profile_store.load(self.game, name)
        if profile is None:
            raise SessionError(f"Profile '{name}' not found")
        by_id = {m.id: m for m in self.mods}
        for index, entry in enumerate(self.profile_store.read_order(self.game, name), start=1):
            mod = by_id.get(entry.mod_id)
            if mod is not None:
                mod.number, mod.is_enabled = index, entry.enabled
        self.mods = prof.apply_profile(self.mods, profile)
        self.order_files.write(self.mods_dir, self.mods, self.settings.mod_order_enabled)
        self.selected_profile = name
        self.settings.set_last_used_profile(self.game, name)
        self.save_settings()

    def create_profile(self, name: str) -> ModProfile:
        if self.game is None:
            raise SessionError("No game selected.")
        name = name.strip()
        if not name:
            raise SessionError("Profile name must not be empty.")
        if self.profile_store.exists(self.game, name):
            raise SessionError(f"A profile named '{name}' already exists.")
        renumber(self.mods)
        profile = prof.snapshot(name, self.mods)
        self.profile_store.save(self.game, profile)
        self.profile_store.write_order(self.game, name, self.mods)
        self.order_files.write(self.mods_dir, self.mods, self.settings.mod_order_enabled)
        self.profiles = self.profile_store.list(self.game)
        self.selected_profile = name
        self.settings.set_last_used_profile(self.game, name)
        self.save_settings()
        return profile

    def duplicate_profile(self, source: str, new_name: str) -> ModProfile:
        if self.game is None:
            raise SessionError("No game selected.")
        new_name = new_name.strip()
        if not new_name:
            raise SessionError("Profile name must not be empty.")
        if self.profile_store.exists(self.game, new_name):
            raise SessionError(f"A profile named '{new_name}' already exists.")
        copy = self.profile_store.duplicate(self.game, source, new_name)
        self.profiles = self.profile_store.list(self.game)
        return copy

    def delete_profile(self, name: str) -> str | None:
        """Delete a profile; returns the profile to load next if the active one was removed."""
        if self.game is None:
            raise SessionError("No game selected.")
        self.profile_store.delete(self.game, name)
        self.profiles = self.profile_store.list(self.game)
        if self.selected_profile != name:
            return None
        self.selected_profile = None
        names = [p.profile_name for p in self.profiles]
        if prof.DEFAULT_PROFILE_NAME in names:
            return prof.DEFAULT_PROFILE_NAME
        return names[0] if names else None

    def save_profile(self) -> None:
        if self.game is None or self.selected_profile is None:
            raise SessionError("No profile selected.")
        renumber(self.mods)
        base = self.profile_store.load(self.game, self.selected_profile)
        profile = prof.snapshot(self.selected_profile, self.mods, base)
        self.profile_store.save(self.game, profile)
        self.profile_store.write_order(self.game, self.selected_profile, self.mods)
        self.order_files.write(self.mods_dir, self.mods, self.settings.mod_order_enabled)

    def save_mod_order(self) -> None:
        """Persist the current order: active profile (if any) plus the game's order file."""
        renumber(self.mods)
        if self.selected_profile is not None and self.game is not None:
            self.save_profile()
        else:
            self.order_files.write(self.mods_dir, self.mods, self.settings.mod_order_enabled)

    # ------------------------------------------------------------------ enable/disable/order
    def set_enabled(self, mod: Mod, enabled: bool) -> None:
        mod.is_enabled = enabled
        self.save_mod_order()

    def set_all_enabled(self, enabled: bool) -> None:
        for mod in self.mods:
            mod.is_enabled = enabled
        self.save_mod_order()

    def set_enabled_many(self, mods: Sequence[Mod], enabled: bool) -> None:
        for mod in mods:
            mod.is_enabled = enabled
        self.save_mod_order()

    def set_category_many(self, mods: Sequence[Mod], category_id: str | None) -> None:
        for mod in mods:
            self.set_category(mod, category_id)

    def move(self, mod: Mod, visible: Sequence[Mod], target_index: int) -> bool:
        if move_in_scope(self.mods, visible, mod, target_index):
            self.save_mod_order()
            return True
        return False

    def reorder(self, ordered_ids: Sequence[str]) -> None:
        """Apply a complete new order (drag & drop)."""
        by_id = {m.id: m for m in self.mods}
        reordered = [by_id[i] for i in ordered_ids if i in by_id]
        reordered.extend(m for m in self.mods if m.id not in set(ordered_ids))
        self.mods = reordered
        self.save_mod_order()

    # ------------------------------------------------------------------ installation
    def _add_installed(self, result: InstallResult) -> InstallResult:
        if result.status is not InstallStatus.INSTALLED or result.mod is None:
            return result
        mod = result.mod
        self.mods = [
            m for m in self.mods if m.id != mod.id or not same_path(m.path or Path(), mod.path or Path())
        ]
        existing = next((m for m in self.mods if m.id == mod.id), None)
        if existing is not None:
            existing.name, existing.version, existing.path = mod.name, mod.version, mod.path
            existing.mod_number = mod.mod_number if mod.mod_number > 0 else existing.mod_number
            mod = existing
        else:
            self.mods.append(mod)
        self.user_data.update_entry(mod.id, lambda e: setattr(e, "last_detected_version", mod.version))
        self._apply_categories([mod])
        install = self.install
        if install is not None:
            mod.is_compatible = is_game_version_compatible(mod.game_version, install.game_version)
        self.save_mod_order()
        return InstallResult(result.status, mod, result.message)

    def install_archive(
        self, archive: Path, mod_number: int, allow_generated_manifest: bool = False
    ) -> InstallResult:
        result = self.library.install_archive(
            archive, self.mods_dir, self.settings, mod_number, allow_generated_manifest
        )
        return self._add_installed(result)

    def install_folder(self, folder: Path) -> InstallResult:
        return self._add_installed(self.library.install_folder(folder, self.mods_dir, self.settings))

    @staticmethod
    def _require_local(mod: Mod) -> None:
        if mod.is_workshop_mod:
            raise SessionError("Steam Workshop mods are managed by Steam and cannot be changed here.")

    def delete_mod(self, mod: Mod) -> None:
        self._require_local(mod)
        self.library.delete_mod_files(mod)
        self.mods = [m for m in self.mods if m is not mod]
        self.save_mod_order()

    def create_backup(self) -> Path | None:
        return self.library.create_backup(self.mods_dir, self.settings.backup_max_count)

    # ------------------------------------------------------------------ per-mod metadata
    def rename_display(self, mod: Mod, new_name: str) -> None:
        new_name = new_name.strip()
        if mod.is_workshop_mod:
            mod.name = new_name
            self.user_data.update_entry(mod.id, lambda e: setattr(e, "custom_name", new_name))
            return
        if mod.path is None:
            raise SessionError("The mod folder does not exist or is not specified.")
        manifest = mf.find_manifest(mod.path)
        fields = {"name": new_name}
        if self.settings.enable_file_renaming:
            fields["modid"] = mod.id
        if manifest is None or not mf.update_manifest_fields(manifest, fields):
            raise SessionError("Failed to update the mod manifest. The changes were not applied.")
        mod.name = new_name
        self.user_data.update_entry(mod.id, lambda e: setattr(e, "custom_name", new_name))

    def rename_id(self, mod: Mod, new_name: str) -> str:
        """Change mod id and folder to match ``new_name``. Returns the new id."""
        if not self.settings.enable_file_renaming:
            raise SessionError("Enable file renaming first if you want to change mod id and folder.")
        self._require_local(mod)
        if mod.path is None:
            raise SessionError("The mod folder does not exist or is not specified.")
        old_id = mod.id
        new_id = generate_mod_id(new_name.strip(), True)
        new_path = self.mods_dir / safe_file_name(new_id)
        if new_path.exists() and not same_path(new_path, mod.path):
            raise SessionError("A mod folder with the new ID already exists. Please choose a different name.")
        manifest = mf.find_manifest(mod.path)
        if manifest is None or not mf.update_manifest_fields(
            manifest, {"name": new_name.strip(), "modid": new_id}
        ):
            raise SessionError("Failed to update the mod manifest. The changes were not applied.")
        if not same_path(new_path, mod.path) or new_path.name != mod.path.name:
            try:
                mod.path.rename(new_path)
            except OSError as exc:
                raise SessionError(f"Failed to rename the mod folder: {exc}") from exc
        mod.id, mod.path, mod.name = new_id, new_path, new_name.strip()
        self._rename_references(old_id, new_id)
        self.save_mod_order()
        return new_id

    def _rename_references(self, old_id: str, new_id: str) -> None:
        if old_id == new_id:
            return
        mods_dir = self.mods_dir

        def move_key(data: dict, value_fix: Callable | None = None) -> None:  # type: ignore[type-arg]
            if old_id in data:
                value = data.pop(old_id)
                if value_fix is not None:
                    value_fix(value)
                data[new_id] = value

        ModNotesRepository(mods_dir).update(move_key)
        versions = ModVersionsRepository(mods_dir)
        if versions.path.exists():
            versions.update(move_key)
        self.user_data.update(lambda d: move_key(d, lambda e: setattr(e, "mod_id", new_id)))
        if self.game is not None:
            for profile in self.profile_store.list(self.game):
                if prof.rename_mod_id(profile, old_id, new_id):
                    self.profile_store.save(self.game, profile)
            self.profiles = self.profile_store.list(self.game)

    def set_note(self, mod: Mod, note: str) -> None:
        mod.note = note
        ModNotesRepository(self.mods_dir).update(lambda notes: notes.__setitem__(mod.id, note))

    def set_custom_version(self, mod: Mod, version: str | None) -> None:
        """Override the displayed version; an empty value reverts to the detected version."""
        value = version.strip() if version else ""
        entries = self.user_data.load()
        detected = entries[mod.id].last_detected_version if mod.id in entries else None

        def apply(entry: UserModData) -> None:
            entry.custom_version = value or None
            if entry.last_detected_version is None:
                entry.last_detected_version = mod.version

        self.user_data.update_entry(mod.id, apply)
        mod.version = value or detected or mod.version

    def set_mod_number(self, mod: Mod, number: int) -> None:
        mod.mod_number = number

        def apply(entries: dict[str, ModVersionInfo]) -> None:
            info = entries.get(mod.id) or ModVersionInfo(version=mod.version)
            info.mod_number = number
            entries[mod.id] = info

        ModVersionsRepository(self.mods_dir).update(apply)

    def toggle_update_checks(self, mod: Mod) -> None:
        mod.update_checks_enabled = not mod.update_checks_enabled

        def apply(entries: dict[str, ModVersionInfo]) -> None:
            info = entries.get(mod.id) or ModVersionInfo(version=mod.version, mod_number=mod.mod_number)
            info.update_checks_enabled = mod.update_checks_enabled
            entries[mod.id] = info

        ModVersionsRepository(self.mods_dir).update(apply)

    def set_ignored_in_conflicts(self, mod: Mod, ignored: bool) -> None:
        mod.ignored_in_conflict_detector = ignored
        self.user_data.update_entry(mod.id, lambda e: setattr(e, "ignored_in_conflict_detector", ignored))

    def set_highlight(self, mod: Mod, color: HighlightColor | None) -> None:
        mod.highlight = color
        self.user_data.update_entry(mod.id, lambda e: setattr(e, "highlight", color))

    def toggle_separator(self, mod: Mod) -> None:
        if mod.is_workshop_mod:
            return
        mod.has_separator_after = not mod.has_separator_after
        self.save_mod_order()

    # ------------------------------------------------------------------ categories
    def set_category(self, mod: Mod, category_id: str | None) -> None:
        if self.user_data.exists() or mod.is_workshop_mod:
            self.user_data.update_entry(mod.id, lambda e: setattr(e, "category_id", category_id or None))
            if mod.path is not None and not mod.is_workshop_mod:
                ModSidecar(mod.path).set_category(None)
        elif mod.path is not None:
            ModSidecar(mod.path).set_category(category_id)
        category = next((c for c in self.categories if c.id == category_id), None)
        mod.category_id = category.id if category else None
        mod.category_name = category.name if category else None

    def create_category(self, name: str) -> ModCategory:
        categories = list(self.categories)
        try:
            category = cat.create_category(categories, name)
        except cat.CategoryError as exc:
            raise SessionError(str(exc)) from exc
        self.category_store.save(categories)
        self.categories = cat.sorted_categories(categories)
        return category

    def save_categories(self, categories: list[ModCategory], reassign: dict[str, str | None]) -> None:
        """Persist an edited category list; ``reassign`` maps deleted ids to a target id (or None)."""
        cat.normalize_orders(categories)
        self.category_store.save(categories)
        self.categories = cat.sorted_categories(categories)
        for mod in self.mods:
            if mod.category_id in reassign:
                self.set_category(mod, reassign[mod.category_id])
        self._apply_categories(self.mods)

    # ------------------------------------------------------------------ manifests
    def update_manifest_game_version(self, mods: Sequence[Mod]) -> int:
        install = self.install
        if install is None or not install.game_version:
            raise SessionError("Could not detect game version")
        count = 0
        for mod in mods:
            if mod.path is None or mod.is_workshop_mod:
                continue
            for manifest in files_with_suffix(mod.path, ".manifest"):
                if manifest.name.casefold() == "mod.manifest" and mf.update_manifest_fields(
                    manifest, {"gameVersion": install.game_version}
                ):
                    count += 1
            mod.game_version = install.game_version
            mod.is_compatible = True
        return count

    # ------------------------------------------------------------------ conflicts
    def scan_conflicts(
        self, progress: Callable[[int], None] | None = None, cancelled: threading.Event | None = None
    ) -> list[ConflictGroup]:
        only_enabled = self.settings.conflict_detector_only_enabled_mods
        targets = [
            ScanTarget(m.id, m.path)
            for m in self.mods
            if m.path is not None
            and not m.ignored_in_conflict_detector
            and (m.is_enabled or not only_enabled)
        ]
        self.conflicts = self.scanner.scan(targets, progress, cancelled)
        return self.conflicts

    # ------------------------------------------------------------------ Nexus updates
    def check_mod_update(self, mod: Mod) -> str | None:
        """Latest Nexus version if newer than installed, else None. Raises NexusError."""
        if self.nexus is None or self.game is None:
            raise SessionError("Nexus is not available.")
        newest = latest_file(self.nexus.mod_files(self.game.nexus_domain, mod.mod_number))
        latest = newest.effective_version if newest else ""
        if latest and mod.version and is_newer(latest, mod.version):
            mod.has_update, mod.latest_version = True, latest
            return latest
        mod.has_update, mod.latest_version = False, ""
        return None

    def check_all_updates(self, cancelled: threading.Event | None = None) -> UpdateCheckSummary:
        summary = UpdateCheckSummary()
        for mod in list(self.mods):
            if cancelled is not None and cancelled.is_set():
                break
            if mod.mod_number <= 0 or not mod.update_checks_enabled:
                continue
            try:
                if self.check_mod_update(mod):
                    summary.updates.append(mod)
                summary.checked += 1
            except NexusRateLimited:
                summary.rate_limited = True
                break
            except NexusError as exc:
                summary.errors += 1
                log.warning("Update check for %s failed: %s", mod.name, exc)
        return summary

    def install_update(self, mod: Mod, progress: Callable[[int, int | None], None] | None = None) -> None:
        """Premium flow: download the newest file and replace the mod in place."""
        if self.nexus is None or self.game is None:
            raise SessionError("Nexus is not available.")
        self._require_local(mod)
        domain = self.game.nexus_domain
        newest = latest_file(self.nexus.mod_files(domain, mod.mod_number))
        if newest is None:
            raise SessionError("No files found on Nexus Mods.")
        url = self.nexus.download_link(domain, mod.mod_number, newest.file_id)
        archive = self.nexus.download(url, mod.mod_number, progress)
        try:
            info = self.library.apply_update(archive, mod, self.settings)
        finally:
            archive.unlink(missing_ok=True)
        mod.version = info.version
        if not self.user_data.load().get(mod.id, UserModData(mod.id)).custom_name:
            mod.name = info.name
        mod.has_update, mod.latest_version, mod.is_compatible = False, "", True
        mod.game_version = info.game_version

        def apply(entries: dict[str, ModVersionInfo]) -> None:
            entry = entries.get(mod.id) or ModVersionInfo(mod_number=mod.mod_number)
            entry.version = info.version
            entry.file_name = newest.name or entry.file_name
            entries[mod.id] = entry

        ModVersionsRepository(self.mods_dir).update(apply)
        self.user_data.update_entry(mod.id, lambda e: setattr(e, "last_detected_version", info.version))
        self.save_mod_order()

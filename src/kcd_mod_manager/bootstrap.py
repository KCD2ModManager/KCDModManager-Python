"""Composition root: builds the object graph without any Qt dependency."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from kcd_mod_manager.application.library import ModLibrary
from kcd_mod_manager.application.nexus_account import NexusAccount
from kcd_mod_manager.application.session import ManagerSession
from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.categories_store import CategoryStore
from kcd_mod_manager.infrastructure.conflict_scanner import ConflictScanner
from kcd_mod_manager.infrastructure.credentials import (
    CredentialStore,
    FileCredentialStore,
    KeyringCredentialStore,
)
from kcd_mod_manager.infrastructure.game_detection import GameDetector
from kcd_mod_manager.infrastructure.legacy_import import import_legacy_settings
from kcd_mod_manager.infrastructure.nexus import NexusClient
from kcd_mod_manager.infrastructure.order_files import OrderFileManager, RetryPrompt
from kcd_mod_manager.infrastructure.profiles_store import ProfileStore
from kcd_mod_manager.infrastructure.repositories import UserModDataRepository
from kcd_mod_manager.infrastructure.settings_store import SettingsStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    paths: AppPaths
    settings: AppSettings
    session: ManagerSession
    nexus: NexusAccount
    credentials: CredentialStore
    order_files: OrderFileManager
    first_run: bool
    imported_legacy: bool


def load_settings(
    paths: AppPaths, credentials: CredentialStore
) -> tuple[SettingsStore, AppSettings, bool, bool]:
    """Load settings; on first run import them (read-only) from the original WPF manager."""
    store = SettingsStore(paths.settings_file)
    if store.exists():
        return store, store.load(), False, False
    legacy = import_legacy_settings()
    if legacy is None:
        settings = AppSettings()
        store.save(settings)
        return store, settings, True, False
    settings = legacy.settings
    if legacy.nexus_token and not credentials.get():
        try:
            credentials.set(legacy.nexus_token)
        except OSError as exc:
            log.warning("Could not store imported Nexus key: %s", exc)
    store.save(settings)
    return store, settings, True, True


def build_context(
    paths: AppPaths | None = None,
    credentials: CredentialStore | None = None,
    retry_prompt: RetryPrompt | None = None,
) -> AppContext:
    paths = paths or AppPaths.default()
    paths.ensure()
    credentials = credentials or KeyringCredentialStore(FileCredentialStore(paths.data_dir / "nexus_api_key"))
    settings_store, settings, first_run, imported = load_settings(paths, credentials)

    order_files = OrderFileManager(paths.safety_dir, retry_prompt)
    nexus_client = NexusClient(credentials.get)
    session = ManagerSession(
        paths=paths,
        settings_store=settings_store,
        settings=settings,
        library=ModLibrary(order_files),
        order_files=order_files,
        profiles=ProfileStore(paths.profiles_dir),
        categories=CategoryStore(paths.categories_file),
        user_data=UserModDataRepository(paths.user_mod_data_file),
        scanner=ConflictScanner(),
        detector=GameDetector(),
        nexus=nexus_client,
    )
    account = NexusAccount(settings, session.save_settings, credentials, nexus_client)
    return AppContext(paths, settings, session, account, credentials, order_files, first_run, imported)

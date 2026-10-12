"""Nexus Mods account state: login via SSO, validation, logout."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain.models import NexusUser
from kcd_mod_manager.infrastructure.credentials import CredentialStore
from kcd_mod_manager.infrastructure.nexus import NexusAuthError, NexusClient
from kcd_mod_manager.infrastructure.nexus_sso import request_api_key

log = logging.getLogger(__name__)


class NexusAccount:
    def __init__(
        self,
        settings: AppSettings,
        save_settings: Callable[[], None],
        credentials: CredentialStore,
        client: NexusClient,
    ) -> None:
        self._settings = settings
        self._save_settings = save_settings
        self.credentials = credentials
        self.client = client

    @property
    def is_logged_in(self) -> bool:
        return bool(self.credentials.get())

    @property
    def username(self) -> str:
        return self._settings.nexus_username

    @property
    def is_premium(self) -> bool:
        return self._settings.nexus_is_premium

    def _store_user(self, user: NexusUser) -> None:
        self._settings.nexus_username = user.name
        self._settings.nexus_user_email = user.email
        self._settings.nexus_user_id = user.user_id
        self._settings.nexus_is_premium = user.is_premium
        self._save_settings()

    def login(self, open_browser: Callable[[str], None], cancelled: threading.Event) -> NexusUser:
        api_key = request_api_key(open_browser, cancelled)
        user = self.client.validate(api_key)
        self.credentials.set(api_key)
        self._store_user(user)
        log.info("Logged in to Nexus Mods as %s (premium=%s)", user.name, user.is_premium)
        return user

    def refresh(self) -> NexusUser | None:
        """Re-validate the stored key (updates premium status). Clears the account if the key was revoked."""
        if not self.is_logged_in:
            return None
        try:
            user = self.client.validate()
        except NexusAuthError:
            log.warning("Stored Nexus API key was rejected; logging out")
            self.logout()
            return None
        self._store_user(user)
        return user

    def logout(self) -> None:
        self.credentials.delete()
        self._settings.clear_nexus_account()
        self._save_settings()

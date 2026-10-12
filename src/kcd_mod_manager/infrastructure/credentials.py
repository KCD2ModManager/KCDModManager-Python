"""Storage of the Nexus Mods API key.

The key is kept in the OS credential store (Windows Credential Manager, Secret Service/KWallet on
Linux) via ``keyring``. If no usable backend exists, it falls back to a file in the data directory
that is readable only by the current user; the UI reports this as "insecure storage".
The key itself is never logged.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

SERVICE_NAME = "KCDModManager"
ACCOUNT_NAME = "nexus_api_key"


class CredentialStore(Protocol):
    @property
    def is_secure(self) -> bool: ...

    def get(self) -> str | None: ...

    def set(self, secret: str) -> None: ...

    def delete(self) -> None: ...


class MemoryCredentialStore:
    """In-memory store for tests."""

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret

    @property
    def is_secure(self) -> bool:
        return True

    def get(self) -> str | None:
        return self._secret

    def set(self, secret: str) -> None:
        self._secret = secret

    def delete(self) -> None:
        self._secret = None


class FileCredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def is_secure(self) -> bool:
        return False

    def get(self) -> str | None:
        try:
            value = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def set(self, secret: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(self.path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
        if sys.platform != "win32":
            self.path.chmod(0o600)

    def delete(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


class KeyringCredentialStore:
    def __init__(self, fallback: FileCredentialStore) -> None:
        self._fallback = fallback
        self._keyring_ok = self._probe()

    @staticmethod
    def _probe() -> bool:
        try:
            import keyring
            from keyring.backends import fail

            backend = keyring.get_keyring()
            if isinstance(backend, fail.Keyring):
                return False
            name = type(backend).__name__.lower()
            return "null" not in name and "plaintext" not in name
        except Exception:  # keyring backends can fail in surprising ways
            log.warning("No usable system keyring; falling back to file storage")
            return False

    @property
    def is_secure(self) -> bool:
        return self._keyring_ok

    def get(self) -> str | None:
        if self._keyring_ok:
            try:
                import keyring

                value = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
                if value:
                    return value
            except Exception as exc:
                log.warning("Reading from the keyring failed: %s", type(exc).__name__)
        return self._fallback.get()

    def set(self, secret: str) -> None:
        if self._keyring_ok:
            try:
                import keyring

                keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, secret)
                self._fallback.delete()
                return
            except Exception as exc:
                log.warning("Writing to the keyring failed (%s); using file storage", type(exc).__name__)
                self._keyring_ok = False
        self._fallback.set(secret)

    def delete(self) -> None:
        if self._keyring_ok:
            try:
                import keyring
                from keyring.errors import PasswordDeleteError

                with contextlib.suppress(PasswordDeleteError):
                    keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
            except Exception as exc:
                log.warning("Deleting from the keyring failed: %s", type(exc).__name__)
        self._fallback.delete()

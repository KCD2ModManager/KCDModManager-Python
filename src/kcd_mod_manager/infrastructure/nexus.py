"""Nexus Mods public API v1 client.

Only the endpoints the original manager used are implemented:

* ``GET  /v1/users/validate.json``
* ``GET  /v1/games/{domain}/mods/{id}/files.json``
* ``GET  /v1/games/{domain}/mods/{id}/files/{file_id}/download_link.json`` (premium only)
* ``POST /v1/games/{domain}/mods/{id}/endorse.json``
* ``GET  /v1/user/endorsements.json`` (to avoid asking users who already endorsed the manager)

The API key is sent in the ``apikey`` header and is never logged.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from kcd_mod_manager import __version__
from kcd_mod_manager.domain.models import NexusFile, NexusUser

log = logging.getLogger(__name__)

API_BASE = "https://api.nexusmods.com/v1"
APPLICATION_NAME = "kcd2mm"
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class NexusError(Exception):
    pass


class NexusAuthError(NexusError):
    """The API key is missing, invalid or revoked."""


class NexusPremiumRequired(NexusError):
    """Direct downloads need a premium account."""


class NexusRateLimited(NexusError):
    """The hourly/daily request quota is exhausted."""


def mod_page_url(domain: str, mod_number: int) -> str:
    return f"https://www.nexusmods.com/{domain}/mods/{mod_number}"


def mod_files_page_url(domain: str, mod_number: int) -> str:
    return f"{mod_page_url(domain, mod_number)}?tab=files"


def latest_file(files: list[NexusFile]) -> NexusFile | None:
    return max(files, key=lambda f: f.uploaded_timestamp, default=None)


def _parse_files(payload: Any) -> list[NexusFile]:
    raw_files = payload.get("files", []) if isinstance(payload, dict) else []
    files: list[NexusFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        try:
            files.append(
                NexusFile(
                    file_id=int(item.get("file_id", 0)),
                    version=str(item.get("version") or ""),
                    uploaded_timestamp=int(item.get("uploaded_timestamp") or 0),
                    name=str(item.get("name") or ""),
                    mod_version=str(item.get("mod_version") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return files


def _parse_download_uri(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload or None
    if isinstance(payload, list):
        for item in payload:
            uri = _parse_download_uri(item)
            if uri:
                return uri
        return None
    if isinstance(payload, dict):
        for key in ("URI", "uri", "url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return None


class NexusClient:
    def __init__(
        self,
        api_key_provider: Callable[[], str | None],
        transport: httpx.BaseTransport | None = None,
        base_url: str = API_BASE,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._client = httpx.Client(
            base_url=base_url,
            timeout=DEFAULT_TIMEOUT,
            transport=transport,
            follow_redirects=True,
            headers={
                "User-Agent": f"KCDModManager/{__version__}",
                "Application-Name": APPLICATION_NAME,
                "Application-Version": __version__,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _key(self, override: str | None = None) -> str:
        key = override or self._api_key_provider()
        if not key:
            raise NexusAuthError("Nexus API key not configured")
        return key

    def _request(self, method: str, path: str, *, api_key: str | None = None) -> Any:
        try:
            response = self._client.request(method, path, headers={"apikey": self._key(api_key)})
        except httpx.HTTPError as exc:
            raise NexusError(f"Network error: {type(exc).__name__}") from exc
        remaining = response.headers.get("x-rl-hourly-remaining")
        if remaining is not None:
            log.debug("Nexus hourly requests remaining: %s", remaining)
        if response.status_code == 401:
            raise NexusAuthError("Nexus rejected the API key")
        if response.status_code == 403:
            raise NexusPremiumRequired("Nexus returned 403 (premium required or forbidden)")
        if response.status_code == 429:
            raise NexusRateLimited("Nexus API rate limit reached")
        if response.status_code >= 400:
            raise NexusError(f"Nexus API returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            return None

    def validate(self, api_key: str | None = None) -> NexusUser:
        data = self._request("GET", "/users/validate.json", api_key=api_key)
        if not isinstance(data, dict):
            raise NexusError("Unexpected response from validate endpoint")
        return NexusUser(
            user_id=int(data.get("user_id") or 0),
            name=str(data.get("name") or ""),
            email=str(data.get("email") or ""),
            is_premium=bool(data.get("is_premium")),
        )

    def mod_files(self, domain: str, mod_number: int) -> list[NexusFile]:
        return _parse_files(self._request("GET", f"/games/{domain}/mods/{mod_number}/files.json"))

    def download_link(self, domain: str, mod_number: int, file_id: int) -> str:
        payload = self._request(
            "GET", f"/games/{domain}/mods/{mod_number}/files/{file_id}/download_link.json"
        )
        uri = _parse_download_uri(payload)
        if not uri:
            raise NexusError("No download link returned")
        return uri

    def endorse(self, domain: str, mod_number: int) -> None:
        self._request("POST", f"/games/{domain}/mods/{mod_number}/endorse.json")

    def has_endorsed(self, domain: str, mod_number: int) -> bool:
        data = self._request("GET", "/user/endorsements.json")
        if not isinstance(data, list):
            return False
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                same_mod = (
                    str(entry.get("domain_name")) == domain and int(entry.get("mod_id") or 0) == mod_number
                )
            except (TypeError, ValueError):
                continue
            if same_mod and str(entry.get("status") or "").lower() == "endorsed":
                return True
        return False

    def download(
        self,
        url: str,
        mod_number: int,
        progress: Callable[[int, int | None], None] | None = None,
        target_dir: Path | None = None,
    ) -> Path:
        """Stream a file to a temporary ``.zip`` path (CDN links are pre-signed; no API key is sent)."""
        directory = target_dir or Path(tempfile.gettempdir())
        suffix = Path(httpx.URL(url).path).suffix.lower() or ".zip"
        target = directory / f"mod_update_{mod_number}_{uuid.uuid4().hex}{suffix}"
        try:
            with httpx.stream(
                "GET", url, timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True
            ) as r:
                if r.status_code >= 400:
                    raise NexusError(f"Download failed with HTTP {r.status_code}")
                total = int(r.headers.get("content-length") or 0) or None
                done = 0
                with target.open("wb") as handle:
                    for chunk in r.iter_bytes(chunk_size=1 << 16):
                        handle.write(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total)
        except httpx.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise NexusError(f"Download failed: {type(exc).__name__}") from exc
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

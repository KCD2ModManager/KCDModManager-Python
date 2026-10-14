"""Check GitHub releases for a newer manager version."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from kcd_mod_manager import __version__
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.domain.versioning import compare_app_versions

log = logging.getLogger(__name__)

RELEASES_REPOSITORY = "KCD2ModManager/KCDModManager-Python"
"""GitHub repository whose latest release is compared with the running version."""
MANAGER_MOD_NUMBERS = {GameType.KCD1: 2119, GameType.KCD2: 187}
"""The manager's own Nexus Mods page for each game."""


def manager_page(game: GameType | None = None) -> str:
    game = game or GameType.KCD2
    return f"https://www.nexusmods.com/{game.nexus_domain}/mods/{MANAGER_MOD_NUMBERS[game]}"


DOWNLOAD_PAGE = manager_page(GameType.KCD2)


@dataclass(frozen=True, slots=True)
class AppUpdate:
    latest_version: str
    download_page: str


def check_for_app_update(
    current_version: str = __version__,
    repository: str = RELEASES_REPOSITORY,
    transport: httpx.BaseTransport | None = None,
) -> AppUpdate | None:
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            response = client.get(
                url, headers={"User-Agent": f"KCDModManager/{current_version}", "Accept": "application/json"}
            )
        if response.status_code != 200:
            log.info("Release check returned HTTP %s", response.status_code)
            return None
        tag = str(response.json().get("tag_name") or "")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.info("Release check failed: %s", type(exc).__name__)
        return None
    if tag and compare_app_versions(tag, current_version):
        return AppUpdate(tag.lstrip("vV"), DOWNLOAD_PAGE)
    return None

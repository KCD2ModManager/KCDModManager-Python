"""When to ask the user, once, to endorse the manager on Nexus Mods."""

from __future__ import annotations

from datetime import date

from kcd_mod_manager.application.settings import AppSettings

MIN_LAUNCHES = 10
MIN_DAYS = 7


def _first_launch(settings: AppSettings) -> date | None:
    try:
        return date.fromisoformat(settings.first_launch_date)
    except ValueError:
        return None


def record_launch(settings: AppSettings, today: date) -> None:
    settings.launch_count += 1
    if _first_launch(settings) is None:
        settings.first_launch_date = today.isoformat()


def should_ask_for_endorsement(settings: AppSettings, today: date) -> bool:
    if settings.endorse_prompt_done or settings.launch_count < MIN_LAUNCHES:
        return False
    first = _first_launch(settings)
    return first is not None and (today - first).days >= MIN_DAYS

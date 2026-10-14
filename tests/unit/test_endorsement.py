from __future__ import annotations

from datetime import date, timedelta

from kcd_mod_manager.application.endorsement import (
    MIN_DAYS,
    MIN_LAUNCHES,
    record_launch,
    should_ask_for_endorsement,
)
from kcd_mod_manager.application.settings import AppSettings

TODAY = date(2026, 10, 14)


def test_first_launch_is_remembered_and_counted() -> None:
    settings = AppSettings()
    record_launch(settings, TODAY)
    record_launch(settings, TODAY + timedelta(days=3))
    assert settings.launch_count == 2
    assert settings.first_launch_date == "2026-10-14"


def test_invalid_first_launch_date_is_replaced() -> None:
    settings = AppSettings(first_launch_date="garbage")
    record_launch(settings, TODAY)
    assert settings.first_launch_date == "2026-10-14"


def test_asks_only_after_enough_launches_and_days() -> None:
    first = TODAY - timedelta(days=MIN_DAYS)
    settings = AppSettings(launch_count=MIN_LAUNCHES - 1, first_launch_date=first.isoformat())
    assert not should_ask_for_endorsement(settings, TODAY)
    settings.launch_count = MIN_LAUNCHES
    assert should_ask_for_endorsement(settings, TODAY)
    assert not should_ask_for_endorsement(settings, TODAY - timedelta(days=1))
    settings.endorse_prompt_done = True
    assert not should_ask_for_endorsement(settings, TODAY)


def test_never_asks_without_a_first_launch_date() -> None:
    assert not should_ask_for_endorsement(AppSettings(launch_count=100), TODAY)

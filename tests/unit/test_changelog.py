"""Release-notes extraction used by the release workflow (scripts/changelog.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("changelog_script", ROOT / "scripts" / "changelog.py")
assert _spec and _spec.loader
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

SAMPLE = """# Changelog

## [Unreleased]

- not yet

## [1.2.0] - 2026-10-01

### Added

- **Bold** feature with `code` and a [link](https://example.com)
* star bullet

### Fixed

- a bug

## [1.1.0]

- older
"""


def test_section_returns_only_the_requested_version() -> None:
    notes = changelog.section(SAMPLE, "1.2.0")
    assert notes.startswith("### Added")
    assert "a bug" in notes
    assert "older" not in notes and "not yet" not in notes
    assert changelog.section(SAMPLE, "1.1.0") == "- older"
    assert changelog.section(SAMPLE, "9.9.9") == ""


def test_plain_strips_markdown() -> None:
    text = changelog.plain(changelog.section(SAMPLE, "1.2.0"))
    assert text == "Bold feature with code and a link\nstar bullet\na bug"


def test_current_version_has_a_changelog_entry() -> None:
    version = changelog.app_version()
    assert version
    assert changelog.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    assert changelog.main([version]) == 0


def test_mismatched_version_is_rejected() -> None:
    assert changelog.main(["0.0.1"]) == 1

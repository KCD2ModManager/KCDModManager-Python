"""Bundled data files (translations, images)."""

from __future__ import annotations

from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return RESOURCE_DIR.joinpath(*parts)

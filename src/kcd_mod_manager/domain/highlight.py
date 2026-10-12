"""Row highlight presets (light/dark variants), identical to the original manager."""

from __future__ import annotations

from kcd_mod_manager.domain.models import HighlightColor

PRESETS: dict[str, HighlightColor] = {
    "blue": HighlightColor("#E8F2FF", "#223246"),
    "green": HighlightColor("#E9F6EE", "#22392E"),
    "purple": HighlightColor("#F0ECFF", "#302A42"),
    "amber": HighlightColor("#FFF5E6", "#423521"),
    "red": HighlightColor("#FDEDEE", "#42262A"),
}


def preset(name: str) -> HighlightColor | None:
    return PRESETS.get(name.strip().lower())

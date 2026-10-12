"""Translations loaded from JSON files (converted from the original .resx resources).

Missing keys fall back to English, then to the key itself. ``{0}``-style placeholders are
formatted positionally like .NET's ``string.Format``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from kcd_mod_manager.application.settings import SUPPORTED_LANGUAGES
from kcd_mod_manager.resources import resource_path

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {"en": "English", "de": "Deutsch", "fr": "Français"}


def _load(language: str, directory: Path) -> dict[str, str]:
    path = directory / f"{language}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Could not load translations %s: %s", path, exc)
        return {}
    return {str(k): str(v).replace("\\n", "\n") for k, v in data.items()}


class Translator:
    def __init__(self, language: str = "en", directory: Path | None = None) -> None:
        self._directory = directory or resource_path("i18n")
        self._fallback = _load("en", self._directory)
        self.language = "en"
        self._strings = self._fallback
        self.set_language(language)

    def set_language(self, language: str) -> None:
        language = language if language in SUPPORTED_LANGUAGES else "en"
        self.language = language
        self._strings = self._fallback if language == "en" else _load(language, self._directory)

    def __call__(self, key: str, *args: object) -> str:
        text = self._strings.get(key) or self._fallback.get(key) or key
        if not args:
            return text
        try:
            return text.format(*args)
        except (IndexError, KeyError, ValueError):
            return text


_translator = Translator()


def tr(key: str, *args: object) -> str:
    return _translator(key, *args)


def set_language(language: str) -> None:
    _translator.set_language(language)


def current_language() -> str:
    return _translator.language

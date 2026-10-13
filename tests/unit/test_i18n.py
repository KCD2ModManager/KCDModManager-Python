from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kcd_mod_manager.application.settings import SUPPORTED_LANGUAGES
from kcd_mod_manager.domain.highlight import PRESETS
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.i18n import LANGUAGE_NAMES, Translator, detect_language
from kcd_mod_manager.resources import resource_path

SRC = Path(__file__).resolve().parents[2] / "src" / "kcd_mod_manager"
I18N = resource_path("i18n")


def used_keys() -> set[str]:
    keys: set[str] = set()
    for path in SRC.rglob("*.py"):
        keys.update(re.findall(r"""\btr\(\s*"([A-Za-z0-9_]+)\"""", path.read_text(encoding="utf-8")))
    keys.update(f"Highlight{name.capitalize()}" for name in PRESETS)
    keys.update(g.display_key for g in GameType)
    keys.update({"ButtonSortLoadOrder", "ButtonSortTitle", "ButtonSortCategory"})
    return keys


def test_every_used_key_exists_in_english() -> None:
    english = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    missing = sorted(used_keys() - english.keys())
    assert not missing, missing


@pytest.mark.parametrize("language", ["de", "fr", "zh"])
def test_translations_cover_the_used_keys(language: str) -> None:
    other = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
    untranslated = used_keys() - other.keys()
    assert len(untranslated) <= 15, sorted(untranslated)


def test_every_supported_language_has_a_file_and_a_name() -> None:
    for code in SUPPORTED_LANGUAGES:
        assert (I18N / f"{code}.json").is_file(), code
        assert code in LANGUAGE_NAMES, code


@pytest.mark.parametrize("language", ["de", "fr", "zh"])
def test_translations_keep_the_placeholders(language: str) -> None:
    english = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    other = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
    for key, text in other.items():
        if key in english:
            assert set(re.findall(r"\{\d+\}", text)) == set(re.findall(r"\{\d+\}", english[key])), key


@pytest.mark.parametrize(
    ("locales", "expected"),
    [
        (["de-DE", "en-US"], "de"),
        (["zh-Hans-CN"], "zh"),
        (["zh_TW"], "zh"),
        (["fr-CA"], "fr"),
        (["ja-JP", "fr-FR"], "fr"),
        (["ja-JP"], "en"),
        ([], "en"),
    ],
)
def test_detect_language_picks_the_first_supported_locale(locales: list[str], expected: str) -> None:
    assert detect_language(locales) == expected


def test_translator_formats_and_falls_back(tmp_path: Path) -> None:
    (tmp_path / "en.json").write_text(json.dumps({"A": "Hello {0}", "B": "line\\nbreak", "C": "en"}), "utf-8")
    (tmp_path / "de.json").write_text(json.dumps({"A": "Hallo {0}"}), "utf-8")
    t = Translator("de", tmp_path)
    assert t("A", "Welt") == "Hallo Welt"
    assert t("C") == "en"
    assert t("missing") == "missing"
    t.set_language("xx")
    assert t.language == "en"
    assert t("B") == "line\nbreak"
    assert t("A") == "Hello {0}"
    assert t("A", 1, 2) == "Hello 1"

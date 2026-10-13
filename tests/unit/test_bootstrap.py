from __future__ import annotations

from pathlib import Path

from kcd_mod_manager.bootstrap import load_settings
from kcd_mod_manager.infrastructure.app_paths import AppPaths
from kcd_mod_manager.infrastructure.credentials import MemoryCredentialStore


def test_first_run_starts_in_the_system_language(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    store, settings, first_run, imported = load_settings(paths, MemoryCredentialStore(), "zh")
    assert (first_run, imported) == (True, False)
    assert settings.language == "zh"
    assert store.load().language == "zh"


def test_existing_settings_keep_their_language(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    load_settings(paths, MemoryCredentialStore(), "de")
    _, settings, first_run, _ = load_settings(paths, MemoryCredentialStore(), "fr")
    assert not first_run
    assert settings.language == "de"

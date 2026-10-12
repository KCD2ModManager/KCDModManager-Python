from __future__ import annotations

from pathlib import Path

import pytest

from kcd_mod_manager.domain import manifest as m
from kcd_mod_manager.infrastructure import manifest_files as mf


def test_parse_with_explicit_mod_id() -> None:
    text = '<?xml version="1.0"?><kcd_mod><info><name> Sword </name><version>1.2</version><modid>sword</modid></info></kcd_mod>'
    parsed = m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=True)
    assert (parsed.info.mod_id, parsed.info.name, parsed.info.version) == ("sword", "Sword", "1.2")
    assert parsed.info.has_explicit_mod_id
    assert parsed.rewritten_text is None


def test_missing_mod_id_is_generated_and_written_when_allowed() -> None:
    text = "<kcd_mod><info><name>My Mod?</name><version>1.0</version></info></kcd_mod>"
    parsed = m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=True)
    assert parsed.info.mod_id == "My Mod"
    assert not parsed.info.has_explicit_mod_id
    assert parsed.rewritten_text is not None and "<modid>My Mod</modid>" in parsed.rewritten_text

    not_written = m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=False)
    assert not_written.rewritten_text is None


@pytest.mark.parametrize(
    "text",
    [
        "<kcd_mod><info><name>x</name></info></kcd_mod>",
        "<kcd_mod><info><version>1</version></info></kcd_mod>",
        "<kcd_mod><other/></kcd_mod>",
        "not xml",
    ],
)
def test_invalid_manifests(text: str) -> None:
    with pytest.raises(m.ManifestError):
        m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=False)


def test_xml_version_2_is_fixed() -> None:
    text = '<?xml version="2.0" encoding="utf-8"?><kcd_mod><info><name>a</name><version>1</version></info></kcd_mod>'
    parsed = m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=False)
    assert parsed.info.name == "a"


def test_bom_and_comments_are_preserved_on_update() -> None:
    text = "\ufeff<kcd_mod><!-- keep me --><info><name>a</name><version>1</version></info></kcd_mod>"
    updated = m.update_info_fields(text, {"gameVersion": "1.2.3"})
    assert "keep me" in updated
    assert m.read_info_field(updated, "gameVersion") == "1.2.3"


def test_generate_manifest_escapes_and_derives_version() -> None:
    text = m.generate_manifest("Swords & Shields-187-1-4-1700000000", renaming_enabled=True)
    parsed = m.parse_manifest(text, renaming_enabled=True, allow_write_mod_id=False)
    assert parsed.info.name == "Swords & Shields-187-1-4-1700000000"
    assert parsed.info.version == "1.4"
    assert parsed.info.description == m.GENERATED_DESCRIPTION


def test_manifest_file_operations(tmp_path: Path) -> None:
    folder = tmp_path / "MyMod"
    folder.mkdir()
    path = folder / "mod.manifest"
    path.write_text(
        '<?xml version="2.0"?><kcd_mod><info><name>N</name><version>1.0</version></info></kcd_mod>'
    )
    info = mf.parse_manifest_file(path, renaming_enabled=True, allow_write_mod_id=True)
    assert info is not None and info.mod_id == "N"
    content = path.read_text(encoding="utf-8")
    assert 'version="2.0"' not in content and "<modid>N</modid>" in content

    assert mf.update_manifest_fields(path, {"name": "Renamed"})
    assert mf.ensure_manifest_mod_id(path, "n")  # case-insensitive equal -> unchanged
    assert m.read_info_field(path.read_text(encoding="utf-8"), "modid") == "N"
    assert mf.find_manifest(folder) == path

    gen_folder = tmp_path / "Gen-1-2-3-4"
    gen_folder.mkdir()
    generated = mf.generate_manifest_file(gen_folder, renaming_enabled=True)
    gen_info = mf.parse_manifest_file(generated, renaming_enabled=True, allow_write_mod_id=False)
    assert gen_info is not None and gen_info.version == "2.3"


def test_invalid_manifest_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "mod.manifest"
    path.write_text("<broken", encoding="utf-8")
    assert mf.parse_manifest_file(path, renaming_enabled=True, allow_write_mod_id=True) is None
    assert not mf.update_manifest_fields(path, {"name": "x"})
    assert path.read_text(encoding="utf-8") == "<broken"

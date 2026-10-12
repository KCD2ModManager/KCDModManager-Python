"""``mod.manifest`` parsing and editing as pure text transformations.

Manifest layout used by KCD::

    <kcd_mod>
      <info>
        <name/><description/><author/><version/><modid/>[<gameVersion/>]
      </info>
    </kcd_mod>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.sax.saxutils import escape

from kcd_mod_manager.domain.models import ManifestInfo
from kcd_mod_manager.domain.naming import generate_mod_id, version_from_nexus_folder_name

MANIFEST_FILE_NAME = "mod.manifest"
GENERATED_DESCRIPTION = "auto generated manifest from kcd2 modmanager"
_BAD_DECLARATION = '<?xml version="2.0"'
_GOOD_DECLARATION = '<?xml version="1.0"'


class ManifestError(ValueError):
    """The manifest is not valid XML or lacks the required ``info/name`` and ``info/version``."""


@dataclass(frozen=True, slots=True)
class ParsedManifest:
    info: ManifestInfo
    rewritten_text: str | None
    """New file content if the parser assigned a generated mod id that should be persisted."""


def fix_xml_version(text: str) -> tuple[str, bool]:
    """Some mods ship ``<?xml version="2.0"`` which XML parsers reject."""
    if _BAD_DECLARATION in text:
        return text.replace(_BAD_DECLARATION, _GOOD_DECLARATION), True
    return text, False


def _parse(text: str) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    try:
        parser.feed(text.lstrip("\ufeff"))
        return parser.close()
    except ET.ParseError as exc:
        raise ManifestError(str(exc)) from exc


def _find_info(root: ET.Element) -> ET.Element | None:
    return root if root.tag == "info" else root.find(".//info")


def _value(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return "".join(element.itertext()).strip()


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _set_child(info: ET.Element, tag: str, value: str) -> None:
    child = info.find(tag)
    if child is None:
        child = ET.SubElement(info, tag)
    for grandchild in list(child):
        child.remove(grandchild)
    child.text = value


def parse_manifest(text: str, *, renaming_enabled: bool, allow_write_mod_id: bool) -> ParsedManifest:
    root = _parse(fix_xml_version(text)[0])
    info = _find_info(root)
    if info is None:
        raise ManifestError("manifest has no <info> element")
    name = _value(info.find("name"))
    version = _value(info.find("version"))
    if not name or not version:
        raise ManifestError("manifest requires <name> and <version>")

    explicit_id = _value(info.find("modid"))
    rewritten: str | None = None
    if explicit_id:
        mod_id = explicit_id
    else:
        mod_id = generate_mod_id(name, renaming_enabled)
        if allow_write_mod_id:
            _set_child(info, "modid", mod_id)
            rewritten = _serialize(root)

    return ParsedManifest(
        info=ManifestInfo(
            mod_id=mod_id,
            name=name,
            version=version,
            description=_value(info.find("description")) or "",
            author=_value(info.find("author")) or "",
            game_version=_value(info.find("gameVersion")) or None,
            has_explicit_mod_id=bool(explicit_id),
        ),
        rewritten_text=rewritten,
    )


def generate_manifest(folder_name: str, *, renaming_enabled: bool) -> str:
    """Manifest for a mod that ships only ``.pak`` files, derived from its folder name."""
    name = folder_name.strip()
    version = version_from_nexus_folder_name(folder_name)
    mod_id = generate_mod_id(name, renaming_enabled)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<kcd_mod>\n"
        "  <info>\n"
        f"    <name>{escape(name)}</name>\n"
        f"    <description>{GENERATED_DESCRIPTION}</description>\n"
        "    <author>N/A</author>\n"
        f"    <version>{escape(version)}</version>\n"
        f"    <modid>{escape(mod_id)}</modid>\n"
        "  </info>\n"
        "</kcd_mod>\n"
    )


def update_info_fields(text: str, fields: dict[str, str]) -> str:
    """Set (or create) children of ``<info>``, e.g. ``{"name": ..., "modid": ...}``."""
    root = _parse(fix_xml_version(text)[0])
    info = _find_info(root)
    if info is None:
        raise ManifestError("manifest has no <info> element")
    for tag, value in fields.items():
        _set_child(info, tag, value)
    return _serialize(root)


def read_info_field(text: str, tag: str) -> str | None:
    root = _parse(fix_xml_version(text)[0])
    info = _find_info(root)
    return None if info is None else _value(info.find(tag))

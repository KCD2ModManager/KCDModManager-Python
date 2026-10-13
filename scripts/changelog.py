"""Extract the release notes for one version from CHANGELOG.md.

    python scripts/changelog.py 5.0.1 --notes release-notes.md --plain nexus-changelog.txt

Exits with an error if the version has no (or an empty) section, or if it does not match the
application version, so a release can never go out without notes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_FILE = ROOT / "src" / "kcd_mod_manager" / "__init__.py"

_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def section(text: str, version: str) -> str:
    """Body of the ``## [version]`` section (without the heading), stripped; empty if missing."""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if inside:
                break
            inside = match.group("version") == version
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines).strip()


def plain(markdown: str) -> str:
    """Nexus Mods style: one entry per line, without bullets, headings, links or emphasis."""
    out: list[str] = []
    for line in markdown.splitlines():
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"(\*\*|__|`)", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "", line).strip()
        if line and not line.startswith("#"):
            out.append(line)
    return "\n".join(out)


def app_version() -> str:
    match = re.search(r'__version__ = "([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="version without the leading v, e.g. 5.0.1")
    parser.add_argument("--notes", type=Path, help="write the Markdown section here")
    parser.add_argument("--plain", type=Path, help="write the plain-text version here")
    args = parser.parse_args(argv)

    if args.version != app_version():
        print(f"error: tag version {args.version} != __version__ {app_version()}", file=sys.stderr)
        return 1
    notes = section(CHANGELOG.read_text(encoding="utf-8"), args.version)
    if not notes:
        print(f"error: CHANGELOG.md has no entry for [{args.version}]", file=sys.stderr)
        return 1
    if args.notes:
        args.notes.write_text(notes + "\n", encoding="utf-8")
    if args.plain:
        args.plain.write_text(plain(notes) + "\n", encoding="utf-8")
    if not args.notes and not args.plain:
        print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

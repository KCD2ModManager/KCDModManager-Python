"""One-off helper: convert .NET .resx string tables into the JSON catalogs used by the app.

Usage: python scripts/convert_resx.py <dir-with-resx-files> <output-dir>

The source directory is only read. Strings.resx and Messages.resx are merged per language;
on key collisions the Messages value wins only if Strings does not define the key.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TABLES = ("Strings", "Messages")
LANGUAGES = {"en": "", "de": ".de", "fr": ".fr"}


def read_resx(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    result: dict[str, str] = {}
    for data in root.iter("data"):
        name = data.get("name")
        value = data.find("value")
        if name and value is not None and data.get("type") is None:
            result[name] = value.text or ""
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=True)
    for lang, suffix in LANGUAGES.items():
        merged: dict[str, str] = {}
        for table in reversed(TABLES):
            path = source / f"{table}{suffix}.resx"
            if not path.exists():
                continue
            for key, value in read_resx(path).items():
                if key in merged and merged[key] != value:
                    print(f"[{lang}] collision on {key!r}: keeping {table} value")
                merged[key] = value
        out = target / f"{lang}.json"
        out.write_text(
            json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {out} ({len(merged)} keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

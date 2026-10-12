"""Read the file version of a Windows executable without Windows APIs (works on Linux too)."""

from __future__ import annotations

import mmap
import struct
from pathlib import Path

_FIXED_FILE_INFO_SIGNATURE = struct.pack("<I", 0xFEEF04BD)


def read_file_version(path: Path) -> str | None:
    """Return ``major.minor.build.revision`` from the VS_FIXEDFILEINFO resource, if present."""
    try:
        with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            index = data.rfind(_FIXED_FILE_INFO_SIGNATURE)
            if index < 0 or index + 16 > len(data):
                return None
            _sig, _struct_version, ms, ls = struct.unpack_from("<IIII", data, index)
    except (OSError, ValueError, struct.error):
        return None
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"

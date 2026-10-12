"""Command line entry point: ``kcd-mod-manager`` / ``python -m kcd_mod_manager``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kcd_mod_manager import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kcd-mod-manager", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Use this folder for settings, profiles and logs (default: shared KCDModManager folder; "
        "can also be set with KCDMM_DATA_DIR).",
    )
    parser.add_argument(
        "--offline", action="store_true", help="Skip Nexus Mods and update checks at startup."
    )
    args = parser.parse_args(argv)

    from kcd_mod_manager.ui.app import run

    return run(args.data_dir, online=not args.offline)


if __name__ == "__main__":
    sys.exit(main())

"""Command line entry point: ``kcd-mod-manager`` / ``python -m kcd_mod_manager``."""

from __future__ import annotations

import argparse
import os
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
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-test-report", type=Path, help=argparse.SUPPRESS)
    if sys.stdout is None:  # windowed (frozen) build: argparse output would fail
        sys.stdout = sys.stderr = Path(os.devnull).open("w", encoding="utf-8")  # noqa: SIM115
    args = parser.parse_args(argv)

    if args.self_test:
        from kcd_mod_manager.selftest import run_self_test

        return run_self_test(args.self_test_report)

    from kcd_mod_manager.ui.app import run

    return run(args.data_dir, online=not args.offline)


if __name__ == "__main__":
    sys.exit(main())

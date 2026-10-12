"""Render the main window against a throw-away fake game and save screenshots.

Uses only temporary directories (never the real data folder or a real game install), so it is
safe to run on a developer machine or in CI:

    uv run python scripts/smoke_screenshot.py out/
"""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

MANIFEST = (
    '<?xml version="1.0" encoding="utf-8"?>\n<kcd_mod><info><name>{name}</name>'
    "<description>demo</description><author>demo</author><version>{version}</version><modid>{mod_id}</modid>"
    "<gameVersion>{game}</gameVersion></info></kcd_mod>\n"
)


def make_fake_game(root: Path) -> Path:
    game = root / "steamapps" / "common" / "KingdomComeDeliverance2"
    exe = game / "Bin" / "Win64MasterMasterSteamPGO" / "KingdomCome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    (game / "Data").mkdir()
    (game / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    mods = game / "Mods"
    demo = [
        ("better_lockpicking", "Better Lockpicking", "1.4.2", "1.2"),
        ("no_helmet_view", "No Helmet View", "2.0", "1.2"),
        ("realistic_weather", "Realistic Weather Overhaul", "0.9.1", "1.1"),
        ("hardcore_tweaks", "Hardcore Tweaks", "3.1", "1.2"),
    ]
    for mod_id, name, version, game_version in demo:
        folder = mods / mod_id
        folder.mkdir(parents=True)
        (folder / "mod.manifest").write_text(
            MANIFEST.format(name=name, version=version, mod_id=mod_id, game=game_version), encoding="utf-8"
        )
        (folder / "Data").mkdir()
        with zipfile.ZipFile(folder / "Data" / f"{mod_id}.pak", "w") as pak:
            pak.writestr("Libs/Tables/shared.xml" if mod_id != "no_helmet_view" else f"{mod_id}.xml", b"x")
    (mods / "mod_order.txt").write_text(
        "better_lockpicking\nno_helmet_view\n# realistic_weather\nhardcore_tweaks\n", encoding="utf-8"
    )
    return game


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "smoke-output").resolve()
    out.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="kcdmm-smoke-"))
    os.environ["KCDMM_DATA_DIR"] = str(temp / "data")
    for variable in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        os.environ[variable] = str(temp / variable.lower())
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from kcd_mod_manager.bootstrap import build_context
    from kcd_mod_manager.domain.highlight import PRESETS
    from kcd_mod_manager.domain.models import GameType
    from kcd_mod_manager.infrastructure.app_paths import AppPaths
    from kcd_mod_manager.infrastructure.credentials import MemoryCredentialStore
    from kcd_mod_manager.infrastructure.game_detection import GameDetector
    from kcd_mod_manager.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    game = make_fake_game(temp / "library")
    ctx = build_context(AppPaths(temp / "data"), credentials=MemoryCredentialStore())
    ctx.session.detector = GameDetector(lambda: [], lambda: [], lambda _g: [])
    ctx.settings.set_game_path(GameType.KCD2, str(game))
    ctx.settings.window_geometry = ""

    window = MainWindow(ctx, online=False)
    window.resize(1180, 640)
    if not window.start():
        return 1
    window.show()
    while window.tasks.busy or window._scan_cancel is not None:
        app.processEvents()
    category = ctx.session.create_category("Gameplay")
    for mod in ctx.session.mods[:2]:
        ctx.session.set_category(mod, category.id)
    ctx.session.set_highlight(ctx.session.mods[3], PRESETS["amber"])
    ctx.session.toggle_separator(ctx.session.mods[1])
    window.refresh_view()
    app.processEvents()

    for dark in (False, True):
        ctx.settings.is_dark_mode = dark
        window.apply_theme()
        app.processEvents()
        target = out / f"main-window-{'dark' if dark else 'light'}.png"
        window.grab().save(str(target))
        print(target)
    window.close()
    print(
        f"mods={len(ctx.session.mods)} conflicts={len(ctx.session.conflicts)} profile={ctx.session.selected_profile}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

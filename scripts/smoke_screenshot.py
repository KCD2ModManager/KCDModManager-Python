"""Render the main window against a throw-away fake game and save screenshots.

Uses only temporary directories (never the real data folder or a real game install), so it is
safe to run on a developer machine or in CI:

    uv run python scripts/smoke_screenshot.py out/
    uv run python scripts/smoke_screenshot.py out-zh/ zh    # in another language
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
    from kcd_mod_manager.i18n import set_language
    from kcd_mod_manager.infrastructure.app_paths import AppPaths
    from kcd_mod_manager.infrastructure.credentials import MemoryCredentialStore
    from kcd_mod_manager.infrastructure.game_detection import GameDetector
    from kcd_mod_manager.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    game = make_fake_game(temp / "library")
    language = sys.argv[2] if len(sys.argv) > 2 else "en"
    ctx = build_context(
        AppPaths(temp / "data"), credentials=MemoryCredentialStore(), system_language=language
    )
    set_language(language)
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

    from kcd_mod_manager.i18n import tr
    from kcd_mod_manager.ui.dialogs import (
        CategoryManagerDialog,
        ConflictDialog,
        DeleteConfirmDialog,
        GameSelectionDialog,
        MessageDialog,
    )
    from kcd_mod_manager.ui.settings_dialog import SettingsDialog, SettingsHooks

    def save(widget: object, name: str, theme: str) -> None:
        app.processEvents()
        target = out / f"{name}-{theme}.png"
        widget.grab().save(str(target))  # type: ignore[attr-defined]
        print(target)

    def show_and_save(widget: object, name: str, theme: str) -> None:
        widget.show()  # type: ignore[attr-defined]
        save(widget, name, theme)
        widget.close()  # type: ignore[attr-defined]

    hooks = SettingsHooks(
        save=lambda: None,
        theme_changed=lambda _d: None,
        mod_order_changed=lambda _e: True,
        set_executable=lambda g, p: ctx.session.set_manual_install(g, p),
        ignored_mods=lambda: ctx.session.mods[:1],
        unignore=lambda _m: None,
        create_backup=lambda: None,
        language_changed=lambda _l: None,
        view_changed=lambda: None,
        open_backups=lambda: None,
    )
    for dark in (False, True):
        theme = "dark" if dark else "light"
        ctx.settings.is_dark_mode = dark
        window.apply_theme()
        save(window, "main-window", theme)
        window.compact_button.click()
        save(window, "main-window-compact", theme)
        window.compact_button.click()

        settings = SettingsDialog(window, ctx.settings, dict(ctx.session.installs), hooks)
        settings.show()
        for page in ("general", "backups", "conflicts"):
            settings.show_page(page)
            save(settings, f"settings-{page}", theme)
        settings.close()

        show_and_save(
            GameSelectionDialog(window, dict(ctx.session.installs), ctx.session.set_manual_install),
            "game-selection",
            theme,
        )
        names = {m.id: m.name for m in ctx.session.mods}
        show_and_save(ConflictDialog(window, ctx.session.conflicts, names, set()), "conflicts", theme)
        show_and_save(
            MessageDialog(
                window,
                "question",
                tr("DialogTitleQuestion"),
                tr("DeleteProfileConfirm", "Default"),
                ["YesButton", "NoButton"],
            ),
            "message",
            theme,
        )
        usage = {category.id: 2}
        show_and_save(CategoryManagerDialog(window, ctx.session.categories, usage), "categories", theme)
        show_and_save(DeleteConfirmDialog(window, ctx.session.mods[0].name), "delete-confirm", theme)
        menu = window._mod_menu(ctx.session.mods[0])
        menu.popup(window.mapToGlobal(window.rect().center()))
        save(menu, "context-menu", theme)
        menu.close()
    window.close()
    session = ctx.session
    print(f"mods={len(session.mods)} conflicts={len(session.conflicts)} profile={session.selected_profile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Themed widgets, icons and dialogs, driven headless."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from kcd_mod_manager.ui import icons
from kcd_mod_manager.ui.dialogs import MessageDialog
from kcd_mod_manager.ui.theme import LIGHT, apply_theme, current_palette
from kcd_mod_manager.ui.widgets import IconButton, Pill, SearchBox, ToggleSwitch, refresh_theme

pytestmark = pytest.mark.ui


def test_every_bundled_icon_renders_in_any_color(qtbot: QtBot) -> None:
    names = icons.available()
    assert {"update", "up", "down", "delete", "folder", "more", "warning_filled"} <= set(names)
    for name in names:
        assert icons._SOURCE_FILL in icons.svg_data(name, icons._SOURCE_FILL).decode()
        image = icons.pixmap(name, "#FF0000", 16, 1.0).toImage()
        assert not image.isNull()
        colors = {
            image.pixelColor(x, y).name()
            for x in range(16)
            for y in range(16)
            if image.pixelColor(x, y).alpha() == 255
        }
        assert colors <= {"#ff0000"}, name
    with pytest.raises(KeyError):
        icons.pixmap("does-not-exist", "#000000")


def test_stylesheet_images_are_written_once(qtbot: QtBot) -> None:
    first = icons.stylesheet_url("checkmark_filled", "#FFFFFF")
    assert first == icons.stylesheet_url("checkmark_filled", "#FFFFFF")
    assert first.endswith(".svg")


def test_toggle_switch_toggles_and_emits(qtbot: QtBot) -> None:
    switch = ToggleSwitch()
    qtbot.addWidget(switch)
    switch.show()
    seen: list[bool] = []
    switch.toggled.connect(seen.append)
    qtbot.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert switch.isChecked() and seen == [True]
    qtbot.waitUntil(lambda: switch.offset == 1.0)
    switch.blockSignals(True)
    switch.setChecked(False)
    switch.blockSignals(False)
    switch.grab()
    assert switch.offset == 0.0 and seen == [True]
    assert switch.sizeHint().width() == ToggleSwitch.WIDTH


def test_theme_switch_refreshes_icons_and_badges(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    apply_theme(app, False)
    button = IconButton("delete", "error")
    pill = Pill("3/4", "success")
    search = SearchBox("Search")
    for widget in (button, pill, search):
        qtbot.addWidget(widget)
    assert current_palette() is LIGHT
    assert pill.sizeHint().width() > pill.sizeHint().height()
    search.setText("x")
    assert search.clear_action.isVisible()
    search.clear_action.trigger()
    assert search.text() == "" and not search.clear_action.isVisible()
    apply_theme(app, True)
    refresh_theme(button)
    assert current_palette().error != LIGHT.error
    assert not button.icon().isNull()
    pill.grab()
    apply_theme(app, False)


def test_message_dialog_reports_clicked_button(qtbot: QtBot) -> None:
    dialog = MessageDialog(None, "question", "Title", "Proceed?", ("YesButton", "NoButton"))
    qtbot.addWidget(dialog)
    buttons = dialog.findChildren(QPushButton)
    assert [b.objectName() for b in buttons] == ["dialogPrimary", ""]
    buttons[1].click()
    assert dialog.clicked_index == 1

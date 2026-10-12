"""Light and dark themes (palette values taken from the original manager's theme dictionaries)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Palette:
    window: str
    panel: str
    row_even: str
    row_odd: str
    row_hover: str
    selected: str
    text: str
    text_secondary: str
    text_disabled: str
    primary: str
    primary_hover: str
    primary_pressed: str
    secondary: str
    secondary_border: str
    input_bg: str
    input_border: str
    separator: str
    success: str
    warning: str
    error: str
    tooltip_bg: str
    tooltip_fg: str
    scroll_thumb: str
    scroll_thumb_hover: str


LIGHT = Palette(
    window="#FAFAFA",
    panel="#FFFFFF",
    row_even="#FFFFFF",
    row_odd="#F5F5F5",
    row_hover="#E8F4F8",
    selected="#D0E8F0",
    text="#1A1A1A",
    text_secondary="#666666",
    text_disabled="#999999",
    primary="#0078D4",
    primary_hover="#106EBE",
    primary_pressed="#005A9E",
    secondary="#F3F3F3",
    secondary_border="#D1D1D1",
    input_bg="#FFFFFF",
    input_border="#D1D1D1",
    separator="#E0E0E0",
    success="#107C10",
    warning="#FFB900",
    error="#E81123",
    tooltip_bg="#2D2D30",
    tooltip_fg="#FFFFFF",
    scroll_thumb="#CCCCCC",
    scroll_thumb_hover="#999999",
)

DARK = Palette(
    window="#1E1E1E",
    panel="#252526",
    row_even="#2D2D30",
    row_odd="#3E3E42",
    row_hover="#3F3F46",
    selected="#094771",
    text="#FFFFFF",
    text_secondary="#CCCCCC",
    text_disabled="#808080",
    primary="#0E639C",
    primary_hover="#1177BB",
    primary_pressed="#094771",
    secondary="#3F3F46",
    secondary_border="#505052",
    input_bg="#3C3C3C",
    input_border="#505052",
    separator="#3F3F46",
    success="#6FCF97",
    warning="#FFB900",
    error="#F48771",
    tooltip_bg="#2D2D30",
    tooltip_fg="#FFFFFF",
    scroll_thumb="#3F3F46",
    scroll_thumb_hover="#505052",
)


def palette_for(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
QWidget {{ color: {p.text}; background-color: {p.window}; }}
QMainWindow, QDialog {{ background-color: {p.window}; }}
QFrame#panel, QWidget#panel {{ background-color: {p.panel}; border: 1px solid {p.separator}; border-radius: 6px; }}
QLabel {{ background: transparent; }}
QLabel#secondary {{ color: {p.text_secondary}; }}
QLabel#premiumBadge {{
    color: #1A1A1A; font-weight: bold; padding: 1px 6px; border: 1px solid #FF8C00; border-radius: 8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFD700, stop:1 #FFA500);
}}
QLabel#countBadge {{
    color: #FFFFFF; background-color: {p.error}; border-radius: 8px; padding: 0px 6px; font-weight: bold;
}}
QPushButton, QToolButton {{
    background-color: {p.secondary}; color: {p.text}; border: 1px solid {p.secondary_border};
    border-radius: 4px; padding: 5px 12px;
}}
QToolButton {{ padding: 4px 6px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {p.primary}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {p.primary_pressed}; color: #FFFFFF; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p.text_disabled}; border-color: {p.separator}; }}
QPushButton#primary {{ background-color: {p.primary}; color: #FFFFFF; border-color: {p.primary}; font-weight: bold; }}
QPushButton#primary:hover {{ background-color: {p.primary_hover}; }}
QPushButton#primary:disabled {{ background-color: {p.secondary}; color: {p.text_disabled}; }}
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.input_border};
    border-radius: 4px; padding: 4px 6px; selection-background-color: {p.primary};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {p.primary}; }}
QComboBox QAbstractItemView {{
    background-color: {p.panel}; color: {p.text}; selection-background-color: {p.selected};
    selection-color: {p.text}; border: 1px solid {p.input_border};
}}
QListView, QListWidget, QTreeWidget, QTableWidget {{
    background-color: {p.panel}; color: {p.text}; border: 1px solid {p.separator}; border-radius: 4px;
    alternate-background-color: {p.row_odd}; outline: 0;
}}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {p.selected}; color: {p.text};
}}
QHeaderView::section {{
    background-color: {p.secondary}; color: {p.text}; border: none; border-bottom: 1px solid {p.separator};
    padding: 4px;
}}
QMenuBar {{ background-color: {p.panel}; border-bottom: 1px solid {p.separator}; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected, QMenu::item:selected {{ background-color: {p.selected}; color: {p.text}; }}
QMenu {{ background-color: {p.panel}; border: 1px solid {p.separator}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 20px; }}
QMenu::item:disabled {{ color: {p.text_disabled}; }}
QMenu::separator {{ height: 1px; background: {p.separator}; margin: 4px 8px; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QGroupBox {{ border: 1px solid {p.separator}; border-radius: 6px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p.text_secondary}; }}
QToolTip {{ background-color: {p.tooltip_bg}; color: {p.tooltip_fg}; border: 1px solid #3F3F46; padding: 4px; }}
QProgressBar {{
    background-color: {p.input_bg}; border: 1px solid {p.input_border}; border-radius: 4px;
    text-align: center; color: {p.text};
}}
QProgressBar::chunk {{ background-color: {p.primary}; border-radius: 3px; }}
QStatusBar {{ background-color: {p.panel}; border-top: 1px solid {p.separator}; }}
QScrollBar:vertical {{ background: {p.window}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p.scroll_thumb}; min-height: 24px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {p.scroll_thumb_hover}; }}
QScrollBar:horizontal {{ background: {p.window}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {p.scroll_thumb}; min-width: 24px; border-radius: 5px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def apply_theme(app: QApplication, dark: bool) -> Palette:
    p = palette_for(dark)
    app.setStyle("Fusion")
    qpal = QPalette()
    qpal.setColor(QPalette.ColorRole.Window, QColor(p.window))
    qpal.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.Base, QColor(p.panel))
    qpal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.row_odd))
    qpal.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.Button, QColor(p.secondary))
    qpal.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    qpal.setColor(QPalette.ColorRole.Highlight, QColor(p.primary))
    qpal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    qpal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_disabled))
    qpal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.tooltip_bg))
    qpal.setColor(QPalette.ColorRole.ToolTipText, QColor(p.tooltip_fg))
    app.setPalette(qpal)
    app.setStyleSheet(stylesheet(p))
    return p

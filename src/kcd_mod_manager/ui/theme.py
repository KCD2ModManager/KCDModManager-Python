"""Light and dark themes (palette values taken from the original manager's theme dictionaries)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from kcd_mod_manager.ui import icons

FONT_FAMILIES = [
    "Segoe UI",
    "Cantarell",
    "Noto Sans",
    "Ubuntu",
    "DejaVu Sans",
    "Microsoft YaHei UI",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "sans-serif",
]


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
    button_disabled: str
    button_disabled_border: str
    secondary: str
    secondary_border: str
    input_bg: str
    input_border: str
    input_disabled: str
    separator: str
    accent: str
    accent_text: str
    """Accent for glyphs and links on panel backgrounds (the dark accent is too dim for text)."""
    success: str
    warning: str
    error: str
    toggle_on: str
    toggle_off: str
    menu_hover: str
    menu_highlight: str
    tooltip_bg: str
    tooltip_fg: str
    tooltip_border: str
    scroll_thumb: str
    scroll_thumb_hover: str
    scroll_thumb_pressed: str
    combo_arrow: str


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
    button_disabled="#E0E0E0",
    button_disabled_border="#CCCCCC",
    secondary="#F3F3F3",
    secondary_border="#D1D1D1",
    input_bg="#FFFFFF",
    input_border="#D1D1D1",
    input_disabled="#F5F5F5",
    separator="#E0E0E0",
    accent="#0078D4",
    accent_text="#0078D4",
    success="#107C10",
    warning="#FFB900",
    error="#E81123",
    toggle_on="#107C10",
    toggle_off="#CCCCCC",
    menu_hover="#E8F4F8",
    menu_highlight="#D0E8F0",
    tooltip_bg="#2D2D30",
    tooltip_fg="#FFFFFF",
    tooltip_border="#3F3F46",
    scroll_thumb="#CCCCCC",
    scroll_thumb_hover="#999999",
    scroll_thumb_pressed="#0078D4",
    combo_arrow="#666666",
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
    button_disabled="#3F3F46",
    button_disabled_border="#505052",
    secondary="#3F3F46",
    secondary_border="#505052",
    input_bg="#3C3C3C",
    input_border="#505052",
    input_disabled="#2D2D30",
    separator="#3F3F46",
    accent="#0E639C",
    accent_text="#3794FF",
    success="#6FCF97",
    warning="#FFB900",
    error="#F48771",
    toggle_on="#6FCF97",
    toggle_off="#505052",
    menu_hover="#3F3F46",
    menu_highlight="#094771",
    tooltip_bg="#2D2D30",
    tooltip_fg="#FFFFFF",
    tooltip_border="#3F3F46",
    scroll_thumb="#3F3F46",
    scroll_thumb_hover="#505052",
    scroll_thumb_pressed="#0E639C",
    combo_arrow="#CCCCCC",
)


def palette_for(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def current_palette() -> Palette:
    app = QApplication.instance()
    dark = bool(app.property("kcdmmDark")) if app is not None else False
    return palette_for(dark)


def stylesheet(p: Palette) -> str:
    check = icons.stylesheet_url("checkmark_filled", "#FFFFFF")
    down = icons.stylesheet_url("chevron_down", p.combo_arrow)
    down_disabled = icons.stylesheet_url("chevron_down", p.text_disabled)
    up = icons.stylesheet_url("chevron_up", p.combo_arrow)
    submenu = icons.stylesheet_url("chevron_right", p.text_secondary)
    return f"""
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog, QMessageBox {{ background-color: {p.window}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QLabel#secondary {{ color: {p.text_secondary}; }}
QLabel#hint {{ color: {p.text_secondary}; font-size: 12px; font-style: italic; }}
QLabel#sectionTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 600; }}
QLabel#dialogHeader {{ font-size: 16px; font-weight: 600; }}
QLabel#fieldLabel {{ font-size: 13px; font-weight: 600; }}
QLabel#gameName {{ color: {p.accent_text}; font-weight: bold; font-size: 13px; }}
QLabel#statusText {{ color: {p.text_secondary}; font-size: 12px; }}
QLabel#cardTitle {{ font-size: 14px; }}
QLabel#cardDescription {{ color: {p.text_secondary}; font-size: 12px; }}
QLabel#username {{ font-size: 12px; font-weight: 600; }}

QFrame#card, QWidget#card {{
    background-color: {p.panel}; border: 1px solid {p.separator}; border-radius: 4px;
}}
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#card QRadioButton {{ background: transparent; }}
QFrame#gameCard {{ background-color: {p.panel}; border: 2px solid {p.separator}; border-radius: 8px; }}
QFrame#gameCard:hover {{ border: 2px solid {p.accent_text}; }}
QFrame#footerBar {{ background-color: {p.panel}; border: none; border-top: 1px solid {p.separator}; }}
QFrame#footerBar QLabel, QFrame#footerBar QCheckBox {{ background: transparent; }}
QFrame#sidebar {{ background-color: {p.panel}; border: none; border-right: 1px solid {p.separator}; }}
QFrame#accountBox {{ background-color: {p.panel}; border: 1px solid {p.separator}; border-radius: 4px; }}
QFrame#hline {{ background-color: {p.separator}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#vline {{ background-color: {p.separator}; border: none; max-width: 1px; min-width: 1px; }}

/* ---------------------------------------------------------------- buttons */
QPushButton, QToolButton {{
    background-color: {p.secondary}; color: {p.text}; border: 1px solid {p.secondary_border};
    border-radius: 4px; padding: 4px 10px; min-height: 18px; font-size: 12px;
}}
QPushButton {{ min-width: 40px; }}
QPushButton:hover, QToolButton:hover {{ border-color: {p.primary}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {p.selected}; }}
QPushButton:disabled, QToolButton:disabled {{
    color: {p.text_disabled}; background-color: {p.input_disabled}; border-color: {p.separator};
}}
QPushButton:focus {{ outline: none; }}
QPushButton#toggleButton:checked {{ background-color: {p.menu_highlight}; border-color: {p.accent_text}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#primary, QToolButton#primary {{
    background-color: {p.primary}; color: #FFFFFF; border: 1px solid {p.primary};
    font-size: 14px; font-weight: 600; min-height: 38px; padding: 0 14px; text-align: center;
}}
QPushButton#primary:hover, QToolButton#primary:hover {{ background-color: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton#primary:pressed, QToolButton#primary:pressed {{ background-color: {p.primary_pressed}; border-color: {p.primary_pressed}; }}
QPushButton#primary:disabled, QToolButton#primary:disabled {{
    background-color: {p.button_disabled}; border-color: {p.button_disabled_border}; color: {p.text_disabled};
}}
QPushButton#dialogPrimary {{
    background-color: {p.primary}; color: #FFFFFF; border: 1px solid {p.primary}; font-weight: 600;
}}
QPushButton#dialogPrimary:hover {{ background-color: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton#dialogPrimary:pressed {{ background-color: {p.primary_pressed}; }}
QPushButton#navButton {{
    background: transparent; border: none; border-left: 3px solid transparent; border-radius: 4px;
    text-align: left; padding: 8px 10px; font-size: 13px; min-height: 20px; min-width: 0;
}}
QPushButton#navButton:hover {{ background-color: {p.menu_hover}; }}
QPushButton#navButton:pressed {{ background-color: {p.selected}; }}
QPushButton#navButton:checked {{ background-color: {p.menu_highlight}; border-left: 3px solid {p.accent_text}; }}
QPushButton#navButton:disabled {{ background: transparent; color: {p.text_disabled}; }}
QToolButton#iconButton {{
    background: transparent; border: none; border-radius: 4px; padding: 0; min-height: 0;
}}
QToolButton#iconButton:hover {{ background-color: {p.row_hover}; }}
QToolButton#iconButton:pressed {{ background-color: {p.selected}; }}
QToolButton#iconButton:disabled {{ background: transparent; }}

/* ---------------------------------------------------------------- inputs */
QLineEdit, QPlainTextEdit, QSpinBox {{
    background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.input_border};
    border-radius: 3px; padding: 5px 8px; selection-background-color: {p.primary}; selection-color: #FFFFFF;
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover {{ border-color: {p.primary}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 2px solid {p.primary}; padding: 4px 7px; }}
QLineEdit:disabled, QSpinBox:disabled {{
    background-color: {p.input_disabled}; border-color: {p.separator}; color: {p.text_disabled};
}}
QLineEdit#search {{ font-size: 15px; border-radius: 4px; padding: 6px 8px; }}
QLineEdit#search:focus {{ padding: 5px 7px; }}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color: {p.row_hover}; }}
QSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}

QComboBox {{
    background-color: {p.input_bg}; color: {p.text}; border: 1px solid {p.input_border};
    border-radius: 3px; padding: 3px 8px; min-height: 20px; font-size: 12px;
}}
QComboBox:hover, QComboBox:focus, QComboBox:on {{ border-color: {p.primary}; }}
QComboBox:disabled {{ background-color: {p.input_disabled}; border-color: {p.separator}; color: {p.text_disabled}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{down_disabled}"); }}
QComboBox QAbstractItemView {{
    background-color: {p.panel}; color: {p.text}; border: 1px solid {p.separator}; border-radius: 4px;
    padding: 4px; outline: 0; selection-background-color: {p.menu_highlight}; selection-color: {p.text};
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 0 6px; border-radius: 2px; }}
QComboBox QAbstractItemView::item:hover {{ background-color: {p.menu_hover}; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 3px; border: 1px solid {p.input_border}; background: {p.input_bg};
}}
QCheckBox::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked {{ background-color: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ background-color: {p.input_disabled}; border-color: {p.separator}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px; border: 1px solid {p.input_border}; background: {p.input_bg};
}}
QRadioButton::indicator:hover {{ border-color: {p.primary}; }}
QRadioButton::indicator:checked {{ border: 5px solid {p.primary}; width: 8px; height: 8px; background: #FFFFFF; }}
QRadioButton::indicator:disabled {{ background-color: {p.input_disabled}; border-color: {p.separator}; }}

/* ---------------------------------------------------------------- lists */
QListView, QListWidget, QTreeWidget, QTableWidget {{
    background-color: {p.panel}; color: {p.text}; border: 1px solid {p.separator}; border-radius: 4px;
    alternate-background-color: {p.row_odd}; outline: 0;
}}
QListView#modList {{ border: none; background-color: {p.window}; padding: 0; }}
QTreeWidget#conflictTree {{ border: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: 2px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {p.row_hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {p.selected}; color: {p.text};
}}
QListWidget#cardList {{ background: transparent; border: none; padding: 0; }}
QListWidget#cardList::item {{
    padding: 0 10px; margin: 1px 0; border-radius: 4px; border-left: 3px solid transparent; font-size: 13px;
}}
QListWidget#cardList::item:hover {{ background-color: {p.menu_hover}; }}
QListWidget#cardList::item:selected {{
    background-color: {p.menu_highlight}; border-left: 3px solid {p.accent_text}; color: {p.text};
}}
QListWidget#settingsNav {{ background: transparent; border: none; padding: 0; }}
QListWidget#settingsNav::item {{ padding: 8px 10px; margin: 1px 0; border-radius: 4px; border-left: 3px solid transparent; }}
QListWidget#settingsNav::item:hover {{ background-color: {p.menu_hover}; }}
QListWidget#settingsNav::item:selected {{
    background-color: {p.menu_highlight}; border-left: 3px solid {p.accent_text}; color: {p.text};
}}
QHeaderView::section {{
    background-color: {p.panel}; color: {p.text_secondary}; border: none; border-bottom: 1px solid {p.separator};
    padding: 6px 8px; font-weight: 600;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget#scrollBody {{ background: transparent; }}

/* ---------------------------------------------------------------- menus */
QMenuBar {{ background-color: {p.panel}; border-bottom: 1px solid {p.separator}; padding: 2px 4px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; font-size: 13px; }}
QMenuBar::item:selected {{ background-color: {p.menu_hover}; }}
QMenuBar::item:pressed {{ background-color: {p.menu_highlight}; }}
QMenu {{
    background-color: {p.panel}; border: 1px solid {p.separator}; border-radius: 4px; padding: 4px;
    font-size: 14px;
}}
QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: 2px; background: transparent; }}
QMenu::item:selected {{ background-color: {p.menu_hover}; color: {p.text}; }}
QMenu::item:disabled {{ color: {p.text_disabled}; }}
QMenu::separator {{ height: 1px; background: {p.separator}; margin: 4px 6px; }}
QMenu::right-arrow {{ image: url("{submenu}"); width: 12px; height: 12px; margin-right: 6px; }}
QMenu::indicator {{
    width: 14px; height: 14px; border-radius: 3px; border: 1px solid {p.input_border};
    background: {p.input_bg}; subcontrol-position: right center; subcontrol-origin: padding; right: 8px;
}}
QMenu::indicator:checked {{ background-color: {p.primary}; border-color: {p.primary}; image: url("{check}"); }}

/* ---------------------------------------------------------------- misc */
QGroupBox {{ border: 1px solid {p.separator}; border-radius: 4px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p.text_secondary}; }}
QToolTip {{
    background-color: {p.tooltip_bg}; color: {p.tooltip_fg}; border: 1px solid {p.tooltip_border};
    border-radius: 4px; padding: 6px 8px;
}}
QProgressBar {{
    background-color: {p.separator}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background-color: {p.primary}; border-radius: 3px; }}
QStatusBar {{ background-color: {p.window}; border: none; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px; }}
QScrollBar::handle:vertical {{ background: {p.scroll_thumb}; min-height: 28px; border-radius: 4px; margin: 0 1px; }}
QScrollBar::handle:vertical:hover {{ background: {p.scroll_thumb_hover}; }}
QScrollBar::handle:vertical:pressed {{ background: {p.scroll_thumb_pressed}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 2px; }}
QScrollBar::handle:horizontal {{ background: {p.scroll_thumb}; min-width: 28px; border-radius: 4px; margin: 1px 0; }}
QScrollBar::handle:horizontal:hover {{ background: {p.scroll_thumb_hover}; }}
QScrollBar::handle:horizontal:pressed {{ background: {p.scroll_thumb_pressed}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def app_font() -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(9.5)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def apply_theme(app: QApplication, dark: bool) -> Palette:
    p = palette_for(dark)
    app.setStyle("Fusion")
    app.setProperty("kcdmmDark", dark)
    app.setFont(app_font())
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
    qpal.setColor(QPalette.ColorRole.Link, QColor(p.accent_text))
    qpal.setColor(QPalette.ColorRole.Mid, QColor(p.separator))
    app.setPalette(qpal)
    app.setStyleSheet(stylesheet(p))
    return p

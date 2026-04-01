# ===== FILE: theme_utils.py =====

# -*- coding: utf-8 -*-
"""
Standalone theme utilities.
"""

import re
from typing import Dict

from PySide6.QtWidgets import QWidget

def get_default_theme() -> Dict:
    """Returns the default color scheme."""
    return {
        "DARK": "#0f0f12",
        "PANEL": "#16161c", 
        "SURFACE": "#1e1e28",
        "SURFACE2": "#26263a",
        "BORDER": "#2e2e42",
        "ACCENT": "#7c6aff",
        "ACCENT2": "#ff6a9b",
        "TEXT": "#e8e6f0",
        "TEXT_DIM": "#7a7890",
        "TEXT_MUTED": "#4a4860",
        "SUCCESS": "#4ade80",
        "WARNING": "#facc15",
        "DANGER": "#f87171",
    }

def theme_to_stylesheet(theme: Dict) -> str:
    """Convert theme dict to complete Qt stylesheet."""
    # Note: Removed 'system-ui' as it breaks Qt stylesheet parsing on some platforms
    return f"""
    QMainWindow, QWidget {{
        background-color: {theme['DARK']};
        color: {theme['TEXT']};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
    }}
    QTabWidget::pane {{
        border: 1px solid {theme['BORDER']};
        background-color: {theme['PANEL']};
        border-radius: 0px;
    }}
    QTabBar::tab {{
        background-color: {theme['SURFACE']};
        color: {theme['TEXT_DIM']};
        padding: 10px 20px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 13px;
        font-weight: 500;
        min-width: 110px;
    }}
    QTabBar::tab:selected {{
        color: {theme['TEXT']};
        border-bottom: 2px solid {theme['ACCENT']};
        background-color: {theme['PANEL']};
    }}
    QTabBar::tab:hover {{
        color: {theme['TEXT']};
        background-color: {theme['SURFACE2']};
    }}
    QListWidget {{
        background-color: {theme['SURFACE']};
        border: 1px solid {theme['BORDER']};
        border-radius: 4px;
        color: {theme['TEXT']};
        outline: none;
        padding: 2px;
    }}
    QListWidget::item {{
        padding: 8px 10px;
        border-radius: 3px;
        border-bottom: 1px solid {theme['BORDER']};
    }}
    QListWidget::item:selected {{
        background-color: {theme['ACCENT']};
        color: white;
    }}
    QListWidget::item:hover:!selected {{
        background-color: {theme['SURFACE2']};
    }}
    /* Generic push button styling */
    QPushButton {{
        background-color: {theme['SURFACE2']};
        color: {theme['TEXT']};
        border: 1px solid {theme['BORDER']};
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {theme['ACCENT']};
        border-color: {theme['ACCENT']};
        color: white;
    }}
    QPushButton:pressed {{
        background-color: {theme['ACCENT']};
        opacity: 0.8;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {theme['SURFACE']};
        width: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {theme['BORDER']};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: {theme['SURFACE']};
        height: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {theme['BORDER']};
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QSplitter::handle {{
        background-color: {theme['BORDER']};
        width: 1px;
        height: 1px;
    }}
    QFrame[frameShape="4"], QFrame[frameShape="5"] {{
        color: {theme['BORDER']};
    }}
    QLabel {{
        color: {theme['TEXT']};
        background: transparent;
    }}
    QMenuBar {{
        background-color: {theme['DARK']};
        color: {theme['TEXT']};
        border-bottom: 1px solid {theme['BORDER']};
        padding: 2px;
    }}
    QMenuBar::item:selected {{
        background-color: {theme['SURFACE2']};
        border-radius: 3px;
    }}
    QMenu {{
        background-color: {theme['SURFACE']};
        color: {theme['TEXT']};
        border: 1px solid {theme['BORDER']};
        border-radius: 4px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 3px;
    }}
    QMenu::item:selected {{
        background-color: {theme['ACCENT']};
        color: white;
    }}
    QMenu::separator {{
        height: 1px;
        background: {theme['BORDER']};
        margin: 4px 8px;
    }}
    """


def replace_widget_theme_colors(root: QWidget, old_colors: Dict[str, str], new_colors: Dict[str, str]) -> None:
    """Replace inline stylesheet colors on an existing widget tree."""
    if root is None:
        return

    replacements: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for key, old in old_colors.items():
        new = new_colors.get(key)
        if not (isinstance(old, str) and isinstance(new, str)):
            continue
        if not (old.startswith("#") and new.startswith("#")):
            continue
        if old.lower() == new.lower():
            continue
        pair = (old.lower(), new.lower())
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        replacements.append((old, new))

    if not replacements:
        return

    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        stylesheet = widget.styleSheet()
        if not stylesheet:
            continue
        updated = stylesheet
        for old, new in replacements:
            updated = re.sub(re.escape(old), new, updated, flags=re.IGNORECASE)
        if updated != stylesheet:
            widget.setStyleSheet(updated)

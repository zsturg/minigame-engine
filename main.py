# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
Vita Adventure Creator
A PyQt6 tool for building 2D adventure games for the PS Vita via LifeLua.
"""

import sys
import random
import string
import struct
import shutil
import zipfile
import tempfile
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QTabWidget,
    QFrame, QSplitter, QMessageBox, QFileDialog, QScrollArea,
    QSizePolicy, QMenuBar, QMenu, QDialog, QDialogButtonBox,
    QSpinBox, QCheckBox, QComboBox, QLineEdit, QFormLayout, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QAction, QFontDatabase
from windows_exporter import export_windows_game
from models import Project, Scene, SCENE_TEMPLATES
from tab_gamedata import GameDataTab
from tab_scene_options import SceneOptionsTab
from tab_3d_maps import MapsTab3D
from tab_objects import ObjectsTab
from tab_editor import EditorTab
from tab_animation_graph import AnimationGraphTab
from theme_utils import theme_to_stylesheet, get_default_theme
import json

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data: dict):
    try:
        existing = load_config()
        existing.update(data)
        with open(CONFIG_PATH, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────
#  SFO EDITOR (Binary Patcher)
# ─────────────────────────────────────────────────────────────

class SFOEditor:
    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.entries = []
        self._load()

    def _load(self):
        with open(self.filepath, 'rb') as f:
            data = f.read()
        self.magic, self.version, key_table_start, data_table_start, count = struct.unpack('<IIIII', data[0:20])
        if self.magic != 0x46535000:
            raise ValueError("Invalid SFO file")
        current_idx = 20
        for _ in range(count):
            key_ofs, fmt, length, max_len, data_ofs = struct.unpack('<HHIII', data[current_idx:current_idx+16])
            key_ptr = key_table_start + key_ofs
            key_end = data.find(b'\0', key_ptr)
            key_name = data[key_ptr:key_end].decode('utf-8')
            data_ptr = data_table_start + data_ofs
            value_bytes = data[data_ptr:data_ptr+length]
            if fmt in [0x0004, 0x0204]:
                value = value_bytes.decode('utf-8').rstrip('\0')
            else:
                value = value_bytes
            self.entries.append({'key': key_name, 'fmt': fmt, 'value': value})
            current_idx += 16

    def set_string(self, key, new_value):
        found = False
        for entry in self.entries:
            if entry['key'] == key:
                entry['value'] = new_value
                found = True
                break
        if not found:
            self.entries.append({'key': key, 'fmt': 0x0004, 'value': new_value})

    def save(self):
        new_key_table = bytearray()
        new_data_table = bytearray()
        index_bytes = bytearray()
        for entry in self.entries:
            key_bytes = entry['key'].encode('utf-8') + b'\0'
            key_ofs = len(new_key_table)
            new_key_table.extend(key_bytes)
            if isinstance(entry['value'], str):
                data_bytes = entry['value'].encode('utf-8') + b'\0'
            else:
                data_bytes = entry['value']
            data_len = len(data_bytes)
            max_len = (data_len + 3) & ~3
            data_ofs = len(new_data_table)
            new_data_table.extend(data_bytes)
            new_data_table.extend(b'\0' * (max_len - data_len))
            index_bytes.extend(struct.pack('<HHIII', key_ofs, entry['fmt'], data_len, max_len, data_ofs))
        header_size = 20
        key_table_start = header_size + len(index_bytes)
        while len(new_key_table) % 4 != 0:
            new_key_table.append(0)
        data_table_start = key_table_start + len(new_key_table)
        header = struct.pack('<IIIII', self.magic, self.version, key_table_start, data_table_start, len(self.entries))
        with open(self.filepath, 'wb') as f:
            f.write(header)
            f.write(index_bytes)
            f.write(new_key_table)
            f.write(new_data_table)


# ─────────────────────────────────────────────────────────────
#  VPK EXPORT DIALOG
# ─────────────────────────────────────────────────────────────

class VPKExportDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export VPK")
        self.setModal(True)
        self.setFixedSize(550, 620)
        self.setStyleSheet(f"""
            QDialog {{ background: {PANEL}; color: {TEXT}; }}
            QLabel {{ color: {TEXT}; font-size: 12px; }}
            QLineEdit {{ padding: 5px; background: {SURFACE}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px; }}
            QPushButton {{ padding: 6px 12px; background: {SURFACE2}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px; }}
            QPushButton:hover {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
            QGroupBox {{ border: 1px solid {BORDER}; border-radius: 5px;
                margin-top: 10px; padding-top: 15px; font-weight: bold; color: {TEXT}; }}
        """)

        layout = QVBoxLayout(self)

        info_lbl = QLabel("Configure game identity and LiveArea assets.\nA unique Title ID is required to install alongside other games.")
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(info_lbl)

        # Game Identity
        id_group = QGroupBox("Game Identity")
        id_layout = QFormLayout()
        id_layout.setSpacing(10)

        self.title_edit = QLineEdit(project.title)
        self.title_edit.setPlaceholderText("My Game")
        id_layout.addRow("Game Title:", self.title_edit)

        id_container = QWidget()
        id_box = QHBoxLayout(id_container)
        id_box.setContentsMargins(0, 0, 0, 0)
        self.id_edit = QLineEdit(project.title_id)
        self.id_edit.setPlaceholderText("ADVG00001")
        self.id_edit.setMaxLength(9)
        rand_btn = QPushButton("Randomize")
        rand_btn.setFixedWidth(100)
        rand_btn.clicked.connect(self._generate_id)
        id_box.addWidget(self.id_edit)
        id_box.addWidget(rand_btn)
        id_layout.addRow("Title ID:", id_container)
        id_layout.addRow(QLabel("(Format: 4 Letters + 5 Numbers, e.g. ADVG00001)"))
        id_group.setLayout(id_layout)
        layout.addWidget(id_group)

        # LiveArea Assets
        asset_group = QGroupBox("LiveArea Assets")
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        def create_asset_row(label_text, resolution_text):
            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)
            path_edit = QLineEdit()
            path_edit.setPlaceholderText(f"Resolution: {resolution_text}")
            path_edit.setReadOnly(True)
            browse_btn = QPushButton("Browse")
            browse_btn.setFixedWidth(80)
            h_layout.addWidget(path_edit)
            h_layout.addWidget(browse_btn)
            form_layout.addRow(label_text, container)
            return path_edit, browse_btn

        self.icon_path, btn_icon = create_asset_row("Icon (Bubble):", "128x128")
        btn_icon.clicked.connect(lambda: self._browse_image(self.icon_path))
        self.startup_path, btn_startup = create_asset_row("Startup Gate:", "280x158")
        btn_startup.clicked.connect(lambda: self._browse_image(self.startup_path))
        self.bg_path, btn_bg = create_asset_row("LiveArea BG:", "840x500")
        btn_bg.clicked.connect(lambda: self._browse_image(self.bg_path))
        self.splash_path, btn_splash = create_asset_row("Boot Splash:", "960x544")
        btn_splash.clicked.connect(lambda: self._browse_image(self.splash_path))

        asset_group.setLayout(form_layout)
        layout.addWidget(asset_group)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        export_btn = QPushButton("Export VPK")
        export_btn.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold;")
        export_btn.clicked.connect(self.accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(export_btn)
        layout.addLayout(btn_layout)

    def _generate_id(self):
        chars = "".join(random.choices(string.ascii_uppercase, k=4))
        nums = "".join(random.choices(string.digits, k=5))
        self.id_edit.setText(f"{chars}{nums}")

    def _browse_image(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg)")
        if path:
            line_edit.setText(path)

    def get_data(self):
        return {
            'title': self.title_edit.text().strip() or "Untitled Game",
            'title_id': self.id_edit.text().strip().upper(),
            'assets': {
                'icon0':   self.icon_path.text(),
                'startup': self.startup_path.text(),
                'bg':      self.bg_path.text(),
                'pic0':    self.splash_path.text(),
            }
        }


# ─────────────────────────────────────────────────────────────
#  STYLE
# ─────────────────────────────────────────────────────────────

DARK     = "#0f0f12"
PANEL    = "#16161c"
SURFACE  = "#1e1e28"
SURFACE2 = "#26263a"
BORDER   = "#2e2e42"
ACCENT   = "#7c6aff"
ACCENT2  = "#ff6a9b"
TEXT     = "#e8e6f0"
TEXT_DIM  = "#7a7890"
TEXT_MUTED = "#4a4860"
SUCCESS  = "#4ade80"
WARNING  = "#facc15"
DANGER   = "#f87171"

ROLE_COLORS = {
    "start": SUCCESS,
    "end":   DANGER,
    "":      TEXT_DIM,
}

APP_STYLE = f"""
QMainWindow, QWidget {{
    background-color: {DARK};
    color: {TEXT};
    font-family: "Segoe UI", "SF Pro Display", system-ui;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {PANEL};
    border-radius: 0px;
}}
QTabBar::tab {{
    background-color: {SURFACE};
    color: {TEXT_DIM};
    padding: 10px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
    font-weight: 500;
    min-width: 110px;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
    background-color: {PANEL};
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background-color: {SURFACE2};
}}
QListWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    outline: none;
    padding: 2px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 3px;
    border-bottom: 1px solid {BORDER};
}}
QListWidget::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QListWidget::item:hover:!selected {{
    background-color: {SURFACE2};
}}
QPushButton {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: white;
}}
QPushButton:pressed {{
    background-color: #5a4adf;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {SURFACE};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {SURFACE};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
    height: 1px;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {BORDER};
}}
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QMenuBar {{
    background-color: {DARK};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background-color: {SURFACE2};
    border-radius: 3px;
}}
QMenu {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
"""

# ─────────────────────────────────────────────────────────────
#  SMALL REUSABLE WIDGETS
# ─────────────────────────────────────────────────────────────

class SectionLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            color: {TEXT_DIM};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            padding: 12px 0 4px 0;
        """)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setStyleSheet(f"color: {BORDER}; background-color: {BORDER}; max-height: 1px;")


class IconButton(QPushButton):
    def __init__(self, label, tooltip="", danger=False, accent=False, parent=None):
        super().__init__(label, parent)
        self.setToolTip(tooltip)
        self.setFixedHeight(30)
        if danger:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {DANGER};
                    color: {DANGER};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: {DANGER};
                    color: white;
                }}
            """)
        elif accent:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT};
                    border: 1px solid {ACCENT};
                    color: white;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: #6a59ef;
                }}
            """)


# ─────────────────────────────────────────────────────────────
#  NEW SCENE DIALOG
# ─────────────────────────────────────────────────────────────

class NewSceneDialog(QDialog):
    """Let the user pick a template when adding a new scene."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Scene")
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl = QLabel("Choose a template:")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)

        TEMPLATE_DESCRIPTIONS = {
            "BLANK":        "Empty — no components pre-added",
            "VN_SCENE":     "Background + Music + VN Dialog Box",
            "CHOICE_SCENE": "Background + Music + VN Dialog Box + Choice Menu",
            "START_SCREEN": "Background + Music  [role: start]",
            "END_SCENE":    "Background + Music  [role: end]",
            "CUTSCENE":     "Video component",
            "3D_SCENE":     "Raycaster map — free, grid, or scripted movement",
        }

        for label, key in SCENE_TEMPLATES:
            desc = TEMPLATE_DESCRIPTIONS.get(key, "")
            item = QListWidgetItem(f"{label}  —  {desc}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_widget.addItem(item)

        self.list_widget.setCurrentRow(1)   # default: VN Scene
        self.list_widget.doubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"color: {TEXT};")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_template(self) -> str:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else "BLANK"


# ─────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = Project.new()
        self.current_scene_index = 0
        self.current_project_path: Path | None = None
        self.unsaved = False
        cfg = load_config()
        self.current_theme = cfg.get("theme", {"colors": get_default_theme()})
        self._show_explorer = cfg.get("show_explorer", True)

        self.setWindowTitle("MINIGAME ENGINE")
        self.setMinimumSize(1280, 760)
        self.resize(1400, 820)

        self._build_menu()
        self._build_ui()
        self._reload_project()
        # Apply saved theme (after UI is built)
        self.apply_theme(self.current_theme)

    # ── Menu ────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        for label, shortcut, slot in [
            ("New Project",       "Ctrl+N",       self.new_project),
            ("Open Project…",     "Ctrl+O",       self.open_project),
            (None, None, None),
            ("Save Project",      "Ctrl+S",       self.save_project),
            ("Save Project As…",  "Ctrl+Shift+S", self.save_project_as),
            (None, None, None),
            ("Export to VPK…",    "Ctrl+E",       self.export_vpk),
            ("Export to VPK (LPP)…",     "Ctrl+Shift+E", self.export_vpk_lpp),
            ("Export to Windows…", "Ctrl+W", self.export_windows),
        ]:
            if label is None:
                file_menu.addSeparator()
            else:
                action = QAction(label, self)
                if shortcut:
                    action.setShortcut(shortcut)
                action.triggered.connect(slot)
                file_menu.addAction(action)

        tools_menu = mb.addMenu("Tools")
        ss_action = QAction("Spritesheet Builder…", self)
        ss_action.triggered.connect(self.open_spritesheet_tool)
        tools_menu.addAction(ss_action)

        tileset_action = QAction("Tileset Manager…", self)
        tileset_action.triggered.connect(self.open_tileset_manager)
        tools_menu.addAction(tileset_action)

        theme_action = QAction("Customize Appearance…", self)
        theme_action.triggered.connect(self.open_theme_customizer)
        tools_menu.addAction(theme_action)

        # View menu
        view_menu = mb.addMenu("View")
        self.show_explorer_action = QAction("Show Project Explorer", self)
        self.show_explorer_action.setCheckable(True)
        self.show_explorer_action.setChecked(self._show_explorer)
        self.show_explorer_action.triggered.connect(self._toggle_explorer)
        view_menu.addAction(self.show_explorer_action)

    def _toggle_explorer(self, checked: bool):
        """Toggle project explorer visibility."""
        self._show_explorer = checked
        self.editor_tab.set_explorer_visible(checked)
        save_config({"show_explorer": checked})

    def open_theme_customizer(self):
        from appearance_customizer import ThemeCustomizer
        dlg = ThemeCustomizer(self.current_theme, self)
        if dlg.exec():
            self.apply_theme(dlg.theme)

    def apply_theme(self, theme: dict):
        """
        Apply a theme dict to the entire app.

        The app-level stylesheet handles all generic Qt widgets.
        We then explicitly re-push styles onto the few widgets that were
        built with hardcoded inline setStyleSheet calls in _build_ui /
        _build_topbar, since those override the app stylesheet.

        The tab files stay completely theme-unaware for LLM work.
        Each tab optionally exposes restyle(colors) — if it doesn't have
        one, we just skip it gracefully.
        """
        self.current_theme = theme
        save_config({"theme": theme})
        c = theme["colors"]

        # 1. App-wide stylesheet
        QApplication.instance().setStyleSheet(theme_to_stylesheet(c))

        # 2. Topbar widgets (inline styles override the app stylesheet)
        self.topbar.setStyleSheet(
            f"background-color: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};"
        )
        self._app_name_label.setStyleSheet(f"""
            color: {c['ACCENT']};
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 2px;
        """)
        self.project_name_label.setStyleSheet(
            f"color: {c['TEXT']}; font-size: 13px; font-weight: 500;"
        )
        self.unsaved_dot.setStyleSheet(f"color: {c['WARNING']}; font-size: 10px;")

        # 3. Status bar
        self.status_label.setStyleSheet(f"""
            background-color: {c['PANEL']};
            color: {c['TEXT_DIM']};
            font-size: 11px;
            padding: 4px 12px;
            border-top: 1px solid {c['BORDER']};
        """)

        # 4. Tabs — each tab can expose restyle(colors) to handle its own
        #    internal inline-styled widgets. This keeps all theme logic out
        #    of the tab files themselves; they just receive the colors dict
        #    and decide what to do with it. If a tab doesn't implement
        #    restyle() yet, we skip it without crashing.
        for tab in (self.editor_tab, self.obj_tab, self.scene_tab, self.anim_tab, self.data_tab, self.maps3d_tab):
            if hasattr(tab, "restyle"):
                tab.restyle(c)

    # ── UI ──────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.topbar = self._build_topbar()
        root.addWidget(self.topbar)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)

        # Tab 1: Editor
        self.editor_tab = EditorTab(self)
        self.editor_tab.instance_changed.connect(self._mark_unsaved)
        self.editor_tab.set_explorer_visible(self._show_explorer)
        self.tabs.addTab(self.editor_tab, "  Editor")

        # Tab 2: Objects
        self.obj_tab = ObjectsTab()
        self.obj_tab.changed.connect(self._mark_unsaved)
        self.tabs.addTab(self.obj_tab, "  Objects")

        # Tab 3: Scene Options
        self.scene_tab = SceneOptionsTab()
        self.scene_tab.changed.connect(self._mark_unsaved)
        self.scene_tab.scene_selected.connect(self._on_scene_tab_selected)
        self.tabs.addTab(self.scene_tab, "  Scene Options")

        # Tab 4: Animation Graph (NEW)
        self.anim_tab = AnimationGraphTab()
        self.tabs.addTab(self.anim_tab, "  Animation Graph")

        self.maps3d_tab = MapsTab3D(self)
        self.tabs.addTab(self.maps3d_tab, "  3D Maps")

        # Tab 5: Game Data
        self.data_tab = GameDataTab()
        self.data_tab.changed.connect(self._mark_unsaved)
        self.tabs.addTab(self.data_tab, "  Game Data")

        root.addWidget(self.tabs)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"""
            background-color: {PANEL};
            color: {TEXT_DIM};
            font-size: 11px;
            padding: 4px 12px;
            border-top: 1px solid {BORDER};
        """)
        root.addWidget(self.status_label)

    def _build_topbar(self):
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"background-color: {PANEL}; border-bottom: 1px solid {BORDER};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)

        self._app_name_label = QLabel("MINIGAME ENGINE")
        self._app_name_label.setStyleSheet(f"""
            color: {ACCENT};
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 2px;
        """)
        layout.addWidget(self._app_name_label)
        layout.addSpacing(20)

        self.project_name_label = QLabel("Untitled Game")
        self.project_name_label.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500;")
        layout.addWidget(self.project_name_label)

        self.unsaved_dot = QLabel("*")
        self.unsaved_dot.setStyleSheet(f"color: {WARNING}; font-size: 10px;")
        self.unsaved_dot.hide()
        layout.addWidget(self.unsaved_dot)

        layout.addStretch()

        return bar

    # ── Refresh ─────────────────────────────────────────────

    def _refresh(self):
        self.editor_tab.refresh(self.project, self.current_scene_index)
        self.scene_tab.refresh_project(self.project, self.current_scene_index)
        name = self.current_project_path.stem if self.current_project_path else self.project.title
        self.project_name_label.setText(name)
        self.unsaved_dot.setVisible(self.unsaved)
        self.setWindowTitle(f"MINIGAME ENGINE VITA — {name}{'  •' if self.unsaved else ''}")

    def _reload_project(self):
        """Full reload — called on new/open."""
        self.data_tab.load_project(self.project)
        self.obj_tab.load_project(self.project)
        self.obj_tab.load_scene(self.project.scenes[0], self.project)
        self.scene_tab.refresh_project(self.project, self.current_scene_index)
        self.editor_tab.refresh(self.project, self.current_scene_index)
        self._refresh()

    def _mark_unsaved(self):
        self.unsaved = True
        self._refresh()

    def _set_status(self, msg: str):
        self.status_label.setText(msg)

    # ── Scene operations ────────────────────────────────────

    def on_scene_selected(self, index: int):
        if 0 <= index < len(self.project.scenes):
            self.current_scene_index = index
            scene = self.project.scenes[index]
            self.scene_tab.refresh_project(self.project, index)
            self.obj_tab.load_scene(scene, self.project)
            if getattr(scene, "scene_type", "2d") == "3d":
                self.maps3d_tab.load_scene(scene)
                self.tabs.setCurrentWidget(self.maps3d_tab)
            else:
                self.maps3d_tab.clear_scene()
            self._refresh()
            self._set_status(f"Scene {index + 1}: {scene.get_summary()}")

    def _on_scene_tab_selected(self, index: int):
        """Called when the user picks a scene from the Scene Options dropdown.
        Updates current_scene_index and syncs the editor, but does NOT call
        refresh_project again (the tab already loaded the scene itself)."""
        if 0 <= index < len(self.project.scenes):
            self.current_scene_index = index
            self.editor_tab.refresh(self.project, index)
            scene = self.project.scenes[index]
            self.obj_tab.load_scene(scene, self.project)
            name = self.current_project_path.stem if self.current_project_path else self.project.title
            self.project_name_label.setText(name)
            self.unsaved_dot.setVisible(self.unsaved)
            self.setWindowTitle(f"MINIGAME ENGINE VITA — {name}{'  •' if self.unsaved else ''}")
            self._set_status(f"Scene {index + 1}: {scene.get_summary()}")

    def add_scene(self):
        dlg = NewSceneDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        template = dlg.selected_template()
        name = f"Scene {len(self.project.scenes) + 1}"
        new_scene = Scene.from_template(template, name=name)
        insert_at = self.current_scene_index + 1
        self.project.scenes.insert(insert_at, new_scene)
        self.current_scene_index = insert_at
        self._mark_unsaved()
        self._set_status("Scene added.")

    def delete_scene(self, index: int):
        if len(self.project.scenes) <= 1:
            QMessageBox.warning(self, "Cannot Delete", "A project must have at least one scene.")
            return
        reply = QMessageBox.question(self, "Delete Scene",
            f"Delete scene {index + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.project.scenes.pop(index)
            self.current_scene_index = max(0, index - 1)
            self._mark_unsaved()
            self._set_status("Scene deleted.")

    def move_scene(self, from_idx: int, to_idx: int):
        scenes = self.project.scenes
        scenes.insert(to_idx, scenes.pop(from_idx))
        self.current_scene_index = to_idx
        self._mark_unsaved()

    def duplicate_scene(self, index: int):
        import json
        original = self.project.scenes[index]
        clone = Scene.from_dict(json.loads(json.dumps(original.to_dict())))
        import uuid
        clone.id = str(uuid.uuid4())[:8]
        clone.name = (clone.name + " Copy") if clone.name else ""
        self.project.scenes.insert(index + 1, clone)
        self.current_scene_index = index + 1
        self._mark_unsaved()
        self._set_status("Scene duplicated.")

    # ── File operations ─────────────────────────────────────

    def _confirm_discard(self) -> bool:
        if not self.unsaved:
            return True
        reply = QMessageBox.question(self, "Unsaved Changes",
            "You have unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Save:
            return self.save_project()
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def new_project(self):
        if not self._confirm_discard():
            return
        self.project = Project.new()
        self.current_scene_index = 0
        self.current_project_path = None
        self.unsaved = False
        self._reload_project()
        self._set_status("New project created.")

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "",
            "Adventure Project (*.agproj);;All Files (*)")
        if not path:
            return
        try:
            self.project = Project.load(path)
            self.current_scene_index = 0
            self.current_project_path = Path(path)
            self.unsaved = False
            self._reload_project()
            self._set_status(f"Opened: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", f"Could not open project:\n{e}")

    def save_project(self) -> bool:
        if self.current_project_path:
            return self._write_project(self.current_project_path)
        return self.save_project_as()

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", "",
            "Adventure Project (*.agproj);;All Files (*)")
        if not path:
            return False
        if not path.endswith(".agproj"):
            path += ".agproj"
        self.current_project_path = Path(path)
        return self._write_project(self.current_project_path)

    def _write_project(self, path: Path) -> bool:
        try:
            self.project.save(path)
            self.unsaved = False
            self._refresh()
            self._set_status(f"Saved: {path}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save:\n{e}")
            return False

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # ── Stubs ───────────────────────────────────────────────

    def export_vpk(self):
        from lua_exporter import export_main_lua

        base_path = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        template_folder = base_path / "vpktemplate"
        if not template_folder.exists() or not template_folder.is_dir():
            QMessageBox.critical(self, "Error",
                "The 'vpktemplate' folder is missing!\n\n"
                "Place a folder named 'vpktemplate' containing eboot.bin "
                "and sce_sys next to this script.")
            return

        # Show export dialog
        dialog = VPKExportDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        export_config = dialog.get_data()
        title_id = export_config['title_id']
        if len(title_id) != 9 or not title_id[:4].isalpha() or not title_id[4:].isdigit():
            QMessageBox.warning(self, "Invalid ID",
                "Title ID must be 4 letters followed by 5 numbers (e.g. ADVG00001).")
            return

        vpk_path_str, _ = QFileDialog.getSaveFileName(
            self, "Save VPK", f"{title_id}.vpk", "Vita VPK (*.vpk)")
        if not vpk_path_str:
            return
        vpk_path = Path(vpk_path_str)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                build_dir = Path(temp_dir)

                # 1. Copy vpktemplate as scaffold
                try:
                    shutil.copytree(template_folder, build_dir, dirs_exist_ok=True)
                except Exception as e:
                    QMessageBox.critical(self, "Copy Error", f"Failed to copy template files:\n{e}")
                    return

                # 2. Patch PARAM.SFO
                sfo_path = build_dir / "sce_sys" / "param.sfo"
                if sfo_path.exists():
                    try:
                        editor = SFOEditor(sfo_path)
                        editor.set_string("TITLE", export_config['title'])
                        editor.set_string("TITLE_ID", title_id)
                        editor.set_string("STITLE", export_config['title'])
                        editor.save()
                    except Exception as e:
                        QMessageBox.warning(self, "SFO Error", f"Failed to patch PARAM.SFO:\n{e}")
                else:
                    QMessageBox.warning(self, "Missing SFO", "param.sfo not found in vpktemplate/sce_sys/.")

                # 3. Copy LiveArea assets
                asset_map = {
                    'icon0':   build_dir / "sce_sys" / "icon0.png",
                    'startup': build_dir / "sce_sys" / "livearea" / "contents" / "startup.png",
                    'bg':      build_dir / "sce_sys" / "livearea" / "contents" / "bg.png",
                    'pic0':    build_dir / "pic0.png",
                }
                for key, dest in asset_map.items():
                    user_path = export_config['assets'].get(key)
                    if user_path:
                        try:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy(user_path, dest)
                        except Exception as e:
                            print(f"Warning: Could not copy LiveArea asset {key}: {e}")

                # 4. Copy all registered game assets to build root
                copied = set()
                for img in self.project.images:
                    if img.path and os.path.exists(img.path) and img.path not in copied:
                        shutil.copy(img.path, build_dir / Path(img.path).name)
                        copied.add(img.path)

                for aud in self.project.audio:
                    if aud.path and os.path.exists(aud.path) and aud.path not in copied:
                        shutil.copy(aud.path, build_dir / Path(aud.path).name)
                        copied.add(aud.path)

                for fnt in self.project.fonts:
                    if fnt.path and os.path.exists(fnt.path) and fnt.path not in copied:
                        shutil.copy(fnt.path, build_dir / Path(fnt.path).name)
                        copied.add(fnt.path)

                # 5. Generate main.lua
                try:
                    lua_code = export_main_lua(self.project)
                    # Patch save path with actual title ID
                    lua_code = lua_code.replace(
                        f"ux0:data/{self.project.title_id}_save.dat",
                        f"ux0:data/{title_id}_save.dat"
                    )
                    with open(build_dir / "main.lua", 'w', encoding='utf-8', newline='\n') as f:
                        f.write(lua_code)
                except Exception as e:
                    QMessageBox.critical(self, "Code Error", f"Failed to generate Lua:\n{e}")
                    return

                # 6. ZIP into VPK (no compression — ZIP_STORED)
                try:
                    with zipfile.ZipFile(vpk_path, 'w', zipfile.ZIP_STORED) as zipf:
                        for root, _, files in os.walk(build_dir):
                            for file in files:
                                file_path = Path(root) / file
                                arcname = file_path.relative_to(build_dir)
                                zipf.write(file_path, arcname)
                except Exception as e:
                    QMessageBox.critical(self, "Zip Error", f"Failed to create VPK:\n{e}")
                    return

            self._set_status(f"VPK exported: {vpk_path}")
            QMessageBox.information(self, "Export Complete",
                f"VPK created successfully!\n\nTitle: {export_config['title']}\n"
                f"ID: {title_id}\nLocation: {vpk_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Export Failed", f"An unexpected error occurred:\n{e}")

    def export_vpk_lpp(self):
        from lpp_exporter import export_lpp, get_asset_mapping

        base_path = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        template_folder = base_path / "lpptemplate"
        if not template_folder.exists() or not template_folder.is_dir():
            QMessageBox.critical(self, "Error",
                "The 'lpptemplate' folder is missing!\n\n"
                "Place a folder named 'lpptemplate' containing eboot.bin "
                "and sce_sys next to this script.")
            return

        dialog = VPKExportDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        export_config = dialog.get_data()
        title_id = export_config['title_id']
        if len(title_id) != 9 or not title_id[:4].isalpha() or not title_id[4:].isdigit():
            QMessageBox.warning(self, "Invalid ID",
                "Title ID must be 4 letters followed by 5 numbers (e.g. ADVG00001).")
            return

        vpk_path_str, _ = QFileDialog.getSaveFileName(
            self, "Save VPK (LPP)", f"{title_id}.vpk", "Vita VPK (*.vpk)")
        if not vpk_path_str:
            return
        vpk_path = Path(vpk_path_str)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                build_dir = Path(temp_dir)

                # 1. Copy lpptemplate as scaffold
                try:
                    shutil.copytree(template_folder, build_dir, dirs_exist_ok=True)
                except Exception as e:
                    QMessageBox.critical(self, "Copy Error", f"Failed to copy template files:\n{e}")
                    return

                # 2. Patch PARAM.SFO
                sfo_path = build_dir / "sce_sys" / "param.sfo"
                if sfo_path.exists():
                    try:
                        editor = SFOEditor(sfo_path)
                        editor.set_string("TITLE", export_config['title'])
                        editor.set_string("TITLE_ID", title_id)
                        editor.set_string("STITLE", export_config['title'])
                        editor.save()
                    except Exception as e:
                        QMessageBox.warning(self, "SFO Error", f"Failed to patch PARAM.SFO:\n{e}")
                else:
                    QMessageBox.warning(self, "Missing SFO", "param.sfo not found in lpptemplate/sce_sys/.")

                # 3. Copy LiveArea assets
                livearea_map = {
                    'icon0':   build_dir / "sce_sys" / "icon0.png",
                    'startup': build_dir / "sce_sys" / "livearea" / "contents" / "startup.png",
                    'bg':      build_dir / "sce_sys" / "livearea" / "contents" / "bg.png",
                    'pic0':    build_dir / "pic0.png",
                }
                for key, dest in livearea_map.items():
                    user_path = export_config['assets'].get(key)
                    if user_path:
                        try:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy(user_path, dest)
                        except Exception as e:
                            print(f"Warning: Could not copy LiveArea asset {key}: {e}")

                # 4a. Copy default font from template into assets/fonts/
                template_font = template_folder / "font.ttf"
                if template_font.exists():
                    fonts_dir = build_dir / "assets" / "fonts"
                    fonts_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy(template_font, fonts_dir / "font.ttf")

                # 4b. Copy raycast3d.lua if any 3D scenes exist
                from lpp_exporter import export_lpp as _lpp_check
                has_3d = any(getattr(s, "scene_type", "2d") == "3d" for s in self.project.scenes)
                if has_3d:
                    raycast_src = base_path / "raycast3d.lua"
                    if raycast_src.exists():
                        files_dir = build_dir / "files"
                        files_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy(raycast_src, files_dir / "raycast3d.lua")
                    else:
                        QMessageBox.warning(self, "Missing File",
                            "raycast3d.lua not found next to the script.\n"
                            "3D scenes will not work without it.")

                # 4. Copy game assets into organized subfolders
                asset_mapping = get_asset_mapping(self.project)
                copied = set()
                for src_path, dest_rel in asset_mapping.items():
                    if src_path and os.path.exists(src_path) and src_path not in copied:
                        dest_abs = build_dir / dest_rel
                        dest_abs.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(src_path, dest_abs)
                        copied.add(src_path)
                # 4c. Bake TileLayer chunks into assets/tilechunks/
                try:
                    from lpp_exporter import bake_tile_chunks
                    bake_tile_chunks(self.project, build_dir)
                except Exception as e:
                    print(f"Warning: tile chunk baking failed: {e}")
                    
                # 5. Generate Lua files (index.lua + lib/ + scenes/)
                try:
                    lua_files = export_lpp(self.project, title_id=title_id)
                    for rel_path, content in lua_files.items():
                        dest_abs = build_dir / rel_path
                        dest_abs.parent.mkdir(parents=True, exist_ok=True)
                        with open(dest_abs, 'w', encoding='utf-8', newline='\n') as f:
                            f.write(content)
                except Exception as e:
                    QMessageBox.critical(self, "Code Error", f"Failed to generate Lua:\n{e}")
                    return

                # 6. ZIP into VPK (no compression — ZIP_STORED)
                try:
                    with zipfile.ZipFile(vpk_path, 'w', zipfile.ZIP_STORED) as zipf:
                        for root, _, files in os.walk(build_dir):
                            for file in files:
                                file_path = Path(root) / file
                                arcname = file_path.relative_to(build_dir)
                                zipf.write(file_path, arcname)
                except Exception as e:
                    QMessageBox.critical(self, "Zip Error", f"Failed to create VPK:\n{e}")
                    return

            self._set_status(f"LPP VPK exported: {vpk_path}")
            QMessageBox.information(self, "Export Complete",
                f"LPP VPK created!\n\nTitle: {export_config['title']}\n"
                f"ID: {title_id}\nLocation: {vpk_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Export Failed", f"An unexpected error occurred:\n{e}")

    def open_spritesheet_tool(self):
        QMessageBox.information(self, "Coming Soon", "Spritesheet Builder will be implemented as a separate tool window.")

    def open_tileset_manager(self):
        from tileset_manager import TilesetManagerDialog
        dlg = TilesetManagerDialog(self.project, self)
        if dlg.exec():
            self._mark_unsaved()
            self.editor_tab.refresh(self.project, self.current_scene_index)

    def export_windows(self):
        export_windows_game(self.project, self)
# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    font = QFont("Segoe UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

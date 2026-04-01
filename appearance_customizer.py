# -*- coding: utf-8 -*-
"""
Appearance Customizer - Standalone dialog.
Import this from main.py. Can be excluded from LLM conversations.
"""
from PySide6.QtCore import Qt, QSize, Signal
import json
from typing import Dict
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QColorDialog, QListWidget, QListWidgetItem, QWidget,
    QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox,
    QScrollArea, QTabWidget, QTextEdit, QComboBox, QSlider, QInputDialog
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor

from theme_utils import get_default_theme, theme_to_stylesheet
from theme_manager import save_theme, load_theme, list_saved_themes

# Copy your default theme structure
DEFAULT_THEME = {
    "colors": get_default_theme(),
    "textures": {
        "use_textures": False,
        "background_texture": None,
        "panel_texture": None,
        "surface_texture": None,
        "texture_opacity": 0.05,
    },
    "fonts": {
        "family": "Segoe UI",
        "size": 13,
    },
    "rounding": {
        "button_radius": 4,
        "widget_radius": 4,
        "tab_radius": 0,
    }
}

PRESET_THEMES = {
    "Default Dark": {
        "colors": get_default_theme(),
    },
    "High Contrast": {
        "colors": {
            "DARK": "#000000",
            "PANEL": "#111111",
            "SURFACE": "#1c1c1c",
            "SURFACE2": "#2a2a2a",
            "BORDER": "#4b4b4b",
            "ACCENT": "#00ff66",
            "ACCENT2": "#ff4d4d",
            "TEXT": "#ffffff",
            "TEXT_DIM": "#d0d0d0",
            "TEXT_MUTED": "#8c8c8c",
            "SUCCESS": "#39ff88",
            "WARNING": "#ffd400",
            "DANGER": "#ff5f5f",
        }
    },
    "Soft Pastel": {
        "colors": {
            "DARK": "#2d2d3a",
            "PANEL": "#3a3a4a",
            "SURFACE": "#454560",
            "SURFACE2": "#505070",
            "BORDER": "#62628a",
            "ACCENT": "#a584d6",
            "ACCENT2": "#f2a6c4",
            "TEXT": "#f0ebff",
            "TEXT_DIM": "#bbb4d6",
            "TEXT_MUTED": "#8781a0",
            "SUCCESS": "#8ccf9b",
            "WARNING": "#f3d38a",
            "DANGER": "#db8b8b",
        }
    },
    "Light Studio": {
        "colors": {
            "DARK": "#eef1f5",
            "PANEL": "#e2e7ee",
            "SURFACE": "#ffffff",
            "SURFACE2": "#d7dee8",
            "BORDER": "#b7c2d0",
            "ACCENT": "#3f6fd9",
            "ACCENT2": "#d96a8d",
            "TEXT": "#1f2a38",
            "TEXT_DIM": "#5d6b7c",
            "TEXT_MUTED": "#8491a0",
            "SUCCESS": "#3ea76a",
            "WARNING": "#d2a126",
            "DANGER": "#cc5a5a",
        }
    },
    "Warm Ember": {
        "colors": {
            "DARK": "#18120f",
            "PANEL": "#241a16",
            "SURFACE": "#32231d",
            "SURFACE2": "#402d25",
            "BORDER": "#5a4337",
            "ACCENT": "#d68a4d",
            "ACCENT2": "#f0b27a",
            "TEXT": "#f8eadc",
            "TEXT_DIM": "#c6a992",
            "TEXT_MUTED": "#8d715f",
            "SUCCESS": "#83c98a",
            "WARNING": "#f7c65b",
            "DANGER": "#ef7d57",
        }
    },
    "Cool Ocean": {
        "colors": {
            "DARK": "#0d171c",
            "PANEL": "#13222a",
            "SURFACE": "#18303a",
            "SURFACE2": "#20404c",
            "BORDER": "#2c5663",
            "ACCENT": "#49c6d9",
            "ACCENT2": "#7be0df",
            "TEXT": "#ddf4f7",
            "TEXT_DIM": "#8ab8bf",
            "TEXT_MUTED": "#587b85",
            "SUCCESS": "#59d38c",
            "WARNING": "#f1c75b",
            "DANGER": "#f27d72",
        }
    },
    "Forest Night": {
        "colors": {
            "DARK": "#101612",
            "PANEL": "#18221b",
            "SURFACE": "#223127",
            "SURFACE2": "#2b4031",
            "BORDER": "#41604a",
            "ACCENT": "#74c365",
            "ACCENT2": "#b5d66f",
            "TEXT": "#e9f2e3",
            "TEXT_DIM": "#9db097",
            "TEXT_MUTED": "#667765",
            "SUCCESS": "#70d18d",
            "WARNING": "#e6c95a",
            "DANGER": "#d97d6f",
        }
    },
    "Retro 95": {
        "colors": {
            "DARK": "#008080",
            "PANEL": "#c0c0c0",
            "SURFACE": "#dfdfdf",
            "SURFACE2": "#b8b8b8",
            "BORDER": "#7a7a7a",
            "ACCENT": "#000080",
            "ACCENT2": "#800080",
            "TEXT": "#111111",
            "TEXT_DIM": "#3b3b3b",
            "TEXT_MUTED": "#666666",
            "SUCCESS": "#008000",
            "WARNING": "#b8860b",
            "DANGER": "#a52a2a",
        }
    },
}

class ColorRow(QWidget):
    """Simple row: label + color button + hex input."""
    changed = Signal(str, str)  # key, new_color
    
    def __init__(self, key: str, color: str, label: str = None):
        super().__init__()
        self.key = key
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 2)
        
        lbl = QLabel(label or key.replace("_", " ").title())
        lbl.setStyleSheet("color: #888; min-width: 120px;")
        self.layout.addWidget(lbl)
        
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(40, 24)
        self.color_btn.setStyleSheet(f"background: {color}; border: 1px solid #444; border-radius: 3px;")
        self.color_btn.clicked.connect(self.pick_color)
        self.layout.addWidget(self.color_btn)
        
        self.hex_edit = QTextEdit()
        self.hex_edit.setFixedHeight(24)
        self.hex_edit.setFixedWidth(80)
        self.hex_edit.setText(color)
        self.hex_edit.textChanged.connect(self.hex_changed)
        self.layout.addWidget(self.hex_edit)
        self.layout.addStretch()
    
    def pick_color(self):
        col = QColorDialog.getColor(QColor(self.hex_edit.toPlainText()), self)
        if col.isValid():
            self.hex_edit.setText(col.name())
    
    def hex_changed(self):
        color = self.hex_edit.toPlainText().strip()
        if len(color) == 7 and color.startswith('#'):
            self.color_btn.setStyleSheet(f"background: {color}; border: 1px solid #444; border-radius: 3px;")
            self.changed.emit(self.key, color)

class ThemeCustomizer(QDialog):
    def __init__(self, current_theme: Dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Appearance")
        self.resize(800, 500)
        self.theme = self._merge_theme(current_theme or DEFAULT_THEME)
        self._saved_preset_names: list[str] = []
        self._build_ui()
    
    def _merge_theme(self, custom):
        """Simple merge - you can make this deeper if needed."""
        result = json.loads(json.dumps(DEFAULT_THEME))
        for k, v in custom.items():
            if isinstance(v, dict) and k in result:
                result[k].update(v)
            else:
                result[k] = v
        return result
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background: #16161c; border-bottom: 1px solid #2e2e42;")
        hl = QHBoxLayout(header)
        hl.addWidget(QLabel("🎨 APPEARANCE CUSTOMIZER"))
        hl.addStretch()
        self.preview_cb = QCheckBox("Live Preview")
        self.preview_cb.setChecked(True)
        self.preview_cb.stateChanged.connect(self.toggle_preview)
        hl.addWidget(self.preview_cb)
        layout.addWidget(header)
        
        # Main content
        content = QWidget()
        cl = QHBoxLayout(content)
        
        # Left: Color categories
        left = QWidget()
        left.setFixedWidth(220)
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("PRESETS:"))
        self.preset_list = QListWidget()
        self.preset_list.currentRowChanged.connect(self.load_preset)
        ll.addWidget(self.preset_list)
        self._refresh_preset_list()

        preset_hint = QLabel("Select a preset to load its colors into the editor.")
        preset_hint.setWordWrap(True)
        preset_hint.setStyleSheet("color: #666; font-size: 11px;")
        ll.addWidget(preset_hint)

        self.save_preset_btn = QPushButton("Save Preset…")
        self.save_preset_btn.clicked.connect(self.save_preset)
        ll.addWidget(self.save_preset_btn)

        ll.addSpacing(12)
        ll.addWidget(QLabel("COLOR GROUPS:"))
        self.category_list = QListWidget()
        self.category_list.addItems(["All", "Base", "Text", "Accents"])
        self.category_list.currentRowChanged.connect(self.filter_colors)
        ll.addWidget(self.category_list)
        self.category_list.setCurrentRow(0)
        ll.addStretch()
        cl.addWidget(left)
        
        # Center: Color grid
        center = QWidget()
        self.color_layout = QVBoxLayout(center)
        self.color_rows = {}
        self._build_color_grid()
        cl.addWidget(center)
        
        # Right: Preview
        right = QWidget()
        right.setFixedWidth(250)
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("PREVIEW"))
        self.preview = QWidget()
        self.preview.setFixedHeight(200)
        self.preview.setStyleSheet("background: #0f0f12; border: 1px solid #2e2e42; border-radius: 4px;")
        rl.addWidget(self.preview)
        self.preview_layout = QVBoxLayout(self.preview)
        self._build_preview_widgets()
        rl.addStretch()
        cl.addWidget(right)
        
        layout.addWidget(content)
        
        # Footer
        footer = QWidget()
        footer.setFixedHeight(60)
        fl = QHBoxLayout(footer)
        fl.addWidget(QLabel("Changes applied to running app on Apply."))
        fl.addStretch()
        self.import_btn = QPushButton("Import…")
        self.import_btn.clicked.connect(self.import_theme)
        self.export_btn = QPushButton("Export…")
        self.export_btn.clicked.connect(self.export_theme)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply)
        for btn in [self.import_btn, self.export_btn, self.reset_btn, self.apply_btn]:
            fl.addWidget(btn)
        layout.addWidget(footer)
        self._update_preview()
    
    def _build_color_grid(self):
        """Build color picker rows."""
        groups = {
            "Base": ["DARK", "PANEL", "SURFACE", "SURFACE2", "BORDER"],
            "Text": ["TEXT", "TEXT_DIM", "TEXT_MUTED"],
            "Accents": ["ACCENT", "ACCENT2", "SUCCESS", "WARNING", "DANGER"],
        }
        
        self.all_rows = []
        for group_name, keys in groups.items():
            grp = QGroupBox(group_name)
            gl = QVBoxLayout(grp)
            for key in keys:
                color = self.theme["colors"][key]
                row = ColorRow(key, color)
                row.changed.connect(self.color_changed)
                gl.addWidget(row)
                self.color_rows[key] = row
                self.all_rows.append(row)
            self.color_layout.addWidget(grp)
        
        self.color_layout.addStretch()
    
    def _build_preview_widgets(self):
        """Sample widgets to preview theme."""
        self.preview_layout.addWidget(QLabel("Sample Label"))
        self.preview_layout.addWidget(QPushButton("PushButton"))
        lst = QListWidget()
        lst.addItems(["Item 1", "Item 2", "Item 3"])
        self.preview_layout.addWidget(lst)
        self.preview_layout.addWidget(QCheckBox("CheckBox"))
        self.preview_layout.addStretch()
    
    def color_changed(self, key: str, color: str):
        self.theme["colors"][key] = color
        if self.preview_cb.isChecked():
            self._update_preview()
    
    def _update_preview(self):
        stylesheet = theme_to_stylesheet(self.theme["colors"])
        self.preview.setStyleSheet(stylesheet)
        # Update all preview widgets
        for i in range(self.preview_layout.count()):
            w = self.preview_layout.itemAt(i).widget()
            if w:
                w.setStyleSheet(stylesheet)
    
    def toggle_preview(self):
        if self.preview_cb.isChecked():
            self._update_preview()
        else:
            self.preview.setStyleSheet("")
            for i in range(self.preview_layout.count()):
                w = self.preview_layout.itemAt(i).widget()
                if w:
                    w.setStyleSheet("")
    
    def filter_colors(self, row):
        """Show/hide color rows based on category."""
        item = self.category_list.item(row)
        if item is None:
            return
        category = item.text()
        groups = {
            "Base": {"DARK", "PANEL", "SURFACE", "SURFACE2", "BORDER"},
            "Text": {"TEXT", "TEXT_DIM", "TEXT_MUTED"},
            "Accents": {"ACCENT", "ACCENT2", "SUCCESS", "WARNING", "DANGER"},
        }
        for row_widget in self.all_rows:
            visible = category == "All" or row_widget.key in groups.get(category, set())
            row_widget.setVisible(visible)

    def _refresh_preset_list(self):
        current_name = None
        current_item = self.preset_list.currentItem()
        if current_item is not None:
            current_name = current_item.data(Qt.ItemDataRole.UserRole)

        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        for name in PRESET_THEMES:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip("Built-in preset")
            self.preset_list.addItem(item)

        self._saved_preset_names = sorted(
            [name for name in list_saved_themes() if name not in PRESET_THEMES],
            key=str.lower,
        )
        for name in self._saved_preset_names:
            item = QListWidgetItem(f"{name} (Saved)")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip("Saved preset")
            self.preset_list.addItem(item)

        if self.preset_list.count():
            target_row = 0
            if current_name is not None:
                for i in range(self.preset_list.count()):
                    if self.preset_list.item(i).data(Qt.ItemDataRole.UserRole) == current_name:
                        target_row = i
                        break
            self.preset_list.setCurrentRow(target_row)
        self.preset_list.blockSignals(False)

    def load_preset(self, row: int):
        if row < 0:
            return
        item = self.preset_list.item(row)
        if item is None:
            return
        preset_name = item.data(Qt.ItemDataRole.UserRole)
        preset = PRESET_THEMES.get(preset_name)
        if preset is None and preset_name in self._saved_preset_names:
            preset = load_theme(preset_name)
        if preset is None:
            return
        updated = json.loads(json.dumps(self.theme))
        updated.setdefault("colors", {}).update(preset.get("colors", {}))
        self.theme = self._merge_theme(updated)
        self._refresh_color_rows()
        if self.preview_cb.isChecked():
            self._update_preview()

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        name = name.strip() if ok else ""
        if not name:
            return
        if name in PRESET_THEMES:
            QMessageBox.warning(self, "Preset Exists", "That name is reserved for a built-in preset.")
            return
        try:
            save_theme(name, self.theme)
            self._refresh_preset_list()
            for i in range(self.preset_list.count()):
                if self.preset_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                    self.preset_list.setCurrentRow(i)
                    break
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Theme", "", "JSON (*.json)")
        if path:
            try:
                with open(path) as f:
                    theme = json.load(f)
                self.theme = self._merge_theme(theme)
                self._refresh_color_rows()
                if self.preview_cb.isChecked():
                    self._update_preview()
            except Exception as e:
                QMessageBox.critical(self, "Import Failed", str(e))
    
    def export_theme(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Theme", "my_theme.json", "JSON (*.json)")
        if path:
            try:
                with open(path, "w") as f:
                    json.dump(self.theme, f, indent=2)
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))
    
    def reset(self):
        self.theme = json.loads(json.dumps(DEFAULT_THEME))
        self._refresh_color_rows()
        if self.preview_cb.isChecked():
            self._update_preview()
    
    def _refresh_color_rows(self):
        for key, row in self.color_rows.items():
            color = self.theme["colors"][key]
            row.hex_edit.setText(color)
            row.color_btn.setStyleSheet(f"background: {color}; border: 1px solid #444; border-radius: 3px;")
    
    def apply(self):
        """Emit the theme to main window."""
        self.accept()

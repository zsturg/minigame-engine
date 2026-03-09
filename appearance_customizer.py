# -*- coding: utf-8 -*-
"""
Appearance Customizer - Standalone dialog.
Import this from main.py. Can be excluded from LLM conversations.
"""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
import json
from typing import Dict
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QColorDialog, QListWidget, QListWidgetItem, QWidget,
    QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox,
    QScrollArea, QTabWidget, QTextEdit, QComboBox, QSlider
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor

from theme_utils import get_default_theme, theme_to_stylesheet

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

class ColorRow(QWidget):
    """Simple row: label + color button + hex input."""
    changed = pyqtSignal(str, str)  # key, new_color
    
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
        left.setFixedWidth(200)
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("COLOR GROUPS:"))
        self.category_list = QListWidget()
        self.category_list.addItems(["All", "Base", "Text", "Accents"])
        self.category_list.currentRowChanged.connect(self.filter_colors)
        ll.addWidget(self.category_list)
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
        category = self.category_list.item(row).text()
        for row_widget in self.all_rows:
            row_widget.setVisible(True)  # Simplified - you can implement real filtering
    
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
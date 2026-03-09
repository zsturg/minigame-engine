# -*- coding: utf-8 -*-
"""
Theme Customizer for Vita Adventure Creator
Standalone dialog for editing app colors and textures.
Invoke via Tools → Customize Appearance in main.py
"""

from __future__ import annotations
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QColorDialog, QListWidget, QListWidgetItem, QWidget,
    QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox,
    QScrollArea, QTabWidget, QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QBrush, QPixmap, QPainter

# ─────────────────────────────────────────────────────────────
#  DEFAULT THEME (matches main.py's current colors)
# ─────────────────────────────────────────────────────────────

DEFAULT_THEME = {
    "colors": {
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
    },
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

# ─────────────────────────────────────────────────────────────
#  HELPER WIDGETS
# ─────────────────────────────────────────────────────────────

class ColorPickerWidget(QWidget):
    """A row with a color label, preview, and hex input."""
    changed = pyqtSignal(str, str)  # key, new_color

    def __init__(self, key: str, color: str, label: str = None, parent=None):
        super().__init__(parent)
        self.key = key
        self.color = color
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 4, 0, 4)
        self.layout.setSpacing(8)

        # Label
        self.lbl = QLabel(label or key)
        self.lbl.setStyleSheet(f"color: #888; font-size: 12px; min-width: 100px;")
        self.layout.addWidget(self.lbl)

        # Color preview button
        self.preview = QPushButton()
        self.preview.setFixedSize(32, 24)
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setStyleSheet(self._button_style(color))
        self.preview.clicked.connect(self._open_dialog)
        self.layout.addWidget(self.preview)

        # Hex input
        self.hex_edit = QTextEdit()
        self.hex_edit.setFixedHeight(24)
        self.hex_edit.setFixedWidth(80)
        self.hex_edit.setStyleSheet("""
            QTextEdit {
                background: #1e1e28;
                color: #e8e6f0;
                border: 1px solid #2e2e42;
                border-radius: 3px;
                padding: 2px 4px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        self.hex_edit.setText(color.upper())
        self.hex_edit.textChanged.connect(self._hex_changed)
        self.layout.addWidget(self.hex_edit)

        self.layout.addStretch()

    def _button_style(self, color: str) -> str:
        return f"""
            QPushButton {{
                background: {color};
                border: 1px solid #444;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border: 1px solid #7c6aff;
            }}
        """

    def _open_dialog(self):
        col = QColorDialog.getColor(QColor(self.color), self, "Choose Color")
        if col.isValid():
            hexcol = col.name()
            self._set_color(hexcol)

    def _hex_changed(self):
        text = self.hex_edit.toPlainText().strip()
        if len(text) == 7 and text.startswith('#') and all(c in "0123456789ABCDEFabcdef" for c in text[1:]):
            self._set_color(text)

    def _set_color(self, hexcol: str):
        self.color = hexcol
        self.preview.setStyleSheet(self._button_style(hexcol))
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(hexcol.upper())
        self.hex_edit.blockSignals(False)
        self.changed.emit(self.key, hexcol)

    def update_color(self, hexcol: str):
        self.color = hexcol
        self.preview.setStyleSheet(self._button_style(hexcol))
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(hexcol.upper())
        self.hex_edit.blockSignals(False)


class TexturePickerWidget(QWidget):
    """Row for texture selection with opacity slider."""
    changed = pyqtSignal(str, object)

    def __init__(self, key: str, value: dict, parent=None):
        super().__init__(parent)
        self.key = key
        self.value = value.copy()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 8)
        self.layout.setSpacing(4)

        # Row 1: Checkbox + label
        row1 = QHBoxLayout()
        self.check = QCheckBox(f"Enable {key.replace('_texture', '')} texture")
        self.check.setChecked(self.value.get("enabled", False))
        self.check.stateChanged.connect(self._on_check)
        row1.addWidget(self.check)
        row1.addStretch()
        self.layout.addLayout(row1)

        # Row 2: File picker
        self.path_row = QHBoxLayout()
        self.path_edit = QTextEdit()
        self.path_edit.setFixedHeight(24)
        self.path_edit.setPlaceholderText("Path to image file (PNG, JPG)…")
        self.path_edit.setText(self.value.get("path", "") or "")
        self.path_edit.textChanged.connect(self._on_path_changed)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        self.path_row.addWidget(self.path_edit, stretch=1)
        self.path_row.addWidget(self.browse_btn)
        self.layout.addLayout(self.path_row)
        self.path_row.setEnabled(self.check.isChecked())

        # Row 3: Opacity
        self.opacity_row = QHBoxLayout()
        self.opacity_row.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSpinBox()
        self.opacity_slider.setRange(1, 100)
        self.opacity_slider.setValue(int(self.value.get("opacity", 5) * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_row.addWidget(self.opacity_slider)
        self.opacity_row.addWidget(QLabel("%"))
        self.opacity_row.addStretch()
        self.layout.addLayout(self.opacity_row)
        self.opacity_row.setEnabled(self.check.isChecked())

    def _on_check(self, state):
        enabled = state == Qt.CheckState.Checked
        self.path_row.setEnabled(enabled)
        self.opacity_row.setEnabled(enabled)
        self.value["enabled"] = enabled
        self.changed.emit(self.key, self.value)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Texture", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)
            self.value["path"] = path
            self.changed.emit(self.key, self.value)

    def _on_path_changed(self):
        self.value["path"] = self.path_edit.toPlainText().strip() or None
        self.changed.emit(self.key, self.value)

    def _on_opacity(self, val):
        self.value["opacity"] = val / 100.0
        self.changed.emit(self.key, self.value)

    def update_value(self, value: dict):
        self.value = value.copy()
        self.check.setChecked(value.get("enabled", False))
        self.path_edit.setText(value.get("path", "") or "")
        self.opacity_slider.setValue(int(value.get("opacity", 0.05) * 100))


# ─────────────────────────────────────────────────────────────
#  MAIN DIALOG
# ─────────────────────────────────────────────────────────────

class ThemeCustomizerDialog(QDialog):
    """Large dialog for editing app appearance."""
    theme_applied = pyqtSignal(dict)  # emits full theme dict when applied

    def __init__(self, current_theme: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Appearance")
        self.setModal(True)
        self.resize(900, 700)
        self.setStyleSheet("background: #16161c; color: #e8e6f0;")

        self.theme = self._merge_theme(current_theme or DEFAULT_THEME)
        self._build_ui()

    def _merge_theme(self, custom: dict) -> dict:
        """Deep merge custom theme with defaults to ensure all keys exist."""
        def merge(dest, src):
            for k, v in src.items():
                if isinstance(v, dict) and k in dest and isinstance(dest[k], dict):
                    merge(dest[k], v)
                else:
                    dest[k] = v
            return dest
        merged = json.loads(json.dumps(DEFAULT_THEME))  # deep copy
        return merge(merged, custom)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background: #16161c; border-bottom: 1px solid #2e2e42; padding: 0 16px;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("🎨 APPEARANCE CUSTOMIZER")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #7c6aff;")
        hl.addWidget(title)
        hl.addStretch()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setChecked(True)
        self.preview_btn.clicked.connect(self._toggle_preview)
        hl.addWidget(self.preview_btn)
        layout.addWidget(header)

        # Main content
        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Left: Theme presets
        left = QWidget()
        left.setFixedWidth(200)
        left.setStyleSheet("background: #0f0f12; border-right: 1px solid #2e2e42;")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)
        ll.setSpacing(4)

        ll.addWidget(QLabel("PRESETS:"))
        self.preset_list = QListWidget()
        self.preset_list.setStyleSheet("""
            QListWidget {
                background: #1e1e28;
                border: 1px solid #2e2e42;
                border-radius: 4px;
                color: #e8e6f0;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #26263a;
            }
            QListWidget::item:selected {
                background: #7c6aff;
                color: white;
            }
        """)
        presets = ["Default Dark", "High Contrast", "Soft Pastel", "Warm", "Cool"]
        for name in presets:
            self.preset_list.addItem(name)
        self.preset_list.currentRowChanged.connect(self._load_preset)
        ll.addWidget(self.preset_list)

        ll.addSpacing(12)
        self.save_preset_btn = QPushButton("Save Preset…")
        self.save_preset_btn.clicked.connect(self._save_preset)
        ll.addWidget(self.save_preset_btn)

        ll.addStretch()
        cl.addWidget(left)

        # Right: Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #0f0f12;
            }
            QTabBar::tab {
                background: #16161c;
                color: #7a7890;
                padding: 10px 16px;
                border: none;
                border-bottom: 2px solid transparent;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                color: #e8e6f0;
                border-bottom: 2px solid #7c6aff;
                background: #0f0f12;
            }
        """)

        # Tab 1: Colors
        self.color_tab = QWidget()
        self._build_color_tab()
        self.tabs.addTab(self.color_tab, "Colors")

        # Tab 2: Textures
        self.texture_tab = QWidget()
        self._build_texture_tab()
        self.tabs.addTab(self.texture_tab, "Textures")

        # Tab 3: Fonts & Rounding
        self.misc_tab = QWidget()
        self._build_misc_tab()
        self.tabs.addTab(self.misc_tab, "Fonts & UI")

        cl.addWidget(self.tabs, stretch=1)

        # Preview pane (right side)
        self.preview_pane = PreviewPane(self.theme)
        self.preview_pane.setFixedWidth(280)
        cl.addWidget(self.preview_pane)

        layout.addWidget(content, stretch=1)

        # Footer
        footer = QWidget()
        footer.setFixedHeight(60)
        footer.setStyleSheet("background: #16161c; border-top: 1px solid #2e2e42;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.addWidget(QLabel("Changes apply to the running app. Restart to see texture changes."))
        fl.addStretch()
        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        fl.addWidget(self.reset_btn)
        self.import_btn = QPushButton("Import…")
        self.import_btn.clicked.connect(self._import_theme)
        fl.addWidget(self.import_btn)
        self.export_btn = QPushButton("Export…")
        self.export_btn.clicked.connect(self._export_theme)
        fl.addWidget(self.export_btn)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background: #7c6aff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: 600;
            }
            QPushButton:hover { background: #6a59ef; }
        """)
        self.apply_btn.clicked.connect(self._apply)
        fl.addWidget(self.apply_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        fl.addWidget(self.cancel_btn)
        layout.addWidget(footer)

        # Build color pickers
        self.color_pickers: dict[str, ColorPickerWidget] = {}
        self._build_color_pickers()

    def _build_color_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.color_layout = QVBoxLayout(content)
        self.color_layout.setSpacing(8)
        scroll.setWidget(content)
        self.color_tab.setLayout(QVBoxLayout())
        self.color_tab.layout().addWidget(scroll)

    def _build_color_pickers(self):
        # Clear existing
        while self.color_layout.count():
            item = self.color_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        groups = {
            "Base": ["DARK", "PANEL", "SURFACE", "SURFACE2", "BORDER"],
            "Text": ["TEXT", "TEXT_DIM", "TEXT_MUTED"],
            "Accents": ["ACCENT", "ACCENT2", "SUCCESS", "WARNING", "DANGER"],
        }

        for group_name, keys in groups.items():
            grp = QGroupBox(group_name)
            grp.setStyleSheet("""
                QGroupBox {
                    background: #1e1e28;
                    border: 1px solid #2e2e42;
                    border-radius: 6px;
                    margin-top: 12px;
                    font-weight: 600;
                    padding-top: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                    color: #7c6aff;
                }
            """)
            gl = QVBoxLayout(grp)
            gl.setContentsMargins(10, 12, 10, 10)
            gl.setSpacing(6)

            for key in keys:
                color = self.theme["colors"][key]
                picker = ColorPickerWidget(key, color, key.replace("_", " ").title())
                picker.changed.connect(self._on_color_changed)
                gl.addWidget(picker)
                self.color_pickers[key] = picker

            self.color_layout.addWidget(grp)

        self.color_layout.addStretch()

    def _build_texture_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        tl = QVBoxLayout(content)
        tl.setSpacing(12)

        # Global texture toggle
        self.texture_enable = QCheckBox("Enable Textures (alpha-blended overlays)")
        self.texture_enable.setChecked(self.theme["textures"]["use_textures"])
        self.texture_enable.stateChanged.connect(self._on_global_texture_toggle)
        tl.addWidget(self.texture_enable)

        # Individual texture controls
        self.texture_pickers: dict[str, TexturePickerWidget] = {}
        for key in ["background_texture", "panel_texture", "surface_texture"]:
            picker = TexturePickerWidget(key, self.theme["textures"])
            picker.changed.connect(self._on_texture_changed)
            self.texture_pickers[key] = picker
            tl.addWidget(picker)

        tl.addStretch()
        scroll.setWidget(content)
        self.texture_tab.setLayout(QVBoxLayout())
        self.texture_tab.layout().addWidget(scroll)

    def _build_misc_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        ml = QVBoxLayout(content)
        ml.setSpacing(16)

        # Font settings
        font_grp = QGroupBox("Application Font")
        font_grp.setStyleSheet("""
            QGroupBox {
                background: #1e1e28;
                border: 1px solid #2e2e42;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: 600;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #7c6aff;
            }
        """)
        fl = QVBoxLayout(font_grp)
        fl.setContentsMargins(12, 12, 12, 12)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font Family:"))
        self.font_family = QComboBox()
        self.font_family.addItems(["Segoe UI", "SF Pro Display", "Arial", "Helvetica", "Consolas"])
        self.font_family.setCurrentText(self.theme["fonts"]["family"])
        self.font_family.currentTextChanged.connect(self._on_font_changed)
        font_row.addWidget(self.font_family)
        fl.addLayout(font_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Base Size:"))
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(self.theme["fonts"]["size"])
        self.font_size.valueChanged.connect(self._on_font_size_changed)
        size_row.addWidget(self.font_size)
        size_row.addWidget(QLabel("px"))
        size_row.addStretch()
        fl.addLayout(size_row)

        ml.addWidget(font_grp)

        # Rounding
        round_grp = QGroupBox("Border Rounding (pixels)")
        round_grp.setStyleSheet("""
            QGroupBox {
                background: #1e1e28;
                border: 1px solid #2e2e42;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: 600;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #7c6aff;
            }
        """)
        rl = QVBoxLayout(round_grp)
        rl.setContentsMargins(12, 12, 12, 12)

        for key, label in [
            ("button_radius", "Buttons"),
            ("widget_radius", "Widgets"),
            ("tab_radius", "Tabs"),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setValue(self.theme["rounding"][key])
            spin.valueChanged.connect(lambda v, k=key: self._on_rounding_changed(k, v))
            row.addWidget(spin)
            row.addStretch()
            rl.addLayout(row)

        ml.addWidget(round_grp)
        ml.addStretch()

        scroll.setWidget(content)
        self.misc_tab.setLayout(QVBoxLayout())
        self.misc_tab.layout().addWidget(scroll)

    # ── Signals ────────────────────────────────────────────────

    def _on_color_changed(self, key: str, color: str):
        self.theme["colors"][key] = color
        self._update_preview()

    def _on_texture_changed(self, key: str, value: dict):
        self.theme["textures"][key] = value
        self._update_preview()

    def _on_global_texture_toggle(self, state):
        self.theme["textures"]["use_textures"] = state == Qt.CheckState.Checked
        for picker in self.texture_pickers.values():
            picker.setEnabled(state == Qt.CheckState.Checked)
        self._update_preview()

    def _on_font_changed(self, family: str):
        self.theme["fonts"]["family"] = family

    def _on_font_size_changed(self, size: int):
        self.theme["fonts"]["size"] = size

    def _on_rounding_changed(self, key: str, value: int):
        self.theme["rounding"][key] = value

    def _update_preview(self):
        if self.preview_btn.isChecked():
            self.preview_pane.apply_theme(self.theme)

    def _toggle_preview(self):
        self._update_preview()

    # ── Presets ────────────────────────────────────────────────

    def _load_preset(self, index: int):
        presets = {
            "Default Dark": DEFAULT_THEME,
            "High Contrast": {
                "colors": {
                    "DARK": "#000000",
                    "PANEL": "#111111",
                    "SURFACE": "#222222",
                    "SURFACE2": "#333333",
                    "BORDER": "#444444",
                    "ACCENT": "#00FF00",
                    "ACCENT2": "#FF0000",
                    "TEXT": "#FFFFFF",
                    "TEXT_DIM": "#CCCCCC",
                    "TEXT_MUTED": "#888888",
                    "SUCCESS": "#00FF00",
                    "WARNING": "#FFFF00",
                    "DANGER": "#FF0000",
                }
            },
            "Soft Pastel": {
                "colors": {
                    "DARK": "#2D2D3A",
                    "PANEL": "#3A3A4A",
                    "SURFACE": "#454560",
                    "SURFACE2": "#505070",
                    "BORDER": "#606080",
                    "ACCENT": "#9B7BB8",
                    "ACCENT2": "#B58FC7",
                    "TEXT": "#E0D8F0",
                    "TEXT_DIM": "#A0A0B0",
                    "TEXT_MUTED": "#606080",
                    "SUCCESS": "#8FBC8F",
                    "WARNING": "#F0E68C",
                    "DANGER": "#CD5C5C",
                }
            },
            "Warm": {
                "colors": {
                    "DARK": "#1A1614",
                    "PANEL": "#241F1C",
                    "SURFACE": "#2E2824",
                    "SURFACE2": "#38322D",
                    "BORDER": "#423C37",
                    "ACCENT": "#D4A574",
                    "ACCENT2": "#E8C19A",
                    "TEXT": "#F5E6D3",
                    "TEXT_DIM": "#B0A090",
                    "TEXT_MUTED": "#807060",
                    "SUCCESS": "#90EE90",
                    "WARNING": "#FFD700",
                    "DANGER": "#FF6347",
                }
            },
            "Cool": {
                "colors": {
                    "DARK": "#0F1A1F",
                    "PANEL": "#152228",
                    "SURFACE": "#1A2C33",
                    "SURFACE2": "#203639",
                    "BORDER": "#28403F",
                    "ACCENT": "#5CC9C7",
                    "ACCENT2": "#7DD9D6",
                    "TEXT": "#D0E8E6",
                    "TEXT_DIM": "#80B0AE",
                    "TEXT_MUTED": "#507070",
                    "SUCCESS": "#4ADE80",
                    "WARNING": "#FACC15",
                    "DANGER": "#F87171",
                }
            },
        }
        name = self.preset_list.item(index).text()
        if name in presets:
            preset = presets[name]
            self._apply_preset(preset)

    def _apply_preset(self, preset: dict):
        # Merge selectively (keep textures/fonts unless overridden)
        for key, value in preset.get("colors", {}).items():
            if key in self.theme["colors"]:
                self.theme["colors"][key] = value
                if key in self.color_pickers:
                    self.color_pickers[key].update_color(value)
        self._update_preview()

    def _save_preset(self):
        name, ok = QMessageBox.getText(self, "Save Preset", "Preset name:")
        if ok and name:
            # Save to ~/.vita_adventure_creator/themes/
            theme_dir = Path.home() / ".vita_adventure_creator" / "themes"
            theme_dir.mkdir(parents=True, exist_ok=True)
            path = theme_dir / f"{name}.json"
            with open(path, "w") as f:
                json.dump(self.theme, f, indent=2)
            QMessageBox.information(self, "Saved", f"Preset saved to {path}")

    # ── Import / Export ───────────────────────────────────────

    def _import_theme(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Theme", "",
            "Theme JSON (*.json);;All Files (*)"
        )
        if path:
            try:
                with open(path) as f:
                    theme = json.load(f)
                self.theme = self._merge_theme(theme)
                self._refresh_all_editors()
                self._update_preview()
            except Exception as e:
                QMessageBox.critical(self, "Import Failed", str(e))

    def _export_theme(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme", "my_theme.json",
            "Theme JSON (*.json);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w") as f:
                    json.dump(self.theme, f, indent=2)
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    # ── Reset / Apply ──────────────────────────────────────────

    def _reset_defaults(self):
        self.theme = self._merge_theme(DEFAULT_THEME)
        self._refresh_all_editors()
        self._update_preview()

    def _refresh_all_editors(self):
        for picker in self.color_pickers.values():
            picker.update_color(self.theme["colors"][picker.key])
        for picker in self.texture_pickers.values():
            picker.update_value(self.theme["textures"])
        self.font_family.setCurrentText(self.theme["fonts"]["family"])
        self.font_size.setValue(self.theme["fonts"]["size"])
        self.texture_enable.setChecked(self.theme["textures"]["use_textures"])
        for k in self.texture_pickers:
            self.texture_pickers[k].setEnabled(self.theme["textures"]["use_textures"])

    def _apply(self):
        self.theme_applied.emit(self.theme)
        self.accept()


# ─────────────────────────────────────────────────────────────
#  PREVIEW PANEL
# ─────────────────────────────────────────────────────────────

class PreviewPane(QWidget):
    """Shows a mini version of the app with current theme applied."""
    def __init__(self, theme: dict):
        super().__init__()
        self.setFixedWidth(280)
        self.setStyleSheet("background: #0f0f12;")
        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("PREVIEW"))
        layout.addWidget(QLabel("This panel updates live as you edit."))

        # Sample widgets
        self.sample_label = QLabel("Sample Label")
        layout.addWidget(self.sample_label)

        self.sample_button = QPushButton("PushButton")
        layout.addWidget(self.sample_button)

        self.sample_list = QListWidget()
        self.sample_list.addItems(["Item 1", "Item 2", "Item 3"])
        self.sample_list.setFixedHeight(80)
        layout.addWidget(self.sample_list)

        self.sample_check = QCheckBox("CheckBox")
        layout.addWidget(self.sample_check)

        layout.addStretch()

    def apply_theme(self, theme: dict):
        colors = theme["colors"]
        rounding = theme["rounding"]

        # Build mini stylesheet just for this preview
        mini_style = f"""
            QWidget {{
                background: {colors['DARK']};
                color: {colors['TEXT']};
                font-family: {theme['fonts']['family']};
                font-size: {theme['fonts']['size']}px;
            }}
            QPushButton {{
                background: {colors['SURFACE2']};
                color: {colors['TEXT']};
                border: 1px solid {colors['BORDER']};
                border-radius: {rounding['button_radius']}px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background: {colors['ACCENT']};
                color: white;
                border: 1px solid {colors['ACCENT']};
            }}
            QListWidget {{
                background: {colors['SURFACE']};
                border: 1px solid {colors['BORDER']};
                border-radius: {rounding['widget_radius']}px;
                color: {colors['TEXT']};
            }}
            QListWidget::item:selected {{
                background: {colors['ACCENT']};
                color: white;
            }}
            QCheckBox {{
                color: {colors['TEXT']};
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {colors['BORDER']};
                border-radius: 3px;
                background: {colors['SURFACE']};
            }}
            QCheckBox::indicator:checked {{
                background: {colors['ACCENT']};
                border: 1px solid {colors['ACCENT']};
            }}
        """

        self.setStyleSheet(mini_style)
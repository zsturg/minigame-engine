# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — Game Data Tab
Registries for images, audio, fonts + global variables, flags, inventory, project settings.
This tab feeds every dropdown in the rest of the app.
"""

from __future__ import annotations
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QFrame, QSplitter, QScrollArea,
    QTextEdit, QGroupBox, QSizePolicy, QAbstractItemView,
    QMessageBox, QColorDialog, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPixmap, QIcon, QPainter
from project_explorer import import_asset_to_project
from models import (
    Project, RegisteredImage, RegisteredAudio, RegisteredFont,
    GameVariable, InventoryItem, GameData, InputAction
)

# ── Colours (match main.py) ──────────────────────────────────
DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURF2   = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
ACCENT2 = "#ff6a9b"
TEXT    = "#e8e6f0"
DIM     = "#7a7890"
MUTED   = "#4a4860"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER  = "#f87171"

# ── Image category colours ───────────────────────────────────
CAT_COLORS = {
    "background": "#7c6aff",
    "foreground":  "#06b6d4",
    "character":   "#f59e0b",
    "ui":          "#4ade80",
    "other":       "#7a7890",
}

# ── Audio type colours ───────────────────────────────────────
AUDIO_COLORS = {
    "music": "#c084fc",
    "sfx":   "#fb923c",
}

# ── Variable type colours ────────────────────────────────────
VAR_COLORS = {
    "number": "#38bdf8",
    "string": "#4ade80",
    "bool":   "#fb923c",
}

# ── Input event colours ──────────────────────────────────────
INPUT_COLORS = {
    "pressed":  "#7c6aff",
    "released": "#ff6a9b",
    "held":     "#facc15",
    "hold_for": "#4ade80",
}

INPUT_BUTTONS = [
    "cross", "circle", "square", "triangle",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "l", "r",
    "start", "select",
]

INPUT_EVENTS = ["pressed", "released", "held", "hold_for"]

# ── Action name validation ───────────────────────────────────
import re as _re
_ACTION_NAME_RE = _re.compile(r'^[a-z][a-z0-9_]{0,31}$')


# ─────────────────────────────────────────────────────────────
#  SHARED HELPERS
# ─────────────────────────────────────────────────────────────

def _tag_label(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {color};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.8px;
        background: transparent;
    """)
    return lbl


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(f"""
        color: {DIM};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.5px;
        padding: 10px 0 4px 0;
        background: transparent;
    """)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
    return f


def _field_style():
    return f"""
        QLineEdit, QComboBox, QSpinBox, QTextEdit {{
            background: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 12px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {{
            border-color: {ACCENT};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background: {SURF2};
            color: {TEXT};
            border: 1px solid {BORDER};
            selection-background-color: {ACCENT};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            background: {SURF2};
            border: none;
            width: 16px;
        }}
        QCheckBox {{
            color: {TEXT};
            font-size: 12px;
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {BORDER};
            border-radius: 3px;
            background: {SURFACE};
        }}
        QCheckBox::indicator:checked {{
            background: {ACCENT};
            border-color: {ACCENT};
        }}
    """


def _btn(label: str, accent=False, danger=False, small=False) -> QPushButton:
    b = QPushButton(label)
    h = 28 if small else 32
    b.setFixedHeight(h)
    
    if accent:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT}; 
                color: white; 
                border: none;
                border-radius: 4px; 
                padding: 0 12px;
                font-size: 12px; 
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #6a59ef; }}
            QPushButton:pressed {{ background-color: #5a4adf; }}
        """)
    elif danger:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; 
                color: {DANGER};
                border: 1px solid {DANGER}; 
                border-radius: 4px;
                padding: 0 12px; 
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {DANGER}; color: white; }}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: {SURF2}; 
                color: {TEXT};
                border: 1px solid {BORDER}; 
                border-radius: 4px;
                padding: 0 12px; 
                font-size: 12px;
            }}
            QPushButton:hover {{ 
                background-color: {ACCENT}; 
                border-color: {ACCENT}; 
                color: white; 
            }}
        """)
    return b


# ─────────────────────────────────────────────────────────────
#  REGISTRY PANEL  (generic left-list + right-editor pattern)
# ─────────────────────────────────────────────────────────────

class RegistryPanel(QWidget):
    """
    Reusable panel: a list on the left, an editor on the right.
    Subclasses implement _build_editor(), _load_item(), _save_item(), _new_item().
    """
    changed = pyqtSignal()  # emitted whenever registry data changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []          # list of data objects
        self._current_idx = -1
        self._suppress = False
        self._build_shell()

    def _build_shell(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: list ──────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px; border-radius: 3px;
                border-bottom: 1px solid {BORDER};
            }}
            QListWidget::item:selected {{
                background: {ACCENT}; color: white;
            }}
            QListWidget::item:hover:!selected {{ background: {SURF2}; }}
        """)
        self.list_widget.currentRowChanged.connect(self._on_select)
        lv.addWidget(self.list_widget)

        btns = QHBoxLayout()
        btns.setSpacing(4)
        self.add_btn = _btn("+ Add", accent=True, small=True)
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = _btn("x", danger=True, small=True)
        self.del_btn.setFixedWidth(32)
        self.del_btn.clicked.connect(self._on_delete)
        btns.addWidget(self.add_btn)
        btns.addWidget(self.del_btn)
        lv.addLayout(btns)
        root.addWidget(left)

        # ── Right: editor (built by subclass) ───────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("border: none; background: transparent;")

        self.editor_widget = QWidget()
        self.editor_widget.setStyleSheet(f"background: {DARK};")
        self.editor_layout = QVBoxLayout(self.editor_widget)
        self.editor_layout.setContentsMargins(20, 16, 20, 20)
        self.editor_layout.setSpacing(8)

        self._build_editor()
        self.editor_layout.addStretch()

        right_scroll.setWidget(self.editor_widget)
        root.addWidget(right_scroll, stretch=1)

        self._show_empty()

    # Subclasses override these ──────────────────────────────

    def _build_editor(self):
        """Build the right-panel editor widgets."""
        pass

    def _load_item(self, item):
        """Populate editor from item data."""
        pass

    def _save_item(self, item):
        """Read editor fields back into item data."""
        pass

    def _new_item(self):
        """Return a fresh data object."""
        raise NotImplementedError

    def _item_label(self, item) -> str:
        return getattr(item, "name", "Unnamed")

    def _item_color(self, item) -> str:
        return TEXT

    def _show_empty(self):
        self.editor_widget.setEnabled(False)

    def _show_editor(self):
        self.editor_widget.setEnabled(True)

    # Core logic ─────────────────────────────────────────────

    def load_items(self, items: list, project: Project = None):
        self._items = items
        self._project = project
        self._refresh_list()
        if self._items:
            self.list_widget.setCurrentRow(0)
        else:
            self._current_idx = -1
            self._show_empty()

    def _refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for item in self._items:
            li = QListWidgetItem(self._item_label(item))
            li.setForeground(QColor(self._item_color(item)))
            self.list_widget.addItem(li)
        self.list_widget.blockSignals(False)

    def _on_select(self, row: int):
        if self._suppress:
            return
        if 0 <= row < len(self._items):
            self._current_idx = row
            self._suppress = True
            self._load_item(self._items[row])
            self._suppress = False
            self._show_editor()
        else:
            self._current_idx = -1
            self._show_empty()

    def _on_add(self):
        item = self._new_item()
        self._items.append(item)
        self._refresh_list()
        self.list_widget.setCurrentRow(len(self._items) - 1)
        self.changed.emit()

    def _on_delete(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._items):
            return
        self._items.pop(row)
        self._refresh_list()
        new_row = min(row, len(self._items) - 1)
        if new_row >= 0:
            self.list_widget.setCurrentRow(new_row)
        else:
            self._current_idx = -1
            self._show_empty()
        self.changed.emit()

    def _emit_change(self):
        if not self._suppress and self._current_idx >= 0:
            self._save_item(self._items[self._current_idx])
            self._refresh_list()
            self.changed.emit()


# ─────────────────────────────────────────────────────────────
#  IMAGE REGISTRY
# ─────────────────────────────────────────────────────────────

class ImageRegistryPanel(RegistryPanel):
    def _item_label(self, item: RegisteredImage) -> str:
        cat = item.category.upper()
        name = item.name or Path(item.path).name if item.path else "unnamed"
        return f"[{cat}]  {name}"

    def _item_color(self, item: RegisteredImage) -> str:
        return CAT_COLORS.get(item.category, TEXT)

    def _new_item(self) -> RegisteredImage:
        return RegisteredImage(name="New Image", category="background")

    def _build_editor(self):
        self.editor_layout.addWidget(_section("IMAGE ASSET"))
        self.editor_layout.addWidget(_divider())

        # Thumbnail
        self.thumb = QLabel()
        self.thumb.setFixedSize(240, 135)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(f"""
            background: {SURFACE}; border: 1px solid {BORDER};
            border-radius: 4px; color: {DIM}; font-size: 11px;
        """)
        self.thumb.setText("No image")
        self.editor_layout.addWidget(self.thumb)

        # Path row
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("File path…")
        self.path_edit.setReadOnly(True)
        self.path_edit.setStyleSheet(_field_style())
        browse_btn = _btn("Browse…", small=True)
        browse_btn.clicked.connect(self._browse_image)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        self.editor_layout.addLayout(path_row)

        # Name
        self.editor_layout.addWidget(_section("NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Friendly name used in dropdowns…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit_change)
        self.editor_layout.addWidget(self.name_edit)

        # Category
        self.editor_layout.addWidget(_section("CATEGORY"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(["background", "foreground", "character", "ui", "other"])
        self.cat_combo.setStyleSheet(_field_style())
        self.cat_combo.currentTextChanged.connect(self._emit_change)
        self.editor_layout.addWidget(self.cat_combo)

        # Info row
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        self.editor_layout.addWidget(self.info_label)

    def _browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not path:
            return
        p = Path(path)
        
        # Copy to project folder if set
        final_path = path
        if self._project and self._project.project_folder:
            filename = import_asset_to_project(path, self._project.project_folder)
            if filename:
                final_path = str(Path(self._project.project_folder) / filename)
        
        self.path_edit.setText(final_path)
        if not self.name_edit.text():
            self.name_edit.setText(p.stem)
        self._update_thumb(final_path)
        self._emit_change()

    def _update_thumb(self, path: str):
        px = QPixmap(path)
        if px.isNull():
            self.thumb.setText("Cannot load image")
            self.info_label.setText("")
        else:
            scaled = px.scaled(240, 135,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.thumb.setPixmap(scaled)
            self.info_label.setText(f"{px.width()} × {px.height()} px")

    def _load_item(self, item: RegisteredImage):
        self.name_edit.setText(item.name)
        self.path_edit.setText(item.path or "")
        idx = self.cat_combo.findText(item.category)
        if idx >= 0:
            self.cat_combo.setCurrentIndex(idx)
        if item.path:
            self._update_thumb(item.path)
        else:
            self.thumb.setText("No image")
            self.info_label.setText("")

    def _save_item(self, item: RegisteredImage):
        item.name = self.name_edit.text().strip() or "Unnamed"
        item.path = self.path_edit.text() or None
        item.category = self.cat_combo.currentText()


# ─────────────────────────────────────────────────────────────
#  AUDIO REGISTRY
# ─────────────────────────────────────────────────────────────

class AudioRegistryPanel(RegistryPanel):
    def _item_label(self, item: RegisteredAudio) -> str:
        t = item.audio_type.upper()
        return f"[{t}]  {item.name or 'Unnamed'}"

    def _item_color(self, item: RegisteredAudio) -> str:
        return AUDIO_COLORS.get(item.audio_type, TEXT)

    def _new_item(self) -> RegisteredAudio:
        return RegisteredAudio(name="New Audio", audio_type="music")

    def _build_editor(self):
        self.editor_layout.addWidget(_section("AUDIO ASSET"))
        self.editor_layout.addWidget(_divider())

        # Path row
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("File path…")
        self.path_edit.setReadOnly(True)
        self.path_edit.setStyleSheet(_field_style())
        browse_btn = _btn("Browse…", small=True)
        browse_btn.clicked.connect(self._browse_audio)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        self.editor_layout.addLayout(path_row)

        # Name
        self.editor_layout.addWidget(_section("NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Friendly name…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit_change)
        self.editor_layout.addWidget(self.name_edit)

        # Type
        self.editor_layout.addWidget(_section("TYPE"))
        type_row = QHBoxLayout()
        self.music_btn = QPushButton("Music")
        self.sfx_btn = QPushButton("SFX")
        for btn in (self.music_btn, self.sfx_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            type_row.addWidget(btn)
        self.music_btn.setChecked(True)
        self.music_btn.clicked.connect(lambda: self._set_type("music"))
        self.sfx_btn.clicked.connect(lambda: self._set_type("sfx"))
        self._style_type_btns()
        self.editor_layout.addLayout(type_row)

        # Info
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        self.editor_layout.addWidget(self.info_label)

    def _set_type(self, t: str):
        self.music_btn.setChecked(t == "music")
        self.sfx_btn.setChecked(t == "sfx")
        self._style_type_btns()
        self._emit_change()

    def _style_type_btns(self):
        for btn, key in ((self.music_btn, "music"), (self.sfx_btn, "sfx")):
            c = AUDIO_COLORS[key]
            if btn.isChecked():
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {c}22; color: {c};
                    border: 1px solid {c}; border-radius: 4px; font-weight: 600; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {SURF2}; color: {DIM};
                    border: 1px solid {BORDER}; border-radius: 4px; }}
                    QPushButton:hover {{ color: {TEXT}; }}
                """)

    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio", "",
            "Audio (*.ogg *.wav *.mp3);;All Files (*)"
        )
        if not path:
            return
        p = Path(path)
        
        # Copy to project folder if set
        final_path = path
        if self._project and self._project.project_folder:
            filename = import_asset_to_project(path, self._project.project_folder)
            if filename:
                final_path = str(Path(self._project.project_folder) / filename)
        
        self.path_edit.setText(final_path)
        if not self.name_edit.text():
            self.name_edit.setText(p.stem)
        self.info_label.setText(f"{p.suffix.upper()}  •  {p.name}")
        self._emit_change()

    def _load_item(self, item: RegisteredAudio):
        self.name_edit.setText(item.name)
        self.path_edit.setText(item.path or "")
        self._set_type(item.audio_type)
        if item.path:
            self.info_label.setText(Path(item.path).name)

    def _save_item(self, item: RegisteredAudio):
        item.name = self.name_edit.text().strip() or "Unnamed"
        item.path = self.path_edit.text() or None
        item.audio_type = "music" if self.music_btn.isChecked() else "sfx"


# ─────────────────────────────────────────────────────────────
#  FONT REGISTRY
# ─────────────────────────────────────────────────────────────

class FontRegistryPanel(RegistryPanel):
    def _item_label(self, item: RegisteredFont) -> str:
        return item.name or "Unnamed"

    def _item_color(self, item) -> str:
        return "#c084fc"

    def _new_item(self) -> RegisteredFont:
        return RegisteredFont(name="font_body")

    def _build_editor(self):
        self.editor_layout.addWidget(_section("FONT ASSET"))
        self.editor_layout.addWidget(_divider())

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("File path…")
        self.path_edit.setReadOnly(True)
        self.path_edit.setStyleSheet(_field_style())
        browse_btn = _btn("Browse…", small=True)
        browse_btn.clicked.connect(self._browse_font)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        self.editor_layout.addLayout(path_row)

        self.editor_layout.addWidget(_section("LOGICAL NAME"))
        hint = QLabel("Used in Lua as a variable name (e.g. font_body, font_title).\nKeep it lowercase with underscores.")
        hint.setStyleSheet(f"color: {DIM}; font-size: 11px; line-height: 1.5;")
        hint.setWordWrap(True)
        self.editor_layout.addWidget(hint)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("font_body")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit_change)
        self.editor_layout.addWidget(self.name_edit)

        self.preview_label = QLabel("The quick brown fox…")
        self.preview_label.setStyleSheet(f"""
            background: {SURFACE}; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 4px;
            padding: 12px; font-size: 16px;
        """)
        self.editor_layout.addWidget(self.preview_label)

    def _browse_font(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Font", "",
            "Fonts (*.ttf *.otf);;All Files (*)"
        )
        if not path:
            return
        p = Path(path)
        
        # Copy to project folder if set
        final_path = path
        if self._project and self._project.project_folder:
            filename = import_asset_to_project(path, self._project.project_folder)
            if filename:
                final_path = str(Path(self._project.project_folder) / filename)
        
        self.path_edit.setText(final_path)
        if not self.name_edit.text():
            self.name_edit.setText(p.stem.lower().replace(" ", "_").replace("-", "_"))
        self._emit_change()

    def _load_item(self, item: RegisteredFont):
        self.name_edit.setText(item.name)
        self.path_edit.setText(item.path or "")

    def _save_item(self, item: RegisteredFont):
        item.name = self.name_edit.text().strip() or "font_unnamed"
        item.path = self.path_edit.text() or None


# ─────────────────────────────────────────────────────────────
#  VARIABLES PANEL
# ─────────────────────────────────────────────────────────────

class VariablesPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._variables: list[GameVariable] = []
        self._current = -1
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left ─────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        self.var_list = QListWidget()
        self.var_list.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURF2}; }}
        """)
        self.var_list.currentRowChanged.connect(self._on_select)
        lv.addWidget(self.var_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        for label, slot, kw in [
            ("+ Number", lambda: self._add("number"), {"accent": True}),
            ("+ String", lambda: self._add("string"), {}),
            ("+ Bool",   lambda: self._add("bool"),   {}),
        ]:
            b = _btn(label, small=True, **kw)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        lv.addLayout(btn_row)

        del_row = QHBoxLayout()
        self.del_btn = _btn("x Delete", danger=True, small=True)
        self.del_btn.clicked.connect(self._delete)
        del_row.addWidget(self.del_btn)
        del_row.addStretch()
        lv.addLayout(del_row)
        root.addWidget(left)

        # ── Right editor ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        rw = QWidget()
        rw.setStyleSheet(f"background: {DARK};")
        self.rl = QVBoxLayout(rw)
        self.rl.setContentsMargins(20, 16, 20, 20)
        self.rl.setSpacing(8)

        self.rl.addWidget(_section("VARIABLE"))
        self.rl.addWidget(_divider())

        # Type badge row
        type_row = QHBoxLayout()
        self.type_badge = QLabel("NUMBER")
        self.type_badge.setStyleSheet(f"color: {VAR_COLORS['number']}; font-size: 11px; font-weight: 700;")
        type_row.addWidget(self.type_badge)
        type_row.addStretch()
        self.rl.addLayout(type_row)

        self.rl.addWidget(_section("VARIABLE NAME"))
        name_hint = QLabel("Used in behaviors and Lua. Lowercase, no spaces.")
        name_hint.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        self.rl.addWidget(name_hint)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("my_variable")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit)
        self.rl.addWidget(self.name_edit)

        self.rl.addWidget(_section("DEFAULT VALUE"))
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("0")
        self.value_edit.setStyleSheet(_field_style())
        self.value_edit.textChanged.connect(self._emit)
        self.rl.addWidget(self.value_edit)

        # Bool shortcut
        self.bool_row = QWidget()
        bl = QHBoxLayout(self.bool_row)
        bl.setContentsMargins(0, 0, 0, 0)
        true_btn = _btn("true", small=True)
        false_btn = _btn("false", small=True)
        true_btn.clicked.connect(lambda: self.value_edit.setText("true"))
        false_btn.clicked.connect(lambda: self.value_edit.setText("false"))
        bl.addWidget(true_btn)
        bl.addWidget(false_btn)
        bl.addStretch()
        self.bool_row.hide()
        self.rl.addWidget(self.bool_row)

        self.rl.addWidget(_section("DESCRIPTION (optional)"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("What does this variable track?")
        self.desc_edit.setStyleSheet(_field_style())
        self.desc_edit.textChanged.connect(self._emit)
        self.rl.addWidget(self.desc_edit)

        self.rl.addStretch()
        scroll.setWidget(rw)
        root.addWidget(scroll, stretch=1)

        rw.setEnabled(False)
        self._editor_widget = rw

    def _add(self, var_type: str):
        v = GameVariable(name=f"new_{var_type}", var_type=var_type,
                         default_value="false" if var_type == "bool" else ("" if var_type == "string" else 0))
        self._variables.append(v)
        self._refresh_list()
        self.var_list.setCurrentRow(len(self._variables) - 1)
        self.changed.emit()

    def _delete(self):
        row = self.var_list.currentRow()
        if 0 <= row < len(self._variables):
            self._variables.pop(row)
            self._refresh_list()
            new = min(row, len(self._variables) - 1)
            if new >= 0:
                self.var_list.setCurrentRow(new)
            else:
                self._current = -1
                self._editor_widget.setEnabled(False)
            self.changed.emit()

    def _refresh_list(self):
        self.var_list.blockSignals(True)
        self.var_list.clear()
        for v in self._variables:
            c = VAR_COLORS.get(v.var_type, TEXT)
            label = f"[{v.var_type[:3].upper()}]  {v.name}"
            item = QListWidgetItem(label)
            item.setForeground(QColor(c))
            self.var_list.addItem(item)
        self.var_list.blockSignals(False)

    def _on_select(self, row: int):
        if self._suppress:
            return
        if 0 <= row < len(self._variables):
            self._current = row
            v = self._variables[row]
            self._suppress = True
            self.name_edit.setText(v.name)
            self.value_edit.setText(str(v.default_value))
            self.desc_edit.setText(getattr(v, "description", ""))
            c = VAR_COLORS.get(v.var_type, TEXT)
            self.type_badge.setText(v.var_type.upper())
            self.type_badge.setStyleSheet(f"color: {c}; font-size: 11px; font-weight: 700;")
            self.bool_row.setVisible(v.var_type == "bool")
            self._suppress = False
            self._editor_widget.setEnabled(True)

    def _emit(self):
        if self._suppress or self._current < 0:
            return
        v = self._variables[self._current]
        v.name = self.name_edit.text().strip() or "unnamed"
        raw = self.value_edit.text().strip()
        if v.var_type == "number":
            try:
                v.default_value = float(raw) if "." in raw else int(raw)
            except ValueError:
                v.default_value = 0
        elif v.var_type == "bool":
            v.default_value = raw.lower() in ("true", "1", "yes")
        else:
            v.default_value = raw
        self._refresh_list()
        self.changed.emit()

    def load_variables(self, variables: list[GameVariable]):
        self._variables = variables
        self._refresh_list()
        if self._variables:
            self.var_list.setCurrentRow(0)
        else:
            self._current = -1
            self._editor_widget.setEnabled(False)


# ─────────────────────────────────────────────────────────────
#  INVENTORY PANEL
# ─────────────────────────────────────────────────────────────

class InventoryPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[InventoryItem] = []
        self._images: list[RegisteredImage] = []
        self._current = -1
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left list ────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        self.item_list = QListWidget()
        self.item_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURF2}; }}
        """)
        self.item_list.currentRowChanged.connect(self._on_select)
        lv.addWidget(self.item_list)

        btns = QHBoxLayout()
        btns.setSpacing(4)
        add_btn = _btn("+ Add Item", accent=True, small=True)
        add_btn.clicked.connect(self._add)
        del_btn = _btn("x", danger=True, small=True)
        del_btn.setFixedWidth(32)
        del_btn.clicked.connect(self._delete)
        btns.addWidget(add_btn)
        btns.addWidget(del_btn)
        lv.addLayout(btns)
        root.addWidget(left)

        # ── Right editor ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        rw = QWidget()
        rw.setStyleSheet(f"background: {DARK};")
        self.rl = QVBoxLayout(rw)
        self.rl.setContentsMargins(20, 16, 20, 20)
        self.rl.setSpacing(8)

        self.rl.addWidget(_section("INVENTORY ITEM"))
        self.rl.addWidget(_divider())

        # Icon thumbnail
        self.icon_thumb = QLabel()
        self.icon_thumb.setFixedSize(80, 80)
        self.icon_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_thumb.setStyleSheet(f"""
            background: {SURFACE}; border: 1px solid {BORDER};
            border-radius: 4px; color: {DIM}; font-size: 10px;
        """)
        self.icon_thumb.setText("No icon")
        self.rl.addWidget(self.icon_thumb)

        self.rl.addWidget(_section("ITEM NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Key, Coin, Letter…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit)
        self.rl.addWidget(self.name_edit)

        self.rl.addWidget(_section("DESCRIPTION"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Displayed when player inspects this item…")
        self.desc_edit.setFixedHeight(70)
        self.desc_edit.setStyleSheet(_field_style())
        self.desc_edit.textChanged.connect(self._emit)
        self.rl.addWidget(self.desc_edit)

        self.rl.addWidget(_section("ICON IMAGE"))
        icon_row = QHBoxLayout()
        self.icon_combo = QComboBox()
        self.icon_combo.setStyleSheet(_field_style())
        self.icon_combo.currentIndexChanged.connect(self._on_icon_change)
        icon_row.addWidget(self.icon_combo)
        self.rl.addLayout(icon_row)

        self.rl.addStretch()
        scroll.setWidget(rw)
        root.addWidget(scroll, stretch=1)

        rw.setEnabled(False)
        self._editor_widget = rw

    def _add(self):
        item = InventoryItem(name="New Item")
        self._items.append(item)
        self._refresh_list()
        self.item_list.setCurrentRow(len(self._items) - 1)
        self.changed.emit()

    def _delete(self):
        row = self.item_list.currentRow()
        if 0 <= row < len(self._items):
            self._items.pop(row)
            self._refresh_list()
            new = min(row, len(self._items) - 1)
            if new >= 0:
                self.item_list.setCurrentRow(new)
            else:
                self._current = -1
                self._editor_widget.setEnabled(False)
            self.changed.emit()

    def _refresh_list(self):
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for item in self._items:
            self.item_list.addItem(item.name or "Unnamed")
        self.item_list.blockSignals(False)

    def _on_select(self, row: int):
        if self._suppress:
            return
        if 0 <= row < len(self._items):
            self._current = row
            item = self._items[row]
            self._suppress = True
            self.name_edit.setText(item.name)
            self.desc_edit.setPlainText(item.description)
            # Set icon combo
            self._refresh_icon_combo()
            if item.icon_id:
                for i in range(self.icon_combo.count()):
                    if self.icon_combo.itemData(i) == item.icon_id:
                        self.icon_combo.setCurrentIndex(i)
                        break
            self._update_icon_thumb()
            self._suppress = False
            self._editor_widget.setEnabled(True)

    def _refresh_icon_combo(self):
        self.icon_combo.blockSignals(True)
        self.icon_combo.clear()
        self.icon_combo.addItem("— none —", None)
        for img in self._images:
            self.icon_combo.addItem(img.name, img.id)
        self.icon_combo.blockSignals(False)

    def _on_icon_change(self):
        if not self._suppress:
            self._update_icon_thumb()
            self._emit()

    def _update_icon_thumb(self):
        icon_id = self.icon_combo.currentData()
        if icon_id:
            img = next((i for i in self._images if i.id == icon_id), None)
            if img and img.path:
                px = QPixmap(img.path)
                if not px.isNull():
                    self.icon_thumb.setPixmap(
                        px.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
                    return
        self.icon_thumb.setPixmap(QPixmap())
        self.icon_thumb.setText("No icon")

    def _emit(self):
        if self._suppress or self._current < 0:
            return
        item = self._items[self._current]
        item.name = self.name_edit.text().strip() or "Unnamed"
        item.description = self.desc_edit.toPlainText()
        item.icon_id = self.icon_combo.currentData()
        self._refresh_list()
        self.changed.emit()

    def load_data(self, items: list[InventoryItem], images: list[RegisteredImage]):
        self._items = items
        self._images = images
        self._refresh_list()
        if self._items:
            self.item_list.setCurrentRow(0)
        else:
            self._current = -1
            self._editor_widget.setEnabled(False)

    def update_images(self, images: list[RegisteredImage]):
        self._images = images
        if self._current >= 0:
            self._refresh_icon_combo()


# ─────────────────────────────────────────────────────────────
#  INPUT PANEL
# ─────────────────────────────────────────────────────────────

class InputPanel(RegistryPanel):
    def _item_label(self, item: InputAction) -> str:
        event = item.event.upper()
        if item.event == "hold_for":
            dur = getattr(item, "hold_duration", 2.0)
            return f"[HOLD {dur}s]  {item.button}  →  {item.name}"
        return f"[{event}]  {item.button}  →  {item.name}"

    def _item_color(self, item: InputAction) -> str:
        return INPUT_COLORS.get(item.event, TEXT)

    def _new_item(self) -> InputAction:
        return InputAction(name="action", button="cross", event="pressed")

    def _build_editor(self):
        self.editor_layout.addWidget(_section("INPUT ACTION"))
        self.editor_layout.addWidget(_divider())

        # Action name
        self.editor_layout.addWidget(_section("ACTION NAME"))
        hint = QLabel("lowercase, underscores only, no leading digit, max 32 chars\ne.g.  jump   walk_left   open_menu")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        self.editor_layout.addWidget(hint)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. jump")
        self.name_edit.setMaxLength(32)
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.editor_layout.addWidget(self.name_edit)

        self.name_error = QLabel("")
        self.name_error.setStyleSheet(f"color: {DANGER}; font-size: 11px;")
        self.editor_layout.addWidget(self.name_error)

        # Button
        self.editor_layout.addWidget(_section("BUTTON"))
        self.button_combo = QComboBox()
        self.button_combo.addItems(INPUT_BUTTONS)
        self.button_combo.setStyleSheet(_field_style())
        self.button_combo.currentTextChanged.connect(self._emit_change)
        self.editor_layout.addWidget(self.button_combo)

        # Event
        self.editor_layout.addWidget(_section("EVENT"))
        event_row = QHBoxLayout()
        self._event_btns = {}
        for ev in INPUT_EVENTS:
            label = "Hold for…" if ev == "hold_for" else ev.capitalize()
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {SURF2}; color: {DIM};
                    border: 1px solid {BORDER}; border-radius: 4px;
                    font-size: 12px; padding: 0 10px;
                }}
                QPushButton:checked {{
                    background: {INPUT_COLORS[ev]}; color: {DARK};
                    border-color: {INPUT_COLORS[ev]}; font-weight: 600;
                }}
                QPushButton:hover:!checked {{ background: {SURF2}; color: {TEXT}; }}
            """)
            btn.clicked.connect(lambda checked, e=ev: self._set_event(e))
            event_row.addWidget(btn)
            self._event_btns[ev] = btn
        self.editor_layout.addLayout(event_row)

        # Hold duration row (shown only when event == "hold_for")
        self._hold_row_widget = QWidget()
        hold_row = QHBoxLayout(self._hold_row_widget)
        hold_row.setContentsMargins(0, 4, 0, 0)
        hold_lbl = QLabel("Hold duration (seconds):")
        hold_lbl.setStyleSheet(f"color: {DIM}; font-size: 11px; background: transparent;")
        hold_row.addWidget(hold_lbl)
        self.hold_duration_spin = QDoubleSpinBox()
        self.hold_duration_spin.setRange(0.1, 30.0)
        self.hold_duration_spin.setSingleStep(0.1)
        self.hold_duration_spin.setDecimals(1)
        self.hold_duration_spin.setValue(2.0)
        self.hold_duration_spin.setFixedWidth(80)
        self.hold_duration_spin.setStyleSheet(_field_style())
        self.hold_duration_spin.valueChanged.connect(self._emit_change)
        hold_row.addWidget(self.hold_duration_spin)
        hold_row.addStretch()
        self._hold_row_widget.setVisible(False)
        self.editor_layout.addWidget(self._hold_row_widget)

    def _on_name_changed(self):
        text = self.name_edit.text()
        if not text:
            self.name_error.setText("")
        elif not _ACTION_NAME_RE.match(text):
            if text[0].isdigit():
                self.name_error.setText("✕  Cannot start with a digit")
            elif text != text.lower():
                self.name_error.setText("✕  Must be lowercase")
            elif ' ' in text:
                self.name_error.setText("✕  No spaces — use underscores")
            else:
                self.name_error.setText("✕  Only letters, digits, underscores allowed")
        else:
            self.name_error.setText("")
        self._emit_change()

    def _set_event(self, event: str):
        for ev, btn in self._event_btns.items():
            btn.setChecked(ev == event)
        self._hold_row_widget.setVisible(event == "hold_for")
        self._emit_change()

    def _load_item(self, item: InputAction):
        self.name_edit.setText(item.name)
        idx = self.button_combo.findText(item.button)
        if idx >= 0:
            self.button_combo.setCurrentIndex(idx)
        for ev, btn in self._event_btns.items():
            btn.setChecked(ev == item.event)
        dur = getattr(item, "hold_duration", 2.0)
        self.hold_duration_spin.setValue(float(dur))
        self._hold_row_widget.setVisible(item.event == "hold_for")

    def _save_item(self, item: InputAction):
        raw = self.name_edit.text().strip()
        if _ACTION_NAME_RE.match(raw):
            item.name = raw
        item.button = self.button_combo.currentText()
        item.event = next((ev for ev, btn in self._event_btns.items() if btn.isChecked()), "pressed")
        item.hold_duration = self.hold_duration_spin.value()


# ─────────────────────────────────────────────────────────────
#  PROJECT SETTINGS PANEL
# ─────────────────────────────────────────────────────────────

class ProjectSettingsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        rw = QWidget()
        rw.setStyleSheet(f"background: {DARK};")
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(24, 16, 24, 24)
        rl.setSpacing(8)

        rl.addWidget(_section("PROJECT IDENTITY"))
        rl.addWidget(_divider())

        rl.addWidget(QLabel("Game Title"))
        self.title_edit = QLineEdit()
        self.title_edit.setStyleSheet(_field_style())
        self.title_edit.textChanged.connect(self._emit)
        rl.addWidget(self.title_edit)

        rl.addWidget(QLabel("Title ID"))
        id_hint = QLabel("Format: 4 letters + 5 digits  (e.g. ADVG00001).\nMust be unique to install alongside other games.")
        id_hint.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        id_hint.setWordWrap(True)
        rl.addWidget(id_hint)
        id_row = QHBoxLayout()
        self.title_id_edit = QLineEdit()
        self.title_id_edit.setMaxLength(9)
        self.title_id_edit.setStyleSheet(_field_style())
        self.title_id_edit.textChanged.connect(self._emit)
        rand_btn = _btn("[R] Random", small=True)
        rand_btn.clicked.connect(self._randomize_id)
        id_row.addWidget(self.title_id_edit)
        id_row.addWidget(rand_btn)
        rl.addLayout(id_row)

        rl.addWidget(QLabel("Author"))
        self.author_edit = QLineEdit()
        self.author_edit.setStyleSheet(_field_style())
        self.author_edit.textChanged.connect(self._emit)
        rl.addWidget(self.author_edit)

        rl.addWidget(QLabel("Version"))
        self.version_edit = QLineEdit()
        self.version_edit.setStyleSheet(_field_style())
        self.version_edit.textChanged.connect(self._emit)
        rl.addWidget(self.version_edit)

        # ── PROJECT FOLDER ────────────────────────────────────
        rl.addSpacing(8)
        rl.addWidget(_section("PROJECT FOLDER"))
        rl.addWidget(_divider())

        folder_hint = QLabel("All assets will be copied here when added. Required for Project Explorer.")
        folder_hint.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        folder_hint.setWordWrap(True)
        rl.addWidget(folder_hint)

        self.folder_path_label = QLabel("Not set")
        self.folder_path_label.setStyleSheet(f"color: {TEXT}; font-size: 11px; padding: 6px 0;")
        self.folder_path_label.setWordWrap(True)
        rl.addWidget(self.folder_path_label)

        folder_btns = QHBoxLayout()
        folder_btns.setSpacing(6)
        create_folder_btn = _btn("Create New…", small=True)
        create_folder_btn.clicked.connect(self._create_project_folder)
        folder_btns.addWidget(create_folder_btn)
        choose_folder_btn = _btn("Choose Existing…", small=True)
        choose_folder_btn.clicked.connect(self._choose_project_folder)
        folder_btns.addWidget(choose_folder_btn)
        folder_btns.addStretch()
        rl.addLayout(folder_btns)

        rl.addSpacing(8)
        rl.addWidget(_section("SYSTEMS"))
        rl.addWidget(_divider())

        # Save system
        self.save_check = QCheckBox("Enable save system")
        self.save_check.setStyleSheet(_field_style())
        self.save_check.stateChanged.connect(self._emit)
        rl.addWidget(self.save_check)

        # Inventory
        inv_row = QHBoxLayout()
        self.inv_check = QCheckBox("Enable inventory system")
        self.inv_check.setStyleSheet(_field_style())
        self.inv_check.stateChanged.connect(self._emit)
        inv_row.addWidget(self.inv_check)
        rl.addLayout(inv_row)

        inv_max_row = QHBoxLayout()
        inv_max_lbl = QLabel("Max inventory slots:")
        inv_max_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.inv_max_spin = QSpinBox()
        self.inv_max_spin.setRange(1, 99)
        self.inv_max_spin.setValue(20)
        self.inv_max_spin.setFixedWidth(70)
        self.inv_max_spin.setStyleSheet(_field_style())
        self.inv_max_spin.valueChanged.connect(self._emit)
        inv_max_row.addWidget(inv_max_lbl)
        inv_max_row.addWidget(self.inv_max_spin)
        inv_max_row.addStretch()
        rl.addLayout(inv_max_row)

        rl.addSpacing(8)
        rl.addWidget(_section("AUDIO"))
        rl.addWidget(_divider())

        vol_row = QHBoxLayout()
        vol_lbl = QLabel("Default volume (0–100):")
        vol_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setValue(100)
        self.volume_spin.setFixedWidth(70)
        self.volume_spin.setStyleSheet(_field_style())
        self.volume_spin.valueChanged.connect(self._emit)
        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self.volume_spin)
        vol_row.addStretch()
        rl.addLayout(vol_row)

        rl.addStretch()
        scroll.setWidget(rw)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _randomize_id(self):
        import random, string
        letters = "".join(random.choices(string.ascii_uppercase, k=4))
        digits = "".join(random.choices(string.digits, k=5))
        self.title_id_edit.setText(f"{letters}{digits}")

    def _create_project_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Location for Project Folder", "",
            QFileDialog.Option.ShowDirsOnly
        )
        if not path:
            return
        project_name = self._project.title.replace(" ", "_") if self._project else "MyProject"
        folder = Path(path) / f"{project_name}_assets"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._set_project_folder(str(folder))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create folder:\n{e}")

    def _choose_project_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Project Folder", "",
            QFileDialog.Option.ShowDirsOnly
        )
        if path:
            self._set_project_folder(path)

    def _set_project_folder(self, path: str):
        if self._project:
            self._project.project_folder = path
            self.folder_path_label.setText(path)
            self.changed.emit()

    def restyle(self, c: dict):
        self._header.setStyleSheet(f"background: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};")
        # Registry panels each have left/right split with inline styles — restyle them
        for panel in (self.images_panel, self.audio_panel, self.fonts_panel, self.input_panel):
            if hasattr(panel, 'list_widget'):
                panel.list_widget.setStyleSheet(f"""
                    QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                        border-radius: 4px; color: {c['TEXT']}; outline: none; }}
                    QListWidget::item {{ padding: 8px 10px; border-radius: 3px;
                        border-bottom: 1px solid {c['BORDER']}; }}
                    QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
                    QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
                """)
            # left sidebar background
            left = panel.list_widget.parent() if hasattr(panel, 'list_widget') else None
            if left:
                left.setStyleSheet(f"background: {c['PANEL']}; border-right: 1px solid {c['BORDER']};")
            if hasattr(panel, 'editor_widget'):
                panel.editor_widget.setStyleSheet(f"background: {c['DARK']};")
        for panel in (self.vars_panel, self.inv_panel):
            if hasattr(panel, 'var_list'):
                panel.var_list.setStyleSheet(f"""
                    QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                        border-radius: 4px; color: {c['TEXT']}; outline: none; }}
                    QListWidget::item {{ padding: 8px 10px; border-radius: 3px;
                        border-bottom: 1px solid {c['BORDER']}; }}
                    QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
                    QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
                """)
            if hasattr(panel, 'item_list'):
                panel.item_list.setStyleSheet(f"""
                    QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                        border-radius: 4px; color: {c['TEXT']}; outline: none; }}
                    QListWidget::item {{ padding: 8px 10px; border-radius: 3px;
                        border-bottom: 1px solid {c['BORDER']}; }}
                    QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
                    QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
                """)

    def load_project(self, project: Project):
        self._project = project
        self._suppress = True
        self.title_edit.setText(project.title)
        self.title_id_edit.setText(project.title_id)
        self.author_edit.setText(project.author)
        self.version_edit.setText(project.version)
        self.save_check.setChecked(project.game_data.save_enabled)
        self.inv_check.setChecked(project.game_data.inventory_enabled)
        self.inv_max_spin.setValue(project.game_data.inventory_max)
        self.volume_spin.setValue(project.game_data.volume_default)
        if project.project_folder:
            self.folder_path_label.setText(project.project_folder)
        else:
            self.folder_path_label.setText("Not set")
        self._suppress = False

    def _emit(self):
        if self._suppress or self._project is None:
            return
        self._project.title = self.title_edit.text().strip() or "Untitled Game"
        self._project.title_id = self.title_id_edit.text().strip().upper()
        self._project.author = self.author_edit.text().strip()
        self._project.version = self.version_edit.text().strip() or "1.0"
        self._project.game_data.save_enabled = self.save_check.isChecked()
        self._project.game_data.inventory_enabled = self.inv_check.isChecked()
        self._project.game_data.inventory_max = self.inv_max_spin.value()
        self._project.game_data.volume_default = self.volume_spin.value()
        self.changed.emit()


# ─────────────────────────────────────────────────────────────
#  GAME DATA TAB  (assembles all panels into a sub-tabbed view)
# ─────────────────────────────────────────────────────────────

SUBTAB_STYLE = f"""
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {BORDER};
    background: {DARK};
}}
QTabBar {{
    background: {PANEL};
}}
QTabBar::tab {{
    background: {PANEL};
    color: {DIM};
    padding: 9px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 500;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background: {PANEL};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
    background: {SURF2};
}}
"""


class GameDataTab(QWidget):
    """
    The full Game Data tab.
    Exposes a .changed signal so MainWindow can mark the project dirty.
    Call .load_project(project) whenever the project changes.
    """
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Project | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        self._header = header
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("GAME DATA")
        title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        desc = QLabel("Registries, variables, and global systems — feeds every dropdown in the editor.")
        desc.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hl.addWidget(title)
        hl.addSpacing(16)
        hl.addWidget(desc)
        hl.addStretch()
        root.addWidget(header)

        # Sub-tabs
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet(SUBTAB_STYLE)
        self.sub_tabs.setTabPosition(QTabWidget.TabPosition.North)

        # Images registry
        self.images_panel = ImageRegistryPanel()
        self.images_panel.changed.connect(self._on_images_changed)
        self.sub_tabs.addTab(self.images_panel, "Images")

        # Audio registry
        self.audio_panel = AudioRegistryPanel()
        self.audio_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.audio_panel, "Audio")

        # Fonts registry
        self.fonts_panel = FontRegistryPanel()
        self.fonts_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.fonts_panel, "Fonts")

        # Variables
        self.vars_panel = VariablesPanel()
        self.vars_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.vars_panel, "Variables")

        # Inventory
        self.inv_panel = InventoryPanel()
        self.inv_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.inv_panel, "Inventory")

        # Input actions
        self.input_panel = InputPanel()
        self.input_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.input_panel, "Input")

        # Project settings
        self.settings_panel = ProjectSettingsPanel()
        self.settings_panel.changed.connect(self._on_changed)
        self.sub_tabs.addTab(self.settings_panel, "Settings")

        root.addWidget(self.sub_tabs)

    # ── Load / sync ─────────────────────────────────────────

    def load_project(self, project: Project):
        self._project = project
        self.images_panel.load_items(project.images, project)
        self.audio_panel.load_items(project.audio, project)
        self.fonts_panel.load_items(project.fonts, project)
        self.vars_panel.load_variables(project.game_data.variables)
        self.inv_panel.load_data(project.game_data.inventory_items, project.images)
        self.input_panel.load_items(project.game_data.input_actions, project)
        self.settings_panel.load_project(project)

    def _on_images_changed(self):
        # When images registry changes, update inventory icon picker too
        if self._project:
            self.inv_panel.update_images(self._project.images)
        self._on_changed()

    def _on_changed(self):
        self.changed.emit()
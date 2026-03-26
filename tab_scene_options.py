# ===== FILE: tab_scene_options.py =====

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator -- Scene Options Tab
Per-scene configuration via components. Each scene has a list of components;
selecting one reveals its config panel on the right.
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QFrame, QScrollArea, QStackedWidget,
    QSizePolicy, QDialog, QDialogButtonBox, QColorDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from models import (
    Project, Scene, SceneComponent, make_component,
    COMPONENT_TYPES, COMPONENT_DEFAULTS
)

# -- Colours -------------------------------------------------------------------
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

ROLE_COLORS = {
    "start": SUCCESS,
    "end":   DANGER,
    "":      DIM,
}

COMPONENT_COLORS = {
    "Layer":          "#38bdf8",
    "Music":          "#c084fc",
    "VNDialogBox":    "#f59e0b",
    "ChoiceMenu":     "#4ade80",
    "HUD":            "#fb923c",
    "Video":          "#f87171",
    "Transition":     "#ec4899",
    "Path":           "#06b6d4",
    "Gravity":        "#a78bfa",
    "LayerAnimation": "#34d399",
    "Grid":           "#14b8a6",
}

BUTTON_CHOICES = ["cross", "square", "circle", "triangle"]


# -- Style helpers -------------------------------------------------------------

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
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background: {SURF2}; color: {TEXT};
            border: 1px solid {BORDER};
            selection-background-color: {ACCENT};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            background: {SURF2}; border: none; width: 16px;
        }}
        QCheckBox {{
            color: {TEXT}; font-size: 12px; spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 14px; height: 14px;
            border: 1px solid {BORDER}; border-radius: 3px;
            background: {SURFACE};
        }}
        QCheckBox::indicator:checked {{
            background: {ACCENT}; border-color: {ACCENT};
        }}
    """


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(f"""
        color: {DIM}; font-size: 10px; font-weight: 700;
        letter-spacing: 1.5px; padding: 10px 0 4px 0; background: transparent;
    """)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
    return f


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
                padding: 0 10px;
                font-size: 12px; 
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #6a59ef; }}
        """)
    elif danger:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; 
                color: {DANGER};
                border: 1px solid {DANGER}; 
                border-radius: 4px;
                padding: 0 10px; 
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
                padding: 0 10px; 
                font-size: 12px;
            }}
            QPushButton:hover {{ 
                background-color: {ACCENT}; 
                border-color: {ACCENT}; 
                color: white; 
            }}
        """)
    return b


def _dim(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {DIM}; font-size: 12px; background: transparent;")
    return lbl


# ─────────────────────────────────────────────────────────────
#  ADD COMPONENT DIALOG
# ─────────────────────────────────────────────────────────────

class AddComponentDialog(QDialog):
    def __init__(self, existing_types: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Component")
        self.setModal(True)
        self.setMinimumWidth(300)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl = QLabel("Choose a component to add:")
        lbl.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        layout.addWidget(lbl)

        # Singletons: Background, Foreground, Music, HUD, Video, VNDialogBox, ChoiceMenu
        # "Layer" is NOT a singleton — multiple are allowed
        MULTI_ALLOWED = {"Layer", "TileLayer", "CollisionLayer", "Path", "LayerAnimation", "Grid"}
        available = [t for t in COMPONENT_TYPES if t in MULTI_ALLOWED or t not in existing_types]

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURF2}; }}
        """)
        for t in available:
            item = QListWidgetItem(t)
            color = COMPONENT_COLORS.get(t, DIM)
            item.setForeground(QColor(color))
            self.list_widget.addItem(item)
        self.list_widget.doubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"color: {TEXT};")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_type(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.text() if item else None


# ─────────────────────────────────────────────────────────────
#  COMPONENT CONFIG PANELS  (one per component type)
# ─────────────────────────────────────────────────────────────

class LayerConfigPanel(QWidget):
    """Config panel for the multi-instance Layer component."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Name ──────────────────────────────────────────────
        layout.addWidget(_section("LAYER NAME"))
        hint = QLabel("Used by layer actions (Show Layer, Hide Layer, etc.)")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. HUD, Overlay, Sky…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit)
        layout.addWidget(self.name_edit)

        # ── Layer number ──────────────────────────────────────
        layout.addWidget(_section("LAYER"))
        order_hint = QLabel("0 = furthest back. Higher numbers draw closer to the camera.")
        order_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        order_hint.setWordWrap(True)
        layout.addWidget(order_hint)
        order_row = QHBoxLayout()
        order_row.setSpacing(8)
        self.order_spin = QSpinBox()
        self.order_spin.setRange(0, 99)
        self.order_spin.setValue(0)
        self.order_spin.setFixedWidth(80)
        self.order_spin.setStyleSheet(_field_style())
        self.order_spin.valueChanged.connect(self._emit)
        order_row.addWidget(self.order_spin)
        order_row.addStretch()
        layout.addLayout(order_row)

        # ── Image ─────────────────────────────────────────────
        layout.addWidget(_section("IMAGE"))
        self.image_combo = QComboBox()
        self.image_combo.setStyleSheet(_field_style())
        self.image_combo.currentIndexChanged.connect(self._on_image_changed)
        layout.addWidget(self.image_combo)

        # ── Visible at start ──────────────────────────────────
        self.visible_check = QCheckBox("Visible at scene start")
        self.visible_check.setChecked(True)
        self.visible_check.setStyleSheet(_field_style())
        self.visible_check.stateChanged.connect(self._emit)
        layout.addWidget(self.visible_check)

        # ── Screen-space lock ─────────────────────────────────
        self.ss_check = QCheckBox("Screen-space locked (ignore camera / shake)")
        self.ss_check.setStyleSheet(_field_style())
        self.ss_check.stateChanged.connect(self._emit)
        layout.addWidget(self.ss_check)
        ss_hint = QLabel("Enable this for HUD or GUI overlays that should not scroll with the camera.")
        ss_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        ss_hint.setWordWrap(True)
        layout.addWidget(ss_hint)

        # ── Scroll ────────────────────────────────────────────
        self._scroll_group = QWidget()
        sg = QVBoxLayout(self._scroll_group)
        sg.setContentsMargins(0, 4, 0, 0)
        sg.setSpacing(4)

        self.scroll_check = QCheckBox("Enable scrolling")
        self.scroll_check.setStyleSheet(_field_style())
        self.scroll_check.stateChanged.connect(self._on_scroll_toggle)
        sg.addWidget(self.scroll_check)

        self._scroll_params = QWidget()
        sp = QHBoxLayout(self._scroll_params)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.setSpacing(8)
        sp.addWidget(_dim("Speed (px/frame):"))
        self.scroll_speed = QSpinBox()
        self.scroll_speed.setRange(1, 60)
        self.scroll_speed.setValue(1)
        self.scroll_speed.setFixedWidth(70)
        self.scroll_speed.setStyleSheet(_field_style())
        self.scroll_speed.valueChanged.connect(self._emit)
        sp.addWidget(self.scroll_speed)
        sp.addWidget(_dim("Direction:"))
        self.scroll_dir = QComboBox()
        self.scroll_dir.addItems(["horizontal", "vertical"])
        self.scroll_dir.setStyleSheet(_field_style())
        self.scroll_dir.currentIndexChanged.connect(self._emit)
        sp.addWidget(self.scroll_dir)
        sp.addStretch()
        self._scroll_params.setVisible(False)
        sg.addWidget(self._scroll_params)

        self._scroll_group.setVisible(False)
        layout.addWidget(self._scroll_group)

        # ── Parallax ──────────────────────────────────────────
        self._parallax_row = QWidget()
        pr = QHBoxLayout(self._parallax_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(8)
        pr.addWidget(_dim("Parallax (0=fixed, 1=full):"))
        self.parallax_spin = QDoubleSpinBox()
        self.parallax_spin.setRange(0.0, 1.0)
        self.parallax_spin.setSingleStep(0.1)
        self.parallax_spin.setValue(1.0)
        self.parallax_spin.setFixedWidth(70)
        self.parallax_spin.setStyleSheet(_field_style())
        self.parallax_spin.valueChanged.connect(self._emit)
        pr.addWidget(self.parallax_spin)
        pr.addStretch()
        self._parallax_row.setVisible(False)
        layout.addWidget(self._parallax_row)

        # ── Tiling ────────────────────────────────────────────
        layout.addWidget(_section("TILING"))
        tile_hint = QLabel("Repeat the image to fill the screen. Pairs with scrolling for seamless looping backgrounds.")
        tile_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        tile_hint.setWordWrap(True)
        layout.addWidget(tile_hint)
        self.tile_x_check = QCheckBox("Tile horizontally")
        self.tile_x_check.setStyleSheet(_field_style())
        self.tile_x_check.stateChanged.connect(self._emit)
        layout.addWidget(self.tile_x_check)
        self.tile_y_check = QCheckBox("Tile vertically")
        self.tile_y_check.setStyleSheet(_field_style())
        self.tile_y_check.stateChanged.connect(self._emit)
        layout.addWidget(self.tile_y_check)

        layout.addStretch()

    def _on_image_changed(self):
        has_img = self.image_combo.currentData() is not None
        self._scroll_group.setVisible(has_img)
        self._parallax_row.setVisible(has_img and not self.ss_check.isChecked())
        self._emit()

    def _on_scroll_toggle(self, state):
        self._scroll_params.setVisible(bool(state))
        self._emit()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        cfg = self._component.config
        cfg["layer_name"]          = self.name_edit.text()
        cfg["layer"]               = self.order_spin.value()
        cfg["image_id"]            = self.image_combo.currentData()
        cfg["visible"]             = self.visible_check.isChecked()
        cfg["screen_space_locked"] = self.ss_check.isChecked()
        cfg["scroll"]              = self.scroll_check.isChecked()
        cfg["scroll_speed"]        = self.scroll_speed.value()
        cfg["scroll_direction"]    = self.scroll_dir.currentText()
        cfg["parallax"]            = self.parallax_spin.value()
        cfg["tile_x"]              = self.tile_x_check.isChecked()
        cfg["tile_y"]              = self.tile_y_check.isChecked()
        # Hide parallax when screen-space locked (it's meaningless)
        has_img = cfg["image_id"] is not None
        self._parallax_row.setVisible(has_img and not cfg["screen_space_locked"])
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config

        self.name_edit.setText(cfg.get("layer_name", "New Layer"))
        self.order_spin.setValue(cfg.get("layer", 0))

        self.image_combo.blockSignals(True)
        self.image_combo.clear()
        self.image_combo.addItem("-- none --", None)
        for img in project.images:
            self.image_combo.addItem(img.name, img.id)
        img_id = cfg.get("image_id")
        if img_id:
            for i in range(self.image_combo.count()):
                if self.image_combo.itemData(i) == img_id:
                    self.image_combo.setCurrentIndex(i)
                    break
        self.image_combo.blockSignals(False)

        self.visible_check.setChecked(cfg.get("visible", True))
        self.ss_check.setChecked(cfg.get("screen_space_locked", False))

        has_img = cfg.get("image_id") is not None
        self._scroll_group.setVisible(has_img)
        self.scroll_check.setChecked(cfg.get("scroll", False))
        self.scroll_speed.setValue(cfg.get("scroll_speed", 1))
        idx = self.scroll_dir.findText(cfg.get("scroll_direction", "horizontal"))
        if idx >= 0:
            self.scroll_dir.setCurrentIndex(idx)
        self._scroll_params.setVisible(cfg.get("scroll", False))

        self.parallax_spin.setValue(cfg.get("parallax", 1.0))
        self._parallax_row.setVisible(has_img and not cfg.get("screen_space_locked", False))

        self.tile_x_check.setChecked(cfg.get("tile_x", False))
        self.tile_y_check.setChecked(cfg.get("tile_y", False))

        self._suppress = False


class MusicConfigPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_section("ACTION"))
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self._action_btns: dict[str, QPushButton] = {}
        for opt in ["keep", "change", "stop"]:
            btn = QPushButton(opt.upper())
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {SURF2}; color: {DIM};
                    border: 1px solid {BORDER}; border-radius: 4px;
                    padding: 0 12px; font-size: 11px; font-weight: 600;
                }}
                QPushButton:checked {{
                    background: {ACCENT}22; color: {ACCENT};
                    border: 1px solid {ACCENT};
                }}
                QPushButton:hover:!checked {{ color: {TEXT}; }}
            """)
            btn.clicked.connect(lambda checked, o=opt: self._on_action(o))
            self._action_btns[opt] = btn
            action_row.addWidget(btn)
        action_row.addStretch()
        self._action_btns["keep"].setChecked(True)
        layout.addLayout(action_row)

        self._track_row = QWidget()
        tr = QVBoxLayout(self._track_row)
        tr.setContentsMargins(0, 4, 0, 0)
        tr.setSpacing(4)
        tr.addWidget(_dim("Track:"))
        self.track_combo = QComboBox()
        self.track_combo.setStyleSheet(_field_style())
        self.track_combo.currentIndexChanged.connect(self._emit)
        tr.addWidget(self.track_combo)
        self._track_row.setVisible(False)
        layout.addWidget(self._track_row)
        layout.addStretch()

    def _on_action(self, action: str):
        for opt, btn in self._action_btns.items():
            btn.setChecked(opt == action)
        self._track_row.setVisible(action == "change")
        self._emit()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        action = next((k for k, b in self._action_btns.items() if b.isChecked()), "keep")
        self._component.config["action"] = action
        self._component.config["audio_id"] = self.track_combo.currentData() if action == "change" else None
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config

        action = cfg.get("action", "keep")
        for opt, btn in self._action_btns.items():
            btn.setChecked(opt == action)
        self._track_row.setVisible(action == "change")

        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        self.track_combo.addItem("-- none --", None)
        for aud in project.audio:
            if aud.audio_type == "music":
                self.track_combo.addItem(aud.name, aud.id)
        current_id = cfg.get("audio_id")
        if current_id:
            for i in range(self.track_combo.count()):
                if self.track_combo.itemData(i) == current_id:
                    self.track_combo.setCurrentIndex(i)
                    break
        self.track_combo.blockSignals(False)
        self._suppress = False


class _DialogPageCard(QFrame):
    """One card in the dialog page list: character name, 4 lines, advance toggle, delete."""
    changed = Signal()
    delete_requested = Signal(object)   # emits self

    def __init__(self, page_index: int = 0, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.setStyleSheet(f"""
            _DialogPageCard {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 6px;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(4)

        # ── Header row: page label + delete button ───────────
        header = QHBoxLayout()
        header.setSpacing(6)
        self._page_label = QLabel(f"Page {self.page_index + 1}")
        self._page_label.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: 700; background: transparent; border: none;")
        header.addWidget(self._page_label)
        header.addStretch()
        del_btn = QPushButton("×")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {DIM}; border: none;
                font-size: 16px; font-weight: 700;
            }}
            QPushButton:hover {{ color: {DANGER}; }}
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        header.addWidget(del_btn)
        layout.addLayout(header)

        # ── Character name ───────────────────────────────────
        self.character_edit = QLineEdit()
        self.character_edit.setPlaceholderText("Character name (optional)…")
        self.character_edit.setStyleSheet(_field_style())
        self.character_edit.textChanged.connect(self.changed.emit)
        layout.addWidget(self.character_edit)

        # ── 4 dialogue lines ────────────────────────────────
        self.line_edits: list[QLineEdit] = []
        for i in range(4):
            edit = QLineEdit()
            edit.setPlaceholderText(f"Line {i + 1}…")
            edit.setStyleSheet(_field_style())
            edit.textChanged.connect(self.changed.emit)
            layout.addWidget(edit)
            self.line_edits.append(edit)

        # ── Advance to next scene toggle ─────────────────────
        self.advance_check = QCheckBox("Advance to next scene after this page")
        self.advance_check.setStyleSheet(_field_style())
        self.advance_check.stateChanged.connect(self.changed.emit)
        layout.addWidget(self.advance_check)

        # ── Typewriter effect ────────────────────────────────
        tw_row = QHBoxLayout()
        tw_row.setSpacing(6)
        self.typewriter_check = QCheckBox("Typewriter effect")
        self.typewriter_check.setStyleSheet(_field_style())
        self.typewriter_check.stateChanged.connect(self._on_tw_toggled)
        tw_row.addWidget(self.typewriter_check)
        tw_speed_lbl = QLabel("chars/sec:")
        tw_speed_lbl.setStyleSheet(f"color: {DIM}; font-size: 11px; background: transparent; border: none;")
        tw_row.addWidget(tw_speed_lbl)
        self.typewriter_speed_spin = QSpinBox()
        self.typewriter_speed_spin.setRange(5, 120)
        self.typewriter_speed_spin.setValue(30)
        self.typewriter_speed_spin.setFixedWidth(60)
        self.typewriter_speed_spin.setStyleSheet(_field_style())
        self.typewriter_speed_spin.setEnabled(False)
        self.typewriter_speed_spin.valueChanged.connect(self.changed.emit)
        tw_row.addWidget(self.typewriter_speed_spin)
        tw_row.addStretch()
        layout.addLayout(tw_row)

    def _on_tw_toggled(self):
        self.typewriter_speed_spin.setEnabled(self.typewriter_check.isChecked())
        self.changed.emit()

    def set_page_index(self, idx: int):
        self.page_index = idx
        self._page_label.setText(f"Page {idx + 1}")

    def get_data(self) -> dict:
        return {
            "character": self.character_edit.text(),
            "lines": [e.text() for e in self.line_edits],
            "advance_to_next": self.advance_check.isChecked(),
            "typewriter": self.typewriter_check.isChecked(),
            "typewriter_speed": self.typewriter_speed_spin.value(),
        }

    def set_data(self, d: dict):
        self.character_edit.blockSignals(True)
        self.character_edit.setText(d.get("character", ""))
        self.character_edit.blockSignals(False)
        lines = d.get("lines", ["", "", "", ""])
        lines = (lines + ["", "", "", ""])[:4]
        for i, edit in enumerate(self.line_edits):
            edit.blockSignals(True)
            edit.setText(lines[i])
            edit.blockSignals(False)
        self.advance_check.blockSignals(True)
        self.advance_check.setChecked(d.get("advance_to_next", False))
        self.advance_check.blockSignals(False)
        self.typewriter_check.blockSignals(True)
        self.typewriter_check.setChecked(d.get("typewriter", False))
        self.typewriter_check.blockSignals(False)
        self.typewriter_speed_spin.blockSignals(True)
        self.typewriter_speed_spin.setValue(d.get("typewriter_speed", 30))
        self.typewriter_speed_spin.blockSignals(False)
        self.typewriter_speed_spin.setEnabled(self.typewriter_check.isChecked())


class VNDialogBoxConfigPanel(QWidget):
    changed = Signal()

    BOX_W = 880
    BOX_H = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._fill_color = "#000000"
        self._border_color = "#ffffff"
        self._text_color = "#ffffff"
        self._nametag_color = "#333333"
        self._page_cards: list[_DialogPageCard] = []
        self._build_ui()

    def _color_btn(self, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(32, 24)
        btn.setStyleSheet(f"background: {color}; border: 1px solid {BORDER}; border-radius: 3px;")
        return btn

    def _update_color_btn(self, btn: QPushButton, color: str):
        btn.setStyleSheet(f"background: {color}; border: 1px solid {BORDER}; border-radius: 3px;")

    def _pick_color(self, current: str, callback):
        col = QColorDialog.getColor(QColor(current), self)
        if col.isValid():
            callback(col.name())

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 0, 16)
        layout.setSpacing(6)

        # ── Dialog Pages ─────────────────────────────────────
        layout.addWidget(_section("DIALOG PAGES"))
        layout.addWidget(_divider())

        info = QLabel("Each page shows 4 lines on the Vita. The player presses a button to advance through pages.")
        info.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._pages_container = QVBoxLayout()
        self._pages_container.setSpacing(8)
        layout.addLayout(self._pages_container)

        add_page_btn = _btn("＋  Add Page", accent=True)
        add_page_btn.clicked.connect(self._add_page)
        layout.addWidget(add_page_btn)

        # ── Advance Button ───────────────────────────────────
        layout.addWidget(_section("ADVANCE BUTTON"))
        layout.addWidget(_divider())

        layout.addWidget(_dim("Button to advance pages / scene:"))
        self.advance_btn_combo = QComboBox()
        self.advance_btn_combo.addItems(BUTTON_CHOICES)
        self.advance_btn_combo.setStyleSheet(_field_style())
        self.advance_btn_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.advance_btn_combo)

        self.auto_advance_check = QCheckBox("Auto-advance after delay")
        self.auto_advance_check.setStyleSheet(_field_style())
        self.auto_advance_check.stateChanged.connect(self._on_auto_advance_toggled)
        layout.addWidget(self.auto_advance_check)

        self._auto_advance_options = QWidget()
        aa = QHBoxLayout(self._auto_advance_options)
        aa.setContentsMargins(0, 0, 0, 0)
        aa.addWidget(_dim("Seconds:"))
        self.auto_advance_spin = QDoubleSpinBox()
        self.auto_advance_spin.setRange(0.5, 30.0)
        self.auto_advance_spin.setSingleStep(0.5)
        self.auto_advance_spin.setValue(3.0)
        self.auto_advance_spin.setFixedWidth(70)
        self.auto_advance_spin.setStyleSheet(_field_style())
        self.auto_advance_spin.valueChanged.connect(self._emit)
        aa.addWidget(self.auto_advance_spin)
        aa.addStretch()
        self._auto_advance_options.setVisible(False)
        layout.addWidget(self._auto_advance_options)

        # ── Background ───────────────────────────────────────
        layout.addWidget(_section("BOX BACKGROUND"))
        layout.addWidget(_divider())

        fill_row = QHBoxLayout()
        fill_lbl = _dim("Fill color:")
        self._fill_btn = self._color_btn(self._fill_color)
        self._fill_btn.clicked.connect(lambda: self._pick_color(
            self._fill_color,
            lambda c: (setattr(self, "_fill_color", c),
                       self._update_color_btn(self._fill_btn, c),
                       self._emit())
        ))
        fill_row.addWidget(fill_lbl)
        fill_row.addWidget(self._fill_btn)
        fill_row.addStretch()
        layout.addLayout(fill_row)

        opacity_row = QHBoxLayout()
        opacity_lbl = _dim("Opacity (0–255):")
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 255)
        self.opacity_spin.setValue(150)
        self.opacity_spin.setFixedWidth(70)
        self.opacity_spin.setStyleSheet(_field_style())
        self.opacity_spin.valueChanged.connect(self._emit)
        opacity_row.addWidget(opacity_lbl)
        opacity_row.addWidget(self.opacity_spin)
        opacity_row.addStretch()
        layout.addLayout(opacity_row)

        # Texture
        layout.addWidget(_dim("Texture image (880 × 200 px recommended):"))
        tex_info = QLabel("If set, drawn stretched over the box. Make it 880×200 for a pixel-perfect fit.")
        tex_info.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        tex_info.setWordWrap(True)
        layout.addWidget(tex_info)
        self.texture_combo = QComboBox()
        self.texture_combo.setStyleSheet(_field_style())
        self.texture_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.texture_combo)

        # ── Border ───────────────────────────────────────────
        layout.addWidget(_section("BORDER"))
        layout.addWidget(_divider())

        self.border_check = QCheckBox("Show border")
        self.border_check.setStyleSheet(_field_style())
        self.border_check.stateChanged.connect(self._on_border_toggled)
        layout.addWidget(self.border_check)

        self._border_options = QWidget()
        bo = QVBoxLayout(self._border_options)
        bo.setContentsMargins(0, 0, 0, 0)
        bo.setSpacing(4)

        border_color_row = QHBoxLayout()
        border_color_row.addWidget(_dim("Border color:"))
        self._border_color_btn = self._color_btn(self._border_color)
        self._border_color_btn.clicked.connect(lambda: self._pick_color(
            self._border_color,
            lambda c: (setattr(self, "_border_color", c),
                       self._update_color_btn(self._border_color_btn, c),
                       self._emit())
        ))
        border_color_row.addWidget(self._border_color_btn)
        border_color_row.addStretch()
        bo.addLayout(border_color_row)

        border_thick_row = QHBoxLayout()
        border_thick_row.addWidget(_dim("Thickness (px):"))
        self.border_thickness_spin = QSpinBox()
        self.border_thickness_spin.setRange(1, 20)
        self.border_thickness_spin.setValue(2)
        self.border_thickness_spin.setFixedWidth(60)
        self.border_thickness_spin.setStyleSheet(_field_style())
        self.border_thickness_spin.valueChanged.connect(self._emit)
        border_thick_row.addWidget(self.border_thickness_spin)
        border_thick_row.addStretch()
        bo.addLayout(border_thick_row)

        self._border_options.setVisible(False)
        layout.addWidget(self._border_options)

        # ── Text ─────────────────────────────────────────────
        layout.addWidget(_section("TEXT"))
        layout.addWidget(_divider())

        text_color_row = QHBoxLayout()
        text_color_row.addWidget(_dim("Text color:"))
        self._text_color_btn = self._color_btn(self._text_color)
        self._text_color_btn.clicked.connect(lambda: self._pick_color(
            self._text_color,
            lambda c: (setattr(self, "_text_color", c),
                       self._update_color_btn(self._text_color_btn, c),
                       self._emit())
        ))
        text_color_row.addWidget(self._text_color_btn)
        text_color_row.addStretch()
        layout.addLayout(text_color_row)

        self.shadow_check = QCheckBox("Drop shadow on text")
        self.shadow_check.setChecked(True)
        self.shadow_check.setStyleSheet(_field_style())
        self.shadow_check.stateChanged.connect(self._emit)
        layout.addWidget(self.shadow_check)

        layout.addWidget(_dim("Font:"))
        self.font_combo = QComboBox()
        self.font_combo.setStyleSheet(_field_style())
        self.font_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.font_combo)

        # Font size
        fs_row = QHBoxLayout()
        fs_row.setSpacing(8)
        fs_row.addWidget(_dim("Font size (px):"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setValue(16)
        self.font_size_spin.setFixedWidth(70)
        self.font_size_spin.setStyleSheet(_field_style())
        self.font_size_spin.valueChanged.connect(self._emit)
        fs_row.addWidget(self.font_size_spin)
        fs_row.addStretch()
        layout.addLayout(fs_row)

        fs_hint = QLabel("Maps to Font.setPixelSizes on Vita. Default font looks good at 16.")
        fs_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        fs_hint.setWordWrap(True)
        layout.addWidget(fs_hint)

        # Line spacing
        ls_row = QHBoxLayout()
        ls_row.setSpacing(8)
        ls_row.addWidget(_dim("Line spacing (px):"))
        self.line_spacing_spin = QSpinBox()
        self.line_spacing_spin.setRange(16, 80)
        self.line_spacing_spin.setValue(35)
        self.line_spacing_spin.setFixedWidth(70)
        self.line_spacing_spin.setStyleSheet(_field_style())
        self.line_spacing_spin.valueChanged.connect(self._emit)
        ls_row.addWidget(self.line_spacing_spin)
        ls_row.addStretch()
        layout.addLayout(ls_row)

        # ── Speaker name tag ─────────────────────────────────
        layout.addWidget(_section("SPEAKER NAME TAG"))
        layout.addWidget(_divider())

        nametag_color_row = QHBoxLayout()
        nametag_color_row.addWidget(_dim("Tag background:"))
        self._nametag_color_btn = self._color_btn(self._nametag_color)
        self._nametag_color_btn.clicked.connect(lambda: self._pick_color(
            self._nametag_color,
            lambda c: (setattr(self, "_nametag_color", c),
                       self._update_color_btn(self._nametag_color_btn, c),
                       self._emit())
        ))
        nametag_color_row.addWidget(self._nametag_color_btn)
        nametag_color_row.addStretch()
        layout.addLayout(nametag_color_row)

        layout.addWidget(_dim("Tag position:"))
        self.nametag_pos_combo = QComboBox()
        self.nametag_pos_combo.addItems(["inside box top", "above box"])
        self.nametag_pos_combo.setStyleSheet(_field_style())
        self.nametag_pos_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.nametag_pos_combo)

        layout.addStretch()
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Page management ──────────────────────────────────────

    def _add_page(self):
        page_data = {"character": "", "lines": ["", "", "", ""], "advance_to_next": False}
        card = self._create_page_card(len(self._page_cards), page_data)
        self._page_cards.append(card)
        self._pages_container.addWidget(card)
        self._emit()

    def _create_page_card(self, index: int, data: dict) -> _DialogPageCard:
        card = _DialogPageCard(page_index=index)
        card.set_data(data)
        card.changed.connect(self._emit)
        card.delete_requested.connect(self._delete_page)
        return card

    def _delete_page(self, card: _DialogPageCard):
        if len(self._page_cards) <= 1:
            return  # always keep at least one page
        self._page_cards.remove(card)
        self._pages_container.removeWidget(card)
        card.setParent(None)
        card.deleteLater()
        # Re-number remaining pages
        for i, c in enumerate(self._page_cards):
            c.set_page_index(i)
        self._emit()

    def _clear_page_cards(self):
        for card in self._page_cards:
            self._pages_container.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._page_cards.clear()

    # ── Signals ──────────────────────────────────────────────

    def _on_border_toggled(self):
        self._border_options.setVisible(self.border_check.isChecked())
        self._emit()

    def _on_auto_advance_toggled(self):
        self._auto_advance_options.setVisible(self.auto_advance_check.isChecked())
        self._emit()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        cfg = self._component.config
        # Dialog pages
        cfg["dialog_pages"]       = [c.get_data() for c in self._page_cards]
        # Advance settings
        cfg["advance_button"]     = self.advance_btn_combo.currentText()
        cfg["auto_advance"]       = self.auto_advance_check.isChecked()
        cfg["auto_advance_secs"]  = self.auto_advance_spin.value()
        # Appearance
        cfg["fill_color"]         = self._fill_color
        cfg["opacity"]            = self.opacity_spin.value()
        cfg["texture_image_id"]   = self.texture_combo.currentData()
        cfg["border"]             = self.border_check.isChecked()
        cfg["border_color"]       = self._border_color
        cfg["border_thickness"]   = self.border_thickness_spin.value()
        cfg["text_color"]         = self._text_color
        cfg["shadow"]             = self.shadow_check.isChecked()
        cfg["font_id"]            = self.font_combo.currentData()
        cfg["font_size"]          = self.font_size_spin.value()
        cfg["line_spacing"]       = self.line_spacing_spin.value()
        cfg["nametag_color"]      = self._nametag_color
        cfg["nametag_position"]   = self.nametag_pos_combo.currentText()
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config

        # Populate font combo
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItem("Default (font.ttf)", None)
        for f in project.fonts:
            self.font_combo.addItem(f.name, f.id)
        self.font_combo.blockSignals(False)

        # Populate texture combo
        self.texture_combo.blockSignals(True)
        self.texture_combo.clear()
        self.texture_combo.addItem("None", None)
        for img in project.images:
            self.texture_combo.addItem(img.name, img.id)
        self.texture_combo.blockSignals(False)

        # ── Load dialog pages ────────────────────────────────
        self._clear_page_cards()
        pages = cfg.get("dialog_pages", [{"character": "", "lines": ["", "", "", ""], "advance_to_next": False}])
        for i, page_data in enumerate(pages):
            card = self._create_page_card(i, page_data)
            self._page_cards.append(card)
            self._pages_container.addWidget(card)

        # ── Advance settings ─────────────────────────────────
        adv_btn_idx = self.advance_btn_combo.findText(cfg.get("advance_button", "cross"))
        if adv_btn_idx >= 0:
            self.advance_btn_combo.setCurrentIndex(adv_btn_idx)

        self.auto_advance_check.setChecked(cfg.get("auto_advance", False))
        self.auto_advance_spin.setValue(cfg.get("auto_advance_secs", 3.0))
        self._auto_advance_options.setVisible(cfg.get("auto_advance", False))

        # ── Restore appearance ───────────────────────────────
        self._fill_color = cfg.get("fill_color", "#000000")
        self._update_color_btn(self._fill_btn, self._fill_color)
        self.opacity_spin.setValue(cfg.get("opacity", 150))

        tex_id = cfg.get("texture_image_id")
        for i in range(self.texture_combo.count()):
            if self.texture_combo.itemData(i) == tex_id:
                self.texture_combo.setCurrentIndex(i)
                break

        self.border_check.setChecked(cfg.get("border", False))
        self._border_color = cfg.get("border_color", "#ffffff")
        self._update_color_btn(self._border_color_btn, self._border_color)
        self.border_thickness_spin.setValue(cfg.get("border_thickness", 2))
        self._border_options.setVisible(cfg.get("border", False))

        self._text_color = cfg.get("text_color", "#ffffff")
        self._update_color_btn(self._text_color_btn, self._text_color)
        self.shadow_check.setChecked(cfg.get("shadow", True))

        font_id = cfg.get("font_id")
        for i in range(self.font_combo.count()):
            if self.font_combo.itemData(i) == font_id:
                self.font_combo.setCurrentIndex(i)
                break

        self.font_size_spin.setValue(cfg.get("font_size", 16))
        self.line_spacing_spin.setValue(cfg.get("line_spacing", 35))

        self._nametag_color = cfg.get("nametag_color", "#333333")
        self._update_color_btn(self._nametag_color_btn, self._nametag_color)
        pos_idx = self.nametag_pos_combo.findText(cfg.get("nametag_position", "inside box top"))
        if pos_idx >= 0:
            self.nametag_pos_combo.setCurrentIndex(pos_idx)

        self._suppress = False


class ChoiceMenuConfigPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_section("CHOICES"))
        layout.addWidget(_divider())

        self._choice_rows: list[dict] = []
        for i in range(4):
            layout.addWidget(_dim(f"Choice {i + 1}:"))
            row = QHBoxLayout()
            row.setSpacing(6)

            text_edit = QLineEdit()
            text_edit.setPlaceholderText("Choice text…")
            text_edit.setStyleSheet(_field_style())
            text_edit.textChanged.connect(self._emit)

            btn_combo = QComboBox()
            btn_combo.addItems(BUTTON_CHOICES)
            btn_combo.setFixedWidth(90)
            btn_combo.setStyleSheet(_field_style())
            btn_combo.currentIndexChanged.connect(self._emit)

            goto_spin = QSpinBox()
            goto_spin.setRange(0, 9999)
            goto_spin.setFixedWidth(80)
            goto_spin.setStyleSheet(_field_style())
            goto_spin.setPrefix("scene ")
            goto_spin.valueChanged.connect(self._emit)

            row.addWidget(text_edit, stretch=1)
            row.addWidget(btn_combo)
            row.addWidget(goto_spin)
            layout.addLayout(row)

            self._choice_rows.append({"text": text_edit, "button": btn_combo, "goto": goto_spin})

        layout.addStretch()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        self._component.config["choices"] = [
            {
                "text":   row["text"].text(),
                "button": row["button"].currentText(),
                "goto":   row["goto"].value(),
            }
            for row in self._choice_rows
        ]
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._suppress = True
        choices = component.config.get("choices", [])
        while len(choices) < 4:
            choices.append({"text": "", "button": "cross", "goto": 0})
        for i, row in enumerate(self._choice_rows):
            c = choices[i]
            row["text"].setText(c.get("text", ""))
            bidx = row["button"].findText(c.get("button", "cross"))
            if bidx >= 0:
                row["button"].setCurrentIndex(bidx)
            row["goto"].setValue(c.get("goto", 0))
        self._suppress = False


class HUDConfigPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("HUD component — configuration coming in a future build.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()


class VideoConfigPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(_section("VIDEO FILE"))
        layout.addWidget(_divider())

        vid_row = QHBoxLayout()
        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("No video selected…")
        self.video_edit.setReadOnly(True)
        self.video_edit.setStyleSheet(_field_style())
        browse_btn = _btn("Browse…", small=True)
        browse_btn.clicked.connect(self._browse)
        vid_row.addWidget(self.video_edit, stretch=1)
        vid_row.addWidget(browse_btn)
        layout.addLayout(vid_row)
        layout.addStretch()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "", "Video Files (*.mp4 *.avi);;All Files (*)"
        )
        if path:
            self.video_edit.setText(path)
            self._emit()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        self._component.config["video_id"] = self.video_edit.text() or None
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._suppress = True
        self.video_edit.setText(component.config.get("video_id") or "")
        self._suppress = False


class TransitionConfigPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_section("TRANSITION FILE"))
        layout.addWidget(_divider())

        layout.addWidget(_dim("Transition (.trans):"))
        self.trans_combo = QComboBox()
        self.trans_combo.setStyleSheet(_field_style())
        self.trans_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.trans_combo)

        layout.addWidget(_section("PLAYBACK"))
        layout.addWidget(_divider())

        fps_row = QHBoxLayout()
        fps_row.setSpacing(8)
        fps_row.addWidget(_dim("FPS override (0 = use file default):"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(0, 120)
        self.fps_spin.setFixedWidth(70)
        self.fps_spin.setStyleSheet(_field_style())
        self.fps_spin.valueChanged.connect(self._emit)
        fps_row.addWidget(self.fps_spin)
        fps_row.addStretch()
        layout.addLayout(fps_row)

        hint = QLabel("The transition plays when this scene ends, before advancing to the next scene.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        self._component.config["trans_file_id"] = self.trans_combo.currentData() or ""
        self._component.config["trans_fps_override"] = self.fps_spin.value()
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config

        self.trans_combo.blockSignals(True)
        self.trans_combo.clear()
        self.trans_combo.addItem("(none)", "")
        if hasattr(project, 'transition_exports'):
            for tr in project.transition_exports:
                self.trans_combo.addItem(tr.name, tr.id)
        current_id = cfg.get("trans_file_id", "")
        for i in range(self.trans_combo.count()):
            if self.trans_combo.itemData(i) == current_id:
                self.trans_combo.setCurrentIndex(i)
                break
        self.trans_combo.blockSignals(False)

        self.fps_spin.setValue(cfg.get("trans_fps_override", 0))
        self._suppress = False


# ─────────────────────────────────────────────────────────────
#  GRAVITY CONFIG PANEL
# ─────────────────────────────────────────────────────────────

class GravityConfigPanel(QWidget):
    """Config panel for the Gravity scene component."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Strength ──────────────────────────────────────────
        layout.addWidget(_section("GRAVITY STRENGTH"))
        hint = QLabel("Acceleration in pixels per frame². Higher = heavier gravity.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.01, 10.0)
        self.strength_spin.setSingleStep(0.1)
        self.strength_spin.setDecimals(2)
        self.strength_spin.setValue(0.5)
        self.strength_spin.setFixedWidth(100)
        self.strength_spin.setStyleSheet(_field_style())
        self.strength_spin.valueChanged.connect(self._emit)
        layout.addWidget(self.strength_spin)

        # ── Direction ─────────────────────────────────────────
        layout.addWidget(_section("DIRECTION"))
        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["down", "up", "left", "right"])
        self.dir_combo.setStyleSheet(_field_style())
        self.dir_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.dir_combo)

        # ── Terminal velocity ─────────────────────────────────
        layout.addWidget(_section("TERMINAL VELOCITY"))
        tv_hint = QLabel("Maximum fall speed in pixels per frame. Prevents infinite acceleration.")
        tv_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        tv_hint.setWordWrap(True)
        layout.addWidget(tv_hint)
        self.terminal_spin = QSpinBox()
        self.terminal_spin.setRange(1, 100)
        self.terminal_spin.setValue(10)
        self.terminal_spin.setFixedWidth(100)
        self.terminal_spin.setStyleSheet(_field_style())
        self.terminal_spin.valueChanged.connect(self._emit)
        layout.addWidget(self.terminal_spin)

        layout.addStretch()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        cfg = self._component.config
        cfg["gravity_strength"]   = self.strength_spin.value()
        cfg["gravity_direction"]  = self.dir_combo.currentText()
        cfg["terminal_velocity"]  = self.terminal_spin.value()
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config
        self.strength_spin.setValue(cfg.get("gravity_strength", 0.5))
        idx = self.dir_combo.findText(cfg.get("gravity_direction", "down"))
        self.dir_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.terminal_spin.setValue(cfg.get("terminal_velocity", 10))
        self._suppress = False


class LayerAnimationConfigPanel(QWidget):
    """Config panel for the LayerAnimation scene component.
    Only parameter: which PaperDollAsset (Layer Animation) to use."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_section("LAYER ANIMATION ASSET"))
        hint = QLabel("Select which Layer Animation to use in this scene.\n"
                       "Create and edit Layer Animations in the Layer Animation tab.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.anim_combo = QComboBox()
        self.anim_combo.setStyleSheet(_field_style())
        self.anim_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.anim_combo)

        layout.addStretch()

    def _emit(self):
        if self._suppress or self._component is None:
            return
        self._component.config["layer_anim_id"] = self.anim_combo.currentData() or ""
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True

        self.anim_combo.blockSignals(True)
        self.anim_combo.clear()
        self.anim_combo.addItem("-- none --", "")
        for doll in project.paper_dolls:
            self.anim_combo.addItem(doll.name, doll.id)
        current_id = component.config.get("layer_anim_id", "")
        if current_id:
            for i in range(self.anim_combo.count()):
                if self.anim_combo.itemData(i) == current_id:
                    self.anim_combo.setCurrentIndex(i)
                    break
        self.anim_combo.blockSignals(False)

        self._suppress = False


# ─────────────────────────────────────────────────────────────
#  GRID CONFIG PANEL
# ─────────────────────────────────────────────────────────────

class GridConfigPanel(QWidget):
    """Config panel for the Grid scene component."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._component: SceneComponent | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Name ──────────────────────────────────────────────
        layout.addWidget(_section("GRID NAME"))
        hint = QLabel("Unique name used by grid behavior actions to target this grid.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. board, inventory, puzzle…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit)
        layout.addWidget(self.name_edit)

        # ── Dimensions ────────────────────────────────────────
        layout.addWidget(_section("GRID SIZE"))
        dim_hint = QLabel("Number of columns and rows in the grid.")
        dim_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        dim_hint.setWordWrap(True)
        layout.addWidget(dim_hint)

        dim_row = QHBoxLayout()
        dim_row.setSpacing(8)
        dim_row.addWidget(_dim("Columns:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 100)
        self.cols_spin.setValue(8)
        self.cols_spin.setFixedWidth(70)
        self.cols_spin.setStyleSheet(_field_style())
        self.cols_spin.valueChanged.connect(self._emit)
        dim_row.addWidget(self.cols_spin)
        dim_row.addSpacing(12)
        dim_row.addWidget(_dim("Rows:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 100)
        self.rows_spin.setValue(8)
        self.rows_spin.setFixedWidth(70)
        self.rows_spin.setStyleSheet(_field_style())
        self.rows_spin.valueChanged.connect(self._emit)
        dim_row.addWidget(self.rows_spin)
        dim_row.addStretch()
        layout.addLayout(dim_row)

        # ── Cell size ─────────────────────────────────────────
        layout.addWidget(_section("CELL SIZE"))
        cell_hint = QLabel("Pixel dimensions of each grid cell.")
        cell_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        cell_hint.setWordWrap(True)
        layout.addWidget(cell_hint)

        cell_row = QHBoxLayout()
        cell_row.setSpacing(8)
        cell_row.addWidget(_dim("Width:"))
        self.cw_spin = QSpinBox()
        self.cw_spin.setRange(1, 512)
        self.cw_spin.setValue(32)
        self.cw_spin.setFixedWidth(70)
        self.cw_spin.setStyleSheet(_field_style())
        self.cw_spin.valueChanged.connect(self._emit)
        cell_row.addWidget(self.cw_spin)
        cell_row.addSpacing(12)
        cell_row.addWidget(_dim("Height:"))
        self.ch_spin = QSpinBox()
        self.ch_spin.setRange(1, 512)
        self.ch_spin.setValue(32)
        self.ch_spin.setFixedWidth(70)
        self.ch_spin.setStyleSheet(_field_style())
        self.ch_spin.valueChanged.connect(self._emit)
        cell_row.addWidget(self.ch_spin)
        cell_row.addStretch()
        layout.addLayout(cell_row)

        # ── Origin ────────────────────────────────────────────
        layout.addWidget(_section("ORIGIN OFFSET"))
        orig_hint = QLabel("Pixel position of the grid's top-left corner in the scene.")
        orig_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        orig_hint.setWordWrap(True)
        layout.addWidget(orig_hint)

        orig_row = QHBoxLayout()
        orig_row.setSpacing(8)
        orig_row.addWidget(_dim("X:"))
        self.ox_spin = QSpinBox()
        self.ox_spin.setRange(-9999, 9999)
        self.ox_spin.setValue(0)
        self.ox_spin.setFixedWidth(80)
        self.ox_spin.setStyleSheet(_field_style())
        self.ox_spin.valueChanged.connect(self._emit)
        orig_row.addWidget(self.ox_spin)
        orig_row.addSpacing(12)
        orig_row.addWidget(_dim("Y:"))
        self.oy_spin = QSpinBox()
        self.oy_spin.setRange(-9999, 9999)
        self.oy_spin.setValue(0)
        self.oy_spin.setFixedWidth(80)
        self.oy_spin.setStyleSheet(_field_style())
        self.oy_spin.valueChanged.connect(self._emit)
        orig_row.addWidget(self.oy_spin)
        orig_row.addStretch()
        layout.addLayout(orig_row)

        # ── Info ──────────────────────────────────────────────
        layout.addWidget(_divider())
        info = QLabel(
            "The grid is a logical structure — it does not draw anything.\n"
            "Use grid_place_at, grid_snap_to, grid_move, etc. in behavior\n"
            "actions to position objects on the grid at runtime."
        )
        info.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Total size readout ────────────────────────────────
        self._size_label = QLabel()
        self._size_label.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        layout.addWidget(self._size_label)
        self._update_size_label()

        layout.addStretch()

    def _update_size_label(self):
        cols = self.cols_spin.value()
        rows = self.rows_spin.value()
        cw = self.cw_spin.value()
        ch = self.ch_spin.value()
        self._size_label.setText(
            f"Total grid area: {cols * cw} × {rows * ch} px  "
            f"({cols}×{rows} cells at {cw}×{ch})"
        )

    def _emit(self):
        if self._suppress or self._component is None:
            return
        cfg = self._component.config
        cfg["grid_name"]   = self.name_edit.text()
        cfg["columns"]     = self.cols_spin.value()
        cfg["rows"]        = self.rows_spin.value()
        cfg["cell_width"]  = self.cw_spin.value()
        cfg["cell_height"] = self.ch_spin.value()
        cfg["origin_x"]    = self.ox_spin.value()
        cfg["origin_y"]    = self.oy_spin.value()
        self._update_size_label()
        self.changed.emit()

    def load(self, component: SceneComponent, project: Project):
        self._component = component
        self._project = project
        self._suppress = True
        cfg = component.config
        self.name_edit.setText(cfg.get("grid_name", "grid1"))
        self.cols_spin.setValue(cfg.get("columns", 8))
        self.rows_spin.setValue(cfg.get("rows", 8))
        self.cw_spin.setValue(cfg.get("cell_width", 32))
        self.ch_spin.setValue(cfg.get("cell_height", 32))
        self.ox_spin.setValue(cfg.get("origin_x", 0))
        self.oy_spin.setValue(cfg.get("origin_y", 0))
        self._update_size_label()
        self._suppress = False


# ─────────────────────────────────────────────────────────────
#  EMPTY STATE PANEL
# ─────────────────────────────────────────────────────────────

class EmptyConfigPanel(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)


# ─────────────────────────────────────────────────────────────
#  SCENE OPTIONS TAB
# ─────────────────────────────────────────────────────────────

class SceneOptionsTab(QWidget):
    changed = Signal()
    scene_selected = Signal(int)  # emitted when user picks a scene from the dropdown

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: Scene | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        self._header = header
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(10)
        title = QLabel("SCENE OPTIONS")
        title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        hl.addWidget(title)
        hl.addSpacing(8)

        # Scene selector combo
        self._scene_combo = QComboBox()
        self._scene_combo.setFixedWidth(260)
        self._scene_combo.setStyleSheet(f"""
            QComboBox {{
                background: {SURFACE}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }}
            QComboBox:focus {{ border-color: {ACCENT}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {SURF2}; color: {TEXT};
                border: 1px solid {BORDER};
                selection-background-color: {ACCENT};
            }}
        """)
        self._scene_combo.currentIndexChanged.connect(self._on_scene_combo_changed)
        hl.addWidget(self._scene_combo)
        hl.addStretch()
        outer.addWidget(header)

        # Main body: left list + right config
        body = QWidget()
        body.setStyleSheet(f"background: {DARK};")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── Left panel: scene name + role + component list ──
        left = QWidget()
        left.setFixedWidth(240)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        self._left_panel = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)

        # Scene name
        left_layout.addWidget(_section("SCENE NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Optional label…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._on_name_changed)
        left_layout.addWidget(self.name_edit)

        # Scene role
        left_layout.addWidget(_section("ROLE"))
        role_row = QHBoxLayout()
        role_row.setSpacing(4)
        self._role_btns: dict[str, QPushButton] = {}
        for role, label, color in [("", "Blank", DIM), ("start", "Start", SUCCESS), ("end", "End", DANGER)]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {SURF2}; color: {DIM};
                    border: 1px solid {BORDER}; border-radius: 4px;
                    padding: 0 8px; font-size: 11px; font-weight: 600;
                }}
                QPushButton:checked {{
                    background: {color}22; color: {color};
                    border: 1px solid {color};
                }}
                QPushButton:hover:!checked {{ color: {TEXT}; }}
            """)
            btn.clicked.connect(lambda checked, r=role: self._on_role_changed(r))
            self._role_btns[role] = btn
            role_row.addWidget(btn)
        role_row.addStretch()
        self._role_btns[""].setChecked(True)
        left_layout.addLayout(role_row)

        # Component list
        left_layout.addWidget(_section("COMPONENTS"))
        self.comp_list = QListWidget()
        self.comp_list.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px; border-radius: 3px;
                border-bottom: 1px solid {BORDER};
            }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURF2}; }}
        """)
        self.comp_list.currentRowChanged.connect(self._on_comp_selected)
        left_layout.addWidget(self.comp_list, stretch=1)

        # Component buttons
        comp_btn_row = QHBoxLayout()
        comp_btn_row.setSpacing(4)
        add_comp_btn = _btn("+ Add", accent=True, small=True)
        add_comp_btn.clicked.connect(self._add_component)
        del_comp_btn = _btn("x", danger=True, small=True)
        del_comp_btn.setFixedWidth(32)
        del_comp_btn.clicked.connect(self._del_component)
        comp_btn_row.addWidget(add_comp_btn)
        comp_btn_row.addWidget(del_comp_btn)
        comp_btn_row.addStretch()
        left_layout.addLayout(comp_btn_row)

        body_layout.addWidget(left)

        # ── Right panel: dynamic component config ───────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("border: none; background: transparent;")

        right_body = QWidget()
        right_body.setStyleSheet(f"background: {DARK};")
        right_v = QVBoxLayout(right_body)
        right_v.setContentsMargins(20, 16, 20, 20)
        right_v.setSpacing(0)

        # Component type header
        self._comp_header = QLabel("")
        self._comp_header.setStyleSheet(f"""
            color: {TEXT}; font-size: 14px; font-weight: 700;
            padding-bottom: 6px; background: transparent;
        """)
        right_v.addWidget(self._comp_header)
        right_v.addWidget(_divider())

        # Stacked widget for per-type config panels
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        # Empty state
        self._empty_panel = EmptyConfigPanel("Select a component to configure it,\nor add one using the + button.")
        self._stack.addWidget(self._empty_panel)

        # Config panels (order matches COMPONENT_TYPES)
        self._panels: dict[str, QWidget] = {
            "Layer":          LayerConfigPanel(),
            "Music":          MusicConfigPanel(),
            "VNDialogBox":    VNDialogBoxConfigPanel(),
            "ChoiceMenu":     ChoiceMenuConfigPanel(),
            "HUD":            HUDConfigPanel(),
            "Video":          VideoConfigPanel(),
            "Transition":     TransitionConfigPanel(),
            "Gravity":        GravityConfigPanel(),
            "LayerAnimation": LayerAnimationConfigPanel(),
            "Grid":           GridConfigPanel(),
        }
        for panel in self._panels.values():
            panel.setStyleSheet("background: transparent;")
            if hasattr(panel, "changed"):
                panel.changed.connect(self._on_component_config_changed)
            self._stack.addWidget(panel)

        right_v.addSpacing(10)
        right_v.addWidget(self._stack, stretch=1)
        right_scroll.setWidget(right_body)
        body_layout.addWidget(right_scroll, stretch=1)

        outer.addWidget(body, stretch=1)

    # ── Component list management ────────────────────────────

    def _refresh_comp_list(self):
        if self._scene is None:
            return
        self.comp_list.blockSignals(True)
        self.comp_list.clear()
        for c in self._scene.components:
            if c.component_type in ("Layer", "TileLayer", "CollisionLayer"):
                label = c.config.get("layer_name", "").strip()
                display = f"{c.component_type}: {label}" if label else c.component_type
            elif c.component_type == "LayerAnimation":
                anim_id = c.config.get("layer_anim_id", "")
                anim_name = ""
                if anim_id and self._project:
                    doll = self._project.get_paper_doll(anim_id)
                    if doll:
                        anim_name = doll.name
                display = f"LayerAnimation: {anim_name}" if anim_name else "LayerAnimation"
            elif c.component_type == "Grid":
                gname = c.config.get("grid_name", "").strip()
                display = f"Grid: {gname}" if gname else "Grid"
            else:
                display = c.component_type
            item = QListWidgetItem(display)
            color = COMPONENT_COLORS.get(c.component_type, DIM)
            item.setForeground(QColor(color))
            self.comp_list.addItem(item)
        self.comp_list.blockSignals(False)

    def _on_comp_selected(self, row: int):
        if self._scene is None or row < 0 or row >= len(self._scene.components):
            self._comp_header.setText("")
            self._stack.setCurrentWidget(self._empty_panel)
            return
        component = self._scene.components[row]
        ct = component.component_type
        color = COMPONENT_COLORS.get(ct, DIM)
        self._comp_header.setText(ct)
        self._comp_header.setStyleSheet(f"""
            color: {color}; font-size: 14px; font-weight: 700;
            padding-bottom: 6px; background: transparent;
        """)
        panel = self._panels.get(ct)
        if panel:
            panel.load(component, self._project)
            self._stack.setCurrentWidget(panel)
        else:
            self._stack.setCurrentWidget(self._empty_panel)

    def _add_component(self):
        if self._scene is None:
            return
        existing = [c.component_type for c in self._scene.components]
        dlg = AddComponentDialog(existing, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ct = dlg.selected_type()
            if ct:
                self._scene.components.append(make_component(ct))
                self._refresh_comp_list()
                self.comp_list.setCurrentRow(len(self._scene.components) - 1)
                self.changed.emit()

    def _del_component(self):
        if self._scene is None:
            return
        row = self.comp_list.currentRow()
        if 0 <= row < len(self._scene.components):
            self._scene.components.pop(row)
            self._refresh_comp_list()
            self._comp_header.setText("")
            self._stack.setCurrentWidget(self._empty_panel)
            self.changed.emit()

    # ── Scene meta handlers ──────────────────────────────────

    def _on_name_changed(self, text: str):
        if self._suppress or self._scene is None:
            return
        self._scene.name = text
        self.changed.emit()

    def _on_role_changed(self, role: str):
        for r, btn in self._role_btns.items():
            btn.setChecked(r == role)
        if self._scene is not None:
            self._scene.role = role
            self.changed.emit()

    def _on_component_config_changed(self):
        self.changed.emit()

    # ── Public API ───────────────────────────────────────────

    def refresh_project(self, project: Project, current_index: int):
        """Repopulate the scene selector and load the scene at current_index.
        Call this from main whenever scenes are added, removed, renamed, or
        reordered — it is the single source of truth for keeping this tab in sync.
        If the scene at current_index is already loaded, only refresh the combo
        labels so that typing in the name field does not steal focus."""
        self._project = project
        idx = max(0, min(current_index, len(project.scenes) - 1))

        self._suppress = True
        self._scene_combo.blockSignals(True)
        self._scene_combo.clear()
        for i, s in enumerate(project.scenes):
            label = s.name.strip() if s.name.strip() else f"Scene {i + 1}"
            self._scene_combo.addItem(f"{i + 1}. {label}")
        self._scene_combo.setCurrentIndex(idx)
        self._scene_combo.blockSignals(False)
        self._suppress = False

        # Only do a full load_scene if the scene actually changed.
        # If it's already loaded (same object), skip — this prevents the
        # textChanged -> changed -> _refresh -> refresh_project -> load_scene
        # loop that steals focus from the name field mid-typing.
        if not project.scenes:
            return
        target = project.scenes[idx]
        if target is not self._scene:
            self.load_scene(target, project)

    def _on_scene_combo_changed(self, index: int):
        if self._suppress or self._project is None:
            return
        if 0 <= index < len(self._project.scenes):
            self.load_scene(self._project.scenes[index], self._project)
            self.scene_selected.emit(index)

    def restyle(self, c: dict):
        self._header.setStyleSheet(f"background: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};")
        self._left_panel.setStyleSheet(f"background: {c['PANEL']}; border-right: 1px solid {c['BORDER']};")
        self.comp_list.setStyleSheet(f"""
            QListWidget {{
                background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                border-radius: 4px; color: {c['TEXT']}; outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px; border-radius: 3px; border-bottom: 1px solid {c['BORDER']};
            }}
            QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
        """)
        self.name_edit.setStyleSheet(f"""
            QLineEdit {{ background: {c['SURFACE']}; color: {c['TEXT']};
                border: 1px solid {c['BORDER']}; border-radius: 4px; padding: 5px 8px; }}
            QLineEdit:focus {{ border-color: {c['ACCENT']}; }}
        """)

    def load_scene(self, scene: Scene, project: Project):
        self._scene = scene
        self._project = project
        self._suppress = True

        self.name_edit.setText(scene.name)

        is_3d = getattr(scene, "scene_type", "2d") == "3d"
        for r, btn in self._role_btns.items():
            btn.setChecked(r == scene.role)
            btn.setVisible(not is_3d)

        self._refresh_comp_list()
        self._comp_header.setText("")
        self._stack.setCurrentWidget(self._empty_panel)

        if self._scene.components:
            self.comp_list.setCurrentRow(0)

        self._suppress = False
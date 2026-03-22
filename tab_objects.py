# ===== FILE: tab_objects.py =====

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator -- Objects Tab
Object definition editor (frames, behaviors, VNCharacter config) + per-scene placed instances.
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QSplitter, QSizePolicy, QAbstractItemView,
    QColorDialog, QDialog
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QWheelEvent, QMouseEvent

from models import (
    Project, Scene, ObjectDefinition, SpriteFrame, Behavior,
    BehaviorAction, PlacedObject, CollisionBox
)


# -- Colours -------------------------------------------------------------------
DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURF2   = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
TEXT    = "#e8e6f0"
DIM     = "#7a7890"
MUTED   = "#4a4860"
DANGER  = "#f87171"
SUCCESS = "#4ade80"
WARNING = "#facc15"

# Available triggers for Object Definitions
TRIGGER_TYPES = [
    "on_create", "on_interact", "on_input", "on_frame", "on_true", "on_false", "on_destroy",
    "on_enter", "on_exit", "on_overlap", "on_interact_zone",
]
BEHAVIOR_TYPES = ["default", "VNCharacter", "GUI_Label", "GUI_Button", "GUI_Panel", "Animation", "LayerAnimation", "Camera"]


# -- Helpers -------------------------------------------------------------------

def _field_style():
    return f"""
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 12px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {ACCENT};
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background: {SURF2}; color: {TEXT};
            border: 1px solid {BORDER};
            selection-background-color: {ACCENT};
        }}
        QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button {{
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


def _list_style():
    return f"""
        QListWidget {{
            background: {SURFACE}; border: 1px solid {BORDER};
            border-radius: 4px; color: {TEXT}; outline: none;
        }}
        QListWidget::item {{
            padding: 7px 10px; border-radius: 3px;
            border-bottom: 1px solid {BORDER};
        }}
        QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
        QListWidget::item:hover:!selected {{ background: {SURF2}; }}
    """


def _make_dim_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
    return lbl


# -- Object definition editor --------------------------------------------------

class ObjectDefEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._obj: ObjectDefinition | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")

        body = QWidget()
        body.setStyleSheet(f"background: {DARK};")
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(16, 12, 16, 16)
        self._layout.setSpacing(6)

        self._layout.addWidget(_section("OBJECT DEFINITION"))
        self._layout.addWidget(_divider())

        self._layout.addWidget(_make_dim_label("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Object name…")
        self.name_edit.setStyleSheet(_field_style())
        self.name_edit.textChanged.connect(self._emit)
        self._layout.addWidget(self.name_edit)

        # Groups
        self._layout.addWidget(_make_dim_label("Groups (comma-separated):"))
        self.groups_edit = QLineEdit()
        self.groups_edit.setPlaceholderText("e.g. enemies, coins, pickups")
        self.groups_edit.setStyleSheet(_field_style())
        self.groups_edit.textChanged.connect(self._emit)
        self._layout.addWidget(self.groups_edit)

        # Behavior type
        self._layout.addWidget(_section("BEHAVIOR TYPE"))
        self.behavior_type_combo = QComboBox()
        self.behavior_type_combo.addItems(BEHAVIOR_TYPES)
        self.behavior_type_combo.setStyleSheet(_field_style())
        self.behavior_type_combo.currentTextChanged.connect(self._on_behavior_type_changed)
        self._layout.addWidget(self.behavior_type_combo)

        # ── VNCharacter config ──
        self._vnchar_group = QWidget()
        vg = QVBoxLayout(self._vnchar_group)
        vg.setContentsMargins(0, 0, 0, 0)
        vg.setSpacing(6)

        vg.addWidget(_section("VN CHARACTER"))
        vg.addWidget(_divider())

        vg.addWidget(_make_dim_label("Display Name (shown in dialogue box):"))
        self.vn_name_edit = QLineEdit()
        self.vn_name_edit.setPlaceholderText("Character display name…")
        self.vn_name_edit.setStyleSheet(_field_style())
        self.vn_name_edit.textChanged.connect(self._emit)
        vg.addWidget(self.vn_name_edit)

        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        color_row.addWidget(_make_dim_label("Name Tag Color:"))
        self._vn_color_preview = QLabel()
        self._vn_color_preview.setFixedSize(28, 28)
        self._vn_color_preview.setStyleSheet("background: #FFFFFF; border: 1px solid #2e2e42; border-radius: 4px;")
        color_row.addWidget(self._vn_color_preview)
        pick_btn = _btn("Pick…", small=True)
        pick_btn.clicked.connect(self._pick_vn_color)
        color_row.addWidget(pick_btn)
        color_row.addStretch()
        vg.addLayout(color_row)

        self._vnchar_group.setVisible(False)
        self._layout.addWidget(self._vnchar_group)

        # ── GUI config ──
        self._gui_group = QWidget()
        gg = QVBoxLayout(self._gui_group)
        gg.setContentsMargins(0, 0, 0, 0)
        gg.setSpacing(6)

        gg.addWidget(_section("GUI PROPERTIES"))
        gg.addWidget(_divider())

        # Text (Label + Button)
        self._gui_text_row = QWidget()
        gt = QVBoxLayout(self._gui_text_row)
        gt.setContentsMargins(0, 0, 0, 0)
        gt.setSpacing(4)
        gt.addWidget(_make_dim_label("Display Text:"))
        self.gui_text_edit = QLineEdit()
        self.gui_text_edit.setPlaceholderText("Button or label text…")
        self.gui_text_edit.setStyleSheet(_field_style())
        self.gui_text_edit.textChanged.connect(self._emit)
        gt.addWidget(self.gui_text_edit)
        gg.addWidget(self._gui_text_row)

        # Text color (Label + Button)
        self._gui_text_color_row = QWidget()
        tc = QHBoxLayout(self._gui_text_color_row)
        tc.setContentsMargins(0, 0, 0, 0)
        tc.setSpacing(8)
        tc.addWidget(_make_dim_label("Text Color:"))
        self._gui_text_color_preview = QLabel()
        self._gui_text_color_preview.setFixedSize(28, 28)
        self._gui_text_color_preview.setStyleSheet(f"background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 4px;")
        tc.addWidget(self._gui_text_color_preview)
        pick_tc_btn = _btn("Pick…", small=True)
        pick_tc_btn.clicked.connect(self._pick_gui_text_color)
        tc.addWidget(pick_tc_btn)
        tc.addStretch()
        gg.addWidget(self._gui_text_color_row)

        # Font (Label + Button)
        self._gui_font_row = QWidget()
        gf = QHBoxLayout(self._gui_font_row)
        gf.setContentsMargins(0, 0, 0, 0)
        gf.setSpacing(8)
        gf.addWidget(_make_dim_label("Font:"))
        self.gui_font_combo = QComboBox()
        self.gui_font_combo.setStyleSheet(_field_style())
        self.gui_font_combo.currentIndexChanged.connect(self._emit)
        gf.addWidget(self.gui_font_combo, stretch=1)
        gg.addWidget(self._gui_font_row)

        # Text alignment (Label + Button)
        self._gui_align_row = QWidget()
        ga = QHBoxLayout(self._gui_align_row)
        ga.setContentsMargins(0, 0, 0, 0)
        ga.setSpacing(8)
        ga.addWidget(_make_dim_label("Align:"))
        self.gui_align_combo = QComboBox()
        self.gui_align_combo.addItems(["left", "center", "right"])
        self.gui_align_combo.setStyleSheet(_field_style())
        self.gui_align_combo.currentIndexChanged.connect(self._emit)
        ga.addWidget(self.gui_align_combo)
        ga.addStretch()
        gg.addWidget(self._gui_align_row)

        # Font size (Label + Button)
        self._gui_font_size_row = QWidget()
        gfs = QHBoxLayout(self._gui_font_size_row)
        gfs.setContentsMargins(0, 0, 0, 0)
        gfs.setSpacing(8)
        gfs.addWidget(_make_dim_label("Font Size:"))
        self.gui_font_size_spin = QSpinBox()
        self.gui_font_size_spin.setRange(4, 128)
        self.gui_font_size_spin.setValue(16)
        self.gui_font_size_spin.setFixedWidth(70)
        self.gui_font_size_spin.setStyleSheet(_field_style())
        self.gui_font_size_spin.valueChanged.connect(self._emit)
        gfs.addWidget(self.gui_font_size_spin)
        gfs.addStretch()
        gg.addWidget(self._gui_font_size_row)

        # Background color (Panel + Button)
        self._gui_bg_color_row = QWidget()
        bc = QHBoxLayout(self._gui_bg_color_row)
        bc.setContentsMargins(0, 0, 0, 0)
        bc.setSpacing(8)
        bc.addWidget(_make_dim_label("BG Color:"))
        self._gui_bg_color_preview = QLabel()
        self._gui_bg_color_preview.setFixedSize(28, 28)
        self._gui_bg_color_preview.setStyleSheet(f"background: #000000; border: 1px solid {BORDER}; border-radius: 4px;")
        bc.addWidget(self._gui_bg_color_preview)
        pick_bc_btn = _btn("Pick…", small=True)
        pick_bc_btn.clicked.connect(self._pick_gui_bg_color)
        bc.addWidget(pick_bc_btn)
        bc.addStretch()
        gg.addWidget(self._gui_bg_color_row)

        # BG opacity (Panel + Button)
        self._gui_opacity_row = QWidget()
        op = QHBoxLayout(self._gui_opacity_row)
        op.setContentsMargins(0, 0, 0, 0)
        op.setSpacing(8)
        op.addWidget(_make_dim_label("BG Opacity:"))
        self.gui_opacity_spin = QSpinBox()
        self.gui_opacity_spin.setRange(0, 255)
        self.gui_opacity_spin.setValue(150)
        self.gui_opacity_spin.setStyleSheet(_field_style())
        self.gui_opacity_spin.valueChanged.connect(self._emit)
        op.addWidget(self.gui_opacity_spin)
        op.addStretch()
        gg.addWidget(self._gui_opacity_row)

        # Size W/H (Panel + Button)
        self._gui_size_row = QWidget()
        gs = QHBoxLayout(self._gui_size_row)
        gs.setContentsMargins(0, 0, 0, 0)
        gs.setSpacing(8)
        gs.addWidget(_make_dim_label("GUI W:"))
        self.gui_width_spin = QSpinBox()
        self.gui_width_spin.setRange(1, 960)
        self.gui_width_spin.setValue(200)
        self.gui_width_spin.setFixedWidth(70)
        self.gui_width_spin.setStyleSheet(_field_style())
        self.gui_width_spin.valueChanged.connect(self._emit)
        gs.addWidget(self.gui_width_spin)
        gs.addWidget(_make_dim_label("H:"))
        self.gui_height_spin = QSpinBox()
        self.gui_height_spin.setRange(1, 544)
        self.gui_height_spin.setValue(50)
        self.gui_height_spin.setFixedWidth(70)
        self.gui_height_spin.setStyleSheet(_field_style())
        self.gui_height_spin.valueChanged.connect(self._emit)
        gs.addWidget(self.gui_height_spin)
        gs.addStretch()
        gg.addWidget(self._gui_size_row)

        # Highlight color (Button only)
        self._gui_highlight_row = QWidget()
        hc = QHBoxLayout(self._gui_highlight_row)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.setSpacing(8)
        hc.addWidget(_make_dim_label("Focus Color:"))
        self._gui_highlight_preview = QLabel()
        self._gui_highlight_preview.setFixedSize(28, 28)
        self._gui_highlight_preview.setStyleSheet(f"background: {ACCENT}; border: 1px solid {BORDER}; border-radius: 4px;")
        hc.addWidget(self._gui_highlight_preview)
        pick_hc_btn = _btn("Pick…", small=True)
        pick_hc_btn.clicked.connect(self._pick_gui_highlight_color)
        hc.addWidget(pick_hc_btn)
        hc.addStretch()
        gg.addWidget(self._gui_highlight_row)

        # Background image (Button only)
        self._gui_image_row = QWidget()
        gi = QHBoxLayout(self._gui_image_row)
        gi.setContentsMargins(0, 0, 0, 0)
        gi.setSpacing(8)
        gi.addWidget(_make_dim_label("BG Image:"))
        self.gui_image_combo = QComboBox()
        self.gui_image_combo.setStyleSheet(_field_style())
        self.gui_image_combo.currentIndexChanged.connect(self._emit)
        gi.addWidget(self.gui_image_combo, stretch=1)
        gg.addWidget(self._gui_image_row)

        self._gui_group.setVisible(False)
        self._layout.addWidget(self._gui_group)

        # ── Animation config (shown when behavior_type == Animation) ──
        self._ani_group = QWidget()
        ag = QVBoxLayout(self._ani_group)
        ag.setContentsMargins(0, 0, 0, 0)
        ag.setSpacing(6)

        ag.addWidget(_section("ANIMATION"))
        ag.addWidget(_divider())

        ag.addWidget(_make_dim_label("Animation File (.ani):"))
        self.ani_file_combo = QComboBox()
        self.ani_file_combo.setStyleSheet(_field_style())
        self.ani_file_combo.currentIndexChanged.connect(self._emit)
        ag.addWidget(self.ani_file_combo)

        self.ani_loop_check = QCheckBox("Loop")
        self.ani_loop_check.setStyleSheet(_field_style())
        self.ani_loop_check.setChecked(True)
        self.ani_loop_check.stateChanged.connect(self._emit)
        ag.addWidget(self.ani_loop_check)

        self.ani_play_on_spawn_check = QCheckBox("Play on spawn")
        self.ani_play_on_spawn_check.setStyleSheet(_field_style())
        self.ani_play_on_spawn_check.setChecked(True)
        self.ani_play_on_spawn_check.stateChanged.connect(self._emit)
        ag.addWidget(self.ani_play_on_spawn_check)

        self.ani_start_paused_check = QCheckBox("Start paused")
        self.ani_start_paused_check.setStyleSheet(_field_style())
        self.ani_start_paused_check.stateChanged.connect(self._emit)
        ag.addWidget(self.ani_start_paused_check)

        pause_frame_row = QHBoxLayout()
        pause_frame_row.setSpacing(8)
        pause_frame_row.addWidget(_make_dim_label("Pause at frame:"))
        self.ani_pause_frame_spin = QSpinBox()
        self.ani_pause_frame_spin.setRange(0, 9999)
        self.ani_pause_frame_spin.setStyleSheet(_field_style())
        self.ani_pause_frame_spin.valueChanged.connect(self._emit)
        pause_frame_row.addWidget(self.ani_pause_frame_spin)
        pause_frame_row.addStretch()
        ag.addLayout(pause_frame_row)

        fps_row = QHBoxLayout()
        fps_row.setSpacing(8)
        fps_row.addWidget(_make_dim_label("FPS override (0 = use file default):"))
        self.ani_fps_spin = QSpinBox()
        self.ani_fps_spin.setRange(0, 120)
        self.ani_fps_spin.setStyleSheet(_field_style())
        self.ani_fps_spin.valueChanged.connect(self._emit)
        fps_row.addWidget(self.ani_fps_spin)
        fps_row.addStretch()
        ag.addLayout(fps_row)

        self._ani_group.setVisible(False)
        self._layout.addWidget(self._ani_group)

        # ── LayerAnimation config (shown when behavior_type == LayerAnimation) ──
        self._layer_anim_group = QWidget()
        lag = QVBoxLayout(self._layer_anim_group)
        lag.setContentsMargins(0, 0, 0, 0)
        lag.setSpacing(6)

        lag.addWidget(_section("LAYER ANIMATION"))
        lag.addWidget(_divider())

        lag.addWidget(_make_dim_label("Paper Doll Asset:"))
        self.layer_anim_combo = QComboBox()
        self.layer_anim_combo.setStyleSheet(_field_style())
        self.layer_anim_combo.currentIndexChanged.connect(self._emit)
        lag.addWidget(self.layer_anim_combo)

        self.layer_anim_blink_check = QCheckBox("Blink enabled at spawn")
        self.layer_anim_blink_check.setStyleSheet(_field_style())
        self.layer_anim_blink_check.setChecked(True)
        self.layer_anim_blink_check.stateChanged.connect(self._emit)
        lag.addWidget(self.layer_anim_blink_check)

        self.layer_anim_talk_check = QCheckBox("Talk enabled at spawn")
        self.layer_anim_talk_check.setStyleSheet(_field_style())
        self.layer_anim_talk_check.setChecked(True)
        self.layer_anim_talk_check.stateChanged.connect(self._emit)
        lag.addWidget(self.layer_anim_talk_check)

        self.layer_anim_idle_check = QCheckBox("Idle breathing enabled at spawn")
        self.layer_anim_idle_check.setStyleSheet(_field_style())
        self.layer_anim_idle_check.setChecked(True)
        self.layer_anim_idle_check.stateChanged.connect(self._emit)
        lag.addWidget(self.layer_anim_idle_check)

        self._layer_anim_group.setVisible(False)
        self._layout.addWidget(self._layer_anim_group)

        # Track GUI colors
        self._gui_text_color = "#FFFFFF"
        self._gui_bg_color = "#000000"
        self._gui_highlight_color = ACCENT

        # ── Camera config (Camera only) ──
        self._camera_group = QWidget()
        cg = QVBoxLayout(self._camera_group)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(6)
        
        cg.addWidget(_section("CAMERA SETTINGS"))
        cg.addWidget(_divider())
        
        self.cam_bounds_check = QCheckBox("Enable Bounds")
        self.cam_bounds_check.setStyleSheet(_field_style())
        self.cam_bounds_check.stateChanged.connect(self._on_camera_bounds_changed)
        cg.addWidget(self.cam_bounds_check)
        
        self._cam_bounds_row = QWidget()
        cbr = QHBoxLayout(self._cam_bounds_row)
        cbr.setContentsMargins(0, 0, 0, 0)
        cbr.addWidget(_make_dim_label("W:"))
        self.cam_w_spin = QSpinBox()
        self.cam_w_spin.setRange(960, 99999)
        self.cam_w_spin.setValue(960)
        self.cam_w_spin.setStyleSheet(_field_style())
        self.cam_w_spin.valueChanged.connect(self._emit)
        cbr.addWidget(self.cam_w_spin)
        cbr.addWidget(_make_dim_label("H:"))
        self.cam_h_spin = QSpinBox()
        self.cam_h_spin.setRange(544, 99999)
        self.cam_h_spin.setValue(544)
        self.cam_h_spin.setStyleSheet(_field_style())
        self.cam_h_spin.valueChanged.connect(self._emit)
        cbr.addWidget(self.cam_h_spin)
        self._cam_bounds_row.setVisible(False)
        cg.addWidget(self._cam_bounds_row)
        
        lag_row = QHBoxLayout()
        lag_row.addWidget(_make_dim_label("Follow Lag:"))
        self.cam_lag_spin = QDoubleSpinBox()
        self.cam_lag_spin.setRange(0.0, 0.95)
        self.cam_lag_spin.setSingleStep(0.05)
        self.cam_lag_spin.setStyleSheet(_field_style())
        self.cam_lag_spin.valueChanged.connect(self._emit)
        lag_row.addWidget(self.cam_lag_spin)
        lag_row.addWidget(_make_dim_label("(0=instant, 0.9=slow)"))
        cg.addLayout(lag_row)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(_make_dim_label("Default Zoom:"))
        self.cam_zoom_spin = QDoubleSpinBox()
        self.cam_zoom_spin.setRange(0.25, 4.0)
        self.cam_zoom_spin.setSingleStep(0.05)
        self.cam_zoom_spin.setValue(1.0)
        self.cam_zoom_spin.setDecimals(2)
        self.cam_zoom_spin.setStyleSheet(_field_style())
        self.cam_zoom_spin.valueChanged.connect(self._emit)
        zoom_row.addWidget(self.cam_zoom_spin)
        zoom_row.addWidget(_make_dim_label("(1.0=normal, 2.0=2× in, 0.5=2× out)"))
        cg.addLayout(zoom_row)
        
        self._camera_group.setVisible(False)
        self._layout.addWidget(self._camera_group)

        # Size
        self._size_row = QWidget()
        size_row = QHBoxLayout(self._size_row)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        self._layout.addWidget(_section("SIZE"))
        w_lbl = _make_dim_label("W:")
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 9999)
        self.width_spin.setValue(64)
        self.width_spin.setFixedWidth(70)
        self.width_spin.setStyleSheet(_field_style())
        self.width_spin.valueChanged.connect(self._emit)
        h_lbl = _make_dim_label("H:")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 9999)
        self.height_spin.setValue(64)
        self.height_spin.setFixedWidth(70)
        self.height_spin.setStyleSheet(_field_style())
        self.height_spin.valueChanged.connect(self._emit)
        size_row.addWidget(w_lbl)
        size_row.addWidget(self.width_spin)
        size_row.addWidget(h_lbl)
        size_row.addWidget(self.height_spin)
        size_row.addStretch()
        self._layout.addWidget(self._size_row)

        self.visible_check = QCheckBox("Visible by default")
        self.visible_check.setStyleSheet(_field_style())
        self.visible_check.setChecked(True)
        self.visible_check.stateChanged.connect(self._emit)
        self._layout.addWidget(self.visible_check)

        self.gravity_check = QCheckBox("Affected by gravity")
        self.gravity_check.setStyleSheet(_field_style())
        self.gravity_check.setChecked(False)
        self.gravity_check.stateChanged.connect(self._emit)
        self._layout.addWidget(self.gravity_check)

        # Frames
        self._frames_section = QWidget()
        fsl = QVBoxLayout(self._frames_section)
        fsl.setContentsMargins(0, 0, 0, 0)
        fsl.addWidget(_section("SPRITE FRAMES"))
        frame_btn_row = QHBoxLayout()
        frame_btn_row.setSpacing(4)
        add_frame_btn = _btn("+ Frame", accent=True, small=True)
        add_frame_btn.clicked.connect(self._add_frame)
        del_frame_btn = _btn("x", danger=True, small=True)
        del_frame_btn.setFixedWidth(32)
        del_frame_btn.clicked.connect(self._del_frame)
        frame_btn_row.addWidget(add_frame_btn)
        frame_btn_row.addWidget(del_frame_btn)
        frame_btn_row.addStretch()
        fsl.addLayout(frame_btn_row)

        self.frame_list = QListWidget()
        self.frame_list.setStyleSheet(_list_style())
        self.frame_list.setFixedHeight(90)
        self.frame_list.currentRowChanged.connect(self._on_frame_selected)
        fsl.addWidget(self.frame_list)

        self._frame_editor = QWidget()
        fe = QHBoxLayout(self._frame_editor)
        fe.setContentsMargins(0, 0, 0, 0)
        fe.setSpacing(8)
        fi_lbl = _make_dim_label("Image:")
        self.frame_img_combo = QComboBox()
        self.frame_img_combo.setStyleSheet(_field_style())
        self.frame_img_combo.currentIndexChanged.connect(self._on_frame_img_changed)
        fd_lbl = _make_dim_label("Duration:")
        self.frame_dur_spin = QSpinBox()
        self.frame_dur_spin.setRange(1, 9999)
        self.frame_dur_spin.setValue(6)
        self.frame_dur_spin.setFixedWidth(70)
        self.frame_dur_spin.setStyleSheet(_field_style())
        self.frame_dur_spin.valueChanged.connect(self._on_frame_dur_changed)
        fe.addWidget(fi_lbl)
        fe.addWidget(self.frame_img_combo, stretch=1)
        fe.addWidget(fd_lbl)
        fe.addWidget(self.frame_dur_spin)
        self._frame_editor.setVisible(False)
        fsl.addWidget(self._frame_editor)

        self.fps_label = QLabel("")
        self.fps_label.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        fsl.addWidget(self.fps_label)
        self._layout.addWidget(self._frames_section)

        # Behaviors
        self._layout.addWidget(_section("BEHAVIORS"))

        self._beh_summary = QLabel("No behaviors.")
        self._beh_summary.setWordWrap(True)
        self._beh_summary.setStyleSheet(
            f"color: {DIM}; font-size: 11px; background: transparent; padding: 2px 0;"
        )
        self._layout.addWidget(self._beh_summary)

        self._beh_edit_btn = QPushButton("⬡  Edit Behaviors")
        self._beh_edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURF2}; color: {ACCENT};
                border: 1px solid {ACCENT}; border-radius: 4px;
                padding: 5px 12px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {ACCENT}; color: white; }}
        """)
        self._beh_edit_btn.clicked.connect(self._open_behavior_graph)
        self._layout.addWidget(self._beh_edit_btn)

        self._layout.addStretch()
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Track current VN color
        self._vn_color = "#FFFFFF"

    def _emit(self):
        if self._suppress or self._obj is None:
            return
        o = self._obj
        o.name = self.name_edit.text().strip() or "Object"
        # Groups: parse comma-separated string → list of stripped non-empty strings
        raw_groups = self.groups_edit.text()
        o.groups = [g.strip() for g in raw_groups.split(",") if g.strip()]
        o.width = self.width_spin.value()
        o.height = self.height_spin.value()
        o.visible_default = self.visible_check.isChecked()
        o.affected_by_gravity = self.gravity_check.isChecked()
        o.vn_display_name = self.vn_name_edit.text()
        o.vn_name_color = self._vn_color
        # GUI fields
        o.gui_text = self.gui_text_edit.text()
        o.gui_text_color = self._gui_text_color
        o.gui_font_id = self.gui_font_combo.currentData() or ""
        o.gui_text_align = self.gui_align_combo.currentText()
        o.gui_font_size = self.gui_font_size_spin.value()
        o.gui_bg_color = self._gui_bg_color
        o.gui_bg_opacity = self.gui_opacity_spin.value()
        o.gui_width = self.gui_width_spin.value()
        o.gui_height = self.gui_height_spin.value()
        o.gui_highlight_color = self._gui_highlight_color
        o.gui_image_id = self.gui_image_combo.currentData() or ""
        # Animation fields
        o.ani_file_id = self.ani_file_combo.currentData() or ""
        o.ani_loop = self.ani_loop_check.isChecked()
        o.ani_play_on_spawn = self.ani_play_on_spawn_check.isChecked()
        o.ani_start_paused = self.ani_start_paused_check.isChecked()
        o.ani_pause_frame = self.ani_pause_frame_spin.value()
        o.ani_fps_override = self.ani_fps_spin.value()
        # LayerAnimation fields
        o.layer_anim_id = self.layer_anim_combo.currentData() or ""
        o.layer_anim_blink = self.layer_anim_blink_check.isChecked()
        o.layer_anim_talk = self.layer_anim_talk_check.isChecked()
        o.layer_anim_idle = self.layer_anim_idle_check.isChecked()
        # Camera fields
        o.camera_bounds_enabled = self.cam_bounds_check.isChecked()
        o.camera_bounds_width = self.cam_w_spin.value()
        o.camera_bounds_height = self.cam_h_spin.value()
        o.camera_follow_lag = self.cam_lag_spin.value()
        o.camera_zoom_default = self.cam_zoom_spin.value()
        self.changed.emit()

    def _on_behavior_type_changed(self, btype: str):
        if self._obj is not None and not self._suppress:
            self._obj.behavior_type = btype
            self.changed.emit()
        self._vnchar_group.setVisible(btype == "VNCharacter")
        is_gui = btype.startswith("GUI_")
        self._gui_group.setVisible(is_gui)
        self._ani_group.setVisible(btype == "Animation")
        self._layer_anim_group.setVisible(btype == "LayerAnimation")

    def _on_camera_bounds_changed(self, state):
        self._cam_bounds_row.setVisible(bool(state))
        self._emit()

    def _pick_vn_color(self):
        color = QColorDialog.getColor(QColor(self._vn_color), self, "Pick Name Tag Color")
        if color.isValid():
            self._vn_color = color.name()
            self._vn_color_preview.setStyleSheet(
                f"background: {self._vn_color}; border: 1px solid #2e2e42; border-radius: 4px;"
            )
            self._emit()

    def _pick_gui_text_color(self):
        color = QColorDialog.getColor(QColor(self._gui_text_color), self, "Pick Text Color")
        if color.isValid():
            self._gui_text_color = color.name()
            self._gui_text_color_preview.setStyleSheet(
                f"background: {self._gui_text_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self._emit()

    def _pick_gui_bg_color(self):
        color = QColorDialog.getColor(QColor(self._gui_bg_color), self, "Pick Background Color")
        if color.isValid():
            self._gui_bg_color = color.name()
            self._gui_bg_color_preview.setStyleSheet(
                f"background: {self._gui_bg_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self._emit()

    def _pick_gui_highlight_color(self):
        color = QColorDialog.getColor(QColor(self._gui_highlight_color), self, "Pick Focus Highlight Color")
        if color.isValid():
            self._gui_highlight_color = color.name()
            self._gui_highlight_preview.setStyleSheet(
                f"background: {self._gui_highlight_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self._emit()

    # -- Frames ----------------------------------------------------------------

    def _add_frame(self):
        if self._obj is None:
            return
        self._obj.frames.append(SpriteFrame())
        self._obj.sync_collision_frames()
        self._refresh_frame_list()
        self.frame_list.setCurrentRow(len(self._obj.frames) - 1)
        self._update_fps_label()
        self.changed.emit()

    def _del_frame(self):
        if self._obj is None:
            return
        row = self.frame_list.currentRow()
        if 0 <= row < len(self._obj.frames):
            self._obj.frames.pop(row)
            self._obj.sync_collision_frames()
            self._refresh_frame_list()
            self._frame_editor.setVisible(False)
            self._update_fps_label()
            self.changed.emit()

    def _refresh_frame_list(self):
        if self._obj is None:
            return
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for i, f in enumerate(self._obj.frames):
            img = self._project.get_image(f.image_id) if (self._project and f.image_id) else None
            label = f"Frame {i+1}: {img.name if img else '(no image)'}  [{f.duration_frames}f]"
            self.frame_list.addItem(label)
        self.frame_list.blockSignals(False)

    def _on_frame_selected(self, row: int):
        if self._obj is None or row < 0 or row >= len(self._obj.frames):
            self._frame_editor.setVisible(False)
            return
        f = self._obj.frames[row]
        self._suppress = True
        self.frame_img_combo.blockSignals(True)
        self.frame_img_combo.clear()
        self.frame_img_combo.addItem("-- none --", None)
        if self._project:
            for img in self._project.images:
                self.frame_img_combo.addItem(img.name, img.id)
        if f.image_id:
            for i in range(self.frame_img_combo.count()):
                if self.frame_img_combo.itemData(i) == f.image_id:
                    self.frame_img_combo.setCurrentIndex(i)
                    break
        self.frame_img_combo.blockSignals(False)
        self.frame_dur_spin.setValue(f.duration_frames)
        self._suppress = False
        self._frame_editor.setVisible(True)

    def _on_frame_img_changed(self):
        if self._suppress or self._obj is None:
            return
        row = self.frame_list.currentRow()
        if 0 <= row < len(self._obj.frames):
            self._obj.frames[row].image_id = self.frame_img_combo.currentData()
            self._refresh_frame_list()
            self.changed.emit()

    def _on_frame_dur_changed(self):
        if self._suppress or self._obj is None:
            return
        row = self.frame_list.currentRow()
        if 0 <= row < len(self._obj.frames):
            self._obj.frames[row].duration_frames = self.frame_dur_spin.value()
            self._refresh_frame_list()
            self._update_fps_label()
            self.changed.emit()

    def _update_fps_label(self):
        if self._obj is None or not self._obj.frames:
            self.fps_label.setText("")
            return
        total = sum(f.duration_frames for f in self._obj.frames)
        if total > 0:
            fps = 60.0 / total
            self.fps_label.setText(f"Total: {total} frames  |  ~{fps:.1f} FPS at 60fps")
        else:
            self.fps_label.setText("")

    # -- Behaviors -------------------------------------------------------------

    def _open_behavior_graph(self):
        if self._obj is None or self._project is None:
            return
        from behavior_node_graph import BehaviorGraphDialog
        dlg = BehaviorGraphDialog(self._obj, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_beh_summary()
            self.changed.emit()

    def _refresh_beh_summary(self):
        if self._obj is None or not self._obj.behaviors:
            self._beh_summary.setText("No behaviors.")
            return
        lines = []
        for b in self._obj.behaviors:
            lines.append(f"• {b.trigger}  ({len(b.actions)} actions)")
        self._beh_summary.setText("\n".join(lines))

    # -- Public ----------------------------------------------------------------

    def load_object(self, obj: ObjectDefinition, project: Project):
        self._obj = obj
        self._project = project
        self._suppress = True

        self.name_edit.setText(obj.name)
        self.groups_edit.setText(", ".join(obj.groups) if obj.groups else "")
        self.width_spin.setValue(obj.width)
        self.height_spin.setValue(obj.height)
        self.visible_check.setChecked(obj.visible_default)
        self.gravity_check.setChecked(getattr(obj, 'affected_by_gravity', False))

        # Behavior type
        idx = self.behavior_type_combo.findText(obj.behavior_type)
        if idx >= 0:
            self.behavior_type_combo.setCurrentIndex(idx)
        self._vnchar_group.setVisible(obj.behavior_type == "VNCharacter")

        # VNCharacter fields
        self.vn_name_edit.setText(obj.vn_display_name)
        self._vn_color = obj.vn_name_color or "#FFFFFF"
        self._vn_color_preview.setStyleSheet(
            f"background: {self._vn_color}; border: 1px solid #2e2e42; border-radius: 4px;"
        )

        # GUI fields
        is_gui = obj.behavior_type.startswith("GUI_")
        is_cam = obj.behavior_type == "Camera"
        
        self._gui_group.setVisible(is_gui)
        self._camera_group.setVisible(is_cam)
        
        self._size_row.setVisible(not is_cam)
        self.visible_check.setVisible(not is_cam)
        self.gravity_check.setVisible(not is_cam)
        self._frames_section.setVisible(not is_cam)
        
        if is_gui:
            self.gui_text_edit.setText(obj.gui_text)
            self._gui_text_color = obj.gui_text_color or "#FFFFFF"
            self._gui_text_color_preview.setStyleSheet(
                f"background: {self._gui_text_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self._gui_bg_color = obj.gui_bg_color or "#000000"
            self._gui_bg_color_preview.setStyleSheet(
                f"background: {self._gui_bg_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self._gui_highlight_color = obj.gui_highlight_color or ACCENT
            self._gui_highlight_preview.setStyleSheet(
                f"background: {self._gui_highlight_color}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            self.gui_opacity_spin.setValue(obj.gui_bg_opacity)
            self.gui_width_spin.setValue(obj.gui_width)
            self.gui_height_spin.setValue(obj.gui_height)

            # Populate font combo
            self.gui_font_combo.blockSignals(True)
            self.gui_font_combo.clear()
            self.gui_font_combo.addItem("(default font)", "")
            for fnt in project.fonts:
                self.gui_font_combo.addItem(fnt.name, fnt.id)
            if obj.gui_font_id:
                for i in range(self.gui_font_combo.count()):
                    if self.gui_font_combo.itemData(i) == obj.gui_font_id:
                        self.gui_font_combo.setCurrentIndex(i)
                        break
            self.gui_font_combo.blockSignals(False)

            # Load alignment
            align = getattr(obj, "gui_text_align", "left")
            align_idx = self.gui_align_combo.findText(align)
            self.gui_align_combo.blockSignals(True)
            self.gui_align_combo.setCurrentIndex(align_idx if align_idx >= 0 else 0)
            self.gui_align_combo.blockSignals(False)

            # Load font size
            self.gui_font_size_spin.blockSignals(True)
            self.gui_font_size_spin.setValue(getattr(obj, "gui_font_size", 16))
            self.gui_font_size_spin.blockSignals(False)

            # Populate GUI image combo
            self.gui_image_combo.blockSignals(True)
            self.gui_image_combo.clear()
            self.gui_image_combo.addItem("(none — use color)", "")
            for img in project.images:
                self.gui_image_combo.addItem(img.name, img.id)
            if obj.gui_image_id:
                for i in range(self.gui_image_combo.count()):
                    if self.gui_image_combo.itemData(i) == obj.gui_image_id:
                        self.gui_image_combo.setCurrentIndex(i)
                        break
            self.gui_image_combo.blockSignals(False)

            # Show/hide GUI sub-rows based on type
            btype = obj.behavior_type
            has_text = btype in ("GUI_Label", "GUI_Button")
            has_bg   = btype in ("GUI_Panel", "GUI_Button", "GUI_Label")
            is_btn   = btype == "GUI_Button"
            self._gui_text_row.setVisible(has_text)
            self._gui_text_color_row.setVisible(has_text)
            self._gui_font_row.setVisible(has_text)
            self._gui_align_row.setVisible(has_text)
            self._gui_font_size_row.setVisible(has_text)
            self._gui_bg_color_row.setVisible(has_bg)
            self._gui_opacity_row.setVisible(has_bg)
            self._gui_size_row.setVisible(has_bg)
            self._gui_highlight_row.setVisible(is_btn)
            self._gui_image_row.setVisible(is_btn)
            
        if is_cam:
            self.cam_bounds_check.setChecked(obj.camera_bounds_enabled)
            self._cam_bounds_row.setVisible(obj.camera_bounds_enabled)
            self.cam_w_spin.setValue(obj.camera_bounds_width)
            self.cam_h_spin.setValue(obj.camera_bounds_height)
            self.cam_lag_spin.setValue(obj.camera_follow_lag)
            self.cam_zoom_spin.setValue(getattr(obj, "camera_zoom_default", 1.0))


        # Animation fields
        self._ani_group.setVisible(obj.behavior_type == "Animation")
        self.ani_file_combo.blockSignals(True)
        self.ani_file_combo.clear()
        self.ani_file_combo.addItem("(none)", "")
        if hasattr(project, 'animation_exports'):
            for ani in project.animation_exports:
                self.ani_file_combo.addItem(ani.name, ani.id)
        if getattr(obj, 'ani_file_id', ''):
            for i in range(self.ani_file_combo.count()):
                if self.ani_file_combo.itemData(i) == obj.ani_file_id:
                    self.ani_file_combo.setCurrentIndex(i)
                    break
        self.ani_file_combo.blockSignals(False)
        self.ani_loop_check.setChecked(getattr(obj, 'ani_loop', True))
        self.ani_play_on_spawn_check.setChecked(getattr(obj, 'ani_play_on_spawn', True))
        self.ani_start_paused_check.setChecked(getattr(obj, 'ani_start_paused', False))
        self.ani_pause_frame_spin.setValue(getattr(obj, 'ani_pause_frame', 0))
        self.ani_fps_spin.setValue(getattr(obj, 'ani_fps_override', 0))

        # LayerAnimation fields
        self._layer_anim_group.setVisible(obj.behavior_type == "LayerAnimation")
        self.layer_anim_combo.blockSignals(True)
        self.layer_anim_combo.clear()
        self.layer_anim_combo.addItem("(none)", "")
        if hasattr(project, 'paper_dolls'):
            for pd in project.paper_dolls:
                self.layer_anim_combo.addItem(pd.name, pd.id)
        if getattr(obj, 'layer_anim_id', ''):
            for i in range(self.layer_anim_combo.count()):
                if self.layer_anim_combo.itemData(i) == obj.layer_anim_id:
                    self.layer_anim_combo.setCurrentIndex(i)
                    break
        self.layer_anim_combo.blockSignals(False)
        self.layer_anim_blink_check.setChecked(getattr(obj, 'layer_anim_blink', True))
        self.layer_anim_talk_check.setChecked(getattr(obj, 'layer_anim_talk', True))
        self.layer_anim_idle_check.setChecked(getattr(obj, 'layer_anim_idle', True))

        self._refresh_frame_list()
        self._update_fps_label()
        self._refresh_beh_summary()
        self._frame_editor.setVisible(False)
        #self.behavior_editor.setVisible(False)

        self._suppress = False


# -- Collision Preview Widget --------------------------------------------------

class CollisionPreviewWidget(QWidget):
    """Zoomable, pannable sprite preview with draggable collision boxes."""
    box_changed = Signal()   # emitted when a box is moved / resized

    _HANDLE = 6              # edge-handle grab radius in screen px

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._boxes: list[CollisionBox] = []
        self._selected: int = -1

        # view transform
        self._zoom: float = 1.0
        self._pan: QPointF = QPointF(0, 0)

        # interaction state
        self._dragging: bool = False
        self._resizing: str = ""          # "", "l", "r", "t", "b", "tl", "tr", "bl", "br"
        self._drag_start: QPointF = QPointF()
        self._box_start: tuple = (0, 0, 0, 0)
        self._mid_panning: bool = False
        self._pan_start: QPointF = QPointF()
        self._pan_origin: QPointF = QPointF()

        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self.setStyleSheet(f"background: {DARK};")

    # -- public api --

    def set_pixmap(self, pm: QPixmap | None):
        self._pixmap = pm
        self._fit_view()
        self.update()

    def set_boxes(self, boxes: list[CollisionBox], selected: int = -1):
        self._boxes = boxes
        self._selected = selected
        self.update()

    def set_selected(self, idx: int):
        self._selected = idx
        self.update()

    # -- coordinate helpers --

    def _widget_to_sprite(self, pos: QPointF) -> QPointF:
        """Convert widget pixel → sprite pixel coords."""
        return QPointF(
            (pos.x() - self._pan.x()) / self._zoom,
            (pos.y() - self._pan.y()) / self._zoom,
        )

    def _sprite_to_widget(self, pos: QPointF) -> QPointF:
        return QPointF(
            pos.x() * self._zoom + self._pan.x(),
            pos.y() * self._zoom + self._pan.y(),
        )

    def _box_widget_rect(self, cb: CollisionBox) -> QRectF:
        tl = self._sprite_to_widget(QPointF(cb.x, cb.y))
        br = self._sprite_to_widget(QPointF(cb.x + cb.width, cb.y + cb.height))
        return QRectF(tl, br)

    def _fit_view(self):
        if self._pixmap is None or self._pixmap.isNull():
            self._zoom = 1.0
            self._pan = QPointF(0, 0)
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        margin = 20
        sx = (ww - margin * 2) / max(pw, 1)
        sy = (wh - margin * 2) / max(ph, 1)
        self._zoom = min(sx, sy, 4.0)
        self._pan = QPointF(
            (ww - pw * self._zoom) / 2,
            (wh - ph * self._zoom) / 2,
        )

    # -- hit testing --

    def _edge_hit(self, pos: QPointF) -> tuple[int, str]:
        """Return (box_index, edge_code) under widget pos. Prefer selected box."""
        h = self._HANDLE
        order = list(range(len(self._boxes)))
        if 0 <= self._selected < len(self._boxes):
            order.remove(self._selected)
            order.append(self._selected)  # check selected last → highest priority
        for i in reversed(order):
            r = self._box_widget_rect(self._boxes[i])
            on_l = abs(pos.x() - r.left()) < h
            on_r = abs(pos.x() - r.right()) < h
            on_t = abs(pos.y() - r.top()) < h
            on_b = abs(pos.y() - r.bottom()) < h
            in_x = r.left() - h < pos.x() < r.right() + h
            in_y = r.top() - h < pos.y() < r.bottom() + h

            if on_t and on_l and in_x and in_y:
                return i, "tl"
            if on_t and on_r and in_x and in_y:
                return i, "tr"
            if on_b and on_l and in_x and in_y:
                return i, "bl"
            if on_b and on_r and in_x and in_y:
                return i, "br"
            if on_l and in_y:
                return i, "l"
            if on_r and in_y:
                return i, "r"
            if on_t and in_x:
                return i, "t"
            if on_b and in_x:
                return i, "b"
            if r.contains(pos):
                return i, "move"
        return -1, ""

    # -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # checkerboard background
        p.fillRect(self.rect(), QColor(DARK))

        if self._pixmap and not self._pixmap.isNull():
            # draw sprite
            pw, ph = self._pixmap.width(), self._pixmap.height()
            dst = QRectF(
                self._pan.x(), self._pan.y(),
                pw * self._zoom, ph * self._zoom,
            )
            p.drawPixmap(dst.toRect(), self._pixmap)
            # sprite boundary outline
            p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(dst)

        # draw collision boxes
        for i, cb in enumerate(self._boxes):
            r = self._box_widget_rect(cb)
            is_sel = (i == self._selected)
            fill = QColor(ACCENT)
            fill.setAlpha(60 if is_sel else 30)
            border_color = QColor(ACCENT) if is_sel else QColor("#4ade80")
            p.setBrush(QBrush(fill))
            p.setPen(QPen(border_color, 2 if is_sel else 1))
            p.drawRect(r)
            # corner handles for selected
            if is_sel:
                hs = 4
                for corner in [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]:
                    p.fillRect(QRectF(corner.x() - hs, corner.y() - hs, hs * 2, hs * 2), border_color)
            # label
            p.setPen(QPen(border_color))
            p.drawText(r.adjusted(3, 1, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, str(i))

        p.end()

    # -- mouse events --

    def wheelEvent(self, event: QWheelEvent):
        old_zoom = self._zoom
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom = max(0.1, min(self._zoom * factor, 20.0))
        # zoom toward cursor
        cursor = QPointF(event.position())
        self._pan = cursor - (cursor - self._pan) * (self._zoom / old_zoom)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = QPointF(event.position())
        # middle button → pan
        if event.button() == Qt.MouseButton.MiddleButton:
            self._mid_panning = True
            self._pan_start = pos
            self._pan_origin = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        idx, edge = self._edge_hit(pos)
        if idx >= 0:
            self._selected = idx
            cb = self._boxes[idx]
            self._box_start = (cb.x, cb.y, cb.width, cb.height)
            self._drag_start = self._widget_to_sprite(pos)
            if edge == "move":
                self._dragging = True
            else:
                self._resizing = edge
            self.box_changed.emit()
            self.update()
        else:
            self._selected = -1
            self.box_changed.emit()
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = QPointF(event.position())
        if self._mid_panning:
            delta = pos - self._pan_start
            self._pan = self._pan_origin + delta
            self.update()
            return

        if self._dragging and 0 <= self._selected < len(self._boxes):
            sp = self._widget_to_sprite(pos)
            dx = int(sp.x() - self._drag_start.x())
            dy = int(sp.y() - self._drag_start.y())
            cb = self._boxes[self._selected]
            cb.x = self._box_start[0] + dx
            cb.y = self._box_start[1] + dy
            self.box_changed.emit()
            self.update()
            return

        if self._resizing and 0 <= self._selected < len(self._boxes):
            sp = self._widget_to_sprite(pos)
            dx = int(sp.x() - self._drag_start.x())
            dy = int(sp.y() - self._drag_start.y())
            ox, oy, ow, oh = self._box_start
            cb = self._boxes[self._selected]
            e = self._resizing
            nx, ny, nw, nh = ox, oy, ow, oh
            if "l" in e:
                nx = ox + dx
                nw = ow - dx
            if "r" in e:
                nw = ow + dx
            if "t" in e:
                ny = oy + dy
                nh = oh - dy
            if "b" in e:
                nh = oh + dy
            # enforce minimum size
            if nw < 4:
                if "l" in e:
                    nx = ox + ow - 4
                nw = 4
            if nh < 4:
                if "t" in e:
                    ny = oy + oh - 4
                nh = 4
            cb.x, cb.y, cb.width, cb.height = nx, ny, nw, nh
            self.box_changed.emit()
            self.update()
            return

        # cursor shape based on hover
        idx, edge = self._edge_hit(pos)
        if edge in ("l", "r"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ("t", "b"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge in ("tl", "br"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ("tr", "bl"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._mid_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self._dragging = False
        self._resizing = ""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_view()


# -- Collision Editor Panel (right side) ---------------------------------------

class CollisionEditorPanel(QWidget):
    """Replaces 'Placed in Scene' — edits per-frame collision boxes on an ObjectDefinition."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._obj: ObjectDefinition | None = None
        self._project: Project | None = None
        self._frame_idx: int = 0
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        title = QLabel("COLLISION EDITOR")
        title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        lay.addWidget(title)

        # Preview canvas
        self._preview = CollisionPreviewWidget()
        self._preview.box_changed.connect(self._on_box_dragged)
        lay.addWidget(self._preview, stretch=1)

        # Frame navigation
        nav = QHBoxLayout()
        nav.setSpacing(4)
        self._prev_btn = _btn("◀", small=True)
        self._prev_btn.setFixedWidth(32)
        self._prev_btn.clicked.connect(self._prev_frame)
        self._next_btn = _btn("▶", small=True)
        self._next_btn.setFixedWidth(32)
        self._next_btn.clicked.connect(self._next_frame)
        self._frame_label = QLabel("Frame 1 / 1")
        self._frame_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._frame_label, stretch=1)
        nav.addWidget(self._next_btn)
        lay.addLayout(nav)

        lay.addWidget(_divider())

        # Box list
        box_hdr = QHBoxLayout()
        box_hdr.setSpacing(4)
        box_lbl = QLabel("BOXES")
        box_lbl.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        box_hdr.addWidget(box_lbl)
        box_hdr.addStretch()
        self._add_box_btn = _btn("+", accent=True, small=True)
        self._add_box_btn.setFixedWidth(28)
        self._add_box_btn.setToolTip("Add collision box")
        self._add_box_btn.clicked.connect(self._add_box)
        self._del_box_btn = _btn("x", danger=True, small=True)
        self._del_box_btn.setFixedWidth(28)
        self._del_box_btn.setToolTip("Delete selected box")
        self._del_box_btn.clicked.connect(self._del_box)
        box_hdr.addWidget(self._add_box_btn)
        box_hdr.addWidget(self._del_box_btn)
        lay.addLayout(box_hdr)

        self._box_list = QListWidget()
        self._box_list.setMaximumHeight(100)
        self._box_list.setStyleSheet(_list_style())
        self._box_list.currentRowChanged.connect(self._on_box_selected)
        lay.addWidget(self._box_list)

        # Manual fields for selected box
        self._fields_widget = QWidget()
        fl = QVBoxLayout(self._fields_widget)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(4)

        r1 = QHBoxLayout()
        r1.setSpacing(4)
        r1.addWidget(_make_dim_label("X:"))
        self._bx_spin = QSpinBox()
        self._bx_spin.setRange(-9999, 9999)
        self._bx_spin.setFixedWidth(60)
        self._bx_spin.setStyleSheet(_field_style())
        self._bx_spin.valueChanged.connect(self._on_field_changed)
        r1.addWidget(self._bx_spin)
        r1.addWidget(_make_dim_label("Y:"))
        self._by_spin = QSpinBox()
        self._by_spin.setRange(-9999, 9999)
        self._by_spin.setFixedWidth(60)
        self._by_spin.setStyleSheet(_field_style())
        self._by_spin.valueChanged.connect(self._on_field_changed)
        r1.addWidget(self._by_spin)
        r1.addStretch()
        fl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(4)
        r2.addWidget(_make_dim_label("W:"))
        self._bw_spin = QSpinBox()
        self._bw_spin.setRange(1, 9999)
        self._bw_spin.setFixedWidth(60)
        self._bw_spin.setStyleSheet(_field_style())
        self._bw_spin.valueChanged.connect(self._on_field_changed)
        r2.addWidget(self._bw_spin)
        r2.addWidget(_make_dim_label("H:"))
        self._bh_spin = QSpinBox()
        self._bh_spin.setRange(1, 9999)
        self._bh_spin.setFixedWidth(60)
        self._bh_spin.setStyleSheet(_field_style())
        self._bh_spin.valueChanged.connect(self._on_field_changed)
        r2.addWidget(self._bh_spin)
        r2.addStretch()
        fl.addLayout(r2)

        self._fields_widget.setVisible(False)
        lay.addWidget(self._fields_widget)

        # Copy helpers
        copy_row = QHBoxLayout()
        copy_row.setSpacing(4)
        self._copy_prev_btn = _btn("Copy ◀ Prev", small=True)
        self._copy_prev_btn.setToolTip("Copy boxes from previous frame")
        self._copy_prev_btn.clicked.connect(self._copy_from_prev)
        self._copy_all_btn = _btn("Copy → All", small=True)
        self._copy_all_btn.setToolTip("Copy this frame's boxes to all frames")
        self._copy_all_btn.clicked.connect(self._copy_to_all)
        copy_row.addWidget(self._copy_prev_btn)
        copy_row.addWidget(self._copy_all_btn)
        copy_row.addStretch()
        lay.addLayout(copy_row)

        lay.addStretch()

    # -- public api --

    def load_object(self, obj: ObjectDefinition | None, project: Project | None):
        self._obj = obj
        self._project = project
        self._frame_idx = 0
        if obj:
            obj.sync_collision_frames(self._frame_count())
        self._refresh()

    # -- frame navigation --

    def _frame_count(self) -> int:
        if self._obj is None:
            return 0
        # Animation behavior type: frame count comes from the .ani export
        if self._obj.behavior_type == "Animation" and self._obj.ani_file_id and self._project:
            ani = self._project.get_animation_export(self._obj.ani_file_id)
            if ani:
                return max(ani.frame_count, 1)
        return max(len(self._obj.frames), 1)

    def _prev_frame(self):
        if self._frame_idx > 0:
            self._frame_idx -= 1
            self._refresh()

    def _next_frame(self):
        if self._frame_idx < self._frame_count() - 1:
            self._frame_idx += 1
            self._refresh()

    # -- refresh everything --

    def _refresh(self):
        if self._obj is None:
            self._preview.set_pixmap(None)
            self._preview.set_boxes([])
            self._box_list.clear()
            self._frame_label.setText("No object")
            self._fields_widget.setVisible(False)
            return

        self._obj.sync_collision_frames(self._frame_count())
        fc = self._frame_count()
        self._frame_idx = max(0, min(self._frame_idx, fc - 1))
        self._frame_label.setText(f"Frame {self._frame_idx + 1} / {fc}")
        self._prev_btn.setEnabled(self._frame_idx > 0)
        self._next_btn.setEnabled(self._frame_idx < fc - 1)

        # load sprite pixmap for current frame
        pm = None
        if self._project and self._obj.behavior_type == "Animation" and self._obj.ani_file_id:
            # Animation object: crop frame from spritesheet
            ani = self._project.get_animation_export(self._obj.ani_file_id)
            if ani and ani.spritesheet_path and self._project.project_folder:
                import os
                sheet_path = os.path.join(self._project.project_folder, "animations", ani.spritesheet_path)
                sheet_pm = QPixmap(sheet_path)
                if not sheet_pm.isNull():
                    cols = max(ani.sheet_width // max(ani.frame_width, 1), 1)
                    col = self._frame_idx % cols
                    row = self._frame_idx // cols
                    sx = col * ani.frame_width
                    sy = row * ani.frame_height
                    pm = sheet_pm.copy(sx, sy, ani.frame_width, ani.frame_height)
                    if pm.isNull():
                        pm = None
        elif self._project and self._obj.frames:
            # Regular sprite frames: look up registered image
            fidx = min(self._frame_idx, len(self._obj.frames) - 1)
            sf = self._obj.frames[fidx]
            if sf.image_id:
                img = self._project.get_image(sf.image_id)
                if img and img.path:
                    pm = QPixmap(img.path)
                    if pm.isNull():
                        pm = None
        # fallback: show blank area sized to object w/h
        if pm is None:
            pm = QPixmap(max(self._obj.width, 16), max(self._obj.height, 16))
            pm.fill(QColor(SURFACE))
        self._preview.set_pixmap(pm)

        # boxes for this frame
        boxes = self._obj.collision_boxes[self._frame_idx] if self._frame_idx < len(self._obj.collision_boxes) else []
        sel = min(self._box_list.currentRow(), len(boxes) - 1)
        self._preview.set_boxes(boxes, sel)
        self._refresh_box_list(sel)

    def _refresh_box_list(self, select: int = -1):
        if self._obj is None:
            self._box_list.clear()
            return
        boxes = self._current_boxes()
        self._box_list.blockSignals(True)
        self._box_list.clear()
        for i, cb in enumerate(boxes):
            self._box_list.addItem(f"Box {i}: ({cb.x},{cb.y}) {cb.width}×{cb.height}")
        self._box_list.blockSignals(False)
        if 0 <= select < len(boxes):
            self._box_list.setCurrentRow(select)
        self._on_box_selected(self._box_list.currentRow())

    def _current_boxes(self) -> list[CollisionBox]:
        if self._obj is None or self._frame_idx >= len(self._obj.collision_boxes):
            return []
        return self._obj.collision_boxes[self._frame_idx]

    # -- box operations --

    def _add_box(self):
        if self._obj is None:
            return
        self._obj.sync_collision_frames(self._frame_count())
        # default box centered on object — use ani frame size for Animation types
        obj_w, obj_h = self._obj.width, self._obj.height
        if self._obj.behavior_type == "Animation" and self._obj.ani_file_id and self._project:
            ani = self._project.get_animation_export(self._obj.ani_file_id)
            if ani:
                obj_w, obj_h = ani.frame_width, ani.frame_height
        bw = max(obj_w // 2, 8)
        bh = max(obj_h // 2, 8)
        bx = (obj_w - bw) // 2
        by = (obj_h - bh) // 2
        cb = CollisionBox(x=bx, y=by, width=bw, height=bh)
        self._obj.collision_boxes[self._frame_idx].append(cb)
        self._refresh_box_list(len(self._obj.collision_boxes[self._frame_idx]) - 1)
        self._preview.set_boxes(self._current_boxes(), self._box_list.currentRow())
        self.changed.emit()

    def _del_box(self):
        if self._obj is None:
            return
        boxes = self._current_boxes()
        row = self._box_list.currentRow()
        if 0 <= row < len(boxes):
            boxes.pop(row)
            new_sel = min(row, len(boxes) - 1)
            self._refresh_box_list(new_sel)
            self._preview.set_boxes(self._current_boxes(), new_sel)
            self.changed.emit()

    def _on_box_selected(self, row: int):
        boxes = self._current_boxes()
        if 0 <= row < len(boxes):
            self._suppress = True
            cb = boxes[row]
            self._bx_spin.setValue(cb.x)
            self._by_spin.setValue(cb.y)
            self._bw_spin.setValue(cb.width)
            self._bh_spin.setValue(cb.height)
            self._suppress = False
            self._fields_widget.setVisible(True)
            self._preview.set_selected(row)
        else:
            self._fields_widget.setVisible(False)
            self._preview.set_selected(-1)

    def _on_field_changed(self):
        if self._suppress or self._obj is None:
            return
        boxes = self._current_boxes()
        row = self._box_list.currentRow()
        if 0 <= row < len(boxes):
            cb = boxes[row]
            cb.x = self._bx_spin.value()
            cb.y = self._by_spin.value()
            cb.width = self._bw_spin.value()
            cb.height = self._bh_spin.value()
            self._refresh_box_list(row)
            self._preview.set_boxes(self._current_boxes(), row)
            self.changed.emit()

    def _on_box_dragged(self):
        """Called when user drags a box in the preview canvas."""
        row = self._preview._selected
        boxes = self._current_boxes()
        if 0 <= row < len(boxes):
            if self._box_list.currentRow() != row:
                self._box_list.setCurrentRow(row)
            self._suppress = True
            cb = boxes[row]
            self._bx_spin.setValue(cb.x)
            self._by_spin.setValue(cb.y)
            self._bw_spin.setValue(cb.width)
            self._bh_spin.setValue(cb.height)
            self._suppress = False
            # refresh list text
            self._box_list.blockSignals(True)
            item = self._box_list.item(row)
            if item:
                item.setText(f"Box {row}: ({cb.x},{cb.y}) {cb.width}×{cb.height}")
            self._box_list.blockSignals(False)
            self.changed.emit()

    # -- copy helpers --

    def _copy_from_prev(self):
        if self._obj is None or self._frame_idx <= 0:
            return
        import json
        prev = self._obj.collision_boxes[self._frame_idx - 1]
        clones = [CollisionBox.from_dict(cb.to_dict()) for cb in prev]
        self._obj.collision_boxes[self._frame_idx] = clones
        self._refresh_box_list(0 if clones else -1)
        self._preview.set_boxes(self._current_boxes(), self._box_list.currentRow())
        self.changed.emit()

    def _copy_to_all(self):
        if self._obj is None:
            return
        import json
        src = self._obj.collision_boxes[self._frame_idx]
        for i in range(len(self._obj.collision_boxes)):
            if i != self._frame_idx:
                self._obj.collision_boxes[i] = [CollisionBox.from_dict(cb.to_dict()) for cb in src]
        self.changed.emit()


# -- Objects Tab ---------------------------------------------------------------

class ObjectsTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Project | None = None
        self._scene: Scene | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        self._header = header
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("OBJECTS")
        title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        desc = QLabel("Define objects, frames, and behaviors. Place instances per scene.")
        desc.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        hl.addWidget(title)
        hl.addSpacing(16)
        hl.addWidget(desc)
        hl.addStretch()
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; width: 1px; }}")

        # Left: object def list
        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(240)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        self._left_panel = left
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        obj_title = QLabel("OBJECT DEFS")
        obj_title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        lv.addWidget(obj_title)

        self.def_list = QListWidget()
        self.def_list.setStyleSheet(_list_style())
        self.def_list.currentRowChanged.connect(self._on_def_selected)
        lv.addWidget(self.def_list)

        def_btns = QHBoxLayout()
        def_btns.setSpacing(4)
        add_def_btn = _btn("+ Add", accent=True, small=True)
        add_def_btn.clicked.connect(self._add_def)
        dup_def_btn = _btn("[D]", small=True)
        dup_def_btn.setToolTip("Duplicate")
        dup_def_btn.setFixedWidth(36)
        dup_def_btn.clicked.connect(self._dup_def)
        del_def_btn = _btn("x", danger=True, small=True)
        del_def_btn.setFixedWidth(32)
        del_def_btn.clicked.connect(self._del_def)
        def_btns.addWidget(add_def_btn)
        def_btns.addWidget(dup_def_btn)
        def_btns.addWidget(del_def_btn)
        def_btns.addStretch()
        lv.addLayout(def_btns)
        splitter.addWidget(left)

        # Middle: object def editor
        self.def_editor = ObjectDefEditor()
        self.def_editor.changed.connect(self._on_def_changed)
        self.def_editor.setEnabled(False)
        splitter.addWidget(self.def_editor)

        # Right: collision editor
        self.collision_editor = CollisionEditorPanel()
        self.collision_editor.setMinimumWidth(240)
        self.collision_editor.setMaximumWidth(360)
        self.collision_editor.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        self.collision_editor.changed.connect(self._on_collision_changed)
        self._right_panel = self.collision_editor
        splitter.addWidget(self.collision_editor)
        splitter.setSizes([210, 500, 280])
        root.addWidget(splitter)

    # -- Object def operations -------------------------------------------------

    def _refresh_def_list(self):
        if self._project is None:
            return
        self.def_list.blockSignals(True)
        self.def_list.clear()
        for od in self._project.object_defs:
            item = QListWidgetItem(od.name)
            if od.behavior_type == "VNCharacter":
                item.setForeground(QColor("#f59e0b"))
            self.def_list.addItem(item)
        self.def_list.blockSignals(False)

    def _on_def_selected(self, row: int):
        if self._project is None or row < 0 or row >= len(self._project.object_defs):
            self.def_editor.setEnabled(False)
            self.collision_editor.load_object(None, None)
            return
        self.def_editor.setEnabled(True)
        self.def_editor.load_object(self._project.object_defs[row], self._project)
        self.collision_editor.load_object(self._project.object_defs[row], self._project)

    def _on_def_changed(self):
        self._refresh_def_list()
        self._update_collision_editor()
        self.changed.emit()

    def _add_def(self):
        if self._project is None:
            return
        self._project.object_defs.append(ObjectDefinition())
        self._refresh_def_list()
        self.def_list.setCurrentRow(len(self._project.object_defs) - 1)
        self.changed.emit()

    def _dup_def(self):
        if self._project is None:
            return
        row = self.def_list.currentRow()
        if row < 0 or row >= len(self._project.object_defs):
            return
        import json
        orig = self._project.object_defs[row]
        clone = ObjectDefinition.from_dict(json.loads(json.dumps(orig.to_dict())))
        import uuid
        clone.id = str(uuid.uuid4())[:8]
        clone.name = clone.name + " Copy"
        self._project.object_defs.insert(row + 1, clone)
        self._refresh_def_list()
        self.def_list.setCurrentRow(row + 1)
        self.changed.emit()

    def _del_def(self):
        if self._project is None:
            return
        row = self.def_list.currentRow()
        if 0 <= row < len(self._project.object_defs):
            self._project.object_defs.pop(row)
            self._refresh_def_list()
            new = min(row, len(self._project.object_defs) - 1)
            if new >= 0:
                self.def_list.setCurrentRow(new)
            else:
                self.def_editor.setEnabled(False)
            self.changed.emit()

    # -- Collision editor callback ------------------------------------------------

    def _on_collision_changed(self):
        self.changed.emit()

    def _update_collision_editor(self):
        """Feed the currently selected object def to the collision editor."""
        if self._project is None:
            self.collision_editor.load_object(None, None)
            return
        row = self.def_list.currentRow()
        if 0 <= row < len(self._project.object_defs):
            self.collision_editor.load_object(self._project.object_defs[row], self._project)
        else:
            self.collision_editor.load_object(None, None)

    # -- Public API ------------------------------------------------------------

    def restyle(self, c: dict):
        self._header.setStyleSheet(f"background: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};")
        self._left_panel.setStyleSheet(f"background: {c['PANEL']}; border-right: 1px solid {c['BORDER']};")
        self._right_panel.setStyleSheet(f"background: {c['PANEL']}; border-left: 1px solid {c['BORDER']};")
        list_style = f"""
            QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                border-radius: 4px; color: {c['TEXT']}; outline: none; }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; border-bottom: 1px solid {c['BORDER']}; }}
            QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
        """
        self.def_list.setStyleSheet(list_style)

    def load_project(self, project: Project):
        self._project = project
        self._refresh_def_list()
        if project.object_defs:
            self.def_list.setCurrentRow(0)
        else:
            self.def_editor.setEnabled(False)
            self.collision_editor.load_object(None, None)

    def load_scene(self, scene: Scene, project: Project):
        self._scene = scene
        self._project = project

    def save_scene(self, scene: Scene):
        pass
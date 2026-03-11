# ===== FILE: tab_objects.py =====

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator -- Objects Tab
Object definition editor (frames, behaviors, VNCharacter config) + per-scene placed instances.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QSplitter, QSizePolicy, QAbstractItemView,
    QColorDialog, QDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from models import (
    Project, Scene, ObjectDefinition, SpriteFrame, Behavior,
    BehaviorAction, PlacedObject
)
# We import the action components from tab_editor to ensure the action lists are identical
from tab_editor import (
    ACTION_PALETTE, ACTION_FIELDS, ActionDetailPanel, ActionPickerDialog,
    TriggerPickerDialog, _action_summary, OBJECT_TRIGGERS, BUTTON_TRIGGERS, BUTTON_OPTIONS
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
BEHAVIOR_TYPES = ["default", "VNCharacter", "GUI_Label", "GUI_Button", "GUI_Panel", "Animation","Camera"]


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


# -- Action editor (uses editor_tab's system) ----------------------------------

class ActionEditor(QWidget):
    """Wrapper that uses ActionDetailPanel from editor_tab"""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action: BehaviorAction | None = None
        self._project: Project | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        layout.addWidget(_section("ACTION PARAMETERS"))
        layout.addWidget(_divider())
        
        self.detail_panel = ActionDetailPanel()
        self.detail_panel.changed.connect(self._emit)
        layout.addWidget(self.detail_panel)

    def _emit(self):
        self.changed.emit()

    def load_action(self, action: BehaviorAction, project: Project):
        self._action = action
        self._project = project
        self.detail_panel.load(action, project)


# -- Behavior editor -----------------------------------------------------------

class BehaviorEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._behavior: Behavior | None = None
        self._project: Project | None = None
        self._suppress = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_section("BEHAVIOR"))
        layout.addWidget(_divider())

        trig_lbl = QLabel("Trigger:")
        trig_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        layout.addWidget(trig_lbl)

        trig_row = QHBoxLayout()
        trig_row.setSpacing(6)
        self._trigger_label = QLabel("—")
        self._trigger_label.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
        self._trigger_change_btn = _btn("change", small=True)
        self._trigger_change_btn.setEnabled(False)
        self._trigger_change_btn.clicked.connect(self._change_trigger)
        trig_row.addWidget(self._trigger_label, stretch=1)
        trig_row.addWidget(self._trigger_change_btn)
        layout.addLayout(trig_row)

        # Button field row (on_button_pressed/held/released)
        self._button_row = QWidget()
        br2 = QHBoxLayout(self._button_row)
        br2.setContentsMargins(0, 0, 0, 0)
        br2.setSpacing(8)
        btn_lbl = QLabel("Button:")
        btn_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.button_combo = QComboBox()
        self.button_combo.setStyleSheet(_field_style())
        for b in BUTTON_OPTIONS:
            self.button_combo.addItem(b)
        self.button_combo.currentTextChanged.connect(self._on_button_changed)
        br2.addWidget(btn_lbl)
        br2.addWidget(self.button_combo)
        br2.addStretch()
        self._button_row.setVisible(False)
        layout.addWidget(self._button_row)

        self._frame_row = QWidget()
        fr = QHBoxLayout(self._frame_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(8)
        fc_lbl = QLabel("Frame count:")
        fc_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.frame_count_spin = QSpinBox()
        self.frame_count_spin.setRange(1, 99999)
        self.frame_count_spin.setValue(60)
        self.frame_count_spin.setStyleSheet(_field_style())
        self.frame_count_spin.valueChanged.connect(self._on_frame_count_changed)
        self.frame_sec_lbl = QLabel("~1.00s at 60fps")
        self.frame_sec_lbl.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        fr.addWidget(fc_lbl)
        fr.addWidget(self.frame_count_spin)
        fr.addWidget(self.frame_sec_lbl)
        fr.addStretch()
        self._frame_row.setVisible(False)
        layout.addWidget(self._frame_row)

        self._bool_row = QWidget()
        br = QHBoxLayout(self._bool_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(8)
        bv_lbl = QLabel("Variable:")
        bv_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.bool_var_combo = QComboBox()
        self.bool_var_combo.setStyleSheet(_field_style())
        self.bool_var_combo.currentTextChanged.connect(self._emit)
        br.addWidget(bv_lbl)
        br.addWidget(self.bool_var_combo)
        br.addStretch()
        self._bool_row.setVisible(False)
        layout.addWidget(self._bool_row)

        self._input_row = QWidget()
        ir = QHBoxLayout(self._input_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.setSpacing(8)
        ia_lbl = QLabel("Action:")
        ia_lbl.setStyleSheet(f"color: {DIM}; font-size: 12px;")
        self.input_action_combo = QComboBox()
        self.input_action_combo.setStyleSheet(_field_style())
        self.input_action_combo.currentTextChanged.connect(self._emit)
        ir.addWidget(ia_lbl)
        ir.addWidget(self.input_action_combo)
        ir.addStretch()
        self._input_row.setVisible(False)
        layout.addWidget(self._input_row)

        layout.addWidget(_section("ACTIONS"))

        act_btn_row = QHBoxLayout()
        act_btn_row.setSpacing(4)
        add_act_btn = _btn("+ Add Action", accent=True, small=True)
        add_act_btn.clicked.connect(self._add_action)
        del_act_btn = _btn("x", danger=True, small=True)
        del_act_btn.setFixedWidth(32)
        del_act_btn.clicked.connect(self._del_action)
        act_btn_row.addWidget(add_act_btn)
        act_btn_row.addWidget(del_act_btn)
        act_btn_row.addStretch()
        layout.addLayout(act_btn_row)

        self.action_list = QListWidget()
        self.action_list.setStyleSheet(_list_style())
        self.action_list.setFixedHeight(100)
        self.action_list.currentRowChanged.connect(self._on_action_selected)
        layout.addWidget(self.action_list)

        self.action_editor = ActionEditor()
        self.action_editor.changed.connect(self._on_action_changed)
        self.action_editor.setVisible(False)
        layout.addWidget(self.action_editor)

        self._layout = layout

    def _change_trigger(self):
        if self._behavior is None:
            return
        dlg = TriggerPickerDialog(OBJECT_TRIGGERS, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        code = dlg.selected_trigger()
        if not code:
            return
        self._behavior.trigger = code
        self._update_trigger_label(code)
        self._update_button_row(code)
        self._frame_row.setVisible(code in ("on_frame", "on_timer"))
        self._bool_row.setVisible(code in ("on_true", "on_false"))
        self._input_row.setVisible(code == "on_input")
        self._emit()

    def _update_trigger_label(self, code: str):
        tmap = {tup[0]: tup[1] for tup in OBJECT_TRIGGERS}
        self._trigger_label.setText(tmap.get(code, code))

    def _update_button_row(self, code: str):
        is_btn = code in BUTTON_TRIGGERS
        self._button_row.setVisible(is_btn)
        if is_btn and self._behavior:
            self._suppress = True
            idx = self.button_combo.findText(self._behavior.button or "cross")
            self.button_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._suppress = False

    def _on_button_changed(self, value: str):
        if self._suppress or self._behavior is None:
            return
        self._behavior.button = value
        self._emit()

    def _on_trigger_changed(self, trigger: str):
        # kept for internal visibility row updates only
        code = trigger
        self._frame_row.setVisible(code in ("on_frame", "on_timer"))
        self._bool_row.setVisible(code in ("on_true", "on_false"))
        self._input_row.setVisible(code == "on_input")
        self._emit()

    def _on_frame_count_changed(self, v: int):
        self.frame_sec_lbl.setText(f"~{v/60:.2f}s at 60fps")
        self._emit()

    def _emit(self):
        if self._suppress or self._behavior is None:
            return
        b = self._behavior
        b.frame_count = self.frame_count_spin.value()
        b.bool_var = self.bool_var_combo.currentText()
        b.input_action_name = self.input_action_combo.currentText()
        if b.trigger in BUTTON_TRIGGERS:
            b.button = self.button_combo.currentText()
        self.changed.emit()

    def _add_action(self):
        if self._behavior is None or self._project is None:
            return
        # This uses the ActionPickerDialog from tab_editor, so the list is identical
        dlg = ActionPickerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        action_type = dlg.selected_action_type()
        if not action_type:
            return
        new_action = BehaviorAction(action_type=action_type)
        self._behavior.actions.append(new_action)
        self._refresh_action_list()
        self.action_list.setCurrentRow(len(self._behavior.actions) - 1)
        self.changed.emit()

    def _del_action(self):
        if self._behavior is None:
            return
        row = self.action_list.currentRow()
        if 0 <= row < len(self._behavior.actions):
            self._behavior.actions.pop(row)
            self._refresh_action_list()
            self.action_editor.setVisible(False)
            self.changed.emit()

    def _refresh_action_list(self):
        if self._behavior is None:
            return
        self.action_list.blockSignals(True)
        self.action_list.clear()
        for i, a in enumerate(self._behavior.actions):
            self.action_list.addItem(f"{i+1:02d}. {_action_summary(a)}")
        self.action_list.blockSignals(False)

    def _on_action_selected(self, row: int):
        if self._behavior is None or row < 0 or row >= len(self._behavior.actions):
            self.action_editor.setVisible(False)
            return
        self.action_editor.load_action(self._behavior.actions[row], self._project)
        self.action_editor.setVisible(True)

    def _on_action_changed(self):
        row = self.action_list.currentRow()
        if self._behavior and 0 <= row < len(self._behavior.actions):
            self.action_list.item(row).setText(f"{row+1:02d}. {_action_summary(self._behavior.actions[row])}")
        self.changed.emit()

    def load_behavior(self, behavior: Behavior, project: Project):
        self._behavior = behavior
        self._project = project
        self._suppress = True

        self.bool_var_combo.clear()
        for v in project.game_data.variables:
            if v.var_type == "bool":
                self.bool_var_combo.addItem(v.name)

        self.input_action_combo.clear()
        for ia in project.game_data.input_actions:
            self.input_action_combo.addItem(ia.name)

        self._trigger_change_btn.setEnabled(True)
        self._update_trigger_label(behavior.trigger)
        self._update_button_row(behavior.trigger)
        self._frame_row.setVisible(behavior.trigger in ("on_frame", "on_timer"))
        self._bool_row.setVisible(behavior.trigger in ("on_true", "on_false"))
        self._input_row.setVisible(behavior.trigger == "on_input")

        self.frame_count_spin.setValue(behavior.frame_count)
        self.frame_sec_lbl.setText(f"~{behavior.frame_count/60:.2f}s at 60fps")
        bi = self.bool_var_combo.findText(behavior.bool_var)
        if bi >= 0:
            self.bool_var_combo.setCurrentIndex(bi)
        ii = self.input_action_combo.findText(getattr(behavior, "input_action_name", ""))
        if ii >= 0:
            self.input_action_combo.setCurrentIndex(ii)

        self._refresh_action_list()
        self.action_editor.setVisible(False)
        self._suppress = False


# -- Object definition editor --------------------------------------------------

class ObjectDefEditor(QWidget):
    changed = pyqtSignal()

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
        beh_btn_row = QHBoxLayout()
        beh_btn_row.setSpacing(4)
        add_beh_btn = _btn("+ Behavior", accent=True, small=True)
        add_beh_btn.clicked.connect(self._add_behavior)
        del_beh_btn = _btn("x", danger=True, small=True)
        del_beh_btn.setFixedWidth(32)
        del_beh_btn.clicked.connect(self._del_behavior)
        beh_btn_row.addWidget(add_beh_btn)
        beh_btn_row.addWidget(del_beh_btn)
        beh_btn_row.addStretch()
        self._layout.addLayout(beh_btn_row)

        self.behavior_list = QListWidget()
        self.behavior_list.setStyleSheet(_list_style())
        self.behavior_list.setFixedHeight(90)
        self.behavior_list.currentRowChanged.connect(self._on_behavior_selected)
        self._layout.addWidget(self.behavior_list)

        self.behavior_editor = BehaviorEditor()
        self.behavior_editor.changed.connect(self._on_behavior_changed)
        self.behavior_editor.setVisible(False)
        self._layout.addWidget(self.behavior_editor)

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
        o.width = self.width_spin.value()
        o.height = self.height_spin.value()
        o.visible_default = self.visible_check.isChecked()
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
        # Camera fields
        o.camera_bounds_enabled = self.cam_bounds_check.isChecked()
        o.camera_bounds_width = self.cam_w_spin.value()
        o.camera_bounds_height = self.cam_h_spin.value()
        o.camera_follow_lag = self.cam_lag_spin.value()
        self.changed.emit()

    def _on_behavior_type_changed(self, btype: str):
        if self._obj is not None and not self._suppress:
            self._obj.behavior_type = btype
            self.changed.emit()
        self._vnchar_group.setVisible(btype == "VNCharacter")
        is_gui = btype.startswith("GUI_")
        self._gui_group.setVisible(is_gui)
        self._ani_group.setVisible(btype == "Animation")

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

    def _add_behavior(self):
        if self._obj is None:
            return
        self._obj.behaviors.append(Behavior())
        self._refresh_behavior_list()
        self.behavior_list.setCurrentRow(len(self._obj.behaviors) - 1)
        self.changed.emit()

    def _del_behavior(self):
        if self._obj is None:
            return
        row = self.behavior_list.currentRow()
        if 0 <= row < len(self._obj.behaviors):
            self._obj.behaviors.pop(row)
            self._refresh_behavior_list()
            self.behavior_editor.setVisible(False)
            self.changed.emit()

    def _refresh_behavior_list(self):
        if self._obj is None:
            return
        self.behavior_list.blockSignals(True)
        self.behavior_list.clear()
        tmap = {tup[0]: tup[1] for tup in OBJECT_TRIGGERS}
        for b in self._obj.behaviors:
            label = tmap.get(b.trigger, b.trigger)
            if b.trigger in BUTTON_TRIGGERS and b.button:
                label = f"{label}: {b.button}"
            self.behavior_list.addItem(label)
        self.behavior_list.blockSignals(False)

    def _on_behavior_selected(self, row: int):
        if self._obj is None or row < 0 or row >= len(self._obj.behaviors):
            self.behavior_editor.setVisible(False)
            return
        self.behavior_editor.load_behavior(self._obj.behaviors[row], self._project)
        self.behavior_editor.setVisible(True)

    def _on_behavior_changed(self):
        self._refresh_behavior_list()
        self.changed.emit()

    # -- Public ----------------------------------------------------------------

    def load_object(self, obj: ObjectDefinition, project: Project):
        self._obj = obj
        self._project = project
        self._suppress = True

        self.name_edit.setText(obj.name)
        self.width_spin.setValue(obj.width)
        self.height_spin.setValue(obj.height)
        self.visible_check.setChecked(obj.visible_default)

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

        self._refresh_frame_list()
        self._update_fps_label()
        self._refresh_behavior_list()
        self._frame_editor.setVisible(False)
        self.behavior_editor.setVisible(False)

        self._suppress = False


# -- Objects Tab ---------------------------------------------------------------

class ObjectsTab(QWidget):
    changed = pyqtSignal()

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

        # Right: placed instances
        right = QWidget()
        right.setMinimumWidth(200)
        right.setMaximumWidth(280)
        right.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        self._right_panel = right
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.setSpacing(6)

        inst_title = QLabel("PLACED IN SCENE")
        inst_title.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        rv.addWidget(inst_title)

        self.inst_list = QListWidget()
        self.inst_list.setStyleSheet(_list_style())
        self.inst_list.currentRowChanged.connect(self._on_inst_selected)
        rv.addWidget(self.inst_list)

        inst_btns = QHBoxLayout()
        inst_btns.setSpacing(4)
        add_inst_btn = _btn("+ Place", accent=True, small=True)
        add_inst_btn.clicked.connect(self._add_instance)
        del_inst_btn = _btn("x", danger=True, small=True)
        del_inst_btn.setFixedWidth(32)
        del_inst_btn.clicked.connect(self._del_instance)
        inst_btns.addWidget(add_inst_btn)
        inst_btns.addWidget(del_inst_btn)
        inst_btns.addStretch()
        rv.addLayout(inst_btns)

        inst_def_lbl = _make_dim_label("Object def:")
        self.inst_def_combo = QComboBox()
        self.inst_def_combo.setStyleSheet(_field_style())
        self.inst_def_combo.currentIndexChanged.connect(self._on_inst_def_changed)

        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        self.inst_x = QSpinBox()
        self.inst_x.setRange(-9999, 9999)
        self.inst_x.setFixedWidth(70)
        self.inst_x.setStyleSheet(_field_style())
        self.inst_x.valueChanged.connect(self._on_inst_changed)
        self.inst_y = QSpinBox()
        self.inst_y.setRange(-9999, 9999)
        self.inst_y.setFixedWidth(70)
        self.inst_y.setStyleSheet(_field_style())
        self.inst_y.valueChanged.connect(self._on_inst_changed)
        pos_row.addWidget(_make_dim_label("X:"))
        pos_row.addWidget(self.inst_x)
        pos_row.addWidget(_make_dim_label("Y:"))
        pos_row.addWidget(self.inst_y)
        pos_row.addStretch()

        self.inst_visible = QCheckBox("Visible")
        self.inst_visible.setStyleSheet(_field_style())
        self.inst_visible.setChecked(True)
        self.inst_visible.stateChanged.connect(self._on_inst_changed)

        self._inst_editor_widget = QWidget()
        iew = QVBoxLayout(self._inst_editor_widget)
        iew.setContentsMargins(0, 0, 0, 0)
        iew.addWidget(inst_def_lbl)
        iew.addWidget(self.inst_def_combo)
        iew.addLayout(pos_row)
        iew.addWidget(self.inst_visible)
        self._inst_editor_widget.setEnabled(False)

        rv.addWidget(self._inst_editor_widget)
        rv.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([210, 500, 220])
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
            return
        self.def_editor.setEnabled(True)
        self.def_editor.load_object(self._project.object_defs[row], self._project)

    def _on_def_changed(self):
        self._refresh_def_list()
        self._refresh_inst_def_combo()
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

    # -- Placed instance operations --------------------------------------------

    def _refresh_inst_def_combo(self):
        if self._project is None:
            return
        self.inst_def_combo.blockSignals(True)
        self.inst_def_combo.clear()
        self.inst_def_combo.addItem("-- none --", None)
        for od in self._project.object_defs:
            self.inst_def_combo.addItem(od.name, od.id)
        self.inst_def_combo.blockSignals(False)

    def _refresh_inst_list(self):
        if self._scene is None or self._project is None:
            return
        self.inst_list.blockSignals(True)
        self.inst_list.clear()
        for po in self._scene.placed_objects:
            od = self._project.get_object_def(po.object_def_id)
            label = f"{od.name if od else '?'}  ({po.x}, {po.y})"
            self.inst_list.addItem(label)
        self.inst_list.blockSignals(False)

    def _on_inst_selected(self, row: int):
        if self._scene is None or row < 0 or row >= len(self._scene.placed_objects):
            self._inst_editor_widget.setEnabled(False)
            return
        po = self._scene.placed_objects[row]
        self._suppress = True
        for i in range(self.inst_def_combo.count()):
            if self.inst_def_combo.itemData(i) == po.object_def_id:
                self.inst_def_combo.setCurrentIndex(i)
                break
        self.inst_x.setValue(po.x)
        self.inst_y.setValue(po.y)
        self.inst_visible.setChecked(po.visible)
        self._suppress = False
        self._inst_editor_widget.setEnabled(True)

    def _on_inst_def_changed(self):
        if self._suppress or self._scene is None:
            return
        row = self.inst_list.currentRow()
        if 0 <= row < len(self._scene.placed_objects):
            self._scene.placed_objects[row].object_def_id = self.inst_def_combo.currentData() or ""
            self._refresh_inst_list()
            self.changed.emit()

    def _on_inst_changed(self):
        if self._suppress or self._scene is None:
            return
        row = self.inst_list.currentRow()
        if 0 <= row < len(self._scene.placed_objects):
            po = self._scene.placed_objects[row]
            po.x = self.inst_x.value()
            po.y = self.inst_y.value()
            po.visible = self.inst_visible.isChecked()
            self._refresh_inst_list()
            self.changed.emit()

    def _add_instance(self):
        if self._scene is None:
            return
        po = PlacedObject()
        if self._project and self._project.object_defs:
            po.object_def_id = self._project.object_defs[0].id
        self._scene.placed_objects.append(po)
        self._refresh_inst_list()
        self.inst_list.setCurrentRow(len(self._scene.placed_objects) - 1)
        self.changed.emit()

    def _del_instance(self):
        if self._scene is None:
            return
        row = self.inst_list.currentRow()
        if 0 <= row < len(self._scene.placed_objects):
            self._scene.placed_objects.pop(row)
            self._refresh_inst_list()
            self._inst_editor_widget.setEnabled(False)
            self.changed.emit()

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
        self.inst_list.setStyleSheet(list_style)

    def load_project(self, project: Project):
        self._project = project
        self._refresh_def_list()
        self._refresh_inst_def_combo()
        if project.object_defs:
            self.def_list.setCurrentRow(0)
        else:
            self.def_editor.setEnabled(False)

    def load_scene(self, scene: Scene, project: Project):
        self._scene = scene
        self._project = project
        self._refresh_inst_def_combo()
        self._refresh_inst_list()
        self._inst_editor_widget.setEnabled(False)
        if self._scene.placed_objects:
            self.inst_list.setCurrentRow(0)

    def save_scene(self, scene: Scene):
        pass

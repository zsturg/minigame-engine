# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — 3D Maps Tab
Wolf3D-style raycaster map editor.
Paint walls on a 2D grid from above; preview renders the 3D view.

Layout:
    Left   — Tools + tile palette + objects list (230px fixed)
    Center — Paintable grid (scrollable)
    Right  — Inspector: map settings + object inspector + 3D preview (280px fixed)
"""

from __future__ import annotations
import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSpinBox, QComboBox,
    QCheckBox, QButtonGroup, QAbstractButton, QColorDialog,
    QGroupBox, QListWidget, QListWidgetItem, QDoubleSpinBox,
    QLineEdit, QInputDialog,
)
from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal
from PySide6.QtGui import (
    QColor, QPixmap, QPainter, QPen, QBrush, QPolygon,
    QMouseEvent, QPaintEvent, QWheelEvent,
)

from models import Project, MapData, PlacedObject, ObjectDefinition, Scene

# ─────────────────────────────────────────────────────────────
#  COLOURS  (match the rest of the editor)
# ─────────────────────────────────────────────────────────────

DARK       = "#0f0f12"
PANEL      = "#16161c"
SURFACE    = "#1e1e28"
SURFACE2   = "#26263a"
BORDER     = "#2e2e42"
ACCENT     = "#7c6aff"
ACCENT2    = "#ff6a9b"
TEXT       = "#e8e6f0"
TEXT_DIM   = "#7a7890"
TEXT_MUTED = "#4a4860"
SUCCESS    = "#4ade80"
WARNING    = "#facc15"
DANGER     = "#f87171"

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────

CELL_MIN   = 8    # minimum editor cell px
CELL_MAX   = 64   # maximum editor cell px
CELL_DEFAULT = 24 # default editor cell px

TILE_EMPTY  = 0   # empty space
TILE_SOLID  = 1   # solid colour wall
# anything >= 2 is a texture index (1-based into registered images)

TOOL_PAINT  = "paint"
TOOL_ERASE  = "erase"
TOOL_SPAWN  = "spawn"
TOOL_FILL   = "fill"
TOOL_OBJECT = "object"

# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _label(text: str, dim: bool = False, small: bool = False) -> QLabel:
    lbl = QLabel(text)
    color = TEXT_DIM if dim else TEXT
    size  = "10px" if small else "11px"
    lbl.setStyleSheet(f"color: {color}; font-size: {size};")
    return lbl

def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; "
        f"letter-spacing: 1.5px; padding: 8px 8px 4px 8px;"
    )
    return lbl

def _divider() -> QFrame:
    d = QFrame()
    d.setFrameShape(QFrame.Shape.HLine)
    d.setFixedHeight(1)
    d.setStyleSheet(f"background: {BORDER}; border: none;")
    return d

def _small_btn(text: str, tooltip: str = "", accent: bool = False,
               danger: bool = False, checked_style: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(26)
    btn.setMinimumWidth(26)
    btn.setToolTip(tooltip)
    if checked_style:
        btn.setCheckable(True)
    base_bg  = ACCENT if accent else (DANGER if danger else SURFACE2)
    hover_bg = "#6458e0" if accent else ("#e05555" if danger else BORDER)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {base_bg}; color: {TEXT}; border: 1px solid {BORDER};
            border-radius: 4px; padding: 0 8px; font-size: 11px;
        }}
        QPushButton:hover {{ background: {hover_bg}; }}
        QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
    """)
    return btn

def _color_btn(color: str) -> QPushButton:
    """A small square button that shows a colour swatch."""
    btn = QPushButton()
    btn.setFixedSize(22, 22)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {color}; border: 1px solid {BORDER};
            border-radius: 3px;
        }}
        QPushButton:hover {{ border-color: {ACCENT}; }}
    """)
    return btn




# ─────────────────────────────────────────────────────────────
#  GRID WIDGET  (the paintable canvas)
# ─────────────────────────────────────────────────────────────

class MapGridWidget(QWidget):
    """
    Draws the 2D map grid and handles mouse painting.
    Emits map_changed whenever a cell is edited.
    """
    map_changed = Signal()

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data  = map_data
        self._scene: Scene | None = None
        self.cell_px   = CELL_DEFAULT   # display size of each cell in pixels
        self.tool      = TOOL_PAINT
        self.paint_value = TILE_SOLID   # what we paint (0=empty,1=solid,2+=texture)
        self.selected_object_id: str = ""  # instance_id of the currently selected PlacedObject
        self._painting = False
        self._last_cell: tuple[int, int] | None = None

        self.setMouseTracking(True)
        self._hover: tuple[int, int] | None = None
        self._update_size()

    # ── size ─────────────────────────────────────────────────
    def _update_size(self):
        w = self.map_data.width  * self.cell_px
        h = self.map_data.height * self.cell_px
        self.setFixedSize(w, h)

    def set_cell_px(self, px: int):
        self.cell_px = max(CELL_MIN, min(CELL_MAX, px))
        self._update_size()
        self.update()

    def set_map(self, map_data: MapData, scene: Scene | None = None):
        self.map_data = map_data
        self._scene = scene
        self._update_size()
        self.update()

    # ── painting ─────────────────────────────────────────────
    def _cell_at(self, pos: QPoint) -> tuple[int, int] | None:
        col = pos.x() // self.cell_px
        row = pos.y() // self.cell_px
        if 0 <= col < self.map_data.width and 0 <= row < self.map_data.height:
            return col, row
        return None

    def _apply_tool(self, col: int, row: int):
        if self.tool == TOOL_PAINT:
            self.map_data.set(col, row, self.paint_value)
            self.map_changed.emit()
            self.update()
        elif self.tool == TOOL_ERASE:
            self.map_data.set(col, row, TILE_EMPTY)
            self.map_changed.emit()
            self.update()
        elif self.tool == TOOL_SPAWN:
            self.map_data.spawn_x = col
            self.map_data.spawn_y = row
            self.map_changed.emit()
            self.update()
        elif self.tool == TOOL_FILL:
            self.map_data.flood_fill(col, row, self.paint_value)
            self.map_changed.emit()
            self.update()
        elif self.tool == TOOL_OBJECT:
            # Move the selected object to the clicked cell
            if self.selected_object_id and self._scene:
                for po in self._scene.placed_objects:
                    if (po.instance_id == self.selected_object_id
                            and getattr(po, "is_3d", False)
                            and not getattr(po, "hud_mode", False)):
                        po.grid_x = col
                        po.grid_y = row
                        self.map_changed.emit()
                        self.update()
                        break

    # ── mouse events ─────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._painting = True
            cell = self._cell_at(e.pos())
            if cell:
                self._last_cell = cell
                self._apply_tool(*cell)

    def mouseMoveEvent(self, e: QMouseEvent):
        cell = self._cell_at(e.pos())
        self._hover = cell
        if self._painting and cell and cell != self._last_cell:
            # Fill and Object tools only trigger once per click, not on drag
            if self.tool not in (TOOL_FILL, TOOL_OBJECT):
                self._last_cell = cell
                self._apply_tool(*cell)
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._painting = False
            self._last_cell = None

    def wheelEvent(self, e: QWheelEvent):
        # Ctrl+Wheel to zoom
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 4 if e.angleDelta().y() > 0 else -4
            self.set_cell_px(self.cell_px + delta)
        else:
            super().wheelEvent(e)

    # ── paint ─────────────────────────────────────────────────
    def paintEvent(self, e: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        cw = self.cell_px
        mw = self.map_data.width
        mh = self.map_data.height

        # Cell colours
        c_empty  = QColor(SURFACE)
        c_solid  = QColor("#3a5a8a")
        c_grid   = QColor(BORDER)
        c_spawn  = QColor(SUCCESS)
        c_hover  = QColor(255, 255, 255, 30)

        for row in range(mh):
            for col in range(mw):
                x = col * cw
                y = row * cw
                val = self.map_data.get(col, row)

                # Background
                if val == TILE_EMPTY:
                    p.fillRect(x, y, cw, cw, c_empty)
                elif val == TILE_SOLID:
                    p.fillRect(x, y, cw, cw, c_solid)
                else:
                    # Textured wall — show as slightly different blue for now
                    p.fillRect(x, y, cw, cw, QColor("#5a7aaa"))
                    # TODO: draw texture thumbnail once image registry is wired up

                # Spawn marker
                if col == self.map_data.spawn_x and row == self.map_data.spawn_y:
                    p.fillRect(x+2, y+2, cw-4, cw-4, c_spawn)
                    # Draw arrow showing spawn angle
                    if cw >= 12:
                        cx = x + cw // 2
                        cy = y + cw // 2
                        angle_rad = math.radians(self.map_data.spawn_angle)
                        dx = int(math.cos(angle_rad) * (cw // 3))
                        dy = int(math.sin(angle_rad) * (cw // 3))
                        p.setPen(QPen(QColor(DARK), 2))
                        p.drawLine(cx, cy, cx + dx, cy + dy)

                # Hover highlight
                if self._hover == (col, row):
                    p.fillRect(x, y, cw, cw, c_hover)

                # Grid lines
                p.setPen(QPen(c_grid, 1))
                p.drawRect(x, y, cw - 1, cw - 1)

        # ── Draw 3D object markers (sprite-type only) ────────
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c_obj      = QColor(WARNING)        # yellow diamond
        c_obj_sel  = QColor(ACCENT2)        # pink highlight for selected

        if self._scene:
            for po in self._scene.placed_objects:
                if not getattr(po, "is_3d", False):
                    continue
                if getattr(po, "hud_mode", False):
                    continue
                if not (0 <= po.grid_x < mw and 0 <= po.grid_y < mh):
                    continue

                cx = po.grid_x * cw + cw // 2
                cy = po.grid_y * cw + cw // 2

                is_selected = (po.instance_id == self.selected_object_id)
                color = c_obj_sel if is_selected else c_obj
                size = max(4, cw // 3)

                # Draw diamond
                diamond = QPolygon([
                    QPoint(cx, cy - size),
                    QPoint(cx + size, cy),
                    QPoint(cx, cy + size),
                    QPoint(cx - size, cy),
                ])
                p.setPen(QPen(QColor(DARK), 1))
                p.setBrush(QBrush(color))
                p.drawPolygon(diamond)

                # Selected ring
                if is_selected:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(color, 2))
                    p.drawEllipse(QPoint(cx, cy), size + 2, size + 2)

        p.end()


# ─────────────────────────────────────────────────────────────
#  3D PREVIEW WIDGET  (placeholder — draws a stub frame)
# ─────────────────────────────────────────────────────────────

class Preview3DWidget(QWidget):
    """
    Stub 3D preview.
    For now renders a placeholder showing floor/sky split and wall colour.
    Will be replaced with actual raycasting render in a later pass.
    """
    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data = map_data
        self.setFixedHeight(160)
        self.setMinimumWidth(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def refresh(self, map_data: MapData):
        self.map_data = map_data
        self.update()

    def paintEvent(self, e: QPaintEvent):
        p = QPainter(self)
        w = self.width()
        h = self.height()
        half = h // 2

        sky_c   = QColor(self.map_data.sky_color)
        floor_c = QColor(self.map_data.floor_color)
        wall_c  = QColor(self.map_data.wall_color)

        # Sky / ceiling
        p.fillRect(0, 0, w, half, sky_c)
        # Floor
        p.fillRect(0, half, w, h - half, floor_c)

        # Stub wall columns — very rough approximation, just visual chrome
        wall_h_ratio = 0.5
        wall_px = int(h * wall_h_ratio)
        wall_top = (h - wall_px) // 2
        col_w = 4
        for x in range(0, w, col_w):
            # Vary height slightly for depth feel
            vary = int((abs(x - w // 2) / (w // 2)) * wall_px * 0.3)
            wh = wall_px - vary
            wt = (h - wh) // 2
            p.fillRect(x, wt, col_w - 1, wh, wall_c)

        # Border
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRect(0, 0, w - 1, h - 1)

        # Label
        p.setPen(QColor(TEXT_DIM))
        p.drawText(QRect(0, h - 18, w, 18),
                   Qt.AlignmentFlag.AlignCenter, "3D Preview (stub)")
        p.end()


# ─────────────────────────────────────────────────────────────
#  TOOL BUTTON ROW
# ─────────────────────────────────────────────────────────────

class ToolButton(QPushButton):
    def __init__(self, label: str, tooltip: str, tool_id: str):
        super().__init__(label)
        self.tool_id = tool_id
        self.setCheckable(True)
        self.setToolTip(tooltip)
        self.setFixedHeight(30)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 4px; font-size: 11px; padding: 0 6px;
            }}
            QPushButton:hover   {{ background: {BORDER}; }}
            QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
        """)


# ─────────────────────────────────────────────────────────────
#  LEFT PANEL  — Tools + tile type palette + objects list
# ─────────────────────────────────────────────────────────────

class LeftPanel(QWidget):
    tool_changed       = Signal(str)
    paint_value_changed = Signal(int)
    object_selected    = Signal(str)       # emits object ID, or "" on deselection

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: Scene | None = None
        self._project: Project | None = None
        self.setFixedWidth(230)
        self.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        self._build()

    def set_scene(self, scene: Scene | None, project: Project | None):
        self._scene = scene
        self._project = project

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Tools ────────────────────────────────────────────
        v.addWidget(_section("TOOLS"))

        tool_row1 = QHBoxLayout()
        tool_row1.setContentsMargins(8, 0, 8, 4)
        tool_row1.setSpacing(4)

        tool_row2 = QHBoxLayout()
        tool_row2.setContentsMargins(8, 0, 8, 4)
        tool_row2.setSpacing(4)

        tool_row3 = QHBoxLayout()
        tool_row3.setContentsMargins(8, 0, 8, 4)
        tool_row3.setSpacing(4)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        self._tools = {
            TOOL_PAINT:  ToolButton("✏ Paint",  "Paint walls",           TOOL_PAINT),
            TOOL_ERASE:  ToolButton("◻ Erase",  "Erase to empty",        TOOL_ERASE),
            TOOL_FILL:   ToolButton("⬛ Fill",   "Flood fill region",     TOOL_FILL),
            TOOL_SPAWN:  ToolButton("⊕ Spawn",  "Place player spawn",    TOOL_SPAWN),
            TOOL_OBJECT: ToolButton("⊙ Object", "Place/move 3D objects", TOOL_OBJECT),
        }

        for btn in self._tools.values():
            self._tool_group.addButton(btn)
        self._tools[TOOL_PAINT].setChecked(True)

        tool_row1.addWidget(self._tools[TOOL_PAINT])
        tool_row1.addWidget(self._tools[TOOL_ERASE])
        tool_row2.addWidget(self._tools[TOOL_FILL])
        tool_row2.addWidget(self._tools[TOOL_SPAWN])
        tool_row3.addWidget(self._tools[TOOL_OBJECT])
        tool_row3.addStretch()

        v.addLayout(tool_row1)
        v.addLayout(tool_row2)
        v.addLayout(tool_row3)

        self._tool_group.buttonClicked.connect(self._on_tool_clicked)

        v.addWidget(_divider())

        # ── Tile type ────────────────────────────────────────
        v.addWidget(_section("TILE TYPE"))

        tile_w = QWidget()
        tile_w.setStyleSheet(f"background: {PANEL};")
        tile_v = QVBoxLayout(tile_w)
        tile_v.setContentsMargins(8, 4, 8, 8)
        tile_v.setSpacing(4)

        self._tile_group = QButtonGroup(self)
        self._tile_group.setExclusive(True)

        self._btn_solid = ToolButton("⬛ Solid Wall",    "Untextured solid wall",  "solid")
        self._btn_tex   = ToolButton("🖼 Textured Wall", "Wall with image texture", "textured")
        self._tile_group.addButton(self._btn_solid)
        self._tile_group.addButton(self._btn_tex)
        self._btn_solid.setChecked(True)

        tile_v.addWidget(self._btn_solid)
        tile_v.addWidget(self._btn_tex)

        # Texture picker (only active when Textured Wall selected)
        tex_row = QHBoxLayout()
        tex_row.setSpacing(4)
        tex_row.addWidget(_label("Texture:", dim=True, small=True))
        self._tex_combo = QComboBox()
        self._tex_combo.setEnabled(False)
        self._tex_combo.setStyleSheet(f"""
            QComboBox {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                selection-background-color: {ACCENT};
            }}
        """)
        self._tex_combo.addItem("(no textures registered)")
        tex_row.addWidget(self._tex_combo, stretch=1)
        tile_v.addLayout(tex_row)

        v.addWidget(tile_w)

        self._tile_group.buttonClicked.connect(self._on_tile_type_changed)
        self._tex_combo.currentIndexChanged.connect(self._on_tex_changed)

        v.addWidget(_divider())

        # ── Zoom ─────────────────────────────────────────────
        v.addWidget(_section("ZOOM"))

        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(8, 0, 8, 8)
        zoom_row.setSpacing(4)

        self._zoom_out = _small_btn("−", "Zoom out (Ctrl+Scroll)")
        self._zoom_in  = _small_btn("+", "Zoom in  (Ctrl+Scroll)")
        self._zoom_lbl = _label("24px", dim=True, small=True)

        zoom_row.addWidget(self._zoom_out)
        zoom_row.addWidget(self._zoom_in)
        zoom_row.addWidget(self._zoom_lbl)
        zoom_row.addStretch()
        v.addLayout(zoom_row)

        v.addWidget(_divider())

        # ── Objects ──────────────────────────────────────────
        v.addWidget(_section("OBJECTS"))

        obj_btn_row = QHBoxLayout()
        obj_btn_row.setContentsMargins(8, 0, 8, 4)
        obj_btn_row.setSpacing(4)

        self._btn_add_obj = _small_btn("+", "Add new 3D object", accent=True)
        self._btn_del_obj = _small_btn("−", "Delete selected object", danger=True)
        obj_btn_row.addWidget(self._btn_add_obj)
        obj_btn_row.addWidget(self._btn_del_obj)
        obj_btn_row.addStretch()
        v.addLayout(obj_btn_row)

        self._obj_list = QListWidget()
        self._obj_list.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; font-size: 11px; outline: none;
            }}
            QListWidget::item {{
                padding: 3px 6px;
            }}
            QListWidget::item:selected {{
                background: {ACCENT}; color: white;
            }}
            QListWidget::item:hover {{
                background: {SURFACE2};
            }}
        """)
        self._obj_list.setFixedHeight(120)

        obj_list_wrap = QWidget()
        obj_list_wrap.setStyleSheet(f"background: {PANEL};")
        olw = QVBoxLayout(obj_list_wrap)
        olw.setContentsMargins(8, 0, 8, 8)
        olw.addWidget(self._obj_list)
        v.addWidget(obj_list_wrap)

        self._btn_add_obj.clicked.connect(self._on_add_object)
        self._btn_del_obj.clicked.connect(self._on_del_object)
        self._obj_list.currentRowChanged.connect(self._on_obj_list_changed)

        v.addStretch()

    # ── slots ─────────────────────────────────────────────────
    def _on_tool_clicked(self, btn: QAbstractButton):
        self.tool_changed.emit(btn.tool_id)

    def _on_tile_type_changed(self, btn: QAbstractButton):
        is_tex = (btn == self._btn_tex)
        self._tex_combo.setEnabled(is_tex)
        if not is_tex:
            self.paint_value_changed.emit(TILE_SOLID)
        else:
            self._on_tex_changed(self._tex_combo.currentIndex())

    def _on_tex_changed(self, idx: int):
        if self._btn_tex.isChecked() and idx >= 0:
            # texture index: 2 + combo index (0-based → stored as 2+)
            self.paint_value_changed.emit(2 + idx)

    def populate_textures(self, image_names: list[str]):
        self._tex_combo.blockSignals(True)
        self._tex_combo.clear()
        if image_names:
            for name in image_names:
                self._tex_combo.addItem(name)
        else:
            self._tex_combo.addItem("(no textures registered)")
            self._btn_tex.setEnabled(False)
        self._tex_combo.blockSignals(False)

    def set_zoom_label(self, px: int):
        self._zoom_lbl.setText(f"{px}px")

    # ── object list ───────────────────────────────────────────

    def _get_3d_objects(self) -> list[PlacedObject]:
        """Return the is_3d placed objects in the current scene."""
        if self._scene is None:
            return []
        return [po for po in self._scene.placed_objects if getattr(po, "is_3d", False)]

    def _on_add_object(self):
        if self._scene is None or self._project is None:
            return
        if not self._project.object_defs:
            return
        names = [od.name for od in self._project.object_defs]
        name, ok = QInputDialog.getItem(
            self, "Add 3D Object", "Choose object definition:", names, 0, False)
        if not ok:
            return
        idx = names.index(name)
        od = self._project.object_defs[idx]
        po = PlacedObject(
            object_def_id=od.id,
            is_3d=True,
            grid_x=1,
            grid_y=1,
        )
        self._scene.placed_objects.append(po)
        self.refresh_objects()
        # Select the newly added object
        objs_3d = self._get_3d_objects()
        self._obj_list.setCurrentRow(len(objs_3d) - 1)

    def _on_del_object(self):
        if self._scene is None:
            return
        row = self._obj_list.currentRow()
        objs_3d = self._get_3d_objects()
        if 0 <= row < len(objs_3d):
            self._scene.placed_objects.remove(objs_3d[row])
            self.refresh_objects()
            self.object_selected.emit("")

    def _on_obj_list_changed(self, row: int):
        objs_3d = self._get_3d_objects()
        if 0 <= row < len(objs_3d):
            self.object_selected.emit(objs_3d[row].instance_id)
        else:
            self.object_selected.emit("")

    def refresh_objects(self):
        """Rebuild the object list from scene.placed_objects (is_3d only)."""
        objs_3d = self._get_3d_objects()

        prev_id = ""
        row = self._obj_list.currentRow()
        if 0 <= row < len(objs_3d):
            prev_id = objs_3d[row].instance_id

        self._obj_list.blockSignals(True)
        self._obj_list.clear()
        restore_row = -1
        # Re-fetch after clear in case list was stale
        objs_3d = self._get_3d_objects()
        for i, po in enumerate(objs_3d):
            # Look up name from ObjectDefinition
            od = self._project.get_object_def(po.object_def_id) if self._project else None
            name = od.name if od else "(unknown)"
            prefix = "🖥" if getattr(po, "hud_mode", False) else "🎯"
            item = QListWidgetItem(f"{prefix} {name}")
            item.setData(Qt.ItemDataRole.UserRole, po.instance_id)
            self._obj_list.addItem(item)
            if po.instance_id == prev_id:
                restore_row = i
        if restore_row >= 0:
            self._obj_list.setCurrentRow(restore_row)
        self._obj_list.blockSignals(False)


# ─────────────────────────────────────────────────────────────
#  RIGHT PANEL  — Inspector + 3D preview
# ─────────────────────────────────────────────────────────────

class RightPanel(QWidget):
    map_settings_changed = Signal()

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data = map_data
        self._scene: Scene | None = None
        self._project: Project | None = None
        self._selected_obj: PlacedObject | None = None
        self._updating = False              # guard against feedback loops
        self.setFixedWidth(280)
        self.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        self._build()

    def set_scene(self, scene: Scene | None, project: Project | None):
        self._scene = scene
        self._project = project

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {PANEL}; }}")

        inner = QWidget()
        inner.setStyleSheet(f"background: {PANEL};")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(0)

        # ── Map Size ─────────────────────────────────────────
        iv.addWidget(_section("MAP SIZE"))

        size_w = QWidget()
        size_w.setStyleSheet(f"background: {PANEL};")
        sg = QVBoxLayout(size_w)
        sg.setContentsMargins(8, 4, 8, 8)
        sg.setSpacing(6)

        wr = QHBoxLayout()
        wr.addWidget(_label("Width:", dim=True, small=True))
        self._spin_w = QSpinBox()
        self._spin_w.setRange(4, 64)
        self._spin_w.setValue(self.map_data.width)
        self._spin_w.setStyleSheet(self._spin_style())
        wr.addWidget(self._spin_w)
        wr.addStretch()

        hr = QHBoxLayout()
        hr.addWidget(_label("Height:", dim=True, small=True))
        self._spin_h = QSpinBox()
        self._spin_h.setRange(4, 64)
        self._spin_h.setValue(self.map_data.height)
        self._spin_h.setStyleSheet(self._spin_style())
        hr.addWidget(self._spin_h)
        hr.addStretch()

        self._btn_apply_size = _small_btn("Apply", "Resize the map", accent=True)
        self._btn_apply_size.clicked.connect(self._on_apply_size)

        sg.addLayout(wr)
        sg.addLayout(hr)
        sg.addWidget(self._btn_apply_size)
        iv.addWidget(size_w)

        iv.addWidget(_divider())

        # ── Tile Settings ─────────────────────────────────────
        iv.addWidget(_section("TILE SETTINGS"))

        tile_w = QWidget()
        tile_w.setStyleSheet(f"background: {PANEL};")
        tg = QVBoxLayout(tile_w)
        tg.setContentsMargins(8, 4, 8, 8)
        tg.setSpacing(6)

        ts_row = QHBoxLayout()
        ts_row.addWidget(_label("Tile Size:", dim=True, small=True))
        self._combo_tilesize = QComboBox()
        self._combo_tilesize.addItems(["32", "64", "128"])
        self._combo_tilesize.setCurrentText(str(self.map_data.tile_size))
        self._combo_tilesize.setStyleSheet(self._combo_style())
        self._combo_tilesize.currentTextChanged.connect(self._on_tilesize_changed)
        ts_row.addWidget(self._combo_tilesize)
        ts_row.addStretch()

        wh_row = QHBoxLayout()
        wh_row.addWidget(_label("Wall Height:", dim=True, small=True))
        self._spin_wallh = QSpinBox()
        self._spin_wallh.setRange(16, 256)
        self._spin_wallh.setValue(self.map_data.wall_height)
        self._spin_wallh.setStyleSheet(self._spin_style())
        self._spin_wallh.valueChanged.connect(self._on_wallh_changed)
        wh_row.addWidget(self._spin_wallh)
        wh_row.addStretch()

        acc_row = QHBoxLayout()
        acc_row.addWidget(_label("Accuracy:", dim=True, small=True))
        self._combo_accuracy = QComboBox()
        self._combo_accuracy.setStyleSheet(self._combo_style())
        acc_labels = [
            "1 — Best", "2 — Very High", "3 — High",
            "4 — Medium", "5 — Low", "6 — Very Low", "7 — Fastest",
        ]
        for lbl in acc_labels:
            self._combo_accuracy.addItem(lbl)
        self._combo_accuracy.setCurrentIndex(max(0, min(6, self.map_data.accuracy - 1)))
        self._combo_accuracy.currentIndexChanged.connect(self._on_accuracy_changed)
        acc_row.addWidget(self._combo_accuracy, stretch=1)

        tg.addLayout(ts_row)
        tg.addLayout(wh_row)
        tg.addLayout(acc_row)
        iv.addWidget(tile_w)

        iv.addWidget(_divider())

        # ── Colours ───────────────────────────────────────────
        iv.addWidget(_section("COLOURS"))

        col_w = QWidget()
        col_w.setStyleSheet(f"background: {PANEL};")
        cg = QVBoxLayout(col_w)
        cg.setContentsMargins(8, 4, 8, 8)
        cg.setSpacing(6)

        self._floor_btn = _color_btn(self.map_data.floor_color)
        self._sky_btn   = _color_btn(self.map_data.sky_color)
        self._wall_btn  = _color_btn(self.map_data.wall_color)

        def _crow(label: str, btn: QPushButton) -> QHBoxLayout:
            row = QHBoxLayout()
            row.addWidget(_label(label, dim=True, small=True))
            row.addWidget(btn)
            row.addStretch()
            return row

        cg.addLayout(_crow("Floor:", self._floor_btn))
        cg.addLayout(_crow("Sky:",   self._sky_btn))
        cg.addLayout(_crow("Wall:",  self._wall_btn))

        self._floor_btn.clicked.connect(lambda: self._pick_color("floor"))
        self._sky_btn.clicked.connect(lambda:   self._pick_color("sky"))
        self._wall_btn.clicked.connect(lambda:  self._pick_color("wall"))

        iv.addWidget(col_w)

        iv.addWidget(_divider())

        # ── Render Flags ──────────────────────────────────────
        iv.addWidget(_section("RENDER FLAGS"))

        flags_w = QWidget()
        flags_w.setStyleSheet(f"background: {PANEL};")
        fg = QVBoxLayout(flags_w)
        fg.setContentsMargins(8, 4, 8, 8)
        fg.setSpacing(4)

        self._chk_floor   = QCheckBox("Enable Floor")
        self._chk_sky     = QCheckBox("Enable Sky")
        self._chk_shading = QCheckBox("Enable Shading")

        for chk in (self._chk_floor, self._chk_sky, self._chk_shading):
            chk.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            fg.addWidget(chk)

        self._chk_floor.setChecked(self.map_data.floor_on)
        self._chk_sky.setChecked(self.map_data.sky_on)
        self._chk_shading.setChecked(self.map_data.shading)

        self._chk_floor.toggled.connect(self._on_flags_changed)
        self._chk_sky.toggled.connect(self._on_flags_changed)
        self._chk_shading.toggled.connect(self._on_flags_changed)

        iv.addWidget(flags_w)

        iv.addWidget(_divider())

        # ── Skybox Image ─────────────────────────────────────
        iv.addWidget(_section("SKYBOX IMAGE"))

        skybox_w = QWidget()
        skybox_w.setStyleSheet(f"background: {PANEL};")
        skybox_g = QVBoxLayout(skybox_w)
        skybox_g.setContentsMargins(8, 4, 8, 8)
        skybox_g.setSpacing(6)

        skybox_g.addWidget(_label(
            "Full-screen background drawn behind walls.\n"
            "Best used with shading enabled.",
            dim=True, small=True,
        ))

        sb_row = QHBoxLayout()
        sb_row.addWidget(_label("Image:", dim=True, small=True))
        self._skybox_combo = QComboBox()
        self._skybox_combo.setStyleSheet(self._combo_style())
        self._skybox_combo.addItem("(none)")
        sb_row.addWidget(self._skybox_combo, stretch=1)
        skybox_g.addLayout(sb_row)

        self._skybox_combo.currentIndexChanged.connect(self._on_skybox_changed)

        iv.addWidget(skybox_w)

        iv.addWidget(_divider())

        # ── Player Spawn ──────────────────────────────────────
        iv.addWidget(_section("PLAYER SPAWN"))

        spawn_w = QWidget()
        spawn_w.setStyleSheet(f"background: {PANEL};")
        spg = QVBoxLayout(spawn_w)
        spg.setContentsMargins(8, 4, 8, 8)
        spg.setSpacing(6)

        sx_row = QHBoxLayout()
        sx_row.addWidget(_label("Col:", dim=True, small=True))
        self._spawn_x = QSpinBox()
        self._spawn_x.setRange(0, self.map_data.width - 1)
        self._spawn_x.setValue(self.map_data.spawn_x)
        self._spawn_x.setStyleSheet(self._spin_style())
        sx_row.addWidget(self._spawn_x)
        sx_row.addStretch()

        sy_row = QHBoxLayout()
        sy_row.addWidget(_label("Row:", dim=True, small=True))
        self._spawn_y = QSpinBox()
        self._spawn_y.setRange(0, self.map_data.height - 1)
        self._spawn_y.setValue(self.map_data.spawn_y)
        self._spawn_y.setStyleSheet(self._spin_style())
        sy_row.addWidget(self._spawn_y)
        sy_row.addStretch()

        sa_row = QHBoxLayout()
        sa_row.addWidget(_label("Angle:", dim=True, small=True))
        self._spawn_angle = QSpinBox()
        self._spawn_angle.setRange(0, 359)
        self._spawn_angle.setValue(self.map_data.spawn_angle)
        self._spawn_angle.setSuffix("°")
        self._spawn_angle.setStyleSheet(self._spin_style())
        sa_row.addWidget(self._spawn_angle)
        sa_row.addStretch()

        spg.addLayout(sx_row)
        spg.addLayout(sy_row)
        spg.addLayout(sa_row)

        self._spawn_x.valueChanged.connect(self._on_spawn_changed)
        self._spawn_y.valueChanged.connect(self._on_spawn_changed)
        self._spawn_angle.valueChanged.connect(self._on_spawn_changed)

        iv.addWidget(spawn_w)

        iv.addWidget(_divider())

        # ── Object Inspector ──────────────────────────────────
        self._obj_inspector = QWidget()
        self._obj_inspector.setStyleSheet(f"background: {PANEL};")
        self._obj_inspector.setVisible(False)

        oi_outer = QVBoxLayout(self._obj_inspector)
        oi_outer.setContentsMargins(0, 0, 0, 0)
        oi_outer.setSpacing(0)

        oi_outer.addWidget(_section("OBJECT INSPECTOR"))

        oi_w = QWidget()
        oi_w.setStyleSheet(f"background: {PANEL};")
        oi = QVBoxLayout(oi_w)
        oi.setContentsMargins(8, 4, 8, 8)
        oi.setSpacing(6)

        # Name (read-only — comes from ObjectDefinition)
        name_row = QHBoxLayout()
        name_row.addWidget(_label("Def:", dim=True, small=True))
        self._obj_def_label = QLabel("")
        self._obj_def_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        name_row.addWidget(self._obj_def_label, stretch=1)
        oi.addLayout(name_row)

        # Image (read-only — from ObjectDefinition's first frame)
        img_row = QHBoxLayout()
        img_row.addWidget(_label("Image:", dim=True, small=True))
        self._obj_image_label = QLabel("(none)")
        self._obj_image_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        img_row.addWidget(self._obj_image_label, stretch=1)
        oi.addLayout(img_row)

        # Type toggle (sprite vs HUD)
        type_row = QHBoxLayout()
        type_row.addWidget(_label("Type:", dim=True, small=True))
        self._obj_type_combo = QComboBox()
        self._obj_type_combo.setStyleSheet(self._combo_style())
        self._obj_type_combo.addItem("Sprite (Billboard)", "sprite")
        self._obj_type_combo.addItem("HUD (Screen)", "hud")
        type_row.addWidget(self._obj_type_combo, stretch=1)
        oi.addLayout(type_row)

        # ── Sprite fields ─────────────────────────────────────
        self._sprite_fields = QWidget()
        self._sprite_fields.setStyleSheet(f"background: {PANEL};")
        sf = QVBoxLayout(self._sprite_fields)
        sf.setContentsMargins(0, 4, 0, 0)
        sf.setSpacing(6)

        gx_row = QHBoxLayout()
        gx_row.addWidget(_label("Grid X:", dim=True, small=True))
        self._obj_grid_x = QSpinBox()
        self._obj_grid_x.setRange(0, 63)
        self._obj_grid_x.setStyleSheet(self._spin_style())
        gx_row.addWidget(self._obj_grid_x)
        gx_row.addStretch()

        gy_row = QHBoxLayout()
        gy_row.addWidget(_label("Grid Y:", dim=True, small=True))
        self._obj_grid_y = QSpinBox()
        self._obj_grid_y.setRange(0, 63)
        self._obj_grid_y.setStyleSheet(self._spin_style())
        gy_row.addWidget(self._obj_grid_y)
        gy_row.addStretch()

        ox_row = QHBoxLayout()
        ox_row.addWidget(_label("Offset X:", dim=True, small=True))
        self._obj_offset_x = QDoubleSpinBox()
        self._obj_offset_x.setRange(0.0, 1.0)
        self._obj_offset_x.setSingleStep(0.1)
        self._obj_offset_x.setDecimals(2)
        self._obj_offset_x.setStyleSheet(self._dspin_style())
        ox_row.addWidget(self._obj_offset_x)
        ox_row.addStretch()

        oy_row = QHBoxLayout()
        oy_row.addWidget(_label("Offset Y:", dim=True, small=True))
        self._obj_offset_y = QDoubleSpinBox()
        self._obj_offset_y.setRange(0.0, 1.0)
        self._obj_offset_y.setSingleStep(0.1)
        self._obj_offset_y.setDecimals(2)
        self._obj_offset_y.setStyleSheet(self._dspin_style())
        oy_row.addWidget(self._obj_offset_y)
        oy_row.addStretch()

        sc_row = QHBoxLayout()
        sc_row.addWidget(_label("Scale:", dim=True, small=True))
        self._obj_scale = QDoubleSpinBox()
        self._obj_scale.setRange(0.1, 10.0)
        self._obj_scale.setSingleStep(0.1)
        self._obj_scale.setDecimals(2)
        self._obj_scale.setStyleSheet(self._dspin_style())
        sc_row.addWidget(self._obj_scale)
        sc_row.addStretch()

        vo_row = QHBoxLayout()
        vo_row.addWidget(_label("V.Offset:", dim=True, small=True))
        self._obj_voffset = QDoubleSpinBox()
        self._obj_voffset.setRange(-10.0, 10.0)
        self._obj_voffset.setSingleStep(0.1)
        self._obj_voffset.setDecimals(2)
        self._obj_voffset.setStyleSheet(self._dspin_style())
        vo_row.addWidget(self._obj_voffset)
        vo_row.addStretch()

        self._obj_blocking = QCheckBox("Blocking")
        self._obj_blocking.setStyleSheet(f"color: {TEXT}; font-size: 11px;")

        sf.addLayout(gx_row)
        sf.addLayout(gy_row)
        sf.addLayout(ox_row)
        sf.addLayout(oy_row)
        sf.addLayout(sc_row)
        sf.addLayout(vo_row)
        sf.addWidget(self._obj_blocking)

        oi.addWidget(self._sprite_fields)

        # ── HUD fields ────────────────────────────────────────
        self._hud_fields = QWidget()
        self._hud_fields.setStyleSheet(f"background: {PANEL};")
        hf = QVBoxLayout(self._hud_fields)
        hf.setContentsMargins(0, 4, 0, 0)
        hf.setSpacing(6)

        hx_row = QHBoxLayout()
        hx_row.addWidget(_label("Screen X:", dim=True, small=True))
        self._obj_hud_x = QSpinBox()
        self._obj_hud_x.setRange(0, 960)
        self._obj_hud_x.setStyleSheet(self._spin_style())
        hx_row.addWidget(self._obj_hud_x)
        hx_row.addStretch()

        hy_row = QHBoxLayout()
        hy_row.addWidget(_label("Screen Y:", dim=True, small=True))
        self._obj_hud_y = QSpinBox()
        self._obj_hud_y.setRange(0, 544)
        self._obj_hud_y.setStyleSheet(self._spin_style())
        hy_row.addWidget(self._obj_hud_y)
        hy_row.addStretch()

        ha_row = QHBoxLayout()
        ha_row.addWidget(_label("Anchor:", dim=True, small=True))
        self._obj_hud_anchor = QComboBox()
        self._obj_hud_anchor.setStyleSheet(self._combo_style())
        for anchor in ("top_left", "top_right", "bottom_left", "bottom_right", "center"):
            self._obj_hud_anchor.addItem(anchor)
        ha_row.addWidget(self._obj_hud_anchor, stretch=1)

        hf.addLayout(hx_row)
        hf.addLayout(hy_row)
        hf.addLayout(ha_row)

        oi.addWidget(self._hud_fields)
        self._hud_fields.setVisible(False)

        # ── Common ────────────────────────────────────────────
        self._obj_visible = QCheckBox("Visible by default")
        self._obj_visible.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        oi.addWidget(self._obj_visible)

        oi_outer.addWidget(oi_w)

        iv.addWidget(self._obj_inspector)

        # ── Connect object inspector signals ──────────────────
        self._obj_type_combo.currentIndexChanged.connect(self._on_obj_type_changed)
        self._obj_grid_x.valueChanged.connect(self._on_obj_edited)
        self._obj_grid_y.valueChanged.connect(self._on_obj_edited)
        self._obj_offset_x.valueChanged.connect(self._on_obj_edited)
        self._obj_offset_y.valueChanged.connect(self._on_obj_edited)
        self._obj_scale.valueChanged.connect(self._on_obj_edited)
        self._obj_voffset.valueChanged.connect(self._on_obj_edited)
        self._obj_blocking.toggled.connect(self._on_obj_edited)
        self._obj_hud_x.valueChanged.connect(self._on_obj_edited)
        self._obj_hud_y.valueChanged.connect(self._on_obj_edited)
        self._obj_hud_anchor.currentIndexChanged.connect(self._on_obj_edited)
        self._obj_visible.toggled.connect(self._on_obj_edited)

        iv.addStretch()

        scroll.setWidget(inner)
        v.addWidget(scroll, stretch=1)

        # ── 3D Preview ────────────────────────────────────────
        v.addWidget(_divider())
        prev_label = _section("3D PREVIEW")
        v.addWidget(prev_label)

        self.preview = Preview3DWidget(self.map_data)
        v.addWidget(self.preview)

    # ── internal slots ────────────────────────────────────────
    def _spin_style(self) -> str:
        return f"""
            QSpinBox {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 4px; font-size: 11px;
            }}
        """

    def _dspin_style(self) -> str:
        return f"""
            QDoubleSpinBox {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 4px; font-size: 11px;
            }}
        """

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                selection-background-color: {ACCENT};
            }}
        """

    def _on_apply_size(self):
        self.map_data.resize(self._spin_w.value(), self._spin_h.value())
        # Update spawn spinbox ranges
        self._spawn_x.setMaximum(self.map_data.width - 1)
        self._spawn_y.setMaximum(self.map_data.height - 1)
        self.map_settings_changed.emit()

    def _on_tilesize_changed(self, text: str):
        self.map_data.tile_size = int(text)
        self.map_settings_changed.emit()

    def _on_wallh_changed(self, val: int):
        self.map_data.wall_height = val
        self.map_settings_changed.emit()

    def _on_accuracy_changed(self, idx: int):
        self.map_data.accuracy = idx + 1   # 0-based index → 1-based accuracy value
        self.map_settings_changed.emit()

    def _on_flags_changed(self):
        self.map_data.floor_on = self._chk_floor.isChecked()
        self.map_data.sky_on   = self._chk_sky.isChecked()
        self.map_data.shading  = self._chk_shading.isChecked()
        self.map_settings_changed.emit()

    def _on_skybox_changed(self, idx: int):
        if idx <= 0:
            self.map_data.skybox_image_id = ""
        else:
            self.map_data.skybox_image_id = self._skybox_combo.itemData(idx) or ""
        self.map_settings_changed.emit()

    def _on_spawn_changed(self):
        self.map_data.spawn_x     = self._spawn_x.value()
        self.map_data.spawn_y     = self._spawn_y.value()
        self.map_data.spawn_angle = self._spawn_angle.value()
        self.map_settings_changed.emit()

    def _pick_color(self, target: str):
        current = {
            "floor": self.map_data.floor_color,
            "sky":   self.map_data.sky_color,
            "wall":  self.map_data.wall_color,
        }[target]
        color = QColorDialog.getColor(QColor(current), self, f"Pick {target} colour")
        if color.isValid():
            hex_val = color.name()
            if target == "floor":
                self.map_data.floor_color = hex_val
                self._floor_btn.setStyleSheet(
                    self._floor_btn.styleSheet().replace(current, hex_val))
            elif target == "sky":
                self.map_data.sky_color = hex_val
                self._sky_btn.setStyleSheet(
                    self._sky_btn.styleSheet().replace(current, hex_val))
            elif target == "wall":
                self.map_data.wall_color = hex_val
                self._wall_btn.setStyleSheet(
                    self._wall_btn.styleSheet().replace(current, hex_val))
            self.map_settings_changed.emit()

    # ── Object inspector ──────────────────────────────────────
    def select_object(self, obj_id: str):
        """Populate inspector for the given PlacedObject instance_id."""
        self._selected_obj = None
        if self._scene:
            for po in self._scene.placed_objects:
                if po.instance_id == obj_id:
                    self._selected_obj = po
                    break

        if self._selected_obj is None:
            self.deselect_object()
            return

        self._obj_inspector.setVisible(True)
        self._populate_obj_inspector()

    def deselect_object(self):
        """Hide/clear the object inspector."""
        self._selected_obj = None
        self._obj_inspector.setVisible(False)

    def _populate_obj_inspector(self):
        """Fill all inspector widgets from self._selected_obj (a PlacedObject)."""
        po = self._selected_obj
        if po is None:
            return

        self._updating = True

        # Def name (read-only)
        od = self._project.get_object_def(po.object_def_id) if self._project else None
        self._obj_def_label.setText(od.name if od else "(unknown)")

        # Image label (read-only, from first frame of object def)
        img_name = "(none)"
        if od and od.frames and self._project:
            img = self._project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
            if img:
                img_name = img.name or img.path or "(image)"
        self._obj_image_label.setText(img_name)

        # Type toggle
        idx = 1 if getattr(po, "hud_mode", False) else 0
        self._obj_type_combo.setCurrentIndex(idx)
        self._sprite_fields.setVisible(not po.hud_mode)
        self._hud_fields.setVisible(po.hud_mode)

        # Sprite fields
        self._obj_grid_x.setMaximum(max(0, self.map_data.width - 1))
        self._obj_grid_y.setMaximum(max(0, self.map_data.height - 1))
        self._obj_grid_x.setValue(po.grid_x)
        self._obj_grid_y.setValue(po.grid_y)
        self._obj_offset_x.setValue(po.offset_x)
        self._obj_offset_y.setValue(po.offset_y)
        self._obj_scale.setValue(po.scale)
        self._obj_voffset.setValue(po.vertical_offset)
        self._obj_blocking.setChecked(po.blocking)

        # HUD fields
        self._obj_hud_x.setValue(po.hud_x)
        self._obj_hud_y.setValue(po.hud_y)
        anchor_idx = self._obj_hud_anchor.findText(po.hud_anchor)
        if anchor_idx >= 0:
            self._obj_hud_anchor.setCurrentIndex(anchor_idx)

        self._obj_visible.setChecked(po.visible)

        self._updating = False

    def _on_obj_type_changed(self, idx: int):
        is_sprite = (idx == 0)
        self._sprite_fields.setVisible(is_sprite)
        self._hud_fields.setVisible(not is_sprite)
        self._on_obj_edited()

    def _on_obj_edited(self):
        """Push all inspector widget values back to the selected PlacedObject."""
        if self._updating or self._selected_obj is None:
            return

        po = self._selected_obj
        po.hud_mode = (self._obj_type_combo.currentIndex() == 1)

        po.grid_x = self._obj_grid_x.value()
        po.grid_y = self._obj_grid_y.value()
        po.offset_x = self._obj_offset_x.value()
        po.offset_y = self._obj_offset_y.value()
        po.scale = self._obj_scale.value()
        po.vertical_offset = self._obj_voffset.value()
        po.blocking = self._obj_blocking.isChecked()

        po.hud_x = self._obj_hud_x.value()
        po.hud_y = self._obj_hud_y.value()
        po.hud_anchor = self._obj_hud_anchor.currentText()

        po.visible = self._obj_visible.isChecked()

        self.map_settings_changed.emit()

    def refresh_from_data(self):
        """Sync all inspector widgets from map_data (called after external changes)."""
        self._spin_w.blockSignals(True)
        self._spin_h.blockSignals(True)
        self._spin_w.setValue(self.map_data.width)
        self._spin_h.setValue(self.map_data.height)
        self._spin_w.blockSignals(False)
        self._spin_h.blockSignals(False)
        self._spawn_x.setMaximum(self.map_data.width - 1)
        self._spawn_y.setMaximum(self.map_data.height - 1)
        # Re-populate object inspector if one is selected
        if self._selected_obj:
            self._populate_obj_inspector()
        self.preview.refresh(self.map_data)


# ─────────────────────────────────────────────────────────────
#  MAIN TAB WIDGET
# ─────────────────────────────────────────────────────────────

class MapsTab3D(QWidget):
    """
    The 3D Maps tab.
    Connects left panel, grid, and right inspector together.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.mw       = main_window
        self._project: Project | None = None
        self._scene   = None
        self.map_data = MapData()
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left
        self._left = LeftPanel()
        self._left.tool_changed.connect(self._on_tool_changed)
        self._left.paint_value_changed.connect(self._on_paint_value_changed)
        self._left._zoom_in.clicked.connect(self._zoom_in)
        self._left._zoom_out.clicked.connect(self._zoom_out)
        self._left.object_selected.connect(self._on_object_selected)
        root.addWidget(self._left)

        # Center — scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {DARK}; border: none; }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background: {PANEL}; width: 8px; height: 8px;
            }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: {BORDER}; border-radius: 4px;
            }}
        """)

        self._grid = MapGridWidget(self.map_data)
        self._grid.map_changed.connect(self._on_map_changed)
        self._scroll.setWidget(self._grid)
        root.addWidget(self._scroll, stretch=1)

        # Right
        self._right = RightPanel(self.map_data)
        self._right.map_settings_changed.connect(self._on_settings_changed)
        root.addWidget(self._right)

    # ── public interface ──────────────────────────────────────
    def set_project(self, project: Project | None):
        self._project = project
        if project:
            self._populate_textures()

    def load_scene(self, scene):
        """Called when a 3D scene is selected in the editor."""
        self._scene   = scene
        self.map_data = scene.map_data
        self._grid.set_map(self.map_data, scene)
        self._right.map_data = self.map_data
        self._right.set_scene(scene, self._project)
        self._right.refresh_from_data()
        self._left.set_scene(scene, self._project)
        self._left.refresh_objects()
        self._right.deselect_object()
        self._grid.selected_object_id = ""
        self._populate_textures()

    def clear_scene(self):
        """Called when a non-3D scene is selected."""
        self._scene   = None
        self.map_data = MapData()
        self._grid.set_map(self.map_data, None)
        self._left.set_scene(None, self._project)
        self._left.refresh_objects()
        self._right.set_scene(None, self._project)
        self._right.deselect_object()
        self._grid.selected_object_id = ""

    def _populate_textures(self):
        if self._project:
            names = [img.name or img.path for img in self._project.images if img.path]
            self._left.populate_textures(names)
            # Populate skybox combo on right panel
            self._right._skybox_combo.blockSignals(True)
            self._right._skybox_combo.clear()
            self._right._skybox_combo.addItem("(none)")
            selected_idx = 0
            for i, img in enumerate(self._project.images):
                if img.path:
                    label = img.name or img.path
                    self._right._skybox_combo.addItem(label, img.id)
                    if img.id == self.map_data.skybox_image_id:
                        selected_idx = i + 1
            self._right._skybox_combo.setCurrentIndex(selected_idx)
            self._right._skybox_combo.blockSignals(False)

    # ── slots ─────────────────────────────────────────────────
    def _on_tool_changed(self, tool: str):
        self._grid.tool = tool

    def _on_paint_value_changed(self, val: int):
        self._grid.paint_value = val

    def _on_object_selected(self, obj_id: str):
        """Left panel selected/deselected an object."""
        self._grid.selected_object_id = obj_id
        self._grid.update()
        if obj_id:
            self._right.select_object(obj_id)
        else:
            self._right.deselect_object()

    def _on_map_changed(self):
        self._right.preview.refresh(self.map_data)
        # If grid moved an object, re-populate inspector to reflect new coords
        if self._right._selected_obj:
            self._right._populate_obj_inspector()
        # Refresh object list in case names changed
        self._left.refresh_objects()

    def _on_settings_changed(self):
        self._grid.set_map(self.map_data)
        self._right.refresh_from_data()
        self._right.preview.refresh(self.map_data)
        # Refresh grid to redraw object markers after inspector edits
        self._grid.update()
        # Refresh object list in case name/type changed
        self._left.refresh_objects()

    def _zoom_in(self):
        self._grid.set_cell_px(self._grid.cell_px + 4)
        self._left.set_zoom_label(self._grid.cell_px)

    def _zoom_out(self):
        self._grid.set_cell_px(self._grid.cell_px - 4)
        self._left.set_zoom_label(self._grid.cell_px)
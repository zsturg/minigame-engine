# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — 3D Maps Tab
Wolf3D-style raycaster map editor.
Paint walls on a 2D grid from above; preview renders the 3D view.

Layout:
    Left   — Tools + tile palette + objects list (300px fixed)
    Center — Paintable grid (scrollable)
    Right  — Inspector: map settings + object inspector + 3D preview (280px fixed)
"""

from __future__ import annotations
import math
import os

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
    QMouseEvent, QPaintEvent, QWheelEvent, QImage, QCursor,
)

from models import (
    Project, MapData, PlacedObject, ObjectDefinition, Scene, SceneComponent,
    TileMeta, TILE_META_DOOR, TILE_META_EXIT, TILE_META_TRIGGER, TILE_META_SWITCH,
    make_component,
)
from theme_utils import replace_widget_theme_colors

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


def _first_3d_animation_slot(project: Project | None, obj_def: ObjectDefinition | None):
    if not project or not obj_def or getattr(obj_def, "behavior_type", "") != "Animation":
        return None
    for slot in getattr(obj_def, "ani_slots", []) or []:
        slot_name = str(slot.get("name", "")).strip()
        ani_id = str(slot.get("ani_file_id", "")).strip()
        if not slot_name or not ani_id:
            continue
        ani = project.get_animation_export(ani_id)
        if ani:
            return slot_name, ani_id, ani
    return None


def _classify_3d_object_def(project: Project | None, obj_def: ObjectDefinition | None) -> tuple[str | None, str]:
    if not obj_def:
        return None, "missing object definition"
    btype = getattr(obj_def, "behavior_type", "") or "default"
    if btype in ("GUI_Panel", "GUI_Label", "GUI_Button", "Camera"):
        return None, f"{btype} objects cannot render as 3D billboards"
    if btype == "LayerAnimation":
        return None, "LayerAnimation objects are not yet supported in 3D billboards"
    if btype == "Animation":
        slot = _first_3d_animation_slot(project, obj_def)
        if slot is None:
            return None, "Animation objects need at least one valid animation slot"
        return "animation", slot[0]
    if not getattr(obj_def, "frames", []):
        return None, "object has no sprite frames"
    if not getattr(obj_def.frames[0], "image_id", ""):
        return None, "object has no valid first-frame image"
    return ("frame_anim" if len(obj_def.frames) > 1 else "static"), ""


def _3d_object_source_label(project: Project | None, obj_def: ObjectDefinition | None) -> str:
    kind, detail = _classify_3d_object_def(project, obj_def)
    if kind == "animation":
        slot = _first_3d_animation_slot(project, obj_def)
        if slot:
            slot_name, _ani_id, ani = slot
            ani_name = getattr(ani, "name", "") or slot_name
            return f'Animation: {ani_name} (slot "{slot_name}")'
        return "Animation"
    if obj_def and getattr(obj_def, "frames", []):
        image_id = getattr(obj_def.frames[0], "image_id", "") or ""
        reg = project.get_image(image_id) if (project and image_id) else None
        image_name = (reg.name or reg.path) if reg else "(missing image)"
        if kind == "frame_anim":
            return f"Frame 0: {image_name}"
        return image_name
    if detail:
        return f"(unsupported: {detail})"
    return "(none)"

TILE_EMPTY  = 0   # empty space
TILE_SOLID  = 1   # solid colour wall
# anything >= 2 is a texture index (1-based into registered images)

TOOL_PAINT  = "paint"
TOOL_ERASE  = "erase"
TOOL_SPAWN  = "spawn"
TOOL_FILL   = "fill"
TOOL_OBJECT = "object"
TOOL_TILE_META = "tile_meta"
TOOL_PATH = "path"


def _theme_snapshot():
    return {
        "DARK": DARK,
        "PANEL": PANEL,
        "SURFACE": SURFACE,
        "SURFACE2": SURFACE2,
        "BORDER": BORDER,
        "ACCENT": ACCENT,
        "ACCENT2": ACCENT2,
        "TEXT": TEXT,
        "TEXT_DIM": TEXT_DIM,
        "TEXT_MUTED": TEXT_MUTED,
        "SUCCESS": SUCCESS,
        "WARNING": WARNING,
        "DANGER": DANGER,
    }

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




TILE_META_LABELS = {
    TILE_META_DOOR: "Door",
    TILE_META_EXIT: "Exit",
    TILE_META_TRIGGER: "Trigger",
    TILE_META_SWITCH: "Switch",
}

TILE_META_OVERLAY_COLORS = {
    TILE_META_DOOR: "#7c6aff",
    TILE_META_EXIT: "#4ade80",
    TILE_META_TRIGGER: "#38bdf8",
    TILE_META_SWITCH: "#facc15",
}

TILE_META_BADGE_TEXT = {
    TILE_META_DOOR: "D",
    TILE_META_EXIT: "E",
    TILE_META_TRIGGER: "T",
    TILE_META_SWITCH: "S",
}


def _tile_meta_key(col: int, row: int) -> str:
    return f"{col},{row}"


def _tile_meta_default_for(meta_type: str) -> TileMeta:
    if meta_type == TILE_META_DOOR:
        return TileMeta(type=TILE_META_DOOR, state="closed")
    if meta_type == TILE_META_EXIT:
        return TileMeta(type=TILE_META_EXIT, state="", target_scene=0)
    if meta_type == TILE_META_TRIGGER:
        return TileMeta(type=TILE_META_TRIGGER, state="", tag="")
    if meta_type == TILE_META_SWITCH:
        return TileMeta(type=TILE_META_SWITCH, state="off", tag="")
    return TileMeta()


def _scene_path_components(scene: Scene | None) -> list[SceneComponent]:
    if scene is None:
        return []
    return [comp for comp in getattr(scene, "components", []) if comp.component_type == "Path"]


def _find_scene_path(scene: Scene | None, path_id: str) -> SceneComponent | None:
    path_id = str(path_id or "").strip()
    if scene is None or not path_id:
        return None
    for comp in _scene_path_components(scene):
        if getattr(comp, "id", "") == path_id:
            return comp
    return None


def _path_name(comp: SceneComponent | None) -> str:
    if comp is None:
        return ""
    name = str(comp.config.get("path_name", "") or "").strip()
    return name or "Path"


def _unique_path_name(scene: Scene | None, base_name: str) -> str:
    base = (base_name or "Path").strip() or "Path"
    taken = {_path_name(comp) for comp in _scene_path_components(scene)}
    if base not in taken:
        return base
    index = 2
    while f"{base} {index}" in taken:
        index += 1
    return f"{base} {index}"


def _map_tile_size(map_data: MapData) -> int:
    return max(1, int(getattr(map_data, "tile_size", 64) or 64))


def _grid_cell_to_world_point(map_data: MapData, col: int, row: int) -> dict[str, int]:
    tile = _map_tile_size(map_data)
    return {
        "x": col * tile + tile // 2,
        "y": row * tile + tile // 2,
        "cx1": 0,
        "cy1": 0,
        "cx2": 0,
        "cy2": 0,
    }


def _world_point_to_grid_cell(map_data: MapData, point: dict) -> tuple[int, int] | None:
    try:
        x = float(point.get("x", 0))
        y = float(point.get("y", 0))
    except Exception:
        return None
    tile = _map_tile_size(map_data)
    return int(x // tile), int(y // tile)


def _is_walkable_path_cell(map_data: MapData, col: int, row: int) -> bool:
    return 0 <= col < map_data.width and 0 <= row < map_data.height and map_data.get(col, row) == TILE_EMPTY


def _path_point_index_for_cell(map_data: MapData, points: list[dict], col: int, row: int) -> int:
    for idx, point in enumerate(points):
        cell = _world_point_to_grid_cell(map_data, point)
        if cell == (col, row):
            return idx
    return -1


# ─────────────────────────────────────────────────────────────
#  GRID WIDGET  (the paintable canvas)
# ─────────────────────────────────────────────────────────────

class MapGridWidget(QWidget):
    """
    Draws the 2D map grid and handles mouse painting.
    Emits map_changed whenever a cell is edited.
    """
    map_changed = Signal()
    cell_selected = Signal(int, int)
    cell_hovered = Signal(int, int)

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data  = map_data
        self._scene: Scene | None = None
        self.cell_px   = CELL_DEFAULT   # display size of each cell in pixels
        self.tool      = TOOL_PAINT
        self.paint_value = TILE_SOLID   # what we paint (0=empty,1=solid,2+=texture)
        self.tile_meta_type = TILE_META_DOOR
        self.selected_object_id: str = ""  # instance_id of the currently selected PlacedObject
        self.active_path_id: str = ""
        self.selected_cell: tuple[int, int] | None = None
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
        elif self.tool == TOOL_TILE_META:
            key = _tile_meta_key(col, row)
            existing = self.map_data.tile_meta.get(key)
            if existing is not None and existing.type == self.tile_meta_type:
                del self.map_data.tile_meta[key]
            else:
                meta = _tile_meta_default_for(self.tile_meta_type)
                if existing is not None:
                    if meta.type == TILE_META_EXIT:
                        meta.target_scene = existing.target_scene
                    if meta.type in (TILE_META_TRIGGER, TILE_META_SWITCH):
                        meta.tag = existing.tag
                    if meta.type == TILE_META_SWITCH and existing.type == TILE_META_SWITCH:
                        meta.state = existing.state or "off"
                    if meta.type == TILE_META_DOOR and existing.type == TILE_META_DOOR:
                        meta.state = existing.state or "closed"
                        meta.texture_image_id = existing.texture_image_id or ""
                if meta.type == TILE_META_DOOR:
                    self.map_data.set(col, row, TILE_SOLID)
                self.map_data.tile_meta[key] = meta
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
        elif self.tool == TOOL_PATH:
            comp = _find_scene_path(self._scene, self.active_path_id)
            if comp is None or not _is_walkable_path_cell(self.map_data, col, row):
                return
            points = comp.config.setdefault("points", [])
            existing_idx = _path_point_index_for_cell(self.map_data, points, col, row)
            if existing_idx >= 0:
                del points[existing_idx]
            else:
                points.append(_grid_cell_to_world_point(self.map_data, col, row))
            self.map_changed.emit()
            self.update()

    # ── mouse events ─────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._painting = True
            cell = self._cell_at(e.pos())
            if cell:
                self.selected_cell = cell
                self.cell_selected.emit(cell[0], cell[1])
                self._last_cell = cell
                self._apply_tool(*cell)

    def mouseMoveEvent(self, e: QMouseEvent):
        cell = self._cell_at(e.pos())
        if cell != self._hover:
            self._hover = cell
            if cell is not None:
                self.cell_hovered.emit(cell[0], cell[1])
        if self._painting and cell and cell != self._last_cell:
            # Fill, Meta, Object, and Path tools only trigger once per click, not on drag
            if self.tool not in (TOOL_FILL, TOOL_TILE_META, TOOL_OBJECT, TOOL_PATH):
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

                meta = self.map_data.tile_meta.get(_tile_meta_key(col, row))
                if meta is not None:
                    overlay = QColor(TILE_META_OVERLAY_COLORS.get(meta.type, ACCENT))
                    overlay.setAlpha(55)
                    p.fillRect(x + 2, y + 2, max(1, cw - 4), max(1, cw - 4), overlay)
                    if cw >= 16:
                        badge = QColor(TILE_META_OVERLAY_COLORS.get(meta.type, ACCENT))
                        badge.setAlpha(220)
                        badge_w = min(14, max(10, cw - 6))
                        p.fillRect(x + 2, y + 2, badge_w, badge_w, badge)
                        p.setPen(QColor(DARK))
                        p.drawText(QRect(x + 2, y + 2, badge_w, badge_w),
                                   Qt.AlignmentFlag.AlignCenter,
                                   TILE_META_BADGE_TEXT.get(meta.type, "?"))

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

                if self.selected_cell == (col, row):
                    p.setPen(QPen(QColor(ACCENT2), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(x + 1, y + 1, max(1, cw - 3), max(1, cw - 3))

        if self._scene:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for comp in _scene_path_components(self._scene):
                points = comp.config.get("points", []) or []
                is_active = (getattr(comp, "id", "") == self.active_path_id)
                line_color = QColor(ACCENT2 if is_active else TEXT_DIM)
                line_color.setAlpha(220 if is_active else 120)
                node_color = QColor(WARNING if is_active else ACCENT)
                node_color.setAlpha(230 if is_active else 170)
                start_color = QColor(SUCCESS if is_active else TEXT_DIM)
                end_color = QColor(ACCENT2 if is_active else TEXT_DIM)
                invalid_color = QColor(DANGER)

                cells: list[tuple[int, int] | None] = []
                valid_flags: list[bool] = []
                blocked_flags: list[bool] = []
                for point in points:
                    cell = _world_point_to_grid_cell(self.map_data, point)
                    if cell is None:
                        cells.append(None)
                        valid_flags.append(False)
                        blocked_flags.append(False)
                        continue
                    col2, row2 = cell
                    in_bounds = (0 <= col2 < mw and 0 <= row2 < mh)
                    cells.append(cell if in_bounds else None)
                    is_valid = in_bounds and _is_walkable_path_cell(self.map_data, col2, row2)
                    valid_flags.append(is_valid)
                    blocked_flags.append(in_bounds and not is_valid)

                p.setPen(QPen(line_color, 2 if is_active else 1))
                for idx in range(1, len(cells)):
                    prev_cell = cells[idx - 1]
                    cell = cells[idx]
                    if prev_cell is None or cell is None:
                        continue
                    if not valid_flags[idx - 1] or not valid_flags[idx]:
                        continue
                    x1 = prev_cell[0] * cw + cw // 2
                    y1 = prev_cell[1] * cw + cw // 2
                    x2 = cell[0] * cw + cw // 2
                    y2 = cell[1] * cw + cw // 2
                    p.drawLine(x1, y1, x2, y2)

                if comp.config.get("closed", False) and len(cells) > 1:
                    first_cell = cells[0]
                    last_cell = cells[-1]
                    if first_cell is not None and last_cell is not None and valid_flags[0] and valid_flags[-1]:
                        x1 = first_cell[0] * cw + cw // 2
                        y1 = first_cell[1] * cw + cw // 2
                        x2 = last_cell[0] * cw + cw // 2
                        y2 = last_cell[1] * cw + cw // 2
                        p.drawLine(x1, y1, x2, y2)

                for idx, cell in enumerate(cells):
                    if cell is None:
                        continue
                    cx = cell[0] * cw + cw // 2
                    cy = cell[1] * cw + cw // 2
                    radius = max(3, cw // 5)
                    if valid_flags[idx]:
                        fill = start_color if idx == 0 else (end_color if idx == len(cells) - 1 else node_color)
                        p.setPen(QPen(QColor(DARK), 1))
                        p.setBrush(QBrush(fill))
                        if idx == len(cells) - 1:
                            size = max(6, radius * 2)
                            p.drawRect(cx - size // 2, cy - size // 2, size, size)
                        else:
                            p.drawEllipse(QPoint(cx, cy), radius, radius)
                    elif blocked_flags[idx]:
                        span = max(4, cw // 4)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.setPen(QPen(invalid_color, 2))
                        p.drawLine(cx - span, cy - span, cx + span, cy + span)
                        p.drawLine(cx - span, cy + span, cx + span, cy - span)

                    if cw >= 18:
                        p.setPen(QColor(TEXT))
                        p.drawText(
                            QRect(cx - cw // 3, cy - cw // 3, (cw * 2) // 3, (cw * 2) // 3),
                            Qt.AlignmentFlag.AlignCenter,
                            str(idx + 1),
                        )

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
    """Lightweight in-editor 3D preview for raycast scenes."""
    _FOV_DEG = 60.0
    _BUTTON_W = 48
    _BUTTON_H = 22
    _BUTTON_GAP = 6

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data = map_data
        self._scene: Scene | None = None
        self._project: Project | None = None
        self._image_cache: dict[str, QImage | None] = {}
        self._texture_images: list[QImage | None] = []
        self._show_controls = False
        self._controls: list[tuple[str, QRect]] = []
        self._preview_x = 0.0
        self._preview_y = 0.0
        self._preview_angle = 0.0
        self.setFixedHeight(160)
        self.setMinimumWidth(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._reset_camera()

    def set_scene(self, scene: Scene | None, project: Project | None):
        scene_changed = scene is not self._scene
        self._scene = scene
        self._project = project
        self._texture_images = self._collect_texture_images()
        if scene_changed:
            self._reset_camera()
        self.update()

    def refresh(
        self,
        map_data: MapData,
        scene: Scene | None = None,
        project: Project | None = None,
    ):
        self.map_data = map_data
        if scene is not None or project is not None:
            self.set_scene(scene, project)
            return
        self._texture_images = self._collect_texture_images()
        self.update()

    def enterEvent(self, event):
        self._show_controls = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_controls = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            for name, rect in self._controls:
                if rect.contains(event.position().toPoint()):
                    self._activate_control(name)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _reset_camera(self):
        ts = max(1, int(getattr(self.map_data, "tile_size", 64) or 64))
        self._preview_x = (self.map_data.spawn_x + 0.5) * ts
        self._preview_y = (self.map_data.spawn_y + 0.5) * ts
        self._preview_angle = float(self.map_data.spawn_angle)

    def _collect_texture_images(self) -> list[QImage | None]:
        if not self._project:
            return []
        images: list[QImage | None] = []
        for reg in self._project.images:
            if reg.path:
                images.append(self._load_image(reg.path))
        return images

    def _load_image(self, path: str | None) -> QImage | None:
        if not path:
            return None
        if path in self._image_cache:
            return self._image_cache[path]
        img = QImage(path)
        self._image_cache[path] = None if img.isNull() else img
        return self._image_cache[path]

    def _image_for_registered_id(self, image_id: str) -> QImage | None:
        if not self._project or not image_id:
            return None
        reg = self._project.get_image(image_id)
        if not reg or not reg.path:
            return None
        return self._load_image(reg.path)

    def _animation_sheet_path(self, ani_export) -> str:
        if not ani_export:
            return ""
        sheet_paths = list(getattr(ani_export, "spritesheet_paths", []) or [])
        if not sheet_paths and getattr(ani_export, "spritesheet_path", ""):
            sheet_paths = [ani_export.spritesheet_path]
        if not sheet_paths:
            return ""
        sheet_path = sheet_paths[0]
        if os.path.isabs(sheet_path):
            return sheet_path
        if self._project and getattr(self._project, "project_folder", ""):
            return os.path.join(self._project.project_folder, "animations", sheet_path)
        return sheet_path

    def _image_for_animation_export(self, ani_export, frame_index: int = 0) -> QImage | None:
        if not ani_export:
            return None
        sheet_paths = list(getattr(ani_export, "spritesheet_paths", []) or [])
        if not sheet_paths and getattr(ani_export, "spritesheet_path", ""):
            sheet_paths = [ani_export.spritesheet_path]
        if not sheet_paths:
            return None
        fpg = int(getattr(ani_export, "frames_per_sheet", 0) or getattr(ani_export, "frame_count", 0) or 0)
        if fpg <= 0:
            fpg = int(getattr(ani_export, "frame_count", 0) or 1)
        frame_index = max(0, int(frame_index))
        sheet_idx = min(len(sheet_paths) - 1, frame_index // max(1, fpg))
        local_frame = frame_index - sheet_idx * max(1, fpg)
        sheet_path = sheet_paths[sheet_idx]
        if not os.path.isabs(sheet_path) and self._project and getattr(self._project, "project_folder", ""):
            sheet_path = os.path.join(self._project.project_folder, "animations", sheet_path)
        sheet = self._load_image(sheet_path)
        fw = int(getattr(ani_export, "frame_width", 0) or 0)
        fh = int(getattr(ani_export, "frame_height", 0) or 0)
        sw = int(getattr(ani_export, "sheet_width", 0) or (sheet.width() if sheet else 0) or 0)
        if sheet is None or sheet.width() <= 0 or sheet.height() <= 0 or fw <= 0 or fh <= 0 or sw <= 0:
            return None
        cols = max(1, sw // fw)
        col = local_frame % cols
        row = local_frame // cols
        return sheet.copy(col * fw, row * fh, fw, fh)

    def _initial_image_for_object_def(self, od: ObjectDefinition | None) -> QImage | None:
        kind, _detail = _classify_3d_object_def(self._project, od)
        if kind == "animation":
            slot = _first_3d_animation_slot(self._project, od)
            if slot:
                return self._image_for_animation_export(slot[2], 0)
            return None
        if od and getattr(od, "frames", []):
            return self._image_for_registered_id(getattr(od.frames[0], "image_id", "") or "")
        return None

    def _texture_for_cell_value(self, value: int) -> QImage | None:
        tex_idx = value - 2
        if tex_idx < 0 or tex_idx >= len(self._texture_images):
            return None
        return self._texture_images[tex_idx]

    def _tile_meta_at(self, col: int, row: int) -> TileMeta | None:
        return self.map_data.tile_meta.get(_tile_meta_key(col, row))

    def _door_closed(self, meta: TileMeta | None) -> bool:
        return bool(meta and meta.type == TILE_META_DOOR and (meta.state or "closed") != "open")

    def _is_solid(self, col: int, row: int) -> bool:
        if col < 0 or row < 0 or col >= self.map_data.width or row >= self.map_data.height:
            return True
        value = self.map_data.cells[row * self.map_data.width + col]
        if value == TILE_EMPTY:
            return False
        meta = self._tile_meta_at(col, row)
        if meta and meta.type == TILE_META_DOOR:
            return self._door_closed(meta)
        return True

    def _wall_image_for_cell(self, col: int, row: int, value: int) -> QImage | None:
        meta = self._tile_meta_at(col, row)
        if self._door_closed(meta):
            door_img = self._image_for_registered_id(getattr(meta, "texture_image_id", "") or "")
            if door_img is not None:
                return door_img
        if value >= 2:
            return self._texture_for_cell_value(value)
        return None

    def _raycast(self, angle_deg: float, max_dist: float) -> tuple[float, int, int, int, float]:
        rad = math.radians(angle_deg)
        dx = math.cos(rad)
        dy = math.sin(rad)
        px = self._preview_x
        py = self._preview_y
        tile = max(1, int(self.map_data.tile_size))
        map_x = int(px // tile)
        map_y = int(py // tile)
        delta_x = abs(tile / dx) if abs(dx) > 1e-8 else 1e30
        delta_y = abs(tile / dy) if abs(dy) > 1e-8 else 1e30

        if dx < 0:
            step_x = -1
            side_x = (px - map_x * tile) / max(abs(dx), 1e-8)
        else:
            step_x = 1
            side_x = (((map_x + 1) * tile) - px) / max(abs(dx), 1e-8)
        if dy < 0:
            step_y = -1
            side_y = (py - map_y * tile) / max(abs(dy), 1e-8)
        else:
            step_y = 1
            side_y = (((map_y + 1) * tile) - py) / max(abs(dy), 1e-8)

        side = 0
        dist = max_dist
        hit_x = map_x
        hit_y = map_y
        while True:
            if side_x < side_y:
                dist = side_x
                side_x += delta_x
                map_x += step_x
                side = 0
            else:
                dist = side_y
                side_y += delta_y
                map_y += step_y
                side = 1
            if dist > max_dist:
                break
            if self._is_solid(map_x, map_y):
                hit_x = map_x
                hit_y = map_y
                break

        hit_wx = px + dx * dist
        hit_wy = py + dy * dist
        tex_u = ((hit_wy if side == 0 else hit_wx) % tile) / tile
        return dist, hit_x, hit_y, side, tex_u

    def _build_controls(self):
        names = ["Left", "Forward", "Back", "Right", "Reset"]
        total_w = len(names) * self._BUTTON_W + (len(names) - 1) * self._BUTTON_GAP
        x = max(8, (self.width() - total_w) // 2)
        y = self.height() - self._BUTTON_H - 8
        self._controls = []
        for name in names:
            rect = QRect(x, y, self._BUTTON_W, self._BUTTON_H)
            self._controls.append((name, rect))
            x += self._BUTTON_W + self._BUTTON_GAP

    def _activate_control(self, name: str):
        if name == "Left":
            self._preview_angle -= 90.0
        elif name == "Right":
            self._preview_angle += 90.0
        elif name == "Forward":
            self._step_grid(1)
        elif name == "Back":
            self._step_grid(-1)
        elif name == "Reset":
            self._reset_camera()
        self.update()

    def _step_grid(self, direction: int):
        tile = max(1, int(self.map_data.tile_size))
        angle = math.radians(self._preview_angle)
        dx = math.cos(angle)
        dy = math.sin(angle)
        if abs(dx) >= abs(dy):
            step_col = 1 if dx >= 0 else -1
            step_row = 0
        else:
            step_col = 0
            step_row = 1 if dy >= 0 else -1
        step_col *= direction
        step_row *= direction
        cur_col = int(self._preview_x // tile)
        cur_row = int(self._preview_y // tile)
        next_col = cur_col + step_col
        next_row = cur_row + step_row
        if self._is_solid(next_col, next_row):
            self._preview_x = (cur_col + 0.5) * tile
            self._preview_y = (cur_row + 0.5) * tile
            return
        self._preview_x = (next_col + 0.5) * tile
        self._preview_y = (next_row + 0.5) * tile

    def _draw_column(
        self,
        painter: QPainter,
        x: int,
        width_px: int,
        top: int,
        height_px: int,
        dist: float,
        wall_img: QImage | None,
        tex_u: float,
    ):
        if height_px <= 0:
            return
        wall_color = QColor(self.map_data.wall_color)
        if wall_img is not None and wall_img.width() > 0 and wall_img.height() > 0:
            src_x = min(wall_img.width() - 1, max(0, int(tex_u * (wall_img.width() - 1))))
            painter.drawImage(
                QRect(x, top, width_px, height_px),
                wall_img,
                QRect(src_x, 0, 1, wall_img.height()),
            )
        else:
            painter.fillRect(x, top, width_px, height_px, wall_color)

        if self.map_data.shading:
            alpha = max(0, min(140, int(dist / max(1.0, self.map_data.tile_size) * 18)))
            painter.fillRect(x, top, width_px, height_px, QColor(0, 0, 0, alpha))

    def _draw_objects(
        self,
        painter: QPainter,
        zbuffer: list[float],
        dist_proj: float,
        stripe_w: int,
    ):
        if not self._scene or not self._project:
            return
        sprites = []
        tile = max(1, int(self.map_data.tile_size))
        ang = math.radians(self._preview_angle)
        dir_x = math.cos(ang)
        dir_y = math.sin(ang)
        plane_mag = math.tan(math.radians(self._FOV_DEG) / 2.0)
        plane_x = -dir_y * plane_mag
        plane_y = dir_x * plane_mag
        det = plane_x * dir_y - dir_x * plane_y
        if abs(det) < 1e-8:
            return
        inv_det = 1.0 / det

        for po in self._scene.placed_objects:
            if not getattr(po, "is_3d", False) or getattr(po, "hud_mode", False) or not po.visible:
                continue
            od = self._project.get_object_def(po.object_def_id)
            img = self._initial_image_for_object_def(od)
            if img is None or img.width() <= 0 or img.height() <= 0:
                continue
            world_x = (po.grid_x + po.offset_x) * tile
            world_y = (po.grid_y + po.offset_y) * tile
            rel_x = world_x - self._preview_x
            rel_y = world_y - self._preview_y
            transform_x = inv_det * (dir_y * rel_x - dir_x * rel_y)
            transform_y = inv_det * (-plane_y * rel_x + plane_x * rel_y)
            if transform_y <= 0.05:
                continue
            sprites.append((transform_y, transform_x, po, img))

        sprites.sort(key=lambda item: item[0], reverse=True)
        y_center = self.height() * 0.5
        screen_cols = len(zbuffer)

        for depth, transform_x, po, img in sprites:
            sprite_h = abs(self.map_data.wall_height * dist_proj / depth) * max(0.01, po.scale)
            sprite_w = sprite_h * (img.width() / max(1, img.height()))
            if sprite_h < 2 or sprite_w < 2:
                continue
            screen_x = int((self.width() * 0.5) * (1.0 + transform_x / depth))
            top = int(y_center - sprite_h * 0.5 - (po.vertical_offset * dist_proj / depth))
            left = int(screen_x - sprite_w * 0.5)
            right = int(left + sprite_w)
            if right < 0 or left >= self.width():
                continue
            start_col = max(0, left // stripe_w)
            end_col = min(screen_cols - 1, right // stripe_w)
            for col in range(start_col, end_col + 1):
                if depth >= zbuffer[col]:
                    continue
                stripe_left = col * stripe_w
                overlap_left = max(left, stripe_left)
                overlap_right = min(right, stripe_left + stripe_w)
                if overlap_right <= overlap_left:
                    continue
                u = (overlap_left - left) / max(1.0, sprite_w)
                src_x = min(img.width() - 1, max(0, int(u * (img.width() - 1))))
                target = QRect(overlap_left, top, overlap_right - overlap_left, int(sprite_h))
                painter.drawImage(target, img, QRect(src_x, 0, 1, img.height()))

    def _draw_controls(self, painter: QPainter):
        self._build_controls()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for name, rect in self._controls:
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.setBrush(QColor(22, 22, 28, 220))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor(TEXT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def paintEvent(self, e: QPaintEvent):
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        half = h // 2

        sky_color = QColor(self.map_data.sky_color if self.map_data.sky_on else DARK)
        floor_color = QColor(self.map_data.floor_color if self.map_data.floor_on else SURFACE)
        painter.fillRect(0, 0, w, half, sky_color)
        painter.fillRect(0, half, w, h - half, floor_color)

        # Stub wall columns — very rough approximation, just visual chrome
        if self.map_data.width > 0 and self.map_data.height > 0:
            stripe_w = 2
            dist_proj = (w * 0.5) / math.tan(math.radians(self._FOV_DEG) * 0.5)
            max_dist = max(self.map_data.width, self.map_data.height) * max(1, self.map_data.tile_size) * 1.5
            zbuffer: list[float] = []
            for x in range(0, w, stripe_w):
                camera_x = ((x + stripe_w * 0.5) / max(1, w)) - 0.5
                angle = self._preview_angle + camera_x * self._FOV_DEG
                raw_dist, cell_x, cell_y, _side, tex_u = self._raycast(angle, max_dist)
                corrected_dist = raw_dist * math.cos(math.radians(angle - self._preview_angle))
                corrected_dist = max(corrected_dist, 0.0001)
                line_h = int((self.map_data.wall_height * dist_proj) / corrected_dist)
                top = (h - line_h) // 2
                value = TILE_SOLID
                if 0 <= cell_x < self.map_data.width and 0 <= cell_y < self.map_data.height:
                    value = self.map_data.cells[cell_y * self.map_data.width + cell_x]
                wall_img = self._wall_image_for_cell(cell_x, cell_y, value)
                self._draw_column(painter, x, stripe_w, top, line_h, corrected_dist, wall_img, tex_u)
                zbuffer.append(corrected_dist)
            self._draw_objects(painter, zbuffer, dist_proj, stripe_w)

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRect(0, 0, w - 1, h - 1)
        if self._show_controls:
            self._draw_controls(painter)
        painter.end()


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
    tile_meta_type_changed = Signal(str)
    color_pick_requested = Signal(str)
    object_selected    = Signal(str)       # emits object ID, or "" on deselection
    object_deleted     = Signal()          # emits after an object is removed
    path_selected      = Signal(str)       # emits active path component id, or ""
    paths_changed      = Signal()          # emits after path create/edit/delete

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene: Scene | None = None
        self._project: Project | None = None
        self._updating_paths = False
        self.setFixedWidth(300)
        self.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        self._build()

    def set_scene(self, scene: Scene | None, project: Project | None):
        self._scene = scene
        self._project = project

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {PANEL}; }}
            QScrollBar:vertical {{
                background: {PANEL}; width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER}; border-radius: 4px;
            }}
        """)

        inner = QWidget()
        inner.setMinimumWidth(0)
        inner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        inner.setStyleSheet(f"background: {PANEL};")
        v = QVBoxLayout(inner)
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

        tool_row4 = QHBoxLayout()
        tool_row4.setContentsMargins(8, 0, 8, 4)
        tool_row4.setSpacing(4)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        self._tools = {
            TOOL_PAINT:  ToolButton("✏ Paint",  "Paint walls",                TOOL_PAINT),
            TOOL_ERASE:  ToolButton("◻ Erase",  "Erase to empty",             TOOL_ERASE),
            TOOL_FILL:   ToolButton("⬛ Fill",   "Flood fill region",          TOOL_FILL),
            TOOL_SPAWN:  ToolButton("⊕ Spawn",  "Place player spawn",         TOOL_SPAWN),
            TOOL_TILE_META: ToolButton("◇ Meta", "Paint door/exit/trigger tiles", TOOL_TILE_META),
            TOOL_OBJECT: ToolButton("⊙ Object", "Place/move 3D objects",      TOOL_OBJECT),
            TOOL_PATH:   ToolButton("↝ Path",   "Author 3D patrol paths",     TOOL_PATH),
        }

        for btn in self._tools.values():
            self._tool_group.addButton(btn)
        self._tools[TOOL_PAINT].setChecked(True)

        tool_row1.addWidget(self._tools[TOOL_PAINT])
        tool_row1.addWidget(self._tools[TOOL_ERASE])
        tool_row2.addWidget(self._tools[TOOL_FILL])
        tool_row2.addWidget(self._tools[TOOL_SPAWN])
        tool_row3.addWidget(self._tools[TOOL_TILE_META])
        tool_row3.addWidget(self._tools[TOOL_OBJECT])
        tool_row4.addWidget(self._tools[TOOL_PATH])
        tool_row4.addStretch()

        v.addLayout(tool_row1)
        v.addLayout(tool_row2)
        v.addLayout(tool_row3)
        v.addLayout(tool_row4)

        self._tool_group.buttonClicked.connect(self._on_tool_clicked)

        v.addWidget(_divider())

        # ── Colors ──────────────────────────────────────────
        v.addWidget(_section("COLORS"))

        color_wrap = QWidget()
        color_wrap.setStyleSheet(f"background: {PANEL};")
        color_row = QHBoxLayout(color_wrap)
        color_row.setContentsMargins(8, 4, 8, 8)
        color_row.setSpacing(4)

        self._wall_btn = _color_btn("#0000ff")
        self._floor_btn = _color_btn("#808080")
        self._sky_btn = _color_btn("#404040")
        for btn in (self._wall_btn, self._floor_btn, self._sky_btn):
            btn.setFixedWidth(56)
            btn.setMinimumHeight(24)

        color_row.addWidget(_label("W", dim=True, small=True))
        color_row.addWidget(self._wall_btn)
        color_row.addWidget(_label("F", dim=True, small=True))
        color_row.addWidget(self._floor_btn)
        color_row.addWidget(_label("S", dim=True, small=True))
        color_row.addWidget(self._sky_btn)
        color_row.addStretch()

        self._wall_btn.clicked.connect(lambda: self.color_pick_requested.emit("wall"))
        self._floor_btn.clicked.connect(lambda: self.color_pick_requested.emit("floor"))
        self._sky_btn.clicked.connect(lambda: self.color_pick_requested.emit("sky"))

        v.addWidget(color_wrap)

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

        # ── Tile metadata ────────────────────────────────────
        v.addWidget(_section("TILE METADATA"))

        meta_w = QWidget()
        meta_w.setStyleSheet(f"background: {PANEL};")
        meta_v = QVBoxLayout(meta_w)
        meta_v.setContentsMargins(8, 4, 8, 8)
        meta_v.setSpacing(6)

        meta_v.addWidget(_label(
            "Used by the Meta tool. Click a cell to paint or clear metadata.",
            dim=True, small=True,
        ))

        meta_row = QHBoxLayout()
        meta_row.setSpacing(4)
        meta_row.addWidget(_label("Type:", dim=True, small=True))
        self._tile_meta_combo = QComboBox()
        self._tile_meta_combo.setStyleSheet(f"""
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
        self._tile_meta_combo.addItem("Door", TILE_META_DOOR)
        self._tile_meta_combo.addItem("Exit", TILE_META_EXIT)
        self._tile_meta_combo.addItem("Trigger", TILE_META_TRIGGER)
        self._tile_meta_combo.addItem("Switch", TILE_META_SWITCH)
        meta_row.addWidget(self._tile_meta_combo, stretch=1)
        meta_v.addLayout(meta_row)

        self._tile_meta_combo.currentIndexChanged.connect(self._on_tile_meta_type_changed)

        v.addWidget(meta_w)

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

        # ── Paths ───────────────────────────────────────────
        v.addWidget(_section("PATHS"))

        path_btn_row = QHBoxLayout()
        path_btn_row.setContentsMargins(8, 0, 8, 4)
        path_btn_row.setSpacing(4)
        self._btn_add_path = _small_btn("+", "Create a new 3D path", accent=True)
        self._btn_del_path = _small_btn("−", "Delete selected path", danger=True)
        path_btn_row.addWidget(self._btn_add_path)
        path_btn_row.addWidget(self._btn_del_path)
        path_btn_row.addStretch()
        v.addLayout(path_btn_row)

        self._path_list = QListWidget()
        self._path_list.setStyleSheet(f"""
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
        self._path_list.setFixedHeight(96)

        path_list_wrap = QWidget()
        path_list_wrap.setStyleSheet(f"background: {PANEL};")
        plw = QVBoxLayout(path_list_wrap)
        plw.setContentsMargins(8, 0, 8, 6)
        plw.setSpacing(6)
        plw.addWidget(self._path_list)

        self._path_name_edit = QLineEdit()
        self._path_name_edit.setPlaceholderText("Path name")
        self._path_name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }}
        """)
        plw.addWidget(self._path_name_edit)

        self._path_closed_check = QCheckBox("Closed Loop")
        self._path_closed_check.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        plw.addWidget(self._path_closed_check)

        path_edit_row = QHBoxLayout()
        path_edit_row.setSpacing(4)
        self._btn_path_remove_last = _small_btn("Undo", "Remove the last path cell")
        self._btn_path_clear = _small_btn("Clear", "Remove all cells from this path", danger=True)
        path_edit_row.addWidget(self._btn_path_remove_last)
        path_edit_row.addWidget(self._btn_path_clear)
        plw.addLayout(path_edit_row)

        v.addWidget(path_list_wrap)

        self._btn_add_path.clicked.connect(self._on_add_path)
        self._btn_del_path.clicked.connect(self._on_del_path)
        self._path_list.currentRowChanged.connect(self._on_path_list_changed)
        self._path_name_edit.textEdited.connect(self._on_path_name_edited)
        self._path_closed_check.toggled.connect(self._on_path_closed_toggled)
        self._btn_path_remove_last.clicked.connect(self._on_remove_last_path_point)
        self._btn_path_clear.clicked.connect(self._on_clear_path_points)

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
        self.refresh_paths("")
        scroll.setWidget(inner)
        outer.addWidget(scroll)

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

    def _on_tile_meta_type_changed(self, idx: int):
        meta_type = self._tile_meta_combo.itemData(idx) or TILE_META_DOOR
        self.tile_meta_type_changed.emit(meta_type)

    def refresh_colors(self, map_data: MapData):
        self._wall_btn.setStyleSheet(_color_btn(map_data.wall_color).styleSheet())
        self._floor_btn.setStyleSheet(_color_btn(map_data.floor_color).styleSheet())
        self._sky_btn.setStyleSheet(_color_btn(map_data.sky_color).styleSheet())

    def populate_textures(self, image_names: list[str]):
        self._tex_combo.blockSignals(True)
        self._tex_combo.clear()
        has_images = bool(image_names)
        self._btn_tex.setEnabled(has_images)
        if image_names:
            for name in image_names:
                self._tex_combo.addItem(name)
        else:
            self._tex_combo.addItem("(no textures registered)")
            if self._btn_tex.isChecked():
                self._btn_solid.setChecked(True)
                self.paint_value_changed.emit(TILE_SOLID)
        self._tex_combo.blockSignals(False)

    def set_zoom_label(self, px: int):
        self._zoom_lbl.setText(f"{px}px")

    # ── path list ───────────────────────────────────────────
    def _get_paths(self) -> list[SceneComponent]:
        return _scene_path_components(self._scene)

    def _current_path_id(self) -> str:
        row = self._path_list.currentRow()
        paths = self._get_paths()
        if 0 <= row < len(paths):
            return getattr(paths[row], "id", "")
        return ""

    def _selected_path(self) -> SceneComponent | None:
        return _find_scene_path(self._scene, self._current_path_id())

    def _sync_path_controls(self):
        comp = self._selected_path()
        self._updating_paths = True
        has_path = comp is not None
        self._path_name_edit.setEnabled(has_path)
        self._path_closed_check.setEnabled(has_path)
        self._btn_del_path.setEnabled(has_path)
        self._btn_path_remove_last.setEnabled(has_path)
        self._btn_path_clear.setEnabled(has_path)
        if has_path:
            self._path_name_edit.setText(_path_name(comp))
            self._path_closed_check.setChecked(bool(comp.config.get("closed", False)))
            has_points = bool(comp.config.get("points", []))
            self._btn_path_remove_last.setEnabled(has_points)
            self._btn_path_clear.setEnabled(has_points)
        else:
            self._path_name_edit.clear()
            self._path_closed_check.setChecked(False)
        self._updating_paths = False

    def refresh_paths(self, selected_id: str | None = None):
        current_id = selected_id if selected_id is not None else self._current_path_id()
        paths = self._get_paths()
        self._path_list.blockSignals(True)
        self._path_list.clear()
        restore_row = -1
        for idx, comp in enumerate(paths):
            label = _path_name(comp)
            count = len(comp.config.get("points", []) or [])
            suffix = " loop" if comp.config.get("closed", False) else ""
            item = QListWidgetItem(f"{label} ({count}){suffix}")
            item.setData(Qt.ItemDataRole.UserRole, getattr(comp, "id", ""))
            self._path_list.addItem(item)
            if getattr(comp, "id", "") == current_id:
                restore_row = idx
        if restore_row >= 0:
            self._path_list.setCurrentRow(restore_row)
        elif paths:
            self._path_list.setCurrentRow(0)
        self._path_list.blockSignals(False)
        self._sync_path_controls()
        self.path_selected.emit(self._current_path_id())

    def _on_add_path(self):
        if self._scene is None:
            return
        suggested = _unique_path_name(self._scene, "Path")
        name, ok = QInputDialog.getText(self, "Add 3D Path", "Path name:", text=suggested)
        if not ok:
            return
        final_name = _unique_path_name(self._scene, name)
        comp = make_component("Path")
        comp.config["path_name"] = final_name
        comp.config["points"] = []
        comp.config["closed"] = False
        self._scene.components.append(comp)
        self.refresh_paths(comp.id)
        self._tools[TOOL_PATH].setChecked(True)
        self.tool_changed.emit(TOOL_PATH)
        self.path_selected.emit(comp.id)
        self.paths_changed.emit()

    def _on_del_path(self):
        if self._scene is None:
            return
        comp = self._selected_path()
        if comp is None:
            return
        self._scene.components = [item for item in self._scene.components if item is not comp]
        for po in self._scene.placed_objects:
            if getattr(po, "actor_patrol_path_id", "") == comp.id:
                po.actor_patrol_path_id = ""
        self.refresh_paths()
        self.path_selected.emit(self._current_path_id())
        self.paths_changed.emit()

    def _on_path_list_changed(self, row: int):
        self._sync_path_controls()
        paths = self._get_paths()
        if 0 <= row < len(paths):
            self.path_selected.emit(getattr(paths[row], "id", ""))
        else:
            self.path_selected.emit("")

    def _on_path_name_edited(self, text: str):
        if self._updating_paths:
            return
        comp = self._selected_path()
        if comp is None:
            return
        desired = (text or "").strip() or "Path"
        taken = {_path_name(item) for item in self._get_paths() if item is not comp}
        final = desired if desired not in taken else _unique_path_name(self._scene, desired)
        comp.config["path_name"] = final
        self.refresh_paths(comp.id)
        self.paths_changed.emit()

    def _on_path_closed_toggled(self, checked: bool):
        if self._updating_paths:
            return
        comp = self._selected_path()
        if comp is None:
            return
        comp.config["closed"] = bool(checked)
        self.refresh_paths(comp.id)
        self.paths_changed.emit()

    def _on_remove_last_path_point(self):
        comp = self._selected_path()
        if comp is None:
            return
        points = comp.config.setdefault("points", [])
        if points:
            points.pop()
            self.refresh_paths(comp.id)
            self.paths_changed.emit()

    def _on_clear_path_points(self):
        comp = self._selected_path()
        if comp is None:
            return
        comp.config["points"] = []
        self.refresh_paths(comp.id)
        self.paths_changed.emit()

    # ── object list ───────────────────────────────────────────

    def _get_3d_objects(self) -> list[PlacedObject]:
        """Return the is_3d placed objects in the current scene."""
        if self._scene is None:
            return []
        return [po for po in self._scene.placed_objects if getattr(po, "is_3d", False)]

    def _on_add_object(self):
        if self._scene is None or self._project is None:
            return
        supported_defs = [
            od for od in self._project.object_defs
            if _classify_3d_object_def(self._project, od)[0] is not None
        ]
        if not supported_defs:
            return
        names = [od.name for od in supported_defs]
        name, ok = QInputDialog.getItem(
            self, "Add 3D Object", "Choose object definition:", names, 0, False)
        if not ok:
            return
        idx = names.index(name)
        od = supported_defs[idx]
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
            self.object_deleted.emit()

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
            if getattr(po, "hud_mode", False):
                prefix = "🖥"
            else:
                kind, _detail = _classify_3d_object_def(self._project, od)
                prefix = "⚠" if kind is None else "🎯"
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
        self._selected_cell: tuple[int, int] | None = None
        self._hover_cell: tuple[int, int] | None = None
        self._updating = False              # guard against feedback loops
        self.setFixedWidth(280)
        self.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        self._build()

    def set_scene(self, scene: Scene | None, project: Project | None):
        self._scene = scene
        self._project = project
        self._populate_exit_scene_combo()
        self._populate_door_texture_combo()
        self._populate_patrol_path_combo()
        self.preview.set_scene(scene, project)

    def _populate_door_texture_combo(self, selected_image_id: str = ""):
        self._tile_meta_door_tex_combo.blockSignals(True)
        self._tile_meta_door_tex_combo.clear()
        self._tile_meta_door_tex_combo.addItem("Solid Wall Color", "")
        if self._project:
            for img in self._project.images:
                if img.path:
                    self._tile_meta_door_tex_combo.addItem(img.name or img.path, img.id)
        match_idx = self._tile_meta_door_tex_combo.findData(selected_image_id)
        self._tile_meta_door_tex_combo.setCurrentIndex(match_idx if match_idx >= 0 else 0)
        self._tile_meta_door_tex_combo.blockSignals(False)

    def _populate_patrol_path_combo(self, selected_path_id: str = ""):
        self._obj_patrol_path.blockSignals(True)
        self._obj_patrol_path.clear()
        self._obj_patrol_path.addItem("(none)", "")
        for comp in _scene_path_components(self._scene):
            self._obj_patrol_path.addItem(_path_name(comp), getattr(comp, "id", ""))
        match_idx = self._obj_patrol_path.findData(selected_path_id)
        self._obj_patrol_path.setCurrentIndex(match_idx if match_idx >= 0 else 0)
        self._obj_patrol_path.blockSignals(False)

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {PANEL}; }}")

        inner = QWidget()
        inner.setMinimumWidth(0)
        inner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        size_row.addWidget(_label("X:", dim=True, small=True))
        self._spin_w = QSpinBox()
        self._spin_w.setRange(4, 64)
        self._spin_w.setValue(self.map_data.width)
        self._spin_w.setStyleSheet(self._spin_style())
        size_row.addWidget(self._spin_w)
        size_row.addWidget(_label("Y:", dim=True, small=True))
        self._spin_h = QSpinBox()
        self._spin_h.setRange(4, 64)
        self._spin_h.setValue(self.map_data.height)
        self._spin_h.setStyleSheet(self._spin_style())
        size_row.addWidget(self._spin_h)
        self._btn_apply_size = _small_btn("Apply", "Resize the map", accent=True)
        self._btn_apply_size.clicked.connect(self._on_apply_size)
        size_row.addWidget(self._btn_apply_size)
        size_row.addStretch()
        sg.addLayout(size_row)
        iv.addWidget(size_w)

        iv.addWidget(_divider())

        # ── Tile Settings ─────────────────────────────────────
        iv.addWidget(_section("TILE SETTINGS"))

        tile_w = QWidget()
        tile_w.setStyleSheet(f"background: {PANEL};")
        tg = QVBoxLayout(tile_w)
        tg.setContentsMargins(8, 4, 8, 8)
        tg.setSpacing(6)

        self._tile_info_hint = QLabel("Hover a map cell to inspect its contents.")
        self._tile_info_hint.setWordWrap(True)
        self._tile_info_hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        tg.addWidget(self._tile_info_hint)

        self._tile_info_labels: dict[str, QLabel] = {}

        def _info_row(title: str, key: str):
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(_label(f"{title}:", dim=True, small=True))
            value = QLabel("-")
            value.setWordWrap(True)
            value.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            row.addWidget(value, stretch=1)
            self._tile_info_labels[key] = value
            tg.addLayout(row)

        _info_row("Cell", "cell")
        _info_row("Surface", "surface")
        _info_row("Material", "material")
        _info_row("Meta", "meta")
        _info_row("Meta Details", "meta_details")
        _info_row("Objects", "objects")
        _info_row("Behaviors", "behaviors")

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
        iv.addWidget(_divider())

        # ── Render Flags ──────────────────────────────────────
        iv.addWidget(_section("RENDER FLAGS"))

        flags_w = QWidget()
        flags_w.setStyleSheet(f"background: {PANEL};")
        fg = QHBoxLayout(flags_w)
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
        spg = QHBoxLayout(spawn_w)
        spg.setContentsMargins(8, 4, 8, 8)
        spg.setSpacing(6)

        spg.addWidget(_label("X:", dim=True, small=True))
        self._spawn_x = QSpinBox()
        self._spawn_x.setRange(0, self.map_data.width - 1)
        self._spawn_x.setValue(self.map_data.spawn_x)
        self._spawn_x.setStyleSheet(self._spin_style())
        spg.addWidget(self._spawn_x)

        spg.addWidget(_label("Y:", dim=True, small=True))
        self._spawn_y = QSpinBox()
        self._spawn_y.setRange(0, self.map_data.height - 1)
        self._spawn_y.setValue(self.map_data.spawn_y)
        self._spawn_y.setStyleSheet(self._spin_style())
        spg.addWidget(self._spawn_y)

        spg.addWidget(_label("A:", dim=True, small=True))
        self._spawn_angle = QSpinBox()
        self._spawn_angle.setRange(0, 359)
        self._spawn_angle.setValue(self.map_data.spawn_angle)
        self._spawn_angle.setSuffix("°")
        self._spawn_angle.setStyleSheet(self._spin_style())
        spg.addWidget(self._spawn_angle)
        spg.addStretch()

        self._spawn_x.valueChanged.connect(self._on_spawn_changed)
        self._spawn_y.valueChanged.connect(self._on_spawn_changed)
        self._spawn_angle.valueChanged.connect(self._on_spawn_changed)

        iv.addWidget(spawn_w)

        iv.addWidget(_divider())

        # ── Tile Metadata Inspector ───────────────────────────
        self._tile_meta_inspector = QWidget()
        self._tile_meta_inspector.setStyleSheet(f"background: {PANEL};")
        self._tile_meta_inspector.setVisible(False)

        tm_outer = QVBoxLayout(self._tile_meta_inspector)
        tm_outer.setContentsMargins(0, 0, 0, 0)
        tm_outer.setSpacing(0)

        tm_outer.addWidget(_section("TILE METADATA"))

        tm_w = QWidget()
        tm_w.setStyleSheet(f"background: {PANEL};")
        tm = QVBoxLayout(tm_w)
        tm.setContentsMargins(8, 4, 8, 8)
        tm.setSpacing(6)

        coord_row = QHBoxLayout()
        coord_row.addWidget(_label("Cell:", dim=True, small=True))
        self._tile_meta_cell_label = QLabel("-")
        self._tile_meta_cell_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        coord_row.addWidget(self._tile_meta_cell_label, stretch=1)
        tm.addLayout(coord_row)

        type_row = QHBoxLayout()
        type_row.addWidget(_label("Type:", dim=True, small=True))
        self._tile_meta_type_label = QLabel("(none)")
        self._tile_meta_type_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        type_row.addWidget(self._tile_meta_type_label, stretch=1)
        tm.addLayout(type_row)

        self._tile_meta_empty_label = QLabel(
            "Selected cell has no tile metadata. Use the Meta tool to paint one."
        )
        self._tile_meta_empty_label.setWordWrap(True)
        self._tile_meta_empty_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        tm.addWidget(self._tile_meta_empty_label)

        self._tile_meta_state_row = QWidget()
        self._tile_meta_state_row.setStyleSheet(f"background: {PANEL};")
        state_row_l = QHBoxLayout(self._tile_meta_state_row)
        state_row_l.setContentsMargins(0, 0, 0, 0)
        state_row_l.setSpacing(6)
        self._tile_meta_state_name = _label("State:", dim=True, small=True)
        state_row_l.addWidget(self._tile_meta_state_name)
        self._tile_meta_state_combo = QComboBox()
        self._tile_meta_state_combo.setStyleSheet(self._combo_style())
        state_row_l.addWidget(self._tile_meta_state_combo, stretch=1)
        tm.addWidget(self._tile_meta_state_row)

        self._tile_meta_target_row = QWidget()
        self._tile_meta_target_row.setStyleSheet(f"background: {PANEL};")
        target_row_l = QHBoxLayout(self._tile_meta_target_row)
        target_row_l.setContentsMargins(0, 0, 0, 0)
        target_row_l.setSpacing(6)
        target_row_l.addWidget(_label("Exit Scene:", dim=True, small=True))
        self._tile_meta_target_combo = QComboBox()
        self._tile_meta_target_combo.setStyleSheet(self._combo_style())
        target_row_l.addWidget(self._tile_meta_target_combo, stretch=1)
        tm.addWidget(self._tile_meta_target_row)

        self._tile_meta_tag_row = QWidget()
        self._tile_meta_tag_row.setStyleSheet(f"background: {PANEL};")
        tag_row_l = QHBoxLayout(self._tile_meta_tag_row)
        tag_row_l.setContentsMargins(0, 0, 0, 0)
        tag_row_l.setSpacing(6)
        tag_row_l.addWidget(_label("Tag:", dim=True, small=True))
        self._tile_meta_tag_edit = QLineEdit()
        self._tile_meta_tag_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }}
        """)
        tag_row_l.addWidget(self._tile_meta_tag_edit, stretch=1)
        tm.addWidget(self._tile_meta_tag_row)

        self._tile_meta_door_tex_row = QWidget()
        self._tile_meta_door_tex_row.setStyleSheet(f"background: {PANEL};")
        door_tex_row_l = QHBoxLayout(self._tile_meta_door_tex_row)
        door_tex_row_l.setContentsMargins(0, 0, 0, 0)
        door_tex_row_l.setSpacing(6)
        door_tex_row_l.addWidget(_label("Door Texture:", dim=True, small=True))
        self._tile_meta_door_tex_combo = QComboBox()
        self._tile_meta_door_tex_combo.setStyleSheet(self._combo_style())
        self._tile_meta_door_tex_combo.addItem("Solid Wall Color", "")
        door_tex_row_l.addWidget(self._tile_meta_door_tex_combo, stretch=1)
        tm.addWidget(self._tile_meta_door_tex_row)

        # Remove meta button
        self._btn_remove_tile_meta = _small_btn("✕ Remove Meta", "Delete tile metadata from this cell", danger=True)
        self._btn_remove_tile_meta.setVisible(False)
        tm.addWidget(self._btn_remove_tile_meta)

        tm_outer.addWidget(tm_w)
        iv.addWidget(self._tile_meta_inspector)

        self._tile_meta_state_combo.currentIndexChanged.connect(self._on_tile_meta_edited)
        self._tile_meta_target_combo.currentIndexChanged.connect(self._on_tile_meta_edited)
        self._tile_meta_tag_edit.textEdited.connect(self._on_tile_meta_edited)
        self._tile_meta_door_tex_combo.currentIndexChanged.connect(self._on_tile_meta_edited)
        self._btn_remove_tile_meta.clicked.connect(self._on_remove_tile_meta)

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

        ir_row = QHBoxLayout()
        ir_row.addWidget(_label("Interact Range:", dim=True, small=True))
        self._obj_interact_range = QSpinBox()
        self._obj_interact_range.setRange(16, 512)
        self._obj_interact_range.setSingleStep(8)
        self._obj_interact_range.setValue(80)
        self._obj_interact_range.setToolTip(
            "Pixel radius within which the player can interact with this object "
            "(default 80 ≈ 1.25 tiles). Passed to RayCast3D.registerObject."
        )
        self._obj_interact_range.setStyleSheet(self._spin_style())
        ir_row.addWidget(self._obj_interact_range)
        ir_row.addStretch()

        tl_row = QHBoxLayout()
        tl_row.addWidget(_label("Tile Link Tag:", dim=True, small=True))
        self._obj_tile_link_tag = QLineEdit()
        self._obj_tile_link_tag.setPlaceholderText("tag (optional)")
        self._obj_tile_link_tag.setToolTip(
            "When a Trigger or Switch tile with this tag fires, it will target "
            "this object via on_signal dispatch. Must match the tile's Tag field."
        )
        self._obj_tile_link_tag.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }}
        """)
        tl_row.addWidget(self._obj_tile_link_tag, stretch=1)

        patrol_row = QHBoxLayout()
        patrol_row.addWidget(_label("Patrol Path:", dim=True, small=True))
        self._obj_patrol_path = QComboBox()
        self._obj_patrol_path.setStyleSheet(self._combo_style())
        self._obj_patrol_path.addItem("(none)", "")
        patrol_row.addWidget(self._obj_patrol_path, stretch=1)

        sf.addLayout(gx_row)
        sf.addLayout(gy_row)
        sf.addLayout(ox_row)
        sf.addLayout(oy_row)
        sf.addLayout(sc_row)
        sf.addLayout(vo_row)
        sf.addWidget(self._obj_blocking)
        sf.addLayout(ir_row)
        sf.addLayout(tl_row)
        sf.addLayout(patrol_row)

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
        for anchor in ("top_left", "top_right", "bottom_left", "bottom_right", "center", "bottom_center"):
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
        self._obj_interact_range.valueChanged.connect(self._on_obj_edited)
        self._obj_tile_link_tag.textEdited.connect(self._on_obj_edited)
        self._obj_patrol_path.currentIndexChanged.connect(self._on_obj_edited)
        self._obj_hud_x.valueChanged.connect(self._on_obj_edited)
        self._obj_hud_y.valueChanged.connect(self._on_obj_edited)
        self._obj_hud_anchor.currentIndexChanged.connect(self._on_obj_edited)
        self._obj_visible.toggled.connect(self._on_obj_edited)

        iv.addStretch()

        scroll.setWidget(inner)
        scroll.horizontalScrollBar().rangeChanged.connect(
            lambda _min, _max, sb=scroll.horizontalScrollBar(): sb.setValue(0)
        )
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
        self.map_data.tile_meta = {
            k: v for k, v in self.map_data.tile_meta.items()
            if 0 <= int(k.split(',')[0]) < self.map_data.width
            and 0 <= int(k.split(',')[1]) < self.map_data.height
        }
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
            elif target == "sky":
                self.map_data.sky_color = hex_val
            elif target == "wall":
                self.map_data.wall_color = hex_val
            self.map_settings_changed.emit()

    def _populate_exit_scene_combo(self, selected_scene: int = 0):
        self._tile_meta_target_combo.blockSignals(True)
        self._tile_meta_target_combo.clear()
        self._tile_meta_target_combo.addItem("(none)", 0)
        if self._project is not None:
            for idx, scene in enumerate(self._project.scenes, start=1):
                label = scene.name or f"Scene {idx}"
                self._tile_meta_target_combo.addItem(f"{idx}: {label}", idx)
        match_idx = self._tile_meta_target_combo.findData(selected_scene)
        self._tile_meta_target_combo.setCurrentIndex(match_idx if match_idx >= 0 else 0)
        self._tile_meta_target_combo.blockSignals(False)

    def set_hover_cell(self, col: int, row: int):
        self._hover_cell = (col, row)
        self._populate_hover_tile_info()

    def _texture_name_for_cell_value(self, val: int) -> str:
        if val < 2 or self._project is None:
            return "-"
        textures = [img for img in self._project.images if img.path]
        idx = val - 2
        if 0 <= idx < len(textures):
            img = textures[idx]
            return img.name or img.path or "-"
        return f"Texture #{idx + 1}"

    def _populate_hover_tile_info(self):
        if self._hover_cell is None:
            for lbl in self._tile_info_labels.values():
                lbl.setText("-")
            return

        col, row = self._hover_cell
        self._tile_info_labels["cell"].setText(f"{col}, {row}")
        val = self.map_data.get(col, row)
        if val == TILE_EMPTY:
            surface = "Empty"
            material = "None"
        elif val == TILE_SOLID:
            surface = "Solid Wall"
            material = f"Wall Color {self.map_data.wall_color}"
        else:
            surface = "Textured Wall"
            material = self._texture_name_for_cell_value(val)
        self._tile_info_labels["surface"].setText(surface)
        self._tile_info_labels["material"].setText(material)

        meta = self.map_data.tile_meta.get(_tile_meta_key(col, row))
        if meta is None:
            self._tile_info_labels["meta"].setText("None")
            self._tile_info_labels["meta_details"].setText("No tile metadata")
        else:
            self._tile_info_labels["meta"].setText(TILE_META_LABELS.get(meta.type, meta.type))
            details: list[str] = []
            if meta.type == TILE_META_DOOR:
                details.append(f"state={meta.state or 'closed'}")
                if getattr(meta, "texture_image_id", "") and self._project:
                    img = self._project.get_image(meta.texture_image_id)
                    if img and img.path:
                        details.append(f"texture={img.name or img.path}")
                if meta.tag:
                    details.append(f"tag={meta.tag}")
            elif meta.type == TILE_META_EXIT:
                details.append(f"target_scene={meta.target_scene}")
            elif meta.type == TILE_META_TRIGGER:
                details.append(f"tag={meta.tag or '(none)'}")
            elif meta.type == TILE_META_SWITCH:
                details.append(f"state={meta.state or 'off'}")
                details.append(f"tag={meta.tag or '(none)'}")
            self._tile_info_labels["meta_details"].setText(", ".join(details) if details else "-")

        obj_lines: list[str] = []
        behavior_lines: list[str] = []
        if self._scene:
            for po in self._scene.placed_objects:
                if not getattr(po, "is_3d", False) or getattr(po, "hud_mode", False):
                    continue
                if po.grid_x == col and po.grid_y == row:
                    od = self._project.get_object_def(po.object_def_id) if self._project else None
                    name = od.name if od else po.object_def_id or "(unknown)"
                    obj_lines.append(f"{name} [{po.instance_id}]")
                    def_count = len(getattr(od, "behaviors", []) or []) if od else 0
                    inst_count = len(getattr(po, "instance_behaviors", []) or [])
                    behavior_lines.append(f"{name}: def {def_count}, inst {inst_count}")
        self._tile_info_labels["objects"].setText("\n".join(obj_lines) if obj_lines else "None")
        self._tile_info_labels["behaviors"].setText("\n".join(behavior_lines) if behavior_lines else "None")

    def select_cell(self, col: int, row: int):
        self._selected_cell = (col, row)
        self._tile_meta_inspector.setVisible(True)
        self._populate_tile_meta_inspector()

    def deselect_cell(self):
        self._selected_cell = None
        self._tile_meta_inspector.setVisible(False)

    def _populate_tile_meta_inspector(self):
        if self._selected_cell is None:
            self._tile_meta_inspector.setVisible(False)
            return

        col, row = self._selected_cell
        if not (0 <= col < self.map_data.width and 0 <= row < self.map_data.height):
            self.deselect_cell()
            return

        self._updating = True
        self._tile_meta_inspector.setVisible(True)
        self._tile_meta_cell_label.setText(f"{col}, {row}")

        meta = self.map_data.tile_meta.get(_tile_meta_key(col, row))
        if meta is None:
            self._tile_meta_type_label.setText("(none)")
            self._tile_meta_empty_label.setVisible(True)
            self._tile_meta_state_row.setVisible(False)
            self._tile_meta_target_row.setVisible(False)
            self._tile_meta_tag_row.setVisible(False)
            self._tile_meta_door_tex_row.setVisible(False)
            self._btn_remove_tile_meta.setVisible(False)
            self._updating = False
            return

        self._tile_meta_type_label.setText(TILE_META_LABELS.get(meta.type, meta.type))
        self._tile_meta_empty_label.setVisible(False)

        if meta.type == TILE_META_DOOR:
            self._tile_meta_state_name.setText("Default:")
            self._tile_meta_state_combo.blockSignals(True)
            self._tile_meta_state_combo.clear()
            self._tile_meta_state_combo.addItem("Closed", "closed")
            self._tile_meta_state_combo.addItem("Open", "open")
            idx = self._tile_meta_state_combo.findData(meta.state or "closed")
            self._tile_meta_state_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._tile_meta_state_combo.blockSignals(False)
            self._populate_door_texture_combo(meta.texture_image_id)
            self._tile_meta_state_row.setVisible(True)
            self._tile_meta_target_row.setVisible(False)
            self._tile_meta_tag_row.setVisible(False)
            self._tile_meta_door_tex_row.setVisible(True)
        elif meta.type == TILE_META_EXIT:
            self._populate_exit_scene_combo(meta.target_scene)
            self._tile_meta_state_row.setVisible(False)
            self._tile_meta_target_row.setVisible(True)
            self._tile_meta_tag_row.setVisible(False)
            self._tile_meta_door_tex_row.setVisible(False)
        elif meta.type == TILE_META_TRIGGER:
            self._tile_meta_tag_edit.setText(meta.tag)
            self._tile_meta_state_row.setVisible(False)
            self._tile_meta_target_row.setVisible(False)
            self._tile_meta_tag_row.setVisible(True)
            self._tile_meta_door_tex_row.setVisible(False)
        elif meta.type == TILE_META_SWITCH:
            self._tile_meta_state_name.setText("Default:")
            self._tile_meta_state_combo.blockSignals(True)
            self._tile_meta_state_combo.clear()
            self._tile_meta_state_combo.addItem("Off", "off")
            self._tile_meta_state_combo.addItem("On", "on")
            idx = self._tile_meta_state_combo.findData(meta.state or "off")
            self._tile_meta_state_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._tile_meta_state_combo.blockSignals(False)
            self._tile_meta_tag_edit.setText(meta.tag)
            self._tile_meta_state_row.setVisible(True)
            self._tile_meta_target_row.setVisible(False)
            self._tile_meta_tag_row.setVisible(True)
            self._tile_meta_door_tex_row.setVisible(False)
        else:
            self._tile_meta_state_row.setVisible(False)
            self._tile_meta_target_row.setVisible(False)
            self._tile_meta_tag_row.setVisible(False)
            self._tile_meta_door_tex_row.setVisible(False)

        self._btn_remove_tile_meta.setVisible(True)
        self._updating = False

    def _on_tile_meta_edited(self, *_args):
        if self._updating or self._selected_cell is None:
            return

        key = _tile_meta_key(*self._selected_cell)
        meta = self.map_data.tile_meta.get(key)
        if meta is None:
            return

        if meta.type == TILE_META_DOOR:
            meta.state = self._tile_meta_state_combo.currentData() or "closed"
            meta.texture_image_id = self._tile_meta_door_tex_combo.currentData() or ""
        elif meta.type == TILE_META_EXIT:
            meta.target_scene = int(self._tile_meta_target_combo.currentData() or 0)
        elif meta.type == TILE_META_TRIGGER:
            meta.tag = self._tile_meta_tag_edit.text()
        elif meta.type == TILE_META_SWITCH:
            meta.state = self._tile_meta_state_combo.currentData() or "off"
            meta.tag = self._tile_meta_tag_edit.text()

        self.map_settings_changed.emit()

    def _on_remove_tile_meta(self):
        """Delete the tile metadata from the currently selected cell."""
        if self._selected_cell is None:
            return
        key = _tile_meta_key(*self._selected_cell)
        if key in self.map_data.tile_meta:
            del self.map_data.tile_meta[key]
        self._populate_tile_meta_inspector()
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

        # Image label (read-only, reflects the actual initial 3D sprite source)
        self._obj_image_label.setText(_3d_object_source_label(self._project, od))

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
        self._obj_interact_range.setValue(getattr(po, "interact_range", 80))
        self._obj_tile_link_tag.setText(getattr(po, "tile_link_tag", ""))
        self._populate_patrol_path_combo(getattr(po, "actor_patrol_path_id", ""))

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
        po.interact_range = self._obj_interact_range.value()
        po.tile_link_tag = self._obj_tile_link_tag.text()
        po.actor_patrol_path_id = self._obj_patrol_path.currentData() or ""

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
        if self._selected_cell is not None:
            col, row = self._selected_cell
            if not (0 <= col < self.map_data.width and 0 <= row < self.map_data.height):
                self.deselect_cell()
            else:
                self._populate_tile_meta_inspector()
        if self._hover_cell is not None:
            col, row = self._hover_cell
            if 0 <= col < self.map_data.width and 0 <= row < self.map_data.height:
                self._populate_hover_tile_info()
        # Re-populate object inspector if one is selected
        if self._selected_obj:
            self._populate_obj_inspector()
        self.preview.refresh(self.map_data, self._scene, self._project)


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
        self._left.tile_meta_type_changed.connect(self._on_tile_meta_type_changed)
        self._left.color_pick_requested.connect(self._on_color_pick_requested)
        self._left._zoom_in.clicked.connect(self._zoom_in)
        self._left._zoom_out.clicked.connect(self._zoom_out)
        self._left.object_selected.connect(self._on_object_selected)
        self._left.object_deleted.connect(self._on_object_deleted)
        self._left.path_selected.connect(self._on_path_selected)
        self._left.paths_changed.connect(self._on_paths_changed)
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
        self._grid.cell_selected.connect(self._on_cell_selected)
        self._grid.cell_hovered.connect(self._on_cell_hovered)
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

    def restyle(self, c: dict):
        global DARK, PANEL, SURFACE, SURFACE2, BORDER, ACCENT, ACCENT2, TEXT, TEXT_DIM, TEXT_MUTED, SUCCESS, WARNING, DANGER
        old = _theme_snapshot()
        DARK = c.get("DARK", DARK)
        PANEL = c.get("PANEL", PANEL)
        SURFACE = c.get("SURFACE", SURFACE)
        SURFACE2 = c.get("SURFACE2", SURFACE2)
        BORDER = c.get("BORDER", BORDER)
        ACCENT = c.get("ACCENT", ACCENT)
        ACCENT2 = c.get("ACCENT2", ACCENT2)
        TEXT = c.get("TEXT", TEXT)
        TEXT_DIM = c.get("TEXT_DIM", TEXT_DIM)
        TEXT_MUTED = c.get("TEXT_MUTED", TEXT_MUTED)
        SUCCESS = c.get("SUCCESS", SUCCESS)
        WARNING = c.get("WARNING", WARNING)
        DANGER = c.get("DANGER", DANGER)
        replace_widget_theme_colors(self, old, _theme_snapshot())

        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {DARK}; border: none; }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background: {PANEL}; width: 8px; height: 8px;
            }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: {BORDER}; border-radius: 4px;
            }}
        """)
        self._left.refresh_colors(self.map_data)
        self._grid.update()
        self._right.refresh_from_data()
        self._right.preview.refresh(self.map_data, self._scene, self._project)

    def load_scene(self, scene):
        """Called when a 3D scene is selected in the editor."""
        self._scene   = scene
        self.map_data = scene.map_data
        self._grid.set_map(self.map_data, scene)
        self._right.map_data = self.map_data
        self._right.set_scene(scene, self._project)
        self._right.refresh_from_data()
        self._left.set_scene(scene, self._project)
        self._left.refresh_colors(self.map_data)
        self._left.refresh_paths("")
        self._left.refresh_objects()
        self._right.deselect_object()
        self._right.deselect_cell()
        self._grid.selected_object_id = ""
        self._grid.active_path_id = ""
        self._grid.selected_cell = None
        self._populate_textures()

    def clear_scene(self):
        """Called when a non-3D scene is selected."""
        self._scene   = None
        self.map_data = MapData()
        self._grid.set_map(self.map_data, None)
        self._right.map_data = self.map_data
        self._left.set_scene(None, self._project)
        self._left.refresh_colors(self.map_data)
        self._left.refresh_paths("")
        self._left.refresh_objects()
        self._right.set_scene(None, self._project)
        self._right.refresh_from_data()
        self._right.deselect_object()
        self._right.deselect_cell()
        self._grid.selected_object_id = ""
        self._grid.active_path_id = ""
        self._grid.selected_cell = None

    def _populate_textures(self):
        if self._project:
            names = [img.name or img.path for img in self._project.images if img.path]
            self._left.populate_textures(names)
            selected_tex = ""
            if self._right._selected_cell is not None:
                key = _tile_meta_key(*self._right._selected_cell)
                meta = self.map_data.tile_meta.get(key)
                selected_tex = getattr(meta, "texture_image_id", "") if meta else ""
            self._right._populate_door_texture_combo(selected_tex)
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

    def _on_tile_meta_type_changed(self, meta_type: str):
        self._grid.tile_meta_type = meta_type

    def _on_color_pick_requested(self, target: str):
        self._right._pick_color(target)

    def _on_cell_selected(self, col: int, row: int):
        self._right.select_cell(col, row)

    def _on_cell_hovered(self, col: int, row: int):
        self._right.set_hover_cell(col, row)

    def _on_object_selected(self, obj_id: str):
        """Left panel selected/deselected an object."""
        self._grid.selected_object_id = obj_id
        self._grid.update()
        if obj_id:
            self._right.select_object(obj_id)
        else:
            self._right.deselect_object()

    def _on_object_deleted(self):
        """Left panel deleted an object — refresh grid and preview."""
        self._grid.selected_object_id = ""
        self._grid.update()
        self._right.preview.refresh(self.map_data, self._scene, self._project)

    def _on_path_selected(self, path_id: str):
        self._grid.active_path_id = path_id
        self._grid.update()

    def _on_paths_changed(self):
        self._grid.update()
        self._right.refresh_from_data()

    def _on_map_changed(self):
        self._right.preview.refresh(self.map_data, self._scene, self._project)
        if self._right._selected_cell is not None:
            self._right._populate_tile_meta_inspector()
        # If grid moved an object, re-populate inspector to reflect new coords
        if self._right._selected_obj:
            self._right._populate_obj_inspector()
        # Refresh object list in case names changed
        self._left.refresh_paths()
        self._left.refresh_objects()

    def _on_settings_changed(self):
        self._grid.set_map(self.map_data, self._scene)
        self._left.refresh_colors(self.map_data)
        self._right.refresh_from_data()
        self._right.preview.refresh(self.map_data, self._scene, self._project)
        # Refresh grid to redraw object markers after inspector edits
        self._grid.update()
        # Refresh object list in case name/type changed
        self._left.refresh_paths()
        self._left.refresh_objects()

    def _zoom_in(self):
        self._grid.set_cell_px(self._grid.cell_px + 4)
        self._left.set_zoom_label(self._grid.cell_px)

    def _zoom_out(self):
        self._grid.set_cell_px(self._grid.cell_px - 4)
        self._left.set_zoom_label(self._grid.cell_px)

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — 3D Maps Tab
Wolf3D-style raycaster map editor.
Paint walls on a 2D grid from above; preview renders the 3D view.

Layout:
    Left   — Tools + tile palette (230px fixed)
    Center — Paintable grid (scrollable)
    Right  — Inspector: map settings + 3D preview (280px fixed)
"""

from __future__ import annotations
import math

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSpinBox, QComboBox,
    QCheckBox, QButtonGroup, QAbstractButton, QColorDialog,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPixmap, QPainter, QPen, QBrush,
    QMouseEvent, QPaintEvent, QWheelEvent,
)

from models import Project, MapData

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
    map_changed = pyqtSignal()

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data  = map_data
        self.cell_px   = CELL_DEFAULT   # display size of each cell in pixels
        self.tool      = TOOL_PAINT
        self.paint_value = TILE_SOLID   # what we paint (0=empty,1=solid,2+=texture)
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

    def set_map(self, map_data: MapData):
        self.map_data = map_data
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
            # Fill tool only triggers once per click, not on drag
            if self.tool != TOOL_FILL:
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
#  LEFT PANEL  — Tools + tile type palette
# ─────────────────────────────────────────────────────────────

class LeftPanel(QWidget):
    tool_changed       = pyqtSignal(str)
    paint_value_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(230)
        self.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        self._build()

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

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        self._tools = {
            TOOL_PAINT: ToolButton("✏ Paint",  "Paint walls",        TOOL_PAINT),
            TOOL_ERASE: ToolButton("◻ Erase",  "Erase to empty",     TOOL_ERASE),
            TOOL_FILL:  ToolButton("⬛ Fill",   "Flood fill region",  TOOL_FILL),
            TOOL_SPAWN: ToolButton("⊕ Spawn",  "Place player spawn", TOOL_SPAWN),
        }

        for btn in self._tools.values():
            self._tool_group.addButton(btn)
        self._tools[TOOL_PAINT].setChecked(True)

        tool_row1.addWidget(self._tools[TOOL_PAINT])
        tool_row1.addWidget(self._tools[TOOL_ERASE])
        tool_row2.addWidget(self._tools[TOOL_FILL])
        tool_row2.addWidget(self._tools[TOOL_SPAWN])

        v.addLayout(tool_row1)
        v.addLayout(tool_row2)

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


# ─────────────────────────────────────────────────────────────
#  RIGHT PANEL  — Inspector + 3D preview
# ─────────────────────────────────────────────────────────────

class RightPanel(QWidget):
    map_settings_changed = pyqtSignal()

    def __init__(self, map_data: MapData, parent=None):
        super().__init__(parent)
        self.map_data = map_data
        self.setFixedWidth(280)
        self.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        self._build()

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

        tg.addLayout(ts_row)
        tg.addLayout(wh_row)
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

    def _on_flags_changed(self):
        self.map_data.floor_on = self._chk_floor.isChecked()
        self.map_data.sky_on   = self._chk_sky.isChecked()
        self.map_data.shading  = self._chk_shading.isChecked()
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
        self._grid.set_map(self.map_data)
        self._right.map_data = self.map_data
        self._right.refresh_from_data()
        self._populate_textures()

    def clear_scene(self):
        """Called when a non-3D scene is selected."""
        self._scene   = None
        self.map_data = MapData()
        self._grid.set_map(self.map_data)

    def _populate_textures(self):
        if self._project:
            names = [img.name or img.path for img in self._project.images if img.path]
            self._left.populate_textures(names)

    # ── slots ─────────────────────────────────────────────────
    def _on_tool_changed(self, tool: str):
        self._grid.tool = tool

    def _on_paint_value_changed(self, val: int):
        self._grid.paint_value = val

    def _on_map_changed(self):
        self._right.preview.refresh(self.map_data)

    def _on_settings_changed(self):
        self._grid.set_map(self.map_data)
        self._right.refresh_from_data()
        self._right.preview.refresh(self.map_data)

    def _zoom_in(self):
        self._grid.set_cell_px(self._grid.cell_px + 4)
        self._left.set_zoom_label(self._grid.cell_px)

    def _zoom_out(self):
        self._grid.set_cell_px(self._grid.cell_px - 4)
        self._left.set_zoom_label(self._grid.cell_px)
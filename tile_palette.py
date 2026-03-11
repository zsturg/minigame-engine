# -*- coding: utf-8 -*-
"""
Tile Palette Widget
Displays a registered tileset as a clickable grid.
Replaces the Project Explorer in the editor when a TileLayer component is active.
Tile size comes from the RegisteredTileset — nothing is hardcoded here.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QComboBox, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen

from models import Project, RegisteredTileset

DARK     = "#0f0f12"
PANEL    = "#16161c"
SURFACE  = "#1e1e28"
SURFACE2 = "#26263a"
BORDER   = "#2e2e42"
ACCENT   = "#7c6aff"
TEXT     = "#e8e6f0"
TEXT_DIM = "#7a7890"

_CELL_PAD = 4   # extra px added to tile_size for display cell size


class PaletteGrid(QWidget):
    """
    Clickable tile grid. Tile display size is derived from the tileset tile_size.
    index -1 = eraser.
    """
    tile_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._columns = 0
        self._rows = 0
        self._tile_size = 32
        self._cell_size = 36
        self._selected = 0
        self._hover = -1
        self.setMouseTracking(True)

    def load(self, pixmap: QPixmap, columns: int, rows: int, tile_size: int):
        self._pixmap = pixmap
        self._columns = columns
        self._rows = rows
        self._tile_size = tile_size
        # Cap display cell at 64px so very large tiles don't explode the palette
        self._cell_size = min(tile_size + _CELL_PAD, 64)
        self._selected = 0
        self._hover = -1
        self.setFixedSize(
            columns * self._cell_size,
            (rows + 1) * self._cell_size   # +1 for eraser row
        )
        self.update()

    def clear(self):
        self._pixmap = None
        self._columns = 0
        self._rows = 0
        self._selected = 0
        self._hover = -1
        self.setFixedSize(10, 10)
        self.update()

    def selected_index(self) -> int:
        return self._selected

    def set_selected(self, index: int):
        self._selected = index
        self.update()

    def _index_at(self, x: int, y: int) -> int:
        if self._columns == 0 or self._cell_size == 0:
            return 0
        col = max(0, min(x // self._cell_size, self._columns - 1))
        row = y // self._cell_size
        if row == 0:
            return -1
        tile_row = row - 1
        if tile_row >= self._rows:
            return self._selected
        return tile_row * self._columns + col

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._index_at(int(event.position().x()), int(event.position().y()))
            self._selected = idx
            self.tile_selected.emit(idx)
            self.update()

    def mouseMoveEvent(self, event):
        idx = self._index_at(int(event.position().x()), int(event.position().y()))
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None or self._columns == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        cs = self._cell_size

        # Eraser row
        eraser_rect = QRect(0, 0, self._columns * cs, cs)
        if self._selected == -1:
            painter.fillRect(eraser_rect, QColor(ACCENT))
        elif self._hover == -1:
            painter.fillRect(eraser_rect, QColor(SURFACE2).lighter(115))
        else:
            painter.fillRect(eraser_rect, QColor(SURFACE2))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRect(eraser_rect.adjusted(0, 0, -1, -1))
        painter.setPen(QColor(TEXT if self._selected == -1 else TEXT_DIM))
        painter.drawText(eraser_rect, Qt.AlignmentFlag.AlignCenter, "✕  Eraser")

        # Tile rows
        src_w = self._pixmap.width() // self._columns
        src_h = self._pixmap.height() // self._rows

        for row in range(self._rows):
            for col in range(self._columns):
                idx = row * self._columns + col
                dest_rect = QRect(col * cs, (row + 1) * cs, cs, cs)
                src_rect  = QRect(col * src_w, row * src_h, src_w, src_h)
                painter.drawPixmap(dest_rect, self._pixmap, src_rect)

                if idx == self._hover and idx != self._selected:
                    painter.fillRect(dest_rect, QColor(255, 255, 255, 40))

                if idx == self._selected:
                    painter.setPen(QPen(QColor(ACCENT), 2))
                    painter.drawRect(dest_rect.adjusted(1, 1, -1, -1))
                else:
                    painter.setPen(QPen(QColor(BORDER), 1))
                    painter.drawRect(dest_rect.adjusted(0, 0, -1, -1))

        painter.end()


class TilePalette(QWidget):
    """
    Full palette: tileset selector + paintbrush toggle + scrollable PaletteGrid.

    Signals:
        tile_selected(int)         — user clicked a tile
        paint_mode_changed(bool)   — paintbrush toggled on/off
    """
    tile_selected      = pyqtSignal(int)
    paint_mode_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Project | None = None
        self._paint_mode = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.setStyleSheet(f"background: {PANEL};")

        # Header: label + paint toggle
        header = QHBoxLayout()
        lbl = QLabel("Tile Palette")
        lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        header.addWidget(lbl)
        header.addStretch()

        self.paint_btn = QPushButton("🖌 Paint")
        self.paint_btn.setCheckable(True)
        self.paint_btn.setFixedHeight(24)
        self.paint_btn.setStyleSheet(self._btn_style(False))
        self.paint_btn.toggled.connect(self._on_paint_toggled)
        header.addWidget(self.paint_btn)
        layout.addLayout(header)

        # Tileset combo
        self.tileset_combo = QComboBox()
        self.tileset_combo.setStyleSheet(f"""
            QComboBox {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 4px; padding: 4px 8px; font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                selection-background-color: {ACCENT};
            }}
        """)
        self.tileset_combo.currentIndexChanged.connect(self._on_tileset_changed)
        layout.addWidget(self.tileset_combo)

        # Scrollable grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(
            f"background: {DARK}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self.grid = PaletteGrid()
        self.grid.tile_selected.connect(self._on_grid_tile_selected)
        self.scroll.setWidget(self.grid)
        layout.addWidget(self.scroll, stretch=1)

        # Status label
        self.sel_lbl = QLabel("Selected: Eraser  |  Paint: OFF")
        self.sel_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        layout.addWidget(self.sel_lbl)

    # ── Public API ───────────────────────────────────────────

    def load_project(self, project: Project):
        self._project = project
        self._refresh_combo()

    def load_for_component(self, tileset_id: str | None):
        self._refresh_combo()
        if tileset_id and self._project:
            for i in range(self.tileset_combo.count()):
                if self.tileset_combo.itemData(i) == tileset_id:
                    self.tileset_combo.setCurrentIndex(i)
                    return
        if self.tileset_combo.count() > 0:
            self.tileset_combo.setCurrentIndex(0)

    def selected_tile(self) -> int:
        return self.grid.selected_index()

    def is_paint_mode(self) -> bool:
        return self._paint_mode

    def current_tileset(self) -> RegisteredTileset | None:
        if self._project is None:
            return None
        ts_id = self.tileset_combo.currentData()
        return self._project.get_tileset(ts_id) if ts_id else None

    def restyle(self, c: dict):
        pass

    # ── Internal ─────────────────────────────────────────────

    def _btn_style(self, active: bool) -> str:
        if active:
            return (f"QPushButton {{ background: {ACCENT}; color: white; border: none; "
                    f"border-radius: 4px; padding: 2px 10px; font-size: 11px; font-weight: 700; }}"
                    f"QPushButton:hover {{ background: #6a59ef; }}")
        return (f"QPushButton {{ background: {SURFACE2}; color: {TEXT_DIM}; border: 1px solid {BORDER}; "
                f"border-radius: 4px; padding: 2px 10px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}")

    def _on_paint_toggled(self, checked: bool):
        self._paint_mode = checked
        self.paint_btn.setStyleSheet(self._btn_style(checked))
        self._update_status()
        self.paint_mode_changed.emit(checked)

    def _on_grid_tile_selected(self, index: int):
        self.tile_selected.emit(index)
        self._update_status()

    def _refresh_combo(self):
        self.tileset_combo.blockSignals(True)
        self.tileset_combo.clear()
        if self._project:
            for ts in self._project.tilesets:
                self.tileset_combo.addItem(ts.name or "(unnamed)", ts.id)
        if self.tileset_combo.count() == 0:
            self.tileset_combo.addItem("No tilesets registered", None)
        self.tileset_combo.blockSignals(False)
        self._load_current_tileset()

    def _on_tileset_changed(self, index: int):
        self._load_current_tileset()

    def _load_current_tileset(self):
        if self._project is None:
            self.grid.clear()
            return
        ts_id = self.tileset_combo.currentData()
        if not ts_id:
            self.grid.clear()
            return
        ts = self._project.get_tileset(ts_id)
        if ts is None or not ts.path or ts.columns == 0 or ts.rows == 0:
            self.grid.clear()
            return
        pix = QPixmap(ts.path)
        if pix.isNull():
            self.grid.clear()
            return
        self.grid.load(pix, ts.columns, ts.rows, ts.tile_size)
        self._update_status()

    def _update_status(self):
        index = self.grid.selected_index()
        paint_str = "ON" if self._paint_mode else "OFF"
        if index == -1:
            self.sel_lbl.setText(f"Eraser  |  Paint: {paint_str}")
        else:
            ts = self.current_tileset()
            if ts and ts.columns > 0:
                col = index % ts.columns
                row = index // ts.columns
                self.sel_lbl.setText(f"Tile {index} ({col},{row})  |  Paint: {paint_str}")
            else:
                self.sel_lbl.setText(f"Tile {index}  |  Paint: {paint_str}")

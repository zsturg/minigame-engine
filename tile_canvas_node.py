# -*- coding: utf-8 -*-
"""
TileCanvasNode — Vita Adventure Creator
=======================================
A single node that wraps any upstream graph output with tile-grid awareness.

What it does
------------
- Declares the atlas layout: tile size (px), columns, rows
- Total canvas = cols * tile_size  wide,  rows * tile_size  tall
- In the preview, draws a grid overlay so you can see tile boundaries
- Provides a "cell UV" output mode (grayscale, encodes cell index) that
  upstream NoiseNode / TileablePatternNode can use to vary per-cell
- Has an "Export PNG" button that saves the flat atlas at native resolution
  → ready to drag into the Tileset Manager

How to wire it
--------------
    [NoiseNode] ──► [ColorRampNode] ──► [TileCanvasNode] ──► [OutputNode]
                 [TileablePatternNode] ──────────────────────────────────┘

The node is transparent to the graph: it passes RGBA through unchanged except
for the preview overlay (which is drawn only in the GfxNode preview, not baked
into the pixel data).  The Export button renders at the true atlas resolution
independently of the project canvas size.

Integration
-----------
1. Copy this file next to nodemaker.py (or tab_animation_graph.py)
2. Import TileCanvasNode and TileCanvasGfxNode at the top of your graph file
3. Add TileCanvasNode to NODE_TYPES (it auto-registers via @register_node)
4. Add GfxTileCanvas to GfxNode's socket map, or use as a drop-in GfxNode
   subclass (see bottom of file)
5. Add "Tile Canvas" to your open_add_node_menu spawner

No other files need to change.
"""

from __future__ import annotations
import numpy as np

from PySide6.QtWidgets import (
    QFileDialog, QPushButton, QApplication,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPen, QPainter, QImage, QPixmap, QFont, QBrush,
)

# ── Import from the host graph module ───────────────────────────────────────
# We import lazily (inside methods) where circular-import risk is highest,
# but pull in the base classes here so the node can be registered normally.
from nodemaker import (
    BaseNode, NodeProperty, register_node,
    PROJECT,
    GfxNode, GfxSocket, _C,
)
from PySide6.QtWidgets import QGraphicsItem
from PySide6.QtGui import QPainterPath


# ============================================================
#  LOGIC NODE
# ============================================================

@register_node
class TileCanvasNode(BaseNode):
    """
    Tile-aware wrapper node.

    Properties
    ----------
    Tile Size   — pixel size of one tile (e.g. 16, 32, 48, 64, 128)
    Columns     — number of tile columns in the atlas
    Rows        — number of tile rows in the atlas
    Cell Seed Offset — added to upstream Noise seeds so each cell varies
                       (0 = all cells identical, useful for uniform floor tiles)
    Show Grid   — whether the preview grid overlay is visible

    Output
    ------
    Passes upstream RGBA through unchanged.  The grid is a preview overlay only
    and is never baked into the pixel data — so the OutputNode and the exported
    PNG are both clean.
    """

    TILE_SIZES = [8, 16, 24, 32, 48, 64, 96, 128, 256]

    def __init__(self):
        super().__init__("Tile Canvas")
        self.inputs = [None]   # slot 0: upstream image

        # ── core tile layout ─────────────────────────────────────────────
        self.add_property("Tile Size",  48,  8,   256)   # px per tile
        self.add_property("Columns",     8,  1,    64)
        self.add_property("Rows",        4,  1,    64)

        # ── per-cell variation helper ─────────────────────────────────────
        # When > 0, the node remaps the output so each tile cell gets a
        # slightly different luminance band — a simple way to feed variance
        # back into any downstream noise without extra nodes.
        # At 0 the pass-through is pixel-perfect.
        self.add_property("Cell Variation", 0.0, 0.0, 1.0)

        # ── preview options ───────────────────────────────────────────────
        self.add_property("Show Grid",  1.0, is_bool=True)

    # ── convenience accessors ─────────────────────────────────────────────

    def tile_size(self, frame=0) -> int:
        return max(1, int(self.properties["Tile Size"].get_value(frame)))

    def columns(self, frame=0) -> int:
        return max(1, int(self.properties["Columns"].get_value(frame)))

    def rows(self, frame=0) -> int:
        return max(1, int(self.properties["Rows"].get_value(frame)))

    def atlas_width(self, frame=0) -> int:
        return self.tile_size(frame) * self.columns(frame)

    def atlas_height(self, frame=0) -> int:
        return self.tile_size(frame) * self.rows(frame)

    # ── evaluate ──────────────────────────────────────────────────────────

    def evaluate(self, frame: int, w: int, h: int) -> np.ndarray:
        """Pass upstream RGBA through; optionally apply per-cell variation."""
        if self.inputs[0] is not None:
            arr = self.inputs[0].evaluate(frame, w, h).copy()
        else:
            arr = np.zeros((h, w, 4), dtype=np.float32)
            arr[..., 3] = 1.0

        variation = self.properties["Cell Variation"].get_value(frame)
        if variation > 0.001 and w > 0 and h > 0:
            cols = self.columns(frame)
            rows_n = self.rows(frame)
            # Build per-pixel cell index map (normalised 0→1 across total cells)
            xs = np.arange(w, dtype=np.float32) / w  # 0→1
            ys = np.arange(h, dtype=np.float32) / h
            col_idx = np.floor(xs * cols).astype(np.int32).clip(0, cols - 1)
            row_idx = np.floor(
                ys.reshape(-1, 1) * rows_n
            ).astype(np.int32).clip(0, rows_n - 1)
            cell_id = (row_idx * cols + col_idx).astype(np.float32)
            # Normalise to 0→1 and mix into luminance
            cell_norm = cell_id / max(cols * rows_n - 1, 1)
            lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
            mixed = lum * (1.0 - variation) + cell_norm * variation
            arr[..., 0] = mixed
            arr[..., 1] = mixed
            arr[..., 2] = mixed

        return np.clip(arr, 0.0, 1.0)

    # ── export ────────────────────────────────────────────────────────────

    def export_atlas(self, frame: int = 0, parent_widget=None) -> str | None:
        """
        Render the atlas at its true native resolution and save as PNG.
        Returns the saved path, or None if cancelled / failed.
        """
        w = self.atlas_width(frame)
        h = self.atlas_height(frame)

        arr = self.evaluate(frame, w, h)
        arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)

        img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()

        path, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Tile Atlas",
            f"tileset_{w}x{h}.png",
            "PNG Image (*.png)",
        )
        if not path:
            return None
        if not path.lower().endswith(".png"):
            path += ".png"

        ok = img.save(path, "PNG")
        return path if ok else None


# ============================================================
#  GRAPHICS NODE  (drop-in replacement for GfxNode)
# ============================================================

class GfxTileCanvas(GfxNode):
    """
    Visual node for TileCanvasNode.

    Extends GfxNode with:
    • Wider card to show tile-layout info
    • Grid overlay drawn in the header area (mini preview)
    • "Export PNG" button embedded in the node body
    """

    HEADER_H = 28
    WIDTH = 200        # wider than the default 150

    def __init__(self, logic_node: TileCanvasNode, scene_ref):
        # We call QGraphicsItem.__init__ directly to avoid GfxNode re-creating
        # sockets before we can set our width.
        QGraphicsItem.__init__(self)
        self.logic = logic_node
        self.scene_ref = scene_ref
        self.width = self.WIDTH
        self.height = 130          # taller to fit the export button
        self.setPos(logic_node.pos)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
        )
        self.in_sockets: list[GfxSocket] = []
        self.out_sockets: list[GfxSocket] = []
        self._init_sockets()
        self._build_export_button()

    # ── sockets ───────────────────────────────────────────────────────────

    def _init_sockets(self):
        self.in_sockets.append(GfxSocket(self, 0, True, "In"))
        self.out_sockets.append(GfxSocket(self, 0, False))

    # ── export button (a QGraphicsProxyWidget) ────────────────────────────

    def _build_export_button(self):
        from PySide6.QtWidgets import QGraphicsProxyWidget
        btn = QPushButton("⬇  Export PNG")
        btn.setFixedSize(self.WIDTH - 16, 26)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: #2a7a4a; color: #e8e6f0;"
            "  border: 1px solid #3aaa6a; border-radius: 4px;"
            "  font-size: 11px; font-weight: bold;"
            "}"
            "QPushButton:hover { background: #3aaa6a; }"
            "QPushButton:pressed { background: #1e5c38; }"
        )
        btn.clicked.connect(self._on_export)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(btn)
        proxy.setPos(8, self.height - 38)
        self._export_proxy = proxy

    def _on_export(self):
        path = self.logic.export_atlas(frame=0, parent_widget=None)
        if path:
            # Brief visual feedback — button text changes for 1.5 s
            btn = self._export_proxy.widget()
            btn.setText("✓  Saved!")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: btn.setText("⬇  Export PNG"))

    # ── bounding rect ──────────────────────────────────────────────────────

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)

    # ── paint ──────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 8
        rect = QRectF(0, 0, self.width, self.height)
        selected = self.isSelected()

        # ── card background ───────────────────────────────────────────────
        painter.setPen(
            QPen(_C["border_sel"] if selected else _C["border"], 1.5 if selected else 1)
        )
        painter.setBrush(QBrush(_C["body_bg"]))
        painter.drawRoundedRect(rect, r, r)

        # ── header ────────────────────────────────────────────────────────
        header_color = QColor(30, 100, 70)   # teal-ish, distinct from other nodes
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(header_color))
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addRoundedRect(QRectF(0, 0, self.width, self.HEADER_H), r, r)
        path.addRect(QRectF(0, self.HEADER_H // 2, self.width, self.HEADER_H // 2))
        painter.drawPath(path)

        # Title
        painter.setPen(_C["text_title"])
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(
            QRectF(8, 0, self.width - 16, self.HEADER_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Tile Canvas",
        )

        # ── tile info text ────────────────────────────────────────────────
        sz = self.logic.tile_size()
        cols = self.logic.columns()
        rows_n = self.logic.rows()
        aw = self.logic.atlas_width()
        ah = self.logic.atlas_height()

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(_C["text_label"])
        info_lines = [
            f"Tile: {sz} px   ·   {cols} × {rows_n}",
            f"Atlas: {aw} × {ah} px",
        ]
        y = self.HEADER_H + 10
        for line in info_lines:
            painter.drawText(QRectF(8, y, self.width - 16, 16), Qt.AlignmentFlag.AlignLeft, line)
            y += 16

        # ── mini grid preview ─────────────────────────────────────────────
        show_grid = bool(self.logic.properties["Show Grid"].get_value(0))
        if show_grid:
            preview_rect = QRectF(8, y + 4, self.width - 16, 36)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(20, 40, 30)))
            painter.drawRoundedRect(preview_rect, 3, 3)

            cell_w = preview_rect.width() / min(cols, 16)
            cell_h = preview_rect.height() / min(rows_n, 8)
            grid_pen = QPen(QColor(60, 180, 100, 140), 0.5)
            painter.setPen(grid_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # vertical lines
            x = preview_rect.x()
            for c in range(min(cols, 16) + 1):
                painter.drawLine(
                    QPointF(x + c * cell_w, preview_rect.y()),
                    QPointF(x + c * cell_w, preview_rect.bottom()),
                )
            # horizontal lines
            yy = preview_rect.y()
            for row in range(min(rows_n, 8) + 1):
                painter.drawLine(
                    QPointF(preview_rect.x(), yy + row * cell_h),
                    QPointF(preview_rect.right(), yy + row * cell_h),
                )

        # ── socket labels are handled by GfxSocket itself ─────────────────

    # ── item change (keep logic pos in sync) ──────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.logic.pos = value
        return super().itemChange(change, value)


# ============================================================
#  REGISTRATION HELPER
# ============================================================

def register_tile_canvas_node(main_window):
    """
    Call this from your AnimationGraphTab (or wherever you build the Add Node
    menu) to wire TileCanvasNode into the existing system.

    Example — in AnimationGraphTab.open_add_node_menu():

        from tile_canvas_node import register_tile_canvas_node
        register_tile_canvas_node(self)   # call once at startup

    Or just do it manually:

        menu.addAction("Tile Canvas", lambda: spawn_tile_canvas(pos))

    See spawn_tile_canvas() below.
    """
    pass   # NODE_TYPES auto-registration happens via @register_node at import


def spawn_tile_canvas(pos: QPointF, graph_tab) -> TileCanvasNode:
    """
    Create a TileCanvasNode + its GfxTileCanvas and add both to the graph.
    Call this from your "Add Node" menu handler.

    graph_tab must have:
        .nodes       list of logic nodes
        .scene       QGraphicsScene
    """
    node = TileCanvasNode()
    node.pos = pos

    gfx = GfxTileCanvas(node, graph_tab.scene)
    graph_tab.nodes.append(node)
    graph_tab.scene.addItem(gfx)
    return node


# ============================================================
#  QUICK STANDALONE TEST
# ============================================================

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow
    from nodemaker import AnimationGraphTab

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = QMainWindow()
    win.setWindowTitle("Tile Canvas Node — Test")
    tab = AnimationGraphTab(win)

    # Inject a TileCanvasNode into the fresh graph
    from PySide6.QtCore import QPointF as _QP
    tc = TileCanvasNode()
    tc.pos = _QP(200, 150)
    gfx = GfxTileCanvas(tc, tab.scene)
    tab.nodes.append(tc)
    tab.scene.addItem(gfx)

    # Connect it to the existing output node
    if tab.output_node:
        tab.output_node.inputs[0] = tc

    win.setCentralWidget(tab)
    win.resize(1200, 800)
    win.show()
    sys.exit(app.exec())

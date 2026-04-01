"""
Vita Adventure Creator — Paper Doll Editor Tab
Hierarchy-based sprite rigging with auto-behaviors (blink, mouth, idle breathing)
and user-defined keyframed macros.
"""

import io
import json
import os
import math
import random
import numpy as np
from PIL import Image as PILImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFrame,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsLineItem,
    QSlider, QAbstractItemView, QComboBox, QLineEdit,
    QDoubleSpinBox, QSpinBox, QCheckBox, QFileDialog,
    QInputDialog, QMessageBox, QSizePolicy, QScrollArea,
    QFormLayout, QGroupBox, QDialog, QDialogButtonBox,
    QListWidget,
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QTimer, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import (
    QColor, QPainter, QPixmap, QPen, QBrush, QTransform, QImage,
)
from models import (
    Project, PaperDollAsset, PaperDollLayer, PaperDollMacro,
    PaperDollKeyframe, BlinkConfig, MouthConfig, IdleBreathingConfig,
    RegisteredImage, AnimationExport,
)
from theme_utils import replace_widget_theme_colors

# ── Aesthetic Constants ────────────────────────────────────────
DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURF2   = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
TEXT    = "#e8e6f0"
DIM     = "#7a7890"

HOOK_MODE_OPTIONS = [
    ("Built-in only", "builtin"),
    ("Built-in + Nodes", "supplement"),
    ("Nodes only", "replace"),
]


def _theme_snapshot():
    return {
        "DARK": DARK,
        "PANEL": PANEL,
        "SURFACE": SURFACE,
        "SURF2": SURF2,
        "BORDER": BORDER,
        "ACCENT": ACCENT,
        "TEXT": TEXT,
        "DIM": DIM,
    }


# ── Shared Helpers ─────────────────────────────────────────────

def _section(title: str):
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; padding-top: 10px;")
    return lbl


def _btn(label: str, accent=False, icon_style=False):
    b = QPushButton(label)
    height = 24 if icon_style else 28
    b.setFixedHeight(height)
    bg = ACCENT if accent else SURF2
    b.setStyleSheet(f"""
        QPushButton {{
            background-color: {bg}; color: white;
            border: 1px solid {BORDER}; border-radius: 4px;
            font-size: 11px; font-weight: 600; padding: 0 8px;
        }}
        QPushButton:hover {{ background-color: {ACCENT}; }}
    """)
    return b


def _keyframe_diamond():
    b = QPushButton("◆")
    b.setFixedSize(20, 20)
    b.setCheckable(True)
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent; color: {DIM}; border: none; font-size: 14px;
            padding: 0; min-width: 0; max-width: 20px; max-height: 20px;
        }}
        QPushButton:checked {{ color: {ACCENT}; }}
        QPushButton:hover {{ color: white; }}
    """)
    return b


def _make_spin(value=0.0, minimum=-9999.0, maximum=9999.0, step=1.0, decimals=1):
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setFixedHeight(24)
    s.setStyleSheet(f"background: {SURF2}; border: 1px solid {BORDER}; color: {TEXT}; padding: 2px 4px;")
    return s


# ── Canvas ─────────────────────────────────────────────────────

class PaperDollCanvas(QGraphicsView):
    """Preview canvas that renders the paper doll layer hierarchy."""

    layer_moved = Signal(str, float, float)       # layer_id, dx, dy
    origin_moved = Signal(str, float, float)      # layer_id, dx, dy
    layer_clicked = Signal(str)                    # layer_id — for selecting via canvas

    ORIGIN_SIZE = 12        # radius of the crosshair grab area

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(0, 0, 960, 544)
        self.setScene(self._scene)
        self.setBackgroundBrush(QColor(DARK))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet(f"border: none; background: {DARK};")
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._pixmap_items: dict[str, QGraphicsPixmapItem] = {}
        self._origin_scene_pos: dict[str, QPointF] = {}     # layer_id -> scene pos of origin
        self._selected_layer_id: str | None = None
        self._dragging: str | None = None
        self._drag_layer_id: str | None = None
        self._drag_start_pos = QPointF()

        # Persistent origin marker items (crosshair + circle) — redrawn on top
        self._origin_circle = None
        self._origin_hline = None
        self._origin_vline = None

        # Preview overrides (set by rebuild caller)
        self._image_swaps: dict[str, str] = {}
        self._scale_offsets: dict[str, float] = {}

    def set_selected_layer(self, layer_id: str | None):
        self._selected_layer_id = layer_id
        self._update_origin_marker()

    def rebuild(self, asset: PaperDollAsset | None, project: Project | None,
                image_swaps: dict[str, str] | None = None,
                scale_offsets: dict[str, float] | None = None):
        self._scene.clear()
        self._pixmap_items.clear()
        self._origin_scene_pos.clear()
        self._origin_circle = None
        self._origin_hline = None
        self._origin_vline = None
        if not asset or not project:
            return
        self._image_swaps = image_swaps or {}
        self._scale_offsets = scale_offsets or {}
        self._draw_layers(asset.root_layers, project, QTransform())
        self._update_origin_marker()

    def _draw_layers(self, layers: list[PaperDollLayer], project: Project, parent_tf: QTransform):
        for layer in layers:
            # Apply preview scale offset if active
            preview_scale = layer.scale + self._scale_offsets.get(layer.id, 0.0)

            tf = QTransform()
            tf.translate(layer.x, layer.y)
            tf.translate(layer.origin_x, layer.origin_y)
            tf.rotate(layer.rotation)
            tf.scale(preview_scale, preview_scale)
            tf.translate(-layer.origin_x, -layer.origin_y)
            composed = tf * parent_tf

            # Determine which image to draw (may be swapped for blink/mouth preview)
            draw_image_id = self._image_swaps.get(layer.id, layer.image_id)

            if draw_image_id:
                img = project.get_image(draw_image_id)
                if img and img.path and os.path.isfile(img.path):
                    pix = QPixmap(img.path)
                    if not pix.isNull():
                        item = self._scene.addPixmap(pix)
                        item.setTransform(composed)
                        item.setData(0, layer.id)
                        self._pixmap_items[layer.id] = item

            # Store the origin's scene-space position for hit testing and marker drawing
            origin_scene = composed.map(QPointF(layer.origin_x, layer.origin_y))
            self._origin_scene_pos[layer.id] = origin_scene

            # Children inherit the full parent transform (position, rotation, scale)
            self._draw_layers(layer.children, project, composed)

    def _update_origin_marker(self):
        """Draw a bright crosshair at the selected layer's origin point."""
        # Remove old marker items
        for item in (self._origin_circle, self._origin_hline, self._origin_vline):
            if item and item.scene():
                self._scene.removeItem(item)
        self._origin_circle = None
        self._origin_hline = None
        self._origin_vline = None

        if not self._selected_layer_id or self._selected_layer_id not in self._origin_scene_pos:
            return

        pos = self._origin_scene_pos[self._selected_layer_id]
        r = self.ORIGIN_SIZE
        pen = QPen(QColor("#ff4488"), 2.0)
        fill = QBrush(QColor("#ff448860"))

        self._origin_circle = self._scene.addEllipse(
            pos.x() - r, pos.y() - r, r * 2, r * 2, pen, fill)
        self._origin_circle.setZValue(2000)

        arm = r + 6
        self._origin_hline = self._scene.addLine(
            pos.x() - arm, pos.y(), pos.x() + arm, pos.y(), pen)
        self._origin_hline.setZValue(2000)

        self._origin_vline = self._scene.addLine(
            pos.x(), pos.y() - arm, pos.x(), pos.y() + arm, pen)
        self._origin_vline.setZValue(2000)

    def _hit_origin(self, scene_pos: QPointF) -> bool:
        """Check if scene_pos is near the selected layer's origin marker."""
        if not self._selected_layer_id or self._selected_layer_id not in self._origin_scene_pos:
            return False
        origin = self._origin_scene_pos[self._selected_layer_id]
        dx = scene_pos.x() - origin.x()
        dy = scene_pos.y() - origin.y()
        return (dx * dx + dy * dy) <= (self.ORIGIN_SIZE + 8) ** 2

    # ── Mouse interaction ──

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        scene_pos = self.mapToScene(event.pos())

        # 1. Check origin marker first (only for selected layer)
        if self._hit_origin(scene_pos):
            self._dragging = "origin"
            self._drag_layer_id = self._selected_layer_id
            self._drag_start_pos = scene_pos
            return

        # 2. Check pixmap items (reverse = front first)
        for lid, item in reversed(list(self._pixmap_items.items())):
            if item.contains(item.mapFromScene(scene_pos)):
                self._dragging = "layer"
                self._drag_layer_id = lid
                self._drag_start_pos = scene_pos
                # Also select this layer in the tree
                self.layer_clicked.emit(lid)
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._dragging or not self._drag_layer_id:
            return super().mouseMoveEvent(event)

        scene_pos = self.mapToScene(event.pos())
        dx = scene_pos.x() - self._drag_start_pos.x()
        dy = scene_pos.y() - self._drag_start_pos.y()

        if self._dragging == "layer":
            self.layer_moved.emit(self._drag_layer_id, dx, dy)
        elif self._dragging == "origin":
            self.origin_moved.emit(self._drag_layer_id, dx, dy)

        self._drag_start_pos = scene_pos

    def mouseReleaseEvent(self, event):
        self._dragging = None
        self._drag_layer_id = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


# ── Timeline Panel ─────────────────────────────────────────────

class KeyframeTrack(QWidget):
    """Draws diamond keyframe markers above the slider."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(20)
        self._keyframe_positions: list[float] = []    # 0.0–1.0 normalized times

    def set_keyframes(self, positions: list[float]):
        self._keyframe_positions = positions
        self.update()

    def paintEvent(self, event):
        if not self._keyframe_positions:
            return
        from PySide6.QtGui import QPainter as _P, QPolygonF
        p = _P(self)
        p.setRenderHint(_P.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))

        w = self.width() - 14       # match slider handle margin
        offset = 7
        size = 5
        for norm in self._keyframe_positions:
            cx = offset + norm * w
            cy = self.height() / 2.0
            diamond = QPolygonF([
                QPointF(cx, cy - size),
                QPointF(cx + size, cy),
                QPointF(cx, cy + size),
                QPointF(cx - size, cy),
            ])
            p.drawPolygon(diamond)
        p.end()


class TimelinePanel(QFrame):
    play_toggled = Signal(bool)
    time_scrubbed = Signal(float)       # 0.0 – 1.0 normalized

    def __init__(self):
        super().__init__()
        self.setFixedHeight(130)
        self.setStyleSheet(f"background: {PANEL}; border-top: 2px solid {BORDER};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self.macro_label = QLabel("NO MACRO SELECTED")
        self.macro_label.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        top.addWidget(self.macro_label)
        top.addStretch()
        self.btn_prev = _btn("◀", icon_style=True)
        self.btn_play = _btn("▶ PLAY", accent=True)
        self.btn_next = _btn("▶", icon_style=True)
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self.play_toggled.emit)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_play)
        top.addWidget(self.btn_next)
        self.time_label = QLabel("0.00 / 0.00")
        self.time_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        top.addWidget(self.time_label)
        layout.addLayout(top)

        self.keyframe_track = KeyframeTrack()
        layout.addWidget(self.keyframe_track)

        self.seeker = QSlider(Qt.Orientation.Horizontal)
        self.seeker.setRange(0, 1000)
        self.seeker.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {DARK}; height: 6px; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -4px 0; border-radius: 7px; }}
        """)
        self.seeker.valueChanged.connect(lambda v: self.time_scrubbed.emit(v / 1000.0))
        layout.addWidget(self.seeker)

    def set_macro(self, macro: PaperDollMacro | None):
        if macro:
            self.macro_label.setText(f"MACRO: {macro.name.upper()}")
            self.time_label.setText(f"0.00 / {macro.duration:.2f}")
            self._update_keyframe_track(macro)
        else:
            self.macro_label.setText("NO MACRO SELECTED")
            self.time_label.setText("0.00 / 0.00")
            self.keyframe_track.set_keyframes([])

    def set_time(self, current: float, duration: float):
        self.time_label.setText(f"{current:.2f} / {duration:.2f}")
        if duration > 0:
            self.seeker.blockSignals(True)
            self.seeker.setValue(int((current / duration) * 1000))
            self.seeker.blockSignals(False)

    def update_keyframes(self, macro: PaperDollMacro | None):
        """Call after keyframes change to refresh the track."""
        self._update_keyframe_track(macro)

    def _update_keyframe_track(self, macro: PaperDollMacro | None):
        if not macro or macro.duration <= 0 or not macro.keyframes:
            self.keyframe_track.set_keyframes([])
            return
        times = sorted(set(k.time for k in macro.keyframes))
        positions = [t / macro.duration for t in times]
        self.keyframe_track.set_keyframes(positions)


# ── Behavior Config Dialog ─────────────────────────────────────

class _LegacyBehaviorConfigDialog(QDialog):
    """Popup dialog for configuring blink, mouth, or idle breathing."""

    def __init__(self, asset: PaperDollAsset, mode: str, project: Project, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.project = project
        self.mode = mode          # "blink" | "mouth" | "idle"
        self.setWindowTitle(f"Configure {mode.title()}")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        self._alt_image_id: str | None = None
        self._build_ui()

    def _collect_layers(self, layers, depth=0):
        result = []
        for l in layers:
            result.append((l.id, "  " * depth + l.name))
            result += self._collect_layers(l.children, depth + 1)
        return result

    def _make_image_row(self, current_image_id: str | None):
        """Create an image selector row with a label, current name, and Browse button."""
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        self._alt_image_label = QLabel("(none)")
        self._alt_image_label.setStyleSheet(f"color: {TEXT}; padding: 2px 6px; background: {SURF2}; border: 1px solid {BORDER};")
        self._alt_image_label.setMinimumWidth(160)
        if current_image_id:
            self._alt_image_id = current_image_id
            img = self.project.get_image(current_image_id)
            if img:
                self._alt_image_label.setText(img.name)
        browse_btn = _btn("Browse…")
        browse_btn.clicked.connect(self._browse_alt_image)
        pick_btn = _btn("Pick…")
        pick_btn.clicked.connect(self._pick_alt_image)
        h.addWidget(self._alt_image_label, stretch=1)
        h.addWidget(pick_btn)
        h.addWidget(browse_btn)
        return container

    def _browse_alt_image(self):
        """Browse filesystem for a new image, register it, set as alt."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Alternate Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        name = os.path.splitext(os.path.basename(path))[0]
        img = RegisteredImage(name=name, path=path, category="character")
        self.project.images.append(img)
        self._alt_image_id = img.id
        self._alt_image_label.setText(img.name)

    def _pick_alt_image(self):
        """Pick from already-registered images."""
        if not self.project.images:
            QMessageBox.information(self, "No Images", "No registered images yet. Use Browse to add one.")
            return
        choices = [img.name for img in self.project.images]
        choice, ok = QInputDialog.getItem(self, "Pick Image", "Select image:", choices, 0, False)
        if not ok:
            return
        idx = choices.index(choice)
        img = self.project.images[idx]
        self._alt_image_id = img.id
        self._alt_image_label.setText(img.name)

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(8)
        all_layers = self._collect_layers(self.asset.root_layers)

        if self.mode == "blink":
            cfg = self.asset.blink
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            layout.addRow("Alt Image (closed):", self._make_image_row(cfg.alt_image_id))

            self.interval_min_spin = _make_spin(cfg.interval_min, 0.1, 30.0, 0.1)
            layout.addRow("Interval Min (s):", self.interval_min_spin)
            self.interval_max_spin = _make_spin(cfg.interval_max, 0.1, 30.0, 0.1)
            layout.addRow("Interval Max (s):", self.interval_max_spin)
            self.duration_spin = _make_spin(cfg.blink_duration, 0.01, 2.0, 0.01, 2)
            layout.addRow("Blink Duration (s):", self.duration_spin)

        elif self.mode == "mouth":
            cfg = self.asset.mouth
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            layout.addRow("Alt Image (open):", self._make_image_row(cfg.alt_image_id))

            self.cycle_spin = _make_spin(cfg.cycle_speed, 0.01, 2.0, 0.01, 2)
            layout.addRow("Cycle Speed (s):", self.cycle_spin)

        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            self.layer_combo.addItem("(Root — all layers)", "")
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            self.scale_spin = _make_spin(cfg.scale_amount, 0.001, 0.5, 0.005, 3)
            layout.addRow("Scale Amount:", self.scale_spin)
            self.speed_spin = _make_spin(cfg.speed, 0.5, 20.0, 0.5)
            layout.addRow("Cycle Speed (s):", self.speed_spin)
            self.children_cb = QCheckBox("Affect Children")
            self.children_cb.setChecked(cfg.affect_children)
            layout.addRow(self.children_cb)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def apply(self):
        """Write widget values back to the asset's config."""
        if self.mode == "blink":
            cfg = self.asset.blink
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.alt_image_id = self._alt_image_id
            cfg.interval_min = self.interval_min_spin.value()
            cfg.interval_max = self.interval_max_spin.value()
            cfg.blink_duration = self.duration_spin.value()
        elif self.mode == "mouth":
            cfg = self.asset.mouth
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.alt_image_id = self._alt_image_id
            cfg.cycle_speed = self.cycle_spin.value()
        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.scale_amount = self.scale_spin.value()
            cfg.speed = self.speed_spin.value()
            cfg.affect_children = self.children_cb.isChecked()


# ── Main Tab Widget ────────────────────────────────────────────

class BehaviorConfigDialog(QDialog):
    """Popup dialog for configuring blink, mouth, or idle breathing."""

    def __init__(self, asset: PaperDollAsset, mode: str, project: Project, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.project = project
        self.mode = mode          # "blink" | "mouth" | "idle"
        self.setWindowTitle(f"Configure {mode.title()}")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        self._alt_image_id: str | None = None
        self._mouth_image_ids: list[str] = []
        self._build_ui()

    def _collect_layers(self, layers, depth=0):
        result = []
        for l in layers:
            result.append((l.id, "  " * depth + l.name))
            result += self._collect_layers(l.children, depth + 1)
        return result

    def _make_hook_mode_combo(self, current_mode: str) -> QComboBox:
        combo = QComboBox()
        for label, value in HOOK_MODE_OPTIONS:
            combo.addItem(label, value)
        idx = combo.findData(current_mode or "builtin")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _make_single_image_row(self, current_image_id: str | None):
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        self._alt_image_label = QLabel("(none)")
        self._alt_image_label.setStyleSheet(
            f"color: {TEXT}; padding: 2px 6px; background: {SURF2}; border: 1px solid {BORDER};"
        )
        self._alt_image_label.setMinimumWidth(160)
        self._alt_image_id = current_image_id
        self._refresh_alt_image_label()
        browse_btn = _btn("Browse...")
        browse_btn.clicked.connect(self._browse_alt_image)
        pick_btn = _btn("Pick...")
        pick_btn.clicked.connect(self._pick_alt_image)
        h.addWidget(self._alt_image_label, stretch=1)
        h.addWidget(pick_btn)
        h.addWidget(browse_btn)
        return container

    def _make_mouth_images_row(self, current_image_ids: list[str]):
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self._mouth_image_ids = [img_id for img_id in current_image_ids if img_id]
        self._mouth_image_list = QListWidget()
        self._mouth_image_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._mouth_image_list.setStyleSheet(
            f"color: {TEXT}; background: {SURF2}; border: 1px solid {BORDER};"
        )
        self._mouth_image_list.setMinimumHeight(110)
        v.addWidget(self._mouth_image_list)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        pick_btn = _btn("Add Existing")
        pick_btn.clicked.connect(self._pick_mouth_image)
        browse_btn = _btn("Browse...")
        browse_btn.clicked.connect(self._browse_mouth_image)
        remove_btn = _btn("Remove")
        remove_btn.clicked.connect(self._remove_mouth_image)
        btn_row.addWidget(pick_btn)
        btn_row.addWidget(browse_btn)
        btn_row.addWidget(remove_btn)
        v.addLayout(btn_row)

        hint = QLabel("Cycles as: base -> shape 1 -> base -> shape 2 -> ...")
        hint.setStyleSheet(f"color: {DIM}; font-size: 10px;")
        v.addWidget(hint)

        self._refresh_mouth_image_list()
        return container

    def _register_image_path(self, path: str) -> RegisteredImage:
        name = os.path.splitext(os.path.basename(path))[0]
        img = RegisteredImage(name=name, path=path, category="character")
        self.project.images.append(img)
        return img

    def _image_choice_entries(self) -> list[tuple[str, RegisteredImage]]:
        entries: list[tuple[str, RegisteredImage]] = []
        for img in self.project.images:
            suffix = os.path.basename(img.path) if img.path else img.id
            entries.append((f"{img.name} [{suffix}]", img))
        return entries

    def _pick_project_image(self, title: str) -> RegisteredImage | None:
        entries = self._image_choice_entries()
        choices = [label for label, _img in entries]
        choice, ok = QInputDialog.getItem(self, title, "Select image:", choices, 0, False)
        if not ok:
            return None
        for label, img in entries:
            if label == choice:
                return img
        return None

    def _refresh_alt_image_label(self):
        if not hasattr(self, "_alt_image_label"):
            return
        if self._alt_image_id:
            img = self.project.get_image(self._alt_image_id)
            self._alt_image_label.setText(img.name if img else f"(missing) {self._alt_image_id}")
        else:
            self._alt_image_label.setText("(none)")

    def _refresh_mouth_image_list(self):
        if not hasattr(self, "_mouth_image_list"):
            return
        self._mouth_image_list.clear()
        for idx, image_id in enumerate(self._mouth_image_ids):
            img = self.project.get_image(image_id)
            label = img.name if img else f"(missing) {image_id}"
            self._mouth_image_list.addItem(f"{idx + 1}. {label}")

    def _browse_alt_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Alternate Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        img = self._register_image_path(path)
        self._alt_image_id = img.id
        self._refresh_alt_image_label()

    def _pick_alt_image(self):
        if not self.project.images:
            QMessageBox.information(self, "No Images", "No registered images yet. Use Browse to add one.")
            return
        img = self._pick_project_image("Pick Image")
        if not img:
            return
        self._alt_image_id = img.id
        self._refresh_alt_image_label()

    def _browse_mouth_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Mouth Shape", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        img = self._register_image_path(path)
        self._mouth_image_ids.append(img.id)
        self._refresh_mouth_image_list()
        self._mouth_image_list.setCurrentRow(len(self._mouth_image_ids) - 1)

    def _pick_mouth_image(self):
        if not self.project.images:
            QMessageBox.information(self, "No Images", "No registered images yet. Use Browse to add one.")
            return
        img = self._pick_project_image("Pick Mouth Shape")
        if not img:
            return
        self._mouth_image_ids.append(img.id)
        self._refresh_mouth_image_list()
        self._mouth_image_list.setCurrentRow(len(self._mouth_image_ids) - 1)

    def _remove_mouth_image(self):
        if not hasattr(self, "_mouth_image_list"):
            return
        row = self._mouth_image_list.currentRow()
        if row < 0 or row >= len(self._mouth_image_ids):
            return
        self._mouth_image_ids.pop(row)
        self._refresh_mouth_image_list()
        if self._mouth_image_ids:
            self._mouth_image_list.setCurrentRow(min(row, len(self._mouth_image_ids) - 1))

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(8)
        all_layers = self._collect_layers(self.asset.root_layers)

        if self.mode == "blink":
            cfg = self.asset.blink
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)
            layout.addRow("Alt Image (closed):", self._make_single_image_row(cfg.alt_image_id))

            self.interval_min_spin = _make_spin(cfg.interval_min, 0.1, 30.0, 0.1)
            layout.addRow("Interval Min (s):", self.interval_min_spin)
            self.interval_max_spin = _make_spin(cfg.interval_max, 0.1, 30.0, 0.1)
            layout.addRow("Interval Max (s):", self.interval_max_spin)
            self.duration_spin = _make_spin(cfg.blink_duration, 0.01, 2.0, 0.01, 2)
            layout.addRow("Blink Duration (s):", self.duration_spin)
            self.hook_mode_combo = self._make_hook_mode_combo(getattr(cfg, "node_hook_mode", "builtin"))
            layout.addRow("Hook Mode:", self.hook_mode_combo)

        elif self.mode == "mouth":
            cfg = self.asset.mouth
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            current_image_ids = cfg.image_ids or ([cfg.alt_image_id] if cfg.alt_image_id else [])
            layout.addRow("Mouth Shapes:", self._make_mouth_images_row(current_image_ids))
            self.cycle_spin = _make_spin(cfg.cycle_speed, 0.01, 2.0, 0.01, 2)
            layout.addRow("Cycle Speed (s):", self.cycle_spin)
            self.hook_mode_combo = self._make_hook_mode_combo(getattr(cfg, "node_hook_mode", "builtin"))
            layout.addRow("Hook Mode:", self.hook_mode_combo)

        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            self.layer_combo.addItem("(Root - all layers)", "")
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            self.scale_spin = _make_spin(cfg.scale_amount, 0.001, 0.5, 0.005, 3)
            layout.addRow("Scale Amount:", self.scale_spin)
            self.speed_spin = _make_spin(cfg.speed, 0.5, 20.0, 0.5)
            layout.addRow("Cycle Speed (s):", self.speed_spin)
            self.children_cb = QCheckBox("Affect Children")
            self.children_cb.setChecked(cfg.affect_children)
            layout.addRow(self.children_cb)
            self.hook_mode_combo = self._make_hook_mode_combo(getattr(cfg, "node_hook_mode", "builtin"))
            layout.addRow("Hook Mode:", self.hook_mode_combo)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def apply(self):
        if self.mode == "blink":
            cfg = self.asset.blink
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.alt_image_id = self._alt_image_id
            cfg.interval_min = self.interval_min_spin.value()
            cfg.interval_max = self.interval_max_spin.value()
            cfg.blink_duration = self.duration_spin.value()
            cfg.node_hook_mode = self.hook_mode_combo.currentData() or "builtin"
        elif self.mode == "mouth":
            cfg = self.asset.mouth
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.image_ids = [img_id for img_id in self._mouth_image_ids if img_id]
            cfg.alt_image_id = cfg.image_ids[0] if cfg.image_ids else None
            cfg.cycle_speed = self.cycle_spin.value()
            cfg.node_hook_mode = self.hook_mode_combo.currentData() or "builtin"
        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.scale_amount = self.scale_spin.value()
            cfg.speed = self.speed_spin.value()
            cfg.affect_children = self.children_cb.isChecked()
            cfg.node_hook_mode = self.hook_mode_combo.currentData() or "builtin"


class MacroExportDialog(QDialog):
    """Prompt for export name and playback FPS."""

    def __init__(self, default_name: str, default_fps: int = 12, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export .ani Spritesheet")
        layout = QFormLayout(self)

        self.name_edit = QLineEdit(default_name)
        self.name_edit.selectAll()
        layout.addRow("Export Name:", self.name_edit)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(default_fps)
        layout.addRow("FPS:", self.fps_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> tuple[str, int]:
        return self.name_edit.text().strip(), self.fps_spin.value()


class PaperDollTab(QWidget):
    """Paper Doll editor tab, integrates into the main app tab bar."""

    changed = Signal()      # emitted whenever data changes (for unsaved dot)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None
        self._current_asset: PaperDollAsset | None = None
        self._selected_layer: PaperDollLayer | None = None
        self._current_macro: PaperDollMacro | None = None
        self._playback_time: float = 0.0
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(16)       # ~60 fps
        self._playback_timer.timeout.connect(self._tick_playback)
        self._suppress_signals = False

        # ── Preview state for unprompted animations ──
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick_preview)
        self._preview_idle = False
        self._preview_blink = False
        self._preview_talk = False
        self._preview_time: float = 0.0
        # Blink state
        self._blink_next: float = 0.0              # time of next blink
        self._blink_active: bool = False            # currently showing alt image
        self._blink_end: float = 0.0                # time blink ends
        # Mouth state
        self._mouth_open: bool = False
        self._mouth_next_toggle: float = 0.0
        self._mouth_shape_index: int = 0
        # Track temp image swaps so canvas can apply them
        self._preview_image_swaps: dict[str, str] = {}  # layer_id -> temp image_id
        # Track temp scale offsets for breathing
        self._preview_scale_offsets: dict[str, float] = {}  # layer_id -> scale delta

        self._build_ui()

    # ── Project wiring (called from main.py) ──

    def load_project(self, project: Project):
        self.project = project
        self._refresh_asset_combo()
        if project.paper_dolls:
            self._current_asset = project.paper_dolls[0]
            self.asset_combo.setCurrentIndex(0)
        else:
            self._current_asset = None
        self._refresh_all()

    def restyle(self, c: dict):
        global DARK, PANEL, SURFACE, SURF2, BORDER, ACCENT, TEXT, DIM
        old = _theme_snapshot()
        DARK = c.get("DARK", DARK)
        PANEL = c.get("PANEL", PANEL)
        SURFACE = c.get("SURFACE", SURFACE)
        SURF2 = c.get("SURFACE2", SURF2)
        BORDER = c.get("BORDER", BORDER)
        ACCENT = c.get("ACCENT", ACCENT)
        TEXT = c.get("TEXT", TEXT)
        DIM = c.get("TEXT_DIM", DIM)
        replace_widget_theme_colors(self, old, _theme_snapshot())

        self.canvas.setBackgroundBrush(QColor(DARK))
        self.canvas.setStyleSheet(f"border: none; background: {DARK};")
        self.timeline.setStyleSheet(f"background: {PANEL}; border-top: 2px solid {BORDER};")
        self.timeline.keyframe_track.update()
        self.timeline.update()
        self.canvas.viewport().update()
        self.update()

    # ── UI Build ───────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Asset selector bar ──
        asset_bar = QHBoxLayout()
        asset_bar.setContentsMargins(10, 6, 10, 6)
        asset_bar.addWidget(QLabel("Animation Asset:"))
        self.asset_combo = QComboBox()
        self.asset_combo.setMinimumWidth(200)
        self.asset_combo.currentIndexChanged.connect(self._on_asset_changed)
        asset_bar.addWidget(self.asset_combo)
        self.btn_new_asset = _btn("+ New", accent=True)
        self.btn_new_asset.clicked.connect(self._new_asset)
        asset_bar.addWidget(self.btn_new_asset)
        self.btn_rename_asset = _btn("Rename")
        self.btn_rename_asset.clicked.connect(self._rename_asset)
        asset_bar.addWidget(self.btn_rename_asset)
        self.btn_delete_asset = _btn("Delete")
        self.btn_delete_asset.clicked.connect(self._delete_asset)
        asset_bar.addWidget(self.btn_delete_asset)
        asset_bar.addStretch()
        root.addLayout(asset_bar)

        # ── Upper area: left / center / right ──
        upper = QHBoxLayout()

        # LEFT: Hierarchy
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        left_vbox = QVBoxLayout(left_panel)
        left_vbox.setContentsMargins(8, 8, 8, 8)
        left_vbox.addWidget(_section("Hierarchy & Parenting"))

        topo_bar = QHBoxLayout()
        self.btn_move_up = _btn("↑", icon_style=True)
        self.btn_move_down = _btn("↓", icon_style=True)
        self.btn_unparent = _btn("←", icon_style=True)
        self.btn_reparent = _btn("→", icon_style=True)
        self.btn_delete_layer = _btn("DEL", icon_style=True)
        self.btn_move_up.clicked.connect(self._move_layer_up)
        self.btn_move_down.clicked.connect(self._move_layer_down)
        self.btn_unparent.clicked.connect(self._unparent_layer)
        self.btn_reparent.clicked.connect(self._reparent_layer)
        self.btn_delete_layer.clicked.connect(self._delete_layer)
        for b in [self.btn_move_up, self.btn_move_down, self.btn_unparent, self.btn_reparent]:
            topo_bar.addWidget(b)
        topo_bar.addStretch()
        topo_bar.addWidget(self.btn_delete_layer)
        left_vbox.addLayout(topo_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER};")
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        left_vbox.addWidget(self.tree)

        self.btn_add_layer = _btn("+ Add Layer from Image…", accent=True)
        self.btn_add_layer.clicked.connect(self._add_layer_from_image)
        left_vbox.addWidget(self.btn_add_layer)
        upper.addWidget(left_panel)

        # CENTER: Canvas
        canvas_container = QWidget()
        canvas_vbox = QVBoxLayout(canvas_container)
        canvas_vbox.setContentsMargins(4, 4, 4, 4)
        self.canvas = PaperDollCanvas()
        self.canvas.layer_moved.connect(self._on_canvas_layer_moved)
        self.canvas.origin_moved.connect(self._on_canvas_origin_moved)
        self.canvas.layer_clicked.connect(self._on_canvas_layer_clicked)
        canvas_vbox.addWidget(self.canvas)
        upper.addWidget(canvas_container, stretch=1)

        # RIGHT: Properties & Macros (scrollable)
        right_scroll = QScrollArea()
        right_scroll.setFixedWidth(360)
        right_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        right_panel = QWidget()
        right_vbox = QVBoxLayout(right_panel)
        right_vbox.setContentsMargins(6, 8, 6, 8)

        # -- Layer name --
        right_vbox.addWidget(_section("Selected Layer"))
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.layer_name_edit = QLineEdit()
        self.layer_name_edit.setStyleSheet(f"background: {SURF2}; border: 1px solid {BORDER}; color: {TEXT}; padding: 3px;")
        self.layer_name_edit.editingFinished.connect(self._on_layer_name_changed)
        name_row.addWidget(self.layer_name_edit)
        right_vbox.addLayout(name_row)

        # -- Transform properties --
        prop_frame = QFrame()
        prop_frame.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;")
        pf_layout = QVBoxLayout(prop_frame)
        pf_layout.setContentsMargins(6, 6, 6, 6)

        self.prop_spins: dict[str, QDoubleSpinBox] = {}
        self.prop_diamonds: dict[str, QPushButton] = {}
        for prop_name, default_val in [("X Offset", 0.0), ("Y Offset", 0.0), ("Rotation", 0.0), ("Scale", 1.0)]:
            row = QHBoxLayout()
            row.setContentsMargins(2, 2, 2, 2)
            diamond = _keyframe_diamond()
            diamond.setProperty("prop_name", prop_name)
            diamond.clicked.connect(self._on_keyframe_diamond_clicked)
            row.addWidget(diamond)
            row.addWidget(QLabel(prop_name))
            if prop_name == "Scale":
                spin = _make_spin(default_val, 0.01, 50.0, 0.05, 2)
            elif prop_name == "Rotation":
                spin = _make_spin(default_val, -360.0, 360.0, 1.0, 1)
            else:
                spin = _make_spin(default_val, -9999.0, 9999.0, 1.0, 1)
            spin.valueChanged.connect(self._on_property_spin_changed)
            spin.setProperty("prop_name", prop_name)
            row.addWidget(spin)
            self.prop_spins[prop_name] = spin
            self.prop_diamonds[prop_name] = diamond
            pf_layout.addLayout(row)

        # Origin display
        origin_row = QHBoxLayout()
        origin_row.setContentsMargins(2, 6, 2, 2)
        origin_row.addWidget(QLabel("Origin:"))
        self.origin_x_spin = _make_spin(0.0, -9999, 9999, 1.0, 1)
        self.origin_y_spin = _make_spin(0.0, -9999, 9999, 1.0, 1)
        self.origin_x_spin.valueChanged.connect(self._on_origin_changed)
        self.origin_y_spin.valueChanged.connect(self._on_origin_changed)
        origin_row.addWidget(QLabel("X"))
        origin_row.addWidget(self.origin_x_spin)
        origin_row.addWidget(QLabel("Y"))
        origin_row.addWidget(self.origin_y_spin)
        pf_layout.addLayout(origin_row)

        right_vbox.addWidget(prop_frame)

        # -- Behaviors --
        right_vbox.addWidget(_section("Behaviors"))

        blink_row = QHBoxLayout()
        blink_row.setSpacing(4)
        self.btn_config_blink = _btn("Blink…")
        self.btn_config_blink.clicked.connect(lambda: self._open_behavior_dialog("blink"))
        self.btn_preview_blink = _btn("▶ Preview", icon_style=True)
        self.btn_preview_blink.setCheckable(True)
        self.btn_preview_blink.toggled.connect(self._toggle_preview_blink)
        self.btn_config_blink.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_preview_blink.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        blink_row.addWidget(self.btn_config_blink, 1)
        blink_row.addWidget(self.btn_preview_blink, 1)
        right_vbox.addLayout(blink_row)

        mouth_row = QHBoxLayout()
        mouth_row.setSpacing(4)
        self.btn_config_mouth = _btn("Talk…")
        self.btn_config_mouth.clicked.connect(lambda: self._open_behavior_dialog("mouth"))
        self.btn_preview_talk = _btn("▶ Preview", icon_style=True)
        self.btn_preview_talk.setCheckable(True)
        self.btn_preview_talk.toggled.connect(self._toggle_preview_talk)
        self.btn_config_mouth.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_preview_talk.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mouth_row.addWidget(self.btn_config_mouth, 1)
        mouth_row.addWidget(self.btn_preview_talk, 1)
        right_vbox.addLayout(mouth_row)

        idle_row = QHBoxLayout()
        idle_row.setSpacing(4)
        self.btn_config_idle = _btn("Idle…")
        self.btn_config_idle.clicked.connect(lambda: self._open_behavior_dialog("idle"))
        self.btn_preview_idle = _btn("▶ Preview", icon_style=True)
        self.btn_preview_idle.setCheckable(True)
        self.btn_preview_idle.toggled.connect(self._toggle_preview_idle)
        self.btn_config_idle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_preview_idle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        idle_row.addWidget(self.btn_config_idle, 1)
        idle_row.addWidget(self.btn_preview_idle, 1)
        right_vbox.addLayout(idle_row)

        # -- Macros --
        right_vbox.addWidget(_section("Macros"))
        self.macro_list = QTreeWidget()
        self.macro_list.setHeaderHidden(True)
        self.macro_list.setMaximumHeight(160)
        self.macro_list.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER};")
        self.macro_list.currentItemChanged.connect(self._on_macro_selection_changed)
        right_vbox.addWidget(self.macro_list)

        macro_btns = QHBoxLayout()
        self.btn_new_macro = _btn("+ New Macro", accent=True)
        self.btn_new_macro.clicked.connect(self._new_macro)
        self.btn_rename_macro = _btn("Rename")
        self.btn_rename_macro.clicked.connect(self._rename_macro)
        self.btn_delete_macro = _btn("Delete")
        self.btn_delete_macro.clicked.connect(self._delete_macro)
        self.btn_new_macro.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_rename_macro.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_delete_macro.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        macro_btns.addWidget(self.btn_new_macro, 2)
        macro_btns.addWidget(self.btn_rename_macro, 1)
        macro_btns.addWidget(self.btn_delete_macro, 1)
        right_vbox.addLayout(macro_btns)

        self.btn_export_macro_ani = _btn("Export .ani Spritesheet")
        self.btn_export_macro_ani.clicked.connect(self._export_current_macro_ani)
        self.btn_export_macro_ani.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right_vbox.addWidget(self.btn_export_macro_ani)

        # Macro duration
        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (s):"))
        self.macro_duration_spin = _make_spin(1.0, 0.1, 60.0, 0.1)
        self.macro_duration_spin.valueChanged.connect(self._on_macro_duration_changed)
        dur_row.addWidget(self.macro_duration_spin)
        self.macro_loop_cb = QCheckBox("Loop")
        self.macro_loop_cb.toggled.connect(self._on_macro_loop_changed)
        dur_row.addWidget(self.macro_loop_cb)
        right_vbox.addLayout(dur_row)

        right_vbox.addStretch()
        right_scroll.setWidget(right_panel)
        upper.addWidget(right_scroll)

        root.addLayout(upper, stretch=1)

        # ── Timeline ──
        self.timeline = TimelinePanel()
        self.timeline.play_toggled.connect(self._on_play_toggled)
        self.timeline.time_scrubbed.connect(self._on_time_scrubbed)
        self.timeline.btn_prev.clicked.connect(self._keyframe_prev)
        self.timeline.btn_next.clicked.connect(self._keyframe_next)
        root.addWidget(self.timeline)

    # ── Asset management ───────────────────────────────────────

    def _refresh_asset_combo(self):
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        if self.project:
            for a in self.project.paper_dolls:
                self.asset_combo.addItem(a.name, a.id)
        self.asset_combo.blockSignals(False)

    def _on_asset_changed(self, idx):
        if not self.project or idx < 0:
            self._current_asset = None
        else:
            aid = self.asset_combo.itemData(idx)
            self._current_asset = self.project.get_paper_doll(aid)
        self._selected_layer = None
        self._current_macro = None
        self._refresh_all()

    def _new_asset(self):
        if not self.project:
            return
        name, ok = QInputDialog.getText(self, "New Animation", "Name:")
        if not ok or not name.strip():
            return
        asset = PaperDollAsset(name=name.strip())
        self.project.paper_dolls.append(asset)
        self._current_asset = asset
        self._selected_layer = None
        self._current_macro = None
        self._refresh_asset_combo()
        self.asset_combo.blockSignals(True)
        self.asset_combo.setCurrentIndex(len(self.project.paper_dolls) - 1)
        self.asset_combo.blockSignals(False)
        self._refresh_all()
        self._mark_changed()

    def _rename_asset(self):
        if not self._current_asset:
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=self._current_asset.name)
        if ok and name.strip():
            self._current_asset.name = name.strip()
            idx = self.asset_combo.currentIndex()
            self.asset_combo.setItemText(idx, name.strip())
            self._mark_changed()

    def _delete_asset(self):
        if not self._current_asset or not self.project:
            return
        r = QMessageBox.question(self, "Delete", f"Delete '{self._current_asset.name}'?")
        if r != QMessageBox.StandardButton.Yes:
            return
        self.project.paper_dolls.remove(self._current_asset)
        self._current_asset = None
        self._selected_layer = None
        self._refresh_asset_combo()
        if self.project.paper_dolls:
            self.asset_combo.setCurrentIndex(0)
        self._refresh_all()
        self._mark_changed()

    # ── Hierarchy management ───────────────────────────────────

    def _refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        if self._current_asset:
            self._populate_tree(self._current_asset.root_layers, self.tree.invisibleRootItem())
        self.tree.expandAll()
        # Re-select
        if self._selected_layer:
            self._select_tree_item(self._selected_layer.id)
        self.tree.blockSignals(False)

    def _populate_tree(self, layers: list[PaperDollLayer], parent_item):
        for layer in layers:
            item = QTreeWidgetItem(parent_item, [layer.name])
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
            self._populate_tree(layer.children, item)

    def _select_tree_item(self, layer_id: str):
        """Find and select a tree item by layer ID."""
        def _find(parent, lid):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == lid:
                    return child
                found = _find(child, lid)
                if found:
                    return found
            return None
        item = _find(self.tree.invisibleRootItem(), layer_id)
        if item:
            self.tree.setCurrentItem(item)

    def _on_tree_selection_changed(self, current, previous):
        if not current or not self._current_asset:
            self._selected_layer = None
        else:
            lid = current.data(0, Qt.ItemDataRole.UserRole)
            self._selected_layer = self._current_asset.find_layer(lid)
        self._refresh_properties()
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _find_layer_parent_and_list(self, layer_id: str, layers=None, parent=None):
        """Return (parent_list, index, parent_layer_or_None)."""
        if layers is None:
            layers = self._current_asset.root_layers if self._current_asset else []
        for i, l in enumerate(layers):
            if l.id == layer_id:
                return layers, i, parent
            result = self._find_layer_parent_and_list(layer_id, l.children, l)
            if result:
                return result
        return None

    def _add_layer_from_image(self):
        if not self.project:
            return
        if not self._current_asset:
            QMessageBox.information(self, "No Animation",
                "Create animation asset first using the '+ New' button above.")
            return

        img = None

        # If project already has registered images, let user choose or browse
        if self.project.images:
            choices = [f"{i.name}" for i in self.project.images] + ["— Browse for new image…"]
            choice, ok = QInputDialog.getItem(self, "Add Layer", "Select image:", choices, len(choices) - 1, False)
            if not ok:
                return
            if choice == "— Browse for new image…":
                img = self._browse_and_register_image()
            else:
                idx = choices.index(choice)
                img = self.project.images[idx]
        else:
            # No registered images — go straight to file browser
            img = self._browse_and_register_image()

        if not img:
            return

        # Create layer
        layer = PaperDollLayer(name=img.name, image_id=img.id)
        # Default origin to center of image
        if img.path and os.path.isfile(img.path):
            pix = QPixmap(img.path)
            if not pix.isNull():
                layer.origin_x = pix.width() / 2.0
                layer.origin_y = pix.height() / 2.0

        # Add as child of selected, or at root
        if self._selected_layer:
            self._selected_layer.children.append(layer)
        else:
            self._current_asset.root_layers.append(layer)

        self._selected_layer = layer
        self._refresh_tree()
        self._refresh_properties()
        self._refresh_canvas()
        self._mark_changed()

    def _browse_and_register_image(self):
        """Open file dialog, register the image to the project, return RegisteredImage or None."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Image(s)", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not paths:
            return None
        # Register first image (or all if multi-select — but return first for the layer)
        first_img = None
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            img = RegisteredImage(name=name, path=path, category="character")
            self.project.images.append(img)
            if first_img is None:
                first_img = img
            # If multiple selected, add extra layers for the rest
            if first_img is not img and self._current_asset:
                extra_layer = PaperDollLayer(name=img.name, image_id=img.id)
                if img.path and os.path.isfile(img.path):
                    pix = QPixmap(img.path)
                    if not pix.isNull():
                        extra_layer.origin_x = pix.width() / 2.0
                        extra_layer.origin_y = pix.height() / 2.0
                if self._selected_layer:
                    self._selected_layer.children.append(extra_layer)
                else:
                    self._current_asset.root_layers.append(extra_layer)
        return first_img

    def _delete_layer(self):
        if not self._selected_layer or not self._current_asset:
            return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result:
            return
        parent_list, idx, _ = result
        parent_list.pop(idx)
        self._selected_layer = None
        self.canvas.set_selected_layer(None)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    def _move_layer_up(self):
        if not self._selected_layer or not self._current_asset:
            return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result:
            return
        parent_list, idx, _ = result
        if idx > 0:
            parent_list[idx], parent_list[idx - 1] = parent_list[idx - 1], parent_list[idx]
            self._refresh_tree()
            self._refresh_canvas()
            self._mark_changed()

    def _move_layer_down(self):
        if not self._selected_layer or not self._current_asset:
            return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result:
            return
        parent_list, idx, _ = result
        if idx < len(parent_list) - 1:
            parent_list[idx], parent_list[idx + 1] = parent_list[idx + 1], parent_list[idx]
            self._refresh_tree()
            self._refresh_canvas()
            self._mark_changed()

    def _unparent_layer(self):
        """Move selected layer up one level in the hierarchy."""
        if not self._selected_layer or not self._current_asset:
            return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result:
            return
        parent_list, idx, parent_layer = result
        if parent_layer is None:
            return  # already at root
        layer = parent_list.pop(idx)
        # Find grandparent list
        gp_result = self._find_layer_parent_and_list(parent_layer.id)
        if gp_result:
            gp_list, gp_idx, _ = gp_result
            gp_list.insert(gp_idx + 1, layer)
        else:
            self._current_asset.root_layers.append(layer)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    def _reparent_layer(self):
        """Make selected layer a child of the layer above it in the same list."""
        if not self._selected_layer or not self._current_asset:
            return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result:
            return
        parent_list, idx, _ = result
        if idx == 0:
            return  # nothing above to become parent
        layer = parent_list.pop(idx)
        new_parent = parent_list[idx - 1]
        new_parent.children.append(layer)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    # ── Properties panel ───────────────────────────────────────

    def _refresh_properties(self):
        self._suppress_signals = True
        layer = self._selected_layer
        has_layer = layer is not None

        self.layer_name_edit.setEnabled(has_layer)
        for spin in self.prop_spins.values():
            spin.setEnabled(has_layer)
        self.origin_x_spin.setEnabled(has_layer)
        self.origin_y_spin.setEnabled(has_layer)

        if layer:
            self.layer_name_edit.setText(layer.name)
            self.prop_spins["X Offset"].setValue(layer.x)
            self.prop_spins["Y Offset"].setValue(layer.y)
            self.prop_spins["Rotation"].setValue(layer.rotation)
            self.prop_spins["Scale"].setValue(layer.scale)
            self.origin_x_spin.setValue(layer.origin_x)
            self.origin_y_spin.setValue(layer.origin_y)
        else:
            self.layer_name_edit.clear()
            for spin in self.prop_spins.values():
                spin.setValue(0.0)
            self.origin_x_spin.setValue(0.0)
            self.origin_y_spin.setValue(0.0)

        self._suppress_signals = False

    def _on_layer_name_changed(self):
        if self._suppress_signals or not self._selected_layer:
            return
        self._selected_layer.name = self.layer_name_edit.text()
        # Update tree item text
        item = self.tree.currentItem()
        if item:
            item.setText(0, self._selected_layer.name)
        self._mark_changed()

    def _on_property_spin_changed(self, value):
        if self._suppress_signals or not self._selected_layer:
            return
        sender = self.sender()
        prop_name = sender.property("prop_name")
        if prop_name == "X Offset":
            self._selected_layer.x = value
        elif prop_name == "Y Offset":
            self._selected_layer.y = value
        elif prop_name == "Rotation":
            self._selected_layer.rotation = value
        elif prop_name == "Scale":
            self._selected_layer.scale = value
        self._refresh_canvas()
        self._mark_changed()

    def _on_origin_changed(self, _value):
        if self._suppress_signals or not self._selected_layer:
            return
        self._selected_layer.origin_x = self.origin_x_spin.value()
        self._selected_layer.origin_y = self.origin_y_spin.value()
        self._refresh_canvas()
        self._mark_changed()

    # ── Canvas interaction ─────────────────────────────────────

    def _on_canvas_layer_moved(self, layer_id: str, dx: float, dy: float):
        if not self._current_asset:
            return
        layer = self._current_asset.find_layer(layer_id)
        if not layer:
            return
        layer.x += dx
        layer.y += dy
        self._selected_layer = layer
        self.canvas.set_selected_layer(layer_id)
        self._select_tree_item(layer_id)
        self._refresh_properties()
        self._refresh_canvas()
        self._mark_changed()

    def _on_canvas_origin_moved(self, layer_id: str, dx: float, dy: float):
        if not self._current_asset:
            return
        layer = self._current_asset.find_layer(layer_id)
        if not layer:
            return
        layer.origin_x += dx
        layer.origin_y += dy
        self._refresh_properties()
        self._refresh_canvas()
        self._mark_changed()

    def _on_canvas_layer_clicked(self, layer_id: str):
        """Select a layer by clicking it on the canvas."""
        if not self._current_asset:
            return
        layer = self._current_asset.find_layer(layer_id)
        if layer:
            self._selected_layer = layer
            self._select_tree_item(layer_id)
            self._refresh_properties()
            self.canvas.set_selected_layer(layer_id)

    # ── Behavior config ────────────────────────────────────────

    def _open_behavior_dialog(self, mode: str):
        if not self._current_asset or not self.project:
            QMessageBox.information(self, "No Asset", "Create or select an animation asset first.")
            return
        dlg = BehaviorConfigDialog(self._current_asset, mode, self.project, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply()
            self._mark_changed()

    # ── Behavior preview ───────────────────────────────────────

    def _any_preview_active(self):
        return self._preview_idle or self._preview_blink or self._preview_talk

    def _ensure_preview_timer(self):
        if self._any_preview_active():
            if not self._preview_timer.isActive():
                self._preview_time = 0.0
                self._preview_timer.start()
        else:
            self._preview_timer.stop()
            self._preview_image_swaps.clear()
            self._preview_scale_offsets.clear()
            self._refresh_canvas()

    def _toggle_preview_idle(self, checked: bool):
        self._preview_idle = checked
        if not checked:
            self._preview_scale_offsets.clear()
            self._refresh_canvas()
        self._ensure_preview_timer()

    def _toggle_preview_blink(self, checked: bool):
        self._preview_blink = checked
        if checked:
            self._blink_active = False
            self._blink_next = self._preview_time + 1.0
        else:
            # Restore original image
            if self._current_asset and self._current_asset.blink.layer_id:
                self._preview_image_swaps.pop(self._current_asset.blink.layer_id, None)
            self._refresh_canvas()
        self._ensure_preview_timer()

    def _toggle_preview_talk(self, checked: bool):
        self._preview_talk = checked
        if checked:
            self._mouth_open = False
            self._mouth_shape_index = 0
            self._mouth_next_toggle = self._preview_time
        else:
            if self._current_asset and self._current_asset.mouth.layer_id:
                self._preview_image_swaps.pop(self._current_asset.mouth.layer_id, None)
            self._refresh_canvas()
        self._ensure_preview_timer()

    def _tick_preview(self):
        if not self._current_asset:
            return
        dt = 0.016
        self._preview_time += dt

        # ── Idle breathing ──
        if self._preview_idle:
            cfg = self._current_asset.idle_breathing
            if cfg.enabled and cfg.speed > 0 and getattr(cfg, "node_hook_mode", "builtin") != "replace":
                phase = (self._preview_time / cfg.speed) * math.pi * 2
                offset = math.sin(phase) * cfg.scale_amount
                target_id = cfg.layer_id if cfg.layer_id else None
                # If no specific layer, apply to all root layers
                if target_id:
                    self._preview_scale_offsets = {target_id: offset}
                else:
                    self._preview_scale_offsets = {
                        l.id: offset for l in self._current_asset.root_layers
                    }
            else:
                self._preview_scale_offsets.clear()

        # ── Blink ──
        if self._preview_blink:
            cfg = self._current_asset.blink
            if (
                cfg.enabled
                and getattr(cfg, "node_hook_mode", "builtin") != "replace"
                and cfg.layer_id
                and cfg.alt_image_id
            ):
                if self._blink_active:
                    if self._preview_time >= self._blink_end:
                        self._blink_active = False
                        self._preview_image_swaps.pop(cfg.layer_id, None)
                        interval = random.uniform(cfg.interval_min, cfg.interval_max)
                        self._blink_next = self._preview_time + interval
                else:
                    if self._preview_time >= self._blink_next:
                        self._blink_active = True
                        self._blink_end = self._preview_time + cfg.blink_duration
                        self._preview_image_swaps[cfg.layer_id] = cfg.alt_image_id

        # ── Mouth ──
        if self._preview_talk:
            cfg = self._current_asset.mouth
            image_ids = [img_id for img_id in getattr(cfg, "image_ids", []) if img_id]
            if cfg.enabled and cfg.layer_id and cfg.cycle_speed > 0:
                if self._preview_time >= self._mouth_next_toggle:
                    self._mouth_next_toggle = self._preview_time + cfg.cycle_speed
                    if self._mouth_open:
                        self._mouth_open = False
                        self._preview_image_swaps.pop(cfg.layer_id, None)
                    else:
                        self._mouth_open = True
                        if (
                            image_ids
                            and getattr(cfg, "node_hook_mode", "builtin") != "replace"
                        ):
                            image_id = image_ids[self._mouth_shape_index % len(image_ids)]
                            self._preview_image_swaps[cfg.layer_id] = image_id
                        else:
                            self._preview_image_swaps.pop(cfg.layer_id, None)
                        if image_ids:
                            self._mouth_shape_index = (self._mouth_shape_index + 1) % len(image_ids)

        self._refresh_canvas_preview()

    # ── Macro management ───────────────────────────────────────

    def _refresh_macro_list(self):
        self.macro_list.blockSignals(True)
        self.macro_list.clear()
        if self._current_asset:
            for m in self._current_asset.macros:
                item = QTreeWidgetItem(self.macro_list, [m.name])
                item.setData(0, Qt.ItemDataRole.UserRole, m.id)
        self.macro_list.blockSignals(False)

    def _on_macro_selection_changed(self, current, previous):
        if not current or not self._current_asset:
            self._current_macro = None
        else:
            mid = current.data(0, Qt.ItemDataRole.UserRole)
            self._current_macro = next((m for m in self._current_asset.macros if m.id == mid), None)

        self._suppress_signals = True
        if self._current_macro:
            self.macro_duration_spin.setEnabled(True)
            self.macro_loop_cb.setEnabled(True)
            self.macro_duration_spin.setValue(self._current_macro.duration)
            self.macro_loop_cb.setChecked(self._current_macro.loop)
        else:
            self.macro_duration_spin.setEnabled(False)
            self.macro_loop_cb.setEnabled(False)
        self._suppress_signals = False

        self.timeline.set_macro(self._current_macro)
        self._playback_time = 0.0

    def _new_macro(self):
        if not self._current_asset:
            return
        name, ok = QInputDialog.getText(self, "New Macro", "Macro name:")
        if not ok or not name.strip():
            return
        macro = PaperDollMacro(name=name.strip())
        self._current_asset.macros.append(macro)
        self._refresh_macro_list()
        # Select new macro
        for i in range(self.macro_list.topLevelItemCount()):
            item = self.macro_list.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == macro.id:
                self.macro_list.setCurrentItem(item)
                break
        self._mark_changed()

    def _rename_macro(self):
        if not self._current_macro:
            return
        name, ok = QInputDialog.getText(self, "Rename Macro", "New name:", text=self._current_macro.name)
        if ok and name.strip():
            self._current_macro.name = name.strip()
            self._refresh_macro_list()
            self.timeline.set_macro(self._current_macro)
            self._mark_changed()

    def _delete_macro(self):
        if not self._current_macro or not self._current_asset:
            return
        self._current_asset.macros.remove(self._current_macro)
        self._current_macro = None
        self._refresh_macro_list()
        self.timeline.set_macro(None)
        self._mark_changed()

    def _on_macro_duration_changed(self, value):
        if self._suppress_signals or not self._current_macro:
            return
        self._current_macro.duration = value
        self.timeline.set_macro(self._current_macro)
        self._mark_changed()

    def _on_macro_loop_changed(self, checked):
        if self._suppress_signals or not self._current_macro:
            return
        self._current_macro.loop = checked
        self._mark_changed()

    # ── Keyframing ─────────────────────────────────────────────

    def _on_keyframe_diamond_clicked(self):
        """Toggle a keyframe at current playback time for the selected layer."""
        if not self._current_macro or not self._selected_layer:
            return
        time = self._playback_time
        lid = self._selected_layer.id

        # Check if keyframe exists at this time for this layer
        existing = [k for k in self._current_macro.keyframes
                    if k.layer_id == lid and abs(k.time - time) < 0.01]

        if existing:
            # Update existing keyframe with current property values
            kf = existing[0]
            kf.x = self._selected_layer.x
            kf.y = self._selected_layer.y
            kf.rotation = self._selected_layer.rotation
            kf.scale = self._selected_layer.scale
        else:
            # Create new keyframe with current values
            kf = PaperDollKeyframe(
                time=round(time, 3),
                layer_id=lid,
                x=self._selected_layer.x,
                y=self._selected_layer.y,
                rotation=self._selected_layer.rotation,
                scale=self._selected_layer.scale,
            )
            self._current_macro.keyframes.append(kf)
            self._current_macro.keyframes.sort(key=lambda k: k.time)

        self.timeline.update_keyframes(self._current_macro)
        self._mark_changed()

    def _keyframe_prev(self):
        """Jump to previous keyframe time."""
        if not self._current_macro or not self._current_macro.keyframes:
            return
        times = sorted(set(k.time for k in self._current_macro.keyframes))
        prev_times = [t for t in times if t < self._playback_time - 0.01]
        if prev_times:
            self._playback_time = prev_times[-1]
        else:
            self._playback_time = 0.0
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    def _keyframe_next(self):
        """Jump to next keyframe time."""
        if not self._current_macro or not self._current_macro.keyframes:
            return
        times = sorted(set(k.time for k in self._current_macro.keyframes))
        next_times = [t for t in times if t > self._playback_time + 0.01]
        if next_times:
            self._playback_time = next_times[0]
        else:
            self._playback_time = self._current_macro.duration
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    # ── Playback ───────────────────────────────────────────────

    def _on_play_toggled(self, playing: bool):
        if playing and self._current_macro:
            self._playback_timer.start()
        else:
            self._playback_timer.stop()

    def _on_time_scrubbed(self, normalized: float):
        if not self._current_macro:
            return
        self._playback_time = normalized * self._current_macro.duration
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    def _tick_playback(self):
        if not self._current_macro:
            self._playback_timer.stop()
            return
        dt = 0.016
        self._playback_time += dt
        if self._playback_time >= self._current_macro.duration:
            if self._current_macro.loop:
                self._playback_time = 0.0
            else:
                self._playback_time = self._current_macro.duration
                self._playback_timer.stop()
                self.timeline.btn_play.setChecked(False)

        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    def _apply_macro_at_time(self, t: float):
        """Interpolate all keyframed layers to time t and refresh canvas."""
        if not self._current_macro or not self._current_asset:
            return

        # Group keyframes by layer
        by_layer: dict[str, list[PaperDollKeyframe]] = {}
        for kf in self._current_macro.keyframes:
            by_layer.setdefault(kf.layer_id, []).append(kf)

        for lid, kfs in by_layer.items():
            layer = self._current_asset.find_layer(lid)
            if not layer:
                continue
            kfs_sorted = sorted(kfs, key=lambda k: k.time)
            # Find bounding keyframes
            before = None
            after = None
            for kf in kfs_sorted:
                if kf.time <= t:
                    before = kf
                if kf.time >= t and after is None:
                    after = kf

            if before and after and before is not after:
                # Lerp
                span = after.time - before.time
                frac = (t - before.time) / span if span > 0 else 0.0
                layer.x = before.x + (after.x - before.x) * frac
                layer.y = before.y + (after.y - before.y) * frac
                layer.rotation = before.rotation + (after.rotation - before.rotation) * frac
                layer.scale = before.scale + (after.scale - before.scale) * frac
            elif before:
                layer.x = before.x
                layer.y = before.y
                layer.rotation = before.rotation
                layer.scale = before.scale
            elif after:
                layer.x = after.x
                layer.y = after.y
                layer.rotation = after.rotation
                layer.scale = after.scale

        self._refresh_properties()
        self._refresh_canvas()

    # ── Refresh helpers ────────────────────────────────────────

    def _iter_layers(self, layers: list[PaperDollLayer]):
        for layer in layers:
            yield layer
            yield from self._iter_layers(layer.children)

    def _default_export_name(self) -> str:
        asset_name = self._current_asset.name.strip() if self._current_asset else "paperdoll"
        macro_name = self._current_macro.name.strip() if self._current_macro else "macro"
        return f"{asset_name}_{macro_name}".strip("_")

    def _sample_macro_pose(self, asset: PaperDollAsset, macro: PaperDollMacro, t: float) -> dict[str, dict]:
        pose: dict[str, dict] = {}
        for layer in self._iter_layers(asset.root_layers):
            pose[layer.id] = {
                "x": layer.x,
                "y": layer.y,
                "rotation": layer.rotation,
                "scale": layer.scale,
            }

        by_layer: dict[str, list[PaperDollKeyframe]] = {}
        for kf in macro.keyframes:
            by_layer.setdefault(kf.layer_id, []).append(kf)

        for lid, kfs in by_layer.items():
            if lid not in pose:
                continue
            kfs_sorted = sorted(kfs, key=lambda k: k.time)
            before = None
            after = None
            for kf in kfs_sorted:
                if kf.time <= t:
                    before = kf
                if kf.time >= t and after is None:
                    after = kf

            if before and after and before is not after:
                span = after.time - before.time
                frac = (t - before.time) / span if span > 0 else 0.0
                pose[lid]["x"] = before.x + (after.x - before.x) * frac
                pose[lid]["y"] = before.y + (after.y - before.y) * frac
                pose[lid]["rotation"] = before.rotation + (after.rotation - before.rotation) * frac
                pose[lid]["scale"] = before.scale + (after.scale - before.scale) * frac
            elif before:
                pose[lid]["x"] = before.x
                pose[lid]["y"] = before.y
                pose[lid]["rotation"] = before.rotation
                pose[lid]["scale"] = before.scale
            elif after:
                pose[lid]["x"] = after.x
                pose[lid]["y"] = after.y
                pose[lid]["rotation"] = after.rotation
                pose[lid]["scale"] = after.scale

        return pose

    def _load_export_pixmaps(self, asset: PaperDollAsset) -> tuple[dict[str, QPixmap], int]:
        pixmaps: dict[str, QPixmap] = {}
        valid_count = 0
        if not self.project:
            return pixmaps, valid_count
        for layer in self._iter_layers(asset.root_layers):
            if not layer.image_id or layer.image_id in pixmaps:
                continue
            img = self.project.get_image(layer.image_id)
            if not img or not img.path or not os.path.isfile(img.path):
                continue
            pm = QPixmap(img.path)
            if pm.isNull():
                continue
            pixmaps[layer.image_id] = pm
            valid_count += 1
        return pixmaps, valid_count

    def _layer_transform(self, layer: PaperDollLayer, pose: dict[str, dict], parent_tf: QTransform) -> QTransform:
        state = pose.get(layer.id, {})
        x = state.get("x", layer.x)
        y = state.get("y", layer.y)
        rotation = state.get("rotation", layer.rotation)
        scale = state.get("scale", layer.scale)

        tf = QTransform()
        tf.translate(x, y)
        tf.translate(layer.origin_x, layer.origin_y)
        tf.rotate(rotation)
        tf.scale(scale, scale)
        tf.translate(-layer.origin_x, -layer.origin_y)
        return tf * parent_tf

    def _accumulate_pose_rect(
        self,
        layers: list[PaperDollLayer],
        pose: dict[str, dict],
        pixmaps: dict[str, QPixmap],
        parent_tf: QTransform | None = None,
    ) -> QRectF | None:
        if parent_tf is None:
            parent_tf = QTransform()
        rect = None
        for layer in layers:
            composed = self._layer_transform(layer, pose, parent_tf)
            pm = pixmaps.get(layer.image_id) if layer.image_id else None
            if pm and not pm.isNull():
                local_rect = composed.mapRect(QRectF(0, 0, pm.width(), pm.height()))
                rect = local_rect if rect is None else rect.united(local_rect)
            child_rect = self._accumulate_pose_rect(layer.children, pose, pixmaps, composed)
            if child_rect is not None:
                rect = child_rect if rect is None else rect.united(child_rect)
        return rect

    def _render_export_layers(
        self,
        painter: QPainter,
        layers: list[PaperDollLayer],
        pose: dict[str, dict],
        pixmaps: dict[str, QPixmap],
        parent_tf: QTransform,
    ):
        for layer in layers:
            composed = self._layer_transform(layer, pose, parent_tf)
            pm = pixmaps.get(layer.image_id) if layer.image_id else None
            if pm and not pm.isNull():
                painter.save()
                painter.setTransform(composed, False)
                painter.drawPixmap(0, 0, pm)
                painter.restore()
            self._render_export_layers(painter, layer.children, pose, pixmaps, composed)

    def _render_pose_frame(
        self,
        asset: PaperDollAsset,
        pose: dict[str, dict],
        pixmaps: dict[str, QPixmap],
        frame_rect: QRectF,
    ) -> QImage:
        width = max(1, int(math.ceil(frame_rect.width())))
        height = max(1, int(math.ceil(frame_rect.height())))
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        root_tf = QTransform()
        root_tf.translate(-frame_rect.left(), -frame_rect.top())

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._render_export_layers(painter, asset.root_layers, pose, pixmaps, root_tf)
        painter.end()
        return image

    def _qimage_to_pil_rgba(self, image: QImage) -> PILImage.Image:
        image = image.convertToFormat(QImage.Format_RGBA8888)
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return PILImage.open(io.BytesIO(bytes(byte_array))).convert("RGBA")

    def _save_quantized_png(self, image: QImage, path: str):
        img_rgba = self._qimage_to_pil_rgba(image)
        arr = np.array(img_rgba).astype(np.float32)
        alpha_channel = arr[:, :, 3:4] / 255.0
        arr[:, :, :3] *= alpha_channel
        img_rgba = PILImage.fromarray(arr.astype(np.uint8), "RGBA")

        r, g, b, alpha = img_rgba.split()
        img_rgb = PILImage.merge("RGB", (r, g, b))
        img_p = img_rgb.quantize(colors=255, method=PILImage.Quantize.MEDIANCUT)

        data = np.array(img_p, dtype=np.uint8) + 1
        palette_bytes = img_p.getpalette()
        new_palette = [0, 0, 0] + palette_bytes[:255 * 3]
        alpha_arr = np.array(alpha, dtype=np.uint8)
        data[alpha_arr < 128] = 0

        img_out = PILImage.fromarray(data, mode="P")
        img_out.putpalette(new_palette)
        img_out.save(path, "PNG", transparency=0)

    def _build_export_sheet(self, frames: list[QImage], frame_width: int, frame_height: int) -> tuple[QImage, int, int]:
        total = len(frames)
        cols = max(1, int(math.ceil(math.sqrt(total))))
        rows = max(1, int(math.ceil(total / cols)))
        sheet = QImage(cols * frame_width, rows * frame_height, QImage.Format_ARGB32)
        sheet.fill(Qt.GlobalColor.transparent)

        painter = QPainter(sheet)
        for i, frame in enumerate(frames):
            row = i // cols
            col = i % cols
            painter.drawImage(col * frame_width, row * frame_height, frame)
        painter.end()
        return sheet, cols * frame_width, rows * frame_height

    def _collect_export_samples(
        self,
        asset: PaperDollAsset,
        macro: PaperDollMacro,
        fps: int,
        pixmaps: dict[str, QPixmap],
    ) -> tuple[list[dict[str, dict]], QRectF]:
        duration = max(float(macro.duration), 0.0)
        frame_count = max(1, int(math.ceil(duration * fps)))
        poses: list[dict[str, dict]] = []
        export_rect = None

        for i in range(frame_count):
            if frame_count == 1 or duration <= 0:
                t = 0.0
            else:
                t = (i / (frame_count - 1)) * duration
            pose = self._sample_macro_pose(asset, macro, t)
            poses.append(pose)
            pose_rect = self._accumulate_pose_rect(asset.root_layers, pose, pixmaps)
            if pose_rect is not None:
                export_rect = pose_rect if export_rect is None else export_rect.united(pose_rect)

        if export_rect is None:
            export_rect = QRectF(0, 0, 1, 1)

        left = math.floor(export_rect.left())
        top = math.floor(export_rect.top())
        right = math.ceil(export_rect.right())
        bottom = math.ceil(export_rect.bottom())
        aligned = QRectF(left, top, max(1, right - left), max(1, bottom - top))
        return poses, aligned

    def _refresh_animation_object_editors(self):
        main_win = self.window()
        if hasattr(main_win, "obj_tab"):
            editor = main_win.obj_tab.def_editor
            if editor._obj is not None:
                editor.load_object(editor._obj, self.project)

    def _export_current_macro_ani(self):
        if not self.project or not self._current_asset:
            QMessageBox.information(self, "No Asset", "Create or select a puppet animation asset first.")
            return
        if not self._current_macro:
            QMessageBox.information(self, "No Macro", "Select a macro to export first.")
            return

        main_win = self.window()
        current_project_path = getattr(main_win, "current_project_path", None)
        if current_project_path is None:
            QMessageBox.warning(
                self,
                "No Project Path",
                "Please save your game project first before exporting .ani files.",
            )
            return

        dlg = MacroExportDialog(self._default_export_name(), default_fps=12, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        export_name, fps = dlg.values()
        if not export_name:
            QMessageBox.warning(self, "Missing Name", "Please enter an export name.")
            return
        if any(ch in export_name for ch in '<>:"/\\|?*'):
            QMessageBox.warning(
                self,
                "Invalid Name",
                "Export names cannot contain these characters: <>:\"/\\\\|?*",
            )
            return

        pixmaps, valid_count = self._load_export_pixmaps(self._current_asset)
        if valid_count == 0:
            QMessageBox.warning(
                self,
                "No Images",
                "The selected puppet asset does not contain any valid source images to export.",
            )
            return

        poses, export_rect = self._collect_export_samples(
            self._current_asset, self._current_macro, fps, pixmaps
        )
        frames = [
            self._render_pose_frame(self._current_asset, pose, pixmaps, export_rect)
            for pose in poses
        ]

        project_dir = os.path.dirname(str(current_project_path))
        anim_dir = os.path.join(project_dir, "animations")
        os.makedirs(anim_dir, exist_ok=True)

        frame_width = max(1, frames[0].width())
        frame_height = max(1, frames[0].height())
        sheet, sheet_width, sheet_height = self._build_export_sheet(frames, frame_width, frame_height)

        sheet_filename = f"{export_name}.png"
        sheet_path = os.path.join(anim_dir, sheet_filename)
        self._save_quantized_png(sheet, sheet_path)

        metadata = {
            "frame_count": len(frames),
            "frame_width": frame_width,
            "frame_height": frame_height,
            "sheet_width": sheet_width,
            "sheet_height": sheet_height,
            "fps": fps,
            "spritesheet_path": sheet_filename,
            "spritesheet_paths": [sheet_filename],
            "sheet_count": 1,
            "frames_per_sheet": len(frames),
        }
        meta_path = os.path.join(anim_dir, f"{export_name}.ani")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        self.project.animation_exports = [
            ani for ani in self.project.animation_exports if ani.name != export_name
        ]
        self.project.animation_exports.append(
            AnimationExport(
                name=export_name,
                spritesheet_path=sheet_filename,
                spritesheet_paths=[sheet_filename],
                frame_count=len(frames),
                frame_width=frame_width,
                frame_height=frame_height,
                sheet_width=sheet_width,
                sheet_height=sheet_height,
                sheet_count=1,
                frames_per_sheet=len(frames),
                fps=fps,
            )
        )

        self._refresh_animation_object_editors()
        self._mark_changed()

        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported '{export_name}.ani' to:\n{anim_dir}",
        )

    def _refresh_all(self):
        self._refresh_tree()
        self._refresh_properties()
        self._refresh_macro_list()
        self._refresh_canvas()
        self.timeline.set_macro(self._current_macro)

    def _refresh_canvas(self):
        if self._any_preview_active():
            self.canvas.rebuild(self._current_asset, self.project,
                                image_swaps=self._preview_image_swaps,
                                scale_offsets=self._preview_scale_offsets)
        else:
            self.canvas.rebuild(self._current_asset, self.project)
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _refresh_canvas_preview(self):
        """Lightweight refresh during preview animation — skips property panel updates."""
        self.canvas.rebuild(self._current_asset, self.project,
                            image_swaps=self._preview_image_swaps,
                            scale_offsets=self._preview_scale_offsets)
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _mark_changed(self):
        self.changed.emit()

    # ── Standalone test ────────────────────────────────────────

    @staticmethod
    def standalone_test():
        """Run standalone for testing outside main app."""
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        project = Project.new()
        tab = PaperDollTab()
        tab.setWindowTitle("Animation Editor — Standalone Test")
        tab.resize(1280, 850)
        tab.setStyleSheet(f"background: {DARK}; color: {TEXT};")
        tab.load_project(project)
        tab.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    PaperDollTab.standalone_test()

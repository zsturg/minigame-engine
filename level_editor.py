import sys
import json
import math
import random
import hashlib
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsItemGroup, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QToolBar, QSpinBox, QComboBox, QPushButton, QSlider,
    QFormLayout, QColorDialog, QFileDialog, QMessageBox, QScrollArea,
    QGroupBox, QDial, QDoubleSpinBox, QFrame, QStackedWidget,
    QSizePolicy, QProgressDialog
)
from PySide6.QtGui import (
    QPen, QColor, QPainter, QPainterPath, QBrush, QImage, QPixmap,
    QLinearGradient, QPolygon, QCursor
)
from PySide6.QtCore import Qt, QRectF, QPoint, QRect, Signal, QTimer
from PIL import Image, ImageDraw, ImageFilter


# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════════

DARK_STYLE = """
QMainWindow, QWidget {
    background: #1a1a1a; color: #ccc;
    font-family: 'Consolas','Courier New',monospace; font-size: 11px;
}
QGroupBox {
    border: 1px solid #2a2a2a; border-radius: 3px;
    margin-top: 8px; padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
    color: #4a4a4a; font-size: 10px; letter-spacing: 2px;
}
QSpinBox, QDoubleSpinBox, QComboBox {
    background: #111; border: 1px solid #2e2e2e; border-radius: 2px;
    color: #eee; padding: 2px 4px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #555; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #1e1e1e; color: #ddd;
    selection-background-color: #2e2e2e;
}
QPushButton {
    background: #222; border: 1px solid #363636; border-radius: 2px;
    color: #bbb; padding: 4px 10px; font-size: 11px; letter-spacing: 1px;
}
QPushButton:hover  { background: #2a2a2a; border-color: #4a4a4a; }
QPushButton:pressed { background: #111; }
QPushButton#mode_city {
    background: #182028; border-color: #334455; color: #6a9acc;
}
QPushButton#mode_city:checked {
    background: #1e2e3e; border-color: #4a7aaa; color: #90c0ee;
}
QPushButton#mode_terrain {
    background: #182818; border-color: #335533; color: #6aac6a;
}
QPushButton#mode_terrain:checked {
    background: #1e321e; border-color: #4a8a4a; color: #90dd90;
}
QPushButton#generate {
    background: #182818; border-color: #335533; color: #6aac6a;
}
QPushButton#generate:hover { background: #1e321e; border-color: #4a8a4a; }
QSlider::groove:horizontal {
    background: #111; border: 1px solid #2e2e2e;
    height: 4px; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #3a5a8a; border: 1px solid #4a6aaa;
    width: 10px; height: 10px; margin: -4px 0; border-radius: 5px;
}
QSlider::handle:horizontal:hover { background: #4a6aaa; }
QScrollBar:vertical {
    background: #111; width: 6px; border: none;
}
QScrollBar::handle:vertical {
    background: #2e2e2e; border-radius: 3px; min-height: 14px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #111; height: 6px; border: none; }
QScrollBar::handle:horizontal {
    background: #2e2e2e; border-radius: 3px; min-width: 14px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  TERRAIN ENGINE  (noise + color ramp + overlays)
# ═══════════════════════════════════════════════════════════════════════════════

TEX_W = TEX_H = 2048

# ── Library detection ─────────────────────────────────────────────────────────
try:
    import noise as _noise_lib; HAS_NOISE = True
except ImportError:
    HAS_NOISE = False

NOISE_TYPES = ["Perlin (built-in)"]
if HAS_NOISE:
    NOISE_TYPES += ["Perlin Tiling (noise lib)", "Simplex (noise lib)"]

# ── Color ramp presets ────────────────────────────────────────────────────────
RAMP_PRESETS = {
    "Terrain": [
        (0.00, QColor( 10,  20,  80), 0.02, "deep_water"),
        (0.35, QColor( 30,  80, 160), 0.04, "water"),
        (0.42, QColor(194, 178, 128), 0.02, "sand"),
        (0.50, QColor( 85, 130,  60), 0.04, "grass"),
        (0.72, QColor( 60,  90,  45), 0.04, "dark_grass"),
        (0.82, QColor(120, 100,  80), 0.03, "rock"),
        (1.00, QColor(240, 240, 250), 0.03, "snow"),
    ],
    "Lava": [
        (0.00, QColor( 10,   5,   5), 0.02, "obsidian"),
        (0.30, QColor( 60,  10,   5), 0.05, "dark_rock"),
        (0.55, QColor(160,  40,   5), 0.04, "lava_rock"),
        (0.72, QColor(220, 100,  10), 0.03, "lava"),
        (0.88, QColor(255, 200,  50), 0.03, "hot_lava"),
        (1.00, QColor(255, 255, 200), 0.02, "core"),
    ],
    "Arctic": [
        (0.00, QColor( 20,  40,  80), 0.03, "deep_water"),
        (0.38, QColor( 60, 100, 160), 0.04, "ice_water"),
        (0.50, QColor(180, 200, 220), 0.03, "slush"),
        (0.65, QColor(220, 230, 240), 0.03, "ice"),
        (1.00, QColor(255, 255, 255), 0.02, "snow"),
    ],
    "Desert": [
        (0.00, QColor( 30,  20,  10), 0.03, "bedrock"),
        (0.25, QColor( 80,  55,  25), 0.05, "dark_sand"),
        (0.55, QColor(180, 140,  70), 0.05, "sand"),
        (0.78, QColor(210, 175, 110), 0.04, "light_sand"),
        (1.00, QColor(240, 220, 170), 0.02, "dune_crest"),
    ],
    "Grayscale": [
        (0.00, QColor(  0,   0,   0), 0.0, "black"),
        (1.00, QColor(255, 255, 255), 0.0, "white"),
    ],
}

# ── Noise generators ──────────────────────────────────────────────────────────

def _build_perm(seed):
    rng = random.Random(seed)
    p = list(range(256)); rng.shuffle(p)
    return np.array(p * 2, dtype=np.int32)

def _fade(t): return t * t * t * (t * (t * 6 - 15) + 10)

def _grad2(h, x, y):
    gx = np.where((h & 1) == 0,  1.0, -1.0)
    gy = np.where((h & 2) == 0,  1.0, -1.0)
    return gx * x + gy * y

def _perlin_layer(xs, ys, perm):
    xi = np.floor(xs).astype(np.int32) & 255
    yi = np.floor(ys).astype(np.int32) & 255
    xf = xs - np.floor(xs); yf = ys - np.floor(ys)
    u = _fade(xf); v = _fade(yf)
    aa = perm[perm[xi  ] + yi  ]; ab = perm[perm[xi  ] + yi+1]
    ba = perm[perm[xi+1] + yi  ]; bb = perm[perm[xi+1] + yi+1]
    x1 = (1-u)*_grad2(aa, xf,   yf  ) + u*_grad2(ba, xf-1, yf  )
    x2 = (1-u)*_grad2(ab, xf,   yf-1) + u*_grad2(bb, xf-1, yf-1)
    return ((1-v)*x1 + v*x2 + 1.0) * 0.5

def _gen_builtin_perlin(W, H, scale, octaves, persistence, lacunarity, seed, ox, oy):
    perm = _build_perm(seed)
    inv  = 1.0 / max(scale, 0.001)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    xs = (xs + ox) * inv; ys = (ys + oy) * inv
    total = np.zeros((H, W), dtype=np.float64)
    max_v = 0.0; freq = amp = 1.0
    for _ in range(octaves):
        total += _perlin_layer(xs*freq, ys*freq, perm) * amp
        max_v += amp; amp *= persistence; freq *= lacunarity
    return (total / max_v).astype(np.float32)

def generate_noise_array(W, H, scale, octaves, persistence, lacunarity,
                          seed, ox, oy, contrast=1.0, brightness=0.0,
                          noise_type="Perlin (built-in)"):
    if noise_type == "Perlin Tiling (noise lib)" and HAS_NOISE:
        inv = 1.0 / max(scale, 0.001)
        arr = np.zeros((H, W), dtype=np.float32)
        rep = max(1, int(max(W, H) * inv))
        for y in range(H):
            for x in range(W):
                v = _noise_lib.pnoise2(
                    (x+ox)*inv, (y+oy)*inv,
                    octaves=octaves, persistence=persistence, lacunarity=lacunarity,
                    repeatx=rep, repeaty=rep, base=seed % 256)
                arr[y, x] = (v + 1.0) * 0.5
    elif noise_type == "Simplex (noise lib)" and HAS_NOISE:
        inv = 1.0 / max(scale, 0.001)
        arr = np.zeros((H, W), dtype=np.float32)
        for y in range(H):
            for x in range(W):
                v = _noise_lib.snoise2(
                    (x+ox)*inv, (y+oy)*inv,
                    octaves=octaves, persistence=persistence,
                    lacunarity=lacunarity, base=seed % 256)
                arr[y, x] = (v + 1.0) * 0.5
    else:
        arr = _gen_builtin_perlin(W, H, scale, octaves, persistence, lacunarity, seed, ox, oy)
    arr = (arr - 0.5) * contrast + 0.5 + brightness
    return np.clip(arr, 0.0, 1.0).astype(np.float32)

def apply_color_ramp(arr, stops):
    stops = sorted(stops, key=lambda s: s[0])
    H, W  = arr.shape
    r0, g0, b0 = stops[0][1].red()/255., stops[0][1].green()/255., stops[0][1].blue()/255.
    out_r = np.full((H, W), r0, dtype=np.float32)
    out_g = np.full((H, W), g0, dtype=np.float32)
    out_b = np.full((H, W), b0, dtype=np.float32)
    for i in range(1, len(stops)):
        pos, col, bw = stops[i][0], stops[i][1], stops[i][2]
        bw = max(bw, 1e-6)
        lo = pos - bw*0.5; hi = pos + bw*0.5
        t  = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
        t  = t * t * (3 - 2*t)
        r1, g1, b1 = col.red()/255., col.green()/255., col.blue()/255.
        out_r = out_r*(1-t) + r1*t
        out_g = out_g*(1-t) + g1*t
        out_b = out_b*(1-t) + b1*t
    return np.stack([
        (out_r*255).astype(np.uint8),
        (out_g*255).astype(np.uint8),
        (out_b*255).astype(np.uint8),
    ], axis=-1)

def compute_edge_detect(arr):
    from numpy.lib.stride_tricks import sliding_window_view
    kx = np.array([[-1,0,1],[-2,0,2],[-1,0,1]], dtype=np.float32)
    ky = np.array([[-1,-2,-1],[0,0,0],[1,2,1]],  dtype=np.float32)
    p  = np.pad(arr, 1, mode='edge')
    w  = sliding_window_view(p, (3,3))
    gx = (w * kx).sum(axis=(-2,-1)); gy = (w * ky).sum(axis=(-2,-1))
    mag = np.sqrt(gx**2 + gy**2); mag = mag / (mag.max() + 1e-8)
    return (np.clip(mag, 0, 1) * 255).astype(np.uint8)

def compute_contours(arr, stops, width=1.0):
    H, W = arr.shape
    out  = np.zeros((H, W, 4), dtype=np.uint8)
    for s in sorted(stops, key=lambda s: s[0]):
        pos = s[0]; hw = max(0.004, width * 0.003)
        mask = (arr >= pos - hw) & (arr <= pos + hw)
        col  = s[1]
        br   = (col.red()*0.299 + col.green()*0.587 + col.blue()*0.114) / 255.
        lc   = 30 if br > 0.5 else 220
        out[mask] = [lc, lc, lc, 255]
    return out

def blend_overlay_on_rgb(base_rgb, overlay_gray, color, opacity):
    if opacity <= 0: return base_rgb
    mask = overlay_gray.astype(np.float32) / 255.0 * opacity
    r = np.clip(base_rgb[:,:,0]*(1-mask) + color[0]*mask, 0, 255)
    g = np.clip(base_rgb[:,:,1]*(1-mask) + color[1]*mask, 0, 255)
    b = np.clip(base_rgb[:,:,2]*(1-mask) + color[2]*mask, 0, 255)
    return np.stack([r.astype(np.uint8), g.astype(np.uint8), b.astype(np.uint8)], axis=-1)

def blend_rgba_overlay_on_rgb(base_rgb, overlay_rgba, opacity):
    if opacity <= 0: return base_rgb
    a = overlay_rgba[:,:,3].astype(np.float32) / 255.0 * opacity
    result = base_rgb.copy().astype(np.float32)
    for c in range(3):
        result[:,:,c] = base_rgb[:,:,c]*(1-a) + overlay_rgba[:,:,c]*a
    return result.astype(np.uint8)


# ── Color Ramp Widget ─────────────────────────────────────────────────────────

RAMP_H = 28; STOP_H = 12; STOP_W = 10; RAMP_PAD = 14

class ColorRampWidget(QWidget):
    rampChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(RAMP_H + STOP_H + 10)
        self.setMinimumWidth(200)
        self._stops = []; self._drag_idx = None
        self.setMouseTracking(True)
        self.load_preset("Terrain")

    def load_preset(self, name):
        raw = RAMP_PRESETS.get(name, RAMP_PRESETS["Terrain"])
        self._stops = [[p, QColor(c), bw, lbl] for p, c, bw, lbl in raw]
        self.rampChanged.emit(); self.update()

    def stops(self):
        return [(s[0], s[1], s[2], s[3]) for s in self._stops]

    def _ramp_rect(self):
        return QRect(RAMP_PAD, 2, self.width() - 2*RAMP_PAD, RAMP_H)

    def _stop_x(self, pos):
        r = self._ramp_rect()
        return int(r.left() + pos * r.width())

    def _x_to_pos(self, x):
        r = self._ramp_rect()
        return max(0.0, min(1.0, (x - r.left()) / r.width()))

    def _hit_stop(self, pt):
        y_top = RAMP_H + 3
        for i, s in enumerate(self._stops):
            x = self._stop_x(s[0])
            if QRect(x - STOP_W//2 - 2, y_top - 2, STOP_W + 4, STOP_H + 4).contains(pt):
                return i
        return -1

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._ramp_rect()
        grad = QLinearGradient(r.left(), 0, r.right(), 0)
        for pos, col, bw, *_ in sorted(self._stops, key=lambda s: s[0]):
            grad.setColorAt(max(0.0, min(1.0, pos)), col)
        p.fillRect(r, QBrush(grad))
        p.setPen(QPen(QColor(55, 55, 55), 1)); p.drawRect(r)
        y_top = RAMP_H + 3
        for i, s in enumerate(self._stops):
            x = self._stop_x(s[0])
            tri = QPolygon([QPoint(x, y_top),
                            QPoint(x - STOP_W//2, y_top + STOP_H),
                            QPoint(x + STOP_W//2, y_top + STOP_H)])
            p.setBrush(QBrush(s[1]))
            p.setPen(QPen(QColor(255, 255, 255) if i == self._drag_idx
                          else QColor(150, 150, 150), 1))
            p.drawPolygon(tri)
        p.end()

    def mousePressEvent(self, e):
        pt = e.position().toPoint(); idx = self._hit_stop(pt)
        if e.button() == Qt.MouseButton.RightButton:
            if idx >= 0 and len(self._stops) > 2:
                self._stops.pop(idx); self.rampChanged.emit(); self.update()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            if idx >= 0:
                self._drag_idx = idx
            else:
                r = self._ramp_rect()
                if r.contains(pt):
                    pos = self._x_to_pos(pt.x())
                    col = self._interp_color(pos)
                    self._stops.append([pos, col, 0.05, f"zone_{len(self._stops)}"])
                    self._stops.sort(key=lambda s: s[0])
                    self.rampChanged.emit(); self.update()

    def mouseReleaseEvent(self, e): self._drag_idx = None

    def mouseMoveEvent(self, e):
        if self._drag_idx is not None:
            self._stops[self._drag_idx][0] = self._x_to_pos(e.position().toPoint().x())
            self.rampChanged.emit(); self.update()

    def mouseDoubleClickEvent(self, e):
        idx = self._hit_stop(e.position().toPoint())
        if idx >= 0:
            col = QColorDialog.getColor(self._stops[idx][1], self, "Stop Color")
            if col.isValid():
                self._stops[idx][1] = col; self.rampChanged.emit(); self.update()

    def _interp_color(self, pos):
        ss = sorted(self._stops, key=lambda s: s[0])
        if pos <= ss[0][0]:  return QColor(ss[0][1])
        if pos >= ss[-1][0]: return QColor(ss[-1][1])
        for i in range(len(ss)-1):
            a, b = ss[i], ss[i+1]
            if a[0] <= pos <= b[0]:
                t = (pos - a[0]) / max(b[0] - a[0], 1e-6)
                return QColor(
                    int(a[1].red()   + t*(b[1].red()   - a[1].red())),
                    int(a[1].green() + t*(b[1].green() - a[1].green())),
                    int(a[1].blue()  + t*(b[1].blue()  - a[1].blue())),
                )
        return QColor(128, 128, 128)


# ── Terrain Viewport ──────────────────────────────────────────────────────────

class TerrainViewport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._pan = QPoint(0, 0)
        self._drag_start = None; self._pan_start = None
        self.tex_w = TEX_W; self.tex_h = TEX_H
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setFixedSize(960, 544)

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self._clamp_pan(); self.update()

    def _clamp_pan(self):
        self._pan.setX(max(0, min(self._pan.x(), max(0, self.tex_w - self.width()))))
        self._pan.setY(max(0, min(self._pan.y(), max(0, self.tex_h - self.height()))))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
            self._pan_start  = QPoint(self._pan)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, e):
        if self._drag_start is not None:
            self._pan = self._pan_start - (e.position().toPoint() - self._drag_start)
            self._clamp_pan(); self.update()

    def mouseReleaseEvent(self, e):
        self._drag_start = None
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self._pixmap:
            sx, sy = self._pan.x(), self._pan.y()
            sw = min(self.width(),  self.tex_w - sx)
            sh = min(self.height(), self.tex_h - sy)
            p.drawPixmap(QRect(0, 0, sw, sh), self._pixmap, QRect(sx, sy, sw, sh))
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.drawRect(0, 0, self.width()-1, self.height()-1)
        p.end()


# ── Terrain Editor Panel ──────────────────────────────────────────────────────

class TerrainEditor(QWidget):
    """Self-contained terrain noise editor with 2048² preview, color ramp,
    edge-detect, contour overlays, and 1×1 / 3×3 export."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._noise_arr  = None
        self._texture_rgb = None
        self._first_shown = False
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # ── Left panel ────────────────────────────────────────────────────────
        left_inner = QWidget(); left_inner.setFixedWidth(250)
        ll = QVBoxLayout(left_inner)
        ll.setContentsMargins(4, 4, 4, 4); ll.setSpacing(6)

        # noise type
        nt_grp = QGroupBox("NOISE TYPE"); nt_l = QVBoxLayout(nt_grp)
        self.noise_type_combo = QComboBox()
        self.noise_type_combo.addItems(NOISE_TYPES)
        nt_l.addWidget(self.noise_type_combo)
        ll.addWidget(nt_grp)

        # noise params
        pn_grp = QGroupBox("PARAMETERS"); pn_l = QVBoxLayout(pn_grp); pn_l.setSpacing(2)
        self.p_scale       = self._dbl(1, 4096, 256, 8, 1)
        self.p_octaves     = self._int(1, 8, 4)
        self.p_persistence = self._dbl(0, 1, 0.5, 0.05, 3)
        self.p_lacunarity  = self._dbl(1, 8, 2.0, 0.1, 2)
        self.p_seed        = self._int(0, 99999, 42)
        self.p_offset_x    = self._dbl(-8192, 8192, 0, 16, 1)
        self.p_offset_y    = self._dbl(-8192, 8192, 0, 16, 1)
        self.p_contrast    = self._dbl(0.1, 5, 1.0, 0.05, 2)
        self.p_brightness  = self._dbl(-1, 1, 0.0, 0.05, 2)
        for lbl, w in [("Scale", self.p_scale), ("Octaves", self.p_octaves),
                       ("Persistence", self.p_persistence), ("Lacunarity", self.p_lacunarity),
                       ("Seed", self.p_seed), ("Offset X", self.p_offset_x),
                       ("Offset Y", self.p_offset_y), ("Contrast", self.p_contrast),
                       ("Brightness", self.p_brightness)]:
            pn_l.addWidget(self._param_row(lbl, w))
        ll.addWidget(pn_grp)

        # color ramp
        cr_grp = QGroupBox("COLOR RAMP"); cr_l = QVBoxLayout(cr_grp); cr_l.setSpacing(4)
        pr_row = QHBoxLayout()
        pr_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(RAMP_PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(
            lambda n: self.color_ramp.load_preset(n))
        pr_row.addWidget(self.preset_combo); pr_row.addStretch()
        cr_l.addLayout(pr_row)
        self.color_ramp = ColorRampWidget()
        self.color_ramp.setFixedHeight(RAMP_H + STOP_H + 14)
        self.color_ramp.rampChanged.connect(self._recolor)
        cr_l.addWidget(self.color_ramp)
        hint = QLabel("drag ▲ · dbl-click recolor · right-click remove · click bar add")
        hint.setStyleSheet("color:#3a3a3a; font-size:9px;"); hint.setWordWrap(True)
        cr_l.addWidget(hint)
        # compact stop list (scrollable)
        stop_scroll = QScrollArea(); stop_scroll.setWidgetResizable(True)
        stop_scroll.setFixedHeight(130)
        stop_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stop_list = QWidget()
        self._stop_list_layout = QVBoxLayout(self._stop_list)
        self._stop_list_layout.setContentsMargins(2, 2, 2, 2)
        self._stop_list_layout.setSpacing(1)
        stop_scroll.setWidget(self._stop_list)
        cr_l.addWidget(stop_scroll)
        self.color_ramp.rampChanged.connect(self._rebuild_stop_list)
        ll.addWidget(cr_grp)

        # overlays
        ov_grp = QGroupBox("OVERLAYS"); ov_l = QVBoxLayout(ov_grp); ov_l.setSpacing(3)
        self.edge_chk = self._ov_btn("Edge Detect")
        self.edge_op  = self._op_spin(0.80)
        self.edge_chk.toggled.connect(self._recolor)
        self.edge_op.valueChanged.connect(self._recolor)
        ov_l.addWidget(self._ov_row(self.edge_chk, self.edge_op))

        self.contour_chk = self._ov_btn("Contour Lines")
        self.contour_op  = self._op_spin(0.70)
        self.contour_width_spin = QDoubleSpinBox()
        self.contour_width_spin.setRange(0.5, 5.0); self.contour_width_spin.setValue(1.0)
        self.contour_width_spin.setSingleStep(0.5); self.contour_width_spin.setDecimals(1)
        self.contour_width_spin.setFixedWidth(52)
        self.contour_chk.toggled.connect(self._recolor)
        self.contour_op.valueChanged.connect(self._recolor)
        self.contour_width_spin.valueChanged.connect(self._recolor)
        ov_l.addWidget(self._ov_row(self.contour_chk, self.contour_op))
        cw_sub = QWidget(); cwl = QHBoxLayout(cw_sub)
        cwl.setContentsMargins(20, 0, 0, 0); cwl.setSpacing(4)
        cwl.addWidget(QLabel("line width")); cwl.addWidget(self.contour_width_spin)
        cwl.addStretch(); ov_l.addWidget(cw_sub)
        ll.addWidget(ov_grp)

        self.gen_btn = QPushButton("GENERATE")
        self.gen_btn.setObjectName("generate")
        self.gen_btn.setFixedHeight(30)
        self.gen_btn.clicked.connect(self._generate)
        ll.addWidget(self.gen_btn)

        # export
        ex_grp = QGroupBox("EXPORT"); ex_l = QVBoxLayout(ex_grp); ex_l.setSpacing(4)
        self.tile_label = QLabel("tile  0, 0")
        self.tile_label.setStyleSheet("color:#3a5a3a; font-size:10px;")
        ex_l.addWidget(self.tile_label)
        grid_row = QWidget(); grl = QHBoxLayout(grid_row)
        grl.setContentsMargins(0, 0, 0, 0); grl.setSpacing(6)
        grl.addWidget(QLabel("Grid"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItem("1×1",  1)
        self.grid_combo.addItem("3×3",  3)
        self.grid_combo.setFixedWidth(70); grl.addWidget(self.grid_combo); grl.addStretch()
        ex_l.addWidget(grid_row)
        eb = QPushButton("EXPORT"); eb.clicked.connect(self._export)
        ex_l.addWidget(eb)
        self.export_status = QLabel("")
        self.export_status.setStyleSheet("color:#557755; font-size:10px;")
        self.export_status.setWordWrap(True); ex_l.addWidget(self.export_status)
        ll.addWidget(ex_grp)
        ll.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_inner); left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(272)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(left_scroll)

        # ── Viewport ──────────────────────────────────────────────────────────
        self.viewport = TerrainViewport()
        vp_wrap = QWidget(); vwl = QVBoxLayout(vp_wrap)
        vwl.setContentsMargins(0, 0, 0, 0)
        vwl.addWidget(self.viewport, 0,
                      Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        vwl.addStretch()
        root.addWidget(vp_wrap, 1)

        # initial stop list
        self._rebuild_stop_list()

    # ── Helper constructors ───────────────────────────────────────────────────

    def _int(self, lo, hi, val, step=1):
        s = QSpinBox(); s.setRange(lo, hi); s.setValue(val)
        s.setSingleStep(step); s.setFixedWidth(82); return s

    def _dbl(self, lo, hi, val, step=0.01, dec=3):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setValue(val)
        s.setSingleStep(step); s.setDecimals(dec); s.setFixedWidth(82); return s

    def _param_row(self, lbl_text, widget):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(lbl_text); lbl.setFixedWidth(82)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet("color:#999; font-size:10px;")
        h.addWidget(lbl); h.addSpacing(4); h.addWidget(widget); h.addStretch()
        return w

    def _ov_btn(self, label):
        btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(18)
        btn.setStyleSheet(
            "QPushButton{background:#1e1e1e;border:1px solid #333;border-radius:2px;"
            "color:#666;font-size:10px;padding:0 6px;text-align:left;}"
            "QPushButton:checked{background:#1e2e1e;border-color:#3a6a3a;color:#8ccc8c;}")
        return btn

    def _op_spin(self, val):
        s = QDoubleSpinBox(); s.setRange(0, 1); s.setValue(val)
        s.setSingleStep(0.05); s.setDecimals(2); s.setFixedWidth(52); return s

    def _ov_row(self, chk, op):
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0, 1, 0, 1); l.setSpacing(5)
        l.addWidget(chk); l.addWidget(op); return w

    # ── Stop list ─────────────────────────────────────────────────────────────

    def _rebuild_stop_list(self):
        while self._stop_list_layout.count():
            item = self._stop_list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for i, (pos, col, bw, lbl) in enumerate(self.color_ramp._stops):
            row = QWidget(); rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 1, 0, 1); rl.setSpacing(4)
            cb = QPushButton(); cb.setFixedSize(14, 14)
            cb.setStyleSheet(f"background:{col.name()};border:1px solid #555;border-radius:2px;padding:0;")
            cb.clicked.connect(lambda _, ii=i: self._pick_stop_color(ii))
            lbl_w = QLabel(f"{pos:.2f}  {lbl}")
            lbl_w.setStyleSheet("color:#666; font-size:9px;")
            rl.addWidget(cb); rl.addWidget(lbl_w); rl.addStretch()
            self._stop_list_layout.addWidget(row)

    def _pick_stop_color(self, i):
        if i >= len(self.color_ramp._stops): return
        col = QColorDialog.getColor(self.color_ramp._stops[i][1], self)
        if col.isValid():
            self.color_ramp._stops[i][1] = col
            self.color_ramp.rampChanged.emit()
            self.color_ramp.update()

    # ── Core generate / recolor ───────────────────────────────────────────────

    def _generate(self):
        nt = self.noise_type_combo.currentText()
        slow = nt in ("Perlin Tiling (noise lib)", "Simplex (noise lib)")
        self.gen_btn.setText("GENERATING (slow)…" if slow else "GENERATING…")
        self.gen_btn.setEnabled(False); QApplication.processEvents()
        self._noise_arr = generate_noise_array(
            TEX_W, TEX_H,
            scale=self.p_scale.value(), octaves=self.p_octaves.value(),
            persistence=self.p_persistence.value(), lacunarity=self.p_lacunarity.value(),
            seed=self.p_seed.value(), ox=self.p_offset_x.value(),
            oy=self.p_offset_y.value(), contrast=self.p_contrast.value(),
            brightness=self.p_brightness.value(), noise_type=nt)
        self._update_tile_label()
        self._recolor()
        self.gen_btn.setText("GENERATE"); self.gen_btn.setEnabled(True)

    def _recolor(self):
        if self._noise_arr is None: return
        stops = self.color_ramp.stops()
        rgb = apply_color_ramp(self._noise_arr, stops)
        if self.edge_chk.isChecked():
            rgb = blend_overlay_on_rgb(
                rgb, compute_edge_detect(self._noise_arr),
                (20, 20, 20), self.edge_op.value())
        if self.contour_chk.isChecked():
            rgb = blend_rgba_overlay_on_rgb(
                rgb,
                compute_contours(self._noise_arr, stops, self.contour_width_spin.value()),
                self.contour_op.value())
        self._texture_rgb = rgb
        H, W, ch = rgb.shape
        pix = QPixmap.fromImage(
            QImage(rgb.tobytes(), W, H, ch*W, QImage.Format.Format_RGB888))
        self.viewport.set_pixmap(pix)

    def _update_tile_label(self):
        tx = int(round(self.p_offset_x.value() / TEX_W))
        ty = int(round(self.p_offset_y.value() / TEX_H))
        self.tile_label.setText(f"tile  {tx}, {ty}")

    def _current_tile(self):
        return (int(round(self.p_offset_x.value() / TEX_W)),
                int(round(self.p_offset_y.value() / TEX_H)))

    def _collect_params(self):
        return dict(scale=self.p_scale.value(), octaves=self.p_octaves.value(),
                    persistence=self.p_persistence.value(),
                    lacunarity=self.p_lacunarity.value(),
                    seed=self.p_seed.value(), contrast=self.p_contrast.value(),
                    brightness=self.p_brightness.value(),
                    noise_type=self.noise_type_combo.currentText())

    def _generate_tile_rgb(self, tx, ty, params):
        arr = generate_noise_array(
            TEX_W, TEX_H, ox=tx*TEX_W, oy=ty*TEX_H, **params)
        return apply_color_ramp(arr, self.color_ramp.stops())

    def _save_rgb_png(self, rgb, path):
        try:
            from PIL import Image as PILImage
            PILImage.fromarray(rgb, mode="RGB").save(path)
        except ImportError:
            H, W, ch = rgb.shape
            QImage(rgb.tobytes(), W, H, ch*W, QImage.Format.Format_RGB888).save(path)

    def _export(self):
        if self._noise_arr is None:
            self.export_status.setText("generate first"); return
        grid = self.grid_combo.currentData()
        cx, cy = self._current_tile()
        if grid == 1:
            if self._texture_rgb is None:
                self.export_status.setText("generate first"); return
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Terrain", f"terrain_{cx}_{cy}.png", "PNG (*.png)")
            if not path: return
            self.export_status.setText("saving…"); QApplication.processEvents()
            self._save_rgb_png(self._texture_rgb, path)
            self.export_status.setText(f"saved  {cx},{cy}")
        else:
            folder = QFileDialog.getExistingDirectory(
                self, f"Export {grid}×{grid} tiles to folder")
            if not folder: return
            params = self._collect_params()
            half = grid // 2
            offsets = [(dx, dy) for dy in range(-half, half+1)
                                 for dx in range(-half, half+1)]
            prog = QProgressDialog(
                f"Exporting {grid}×{grid} tiles…", "Cancel", 0, len(offsets), self)
            prog.setWindowTitle(f"Export {grid}×{grid}")
            prog.setMinimumDuration(0); prog.setValue(0)
            for i, (dx, dy) in enumerate(offsets):
                if prog.wasCanceled():
                    self.export_status.setText("cancelled"); return
                tx, ty = cx+dx, cy+dy
                prog.setLabelText(f"tile {tx},{ty}  ({i+1}/{len(offsets)})")
                QApplication.processEvents()
                self._save_rgb_png(
                    self._generate_tile_rgb(tx, ty, params),
                    f"{folder}/terrain_{tx}_{ty}.png")
                prog.setValue(i+1)
            prog.close()
            self.export_status.setText(f"{len(offsets)} tiles → {folder}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CITY ENGINE  (unchanged from original, inlined here)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Pattern generators ────────────────────────────────────────────────────────

class PatternCache:
    def __init__(self): self.cache = {}
    def get_or_create(self, key, fn):
        if key not in self.cache: self.cache[key] = fn()
        return self.cache[key]
    def clear(self): self.cache.clear()

pattern_cache = PatternCache()

def pil_to_qimage(pil_img):
    pil_img = pil_img.convert('RGB')
    data = pil_img.tobytes('raw', 'RGB')
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGB888)
    return qimg.copy()

def apply_weathering(img, params):
    dirt = params.get('weather_dirt', 0); stain = params.get('weather_stain', 0)
    if dirt == 0 and stain == 0: return img
    w, h = img.size; rng = random.Random(params.get('seed', 42) + 9999)
    if dirt > 0:
        layer = Image.new('RGBA', (w, h), (0,0,0,0)); dr = ImageDraw.Draw(layer)
        for _ in range(int((w*h/600)*(dirt/100))):
            dx=rng.randint(0,w-1); dy=rng.randint(0,h-1); sz=rng.randint(2,max(3,w//20))
            dr.ellipse([dx-sz,dy-sz,dx+sz,dy+sz],fill=(28,22,14,rng.randint(40,110)))
        layer=layer.filter(ImageFilter.GaussianBlur(2))
        img=Image.alpha_composite(img.convert('RGBA'),layer).convert('RGB')
    if stain > 0:
        layer=Image.new('RGBA',(w,h),(0,0,0,0)); dr=ImageDraw.Draw(layer)
        for _ in range(int((w*h/2000)*(stain/100))):
            sx=rng.randint(0,w); sy=rng.randint(0,h); sz=rng.randint(max(4,w//16),max(8,w//6))
            col=rng.choice([(55,45,30,rng.randint(30,80)),(80,65,40,rng.randint(20,60)),(35,50,30,rng.randint(20,50))])
            dr.ellipse([sx-sz,sy-sz,sx+sz,sy+sz],fill=col)
        layer=layer.filter(ImageFilter.GaussianBlur(5))
        img=Image.alpha_composite(img.convert('RGBA'),layer).convert('RGB')
    return img

def generate_brick_pattern(width, height, params):
    brick_w=params.get('brick_width',60); brick_h=params.get('brick_height',20)
    mortar_w=params.get('mortar_width',3); brick_color=params.get('brick_color','#8B4513')
    mortar_color=params.get('mortar_color','#CCCCCC'); color_var=params.get('color_variation',20)
    dirt_amount=params.get('dirt',0); wear=params.get('wear',0); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    img=Image.new('RGB',(width,height),mortar_color); draw=ImageDraw.Draw(img)
    brick_r=int(brick_color[1:3],16); brick_g=int(brick_color[3:5],16); brick_b=int(brick_color[5:7],16)
    y=0; row=0
    while y<height:
        x=0
        if row%2==1: x=-(brick_w//2)
        while x<width:
            var=random.randint(-color_var,color_var)
            br=max(0,min(255,brick_r+var)); bg=max(0,min(255,brick_g+var)); bb=max(0,min(255,brick_b+var))
            bx=x+mortar_w; by=y+mortar_w; bwidth=brick_w-mortar_w; bheight=brick_h-mortar_w
            if bx<width and by<height:
                draw.rectangle([bx,by,min(bx+bwidth,width),min(by+bheight,height)],fill=(br,bg,bb))
                if wear>0 and random.random()<wear/100:
                    cs=random.randint(1,4); cx2=bx+random.randint(0,bwidth-cs); cy2=by+random.randint(0,bheight-cs)
                    draw.rectangle([cx2,cy2,cx2+cs,cy2+cs],fill=mortar_color)
            x+=brick_w
        y+=brick_h; row+=1
    if dirt_amount>0:
        dl=Image.new('RGBA',(width,height),(0,0,0,0)); dd=ImageDraw.Draw(dl)
        for _ in range(int((width*height/1000)*(dirt_amount/20))):
            dx=random.randint(0,width-1); dy=random.randint(0,height-1); size=random.randint(2,8)
            dd.ellipse([dx-size,dy-size,dx+size,dy+size],fill=(40,30,20,random.randint(30,80)))
        dl=dl.filter(ImageFilter.GaussianBlur(2))
        img=Image.alpha_composite(img.convert('RGBA'),dl).convert('RGB')
    return pil_to_qimage(img)

def generate_tile_pattern(width, height, params):
    tile_size=params.get('tile_size',40); grout_w=params.get('grout_width',2)
    tile_color=params.get('tile_color','#E0E0E0'); grout_color=params.get('grout_color','#888888')
    color_var=params.get('color_variation',10); dirt_amount=params.get('dirt',0)
    crack_density=params.get('cracks',0); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    img=Image.new('RGB',(width,height),grout_color); draw=ImageDraw.Draw(img)
    tile_r=int(tile_color[1:3],16); tile_g=int(tile_color[3:5],16); tile_b=int(tile_color[5:7],16)
    y=0
    while y<height:
        x=0
        while x<width:
            var=random.randint(-color_var,color_var)
            tr=max(0,min(255,tile_r+var)); tg=max(0,min(255,tile_g+var)); tb=max(0,min(255,tile_b+var))
            tx2=x+grout_w; ty2=y+grout_w; tw=tile_size-grout_w; th=tile_size-grout_w
            if tx2<width and ty2<height:
                draw.rectangle([tx2,ty2,min(tx2+tw,width),min(ty2+th,height)],fill=(tr,tg,tb))
                if crack_density>0 and random.random()<crack_density/100:
                    draw.line([tx2+random.randint(0,tw),ty2+random.randint(0,th),
                               tx2+random.randint(0,tw),ty2+random.randint(0,th)],fill=(60,60,60),width=1)
            x+=tile_size
        y+=tile_size
    if dirt_amount>0:
        dl=Image.new('RGBA',(width,height),(0,0,0,0)); dd=ImageDraw.Draw(dl)
        for _ in range(int((width+height)/10*(dirt_amount/50))):
            if random.random()<0.5:
                dy2=random.randint(0,height-1)
                dd.line([0,dy2,width,dy2],fill=(30,25,20,random.randint(40,100)),width=grout_w)
            else:
                dx2=random.randint(0,width-1)
                dd.line([dx2,0,dx2,height],fill=(30,25,20,random.randint(40,100)),width=grout_w)
        dl=dl.filter(ImageFilter.GaussianBlur(1))
        img=Image.alpha_composite(img.convert('RGBA'),dl).convert('RGB')
    return pil_to_qimage(img)

def generate_concrete_pattern(width, height, params):
    base_color=params.get('concrete_color','#A0A0A0'); roughness=params.get('roughness',30)
    crack_density=params.get('cracks',0); stain_amount=params.get('stains',0)
    dirt_amount=params.get('dirt',0); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    base_r=int(base_color[1:3],16); base_g=int(base_color[3:5],16); base_b=int(base_color[5:7],16)
    img_array=np.ones((height,width,3),dtype=np.uint8)
    img_array[:,:,0]=base_r; img_array[:,:,1]=base_g; img_array[:,:,2]=base_b
    if roughness>0:
        noise=np.random.randint(-roughness,roughness,(height,width,3))
        img_array=np.clip(img_array.astype(np.int16)+noise,0,255).astype(np.uint8)
    img=Image.fromarray(img_array,'RGB'); draw=ImageDraw.Draw(img)
    if crack_density>0:
        for _ in range(int((width*height/5000)*(crack_density/20))):
            x1=random.randint(0,width); y1=random.randint(0,height)
            pts=[(x1,y1)]
            for _ in range(random.randint(3,8)):
                x1+=random.randint(-15,15); y1+=random.randint(-15,15)
                pts.append((max(0,min(width,x1)),max(0,min(height,y1))))
            draw.line(pts,fill=(40,40,40),width=random.randint(1,2))
    if stain_amount>0:
        sl=Image.new('RGBA',(width,height),(0,0,0,0)); sd=ImageDraw.Draw(sl)
        for _ in range(int((width*height/2000)*(stain_amount/20))):
            sx=random.randint(0,width); sy=random.randint(0,height); size=random.randint(10,40)
            sc=random.choice([(50,50,50,random.randint(30,80)),(80,70,50,random.randint(20,60)),(40,60,40,random.randint(20,50))])
            sd.ellipse([sx-size,sy-size,sx+size,sy+size],fill=sc)
        sl=sl.filter(ImageFilter.GaussianBlur(5))
        img=Image.alpha_composite(img.convert('RGBA'),sl).convert('RGB')
    if dirt_amount>0:
        dl=Image.new('RGBA',(width,height),(0,0,0,0)); dd=ImageDraw.Draw(dl)
        for _ in range(int((width*height/1000)*(dirt_amount/20))):
            dx=random.randint(0,width); dy=random.randint(0,height); size=random.randint(3,12)
            dd.ellipse([dx-size,dy-size,dx+size,dy+size],fill=(35,30,25,random.randint(40,90)))
        dl=dl.filter(ImageFilter.GaussianBlur(3))
        img=Image.alpha_composite(img.convert('RGBA'),dl).convert('RGB')
    return pil_to_qimage(img)

def generate_asphalt_pattern(width, height, params):
    base_color=params.get('asphalt_color','#2A2A2A'); condition=params.get('condition','Fresh')
    crack_density=params.get('cracks',30); stain_amount=params.get('stains',20); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    base_r=int(base_color[1:3],16); base_g=int(base_color[3:5],16); base_b=int(base_color[5:7],16)
    if condition=="Aged": base_r=min(255,base_r+15); base_g=min(255,base_g+15); base_b=min(255,base_b+15)
    elif condition=="Weathered": base_r=min(255,base_r+25); base_g=min(255,base_g+25); base_b=min(255,base_b+25)
    roughness=15 if condition=="Fresh" else (25 if condition=="Aged" else 35)
    img_array=np.ones((height,width,3),dtype=np.uint8)
    img_array[:,:,0]=base_r; img_array[:,:,1]=base_g; img_array[:,:,2]=base_b
    noise=np.random.randint(-roughness,roughness,(height,width,3))
    img_array=np.clip(img_array.astype(np.int16)+noise,0,255).astype(np.uint8)
    img=Image.fromarray(img_array,'RGB'); draw=ImageDraw.Draw(img)
    if crack_density>0:
        for _ in range(int((width*height/5000)*(crack_density/25))):
            x1=random.randint(0,width); y1=random.randint(0,height); pts=[(x1,y1)]
            for _ in range(random.randint(2,6)):
                x1+=random.randint(-20,20); y1+=random.randint(-20,20)
                pts.append((max(0,min(width,x1)),max(0,min(height,y1))))
            draw.line(pts,fill=(20,20,20),width=random.randint(1,2))
    if stain_amount>0:
        sl=Image.new('RGBA',(width,height),(0,0,0,0)); sd=ImageDraw.Draw(sl)
        for _ in range(int((width*height/3000)*(stain_amount/25))):
            sx=random.randint(0,width); sy=random.randint(0,height); size=random.randint(8,25)
            sd.ellipse([sx-size,sy-size,sx+size,sy+size],fill=(15,15,15,random.randint(40,80)))
        sl=sl.filter(ImageFilter.GaussianBlur(4))
        img=Image.alpha_composite(img.convert('RGBA'),sl).convert('RGB')
    return pil_to_qimage(img)

def generate_cobblestone_pattern(width, height, params):
    stone_color=params.get('stone_color','#6B6B6B'); grout_color=params.get('grout_color','#4A4A4A')
    stone_size=params.get('stone_size',20); variation=params.get('variation',25); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    img=Image.new('RGB',(width,height),grout_color); draw=ImageDraw.Draw(img)
    stone_r=int(stone_color[1:3],16); stone_g=int(stone_color[3:5],16); stone_b=int(stone_color[5:7],16)
    grout_w=max(2,stone_size//10); y=0; row=0
    while y<height:
        x=0
        if row%2==1: x=-(stone_size//2)
        while x<width:
            size_var=random.randint(-stone_size//4,stone_size//4); curr_size=max(stone_size//2,stone_size+size_var)
            var=random.randint(-variation,variation)
            sr=max(0,min(255,stone_r+var)); sg=max(0,min(255,stone_g+var)); sb=max(0,min(255,stone_b+var))
            sx2=x+grout_w; sy2=y+grout_w
            if sx2<width and sy2<height:
                draw.rounded_rectangle([sx2,sy2,min(sx2+curr_size-grout_w,width),min(sy2+curr_size-grout_w,height)],radius=random.randint(2,6),fill=(sr,sg,sb))
            x+=curr_size
        y+=stone_size; row+=1
    return pil_to_qimage(img)

def generate_dirt_pattern(width, height, params):
    dirt_color=params.get('dirt_color','#8B7355'); roughness=params.get('roughness',50)
    rock_density=params.get('rocks',30); seed=params.get('seed',42)
    random.seed(seed); np.random.seed(seed)
    dirt_r=int(dirt_color[1:3],16); dirt_g=int(dirt_color[3:5],16); dirt_b=int(dirt_color[5:7],16)
    img_array=np.ones((height,width,3),dtype=np.uint8)
    img_array[:,:,0]=dirt_r; img_array[:,:,1]=dirt_g; img_array[:,:,2]=dirt_b
    noise=np.random.randint(-roughness,roughness,(height,width,3))
    img_array=np.clip(img_array.astype(np.int16)+noise,0,255).astype(np.uint8)
    img=Image.fromarray(img_array,'RGB'); draw=ImageDraw.Draw(img)
    if rock_density>0:
        for _ in range(int((width*height/200)*(rock_density/100))):
            rx=random.randint(0,width); ry=random.randint(0,height); size=random.randint(1,4)
            rb=random.choice([-40,-20,20,40,60])
            rr=max(0,min(255,dirt_r+rb)); rg=max(0,min(255,dirt_g+rb)); rbv=max(0,min(255,dirt_b+rb))
            draw.ellipse([rx-size,ry-size,rx+size,ry+size],fill=(rr,rg,rbv))
    img=img.filter(ImageFilter.GaussianBlur(0.5))
    return pil_to_qimage(img)

def load_custom_texture(filepath):
    try:
        pil_img=Image.open(filepath); return pil_to_qimage(pil_img)
    except Exception as e:
        print(f"Error loading texture: {e}"); return None


# ── City widgets ──────────────────────────────────────────────────────────────

class ColorButton(QPushButton):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color); self.update_style()
        self.clicked.connect(self.choose_color)
    def choose_color(self):
        new_color = QColorDialog.getColor(self.color, self, "Choose Color")
        if new_color.isValid(): self.color = new_color; self.update_style()
    def update_style(self):
        self.setStyleSheet(f"background-color:{self.color.name()};border:1px solid gray;border-radius:4px;")


class MaterialWidget(QWidget):
    def __init__(self, material_name, parent=None):
        super().__init__(parent)
        self.material_name=material_name; self.material_type="Solid Color"
        self.params={}; self.change_callback=None
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        type_layout=QHBoxLayout(); type_layout.addWidget(QLabel(f"{material_name}:"))
        self.combo_type=QComboBox(); self.combo_type.addItems(["Solid Color","Brick","Tile","Concrete","Custom Texture"])
        self.combo_type.currentTextChanged.connect(self.on_type_changed); type_layout.addWidget(self.combo_type)
        layout.addLayout(type_layout)
        self.controls_widget=QWidget(); self.controls_layout=QFormLayout(self.controls_widget)
        layout.addWidget(self.controls_widget)
        weather_box=QGroupBox("Weathering"); weather_form=QFormLayout(weather_box)
        self.slider_weather_dirt=QSlider(Qt.Horizontal); self.slider_weather_dirt.setRange(0,100)
        self.slider_weather_stain=QSlider(Qt.Horizontal); self.slider_weather_stain.setRange(0,100)
        weather_form.addRow("Dirt/Grime:",self.slider_weather_dirt); weather_form.addRow("Stains:",self.slider_weather_stain)
        self.slider_weather_dirt.valueChanged.connect(self.notify_change)
        self.slider_weather_stain.valueChanged.connect(self.notify_change)
        layout.addWidget(weather_box); self.build_solid_color_controls()

    def on_type_changed(self, new_type):
        self.material_type=new_type
        while self.controls_layout.count():
            item=self.controls_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if new_type=="Solid Color": self.build_solid_color_controls()
        elif new_type=="Brick": self.build_brick_controls()
        elif new_type=="Tile": self.build_tile_controls()
        elif new_type=="Concrete": self.build_concrete_controls()
        elif new_type=="Custom Texture": self.build_texture_controls()
        self.notify_change()

    def build_solid_color_controls(self):
        self.btn_color=ColorButton("#444444"); self.btn_color.clicked.connect(self.notify_change)
        self.controls_layout.addRow("Color:",self.btn_color); self.params={"color":"#444444"}

    def build_brick_controls(self):
        self.btn_brick_color=ColorButton("#8B4513"); self.btn_mortar_color=ColorButton("#CCCCCC")
        self.slider_brick_w=self._s(30,100,60); self.slider_brick_h=self._s(10,40,20)
        self.slider_mortar=self._s(1,8,3); self.slider_brick_var=self._s(0,50,20)
        self.slider_brick_dirt=self._s(0,100,0); self.slider_brick_wear=self._s(0,100,0)
        for row,w in [("Brick Color:",self.btn_brick_color),("Mortar Color:",self.btn_mortar_color),
                      ("Brick Width:",self.slider_brick_w),("Brick Height:",self.slider_brick_h),
                      ("Mortar Width:",self.slider_mortar),("Color Variation:",self.slider_brick_var),
                      ("Dirt Amount:",self.slider_brick_dirt),("Wear/Chips:",self.slider_brick_wear)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_brick_color,self.btn_mortar_color,self.slider_brick_w,self.slider_brick_h,
                  self.slider_mortar,self.slider_brick_var,self.slider_brick_dirt,self.slider_brick_wear]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_brick_params()

    def build_tile_controls(self):
        self.btn_tile_color=ColorButton("#E0E0E0"); self.btn_grout_color=ColorButton("#888888")
        self.slider_tile_size=self._s(20,80,40); self.slider_grout=self._s(1,6,2)
        self.slider_tile_var=self._s(0,30,10); self.slider_tile_dirt=self._s(0,100,0)
        self.slider_tile_cracks=self._s(0,100,0)
        for row,w in [("Tile Color:",self.btn_tile_color),("Grout Color:",self.btn_grout_color),
                      ("Tile Size:",self.slider_tile_size),("Grout Width:",self.slider_grout),
                      ("Color Variation:",self.slider_tile_var),("Dirt Amount:",self.slider_tile_dirt),
                      ("Crack Density:",self.slider_tile_cracks)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_tile_color,self.btn_grout_color,self.slider_tile_size,self.slider_grout,
                  self.slider_tile_var,self.slider_tile_dirt,self.slider_tile_cracks]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_tile_params()

    def build_concrete_controls(self):
        self.btn_concrete_color=ColorButton("#A0A0A0"); self.slider_roughness=self._s(0,60,30)
        self.slider_concrete_cracks=self._s(0,100,0); self.slider_stains=self._s(0,100,0)
        self.slider_concrete_dirt=self._s(0,100,0)
        for row,w in [("Base Color:",self.btn_concrete_color),("Roughness:",self.slider_roughness),
                      ("Crack Density:",self.slider_concrete_cracks),("Stains:",self.slider_stains),
                      ("Dirt Amount:",self.slider_concrete_dirt)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_concrete_color,self.slider_roughness,self.slider_concrete_cracks,
                  self.slider_stains,self.slider_concrete_dirt]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_concrete_params()

    def build_texture_controls(self):
        self.btn_load_texture=QPushButton("Load Texture File"); self.btn_load_texture.clicked.connect(self.load_texture)
        self.lbl_texture_path=QLabel("No texture loaded"); self.lbl_texture_path.setWordWrap(True)
        self.controls_layout.addRow("Texture:",self.btn_load_texture)
        self.controls_layout.addRow("",self.lbl_texture_path)
        self.params={"texture_path":None,"texture_image":None}

    def load_texture(self):
        fp,_=QFileDialog.getOpenFileName(self,"Load Texture","","Images (*.png *.jpg *.jpeg *.bmp)")
        if fp:
            ti=load_custom_texture(fp)
            if ti:
                self.params["texture_path"]=fp; self.params["texture_image"]=ti
                self.lbl_texture_path.setText(fp.split('/')[-1]); self.notify_change()

    def _s(self,mn,mx,dv):
        s=QSlider(Qt.Horizontal); s.setRange(mn,mx); s.setValue(dv); return s

    def update_brick_params(self):
        self.params={"brick_color":self.btn_brick_color.color.name(),"mortar_color":self.btn_mortar_color.color.name(),
                     "brick_width":self.slider_brick_w.value(),"brick_height":self.slider_brick_h.value(),
                     "mortar_width":self.slider_mortar.value(),"color_variation":self.slider_brick_var.value(),
                     "dirt":self.slider_brick_dirt.value(),"wear":self.slider_brick_wear.value()}

    def update_tile_params(self):
        self.params={"tile_color":self.btn_tile_color.color.name(),"grout_color":self.btn_grout_color.color.name(),
                     "tile_size":self.slider_tile_size.value(),"grout_width":self.slider_grout.value(),
                     "color_variation":self.slider_tile_var.value(),"dirt":self.slider_tile_dirt.value(),
                     "cracks":self.slider_tile_cracks.value()}

    def update_concrete_params(self):
        self.params={"concrete_color":self.btn_concrete_color.color.name(),"roughness":self.slider_roughness.value(),
                     "cracks":self.slider_concrete_cracks.value(),"stains":self.slider_stains.value(),
                     "dirt":self.slider_concrete_dirt.value()}

    def notify_change(self):
        if self.material_type=="Brick": self.update_brick_params()
        elif self.material_type=="Tile": self.update_tile_params()
        elif self.material_type=="Concrete": self.update_concrete_params()
        elif self.material_type=="Solid Color": self.params={"color":self.btn_color.color.name()}
        self.params["weather_dirt"]=self.slider_weather_dirt.value()
        self.params["weather_stain"]=self.slider_weather_stain.value()
        if self.change_callback: self.change_callback()

    def get_brush(self, width, height, seed=42):
        if self.material_type=="Solid Color": return QBrush(QColor(self.params.get("color","#444444")))
        elif self.material_type=="Custom Texture":
            if self.params.get("texture_image"): return QBrush(QPixmap.fromImage(self.params["texture_image"]))
            return QBrush(QColor("#888888"))
        elif self.material_type=="Brick":
            p=self.params.copy(); p['seed']=seed
            ck=f"brick_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_brick_pattern(width,height,p))))
        elif self.material_type=="Tile":
            p=self.params.copy(); p['seed']=seed
            ck=f"tile_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_tile_pattern(width,height,p))))
        elif self.material_type=="Concrete":
            p=self.params.copy(); p['seed']=seed
            ck=f"concrete_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_concrete_pattern(width,height,p))))
        return QBrush(QColor("#888888"))

    def get_data(self):
        return {"type":self.material_type,"params":self.params.copy()}

    def set_data(self, data):
        self.combo_type.setCurrentText(data.get("type","Solid Color"))


class BuildingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.building_types=[]
        main_layout=QVBoxLayout(self)
        lib_layout=QHBoxLayout()
        self.combo_box=QComboBox(); self.combo_box.currentIndexChanged.connect(self.load_selected)
        self.btn_add=QPushButton("+ Add Building"); self.btn_add.clicked.connect(self.add_new)
        lib_layout.addWidget(QLabel("Preset:")); lib_layout.addWidget(self.combo_box); lib_layout.addWidget(self.btn_add)
        main_layout.addLayout(lib_layout)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll_content=QWidget(); self.scroll_layout=QVBoxLayout(self.scroll_content)
        group_base=QGroupBox("1. Grid & Base Shape"); form_base=QFormLayout(group_base)
        self.spin_grid_w=QSpinBox(); self.spin_grid_w.setRange(1,10)
        self.spin_grid_h=QSpinBox(); self.spin_grid_h.setRange(1,10)
        self.slider_width=self._s(20,100,80); self.slider_depth=self._s(20,100,80)
        self.slider_edge=self._s(0,50,0)
        form_base.addRow("Grid Width:",self.spin_grid_w); form_base.addRow("Grid Depth:",self.spin_grid_h)
        form_base.addRow("Vis Width (%):",self.slider_width); form_base.addRow("Vis Depth (%):",self.slider_depth)
        form_base.addRow("Edge Rounding:",self.slider_edge); self.scroll_layout.addWidget(group_base)
        group_mass=QGroupBox("2. Massing & Tiers"); form_mass=QFormLayout(group_mass)
        self.slider_height=self._s(10,200,60); self.spin_tiers=QSpinBox(); self.spin_tiers.setRange(1,5)
        self.slider_shrink=self._s(50,150,85)
        form_mass.addRow("Base Height:",self.slider_height); form_mass.addRow("Tier Count:",self.spin_tiers)
        form_mass.addRow("Tier Shrink/Grow (%):",self.slider_shrink); self.scroll_layout.addWidget(group_mass)
        group_roof=QGroupBox("3. Roof & Architecture"); form_roof=QFormLayout(group_roof)
        self.combo_roof=QComboBox(); self.combo_roof.addItems(["Flat","Pitched"])
        self.slider_inset=self._s(0,20,5); self.slider_greeble=self._s(0,20,0)
        form_roof.addRow("Roof Style:",self.combo_roof); form_roof.addRow("Roof Inset:",self.slider_inset)
        form_roof.addRow("Greeble Density:",self.slider_greeble); self.scroll_layout.addWidget(group_roof)
        group_facade=QGroupBox("4. Facades & Details"); form_facade=QFormLayout(group_facade)
        self.spin_win_cols=QSpinBox(); self.spin_win_cols.setRange(0,10)
        self.spin_win_rows=QSpinBox(); self.spin_win_rows.setRange(0,10)
        self.slider_lit=self._s(0,100,30); self.combo_sign=QComboBox()
        self.combo_sign.addItems(["None","Neon Left","Banner Right"])
        form_facade.addRow("Window Cols:",self.spin_win_cols); form_facade.addRow("Window Rows:",self.spin_win_rows)
        form_facade.addRow("Lit Window %:",self.slider_lit); form_facade.addRow("Signage:",self.combo_sign)
        self.scroll_layout.addWidget(group_facade)
        group_material=QGroupBox("5. Materials"); material_layout=QVBoxLayout(group_material)
        self.wall_material=MaterialWidget("Wall Material"); self.wall_material.change_callback=self.save_and_notify
        material_layout.addWidget(self.wall_material)
        self.roof_material=MaterialWidget("Roof Material"); self.roof_material.change_callback=self.save_and_notify
        material_layout.addWidget(self.roof_material)
        win_layout=QHBoxLayout(); win_layout.addWidget(QLabel("Window Light:"))
        self.btn_win_color=ColorButton("#FFD700"); self.btn_win_color.clicked.connect(self.save_and_notify)
        win_layout.addWidget(self.btn_win_color); material_layout.addLayout(win_layout)
        self.scroll_layout.addWidget(group_material)
        self.scroll_layout.addStretch(); self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll)
        for w in [self.slider_width,self.slider_depth,self.slider_height,self.slider_edge,self.slider_inset,
                  self.spin_grid_w,self.spin_grid_h,self.spin_tiers,self.slider_shrink,self.slider_greeble,
                  self.spin_win_cols,self.spin_win_rows,self.slider_lit]:
            w.valueChanged.connect(self.save_and_notify)
        self.combo_roof.currentIndexChanged.connect(self.save_and_notify)
        self.combo_sign.currentIndexChanged.connect(self.save_and_notify)
        self.add_new()

    def _s(self,mn,mx,dv):
        s=QSlider(Qt.Horizontal); s.setRange(mn,mx); s.setValue(dv); return s

    def add_new(self):
        b_id=len(self.building_types)+1; name=f"Building {b_id}"
        new_bldg={"type":"building","name":name,"grid_w":1,"grid_h":1,"width":80,"depth":80,
                  "height":60,"edge":0,"inset":5,"tiers":1,"shrink":85,"roof":"Flat","greebles":0,
                  "win_cols":0,"win_rows":0,"win_lit":30,"sign":"None",
                  "wall_material":{"type":"Solid Color","params":{"color":"#444444"}},
                  "roof_material":{"type":"Solid Color","params":{"color":"#777777"}},"win_color":"#FFD700"}
        self.building_types.append(new_bldg); self.combo_box.addItem(name)
        self.combo_box.setCurrentIndex(b_id-1)

    def load_selected(self, index):
        if index<0 or index>=len(self.building_types): return
        self.blockSignals(True); b=self.building_types[index]
        self.spin_grid_w.setValue(b.get("grid_w",1)); self.spin_grid_h.setValue(b.get("grid_h",1))
        self.slider_width.setValue(b.get("width",80)); self.slider_depth.setValue(b.get("depth",80))
        self.slider_height.setValue(b.get("height",60)); self.slider_edge.setValue(b.get("edge",0))
        self.spin_tiers.setValue(b.get("tiers",1)); self.slider_shrink.setValue(b.get("shrink",85))
        self.combo_roof.setCurrentText(b.get("roof","Flat")); self.slider_inset.setValue(b.get("inset",5))
        self.slider_greeble.setValue(b.get("greebles",0)); self.spin_win_cols.setValue(b.get("win_cols",0))
        self.spin_win_rows.setValue(b.get("win_rows",0)); self.slider_lit.setValue(b.get("win_lit",30))
        self.combo_sign.setCurrentText(b.get("sign","None"))
        self.wall_material.set_data(b.get("wall_material",{"type":"Solid Color","params":{"color":"#444444"}}))
        self.roof_material.set_data(b.get("roof_material",{"type":"Solid Color","params":{"color":"#777777"}}))
        self.btn_win_color.color=QColor(b.get("win_color","#FFD700")); self.btn_win_color.update_style()
        self.blockSignals(False)
        if hasattr(self,'main_window'): self.main_window.city_canvas.redraw_all()

    def save_and_notify(self):
        index=self.combo_box.currentIndex()
        if index<0: return
        b=self.building_types[index]
        b["grid_w"]=self.spin_grid_w.value(); b["grid_h"]=self.spin_grid_h.value()
        b["width"]=self.slider_width.value(); b["depth"]=self.slider_depth.value()
        b["height"]=self.slider_height.value(); b["edge"]=self.slider_edge.value()
        b["tiers"]=self.spin_tiers.value(); b["shrink"]=self.slider_shrink.value()
        b["roof"]=self.combo_roof.currentText(); b["inset"]=self.slider_inset.value()
        b["greebles"]=self.slider_greeble.value(); b["win_cols"]=self.spin_win_cols.value()
        b["win_rows"]=self.spin_win_rows.value(); b["win_lit"]=self.slider_lit.value()
        b["sign"]=self.combo_sign.currentText()
        b["wall_material"]=self.wall_material.get_data(); b["roof_material"]=self.roof_material.get_data()
        b["win_color"]=self.btn_win_color.color.name()
        if hasattr(self,'main_window'): self.main_window.city_canvas.redraw_all()

    def get_current_data(self):
        idx=self.combo_box.currentIndex()
        return self.building_types[idx] if idx>=0 else None


class RoadMaterialWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.material_type="Solid Color"; self.params={}; self.change_callback=None
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        type_layout=QHBoxLayout(); type_layout.addWidget(QLabel("Surface:"))
        self.combo_type=QComboBox()
        self.combo_type.addItems(["Solid Color","Asphalt","Concrete","Cobblestone","Dirt","Custom Texture"])
        self.combo_type.currentTextChanged.connect(self.on_type_changed); type_layout.addWidget(self.combo_type)
        layout.addLayout(type_layout)
        self.controls_widget=QWidget(); self.controls_layout=QFormLayout(self.controls_widget)
        layout.addWidget(self.controls_widget); self.build_solid_color_controls()

    def on_type_changed(self, new_type):
        self.material_type=new_type
        while self.controls_layout.count():
            item=self.controls_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if new_type=="Solid Color": self.build_solid_color_controls()
        elif new_type=="Asphalt": self.build_asphalt_controls()
        elif new_type=="Concrete": self.build_concrete_controls()
        elif new_type=="Cobblestone": self.build_cobblestone_controls()
        elif new_type=="Dirt": self.build_dirt_controls()
        elif new_type=="Custom Texture": self.build_texture_controls()
        self.notify_change()

    def build_solid_color_controls(self):
        self.btn_color=ColorButton("#333333"); self.btn_color.clicked.connect(self.notify_change)
        self.controls_layout.addRow("Color:",self.btn_color); self.params={"color":"#333333"}

    def build_asphalt_controls(self):
        self.btn_asphalt_color=ColorButton("#2A2A2A"); self.combo_condition=QComboBox()
        self.combo_condition.addItems(["Fresh","Aged","Weathered"])
        self.slider_cracks=self._s(0,100,30); self.slider_stains=self._s(0,100,20)
        for row,w in [("Base Color:",self.btn_asphalt_color),("Condition:",self.combo_condition),
                      ("Cracks:",self.slider_cracks),("Oil Stains:",self.slider_stains)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_asphalt_color,self.combo_condition,self.slider_cracks,self.slider_stains]:
            if isinstance(w,QSlider): w.valueChanged.connect(self.notify_change)
            elif isinstance(w,QComboBox): w.currentTextChanged.connect(self.notify_change)
            else: w.clicked.connect(self.notify_change)
        self.update_asphalt_params()

    def build_concrete_controls(self):
        self.btn_concrete_color=ColorButton("#8A8A8A"); self.slider_concrete_rough=self._s(0,60,25)
        self.slider_concrete_cracks=self._s(0,100,15)
        for row,w in [("Base Color:",self.btn_concrete_color),("Roughness:",self.slider_concrete_rough),
                      ("Cracks:",self.slider_concrete_cracks)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_concrete_color,self.slider_concrete_rough,self.slider_concrete_cracks]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_concrete_params()

    def build_cobblestone_controls(self):
        self.btn_stone_color=ColorButton("#6B6B6B"); self.btn_grout_color=ColorButton("#4A4A4A")
        self.slider_stone_size=self._s(10,40,20); self.slider_stone_var=self._s(0,40,25)
        for row,w in [("Stone Color:",self.btn_stone_color),("Grout Color:",self.btn_grout_color),
                      ("Stone Size:",self.slider_stone_size),("Variation:",self.slider_stone_var)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_stone_color,self.btn_grout_color,self.slider_stone_size,self.slider_stone_var]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_cobblestone_params()

    def build_dirt_controls(self):
        self.btn_dirt_color=ColorButton("#8B7355"); self.slider_dirt_rough=self._s(20,80,50)
        self.slider_rocks=self._s(0,100,30)
        for row,w in [("Dirt Color:",self.btn_dirt_color),("Roughness:",self.slider_dirt_rough),
                      ("Rocks/Debris:",self.slider_rocks)]:
            self.controls_layout.addRow(row,w)
        for w in [self.btn_dirt_color,self.slider_dirt_rough,self.slider_rocks]:
            (w.valueChanged if isinstance(w,QSlider) else w.clicked).connect(self.notify_change)
        self.update_dirt_params()

    def build_texture_controls(self):
        self.btn_load_texture=QPushButton("Load Texture File"); self.btn_load_texture.clicked.connect(self.load_texture)
        self.lbl_texture_path=QLabel("No texture loaded"); self.lbl_texture_path.setWordWrap(True)
        self.controls_layout.addRow("Texture:",self.btn_load_texture)
        self.controls_layout.addRow("",self.lbl_texture_path)
        self.params={"texture_path":None,"texture_image":None}

    def load_texture(self):
        fp,_=QFileDialog.getOpenFileName(self,"Load Texture","","Images (*.png *.jpg *.jpeg *.bmp)")
        if fp:
            ti=load_custom_texture(fp)
            if ti:
                self.params["texture_path"]=fp; self.params["texture_image"]=ti
                self.lbl_texture_path.setText(fp.split('/')[-1]); self.notify_change()

    def _s(self,mn,mx,dv):
        s=QSlider(Qt.Horizontal); s.setRange(mn,mx); s.setValue(dv); return s

    def update_asphalt_params(self):
        self.params={"asphalt_color":self.btn_asphalt_color.color.name(),
                     "condition":self.combo_condition.currentText(),
                     "cracks":self.slider_cracks.value(),"stains":self.slider_stains.value()}

    def update_concrete_params(self):
        self.params={"concrete_color":self.btn_concrete_color.color.name(),
                     "roughness":self.slider_concrete_rough.value(),"cracks":self.slider_concrete_cracks.value()}

    def update_cobblestone_params(self):
        self.params={"stone_color":self.btn_stone_color.color.name(),"grout_color":self.btn_grout_color.color.name(),
                     "stone_size":self.slider_stone_size.value(),"variation":self.slider_stone_var.value()}

    def update_dirt_params(self):
        self.params={"dirt_color":self.btn_dirt_color.color.name(),"roughness":self.slider_dirt_rough.value(),
                     "rocks":self.slider_rocks.value()}

    def notify_change(self):
        if self.material_type=="Asphalt": self.update_asphalt_params()
        elif self.material_type=="Concrete": self.update_concrete_params()
        elif self.material_type=="Cobblestone": self.update_cobblestone_params()
        elif self.material_type=="Dirt": self.update_dirt_params()
        elif self.material_type=="Solid Color": self.params={"color":self.btn_color.color.name()}
        if self.change_callback: self.change_callback()

    def get_data(self): return {"type":self.material_type,"params":self.params.copy()}
    def set_data(self, data): self.combo_type.setCurrentText(data.get("type","Solid Color"))


class RoadTab(QWidget):
    def __init__(self):
        super().__init__()
        self.road_types=[]
        main_layout=QVBoxLayout(self)
        lib_layout=QHBoxLayout()
        self.combo_box=QComboBox(); self.combo_box.currentIndexChanged.connect(self.load_selected)
        self.btn_add=QPushButton("+ Add Road Type"); self.btn_add.clicked.connect(self.add_new)
        lib_layout.addWidget(QLabel("Preset:")); lib_layout.addWidget(self.combo_box); lib_layout.addWidget(self.btn_add)
        main_layout.addLayout(lib_layout)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll_content=QWidget(); self.scroll_layout=QVBoxLayout(self.scroll_content)
        group_surface=QGroupBox("1. Surface Material"); surface_layout=QVBoxLayout(group_surface)
        self.surface_material=RoadMaterialWidget(); self.surface_material.change_callback=self.save_and_notify
        surface_layout.addWidget(self.surface_material); self.scroll_layout.addWidget(group_surface)
        group_config=QGroupBox("2. Road Configuration"); form_config=QFormLayout(group_config)
        self.combo_width=QComboBox(); self.combo_width.addItems(["Alley (1-lane)","Street (2-lane)","Highway (4-lane)"])
        self.combo_width.setCurrentIndex(1)
        self.check_sidewalks=QComboBox(); self.check_sidewalks.addItems(["No Sidewalks","With Sidewalks"])
        self.slider_sidewalk_width=self._s(5,20,10); self.btn_sidewalk_color=ColorButton("#8A8A8A")
        form_config.addRow("Width Type:",self.combo_width); form_config.addRow("Sidewalks:",self.check_sidewalks)
        form_config.addRow("Sidewalk Width:",self.slider_sidewalk_width)
        form_config.addRow("Sidewalk Color:",self.btn_sidewalk_color); self.scroll_layout.addWidget(group_config)
        group_markings=QGroupBox("3. Markings & Lines"); form_markings=QFormLayout(group_markings)
        self.combo_centerline=QComboBox()
        self.combo_centerline.addItems(["None","Dashed Yellow","Solid Yellow","Double Yellow","Dashed White"])
        self.combo_centerline.setCurrentIndex(1); self.btn_line_color=ColorButton("#FFD700")
        self.check_crosswalks=QComboBox(); self.check_crosswalks.addItems(["No Crosswalks","Crosswalks at Intersections"])
        self.check_parking=QComboBox(); self.check_parking.addItems(["No Parking Spaces","Parking Spaces"])
        form_markings.addRow("Center Line:",self.combo_centerline); form_markings.addRow("Line Color:",self.btn_line_color)
        form_markings.addRow("Crosswalks:",self.check_crosswalks); form_markings.addRow("Parking:",self.check_parking)
        self.scroll_layout.addWidget(group_markings)
        group_elevation=QGroupBox("4. Elevation & Bridges"); form_elevation=QFormLayout(group_elevation)
        self.spin_elevation=QSpinBox(); self.spin_elevation.setRange(0,3)
        self.check_railings=QComboBox(); self.check_railings.addItems(["No Railings","With Railings"])
        self.combo_pillars=QComboBox(); self.combo_pillars.addItems(["Concrete Pillars","Steel Pillars","Brick Pillars"])
        form_elevation.addRow("Elevation Level:",self.spin_elevation)
        form_elevation.addRow("Railings:",self.check_railings)
        form_elevation.addRow("Support Style:",self.combo_pillars); self.scroll_layout.addWidget(group_elevation)
        group_features=QGroupBox("5. Street Features"); form_features=QFormLayout(group_features)
        self.combo_lights=QComboBox(); self.combo_lights.addItems(["No Lights","Corners Only","Both Sides"])
        self.slider_manholes=self._s(0,10,0)
        self.check_drains=QComboBox(); self.check_drains.addItems(["No Drains","Storm Drains"])
        self.check_signals=QComboBox(); self.check_signals.addItems(["No Signals","Traffic Lights at 4-way"])
        form_features.addRow("Street Lights:",self.combo_lights)
        form_features.addRow("Manhole Density:",self.slider_manholes)
        form_features.addRow("Storm Drains:",self.check_drains)
        form_features.addRow("Traffic Signals:",self.check_signals); self.scroll_layout.addWidget(group_features)
        self.scroll_layout.addStretch(); self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll)
        for w in [self.combo_width,self.check_sidewalks,self.slider_sidewalk_width,self.btn_sidewalk_color,
                  self.combo_centerline,self.btn_line_color,self.check_crosswalks,self.check_parking,
                  self.spin_elevation,self.check_railings,self.combo_pillars,self.combo_lights,
                  self.slider_manholes,self.check_drains,self.check_signals]:
            if isinstance(w,QSlider): w.valueChanged.connect(self.save_and_notify)
            elif isinstance(w,QSpinBox): w.valueChanged.connect(self.save_and_notify)
            elif isinstance(w,QComboBox): w.currentTextChanged.connect(self.save_and_notify)
            elif isinstance(w,ColorButton): w.clicked.connect(self.save_and_notify)
        self.add_new()

    def _s(self,mn,mx,dv):
        s=QSlider(Qt.Horizontal); s.setRange(mn,mx); s.setValue(dv); return s

    def add_new(self):
        r_id=len(self.road_types)+1; name=f"Road Type {r_id}"
        new_road={"type":"road","name":name,"grid_w":1,"grid_h":1,
                  "surface_material":{"type":"Solid Color","params":{"color":"#333333"}},
                  "width_type":"Street (2-lane)","sidewalks":"No Sidewalks","sidewalk_width":10,
                  "sidewalk_color":"#8A8A8A","centerline":"Dashed Yellow","line_color":"#FFD700",
                  "crosswalks":"No Crosswalks","parking":"No Parking Spaces","elevation":0,
                  "railings":"No Railings","pillars":"Concrete Pillars","lights":"No Lights",
                  "manholes":0,"drains":"No Drains","signals":"No Signals"}
        self.road_types.append(new_road); self.combo_box.addItem(name)
        self.combo_box.setCurrentIndex(r_id-1)

    def load_selected(self, index):
        if index<0 or index>=len(self.road_types): return
        self.blockSignals(True); road=self.road_types[index]
        self.surface_material.set_data(road.get("surface_material",{"type":"Solid Color","params":{"color":"#333333"}}))
        self.combo_width.setCurrentText(road.get("width_type","Street (2-lane)"))
        self.check_sidewalks.setCurrentText(road.get("sidewalks","No Sidewalks"))
        self.slider_sidewalk_width.setValue(road.get("sidewalk_width",10))
        self.btn_sidewalk_color.color=QColor(road.get("sidewalk_color","#8A8A8A")); self.btn_sidewalk_color.update_style()
        self.combo_centerline.setCurrentText(road.get("centerline","Dashed Yellow"))
        self.btn_line_color.color=QColor(road.get("line_color","#FFD700")); self.btn_line_color.update_style()
        self.check_crosswalks.setCurrentText(road.get("crosswalks","No Crosswalks"))
        self.check_parking.setCurrentText(road.get("parking","No Parking Spaces"))
        self.spin_elevation.setValue(road.get("elevation",0))
        self.check_railings.setCurrentText(road.get("railings","No Railings"))
        self.combo_pillars.setCurrentText(road.get("pillars","Concrete Pillars"))
        self.combo_lights.setCurrentText(road.get("lights","No Lights"))
        self.slider_manholes.setValue(road.get("manholes",0))
        self.check_drains.setCurrentText(road.get("drains","No Drains"))
        self.check_signals.setCurrentText(road.get("signals","No Signals"))
        self.blockSignals(False)

    def save_and_notify(self):
        index=self.combo_box.currentIndex()
        if index<0: return
        road=self.road_types[index]
        road["surface_material"]=self.surface_material.get_data()
        road["width_type"]=self.combo_width.currentText()
        road["sidewalks"]=self.check_sidewalks.currentText()
        road["sidewalk_width"]=self.slider_sidewalk_width.value()
        road["sidewalk_color"]=self.btn_sidewalk_color.color.name()
        road["centerline"]=self.combo_centerline.currentText()
        road["line_color"]=self.btn_line_color.color.name()
        road["crosswalks"]=self.check_crosswalks.currentText()
        road["parking"]=self.check_parking.currentText()
        road["elevation"]=self.spin_elevation.value()
        road["railings"]=self.check_railings.currentText()
        road["pillars"]=self.combo_pillars.currentText()
        road["lights"]=self.combo_lights.currentText()
        road["manholes"]=self.slider_manholes.value()
        road["drains"]=self.check_drains.currentText()
        road["signals"]=self.check_signals.currentText()
        if hasattr(self,'main_window'): self.main_window.city_canvas.redraw_all()

    def get_current_data(self):
        idx=self.combo_box.currentIndex()
        return self.road_types[idx] if idx>=0 else None


class EnvironmentTab(QWidget):
    def __init__(self):
        super().__init__()
        self.env_types=[]
        main_layout=QVBoxLayout(self)
        lib_layout=QHBoxLayout()
        self.combo_box=QComboBox(); self.combo_box.currentIndexChanged.connect(self.load_selected)
        self.btn_add=QPushButton("+ Add Object"); self.btn_add.clicked.connect(self.add_new)
        lib_layout.addWidget(QLabel("Preset:")); lib_layout.addWidget(self.combo_box); lib_layout.addWidget(self.btn_add)
        main_layout.addLayout(lib_layout)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll_content=QWidget(); self.scroll_layout=QVBoxLayout(self.scroll_content)
        group_type=QGroupBox("1. Object Type"); form_type=QFormLayout(group_type)
        self.combo_env_type=QComboBox()
        self.combo_env_type.addItems(["Tree","Terrain Patch","Vacant Lot","Water Feature"])
        self.combo_env_type.currentTextChanged.connect(self._on_env_type_changed)
        form_type.addRow("Type:",self.combo_env_type); self.scroll_layout.addWidget(group_type)
        # Tree
        self.group_tree=QGroupBox("2. Tree Settings"); form_tree=QFormLayout(self.group_tree)
        self.combo_tree_species=QComboBox(); self.combo_tree_species.addItems(["Deciduous","Pine","Palm","Dead","Shrub"])
        self.slider_tree_canopy=self._s(30,95,65); self.slider_tree_trunk=self._s(5,30,12)
        self.btn_tree_canopy_color=ColorButton("#3A6B2A"); self.btn_tree_trunk_color=ColorButton("#5C3A1E")
        self.slider_tree_color_var=self._s(0,40,15); self.slider_tree_density=self._s(1,5,1)
        for row,w in [("Species:",self.combo_tree_species),("Canopy Size (%):",self.slider_tree_canopy),
                      ("Trunk Width:",self.slider_tree_trunk),("Canopy Color:",self.btn_tree_canopy_color),
                      ("Trunk Color:",self.btn_tree_trunk_color),("Color Variation:",self.slider_tree_color_var),
                      ("Trees per Tile:",self.slider_tree_density)]:
            form_tree.addRow(row,w)
        self.scroll_layout.addWidget(self.group_tree)
        # Terrain
        self.group_terrain=QGroupBox("2. Terrain Settings"); form_terrain=QFormLayout(self.group_terrain)
        self.combo_terrain_type=QComboBox(); self.combo_terrain_type.addItems(["Grass","Gravel","Mud","Sand","Snow"])
        self.slider_terrain_roughness=self._s(0,80,30); self.slider_terrain_wear=self._s(0,100,20)
        self.btn_terrain_color=ColorButton("#5A8A3C"); self.slider_terrain_rock=self._s(0,60,0)
        self.slider_terrain_weed=self._s(0,60,0)
        for row,w in [("Surface:",self.combo_terrain_type),("Base Color:",self.btn_terrain_color),
                      ("Roughness:",self.slider_terrain_roughness),("Wear/Patching:",self.slider_terrain_wear),
                      ("Rocks:",self.slider_terrain_rock),("Weeds:",self.slider_terrain_weed)]:
            form_terrain.addRow(row,w)
        self.scroll_layout.addWidget(self.group_terrain)
        # Vacant
        self.group_vacant=QGroupBox("2. Vacant Lot Settings"); form_vacant=QFormLayout(self.group_vacant)
        self.slider_vacant_debris=self._s(0,100,40); self.slider_vacant_vegetation=self._s(0,100,30)
        self.combo_vacant_fence=QComboBox(); self.combo_vacant_fence.addItems(["No Fence","Chain Link","Wooden","Collapsed"])
        self.btn_vacant_ground_color=ColorButton("#6B5A3E"); self.slider_vacant_puddles=self._s(0,60,0)
        for row,w in [("Ground Color:",self.btn_vacant_ground_color),("Debris Amount:",self.slider_vacant_debris),
                      ("Vegetation:",self.slider_vacant_vegetation),("Fence:",self.combo_vacant_fence),
                      ("Puddles:",self.slider_vacant_puddles)]:
            form_vacant.addRow(row,w)
        self.scroll_layout.addWidget(self.group_vacant)
        # Water
        self.group_water=QGroupBox("2. Water Feature Settings"); form_water=QFormLayout(self.group_water)
        self.btn_water_shallow=ColorButton("#5B9EC9"); self.btn_water_deep=ColorButton("#1A4A7A")
        self.btn_water_shore=ColorButton("#7A8C6E")
        self.combo_water_shore_style=QComboBox(); self.combo_water_shore_style.addItems(["Grassy","Stone","Dirt","Concrete"])
        self.slider_water_shore_width=self._s(2,20,8)
        self.combo_water_feature=QComboBox(); self.combo_water_feature.addItems(["None","Fountain","Lily Pads","Reeds","Lily Pads & Reeds"])
        self.slider_water_turbulence=self._s(0,100,20); self.slider_water_depth_rings=self._s(1,6,3)
        for row,w in [("Shallow Color:",self.btn_water_shallow),("Deep Color:",self.btn_water_deep),
                      ("Shore Color:",self.btn_water_shore),("Shore Style:",self.combo_water_shore_style),
                      ("Shore Width:",self.slider_water_shore_width),("Feature:",self.combo_water_feature),
                      ("Turbulence:",self.slider_water_turbulence),("Depth Rings:",self.slider_water_depth_rings)]:
            form_water.addRow(row,w)
        self.scroll_layout.addWidget(self.group_water)
        self.scroll_layout.addStretch(); self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll)
        for w in [self.combo_tree_species,self.combo_terrain_type,self.combo_vacant_fence,
                  self.combo_water_shore_style,self.combo_water_feature]:
            w.currentTextChanged.connect(self.save_and_notify)
        for w in [self.slider_tree_canopy,self.slider_tree_trunk,self.slider_tree_color_var,
                  self.slider_tree_density,self.slider_terrain_roughness,self.slider_terrain_wear,
                  self.slider_terrain_rock,self.slider_terrain_weed,self.slider_vacant_debris,
                  self.slider_vacant_vegetation,self.slider_vacant_puddles,
                  self.slider_water_shore_width,self.slider_water_turbulence,self.slider_water_depth_rings]:
            w.valueChanged.connect(self.save_and_notify)
        for w in [self.btn_tree_canopy_color,self.btn_tree_trunk_color,self.btn_terrain_color,
                  self.btn_vacant_ground_color,self.btn_water_shallow,self.btn_water_deep,self.btn_water_shore]:
            w.clicked.connect(self.save_and_notify)
        self._on_env_type_changed("Tree"); self.add_new()

    def _s(self,mn,mx,dv):
        s=QSlider(Qt.Horizontal); s.setRange(mn,mx); s.setValue(dv); return s

    def _on_env_type_changed(self, env_type):
        self.group_tree.setVisible(env_type=="Tree")
        self.group_terrain.setVisible(env_type=="Terrain Patch")
        self.group_vacant.setVisible(env_type=="Vacant Lot")
        self.group_water.setVisible(env_type=="Water Feature")
        defaults={"Grass":"#5A8A3C","Gravel":"#8A7E6A","Mud":"#6B5030","Sand":"#C4A96A","Snow":"#E8ECEE"}
        if env_type=="Terrain Patch":
            self.btn_terrain_color.color=QColor(defaults.get(self.combo_terrain_type.currentText(),"#5A8A3C"))
            self.btn_terrain_color.update_style()
        self.save_and_notify()

    def add_new(self):
        e_id=len(self.env_types)+1; name=f"Env {e_id}"
        new_env={"type":"environment","name":name,"env_type":"Tree",
                 "tree_species":"Deciduous","tree_canopy":65,"tree_trunk":12,
                 "tree_canopy_color":"#3A6B2A","tree_trunk_color":"#5C3A1E","tree_color_var":15,"tree_density":1,
                 "terrain_type":"Grass","terrain_color":"#5A8A3C","terrain_roughness":30,"terrain_wear":20,
                 "terrain_rock":0,"terrain_weed":0,"vacant_ground_color":"#6B5A3E","vacant_debris":40,
                 "vacant_vegetation":30,"vacant_fence":"No Fence","vacant_puddles":0,
                 "water_shallow":"#5B9EC9","water_deep":"#1A4A7A","water_shore":"#7A8C6E",
                 "water_shore_style":"Grassy","water_shore_width":8,"water_feature":"None",
                 "water_turbulence":20,"water_depth_rings":3}
        self.env_types.append(new_env); self.combo_box.addItem(name)
        self.combo_box.setCurrentIndex(e_id-1)

    def load_selected(self, index):
        if index<0 or index>=len(self.env_types): return
        self.blockSignals(True); e=self.env_types[index]
        self.combo_env_type.setCurrentText(e.get("env_type","Tree"))
        self.combo_tree_species.setCurrentText(e.get("tree_species","Deciduous"))
        self.slider_tree_canopy.setValue(e.get("tree_canopy",65))
        self.slider_tree_trunk.setValue(e.get("tree_trunk",12))
        self.btn_tree_canopy_color.color=QColor(e.get("tree_canopy_color","#3A6B2A")); self.btn_tree_canopy_color.update_style()
        self.btn_tree_trunk_color.color=QColor(e.get("tree_trunk_color","#5C3A1E")); self.btn_tree_trunk_color.update_style()
        self.slider_tree_color_var.setValue(e.get("tree_color_var",15))
        self.slider_tree_density.setValue(e.get("tree_density",1))
        self.combo_terrain_type.setCurrentText(e.get("terrain_type","Grass"))
        self.btn_terrain_color.color=QColor(e.get("terrain_color","#5A8A3C")); self.btn_terrain_color.update_style()
        self.slider_terrain_roughness.setValue(e.get("terrain_roughness",30))
        self.slider_terrain_wear.setValue(e.get("terrain_wear",20))
        self.slider_terrain_rock.setValue(e.get("terrain_rock",0))
        self.slider_terrain_weed.setValue(e.get("terrain_weed",0))
        self.btn_vacant_ground_color.color=QColor(e.get("vacant_ground_color","#6B5A3E")); self.btn_vacant_ground_color.update_style()
        self.slider_vacant_debris.setValue(e.get("vacant_debris",40))
        self.slider_vacant_vegetation.setValue(e.get("vacant_vegetation",30))
        self.combo_vacant_fence.setCurrentText(e.get("vacant_fence","No Fence"))
        self.slider_vacant_puddles.setValue(e.get("vacant_puddles",0))
        self.btn_water_shallow.color=QColor(e.get("water_shallow","#5B9EC9")); self.btn_water_shallow.update_style()
        self.btn_water_deep.color=QColor(e.get("water_deep","#1A4A7A")); self.btn_water_deep.update_style()
        self.btn_water_shore.color=QColor(e.get("water_shore","#7A8C6E")); self.btn_water_shore.update_style()
        self.combo_water_shore_style.setCurrentText(e.get("water_shore_style","Grassy"))
        self.slider_water_shore_width.setValue(e.get("water_shore_width",8))
        self.combo_water_feature.setCurrentText(e.get("water_feature","None"))
        self.slider_water_turbulence.setValue(e.get("water_turbulence",20))
        self.slider_water_depth_rings.setValue(e.get("water_depth_rings",3))
        self._on_env_type_changed(e.get("env_type","Tree")); self.blockSignals(False)

    def save_and_notify(self):
        index=self.combo_box.currentIndex()
        if index<0: return
        e=self.env_types[index]
        e["env_type"]=self.combo_env_type.currentText()
        e["tree_species"]=self.combo_tree_species.currentText()
        e["tree_canopy"]=self.slider_tree_canopy.value(); e["tree_trunk"]=self.slider_tree_trunk.value()
        e["tree_canopy_color"]=self.btn_tree_canopy_color.color.name()
        e["tree_trunk_color"]=self.btn_tree_trunk_color.color.name()
        e["tree_color_var"]=self.slider_tree_color_var.value(); e["tree_density"]=self.slider_tree_density.value()
        e["terrain_type"]=self.combo_terrain_type.currentText()
        e["terrain_color"]=self.btn_terrain_color.color.name()
        e["terrain_roughness"]=self.slider_terrain_roughness.value()
        e["terrain_wear"]=self.slider_terrain_wear.value()
        e["terrain_rock"]=self.slider_terrain_rock.value(); e["terrain_weed"]=self.slider_terrain_weed.value()
        e["vacant_ground_color"]=self.btn_vacant_ground_color.color.name()
        e["vacant_debris"]=self.slider_vacant_debris.value()
        e["vacant_vegetation"]=self.slider_vacant_vegetation.value()
        e["vacant_fence"]=self.combo_vacant_fence.currentText()
        e["vacant_puddles"]=self.slider_vacant_puddles.value()
        e["water_shallow"]=self.btn_water_shallow.color.name()
        e["water_deep"]=self.btn_water_deep.color.name(); e["water_shore"]=self.btn_water_shore.color.name()
        e["water_shore_style"]=self.combo_water_shore_style.currentText()
        e["water_shore_width"]=self.slider_water_shore_width.value()
        e["water_feature"]=self.combo_water_feature.currentText()
        e["water_turbulence"]=self.slider_water_turbulence.value()
        e["water_depth_rings"]=self.slider_water_depth_rings.value()
        if hasattr(self,'main_window'): self.main_window.city_canvas.redraw_all()

    def get_current_data(self):
        idx=self.combo_box.currentIndex()
        return self.env_types[idx] if idx>=0 else None


# ── City Canvas (full draw engine, same as original) ─────────────────────────

class CityCanvas(QGraphicsView):
    def __init__(self, scene_width=2048, scene_height=2048, view_width=960, view_height=544):
        super().__init__()
        self.scene_width=scene_width; self.scene_height=scene_height; self.cell_size=128
        self.scene=QGraphicsScene(self)
        self.scene.setSceneRect(0,0,self.scene_width,self.scene_height)
        self.setScene(self.scene); self.setFixedSize(view_width,view_height)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setAlignment(Qt.AlignLeft|Qt.AlignTop)
        self.setDragMode(QGraphicsView.NoDrag)
        self.scene.setBackgroundBrush(QColor(100,150,100))
        self._panning=False; self._pan_start=QPoint()
        self.grid_lines=[]; self.grid_data={}; self.grid_items={}
        self.get_active_data_cb=None
        self.draw_guidelines()

    def set_block_size(self, new_size):
        self.cell_size=new_size; self.draw_guidelines(); self.redraw_all()

    def draw_guidelines(self):
        for line in self.grid_lines: self.scene.removeItem(line)
        self.grid_lines.clear()
        guide_pen=QPen(QColor(0,0,0,40))
        for x in range(0,self.scene_width+1,self.cell_size):
            self.grid_lines.append(self.scene.addLine(x,0,x,self.scene_height,guide_pen))
        for y in range(0,self.scene_height+1,self.cell_size):
            self.grid_lines.append(self.scene.addLine(0,y,self.scene_width,y,guide_pen))

    def place_tile(self, col, row, tile_data):
        gw=tile_data.get("grid_w",1); gh=tile_data.get("grid_h",1)
        max_c=self.scene_width//self.cell_size; max_r=self.scene_height//self.cell_size
        if col+gw>max_c or row+gh>max_r: return
        for r in range(row,row+gh):
            for c in range(col,col+gw): self.erase_tile(c,r,update_neighbors=True)
        self.grid_data[(col,row)]=tile_data
        for r in range(row,row+gh):
            for c in range(col,col+gw):
                if c==col and r==row: continue
                self.grid_data[(c,r)]={"type":"child","anchor":(col,row)}
        if tile_data["type"]=="road":
            # Draw self first so _is_road() returns True for neighbors during update_neighbors.
            # Then update neighbors so they connect to us.
            # Then redraw self so we connect back to them.
            self.draw_tile(col,row)
            self.update_neighbors(col,row)
            self.draw_tile(col,row)
        elif tile_data.get("type")=="environment" and tile_data.get("env_type")=="Water Feature":
            self.draw_tile(col,row)
            self.update_neighbors(col,row)
            self.draw_tile(col,row)
        else:
            self.draw_tile(col,row)

    def erase_tile(self, col, row, update_neighbors=True):
        if (col,row) not in self.grid_data: return
        data=self.grid_data[(col,row)]
        if data["type"]=="child": ax,ay=data["anchor"]; self.erase_tile(ax,ay,update_neighbors); return
        gw=data.get("grid_w",1); gh=data.get("grid_h",1)
        was_road=data["type"]=="road"
        was_water=data.get("type")=="environment" and data.get("env_type")=="Water Feature"
        if (col,row) in self.grid_items: self.scene.removeItem(self.grid_items[(col,row)]); del self.grid_items[(col,row)]
        for r in range(row,row+gh):
            for c in range(col,col+gw):
                if (c,r) in self.grid_data: del self.grid_data[(c,r)]
        if was_road and update_neighbors: self.update_neighbors(col,row)
        if was_water and update_neighbors: self.update_neighbors(col,row)

    def update_neighbors(self, col, row):
        for c,r in [(col,row-1),(col,row+1),(col-1,row),(col+1,row)]:
            if c>=0 and r>=0 and (c,r) in self.grid_data:
                if self.grid_data[(c,r)]["type"]=="road": self.draw_tile(c,r)

    def _is_road(self, col, row):
        return (col,row) in self.grid_data and self.grid_data[(col,row)]["type"]=="road"

    def _is_water(self, col, row):
        d=self.grid_data.get((col,row))
        return d is not None and d.get("type")=="environment" and d.get("env_type")=="Water Feature"

    def _make_rounded_rect(self, x, y, w, h, r):
        path=QPainterPath(); path.addRoundedRect(x,y,w,h,r,r); return path

    def redraw_all(self):
        for (col,row) in list(self.grid_items.keys()): self.draw_tile(col,row)

    def _get_material_brush(self, mat_data, width, height, seed):
        mat_type=mat_data.get("type","Solid Color"); params=mat_data.get("params",{})
        weather_dirt=params.get("weather_dirt",0); weather_stain=params.get("weather_stain",0)
        has_weathering=(weather_dirt>0 or weather_stain>0)
        if mat_type=="Solid Color":
            if not has_weathering: return QBrush(QColor(params.get("color","#888888")))
            p=params.copy(); p['seed']=seed
            ck=f"solid_w_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            def _make():
                img=Image.new('RGB',(width,height),params.get("color","#888888"))
                return pil_to_qimage(apply_weathering(img,p))
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,_make)))
        elif mat_type=="Custom Texture":
            if params.get("texture_image"): return QBrush(QPixmap.fromImage(params["texture_image"]))
            return QBrush(QColor("#888888"))
        elif mat_type=="Brick":
            p=params.copy(); p['seed']=seed
            ck=f"brick_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            def _make():
                iq=generate_brick_pattern(width,height,p)
                if has_weathering:
                    pil=Image.frombytes('RGB',(width,height),iq.bits().tobytes())
                    return pil_to_qimage(apply_weathering(pil,p))
                return iq
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,_make)))
        elif mat_type=="Tile":
            p=params.copy(); p['seed']=seed
            ck=f"tile_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            def _make():
                iq=generate_tile_pattern(width,height,p)
                if has_weathering:
                    pil=Image.frombytes('RGB',(width,height),iq.bits().tobytes())
                    return pil_to_qimage(apply_weathering(pil,p))
                return iq
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,_make)))
        elif mat_type=="Concrete":
            p=params.copy(); p['seed']=seed
            ck=f"concrete_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            def _make():
                iq=generate_concrete_pattern(width,height,p)
                if has_weathering:
                    pil=Image.frombytes('RGB',(width,height),iq.bits().tobytes())
                    return pil_to_qimage(apply_weathering(pil,p))
                return iq
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,_make)))
        return QBrush(QColor("#888888"))

    def _get_road_material_brush(self, mat_data, width, height, seed):
        mat_type=mat_data.get("type","Solid Color"); params=mat_data.get("params",{})
        if mat_type=="Solid Color": return QBrush(QColor(params.get("color","#333333")))
        elif mat_type=="Custom Texture":
            if params.get("texture_image"): return QBrush(QPixmap.fromImage(params["texture_image"]))
            return QBrush(QColor("#333333"))
        elif mat_type=="Asphalt":
            p=params.copy(); p['seed']=seed
            ck=f"asphalt_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_asphalt_pattern(width,height,p))))
        elif mat_type=="Concrete":
            p=params.copy(); p['seed']=seed
            ck=f"road_concrete_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_concrete_pattern(width,height,p))))
        elif mat_type=="Cobblestone":
            p=params.copy(); p['seed']=seed
            ck=f"cobble_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_cobblestone_pattern(width,height,p))))
        elif mat_type=="Dirt":
            p=params.copy(); p['seed']=seed
            ck=f"dirt_{width}_{height}_{hashlib.md5(str(p).encode()).hexdigest()}"
            return QBrush(QPixmap.fromImage(pattern_cache.get_or_create(ck,lambda:generate_dirt_pattern(width,height,p))))
        return QBrush(QColor("#333333"))

    def draw_tile(self, col, row):
        if (col,row) in self.grid_items:
            self.scene.removeItem(self.grid_items[(col,row)]); del self.grid_items[(col,row)]
        data=self.grid_data.get((col,row))
        if not data or data["type"]=="child": return
        # Delegate to the original drawing logic (imported verbatim from city tool)
        self._draw_tile_impl(col, row, data)

    def _draw_tile_impl(self, col, row, data):
        """Full tile drawing — exact copy of the original draw_tile body."""
        group=QGraphicsItemGroup()
        s=self.cell_size; x,y=col*s, row*s

        if data["type"]=="building":
            random.seed(f"{col}_{row}_{data['name']}")
            scale=s/128.0; gw,gh=data.get("grid_w",1),data.get("grid_h",1)
            total_w,total_h=gw*s,gh*s
            w=(data.get("width",80)/100.0)*total_w; h=(data.get("depth",80)/100.0)*total_h
            b_height=data.get("height",60)*scale; edge=data.get("edge",0)*scale
            sun_ang=math.radians(self.window().sun_angle if hasattr(self.window(),'sun_angle') else 45)
            sh_x=math.cos(sun_ang)*(b_height*0.5); sh_y=math.sin(sun_ang)*(b_height*0.5)
            bx,by=x+(total_w-w)/2, y+(total_h-h)/2
            shadow=self.scene.addPath(self._make_rounded_rect(bx+sh_x,by+sh_y,w,h,edge))
            shadow.setBrush(QColor(0,0,0,80)); shadow.setPen(Qt.NoPen); group.addToGroup(shadow)
            current_w,current_h=w,h; current_bx,current_by=bx,by; current_y_floor=by
            tiers=data.get("tiers",1); shrink=data.get("shrink",85)/100.0
            win_color=QColor(data.get("win_color","#FFD700"))
            wall_mat_data=data.get("wall_material",{"type":"Solid Color","params":{"color":"#444444"}})
            roof_mat_data=data.get("roof_material",{"type":"Solid Color","params":{"color":"#777777"}})
            pseed=hash(f"{col}_{row}")%10000
            wall_brush=self._get_material_brush(wall_mat_data,int(w),int(h),pseed)
            roof_brush=self._get_material_brush(roof_mat_data,int(w),int(h),pseed+1)
            dark_win=QColor("#222222")
            for t in range(tiers):
                p1=QPainterPath(); p1.addRoundedRect(current_bx,current_y_floor,current_w,current_h,edge,edge)
                p2=QPainterPath(); p2.addRoundedRect(current_bx,current_y_floor-b_height,current_w,current_h,edge,edge)
                p3=QPainterPath(); p3.addRect(current_bx,current_y_floor-b_height+edge,current_w,b_height+current_h-2*edge)
                wall=self.scene.addPath(p1.united(p2).united(p3))
                wall.setBrush(wall_brush); wall.setPen(QPen(QColor(30,30,30),max(1,int(1*scale)))); group.addToGroup(wall)
                base=self.scene.addPath(self._make_rounded_rect(current_bx,current_y_floor-b_height,current_w,current_h,edge))
                darker_wall=QBrush(wall_brush.color().darker(120)) if wall_brush.style()==Qt.SolidPattern else wall_brush
                base.setBrush(darker_wall); base.setPen(QPen(QColor(30,30,30))); group.addToGroup(base)
                cols_w,rows_w=data.get("win_cols",0),data.get("win_rows",0)
                if cols_w>0 and rows_w>0:
                    wall_top_y=current_y_floor-b_height+current_h; wall_x=current_bx; wall_w=current_w; wall_h=b_height
                    gutter_x=max(2.0,wall_w*0.06); gutter_y=max(2.0,wall_h*0.12)
                    win_w=(wall_w-gutter_x*(cols_w+1))/cols_w; win_h=(wall_h-gutter_y*(rows_w+1))/rows_w
                    if win_w>1 and win_h>1:
                        for wr in range(rows_w):
                            for wc in range(cols_w):
                                wx=wall_x+gutter_x+wc*(win_w+gutter_x); wy=wall_top_y+gutter_y+wr*(win_h+gutter_y)
                                win=self.scene.addRect(wx,wy,win_w,win_h)
                                is_lit=random.randint(0,100)<data.get("win_lit",30)
                                win.setBrush(win_color if is_lit else dark_win); win.setPen(QPen(QColor(20,20,20)))
                                group.addToGroup(win)
                if t==0 and data.get("sign","None")!="None":
                    sign_w_px=10*scale; sign_h_px=b_height*0.7
                    if "Left" in data["sign"]:
                        sign=self.scene.addRect(current_bx-sign_w_px,current_y_floor-b_height+(b_height*0.1),sign_w_px,sign_h_px)
                    else:
                        sign=self.scene.addRect(current_bx+current_w,current_y_floor-b_height+(b_height*0.1),sign_w_px,sign_h_px)
                    sign.setBrush(QColor(200,50,50) if "Neon" in data["sign"] else QColor(50,50,200))
                    sign.setPen(QPen(QColor(20,20,20))); group.addToGroup(sign)
                current_y_floor-=b_height; new_w=current_w*shrink; new_h=current_h*shrink
                current_bx+=(current_w-new_w)/2; current_by+=(current_h-new_h)/2
                current_w,current_h=new_w,new_h
            inset=data.get("inset",5)*scale
            if current_w>inset*2 and current_h>inset*2:
                if data.get("roof","Flat")=="Pitched":
                    poly=QPainterPath()
                    poly.moveTo(current_bx,current_y_floor+current_h)
                    poly.lineTo(current_bx+current_w/2,current_y_floor-(b_height*0.5))
                    poly.lineTo(current_bx+current_w,current_y_floor+current_h); poly.closeSubpath()
                    roof=self.scene.addPath(poly); roof.setBrush(roof_brush); roof.setPen(QPen(QColor(30,30,30)))
                    group.addToGroup(roof)
                else:
                    roof=self.scene.addPath(self._make_rounded_rect(current_bx+inset,current_y_floor+inset,current_w-inset*2,current_h-inset*2,max(0,edge-inset)))
                    roof.setBrush(roof_brush); roof.setPen(QPen(QColor(30,30,30))); group.addToGroup(roof)
                    greebles=data.get("greebles",0)
                    for _ in range(greebles):
                        gw_px=random.uniform(4*scale,12*scale); gh_px=random.uniform(4*scale,12*scale)
                        gx=random.uniform(current_bx+inset+2,current_bx+current_w-inset-gw_px-2)
                        gy=random.uniform(current_y_floor+inset+2,current_y_floor+current_h-inset-gh_px-2)
                        gb=self.scene.addRect(gx,gy,gw_px,gh_px)
                        gb.setBrush(QColor(random.choice(["#333333","#555555","#888888"])))
                        gb.setPen(QPen(QColor(20,20,20))); group.addToGroup(gb)
            group.setZValue(row+data.get("grid_h",1))

        elif data["type"]=="road":
            elevation=data.get("elevation",0); y_offset=elevation*(s*0.3)
            n=self._is_road(col,row-1); so=self._is_road(col,row+1)
            e=self._is_road(col+1,row); w_side=self._is_road(col-1,row)
            neighbors=[n,so,e,w_side]; neighbor_count=sum(neighbors)
            is_corner=neighbor_count==2 and ((n and e) or (n and w_side) or (so and e) or (so and w_side))
            if elevation>0:
                pillar_style=data.get("pillars","Concrete Pillars")
                pillar_color={"Concrete Pillars":QColor("#888888"),"Steel Pillars":QColor("#606060"),"Brick Pillars":QColor("#8B4513")}.get(pillar_style,QColor("#888888"))
                pillar_w=max(s*0.08,4)
                for px2,py2 in [(x+s*0.2,y+s*0.2),(x+s*0.8-pillar_w,y+s*0.2),(x+s*0.2,y+s*0.8-pillar_w),(x+s*0.8-pillar_w,y+s*0.8-pillar_w)]:
                    pillar=self.scene.addRect(px2,py2,pillar_w,y_offset); pillar.setBrush(pillar_color); pillar.setPen(QPen(QColor(40,40,40))); group.addToGroup(pillar)
            if elevation>0:
                shadow=self.scene.addRect(x,y,s,s); shadow.setBrush(QColor(0,0,0,60+elevation*20)); shadow.setPen(Qt.NoPen); group.addToGroup(shadow)
            road_y=y-y_offset
            pseed=hash(f"{col}_{row}")%10000
            mat_data=data.get("surface_material",{"type":"Solid Color","params":{"color":"#333333"}})
            surface_brush=self._get_road_material_brush(mat_data,int(s),int(s),pseed)
            def _road_width_for(td):
                wt=td.get("width_type","Street (2-lane)")
                if "Alley" in wt: return s*0.4
                elif "Highway" in wt: return s*0.95
                return s*0.7
            road_width=_road_width_for(data); road_offset=(s-road_width)/2
            def _neighbor_offset(nc,nr):
                nd=self.grid_data.get((nc,nr))
                if nd and nd.get("type")=="road":
                    nw=_road_width_for(nd); blended=min(road_width,nw); return (s-blended)/2
                return road_offset
            off_n=_neighbor_offset(col,row-1) if n else road_offset
            off_s=_neighbor_offset(col,row+1) if so else road_offset
            off_e=_neighbor_offset(col+1,row) if e else road_offset
            off_w=_neighbor_offset(col-1,row) if w_side else road_offset
            def build_road_path(offset, width):
                path=QPainterPath(); r_in=offset; r_out=offset+width; tp=0.25
                if is_corner:
                    if n and e:
                        path.moveTo(x+r_in,road_y); path.arcTo(x+s-r_out,road_y-r_out,2*r_out,2*r_out,180,90)
                        path.lineTo(x+s,road_y+r_in); path.arcTo(x+s-r_in,road_y-r_in,2*r_in,2*r_in,270,-90); path.closeSubpath()
                    elif n and w_side:
                        path.moveTo(x+r_out,road_y); path.arcTo(x-r_out,road_y-r_out,2*r_out,2*r_out,0,-90)
                        path.lineTo(x,road_y+r_in); path.arcTo(x-r_in,road_y-r_in,2*r_in,2*r_in,270,90); path.closeSubpath()
                    elif so and e:
                        path.moveTo(x+s,road_y+s-r_out); path.arcTo(x+s-r_out,road_y+s-r_out,2*r_out,2*r_out,90,90)
                        path.lineTo(x+r_out,road_y+s); path.arcTo(x+s-r_in,road_y+s-r_in,2*r_in,2*r_in,180,-90); path.closeSubpath()
                    elif so and w_side:
                        path.moveTo(x,road_y+s-r_out); path.arcTo(x-r_out,road_y+s-r_out,2*r_out,2*r_out,90,-90)
                        path.lineTo(x+r_in,road_y+s); path.arcTo(x-r_in,road_y+s-r_in,2*r_in,2*r_in,0,90); path.closeSubpath()
                else:
                    if neighbor_count==0:
                        path.addRect(x+offset,road_y,width,s)
                    elif (n or so) and not (e or w_side):
                        n_taper_y=road_y+s*tp; s_taper_y=road_y+s*(1-tp)
                        path.addRect(x+offset,n_taper_y if n else road_y,width,(s_taper_y if so else road_y+s)-(n_taper_y if n else road_y))
                        if n:
                            p2=QPainterPath(); p2.moveTo(x+off_n,road_y); p2.lineTo(x+s-off_n,road_y); p2.lineTo(x+s-offset,n_taper_y); p2.lineTo(x+offset,n_taper_y); p2.closeSubpath(); path=path.united(p2)
                        if so:
                            p2=QPainterPath(); p2.moveTo(x+offset,s_taper_y); p2.lineTo(x+s-offset,s_taper_y); p2.lineTo(x+s-off_s,road_y+s); p2.lineTo(x+off_s,road_y+s); p2.closeSubpath(); path=path.united(p2)
                    elif (e or w_side) and not (n or so):
                        w_taper_x=x+s*tp; e_taper_x=x+s*(1-tp)
                        path.addRect(w_taper_x if w_side else x,road_y+offset,(e_taper_x if e else x+s)-(w_taper_x if w_side else x),width)
                        if w_side:
                            p2=QPainterPath(); p2.moveTo(x,road_y+off_w); p2.lineTo(x,road_y+s-off_w); p2.lineTo(w_taper_x,road_y+s-offset); p2.lineTo(w_taper_x,road_y+offset); p2.closeSubpath(); path=path.united(p2)
                        if e:
                            p2=QPainterPath(); p2.moveTo(e_taper_x,road_y+offset); p2.lineTo(e_taper_x,road_y+s-offset); p2.lineTo(x+s,road_y+s-off_e); p2.lineTo(x+s,road_y+off_e); p2.closeSubpath(); path=path.united(p2)
                    else:
                        cx_l=x+offset; cx_r=x+s-offset; cy_t=road_y+offset; cy_b=road_y+s-offset
                        path.addRect(cx_l,cy_t,width,width)
                        if n:
                            n_taper_y=road_y+s*tp
                            p2=QPainterPath(); p2.moveTo(x+off_n,road_y); p2.lineTo(x+s-off_n,road_y); p2.lineTo(cx_r,n_taper_y); p2.lineTo(cx_l,n_taper_y); p2.closeSubpath()
                            path=path.united(p2)
                        if so:
                            s_taper_y=road_y+s*(1-tp)
                            p2=QPainterPath(); p2.moveTo(cx_l,s_taper_y); p2.lineTo(cx_r,s_taper_y); p2.lineTo(x+s-off_s,road_y+s); p2.lineTo(x+off_s,road_y+s); p2.closeSubpath()
                            path=path.united(p2)
                        if e:
                            e_taper_x=x+s*(1-tp)
                            p2=QPainterPath(); p2.moveTo(e_taper_x,cy_t); p2.lineTo(e_taper_x,cy_b); p2.lineTo(x+s,road_y+s-off_e); p2.lineTo(x+s,road_y+off_e); p2.closeSubpath()
                            path=path.united(p2)
                        if w_side:
                            w_taper_x=x+s*tp
                            p2=QPainterPath(); p2.moveTo(x,road_y+off_w); p2.lineTo(x,road_y+s-off_w); p2.lineTo(w_taper_x,cy_b); p2.lineTo(w_taper_x,cy_t); p2.closeSubpath()
                            path=path.united(p2)
                        path=path.simplified()
                return path
            if data.get("sidewalks","No Sidewalks")=="With Sidewalks":
                sw_w=data.get("sidewalk_width",10)*(s/128); sw_col=QColor(data.get("sidewalk_color","#8A8A8A"))
                sw_offset=max(0,road_offset-sw_w); sw_width=min(s,road_width+2*sw_w)
                if sw_offset==0: sw_width=s
                sw_surf=self.scene.addPath(build_road_path(sw_offset,sw_width))
                sw_surf.setBrush(sw_col); sw_surf.setPen(Qt.NoPen); group.addToGroup(sw_surf)
            road_surface=self.scene.addPath(build_road_path(road_offset,road_width))
            road_surface.setBrush(surface_brush); road_surface.setPen(Qt.NoPen); group.addToGroup(road_surface)
            centerline=data.get("centerline","None")
            if centerline!="None":
                line_color=QColor(data.get("line_color","#FFD700")); line_pen=QPen(line_color,max(2,s//40))
                if "Dashed" in centerline: line_pen.setStyle(Qt.DashLine)
                def add_line(x1,y1,x2,y2):
                    if "Double" in centerline:
                        off=max(2,s//50)
                        if x1==x2:
                            group.addToGroup(self.scene.addLine(x1-off,y1,x2-off,y2,line_pen))
                            group.addToGroup(self.scene.addLine(x1+off,y1,x2+off,y2,line_pen))
                        else:
                            group.addToGroup(self.scene.addLine(x1,y1-off,x2,y2-off,line_pen))
                            group.addToGroup(self.scene.addLine(x1,y1+off,x2,y2+off,line_pen))
                    else: group.addToGroup(self.scene.addLine(x1,y1,x2,y2,line_pen))
                rc=s/2; cx2,cy2=x+rc,road_y+rc
                if is_corner:
                    if "Double" in centerline: line_pen.setWidth(max(1,s//20))
                    lp=QPainterPath()
                    if n and e: lp.arcMoveTo(x+rc,road_y-rc,s,s,180); lp.arcTo(x+rc,road_y-rc,s,s,180,90)
                    elif n and w_side: lp.arcMoveTo(x-rc,road_y-rc,s,s,0); lp.arcTo(x-rc,road_y-rc,s,s,0,-90)
                    elif so and e: lp.arcMoveTo(x+rc,road_y+rc,s,s,180); lp.arcTo(x+rc,road_y+rc,s,s,180,-90)
                    elif so and w_side: lp.arcMoveTo(x-rc,road_y+rc,s,s,0); lp.arcTo(x-rc,road_y+rc,s,s,0,90)
                    group.addToGroup(self.scene.addPath(lp,line_pen))
                else:
                    if (n or so) and not (e or w_side): add_line(cx2,road_y,cx2,road_y+s)
                    elif (e or w_side) and not (n or so): add_line(x,cy2,x+s,cy2)
                    else:
                        if n: add_line(cx2,road_y,cx2,cy2)
                        if so: add_line(cx2,cy2,cx2,road_y+s)
                        if e: add_line(cx2,cy2,x+s,cy2)
                        if w_side: add_line(x,cy2,cx2,cy2)
                        if neighbor_count==0: add_line(cx2,road_y,cx2,road_y+s)
            if data.get("crosswalks","No Crosswalks")=="Crosswalks at Intersections" and neighbor_count>=3:
                cwpen=QPen(QColor(255,255,255),max(2,s//50)); ssp=s//20
                if n:
                    for i in range(0,int(road_width),ssp): group.addToGroup(self.scene.addLine(x+road_offset+i,road_y,x+road_offset+i,road_y+ssp*2,cwpen))
                if so:
                    for i in range(0,int(road_width),ssp): group.addToGroup(self.scene.addLine(x+road_offset+i,road_y+s-ssp*2,x+road_offset+i,road_y+s,cwpen))
                if e:
                    for i in range(0,int(road_width),ssp): group.addToGroup(self.scene.addLine(x+s-ssp*2,road_y+road_offset+i,x+s,road_y+road_offset+i,cwpen))
                if w_side:
                    for i in range(0,int(road_width),ssp): group.addToGroup(self.scene.addLine(x,road_y+road_offset+i,x+ssp*2,road_y+road_offset+i,cwpen))
            if data.get("parking","No Parking Spaces")=="Parking Spaces" and not is_corner and neighbor_count<3:
                ppen=QPen(QColor(200,200,200),max(1,s//80)); pw=s//6; ph2=s//3
                if (n or so) and not (e or w_side):
                    for i in range(3):
                        py2=road_y+i*(s//3)
                        group.addToGroup(self.scene.addRect(x+road_offset,py2,pw,ph2,ppen))
                        group.addToGroup(self.scene.addRect(x+road_offset+road_width-pw,py2,pw,ph2,ppen))
                elif (e or w_side) and not (n or so):
                    for i in range(3):
                        px2=x+i*(s//3)
                        group.addToGroup(self.scene.addRect(px2,road_y+road_offset,ph2,pw,ppen))
                        group.addToGroup(self.scene.addRect(px2,road_y+road_offset+road_width-pw,ph2,pw,ppen))
            mhd=data.get("manholes",0)
            if mhd>0 and random.random()<mhd/10:
                mhsz=s//10; mx2=x+s/2+random.randint(-int(s//4),int(s//4)); my2=road_y+s/2+random.randint(-int(s//4),int(s//4))
                mh=self.scene.addEllipse(mx2-mhsz/2,my2-mhsz/2,mhsz,mhsz)
                mh.setBrush(QColor(60,60,60)); mh.setPen(QPen(QColor(40,40,40))); group.addToGroup(mh)
            lights=data.get("lights","No Lights")
            if lights=="Corners Only" and neighbor_count>=3:
                c_off=max(s//10,road_offset)
                for lx2,ly2 in [(x+c_off,road_y+c_off),(x+s-c_off,road_y+c_off),(x+c_off,road_y+s-c_off),(x+s-c_off,road_y+s-c_off)]:
                    pole=self.scene.addRect(lx2,ly2,s//40,s//5); pole.setBrush(QColor(80,80,80)); pole.setPen(Qt.NoPen); group.addToGroup(pole)
                    light=self.scene.addEllipse(lx2-s//20,ly2-s//20,s//10,s//10); light.setBrush(QColor(255,255,200,180)); light.setPen(Qt.NoPen); group.addToGroup(light)
            if elevation>0 and data.get("railings","No Railings")=="With Railings":
                rpen=QPen(QColor(100,100,100),max(2,s//60))
                if not is_corner and neighbor_count<3:
                    if (n or so) and not (e or w_side):
                        group.addToGroup(self.scene.addLine(x+road_offset,road_y,x+road_offset,road_y+s,rpen))
                        group.addToGroup(self.scene.addLine(x+road_offset+road_width,road_y,x+road_offset+road_width,road_y+s,rpen))
                    elif (e or w_side) and not (n or so):
                        group.addToGroup(self.scene.addLine(x,road_y+road_offset,x+s,road_y+road_offset,rpen))
                        group.addToGroup(self.scene.addLine(x,road_y+road_offset+road_width,x+s,road_y+road_offset+road_width,rpen))
            group.setZValue(-10+elevation*100)

        elif data["type"]=="environment":
            random.seed(f"env_{col}_{row}_{data.get('name','')}")
            env_type=data.get("env_type","Tree"); scale=s/128.0
            if env_type=="Tree":
                species=data.get("tree_species","Deciduous"); canopy_pct=data.get("tree_canopy",65)/100.0
                trunk_w_base=data.get("tree_trunk",12)*scale; c_col=QColor(data.get("tree_canopy_color","#3A6B2A"))
                t_col=QColor(data.get("tree_trunk_color","#5C3A1E")); color_var=data.get("tree_color_var",15)
                density=data.get("tree_density",1)
                ground=self.scene.addRect(x,y,s,s); ground.setBrush(QColor(80,110,60,60)); ground.setPen(Qt.NoPen); group.addToGroup(ground)
                positions=[]
                if density==1: positions=[(0.5,0.6)]
                elif density==2: positions=[(0.3,0.55),(0.7,0.6)]
                elif density==3: positions=[(0.2,0.6),(0.5,0.5),(0.8,0.6)]
                elif density==4: positions=[(0.25,0.55),(0.75,0.55),(0.2,0.75),(0.8,0.75)]
                else: positions=[(0.2,0.55),(0.5,0.45),(0.8,0.55),(0.3,0.75),(0.7,0.75)]
                for px_pct,py_pct in positions:
                    tx2=x+px_pct*s; ty2=y+py_pct*s; canopy_r=(s*canopy_pct*0.5)*random.uniform(0.85,1.15)
                    tw=trunk_w_base*random.uniform(0.8,1.2); trunk_h=max(canopy_r*0.30,tw*2.5); trunk_top_y=ty2-trunk_h
                    vr=random.randint(-color_var,color_var)
                    cr2=max(0,min(255,c_col.red()+vr)); cg2=max(0,min(255,c_col.green()+vr)); cb2=max(0,min(255,c_col.blue()+vr))
                    varied_canopy=QColor(cr2,cg2,cb2)
                    if species=="Dead":
                        tr=self.scene.addRect(tx2-tw/2,trunk_top_y,tw,trunk_h); tr.setBrush(t_col); tr.setPen(Qt.NoPen); group.addToGroup(tr)
                        bpen=QPen(t_col,max(1,int(tw*0.4))); bory=trunk_top_y+trunk_h*0.3
                        for ang_deg in [-50,-20,20,50]:
                            ang=math.radians(ang_deg); bl=canopy_r*random.uniform(0.45,0.75)
                            bx2=tx2+math.sin(ang)*bl; by2=bory-math.cos(ang)*bl*0.5
                            group.addToGroup(self.scene.addLine(tx2,bory,bx2,by2,bpen))
                    elif species=="Pine":
                        stub_h=trunk_h*0.25
                        tr=self.scene.addRect(tx2-tw/2,trunk_top_y+trunk_h-stub_h,tw,stub_h); tr.setBrush(t_col); tr.setPen(Qt.NoPen); group.addToGroup(tr)
                        tier_total=trunk_h*0.85
                        for tier in range(3):
                            frac=1.0-tier*0.28; tr_w=canopy_r*frac
                            tier_top_y=trunk_top_y+tier_total*(1.0-(tier+1)/3.0); tier_bot_y=trunk_top_y+tier_total*(1.0-tier/3.0)
                            tri=QPainterPath(); tri.moveTo(tx2,tier_top_y); tri.lineTo(tx2-tr_w,tier_bot_y); tri.lineTo(tx2+tr_w,tier_bot_y); tri.closeSubpath()
                            ti=self.scene.addPath(tri); ti.setBrush(varied_canopy); ti.setPen(Qt.NoPen); group.addToGroup(ti)
                    elif species=="Palm":
                        lean=random.uniform(-0.06,0.06)*s
                        tp2=QPainterPath(); tp2.moveTo(tx2-tw/2,ty2); tp2.lineTo(tx2+tw/2,ty2); tp2.lineTo(tx2+tw/4+lean,trunk_top_y); tp2.lineTo(tx2-tw/4+lean,trunk_top_y); tp2.closeSubpath()
                        ti=self.scene.addPath(tp2); ti.setBrush(t_col); ti.setPen(Qt.NoPen); group.addToGroup(ti)
                        fpen=QPen(varied_canopy,max(2,int(tw*0.5))); top_x=tx2+lean; top_y=trunk_top_y
                        for ang_deg in [-70,-40,-10,20,50,80]:
                            ang=math.radians(ang_deg-90); fl=canopy_r*random.uniform(0.7,1.0)
                            fx=top_x+math.cos(ang)*fl; fy=top_y+math.sin(ang)*fl
                            group.addToGroup(self.scene.addLine(top_x,top_y,fx,fy,fpen))
                    elif species=="Shrub":
                        stub_h=min(trunk_h*0.4,tw*1.5)
                        tr=self.scene.addRect(tx2-tw*0.4,trunk_top_y+trunk_h-stub_h,tw*0.8,stub_h); tr.setBrush(t_col); tr.setPen(Qt.NoPen); group.addToGroup(tr)
                        lobe_cy=trunk_top_y+trunk_h*0.35
                        for lobe in range(4):
                            la=math.radians(lobe*90+random.randint(-20,20)); lr=canopy_r*random.uniform(0.40,0.60)
                            lx2=tx2+math.cos(la)*canopy_r*0.22; ly2=lobe_cy+math.sin(la)*canopy_r*0.22
                            li=self.scene.addEllipse(lx2-lr,ly2-lr,lr*2,lr*2); li.setBrush(varied_canopy); li.setPen(Qt.NoPen); group.addToGroup(li)
                    else:
                        sh=self.scene.addEllipse(tx2-canopy_r*0.85,ty2-canopy_r*0.25,canopy_r*1.7,canopy_r*0.5)
                        sh.setBrush(QColor(0,0,0,40)); sh.setPen(Qt.NoPen); group.addToGroup(sh)
                        tr=self.scene.addRect(tx2-tw/2,trunk_top_y,tw,trunk_h); tr.setBrush(t_col); tr.setPen(Qt.NoPen); group.addToGroup(tr)
                        can=self.scene.addEllipse(tx2-canopy_r,trunk_top_y-canopy_r*0.75-canopy_r,canopy_r*2,canopy_r*2)
                        can.setBrush(varied_canopy); can.setPen(Qt.NoPen); group.addToGroup(can)
                        hi_col=QColor(min(255,cr2+20),min(255,cg2+25),min(255,cb2+10),120)
                        hi=self.scene.addEllipse(tx2-canopy_r*0.55,trunk_top_y-canopy_r*0.75-canopy_r*0.55,canopy_r*0.85,canopy_r*0.75)
                        hi.setBrush(hi_col); hi.setPen(Qt.NoPen); group.addToGroup(hi)
                group.setZValue(row+0.5)

            elif env_type=="Terrain Patch":
                base_col=QColor(data.get("terrain_color","#5A8A3C")); roughness=data.get("terrain_roughness",30)
                wear=data.get("terrain_wear",20); rocks=data.get("terrain_rock",0); weeds=data.get("terrain_weed",0)
                scale2=s/128.0
                base=self.scene.addRect(x,y,s,s); base.setBrush(base_col); base.setPen(Qt.NoPen); group.addToGroup(base)
                p={"dirt_color":base_col.name(),"roughness":roughness,"rocks":rocks,"seed":hash(f"{col}_{row}")%10000}
                ck=f"terrain_{s}_{hashlib.md5(str(p).encode()).hexdigest()}"
                qimg=pattern_cache.get_or_create(ck,lambda:generate_dirt_pattern(int(s),int(s),p))
                tex=self.scene.addRect(x,y,s,s); tex.setBrush(QBrush(QPixmap.fromImage(qimg))); tex.setPen(Qt.NoPen); group.addToGroup(tex)
                if wear>0:
                    for _ in range(int(wear/15)):
                        px3=x+random.uniform(0.1,0.85)*s; py3=y+random.uniform(0.1,0.85)*s
                        pr=random.uniform(s*0.06,s*0.18); wc=base_col.lighter(130+random.randint(0,30)); wc.setAlpha(160)
                        patch=self.scene.addEllipse(px3-pr,py3-pr,pr*2,pr*2); patch.setBrush(wc); patch.setPen(Qt.NoPen); group.addToGroup(patch)
                if weeds>0:
                    wpen=QPen(QColor(60,110,40),max(1,int(scale2)))
                    for _ in range(int((s*s/800)*(weeds/60))):
                        wx3=x+random.uniform(0.05,0.95)*s; wy3=y+random.uniform(0.05,0.95)*s; wh=random.uniform(scale2*3,scale2*8)
                        group.addToGroup(self.scene.addLine(wx3,wy3,wx3+random.uniform(-2,2)*scale2,wy3-wh,wpen))
                group.setZValue(-5)

            elif env_type=="Vacant Lot":
                ground_col=QColor(data.get("vacant_ground_color","#6B5A3E"))
                debris_amt=data.get("vacant_debris",40); veg_amt=data.get("vacant_vegetation",30)
                fence_style=data.get("vacant_fence","No Fence"); puddles_amt=data.get("vacant_puddles",0)
                scale2=s/128.0
                p={"dirt_color":ground_col.name(),"roughness":45,"rocks":min(60,debris_amt//2),"seed":hash(f"vac_{col}_{row}")%10000}
                ck=f"vacant_{s}_{hashlib.md5(str(p).encode()).hexdigest()}"
                qimg=pattern_cache.get_or_create(ck,lambda:generate_dirt_pattern(int(s),int(s),p))
                base=self.scene.addRect(x,y,s,s); base.setBrush(QBrush(QPixmap.fromImage(qimg))); base.setPen(Qt.NoPen); group.addToGroup(base)
                if puddles_amt>0:
                    for _ in range(max(1,puddles_amt//20)):
                        pudx=x+random.uniform(0.1,0.8)*s; pudy=y+random.uniform(0.1,0.8)*s
                        pw=random.uniform(s*0.08,s*0.2); ph2=pw*random.uniform(0.4,0.7)
                        pud=self.scene.addEllipse(pudx,pudy,pw,ph2); pud.setBrush(QColor(60,80,110,160)); pud.setPen(Qt.NoPen); group.addToGroup(pud)
                if debris_amt>0:
                    dcols=[QColor(80,80,80),QColor(100,85,60),QColor(60,60,55),QColor(120,100,70)]
                    for _ in range(int((s*s/1200)*(debris_amt/100))):
                        dx2=x+random.uniform(0.05,0.92)*s; dy2=y+random.uniform(0.05,0.92)*s
                        dw=random.uniform(scale2*2,scale2*7); dh=random.uniform(scale2*1,scale2*4)
                        deb=self.scene.addRect(dx2,dy2,dw,dh); deb.setBrush(random.choice(dcols)); deb.setPen(Qt.NoPen); group.addToGroup(deb)
                if veg_amt>0:
                    for _ in range(int((s*s/600)*(veg_amt/100))):
                        vx2=x+random.uniform(0.05,0.95)*s; vy2=y+random.uniform(0.05,0.95)*s
                        if random.random()<0.6:
                            vg=random.randint(80,130); wpen=QPen(QColor(40,vg,30),max(1,int(scale2))); wh=random.uniform(scale2*4,scale2*10)
                            group.addToGroup(self.scene.addLine(vx2,vy2,vx2+random.uniform(-3,3)*scale2,vy2-wh,wpen))
                        else:
                            sr=random.uniform(scale2*2,scale2*5); sc=self.scene.addEllipse(vx2-sr,vy2-sr,sr*2,sr*2)
                            sc.setBrush(QColor(50,random.randint(90,130),35,200)); sc.setPen(Qt.NoPen); group.addToGroup(sc)
                if fence_style!="No Fence":
                    margin=max(2,int(s*0.04))
                    if fence_style=="Chain Link": fpen=QPen(QColor(140,140,130),max(1,int(s/128.0))); fpen.setStyle(Qt.DashLine)
                    elif fence_style=="Wooden": fpen=QPen(QColor(100,70,40),max(2,int(s/128.0*1.5)))
                    else: fpen=QPen(QColor(90,65,35),max(1,int(s/128.0))); fpen.setStyle(Qt.DotLine)
                    fx1,fy1=x+margin,y+margin; fx2,fy2=x+s-margin,y+s-margin
                    for seg in [(fx1,fy1,fx2,fy1),(fx2,fy1,fx2,fy2),(fx2,fy2,fx1,fy2),(fx1,fy2,fx1,fy1)]:
                        if fence_style=="Collapsed" and random.random()<0.4: continue
                        group.addToGroup(self.scene.addLine(*seg,fpen))
                    if fence_style in ("Chain Link","Wooden"):
                        ppost=QPen(QColor(80,60,35),max(2,int(s/128.0*2))); pspc=s//3
                        for px4 in range(int(fx1),int(fx2),pspc):
                            group.addToGroup(self.scene.addLine(px4,fy1,px4,fy1-s/128.0*2,ppost))
                            group.addToGroup(self.scene.addLine(px4,fy2,px4,fy2+s/128.0*2,ppost))
                group.setZValue(-5)

            elif env_type=="Water Feature":
                random.seed(f"water_{col}_{row}")
                shallow_col=QColor(data.get("water_shallow","#5B9EC9")); deep_col=QColor(data.get("water_deep","#1A4A7A"))
                shore_col=QColor(data.get("water_shore","#7A8C6E")); shore_style=data.get("water_shore_style","Grassy")
                shore_w=data.get("water_shore_width",8)*scale; feature=data.get("water_feature","None")
                turbulence=data.get("water_turbulence",20); depth_rings=data.get("water_depth_rings",3)
                if shore_style=="Stone": shore_col=QColor(130,120,110)
                elif shore_style=="Dirt": shore_col=QColor(110,85,55)
                elif shore_style=="Concrete": shore_col=QColor(160,155,148)
                wn=self._is_water(col,row-1); ws=self._is_water(col,row+1)
                we=self._is_water(col+1,row); ww=self._is_water(col-1,row)
                wneighbors=[wn,ws,we,ww]; wneighbor_count=sum(wneighbors)
                w_is_corner=wneighbor_count==2 and ((wn and we) or (wn and ww) or (ws and we) or (ws and ww))
                water_width=s-2*shore_w; offset=shore_w; r_in=offset; r_out=offset+water_width
                def build_water_path():
                    path=QPainterPath()
                    if w_is_corner:
                        if wn and we:
                            path.moveTo(x+r_in,y); path.arcTo(x+s-r_out,y-r_out,2*r_out,2*r_out,180,90)
                            path.lineTo(x+s,y+r_in); path.arcTo(x+s-r_in,y-r_in,2*r_in,2*r_in,270,-90); path.closeSubpath()
                        elif wn and ww:
                            path.moveTo(x+r_out,y); path.arcTo(x-r_out,y-r_out,2*r_out,2*r_out,0,-90)
                            path.lineTo(x,y+r_in); path.arcTo(x-r_in,y-r_in,2*r_in,2*r_in,270,90); path.closeSubpath()
                        elif ws and we:
                            path.moveTo(x+s,y+s-r_out); path.arcTo(x+s-r_out,y+s-r_out,2*r_out,2*r_out,90,90)
                            path.lineTo(x+r_out,y+s); path.arcTo(x+s-r_in,y+s-r_in,2*r_in,2*r_in,180,-90); path.closeSubpath()
                        elif ws and ww:
                            path.moveTo(x,y+s-r_out); path.arcTo(x-r_out,y+s-r_out,2*r_out,2*r_out,90,-90)
                            path.lineTo(x+r_in,y+s); path.arcTo(x-r_in,y+s-r_in,2*r_in,2*r_in,0,90); path.closeSubpath()
                    else:
                        path.addRect(x+offset,y+offset,water_width,water_width)
                        if wn: path.addRect(x+offset,y,water_width,offset)
                        if ws: path.addRect(x+offset,y+offset+water_width,water_width,s-(offset+water_width))
                        if we: path.addRect(x+offset+water_width,y+offset,s-(offset+water_width),water_width)
                        if ww: path.addRect(x,y+offset,offset,water_width)
                        if wneighbor_count==0: path.addRect(x+offset,y,water_width,s)
                        path=path.simplified()
                    return path
                water_path=build_water_path()
                shore_rect=self.scene.addRect(x,y,s,s); shore_rect.setBrush(shore_col); shore_rect.setPen(Qt.NoPen); group.addToGroup(shore_rect)
                def lerp_color(c1,c2,t):
                    return QColor(int(c1.red()+(c2.red()-c1.red())*t),int(c1.green()+(c2.green()-c1.green())*t),int(c1.blue()+(c2.blue()-c1.blue())*t))
                for ring in range(depth_rings):
                    t=ring/max(1,depth_rings-1); ring_col=lerp_color(shallow_col,deep_col,t)
                    if ring==0: ring_path=water_path
                    else:
                        shrink=t*shore_w*1.2; inner_off=offset+shrink; inner_w=max(2,s-2*inner_off)
                        inner_rin=inner_off; inner_rout=inner_off+inner_w
                        def build_inner(io,iw,iri,iro):
                            p2=QPainterPath()
                            if w_is_corner:
                                if wn and we:
                                    p2.moveTo(x+iri,y); p2.arcTo(x+s-iro,y-iro,2*iro,2*iro,180,90); p2.lineTo(x+s,y+iri); p2.arcTo(x+s-iri,y-iri,2*iri,2*iri,270,-90); p2.closeSubpath()
                                elif wn and ww:
                                    p2.moveTo(x+iro,y); p2.arcTo(x-iro,y-iro,2*iro,2*iro,0,-90); p2.lineTo(x,y+iri); p2.arcTo(x-iri,y-iri,2*iri,2*iri,270,90); p2.closeSubpath()
                                elif ws and we:
                                    p2.moveTo(x+s,y+s-iro); p2.arcTo(x+s-iro,y+s-iro,2*iro,2*iro,90,90); p2.lineTo(x+iro,y+s); p2.arcTo(x+s-iri,y+s-iri,2*iri,2*iri,180,-90); p2.closeSubpath()
                                elif ws and ww:
                                    p2.moveTo(x,y+s-iro); p2.arcTo(x-iro,y+s-iro,2*iro,2*iro,90,-90); p2.lineTo(x+iri,y+s); p2.arcTo(x-iri,y+s-iri,2*iri,2*iri,0,90); p2.closeSubpath()
                            else:
                                p2.addRect(x+io,y+io,iw,iw)
                                if wn: p2.addRect(x+io,y,iw,io)
                                if ws: p2.addRect(x+io,y+io+iw,iw,s-(io+iw))
                                if we: p2.addRect(x+io+iw,y+io,s-(io+iw),iw)
                                if ww: p2.addRect(x,y+io,io,iw)
                                if wneighbor_count==0: p2.addRect(x+io,y,iw,s)
                                p2=p2.simplified()
                            return p2
                        ring_path=build_inner(inner_off,inner_w,inner_rin,inner_rout)
                    ri=self.scene.addPath(ring_path); ri.setBrush(ring_col); ri.setPen(Qt.NoPen); group.addToGroup(ri)
                cx2=x+s/2; cy2=y+s/2; ripple_r=water_width*0.35
                rpen=QPen(QColor(255,255,255,55),max(1,int(scale*0.6)))
                for _ in range(max(1,int(turbulence/15))+1):
                    rx2=cx2+random.uniform(-ripple_r,ripple_r); ry2=cy2+random.uniform(-ripple_r,ripple_r)
                    rw2=random.uniform(ripple_r*0.3,ripple_r*0.9); rh2=rw2*random.uniform(0.3,0.6)
                    rip=self.scene.addEllipse(rx2-rw2/2,ry2-rh2/2,rw2,rh2); rip.setBrush(Qt.NoBrush); rip.setPen(rpen); group.addToGroup(rip)
                if shore_style=="Grassy" and not w_is_corner:
                    wpen=QPen(QColor(60,100,45),max(1,int(scale)))
                    for side,gx_fn,gy_fn in [
                        (not wn, lambda:x+random.uniform(offset,s-offset), lambda:y+random.uniform(0,shore_w*0.8)),
                        (not ws, lambda:x+random.uniform(offset,s-offset), lambda:y+s-random.uniform(0,shore_w*0.8)),
                        (not ww, lambda:x+random.uniform(0,shore_w*0.8),   lambda:y+random.uniform(offset,s-offset)),
                        (not we, lambda:x+s-random.uniform(0,shore_w*0.8), lambda:y+random.uniform(offset,s-offset)),
                    ]:
                        if side:
                            for _ in range(random.randint(2,4)):
                                gx3=gx_fn(); gy3=gy_fn(); wh=random.uniform(scale*3,scale*7)
                                group.addToGroup(self.scene.addLine(gx3,gy3,gx3+random.uniform(-2,2)*scale,gy3-wh,wpen))
                if not w_is_corner and water_width>s*0.25:
                    if "Fountain" in feature:
                        basin_r=water_width*0.18
                        basin=self.scene.addEllipse(cx2-basin_r,cy2-basin_r,basin_r*2,basin_r*2)
                        basin.setBrush(QColor(200,200,195,180)); basin.setPen(QPen(QColor(160,155,148),max(1,int(scale)))); group.addToGroup(basin)
                        spray_pen=QPen(QColor(200,225,255,160),max(1,int(scale*0.8)))
                        for ang_deg in range(0,360,45):
                            ang=math.radians(ang_deg); sr2=basin_r*0.55; sh2=basin_r*random.uniform(0.8,1.4)
                            sx2=cx2+math.cos(ang)*sr2*0.3; sy2=cy2+math.sin(ang)*sr2*0.3
                            group.addToGroup(self.scene.addLine(sx2,sy2,sx2+math.cos(ang)*sr2,sy2-sh2,spray_pen))
                        group.addToGroup(self.scene.addLine(cx2,cy2,cx2,cy2-basin_r*1.6,spray_pen))
                    if "Lily Pads" in feature:
                        pad_col=QColor(55,110,45,210); pad_pen=QPen(QColor(35,80,30),max(1,int(scale*0.5)))
                        for _ in range(random.randint(3,6)):
                            pr=random.uniform(water_width*0.055,water_width*0.10)
                            px4=cx2+random.uniform(-water_width*0.28,water_width*0.28)
                            py4=cy2+random.uniform(-water_width*0.28,water_width*0.28)
                            pad=self.scene.addEllipse(px4-pr,py4-pr*0.7,pr*2,pr*1.4); pad.setBrush(pad_col); pad.setPen(pad_pen); group.addToGroup(pad)
                            group.addToGroup(self.scene.addLine(px4,py4,px4,py4-pr*0.7,pad_pen))
                            if random.random()<0.35:
                                fl=self.scene.addEllipse(px4-pr*0.3,py4-pr*0.65,pr*0.6,pr*0.6); fl.setBrush(QColor(240,200,200,220)); fl.setPen(Qt.NoPen); group.addToGroup(fl)
                    if "Reeds" in feature:
                        rpen2=QPen(QColor(85,110,55),max(1,int(scale*0.9)))
                        for _ in range(random.randint(5,11)):
                            ang=random.uniform(0,2*math.pi); dist=random.uniform(0.35,0.72)
                            rx3=cx2+math.cos(ang)*water_width*0.5*dist; ry3=cy2+math.sin(ang)*water_width*0.5*dist
                            rh3=random.uniform(scale*6,scale*13)
                            group.addToGroup(self.scene.addLine(rx3,ry3,rx3+random.uniform(-1,1)*scale,ry3-rh3,rpen2))
                            hr=scale*random.uniform(1.0,2.0)
                            head=self.scene.addEllipse(rx3-hr*0.5,ry3-rh3-hr*1.5,hr,hr*2.5); head.setBrush(QColor(60,45,20)); head.setPen(Qt.NoPen); group.addToGroup(head)
                group.setZValue(-4)

        self.scene.addItem(group); self.grid_items[(col,row)]=group

    def _scene_cell(self, pos):
        scene_pos=self.mapToScene(pos); col=int(scene_pos.x()//self.cell_size); row=int(scene_pos.y()//self.cell_size)
        max_c=self.scene_width//self.cell_size; max_r=self.scene_height//self.cell_size
        if 0<=col<max_c and 0<=row<max_r: return col,row
        return None

    def mousePressEvent(self, event):
        if event.button()==Qt.MiddleButton:
            self._panning=True; self._pan_start=event.pos(); self.setCursor(Qt.ClosedHandCursor); event.accept()
        elif event.button()==Qt.LeftButton:
            cell=self._scene_cell(event.pos())
            if cell:
                data=self.get_active_data_cb()
                if data: self.place_tile(cell[0],cell[1],data.copy())
            event.accept()
        elif event.button()==Qt.RightButton:
            cell=self._scene_cell(event.pos())
            if cell: self.erase_tile(cell[0],cell[1])
            event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta=event.pos()-self._pan_start; self._pan_start=event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y()); event.accept()
        elif event.buttons()&Qt.LeftButton:
            cell=self._scene_cell(event.pos())
            if cell:
                data=self.get_active_data_cb()
                if data: self.place_tile(cell[0],cell[1],data.copy())
            event.accept()
        elif event.buttons()&Qt.RightButton:
            cell=self._scene_cell(event.pos())
            if cell: self.erase_tile(cell[0],cell[1])
            event.accept()
        else: super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button()==Qt.MiddleButton:
            self._panning=False; self.setCursor(Qt.ArrowCursor); event.accept()
        else: super().mouseReleaseEvent(event)


# ── City Editor Panel ─────────────────────────────────────────────────────────

class CityEditor(QWidget):
    """Wraps CityCanvas + the three tabs, mirroring the original MainWindow layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.city_canvas = CityCanvas()
        layout.addWidget(self.city_canvas)

        self.tabs = QTabWidget(); self.tabs.setFixedWidth(350)

        self.env_tab = EnvironmentTab(); self.env_tab.main_window = self
        self.tabs.addTab(self.env_tab, "Environment")

        self.road_tab = RoadTab(); self.road_tab.main_window = self
        self.tabs.addTab(self.road_tab, "Roads")

        self.building_tab = BuildingTab(); self.building_tab.main_window = self
        self.tabs.addTab(self.building_tab, "Buildings")

        layout.addWidget(self.tabs)
        self.city_canvas.get_active_data_cb = self._get_active_data

    # expose sun_angle so CityCanvas.draw_tile can call self.window().sun_angle
    @property
    def sun_angle(self): return self.window().sun_angle if hasattr(self.window(),'sun_angle') else 45

    def _get_active_data(self):
        active = self.tabs.currentWidget()
        if active == self.building_tab: return self.building_tab.get_current_data()
        elif active == self.road_tab:   return self.road_tab.get_current_data()
        elif active == self.env_tab:    return self.env_tab.get_current_data()
        return None

    # ── Project serialisation helpers ─────────────────────────────────────────

    @staticmethod
    def _strip_texture_image(params: dict) -> dict:
        """Return a copy of a material params dict safe for JSON (no QImage)."""
        p = params.copy()
        p.pop("texture_image", None)   # not serialisable; path is kept
        return p

    @staticmethod
    def _serialise_material(mat: dict) -> dict:
        return {"type": mat.get("type", "Solid Color"),
                "params": CityEditor._strip_texture_image(mat.get("params", {}))}

    def _serialise_tile(self, data: dict) -> dict:
        """Deep-copy a tile dict, stripping non-JSON fields."""
        d = {}
        for k, v in data.items():
            if k in ("wall_material", "roof_material"):
                d[k] = self._serialise_material(v)
            elif k == "surface_material":
                d[k] = self._serialise_material(v)
            else:
                d[k] = v
        return d

    def get_project_data(self, sun_angle: int, cell_size: int) -> dict:
        """Collect everything needed to reconstruct this city project."""
        # grid tiles (anchor tiles only — children are reconstructed on load)
        tiles = []
        for (c, r), data in self.city_canvas.grid_data.items():
            if data.get("type") == "child":
                continue
            t = self._serialise_tile(data)
            t["_col"] = c
            t["_row"] = r
            tiles.append(t)

        return {
            "version": 1,
            "cell_size": cell_size,
            "sun_angle": sun_angle,
            "buildings": [self._serialise_tile(b)
                          for b in self.building_tab.building_types],
            "roads":     [self._serialise_tile(r)
                          for r in self.road_tab.road_types],
            "envs":      [self._serialise_tile(e)
                          for e in self.env_tab.env_types],
            "tiles":     tiles,
        }

    def _rehydrate_material(self, mat: dict) -> dict:
        """Reload texture_image from disk if a texture_path is stored."""
        if mat.get("type") != "Custom Texture":
            return mat
        params = mat.get("params", {})
        path = params.get("texture_path")
        if path:
            img = load_custom_texture(path)
            if img:
                params = params.copy()
                params["texture_image"] = img
            else:
                print(f"[load] missing texture: {path}")
        return {"type": mat["type"], "params": params}

    def _rehydrate_tile(self, d: dict) -> dict:
        """Restore any Custom Texture images in a tile dict."""
        d = d.copy()
        for key in ("wall_material", "roof_material", "surface_material"):
            if key in d:
                d[key] = self._rehydrate_material(d[key])
        return d

    def load_project_data(self, proj: dict, cell_size_spin) -> tuple:
        """
        Restore canvas + tab presets from a saved project dict.
        Returns (cell_size, sun_angle).
        """
        cell_size  = proj.get("cell_size",  128)
        sun_angle  = proj.get("sun_angle",  45)

        # ── Clear canvas ──────────────────────────────────────────────────────
        for key in list(self.city_canvas.grid_data.keys()):
            self.city_canvas.erase_tile(key[0], key[1], update_neighbors=False)
        pattern_cache.clear()

        # ── Restore cell size ─────────────────────────────────────────────────
        cell_size_spin.blockSignals(True)
        cell_size_spin.setValue(cell_size)
        cell_size_spin.blockSignals(False)
        self.city_canvas.set_block_size(cell_size)

        # ── Restore building presets ──────────────────────────────────────────
        self.building_tab.building_types.clear()
        self.building_tab.combo_box.blockSignals(True)
        self.building_tab.combo_box.clear()
        for b in proj.get("buildings", []):
            self.building_tab.building_types.append(self._rehydrate_tile(b))
            self.building_tab.combo_box.addItem(b.get("name", "Building"))
        self.building_tab.combo_box.blockSignals(False)
        if self.building_tab.building_types:
            self.building_tab.combo_box.setCurrentIndex(0)
            self.building_tab.load_selected(0)

        # ── Restore road presets ──────────────────────────────────────────────
        self.road_tab.road_types.clear()
        self.road_tab.combo_box.blockSignals(True)
        self.road_tab.combo_box.clear()
        for r in proj.get("roads", []):
            self.road_tab.road_types.append(self._rehydrate_tile(r))
            self.road_tab.combo_box.addItem(r.get("name", "Road"))
        self.road_tab.combo_box.blockSignals(False)
        if self.road_tab.road_types:
            self.road_tab.combo_box.setCurrentIndex(0)
            self.road_tab.load_selected(0)

        # ── Restore environment presets ───────────────────────────────────────
        self.env_tab.env_types.clear()
        self.env_tab.combo_box.blockSignals(True)
        self.env_tab.combo_box.clear()
        for e in proj.get("envs", []):
            self.env_tab.env_types.append(self._rehydrate_tile(e))
            self.env_tab.combo_box.addItem(e.get("name", "Env"))
        self.env_tab.combo_box.blockSignals(False)
        if self.env_tab.env_types:
            self.env_tab.combo_box.setCurrentIndex(0)
            self.env_tab.load_selected(0)

        # ── Re-place tiles ────────────────────────────────────────────────────
        for tile in proj.get("tiles", []):
            col = tile.pop("_col"); row = tile.pop("_row")
            tile = self._rehydrate_tile(tile)
            self.city_canvas.place_tile(col, row, tile)

        return cell_size, sun_angle

    # ── PNG export ────────────────────────────────────────────────────────────

    def export_map(self, parent_window):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Map Data", "my_city", "PNG Image (*.png)")
        if not file_path: return
        base_path = file_path.rsplit('.', 1)[0]
        scene = self.city_canvas.scene; rect = scene.sceneRect()
        for line in self.city_canvas.grid_lines: line.hide()
        for (c,r),group in self.city_canvas.grid_items.items():
            data=self.city_canvas.grid_data.get((c,r))
            (group.hide() if data and data["type"]=="building" else group.show())
        img_ground=QImage(int(rect.width()),int(rect.height()),QImage.Format_ARGB32)
        img_ground.fill(QColor(100,150,100)); pg=QPainter(img_ground); scene.render(pg); pg.end()
        img_ground.save(f"{base_path}_ground.png")
        for (c,r),group in self.city_canvas.grid_items.items():
            data=self.city_canvas.grid_data.get((c,r))
            (group.show() if data and data["type"]=="building" else group.hide())
        prev_bg=scene.backgroundBrush(); scene.setBackgroundBrush(Qt.NoBrush)
        img_bldgs=QImage(int(rect.width()),int(rect.height()),QImage.Format_ARGB32)
        img_bldgs.fill(QColor(0,0,0,0)); pb=QPainter(img_bldgs); scene.render(pb); pb.end()
        img_bldgs.save(f"{base_path}_buildings.png")
        export_data={"canvas_width":self.city_canvas.scene_width,"canvas_height":self.city_canvas.scene_height,
                     "cell_size":self.city_canvas.cell_size,"objects":[]}
        for (c,r),data in self.city_canvas.grid_data.items():
            if data["type"]=="child": continue
            obj=data.copy(); obj["grid_x"]=c; obj["grid_y"]=r
            obj["pixel_x"]=c*self.city_canvas.cell_size; obj["pixel_y"]=r*self.city_canvas.cell_size
            export_data["objects"].append(obj)
        with open(f"{base_path}_data.json",'w') as f: json.dump(export_data,f,indent=4)
        scene.setBackgroundBrush(prev_bg)
        for group in self.city_canvas.grid_items.values(): group.show()
        for line in self.city_canvas.grid_lines: line.show()
        QMessageBox.information(parent_window,"Export Successful",
            f"Exported to:\n{base_path}_ground.png\n{base_path}_buildings.png\n{base_path}_data.json")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    PROJECT_EXT     = ".levproj"
    PROJECT_FILTER  = "Level Project (*.levproj)"
    WINDOW_BASE     = "Level Editor  //  City + Terrain"

    def __init__(self):
        super().__init__()
        self.sun_angle     = 45
        self._project_path = None   # current file path or None (unsaved)
        self._dirty        = False  # unsaved changes flag

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QToolBar("Main"); tb.setMovable(False); self.addToolBar(tb)

        # Mode toggle
        mode_lbl = QLabel("  Mode: ")
        mode_lbl.setStyleSheet("color:#777; font-size:11px;")
        tb.addWidget(mode_lbl)

        self.btn_city = QPushButton("CITY")
        self.btn_city.setObjectName("mode_city")
        self.btn_city.setCheckable(True); self.btn_city.setChecked(True)
        self.btn_city.setFixedHeight(26)
        self.btn_city.clicked.connect(lambda: self._switch_mode("city"))
        tb.addWidget(self.btn_city)

        self.btn_terrain = QPushButton("TERRAIN")
        self.btn_terrain.setObjectName("mode_terrain")
        self.btn_terrain.setCheckable(True)
        self.btn_terrain.setFixedHeight(26)
        self.btn_terrain.clicked.connect(lambda: self._switch_mode("terrain"))
        tb.addWidget(self.btn_terrain)

        tb.addSeparator()

        # ── Project buttons (always visible) ──────────────────────────────────
        def _proj_btn(label, slot, tip=""):
            b = QPushButton(label); b.setFixedHeight(26)
            b.setToolTip(tip); b.clicked.connect(slot)
            b.setStyleSheet(
                "QPushButton{background:#1e1e1e;border:1px solid #333;border-radius:2px;"
                "color:#aaa;padding:0 8px;font-size:10px;letter-spacing:1px;}"
                "QPushButton:hover{background:#2a2a2a;border-color:#555;}"
            )
            return b

        self.btn_new  = _proj_btn("NEW",     self._new_project,  "New project (clears canvas)")
        self.btn_open = _proj_btn("OPEN",    self._open_project, "Open .levproj file  (Ctrl+O)")
        self.btn_save = _proj_btn("SAVE",    self._save_project, "Save project  (Ctrl+S)")
        self.btn_saveas = _proj_btn("SAVE AS", self._save_project_as, "Save project as new file")
        for b in (self.btn_new, self.btn_open, self.btn_save, self.btn_saveas):
            tb.addWidget(b)

        tb.addSeparator()

        # ── City-only controls ────────────────────────────────────────────────
        self.lbl_grid = QLabel("  Grid: ")
        self.lbl_grid.setStyleSheet("color:#777; font-size:11px;")
        tb.addWidget(self.lbl_grid)
        self.spinbox = QSpinBox(); self.spinbox.setRange(32, 512)
        self.spinbox.setSingleStep(32); self.spinbox.setValue(128)
        tb.addWidget(self.spinbox)

        hint = QLabel("  LMB: Paint  |  RMB: Erase  |  MMB: Pan")
        hint.setStyleSheet("color:#555; font-style:italic;")
        tb.addWidget(hint)
        self._city_toolbar_widgets = [self.lbl_grid, self.spinbox, hint]

        self.lbl_sun = QLabel("  Sun: ")
        self.lbl_sun.setStyleSheet("color:#777; font-size:11px;")
        tb.addWidget(self.lbl_sun)
        self.dial_sun = QDial(); self.dial_sun.setFixedSize(36, 36)
        self.dial_sun.setRange(0, 360); self.dial_sun.setValue(45)
        self.dial_sun.valueChanged.connect(self._update_sun)
        tb.addWidget(self.dial_sun)
        self._city_toolbar_widgets += [self.lbl_sun, self.dial_sun]

        self.btn_export_city = QPushButton("Export PNGs")
        self.btn_export_city.setStyleSheet(
            "background:#182028;border:1px solid #334455;"
            "color:#6a9acc;padding:4px 10px;")
        self.btn_export_city.setToolTip("Bake city to ground + building PNG layers + JSON")
        self.btn_export_city.clicked.connect(self._export_city)
        tb.addWidget(self.btn_export_city)
        self._city_toolbar_widgets.append(self.btn_export_city)

        # ── Central stacked widget ────────────────────────────────────────────
        self._stack = QStackedWidget()

        self.city_editor = CityEditor()
        self._stack.addWidget(self.city_editor)    # index 0

        self.terrain_editor = TerrainEditor()
        self._stack.addWidget(self.terrain_editor) # index 1

        self.setCentralWidget(self._stack)

        # Generate terrain only on first visit to that tab
        self._stack.currentChanged.connect(self._on_stack_changed)

        # Wire grid-size spinbox
        self.spinbox.valueChanged.connect(self._on_cell_size_changed)

        # Mark dirty whenever the canvas changes
        self.city_editor.city_canvas.scene.changed.connect(self._mark_dirty)

        # Keyboard shortcuts
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_project)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_project)
        QShortcut(QKeySequence("Ctrl+N"), self, self._new_project)

        self._switch_mode("city")
        self._update_title()

    # ── Title bar ─────────────────────────────────────────────────────────────

    def _update_title(self):
        if self._project_path:
            import os
            name = os.path.basename(self._project_path)
        else:
            name = "untitled"
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"{self.WINDOW_BASE}  —  {name}{dirty}")

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    # ── Mode switching ────────────────────────────────────────────────────────

    def _on_stack_changed(self, index):
        if index == 1 and not self.terrain_editor._first_shown:
            self.terrain_editor._first_shown = True
            QTimer.singleShot(50, self.terrain_editor._generate)

    def _switch_mode(self, mode):
        is_city = (mode == "city")
        self.btn_city.setChecked(is_city)
        self.btn_terrain.setChecked(not is_city)
        self._stack.setCurrentIndex(0 if is_city else 1)
        for w in self._city_toolbar_widgets:
            w.setVisible(is_city)

    def _update_sun(self, val):
        self.sun_angle = val
        self.city_editor.city_canvas.redraw_all()
        self._mark_dirty()

    def _on_cell_size_changed(self, val):
        self.city_editor.city_canvas.set_block_size(val)
        self._mark_dirty()

    def _export_city(self):
        self.city_editor.export_map(self)

    # ── Unsaved-changes guard ─────────────────────────────────────────────────

    def _confirm_discard(self) -> bool:
        """Return True if it's OK to discard current work."""
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "The current project has unsaved changes.\nDiscard and continue?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Save:
            return self._save_project()   # returns True on success
        return reply == QMessageBox.Discard

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # ── New / Open / Save ─────────────────────────────────────────────────────

    def _new_project(self):
        if not self._confirm_discard():
            return
        # Clear canvas and reset all presets to one default each
        ce = self.city_editor
        for key in list(ce.city_canvas.grid_data.keys()):
            ce.city_canvas.erase_tile(key[0], key[1], update_neighbors=False)
        pattern_cache.clear()
        # Reset tab presets
        for tab, klass in [(ce.building_tab, None), (ce.road_tab, None), (ce.env_tab, None)]:
            tab.building_types if hasattr(tab, 'building_types') else None
            lst_attr = ('building_types' if hasattr(tab,'building_types')
                        else 'road_types' if hasattr(tab,'road_types')
                        else 'env_types')
            getattr(tab, lst_attr).clear()
            tab.combo_box.blockSignals(True); tab.combo_box.clear()
            tab.combo_box.blockSignals(False)
            tab.add_new()
        self.spinbox.setValue(128)
        self.dial_sun.setValue(45)
        self._project_path = None
        self._dirty = False
        self._update_title()
        self._switch_mode("city")

    def _open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", self.PROJECT_FILTER)
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                proj = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", f"Could not read project:\n{e}")
            return

        try:
            cell_size, sun_angle = self.city_editor.load_project_data(proj, self.spinbox)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Project load failed:\n{e}")
            return

        self.dial_sun.blockSignals(True)
        self.dial_sun.setValue(sun_angle)
        self.sun_angle = sun_angle
        self.dial_sun.blockSignals(False)
        self.city_editor.city_canvas.redraw_all()

        self._project_path = path
        self._dirty = False
        self._update_title()
        self._switch_mode("city")

    def _save_project(self) -> bool:
        """Save to current path; prompt for path if unsaved. Returns True on success."""
        if self._project_path is None:
            return self._save_project_as()
        return self._write_project(self._project_path)

    def _save_project_as(self) -> bool:
        import os
        default = os.path.splitext(self._project_path)[0] if self._project_path else "my_city"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", default, self.PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith(self.PROJECT_EXT):
            path += self.PROJECT_EXT
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            proj = self.city_editor.get_project_data(
                sun_angle=self.sun_angle,
                cell_size=self.city_editor.city_canvas.cell_size,
            )
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(proj, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save project:\n{e}")
            return False
        self._project_path = path
        self._dirty = False
        self._update_title()
        return True


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.setStyleSheet(DARK_STYLE)
    w.show()
    sys.exit(app.exec())
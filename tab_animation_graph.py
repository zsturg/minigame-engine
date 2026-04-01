import sys
import os
import json
import numpy as np
from itertools import product
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QMessageBox,
                             QHBoxLayout, QGraphicsView, QGraphicsScene, QSplitter, 
                             QLabel, QPushButton, QDoubleSpinBox, 
                             QToolButton, QMenu, QGraphicsPathItem, QGraphicsItem,
                             QComboBox, QColorDialog, QDialog, QFormLayout, QSpinBox,
                             QCheckBox, QFileDialog, QProgressDialog, QLineEdit,
                             QFontComboBox, QScrollArea, QFrame, QTextEdit,
                             QPlainTextEdit)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal, QEvent
from PySide6.QtGui import (QColor, QPen, QPainterPath, QImage, QPixmap, QPainter,
                         QFont, QBrush, QPolygonF, QFontDatabase)
from PIL import Image as PILImage
import glob
import shlex
from theme_utils import get_default_theme, replace_widget_theme_colors
# ==========================================
# 0. PROJECT SETTINGS
# ==========================================
class ProjectConfig:
    def __init__(self):
        self.width = 960
        self.height = 544
        self.fps = 30
        self.duration = 60
        self.bg_style = "Checkerboard"
        self.preview_divisor = 4
        self.preview_mode = "Fit"  # Fit, Actual Size, Full Screen Context
        self.file_path = None  # Current save path

    def to_dict(self):
        return {
            'width': self.width, 'height': self.height,
            'fps': self.fps, 'duration': self.duration,
            'bg_style': self.bg_style, 'preview_divisor': self.preview_divisor,
            'preview_mode': self.preview_mode
        }

    def from_dict(self, d):
        self.width = d.get('width', 960)
        self.height = d.get('height', 544)
        self.fps = d.get('fps', 30)
        self.duration = d.get('duration', 60)
        self.bg_style = d.get('bg_style', 'Checkerboard')
        self.preview_divisor = d.get('preview_divisor', 4)
        self.preview_mode = d.get('preview_mode', 'Fit')

PROJECT = ProjectConfig()

# TileCanvasNode updates this before rendering each atlas cell so seed-driven
# nodes can vary per tile without changing the rest of the graph API.
TILE_SEED_OFFSET = 0

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Animation Settings")
        layout = QFormLayout()
        self.w_spin = QSpinBox(); self.w_spin.setRange(1, 4096); self.w_spin.setValue(PROJECT.width)
        self.h_spin = QSpinBox(); self.h_spin.setRange(1, 4096); self.h_spin.setValue(PROJECT.height)
        self.fps_spin = QSpinBox(); self.fps_spin.setRange(1, 120); self.fps_spin.setValue(PROJECT.fps)
        self.dur_spin = QSpinBox(); self.dur_spin.setRange(1, 10000); self.dur_spin.setValue(PROJECT.duration)
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["Checkerboard", "Black", "Dark Gray"])
        self.bg_combo.setCurrentText(PROJECT.bg_style)
        self.preview_combo = QComboBox()
        self.preview_combo.addItems(["1 (Full)", "2 (Half)", "4 (Quarter)", "8 (Eighth)"])
        self.preview_combo.setCurrentIndex({1:0,2:1,4:2,8:3}.get(PROJECT.preview_divisor, 2))
        layout.addRow("Width:", self.w_spin); layout.addRow("Height:", self.h_spin)
        layout.addRow("FPS:", self.fps_spin); layout.addRow("Duration (Frames):", self.dur_spin)
        layout.addRow("Background:", self.bg_combo); layout.addRow("Preview Quality:", self.preview_combo)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Apply"); ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn); btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box); self.setLayout(layout)

    def apply_settings(self):
        PROJECT.width = self.w_spin.value(); PROJECT.height = self.h_spin.value()
        PROJECT.fps = self.fps_spin.value(); PROJECT.duration = self.dur_spin.value()
        PROJECT.bg_style = self.bg_combo.currentText()
        PROJECT.preview_divisor = [1, 2, 4, 8][self.preview_combo.currentIndex()]

# ==========================================
# 1. CORE DATA MODEL
# ==========================================
class NodeProperty:
    def __init__(self, name, value=0.0, min_val=-100.0, max_val=100.0,
                 is_enum=False, enum_items=None, is_bool=False, is_string=False):
        self.name = name
        self.default_value = value
        self.min_val = min_val
        self.max_val = max_val
        self.keyframes = {}
        self.override_frame = -1
        self.override_value = None
        self.is_enum = is_enum
        self.is_bool = is_bool
        self.is_string = is_string
        self.enum_items = enum_items or []

    def get_value(self, frame):
        if frame == self.override_frame and self.override_value is not None:
            return self.override_value
        if frame in self.keyframes:
            return self.keyframes[frame]
        if not self.keyframes:
            return self.default_value
        if self.is_enum or self.is_bool or self.is_string:
            frames = sorted(self.keyframes.keys())
            if frame < frames[0]: return self.keyframes[frames[0]]
            valid = [k for k in frames if k <= frame]
            return self.keyframes[valid[-1]] if valid else self.default_value
        frames = sorted(self.keyframes.keys())
        if frame <= frames[0]: return self.keyframes[frames[0]]
        if frame >= frames[-1]: return self.keyframes[frames[-1]]
        for i in range(len(frames) - 1):
            a, b = frames[i], frames[i+1]
            if a <= frame <= b:
                t = (frame - a) / (b - a)
                return self.keyframes[a] + (self.keyframes[b] - self.keyframes[a]) * t
        return self.default_value

    def set_keyframe(self, frame, value):
        self.keyframes[frame] = value
        self.clear_override()
        
    def remove_keyframe(self, frame):
        if frame in self.keyframes: del self.keyframes[frame]
        
    def set_override(self, frame, value):
        self.override_frame = frame
        self.override_value = value
        
    def clear_override(self):
        self.override_frame = -1
        self.override_value = None

    def to_dict(self):
        return {
            'name': self.name,
            'default_value': self.default_value,
            'min_val': self.min_val,
            'max_val': self.max_val,
            'is_enum': self.is_enum,
            'is_bool': self.is_bool,
            'is_string': self.is_string,
            'enum_items': self.enum_items,
            'keyframes': {str(k): v for k, v in self.keyframes.items()}
        }

    def from_dict(self, d):
        self.default_value = d.get('default_value', self.default_value)
        self.keyframes = {int(k): v for k, v in d.get('keyframes', {}).items()}

# ==========================================
# 2. NOISE UTILITIES
# ==========================================
def _hash2d_vec(xi, yi, seed=0):
    xi = xi.astype(np.int64); yi = yi.astype(np.int64)
    n = xi * 374761393 + yi * 668265263 + seed * 1274126177
    n = (n ^ (n >> 13)) * 1274126177; n = n ^ (n >> 16)
    return (n & 0x7fffffff) / 0x7fffffff

def _hash2d_gradient(xi, yi, seed=0):
    h = _hash2d_vec(xi, yi, seed); angle = h * 2.0 * np.pi
    return np.cos(angle), np.sin(angle)

def _smoothstep(t): return t*t*t*(t*(t*6.0-15.0)+10.0)
def _lerp(a, b, t): return a + (b - a) * t

_HASH_PRIMES = (
    np.int64(374761393),
    np.int64(668265263),
    np.int64(2147483647),
    np.int64(1274126177),
    np.int64(97531),
)

_SIMPLEX_GRAD3 = np.array([
    [1, 1, 0],  [-1, 1, 0],  [1, -1, 0],  [-1, -1, 0],
    [1, 0, 1],  [-1, 0, 1],  [1, 0, -1],  [-1, 0, -1],
    [0, 1, 1],  [0, -1, 1],  [0, 1, -1],  [0, -1, -1],
], dtype=np.float32)

_SIMPLEX_GRAD4 = np.array([
    [0, 1, 1, 1],   [0, 1, 1, -1],  [0, 1, -1, 1],  [0, 1, -1, -1],
    [0, -1, 1, 1],  [0, -1, 1, -1], [0, -1, -1, 1], [0, -1, -1, -1],
    [1, 0, 1, 1],   [1, 0, 1, -1],  [1, 0, -1, 1],  [1, 0, -1, -1],
    [-1, 0, 1, 1],  [-1, 0, 1, -1], [-1, 0, -1, 1], [-1, 0, -1, -1],
    [1, 1, 0, 1],   [1, 1, 0, -1],  [1, -1, 0, 1],  [1, -1, 0, -1],
    [-1, 1, 0, 1],  [-1, 1, 0, -1], [-1, -1, 0, 1], [-1, -1, 0, -1],
    [1, 1, 1, 0],   [1, 1, -1, 0],  [1, -1, 1, 0],  [1, -1, -1, 0],
    [-1, 1, 1, 0],  [-1, 1, -1, 0], [-1, -1, 1, 0], [-1, -1, -1, 0],
], dtype=np.float32)

def _smoothstep_edges(edge0, edge1, x):
    width = max(float(edge1) - float(edge0), 1e-6)
    return _smoothstep(np.clip((x - edge0) / width, 0.0, 1.0))

def _hash_nd(seed, *coords):
    acc = np.zeros_like(np.asarray(coords[0], dtype=np.int64), dtype=np.int64)
    acc += np.int64(seed) * np.int64(1274126177)
    for idx, coord in enumerate(coords):
        ci = np.asarray(coord, dtype=np.int64)
        acc ^= ci * _HASH_PRIMES[idx % len(_HASH_PRIMES)]
        acc = (acc ^ (acc >> 13)) * np.int64(1274126177)
        acc ^= (acc >> 16)
    return (acc & np.int64(0x7fffffff)) / float(0x7fffffff)

def _normalize_components(*components):
    mag_sq = np.zeros_like(np.asarray(components[0], dtype=np.float64), dtype=np.float64)
    for comp in components:
        mag_sq += comp * comp
    mag = np.sqrt(mag_sq)
    mag = np.where(mag < 1e-8, 1.0, mag)
    return tuple(comp / mag for comp in components)

def _hash3d_gradient(xi, yi, zi, seed=0):
    gx = _hash_nd(seed + 11, xi, yi, zi) * 2.0 - 1.0
    gy = _hash_nd(seed + 29, xi, yi, zi) * 2.0 - 1.0
    gz = _hash_nd(seed + 47, xi, yi, zi) * 2.0 - 1.0
    return _normalize_components(gx, gy, gz)

def _hash4d_gradient(xi, yi, zi, wi, seed=0):
    gx = _hash_nd(seed + 11, xi, yi, zi, wi) * 2.0 - 1.0
    gy = _hash_nd(seed + 29, xi, yi, zi, wi) * 2.0 - 1.0
    gz = _hash_nd(seed + 47, xi, yi, zi, wi) * 2.0 - 1.0
    gw = _hash_nd(seed + 71, xi, yi, zi, wi) * 2.0 - 1.0
    return _normalize_components(gx, gy, gz, gw)

def _interpolate_hypercube(values, weights):
    acc = list(values)
    for t in reversed(weights):
        acc = [_lerp(acc[i], acc[i + 1], t) for i in range(0, len(acc), 2)]
    return acc[0]

def _simplex_grad3(cx, cy, cz, seed=0):
    idx = (_hash_nd(seed + 313, cx, cy, cz) * len(_SIMPLEX_GRAD3)).astype(np.int32) % len(_SIMPLEX_GRAD3)
    grads = _SIMPLEX_GRAD3[idx]
    return grads[..., 0], grads[..., 1], grads[..., 2]

def _simplex_grad4(cx, cy, cz, cw, seed=0):
    idx = (_hash_nd(seed + 313, cx, cy, cz, cw) * len(_SIMPLEX_GRAD4)).astype(np.int32) % len(_SIMPLEX_GRAD4)
    grads = _SIMPLEX_GRAD4[idx]
    return grads[..., 0], grads[..., 1], grads[..., 2], grads[..., 3]

def value_noise_2d(X, Y, seed=0):
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64)
    xf = X - xi; yf = Y - yi; u = _smoothstep(xf); v = _smoothstep(yf)
    return _lerp(_lerp(_hash2d_vec(xi,yi,seed), _hash2d_vec(xi+1,yi,seed), u),
                 _lerp(_hash2d_vec(xi,yi+1,seed), _hash2d_vec(xi+1,yi+1,seed), u), v)

def value_noise_3d(X, Y, Z, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64); Z = np.asarray(Z, dtype=np.float64)
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64); zi = np.floor(Z).astype(np.int64)
    xf = X - xi; yf = Y - yi; zf = Z - zi
    u = _smoothstep(xf); v = _smoothstep(yf); w = _smoothstep(zf)
    corners = [
        _hash_nd(seed, xi + dx, yi + dy, zi + dz)
        for dx, dy, dz in product((0, 1), repeat=3)
    ]
    return _interpolate_hypercube(corners, (u, v, w))

def value_noise_4d(X, Y, Z, W, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64)
    Z = np.asarray(Z, dtype=np.float64); W = np.asarray(W, dtype=np.float64)
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64)
    zi = np.floor(Z).astype(np.int64); wi = np.floor(W).astype(np.int64)
    xf = X - xi; yf = Y - yi; zf = Z - zi; wf = W - wi
    u = _smoothstep(xf); v = _smoothstep(yf); s = _smoothstep(zf); t = _smoothstep(wf)
    corners = [
        _hash_nd(seed, xi + dx, yi + dy, zi + dz, wi + dw)
        for dx, dy, dz, dw in product((0, 1), repeat=4)
    ]
    return _interpolate_hypercube(corners, (u, v, s, t))

def perlin_noise_2d(X, Y, seed=0):
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64)
    xf = X - xi; yf = Y - yi; u = _smoothstep(xf); v = _smoothstep(yf)
    def gd(cx, cy, dx, dy):
        gx, gy = _hash2d_gradient(cx, cy, seed); return gx*dx + gy*dy
    n00=gd(xi,yi,xf,yf); n10=gd(xi+1,yi,xf-1,yf)
    n01=gd(xi,yi+1,xf,yf-1); n11=gd(xi+1,yi+1,xf-1,yf-1)
    return _lerp(_lerp(n00,n10,u), _lerp(n01,n11,u), v) * 0.7071 + 0.5

def perlin_noise_3d(X, Y, Z, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64); Z = np.asarray(Z, dtype=np.float64)
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64); zi = np.floor(Z).astype(np.int64)
    xf = X - xi; yf = Y - yi; zf = Z - zi
    u = _smoothstep(xf); v = _smoothstep(yf); w = _smoothstep(zf)

    def gd(dx, dy, dz):
        gx, gy, gz = _hash3d_gradient(xi + dx, yi + dy, zi + dz, seed)
        return gx * (xf - dx) + gy * (yf - dy) + gz * (zf - dz)

    corners = [gd(dx, dy, dz) for dx, dy, dz in product((0, 1), repeat=3)]
    return np.clip(_interpolate_hypercube(corners, (u, v, w)) * 0.5 + 0.5, 0.0, 1.0)

def perlin_noise_4d(X, Y, Z, W, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64)
    Z = np.asarray(Z, dtype=np.float64); W = np.asarray(W, dtype=np.float64)
    xi = np.floor(X).astype(np.int64); yi = np.floor(Y).astype(np.int64)
    zi = np.floor(Z).astype(np.int64); wi = np.floor(W).astype(np.int64)
    xf = X - xi; yf = Y - yi; zf = Z - zi; wf = W - wi
    u = _smoothstep(xf); v = _smoothstep(yf); s = _smoothstep(zf); t = _smoothstep(wf)

    def gd(dx, dy, dz, dw):
        gx, gy, gz, gw = _hash4d_gradient(xi + dx, yi + dy, zi + dz, wi + dw, seed)
        return gx * (xf - dx) + gy * (yf - dy) + gz * (zf - dz) + gw * (wf - dw)

    corners = [gd(dx, dy, dz, dw) for dx, dy, dz, dw in product((0, 1), repeat=4)]
    return np.clip(_interpolate_hypercube(corners, (u, v, s, t)) * 0.5 + 0.5, 0.0, 1.0)

def simplex_noise_2d(X, Y, seed=0):
    F2 = 0.5*(np.sqrt(3.0)-1.0); G2 = (3.0-np.sqrt(3.0))/6.0
    s = (X+Y)*F2
    i = np.floor(X+s).astype(np.int64); j = np.floor(Y+s).astype(np.int64)
    t = (i+j)*G2; x0 = X-(i-t); y0 = Y-(j-t)
    i1 = np.where(x0>y0,1,0).astype(np.int64); j1 = np.where(x0>y0,0,1).astype(np.int64)
    x1=x0-i1+G2; y1=y0-j1+G2; x2=x0-1.0+2.0*G2; y2=y0-1.0+2.0*G2
    def ct(cx, cy, dx, dy):
        tt = np.maximum(0.5-dx*dx-dy*dy, 0.0); tt = tt*tt
        gx, gy = _hash2d_gradient(cx, cy, seed); return tt*tt*(gx*dx+gy*dy)
    return (70.0*(ct(i,j,x0,y0)+ct(i+i1,j+j1,x1,y1)+ct(i+1,j+1,x2,y2)))*0.5+0.5

def simplex_noise_3d(X, Y, Z, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64); Z = np.asarray(Z, dtype=np.float64)
    F3 = 1.0 / 3.0
    G3 = 1.0 / 6.0
    s = (X + Y + Z) * F3
    i = np.floor(X + s).astype(np.int64)
    j = np.floor(Y + s).astype(np.int64)
    k = np.floor(Z + s).astype(np.int64)
    t = (i + j + k) * G3
    x0 = X - (i - t)
    y0 = Y - (j - t)
    z0 = Z - (k - t)

    rankx = np.zeros_like(x0, dtype=np.int64)
    ranky = np.zeros_like(x0, dtype=np.int64)
    rankz = np.zeros_like(x0, dtype=np.int64)
    rankx += (x0 > y0).astype(np.int64); ranky += (x0 <= y0).astype(np.int64)
    rankx += (x0 > z0).astype(np.int64); rankz += (x0 <= z0).astype(np.int64)
    ranky += (y0 > z0).astype(np.int64); rankz += (y0 <= z0).astype(np.int64)

    i1 = (rankx >= 2).astype(np.int64); j1 = (ranky >= 2).astype(np.int64); k1 = (rankz >= 2).astype(np.int64)
    i2 = (rankx >= 1).astype(np.int64); j2 = (ranky >= 1).astype(np.int64); k2 = (rankz >= 1).astype(np.int64)

    x1 = x0 - i1 + G3;      y1 = y0 - j1 + G3;      z1 = z0 - k1 + G3
    x2 = x0 - i2 + 2*G3;    y2 = y0 - j2 + 2*G3;    z2 = z0 - k2 + 2*G3
    x3 = x0 - 1.0 + 3*G3;   y3 = y0 - 1.0 + 3*G3;   z3 = z0 - 1.0 + 3*G3

    def ct(cx, cy, cz, dx, dy, dz):
        tt = np.maximum(0.6 - dx*dx - dy*dy - dz*dz, 0.0)
        tt = tt * tt
        gx, gy, gz = _simplex_grad3(cx, cy, cz, seed)
        return tt * tt * (gx * dx + gy * dy + gz * dz)

    n0 = ct(i,         j,         k,         x0, y0, z0)
    n1 = ct(i + i1,    j + j1,    k + k1,    x1, y1, z1)
    n2 = ct(i + i2,    j + j2,    k + k2,    x2, y2, z2)
    n3 = ct(i + 1,     j + 1,     k + 1,     x3, y3, z3)
    return np.clip((32.0 * (n0 + n1 + n2 + n3)) * 0.5 + 0.5, 0.0, 1.0)

def simplex_noise_4d(X, Y, Z, W, seed=0):
    X = np.asarray(X, dtype=np.float64); Y = np.asarray(Y, dtype=np.float64)
    Z = np.asarray(Z, dtype=np.float64); W = np.asarray(W, dtype=np.float64)
    F4 = (np.sqrt(5.0) - 1.0) / 4.0
    G4 = (5.0 - np.sqrt(5.0)) / 20.0
    s = (X + Y + Z + W) * F4
    i = np.floor(X + s).astype(np.int64)
    j = np.floor(Y + s).astype(np.int64)
    k = np.floor(Z + s).astype(np.int64)
    l = np.floor(W + s).astype(np.int64)
    t = (i + j + k + l) * G4
    x0 = X - (i - t)
    y0 = Y - (j - t)
    z0 = Z - (k - t)
    w0 = W - (l - t)

    rankx = np.zeros_like(x0, dtype=np.int64)
    ranky = np.zeros_like(x0, dtype=np.int64)
    rankz = np.zeros_like(x0, dtype=np.int64)
    rankw = np.zeros_like(x0, dtype=np.int64)

    rankx += (x0 > y0).astype(np.int64); ranky += (x0 <= y0).astype(np.int64)
    rankx += (x0 > z0).astype(np.int64); rankz += (x0 <= z0).astype(np.int64)
    rankx += (x0 > w0).astype(np.int64); rankw += (x0 <= w0).astype(np.int64)
    ranky += (y0 > z0).astype(np.int64); rankz += (y0 <= z0).astype(np.int64)
    ranky += (y0 > w0).astype(np.int64); rankw += (y0 <= w0).astype(np.int64)
    rankz += (z0 > w0).astype(np.int64); rankw += (z0 <= w0).astype(np.int64)

    i1 = (rankx >= 3).astype(np.int64); j1 = (ranky >= 3).astype(np.int64); k1 = (rankz >= 3).astype(np.int64); l1 = (rankw >= 3).astype(np.int64)
    i2 = (rankx >= 2).astype(np.int64); j2 = (ranky >= 2).astype(np.int64); k2 = (rankz >= 2).astype(np.int64); l2 = (rankw >= 2).astype(np.int64)
    i3 = (rankx >= 1).astype(np.int64); j3 = (ranky >= 1).astype(np.int64); k3 = (rankz >= 1).astype(np.int64); l3 = (rankw >= 1).astype(np.int64)

    x1 = x0 - i1 + G4;        y1 = y0 - j1 + G4;        z1 = z0 - k1 + G4;        w1 = w0 - l1 + G4
    x2 = x0 - i2 + 2*G4;      y2 = y0 - j2 + 2*G4;      z2 = z0 - k2 + 2*G4;      w2 = w0 - l2 + 2*G4
    x3 = x0 - i3 + 3*G4;      y3 = y0 - j3 + 3*G4;      z3 = z0 - k3 + 3*G4;      w3 = w0 - l3 + 3*G4
    x4 = x0 - 1.0 + 4*G4;     y4 = y0 - 1.0 + 4*G4;     z4 = z0 - 1.0 + 4*G4;     w4 = w0 - 1.0 + 4*G4

    def ct(cx, cy, cz, cw, dx, dy, dz, dw):
        tt = np.maximum(0.6 - dx*dx - dy*dy - dz*dz - dw*dw, 0.0)
        tt = tt * tt
        gx, gy, gz, gw = _simplex_grad4(cx, cy, cz, cw, seed)
        return tt * tt * (gx * dx + gy * dy + gz * dz + gw * dw)

    n0 = ct(i,         j,         k,         l,         x0, y0, z0, w0)
    n1 = ct(i + i1,    j + j1,    k + k1,    l + l1,    x1, y1, z1, w1)
    n2 = ct(i + i2,    j + j2,    k + k2,    l + l2,    x2, y2, z2, w2)
    n3 = ct(i + i3,    j + j3,    k + k3,    l + l3,    x3, y3, z3, w3)
    n4 = ct(i + 1,     j + 1,     k + 1,     l + 1,     x4, y4, z4, w4)
    return np.clip((27.0 * (n0 + n1 + n2 + n3 + n4)) * 0.5 + 0.5, 0.0, 1.0)

def _dist_euc(components):
    total = np.zeros_like(np.asarray(components[0], dtype=np.float64), dtype=np.float64)
    for comp in components:
        total += comp * comp
    return np.sqrt(total)

def _dist_man(components):
    total = np.zeros_like(np.asarray(components[0], dtype=np.float64), dtype=np.float64)
    for comp in components:
        total += np.abs(comp)
    return total

def _dist_cheb(components):
    total = np.zeros_like(np.asarray(components[0], dtype=np.float64), dtype=np.float64)
    for comp in components:
        total = np.maximum(total, np.abs(comp))
    return total

DFUNCS = {0: _dist_euc, 1: _dist_man, 2: _dist_cheb}

def cellular_info_nd(*coords, seed=0, jitter=1.0, dist_type=0):
    coord_arrays = [np.asarray(coord, dtype=np.float64) for coord in coords]
    cell_coords = [np.floor(coord).astype(np.int64) for coord in coord_arrays]
    dfn = DFUNCS.get(dist_type, _dist_euc)
    f1 = np.full_like(coord_arrays[0], 999.0, dtype=np.float64)
    f2 = np.full_like(coord_arrays[0], 999.0, dtype=np.float64)
    cid = np.zeros_like(coord_arrays[0], dtype=np.float64)

    for offsets in product((-1, 0, 1), repeat=len(coord_arrays)):
        lattice = [cell_coords[idx] + offsets[idx] for idx in range(len(coord_arrays))]
        point = []
        for dim, cell in enumerate(lattice):
            h = _hash_nd(seed + 1009 * (dim + 1), *lattice)
            point.append(cell + 0.5 + ((h - 0.5) * jitter))
        d = dfn([coord_arrays[idx] - point[idx] for idx in range(len(coord_arrays))])
        tid = _hash_nd(seed + 9999, *lattice)
        use_f1 = d < f1
        f2 = np.where(use_f1, f1, np.where(d < f2, d, f2))
        f1 = np.where(use_f1, d, f1)
        cid = np.where(use_f1, tid, cid)

    return f1, f2, np.clip(cid, 0.0, 1.0)

def cellular_noise_nd(*coords, seed=0, jitter=1.0, dist_type=0, mode=0):
    f1, f2, cid = cellular_info_nd(*coords, seed=seed, jitter=jitter, dist_type=dist_type)
    if mode == 0:
        result = f1
    elif mode == 1:
        result = f2
    elif mode == 2:
        result = f2 - f1
    elif mode == 3:
        return cid
    else:
        result = f1
    norm = 1.2 * np.sqrt(max(len(coords), 2) / 2.0)
    return np.clip(result / norm, 0.0, 1.0)

def cellular_noise_2d(X, Y, seed=0, jitter=1.0, dist_type=0, mode=0):
    return cellular_noise_nd(X, Y, seed=seed, jitter=jitter, dist_type=dist_type, mode=mode)

def fbm_noise(coords, fn, octaves=1, lac=2.0, pers=0.5, seed=0, **kw):
    result = np.zeros_like(np.asarray(coords[0], dtype=np.float64), dtype=np.float64)
    amp = 1.0; freq = 1.0; ma = 0.0
    for i in range(int(octaves)):
        scaled_coords = tuple(coord * freq for coord in coords)
        result += amp * fn(*scaled_coords, seed=seed+i*37, **kw)
        ma += amp; amp *= pers; freq *= lac
    return result / ma if ma > 0 else result

def domain_warp(X, Y, strength, seed=0):
    if strength <= 0.001: return X, Y
    wx = perlin_noise_2d(X, Y, seed=seed+500) - 0.5
    wy = perlin_noise_2d(X, Y, seed=seed+700) - 0.5
    return X + wx*strength, Y + wy*strength

def normalized_time(frame, total):
    return frame / max(total - 1, 1)

def temporal_components(frame, total, evolution, loop=False):
    evo = max(float(evolution), 0.0)
    if evo <= 0.001:
        return ()
    t = normalized_time(frame, total)
    if loop:
        angle = t * 2.0 * np.pi
        return (np.cos(angle) * evo, np.sin(angle) * evo)
    return (t * evo,)

# ==========================================
# 2b. PARTICLE UTILITIES
# ==========================================
def deterministic_random(seed, index, offset=0):
    """Generate deterministic random value from seed and index"""
    n = (seed * 1274126177 + index * 668265263 + offset * 374761393) & 0x7fffffff
    n = ((n ^ (n >> 13)) * 1274126177) & 0x7fffffff
    n = (n ^ (n >> 16)) & 0x7fffffff
    return n / 0x7fffffff

def deterministic_random_range(seed, index, offset, min_val, max_val):
    """Generate deterministic random value in range"""
    return min_val + deterministic_random(seed, index, offset) * (max_val - min_val)

# ==========================================
# 2c. SDF UTILITIES
# ==========================================
def sdf_grid(w, h):
    x = np.linspace(-1, 1, w); y = np.linspace(-1, 1, h)
    X, Y = np.meshgrid(x, y)
    if w > h: X *= (w/h)
    else: Y *= (h/w)
    return X, Y

def apply_transform(X, Y, pos_x, pos_y, rotation, scale_x, scale_y):
    """Apply inverse transform to coordinates (scale, rotate, translate)"""
    # Translate
    X = X - pos_x
    Y = Y - pos_y
    # Scale (inverse)
    if scale_x != 0: X = X / scale_x
    if scale_y != 0: Y = Y / scale_y
    # Rotate (inverse)
    if rotation != 0:
        angle = -np.radians(rotation)
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        X_new = X * cos_a - Y * sin_a
        Y_new = X * sin_a + Y * cos_a
        X, Y = X_new, Y_new
    return X, Y

def sdf_circle(X, Y, r): return np.sqrt(X**2+Y**2)-r
def sdf_box(X, Y, bw, bh):
    dx = np.abs(X)-bw; dy = np.abs(Y)-bh
    return np.sqrt(np.maximum(dx,0)**2+np.maximum(dy,0)**2)+np.minimum(np.maximum(dx,dy),0)
def sdf_ring(X, Y, r, t): return np.abs(np.sqrt(X**2+Y**2)-r)-t
def sdf_hexagon(X, Y, r): return np.maximum(np.abs(X)*0.866025+np.abs(Y)*0.5, np.abs(Y))-r
def sdf_star(X, Y, radius, points=5, inner_ratio=0.4):
    angle = np.arctan2(Y, X); dist = np.sqrt(X**2+Y**2)
    seg = 2.0*np.pi/points; a = np.mod(angle+seg*0.5, seg)-seg*0.5
    t = np.abs(a)/(seg*0.5); smooth_r = _lerp(radius, radius*inner_ratio, t)
    return dist - smooth_r

def sdf_soft(d, softness):
    return 1.0 - np.clip(d / max(softness, 0.0001), 0.0, 1.0)

def sdf_to_rgba(mask):
    h, w = mask.shape
    arr = np.zeros((h, w, 4), dtype=np.float32)
    arr[...,0]=mask; arr[...,1]=mask; arr[...,2]=mask; arr[...,3]=mask
    return arr

# ==========================================
# 3. LOGIC NODES
# ==========================================

# Node type registry for serialization
NODE_TYPES = {}

def register_node(cls):
    NODE_TYPES[cls.__name__] = cls
    return cls

# ==========================================
# 3a. LLM COPY/PASTE HELPERS
# ==========================================

def _ani_format_props(node, frame=0):
    """Return 'PropName=value ...' string for non-default properties only.
    If a property has keyframes, emits PropName={frame:val,frame:val,...} instead of a scalar.
    """
    parts = []
    for name, prop in node.properties.items():
        if prop.keyframes:
            # Serialize all keyframes — always emit regardless of values
            inner = ",".join(
                f"{f}:{round(v, 4)}" if isinstance(v, float) else f"{f}:{v}"
                for f, v in sorted(prop.keyframes.items())
            )
            parts.append(f"{name}={{{inner}}}")
        else:
            # No keyframes — emit scalar only if it differs from the class default
            val = prop.get_value(frame)
            if val != prop.default_value:
                if isinstance(val, float):
                    parts.append(f"{name}={round(val, 4)}")
                else:
                    parts.append(f"{name}={val}")
    return "  ".join(parts)


def ani_canvas_to_text(tab, selected_only=False):
    """Serialize animation graph nodes to human/LLM-readable text."""
    from PySide6.QtWidgets import QGraphicsScene
    # Collect GfxNode items
    all_gfx = [item for item in tab.scene.items() if isinstance(item, GfxNode)]
    if selected_only:
        gfx_items = [item for item in all_gfx if item.isSelected()]
        if not gfx_items:
            gfx_items = all_gfx
    else:
        gfx_items = all_gfx

    # Build local id map
    local_id = {gfx.logic: i for i, gfx in enumerate(gfx_items)}
    logic_to_gfx = {gfx.logic: gfx for gfx in gfx_items}

    lines = ["# Animation Graph"]
    # NODE lines
    for i, gfx in enumerate(gfx_items):
        node = gfx.logic
        cls_name = type(node).__name__
        p = gfx.pos()
        prop_str = _ani_format_props(node, 0)
        line = f"NODE {cls_name}  id={i}  pos={round(p.x(),1)},{round(p.y(),1)}"
        if prop_str:
            line += f"  {prop_str}"
        lines.append(line)
        # Extra data (e.g. ColorRampNode color_stops, ImageTextureNode image_path)
        extra = node._extra_to_dict()
        if extra:
            lines.append(f"# extra: {json.dumps(extra, separators=(',', ':'))}")

    # CONNECT lines
    for gfx in gfx_items:
        node = gfx.logic
        if node not in local_id:
            continue
        to_id = local_id[node]
        for slot_idx, input_node in enumerate(node.inputs):
            if input_node is not None and input_node in local_id:
                from_id = local_id[input_node]
                lines.append(f"CONNECT from={from_id}  to={to_id}  input={slot_idx}")

    return "\n".join(lines)


def ani_text_to_nodes(text):
    """Parse animation graph text back into node specs and connection specs.

    Returns (node_specs, connection_specs, warnings).
    node_specs: list of dicts with keys cls_name, local_id, pos, props, extra
    connection_specs: list of dicts with keys from_id, to_id, input_slot
    warnings: list of str
    """
    node_specs = []
    connection_specs = []
    warnings = []
    last_node_spec = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if line.startswith("# extra:") and last_node_spec is not None:
                try:
                    extra_json = line[len("# extra:"):].strip()
                    last_node_spec["extra"] = json.loads(extra_json)
                except Exception as e:
                    warnings.append(f"Could not parse extra data: {e}")
            continue

        if line.startswith("NODE "):
            try:
                tokens = shlex.split(line)
            except Exception as e:
                warnings.append(f"Malformed NODE line: {e}")
                continue

            if len(tokens) < 2:
                warnings.append(f"Malformed NODE line: {line}")
                continue

            cls_name = tokens[1]
            if cls_name not in NODE_TYPES:
                warnings.append(f"Unknown node type '{cls_name}' — skipped.")
                last_node_spec = None
                continue

            spec = {"cls_name": cls_name, "local_id": None, "pos": QPointF(0, 0),
                    "props": {}, "extra": {}}
            for tok in tokens[2:]:
                if "=" not in tok:
                    continue
                k, v = tok.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "id":
                    try:
                        spec["local_id"] = int(v)
                    except ValueError:
                        pass
                elif k == "pos":
                    try:
                        px, py = v.split(",")
                        spec["pos"] = QPointF(float(px), float(py))
                    except Exception:
                        pass
                else:
                    if v.startswith("{") and v.endswith("}"):
                        try:
                            inner = v[1:-1]
                            kf = {}
                            for pair in inner.split(","):
                                if ":" not in pair:
                                    continue
                                kf_frame, kf_val = pair.split(":", 1)
                                raw_kf_val = kf_val.strip()
                                try:
                                    parsed_kf_val = float(raw_kf_val)
                                except ValueError:
                                    parsed_kf_val = raw_kf_val.strip("\"'")
                                kf[int(kf_frame.strip())] = parsed_kf_val
                            spec["props"][k] = kf
                        except Exception:
                            warnings.append(f"Could not parse keyframes for '{k}': {v}")
                    else:
                        try:
                            spec["props"][k] = float(v)
                        except ValueError:
                            spec["props"][k] = v

            node_specs.append(spec)
            last_node_spec = spec

        elif line.startswith("CONNECT "):
            try:
                tokens = shlex.split(line)
            except Exception as e:
                warnings.append(f"Malformed CONNECT line: {e}")
                continue
            conn = {"from_id": None, "to_id": None, "input_slot": 0}
            for tok in tokens[1:]:
                if "=" not in tok:
                    continue
                k, v = tok.split("=", 1)
                k = k.strip(); v = v.strip()
                try:
                    if k == "from":
                        conn["from_id"] = int(v)
                    elif k == "to":
                        conn["to_id"] = int(v)
                    elif k == "input":
                        conn["input_slot"] = int(v)
                except ValueError:
                    pass
            if conn["from_id"] is not None and conn["to_id"] is not None:
                connection_specs.append(conn)
            else:
                warnings.append(f"Malformed CONNECT line: {line}")

    return node_specs, connection_specs, warnings

def _ani_parse_bool_value(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if float(value) != 0.0 else 0.0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return 1.0
        if s in ("0", "false", "no", "off"):
            return 0.0
    raise ValueError(f"invalid bool value: {value}")


def _ani_parse_enum_value(prop, raw_value):
    if isinstance(raw_value, str):
        s = raw_value.strip()
        if s == "":
            raise ValueError("empty enum value")
        try:
            enum_index = int(float(s))
        except Exception:
            lowered = s.lower()
            enum_index = None
            for i, item in enumerate(prop.enum_items or []):
                if str(item).strip().lower() == lowered:
                    enum_index = i
                    break
            if enum_index is None:
                raise ValueError(f"enum requires integer index or valid label, got {raw_value!r}")
    else:
        enum_index = int(float(raw_value))

    max_index = max(0, len(prop.enum_items) - 1)
    if enum_index < 0:
        enum_index = 0
    if enum_index > max_index:
        enum_index = max_index
    return float(enum_index)


def _ani_sanitize_scalar_for_property(prop, raw_value):
    if prop.is_string:
        if raw_value is None:
            return ""
        return str(raw_value)

    if prop.is_bool:
        return _ani_parse_bool_value(raw_value)

    if prop.is_enum:
        return _ani_parse_enum_value(prop, raw_value)

    if isinstance(raw_value, str):
        s = raw_value.strip()
        if s == "":
            raise ValueError("empty numeric value")
        numeric = float(s)
    else:
        numeric = float(raw_value)

    if numeric < prop.min_val:
        numeric = prop.min_val
    if numeric > prop.max_val:
        numeric = prop.max_val
    return numeric


def _ani_apply_sanitized_property(node, prop_name, raw_value, warnings, node_label=""):
    prop = node.properties.get(prop_name)
    if prop is None:
        warnings.append(f"{node_label}Unknown property '{prop_name}' skipped.")
        return False

    try:
        clean_value = _ani_sanitize_scalar_for_property(prop, raw_value)
    except Exception as e:
        warnings.append(f"{node_label}Property '{prop_name}' skipped: {e}")
        return False

    prop.default_value = clean_value
    prop.keyframes.clear()
    prop.clear_override()
    return True


def _ani_apply_sanitized_keyframes(node, prop_name, raw_keyframes, warnings, node_label=""):
    prop = node.properties.get(prop_name)
    if prop is None:
        warnings.append(f"{node_label}Unknown property '{prop_name}' skipped.")
        return False

    if not isinstance(raw_keyframes, dict):
        warnings.append(f"{node_label}Property '{prop_name}' keyframes skipped: not a dict.")
        return False

    sanitized = {}
    for raw_frame, raw_value in raw_keyframes.items():
        try:
            frame = int(raw_frame)
            if frame < 0:
                warnings.append(f"{node_label}Property '{prop_name}' keyframe {raw_frame} skipped: negative frame.")
                continue
        except Exception:
            warnings.append(f"{node_label}Property '{prop_name}' keyframe '{raw_frame}' skipped: invalid frame.")
            continue

        try:
            sanitized_value = _ani_sanitize_scalar_for_property(prop, raw_value)
        except Exception as e:
            warnings.append(f"{node_label}Property '{prop_name}' keyframe {frame} skipped: {e}")
            continue

        sanitized[frame] = sanitized_value

    if not sanitized:
        warnings.append(f"{node_label}Property '{prop_name}' keyframes skipped: no valid entries.")
        return False

    prop.keyframes.clear()
    for frame in sorted(sanitized.keys()):
        prop.set_keyframe(frame, sanitized[frame])
    prop.clear_override()
    return True


def build_ani_legend_text():
    """Build a human/LLM-readable reference document of all registered node types."""
    skip_instantiate = {"ImageTextureNode", "PNGSequenceNode"}

    lines = [
        "=== VITA ADVENTURE CREATOR — ANIMATION GRAPH NODE LEGEND ===",
        "Use these class names in NODE lines when writing or editing graphs.",
        "",
        "━━ STRICT RULES ━━",
        "  1. Every node line must start with: NODE ClassName id=N pos=X,Y",
        "  2. Use quoted strings only for real string properties.",
        '     Example: NODE TextNode id=0 pos=0,0 Text="Hello World" Font="Times New Roman" Size=48',
        "  3. Enum properties may use either the numeric index or the exact label shown below.",
        "  4. Bool properties may use 0/1, true/false, yes/no, on/off.",
        "  5. Keyframes must use compact braces with no spaces inside one pair.",
        "     Example: Evolution={0:0.0,300:5.0}",
        "  6. The # extra line is JSON and must use full objects, not shorthand numbers.",
        '     Valid ColorRamp extra: # extra: {"color_stops":[{"pos":0.0,"r":0.0,"g":0.0,"b":0.0,"a":1.0},{"pos":1.0,"r":1.0,"g":1.0,"b":1.0,"a":1.0}]}',
        '     Invalid ColorRamp extra: # extra: {"color_stops":[0.4,0.45]}',
        "  7. Do not invent node types. Use only the registered node classes listed below.",
        "  8. Always include explicit pos=X,Y values and spread nodes horizontally.",
        "",
        "━━ NODE TYPES ━━",
        "",
    ]

    for cls_name, cls in sorted(NODE_TYPES.items()):
        if cls_name in skip_instantiate:
            lines.append(f"  {cls_name}")
            lines.append("    (contains file path data — omit or set manually after paste)")
            lines.append("")
            continue
        try:
            node = cls()
        except Exception:
            lines.append(f"  {cls_name}  (could not inspect)")
            lines.append("")
            continue

        num_inputs = len(node.inputs)
        lines.append(f"  {cls_name:<30} inputs={num_inputs}")

        for prop_name, prop in node.properties.items():
            if prop.is_enum and prop.enum_items:
                items_str = ", ".join(f"{i}:{item}" for i, item in enumerate(prop.enum_items))
                lines.append(f"    {prop_name:<20} enum [{items_str}]  default={prop.default_value}")
            elif prop.is_bool:
                lines.append(f"    {prop_name:<20} bool  default={prop.default_value}")
            elif prop.is_string:
                lines.append(f"    {prop_name:<20} string  default={repr(prop.default_value)}")
            else:
                lines.append(f"    {prop_name:<20} float ({prop.min_val}–{prop.max_val})  default={prop.default_value}")
        lines.append("")

    lines += [
        "━━ GRAPH TEXT FORMAT ━━",
        "  NODE ClassName  id=N  pos=X,Y  PropName=value ...",
        '  # extra: {"color_stops": [...]}   ← optional, for ColorRampNode etc.',
        "  CONNECT from=<id>  to=<id>  input=<slot>",
        "",
        "━━ VALID EXAMPLES ━━",
        "  NODE VoronoiNode id=0 pos=-320,0 Output=Edge Scale=12 Evolution={0:0.0,300:5.0}",
        "  NODE ColorRampNode id=1 pos=-80,0 Mode=Constant",
        '  # extra: {"color_stops":[{"pos":0.0,"r":0.0,"g":0.2,"b":0.5,"a":1.0},{"pos":0.45,"r":0.0,"g":0.8,"b":1.0,"a":1.0},{"pos":1.0,"r":1.0,"g":1.0,"b":1.0,"a":1.0}]}',
        "  NODE MergeNode id=2 pos=160,0 Mode=Screen Opacity=0.6",
        "  NODE OutputNode id=3 pos=400,0",
        "  CONNECT from=0 to=1 input=0",
        "  CONNECT from=1 to=2 input=0",
        "  CONNECT from=2 to=3 input=0",
        "",
        "━━ INVALID EXAMPLES ━━",
        "  NODE GlowNode id=6                  ← invalid if GlowNode is not in the node list below",
        "  NODE VoronoiNode id=0 Output=Edge   ← invalid if pos=X,Y is omitted",
        '  # extra: {"color_stops":[0.4,0.45]}   ← invalid ColorRamp payload',
        "",
        "OutputNode is always present. Paste will skip creating a second OutputNode.",
        "id values are local to this paste batch, starting at 0.",
        "Omit props with default values to keep text compact.",
    ]
    return "\n".join(lines)



class BaseNode:
    def __init__(self, name):
        self.name = name
        self.pos = QPointF(0, 0)
        self.properties = {}
        self.inputs = []
        self.node_id = id(self)  # Unique ID for serialization

    def add_property(self, name, default=0.0, min_v=-100.0, max_v=100.0,
                     is_enum=False, items=None, is_bool=False, is_string=False):
        self.properties[name] = NodeProperty(name, default, min_v, max_v, is_enum, items, is_bool, is_string)

    def add_transform_properties(self):
        """Add standard transform properties"""
        self.add_property("Pos X", 0.0, -10.0, 10.0)
        self.add_property("Pos Y", 0.0, -10.0, 10.0)
        self.add_property("Rotation", 0.0, -360.0, 360.0)
        self.add_property("Scale X", 1.0, 0.01, 10.0)
        self.add_property("Scale Y", 1.0, 0.01, 10.0)

    def get_transform(self, frame):
        """Get transform values for current frame"""
        return (
            self.properties.get("Pos X", NodeProperty("", 0)).get_value(frame),
            self.properties.get("Pos Y", NodeProperty("", 0)).get_value(frame),
            self.properties.get("Rotation", NodeProperty("", 0)).get_value(frame),
            self.properties.get("Scale X", NodeProperty("", 1)).get_value(frame),
            self.properties.get("Scale Y", NodeProperty("", 1)).get_value(frame)
        )

    def evaluate(self, frame, w, h):
        return np.zeros((h, w, 4), dtype=np.float32)

    def to_dict(self):
        return {
            'type': self.__class__.__name__,
            'node_id': self.node_id,
            'pos': [self.pos.x(), self.pos.y()],
            'properties': {k: v.to_dict() for k, v in self.properties.items()},
            'inputs': [None] * len(self.inputs),  # Connections handled separately
            'extra': self._extra_to_dict()
        }

    def _extra_to_dict(self):
        """Override for node-specific data"""
        return {}

    def _extra_from_dict(self, d):
        """Override for node-specific data"""
        pass

    def from_dict(self, d):
        self.node_id = d.get('node_id', id(self))
        pos = d.get('pos', [0, 0])
        self.pos = QPointF(pos[0], pos[1])
        for k, v in d.get('properties', {}).items():
            if k in self.properties:
                self.properties[k].from_dict(v)
        self._extra_from_dict(d.get('extra', {}))

@register_node
class OutputNode(BaseNode):
    def __init__(self):
        super().__init__("Output")
        self.inputs = [None]

    def evaluate(self, frame, w, h):
        if self.inputs[0]:
            return self.inputs[0].evaluate(frame, w, h)
        return np.zeros((h, w, 4), dtype=np.float32)

@register_node
class ValueNode(BaseNode):
    def __init__(self):
        super().__init__("Value")
        self.add_property("Val", 1.0, -1000.0, 1000.0)

    def evaluate(self, frame, w, h):
        return np.full((h, w, 4), self.properties["Val"].get_value(frame), dtype=np.float32)

@register_node
class ColorNode(BaseNode):
    def __init__(self):
        super().__init__("Color")
        self.add_property("Red", 1.0, 0, 1)
        self.add_property("Green", 0.0, 0, 1)
        self.add_property("Blue", 0.0, 0, 1)
        self.add_property("Alpha", 1.0, 0, 1)

    def evaluate(self, frame, w, h):
        arr = np.zeros((h, w, 4), dtype=np.float32)
        arr[:] = [
            self.properties["Red"].get_value(frame),
            self.properties["Green"].get_value(frame),
            self.properties["Blue"].get_value(frame),
            self.properties["Alpha"].get_value(frame)
        ]
        return arr

@register_node
class MixNode(BaseNode):
    def __init__(self):
        super().__init__("Mix")
        self.inputs = [None, None]
        self.add_property("Factor", 0.5, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        a = self.inputs[0].evaluate(frame, w, h) if self.inputs[0] else np.zeros((h, w, 4))
        b = self.inputs[1].evaluate(frame, w, h) if self.inputs[1] else np.zeros((h, w, 4))
        f = np.clip(self.properties["Factor"].get_value(frame), 0.0, 1.0)
        return (1.0 - f) * a + f * b

@register_node
class MergeNode(BaseNode):
    BLEND_MODES = [
        "Normal", "Add", "Subtract", "Multiply",
        "Screen", "Overlay", "Darken", "Lighten",
        "Difference", "Divide"
    ]

    def __init__(self):
        super().__init__("Merge")
        self.inputs = [None, None]  # [Base, Blend]
        self.add_property("Mode", 0.0, is_enum=True, items=self.BLEND_MODES)
        self.add_property("Opacity", 1.0, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        base  = self.inputs[0].evaluate(frame, w, h) if self.inputs[0] else np.zeros((h, w, 4), dtype=np.float32)
        blend = self.inputs[1].evaluate(frame, w, h) if self.inputs[1] else np.zeros((h, w, 4), dtype=np.float32)

        mode    = int(self.properties["Mode"].get_value(frame))
        opacity = np.clip(self.properties["Opacity"].get_value(frame), 0.0, 1.0)

        b_rgb = base[..., :3]
        f_rgb = blend[..., :3]

        if   mode == 0: comp = f_rgb                                                          # Normal
        elif mode == 1: comp = b_rgb + f_rgb                                                  # Add
        elif mode == 2: comp = b_rgb - f_rgb                                                  # Subtract
        elif mode == 3: comp = b_rgb * f_rgb                                                  # Multiply
        elif mode == 4: comp = 1.0 - (1.0 - b_rgb) * (1.0 - f_rgb)                          # Screen
        elif mode == 5: comp = np.where(b_rgb < 0.5,                                         # Overlay
                                        2.0 * b_rgb * f_rgb,
                                        1.0 - 2.0 * (1.0 - b_rgb) * (1.0 - f_rgb))
        elif mode == 6: comp = np.minimum(b_rgb, f_rgb)                                       # Darken
        elif mode == 7: comp = np.maximum(b_rgb, f_rgb)                                       # Lighten
        elif mode == 8: comp = np.abs(b_rgb - f_rgb)                                          # Difference
        elif mode == 9: comp = np.where(f_rgb != 0, b_rgb / (f_rgb + 1e-6), b_rgb)           # Divide
        else:           comp = f_rgb

        comp = np.clip(comp, 0.0, 1.0)

        blend_alpha = blend[..., 3:4] * opacity
        out_rgb   = b_rgb * (1.0 - blend_alpha) + comp * blend_alpha
        out_alpha = np.maximum(base[..., 3:4], blend[..., 3:4] * opacity)

        result = np.empty_like(base)
        result[..., :3]  = out_rgb
        result[..., 3:4] = out_alpha
        return result

@register_node
class MathNode(BaseNode):
    def __init__(self):
        super().__init__("Math")
        self.inputs = [None, None]
        self.add_property("Operation", 0.0, is_enum=True,
                         items=["Add", "Subtract", "Multiply", "Power", "Step (>)", "Max"])
        self.add_property("Value B", 1.0, -100, 100)

    def evaluate(self, frame, w, h):
        a = self.inputs[0].evaluate(frame, w, h) if self.inputs[0] else np.zeros((h, w, 4))
        b = self.inputs[1].evaluate(frame, w, h) if self.inputs[1] else np.full((h, w, 4), self.properties["Value B"].get_value(frame))
        op = int(self.properties["Operation"].get_value(frame))
        if op == 0: return a + b
        if op == 1: return a - b
        if op == 2: return a * b
        if op == 3: return np.power(np.abs(a), b)
        if op == 4: return (a > b).astype(np.float32)
        if op == 5: return np.maximum(a, b)
        return a

@register_node
class GradientNode(BaseNode):
    def __init__(self):
        super().__init__("Gradient Map")
        self.inputs = [None]
        self.add_property("Start R", 0, 0, 1)
        self.add_property("Start G", 0, 0, 1)
        self.add_property("Start B", 0, 0, 1)
        self.add_property("End R", 1, 0, 1)
        self.add_property("End G", 0.5, 0, 1)
        self.add_property("End B", 0.2, 0, 1)

    def evaluate(self, frame, w, h):
        fac = self.inputs[0].evaluate(frame, w, h)[..., 0] if self.inputs[0] else np.zeros((h, w))
        p = self.properties
        res = np.zeros((h, w, 4), dtype=np.float32)
        res[..., 0] = p["Start R"].get_value(frame) + (p["End R"].get_value(frame) - p["Start R"].get_value(frame)) * fac
        res[..., 1] = p["Start G"].get_value(frame) + (p["End G"].get_value(frame) - p["Start G"].get_value(frame)) * fac
        res[..., 2] = p["Start B"].get_value(frame) + (p["End B"].get_value(frame) - p["Start B"].get_value(frame)) * fac
        res[..., 3] = fac
        return res

@register_node
class ImageTextureNode(BaseNode):
    def __init__(self):
        super().__init__("Image Texture")
        self.inputs = []
        self.image_path = None
        self.image_array = None

        self.add_property("Scale X", 1.0, 0.01, 100.0)
        self.add_property("Scale Y", 1.0, 0.01, 100.0)
        self.add_property("Offset X", 0.0, -10.0, 10.0)
        self.add_property("Offset Y", 0.0, -10.0, 10.0)
        self.add_property("Tiling", 1.0, is_bool=True)

    def load_image(self, path):
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        arr = np.array(img).astype(np.float32) / 255.0
        self.image_path = path
        self.image_array = arr

    def _extra_to_dict(self):
        return {'image_path': self.image_path}

    def _extra_from_dict(self, d):
        path = d.get('image_path')
        if path and os.path.exists(path):
            self.load_image(path)

    def evaluate(self, frame, w, h):
        if self.image_array is None:
            return np.zeros((h, w, 4), dtype=np.float32)

        p = self.properties
        sx = p["Scale X"].get_value(frame)
        sy = p["Scale Y"].get_value(frame)
        ox = p["Offset X"].get_value(frame)
        oy = p["Offset Y"].get_value(frame)
        tiling = bool(p["Tiling"].get_value(frame))

        tex = self.image_array
        th, tw, _ = tex.shape

        u = np.linspace(0, sx, w) + ox
        v = np.linspace(0, sy, h) + oy
        U, V = np.meshgrid(u, v)

        if tiling:
            U = U % 1.0
            V = V % 1.0
        else:
            U = np.clip(U, 0.0, 1.0)
            V = np.clip(V, 0.0, 1.0)

        tx = (U * (tw - 1)).astype(np.int32)
        ty = (V * (th - 1)).astype(np.int32)
        return tex[ty, tx].copy()

@register_node
class ColorRampNode(BaseNode):
    INTERP_MODES = ["Linear", "Constant", "Smoothstep"]

    def __init__(self):
        super().__init__("Color Ramp")
        self.inputs = [None]
        self.add_property("Mode", 0.0, is_enum=True, items=self.INTERP_MODES)
        self.color_stops = [
            {'pos': 0.0, 'r': 0.0, 'g': 0.0, 'b': 0.0, 'a': 1.0},
            {'pos': 1.0, 'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0},
        ]

    def _sort_stops(self):
        self.color_stops.sort(key=lambda s: s['pos'])

    def add_stop(self, pos, r, g, b, a=1.0):
        pos = max(0.0, min(1.0, pos))
        self.color_stops.append({'pos': pos, 'r': r, 'g': g, 'b': b, 'a': a})
        self._sort_stops()

    def remove_stop(self, index):
        if len(self.color_stops) > 2 and 0 <= index < len(self.color_stops):
            del self.color_stops[index]

    def _extra_to_dict(self):
        return {'color_stops': self.color_stops.copy()}

    def _extra_from_dict(self, d):
        self.color_stops = d.get('color_stops', self.color_stops)

    def _get_color_at(self, fac_val, mode):
        stops = self.color_stops
        if not stops: return (0, 0, 0, 1)
        if fac_val <= stops[0]['pos']:
            s = stops[0]; return (s['r'], s['g'], s['b'], s['a'])
        if fac_val >= stops[-1]['pos']:
            s = stops[-1]; return (s['r'], s['g'], s['b'], s['a'])
        for i in range(len(stops) - 1):
            s1, s2 = stops[i], stops[i+1]
            if s1['pos'] <= fac_val <= s2['pos']:
                if mode == 1:
                    return (s1['r'], s1['g'], s1['b'], s1['a'])
                span = s2['pos'] - s1['pos']
                if span < 0.0001:
                    return (s1['r'], s1['g'], s1['b'], s1['a'])
                t = (fac_val - s1['pos']) / span
                if mode == 2:
                    t = t * t * (3.0 - 2.0 * t)
                return (
                    s1['r'] + (s2['r'] - s1['r']) * t,
                    s1['g'] + (s2['g'] - s1['g']) * t,
                    s1['b'] + (s2['b'] - s1['b']) * t,
                    s1['a'] + (s2['a'] - s1['a']) * t,
                )
        s = stops[-1]; return (s['r'], s['g'], s['b'], s['a'])

    def evaluate(self, frame, w, h):
        fac = np.clip(
            self.inputs[0].evaluate(frame, w, h)[..., 0] if self.inputs[0] else np.zeros((h, w)),
            0.0, 1.0)
        mode = int(self.properties["Mode"].get_value(frame))
        self._sort_stops()
        stops = self.color_stops
        out = np.zeros((h, w, 4), dtype=np.float32)
        if len(stops) < 2:
            if stops:
                s = stops[0]
                out[..., 0] = s['r']; out[..., 1] = s['g']
                out[..., 2] = s['b']; out[..., 3] = s['a']
            return out

        positions = np.array([s['pos'] for s in stops], dtype=np.float32)
        colors = np.array([[s['r'], s['g'], s['b'], s['a']] for s in stops], dtype=np.float32)
        idx = np.searchsorted(positions, fac, side='right') - 1
        idx = np.clip(idx, 0, len(stops) - 2)
        idx_next = idx + 1

        pos_lo = positions[idx]; pos_hi = positions[idx_next]
        col_lo = colors[idx]; col_hi = colors[idx_next]

        span = pos_hi - pos_lo
        span = np.where(span < 0.0001, 1.0, span)
        t = (fac - pos_lo) / span
        t = np.clip(t, 0.0, 1.0)

        if mode == 1:
            t = np.zeros_like(t)
        elif mode == 2:
            t = t * t * (3.0 - 2.0 * t)

        below = fac <= positions[0]
        above = fac >= positions[-1]

        t_4 = t[..., np.newaxis]
        result = col_lo + (col_hi - col_lo) * t_4

        if np.any(below):
            result[below] = colors[0]
        if np.any(above):
            result[above] = colors[-1]

        out[..., 0] = result[..., 0]; out[..., 1] = result[..., 1]
        out[..., 2] = result[..., 2]; out[..., 3] = result[..., 3]
        return out

# --- SDF SHAPES WITH TRANSFORM ---
@register_node
class CircleNode(BaseNode):
    def __init__(self):
        super().__init__("Circle SDF")
        self.inputs = [None]  # Radius input
        self.add_property("Radius", 0.4, 0, 2)
        self.add_property("Softness", 0.05, 0.001, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        rad = self.inputs[0].evaluate(frame, w, h)[..., 0] if self.inputs[0] else self.properties["Radius"].get_value(frame)
        X, Y = sdf_grid(w, h)
        px, py, rot, sx, sy = self.get_transform(frame)
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        return sdf_to_rgba(sdf_soft(sdf_circle(X, Y, rad), self.properties["Softness"].get_value(frame)))

@register_node
class BoxNode(BaseNode):
    def __init__(self):
        super().__init__("Box SDF")
        self.inputs = []
        self.add_property("Width", 0.5, 0, 2)
        self.add_property("Height", 0.3, 0, 2)
        self.add_property("Softness", 0.05, 0.001, 1)
        self.add_property("Round", 0.0, 0, 0.5)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        X, Y = sdf_grid(w, h)
        px, py, rot, sx, sy = self.get_transform(frame)
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        d = sdf_box(X, Y, p["Width"].get_value(frame), p["Height"].get_value(frame)) - p["Round"].get_value(frame)
        return sdf_to_rgba(sdf_soft(d, p["Softness"].get_value(frame)))

@register_node
class RingNode(BaseNode):
    def __init__(self):
        super().__init__("Ring SDF")
        self.inputs = []
        self.add_property("Radius", 0.5, 0, 2)
        self.add_property("Thickness", 0.05, 0.001, 0.5)
        self.add_property("Softness", 0.03, 0.001, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        X, Y = sdf_grid(w, h)
        px, py, rot, sx, sy = self.get_transform(frame)
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        return sdf_to_rgba(sdf_soft(sdf_ring(X, Y, p["Radius"].get_value(frame), p["Thickness"].get_value(frame)), p["Softness"].get_value(frame)))

@register_node
class HexagonNode(BaseNode):
    def __init__(self):
        super().__init__("Hexagon SDF")
        self.inputs = []
        self.add_property("Radius", 0.5, 0, 2)
        self.add_property("Softness", 0.05, 0.001, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        X, Y = sdf_grid(w, h)
        px, py, rot, sx, sy = self.get_transform(frame)
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        return sdf_to_rgba(sdf_soft(sdf_hexagon(X, Y, self.properties["Radius"].get_value(frame)), self.properties["Softness"].get_value(frame)))

@register_node
class StarNode(BaseNode):
    def __init__(self):
        super().__init__("Star SDF")
        self.inputs = []
        self.add_property("Radius", 0.5, 0, 2)
        self.add_property("Points", 5, 3, 12)
        self.add_property("Inner Ratio", 0.4, 0.1, 0.9)
        self.add_property("Softness", 0.05, 0.001, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        X, Y = sdf_grid(w, h)
        px, py, rot, sx, sy = self.get_transform(frame)
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        d = sdf_star(X, Y, p["Radius"].get_value(frame), int(p["Points"].get_value(frame)), p["Inner Ratio"].get_value(frame))
        return sdf_to_rgba(sdf_soft(d, p["Softness"].get_value(frame)))

# --- VECTOR SHAPES ---
@register_node
class VectorRectNode(BaseNode):
    def __init__(self):
        super().__init__("Vector Rect")
        self.inputs = [None]  # Can drive width
        self.add_property("Width", 0.6, 0.01, 2.0)
        self.add_property("Height", 0.4, 0.01, 2.0)
        self.add_property("Fill R", 1.0, 0, 1)
        self.add_property("Fill G", 1.0, 0, 1)
        self.add_property("Fill B", 1.0, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Stroke R", 0.0, 0, 1)
        self.add_property("Stroke G", 0.0, 0, 1)
        self.add_property("Stroke B", 0.0, 0, 1)
        self.add_property("Stroke A", 1.0, 0, 1)
        self.add_property("Stroke Width", 0.0, 0, 50)
        self.add_property("Corner Radius", 0.0, 0, 100)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        rect_w = self.inputs[0].evaluate(frame, w, h)[..., 0].mean() if self.inputs[0] else p["Width"].get_value(frame)
        rect_h = p["Height"].get_value(frame)
        
        fill_color = QColor.fromRgbF(
            p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
            p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        stroke_color = QColor.fromRgbF(
            p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
            p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        stroke_w = p["Stroke Width"].get_value(frame)
        corner_r = p["Corner Radius"].get_value(frame)
        
        px, py, rot, sx, sy = self.get_transform(frame)
        
        return self._render_vector(w, h, rect_w, rect_h, fill_color, stroke_color, stroke_w, corner_r, px, py, rot, sx, sy)

    def _render_vector(self, w, h, rect_w, rect_h, fill_color, stroke_color, stroke_w, corner_r, px, py, rot, sx, sy):
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Transform
        painter.translate(w/2 + px * w/2, h/2 + py * h/2)
        painter.rotate(rot)
        painter.scale(sx, sy)
        
        # Draw rect centered
        rw = rect_w * w / 2
        rh = rect_h * h / 2
        rect = QRectF(-rw/2, -rh/2, rw, rh)
        
        if fill_color.alphaF() > 0:
            painter.setBrush(QBrush(fill_color))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
        if stroke_w > 0 and stroke_color.alphaF() > 0:
            painter.setPen(QPen(stroke_color, stroke_w))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        
        if corner_r > 0:
            painter.drawRoundedRect(rect, corner_r, corner_r)
        else:
            painter.drawRect(rect)
        
        painter.end()
        
        # Convert to numpy
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        return arr

@register_node
class VectorEllipseNode(BaseNode):
    def __init__(self):
        super().__init__("Vector Ellipse")
        self.inputs = [None]  # Can drive radius
        self.add_property("Radius X", 0.4, 0.01, 2.0)
        self.add_property("Radius Y", 0.4, 0.01, 2.0)
        self.add_property("Fill R", 1.0, 0, 1)
        self.add_property("Fill G", 1.0, 0, 1)
        self.add_property("Fill B", 1.0, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Stroke R", 0.0, 0, 1)
        self.add_property("Stroke G", 0.0, 0, 1)
        self.add_property("Stroke B", 0.0, 0, 1)
        self.add_property("Stroke A", 1.0, 0, 1)
        self.add_property("Stroke Width", 0.0, 0, 50)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        rx = self.inputs[0].evaluate(frame, w, h)[..., 0].mean() if self.inputs[0] else p["Radius X"].get_value(frame)
        ry = p["Radius Y"].get_value(frame)
        
        fill_color = QColor.fromRgbF(
            p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
            p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        stroke_color = QColor.fromRgbF(
            p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
            p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        stroke_w = p["Stroke Width"].get_value(frame)
        
        px, py, rot, sx, sy = self.get_transform(frame)
        
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.translate(w/2 + px * w/2, h/2 + py * h/2)
        painter.rotate(rot)
        painter.scale(sx, sy)
        
        ellipse_w = rx * w
        ellipse_h = ry * h
        rect = QRectF(-ellipse_w/2, -ellipse_h/2, ellipse_w, ellipse_h)
        
        if fill_color.alphaF() > 0:
            painter.setBrush(QBrush(fill_color))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
        if stroke_w > 0 and stroke_color.alphaF() > 0:
            painter.setPen(QPen(stroke_color, stroke_w))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        
        painter.drawEllipse(rect)
        painter.end()
        
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        return arr

@register_node
class VectorPolygonNode(BaseNode):
    def __init__(self):
        super().__init__("Vector Polygon")
        self.inputs = [None]  # Can drive radius
        self.add_property("Radius", 0.4, 0.01, 2.0)
        self.add_property("Sides", 6, 3, 32)
        self.add_property("Fill R", 1.0, 0, 1)
        self.add_property("Fill G", 1.0, 0, 1)
        self.add_property("Fill B", 1.0, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Stroke R", 0.0, 0, 1)
        self.add_property("Stroke G", 0.0, 0, 1)
        self.add_property("Stroke B", 0.0, 0, 1)
        self.add_property("Stroke A", 1.0, 0, 1)
        self.add_property("Stroke Width", 0.0, 0, 50)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        radius = self.inputs[0].evaluate(frame, w, h)[..., 0].mean() if self.inputs[0] else p["Radius"].get_value(frame)
        sides = int(p["Sides"].get_value(frame))
        
        fill_color = QColor.fromRgbF(
            p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
            p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        stroke_color = QColor.fromRgbF(
            p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
            p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        stroke_w = p["Stroke Width"].get_value(frame)
        
        px, py, rot, sx, sy = self.get_transform(frame)
        
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.translate(w/2 + px * w/2, h/2 + py * h/2)
        painter.rotate(rot)
        painter.scale(sx, sy)
        
        # Build polygon
        r = radius * min(w, h) / 2
        points = []
        for i in range(sides):
            angle = (2 * np.pi * i / sides) - np.pi/2
            points.append(QPointF(r * np.cos(angle), r * np.sin(angle)))
        polygon = QPolygonF(points)
        
        if fill_color.alphaF() > 0:
            painter.setBrush(QBrush(fill_color))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
        if stroke_w > 0 and stroke_color.alphaF() > 0:
            painter.setPen(QPen(stroke_color, stroke_w))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        
        painter.drawPolygon(polygon)
        painter.end()
        
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        return arr

@register_node
class VectorLineNode(BaseNode):
    def __init__(self):
        super().__init__("Vector Line")
        self.inputs = []
        self.add_property("X1", -0.3, -2, 2)
        self.add_property("Y1", 0.0, -2, 2)
        self.add_property("X2", 0.3, -2, 2)
        self.add_property("Y2", 0.0, -2, 2)
        self.add_property("Stroke R", 1.0, 0, 1)
        self.add_property("Stroke G", 1.0, 0, 1)
        self.add_property("Stroke B", 1.0, 0, 1)
        self.add_property("Stroke A", 1.0, 0, 1)
        self.add_property("Stroke Width", 2.0, 0.5, 50)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        x1, y1 = p["X1"].get_value(frame), p["Y1"].get_value(frame)
        x2, y2 = p["X2"].get_value(frame), p["Y2"].get_value(frame)
        
        stroke_color = QColor.fromRgbF(
            p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
            p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        stroke_w = p["Stroke Width"].get_value(frame)
        
        px, py, rot, sx, sy = self.get_transform(frame)
        
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.translate(w/2 + px * w/2, h/2 + py * h/2)
        painter.rotate(rot)
        painter.scale(sx, sy)
        
        painter.setPen(QPen(stroke_color, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(x1 * w/2, y1 * h/2), QPointF(x2 * w/2, y2 * h/2))
        painter.end()
        
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        return arr

# --- TEXT NODE ---
@register_node
class TextNode(BaseNode):
    def __init__(self):
        super().__init__("Text")
        self.inputs = [None]  # Support for image texture fill
        self.add_property("Text", "Hello", is_string=True)
        self.add_property("Font", "Arial", is_string=True)
        self.add_property("Size", 48, 8, 500)
        self.add_property("Vertical", 0.0, is_bool=True)
        self.add_property("Fill R", 1.0, 0, 1)
        self.add_property("Fill G", 1.0, 0, 1)
        self.add_property("Fill B", 1.0, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Stroke R", 0.0, 0, 1)
        self.add_property("Stroke G", 0.0, 0, 1)
        self.add_property("Stroke B", 0.0, 0, 1)
        self.add_property("Stroke A", 0.0, 0, 1)
        self.add_property("Stroke Width", 0.0, 0, 20)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        text = str(p["Text"].get_value(frame))
        font_name = str(p["Font"].get_value(frame))
        font_size = int(p["Size"].get_value(frame))
        vertical = bool(p["Vertical"].get_value(frame)) if "Vertical" in p else False
        
        fill_color = QColor.fromRgbF(
            p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
            p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        stroke_color = QColor.fromRgbF(
            p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
            p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        stroke_w = p["Stroke Width"].get_value(frame)
        
        px, py, rot, sx, sy = self.get_transform(frame)
        
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        scale_factor = w / PROJECT.width if PROJECT.width > 0 else 1.0
        font = QFont(font_name, max(1, int(font_size * scale_factor)))
        painter.setFont(font)
        
        fm = painter.fontMetrics()
        
        # Determine lines for standard/vertical typing
        if vertical:
            lines = list(text.replace('\n', ''))
        else:
            lines = text.split('\n')
            
        line_spacing = fm.lineSpacing()
        total_height = fm.height() + line_spacing * max(0, len(lines) - 1)
        start_y = -total_height / 2 + fm.ascent()
        
        # Build text path (enables multi-line, vertical layout, and texture fill masking)
        path = QPainterPath()
        for i, line in enumerate(lines):
            line_width = fm.horizontalAdvance(line)
            path.addText(-line_width / 2, start_y + i * line_spacing, font, line)
        
        painter.translate(w/2 + px * w/2, h/2 + py * h/2)
        painter.rotate(rot)
        painter.scale(sx, sy)
        
        # Draw stroke first
        if stroke_w > 0 and stroke_color.alphaF() > 0:
            painter.setPen(QPen(stroke_color, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        
        # Draw fill
        if self.inputs[0]:
            fill_arr = self.inputs[0].evaluate(frame, w, h)
            fill_arr = np.clip(fill_arr * 255, 0, 255).astype(np.uint8)
            if not fill_arr.flags['C_CONTIGUOUS']:
                fill_arr = np.ascontiguousarray(fill_arr)
            fill_img = QImage(fill_arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            
            brush = QBrush(QPixmap.fromImage(fill_img))
            # Inverse transform so the texture inherently maps 1:1 with canvas space over the text mask
            brush.setTransform(painter.transform().inverted()[0])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(brush)
            painter.drawPath(path)
        elif fill_color.alphaF() > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawPath(path)
        
        painter.end()
        
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0
        return arr

# --- TILE CANVAS NODE ---
@register_node
class TileCanvasNode(BaseNode):
    """
    Tile-aware atlas builder.

    Renders the upstream graph once per cell at Tile Size, optionally varies
    seed-based nodes per cell, then stamps the results into a larger atlas.
    """

    MODES = ["Top-Down", "Platformer"]
    INPUT_MODES = ["Repeat Per Tile", "Slice Atlas"]

    def __init__(self):
        super().__init__("Tile Canvas")
        self.inputs = [None]
        self.add_property("Mode", 0, is_enum=True, items=self.MODES)
        self.add_property("Input Mode", 0, is_enum=True, items=self.INPUT_MODES)
        self.add_property("Tile Size", 48, 8, 256)
        self.add_property("Columns", 8, 1, 64)
        self.add_property("Rows", 4, 1, 64)
        self.add_property("Cell Variation", 0.0, 0.0, 1.0)
        self.add_property("Seamless", 1.0, is_bool=True)
        self.add_property("Seamless Blend", 0.15, 0.01, 0.5)
        self.add_property("Band Width", 4, 1, 64)
        self.add_property("Band R", 1.0, 0.0, 1.0)
        self.add_property("Band G", 1.0, 0.0, 1.0)
        self.add_property("Band B", 1.0, 0.0, 1.0)
        self.add_property("Band Opacity", 0.6, 0.0, 1.0)
        self.add_property("Show Grid", 1.0, is_bool=True)

    def tile_size(self, frame=0):
        return max(1, int(self.properties["Tile Size"].get_value(frame)))

    def columns(self, frame=0):
        return max(1, int(self.properties["Columns"].get_value(frame)))

    def rows(self, frame=0):
        return max(1, int(self.properties["Rows"].get_value(frame)))

    def atlas_width(self, frame=0):
        return self.tile_size(frame) * self.columns(frame)

    def atlas_height(self, frame=0):
        return self.tile_size(frame) * self.rows(frame)

    def _apply_seamless(self, cell, blend_frac, edges=(True, True, True, True)):
        h, w = cell.shape[:2]
        result = cell.copy()
        bh = max(1, int(h * blend_frac))
        bw = max(1, int(w * blend_frac))
        top, bottom, left, right = edges

        if top or bottom:
            for y in range(bh):
                t = y / bh
                alpha_edge = 1.0 - t
                alpha_local = t
                if top:
                    result[y, :] = (
                        alpha_local * cell[y, :] + alpha_edge * cell[h - bh + y, :]
                    )
                if bottom:
                    result[h - bh + y, :] = (
                        alpha_local * cell[h - bh + y, :] + alpha_edge * cell[y, :]
                    )

        if left or right:
            for x in range(bw):
                t = x / bw
                alpha_edge = 1.0 - t
                alpha_local = t
                if left:
                    result[:, x] = (
                        alpha_local * result[:, x] + alpha_edge * result[:, w - bw + x]
                    )
                if right:
                    result[:, w - bw + x] = (
                        alpha_local * result[:, w - bw + x] + alpha_edge * result[:, x]
                    )

        return np.clip(result, 0.0, 1.0)

    def _apply_edge_band(self, cell, band_width, r, g, b, opacity):
        result = cell.copy()
        h = cell.shape[0]
        bw = max(1, min(band_width, h))
        band_color = np.array([r, g, b, 1.0], dtype=np.float32)
        for y in range(bw):
            t = 1.0 - (y / bw)
            alpha = opacity * t
            result[y, :] = result[y, :] * (1.0 - alpha) + band_color * alpha
        return np.clip(result, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        global TILE_SEED_OFFSET

        p = self.properties
        mode = int(p["Mode"].get_value(frame))
        input_mode = int(p["Input Mode"].get_value(frame))
        tile_sz = self.tile_size(frame)
        cols = self.columns(frame)
        rows_n = self.rows(frame)
        variation = p["Cell Variation"].get_value(frame)
        seamless = bool(p["Seamless"].get_value(frame))
        blend_frac = p["Seamless Blend"].get_value(frame)
        band_width = max(1, int(p["Band Width"].get_value(frame)))
        band_r = p["Band R"].get_value(frame)
        band_g = p["Band G"].get_value(frame)
        band_b = p["Band B"].get_value(frame)
        band_opacity = p["Band Opacity"].get_value(frame)

        atlas = np.zeros((rows_n * tile_sz, cols * tile_sz, 4), dtype=np.float32)

        if self.inputs[0] is None:
            atlas[..., 3] = 1.0
            return atlas

        edges = (True, True, True, True) if mode == 0 else (False, True, True, True)
        total_cells = cols * rows_n
        source_atlas = None

        if input_mode == 1:
            TILE_SEED_OFFSET = 0
            source_atlas = self.inputs[0].evaluate(frame, cols * tile_sz, rows_n * tile_sz).copy()

        for cell_idx in range(total_cells):
            col = cell_idx % cols
            row = cell_idx // cols

            y0 = row * tile_sz
            x0 = col * tile_sz

            if input_mode == 1 and source_atlas is not None:
                TILE_SEED_OFFSET = 0
                cell = source_atlas[y0:y0 + tile_sz, x0:x0 + tile_sz].copy()
            else:
                TILE_SEED_OFFSET = int(cell_idx * variation * 100) if variation > 0.001 else 0
                cell = self.inputs[0].evaluate(frame, tile_sz, tile_sz).copy()

            if seamless:
                cell = self._apply_seamless(cell, blend_frac, edges)

            if mode == 1:
                cell = self._apply_edge_band(
                    cell, band_width, band_r, band_g, band_b, band_opacity
                )

            atlas[y0:y0 + tile_sz, x0:x0 + tile_sz] = cell

        TILE_SEED_OFFSET = 0
        return np.clip(atlas, 0.0, 1.0)

def build_field_coords(frame, w, h, scale, offset_x, offset_y, evolution, loop, warp_strength, seed, seamless_tile):
    asp = w / max(h, 1)
    X, Y = np.meshgrid(np.linspace(0, scale * asp, w), np.linspace(0, scale, h))
    X += offset_x
    Y += offset_y
    if seamless_tile:
        X = X % scale
        Y = Y % scale
    if warp_strength > 0.001:
        X, Y = domain_warp(X, Y, warp_strength, seed)
    return (X, Y) + temporal_components(frame, PROJECT.duration, evolution, loop)

# --- NOISE NODE ---
@register_node
class NoiseNode(BaseNode):
    NTYPES = ["Value", "Perlin", "Simplex"]
    DTYPES = ["Round", "Diamond", "Square"]

    def __init__(self):
        super().__init__("Noise")
        self.inputs = []
        self.add_property("Type", 1, is_enum=True, items=self.NTYPES)
        self.add_property("Scale", 5, 0.1, 100)
        self.add_property("Seed", 0, 0, 9999)
        self.add_property("Octaves", 3, 1, 8)
        self.add_property("Lacunarity", 2, 1, 4)
        self.add_property("Persistence", 0.5, 0, 1)
        self.add_property("Offset X", 0, -1000, 1000)
        self.add_property("Offset Y", 0, -1000, 1000)
        self.add_property("Evolution", 0, 0, 100)
        self.add_property("Temporal Loop", 0, is_bool=True)
        self.add_property("Warp Strength", 0, 0, 10)
        self.add_property("Seamless Tile", 0, is_bool=True)
        self.add_property("Invert", 0, is_bool=True)

    def evaluate(self, frame, w, h):
        global TILE_SEED_OFFSET
        p = self.properties
        nt = int(p["Type"].get_value(frame))
        sc = max(p["Scale"].get_value(frame), 0.1)
        sd = int(p["Seed"].get_value(frame)) + TILE_SEED_OFFSET
        oc = int(np.clip(p["Octaves"].get_value(frame), 1, 8))
        la = p["Lacunarity"].get_value(frame)
        pe = p["Persistence"].get_value(frame)
        ox = p["Offset X"].get_value(frame)
        oy = p["Offset Y"].get_value(frame)
        ev = p["Evolution"].get_value(frame)
        lp = bool(p["Temporal Loop"].get_value(frame))
        wa = p["Warp Strength"].get_value(frame)
        ti = bool(p["Seamless Tile"].get_value(frame))
        inv = bool(p["Invert"].get_value(frame))

        coords = build_field_coords(frame, w, h, sc, ox, oy, ev, lp, wa, sd, ti)
        temporal_dims = len(coords) - 2
        fns = [
            [value_noise_2d, value_noise_3d, value_noise_4d],
            [perlin_noise_2d, perlin_noise_3d, perlin_noise_4d],
            [simplex_noise_2d, simplex_noise_3d, simplex_noise_4d],
        ]
        fn = fns[nt][min(temporal_dims, 2)]
        noise = fbm_noise(coords, fn, oc, la, pe, sd)
        noise = np.clip(noise, 0.0, 1.0)
        if inv:
            noise = 1.0 - noise
        arr = np.zeros((h, w, 4), dtype=np.float32)
        arr[..., 0] = noise; arr[..., 1] = noise; arr[..., 2] = noise; arr[..., 3] = 1.0
        return arr

@register_node
class VoronoiNode(BaseNode):
    OUTPUTS = ["F1", "F2", "Edge", "Cell ID", "Cells", "Borders"]
    DTYPES = NoiseNode.DTYPES

    def __init__(self):
        super().__init__("Voronoi")
        self.inputs = []
        self.add_property("Output", 2, is_enum=True, items=self.OUTPUTS)
        self.add_property("Scale", 5, 0.1, 100)
        self.add_property("Seed", 0, 0, 9999)
        self.add_property("Octaves", 3, 1, 8)
        self.add_property("Lacunarity", 2, 1, 4)
        self.add_property("Persistence", 0.5, 0, 1)
        self.add_property("Jitter", 1, 0, 1)
        self.add_property("Distance", 0, is_enum=True, items=self.DTYPES)
        self.add_property("Offset X", 0, -1000, 1000)
        self.add_property("Offset Y", 0, -1000, 1000)
        self.add_property("Evolution", 0, 0, 100)
        self.add_property("Temporal Loop", 0, is_bool=True)
        self.add_property("Warp Strength", 0, 0, 10)
        self.add_property("Seamless Tile", 0, is_bool=True)
        self.add_property("Invert", 0, is_bool=True)
        self.add_property("Border Width", 0.08, 0.001, 1.0)
        self.add_property("Softness", 0.03, 0.0, 1.0)
        self.add_property("Variation", 1.0, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        global TILE_SEED_OFFSET
        p = self.properties
        mode = int(p["Output"].get_value(frame))
        sc = max(p["Scale"].get_value(frame), 0.1)
        sd = int(p["Seed"].get_value(frame)) + TILE_SEED_OFFSET
        oc = int(np.clip(p["Octaves"].get_value(frame), 1, 8))
        la = p["Lacunarity"].get_value(frame)
        pe = p["Persistence"].get_value(frame)
        ji = np.clip(p["Jitter"].get_value(frame), 0, 1)
        dt = int(p["Distance"].get_value(frame))
        ox = p["Offset X"].get_value(frame)
        oy = p["Offset Y"].get_value(frame)
        ev = p["Evolution"].get_value(frame)
        lp = bool(p["Temporal Loop"].get_value(frame))
        wa = p["Warp Strength"].get_value(frame)
        ti = bool(p["Seamless Tile"].get_value(frame))
        inv = bool(p["Invert"].get_value(frame))
        border_width = p["Border Width"].get_value(frame)
        softness = p["Softness"].get_value(frame)
        variation = p["Variation"].get_value(frame)

        coords = build_field_coords(frame, w, h, sc, ox, oy, ev, lp, wa, sd, ti)
        ck = dict(jitter=ji, dist_type=dt)

        if mode <= 2:
            field = fbm_noise(
                coords,
                lambda *sample_coords, seed=0: cellular_noise_nd(*sample_coords, seed=seed, mode=mode, **ck),
                oc, la, pe, sd
            )
        else:
            f1, f2, cid = cellular_info_nd(*coords, seed=sd, **ck)
            edge_norm = 1.2 * np.sqrt(max(len(coords), 2) / 2.0)
            edge = np.clip((f2 - f1) / edge_norm, 0.0, 1.0)
            if mode == 3:
                field = cid
            elif mode == 4:
                field = np.clip((1.0 - variation) + (cid * variation), 0.0, 1.0)
            else:
                field = 1.0 - _smoothstep_edges(border_width, border_width + softness, edge)

        field = np.clip(field, 0.0, 1.0)
        if inv:
            field = 1.0 - field
        arr = np.zeros((h, w, 4), dtype=np.float32)
        arr[..., 0] = field; arr[..., 1] = field; arr[..., 2] = field; arr[..., 3] = 1.0
        return arr

# --- RANDOM SELECT NODE ---
@register_node
class RandomSelectNode(BaseNode):
    def __init__(self):
        super().__init__("Random Select")
        self.inputs = [None, None, None, None]  # 4 inputs (simpler)
        self.add_property("Seed", 0, 0, 9999)

    def get_random_input(self, seed, particle_index=0):
        """Get a random connected input based on seed and particle index"""
        connected = [(i, inp) for i, inp in enumerate(self.inputs) if inp is not None]
        if not connected:
            return None
        idx = int(deterministic_random(seed, particle_index, 12345) * len(connected)) % len(connected)
        return connected[idx][1]

    def evaluate(self, frame, w, h):
        connected = [inp for inp in self.inputs if inp is not None]
        if not connected:
            return np.zeros((h, w, 4), dtype=np.float32)
        seed = int(self.properties["Seed"].get_value(frame))
        idx = int(deterministic_random(seed, frame, 0) * len(connected)) % len(connected)
        return connected[idx].evaluate(frame, w, h)

# --- SIMPLE PARTICLE EMITTER NODE ---
@register_node
class ParticleEmitterNode(BaseNode):
    MODES = ["Burst", "Continuous"]
    SPRITES = ["(Use Input)", "Circle", "Square", "Star", "Spark"]
    BLENDS = ["Normal", "Additive"]

    def __init__(self):
        super().__init__("Particles")
        self.inputs = [None]  # Sprite input
        
        # Basic
        self.add_property("Mode", 0, is_enum=True, items=self.MODES)
        self.add_property("Amount", 20, 1, 200)
        self.add_property("Lifetime", 30, 5, 300)
        
        # Movement
        self.add_property("Direction", 270, 0, 360)  # 270 = up
        self.add_property("Spread", 45, 0, 360)
        self.add_property("Speed", 150, 0, 500)
        self.add_property("Gravity", 100, -300, 300)
        
        # Appearance
        self.add_property("Size", 32, 8, 128)
        self.add_property("Fade Out", 1.0, is_bool=True)
        self.add_property("Shrink", 1.0, is_bool=True)
        self.add_property("Blend", 0, is_enum=True, items=self.BLENDS)
        
        # Built-in sprite
        self.add_property("Built-in", 0, is_enum=True, items=self.SPRITES)
        self.add_property("Color R", 1.0, 0, 1)
        self.add_property("Color G", 0.8, 0, 1)
        self.add_property("Color B", 0.2, 0, 1)
        
        # Position
        self.add_property("Emitter X", 480, 0, 1920)
        self.add_property("Emitter Y", 400, 0, 1080)
        
        # Seed for randomness
        self.add_property("Seed", 42, 0, 9999)

    def _make_builtin_sprite(self, sprite_type, size, r, g, b):
        """Generate a built-in sprite"""
        arr = np.zeros((size, size, 4), dtype=np.float32)
        cx, cy = size / 2, size / 2
        
        Y, X = np.ogrid[:size, :size]
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        
        if sprite_type == 1:  # Circle
            mask = dist < (size * 0.45)
            edge = (dist >= size * 0.35) & (dist < size * 0.45)
            arr[mask, 0] = r
            arr[mask, 1] = g
            arr[mask, 2] = b
            arr[mask, 3] = 1.0
            # Soft edge
            arr[edge, 3] = 1.0 - (dist[edge] - size * 0.35) / (size * 0.1)
            
        elif sprite_type == 2:  # Square
            margin = size * 0.15
            mask = (X >= margin) & (X < size - margin) & (Y >= margin) & (Y < size - margin)
            arr[mask, 0] = r
            arr[mask, 1] = g
            arr[mask, 2] = b
            arr[mask, 3] = 1.0
            
        elif sprite_type == 3:  # Star
            angle = np.arctan2(Y - cy, X - cx)
            star_r = size * 0.4 * (0.5 + 0.5 * np.cos(5 * angle))
            mask = dist < star_r
            arr[mask, 0] = r
            arr[mask, 1] = g
            arr[mask, 2] = b
            arr[mask, 3] = 1.0
            
        elif sprite_type == 4:  # Spark (soft glow)
            falloff = 1.0 - np.clip(dist / (size * 0.4), 0, 1)
            falloff = falloff ** 2  # Sharper falloff
            arr[..., 0] = r * falloff
            arr[..., 1] = g * falloff
            arr[..., 2] = b * falloff
            arr[..., 3] = falloff
        
        return arr

    def evaluate(self, frame, w, h):
        p = self.properties
        
        mode = int(p["Mode"].get_value(frame))
        amount = int(p["Amount"].get_value(frame))
        lifetime = int(p["Lifetime"].get_value(frame))
        
        direction = p["Direction"].get_value(frame)
        spread = p["Spread"].get_value(frame)
        speed = p["Speed"].get_value(frame)
        gravity = p["Gravity"].get_value(frame)
        
        size = int(p["Size"].get_value(frame))
        fade_out = bool(p["Fade Out"].get_value(frame))
        shrink = bool(p["Shrink"].get_value(frame))
        blend_mode = int(p["Blend"].get_value(frame))
        
        builtin = int(p["Built-in"].get_value(frame))
        color_r = p["Color R"].get_value(frame)
        color_g = p["Color G"].get_value(frame)
        color_b = p["Color B"].get_value(frame)
        
        emitter_x = p["Emitter X"].get_value(frame)
        emitter_y = p["Emitter Y"].get_value(frame)
        seed = int(p["Seed"].get_value(frame))
        
        # Scale for preview
        scale_x = w / PROJECT.width
        scale_y = h / PROJECT.height
        
        # Get or create sprite
        if builtin > 0:
            sprite_img = self._make_builtin_sprite(builtin, size, color_r, color_g, color_b)
        elif self.inputs[0]:
            sprite_img = self.inputs[0].evaluate(frame, size, size)
        else:
            # Default: white circle
            sprite_img = self._make_builtin_sprite(1, size, 1.0, 1.0, 1.0)
        
        output = np.zeros((h, w, 4), dtype=np.float32)
        
        # Generate particles
        particles = []
        
        if mode == 0:  # Burst
            # All particles spawn at frame 0
            for i in range(amount):
                spawn_frame = 0
                age = frame - spawn_frame
                if 0 <= age < lifetime:
                    particles.append((i, age, lifetime))
        else:  # Continuous
            # Spread spawns across time
            spawn_interval = max(1, lifetime / amount)
            for i in range(amount):
                spawn_frame = int(i * spawn_interval) % lifetime
                # Wrap around for looping
                age = (frame - spawn_frame) % lifetime
                if age >= 0:
                    particles.append((i, age, lifetime))
        
        # Render each particle
        for p_idx, age, p_lifetime in particles:
            life_t = age / max(p_lifetime - 1, 1)  # 0 to 1
            
            # Direction with spread
            p_dir = direction + deterministic_random_range(seed, p_idx, 0, -spread/2, spread/2)
            p_dir_rad = np.radians(p_dir)
            
            # Speed with slight variation
            p_speed = speed * deterministic_random_range(seed, p_idx, 1, 0.8, 1.2)
            
            # Initial velocity
            vx = p_speed * np.cos(p_dir_rad)
            vy = p_speed * np.sin(p_dir_rad)
            
            # Simulate position
            # Using simple physics: pos = v*t + 0.5*g*t^2
            t = age / PROJECT.fps
            px = vx * t
            py = vy * t + 0.5 * gravity * t * t
            
            final_x = emitter_x + px
            final_y = emitter_y + py
            
            # Scale
            p_scale = 1.0
            if shrink:
                p_scale = 1.0 - life_t * 0.7  # Shrink to 30% of original
            
            # Alpha
            p_alpha = 1.0
            if fade_out:
                p_alpha = 1.0 - life_t
            
            # Composite
            self._composite_sprite(
                output, sprite_img,
                final_x * scale_x, final_y * scale_y,
                p_scale, p_alpha, blend_mode
            )
        
        return output

    def _composite_sprite(self, output, sprite, cx, cy, scale, alpha, blend_mode):
        """Simple sprite compositing without rotation"""
        h, w, _ = output.shape
        sh, sw, _ = sprite.shape
        
        # Scaled size
        scaled_w = int(sw * scale)
        scaled_h = int(sh * scale)
        
        if scaled_w < 1 or scaled_h < 1:
            return
        
        # Bounds
        x1 = int(cx - scaled_w / 2)
        y1 = int(cy - scaled_h / 2)
        x2 = x1 + scaled_w
        y2 = y1 + scaled_h
        
        # Clip to output
        src_x1 = max(0, -x1)
        src_y1 = max(0, -y1)
        src_x2 = sw - max(0, x2 - w)
        src_y2 = sh - max(0, y2 - h)
        
        dst_x1 = max(0, x1)
        dst_y1 = max(0, y1)
        dst_x2 = min(w, x2)
        dst_y2 = min(h, y2)
        
        if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
            return
        
        # Sample sprite with scaling
        if scale != 1.0:
            # Create scaled coordinates
            src_h = src_y2 - src_y1
            src_w = src_x2 - src_x1
            dst_h = dst_y2 - dst_y1
            dst_w = dst_x2 - dst_x1
            
            # Map destination pixels to source
            y_indices = np.linspace(src_y1, src_y2 - 1, dst_h).astype(np.int32)
            x_indices = np.linspace(src_x1, src_x2 - 1, dst_w).astype(np.int32)
            
            y_indices = np.clip(y_indices, 0, sh - 1)
            x_indices = np.clip(x_indices, 0, sw - 1)
            
            sampled = sprite[y_indices[:, np.newaxis], x_indices[np.newaxis, :]]
        else:
            sampled = sprite[src_y1:src_y2, src_x1:src_x2]
        
        # Apply alpha
        sampled = sampled.copy()
        sampled[..., 3] *= alpha
        
        out_region = output[dst_y1:dst_y2, dst_x1:dst_x2]
        
        # Handle size mismatch
        min_h = min(out_region.shape[0], sampled.shape[0])
        min_w = min(out_region.shape[1], sampled.shape[1])
        
        if min_h <= 0 or min_w <= 0:
            return
            
        out_region = out_region[:min_h, :min_w]
        sampled = sampled[:min_h, :min_w]
        
        src_alpha = sampled[..., 3:4]
        
        if blend_mode == 0:  # Normal
            output[dst_y1:dst_y1+min_h, dst_x1:dst_x1+min_w, :3] = (
                out_region[..., :3] * (1 - src_alpha) + sampled[..., :3] * src_alpha
            )
            output[dst_y1:dst_y1+min_h, dst_x1:dst_x1+min_w, 3:4] = np.maximum(
                out_region[..., 3:4], src_alpha
            )
        else:  # Additive
            output[dst_y1:dst_y1+min_h, dst_x1:dst_x1+min_w, :3] = np.clip(
                out_region[..., :3] + sampled[..., :3] * src_alpha, 0, 1
            )
            output[dst_y1:dst_y1+min_h, dst_x1:dst_x1+min_w, 3:4] = np.maximum(
                out_region[..., 3:4], src_alpha
            )
#__________________________
# ==========================================
# NEW NODES FOR ASSET GENERATION
# ==========================================

@register_node
class BrickPatternNode(BaseNode):
    def __init__(self):
        super().__init__("Brick / Tile")
        self.inputs = []
        self.add_property("Scale X", 4.0, 1.0, 50.0)
        self.add_property("Scale Y", 4.0, 1.0, 50.0)
        self.add_property("Mortar Size", 0.05, 0.0, 0.5)
        self.add_property("Offset (Stagger)", 0.5, 0.0, 1.0)
        self.add_property("Bevel", 0.0, 0.0, 1.0)
        
        # Colors
        self.add_property("Brick R", 0.8, 0, 1)
        self.add_property("Brick G", 0.4, 0, 1)
        self.add_property("Brick B", 0.3, 0, 1)
        self.add_property("Mortar R", 0.2, 0, 1)
        self.add_property("Mortar G", 0.2, 0, 1)
        self.add_property("Mortar B", 0.2, 0, 1)

    def evaluate(self, frame, w, h):
        p = self.properties
        sx = p["Scale X"].get_value(frame)
        sy = p["Scale Y"].get_value(frame)
        ms = p["Mortar Size"].get_value(frame)
        st = p["Offset (Stagger)"].get_value(frame)
        
        # Grid Setup
        asp = w / h
        x = np.linspace(0, sx * asp, w)
        y = np.linspace(0, sy, h)
        X, Y = np.meshgrid(x, y)
        
        # Row identification
        row_idx = np.floor(Y)
        
        # Stagger X based on row parity
        X_shifted = X + (row_idx % 2) * st
        
        # Local Cell Coordinates (0.0 to 1.0)
        u = X_shifted % 1.0
        v = Y % 1.0
        
        # Distance to center of cell (0.5, 0.5) for Bevel/Mortar
        # Simple Box SDF approach logic
        # Distance to edges:
        d_x = np.abs(u - 0.5) * 2.0  # 0 center -> 1 edge
        d_y = np.abs(v - 0.5) * 2.0
        dist = np.maximum(d_x, d_y)
        
        # Mortar Mask
        # If dist > (1.0 - mortar_size), it's mortar
        is_mortar = dist > (1.0 - ms)
        
        # Colors
        br = p["Brick R"].get_value(frame)
        bg = p["Brick G"].get_value(frame)
        bb = p["Brick B"].get_value(frame)
        
        mr = p["Mortar R"].get_value(frame)
        mg = p["Mortar G"].get_value(frame)
        mb = p["Mortar B"].get_value(frame)
        
        out = np.zeros((h, w, 4), dtype=np.float32)
        
        # Fill Brick
        out[..., 0] = np.where(is_mortar, mr, br)
        out[..., 1] = np.where(is_mortar, mg, bg)
        out[..., 2] = np.where(is_mortar, mb, bb)
        out[..., 3] = 1.0
        
        return out

@register_node
class TileablePatternNode(BaseNode):
    def __init__(self):
        super().__init__("Tileable Patterns")
        self.inputs = [None, None, None]
        self.input_names = ["UV Warp", "Mask", "Input Texture"]

        # --- 1. CORE TILE STRUCTURES ---
        layouts = ["Grid", "Brick", "Half-Drop", "Mirror (Ogee)", "Hex Stagger", "Polar Fold"]
        self.add_property("Layout", 0.0, 0.0, len(layouts)-1, is_enum=True, items=layouts)
        self.add_property("Repeat X", 4.0, 0.1, 100.0)
        self.add_property("Repeat Y", 4.0, 0.1, 100.0)
        self.add_property("Offset X", 0.0, -10.0, 10.0)
        self.add_property("Offset Y", 0.0, -10.0, 10.0)
        self.add_property("Warp Strength", 0.2, 0.0, 2.0)

        # --- 2. SHAPES & GEOMETRY ---
        shapes = ["Circle", "Square", "Stripe V", "Cross", "Cellular (Voronoi)",
                  "Checkerboard", "Diagonal Stripes", "Sine Wave", "Chevron/ZigZag",
                  "N-Point Star", "Value Noise", "Input Texture"]
        self.add_property("Shape", 0.0, 0.0, len(shapes)-1, is_enum=True, items=shapes)

        # --- 3. ADVANCED CONTROLS ---
        self.add_property("Thickness/Size", 0.8, 0.0, 2.0)
        self.add_property("Softness", 0.02, 0.0, 1.0)
        self.add_property("Symmetry Points", 6.0, 3.0, 16.0)
        self.add_property("Jitter", 1.0, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        # Fetch params
        layout = int(self.properties["Layout"].get_value(frame))
        rep_x = self.properties["Repeat X"].get_value(frame)
        rep_y = self.properties["Repeat Y"].get_value(frame)
        off_x = self.properties["Offset X"].get_value(frame)
        off_y = self.properties["Offset Y"].get_value(frame)
        warp = self.properties["Warp Strength"].get_value(frame)

        shape_type = int(self.properties["Shape"].get_value(frame))
        size = self.properties["Thickness/Size"].get_value(frame)
        softness = self.properties["Softness"].get_value(frame)
        symmetry = np.floor(self.properties["Symmetry Points"].get_value(frame))
        jitter = self.properties["Jitter"].get_value(frame)

        # Generate base normalized UVs
        x = np.linspace(0, 1, w, dtype=np.float32)
        y = np.linspace(0, 1, h, dtype=np.float32)
        U, V = np.meshgrid(x, y)

        # Apply External UV Warping (Organic wood/marble patterns)
        if self.inputs[0]:
            warp_map = self.inputs[0].evaluate(frame, w, h)
            U += (warp_map[..., 0] - 0.5) * warp
            V += (warp_map[..., 1] - 0.5) * warp

        # Apply Scale & Offset
        U = (U * rep_x) + off_x
        V = (V * rep_y) + off_y

        # ==========================================
        # PHASE 1: CORE TILING LAYOUTS (UV MUTATION)
        # ==========================================
        if layout == 1:   # BRICK
            U += (np.floor(V) % 2) * 0.5
        elif layout == 2: # HALF-DROP
            V += (np.floor(U) % 2) * 0.5
        elif layout == 4: # HEX STAGGER
            V *= 1.1547
            U += (np.floor(V) % 2) * 0.5

        # Local Tile UVs
        if layout == 3: # MIRROR / OGEE REPEAT
            cell_U = np.abs((U % 2.0) - 1.0)
            cell_V = np.abs((V % 2.0) - 1.0)
        else:
            cell_U = U % 1.0
            cell_V = V % 1.0

        # Center coordinates for SDF math (-0.5 to 0.5)
        cx = cell_U - 0.5
        cy = cell_V - 0.5

        # POLAR KALEIDOSCOPE FOLDING (Islamic Geometry base)
        if layout == 5:
            r = np.sqrt(cx**2 + cy**2)
            theta = np.arctan2(cy, cx)
            segment = (np.pi * 2.0) / symmetry
            theta = (theta % segment) - (segment / 2.0)
            cx = r * np.cos(theta)
            cy = r * np.sin(theta)

        # ==========================================
        # PHASE 2 & 3: SHAPES & SDFs
        # ==========================================
        d = np.zeros_like(U)
        is_direct_mask = False

        if shape_type == 0:   # Circle
            d = np.sqrt(cx**2 + cy**2)
        elif shape_type == 1: # Square
            d = np.maximum(np.abs(cx), np.abs(cy))
        elif shape_type == 2: # Stripe V
            d = np.abs(cx)
        elif shape_type == 3: # Cross
            d = np.minimum(np.abs(cx), np.abs(cy))

        elif shape_type == 4: # CELLULAR / VORONOI
            ix, iy = np.floor(U), np.floor(V)
            min_dist = np.ones_like(U) * 10.0
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    nx, ny = ix + dx, iy + dy
                    h1 = np.sin(nx * 12.9898 + ny * 78.233) * 43758.5453
                    h2 = np.sin(nx * 39.346 + ny * 11.135) * 43758.5453
                    px = (h1 - np.floor(h1)) * jitter + 0.5 * (1.0 - jitter)
                    py = (h2 - np.floor(h2)) * jitter + 0.5 * (1.0 - jitter)
                    vx, vy = dx + px - cell_U, dy + py - cell_V
                    min_dist = np.minimum(min_dist, np.sqrt(vx**2 + vy**2))
            d = min_dist

        elif shape_type == 5: # CHECKERBOARD
            mask = (np.floor(U) + np.floor(V)) % 2
            is_direct_mask = True

        elif shape_type == 6: # DIAGONAL STRIPES
            d = np.abs(((cell_U + cell_V) % 1.0) - 0.5)

        elif shape_type == 7: # SINE WAVE
            d = np.abs(cy - (np.sin(cell_U * np.pi * 2.0) * 0.25))

        elif shape_type == 8: # CHEVRON / ZIGZAG
            d = np.abs(cy - (np.abs(cx) * 1.0))

        elif shape_type == 9: # N-POINT STAR
            an = np.arctan2(cy, cx)
            ra = np.sqrt(cx**2 + cy**2)
            seg = (np.pi * 2.0) / symmetry
            an = (an % seg) - (seg / 2.0)
            d = ra * np.cos(an)

        elif shape_type == 10: # VALUE NOISE
            iU = np.floor(U)
            iV = np.floor(V)
            fU = U % 1.0
            fV = V % 1.0
            u = fU * fU * (3.0 - 2.0 * fU)
            v = fV * fV * (3.0 - 2.0 * fV)

            def hash2(x, y):
                hv = np.sin(x * 12.9898 + y * 78.233) * 43758.5453
                return hv - np.floor(hv)

            a = hash2(iU, iV)
            b = hash2(iU + 1.0, iV)
            c = hash2(iU, iV + 1.0)
            e = hash2(iU + 1.0, iV + 1.0)
            mask = a + (b - a) * u + (c - a) * v + (a - b - c + e) * u * v
            is_direct_mask = True

        elif shape_type == 11: # INPUT TEXTURE
            if self.inputs[2]:
                tex = self.inputs[2].evaluate(frame, w, h)
                # cell_U / cell_V are 0->1 within each tile cell.
                # Use them to index into the texture via nearest-neighbour lookup.
                tex_h, tex_w = tex.shape[:2]
                ix = np.clip((cell_U * tex_w).astype(np.int32), 0, tex_w - 1)
                iy = np.clip((cell_V * tex_h).astype(np.int32), 0, tex_h - 1)
                # Luminance from RGB channels as the tile mask
                r = tex[iy, ix, 0]
                g = tex[iy, ix, 1]
                b_ch = tex[iy, ix, 2]
                mask = 0.2126 * r + 0.7152 * g + 0.0722 * b_ch
            else:
                # No texture connected — solid white so the node doesn't silently break
                mask = np.ones((h, w), dtype=np.float32)
            is_direct_mask = True

        # Mask modifier via Socket 1
        if self.inputs[1]:
            mask_map = self.inputs[1].evaluate(frame, w, h)
            size = size * mask_map[..., 0]

        # ==========================================
        # PHASE 4: EDGE BLENDING
        # ==========================================
        if not is_direct_mask:
            radius = size * 0.5
            edge_outer = radius + (softness * 0.5)
            edge_inner = radius - (softness * 0.5)
            diff = np.maximum(1e-5, edge_outer - edge_inner)
            t = np.clip((edge_outer - d) / diff, 0.0, 1.0)
            mask = t * t * (3.0 - 2.0 * t) # Smoothstep

        # Pack into RGBA
        arr = np.zeros((h, w, 4), dtype=np.float32)
        arr[..., 0] = mask
        arr[..., 1] = mask
        arr[..., 2] = mask
        arr[..., 3] = 1.0

        return arr

@register_node
class PolarCoordsNode(BaseNode):
    def __init__(self):
        super().__init__("Polar Coords")
        self.inputs = [None] # Input image to wrap
        self.add_property("Zoom", 1.0, 0.1, 10.0)
        self.add_property("Twist", 0.0, -10.0, 10.0)
        self.add_property("Spiral", 0.0, -10.0, 10.0)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
            
        # 1. Get Transform
        px, py, rot, sx, sy = self.get_transform(frame)
        
        # 2. Create Grid centered at 0,0
        aspect = w / h
        x = np.linspace(-1 * aspect, 1 * aspect, w)
        y = np.linspace(-1, 1, h)
        X, Y = np.meshgrid(x, y)
        
        # 3. Apply standard transform (Pan/Scale/Rot of the "lens")
        X, Y = apply_transform(X, Y, px, py, rot, sx, sy)
        
        # 4. Convert to Polar
        # Radius (Distance from center) -> Maps to Y (V)
        radius = np.sqrt(X**2 + Y**2)
        
        # Angle -> Maps to X (U)
        angle = np.arctan2(Y, X) / (2 * np.pi) + 0.5 # 0 to 1
        
        # 5. Apply Modifiers
        zoom = self.properties["Zoom"].get_value(frame)
        twist = self.properties["Twist"].get_value(frame)
        spiral = self.properties["Spiral"].get_value(frame)
        
        # Map Radius to V (Texture Y)
        # Zoom affects how much of the texture we see radially
        v_coord = radius * zoom
        
        # Map Angle to U (Texture X)
        # Twist bends the angle based on radius
        u_coord = angle + (radius * twist) + (spiral * radius)
        
        # 6. Sample Input
        # We need to render the input node at a resolution, then sample pixels
        # Optimization: Render input at same res
        src_img = self.inputs[0].evaluate(frame, w, h)
        
        # Sampling logic (Nearest neighbor wrapping for now for speed)
        # Convert 0-1 UVs back to pixel coordinates
        u_idx = (u_coord * w).astype(np.int32) % w
        v_idx = (v_coord * h).astype(np.int32) % h
        
        # Fancy numpy indexing to remap pixels
        result = src_img[v_idx, u_idx]
        
        return result

@register_node
class DisplacementNode(BaseNode):
    def __init__(self):
        super().__init__("Displace / Warp")
        self.inputs = [None, None] # [Source, Map]
        self.add_property("Strength X", 0.1, -1.0, 1.0)
        self.add_property("Strength Y", 0.1, -1.0, 1.0)
        self.add_property("Midlevel", 0.5, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        src = self.inputs[0].evaluate(frame, w, h) if self.inputs[0] else np.zeros((h,w,4), dtype=np.float32)
        dmap = self.inputs[1].evaluate(frame, w, h) if self.inputs[1] else np.zeros((h,w,4), dtype=np.float32)
        
        str_x = self.properties["Strength X"].get_value(frame)
        str_y = self.properties["Strength Y"].get_value(frame)
        mid = self.properties["Midlevel"].get_value(frame)
        
        # Create coordinate grid
        x = np.arange(w)
        y = np.arange(h)
        X, Y = np.meshgrid(x, y)
        
        # Calculate offsets based on map brightness (using Red channel)
        # Offset = (MapVal - Mid) * Strength * Size
        offset_x = (dmap[..., 0] - mid) * str_x * w
        offset_y = (dmap[..., 1] - mid) * str_y * h # Use Green for Y if available
        
        # New sample coordinates
        sample_x = np.clip(X + offset_x, 0, w - 1).astype(np.int32)
        sample_y = np.clip(Y + offset_y, 0, h - 1).astype(np.int32)
        
        return src[sample_y, sample_x]

@register_node
class ColorAdjustNode(BaseNode):
    def __init__(self):
        super().__init__("Color Adjust")
        self.inputs = [None]
        self.add_property("Brightness", 0.0, -1.0, 1.0)
        self.add_property("Contrast", 1.0, 0.0, 5.0)
        self.add_property("Saturation", 1.0, 0.0, 5.0)
        self.add_property("Invert", 0.0, is_bool=True)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]: return np.zeros((h, w, 4), dtype=np.float32)
        
        img = self.inputs[0].evaluate(frame, w, h).copy()
        
        bright = self.properties["Brightness"].get_value(frame)
        cont = self.properties["Contrast"].get_value(frame)
        sat = self.properties["Saturation"].get_value(frame)
        inv = bool(self.properties["Invert"].get_value(frame))
        
        rgb = img[..., :3]
        alpha = img[..., 3:]
        
        # Invert
        if inv:
            rgb = 1.0 - rgb
            
        # Contrast
        # (Color - 0.5) * Contrast + 0.5
        rgb = (rgb - 0.5) * cont + 0.5
        
        # Brightness
        rgb = rgb + bright
        
        # Saturation (Lerp between grayscale and color)
        # Grayscale weight: 0.299 R + 0.587 G + 0.114 B
        gray = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
        gray = gray[..., np.newaxis]
        rgb = gray + (rgb - gray) * sat
        
        # Clamp and recombine
        result = np.concatenate([np.clip(rgb, 0.0, 1.0), alpha], axis=2)
        return result

@register_node
class OscillatorNode(BaseNode):
    def __init__(self):
        super().__init__("Oscillator (Math)")
        # This node outputs a VALUE, not an image
        self.add_property("Waveform", 0, is_enum=True, items=["Sine", "Triangle", "Sawtooth", "Square", "Pulse"])
        self.add_property("Frequency", 1.0, 0.0, 50.0) # Cycles per second (approx)
        self.add_property("Amplitude", 1.0, 0.0, 100.0)
        self.add_property("Offset", 0.0, -100.0, 100.0)
        self.add_property("Phase", 0.0, 0.0, 1.0) # 0 to 1

    def evaluate(self, frame, w, h):
        # Time logic
        fps = PROJECT.fps
        t = frame / fps
        
        p = self.properties
        mode = int(p["Waveform"].get_value(frame))
        freq = p["Frequency"].get_value(frame)
        amp = p["Amplitude"].get_value(frame)
        off = p["Offset"].get_value(frame)
        phase = p["Phase"].get_value(frame)
        
        val = 0.0
        x = t * freq + phase
        
        if mode == 0: # Sine
            val = np.sin(x * 2 * np.pi)
        elif mode == 1: # Triangle
            val = 2 * np.abs(2 * (x - np.floor(x + 0.5))) - 1
        elif mode == 2: # Sawtooth
            val = 2 * (x - np.floor(x + 0.5))
        elif mode == 3: # Square
            val = np.sign(np.sin(x * 2 * np.pi))
        elif mode == 4: # Pulse (short blip)
            sine = np.sin(x * 2 * np.pi)
            val = 1.0 if sine > 0.9 else 0.0
            
        final = val * amp + off
        
        return np.full((h, w, 4), final, dtype=np.float32)
# ==========================================
# WAVE NODE PATCH for tab_animation_graph.py
# ==========================================
# INSTRUCTIONS: Make 4 changes to your existing file.
#
# CHANGE 1: Paste this class right before the line:
#   @register_node
#   class PNGSequenceNode(BaseNode):
#
# CHANGE 2: In NODE_COLORS dict, add after PNGSequenceNode line:
#   WaveNode:            QColor(40, 80, 130),
#
# CHANGE 3: In GfxNode._init_sockets() smap dict, add after PNGSequenceNode line:
#   WaveNode: [("Warp",)],
#
# CHANGE 4: In BOTH context menus (contextMenuEvent and open_add_node_menu),
#   add after the PNG Sequence line:
#   gen.addAction("Wave Texture",   lambda: spawn(WaveNode))
# ==========================================


@register_node
class WaveNode(BaseNode):
    """
    Generates a 2D spatial wave pattern image.
    Unlike OscillatorNode (which outputs a flat time-driven scalar),
    this varies the wave across pixels — useful for stripes, ripples,
    and driving ColorRamp / Merge / Displacement nodes.

    Warp input (optional): plug in a Noise node to organically distort
    the wave coordinates before sampling.
    """
    WAVE_TYPES = ["Sine", "Triangle", "Sawtooth", "Square", "Ripple (Radial)", "Checkerboard"]

    def __init__(self):
        super().__init__("Wave Texture")
        self.inputs = [None]  # Optional warp/distortion input
        self.add_property("Type", 0, is_enum=True, items=self.WAVE_TYPES)
        self.add_property("Frequency", 4.0, 0.1, 64.0)
        self.add_property("Direction", 0.0, -180.0, 180.0)   # degrees; 0 = horizontal bands
        self.add_property("Phase", 0.0, 0.0, 1.0)            # manual phase offset (0-1)
        self.add_property("Speed", 0.0, -10.0, 10.0)         # auto-animates phase from frame
        self.add_property("Distort", 0.0, 0.0, 2.0)          # strength of warp input
        self.add_property("Amplitude", 1.0, 0.0, 2.0)        # output scale
        self.add_property("Bias", 0.0, -1.0, 1.0)            # output shift
        self.add_property("Sharpness", 0.0, 0.0, 1.0)        # Square: softens edges / duty cycle

    def evaluate(self, frame, w, h):
        p = self.properties
        wave_type = int(p["Type"].get_value(frame))
        freq      = p["Frequency"].get_value(frame)
        direction = np.radians(p["Direction"].get_value(frame))
        phase     = p["Phase"].get_value(frame)
        speed     = p["Speed"].get_value(frame)
        distort   = p["Distort"].get_value(frame)
        amplitude = p["Amplitude"].get_value(frame)
        bias      = p["Bias"].get_value(frame)
        sharpness = p["Sharpness"].get_value(frame)

        # Auto-animate phase from frame number
        t = frame / max(PROJECT.fps, 1)
        animated_phase = phase + speed * t

        # Normalized pixel coords  (-asp..asp, -1..1)
        asp = w / h
        x = np.linspace(-1.0 * asp, 1.0 * asp, w, dtype=np.float32)
        y = np.linspace(-1.0, 1.0, h, dtype=np.float32)
        X, Y = np.meshgrid(x, y)

        # Optional warp input distorts coordinates before sampling
        if self.inputs[0] and distort > 0.001:
            warp = self.inputs[0].evaluate(frame, w, h)
            X = X + (warp[..., 0] - 0.5) * distort
            Y = Y + (warp[..., 1] - 0.5) * distort

        tau = 2.0 * np.pi

        # Project onto the wave axis (or compute radial / checkerboard)
        if wave_type == 4:    # Ripple: radial distance from center
            axis = np.sqrt(X ** 2 + Y ** 2)
        elif wave_type == 5:  # Checkerboard: handled separately below
            axis = None
        else:
            axis = X * np.cos(direction) + Y * np.sin(direction)

        # ── Wave shapes ────────────────────────────────────────────────────
        if wave_type == 0:    # Sine
            raw = np.sin((axis * freq + animated_phase) * tau) * 0.5 + 0.5

        elif wave_type == 1:  # Triangle
            u = (axis * freq + animated_phase) % 1.0
            raw = 1.0 - np.abs(u * 2.0 - 1.0)

        elif wave_type == 2:  # Sawtooth
            raw = (axis * freq + animated_phase) % 1.0

        elif wave_type == 3:  # Square  (Sharpness softens the edges)
            u = (axis * freq + animated_phase) % 1.0
            if sharpness < 0.01:
                raw = (u < 0.5).astype(np.float32)
            else:
                # Sigmoid-style soft edge; sharpness 1.0 = hard, 0.0 = sine-ish
                k = 1.0 / max(1.0 - sharpness, 0.01) * 0.15
                raw = np.clip(np.sign(np.sin((axis * freq + animated_phase) * tau))
                              * 0.5 + 0.5, 0.0, 1.0)
                # Blend hard square with soft sine for intermediate values
                soft = np.sin((axis * freq + animated_phase) * tau) * 0.5 + 0.5
                raw = raw * sharpness + soft * (1.0 - sharpness)

        elif wave_type == 4:  # Ripple (radial sine — axis = radius)
            raw = np.sin((axis * freq + animated_phase) * tau) * 0.5 + 0.5

        else:                  # Checkerboard (XOR of two square waves)
            ux = (X * freq * 0.5 + animated_phase) % 1.0
            uy = (Y * freq * 0.5) % 1.0
            cx = (ux < 0.5).astype(np.float32)
            cy = (uy < 0.5).astype(np.float32)
            raw = np.abs(cx - cy)

        # ── Output remapping ───────────────────────────────────────────────
        result = np.clip(raw * amplitude + bias, 0.0, 1.0)

        out = np.empty((h, w, 4), dtype=np.float32)
        out[..., 0] = result
        out[..., 1] = result
        out[..., 2] = result
        out[..., 3] = 1.0
        return out



@register_node
class OscilloscopeNode(BaseNode):
    """
    Draws an animated waveform line on the canvas like a graphing calculator / oscilloscope.
    Stroke Texture input: textures the stroke line itself.
    Fill Texture input: textures the interior of the stroke.
    Noise Mod input: organically warps the waveform when connected.
    """
    WAVE_TYPES = ["Sine", "Triangle", "Sawtooth", "Square", "Noise Modulated"]

    def __init__(self):
        super().__init__("Oscilloscope")
        self.inputs = [None, None, None]  # [Stroke Texture, Fill Texture, Noise Mod]
        self.add_property("Type", 0, is_enum=True, items=self.WAVE_TYPES)
        self.add_property("Frequency", 2.0, 0.1, 32.0)
        self.add_property("Phase", 0.0, 0.0, 1.0)
        self.add_property("Speed", 0.0, -10.0, 10.0)
        self.add_property("Amplitude", 0.3, 0.01, 1.0)
        self.add_property("Stroke Width", 3.0, 0.5, 64.0)
        self.add_property("Stroke R", 1.0, 0, 1)
        self.add_property("Stroke G", 1.0, 0, 1)
        self.add_property("Stroke B", 1.0, 0, 1)
        self.add_property("Stroke A", 1.0, 0, 1)
        self.add_property("Scale X", 1.0, 0.01, 4.0)
        self.add_property("Scale Y", 1.0, 0.01, 4.0)
        self.add_transform_properties()

    def _sample_wave(self, x_norm, wave_type, freq, phase, amplitude, noise_row=None):
        """
        x_norm: float or array in 0..1 (position along wave width)
        Returns y offset in -1..1
        """
        t = x_norm * freq + phase
        if wave_type == 0:   # Sine
            y = np.sin(t * 2.0 * np.pi)
        elif wave_type == 1: # Triangle
            u = t % 1.0
            y = 1.0 - np.abs(u * 2.0 - 1.0) * 2.0 - 1.0
        elif wave_type == 2: # Sawtooth
            y = (t % 1.0) * 2.0 - 1.0
        elif wave_type == 3: # Square
            y = np.sign(np.sin(t * 2.0 * np.pi))
        else:                # Noise Modulated sine
            y = np.sin(t * 2.0 * np.pi)
            if noise_row is not None:
                y = y + (noise_row - 0.5) * 2.0
                y = np.clip(y, -1.0, 1.0)
        return y * amplitude

    def evaluate(self, frame, w, h):
        p = self.properties
        wave_type  = int(p["Type"].get_value(frame))
        freq       = p["Frequency"].get_value(frame)
        phase      = p["Phase"].get_value(frame) + p["Speed"].get_value(frame) * frame / max(PROJECT.fps, 1)
        amplitude  = p["Amplitude"].get_value(frame)
        stroke_w   = p["Stroke Width"].get_value(frame)
        sr, sg, sb, sa = (p["Stroke R"].get_value(frame), p["Stroke G"].get_value(frame),
                          p["Stroke B"].get_value(frame), p["Stroke A"].get_value(frame))
        scale_x    = p["Scale X"].get_value(frame)
        scale_y    = p["Scale Y"].get_value(frame)
        px, py, rot, tsx, tsy = self.get_transform(frame)

        # Optional noise modulator
        # Build waveform path points
        num_pts = w * 2

        noise_row = None
        if self.inputs[2] and wave_type == 4:
            noise_img = self.inputs[2].evaluate(frame, num_pts, 1)
            noise_row = noise_img[0, :, 0]  # single row, red channel

        # Build waveform path points
        num_pts = w * 2
        xs_norm = np.linspace(0.0, 1.0, num_pts)
        ys_norm = self._sample_wave(xs_norm, wave_type, freq, phase, amplitude, noise_row)

        # Convert to pixel coords in wave-local space (centered at 0,0)
        wave_half_w = (w / 2) * scale_x
        wave_half_h = (h / 2) * scale_y
        px_coords = (xs_norm - 0.5) * 2.0 * wave_half_w   # -wave_half_w .. +wave_half_w
        py_coords = ys_norm * wave_half_h                   # -wave_half_h .. +wave_half_h

        # For Square wave: insert vertical segments at discontinuities
        if wave_type == 3:
            path_pts = []
            for i in range(len(px_coords)):
                if i > 0 and abs(py_coords[i] - py_coords[i-1]) > wave_half_h * 0.5:
                    # Insert vertical jump
                    path_pts.append((px_coords[i], py_coords[i-1]))
                path_pts.append((px_coords[i], py_coords[i]))
        else:
            path_pts = list(zip(px_coords.tolist(), py_coords.tolist()))

        # --- Draw ---
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Apply transform (same convention as other nodes)
        painter.translate(w / 2 + px * w / 2, h / 2 + py * h / 2)
        painter.rotate(rot)
        painter.scale(tsx, tsy)

        # Build QPainterPath
        path = QPainterPath()
        if path_pts:
            path.moveTo(path_pts[0][0], path_pts[0][1])
            for pt in path_pts[1:]:
                path.lineTo(pt[0], pt[1])

        # Stroke texture or fallback color
        if self.inputs[0]:
            tex_arr = self.inputs[0].evaluate(frame, w, h)
            tex_arr = np.clip(tex_arr * 255, 0, 255).astype(np.uint8)
            if not tex_arr.flags['C_CONTIGUOUS']:
                tex_arr = np.ascontiguousarray(tex_arr)
            tex_img = QImage(tex_arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            pen = QPen(QBrush(QPixmap.fromImage(tex_img)), stroke_w,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        else:
            stroke_color = QColor.fromRgbF(sr, sg, sb, sa)
            pen = QPen(stroke_color, stroke_w,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)

        # Fill texture (textures the inside of the stroke shape)
        if self.inputs[1]:
            fill_arr = self.inputs[1].evaluate(frame, w, h)
            fill_arr = np.clip(fill_arr * 255, 0, 255).astype(np.uint8)
            if not fill_arr.flags['C_CONTIGUOUS']:
                fill_arr = np.ascontiguousarray(fill_arr)
            fill_img = QImage(fill_arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            painter.setBrush(QBrush(QPixmap.fromImage(fill_img)))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawPath(path)
        painter.end()

        return np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0


@register_node
class TransformNode(BaseNode):
    """
    Repositions, scales, and rotates any image input.
    Anchor X/Y: 0=left/top, 0.5=center, 1=right/bottom.
    """
    def __init__(self):
        super().__init__("Transform")
        self.inputs = [None]
        self.add_property("Pos X", 0.0, -2.0, 2.0)
        self.add_property("Pos Y", 0.0, -2.0, 2.0)
        self.add_property("Scale X", 1.0, 0.01, 10.0)
        self.add_property("Scale Y", 1.0, 0.01, 10.0)
        self.add_property("Rotation", 0.0, -360.0, 360.0)
        self.add_property("Anchor X", 0.5, 0.0, 1.0)
        self.add_property("Anchor Y", 0.5, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        src = self.inputs[0].evaluate(frame, w, h)
        src = np.clip(src * 255, 0, 255).astype(np.uint8)
        if not src.flags['C_CONTIGUOUS']:
            src = np.ascontiguousarray(src)
        p = self.properties
        pos_x   = p["Pos X"].get_value(frame)
        pos_y   = p["Pos Y"].get_value(frame)
        scale_x = p["Scale X"].get_value(frame)
        scale_y = p["Scale Y"].get_value(frame)
        rot     = p["Rotation"].get_value(frame)
        anch_x  = p["Anchor X"].get_value(frame)
        anch_y  = p["Anchor Y"].get_value(frame)
        src_img = QImage(src.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        out_img = QImage(w, h, QImage.Format.Format_RGBA8888)
        out_img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        anchor_px = anch_x * w
        anchor_py = anch_y * h
        painter.translate(anchor_px + pos_x * w, anchor_py + pos_y * h)
        painter.rotate(rot)
        painter.scale(scale_x, scale_y)
        painter.translate(-anchor_px, -anchor_py)
        painter.drawImage(0, 0, src_img)
        painter.end()
        return np.frombuffer(out_img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0


@register_node
class PNGSequenceNode(BaseNode):
    """Import a folder of PNG files as an animation sequence."""
    def __init__(self):
        super().__init__("PNG Sequence")
        self.inputs = []
        self.folder_path = None
        self.frame_paths = []
        self.frame_cache = {}
        self.add_property("Loop", 1.0, is_bool=True)
        self.add_property("Speed", 1.0, 0.1, 10.0)
        self.add_property("Start Frame", 0, 0, 9999)

    def load_folder(self, folder_path):
        """Load all PNG files from a folder, sorted by name."""
        self.folder_path = folder_path
        self.frame_paths = sorted(glob.glob(os.path.join(folder_path, "*.png")))
        self.frame_cache.clear()
        return len(self.frame_paths)

    def _load_frame(self, idx):
        """Load and cache a single frame."""
        if idx in self.frame_cache:
            return self.frame_cache[idx]
        if idx < 0 or idx >= len(self.frame_paths):
            return None
        try:
            img = PILImage.open(self.frame_paths[idx]).convert("RGBA")
            arr = np.array(img).astype(np.float32) / 255.0
            self.frame_cache[idx] = arr
            return arr
        except Exception:
            return None

    def _extra_to_dict(self):
        return {'folder_path': self.folder_path}

    def _extra_from_dict(self, d):
        path = d.get('folder_path')
        if path and os.path.isdir(path):
            self.load_folder(path)

    def evaluate(self, frame, w, h):
        if not self.frame_paths:
            return np.zeros((h, w, 4), dtype=np.float32)
        
        p = self.properties
        loop = bool(p["Loop"].get_value(frame))
        speed = p["Speed"].get_value(frame)
        start = int(p["Start Frame"].get_value(frame))
        
        # Calculate which source frame to use
        src_frame = int((frame - start) * speed)
        
        if loop:
            src_frame = src_frame % len(self.frame_paths)
        else:
            src_frame = max(0, min(src_frame, len(self.frame_paths) - 1))
        
        arr = self._load_frame(src_frame)
        if arr is None:
            return np.zeros((h, w, 4), dtype=np.float32)
        
        # Resize if needed
        src_h, src_w = arr.shape[:2]
        if src_w != w or src_h != h:
            # Simple nearest-neighbor resize
            y_idx = (np.arange(h) * src_h / h).astype(np.int32)
            x_idx = (np.arange(w) * src_w / w).astype(np.int32)
            y_idx = np.clip(y_idx, 0, src_h - 1)
            x_idx = np.clip(x_idx, 0, src_w - 1)
            return arr[y_idx[:, np.newaxis], x_idx[np.newaxis, :]]
        
        return arr.copy()


# ==========================================
# NEW NODES - DROP IN AFTER PNGSequenceNode
# (before the "4. VISUALS" section)
# ==========================================

# -----------------------------------------------------------------------
# MODIFIER NODES
# -----------------------------------------------------------------------

@register_node
class BlurNode(BaseNode):
    def __init__(self):
        super().__init__("Blur")
        self.inputs = [None]
        self.add_property("Radius", 3.0, 0.0, 64.0)
        self.add_property("Mode", 0, is_enum=True, items=["Box", "Gaussian"])

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h)
        radius = int(self.properties["Radius"].get_value(frame))
        mode = int(self.properties["Mode"].get_value(frame))
        if radius < 1:
            return img
        result = img.copy()
        if mode == 0:  # Box blur: separable 1D passes
            k = np.ones(radius * 2 + 1, dtype=np.float32) / (radius * 2 + 1)
            for c in range(4):
                # Horizontal
                result[..., c] = np.apply_along_axis(
                    lambda row: np.convolve(row, k, mode='same'), 1, result[..., c])
                # Vertical
                result[..., c] = np.apply_along_axis(
                    lambda col: np.convolve(col, k, mode='same'), 0, result[..., c])
        else:  # Gaussian: use a simple 2-pass approximation (3x box blur)
            k = np.ones(radius * 2 + 1, dtype=np.float32) / (radius * 2 + 1)
            for _ in range(3):  # 3 box passes ≈ gaussian
                for c in range(4):
                    result[..., c] = np.apply_along_axis(
                        lambda row: np.convolve(row, k, mode='same'), 1, result[..., c])
                    result[..., c] = np.apply_along_axis(
                        lambda col: np.convolve(col, k, mode='same'), 0, result[..., c])
        return np.clip(result, 0.0, 1.0)


@register_node
class EdgeDetectNode(BaseNode):
    def __init__(self):
        super().__init__("Edge Detect")
        self.inputs = [None]
        self.add_property("Mode", 0, is_enum=True, items=["Sobel", "Laplacian"])
        self.add_property("Threshold", 0.1, 0.0, 1.0)
        self.add_property("Edge R", 1.0, 0, 1)
        self.add_property("Edge G", 1.0, 0, 1)
        self.add_property("Edge B", 1.0, 0, 1)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h)
        # Luminance
        lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
        mode = int(self.properties["Mode"].get_value(frame))
        thresh = self.properties["Threshold"].get_value(frame)

        if mode == 0:  # Sobel
            # Pad to handle borders
            pad = np.pad(lum, 1, mode='edge')
            gx = (pad[1:-1, 2:] - pad[1:-1, :-2]) * 0.5
            gy = (pad[2:, 1:-1] - pad[:-2, 1:-1]) * 0.5
            edge = np.sqrt(gx**2 + gy**2)
        else:  # Laplacian
            pad = np.pad(lum, 1, mode='edge')
            edge = np.abs(
                -pad[:-2, 1:-1] - pad[2:, 1:-1]
                - pad[1:-1, :-2] - pad[1:-1, 2:]
                + 4.0 * pad[1:-1, 1:-1]
            )

        edge = np.clip(edge / max(edge.max(), 0.0001), 0.0, 1.0)
        mask = (edge > thresh).astype(np.float32)

        out = np.zeros((h, w, 4), dtype=np.float32)
        er = self.properties["Edge R"].get_value(frame)
        eg = self.properties["Edge G"].get_value(frame)
        eb = self.properties["Edge B"].get_value(frame)
        out[..., 0] = er * mask
        out[..., 1] = eg * mask
        out[..., 2] = eb * mask
        out[..., 3] = mask
        return out


@register_node
class PixelateNode(BaseNode):
    def __init__(self):
        super().__init__("Pixelate")
        self.inputs = [None]
        self.add_property("Block Size", 8, 1, 128)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h)
        bs = max(1, int(self.properties["Block Size"].get_value(frame)))
        # Downscale then upscale (nearest neighbor = pixelate)
        sw = max(1, w // bs)
        sh = max(1, h // bs)
        # Downscale
        y_idx = (np.arange(sh) * h / sh).astype(np.int32)
        x_idx = (np.arange(sw) * w / sw).astype(np.int32)
        small = img[y_idx[:, np.newaxis], x_idx[np.newaxis, :]]
        # Upscale back to original
        y_up = (np.arange(h) * sh / h).astype(np.int32)
        x_up = (np.arange(w) * sw / w).astype(np.int32)
        y_up = np.clip(y_up, 0, sh - 1)
        x_up = np.clip(x_up, 0, sw - 1)
        return small[y_up[:, np.newaxis], x_up[np.newaxis, :]]


@register_node
class ChromaticAberrationNode(BaseNode):
    def __init__(self):
        super().__init__("Chromatic Aberration")
        self.inputs = [None]
        self.add_property("Strength", 0.01, 0.0, 0.2)
        self.add_property("Mode", 0, is_enum=True, items=["Lateral (H)", "Radial"])
        self.add_property("Angle", 0.0, -180.0, 180.0)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h)
        strength = self.properties["Strength"].get_value(frame)
        mode = int(self.properties["Mode"].get_value(frame))
        angle = np.radians(self.properties["Angle"].get_value(frame))

        out = img.copy()

        if mode == 0:  # Lateral: shift R and B channels horizontally
            dx_r = int( strength * w * np.cos(angle))
            dy_r = int( strength * h * np.sin(angle))
            dx_b = int(-strength * w * np.cos(angle))
            dy_b = int(-strength * h * np.sin(angle))

            def shift_channel(ch, dx, dy):
                src = img[..., ch]
                shifted = np.roll(src, dy, axis=0)
                shifted = np.roll(shifted, dx, axis=1)
                return shifted

            out[..., 0] = shift_channel(0, dx_r, dy_r)  # Red
            out[..., 2] = shift_channel(2, dx_b, dy_b)  # Blue
            # Green stays
        else:  # Radial: R pushed out from center, B pulled in
            cx, cy = w / 2.0, h / 2.0
            x = np.arange(w, dtype=np.float32)
            y = np.arange(h, dtype=np.float32)
            X, Y = np.meshgrid(x, y)
            dx = (X - cx) / cx  # -1 to 1
            dy = (Y - cy) / cy

            for c, sign in [(0, 1.0), (2, -1.0)]:  # R out, B in
                sample_x = np.clip(X + dx * strength * w * sign, 0, w - 1).astype(np.int32)
                sample_y = np.clip(Y + dy * strength * h * sign, 0, h - 1).astype(np.int32)
                out[..., c] = img[sample_y, sample_x, c]

        return np.clip(out, 0.0, 1.0)


@register_node
class ScanlinesNode(BaseNode):
    def __init__(self):
        super().__init__("Scanlines")
        self.inputs = [None]
        self.add_property("Line Spacing", 4, 1, 64)
        self.add_property("Darkness", 0.5, 0.0, 1.0)
        self.add_property("Orientation", 0, is_enum=True, items=["Horizontal", "Vertical"])
        self.add_property("Scroll Speed", 0.0, -10.0, 10.0)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h).copy()
        spacing = max(1, int(self.properties["Line Spacing"].get_value(frame)))
        darkness = self.properties["Darkness"].get_value(frame)
        orient = int(self.properties["Orientation"].get_value(frame))
        scroll = self.properties["Scroll Speed"].get_value(frame)
        offset = int(frame * scroll) % spacing

        if orient == 0:  # Horizontal lines
            rows = np.arange(h)
            mask = ((rows + offset) % spacing == 0)
            img[mask, :, :3] *= (1.0 - darkness)
        else:  # Vertical lines
            cols = np.arange(w)
            mask = ((cols + offset) % spacing == 0)
            img[:, mask, :3] *= (1.0 - darkness)

        return np.clip(img, 0.0, 1.0)


# -----------------------------------------------------------------------
# FAKE SHADER NODES
# -----------------------------------------------------------------------

@register_node
class CRTNode(BaseNode):
    """Combines scanlines, barrel distortion, and vignette in one node."""
    def __init__(self):
        super().__init__("CRT Effect")
        self.inputs = [None]
        self.add_property("Scanline Strength", 0.3, 0.0, 1.0)
        self.add_property("Scanline Spacing", 3, 1, 32)
        self.add_property("Barrel", 0.15, 0.0, 1.0)
        self.add_property("Vignette", 0.4, 0.0, 1.0)
        self.add_property("Chromatic Fringe", 0.005, 0.0, 0.05)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)

        p = self.properties
        barrel = p["Barrel"].get_value(frame)
        vig = p["Vignette"].get_value(frame)
        fringe = p["Chromatic Fringe"].get_value(frame)
        scan_str = p["Scanline Strength"].get_value(frame)
        scan_sp = max(1, int(p["Scanline Spacing"].get_value(frame)))

        # Coordinate grids
        cx, cy = w / 2.0, h / 2.0
        x = np.arange(w, dtype=np.float32)
        y = np.arange(h, dtype=np.float32)
        X, Y = np.meshgrid(x, y)
        nx = (X - cx) / cx  # -1 to 1
        ny = (Y - cy) / cy

        # Barrel distortion: r^2 warp
        r2 = nx**2 + ny**2
        warp = 1.0 + barrel * r2
        src_x = np.clip((nx * warp) * cx + cx, 0, w - 1).astype(np.int32)
        src_y = np.clip((ny * warp) * cy + cy, 0, h - 1).astype(np.int32)

        # Sample base image
        img = self.inputs[0].evaluate(frame, w, h)
        out = img[src_y, src_x].copy()

        # Chromatic fringe (radial, small)
        if fringe > 0.0:
            for c, sign in [(0, 1.0), (2, -1.0)]:
                sx = np.clip(src_x + (nx * fringe * w * sign).astype(np.int32), 0, w - 1)
                sy = np.clip(src_y + (ny * fringe * h * sign).astype(np.int32), 0, h - 1)
                out[..., c] = img[sy, sx, c]

        # Scanlines
        rows = np.arange(h)
        scan_mask = ((rows % scan_sp) == 0)
        out[scan_mask, :, :3] *= (1.0 - scan_str)

        # Vignette: smooth radial falloff
        vig_map = 1.0 - np.clip(r2 * vig, 0.0, 1.0)
        out[..., :3] *= vig_map[..., np.newaxis]

        # Black outside barrel warp boundary
        outside = (r2 * barrel) > 1.0
        out[outside] = 0.0

        return np.clip(out, 0.0, 1.0)


@register_node
class DitherNode(BaseNode):
    """Ordered (Bayer matrix) dithering — great for lo-fi palette reduction."""
    BAYER2 = np.array([[0, 2], [3, 1]], dtype=np.float32) / 4.0
    BAYER4 = np.array([
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5]], dtype=np.float32) / 16.0
    BAYER8 = np.array([
        [ 0, 32,  8, 40,  2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44,  4, 36, 14, 46,  6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [ 3, 35, 11, 43,  1, 33,  9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47,  7, 39, 13, 45,  5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21]], dtype=np.float32) / 64.0

    def __init__(self):
        super().__init__("Dither")
        self.inputs = [None]
        self.add_property("Matrix", 1, is_enum=True, items=["2x2", "4x4", "8x8"])
        self.add_property("Levels", 4, 2, 32)
        self.add_property("Strength", 1.0, 0.0, 2.0)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h).copy()
        mat_idx = int(self.properties["Matrix"].get_value(frame))
        levels = max(2, int(self.properties["Levels"].get_value(frame)))
        strength = self.properties["Strength"].get_value(frame)

        matrices = [self.BAYER2, self.BAYER4, self.BAYER8]
        bayer = matrices[min(mat_idx, 2)]
        bh, bw = bayer.shape

        # Tile bayer matrix to image size
        reps_y = (h + bh - 1) // bh
        reps_x = (w + bw - 1) // bw
        tiled = np.tile(bayer, (reps_y, reps_x))[:h, :w]

        # Apply threshold: quantize each channel
        step = 1.0 / (levels - 1)
        for c in range(3):
            channel = img[..., c]
            # Add threshold offset scaled by strength
            threshold = (tiled - 0.5) * step * strength
            channel = np.clip(channel + threshold, 0.0, 1.0)
            # Quantize
            img[..., c] = np.round(channel / step) * step

        return np.clip(img, 0.0, 1.0)


@register_node
class PosterizeNode(BaseNode):
    """Posterize / palette reduction. Can also do a full palette swap via color ramp input."""
    def __init__(self):
        super().__init__("Posterize")
        self.inputs = [None]  # Source image
        self.add_property("Levels", 4, 2, 32)
        self.add_property("Per Channel", 1, is_bool=True)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h).copy()
        levels = max(2, int(self.properties["Levels"].get_value(frame)))
        per_ch = bool(self.properties["Per Channel"].get_value(frame))
        step = 1.0 / (levels - 1)
        if per_ch:
            img[..., :3] = np.round(img[..., :3] / step) * step
        else:
            # Posterize based on luminance, preserve hue
            lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
            lum_q = np.round(lum / step) * step
            ratio = np.where(lum > 0.0001, lum_q / np.maximum(lum, 0.0001), 1.0)
            img[..., :3] *= ratio[..., np.newaxis]
        return np.clip(img, 0.0, 1.0)


@register_node
class GlowNode(BaseNode):
    """Fake bloom/glow — extracts bright areas and adds blurred additive pass."""
    def __init__(self):
        super().__init__("Glow / Bloom")
        self.inputs = [None]
        self.add_property("Threshold", 0.6, 0.0, 1.0)
        self.add_property("Radius", 8, 1, 48)
        self.add_property("Intensity", 1.0, 0.0, 5.0)
        self.add_property("Tint R", 1.0, 0, 1)
        self.add_property("Tint G", 0.9, 0, 1)
        self.add_property("Tint B", 0.7, 0, 1)

    def _fast_blur(self, arr, radius):
        """3-pass box blur approximating gaussian."""
        k = np.ones(radius * 2 + 1, dtype=np.float32) / (radius * 2 + 1)
        result = arr.copy()
        for _ in range(3):
            for c in range(arr.shape[2]):
                result[..., c] = np.apply_along_axis(
                    lambda r: np.convolve(r, k, mode='same'), 1, result[..., c])
                result[..., c] = np.apply_along_axis(
                    lambda r: np.convolve(r, k, mode='same'), 0, result[..., c])
        return result

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)
        img = self.inputs[0].evaluate(frame, w, h)
        thresh = self.properties["Threshold"].get_value(frame)
        radius = max(1, int(self.properties["Radius"].get_value(frame)))
        intensity = self.properties["Intensity"].get_value(frame)
        tr = self.properties["Tint R"].get_value(frame)
        tg = self.properties["Tint G"].get_value(frame)
        tb = self.properties["Tint B"].get_value(frame)

        # Extract bright pixels
        lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
        bright_mask = np.maximum(lum - thresh, 0.0) / max(1.0 - thresh, 0.0001)
        bright = img.copy()
        bright[..., :3] *= bright_mask[..., np.newaxis]
        bright[..., 3] = bright_mask

        # Blur the bright layer
        bloom = self._fast_blur(bright, radius)

        # Apply tint to bloom
        bloom[..., 0] *= tr
        bloom[..., 1] *= tg
        bloom[..., 2] *= tb

        # Additive composite: original + bloom * intensity
        out = img.copy()
        out[..., :3] = np.clip(img[..., :3] + bloom[..., :3] * intensity, 0.0, 1.0)
        out[..., 3] = img[..., 3]
        return out


# -----------------------------------------------------------------------
# SDF OP NODES
# -----------------------------------------------------------------------

@register_node
class SDFBooleanNode(BaseNode):
    """
    Boolean operations between two SDF masks.
    Inputs should be SDF nodes (Circle, Box, Ring, etc.) — uses the R channel as the mask.
    Union      = max(A, B)
    Subtract   = A * (1 - B)   (A minus B)
    Intersect  = min(A, B)
    SmoothUnion = smooth blend of A and B (k controls smoothness)
    """
    def __init__(self):
        super().__init__("SDF Boolean")
        self.inputs = [None, None]
        self.add_property("Operation", 0, is_enum=True,
                          items=["Union", "Subtract", "Intersect", "Smooth Union"])
        self.add_property("Smooth K", 0.1, 0.001, 1.0)

    def evaluate(self, frame, w, h):
        a_img = self.inputs[0].evaluate(frame, w, h) if self.inputs[0] else np.zeros((h, w, 4), dtype=np.float32)
        b_img = self.inputs[1].evaluate(frame, w, h) if self.inputs[1] else np.zeros((h, w, 4), dtype=np.float32)

        a = a_img[..., 0]  # Use red channel as mask
        b = b_img[..., 0]

        op = int(self.properties["Operation"].get_value(frame))
        k = self.properties["Smooth K"].get_value(frame)

        if op == 0:   # Union
            result = np.maximum(a, b)
        elif op == 1:  # Subtract
            result = a * (1.0 - b)
        elif op == 2:  # Intersect
            result = np.minimum(a, b)
        else:          # Smooth Union (polynomial smooth-min)
            da = 1.0 - a
            db = 1.0 - b
            h_val = np.clip(0.5 + 0.5 * (db - da) / k, 0.0, 1.0)
            smooth_d = db * h_val + da * (1.0 - h_val) - k * h_val * (1.0 - h_val)
            result = 1.0 - smooth_d

        result = np.clip(result, 0.0, 1.0)
        weight_a = a / np.maximum(a + b, 0.0001)
        weight_b = 1.0 - weight_a
        out = np.zeros((h, w, 4), dtype=np.float32)
        out[..., :3] = (a_img[..., :3] * weight_a[..., np.newaxis] +
                        b_img[..., :3] * weight_b[..., np.newaxis])
        out[..., 3] = result
        out[..., 0] = result
        out[..., 1] = result
        out[..., 2] = result
        return out


@register_node
class SDFRepeatNode(BaseNode):
    """
    Tiles/repeats an SDF in a grid pattern.
    """
    def __init__(self):
        super().__init__("SDF Repeat")
        self.inputs = [None]
        self.add_property("Cols", 3, 1, 20)
        self.add_property("Rows", 3, 1, 20)
        self.add_property("Offset X", 0.0, -1.0, 1.0)
        self.add_property("Offset Y", 0.0, -1.0, 1.0)
        self.add_property("Scale", 0.8, 0.1, 1.0)
        self.add_property("Stagger", 0.0, 0.0, 1.0)

    def evaluate(self, frame, w, h):
        if not self.inputs[0]:
            return np.zeros((h, w, 4), dtype=np.float32)

        p = self.properties
        cols = max(1, int(p["Cols"].get_value(frame)))
        rows = max(1, int(p["Rows"].get_value(frame)))
        off_x = p["Offset X"].get_value(frame)
        off_y = p["Offset Y"].get_value(frame)
        cell_scale = p["Scale"].get_value(frame)
        stagger = p["Stagger"].get_value(frame)

        cell_w = max(1, w // cols)
        cell_h = max(1, h // rows)

        cell_img = self.inputs[0].evaluate(frame, cell_w, cell_h)

        out = np.zeros((h, w, 4), dtype=np.float32)

        for row in range(rows):
            for col in range(cols):
                x0 = col * cell_w
                y0 = row * cell_h
                x1 = min(x0 + cell_w, w)
                y1 = min(y0 + cell_h, h)

                if x1 <= x0 or y1 <= y0:
                    continue

                if stagger > 0.0 and row % 2 == 1:
                    stagger_px = int(stagger * cell_w)
                    x0 = (x0 + stagger_px) % w
                    x1 = x0 + (x1 - (col * cell_w))
                    x1 = min(x1, w)

                tile_h = y1 - y0
                tile_w = x1 - x0

                if tile_w <= 0 or tile_h <= 0:
                    continue

                ly = np.linspace(0.5 - 0.5 / cell_scale + off_y,
                                 0.5 + 0.5 / cell_scale + off_y, tile_h)
                lx = np.linspace(0.5 - 0.5 / cell_scale + off_x,
                                 0.5 + 0.5 / cell_scale + off_x, tile_w)

                src_y = (ly * cell_h).astype(np.int32)
                src_x = (lx * cell_w).astype(np.int32)

                valid_y = (src_y >= 0) & (src_y < cell_h)
                valid_x = (src_x >= 0) & (src_x < cell_w)

                src_y_c = np.clip(src_y, 0, cell_h - 1)
                src_x_c = np.clip(src_x, 0, cell_w - 1)

                sampled = cell_img[src_y_c[:, np.newaxis], src_x_c[np.newaxis, :]]

                outside = ~(valid_y[:, np.newaxis] & valid_x[np.newaxis, :])
                sampled = sampled.copy()
                sampled[outside] = 0.0

                out[y0:y1, x0:x1] = sampled

        return out


# ==========================================
# UI NODES
# ==========================================

@register_node
class UIPanelNode(BaseNode):
    def __init__(self):
        super().__init__("UI Panel")
        self.inputs = []
        self.add_property("Width", 200, 1, 960)
        self.add_property("Height", 100, 1, 544)
        self.add_property("Corner Radius", 8.0, 0, 100)
        self.add_property("Fill R", 0.2, 0, 1)
        self.add_property("Fill G", 0.2, 0, 1)
        self.add_property("Fill B", 0.25, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Border R", 0.5, 0, 1)
        self.add_property("Border G", 0.5, 0, 1)
        self.add_property("Border B", 0.5, 0, 1)
        self.add_property("Border A", 1.0, 0, 1)
        self.add_property("Border Width", 2.0, 0, 20)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        rect_w = p["Width"].get_value(frame)
        rect_h = p["Height"].get_value(frame)
        corner = p["Corner Radius"].get_value(frame)
        fill = QColor.fromRgbF(p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
                               p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        border = QColor.fromRgbF(p["Border R"].get_value(frame), p["Border G"].get_value(frame),
                                 p["Border B"].get_value(frame), p["Border A"].get_value(frame))
        border_w = p["Border Width"].get_value(frame)
        px, py, rot, sx, sy = self.get_transform(frame)

        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(w / 2 + px * w / 2, h / 2 + py * h / 2)
        painter.rotate(rot)
        painter.scale(sx, sy)

        rect = QRectF(-rect_w / 2, -rect_h / 2, rect_w, rect_h)
        painter.setBrush(QBrush(fill))
        if border_w > 0 and border.alphaF() > 0:
            painter.setPen(QPen(border, border_w))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        if corner > 0:
            painter.drawRoundedRect(rect, corner, corner)
        else:
            painter.drawRect(rect)
        painter.end()

        return np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0


@register_node
class UIButtonNode(BaseNode):
    def __init__(self):
        super().__init__("UI Button")
        self.inputs = []
        self.add_property("Width", 120, 1, 960)
        self.add_property("Height", 48, 1, 544)
        self.add_property("Corner Radius", 10.0, 0, 100)
        self.add_property("Fill R", 0.25, 0, 1)
        self.add_property("Fill G", 0.45, 0, 1)
        self.add_property("Fill B", 0.8, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Border R", 0.1, 0, 1)
        self.add_property("Border G", 0.2, 0, 1)
        self.add_property("Border B", 0.5, 0, 1)
        self.add_property("Border A", 1.0, 0, 1)
        self.add_property("Border Width", 2.0, 0, 20)
        self.add_property("Bevel Size", 3.0, 0, 20)
        self.add_property("Bevel Strength", 1.0, 0, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        rect_w = p["Width"].get_value(frame)
        rect_h = p["Height"].get_value(frame)
        corner = p["Corner Radius"].get_value(frame)
        fill = QColor.fromRgbF(p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
                               p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        border = QColor.fromRgbF(p["Border R"].get_value(frame), p["Border G"].get_value(frame),
                                 p["Border B"].get_value(frame), p["Border A"].get_value(frame))
        border_w = p["Border Width"].get_value(frame)
        bevel_size = p["Bevel Size"].get_value(frame)
        bevel_str = p["Bevel Strength"].get_value(frame)
        px, py, rot, sx, sy = self.get_transform(frame)

        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(w / 2 + px * w / 2, h / 2 + py * h / 2)
        painter.rotate(rot)
        painter.scale(sx, sy)

        rect = QRectF(-rect_w / 2, -rect_h / 2, rect_w, rect_h)

        painter.setBrush(QBrush(fill))
        if border_w > 0 and border.alphaF() > 0:
            painter.setPen(QPen(border, border_w))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        if corner > 0:
            painter.drawRoundedRect(rect, corner, corner)
        else:
            painter.drawRect(rect)

        if bevel_size > 0 and bevel_str > 0:
            alpha_hi = int(180 * bevel_str)
            alpha_sh = int(160 * bevel_str)
            bs = bevel_size
            pen_hi = QPen(QColor(255, 255, 255, alpha_hi), bs)
            pen_hi.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_hi)
            painter.drawLine(QPointF(-rect_w / 2 + corner, -rect_h / 2 + bs / 2),
                             QPointF(rect_w / 2 - corner, -rect_h / 2 + bs / 2))
            painter.drawLine(QPointF(-rect_w / 2 + bs / 2, -rect_h / 2 + corner),
                             QPointF(-rect_w / 2 + bs / 2, rect_h / 2 - corner))
            pen_sh = QPen(QColor(0, 0, 0, alpha_sh), bs)
            pen_sh.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_sh)
            painter.drawLine(QPointF(-rect_w / 2 + corner, rect_h / 2 - bs / 2),
                             QPointF(rect_w / 2 - corner, rect_h / 2 - bs / 2))
            painter.drawLine(QPointF(rect_w / 2 - bs / 2, -rect_h / 2 + corner),
                             QPointF(rect_w / 2 - bs / 2, rect_h / 2 - corner))

        painter.end()

        return np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0


@register_node
class UICheckboxNode(BaseNode):
    def __init__(self):
        super().__init__("UI Checkbox")
        self.inputs = []
        self.add_property("Size", 40, 4, 200)
        self.add_property("Shape", 0, is_enum=True, items=["Circle", "Rounded Rect", "Rect"])
        self.add_property("Corner Radius", 6.0, 0, 100)
        self.add_property("Fill R", 0.15, 0, 1)
        self.add_property("Fill G", 0.15, 0, 1)
        self.add_property("Fill B", 0.15, 0, 1)
        self.add_property("Fill A", 1.0, 0, 1)
        self.add_property("Indicator R", 0.2, 0, 1)
        self.add_property("Indicator G", 0.8, 0, 1)
        self.add_property("Indicator B", 0.3, 0, 1)
        self.add_property("Indicator A", 1.0, 0, 1)
        self.add_property("Indicator Scale", 0.6, 0.1, 1.0)
        self.add_property("Border R", 0.5, 0, 1)
        self.add_property("Border G", 0.5, 0, 1)
        self.add_property("Border B", 0.5, 0, 1)
        self.add_property("Border A", 1.0, 0, 1)
        self.add_property("Border Width", 2.0, 0, 20)
        self.add_property("Bevel Size", 2.0, 0, 20)
        self.add_property("Bevel Strength", 0.8, 0, 1)
        self.add_transform_properties()

    def evaluate(self, frame, w, h):
        p = self.properties
        size = p["Size"].get_value(frame)
        shape = int(p["Shape"].get_value(frame))
        corner = p["Corner Radius"].get_value(frame)
        fill = QColor.fromRgbF(p["Fill R"].get_value(frame), p["Fill G"].get_value(frame),
                               p["Fill B"].get_value(frame), p["Fill A"].get_value(frame))
        indicator = QColor.fromRgbF(p["Indicator R"].get_value(frame), p["Indicator G"].get_value(frame),
                                    p["Indicator B"].get_value(frame), p["Indicator A"].get_value(frame))
        ind_scale = p["Indicator Scale"].get_value(frame)
        border = QColor.fromRgbF(p["Border R"].get_value(frame), p["Border G"].get_value(frame),
                                 p["Border B"].get_value(frame), p["Border A"].get_value(frame))
        border_w = p["Border Width"].get_value(frame)
        bevel_size = p["Bevel Size"].get_value(frame)
        bevel_str = p["Bevel Strength"].get_value(frame)
        px, py, rot, sx, sy = self.get_transform(frame)

        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(w / 2 + px * w / 2, h / 2 + py * h / 2)
        painter.rotate(rot)
        painter.scale(sx, sy)

        rect = QRectF(-size / 2, -size / 2, size, size)
        pen = QPen(border, border_w) if border_w > 0 and border.alphaF() > 0 else Qt.PenStyle.NoPen
        painter.setBrush(QBrush(fill))
        painter.setPen(pen)

        if shape == 0:
            painter.drawEllipse(rect)
        elif shape == 1:
            painter.drawRoundedRect(rect, corner, corner)
        else:
            painter.drawRect(rect)

        ind_size = size * ind_scale
        ind_rect = QRectF(-ind_size / 2, -ind_size / 2, ind_size, ind_size)
        painter.setBrush(QBrush(indicator))
        painter.setPen(Qt.PenStyle.NoPen)
        if shape == 0:
            painter.drawEllipse(ind_rect)
        elif shape == 1:
            painter.drawRoundedRect(ind_rect, corner * ind_scale, corner * ind_scale)
        else:
            painter.drawRect(ind_rect)

        if bevel_size > 0 and bevel_str > 0:
            alpha_hi = int(180 * bevel_str)
            alpha_sh = int(160 * bevel_str)
            bs = bevel_size
            if shape == 0:
                painter.setPen(QPen(QColor(255, 255, 255, alpha_hi), bs))
                painter.drawArc(rect, 45 * 16, 180 * 16)
                painter.setPen(QPen(QColor(0, 0, 0, alpha_sh), bs))
                painter.drawArc(rect, 225 * 16, 180 * 16)
            else:
                painter.setPen(QPen(QColor(255, 255, 255, alpha_hi), bs))
                painter.drawLine(QPointF(-size / 2 + corner, -size / 2 + bs / 2),
                                 QPointF(size / 2 - corner, -size / 2 + bs / 2))
                painter.drawLine(QPointF(-size / 2 + bs / 2, -size / 2 + corner),
                                 QPointF(-size / 2 + bs / 2, size / 2 - corner))
                painter.setPen(QPen(QColor(0, 0, 0, alpha_sh), bs))
                painter.drawLine(QPointF(-size / 2 + corner, size / 2 - bs / 2),
                                 QPointF(size / 2 - corner, size / 2 - bs / 2))
                painter.drawLine(QPointF(size / 2 - bs / 2, -size / 2 + corner),
                                 QPointF(size / 2 - bs / 2, size / 2 - corner))

        painter.end()

        return np.frombuffer(img.bits(), dtype=np.uint8).reshape(h, w, 4).astype(np.float32) / 255.0


# ==========================================
# 4. VISUALS
# ==========================================

# Shared palette matching behavior_node_graph.py
_C = {
    "body_bg":      QColor("#1a1a24"),
    "border":       QColor("#2e2e42"),
    "border_sel":   QColor("#4a4860"),
    "port_in":      QColor("#4a4860"),
    "port_out":     QColor("#f59e0b"),
    "port_border":  QColor("#1a1a24"),
    "port_hover":   QColor("#ffffff"),
    "text_title":   QColor("#e8e6f0"),
    "text_label":   QColor("#9090a8"),
    "edge_default": QColor("#f59e0b"),
}

class GfxSocket(QGraphicsItem):
    RADIUS = 5

    def __init__(self, parent_node, index, is_input=True, label=""):
        super().__init__(parent_node)
        self.parent_node = parent_node
        self.index = index
        self.is_input = is_input
        self.radius = self.RADIUS
        self.label = label
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self._reposition()

    def _reposition(self):
        header_h = 28
        y = header_h + 10 + self.index * 22
        x = 0 if self.is_input else self.parent_node.width
        self.setPos(x, y)

    def boundingRect(self):
        r = self.radius + 4
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = _C["port_hover"] if self._hovered else (
            _C["port_in"] if self.is_input else _C["port_out"])
        painter.setPen(QPen(_C["port_border"], 1.5))
        painter.setBrush(QBrush(fill))
        r = self.radius
        painter.drawEllipse(-r, -r, r * 2, r * 2)
        if self.label:
            painter.setPen(_C["text_label"])
            font = QFont("Segoe UI", 8)
            painter.setFont(font)
            if self.is_input:
                painter.drawText(QRectF(r + 4, -8, 60, 16),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 self.label)
            else:
                painter.drawText(QRectF(-64 - r, -8, 60, 16),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                 self.label)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

NODE_COLORS = {
    NoiseNode: QColor(80, 50, 100),
    VoronoiNode: QColor(100, 60, 120),
    ColorRampNode: QColor(100, 60, 40),
    CircleNode: QColor(40, 70, 90),
    BoxNode: QColor(40, 70, 90),
    RingNode: QColor(40, 70, 90),
    HexagonNode: QColor(40, 70, 90),
    StarNode: QColor(40, 70, 90),
    OutputNode: QColor(100, 40, 40),
    VectorRectNode: QColor(60, 90, 60),
    VectorEllipseNode: QColor(60, 90, 60),
    VectorPolygonNode: QColor(60, 90, 60),
    VectorLineNode: QColor(60, 90, 60),
    TextNode: QColor(90, 70, 50),
    ParticleEmitterNode: QColor(120, 80, 40),
    RandomSelectNode: QColor(80, 80, 100),
    BrickPatternNode: QColor(100, 50, 50),
    TileablePatternNode: QColor(110, 60, 45),
    PolarCoordsNode:  QColor(50, 100, 100),
    DisplacementNode: QColor(100, 50, 100),
    ColorAdjustNode:  QColor(100, 100, 50),
    OscillatorNode:   QColor(50, 80, 80),
    PNGSequenceNode:  QColor(40, 100, 60),
    WaveNode: QColor(40, 80, 130),
    OscilloscopeNode:    QColor(30, 110, 90),
    TransformNode:       QColor(90, 90, 50),
    # --- Modifiers ---
    BlurNode:                QColor(60, 80, 110),
    EdgeDetectNode:          QColor(110, 80, 60),
    PixelateNode:            QColor(70, 60, 110),
    ChromaticAberrationNode: QColor(110, 50, 90),
    ScanlinesNode:           QColor(50, 70, 70),
    # --- Fake Shader ---
    CRTNode:                 QColor(40, 90, 80),
    DitherNode:              QColor(80, 110, 60),
    PosterizeNode:           QColor(110, 90, 40),
    GlowNode:                QColor(120, 100, 40),
    # --- SDF Ops ---
    SDFBooleanNode:          QColor(60, 50, 120),
    SDFRepeatNode:           QColor(50, 60, 120),
    # --- UI ---
    UIPanelNode:             QColor(50, 70, 90),
    UIButtonNode:            QColor(40, 80, 110),
    UICheckboxNode:          QColor(40, 90, 80),
    # --- Compositing ---
    MergeNode:               QColor(80, 55, 110),
}

class GfxNode(QGraphicsItem):
    HEADER_H = 28
    CORNER   = 8
    WIDTH    = 150

    def __init__(self, logic_node, scene_ref):
        super().__init__()
        self.logic = logic_node
        self.scene_ref = scene_ref
        self.width = self.WIDTH
        self.height = 80
        self.setPos(logic_node.pos)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.in_sockets = []
        self.out_sockets = []
        self._init_sockets()

    def _init_sockets(self):
        smap = {
            OutputNode: [("Img",)],
            MathNode: [("A",), ("B",)],
            MixNode:   [("A",), ("B",)],
            MergeNode: [("Base",), ("Blend",)],
            CircleNode: [("Rad",)],
            GradientNode: [("Fac",)],
            ColorRampNode: [("Fac",)],
            VectorRectNode: [("W",)],
            VectorEllipseNode: [("Rx",)],
            VectorPolygonNode: [("R",)],
            TextNode:[("Fill",)],
            ParticleEmitterNode: [("Sprite",)],
            RandomSelectNode: [("1",), ("2",), ("3",), ("4",)],
            BrickPatternNode: [],
            TileCanvasNode: [("In",)],
            TileablePatternNode: [("UV",), ("Mask",), ("Tex",)],
            PolarCoordsNode: [("Img",)],
            DisplacementNode: [("Src",), ("Map",)],
            ColorAdjustNode: [("Img",)],
            OscillatorNode: [],
            PNGSequenceNode: [],
            WaveNode: [("Warp",)],
            OscilloscopeNode: [("Stroke",), ("Fill",), ("Noise",)],
            TransformNode: [("Img",)],
            # --- Modifiers ---
            BlurNode: [("Img",)],
            EdgeDetectNode: [("Img",)],
            PixelateNode: [("Img",)],
            ChromaticAberrationNode: [("Img",)],
            ScanlinesNode: [("Img",)],
            # --- Fake Shader ---
            CRTNode: [("Img",)],
            DitherNode: [("Img",)],
            PosterizeNode: [("Img",)],
            GlowNode: [("Img",)],
            # --- SDF Ops ---
            SDFBooleanNode: [("A",), ("B",)],
            SDFRepeatNode: [("SDF",)],
            # --- UI ---
            UIPanelNode: [],
            UIButtonNode: [],
            UICheckboxNode: [],
        }
        for i, (label,) in enumerate(smap.get(type(self.logic), [])):
            self.in_sockets.append(GfxSocket(self, i, True, label))
        if not isinstance(self.logic, OutputNode):
            self.out_sockets.append(GfxSocket(self, 0, False))
        slot_count = max(len(self.in_sockets), len(self.out_sockets), 1)
        self.height = self.HEADER_H + 12 + slot_count * 22 + 10

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self.boundingRect()
        corner = self.CORNER
        hdr_h  = self.HEADER_H
        w      = self.width
        sel    = self.isSelected()

        # Body (full rounded rect, dark background)
        painter.setBrush(QBrush(_C["body_bg"]))
        painter.setPen(QPen(_C["border_sel"] if sel else _C["border"],
                            2 if sel else 1))
        painter.drawRoundedRect(rect, corner, corner)

        # Header band — draw rounded rect then cover bottom half with body color
        # so only the top corners are rounded, bottom edge is flat
        hc = NODE_COLORS.get(type(self.logic), QColor(60, 60, 80))
        painter.setBrush(QBrush(hc))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, w, hdr_h), corner, corner)
        # Fill bottom strip of header to square off the bottom corners
        painter.drawRect(QRectF(0, hdr_h - corner, w, corner))

        # Title text — drawn on top of header, no clipping needed
        painter.setPen(_C["text_title"])
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(8, 0, w - 16, hdr_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self.logic.name)

        # Selection glow
        if sel:
            painter.setPen(QPen(_C["border_sel"], 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), corner, corner)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.scene():
            for item in self.scene().items():
                if isinstance(item, GfxConnection):
                    if (item.out_sock and item.out_sock.parent_node == self) or \
                       (item.in_sock and item.in_sock.parent_node == self):
                        item.update_path()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.scene().views()[0].window_ref.inspector.set_selection(self.logic)

class GfxConnection(QGraphicsPathItem):
    def __init__(self, socket_out, socket_in):
        super().__init__()
        self.out_sock = socket_out
        self.in_sock = socket_in
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        if not self.out_sock or not self.in_sock:
            return
        s = self.out_sock.scenePos()
        e = self.in_sock.scenePos()
        path = QPainterPath()
        path.moveTo(s)
        dx = max(abs(e.x() - s.x()) * 0.55, 60)
        path.cubicTo(s + QPointF(dx, 0), e - QPointF(dx, 0), e)
        self.setPath(path)
        self.setPen(QPen(_C["edge_default"], 2))


class GfxTileCanvas(GfxNode):
    """Wider card for TileCanvasNode with atlas and grid metadata."""

    WIDTH = 210

    def __init__(self, logic_node, scene_ref):
        QGraphicsItem.__init__(self)
        self.logic = logic_node
        self.scene_ref = scene_ref
        self.width = self.WIDTH
        self.height = 120
        self.setPos(logic_node.pos)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.in_sockets = []
        self.out_sockets = []
        self._init_sockets()

    def _init_sockets(self):
        self.in_sockets.append(GfxSocket(self, 0, True, "In"))
        self.out_sockets.append(GfxSocket(self, 0, False))

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect()
        sel = self.isSelected()
        corner = self.CORNER

        painter.setPen(QPen(_C["border_sel"] if sel else _C["border"], 2 if sel else 1))
        painter.setBrush(QBrush(_C["body_bg"]))
        painter.drawRoundedRect(rect, corner, corner)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(30, 100, 70)))
        painter.drawRoundedRect(QRectF(0, 0, self.width, self.HEADER_H), corner, corner)
        painter.drawRect(QRectF(0, self.HEADER_H - corner, self.width, corner))

        painter.setPen(_C["text_title"])
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(8, 0, self.width - 16, self.HEADER_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Tile Canvas",
        )

        mode_idx = int(self.logic.properties["Mode"].get_value(0))
        mode_str = (
            TileCanvasNode.MODES[mode_idx]
            if mode_idx < len(TileCanvasNode.MODES)
            else "?"
        )
        input_idx = int(self.logic.properties["Input Mode"].get_value(0))
        input_str = (
            TileCanvasNode.INPUT_MODES[input_idx]
            if input_idx < len(TileCanvasNode.INPUT_MODES)
            else "?"
        )
        sz = self.logic.tile_size()
        cols = self.logic.columns()
        rows_n = self.logic.rows()
        aw = self.logic.atlas_width()
        ah = self.logic.atlas_height()

        painter.setPen(_C["text_label"])
        painter.setFont(QFont("Segoe UI", 8))
        y = self.HEADER_H + 6
        for line in [
            f"Mode: {mode_str}",
            f"Input: {input_str}",
            f"Tile: {sz}px   {cols} x {rows_n}",
            f"Atlas: {aw} x {ah} px",
        ]:
            painter.drawText(
                QRectF(8, y, self.width - 16, 15),
                Qt.AlignmentFlag.AlignLeft,
                line,
            )
            y += 16

        show_grid = bool(self.logic.properties["Show Grid"].get_value(0))
        if show_grid:
            preview_rect = QRectF(8, y + 2, self.width - 16, 34)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(15, 35, 25)))
            painter.drawRoundedRect(preview_rect, 3, 3)

            max_cols = min(cols, 20)
            max_rows = min(rows_n, 8)
            cell_w = preview_rect.width() / max_cols
            cell_h = preview_rect.height() / max_rows
            painter.setPen(QPen(QColor(60, 180, 100, 150), 0.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            for c in range(max_cols + 1):
                x = preview_rect.x() + c * cell_w
                painter.drawLine(QPointF(x, preview_rect.y()), QPointF(x, preview_rect.bottom()))
            for r in range(max_rows + 1):
                yy = preview_rect.y() + r * cell_h
                painter.drawLine(QPointF(preview_rect.x(), yy), QPointF(preview_rect.right(), yy))

            if mode_idx == 1:
                band_h_frac = 0.25
                painter.setPen(QPen(QColor(255, 220, 80, 120), 1.0))
                for r in range(max_rows):
                    yy = preview_rect.y() + r * cell_h + cell_h * band_h_frac
                    painter.drawLine(QPointF(preview_rect.x(), yy), QPointF(preview_rect.right(), yy))

        self.height = int(y + (38 if show_grid else 4))

        if sel:
            painter.setPen(QPen(_C["border_sel"], 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), corner, corner)

# ==========================================
# 5. NAVIGATION
# ==========================================
class InfiniteScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_colors = get_default_theme().copy()
        self.setBackgroundBrush(QColor(self._theme_colors["PANEL"]))
        self.setSceneRect(-100000, -100000, 200000, 200000)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        gs = 50
        lc = QColor(self._theme_colors["BORDER"])
        left = int(rect.left()) - (int(rect.left()) % gs)
        top = int(rect.top()) - (int(rect.top()) % gs)
        lines = []
        for x in range(left, int(rect.right()), gs):
            lines.append(QPointF(x, rect.top()))
            lines.append(QPointF(x, rect.bottom()))
        for y in range(top, int(rect.bottom()), gs):
            lines.append(QPointF(rect.left(), y))
            lines.append(QPointF(rect.right(), y))
        painter.setPen(QPen(lc, 1))
        painter.drawLines(lines)

class GraphView(QGraphicsView):
    def __init__(self, scene, parent_window):
        super().__init__(scene)
        self.window_ref = parent_window
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.is_panning = False
        self.pan_start_pos = QPointF(0, 0)
        self.drag_line = QGraphicsPathItem()
        self.drag_line.setPen(QPen(QColor(255, 255, 255), 2, Qt.PenStyle.DashLine))
        self.scene().addItem(self.drag_line)
        self.drag_line.hide()
        self.start_socket = None

    def wheelEvent(self, event):
        f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        # Clamp zoom-out: don't let scale drop below 0.2
        current = self.transform().m11()
        if f < 1.0 and current * f < 0.2:
            return
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(f, f)


    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for item in self.scene().selectedItems():
                if isinstance(item, GfxNode) and not isinstance(item.logic, OutputNode):
                    # Disconnect all connections touching this node
                    for conn in [i for i in self.scene().items() if isinstance(i, GfxConnection)]:
                        if conn.out_sock.parentItem() == item or conn.in_sock.parentItem() == item:
                            conn.in_sock.parentItem().logic.inputs[conn.in_sock.index] = None
                            self.scene().removeItem(conn)
                    self.scene().removeItem(item)
                    self.window_ref.nodes.remove(item.logic)
            self.window_ref.render_preview(self.window_ref.timeline.current_frame)
        else:
            super().keyPressEvent(event)



    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = True
            self.pan_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.scene().itemAt(self.mapToScene(event.pos()), self.transform())
            if isinstance(item, GfxSocket):
                self.start_socket = item
                self.drag_line.show()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_panning:
            d = event.pos() - self.pan_start_pos
            self.pan_start_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        if self.start_socket:
            path = QPainterPath()
            path.moveTo(self.start_socket.scenePos())
            path.lineTo(self.mapToScene(event.pos()))
            self.drag_line.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self.start_socket:
            end_item = self.scene().itemAt(self.mapToScene(event.pos()), self.transform())
            if isinstance(end_item, GfxSocket) and end_item != self.start_socket:
                if self.start_socket.is_input != end_item.is_input:
                    inp = self.start_socket if self.start_socket.is_input else end_item
                    out = end_item if self.start_socket.is_input else self.start_socket
                    self.create_connection(out, inp)
            self.start_socket = None
            self.drag_line.hide()
            return
        super().mouseReleaseEvent(event)

    def create_connection(self, out_sock, in_sock):
        in_sock.parent_node.logic.inputs[in_sock.index] = out_sock.parent_node.logic
        for e in [i for i in self.scene().items() if isinstance(i, GfxConnection) and i.in_sock == in_sock]:
            self.scene().removeItem(e)
        self.scene().addItem(GfxConnection(out_sock, in_sock))
        self.window_ref.render_preview(self.window_ref.timeline.current_frame)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        pos = self.mapToScene(event.pos())

        menu.addAction("📋 Copy Nodes as Text",    lambda: self.window_ref.copy_nodes_as_text())
        menu.addAction("📝 Paste Nodes from Text", lambda: self.window_ref.paste_nodes_from_text(pos))
        menu.addSeparator()

        def spawn(cls):
            n = cls()
            n.pos = pos
            self.window_ref.add_node(n)

        # --- Generators ---
        gen = menu.addMenu("Generators")
        gen.addAction("Color",         lambda: spawn(ColorNode))
        gen.addAction("Value",         lambda: spawn(ValueNode))
        gen.addAction("Oscillator",    lambda: spawn(OscillatorNode))
        gen.addAction("Noise",         lambda: spawn(NoiseNode))
        gen.addAction("Voronoi",       lambda: spawn(VoronoiNode))
        gen.addAction("Brick / Tile",  lambda: spawn(BrickPatternNode))
        gen.addAction("Image Texture", lambda: spawn(ImageTextureNode))
        gen.addAction("PNG Sequence",  lambda: spawn(PNGSequenceNode))
        gen.addAction("Wave Texture",   lambda: spawn(WaveNode))
        gen.addAction("Oscilloscope",   lambda: spawn(OscilloscopeNode))
        gen.addAction("Tileable Patterns", lambda: spawn(TileablePatternNode))

        tilesets = menu.addMenu("TileSets")
        tilesets.addAction("Tile Canvas", lambda: spawn(TileCanvasNode))

        # --- Modifiers ---
        mod = menu.addMenu("Modifiers")
        mod.addAction("Blur",                 lambda: spawn(BlurNode))
        mod.addAction("Edge Detect",          lambda: spawn(EdgeDetectNode))
        mod.addAction("Pixelate",             lambda: spawn(PixelateNode))
        mod.addAction("Chromatic Aberration", lambda: spawn(ChromaticAberrationNode))
        mod.addAction("Scanlines",            lambda: spawn(ScanlinesNode))
        mod.addAction("Displacement / Warp",  lambda: spawn(DisplacementNode))
        mod.addAction("Polar Coordinates",    lambda: spawn(PolarCoordsNode))
        mod.addAction("Color Adjust",         lambda: spawn(ColorAdjustNode))
        mod.addAction("Transform",            lambda: spawn(TransformNode))

        # --- Fake Shader ---
        fx = menu.addMenu("Fake Shader")
        fx.addAction("CRT Effect",   lambda: spawn(CRTNode))
        fx.addAction("Dither",       lambda: spawn(DitherNode))
        fx.addAction("Posterize",    lambda: spawn(PosterizeNode))
        fx.addAction("Glow / Bloom", lambda: spawn(GlowNode))

        # --- Vector Shapes ---
        vec = menu.addMenu("Vector Shapes")
        vec.addAction("Rectangle", lambda: spawn(VectorRectNode))
        vec.addAction("Ellipse",   lambda: spawn(VectorEllipseNode))
        vec.addAction("Polygon",   lambda: spawn(VectorPolygonNode))
        vec.addAction("Line",      lambda: spawn(VectorLineNode))

        # --- SDF Shapes ---
        sdf = menu.addMenu("SDF Shapes")
        sdf.addAction("Circle",      lambda: spawn(CircleNode))
        sdf.addAction("Box",         lambda: spawn(BoxNode))
        sdf.addAction("Ring",        lambda: spawn(RingNode))
        sdf.addAction("Hexagon",     lambda: spawn(HexagonNode))
        sdf.addAction("Star",        lambda: spawn(StarNode))
        sdf.addAction("SDF Boolean", lambda: spawn(SDFBooleanNode))
        sdf.addAction("SDF Repeat",  lambda: spawn(SDFRepeatNode))

        # --- Text ---
        txt = menu.addMenu("Text")
        txt.addAction("Text", lambda: spawn(TextNode))

        # --- Particles ---
        prt = menu.addMenu("Particles")
        prt.addAction("Particle Emitter", lambda: spawn(ParticleEmitterNode))
        prt.addAction("Random Select",    lambda: spawn(RandomSelectNode))

        # --- Color ---
        col = menu.addMenu("Color")
        col.addAction("Color Ramp",    lambda: spawn(ColorRampNode))
        col.addAction("Gradient Map",  lambda: spawn(GradientNode))

        # --- Math ---
        mth = menu.addMenu("Math / Blend")
        mth.addAction("Math",  lambda: spawn(MathNode))
        mth.addAction("Mix",   lambda: spawn(MixNode))
        mth.addAction("Merge", lambda: spawn(MergeNode))

        # --- UI ---
        ui = menu.addMenu("UI")
        ui.addAction("UI Panel",    lambda: spawn(UIPanelNode))
        ui.addAction("UI Button",   lambda: spawn(UIButtonNode))
        ui.addAction("UI Checkbox", lambda: spawn(UICheckboxNode))

        menu.exec(event.globalPos())

# ==========================================
# 6. COLOR RAMP WIDGET
# ==========================================
class ColorRampWidget(QWidget):
    changed = Signal()

    def __init__(self, ramp_node):
        super().__init__()
        self.node = ramp_node
        self.setFixedHeight(60)
        self.setMinimumWidth(200)
        self.dragging_idx = -1
        self.selected_idx = 0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_y = 5
        bar_h = 25
        w = self.width()
        margin = 8

        stops = self.node.color_stops
        if len(stops) >= 2:
            for px in range(margin, w - margin):
                t = (px - margin) / max(w - 2 * margin, 1)
                r, g, b, a = self.node._get_color_at(t, 0)
                p.setPen(QColor(int(r * 255), int(g * 255), int(b * 255)))
                p.drawLine(px, bar_y, px, bar_y + bar_h)
        else:
            p.fillRect(margin, bar_y, w - 2 * margin, bar_h, QColor(50, 50, 50))

        p.setPen(QPen(QColor(100, 100, 100), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(margin, bar_y, w - 2 * margin, bar_h)

        handle_y = bar_y + bar_h + 2
        for i, s in enumerate(stops):
            x = margin + s['pos'] * (w - 2 * margin)
            color = QColor(int(s['r'] * 255), int(s['g'] * 255), int(s['b'] * 255))
            pts = [QPointF(x, handle_y), QPointF(x - 5, handle_y + 12), QPointF(x + 5, handle_y + 12)]
            p.setBrush(color)
            border = QColor(255, 200, 0) if i == self.selected_idx else QColor(180, 180, 180)
            p.setPen(QPen(border, 2 if i == self.selected_idx else 1))
            p.drawPolygon(pts)

    def _pos_to_stop_idx(self, x):
        margin = 8
        w = self.width()
        best = -1
        best_dist = 15
        for i, s in enumerate(self.node.color_stops):
            sx = margin + s['pos'] * (w - 2 * margin)
            d = abs(x - sx)
            if d < best_dist:
                best = i
                best_dist = d
        return best

    def _x_to_t(self, x):
        margin = 8
        w = self.width()
        return max(0.0, min(1.0, (x - margin) / max(w - 2 * margin, 1)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._pos_to_stop_idx(event.pos().x())
            if idx >= 0:
                self.selected_idx = idx
                self.dragging_idx = idx
            else:
                t = self._x_to_t(event.pos().x())
                r, g, b, a = self.node._get_color_at(t, 0)
                self.node.add_stop(t, r, g, b, a)
                self.selected_idx = next(i for i, s in enumerate(self.node.color_stops) if abs(s['pos'] - t) < 0.001)
                self.changed.emit()
            self.update()

    def mouseMoveEvent(self, event):
        if self.dragging_idx >= 0:
            t = self._x_to_t(event.pos().x())
            self.node.color_stops[self.dragging_idx]['pos'] = t
            self.node._sort_stops()
            self.selected_idx = self.dragging_idx
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, event):
        self.dragging_idx = -1

    def mouseDoubleClickEvent(self, event):
        idx = self._pos_to_stop_idx(event.pos().x())
        if idx >= 0:
            self.selected_idx = idx
            s = self.node.color_stops[idx]
            col = QColorDialog.getColor(
                QColor(int(s['r'] * 255), int(s['g'] * 255), int(s['b'] * 255), int(s['a'] * 255)),
                self, "Stop Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if col.isValid():
                s['r'] = col.redF()
                s['g'] = col.greenF()
                s['b'] = col.blueF()
                s['a'] = col.alphaF()
                self.update()
                self.changed.emit()

    def contextMenuEvent(self, event):
        idx = self._pos_to_stop_idx(event.pos().x())
        if idx >= 0 and len(self.node.color_stops) > 2:
            menu = QMenu(self)
            menu.addAction("Delete Stop", lambda: self._delete_stop(idx))
            menu.exec(event.globalPos())

    def _delete_stop(self, idx):
        self.node.remove_stop(idx)
        self.selected_idx = max(0, min(self.selected_idx, len(self.node.color_stops) - 1))
        self.update()
        self.changed.emit()

# ==========================================
# 7. INSPECTOR
# ==========================================
class Inspector(QWidget):
    render_needed = Signal()

    def __init__(self, timeline_ref):
        super().__init__()
        self.setMinimumWidth(300)
        self.timeline_ref = timeline_ref
        self.current_node = None
        
        # Create scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.scroll_content = QWidget()
        self.layout = QVBoxLayout()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_content.setLayout(self.layout)
        self.scroll_area.setWidget(self.scroll_content)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)
        self.setLayout(main_layout)
        
        self.inputs = {}
        self.color_btn = None
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(30)
        self._render_timer.timeout.connect(lambda: self.render_needed.emit())

    def set_selection(self, logic_node):
        self.current_node = logic_node
        self.inputs.clear()
        self.color_btn = None
        
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        
        if not logic_node:
            self.layout.addWidget(QLabel("No Selection"))
            return
        
        lbl = QLabel(f"{logic_node.name} Properties")
        lbl.setStyleSheet("font-weight: bold; margin-bottom: 10px; color: white;")
        self.layout.addWidget(lbl)
        
        if isinstance(logic_node, ImageTextureNode):
            load_btn = QPushButton("Load Image")
            load_btn.clicked.connect(lambda: self.load_texture_image(logic_node))
            self.layout.addWidget(load_btn)
        
        if isinstance(logic_node, PNGSequenceNode):
            load_btn = QPushButton("Load PNG Folder")
            load_btn.clicked.connect(lambda: self.load_png_sequence_folder(logic_node))
            self.layout.addWidget(load_btn)
            if logic_node.folder_path:
                info_lbl = QLabel(f"Loaded: {len(logic_node.frame_paths)} frames")
                info_lbl.setStyleSheet("color: #8f8; font-size: 10px;")
                self.layout.addWidget(info_lbl)
        
        if isinstance(logic_node, ColorNode):
            row = QHBoxLayout()
            self.color_btn = QPushButton()
            self.color_btn.setFixedHeight(30)
            self.color_btn.clicked.connect(self.open_color_dialog)
            ka = QPushButton("Key All")
            ka.setFixedWidth(50)
            ka.clicked.connect(self.keyframe_current_color)
            row.addWidget(self.color_btn)
            row.addWidget(ka)
            self.layout.addLayout(row)
        
        if isinstance(logic_node, ColorRampNode):
            ramp_lbl = QLabel("Double-click stop to change color\nClick empty space to add, right-click to remove")
            ramp_lbl.setStyleSheet("color: #999; font-size: 10px; margin-bottom: 4px;")
            self.layout.addWidget(ramp_lbl)
            self.ramp_widget = ColorRampWidget(logic_node)
            self.ramp_widget.changed.connect(lambda: self._render_timer.start())
            self.layout.addWidget(self.ramp_widget)
        
        if isinstance(logic_node, ParticleEmitterNode):
            center_btn = QPushButton("Center Emitter")
            center_btn.clicked.connect(lambda: self.center_emitter(logic_node))
            self.layout.addWidget(center_btn)
        
        # Group properties
        transform_props = ["Pos X", "Pos Y", "Rotation", "Scale X", "Scale Y"]
        fill_props = ["Fill R", "Fill G", "Fill B", "Fill A"]
        stroke_props = ["Stroke R", "Stroke G", "Stroke B", "Stroke A", "Stroke Width"]
        
        # Simple particle groups
        particle_basic = ["Mode", "Amount", "Lifetime"]
        particle_movement = ["Direction", "Spread", "Speed", "Gravity"]
        particle_appearance = ["Size", "Fade Out", "Shrink", "Blend"]
        particle_sprite = ["Built-in", "Color R", "Color G", "Color B"]
        particle_position = ["Emitter X", "Emitter Y", "Seed"]
        
        all_grouped = (transform_props + fill_props + stroke_props + 
                      particle_basic + particle_movement + particle_appearance + 
                      particle_sprite + particle_position)
        
        # Regular properties first (ungrouped)
        for pn, po in logic_node.properties.items():
            if pn not in all_grouped:
                self.add_property_widget(pn, po)
        
        # Particle basic properties
        basic_present = [p for p in particle_basic if p in logic_node.properties]
        if basic_present:
            self.add_section_header("Basic")
            for pn in basic_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Particle movement properties
        movement_present = [p for p in particle_movement if p in logic_node.properties]
        if movement_present:
            self.add_section_header("Movement")
            for pn in movement_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Particle appearance properties
        appearance_present = [p for p in particle_appearance if p in logic_node.properties]
        if appearance_present:
            self.add_section_header("Appearance")
            for pn in appearance_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Particle sprite properties
        sprite_present = [p for p in particle_sprite if p in logic_node.properties]
        if sprite_present:
            self.add_section_header("Built-in Sprite")
            for pn in sprite_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Particle position properties
        position_present = [p for p in particle_position if p in logic_node.properties]
        if position_present:
            self.add_section_header("Position")
            for pn in position_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Fill properties (if any)
        fill_present = [p for p in fill_props if p in logic_node.properties]
        if fill_present:
            self.add_section_header("Fill")
            for pn in fill_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Stroke properties (if any)
        stroke_present = [p for p in stroke_props if p in logic_node.properties]
        if stroke_present:
            self.add_section_header("Stroke")
            for pn in stroke_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        # Transform properties (if any)
        transform_present = [p for p in transform_props if p in logic_node.properties]
        if transform_present:
            self.add_section_header("Transform")
            for pn in transform_present:
                self.add_property_widget(pn, logic_node.properties[pn])
        
        self.layout.addStretch()
        self.update_ui_from_frame()

    def add_section_header(self, text):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #555;")
        self.layout.addWidget(sep)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 11px; margin-top: 5px;")
        self.layout.addWidget(lbl)

    def load_texture_image(self, node):
        path, _ = QFileDialog.getOpenFileName(self, "Load Image", "", "Images (*.png *.jpg *.bmp)")
        if path:
            node.load_image(path)
            self.render_needed.emit()

    def load_png_sequence_folder(self, node):
        folder = QFileDialog.getExistingDirectory(self, "Select PNG Sequence Folder")
        if folder:
            count = node.load_folder(folder)
            self.set_selection(node)  # Refresh to show frame count
            self.render_needed.emit()

    def open_color_dialog(self):
        if not self.current_node:
            return
        f = self.timeline_ref.current_frame
        r = int(self.current_node.properties["Red"].get_value(f) * 255)
        g = int(self.current_node.properties["Green"].get_value(f) * 255)
        b = int(self.current_node.properties["Blue"].get_value(f) * 255)
        a = int(self.current_node.properties["Alpha"].get_value(f) * 255)
        col = QColorDialog.getColor(QColor(r, g, b, a), self, "Pick Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if col.isValid():
            self.current_node.properties["Red"].set_override(f, col.redF())
            self.current_node.properties["Green"].set_override(f, col.greenF())
            self.current_node.properties["Blue"].set_override(f, col.blueF())
            self.current_node.properties["Alpha"].set_override(f, col.alphaF())
            self.update_ui_from_frame()
            self.render_needed.emit()

    def keyframe_current_color(self):
        if not self.current_node:
            return
        f = self.timeline_ref.current_frame
        for c in ["Red", "Green", "Blue", "Alpha"]:
            self.current_node.properties[c].set_keyframe(f, self.current_node.properties[c].get_value(f))
        self.update_ui_from_frame()
        self.timeline_ref.update()

    def center_emitter(self, node):
        """Center the particle emitter to the current project dimensions"""
        node.properties["Emitter X"].default_value = PROJECT.width / 2
        node.properties["Emitter Y"].default_value = PROJECT.height / 2
        # Clear any keyframes/overrides so defaults take effect
        node.properties["Emitter X"].keyframes.clear()
        node.properties["Emitter Y"].keyframes.clear()
        node.properties["Emitter X"].clear_override()
        node.properties["Emitter Y"].clear_override()
        self.update_ui_from_frame()
        self.render_needed.emit()

    def add_property_widget(self, name, prop):
        container = QWidget()
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        container.setLayout(h)
        lbl = QLabel(name)
        lbl.setFixedWidth(80)
        btn = QToolButton()
        btn.setText("◇")
        btn.setCheckable(True)
        btn.setStyleSheet("QToolButton:checked { color: yellow; font-weight: bold; }")
        
        if prop.is_string:
            # Check if this is the Font property to use the native system font picker
            if name == "Font":
                w = QFontComboBox()
                w.setCurrentFont(QFont(str(prop.default_value)))
                w.currentFontChanged.connect(lambda f: self.on_val(prop, f.family(), w))
            else:
                w = QLineEdit()
                w.setText(str(prop.default_value))
                w.textChanged.connect(lambda t: self.on_val(prop, t, w))
        elif prop.is_bool:
            w = QCheckBox()
            w.setChecked(bool(prop.default_value))
            w.stateChanged.connect(lambda s: self.on_val(prop, 1.0 if s else 0.0, w))
        elif prop.is_enum:
            w = QComboBox()
            w.addItems(prop.enum_items)
            w.setCurrentIndex(int(prop.default_value))
            w.currentIndexChanged.connect(lambda i: self.on_val(prop, float(i), w))
        else:
            w = QDoubleSpinBox()
            w.setRange(prop.min_val, prop.max_val)
            w.setSingleStep(0.1)
            w.setDecimals(3)
            w.setValue(prop.default_value)
            w.valueChanged.connect(lambda v: self.on_val(prop, v, w))

        def gv():
            if prop.is_string:
                # Handle getting the value from either a Font Box or a Line Edit
                if isinstance(w, QFontComboBox):
                    return w.currentFont().family()
                return w.text()
            elif prop.is_bool:
                return 1.0 if w.isChecked() else 0.0
            elif prop.is_enum:
                return float(w.currentIndex())
            else:
                return w.value()

        btn.clicked.connect(lambda: self.toggle_kf(prop, gv(), btn))
        h.addWidget(lbl)
        h.addWidget(w)
        h.addWidget(btn)
        self.layout.addWidget(container)
        self.inputs[name] = (w, btn)

    def on_val(self, prop, val, widget):
        f = self.timeline_ref.current_frame
        if f in prop.keyframes:
            prop.keyframes[f] = val
        else:
            prop.set_override(f, val)
        self.update_color_btn()
        self._render_timer.start()

    def toggle_kf(self, prop, val, btn):
        f = self.timeline_ref.current_frame
        if btn.isChecked():
            prop.set_keyframe(f, val)
        else:
            prop.remove_keyframe(f)
        self.timeline_ref.update()
        self.update_ui_from_frame()

    def update_ui_from_frame(self):
        if not self.current_node:
            return
        f = self.timeline_ref.current_frame
        for name, (w, btn) in self.inputs.items():
            if name not in self.current_node.properties:
                continue
            prop = self.current_node.properties[name]
            prop.clear_override()
            val = prop.get_value(f)
            w.blockSignals(True)
            if prop.is_string:
                # Handle setting the value for either a Font Box or a Line Edit
                if isinstance(w, QFontComboBox):
                    w.setCurrentFont(QFont(str(val)))
                else:
                    w.setText(str(val))
            elif prop.is_bool:
                w.setChecked(bool(val))
            elif prop.is_enum:
                w.setCurrentIndex(int(val))
            else:
                w.setValue(val)
            if f in prop.keyframes:
                btn.setChecked(True)
                btn.setText("◆")
            else:
                btn.setChecked(False)
                btn.setText("◇")
            w.blockSignals(False)
        self.update_color_btn()

    def update_color_btn(self):
        if self.color_btn and isinstance(self.current_node, ColorNode):
            f = self.timeline_ref.current_frame
            r = int(self.current_node.properties["Red"].get_value(f) * 255)
            g = int(self.current_node.properties["Green"].get_value(f) * 255)
            b = int(self.current_node.properties["Blue"].get_value(f) * 255)
            self.color_btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 2px solid white; border-radius: 4px;")

# ==========================================
# 8. TIMELINE
# ==========================================
class TimelineWidget(QWidget):
    frame_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(60)
        self.current_frame = 0
        self.playing = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.advance_frame)
        self.main_window = None

    def set_main_ref(self, w):
        self.main_window = w

    def advance_frame(self):
        self.current_frame = (self.current_frame + 1) % PROJECT.duration
        self.frame_changed.emit(self.current_frame)
        self.update()

    def mousePressEvent(self, event):
        f = int(event.pos().x() / (self.width() / PROJECT.duration))
        self.current_frame = max(0, min(f, PROJECT.duration - 1))
        self.frame_changed.emit(self.current_frame)
        self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        w = self.width()
        step = w / PROJECT.duration
        theme = getattr(self.main_window, "_theme_colors", get_default_theme())
        painter.fillRect(self.rect(), QColor(theme["PANEL"]))
        painter.setPen(QColor(theme["BORDER"]))
        for i in range(PROJECT.duration):
            x = i * step
            painter.drawLine(int(x), 40, int(x), 60)
            if i % 10 == 0:
                painter.drawText(int(x) + 2, 55, str(i))
        if self.main_window and self.main_window.inspector.current_node:
            nd = self.main_window.inspector.current_node
            painter.setBrush(QColor(theme["WARNING"]))
            painter.setPen(Qt.PenStyle.NoPen)
            keys = set()
            for p in nd.properties.values():
                keys.update(p.keyframes.keys())
            for k in keys:
                if k < PROJECT.duration:
                    painter.drawEllipse(QPointF((k * step) + (step / 2), 30), 3, 3)
        px = self.current_frame * step
        current_fill = QColor(theme["ACCENT"])
        current_fill.setAlpha(100)
        painter.setBrush(current_fill)
        painter.drawRect(int(px), 0, int(step), 60)

# ==========================================
# 9. SERIALIZATION
# ==========================================
class ProjectSerializer:
    @staticmethod
    def save(main_window, filepath):
        data = {
            'version': 1,
            'project': PROJECT.to_dict(),
            'nodes': [],
            'connections': []
        }
        
        # Build node ID map
        node_map = {}
        for i, node in enumerate(main_window.nodes):
            node.node_id = i
            node_map[id(node)] = i
        
        # Serialize nodes
        for node in main_window.nodes:
            # Update position from graphics item
            for item in main_window.scene.items():
                if isinstance(item, GfxNode) and item.logic == node:
                    node.pos = item.pos()
                    break
            data['nodes'].append(node.to_dict())
        
        # Serialize connections
        for node in main_window.nodes:
            for input_idx, input_node in enumerate(node.inputs):
                if input_node is not None:
                    data['connections'].append({
                        'from_node': node_map.get(id(input_node)),
                        'to_node': node.node_id,
                        'to_input': input_idx
                    })
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load(main_window, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Clear existing
        main_window.clear_graph()
        
        # Load project settings
        PROJECT.from_dict(data.get('project', {}))
        main_window.timeline.timer.setInterval(int(1000 / PROJECT.fps))
        main_window.update_preview_bg()
        main_window.preview_mode_combo.setCurrentText(PROJECT.preview_mode)
        main_window.timeline.update()
        
        # Create nodes
        node_map = {}
        for node_data in data.get('nodes', []):
            node_type = node_data.get('type')
            if node_type in NODE_TYPES:
                node = NODE_TYPES[node_type]()
                node.from_dict(node_data)
                main_window.add_node(node)
                node_map[node_data.get('node_id')] = node
                if isinstance(node, OutputNode):
                    main_window.output_node = node
        
        # Create connections
        for conn in data.get('connections', []):
            from_id = conn.get('from_node')
            to_id = conn.get('to_node')
            to_input = conn.get('to_input', 0)
            
            if from_id in node_map and to_id in node_map:
                from_node = node_map[from_id]
                to_node = node_map[to_id]
                if to_input < len(to_node.inputs):
                    to_node.inputs[to_input] = from_node
        
        # Rebuild visual connections
        main_window.rebuild_connections()
        main_window.render_preview(main_window.timeline.current_frame)

# ==========================================
# ==========================================
# 9b. EXPORT ANIMATION DIALOG
# ==========================================
class ExportAnimationDialog(QDialog):
    """Dialog for exporting animations as .ani or .trans files with spritesheet."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Animation")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # Export type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems([".ani (General Animation)", ".trans (Scene Transition)"])
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)
        
        # Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit("my_animation")
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)
        
        # Sheet count
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Spritesheet count:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.addItems(["1", "2", "4", "8", "16", "Auto (best quality)"])
        self.sheet_combo.setCurrentIndex(0)
        sheet_row.addWidget(self.sheet_combo)
        layout.addLayout(sheet_row)

        # Quality estimate label
        self.quality_label = QLabel("")
        self.quality_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.quality_label)

        self.sheet_combo.currentIndexChanged.connect(self._update_quality_estimate)
        self.type_combo.currentIndexChanged.connect(self._update_quality_estimate)

        # Info
        info = QLabel("This will render all frames, pack them into spritesheets,\nand save metadata for the Lua exporter.")
        info.setStyleSheet("color: #888; font-size: 10px; margin: 10px 0;")
        layout.addWidget(info)
        
        # Buttons
        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export")
        export_btn.setStyleSheet("background-color: #2a6e2a; font-weight: bold;")
        export_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
    
    def _get_sheet_count(self):
        """Return selected sheet count, or 0 for Auto."""
        idx = self.sheet_combo.currentIndex()
        mapping = [1, 2, 4, 8, 16, 0]  # 0 = auto
        return mapping[idx]

    def _update_quality_estimate(self):
        """Show estimated per-frame resolution based on sheet count selection."""
        is_trans = self.type_combo.currentIndex() == 1
        if is_trans:
            self.quality_label.setText("Transitions use fixed 240×136 frames.")
            return
        w, h = PROJECT.width, PROJECT.height
        total = PROJECT.duration
        if total < 1 or w < 1 or h < 1:
            self.quality_label.setText("")
            return
        sheet_count = self._get_sheet_count()
        MAX_SHEET = 2048
        if sheet_count == 0:
            # Auto: find minimum sheets for full resolution
            sheet_count = 1
            while True:
                fpg = int(np.ceil(total / sheet_count))
                cols = int(np.ceil(np.sqrt(fpg)))
                rows = int(np.ceil(fpg / cols))
                if cols * w <= MAX_SHEET and rows * h <= MAX_SHEET:
                    break
                sheet_count += 1
            self.quality_label.setText(f"Auto: {sheet_count} sheets — full resolution {w}×{h} per frame")
        else:
            fpg = int(np.ceil(total / sheet_count))
            cols = int(np.ceil(np.sqrt(fpg)))
            rows = int(np.ceil(fpg / cols))
            sw = cols * w
            sh = rows * h
            if sw > MAX_SHEET or sh > MAX_SHEET:
                scale = min(MAX_SHEET / sw, MAX_SHEET / sh)
                est_w = max(1, int(w * scale))
                est_h = max(1, int(h * scale))
                self.quality_label.setText(f"Estimated frame size: {est_w}×{est_h} (downscaled from {w}×{h})")
            else:
                self.quality_label.setText(f"Full resolution: {w}×{h} per frame")

    def get_settings(self):
        return {
            'type': 'trans' if self.type_combo.currentIndex() == 1 else 'ani',
            'name': self.name_edit.text() or 'animation',
            'sheet_count': self._get_sheet_count(),
        }

# ==========================================
# ==========================================
# 10. MAIN TAB WIDGET
# ==========================================
class AnimationGraphTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_colors = get_default_theme().copy()
        self.nodes = []
        self.output_node = None
        self.scene = InfiniteScene()
        self.scene._theme_colors = self._theme_colors
        self.view = GraphView(self.scene, self)
        self.timeline = TimelineWidget()
        self.timeline.set_main_ref(self)
        self.inspector = Inspector(self.timeline)
        self.preview_lbl = QLabel()
        self.preview_lbl.setStyleSheet(f"border: 2px solid {self._theme_colors['BORDER']};")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.setup_ui()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        
        self.timeline.frame_changed.connect(self.inspector.update_ui_from_frame)
        self.timeline.frame_changed.connect(lambda f: self.render_preview(f))
        self.inspector.render_needed.connect(lambda: self.render_preview(self.timeline.current_frame))
        self.init_graph()
        self.update_preview_bg()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and self._is_graph_widget(obj):
            if self._handle_graph_hotkey(event):
                return True
        return super().eventFilter(obj, event)

    def _is_graph_widget(self, obj):
        if not isinstance(obj, QWidget):
            return False
        return obj is self or self.isAncestorOf(obj)

    def _focus_blocks_graph_hotkeys(self):
        focus = QApplication.focusWidget()
        current = focus if isinstance(focus, QWidget) else None
        while current is not None:
            if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit, QFontComboBox)):
                return True
            if isinstance(current, QComboBox) and current.isEditable():
                return True
            current = current.parentWidget()
        return False

    def _keyframe_node_properties(self, node):
        if node is None:
            return 0
        frame = self.timeline.current_frame
        count = 0
        for prop in node.properties.values():
            prop.set_keyframe(frame, prop.get_value(frame))
            count += 1
        return count

    def _refresh_keyframe_ui(self):
        self.inspector.update_ui_from_frame()
        self.timeline.update()
        self.render_preview(self.timeline.current_frame)

    def keyframe_selected_node(self):
        node = self.inspector.current_node
        if node is None:
            self._show_toast("No node selected")
            return
        count = self._keyframe_node_properties(node)
        self._refresh_keyframe_ui()
        self._show_toast(f"Keyframed {count} parameter(s) on {node.name}")

    def keyframe_all_nodes(self):
        keyed_props = 0
        keyed_nodes = 0
        for node in self.nodes:
            count = self._keyframe_node_properties(node)
            if count > 0:
                keyed_props += count
                keyed_nodes += 1
        self._refresh_keyframe_ui()
        self._show_toast(f"Keyframed {keyed_props} parameter(s) across {keyed_nodes} node(s)")

    def _handle_graph_hotkey(self, event):
        if event.key() != Qt.Key.Key_I:
            return False
        if self._focus_blocks_graph_hotkeys():
            return False
        if event.isAutoRepeat():
            return True
        mods = event.modifiers()
        disallowed_mods = (
            Qt.KeyboardModifier.ShiftModifier |
            Qt.KeyboardModifier.AltModifier |
            Qt.KeyboardModifier.MetaModifier
        )
        if mods & disallowed_mods:
            return False
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.keyframe_all_nodes()
            return True
        if mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            self.keyframe_selected_node()
            return True
        return False

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def setup_ui(self):
        left = QWidget()
        ll = QVBoxLayout()
        
        # File buttons
        file_row = QHBoxLayout()
        btn_new = QPushButton("New")
        btn_new.clicked.connect(self.file_new)
        btn_open = QPushButton("Open")
        btn_open.clicked.connect(self.file_open)
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.file_save)
        btn_saveas = QPushButton("Save As")
        btn_saveas.clicked.connect(self.file_save_as)
        file_row.addWidget(btn_new)
        file_row.addWidget(btn_open)
        file_row.addWidget(btn_save)
        file_row.addWidget(btn_saveas)
        ll.addLayout(file_row)
        
        btn_row = QHBoxLayout()
        bs = QPushButton("⚙ Settings")
        bs.clicked.connect(self.open_settings)
        ba = QPushButton("＋ Add Node")
        ba.clicked.connect(self.open_add_node_menu)
        btn_row.addWidget(bs)
        btn_row.addWidget(ba)
        ll.addLayout(btn_row)
        # Preview mode dropdown
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview Mode:"))
        self.preview_mode_combo = QComboBox()
        self.preview_mode_combo.addItems(["Fit", "Actual Size", "Full Screen Context"])
        self.preview_mode_combo.setCurrentText(PROJECT.preview_mode)
        self.preview_mode_combo.currentTextChanged.connect(self.on_preview_mode_changed)
        preview_row.addWidget(self.preview_mode_combo)
        ll.addLayout(preview_row)

        # Fixed-size preview label: 320x180 locks the 16:9 ratio of 960x544
        self.preview_lbl.setFixedSize(320, 180)
        ll.addWidget(self.preview_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        bp = QPushButton("▶ Play / Stop")
        bp.clicked.connect(self.toggle_play)
        ll.addWidget(bp)
        be = QPushButton("Export PNG Sequence")
        #be.setStyleSheet("background-color: #2a6e2a; font-weight: bold; padding: 8px;")
        be.clicked.connect(self.export_png_sequence)
        ll.addWidget(be)

        bf = QPushButton("Export Single Frame")
        #bf.setStyleSheet("background-color: #2a5a7a; font-weight: bold; padding: 8px;")
        bf.clicked.connect(self.export_single_frame)
        ll.addWidget(bf)

        bv = QPushButton("Export Animation/Transition (.ani/.trans)")
        #bv.setStyleSheet("background-color: #6a2a9e; font-weight: bold; padding: 8px;")
        bv.clicked.connect(self.export_for_vita)
        ll.addWidget(bv)
        ll.addStretch()
        left.setLayout(ll)
        
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.view)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(1, 3)
        
        ml = QVBoxLayout()
        ml.addWidget(splitter)
        ml.addWidget(self.timeline)
        
        # Use setLayout instead of setCentralWidget
        self.setLayout(ml)

    def restyle(self, colors: dict):
        old = dict(self._theme_colors)
        merged = get_default_theme()
        merged.update(colors or {})
        self._theme_colors = merged
        self.scene._theme_colors = merged
        self.scene.setBackgroundBrush(QColor(merged["PANEL"]))
        replace_widget_theme_colors(self, old, merged)
        self.view.drag_line.setPen(QPen(QColor(merged["TEXT"]), 2, Qt.PenStyle.DashLine))
        self.update_preview_bg()
        self.scene.update(self.scene.sceneRect())
        self.view.viewport().update()
        self.timeline.update()
        self.preview_lbl.update()

    def file_new(self):
        self.clear_graph()
        PROJECT.file_path = None
        PROJECT.width = 960
        PROJECT.height = 544
        PROJECT.fps = 30
        PROJECT.duration = 60
        PROJECT.bg_style = "Checkerboard"
        PROJECT.preview_divisor = 4
        self.init_graph()
        self.update_preview_bg()
        self.timeline.current_frame = 0
        self.timeline.update()
        self.render_preview(0)

    def file_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Animation", "", "Animation Files (*.ani)")
        if path:
            ProjectSerializer.load(self, path)
            PROJECT.file_path = path

    def file_save(self):
        if PROJECT.file_path:
            ProjectSerializer.save(self, PROJECT.file_path)
        else:
            self.file_save_as()

    def file_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Animation", "", "Animation Files (*.ani)")
        if path:
            if not path.endswith('.ani'):
                path += '.ani'
            ProjectSerializer.save(self, path)
            PROJECT.file_path = path

    def clear_graph(self):
        self.nodes.clear()
        self.output_node = None
        self.scene.clear()
        self.view.drag_line = QGraphicsPathItem()
        self.view.drag_line.setPen(QPen(QColor(255, 255, 255), 2, Qt.PenStyle.DashLine))
        self.scene.addItem(self.view.drag_line)
        self.view.drag_line.hide()
        self.inspector.set_selection(None)

    def rebuild_connections(self):
        gfx_map = {}
        for item in self.scene.items():
            if isinstance(item, GfxNode):
                gfx_map[item.logic] = item
        for node in self.nodes:
            if node in gfx_map:
                gfx_node = gfx_map[node]
                for input_idx, input_node in enumerate(node.inputs):
                    if input_node is not None and input_node in gfx_map:
                        in_gfx = gfx_map[input_node]
                        if input_idx < len(gfx_node.in_sockets) and len(in_gfx.out_sockets) > 0:
                            self.scene.addItem(GfxConnection(
                                in_gfx.out_sockets[0],
                                gfx_node.in_sockets[input_idx]
                            ))

    def init_graph(self):
        out = OutputNode()
        out.pos = QPointF(400, 100)
        self.add_node(out)
        self.output_node = out

    def add_node(self, n):
        self.nodes.append(n)
        gfx = GfxTileCanvas(n, self.scene) if isinstance(n, TileCanvasNode) else GfxNode(n, self.scene)
        self.scene.addItem(gfx)

    def _get_connected_tile_canvas(self):
        if not self.output_node:
            return None

        stack = [self.output_node]
        seen = set()
        while stack:
            node = stack.pop()
            node_key = id(node)
            if node_key in seen:
                continue
            seen.add(node_key)
            if isinstance(node, TileCanvasNode):
                return node
            stack.extend(inp for inp in getattr(node, "inputs", []) if inp is not None)
        return None

    def _draw_tile_grid_overlay(self, arr, tile_sz, cols, rows_n):
        result = arr.copy()
        h, w = result.shape[:2]
        line_color = np.array([0.3, 1.0, 0.5, 1.0], dtype=np.float32)
        alpha = 0.4

        for c in range(1, cols):
            x = c * tile_sz
            if x < w:
                result[:, x] = result[:, x] * (1 - alpha) + line_color * alpha

        for r in range(1, rows_n):
            y = r * tile_sz
            if y < h:
                result[y, :] = result[y, :] * (1 - alpha) + line_color * alpha

        return result

    # ------------------------------------------------------------------
    # LLM Copy / Paste
    # ------------------------------------------------------------------

    def _show_toast(self, msg, duration_ms=2000):
        lbl = QLabel(msg, self.view)
        lbl.setStyleSheet(
            "background: rgba(30,30,30,210); color: #eee; padding: 6px 12px;"
            "border-radius: 6px; font-size: 12px;"
        )
        lbl.adjustSize()
        lbl.move((self.view.width() - lbl.width()) // 2, 12)
        lbl.show()
        QTimer.singleShot(duration_ms, lbl.deleteLater)

    def copy_nodes_as_text(self):
        selected = [item for item in self.scene.selectedItems() if isinstance(item, GfxNode)]
        text = ani_canvas_to_text(self, selected_only=bool(selected))
        QApplication.clipboard().setText(text)
        count = text.count("\nNODE ") + (1 if text.startswith("NODE ") else 0)
        self._show_toast(f"📋 {count} node(s) copied as text")

    def paste_nodes_from_text(self, scene_pos=None):
        text = QApplication.clipboard().text()
        if not text.strip():
            self._show_toast("⚠ Clipboard is empty")
            return

        node_specs, connection_specs, warnings = ani_text_to_nodes(text)
        if not node_specs:
            self._show_toast("⚠ No valid NODE lines found in clipboard")
            return

        if scene_pos is None:
            scene_pos = self.view.mapToScene(self.view.rect().center())

        positions = [spec["pos"] for spec in node_specs]
        distinct_positions = {(round(p.x(), 3), round(p.y(), 3)) for p in positions}
        use_auto_layout = len(distinct_positions) <= 1

        if not use_auto_layout:
            xs = [p.x() for p in positions]
            ys = [p.y() for p in positions]
            if (max(xs) - min(xs) < 8.0) and (max(ys) - min(ys) < 8.0):
                use_auto_layout = True

        cx = sum(p.x() for p in positions) / len(positions)
        cy = sum(p.y() for p in positions) / len(positions)

        sorted_specs = list(node_specs)
        if use_auto_layout:
            sorted_specs.sort(key=lambda spec: spec.get("local_id") if spec.get("local_id") is not None else 999999)
            warnings.append("Paste positions were missing or collapsed. Applied automatic layout.")

        local_id_to_node = {}
        created_count = 0
        x_spacing = 240.0
        y_spacing = 180.0
        columns = max(1, min(4, int(np.ceil(np.sqrt(max(1, len(sorted_specs)))))))

        for idx, spec in enumerate(sorted_specs):
            cls_name = spec["cls_name"]
            if cls_name == "OutputNode" and self.output_node is not None:
                warnings.append("OutputNode skipped (already exists).")
                continue
            node = NODE_TYPES[cls_name]()

            if use_auto_layout:
                col = idx % columns
                row = idx // columns
                block_w = (columns - 1) * x_spacing
                offset_x = (col * x_spacing) - (block_w / 2.0)
                offset_y = row * y_spacing
                node.pos = QPointF(scene_pos.x() + offset_x, scene_pos.y() + offset_y)
            else:
                offset = spec["pos"] - QPointF(cx, cy)
                node.pos = scene_pos + offset

            node_label = f"{cls_name}: "
            for prop_name, val in spec["props"].items():
                if isinstance(val, dict):
                    _ani_apply_sanitized_keyframes(node, prop_name, val, warnings, node_label=node_label)
                else:
                    _ani_apply_sanitized_property(node, prop_name, val, warnings, node_label=node_label)

            if spec["extra"]:
                try:
                    node._extra_from_dict(spec["extra"])
                except Exception as e:
                    warnings.append(f"{cls_name}: extra data skipped: {e}")

            self.add_node(node)
            if cls_name == "OutputNode":
                self.output_node = node
            if spec["local_id"] is not None:
                local_id_to_node[spec["local_id"]] = node
            created_count += 1

        for conn in connection_specs:
            from_node = local_id_to_node.get(conn["from_id"])
            to_node = local_id_to_node.get(conn["to_id"])
            slot = conn["input_slot"]
            if from_node and to_node and slot < len(to_node.inputs):
                to_node.inputs[slot] = from_node
            else:
                warnings.append(
                    f"Could not wire CONNECT from={conn['from_id']} to={conn['to_id']} input={slot}"
                )

        self.rebuild_connections()
        self.render_preview(self.timeline.current_frame)

        msg = f"📝 Pasted {created_count} node(s)"
        if warnings:
            msg += f" ({len(warnings)} warning(s))"
        self._show_toast(msg)

    def _copy_ani_legend(self):
        QApplication.clipboard().setText(build_ani_legend_text())
        self._show_toast("📋 Animation node legend copied to clipboard")

    def toggle_play(self):
        if self.timeline.playing:
            self.timeline.timer.stop()
        else:
            self.timeline.timer.start(int(1000 / PROJECT.fps))
        self.timeline.playing = not self.timeline.playing





    def open_add_node_menu(self):
        menu = QMenu(self)
        pos = self.view.mapToScene(self.view.rect().center())

        def spawn(cls):
            n = cls()
            n.pos = pos
            self.add_node(n)

        # copy-paste the same menu body from contextMenuEvent
        gen = menu.addMenu("Generators")
        gen.addAction("Color",         lambda: spawn(ColorNode))
        gen.addAction("Value",         lambda: spawn(ValueNode))
        gen.addAction("Oscillator",    lambda: spawn(OscillatorNode))
        gen.addAction("Noise",         lambda: spawn(NoiseNode))
        gen.addAction("Voronoi",       lambda: spawn(VoronoiNode))
        gen.addAction("Brick / Tile",  lambda: spawn(BrickPatternNode))
        gen.addAction("Image Texture", lambda: spawn(ImageTextureNode))
        gen.addAction("PNG Sequence",  lambda: spawn(PNGSequenceNode))
        gen.addAction("Wave Texture",   lambda: spawn(WaveNode))
        gen.addAction("Oscilloscope",   lambda: spawn(OscilloscopeNode))
        gen.addAction("Tileable Patterns", lambda: spawn(TileablePatternNode))
        tilesets = menu.addMenu("TileSets")
        tilesets.addAction("Tile Canvas", lambda: spawn(TileCanvasNode))
        mod = menu.addMenu("Modifiers")
        mod.addAction("Blur",                 lambda: spawn(BlurNode))
        mod.addAction("Edge Detect",          lambda: spawn(EdgeDetectNode))
        mod.addAction("Pixelate",             lambda: spawn(PixelateNode))
        mod.addAction("Chromatic Aberration", lambda: spawn(ChromaticAberrationNode))
        mod.addAction("Scanlines",            lambda: spawn(ScanlinesNode))
        mod.addAction("Displacement / Warp",  lambda: spawn(DisplacementNode))
        mod.addAction("Polar Coordinates",    lambda: spawn(PolarCoordsNode))
        mod.addAction("Color Adjust",         lambda: spawn(ColorAdjustNode))
        mod.addAction("Transform",            lambda: spawn(TransformNode))
        fx = menu.addMenu("Screen Effects")
        fx.addAction("CRT Effect",   lambda: spawn(CRTNode))
        fx.addAction("Dither",       lambda: spawn(DitherNode))
        fx.addAction("Posterize",    lambda: spawn(PosterizeNode))
        fx.addAction("Glow / Bloom", lambda: spawn(GlowNode))
        vec = menu.addMenu("Vector Shapes")
        vec.addAction("Rectangle", lambda: spawn(VectorRectNode))
        vec.addAction("Ellipse",   lambda: spawn(VectorEllipseNode))
        vec.addAction("Polygon",   lambda: spawn(VectorPolygonNode))
        vec.addAction("Line",      lambda: spawn(VectorLineNode))
        sdf = menu.addMenu("SDF Shapes")
        sdf.addAction("Circle",      lambda: spawn(CircleNode))
        sdf.addAction("Box",         lambda: spawn(BoxNode))
        sdf.addAction("Ring",        lambda: spawn(RingNode))
        sdf.addAction("Hexagon",     lambda: spawn(HexagonNode))
        sdf.addAction("Star",        lambda: spawn(StarNode))
        sdf.addAction("SDF Boolean", lambda: spawn(SDFBooleanNode))
        sdf.addAction("SDF Repeat",  lambda: spawn(SDFRepeatNode))
        txt = menu.addMenu("Text")
        txt.addAction("Text", lambda: spawn(TextNode))
        prt = menu.addMenu("Particles")
        prt.addAction("Particle Emitter", lambda: spawn(ParticleEmitterNode))
        prt.addAction("Random Select",    lambda: spawn(RandomSelectNode))
        col = menu.addMenu("Color")
        col.addAction("Color Ramp",    lambda: spawn(ColorRampNode))
        col.addAction("Gradient Map",  lambda: spawn(GradientNode))
        mth = menu.addMenu("Math / Blend")
        mth.addAction("Math",  lambda: spawn(MathNode))
        mth.addAction("Mix",   lambda: spawn(MixNode))
        mth.addAction("Merge", lambda: spawn(MergeNode))
        ui = menu.addMenu("UI")
        ui.addAction("UI Panel",    lambda: spawn(UIPanelNode))
        ui.addAction("UI Button",   lambda: spawn(UIButtonNode))
        ui.addAction("UI Checkbox", lambda: spawn(UICheckboxNode))

        menu.addSeparator()
        dbg = menu.addMenu("Debug")
        dbg.addAction("📋 Copy Nodes as Text",      lambda: self.copy_nodes_as_text())
        dbg.addAction("📝 Paste Nodes from Text",   lambda: self.paste_nodes_from_text())
        dbg.addSeparator()
        dbg.addAction("📖 Copy Node Legend as Text", lambda: self._copy_ani_legend())

        menu.exec(self.view.mapToGlobal(self.view.rect().topLeft()))





    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            dlg.apply_settings()
            self.timeline.timer.setInterval(int(1000 / PROJECT.fps))
            self.update_preview_bg()
            self.timeline.update()
            self.render_preview(self.timeline.current_frame)

    def update_preview_bg(self):
        border = self._theme_colors["BORDER"]
        if PROJECT.bg_style == "Black":
            bg = self._theme_colors["DARK"]
        elif PROJECT.bg_style == "Dark Gray":
            bg = self._theme_colors["SURFACE2"]
        else:
            bg = self._theme_colors["BORDER"]
        self.preview_lbl.setStyleSheet(f"background-color: {bg}; border: 2px solid {border};")

    def on_preview_mode_changed(self, mode):
        PROJECT.preview_mode = mode
        self.render_preview(self.timeline.current_frame)

    def render_preview(self, frame):
        if not self.output_node: return
        d = PROJECT.preview_divisor
        mode = PROJECT.preview_mode
        preview_w = self.preview_lbl.width()
        preview_h = self.preview_lbl.height()
        tile_node = self._get_connected_tile_canvas()

        if mode == "Actual Size":
            # Render at full project resolution — 1:1 pixel mapping
            w = PROJECT.width
            h = PROJECT.height
        else:
            # Fit and Full Screen Context render at reduced quality for speed
            w = max(PROJECT.width // d, 1)
            h = max(PROJECT.height // d, 1)

        arr = self.output_node.evaluate(frame, w, h)
        if tile_node and bool(tile_node.properties["Show Grid"].get_value(frame)):
            arr = self._draw_tile_grid_overlay(
                arr,
                tile_node.tile_size(frame),
                tile_node.columns(frame),
                tile_node.rows(frame),
            )
        arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
        if not arr.flags['C_CONTIGUOUS']: arr = np.ascontiguousarray(arr)
        ha, wa, _ = arr.shape

        if mode == "Fit":
            # Scale the rendered image to fill the preview label, keeping aspect ratio
            img = QImage(arr.data, wa, ha, wa * 4, QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(img)
            self.preview_lbl.setPixmap(
                pix.scaled(preview_w, preview_h,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            )

        elif mode == "Actual Size":
            # Draw the full-res image 1:1, centered; crop to preview label bounds
            img = QImage(arr.data, wa, ha, wa * 4, QImage.Format.Format_RGBA8888)
            result = QImage(preview_w, preview_h, QImage.Format.Format_RGBA8888)
            result.fill(Qt.GlobalColor.transparent)
            painter = QPainter(result)
            # Center the full-res canvas inside the (much smaller) preview label
            x = (preview_w - wa) // 2
            y = (preview_h - ha) // 2
            painter.drawImage(x, y, img)
            painter.end()
            self.preview_lbl.setPixmap(QPixmap.fromImage(result))

        elif mode == "Full Screen Context":
            # Show what the image looks like relative to the 960x544 Vita screen.
            # Scale the full 960x544 "screen" down to fit inside the preview label,
            # then draw the rendered image scaled to match that same reduction.
            VITA_W, VITA_H = 960, 544
            scale = min(preview_w / VITA_W, preview_h / VITA_H) * 0.9
            ref_w = int(VITA_W * scale)
            ref_h = int(VITA_H * scale)
            result = QImage(preview_w, preview_h, QImage.Format.Format_RGBA8888)
            result.fill(QColor(self._theme_colors["PANEL"]))
            painter = QPainter(result)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            ref_x = (preview_w - ref_w) // 2
            ref_y = (preview_h - ref_h) // 2
            # Draw background inside the screen rect
            if PROJECT.bg_style == "Black":
                painter.fillRect(ref_x, ref_y, ref_w, ref_h, QColor(self._theme_colors["DARK"]))
            elif PROJECT.bg_style == "Dark Gray":
                painter.fillRect(ref_x, ref_y, ref_w, ref_h, QColor(self._theme_colors["SURFACE2"]))
            else:
                checker_size = 8
                for cy in range(ref_h // checker_size + 1):
                    for cx in range(ref_w // checker_size + 1):
                        c = QColor(self._theme_colors["PANEL"]) if (cx + cy) % 2 == 0 else QColor(self._theme_colors["SURFACE2"])
                        painter.fillRect(ref_x + cx * checker_size, ref_y + cy * checker_size,
                                         checker_size, checker_size, c)
            painter.setClipRect(ref_x, ref_y, ref_w, ref_h)
            img = QImage(arr.data, wa, ha, wa * 4, QImage.Format.Format_RGBA8888)
            # Scale by project dimensions so a 64x64 canvas appears small inside a 960x544 screen rect
            img_scaled_w = int(PROJECT.width * scale)
            img_scaled_h = int(PROJECT.height * scale)
            scaled_img = img.scaled(img_scaled_w, img_scaled_h,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            content_x = ref_x + (ref_w - scaled_img.width()) // 2
            content_y = ref_y + (ref_h - scaled_img.height()) // 2
            painter.drawImage(content_x, content_y, scaled_img)
            painter.setClipping(False)
            painter.setPen(QPen(QColor(self._theme_colors["BORDER"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ref_x, ref_y, ref_w, ref_h)
            painter.setPen(QColor(self._theme_colors["TEXT_DIM"]))
            painter.drawText(ref_x, ref_y - 5, f"{PROJECT.width}x{PROJECT.height}")
            painter.end()
            self.preview_lbl.setPixmap(QPixmap.fromImage(result))

    def export_for_vita(self):
        """Export animation as .ani or .trans with spritesheet for Vita."""
        if not self.output_node:
            return
        
        dlg = ExportAnimationDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        
        settings = dlg.get_settings()

        main_win = QApplication.instance().activeWindow()
        if not hasattr(main_win, 'project') or not main_win.current_project_path:
            QMessageBox.warning(self, "No Project", "Please save your game project first before exporting animations.")
            return

        import shutil
        project_anim_dir = os.path.join(os.path.dirname(str(main_win.current_project_path)), "animations")
        os.makedirs(project_anim_dir, exist_ok=True)
        
        total = PROJECT.duration
        name = settings['name']
        is_trans = settings['type'] == 'trans'
        sheet_count_setting = settings['sheet_count']  # 0 = auto
        tile_node = self._get_connected_tile_canvas()
        if tile_node and not is_trans:
            w = tile_node.atlas_width(0)
            h = tile_node.atlas_height(0)
        else:
            w, h = PROJECT.width, PROJECT.height

        TRANS_W, TRANS_H = 240, 136
        MAX_SHEET = 2048

        render_w = 960 if is_trans else w
        render_h = 544 if is_trans else h
        store_w  = TRANS_W if is_trans else w
        store_h  = TRANS_H if is_trans else h

        # Determine sheet count
        if is_trans:
            num_sheets = 1
        elif sheet_count_setting == 0:
            # Auto: find minimum sheets for full resolution
            num_sheets = 1
            while True:
                fpg = int(np.ceil(total / num_sheets))
                cols = int(np.ceil(np.sqrt(fpg)))
                rows = int(np.ceil(fpg / cols))
                if cols * store_w <= MAX_SHEET and rows * store_h <= MAX_SHEET:
                    break
                num_sheets += 1
        else:
            num_sheets = sheet_count_setting

        frames_per_sheet = int(np.ceil(total / num_sheets))

        # For .ani, compute per-sheet layout and downscale if needed
        if not is_trans:
            cols = int(np.ceil(np.sqrt(frames_per_sheet)))
            rows = int(np.ceil(frames_per_sheet / cols))
            sheet_w = cols * store_w
            sheet_h = rows * store_h
            if sheet_w > MAX_SHEET or sheet_h > MAX_SHEET:
                scale_factor = min(MAX_SHEET / sheet_w, MAX_SHEET / sheet_h)
                store_w = max(1, int(store_w * scale_factor))
                store_h = max(1, int(store_h * scale_factor))

        progress = QProgressDialog("Rendering frames...", "Cancel", 0, total + num_sheets + 1, self)
        progress.setWindowTitle("Exporting")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        frames = []
        for frame in range(total):
            if progress.wasCanceled():
                return
            progress.setValue(frame)
            QApplication.processEvents()
            
            arr = self.output_node.evaluate(frame, render_w, render_h)
            arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
            if not arr.flags['C_CONTIGUOUS']:
                arr = np.ascontiguousarray(arr)

            src_h, src_w = arr.shape[:2]
            if is_trans or (store_w != src_w or store_h != src_h):
                pil_frame = PILImage.fromarray(arr, 'RGBA')
                pil_frame = pil_frame.resize((store_w, store_h), PILImage.Resampling.LANCZOS)
                arr = np.array(pil_frame)

            frames.append(arr)

        # Pack frames into sheets
        sheet_filenames = []
        cols = int(np.ceil(np.sqrt(frames_per_sheet)))
        rows = int(np.ceil(frames_per_sheet / cols))
        sheet_w = cols * store_w
        sheet_h = rows * store_h

        for si in range(num_sheets):
            if progress.wasCanceled():
                return
            progress.setLabelText(f"Packing spritesheet {si + 1}/{num_sheets}...")
            progress.setValue(total + si)
            QApplication.processEvents()

            start_idx = si * frames_per_sheet
            end_idx = min(start_idx + frames_per_sheet, total)
            chunk = frames[start_idx:end_idx]

            spritesheet = np.zeros((sheet_h, sheet_w, 4), dtype=np.uint8)
            for i, frame_arr in enumerate(chunk):
                r = i // cols
                c = i % cols
                y = r * store_h
                x = c * store_w
                spritesheet[y:y+store_h, x:x+store_w] = frame_arr

            img = PILImage.fromarray(spritesheet, 'RGBA')

            # Premultiply alpha for vita2d
            arr_final = np.array(img).astype(np.float32)
            alpha_channel = arr_final[:, :, 3:4] / 255.0
            arr_final[:, :, :3] *= alpha_channel
            img = PILImage.fromarray(arr_final.astype(np.uint8), 'RGBA')

            if num_sheets == 1:
                sheet_filename = f"{name}.png"
            else:
                sheet_filename = f"{name}_{si}.png"
            sheet_path = os.path.join(project_anim_dir, sheet_filename)
            img.save(sheet_path, "PNG")
            sheet_filenames.append(sheet_filename)

        progress.setLabelText("Saving metadata...")
        progress.setValue(total + num_sheets)
        QApplication.processEvents()

        ext = 'trans' if is_trans else 'ani'
        metadata = {
            'frame_count': total,
            'frame_width': store_w,
            'frame_height': store_h,
            'sheet_width': sheet_w,
            'sheet_height': sheet_h,
            'fps': PROJECT.fps,
            'spritesheet_path': sheet_filenames[0],
            'spritesheet_paths': sheet_filenames,
            'sheet_count': num_sheets,
            'frames_per_sheet': frames_per_sheet,
        }
        
        meta_path = os.path.join(project_anim_dir, f"{name}.{ext}")
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        progress.setValue(total + num_sheets + 1)
        progress.close()

        from models import AnimationExport, TransitionExport
        if is_trans:
            entry = TransitionExport(
                name=name,
                spritesheet_path=sheet_filenames[0],
                frame_count=total,
                sheet_width=sheet_w,
                sheet_height=sheet_h,
                fps=PROJECT.fps
            )
            main_win.project.transition_exports.append(entry)
        else:
            entry = AnimationExport(
                name=name,
                spritesheet_path=sheet_filenames[0],
                spritesheet_paths=sheet_filenames,
                frame_count=total,
                frame_width=store_w,
                frame_height=store_h,
                sheet_width=sheet_w,
                sheet_height=sheet_h,
                sheet_count=num_sheets,
                frames_per_sheet=frames_per_sheet,
                fps=PROJECT.fps
            )
            main_win.project.animation_exports.append(entry)
        if hasattr(main_win, 'obj_tab'):
            editor = main_win.obj_tab.def_editor
            if editor._obj is not None:
                editor.load_object(editor._obj, main_win.project)

    def export_png_sequence(self):
        if not self.output_node: return
        folder = QFileDialog.getExistingDirectory(self, "Choose Export Folder")
        if not folder: return
        tile_node = self._get_connected_tile_canvas()
        if tile_node:
            w = tile_node.atlas_width(0)
            h = tile_node.atlas_height(0)
        else:
            w, h = PROJECT.width, PROJECT.height
        total = PROJECT.duration
        progress = QProgressDialog("Exporting frames...", "Cancel", 0, total, self)
        progress.setWindowTitle("Exporting")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        for frame in range(total):
            if progress.wasCanceled(): break
            progress.setValue(frame); QApplication.processEvents()
            arr = self.output_node.evaluate(frame, w, h)
            arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
            if not arr.flags['C_CONTIGUOUS']: arr = np.ascontiguousarray(arr)
            frame_h, frame_w = arr.shape[:2]
            img = QImage(arr.data, frame_w, frame_h, frame_w * 4, QImage.Format.Format_RGBA8888)
            img.save(os.path.join(folder, f"frame_{frame:04d}.png"), "PNG")
        progress.setValue(total); progress.close()
    def export_single_frame(self):
        """Export the current frame as a quantized 8-bit indexed PNG."""
        if not self.output_node:
            return

        frame = self.timeline.current_frame
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Single Frame", f"frame_{frame:04d}.png",
            "PNG Image (*.png)"
        )
        if not path:
            return

        w, h = PROJECT.width, PROJECT.height
        arr = self.output_node.evaluate(frame, w, h)
        arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
        if not arr.flags['C_CONTIGUOUS']:
            arr = np.ascontiguousarray(arr)

        img_rgba = PILImage.fromarray(arr, 'RGBA')

        # Split alpha so quantization only touches RGB
        r, g, b, alpha = img_rgba.split()
        img_rgb = PILImage.merge('RGB', (r, g, b))

        # Quantize RGB to 255 colors (reserve index 0 for transparent)
        img_p = img_rgb.quantize(colors=255, method=PILImage.Quantize.MEDIANCUT)

        # Shift all palette indices up by 1 to free index 0 for transparency
        data = np.array(img_p, dtype=np.uint8)
        data = data + 1  # 0-254 -> 1-255

        # Build new palette: slot 0 = black placeholder (marked transparent), slots 1-255 = original colors
        palette_bytes = img_p.getpalette()  # R,G,B x 256
        new_palette = [0, 0, 0] + palette_bytes[:255 * 3]

        # Any pixel where alpha < 128 gets index 0 (transparent)
        alpha_arr = np.array(alpha, dtype=np.uint8)
        data[alpha_arr < 128] = 0

        img_out = PILImage.fromarray(data, mode='P')
        img_out.putpalette(new_palette)
        img_out.save(path, "PNG", transparency=0)

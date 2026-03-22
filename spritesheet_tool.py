"""
Spritesheet Tool
Standalone PySide6 spritesheet viewer with live preview and animation playback.

How it works:
  1. Open an image
  2. Set Columns and Rows (or click Detect Frames)
  3. The tool divides the image evenly into that many cells
  4. Adjust Offset and Gap only if needed

Frame size is calculated automatically: (image_size - offset - gaps) / count
"""

import sys
import os
import json
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QSplitter, QSizePolicy, QSpinBox,
    QScrollArea, QCheckBox, QPushButton, QGroupBox, QGridLayout,
    QSlider, QFrame, QLineEdit, QMessageBox,
)
from PySide6.QtGui import (
    QPainter, QPen, QColor, QFont, QPalette, QPixmap, QImage,
)
from PySide6.QtCore import Qt, QPoint, QRectF, Signal, QSize, QTimer


# ── Palette ──────────────────────────────────────────────
DARK   = "#0e0e12"
PANEL  = "#16161c"
CARD   = "#1e1e28"
BORDER = "#2a2a38"
ACCENT = "#5b8dde"
ADIM   = "#2d3f66"
AHOV   = "#7aa8f0"
FG     = "#e2e2ee"
FG2    = "#7878a0"
DIM    = "#454560"
GRID_C = "#4488ff"

SS = f"""
* {{ font-family: "Segoe UI", "Helvetica Neue", sans-serif; font-size: 12px; color: {FG}; }}
QMainWindow, QWidget {{ background: {DARK}; }}
QGroupBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
    margin-top: 10px; padding: 14px 10px 10px 10px;
    font-size: 11px; color: {FG2}; font-weight: bold;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}
QSpinBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 3px;
    color: {FG}; padding: 4px 6px; min-width: 60px;
}}
QSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ background: {BORDER}; border: none; width: 16px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {ADIM}; }}
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 4px;
    color: {FG}; padding: 6px 14px;
}}
QPushButton:hover {{ background: {ADIM}; border-color: {ACCENT}; color: {AHOV}; }}
QPushButton:pressed {{ background: {ACCENT}; color: #fff; }}
QPushButton#open {{
    background: {ADIM}; border-color: {ACCENT}; color: {AHOV}; font-weight: bold;
}}
QPushButton#open:hover {{ background: {ACCENT}; color: #fff; }}
QPushButton#detect {{
    background: {ADIM}; border-color: {ACCENT}; color: {AHOV};
}}
QPushButton#detect:hover {{ background: {ACCENT}; color: #fff; }}
QLabel#heading {{ color: {FG2}; font-size: 10px; font-weight: bold; letter-spacing: 1px; }}
QLabel#value {{ color: {FG}; }}
QLabel#accent {{ color: {ACCENT}; font-weight: bold; }}
QLabel#hint {{ color: {DIM}; font-size: 10px; }}
QLabel#dim {{ color: {DIM}; font-size: 11px; }}
QLabel#info {{ color: {FG2}; font-size: 11px; }}
QLineEdit {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 3px;
    color: {FG}; padding: 3px 6px; font-size: 11px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QCheckBox {{ color: {FG2}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {BORDER};
    border-radius: 2px; background: {CARD};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollArea {{ border: 1px solid {BORDER}; background: {DARK}; }}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {PANEL}; width: 10px; height: 10px; border: none;
}}
QScrollBar::handle {{ background: {BORDER}; border-radius: 5px; min-height: 20px; min-width: 20px; }}
QScrollBar::handle:hover {{ background: {ADIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; }}
QSplitter::handle {{ background: {BORDER}; width: 2px; }}
QSlider::groove:horizontal {{
    height: 4px; background: {BORDER}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -5px 0;
    background: {ACCENT}; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {AHOV}; }}
"""


# ═══════════════════════════════════════════════════════════
#  Auto-detect: scan transparency to find columns and rows
# ═══════════════════════════════════════════════════════════
def detect_grid(qimage: QImage):
    """Analyze a spritesheet image and return (cols, rows) guess.
    
    Strategy: find evenly-spaced content regions by scanning
    columns and rows for transparency gaps.
    """
    # Convert QImage to numpy array
    qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
    w, h = qimage.width(), qimage.height()
    bpl = qimage.bytesPerLine()          # may be > w*4 due to scanline padding
    ptr = qimage.bits()
    raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl))
    arr = raw[:, :w * 4].reshape((h, w, 4))
    alpha = arr[:, :, 3]

    def find_count(has_content):
        """Given a 1D bool array (column or row has content),
        find how many evenly-spaced groups there are."""
        n = len(has_content)
        # Find contiguous groups of True
        groups = []
        in_group = False
        for i in range(n):
            if has_content[i] and not in_group:
                start = i
                in_group = True
            elif not has_content[i] and in_group:
                groups.append((start, i - 1))
                in_group = False
        if in_group:
            groups.append((start, n - 1))

        if len(groups) <= 1:
            return len(groups), groups

        # Check if groups are evenly spaced (by center or by start)
        # Return group count
        return len(groups), groups

    # Scan columns
    col_has_content = np.any(alpha > 0, axis=0)
    n_cols, col_groups = find_count(col_has_content)

    # Scan rows
    row_has_content = np.any(alpha > 0, axis=1)
    n_rows, row_groups = find_count(row_has_content)

    # For columns: if groups are evenly spaced, the count is the number of frames
    # But we also need to handle sheets where content fills the whole cell
    # (no transparent gaps between columns). In that case col_groups will be 1.
    # Fall back to checking if the image width divides evenly by common sizes.

    if n_cols == 0:
        n_cols = 1
    if n_rows == 0:
        n_rows = 1

    # If we only found 1 column group but multiple row groups,
    # the sheet might be tightly packed horizontally.
    # Try to detect columns by looking at whether the image width
    # divides evenly by the height of each row-group (assuming square-ish frames).
    if n_cols == 1 and n_rows >= 1 and row_groups:
        # Estimate frame height from row groups
        avg_row_h = sum(e - s + 1 for s, e in row_groups) / len(row_groups)
        # Try frame width = image_width / N for various N
        # Pick N where frame_width is closest to avg_row_h
        best_n = 1
        best_diff = abs(w - avg_row_h)
        for n in range(2, min(65, w + 1)):
            fw = w / n
            diff = abs(fw - avg_row_h)
            if diff < best_diff:
                best_diff = diff
                best_n = n
        n_cols = best_n

    # Same for rows if only 1 row group found
    if n_rows == 1 and n_cols >= 1 and col_groups:
        avg_col_w = sum(e - s + 1 for s, e in col_groups) / len(col_groups)
        best_n = 1
        best_diff = abs(h - avg_col_w)
        for n in range(2, min(65, h + 1)):
            fh = h / n
            diff = abs(fh - avg_col_w)
            if diff < best_diff:
                best_diff = diff
                best_n = n
        n_rows = best_n

    return max(1, n_cols), max(1, n_rows)


# ═══════════════════════════════════════════════════════════
#  SheetCanvas — shows the spritesheet with grid overlay
# ═══════════════════════════════════════════════════════════
class SheetCanvas(QWidget):
    cellClicked = Signal(int, int)
    cellHovered = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 200)

        self._pm = None
        self._zoom = 1.0
        self._pan_offset = QPoint(0, 0)
        self._pan_start = None

        # Grid params
        self._cols = 1
        self._rows = 1
        self._ox = 0        # offset x
        self._oy = 0        # offset y
        self._gx = 0        # gap x (between frames)
        self._gy = 0        # gap y
        self._fw = 32       # computed frame width
        self._fh = 32       # computed frame height

        self._show_grid = True
        self._hover = (-1, -1)
        self._selected = (-1, -1)

    def load(self, pm: QPixmap):
        self._pm = pm
        self._selected = (-1, -1)
        self._hover = (-1, -1)
        self._fit()
        self.update()

    def setGrid(self, cols, rows, ox, oy, gx, gy):
        self._cols = max(1, cols)
        self._rows = max(1, rows)
        self._ox = ox
        self._oy = oy
        self._gx = max(0, gx)
        self._gy = max(0, gy)
        self._recompute_frame_size()
        self.update()

    def _recompute_frame_size(self):
        """Frame size = (image_dimension - offset - total_gaps) / count"""
        if self._pm is None:
            self._fw = self._fh = 1
            return
        usable_w = self._pm.width() - self._ox - self._gx * (self._cols - 1)
        usable_h = self._pm.height() - self._oy - self._gy * (self._rows - 1)
        self._fw = max(1, usable_w // self._cols)
        self._fh = max(1, usable_h // self._rows)

    def setShowGrid(self, v):
        self._show_grid = v
        self.update()

    def cols(self): return self._cols
    def rows(self): return self._rows
    def frameWidth(self): return self._fw
    def frameHeight(self): return self._fh

    def framePm(self, col, row):
        if self._pm is None:
            return None
        step_x = self._fw + self._gx
        step_y = self._fh + self._gy
        x = self._ox + col * step_x
        y = self._oy + row * step_y
        return self._pm.copy(x, y, self._fw, self._fh)

    def framesByRow(self):
        rows = []
        for r in range(self._rows):
            row_frames = []
            for c in range(self._cols):
                row_frames.append(self.framePm(c, r))
            rows.append(row_frames)
        return rows

    def _fit(self):
        if self._pm is None:
            return
        vw, vh = self.width(), self.height()
        iw, ih = self._pm.width(), self._pm.height()
        if iw and ih:
            self._zoom = min(vw / iw, vh / ih) * 0.92
            self._pan_offset = QPoint(
                int((vw - iw * self._zoom) / 2),
                int((vh - ih * self._zoom) / 2),
            )

    def _toImage(self, pos):
        return (
            (pos.x() - self._pan_offset.x()) / self._zoom,
            (pos.y() - self._pan_offset.y()) / self._zoom,
        )

    def _cellAt(self, pos):
        if self._pm is None or not self._cols or not self._rows:
            return (-1, -1)
        ix, iy = self._toImage(pos)
        ix -= self._ox
        iy -= self._oy
        if ix < 0 or iy < 0:
            return (-1, -1)
        step_x = self._fw + self._gx
        step_y = self._fh + self._gy
        col = int(ix / step_x) if step_x else 0
        row = int(iy / step_y) if step_y else 0
        # Reject clicks in the gap
        if self._gx and (ix % step_x) >= self._fw:
            return (-1, -1)
        if self._gy and (iy % step_y) >= self._fh:
            return (-1, -1)
        if col >= self._cols or row >= self._rows:
            return (-1, -1)
        return col, row

    # ── Events ─────────────────────────────────
    def wheelEvent(self, e):
        f = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        oz = self._zoom
        self._zoom = max(0.1, min(16.0, self._zoom * f))
        cx, cy = e.position().x(), e.position().y()
        self._pan_offset = QPoint(
            int(cx - (cx - self._pan_offset.x()) * self._zoom / oz),
            int(cy - (cy - self._pan_offset.y()) * self._zoom / oz),
        )
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (
            e.button() == Qt.LeftButton and e.modifiers() & Qt.AltModifier
        ):
            self._pan_start = e.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        elif e.button() == Qt.LeftButton:
            c = self._cellAt(e.position().toPoint())
            if c != (-1, -1):
                self._selected = c
                self.cellClicked.emit(*c)
                self.update()

    def mouseReleaseEvent(self, e):
        self._pan_start = None
        self.setCursor(Qt.CrossCursor)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._pan_start:
            self._pan_offset += pos - self._pan_start
            self._pan_start = pos
            self.update()
            return
        c = self._cellAt(pos)
        if c != self._hover:
            self._hover = c
            if c != (-1, -1):
                self.cellHovered.emit(*c)
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pm:
            self._fit()

    # ── Paint ──────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        s = 12
        c1, c2 = QColor("#0e0e12"), QColor("#141418")
        for r in range(self.height() // s + 1):
            for c in range(self.width() // s + 1):
                p.fillRect(c * s, r * s, s, s, c1 if (r + c) % 2 == 0 else c2)

        if self._pm is None:
            p.setPen(QColor(DIM))
            p.setFont(QFont("Segoe UI", 13))
            p.drawText(
                self.rect(), Qt.AlignCenter,
                "Open or drag & drop a spritesheet image",
            )
            p.end()
            return

        p.save()
        p.translate(self._pan_offset.x(), self._pan_offset.y())
        p.scale(self._zoom, self._zoom)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self._zoom < 2.0)

        p.drawPixmap(0, 0, self._pm)

        if self._show_grid and self._cols and self._rows:
            pen = QPen(QColor(GRID_C))
            pen.setCosmetic(True)
            pen.setWidthF(1.0)
            p.setPen(pen)
            step_x = self._fw + self._gx
            step_y = self._fh + self._gy
            for row in range(self._rows):
                for col in range(self._cols):
                    x = self._ox + col * step_x
                    y = self._oy + row * step_y
                    p.drawRect(QRectF(x, y, self._fw, self._fh))

        if self._hover != (-1, -1):
            col, row = self._hover
            step_x = self._fw + self._gx
            step_y = self._fh + self._gy
            r = QRectF(self._ox + col * step_x, self._oy + row * step_y, self._fw, self._fh)
            p.fillRect(r, QColor(91, 141, 222, 50))
            pen = QPen(QColor(91, 141, 222, 200))
            pen.setCosmetic(True)
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.drawRect(r)

        if self._selected != (-1, -1):
            col, row = self._selected
            step_x = self._fw + self._gx
            step_y = self._fh + self._gy
            r = QRectF(self._ox + col * step_x, self._oy + row * step_y, self._fw, self._fh)
            p.fillRect(r, QColor(78, 200, 122, 60))
            pen = QPen(QColor(78, 200, 122, 220))
            pen.setCosmetic(True)
            pen.setWidthF(2)
            p.setPen(pen)
            p.drawRect(r)

        p.restore()
        p.end()


# ═══════════════════════════════════════════════════════════
#  FrameStrip — rows with name, frame count, export
# ═══════════════════════════════════════════════════════════
class FrameStrip(QScrollArea):
    rowClicked = Signal(int)
    # row_idx, name, frame_count — emitted when export is clicked
    exportRow = Signal(int, str, int)
    # row_idx, name, frame_count — emitted when .ani export is clicked
    exportRowAni = Signal(int, str, int)

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 4, 6, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self.setWidget(self._container)
        self._row_widgets = []
        self._row_data = []  # list of dicts: {name_edit, count_spin, total_frames}
        self._selected_row = -1

    def setRows(self, rows_of_pixmaps):
        for w in self._row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._row_widgets.clear()
        self._row_data.clear()
        self._selected_row = -1

        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()

        thumb_size = 36
        default_names = [
            "idle", "run", "jump", "fall", "attack", "hurt", "die",
            "climb", "crouch", "dash", "swim", "cast",
        ]

        for row_idx, row_frames in enumerate(rows_of_pixmaps):
            row_widget = QWidget()
            row_widget.setStyleSheet(
                f"background: {CARD}; border: 2px solid transparent; border-radius: 5px;"
            )
            row_widget.setCursor(Qt.PointingHandCursor)
            row_lo = QVBoxLayout(row_widget)
            row_lo.setContentsMargins(6, 4, 6, 4)
            row_lo.setSpacing(4)

            # Top controls: name, frame count, export
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(4)

            name_edit = QLineEdit()
            default_name = default_names[row_idx] if row_idx < len(default_names) else f"anim_{row_idx + 1}"
            name_edit.setText(default_name)
            name_edit.setPlaceholderText("animation name")
            name_edit.setFixedWidth(90)
            name_edit.setStyleSheet(
                f"background: {DARK}; border: 1px solid {BORDER}; border-radius: 3px;"
                f" color: {FG}; padding: 2px 4px; font-size: 11px;"
            )
            ctrl_row.addWidget(name_edit)

            frames_label = QLabel("Frames:")
            frames_label.setObjectName("hint")
            ctrl_row.addWidget(frames_label)

            count_spin = QSpinBox()
            count_spin.setRange(1, len(row_frames))
            count_spin.setValue(len(row_frames))
            count_spin.setFixedWidth(50)
            count_spin.valueChanged.connect(
                lambda val, idx=row_idx: self._onCountChanged(idx, val)
            )
            ctrl_row.addWidget(count_spin)

            ctrl_row.addStretch()

            export_btn = QPushButton("Export .png")
            export_btn.setFixedWidth(90)
            export_btn.clicked.connect(
                lambda checked, idx=row_idx: self._onExport(idx)
            )
            ctrl_row.addWidget(export_btn)

            ani_btn = QPushButton("Export .ani")
            ani_btn.setFixedWidth(90)
            ani_btn.setToolTip("Export as .ani for Vita (requires saved project)")
            ani_btn.clicked.connect(
                lambda checked, idx=row_idx: self._onExportAni(idx)
            )
            ctrl_row.addWidget(ani_btn)

            row_lo.addLayout(ctrl_row)

            # Thumbnail strip
            thumb_row = QHBoxLayout()
            thumb_row.setSpacing(2)
            for pm in row_frames:
                lbl = QLabel()
                scaled = pm.scaled(thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.FastTransformation)
                lbl.setPixmap(scaled)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setFixedSize(thumb_size + 4, thumb_size + 4)
                lbl.setStyleSheet("background: transparent; border: none;")
                thumb_row.addWidget(lbl)
            thumb_row.addStretch()
            row_lo.addLayout(thumb_row)

            # Click on the widget background selects the row
            row_widget.mousePressEvent = lambda e, idx=row_idx: self._onRowClick(idx)
            self._layout.addWidget(row_widget)
            self._row_widgets.append(row_widget)
            self._row_data.append({
                "name_edit": name_edit,
                "count_spin": count_spin,
                "total_frames": len(row_frames),
            })

        self._layout.addStretch()
        if rows_of_pixmaps:
            self._onRowClick(0)

    def _onCountChanged(self, row_idx, val):
        """When frame count changes, re-select the row to update the animation preview."""
        if row_idx == self._selected_row:
            self.rowClicked.emit(row_idx)

    def _onExport(self, row_idx):
        if 0 <= row_idx < len(self._row_data):
            data = self._row_data[row_idx]
            name = data["name_edit"].text().strip()
            if not name:
                name = f"anim_{row_idx + 1}"
            count = data["count_spin"].value()
            self.exportRow.emit(row_idx, name, count)

    def _onExportAni(self, row_idx):
        if 0 <= row_idx < len(self._row_data):
            data = self._row_data[row_idx]
            name = data["name_edit"].text().strip()
            if not name:
                name = f"anim_{row_idx + 1}"
            count = data["count_spin"].value()
            self.exportRowAni.emit(row_idx, name, count)

    def getRowFrameCount(self, row_idx):
        if 0 <= row_idx < len(self._row_data):
            return self._row_data[row_idx]["count_spin"].value()
        return 0

    def _onRowClick(self, idx):
        self.selectRow(idx)
        self.rowClicked.emit(idx)

    def selectRow(self, idx):
        if 0 <= self._selected_row < len(self._row_widgets):
            self._row_widgets[self._selected_row].setStyleSheet(
                f"background: {CARD}; border: 2px solid transparent; border-radius: 5px;"
            )
        self._selected_row = idx
        if 0 <= idx < len(self._row_widgets):
            self._row_widgets[idx].setStyleSheet(
                f"background: {CARD}; border: 2px solid {ACCENT}; border-radius: 5px;"
            )


# ═══════════════════════════════════════════════════════════
#  AnimPreview — starts paused
# ═══════════════════════════════════════════════════════════
class AnimPreview(QWidget):
    def __init__(self):
        super().__init__()
        self._frames = []
        self._index = 0
        self._playing = False
        self.setFixedSize(140, 140)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(125)

    def setFrames(self, pixmaps):
        self._frames = pixmaps
        self._index = 0
        self.update()

    def setFps(self, fps):
        fps = max(1, min(30, fps))
        self._timer.setInterval(int(1000 / fps))

    def playing(self):
        return self._playing

    def setPlaying(self, v):
        self._playing = v
        if v and self._frames:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        if self._frames:
            self._index = (self._index + 1) % len(self._frames)
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        s = 8
        c1, c2 = QColor("#1a1a24"), QColor("#222232")
        for r in range(self.height() // s + 1):
            for c in range(self.width() // s + 1):
                p.fillRect(c * s, r * s, s, s, c1 if (r + c) % 2 == 0 else c2)
        if self._frames:
            pm = self._frames[self._index]
            scale = min(
                (self.width() - 8) / max(1, pm.width()),
                (self.height() - 8) / max(1, pm.height()),
            )
            dw = int(pm.width() * scale)
            dh = int(pm.height() * scale)
            dx = (self.width() - dw) // 2
            dy = (self.height() - dh) // 2
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawPixmap(dx, dy, dw, dh, pm)
        pen = QPen(QColor(BORDER))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.end()


# ═══════════════════════════════════════════════════════════
#  ControlPanel
# ═══════════════════════════════════════════════════════════
class ControlPanel(QWidget):
    # cols, rows, ox, oy, gx, gy
    gridChanged = Signal(int, int, int, int, int, int)
    gridToggled = Signal(bool)
    fitClicked = Signal()
    detectClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(240)
        
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        # ── Layout (PRIMARY) ───────────────────
        lg = QGroupBox("Layout")
        lgl = QGridLayout(lg)
        lgl.setSpacing(6)

        self.ncols = self._spin(1, 256, 1)
        self.nrows = self._spin(1, 256, 1)
        lgl.addWidget(QLabel("Columns"), 0, 0)
        lgl.addWidget(self.ncols, 0, 1)
        lgl.addWidget(QLabel("Rows"), 1, 0)
        lgl.addWidget(self.nrows, 1, 1)

        hint = QLabel(
            "How many frames across and down. "
            "The image is divided evenly."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lgl.addWidget(hint, 2, 0, 1, 2)

        self.i_frames = QLabel("1")
        self.i_frames.setObjectName("value")
        lgl.addWidget(QLabel("Total frames"), 3, 0)
        lgl.addWidget(self.i_frames, 3, 1)

        self.i_fsize = QLabel("—")
        self.i_fsize.setObjectName("info")
        lgl.addWidget(QLabel("Frame size"), 4, 0)
        lgl.addWidget(self.i_fsize, 4, 1)

        lo.addWidget(lg)

        # ── Detect button ──────────────────────
        detect_btn = QPushButton("Detect Frames")
        detect_btn.setObjectName("detect")
        detect_btn.setToolTip("Scan the image for frames and fill in columns/rows automatically")
        detect_btn.clicked.connect(self.detectClicked)
        lo.addWidget(detect_btn)

        # ── Gap ────────────────────────────────
        gg = QGroupBox("Gap")
        ggl = QGridLayout(gg)
        ggl.setSpacing(6)

        self.gx = self._spin(0, 512, 0)
        self.gy = self._spin(0, 512, 0)
        ggl.addWidget(QLabel("Horizontal"), 0, 0)
        ggl.addWidget(self.gx, 0, 1)
        ggl.addWidget(QLabel("Vertical"), 1, 0)
        ggl.addWidget(self.gy, 1, 1)

        hint_gap = QLabel(
            "Empty pixels between frames. Usually 0. "
            "Increase if you see slivers of neighboring frames."
        )
        hint_gap.setObjectName("hint")
        hint_gap.setWordWrap(True)
        ggl.addWidget(hint_gap, 2, 0, 1, 2)
        lo.addWidget(gg)

        # ── Offset ─────────────────────────────
        og = QGroupBox("Offset")
        ogl = QGridLayout(og)
        ogl.setSpacing(6)

        self.ox = self._spin(-512, 512, 0)
        self.oy = self._spin(-512, 512, 0)
        ogl.addWidget(QLabel("X"), 0, 0)
        ogl.addWidget(self.ox, 0, 1)
        ogl.addWidget(QLabel("Y"), 1, 0)
        ogl.addWidget(self.oy, 1, 1)

        hint_off = QLabel(
            "Where the first frame starts. Usually 0, 0."
        )
        hint_off.setObjectName("hint")
        hint_off.setWordWrap(True)
        ogl.addWidget(hint_off, 2, 0, 1, 2)
        lo.addWidget(og)

        # ── View ───────────────────────────────
        self.grid_chk = QCheckBox("Show grid overlay")
        self.grid_chk.setChecked(True)
        self.grid_chk.toggled.connect(self.gridToggled)
        lo.addWidget(self.grid_chk)

        fit_btn = QPushButton("Fit Image to View")
        fit_btn.clicked.connect(self.fitClicked)
        lo.addWidget(fit_btn)

        # ── Image Info ─────────────────────────
        self.i_size = QLabel("—")
        self.i_size.setObjectName("hint")
        lo.addWidget(self.i_size)

        lo.addStretch()

        for sp in (self.ncols, self.nrows, self.gx, self.gy, self.ox, self.oy):
            sp.valueChanged.connect(self._emit)

    def _spin(self, lo, hi, val):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _emit(self):
        cols = self.ncols.value()
        rows = self.nrows.value()
        self.i_frames.setText(str(cols * rows))
        self.gridChanged.emit(
            cols, rows,
            self.ox.value(), self.oy.value(),
            self.gx.value(), self.gy.value(),
        )

    def updateInfo(self, w, h):
        self.i_size.setText(f"Image: {w} x {h} px")

    def updateFrameSize(self, fw, fh):
        self.i_fsize.setText(f"{fw} x {fh} px")


# ═══════════════════════════════════════════════════════════
#  BottomBar — anim preview + row filmstrip
# ═══════════════════════════════════════════════════════════
class BottomBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(200)
        self._rows_data = []
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 6, 8, 6)
        lo.setSpacing(10)

        anim_box = QVBoxLayout()
        anim_box.setSpacing(6)
        anim_label = QLabel("Animation Preview")
        anim_label.setObjectName("heading")
        anim_box.addWidget(anim_label)

        self.anim = AnimPreview()
        anim_box.addWidget(self.anim, alignment=Qt.AlignCenter)

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setFixedWidth(100)
        self.play_btn.clicked.connect(self._togglePlay)
        anim_box.addWidget(self.play_btn, alignment=Qt.AlignCenter)

        fps_row = QHBoxLayout()
        fps_row.setSpacing(6)
        speed_label = QLabel("Speed")
        speed_label.setObjectName("hint")
        fps_row.addWidget(speed_label)
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(1, 30)
        self.fps_slider.setValue(8)
        self.fps_slider.setFixedWidth(100)
        self.fps_slider.valueChanged.connect(self._onFps)
        fps_row.addWidget(self.fps_slider)
        self.fps_label = QLabel("8 fps")
        self.fps_label.setObjectName("accent")
        self.fps_label.setFixedWidth(42)
        fps_row.addWidget(self.fps_label)
        anim_box.addLayout(fps_row)
        lo.addLayout(anim_box)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {BORDER};")
        lo.addWidget(sep)

        strip_box = QVBoxLayout()
        strip_box.setSpacing(4)
        strip_label = QLabel("Rows — click a row to preview its animation")
        strip_label.setObjectName("heading")
        strip_box.addWidget(strip_label)
        self.strip = FrameStrip()
        self.strip.rowClicked.connect(self._onRowClicked)
        strip_box.addWidget(self.strip)
        lo.addLayout(strip_box, 1)

    def _onFps(self, val):
        self.fps_label.setText(f"{val} fps")
        self.anim.setFps(val)

    def _togglePlay(self):
        playing = not self.anim.playing()
        self.anim.setPlaying(playing)
        self.play_btn.setText("⏸  Pause" if playing else "▶  Play")

    def _onRowClicked(self, row_idx):
        if 0 <= row_idx < len(self._rows_data):
            # Only show the number of frames the user set for this row
            count = self.strip.getRowFrameCount(row_idx)
            frames = self._rows_data[row_idx][:count]
            self.anim.setFrames(frames)
            if self.anim.playing():
                self.anim.setPlaying(True)

    def setFrameRows(self, rows_of_pixmaps):
        self._rows_data = rows_of_pixmaps
        self.strip.setRows(rows_of_pixmaps)
        if rows_of_pixmaps:
            count = self.strip.getRowFrameCount(0)
            self.anim.setFrames(rows_of_pixmaps[0][:count])
        else:
            self.anim.setFrames([])
        self.anim.setPlaying(False)
        self.play_btn.setText("▶  Play")


# ═══════════════════════════════════════════════════════════
#  Main Window
# ═══════════════════════════════════════════════════════════
class SpritesheetTool(QMainWindow):
    def __init__(self, main_window=None):
        super().__init__()
        self._main_window = main_window
        self.setWindowTitle("Spritesheet Tool")
        self.resize(1200, 780)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(SS)
        self.setAcceptDrops(True)
        self._pm = None
        self._build()

    def _build(self):
        tb = self.addToolBar("main")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setStyleSheet(
            f"QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER};"
            f" padding: 4px; spacing: 6px; }}"
        )
        open_btn = QPushButton("Open Spritesheet")
        open_btn.setObjectName("open")
        open_btn.clicked.connect(self._openFile)
        tb.addWidget(open_btn)
        tb.addSeparator()
        self._file_label = QLabel("  No file loaded")
        self._file_label.setObjectName("dim")
        tb.addWidget(self._file_label)

        central = QWidget()
        main_lo = QVBoxLayout(central)
        main_lo.setContentsMargins(0, 0, 0, 0)
        main_lo.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        self.canvas = SheetCanvas()
        self.canvas.cellClicked.connect(self._onCellClick)
        self.canvas.cellHovered.connect(self._onCellHover)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        self.panel = ControlPanel()
        self.panel.gridChanged.connect(self._onGridChanged)
        self.panel.gridToggled.connect(self.canvas.setShowGrid)
        self.panel.fitClicked.connect(self._fit)
        self.panel.detectClicked.connect(self._detect)

        # Wrap the panel in a scroll area to stop the spin boxes from squishing
        panel_scroll = QScrollArea()
        panel_scroll.setWidget(self.panel)
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setMinimumWidth(255) # 240px for panel + 15px for scrollbar
        
        splitter.addWidget(panel_scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([920, 240])
        main_lo.addWidget(splitter, 1)

        self.bottom = BottomBar()
        self.bottom.strip.exportRow.connect(self._exportRow)
        self.bottom.strip.exportRowAni.connect(self._exportRowAni)
        main_lo.addWidget(self.bottom)
        self.setCentralWidget(central)

        sb = self.statusBar()
        sb.setStyleSheet(
            f"QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER};"
            f" color: {FG2}; font-size: 11px; }}"
        )
        self._sb_hover = QLabel("—")
        sb.addPermanentWidget(self._sb_hover)
        sb.showMessage("Open a spritesheet to get started.")

        # Debounce timer for frame extraction
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._refreshFrames)

    # ── File handling ──────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
                self._load(p)
                break

    def _openFile(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Open Spritesheet", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)",
        )
        if p:
            self._load(p)

    def _load(self, path):
        pm = QPixmap(path)
        if pm.isNull():
            self.statusBar().showMessage(f"Could not load: {path}", 4000)
            return
        self._pm = pm
        fname = path.replace("\\", "/").split("/")[-1]

        self.canvas.load(pm)
        self.panel.updateInfo(pm.width(), pm.height())
        self._file_label.setText(f"  {fname}  —  {pm.width()} x {pm.height()} px")
        self._file_label.setStyleSheet(f"color: {FG2};")
        self.statusBar().showMessage(f"Loaded {fname}", 3000)

        # Auto-detect on load
        self._detect()
        self._fit()

    def _detect(self):
        if self._pm is None:
            return
        qimg = self._pm.toImage()
        cols, rows = detect_grid(qimg)
        # Block signals while setting both to avoid double refresh
        self.panel.ncols.blockSignals(True)
        self.panel.nrows.blockSignals(True)
        self.panel.ncols.setValue(cols)
        self.panel.nrows.setValue(rows)
        self.panel.ncols.blockSignals(False)
        self.panel.nrows.blockSignals(False)
        # Now push to canvas and refresh
        self._pushGrid()
        self._updateFrameSizeLabel()
        self._refreshFrames()
        self.statusBar().showMessage(f"Detected {cols} columns, {rows} rows", 3000)

    def _pushGrid(self):
        self.canvas.setGrid(
            self.panel.ncols.value(), self.panel.nrows.value(),
            self.panel.ox.value(), self.panel.oy.value(),
            self.panel.gx.value(), self.panel.gy.value(),
        )

    def _updateFrameSizeLabel(self):
        self.panel.updateFrameSize(self.canvas.frameWidth(), self.canvas.frameHeight())
        self.panel.i_frames.setText(str(self.canvas.cols() * self.canvas.rows()))

    # ── Grid updates ──────────────────────────
    def _onGridChanged(self, cols, rows, ox, oy, gx, gy):
        self.canvas.setGrid(cols, rows, ox, oy, gx, gy)
        self._updateFrameSizeLabel()
        if self._pm:
            self._debounce.start(150)

    def _refreshFrames(self):
        rows = self.canvas.framesByRow()
        self.bottom.setFrameRows(rows)

    def _onCellClick(self, col, row):
        self._sb_hover.setText(f"col {col}  row {row}  selected")
        self.bottom.strip.selectRow(row)
        self.bottom._onRowClicked(row)

    def _onCellHover(self, col, row):
        idx = row * self.canvas.cols() + col
        self._sb_hover.setText(f"col {col}  row {row}  (frame {idx})")

    def _fit(self):
        self.canvas._fit()
        self.canvas.update()

    def _exportRow(self, row_idx, name, frame_count):
        """Export a single row's frames as a PNG sequence into a chosen folder."""
        if self._pm is None:
            return
        rows_data = self.canvas.framesByRow()
        if row_idx >= len(rows_data):
            return
        frames = rows_data[row_idx][:frame_count]
        if not frames:
            return

        # Ask user where to save
        base_dir = QFileDialog.getExistingDirectory(
            self, f"Choose folder to save '{name}' frames",
        )
        if not base_dir:
            return

        # Create subfolder with the animation name
        out_dir = os.path.join(base_dir, name)
        os.makedirs(out_dir, exist_ok=True)

        for i, pm in enumerate(frames):
            filepath = os.path.join(out_dir, f"{name}_{i + 1}.png")
            pm.save(filepath, "PNG")

        self.statusBar().showMessage(
            f"Exported {len(frames)} frames to {out_dir}", 5000
        )

    def _exportRowAni(self, row_idx, name, frame_count):
        """Export a row as a .ani file + spritesheet, registered to the project."""
        if self._pm is None:
            return

        # ── Validate project access ──
        mw = self._main_window
        if mw is None or not hasattr(mw, 'project') or mw.project is None:
            QMessageBox.warning(self, "No Project",
                                "Please save your game project first before exporting .ani files.")
            return
        if not hasattr(mw, 'current_project_path') or not mw.current_project_path:
            QMessageBox.warning(self, "No Project Path",
                                "Please save your game project first before exporting .ani files.")
            return

        rows_data = self.canvas.framesByRow()
        if row_idx >= len(rows_data):
            return
        frames = rows_data[row_idx][:frame_count]
        if not frames:
            return

        fw = self.canvas.frameWidth()
        fh = self.canvas.frameHeight()
        fps = self.bottom.fps_slider.value()

        # ── Build spritesheet (same grid layout as animation graph) ──
        import math
        total = len(frames)
        cols = int(math.ceil(math.sqrt(total)))
        rows = int(math.ceil(total / cols))
        sheet_w = cols * fw
        sheet_h = rows * fh

        sheet_img = QImage(sheet_w, sheet_h, QImage.Format_RGBA8888)
        sheet_img.fill(QColor(0, 0, 0, 0))
        p = QPainter(sheet_img)
        for i, pm in enumerate(frames):
            r = i // cols
            c = i % cols
            p.drawPixmap(c * fw, r * fh, fw, fh, pm)
        p.end()

        # ── Save to project animations folder ──
        project_dir = os.path.dirname(str(mw.current_project_path))
        anim_dir = os.path.join(project_dir, "animations")
        os.makedirs(anim_dir, exist_ok=True)

        sheet_filename = f"{name}.png"
        sheet_path = os.path.join(anim_dir, sheet_filename)
        sheet_img.save(sheet_path, "PNG")

        metadata = {
            'frame_count': total,
            'frame_width': fw,
            'frame_height': fh,
            'sheet_width': sheet_w,
            'sheet_height': sheet_h,
            'fps': fps,
            'spritesheet_path': sheet_filename,
        }
        meta_path = os.path.join(anim_dir, f"{name}.ani")
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        # ── Register AnimationExport on the project ──
        from models import AnimationExport
        # Remove existing entry with the same name to avoid duplicates
        mw.project.animation_exports = [
            a for a in mw.project.animation_exports if a.name != name
        ]
        entry = AnimationExport(
            name=name,
            spritesheet_path=sheet_filename,
            frame_count=total,
            frame_width=fw,
            frame_height=fh,
            sheet_width=sheet_w,
            sheet_height=sheet_h,
            fps=fps,
        )
        mw.project.animation_exports.append(entry)

        # Refresh the object tab's ani combo if open
        if hasattr(mw, 'obj_tab'):
            editor = mw.obj_tab.def_editor
            if editor._obj is not None:
                editor.load_object(editor._obj, mw.project)

        self.statusBar().showMessage(
            f"Exported '{name}.ani' → {anim_dir}", 5000
        )


# ── Entry point ───────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(DARK))
    pal.setColor(QPalette.WindowText, QColor(FG))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.AlternateBase, QColor(CARD))
    pal.setColor(QPalette.Text, QColor(FG))
    pal.setColor(QPalette.Button, QColor(CARD))
    pal.setColor(QPalette.ButtonText, QColor(FG))
    pal.setColor(QPalette.Highlight, QColor(ADIM))
    pal.setColor(QPalette.HighlightedText, QColor(AHOV))
    app.setPalette(pal)

    w = SpritesheetTool()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
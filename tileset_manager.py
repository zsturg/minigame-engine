# -*- coding: utf-8 -*-
"""
Tileset Manager Dialog
Lets the dev register PNG spritesheets as tilesets for use in TileLayer components.
Lives under Tools > Tileset Manager…
"""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox,
    QWidget, QScrollArea, QSizePolicy, QSpinBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen

from models import Project, RegisteredTileset

DARK     = "#0f0f12"
PANEL    = "#16161c"
SURFACE  = "#1e1e28"
SURFACE2 = "#26263a"
BORDER   = "#2e2e42"
ACCENT   = "#4a4860"
TEXT     = "#e8e6f0"
TEXT_DIM = "#7a7890"
DANGER   = "#f87171"


class TilesetPreview(QWidget):
    """Renders a tileset PNG with a 32x32 grid overlay so the dev can verify alignment."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._cols = 0
        self._rows = 0
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background: {DARK}; border: 1px solid {BORDER}; border-radius: 4px;")

    def load(self, path: str, cols: int, rows: int):
        self._pixmap = QPixmap(path)
        self._cols = cols
        self._rows = rows
        # Scale height to fit the widget width proportionally, capped at 300px
        if not self._pixmap.isNull():
            aspect = self._pixmap.height() / max(self._pixmap.width(), 1)
            w = self.width() if self.width() > 10 else 400
            h = min(int(w * aspect), 300)
            self.setFixedHeight(max(h, 80))
        self.update()

    def clear(self):
        self._pixmap = None
        self._cols = 0
        self._rows = 0
        self.setFixedHeight(120)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(DARK))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No tileset selected")
            return

        # Draw scaled pixmap
        scaled = self._pixmap.scaled(
            self.width(), self.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        x_off = (self.width() - scaled.width()) // 2
        y_off = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x_off, y_off, scaled)

        # Draw grid overlay
        if self._cols > 0 and self._rows > 0:
            cell_w = scaled.width() / self._cols
            cell_h = scaled.height() / self._rows
            pen = QPen(QColor(ACCENT))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            for c in range(self._cols + 1):
                x = x_off + int(c * cell_w)
                painter.drawLine(x, y_off, x, y_off + scaled.height())
            for r in range(self._rows + 1):
                y = y_off + int(r * cell_h)
                painter.drawLine(x_off, y, x_off + scaled.width(), y)

        painter.end()


class TilesetManagerDialog(QDialog):
    """
    Dialog for managing registered tilesets project-wide.
    Opened via Tools > Tileset Manager…
    Changes are applied directly to project.tilesets on accept.
    """

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Tileset Manager")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.resize(760, 540)
        self.setStyleSheet(f"""
            QDialog {{ background: {PANEL}; color: {TEXT}; }}
            QLabel {{ color: {TEXT}; font-size: 12px; background: transparent; }}
            QLineEdit {{
                padding: 5px 8px; background: {SURFACE}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px; font-size: 12px;
            }}
            QPushButton {{
                padding: 6px 14px; background: {SURFACE2}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 3px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)

        self._build_ui()
        self._populate_list()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ── LEFT: tileset list + add/remove ─────────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        list_lbl = QLabel("Registered Tilesets")
        list_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        left.addWidget(list_lbl)

        self.tileset_list = QListWidget()
        self.tileset_list.setFixedWidth(200)
        self.tileset_list.currentRowChanged.connect(self._on_selection_changed)
        left.addWidget(self.tileset_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_tileset)
        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: 1px solid {DANGER};
                color: {DANGER}; border-radius: 4px; padding: 6px 14px; font-size: 12px; }}
            QPushButton:hover {{ background: {DANGER}; color: white; }}
        """)
        remove_btn.clicked.connect(self._remove_tileset)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        left.addLayout(btn_row)

        root.addLayout(left)

        # ── RIGHT: detail / preview ──────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        detail_lbl = QLabel("Tileset Details")
        detail_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        right.addWidget(detail_lbl)

        # Name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Overworld Tiles")
        self.name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self.name_edit)
        right.addLayout(name_row)

        # Tile size row
        tile_size_row = QHBoxLayout()
        tile_size_row.addWidget(QLabel("Tile size (px):"))
        self.tile_size_spin = QSpinBox()
        self.tile_size_spin.setRange(8, 512)
        self.tile_size_spin.setSingleStep(8)
        self.tile_size_spin.setValue(32)
        self.tile_size_spin.setStyleSheet(f"""
            QSpinBox {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 4px; padding: 4px 8px; font-size: 12px; }}
        """)
        self.tile_size_spin.setToolTip("Must divide evenly into the image width and height")
        self.tile_size_spin.valueChanged.connect(self._on_tile_size_changed)
        tile_size_row.addWidget(self.tile_size_spin)
        right.addLayout(tile_size_row)

        # Path row
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("PNG:"))
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("No file selected")
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_png)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        right.addLayout(path_row)

        # Info row (columns x rows, tile count)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        right.addWidget(self.info_lbl)

        # Preview
        self.preview_lbl = QLabel("Preview")
        self.preview_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        right.addWidget(self.preview_lbl)

        self.preview = TilesetPreview()
        right.addWidget(self.preview)

        right.addStretch()

        # OK / Cancel
        btn_row2 = QHBoxLayout()
        btn_row2.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold; border-color: {ACCENT};")
        ok_btn.clicked.connect(self.accept)
        btn_row2.addWidget(cancel_btn)
        btn_row2.addWidget(ok_btn)
        right.addLayout(btn_row2)

        root.addLayout(right, stretch=1)

    # ── List management ──────────────────────────────────────

    def _populate_list(self):
        self.tileset_list.clear()
        for ts in self.project.tilesets:
            item = QListWidgetItem(ts.name or "(unnamed)")
            item.setData(Qt.ItemDataRole.UserRole, ts.id)
            self.tileset_list.addItem(item)
        if self.tileset_list.count() > 0:
            self.tileset_list.setCurrentRow(0)
        else:
            self._clear_detail()

    def _current_tileset(self) -> RegisteredTileset | None:
        item = self.tileset_list.currentItem()
        if item is None:
            return None
        ts_id = item.data(Qt.ItemDataRole.UserRole)
        return self.project.get_tileset(ts_id)

    def _on_selection_changed(self, row: int):
        ts = self._current_tileset()
        if ts is None:
            self._clear_detail()
            return
        self._loading = True
        self.name_edit.setText(ts.name)
        self.tile_size_spin.setValue(ts.tile_size)
        self.path_edit.setText(ts.path or "")
        self._refresh_info(ts)
        if ts.path:
            self.preview.load(ts.path, ts.columns, ts.rows)
        else:
            self.preview.clear()
        self._loading = False

    def _clear_detail(self):
        self._loading = True
        self.name_edit.clear()
        self.tile_size_spin.setValue(32)
        self.path_edit.clear()
        self.info_lbl.setText("")
        self.preview.clear()
        self._loading = False

    def _refresh_info(self, ts: RegisteredTileset):
        self.preview_lbl.setText(f"Preview  ({ts.tile_size}×{ts.tile_size} grid overlay)")
        if ts.columns > 0 and ts.rows > 0:
            total = ts.columns * ts.rows
            self.info_lbl.setText(
                f"{ts.columns} columns × {ts.rows} rows  —  {total} tiles total  "
                f"({ts.columns * ts.tile_size}×{ts.rows * ts.tile_size} px)"
            )
        else:
            self.info_lbl.setText("")

    # ── Editing ──────────────────────────────────────────────

    _loading: bool = False

    def _on_name_changed(self, text: str):
        if self._loading:
            return
        ts = self._current_tileset()
        if ts is None:
            return
        ts.name = text
        item = self.tileset_list.currentItem()
        if item:
            item.setText(text or "(unnamed)")

    def _on_tile_size_changed(self, value: int):
        if self._loading:
            return
        ts = self._current_tileset()
        if ts is None:
            return
        ts.tile_size = value
        # Recompute columns/rows if a PNG is already loaded
        if ts.path:
            pix = QPixmap(ts.path)
            if not pix.isNull() and value > 0:
                if pix.width() % value == 0 and pix.height() % value == 0:
                    ts.columns = pix.width() // value
                    ts.rows = pix.height() // value
                else:
                    ts.columns = 0
                    ts.rows = 0
        self._refresh_info(ts)
        self.preview.load(ts.path, ts.columns, ts.rows) if ts.path else self.preview.clear()

    def _browse_png(self):
        ts = self._current_tileset()
        if ts is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select Tileset PNG", "", "PNG Images (*.png)")
        if not path:
            return

        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "Invalid Image", "Could not load the selected PNG.")
            return

        w, h = pix.width(), pix.height()
        tile_size = ts.tile_size
        if w % tile_size != 0 or h % tile_size != 0:
            QMessageBox.warning(
                self, "Size Mismatch",
                f"Image size {w}×{h} is not evenly divisible by the tile size ({tile_size}px).\n"
                f"Adjust the tile size or use an image whose dimensions are multiples of {tile_size}."
            )
            return

        ts.path = path
        ts.columns = w // tile_size
        ts.rows = h // tile_size
        self.path_edit.setText(path)
        self._refresh_info(ts)
        self.preview.load(path, ts.columns, ts.rows)

    def _add_tileset(self):
        ts = RegisteredTileset(name="New Tileset")
        self.project.tilesets.append(ts)
        item = QListWidgetItem(ts.name)
        item.setData(Qt.ItemDataRole.UserRole, ts.id)
        self.tileset_list.addItem(item)
        self.tileset_list.setCurrentItem(item)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _remove_tileset(self):
        ts = self._current_tileset()
        if ts is None:
            return
        # Warn if any TileLayer components reference this tileset
        refs = []
        for scene in self.project.scenes:
            for comp in scene.components:
                if comp.component_type == "TileLayer" and comp.config.get("tileset_id") == ts.id:
                    refs.append(scene.name or f"Scene {self.project.scenes.index(scene) + 1}")
        if refs:
            names = ", ".join(refs)
            reply = QMessageBox.warning(
                self, "Tileset In Use",
                f"This tileset is used by: {names}\n\nRemove anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.project.tilesets = [t for t in self.project.tilesets if t.id != ts.id]
        row = self.tileset_list.currentRow()
        self.tileset_list.takeItem(row)
        if self.tileset_list.count() == 0:
            self._clear_detail()
# -*- coding: utf-8 -*-
"""
Project Explorer - Read-only file browser for viewing project folder contents.
Displays files in the project folder with view options (list/grid) and filtering.
Supports drag-and-drop INTO the explorer to copy files to the project folder.
"""

from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QFrame, QFileDialog,
    QMessageBox, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent, QColor

# ─────────────────────────────────────────────────────────────
#  COLORS (matches main app theme)
# ─────────────────────────────────────────────────────────────

DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURFACE2 = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
TEXT    = "#e8e6f0"
TEXT_DIM = "#7a7890"
TEXT_MUTED = "#4a4860"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER  = "#f87171"

# ─────────────────────────────────────────────────────────────
#  FILE TYPE DEFINITIONS
# ─────────────────────────────────────────────────────────────

FILE_CATEGORIES = {
    "All": None,  # No filter
    "Images": [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"],
    "Audio": [".wav", ".mp3", ".ogg", ".flac", ".aac"],
    "Fonts": [".ttf", ".otf", ".pvf"],
    "Animation": [".json", ".anim"],  # Placeholder for future animation formats
    "Other": [],  # Catch-all for unrecognized types
}

# File type to icon/color mapping for visual distinction
FILE_TYPE_COLORS = {
    "image": "#7c6aff",   # Purple/Accent
    "audio": "#c084fc",   # Light purple
    "font": "#06b6d4",    # Cyan
    "animation": "#f59e0b",  # Orange
    "other": TEXT_DIM,
}


def get_file_category(filename: str) -> str:
    """Determine which category a file belongs to based on extension."""
    ext = Path(filename).suffix.lower()
    for category, extensions in FILE_CATEGORIES.items():
        if extensions is None:
            continue
        if ext in extensions:
            return category
    return "Other"


def get_file_type_color(filename: str) -> str:
    """Get the display color for a file based on its type."""
    category = get_file_category(filename)
    type_map = {
        "Images": "image",
        "Audio": "audio",
        "Fonts": "font",
        "Animation": "animation",
        "Other": "other",
    }
    return FILE_TYPE_COLORS.get(type_map.get(category, "other"), TEXT_DIM)


# ─────────────────────────────────────────────────────────────
#  HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_unique_filename(folder: Path, filename: str) -> str:
    """
    If filename already exists in folder, return a renamed version.
    e.g., sprite.png -> sprite_1.png -> sprite_2.png
    """
    target = folder / filename
    if not target.exists():
        return filename
    
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        if not (folder / new_name).exists():
            return new_name
        counter += 1


def copy_file_to_project(source_path: str, project_folder: Path) -> Optional[str]:
    """
    Copy a file to the project folder, handling duplicates by renaming.
    Returns the final filename (just the name, not full path) or None on failure.
    """
    if not project_folder or not project_folder.exists():
        return None
    
    source = Path(source_path)
    if not source.exists():
        return None
    
    filename = get_unique_filename(project_folder, source.name)
    target = project_folder / filename
    
    try:
        shutil.copy2(source, target)
        return filename
    except Exception as e:
        print(f"Failed to copy {source} to {target}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  DROP-ENABLED LIST WIDGET
# ─────────────────────────────────────────────────────────────

class DropEnabledListWidget(QListWidget):
    """QListWidget that accepts file drops to copy files into the project folder."""
    
    files_dropped = pyqtSignal(list)  # Emits list of source file paths
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Check if any URLs are files (not directories)
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file():
                        event.acceptProposedAction()
                        return
        event.ignore()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            file_paths = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file():
                        file_paths.append(str(path))
            
            if file_paths:
                self.files_dropped.emit(file_paths)
                event.acceptProposedAction()
                return
        
        event.ignore()


# ─────────────────────────────────────────────────────────────
#  PROJECT EXPLORER WIDGET
# ─────────────────────────────────────────────────────────────

class ProjectExplorer(QWidget):
    """
    Read-only file browser showing contents of the project folder.
    Supports drag-and-drop to import files.
    """
    
    files_imported = pyqtSignal(list)  # Emits list of imported filenames
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_folder: Optional[Path] = None
        self._view_mode = "list"  # "list" or "grid"
        self._current_filter = "All"
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ── Header toolbar ────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(32)
        toolbar.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 0, 8, 0)
        tb_layout.setSpacing(8)
        
        # Title
        title = QLabel("PROJECT FILES")
        title.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        tb_layout.addWidget(title)
        
        tb_layout.addStretch()
        
        # Filter dropdown
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        tb_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.setFixedWidth(80)
        self.filter_combo.setStyleSheet(self._combo_style())
        for category in FILE_CATEGORIES.keys():
            self.filter_combo.addItem(category)
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self.filter_combo)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {BORDER}; max-width: 1px;")
        tb_layout.addWidget(sep)
        
        # View toggle buttons
        self.list_btn = QPushButton("☰")
        self.list_btn.setFixedSize(24, 24)
        self.list_btn.setToolTip("List View")
        self.list_btn.setStyleSheet(self._view_btn_style(active=True))
        self.list_btn.clicked.connect(lambda: self._set_view_mode("list"))
        tb_layout.addWidget(self.list_btn)
        
        self.grid_btn = QPushButton("⊞")
        self.grid_btn.setFixedSize(24, 24)
        self.grid_btn.setToolTip("Grid View")
        self.grid_btn.setStyleSheet(self._view_btn_style(active=False))
        self.grid_btn.clicked.connect(lambda: self._set_view_mode("grid"))
        tb_layout.addWidget(self.grid_btn)
        
        # Refresh button
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip("Refresh")
        refresh_btn.setStyleSheet(self._icon_btn_style())
        refresh_btn.clicked.connect(self.refresh)
        tb_layout.addWidget(refresh_btn)
        
        layout.addWidget(toolbar)
        self._toolbar = toolbar
        
        # ── File list ─────────────────────────────────────────
        self.file_list = DropEnabledListWidget()
        self.file_list.setStyleSheet(self._list_style())
        self.file_list.files_dropped.connect(self._on_files_dropped)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.file_list)
        
        # ── Empty state / no folder message ───────────────────
        self.empty_label = QLabel("No project folder set.\nGo to Game Data → Settings to set one.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        
        # Initially show empty state
        self.file_list.hide()
        self.empty_label.show()
    
    # ── Styles ────────────────────────────────────────────────
    
    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: {SURFACE};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 10px;
            }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE2}; color: {TEXT};
                border: 1px solid {BORDER};
                selection-background-color: {ACCENT};
            }}
        """
    
    def _view_btn_style(self, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: {ACCENT};
                    color: white;
                    border: none;
                    border-radius: 3px;
                    font-size: 12px;
                }}
            """
        return f"""
            QPushButton {{
                background: {SURFACE2};
                color: {TEXT_DIM};
                border: 1px solid {BORDER};
                border-radius: 3px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {SURFACE};
                color: {TEXT};
            }}
        """
    
    def _icon_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: {SURFACE2};
                color: {TEXT_DIM};
                border: 1px solid {BORDER};
                border-radius: 3px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {ACCENT};
                color: white;
                border-color: {ACCENT};
            }}
        """
    
    def _list_style(self) -> str:
        return f"""
            QListWidget {{
                background: {SURFACE};
                border: none;
                color: {TEXT};
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {BORDER};
            }}
            QListWidget::item:hover {{
                background: {SURFACE2};
            }}
        """
    
    # ── View mode ─────────────────────────────────────────────
    
    def _set_view_mode(self, mode: str):
        self._view_mode = mode
        self.list_btn.setStyleSheet(self._view_btn_style(active=(mode == "list")))
        self.grid_btn.setStyleSheet(self._view_btn_style(active=(mode == "grid")))
        
        if mode == "grid":
            self.file_list.setViewMode(QListWidget.ViewMode.IconMode)
            self.file_list.setIconSize(self.file_list.iconSize().scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio))
            self.file_list.setGridSize(self.file_list.gridSize().scaled(70, 70, Qt.AspectRatioMode.KeepAspectRatio))
            self.file_list.setSpacing(4)
            self.file_list.setWordWrap(True)
        else:
            self.file_list.setViewMode(QListWidget.ViewMode.ListMode)
            self.file_list.setSpacing(0)
            self.file_list.setWordWrap(False)
        
        self.refresh()
    
    # ── Filter ────────────────────────────────────────────────
    
    def _on_filter_changed(self, category: str):
        self._current_filter = category
        self.refresh()
    
    # ── Public API ────────────────────────────────────────────
    
    def set_project_folder(self, folder_path: Optional[str]):
        """Set the project folder to display."""
        if folder_path:
            self._project_folder = Path(folder_path)
        else:
            self._project_folder = None
        self.refresh()
    
    def get_project_folder(self) -> Optional[Path]:
        """Get the current project folder path."""
        return self._project_folder
    
    def refresh(self):
        """Refresh the file list from disk."""
        self.file_list.clear()
        
        if not self._project_folder or not self._project_folder.exists():
            self.file_list.hide()
            self.empty_label.show()
            return
        
        self.file_list.show()
        self.empty_label.hide()
        
        # Get all files in the project folder (flat, no subdirectories)
        try:
            files = [f for f in self._project_folder.iterdir() if f.is_file()]
        except Exception as e:
            print(f"Error reading project folder: {e}")
            return
        
        # Apply filter
        if self._current_filter != "All":
            extensions = FILE_CATEGORIES.get(self._current_filter, [])
            if extensions:
                files = [f for f in files if f.suffix.lower() in extensions]
            elif self._current_filter == "Other":
                # Show files that don't match any known category
                known_exts = set()
                for exts in FILE_CATEGORIES.values():
                    if exts:
                        known_exts.update(exts)
                files = [f for f in files if f.suffix.lower() not in known_exts]
        
        # Sort alphabetically
        files.sort(key=lambda f: f.name.lower())
        
        # Populate list
        for file_path in files:
            item = QListWidgetItem(file_path.name)
            color = get_file_type_color(file_path.name)
            item.setForeground(QColor(color))
            
            # Add category tag for list view
            category = get_file_category(file_path.name)
            item.setToolTip(f"{file_path.name}\nType: {category}\nSize: {self._format_size(file_path)}")
            
            self.file_list.addItem(item)
        
        # Update empty state if no files after filter
        if self.file_list.count() == 0:
            self.empty_label.setText(f"No {self._current_filter.lower()} files in project folder.")
            self.empty_label.show()
            self.file_list.hide()
    
    def _format_size(self, file_path: Path) -> str:
        """Format file size for display."""
        try:
            size = file_path.stat().st_size
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            else:
                return f"{size / (1024 * 1024):.1f} MB"
        except:
            return "Unknown"
    
    # ── Drag and drop handling ────────────────────────────────
    
    def _on_files_dropped(self, file_paths: List[str]):
        """Handle files dropped onto the explorer."""
        if not self._project_folder or not self._project_folder.exists():
            QMessageBox.warning(
                self, "No Project Folder",
                "Please set a project folder in Game Data → Settings first."
            )
            return
        
        imported = []
        for source_path in file_paths:
            filename = copy_file_to_project(source_path, self._project_folder)
            if filename:
                imported.append(filename)
        
        if imported:
            self.refresh()
            self.files_imported.emit(imported)
    
    # ── Context menu ──────────────────────────────────────────
    
    def _show_context_menu(self, position):
        """Show right-click context menu."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {SURFACE};
                color: {TEXT};
                border: 1px solid {BORDER};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 3px;
            }}
            QMenu::item:selected {{
                background: {ACCENT};
                color: white;
            }}
        """)
        
        refresh_action = menu.addAction("Refresh")
        refresh_action.triggered.connect(self.refresh)
        
        if self._project_folder and self._project_folder.exists():
            menu.addSeparator()
            open_folder = menu.addAction("Open Folder in Explorer")
            open_folder.triggered.connect(self._open_in_system)
        
        menu.exec(self.file_list.mapToGlobal(position))
    
    def _open_in_system(self):
        """Open the project folder in the system file manager."""
        if self._project_folder and self._project_folder.exists():
            import subprocess
            import sys
            if sys.platform == "win32":
                subprocess.run(["explorer", str(self._project_folder)])
            elif sys.platform == "darwin":
                subprocess.run(["open", str(self._project_folder)])
            else:
                subprocess.run(["xdg-open", str(self._project_folder)])
    
    # ── Theming ───────────────────────────────────────────────
    
    def restyle(self, c: dict):
        """Apply theme colors."""
        global DARK, PANEL, SURFACE, SURFACE2, BORDER, ACCENT, TEXT, TEXT_DIM, TEXT_MUTED
        DARK = c.get('DARK', DARK)
        PANEL = c.get('PANEL', PANEL)
        SURFACE = c.get('SURFACE', SURFACE)
        SURFACE2 = c.get('SURFACE2', SURFACE2)
        BORDER = c.get('BORDER', BORDER)
        ACCENT = c.get('ACCENT', ACCENT)
        TEXT = c.get('TEXT', TEXT)
        TEXT_DIM = c.get('TEXT_DIM', TEXT_DIM)
        TEXT_MUTED = c.get('TEXT_MUTED', TEXT_MUTED)
        
        self._toolbar.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        self.file_list.setStyleSheet(self._list_style())
        self.filter_combo.setStyleSheet(self._combo_style())
        self.empty_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        
        # Update view button styles
        self.list_btn.setStyleSheet(self._view_btn_style(active=(self._view_mode == "list")))
        self.grid_btn.setStyleSheet(self._view_btn_style(active=(self._view_mode == "grid")))


# ─────────────────────────────────────────────────────────────
#  UTILITY: Copy asset to project folder (for use by registry panels)
# ─────────────────────────────────────────────────────────────

def import_asset_to_project(source_path: str, project_folder: Optional[str]) -> Optional[str]:
    """
    Copy an asset file to the project folder.
    Returns the filename (not full path) on success, None on failure.
    Used by asset registry panels when adding new assets.
    """
    if not project_folder:
        return None
    
    folder = Path(project_folder)
    if not folder.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Failed to create project folder: {e}")
            return None
    
    return copy_file_to_project(source_path, folder)

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from theme_utils import get_default_theme


class DocumentViewerDialog(QDialog):
    def __init__(self, title: str, doc_path: str | Path, parent=None):
        super().__init__(parent)
        self._doc_path = Path(doc_path)
        self._colors = self._resolve_colors(parent)
        self._build_ui(title)
        self._load_document()

    def _resolve_colors(self, parent) -> dict:
        if parent is not None:
            theme = getattr(parent, "current_theme", None)
            if isinstance(theme, dict):
                colors = theme.get("colors")
                if isinstance(colors, dict):
                    return colors
        return get_default_theme()

    def _build_ui(self, title: str) -> None:
        c = self._colors
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(960, 700)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {c['PANEL']};
                color: {c['TEXT']};
            }}
            QLabel {{
                color: {c['TEXT_DIM']};
                background: transparent;
            }}
            QLineEdit {{
                background: {c['SURFACE']};
                color: {c['TEXT']};
                border: 1px solid {c['BORDER']};
                border-radius: 4px;
                padding: 6px 8px;
            }}
            QPushButton {{
                background: {c['SURFACE2']};
                color: {c['TEXT']};
                border: 1px solid {c['BORDER']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background: {c['ACCENT']};
                border-color: {c['ACCENT']};
                color: white;
            }}
            QTextBrowser {{
                background: {c['SURFACE']};
                color: {c['TEXT']};
                border: 1px solid {c['BORDER']};
                border-radius: 6px;
                padding: 12px;
                selection-background-color: {c['ACCENT']};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {c['TEXT']}; font-size: 16px; font-weight: 700;")
        top.addWidget(title_lbl)
        top.addStretch(1)

        path_lbl = QLabel(str(self._doc_path.name))
        path_lbl.setStyleSheet(f"color: {c['TEXT_MUTED']}; font-size: 11px;")
        top.addWidget(path_lbl)
        root.addLayout(top)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        search_lbl = QLabel("Search")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Find in document")
        self.search_edit.returnPressed.connect(self.find_next)

        prev_btn = QPushButton("Previous")
        prev_btn.clicked.connect(self.find_previous)
        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self.find_next)

        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        search_row.addWidget(search_lbl)
        search_row.addWidget(self.search_edit, stretch=1)
        search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn)
        search_row.addWidget(self.status_lbl)
        root.addLayout(search_row)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setReadOnly(True)
        root.addWidget(self.browser, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _load_document(self) -> None:
        if not self._doc_path.exists():
            self.browser.setHtml(
                f"""
                <h1>Document Not Found</h1>
                <p>The requested bundled document could not be found.</p>
                <p><code>{self._doc_path}</code></p>
                """
            )
            self.status_lbl.setText("Missing file")
            return

        try:
            text = self._doc_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.browser.setHtml(
                f"""
                <h1>Unable to Open Document</h1>
                <p>The viewer could not read this file.</p>
                <p><code>{self._doc_path}</code></p>
                <p>{exc}</p>
                """
            )
            self.status_lbl.setText("Read error")
            return

        suffix = self._doc_path.suffix.lower()
        if suffix in {".md", ".markdown"} and hasattr(self.browser, "setMarkdown"):
            self.browser.setMarkdown(text)
        elif suffix in {".html", ".htm"}:
            self.browser.setHtml(text)
        else:
            self.browser.setPlainText(text)
        self.browser.moveCursor(self.browser.textCursor().MoveOperation.Start)
        self.status_lbl.setText("")

    def _find(self, backward: bool = False) -> None:
        query = self.search_edit.text().strip()
        if not query:
            self.status_lbl.setText("Enter search text")
            return

        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag()
        if self.browser.find(query, flags):
            self.status_lbl.setText("")
            return

        cursor = self.browser.textCursor()
        cursor.movePosition(
            cursor.MoveOperation.End if backward else cursor.MoveOperation.Start
        )
        self.browser.setTextCursor(cursor)

        if self.browser.find(query, flags):
            self.status_lbl.setText("Wrapped")
        else:
            self.status_lbl.setText("No matches")

    def find_next(self) -> None:
        self._find(backward=False)

    def find_previous(self) -> None:
        self._find(backward=True)

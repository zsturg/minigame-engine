# -*- coding: utf-8 -*-
"""
Theme persistence manager for Vita Adventure Creator.
"""

from pathlib import Path
import json
from typing import Dict

THEMES_DIR = Path.home() / ".vita_adventure_creator" / "themes"

def save_theme(name: str, theme: Dict):
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    path = THEMES_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(theme, f, indent=2)
    return path

def load_theme(name: str) -> Dict:
    path = THEMES_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def list_saved_themes() -> list[str]:
    if THEMES_DIR.exists():
        return [p.stem for p in THEMES_DIR.glob("*.json")]
    return []
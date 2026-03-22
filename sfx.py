# ===== FILE: tab_sfx.py =====

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator -- SFX Generator Tab
A PySfxr-style sound effect designer integrated into the editor.
UI only — connect play_sound / export_wav signals for audio backend.
"""

from __future__ import annotations
import random
import io
import wave
import math
import random

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QScrollArea, QButtonGroup, QSizePolicy,
    QGridLayout, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QObject, QBuffer, QIODevice, QByteArray
from PySide6.QtMultimedia import QAudioFormat, QAudioSink

# -- Colours (shared palette) --------------------------------------------------
DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURF2   = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
ACCENT2 = "#ff6a9b"
TEXT    = "#e8e6f0"
DIM     = "#7a7890"
MUTED   = "#4a4860"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER  = "#f87171"

# Colour-coded preset categories
PRESET_COLORS = {
    "Pickup / Coin":  WARNING,
    "Laser / Shoot":  "#38bdf8",
    "Explosion":      DANGER,
    "Powerup":        SUCCESS,
    "Hit / Hurt":     ACCENT2,
    "Jump":           "#c084fc",
    "Blip / Select":  "#06b6d4",
    "Mutate":         "#fb923c",
    "Randomize":      DIM,
}

# -- Style helpers (mirrors tab_scene_options.py) ------------------------------

def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(f"""
        color: {DIM}; font-size: 10px; font-weight: 700;
        letter-spacing: 1.5px; padding: 8px 0 4px 0; background: transparent;
    """)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
    return f


def _vdivider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet(f"background: {BORDER}; max-width: 1px; border: none;")
    return f


def _btn(label: str, accent=False, danger=False, small=False, color: str | None = None) -> QPushButton:
    b = QPushButton(label)
    h = 28 if small else 32
    b.setFixedHeight(h)
    if accent:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT}; color: white;
                border: none; border-radius: 4px;
                padding: 0 10px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #6a59ef; }}
        """)
    elif danger:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {DANGER};
                border: 1px solid {DANGER}; border-radius: 4px;
                padding: 0 10px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {DANGER}; color: white; }}
        """)
    elif color:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {color};
                border: 1px solid {color}; border-radius: 4px;
                padding: 0 10px; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {color}22; }}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: {SURF2}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 4px;
                padding: 0 10px; font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {ACCENT}; border-color: {ACCENT}; color: white;
            }}
        """)
    return b


# -- Waveform toggle button ----------------------------------------------------

class WaveButton(QPushButton):
    """A checkable button styled as a waveform selector."""
    def __init__(self, label: str):
        super().__init__(label)
        self.setCheckable(True)
        self.setFixedHeight(30)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT}; color: white;
                    border: 1px solid {ACCENT}; border-radius: 4px;
                    font-size: 12px; font-weight: 600;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {SURF2}; color: {DIM};
                    border: 1px solid {BORDER}; border-radius: 4px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border-color: {ACCENT}; color: {TEXT};
                }}
            """)


# -- Float slider row ----------------------------------------------------------

class FloatSliderRow(QWidget):
    """A labelled horizontal float slider row in the app's style."""
    valueChanged = Signal(float)

    def __init__(self, name: str, min_val: float, max_val: float, default_val: float):
        super().__init__()
        self.min_val = min_val
        self.max_val = max_val

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)

        self.name_lbl = QLabel(name)
        self.name_lbl.setFixedWidth(130)
        self.name_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px; background: transparent;")

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {SURF2}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {ACCENT}; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT}; border-radius: 2px;
            }}
        """)

        self.val_lbl = QLabel()
        self.val_lbl.setFixedWidth(38)
        self.val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val_lbl.setStyleSheet(f"color: {DIM}; font-size: 11px; background: transparent;")

        layout.addWidget(self.name_lbl)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.val_lbl)

        self.slider.valueChanged.connect(self._on_changed)
        self.set_value(default_val)

    def _on_changed(self, _):
        v = self.get_value()
        self.val_lbl.setText(f"{v:+.2f}" if self.min_val < 0 else f"{v:.2f}")
        self.valueChanged.emit(v)

    def get_value(self) -> float:
        ratio = self.slider.value() / 1000.0
        return self.min_val + ratio * (self.max_val - self.min_val)

    def set_value(self, val: float):
        val = max(self.min_val, min(val, self.max_val))
        ratio = (val - self.min_val) / (self.max_val - self.min_val)
        self.slider.blockSignals(True)
        self.slider.setValue(int(ratio * 1000))
        self.slider.blockSignals(False)
        self._on_changed(0)


# -- Slider group (labelled section) ------------------------------------------

def _slider_group(title: str, specs: list[tuple]) -> tuple[QWidget, dict]:
    """
    Returns (widget, sliders_dict).
    specs: list of (name, min_val, max_val, default_val)
    """
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(_section(title))
    layout.addWidget(_divider())

    sliders = {}
    for name, mn, mx, dfl in specs:
        row = FloatSliderRow(name, mn, mx, dfl)
        layout.addWidget(row)
        sliders[name] = row

    layout.addSpacing(6)
    return container, sliders


# -- Main Tab Widget -----------------------------------------------------------

class TabSfx(QWidget):
    """SFX Generator tab — drop into the main QTabWidget."""

    # Emitted when the user clicks Play or Export so the host can handle audio.
    play_requested  = Signal(dict)   # passes the full params dict
    export_requested = Signal(dict)  # passes the full params dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {DARK}; color: {TEXT};")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left sidebar ──────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(170)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(12, 14, 12, 14)
        left_v.setSpacing(4)
        left_v.setAlignment(Qt.AlignTop)

        left_v.addWidget(_section("PRESETS"))

        for label, color in PRESET_COLORS.items():
            btn = _btn(label, color=color, small=True)
            btn.clicked.connect(lambda checked=False, lbl=label: self._apply_preset(lbl))
            left_v.addWidget(btn)

        left_v.addSpacing(16)
        left_v.addWidget(_divider())
        left_v.addSpacing(12)

        self.play_btn = _btn("▶  PLAY", accent=True)
        self.play_btn.setFixedHeight(36)
        self.play_btn.clicked.connect(self._on_play)
        left_v.addWidget(self.play_btn)

        self.export_btn = _btn("⬇  EXPORT .WAV")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self._on_export)
        left_v.addWidget(self.export_btn)

        root.addWidget(left)

        # ── Main scrollable area ──────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setStyleSheet(f"background: {DARK};")
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(20, 16, 20, 20)
        body_h.setSpacing(24)
        body_h.setAlignment(Qt.AlignTop)

        # ── Column 1: Waveform + Envelope + Frequency ─────────
        col1 = QWidget()
        col1.setStyleSheet("background: transparent;")
        col1_v = QVBoxLayout(col1)
        col1_v.setContentsMargins(0, 0, 0, 0)
        col1_v.setSpacing(0)
        col1_v.setAlignment(Qt.AlignTop)

        # Waveform selector
        col1_v.addWidget(_section("WAVEFORM"))
        col1_v.addWidget(_divider())
        wave_row = QHBoxLayout()
        wave_row.setSpacing(6)
        self.wave_btn_group = QButtonGroup(self)
        self._wave_btns = []
        for i, name in enumerate(["Square", "Sawtooth", "Sine", "Noise"]):
            wb = WaveButton(name)
            self.wave_btn_group.addButton(wb, i)
            wave_row.addWidget(wb)
            self._wave_btns.append(wb)
        self._wave_btns[0].setChecked(True)
        wave_row.addStretch()
        col1_v.addLayout(wave_row)
        col1_v.addSpacing(10)

        # Envelope
        env_widget, env_sliders = _slider_group("ENVELOPE", [
            ("Attack Time",    0.0, 1.0, 0.0),
            ("Sustain Time",   0.0, 1.0, 0.3),
            ("Sustain Punch",  0.0, 1.0, 0.0),
            ("Decay Time",     0.0, 1.0, 0.4),
        ])
        col1_v.addWidget(env_widget)

        # Frequency
        freq_widget, freq_sliders = _slider_group("FREQUENCY", [
            ("Start Frequency", 0.0,  1.0, 0.3),
            ("Min Frequency",   0.0,  1.0, 0.0),
            ("Slide",          -1.0,  1.0, 0.0),
            ("Delta Slide",    -1.0,  1.0, 0.0),
            ("Vibrato Depth",   0.0,  1.0, 0.0),
            ("Vibrato Speed",   0.0,  1.0, 0.0),
        ])
        col1_v.addWidget(freq_widget)
        col1_v.addStretch()

        body_h.addWidget(col1, 1)
        body_h.addWidget(_vdivider())

        # ── Column 2: Filters + Phaser + Duty + Retrigger ─────
        col2 = QWidget()
        col2.setStyleSheet("background: transparent;")
        col2_v = QVBoxLayout(col2)
        col2_v.setContentsMargins(0, 0, 0, 0)
        col2_v.setSpacing(0)
        col2_v.setAlignment(Qt.AlignTop)

        lpf_widget, lpf_sliders = _slider_group("LOW-PASS FILTER", [
            ("LPF Cutoff",       0.0,  1.0, 1.0),
            ("LPF Cutoff Sweep", -1.0, 1.0, 0.0),
            ("LPF Resonance",    0.0,  1.0, 0.0),
        ])
        col2_v.addWidget(lpf_widget)

        hpf_widget, hpf_sliders = _slider_group("HIGH-PASS FILTER", [
            ("HPF Cutoff",       0.0,  1.0, 0.0),
            ("HPF Cutoff Sweep", -1.0, 1.0, 0.0),
        ])
        col2_v.addWidget(hpf_widget)

        phaser_widget, phaser_sliders = _slider_group("PHASER", [
            ("Phaser Offset", -1.0, 1.0, 0.0),
            ("Phaser Sweep",  -1.0, 1.0, 0.0),
        ])
        col2_v.addWidget(phaser_widget)

        duty_widget, duty_sliders = _slider_group("DUTY / RETRIGGER", [
            ("Square Duty",    0.0,  1.0, 0.5),
            ("Duty Sweep",    -1.0,  1.0, 0.0),
            ("Retrigger Rate", 0.0,  1.0, 0.0),
        ])
        col2_v.addWidget(duty_widget)
        col2_v.addStretch()

        body_h.addWidget(col2, 1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ── Collect all sliders into one dict ─────────────────
        self.sliders: dict[str, FloatSliderRow] = {}
        for d in (env_sliders, freq_sliders, lpf_sliders,
                  hpf_sliders, phaser_sliders, duty_sliders):
            self.sliders.update(d)

    # ── Preset / randomise ────────────────────────────────────

    def _apply_preset(self, label: str):
        """
        Generate preset parameters using the canonical DrPetter / jsfxr algorithms.
        Each preset zeros everything first, then sets only the parameters that
        define that sound class — exactly as the original sfxr C source does.
        frnd(x) = random float in [0, x]
        rnd(x)  = random int in [0, x]
        """
        frnd = lambda x: random.uniform(0.0, x)
        rnd  = lambda x: random.randint(0, x)

        # Helper: zero all sliders and select a waveform
        def _zero(wave: int):
            btn = self.wave_btn_group.button(wave)
            if btn:
                btn.setChecked(True)
            for s in self.sliders.values():
                s.set_value(0.0)
            # Restore non-zero defaults that "zero" would break
            self.sliders["LPF Cutoff"].set_value(1.0)
            self.sliders["Square Duty"].set_value(0.5)
            self.sliders["Sustain Time"].set_value(0.3)
            self.sliders["Decay Time"].set_value(0.4)

        if label == "Pickup / Coin":
            _zero(WAVE_SQUARE)
            self.sliders["Start Frequency"].set_value(0.4 + frnd(0.5))
            self.sliders["Sustain Time"].set_value(frnd(0.1))
            self.sliders["Sustain Punch"].set_value(0.3 + frnd(0.3))
            self.sliders["Decay Time"].set_value(0.1 + frnd(0.4))
            if rnd(1):
                self.sliders["Slide"].set_value(0.3 + frnd(0.3))
                self.sliders["Min Frequency"].set_value(frnd(0.2))
            if rnd(1):
                self.sliders["Square Duty"].set_value(frnd(0.6))
                self.sliders["Duty Sweep"].set_value(frnd(0.2))
            else:
                self.sliders["Square Duty"].set_value(0.4 + frnd(0.4))

        elif label == "Laser / Shoot":
            wave = rnd(2)  # square, saw, or sine
            _zero(wave)
            self.sliders["Start Frequency"].set_value(0.5 + frnd(0.5))
            self.sliders["Min Frequency"].set_value(
                max(0.2, self.sliders["Start Frequency"].get_value() - 0.2 - frnd(0.6))
            )
            self.sliders["Slide"].set_value(-0.15 - frnd(0.2))
            if rnd(2) == 0:
                self.sliders["Start Frequency"].set_value(0.3 + frnd(0.6))
                self.sliders["Min Frequency"].set_value(frnd(0.1))
                self.sliders["Slide"].set_value(-0.35 - frnd(0.3))
            if rnd(1):
                self.sliders["Square Duty"].set_value(frnd(0.5))
                self.sliders["Duty Sweep"].set_value(frnd(0.2))
            else:
                self.sliders["Square Duty"].set_value(0.4 + frnd(0.4))
            self.sliders["Sustain Time"].set_value(0.1 + frnd(0.2))
            self.sliders["Decay Time"].set_value(frnd(0.4))
            if rnd(1):
                self.sliders["Sustain Punch"].set_value(frnd(0.3))
            if rnd(2) == 0:
                self.sliders["Phaser Offset"].set_value(frnd(0.2))
                self.sliders["Phaser Sweep"].set_value(-frnd(0.2))
            self.sliders["HPF Cutoff"].set_value(frnd(0.3))

        elif label == "Explosion":
            _zero(WAVE_NOISE)
            if rnd(1):
                self.sliders["Start Frequency"].set_value(0.1 + frnd(0.4))
                self.sliders["Slide"].set_value(-0.1 - frnd(0.2))
            else:
                self.sliders["Start Frequency"].set_value(0.2 + frnd(0.7))
                self.sliders["Slide"].set_value(-0.2 - frnd(0.2))
            self.sliders["Start Frequency"].set_value(
                self.sliders["Start Frequency"].get_value() ** 2
            )
            if rnd(4) == 0:
                self.sliders["Slide"].set_value(0.0)
            self.sliders["Sustain Time"].set_value(0.1 + frnd(0.3))
            self.sliders["Decay Time"].set_value(0.4 + frnd(0.5))
            self.sliders["Sustain Punch"].set_value(0.6 + frnd(0.3))
            if rnd(1):
                self.sliders["Phaser Offset"].set_value(-0.3 + frnd(0.9))
                self.sliders["Phaser Sweep"].set_value(-frnd(0.3))
            if rnd(1):
                self.sliders["Vibrato Depth"].set_value(frnd(0.7))
                self.sliders["Vibrato Speed"].set_value(frnd(0.6))
            if rnd(2) == 0:
                self.sliders["Delta Slide"].set_value(-0.3 + frnd(0.9))
                self.sliders["Decay Time"].set_value(
                    self.sliders["Decay Time"].get_value() + frnd(0.3)
                )

        elif label == "Powerup":
            _zero(WAVE_SQUARE if rnd(1) == 0 else WAVE_SINE)
            if rnd(1):
                self.sliders["Slide"].set_value(0.1 + frnd(0.4))
            else:
                self.sliders["Start Frequency"].set_value(0.2 + frnd(0.3))
                self.sliders["Min Frequency"].set_value(0.6 + frnd(0.3))
                self.sliders["Slide"].set_value(0.2 + frnd(0.3))
            self.sliders["Start Frequency"].set_value(0.2 + frnd(0.4))
            self.sliders["Sustain Time"].set_value(0.1 + frnd(0.4))
            self.sliders["Decay Time"].set_value(0.1 + frnd(0.4))
            self.sliders["Square Duty"].set_value(frnd(0.6))
            if rnd(1):
                self.sliders["Vibrato Depth"].set_value(frnd(0.7))
                self.sliders["Vibrato Speed"].set_value(frnd(0.6))
            if rnd(2) == 0:
                self.sliders["Sustain Punch"].set_value(frnd(0.4))

        elif label == "Hit / Hurt":
            wave = rnd(2)  # square, saw, or noise
            _zero(wave)
            if wave == WAVE_SQUARE:
                self.sliders["Square Duty"].set_value(frnd(0.6))
            self.sliders["Start Frequency"].set_value(0.2 + frnd(0.6))
            self.sliders["Slide"].set_value(-0.3 - frnd(0.4))
            self.sliders["Sustain Time"].set_value(frnd(0.1))
            self.sliders["Decay Time"].set_value(0.1 + frnd(0.2))
            self.sliders["HPF Cutoff"].set_value(frnd(0.3))

        elif label == "Jump":
            _zero(WAVE_SQUARE)
            self.sliders["Square Duty"].set_value(frnd(0.6))
            self.sliders["Start Frequency"].set_value(0.3 + frnd(0.3))
            self.sliders["Slide"].set_value(0.1 + frnd(0.2)
                                            if rnd(1) else 0.0)
            self.sliders["Sustain Time"].set_value(0.1 + frnd(0.3))
            self.sliders["Decay Time"].set_value(0.1 + frnd(0.2))
            if rnd(1):
                self.sliders["HPF Cutoff"].set_value(frnd(0.3))
            if rnd(1):
                self.sliders["LPF Cutoff"].set_value(1.0 - frnd(0.6))

        elif label == "Blip / Select":
            wave = rnd(1)  # square or sine
            _zero(wave)
            if wave == WAVE_SQUARE:
                self.sliders["Square Duty"].set_value(frnd(0.6))
            self.sliders["Start Frequency"].set_value(0.2 + frnd(0.4))
            self.sliders["Sustain Time"].set_value(0.1 + frnd(0.1))
            self.sliders["Decay Time"].set_value(frnd(0.2))
            self.sliders["HPF Cutoff"].set_value(0.1)

        elif label == "Mutate":
            # Slight mutation of current params — matches jsfxr mutate()
            for name, s in self.sliders.items():
                if random.random() < 0.25:
                    delta = random.uniform(-0.05, 0.05) * (s.max_val - s.min_val)
                    s.set_value(s.get_value() + delta)

        else:  # "Randomize" — full random, deliberately chaotic
            wave = rnd(3)
            self.wave_btn_group.button(wave).setChecked(True)
            for name, slider in self.sliders.items():
                val = random.uniform(slider.min_val, slider.max_val)
                if slider.min_val < 0 and rnd(2) == 0:
                    val = 0.0
                slider.set_value(val)

    # ── State I/O ─────────────────────────────────────────────

    def get_params(self) -> dict:
        """Return current parameters as a plain dict (for audio backend)."""
        params = {"Waveform": self.wave_btn_group.checkedId()}
        for name, slider in self.sliders.items():
            params[name] = slider.get_value()
        return params

    def load_params(self, params: dict):
        """Restore UI from a params dict (e.g. saved project state)."""
        wf = params.get("Waveform", 0)
        btn = self.wave_btn_group.button(wf)
        if btn:
            btn.setChecked(True)
        for name, slider in self.sliders.items():
            if name in params:
                slider.set_value(params[name])

    # ── Button handlers ───────────────────────────────────────

    def _on_play(self):
        self.play_requested.emit(self.get_params())

    def _on_export(self):
        self.export_requested.emit(self.get_params())


# -- Standalone test -----------------------------------------------------------

# ---------------------------------------------------------------------------
# Audio engine
# ---------------------------------------------------------------------------

SAMPLE_RATE = 44100
MAX_SAMPLES = SAMPLE_RATE * 4
WAVE_SQUARE, WAVE_SAW, WAVE_SINE, WAVE_NOISE = 0, 1, 2, 3


def _freq_to_period(f):
    f = max(f, 0.001)
    return SAMPLE_RATE / (10.0 + 10000.0 * f * f)


def synthesize(params):
    from scipy.signal import butter, lfilter

    w       = int(params.get("Waveform", 0))
    attack  = float(params.get("Attack Time",     0.0))
    sustain = float(params.get("Sustain Time",    0.3))
    punch   = float(params.get("Sustain Punch",   0.0))
    decay   = float(params.get("Decay Time",      0.4))
    sf      = float(params.get("Start Frequency", 0.3))
    mf      = float(params.get("Min Frequency",   0.0))
    slide   = float(params.get("Slide",           0.0))
    dslide  = float(params.get("Delta Slide",     0.0))
    vdepth  = float(params.get("Vibrato Depth",   0.0))
    vspeed  = float(params.get("Vibrato Speed",   0.0))
    lpfc    = float(params.get("LPF Cutoff",      1.0))
    lpfres  = float(params.get("LPF Resonance",   0.0))
    hpfc    = float(params.get("HPF Cutoff",      0.0))
    duty    = float(params.get("Square Duty",     0.5))
    dsweep  = float(params.get("Duty Sweep",      0.0))

    # Envelope lengths in samples
    env_a = int(attack  ** 2 * 100000)
    env_s = int(sustain ** 2 * 100000)
    env_d = int(decay   ** 2 * 100000)
    total = min(max(env_a + env_s + env_d, 1), MAX_SAMPLES)
    t = np.arange(total, dtype=np.float64)

    # Instantaneous frequency with slide
    start_hz = max(10.0 + 10000.0 * sf * sf, 1.0)
    end_hz   = max(10.0 + 10000.0 * mf * mf, 1.0)
    # slide: negative slide = pitch down, positive = pitch up
    slide_factor = 1.0 - slide ** 3 * 0.01
    hz = np.clip(start_hz * (slide_factor ** t), end_hz, 20000.0)

    # Vibrato
    if vdepth > 0 and vspeed > 0:
        vib_hz = vspeed ** 2 * 0.01 * SAMPLE_RATE / (2 * np.pi)
        hz *= 1.0 + vdepth * 0.5 * np.sin(2 * np.pi * vib_hz / SAMPLE_RATE * t)

    # Phase accumulation
    phase = np.cumsum(hz / SAMPLE_RATE)

    # Waveform generation
    if w == WAVE_SQUARE:
        duty_arr = np.clip(duty + dsweep * 0.00005 * t, 0.0, 1.0)
        frac = phase % 1.0
        out = np.where(frac < duty_arr, 1.0, -1.0).astype(np.float32)
    elif w == WAVE_SAW:
        out = (1.0 - (phase % 1.0) * 2.0).astype(np.float32)
    elif w == WAVE_SINE:
        out = np.sin(2.0 * np.pi * phase).astype(np.float32)
    else:  # NOISE
        out = np.random.uniform(-1.0, 1.0, total).astype(np.float32)

    # Low-pass filter
    if lpfc < 0.99:
        cutoff = max(min(lpfc ** 3 * 0.5 * SAMPLE_RATE, SAMPLE_RATE * 0.49), 20.0)
        resonance = 1.0 + lpfres * 2.0
        b, a = butter(2, cutoff / (SAMPLE_RATE / 2), btype='low')
        out = lfilter(b, a, out).astype(np.float32)

    # High-pass filter
    if hpfc > 0.01:
        cutoff = max(min(hpfc ** 2 * 0.5 * SAMPLE_RATE, SAMPLE_RATE * 0.49), 20.0)
        b, a = butter(2, cutoff / (SAMPLE_RATE / 2), btype='high')
        out = lfilter(b, a, out).astype(np.float32)

    # Envelope
    env = np.empty(total, dtype=np.float32)
    if env_a > 0:
        env[:env_a] = np.linspace(0.0, 1.0, min(env_a, total))
    s0, s1 = env_a, min(env_a + env_s, total)
    if s0 < s1:
        env[s0:s1] = 1.0 + punch
    d0, d1 = s1, total
    if d0 < d1:
        env[d0:d1] = np.linspace(1.0 + punch, 0.0, d1 - d0)

    out *= env * 0.5

    peak = np.max(np.abs(out))
    if peak > 0:
        out *= 0.9 / peak
    return out


def _to_pcm16(samples):
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def _make_wav_bytes(params):
    pcm = _to_pcm16(synthesize(params))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


class SfxPlayer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fmt = QAudioFormat()
        self._fmt.setSampleRate(SAMPLE_RATE)
        self._fmt.setChannelCount(1)
        self._fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._sink = self._buf = None

    def play(self, params):
        self._stop()
        ba = QByteArray(_to_pcm16(synthesize(params)))
        self._buf = QBuffer(self)
        self._buf.setData(ba)
        self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = QAudioSink(self._fmt, self)
        self._sink.start(self._buf)

    def export(self, params):
        path, _ = QFileDialog.getSaveFileName(None, "Export WAV", "sound.wav", "WAV (*.wav)")
        if path:
            with open(path, "wb") as f:
                f.write(_make_wav_bytes(params))

    def _stop(self):
        if self._sink: self._sink.stop(); self._sink = None
        if self._buf:  self._buf.close();  self._buf = None




# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = QMainWindow()
    win.setWindowTitle("SFX Generator")
    win.resize(860, 620)

    tabs = QTabWidget()
    tabs.setStyleSheet(f"""
        QTabWidget::pane {{ border: none; background: {DARK}; }}
        QTabBar::tab {{
            background: {PANEL}; color: {DIM};
            padding: 6px 16px; border: none;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
        QTabBar::tab:hover {{ color: {TEXT}; }}
    """)

    sfx_tab = TabSfx()
    player  = SfxPlayer(parent=app)
    sfx_tab.play_requested.connect(player.play)
    sfx_tab.export_requested.connect(player.export)

    tabs.addTab(sfx_tab, "SFX Generator")
    win.setCentralWidget(tabs)
    win.show()
    sys.exit(app.exec())
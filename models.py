"""
Vita Adventure Creator — Data Models
All project state lives here. Nothing Qt, nothing Lua — pure data.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
import json
import uuid


# ─────────────────────────────────────────────────────────────
#  REGISTRY ENTRIES  (registered assets, reusable project-wide)
# ─────────────────────────────────────────────────────────────

@dataclass
class RegisteredImage:
    """A background, foreground, or UI image registered to the project."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    path: Optional[str] = None
    category: str = "background"        # background | foreground | character | ui | other

    def to_dict(self):
        return {"id": self.id, "name": self.name, "path": self.path, "category": self.category}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class RegisteredAudio:
    """A music track or sound effect registered to the project."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    path: Optional[str] = None
    audio_type: str = "music"           # music | sfx

    def to_dict(self):
        return {"id": self.id, "name": self.name, "path": self.path, "audio_type": self.audio_type}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class RegisteredFont:
    """A font file registered to the project."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    path: Optional[str] = None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class RegisteredTileset:
    """A tileset spritesheet registered to the project."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    path: Optional[str] = None
    tile_size: int = 32          # always 32 for now
    columns: int = 0             # derived at registration time: image_width // tile_size
    rows: int = 0                # derived at registration time: image_height // tile_size

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "tile_size": self.tile_size,
            "columns": self.columns,
            "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", ""),
            path=d.get("path"),
            tile_size=d.get("tile_size", 32),
            columns=d.get("columns", 0),
            rows=d.get("rows", 0),
        )


@dataclass
class AnimationExport:
    """An exported .ani animation file (spritesheet + metadata)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    spritesheet_path: str = ""
    frame_count: int = 1
    frame_width: int = 64
    frame_height: int = 64
    sheet_width: int = 64
    sheet_height: int = 64
    fps: int = 12

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "spritesheet_path": self.spritesheet_path,
            "frame_count": self.frame_count,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "sheet_width": self.sheet_width,
            "sheet_height": self.sheet_height,
            "fps": self.fps,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class TransitionExport:
    """An exported .trans transition file (spritesheet + metadata)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    spritesheet_path: str = ""
    frame_count: int = 1
    sheet_width: int = 960
    sheet_height: int = 544
    fps: int = 12

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "spritesheet_path": self.spritesheet_path,
            "frame_count": self.frame_count,
            "sheet_width": self.sheet_width,
            "sheet_height": self.sheet_height,
            "fps": self.fps,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


# ─────────────────────────────────────────────────────────────
#  OBJECT SYSTEM
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
#  OBJECT SYSTEM
# ─────────────────────────────────────────────────────────────

@dataclass
class SpriteFrame:
    image_id: Optional[str] = None
    duration_frames: int = 6

    def to_dict(self):
        return {"image_id": self.image_id, "duration_frames": self.duration_frames}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class BehaviorAction:
    action_type: str = "none"

    # ── Scene flow ───────────────────────────────────────────
    target_scene: int = 0              # go_to_scene, if branches

    # ── Timing ───────────────────────────────────────────────
    duration: float = 1.0              # wait seconds, fade duration, slide duration, etc.

    # ── Screen effects ───────────────────────────────────────
    color: str = "#000000"             # fade_to_color, flash color
    intensity: float = 5.0             # shake intensity

    # ── Variables / flags ────────────────────────────────────
    var_name: str = ""
    var_value: str = ""                # set_variable value (string rep)
    var_operator: str = "set"          # set | add | subtract | multiply | divide
    var_compare: str = "=="            # == | != | > | < | >= | <=
    bool_name: str = ""
    bool_value: bool = True            # set_flag value
    bool_expected: bool = True         # if_flag expected state

    # ── Object targeting ─────────────────────────────────────
    object_def_id: str = ""            # which object definition
    instance_id: str = ""             # specific placed instance (empty = all of type)

    # ── Transform ────────────────────────────────────────────
    target_x: int = 0
    target_y: int = 0
    offset_x: int = 0
    offset_y: int = 0
    target_scale: float = 1.0
    target_rotation: float = 0.0
    target_opacity: float = 1.0
    spin_speed: float = 90.0           # degrees per second

    # ── Animation ────────────────────────────────────────────
    frame_index: int = 0
    anim_fps: int = 6

    # ── Audio ────────────────────────────────────────────────
    audio_id: str = ""
    audio_loop: bool = True
    volume: int = 100

    # ── Images ───────────────────────────────────────────────
    image_id: str = ""

    # ── Dialogue ─────────────────────────────────────────────
    speaker_name: str = ""
    speaker_color: str = "#FFFFFF"
    dialogue_text: str = ""
    dialogue_line_index: int = 0       # which line slot (0-3)

    # ── Choice menu ──────────────────────────────────────────
    choice_index: int = 0
    choice_text: str = ""
    choice_goto: int = 0

    # ── Inventory ────────────────────────────────────────────
    item_name: str = ""

    # ── Branching (if actions) ───────────────────────────────
    # These store serialized sub-action lists as JSON strings for simplicity
    true_actions:  list = field(default_factory=list)   # list of action dicts
    false_actions: list = field(default_factory=list)

    # ── Debug ────────────────────────────────────────────────
    log_message: str = ""

    # ── Movement prebuilts ───────────────────────────────────
    movement_speed: float = 1.0
    movement_style: str = "instant"   # "instant" | "slide"
    collision_layer_id: str = ""
    player_width:       int = 32
    player_height:      int = 48
    bullet_direction:   str = "right"       # right | left | up | down
    bullet_speed:       int = 6             # px per frame
    two_way_axis:       str = "horizontal"  # horizontal | vertical

    # ── Conditional input actions ────────────────────────────
    button: str = ""                   # cross, circle, square, triangle, dpad_up, etc.
    sub_actions: list = field(default_factory=list)  # list of BehaviorAction (nested)

    # ── Camera actions ───────────────────────────────────────
    camera_target_x: int = 0
    camera_target_y: int = 0
    camera_offset_x: int = 0
    camera_offset_y: int = 0
    camera_duration: float = 0.0             # 0 = instant
    camera_easing: str = "linear"            # linear | ease_in | ease_out | ease_in_out
    camera_follow_target_def_id: str = ""    # object definition to follow
    camera_follow_offset_x: int = 0
    camera_follow_offset_y: int = 0
    shake_intensity: float = 5.0             # screen shake strength
    shake_duration: float = 0.5              # screen shake seconds

    # ── Animation object actions ─────────────────────────────
    ani_target_frame: int = 0                # ani_set_frame target
    ani_fps: int = 12                        # ani_set_speed fps

    # ── Layer actions ────────────────────────────────────────
    layer_name: str = ""                     # target layer by name (layer_show, layer_hide, layer_set_image)

    def to_dict(self):
        d = self.__dict__.copy()
        # Serialize all nested action lists recursively
        for key in ("sub_actions", "true_actions", "false_actions"):
            lst = getattr(self, key, [])
            if lst:
                d[key] = [a.to_dict() if isinstance(a, BehaviorAction) else a for a in lst]
            else:
                d[key] = []
        return d

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        for k, v in d.items():
            if k in ("sub_actions", "true_actions", "false_actions") and isinstance(v, list):
                setattr(obj, k, [BehaviorAction.from_dict(sa) if isinstance(sa, dict) else sa for sa in v])
            elif hasattr(obj, k):
                setattr(obj, k, v)
        return obj


@dataclass
class Behavior:
    trigger: str = "on_interact"
    # Valid triggers:
    #   on_interact      — player presses interact button near this object
    #   on_input         — any mapped input action fires (uses input_action_name)
    #   on_frame         — runs every frame (uses frame_count for interval)
    #   on_button_pressed  — fires once when button is first pressed (uses button)
    #   on_button_held     — fires every frame while button is held (uses button)
    #   on_button_released — fires once when button is released (uses button)
    #   on_scene_start   — fires once when the scene loads
    #   on_scene_end     — fires once when the scene ends
    #   on_timer         — fires on a repeating frame interval (uses frame_count)
    #   on_create        — fires once when the object is created/spawned
    #   on_destroy       — fires once when the object is destroyed
    #   on_enter         — fires once when a zone target first overlaps this zone
    #   on_exit          — fires once when a zone target stops overlapping this zone
    #   on_overlap       — fires every frame while a zone target overlaps this zone
    #   on_interact_zone — player presses interact button while inside this zone
    frame_count: int = 60
    bool_var: str = ""
    input_action_name: str = ""
    button: str = ""               # used by on_button_pressed / held / released
    actions: list[BehaviorAction] = field(default_factory=list)

    def to_dict(self):
        return {
            "trigger": self.trigger,
            "frame_count": self.frame_count,
            "bool_var": self.bool_var,
            "input_action_name": self.input_action_name,
            "button": self.button,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d):
        b = cls()
        b.trigger = d.get("trigger", "on_interact")
        b.frame_count = d.get("frame_count", 60)
        b.bool_var = d.get("bool_var", "")
        b.input_action_name = d.get("input_action_name", "")
        b.button = d.get("button", "")
        b.actions = [BehaviorAction.from_dict(a) for a in d.get("actions", [])]
        return b


@dataclass
class ObjectDefinition:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Object"
    frames: list[SpriteFrame] = field(default_factory=list)
    fps: int = 6
    behaviors: list[Behavior] = field(default_factory=list)
    width: int = 64
    height: int = 64
    visible_default: bool = True
    # VNCharacter behavior config — only meaningful when behavior_type == "VNCharacter"
    behavior_type: str = "default"      # default | VNCharacter | GUI_Label | GUI_Button | GUI_Panel | Camera
    vn_display_name: str = ""           # shown in the VN dialogue name box
    vn_name_color: str = "#FFFFFF"      # hex color for the name tag
    # GUI config — only meaningful when behavior_type starts with "GUI_"
    gui_text: str = ""                  # display text for Label and Button
    gui_text_color: str = "#FFFFFF"     # text color
    gui_font_id: str = ""              # registered font ID (empty = default font)
    gui_text_align: str = "left"        # text alignment: left | center | right (Label + Button)
    gui_font_size: int = 16             # font size in pixels for Label and Button
    gui_bg_color: str = "#000000"      # background fill for Panel and Button
    gui_bg_opacity: int = 150          # background alpha (0-255) for Panel and Button
    gui_width: int = 200               # rectangle width for Panel and Button
    gui_height: int = 50               # rectangle height for Panel and Button
    gui_highlight_color: str = "#7c6aff"  # focused state color for Button
    gui_image_id: str = ""             # optional background image for Button
    # Camera config — only meaningful when behavior_type == "Camera"
    camera_bounds_enabled: bool = False      # True = use manual bounds, False = auto from background
    camera_bounds_width: int = 960           # manual bounds width (only if enabled)
    camera_bounds_height: int = 544          # manual bounds height (only if enabled)
    camera_follow_lag: float = 0.0           # 0 = instant, higher = smoother (0.0 to 0.95)

    # Animation config — only meaningful when behavior_type == "Animation"
    ani_file_id: str = ""                    # reference to AnimationExport.id
    ani_loop: bool = True                    # loop or play once
    ani_play_on_spawn: bool = True           # start playing when object spawns
    ani_start_paused: bool = False           # start paused at specific frame
    ani_pause_frame: int = 0                 # frame to pause on if ani_start_paused
    ani_fps_override: int = 0                # 0 = use file default

    # Zone config — makes this object act as an Area2D-style trigger region
    is_zone: bool = False                    # True = this object is a trigger zone
    zone_target: str = "player"              # "player" = only player trips it | "any" = any object trips it

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "frames": [f.to_dict() for f in self.frames],
            "fps": self.fps,
            "behaviors": [b.to_dict() for b in self.behaviors],
            "width": self.width,
            "height": self.height,
            "visible_default": self.visible_default,
            "behavior_type": self.behavior_type,
            "vn_display_name": self.vn_display_name,
            "vn_name_color": self.vn_name_color,
            "gui_text": self.gui_text,
            "gui_text_color": self.gui_text_color,
            "gui_font_id": self.gui_font_id,
            "gui_text_align": self.gui_text_align,
            "gui_font_size": self.gui_font_size,
            "gui_bg_color": self.gui_bg_color,
            "gui_bg_opacity": self.gui_bg_opacity,
            "gui_width": self.gui_width,
            "gui_height": self.gui_height,
            "gui_highlight_color": self.gui_highlight_color,
            "gui_image_id": self.gui_image_id,
            "camera_bounds_enabled": self.camera_bounds_enabled,
            "camera_bounds_width": self.camera_bounds_width,
            "camera_bounds_height": self.camera_bounds_height,
            "camera_follow_lag": self.camera_follow_lag,
            "ani_file_id": self.ani_file_id,
            "ani_loop": self.ani_loop,
            "ani_play_on_spawn": self.ani_play_on_spawn,
            "ani_start_paused": self.ani_start_paused,
            "ani_pause_frame": self.ani_pause_frame,
            "ani_fps_override": self.ani_fps_override,
            "is_zone": self.is_zone,
            "zone_target": self.zone_target,
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Object")
        obj.frames = [SpriteFrame.from_dict(f) for f in d.get("frames", [])]
        obj.fps = d.get("fps", 6)
        obj.behaviors = [Behavior.from_dict(b) for b in d.get("behaviors", [])]
        obj.width = d.get("width", 64)
        obj.height = d.get("height", 64)
        obj.visible_default = d.get("visible_default", True)
        obj.behavior_type = d.get("behavior_type", "default")
        obj.vn_display_name = d.get("vn_display_name", "")
        obj.vn_name_color = d.get("vn_name_color", "#FFFFFF")
        obj.gui_text = d.get("gui_text", "")
        obj.gui_text_color = d.get("gui_text_color", "#FFFFFF")
        obj.gui_font_id = d.get("gui_font_id", "")
        obj.gui_text_align = d.get("gui_text_align", "left")
        obj.gui_font_size = d.get("gui_font_size", 16)
        obj.gui_bg_color = d.get("gui_bg_color", "#000000")
        obj.gui_bg_opacity = d.get("gui_bg_opacity", 150)
        obj.gui_width = d.get("gui_width", 200)
        obj.gui_height = d.get("gui_height", 50)
        obj.gui_highlight_color = d.get("gui_highlight_color", "#7c6aff")
        obj.gui_image_id = d.get("gui_image_id", "")
        obj.camera_bounds_enabled = d.get("camera_bounds_enabled", False)
        obj.camera_bounds_width = d.get("camera_bounds_width", 960)
        obj.camera_bounds_height = d.get("camera_bounds_height", 544)
        obj.camera_follow_lag = d.get("camera_follow_lag", 0.0)
        obj.ani_file_id = d.get("ani_file_id", "")
        obj.ani_loop = d.get("ani_loop", True)
        obj.ani_play_on_spawn = d.get("ani_play_on_spawn", True)
        obj.ani_start_paused = d.get("ani_start_paused", False)
        obj.ani_pause_frame = d.get("ani_pause_frame", 0)
        obj.ani_fps_override = d.get("ani_fps_override", 0)
        obj.is_zone = d.get("is_zone", False)
        obj.zone_target = d.get("zone_target", "player")
        return obj


# ─────────────────────────────────────────────────────────────
#  SCENE PLACEMENT  (object instances placed into a scene)
# ─────────────────────────────────────────────────────────────

@dataclass
class PlacedObject:
    instance_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    object_def_id: str = ""
    x: int = 100
    y: int = 100
    scale: float = 1.0
    rotation: float = 0.0               # degrees
    opacity: float = 1.0                # 0.0 – 1.0
    visible: bool = True
    layer_id: str = ""                  # SceneComponent id of a Layer component; "" = world (no layer)
    draw_layer: int = 2                 # draw order when not assigned to a Layer component; 0=back, higher=front
    instance_behaviors: list[Behavior] = field(default_factory=list)

    def to_dict(self):
        return {
            "instance_id": self.instance_id,
            "object_def_id": self.object_def_id,
            "x": self.x,
            "y": self.y,
            "scale": self.scale,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "visible": self.visible,
            "layer_id": self.layer_id,
            "draw_layer": self.draw_layer,
            "instance_behaviors": [b.to_dict() for b in self.instance_behaviors],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.instance_id = d.get("instance_id", obj.instance_id)
        obj.object_def_id = d.get("object_def_id", "")
        obj.x = d.get("x", 100)
        obj.y = d.get("y", 100)
        obj.scale = d.get("scale", 1.0)
        obj.rotation = d.get("rotation", 0.0)
        obj.opacity = d.get("opacity", 1.0)
        obj.visible = d.get("visible", True)
        obj.layer_id = d.get("layer_id", "")
        obj.draw_layer = d.get("draw_layer", 2)
        obj.instance_behaviors = [Behavior.from_dict(b) for b in d.get("instance_behaviors", [])]
        return obj


# ─────────────────────────────────────────────────────────────
#  SCENE COMPONENTS
# ─────────────────────────────────────────────────────────────

# Available component types and their default configs
COMPONENT_TYPES = [
    "Background",
    "Foreground",
    "Layer",
    "TileLayer",
    "CollisionLayer",
    "Music",
    "VNDialogBox",
    "ChoiceMenu",
    "SelectionGroup",
    "HUD",
    "Video",
    "Transition",
]

COMPONENT_DEFAULTS: dict[str, dict] = {
    "Background": {
        "image_id": None,
        "scroll": False,
        "scroll_speed": 1,
        "scroll_direction": "horizontal",
        "parallax": 1.0,  # 0 = fixed, 1 = moves with camera, 0.5 = half speed
    },
    "Foreground": {
        "image_id": None,
    },
    "Layer": {
        "layer_name": "New Layer",
        "layer": 0,                 # 0 = furthest back, higher = closer to camera
        "image_id": None,
        "visible": True,
        "screen_space_locked": False,
        "scroll": False,
        "scroll_speed": 1,
        "scroll_direction": "horizontal",
        "parallax": 1.0,
    },
    "TileLayer": {
        "layer_name": "New Tile Layer",
        "layer": 0,              # unified draw order index (shared with Layer components)
        "tileset_id": None,      # RegisteredTileset.id
        "tile_size": 32,         # grid cell size in pixels
        "map_width": 30,         # width in tiles
        "map_height": 17,        # height in tiles
        "tiles": [],             # flat int array, len = map_width * map_height, -1 = empty
        "visible": True,
        "scroll": False,
        "scroll_speed": 1,
        "scroll_direction": "horizontal",
        "parallax": 1.0,
    },
    "CollisionLayer": {
        "layer_name": "New Collision Layer",
        "layer": 0,              # unified draw order index
        "tile_size": 32,         # collision grid cell size in pixels (independent of any tile layer)
        "map_width": 30,
        "map_height": 17,
        "tiles": [],             # flat int array, len = map_width * map_height, 0 = empty, 1 = solid
    },
    "Music": {
        "action": "keep",       # keep | change | stop
        "audio_id": None,
    },
    "VNDialogBox": {
        "speaker_name": "",
        "lines": ["", "", "", ""],
    },
    "ChoiceMenu": {
        "choices": [
            {"text": "", "button": "cross",    "goto": 0},
            {"text": "", "button": "square",   "goto": 0},
            {"text": "", "button": "circle",   "goto": 0},
            {"text": "", "button": "triangle", "goto": 0},
        ],
    },
    "SelectionGroup": {
        "selectable_ids": [],              # ordered list of placed instance IDs
        "cycle_buttons": "updown",         # updown | leftright
        "confirm_button": "cross",         # cross | circle
    },
    "HUD": {},
    "Video": {
        "video_id": None,
    },
    "Transition": {
        "trans_file_id": "",
        "trans_fps_override": 0,
    },
}



@dataclass
class SceneComponent:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    component_type: str = "Background"
    config: dict = field(default_factory=dict)

    def __post_init__(self):
        # Fill in any missing keys from defaults so components are always complete
        defaults = COMPONENT_DEFAULTS.get(self.component_type, {})
        for k, v in defaults.items():
            if k not in self.config:
                import copy
                self.config[k] = copy.deepcopy(v)

    def to_dict(self):
        return {
            "id": self.id,
            "component_type": self.component_type,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls.__new__(cls)
        obj.id = d.get("id", str(uuid.uuid4())[:8])
        obj.component_type = d.get("component_type", "Background")
        obj.config = d.get("config", {})
        # Fill any missing keys from defaults
        defaults = COMPONENT_DEFAULTS.get(obj.component_type, {})
        import copy
        for k, v in defaults.items():
            if k not in obj.config:
                obj.config[k] = copy.deepcopy(v)
        return obj


def make_component(component_type: str) -> SceneComponent:
    """Create a new SceneComponent with default config for the given type."""
    import copy
    return SceneComponent(
        component_type=component_type,
        config=copy.deepcopy(COMPONENT_DEFAULTS.get(component_type, {})),
    )


# ─────────────────────────────────────────────────────────────
#  MAP DATA  (3D scene map, owned by Scene)
# ─────────────────────────────────────────────────────────────

@dataclass
class MapData:
    width:        int   = 16
    height:       int   = 16
    cells:        list  = field(default_factory=lambda: [0] * (16 * 16))
    spawn_x:      int   = 1
    spawn_y:      int   = 1
    spawn_angle:  int   = 0
    tile_size:    int   = 64
    wall_height:  int   = 64
    floor_color:  str   = "#808080"
    sky_color:    str   = "#404040"
    wall_color:   str   = "#0000ff"
    shading:      bool  = False
    floor_on:     bool  = False
    sky_on:       bool  = False

    def get(self, col: int, row: int) -> int:
        if 0 <= col < self.width and 0 <= row < self.height:
            return self.cells[row * self.width + col]
        return 0

    def set(self, col: int, row: int, value: int):
        if 0 <= col < self.width and 0 <= row < self.height:
            self.cells[row * self.width + col] = value

    def resize(self, new_w: int, new_h: int):
        new_cells = [0] * (new_w * new_h)
        for r in range(min(self.height, new_h)):
            for c in range(min(self.width, new_w)):
                new_cells[r * new_w + c] = self.get(c, r)
        self.width  = new_w
        self.height = new_h
        self.cells  = new_cells
        self.spawn_x = min(self.spawn_x, new_w - 1)
        self.spawn_y = min(self.spawn_y, new_h - 1)

    def flood_fill(self, col: int, row: int, new_val: int):
        target = self.get(col, row)
        if target == new_val:
            return
        stack = [(col, row)]
        while stack:
            c, r = stack.pop()
            if not (0 <= c < self.width and 0 <= r < self.height):
                continue
            if self.get(c, r) != target:
                continue
            self.set(c, r, new_val)
            stack += [(c+1,r),(c-1,r),(c,r+1),(c,r-1)]

    def to_dict(self):
        return {
            "width":       self.width,
            "height":      self.height,
            "cells":       self.cells,
            "spawn_x":     self.spawn_x,
            "spawn_y":     self.spawn_y,
            "spawn_angle": self.spawn_angle,
            "tile_size":   self.tile_size,
            "wall_height": self.wall_height,
            "floor_color": self.floor_color,
            "sky_color":   self.sky_color,
            "wall_color":  self.wall_color,
            "shading":     self.shading,
            "floor_on":    self.floor_on,
            "sky_on":      self.sky_on,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MapData":
        m = cls()
        m.width       = d.get("width",       16)
        m.height      = d.get("height",      16)
        m.tile_size   = d.get("tile_size",   64)
        m.cells       = d.get("cells",       [0] * (m.width * m.height))
        m.spawn_x     = d.get("spawn_x",     1)
        m.spawn_y     = d.get("spawn_y",     1)
        m.spawn_angle = d.get("spawn_angle", 0)
        m.wall_height = d.get("wall_height", 64)
        m.floor_color = d.get("floor_color", "#808080")
        m.sky_color   = d.get("sky_color",   "#404040")
        m.wall_color  = d.get("wall_color",  "#0000ff")
        m.shading     = d.get("shading",     False)
        m.floor_on    = d.get("floor_on",    False)
        m.sky_on      = d.get("sky_on",      False)
        return m


# ─────────────────────────────────────────────────────────────
#  SCENE TEMPLATES  (used only at creation time)
# ─────────────────────────────────────────────────────────────

def _make_scene_components(template: str) -> list[SceneComponent]:
    """Return a pre-populated component list for the given template name."""
    import copy
    if template == "BLANK":
        return []
    elif template == "VN_SCENE":
        return [
            make_component("Background"),
            make_component("Music"),
            make_component("VNDialogBox"),
        ]
    elif template == "CHOICE_SCENE":
        return [
            make_component("Background"),
            make_component("Music"),
            make_component("VNDialogBox"),
            make_component("ChoiceMenu"),
        ]
    elif template == "START_SCREEN":
        return [
            make_component("Background"),
            make_component("Music"),
        ]
    elif template == "END_SCENE":
        return [
            make_component("Background"),
            make_component("Music"),
        ]
    elif template == "CUTSCENE":
        return [
            make_component("Video"),
        ]
    elif template == "3D_SCENE":
        return []
    else:
        return []


SCENE_TEMPLATES = [
    ("Blank",        "BLANK"),
    ("VN Scene",     "VN_SCENE"),
    ("Choice Scene", "CHOICE_SCENE"),
    ("Start Screen", "START_SCREEN"),
    ("End Scene",    "END_SCENE"),
    ("Cutscene",     "CUTSCENE"),
    ("3D Scene",     "3D_SCENE"),
]


# ─────────────────────────────────────────────────────────────
#  SCENE
# ─────────────────────────────────────────────────────────────

@dataclass
class Scene:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    role: str = ""                      # "" | "start" | "end"
    components: list[SceneComponent] = field(default_factory=list)
    placed_objects: list[PlacedObject] = field(default_factory=list)
    behaviors: list[Behavior] = field(default_factory=list)  # scene-level behaviors

    # ── 3D ───────────────────────────────────────────────────
    scene_type:     str      = "2d"     # "2d" | "3d"
    movement_mode:  str      = "free"   # "free" | "grid" | "none"
    move_speed:     int      = 5
    turn_speed:     int      = 50
    map_data:       MapData  = field(default_factory=MapData)

    # ── Helpers ──────────────────────────────────────────────

    def has_component(self, component_type: str) -> bool:
        return any(c.component_type == component_type for c in self.components)

    def get_component(self, component_type: str) -> Optional[SceneComponent]:
        return next((c for c in self.components if c.component_type == component_type), None)

    def get_summary(self) -> str:
        if self.role == "start":
            role_tag = "[START] "
        elif self.role == "end":
            role_tag = "[END] "
        else:
            role_tag = ""
        label = self.name or ""
        if label:
            preview = label[:28] + "…" if len(label) > 28 else label
            return f"{role_tag}{preview}"
        comp_names = ", ".join(c.component_type for c in self.components) if self.components else "Empty"
        return f"{role_tag}{comp_names}"

    # ── Serialization ────────────────────────────────────────

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "components": [c.to_dict() for c in self.components],
            "placed_objects": [o.to_dict() for o in self.placed_objects],
            "behaviors": [b.to_dict() for b in self.behaviors],
            "scene_type":    self.scene_type,
            "movement_mode": self.movement_mode,
            "move_speed":    self.move_speed,
            "turn_speed":    self.turn_speed,
            "map_data":      self.map_data.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        s = cls()
        s.id = d.get("id", s.id)
        s.name = d.get("name", "")
        s.role = d.get("role", "")
        s.components = [SceneComponent.from_dict(c) for c in d.get("components", [])]
        s.placed_objects = [PlacedObject.from_dict(o) for o in d.get("placed_objects", [])]
        s.behaviors = [Behavior.from_dict(b) for b in d.get("behaviors", [])]
        s.scene_type    = d.get("scene_type",    "2d")
        s.movement_mode = d.get("movement_mode", "free")
        s.move_speed    = d.get("move_speed",    5)
        s.turn_speed    = d.get("turn_speed",    50)
        s.map_data      = MapData.from_dict(d["map_data"]) if "map_data" in d else MapData()
        return s

    @classmethod
    def from_template(cls, template: str, name: str = "") -> "Scene":
        s = cls()
        s.name = name
        s.components = _make_scene_components(template)
        if template == "START_SCREEN":
            s.role = "start"
        elif template == "END_SCENE":
            s.role = "end"
        elif template == "3D_SCENE":
            s.scene_type = "3d"
            s.map_data   = MapData()
        return s


# ─────────────────────────────────────────────────────────────
#  GAME DATA
# ─────────────────────────────────────────────────────────────

@dataclass
class GameVariable:
    name: str = "my_var"
    var_type: str = "number"
    default_value: Any = 0

    def to_dict(self):
        return {"name": self.name, "var_type": self.var_type, "default_value": self.default_value}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class InventoryItem:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Item"
    description: str = ""
    icon_id: Optional[str] = None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "icon_id": self.icon_id}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class InputAction:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "action"
    button: str = "cross"
    event: str = "pressed"
    hold_duration: float = 2.0  # seconds; only used when event == "hold_for"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "button": self.button,
            "event": self.event,
            "hold_duration": self.hold_duration,
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", obj.name)
        obj.button = d.get("button", obj.button)
        obj.event = d.get("event", obj.event)
        obj.hold_duration = float(d.get("hold_duration", 2.0))
        return obj


@dataclass
class GameSignal:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "my_signal"

    def to_dict(self):
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", obj.name)
        return obj


@dataclass
class GameData:
    variables: list[GameVariable] = field(default_factory=list)
    inventory_items: list[InventoryItem] = field(default_factory=list)
    input_actions: list[InputAction] = field(default_factory=list)
    signals: list[GameSignal] = field(default_factory=list)
    inventory_enabled: bool = False
    inventory_max: int = 20
    save_enabled: bool = True
    volume_default: int = 100

    def to_dict(self):
        return {
            "variables": [v.to_dict() for v in self.variables],
            "inventory_items": [i.to_dict() for i in self.inventory_items],
            "input_actions": [a.to_dict() for a in self.input_actions],
            "signals": [s.to_dict() for s in self.signals],
            "inventory_enabled": self.inventory_enabled,
            "inventory_max": self.inventory_max,
            "save_enabled": self.save_enabled,
            "volume_default": self.volume_default,
        }

    @classmethod
    def from_dict(cls, d):
        gd = cls()
        gd.variables = [GameVariable.from_dict(v) for v in d.get("variables", [])]
        gd.inventory_items = [InventoryItem.from_dict(i) for i in d.get("inventory_items", [])]
        gd.input_actions = [InputAction.from_dict(a) for a in d.get("input_actions", [])]
        gd.signals = [GameSignal.from_dict(s) for s in d.get("signals", [])]
        gd.inventory_enabled = d.get("inventory_enabled", False)
        gd.inventory_max = d.get("inventory_max", 20)
        gd.save_enabled = d.get("save_enabled", True)
        gd.volume_default = d.get("volume_default", 100)
        return gd


# ─────────────────────────────────────────────────────────────
#  PROJECT
# ─────────────────────────────────────────────────────────────

@dataclass
class Project:
    title: str = "Untitled Game"
    title_id: str = "ADVG00001"
    author: str = ""
    version: str = "1.0"
    project_folder: Optional[str] = None

    images: list[RegisteredImage] = field(default_factory=list)
    audio: list[RegisteredAudio] = field(default_factory=list)
    fonts: list[RegisteredFont] = field(default_factory=list)
    tilesets: list[RegisteredTileset] = field(default_factory=list)

    object_defs: list[ObjectDefinition] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=lambda: [Scene()])
    game_data: GameData = field(default_factory=GameData)
    animation_exports: list[AnimationExport] = field(default_factory=list)
    transition_exports: list[TransitionExport] = field(default_factory=list)

    # ── Lookup helpers ──────────────────────────────────────

    def get_image(self, image_id: str) -> Optional[RegisteredImage]:
        return next((i for i in self.images if i.id == image_id), None)

    def get_audio(self, audio_id: str) -> Optional[RegisteredAudio]:
        return next((a for a in self.audio if a.id == audio_id), None)

    def get_font(self, font_id: str) -> Optional[RegisteredFont]:
        return next((f for f in self.fonts if f.id == font_id), None)

    def get_object_def(self, obj_id: str) -> Optional[ObjectDefinition]:
        return next((o for o in self.object_defs if o.id == obj_id), None)

    def get_tileset(self, tileset_id: str) -> Optional[RegisteredTileset]:
        return next((t for t in self.tilesets if t.id == tileset_id), None)

    def get_animation_export(self, ani_id: str) -> Optional[AnimationExport]:
        return next((a for a in self.animation_exports if a.id == ani_id), None)

    def get_transition_export(self, trans_id: str) -> Optional[TransitionExport]:
        return next((t for t in self.transition_exports if t.id == trans_id), None)

    # ── Serialization ───────────────────────────────────────
    def to_dict(self):
        return {
            "format_version": 2,
            "title": self.title,
            "title_id": self.title_id,
            "author": self.author,
            "version": self.version,
            "project_folder": self.project_folder,
            "images": [i.to_dict() for i in self.images],
            "audio": [a.to_dict() for a in self.audio],
            "fonts": [f.to_dict() for f in self.fonts],
            "tilesets": [t.to_dict() for t in self.tilesets],
            "object_defs": [o.to_dict() for o in self.object_defs],
            "scenes": [s.to_dict() for s in self.scenes],
            "game_data": self.game_data.to_dict(),
            "animation_exports": [a.to_dict() for a in self.animation_exports],
            "transition_exports": [t.to_dict() for t in self.transition_exports],
        }

    def save(self, path: str | Path):
        path = Path(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = cls()
        p.title = d.get("title", "Untitled Game")
        p.title_id = d.get("title_id", "ADVG00001")
        p.author = d.get("author", "")
        p.version = d.get("version", "1.0")
        p.project_folder = d.get("project_folder")
        p.images = [RegisteredImage.from_dict(i) for i in d.get("images", [])]
        p.audio = [RegisteredAudio.from_dict(a) for a in d.get("audio", [])]
        p.fonts = [RegisteredFont.from_dict(f) for f in d.get("fonts", [])]
        p.tilesets = [RegisteredTileset.from_dict(t) for t in d.get("tilesets", [])]
        p.object_defs = [ObjectDefinition.from_dict(o) for o in d.get("object_defs", [])]
        p.scenes = [Scene.from_dict(s) for s in d.get("scenes", [])]
        if not p.scenes:
            p.scenes = [Scene()]
        p.game_data = GameData.from_dict(d.get("game_data", {}))
        p.animation_exports = [AnimationExport.from_dict(a) for a in d.get("animation_exports", [])]
        p.transition_exports = [TransitionExport.from_dict(t) for t in d.get("transition_exports", [])]
        return p

    @classmethod
    def new(cls) -> "Project":
        p = cls()
        p.scenes = [
            Scene.from_template("START_SCREEN", name="Start"),
            Scene.from_template("VN_SCENE",     name="Scene 1"),
            Scene.from_template("END_SCENE",     name="End"),
        ]
        return p

"""
Vita Adventure Creator — Data Models
All project state lives here. Nothing Qt, nothing Lua — pure data.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
import copy
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
    spritesheet_path: str = ""              # primary sheet (single-sheet compat)
    spritesheet_paths: list = field(default_factory=list)  # all sheets for multi-sheet
    frame_count: int = 1
    frame_width: int = 64
    frame_height: int = 64
    sheet_width: int = 64
    sheet_height: int = 64
    sheet_count: int = 1
    frames_per_sheet: int = 1
    fps: int = 12

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "spritesheet_path": self.spritesheet_path,
            "spritesheet_paths": self.spritesheet_paths,
            "frame_count": self.frame_count,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "sheet_width": self.sheet_width,
            "sheet_height": self.sheet_height,
            "sheet_count": self.sheet_count,
            "frames_per_sheet": self.frames_per_sheet,
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
    plugin_data: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ── Scene flow ───────────────────────────────────────────
    target_scene: int = 0              # go_to_scene, if branches

    # ── Timing ───────────────────────────────────────────────
    duration: float = 1.0              # wait seconds, fade duration, slide duration, etc.
    wait_max: float = 1.0              # wait_random: max seconds (duration = min)

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
    signal_name: str = ""              # emit_signal action name

    # ── Variable-to-variable / expression actions ────────────
    var_source: str = ""               # set_variable_from_variable, change_variable_by_variable: source variable name
    expression: str = ""              # evaluate_expression: freeform math string (e.g. "gold + click_power * mult")
    clamp_min: str = ""               # clamp_variable: min bound (number string, or "" = no min)
    clamp_max: str = ""               # clamp_variable: max bound (number string, or "" = no max)
    loop_count: int = 0               # loop: number of iterations (0 = infinite)

    # ── Object targeting ─────────────────────────────────────
    object_def_id: str = ""            # which object definition
    instance_id: str = ""             # specific placed instance (empty = all of type)
    group_name: str = ""              # target group name for group actions
    group_action_type: str = ""       # action type to broadcast to each group member
    focus_target_object_id: str = ""  # set_focus: which object definition to focus

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

    # ── Raw Lua escape hatch ─────────────────────────────────
    lua_snippet: str = ""              # lua_code action: raw Lua lines pasted by developer

    # ── Movement prebuilts ───────────────────────────────────
    movement_speed: float = 1.0
    movement_style: str = "instant"   # "instant" | "slide"
    collision_layer_id: str = ""
    player_width:       int = 32
    player_height:      int = 48
    bullet_direction:   str = "right"       # right | left | up | down
    bullet_speed:       int = 6             # px per frame
    two_way_axis:       str = "horizontal"  # horizontal | vertical
    rotation_mode:          str   = "instant"  # "instant" | "tween"  (8-way movement)
    rotation_tween_duration: float = 0.3       # seconds, used when rotation_mode == "tween"

    # ── Velocity / physics actions ────────────────────────────
    velocity_vx: float = 0.0            # set_velocity / add_velocity: horizontal component
    velocity_vy: float = 0.0            # set_velocity / add_velocity: vertical component
    velocity_set_x: bool = True         # set_velocity: whether to apply the x component
    velocity_set_y: bool = True         # set_velocity: whether to apply the y component

    # ── Jump action ───────────────────────────────────────────
    jump_strength: float = 12.0         # upward velocity kick (always positive; exporter negates)
    jump_max_count: int = 1             # 1 = single jump, 2 = double jump, etc.
    jump_variable_height: bool = False  # if True: cutting the button early reduces jump height
    jump_variable_min_vy: float = 4.0   # minimum upward velocity when button released early
    jump_float: bool = False            # if True: reduced gravity multiplier while rising + button held
    jump_float_gravity_mult: float = 0.4  # gravity multiplier during float (0.0–1.0)
    jump_collision_layer_id: str = ""   # collision layer to use for grounded detection
    jump_player_width: int = 32         # player hitbox width for grounded check
    jump_player_height: int = 48        # player hitbox height for grounded check
    jump_button: str = "cross"          # which button triggers the jump (for variable height release)
    collision_value: int = 1            # collision cell value for collision_set_cell (0=empty, 1=solid)
    collision_source_role: str = "Hitbox"   # object overlap source role filter
    collision_target_role: str = "Hurtbox"  # object overlap target role filter

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
    camera_zoom_target: float = 1.0          # target zoom level for camera_set_zoom / camera_zoom_to
    camera_zoom_duration: float = 0.0        # 0 = instant; used by camera_zoom_to
    camera_zoom_easing: str = "linear"       # easing for camera_zoom_to

    # ── Animation object actions ─────────────────────────────
    ani_target_frame: int = 0                # ani_set_frame target
    ani_fps: int = 12                        # ani_set_speed fps
    ani_slot_name: str = ""                  # ani_switch_slot: slot name to switch to
    ani_flip_h: bool = False                 # ani_set_flip: horizontal flip state
    ani_flip_v: bool = False                 # ani_set_flip: vertical flip state

    # ── Layer actions ────────────────────────────────────────
    layer_name: str = ""                     # target layer by name (layer_show, layer_hide, layer_set_image)

    # ── Path actions ─────────────────────────────────────────
    path_name: str = ""                      # follow_path, set_path_speed: path name
    path_speed: float = 1.0                  # follow_path, set_path_speed: px per frame
    path_loop: bool = False                  # follow_path: loop at end

    # ── Spawn / create_object ────────────────────────────────
    spawn_at_self: bool = False              # True = use spawning object's position as base
    spawn_offset_x: int = 0                  # pixel offset added to spawn X
    spawn_offset_y: int = 0                  # pixel offset added to spawn Y

    # ── Parenting (attach_to, detach, create_object with parent) ─
    parent_id: str = ""                      # instance_id or def_id of parent (attach_to, create_object)
    inherit_position: bool = True
    inherit_rotation: bool = False
    inherit_scale: bool = False
    destroy_with_parent: bool = False
    rotation_offset: float = 0.0             # degrees added to parent rotation when inherit_rotation is True

    # ── Layer Animation actions ──────────────────────────────
    # action_types: layer_anim_play_macro, layer_anim_stop_macro,
    #               layer_anim_set_blink, layer_anim_set_idle,
    #               layer_anim_set_talk, layer_anim_talk_for
    layer_anim_id: str = ""                  # which PaperDollAsset (by id)
    layer_anim_macro_name: str = ""          # macro name to play/stop
    layer_anim_macro_loop: bool = False      # loop the macro
    layer_anim_behavior: str = ""            # "blink" | "idle" | "talk"
    layer_anim_enabled: bool = True          # enable or disable the behavior
    layer_anim_talk_duration: float = 2.0    # seconds for talk_for

    # ── VN Dialog Sound actions ──────────────────────────────
    # action_types: vn_dialog_sound, vn_tw_sound
    vn_dialog_sound_id: str = ""             # audio_id for dialog sound
    vn_dialog_sound_mode: str = "play_once"  # play_once | loop | repeat_on_cycle
    vn_tw_sound_id_0: str = ""               # click sound pool slot 0
    vn_tw_sound_id_1: str = ""               # click sound pool slot 1
    vn_tw_sound_id_2: str = ""               # click sound pool slot 2
    vn_tw_sound_id_3: str = ""               # click sound pool slot 3
    vn_tw_sound_interval: int = 1            # fire every N characters

    # ── Grid actions ─────────────────────────────────────────
    # action_types: grid_place_at, grid_snap_to, grid_get_cell,
    #               grid_get_at, grid_is_empty, grid_get_neighbors,
    #               grid_for_each, grid_clear_cell, grid_clear_all,
    #               grid_move, grid_swap
    grid_name: str = ""                      # which Grid component to target (by grid_name)
    grid_col: int = 0                        # target column (literal)
    grid_row: int = 0                        # target row (literal)
    grid_col_var: str = ""                   # read col from variable instead of literal (if non-empty)
    grid_row_var: str = ""                   # read row from variable instead of literal (if non-empty)
    grid_direction: str = "right"            # for grid_move: up | down | left | right
    grid_distance: int = 1                   # for grid_move: how many cells to shift
    grid_neighbor_mode: str = "4"            # 4 = cardinal only, 8 = include diagonals
    grid_result_var: str = ""                # store result into variable (instance_id, col, row)
    grid_col2: int = 0                       # second cell column (grid_swap)
    grid_row2: int = 0                       # second cell row (grid_swap)
    grid_col2_var: str = ""                  # read second col from variable (grid_swap)
    grid_row2_var: str = ""                  # read second row from variable (grid_swap)

    # 3D scene actions
    door_target_mode: str = "coords"         # open_door / close_door / toggle_door: "coords" | "tag"
    door_col: int = 0                        # target door column when targeting by coords
    door_row: int = 0                        # target door row when targeting by coords
    door_tag: str = ""                       # target door tag when targeting by tag
    obj_3d_id: str = ""                      # move_3d_object / set_3d_object_visible target object id
    obj_3d_wx: float = 0.0                   # target 3D world x position
    obj_3d_wy: float = 0.0                   # target 3D world y position
    obj_3d_visible: bool = True              # target 3D visibility state
    actor_3d_state: str = ""                 # 3D actor state string
    actor_3d_angle: float = 0.0              # 3D actor facing angle in degrees
    actor_3d_query_range: float = 0.0        # optional distance override for 3D actor queries
    actor_3d_alive: bool = True              # 3D actor alive/dead state
    actor_3d_blocking: bool = True           # 3D actor blocking state
    actor_3d_interactable: bool = True       # 3D actor interactable state
    actor_3d_patrol_enabled: bool = True     # 3D actor patrol paused/running state
    player_tile_where: str = "under_player"  # check_player_tile source: under_player | facing_tile
    player_tile_type: str = "empty"          # check_player_tile test: empty | wall | door | exit | trigger | switch

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
        if not isinstance(obj.plugin_data, dict):
            obj.plugin_data = {}
        return obj


@dataclass
class Behavior:
    trigger: str = "on_scene_start"
    plugin_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Valid triggers:
    #   on_input              — any mapped input action fires (uses input_action_name)
    #   on_frame              — runs every frame (uses frame_count for interval)
    #   on_button_pressed     — fires once when button is first pressed (uses button)
    #   on_button_held        — fires every frame while button is held (uses button)
    #   on_button_released    — fires once when button is released (uses button)
    #   on_scene_start        — fires once when the scene loads
    #   on_scene_end          — fires once when the scene ends
    #   on_timer              — fires on a repeating frame interval (uses frame_count)
    #   on_timer_variable     — repeating timer where interval is read from a variable (uses timer_var)
    #   on_create             — fires once when the object is created/spawned
    #   on_destroy            — fires once when the object is destroyed
    #   on_enter              — fires once when a zone target first overlaps this zone
    #   on_exit               — fires once when a zone target stops overlapping this zone
    #   on_overlap            — fires every frame while a zone target overlaps this zone
    #   on_interact_zone      — player presses interact button while inside this zone
    #   on_variable_threshold — fires when a variable crosses a comparison threshold
    #                           (uses threshold_var, threshold_value, threshold_compare, threshold_repeat)
    #   on_touch_tap          — fires when the front touchscreen is tapped inside this object's bounding box
    #   on_touch_swipe        — fires when a touch gesture ends and qualifies as a swipe
    #                           (uses swipe_direction, swipe_min_distance, swipe_scope)
    #   on_path_complete      — fires when an object finishes following a named path (uses path_name)
    #   on_animation_finish   — fires once when a non-looping Animation object reaches its last frame
    #                           (uses ani_trigger_object: object_def_id of the Animation object to watch)
    #   on_animation_frame    — fires each time an Animation object reaches a specific frame index
    #                           (uses ani_trigger_object and ani_trigger_frame)
    #   on_selection          — fires once when this object becomes the focused navigation target
    frame_count: int = 60
    bool_var: str = ""
    input_action_name: str = ""
    button: str = ""               # used by on_button_pressed / held / released
    timer_var: str = ""            # on_timer_variable: name of variable holding the frame interval
    threshold_var: str = ""        # on_variable_threshold: which variable to watch
    threshold_value: str = ""      # on_variable_threshold: value to compare against
    threshold_compare: str = ">="  # on_variable_threshold: == | != | > | < | >= | <=
    threshold_repeat: bool = False # on_variable_threshold: re-arm and fire again each time condition is met
    path_name: str = ""            # on_path_complete: name of the path to watch
    ani_trigger_object: str = ""  # on_animation_finish / on_animation_frame: object_def_id of Animation object
    ani_trigger_frame: int = 0    # on_animation_frame: frame index to watch for
    overlap_object_id: str = ""   # object type or instance id to test against for object-overlap triggers
    overlap_source_role: str = "Hitbox"
    overlap_target_role: str = "Hurtbox"
    swipe_direction: str = "any"  # on_touch_swipe: left | right | up | down | any
    swipe_min_distance: int = 48  # on_touch_swipe: minimum pixel distance to qualify as a swipe
    swipe_scope: str = "screen"   # on_touch_swipe: screen | object
    lua_condition: str = ""       # on_lua_condition: raw Lua boolean expression evaluated every frame
    actions: list[BehaviorAction] = field(default_factory=list)

    def to_dict(self):
        return {
            "trigger":            self.trigger,
            "plugin_data":        copy.deepcopy(self.plugin_data),
            "frame_count":        self.frame_count,
            "bool_var":           self.bool_var,
            "input_action_name":  self.input_action_name,
            "button":             self.button,
            "timer_var":          self.timer_var,
            "threshold_var":      self.threshold_var,
            "threshold_value":    self.threshold_value,
            "threshold_compare":  self.threshold_compare,
            "threshold_repeat":   self.threshold_repeat,
            "path_name":          self.path_name,
            "ani_trigger_object": self.ani_trigger_object,
            "ani_trigger_frame":  self.ani_trigger_frame,
            "overlap_object_id":  self.overlap_object_id,
            "overlap_source_role": self.overlap_source_role,
            "overlap_target_role": self.overlap_target_role,
            "swipe_direction":    self.swipe_direction,
            "swipe_min_distance": self.swipe_min_distance,
            "swipe_scope":        self.swipe_scope,
            "lua_condition":      self.lua_condition,
            "actions":            [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d):
        b = cls()
        b.trigger           = d.get("trigger",           "on_scene_start")
        plugin_data = d.get("plugin_data", {})
        b.plugin_data = copy.deepcopy(plugin_data) if isinstance(plugin_data, dict) else {}
        b.frame_count       = d.get("frame_count",       60)
        b.bool_var          = d.get("bool_var",          "")
        b.input_action_name = d.get("input_action_name", "")
        b.button            = d.get("button",            "")
        b.timer_var         = d.get("timer_var",         "")
        b.threshold_var     = d.get("threshold_var",     "")
        b.threshold_value   = d.get("threshold_value",   "")
        b.threshold_compare = d.get("threshold_compare", ">=")
        b.threshold_repeat  = d.get("threshold_repeat",  False)
        b.path_name         = d.get("path_name",         "")
        b.ani_trigger_object = d.get("ani_trigger_object", "")
        b.ani_trigger_frame  = d.get("ani_trigger_frame",  0)
        b.overlap_object_id  = d.get("overlap_object_id",  "")
        b.overlap_source_role = d.get("overlap_source_role", "Hitbox")
        b.overlap_target_role = d.get("overlap_target_role", "Hurtbox")
        b.swipe_direction    = d.get("swipe_direction",    "any")
        b.swipe_min_distance = d.get("swipe_min_distance", 48)
        b.swipe_scope        = d.get("swipe_scope",        "screen")
        b.lua_condition      = d.get("lua_condition",      "")
        b.actions           = [BehaviorAction.from_dict(a) for a in d.get("actions", [])]
        return b


def get_behavior_plugin_value(container: Any, code: str, field_name: str, default: Any = None) -> Any:
    if hasattr(container, field_name):
        return getattr(container, field_name)
    plugin_data = getattr(container, "plugin_data", {}) or {}
    bucket = plugin_data.get(code, {})
    if isinstance(bucket, dict):
        return bucket.get(field_name, default)
    return default


def set_behavior_plugin_value(container: Any, code: str, field_name: str, value: Any) -> None:
    if hasattr(container, field_name):
        setattr(container, field_name, value)
        return
    plugin_data = getattr(container, "plugin_data", None)
    if not isinstance(plugin_data, dict):
        plugin_data = {}
        setattr(container, "plugin_data", plugin_data)
    bucket = plugin_data.setdefault(code, {})
    if not isinstance(bucket, dict):
        bucket = {}
        plugin_data[code] = bucket
    bucket[field_name] = value


COLLISION_BOX_ROLES = ("Physics", "Hurtbox", "Hitbox", "Trigger")


@dataclass
class CollisionBox:
    """Axis-aligned collision rectangle, in pixel coords relative to object origin."""
    x: int = 0
    y: int = 0
    width: int = 32
    height: int = 32
    role: str = "Physics"

    def to_dict(self):
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "role": self.role if self.role in COLLISION_BOX_ROLES else "Physics",
        }

    @classmethod
    def from_dict(cls, d):
        role = str(d.get("role", "Physics") or "Physics")
        if role not in COLLISION_BOX_ROLES:
            role = "Physics"
        return cls(
            x=d.get("x", 0), y=d.get("y", 0),
            width=d.get("width", 32), height=d.get("height", 32),
            role=role,
        )


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
    groups: list[str] = field(default_factory=list)  # design-time group membership tags
    behavior_type: str = "default"      # default | GUI_Label | GUI_Button | GUI_Panel | Camera | Animation | LayerAnimation
    vn_display_name: str = ""           # shown in the VN dialogue name box
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
    camera_zoom_default: float = 1.0         # starting zoom level for this camera (0.25 – 4.0)
    # 3D actor config — only meaningful for raycast scenes
    is_3d_actor: bool = False
    actor_faction: str = ""
    actor_max_health: int = 100
    actor_move_speed: float = 1.0
    actor_radius: float = 16.0
    actor_sight_range: float = 160.0
    actor_attack_range: float = 48.0
    actor_patrol_path: str = ""
    actor_start_state: str = "idle"

    # Animation config — only meaningful when behavior_type == "Animation"
    ani_file_id: str = ""                    # DEPRECATED — kept for migration only; use ani_slots[0]
    ani_slots: list = field(default_factory=list)  # [{"name": str, "ani_file_id": str}, ...]
    ani_loop: bool = True                    # loop or play once
    ani_play_on_spawn: bool = True           # start playing when object spawns
    ani_start_paused: bool = False           # start paused at specific frame
    ani_pause_frame: int = 0                 # frame to pause on if ani_start_paused
    ani_fps_override: int = 0                # 0 = use file default
    ani_flip_h: bool = False                 # default horizontal flip
    ani_flip_v: bool = False                 # default vertical flip

    # LayerAnimation config — only meaningful when behavior_type == "LayerAnimation"
    layer_anim_id: str = ""                  # reference to PaperDollAsset.id
    layer_anim_blink: bool = True            # blink behavior enabled at spawn
    layer_anim_talk: bool = True             # talk behavior enabled at spawn
    layer_anim_idle: bool = True             # idle breathing behavior enabled at spawn

    # Zone config — makes this object act as an Area2D-style trigger region
    is_zone: bool = False                    # True = this object is a trigger zone
    zone_target: str = "player"              # "player" = only player trips it | "any" = any object trips it

    # Physics config
    affected_by_gravity: bool = False        # True = scene gravity applies to this object
    is_mover: bool = True                    # participates in zone overlap checks
    blocks_2d_movement: bool = False         # if True, this object blocks 2D movement against other objects

    # D-pad navigation config
    navigable: bool = False                  # True = this object can receive focus
    focus_nav_up: str = ""                   # object_def_id of neighbor when pressing up
    focus_nav_down: str = ""                 # object_def_id of neighbor when pressing down
    focus_nav_left: str = ""                 # object_def_id of neighbor when pressing left
    focus_nav_right: str = ""               # object_def_id of neighbor when pressing right

    # Collision boxes — per-frame list of collision rectangles
    # collision_boxes[frame_index] = list of CollisionBox for that frame
    collision_boxes: list[list[CollisionBox]] = field(default_factory=list)
    # Animation collision boxes — keyed by slot name, then frame index
    # ani_collision_boxes[slot_name][frame_index] = list of CollisionBox
    ani_collision_boxes: dict[str, list[list[CollisionBox]]] = field(default_factory=dict)

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
            "groups": list(self.groups),
            "behavior_type": self.behavior_type,
            "vn_display_name": self.vn_display_name,
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
            "camera_zoom_default": self.camera_zoom_default,
            "is_3d_actor": self.is_3d_actor,
            "actor_faction": self.actor_faction,
            "actor_max_health": self.actor_max_health,
            "actor_move_speed": self.actor_move_speed,
            "actor_radius": self.actor_radius,
            "actor_sight_range": self.actor_sight_range,
            "actor_attack_range": self.actor_attack_range,
            "actor_patrol_path": self.actor_patrol_path,
            "actor_start_state": self.actor_start_state,
            "ani_slots": list(self.ani_slots),
            "ani_loop": self.ani_loop,
            "ani_play_on_spawn": self.ani_play_on_spawn,
            "ani_start_paused": self.ani_start_paused,
            "ani_pause_frame": self.ani_pause_frame,
            "ani_fps_override": self.ani_fps_override,
            "ani_flip_h": self.ani_flip_h,
            "ani_flip_v": self.ani_flip_v,
            "layer_anim_id": self.layer_anim_id,
            "layer_anim_blink": self.layer_anim_blink,
            "layer_anim_talk": self.layer_anim_talk,
            "layer_anim_idle": self.layer_anim_idle,
            "is_zone": self.is_zone,
            "zone_target": self.zone_target,
            "affected_by_gravity": self.affected_by_gravity,
            "is_mover": self.is_mover,
            "blocks_2d_movement": self.blocks_2d_movement,
            "navigable": self.navigable,
            "focus_nav_up": self.focus_nav_up,
            "focus_nav_down": self.focus_nav_down,
            "focus_nav_left": self.focus_nav_left,
            "focus_nav_right": self.focus_nav_right,
            "collision_boxes": [[cb.to_dict() for cb in frame_boxes] for frame_boxes in self.collision_boxes],
            "ani_collision_boxes": {
                slot_name: [[cb.to_dict() for cb in frame_boxes] for frame_boxes in frames]
                for slot_name, frames in self.ani_collision_boxes.items()
            },
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
        obj.groups = list(d.get("groups", []))
        obj.behavior_type = d.get("behavior_type", "default")
        obj.vn_display_name = d.get("vn_display_name", "")
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
        obj.camera_zoom_default = d.get("camera_zoom_default", 1.0)
        obj.is_3d_actor = d.get("is_3d_actor", False)
        obj.actor_faction = d.get("actor_faction", "")
        obj.actor_max_health = d.get("actor_max_health", 100)
        obj.actor_move_speed = d.get("actor_move_speed", 1.0)
        obj.actor_radius = d.get("actor_radius", 16.0)
        obj.actor_sight_range = d.get("actor_sight_range", 160.0)
        obj.actor_attack_range = d.get("actor_attack_range", 48.0)
        obj.actor_patrol_path = d.get("actor_patrol_path", "")
        obj.actor_start_state = d.get("actor_start_state", "idle")
        obj.ani_file_id = d.get("ani_file_id", "")  # kept only for migration below
        # Migrate: if saved with old single ani_file_id and no ani_slots, seed slot 0
        raw_slots = d.get("ani_slots", None)
        if raw_slots is not None:
            obj.ani_slots = cls.normalize_ani_slots(raw_slots)
        elif obj.ani_file_id:
            obj.ani_slots = cls.normalize_ani_slots([{"name": "0", "ani_file_id": obj.ani_file_id}])
        else:
            obj.ani_slots = []
        obj.ani_loop = d.get("ani_loop", True)
        obj.ani_play_on_spawn = d.get("ani_play_on_spawn", True)
        obj.ani_start_paused = d.get("ani_start_paused", False)
        obj.ani_pause_frame = d.get("ani_pause_frame", 0)
        obj.ani_fps_override = d.get("ani_fps_override", 0)
        obj.ani_flip_h = d.get("ani_flip_h", False)
        obj.ani_flip_v = d.get("ani_flip_v", False)
        obj.layer_anim_id = d.get("layer_anim_id", "")
        obj.layer_anim_blink = d.get("layer_anim_blink", True)
        obj.layer_anim_talk = d.get("layer_anim_talk", True)
        obj.layer_anim_idle = d.get("layer_anim_idle", True)
        obj.is_zone = d.get("is_zone", False)
        obj.zone_target = d.get("zone_target", "player")
        obj.affected_by_gravity = d.get("affected_by_gravity", False)
        obj.is_mover = d.get("is_mover", True)
        obj.blocks_2d_movement = d.get("blocks_2d_movement", False)
        obj.navigable = d.get("navigable", False)
        obj.focus_nav_up = d.get("focus_nav_up", "")
        obj.focus_nav_down = d.get("focus_nav_down", "")
        obj.focus_nav_left = d.get("focus_nav_left", "")
        obj.focus_nav_right = d.get("focus_nav_right", "")
        obj.collision_boxes = [
            [CollisionBox.from_dict(cb) for cb in frame_boxes]
            for frame_boxes in d.get("collision_boxes", [])
        ]
        obj.ani_collision_boxes = {
            str(slot_name): [
                [CollisionBox.from_dict(cb) for cb in frame_boxes]
                for frame_boxes in frames
            ]
            for slot_name, frames in d.get("ani_collision_boxes", {}).items()
        }
        if obj.behavior_type == "Animation" and not obj.ani_collision_boxes and obj.collision_boxes:
            for slot in obj.ani_slots:
                slot_name = str(slot.get("name", "")).strip()
                if slot_name:
                    obj.ani_collision_boxes[slot_name] = cls.clone_collision_frames(obj.collision_boxes)
        # Do NOT call sync_collision_frames() here — for Animation behavior_type objects
        # the real frame count comes from the AnimationExport, which isn't available at
        # load time. Calling it here would truncate saved collision frames down to 1.
        # The UI (CollisionEditorPanel.load_object / _refresh) always calls
        # sync_collision_frames(frame_count_override) with the correct count.
        return obj

    @staticmethod
    def clone_collision_frames(frames: list[list[CollisionBox]]) -> list[list[CollisionBox]]:
        return [
            [CollisionBox.from_dict(cb.to_dict()) for cb in frame_boxes]
            for frame_boxes in frames
        ]

    @staticmethod
    def normalize_ani_slots(slots: list) -> list[dict]:
        normalized: list[dict] = []
        used_names: set[str] = set()
        for idx, slot in enumerate(slots or []):
            raw_name = str((slot or {}).get("name", "")).strip() or str(idx)
            name = raw_name
            suffix = 1
            while name in used_names:
                name = f"{raw_name}_{suffix}"
                suffix += 1
            used_names.add(name)
            normalized.append({
                "name": name,
                "ani_file_id": str((slot or {}).get("ani_file_id", "") or ""),
            })
        return normalized

    def default_ani_slot_name(self) -> str:
        return next(
            (str(slot.get("name", "")).strip() for slot in self.ani_slots if str(slot.get("name", "")).strip()),
            "",
        )

    def collision_slot_name(self, slot_name: str = "") -> str:
        if self.behavior_type != "Animation":
            return ""
        wanted = str(slot_name or "").strip()
        valid_names = {
            str(slot.get("name", "")).strip()
            for slot in self.ani_slots
            if str(slot.get("name", "")).strip()
        }
        if wanted and wanted in valid_names:
            return wanted
        return self.default_ani_slot_name()

    def collision_frames(self, slot_name: str = "", create: bool = False) -> list[list[CollisionBox]]:
        if self.behavior_type != "Animation":
            return self.collision_boxes
        resolved = self.collision_slot_name(slot_name)
        if not resolved:
            return self.collision_boxes
        if create:
            return self.ani_collision_boxes.setdefault(resolved, [])
        return self.ani_collision_boxes.get(resolved, [])

    def has_any_collision_boxes(self) -> bool:
        if any(frame_boxes for frame_boxes in self.collision_boxes):
            return True
        return any(
            frame_boxes
            for frames in self.ani_collision_boxes.values()
            for frame_boxes in frames
        )

    def sync_collision_frames(self, frame_count_override: int = 0, slot_name: str = ""):
        """Ensure collision_boxes has one entry per frame (at least 1 for static objects).

        frame_count_override: if > 0, use this instead of len(self.frames).
                              Useful for Animation behavior_type where frame count
                              comes from the AnimationExport, not self.frames.

        Trimming only happens when frame_count_override is explicitly provided.
        Without an override (e.g. called from non-UI code that lacks project context),
        we only grow the list — never shrink it — to avoid silently discarding
        collision data for Animation objects whose frame count isn't knowable here.
        """
        frames = self.collision_frames(slot_name, create=True)
        target = frame_count_override if frame_count_override > 0 else max(len(self.frames), 1)
        while len(frames) < target:
            frames.append([])
        # Only trim when the caller explicitly provided the real frame count.
        # Without an override we can't know the true count for Animation objects.
        if frame_count_override > 0 and len(frames) > target:
            del frames[target:]


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

    # ── 3D placement (only used when placed in a 3D scene) ──
    is_3d: bool = False                # True = billboard sprite or HUD in a 3D scene
    grid_x: int = 1                    # tile column
    grid_y: int = 1                    # tile row
    offset_x: float = 0.5             # sub-tile position 0.0–1.0 (0.5 = center)
    offset_y: float = 0.5             # sub-tile position 0.0–1.0 (0.5 = center)
    vertical_offset: float = 0.0       # shift sprite up/down in world
    blocking: bool = False             # blocks player movement?
    hud_mode: bool = False             # True = screen-space HUD image, not a billboard
    hud_x: int = 10                    # screen pixel X (960×544)
    hud_y: int = 10                    # screen pixel Y
    hud_anchor: str = "top_left"       # top_left | top_right | bottom_left | bottom_right | center | bottom_center
    interact_range: int = 80            # pixel radius for RayCast3D.registerObject; ~1.25 tiles at default tile_size
    tile_link_tag: str = ""             # matches a Trigger/Switch tile tag so emit_signal(tag) targets this object
    actor_patrol_path_id: str = ""      # SceneComponent.id of the default 3D patrol path for this placed actor

    # ── Parenting ────────────────────────────────────────────
    parent_id: str = ""                # instance_id of parent PlacedObject ("" = no parent)
    inherit_position: bool = True
    inherit_rotation: bool = False
    inherit_scale: bool = False
    destroy_with_parent: bool = False
    rotation_offset: float = 0.0       # degrees added to parent rotation when inherit_rotation is True

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
            "is_3d": self.is_3d,
            "grid_x": self.grid_x,
            "grid_y": self.grid_y,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "vertical_offset": self.vertical_offset,
            "blocking": self.blocking,
            "hud_mode": self.hud_mode,
            "hud_x": self.hud_x,
            "hud_y": self.hud_y,
            "hud_anchor": self.hud_anchor,
            "interact_range": self.interact_range,
            "tile_link_tag": self.tile_link_tag,
            "actor_patrol_path_id": self.actor_patrol_path_id,
            "parent_id": self.parent_id,
            "inherit_position": self.inherit_position,
            "inherit_rotation": self.inherit_rotation,
            "inherit_scale": self.inherit_scale,
            "destroy_with_parent": self.destroy_with_parent,
            "rotation_offset": self.rotation_offset,
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
        obj.is_3d = d.get("is_3d", False)
        obj.grid_x = d.get("grid_x", 1)
        obj.grid_y = d.get("grid_y", 1)
        obj.offset_x = float(d.get("offset_x", 0.5))
        obj.offset_y = float(d.get("offset_y", 0.5))
        obj.vertical_offset = float(d.get("vertical_offset", 0.0))
        obj.blocking = d.get("blocking", False)
        obj.hud_mode = d.get("hud_mode", False)
        obj.hud_x = d.get("hud_x", 10)
        obj.hud_y = d.get("hud_y", 10)
        obj.hud_anchor = d.get("hud_anchor", "top_left")
        obj.interact_range = int(d.get("interact_range", 80))
        obj.tile_link_tag = d.get("tile_link_tag", "")
        obj.actor_patrol_path_id = d.get("actor_patrol_path_id", "")
        obj.parent_id = d.get("parent_id", "")
        obj.inherit_position = d.get("inherit_position", True)
        obj.inherit_rotation = d.get("inherit_rotation", False)
        obj.inherit_scale = d.get("inherit_scale", False)
        obj.destroy_with_parent = d.get("destroy_with_parent", False)
        obj.rotation_offset = float(d.get("rotation_offset", 0.0))
        return obj


def clone_behaviors(behaviors: list[Behavior]) -> list[Behavior]:
    return [Behavior.from_dict(copy.deepcopy(b.to_dict())) for b in behaviors]


def seed_instance_behaviors_from_definition(
    instance: PlacedObject | None,
    object_def: ObjectDefinition | None,
) -> bool:
    if instance is None or object_def is None:
        return False
    if getattr(instance, "instance_behaviors", None):
        return False
    if not getattr(object_def, "behaviors", None):
        return False
    instance.instance_behaviors = clone_behaviors(object_def.behaviors)
    if not getattr(instance, "instance_node_groups", None):
        node_groups = getattr(object_def, "node_groups", None)
        if isinstance(node_groups, dict):
            setattr(instance, "instance_node_groups", copy.deepcopy(node_groups))
    return True


def effective_placed_behaviors(
    instance: PlacedObject | None,
    object_def: ObjectDefinition | None,
) -> list[Behavior]:
    if instance is not None and getattr(instance, "instance_behaviors", None):
        return list(instance.instance_behaviors)
    if object_def is not None and getattr(object_def, "behaviors", None):
        return list(object_def.behaviors)
    return []


# ─────────────────────────────────────────────────────────────
#  PAPER DOLL SYSTEM
# ─────────────────────────────────────────────────────────────

@dataclass
class PaperDollLayer:
    """One node in a paper doll hierarchy. Children inherit parent transforms."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Layer"
    image_id: Optional[str] = None          # RegisteredImage.id
    origin_x: float = 0.0                   # pivot point, pixels relative to image
    origin_y: float = 0.0                   # pivot point, pixels relative to image
    x: float = 0.0                          # offset from parent's origin
    y: float = 0.0                          # offset from parent's origin
    rotation: float = 0.0                   # degrees
    scale: float = 1.0
    children: list["PaperDollLayer"] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "image_id": self.image_id,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "scale": self.scale,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Layer")
        obj.image_id = d.get("image_id")
        obj.origin_x = float(d.get("origin_x", 0.0))
        obj.origin_y = float(d.get("origin_y", 0.0))
        obj.x = float(d.get("x", 0.0))
        obj.y = float(d.get("y", 0.0))
        obj.rotation = float(d.get("rotation", 0.0))
        obj.scale = float(d.get("scale", 1.0))
        obj.children = [PaperDollLayer.from_dict(c) for c in d.get("children", [])]
        return obj


@dataclass
class BlinkConfig:
    """Auto-blink: swaps a layer's image on a randomized interval."""
    enabled: bool = False
    layer_id: str = ""                      # which PaperDollLayer gets swapped
    alt_image_id: Optional[str] = None      # RegisteredImage.id for closed-eye frame
    interval_min: float = 2.0               # seconds between blinks (lower bound)
    interval_max: float = 5.0               # seconds between blinks (upper bound)
    blink_duration: float = 0.15            # seconds the alt image stays visible
    node_hook_mode: str = "builtin"         # builtin | supplement | replace

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "layer_id": self.layer_id,
            "alt_image_id": self.alt_image_id,
            "interval_min": self.interval_min,
            "interval_max": self.interval_max,
            "blink_duration": self.blink_duration,
            "node_hook_mode": self.node_hook_mode,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            enabled=d.get("enabled", False),
            layer_id=d.get("layer_id", ""),
            alt_image_id=d.get("alt_image_id"),
            interval_min=float(d.get("interval_min", 2.0)),
            interval_max=float(d.get("interval_max", 5.0)),
            blink_duration=float(d.get("blink_duration", 0.15)),
            node_hook_mode=d.get("node_hook_mode", "builtin"),
        )


@dataclass
class MouthConfig:
    """Auto-talk: swaps a layer's image while typewriter text is active."""
    enabled: bool = False
    layer_id: str = ""                      # which PaperDollLayer gets swapped
    alt_image_id: Optional[str] = None      # RegisteredImage.id for open-mouth frame
    image_ids: list[str] = field(default_factory=list)  # ordered extra mouth shapes
    cycle_speed: float = 0.12               # seconds per open/close cycle
    node_hook_mode: str = "builtin"         # builtin | supplement | replace

    def to_dict(self):
        image_ids = [img_id for img_id in self.image_ids if img_id]
        first_image_id = image_ids[0] if image_ids else self.alt_image_id
        return {
            "enabled": self.enabled,
            "layer_id": self.layer_id,
            "alt_image_id": first_image_id,
            "image_ids": image_ids,
            "cycle_speed": self.cycle_speed,
            "node_hook_mode": self.node_hook_mode,
        }

    @classmethod
    def from_dict(cls, d):
        image_ids = [str(img_id) for img_id in d.get("image_ids", []) if img_id]
        legacy_alt = d.get("alt_image_id")
        if not image_ids and legacy_alt:
            image_ids = [legacy_alt]
        return cls(
            enabled=d.get("enabled", False),
            layer_id=d.get("layer_id", ""),
            alt_image_id=image_ids[0] if image_ids else legacy_alt,
            image_ids=image_ids,
            cycle_speed=float(d.get("cycle_speed", 0.12)),
            node_hook_mode=d.get("node_hook_mode", "builtin"),
        )


@dataclass
class IdleBreathingConfig:
    """Idle breathing: periodic scale pulse on a chosen layer."""
    enabled: bool = False
    layer_id: str = ""                      # which PaperDollLayer to pulse (empty = root)
    scale_amount: float = 0.02              # ±percentage (0.02 = ±2%)
    speed: float = 3.0                      # full cycle duration in seconds
    affect_children: bool = True            # if False, only the target layer scales
    node_hook_mode: str = "builtin"         # builtin | supplement | replace

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "layer_id": self.layer_id,
            "scale_amount": self.scale_amount,
            "speed": self.speed,
            "affect_children": self.affect_children,
            "node_hook_mode": self.node_hook_mode,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            enabled=d.get("enabled", False),
            layer_id=d.get("layer_id", ""),
            scale_amount=float(d.get("scale_amount", 0.02)),
            speed=float(d.get("speed", 3.0)),
            affect_children=d.get("affect_children", True),
            node_hook_mode=d.get("node_hook_mode", "builtin"),
        )


@dataclass
class PaperDollKeyframe:
    """One keyframe for one layer at a specific time in a macro."""
    time: float = 0.0                       # seconds into the macro
    layer_id: str = ""                      # which PaperDollLayer
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale: float = 1.0

    def to_dict(self):
        return {
            "time": self.time,
            "layer_id": self.layer_id,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "scale": self.scale,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            time=float(d.get("time", 0.0)),
            layer_id=d.get("layer_id", ""),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            rotation=float(d.get("rotation", 0.0)),
            scale=float(d.get("scale", 1.0)),
        )


@dataclass
class PaperDollMacro:
    """A named, keyframed animation sequence for a paper doll."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Macro"
    duration: float = 1.0                   # total length in seconds
    loop: bool = False
    keyframes: list[PaperDollKeyframe] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "duration": self.duration,
            "loop": self.loop,
            "keyframes": [k.to_dict() for k in self.keyframes],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Macro")
        obj.duration = float(d.get("duration", 1.0))
        obj.loop = d.get("loop", False)
        obj.keyframes = [PaperDollKeyframe.from_dict(k) for k in d.get("keyframes", [])]
        return obj


@dataclass
class PaperDollAsset:
    """A complete paper doll: layer hierarchy + auto-behaviors + macros."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Paper Doll"
    root_layers: list[PaperDollLayer] = field(default_factory=list)
    blink: BlinkConfig = field(default_factory=BlinkConfig)
    mouth: MouthConfig = field(default_factory=MouthConfig)
    idle_breathing: IdleBreathingConfig = field(default_factory=IdleBreathingConfig)
    macros: list[PaperDollMacro] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "root_layers": [l.to_dict() for l in self.root_layers],
            "blink": self.blink.to_dict(),
            "mouth": self.mouth.to_dict(),
            "idle_breathing": self.idle_breathing.to_dict(),
            "macros": [m.to_dict() for m in self.macros],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Paper Doll")
        obj.root_layers = [PaperDollLayer.from_dict(l) for l in d.get("root_layers", [])]
        obj.blink = BlinkConfig.from_dict(d.get("blink", {}))
        obj.mouth = MouthConfig.from_dict(d.get("mouth", {}))
        obj.idle_breathing = IdleBreathingConfig.from_dict(d.get("idle_breathing", {}))
        obj.macros = [PaperDollMacro.from_dict(m) for m in d.get("macros", [])]
        return obj

    def find_layer(self, layer_id: str) -> Optional[PaperDollLayer]:
        """Recursively search the hierarchy for a layer by ID."""
        def _search(layers):
            for l in layers:
                if l.id == layer_id:
                    return l
                found = _search(l.children)
                if found:
                    return found
            return None
        return _search(self.root_layers)


# ─────────────────────────────────────────────────────────────
#  SCENE COMPONENTS
# ─────────────────────────────────────────────────────────────

# Available component types and their default configs
COMPONENT_TYPES = [
    "Layer",
    "TileLayer",
    "CollisionLayer",
    "LightmapLayer",
    "Raycast3DConfig",
    "Music",
    "VNDialogBox",
    "ChoiceMenu",
    "SelectionGroup",
    "HUD",
    "Video",
    "Transition",
    "Path",
    "Gravity",
    "LayerAnimation",
    "Grid",
    "SaveGame",
]

COMPONENT_DEFAULTS: dict[str, dict] = {
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
        "tile_x": False,            # repeat the image horizontally to fill screen width
        "tile_y": False,            # repeat the image vertically to fill screen height
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
    "LightmapLayer": {
        "layer_name": "New Lightmap",
        "layer": 99,             # drawn as an overlay after world rendering
        "tile_size": 32,         # light grid cell size in pixels
        "map_width": 30,
        "map_height": 17,
        "cells": [],             # flat int array, len = map_width * map_height, 0..255 darkness
        "visible": True,
        "opacity": 255,          # master alpha multiplier for the whole layer
        "blend_color": "#000000",
        "paint_value": 192,      # default brush darkness in the editor
        "brush_mode": "set",     # set | add | subtract
        "brush_radius": 0,       # radius in cells; 0 = single-cell stamp
        "brush_strength": 48,    # per-stamp delta for add/subtract/soft set
    },
    "Raycast3DConfig": {
        "movement_mode": "grid",         # free | grid | rail
        "control_profile": "grid_strafe",# grid_classic | grid_strafe | free_modern
        "turn_mode": "smooth",           # smooth | step
        "rail_mode": "path",             # path | locked_forward
        "move_speed": 5.0,               # free movement step per frame
        "turn_speed": 5.0,               # smooth turn degrees per frame
        "grid_step_distance": 64,        # pixels advanced per grid step
        "grid_step_duration": 0.15,      # seconds per grid move
        "turn_step_angle": 90,           # degrees per turn in step mode
        "turn_duration": 0.12,           # seconds per step turn
        "allow_strafe": False,
        "allow_backstep": True,
        "interact_distance": 80,         # pixel range for tile/object interact tests
        "lock_input_while_moving": True,
        "collision_behavior": "stop",    # stop | slide
        "camera_pitch_enabled": False,
        "controller_scheme": "standard", # legacy reserved field; superseded by control_profile
        "default_object_interact_distance": 80,
        "render_view_size": 60,
        "rail_path_name": "",
    },
    "Music": {
        "action": "keep",       # keep | change | stop
        "audio_id": None,
    },
    "VNDialogBox": {
        "dialog_pages": [
            {"character": "", "lines": ["", "", "", ""], "advance_to_next": False, "typewriter": False, "typewriter_speed": 30},
        ],
        "font_size": 16,
        "line_spacing": 35,
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
    "Path": {
        "path_name": "New Path",
        "points": [],          # list of {x, y, cx1, cy1, cx2, cy2}
        "closed": False,
    },
    "Gravity": {
        "gravity_strength": 0.5,       # pixels per frame² (acceleration)
        "gravity_direction": "down",   # down | up | left | right
        "terminal_velocity": 10,       # max fall speed in pixels per frame
    },
    "LayerAnimation": {
        "layer_anim_id": "",           # PaperDollAsset.id
    },
    "Grid": {
        "grid_name": "grid1",          # lookup key for behavior actions
        "columns": 8,                  # number of columns
        "rows": 8,                     # number of rows
        "cell_width": 32,              # pixel width of each cell
        "cell_height": 32,             # pixel height of each cell
        "origin_x": 0,                 # pixel X offset of grid top-left in scene
        "origin_y": 0,                 # pixel Y offset of grid top-left in scene
    },
    "SaveGame": {
        "title_text": "SAVE / LOAD",
        "slot_prefix": "Slot",
        "help_text": "Cross: Save Triangle: Load Circle: Back",
        "empty_slot_text": "Empty",
        "saved_text": "Saved.",
        "no_save_text": "No save in this slot.",
        "font_id": "",
        "title_font_size": 24,
        "slot_font_size": 18,
        "message_font_size": 18,
        "help_font_size": 16,
        "bg_color": "#000000",
        "title_color": "#FFFFFF",
        "slot_color": "#B4B4B4",
        "selected_slot_color": "#FFFF64",
        "empty_slot_color": "#787878",
        "message_color": "#FFFFFF",
        "help_color": "#C8C8C8",
        "background_use_image": False,
        "background_image_id": None,
        "layout_preset": "center",
        "slot_spacing": 60,
        "show_help_text": True,
        "use_panel": False,
        "panel_color": "#101018",
        "panel_opacity": 180,
    },
}



@dataclass
class SceneComponent:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    component_type: str = "Layer"
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
        obj.component_type = d.get("component_type", "Layer")
        obj.config = d.get("config", {})
        # ── Migrate legacy VNDialogBox (speaker_name + lines → dialog_pages) ──
        # Must run BEFORE defaults fill, which would add an empty dialog_pages.
        if obj.component_type == "VNDialogBox" and "dialog_pages" not in obj.config and "lines" in obj.config:
            legacy_name  = obj.config.pop("speaker_name", "")
            legacy_lines = obj.config.pop("lines", ["", "", "", ""])
            legacy_lines = (legacy_lines + ["", "", "", ""])[:4]
            advance_flag = obj.config.get("advance", True)
            obj.config["dialog_pages"] = [
                {"character": legacy_name, "lines": legacy_lines, "advance_to_next": advance_flag, "typewriter": False, "typewriter_speed": 30},
            ]
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


def ensure_raycast3d_config(scene: "Scene") -> SceneComponent:
    """Ensure every 3D scene owns exactly one Raycast3D config component."""
    existing = [c for c in scene.components if c.component_type == "Raycast3DConfig"]
    if existing:
        primary = existing[0]
        defaults = COMPONENT_DEFAULTS.get("Raycast3DConfig", {})
        import copy
        for k, v in defaults.items():
            if k not in primary.config:
                primary.config[k] = copy.deepcopy(v)
        if "control_profile" not in primary.config:
            _mode = primary.config.get("movement_mode", getattr(scene, "movement_mode", "grid"))
            primary.config["control_profile"] = "free_modern" if _mode == "free" else "grid_strafe"
        for extra in existing[1:]:
            scene.components.remove(extra)
        return primary

    comp = make_component("Raycast3DConfig")
    comp.config["movement_mode"] = getattr(scene, "movement_mode", comp.config["movement_mode"])
    comp.config["control_profile"] = "free_modern" if comp.config["movement_mode"] == "free" else "grid_strafe"
    comp.config["move_speed"] = float(getattr(scene, "move_speed", comp.config["move_speed"]))
    comp.config["turn_speed"] = float(getattr(scene, "turn_speed", comp.config["turn_speed"]))
    scene.components.insert(0, comp)
    return comp


# ─────────────────────────────────────────────────────────────
#  MAP DATA  (3D scene map, owned by Scene)
# ─────────────────────────────────────────────────────────────

# TileMetaType constants — valid values for TileMeta.type
TILE_META_DOOR    = "door"
TILE_META_EXIT    = "exit"
TILE_META_TRIGGER = "trigger"
TILE_META_SWITCH  = "switch"


@dataclass
class TileMeta:
    """Metadata attached to a single map tile. Sparse — only exists where painted.
    Keyed in MapData.tile_meta by the string "col,row".

    type:         one of the TILE_META_* constants
    state:        runtime-mutable state string  ("open"/"closed" for doors,
                  "on"/"off" for switches, "" for triggers/exits)
    target_scene: scene index to load (exit tiles only; matches Scene index in project)
    tag:          arbitrary string identifier used by trigger/switch tiles to
                  link to behavior dispatch
    """
    type:         str = TILE_META_DOOR
    state:        str = "closed"
    target_scene: int = 0
    tag:          str = ""
    texture_image_id: str = ""  # door-only: registered image id used for the closed door surface

    def to_dict(self):
        return {
            "type":         self.type,
            "state":        self.state,
            "target_scene": self.target_scene,
            "tag":          self.tag,
            "texture_image_id": self.texture_image_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TileMeta":
        return cls(
            type=d.get("type", TILE_META_DOOR),
            state=d.get("state", "closed"),
            target_scene=int(d.get("target_scene", 0)),
            tag=d.get("tag", ""),
            texture_image_id=d.get("texture_image_id", ""),
        )


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
    skybox_image_id: str = ""          # registered image ID for skybox background (empty = use fillRect)
    accuracy:     int   = 3            # raycaster column stride (1=best quality, 7=fastest)
    tile_meta:    dict  = field(default_factory=dict)  # sparse {"{col},{row}": TileMeta}

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
            "skybox_image_id": self.skybox_image_id,
            "accuracy":    self.accuracy,
            "tile_meta":   {k: v.to_dict() for k, v in self.tile_meta.items()},
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
        m.skybox_image_id = d.get("skybox_image_id", "")
        m.accuracy    = d.get("accuracy",    3)
        raw_meta = d.get("tile_meta", {})
        m.tile_meta = {k: TileMeta.from_dict(v) for k, v in raw_meta.items()}
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
            make_component("Music"),
            make_component("VNDialogBox"),
        ]
    elif template == "CHOICE_SCENE":
        return [
            make_component("Music"),
            make_component("VNDialogBox"),
            make_component("ChoiceMenu"),
        ]
    elif template == "START_SCREEN":
        return [
            make_component("Music"),
        ]
    elif template == "END_SCENE":
        return [
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
    #("Choice Scene", "CHOICE_SCENE"),#
    #("Start Screen", "START_SCREEN"),#
    #("End Scene",    "END_SCENE"),#
    #("Cutscene",     "CUTSCENE"),#
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

    def ensure_required_components(self):
        if self.scene_type == "3d":
            ensure_raycast3d_config(self)

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
        s.ensure_required_components()
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
            s.movement_mode = "grid"
            s.map_data   = MapData()
        s.ensure_required_components()
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
    source_type: str = "button"
    stick: str = "left"
    direction: str = "up"
    deadzone: int = 32

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "button": self.button,
            "event": self.event,
            "hold_duration": self.hold_duration,
            "source_type": self.source_type,
            "stick": self.stick,
            "direction": self.direction,
            "deadzone": self.deadzone,
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", obj.name)
        obj.button = d.get("button", obj.button)
        obj.event = d.get("event", obj.event)
        obj.hold_duration = float(d.get("hold_duration", 2.0))
        obj.source_type = d.get("source_type", "button")
        obj.stick = d.get("stick", "left")
        obj.direction = d.get("direction", "up")
        obj.deadzone = int(d.get("deadzone", 32))
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
    volume_default: int = 100
    fps_cap_enabled: bool = True
    dpad_mirror_stick: str = "none"
    dpad_mirror_deadzone: int = 32

    def to_dict(self):
        return {
            "variables": [v.to_dict() for v in self.variables],
            "inventory_items": [i.to_dict() for i in self.inventory_items],
            "input_actions": [a.to_dict() for a in self.input_actions],
            "signals": [s.to_dict() for s in self.signals],
            "inventory_enabled": self.inventory_enabled,
            "inventory_max": self.inventory_max,
            "volume_default": self.volume_default,
            "fps_cap_enabled": self.fps_cap_enabled,
            "dpad_mirror_stick": self.dpad_mirror_stick,
            "dpad_mirror_deadzone": self.dpad_mirror_deadzone,
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
        gd.volume_default = d.get("volume_default", 100)
        gd.fps_cap_enabled = d.get("fps_cap_enabled", True)
        gd.dpad_mirror_stick = d.get("dpad_mirror_stick", "none")
        gd.dpad_mirror_deadzone = int(d.get("dpad_mirror_deadzone", 32))
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
    paper_dolls: list[PaperDollAsset] = field(default_factory=list)
    plugin_registry: Any = field(default=None, repr=False, compare=False)

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

    def get_paper_doll(self, doll_id: str) -> Optional[PaperDollAsset]:
        return next((d for d in self.paper_dolls if d.id == doll_id), None)

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
            "paper_dolls": [d.to_dict() for d in self.paper_dolls],
        }

    def save(self, path: str | Path):
        path = Path(path)
        self.project_folder = str(path.parent)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        from plugin_registry import scan_plugins

        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = cls()
        p.title = d.get("title", "Untitled Game")
        p.title_id = d.get("title_id", "ADVG00001")
        p.author = d.get("author", "")
        p.version = d.get("version", "1.0")
        p.project_folder = str(path.parent)
        p.plugin_registry = scan_plugins(path.parent)
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
        p.paper_dolls = [PaperDollAsset.from_dict(pd) for pd in d.get("paper_dolls", [])]
        return p

    @classmethod
    def new(cls) -> "Project":
        from plugin_registry import scan_plugins

        p = cls()
        p.project_folder = str(Path.cwd())
        p.plugin_registry = scan_plugins(p.project_folder)
        p.scenes = [
            Scene.from_template("BLANK", name="Scene 1"),
        ]
        return p

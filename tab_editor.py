# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — Editor Tab
WYSIWYG scene editor with 960x544 1:1 canvas, grid, snap, drag-and-drop,
and a tabbed inspector (Object tab + Scene tab) with behavior/action editing.
"""

from __future__ import annotations
import copy

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QScrollArea,
    QDialog, QDialogButtonBox, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QSlider, QTabWidget,
    QLineEdit, QStackedWidget, QSizePolicy, QSplitter, QColorDialog,
)
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QPixmap, QPainter, QPen, QBrush,
    QMouseEvent, QPaintEvent, QTransform,
)

from models import (
    Project,
    Scene,
    PlacedObject,
    Behavior,
    BehaviorAction,
    SceneComponent,
    ObjectDefinition,
    seed_instance_behaviors_from_definition,
    effective_placed_behaviors,
)
from plugin_registry import build_auto_panel
from project_explorer import ProjectExplorer
from tile_palette import TilePalette
from theme_utils import replace_widget_theme_colors

# ─────────────────────────────────────────────────────────────
#  COLOURS
# ─────────────────────────────────────────────────────────────

DARK       = "#0f0f12"
PANEL      = "#16161c"
SURFACE    = "#1e1e28"
SURFACE2   = "#26263a"
BORDER     = "#2e2e42"
ACCENT     = "#7c6aff"
TEXT       = "#e8e6f0"
TEXT_DIM   = "#7a7890"
TEXT_MUTED = "#4a4860"
SUCCESS    = "#4ade80"
WARNING    = "#facc15"
DANGER     = "#f87171"

ROLE_COLORS = {"start": SUCCESS, "end": DANGER, "": TEXT_DIM}

# Mutable theme snapshot — updated by EditorTab.restyle() so helpers always
# read the current accent/border/etc. without needing to re-construct widgets.
_current_theme: dict = {
    "DARK": DARK, "PANEL": PANEL, "SURFACE": SURFACE, "SURFACE2": SURFACE2,
    "BORDER": BORDER, "ACCENT": ACCENT,
    "TEXT": TEXT, "TEXT_DIM": TEXT_DIM, "TEXT_MUTED": TEXT_MUTED,
    "SUCCESS": SUCCESS, "WARNING": WARNING, "DANGER": DANGER,
}
# Every accent QPushButton created by _small_btn is registered here so
# restyle() can update them all — they are built once at construction time.
_accent_buttons: list = []
VITA_W = 960
VITA_H = 544

_BUILTIN_EDITOR_TOOLS: dict[str, list[dict]] = {
    "CollisionLayer": [
        {
            "kind": "grid_map",
            "data_key": "tiles",
            "width_key": "map_width",
            "height_key": "map_height",
            "cell_size_key": "tile_size",
            "mode": "binary",
            "default_cell": 0,
            "active_value": 1,
            "overlay_color": "#ff5050",
            "paint_label": "Paint",
            "erase_label": "Erase",
        }
    ],
    "LightmapLayer": [
        {
            "kind": "grid_map",
            "data_key": "cells",
            "width_key": "map_width",
            "height_key": "map_height",
            "cell_size_key": "tile_size",
            "mode": "scalar",
            "default_cell": 0,
            "paint_value_key": "paint_value",
            "brush_mode_key": "brush_mode",
            "brush_radius_key": "brush_radius",
            "brush_strength_key": "brush_strength",
            "overlay_color_key": "blend_color",
            "opacity_key": "opacity",
            "paint_label": "Paint",
            "erase_label": "Erase",
        }
    ],
    "Path": [
        {
            "kind": "path",
            "points_key": "points",
            "closed_key": "closed",
            "name_key": "path_name",
            "draw_label": "Draw Path",
            "supports_bezier": True,
        }
    ],
}


def _project_registry(project: Project | None):
    return getattr(project, "plugin_registry", None) if project is not None else None


def _component_descriptor(project: Project | None, component_type: str) -> dict | None:
    registry = _project_registry(project)
    return registry.get_component_descriptor(component_type) if registry else None


def _component_editor_tools(project: Project | None, component_or_type) -> list[dict]:
    component_type = (
        component_or_type.component_type
        if hasattr(component_or_type, "component_type")
        else str(component_or_type)
    )
    descriptor = _component_descriptor(project, component_type)
    if descriptor:
        return copy.deepcopy(descriptor.get("editor_tools", []) or [])
    return copy.deepcopy(_BUILTIN_EDITOR_TOOLS.get(component_type, []))


def _component_editor_tool(project: Project | None, component, kind: str) -> dict | None:
    for tool in _component_editor_tools(project, component):
        if str(tool.get("kind", "")) == kind:
            return tool
    return None


class _PlacedObjectBehaviorTarget:
    def __init__(self, instance: PlacedObject, object_def: ObjectDefinition | None):
        self._instance = instance
        self._object_def = object_def

    @property
    def name(self) -> str:
        base_name = self._object_def.name if self._object_def else "Object"
        instance_id = getattr(self._instance, "instance_id", "")
        return f"{base_name} [{instance_id}]" if instance_id else base_name

    @property
    def instance_id(self) -> str:
        return getattr(self._instance, "instance_id", "")

    @property
    def behaviors(self) -> list[Behavior]:
        return self._instance.instance_behaviors

    @behaviors.setter
    def behaviors(self, value: list[Behavior]) -> None:
        self._instance.instance_behaviors = list(value)

    @property
    def node_groups(self):
        return getattr(self._instance, "instance_node_groups", None)

    @node_groups.setter
    def node_groups(self, value) -> None:
        setattr(self._instance, "instance_node_groups", copy.deepcopy(value) if isinstance(value, dict) else value)


def _theme_snapshot() -> dict:
    return {
        "DARK": DARK,
        "PANEL": PANEL,
        "SURFACE": SURFACE,
        "SURFACE2": SURFACE2,
        "BORDER": BORDER,
        "ACCENT": ACCENT,
        "TEXT": TEXT,
        "TEXT_DIM": TEXT_DIM,
        "TEXT_MUTED": TEXT_MUTED,
        "SUCCESS": SUCCESS,
        "WARNING": WARNING,
        "DANGER": DANGER,
    }

# ─────────────────────────────────────────────────────────────
#  ACTION PALETTE DATA
# ─────────────────────────────────────────────────────────────

OBJECT_TRIGGERS = [
    ("on_interact",        "On Interact",             "Input",    "Player presses the interact button near this object."),
    ("on_button_pressed",  "On Button Pressed",       "Input",    "Fires once the frame a specific button is first pressed."),
    ("on_button_held",     "On Button Held",          "Input",    "Fires every frame while a specific button is held down."),
    ("on_button_released", "On Button Released",      "Input",    "Fires once the frame a specific button is released."),
    ("on_input",           "On Input Action",         "Input",    "Fires when a named input action from Game Data triggers."),
    ("on_frame",           "Every Frame",             "Timing",   "Runs every single frame. Use for continuous logic."),
    ("on_timer",           "On Timer",                "Timing",   "Fires on a repeating interval (in frames)."),
    ("on_scene_start",     "On Scene Start",          "Scene",    "Fires once when this scene first loads."),
    ("on_scene_end",       "On Scene End",            "Scene",    "Fires once just before this scene ends."),
    ("on_create",          "On Create",               "Object",   "Fires once when this object is spawned into the scene."),
    ("on_destroy",         "On Destroy",              "Object",   "Fires once just before this object is destroyed."),
    ("on_enter",           "On Zone Enter",           "Zone",     "Fires once when a target first overlaps this zone."),
    ("on_exit",            "On Zone Exit",            "Zone",     "Fires once when a target stops overlapping this zone."),
    ("on_overlap",         "On Zone Overlap",         "Zone",     "Fires every frame while a target overlaps this zone."),
    ("on_interact_zone",   "On Interact in Zone",     "Zone",     "Player presses interact while inside this zone."),
    ("on_signal",          "On Signal",               "Signal",   "Fires when a named signal is emitted anywhere in the scene."),
    ("on_layer_anim_blink", "On Puppet Blink",        "Puppet Animation", "Fires when this LayerAnimation object produces a blink hook event."),
    ("on_layer_anim_talk_step", "On Puppet Talk Step", "Puppet Animation", "Fires when this LayerAnimation object advances to the next talk-step hook event."),
    ("on_layer_anim_idle_cycle", "On Puppet Idle Cycle", "Puppet Animation", "Fires when this LayerAnimation object completes an idle-breathing cycle hook event."),
]

SCENE_TRIGGERS = [
    ("on_scene_start",     "On Scene Start",          "Scene",    "Fires once when this scene first loads."),
    ("on_scene_end",       "On Scene End",            "Scene",    "Fires once just before this scene ends."),
    ("on_scene_loop",      "On Scene Loop",           "Scene",    "Fires every time the scene loops back to the start."),
    ("on_timer",           "On Timer",                "Timing",   "Fires on a repeating interval (in frames)."),
]

BUTTON_OPTIONS = ["cross", "circle", "square", "triangle", "dpad_up", "dpad_down", "dpad_left", "dpad_right", "l", "r", "start", "select"]
BUTTON_TRIGGERS = {"on_button_pressed", "on_button_held", "on_button_released"}

ACTION_PALETTE = {
    "Scene Flow": [
        ("go_to_scene",     "Go to Scene",          "Jump to a specific scene by number."),
        ("go_to_next",      "Go to Next Scene",      "Advance to the next scene in the list."),
        ("go_to_prev",      "Go to Previous Scene",  "Go back to the previous scene."),
        ("go_to_random",    "Go to Random Scene",    "Jump to a random scene from a list you specify."),
        ("restart_scene",   "Restart Scene",         "Reload and restart the current scene from the beginning."),
        ("quit_game",       "Quit Game",             "Exit the application."),
    ],
    "Timing": [
        ("wait",            "Wait",                  "Pause execution for N seconds before continuing."),
        ("wait_for_input",  "Wait for Input",        "Pause until the player presses any button."),
    ],
    "Screen": [
        ("fade_in",         "Fade In",               "Fade the screen in from black over N seconds."),
        ("fade_out",        "Fade Out",              "Fade the screen out to black over N seconds."),
        ("fade_to_color",   "Fade to Color",         "Fade to a specific color over N seconds."),
        ("flash_screen",    "Flash Screen",          "Briefly flash the screen a color."),
        ("shake_screen",    "Shake Screen",          "Shake the screen for N seconds with a given intensity."),
    ],
    "Camera": [
        ("camera_move_to",    "Move Camera To",        "Move the camera center to an absolute X, Y position."),
        ("camera_offset",     "Offset Camera",         "Move the camera relative to its current position."),
        ("camera_follow",     "Follow Object",         "Make the camera follow a specific object."),
        ("camera_stop_follow","Stop Following",        "Stop the camera from following any object."),
        ("camera_reset",      "Reset Camera",          "Return camera to default center position (480, 272)."),
        ("camera_shake",      "Shake Camera",          "Shake the screen with a given intensity and duration."),
        ("camera_set_zoom",   "Set Camera Zoom",       "Instantly set the camera zoom level (1.0 = normal)."),
        ("camera_zoom_to",    "Zoom Camera To",        "Smoothly tween the camera zoom to a target level."),
    ],
    "Animation": [
        ("ani_play",      "Play Animation",    "Start or resume an animation object."),
        ("ani_pause",     "Pause Animation",   "Pause an animation object."),
        ("ani_stop",      "Stop Animation",    "Stop and reset an animation object to frame 0."),
        ("ani_set_frame", "Set Frame",         "Jump to a specific frame."),
        ("ani_set_speed", "Set Speed",         "Change the playback FPS."),
    ],
    "Layers": [
        ("layer_show",      "Show Layer",            "Make a named Layer component visible."),
        ("layer_hide",      "Hide Layer",            "Make a named Layer component invisible."),
        ("layer_set_image", "Set Layer Image",       "Swap the image displayed on a named Layer component."),
    ],
    "Music & Sound": [
        ("play_music",      "Play Music",            "Start playing a registered music track."),
        ("stop_music",      "Stop Music",            "Stop the currently playing music."),
        ("pause_music",     "Pause Music",           "Pause the current music track."),
        ("resume_music",    "Resume Music",          "Resume a paused music track."),
        ("set_music_volume","Set Music Volume",      "Set the music volume to a value between 0 and 100."),
        ("play_sfx",        "Play Sound Effect",     "Play a registered sound effect once."),
        ("stop_all_sounds", "Stop All Sounds",       "Stop all currently playing sound effects."),
    ],
    "Dialogue": [
        ("show_dialogue",   "Show Dialogue Box",     "Make the VN dialogue box visible."),
        ("hide_dialogue",   "Hide Dialogue Box",     "Hide the VN dialogue box."),
        ("set_speaker",     "Set Speaker Name",      "Set the name displayed in the dialogue name tag."),
        ("set_speaker_color","Set Speaker Color",    "Change the color of the speaker name tag."),
        ("set_dialogue_line","Set Dialogue Line",    "Set the text for a specific dialogue line slot (1-4)."),
        ("clear_dialogue",  "Clear Dialogue",        "Clear the dialogue text and speaker name."),
        ("wait_for_advance","Wait for Dialogue Advance","Pause until the player presses the advance button."),
    ],
    "Choice Menu": [
        ("show_choices",    "Show Choice Menu",      "Display the choice menu."),
        ("hide_choices",    "Hide Choice Menu",      "Hide the choice menu."),
        ("set_choice_text", "Set Choice Text",       "Set the label for a specific choice button."),
        ("set_choice_dest", "Set Choice Destination","Set which scene a specific choice button leads to."),
    ],
    "Variables & Flags": [
        ("set_variable",    "Set Variable",          "Set a game variable to a specific value."),
        ("change_variable", "Change Variable",       "Add, subtract, multiply, or divide a variable by a value."),
        ("increment_var",   "Increment Variable",    "Add a value to a variable using the common counter pattern."),
        ("set_flag",        "Set Flag",              "Set a boolean flag to true or false."),
        ("toggle_flag",     "Toggle Flag",           "Flip a boolean flag from its current state."),
        ("if_variable",     "If Variable",           "Branch: run different actions based on a variable's value."),
        ("if_flag",         "If Flag",               "Branch: run different actions based on whether a flag is true."),
    ],
    "Inventory": [
        ("add_item",        "Add Item",              "Give the player a registered inventory item."),
        ("remove_item",     "Remove Item",           "Remove a specific item from the player's inventory."),
        ("if_has_item",     "If Has Item",           "Branch: run actions based on whether the player has an item."),
        ("show_inventory",  "Show Inventory",        "Open the inventory overlay."),
        ("hide_inventory",  "Hide Inventory",        "Close the inventory overlay."),
    ],
    "Save & Load": [
        ("save_game",       "Save Game",             "Write the current game state to the save file."),
        ("load_game",       "Load Game",             "Load the saved game state."),
        ("delete_save",     "Delete Save",           "Erase the save file."),
        ("if_save_exists",  "If Save Exists",        "Branch: run actions based on whether a save file exists."),
    ],
    "Signals": [
        ("emit_signal",    "Emit Signal",           "Broadcast a named signal to any on_signal behaviors in this scene."),
    ],
    "Input": [
        ("if_button_pressed",  "If Button Pressed",  "Branch: run actions when a specific button is pressed this frame."),
        ("if_button_held",     "If Button Held",     "Branch: run actions while a specific button is held."),
        ("if_button_released", "If Button Released", "Branch: run actions when a specific button is released this frame."),
    ],
    "Movement": [
        ("four_way_movement",         "4-Way Movement",           "Move this object with the d-pad. No input setup required — just set speed and drop it on any object."),
        ("four_way_movement_collide", "4-Way Movement (Collide)", "Move with d-pad, blocked by a CollisionLayer. Set speed, player size, and pick the collision layer."),
        ("two_way_movement",          "2-Way Movement",           "Move left/right OR up/down with the d-pad. Choose axis and speed."),
        ("two_way_movement_collide",  "2-Way Movement (Collide)", "2-way d-pad movement blocked by a CollisionLayer. Choose axis, speed, player size, and collision layer."),
        ("fire_bullet",               "Fire Bullet",              "Move this object as a projectile each frame. Set direction and speed. Pair with Create Object to spawn it."),
    ],
    "Collision": [
        ("collision_set_cell",    "Set Collision Cell",    "Set a CollisionLayer cell to empty or solid at runtime."),
        ("collision_toggle_cell", "Toggle Collision Cell", "Flip a CollisionLayer cell between empty and solid at runtime."),
        ("collision_get_cell",    "Get Collision Cell",    "Read a CollisionLayer cell into a variable at runtime."),
    ],
    "Objects": [
        ("show_object",     "Show Object",           "Make a placed object visible."),
        ("hide_object",     "Hide Object",           "Make a placed object invisible."),
        ("set_opacity",     "Set Opacity",           "Set an object's opacity to a value between 0 and 100."),
        ("fade_in_object",  "Fade Object In",        "Gradually fade an object to fully visible over N seconds."),
        ("fade_out_object", "Fade Object Out",       "Gradually fade an object to invisible over N seconds."),
        ("move_to",         "Move To Position",      "Instantly place an object at a specific X, Y coordinate."),
        ("move_to_variable","Move To Variables",     "Move an object to X and Y values read from variables."),
        ("move_by",         "Move By Offset",        "Instantly shift an object by X, Y pixels from its current position."),
        ("slide_to",        "Slide To Position",     "Smoothly move an object to X, Y over N seconds."),
        ("slide_by",        "Slide By Offset",       "Smoothly move an object by X, Y pixels over N seconds."),
        ("return_to_start", "Return to Start",       "Move the object back to where it was placed in the editor."),
        ("set_scale",       "Set Scale",             "Instantly set an object's scale to a specific value."),
        ("scale_to",        "Scale To",              "Smoothly scale an object to a target value over N seconds."),
        ("set_rotation",    "Set Rotation",          "Instantly set an object's rotation in degrees."),
        ("rotate_to",       "Rotate To",             "Smoothly rotate an object to a target angle over N seconds."),
        ("rotate_by",       "Rotate By",             "Rotate an object by N degrees from its current angle over N seconds."),
        ("spin",            "Spin",                  "Continuously rotate an object at N degrees per second."),
        ("stop_spin",       "Stop Spinning",         "Stop any continuous rotation on an object."),
        ("play_anim",       "Play Animation",        "Start playing the object's animation frames."),
        ("stop_anim",       "Stop Animation",        "Freeze the animation on the current frame."),
        ("set_frame",       "Set Frame",             "Jump to a specific animation frame index."),
        ("set_anim_speed",  "Set Animation Speed",   "Change the frames-per-second of the animation."),
        ("create_object",   "Create Object",         "Create a new instance of an object definition at X, Y."),
        ("destroy_object",  "Destroy Object",        "Remove a specific placed object from the scene."),
        ("destroy_all_type","Destroy All of Type",   "Remove all instances of a given object definition."),
        ("enable_interact", "Enable Interaction",    "Allow the player to interact with this object."),
        ("disable_interact","Disable Interaction",   "Prevent the player from interacting with this object."),
        ("add_to_group",         "Add Object to Group",      "Add an object to a named group at runtime."),
        ("remove_from_group",    "Remove Object from Group", "Remove an object from a named group at runtime."),
        ("call_action_on_group", "Call Action on Group",     "Broadcast an action to every object currently in a named group."),
        ("if_in_group",          "If Object in Group",       "Branch based on whether an object is a member of a named group."),
    ],
    "VN Character": [
        ("set_char_sprite", "Set Character Sprite",  "Change which image the character is displaying."),
        ("set_display_name","Set Display Name",      "Change the name shown in the dialogue name tag."),
        ("char_enter",      "Character Enter",       "Slide or fade a character into the scene from an edge."),
        ("char_exit",       "Character Exit",        "Slide or fade a character out of the scene toward an edge."),
        ("char_react",      "Character React",       "Play a brief shake or bounce on the character."),
    ],
    "GUI": [
        ("set_label_text",     "Set Label Text",         "Replace the full text of a GUI_Label at runtime."),
        ("set_label_text_var", "Set Label Text (Variable)", "Set a GUI_Label's text to the current value of a game variable."),
        ("set_label_color",    "Set Label Color",        "Change the text color of a GUI_Label at runtime."),
        ("set_label_size",     "Set Label Font Size",    "Change the font size of a GUI_Label at runtime."),
    ],
    "Debug": [
        ("log_message",     "Log Message",           "Print a message to the debug console. Does nothing in release builds."),
        ("show_debug",      "Show Debug Overlay",    "Toggle a debug overlay showing current variable values."),
    ],
}

# Fields per action_type: (field_name, label, widget_type, extra_dict)
ACTION_FIELDS = {
    "go_to_scene":       [("target_scene",      "Scene Number",    "scene_num", {})],
    "wait":              [("duration",           "Seconds",         "dspin",    {"min":0.0,"max":999.0,"step":0.1})],
    "fade_in":           [("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "fade_out":          [("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "fade_to_color":     [("color",              "Color (#rrggbb)", "text",     {}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "flash_screen":      [("color",              "Color (#rrggbb)", "text",     {}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":5.0,"step":0.1})],
    "shake_screen":      [("intensity",          "Intensity",       "dspin",    {"min":1.0,"max":50.0,"step":1.0}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":10.0,"step":0.1})],
    "layer_show":        [("layer_name",         "Layer Name",      "text",     {})],
    "layer_hide":        [("layer_name",         "Layer Name",      "text",     {})],
    "layer_set_image":   [("layer_name",         "Layer Name",      "text",     {}),
                          ("image_id",           "Image",           "image",    {})],
    "play_music":        [("audio_id",           "Track",           "audio",    {}),
                          ("audio_loop",         "Loop",            "check",    {})],
    "set_music_volume":  [("volume",             "Volume (0-100)",  "spin",     {"min":0,"max":100})],
    "play_sfx":          [("audio_id",           "Sound Effect",    "audio",    {})],
    "set_speaker":       [("speaker_name",       "Name",            "text",     {})],
    "set_speaker_color": [("speaker_color",      "Color (#rrggbb)", "text",     {})],
    "set_dialogue_line": [("dialogue_line_index","Line (1-4)",      "spin",     {"min":1,"max":4}),
                          ("dialogue_text",      "Text",            "text",     {})],
    "set_choice_text":   [("choice_index",       "Button (1-4)",    "spin",     {"min":1,"max":4}),
                          ("choice_text",        "Label",           "text",     {})],
    "set_choice_dest":   [("choice_index",       "Button (1-4)",    "spin",     {"min":1,"max":4}),
                          ("choice_goto",        "Go to Scene",     "scene_num",{})],
    "set_variable":      [("var_name",           "Variable",        "text",     {}),
                          ("var_value",          "Value",           "text",     {})],
    "change_variable":   [("var_name",           "Variable",        "text",     {}),
                          ("var_operator",       "Operation",       "combo",    {"options":["add","subtract","multiply","divide"]}),
                          ("var_value",          "Amount",          "text",     {})],
    "increment_var":     [("var_name",           "Variable",        "text",     {}),
                          ("var_value",          "Amount",          "text",     {})],
    "set_flag":          [("bool_name",          "Flag",            "text",     {}),
                          ("bool_value",         "Value",           "check",    {})],
    "toggle_flag":       [("bool_name",          "Flag",            "text",     {})],
    "if_variable":       [("var_name",           "Variable",        "text",     {}),
                          ("var_compare",        "Condition",       "combo",    {"options":["==","!=",">","<",">=","<="]}),
                          ("var_value",          "Value",           "text",     {})],
    "if_flag":           [("bool_name",          "Flag",            "text",     {}),
                          ("bool_expected",      "Expected",        "check",    {})],
    "add_item":          [("item_name",          "Item Name",       "text",     {})],
    "remove_item":       [("item_name",          "Item Name",       "text",     {})],
    "if_has_item":       [("item_name",          "Item Name",       "text",     {})],
    "show_object":       [("object_def_id",      "Object",          "object",   {})],
    "hide_object":       [("object_def_id",      "Object",          "object",   {})],
    "set_opacity":       [("object_def_id",      "Object",          "object",   {}),
                          ("target_opacity",     "Opacity (0-1)",   "dspin",    {"min":0.0,"max":1.0,"step":0.05})],
    "fade_in_object":    [("object_def_id",      "Object",          "object",   {}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "fade_out_object":   [("object_def_id",      "Object",          "object",   {}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "move_to":           [("object_def_id",      "Object",          "object",   {}),
                          ("target_x",           "X",               "spin",     {"min":-999,"max":9999}),
                          ("target_y",           "Y",               "spin",     {"min":-999,"max":9999})],
    "move_to_variable":  [("object_def_id",      "Object",          "object",   {}),
                          ("var_name",           "X Variable",      "text",     {}),
                          ("var_source",         "Y Variable",      "text",     {})],
    "move_by":           [("object_def_id",      "Object",          "object",   {}),
                          ("offset_x",           "Offset X",        "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",           "Offset Y",        "spin",     {"min":-9999,"max":9999})],
    "slide_to":          [("object_def_id",      "Object",          "object",   {}),
                          ("target_x",           "X",               "spin",     {"min":-999,"max":9999}),
                          ("target_y",           "Y",               "spin",     {"min":-999,"max":9999}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "slide_by":          [("object_def_id",      "Object",          "object",   {}),
                          ("offset_x",           "Offset X",        "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",           "Offset Y",        "spin",     {"min":-9999,"max":9999}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "return_to_start":   [("object_def_id",      "Object",          "object",   {})],
    "set_scale":         [("object_def_id",      "Object",          "object",   {}),
                          ("target_scale",       "Scale",           "dspin",    {"min":0.01,"max":20.0,"step":0.1})],
    "scale_to":          [("object_def_id",      "Object",          "object",   {}),
                          ("target_scale",       "Scale",           "dspin",    {"min":0.01,"max":20.0,"step":0.1}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "set_rotation":      [("object_def_id",      "Object",          "object",   {}),
                          ("target_rotation",    "Degrees",         "dspin",    {"min":-360.0,"max":360.0,"step":1.0})],
    "rotate_to":         [("object_def_id",      "Object",          "object",   {}),
                          ("target_rotation",    "Degrees",         "dspin",    {"min":-360.0,"max":360.0,"step":1.0}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "rotate_by":         [("object_def_id",      "Object",          "object",   {}),
                          ("target_rotation",    "Degrees",         "dspin",    {"min":-360.0,"max":360.0,"step":1.0}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "spin":              [("object_def_id",      "Object",          "object",   {}),
                          ("spin_speed",         "Degrees/sec",     "dspin",    {"min":-3600.0,"max":3600.0,"step":10.0})],
    "stop_spin":         [("object_def_id",      "Object",          "object",   {})],
    "play_anim":         [("object_def_id",      "Object",          "object",   {})],
    "stop_anim":         [("object_def_id",      "Object",          "object",   {})],
    "set_frame":         [("object_def_id",      "Object",          "object",   {}),
                          ("frame_index",        "Frame Index",     "spin",     {"min":0,"max":999})],
    "set_anim_speed":    [("object_def_id",      "Object",          "object",   {}),
                          ("anim_fps",           "FPS",             "spin",     {"min":1,"max":60})],
    "create_object":     [("object_def_id",      "Object",          "object",   {}),
                          ("target_x",           "X",               "spin",     {"min":0,"max":9999}),
                          ("target_y",           "Y",               "spin",     {"min":0,"max":9999})],
    "destroy_object":    [("object_def_id",      "Object",          "object",   {})],
    "destroy_all_type":  [("object_def_id",      "Object Type",     "object",   {})],
    "enable_interact":   [("object_def_id",      "Object",          "object",   {})],
    "disable_interact":  [("object_def_id",      "Object",          "object",   {})],
    "set_char_sprite":   [("object_def_id",      "Character",       "object",   {}),
                          ("image_id",           "Image",           "image",    {})],
    "set_display_name":  [("object_def_id",      "Character",       "object",   {}),
                          ("speaker_name",       "Name",            "text",     {})],
    "char_enter":        [("object_def_id",      "Character",       "object",   {}),
                          ("var_value",          "From Edge",       "combo",    {"options":["left","right","top","bottom"]}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":5.0,"step":0.1})],
    "char_exit":         [("object_def_id",      "Character",       "object",   {}),
                          ("var_value",          "To Edge",         "combo",    {"options":["left","right","top","bottom"]}),
                          ("duration",           "Seconds",         "dspin",    {"min":0.0,"max":5.0,"step":0.1})],
    "char_react":        [("object_def_id",      "Character",       "object",   {}),
                          ("var_value",          "Reaction",        "combo",    {"options":["shake","bounce","nod","spin_once"]})],
    "set_label_text":    [("object_def_id",      "Label Object",    "object",   {}),
                          ("dialogue_text",      "New Text",        "text",     {})],
    "set_label_text_var":[("object_def_id",      "Label Object",    "object",   {}),
                          ("var_name",           "Variable",        "text",     {})],
    "set_label_color":   [("object_def_id",      "Label Object",    "object",   {}),
                          ("color",              "Color (#rrggbb)", "text",     {})],
    "set_label_size":    [("object_def_id",      "Label Object",    "object",   {}),
                          ("frame_index",        "Size (px)",       "spin",     {"min":4,"max":128})],
    "log_message":       [("log_message",        "Message",         "text",     {})],
    "four_way_movement": [("movement_speed",     "Speed (px/frame)","dspin",     {"min":0.1,"max":20.0,"step":0.1}),
                          ("movement_style",     "Style",           "combo",    {"options":["instant","slide"]})],
    "four_way_movement_collide": [
        ("movement_speed",      "Speed (px/frame)", "dspin",   {"min":0.1,"max":20.0,"step":0.1}),
        ("movement_style",      "Style",            "combo",  {"options":["instant","slide"]}),
        ("collision_layer_id",  "Collision Layer",  "collision_layer", {}),
        ("player_width",        "Player Width (px)","spin",   {"min":1,"max":512}),
        ("player_height",       "Player Height (px)","spin",  {"min":1,"max":512}),
    ],
    "two_way_movement": [
        ("movement_speed", "Speed (px/frame)", "dspin",  {"min":0.1,"max":20.0,"step":0.1}),
        ("two_way_axis",   "Axis",             "combo", {"options":["horizontal","vertical"]}),
        ("movement_style", "Style",            "combo", {"options":["instant","slide"]}),
    ],
    "two_way_movement_collide": [
        ("movement_speed",     "Speed (px/frame)",  "dspin",            {"min":0.1,"max":20.0,"step":0.1}),
        ("two_way_axis",       "Axis",               "combo",           {"options":["horizontal","vertical"]}),
        ("movement_style",     "Style",              "combo",           {"options":["instant","slide"]}),
        ("collision_layer_id", "Collision Layer",    "collision_layer", {}),
        ("player_width",       "Player Width (px)",  "spin",            {"min":1,"max":512}),
        ("player_height",      "Player Height (px)", "spin",            {"min":1,"max":512}),
    ],
    "fire_bullet": [
        ("bullet_direction", "Direction",        "combo", {"options":["right","left","up","down"]}),
        ("bullet_speed",     "Speed (px/frame)", "spin",  {"min":1,"max":40}),
    ],
    "collision_set_cell": [
        ("collision_layer_id", "Collision Layer",  "collision_layer", {}),
        ("grid_col",           "Column",           "spin",            {"min":0,"max":999}),
        ("grid_row",           "Row",              "spin",            {"min":0,"max":999}),
        ("grid_col_var",       "Col Variable",     "text",            {}),
        ("grid_row_var",       "Row Variable",     "text",            {}),
        ("collision_value",    "Value (0-1)",      "spin",            {"min":0,"max":1}),
    ],
    "collision_toggle_cell": [
        ("collision_layer_id", "Collision Layer",  "collision_layer", {}),
        ("grid_col",           "Column",           "spin",            {"min":0,"max":999}),
        ("grid_row",           "Row",              "spin",            {"min":0,"max":999}),
        ("grid_col_var",       "Col Variable",     "text",            {}),
        ("grid_row_var",       "Row Variable",     "text",            {}),
    ],
    "collision_get_cell": [
        ("collision_layer_id", "Collision Layer",  "collision_layer", {}),
        ("grid_col",           "Column",           "spin",            {"min":0,"max":999}),
        ("grid_row",           "Row",              "spin",            {"min":0,"max":999}),
        ("grid_col_var",       "Col Variable",     "text",            {}),
        ("grid_row_var",       "Row Variable",     "text",            {}),
        ("grid_result_var",    "Store in Variable","text",            {}),
    ],
    "camera_move_to":    [("camera_target_x","Target X","spin",{"min":-9999,"max":9999}),("camera_target_y","Target Y","spin",{"min":-9999,"max":9999}),("camera_duration","Duration (sec)","dspin",{"min":0.0,"max":30.0,"step":0.1}),("camera_easing","Easing","combo",{"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "camera_offset":     [("camera_offset_x","Offset X","spin",{"min":-9999,"max":9999}),("camera_offset_y","Offset Y","spin",{"min":-9999,"max":9999}),("camera_duration","Duration (sec)","dspin",{"min":0.0,"max":30.0,"step":0.1}),("camera_easing","Easing","combo",{"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "camera_follow":     [("camera_follow_target_def_id","Object to Follow","object",{}),("camera_follow_offset_x","Offset X","spin",{"min":-999,"max":999}),("camera_follow_offset_y","Offset Y","spin",{"min":-999,"max":999})],
    "camera_stop_follow":[],
    "camera_reset":      [("camera_duration","Duration (sec)","dspin",{"min":0.0,"max":30.0,"step":0.1}),("camera_easing","Easing","combo",{"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "camera_shake":      [("shake_intensity","Intensity","dspin",{"min":1.0,"max":50.0,"step":1.0}),("shake_duration","Duration (sec)","dspin",{"min":0.0,"max":10.0,"step":0.1})],
    "camera_set_zoom":   [("camera_zoom_target","Zoom Level","dspin",{"min":0.25,"max":4.0,"step":0.05})],
    "camera_zoom_to":    [("camera_zoom_target","Zoom Level","dspin",{"min":0.25,"max":4.0,"step":0.05}),("camera_zoom_duration","Duration (sec)","dspin",{"min":0.0,"max":30.0,"step":0.1}),("camera_zoom_easing","Easing","combo",{"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "ani_play":          [("object_def_id","Target Object","object",{})],
    "ani_pause":         [("object_def_id","Target Object","object",{})],
    "ani_stop":          [("object_def_id","Target Object","object",{})],
    "ani_set_frame":     [("object_def_id","Target Object","object",{}),("ani_target_frame","Frame","spin",{"min":0,"max":9999})],
    "ani_set_speed":     [("object_def_id","Target Object","object",{}),("ani_fps","FPS","spin",{"min":1,"max":120})],
    "emit_signal":       [("signal_name",        "Signal",          "signal",   {})],
    "if_button_pressed": [("button",             "Button",          "combo",    {"options":["cross","circle","square","triangle","dpad_up","dpad_down","dpad_left","dpad_right","l","r","start","select","left_stick_up","left_stick_down","left_stick_left","left_stick_right","right_stick_up","right_stick_down","right_stick_left","right_stick_right"]})],
    "if_button_held":    [("button",             "Button",          "combo",    {"options":["cross","circle","square","triangle","dpad_up","dpad_down","dpad_left","dpad_right","l","r","start","select","left_stick_up","left_stick_down","left_stick_left","left_stick_right","right_stick_up","right_stick_down","right_stick_left","right_stick_right"]})],
    "if_button_released":[("button",             "Button",          "combo",    {"options":["cross","circle","square","triangle","dpad_up","dpad_down","dpad_left","dpad_right","l","r","start","select","left_stick_up","left_stick_down","left_stick_left","left_stick_right","right_stick_up","right_stick_down","right_stick_left","right_stick_right"]})],
    "add_to_group": [
        ("object_def_id", "Object",     "object", {}),
        ("group_name",    "Group Name", "text",   {}),
    ],
    "remove_from_group": [
        ("object_def_id", "Object",     "object", {}),
        ("group_name",    "Group Name", "text",   {}),
    ],
    "call_action_on_group": [
        ("group_name",        "Group Name",    "text",  {}),
        ("group_action_type", "Action to Run", "combo", {"options": [
            "show_object", "hide_object", "destroy_object",
            "move_to", "move_by", "set_opacity", "set_scale", "set_rotation",
            "enable_interact", "disable_interact",
            "emit_signal",
        ]}),
        ("target_x",      "Target X",   "spin",  {"min": -9999, "max": 9999}),
        ("target_y",      "Target Y",   "spin",  {"min": -9999, "max": 9999}),
        ("offset_x",      "Offset X",   "spin",  {"min": -9999, "max": 9999}),
        ("offset_y",      "Offset Y",   "spin",  {"min": -9999, "max": 9999}),
        ("target_opacity","Opacity",    "dspin", {"min": 0.0, "max": 1.0, "step": 0.05}),
        ("target_scale",  "Scale",      "dspin", {"min": 0.01, "max": 20.0, "step": 0.1}),
        ("target_rotation","Degrees",   "dspin", {"min": -360.0, "max": 360.0, "step": 1.0}),
    ],
    "if_in_group": [
        ("object_def_id", "Object",     "object", {}),
        ("group_name",    "Group Name", "text",   {}),
    ],
}


def _action_display_name(action_type: str) -> str:
    for actions in ACTION_PALETTE.values():
        for at, name, _ in actions:
            if at == action_type:
                return name
    return action_type


def _action_summary(action: BehaviorAction) -> str:
    name = _action_display_name(action.action_type)
    t = action.action_type
    details = {
        "go_to_scene":       f"→ scene {action.target_scene}",
        "wait":              f"{action.duration}s",
        "fade_in":           f"{action.duration}s",
        "fade_out":          f"{action.duration}s",
        "fade_to_color":     f"{action.color} {action.duration}s",
        "shake_screen":      f"x{action.intensity} {action.duration}s",
        "play_music":        action.audio_id or "?",
        "play_sfx":          action.audio_id or "?",
        "set_music_volume":  str(action.volume),
        "set_speaker":       action.speaker_name or "?",
        "set_dialogue_line": f"#{action.dialogue_line_index}: {action.dialogue_text[:18]}",
        "set_variable":      f"{action.var_name} = {action.var_value}",
        "change_variable":   f"{action.var_name} {action.var_operator} {action.var_value}",
        "increment_var":     f"{action.var_name} += {action.var_value or 1}",
        "set_flag":          f"{action.bool_name} = {action.bool_value}",
        "toggle_flag":       action.bool_name,
        "if_variable":       f"{action.var_name} {action.var_compare} {action.var_value}",
        "if_flag":           f"{action.bool_name}=={action.bool_expected}",
        "add_item":          action.item_name,
        "remove_item":       action.item_name,
        "if_has_item":       action.item_name,
        "show_object":       action.object_def_id or "?",
        "hide_object":       action.object_def_id or "?",
        "layer_show":        action.layer_name or "?",
        "layer_hide":        action.layer_name or "?",
        "layer_set_image":   f"{action.layer_name or '?'} → img",
        "move_to":           f"({action.target_x},{action.target_y})",
        "move_to_variable":  f"({action.var_name or 'x'},{action.var_source or 'y'})",
        "slide_to":          f"({action.target_x},{action.target_y}) {action.duration}s",
        "move_by":           f"({action.offset_x},{action.offset_y})",
        "slide_by":          f"({action.offset_x},{action.offset_y}) {action.duration}s",
        "set_scale":         str(action.target_scale),
        "scale_to":          f"{action.target_scale} {action.duration}s",
        "set_rotation":      f"{action.target_rotation}°",
        "rotate_to":         f"{action.target_rotation}° {action.duration}s",
        "spin":              f"{action.spin_speed}°/s",
        "create_object":     f"({action.target_x},{action.target_y})",
        "char_enter":        f"from {action.var_value}",
        "char_exit":         f"to {action.var_value}",
        "char_react":        action.var_value,
        "set_label_text":    action.dialogue_text[:20],
        "set_label_text_var":action.var_name,
        "set_label_color":   action.color,
        "set_label_size":    str(action.frame_index),
        "log_message":       action.log_message[:20],
        "four_way_movement": f"speed {getattr(action, 'movement_speed', 4)}px  {getattr(action, 'movement_style', 'instant')}",
        "four_way_movement_collide": f"speed {getattr(action, 'movement_speed', 4)}px  collide",
        "two_way_movement":          f"{getattr(action,'two_way_axis','horizontal')}  speed {getattr(action,'movement_speed',4)}px",
        "two_way_movement_collide":  f"{getattr(action,'two_way_axis','horizontal')}  speed {getattr(action,'movement_speed',4)}px  collide",
        "fire_bullet":               f"→ {getattr(action,'bullet_direction','right')}  {getattr(action,'bullet_speed',6)}px/f",
        "collision_set_cell":        f"cell ({getattr(action,'grid_col',0)},{getattr(action,'grid_row',0)}) = {getattr(action,'collision_value',1)}",
        "collision_toggle_cell":     f"toggle ({getattr(action,'grid_col',0)},{getattr(action,'grid_row',0)})",
        "collision_get_cell":        f"({getattr(action,'grid_col',0)},{getattr(action,'grid_row',0)}) → {getattr(action,'grid_result_var','value') or 'value'}",
        "camera_move_to":    f"({getattr(action, 'camera_target_x', 0)},{getattr(action, 'camera_target_y', 0)})",
        "camera_offset":     f"({getattr(action, 'camera_offset_x', 0)},{getattr(action, 'camera_offset_y', 0)})",
        "camera_follow":     getattr(action, 'camera_follow_target_def_id', '') or "?",
        "camera_stop_follow":"",
        "camera_reset":      "",
        "camera_shake":      f"x{getattr(action, 'shake_intensity', 5)}",
        "camera_set_zoom":   f"zoom={getattr(action, 'camera_zoom_target', 1.0)}",
        "camera_zoom_to":    f"zoom={getattr(action, 'camera_zoom_target', 1.0)} over {getattr(action, 'camera_zoom_duration', 0.0)}s",
        "ani_play":          getattr(action, 'object_def_id', '') or "self",
        "ani_pause":         getattr(action, 'object_def_id', '') or "self",
        "ani_stop":          getattr(action, 'object_def_id', '') or "self",
        "ani_set_frame":     f"{getattr(action, 'object_def_id', '') or 'self'} → {getattr(action, 'ani_target_frame', 0)}",
        "ani_set_speed":     f"{getattr(action, 'object_def_id', '') or 'self'} → {getattr(action, 'ani_fps', 12)} fps",
        "emit_signal":       f"📡 {getattr(action, 'signal_name', '?')}",
        "if_button_pressed": f"{getattr(action, 'button', '?')}",
        "if_button_held":    f"{getattr(action, 'button', '?')}",
        "if_button_released":f"{getattr(action, 'button', '?')}",
        "add_to_group":         f"{action.object_def_id or '?'} → group '{action.group_name}'",
        "remove_from_group":    f"{action.object_def_id or '?'} ← group '{action.group_name}'",
        "call_action_on_group": f"group '{action.group_name}' → {action.group_action_type}",
        "if_in_group":          f"{action.object_def_id or '?'} in '{action.group_name}'?",
    }
    detail = details.get(t, "")
    return f"{name}  {detail}" if detail else name


# ─────────────────────────────────────────────────────────────
#  STYLE HELPERS
# ─────────────────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {TEXT_DIM}; font-size: 10px; font-weight: 700;
        letter-spacing: 1.5px; padding: 8px 0 3px 0; background: transparent;
    """)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
    return f

def _list_style():
    return f"""
        QListWidget {{
            background: {SURFACE}; border: 1px solid {BORDER};
            border-radius: 4px; color: {TEXT}; outline: none;
        }}
        QListWidget::item {{
            padding: 4px 8px; border-radius: 3px;
            border-bottom: 1px solid {BORDER};
        }}
        QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
        QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
    """
def _field_style() -> str:
    return f"""
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {SURFACE}; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 4px;
            padding: 4px 7px; font-size: 12px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {ACCENT};
        }}
        QComboBox::drop-down {{ border: none; width: 18px; }}
        QComboBox QAbstractItemView {{
            background: {SURFACE2}; color: {TEXT};
            border: 1px solid {BORDER};
            selection-background-color: {ACCENT};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            background: {SURFACE2}; border: none; width: 14px;
        }}
        QCheckBox {{ color: {TEXT}; font-size: 12px; spacing: 6px; }}
        QCheckBox::indicator {{
            width: 13px; height: 13px;
            border: 1px solid {BORDER}; border-radius: 3px; background: {SURFACE};
        }}
        QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QSlider::groove:horizontal {{
            height: 4px; background: {SURFACE2}; border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {ACCENT}; width: 12px; height: 12px;
            border-radius: 6px; margin: -4px 0;
        }}
        QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    """


def _small_btn(label: str, tooltip: str = "", accent: bool = False, danger: bool = False) -> QPushButton:
    b = QPushButton(label)
    b.setToolTip(tooltip)
    b.setFixedSize(26, 26)
    
    # We use background-color specifically to ensure it overrides the generic stylesheet
    if accent:
        _ac = _current_theme["ACCENT"]
        b.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {_ac}; 
                color: white; 
                border: none;
                border-radius: 4px; 
                font-size: 13px; 
                font-weight: 700; 
                padding: 0;
            }}
            QPushButton:hover {{ background-color: {_ac}cc; }}
        """)
        _accent_buttons.append(b)
    elif danger:
        b.setStyleSheet(f"""
            QPushButton {{ 
                background-color: transparent; 
                color: {DANGER};
                border: 1px solid {DANGER}; 
                border-radius: 4px; 
                font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover {{ background-color: {DANGER}; color: white; }}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {SURFACE2}; 
                color: {TEXT};
                border: 1px solid {BORDER}; 
                border-radius: 4px; 
                font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover {{ 
                background-color: {ACCENT}; 
                border-color: {ACCENT}; 
                color: white; 
            }}
        """)
    return b

#--------------------------------------------------------------
#class for collapsable inspector shit
#-----------------------------------------------------------------


# Paste this BEFORE 'class ActionPickerDialog(QDialog):'

class CollapsibleBox(QWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.toggle_btn = QPushButton(f"▼  {title}")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left; background: transparent; border: none;
                color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
                padding: 8px 0 4px 0;
            }}
            QPushButton:hover {{ color: {ACCENT}; }}
        """)
        self.toggle_btn.toggled.connect(self._on_toggle)

        self.content_area = QWidget()
        self.v_layout = QVBoxLayout(self.content_area)
        self.v_layout.setContentsMargins(0, 0, 0, 4)
        self.v_layout.setSpacing(4)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.toggle_btn)
        lay.addWidget(self.content_area)

    def _on_toggle(self, checked):
        self.content_area.setVisible(checked)
        self.toggle_btn.setText(f"{'▼' if checked else '▶'}  {self.toggle_btn.text()[3:]}")

    def addWidget(self, widget):
        self.v_layout.addWidget(widget)

    def addLayout(self, layout):
        self.v_layout.addLayout(layout)



# ─────────────────────────────────────────────────────────────
#  TRIGGER PICKER DIALOG
# ─────────────────────────────────────────────────────────────

class TriggerPickerDialog(QDialog):
    def __init__(self, available_triggers: list[tuple], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Trigger")
        self.setModal(True)
        self.setMinimumSize(540, 360)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        self._triggers = available_triggers
        self._selected_code: str | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; width: 1px; }}")

        # Category list (left)
        left = QWidget()
        left.setStyleSheet(f"background: {SURFACE};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        cat_hdr = QLabel("CATEGORY")
        cat_hdr.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
            padding: 8px 10px; background: {PANEL}; border-bottom: 1px solid {BORDER};
        """)
        lv.addWidget(cat_hdr)
        self.cat_list = QListWidget()
        self.cat_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: none; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        # Build unique categories preserving order
        seen = []
        for tup in self._triggers:
            cat = tup[2]
            if cat not in seen:
                seen.append(cat)
        for cat in seen:
            self.cat_list.addItem(cat)
        self.cat_list.currentRowChanged.connect(self._on_cat_changed)
        lv.addWidget(self.cat_list)
        splitter.addWidget(left)

        # Trigger list + description (right)
        right = QWidget()
        right.setStyleSheet(f"background: {DARK};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        trg_hdr = QLabel("TRIGGERS")
        trg_hdr.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
            padding: 8px 10px; background: {PANEL}; border-bottom: 1px solid {BORDER};
        """)
        rv.addWidget(trg_hdr)
        self.trg_list = QListWidget()
        self.trg_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: none; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        self.trg_list.currentRowChanged.connect(self._on_trg_changed)
        self.trg_list.doubleClicked.connect(self.accept)
        rv.addWidget(self.trg_list, stretch=1)
        self.desc_lbl = QLabel("")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 11px; font-style: italic;
            padding: 8px 12px; background: {PANEL}; border-top: 1px solid {BORDER};
        """)
        self.desc_lbl.setFixedHeight(50)
        rv.addWidget(self.desc_lbl)
        splitter.addWidget(right)
        splitter.setSizes([155, 365])
        root.addWidget(splitter, stretch=1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(f"color: {TEXT};")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        if self.cat_list.count():
            self.cat_list.setCurrentRow(0)

    def _on_cat_changed(self, row: int):
        self.trg_list.clear()
        if row < 0:
            return
        cat = self.cat_list.item(row).text()
        for tup in self._triggers:
            code, label, tcat, desc = tup
            if tcat == cat:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, (code, desc))
                self.trg_list.addItem(item)
        if self.trg_list.count():
            self.trg_list.setCurrentRow(0)

    def _on_trg_changed(self, row: int):
        item = self.trg_list.item(row)
        if item:
            code, desc = item.data(Qt.ItemDataRole.UserRole)
            self.desc_lbl.setText(desc)
            self._selected_code = code
        else:
            self.desc_lbl.setText("")
            self._selected_code = None

    def selected_trigger(self) -> str | None:
        return self._selected_code


# ─────────────────────────────────────────────────────────────
#  ACTION PICKER DIALOG
# ─────────────────────────────────────────────────────────────

class ActionPickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Action")
        self.setModal(True)
        self.setMinimumSize(540, 380)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        self._selected_type: str | None = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; width: 1px; }}")

        # Category list
        left = QWidget()
        left.setStyleSheet(f"background: {SURFACE};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        cat_hdr = QLabel("CATEGORY")
        cat_hdr.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
            padding: 8px 10px; background: {PANEL}; border-bottom: 1px solid {BORDER};
        """)
        lv.addWidget(cat_hdr)
        self.cat_list = QListWidget()
        self.cat_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: none; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        for cat in ACTION_PALETTE:
            self.cat_list.addItem(cat)
        self.cat_list.currentRowChanged.connect(self._on_cat_changed)
        lv.addWidget(self.cat_list)
        splitter.addWidget(left)

        # Action list + description
        right = QWidget()
        right.setStyleSheet(f"background: {DARK};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        act_hdr = QLabel("ACTIONS")
        act_hdr.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
            padding: 8px 10px; background: {PANEL}; border-bottom: 1px solid {BORDER};
        """)
        rv.addWidget(act_hdr)
        self.act_list = QListWidget()
        self.act_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: none; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        self.act_list.currentRowChanged.connect(self._on_act_changed)
        self.act_list.doubleClicked.connect(self.accept)
        rv.addWidget(self.act_list, stretch=1)
        self.desc_lbl = QLabel("")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 11px; font-style: italic;
            padding: 8px 12px; background: {PANEL}; border-top: 1px solid {BORDER};
        """)
        self.desc_lbl.setFixedHeight(50)
        rv.addWidget(self.desc_lbl)
        splitter.addWidget(right)
        splitter.setSizes([155, 365])
        root.addWidget(splitter, stretch=1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(f"color: {TEXT};")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        if self.cat_list.count():
            self.cat_list.setCurrentRow(0)

    def _on_cat_changed(self, row: int):
        self.act_list.clear()
        if row < 0:
            return
        cat = self.cat_list.item(row).text()
        for at, name, desc in ACTION_PALETTE.get(cat, []):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, (at, desc))
            self.act_list.addItem(item)
        if self.act_list.count():
            self.act_list.setCurrentRow(0)

    def _on_act_changed(self, row: int):
        item = self.act_list.item(row)
        if item:
            at, desc = item.data(Qt.ItemDataRole.UserRole)
            self.desc_lbl.setText(desc)
            self._selected_type = at
        else:
            self.desc_lbl.setText("")
            self._selected_type = None

    def selected_action_type(self) -> str | None:
        return self._selected_type


# ─────────────────────────────────────────────────────────────
#  BRANCH EDITOR  (mini action list for true/false branches)
# ─────────────────────────────────────────────────────────────

BRANCH_TYPES = {
    "if_variable",
    "if_flag",
    "if_has_item",
    "if_save_exists",
    "if_button_pressed",
    "if_button_held",
    "if_button_released",
}
SIGNAL_TRIGGER = "on_signal"
SIGNAL_ACTION  = "emit_signal"


class BranchEditorWidget(QWidget):
    """
    A compact action list for editing one branch (true_actions or false_actions)
    of a conditional BehaviorAction.  Does NOT nest further branch editors.
    """
    changed = Signal()

    def __init__(self, label: str, branch_field: str, parent=None):
        """
        label        — displayed header, e.g. "✔ TRUE branch"
        branch_field — attribute name on BehaviorAction: "true_actions" or "false_actions"
        """
        super().__init__(parent)
        self._action:       BehaviorAction | None = None
        self._project:      Project        | None = None
        self._branch_field  = branch_field
        self._build_ui(label)

    def _build_ui(self, label: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(2)

        # Header row
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700;"
            f" letter-spacing: 1.2px; background: transparent;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()
        ab = _small_btn("+", "Add action to branch", accent=True)
        ab.clicked.connect(self._add)
        db = _small_btn("x", "Remove selected action", danger=True)
        db.clicked.connect(self._del)
        ub = _small_btn("↑", "Move up")
        ub.clicked.connect(self._up)
        dnb = _small_btn("↓", "Move down")
        dnb.clicked.connect(self._dn)
        for b in (ab, db, ub, dnb):
            hdr.addWidget(b)
        root.addLayout(hdr)

        self._list = QListWidget()
        self._list.setFixedHeight(72)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none;
            }}
            QListWidget::item {{
                padding: 3px 7px; border-bottom: 1px solid {BORDER}; font-size: 11px;
            }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        root.addWidget(self._list)

    # ── public API ────────────────────────────────────────────

    def load(self, action: BehaviorAction, project: Project):
        self._action  = action
        self._project = project
        self._refresh()

    def clear(self):
        self._action  = None
        self._project = None
        self._list.clear()

    # ── internals ─────────────────────────────────────────────

    def _branch(self) -> list:
        if self._action is None:
            return []
        lst = getattr(self._action, self._branch_field, None)
        if lst is None:
            setattr(self._action, self._branch_field, [])
            lst = getattr(self._action, self._branch_field)
        return lst

    def _refresh(self):
        self._list.blockSignals(True)
        prev = self._list.currentRow()
        self._list.clear()
        for i, a in enumerate(self._branch()):
            self._list.addItem(f"{i+1:02d}. {_action_summary(a)}")
        self._list.blockSignals(False)
        self._list.setCurrentRow(max(0, min(prev, self._list.count() - 1)))

    def _add(self):
        if self._action is None:
            return
        dlg = ActionPickerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        at = dlg.selected_action_type()
        if not at:
            return
        self._branch().append(BehaviorAction(action_type=at))
        self._refresh()
        self._list.setCurrentRow(len(self._branch()) - 1)
        self.changed.emit()

    def _del(self):
        row = self._list.currentRow()
        branch = self._branch()
        if 0 <= row < len(branch):
            branch.pop(row)
            self._refresh()
            self.changed.emit()

    def _up(self):
        row = self._list.currentRow()
        branch = self._branch()
        if row > 0:
            branch[row], branch[row - 1] = branch[row - 1], branch[row]
            self._refresh()
            self._list.setCurrentRow(row - 1)
            self.changed.emit()

    def _dn(self):
        row = self._list.currentRow()
        branch = self._branch()
        if 0 <= row < len(branch) - 1:
            branch[row], branch[row + 1] = branch[row + 1], branch[row]
            self._refresh()
            self._list.setCurrentRow(row + 1)
            self.changed.emit()


# ─────────────────────────────────────────────────────────────
#  ACTION DETAIL PANEL
# ─────────────────────────────────────────────────────────────

class ActionDetailPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action:  BehaviorAction | None = None
        self._project: Project        | None = None
        self._suppress = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(3)
        self.setStyleSheet(f"background: {DARK};")
        self._show_placeholder()

    def _show_placeholder(self):
        lbl = QLabel("Select an action to configure it.")
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 4px 0;")
        self._layout.addWidget(lbl)
        self._layout.addStretch()

    def load(self, action: BehaviorAction, project: Project):
        self._action  = action
        self._project = project
        self._rebuild()

    def clear(self):
        self._action = None
        self._rebuild()

    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._action is None:
            self._show_placeholder()
            return

        fields = ACTION_FIELDS.get(self._action.action_type, [])
        if not fields:
            lbl = QLabel("No configurable parameters.")
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; padding: 4px 0;")
            self._layout.addWidget(lbl)
            self._layout.addStretch()
            return

        fs = _field_style()
        self._suppress = True

        for field_name, label_text, wtype, extra in fields:
            lbl = QLabel(label_text + ":")
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
            self._layout.addWidget(lbl)
            cur = getattr(self._action, field_name, None)

            if wtype == "text":
                w = QLineEdit(str(cur or ""))
                w.setStyleSheet(fs)
                w.textChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            elif wtype == "spin":
                w = QSpinBox()
                w.setStyleSheet(fs)
                w.setRange(extra.get("min", 0), extra.get("max", 9999))
                try:
                    w.setValue(int(cur or 0))
                except Exception:
                    pass
                w.valueChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            elif wtype == "dspin":
                w = QDoubleSpinBox()
                w.setStyleSheet(fs)
                w.setRange(extra.get("min", 0.0), extra.get("max", 999.0))
                w.setSingleStep(extra.get("step", 0.1))
                w.setDecimals(2)
                try:
                    w.setValue(float(cur or 0.0))
                except Exception:
                    pass
                w.valueChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            elif wtype == "check":
                w = QCheckBox()
                w.setStyleSheet(fs)
                w.setChecked(bool(cur))
                w.stateChanged.connect(lambda v, fn=field_name: self._set(fn, bool(v)))

            elif wtype == "combo":
                w = QComboBox()
                w.setStyleSheet(fs)
                options = extra.get("options", [])
                for opt in options:
                    w.addItem(opt)
                if cur in options:
                    w.setCurrentText(str(cur))
                else:
                    # cur is not a valid option for this combo (e.g. var_operator="set"
                    # on a change_variable action) — snap to first option and persist it
                    # immediately so the model stays in sync with what the widget shows.
                    if options:
                        w.setCurrentIndex(0)
                        setattr(self._action, field_name, options[0])
                w.currentTextChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            elif wtype in ("audio", "image", "object"):
                w = QComboBox()
                w.setStyleSheet(fs)
                w.addItem("-- none --", None)
                if self._project:
                    if wtype == "audio":
                        items = [(a.name, a.id) for a in self._project.audio]
                    elif wtype == "image":
                        items = [(i.name, i.id) for i in self._project.images]
                    else:
                        items = [(o.name, o.id) for o in self._project.object_defs]
                    for nm, id_ in items:
                        w.addItem(nm, id_)
                for i in range(w.count()):
                    if w.itemData(i) == cur:
                        w.setCurrentIndex(i)
                        break
                w.currentIndexChanged.connect(lambda _, fn=field_name, ww=w: self._set(fn, ww.currentData()))

            elif wtype == "scene_num":
                w = QSpinBox()
                w.setStyleSheet(fs)
                w.setRange(1, 999)
                try:
                    w.setValue(int(cur or 1))
                except Exception:
                    pass
                w.valueChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            elif wtype == "signal":
                w = QComboBox()
                w.setStyleSheet(fs)
                w.addItem("-- none --", "")
                if self._project:
                    for sig in self._project.game_data.signals:
                        w.addItem(sig.name, sig.name)
                for i in range(w.count()):
                    if w.itemData(i) == cur:
                        w.setCurrentIndex(i)
                        break
                w.currentIndexChanged.connect(lambda _, fn=field_name, ww=w: self._set(fn, ww.currentData() or ""))

            elif wtype == "collision_layer":
                w = QComboBox()
                w.setStyleSheet(fs)
                w.addItem("-- none --", "")
                if self._project:
                    for scene in self._project.scenes:
                        for comp in scene.components:
                            if comp.component_type == "CollisionLayer":
                                lname = comp.config.get("layer_name", "") or comp.id
                                w.addItem(lname, comp.id)
                matched = False
                for i in range(w.count()):
                    if w.itemData(i) == cur:
                        w.setCurrentIndex(i)
                        matched = True
                        break
                # If no layer selected yet and at least one exists, default to it
                if not matched and not cur and w.count() > 1:
                    w.setCurrentIndex(1)
                    if self._action:
                        setattr(self._action, field_name, w.itemData(1) or "")
                w.currentIndexChanged.connect(lambda _, fn=field_name, ww=w: self._set(fn, ww.currentData() or ""))

            else:
                w = QLineEdit(str(cur or ""))
                w.setStyleSheet(fs)
                w.textChanged.connect(lambda v, fn=field_name: self._set(fn, v))

            self._layout.addWidget(w)

        # Branch editors for if_variable / if_flag / if_has_item / if_save_exists
        if self._action.action_type in BRANCH_TYPES:
            self._layout.addWidget(_divider())
            true_editor  = BranchEditorWidget("✔  TRUE branch",  "true_actions",  self)
            false_editor = BranchEditorWidget("✘  FALSE branch", "false_actions", self)
            true_editor.load(self._action, self._project)
            false_editor.load(self._action, self._project)
            true_editor.changed.connect(self.changed)
            false_editor.changed.connect(self.changed)
            self._layout.addWidget(true_editor)
            self._layout.addWidget(false_editor)

        self._layout.addStretch()
        self._suppress = False

    def _set(self, field_name: str, value):
        if self._suppress or self._action is None:
            return
        setattr(self._action, field_name, value)
        self.changed.emit()


# ─────────────────────────────────────────────────────────────
#  SCENE COMPONENTS PANEL
# ─────────────────────────────────────────────────────────────

class SceneComponentsPanel(QWidget):
    changed = Signal()
    tile_layer_selected = Signal(str)  # emits "__tilelayer__:{comp_id}:{tileset_id}" and generic editor-tool tokens
    path_draw_requested = Signal(str)  # emits component id of the path-backed component to draw

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene:   Scene   | None = None
        self._project: Project | None = None
        self._suppress = False
        self._active_path_component_id: str | None = None
        self._grid_tool_shapes: dict[tuple[str, str], tuple[int, int]] = {}
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(3)
        lbl = QLabel("No scene loaded.")
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._root.addWidget(lbl)

    def load(self, scene: Scene, project: Project):
        self._scene   = scene
        self._project = project
        self._rebuild()

    def clear(self):
        self._scene = None
        self._rebuild()

    def set_active_path_component_id(self, component_id: str | None):
        if self._active_path_component_id == component_id:
            return
        self._active_path_component_id = component_id
        if self._scene is not None:
            self._rebuild()

    def _sync_tool_shape_cache(self):
        self._grid_tool_shapes = {}
        if self._scene is None:
            return
        for comp in self._scene.components:
            tool = _component_editor_tool(self._project, comp, "grid_map")
            if not tool:
                continue
            width_key = str(tool.get("width_key", "map_width"))
            height_key = str(tool.get("height_key", "map_height"))
            data_key = str(tool.get("data_key", "tiles"))
            width = max(1, int(comp.config.get(width_key, 1) or 1))
            height = max(1, int(comp.config.get(height_key, 1) or 1))
            self._grid_tool_shapes[(comp.id, data_key)] = (width, height)

    def _resize_grid_tool_data(self, comp: SceneComponent, tool: dict, old_width: int, old_height: int):
        data_key = str(tool.get("data_key", "tiles"))
        width_key = str(tool.get("width_key", "map_width"))
        height_key = str(tool.get("height_key", "map_height"))
        new_width = max(1, int(comp.config.get(width_key, old_width) or old_width or 1))
        new_height = max(1, int(comp.config.get(height_key, old_height) or old_height or 1))
        old_width = max(1, int(old_width or 1))
        old_height = max(1, int(old_height or 1))
        old_values = list(comp.config.get(data_key, []) or [])
        default_cell = tool.get("default_cell", 0)
        new_values = []
        for row in range(new_height):
            for col in range(new_width):
                if row < old_height and col < old_width:
                    old_idx = row * old_width + col
                    if old_idx < len(old_values):
                        new_values.append(old_values[old_idx])
                        continue
                new_values.append(default_cell)
        comp.config[data_key] = new_values
        self._grid_tool_shapes[(comp.id, data_key)] = (new_width, new_height)

    def _grid_tool_info_text(self, comp: SceneComponent, tool: dict) -> str:
        data_key = str(tool.get("data_key", "tiles"))
        width_key = str(tool.get("width_key", "map_width"))
        height_key = str(tool.get("height_key", "map_height"))
        cell_size_key = str(tool.get("cell_size_key", "tile_size"))
        width = max(1, int(comp.config.get(width_key, 1) or 1))
        height = max(1, int(comp.config.get(height_key, 1) or 1))
        cell_size = max(1, int(comp.config.get(cell_size_key, 1) or 1))
        values = list(comp.config.get(data_key, []) or [])
        if str(tool.get("mode", "binary")) == "binary":
            active_value = tool.get("active_value", 1)
            painted = sum(1 for value in values if value == active_value)
            return f"{width}x{height} cells  •  cell {cell_size}px  •  {painted} solid"
        painted = sum(1 for value in values if int(value or 0) > 0)
        avg_value = int(sum(int(value or 0) for value in values) / painted) if painted else 0
        return f"{width}x{height} cells  •  cell {cell_size}px  •  {painted} painted  •  avg {avg_value}"

    def _on_plugin_field_changed(self, comp: SceneComponent, descriptor: dict, field_key: str):
        for tool in descriptor.get("editor_tools", []) or []:
            if str(tool.get("kind", "")) != "grid_map":
                continue
            width_key = str(tool.get("width_key", "map_width"))
            height_key = str(tool.get("height_key", "map_height"))
            data_key = str(tool.get("data_key", "tiles"))
            if field_key not in {width_key, height_key}:
                continue
            old_width, old_height = self._grid_tool_shapes.get(
                (comp.id, data_key),
                (
                    max(1, int(comp.config.get(width_key, 1) or 1)),
                    max(1, int(comp.config.get(height_key, 1) or 1)),
                ),
            )
            self._resize_grid_tool_data(comp, tool, old_width, old_height)

    def _emit_grid_tool_request(self, comp: SceneComponent, mode: str):
        self.tile_layer_selected.emit(f"__gridtool__:{comp.id}:{mode}")

    def _add_grid_tool_buttons(self, comp: SceneComponent, tool: dict, *, accent_color: str | None = None):
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.setContentsMargins(0, 4, 0, 6)

        paint_label = str(tool.get("paint_label", "Paint"))
        erase_label = str(tool.get("erase_label", "Erase"))
        color = accent_color or str(tool.get("overlay_color", "") or "#c0392b")
        hover = color + "cc" if color.startswith("#") and len(color) == 7 else color

        paint_btn = QPushButton(paint_label)
        paint_btn.setStyleSheet(f"""
            QPushButton {{ background: {color}; color: white; border: none;
                border-radius: 4px; padding: 6px 10px; font-size: 11px; font-weight: 600; }}
            QPushButton:hover {{ background: {hover}; }}
        """)
        paint_btn.clicked.connect(lambda _, c=comp: self._emit_grid_tool_request(c, "paint"))

        erase_btn = QPushButton(erase_label)
        erase_btn.setStyleSheet(f"""
            QPushButton {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 4px; padding: 6px 10px; font-size: 11px; font-weight: 600; }}
            QPushButton:hover {{ background: {BORDER}; }}
        """)
        erase_btn.clicked.connect(lambda _, c=comp: self._emit_grid_tool_request(c, "erase"))

        btn_row.addWidget(paint_btn)
        btn_row.addWidget(erase_btn)
        self._root.addLayout(btn_row)

    def _add_path_tool_controls(self, comp: SceneComponent, tool: dict):
        name_key = str(tool.get("name_key", "path_name"))
        closed_key = str(tool.get("closed_key", "closed"))
        points_key = str(tool.get("points_key", "points"))

        lbl = QLabel("Path Name:")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
        self._root.addWidget(lbl)
        name_edit = QLineEdit(comp.config.get(name_key, "New Path"))
        name_edit.setStyleSheet(_field_style())
        name_edit.setPlaceholderText("Path name…")
        name_edit.textChanged.connect(lambda v, c=comp, k=name_key: self._cfg(c, k, v))
        self._root.addWidget(name_edit)

        closed_chk = QCheckBox("Closed Loop")
        closed_chk.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        closed_chk.setChecked(bool(comp.config.get(closed_key, False)))
        closed_chk.toggled.connect(lambda v, c=comp, k=closed_key: self._cfg(c, k, v))
        self._root.addWidget(closed_chk)

        pts = comp.config.get(points_key, []) or []
        pt_lbl = QLabel(f"{len(pts)} point{'s' if len(pts) != 1 else ''}")
        pt_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; background: transparent;")
        self._root.addWidget(pt_lbl)

        draw_btn = QPushButton(f"✏  {tool.get('draw_label', 'Draw Path')}")
        draw_btn.setStyleSheet(f"""
            QPushButton {{ background: #06b6d4; color: white; border: none;
                border-radius: 4px; padding: 5px 10px; font-size: 11px; font-weight: 600; }}
            QPushButton:hover {{ background: #0891b2; }}
        """)
        draw_btn.clicked.connect(lambda _, c=comp: self.path_draw_requested.emit(c.id))
        self._root.addWidget(draw_btn)

        if self._active_path_component_id == comp.id:
            hint = QLabel("Shift-drag a point to create curve handles.")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; background: transparent;")
            self._root.addWidget(hint)

    def _render_plugin_component(self, comp: SceneComponent, descriptor: dict):
        panel = build_auto_panel(
            descriptor.get("fields", []),
            comp,
            self._project,
            changed_callback=lambda: self.changed.emit(),
            field_changed_callback=lambda field_key, c=comp, d=descriptor: self._on_plugin_field_changed(c, d, field_key),
        )
        panel.setStyleSheet("background: transparent;")
        self._root.addWidget(panel)

        for tool in descriptor.get("editor_tools", []) or []:
            kind = str(tool.get("kind", ""))
            if kind == "grid_map":
                info_lbl = QLabel(self._grid_tool_info_text(comp, tool))
                info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
                self._root.addWidget(info_lbl)
                self._add_grid_tool_buttons(comp, tool)
            elif kind == "path":
                self._add_path_tool_controls(comp, tool)

    def _rebuild(self):
        # Clear existing
        while self._root.count():
            item = self._root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._scene is None:
            lbl = QLabel("No scene loaded.")
            # FIX: Changed MUTED to TEXT_MUTED
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            self._root.addWidget(lbl)
            return

        fs = _field_style()
        self._suppress = True
        self._sync_tool_shape_cache()

        # Save the real main layout
        real_root = self._root

        for comp in self._scene.components:
            ct = comp.component_type
            descriptor = _component_descriptor(self._project, ct)
            
            # Create a box for this component
            if ct == "Layer":
                lname = comp.config.get("layer_name", "").strip()
                lnum  = comp.config.get("layer", 0)
                header = f"LAYER [{lnum}]  {lname}".strip() if lname else f"LAYER [{lnum}]"
            else:
                header = str((descriptor or {}).get("label", ct)).upper()
            box = CollapsibleBox(header)
            real_root.addWidget(box)
            
            # TRICK: Temporarily swap self._root to the box's layout
            self._root = box.v_layout

            if ct == "Music":
                lbl = QLabel("Action:")
                lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl)
                ac = QComboBox()
                ac.setStyleSheet(fs)
                for opt in ("keep", "change", "stop"):
                    ac.addItem(opt)
                ac.setCurrentText(comp.config.get("action", "keep"))
                ac.currentTextChanged.connect(lambda v, c=comp: self._cfg(c, "action", v))
                self._root.addWidget(ac)
                self._audio_combo(comp, "audio_id", "Track", fs)

            elif ct == "VNDialogBox":
                # Read-only preview of first dialog page
                pages = comp.config.get("dialog_pages", [])
                if pages:
                    p0 = pages[0]
                    char = p0.get("character", "")
                    first_lines = [l for l in p0.get("lines", []) if l.strip()]
                    preview = ""
                    if char:
                        preview += f"[{char}] "
                    if first_lines:
                        preview += first_lines[0]
                    if not preview:
                        preview = "(empty)"
                    if len(first_lines) > 1:
                        preview += f"  (+{len(first_lines)-1} more lines)"
                    if len(pages) > 1:
                        preview += f"\n… {len(pages)} pages total"
                else:
                    preview = "(no dialog pages)"
                prev_lbl = QLabel(preview)
                prev_lbl.setWordWrap(True)
                prev_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px; background: transparent; padding: 2px 0;")
                self._root.addWidget(prev_lbl)
                hint = QLabel("Edit dialog pages in the Scene Options tab.")
                hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-style: italic; background: transparent;")
                self._root.addWidget(hint)

            elif ct == "ChoiceMenu":
                btn_labels = ["✕ Cross", "□ Square", "○ Circle", "△ Triangle"]
                choices = comp.config.get("choices", [])
                for i, ch in enumerate(choices):
                    cl = QLabel(btn_labels[i] if i < len(btn_labels) else f"Choice {i+1}:")
                    cl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                    self._root.addWidget(cl)
                    row = QHBoxLayout()
                    row.setSpacing(4)
                    te = QLineEdit(ch.get("text", ""))
                    te.setStyleSheet(fs)
                    te.setPlaceholderText("Label…")
                    te.textChanged.connect(lambda v, c=comp, idx=i: self._choice_text(c, idx, v))
                    gs = QSpinBox()
                    gs.setStyleSheet(fs)
                    gs.setRange(1, 999)
                    gs.setFixedWidth(52)
                    gs.setToolTip("Go to scene")
                    gs.setValue(ch.get("goto", 1))
                    gs.valueChanged.connect(lambda v, c=comp, idx=i: self._choice_goto(c, idx, v))
                    arr = QLabel("→")
                    arr.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
                    row.addWidget(te, stretch=1)
                    row.addWidget(arr)
                    row.addWidget(gs)
                    self._root.addLayout(row)

            elif ct == "SelectionGroup":
                lbl = QLabel("Cycle With:")
                lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl)
                cycle_cb = QComboBox()
                cycle_cb.setStyleSheet(fs)
                cycle_cb.addItems(["updown", "leftright"])
                cycle_cb.setCurrentText(comp.config.get("cycle_buttons", "updown"))
                cycle_cb.currentTextChanged.connect(lambda v, c=comp: self._cfg(c, "cycle_buttons", v))
                self._root.addWidget(cycle_cb)

                lbl2 = QLabel("Confirm Button:")
                lbl2.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl2)
                conf_cb = QComboBox()
                conf_cb.setStyleSheet(fs)
                conf_cb.addItems(["cross", "circle"])
                conf_cb.setCurrentText(comp.config.get("confirm_button", "cross"))
                conf_cb.currentTextChanged.connect(lambda v, c=comp: self._cfg(c, "confirm_button", v))
                self._root.addWidget(conf_cb)

                lbl3 = QLabel("Selectable Objects (cycle order):")
                lbl3.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl3)

                sel_list = QListWidget()
                sel_list.setStyleSheet(_list_style())
                sel_list.setFixedHeight(100)
                sel_ids = comp.config.get("selectable_ids", [])
                for sid in sel_ids:
                    name = self._instance_name(sid)
                    sel_list.addItem(f"{name}  ({sid})")
                self._root.addWidget(sel_list)

                btn_row = QHBoxLayout()
                btn_row.setSpacing(4)

                add_sel_btn = QPushButton("+ Add")
                add_sel_btn.setFixedHeight(28)
                _ac = _current_theme["ACCENT"]
                add_sel_btn.setStyleSheet(f"""
                    QPushButton {{ background: {_ac}; color: white; border: none;
                        border-radius: 4px; padding: 0 10px; font-size: 12px; font-weight: 600; }}
                    QPushButton:hover {{ background: {_ac}cc; }}
                """)
                add_sel_btn.clicked.connect(lambda _, c=comp, sl=sel_list: self._add_selectable(c, sl))
                btn_row.addWidget(add_sel_btn)

                rem_sel_btn = QPushButton("Remove")
                rem_sel_btn.setFixedHeight(28)
                rem_sel_btn.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {DANGER};
                        border: 1px solid {DANGER}; border-radius: 4px;
                        padding: 0 10px; font-size: 12px; }}
                    QPushButton:hover {{ background: {DANGER}; color: white; }}
                """)
                rem_sel_btn.clicked.connect(lambda _, c=comp, sl=sel_list: self._rem_selectable(c, sl))
                btn_row.addWidget(rem_sel_btn)

                up_btn = QPushButton("▲")
                up_btn.setFixedHeight(28)
                up_btn.setFixedWidth(32)
                up_btn.setStyleSheet(fs)
                up_btn.clicked.connect(lambda _, c=comp, sl=sel_list: self._move_selectable(c, sl, -1))
                btn_row.addWidget(up_btn)

                dn_btn = QPushButton("▼")
                dn_btn.setFixedHeight(28)
                dn_btn.setFixedWidth(32)
                dn_btn.setStyleSheet(fs)
                dn_btn.clicked.connect(lambda _, c=comp, sl=sel_list: self._move_selectable(c, sl, 1))
                btn_row.addWidget(dn_btn)

                btn_row.addStretch()
                self._root.addLayout(btn_row)

            elif ct == "Layer":
                # Layer name
                lbl_nm = QLabel("Name:")
                lbl_nm.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_nm)
                name_edit = QLineEdit(comp.config.get("layer_name", ""))
                name_edit.setStyleSheet(fs)
                name_edit.setPlaceholderText("e.g. Background, HUD…")
                name_edit.textChanged.connect(lambda v, c=comp: self._cfg(c, "layer_name", v))
                self._root.addWidget(name_edit)

                # Layer number
                lbl_n = QLabel("Layer:")
                lbl_n.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_n)
                layer_spin = QSpinBox()
                layer_spin.setStyleSheet(fs)
                layer_spin.setRange(0, 99)
                layer_spin.setValue(comp.config.get("layer", 0))
                layer_spin.setToolTip("0 = furthest back, higher = closer to camera")
                layer_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "layer", v))
                self._root.addWidget(layer_spin)

                # Image
                self._img_combo(comp, "image_id", "Image", fs)

                # Visible at start
                vis_chk = QCheckBox("Visible at scene start")
                vis_chk.setStyleSheet(fs)
                vis_chk.setChecked(comp.config.get("visible", True))
                vis_chk.stateChanged.connect(lambda v, c=comp: self._cfg(c, "visible", bool(v)))
                self._root.addWidget(vis_chk)

                # Screen-space locked
                ss_chk = QCheckBox("Screen-space locked (HUD / GUI)")
                ss_chk.setStyleSheet(fs)
                ss_chk.setChecked(comp.config.get("screen_space_locked", False))
                ss_chk.stateChanged.connect(lambda v, c=comp: self._cfg(c, "screen_space_locked", bool(v)))
                self._root.addWidget(ss_chk)

                # Parallax
                lbl_p = QLabel("Parallax (0=fixed, 1=full):")
                lbl_p.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_p)
                par_spin = QDoubleSpinBox()
                par_spin.setStyleSheet(fs)
                par_spin.setRange(0.0, 1.0)
                par_spin.setSingleStep(0.1)
                par_spin.setDecimals(2)
                par_spin.setValue(comp.config.get("parallax", 1.0))
                par_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "parallax", v))
                self._root.addWidget(par_spin)

                # Scroll
                scroll_chk = QCheckBox("Enable scrolling")
                scroll_chk.setStyleSheet(fs)
                scroll_chk.setChecked(comp.config.get("scroll", False))
                scroll_chk.stateChanged.connect(lambda v, c=comp: self._cfg(c, "scroll", bool(v)))
                self._root.addWidget(scroll_chk)

                lbl_spd = QLabel("Scroll speed (px/frame):")
                lbl_spd.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_spd)
                spd_spin = QSpinBox()
                spd_spin.setStyleSheet(fs)
                spd_spin.setRange(1, 60)
                spd_spin.setValue(comp.config.get("scroll_speed", 1))
                spd_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "scroll_speed", v))
                self._root.addWidget(spd_spin)

                lbl_dir = QLabel("Scroll direction:")
                lbl_dir.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_dir)
                dir_cb = QComboBox()
                dir_cb.setStyleSheet(fs)
                dir_cb.addItems(["horizontal", "vertical"])
                dir_cb.setCurrentText(comp.config.get("scroll_direction", "horizontal"))
                dir_cb.currentTextChanged.connect(lambda v, c=comp: self._cfg(c, "scroll_direction", v))
                self._root.addWidget(dir_cb)

            elif ct == "CollisionLayer":
                grid_tool = _component_editor_tool(self._project, comp, "grid_map") or {}
                # Layer name
                lbl_nm = QLabel("Name:")
                lbl_nm.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_nm)
                name_edit = QLineEdit(comp.config.get("layer_name", ""))
                name_edit.setStyleSheet(fs)
                name_edit.setPlaceholderText("e.g. Walls, Floor Collision…")
                name_edit.textChanged.connect(lambda v, c=comp: self._cfg(c, "layer_name", v))
                self._root.addWidget(name_edit)

                # Layer draw order
                lbl_l = QLabel("Layer (draw order):")
                lbl_l.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_l)
                layer_spin = QSpinBox()
                layer_spin.setStyleSheet(fs)
                layer_spin.setRange(0, 99)
                layer_spin.setValue(comp.config.get("layer", 0))
                layer_spin.setToolTip("Invisible at runtime — draw order only matters for editor visibility")
                layer_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "layer", v))
                self._root.addWidget(layer_spin)

                # Tile (cell) size
                lbl_ts = QLabel("Cell size (px):")
                lbl_ts.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_ts)
                ts_spin = QSpinBox()
                ts_spin.setStyleSheet(fs)
                ts_spin.setRange(4, 512)
                ts_spin.setValue(comp.config.get("tile_size", 32))
                ts_spin.setToolTip("Grid cell size in pixels — independent of any tilemap layer")
                ts_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "tile_size", v))
                self._root.addWidget(ts_spin)

                # Map width / height
                lbl_mw = QLabel("Map width (cells):")
                lbl_mw.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mw)
                mw_spin = QSpinBox()
                mw_spin.setStyleSheet(fs)
                mw_spin.setRange(1, 500)
                mw_spin.setValue(comp.config.get("map_width", 30))
                mw_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_collayer_size_changed(c, "map_width", v))
                self._root.addWidget(mw_spin)

                lbl_mh = QLabel("Map height (cells):")
                lbl_mh.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mh)
                mh_spin = QSpinBox()
                mh_spin.setStyleSheet(fs)
                mh_spin.setRange(1, 500)
                mh_spin.setValue(comp.config.get("map_height", 17))
                mh_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_collayer_size_changed(c, "map_height", v))
                self._root.addWidget(mh_spin)

                info_lbl = QLabel(self._grid_tool_info_text(comp, grid_tool))
                info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
                self._root.addWidget(info_lbl)
                self._add_grid_tool_buttons(comp, grid_tool, accent_color="#c0392b")

            elif ct == "LightmapLayer":
                grid_tool = _component_editor_tool(self._project, comp, "grid_map") or {}
                lbl_nm = QLabel("Name:")
                lbl_nm.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_nm)
                name_edit = QLineEdit(comp.config.get("layer_name", ""))
                name_edit.setStyleSheet(fs)
                name_edit.setPlaceholderText("e.g. Indoor Darkness, Night Fog...")
                name_edit.textChanged.connect(lambda v, c=comp: self._cfg(c, "layer_name", v))
                self._root.addWidget(name_edit)

                lbl_l = QLabel("Layer (overlay order):")
                lbl_l.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_l)
                layer_spin = QSpinBox()
                layer_spin.setStyleSheet(fs)
                layer_spin.setRange(0, 99)
                layer_spin.setValue(comp.config.get("layer", 99))
                layer_spin.setToolTip("Reserved for future multi-lightmap ordering; v1 draws all lightmaps after the world")
                layer_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "layer", v))
                self._root.addWidget(layer_spin)

                lbl_ts = QLabel("Cell size (px):")
                lbl_ts.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_ts)
                ts_spin = QSpinBox()
                ts_spin.setStyleSheet(fs)
                ts_spin.setRange(4, 512)
                ts_spin.setValue(comp.config.get("tile_size", 32))
                ts_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "tile_size", v))
                self._root.addWidget(ts_spin)

                lbl_mw = QLabel("Map width (cells):")
                lbl_mw.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mw)
                mw_spin = QSpinBox()
                mw_spin.setStyleSheet(fs)
                mw_spin.setRange(1, 500)
                mw_spin.setValue(comp.config.get("map_width", 30))
                mw_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_lightmap_size_changed(c, "map_width", v))
                self._root.addWidget(mw_spin)

                lbl_mh = QLabel("Map height (cells):")
                lbl_mh.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mh)
                mh_spin = QSpinBox()
                mh_spin.setStyleSheet(fs)
                mh_spin.setRange(1, 500)
                mh_spin.setValue(comp.config.get("map_height", 17))
                mh_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_lightmap_size_changed(c, "map_height", v))
                self._root.addWidget(mh_spin)

                visible_check = QCheckBox("Visible")
                visible_check.setChecked(comp.config.get("visible", True))
                visible_check.setStyleSheet(f"color: {TEXT};")
                visible_check.toggled.connect(lambda v, c=comp: self._cfg(c, "visible", bool(v)))
                self._root.addWidget(visible_check)

                lbl_op = QLabel("Layer opacity:")
                lbl_op.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_op)
                op_spin = QSpinBox()
                op_spin.setStyleSheet(fs)
                op_spin.setRange(0, 255)
                op_spin.setValue(comp.config.get("opacity", 255))
                op_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "opacity", v))
                self._root.addWidget(op_spin)

                lbl_col = QLabel("Blend color:")
                lbl_col.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_col)
                col_val = comp.config.get("blend_color", "#000000")
                col_btn = QPushButton(col_val)
                col_btn.setStyleSheet(
                    f"background: {col_val}; color: white; border: 1px solid {BORDER}; "
                    f"border-radius: 4px; padding: 6px;"
                )
                def _pick_lightmap_color(*_, c=comp, btn=col_btn):
                    picked = QColorDialog.getColor(QColor(c.config.get("blend_color", "#000000")), self)
                    if not picked.isValid():
                        return
                    value = picked.name()
                    btn.setText(value)
                    btn.setStyleSheet(
                        f"background: {value}; color: white; border: 1px solid {BORDER}; "
                        f"border-radius: 4px; padding: 6px;"
                    )
                    self._cfg(c, "blend_color", value)
                col_btn.clicked.connect(_pick_lightmap_color)
                self._root.addWidget(col_btn)

                info_lbl = QLabel(self._grid_tool_info_text(comp, grid_tool))
                info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
                self._root.addWidget(info_lbl)
                self._add_grid_tool_buttons(comp, grid_tool, accent_color="#d97706")

                lbl_brush = QLabel("Brush darkness:")
                lbl_brush.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_brush)
                brush_spin = QSpinBox()
                brush_spin.setStyleSheet(fs)
                brush_spin.setRange(0, 255)
                brush_spin.setValue(comp.config.get("paint_value", 192))
                brush_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "paint_value", v))
                self._root.addWidget(brush_spin)

                preset_row = QHBoxLayout()
                preset_row.setSpacing(4)
                for preset in (0, 64, 128, 192, 255):
                    btn = QPushButton(str(preset))
                    btn.setStyleSheet(
                        f"background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; "
                        f"border-radius: 4px; padding: 4px 6px;"
                    )
                    btn.clicked.connect(lambda _, v=preset, c=comp, s=brush_spin: (s.setValue(v), self._cfg(c, "paint_value", v)))
                    preset_row.addWidget(btn)
                self._root.addLayout(preset_row)

                lbl_mode = QLabel("Brush mode:")
                lbl_mode.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mode)
                mode_combo = QComboBox()
                mode_combo.setStyleSheet(fs)
                mode_combo.addItems(["set", "add", "subtract"])
                mode_combo.setCurrentText(comp.config.get("brush_mode", "set"))
                mode_combo.currentTextChanged.connect(lambda v, c=comp: self._cfg(c, "brush_mode", v))
                self._root.addWidget(mode_combo)

                lbl_radius = QLabel("Brush radius (cells):")
                lbl_radius.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_radius)
                radius_spin = QSpinBox()
                radius_spin.setStyleSheet(fs)
                radius_spin.setRange(0, 6)
                radius_spin.setValue(comp.config.get("brush_radius", 0))
                radius_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "brush_radius", v))
                self._root.addWidget(radius_spin)

                lbl_strength = QLabel("Brush strength:")
                lbl_strength.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_strength)
                strength_spin = QSpinBox()
                strength_spin.setStyleSheet(fs)
                strength_spin.setRange(1, 255)
                strength_spin.setValue(comp.config.get("brush_strength", 48))
                strength_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "brush_strength", v))
                self._root.addWidget(strength_spin)

            elif ct == "TileLayer":
                # Tileset selector
                lbl_ts = QLabel("Tileset:")
                lbl_ts.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_ts)
                ts_combo = QComboBox()
                ts_combo.setStyleSheet(fs)
                ts_combo.addItem("-- none --", None)
                if self._project:
                    for ts in self._project.tilesets:
                        ts_combo.addItem(ts.name or "(unnamed)", ts.id)
                cur_ts = comp.config.get("tileset_id")
                for i in range(ts_combo.count()):
                    if ts_combo.itemData(i) == cur_ts:
                        ts_combo.setCurrentIndex(i)
                        break
                ts_combo.currentIndexChanged.connect(
                    lambda _, c=comp, w=ts_combo: self._on_tilelayer_tileset_changed(c, w))
                self._root.addWidget(ts_combo)

                # Map width / height in tiles
                lbl_mw = QLabel("Map width (tiles):")
                lbl_mw.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mw)
                mw_spin = QSpinBox()
                mw_spin.setStyleSheet(fs)
                mw_spin.setRange(1, 500)
                mw_spin.setValue(comp.config.get("map_width", 30))
                mw_spin.setToolTip("Number of tiles across (30 = one Vita screen at 32px)")
                mw_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_tilelayer_size_changed(c, "map_width", v))
                self._root.addWidget(mw_spin)

                lbl_mh = QLabel("Map height (tiles):")
                lbl_mh.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_mh)
                mh_spin = QSpinBox()
                mh_spin.setStyleSheet(fs)
                mh_spin.setRange(1, 500)
                mh_spin.setValue(comp.config.get("map_height", 17))
                mh_spin.setToolTip("Number of tiles tall (17 = one Vita screen at 32px)")
                mh_spin.valueChanged.connect(
                    lambda v, c=comp: self._on_tilelayer_size_changed(c, "map_height", v))
                self._root.addWidget(mh_spin)

                # Draw layer
                lbl_dl = QLabel("Draw layer (z-order):")
                lbl_dl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_dl)
                dl_spin = QSpinBox()
                dl_spin.setStyleSheet(fs)
                dl_spin.setRange(0, 99)
                dl_spin.setValue(comp.config.get("draw_layer", 0))
                dl_spin.setToolTip("0 = drawn first (behind everything)")
                dl_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "draw_layer", v))
                self._root.addWidget(dl_spin)

                # Info label
                tiles = comp.config.get("tiles", [])
                painted = sum(1 for t in tiles if t != -1)
                mw = comp.config.get("map_width", 30)
                mh = comp.config.get("map_height", 17)
                info_lbl = QLabel(
                    f"{mw}×{mh} tiles  •  {mw*mh} cells  •  {painted} painted\n"
                    f"Baked size: {mw*32}×{mh*32} px"
                )
                info_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
                self._root.addWidget(info_lbl)

                # Open palette button
                palette_btn = QPushButton("Open Tile Palette ↓")
                _ac = _current_theme["ACCENT"]
                palette_btn.setStyleSheet(f"""
                    QPushButton {{ background: {_ac}; color: white; border: none;
                        border-radius: 4px; padding: 5px 10px; font-size: 11px; font-weight: 600; }}
                    QPushButton:hover {{ background: {_ac}cc; }}
                """)
                palette_btn.clicked.connect(
                    lambda _, c=comp: self.tile_layer_selected.emit(
                        f"__tilelayer__:{c.id}:{c.config.get('tileset_id') or ''}"
                    ))
                self._root.addWidget(palette_btn)

            elif ct == "LayerAnimation":
                anim_id = comp.config.get("layer_anim_id", "")
                doll_name = "(none)"
                if anim_id and self._project:
                    doll = self._project.get_paper_doll(anim_id)
                    if doll:
                        doll_name = doll.name

                lbl_a = QLabel("Asset:")
                lbl_a.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_a)
                asset_cb = QComboBox()
                asset_cb.setStyleSheet(fs)
                asset_cb.addItem("-- none --", "")
                if self._project:
                    for pd in self._project.paper_dolls:
                        asset_cb.addItem(pd.name, pd.id)
                for i in range(asset_cb.count()):
                    if asset_cb.itemData(i) == anim_id:
                        asset_cb.setCurrentIndex(i)
                        break
                asset_cb.currentIndexChanged.connect(
                    lambda _, c=comp, w=asset_cb: self._cfg(c, "layer_anim_id", w.currentData()))
                self._root.addWidget(asset_cb)

                lbl_dl = QLabel("Draw layer (z-order):")
                lbl_dl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
                self._root.addWidget(lbl_dl)
                dl_spin = QSpinBox()
                dl_spin.setStyleSheet(fs)
                dl_spin.setRange(0, 99)
                dl_spin.setValue(comp.config.get("draw_layer", 0))
                dl_spin.setToolTip("0 = drawn first (behind everything)")
                dl_spin.valueChanged.connect(lambda v, c=comp: self._cfg(c, "draw_layer", v))
                self._root.addWidget(dl_spin)

                note = QLabel("⚠  Deprecated — use a LayerAnimation object instead.")
                note.setWordWrap(True)
                note.setStyleSheet(f"color: {WARNING}; font-size: 10px; background: transparent;")
                self._root.addWidget(note)

            elif ct == "Path":
                path_tool = _component_editor_tool(self._project, comp, "path") or {}
                self._add_path_tool_controls(comp, path_tool)

            elif descriptor:
                self._render_plugin_component(comp, descriptor)

        # Restore real root
        self._root = real_root
        self._root.addStretch()
        self._suppress = False

    def _img_combo(self, comp, key, lbl_text, fs):
        lbl = QLabel(lbl_text + ":")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
        self._root.addWidget(lbl)
        cb = QComboBox()
        cb.setStyleSheet(fs)
        cb.addItem("-- none --", None)
        if self._project:
            for img in self._project.images:
                cb.addItem(img.name, img.id)
        cur = comp.config.get(key)
        for i in range(cb.count()):
            if cb.itemData(i) == cur:
                cb.setCurrentIndex(i)
                break
        cb.currentIndexChanged.connect(lambda _, c=comp, k=key, w=cb: self._cfg(c, k, w.currentData()))
        self._root.addWidget(cb)

    def _audio_combo(self, comp, key, lbl_text, fs):
        lbl = QLabel(lbl_text + ":")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
        self._root.addWidget(lbl)
        cb = QComboBox()
        cb.setStyleSheet(fs)
        cb.addItem("-- none --", None)
        if self._project:
            for a in self._project.audio:
                cb.addItem(a.name, a.id)
        cur = comp.config.get(key)
        for i in range(cb.count()):
            if cb.itemData(i) == cur:
                cb.setCurrentIndex(i)
                break
        cb.currentIndexChanged.connect(lambda _, c=comp, k=key, w=cb: self._cfg(c, k, w.currentData()))
        self._root.addWidget(cb)

    def _instance_name(self, instance_id: str) -> str:
        """Get a display name for a placed object instance ID."""
        if self._scene and self._project:
            for po in self._scene.placed_objects:
                if po.instance_id == instance_id:
                    od = self._project.get_object_def(po.object_def_id)
                    return od.name if od else "Unknown"
        return "?"

    def _add_selectable(self, comp, list_widget):
        """Show a picker of placed objects in this scene, add selection."""
        if not self._scene or not self._project:
            return
        sel_ids = comp.config.get("selectable_ids", [])
        # Build list of placed objects not already in the selection group
        available = []
        for po in self._scene.placed_objects:
            if po.instance_id not in sel_ids:
                od = self._project.get_object_def(po.object_def_id)
                name = od.name if od else "Unknown"
                available.append((po.instance_id, name))
        if not available:
            return
        # Simple pick dialog
        from PySide6.QtWidgets import QInputDialog
        names = [f"{n}  ({iid})" for iid, n in available]
        choice, ok = QInputDialog.getItem(self, "Add Selectable", "Pick an object:", names, 0, False)
        if ok and choice:
            idx = names.index(choice)
            sel_ids.append(available[idx][0])
            comp.config["selectable_ids"] = sel_ids
            list_widget.addItem(choice)
            self.changed.emit()

    def _rem_selectable(self, comp, list_widget):
        """Remove the selected item from the selection group."""
        row = list_widget.currentRow()
        sel_ids = comp.config.get("selectable_ids", [])
        if 0 <= row < len(sel_ids):
            sel_ids.pop(row)
            list_widget.takeItem(row)
            self.changed.emit()

    def _move_selectable(self, comp, list_widget, direction):
        """Move a selectable up or down in the cycle order."""
        row = list_widget.currentRow()
        sel_ids = comp.config.get("selectable_ids", [])
        new_row = row + direction
        if 0 <= row < len(sel_ids) and 0 <= new_row < len(sel_ids):
            sel_ids[row], sel_ids[new_row] = sel_ids[new_row], sel_ids[row]
            item = list_widget.takeItem(row)
            list_widget.insertItem(new_row, item)
            list_widget.setCurrentRow(new_row)
            self.changed.emit()

    def _on_tilelayer_tileset_changed(self, comp, combo):
        if self._suppress:
            return
        ts_id = combo.currentData()
        comp.config["tileset_id"] = ts_id
        self.changed.emit()
        self.tile_layer_selected.emit(f"__tilelayer__:{comp.id}:{ts_id or ''}")

    def _on_tilelayer_size_changed(self, comp, key, value):
        if self._suppress:
            return
        comp.config[key] = value
        # Resize the tiles array to match new dimensions, preserving existing data
        mw = comp.config.get("map_width", 30)
        mh = comp.config.get("map_height", 17)
        old_tiles = comp.config.get("tiles", [])
        old_w = comp.config.get("map_width", mw) if key == "map_height" else (len(old_tiles) // mh if mh else mw)
        # Rebuild flat array preserving what we can
        new_tiles = []
        for row in range(mh):
            for col in range(mw):
                old_idx = row * old_w + col
                if old_idx < len(old_tiles) and col < old_w:
                    new_tiles.append(old_tiles[old_idx])
                else:
                    new_tiles.append(-1)
        comp.config["tiles"] = new_tiles
        self.changed.emit()

    def _on_collayer_size_changed(self, comp, key, value):
        if self._suppress:
            return
        tool = _component_editor_tool(self._project, comp, "grid_map") or {}
        data_key = str(tool.get("data_key", "tiles"))
        old_width, old_height = self._grid_tool_shapes.get(
            (comp.id, data_key),
            (
                max(1, int(comp.config.get(str(tool.get("width_key", "map_width")), 1) or 1)),
                max(1, int(comp.config.get(str(tool.get("height_key", "map_height")), 1) or 1)),
            ),
        )
        comp.config[key] = value
        self._resize_grid_tool_data(comp, tool, old_width, old_height)
        self.changed.emit()

    def _on_lightmap_size_changed(self, comp, key, value):
        if self._suppress:
            return
        tool = _component_editor_tool(self._project, comp, "grid_map") or {}
        data_key = str(tool.get("data_key", "cells"))
        old_width, old_height = self._grid_tool_shapes.get(
            (comp.id, data_key),
            (
                max(1, int(comp.config.get(str(tool.get("width_key", "map_width")), 1) or 1)),
                max(1, int(comp.config.get(str(tool.get("height_key", "map_height")), 1) or 1)),
            ),
        )
        comp.config[key] = value
        self._resize_grid_tool_data(comp, tool, old_width, old_height)
        self.changed.emit()

    def _cfg(self, comp, key, value):
        if self._suppress:
            return
        comp.config[key] = value
        self.changed.emit()

    def _set_line(self, comp, idx, value):
        if self._suppress:
            return
        lines = comp.config.setdefault("lines", ["", "", "", ""])
        while len(lines) <= idx:
            lines.append("")
        lines[idx] = value
        self.changed.emit()

    def _choice_text(self, comp, idx, value):
        if self._suppress:
            return
        comp.config["choices"][idx]["text"] = value
        self.changed.emit()

    def _choice_goto(self, comp, idx, value):
        if self._suppress:
            return
        comp.config["choices"][idx]["goto"] = value
        self.changed.emit()


# ─────────────────────────────────────────────────────────────
#  TABBED INSPECTOR
# ─────────────────────────────────────────────────────────────

class TabbedInspector(QWidget):
    changed = Signal()
    tile_layer_selected = Signal(str)  # forwarded from SceneComponentsPanel
    path_draw_requested = Signal(str)  # forwarded from SceneComponentsPanel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._instance: PlacedObject | None = None
        self._project:  Project      | None = None
        self._scene:    Scene        | None = None
        self._suppress  = False
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        self._inspector_header = header
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        self._header_lbl = QLabel("INSPECTOR")
        self._header_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
        )
        hl.addWidget(self._header_lbl)
        hl.addStretch()
        outer.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background: {DARK}; }}
            QTabBar::tab {{
                background: {SURFACE}; color: {TEXT_DIM};
                padding: 6px 16px; border: none;
                border-bottom: 2px solid transparent;
                font-size: 11px; font-weight: 500;
            }}
            QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; background: {DARK}; }}
            QTabBar::tab:hover {{ color: {TEXT}; background: {SURFACE2}; }}
        """)

        # ── Object Tab ────────────────────────────────────────
        obj_scroll = QScrollArea()
        obj_scroll.setWidgetResizable(True)
        obj_scroll.setStyleSheet("border: none; background: transparent;")
        self._obj_body = QWidget()
        self._obj_body.setStyleSheet(f"background: {DARK};")
        ov = QVBoxLayout(self._obj_body)
        ov.setContentsMargins(10, 6, 10, 10)
        ov.setSpacing(4)

        fs = _field_style()

        # [1] TRANSFORM & DISPLAY
        self.trans_box = CollapsibleBox("TRANSFORM & DISPLAY")
        
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        for attr, prefix in (("x_spin", "X:"), ("y_spin", "Y:")):
            lbl = QLabel(prefix)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
            spin = QSpinBox()
            spin.setRange(-9999, 9999)
            spin.setStyleSheet(fs)
            spin.valueChanged.connect(self._emit_transform)
            setattr(self, attr, spin)
            pos_row.addWidget(lbl)
            pos_row.addWidget(spin)
        self.trans_box.addLayout(pos_row)

        self.trans_box.addWidget(QLabel("Scale:", styleSheet=f"color:{TEXT_DIM}; font-size:11px;"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 20.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setStyleSheet(fs)
        self.scale_spin.valueChanged.connect(self._emit_transform)
        self.trans_box.addWidget(self.scale_spin)

        self.trans_box.addWidget(QLabel("Rotation:", styleSheet=f"color:{TEXT_DIM}; font-size:11px;"))
        rr = QHBoxLayout()
        rr.setSpacing(4)
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-360.0, 360.0)
        self.rotation_spin.setSingleStep(1.0)
        self.rotation_spin.setDecimals(1)
        self.rotation_spin.setStyleSheet(fs)
        self.rotation_spin.valueChanged.connect(self._emit_transform)
        rot_reset = QPushButton("0°")
        rot_reset.setFixedSize(32, 26)
        rot_reset.setStyleSheet(f"""
            QPushButton {{ background: {SURFACE2}; color: {TEXT_DIM};
                border: 1px solid {BORDER}; border-radius: 4px; font-size: 11px; }}
            QPushButton:hover {{ color: {TEXT}; background: {ACCENT}; border-color: {ACCENT}; }}
        """)
        rot_reset.clicked.connect(lambda: self.rotation_spin.setValue(0.0))
        rr.addWidget(self.rotation_spin)
        rr.addWidget(rot_reset)
        self.trans_box.addLayout(rr)

        self.trans_box.addWidget(QLabel("Opacity:", styleSheet=f"color:{TEXT_DIM}; font-size:11px;"))
        opr = QHBoxLayout()
        opr.setSpacing(6)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setStyleSheet(fs)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_lbl = QLabel("100%")
        self.opacity_lbl.setFixedWidth(36)
        self.opacity_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
        opr.addWidget(self.opacity_slider)
        opr.addWidget(self.opacity_lbl)
        self.trans_box.addLayout(opr)

        self.visible_check = QCheckBox("Visible")
        self.visible_check.setStyleSheet(fs)
        self.visible_check.stateChanged.connect(self._emit_transform)
        self.trans_box.addWidget(self.visible_check)

        self.trans_box.addWidget(QLabel("Layer:", styleSheet=f"color:{TEXT_DIM}; font-size:11px;"))
        self.layer_combo = QComboBox()
        self.layer_combo.setStyleSheet(fs)
        self.layer_combo.currentIndexChanged.connect(self._emit_transform)
        self.trans_box.addWidget(self.layer_combo)

        self.trans_box.addWidget(QLabel("Draw Layer (if no layer assigned):", styleSheet=f"color:{TEXT_DIM}; font-size:11px;"))
        self.draw_layer_spin = QSpinBox()
        self.draw_layer_spin.setRange(0, 99)
        self.draw_layer_spin.setValue(2)
        self.draw_layer_spin.setStyleSheet(fs)
        self.draw_layer_spin.valueChanged.connect(self._emit_transform)
        self.trans_box.addWidget(self.draw_layer_spin)

        ov.addWidget(self.trans_box)

        ov.addWidget(_divider())

        # [2] OBJECT BEHAVIORS
        self.beh_box = CollapsibleBox("BEHAVIORS")

        self._beh_summary = QLabel("No behaviors.")
        self._beh_summary.setWordWrap(True)
        self._beh_summary.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 11px; background: transparent; padding: 2px 0;"
        )
        self.beh_box.addWidget(self._beh_summary)

        self._beh_edit_btn = QPushButton("⬡  Edit Behaviors")
        self._beh_edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE2}; color: {ACCENT};
                border: 1px solid {ACCENT}; border-radius: 4px;
                padding: 5px 12px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {ACCENT}; color: white; }}
        """)
        self._beh_edit_btn.clicked.connect(self._open_behavior_graph)
        self.beh_box.addWidget(self._beh_edit_btn)

        ov.addWidget(self.beh_box)

        # FIX: Added stretch at the very bottom to push everything up
        ov.addStretch()

        self._obj_body.setEnabled(False)
        obj_scroll.setWidget(self._obj_body)
        self.tabs.addTab(obj_scroll, "Object")

        # ── Scene Tab ─────────────────────────────────────────
        scene_scroll = QScrollArea()
        scene_scroll.setWidgetResizable(True)
        scene_scroll.setStyleSheet("border: none; background: transparent;")
        self._scene_body = QWidget()
        self._scene_body.setStyleSheet(f"background: {DARK};")
        sv = QVBoxLayout(self._scene_body)
        sv.setContentsMargins(10, 6, 10, 10)
        sv.setSpacing(4)

        # [3] COMPONENTS
        self.comps_panel = SceneComponentsPanel()
        self.comps_panel.changed.connect(lambda: self.changed.emit())
        self.comps_panel.tile_layer_selected.connect(self.tile_layer_selected)
        self.comps_panel.path_draw_requested.connect(self.path_draw_requested)
        sv.addWidget(self.comps_panel)

        sv.addStretch()

        self._scene_body.setEnabled(False)
        scene_scroll.setWidget(self._scene_body)
        self.tabs.addTab(scene_scroll, "Scene")

        outer.addWidget(self.tabs, stretch=1)

    def restyle(self, c: dict):
        self._inspector_header.setStyleSheet(
            f"background: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};"
        )
        self._header_lbl.setStyleSheet(
            f"color: {c['TEXT_DIM']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
        )
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background: {c['DARK']}; }}
            QTabBar::tab {{
                background: {c['SURFACE']}; color: {c['TEXT_DIM']};
                padding: 6px 16px; border: none;
                border-bottom: 2px solid transparent;
                font-size: 11px; font-weight: 500;
            }}
            QTabBar::tab:selected {{ color: {c['TEXT']}; border-bottom: 2px solid {c['ACCENT']}; background: {c['DARK']}; }}
            QTabBar::tab:hover {{ color: {c['TEXT']}; background: {c['SURFACE2']}; }}
        """)
        self._obj_body.setStyleSheet(f"background: {c['DARK']};")
        self._scene_body.setStyleSheet(f"background: {c['DARK']};")
        # Restyle the one-off accent button that was built at construction time
        self._beh_edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['SURFACE2']}; color: {c['ACCENT']};
                border: 1px solid {c['ACCENT']}; border-radius: 4px;
                padding: 5px 12px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {c['ACCENT']}; color: white; }}
        """)
    def _on_opacity(self, value: int):
        self.opacity_lbl.setText(f"{value}%")
        self._emit_transform()

    def _emit_transform(self):
        if self._suppress or self._instance is None:
            return
        self._instance.x        = self.x_spin.value()
        self._instance.y        = self.y_spin.value()
        self._instance.scale    = self.scale_spin.value()
        self._instance.rotation = self.rotation_spin.value()
        self._instance.opacity  = self.opacity_slider.value() / 100.0
        self._instance.visible  = self.visible_check.isChecked()
        self._instance.layer_id    = self.layer_combo.currentData() or ""
        self._instance.draw_layer  = self.draw_layer_spin.value()
        self.draw_layer_spin.setVisible(self._instance.layer_id == "")
        self.changed.emit()




    def _open_behavior_graph(self):
        if self._instance is None or self._project is None:
            return
        od = self._project.get_object_def(self._instance.object_def_id)
        if od is None:
            return
        from plugin_registry import sync_runtime_modules
        from behavior_node_graph import BehaviorGraphDialog
        sync_runtime_modules(getattr(self._project, "plugin_registry", None))
        seed_instance_behaviors_from_definition(self._instance, od)
        dlg = BehaviorGraphDialog(
            _PlacedObjectBehaviorTarget(self._instance, od),
            parent=self,
            scene=self._scene,
            project=self._project,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_beh_summary()
            self.changed.emit()

    def _refresh_beh_summary(self):
        od = self._project.get_object_def(self._instance.object_def_id) if self._instance and self._project else None
        behaviors = effective_placed_behaviors(self._instance, od)
        if not behaviors:
            self._beh_summary.setText("No behaviors.")
            return
        lines = []
        for b in behaviors:
            lines.append(f"• {b.trigger}  ({len(b.actions)} actions)")
        self._beh_summary.setText("\n".join(lines))






    def load_instance(self, instance: PlacedObject, project: Project, scene: Scene):
        self._instance = instance
        self._project  = project
        self._scene    = scene
        self._suppress = True
        od = project.get_object_def(instance.object_def_id)
        self._header_lbl.setText(f"INSPECTOR  —  {od.name if od else 'Object'}")
        self.x_spin.setValue(instance.x)
        self.y_spin.setValue(instance.y)
        self.scale_spin.setValue(instance.scale)
        self.rotation_spin.setValue(instance.rotation)
        pct = int(round(instance.opacity * 100))
        self.opacity_slider.setValue(pct)
        self.opacity_lbl.setText(f"{pct}%")
        self.visible_check.setChecked(instance.visible)

        # Populate layer dropdown from scene's Layer components
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("— world (no layer) —", "")
        for comp in scene.components:
            if comp.component_type == "Layer":
                lname = comp.config.get("layer_name", "").strip() or "Unnamed Layer"
                lnum  = comp.config.get("layer", 0)
                self.layer_combo.addItem(f"[{lnum}] {lname}", comp.id)
        current_layer_id = getattr(instance, "layer_id", "")
        for i in range(self.layer_combo.count()):
            if self.layer_combo.itemData(i) == current_layer_id:
                self.layer_combo.setCurrentIndex(i)
                break
        self.layer_combo.blockSignals(False)

        self.draw_layer_spin.blockSignals(True)
        self.draw_layer_spin.setValue(getattr(instance, "draw_layer", 2))
        self.draw_layer_spin.blockSignals(False)
        # Only show draw_layer spin when no layer component is assigned
        self.draw_layer_spin.setVisible(current_layer_id == "")

        self._refresh_beh_summary()
        self._obj_body.setEnabled(True)
        self._suppress = False

    def load_scene(self, scene: Scene, project: Project):
        self._scene   = scene
        self._project = project
        self._scene_body.setEnabled(True)
        self.comps_panel.set_active_path_component_id(None)
        self.comps_panel.load(scene, project)

    def set_active_path_component_id(self, component_id: str | None):
        self.comps_panel.set_active_path_component_id(component_id)

    def sync_position(self, x: int, y: int):
        self._suppress = True
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        self._suppress = False

    def clear_object(self):
        self._instance = None
        self._obj_body.setEnabled(False)
        self._header_lbl.setText("INSPECTOR")

    def clear_all(self):
        self.clear_object()
        self._scene = None
        self._scene_body.setEnabled(False)
        self.comps_panel.set_active_path_component_id(None)
        self.comps_panel.clear()


# ─────────────────────────────────────────────────────────────
#  VITA CANVAS
# ─────────────────────────────────────────────────────────────

class VitaCanvas(QWidget):
    object_moved    = Signal(str, int, int)
    object_selected = Signal(int)
    scene_changed   = Signal()
    path_mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(VITA_W, VITA_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._scene:         Scene   | None = None
        self._project:       Project | None = None
        self._grid_visible:  bool  = False
        self._grid_size:     int   = 32
        self._snap:          bool  = False
        self._pixmap_cache:  dict[str, QPixmap] = {}
        self._dragging:      bool          = False
        self._drag_instance: PlacedObject | None = None
        self._drag_offset:   QPoint        = QPoint(0, 0)
        self._selected_row:  int           = -1
        # Tile paint mode
        self._tile_paint_mode:  bool             = False
        self._tile_layer_comp:  SceneComponent   | None = None
        self._tile_tileset:     object           | None = None   # RegisteredTileset
        self._tile_palette_ref: object           | None = None   # TilePalette
        self._tile_painting:    bool             = False         # mouse held
        self._grid_paint_mode:  bool             = False
        self._grid_tool_comp:   SceneComponent   | None = None
        self._grid_tool:        dict | None      = None
        self._grid_erase_mode:  bool             = False
        # Path draw mode
        self._path_draw_mode:   bool             = False
        self._path_draw_comp:   SceneComponent   | None = None   # which Path component
        self._path_draw_tool:   dict | None      = None
        self._path_drag_idx:    int              = -1             # index of point being dragged
        self._path_drag_handle: str              = ""             # "" | "anchor" | "cx1" | "cx2"
        # Camera / world pan
        self._cam_x:         int    = 0
        self._cam_y:         int    = 0
        self._panning:       bool   = False
        self._pan_origin:    QPoint = QPoint(0, 0)
        self._pan_cam_origin: tuple = (0, 0)

    def load(self, scene, project):
        self._scene   = scene
        self._project = project
        self._cam_x   = 0
        self._cam_y   = 0
        # Exit any active draw modes
        self._path_draw_mode = False
        self._path_draw_comp = None
        self._path_draw_tool = None
        self._tile_paint_mode = False
        self._grid_paint_mode = False
        self._grid_tool_comp = None
        self._grid_tool = None
        self.update()

    def set_selected_row(self, row):
        self._selected_row = row
        self.update()

    def set_grid_visible(self, v):
        self._grid_visible = v
        self.update()

    def set_grid_size(self, s):
        self._grid_size = s
        self.update()

    def set_tile_paint_mode(self, active: bool, tile_layer_comp, tileset, palette_ref):
        self._tile_paint_mode  = active
        self._tile_layer_comp  = tile_layer_comp
        self._tile_tileset     = tileset
        self._tile_palette_ref = palette_ref
        if active:
            self._grid_paint_mode = False
            self._grid_tool_comp = None
            self._grid_tool = None
            self._path_draw_mode = False
            self._path_draw_comp = None
            self._path_draw_tool = None
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_grid_paint_mode(self, active: bool, component: SceneComponent | None, tool: dict | None, *, erase_mode: bool = False):
        self._grid_paint_mode = active
        self._grid_tool_comp = component
        self._grid_tool = copy.deepcopy(tool) if tool else None
        self._grid_erase_mode = bool(erase_mode)
        if active:
            self._tile_paint_mode = False
            self._tile_layer_comp = None
            self._tile_tileset = None
            self._tile_palette_ref = None
            self._path_draw_mode = False
            self._path_draw_comp = None
            self._path_draw_tool = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_paint_tile(self, index: int):
        self.update()

    def enter_path_draw(self, comp: SceneComponent, tool: dict):
        """Enter path-draw mode for the given path-backed component."""
        self._path_draw_mode  = True
        self._path_draw_comp  = comp
        self._path_draw_tool  = copy.deepcopy(tool)
        self._path_drag_idx   = -1
        self._path_drag_handle = ""
        self._tile_paint_mode = False
        self._grid_paint_mode = False
        self._grid_tool_comp = None
        self._grid_tool = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.path_mode_changed.emit(comp.id)
        self.update()

    def exit_path_draw(self):
        """Leave path-draw mode."""
        self._path_draw_mode  = False
        self._path_draw_comp  = None
        self._path_draw_tool  = None
        self._path_drag_idx   = -1
        self._path_drag_handle = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.path_mode_changed.emit("")
        self.update()

    def _path_hit_test(self, wx, wy, radius=8):
        """Return (point_index, handle_type) or (-1, '') if nothing hit.
        handle_type is 'anchor', 'cx1', or 'cx2'."""
        if not self._path_draw_comp:
            return -1, ""
        points_key = str((self._path_draw_tool or {}).get("points_key", "points"))
        pts = self._path_draw_comp.config.get(points_key, [])
        for i, pt in enumerate(pts):
            # Check control handles first (smaller targets drawn on top)
            for hk_x, hk_y, name in (("cx1","cy1","cx1"), ("cx2","cy2","cx2")):
                hx = pt["x"] + pt.get(hk_x, 0)
                hy = pt["y"] + pt.get(hk_y, 0)
                if (pt.get(hk_x, 0) != 0 or pt.get(hk_y, 0) != 0):
                    if abs(wx - hx) <= radius and abs(wy - hy) <= radius:
                        return i, name
            # Check anchor
            if abs(wx - pt["x"]) <= radius and abs(wy - pt["y"]) <= radius:
                return i, "anchor"
        return -1, ""

    def _paint_tile_at(self, canvas_x: int, canvas_y: int):
        if self._grid_paint_mode and self._grid_tool_comp is not None and self._grid_tool:
            comp = self._grid_tool_comp
            tool = self._grid_tool
            data_key = str(tool.get("data_key", "tiles"))
            width_key = str(tool.get("width_key", "map_width"))
            height_key = str(tool.get("height_key", "map_height"))
            cell_size_key = str(tool.get("cell_size_key", "tile_size"))
            default_cell = tool.get("default_cell", 0)
            tile_size = max(1, int(comp.config.get(cell_size_key, 32) or 32))
            map_w = max(1, int(comp.config.get(width_key, 1) or 1))
            map_h = max(1, int(comp.config.get(height_key, 1) or 1))
            col = canvas_x // tile_size
            row = canvas_y // tile_size
            if col < 0 or col >= map_w or row < 0 or row >= map_h:
                return
            values = comp.config.get(data_key, [])
            needed = map_w * map_h
            if len(values) < needed:
                values.extend([default_cell] * (needed - len(values)))
                comp.config[data_key] = values
            if str(tool.get("mode", "binary")) == "binary":
                flat_idx = row * map_w + col
                new_val = default_cell if self._grid_erase_mode else tool.get("active_value", 1)
                if values[flat_idx] != new_val:
                    values[flat_idx] = new_val
                    self.scene_changed.emit()
                    self.update()
                return
            paint_key = str(tool.get("paint_value_key", "paint_value"))
            paint_value = int(default_cell) if self._grid_erase_mode else max(
                0,
                min(255, int(comp.config.get(paint_key, default_cell) or default_cell)),
            )
            if self._apply_scalar_grid_brush(comp, tool, values, map_w, map_h, col, row, paint_value):
                self.scene_changed.emit()
                self.update()
            return

        if self._tile_layer_comp is None:
            return
        comp = self._tile_layer_comp

        if self._tile_tileset is None or self._tile_palette_ref is None:
            return
        ts        = self._tile_tileset
        tile_size = ts.tile_size
        map_w     = comp.config.get("map_width", 30)
        map_h     = comp.config.get("map_height", 17)
        col = canvas_x // tile_size
        row = canvas_y // tile_size
        if col < 0 or col >= map_w or row < 0 or row >= map_h:
            return
        tiles  = comp.config.get("tiles", [])
        needed = map_w * map_h
        if len(tiles) < needed:
            tiles.extend([-1] * (needed - len(tiles)))
            comp.config["tiles"] = tiles
        flat_idx   = row * map_w + col
        tile_index = self._tile_palette_ref.selected_tile()
        if tiles[flat_idx] != tile_index:
            tiles[flat_idx] = tile_index
            self.scene_changed.emit()
            self.update()

    def _apply_scalar_grid_brush(
        self,
        comp,
        tool: dict,
        cells: list[int],
        map_w: int,
        map_h: int,
        center_col: int,
        center_row: int,
        paint_value: int,
    ) -> bool:
        brush_mode = str(comp.config.get(str(tool.get("brush_mode_key", "brush_mode")), "set") or "set")
        radius = max(0, int(comp.config.get(str(tool.get("brush_radius_key", "brush_radius")), 0) or 0))
        strength = max(1, min(255, int(comp.config.get(str(tool.get("brush_strength_key", "brush_strength")), 48) or 48)))
        paint_value = max(0, min(255, int(paint_value)))
        changed = False

        def _apply_at(c: int, r: int, falloff: float):
            nonlocal changed
            if c < 0 or c >= map_w or r < 0 or r >= map_h:
                return
            idx = r * map_w + c
            current = max(0, min(255, int(cells[idx] or 0)))
            if brush_mode == "add":
                delta = max(1, int(round(strength * falloff)))
                new_val = min(255, current + delta)
            elif brush_mode == "subtract":
                delta = max(1, int(round(strength * falloff)))
                new_val = max(0, current - delta)
            else:
                if radius <= 0:
                    new_val = paint_value
                else:
                    target = int(round(paint_value * falloff))
                    blend = max(1, int(round(strength * falloff)))
                    if current < target:
                        new_val = min(target, current + blend)
                    else:
                        new_val = max(target, current - blend)
            if new_val != current:
                cells[idx] = new_val
                changed = True

        if radius <= 0:
            _apply_at(center_col, center_row, 1.0)
            return changed

        radius_sq = radius * radius
        for r in range(center_row - radius, center_row + radius + 1):
            for c in range(center_col - radius, center_col + radius + 1):
                dc = c - center_col
                dr = r - center_row
                dist_sq = dc * dc + dr * dr
                if dist_sq > radius_sq:
                    continue
                dist = dist_sq ** 0.5
                falloff = max(0.0, 1.0 - (dist / (radius + 0.001)))
                if falloff <= 0.0:
                    continue
                _apply_at(c, r, falloff)
        return changed

    def _world_size(self) -> tuple[int, int]:
        """Return (world_w, world_h) in pixels from TileLayers or Camera object bounds."""
        if self._scene is None:
            return VITA_W, VITA_H
        best_w, best_h = VITA_W, VITA_H
        for comp in self._scene.components:
            if comp.component_type != "TileLayer":
                continue
            ts_id = comp.config.get("tileset_id")
            ts = self._project.get_tileset(ts_id) if self._project and ts_id else None
            tsz = ts.tile_size if ts else 32
            w = comp.config.get("map_width",  30) * tsz
            h = comp.config.get("map_height", 17) * tsz
            best_w = max(best_w, w)
            best_h = max(best_h, h)
        # Also check Camera objects placed in this scene
        if self._project:
            for po in self._scene.placed_objects:
                od = self._project.get_object_def(po.object_def_id)
                if od and od.behavior_type == "Camera" and od.camera_bounds_enabled:
                    best_w = max(best_w, od.camera_bounds_width)
                    best_h = max(best_h, od.camera_bounds_height)
        return best_w, best_h

    def _clamp_cam(self):
        ww, wh = self._world_size()
        self._cam_x = max(0, min(self._cam_x, ww - VITA_W))
        self._cam_y = max(0, min(self._cam_y, wh - VITA_H))

    def set_snap(self, v):
        self._snap = v

    def clear(self):
        self._scene = None
        self._project = None
        self._selected_row = -1
        self._tile_paint_mode = False
        self._grid_paint_mode = False
        self._grid_tool_comp = None
        self._grid_tool = None
        self._path_draw_mode = False
        self._path_draw_comp = None
        self._path_draw_tool = None
        self.update()

    def _load_pixmap(self, path):
        if not path:
            return None
        if path in self._pixmap_cache:
            return self._pixmap_cache[path]
        p = QPixmap(path)
        if p.isNull():
            return None
        self._pixmap_cache[path] = p
        return p

    def _img_path(self, image_id):
        if not self._project or not image_id:
            return None
        r = self._project.get_image(image_id)
        return r.path if r else None

    def _obj_pixmap(self, po):
        if not self._project:
            return None
        od = self._project.get_object_def(po.object_def_id)
        if not od:
            return None
        # ── Still-sprite path (existing behaviour) ──
        if od.frames:
            path = self._img_path(od.frames[0].image_id)
            return self._load_pixmap(path) if path else None
        # ── Animation object: crop first frame from spritesheet ──
        _ani_fid = od.ani_slots[0].get("ani_file_id", "") if od.ani_slots else ""
        if od.behavior_type == "Animation" and _ani_fid:
            ani = self._project.get_animation_export(_ani_fid)
            if ani and ani.spritesheet_path and self._project.project_folder:
                cache_key = f"__ani_frame0__{ani.id}"
                if cache_key in self._pixmap_cache:
                    return self._pixmap_cache[cache_key]
                import os
                sheet_abs = os.path.join(self._project.project_folder,
                                         "animations", ani.spritesheet_path)
                sheet = QPixmap(sheet_abs)
                if sheet.isNull():
                    return None
                frame = sheet.copy(0, 0, ani.frame_width, ani.frame_height)
                self._pixmap_cache[cache_key] = frame
                return frame
        # ── LayerAnimation object: composite paper doll layers ──
        if od.behavior_type == "LayerAnimation" and od.layer_anim_id:
            doll = self._project.get_paper_doll(od.layer_anim_id)
            if doll and doll.root_layers:
                cache_key = f"__layer_anim__{doll.id}"
                if cache_key in self._pixmap_cache:
                    return self._pixmap_cache[cache_key]
                composite = self._composite_paper_doll(doll)
                if composite and not composite.isNull():
                    self._pixmap_cache[cache_key] = composite
                    return composite
        return None

    def _obj_rect(self, po):
        px = self._obj_pixmap(po)
        if px is None:
            if self._project:
                od = self._project.get_object_def(po.object_def_id)
                if od:
                    return QRect(po.x, po.y, int(od.width * po.scale), int(od.height * po.scale))
            return QRect(po.x, po.y, 64, 64)
        od = self._project.get_object_def(po.object_def_id) if self._project else None
        _ani_fid = od.ani_slots[0].get("ani_file_id", "") if (od and od.ani_slots) else ""
        if od and od.behavior_type == "Animation" and _ani_fid:
            return QRect(po.x, po.y, int(od.width * po.scale), int(od.height * po.scale))
        return QRect(po.x, po.y, int(px.width() * po.scale), int(px.height() * po.scale))

    def _composite_paper_doll(self, doll):
        """Flatten a PaperDollAsset's layer tree into a single QPixmap for preview.
        Uses a temporary QGraphicsScene so bounds are computed exactly the same
        way as PaperDollCanvas."""
        import os
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem
        if not self._project or not doll.root_layers:
            return None

        scene = QGraphicsScene()
        self._add_doll_layers_to_scene(scene, doll.root_layers, QTransform())

        bounds = scene.itemsBoundingRect()
        if bounds.isEmpty():
            return None

        result = QPixmap(int(bounds.width()), int(bounds.height()))
        result.fill(QColor(0, 0, 0, 0))
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scene.render(p, source=bounds)
        p.end()
        return result

    def _add_doll_layers_to_scene(self, scene, layers, parent_tf):
        """Recursively add paper doll layer pixmaps to a QGraphicsScene
        with the same transform math as PaperDollCanvas._draw_layers."""
        import os
        for layer in layers:
            tf = QTransform()
            tf.translate(layer.x, layer.y)
            tf.translate(layer.origin_x, layer.origin_y)
            tf.rotate(layer.rotation)
            tf.scale(layer.scale, layer.scale)
            tf.translate(-layer.origin_x, -layer.origin_y)
            composed = tf * parent_tf

            if layer.image_id:
                img = self._project.get_image(layer.image_id)
                if img and img.path and os.path.isfile(img.path):
                    pix = self._load_pixmap(img.path)
                    if pix and not pix.isNull():
                        item = scene.addPixmap(pix)
                        item.setTransform(composed)

            self._add_doll_layers_to_scene(scene, layer.children, composed)

    def _snap_v(self, v):
        if self._snap and self._grid_size > 0:
            return round(v / self._grid_size) * self._grid_size
        return v

    def _row_at(self, pos):
        if not self._scene:
            return -1
        # Convert screen position to world position
        world_pos = pos + QPoint(self._cam_x, self._cam_y)
        for i in range(len(self._scene.placed_objects) - 1, -1, -1):
            po = self._scene.placed_objects[i]
            if not po.visible:
                continue
            if self._obj_rect(po).contains(world_pos):
                return i
        return -1

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(0, 0, VITA_W, VITA_H, QColor("#000"))

        if self._scene is None:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No scene selected")
            return

        # Apply camera offset — all world-space drawing uses this transform
        p.translate(-self._cam_x, -self._cam_y)

        # Collect Layer components
        layer_comps = sorted(
            [c for c in self._scene.components if c.component_type == "Layer"],
            key=lambda c: c.config.get("layer", 0)
        )

        # Build layer_id → comp map for object grouping
        layer_by_id = {c.id: c for c in layer_comps}

        # Unified draw_slots: TileLayers, Layers, and objects all sorted together
        draw_slots = []

        # TileLayer components — participate in draw_layer ordering
        for comp in self._scene.components:
            if comp.component_type == "TileLayer":
                draw_slots.append((comp.config.get("draw_layer", 0), "tile_layer", comp))

        # Layer components
        for lc in layer_comps:
            draw_slots.append((lc.config.get("layer", 0), "layer_img", lc))

        # Placed objects: layer-assigned → their layer's number + 0.5, unassigned → draw_layer
        obj_groups: dict = {}  # sort_key → [po, ...]
        for po in self._scene.placed_objects:
            if not po.visible:
                continue
            lid = getattr(po, "layer_id", "")
            if lid and lid in layer_by_id:
                key = layer_by_id[lid].config.get("layer", 0) + 0.5
            else:
                key = getattr(po, "draw_layer", 2)
            obj_groups.setdefault(key, []).append(po)

        for key, objects in obj_groups.items():
            draw_slots.append((key, "objects", objects))

        draw_slots.sort(key=lambda e: e[0])

        for _order, kind, payload in draw_slots:
            if kind == "tile_layer":
                comp = payload
                ts_id = comp.config.get("tileset_id")
                if not ts_id or self._project is None:
                    continue
                ts = self._project.get_tileset(ts_id)
                if ts is None or not ts.path or ts.tile_size == 0 or ts.columns == 0:
                    continue
                pix = self._load_pixmap(ts.path)
                if pix is None:
                    continue
                tiles   = comp.config.get("tiles", [])
                map_w   = comp.config.get("map_width", 30)
                map_h   = comp.config.get("map_height", 17)
                tsz     = ts.tile_size
                src_w   = pix.width()  // ts.columns
                src_h   = pix.height() // ts.rows
                for row in range(map_h):
                    for col in range(map_w):
                        flat = row * map_w + col
                        if flat >= len(tiles):
                            continue
                        tile_idx = tiles[flat]
                        if tile_idx < 0:
                            continue
                        tc = tile_idx % ts.columns
                        tr = tile_idx // ts.columns
                        src_rect  = QRect(tc * src_w, tr * src_h, src_w, src_h)
                        dest_rect = QRect(col * tsz, row * tsz, tsz, tsz)
                        p.drawPixmap(dest_rect, pix, src_rect)
                # Grid overlay when in paint mode for this layer
                if self._tile_paint_mode and self._tile_layer_comp is comp:
                    p.save()
                    p.setPen(QPen(QColor(ACCENT + "55"), 1))
                    for col in range(map_w + 1):
                        x = col * tsz
                        p.drawLine(x, 0, x, map_h * tsz)
                    for row in range(map_h + 1):
                        y = row * tsz
                        p.drawLine(0, y, map_w * tsz, y)
                    p.restore()
            elif kind == "layer_img":
                lc = payload
                if not lc.config.get("visible", True):
                    continue
                path = self._img_path(lc.config.get("image_id"))
                if path:
                    px = self._load_pixmap(path)
                    if px:
                        p.drawPixmap(0, 0, px)
            else:
                for po in payload:
                    px = self._obj_pixmap(po)
                    if px is None:
                        p.save()
                        p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
                        p.setBrush(QBrush(QColor(ACCENT + "33")))
                        od = self._project.get_object_def(po.object_def_id) if self._project else None
                        w = int((od.width if od else 64) * po.scale)
                        h = int((od.height if od else 64) * po.scale)
                        p.drawRect(po.x, po.y, w, h)
                        p.setPen(QColor(TEXT))
                        p.drawText(po.x + 4, po.y + 14, od.name if od else "?")
                        p.restore()
                        continue
                    # For Animation objects, use od.width/height as the intended
                    # display size — the spritesheet frame may have been downscaled
                    # to fit within the 2048x2048 sheet limit.
                    od = self._project.get_object_def(po.object_def_id) if self._project else None
                    _ani_fid = od.ani_slots[0].get("ani_file_id", "") if (od and od.ani_slots) else ""
                    if od and od.behavior_type == "Animation" and _ani_fid:
                        w = int(od.width * po.scale)
                        h = int(od.height * po.scale)
                    else:
                        w = int(px.width() * po.scale)
                        h = int(px.height() * po.scale)
                    p.save()
                    p.setOpacity(po.opacity)
                    if po.rotation != 0.0:
                        cx, cy = po.x + w / 2, po.y + h / 2
                        p.translate(cx, cy)
                        p.rotate(po.rotation)
                        p.translate(-w / 2, -h / 2)
                        p.drawPixmap(0, 0, w, h, px)
                    else:
                        p.drawPixmap(po.x, po.y, w, h, px)
                    p.restore()

        # Grid-map editor tools — always drawn on top as editor overlays
        for comp in self._scene.components:
            tool = _component_editor_tool(self._project, comp, "grid_map")
            if not tool:
                continue
            if "visible" in comp.config and not comp.config.get("visible", True):
                continue
            data_key = str(tool.get("data_key", "tiles"))
            width_key = str(tool.get("width_key", "map_width"))
            height_key = str(tool.get("height_key", "map_height"))
            cell_size_key = str(tool.get("cell_size_key", "tile_size"))
            tile_size = max(1, int(comp.config.get(cell_size_key, 32) or 32))
            map_w = max(1, int(comp.config.get(width_key, 1) or 1))
            map_h = max(1, int(comp.config.get(height_key, 1) or 1))
            values = comp.config.get(data_key, []) or []
            mode = str(tool.get("mode", "binary"))
            base_color = str(tool.get("overlay_color", "") or "").strip()
            color_key = str(tool.get("overlay_color_key", "") or "").strip()
            if color_key:
                base_color = str(comp.config.get(color_key, base_color or "#ff5050"))
            if not base_color:
                base_color = "#ff5050"
            color = QColor(base_color)
            is_active = self._grid_paint_mode and self._grid_tool_comp is comp
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            for row in range(map_h):
                for col in range(map_w):
                    flat = row * map_w + col
                    if flat >= len(values):
                        continue
                    fill = QColor(color)
                    if mode == "binary":
                        active_value = tool.get("active_value", 1)
                        if values[flat] != active_value:
                            continue
                        fill.setAlpha(120 if is_active else 100)
                    else:
                        opacity_key = str(tool.get("opacity_key", "") or "").strip()
                        layer_opacity = max(0, min(255, int(comp.config.get(opacity_key, 255) if opacity_key else 255)))
                        dark = max(0, min(255, int(values[flat] or 0)))
                        if dark <= 0:
                            continue
                        fill.setAlpha(max(12, min(220, (dark * layer_opacity) // 255)))
                    p.setBrush(QBrush(fill))
                    p.drawRect(col * tile_size, row * tile_size, tile_size, tile_size)
            grid_color = QColor(color)
            grid_color.setAlpha(120 if is_active else 68)
            p.setPen(QPen(grid_color, 1))
            for col in range(map_w + 1):
                x = col * tile_size
                p.drawLine(x, 0, x, map_h * tile_size)
            for row in range(map_h + 1):
                y = row * tile_size
                p.drawLine(0, y, map_w * tile_size, y)
            p.restore()

        if 0 <= self._selected_row < len(self._scene.placed_objects):
            po = self._scene.placed_objects[self._selected_row]
            rect = self._obj_rect(po)
            if rect:
                p.save()
                p.setPen(QPen(QColor(ACCENT), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rect.adjusted(-2, -2, 2, 2))
                p.setBrush(QColor(ACCENT))
                hs = 6
                for hx, hy in [(rect.left()-3, rect.top()-3), (rect.right()-3, rect.top()-3),
                               (rect.left()-3, rect.bottom()-3), (rect.right()-3, rect.bottom()-3)]:
                    p.drawRect(hx, hy, hs, hs)
                p.restore()

        # Reset to screen space for fixed overlays
        p.resetTransform()

        if self._scene.has_component("VNDialogBox"):
            comp = self._scene.get_component("VNDialogBox")
            cfg  = comp.config if comp else {}
            p.save()
            p.setOpacity(0.85)
            p.fillRect(40, 335, 880, 200, QColor(0, 0, 0, 200))
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawRoundedRect(40, 335, 880, 200, 6, 6)
            p.setOpacity(1.0)
            # Pull first page from dialog_pages
            pages = cfg.get("dialog_pages", [])
            page0 = pages[0] if pages else {}
            speaker = page0.get("character", "")
            if speaker:
                tag_w = max(120, len(speaker) * 9 + 24)
                p.fillRect(60, 310, tag_w, 26, QColor(40, 40, 80, 220))
                p.setPen(QColor(255, 255, 255))
                from PySide6.QtGui import QFont as _QFont
                p.setFont(_QFont("Segoe UI", 11, _QFont.Weight.Bold))
                p.drawText(70, 328, speaker)
            lines = [l for l in page0.get("lines", []) if l.strip()]
            from PySide6.QtGui import QFont as _QFont
            p.setFont(_QFont("Segoe UI", 11))
            p.setPen(QColor(240, 240, 240))
            for i, line in enumerate(lines[:4]):
                p.drawText(70, 365 + i * 26, line)
            if len(pages) > 1:
                p.setPen(QColor(180, 180, 220, 140))
                p.setFont(_QFont("Segoe UI", 9))
                p.drawText(820, 528, f"1/{len(pages)}")
            p.restore()

        if self._scene.has_component("ChoiceMenu"):
            p.save()
            p.setOpacity(0.6)
            p.fillRect(280, 140, 400, 260, QColor(0, 0, 0, 160))
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawRoundedRect(280, 140, 400, 260, 6, 6)
            p.restore()

        if self._grid_visible and self._grid_size > 0:
            p.save()
            gs = self._grid_size
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            x = gs
            while x < VITA_W:
                p.drawLine(x, 0, x, VITA_H); x += gs
            y = gs
            while y < VITA_H:
                p.drawLine(0, y, VITA_W, y); y += gs
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            major = gs * 4
            x = major
            while x < VITA_W:
                p.drawLine(x, 0, x, VITA_H); x += major
            y = major
            while y < VITA_H:
                p.drawLine(0, y, VITA_W, y); y += major
            p.restore()

        # Camera position HUD — shown whenever camera is not at origin
        if self._cam_x != 0 or self._cam_y != 0:
            ww, wh = self._world_size()
            hud = f"cam ({self._cam_x}, {self._cam_y})  world {ww}×{wh}"
            p.save()
            p.setOpacity(0.7)
            p.fillRect(6, 6, len(hud) * 7 + 12, 18, QColor(0, 0, 0, 160))
            p.setOpacity(1.0)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(12, 19, hud)
            p.restore()

        # ── Draw all Path components (always visible on canvas) ──────────────
        if self._scene:
            from PySide6.QtGui import QPainterPath as QPPath
            for comp in self._scene.components:
                tool = _component_editor_tool(self._project, comp, "path")
                if not tool:
                    continue
                points_key = str(tool.get("points_key", "points"))
                closed_key = str(tool.get("closed_key", "closed"))
                pts = comp.config.get(points_key, [])
                if len(pts) < 1:
                    continue
                is_active = (self._path_draw_mode and self._path_draw_comp
                             and self._path_draw_comp.id == comp.id)
                path_color = QColor("#06b6d4") if is_active else QColor("#06b6d4")
                path_color.setAlpha(200 if is_active else 100)

                # Draw the bezier curve
                if len(pts) >= 2:
                    pp = QPPath()
                    p0 = pts[0]
                    pp.moveTo(p0["x"] - self._cam_x, p0["y"] - self._cam_y)
                    n = len(pts)
                    count = n if comp.config.get(closed_key, False) else n - 1
                    for si in range(count):
                        a = pts[si]
                        b = pts[(si + 1) % n]
                        cx0 = a["x"] + a.get("cx2", 0) - self._cam_x
                        cy0 = a["y"] + a.get("cy2", 0) - self._cam_y
                        cx1 = b["x"] + b.get("cx1", 0) - self._cam_x
                        cy1 = b["y"] + b.get("cy1", 0) - self._cam_y
                        bx  = b["x"] - self._cam_x
                        by  = b["y"] - self._cam_y
                        pp.cubicTo(cx0, cy0, cx1, cy1, bx, by)
                    pen = QPen(path_color, 2.5 if is_active else 1.5)
                    pen.setStyle(Qt.PenStyle.SolidLine)
                    p.setPen(pen)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(pp)

                # Draw anchor points and handles (only when in draw mode for this path)
                if is_active:
                    handle_pen = QPen(QColor("#ffffff"), 1)
                    handle_line_pen = QPen(QColor(255, 255, 255, 80), 1, Qt.PenStyle.DashLine)
                    for i, pt in enumerate(pts):
                        ax = pt["x"] - self._cam_x
                        ay = pt["y"] - self._cam_y
                        # Control handle lines and circles
                        for hx_key, hy_key in (("cx1", "cy1"), ("cx2", "cy2")):
                            hx = pt.get(hx_key, 0)
                            hy = pt.get(hy_key, 0)
                            if hx != 0 or hy != 0:
                                p.setPen(handle_line_pen)
                                p.drawLine(int(ax), int(ay), int(ax + hx), int(ay + hy))
                                p.setPen(handle_pen)
                                p.setBrush(QColor("#06b6d4"))
                                p.drawEllipse(int(ax + hx) - 4, int(ay + hy) - 4, 8, 8)
                        # Anchor square
                        p.setPen(QPen(QColor("#ffffff"), 1))
                        p.setBrush(QColor("#06b6d4") if i > 0 else QColor("#4ade80"))
                        p.drawRect(int(ax) - 5, int(ay) - 5, 10, 10)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self._pan_cam_origin = (self._cam_x, self._cam_y)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return

        pos = event.position().toPoint()
        wx = pos.x() + self._cam_x
        wy = pos.y() + self._cam_y

        # ── Path draw mode ──────────────────────────────────────
        if self._path_draw_mode and self._path_draw_comp:
            points_key = str((self._path_draw_tool or {}).get("points_key", "points"))
            pts = self._path_draw_comp.config.setdefault(points_key, [])
            if event.button() == Qt.MouseButton.RightButton:
                # Right-click: delete nearest point
                idx, _ = self._path_hit_test(wx, wy, radius=12)
                if idx >= 0:
                    pts.pop(idx)
                    self.scene_changed.emit()
                self.update()
                return
            if event.button() != Qt.MouseButton.LeftButton:
                return
            # Left-click: check if we hit an existing point/handle
            idx, handle = self._path_hit_test(wx, wy)
            if idx >= 0:
                self._path_drag_idx    = idx
                self._path_drag_handle = handle
            else:
                # Add new point at click position
                new_pt = {"x": wx, "y": wy, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0}
                pts.append(new_pt)
                self._path_drag_idx    = len(pts) - 1
                self._path_drag_handle = "anchor"
                self.scene_changed.emit()
            self.update()
            return

        if self._grid_paint_mode or self._tile_paint_mode:
            if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                return
            self._tile_painting = True
            if self._grid_paint_mode:
                self._grid_erase_mode = event.button() == Qt.MouseButton.RightButton
            world_x = pos.x() + self._cam_x
            world_y = pos.y() + self._cam_y
            self._paint_tile_at(world_x, world_y)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        row = self._row_at(pos)
        if row >= 0:
            self._selected_row = row
            self.object_selected.emit(row)
            po = self._scene.placed_objects[row]
            self._dragging      = True
            self._drag_instance = po
            self._drag_offset   = pos - QPoint(po.x - self._cam_x, po.y - self._cam_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._selected_row = -1
            self.object_selected.emit(-1)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._panning:
            dx = pos.x() - self._pan_origin.x()
            dy = pos.y() - self._pan_origin.y()
            self._cam_x = self._pan_cam_origin[0] - dx
            self._cam_y = self._pan_cam_origin[1] - dy
            self._clamp_cam()
            self.update()
            return
        # ── Path draw drag ──────────────────────────────────────
        if self._path_draw_mode and self._path_draw_comp and self._path_drag_idx >= 0:
            points_key = str((self._path_draw_tool or {}).get("points_key", "points"))
            pts = self._path_draw_comp.config.get(points_key, [])
            if self._path_drag_idx < len(pts):
                pt = pts[self._path_drag_idx]
                wx = pos.x() + self._cam_x
                wy = pos.y() + self._cam_y
                if self._path_drag_handle == "anchor":
                    if bool((self._path_draw_tool or {}).get("supports_bezier")) and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        dx = wx - pt["x"]
                        dy = wy - pt["y"]
                        pt["cx2"] = dx
                        pt["cy2"] = dy
                        pt["cx1"] = -dx
                        pt["cy1"] = -dy
                    else:
                        pt["x"] = wx
                        pt["y"] = wy
                elif self._path_drag_handle == "cx1":
                    pt["cx1"] = wx - pt["x"]
                    pt["cy1"] = wy - pt["y"]
                elif self._path_drag_handle == "cx2":
                    pt["cx2"] = wx - pt["x"]
                    pt["cy2"] = wy - pt["y"]
                self.scene_changed.emit()
                self.update()
            return
        if self._path_draw_mode:
            return
        if self._grid_paint_mode or self._tile_paint_mode:
            if self._tile_painting:
                self._paint_tile_at(pos.x() + self._cam_x, pos.y() + self._cam_y)
            return
        if not self._dragging or self._drag_instance is None:
            if self._scene and self._row_at(pos) >= 0:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        world_x = self._snap_v(pos.x() - self._drag_offset.x() + self._cam_x)
        world_y = self._snap_v(pos.y() - self._drag_offset.y() + self._cam_y)
        self._drag_instance.x = world_x
        self._drag_instance.y = world_y
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(
                Qt.CursorShape.CrossCursor if (self._tile_paint_mode or self._grid_paint_mode or self._path_draw_mode)
                else Qt.CursorShape.ArrowCursor
            )
            return
        # ── Path draw release ───────────────────────────────────
        if self._path_draw_mode:
            if event.button() == Qt.MouseButton.LeftButton:
                self._path_drag_idx    = -1
                self._path_drag_handle = ""
            return
        if self._grid_paint_mode or self._tile_paint_mode:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self._tile_painting = False
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._dragging:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._drag_instance is not None:
            self.object_moved.emit(
                self._drag_instance.instance_id,
                self._drag_instance.x,
                self._drag_instance.y,
            )
        self._drag_instance = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._path_draw_mode:
            self.exit_path_draw()
            return
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────
#  SCENE LIST PANEL
# ─────────────────────────────────────────────────────────────

class SceneListPanel(QWidget):
    scene_selected       = Signal(int)
    scene_added          = Signal()
    scene_deleted        = Signal(int)
    scene_moved          = Signal(int, int)
    scene_duplicated     = Signal(int)
    scene_save_requested = Signal(int)
    scene_load_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("SCENES")
        title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
        )
        header.addWidget(title)
        header.addStretch()
        add_btn = _small_btn("+", "Add scene", accent=True)
        add_btn.clicked.connect(self.scene_added.emit)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 3px;
                border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        self.list_widget.currentRowChanged.connect(lambda r: self.scene_selected.emit(r) if r >= 0 else None)
        layout.addWidget(self.list_widget)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        for lbl, tip, slot, dan in [
            ("D", "Duplicate", lambda: self.scene_duplicated.emit(self.list_widget.currentRow()) if self.list_widget.currentRow() >= 0 else None, False),
            ("x", "Delete",    lambda: self.scene_deleted.emit(self.list_widget.currentRow())    if self.list_widget.currentRow() >= 0 else None, True),
            ("↑", "Move up",   self._move_up,   False),
            ("↓", "Move down", self._move_down, False),
        ]:
            b = _small_btn(lbl, tip, danger=dan)
            b.clicked.connect(slot)
            controls.addWidget(b)

        controls.addSpacing(8)
        for lbl, tip, slot in [
            ("S", "Save scene",  lambda: self.scene_save_requested.emit(self.list_widget.currentRow()) if self.list_widget.currentRow() >= 0 else None),
            ("L", "Load scene",  lambda: self.scene_load_requested.emit()),
        ]:
            b = _small_btn(lbl, tip)
            b.clicked.connect(slot)
            controls.addWidget(b)

        controls.addStretch()
        layout.addLayout(controls)

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.scene_moved.emit(row, row - 1)

    def _move_down(self):
        row = self.list_widget.currentRow()
        if row >= 0 and row < self.list_widget.count() - 1:
            self.scene_moved.emit(row, row + 1)

    def refresh(self, scenes: list, current_index: int):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for i, scene in enumerate(scenes):
            badge = "[3D] " if getattr(scene, "scene_type", "2d") == "3d" else ""
            item = QListWidgetItem(f"{i+1:02d}  {badge}{scene.get_summary()}")
            color = "#7c6aff" if badge else ROLE_COLORS.get(scene.role, TEXT_DIM)
            item.setForeground(QColor(color if i != current_index else "#ffffff"))
            self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(current_index)
        self.list_widget.blockSignals(False)

    def select_row(self, index: int):
        self.list_widget.blockSignals(True)
        self.list_widget.setCurrentRow(index)
        self.list_widget.blockSignals(False)


# ─────────────────────────────────────────────────────────────
#  EDITOR TAB
# ─────────────────────────────────────────────────────────────

class EditorTab(QWidget):
    instance_changed = Signal()
    object_def_created = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self._project: Project | None = None
        self._scene:   Scene   | None = None
        self._build_ui()

    def _build_ui(self):
        self._active_grid_comp_id: str | None = None
        self._active_tile_layer_comp_id: str | None = None
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── LEFT ─────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        obj_panel = QWidget()
        obj_panel.setStyleSheet(f"background: {PANEL};")
        op = QVBoxLayout(obj_panel)
        op.setContentsMargins(8, 8, 8, 6)
        op.setSpacing(4)

        oh = QHBoxLayout()
        ot = QLabel("OBJECTS IN SCENE")
        ot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;")
        oh.addWidget(ot)
        oh.addStretch()
        pb = _small_btn("+", "Place object", accent=True)
        pb.clicked.connect(self._place_object)
        rb = _small_btn("x", "Remove from scene", danger=True)
        rb.clicked.connect(self._remove_object)
        oh.addWidget(pb)
        oh.addWidget(rb)
        op.addLayout(oh)

        self.objects_list = QListWidget()
        self.objects_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 3px;
                border-bottom: 1px solid {BORDER}; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE2}; }}
        """)
        self.objects_list.currentRowChanged.connect(self._on_instance_selected)
        op.addWidget(self.objects_list)

        ordr = QHBoxLayout()
        ordr.setSpacing(4)
        ub = _small_btn("↑", "Move layer up")
        ub.clicked.connect(self._move_obj_up)
        db = _small_btn("↓", "Move layer down")
        db.clicked.connect(self._move_obj_dn)
        ordr.addWidget(ub)
        ordr.addWidget(db)
        ordr.addStretch()
        op.addLayout(ordr)

        lv.addWidget(obj_panel, stretch=1)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {BORDER}; border: none;")
        lv.addWidget(div)

        self.scene_list_panel = SceneListPanel()
        self.scene_list_panel.scene_selected.connect(self.mw.on_scene_selected)
        self.scene_list_panel.scene_added.connect(self.mw.add_scene)
        self.scene_list_panel.scene_deleted.connect(self.mw.delete_scene)
        self.scene_list_panel.scene_moved.connect(self.mw.move_scene)
        self.scene_list_panel.scene_duplicated.connect(self.mw.duplicate_scene)
        self.scene_list_panel.scene_save_requested.connect(self.mw.save_scene)
        self.scene_list_panel.scene_load_requested.connect(self.mw.load_scene)
        lv.addWidget(self.scene_list_panel, stretch=1)
        root.addWidget(left)

        # ── CENTER ───────────────────────────────────────────
        center = QWidget()
        center.setStyleSheet(f"background: {DARK};")
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        # Toolbar
        tb_widget = QWidget()
        tb_widget.setFixedHeight(36)
        tb_widget.setStyleSheet(f"background: {PANEL}; border-bottom: 1px solid {BORDER};")
        tb = QHBoxLayout(tb_widget)
        tb.setContentsMargins(12, 0, 12, 0)
        tb.setSpacing(12)

        sl = QLabel("VITA SCREEN  •  960 × 544  •  1:1")
        sl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; letter-spacing: 1px; font-weight: 600;")
        tb.addWidget(sl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {BORDER}; max-width: 1px;")
        tb.addWidget(sep)

        fs = _field_style()
        self.grid_check = QCheckBox("Grid")
        self.grid_check.setStyleSheet(fs)
        self.grid_check.stateChanged.connect(lambda v: self.canvas.set_grid_visible(bool(v)))
        tb.addWidget(self.grid_check)

        gsl = QLabel("Size:")
        gsl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        tb.addWidget(gsl)

        self.grid_combo = QComboBox()
        self.grid_combo.setStyleSheet(fs)
        self.grid_combo.setFixedWidth(64)
        for s in (8, 16, 32, 48, 64):
            self.grid_combo.addItem(str(s), s)
        self.grid_combo.setCurrentIndex(2)
        self.grid_combo.currentIndexChanged.connect(
            lambda: self.canvas.set_grid_size(self.grid_combo.currentData()))
        tb.addWidget(self.grid_combo)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color: {BORDER}; max-width: 1px;")
        tb.addWidget(sep2)

        self.snap_check = QCheckBox("Snap")
        self.snap_check.setStyleSheet(fs)
        self.snap_check.stateChanged.connect(lambda v: self.canvas.set_snap(bool(v)))
        tb.addWidget(self.snap_check)
        tb.addStretch()

        self.coord_lbl = QLabel("x: —  y: —")
        self.coord_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        tb.addWidget(self.coord_lbl)
        cv.addWidget(tb_widget)

        # Canvas
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(False)
        scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll_area.setStyleSheet(f"background: {DARK}; border: none;")
        self.canvas = VitaCanvas()
        self.canvas.object_moved.connect(self._on_obj_moved)
        self.canvas.object_selected.connect(self._on_canvas_selected)
        self.canvas.scene_changed.connect(self._on_canvas_scene_changed)
        _orig = self.canvas.mouseMoveEvent
        def _mm(event, _o=_orig):
            pos = event.position().toPoint()
            self.coord_lbl.setText(f"x: {pos.x()}  y: {pos.y()}")
            _o(event)
        self.canvas.mouseMoveEvent = _mm
        scroll_area.setWidget(self.canvas)
        cv.addWidget(scroll_area, stretch=1)

        # Bottom panel: QStackedWidget switching between ProjectExplorer and TilePalette
        self._bottom_stack = QStackedWidget()
        self._bottom_stack.setFixedHeight(150)

        self.project_explorer = ProjectExplorer()
        self._bottom_stack.addWidget(self.project_explorer)   # index 0

        self.tile_palette = TilePalette()
        self.tile_palette.tile_selected.connect(self._on_palette_tile_selected)
        self.tile_palette.paint_mode_changed.connect(self._on_paint_mode_changed)
        self._bottom_stack.addWidget(self.tile_palette)       # index 1

        self._bottom_stack.setCurrentIndex(0)
        cv.addWidget(self._bottom_stack)

        # Info bar
        ib_widget = QWidget()
        ib_widget.setFixedHeight(32)
        ib_widget.setStyleSheet(f"background: {PANEL}; border-top: 1px solid {BORDER};")
        ib = QHBoxLayout(ib_widget)
        ib.setContentsMargins(12, 0, 12, 0)
        ib.setSpacing(20)
        self.info_index = self._pair("Scene", "—")
        self.info_role  = self._pair("Role",  "—")
        self.info_comps = self._pair("Components", "0")
        self.info_objs  = self._pair("Objects", "0")
        for lbl, val in (self.info_index, self.info_role, self.info_comps, self.info_objs):
            pr = QHBoxLayout()
            pr.setSpacing(4)
            pr.addWidget(lbl)
            pr.addWidget(val)
            ib.addLayout(pr)
        ib.addStretch()
        cv.addWidget(ib_widget)
        root.addWidget(center, stretch=1)

        # ── RIGHT — INSPECTOR ────────────────────────────────
        self.inspector = TabbedInspector()
        self.inspector.setFixedWidth(292)
        self.inspector.changed.connect(self._on_inspector_changed)
        self.inspector.tile_layer_selected.connect(self._on_tile_layer_selected)
        self.inspector.path_draw_requested.connect(self._on_path_draw_requested)
        self.canvas.path_mode_changed.connect(self.inspector.set_active_path_component_id)
        root.addWidget(self.inspector)
        self._left_panel = left
        self._tb_widget = tb_widget
        self._ib_widget = ib_widget
        self._scroll_area = scroll_area

    def set_explorer_visible(self, visible: bool):
        """Show or hide the bottom panel (project explorer or tile palette)."""
        self._bottom_stack.setVisible(visible)

    def _show_tile_palette(self, tileset_id: str | None):
        """Switch bottom panel to tile palette for the given tileset."""
        if self._project:
            self.tile_palette.load_project(self._project)
        self.tile_palette.load_for_component(tileset_id)
        self._bottom_stack.setFixedHeight(180)
        self._bottom_stack.setCurrentIndex(1)

    def _show_project_explorer(self):
        """Switch bottom panel back to project explorer."""
        self._bottom_stack.setFixedHeight(150)
        self._bottom_stack.setCurrentIndex(0)

    def _show_grid_tool_painter(self, comp_id: str, erase: bool = False):
        """Activate grid-map paint mode for the given grid-backed component id."""
        if self._scene is None:
            return
        comp = next((c for c in self._scene.components if c.id == comp_id), None)
        if comp is None:
            return
        tool = _component_editor_tool(self._project, comp, "grid_map")
        if not tool:
            return
        if self._project:
            self.tile_palette.load_project(self._project)
        self.tile_palette.load_for_component(None)
        self._bottom_stack.setFixedHeight(60)
        self._bottom_stack.setCurrentIndex(1)
        self.canvas.set_grid_paint_mode(True, comp, tool, erase_mode=erase)

    def _on_tile_layer_selected(self, tileset_id: str):
        """Called when a tile layer or declarative editor tool button is clicked."""
        if tileset_id.startswith("__gridtool__:"):
            payload = tileset_id[len("__gridtool__:"):]
            comp_id, _, mode = payload.partition(":")
            self._active_grid_comp_id = comp_id or None
            self._active_tile_layer_comp_id = None
            self._show_grid_tool_painter(comp_id, erase=(mode == "erase"))
        elif tileset_id.startswith("__tilelayer__:"):
            payload = tileset_id[len("__tilelayer__:"):]
            comp_id, _, selected_tileset_id = payload.partition(":")
            self._active_grid_comp_id = None
            self._active_tile_layer_comp_id = comp_id or None
            self.canvas.set_grid_paint_mode(False, None, None)
            if self.canvas._path_draw_mode:
                self.canvas.exit_path_draw()
            self._show_tile_palette(selected_tileset_id or None)
            if self.tile_palette.is_paint_mode():
                tile_layer = self._get_active_tile_layer()
                ts = self.tile_palette.current_tileset()
                if tile_layer and ts:
                    self.canvas.set_tile_paint_mode(True, tile_layer, ts, self.tile_palette)
        elif tileset_id:
            self._active_grid_comp_id = None
            self._active_tile_layer_comp_id = None
            self.canvas.set_grid_paint_mode(False, None, None)
            self._show_tile_palette(tileset_id)
        else:
            self._active_grid_comp_id = None
            self._active_tile_layer_comp_id = None
            self.canvas.set_grid_paint_mode(False, None, None)
            self._show_project_explorer()

    def _on_paint_mode_changed(self, active: bool):
        """Toggle tile paint mode on the canvas."""
        if active:
            if getattr(self, "_active_grid_comp_id", None):
                return
            # Find the active TileLayer component
            tile_layer = self._get_active_tile_layer()
            ts = self.tile_palette.current_tileset()
            if tile_layer and ts:
                self.canvas.set_tile_paint_mode(True, tile_layer, ts, self.tile_palette)
            else:
                # No valid layer — turn button back off
                self.tile_palette.paint_btn.setChecked(False)
        else:
            self._active_grid_comp_id = None
            self.canvas.set_tile_paint_mode(False, None, None, None)

    def _get_active_tile_layer(self):
        """Return the TileLayer currently being edited, falling back to the first."""
        if self._scene is None:
            return None
        active_id = getattr(self, "_active_tile_layer_comp_id", None)
        if active_id:
            for comp in self._scene.components:
                if comp.id == active_id and comp.component_type == "TileLayer":
                    return comp
        for comp in self._scene.components:
            if comp.component_type == "TileLayer":
                return comp
        return None

    def _on_palette_tile_selected(self, index: int):
        """Palette tile clicked — update canvas brush."""
        self.canvas.set_paint_tile(index)

    def _on_path_draw_requested(self, comp_id: str):
        """Called when 'Draw Path' is clicked in the scene inspector."""
        if not self._scene:
            return
        # If already in path draw for this component, toggle off
        if (self.canvas._path_draw_mode and self.canvas._path_draw_comp
                and self.canvas._path_draw_comp.id == comp_id):
            self.canvas.exit_path_draw()
            return
        # Find the path-backed component by id
        for comp in self._scene.components:
            tool = _component_editor_tool(self._project, comp, "path")
            if comp.id == comp_id and tool:
                # Exit tile paint if active
                self.canvas.set_tile_paint_mode(False, None, None, None)
                self.canvas.set_grid_paint_mode(False, None, None)
                self.canvas.enter_path_draw(comp, tool)
                self.canvas.setFocus()       # grab keyboard for Escape
                return

    def restyle(self, c: dict):
        global DARK, PANEL, SURFACE, SURFACE2, BORDER, ACCENT, TEXT, TEXT_DIM, TEXT_MUTED, SUCCESS, WARNING, DANGER
        old = _theme_snapshot()
        DARK = c.get("DARK", DARK)
        PANEL = c.get("PANEL", PANEL)
        SURFACE = c.get("SURFACE", SURFACE)
        SURFACE2 = c.get("SURFACE2", SURFACE2)
        BORDER = c.get("BORDER", BORDER)
        ACCENT = c.get("ACCENT", ACCENT)
        TEXT = c.get("TEXT", TEXT)
        TEXT_DIM = c.get("TEXT_DIM", TEXT_DIM)
        TEXT_MUTED = c.get("TEXT_MUTED", TEXT_MUTED)
        SUCCESS = c.get("SUCCESS", SUCCESS)
        WARNING = c.get("WARNING", WARNING)
        DANGER = c.get("DANGER", DANGER)
        ROLE_COLORS.update({"start": SUCCESS, "end": DANGER, "": TEXT_DIM})

        # Push new colours into the module-level snapshot so all helpers and
        # dynamically-rebuilt widgets (_rebuild, _small_btn, etc.) use them.
        _current_theme.update(_theme_snapshot())
        _current_theme.update(c)
        replace_widget_theme_colors(self, old, _current_theme)

        # Re-apply stylesheet to every accent button built at construction time
        _ac = c["ACCENT"]
        _btn_ss = f"""
            QPushButton {{
                background-color: {_ac}; color: white; border: none;
                border-radius: 4px; font-size: 13px; font-weight: 700; padding: 0;
            }}
            QPushButton:hover {{ background-color: {_ac}cc; }}
        """
        for _b in _accent_buttons:
            _b.setStyleSheet(_btn_ss)

        self._left_panel.setStyleSheet(f"background: {c['PANEL']}; border-right: 1px solid {c['BORDER']};")
        self._tb_widget.setStyleSheet(f"background: {c['PANEL']}; border-bottom: 1px solid {c['BORDER']};")
        self._ib_widget.setStyleSheet(f"background: {c['PANEL']}; border-top: 1px solid {c['BORDER']};")
        self._scroll_area.setStyleSheet(f"background: {c['DARK']}; border: none;")
        if hasattr(self, 'project_explorer'):
            self.project_explorer.restyle(c)
        if hasattr(self, 'tile_palette'):
            self.tile_palette.restyle(c)
        self.objects_list.setStyleSheet(f"""
            QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                border-radius: 4px; color: {c['TEXT']}; outline: none; }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 3px; border-bottom: 1px solid {c['BORDER']}; }}
            QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
        """)
        self.scene_list_panel.list_widget.setStyleSheet(f"""
            QListWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
                border-radius: 4px; color: {c['TEXT']}; outline: none; }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 3px; border-bottom: 1px solid {c['BORDER']}; }}
            QListWidget::item:selected {{ background: {c['ACCENT']}; color: white; }}
            QListWidget::item:hover:!selected {{ background: {c['SURFACE2']}; }}
        """)
        self.inspector.restyle(c)

    def _pair(self, lbl_text, default):
        lbl = QLabel(lbl_text + ":")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-weight: 600;")
        val = QLabel(default)
        val.setStyleSheet(f"color: {TEXT}; font-size: 10px;")
        return lbl, val

    # ── Object list ops ───────────────────────────────────────

    def _place_object(self):
        if self._project is None or self._scene is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Place Object")
        dlg.setModal(True)
        dlg.setMinimumWidth(260)
        dlg.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(12, 12, 12, 12)
        dv.setSpacing(8)
        lbl = QLabel("Select an object definition to place:")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        dv.addWidget(lbl)
        lst = QListWidget()
        lst.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER};
                border-radius: 4px; color: {TEXT}; outline: none; }}
            QListWidget::item {{ padding: 7px 10px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
        """)
        default_item = QListWidgetItem("＋ Default Object")
        default_item.setData(Qt.ItemDataRole.UserRole, "__new__")
        default_item.setForeground(QColor(ACCENT))
        lst.addItem(default_item)
        for od in self._project.object_defs:
            item = QListWidgetItem(od.name)
            item.setData(Qt.ItemDataRole.UserRole, od.id)
            if od.behavior_type == "VNCharacter":
                item.setForeground(QColor("#f59e0b"))
            lst.addItem(item)
        lst.setCurrentRow(0)
        lst.doubleClicked.connect(dlg.accept)
        dv.addWidget(lst)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"color: {TEXT};")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dv.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        item = lst.currentItem()
        if not item:
            return
        import copy, json, uuid
        selected_id = item.data(Qt.ItemDataRole.UserRole)

        if selected_id == "__new__":
            # Second dialog: name + hidden checkbox
            dlg2 = QDialog(self)
            dlg2.setWindowTitle("New Default Object")
            dlg2.setModal(True)
            dlg2.setMinimumWidth(260)
            dlg2.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
            dv2 = QVBoxLayout(dlg2)
            dv2.setContentsMargins(12, 12, 12, 12)
            dv2.setSpacing(8)
            name_lbl = QLabel("Object name:")
            name_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            dv2.addWidget(name_lbl)
            name_edit = QLineEdit()
            name_edit.setPlaceholderText("Object name…")
            name_edit.setStyleSheet(f"background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 6px;")
            dv2.addWidget(name_edit)
            hidden_check = QCheckBox("Hidden by default")
            hidden_check.setStyleSheet(f"color: {TEXT};")
            hidden_check.setChecked(False)
            dv2.addWidget(hidden_check)
            btns2 = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            btns2.setStyleSheet(f"color: {TEXT};")
            btns2.accepted.connect(dlg2.accept)
            btns2.rejected.connect(dlg2.reject)
            dv2.addWidget(btns2)
            if dlg2.exec() != QDialog.DialogCode.Accepted:
                return
            obj_name = name_edit.text().strip() or "New Object"
            new_od = ObjectDefinition()
            new_od.id = str(uuid.uuid4())[:8]
            new_od.name = obj_name
            new_od.visible_default = not hidden_check.isChecked()
            self._project.object_defs.append(new_od)
            self.object_def_created.emit()
            selected_id = new_od.id

        po = PlacedObject()
        po.object_def_id = selected_id
        po.x, po.y = 400, 200
        od = self._project.get_object_def(po.object_def_id)
        seed_instance_behaviors_from_definition(po, od)
        if od and not od.visible_default:
            po.visible = False
        self._scene.placed_objects.append(po)
        self._refresh_objs()
        row = len(self._scene.placed_objects) - 1
        self.objects_list.setCurrentRow(row)
        self.canvas.set_selected_row(row)
        self.instance_changed.emit()

    def _remove_object(self):
        if self._scene is None:
            return
        row = self.objects_list.currentRow()
        if 0 <= row < len(self._scene.placed_objects):
            self._scene.placed_objects.pop(row)
            self._refresh_objs()
            self.inspector.clear_object()
            self.canvas.set_selected_row(-1)
            self.instance_changed.emit()

    def _move_obj_up(self):
        if self._scene is None:
            return
        row = self.objects_list.currentRow()
        if row < len(self._scene.placed_objects) - 1:
            objs = self._scene.placed_objects
            objs[row], objs[row+1] = objs[row+1], objs[row]
            self._refresh_objs()
            self.objects_list.setCurrentRow(row + 1)
            self.canvas.set_selected_row(row + 1)
            self.instance_changed.emit()

    def _move_obj_dn(self):
        if self._scene is None:
            return
        row = self.objects_list.currentRow()
        if row > 0:
            objs = self._scene.placed_objects
            objs[row], objs[row-1] = objs[row-1], objs[row]
            self._refresh_objs()
            self.objects_list.setCurrentRow(row - 1)
            self.canvas.set_selected_row(row - 1)
            self.instance_changed.emit()

    def _refresh_objs(self):
        if self._scene is None or self._project is None:
            return
        # Build a quick id→name map for Layer components in this scene
        layer_names = {}
        for comp in self._scene.components:
            if comp.component_type == "Layer":
                lname = comp.config.get("layer_name", "").strip()
                layer_names[comp.id] = lname if lname else "Layer"

        self.objects_list.blockSignals(True)
        self.objects_list.clear()
        for po in self._scene.placed_objects:
            od = self._project.get_object_def(po.object_def_id)
            name = od.name if od else "?"
            label = f"{name}  ({po.x}, {po.y})"
            if not po.visible:
                label += "  [hidden]"
            layer_id = getattr(po, "layer_id", "")
            if layer_id and layer_id in layer_names:
                label += f"  [{layer_names[layer_id]}]"
            item = QListWidgetItem(label)
            if od and od.behavior_type == "VNCharacter":
                item.setForeground(QColor("#f59e0b"))
            elif not po.visible:
                item.setForeground(QColor(TEXT_MUTED))
            self.objects_list.addItem(item)
        self.objects_list.blockSignals(False)
        self.canvas.update()

    def _on_instance_selected(self, row: int):
        if self._scene is None or self._project is None:
            return
        self.canvas.set_selected_row(row)
        if row < 0 or row >= len(self._scene.placed_objects):
            self.inspector.clear_object()
            return
        self.inspector.load_instance(self._scene.placed_objects[row], self._project, self._scene)
        self.inspector.tabs.setCurrentIndex(0)

    def _on_canvas_selected(self, row: int):
        self.objects_list.blockSignals(True)
        self.objects_list.setCurrentRow(row)
        self.objects_list.blockSignals(False)
        if self._scene is None or self._project is None:
            return
        if row < 0 or row >= len(self._scene.placed_objects):
            self.inspector.clear_object()
            return
        self.inspector.load_instance(self._scene.placed_objects[row], self._project, self._scene)
        self.inspector.tabs.setCurrentIndex(0)

    def _on_obj_moved(self, instance_id: str, x: int, y: int):
        self.inspector.sync_position(x, y)
        self._refresh_objs()
        self.instance_changed.emit()

    def _on_canvas_scene_changed(self):
        self._refresh_objs()
        if self._scene is not None and self._project is not None:
            self.inspector.load_scene(self._scene, self._project)
        self.instance_changed.emit()

    def _on_inspector_changed(self):
        self._refresh_objs()
        self.canvas.update()
        self.instance_changed.emit()

    # ── Public API ────────────────────────────────────────────

    def refresh(self, project: Project, current_index: int):
        self._project = project
        self.scene_list_panel.refresh(project.scenes, current_index)

        # Refresh project explorer with project folder
        if hasattr(self, 'project_explorer'):
            self.project_explorer.set_project_folder(project.project_folder)

        # Keep tile palette in sync with current project tilesets
        if hasattr(self, 'tile_palette'):
            self.tile_palette.load_project(project)

        if current_index < 0 or current_index >= len(project.scenes):
            self._active_grid_comp_id = None
            self._active_tile_layer_comp_id = None
            self.canvas.clear()
            self._scene = None
            self.objects_list.clear()
            self.inspector.clear_all()
            return

        scene = project.scenes[current_index]
        self._active_grid_comp_id = None
        self._active_tile_layer_comp_id = None
        self._scene = scene
        self.canvas.load(scene, project)
        self._refresh_objs()
        self.inspector.load_scene(scene, project)

        self.info_index[1].setText(f"{current_index + 1} / {len(project.scenes)}")
        role_text  = scene.role.upper() if scene.role else "none"
        role_color = ROLE_COLORS.get(scene.role, TEXT_DIM)
        self.info_role[1].setText(role_text)
        self.info_role[1].setStyleSheet(f"color: {role_color}; font-size: 10px; font-weight: 700;")
        self.info_comps[1].setText(str(len(scene.components)))
        self.info_objs[1].setText(str(len(scene.placed_objects)))

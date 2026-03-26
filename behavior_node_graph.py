import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDialog,
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsTextItem,
    QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSplitter,
    QToolBar, QPushButton, QMenu, QWidget, QScrollArea,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QSizePolicy, QStackedWidget, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont,
    QPainterPath, QPainterPathStroker, QLinearGradient,
)

MIN_ZOOM  = 0.25
MAX_ZOOM  = 3.0
GRID_SIZE = 20   # snap increment in scene units

MENU_STYLE = """
    QMenu { background: #1e1e28; color: #e8e6f0; border: 1px solid #2e2e42; font: 11px 'Segoe UI'; }
    QMenu::item { padding: 5px 24px 5px 14px; }
    QMenu::item:selected { background: #7c6aff; color: #ffffff; }
    QMenu::separator { height: 1px; background: #2e2e42; margin: 3px 0; }
"""

FIELD_STYLE = """
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #1e1e28; color: #e8e6f0;
        border: 1px solid #2e2e42; border-radius: 3px;
        padding: 3px 6px; font: 11px 'Segoe UI';
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border-color: #7c6aff;
    }
    QComboBox::drop-down { border: none; width: 16px; }
    QComboBox QAbstractItemView {
        background: #1e1e28; color: #e8e6f0; border: 1px solid #2e2e42;
        selection-background-color: #7c6aff;
    }
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        background: #26263a; border: none; width: 14px;
    }
    QCheckBox { color: #e8e6f0; font: 11px 'Segoe UI'; spacing: 6px; }
    QCheckBox::indicator {
        width: 13px; height: 13px;
        border: 1px solid #2e2e42; border-radius: 3px; background: #1e1e28;
    }
    QCheckBox::indicator:checked { background: #7c6aff; border-color: #7c6aff; }
"""

# ─────────────────────────────────────────────────────────────
#  DATA TABLES
# ─────────────────────────────────────────────────────────────

OBJECT_TRIGGERS = {
    "on_button_pressed":     "On Button Pressed",
    "on_button_held":        "On Button Held",
    "on_button_released":    "On Button Released",
    "on_input":              "On Input Action",
    "on_frame":              "Every Frame",
    "on_timer":              "On Timer",
    "on_timer_variable":     "On Timer (Variable)",
    "on_scene_start":        "On Scene Start",
    "on_scene_end":          "On Scene End",
    "on_create":             "On Create",
    "on_destroy":            "On Destroy",
    "on_enter":              "On Zone Enter",
    "on_exit":               "On Zone Exit",
    "on_overlap":            "On Zone Overlap",
    "on_interact_zone":      "On Interact in Zone",
    "on_signal":             "On Signal",
    "on_variable_threshold": "On Variable Threshold",
    "on_touch_tap":          "On Touch Tap",
    "on_path_complete":      "On Path Complete",
    "on_animation_finish":   "On Animation Finish",
    "on_animation_frame":    "On Animation Frame",
}

TRIGGER_CATEGORIES = {
    "Input":     ["on_button_pressed","on_button_held","on_button_released","on_input"],
    "Touch":     ["on_touch_tap"],
    "Timing":    ["on_frame","on_timer","on_timer_variable"],
    "Scene":     ["on_scene_start","on_scene_end"],
    "Object":    ["on_create","on_destroy"],
    "Zone":      ["on_enter","on_exit","on_overlap","on_interact_zone"],
    "Signal":    ["on_signal"],
    "Variables": ["on_variable_threshold"],
    "Paths":     ["on_path_complete"],
    "Animation": ["on_animation_finish", "on_animation_frame"],
}

BUTTON_OPTIONS = ["cross","circle","square","triangle",
                  "dpad_up","dpad_down","dpad_left","dpad_right",
                  "l","r","start","select"]

COMPARE_OPTIONS = ["==","!=",">","<",">=","<="]

TRIGGER_FIELDS = {
    "on_button_pressed":     [("button",             "Button",            "combo", {"options": BUTTON_OPTIONS})],
    "on_button_held":        [("button",             "Button",            "combo", {"options": BUTTON_OPTIONS})],
    "on_button_released":    [("button",             "Button",            "combo", {"options": BUTTON_OPTIONS})],
    "on_timer":              [("interval",           "Interval (frames)", "spin",  {"min":1,"max":9999})],
    "on_timer_variable":     [("timer_var",          "Interval Variable", "text",  {})],
    "on_signal":             [("signal_name",        "Signal Name",       "text",  {})],
    "on_input":              [("input_action_name",  "Action Name",       "text",  {})],
    "on_variable_threshold": [("threshold_var",      "Variable",          "text",  {}),
                              ("threshold_compare",  "Condition",         "combo", {"options": COMPARE_OPTIONS}),
                              ("threshold_value",    "Value",             "text",  {}),
                              ("threshold_repeat",   "Repeat",            "check", {})],
    "on_path_complete":      [("path_name",          "Path Name",         "text",  {})],
    "on_animation_finish":   [("ani_trigger_object", "Animation Object",  "object", {})],
    "on_animation_frame":    [("ani_trigger_object", "Animation Object",  "object", {}),
                              ("ani_trigger_frame",  "Frame Index",       "spin",   {"min": 0, "max": 9999})],
}

ACTION_PALETTE = {
    "Objects: Visibility":  [("show_object","Show Object"),("hide_object","Hide Object"),("set_opacity","Set Opacity"),("fade_in_object","Fade Object In"),("fade_out_object","Fade Object Out")],
    "Objects: Transform":   [("move_to","Move To Position"),("move_by","Move By Offset"),("slide_to","Slide To Position"),("slide_by","Slide By Offset"),("return_to_start","Return to Start"),("set_scale","Set Scale"),("scale_to","Scale To"),("set_rotation","Set Rotation"),("rotate_to","Rotate To"),("rotate_by","Rotate By"),("spin","Spin"),("stop_spin","Stop Spinning")],
    "Objects: Animation":   [("play_anim","Play Animation"),("stop_anim","Stop Animation"),("set_frame","Set Frame"),("set_anim_speed","Set Animation Speed")],
    "Objects: Lifecycle":   [("create_object","Create Object"),("destroy_object","Destroy Object"),("destroy_all_type","Destroy All of Type"),("enable_interact","Enable Interaction"),("disable_interact","Disable Interaction"),("attach_to","Attach to Object"),("detach","Detach from Parent")],
    "Objects: Groups":      [("add_to_group","Add Object to Group"),("remove_from_group","Remove Object from Group"),("call_action_on_group","Call Action on Group"),("if_in_group","If Object in Group")],
    "Scene Flow":        [("go_to_scene","Go to Scene"),("go_to_next","Go to Next Scene"),("go_to_prev","Go to Previous Scene"),("go_to_random","Go to Random Scene"),("restart_scene","Restart Scene"),("quit_game","Quit Game")],
    "State Machine":     [("go_to_state","Go to State")],
    "Control Flow":      [("loop","Loop"),("cancel_all","Cancel All Actions")],
    "Timing":            [("wait","Wait"),("wait_random","Wait Random"),("wait_for_input","Wait for Input")],
    "Screen":            [("fade_in","Fade In"),("fade_out","Fade Out"),("fade_to_color","Fade to Color"),("flash_screen","Flash Screen"),("shake_screen","Shake Screen")],
    "Camera":            [("camera_move_to","Move Camera To"),("camera_offset","Offset Camera"),("camera_follow","Follow Object"),("camera_stop_follow","Stop Following"),("camera_reset","Reset Camera"),("camera_shake","Shake Camera"),("camera_set_zoom","Set Camera Zoom"),("camera_zoom_to","Zoom Camera To")],
    "Animation":         [("ani_play","Play Animation"),("ani_pause","Pause Animation"),("ani_stop","Stop Animation"),("ani_set_frame","Set Frame"),("ani_set_speed","Set Speed"),("ani_switch_slot","Switch Animation Slot"),("ani_set_flip","Set Flip")],
    "Background":        [("set_background","Set Background Image"),("scroll_bg","Scroll Background"),("stop_scroll_bg","Stop Background Scroll")],
    "Layers":            [("layer_show","Show Layer"),("layer_hide","Hide Layer"),("layer_set_image","Set Layer Image")],
    "Music & Sound":     [("play_music","Play Music"),("stop_music","Stop Music"),("pause_music","Pause Music"),("resume_music","Resume Music"),("set_music_volume","Set Music Volume"),("play_sfx","Play Sound Effect"),("stop_all_sounds","Stop All Sounds")],
    "Dialogue":          [("show_dialogue","Show Dialogue Box"),("hide_dialogue","Hide Dialogue Box"),("set_speaker","Set Speaker Name"),("set_speaker_color","Set Speaker Color"),("set_dialogue_line","Set Dialogue Line"),("clear_dialogue","Clear Dialogue"),("wait_for_advance","Wait for Dialogue Advance")],
    "Choice Menu":       [("show_choices","Show Choice Menu"),("hide_choices","Hide Choice Menu"),("set_choice_text","Set Choice Text"),("set_choice_dest","Set Choice Destination")],
    "Variables & Flags": [
        ("set_variable",              "Set Variable"),
        ("change_variable",           "Change Variable"),
        ("set_variable_from_variable","Copy Variable"),
        ("change_variable_by_variable","Math with Variable"),
        ("evaluate_expression",       "Evaluate Expression"),
        ("clamp_variable",            "Clamp Variable"),
        ("set_flag",                  "Set Flag"),
        ("toggle_flag",               "Toggle Flag"),
        ("if_variable",               "If Variable"),
        ("if_flag",                   "If Flag"),
        ("random_chance",             "If Random Chance"),
        ("random_set",                "Set Variable Random"),
    ],
    "Inventory":         [("add_item","Add Item"),("remove_item","Remove Item"),("if_has_item","If Has Item"),("show_inventory","Show Inventory"),("hide_inventory","Hide Inventory")],
    "Save & Load":       [("save_game","Save Game"),("load_game","Load Game"),("delete_save","Delete Save"),("if_save_exists","If Save Exists")],
    "Signals":           [("emit_signal","Emit Signal")],
    "Movement":          [("four_way_movement","4-Way Movement"),("four_way_movement_collide","4-Way Movement (Collide)"),("eight_way_movement","8-Way Movement"),("eight_way_movement_collide","8-Way Movement (Collide)"),("two_way_movement","2-Way Movement"),("two_way_movement_collide","2-Way Movement (Collide)"),("fire_bullet","Fire Bullet"),("set_velocity","Set Velocity"),("add_velocity","Add Velocity"),("jump","Jump")],
    "GUI":               [("set_label_text","Set Label Text"),("set_label_text_var","Set Label Text (Variable)"),("set_label_color","Set Label Color"),("set_label_size","Set Label Font Size")],
    "Debug":             [("log_message","Log Message"),("show_debug","Show Debug Overlay")],
    "Paths":             [("follow_path","Follow Path"),("stop_path","Stop Following Path"),("resume_path","Resume Following Path"),("set_path_speed","Set Path Speed")],
    "Layer Animation":   [("layer_anim_play_macro","Play Macro"),("layer_anim_stop_macro","Stop Macro"),("layer_anim_set_blink","Set Blink"),("layer_anim_set_idle","Set Idle Breathing"),("layer_anim_set_talk","Set Talk"),("layer_anim_talk_for","Talk For Duration")],
    "Getters":           [("get_position","Get Object Position"),("get_distance","Get Distance to Object"),("if_distance","If Distance to Object")],
    "Grid":              [("grid_place_at","Place on Grid"),("grid_snap_to","Snap to Grid"),("grid_get_cell","Get Grid Cell"),("grid_get_at","Get Object at Cell"),("grid_is_empty","If Cell is Empty"),("grid_get_neighbors","Get Neighbors"),("grid_for_each","For Each Cell"),("grid_clear_cell","Clear Cell"),("grid_clear_all","Clear Entire Grid"),("grid_move","Grid Move"),("grid_swap","Grid Swap")],
}

ACTION_NAMES: dict[str, str] = {}
for _cat, _items in ACTION_PALETTE.items():
    for _code, _name in _items:
        ACTION_NAMES[_code] = _name

# Actions hidden from the node-graph palette but kept in code for future
# genre-template reintroduction.  Remove entries to re-enable them.
DEFERRED_ACTIONS = {
    # Dialogue
    "show_dialogue", "hide_dialogue", "set_speaker", "set_speaker_color",
    "set_dialogue_line", "clear_dialogue", "wait_for_advance",
    # Choice Menu
    "show_choices", "hide_choices", "set_choice_text", "set_choice_dest",
    # Legacy Background (replaced by layer system)
    "set_background",
    # Layer image swap (use show/hide layers instead)
    "layer_set_image",
    # Scene Flow
    "go_to_random",
    # Inventory (full UI not yet implemented)
    "add_item", "remove_item", "if_has_item", "show_inventory", "hide_inventory",
}

BRANCH_TYPES = {"if_variable","if_flag","if_has_item","if_save_exists","if_in_group","random_chance","if_distance","grid_is_empty","grid_get_at"}
LOOP_TYPES   = {"loop","grid_for_each","grid_get_neighbors"}

ACTION_FIELDS = {
    "go_to_scene":       [("target_scene",       "Scene",            "scene_num",{})],
    "go_to_random":      [("random_scenes",       "Scenes (csv)",     "text",     {})],
    "go_to_state":       [("target_state",        "State Name",       "text",     {})],
    "loop":              [("loop_count",          "Iterations (0=∞)", "spin",     {"min":0,"max":9999})],
    "wait":              [("duration",            "Seconds",          "dspin",    {"min":0.0,"max":999.0,"step":0.1})],
    "fade_in":           [("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "fade_out":          [("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "fade_to_color":     [("color",               "Color (#rrggbb)",  "text",     {}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "flash_screen":      [("color",               "Color (#rrggbb)",  "text",     {}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":5.0,"step":0.1})],
    "shake_screen":      [("intensity",           "Intensity",        "dspin",    {"min":1.0,"max":50.0,"step":1.0}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":10.0,"step":0.1})],
    "camera_move_to":    [("camera_target_x",     "Target X",         "spin",     {"min":-9999,"max":9999}),
                          ("camera_target_y",     "Target Y",         "spin",     {"min":-9999,"max":9999}),
                          ("camera_duration",     "Duration",         "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("camera_easing",       "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "camera_offset":     [("camera_offset_x",     "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("camera_offset_y",     "Offset Y",         "spin",     {"min":-9999,"max":9999}),
                          ("camera_duration",     "Duration",         "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("camera_easing",       "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "camera_follow":     [("camera_follow_target_def_id","Object",    "object",   {}),
                          ("camera_follow_offset_x","Offset X",       "spin",     {"min":-999,"max":999}),
                          ("camera_follow_offset_y","Offset Y",       "spin",     {"min":-999,"max":999})],
    "camera_reset":      [("camera_duration",     "Duration",         "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "camera_shake":      [("shake_intensity",     "Intensity",        "dspin",    {"min":1.0,"max":50.0,"step":1.0}),
                          ("shake_duration",      "Duration",         "dspin",    {"min":0.0,"max":10.0,"step":0.1})],
    "camera_set_zoom":   [("camera_zoom_target",  "Zoom Level",       "dspin",    {"min":0.25,"max":4.0,"step":0.05})],
    "camera_zoom_to":    [("camera_zoom_target",  "Zoom Level",       "dspin",    {"min":0.25,"max":4.0,"step":0.05}),
                          ("camera_zoom_duration","Duration",         "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("camera_zoom_easing",  "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "ani_play":          [("object_def_id",       "Object",           "object",   {})],
    "ani_pause":         [("object_def_id",       "Object",           "object",   {})],
    "ani_stop":          [("object_def_id",       "Object",           "object",   {})],
    "ani_set_frame":     [("object_def_id",       "Object",           "object",   {}),
                          ("ani_target_frame",    "Frame",            "spin",     {"min":0,"max":9999})],
    "ani_set_speed":     [("object_def_id",       "Object",           "object",   {}),
                          ("ani_fps",             "FPS",              "spin",     {"min":1,"max":120})],
    "ani_switch_slot":   [("object_def_id",       "Object",           "object",   {}),
                          ("ani_slot_name",       "Slot Name",        "text",     {})],
    "ani_set_flip":      [("object_def_id",       "Object",           "object",   {}),
                          ("ani_flip_h",          "Flip H",           "check",    {}),
                          ("ani_flip_v",          "Flip V",           "check",    {})],
    "set_background":    [("image_id",            "Image",            "image",    {})],
    "scroll_bg":         [("layer_name",          "Layer Name",       "text",     {}),
                          ("scroll_direction",    "Direction",        "combo",    {"options":["horizontal","vertical"]}),
                          ("scroll_speed",        "Speed (px/f)",     "spin",     {"min":-20,"max":20})],
    "stop_scroll_bg":    [("layer_name",          "Layer Name",       "text",     {})],
    "layer_show":        [("layer_name",          "Layer Name",       "text",     {})],
    "layer_hide":        [("layer_name",          "Layer Name",       "text",     {})],
    "layer_set_image":   [("layer_name",          "Layer Name",       "text",     {}),
                          ("image_id",            "Image",            "image",    {})],
    "play_music":        [("audio_id",            "Track",            "audio",    {}),
                          ("audio_loop",          "Loop",             "check",    {})],
    "set_music_volume":  [("volume",              "Volume (0-100)",   "spin",     {"min":0,"max":100})],
    "play_sfx":          [("audio_id",            "Sound Effect",     "audio",    {})],
    "set_speaker":       [("speaker_name",        "Name",             "text",     {})],
    "set_speaker_color": [("speaker_color",       "Color (#rrggbb)",  "text",     {})],
    "set_dialogue_line": [("dialogue_line_index", "Line (1-4)",       "spin",     {"min":1,"max":4}),
                          ("dialogue_text",       "Text",             "text",     {})],
    "set_choice_text":   [("choice_index",        "Button (1-4)",     "spin",     {"min":1,"max":4}),
                          ("choice_text",         "Label",            "text",     {})],
    "set_choice_dest":   [("choice_index",        "Button (1-4)",     "spin",     {"min":1,"max":4}),
                          ("choice_goto",         "Go to Scene",      "scene_num",{})],
    "set_variable":      [("var_name",            "Variable",         "text",     {}),
                          ("var_value",           "Value",            "text",     {})],
    "change_variable":   [("var_name",            "Variable",         "text",     {}),
                          ("var_operator",        "Operation",        "combo",    {"options":["add","subtract","multiply","divide"]}),
                          ("var_value",           "Amount",           "text",     {})],
    "set_variable_from_variable": [
                          ("var_name",            "Target Variable",  "text",     {}),
                          ("var_source",          "Source Variable",  "text",     {})],
    "change_variable_by_variable": [
                          ("var_name",            "Target Variable",  "text",     {}),
                          ("var_operator",        "Operation",        "combo",    {"options":["add","subtract","multiply","divide"]}),
                          ("var_source",          "Source Variable",  "text",     {})],
    "evaluate_expression":[("var_name",           "Result Variable",  "text",     {}),
                          ("expression",          "Expression",       "text",     {})],
    "clamp_variable":    [("var_name",            "Variable",         "text",     {}),
                          ("clamp_min",           "Min (blank=none)", "text",     {}),
                          ("clamp_max",           "Max (blank=none)", "text",     {})],
    "set_flag":          [("bool_name",           "Flag",             "text",     {}),
                          ("bool_value",          "Value",            "check",    {})],
    "toggle_flag":       [("bool_name",           "Flag",             "text",     {})],
    "if_variable":       [("var_name",            "Variable",         "text",     {}),
                          ("var_compare",         "Condition",        "combo",    {"options":["==","!=",">","<",">=","<="]}),
                          ("var_value",           "Value",            "text",     {})],
    "if_flag":           [("bool_name",           "Flag",             "text",     {}),
                          ("bool_expected",       "Expected",         "check",    {})],
    "add_item":          [("item_name",           "Item",             "text",     {})],
    "remove_item":       [("item_name",           "Item",             "text",     {})],
    "if_has_item":       [("item_name",           "Item",             "text",     {})],
    "emit_signal":       [("signal_name",         "Signal",           "text",     {})],
    "show_object":       [("object_def_id",       "Object",           "object",   {})],
    "hide_object":       [("object_def_id",       "Object",           "object",   {})],
    "set_opacity":       [("object_def_id",       "Object",           "object",   {}),
                          ("target_opacity",      "Opacity (0-1)",    "dspin",    {"min":0.0,"max":1.0,"step":0.05})],
    "fade_in_object":    [("object_def_id",       "Object",           "object",   {}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "fade_out_object":   [("object_def_id",       "Object",           "object",   {}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "move_to":           [("object_def_id",       "Object",           "object",   {}),
                          ("target_x",            "X",                "spin",     {"min":-999,"max":9999}),
                          ("target_y",            "Y",                "spin",     {"min":-999,"max":9999})],
    "move_by":           [("object_def_id",       "Object",           "object",   {}),
                          ("offset_x",            "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",            "Offset Y",         "spin",     {"min":-9999,"max":9999})],
    "slide_to":          [("object_def_id",       "Object",           "object",   {}),
                          ("target_x",            "X",                "spin",     {"min":-999,"max":9999}),
                          ("target_y",            "Y",                "spin",     {"min":-999,"max":9999}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "slide_by":          [("object_def_id",       "Object",           "object",   {}),
                          ("offset_x",            "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",            "Offset Y",         "spin",     {"min":-9999,"max":9999}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "return_to_start":   [("object_def_id",       "Object",           "object",   {})],
    "set_scale":         [("object_def_id",       "Object",           "object",   {}),
                          ("target_scale",        "Scale",            "dspin",    {"min":0.01,"max":20.0,"step":0.1})],
    "scale_to":          [("object_def_id",       "Object",           "object",   {}),
                          ("target_scale",        "Scale",            "dspin",    {"min":0.01,"max":20.0,"step":0.1}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "set_rotation":      [("object_def_id",       "Object",           "object",   {}),
                          ("target_rotation",     "Degrees",          "dspin",    {"min":-360.0,"max":360.0,"step":1.0})],
    "rotate_to":         [("object_def_id",       "Object",           "object",   {}),
                          ("target_rotation",     "Degrees",          "dspin",    {"min":-360.0,"max":360.0,"step":1.0}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1}),
                          ("easing",              "Easing",           "combo",    {"options":["linear","ease_in","ease_out","ease_in_out"]})],
    "rotate_by":         [("object_def_id",       "Object",           "object",   {}),
                          ("target_rotation",     "Degrees",          "dspin",    {"min":-360.0,"max":360.0,"step":1.0}),
                          ("duration",            "Seconds",          "dspin",    {"min":0.0,"max":30.0,"step":0.1})],
    "spin":              [("object_def_id",       "Object",           "object",   {}),
                          ("spin_speed",          "Degrees/sec",      "dspin",    {"min":-3600.0,"max":3600.0,"step":10.0})],
    "stop_spin":         [("object_def_id",       "Object",           "object",   {})],
    "play_anim":         [("object_def_id",       "Object",           "object",   {}),
                          ("ani_slot_name",       "Slot (blank=current)", "text", {})],
    "stop_anim":         [("object_def_id",       "Object",           "object",   {})],
    "set_frame":         [("object_def_id",       "Object",           "object",   {}),
                          ("frame_index",         "Frame",            "spin",     {"min":0,"max":999})],
    "set_anim_speed":    [("object_def_id",       "Object",           "object",   {}),
                          ("anim_fps",            "FPS",              "spin",     {"min":1,"max":60})],
    "create_object":     [("object_def_id",       "Object",           "object",   {}),
                          ("spawn_at_self",       "Spawn at Self",    "check",    {}),
                          ("target_x",            "X",                "spin",     {"min":0,"max":9999}),
                          ("target_y",            "Y",                "spin",     {"min":0,"max":9999}),
                          ("spawn_offset_x",      "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("spawn_offset_y",      "Offset Y",         "spin",     {"min":-9999,"max":9999}),
                          ("bullet_speed",        "Bullet Speed (0=static)", "spin", {"min":0,"max":100}),
                          ("parent_id",           "Parent Object",    "object",   {}),
                          ("inherit_position",    "Inherit Position", "check",    {}),
                          ("inherit_rotation",    "Inherit Rotation", "check",    {}),
                          ("inherit_scale",       "Inherit Scale",    "check",    {}),
                          ("destroy_with_parent", "Destroy w/ Parent","check",    {})],
    "attach_to":         [("parent_id",           "Parent Object",    "object",   {}),
                          ("offset_x",            "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",            "Offset Y",         "spin",     {"min":-9999,"max":9999}),
                          ("inherit_position",    "Inherit Position", "check",    {}),
                          ("inherit_rotation",    "Inherit Rotation", "check",    {}),
                          ("rotation_offset",     "Rotation Offset",  "spin",     {"min":-360,"max":360}),
                          ("inherit_scale",       "Inherit Scale",    "check",    {}),
                          ("destroy_with_parent", "Destroy w/ Parent","check",    {})],
    "detach":            [],
    "destroy_object":    [("object_def_id",       "Object",           "object",   {})],
    "destroy_all_type":  [("object_def_id",       "Object Type",      "object",   {})],
    "enable_interact":   [("object_def_id",       "Object",           "object",   {})],
    "disable_interact":  [("object_def_id",       "Object",           "object",   {})],
    "add_to_group":      [("object_def_id",       "Object",           "object",   {}),
                          ("group_name",          "Group Name",       "text",     {})],
    "remove_from_group": [("object_def_id",       "Object",           "object",   {}),
                          ("group_name",          "Group Name",       "text",     {})],
    "call_action_on_group": [
                          ("group_name",          "Group Name",       "text",     {}),
                          ("group_action_type",   "Action to Run",    "combo",    {"options": [
                              "show_object", "hide_object", "destroy_object",
                              "move_to", "move_by", "set_opacity", "set_scale", "set_rotation",
                              "enable_interact", "disable_interact",
                              "emit_signal",
                          ]}),
                          ("target_x",            "Target X",         "spin",     {"min":-9999,"max":9999}),
                          ("target_y",            "Target Y",         "spin",     {"min":-9999,"max":9999}),
                          ("offset_x",            "Offset X",         "spin",     {"min":-9999,"max":9999}),
                          ("offset_y",            "Offset Y",         "spin",     {"min":-9999,"max":9999}),
                          ("target_opacity",      "Opacity",          "dspin",    {"min":0.0,"max":1.0,"step":0.05}),
                          ("target_scale",        "Scale",            "dspin",    {"min":0.01,"max":20.0,"step":0.1}),
                          ("target_rotation",     "Degrees",          "dspin",    {"min":-360.0,"max":360.0,"step":1.0})],
    "if_in_group":       [("object_def_id",       "Object",           "object",   {}),
                          ("group_name",          "Group Name",       "text",     {})],
    "set_label_text":    [("object_def_id",       "Label Object",     "object",   {}),
                          ("dialogue_text",       "New Text",         "text",     {})],
    "set_label_text_var":[("object_def_id",       "Label Object",     "object",   {}),
                          ("var_name",            "Variable",         "text",     {})],
    "set_label_color":   [("object_def_id",       "Label Object",     "object",   {}),
                          ("color",               "Color (#rrggbb)",  "text",     {})],
    "set_label_size":    [("object_def_id",       "Label Object",     "object",   {}),
                          ("frame_index",         "Size (px)",        "spin",     {"min":4,"max":128})],
    "log_message":       [("log_message",         "Message",          "text",     {})],
    "four_way_movement": [("movement_speed",      "Speed (px/f)",     "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("movement_style",      "Style",            "combo",    {"options":["instant","slide"]})],
    "four_way_movement_collide": [
                          ("movement_speed",      "Speed (px/f)",     "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("movement_style",      "Style",            "combo",    {"options":["instant","slide"]}),
                          ("collision_layer_id",  "Collision Layer",  "collision_layer",{}),
                          ("player_width",        "Player W (px)",    "spin",     {"min":1,"max":512}),
                          ("player_height",       "Player H (px)",    "spin",     {"min":1,"max":512})],
    "eight_way_movement": [
                          ("movement_speed",          "Speed (px/f)",       "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("rotation_mode",           "Rotation",           "combo",    {"options":["instant","tween"]}),
                          ("rotation_tween_duration", "Tween Duration (s)", "dspin",    {"min":0.05,"max":5.0,"step":0.05})],
    "eight_way_movement_collide": [
                          ("movement_speed",          "Speed (px/f)",       "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("rotation_mode",           "Rotation",           "combo",    {"options":["instant","tween"]}),
                          ("rotation_tween_duration", "Tween Duration (s)", "dspin",    {"min":0.05,"max":5.0,"step":0.05}),
                          ("collision_layer_id",      "Collision Layer",    "collision_layer",{}),
                          ("player_width",            "Player W (px)",      "spin",     {"min":1,"max":512}),
                          ("player_height",           "Player H (px)",      "spin",     {"min":1,"max":512})],
    "two_way_movement":  [("movement_speed",      "Speed (px/f)",     "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("two_way_axis",        "Axis",             "combo",    {"options":["horizontal","vertical"]}),
                          ("movement_style",      "Style",            "combo",    {"options":["instant","slide"]})],
    "two_way_movement_collide": [
                          ("movement_speed",      "Speed (px/f)",     "dspin",    {"min":0.1,"max":20.0,"step":0.1}),
                          ("two_way_axis",        "Axis",             "combo",    {"options":["horizontal","vertical"]}),
                          ("movement_style",      "Style",            "combo",    {"options":["instant","slide"]}),
                          ("collision_layer_id",  "Collision Layer",  "collision_layer",{}),
                          ("player_width",        "Player W (px)",    "spin",     {"min":1,"max":512}),
                          ("player_height",       "Player H (px)",    "spin",     {"min":1,"max":512})],
    "fire_bullet":       [("bullet_direction",    "Direction",        "combo",    {"options":["right","left","up","down"]}),
                          ("bullet_speed",        "Speed (px/f)",     "spin",     {"min":1,"max":40})],
    "set_velocity":  [
        ("object_def_id",       "Object",                   "object",  {}),
        ("velocity_vx",         "Velocity X (px/f)",        "dspin",   {"min":-50.0, "max":50.0, "step":0.5}),
        ("velocity_set_x",      "Apply X",                  "check",   {}),
        ("velocity_vy",         "Velocity Y (px/f)",        "dspin",   {"min":-50.0, "max":50.0, "step":0.5}),
        ("velocity_set_y",      "Apply Y",                  "check",   {}),
    ],
    "add_velocity":  [
        ("object_def_id",       "Object",                   "object",  {}),
        ("velocity_vx",         "Add X (px/f)",             "dspin",   {"min":-50.0, "max":50.0, "step":0.5}),
        ("velocity_set_x",      "Apply X",                  "check",   {}),
        ("velocity_vy",         "Add Y (px/f)",             "dspin",   {"min":-50.0, "max":50.0, "step":0.5}),
        ("velocity_set_y",      "Apply Y",                  "check",   {}),
    ],
    "jump":          [
        ("object_def_id",           "Object",               "object",  {}),
        ("jump_strength",           "Jump Strength (px/f)", "dspin",   {"min":1.0,  "max":40.0, "step":0.5}),
        ("jump_max_count",          "Max Jumps (1=single, 2=double…)", "spin", {"min":1, "max":5}),
        ("jump_variable_height",    "Variable Height",      "check",   {}),
        ("jump_variable_min_vy",    "Min Height (if variable)", "dspin", {"min":0.5, "max":20.0, "step":0.5}),
        ("jump_float",              "Float (hold to fall slower)", "check", {}),
        ("jump_float_gravity_mult", "Float Gravity Mult",   "dspin",   {"min":0.0,  "max":1.0,  "step":0.05}),
        ("jump_button",             "Jump Button",          "combo",   {"options": ["cross","circle","square","triangle","dpad_up","l","r"]}),
        ("jump_collision_layer_id", "Collision Layer",      "collision_layer", {}),
        ("jump_player_width",       "Player W (px)",        "spin",    {"min":1, "max":512}),
        ("jump_player_height",      "Player H (px)",        "spin",    {"min":1, "max":512}),
    ],
    "follow_path":       [("object_def_id",       "Object",           "object",   {}),
                          ("path_name",            "Path Name",        "text",     {}),
                          ("path_speed",           "Speed (px/f)",     "dspin",    {"min":0.1,"max":40.0,"step":0.1}),
                          ("path_loop",            "Loop",             "check",    {})],
    "stop_path":         [("object_def_id",       "Object",           "object",   {})],
    "resume_path":       [("object_def_id",       "Object",           "object",   {})],
    "set_path_speed":    [("object_def_id",       "Object",           "object",   {}),
                          ("path_speed",           "Speed (px/f)",     "dspin",    {"min":0.1,"max":40.0,"step":0.1})],
    "layer_anim_play_macro": [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_macro_name","Macro Name",       "text",     {}),
                          ("layer_anim_macro_loop","Loop",             "check",    {})],
    "layer_anim_stop_macro": [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_macro_name","Macro Name",       "text",     {})],
    "layer_anim_set_blink":  [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_enabled",   "Enabled",          "check",    {})],
    "layer_anim_set_idle":   [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_enabled",   "Enabled",          "check",    {})],
    "layer_anim_set_talk":   [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_enabled",   "Enabled",          "check",    {})],
    "layer_anim_talk_for":   [
                          ("layer_anim_id",        "Layer Animation",  "paper_doll",{}),
                          ("layer_anim_talk_duration","Duration (s)",  "dspin",    {"min":0.1,"max":60.0,"step":0.1})],
    # ── New nodes ─────────────────────────────────────────────
    "wait_random":       [("duration",            "Min Seconds",      "dspin",    {"min":0.0,"max":999.0,"step":0.1}),
                          ("wait_max",            "Max Seconds",      "dspin",    {"min":0.0,"max":999.0,"step":0.1})],
    "random_chance":     [("var_value",           "Chance (%)",       "spin",     {"min":1,"max":100})],
    "random_set":        [("var_name",            "Variable",         "text",     {}),
                          ("clamp_min",           "Min Value",        "text",     {}),
                          ("clamp_max",           "Max Value",        "text",     {})],
    "get_position":      [("object_def_id",       "Object",           "object",   {}),
                          ("var_name",            "X Variable",       "text",     {}),
                          ("var_source",          "Y Variable",       "text",     {})],
    "if_distance":       [("object_def_id",       "Target Object",    "object",   {}),
                          ("var_compare",         "Condition",        "combo",    {"options":["<=",">=","<",">","==","!="]}),
                          ("var_value",           "Distance (px)",    "text",     {})],
    "get_distance":      [("object_def_id",       "Target Object",    "object",   {}),
                          ("var_name",            "Store in Variable","text",     {})],
    "cancel_all":        [("object_def_id",       "Object (empty=self)","object", {})],
    # ── Grid actions ─────────────────────────────────────────
    "grid_place_at":     [("grid_name",            "Grid Name",        "text",     {}),
                          ("object_def_id",         "Object",           "object",   {}),
                          ("grid_col",              "Column",           "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Row",              "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {})],
    "grid_snap_to":      [("grid_name",            "Grid Name",        "text",     {}),
                          ("object_def_id",         "Object",           "object",   {})],
    "grid_get_cell":     [("grid_name",            "Grid Name",        "text",     {}),
                          ("object_def_id",         "Object",           "object",   {}),
                          ("grid_col_var",          "Store Col in Var", "text",     {}),
                          ("grid_row_var",          "Store Row in Var", "text",     {})],
    "grid_get_at":       [("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_col",              "Column",           "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Row",              "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {}),
                          ("grid_result_var",       "Store ID in Var",  "text",     {})],
    "grid_is_empty":     [("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_col",              "Column",           "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Row",              "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {})],
    "grid_get_neighbors":[("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_col",              "Column",           "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Row",              "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {}),
                          ("grid_neighbor_mode",    "Mode",             "combo",    {"options":["4","8"]})],
    "grid_for_each":     [("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_result_var",       "Occupant Var",     "text",     {}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {})],
    "grid_clear_cell":   [("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_col",              "Column",           "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Row",              "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col Variable",     "text",     {}),
                          ("grid_row_var",          "Row Variable",     "text",     {})],
    "grid_clear_all":    [("grid_name",            "Grid Name",        "text",     {})],
    "grid_move":         [("grid_name",            "Grid Name",        "text",     {}),
                          ("object_def_id",         "Object",           "object",   {}),
                          ("grid_direction",        "Direction",        "combo",    {"options":["up","down","left","right"]}),
                          ("grid_distance",         "Distance (cells)", "spin",     {"min":1,"max":99})],
    "grid_swap":         [("grid_name",            "Grid Name",        "text",     {}),
                          ("grid_col",              "Cell 1 Col",       "spin",     {"min":0,"max":999}),
                          ("grid_row",              "Cell 1 Row",       "spin",     {"min":0,"max":999}),
                          ("grid_col2",             "Cell 2 Col",       "spin",     {"min":0,"max":999}),
                          ("grid_row2",             "Cell 2 Row",       "spin",     {"min":0,"max":999}),
                          ("grid_col_var",          "Col 1 Variable",   "text",     {}),
                          ("grid_row_var",          "Row 1 Variable",   "text",     {}),
                          ("grid_col2_var",         "Col 2 Variable",   "text",     {}),
                          ("grid_row2_var",         "Row 2 Variable",   "text",     {})],
}

CATEGORY_ACCENTS = {
    "Scene Flow":"#f87171","State Machine":"#c084fc","Control Flow":"#c084fc",
    "Timing":"#a78bfa","Screen":"#60a5fa",
    "Camera":"#34d399","Animation":"#34d399","Background":"#60a5fa",
    "Layers":"#60a5fa","Music & Sound":"#fb923c","Dialogue":"#e879f9",
    "Choice Menu":"#e879f9","Variables & Flags":"#facc15","Inventory":"#facc15",
    "Save & Load":"#f87171","Signals":"#a78bfa","Movement":"#4ade80",
    "Objects: Visibility":"#7c6aff","Objects: Transform":"#7c6aff",
    "Objects: Animation":"#7c6aff","Objects: Lifecycle":"#7c6aff",
    "Objects: Groups":"#7c6aff",
    "VN Character":"#f59e0b","GUI":"#7c6aff","Debug":"#94a3b8",
    "Paths":"#06b6d4",
    "Layer Animation":"#f472b6",
    "Getters":"#22d3ee",
}

def get_action_category(action_type: str) -> str:
    for cat, items in ACTION_PALETTE.items():
        for code, _ in items:
            if code == action_type:
                return cat
    return ""

def get_fields(node_type: str, code: str) -> list:
    if node_type == NODE_TRIGGER:
        return TRIGGER_FIELDS.get(code, [])
    elif node_type == NODE_ACTION:
        return ACTION_FIELDS.get(code, [])
    return []

def build_summary(node_type: str, code: str, params: dict) -> str:
    p = params
    if node_type == NODE_TRIGGER:
        if code in ("on_button_pressed","on_button_held","on_button_released"):
            b = p.get("button",""); return f"[ {b} ]" if b else ""
        if code == "on_timer":
            iv = p.get("interval",""); return f"every {iv} frames" if iv else ""
        if code == "on_timer_variable":
            tv = p.get("timer_var",""); return f"interval: {tv}" if tv else ""
        if code == "on_signal":
            s = p.get("signal_name",""); return f"📡 {s}" if s else ""
        if code == "on_input":
            return p.get("input_action_name","")
        if code == "on_variable_threshold":
            v = p.get("threshold_var","")
            c = p.get("threshold_compare",">=")
            val = p.get("threshold_value","")
            repeat = " ↻" if p.get("threshold_repeat") else ""
            return f"{v} {c} {val}{repeat}" if v else ""
        if code == "on_path_complete":
            pn = p.get("path_name",""); return f"🛤 {pn}" if pn else ""
        if code == "on_animation_finish":
            obj = p.get("ani_trigger_object",""); return f"🎞 {obj}" if obj else ""
        if code == "on_animation_frame":
            obj = p.get("ani_trigger_object","")
            fr  = p.get("ani_trigger_frame", 0)
            return f"🎞 {obj} @ frame {fr}" if obj else ""
        return ""
    summaries = {
        "go_to_scene":       lambda: f"→ scene {p.get('target_scene','')}",
        "go_to_state":       lambda: f"→ state: {p.get('target_state','')}",
        "go_to_random":      lambda: f"→ [{p.get('random_scenes','')}]",
        "loop":              lambda: f"× {p.get('loop_count',0)}" if p.get('loop_count',0) > 0 else "∞ loop",
        "wait":              lambda: f"{p.get('duration',0)}s",
        "fade_in":           lambda: f"{p.get('duration',0)}s",
        "fade_out":          lambda: f"{p.get('duration',0)}s",
        "fade_to_color":     lambda: f"{p.get('color','')}  {p.get('duration',0)}s",
        "flash_screen":      lambda: f"{p.get('color','')}  {p.get('duration',0)}s",
        "shake_screen":      lambda: f"x{p.get('intensity',0)}  {p.get('duration',0)}s",
        "camera_move_to":    lambda: f"({p.get('camera_target_x',0)}, {p.get('camera_target_y',0)})",
        "camera_offset":     lambda: f"({p.get('camera_offset_x',0)}, {p.get('camera_offset_y',0)})",
        "camera_shake":      lambda: f"x{p.get('shake_intensity',0)}  {p.get('shake_duration',0)}s",
        "scroll_bg":         lambda: f"{p.get('layer_name','')}  {p.get('scroll_direction','')} spd {p.get('scroll_speed',0)}",
        "layer_show":        lambda: p.get("layer_name",""),
        "layer_hide":        lambda: p.get("layer_name",""),
        "layer_set_image":   lambda: p.get("layer_name",""),
        "play_music":        lambda: p.get("audio_id",""),
        "play_sfx":          lambda: p.get("audio_id",""),
        "set_music_volume":  lambda: f"vol {p.get('volume',0)}",
        "set_speaker":       lambda: p.get("speaker_name",""),
        "set_dialogue_line": lambda: f"#{p.get('dialogue_line_index','')}  {str(p.get('dialogue_text',''))[:16]}",
        "set_choice_dest":   lambda: f"#{p.get('choice_index','')} → scene {p.get('choice_goto','')}",
        "set_choice_text":   lambda: f"#{p.get('choice_index','')}  {p.get('choice_text','')}",
        "set_variable":      lambda: f"{p.get('var_name','')} = {p.get('var_value','')}",
        "change_variable":   lambda: f"{p.get('var_name','')} {p.get('var_operator','')} {p.get('var_value','')}",
        "set_variable_from_variable": lambda: f"{p.get('var_name','')} = {p.get('var_source','')}",
        "change_variable_by_variable": lambda: f"{p.get('var_name','')} {p.get('var_operator','')} {p.get('var_source','')}",
        "evaluate_expression": lambda: f"{p.get('var_name','')} = {str(p.get('expression',''))[:18]}",
        "clamp_variable":    lambda: f"{p.get('var_name','')} [{p.get('clamp_min','?')}…{p.get('clamp_max','?')}]",
        "set_flag":          lambda: f"{p.get('bool_name','')} = {p.get('bool_value',False)}",
        "toggle_flag":       lambda: p.get("bool_name",""),
        "if_variable":       lambda: f"{p.get('var_name','')} {p.get('var_compare','')} {p.get('var_value','')}",
        "if_flag":           lambda: f"{p.get('bool_name','')} == {p.get('bool_expected',False)}",
        "add_item":          lambda: p.get("item_name",""),
        "remove_item":       lambda: p.get("item_name",""),
        "if_has_item":       lambda: p.get("item_name",""),
        "emit_signal":       lambda: f"📡 {p.get('signal_name','')}",
        "move_to":           lambda: f"({p.get('target_x',0)}, {p.get('target_y',0)})",
        "move_by":           lambda: f"({p.get('offset_x',0)}, {p.get('offset_y',0)})",
        "slide_to":          lambda: f"({p.get('target_x',0)}, {p.get('target_y',0)})  {p.get('duration',0)}s",
        "slide_by":          lambda: f"({p.get('offset_x',0)}, {p.get('offset_y',0)})  {p.get('duration',0)}s",
        "set_scale":         lambda: f"× {p.get('target_scale',1.0)}",
        "scale_to":          lambda: f"× {p.get('target_scale',1.0)}  {p.get('duration',0)}s",
        "set_rotation":      lambda: f"{p.get('target_rotation',0)}°",
        "rotate_to":         lambda: f"{p.get('target_rotation',0)}°  {p.get('duration',0)}s",
        "rotate_by":         lambda: f"{p.get('target_rotation',0)}°  {p.get('duration',0)}s",
        "spin":              lambda: f"{p.get('spin_speed',0)}°/s",
        "set_frame":         lambda: f"frame {p.get('frame_index',0)}",
        "set_anim_speed":    lambda: f"{p.get('anim_fps',12)} fps",
        "create_object":     lambda: (f"@ self +({p.get('spawn_offset_x',0)}, {p.get('spawn_offset_y',0)})" if p.get("spawn_at_self") else f"({p.get('target_x',0)}, {p.get('target_y',0)}) +({p.get('spawn_offset_x',0)}, {p.get('spawn_offset_y',0)})"),
        "four_way_movement": lambda: f"{p.get('movement_speed',4)} px/f  {p.get('movement_style','instant')}",
        "four_way_movement_collide": lambda: f"{p.get('movement_speed',4)} px/f  collide",
        "eight_way_movement": lambda: f"{p.get('movement_speed',4)} px/f  rot:{p.get('rotation_mode','instant')}",
        "eight_way_movement_collide": lambda: f"{p.get('movement_speed',4)} px/f  collide  rot:{p.get('rotation_mode','instant')}",
        "two_way_movement":  lambda: f"{p.get('two_way_axis','h')}  {p.get('movement_speed',4)} px/f",
        "fire_bullet":       lambda: f"→ {p.get('bullet_direction','right')}  {p.get('bullet_speed',6)} px/f",
        "set_velocity":  lambda: (
            f"vx={p.get('velocity_vx',0)}" if p.get('velocity_set_x',True) and not p.get('velocity_set_y',True)
            else f"vy={p.get('velocity_vy',0)}" if p.get('velocity_set_y',True) and not p.get('velocity_set_x',True)
            else f"vx={p.get('velocity_vx',0)}  vy={p.get('velocity_vy',0)}"
        ),
        "add_velocity":  lambda: (
            f"+vx={p.get('velocity_vx',0)}" if p.get('velocity_set_x',True) and not p.get('velocity_set_y',True)
            else f"+vy={p.get('velocity_vy',0)}" if p.get('velocity_set_y',True) and not p.get('velocity_set_x',True)
            else f"+vx={p.get('velocity_vx',0)}  +vy={p.get('velocity_vy',0)}"
        ),
        "jump":          lambda: f"↑{p.get('jump_strength',12)}  ×{p.get('jump_max_count',1)}{'  float' if p.get('jump_float') else ''}{'  var-h' if p.get('jump_variable_height') else ''}",
        "set_label_text":    lambda: str(p.get("dialogue_text",""))[:20],
        "log_message":       lambda: str(p.get("log_message",""))[:20],
        "follow_path":       lambda: f"🛤 {p.get('path_name','')}  {p.get('path_speed',1)} px/f{'  ↻' if p.get('path_loop') else ''}",
        "stop_path":         lambda: "⏸ stop",
        "resume_path":       lambda: "▶ resume",
        "set_path_speed":    lambda: f"{p.get('path_speed',1)} px/f",
        "layer_anim_play_macro": lambda: f"▶ {p.get('layer_anim_macro_name','?')}{'  ↻' if p.get('layer_anim_macro_loop') else ''}",
        "layer_anim_stop_macro": lambda: f"⏹ {p.get('layer_anim_macro_name','?')}",
        "layer_anim_set_blink":  lambda: f"blink {'ON' if p.get('layer_anim_enabled',True) else 'OFF'}",
        "layer_anim_set_idle":   lambda: f"idle {'ON' if p.get('layer_anim_enabled',True) else 'OFF'}",
        "layer_anim_set_talk":   lambda: f"talk {'ON' if p.get('layer_anim_enabled',True) else 'OFF'}",
        "layer_anim_talk_for":   lambda: f"talk {p.get('layer_anim_talk_duration',2.0)}s",
        # ── New nodes ──
        "wait_random":       lambda: f"{p.get('duration',0)}s – {p.get('wait_max',0)}s",
        "random_chance":     lambda: f"{p.get('var_value',0)}% chance",
        "random_set":        lambda: f"{p.get('var_name','')} = {p.get('clamp_min','?')}–{p.get('clamp_max','?')}",
        "get_position":      lambda: f"→ {p.get('var_name','x')}, {p.get('var_source','y')}",
        "if_distance":       lambda: f"{p.get('var_compare','<=')} {p.get('var_value','?')}px",
        "get_distance":      lambda: f"→ {p.get('var_name','dist')}",
        "cancel_all":        lambda: "⊘ cancel all",
        "attach_to":         lambda: p.get("parent_id", "") or "?",
        "detach":            lambda: "detach",
        "ani_switch_slot":   lambda: f"→ slot \"{p.get('ani_slot_name','')}\"",
        "ani_set_flip":      lambda: f"H:{p.get('ani_flip_h',False)}  V:{p.get('ani_flip_v',False)}",
        "play_anim":         lambda: f"slot \"{p.get('ani_slot_name','')}\"" if p.get('ani_slot_name') else "",
    }
    fn = summaries.get(code)
    return fn() if fn else ""


# ─────────────────────────────────────────────────────────────
#  NODE TYPE CONSTANTS
# ─────────────────────────────────────────────────────────────

NODE_TRIGGER = "trigger"
NODE_ACTION  = "action"
NODE_OBJECT  = "object"

COLOR = {
    "trigger_header":     QColor("#b45309"),
    "trigger_header2":    QColor("#92400e"),
    "trigger_border":     QColor("#f59e0b"),
    "trigger_border_sel": QColor("#fcd34d"),
    "action_header":      QColor("#1e3a5f"),
    "action_header2":     QColor("#172d4a"),
    "action_border":      QColor("#3b6ea8"),
    "action_border_sel":  QColor("#7c6aff"),
    "object_header":      QColor("#1a3d2b"),
    "object_header2":     QColor("#14301f"),
    "object_border":      QColor("#2d7a4a"),
    "object_border_sel":  QColor("#4ade80"),
    "port_out_fill":      QColor("#f59e0b"),
    "port_in_fill":       QColor("#7c6aff"),
    "port_true_fill":     QColor("#4ade80"),
    "port_false_fill":    QColor("#f87171"),
    "port_loop_fill":     QColor("#c084fc"),
    "port_hover":         QColor("#ffffff"),
    "port_border":        QColor("#1a1a24"),
    "body_normal":        QColor("#16161c"),
    "body_selected":      QColor("#1e1e2e"),
    "body_object":        QColor("#0f1a14"),
    "title_text":         QColor("#f0eeff"),
    "summary_text":       QColor("#7a7890"),
}


# ─────────────────────────────────────────────────────────────
#  PORT ITEM
# ─────────────────────────────────────────────────────────────

class PortItem(QGraphicsEllipseItem):
    RADIUS = 6

    def __init__(self, node, is_output: bool, port_id: str = "default", label: str = ""):
        r = self.RADIUS
        super().__init__(-r, -r, r*2, r*2, node)
        self.node       = node
        self.is_output  = is_output
        self.port_id    = port_id
        self.label      = label
        self.edges: list["EdgeItem"] = []
        self._label_item = None
        self._update_color()
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setZValue(2)
        if label:
            self._label_item = QGraphicsTextItem(label, node)
            self._label_item.setDefaultTextColor(COLOR["summary_text"])
            self._label_item.setFont(QFont("Segoe UI", 8))
            self._label_item.setZValue(3)

    def _update_color(self):
        if self.port_id == "true":       fill = COLOR["port_true_fill"]
        elif self.port_id == "false":    fill = COLOR["port_false_fill"]
        elif self.port_id == "loop":     fill = COLOR["port_loop_fill"]
        elif self.is_output:             fill = COLOR["port_out_fill"]
        else:                            fill = COLOR["port_in_fill"]
        self._normal_fill = fill
        self.setBrush(QBrush(fill))
        self.setPen(QPen(COLOR["port_border"], 1.5))

    def set_y_position(self, y: float):
        x = self.node.width if self.is_output else 0
        self.setPos(x, y)
        if self._label_item:
            lw = self._label_item.boundingRect().width()
            if self.is_output:
                self._label_item.setPos(x - lw - self.RADIUS - 3, y - 9)
            else:
                self._label_item.setPos(x + self.RADIUS + 3, y - 9)

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(COLOR["port_hover"]))
        self.setScale(1.3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(self._normal_fill))
        self.setScale(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_output:
            self.scene().views()[0].start_edge_drag(self)
            event.accept()
        else:
            event.ignore()


# ─────────────────────────────────────────────────────────────
#  EDGE ITEM
# ─────────────────────────────────────────────────────────────

class EdgeItem(QGraphicsPathItem):
    def __init__(self, src: PortItem, dst: PortItem):
        super().__init__()
        self.src = src
        self.dst = dst
        src.edges.append(self)
        dst.edges.append(self)
        self._edge_color = self._port_color(src)
        self.setPen(QPen(self._edge_color, 2))
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.refresh()

    def _port_color(self, port: PortItem) -> QColor:
        if port.port_id == "true":  return COLOR["port_true_fill"]
        if port.port_id == "false": return COLOR["port_false_fill"]
        if port.port_id == "loop":  return COLOR["port_loop_fill"]
        if port.is_output:          return COLOR["port_out_fill"]
        return COLOR["port_in_fill"]

    def refresh(self):
        self.setPath(_bezier(self.src.scene_center(), self.dst.scene_center()))

    def shape(self):
        s = QPainterPathStroker(); s.setWidth(14)
        return s.createStroke(self.path())

    def hoverEnterEvent(self, event):
        self.setPen(QPen(self._edge_color, 3))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(self._edge_color, 2))
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(); menu.setStyleSheet(MENU_STYLE)
        da = menu.addAction("✕  Delete Connection")
        if menu.exec(event.screenPos()) == da:
            self.delete_edge()

    def detach(self):
        if self in self.src.edges: self.src.edges.remove(self)
        if self in self.dst.edges: self.dst.edges.remove(self)

    def delete_edge(self):
        self.detach()
        if self.scene(): self.scene().removeItem(self)


def _snap(v: float, grid: int = GRID_SIZE) -> float:
    return round(v / grid) * grid


def _bezier(p1: QPointF, p2: QPointF) -> QPainterPath:
    path = QPainterPath(p1)
    dx = max(abs(p2.x() - p1.x()) * 0.55, 60)
    path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
    return path


# ─────────────────────────────────────────────────────────────
#  NODE ITEM
# ─────────────────────────────────────────────────────────────

class NodeItem(QGraphicsItem):

    def __init__(self, node_type: str, code: str, display_name: str, x=0, y=0):
        super().__init__()
        self.node_type    = node_type
        self.code         = code
        self.display_name = display_name
        self.params: dict = {}
        self._summary     = ""

        self.width    = 190
        self.header_h = 36
        self.body_h   = 28
        self.corner   = 8

        self.category     = get_action_category(code) if node_type == NODE_ACTION else ""
        self.accent_color = QColor(CATEGORY_ACCENTS.get(self.category, "#7c6aff")) if self.category else None
        self.is_branch    = (node_type == NODE_ACTION and code in BRANCH_TYPES)
        self.is_loop      = (node_type == NODE_ACTION and code in LOOP_TYPES)

        for field_name, _lbl, wtype, extra in get_fields(node_type, code):
            if wtype == "spin":         self.params[field_name] = extra.get("min", 0)
            elif wtype == "dspin":      self.params[field_name] = extra.get("min", 0.0)
            elif wtype == "check":      self.params[field_name] = False
            elif wtype == "combo":
                opts = extra.get("options", [])
                self.params[field_name] = opts[0] if opts else ""
            elif wtype == "scene_num":  self.params[field_name] = 1
            else:                       self.params[field_name] = ""

        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self._build_ports()
        self._recalc_size()

    def _build_ports(self):
        self.in_port = self.out_port = self.true_port = self.false_port = self.loop_port = None
        if self.node_type == NODE_TRIGGER:
            self.out_port  = PortItem(self, is_output=True,  port_id="default", label="")
        elif self.node_type == NODE_ACTION:
            self.in_port   = PortItem(self, is_output=False, port_id="default", label="")
            if self.is_branch:
                self.true_port  = PortItem(self, is_output=True, port_id="true",  label="✔ True")
                self.false_port = PortItem(self, is_output=True, port_id="false", label="✘ False")
            elif self.is_loop:
                self.loop_port = PortItem(self, is_output=True, port_id="loop",  label="↺ Body")
                self.out_port  = PortItem(self, is_output=True, port_id="default", label="")
            else:
                self.out_port = PortItem(self, is_output=True, port_id="default", label="")
        elif self.node_type == NODE_OBJECT:
            self.out_port  = PortItem(self, is_output=True,  port_id="default", label="")

    def _recalc_size(self):
        if self.is_branch:
            self.body_h = 56
        elif self.is_loop:
            self.body_h = 56
        else:
            self.body_h = 36 if self._summary else 28
        self.total_h = self.header_h + self.body_h

        if self.is_branch:
            mid_in = self.header_h + self.body_h // 2
            if self.in_port:    self.in_port.set_y_position(mid_in)
            if self.true_port:  self.true_port.set_y_position(self.header_h + 18)
            if self.false_port: self.false_port.set_y_position(self.header_h + 38)
        elif self.is_loop:
            mid_in = self.header_h + self.body_h // 2
            if self.in_port:   self.in_port.set_y_position(mid_in)
            if self.loop_port: self.loop_port.set_y_position(self.header_h + 18)
            if self.out_port:  self.out_port.set_y_position(self.header_h + 38)
        else:
            mid_y = self.header_h + self.body_h // 2
            if self.in_port:  self.in_port.set_y_position(mid_y)
            if self.out_port: self.out_port.set_y_position(mid_y)

    def update_summary(self):
        self.prepareGeometryChange()
        self._summary = build_summary(self.node_type, self.code, self.params)
        self._recalc_size()
        self.update()

    def boundingRect(self):
        return QRectF(-2, -2, self.width + 4, self.total_h + 4)

    def all_ports(self):
        return [p for p in [self.in_port, self.out_port, self.true_port, self.false_port, self.loop_port] if p]

    def paint(self, painter, _option=None, _widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        selected = self.isSelected()
        w, h, r  = self.width, self.total_h, self.corner

        if self.node_type == NODE_TRIGGER:
            bc = COLOR["trigger_border_sel"] if selected else COLOR["trigger_border"]
        elif self.node_type == NODE_OBJECT:
            bc = COLOR["object_border_sel"]  if selected else COLOR["object_border"]
        else:
            bc = COLOR["action_border_sel"]  if selected else COLOR["action_border"]

        body_col = (COLOR["body_object"]   if self.node_type == NODE_OBJECT else
                    COLOR["body_selected"] if selected else COLOR["body_normal"])
        painter.setBrush(QBrush(body_col))
        painter.setPen(QPen(bc, 2 if selected else 1.5))
        painter.drawRoundedRect(0, 0, w, h, r, r)

        if self.node_type == NODE_TRIGGER:
            c1, c2 = COLOR["trigger_header"], COLOR["trigger_header2"]
        elif self.node_type == NODE_OBJECT:
            c1, c2 = COLOR["object_header"], COLOR["object_header2"]
        else:
            c1, c2 = COLOR["action_header"], COLOR["action_header2"]

        grad = QLinearGradient(0, 0, 0, self.header_h)
        grad.setColorAt(0, c1); grad.setColorAt(1, c2)
        painter.setBrush(QBrush(grad)); painter.setPen(Qt.NoPen)
        hp = QPainterPath(); hp.addRoundedRect(0, 0, w, self.header_h + r, r, r)
        clip = QPainterPath(); clip.addRect(0, 0, w, self.header_h)
        painter.drawPath(hp.intersected(clip))

        if self.accent_color and self.node_type == NODE_ACTION:
            painter.setBrush(QBrush(self.accent_color))
            ap = QPainterPath(); ap.addRoundedRect(0, 0, w, 3, 1, 1)
            painter.drawPath(ap)

        if self.node_type == NODE_TRIGGER:
            badge_text, badge_col = "TRIGGER", QColor("#f59e0b")
        elif self.node_type == NODE_OBJECT:
            badge_text, badge_col = "OBJECT",  QColor("#4ade80")
        else:
            badge_text, badge_col = None, None

        bx = w
        if badge_text:
            painter.setFont(QFont("Segoe UI", 6, QFont.Bold))
            fm  = painter.fontMetrics()
            bw  = fm.horizontalAdvance(badge_text) + 10
            bh  = 13; bx = w - bw - 6; by = (self.header_h - bh) // 2 + 1
            bg  = QColor(badge_col.red(), badge_col.green(), badge_col.blue(), 50)
            painter.setBrush(QBrush(bg)); painter.setPen(QPen(badge_col, 1))
            painter.drawRoundedRect(bx, by, bw, bh, 3, 3)
            painter.setPen(badge_col)
            painter.drawText(bx, by, bw, bh, Qt.AlignCenter, badge_text)

        painter.setPen(QPen(COLOR["title_text"]))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(10, 0, bx - 14, self.header_h,
                         Qt.AlignVCenter | Qt.TextSingleLine, self.display_name)

        painter.setPen(QPen(bc, 1)); painter.setOpacity(0.25)
        painter.drawLine(0, self.header_h, w, self.header_h)
        painter.setOpacity(1.0)

        if self._summary and not self.is_branch and not self.is_loop:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(COLOR["summary_text"]))
            painter.drawText(14, self.header_h + 2, w - 28, self.body_h - 4,
                             Qt.AlignVCenter | Qt.TextSingleLine, self._summary)

        if self.is_branch:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#4ade80")))
            painter.drawText(14, self.header_h + 8,  w - 28, 16, Qt.AlignVCenter, "✔  True")
            painter.setPen(QPen(QColor("#f87171")))
            painter.drawText(14, self.header_h + 28, w - 28, 16, Qt.AlignVCenter, "✘  False")

        if self.is_loop:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#c084fc")))
            painter.drawText(14, self.header_h + 8,  w - 28, 16, Qt.AlignVCenter, "↺  Body")
            painter.setPen(QPen(COLOR["summary_text"]))
            count = self.params.get("loop_count", 0)
            label = f"× {count}" if count > 0 else "∞"
            painter.drawText(14, self.header_h + 28, w - 28, 16, Qt.AlignVCenter, label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            sc = self.scene()
            if sc and sc.views():
                view = sc.views()[0]
                if getattr(view, "_snap_enabled", False):
                    value = QPointF(_snap(value.x()), _snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            for port in self.all_ports():
                for edge in port.edges:
                    edge.refresh()
        if change == QGraphicsItem.ItemSelectedChange:
            sc = self.scene()
            if sc and sc.views():
                view = sc.views()[0]
                widget = view.parent()
                while widget is not None:
                    if hasattr(widget, "_inspector") and hasattr(widget._inspector, "show_node"):
                        if value:   widget._inspector.show_node(self)
                        else:       widget._inspector.clear()
                        break
                    widget = widget.parent()
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        menu = QMenu(); menu.setStyleSheet(MENU_STYLE)
        copy_a  = menu.addAction("⧉  Copy Node(s)")
        menu.addSeparator()
        da      = menu.addAction("✕  Delete Node")
        chosen  = menu.exec(event.screenPos())
        if chosen == da:
            self.delete_node()
        elif chosen == copy_a:
            sc = self.scene()
            if sc and sc.views():
                sc.views()[0].copy_selected()

    def delete_node(self):
        for edge in list(sum([p.edges for p in self.all_ports()], [])):
            edge.delete_edge()
        if self.scene(): self.scene().removeItem(self)


# ─────────────────────────────────────────────────────────────
#  LLM TEXT EXPORT / IMPORT
# ─────────────────────────────────────────────────────────────

def build_legend_text() -> str:
    lines = [
        "=== VITA ADVENTURE CREATOR — NODE LEGEND ===",
        "Use these exact codes when writing or editing node trees.",
        "",
        "━━ TRIGGERS ━━",
    ]
    for cat, codes in TRIGGER_CATEGORIES.items():
        lines.append(f"  [{cat}]")
        for code in codes:
            display = OBJECT_TRIGGERS.get(code, code)
            lines.append(f"    {code}  \"{display}\"")
            for field_name, label, wtype, extra in TRIGGER_FIELDS.get(code, []):
                if wtype == "combo":
                    opts = ", ".join(extra.get("options", []))
                    lines.append(f"      {field_name}: combo [{opts}]")
                elif wtype in ("spin", "scene_num"):
                    lines.append(f"      {field_name}: int ({extra.get('min',0)}–{extra.get('max',9999)})")
                elif wtype == "dspin":
                    lines.append(f"      {field_name}: float ({extra.get('min',0.0)}–{extra.get('max',999.0)})")
                elif wtype == "check":
                    lines.append(f"      {field_name}: bool (True/False)")
                else:
                    lines.append(f"      {field_name}: text")
    lines += ["", "━━ ACTIONS ━━"]
    for cat, items in ACTION_PALETTE.items():
        active = [(c, d) for c, d in items if c not in DEFERRED_ACTIONS]
        if not active:
            continue
        lines.append(f"  [{cat}]")
        for code, display in active:
            lines.append(f"    {code}  \"{display}\"")
            for field_name, label, wtype, extra in ACTION_FIELDS.get(code, []):
                if wtype == "combo":
                    opts = ", ".join(extra.get("options", []))
                    lines.append(f"      {field_name}: combo [{opts}]")
                elif wtype in ("spin", "scene_num"):
                    lines.append(f"      {field_name}: int ({extra.get('min',0)}–{extra.get('max',9999)})")
                elif wtype == "dspin":
                    lines.append(f"      {field_name}: float ({extra.get('min',0.0)}–{extra.get('max',999.0)})")
                elif wtype == "check":
                    lines.append(f"      {field_name}: bool (True/False)")
                elif wtype == "object":
                    lines.append(f"      {field_name}: object_id (use object name or id)")
                elif wtype == "paper_doll":
                    lines.append(f"      {field_name}: paper_doll_id (use layer animation name or id)")
                else:
                    lines.append(f"      {field_name}: text")
    lines += [
        "",
        "━━ NODE TREE FORMAT ━━",
        "  # Object: <n>  State: <state>",
        "  TRIGGER <trigger_code>  [param=value ...]",
        "    ACTION <action_code>  [param=value ...]",
        "    ACTION <branch_code>  [param=value ...]",
        "      TRUE: ACTION <action_code>  [param=value ...]",
        "      FALSE: ACTION <action_code>  [param=value ...]",
        "    ACTION loop  loop_count=3",
        "      LOOP: ACTION <action_code>  [param=value ...]",
        "",
        "  Indent with 2 spaces per level. Each TRIGGER starts a new tree.",
        "  Params are optional — omit if default is fine.",
    ]
    return "\n".join(lines)


def _format_params(params: dict) -> str:
    """Format a params dict as  key=value  pairs, skipping empty/default values."""
    parts = []
    for k, v in params.items():
        if v is None or v == "" or v == 0 or v == 0.0 or v is False:
            continue
        parts.append(f"{k}={v}")
    return ("  " + "  ".join(parts)) if parts else ""


def canvas_to_text(canvas, obj_name: str = "Object", state_name: str = "Default") -> str:
    """Serialize the canvas node graph to a structured human/LLM-readable string."""
    trigger_nodes = sorted(
        [i for i in canvas._scene.items()
         if isinstance(i, NodeItem) and i.node_type == NODE_TRIGGER],
        key=lambda n: n.pos().y()
    )

    def next_node(port):
        if not port or not port.edges:
            return None
        return port.edges[0].dst.node

    def format_chain(node, indent: int) -> list[str]:
        lines = []
        pad = "  " * indent
        while node is not None:
            params_str = _format_params(node.params)
            lines.append(f"{pad}ACTION {node.code}{params_str}")
            if node.is_branch:
                true_first  = next_node(node.true_port)
                false_first = next_node(node.false_port)
                if true_first:
                    lines.append(f"{pad}  TRUE:")
                    lines.extend(format_chain(true_first, indent + 2))
                if false_first:
                    lines.append(f"{pad}  FALSE:")
                    lines.extend(format_chain(false_first, indent + 2))
                break
            if node.is_loop:
                loop_first = next_node(node.loop_port)
                if loop_first:
                    lines.append(f"{pad}  LOOP:")
                    lines.extend(format_chain(loop_first, indent + 2))
                node = next_node(node.out_port)
                continue
            node = next_node(node.out_port)
        return lines

    out = [f"# Object: {obj_name}  State: {state_name}"]
    if not trigger_nodes:
        out.append("# (no nodes)")
        return "\n".join(out)

    for tnode in trigger_nodes:
        params_str = _format_params(tnode.params)
        out.append(f"TRIGGER {tnode.code}{params_str}")
        first = next_node(tnode.out_port)
        if first:
            out.extend(format_chain(first, 1))

    return "\n".join(out)


def text_to_nodes(text: str) -> tuple[list[dict], list[str]]:
    """
    Parse structured node-tree text back into a list of clipboard-format dicts.
    Returns (nodes_list, warnings).
    Each dict matches the clipboard format used by paste_nodes / _paste_at.
    """
    nodes   = []
    warnings = []
    idx     = 0

    parsed = []   # list of dicts: {level, node_type, code, params, branch_side}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue

        stripped = line.lstrip()
        indent   = len(line) - len(stripped)
        level    = indent // 2

        branch_side = None
        if stripped.startswith("TRUE:"):
            branch_side = "true"
            stripped    = stripped[5:].strip()
            level      += 1
        elif stripped.startswith("FALSE:"):
            branch_side = "false"
            stripped    = stripped[6:].strip()
            level      += 1
        elif stripped.startswith("LOOP:"):
            branch_side = "loop"
            stripped    = stripped[5:].strip()
            level      += 1

        parts     = stripped.split()
        if not parts:
            continue
        kind      = parts[0].upper()
        if kind not in ("TRIGGER", "ACTION"):
            continue
        if len(parts) < 2:
            warnings.append(f"Skipped (no code): {raw_line.strip()}")
            continue

        code = parts[1]

        # Validate code exists
        if kind == "TRIGGER" and code not in OBJECT_TRIGGERS:
            warnings.append(f"Unknown trigger '{code}' — skipped")
            continue
        if kind == "ACTION" and code not in ACTION_NAMES:
            warnings.append(f"Unknown action '{code}' — skipped")
            continue

        # Parse param=value pairs
        params = {}
        for token in parts[2:]:
            if "=" in token:
                k, _, v = token.partition("=")
                fields = get_fields(
                    NODE_TRIGGER if kind == "TRIGGER" else NODE_ACTION, code)
                wtype_map = {f[0]: f[2] for f in fields}
                wt = wtype_map.get(k, "text")
                try:
                    if wt in ("spin", "scene_num"):
                        params[k] = int(v)
                    elif wt == "dspin":
                        params[k] = float(v)
                    elif wt == "check":
                        params[k] = v.lower() in ("true", "1", "yes")
                    else:
                        params[k] = v
                except ValueError:
                    params[k] = v

        parsed.append({
            "level":       level,
            "node_type":   NODE_TRIGGER if kind == "TRIGGER" else NODE_ACTION,
            "code":        code,
            "params":      params,
            "branch_side": branch_side,
        })

    if not parsed:
        return [], ["No valid nodes found in text."]

    # Assign positions and build clipboard entries
    XSTEP = 220
    YSTEP = 160

    trigger_count = 0
    stack: list[tuple[dict, dict]] = []

    for p in parsed:
        node_type    = p["node_type"]
        code         = p["code"]
        display_name = (OBJECT_TRIGGERS.get(code, code)
                        if node_type == NODE_TRIGGER
                        else ACTION_NAMES.get(code, code))

        level = p["level"]
        if node_type == NODE_TRIGGER:
            rx = -600
            ry = trigger_count * YSTEP
            trigger_count += 1
        else:
            rx = -360 + level * XSTEP
            base_y = 0
            for s_p, s_n in reversed(stack):
                if s_p["node_type"] == NODE_TRIGGER:
                    base_y = s_n["ry"]
                    break
            branch_offset = 0
            if p["branch_side"] == "true":
                branch_offset = -70
            elif p["branch_side"] == "false":
                branch_offset = 70
            elif p["branch_side"] == "loop":
                branch_offset = -35
            ry = base_y + branch_offset

        entry = {
            "node_type":    node_type,
            "code":         code,
            "display_name": display_name,
            "params":       p["params"],
            "rx":           float(rx),
            "ry":           float(ry),
            "idx":          idx,
            "out_edges":    [],
            "_level":       level,
            "_branch_side": p["branch_side"],
        }
        idx += 1

        # Wire edge from parent
        if stack:
            for s_p, s_n in reversed(stack):
                s_level = s_p["level"]
                s_type  = s_p["node_type"]
                s_code  = s_p["code"]
                is_branch_parent = (s_type == NODE_ACTION and s_code in BRANCH_TYPES)
                is_loop_parent   = (s_type == NODE_ACTION and s_code in LOOP_TYPES)

                if p["branch_side"] and is_branch_parent and s_level == level - 2:
                    src_port = p["branch_side"]
                    s_n["out_edges"].append({
                        "src_port":      src_port,
                        "src_is_output": True,
                        "dst_idx":       entry["idx"],
                        "dst_port":      "default",
                        "dst_is_output": False,
                    })
                    break
                elif p["branch_side"] == "loop" and is_loop_parent and s_level == level - 2:
                    s_n["out_edges"].append({
                        "src_port":      "loop",
                        "src_is_output": True,
                        "dst_idx":       entry["idx"],
                        "dst_port":      "default",
                        "dst_is_output": False,
                    })
                    break
                elif not p["branch_side"] and s_level == level - 1 and not is_branch_parent:
                    s_n["out_edges"].append({
                        "src_port":      "default",
                        "src_is_output": True,
                        "dst_idx":       entry["idx"],
                        "dst_port":      "default",
                        "dst_is_output": False,
                    })
                    break
                elif not p["branch_side"] and s_level == level and not p["branch_side"]:
                    if s_type == NODE_ACTION and s_level == level:
                        s_n["out_edges"].append({
                            "src_port":      "default",
                            "src_is_output": True,
                            "dst_idx":       entry["idx"],
                            "dst_port":      "default",
                            "dst_is_output": False,
                        })
                        break

        stack.append((p, entry))
        nodes.append(entry)

    return nodes, warnings


# ─────────────────────────────────────────────────────────────
#  NODE CANVAS  (one per state)
# ─────────────────────────────────────────────────────────────

class NodeCanvas(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene()
        self._scene.setSceneRect(-4000, -4000, 8000, 8000)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setBackgroundBrush(QBrush(QColor("#0f0f12")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet("border: none;")
        self.setFocusPolicy(Qt.StrongFocus)

        self._panning        = False
        self._pan_start      = QPointF()
        self._drag_source: PortItem | None = None
        self._drag_edge: QGraphicsPathItem | None = None
        self._spawn_offset   = 0
        self._snap_enabled   = True
        self._clipboard: list[dict] = []

        self._draw_grid()

    def _draw_grid(self):
        minor = QPen(QColor("#16161e"), 1)
        major = QPen(QColor("#1e1e2a"), 1)
        step  = 40
        for x in range(-4000, 4001, step):
            self._scene.addLine(x, -4000, x, 4000, major if x%(step*4)==0 else minor)
        for y in range(-4000, 4001, step):
            self._scene.addLine(-4000, y, 4000, y, major if y%(step*4)==0 else minor)

    def add_node(self, node_type: str, code: str, display_name: str) -> NodeItem:
        vc = self.viewport().rect().center()
        sp = self.mapToScene(vc)
        x  = sp.x() + self._spawn_offset
        y  = sp.y() + self._spawn_offset
        self._spawn_offset = (self._spawn_offset + 20) % 100
        if self._snap_enabled:
            x, y = _snap(x), _snap(y)
        node = NodeItem(node_type, code, display_name, x, y)
        self._scene.addItem(node)
        return node

    def clear_canvas(self):
        self._scene.clear()
        self._spawn_offset = 0
        self._draw_grid()

    def wheelEvent(self, event):
        cur    = self.transform().m11()
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        new    = cur * factor
        if new < MIN_ZOOM:   factor = MIN_ZOOM / cur
        elif new > MAX_ZOOM: factor = MAX_ZOOM / cur
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True; self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.pos() - self._pan_start; self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept(); return
        if self._drag_source is not None:
            self._drag_edge.setPath(
                _bezier(self._drag_source.scene_center(), self.mapToScene(event.pos())))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False; self.setCursor(Qt.ArrowCursor); event.accept(); return
        if self._drag_source is not None and event.button() == Qt.LeftButton:
            target = None
            for item in self.items(event.pos()):
                if isinstance(item, PortItem):
                    target = item; break
            if target and not target.is_output and target.node is not self._drag_source.node:
                self._scene.addItem(EdgeItem(self._drag_source, target))
            self._scene.removeItem(self._drag_edge)
            self._drag_edge = self._drag_source = None
            event.accept(); return
        super().mouseReleaseEvent(event)

    def start_edge_drag(self, source: PortItem):
        self._drag_source = source
        self._drag_edge   = QGraphicsPathItem()
        self._drag_edge.setPen(QPen(source._normal_fill, 2, Qt.DashLine))
        self._drag_edge.setZValue(10)
        self._scene.addItem(self._drag_edge)

    # ── Keyboard shortcuts ────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            for item in list(self._scene.selectedItems()):
                if isinstance(item, NodeItem):
                    item.delete_node()
            event.accept(); return
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_C:
                self.copy_selected(); event.accept(); return
            if event.key() == Qt.Key_V:
                self.paste_nodes(); event.accept(); return
            if event.key() == Qt.Key_A:
                for item in self._scene.items():
                    if isinstance(item, NodeItem):
                        item.setSelected(True)
                event.accept(); return
        super().keyPressEvent(event)

    # ── Copy / Paste ──────────────────────────────────────────

    def copy_selected(self):
        """Serialise selected NodeItems into self._clipboard."""
        nodes = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        if not nodes:
            return
        cx = sum(n.pos().x() for n in nodes) / len(nodes)
        cy = sum(n.pos().y() for n in nodes) / len(nodes)
        self._clipboard = []
        id_map = {id(n): idx for idx, n in enumerate(nodes)}
        for n in nodes:
            entry = {
                "node_type":    n.node_type,
                "code":         n.code,
                "display_name": n.display_name,
                "params":       dict(n.params),
                "rx":           n.pos().x() - cx,
                "ry":           n.pos().y() - cy,
                "idx":          id_map[id(n)],
            }
            out_edges = []
            for port in n.all_ports():
                if port.is_output:
                    for edge in port.edges:
                        dst_node = edge.dst.node
                        if id(dst_node) in id_map:
                            out_edges.append({
                                "src_port":      port.port_id,
                                "src_is_output": True,
                                "dst_idx":       id_map[id(dst_node)],
                                "dst_port":      edge.dst.port_id,
                                "dst_is_output": False,
                            })
            entry["out_edges"] = out_edges
            self._clipboard.append(entry)

    def paste_nodes(self):
        """Instantiate a copy of _clipboard near the current view centre."""
        if not self._clipboard:
            return
        vc = self.viewport().rect().center()
        sp = self.mapToScene(vc)
        self._paste_at(sp)

    # ── Node group insert ─────────────────────────────────────

    def insert_node_group(self, group: dict):
        """Stamp a saved node-group dict onto the canvas (same format as clipboard)."""
        if not group.get("nodes"):
            return
        old_cb = self._clipboard
        self._clipboard = group["nodes"]
        self.paste_nodes()
        self._clipboard = old_cb

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None and not isinstance(item, (QGraphicsPathItem,)):
            super().contextMenuEvent(event)
            return
        menu = QMenu(self); menu.setStyleSheet(MENU_STYLE)

        paste_a      = menu.addAction("⧉  Paste")
        paste_a.setEnabled(bool(self._clipboard))

        menu.addSeparator()

        copy_text_a  = menu.addAction("📋  Copy Nodes as Text")
        paste_text_a = menu.addAction("📝  Paste Nodes from Text")

        chosen = menu.exec(event.globalPos())
        if chosen == paste_a:
            self._paste_at(self.mapToScene(event.pos()))
        elif chosen == copy_text_a:
            self.copy_nodes_as_text()
        elif chosen == paste_text_a:
            self.paste_nodes_from_text(self.mapToScene(event.pos()))

    # ── Toast notification ────────────────────────────────────

    def _show_toast(self, message: str):
        """Show a brief floating label over the canvas that fades after 2s."""
        toast = QLabel(message, self)
        toast.setStyleSheet("""
            QLabel {
                background: #26263a; color: #e8e6f0;
                border: 1px solid #7c6aff; border-radius: 6px;
                padding: 6px 16px; font: 11px 'Segoe UI';
            }
        """)
        toast.adjustSize()
        x = (self.width()  - toast.width())  // 2
        y = 12
        toast.move(x, y)
        toast.show()
        QTimer.singleShot(2000, toast.deleteLater)

    # ── LLM text export / import ──────────────────────────────

    def copy_nodes_as_text(self):
        """Export selected (or all) nodes as structured text to system clipboard."""
        obj_name   = "Object"
        state_name = "Default"
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, "_obj"):
                obj_name = getattr(widget._obj, "name", "Object")
            if hasattr(widget, "_state_machine"):
                state_name = widget._state_machine._tab_bar.current_name()
                break
            widget = widget.parent()

        selected = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        text = canvas_to_text(self, obj_name, state_name)
        if selected:
            selected_ids = {id(n) for n in selected}

            class _Proxy:
                class _Scene:
                    def __init__(self, nodes):
                        self._nodes = nodes
                    def items(self):
                        return self._nodes
                def __init__(self, nodes):
                    self._scene = self._Scene(nodes)

            proxy = _Proxy(selected)
            text = canvas_to_text(proxy, obj_name, state_name)

        QApplication.clipboard().setText(text)
        count = len(selected) if selected else sum(
            1 for i in self._scene.items() if isinstance(i, NodeItem))
        self._show_toast(f"📋 Copied {count} node(s) as text")

    def paste_nodes_from_text(self, scene_pos: QPointF | None = None):
        """Read structured node text from system clipboard and stamp onto canvas."""
        text = QApplication.clipboard().text()
        if not text.strip():
            self._show_toast("⚠ Clipboard is empty")
            return

        nodes, warnings = text_to_nodes(text)
        if not nodes:
            self._show_toast("⚠ No valid nodes found in clipboard text")
            return

        old_cb = self._clipboard
        self._clipboard = nodes
        if scene_pos is not None:
            self._paste_at(scene_pos)
        else:
            self.paste_nodes()
        self._clipboard = old_cb

        msg = f"📝 Pasted {len(nodes)} node(s)"
        if warnings:
            msg += f"  ({len(warnings)} warning(s))"
        self._show_toast(msg)

    def _paste_at(self, scene_pos: QPointF):
        """Paste clipboard centred on a specific scene position."""
        if not self._clipboard:
            return
        cx, cy = scene_pos.x(), scene_pos.y()
        if self._snap_enabled:
            cx, cy = _snap(cx), _snap(cy)

        self._scene.clearSelection()
        new_nodes: list[NodeItem] = []
        for entry in self._clipboard:
            x = cx + entry["rx"]
            y = cy + entry["ry"]
            if self._snap_enabled:
                x, y = _snap(x), _snap(y)
            node = NodeItem(entry["node_type"], entry["code"], entry["display_name"], x, y)
            node.params = dict(entry["params"])
            node.update_summary()
            self._scene.addItem(node)
            node.setSelected(True)
            new_nodes.append(node)

        port_by_id = {}
        for node, entry in zip(new_nodes, self._clipboard):
            for port in node.all_ports():
                port_by_id[(entry["idx"], port.port_id, port.is_output)] = port

        for entry in self._clipboard:
            for oe in entry.get("out_edges", []):
                src_port = port_by_id.get((entry["idx"],  oe["src_port"], True))
                dst_port = port_by_id.get((oe["dst_idx"], oe["dst_port"], False))
                if src_port and dst_port:
                    self._scene.addItem(EdgeItem(src_port, dst_port))


# ─────────────────────────────────────────────────────────────
#  CUSTOM TAB BAR
# ─────────────────────────────────────────────────────────────

class StateTabBar(QWidget):
    """
    Custom tab bar showing Default (undeletable, unrenameable) plus
    named state tabs. Emits tab_changed(index) when selection changes.
    """
    tab_changed = Signal(int)

    DEFAULT_NAME = "Default"

    _TAB_STYLE_ACTIVE = """
        QPushButton {{
            background: #1e1e28; color: #e8e6f0;
            border: none; border-bottom: 2px solid #7c6aff;
            padding: 0 14px; font: 11px 'Segoe UI'; border-radius: 0;
        }}
    """
    _TAB_STYLE_INACTIVE = """
        QPushButton {{
            background: transparent; color: #4a4860;
            border: none; border-bottom: 2px solid transparent;
            padding: 0 14px; font: 11px 'Segoe UI'; border-radius: 0;
        }}
        QPushButton:hover {{ color: #9990b8; }}
    """
    _DEFAULT_ACTIVE = """
        QPushButton {{
            background: #1e1e28; color: #c084fc;
            border: none; border-bottom: 2px solid #c084fc;
            padding: 0 14px; font: bold 11px 'Segoe UI'; border-radius: 0;
        }}
    """
    _DEFAULT_INACTIVE = """
        QPushButton {{
            background: transparent; color: #6b4fa8;
            border: none; border-bottom: 2px solid transparent;
            padding: 0 14px; font: bold 11px 'Segoe UI'; border-radius: 0;
        }}
        QPushButton:hover {{ color: #c084fc; }}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(f"background: #16161c; border-bottom: 1px solid #2e2e42;")

        self._tabs: list[str] = [self.DEFAULT_NAME]
        self._current = 0

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 8, 0)
        self._layout.setSpacing(0)

        self._btn_container = QWidget()
        self._btn_container.setStyleSheet("background: transparent;")
        self._btn_layout = QHBoxLayout(self._btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout.setSpacing(0)
        self._layout.addWidget(self._btn_container)
        self._layout.addStretch()

        self._add_btn = QPushButton("＋ Add State")
        self._add_btn.setFixedHeight(24)
        self._add_btn.setStyleSheet("""
            QPushButton { background: #26263a; color: #7c6aff;
                border: 1px solid #2e2e42; border-radius: 3px;
                padding: 0 10px; font: 11px 'Segoe UI'; }
            QPushButton:hover { background: #2e2e42; border-color: #7c6aff; }
        """)
        self._add_btn.clicked.connect(self._on_add)
        self._layout.addWidget(self._add_btn)

        self._rename_btn = QPushButton("✎ Rename")
        self._rename_btn.setFixedHeight(24)
        self._rename_btn.setStyleSheet("""
            QPushButton { background: #26263a; color: #7a7890;
                border: 1px solid #2e2e42; border-radius: 3px;
                padding: 0 10px; font: 11px 'Segoe UI'; margin-left: 6px; }
            QPushButton:hover { background: #2e2e42; color: #e8e6f0; }
        """)
        self._rename_btn.clicked.connect(self._on_rename)
        self._layout.addWidget(self._rename_btn)

        self._del_btn = QPushButton("✕")
        self._del_btn.setFixedSize(24, 24)
        self._del_btn.setToolTip("Delete state")
        self._del_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #4a4860;
                border: 1px solid #2e2e42; border-radius: 3px;
                font: 11px 'Segoe UI'; margin-left: 4px; }
            QPushButton:hover { background: #f87171; color: white; border-color: #f87171; }
        """)
        self._del_btn.clicked.connect(self._on_delete)
        self._layout.addWidget(self._del_btn)

        self._rebuild_buttons()

    # ── Public ────────────────────────────────────────────────

    def current_index(self) -> int:
        return self._current

    def current_name(self) -> str:
        return self._tabs[self._current]

    def state_names(self) -> list[str]:
        return list(self._tabs)

    def add_state(self, name: str):
        self._tabs.append(name)
        self._rebuild_buttons()
        self._select(len(self._tabs) - 1)

    def rename_state(self, index: int, new_name: str):
        if index == 0:
            return
        self._tabs[index] = new_name
        self._rebuild_buttons()

    def remove_state(self, index: int):
        if index == 0 or len(self._tabs) <= 1:
            return
        self._tabs.pop(index)
        new_idx = min(self._current, len(self._tabs) - 1)
        self._rebuild_buttons()
        self._select(new_idx)

    # ── Slots ─────────────────────────────────────────────────

    def _on_add(self):
        name, ok = QInputDialog.getText(
            self, "New State", "State name:",
            text="NewState"
        )
        if ok and name.strip():
            name = name.strip()
            if name == self.DEFAULT_NAME or name in self._tabs:
                QMessageBox.warning(self, "Duplicate Name",
                    f'A state named "{name}" already exists.')
                return
            self.add_state(name)

    def _on_rename(self):
        if self._current == 0:
            QMessageBox.information(self, "Rename",
                "The Default state cannot be renamed.")
            return
        old = self._tabs[self._current]
        name, ok = QInputDialog.getText(
            self, "Rename State", "New name:", text=old)
        if ok and name.strip() and name.strip() != old:
            name = name.strip()
            if name == self.DEFAULT_NAME or name in self._tabs:
                QMessageBox.warning(self, "Duplicate Name",
                    f'A state named "{name}" already exists.')
                return
            self.rename_state(self._current, name)

    def _on_delete(self):
        if self._current == 0:
            QMessageBox.information(self, "Delete",
                "The Default state cannot be deleted.")
            return
        name = self._tabs[self._current]
        reply = QMessageBox.question(
            self, "Delete State",
            f'Delete state "{name}" and all its nodes?',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.remove_state(self._current)

    def _select(self, index: int):
        self._current = index
        self._rebuild_buttons()
        self.tab_changed.emit(index)

    def _rebuild_buttons(self):
        while self._btn_layout.count():
            item = self._btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, name in enumerate(self._tabs):
            btn = QPushButton(name)
            btn.setFixedHeight(36)
            btn.setMinimumWidth(80)
            is_active  = (i == self._current)
            is_default = (i == 0)
            if is_default:
                btn.setStyleSheet(self._DEFAULT_ACTIVE if is_active else self._DEFAULT_INACTIVE)
            else:
                btn.setStyleSheet(self._TAB_STYLE_ACTIVE if is_active else self._TAB_STYLE_INACTIVE)
            btn.clicked.connect(lambda checked=False, idx=i: self._select(idx))
            self._btn_layout.addWidget(btn)

        is_default_selected = (self._current == 0)
        self._rename_btn.setEnabled(not is_default_selected)
        self._del_btn.setEnabled(not is_default_selected)
        self._rename_btn.setStyleSheet(self._rename_btn.styleSheet())


# ─────────────────────────────────────────────────────────────
#  STATE MACHINE WIDGET  (tab bar + stacked canvases)
# ─────────────────────────────────────────────────────────────

class StateMachineWidget(QWidget):
    """
    Owns the tab bar and a QStackedWidget of NodeCanvas instances.
    One canvas per state. Default canvas has a pre-built sample graph.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_bar = StateTabBar()
        self._tab_bar.tab_changed.connect(self._on_tab_changed)
        root.addWidget(self._tab_bar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #0f0f12;")
        root.addWidget(self._stack, stretch=1)

        self._node_groups: dict[str, dict] = {}

        default_canvas = NodeCanvas()
        self._add_sample_nodes(default_canvas)
        self._stack.addWidget(default_canvas)

    # ── Public API ────────────────────────────────────────────

    def current_canvas(self) -> NodeCanvas:
        return self._stack.currentWidget()

    def add_node(self, node_type: str, code: str, display_name: str):
        return self.current_canvas().add_node(node_type, code, display_name)

    def clear_current(self):
        self.current_canvas().clear_canvas()

    def state_names(self) -> list[str]:
        return self._tab_bar.state_names()

    # ── Node groups ───────────────────────────────────────────

    def get_groups(self) -> dict:
        return dict(self._node_groups)

    def set_groups(self, groups: dict):
        self._node_groups = dict(groups)

    def save_group(self, name: str):
        """Save currently selected nodes on the active canvas as a named group."""
        canvas = self.current_canvas()
        canvas.copy_selected()
        if not canvas._clipboard:
            return False
        self._node_groups[name] = {"nodes": list(canvas._clipboard)}
        return True

    def insert_group(self, name: str):
        """Stamp a named group onto the active canvas."""
        group = self._node_groups.get(name)
        if group:
            self.current_canvas().insert_node_group(group)

    def delete_group(self, name: str):
        self._node_groups.pop(name, None)

    def group_names(self) -> list[str]:
        return list(self._node_groups.keys())

    # ── Slots ─────────────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        while self._stack.count() <= index:
            canvas = NodeCanvas()
            self._stack.addWidget(canvas)
        self._stack.setCurrentIndex(index)

        while self._stack.count() > len(self._tab_bar.state_names()):
            widget = self._stack.widget(self._stack.count() - 1)
            self._stack.removeWidget(widget)
            widget.deleteLater()

    # ── Sample ────────────────────────────────────────────────

    def _add_sample_nodes(self, canvas: NodeCanvas):
        t = NodeItem(NODE_TRIGGER, "on_button_pressed", "On Button Pressed", -300, -80)
        t.params["button"] = "cross"; t.update_summary()

        a = NodeItem(NODE_ACTION, "show_dialogue", "Show Dialogue Box", -80, -80)

        b = NodeItem(NODE_ACTION, "if_flag", "If Flag", 160, -80)
        b.params["bool_name"] = "has_sword"; b.update_summary()

        t1 = NodeItem(NODE_ACTION, "go_to_scene", "Go to Scene", 400, -120)
        t1.params["target_scene"] = 3; t1.update_summary()

        t2 = NodeItem(NODE_ACTION, "go_to_state", "Go to State", 400, -20)
        t2.params["target_state"] = "Chase"; t2.update_summary()

        obj = NodeItem(NODE_OBJECT, "player", "Player", -300, 100)

        for n in (t, a, b, t1, t2, obj):
            canvas._scene.addItem(n)
        for src, dst in [
            (t.out_port, a.in_port),
            (a.out_port, b.in_port),
            (b.true_port, t1.in_port),
            (b.false_port, t2.in_port),
        ]:
            canvas._scene.addItem(EdgeItem(src, dst))


# ─────────────────────────────────────────────────────────────
#  INSPECTOR
# ─────────────────────────────────────────────────────────────

class Inspector(QFrame):
    def __init__(self, scene_objects=None, project=None):
        super().__init__()
        self._scene_objects: list = scene_objects or []
        self._project = project
        self.setMinimumWidth(240)
        self.setMaximumWidth(300)
        self._current_node: NodeItem | None = None
        self.setStyleSheet("QFrame { background: #16161c; border-left: 1px solid #2e2e42; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(36)
        hdr.setStyleSheet("background: #1e1e28; border-bottom: 1px solid #2e2e42;")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(12, 0, 12, 0)
        self._title_lbl = QLabel("INSPECTOR")
        self._title_lbl.setStyleSheet(
            "color: #4a4860; font: bold 10px 'Segoe UI'; letter-spacing: 1.5px; background: transparent;")
        hh.addWidget(self._title_lbl)
        root.addWidget(hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        self._body = QWidget(); self._body.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(5)
        self._layout.addStretch()
        scroll.setWidget(self._body)
        root.addWidget(scroll, stretch=1)

    def show_node(self, node: NodeItem):
        self._current_node = node
        self._rebuild()

    def clear(self):
        self._current_node = None
        self._rebuild()

    def _rebuild(self):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if self._current_node is None:
            self._title_lbl.setText("INSPECTOR"); return

        node = self._current_node
        self._title_lbl.setText(f"INSPECTOR  —  {node.display_name[:22]}")

        if node.node_type == NODE_TRIGGER: bt, bc = "TRIGGER", "#f59e0b"
        elif node.node_type == NODE_OBJECT: bt, bc = "OBJECT",  "#4ade80"
        else:                               bt, bc = "ACTION",  "#7c6aff"

        idx = 0
        def ins(w):
            nonlocal idx
            self._layout.insertWidget(idx, w); idx += 1

        ins(self._badge(bt, bc))
        ins(self._divider())

        fields = get_fields(node.node_type, node.code)
        if fields:
            ins(self._section("PARAMETERS"))
            for field_name, label_text, wtype, extra in fields:
                ins(self._field_row(node, field_name, label_text, wtype, extra))
            ins(self._divider())

        if node.is_branch:
            ins(self._note("Splits into True and False execution branches."))
            ins(self._divider())

        if node.is_loop:
            ins(self._note("Body port connects actions to repeat. Out port continues after the loop."))
            ins(self._divider())

        ins(self._section("NODE INFO"))
        ins(self._kv("Code", node.code))
        if node.category: ins(self._kv("Category", node.category))

    def _badge(self, text, color):
        w = QWidget(); w.setFixedHeight(26)
        l = QHBoxLayout(w); l.setContentsMargins(0, 2, 0, 2)
        b = QLabel(text)
        b.setStyleSheet(f"color:{color}; background:{color}22; border:1px solid {color}55;"
                        f"border-radius:3px; font:bold 9px 'Segoe UI'; padding:2px 8px; letter-spacing:1px;")
        l.addWidget(b); l.addStretch(); return w

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine); f.setFixedHeight(1)
        f.setStyleSheet("background:#2e2e42; border:none; margin:2px 0;"); return f

    def _section(self, text):
        l = QLabel(text)
        l.setStyleSheet("color:#4a4860; font:bold 9px 'Segoe UI';"
                        "letter-spacing:1.5px; background:transparent; padding:4px 0 2px 0;")
        return l

    def _note(self, text):
        l = QLabel(text); l.setWordWrap(True)
        l.setStyleSheet("color:#4a4860; font:italic 10px 'Segoe UI'; background:transparent;")
        return l

    def _kv(self, key, val):
        w = QWidget(); rl = QHBoxLayout(w)
        rl.setContentsMargins(0, 1, 0, 1); rl.setSpacing(8)
        k = QLabel(key); k.setFixedWidth(72)
        k.setStyleSheet("color:#4a4860; font:10px 'Segoe UI'; background:transparent;")
        v = QLabel(val); v.setWordWrap(True)
        v.setStyleSheet("color:#7a7890; font:10px 'Segoe UI'; background:transparent;")
        rl.addWidget(k); rl.addWidget(v, stretch=1); return w

    def _field_row(self, node, field_name, label_text, wtype, extra):
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 2, 0, 2); cl.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color:#7a7890; font:10px 'Segoe UI'; background:transparent;")
        cl.addWidget(lbl)
        cur = node.params.get(field_name)

        if wtype == "text":
            w = QLineEdit(str(cur or "")); w.setStyleSheet(FIELD_STYLE)
            w.textChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))
        elif wtype == "spin":
            w = QSpinBox(); w.setStyleSheet(FIELD_STYLE)
            w.setRange(extra.get("min",0), extra.get("max",9999))
            try: w.setValue(int(cur or 0))
            except: pass
            w.valueChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))
        elif wtype == "dspin":
            w = QDoubleSpinBox(); w.setStyleSheet(FIELD_STYLE)
            w.setRange(extra.get("min",0.0), extra.get("max",999.0))
            w.setSingleStep(extra.get("step",0.1)); w.setDecimals(2)
            try: w.setValue(float(cur or 0.0))
            except: pass
            w.valueChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))
        elif wtype == "check":
            w = QCheckBox(); w.setStyleSheet(FIELD_STYLE); w.setChecked(bool(cur))
            w.stateChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, bool(v)))
        elif wtype == "combo":
            w = QComboBox(); w.setStyleSheet(FIELD_STYLE)
            for opt in extra.get("options",[]): w.addItem(opt)
            if cur in extra.get("options",[]): w.setCurrentText(str(cur))
            w.currentTextChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))
        elif wtype == "scene_num":
            w = QSpinBox(); w.setStyleSheet(FIELD_STYLE); w.setRange(1, 999)
            try: w.setValue(int(cur or 1))
            except: pass
            w.valueChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))
        elif wtype == "object":
            w = QComboBox(); w.setStyleSheet(FIELD_STYLE)
            w.addItem("— none —", "")
            for def_id, name in self._scene_objects:
                w.addItem(name, def_id)
            idx = w.findData(cur or "")
            if idx >= 0:
                w.setCurrentIndex(idx)
            w.currentIndexChanged.connect(
                lambda _, fn=field_name, nd=node, ww=w:
                self._set(nd, fn, ww.currentData() or ""))
        elif wtype == "collision_layer":
            w = QComboBox(); w.setStyleSheet(FIELD_STYLE)
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
            if not matched and not cur and w.count() > 1:
                w.setCurrentIndex(1)
                self._set(node, field_name, w.itemData(1) or "")
            w.currentIndexChanged.connect(
                lambda _, fn=field_name, nd=node, ww=w:
                self._set(nd, fn, ww.currentData() or ""))
        elif wtype in ("audio", "image", "signal"):
            w = QComboBox(); w.setStyleSheet(FIELD_STYLE)
            w.addItem("— not connected —", None)
            if cur: w.addItem(str(cur), cur); w.setCurrentIndex(1)
            w.setToolTip(f"Populated from project on engine integration ({wtype})")
            w.currentIndexChanged.connect(
                lambda _, fn=field_name, nd=node, ww=w:
                self._set(nd, fn, ww.currentData() or ""))
        elif wtype == "paper_doll":
            w = QComboBox(); w.setStyleSheet(FIELD_STYLE)
            w.addItem("— none —", "")
            if self._project:
                for doll in self._project.paper_dolls:
                    w.addItem(doll.name, doll.id)
            idx = w.findData(cur or "")
            if idx >= 0:
                w.setCurrentIndex(idx)
            w.currentIndexChanged.connect(
                lambda _, fn=field_name, nd=node, ww=w:
                self._set(nd, fn, ww.currentData() or ""))
        else:
            w = QLineEdit(str(cur or "")); w.setStyleSheet(FIELD_STYLE)
            w.textChanged.connect(lambda v, fn=field_name, nd=node: self._set(nd, fn, v))

        cl.addWidget(w)
        return container

    def _set(self, node, field_name, value):
        node.params[field_name] = value
        node.update_summary()


# ─────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vita Adventure Creator — Node Canvas")
        self.resize(1440, 860)
        self.setStyleSheet("""
            QMainWindow { background: #0f0f12; }
            QToolBar { background: #16161c; border-bottom: 1px solid #2e2e42;
                       padding: 4px 10px; spacing: 6px; }
            QPushButton { background: #26263a; color: #e8e6f0;
                border: 1px solid #2e2e42; padding: 5px 14px;
                border-radius: 4px; font: 11px 'Segoe UI'; }
            QPushButton:hover { background: #2e2e42; border-color: #7c6aff; }
            QPushButton:pressed { background: #1e1e28; }
            QPushButton::menu-indicator { image: none; }
        """)

        self.state_machine = StateMachineWidget()
        self.inspector     = Inspector()
        self._setup_toolbar()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.state_machine)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStyleSheet("QSplitter::handle { background: #2e2e42; width: 1px; }")
        self.setCentralWidget(splitter)

    def _setup_toolbar(self):
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        trg_btn  = QPushButton("⚡ Trigger")
        trg_menu = QMenu(trg_btn); trg_menu.setStyleSheet(MENU_STYLE)
        for cat, codes in TRIGGER_CATEGORIES.items():
            cm = trg_menu.addMenu(cat)
            for code in codes:
                name = OBJECT_TRIGGERS.get(code, code)
                a = cm.addAction(name)
                a.triggered.connect(
                    lambda checked=False, c=code, n=name:
                    self.state_machine.add_node(NODE_TRIGGER, c, n))
        trg_btn.setMenu(trg_menu)
        tb.addWidget(trg_btn)

        act_btn  = QPushButton("▶ Action")
        act_menu = QMenu(act_btn); act_menu.setStyleSheet(MENU_STYLE)
        for cat, items in ACTION_PALETTE.items():
            active = [(c, n) for c, n in items if c not in DEFERRED_ACTIONS]
            if not active:
                continue
            cm = act_menu.addMenu(cat)
            for code, name in active:
                a = cm.addAction(name)
                a.triggered.connect(
                    lambda checked=False, c=code, n=name:
                    self.state_machine.add_node(NODE_ACTION, c, n))
            if cat == "Debug":
                cm.addSeparator()
                legend_a = cm.addAction("📋 Copy Triggers & Actions as Text")
                legend_a.triggered.connect(self._copy_legend)
        act_btn.setMenu(act_menu)
        tb.addWidget(act_btn)

        obj_btn  = QPushButton("◈ Object")
        obj_menu = QMenu(obj_btn); obj_menu.setStyleSheet(MENU_STYLE)
        ph = obj_menu.addAction("(no scene loaded)"); ph.setEnabled(False)
        obj_btn.setMenu(obj_menu)
        tb.addWidget(obj_btn)

        tb.addSeparator()

        self._grp_btn  = QPushButton("⊞ Groups")
        self._grp_menu = QMenu(self._grp_btn); self._grp_menu.setStyleSheet(MENU_STYLE)
        self._grp_btn.setMenu(self._grp_menu)
        self._grp_menu.aboutToShow.connect(self._rebuild_groups_menu)
        tb.addWidget(self._grp_btn)

        tb.addSeparator()

        self._snap_btn = QPushButton("⊹ Snap: ON")
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._snap_btn.clicked.connect(self._toggle_snap)
        tb.addWidget(self._snap_btn)

        tb.addSeparator()

        clr = QPushButton("✕ Clear")
        clr.clicked.connect(self._clear_current)
        tb.addWidget(clr)

    def _clear_current(self):
        self.state_machine.clear_current()
        self.inspector.clear()

    def _toggle_snap(self, checked: bool):
        self._snap_btn.setText("⊹ Snap: ON" if not checked else "⊹ Snap: OFF")
        stack = self.state_machine._stack
        for i in range(stack.count()):
            w = stack.widget(i)
            if isinstance(w, NodeCanvas):
                w._snap_enabled = not checked

    def _rebuild_groups_menu(self):
        self._grp_menu.clear()
        save_a = self._grp_menu.addAction("💾  Save Selection as Group…")
        save_a.triggered.connect(self._save_group)
        names = self.state_machine.group_names()
        if names:
            self._grp_menu.addSeparator()
            insert_sub = self._grp_menu.addMenu("Insert Group")
            insert_sub.setStyleSheet(MENU_STYLE)
            delete_sub = self._grp_menu.addMenu("Delete Group")
            delete_sub.setStyleSheet(MENU_STYLE)
            for name in names:
                ia = insert_sub.addAction(name)
                ia.triggered.connect(
                    lambda checked=False, n=name: self.state_machine.insert_group(n))
                da = delete_sub.addAction(name)
                da.triggered.connect(
                    lambda checked=False, n=name: self.state_machine.delete_group(n))
        else:
            self._grp_menu.addSeparator()
            ph = self._grp_menu.addAction("(no groups saved)")
            ph.setEnabled(False)

    def _save_group(self):
        name, ok = QInputDialog.getText(
            self, "Save Node Group", "Group name:", text="MyGroup")
        if not ok or not name.strip():
            return
        if not self.state_machine.save_group(name.strip()):
            QMessageBox.warning(self, "Save Group",
                "No nodes selected. Select nodes first.")

    def _copy_legend(self):
        QApplication.clipboard().setText(build_legend_text())
        self.state_machine.current_canvas()._show_toast("📋 Full legend copied to clipboard")


# ─────────────────────────────────────────────────────────────
#  CONVERSION FUNCTIONS
# ─────────────────────────────────────────────────────────────

def behaviors_to_graph(behaviors: list, canvas: NodeCanvas):
    canvas.clear_canvas()

    TRIGGER_X      = -600
    ACTION_START_X = -360
    NODE_X_STEP    =  220
    NODE_Y_STEP    =  160

    scene = canvas._scene

    def place_chain(actions, x, y):
        from models import BehaviorAction
        first_node = None
        prev_node  = None

        for action in actions:
            display = ACTION_NAMES.get(action.action_type, action.action_type)
            node    = NodeItem(NODE_ACTION, action.action_type, display, x, y)

            for field_name, _lbl, wtype, _extra in get_fields(NODE_ACTION, action.action_type):
                val = getattr(action, field_name, None)
                if val is not None:
                    node.params[field_name] = val

            node.update_summary()
            scene.addItem(node)

            if prev_node and prev_node.out_port and node.in_port:
                scene.addItem(EdgeItem(prev_node.out_port, node.in_port))

            if node.is_branch:
                true_acts  = [BehaviorAction.from_dict(a) if isinstance(a, dict) else a
                              for a in action.true_actions]
                false_acts = [BehaviorAction.from_dict(a) if isinstance(a, dict) else a
                              for a in action.false_actions]
                if true_acts:
                    fn = place_chain(true_acts, x + NODE_X_STEP, y - 70)
                    if fn and node.true_port and fn.in_port:
                        scene.addItem(EdgeItem(node.true_port, fn.in_port))
                if false_acts:
                    fn = place_chain(false_acts, x + NODE_X_STEP, y + 70)
                    if fn and node.false_port and fn.in_port:
                        scene.addItem(EdgeItem(node.false_port, fn.in_port))

            if node.is_loop:
                loop_acts = [BehaviorAction.from_dict(a) if isinstance(a, dict) else a
                             for a in action.sub_actions]
                if loop_acts and node.loop_port:
                    fn = place_chain(loop_acts, x + NODE_X_STEP, y - 35)
                    if fn and fn.in_port:
                        scene.addItem(EdgeItem(node.loop_port, fn.in_port))

            if first_node is None:
                first_node = node
            prev_node = node
            x += NODE_X_STEP

        return first_node

    for i, behavior in enumerate(behaviors):
        y       = i * NODE_Y_STEP
        display = OBJECT_TRIGGERS.get(behavior.trigger, behavior.trigger)

        tnode = NodeItem(NODE_TRIGGER, behavior.trigger, display, TRIGGER_X, y)
        if behavior.button:
            tnode.params["button"] = behavior.button
        if behavior.frame_count:
            tnode.params["interval"] = behavior.frame_count
        if behavior.input_action_name:
            tnode.params["input_action_name"] = behavior.input_action_name
        if behavior.bool_var:
            tnode.params["signal_name"] = behavior.bool_var
        # New trigger params
        if behavior.timer_var:
            tnode.params["timer_var"] = behavior.timer_var
        if behavior.threshold_var:
            tnode.params["threshold_var"]     = behavior.threshold_var
            tnode.params["threshold_value"]   = behavior.threshold_value
            tnode.params["threshold_compare"] = behavior.threshold_compare
            tnode.params["threshold_repeat"]  = behavior.threshold_repeat
        if behavior.path_name:
            tnode.params["path_name"] = behavior.path_name
        if behavior.ani_trigger_object:
            tnode.params["ani_trigger_object"] = behavior.ani_trigger_object
            tnode.params["ani_trigger_frame"]  = behavior.ani_trigger_frame
        tnode.update_summary()
        scene.addItem(tnode)

        if behavior.actions:
            first = place_chain(behavior.actions, ACTION_START_X, y)
            if first and tnode.out_port and first.in_port:
                scene.addItem(EdgeItem(tnode.out_port, first.in_port))


def graph_to_behaviors(canvas: NodeCanvas) -> list:
    from models import Behavior, BehaviorAction

    def next_node(port):
        if not port or not port.edges:
            return None
        return port.edges[0].dst.node

    def collect_chain(first_node):
        actions = []
        node = first_node

        while node is not None:
            action = BehaviorAction(action_type=node.code)

            for field_name, _lbl, wtype, _extra in get_fields(NODE_ACTION, node.code):
                if field_name in node.params:
                    setattr(action, field_name, node.params[field_name])

            if node.is_branch:
                true_first  = next_node(node.true_port)
                false_first = next_node(node.false_port)
                action.true_actions  = [a.to_dict() for a in collect_chain(true_first)]  if true_first  else []
                action.false_actions = [a.to_dict() for a in collect_chain(false_first)] if false_first else []
                actions.append(action)
                break

            if node.is_loop:
                loop_first = next_node(node.loop_port)
                action.sub_actions = [a.to_dict() for a in collect_chain(loop_first)] if loop_first else []
                actions.append(action)
                node = next_node(node.out_port)
                continue

            actions.append(action)
            node = next_node(node.out_port)

        return actions

    trigger_nodes = [
        item for item in canvas._scene.items()
        if isinstance(item, NodeItem) and item.node_type == NODE_TRIGGER
    ]
    trigger_nodes.sort(key=lambda n: n.pos().y())

    behaviors = []
    for tnode in trigger_nodes:
        b = Behavior(trigger=tnode.code)
        if "button" in tnode.params:
            b.button = tnode.params["button"]
        if "interval" in tnode.params:
            b.frame_count = tnode.params["interval"]
        if "input_action_name" in tnode.params:
            b.input_action_name = tnode.params["input_action_name"]
        if "signal_name" in tnode.params:
            b.bool_var = tnode.params["signal_name"]
        # New trigger params
        if "timer_var" in tnode.params:
            b.timer_var = tnode.params["timer_var"]
        if "threshold_var" in tnode.params:
            b.threshold_var     = tnode.params["threshold_var"]
            b.threshold_value   = tnode.params.get("threshold_value", "")
            b.threshold_compare = tnode.params.get("threshold_compare", ">=")
            b.threshold_repeat  = tnode.params.get("threshold_repeat", False)
        if "path_name" in tnode.params:
            b.path_name = tnode.params["path_name"]
        if "ani_trigger_object" in tnode.params:
            b.ani_trigger_object = tnode.params["ani_trigger_object"]
            b.ani_trigger_frame  = tnode.params.get("ani_trigger_frame", 0)

        first = next_node(tnode.out_port)
        if first:
            b.actions = collect_chain(first)

        behaviors.append(b)

    return behaviors


# ─────────────────────────────────────────────────────────────
#  BEHAVIOR GRAPH DIALOG
# ─────────────────────────────────────────────────────────────

class BehaviorGraphDialog(QDialog):
    def __init__(self, obj, parent=None, scene=None, project=None):
        super().__init__(parent)
        self._obj = obj
        self.setWindowTitle(f"Node Graph — {obj.name}")
        self.resize(1280, 800)
        self.setStyleSheet("""
            QDialog { background: #0f0f12; }
            QPushButton {
                background: #26263a; color: #e8e6f0;
                border: 1px solid #2e2e42; padding: 6px 20px;
                border-radius: 4px; font: 11px 'Segoe UI';
            }
            QPushButton:hover { background: #2e2e42; border-color: #7c6aff; }
            QPushButton:pressed { background: #1e1e28; }
        """)

        # ── Build scene object list from placed objects ─────────
        scene_objects = []
        if scene is not None and project is not None:
            seen = set()
            for inst in scene.placed_objects:
                od = project.get_object_def(inst.object_def_id)
                if od and od.id not in seen:
                    seen.add(od.id)
                    scene_objects.append((od.id, od.name))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── State machine + inspector ──────────────────────────
        self._state_machine = StateMachineWidget()
        self._inspector     = Inspector(scene_objects=scene_objects, project=project)

        # ── Load saved node groups from the object if present ──
        saved_groups = getattr(obj, "node_groups", None)
        if isinstance(saved_groups, dict):
            self._state_machine.set_groups(saved_groups)

        # ── Toolbar ───────────────────────────────────────────────
        tb = QToolBar()
        tb.setMovable(False)
        tb.setStyleSheet("""
            QToolBar { background: #16161c; border-bottom: 1px solid #2e2e42;
                    padding: 4px 10px; spacing: 6px; }
            QPushButton { background: #26263a; color: #e8e6f0;
                border: 1px solid #2e2e42; padding: 5px 14px;
                border-radius: 4px; font: 11px 'Segoe UI'; }
            QPushButton:hover { background: #2e2e42; border-color: #7c6aff; }
            QPushButton:pressed { background: #1e1e28; }
            QPushButton::menu-indicator { image: none; }
        """)

        trg_btn  = QPushButton("⚡ Trigger")
        trg_menu = QMenu(trg_btn); trg_menu.setStyleSheet(MENU_STYLE)
        for cat, codes in TRIGGER_CATEGORIES.items():
            cm = trg_menu.addMenu(cat)
            for code in codes:
                name = OBJECT_TRIGGERS.get(code, code)
                a = cm.addAction(name)
                a.triggered.connect(
                    lambda checked=False, c=code, n=name:
                    self._state_machine.add_node(NODE_TRIGGER, c, n))
        trg_btn.setMenu(trg_menu)
        tb.addWidget(trg_btn)

        act_btn  = QPushButton("▶ Action")
        act_menu = QMenu(act_btn); act_menu.setStyleSheet(MENU_STYLE)
        for cat, items in ACTION_PALETTE.items():
            active = [(c, n) for c, n in items if c not in DEFERRED_ACTIONS]
            if not active:
                continue
            cm = act_menu.addMenu(cat)
            for code, name in active:
                a = cm.addAction(name)
                a.triggered.connect(
                    lambda checked=False, c=code, n=name:
                    self._state_machine.add_node(NODE_ACTION, c, n))
            if cat == "Debug":
                cm.addSeparator()
                legend_a = cm.addAction("📋 Copy Triggers & Actions as Text")
                legend_a.triggered.connect(self._copy_legend)
        act_btn.setMenu(act_menu)
        tb.addWidget(act_btn)

        tb.addSeparator()

        self._grp_btn  = QPushButton("⊞ Groups")
        self._grp_menu = QMenu(self._grp_btn); self._grp_menu.setStyleSheet(MENU_STYLE)
        self._grp_btn.setMenu(self._grp_menu)
        self._grp_menu.aboutToShow.connect(self._rebuild_groups_menu)
        tb.addWidget(self._grp_btn)

        tb.addSeparator()

        # ── Snap toggle ────────────────────────────────────────
        self._snap_btn = QPushButton("⊹ Snap: ON")
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._snap_btn.setStyleSheet("""
            QPushButton { background: #26263a; color: #7c6aff;
                border: 1px solid #7c6aff44; padding: 5px 14px;
                border-radius: 4px; font: 11px 'Segoe UI'; }
            QPushButton:hover { background: #2e2e42; border-color: #7c6aff; }
            QPushButton:checked { background: #1e1e28; color: #4a4860;
                border-color: #2e2e42; }
        """)
        self._snap_btn.clicked.connect(self._toggle_snap)
        tb.addWidget(self._snap_btn)

        tb.addSeparator()

        clr = QPushButton("✕ Clear")
        clr.clicked.connect(self._state_machine.clear_current)
        tb.addWidget(clr)

        root.addWidget(tb)

        # ── Splitter ───────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._state_machine)
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStyleSheet("QSplitter::handle { background: #2e2e42; width: 1px; }")
        root.addWidget(splitter, stretch=1)

        # ── Bottom bar ─────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background: #16161c; border-top: 1px solid #2e2e42;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(8)
        bl.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        bl.addWidget(cancel_btn)
        bl.addWidget(ok_btn)
        root.addWidget(bar)

        # ── Load the object's behaviors into the graph ─────────
        canvas = self._state_machine.current_canvas()
        behaviors_to_graph(obj.behaviors, canvas)

    def _on_ok(self):
        canvas = self._state_machine.current_canvas()
        self._obj.behaviors = graph_to_behaviors(canvas)
        self._obj.node_groups = self._state_machine.get_groups()
        self.accept()

    def _copy_legend(self):
        QApplication.clipboard().setText(build_legend_text())
        canvas = self._state_machine.current_canvas()
        canvas._show_toast("📋 Full legend copied to clipboard")

    def _toggle_snap(self, checked: bool):
        label = "⊹ Snap: ON" if not checked else "⊹ Snap: OFF"
        self._snap_btn.setText(label)
        stack = self._state_machine._stack
        for i in range(stack.count()):
            w = stack.widget(i)
            if isinstance(w, NodeCanvas):
                w._snap_enabled = not checked

    def _rebuild_groups_menu(self):
        self._grp_menu.clear()
        save_a = self._grp_menu.addAction("💾  Save Selection as Group…")
        save_a.triggered.connect(self._save_group)

        names = self._state_machine.group_names()
        if names:
            self._grp_menu.addSeparator()
            insert_sub = self._grp_menu.addMenu("Insert Group")
            insert_sub.setStyleSheet(MENU_STYLE)
            delete_sub = self._grp_menu.addMenu("Delete Group")
            delete_sub.setStyleSheet(MENU_STYLE)
            for name in names:
                ia = insert_sub.addAction(name)
                ia.triggered.connect(
                    lambda checked=False, n=name: self._state_machine.insert_group(n))
                da = delete_sub.addAction(name)
                da.triggered.connect(
                    lambda checked=False, n=name: self._delete_group(n))
        else:
            self._grp_menu.addSeparator()
            ph = self._grp_menu.addAction("(no groups saved)")
            ph.setEnabled(False)

    def _save_group(self):
        name, ok = QInputDialog.getText(
            self, "Save Node Group", "Group name:", text="MyGroup")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not self._state_machine.save_group(name):
            QMessageBox.warning(self, "Save Group",
                "No nodes selected. Select one or more nodes before saving a group.")

    def _delete_group(self, name: str):
        reply = QMessageBox.question(
            self, "Delete Group",
            f'Delete group "{name}"?',
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._state_machine.delete_group(name)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
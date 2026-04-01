# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — LPP Exporter
Generates a multi-file Lua project using the LPP-Vita API.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from models import (
    Project,
    Scene,
    Behavior,
    BehaviorAction,
    effective_placed_behaviors,
    get_behavior_plugin_value,
)


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _lua_str(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'

def _lua_bool(b: bool) -> str:
    return "true" if b else "false"

def _safe_name(s: str) -> str:
    out = ""
    for c in s:
        out += c if c.isalnum() or c == "_" else "_"
    if out and out[0].isdigit():
        out = "_" + out
    return out or "obj"


def _behavior_field(container: Any, code: str, field_name: str, default: Any = None) -> Any:
    return get_behavior_plugin_value(container, code, field_name, default)


def _app_ui_trigger_condition(behavior: Behavior) -> str | None:
    request_id = str(_behavior_field(behavior, behavior.trigger, "request_id", "") or "")
    helpers = {
        "on_keyboard_submit": "app_ui_keyboard_submitted",
        "on_keyboard_cancel": "app_ui_keyboard_canceled",
        "on_confirm_yes": "app_ui_confirmed_yes",
        "on_confirm_no": "app_ui_confirmed_no",
    }
    helper = helpers.get(behavior.trigger)
    if not helper:
        return None
    return f"{helper}({_lua_str(request_id)})"

def _asset_filename(path: str) -> str:
    return Path(path).name if path else ""


def _plugin_registry(project: Project | None):
    return getattr(project, "plugin_registry", None) if project else None


def _active_export_scene(project: Project | None):
    return getattr(project, "_active_export_scene", None) if project else None


def _placed_var_name(placed_object) -> str:
    return f"obj_{_safe_name(getattr(placed_object, 'instance_id', '') or 'placed')}"


def _first_animation_slot(obj_def, project: Project | None):
    if not obj_def or getattr(obj_def, "behavior_type", "") != "Animation" or not project:
        return None
    for slot in getattr(obj_def, "ani_slots", []) or []:
        slot_name = str(slot.get("name", "")).strip()
        ani_id = str(slot.get("ani_file_id", "")).strip()
        if not slot_name or not ani_id:
            continue
        ani_export = project.get_animation_export(ani_id)
        if ani_export:
            return slot_name, ani_id, ani_export
    return None


def _regular_frame_image_name(obj_def, project: Project | None, frame_index: int = 0) -> str:
    if not obj_def or not project:
        return ""
    frames = getattr(obj_def, "frames", []) or []
    if frame_index < 0 or frame_index >= len(frames):
        return ""
    image_id = getattr(frames[frame_index], "image_id", "") or ""
    img = project.get_image(image_id) if image_id else None
    return _asset_filename(img.path) if (img and img.path) else ""


def _classify_3d_billboard(obj_def, project: Project | None) -> tuple[str | None, str]:
    """Return (kind, detail_or_reason) for a 3D billboard-capable object."""
    if not obj_def:
        return None, "missing object definition"

    btype = getattr(obj_def, "behavior_type", "") or "default"
    if btype in ("GUI_Panel", "GUI_Label", "GUI_Button", "Camera"):
        return None, f"{btype} objects cannot render as 3D billboards"
    if btype == "LayerAnimation":
        return None, "LayerAnimation objects are not yet supported as 3D billboards"
    if btype == "Animation":
        slot = _first_animation_slot(obj_def, project)
        if slot is None:
            return None, "Animation objects need at least one valid animation slot"
        return "animation", slot[0]

    frames = getattr(obj_def, "frames", []) or []
    if not frames:
        return None, "object has no sprite frames"
    if not _regular_frame_image_name(obj_def, project, 0):
        return None, "object has no valid first-frame image"
    if len(frames) > 1:
        return "frame_anim", ""
    return "static", ""


def _scene_target_refs(target_id: str, project: Project | None) -> list[tuple[Any, Any]]:
    if not target_id or not project:
        return []
    scene = _active_export_scene(project)
    if scene is None:
        return []

    instance_hits: list[tuple[Any, Any]] = []
    def_hits: list[tuple[Any, Any]] = []
    for po in getattr(scene, "placed_objects", []):
        od = project.get_object_def(po.object_def_id)
        if od is None:
            continue
        if po.instance_id == target_id:
            instance_hits.append((po, od))
        if po.object_def_id == target_id:
            def_hits.append((po, od))
    if instance_hits:
        return instance_hits
    return def_hits


def _scene_target_vars(target_id: str, project: Project | None) -> list[str]:
    return [_placed_var_name(po) for po, _od in _scene_target_refs(target_id, project)]


def _scene_target_handles(target_id: str, project: Project | None) -> list[str]:
    return [po.instance_id for po, _od in _scene_target_refs(target_id, project)]


def _set_active_export_scene(project: Project | None, scene: Scene | None) -> None:
    if project is not None:
        setattr(project, "_active_export_scene", scene)


def _is_3d_export_context(project: Project | None) -> bool:
    scene = _active_export_scene(project) if project is not None else None
    return bool(scene and getattr(scene, "scene_type", "2d") == "3d")


def _target_vars_for_action(action: BehaviorAction, project: Project | None, obj_var: str | None = None) -> list[str]:
    if project:
        if action.instance_id:
            vars_for_instance = _scene_target_vars(action.instance_id, project)
            if vars_for_instance:
                return vars_for_instance
        if action.object_def_id:
            vars_for_def = _scene_target_vars(action.object_def_id, project)
            if vars_for_def:
                return vars_for_def
    return [obj_var] if obj_var else []


def _target_handles_for_action(action: BehaviorAction, project: Project | None, obj_var: str | None = None) -> list[str]:
    if project:
        if action.instance_id:
            handles_for_instance = _scene_target_handles(action.instance_id, project)
            if handles_for_instance:
                return [_lua_str(handle) for handle in handles_for_instance]
        if action.object_def_id:
            handles_for_def = _scene_target_handles(action.object_def_id, project)
            if handles_for_def:
                return [_lua_str(handle) for handle in handles_for_def]
    if obj_var:
        return [f'prim.handle_from_var({_lua_str(obj_var)})']
    return []


def _append_per_target(lines: list[str], target_vars: list[str], emit) -> None:
    for target_var in target_vars:
        for line in emit(target_var):
            lines.append(line)


def _emit_3d_actor_call(
    lines: list[str],
    action: BehaviorAction,
    project: Project | None,
    obj_var: str | None,
    emit_for_target,
    missing_comment: str,
) -> None:
    target_ids: list[str] = []
    if project:
        if action.instance_id:
            target_ids = _scene_target_handles(action.instance_id, project)
        elif action.object_def_id:
            target_ids = _scene_target_handles(action.object_def_id, project)
    if target_ids:
        for target_id in target_ids:
            for line in emit_for_target(_lua_str(target_id)):
                lines.append(line)
        return
    if obj_var:
        lines.append("do")
        lines.append(f"    local _actor3d_id = actor3d_id_from_var({_lua_str(obj_var)})")
        lines.append("    if _actor3d_id then")
        for line in emit_for_target("_actor3d_id"):
            lines.append(f"        {line}")
        lines.append("    end")
        lines.append("end")
        return
    lines.append(missing_comment)


def _plugin_scene_hook_lines(scene: Scene, project: Project, hook_name: str) -> list[str]:
    registry = _plugin_registry(project)
    if not registry:
        return []
    lines: list[str] = []
    for component, descriptor, _plugin_id in registry.iter_scene_plugin_components(scene):
        hook = descriptor.get(hook_name)
        if callable(hook):
            for line in hook(component.config, project) or []:
                lines.append(str(line))
    return lines


def _emit_plugin_trigger_dispatch(out: list[str], beh: Behavior, obj_var: str | None, project: Project, obj_def=None, indent: str = "") -> bool:
    registry = _plugin_registry(project)
    if not registry:
        return False
    descriptor = registry.get_trigger_descriptor(beh.trigger)
    if not descriptor:
        return False
    condition = str(descriptor["lua_condition"](beh, obj_var, project) or "").strip()
    if not condition:
        return True
    out.append(f"{indent}if {condition} then")
    for action in beh.actions:
        for line in _action_to_lua_inline(action, obj_var, project, obj_def=obj_def):
            out.append(f"{indent}    {line}")
    out.append(f"{indent}end")
    return True


def _object_has_collision_boxes(obj_def) -> bool:
    if not obj_def:
        return False
    if any(frame_boxes for frame_boxes in getattr(obj_def, "collision_boxes", [])):
        return True
    return any(
        frame_boxes
        for frames in getattr(obj_def, "ani_collision_boxes", {}).values()
        for frame_boxes in frames
    )


def _object_collision_slots(obj_def) -> dict[str, list]:
    if not obj_def:
        return {}
    if getattr(obj_def, "behavior_type", "") != "Animation":
        return {"": getattr(obj_def, "collision_boxes", [])}

    slots = {}
    for slot in getattr(obj_def, "ani_slots", []):
        slot_name = str(slot.get("name", "")).strip()
        if not slot_name:
            continue
        slots[slot_name] = getattr(obj_def, "ani_collision_boxes", {}).get(slot_name, [])
    for slot_name, frames in getattr(obj_def, "ani_collision_boxes", {}).items():
        slot_name = str(slot_name).strip()
        if slot_name and slot_name not in slots:
            slots[slot_name] = frames
    if not slots and getattr(obj_def, "collision_boxes", []):
        default_name = ""
        if getattr(obj_def, "ani_slots", []):
            default_name = str(obj_def.ani_slots[0].get("name", "")).strip()
        slots[default_name] = getattr(obj_def, "collision_boxes", [])
    return slots


def _current_collision_state_expr(obj_var: str | None, obj_def) -> tuple[str, str, str]:
    if not obj_var or obj_def is None:
        return '""', "0", '""'
    frame_expr = f"{obj_var}_ani_frame" if getattr(obj_def, "behavior_type", "") == "Animation" else "0"
    slot_expr = f"{obj_var}_ani_slot_name" if getattr(obj_def, "behavior_type", "") == "Animation" else '""'
    return _lua_str(getattr(obj_def, "id", "") or ""), frame_expr, slot_expr

def _button_constant(button: str) -> str:
    return {
        "cross":      "SCE_CTRL_CROSS",
        "circle":     "SCE_CTRL_CIRCLE",
        "square":     "SCE_CTRL_SQUARE",
        "triangle":   "SCE_CTRL_TRIANGLE",
        "dpad_up":    "SCE_CTRL_UP",
        "dpad_down":  "SCE_CTRL_DOWN",
        "dpad_left":  "SCE_CTRL_LEFT",
        "dpad_right": "SCE_CTRL_RIGHT",
        "l":          "SCE_CTRL_LTRIGGER",
        "r":          "SCE_CTRL_RTRIGGER",
        "start":      "SCE_CTRL_START",
        "select":     "SCE_CTRL_SELECT",
    }.get(button, "SCE_CTRL_CROSS")

_STICK_VIRTUAL_BUTTONS = {
    "left_stick_up":    ("left",  "up"),
    "left_stick_down":  ("left",  "down"),
    "left_stick_left":  ("left",  "left"),
    "left_stick_right": ("left",  "right"),
    "right_stick_up":   ("right", "up"),
    "right_stick_down": ("right", "down"),
    "right_stick_left": ("right", "left"),
    "right_stick_right":("right", "right"),
}

def _is_stick_virtual_button(button: str) -> bool:
    return button in _STICK_VIRTUAL_BUTTONS

def _stick_button_to_parts(button: str):
    """Return (stick, direction) for a virtual stick button name, or (None, None)."""
    return _STICK_VIRTUAL_BUTTONS.get(button, (None, None))

def _event_check(event: str) -> str:
    return {
        "pressed":  "controls_pressed",
        "released": "controls_released",
        "held":     "controls_held",
    }.get(event, "controls_pressed")


# Maps a movement_input mode + cardinal direction to the correct Lua boolean
# expression for use in an `if ... then` guard inside a movement generator.
# direction must be one of: "up" | "down" | "left" | "right"
_DPAD_CONST = {
    "up":    "SCE_CTRL_UP",
    "down":  "SCE_CTRL_DOWN",
    "left":  "SCE_CTRL_LEFT",
    "right": "SCE_CTRL_RIGHT",
}

def _movement_input_cond(movement_input: str, direction: str, deadzone: int = 32) -> str:
    """Return the Lua condition expression for one cardinal direction given a movement_input mode.

    movement_input values:
      "dpad"                  – digital pad only (legacy / default)
      "left_stick"            – left analog stick only
      "right_stick"           – right analog stick only
      "dpad_and_left_stick"   – either d-pad OR left stick
      "dpad_and_right_stick"  – either d-pad OR right stick
    """
    dpad_expr  = f"controls_held({_DPAD_CONST[direction]})"
    left_expr  = f"stick_dir_held('left', '{direction}', {deadzone})"
    right_expr = f"stick_dir_held('right', '{direction}', {deadzone})"

    if movement_input == "left_stick":
        return left_expr
    elif movement_input == "right_stick":
        return right_expr
    elif movement_input == "dpad_and_left_stick":
        return f"({dpad_expr} or {left_expr})"
    elif movement_input == "dpad_and_right_stick":
        return f"({dpad_expr} or {right_expr})"
    else:  # "dpad" or any unrecognised value — safe default preserving old behaviour
        return dpad_expr

def _color(r: int, g: int, b: int, a: int = 255) -> str:
    return f"Color.new({r}, {g}, {b}, {a})"

def _parse_hex_color(hex_color: str, alpha: int = 255) -> str:
    hx = hex_color.lstrip('#')
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return _color(r, g, b, alpha)


# ─────────────────────────────────────────────────────────────
#  TILE CHUNK BAKER
# ─────────────────────────────────────────────────────────────

CHUNK_SIZE = 512

def bake_tile_chunks(project: Project, build_dir) -> list:
    import math
    from PIL import Image

    out_dir = Path(build_dir) / "assets" / "tilechunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    for si, scene in enumerate(project.scenes):
        for comp in scene.components:
            if comp.component_type != "TileLayer":
                continue
            ts_id = comp.config.get("tileset_id")
            if not ts_id:
                continue
            ts = project.get_tileset(ts_id)
            if ts is None or not ts.path or ts.columns == 0 or ts.rows == 0:
                continue

            tile_size = ts.tile_size
            map_w     = comp.config.get("map_width",  30)
            map_h     = comp.config.get("map_height", 17)
            tiles     = comp.config.get("tiles", [])

            try:
                tileset_img = Image.open(ts.path).convert("RGBA")
            except Exception as e:
                print(f"bake_tile_chunks: could not load {ts.path}: {e}")
                continue

            src_tile_w = tileset_img.width  // ts.columns
            src_tile_h = tileset_img.height // ts.rows

            world_w   = map_w * tile_size
            world_h   = map_h * tile_size
            world_img = Image.new("RGBA", (world_w, world_h), (0, 0, 0, 0))

            for row in range(map_h):
                for col in range(map_w):
                    flat = row * map_w + col
                    if flat >= len(tiles):
                        continue
                    tile_idx = tiles[flat]
                    if tile_idx < 0:
                        continue
                    tc        = tile_idx % ts.columns
                    tr        = tile_idx // ts.columns
                    src_x     = tc * src_tile_w
                    src_y     = tr * src_tile_h
                    tile_crop = tileset_img.crop((src_x, src_y, src_x + src_tile_w, src_y + src_tile_h))
                    if src_tile_w != tile_size or src_tile_h != tile_size:
                        tile_crop = tile_crop.resize((tile_size, tile_size), Image.NEAREST)
                    world_img.paste(tile_crop, (col * tile_size, row * tile_size))

            chunks_x = math.ceil(world_w / CHUNK_SIZE)
            chunks_y = math.ceil(world_h / CHUNK_SIZE)
            safe_id  = comp.id.replace("-", "_")

            for cy in range(chunks_y):
                for cx in range(chunks_x):
                    x0    = cx * CHUNK_SIZE
                    y0    = cy * CHUNK_SIZE
                    x1    = min(x0 + CHUNK_SIZE, world_w)
                    y1    = min(y0 + CHUNK_SIZE, world_h)
                    chunk = world_img.crop((x0, y0, x1, y1))
                    fname = f"tl_{safe_id}_{cx}_{cy}.png"
                    chunk.save(out_dir / fname)
                    written.append((si, comp.id, cx, cy, fname))

    return written


# ─────────────────────────────────────────────────────────────
#  LIB FILE GENERATORS
# ─────────────────────────────────────────────────────────────

def _make_controls_lib(dpad_mirror_stick: str = "none", dpad_mirror_deadzone: int = 32) -> str:
    lines = [
        "-- lib/controls.lua",
        "local _pad_old = 0",
        "local _pad_cur = 0",
        "",
        "-- analog stick raw state (0-255, centered at 128)",
        "local _lx, _ly = 128, 128",
        "local _rx, _ry = 128, 128",
        "",
        "-- analog stick virtual directional booleans (current frame)",
        "local _ls_up,   _ls_down,  _ls_left,  _ls_right  = false, false, false, false",
        "local _rs_up,   _rs_down,  _rs_left,  _rs_right  = false, false, false, false",
        "",
        "-- analog stick virtual directional booleans (previous frame)",
        "local _ls_up_p, _ls_down_p, _ls_left_p, _ls_right_p = false, false, false, false",
        "local _rs_up_p, _rs_down_p, _rs_left_p, _rs_right_p = false, false, false, false",
        "",
        f"-- D-pad mirror settings (set from project GameData)",
        f'local _dpad_mirror_stick    = "{dpad_mirror_stick}"',
        f"local _dpad_mirror_deadzone = {dpad_mirror_deadzone}",
        "",
        "function controls_update()",
        "    _pad_old = _pad_cur",
        "    _pad_cur = Controls.read()",
        "",
        "    -- save previous analog directions before updating",
        "    _ls_up_p, _ls_down_p, _ls_left_p, _ls_right_p = _ls_up, _ls_down, _ls_left, _ls_right",
        "    _rs_up_p, _rs_down_p, _rs_left_p, _rs_right_p = _rs_up, _rs_down, _rs_left, _rs_right",
        "",
        "    -- read raw analog values (0-255, centered at 128)",
        "    _lx, _ly = Controls.readLeftAnalog()",
        "    _rx, _ry = Controls.readRightAnalog()",
        "    if _lx == nil then _lx = 128 end",
        "    if _ly == nil then _ly = 128 end",
        "    if _rx == nil then _rx = 128 end",
        "    if _ry == nil then _ry = 128 end",
        "",
        "    -- derive virtual directions from left stick",
        "    local _lxc = _lx - 128",
        "    local _lyc = _ly - 128",
        "    _ls_left  = _lxc <= -_dpad_mirror_deadzone",
        "    _ls_right = _lxc >=  _dpad_mirror_deadzone",
        "    _ls_up    = _lyc <= -_dpad_mirror_deadzone",
        "    _ls_down  = _lyc >=  _dpad_mirror_deadzone",
        "",
        "    -- derive virtual directions from right stick",
        "    local _rxc = _rx - 128",
        "    local _ryc = _ry - 128",
        "    _rs_left  = _rxc <= -_dpad_mirror_deadzone",
        "    _rs_right = _rxc >=  _dpad_mirror_deadzone",
        "    _rs_up    = _ryc <= -_dpad_mirror_deadzone",
        "    _rs_down  = _ryc >=  _dpad_mirror_deadzone",
        "end",
        "",
        "function controls_held(btn)",
        "    if Controls.check(_pad_cur, btn) then return true end",
        "    if _dpad_mirror_stick == 'none' then return false end",
        "    local _ms = _dpad_mirror_stick",
        "    if btn == SCE_CTRL_UP    then return _ms=='left' and _ls_up    or _ms=='right' and _rs_up    end",
        "    if btn == SCE_CTRL_DOWN  then return _ms=='left' and _ls_down  or _ms=='right' and _rs_down  end",
        "    if btn == SCE_CTRL_LEFT  then return _ms=='left' and _ls_left  or _ms=='right' and _rs_left  end",
        "    if btn == SCE_CTRL_RIGHT then return _ms=='left' and _ls_right or _ms=='right' and _rs_right end",
        "    return false",
        "end",
        "",
        "function controls_pressed(btn)",
        "    local _cur_dig = Controls.check(_pad_cur, btn)",
        "    local _old_dig = Controls.check(_pad_old, btn)",
        "    if _cur_dig and not _old_dig then return true end",
        "    if _dpad_mirror_stick == 'none' then return false end",
        "    local _ms = _dpad_mirror_stick",
        "    if btn == SCE_CTRL_UP then",
        "        local c = _ms=='left' and _ls_up or _ms=='right' and _rs_up",
        "        local p = _ms=='left' and _ls_up_p or _ms=='right' and _rs_up_p",
        "        return c and not p",
        "    end",
        "    if btn == SCE_CTRL_DOWN then",
        "        local c = _ms=='left' and _ls_down or _ms=='right' and _rs_down",
        "        local p = _ms=='left' and _ls_down_p or _ms=='right' and _rs_down_p",
        "        return c and not p",
        "    end",
        "    if btn == SCE_CTRL_LEFT then",
        "        local c = _ms=='left' and _ls_left or _ms=='right' and _rs_left",
        "        local p = _ms=='left' and _ls_left_p or _ms=='right' and _rs_left_p",
        "        return c and not p",
        "    end",
        "    if btn == SCE_CTRL_RIGHT then",
        "        local c = _ms=='left' and _ls_right or _ms=='right' and _rs_right",
        "        local p = _ms=='left' and _ls_right_p or _ms=='right' and _rs_right_p",
        "        return c and not p",
        "    end",
        "    return false",
        "end",
        "",
        "function controls_released(btn)",
        "    local _cur_dig = Controls.check(_pad_cur, btn)",
        "    local _old_dig = Controls.check(_pad_old, btn)",
        "    if not _cur_dig and _old_dig then return true end",
        "    if _dpad_mirror_stick == 'none' then return false end",
        "    local _ms = _dpad_mirror_stick",
        "    if btn == SCE_CTRL_UP then",
        "        local c = _ms=='left' and _ls_up or _ms=='right' and _rs_up",
        "        local p = _ms=='left' and _ls_up_p or _ms=='right' and _rs_up_p",
        "        return p and not c",
        "    end",
        "    if btn == SCE_CTRL_DOWN then",
        "        local c = _ms=='left' and _ls_down or _ms=='right' and _rs_down",
        "        local p = _ms=='left' and _ls_down_p or _ms=='right' and _rs_down_p",
        "        return p and not c",
        "    end",
        "    if btn == SCE_CTRL_LEFT then",
        "        local c = _ms=='left' and _ls_left or _ms=='right' and _rs_left",
        "        local p = _ms=='left' and _ls_left_p or _ms=='right' and _rs_left_p",
        "        return p and not c",
        "    end",
        "    if btn == SCE_CTRL_RIGHT then",
        "        local c = _ms=='left' and _ls_right or _ms=='right' and _rs_right",
        "        local p = _ms=='left' and _ls_right_p or _ms=='right' and _rs_right_p",
        "        return p and not c",
        "    end",
        "    return false",
        "end",
        "",
        "-- analog stick direction helpers",
        "-- deadzone: integer, applied after centering (raw - 128)",
        "-- stick: 'left' or 'right'",
        "-- dir: 'up', 'down', 'left', 'right'",
        "function stick_dir_held(stick, dir, deadzone)",
        "    local cx, cy",
        "    if stick == 'left' then",
        "        cx = _lx - 128",
        "        cy = _ly - 128",
        "    else",
        "        cx = _rx - 128",
        "        cy = _ry - 128",
        "    end",
        "    if dir == 'left'  then return cx <= -deadzone end",
        "    if dir == 'right' then return cx >=  deadzone end",
        "    if dir == 'up'    then return cy <= -deadzone end",
        "    if dir == 'down'  then return cy >=  deadzone end",
        "    return false",
        "end",
        "",
        "function stick_dir_pressed(stick, dir, deadzone)",
        "    local cur = stick_dir_held(stick, dir, deadzone)",
        "    local prev",
        "    if stick == 'left' then",
        "        if dir == 'up'    then prev = _ls_up_p",
        "        elseif dir == 'down'  then prev = _ls_down_p",
        "        elseif dir == 'left'  then prev = _ls_left_p",
        "        else                       prev = _ls_right_p end",
        "    else",
        "        if dir == 'up'    then prev = _rs_up_p",
        "        elseif dir == 'down'  then prev = _rs_down_p",
        "        elseif dir == 'left'  then prev = _rs_left_p",
        "        else                       prev = _rs_right_p end",
        "    end",
        "    return cur and not prev",
        "end",
        "",
        "function stick_dir_released(stick, dir, deadzone)",
        "    local cur = stick_dir_held(stick, dir, deadzone)",
        "    local prev",
        "    if stick == 'left' then",
        "        if dir == 'up'    then prev = _ls_up_p",
        "        elseif dir == 'down'  then prev = _ls_down_p",
        "        elseif dir == 'left'  then prev = _ls_left_p",
        "        else                       prev = _ls_right_p end",
        "    else",
        "        if dir == 'up'    then prev = _rs_up_p",
        "        elseif dir == 'down'  then prev = _rs_down_p",
        "        elseif dir == 'left'  then prev = _rs_left_p",
        "        else                       prev = _rs_right_p end",
        "    end",
        "    return prev and not cur",
        "end",
        "",
        "-- touch state (single-finger front touchscreen only)",
        "_touch_x     = 0",
        "_touch_y     = 0",
        "_touch_down  = false",
        "_touch_began = false",
        "_touch_ended = false",
        "local _touch_prev = false",
        "",
        "-- swipe gesture state (valid for one frame after release)",
        "_touch_start_x   = 0",
        "_touch_start_y   = 0",
        "_touch_end_x     = 0",
        "_touch_end_y     = 0",
        "_touch_swipe     = false",
        "_touch_swipe_dir = \"\"",
        "_touch_swipe_dx  = 0",
        "_touch_swipe_dy  = 0",
        "_touch_swipe_dist = 0",
        "_touch_start_world_x = 0",
        "_touch_start_world_y = 0",
        "",
        "function touch_update()",
        "    -- reset swipe result at start of every frame",
        "    _touch_swipe     = false",
        "    _touch_swipe_dir = \"\"",
        "    _touch_swipe_dx  = 0",
        "    _touch_swipe_dy  = 0",
        "    _touch_swipe_dist = 0",
        "    local x1, y1 = Controls.readTouch()",
        "    _touch_prev = _touch_down",
        "    if x1 ~= nil and x1 ~= 0 and y1 ~= nil and y1 ~= 0 then",
        "        _touch_down = true",
        "        _touch_x = x1",
        "        _touch_y = y1",
        "    else",
        "        _touch_down = false",
        "    end",
        "    _touch_began = _touch_down and not _touch_prev",
        "    _touch_ended = not _touch_down and _touch_prev",
        "    if _touch_began then",
        "        _touch_start_x = _touch_x",
        "        _touch_start_y = _touch_y",
        "        local wx, wy = screen_to_world(_touch_start_x, _touch_start_y)",
        "        _touch_start_world_x = wx",
        "        _touch_start_world_y = wy",
        "    end",
        "    if _touch_ended then",
        "        _touch_end_x = _touch_x",
        "        _touch_end_y = _touch_y",
        "        local dx = _touch_end_x - _touch_start_x",
        "        local dy = _touch_end_y - _touch_start_y",
        "        local dist = math.sqrt(dx * dx + dy * dy)",
        "        if dist > 0 then",
        "            _touch_swipe_dx   = dx",
        "            _touch_swipe_dy   = dy",
        "            _touch_swipe_dist = dist",
        "            if math.abs(dx) >= math.abs(dy) then",
        "                _touch_swipe_dir = dx < 0 and \"left\" or \"right\"",
        "            else",
        "                _touch_swipe_dir = dy < 0 and \"up\" or \"down\"",
        "            end",
        "            _touch_swipe = true",
        "        end",
        "    end",
        "end",
        "",
        "function screen_to_world(sx, sy)",
        "    local z = camera.zoom",
        "    return (sx - 480) / z + camera.x, (sy - 272) / z + camera.y",
        "end",
        "",
        "function touch_in_rect(wx, wy, ww, wh)",
        "    if not _touch_began then return false end",
        "    local twx, twy = screen_to_world(_touch_x, _touch_y)",
        "    return twx >= wx and twx < wx + ww and twy >= wy and twy < wy + wh",
        "end",
        "",
        "function touch_swipe_matches(dir, min_dist)",
        "    if not _touch_swipe then return false end",
        "    if _touch_swipe_dist < min_dist then return false end",
        "    if dir == \"any\" then return true end",
        "    return _touch_swipe_dir == dir",
        "end",
        "",
        "function touch_start_in_rect(wx, wy, ww, wh)",
        "    return _touch_start_world_x >= wx and _touch_start_world_x < wx + ww",
        "       and _touch_start_world_y >= wy and _touch_start_world_y < wy + wh",
        "end",
    ]
    return "\n".join(lines)


def _make_tween_lib() -> str:
    lines = [
        "-- lib/tween.lua",
        "tweens = {}",
        "",
        "local function ease_linear(t) return t end",
        "local function ease_in(t) return t * t end",
        "local function ease_out(t) return 1 - (1 - t) * (1 - t) end",
        "local function ease_in_out(t)",
        "    if t < 0.5 then return 2 * t * t",
        "    else return 1 - 2 * (1 - t) * (1 - t) end",
        "end",
        "",
        "function emit_signal(name)",
        "    _signals[name] = (_signals[name] or 0) + 1",
        "end",
        "",
        "function signal_fired(name)",
        "    return (_signals[name] or 0) > 0",
        "end",
        "",
        "local easing_funcs = {",
        "    linear      = ease_linear,",
        "    ease_in     = ease_in,",
        "    ease_out    = ease_out,",
        "    ease_in_out = ease_in_out,",
        "}",
        "",
        "function tween_add(id, target_table, key, target_value, duration_frames, easing)",
        "    tweens[id] = {",
        "        target      = target_table,",
        "        key         = key,",
        "        start_value = target_table[key],",
        "        end_value   = target_value,",
        "        duration    = duration_frames,",
        "        elapsed     = 0,",
        "        easing      = easing_funcs[easing] or ease_linear,",
        "    }",
        "end",
        "",
        "function tween_update()",
        "    for id, tw in pairs(tweens) do",
        "        tw.elapsed = tw.elapsed + 1",
        "        local t = tw.elapsed / tw.duration",
        "        if t >= 1 then",
        "            tw.target[tw.key] = tw.end_value",
        "            tweens[id] = nil",
        "        else",
        "            local eased = tw.easing(t)",
        "            tw.target[tw.key] = tw.start_value + (tw.end_value - tw.start_value) * eased",
        "        end",
        "    end",
        "end",
        "",
        "function tween_remove_prefix(prefix)",
        "    for id, _ in pairs(tweens) do",
        "        if string.sub(id, 1, #prefix) == prefix then",
        "            tweens[id] = nil",
        "        end",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _make_camera_lib() -> str:
    lines = [
        "-- lib/camera.lua",
        "camera = {",
        "    x               = 480,",
        "    y               = 272,",
        "    zoom            = 1.0,",
        "    bounds_enabled  = false,",
        "    bounds_width    = 960,",
        "    bounds_height   = 544,",
        "    follow_target   = nil,",
        "    follow_offset_x = 0,",
        "    follow_offset_y = 0,",
        "    follow_lag      = 0,",
        "}",
        "",
        "function camera_reset_state()",
        "    camera.x               = 480",
        "    camera.y               = 272",
        "    camera.zoom            = 1.0",
        "    camera.bounds_enabled  = false",
        "    camera.bounds_width    = 960",
        "    camera.bounds_height   = 544",
        "    camera.follow_target   = nil",
        "    camera.follow_offset_x = 0",
        "    camera.follow_offset_y = 0",
        "    camera.follow_lag      = 0",
        "end",
        "",
        "function world_to_screen(wx, wy)",
        "    local z = camera.zoom",
        "    return (wx - camera.x) * z + 480, (wy - camera.y) * z + 272",
        "end",
        "",
        "function camera_bg_offset(parallax)",
        "    local z = camera.zoom",
        "    return -(camera.x - 480) * parallax * z, -(camera.y - 272) * parallax * z",
        "end",
        "",
        "function camera_apply_bounds()",
        "    if not camera.bounds_enabled then return end",
        "    local z   = camera.zoom",
        "    local hw  = math.floor(480 / z)",
        "    local hh  = math.floor(272 / z)",
        "    if camera.x < hw  then camera.x = hw  end",
        "    if camera.y < hh  then camera.y = hh  end",
        "    if camera.x > camera.bounds_width  - hw then camera.x = camera.bounds_width  - hw end",
        "    if camera.y > camera.bounds_height - hh then camera.y = camera.bounds_height - hh end",
        "end",
        "",
        "function camera_update_follow()",
        "    if not camera.follow_target then return end",
        "    local tx = _G[camera.follow_target .. '_x']",
        "    local ty = _G[camera.follow_target .. '_y']",
        "    if tx == nil or ty == nil then return end",
        "    tx = tx + camera.follow_offset_x",
        "    ty = ty + camera.follow_offset_y",
        "    if camera.follow_lag <= 0 then",
        "        camera.x = tx",
        "        camera.y = ty",
        "    else",
        "        camera.x = camera.x + (tx - camera.x) * (1 - camera.follow_lag)",
        "        camera.y = camera.y + (ty - camera.y) * (1 - camera.follow_lag)",
        "    end",
        "    camera_apply_bounds()",
        "end",
    ]
    return "\n".join(lines)


def _make_shake_lib() -> str:
    lines = [
        "-- lib/shake.lua",
        "shake_intensity = 0",
        "shake_timer     = 0",
        "shake_offset_x  = 0",
        "shake_offset_y  = 0",
        "",
        "function shake_update()",
        "    if shake_timer > 0 then",
        "        local _si = math.floor(shake_intensity)",
        "        if _si < 1 then _si = 1 end",
        "        shake_offset_x = math.random(-_si, _si)",
        "        shake_offset_y = math.random(-_si, _si)",
        "        shake_timer    = shake_timer - 1",
        "    else",
        "        shake_offset_x = 0",
        "        shake_offset_y = 0",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _make_flash_lib() -> str:
    lines = [
        "-- lib/flash.lua",
        "flash_timer     = 0",
        "flash_duration  = 0",
        "flash_r         = 255",
        "flash_g         = 255",
        "flash_b         = 255",
        "",
        "function flash_update()",
        "    if flash_timer > 0 then",
        "        flash_timer = flash_timer - 1",
        "    end",
        "end",
        "",
        "function flash_draw()",
        "    if flash_timer > 0 and flash_duration > 0 then",
        "        local _alpha = math.floor(255 * flash_timer / flash_duration)",
        "        if _alpha > 255 then _alpha = 255 end",
        "        if _alpha > 0 then",
        "            local _fc = Color.new(flash_r, flash_g, flash_b, _alpha)",
        "            Graphics.fillRect(0, 960, 0, 544, _fc)",
        "        end",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _make_app_ui_lib() -> str:
    lines = [
        "-- lib/app_ui.lua",
        "_app_modal_kind = \"\"",
        "_app_modal_request_id = \"\"",
        "_app_modal_target_var = \"\"",
        "_app_keyboard_submit_request = nil",
        "_app_keyboard_cancel_request = nil",
        "_app_confirm_yes_request = nil",
        "_app_confirm_no_request = nil",
        "",
        "local function _app_ui_clear_modal()",
        "    _app_modal_kind = \"\"",
        "    _app_modal_request_id = \"\"",
        "    _app_modal_target_var = \"\"",
        "end",
        "",
        "function app_ui_reset()",
        "    if _app_modal_kind == \"keyboard\" then",
        "        Keyboard.clear()",
        "    elseif _app_modal_kind == \"confirm\" or _app_modal_kind == \"message\" then",
        "        System.closeMessage()",
        "    end",
        "    _app_keyboard_submit_request = nil",
        "    _app_keyboard_cancel_request = nil",
        "    _app_confirm_yes_request = nil",
        "    _app_confirm_no_request = nil",
        "    _app_ui_clear_modal()",
        "end",
        "",
        "function app_ui_modal_active()",
        "    return _app_modal_kind ~= \"\"",
        "end",
        "",
        "local function _app_ui_match_request(actual, expected)",
        "    if actual == nil then return false end",
        "    local _expected = tostring(expected or \"\")",
        "    if _expected == \"\" then return true end",
        "    return tostring(actual or \"\") == _expected",
        "end",
        "",
        "function app_ui_keyboard_submitted(expected_request_id)",
        "    return _app_ui_match_request(_app_keyboard_submit_request, expected_request_id)",
        "end",
        "",
        "function app_ui_keyboard_canceled(expected_request_id)",
        "    return _app_ui_match_request(_app_keyboard_cancel_request, expected_request_id)",
        "end",
        "",
        "function app_ui_confirmed_yes(expected_request_id)",
        "    return _app_ui_match_request(_app_confirm_yes_request, expected_request_id)",
        "end",
        "",
        "function app_ui_confirmed_no(expected_request_id)",
        "    return _app_ui_match_request(_app_confirm_no_request, expected_request_id)",
        "end",
        "",
        "function app_ui_begin_frame()",
        "    _app_keyboard_submit_request = nil",
        "    _app_keyboard_cancel_request = nil",
        "    _app_confirm_yes_request = nil",
        "    _app_confirm_no_request = nil",
        "    if _app_modal_kind == \"keyboard\" then",
        "        local _state = Keyboard.getState()",
        "        if _state == FINISHED then",
        "            if _app_modal_target_var ~= \"\" then",
        "                _G[_app_modal_target_var] = Keyboard.getInput() or \"\"",
        "            end",
        "            _app_keyboard_submit_request = _app_modal_request_id or \"\"",
        "            Keyboard.clear()",
        "            _app_ui_clear_modal()",
        "        elseif _state == CANCELED then",
        "            _app_keyboard_cancel_request = _app_modal_request_id or \"\"",
        "            Keyboard.clear()",
        "            _app_ui_clear_modal()",
        "        end",
        "    elseif _app_modal_kind == \"confirm\" then",
        "        local _state = System.getMessageState()",
        "        if _state == FINISHED then",
        "            _app_confirm_yes_request = _app_modal_request_id or \"\"",
        "            System.closeMessage()",
        "            _app_ui_clear_modal()",
        "        elseif _state == CANCELED then",
        "            _app_confirm_no_request = _app_modal_request_id or \"\"",
        "            System.closeMessage()",
        "            _app_ui_clear_modal()",
        "        end",
        "    end",
        "end",
        "",
        "function app_ui_open_keyboard(request_id, title, target_var_name, initial_text, max_length)",
        "    if app_ui_modal_active() then return false end",
        "    local _title = tostring(title or \"\")",
        "    local _text = tostring(initial_text or \"\")",
        "    local _length = math.floor(tonumber(max_length) or 255)",
        "    if _length < 1 then _length = 1 end",
        "    Keyboard.start(_title, _text, _length, TYPE_DEFAULT, MODE_TEXT, OPT_NO_AUTOCAP)",
        "    _app_modal_kind = \"keyboard\"",
        "    _app_modal_request_id = tostring(request_id or \"\")",
        "    _app_modal_target_var = tostring(target_var_name or \"\")",
        "    return true",
        "end",
        "",
        "function app_ui_show_confirm(request_id, message_text)",
        "    if app_ui_modal_active() then return false end",
        "    System.setMessage(tostring(message_text or \"\"), false, BUTTON_YES_NO)",
        "    _app_modal_kind = \"confirm\"",
        "    _app_modal_request_id = tostring(request_id or \"\")",
        "    _app_modal_target_var = \"\"",
        "    return true",
        "end",
        "",
        "function app_ui_show_message(message_text)",
        "    if app_ui_modal_active() then return false end",
        "    _app_modal_kind = \"message\"",
        "    System.setMessage(tostring(message_text or \"\"), false, BUTTON_OK)",
        "    while true do",
        "        local _state = System.getMessageState()",
        "        if _state ~= RUNNING then",
        "            break",
        "        end",
        "        System.wait(1000)",
        "    end",
        "    System.closeMessage()",
        "    _app_ui_clear_modal()",
        "    return true",
        "end",
    ]
    return "\n".join(lines)



def _make_save_lib_new(title_id: str, project) -> str:
    """Generate lib/save.lua — multi-slot save/load library.

    Saves current_scene, all game variables, and all placed object state
    (x, y, visible, scale, rotation, opacity) keyed by scene+object so
    scenes don't collide. On load sets _save_just_loaded = true so scene
    init skips overwriting restored state with hardcoded defaults.
    """
    base = f"ux0:data/{title_id}"

    # Game variable save/load lines
    var_save_lines = []
    all_load_lines = []
    for v in project.game_data.variables:
        lua_name = _safe_name(v.name)
        var_save_lines.append(
            f'    lines[#lines+1] = "{lua_name}=" .. tostring({lua_name})'
        )
        if v.var_type == "number":
            all_load_lines.append((lua_name, f'{lua_name} = tonumber(v) or 0'))
        elif v.var_type == "bool":
            all_load_lines.append((lua_name, f'{lua_name} = (v == "true")'))
        else:
            all_load_lines.append((lua_name, f'{lua_name} = v'))

    # Object state save/load lines
    obj_save_lines = []
    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _safe_name(od.name)
            prefix = f"_s{scene_num}_{vname}"
            is_sprite = od.behavior_type not in ("GUI_Panel", "GUI_Label", "GUI_Button")
            fields = [
                (f"{prefix}_x",       vname + "_x",       "number"),
                (f"{prefix}_y",       vname + "_y",       "number"),
                (f"{prefix}_visible", vname + "_visible",  "bool"),
            ]
            if is_sprite:
                fields += [
                    (f"{prefix}_scale",    vname + "_scale",    "number"),
                    (f"{prefix}_rotation", vname + "_rotation", "number"),
                    (f"{prefix}_opacity",  vname + "_opacity",  "number"),
                ]
            for key, lua_var, ftype in fields:
                obj_save_lines.append(
                    f'    lines[#lines+1] = "{key}=" .. tostring({lua_var})'
                )
                if ftype == "number":
                    all_load_lines.append((key, f'{lua_var} = tonumber(v) or 0'))
                else:
                    all_load_lines.append((key, f'{lua_var} = (v == "true")'))

    lines = [
        "-- lib/save.lua  (generated by Vita Adventure Creator)",
        f'local _SAVE_BASE = "{base}"',
        "",
        "local function _slot_path(slot)",
        '    if slot == "auto" then return _SAVE_BASE .. "/autosave.sav" end',
        '    return _SAVE_BASE .. "/slot_" .. tostring(slot) .. ".sav"',
        "end",
        "",
        "function save_serialize(scene_num)",
        "    local lines = {}",
        '    lines[#lines+1] = "current_scene=" .. tostring(scene_num)',
    ]
    lines.extend(var_save_lines)
    lines.extend(obj_save_lines)
    lines += [
        '    return table.concat(lines, "\\n")',
        "end",
        "",
        "function save_to_slot(slot, scene_num)",
        "    System.createDirectory(_SAVE_BASE)",
        "    local path = _slot_path(slot)",
        '    local f = io.open(path, "w")',
        "    if f then",
        "        f:write(save_serialize(scene_num))",
        "        f:close()",
        "    end",
        "end",
        "",
        "function load_from_slot(slot)",
        "    local path = _slot_path(slot)",
        '    local f = io.open(path, "r")',
        "    if not f then return nil end",
        '    local content = f:read("*a")',
        "    f:close()",
        "    local saved_scene = nil",
        '    for line in content:gmatch("[^\\n]+") do',
        '        local k, v = line:match("^(.-)=(.+)$")',
        "        if k and v then",
        '            if k == "current_scene" then',
        "                saved_scene = tonumber(v)",
    ]
    for key, assignment in all_load_lines:
        lines.append(f'            elseif k == "{key}" then {assignment}')
    lines += [
        "            end",
        "        end",
        "    end",
        "    if saved_scene then _save_just_loaded = true end",
        "    return saved_scene",
        "end",
        "",
        "function slot_exists(slot)",
        "    local path = _slot_path(slot)",
        '    local f = io.open(path, "r")',
        "    if f then f:close(); return true end",
        "    return false",
        "end",
    ]
    return "\n".join(lines)


def _find_active_savegame_component(project):
    """Return the first SaveGame component found in project scene/component order."""
    if not project:
        return None
    for scene in project.scenes:
        for comp in scene.components:
            if comp.component_type == "SaveGame":
                return comp
    return None


def _export_save_scene(project, scene_number: int, save_component=None) -> str:
    """
    Generate scenes/save_scene.lua — the dedicated save/load UI scene.
    scene_number is the 1-based index assigned to this scene in the main loop.
    Uses local advance = false / while not advance do, identical to every
    other scene function generated by this exporter.
    """
    config = getattr(save_component, "config", {}) or {}

    title_text          = str(config.get("title_text", "SAVE / LOAD"))
    slot_prefix         = str(config.get("slot_prefix", "Slot"))
    help_text           = str(config.get("help_text", "Cross: Save  Triangle: Load  Circle: Back"))
    empty_slot_text     = str(config.get("empty_slot_text", "Empty"))
    saved_text          = str(config.get("saved_text", "Saved."))
    no_save_text        = str(config.get("no_save_text", "No save in this slot."))
    title_font_size     = int(config.get("title_font_size", 24) or 24)
    slot_font_size      = int(config.get("slot_font_size", 18) or 18)
    message_font_size   = int(config.get("message_font_size", 18) or 18)
    help_font_size      = int(config.get("help_font_size", 16) or 16)
    bg_color            = str(config.get("bg_color", "#000000") or "#000000")
    title_color         = str(config.get("title_color", "#FFFFFF") or "#FFFFFF")
    slot_color          = str(config.get("slot_color", "#B4B4B4") or "#B4B4B4")
    selected_slot_color = str(config.get("selected_slot_color", "#FFFF64") or "#FFFF64")
    empty_slot_color    = str(config.get("empty_slot_color", "#787878") or "#787878")
    message_color       = str(config.get("message_color", "#FFFFFF") or "#FFFFFF")
    help_color          = str(config.get("help_color", "#A0A0A0") or "#A0A0A0")
    background_use_image = bool(config.get("background_use_image", False))
    background_image_id  = config.get("background_image_id", "") or ""
    layout_preset       = str(config.get("layout_preset", "center") or "center").lower()
    slot_spacing        = int(config.get("slot_spacing", 60) or 60)
    show_help_text      = bool(config.get("show_help_text", True))
    use_panel           = bool(config.get("use_panel", False))
    panel_color         = str(config.get("panel_color", "#000000") or "#000000")
    panel_opacity       = int(config.get("panel_opacity", 160) or 160)

    if layout_preset not in ("center", "left", "right"):
        layout_preset = "center"
    if slot_spacing < 1:
        slot_spacing = 1
    panel_opacity = max(0, min(255, panel_opacity))

    font_var = "deff"
    font_id = config.get("font_id", "") or ""
    if font_id:
        fnt = project.get_font(font_id) if project else None
        if fnt and fnt.path:
            font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'

    bg_image_fname = None
    if background_use_image and background_image_id and project:
        img = project.get_image(background_image_id)
        if img and img.path:
            bg_image_fname = _asset_filename(img.path)

    if layout_preset == "left":
        title_x = 60;  slot_x = 80;  msg_x = 60;  help_x = 60
        panel_x1 = 40; panel_x2 = 520
    elif layout_preset == "right":
        title_x = 540; slot_x = 560; msg_x = 540; help_x = 540
        panel_x1 = 500; panel_x2 = 920
    else:  # center
        title_x = 300; slot_x = 320; msg_x = 300; help_x = 300
        panel_x1 = 260; panel_x2 = 700

    title_y    = 40
    slot_y_start = 110
    msg_y      = 370
    help_y     = 430
    panel_y1   = 20
    panel_y2   = 500

    lines = [
        "-- scenes/save_scene.lua  (generated by Vita Adventure Creator)",
        "function scene_save_scene()",
        f"    local ui_font = {font_var}",
        "    local advance = false",
        "    local selected = 1",
        f'    local msg = {_lua_str("")}',
        "    local msg_timer = 0",
    ]

    if bg_image_fname:
        lines.append(f'    local bg_image = images[{_lua_str(bg_image_fname)}]')
    else:
        lines.append("    local bg_image = nil")

    lines += [
        "",
        "    while not advance do",
        "        controls_update()",
        "        touch_update()",
        "        _signals = {}",
        "",
        "        -- Navigation",
        "        if controls_pressed(SCE_CTRL_UP) then",
        "            selected = selected - 1",
        "            if selected < 1 then selected = 3 end",
        "        elseif controls_pressed(SCE_CTRL_DOWN) then",
        "            selected = selected + 1",
        "            if selected > 3 then selected = 1 end",
        "        end",
        "",
        "        -- Save (Cross)",
        "        if controls_pressed(SCE_CTRL_CROSS) then",
        "            save_to_slot(selected, _prev_scene or current_scene)",
        f'            msg = {_lua_str(saved_text)}',
        "            msg_timer = 90",
        "        end",
        "",
        "        -- Load (Triangle)",
        "        if controls_pressed(SCE_CTRL_TRIANGLE) then",
        "            if slot_exists(selected) then",
        "                local saved_scene = load_from_slot(selected)",
        "                if saved_scene then",
        "                    current_scene = saved_scene",
        "                    advance = true",
        "                end",
        "            else",
        f'                msg = {_lua_str(no_save_text)}',
        "                msg_timer = 90",
        "            end",
        "        end",
        "",
        "        -- Cancel / Exit (Circle)",
        "        if controls_pressed(SCE_CTRL_CIRCLE) then",
        "            _save_scene_leaving = true",
        "            current_scene = _prev_scene or current_scene",
        "            advance = true",
        "        end",
        "",
        "        -- Draw",
        "        Graphics.initBlend()",
        "        Screen.clear()",
        f"        Graphics.fillRect(0, 960, 0, 544, {_parse_hex_color(bg_color)})",
        "        if bg_image then Graphics.drawImage(0, 0, bg_image) end",
    ]

    if use_panel:
        lines.append(f"        Graphics.fillRect({panel_x1}, {panel_x2}, {panel_y1}, {panel_y2}, {_parse_hex_color(panel_color, panel_opacity)})")

    lines += [
        "        if ui_font then",
        f"            Font.setPixelSizes(ui_font, {title_font_size})",
        f"            Font.print(ui_font, {title_x}, {title_y}, {_lua_str(title_text)}, {_parse_hex_color(title_color)})",
        f"            Font.setPixelSizes(ui_font, {slot_font_size})",
        "            for i = 1, 3 do",
        f"                local y = {slot_y_start} + (i - 1) * {slot_spacing}",
        f"                local label = {_lua_str(slot_prefix)} .. \" \" .. tostring(i)",
        f"                local col = {_parse_hex_color(slot_color)}",
        "                if i == selected then",
        f"                    col = {_parse_hex_color(selected_slot_color)}",
        "                elseif not slot_exists(i) then",
        f"                    col = {_parse_hex_color(empty_slot_color)}",
        "                end",
        "                if not slot_exists(i) then",
        f"                    label = label .. \" - \" .. {_lua_str(empty_slot_text)}",
        "                end",
        f"                Font.print(ui_font, {slot_x}, y, label, col)",
        "            end",
        "            if msg_timer > 0 then",
        f"                Font.setPixelSizes(ui_font, {message_font_size})",
        f"                Font.print(ui_font, {msg_x}, {msg_y}, msg, {_parse_hex_color(message_color)})",
        "                msg_timer = msg_timer - 1",
        "            end",
    ]

    if show_help_text:
        lines += [
            f"            Font.setPixelSizes(ui_font, {help_font_size})",
            f"            Font.print(ui_font, {help_x}, {help_y}, {_lua_str(help_text)}, {_parse_hex_color(help_color)})",
        ]

    lines += [
        "        end",
        "        Graphics.termBlend()",
        "        Screen.flip()",
        "    end",
        "end",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  INLINE ACTION → LUA
# ─────────────────────────────────────────────────────────────

def _resolve_target_name(target_id: str, project) -> str:
    if not target_id:
        return ""
    if not project:
        return _safe_name(target_id)
    scene_hits = _scene_target_vars(target_id, project)
    if scene_hits:
        return scene_hits[0]
    od = project.get_object_def(target_id)
    if od:
        return _safe_name(od.name)
    for scene in project.scenes:
        for po in scene.placed_objects:
            if po.instance_id == target_id:
                od = project.get_object_def(po.object_def_id)
                if od:
                    return _safe_name(od.name)
    return _safe_name(target_id)


def _resolve_target_od(target_id: str, project):
    """Return the ObjectDefinition for a target id (def id or instance id), or None."""
    if not target_id or not project:
        return None
    refs = _scene_target_refs(target_id, project)
    if refs:
        return refs[0][1]
    od = project.get_object_def(target_id)
    if od:
        return od
    for scene in project.scenes:
        for po in scene.placed_objects:
            if po.instance_id == target_id:
                return project.get_object_def(po.object_def_id)
    return None


def _resolve_layer_anim_target(layer_anim_id: str, project) -> str:
    """Resolve a PaperDollAsset id to the variable name of the object that uses it."""
    if not layer_anim_id or not project:
        return ""
    scene = _active_export_scene(project)
    if scene is not None:
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "LayerAnimation" and od.layer_anim_id == layer_anim_id:
                return _placed_var_name(po)
    for od in project.object_defs:
        if od.behavior_type == "LayerAnimation" and od.layer_anim_id == layer_anim_id:
            return _safe_name(od.name)
    return ""


def _collect_vn_sound_configs(scene, project):
    """Scan placed objects for vn_dialog_sound / vn_tw_sound nodes.
    Returns (dialog_cfg, tw_cfg) where each is a dict or None.
      dialog_cfg: {fname, mode}
      tw_cfg:     {fnames: [str,...], interval: int}
    Only the first found node of each type is used.
    """
    dialog_cfg = None
    tw_cfg = None
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od:
            continue
        for beh in effective_placed_behaviors(po, od):
            for action in beh.actions:
                t = action.action_type
                if t == "vn_dialog_sound" and dialog_cfg is None:
                    aid = action.vn_dialog_sound_id or ""
                    aud = project.get_audio(aid) if aid else None
                    if aud and aud.path:
                        dialog_cfg = {
                            "fname": _asset_filename(aud.path),
                            "mode":  action.vn_dialog_sound_mode or "play_once",
                        }
                elif t == "vn_tw_sound" and tw_cfg is None:
                    fnames = []
                    for i in range(4):
                        aid = getattr(action, f"vn_tw_sound_id_{i}", "") or ""
                        aud = project.get_audio(aid) if aid else None
                        if aud and aud.path:
                            fnames.append(_asset_filename(aud.path))
                    if fnames:
                        tw_cfg = {
                            "fnames":   fnames,
                            "interval": max(1, int(action.vn_tw_sound_interval or 1)),
                        }
    return dialog_cfg, tw_cfg


def _emit_pdoll_layers(out: list, layers, project, indent: int):
    """Recursively emit Lua table entries for a paper doll layer tree."""
    pad = "    " * indent
    for layer in layers:
        img = project.get_image(layer.image_id) if layer.image_id else None
        img_fname = _lua_str(_asset_filename(img.path)) if img and img.path else "nil"
        out.append(f'{pad}{{')
        out.append(f'{pad}    id = {_lua_str(layer.id)},')
        out.append(f'{pad}    name = {_lua_str(layer.name)},')
        out.append(f'{pad}    image = {img_fname},')
        out.append(f'{pad}    origin_x = {layer.origin_x}, origin_y = {layer.origin_y},')
        out.append(f'{pad}    x = {layer.x}, y = {layer.y},')
        out.append(f'{pad}    rotation = {layer.rotation}, scale = {layer.scale},')
        if layer.children:
            out.append(f'{pad}    children = {{')
            _emit_pdoll_layers(out, layer.children, project, indent + 2)
            out.append(f'{pad}    }},')
        else:
            out.append(f'{pad}    children = {{}},')
        out.append(f'{pad}}},')



def _action_to_lua_inline(action: BehaviorAction, obj_var: str | None, project=None, obj_def=None) -> list[str]:
    # Nested actions (true_actions, false_actions, sub_actions) may be stored as
    # plain dicts when serialised via to_dict(); coerce back to BehaviorAction here
    # so all attribute accesses below work regardless of how the caller got the data.
    if isinstance(action, dict):
        action = BehaviorAction.from_dict(action)
    t = action.action_type
    lines = []
    spd = action.movement_speed  # int, always present

    if t == "four_way_movement":
        _mi = getattr(action, "movement_input", "dpad") or "dpad"
        lines.append(f"if {_movement_input_cond(_mi, 'up')}    then {obj_var}_y = {obj_var}_y - {spd} end")
        lines.append(f"if {_movement_input_cond(_mi, 'down')}  then {obj_var}_y = {obj_var}_y + {spd} end")
        lines.append(f"if {_movement_input_cond(_mi, 'left')}  then {obj_var}_x = {obj_var}_x - {spd} end")
        lines.append(f"if {_movement_input_cond(_mi, 'right')} then {obj_var}_x = {obj_var}_x + {spd} end")

    elif t == "four_way_movement_collide":
        grid_id = action.collision_layer_id or ""
        pw      = action.player_width
        ph      = action.player_height
        _mi     = getattr(action, "movement_input", "dpad") or "dpad"
        if not grid_id and project:
            for _scene in project.scenes:
                for _comp in _scene.components:
                    if _comp.component_type == "CollisionLayer":
                        grid_id = _comp.id
                        break
                if grid_id:
                    break
        _has_cboxes = _object_has_collision_boxes(obj_def)
        if obj_var and obj_def:
            _cframe = f"{obj_var}_ani_frame" if obj_def.behavior_type == "Animation" else "0"
            _cslot = f"{obj_var}_ani_slot_name" if obj_def.behavior_type == "Animation" else '""'
            _cid = _lua_str(obj_def.id)
            lines.append("do")
            lines.append(f"    local _grid = collision_grids[{_lua_str(grid_id)}]")
            lines.append(f"    local _self_handle = prim.handle_from_var({_lua_str(obj_var)}) or \"__self__\"")
            lines.append(f"    if {_movement_input_cond(_mi, 'left')} then")
            lines.append(f"        local _nx = {obj_var}_x - {spd}")
            if _has_cboxes:
                _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe}))"
            else:
                _grid_block = f"(_grid and check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}))"
            _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe})"
            lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_x = _nx end")
            lines.append("    end")
            lines.append(f"    if {_movement_input_cond(_mi, 'right')} then")
            lines.append(f"        local _nx = {obj_var}_x + {spd}")
            if _has_cboxes:
                _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe}))"
            else:
                _grid_block = f"(_grid and check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}))"
            _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe})"
            lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_x = _nx end")
            lines.append("    end")
            lines.append(f"    if {_movement_input_cond(_mi, 'up')} then")
            lines.append(f"        local _ny = {obj_var}_y - {spd}")
            if _has_cboxes:
                _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe}))"
            else:
                _grid_block = f"(_grid and check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}))"
            _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe})"
            lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_y = _ny end")
            lines.append("    end")
            lines.append(f"    if {_movement_input_cond(_mi, 'down')} then")
            lines.append(f"        local _ny = {obj_var}_y + {spd}")
            if _has_cboxes:
                _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe}))"
            else:
                _grid_block = f"(_grid and check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}))"
            _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe})"
            lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_y = _ny end")
            lines.append("    end")
            lines.append("end")
        else:
            lines.append(f"if {_movement_input_cond(_mi, 'up')}    then {obj_var}_y = {obj_var}_y - {spd} end")
            lines.append(f"if {_movement_input_cond(_mi, 'down')}  then {obj_var}_y = {obj_var}_y + {spd} end")
            lines.append(f"if {_movement_input_cond(_mi, 'left')}  then {obj_var}_x = {obj_var}_x - {spd} end")
            lines.append(f"if {_movement_input_cond(_mi, 'right')} then {obj_var}_x = {obj_var}_x + {spd} end")

    elif t in ("eight_way_movement", "eight_way_movement_collide"):
        rot_mode  = getattr(action, "rotation_mode", "instant")
        rot_dur   = getattr(action, "rotation_tween_duration", 0.3)
        rot_frames = max(1, round(rot_dur * 60))
        _mi       = getattr(action, "movement_input", "dpad") or "dpad"

        # Diagonal angles: atan2(dy, dx) + 90 so sprite facing UP = 0°
        # UP=0, UP-RIGHT=45, RIGHT=90, DOWN-RIGHT=135,
        # DOWN=180, DOWN-LEFT=225(-135), LEFT=270(-90), UP-LEFT=315(-45)
        # We use a lookup table keyed on (dx,dy) sign pairs for clarity.

        def _rot_line(angle: float) -> str:
            if rot_mode == "tween":
                return f'tween_add("{obj_var}_rot8", _G, "{obj_var}_rotation", {angle}, {rot_frames}, "linear")'
            else:
                return f"{obj_var}_rotation = {angle}"

        if t == "eight_way_movement":
            # Simple no-collision version
            lines.append(f"do")
            lines.append(f"    local _dx8 = 0")
            lines.append(f"    local _dy8 = 0")
            lines.append(f"    if {_movement_input_cond(_mi, 'up')}    then _dy8 = _dy8 - 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'down')}  then _dy8 = _dy8 + 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'left')}  then _dx8 = _dx8 - 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'right')} then _dx8 = _dx8 + 1 end")
            lines.append(f"    if _dx8 ~= 0 or _dy8 ~= 0 then")
            lines.append(f"        local _spd8 = {spd}")
            lines.append(f"        if _dx8 ~= 0 and _dy8 ~= 0 then _spd8 = _spd8 * 0.7071 end")
            lines.append(f"        {obj_var}_x = {obj_var}_x + _dx8 * _spd8")
            lines.append(f"        {obj_var}_y = {obj_var}_y + _dy8 * _spd8")
            lines.append(f"        if     _dx8 == 0  and _dy8 == -1 then {_rot_line(0)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == -1 then {_rot_line(45)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == 0  then {_rot_line(90)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == 1  then {_rot_line(135)}")
            lines.append(f"        elseif _dx8 == 0  and _dy8 == 1  then {_rot_line(180)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == 1  then {_rot_line(225)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == 0  then {_rot_line(270)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == -1 then {_rot_line(315)}")
            lines.append(f"        end")
            lines.append(f"    end")
            lines.append(f"end")

        else:  # eight_way_movement_collide
            grid_id = action.collision_layer_id or ""
            pw      = action.player_width
            ph      = action.player_height
            if not grid_id and project:
                for _scene in project.scenes:
                    for _comp in _scene.components:
                        if _comp.component_type == "CollisionLayer":
                            grid_id = _comp.id
                            break
                    if grid_id:
                        break
            _has_cboxes = _object_has_collision_boxes(obj_def)

            lines.append(f"do")
            lines.append(f"    local _dx8 = 0")
            lines.append(f"    local _dy8 = 0")
            lines.append(f"    if {_movement_input_cond(_mi, 'up')}    then _dy8 = _dy8 - 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'down')}  then _dy8 = _dy8 + 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'left')}  then _dx8 = _dx8 - 1 end")
            lines.append(f"    if {_movement_input_cond(_mi, 'right')} then _dx8 = _dx8 + 1 end")
            lines.append(f"    if _dx8 ~= 0 or _dy8 ~= 0 then")
            lines.append(f"        local _spd8 = {spd}")
            lines.append(f"        if _dx8 ~= 0 and _dy8 ~= 0 then _spd8 = _spd8 * 0.7071 end")
            _cframe = f"{obj_var}_ani_frame" if obj_def and obj_def.behavior_type == "Animation" else "0"
            _cslot  = f"{obj_var}_ani_slot_name" if obj_def and obj_def.behavior_type == "Animation" else '""'
            _cid    = _lua_str(obj_def.id) if obj_def else '""'
            lines.append(f"        local _grid = collision_grids[{_lua_str(grid_id)}]")
            lines.append(f"        local _self_handle = prim.handle_from_var({_lua_str(obj_var)}) or \"__self__\"")
            lines.append(f"        local _nx8 = {obj_var}_x + _dx8 * _spd8")
            lines.append(f"        local _ny8 = {obj_var}_y + _dy8 * _spd8")
            if _has_cboxes:
                _grid_block_x = f"(_grid and check_obj_vs_grid(_grid, {_cid}, _nx8, {obj_var}_y, {_cslot}, {_cframe}))"
                _grid_block_y = f"(_grid and check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny8, {_cslot}, {_cframe}))"
            else:
                _grid_block_x = f"(_grid and check_collision_rect(_grid, _nx8, {obj_var}_y, {pw}, {ph}))"
                _grid_block_y = f"(_grid and check_collision_rect(_grid, {obj_var}_x, _ny8, {pw}, {ph}))"
            _solid_block_x = f"check_obj_vs_solids(_self_handle, {_cid}, _nx8, {obj_var}_y, {_cslot}, {_cframe})"
            _solid_block_y = f"check_obj_vs_solids(_self_handle, {_cid}, {obj_var}_x, _ny8, {_cslot}, {_cframe})"
            lines.append(f"        if not ({_grid_block_x} or {_solid_block_x}) then {obj_var}_x = _nx8 end")
            lines.append(f"        if not ({_grid_block_y} or {_solid_block_y}) then {obj_var}_y = _ny8 end")
            lines.append(f"        if     _dx8 == 0  and _dy8 == -1 then {_rot_line(0)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == -1 then {_rot_line(45)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == 0  then {_rot_line(90)}")
            lines.append(f"        elseif _dx8 == 1  and _dy8 == 1  then {_rot_line(135)}")
            lines.append(f"        elseif _dx8 == 0  and _dy8 == 1  then {_rot_line(180)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == 1  then {_rot_line(225)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == 0  then {_rot_line(270)}")
            lines.append(f"        elseif _dx8 == -1 and _dy8 == -1 then {_rot_line(315)}")
            lines.append(f"        end")
            lines.append(f"    end")
            lines.append(f"end")

    elif t == "two_way_movement":
        axis = action.two_way_axis
        _mi  = getattr(action, "movement_input", "dpad") or "dpad"
        if axis == "horizontal":
            lines.append(f"if {_movement_input_cond(_mi, 'left')}  then {obj_var}_x = {obj_var}_x - {spd} end")
            lines.append(f"if {_movement_input_cond(_mi, 'right')} then {obj_var}_x = {obj_var}_x + {spd} end")
        else:
            lines.append(f"if {_movement_input_cond(_mi, 'up')}    then {obj_var}_y = {obj_var}_y - {spd} end")
            lines.append(f"if {_movement_input_cond(_mi, 'down')}  then {obj_var}_y = {obj_var}_y + {spd} end")

    elif t == "two_way_movement_collide":
        axis    = action.two_way_axis
        grid_id = action.collision_layer_id or ""
        pw      = action.player_width
        ph      = action.player_height
        _mi     = getattr(action, "movement_input", "dpad") or "dpad"
        if not grid_id and project:
            for _scene in project.scenes:
                for _comp in _scene.components:
                    if _comp.component_type == "CollisionLayer":
                        grid_id = _comp.id
                        break
                if grid_id:
                    break
        _has_cboxes = _object_has_collision_boxes(obj_def)
        if obj_var and obj_def:
            _cframe = f"{obj_var}_ani_frame" if obj_def.behavior_type == "Animation" else "0"
            _cslot = f"{obj_var}_ani_slot_name" if obj_def.behavior_type == "Animation" else '""'
            _cid = _lua_str(obj_def.id)
            lines.append("do")
            lines.append(f"    local _grid = collision_grids[{_lua_str(grid_id)}]")
            lines.append(f"    local _self_handle = prim.handle_from_var({_lua_str(obj_var)}) or \"__self__\"")
            if axis == "horizontal":
                lines.append(f"    if {_movement_input_cond(_mi, 'left')} then")
                lines.append(f"        local _nx = {obj_var}_x - {spd}")
                if _has_cboxes:
                    _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe}))"
                else:
                    _grid_block = f"(_grid and check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}))"
                _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe})"
                lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_x = _nx end")
                lines.append("    end")
                lines.append(f"    if {_movement_input_cond(_mi, 'right')} then")
                lines.append(f"        local _nx = {obj_var}_x + {spd}")
                if _has_cboxes:
                    _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe}))"
                else:
                    _grid_block = f"(_grid and check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}))"
                _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, _nx, {obj_var}_y, {_cslot}, {_cframe})"
                lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_x = _nx end")
                lines.append("    end")
            else:
                lines.append(f"    if {_movement_input_cond(_mi, 'up')} then")
                lines.append(f"        local _ny = {obj_var}_y - {spd}")
                if _has_cboxes:
                    _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe}))"
                else:
                    _grid_block = f"(_grid and check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}))"
                _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe})"
                lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_y = _ny end")
                lines.append("    end")
                lines.append(f"    if {_movement_input_cond(_mi, 'down')} then")
                lines.append(f"        local _ny = {obj_var}_y + {spd}")
                if _has_cboxes:
                    _grid_block = f"(_grid and check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe}))"
                else:
                    _grid_block = f"(_grid and check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}))"
                _solid_block = f"check_obj_vs_solids(_self_handle, {_cid}, {obj_var}_x, _ny, {_cslot}, {_cframe})"
                lines.append(f"        if not ({_grid_block} or {_solid_block}) then {obj_var}_y = _ny end")
                lines.append("    end")
            lines.append("end")
        else:
            if axis == "horizontal":
                lines.append(f"if {_movement_input_cond(_mi, 'left')}  then {obj_var}_x = {obj_var}_x - {spd} end")
                lines.append(f"if {_movement_input_cond(_mi, 'right')} then {obj_var}_x = {obj_var}_x + {spd} end")
            else:
                lines.append(f"if {_movement_input_cond(_mi, 'up')}    then {obj_var}_y = {obj_var}_y - {spd} end")
                lines.append(f"if {_movement_input_cond(_mi, 'down')}  then {obj_var}_y = {obj_var}_y + {spd} end")

    elif t == "fire_bullet":
        bdir = action.bullet_direction
        bspd = action.bullet_speed
        if bdir == "right":
            lines.append(f"{obj_var}_x = {obj_var}_x + {bspd}")
        elif bdir == "left":
            lines.append(f"{obj_var}_x = {obj_var}_x - {bspd}")
        elif bdir == "down":
            lines.append(f"{obj_var}_y = {obj_var}_y + {bspd}")
        elif bdir == "up":
            lines.append(f"{obj_var}_y = {obj_var}_y - {bspd}")

    elif t == "set_velocity":
        target_handles = _target_handles_for_action(action, project, obj_var)
        if target_handles:
            for handle_expr in target_handles:
                lines.append("do")
                lines.append(f"    local _target_handle = {handle_expr}")
                lines.append("    if _target_handle then")
                lines.append(
                    f"        prim.set_velocity(_target_handle, {action.velocity_vx}, {action.velocity_vy}, "
                    f"{_lua_bool(action.velocity_set_x)}, {_lua_bool(action.velocity_set_y)})"
                )
                lines.append("    end")
                lines.append("end")

    elif t == "add_velocity":
        target_handles = _target_handles_for_action(action, project, obj_var)
        if target_handles:
            for handle_expr in target_handles:
                lines.append("do")
                lines.append(f"    local _target_handle = {handle_expr}")
                lines.append("    if _target_handle then")
                lines.append(
                    f"        prim.add_velocity(_target_handle, {action.velocity_vx}, {action.velocity_vy}, "
                    f"{_lua_bool(action.velocity_set_x)}, {_lua_bool(action.velocity_set_y)})"
                )
                lines.append("    end")
                lines.append("end")

    elif t == "jump":
        target_vars = _target_vars_for_action(action, project, obj_var)
        if not target_vars:
            return lines
        strength      = action.jump_strength
        max_jumps     = action.jump_max_count
        for target in target_vars:
            lines.append(f"if {target}_jump_count < {max_jumps} then")
            lines.append(f"    {target}_vy = -{strength}")
            lines.append(f"    {target}_jump_count = {target}_jump_count + 1")
            lines.append(f"    {target}_jump_button_held = true")
            lines.append("end")

    elif t == "restart_scene":
        lines.append("advance = true  -- current_scene unchanged; main loop re-calls this scene")

    elif t == "emit_signal":
        sig = getattr(action, "signal_name", "") or action.var_name or ""
        if sig:
            lines.append(f"emit_signal({_lua_str(sig)})")
        else:
            lines.append("-- emit_signal: no signal name set")

    elif t == "go_to_next":
        max_scene = len(project.scenes) if project else 1
        lines.append(f"current_scene = math.min(current_scene + 1, {max_scene})")
        lines.append("advance = true")

    elif t == "go_to_prev":
        lines.append("current_scene = math.max(current_scene - 1, 1)")
        lines.append("advance = true")

    elif t == "go_to_scene":
        lines.append(f"current_scene = {action.target_scene}")
        lines.append("advance = true")

    elif t == "quit_game":
        lines.append("if current_music then Sound.close(current_music) end")
        lines.append("os.exit()")

    elif t == "stop_music":
        lines.append("if current_music then Sound.close(current_music) end")
        lines.append("current_music = nil")

    elif t == "play_music":
        audio_id = action.audio_id or ""
        if audio_id and project:
            aud = project.get_audio(audio_id)
            if aud and aud.path:
                fname = _asset_filename(aud.path)
                lines.append("if current_music then Sound.close(current_music) end")
                lines.append(f"current_music = audio_tracks[{_lua_str(fname)}]")
                lines.append("if current_music then Sound.play(current_music, true) end")
            else:
                lines.append(f"-- play_music: audio asset {_lua_str(audio_id)} not found")
        else:
            lines.append("-- play_music: no audio_id specified")

    elif t == "set_music_volume":
        vol = int(action.volume)
        lpp_vol = int(vol / 100.0 * 32767)
        lpp_vol = max(0, min(32767, lpp_vol))
        lines.append(f"if current_music then Sound.setVolume(current_music, {lpp_vol}) end")

    elif t == "play_sfx":
        audio_id = action.audio_id or ""
        if audio_id and project:
            aud = project.get_audio(audio_id)
            if aud and aud.path:
                fname = _asset_filename(aud.path)
                lines.append(f"do")
                lines.append(f"    local _sfx = audio_tracks[{_lua_str(fname)}]")
                lines.append(f"    if _sfx then Sound.play(_sfx, false) end")
                lines.append(f"end")
            else:
                lines.append(f"-- play_sfx: audio asset {_lua_str(audio_id)} not found")
        else:
            lines.append("-- play_sfx: no audio_id specified")

    elif t == "set_flag":
        bn  = _safe_name(action.bool_name) if action.bool_name else "unknown_flag"
        val = "true" if action.bool_value else "false"
        lines.append(f"{bn} = {val}")

    elif t == "toggle_flag":
        bn = _safe_name(action.bool_name) if action.bool_name else "unknown_flag"
        lines.append(f"{bn} = not {bn}")

    elif t == "add_item":
        iname = _safe_name(action.item_name) if action.item_name else "unknown_item"
        lines.append(f'inventory_add("{iname}")')

    elif t == "remove_item":
        iname = _safe_name(action.item_name) if action.item_name else "unknown_item"
        lines.append(f'inventory_remove("{iname}")')

    elif t == "move_to" and obj_var:
        lines.append(f"{obj_var}_x = {action.target_x}")
        lines.append(f"{obj_var}_y = {action.target_y}")

    elif t == "move_to_variable":
        targets = _target_vars_for_action(action, project, obj_var)
        xvar = _safe_name(action.var_name) if action.var_name else "0"
        yvar = _safe_name(action.var_source) if action.var_source else "0"
        for target in targets:
            lines.append(f"{target}_x = {xvar}")
            lines.append(f"{target}_y = {yvar}")

    elif t == "move_by" and obj_var:
        lines.append(f"{obj_var}_x = {obj_var}_x + {action.offset_x}")
        lines.append(f"{obj_var}_y = {obj_var}_y + {action.offset_y}")

    elif t == "show_object" and obj_var:
        lines.append(f"{obj_var}_visible = true")

    elif t == "hide_object" and obj_var:
        lines.append(f"{obj_var}_visible = false")

    elif t == "set_variable":
        vn  = _safe_name(action.var_name) if action.var_name else "unknown"
        val = _lua_str(action.var_value) if isinstance(action.var_value, str) else str(action.var_value)
        lines.append(f"{vn} = {val}")

    elif t == "change_variable":
        vn  = _safe_name(action.var_name) if action.var_name else "unknown"
        val = action.var_value if action.var_value else "0"
        op  = action.var_operator  # set | add | subtract | multiply | divide
        if op == "add":
            lines.append(f"{vn} = ({vn} or 0) + {val}")
        elif op == "subtract":
            lines.append(f"{vn} = ({vn} or 0) - {val}")
        elif op == "multiply":
            lines.append(f"{vn} = ({vn} or 0) * {val}")
        elif op == "divide":
            lines.append(f"{vn} = ({vn} or 0) / {val}")
        else:
            lines.append(f"{vn} = {val}")

    elif t == "set_variable_from_variable":
        # target = source  (copy one variable's value into another)
        vn  = _safe_name(action.var_name)   if action.var_name   else "unknown"
        src = _safe_name(action.var_source) if action.var_source else "unknown_src"
        lines.append(f"{vn} = {src}")

    elif t == "change_variable_by_variable":
        # target op= source  (arithmetic using another variable as the operand)
        vn  = _safe_name(action.var_name)   if action.var_name   else "unknown"
        src = _safe_name(action.var_source) if action.var_source else "unknown_src"
        op  = action.var_operator
        if op == "add":
            lines.append(f"{vn} = ({vn} or 0) + ({src} or 0)")
        elif op == "subtract":
            lines.append(f"{vn} = ({vn} or 0) - ({src} or 0)")
        elif op == "multiply":
            lines.append(f"{vn} = ({vn} or 0) * ({src} or 0)")
        elif op == "divide":
            lines.append(f"if ({src} or 0) ~= 0 then {vn} = ({vn} or 0) / {src} end")
        else:
            lines.append(f"{vn} = {src}")

    elif t == "evaluate_expression":
        # result_var = load("return " .. expression)()
        # The expression string may reference any global variable by name.
        vn   = _safe_name(action.var_name) if action.var_name else "unknown"
        expr = (action.expression or "").strip()
        if expr:
            lines.append(f"do")
            lines.append(f"    local _fn, _err = load(\"return \" .. tostring({_lua_str(expr)}))")
            lines.append(f"    if _fn then {vn} = _fn() else")
            lines.append(f"        -- evaluate_expression error: ' .. (_err or '?')")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            lines.append(f"-- evaluate_expression: no expression set for {vn}")

    elif t == "clamp_variable":
        vn  = _safe_name(action.var_name) if action.var_name else "unknown"
        cmin = (action.clamp_min or "").strip()
        cmax = (action.clamp_max or "").strip()
        if cmin and cmax:
            lines.append(f"{vn} = math.max({cmin}, math.min({cmax}, ({vn} or 0)))")
        elif cmin:
            lines.append(f"if ({vn} or 0) < {cmin} then {vn} = {cmin} end")
        elif cmax:
            lines.append(f"if ({vn} or 0) > {cmax} then {vn} = {cmax} end")
        else:
            lines.append(f"-- clamp_variable: no min or max set for {vn}")

    elif t == "loop":
        # loop_count == 0 means infinite (while true); sub_actions are the body.
        count = int(action.loop_count or 0)
        body_actions = action.sub_actions or []
        if count > 0:
            lines.append(f"for _li = 1, {count} do")
        else:
            lines.append(f"while true do")
        for sa in body_actions:
            if isinstance(sa, dict):
                sa = BehaviorAction.from_dict(sa)
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        lines.append("end")

    elif t == "increment_var":
        vn    = _safe_name(action.var_name) if action.var_name else "unknown"
        delta = action.var_value if action.var_value else "1"
        lines.append(f"{vn} = {vn} + {delta}")

    elif t == "if_button_pressed":
        btn = _button_constant(action.button)
        lines.append(f"if controls_pressed({btn}) then")
        for sa in (action.true_actions or action.sub_actions or []):
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_button_held":
        btn = _button_constant(action.button)
        lines.append(f"if controls_held({btn}) then")
        for sa in (action.true_actions or action.sub_actions or []):
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_button_released":
        btn = _button_constant(action.button)
        lines.append(f"if controls_released({btn}) then")
        for sa in (action.true_actions or action.sub_actions or []):
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "camera_move_to":
        if action.camera_duration > 0:
            frames = int(action.camera_duration * 60)
            lines.append(f'tween_add("cam_x", camera, "x", {action.camera_target_x}, {frames}, "{action.camera_easing}")')
            lines.append(f'tween_add("cam_y", camera, "y", {action.camera_target_y}, {frames}, "{action.camera_easing}")')
        else:
            lines.append(f"camera.x = {action.camera_target_x}")
            lines.append(f"camera.y = {action.camera_target_y}")
        lines.append("camera_apply_bounds()")

    elif t == "camera_offset":
        if action.camera_duration > 0:
            frames = int(action.camera_duration * 60)
            lines.append(f'tween_add("cam_x", camera, "x", camera.x + {action.camera_offset_x}, {frames}, "{action.camera_easing}")')
            lines.append(f'tween_add("cam_y", camera, "y", camera.y + {action.camera_offset_y}, {frames}, "{action.camera_easing}")')
        else:
            lines.append(f"camera.x = camera.x + {action.camera_offset_x}")
            lines.append(f"camera.y = camera.y + {action.camera_offset_y}")
        lines.append("camera_apply_bounds()")

    elif t == "camera_follow":
        target_var = _resolve_target_name(action.camera_follow_target_def_id, project) if project else _safe_name(action.camera_follow_target_def_id or "")
        if target_var:
            lines.append(f'camera.follow_target = "{target_var}"')
            lines.append(f"camera.follow_offset_x = {action.camera_follow_offset_x}")
            lines.append(f"camera.follow_offset_y = {action.camera_follow_offset_y}")
        else:
            lines.append("-- camera_follow: no target specified")

    elif t == "camera_stop_follow":
        lines.append("camera.follow_target = nil")

    elif t == "camera_reset":
        if action.camera_duration > 0:
            frames = int(action.camera_duration * 60)
            lines.append(f'tween_add("cam_x", camera, "x", 480, {frames}, "{action.camera_easing}")')
            lines.append(f'tween_add("cam_y", camera, "y", 272, {frames}, "{action.camera_easing}")')
        else:
            lines.append("camera.x = 480")
            lines.append("camera.y = 272")
        lines.append("camera.follow_target = nil")

    elif t == "camera_shake":
        intensity = action.shake_intensity
        duration  = action.shake_duration
        frames    = int(duration * 60)
        lines.append(f"shake_intensity = {intensity}")
        lines.append(f"shake_timer = {frames}")

    elif t == "camera_set_zoom":
        zoom = getattr(action, "camera_zoom_target", 1.0)
        lines.append(f"camera.zoom = {zoom}")
        lines.append("camera_apply_bounds()")

    elif t == "camera_zoom_to":
        zoom = getattr(action, "camera_zoom_target", 1.0)
        dur  = getattr(action, "camera_zoom_duration", 0.0)
        ease = getattr(action, "camera_zoom_easing", "linear")
        if dur > 0:
            frames = int(dur * 60)
            lines.append(f'tween_add("cam_zoom", camera, "zoom", {zoom}, {frames}, "{ease}")')
        else:
            lines.append(f"camera.zoom = {zoom}")
        lines.append("camera_apply_bounds()")

    elif t == "flash_screen":
        hex_color = (action.color or "#ffffff").lstrip("#")
        try:
            fr, fg, fb = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        except (ValueError, IndexError):
            fr, fg, fb = 255, 255, 255
        dur    = action.duration
        frames = max(1, int(float(dur) * 60))
        lines.append(f"flash_r        = {fr}")
        lines.append(f"flash_g        = {fg}")
        lines.append(f"flash_b        = {fb}")
        lines.append(f"flash_duration = {frames}")
        lines.append(f"flash_timer    = {frames}")

    elif t == "ani_play":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_frame        = 0")
            lines.append(f"{target}_frame_timer   = 0")
            lines.append(f"{target}_frame_loop    = true")
            lines.append(f"{target}_frame_playing = true")

    elif t == "ani_pause":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_frame_playing = false")

    elif t == "ani_stop":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_frame_playing = false")
            lines.append(f"{target}_frame        = 0")
            lines.append(f"{target}_frame_timer   = 0")

    elif t == "ani_set_frame":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        frame  = max(0, int(getattr(action, "ani_target_frame", 1)) - 1)
        if target:
            lines.append(f"{target}_frame        = {frame}")
            lines.append(f"{target}_frame_timer   = 0")
            lines.append(f"{target}_frame_playing = false")

    elif t == "ani_advance_frame":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        step   = int(action.ani_target_frame) if action.ani_target_frame != 0 else 1
        if target:
            lines.append(f"do")
            lines.append(f"    local _fc = 0")
            lines.append(f"    for _ in pairs({target}_frames) do _fc = _fc + 1 end")
            lines.append(f"    {target}_frame = {target}_frame + ({step})")
            lines.append(f"    if {target}_frame < 0 then {target}_frame = 0 end")
            lines.append(f"    if {target}_frame >= _fc then {target}_frame = _fc - 1 end")
            lines.append(f"    {target}_frame_timer   = 0")
            lines.append(f"    {target}_frame_playing = false")
            lines.append(f"end")
        else:
            lines.append("-- ani_advance_frame: no target specified")

    elif t == "ani_set_speed":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        fps    = action.ani_fps
        _tod   = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else obj_def
        if target and fps > 0:
            dur = max(1, round(60 / fps))
            if _tod and len(_tod.frames) > 1:
                for fi in range(len(_tod.frames)):
                    lines.append(f"if {target}_frames[{fi}] then {target}_frames[{fi}].dur = {dur} end")

    elif t == "ani_switch_slot":
        target    = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        slot_name = action.ani_slot_name or ""
        _tod      = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else obj_def
        if target and slot_name and _tod and _tod.behavior_type == "Animation":
            lines.append(f"do")
            lines.append(f"    local _new_id = {target}_ani_slots[{_lua_str(slot_name)}]")
            lines.append(f"    if _new_id then")
            lines.append(f"        {target}_ani_id      = _new_id")
            lines.append(f"        {target}_ani_slot_name = {_lua_str(slot_name)}")
            lines.append(f"        {target}_ani_frame   = 0")
            lines.append(f"        {target}_ani_timer   = 0")
            lines.append(f"        {target}_ani_done    = false")
            lines.append(f"        {target}_ani_playing = true")
            lines.append(f"    end")
            lines.append(f"end")

    elif t == "ani_set_flip":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_flip_h = {_lua_bool(action.ani_flip_h)}")
            lines.append(f"{target}_flip_v = {_lua_bool(action.ani_flip_v)}")

    elif t == "set_anim_speed":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        fps    = action.anim_fps
        _tod   = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else obj_def
        _is_ani_type = _tod and _tod.behavior_type == "Animation"
        if target:
            if _is_ani_type:
                lines.append(f"{target}_ani_fps = {fps}")
            else:
                # For regular objects, rewrite every frame's duration to match the requested FPS.
                # dur = ticks per frame = 60 / fps (clamped to minimum 1).
                if fps > 0:
                    dur = max(1, round(60 / fps))
                    _tod2 = _tod  # already resolved above
                    if _tod2 and len(_tod2.frames) > 1:
                        for fi in range(len(_tod2.frames)):
                            lines.append(f"if {target}_frames[{fi}] then {target}_frames[{fi}].dur = {dur} end")

    elif t == "play_anim":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        slot   = action.ani_slot_name or ""
        _tod   = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else obj_def
        _is_ani_type = _tod and _tod.behavior_type == "Animation"
        if target:
            if _is_ani_type:
                if slot:
                    lines.append(f"do")
                    lines.append(f"    local _new_id = {target}_ani_slots[{_lua_str(slot)}]")
                    lines.append(f"    if _new_id then")
                    lines.append(f"        {target}_ani_id = _new_id")
                    lines.append(f"        {target}_ani_slot_name = {_lua_str(slot)}")
                    lines.append(f"    end")
                    lines.append(f"end")
                lines.append(f"{target}_ani_frame   = 0")
                lines.append(f"{target}_ani_timer   = 0")
                lines.append(f"{target}_ani_done    = false")
                lines.append(f"{target}_ani_playing = true")
            else:
                lines.append(f"{target}_frame        = 0")
                lines.append(f"{target}_frame_timer   = 0")
                lines.append(f"{target}_frame_loop    = true")
                lines.append(f"{target}_frame_playing = true")

    elif t == "stop_anim":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        _tod   = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else obj_def
        _is_ani_type = _tod and _tod.behavior_type == "Animation"
        if target:
            if _is_ani_type:
                lines.append(f"{target}_ani_playing = false")
            else:
                lines.append(f"{target}_frame_playing = false")

    elif t == "layer_show":
        lname = _safe_name(action.layer_name or "")
        if lname:
            lines.append(f"layer_{lname}_visible = true")
        else:
            lines.append("-- layer_show: no layer name specified")

    elif t == "layer_hide":
        lname = _safe_name(action.layer_name or "")
        if lname:
            lines.append(f"layer_{lname}_visible = false")
        else:
            lines.append("-- layer_hide: no layer name specified")

    elif t == "layer_start_scroll":
        lname = _safe_name(action.layer_name or "")
        if lname:
            lines.append(f"if layer_{lname}_scroll_enabled ~= nil then")
            lines.append(f"    layer_{lname}_scroll_enabled = true")
            lines.append(f"end")
        else:
            lines.append("-- layer_start_scroll: no layer name specified")

    elif t == "layer_stop_scroll":
        lname = _safe_name(action.layer_name or "")
        if lname:
            lines.append(f"if layer_{lname}_scroll_enabled ~= nil then")
            lines.append(f"    layer_{lname}_scroll_enabled = false")
            lines.append(f"end")
        else:
            lines.append("-- layer_stop_scroll: no layer name specified")

    elif t == "layer_set_image":
        lname = _safe_name(action.layer_name or "")
        lines.append(f"-- layer_set_image: runtime image swap not yet supported for layer_{lname}")

    elif t == "set_scale" and obj_var:
        val = action.target_scale
        lines.append(f"{obj_var}_scale = {val}")

    elif t == "set_rotation" and obj_var:
        val = action.target_rotation
        lines.append(f"{obj_var}_rotation = {val}")

    elif t == "set_opacity" and obj_var:
        val = int(float(action.target_opacity) * 255)
        lines.append(f"{obj_var}_opacity = {val}")

    elif t == "scale_to" and obj_var:
        val    = action.target_scale
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        frames = max(1, int(float(dur) * 60))
        lines.append(f'tween_add("{obj_var}_scale", _G, "{obj_var}_scale", {val}, {frames}, "{easing}")')

    elif t == "rotate_to" and obj_var:
        val    = action.target_rotation
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        frames = max(1, int(float(dur) * 60))
        lines.append(f'tween_add("{obj_var}_rot", _G, "{obj_var}_rotation", {val}, {frames}, "{easing}")')

    elif t == "rotate_by" and obj_var:
        delta = action.target_rotation
        lines.append(f"{obj_var}_rotation = {obj_var}_rotation + {delta}")

    elif t == "slide_to" and obj_var:
        tx     = action.target_x
        ty     = action.target_y
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        frames = max(1, int(float(dur) * 60))
        lines.append(f'tween_add("{obj_var}_sx", _G, "{obj_var}_x", {tx}, {frames}, "{easing}")')
        lines.append(f'tween_add("{obj_var}_sy", _G, "{obj_var}_y", {ty}, {frames}, "{easing}")')

    elif t == "slide_by" and obj_var:
        dx     = action.offset_x
        dy     = action.offset_y
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        frames = max(1, int(float(dur) * 60))
        lines.append(f"do")
        lines.append(f'    tween_add("{obj_var}_sx", _G, "{obj_var}_x", {obj_var}_x + {dx}, {frames}, "{easing}")')
        lines.append(f'    tween_add("{obj_var}_sy", _G, "{obj_var}_y", {obj_var}_y + {dy}, {frames}, "{easing}")')
        lines.append(f"end")

    elif t == "return_to_start" and obj_var:
        dur    = action.duration
        easing = action.camera_easing
        if dur and float(dur) > 0:
            frames = max(1, int(float(dur) * 60))
            lines.append(f'tween_add("{obj_var}_sx", _G, "{obj_var}_x", {obj_var}_start_x, {frames}, "{easing}")')
            lines.append(f'tween_add("{obj_var}_sy", _G, "{obj_var}_y", {obj_var}_start_y, {frames}, "{easing}")')
        else:
            lines.append(f"{obj_var}_x = {obj_var}_start_x")
            lines.append(f"{obj_var}_y = {obj_var}_start_y")

    elif t == "spin" and obj_var:
        speed = action.spin_speed
        lines.append(f"{obj_var}_spin_speed = {speed}")

    elif t == "stop_spin" and obj_var:
        lines.append(f"{obj_var}_spin_speed = 0.0")

    elif t == "create_object":
        def_id = action.object_def_id or ""
        spawn_self = getattr(action, "spawn_at_self", False)
        off_x  = getattr(action, "spawn_offset_x", 0)
        off_y  = getattr(action, "spawn_offset_y", 0)
        tx     = action.target_x
        ty     = action.target_y
        if def_id and project:
            od = project.get_object_def(def_id)
            if od:
                iid   = f"{_safe_name(od.name)}_dyn_{def_id[:6]}"
                fname = ""
                if od.frames and od.frames[0].image_id:
                    img = project.get_image(od.frames[0].image_id)
                    if img and img.path:
                        fname = _asset_filename(img.path)
                if spawn_self and obj_var:
                    # Use the spawning object's dimensions for the pivot (center of the ship),
                    # not the bullet's dimensions. obj_def is the spawner, od is the bullet.
                    spawner_w = obj_def.width  if obj_def else od.width
                    spawner_h = obj_def.height if obj_def else od.height
                    ppiv_x = spawner_w / 2.0
                    ppiv_y = spawner_h / 2.0
                    if off_x or off_y:
                        lines.append(f"do")
                        lines.append(f"    local _srad = ({obj_var}_rotation or 0) * math.pi / 180")
                        lines.append(f"    local _sox  = {off_x} * math.cos(_srad) - {off_y} * math.sin(_srad)")
                        lines.append(f"    local _soy  = {off_x} * math.sin(_srad) + {off_y} * math.cos(_srad)")
                        x_expr = f"{obj_var}_x + {ppiv_x} + _sox"
                        y_expr = f"{obj_var}_y + {ppiv_y} + _soy"
                    else:
                        lines.append(f"do")
                        x_expr = f"{obj_var}_x + {ppiv_x}"
                        y_expr = f"{obj_var}_y + {ppiv_y}"
                else:
                    lines.append(f"do")
                    x_expr = str(tx + off_x) if off_x else str(tx)
                    y_expr = str(ty + off_y) if off_y else str(ty)
                lines.append(f'    local _iid = "{iid}_" .. tostring(os.clock()):gsub("%.", "")')
                lines.append(f"    _live_objects[_iid] = {{")
                lines.append(f"        def_id       = {_lua_str(def_id)},")
                lines.append(f"        x            = {x_expr},")
                lines.append(f"        y            = {y_expr},")
                lines.append(f"        visible      = true,")
                lines.append(f"        scale        = 1.0,")
                lines.append(f"        rotation     = 0.0,")
                lines.append(f"        opacity      = 255,")
                lines.append(f"        spin_speed   = 0.0,")
                lines.append(f"        interactable = true,")
                lines.append(f"        image        = {_lua_str(fname)},")
                bspd = getattr(action, "bullet_speed", 0) or 0
                if bspd and obj_var:
                    lines.append(f"        speed        = {bspd},")
                    lines.append(f"        angle        = ({obj_var}_rotation or 0),")
                else:
                    lines.append(f"        speed        = 0,")
                    lines.append(f"        angle        = 0,")
                lines.append(f"    }}")
                lines.append(f"    prim.register_spawned(_iid, {_lua_str(def_id)}, _live_objects[_iid])")
                # Register in parent system if a parent was specified
                parent_id = getattr(action, "parent_id", "")
                if parent_id and project:
                    pvar = _resolve_target_name(parent_id, project)
                    if pvar:
                        ipos = "true"  if getattr(action, "inherit_position",    True)  else "false"
                        irot = "true"  if getattr(action, "inherit_rotation",    False) else "false"
                        iscl = "true"  if getattr(action, "inherit_scale",       False) else "false"
                        dwp  = "true"  if getattr(action, "destroy_with_parent", False) else "false"
                        roff = getattr(action, "rotation_offset", 0.0)
                        lines.append(
                            f'    _parents[_iid] = {{parent_var="{pvar}", '
                            f'offset_x={off_x}, offset_y={off_y}, rotation_offset={roff}, '
                            f'inherit_position={ipos}, inherit_rotation={irot}, '
                            f'inherit_scale={iscl}, destroy_with_parent={dwp}}}'
                        )
                lines.append(f"end")
            else:
                lines.append(f"-- create_object: def {_lua_str(def_id)} not found")
        else:
            lines.append("-- create_object: no object_def_id specified")

    elif t == "destroy_object":
        def_id  = action.object_def_id or ""
        inst_id = action.instance_id or ""
        if inst_id:
            lines.append(f"prim.destroy_handle({_lua_str(inst_id)})")
        elif def_id and project:
            target_handles = _target_handles_for_action(action, project)
            if target_handles:
                for handle_expr in target_handles:
                    lines.append(f"prim.destroy_handle({handle_expr})")
            else:
                lines.append(f"-- destroy_object: def {_lua_str(def_id)} not found")
        else:
            lines.append("-- destroy_object: no target specified")

    elif t == "destroy_all_type":
        def_id = action.object_def_id or ""
        if def_id and project:
            lines.append("do")
            lines.append(f"    local _targets = prim.list_objects({{def_id = {_lua_str(def_id)}}})")
            lines.append("    prim.destroy_handles(_targets)")
            lines.append("end")
        else:
            lines.append("-- destroy_all_type: no object_def_id specified")

    elif t == "enable_interact" and obj_var:
        lines.append(f"{obj_var}_interactable = true")

    elif t == "disable_interact" and obj_var:
        lines.append(f"{obj_var}_interactable = false")

    elif t == "attach_to":
        parent_id = getattr(action, "parent_id", "")
        if parent_id and project and obj_var:
            parent_od = project.get_object_def(parent_id)
            child_od  = project.get_object_def(obj_def.id) if obj_def else None
            if parent_od:
                pvar      = _safe_name(parent_od.name)
                ox        = getattr(action, "offset_x", 0)
                oy        = getattr(action, "offset_y", 0)
                ipos      = "true"  if getattr(action, "inherit_position",    True)  else "false"
                irot      = "true"  if getattr(action, "inherit_rotation",    False) else "false"
                iscl      = "true"  if getattr(action, "inherit_scale",       False) else "false"
                dwp       = "true"  if getattr(action, "destroy_with_parent", False) else "false"
                roff      = getattr(action, "rotation_offset", 0.0)
                ppiv_x    = parent_od.width  / 2.0
                ppiv_y    = parent_od.height / 2.0
                cpiv_x    = child_od.width   / 2.0 if child_od else 0.0
                cpiv_y    = child_od.height  / 2.0 if child_od else 0.0
                lines.append(
                    f'_parents["{obj_var}"] = {{parent_var="{pvar}", '
                    f'offset_x={ox}, offset_y={oy}, rotation_offset={roff}, '
                    f'pivot_x={ppiv_x}, pivot_y={ppiv_y}, '
                    f'child_pivot_x={cpiv_x}, child_pivot_y={cpiv_y}, '
                    f'inherit_position={ipos}, inherit_rotation={irot}, '
                    f'inherit_scale={iscl}, destroy_with_parent={dwp}}}'
                )
            else:
                lines.append("-- attach_to: parent object not found")
        else:
            lines.append("-- attach_to: missing parent_id or context")

    elif t == "detach":
        if obj_var:
            lines.append(f'_parents["{obj_var}"] = nil')

    elif t == "if_variable":
        vn  = _safe_name(action.var_name) if action.var_name else "unknown"
        val = action.var_value if action.var_value else "0"
        op  = action.var_compare or "=="
        lines.append(f"if ({vn} or 0) {op} {val} then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_flag":
        bn  = _safe_name(action.bool_name) if action.bool_name else "unknown_flag"
        exp = "true" if action.bool_expected else "false"
        lines.append(f"if {bn} == {exp} then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_has_item":
        iname = _safe_name(action.item_name) if action.item_name else "unknown_item"
        lines.append(f"if inventory_has(\"{iname}\") then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "on_leave_save_scene":
        lines.append("if _save_scene_leaving then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        lines.append("end")

    elif t == "open_keyboard":
        request_id = str(_behavior_field(action, t, "request_id", "") or "")
        title = str(_behavior_field(action, t, "title", "") or "")
        target_var = str(_behavior_field(action, t, "target_var", "") or "")
        initial_text_var = str(_behavior_field(action, t, "initial_text_var", "") or "")
        max_length = int(_behavior_field(action, t, "max_length", 255) or 255)
        target_ident = _safe_name(target_var) if target_var else ""
        initial_ident = _safe_name(initial_text_var) if initial_text_var else ""
        initial_expr = f"({initial_ident} or \"\")" if initial_ident else "\"\""
        lines.append(
            f'app_ui_open_keyboard({_lua_str(request_id)}, {_lua_str(title)}, {_lua_str(target_ident)}, {initial_expr}, {max_length})'
        )

    elif t == "show_confirm":
        request_id = str(_behavior_field(action, t, "request_id", "") or "")
        message_text = str(_behavior_field(action, t, "message_text", "") or "")
        lines.append(f'app_ui_show_confirm({_lua_str(request_id)}, {_lua_str(message_text)})')

    elif t == "show_message":
        message_text = str(_behavior_field(action, t, "message_text", "") or "")
        lines.append(f'app_ui_show_message({_lua_str(message_text)})')

    elif t == "store_current_date":
        year_var = str(_behavior_field(action, t, "year_var", "") or "")
        month_var = str(_behavior_field(action, t, "month_var", "") or "")
        day_var = str(_behavior_field(action, t, "day_var", "") or "")
        weekday_var = str(_behavior_field(action, t, "weekday_var", "") or "")
        lines.append("do")
        lines.append("    local _weekday, _day, _month, _year = System.getDate()")
        if year_var:
            lines.append(f"    {_safe_name(year_var)} = _year or 0")
        if month_var:
            lines.append(f"    {_safe_name(month_var)} = _month or 0")
        if day_var:
            lines.append(f"    {_safe_name(day_var)} = _day or 0")
        if weekday_var:
            lines.append(f"    {_safe_name(weekday_var)} = _weekday or 0")
        lines.append("end")

    elif t == "store_current_time":
        hour_var = str(_behavior_field(action, t, "hour_var", "") or "")
        minute_var = str(_behavior_field(action, t, "minute_var", "") or "")
        second_var = str(_behavior_field(action, t, "second_var", "") or "")
        lines.append("do")
        lines.append("    local _hour, _minute, _second = System.getTime()")
        if hour_var:
            lines.append(f"    {_safe_name(hour_var)} = _hour or 0")
        if minute_var:
            lines.append(f"    {_safe_name(minute_var)} = _minute or 0")
        if second_var:
            lines.append(f"    {_safe_name(second_var)} = _second or 0")
        lines.append("end")

    elif t == "set_label_text":
        def_id = action.object_def_id or ""
        new_text = action.dialogue_text or ""
        targets = _scene_target_vars(def_id, project) if (project and def_id) else []
        if targets:
            for tgt in targets:
                lines.append(f"{tgt}_text = {_lua_str(new_text)}")
        else:
            lines.append("-- set_label_text: no label/button object specified")

    elif t == "set_label_text_var":
        def_id = action.object_def_id or ""
        vn = _safe_name(action.var_name or "")
        targets = _scene_target_vars(def_id, project) if (project and def_id) else []
        if targets and vn:
            for tgt in targets:
                lines.append(f'{tgt}_text = tostring({vn} or "")')
        else:
            lines.append("-- set_label_text_var: missing label/button or variable name")

    elif t == "set_label_color":
        def_id = action.object_def_id or ""
        hx = (action.color or "#ffffff").lstrip('#')
        try:
            cr, cg, cb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except (ValueError, IndexError):
            cr, cg, cb = 255, 255, 255
        targets = _scene_target_vars(def_id, project) if (project and def_id) else []
        if targets:
            for tgt in targets:
                lines.append(f"{tgt}_text_r = {cr}")
                lines.append(f"{tgt}_text_g = {cg}")
                lines.append(f"{tgt}_text_b = {cb}")
        else:
            lines.append("-- set_label_color: no label/button object specified")

    elif t == "set_label_size":
        def_id = action.object_def_id or ""
        size = action.frame_index
        targets = _scene_target_vars(def_id, project) if (project and def_id) else []
        if targets:
            for tgt in targets:
                lines.append(f"{tgt}_font_size = {size}")
        else:
            lines.append("-- set_label_size: no label/button object specified")

    elif t == "log_message":
        lines.append(f"-- LOG: {action.log_message}")

    elif t == "lua_code":
        snippet = (getattr(action, "lua_snippet", "") or "").strip()
        if snippet:
            lines.append("-- [lua_code node]")
            for lua_line in snippet.splitlines():
                lines.append(lua_line)
            lines.append("-- [/lua_code node]")
        else:
            lines.append("-- lua_code node: (empty)")

    elif t == "add_to_group":
        def_id = action.object_def_id or ""
        gname  = action.group_name or ""
        if def_id and gname and project:
            target_handles = _scene_target_handles(def_id, project)
            if target_handles:
                for handle in target_handles:
                    lines.append(f'group_add({_lua_str(gname)}, {_lua_str(handle)})')
            else:
                lines.append(f"-- add_to_group: object def {_lua_str(def_id)} not found")
        else:
            lines.append("-- add_to_group: missing object or group name")

    elif t == "remove_from_group":
        def_id = action.object_def_id or ""
        gname  = action.group_name or ""
        if def_id and gname and project:
            target_handles = _scene_target_handles(def_id, project)
            if target_handles:
                for handle in target_handles:
                    lines.append(f'group_remove({_lua_str(gname)}, {_lua_str(handle)})')
            else:
                lines.append(f"-- remove_from_group: object def {_lua_str(def_id)} not found")
        else:
            lines.append("-- remove_from_group: missing object or group name")

    elif t == "call_action_on_group":
        gname    = action.group_name or ""
        sub_type = action.group_action_type or ""
        if gname and sub_type:
            lines.append(f"do")
            lines.append(f"    local _g = _groups[{_lua_str(gname)}]")
            lines.append(f"    if _g then")
            lines.append(f"        for _gi = 1, #_g do")
            lines.append(f"            local _gv = _g[_gi]")
            if sub_type == "show_object":
                lines.append(f"            prim.set_visible(_gv, true)")
            elif sub_type == "hide_object":
                lines.append(f"            prim.set_visible(_gv, false)")
            elif sub_type == "destroy_object":
                lines.append(f"            prim.destroy_handle(_gv)")
            elif sub_type == "enable_interact":
                lines.append(f"            prim.set_interactable(_gv, true)")
            elif sub_type == "disable_interact":
                lines.append(f"            prim.set_interactable(_gv, false)")
            elif sub_type == "set_opacity":
                val = int(float(action.target_opacity) * 255)
                lines.append(f"            prim.set_opacity(_gv, {val})")
            elif sub_type == "set_scale":
                lines.append(f"            prim.set_scale(_gv, {action.target_scale})")
            elif sub_type == "set_rotation":
                lines.append(f"            prim.set_rotation(_gv, {action.target_rotation})")
            elif sub_type == "move_to":
                lines.append(f"            prim.set_position(_gv, {action.target_x}, {action.target_y})")
            elif sub_type == "move_by":
                lines.append(
                    f"            prim.set_position(_gv, (prim.get_x(_gv) or 0) + {action.offset_x}, "
                    f"(prim.get_y(_gv) or 0) + {action.offset_y})"
                )
            elif sub_type == "emit_signal":
                sig = getattr(action, "signal_name", "") or action.var_name or ""
                if sig:
                    lines.append(f'            emit_signal({_lua_str(sig)})')
                else:
                    lines.append(f'            -- call_action_on_group/emit_signal: no signal name')
            else:
                lines.append(f'            -- call_action_on_group: unsupported sub-type "{sub_type}"')
            lines.append(f"        end")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            lines.append("-- call_action_on_group: missing group name or action type")

    elif t == "if_in_group":
        def_id = action.object_def_id or ""
        gname  = action.group_name or ""
        if def_id and gname and project:
            od = project.get_object_def(def_id)
            target_vars = _scene_target_vars(def_id, project)
            target_handles = _scene_target_handles(def_id, project)
            if od and target_vars and target_handles:
                handle = target_handles[0]
                vname = target_vars[0]
                lines.append(f"if group_has({_lua_str(gname)}, {_lua_str(handle)}) then")
                for sa in action.true_actions:
                    for sl in _action_to_lua_inline(sa, vname, project, obj_def=od):
                        lines.append(f"    {sl}")
                if action.false_actions:
                    lines.append("else")
                    for sa in action.false_actions:
                        for sl in _action_to_lua_inline(sa, vname, project, obj_def=od):
                            lines.append(f"    {sl}")
                lines.append("end")
            else:
                lines.append(f"-- if_in_group: object def {_lua_str(def_id)} not found")
        else:
            lines.append("-- if_in_group: missing object or group name")

    elif t == "random_chance":
        chance = int(action.var_value) if action.var_value else 50
        lines.append(f"if math.random(1, 100) <= {chance} then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "random_set":
        vn = _safe_name(action.var_name) if action.var_name else "unknown"
        rmin = action.clamp_min if action.clamp_min else "1"
        rmax = action.clamp_max if action.clamp_max else "10"
        lines.append(f"{vn} = math.random({rmin}, {rmax})")

    elif t == "get_position":
        def_id = action.object_def_id or ""
        xvar = _safe_name(action.var_name) if action.var_name else "px"
        yvar = _safe_name(action.var_source) if action.var_source else "py"
        if def_id and project:
            tgt = _resolve_target_name(def_id, project)
        elif obj_var:
            tgt = obj_var
        else:
            tgt = ""
        if tgt:
            lines.append(f"{xvar} = {tgt}_x")
            lines.append(f"{yvar} = {tgt}_y")
        else:
            lines.append("-- get_position: no object context")

    elif t == "if_distance":
        def_id = action.object_def_id or ""
        threshold = action.var_value if action.var_value else "80"
        op = action.var_compare or "<="
        if def_id and project and obj_var:
            tgt = _resolve_target_name(def_id, project)
            if tgt:
                lines.append("do")
                lines.append(f"    local _dx = math.abs({obj_var}_x - {tgt}_x)")
                lines.append(f"    local _dy = math.abs({obj_var}_y - {tgt}_y)")
                lines.append(f"    local _dist = _dx + _dy")
                lines.append(f"    if _dist {op} {threshold} then")
                for sa in action.true_actions:
                    for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                        lines.append(f"        {sl}")
                if action.false_actions:
                    lines.append("    else")
                    for sa in action.false_actions:
                        for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                            lines.append(f"        {sl}")
                lines.append("    end")
                lines.append("end")
            else:
                lines.append(f"-- if_distance: target object not found")
        else:
            lines.append("-- if_distance: missing object or context")

    elif t == "get_distance":
        def_id = action.object_def_id or ""
        vn = _safe_name(action.var_name) if action.var_name else "dist"
        if def_id and project and obj_var:
            tgt = _resolve_target_name(def_id, project)
            if tgt:
                lines.append(f"{vn} = math.abs({obj_var}_x - {tgt}_x) + math.abs({obj_var}_y - {tgt}_y)")
            else:
                lines.append("-- get_distance: target object not found")
        else:
            lines.append("-- get_distance: missing object or context")

    elif t == "if_object_overlap":
        if obj_var and obj_def:
            current_def_id, current_frame, current_slot = _current_collision_state_expr(obj_var, obj_def)
            target_id = action.instance_id or action.object_def_id or ""
            source_role = getattr(action, "collision_source_role", "Hitbox") or "Hitbox"
            target_role = getattr(action, "collision_target_role", "Hurtbox") or "Hurtbox"
            lines.append("do")
            lines.append(f"    local _self_handle = prim.handle_from_var({_lua_str(obj_var)}) or \"__self__\"")
            lines.append(
                f"    local _overlap_now = any_object_overlap(_self_handle, {current_def_id}, {obj_var}_x, {obj_var}_y, "
                f"{current_slot}, {current_frame}, {_lua_str(target_id)}, {_lua_str(source_role)}, {_lua_str(target_role)})"
            )
            lines.append("    if _overlap_now then")
            for sa in action.true_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"        {sl}")
            if action.false_actions:
                lines.append("    else")
                for sa in action.false_actions:
                    for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                        lines.append(f"        {sl}")
            lines.append("    end")
            lines.append("end")
        else:
            lines.append("-- if_object_overlap: missing object context")

    elif t == "get_object_overlap_count":
        if obj_var and obj_def:
            current_def_id, current_frame, current_slot = _current_collision_state_expr(obj_var, obj_def)
            target_id = action.instance_id or action.object_def_id or ""
            source_role = getattr(action, "collision_source_role", "Hitbox") or "Hitbox"
            target_role = getattr(action, "collision_target_role", "Hurtbox") or "Hurtbox"
            result_var = _safe_name(action.var_name) if action.var_name else ""
            if result_var:
                lines.append("do")
                lines.append(f"    local _self_handle = prim.handle_from_var({_lua_str(obj_var)}) or \"__self__\"")
                lines.append(
                    f"    {result_var} = count_object_overlaps(_self_handle, {current_def_id}, {obj_var}_x, {obj_var}_y, "
                    f"{current_slot}, {current_frame}, {_lua_str(target_id)}, {_lua_str(source_role)}, {_lua_str(target_role)})"
                )
                lines.append("end")
            else:
                lines.append("-- get_object_overlap_count: missing result variable")
        else:
            lines.append("-- get_object_overlap_count: missing object context")

    elif t == "cancel_all":
        targets = _target_vars_for_action(action, project, obj_var)
        if targets:
            for tgt in targets:
                lines.append(f'tween_remove_prefix("{tgt}_")')
                lines.append(f'path_stop("{tgt}")')
                lines.append(f"{tgt}_wait_until = 0")
                lines.append(f"{tgt}_spin_speed = 0")
        else:
            lines.append("-- cancel_all: no object context")

    elif t == "follow_path":
        def_id = action.object_def_id or ""
        pname  = _safe_name(getattr(action, "path_name", "") or "")
        speed  = getattr(action, "path_speed", 1.0) or 1.0
        loop   = "true" if getattr(action, "path_loop", False) else "false"
        targets = _scene_target_vars(def_id, project) if (def_id and project) else []
        if targets and pname:
            for vname in targets:
                lines.append(f'path_start("{vname}", "{pname}", {speed}, {loop})')
        else:
            lines.append("-- follow_path: missing object or path name")

    elif t == "stop_path":
        def_id = action.object_def_id or ""
        targets = _scene_target_vars(def_id, project) if (def_id and project) else []
        if targets:
            for vname in targets:
                lines.append(f'path_stop("{vname}")')
        else:
            lines.append("-- stop_path: missing object")

    elif t == "resume_path":
        def_id = action.object_def_id or ""
        targets = _scene_target_vars(def_id, project) if (def_id and project) else []
        if targets:
            for vname in targets:
                lines.append(f'path_resume("{vname}")')
        else:
            lines.append("-- resume_path: missing object")

    elif t == "set_path_speed":
        def_id = action.object_def_id or ""
        speed  = getattr(action, "path_speed", 1.0) or 1.0
        targets = _scene_target_vars(def_id, project) if (def_id and project) else []
        if targets:
            for vname in targets:
                lines.append(f'path_set_speed("{vname}", {speed})')
        else:
            lines.append("-- set_path_speed: missing object")

    elif t == "wait":
        dur_ms = int(float(action.duration) * 1000)
        if obj_var:
            lines.append(f"{obj_var}_wait_until = Timer.getTime(_scene_timer) + {dur_ms}")
        else:
            lines.append(f"-- wait: no object context")

    elif t == "wait_for_input":
        if obj_var:
            lines.append(f"{obj_var}_waiting_input = true")
        else:
            lines.append(f"-- wait_for_input: no object context")

    elif t == "wait_random":
        wmin = int(float(action.duration) * 1000)
        wmax = int(float(getattr(action, "wait_max", 1.0)) * 1000)
        if wmax < wmin:
            wmax = wmin
        if obj_var:
            lines.append("do")
            lines.append(f"    local _wmin = {wmin}")
            lines.append(f"    local _wmax = {wmax}")
            lines.append(f"    {obj_var}_wait_until = Timer.getTime(_scene_timer) + math.random(_wmin, _wmax)")
            lines.append("end")
        else:
            lines.append("-- wait_random: no object context")

    elif t == "fade_in":
        dur_ms = int(float(action.duration) * 1000)
        lines.append(f"_fade_from     = 255")
        lines.append(f"_fade_to       = 0")
        lines.append(f"_fade_duration = {dur_ms}")
        lines.append(f"_fade_start    = Timer.getTime(_scene_timer)")
        lines.append(f"_fade_alpha    = 255")

    elif t == "fade_out":
        dur_ms = int(float(action.duration) * 1000)
        lines.append(f"_fade_from     = 0")
        lines.append(f"_fade_to       = 255")
        lines.append(f"_fade_duration = {dur_ms}")
        lines.append(f"_fade_start    = Timer.getTime(_scene_timer)")
        lines.append(f"_fade_alpha    = 0")

    elif t == "fade_in_object":
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        if target:
            frames = max(1, int(float(dur) * 60))
            lines.append(f'{target}_opacity = 0')
            lines.append(f'tween_add("{target}_fade", _G, "{target}_opacity", 255, {frames}, "{easing}")')
        else:
            lines.append("-- fade_in_object: no target specified")

    elif t == "fade_out_object":
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        dur    = action.duration
        easing = getattr(action, "easing", "") or action.camera_easing
        if target:
            frames = max(1, int(float(dur) * 60))
            lines.append(f'tween_add("{target}_fade", _G, "{target}_opacity", 0, {frames}, "{easing}")')
        else:
            lines.append("-- fade_out_object: no target specified")

    elif t == "set_frame":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        frame  = action.frame_index
        _tod   = _resolve_target_od(action.object_def_id, project) if (project and action.object_def_id) else None
        _is_ani_type = _tod and _tod.behavior_type == "Animation"
        if target:
            if _is_ani_type:
                lines.append(f"{target}_ani_frame = {frame}")
            else:
                lines.append(f"{target}_frame        = {frame}")
                lines.append(f"{target}_frame_timer   = 0")
                lines.append(f"{target}_frame_playing = false")
        else:
            lines.append("-- set_frame: no target specified")

    elif t == "advance_frame":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        step   = int(action.frame_index) if action.frame_index != 0 else 1
        if target:
            lines.append(f"do")
            lines.append(f"    local _ani_d = ani_data[{target}_ani_id]")
            lines.append(f"    if _ani_d then")
            lines.append(f"        {target}_ani_frame = {target}_ani_frame + ({step})")
            lines.append(f"        if {target}_ani_frame < 0 then {target}_ani_frame = 0 end")
            lines.append(f"        if {target}_ani_frame >= _ani_d.frame_count then {target}_ani_frame = _ani_d.frame_count - 1 end")
            lines.append(f"        {target}_ani_playing = false")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            lines.append("-- advance_frame: no target specified")

    elif t == "pause_music":
        lines.append("if current_music then Sound.pause(current_music) end")

    elif t == "resume_music":
        lines.append("if current_music then Sound.resume(current_music) end")

    elif t == "stop_all_sounds":
        lines.append("if current_music then Sound.close(current_music) end")
        lines.append("current_music = nil")

    elif t == "open_save_menu":
        lines.append("_prev_scene = current_scene")
        lines.append("current_scene = _SAVE_SCENE_NUM")
        lines.append("advance = true")

    elif t == "auto_save":
        lines.append('save_to_slot("auto", current_scene)')

    elif t == "load_save":
        slot = getattr(action, "slot_number", 1)
        lines.append(f"do")
        lines.append(f"    local _sc = load_from_slot({slot})")
        lines.append(f"    if _sc then")
        lines.append(f"        current_scene = _sc")
        lines.append(f"        advance = true")
        lines.append(f"    end")
        lines.append(f"end")

    # ── Layer Animation (paper doll) actions ─────────────────
    elif t == "layer_anim_play_macro":
        target = _resolve_layer_anim_target(action.layer_anim_id, project)
        macro  = _lua_str(action.layer_anim_macro_name or "")
        loop   = _lua_bool(action.layer_anim_macro_loop)
        if target:
            lines.append(f"pdoll_play_macro({target}_pdoll, {macro}, {loop})")

    elif t == "layer_anim_stop_macro":
        target = _resolve_layer_anim_target(action.layer_anim_id, project)
        macro  = _lua_str(action.layer_anim_macro_name or "")
        if target:
            lines.append(f"pdoll_stop_macro({target}_pdoll, {macro})")

    elif t == "layer_anim_set_blink":
        target  = _resolve_layer_anim_target(action.layer_anim_id, project)
        enabled = _lua_bool(action.layer_anim_enabled)
        if target:
            lines.append(f"{target}_pdoll.blink_enabled = {enabled}")

    elif t == "layer_anim_set_idle":
        target  = _resolve_layer_anim_target(action.layer_anim_id, project)
        enabled = _lua_bool(action.layer_anim_enabled)
        if target:
            lines.append(f"{target}_pdoll.idle_enabled = {enabled}")

    elif t == "layer_anim_set_talk":
        target  = _resolve_layer_anim_target(action.layer_anim_id, project)
        enabled = _lua_bool(action.layer_anim_enabled)
        if target:
            lines.append(f"{target}_pdoll.talk_enabled = {enabled}")

    elif t == "layer_anim_talk_for":
        target   = _resolve_layer_anim_target(action.layer_anim_id, project)
        duration = action.layer_anim_talk_duration
        if target:
            lines.append(f"{target}_pdoll.talk_timer = {duration}")
            lines.append(f"{target}_pdoll.talk_active = true")

    elif t in ("vn_dialog_sound", "vn_tw_sound"):
        pass  # handled at scene-level by VN typewriter/page logic

    elif t == "collision_set_cell":
        layer_id = action.collision_layer_id or ""
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        value_expr = str(1 if int(action.collision_value or 0) else 0)
        lines.append("do")
        lines.append(f"    prim.write_collision_cell({_lua_str(layer_id)}, {col_expr}, {row_expr}, {value_expr})")
        lines.append("end")

    elif t == "collision_toggle_cell":
        layer_id = action.collision_layer_id or ""
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        lines.append("do")
        lines.append(f"    prim.toggle_collision_cell({_lua_str(layer_id)}, {col_expr}, {row_expr})")
        lines.append("end")

    elif t == "collision_get_cell":
        layer_id = action.collision_layer_id or ""
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        result_var = _safe_name(action.grid_result_var.strip()) if action.grid_result_var.strip() else "collision_value"
        lines.append("do")
        lines.append(f"    {result_var} = prim.read_collision_cell({_lua_str(layer_id)}, {col_expr}, {row_expr}) or 0")
        lines.append("end")

    # ── Grid actions ─────────────────────────────────────────

    elif t == "grid_place_at":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        target_handles = _target_handles_for_action(action, project, obj_var)
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        if target_handles:
            for handle_expr in target_handles:
                lines.append("do")
                lines.append(f'    local _g = _scene_grids["{gname}"]')
                lines.append(f"    local _handle = {handle_expr}")
                lines.append(f"    if _g and _handle then")
                lines.append(f"        local _c = {col_expr}")
                lines.append(f"        local _r = {row_expr}")
                lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
                lines.append(f"            _g.cells[_r][_c] = _handle")
                lines.append(f"            prim.set_position(_handle, _g.ox + _c * _g.cw + math.floor(_g.cw / 2), _g.oy + _r * _g.ch + math.floor(_g.ch / 2))")
                lines.append(f"        end")
                lines.append(f"    end")
                lines.append("end")
        else:
            lines.append("-- grid_place_at: no target object")

    elif t == "grid_snap_to":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        target_handles = _target_handles_for_action(action, project, obj_var)
        if target_handles:
            for handle_expr in target_handles:
                lines.append("do")
                lines.append(f'    local _g = _scene_grids["{gname}"]')
                lines.append(f"    local _handle = {handle_expr}")
                lines.append(f"    if _g and _handle then")
                lines.append(f"        local _c = math.floor(((prim.get_x(_handle) or 0) - _g.ox) / _g.cw)")
                lines.append(f"        local _r = math.floor(((prim.get_y(_handle) or 0) - _g.oy) / _g.ch)")
                lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
                lines.append(f"            _g.cells[_r][_c] = _handle")
                lines.append(f"            prim.set_position(_handle, _g.ox + _c * _g.cw + math.floor(_g.cw / 2), _g.oy + _r * _g.ch + math.floor(_g.ch / 2))")
                lines.append(f"        end")
                lines.append(f"    end")
                lines.append("end")
        else:
            lines.append("-- grid_snap_to: no target object")

    elif t == "grid_get_cell":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        cv = _safe_name(action.grid_col_var.strip()) if action.grid_col_var.strip() else "grid_col"
        rv = _safe_name(action.grid_row_var.strip()) if action.grid_row_var.strip() else "grid_row"
        if target:
            lines.append("do")
            lines.append(f'    local _g = _scene_grids["{gname}"]')
            lines.append(f"    if _g then")
            lines.append(f"        {cv} = math.floor(({target}_x - _g.ox) / _g.cw)")
            lines.append(f"        {rv} = math.floor(({target}_y - _g.oy) / _g.ch)")
            lines.append(f"    end")
            lines.append("end")
        else:
            lines.append("-- grid_get_cell: no target object")

    elif t == "grid_get_at":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        rvar = _safe_name(action.grid_result_var.strip()) if action.grid_result_var.strip() else "grid_result"
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    local _occ = nil")
        lines.append(f"    if _g then")
        lines.append(f"        local _c = {col_expr}")
        lines.append(f"        local _r = {row_expr}")
        lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
        lines.append(f"            _occ = _g.cells[_r][_c]")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append(f"    {rvar} = _occ or \"\"")
        lines.append(f"    if _occ then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"        {sl}")
        if action.false_actions:
            lines.append(f"    else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"        {sl}")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_is_empty":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    local _empty = true")
        lines.append(f"    if _g then")
        lines.append(f"        local _c = {col_expr}")
        lines.append(f"        local _r = {row_expr}")
        lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
        lines.append(f"            _empty = (_g.cells[_r][_c] == nil)")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append(f"    if _empty then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"        {sl}")
        if action.false_actions:
            lines.append(f"    else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"        {sl}")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_get_neighbors":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        mode = action.grid_neighbor_mode or "4"
        if mode == "8":
            dirs = "{{-1,-1},{0,-1},{1,-1},{-1,0},{1,0},{-1,1},{0,1},{1,1}}"
        else:
            dirs = "{{0,-1},{-1,0},{1,0},{0,1}}"
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    if _g then")
        lines.append(f"        local _bc = {col_expr}")
        lines.append(f"        local _br = {row_expr}")
        lines.append(f"        local _dirs = {dirs}")
        lines.append(f"        for _di=1,#_dirs do")
        lines.append(f"            local _nc = _bc + _dirs[_di][1]")
        lines.append(f"            local _nr = _br + _dirs[_di][2]")
        lines.append(f"            if _nc >= 0 and _nc < _g.cols and _nr >= 0 and _nr < _g.rows then")
        lines.append(f"                local _nocc = _g.cells[_nr][_nc]")
        lines.append(f"                if _nocc then")
        for sa in action.sub_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"                    {sl}")
        lines.append(f"                end")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_for_each":
        gname = _safe_name(action.grid_name) if action.grid_name else "grid1"
        rvar  = _safe_name(action.grid_result_var.strip()) if action.grid_result_var.strip() else "grid_occ"
        cvout = _safe_name(action.grid_col_var.strip()) if action.grid_col_var.strip() else "grid_c"
        rvout = _safe_name(action.grid_row_var.strip()) if action.grid_row_var.strip() else "grid_r"
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    if _g then")
        lines.append(f"        for _r=0, _g.rows-1 do")
        lines.append(f"            for _c=0, _g.cols-1 do")
        lines.append(f"                local _occ = _g.cells[_r][_c]")
        lines.append(f"                if _occ then")
        lines.append(f"                    {rvar} = _occ")
        lines.append(f"                    {cvout} = _c")
        lines.append(f"                    {rvout} = _r")
        for sa in action.sub_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"                    {sl}")
        lines.append(f"                end")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_clear_cell":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    if _g then")
        lines.append(f"        local _c = {col_expr}")
        lines.append(f"        local _r = {row_expr}")
        lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
        lines.append(f"            _g.cells[_r][_c] = nil")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_clear_all":
        gname = _safe_name(action.grid_name) if action.grid_name else "grid1"
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    if _g then")
        lines.append(f"        for _r=0, _g.rows-1 do")
        lines.append(f"            for _c=0, _g.cols-1 do")
        lines.append(f"                _g.cells[_r][_c] = nil")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

    elif t == "grid_move":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        target_handles = _target_handles_for_action(action, project, obj_var)
        direction = action.grid_direction or "right"
        dist = action.grid_distance or 1
        dc, dr = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(direction, (1, 0))
        if target_handles:
            for handle_expr in target_handles:
                lines.append("do")
                lines.append(f'    local _g = _scene_grids["{gname}"]')
                lines.append(f"    local _handle = {handle_expr}")
                lines.append(f"    if _g and _handle then")
                lines.append(f"        local _fc, _fr = nil, nil")
                lines.append(f"        for _r=0, _g.rows-1 do")
                lines.append(f"            for _c=0, _g.cols-1 do")
                lines.append(f"                if _g.cells[_r][_c] == _handle then _fc = _c; _fr = _r end")
                lines.append(f"            end")
                lines.append(f"        end")
                lines.append(f"        if _fc then")
                lines.append(f"            local _nc = _fc + {dc * dist}")
                lines.append(f"            local _nr = _fr + {dr * dist}")
                lines.append(f"            if _nc >= 0 and _nc < _g.cols and _nr >= 0 and _nr < _g.rows and _g.cells[_nr][_nc] == nil then")
                lines.append(f"                _g.cells[_fr][_fc] = nil")
                lines.append(f"                _g.cells[_nr][_nc] = _handle")
                lines.append(f"                prim.set_position(_handle, _g.ox + _nc * _g.cw + math.floor(_g.cw / 2), _g.oy + _nr * _g.ch + math.floor(_g.ch / 2))")
                lines.append(f"            end")
                lines.append(f"        end")
                lines.append(f"    end")
                lines.append("end")
        else:
            lines.append("-- grid_move: no target object")

    elif t == "grid_swap":
        gname = _safe_name(action.grid_name) if action.grid_name else "grid1"
        cv1 = action.grid_col_var.strip()
        rv1 = action.grid_row_var.strip()
        cv2 = action.grid_col2_var.strip()
        rv2 = action.grid_row2_var.strip()
        c1_expr = _safe_name(cv1) if cv1 else str(action.grid_col)
        r1_expr = _safe_name(rv1) if rv1 else str(action.grid_row)
        c2_expr = _safe_name(cv2) if cv2 else str(action.grid_col2)
        r2_expr = _safe_name(rv2) if rv2 else str(action.grid_row2)
        lines.append("do")
        lines.append(f'    local _g = _scene_grids["{gname}"]')
        lines.append(f"    if _g then")
        lines.append(f"        local _c1 = {c1_expr}")
        lines.append(f"        local _r1 = {r1_expr}")
        lines.append(f"        local _c2 = {c2_expr}")
        lines.append(f"        local _r2 = {r2_expr}")
        lines.append(f"        if _c1 >= 0 and _c1 < _g.cols and _r1 >= 0 and _r1 < _g.rows")
        lines.append(f"           and _c2 >= 0 and _c2 < _g.cols and _r2 >= 0 and _r2 < _g.rows then")
        lines.append(f"            local _tmp = _g.cells[_r1][_c1]")
        lines.append(f"            _g.cells[_r1][_c1] = _g.cells[_r2][_c2]")
        lines.append(f"            _g.cells[_r2][_c2] = _tmp")
        lines.append(f"            if _g.cells[_r1][_c1] then")
        lines.append(f"                prim.set_position(_g.cells[_r1][_c1], _g.ox + _c1 * _g.cw + math.floor(_g.cw / 2), _g.oy + _r1 * _g.ch + math.floor(_g.ch / 2))")
        lines.append(f"            end")
        lines.append(f"            if _g.cells[_r2][_c2] then")
        lines.append(f"                prim.set_position(_g.cells[_r2][_c2], _g.ox + _c2 * _g.cw + math.floor(_g.cw / 2), _g.oy + _r2 * _g.ch + math.floor(_g.ch / 2))")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

    elif t == "set_focus":
        handles = _scene_target_handles(action.focus_target_object_id, project) if action.focus_target_object_id else []
        if handles:
            handle = handles[0]
            lines.append(f"if prim.get_visible({_lua_str(handle)}) then")
            lines.append(f"    if _focused_obj ~= {_lua_str(handle)} then")
            lines.append(f"        _focused_obj = {_lua_str(handle)}")
            lines.append(f"        _focus_selected_obj = {_lua_str(handle)}")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            lines.append("-- set_focus: no target object specified")

    elif t == "activate_focused_object":
        lines.append("if _focused_obj then _focus_activated_obj = _focused_obj end")

    # ── S10: 3D door / object / tile-check actions ─────────────────────────
    elif t in ("open_door", "close_door", "toggle_door"):
        _door_mode  = getattr(action, "door_target_mode", "coords") or "coords"
        _door_col   = int(getattr(action, "door_col", 0) or 0)
        _door_row   = int(getattr(action, "door_row", 0) or 0)
        _door_tag   = getattr(action, "door_tag", "") or ""
        # Map action type → Lua state string
        _state_str  = {"open_door": "\"open\"", "close_door": "\"closed\"",
                       "toggle_door": "\"toggle\""}[t]
        if _door_mode == "tag" and _door_tag:
            # Tag mode: iterate _tile_meta looking for matching tag entries.
            # _setDoorStateByTag is emitted once per scene by
            # _emit_3d_door_helpers when any door action is present.
            lines.append(f"_setDoorStateByTag({_lua_str(_door_tag)}, {_state_str})")
        else:
            # Coords mode: direct cell mutation via _setDoorState helper.
            lines.append(f"_setDoorState({_door_col}, {_door_row}, {_state_str})")

    elif t == "move_3d_object":
        _obj_id = getattr(action, "obj_3d_id", "") or ""
        _wx     = float(getattr(action, "obj_3d_wx", 0.0) or 0.0)
        _wy     = float(getattr(action, "obj_3d_wy", 0.0) or 0.0)
        if _obj_id:
            _targets = _scene_target_vars(_obj_id, project)
            if _targets:
                for _target in _targets:
                    lines.append(f"{_target}_x = {_wx}")
                    lines.append(f"{_target}_y = {_wy}")
                if _is_3d_export_context(project):
                    for _target_id in _scene_target_handles(_obj_id, project):
                        lines.append(f"actor3d_set_pos({_lua_str(_target_id)}, {_wx}, {_wy})")
            else:
                lines.append(f"RayCast3D.moveObject({_lua_str(_obj_id)}, {_wx}, {_wy})")
        else:
            lines.append("-- move_3d_object: no object id set")

    elif t == "set_3d_object_visible":
        _obj_id  = getattr(action, "obj_3d_id", "") or ""
        _visible = bool(getattr(action, "obj_3d_visible", True))
        if _obj_id:
            _targets = _scene_target_vars(_obj_id, project)
            if _targets:
                for _target in _targets:
                    lines.append(f"{_target}_visible = {_lua_bool(_visible)}")
                if _is_3d_export_context(project):
                    for _target_id in _scene_target_handles(_obj_id, project):
                        lines.append(f"actor3d_set_visible({_lua_str(_target_id)}, {_lua_bool(_visible)})")
            else:
                _fn = "showObject" if _visible else "hideObject"
                lines.append(f"RayCast3D.{_fn}({_lua_str(_obj_id)})")
        else:
            lines.append("-- set_3d_object_visible: no object id set")

    elif t == "actor3d_start_patrol":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_start_patrol: only valid in 3D scenes")
        else:
            _pname = _safe_name(getattr(action, "path_name", "") or "")
            _speed = getattr(action, "path_speed", 1.0) or 1.0
            _loop = "true" if getattr(action, "path_loop", False) else "false"
            if _pname:
                _emit_3d_actor_call(
                    lines,
                    action,
                    project,
                    obj_var,
                    lambda _target: [f"actor3d_start_patrol({_target}, {_lua_str(_pname)}, {_speed}, {_loop})"],
                    "-- actor3d_start_patrol: missing actor target",
                )
            else:
                lines.append("-- actor3d_start_patrol: missing path name")

    elif t == "actor3d_stop_patrol":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_stop_patrol: only valid in 3D scenes")
        else:
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_stop_patrol({_target})"],
                "-- actor3d_stop_patrol: missing actor target",
            )

    elif t == "actor3d_resume_patrol":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_resume_patrol: only valid in 3D scenes")
        else:
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_resume_patrol({_target})"],
                "-- actor3d_resume_patrol: missing actor target",
            )

    elif t == "actor3d_set_patrol_enabled":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_patrol_enabled: only valid in 3D scenes")
        else:
            _enabled = _lua_bool(bool(getattr(action, "actor_3d_patrol_enabled", True)))
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_set_patrol_enabled({_target}, {_enabled})"],
                "-- actor3d_set_patrol_enabled: missing actor target",
            )

    elif t == "actor3d_set_state":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_state: only valid in 3D scenes")
        else:
            _state = getattr(action, "actor_3d_state", "") or ""
            if _state:
                _emit_3d_actor_call(
                    lines,
                    action,
                    project,
                    obj_var,
                    lambda _target: [f"actor3d_set_state({_target}, {_lua_str(_state)})"],
                    "-- actor3d_set_state: missing actor target",
                )
            else:
                lines.append("-- actor3d_set_state: missing state")

    elif t == "actor3d_set_angle":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_angle: only valid in 3D scenes")
        else:
            _angle = float(getattr(action, "actor_3d_angle", 0.0) or 0.0)
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_set_angle({_target}, {_angle})"],
                "-- actor3d_set_angle: missing actor target",
            )

    elif t == "actor3d_face_player":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_face_player: only valid in 3D scenes")
        else:
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_face_player({_target})"],
                "-- actor3d_face_player: missing actor target",
            )

    elif t == "actor3d_set_alive":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_alive: only valid in 3D scenes")
        else:
            _alive = _lua_bool(bool(getattr(action, "actor_3d_alive", True)))
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_set_alive({_target}, {_alive})"],
                "-- actor3d_set_alive: missing actor target",
            )

    elif t == "actor3d_kill":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_kill: only valid in 3D scenes")
        else:
            _death_state = getattr(action, "actor_3d_state", "") or "dead"
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_kill({_target}, {_lua_str(_death_state)})"],
                "-- actor3d_kill: missing actor target",
            )

    elif t == "actor3d_set_blocking":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_blocking: only valid in 3D scenes")
        else:
            _blocking = _lua_bool(bool(getattr(action, "actor_3d_blocking", True)))
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_set_blocking({_target}, {_blocking})"],
                "-- actor3d_set_blocking: missing actor target",
            )

    elif t == "actor3d_set_interactable":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_set_interactable: only valid in 3D scenes")
        else:
            _interactable = _lua_bool(bool(getattr(action, "actor_3d_interactable", True)))
            _emit_3d_actor_call(
                lines,
                action,
                project,
                obj_var,
                lambda _target: [f"actor3d_set_interactable({_target}, {_interactable})"],
                "-- actor3d_set_interactable: missing actor target",
            )

    elif t == "actor3d_get_distance_to_player":
        if not _is_3d_export_context(project):
            lines.append("-- actor3d_get_distance_to_player: only valid in 3D scenes")
        else:
            _result_var = _safe_name(action.var_name) if action.var_name else ""
            if not _result_var:
                lines.append("-- actor3d_get_distance_to_player: missing result variable")
            else:
                _targets = []
                if project:
                    if action.instance_id:
                        _targets = _scene_target_handles(action.instance_id, project)
                    elif action.object_def_id:
                        _targets = _scene_target_handles(action.object_def_id, project)
                if _targets:
                    lines.append(f"{_result_var} = actor3d_distance_to_player({_lua_str(_targets[0])})")
                elif obj_var:
                    lines.append("do")
                    lines.append(f"    local _actor3d_id = actor3d_id_from_var({_lua_str(obj_var)})")
                    lines.append("    if _actor3d_id then")
                    lines.append(f"        {_result_var} = actor3d_distance_to_player(_actor3d_id)")
                    lines.append("    end")
                    lines.append("end")
                else:
                    lines.append("-- actor3d_get_distance_to_player: missing actor target")

    elif t in ("if_actor3d_player_in_range", "if_actor3d_player_in_sight", "if_actor3d_alive"):
        if not _is_3d_export_context(project):
            lines.append(f"-- {t}: only valid in 3D scenes")
        else:
            _range = float(getattr(action, "actor_3d_query_range", 0.0) or 0.0)
            _targets = []
            if project:
                if action.instance_id:
                    _targets = _scene_target_handles(action.instance_id, project)
                elif action.object_def_id:
                    _targets = _scene_target_handles(action.object_def_id, project)
            lines.append("do")
            lines.append("    local _actor3d_ok = false")
            if _targets:
                for _target_id in _targets:
                    if t == "if_actor3d_player_in_range":
                        lines.append(f"    if actor3d_distance_to_player({_lua_str(_target_id)}) <= ({_range} > 0 and {_range} or ((actor3d_get({_lua_str(_target_id)}) and actor3d_get({_lua_str(_target_id)}).attack_range) or math.huge)) then _actor3d_ok = true end")
                    elif t == "if_actor3d_player_in_sight":
                        lines.append(f"    if actor3d_can_see_player({_lua_str(_target_id)}, {_range}) then _actor3d_ok = true end")
                    else:
                        lines.append(f"    if actor3d_is_alive({_lua_str(_target_id)}) then _actor3d_ok = true end")
            elif obj_var:
                lines.append(f"    local _actor3d_id = actor3d_id_from_var({_lua_str(obj_var)})")
                lines.append("    if _actor3d_id then")
                if t == "if_actor3d_player_in_range":
                    lines.append(f"        if actor3d_distance_to_player(_actor3d_id) <= ({_range} > 0 and {_range} or ((actor3d_get(_actor3d_id) and actor3d_get(_actor3d_id).attack_range) or math.huge)) then _actor3d_ok = true end")
                elif t == "if_actor3d_player_in_sight":
                    lines.append(f"        if actor3d_can_see_player(_actor3d_id, {_range}) then _actor3d_ok = true end")
                else:
                    lines.append("        if actor3d_is_alive(_actor3d_id) then _actor3d_ok = true end")
                lines.append("    end")
            else:
                lines.append(f"    -- {t}: missing actor target")
            lines.append("    if _actor3d_ok then")
            for sa in (action.true_actions or []):
                if isinstance(sa, dict):
                    from models import BehaviorAction as _BA
                    sa = _BA.from_dict(sa)
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"        {sl}")
            if action.false_actions:
                lines.append("    else")
                for sa in (action.false_actions or []):
                    if isinstance(sa, dict):
                        from models import BehaviorAction as _BA
                        sa = _BA.from_dict(sa)
                    for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                        lines.append(f"        {sl}")
            lines.append("    end")
            lines.append("end")

    elif t == "check_player_tile":
        # Branch node — emits a do...end block with an if guard.
        # Caller wraps true_actions / false_actions; this emits the condition
        # block and the true branch only (false branch appended by the standard
        # branch machinery in the behavior emit loop, same as if_variable etc.).
        _where     = getattr(action, "player_tile_where", "under_player") or "under_player"
        _tile_type = getattr(action, "player_tile_type",  "empty")        or "empty"
        # Tile size is baked as a literal; we need it at emit time.
        # It isn't available on the action itself — we pass it via the project
        # or fall back to the common default. The caller always has project; we
        # guard gracefully if not.
        _ts = 64  # fallback
        if project:
            for _sc in project.scenes:
                if hasattr(_sc, "map_data") and _sc.map_data:
                    _ts = _sc.map_data.tile_size or 64
                    break
        lines.append("do")
        if _where == "facing_tile":
            lines.append("    local _cpt = RayCast3D.getFacingTile()")
            lines.append("    local _cpt_col = _cpt and _cpt.x")
            lines.append("    local _cpt_row = _cpt and _cpt.y")
        else:  # under_player
            lines.append(f"    local _cpt_pl  = RayCast3D.getPlayer()")
            lines.append(f"    local _cpt_col = math.floor(_cpt_pl.x / {_ts})")
            lines.append(f"    local _cpt_row = math.floor(_cpt_pl.y / {_ts})")
        lines.append("    local _cpt_meta = (_cpt_col and _cpt_row) and RayCast3D.getTileMeta(_cpt_col, _cpt_row) or nil")
        # Build the condition expression for the requested tile type
        if _tile_type == "empty":
            # Empty = no meta AND map cell is 0 (passable, no wall)
            lines.append("    local _cpt_ok = (_cpt_meta == nil) and")
            lines.append(f"        (_cpt_col and _cpt_row and (map[_cpt_row * {_ts} + _cpt_col + 1] or 0) == 0 or false)")
        elif _tile_type == "wall":
            # Wall = no meta AND map cell is solid (non-zero)
            lines.append("    local _cpt_ok = (_cpt_meta == nil) and")
            lines.append(f"        (_cpt_col and _cpt_row and (map[_cpt_row * {_ts} + _cpt_col + 1] or 0) ~= 0 or false)")
        else:
            # Meta type: door / exit / trigger / switch
            lines.append(f"    local _cpt_ok = _cpt_meta ~= nil and _cpt_meta.type == {_lua_str(_tile_type)}")
        lines.append("    if _cpt_ok then")
        # true_actions are emitted by the branch machinery that calls us;
        # we push a sentinel comment so the branch loop knows where to splice.
        # In practice _action_to_lua_inline is called for leaf actions, and
        # check_player_tile is a BRANCH_TYPE so the outer emit loop handles
        # true_actions / false_actions — we just emit the open block here.
        # The "end" for the if and the do are closed by the branch emit loop
        # via the _emit_branch_tail helper, same as if_variable.
        # We append them explicitly here because _action_to_lua_inline is used
        # directly in _obj_dispatch where the branch machinery isn't present.
        for sa in (action.true_actions or []):
            if isinstance(sa, dict):
                from models import BehaviorAction as _BA
                sa = _BA.from_dict(sa)
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"        {sl}")
        lines.append("    end")
        lines.append("end")

    else:
        registry = _plugin_registry(project)
        descriptor = registry.get_action_descriptor(t) if registry else None
        if descriptor:
            for line in descriptor["lua_export"](action, obj_var, project) or []:
                lines.append(str(line))
        elif t not in ("none", ""):
            lines.append(f"-- [{t}] not yet implemented in LPP exporter")

    return lines


# ─────────────────────────────────────────────────────────────
#  ANIMATION SYSTEM — embedded in index.lua
# ─────────────────────────────────────────────────────────────

def _make_ani_lib() -> str:
    lines = [
        "-- Animation helpers",
        "ani_data   = {}",
        "ani_sheets = {}",
        "trans_data   = {}",
        "trans_sheets = {}",
        "",
        "function ani_get_sheet_and_rect(ani_id, frame)",
        "    local data = ani_data[ani_id]",
        "    if not data then return nil, 0, 0, 64, 64 end",
        "    local sheets = ani_sheets[ani_id]",
        "    if not sheets then return nil, 0, 0, 64, 64 end",
        "    local fpg = data.frames_per_sheet or data.frame_count",
        "    local si  = math.floor(frame / fpg) + 1",
        "    if si > #sheets then si = #sheets end",
        "    local lf  = frame - (si - 1) * fpg",
        "    local cols = math.floor(data.sheet_width / data.frame_width)",
        "    if cols < 1 then cols = 1 end",
        "    local col = lf % cols",
        "    local row = math.floor(lf / cols)",
        "    return sheets[si], col * data.frame_width, row * data.frame_height,",
        "           data.frame_width, data.frame_height",
        "end",
        "",
        "function ani_draw(ani_id, frame, x, y)",
        "    local sheet, sx, sy, sw, sh = ani_get_sheet_and_rect(ani_id, frame)",
        "    if not sheet then return end",
        "    Graphics.drawPartialImage(x, y, sheet, sx, sy, sw, sh)",
        "end",
        "",
        "local function trans_draw_frame(trans_id, frame)",
        "    local sheet = trans_sheets[trans_id]",
        "    local data  = trans_data[trans_id]",
        "    if not sheet or not data then return end",
        "    local fw      = data.frame_width  or 240",
        "    local fh      = data.frame_height or 136",
        "    local cols    = math.floor(data.sheet_width / fw)",
        "    if cols < 1 then cols = 1 end",
        "    local col     = frame % cols",
        "    local row     = math.floor(frame / cols)",
        "    local x_scale = 960 / fw",
        "    local y_scale = 544 / fh",
        "    local draw_x  = -(col * 960)",
        "    local draw_y  = -(row * 544)",
        "    Graphics.drawScaleImage(draw_x, draw_y, sheet, x_scale, y_scale, Color.new(255, 255, 255, 255))",
        "end",
        "",
        "function play_transition(trans_id, fps_override)",
        "    local data = trans_data[trans_id]",
        "    if not data then return end",
        "    local fps      = fps_override or data.fps or 12",
        "    local frame_ms = math.floor(1000 / fps)",
        "    local frame    = 0",
        "    local t        = Timer.new()",
        "    Timer.reset(t)",
        "    while frame < data.frame_count do",
        "        if Timer.getTime(t) >= frame_ms then",
        "            Timer.reset(t)",
        "            frame = frame + 1",
        "        end",
        "        Graphics.initBlend()",
        "        trans_draw_frame(trans_id, frame)",
        "        Graphics.termBlend()",
        "        Screen.flip()",
        "    end",
        "    Timer.destroy(t)",
        "end",
    ]
    return "\n".join(lines)


def _make_pdoll_lib() -> str:
    """Emit the Lua runtime library for paper doll (layer animation) objects."""
    lines = [
        "-- Paper doll (layer animation) helpers",
        "pdoll_defs = {}",
        "",
        "-- Deep-copy a layer tree so each instance has its own runtime state",
        "local function pdoll_copy_layers(src)",
        "    local out = {}",
        "    for i = 1, #src do",
        "        local s = src[i]",
        "        out[i] = {",
        "            id       = s.id,",
        "            name     = s.name,",
        "            image    = s.image,",
        "            origin_x = s.origin_x, origin_y = s.origin_y,",
        "            x = s.x, y = s.y,",
        "            rotation = s.rotation, scale = s.scale,",
        "            -- runtime overrides from macros",
        "            dx = 0, dy = 0, drot = 0, dscale = 0,",
        "            -- image swap (blink / mouth)",
        "            base_image = s.image,",
        "            children = pdoll_copy_layers(s.children or {}),",
        "        }",
        "    end",
        "    return out",
        "end",
        "",
        "function pdoll_create(doll_id)",
        "    local def = pdoll_defs[doll_id]",
        "    if not def then return nil end",
        "    local p = {",
        "        def_id        = doll_id,",
        "        layers        = pdoll_copy_layers(def.layers or {}),",
        "        blink_enabled = false,",
        "        talk_enabled  = false,",
        "        idle_enabled  = false,",
        "        -- blink state",
        "        blink_timer   = 0,",
        "        blink_next    = 2 + math.random() * 3,",
        "        blink_active  = false,",
        "        blink_dur     = 0,",
        "        -- talk state",
        "        talk_active   = false,",
        "        talk_timer    = 0,",
        "        talk_cycle    = 0,",
        "        talk_open     = false,",
        "        talk_shape_index = 1,",
        "        -- idle state",
        "        idle_time     = 0,",
        "        -- one-frame hook events",
        "        event_blink      = false,",
        "        event_talk_step  = false,",
        "        event_idle_cycle = false,",
        "        -- macro state",
        "        active_macros = {},",
        "    }",
        "    return p",
        "end",
        "",
        "local function pdoll_find_layer(layers, layer_id)",
        "    for i = 1, #layers do",
        "        if layers[i].id == layer_id then return layers[i] end",
        "        local found = pdoll_find_layer(layers[i].children, layer_id)",
        "        if found then return found end",
        "    end",
        "    return nil",
        "end",
        "",
        "function pdoll_play_macro(p, macro_name, should_loop)",
        "    if not p then return end",
        "    local def = pdoll_defs[p.def_id]",
        "    if not def or not def.macros or not def.macros[macro_name] then return end",
        "    local mdef = def.macros[macro_name]",
        "    p.active_macros[macro_name] = {",
        "        name     = macro_name,",
        "        time     = 0,",
        "        duration = mdef.duration,",
        "        loop     = should_loop or mdef.loop,",
        "        kf       = mdef.keyframes,",
        "    }",
        "end",
        "",
        "function pdoll_stop_macro(p, macro_name)",
        "    if not p then return end",
        "    p.active_macros[macro_name] = nil",
        "    -- reset layer deltas",
        "    local function reset_deltas(layers)",
        "        for i = 1, #layers do",
        "            layers[i].dx = 0",
        "            layers[i].dy = 0",
        "            layers[i].drot = 0",
        "            layers[i].dscale = 0",
        "            reset_deltas(layers[i].children)",
        "        end",
        "    end",
        "    reset_deltas(p.layers)",
        "end",
        "",
        "function pdoll_update(p, dt)",
        "    if not p then return end",
        "    local def = pdoll_defs[p.def_id]",
        "    if not def then return end",
        "    p.event_blink = false",
        "    p.event_talk_step = false",
        "    p.event_idle_cycle = false",
        "",
        "    -- Blink",
        "    if p.blink_enabled and def.blink then",
        "        local blink_hook_mode = def.blink.hook_mode or 'builtin'",
        "        local bl = nil",
        "        if def.blink.layer_id ~= '' then",
        "            bl = pdoll_find_layer(p.layers, def.blink.layer_id)",
        "        end",
        "        local blink_has_visual = bl and def.blink.alt_image and images[def.blink.alt_image]",
        "        if blink_hook_mode ~= 'builtin' or blink_has_visual then",
        "            if p.blink_active then",
        "                p.blink_dur = p.blink_dur + dt",
        "                if p.blink_dur >= def.blink.duration then",
        "                    if blink_has_visual and blink_hook_mode ~= 'replace' then",
        "                        bl.image = bl.base_image",
        "                    end",
        "                    p.blink_active = false",
        "                    p.blink_timer  = 0",
        "                    p.blink_next   = def.blink.interval_min + math.random() * (def.blink.interval_max - def.blink.interval_min)",
        "                end",
        "            else",
        "                p.blink_timer = p.blink_timer + dt",
        "                if p.blink_timer >= p.blink_next then",
        "                    if blink_has_visual and blink_hook_mode ~= 'replace' then",
        "                        bl.image = def.blink.alt_image",
        "                    end",
        "                    p.blink_active = true",
        "                    p.blink_dur    = 0",
        "                    if blink_hook_mode ~= 'builtin' then",
        "                        p.event_blink = true",
        "                    end",
        "                end",
        "            end",
        "        end",
        "    end",
        "",
        "    -- Talk (mouth cycle)",
        "    if p.talk_enabled and p.talk_active and def.mouth then",
        "        local talk_hook_mode = def.mouth.hook_mode or 'builtin'",
        "        local talk_images = def.mouth.images or {}",
        "        local talk_has_shapes = #talk_images > 0",
        "        local ml = nil",
        "        if def.mouth.layer_id ~= '' then",
        "            ml = pdoll_find_layer(p.layers, def.mouth.layer_id)",
        "        end",
        "        if def.mouth.cycle_speed > 0 and (talk_hook_mode ~= 'builtin' or (ml and talk_has_shapes)) then",
        "            p.talk_cycle = p.talk_cycle + dt",
        "            if p.talk_cycle >= def.mouth.cycle_speed then",
        "                p.talk_cycle = 0",
        "                if p.talk_open then",
        "                    p.talk_open = false",
        "                    if ml and talk_hook_mode ~= 'replace' then",
        "                        ml.image = ml.base_image",
        "                    end",
        "                else",
        "                    p.talk_open = true",
        "                    local next_image = talk_images[p.talk_shape_index]",
        "                    if ml and talk_hook_mode ~= 'replace' then",
        "                        if next_image and images[next_image] then",
        "                            ml.image = next_image",
        "                        else",
        "                            ml.image = ml.base_image",
        "                        end",
        "                    end",
        "                    if talk_has_shapes then",
        "                        p.talk_shape_index = p.talk_shape_index + 1",
        "                        if p.talk_shape_index > #talk_images then",
        "                            p.talk_shape_index = 1",
        "                        end",
        "                    end",
        "                    if talk_hook_mode ~= 'builtin' then",
        "                        p.event_talk_step = true",
        "                    end",
        "                end",
        "            end",
        "        end",
        "        -- decrement talk_for timer",
        "        if p.talk_timer > 0 then",
        "            p.talk_timer = p.talk_timer - dt",
        "            if p.talk_timer <= 0 then",
        "                p.talk_timer  = 0",
        "                p.talk_active = false",
        "                p.talk_open   = false",
        "                p.talk_cycle  = 0",
        "                p.talk_shape_index = 1",
        "                if ml and talk_hook_mode ~= 'replace' then",
        "                    ml.image = ml.base_image",
        "                end",
        "            end",
        "        end",
        "    end",
        "",
        "    -- Idle breathing (sine wave scale pulse)",
        "    if p.idle_enabled and def.idle and def.idle.speed > 0 then",
        "        local idle_hook_mode = def.idle.hook_mode or 'builtin'",
        "        local prev_cycle = math.floor(p.idle_time / def.idle.speed)",
        "        p.idle_time = p.idle_time + dt",
        "        local next_cycle = math.floor(p.idle_time / def.idle.speed)",
        "        if idle_hook_mode ~= 'builtin' and next_cycle > prev_cycle then",
        "            p.event_idle_cycle = true",
        "        end",
        "        if idle_hook_mode ~= 'replace' and def.idle.layer_id ~= '' then",
        "            local phase   = (p.idle_time / def.idle.speed) * math.pi * 2",
        "            local ds      = math.sin(phase) * def.idle.scale_amount",
        "            local il      = pdoll_find_layer(p.layers, def.idle.layer_id)",
        "            if il then",
        "                il.dscale = ds",
        "            end",
        "        end",
        "    end",
        "",
        "    -- Macros (keyframe interpolation)",
        "    for mname, ms in pairs(p.active_macros) do",
        "        ms.time = ms.time + dt",
        "        if ms.time >= ms.duration then",
        "            if ms.loop then",
        "                ms.time = ms.time - ms.duration",
        "            else",
        "                ms.time = ms.duration",
        "                p.active_macros[mname] = nil",
        "            end",
        "        end",
        "        if ms then",
        "            -- Apply keyframes: find surrounding pair per layer and lerp",
        "            local layers_done = {}",
        "            for ki = 1, #ms.kf do",
        "                local kf = ms.kf[ki]",
        "                local lid = kf.layer_id",
        "                if not layers_done[lid] then",
        "                    -- find prev and next keyframes for this layer",
        "                    local prev_kf, next_kf = nil, nil",
        "                    for kj = 1, #ms.kf do",
        "                        local k = ms.kf[kj]",
        "                        if k.layer_id == lid then",
        "                            if k.time <= ms.time then",
        "                                if not prev_kf or k.time > prev_kf.time then prev_kf = k end",
        "                            end",
        "                            if k.time >= ms.time then",
        "                                if not next_kf or k.time < next_kf.time then next_kf = k end",
        "                            end",
        "                        end",
        "                    end",
        "                    local layer = pdoll_find_layer(p.layers, lid)",
        "                    if layer and prev_kf then",
        "                        if next_kf and next_kf.time > prev_kf.time then",
        "                            local t = (ms.time - prev_kf.time) / (next_kf.time - prev_kf.time)",
        "                            layer.dx   = prev_kf.x + (next_kf.x - prev_kf.x) * t",
        "                            layer.dy   = prev_kf.y + (next_kf.y - prev_kf.y) * t",
        "                            layer.drot = prev_kf.rotation + (next_kf.rotation - prev_kf.rotation) * t",
        "                            layer.dscale = prev_kf.scale + (next_kf.scale - prev_kf.scale) * t - 1",
        "                        else",
        "                            layer.dx   = prev_kf.x",
        "                            layer.dy   = prev_kf.y",
        "                            layer.drot = prev_kf.rotation",
        "                            layer.dscale = prev_kf.scale - 1",
        "                        end",
        "                        layers_done[lid] = true",
        "                    end",
        "                end",
        "            end",
        "        end",
        "    end",
        "end",
        "",
        "function pdoll_draw(p, bx, by, obj_scale, obj_rotation, obj_opacity)",
        "    if not p then return end",
        "    local tc = Color.new(255, 255, 255, obj_opacity)",
        "",
        "    local function draw_layer(layer, parent_x, parent_y, parent_rot, parent_scale)",
        "        local lx = layer.x + layer.dx",
        "        local ly = layer.y + layer.dy",
        "        local lr = layer.rotation + layer.drot",
        "        local ls = layer.scale + layer.dscale",
        "",
        "        -- compose with parent",
        "        local cos_pr = math.cos(parent_rot * math.pi / 180)",
        "        local sin_pr = math.sin(parent_rot * math.pi / 180)",
        "        local wx = parent_x + (lx * cos_pr - ly * sin_pr) * parent_scale",
        "        local wy = parent_y + (lx * sin_pr + ly * cos_pr) * parent_scale",
        "        local wr = parent_rot + lr",
        "        local ws = parent_scale * ls",
        "",
        "        if layer.image and images[layer.image] then",
        "            local img = images[layer.image]",
        "            local iw = Graphics.getImageWidth(img)",
        "            local ih = Graphics.getImageHeight(img)",
        "            local final_scale = ws * obj_scale",
        "            local final_rot   = (wr + obj_rotation) * (math.pi / 180)",
        "            -- drawImageExtended uses (x,y) as center; editor stores top-left",
        "            local cx = bx + wx * obj_scale + iw * final_scale * 0.5",
        "            local cy = by + wy * obj_scale + ih * final_scale * 0.5",
        "            Graphics.drawImageExtended(cx, cy, img, 0, 0, iw, ih,",
        "                final_rot, final_scale, final_scale, tc)",
        "        end",
        "",
        "        for ci = 1, #layer.children do",
        "            draw_layer(layer.children[ci], wx, wy, wr, ws)",
        "        end",
        "    end",
        "",
        "    for i = 1, #p.layers do",
        "        draw_layer(p.layers[i], 0, 0, 0, 1)",
        "    end",
        "end",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  2D SCENE → LUA
# ─────────────────────────────────────────────────────────────

def _scene_to_lua(scene: Scene, scene_num: int, project: Project) -> str:
    out = []
    out.append(f"-- scenes/scene_{scene_num:03d}.lua")
    out.append(f"-- Scene {scene_num}: {scene.name or 'Unnamed'}")
    out.append("")
    out.append(f"function scene_{scene_num}()")

    camera_obj    = None
    camera_placed = None
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.behavior_type == "Camera":
            camera_obj    = od
            camera_placed = po
            break

    out.append("    camera_reset_state()")
    out.append("    prim.reset_scene()")
    out.append("    app_ui_reset()")
    if camera_obj:
        if camera_placed:
            out.append(f"    camera.x = {camera_placed.x}")
            out.append(f"    camera.y = {camera_placed.y}")
        else:
            for po in scene.placed_objects:
                od = project.get_object_def(po.object_def_id)
                if od:
                    for beh in effective_placed_behaviors(po, od):
                        for action in beh.actions:
                            if action.action_type == "camera_follow":
                                out.append(f"    camera.x = {po.x}")
                                out.append(f"    camera.y = {po.y}")
        if camera_obj.camera_bounds_enabled:
            out.append(f"    camera.bounds_enabled = true")
            out.append(f"    camera.bounds_width   = {camera_obj.camera_bounds_width}")
            out.append(f"    camera.bounds_height  = {camera_obj.camera_bounds_height}")
        else:
            out.append(f"    camera.bounds_enabled = false")
        out.append(f"    camera.follow_lag = {camera_obj.camera_follow_lag}")
        zoom_default = getattr(camera_obj, "camera_zoom_default", 1.0)
        if zoom_default != 1.0:
            out.append(f"    camera.zoom = {zoom_default}")

    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.behavior_type != "Camera":
            vname = _placed_var_name(po)
            opacity_255 = int(round(po.opacity * 255))
            # Wrap restorable state in save guard — skip defaults if a save was just loaded
            has_save = any(c.component_type == "SaveGame" for sc in project.scenes for c in sc.components)
            if has_save:
                out.append(f"    if not _save_just_loaded then")
                out.append(f"        {vname}_x       = {po.x}")
                out.append(f"        {vname}_y       = {po.y}")
                out.append(f"        {vname}_visible = {_lua_bool(po.visible)}")
            else:
                out.append(f"    {vname}_x          = {po.x}")
                out.append(f"    {vname}_y          = {po.y}")
                out.append(f"    {vname}_visible    = {_lua_bool(po.visible)}")
            is_sprite = od.behavior_type not in ("GUI_Panel", "GUI_Label", "GUI_Button")
            if is_sprite:
                if has_save:
                    out.append(f"        {vname}_scale    = {po.scale}")
                    out.append(f"        {vname}_rotation = {po.rotation}")
                    out.append(f"        {vname}_opacity  = {opacity_255}")
                    out.append(f"    end")
                else:
                    out.append(f"    {vname}_scale     = {po.scale}")
                out.append(f"    {vname}_rotation  = {po.rotation}")
                out.append(f"    {vname}_opacity   = {opacity_255}")
                out.append(f"    {vname}_start_x   = {po.x}")
                out.append(f"    {vname}_start_y   = {po.y}")
                out.append(f"    {vname}_spin_speed = 0.0")
                out.append(f"    {vname}_interactable = true")
            elif has_save:
                out.append(f"    end")
            out.append(f"    prim.register_placed({_lua_str(po.instance_id)}, {_lua_str(od.id)}, {_lua_str(po.instance_id)}, {_lua_str(vname)})")
            if od.behavior_type in ("GUI_Label", "GUI_Button"):
                out.append(f'    {vname}_text = {_lua_str(od.gui_text)}')
                hx = od.gui_text_color.lstrip('#')
                lr, lg, lb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
                out.append(f'    {vname}_text_r = {lr}')
                out.append(f'    {vname}_text_g = {lg}')
                out.append(f'    {vname}_text_b = {lb}')
                out.append(f'    {vname}_font_size = {od.gui_font_size}')
            if od.behavior_type == "Animation" and od.ani_slots:
                first_slot = od.ani_slots[0]
                first_name = first_slot.get("name", "")
                first_id   = first_slot.get("ani_file_id", "")
                ani_playing = "true" if od.ani_play_on_spawn and not od.ani_start_paused else "false"
                start_frame = od.ani_pause_frame if od.ani_start_paused else 0
                # Slot lookup table: slot name -> ani_file_id string
                out.append(f"    {vname}_ani_slots = {{")
                for slot in od.ani_slots:
                    sname = slot.get("name", "")
                    sfid  = slot.get("ani_file_id", "")
                    out.append(f"        [{_lua_str(sname)}] = {_lua_str(sfid)},")
                out.append(f"    }}")
                out.append(f"    {vname}_ani_id      = {_lua_str(first_id)}")
                out.append(f"    {vname}_ani_slot_name = {_lua_str(first_name)}")
                out.append(f"    {vname}_ani_frame   = {start_frame}")
                out.append(f"    {vname}_ani_playing = {ani_playing}")
                out.append(f"    {vname}_ani_timer   = 0")
                out.append(f"    {vname}_ani_loop    = {_lua_bool(od.ani_loop)}")
                out.append(f"    {vname}_ani_fps     = {od.ani_fps_override}")
                out.append(f"    {vname}_ani_done    = false")
                out.append(f"    {vname}_flip_h      = {_lua_bool(od.ani_flip_h)}")
                out.append(f"    {vname}_flip_v      = {_lua_bool(od.ani_flip_v)}")

            if od.behavior_type == "LayerAnimation" and od.layer_anim_id:
                doll = project.get_paper_doll(od.layer_anim_id)
                if doll:
                    out.append(f"    {vname}_pdoll = pdoll_create({_lua_str(doll.id)})")
                    out.append(f"    {vname}_pdoll.blink_enabled = {_lua_bool(od.layer_anim_blink)}")
                    out.append(f"    {vname}_pdoll.talk_enabled  = {_lua_bool(od.layer_anim_talk)}")
                    out.append(f"    {vname}_pdoll.idle_enabled  = {_lua_bool(od.layer_anim_idle)}")

            # Sprite-frame animation for regular objects with multiple frames.
            # Single-frame objects need no runtime state — they always draw frames[0].
            if od.behavior_type not in ("Animation", "LayerAnimation",
                                        "GUI_Panel", "GUI_Label", "GUI_Button", "Camera"):
                if len(od.frames) > 1:
                    out.append(f"    {vname}_frames = {{")
                    for fi, fr in enumerate(od.frames):
                        img   = project.get_image(fr.image_id) if fr.image_id else None
                        fname = _asset_filename(img.path) if (img and img.path) else ""
                        dur   = max(1, fr.duration_frames)
                        out.append(f"        [{fi}] = {{img={_lua_str(fname)}, dur={dur}}},")
                    out.append(f"    }}")
                    out.append(f"    {vname}_frame        = 0")
                    out.append(f"    {vname}_frame_timer   = 0")
                    out.append(f"    {vname}_frame_playing = false")
                    out.append(f"    {vname}_frame_loop    = true")

    # Initialise gravity velocity for objects that opt in
    gravity_comp = scene.get_component("Gravity")
    if gravity_comp:
        _gdir = gravity_comp.config.get("gravity_direction", "down")
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and getattr(od, "affected_by_gravity", False) and od.behavior_type != "Camera":
                _all_behaviors = effective_placed_behaviors(po, od)
                vname = _placed_var_name(po)
                if _gdir in ("down", "up"):
                    out.append(f"    {vname}_vy = 0")
                else:
                    out.append(f"    {vname}_vx = 0")
                _has_jump = any(
                    act.action_type == "jump"
                    for beh in _all_behaviors
                    for act in beh.actions
                )
                if _has_jump:
                    _jump_act = next(
                        act
                        for beh in _all_behaviors
                        for act in beh.actions
                        if act.action_type == "jump"
                    )
                    out.append(f"    {vname}_jump_count = 0")
                    out.append(f"    {vname}_jump_max = {_jump_act.jump_max_count}")
                    out.append(f"    {vname}_jump_button_held = false")

    # Initialise _groups from design-time group membership for objects placed in this scene.
    # Groups are rebuilt fresh each scene load — scene-scoped at runtime, global in the editor.
    group_map: dict[str, list[str]] = {}
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.groups:
            handle = po.instance_id
            for gname in od.groups:
                gname = gname.strip()
                if gname:
                    group_map.setdefault(gname, [])
                    if handle not in group_map[gname]:
                        group_map[gname].append(handle)
    out.append("    _groups = {}")
    for gname, members in group_map.items():
        member_str = ", ".join(f'"{m}"' for m in members)
        out.append(f'    _groups[{_lua_str(gname)}] = {{{member_str}}}')

    # Bake path data from Path components
    out.append("    scene_paths = {}")
    out.append("    path_followers = {}")
    for comp in scene.components:
        if comp.component_type == "Path":
            pname = _safe_name(comp.config.get("path_name", "path"))
            raw_points = comp.config.get("points", [])
            is_closed = comp.config.get("closed", False)
            baked = _bake_bezier_points(raw_points, is_closed, interval=2.0)
            if baked:
                pts_str = ", ".join(f"{{x={p['x']},y={p['y']}}}" for p in baked)
                out.append(f'    scene_paths["{pname}"] = {{{pts_str}}}')

    # Bake grid data from Grid components
    out.append("    _scene_grids = {}")
    for comp in scene.components:
        if comp.component_type == "Grid":
            gname = _safe_name(comp.config.get("grid_name", "grid1"))
            cols  = comp.config.get("columns", 8)
            rows  = comp.config.get("rows", 8)
            cw    = comp.config.get("cell_width", 32)
            ch    = comp.config.get("cell_height", 32)
            ox    = comp.config.get("origin_x", 0)
            oy    = comp.config.get("origin_y", 0)
            out.append(f'    _scene_grids["{gname}"] = {{cols={cols}, rows={rows}, cw={cw}, ch={ch}, ox={ox}, oy={oy}, cells={{}}}}')
            # initialise empty cells table
            out.append(f'    for _gr=0,{rows-1} do')
            out.append(f'        _scene_grids["{gname}"].cells[_gr] = {{}}')
            out.append(f'        for _gc=0,{cols-1} do')
            out.append(f'            _scene_grids["{gname}"].cells[_gr][_gc] = nil')
            out.append(f'        end')
            out.append(f'    end')

    # Build parent registry from any placed objects that have a parent_id set
    out.append("    _parents = {}")
    _iid_to_po = {po.instance_id: po for po in scene.placed_objects}
    for po in scene.placed_objects:
        if po.parent_id and po.parent_id in _iid_to_po:
            od = project.get_object_def(po.object_def_id)
            parent_po = _iid_to_po[po.parent_id]
            parent_od = project.get_object_def(parent_po.object_def_id)
            if od and parent_od:
                child_var  = _placed_var_name(po)
                parent_var = _placed_var_name(parent_po)
                ppiv_x = parent_od.width  / 2.0
                ppiv_y = parent_od.height / 2.0
                cpiv_x = od.width         / 2.0
                cpiv_y = od.height        / 2.0
                off_x  = (po.x + cpiv_x) - (parent_po.x + ppiv_x)
                off_y  = (po.y + cpiv_y) - (parent_po.y + ppiv_y)
                ipos   = "true"  if po.inherit_position    else "false"
                irot   = "true"  if po.inherit_rotation     else "false"
                iscl   = "true"  if po.inherit_scale        else "false"
                dwp    = "true"  if po.destroy_with_parent  else "false"
                roff   = getattr(po, "rotation_offset", 0.0)
                out.append(
                    f'    _parents["{child_var}"] = '
                    f'{{parent_var="{parent_var}", offset_x={off_x}, offset_y={off_y}, rotation_offset={roff}, '
                    f'pivot_x={ppiv_x}, pivot_y={ppiv_y}, '
                    f'child_pivot_x={cpiv_x}, child_pivot_y={cpiv_y}, '
                    f'inherit_position={ipos}, inherit_rotation={irot}, '
                    f'inherit_scale={iscl}, destroy_with_parent={dwp}}}'
                )

    # Initialise on_timer and on_timer_variable counters, and
    # on_variable_threshold state for all behaviors in the scene.
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od or od.behavior_type == "Camera":
            continue
        vname = _placed_var_name(po)
        all_behaviors = effective_placed_behaviors(po, od)
        for bi, beh in enumerate(all_behaviors):
            if beh.trigger == "on_timer":
                out.append(f"    {vname}_timer_{bi} = 0")
            elif beh.trigger == "on_timer_variable":
                out.append(f"    {vname}_tvtimer_{bi} = 0")
            elif beh.trigger == "on_variable_threshold" and not beh.threshold_repeat:
                # one-shot: track whether it has already fired
                out.append(f"    {vname}_thresh_fired_{bi} = false")
            if beh.trigger == "on_input" and beh.input_action_name:
                ia = next((a for a in project.game_data.input_actions
                           if a.name == beh.input_action_name), None)
                if ia and ia.event == "hold_for":
                    timer_var = f"_hold_{_safe_name(ia.name)}_timer"
                    out.append(f"    {timer_var} = 0")

    ZONE_TRIGGERS = {"on_enter", "on_exit", "on_overlap", "on_interact_zone"}
    OBJECT_OVERLAP_TRIGGERS = {"on_object_overlap", "on_object_overlap_enter", "on_object_overlap_exit"}

    zone_objects = []
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od:
            continue
        all_behs = effective_placed_behaviors(po, od)
        if any(b.trigger in ZONE_TRIGGERS for b in all_behs):
            zone_objects.append(po)
    if zone_objects:
        out.append("    local _zone_prev = {}")
        for zpo in zone_objects:
            out.append(f"    _zone_prev[{_lua_str(zpo.instance_id)}] = false")
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od or od.behavior_type == "Camera":
            continue
        vname = _placed_var_name(po)
        for bi, beh in enumerate(effective_placed_behaviors(po, od)):
            if beh.trigger in OBJECT_OVERLAP_TRIGGERS:
                out.append(f"    {vname}_obj_overlap_prev_{bi} = false")

    scene_layers = sorted(
        [c for c in scene.components if c.component_type == "Layer"],
        key=lambda c: c.config.get("layer", 0)
    )
    for lc in scene_layers:
        lname = _safe_name(lc.config.get("layer_name", "") or lc.id)
        visible_init = "true" if lc.config.get("visible", True) else "false"
        scroll_init  = "true" if lc.config.get("scroll", False) else "false"
        out.append(f"    layer_{lname}_visible        = {visible_init}")
        out.append(f"    layer_{lname}_scroll_enabled = {scroll_init}")
        out.append(f"    layer_{lname}_scroll_x       = 0")
        out.append(f"    layer_{lname}_scroll_y       = 0")

    for comp in scene.components:
        if comp.component_type == "Music":
            action = comp.config.get("action", "keep")
            if action == "change":
                aud = project.get_audio(comp.config.get("audio_id", ""))
                if aud and aud.path:
                    fname = _asset_filename(aud.path)
                    out.append(f"    if current_music then Sound.close(current_music) end")
                    out.append(f"    current_music = audio_tracks[{_lua_str(fname)}]")
                    out.append(f"    if current_music then Sound.play(current_music, true) end")
            elif action == "stop":
                out.append(f"    if current_music then Sound.close(current_music) end")
                out.append(f"    current_music = nil")

    if scene.role == "start":
        out.append("    local chosen = false")
        out.append("    while not chosen do")
        out.append("        controls_update()")
        out.append("        touch_update()")
        out.append("        _signals = {}")
        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")
        out.append('        if deff then')
        out.append('            Font.print(deff, 62, 452, "Cross: New Game    Triangle: Continue", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 450, "Cross: New Game    Triangle: Continue", Color.new(255,255,255))')
        out.append('        end')
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")
        out.append("        if controls_released(SCE_CTRL_START) then os.exit() end")
        out.append("        if controls_released(SCE_CTRL_CROSS) then")
        out.append(f"            current_scene = {scene_num + 1}")
        out.append("            chosen = true")
        out.append("        elseif controls_released(SCE_CTRL_TRIANGLE) then")
        out.append(f"            current_scene = {scene_num + 1}")
        out.append("            chosen = true")
        out.append("        end")
        out.append("    end")

    elif scene.role == "end":
        out.append("    local waiting = true")
        out.append("    while waiting do")
        out.append("        controls_update()")
        out.append("        touch_update()")
        out.append("        _signals = {}")
        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")
        out.append('        if deff then')
        out.append('            Font.print(deff, 62, 262, "--- THE END ---", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 260, "--- THE END ---", Color.new(255,255,255))')
        out.append('            Font.print(deff, 62, 302, "Press START to exit", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 300, "Press START to exit", Color.new(255,255,255))')
        out.append('        end')
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")
        out.append("        if controls_released(SCE_CTRL_START) then")
        out.append("            if current_music then Sound.close(current_music) end")
        out.append("            waiting = false")
        out.append("            running = false")
        out.append("        end")
        out.append("    end")

    else:
        vn_comp = next((c for c in scene.components if c.component_type == "VNDialogBox"), None)
        vn_dialog_cfg, vn_tw_cfg = _collect_vn_sound_configs(scene, project) if vn_comp else (None, None)

        out.append("    local advance = false")
        out.append("    local _focused_obj        = nil  -- runtime handle of the currently focused navigable object")
        out.append("    local _focus_selected_obj  = nil  -- set for one frame when focus changes")
        out.append("    local _focus_activated_obj = nil  -- set for one frame when Activate Focused is called")
        if any(c.component_type == "SaveGame" for sc in project.scenes for c in sc.components):
            out.append("    _save_just_loaded = false")
        if vn_comp:
            cfg_vn = vn_comp.config
            pages = cfg_vn.get("dialog_pages", [])
            if not pages:
                pages = [{"character": "", "lines": ["", "", "", ""], "advance_to_next": True}]
            # Build Lua pages table
            out.append("    local _vn_pages = {}")
            for pi, page in enumerate(pages, 1):
                char = page.get("character", "")
                lines = page.get("lines", ["", "", "", ""])
                adv = "true" if page.get("advance_to_next", False) else "false"
                tw = "true" if page.get("typewriter", False) else "false"
                tw_speed = page.get("typewriter_speed", 30)
                lua_lines = ", ".join(_lua_str(l) for l in lines)
                out.append(f"    _vn_pages[{pi}] = {{character = {_lua_str(char)}, lines = {{{lua_lines}}}, advance_to_next = {adv}, typewriter = {tw}, tw_speed = {tw_speed}}}")
            out.append(f"    local _vn_page = 1")
            out.append(f"    local _vn_page_count = {len(pages)}")
            out.append( "    local _vn_char_idx = 0")
            out.append( "    local _vn_tw_done = false")
            out.append( "    local _vn_prev_time = 0")
            out.append( "    local _vn_frame_ms = 0")
            # ── Emit tag-aware helper functions ──────────────
            out.append( "    -- strips [tags] from a string, returns only visible text")
            out.append( "    local function _vn_strip_tags(s)")
            out.append( "        return (s:gsub('%[/?[^%]]*%]', ''))")
            out.append( "    end")
            out.append( "    -- draws a single line with tag support (color, bold, bounce, shake, wave, rainbow)")
            out.append( "    local function _vn_draw_line(font, s, base_x, base_y, def_col, visible_chars, frame, do_shadow)")
            out.append( "        local i = 1")
            out.append( "        local x = base_x")
            out.append( "        local col = def_col")
            out.append( "        local effect = 'none'")
            out.append( "        local drawn = 0")
            out.append( "        local slen = #s")
            out.append( "        while i <= slen do")
            out.append( "            if s:sub(i,i) == '[' then")
            out.append( "                local ce = s:find(']', i, true)")
            out.append( "                if ce then")
            out.append( "                    local tag = s:sub(i+1, ce-1)")
            out.append( "                    if tag == '/color' then col = def_col")
            out.append( "                    elseif tag:sub(1,6) == 'color=' then")
            out.append( "                        local hex = tag:sub(8)")
            out.append( "                        local r = tonumber(hex:sub(1,2),16) or 255")
            out.append( "                        local g = tonumber(hex:sub(3,4),16) or 255")
            out.append( "                        local b = tonumber(hex:sub(5,6),16) or 255")
            out.append( "                        col = Color.new(r,g,b,255)")
            out.append( "                    elseif tag=='bounce' then effect='bounce'")
            out.append( "                    elseif tag=='shake'  then effect='shake'")
            out.append( "                    elseif tag=='wave'   then effect='wave'")
            out.append( "                    elseif tag=='rainbow' then effect='rainbow'")
            out.append( "                    elseif tag=='/bounce' or tag=='/shake' or tag=='/wave' or tag=='/rainbow' or tag=='/b' then effect='none'")
            out.append( "                    end")
            out.append( "                    i = ce + 1")
            out.append( "                else i = i + 1 end")
            out.append( "            else")
            out.append( "                if visible_chars ~= nil and drawn >= visible_chars then break end")
            out.append( "                local ch = s:sub(i,i)")
            out.append( "                local ox, oy = 0, 0")
            out.append( "                local draw_col = col")
            out.append( "                if effect == 'bounce' then")
            out.append( "                    oy = math.floor(math.sin(frame * 0.15 + drawn * 0.5) * 4)")
            out.append( "                elseif effect == 'shake' then")
            out.append( "                    ox = math.floor((math.random()-0.5)*4)")
            out.append( "                    oy = math.floor((math.random()-0.5)*2)")
            out.append( "                elseif effect == 'wave' then")
            out.append( "                    oy = math.floor(math.sin(frame * 0.08 + drawn * 0.35) * 5)")
            out.append( "                elseif effect == 'rainbow' then")
            out.append( "                    local hue = (frame * 3 + drawn * 20) % 360")
            out.append( "                    local h6 = hue/60")
            out.append( "                    local f2 = h6 - math.floor(h6)")
            out.append( "                    local q = math.floor((1-f2)*255)")
            out.append( "                    local t2 = math.floor(f2*255)")
            out.append( "                    local sec = math.floor(h6) % 6")
            out.append( "                    local ri,gi,bi = 255,0,0")
            out.append( "                    if sec==0 then ri,gi,bi=255,t2,0")
            out.append( "                    elseif sec==1 then ri,gi,bi=q,255,0")
            out.append( "                    elseif sec==2 then ri,gi,bi=0,255,t2")
            out.append( "                    elseif sec==3 then ri,gi,bi=0,q,255")
            out.append( "                    elseif sec==4 then ri,gi,bi=t2,0,255")
            out.append( "                    else ri,gi,bi=255,0,q end")
            out.append( "                    draw_col = Color.new(ri,gi,bi,255)")
            out.append( "                end")
            out.append( "                local cw = Font.getTextWidth(font, ch)")
            out.append( "                if do_shadow then Font.print(font, x+ox+2, base_y+oy+2, ch, Color.new(0,0,0)) end")
            out.append( "                Font.print(font, x+ox, base_y+oy, ch, draw_col)")
            out.append( "                x = x + cw")
            out.append( "                drawn = drawn + 1")
            out.append( "                i = i + 1")
            out.append( "            end")
            out.append( "        end")
            out.append( "    end")
            if cfg_vn.get("auto_advance", False):
                out.append("    local auto_advance_timer = 0")
            # If page 1 has typewriter, activate talk on all talk-enabled LayerAnimation objects
            if pages and pages[0].get("typewriter", False):
                for po2 in scene.placed_objects:
                    od2 = project.get_object_def(po2.object_def_id)
                    if od2 and od2.behavior_type == "LayerAnimation" and od2.layer_anim_talk and od2.layer_anim_id:
                        vn2 = _placed_var_name(po2)
                        out.append(f"    {vn2}_pdoll.talk_active = true")
                if vn_dialog_cfg:
                    fname = vn_dialog_cfg["fname"]
                    mode  = vn_dialog_cfg["mode"]
                    out.append(f"    do")
                    out.append(f"        local _ds = audio_tracks[{_lua_str(fname)}]")
                    out.append(f"        if _ds then Sound.play(_ds, {_lua_bool(mode == 'loop')}) end")
                    out.append(f"    end")

        # ── on_scene_start / on_create  (run once before main loop) ──────────
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _placed_var_name(po)
            all_behaviors = effective_placed_behaviors(po, od)
            for bi, beh in enumerate(all_behaviors):
                if beh.trigger in ("on_scene_start", "on_create"):
                    out.append(f"    -- {beh.trigger} [{od.name}]")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"    {line}")
        for line in _plugin_scene_hook_lines(scene, project, "lua_scene_init"):
            out.append(f"    {line}")

        # ── Wait / fade state ───────────────────────────────────────────────
        out.append("    local _scene_timer = Timer.new()")
        out.append("    Timer.reset(_scene_timer)")
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname = _placed_var_name(po)
                out.append(f"    {vname}_wait_until = 0")
                out.append(f"    {vname}_waiting_input = false")
        out.append("    _fade_alpha    = 0")
        out.append("    _fade_start    = 0")
        out.append("    _fade_duration = 0")
        out.append("    _fade_from     = 0")
        out.append("    _fade_to       = 0")

        # ── FPS cap timer (if enabled) ────────────────────────────────────
        if project.game_data.fps_cap_enabled:
            out.append("    local _frame_timer = Timer.new()")
            out.append("    Timer.reset(_frame_timer)")

        out.append("    while not advance do")

        out.append("        controls_update()")
        out.append("        touch_update()")
        out.append("        _signals = {}")
        out.append("        app_ui_begin_frame()")
        out.append("        tween_update()")
        out.append("        path_update()")
        out.append("        shake_update()")
        out.append("        flash_update()")

        # ── D-pad navigation ─────────────────────────────────────────────
        # Emit once per scene; only if any placed object is navigable
        nav_objects = []
        for _npo in scene.placed_objects:
            _nod = project.get_object_def(_npo.object_def_id)
            if _nod and getattr(_nod, 'navigable', False):
                nav_objects.append((_npo, _nod))

        if nav_objects:
            out.append("        -- D-pad navigation")
            out.append("        _focus_selected_obj  = nil")
            out.append("        _focus_activated_obj = nil")

            def _nav_resolve(def_id):
                handles = _scene_target_handles(def_id, project)
                if handles:
                    return _lua_str(handles[0])
                return "nil"

            # D-pad moves focus only — does NOT fire on_selection
            out.append("        do")
            out.append("            local _nav_move = nil")
            out.append("            if controls_pressed(SCE_CTRL_UP)    then _nav_move = \"up\"    end")
            out.append("            if controls_pressed(SCE_CTRL_DOWN)  then _nav_move = \"down\"  end")
            out.append("            if controls_pressed(SCE_CTRL_LEFT)  then _nav_move = \"left\"  end")
            out.append("            if controls_pressed(SCE_CTRL_RIGHT) then _nav_move = \"right\" end")
            out.append("            if _nav_move and _focused_obj then")
            for _npo, _nod in nav_objects:
                vn = _placed_var_name(_npo)
                handle = _npo.instance_id
                up_s    = _nav_resolve(getattr(_nod, 'focus_nav_up',    ""))
                down_s  = _nav_resolve(getattr(_nod, 'focus_nav_down',  ""))
                left_s  = _nav_resolve(getattr(_nod, 'focus_nav_left',  ""))
                right_s = _nav_resolve(getattr(_nod, 'focus_nav_right', ""))
                out.append(f"                if _focused_obj == {_lua_str(handle)} then")
                out.append(f"                    local _nb = nil")
                out.append(f"                    if _nav_move == \"up\"    then _nb = {up_s}    end")
                out.append(f"                    if _nav_move == \"down\"  then _nb = {down_s}  end")
                out.append(f"                    if _nav_move == \"left\"  then _nb = {left_s}  end")
                out.append(f"                    if _nav_move == \"right\" then _nb = {right_s} end")
                out.append(f"                    if _nb and _nb ~= {_lua_str(handle)} then")
                out.append(f"                        local _nbv = false")
                for _npo2, _nod2 in nav_objects:
                    vn2 = _placed_var_name(_npo2)
                    handle2 = _npo2.instance_id
                    out.append(f"                        if _nb == {_lua_str(handle2)} then _nbv = {vn2}_visible end")
                out.append(f"                        if _nbv then _focused_obj = _nb end")
                out.append(f"                    end")
                out.append(f"                end")
            out.append("            end")
            # Cross press confirms the focused object → fires on_selection
            out.append("            if controls_pressed(SCE_CTRL_CROSS) and _focused_obj then")
            out.append("                _focus_selected_obj = _focused_obj")
            out.append("            end")
            out.append("        end")

        # ── Typewriter accumulator ───────────────────────────────────────
        if vn_comp:
            out.append("        do")
            out.append("            local _now = Timer.getTime(_scene_timer)")
            out.append("            _vn_frame_ms = _now - _vn_prev_time")
            out.append("            if _vn_frame_ms > 100 then _vn_frame_ms = 100 end")
            out.append("            _vn_prev_time = _now")
            out.append("            local _dt = _vn_frame_ms / 1000")
            out.append("            local _cp = _vn_pages[_vn_page]")
            out.append("            if _cp.typewriter and not _vn_tw_done then")
            out.append("                local _total = 0")
            out.append("                for _i = 1, #_cp.lines do _total = _total + #_vn_strip_tags(_cp.lines[_i]) end")
            out.append("                local _prev_idx = math.floor(_vn_char_idx)")
            out.append("                _vn_char_idx = _vn_char_idx + _cp.tw_speed * _dt")
            out.append("                local _new_idx = math.floor(_vn_char_idx)")
            if vn_tw_cfg:
                interval = vn_tw_cfg["interval"]
                fnames   = vn_tw_cfg["fnames"]
                lua_pool = "{" + ", ".join(f"audio_tracks[{_lua_str(f)}]" for f in fnames) + "}"
                out.append(f"                if _new_idx > _prev_idx and (_new_idx % {interval}) == 0 then")
                out.append(f"                    local _pool = {lua_pool}")
                out.append(f"                    local _snd = _pool[math.random(1, {len(fnames)})]")
                out.append(f"                    if _snd then Sound.play(_snd, false) end")
                out.append(f"                end")
            out.append("                if _vn_char_idx >= _total then")
            out.append("                    _vn_char_idx = _total")
            out.append("                    _vn_tw_done = true")
            # stop talk on all talk-enabled LayerAnimation objects
            for po2 in scene.placed_objects:
                od2 = project.get_object_def(po2.object_def_id)
                if od2 and od2.behavior_type == "LayerAnimation" and od2.layer_anim_talk and od2.layer_anim_id:
                    vn2 = _placed_var_name(po2)
                    out.append(f"                    {vn2}_pdoll.talk_active = false")
                    out.append(f"                    {vn2}_pdoll.talk_open   = false")
            if vn_dialog_cfg and vn_dialog_cfg["mode"] in ("loop", "play_once"):
                fname = vn_dialog_cfg["fname"]
                out.append(f"                    do")
                out.append(f"                        local _ds = audio_tracks[{_lua_str(fname)}]")
                out.append(f"                        if _ds then Sound.stop(_ds) end")
                out.append(f"                    end")
            out.append("                end")
            out.append("            end")
            out.append("        end")

        # ── Fade alpha update ──────────────────────────────────────────────
        out.append("        if _fade_duration > 0 then")
        out.append("            local _ft = Timer.getTime(_scene_timer) - _fade_start")
        out.append("            if _ft >= _fade_duration then")
        out.append("                _fade_alpha = _fade_to")
        out.append("                _fade_duration = 0")
        out.append("            else")
        out.append("                _fade_alpha = _fade_from + (_fade_to - _fade_from) * _ft / _fade_duration")
        out.append("            end")
        out.append("        end")

        for line in _plugin_scene_hook_lines(scene, project, "lua_scene_loop"):
            out.append(f"        {line}")

        # ── Per-frame behavior dispatch ─────────────────────────────────────
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _placed_var_name(po)
            handle = po.instance_id
            all_behaviors = effective_placed_behaviors(po, od)

            # Wait guard: clear expired waits, then skip if still waiting
            out.append(f"        if {vname}_waiting_input and Controls.read() ~= 0 then {vname}_waiting_input = false end")
            out.append(f"        if {vname}_wait_until > 0 and Timer.getTime(_scene_timer) >= {vname}_wait_until then {vname}_wait_until = 0 end")
            out.append(f"        if {vname}_wait_until == 0 and not {vname}_waiting_input then")

            for bi, beh in enumerate(all_behaviors):

                if beh.trigger == "on_frame":
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"            {line}")

                elif beh.trigger == "on_timer" and beh.frame_count > 0:
                    tvar = f"{vname}_timer_{bi}"
                    out.append(f"            {tvar} = {tvar} + 1")
                    out.append(f"            if {tvar} >= {beh.frame_count} then")
                    out.append(f"                {tvar} = 0")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_timer_variable" and beh.timer_var:
                    tvar    = f"{vname}_tvtimer_{bi}"
                    iv_name = _safe_name(beh.timer_var)
                    out.append(f"            {tvar} = {tvar} + 1")
                    out.append(f"            if ({iv_name} or 0) > 0 and {tvar} >= {iv_name} then")
                    out.append(f"                {tvar} = 0")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_variable_threshold" and beh.threshold_var:
                    tv   = _safe_name(beh.threshold_var)
                    tval = beh.threshold_value or "0"
                    tcmp = beh.threshold_compare or ">="
                    if beh.threshold_repeat:
                        pvar = f"{vname}_thresh_prev_{bi}"
                        out.append(f"            do")
                        out.append(f"                local _tcond = ({tv} or 0) {tcmp} {tval}")
                        out.append(f"                if _tcond and not ({pvar} == true) then")
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                    {line}")
                        out.append(f"                end")
                        out.append(f"                {pvar} = _tcond")
                        out.append(f"            end")
                    else:
                        fvar = f"{vname}_thresh_fired_{bi}"
                        out.append(f"            if not {fvar} and ({tv} or 0) {tcmp} {tval} then")
                        out.append(f"                {fvar} = true")
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                {line}")
                        out.append(f"            end")

                elif beh.trigger == "on_button_pressed" and beh.button:
                    if _is_stick_virtual_button(beh.button):
                        _stick, _dir = _stick_button_to_parts(beh.button)
                        out.append(f"            if stick_dir_pressed('{_stick}', '{_dir}', 32) then")
                    else:
                        btn = _button_constant(beh.button)
                        out.append(f"            if controls_pressed({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_button_held" and beh.button:
                    if _is_stick_virtual_button(beh.button):
                        _stick, _dir = _stick_button_to_parts(beh.button)
                        out.append(f"            if stick_dir_held('{_stick}', '{_dir}', 32) then")
                    else:
                        btn = _button_constant(beh.button)
                        out.append(f"            if controls_held({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_button_released" and beh.button:
                    if _is_stick_virtual_button(beh.button):
                        _stick, _dir = _stick_button_to_parts(beh.button)
                        out.append(f"            if stick_dir_released('{_stick}', '{_dir}', 32) then")
                    else:
                        btn = _button_constant(beh.button)
                        out.append(f"            if controls_released({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_signal" and beh.bool_var:
                    sig = beh.bool_var
                    out.append(f"            if signal_fired({_lua_str(sig)}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger in ("on_keyboard_submit", "on_keyboard_cancel", "on_confirm_yes", "on_confirm_no"):
                    _cond = _app_ui_trigger_condition(beh)
                    if _cond:
                        out.append(f"            if {_cond} then")
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                {line}")
                        out.append(f"            end")

                elif beh.trigger in ("on_layer_anim_blink", "on_layer_anim_talk_step", "on_layer_anim_idle_cycle"):
                    event_attr = {
                        "on_layer_anim_blink": "event_blink",
                        "on_layer_anim_talk_step": "event_talk_step",
                        "on_layer_anim_idle_cycle": "event_idle_cycle",
                    }[beh.trigger]
                    out.append(f"            if {vname}_pdoll and {vname}_pdoll.{event_attr} then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_touch_tap":
                    if od.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                        tw = od.gui_width
                        th = od.gui_height
                    else:
                        tw = int(od.width * po.scale)
                        th = int(od.height * po.scale)
                    out.append(f"            if {vname}_visible and (touch_in_rect({vname}_x, {vname}_y, {tw}, {th}) or _focus_activated_obj == {_lua_str(handle)}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_touch_swipe":
                    sdir  = beh.swipe_direction or "any"
                    sdist = int(beh.swipe_min_distance)
                    if beh.swipe_scope == "object":
                        if od.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                            tw = od.gui_width
                            th = od.gui_height
                        else:
                            tw = int(od.width * po.scale)
                            th = int(od.height * po.scale)
                        out.append(f"            if {vname}_visible and touch_swipe_matches({_lua_str(sdir)}, {sdist}) and touch_start_in_rect({vname}_x, {vname}_y, {tw}, {th}) then")
                    else:
                        out.append(f"            if touch_swipe_matches({_lua_str(sdir)}, {sdist}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_selection":
                    out.append(f"            if _focus_selected_obj == {_lua_str(handle)} then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_path_complete":
                    pname = _safe_name(beh.path_name or "")
                    if pname:
                        out.append(f'            if signal_fired("path_complete_{pname}") then')
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                {line}")
                        out.append(f"            end")

                elif beh.trigger == "on_animation_finish" and beh.ani_trigger_object:
                    target_vars = _scene_target_vars(beh.ani_trigger_object, project)
                    tname = target_vars[0] if target_vars else None
                    if tname:
                        out.append(f"            if {tname}_ani_done then")
                        out.append(f"                {tname}_ani_done = false  -- consume so it fires once")
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                {line}")
                        out.append(f"            end")

                elif beh.trigger == "on_animation_frame" and beh.ani_trigger_object:
                    target_vars = _scene_target_vars(beh.ani_trigger_object, project)
                    tname = target_vars[0] if target_vars else None
                    fvar  = f"{vname}_aniframe_prev_{bi}"
                    if tname:
                        out.append(f"            do")
                        out.append(f"                local _af = {tname}_ani_frame or 0")
                        out.append(f"                if _af == {beh.ani_trigger_frame} and {fvar} ~= {beh.ani_trigger_frame} then")
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                out.append(f"                    {line}")
                        out.append(f"                end")
                        out.append(f"                {fvar} = _af")
                        out.append(f"            end")

                elif beh.trigger == "on_lua_condition" and beh.lua_condition:
                    expr = beh.lua_condition.strip()
                    out.append(f"            if {expr} then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif _emit_plugin_trigger_dispatch(out, beh, vname, project, obj_def=od, indent="            "):
                    pass

            out.append(f"        end  -- wait guard [{od.name}]")

        out.append("        prim.update_motion()")
        out.append("        camera_update_follow()")
        out.append("        parents_update()")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            if od.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                continue
            vname = _placed_var_name(po)
            out.append(f"        if {vname}_spin_speed ~= 0 then {vname}_rotation = {vname}_rotation + {vname}_spin_speed end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "Animation" and od.ani_slots:
                vname = _placed_var_name(po)
                out.append(f"        if {vname}_ani_playing and not {vname}_ani_done then")
                out.append(f"            local _ani_d = ani_data[{vname}_ani_id]")
                out.append(f"            if _ani_d then")
                out.append(f"                local _fps   = {vname}_ani_fps > 0 and {vname}_ani_fps or _ani_d.fps")
                out.append(f"                local _delay = math.floor(60 / _fps)")
                out.append(f"                if _delay < 1 then _delay = 1 end")
                out.append(f"                {vname}_ani_timer = {vname}_ani_timer + 1")
                out.append(f"                if {vname}_ani_timer >= _delay then")
                out.append(f"                    {vname}_ani_timer = 0")
                out.append(f"                    {vname}_ani_frame = {vname}_ani_frame + 1")
                out.append(f"                    if {vname}_ani_frame >= _ani_d.frame_count then")
                out.append(f"                        if {vname}_ani_loop then")
                out.append(f"                            {vname}_ani_frame = 0")
                out.append(f"                        else")
                out.append(f"                            {vname}_ani_frame = _ani_d.frame_count - 1")
                out.append(f"                            {vname}_ani_done    = true")
                out.append(f"                            {vname}_ani_playing = false")
                out.append(f"                        end")
                out.append(f"                    end")
                out.append(f"                end")
                out.append(f"            end")
                out.append(f"        end")

        # Sprite-frame ticker for regular multi-frame objects
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od:
                continue
            if od.behavior_type in ("Animation", "LayerAnimation",
                                    "GUI_Panel", "GUI_Label", "GUI_Button", "Camera"):
                continue
            if len(od.frames) > 1:
                vname = _placed_var_name(po)
                out.append(f"        if {vname}_frame_playing then")
                out.append(f"            local _fdef = {vname}_frames[{vname}_frame]")
                out.append(f"            if _fdef then")
                out.append(f"                {vname}_frame_timer = {vname}_frame_timer + 1")
                out.append(f"                if {vname}_frame_timer >= _fdef.dur then")
                out.append(f"                    {vname}_frame_timer = 0")
                out.append(f"                    {vname}_frame = {vname}_frame + 1")
                out.append(f"                    local _fc = 0")
                out.append(f"                    for _ in pairs({vname}_frames) do _fc = _fc + 1 end")
                out.append(f"                    if {vname}_frame >= _fc then")
                out.append(f"                        if {vname}_frame_loop then")
                out.append(f"                            {vname}_frame = 0")
                out.append(f"                        else")
                out.append(f"                            {vname}_frame = _fc - 1")
                out.append(f"                            {vname}_frame_playing = false")
                out.append(f"                        end")
                out.append(f"                    end")
                out.append(f"                end")
                out.append(f"            end")
                out.append(f"        end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "LayerAnimation" and od.layer_anim_id:
                doll = project.get_paper_doll(od.layer_anim_id)
                if doll:
                    vname = _placed_var_name(po)
                    if vn_dialog_cfg and vn_dialog_cfg["mode"] == "repeat_on_cycle" and od.layer_anim_talk:
                        fname = vn_dialog_cfg["fname"]
                        out.append(f"        if {vname}_pdoll then")
                        out.append(f"            pdoll_update({vname}_pdoll, 1/60)")
                        out.append(f"            if {vname}_pdoll.event_talk_step then")
                        out.append(f"                local _ds = audio_tracks[{_lua_str(fname)}]")
                        out.append(f"                if _ds then Sound.play(_ds, false) end")
                        out.append(f"            end")
                        out.append(f"        end")
                    else:
                        out.append(f"        if {vname}_pdoll then pdoll_update({vname}_pdoll, 1/60) end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _placed_var_name(po)
            current_def_id, current_frame, current_slot = _current_collision_state_expr(vname, od)
            all_behaviors = effective_placed_behaviors(po, od)
            for bi, beh in enumerate(all_behaviors):
                if beh.trigger not in OBJECT_OVERLAP_TRIGGERS:
                    continue
                target_id = getattr(beh, "overlap_object_id", "") or ""
                source_role = getattr(beh, "overlap_source_role", "Hitbox") or "Hitbox"
                target_role = getattr(beh, "overlap_target_role", "Hurtbox") or "Hurtbox"
                overlap_var = f"_obj_overlap_{_safe_name(po.instance_id)}_{bi}"
                prev_var = f"{vname}_obj_overlap_prev_{bi}"
                out.append("        do")
                out.append(
                    f"            local {overlap_var}_count = count_object_overlaps({_lua_str(po.instance_id)}, {current_def_id}, "
                    f"{vname}_x, {vname}_y, {current_slot}, {current_frame}, {_lua_str(target_id)}, "
                    f"{_lua_str(source_role)}, {_lua_str(target_role)})"
                )
                out.append(f"            local {overlap_var}_now = {overlap_var}_count > 0")
                if beh.trigger == "on_object_overlap_enter":
                    out.append(f"            if {overlap_var}_now and not {prev_var} then")
                elif beh.trigger == "on_object_overlap_exit":
                    out.append(f"            if not {overlap_var}_now and {prev_var} then")
                else:
                    out.append(f"            if {overlap_var}_now then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"                {line}")
                out.append("            end")
                out.append(f"            {prev_var} = {overlap_var}_now")
                out.append("        end")

        if zone_objects:
            zone_instance_ids = {zpo.instance_id for zpo in zone_objects}
            mover_objects = [
                (_po, project.get_object_def(_po.object_def_id))
                for _po in scene.placed_objects
                if _po.instance_id not in zone_instance_ids
                and project.get_object_def(_po.object_def_id) is not None
                and project.get_object_def(_po.object_def_id).behavior_type != "Camera"
                and getattr(project.get_object_def(_po.object_def_id), 'is_mover', True)
            ]
            for zpo in zone_objects:
                zod = project.get_object_def(zpo.object_def_id)
                if not zod:
                    continue
                zname = _placed_var_name(zpo)
                zw = int(zod.width * zpo.scale)
                zh = int(zod.height * zpo.scale)
                all_zbeh = effective_placed_behaviors(zpo, zod)
                has_zone_behs = any(b.trigger in ("on_enter","on_exit","on_overlap","on_interact_zone") for b in all_zbeh)
                if not has_zone_behs:
                    continue
                out.append(f"        -- zone: {zname}")
                _zone_has_cboxes = _object_has_collision_boxes(zod)
                if not _zone_has_cboxes:
                    out.append(f"        local _zx1_{zname} = {zname}_x")
                    out.append(f"        local _zy1_{zname} = {zname}_y")
                    out.append(f"        local _zx2_{zname} = {zname}_x + {zw}")
                    out.append(f"        local _zy2_{zname} = {zname}_y + {zh}")
                out.append(f"        local _znow_{zname} = false")
                for mpo, mod in mover_objects:
                    mname = _placed_var_name(mpo)
                    mw = int(mod.width * mpo.scale)
                    mh = int(mod.height * mpo.scale)
                    _mover_has_cboxes = _object_has_collision_boxes(mod)
                    out.append(f"        if not _znow_{zname} then")
                    if _zone_has_cboxes and _mover_has_cboxes:
                        # Both have collision boxes — use check_obj_collision
                        _zframe = f"{zname}_ani_frame" if zod.behavior_type == "Animation" else "0"
                        _zslot = f"{zname}_ani_slot_name" if zod.behavior_type == "Animation" else '""'
                        _mframe = f"{mname}_ani_frame" if mod.behavior_type == "Animation" else "0"
                        _mslot = f"{mname}_ani_slot_name" if mod.behavior_type == "Animation" else '""'
                        out.append(f"            _znow_{zname} = check_obj_collision({_lua_str(zod.id)}, {zname}_x, {zname}_y, {_zslot}, {_zframe}, {_lua_str(mod.id)}, {mname}_x, {mname}_y, {_mslot}, {_mframe})")
                    elif _zone_has_cboxes:
                        # Zone has boxes, mover uses bounding box — check each zone box vs mover AABB
                        _zframe = f"{zname}_ani_frame" if zod.behavior_type == "Animation" else "0"
                        _zslot = f"{zname}_ani_slot_name" if zod.behavior_type == "Animation" else '""'
                        out.append(f"            local _zboxes = def_frame_boxes({_lua_str(zod.id)}, {_zslot}, {_zframe})")
                        out.append(f"            for _, _zb in ipairs(_zboxes) do")
                        out.append(f"                if aabb_overlap({zname}_x + _zb.x, {zname}_y + _zb.y, _zb.w, _zb.h, {mname}_x, {mname}_y, {mw}, {mh}) then")
                        out.append(f"                    _znow_{zname} = true")
                        out.append(f"                    break")
                        out.append(f"                end")
                        out.append(f"            end")
                    elif _mover_has_cboxes:
                        # Mover has boxes, zone uses bounding box — check each mover box vs zone AABB
                        _mframe = f"{mname}_ani_frame" if mod.behavior_type == "Animation" else "0"
                        _mslot = f"{mname}_ani_slot_name" if mod.behavior_type == "Animation" else '""'
                        out.append(f"            local _mboxes = def_frame_boxes({_lua_str(mod.id)}, {_mslot}, {_mframe})")
                        out.append(f"            for _, _mb in ipairs(_mboxes) do")
                        out.append(f"                if aabb_overlap({zname}_x, {zname}_y, {zw}, {zh}, {mname}_x + _mb.x, {mname}_y + _mb.y, _mb.w, _mb.h) then")
                        out.append(f"                    _znow_{zname} = true")
                        out.append(f"                    break")
                        out.append(f"                end")
                        out.append(f"            end")
                    else:
                        # Neither has collision boxes — original bounding box check
                        out.append(f"            local _mx1 = {mname}_x")
                        out.append(f"            local _my1 = {mname}_y")
                        out.append(f"            local _mx2 = {mname}_x + {mw}")
                        out.append(f"            local _my2 = {mname}_y + {mh}")
                        out.append(f"            _znow_{zname} = (_mx1 < _zx2_{zname} and _mx2 > _zx1_{zname} and _my1 < _zy2_{zname} and _my2 > _zy1_{zname})")
                    out.append(f"        end")
                out.append(f"        local _zprev_{zname} = _zone_prev[{_lua_str(zpo.instance_id)}]")
                enter_behs = [b for b in all_zbeh if b.trigger == "on_enter"]
                if enter_behs:
                    out.append(f"        if _znow_{zname} and not _zprev_{zname} then")
                    for beh in enter_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project, obj_def=zod):
                                out.append(f"            {line}")
                    out.append(f"        end")
                exit_behs = [b for b in all_zbeh if b.trigger == "on_exit"]
                if exit_behs:
                    out.append(f"        if not _znow_{zname} and _zprev_{zname} then")
                    for beh in exit_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project, obj_def=zod):
                                out.append(f"            {line}")
                    out.append(f"        end")
                overlap_behs = [b for b in all_zbeh if b.trigger == "on_overlap"]
                if overlap_behs:
                    out.append(f"        if _znow_{zname} then")
                    for beh in overlap_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project, obj_def=zod):
                                out.append(f"            {line}")
                    out.append(f"        end")
                iz_behs = [b for b in all_zbeh if b.trigger == "on_interact_zone"]
                if iz_behs:
                    out.append(f"        if _znow_{zname} and ({zname}_interactable ~= false) and controls_released(SCE_CTRL_CROSS) then")
                    for beh in iz_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project, obj_def=zod):
                                out.append(f"            {line}")
                    out.append(f"        end")
                out.append(f"        _zone_prev[{_lua_str(zpo.instance_id)}] = _znow_{zname}")

        # ── Gravity physics ──────────────────────────────────
        if gravity_comp:
            gstr = gravity_comp.config.get("gravity_strength", 0.5)
            gdir = gravity_comp.config.get("gravity_direction", "down")
            tvel = gravity_comp.config.get("terminal_velocity", 10)
            gravity_objects = []
            for po in scene.placed_objects:
                od = project.get_object_def(po.object_def_id)
                if od and getattr(od, "affected_by_gravity", False) and od.behavior_type != "Camera":
                    gravity_objects.append((po, od))
            if gravity_objects:
                out.append("        -- gravity")
                scene_has_solid_blockers = any(
                    _sod and getattr(_sod, "blocks_2d_movement", False)
                    for _spo in scene.placed_objects
                    for _sod in [project.get_object_def(_spo.object_def_id)]
                )
                for po, od in gravity_objects:
                    _all_behaviors = effective_placed_behaviors(po, od)
                    vname = _placed_var_name(po)
                    if gdir in ("down", "up"):
                        vel_var = f"{vname}_vy"
                        pos_var = f"{vname}_y"
                        other_pos = f"{vname}_x"
                        sign = 1 if gdir == "down" else -1
                    else:
                        vel_var = f"{vname}_vx"
                        pos_var = f"{vname}_x"
                        other_pos = f"{vname}_y"
                        sign = 1 if gdir == "right" else -1
                    out.append(f"        {vel_var} = {vel_var} + {sign * gstr}")
                    out.append(f"        if {vel_var} > {tvel} then {vel_var} = {tvel} end")
                    out.append(f"        if {vel_var} < -{tvel} then {vel_var} = -{tvel} end")

                    # Find collision layer for this object from its behaviors
                    _grav_grid_id = ""
                    _grav_pw = 32
                    _grav_ph = 48
                    for beh in _all_behaviors:
                        for act in beh.actions:
                            if act.action_type in ("four_way_movement_collide", "two_way_movement_collide", "eight_way_movement_collide"):
                                _grav_grid_id = act.collision_layer_id or ""
                                _grav_pw = act.player_width
                                _grav_ph = act.player_height
                                break
                        if _grav_grid_id:
                            break
                    # Fallback: first CollisionLayer in any scene
                    if not _grav_grid_id:
                        for _sc in project.scenes:
                            for _comp in _sc.components:
                                if _comp.component_type == "CollisionLayer":
                                    _grav_grid_id = _comp.id
                                    break
                            if _grav_grid_id:
                                break

                    _has_cboxes = _object_has_collision_boxes(od)
                    _cframe = f"{vname}_ani_frame" if od.behavior_type == "Animation" else "0"
                    _cslot = f"{vname}_ani_slot_name" if od.behavior_type == "Animation" else '""'
                    _cid = _lua_str(od.id)
                    if gdir in ("down", "up"):
                        new_pos_expr = f"{pos_var} + {vel_var}"
                        if _has_cboxes:
                            grid_check_expr = f"(_ggrid and check_obj_vs_grid(_ggrid, {_cid}, {other_pos}, _gnp, {_cslot}, {_cframe}))"
                            grid_test_expr = f"(_ggrid and check_obj_vs_grid(_ggrid, {_cid}, {other_pos}, _gtest, {_cslot}, {_cframe}))"
                        else:
                            grid_check_expr = f"(_ggrid and check_collision_rect(_ggrid, {other_pos}, _gnp, {_grav_pw}, {_grav_ph}))"
                            grid_test_expr = f"(_ggrid and check_collision_rect(_ggrid, {other_pos}, _gtest, {_grav_pw}, {_grav_ph}))"
                        solid_check_expr = f"check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, {other_pos}, _gnp, {_cslot}, {_cframe})"
                        solid_test_expr = f"check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, {other_pos}, _gtest, {_cslot}, {_cframe})"
                    else:
                        new_pos_expr = f"{pos_var} + {vel_var}"
                        if _has_cboxes:
                            grid_check_expr = f"(_ggrid and check_obj_vs_grid(_ggrid, {_cid}, _gnp, {other_pos}, {_cslot}, {_cframe}))"
                            grid_test_expr = f"(_ggrid and check_obj_vs_grid(_ggrid, {_cid}, _gtest, {other_pos}, {_cslot}, {_cframe}))"
                        else:
                            grid_check_expr = f"(_ggrid and check_collision_rect(_ggrid, _gnp, {other_pos}, {_grav_pw}, {_grav_ph}))"
                            grid_test_expr = f"(_ggrid and check_collision_rect(_ggrid, _gtest, {other_pos}, {_grav_pw}, {_grav_ph}))"
                        solid_check_expr = f"check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, _gnp, {other_pos}, {_cslot}, {_cframe})"
                        solid_test_expr = f"check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, _gtest, {other_pos}, {_cslot}, {_cframe})"
                    if _grav_grid_id or scene_has_solid_blockers:
                        out.append(f"        do")
                        out.append(f"            local _ggrid = collision_grids[{_lua_str(_grav_grid_id)}]")
                        out.append(f"            local _gnp = {new_pos_expr}")
                        out.append(f"            local _blocked = false")
                        out.append(f"            if {grid_check_expr} then _blocked = true end")
                        out.append(f"            if not _blocked and {solid_check_expr} then _blocked = true end")
                        out.append(f"            if _blocked then")
                        out.append(f"                local function _grav_hits(_gtest)")
                        out.append(f"                    if {grid_test_expr} then return true end")
                        out.append(f"                    if {solid_test_expr} then return true end")
                        out.append(f"                    return false")
                        out.append(f"                end")
                        out.append(f"                local _step = 0")
                        out.append(f"                if _gnp > {pos_var} then _step = 1 elseif _gnp < {pos_var} then _step = -1 end")
                        out.append(f"                local _resolved = {pos_var}")
                        out.append(f"                if _step ~= 0 then")
                        out.append(f"                    if _grav_hits(_resolved) then")
                        out.append(f"                        local _tries = 0")
                        out.append(f"                        while _grav_hits(_resolved) and _tries < 2048 do")
                        out.append(f"                            _resolved = _resolved - _step")
                        out.append(f"                            _tries = _tries + 1")
                        out.append(f"                        end")
                        out.append(f"                    else")
                        out.append(f"                        local _tries = 0")
                        out.append(f"                        while _tries < 2048 do")
                        out.append(f"                            local _next = _resolved + _step")
                        out.append(f"                            if (_step > 0 and _next > _gnp) or (_step < 0 and _next < _gnp) then _next = _gnp end")
                        out.append(f"                            if _grav_hits(_next) then break end")
                        out.append(f"                            _resolved = _next")
                        out.append(f"                            if _resolved == _gnp then break end")
                        out.append(f"                            _tries = _tries + 1")
                        out.append(f"                        end")
                        out.append(f"                    end")
                        out.append(f"                end")
                        out.append(f"                {pos_var} = _resolved")
                        out.append(f"                {vel_var} = 0")
                        out.append(f"            else")
                        out.append(f"                {pos_var} = _gnp")
                        out.append(f"            end")
                        out.append(f"        end")
                    else:
                        out.append(f"        {pos_var} = {pos_var} + {vel_var}")

                    # --- jump state management ---
                    _has_jump = any(
                        act.action_type == "jump"
                        for beh in _all_behaviors
                        for act in beh.actions
                    )
                    if _has_jump:
                        _jump_act = next(
                            act
                            for beh in _all_behaviors
                            for act in beh.actions
                            if act.action_type == "jump"
                        )
                        _btn        = _jump_act.jump_button
                        _var_height = _jump_act.jump_variable_height
                        _min_vy     = _jump_act.jump_variable_min_vy
                        _do_float   = _jump_act.jump_float
                        _float_mult = _jump_act.jump_float_gravity_mult
                        _grid_id    = _jump_act.jump_collision_layer_id or _grav_grid_id
                        _has_cboxes = _object_has_collision_boxes(od)

                        # Grounded reset: vy was zeroed by collision this frame = landed
                        out.append(f"        -- jump: grounded reset")
                        out.append(f"        if {vel_var} == 0 and {vname}_jump_count > 0 then")
                        if _grid_id or scene_has_solid_blockers:
                            _cframe = f"{vname}_ani_frame" if od.behavior_type == "Animation" else "0"
                            _cslot  = f"{vname}_ani_slot_name" if od.behavior_type == "Animation" else '""'
                            _cid    = _lua_str(od.id)
                            out.append(f"            do")
                            out.append(f"                local _jgrid = collision_grids[{_lua_str(_grid_id)}]")
                            out.append(f"                local _probe = {pos_var} + {sign}")
                            out.append(f"                local _landed = false")
                            if gdir in ("down", "up"):
                                if _has_cboxes:
                                    out.append(f"                if _jgrid and check_obj_vs_grid(_jgrid, {_cid}, {other_pos}, _probe, {_cslot}, {_cframe}) then _landed = true end")
                                else:
                                    out.append(f"                if _jgrid and check_collision_rect(_jgrid, {other_pos}, _probe, {_jump_act.jump_player_width}, {_jump_act.jump_player_height}) then _landed = true end")
                                out.append(f"                if not _landed and check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, {other_pos}, _probe, {_cslot}, {_cframe}) then _landed = true end")
                            else:
                                if _has_cboxes:
                                    out.append(f"                if _jgrid and check_obj_vs_grid(_jgrid, {_cid}, _probe, {other_pos}, {_cslot}, {_cframe}) then _landed = true end")
                                else:
                                    out.append(f"                if _jgrid and check_collision_rect(_jgrid, _probe, {other_pos}, {_jump_act.jump_player_width}, {_jump_act.jump_player_height}) then _landed = true end")
                                out.append(f"                if not _landed and check_obj_vs_solids({_lua_str(po.instance_id)}, {_cid}, _probe, {other_pos}, {_cslot}, {_cframe}) then _landed = true end")
                            out.append(f"                if _landed then")
                            out.append(f"                    {vname}_jump_count = 0")
                            out.append(f"                end")
                            out.append(f"            end")
                        else:
                            out.append(f"            {vname}_jump_count = 0")
                        out.append(f"        end")

                        # Variable height: if button released early, clamp rising velocity
                        if _var_height:
                            _lpp_btn = _button_constant(_btn)
                            out.append(f"        -- jump: variable height")
                            out.append(f"        if {vel_var} < 0 and not controls_held({_lpp_btn}) then")
                            out.append(f"            {vname}_jump_button_held = false")
                            out.append(f"            if {vel_var} < -{_min_vy} then")
                            out.append(f"                {vel_var} = -{_min_vy}")
                            out.append(f"            end")
                            out.append(f"        end")

                        # Float: while rising and button held, reduce gravity effect
                        if _do_float:
                            _lpp_btn = _button_constant(_btn)
                            out.append(f"        -- jump: float")
                            out.append(f"        if {vel_var} < 0 and controls_held({_lpp_btn}) then")
                            _float_delta = round(sign * gstr * (1.0 - _float_mult), 4)
                            out.append(f"            {vel_var} = {vel_var} - {_float_delta}")
                            out.append(f"        end")

        # ── Layer scroll position advance ────────────────────────────────────
        for lc in scene_layers:
            lname     = _safe_name(lc.config.get("layer_name", "") or lc.id)
            speed     = lc.config.get("scroll_speed", 1)
            direction = lc.config.get("scroll_direction", "horizontal")
            if direction == "horizontal":
                out.append(f"        if layer_{lname}_scroll_enabled then")
                out.append(f"            layer_{lname}_scroll_x = layer_{lname}_scroll_x + {speed}")
                out.append(f"        end")
            else:
                out.append(f"        if layer_{lname}_scroll_enabled then")
                out.append(f"            layer_{lname}_scroll_y = layer_{lname}_scroll_y + {speed}")
                out.append(f"        end")

        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")

        layer_by_id = {lc.id: lc for lc in scene_layers}

        def _emit_layer_image(lc):
            lname = _safe_name(lc.config.get("layer_name", "") or lc.id)
            img = project.get_image(lc.config.get("image_id", ""))
            if not img or not img.path:
                return
            fname = _asset_filename(img.path)
            locked   = lc.config.get("screen_space_locked", False)
            parallax = lc.config.get("parallax", 1.0)
            tile_x   = lc.config.get("tile_x", False)
            tile_y   = lc.config.get("tile_y", False)

            out.append(f"        if layer_{lname}_visible and images[{_lua_str(fname)}] then")

            if tile_x or tile_y:
                # Compute base draw origin (same logic as non-tiled path)
                if locked:
                    out.append(f"            local _bx = (layer_{lname}_scroll_x or 0)")
                    out.append(f"            local _by = (layer_{lname}_scroll_y or 0)")
                else:
                    out.append(f"            local _lox, _loy = camera_bg_offset({parallax})")
                    out.append(f"            local _bx = _lox + (layer_{lname}_scroll_x or 0)" + (" + shake_offset_x" if not locked else ""))
                    out.append(f"            local _by = _loy + (layer_{lname}_scroll_y or 0)" + (" + shake_offset_y" if not locked else ""))

                out.append(f"            local _iw = Graphics.getImageWidth(images[{_lua_str(fname)}])")
                out.append(f"            local _ih = Graphics.getImageHeight(images[{_lua_str(fname)}])")

                if tile_x and tile_y:
                    # Wrap both axes so the scroll offset stays within one tile period
                    out.append(f"            local _ox = _bx % _iw")
                    out.append(f"            local _oy = _by % _ih")
                    out.append(f"            local _tx = -_iw + _ox")
                    out.append(f"            if _tx > 0 then _tx = _tx - _iw end")
                    out.append(f"            while _tx < 960 do")
                    out.append(f"                local _ty = -_ih + _oy")
                    out.append(f"                if _ty > 0 then _ty = _ty - _ih end")
                    out.append(f"                while _ty < 544 do")
                    out.append(f"                    Graphics.drawImage(_tx, _ty, images[{_lua_str(fname)}])")
                    out.append(f"                    _ty = _ty + _ih")
                    out.append(f"                end")
                    out.append(f"                _tx = _tx + _iw")
                    out.append(f"            end")
                elif tile_x:
                    out.append(f"            local _ox = _bx % _iw")
                    out.append(f"            local _tx = -_iw + _ox")
                    out.append(f"            if _tx > 0 then _tx = _tx - _iw end")
                    out.append(f"            while _tx < 960 do")
                    out.append(f"                Graphics.drawImage(_tx, _by, images[{_lua_str(fname)}])")
                    out.append(f"                _tx = _tx + _iw")
                    out.append(f"            end")
                else:  # tile_y only
                    out.append(f"            local _oy = _by % _ih")
                    out.append(f"            local _ty = -_ih + _oy")
                    out.append(f"            if _ty > 0 then _ty = _ty - _ih end")
                    out.append(f"            while _ty < 544 do")
                    out.append(f"                Graphics.drawImage(_bx, _ty, images[{_lua_str(fname)}])")
                    out.append(f"                _ty = _ty + _ih")
                    out.append(f"            end")
            else:
                # Original non-tiled draw path
                if locked:
                    out.append(f"            Graphics.drawImage((layer_{lname}_scroll_x or 0), (layer_{lname}_scroll_y or 0), images[{_lua_str(fname)}])")
                else:
                    out.append(f"            local _lox, _loy = camera_bg_offset({parallax})")
                    out.append(f"            Graphics.drawImage(_lox + (layer_{lname}_scroll_x or 0) + shake_offset_x, _loy + (layer_{lname}_scroll_y or 0) + shake_offset_y, images[{_lua_str(fname)}])")

            out.append("        end")

        def _emit_object_draw(po, locked=False):
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                return
            vname = _placed_var_name(po)
            ws_call = f"local _sx, _sy = {vname}_x, {vname}_y" if locked else f"local _sx, _sy = world_to_screen({vname}_x, {vname}_y)"
            shk_x = "" if locked else " + shake_offset_x"
            shk_y = "" if locked else " + shake_offset_y"

            if od.behavior_type == "GUI_Panel":
                hx = od.gui_bg_color.lstrip('#')
                pr, pg, pb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
                out.append(f'        if {vname}_visible then')
                out.append(f'            local _pc = Color.new({pr}, {pg}, {pb}, {od.gui_bg_opacity})')
                out.append(f'            Graphics.fillRect({vname}_x{shk_x}, {vname}_x + {od.gui_width}{shk_x}, {vname}_y{shk_y}, {vname}_y + {od.gui_height}{shk_y}, _pc)')
                out.append(f'        end')
            elif od.behavior_type == "GUI_Label":
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'
                align = od.gui_text_align
                has_bg = od.gui_bg_opacity > 0
                out.append(f'        if {vname}_visible and {font_var} then')
                if has_bg:
                    hx_bg = od.gui_bg_color.lstrip('#')
                    bgr, bgg, bgb = int(hx_bg[0:2], 16), int(hx_bg[2:4], 16), int(hx_bg[4:6], 16)
                    out.append(f'            local _lbg = Color.new({bgr}, {bgg}, {bgb}, {od.gui_bg_opacity})')
                    out.append(f'            Graphics.fillRect({vname}_x{shk_x}, {vname}_x + {od.gui_width}{shk_x}, {vname}_y{shk_y}, {vname}_y + {od.gui_height}{shk_y}, _lbg)')
                out.append(f'            Font.setPixelSizes({font_var}, {vname}_font_size)')
                out.append(f'            local _lc = Color.new({vname}_text_r, {vname}_text_g, {vname}_text_b)')
                if align == "center":
                    out.append(f'            local _tw = Font.getTextWidth({font_var}, {vname}_text)')
                    out.append(f'            local _tx = {vname}_x + math.floor(({od.gui_width} - _tw) / 2)')
                    out.append(f'            Font.print({font_var}, _tx{shk_x}, {vname}_y{shk_y}, {vname}_text, _lc)')
                elif align == "right":
                    out.append(f'            local _tw = Font.getTextWidth({font_var}, {vname}_text)')
                    out.append(f'            local _tx = {vname}_x + {od.gui_width} - _tw')
                    out.append(f'            Font.print({font_var}, _tx{shk_x}, {vname}_y{shk_y}, {vname}_text, _lc)')
                else:
                    out.append(f'            Font.print({font_var}, {vname}_x{shk_x}, {vname}_y{shk_y}, {vname}_text, _lc)')
                out.append(f'        end')
            elif od.behavior_type == "GUI_Button":
                hx_bg = od.gui_bg_color.lstrip('#')
                br, bg_g, bb = int(hx_bg[0:2], 16), int(hx_bg[2:4], 16), int(hx_bg[4:6], 16)
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'
                out.append(f'        if {vname}_visible then')
                bg_img = None
                if od.gui_image_id:
                    bi = project.get_image(od.gui_image_id)
                    if bi and bi.path:
                        bg_img = _asset_filename(bi.path)
                if bg_img:
                    out.append(f'            if images[{_lua_str(bg_img)}] then Graphics.drawImage({vname}_x{shk_x}, {vname}_y{shk_y}, images[{_lua_str(bg_img)}]) end')
                else:
                    out.append(f'            local _bc = Color.new({br}, {bg_g}, {bb}, {od.gui_bg_opacity})')
                    out.append(f'            Graphics.fillRect({vname}_x{shk_x}, {vname}_x + {od.gui_width}{shk_x}, {vname}_y{shk_y}, {vname}_y + {od.gui_height}{shk_y}, _bc)')
                out.append(f'            if {font_var} then')
                out.append(f'                Font.setPixelSizes({font_var}, {vname}_font_size)')
                out.append(f'                local _tc = Color.new({vname}_text_r, {vname}_text_g, {vname}_text_b)')
                out.append(f'                Font.print({font_var}, {vname}_x + 8{shk_x}, {vname}_y + 8{shk_y}, tostring({vname}_text or ""), _tc)')
                out.append(f'            end')
                out.append(f'        end')
            elif od.behavior_type == "Animation":
                if od.ani_slots:
                    # Compute scale ratio using the first slot's AnimationExport
                    first_fid  = od.ani_slots[0].get("ani_file_id", "")
                    ani_export = project.get_animation_export(first_fid) if first_fid else None
                    if ani_export and ani_export.frame_width > 0 and ani_export.frame_height > 0:
                        ani_sx = od.width / ani_export.frame_width
                        ani_sy = od.height / ani_export.frame_height
                    else:
                        ani_sx = 1.0
                        ani_sy = 1.0
                    out.append(f'        if {vname}_visible then')
                    out.append(f'            {ws_call}')
                    out.append(f'            local _ani_d = ani_data[{vname}_ani_id]')
                    out.append(f'            if _ani_d then')
                    out.append(f'                local _sheet, _fsx, _fsy, _fw2, _fh2 = ani_get_sheet_and_rect({vname}_ani_id, {vname}_ani_frame)')
                    out.append(f'                if _sheet then')
                    out.append(f'                local _asx  = {ani_sx}')
                    out.append(f'                local _asy  = {ani_sy}')
                    out.append(f'                local _fh   = _ani_d.frame_height * _asy * {vname}_scale * camera.zoom')
                    out.append(f'                local _fsx2 = _asx * {vname}_scale * camera.zoom * ({vname}_flip_h and -1 or 1)')
                    out.append(f'                local _fsy2 = _asy * {vname}_scale * camera.zoom * ({vname}_flip_v and -1 or 1)')
                    out.append(f'                local _fw   = _ani_d.frame_width  * math.abs(_fsx2)')
                    out.append(f'                local _ox   = _sx + _fw * 0.5{shk_x}')
                    out.append(f'                local _oy   = _sy + _fh * 0.5{shk_y}')
                    out.append(f'                local _tc   = Color.new(255, 255, 255, {vname}_opacity)')
                    out.append(f'                Graphics.drawImageExtended(_ox, _oy, _sheet, _fsx, _fsy, _ani_d.frame_width, _ani_d.frame_height, {vname}_rotation * (math.pi / 180), _fsx2, _fsy2, _tc)')
                    out.append(f'                end')
                    out.append(f'            end')
                    out.append(f'        end')
            elif od.behavior_type == "LayerAnimation":
                if od.layer_anim_id:
                    out.append(f'        if {vname}_visible and {vname}_pdoll then')
                    out.append(f'            {ws_call}')
                    out.append(f'            pdoll_draw({vname}_pdoll, _sx{shk_x}, _sy{shk_y}, {vname}_scale * camera.zoom, {vname}_rotation, {vname}_opacity)')
                    out.append(f'        end')
            else:
                if od.frames:
                    if len(od.frames) > 1:
                        # Multi-frame regular object: pick the current frame at runtime
                        # Build the fallback filename from frames[0] for safety
                        _fb_img  = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
                        _fb_name = _asset_filename(_fb_img.path) if (_fb_img and _fb_img.path) else ""
                        out.append(f'        if {vname}_visible then')
                        out.append(f'            {ws_call}')
                        out.append(f'            local _fdef = {vname}_frames[{vname}_frame]')
                        out.append(f'            local _fname = (_fdef and _fdef.img ~= "") and _fdef.img or {_lua_str(_fb_name)}')
                        out.append(f'            local _img = (_fname ~= "") and images[_fname] or nil')
                        out.append(f'            if _img then')
                        out.append(f'                local _iw = Graphics.getImageWidth(_img)')
                        out.append(f'                local _ih = Graphics.getImageHeight(_img)')
                        out.append(f'                local _tc = Color.new(255, 255, 255, {vname}_opacity)')
                        out.append(f'                local _sw = _iw * {vname}_scale * camera.zoom')
                        out.append(f'                local _sh = _ih * {vname}_scale * camera.zoom')
                        out.append(f'                local _ox = _sx + _sw * 0.5{shk_x}')
                        out.append(f'                local _oy = _sy + _sh * 0.5{shk_y}')
                        out.append(f'                Graphics.drawImageExtended(_ox, _oy, _img, 0, 0, _iw, _ih, {vname}_rotation * (math.pi / 180), {vname}_scale * camera.zoom, {vname}_scale * camera.zoom, _tc)')
                        out.append(f'            end')
                        out.append(f'        end')
                    else:
                        # Single-frame object: static, always draws frames[0]
                        img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
                        if img and img.path:
                            fname = _asset_filename(img.path)
                            out.append(f'        if {vname}_visible and images[{_lua_str(fname)}] then')
                            out.append(f'            {ws_call}')
                            out.append(f'            local _iw = Graphics.getImageWidth(images[{_lua_str(fname)}])')
                            out.append(f'            local _ih = Graphics.getImageHeight(images[{_lua_str(fname)}])')
                            out.append(f'            local _tc = Color.new(255, 255, 255, {vname}_opacity)')
                            out.append(f'            local _sw = _iw * {vname}_scale * camera.zoom')
                            out.append(f'            local _sh = _ih * {vname}_scale * camera.zoom')
                            out.append(f'            local _ox = _sx + _sw * 0.5{shk_x}')
                            out.append(f'            local _oy = _sy + _sh * 0.5{shk_y}')
                            out.append(f'            Graphics.drawImageExtended(_ox, _oy, images[{_lua_str(fname)}], 0, 0, _iw, _ih, {vname}_rotation * (math.pi / 180), {vname}_scale * camera.zoom, {vname}_scale * camera.zoom, _tc)')
                            out.append(f'        end')
                else:
                    all_behs = effective_placed_behaviors(po, od)
                    is_zone_obj = any(b.trigger in ("on_enter","on_exit","on_overlap","on_interact_zone") for b in all_behs)
                    if is_zone_obj:
                        zw = int(od.width * po.scale)
                        zh = int(od.height * po.scale)
                        out.append(f'        if {vname}_visible then')
                        out.append(f'            {ws_call}')
                        out.append(f'            local _zc = Color.new(0, 255, 0, 80)')
                        out.append(f'            Graphics.fillRect(_sx{shk_x}, _sx + {zw}{shk_x}, _sy{shk_y}, _sy + {zh}{shk_y}, _zc)')
                        out.append(f'        end')

        draw_slots = []
        for lc in scene_layers:
            draw_slots.append((lc.config.get("layer", 0), "layer", lc))
        for comp in scene.components:
            if comp.component_type == "TileLayer":
                dl = comp.config.get("draw_layer", 0)
                draw_slots.append((dl - 0.1, "tilelayer", comp))

        layer_object_groups: dict[str, list] = {}
        world_objects_by_layer: dict[int, list] = {}
        for po in scene.placed_objects:
            lid = getattr(po, "layer_id", "")
            if lid and lid in layer_by_id:
                layer_object_groups.setdefault(lid, []).append(po)
            else:
                dl = getattr(po, "draw_layer", 2)
                world_objects_by_layer.setdefault(dl, []).append(po)

        for dl, objects in world_objects_by_layer.items():
            draw_slots.append((dl, "objects", (objects, False)))
        for lid, objects in layer_object_groups.items():
            lc = layer_by_id[lid]
            order = lc.config.get("layer", 0) + 0.5
            locked = lc.config.get("screen_space_locked", False)
            draw_slots.append((order, "objects", (objects, locked)))

        draw_slots.sort(key=lambda e: e[0])

        for _order, kind, payload in draw_slots:
            if kind == "layer":
                _emit_layer_image(payload)
            elif kind == "tilelayer":
                comp = payload
                ts_id = comp.config.get("tileset_id")
                if ts_id:
                    ts = project.get_tileset(ts_id)
                    if ts:
                        import math
                        safe_id  = comp.id.replace("-", "_")
                        map_w    = comp.config.get("map_width",  30)
                        map_h    = comp.config.get("map_height", 17)
                        world_w  = map_w * ts.tile_size
                        world_h  = map_h * ts.tile_size
                        chunks_x = math.ceil(world_w / CHUNK_SIZE)
                        chunks_y = math.ceil(world_h / CHUNK_SIZE)
                        out.append(f"        -- TileLayer {safe_id}")
                        out.append(f"        do")
                        out.append(f"            local _z  = camera.zoom")
                        out.append(f"            local _cl = camera.x - 480")
                        out.append(f"            local _ct = camera.y - 272")
                        out.append(f"            local _cx0 = math.floor(_cl / {CHUNK_SIZE})")
                        out.append(f"            local _cy0 = math.floor(_ct / {CHUNK_SIZE})")
                        out.append(f"            for _dcy = _cy0, _cy0 + 1 do")
                        out.append(f"                for _dcx = _cx0 - 1, _cx0 + 2 do")
                        out.append(f"                    if _dcx >= 0 and _dcx < {chunks_x} and _dcy >= 0 and _dcy < {chunks_y} then")
                        out.append(f"                        local _k = 'tl_{safe_id}_' .. _dcx .. '_' .. _dcy")
                        out.append(f"                        local _im = tile_chunks[_k]")
                        out.append(f"                        if _im then")
                        out.append(f"                            local _wx = _dcx * {CHUNK_SIZE}")
                        out.append(f"                            local _wy = _dcy * {CHUNK_SIZE}")
                        out.append(f"                            local _dx = (_wx - camera.x) * _z + 480 + shake_offset_x")
                        out.append(f"                            local _dy = (_wy - camera.y) * _z + 272 + shake_offset_y")
                        out.append(f"                            Graphics.drawScaleImage(_dx, _dy, _im, _z, _z, Color.new(255, 255, 255, 255))")
                        out.append(f"                        end")
                        out.append(f"                    end")
                        out.append(f"                end")
                        out.append(f"            end")
                        out.append(f"        end")
            else:
                objects, locked = payload
                for po in objects:
                    _emit_object_draw(po, locked=locked)

        # ── Focus rectangle ─────────────────────────────────────────────
        if nav_objects:
            out.append("        -- focus rectangle")
            out.append("        if _focused_obj then")
            for _npo, _nod in nav_objects:
                vn = _placed_var_name(_npo)
                handle = _npo.instance_id
                if _nod.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                    fw = _nod.gui_width
                    fh = _nod.gui_height
                    # GUI objects use screen-space coords directly
                    out.append(f"            if _focused_obj == {_lua_str(handle)} and {vn}_visible then")
                    out.append(f"                local _fr = Color.new(255, 255, 255, 200)")
                    t = 2
                    out.append(f"                Graphics.fillRect({vn}_x, {vn}_x + {fw}, {vn}_y, {vn}_y + {t}, _fr)")
                    out.append(f"                Graphics.fillRect({vn}_x, {vn}_x + {fw}, {vn}_y + {fh} - {t}, {vn}_y + {fh}, _fr)")
                    out.append(f"                Graphics.fillRect({vn}_x, {vn}_x + {t}, {vn}_y, {vn}_y + {fh}, _fr)")
                    out.append(f"                Graphics.fillRect({vn}_x + {fw} - {t}, {vn}_x + {fw}, {vn}_y, {vn}_y + {fh}, _fr)")
                    out.append(f"            end")
                else:
                    fw = int(_nod.width  * _npo.scale)
                    fh = int(_nod.height * _npo.scale)
                    out.append(f"            if _focused_obj == {_lua_str(handle)} and {vn}_visible then")
                    out.append(f"                local _fsx, _fsy = world_to_screen({vn}_x, {vn}_y)")
                    out.append(f"                local _fsx2 = _fsx + shake_offset_x")
                    out.append(f"                local _fsy2 = _fsy + shake_offset_y")
                    out.append(f"                local _fw = math.floor({fw} * camera.zoom)")
                    out.append(f"                local _fh = math.floor({fh} * camera.zoom)")
                    out.append(f"                local _fr = Color.new(255, 255, 255, 200)")
                    t = 2
                    out.append(f"                Graphics.fillRect(_fsx2, _fsx2 + _fw, _fsy2, _fsy2 + {t}, _fr)")
                    out.append(f"                Graphics.fillRect(_fsx2, _fsx2 + _fw, _fsy2 + _fh - {t}, _fsy2 + _fh, _fr)")
                    out.append(f"                Graphics.fillRect(_fsx2, _fsx2 + {t}, _fsy2, _fsy2 + _fh, _fr)")
                    out.append(f"                Graphics.fillRect(_fsx2 + _fw - {t}, _fsx2 + _fw, _fsy2, _fsy2 + _fh, _fr)")
                    out.append(f"            end")
            out.append("        end")

        if vn_comp:
            cfg       = vn_comp.config
            fill      = cfg.get("fill_color", "#000000")
            opacity   = cfg.get("opacity", 150)
            r, g, b   = int(fill[1:3], 16), int(fill[3:5], 16), int(fill[5:7], 16)
            tex_id    = cfg.get("texture_image_id")
            if tex_id:
                tex_img = project.get_image(tex_id)
                if tex_img and tex_img.path:
                    fname = _asset_filename(tex_img.path)
                    out.append(f'        if images[{_lua_str(fname)}] then')
                    out.append(f'            Graphics.drawPartialImage(40 + shake_offset_x, 335 + shake_offset_y, images[{_lua_str(fname)}], 0, 0, 880, 200)')
                    out.append(f'        else')
                    out.append(f'            local box_col = Color.new({r}, {g}, {b}, {opacity})')
                    out.append(f'            Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, box_col)')
                    out.append(f'        end')
            else:
                out.append(f'        local box_col = Color.new({r}, {g}, {b}, {opacity})')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, box_col)')
            if cfg.get("border", False):
                bc            = cfg.get("border_color", "#ffffff")
                br2, bg2, bb2 = int(bc[1:3], 16), int(bc[3:5], 16), int(bc[5:7], 16)
                thick         = cfg.get("border_thickness", 2)
                out.append(f'        local border_col = Color.new({br2}, {bg2}, {bb2})')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, {335+thick} + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, {535-thick} + shake_offset_y, 535 + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, {40+thick} + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect({920-thick} + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, border_col)')
            tc            = cfg.get("text_color", "#ffffff")
            tr2, tg2, tb2 = int(tc[1:3], 16), int(tc[3:5], 16), int(tc[5:7], 16)
            shadow        = cfg.get("shadow", True)
            out.append(f'        local txt_col = Color.new({tr2}, {tg2}, {tb2})')
            font_id  = cfg.get("font_id")
            font_var = "deff"
            if font_id:
                fnt = project.get_font(font_id)
                if fnt and fnt.path:
                    fname    = _asset_filename(fnt.path)
                    font_var = f'fonts[{_lua_str(fname)}]'
            # Draw current page speaker name + lines from _vn_pages table
            vn_font_size   = cfg.get("font_size", 16)
            vn_line_spacing = cfg.get("line_spacing", 35)
            out.append(f'        if {font_var} then Font.setPixelSizes({font_var}, {vn_font_size}) end')
            nametag_pos = cfg.get("nametag_position", "inside box top")
            nc          = cfg.get("nametag_color", "#333333")
            nr, ng, nb  = int(nc[1:3], 16), int(nc[3:5], 16), int(nc[5:7], 16)
            name_y      = 345 if nametag_pos == "inside box top" else 320
            tag_bg_y    = name_y - 5
            out.append(f'        local _cp = _vn_pages[_vn_page]')
            out.append(f'        if _cp.character ~= "" then')
            out.append(f'            local tag_col = Color.new({nr}, {ng}, {nb}, 200)')
            out.append(f'            Graphics.fillRect(40 + shake_offset_x, 240 + shake_offset_x, {tag_bg_y} + shake_offset_y, {tag_bg_y+26} + shake_offset_y, tag_col)')
            if shadow:
                out.append(f'            if {font_var} then Font.print({font_var}, 62 + shake_offset_x, {name_y+2} + shake_offset_y, _cp.character, Color.new(0,0,0)) end')
            out.append(f'            if {font_var} then Font.print({font_var}, 60 + shake_offset_x, {name_y} + shake_offset_y, _cp.character, txt_col) end')
            out.append(f'        end')
            out.append(f'        local _ly = 383')
            out.append(f'        local _chars_left = math.floor(_vn_char_idx)')
            out.append(f'        local _vn_frame = Timer.getTime(_scene_timer)')
            out.append(f'        for _li = 1, #_cp.lines do')
            out.append(f'            local _ln = _cp.lines[_li]')
            out.append(f'            if _ln ~= "" then')
            out.append(f'                local _visible = nil')
            out.append(f'                if _cp.typewriter and not _vn_tw_done then')
            out.append(f'                    local _plain_len = #_vn_strip_tags(_ln)')
            out.append(f'                    if _chars_left <= 0 then _visible = 0')
            out.append(f'                    elseif _chars_left < _plain_len then _visible = _chars_left')
            out.append(f'                    end')
            out.append(f'                    _chars_left = _chars_left - _plain_len')
            out.append(f'                end')
            out.append(f'                if {font_var} then')
            out.append(f'                    _vn_draw_line({font_var}, _ln, 60 + shake_offset_x, _ly + shake_offset_y, txt_col, _visible, _vn_frame, {str(shadow).lower()})')
            out.append(f'                end')
            out.append(f'            end')
            out.append(f'            _ly = _ly + {vn_line_spacing}')
            out.append(f'        end')

        out.append("        -- update and draw dynamically created objects")
        out.append("        for _liid, _lo in pairs(_live_objects) do")
        out.append("            -- cull if off screen (with margin)")
        out.append("            local _lsx, _lsy = world_to_screen(_lo.x, _lo.y)")
        out.append("            local _margin = 200")
        out.append("            if _lsx < -_margin or _lsx > 960 + _margin or _lsy < -_margin or _lsy > 544 + _margin then")
        out.append("                prim.unregister(_liid)")
        out.append("                _live_objects[_liid] = nil")
        out.append("            elseif _lo.visible then")
        out.append("                local _limg = _lo.image and images[_lo.image]")
        out.append("                if _limg then")
        out.append("                    local _liw = Graphics.getImageWidth(_limg)")
        out.append("                    local _lih = Graphics.getImageHeight(_limg)")
        out.append("                    local _ltc = Color.new(255, 255, 255, _lo.opacity)")
        out.append("                    local _lsw = _liw * _lo.scale * camera.zoom")
        out.append("                    local _lsh = _lih * _lo.scale * camera.zoom")
        out.append("                    local _lox = _lsx + _lsw * 0.5 + shake_offset_x")
        out.append("                    local _loy = _lsy + _lsh * 0.5 + shake_offset_y")
        out.append("                    Graphics.drawImageExtended(_lox, _loy, _limg, 0, 0, _liw, _lih, _lo.angle * (math.pi / 180), _lo.scale * camera.zoom, _lo.scale * camera.zoom, _ltc)")
        out.append("                end")
        out.append("            end")
        out.append("        end")

        for comp in scene.components:
            if comp.component_type != "LightmapLayer":
                continue
            out.append(f"        draw_light_grid(light_grids[{_lua_str(comp.id)}])")

        for line in _plugin_scene_hook_lines(scene, project, "lua_scene_draw"):
            out.append(f"        {line}")
        out.append("        flash_draw()")
        out.append("        if _fade_alpha > 0 then")
        out.append("            local _fa = math.floor(_fade_alpha)")
        out.append("            if _fa > 255 then _fa = 255 end")
        out.append("            Graphics.fillRect(0, 960, 0, 544, Color.new(0, 0, 0, _fa))")
        out.append("        end")
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")

        out.append("        if controls_released(SCE_CTRL_START) then")
        out.append("            if current_music then Sound.close(current_music) end")
        out.append("            os.exit()")
        out.append("        end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname         = _placed_var_name(po)
                all_behaviors = effective_placed_behaviors(po, od)
                for beh in all_behaviors:
                    if beh.trigger == "on_input" and beh.input_action_name:
                        ia = next((a for a in project.game_data.input_actions
                                   if a.name == beh.input_action_name), None)
                        if ia:
                            src = getattr(ia, "source_type", "button")
                            if src == "stick_direction":
                                # ── Stick-direction input action ──────────────────
                                _stick = getattr(ia, "stick", "left")
                                _dir   = getattr(ia, "direction", "up")
                                _dz    = getattr(ia, "deadzone", 32)
                                if ia.event == "hold_for":
                                    timer_var = f"_hold_{_safe_name(ia.name)}_timer"
                                    frames    = int(ia.hold_duration * 60)
                                    out.append(f"        if stick_dir_held('{_stick}', '{_dir}', {_dz}) then")
                                    out.append(f"            {timer_var} = {timer_var} + 1")
                                    out.append(f"            if {timer_var} == {frames} then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"                {line}")
                                    out.append(f"            end")
                                    out.append(f"        else")
                                    out.append(f"            {timer_var} = 0")
                                    out.append(f"        end")
                                elif ia.event == "pressed":
                                    out.append(f"        if stick_dir_pressed('{_stick}', '{_dir}', {_dz}) then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"            {line}")
                                    out.append(f"        end")
                                elif ia.event == "released":
                                    out.append(f"        if stick_dir_released('{_stick}', '{_dir}', {_dz}) then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"            {line}")
                                    out.append(f"        end")
                                else:  # held
                                    out.append(f"        if stick_dir_held('{_stick}', '{_dir}', {_dz}) then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"            {line}")
                                    out.append(f"        end")
                            else:
                                # ── Button input action (original logic, unchanged) ─
                                btn = _button_constant(ia.button)
                                if ia.event == "hold_for":
                                    timer_var = f"_hold_{_safe_name(ia.name)}_timer"
                                    frames    = int(ia.hold_duration * 60)
                                    out.append(f"        if controls_held({btn}) then")
                                    out.append(f"            {timer_var} = {timer_var} + 1")
                                    out.append(f"            if {timer_var} == {frames} then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"                {line}")
                                    out.append(f"            end")
                                    out.append(f"        else")
                                    out.append(f"            {timer_var} = 0")
                                    out.append(f"        end")
                                else:
                                    fn_check = _event_check(ia.event)
                                    out.append(f"        if {fn_check}({btn}) then")
                                    for action in beh.actions:
                                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                                            out.append(f"            {line}")
                                    out.append(f"        end")

        if vn_comp:
            cfg = vn_comp.config
            btn_const = {
                "cross":    "SCE_CTRL_CROSS",
                "circle":   "SCE_CTRL_CIRCLE",
                "square":   "SCE_CTRL_SQUARE",
                "triangle": "SCE_CTRL_TRIANGLE",
            }.get(cfg.get("advance_button", "cross"), "SCE_CTRL_CROSS")
            out.append(f"        if controls_released({btn_const}) then")
            out.append(f"            local _cp = _vn_pages[_vn_page]")
            out.append(f"            if _cp.typewriter and not _vn_tw_done then")
            out.append(f"                _vn_tw_done = true")
            out.append(f"                local _total = 0")
            out.append(f"                for _i = 1, #_cp.lines do _total = _total + #_vn_strip_tags(_cp.lines[_i]) end")
            out.append(f"                _vn_char_idx = _total")
            # button-skipped typewriter to done: stop talk
            for po2 in scene.placed_objects:
                od2 = project.get_object_def(po2.object_def_id)
                if od2 and od2.behavior_type == "LayerAnimation" and od2.layer_anim_talk and od2.layer_anim_id:
                    vn2 = _placed_var_name(po2)
                    out.append(f"                {vn2}_pdoll.talk_active = false")
                    out.append(f"                {vn2}_pdoll.talk_open   = false")
            if vn_dialog_cfg and vn_dialog_cfg["mode"] in ("loop", "play_once"):
                fname = vn_dialog_cfg["fname"]
                out.append(f"                do")
                out.append(f"                    local _ds = audio_tracks[{_lua_str(fname)}]")
                out.append(f"                    if _ds then Sound.stop(_ds) end")
                out.append(f"                end")
            out.append(f"            elseif _cp.advance_to_next then")
            out.append(f"                current_scene = current_scene + 1")
            out.append(f"                advance = true")
            out.append(f"            elseif _vn_page < _vn_page_count then")
            out.append(f"                _vn_page = _vn_page + 1")
            out.append(f"                _vn_char_idx = 0")
            out.append(f"                _vn_tw_done = false")
            out.append(f"                _vn_prev_time = Timer.getTime(_scene_timer)")
            # new page: start talk if it has typewriter
            out.append(f"                local _np = _vn_pages[_vn_page]")
            out.append(f"                if _np.typewriter then")
            for po2 in scene.placed_objects:
                od2 = project.get_object_def(po2.object_def_id)
                if od2 and od2.behavior_type == "LayerAnimation" and od2.layer_anim_talk and od2.layer_anim_id:
                    vn2 = _placed_var_name(po2)
                    out.append(f"                    {vn2}_pdoll.talk_active = true")
            if vn_dialog_cfg:
                fname = vn_dialog_cfg["fname"]
                mode  = vn_dialog_cfg["mode"]
                out.append(f"                    do")
                out.append(f"                        local _ds = audio_tracks[{_lua_str(fname)}]")
                out.append(f"                        if _ds then Sound.play(_ds, {_lua_bool(mode == 'loop')}) end")
                out.append(f"                    end")
            out.append(f"                end")
            if cfg.get("auto_advance", False):
                out.append(f"                auto_advance_timer = 0")
            out.append(f"            end")
            out.append(f"        end")
            if cfg.get("auto_advance", False):
                secs   = cfg.get("auto_advance_secs", 3.0)
                ms_threshold = int(secs * 1000)
                out.append(f"        if _vn_tw_done or not _vn_pages[_vn_page].typewriter then")
                out.append(f"            auto_advance_timer = auto_advance_timer + _vn_frame_ms")
                out.append(f"        end")
                out.append(f"        if auto_advance_timer >= {ms_threshold} then")
                out.append(f"            local _cp = _vn_pages[_vn_page]")
                out.append(f"            if _cp.advance_to_next then")
                out.append(f"                current_scene = current_scene + 1")
                out.append(f"                advance = true")
                out.append(f"            elseif _vn_page < _vn_page_count then")
                out.append(f"                _vn_page = _vn_page + 1")
                out.append(f"                _vn_char_idx = 0")
                out.append(f"                _vn_tw_done = false")
                out.append(f"                _vn_prev_time = Timer.getTime(_scene_timer)")
                out.append(f"                auto_advance_timer = 0")
                # new page: start talk if it has typewriter
                out.append(f"                local _np2 = _vn_pages[_vn_page]")
                out.append(f"                if _np2.typewriter then")
                for po2 in scene.placed_objects:
                    od2 = project.get_object_def(po2.object_def_id)
                    if od2 and od2.behavior_type == "LayerAnimation" and od2.layer_anim_talk and od2.layer_anim_id:
                        vn2 = _placed_var_name(po2)
                        out.append(f"                    {vn2}_pdoll.talk_active = true")
                if vn_dialog_cfg:
                    fname = vn_dialog_cfg["fname"]
                    mode  = vn_dialog_cfg["mode"]
                    out.append(f"                    do")
                    out.append(f"                        local _ds = audio_tracks[{_lua_str(fname)}]")
                    out.append(f"                        if _ds then Sound.play(_ds, {_lua_bool(mode == 'loop')}) end")
                    out.append(f"                    end")
                out.append(f"                end")
                out.append(f"            end")
                out.append(f"        end")

        # ── FPS cap: wait until 16 ms have elapsed ─────────────────────
        if project.game_data.fps_cap_enabled:
            out.append("        while Timer.getTime(_frame_timer) < 16 do end")
            out.append("        Timer.reset(_frame_timer)")

        out.append("    end")

        # ── Destroy FPS cap timer ─────────────────────────────────────
        if project.game_data.fps_cap_enabled:
            out.append("    Timer.destroy(_frame_timer)")

        trans_comp = next((c for c in scene.components if c.component_type == "Transition"), None)
        if trans_comp:
            trans_id     = trans_comp.config.get("trans_file_id", "")
            fps_override = trans_comp.config.get("trans_fps_override", 0)
            if trans_id:
                if fps_override > 0:
                    out.append(f"    play_transition({_lua_str(trans_id)}, {fps_override})")
                else:
                    out.append(f"    play_transition({_lua_str(trans_id)}, nil)")

    out.append("end")
    out.append("")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
#  3D SCENE → LUA
# ─────────────────────────────────────────────────────────────

def _collect_all_image_paths(project) -> list[str]:
    """Collect every image path that will be loaded into the export."""
    all_image_paths: set[str] = set()
    for scene in project.scenes:
        for comp in scene.components:
            if comp.component_type == "Layer":
                img = project.get_image(comp.config.get("image_id", ""))
                if img and img.path:
                    all_image_paths.add(img.path)
    for od in project.object_defs:
        for fr in od.frames:
            img = project.get_image(fr.image_id) if fr.image_id else None
            if img and img.path:
                all_image_paths.add(img.path)
        if od.gui_image_id:
            img = project.get_image(od.gui_image_id)
            if img and img.path:
                all_image_paths.add(img.path)
    for scene in project.scenes:
        if getattr(scene, "scene_type", "2d") == "3d":
            skybox_id = getattr(scene.map_data, "skybox_image_id", "")
            if skybox_id:
                img = project.get_image(skybox_id)
                if img and img.path:
                    all_image_paths.add(img.path)
            for po in scene.placed_objects:
                if getattr(po, "is_3d", False):
                    od = project.get_object_def(po.object_def_id)
                    if od:
                        for fr in od.frames:
                            img = project.get_image(fr.image_id) if fr.image_id else None
                            if img and img.path:
                                all_image_paths.add(img.path)

    def _collect_pdoll_layer_images(layers):
        for layer in layers:
            if layer.image_id:
                img = project.get_image(layer.image_id)
                if img and img.path:
                    all_image_paths.add(img.path)
            _collect_pdoll_layer_images(layer.children)

    for doll in project.paper_dolls:
        _collect_pdoll_layer_images(doll.root_layers)
        if doll.blink.alt_image_id:
            img = project.get_image(doll.blink.alt_image_id)
            if img and img.path:
                all_image_paths.add(img.path)
        mouth_image_ids = doll.mouth.image_ids or ([doll.mouth.alt_image_id] if doll.mouth.alt_image_id else [])
        for mouth_image_id in mouth_image_ids:
            img = project.get_image(mouth_image_id)
            if img and img.path:
                all_image_paths.add(img.path)

    active_save_component = _find_active_savegame_component(project)
    if active_save_component:
        _save_cfg = getattr(active_save_component, "config", {}) or {}
        if _save_cfg.get("background_use_image"):
            _bg_img_id = _save_cfg.get("background_image_id", "") or ""
            if _bg_img_id:
                _bg_img = project.get_image(_bg_img_id)
                if _bg_img and _bg_img.path:
                    all_image_paths.add(_bg_img.path)
    for img in project.images:
        if img.path:
            all_image_paths.add(img.path)
    return sorted(all_image_paths)


def _collect_3d_texture_paths(project) -> list[str]:
    """Collect 3D wall/door texture paths in the same order as the map editor."""
    paths: list[str] = []
    seen: set[str] = set()
    for img in project.images:
        if img.path and img.path not in seen:
            paths.append(img.path)
            seen.add(img.path)
    return paths


def _map_cell_lua_expr_for_texture_id(project, image_id: str) -> str | None:
    """Return the Lua expression used for a closed textured wall cell."""
    if not project or not image_id:
        return None
    img = project.get_image(image_id)
    if not img or not img.path:
        return None
    all_image_paths = _collect_all_image_paths(project)
    if img.path not in all_image_paths:
        return None
    fname = _asset_filename(img.path)
    return f"images[{_lua_str(fname)}]"


def _emit_tile_meta_table(out: list, md, project=None, indent: str = "    ") -> bool:
    """Emit the tile_meta Lua table and loadTileMeta call.
    Returns True if any tile_meta entries were emitted."""
    if not md.tile_meta:
        out.append(f"{indent}RayCast3D.loadTileMeta({{}})")
        return False
    out.append(f"{indent}local _tile_meta = {{")
    for key, tm in md.tile_meta.items():
        _door_closed_value_expr = None
        if getattr(tm, "type", "") == "door":
            _door_closed_value_expr = _map_cell_lua_expr_for_texture_id(project, getattr(tm, "texture_image_id", "") or "")
        out.append(f"{indent}    [{_lua_str(key)}] = {{")
        out.append(f"{indent}        type         = {_lua_str(tm.type)},")
        out.append(f"{indent}        state        = {_lua_str(tm.state)},")
        out.append(f"{indent}        tag          = {_lua_str(tm.tag)},")
        out.append(f"{indent}        target_scene = {tm.target_scene},")
        if _door_closed_value_expr is not None:
            out.append(f"{indent}        closed_value = {_door_closed_value_expr},")
        out.append(f"{indent}    }},")
    out.append(f"{indent}}}")
    out.append(f"{indent}RayCast3D.loadTileMeta(_tile_meta)")
    return True


# ─────────────────────────────────────────────────────────────
#  3D SCENE LOOP HELPERS  (called by _scene_3d_to_lua)
#  Each helper appends lines to `out` for one phase of the loop.
#  Adding a new phase in future sessions means adding a helper
#  and one call site — nothing else in the function changes.
# ─────────────────────────────────────────────────────────────

def _resolve_skybox(md, project) -> str | None:
    """Return the skybox filename if one is set and resolvable, else None."""
    if md.skybox_image_id and project:
        reg = project.get_image(md.skybox_image_id)
        if reg and reg.path:
            return _asset_filename(reg.path)
    return None


def _emit_3d_loop_header(out: list) -> None:
    """Frame header: poll input, clear signals, handle quit."""
    out.append("        controls_update()")
    out.append("        touch_update()")
    out.append("        _signals = {}")
    out.append("        app_ui_begin_frame()")
    out.append("        if (not app_ui_modal_active()) and controls_released(SCE_CTRL_START) then")
    out.append("            if current_music then Sound.close(current_music) end")
    out.append("            os.exit()")
    out.append("        end")


def _emit_3d_loop_movement(out: list, mode: str, move_speed, turn_speed,
                            md, has_blocking: bool, control_profile: str) -> None:
    """Movement block + blocking-sprite collision rollback."""
    if has_blocking:
        out.append("        local _save_px, _save_py = RayCast3D.getPlayer().x, RayCast3D.getPlayer().y")
    if mode == "free":
        if control_profile == "free_modern":
            out.append(f"        if stick_dir_held('left',  'up',    32) then RayCast3D.movePlayer(FORWARD, {move_speed}) end")
            out.append(f"        if stick_dir_held('left',  'down',  32) then RayCast3D.movePlayer(BACK,    {move_speed}) end")
            out.append(f"        if stick_dir_held('left',  'left',  32) then RayCast3D.movePlayer(LEFT,    {move_speed}) end")
            out.append(f"        if stick_dir_held('left',  'right', 32) then RayCast3D.movePlayer(RIGHT,   {move_speed}) end")
            out.append(f"        if stick_dir_held('right', 'left',  32) then RayCast3D.rotateCamera(LEFT,  {turn_speed}) end")
            out.append(f"        if stick_dir_held('right', 'right', 32) then RayCast3D.rotateCamera(RIGHT, {turn_speed}) end")
        else:
            out.append(f"        if controls_held(SCE_CTRL_UP)    then RayCast3D.movePlayer(FORWARD, {move_speed}) end")
            out.append(f"        if controls_held(SCE_CTRL_DOWN)  then RayCast3D.movePlayer(BACK,    {move_speed}) end")
            out.append(f"        if controls_held(SCE_CTRL_LEFT)  then RayCast3D.rotateCamera(LEFT,  {turn_speed}) end")
            out.append(f"        if controls_held(SCE_CTRL_RIGHT) then RayCast3D.rotateCamera(RIGHT, {turn_speed}) end")
    elif mode == "grid":
        snap = 90 * (960 // 60)
        out.append(f"        if controls_pressed(SCE_CTRL_UP)    then RayCast3D.movePlayerGrid(FORWARD) end")
        out.append(f"        if controls_pressed(SCE_CTRL_DOWN)  then RayCast3D.movePlayerGrid(BACK) end")
        out.append(f"        if controls_pressed(SCE_CTRL_LEFT)  then RayCast3D.snapPlayerToGrid(); RayCast3D.rotateCamera(LEFT,  {snap}) end")
        out.append(f"        if controls_pressed(SCE_CTRL_RIGHT) then RayCast3D.snapPlayerToGrid(); RayCast3D.rotateCamera(RIGHT, {snap}) end")
        if control_profile == "grid_strafe":
            out.append(f"        if controls_pressed(SCE_CTRL_LTRIGGER) then RayCast3D.movePlayerGrid(LEFT) end")
            out.append(f"        if controls_pressed(SCE_CTRL_RTRIGGER) then RayCast3D.movePlayerGrid(RIGHT) end")
    if has_blocking:
        out.append("        if RayCast3D.checkSpriteCollision(16) > 0 then")
        out.append("            RayCast3D.setPlayerPos(_save_px, _save_py)")
        out.append("        end")


def _emit_3d_loop_interact(out: list, has_interact: bool, has_exits: bool,
                            has_triggers: bool, has_3d_objects: bool,
                            interact_distance: int) -> None:
    """Cross-button interact: tile meta (doors/exits/triggers) then named sprites.

    Tile meta fires first so a door directly in front always takes priority
    over a sprite that might be nearby. Named-object dispatch fires second
    inside the same button press, guarded by its own getInteractableObject()
    range test — so a sprite behind an open door can still be interacted with.

    Trigger/switch tiles emit_signal(tag) so any on_signal behavior in the
    scene (attached to 2D objects or future 3D dispatch) reacts automatically.
    """
    if has_interact:
        out.append("        if controls_pressed(SCE_CTRL_CROSS) then")
        out.append(f"            local _meta = RayCast3D.interactFacing({interact_distance})")
        out.append("            if _meta then")
        out.append("                if _meta.type == \"exit\" then")
        out.append("                    advance = true")
        out.append("                    current_scene = _meta.target_scene")
        if has_triggers:
            # Trigger/switch: fire the tile's tag as a signal so on_signal
            # behaviors on any object in the scene respond without extra wiring.
            out.append("                elseif _meta.type == \"trigger\" or _meta.type == \"switch\" then")
            out.append("                    if _meta.tag and _meta.tag ~= \"\" then")
            out.append("                        emit_signal(_meta.tag)")
            out.append("                    end")
        out.append("                end")
        out.append("                -- doors handled internally by interactFacing()")
        out.append("            end")
        # Named-object interact: runs inside same Cross press block so it shares
        # the button edge. Tile meta took priority above; this only fires when
        # interactFacing() returned nil (no tile) OR when _meta was a door/switch
        # that didn't set advance — the player might still be near a sprite.
        out.append(f"            local _oid = RayCast3D.getInteractableObject({interact_distance})")
        out.append("            if _oid then")
        out.append("                local _fn = _obj_dispatch[_oid]")
        out.append("                if _fn then _fn() end")
        out.append("            end")
        out.append("        end")
    elif has_3d_objects:
        # No tile meta at all, but there are named sprites — still need interact.
        out.append("        if controls_pressed(SCE_CTRL_CROSS) then")
        out.append(f"            local _oid = RayCast3D.getInteractableObject({interact_distance})")
        out.append("            if _oid then")
        out.append("                local _fn = _obj_dispatch[_oid]")
        out.append("                if _fn then _fn() end")
        out.append("            end")
        out.append("        end")


def _emit_3d_loop_exit_on_step(out: list, has_exits: bool, md) -> None:
    """Walk-onto-exit: fires every frame the player stands on an exit tile."""
    if not has_exits:
        return
    out.append("        do")
    out.append(f"            local _pl = RayCast3D.getPlayer()")
    out.append(f"            local _pc = math.floor(_pl.x / {md.tile_size})")
    out.append(f"            local _pr = math.floor(_pl.y / {md.tile_size})")
    out.append(f"            local _pm = RayCast3D.getTileMeta(_pc, _pr)")
    out.append(f"            if _pm and _pm.type == \"exit\" then")
    out.append(f"                advance = true")
    out.append(f"                current_scene = _pm.target_scene")
    out.append(f"            end")
    out.append(f"        end")


def _emit_3d_loop_sprite_dispatch(out: list, valid_sprite_objects: list,
                                   project) -> None:
    """Per-frame behavior dispatch for named 3D billboard sprites.

    Mirrors the 2D scene per-object dispatch loop for billboard-backed actors.

    on_3d_interact is intentionally excluded here — it is handled by
    _emit_3d_loop_interact via _obj_dispatch. S9 populates _obj_dispatch.

    Sprites with no dispatchable behaviors produce no output (early-continue).
    """
    _DISPATCH_TRIGGERS = {
        "on_frame", "on_timer", "on_signal", "on_path_complete",
        "on_button_pressed", "on_button_held", "on_button_released",
        "on_animation_finish", "on_animation_frame", "on_lua_condition",
        "on_layer_anim_blink", "on_layer_anim_talk_step", "on_layer_anim_idle_cycle",
        "on_keyboard_submit", "on_keyboard_cancel", "on_confirm_yes", "on_confirm_no",
    }
    registry = _plugin_registry(project)
    for po in valid_sprite_objects:
        od = project.get_object_def(po.object_def_id)
        all_behs = effective_placed_behaviors(po, od)
        dispatch_behs = [
            b for b in all_behs
            if b.trigger in _DISPATCH_TRIGGERS or (registry and registry.get_trigger_descriptor(b.trigger))
        ]
        if not dispatch_behs:
            continue
        vname = _placed_var_name(po)
        out.append(f"        -- sprite dispatch: {po.instance_id}")
        for bi, beh in enumerate(dispatch_behs):
            if beh.trigger == "on_frame":
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"        {line}")

            elif beh.trigger == "on_timer" and beh.frame_count > 0:
                tvar = f"{vname}_t{bi}"
                out.append(f"        {tvar} = ({tvar} or 0) + 1")
                out.append(f"        if {tvar} >= {beh.frame_count} then")
                out.append(f"            {tvar} = 0")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif beh.trigger == "on_signal" and beh.bool_var:
                out.append(f"        if signal_fired({_lua_str(beh.bool_var)}) then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif beh.trigger in ("on_keyboard_submit", "on_keyboard_cancel", "on_confirm_yes", "on_confirm_no"):
                cond = _app_ui_trigger_condition(beh)
                if cond:
                    out.append(f"        if {cond} then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"            {line}")
                    out.append(f"        end")

            elif beh.trigger in ("on_layer_anim_blink", "on_layer_anim_talk_step", "on_layer_anim_idle_cycle"):
                event_attr = {
                    "on_layer_anim_blink": "event_blink",
                    "on_layer_anim_talk_step": "event_talk_step",
                    "on_layer_anim_idle_cycle": "event_idle_cycle",
                }[beh.trigger]
                out.append(f"        if {vname}_pdoll and {vname}_pdoll.{event_attr} then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif beh.trigger == "on_path_complete" and beh.path_name:
                out.append(f"        if signal_fired({_lua_str('path_complete_' + _safe_name(beh.path_name))}) then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif beh.trigger in ("on_button_pressed", "on_button_held", "on_button_released") and beh.button:
                if _is_stick_virtual_button(beh.button):
                    stick, direction = _stick_button_to_parts(beh.button)
                    cond = f"stick_dir_{'pressed' if beh.trigger == 'on_button_pressed' else 'held' if beh.trigger == 'on_button_held' else 'released'}('{stick}', '{direction}', 32)"
                else:
                    btn = _button_constant(beh.button)
                    fn  = {"on_button_pressed": "controls_pressed",
                           "on_button_held":    "controls_held",
                           "on_button_released":"controls_released"}[beh.trigger]
                    cond = f"{fn}({btn})"
                out.append(f"        if {cond} then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif beh.trigger == "on_animation_finish" and beh.ani_trigger_object:
                target_vars = _scene_target_vars(beh.ani_trigger_object, project)
                tname = target_vars[0] if target_vars else None
                if tname:
                    out.append(f"        if {tname}_ani_done then")
                    out.append(f"            {tname}_ani_done = false")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"            {line}")
                    out.append(f"        end")

            elif beh.trigger == "on_animation_frame" and beh.ani_trigger_object:
                target_vars = _scene_target_vars(beh.ani_trigger_object, project)
                tname = target_vars[0] if target_vars else None
                fvar = f"{vname}_aniframe_prev_{bi}"
                if tname:
                    out.append(f"        do")
                    out.append(f"            local _af = {tname}_ani_frame or 0")
                    out.append(f"            if _af == {beh.ani_trigger_frame} and {fvar} ~= {beh.ani_trigger_frame} then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")
                    out.append(f"            {fvar} = _af")
                    out.append(f"        end")

            elif beh.trigger == "on_lua_condition" and beh.lua_condition:
                expr = beh.lua_condition.strip()
                out.append(f"        if {expr} then")
                for action in beh.actions:
                    for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                        out.append(f"            {line}")
                out.append(f"        end")

            elif _emit_plugin_trigger_dispatch(out, beh, vname, project, obj_def=od, indent="        "):
                pass


def _emit_3d_actor_animation_updates(out: list, valid_sprite_objects: list, project) -> None:
    for po in valid_sprite_objects:
        od = project.get_object_def(po.object_def_id)
        if not od:
            continue
        vname = _placed_var_name(po)
        if od.behavior_type == "Animation" and _first_animation_slot(od, project):
            out.append(f"        if {vname}_ani_playing and not {vname}_ani_done then")
            out.append(f"            local _ani_d = ani_data[{vname}_ani_id]")
            out.append(f"            if _ani_d then")
            out.append(f"                local _fps = {vname}_ani_fps > 0 and {vname}_ani_fps or _ani_d.fps")
            out.append(f"                local _delay = math.floor(60 / _fps)")
            out.append(f"                if _delay < 1 then _delay = 1 end")
            out.append(f"                {vname}_ani_timer = {vname}_ani_timer + 1")
            out.append(f"                if {vname}_ani_timer >= _delay then")
            out.append(f"                    {vname}_ani_timer = 0")
            out.append(f"                    {vname}_ani_frame = {vname}_ani_frame + 1")
            out.append(f"                    if {vname}_ani_frame >= _ani_d.frame_count then")
            out.append(f"                        if {vname}_ani_loop then")
            out.append(f"                            {vname}_ani_frame = 0")
            out.append(f"                        else")
            out.append(f"                            {vname}_ani_frame = _ani_d.frame_count - 1")
            out.append(f"                            {vname}_ani_done = true")
            out.append(f"                            {vname}_ani_playing = false")
            out.append(f"                        end")
            out.append(f"                    end")
            out.append(f"                end")
            out.append(f"            end")
            out.append(f"        end")
        elif len(getattr(od, "frames", []) or []) > 1:
            out.append(f"        if {vname}_frame_playing then")
            out.append(f"            local _fdef = {vname}_frames[{vname}_frame]")
            out.append(f"            if _fdef then")
            out.append(f"                {vname}_frame_timer = {vname}_frame_timer + 1")
            out.append(f"                if {vname}_frame_timer >= _fdef.dur then")
            out.append(f"                    {vname}_frame_timer = 0")
            out.append(f"                    {vname}_frame = {vname}_frame + 1")
            out.append(f"                    local _fc = 0")
            out.append(f"                    for _ in pairs({vname}_frames) do _fc = _fc + 1 end")
            out.append(f"                    if {vname}_frame >= _fc then")
            out.append(f"                        if {vname}_frame_loop then")
            out.append(f"                            {vname}_frame = 0")
            out.append(f"                        else")
            out.append(f"                            {vname}_frame = _fc - 1")
            out.append(f"                            {vname}_frame_playing = false")
            out.append(f"                        end")
            out.append(f"                    end")
            out.append(f"                end")
            out.append(f"            end")
            out.append(f"        end")


def _emit_3d_actor_sync(out: list, valid_sprite_objects: list, sprite_idx_map: dict[str, int], project) -> None:
    for po in valid_sprite_objects:
        od = project.get_object_def(po.object_def_id)
        if not od:
            continue
        vname = _placed_var_name(po)
        sprite_idx = sprite_idx_map[po.instance_id]
        out.append(f"        do")
        out.append(f"            local _actor = actor3d_sync_entry({_lua_str(po.instance_id)})")
        out.append(f"            if _actor then")
        out.append(f"                RayCast3D.moveObject({_lua_str(po.instance_id)}, _actor.x, _actor.y)")
        out.append(f"                RayCast3D.setSpriteVisible({sprite_idx}, _actor.visible)")
        out.append(f"                RayCast3D.setSpriteScale({sprite_idx}, _actor.scale)")
        out.append(f"                RayCast3D.setSpriteBlocking({sprite_idx}, _actor.blocking)")
        out.append(f"            end")
        out.append(f"        end")
        if od.behavior_type == "Animation" and _first_animation_slot(od, project):
            out.append(f"        do")
            out.append(f"            local _sheet, _sx, _sy, _sw, _sh = ani_get_sheet_and_rect({vname}_ani_id, {vname}_ani_frame)")
            out.append(f"            if _sheet then")
            out.append(f"                RayCast3D.setSpriteFrame({sprite_idx}, _sheet, _sx, _sy, _sw, _sh)")
            out.append(f"            end")
            out.append(f"        end")
        elif len(getattr(od, "frames", []) or []) > 1:
            _fallback = _regular_frame_image_name(od, project, 0)
            out.append(f"        do")
            out.append(f"            local _fdef = {vname}_frames[{vname}_frame]")
            out.append(f"            local _fname = (_fdef and _fdef.img ~= \"\") and _fdef.img or {_lua_str(_fallback)}")
            out.append(f"            local _img = (_fname ~= \"\") and images[_fname] or nil")
            out.append(f"            if _img then")
            out.append(f"                RayCast3D.setSpriteImage({sprite_idx}, _img)")
            out.append(f"            end")
            out.append(f"        end")


def _emit_3d_loop_render(out: list, md, hud_objects: list, project,
                          skybox_img: str | None, plugin_draw_lines: list[str] | None = None) -> None:
    """Render phase: background fill/skybox, raycaster, sprites, HUD, flip."""
    out.append("        Graphics.initBlend()")
    if skybox_img:
        out.append(f"        if images[{_lua_str(skybox_img)}] then")
        out.append(f"            Graphics.drawImage(0, 0, images[{_lua_str(skybox_img)}])")
        out.append(f"        else")
        out.append(f"            Graphics.fillRect(0, 960, 0, 272, _ceil_c)")
        out.append(f"            Graphics.fillRect(0, 960, 272, 544, _floor_c)")
        out.append(f"        end")
    else:
        out.append(f"        Graphics.fillRect(0, 960, 0, 272, _ceil_c)")
        out.append(f"        Graphics.fillRect(0, 960, 272, 544, _floor_c)")
    out.append("        RayCast3D.renderScene(0, 0)")
    out.append("        RayCast3D.renderSprites(0, 0)")
    # HUD objects: screen-space images drawn after all 3D rendering
    for po in hud_objects:
        od = project.get_object_def(po.object_def_id)
        if not od or not od.frames:
            continue
        img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
        if not img or not img.path:
            continue
        fname = _asset_filename(img.path)
        vname = f"hud_{po.instance_id}"
        anchor = po.hud_anchor
        if anchor == "top_left":
            x_expr = str(po.hud_x)
            y_expr = str(po.hud_y)
        elif anchor == "top_right":
            x_expr = f"960 - Graphics.getImageWidth(images[{_lua_str(fname)}]) - {po.hud_x}"
            y_expr = str(po.hud_y)
        elif anchor == "bottom_left":
            x_expr = str(po.hud_x)
            y_expr = f"544 - Graphics.getImageHeight(images[{_lua_str(fname)}]) - {po.hud_y}"
        elif anchor == "bottom_right":
            x_expr = f"960 - Graphics.getImageWidth(images[{_lua_str(fname)}]) - {po.hud_x}"
            y_expr = f"544 - Graphics.getImageHeight(images[{_lua_str(fname)}]) - {po.hud_y}"
        elif anchor == "center":
            x_expr = f"480 - Graphics.getImageWidth(images[{_lua_str(fname)}]) / 2 + {po.hud_x}"
            y_expr = f"272 - Graphics.getImageHeight(images[{_lua_str(fname)}]) / 2 + {po.hud_y}"
        elif anchor == "bottom_center":
            x_expr = f"480 - Graphics.getImageWidth(images[{_lua_str(fname)}]) / 2 + {po.hud_x}"
            y_expr = f"544 - Graphics.getImageHeight(images[{_lua_str(fname)}]) - {po.hud_y}"
        else:
            x_expr = str(po.hud_x)
            y_expr = str(po.hud_y)
        out.append(f"        if {vname}_visible then")
        out.append(f"            Graphics.drawImage({x_expr}, {y_expr}, images[{_lua_str(fname)}])")
        out.append(f"        end")
    for line in plugin_draw_lines or []:
        out.append(f"        {line}")
    out.append("        Graphics.termBlend()")
    out.append("        Screen.flip()")


def _emit_3d_door_helpers(out: list, md) -> None:
    """Emit _setDoorState and _setDoorStateByTag Lua helpers.

    Called once per scene when any behavior uses open_door / close_door /
    toggle_door.  The helpers are emitted as locals inside the scene function
    so they share the same upvalue scope as map_cells and _tile_meta.

    _setDoorState(col, row, mode)
        mode is "open", "closed", or "toggle".
        Mutates map_cells directly (same table RayCast3D.loadMap received) and
        updates the meta state so subsequent getTileMeta calls see the new state.
        Re-calls loadMap after mutation so the raycaster picks up the change.

    _setDoorStateByTag(tag, mode)
        Iterates _tile_meta looking for door entries whose .tag matches, then
        delegates to _setDoorState for each.  No-ops silently if no match.
    """
    ts = md.tile_size
    w  = md.width
    out.append("    -- Door state helpers (S10)")
    out.append("    local function _setDoorState(col, row, mode)")
    out.append(f"        local _k = col .. \",\" .. row")
    out.append(f"        local _m = _tile_meta and _tile_meta[_k]")
    out.append(f"        if not _m then return end")
    out.append(f"        if mode == \"toggle\" then")
    out.append(f"            mode = (_m.state == \"open\") and \"closed\" or \"open\"")
    out.append(f"        end")
    out.append(f"        local _idx = row * {w} + col + 1")
    out.append(f"        if mode == \"open\" then")
    out.append(f"            map_cells[_idx] = 0")
    out.append(f"            _m.state = \"open\"")
    out.append(f"        elseif mode == \"closed\" then")
    out.append(f"            map_cells[_idx] = _m.closed_value or 1")
    out.append(f"            _m.state = \"closed\"")
    out.append(f"        end")
    out.append(f"        RayCast3D.loadMap(map_cells, {w}, {md.height}, {ts}, {md.wall_height})")
    out.append("    end")
    out.append("    local function _setDoorStateByTag(tag, mode)")
    out.append("        if not _tile_meta then return end")
    out.append("        for _k, _m in pairs(_tile_meta) do")
    out.append("            if _m.type == \"door\" and _m.tag == tag then")
    out.append("                local _parts = {}")
    out.append("                for _p in string.gmatch(_k, \"([^,]+)\") do")
    out.append("                    _parts[#_parts + 1] = tonumber(_p)")
    out.append("                end")
    out.append("                if _parts[1] and _parts[2] then")
    out.append("                    _setDoorState(_parts[1], _parts[2], mode)")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("    end")


def _emit_3d_actor_helpers(out: list, md) -> None:
    out.append("    local _actors3d = {}")
    out.append("    local _actors3d_by_var = {}")
    out.append("    local _actor3d_patrols = {}")
    out.append("    local _actor3d_nav_followers = {}")
    out.append("    local function actor3d_get(id)")
    out.append("        return _actors3d[tostring(id or \"\")]")
    out.append("    end")
    out.append("    local function actor3d_id_from_var(obj_var)")
    out.append("        return _actors3d_by_var[tostring(obj_var or \"\")]")
    out.append("    end")
    out.append("    local function actor3d_get_by_var(obj_var)")
    out.append("        local _id = actor3d_id_from_var(obj_var)")
    out.append("        return _id and _actors3d[_id] or nil")
    out.append("    end")
    out.append("    local function actor3d_register(id, def_id, obj_var, sprite_idx, data)")
    out.append("        local _id = tostring(id or \"\")")
    out.append("        local _obj_var = tostring(obj_var or \"\")")
    out.append("        local _blocking = data.blocking ~= false")
    out.append("        local _interactable = data.interactable ~= false")
    out.append("        local entry = {")
    out.append("            id = _id,")
    out.append("            def_id = tostring(def_id or \"\"),")
    out.append("            obj_var = _obj_var,")
    out.append("            sprite_idx = sprite_idx,")
    out.append("            x = tonumber(data.x or 0) or 0,")
    out.append("            y = tonumber(data.y or 0) or 0,")
    out.append("            angle = tonumber(data.angle or 0) or 0,")
    out.append("            visible = data.visible ~= false,")
    out.append("            blocking = _blocking,")
    out.append("            interactable = _interactable,")
    out.append("            default_blocking = _blocking,")
    out.append("            default_interactable = _interactable,")
    out.append("            alive = data.alive ~= false,")
    out.append("            state = tostring(data.state or \"idle\"),")
    out.append("            faction = tostring(data.faction or \"\"),")
    out.append("            health = tonumber(data.health or 0) or 0,")
    out.append("            max_health = tonumber(data.max_health or data.health or 0) or 0,")
    out.append("            speed = tonumber(data.speed or 0) or 0,")
    out.append("            radius = tonumber(data.radius or 16) or 16,")
    out.append("            sight_range = tonumber(data.sight_range or 0) or 0,")
    out.append("            attack_range = tonumber(data.attack_range or 0) or 0,")
    out.append("            patrol_path = tostring(data.patrol_path or \"\"),")
    out.append("            scale = tonumber(data.scale or 1.0) or 1.0,")
    out.append("            cooldowns = {},")
    out.append("            timers = {},")
    out.append("        }")
    out.append("        _actors3d[_id] = entry")
    out.append("        if _obj_var ~= \"\" then")
    out.append("            _actors3d_by_var[_obj_var] = _id")
    out.append("        end")
    out.append("        return entry")
    out.append("    end")
    out.append("    local function actor3d_sync_entry(id)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return nil end")
    out.append("        local base = entry.obj_var")
    out.append("        if base and base ~= \"\" then")
    out.append("            entry.x = tonumber(_G[base .. \"_x\"] or entry.x or 0) or 0")
    out.append("            entry.y = tonumber(_G[base .. \"_y\"] or entry.y or 0) or 0")
    out.append("            entry.visible = (_G[base .. \"_visible\"] ~= false)")
    out.append("            entry.scale = tonumber(_G[base .. \"_scale\"] or entry.scale or 1.0) or 1.0")
    out.append("            entry.blocking = (_G[base .. \"_blocking\"] ~= false)")
    out.append("            entry.interactable = (_G[base .. \"_interactable\"] ~= false)")
    out.append("            entry.angle = tonumber(_G[base .. \"_angle\"] or entry.angle or 0) or 0")
    out.append("        end")
    out.append("        return entry")
    out.append("    end")
    out.append("    local function actor3d_sync_all()")
    out.append("        for _id, _ in pairs(_actors3d) do")
    out.append("            actor3d_sync_entry(_id)")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_pos(id, x, y)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.x = tonumber(x or entry.x or 0) or 0")
    out.append("        entry.y = tonumber(y or entry.y or 0) or 0")
    out.append("        if entry.obj_var ~= \"\" then")
    out.append("            _G[entry.obj_var .. \"_x\"] = entry.x")
    out.append("            _G[entry.obj_var .. \"_y\"] = entry.y")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_angle(id, angle)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.angle = tonumber(angle or entry.angle or 0) or 0")
    out.append("        if entry.obj_var ~= \"\" then")
    out.append("            _G[entry.obj_var .. \"_angle\"] = entry.angle")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_state(id, state)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.state = tostring(state or entry.state or \"idle\")")
    out.append("    end")
    out.append("    local function actor3d_set_visible(id, visible)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.visible = not not visible")
    out.append("        if entry.obj_var ~= \"\" then")
    out.append("            _G[entry.obj_var .. \"_visible\"] = entry.visible")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_blocking(id, blocking)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.blocking = blocking and true or false")
    out.append("        if entry.obj_var ~= \"\" then")
    out.append("            _G[entry.obj_var .. \"_blocking\"] = entry.blocking")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_interactable(id, interactable)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return end")
    out.append("        entry.interactable = interactable and true or false")
    out.append("        if entry.obj_var ~= \"\" then")
    out.append("            _G[entry.obj_var .. \"_interactable\"] = entry.interactable")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_is_alive(id)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        return entry ~= nil and entry.alive ~= false")
    out.append("    end")
    out.append("    local function actor3d_distance_to_player(id)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        local pl = RayCast3D.getPlayer()")
    out.append("        if not entry or not pl then return math.huge end")
    out.append("        local dx = (pl.x or 0) - (entry.x or 0)")
    out.append("        local dy = (pl.y or 0) - (entry.y or 0)")
    out.append("        return math.sqrt(dx * dx + dy * dy)")
    out.append("    end")
    out.append("    local function _actor3d_is_cell_solid(col, row)")
    out.append(f"        if col < 0 or col >= {md.width} or row < 0 or row >= {md.height} then")
    out.append("            return true")
    out.append("        end")
    out.append("        local meta = RayCast3D.getTileMeta(col, row)")
    out.append("        if meta and meta.type == \"door\" then")
    out.append("            return meta.state ~= \"open\"")
    out.append("        end")
    out.append(f"        local idx = row * {md.width} + col + 1")
    out.append("        return (map_cells[idx] or 0) ~= 0")
    out.append("    end")
    out.append("    local function actor3d_can_see_player(id, max_range)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        local pl = RayCast3D.getPlayer()")
    out.append("        if not entry or not pl or entry.alive == false or entry.visible == false then return false end")
    out.append("        local dx = (pl.x or 0) - (entry.x or 0)")
    out.append("        local dy = (pl.y or 0) - (entry.y or 0)")
    out.append("        local dist = math.sqrt(dx * dx + dy * dy)")
    out.append("        local cap = tonumber(max_range or 0) or 0")
    out.append("        if cap <= 0 then cap = tonumber(entry.sight_range or 0) or 0 end")
    out.append("        if cap > 0 and dist > cap then return false end")
    out.append(f"        local step_len = math.max(4, math.floor({md.tile_size} / 4))")
    out.append("        local steps = math.max(1, math.floor(dist / step_len))")
    out.append("        for i = 1, steps - 1 do")
    out.append("            local t = i / steps")
    out.append("            local sx = (entry.x or 0) + dx * t")
    out.append("            local sy = (entry.y or 0) + dy * t")
    out.append(f"            local col = math.floor(sx / {md.tile_size})")
    out.append(f"            local row = math.floor(sy / {md.tile_size})")
    out.append("            if _actor3d_is_cell_solid(col, row) then")
    out.append("                return false")
    out.append("            end")
    out.append("        end")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_face_player(id)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        local pl = RayCast3D.getPlayer()")
    out.append("        if not entry or not pl then return end")
    out.append("        actor3d_set_angle(id, math.deg(math.atan2((pl.y or 0) - (entry.y or 0), (pl.x or 0) - (entry.x or 0))))")
    out.append("    end")
    out.append("    local function actor3d_find_by_faction(faction)")
    out.append("        local matches = {}")
    out.append("        local wanted = tostring(faction or \"\")")
    out.append("        for _id, entry in pairs(_actors3d) do")
    out.append("            if entry.faction == wanted then")
    out.append("                matches[#matches + 1] = entry")
    out.append("            end")
    out.append("        end")
    out.append("        return matches")
    out.append("    end")
    out.append("    local function actor3d_iter_live()")
    out.append("        local ids = {}")
    out.append("        for _id, entry in pairs(_actors3d) do")
    out.append("            if entry.alive ~= false then")
    out.append("                ids[#ids + 1] = _id")
    out.append("            end")
    out.append("        end")
    out.append("        local idx = 0")
    out.append("        return function()")
    out.append("            idx = idx + 1")
    out.append("            local _id = ids[idx]")
    out.append("            if _id then")
    out.append("                return _id, _actors3d[_id]")
    out.append("            end")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_set_patrol_enabled(id, enabled)")
    out.append("        local pf = _actor3d_patrols[tostring(id or \"\")]")
    out.append("        if not pf then return false end")
    out.append("        pf.paused = not (enabled and true or false)")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_kill(id, death_state)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return false end")
    out.append("        entry.alive = false")
    out.append("        entry.state = tostring(death_state or entry.state or \"dead\")")
    out.append("        if entry.state == \"\" then entry.state = \"dead\" end")
    out.append("        entry.cooldowns = {}")
    out.append("        entry.timers = {}")
    out.append("        _actor3d_patrols[entry.id] = nil")
    out.append("        _actor3d_nav_followers[entry.id] = nil")
    out.append("        actor3d_set_blocking(entry.id, false)")
    out.append("        actor3d_set_interactable(entry.id, false)")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_set_alive(id, alive)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return false end")
    out.append("        if alive == false then")
    out.append("            return actor3d_kill(id, entry.state or \"dead\")")
    out.append("        end")
    out.append("        entry.alive = true")
    out.append("        actor3d_set_blocking(entry.id, entry.default_blocking)")
    out.append("        actor3d_set_interactable(entry.id, entry.default_interactable)")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_set_cooldown(id, key, frames)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        local cname = tostring(key or \"\")")
    out.append("        if not entry or cname == \"\" then return false end")
    out.append("        entry.cooldowns[cname] = math.max(0, tonumber(frames or 0) or 0)")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_get_cooldown(id, key)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return 0 end")
    out.append("        return tonumber(entry.cooldowns[tostring(key or \"\")] or 0) or 0")
    out.append("    end")
    out.append("    local function actor3d_cooldown_ready(id, key)")
    out.append("        return actor3d_get_cooldown(id, key) <= 0")
    out.append("    end")
    out.append("    local function actor3d_clear_cooldown(id, key)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return false end")
    out.append("        entry.cooldowns[tostring(key or \"\")] = nil")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_set_timer(id, key, frames)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        local tname = tostring(key or \"\")")
    out.append("        if not entry or tname == \"\" then return false end")
    out.append("        entry.timers[tname] = math.max(0, tonumber(frames or 0) or 0)")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_get_timer(id, key)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return 0 end")
    out.append("        return tonumber(entry.timers[tostring(key or \"\")] or 0) or 0")
    out.append("    end")
    out.append("    local function actor3d_timer_ready(id, key)")
    out.append("        return actor3d_get_timer(id, key) <= 0")
    out.append("    end")
    out.append("    local function actor3d_clear_timer(id, key)")
    out.append("        local entry = actor3d_get(id)")
    out.append("        if not entry then return false end")
    out.append("        entry.timers[tostring(key or \"\")] = nil")
    out.append("        return true")
    out.append("    end")
    out.append("    local function _actor3d_tick_bucket(bucket)")
    out.append("        for _name, _frames in pairs(bucket) do")
    out.append("            _frames = (tonumber(_frames or 0) or 0) - 1")
    out.append("            if _frames <= 0 then")
    out.append("                bucket[_name] = nil")
    out.append("            else")
    out.append("                bucket[_name] = _frames")
    out.append("            end")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_tick_runtime()")
    out.append("        for _, entry in pairs(_actors3d) do")
    out.append("            _actor3d_tick_bucket(entry.cooldowns or {})")
    out.append("            _actor3d_tick_bucket(entry.timers or {})")
    out.append("        end")
    out.append("    end")
    out.append("    local function actor3d_start_patrol(id, path_name, speed, should_loop)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        local pname = tostring(path_name or entry and entry.patrol_path or \"\")")
    out.append("        local pts = scene_paths and scene_paths[pname] or nil")
    out.append("        if not entry or pname == \"\" or not pts or #pts == 0 then return false end")
    out.append("        _actor3d_nav_followers[entry.id] = nil")
    out.append("        local start_idx = 1")
    out.append("        if path_nearest_point then")
    out.append("            local idx = path_nearest_point(pname, entry.x or 0, entry.y or 0)")
    out.append("            if idx then start_idx = idx end")
    out.append("        end")
    out.append("        _actor3d_patrols[entry.id] = {")
    out.append("            path = pname,")
    out.append("            index = start_idx,")
    out.append("            speed = tonumber(speed or entry.speed or 1.0) or 1.0,")
    out.append("            accum = 0,")
    out.append("            loop = should_loop == true,")
    out.append("            paused = false,")
    out.append("        }")
    out.append("        local pt = pts[start_idx] or pts[1]")
    out.append("        if pt then")
    out.append("            actor3d_set_pos(entry.id, pt.x, pt.y)")
    out.append("        end")
    out.append("        return true")
    out.append("    end")
    out.append("    local function actor3d_stop_patrol(id)")
    out.append("        _actor3d_patrols[tostring(id or \"\")] = nil")
    out.append("    end")
    out.append("    local function actor3d_resume_patrol(id)")
    out.append("        local pf = _actor3d_patrols[tostring(id or \"\")]")
    out.append("        if pf then pf.paused = false end")
    out.append("    end")
    out.append("    local function actor3d_set_patrol_speed(id, speed)")
    out.append("        local pf = _actor3d_patrols[tostring(id or \"\")]")
    out.append("        if pf then pf.speed = tonumber(speed or pf.speed or 1.0) or 1.0 end")
    out.append("    end")
    out.append("    local function actor3d_update_patrols()")
    out.append("        for _id, pf in pairs(_actor3d_patrols) do")
    out.append("            local entry = actor3d_sync_entry(_id)")
    out.append("            if not entry or entry.alive == false then")
    out.append("                _actor3d_patrols[_id] = nil")
    out.append("            elseif not pf.paused then")
    out.append("                local pts = scene_paths and scene_paths[pf.path] or nil")
    out.append("                if pts then")
    out.append("                    pf.accum = pf.accum + (tonumber(pf.speed or 1.0) or 1.0)")
    out.append("                    while pf.accum >= 1 and pf.index <= #pts do")
    out.append("                        pf.index = pf.index + 1")
    out.append("                        pf.accum = pf.accum - 1")
    out.append("                    end")
    out.append("                    if pf.index > #pts then")
    out.append("                        emit_signal(\"path_complete_\" .. tostring(pf.path or \"\"))")
    out.append("                        if pf.loop then")
    out.append("                            pf.index = 1")
    out.append("                        else")
    out.append("                            _actor3d_patrols[_id] = nil")
    out.append("                        end")
    out.append("                    else")
    out.append("                        local pt = pts[pf.index]")
    out.append("                        if pt then")
    out.append("                            actor3d_set_pos(_id, pt.x, pt.y)")
    out.append("                        end")
    out.append("                    end")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("    end")
    out.append("    local function _nav3d_world_to_cell(wx, wy)")
    out.append(f"        return math.floor((tonumber(wx or 0) or 0) / {md.tile_size}), math.floor((tonumber(wy or 0) or 0) / {md.tile_size})")
    out.append("    end")
    out.append("    local function _nav3d_cell_center(col, row)")
    out.append(f"        return {{x = col * {md.tile_size} + math.floor({md.tile_size} / 2), y = row * {md.tile_size} + math.floor({md.tile_size} / 2)}}")
    out.append("    end")
    out.append("    local function _nav3d_actor_blocks_cell(col, row, opts)")
    out.append("        local ignore_id = opts and tostring(opts.ignore_actor_id or opts.ignore_id or \"\") or \"\"")
    out.append("        for _id, entry in pairs(_actors3d) do")
    out.append("            if entry.blocking and entry.visible ~= false and entry.alive ~= false and _id ~= ignore_id then")
    out.append("                local ac, ar = _nav3d_world_to_cell(entry.x or 0, entry.y or 0)")
    out.append("                if ac == col and ar == row then")
    out.append("                    return true")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("        return false")
    out.append("    end")
    out.append("    local function nav3d_is_walkable(col, row, opts)")
    out.append(f"        if col < 0 or col >= {md.width} or row < 0 or row >= {md.height} then return false end")
    out.append("        if _actor3d_is_cell_solid(col, row) then return false end")
    out.append("        local allow_actor_block = opts and opts.allow_actor_block == true")
    out.append("        if not allow_actor_block and _nav3d_actor_blocks_cell(col, row, opts) then return false end")
    out.append("        return true")
    out.append("    end")
    out.append("    local function nav3d_is_walkable_world(wx, wy, opts)")
    out.append("        local col, row = _nav3d_world_to_cell(wx, wy)")
    out.append("        return nav3d_is_walkable(col, row, opts)")
    out.append("    end")
    out.append("    local function _nav3d_cell_key(col, row)")
    out.append("        return tostring(col) .. \",\" .. tostring(row)")
    out.append("    end")
    out.append("    local function _nav3d_reconstruct_path(came_from, cell_lookup, current_key)")
    out.append("        local rev = {}")
    out.append("        local ck = current_key")
    out.append("        while ck do")
    out.append("            local cell = cell_lookup[ck]")
    out.append("            if not cell then break end")
    out.append("            rev[#rev + 1] = {col = cell.col, row = cell.row}")
    out.append("            ck = came_from[ck]")
    out.append("        end")
    out.append("        local out_path = {}")
    out.append("        for i = #rev, 1, -1 do")
    out.append("            out_path[#out_path + 1] = rev[i]")
    out.append("        end")
    out.append("        return out_path")
    out.append("    end")
    out.append("    local function nav3d_find_path_cells(start_col, start_row, goal_col, goal_row, opts)")
    out.append("        start_col = math.floor(tonumber(start_col or 0) or 0)")
    out.append("        start_row = math.floor(tonumber(start_row or 0) or 0)")
    out.append("        goal_col = math.floor(tonumber(goal_col or 0) or 0)")
    out.append("        goal_row = math.floor(tonumber(goal_row or 0) or 0)")
    out.append(f"        if start_col < 0 or start_col >= {md.width} or start_row < 0 or start_row >= {md.height} then return {{}} end")
    out.append(f"        if goal_col < 0 or goal_col >= {md.width} or goal_row < 0 or goal_row >= {md.height} then return {{}} end")
    out.append("        local allow_goal_blocked = opts and opts.allow_goal_blocked == true")
    out.append("        if _actor3d_is_cell_solid(goal_col, goal_row) then return {} end")
    out.append("        if not allow_goal_blocked and _nav3d_actor_blocks_cell(goal_col, goal_row, opts) then return {} end")
    out.append("        local start_key = _nav3d_cell_key(start_col, start_row)")
    out.append("        local goal_key = _nav3d_cell_key(goal_col, goal_row)")
    out.append("        local function heuristic(col, row)")
    out.append("            return math.abs(goal_col - col) + math.abs(goal_row - row)")
    out.append("        end")
    out.append("        local open = {[start_key] = true}")
    out.append("        local open_list = {{key = start_key, col = start_col, row = start_row}}")
    out.append("        local came_from = {}")
    out.append("        local cell_lookup = {[start_key] = {col = start_col, row = start_row}}")
    out.append("        local g_score = {[start_key] = 0}")
    out.append("        local f_score = {[start_key] = heuristic(start_col, start_row)}")
    out.append("        local dirs = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}")
    out.append("        local max_nodes = math.max(64, tonumber(opts and opts.max_nodes or 0) or 0)")
    out.append("        if max_nodes <= 0 then max_nodes = 2048 end")
    out.append("        local visited = 0")
    out.append("        while #open_list > 0 and visited < max_nodes do")
    out.append("            visited = visited + 1")
    out.append("            local best_idx = 1")
    out.append("            local best_key = open_list[1].key")
    out.append("            local best_score = tonumber(f_score[best_key] or math.huge) or math.huge")
    out.append("            for i = 2, #open_list do")
    out.append("                local k = open_list[i].key")
    out.append("                local score = tonumber(f_score[k] or math.huge) or math.huge")
    out.append("                if score < best_score then")
    out.append("                    best_idx = i")
    out.append("                    best_key = k")
    out.append("                    best_score = score")
    out.append("                end")
    out.append("            end")
    out.append("            local current = table.remove(open_list, best_idx)")
    out.append("            open[current.key] = nil")
    out.append("            if current.key == goal_key then")
    out.append("                return _nav3d_reconstruct_path(came_from, cell_lookup, current.key)")
    out.append("            end")
    out.append("            for _, dir in ipairs(dirs) do")
    out.append("                local nc = current.col + dir[1]")
    out.append("                local nr = current.row + dir[2]")
    out.append("                local is_goal = (nc == goal_col and nr == goal_row)")
    out.append("                local can_step = nav3d_is_walkable(nc, nr, {ignore_actor_id = opts and (opts.ignore_actor_id or opts.ignore_id) or nil, allow_actor_block = is_goal and allow_goal_blocked})")
    out.append("                if can_step then")
    out.append("                    local nkey = _nav3d_cell_key(nc, nr)")
    out.append("                    local tentative = (tonumber(g_score[current.key] or math.huge) or math.huge) + 1")
    out.append("                    if tentative < (tonumber(g_score[nkey] or math.huge) or math.huge) then")
    out.append("                        came_from[nkey] = current.key")
    out.append("                        cell_lookup[nkey] = {col = nc, row = nr}")
    out.append("                        g_score[nkey] = tentative")
    out.append("                        f_score[nkey] = tentative + heuristic(nc, nr)")
    out.append("                        if not open[nkey] then")
    out.append("                            open[nkey] = true")
    out.append("                            open_list[#open_list + 1] = {key = nkey, col = nc, row = nr}")
    out.append("                        end")
    out.append("                    end")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("        return {}")
    out.append("    end")
    out.append("    local function nav3d_find_path(start_wx, start_wy, goal_wx, goal_wy, opts)")
    out.append("        local sc, sr = _nav3d_world_to_cell(start_wx, start_wy)")
    out.append("        local gc, gr = _nav3d_world_to_cell(goal_wx, goal_wy)")
    out.append("        local cells = nav3d_find_path_cells(sc, sr, gc, gr, opts)")
    out.append("        local pts = {}")
    out.append("        for i = 1, #(cells or {}) do")
    out.append("            local center = _nav3d_cell_center(cells[i].col, cells[i].row)")
    out.append("            pts[#pts + 1] = {x = center.x, y = center.y, col = cells[i].col, row = cells[i].row}")
    out.append("        end")
    out.append("        return pts")
    out.append("    end")
    out.append("    local function nav3d_stop_follow(id)")
    out.append("        _actor3d_nav_followers[tostring(id or \"\")] = nil")
    out.append("    end")
    out.append("    local function nav3d_follow_path(id, points, speed, opts)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        if not entry or type(points) ~= \"table\" or #points == 0 then return false end")
    out.append("        actor3d_stop_patrol(entry.id)")
    out.append("        local start_idx = 1")
    out.append("        if points[1] and points[1].x ~= nil and points[1].y ~= nil then")
    out.append("            local pdx = (points[1].x or 0) - (entry.x or 0)")
    out.append("            local pdy = (points[1].y or 0) - (entry.y or 0)")
    out.append("            local pdist = math.sqrt(pdx * pdx + pdy * pdy)")
    out.append("            if pdist <= math.max(1, tonumber(speed or entry.speed or 1.0) or 1.0) and #points > 1 then")
    out.append("                start_idx = 2")
    out.append("            end")
    out.append("        end")
    out.append("        _actor3d_nav_followers[entry.id] = {points = points, index = start_idx, speed = tonumber(speed or entry.speed or 1.0) or 1.0, face_movement = opts and opts.face_movement == true or false}")
    out.append("        return true")
    out.append("    end")
    out.append("    local function nav3d_follow_to(id, goal_wx, goal_wy, speed, opts)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        if not entry then return false, {} end")
    out.append("        local path = nav3d_find_path(entry.x or 0, entry.y or 0, goal_wx, goal_wy, opts)")
    out.append("        if #path == 0 then return false, path end")
    out.append("        return nav3d_follow_path(id, path, speed, opts), path")
    out.append("    end")
    out.append("    local function nav3d_update_followers()")
    out.append("        for _id, follower in pairs(_actor3d_nav_followers) do")
    out.append("            local entry = actor3d_sync_entry(_id)")
    out.append("            if not entry or entry.alive == false then")
    out.append("                _actor3d_nav_followers[_id] = nil")
    out.append("            else")
    out.append("                local remaining = tonumber(follower.speed or entry.speed or 1.0) or 1.0")
    out.append("                while remaining > 0 and _actor3d_nav_followers[_id] do")
    out.append("                    local pt = follower.points[follower.index]")
    out.append("                    if not pt then")
    out.append("                        _actor3d_nav_followers[_id] = nil")
    out.append("                        break")
    out.append("                    end")
    out.append("                    local dx = (pt.x or 0) - (entry.x or 0)")
    out.append("                    local dy = (pt.y or 0) - (entry.y or 0)")
    out.append("                    local dist = math.sqrt(dx * dx + dy * dy)")
    out.append("                    if dist <= 0.001 then")
    out.append("                        actor3d_set_pos(_id, pt.x or entry.x or 0, pt.y or entry.y or 0)")
    out.append("                        follower.index = follower.index + 1")
    out.append("                    elseif dist <= remaining then")
    out.append("                        if follower.face_movement then actor3d_set_angle(_id, math.deg(math.atan2(dy, dx))) end")
    out.append("                        actor3d_set_pos(_id, pt.x or entry.x or 0, pt.y or entry.y or 0)")
    out.append("                        remaining = remaining - dist")
    out.append("                        follower.index = follower.index + 1")
    out.append("                    else")
    out.append("                        local step = remaining / dist")
    out.append("                        if follower.face_movement then actor3d_set_angle(_id, math.deg(math.atan2(dy, dx))) end")
    out.append("                        actor3d_set_pos(_id, (entry.x or 0) + dx * step, (entry.y or 0) + dy * step)")
    out.append("                        remaining = 0")
    out.append("                    end")
    out.append("                    entry = actor3d_sync_entry(_id)")
    out.append("                    if follower.index > #(follower.points or {}) then")
    out.append("                        _actor3d_nav_followers[_id] = nil")
    out.append("                    end")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("    end")
    out.append("    local function _ray3d_wall_hit(wx, wy, dx, dy, max_range, step_len)")
    out.append("        local dist = 0")
    out.append("        while dist <= max_range do")
    out.append("            local px = (wx or 0) + dx * dist")
    out.append("            local py = (wy or 0) + dy * dist")
    out.append(f"            local col = math.floor(px / {md.tile_size})")
    out.append(f"            local row = math.floor(py / {md.tile_size})")
    out.append("            if _actor3d_is_cell_solid(col, row) then")
    out.append("                local meta = RayCast3D.getTileMeta(col, row)")
    out.append("                local kind = (meta and meta.type == \"door\") and \"door\" or \"wall\"")
    out.append("                return {kind = kind, distance = dist, x = px, y = py, col = col, row = row, tag = meta and meta.tag or \"\", door_state = meta and meta.state or \"\"}")
    out.append("            end")
    out.append("            dist = dist + step_len")
    out.append("        end")
    out.append("        return nil")
    out.append("    end")
    out.append("    local function _ray3d_actor_matches(entry, opts)")
    out.append("        if not entry or entry.alive == false or entry.visible == false then return false end")
    out.append("        local ignore_id = tostring(opts and (opts.ignore_actor_id or opts.ignore_id) or \"\")")
    out.append("        if ignore_id ~= \"\" and entry.id == ignore_id then return false end")
    out.append("        if opts and opts.ignore_nonblocking == true and entry.blocking ~= true then return false end")
    out.append("        local faction = tostring(entry.faction or \"\")")
    out.append("        if opts and tostring(opts.faction or \"\") ~= \"\" and faction ~= tostring(opts.faction or \"\") then return false end")
    out.append("        if opts and tostring(opts.exclude_faction or \"\") ~= \"\" and faction == tostring(opts.exclude_faction or \"\") then return false end")
    out.append("        if opts and tostring(opts.def_id or \"\") ~= \"\" and tostring(entry.def_id or \"\") ~= tostring(opts.def_id or \"\") then return false end")
    out.append("        return true")
    out.append("    end")
    out.append("    local function ray3d_trace(wx, wy, angle, max_range, opts)")
    out.append(f"        local cap = tonumber(max_range or (opts and opts.max_range) or {max(md.width, md.height) * md.tile_size}) or 0")
    out.append(f"        if cap <= 0 then cap = {max(md.width, md.height) * md.tile_size} end")
    out.append("        local radians = math.rad(tonumber(angle or 0) or 0)")
    out.append("        local dx = math.cos(radians)")
    out.append("        local dy = math.sin(radians)")
    out.append(f"        local step_len = math.max(2, tonumber(opts and opts.step_len or 0) or math.floor({md.tile_size} / 8))")
    out.append("        local best = _ray3d_wall_hit(wx, wy, dx, dy, cap, step_len)")
    out.append("        if not best then")
    out.append("            best = {kind = \"none\", distance = cap, x = (wx or 0) + dx * cap, y = (wy or 0) + dy * cap, col = -1, row = -1}")
    out.append("        end")
    out.append("        for _, entry in pairs(_actors3d) do")
    out.append("            if _ray3d_actor_matches(entry, opts) then")
    out.append("                local ex = (entry.x or 0) - (wx or 0)")
    out.append("                local ey = (entry.y or 0) - (wy or 0)")
    out.append("                local proj = ex * dx + ey * dy")
    out.append("                if proj >= 0 and proj <= cap then")
    out.append("                    local radius = math.max(1, tonumber(entry.radius or 16) or 16)")
    out.append("                    local center_sq = ex * ex + ey * ey")
    out.append("                    local perp_sq = center_sq - proj * proj")
    out.append("                    if perp_sq <= radius * radius then")
    out.append("                        local thc = math.sqrt(math.max(0, radius * radius - perp_sq))")
    out.append("                        local hit_dist = proj - thc")
    out.append("                        if hit_dist < 0 then hit_dist = proj + thc end")
    out.append("                        if hit_dist >= 0 and hit_dist < (tonumber(best.distance or math.huge) or math.huge) then")
    out.append("                            best = {kind = \"actor\", distance = hit_dist, x = (wx or 0) + dx * hit_dist, y = (wy or 0) + dy * hit_dist, ")
    out.append(f"                                col = math.floor((((wx or 0) + dx * hit_dist)) / {md.tile_size}), row = math.floor((((wy or 0) + dy * hit_dist)) / {md.tile_size}), ")
    out.append("                                actor_id = entry.id, def_id = entry.def_id, faction = entry.faction, sprite_idx = entry.sprite_idx}")
    out.append("                        end")
    out.append("                    end")
    out.append("                end")
    out.append("            end")
    out.append("        end")
    out.append("        return best")
    out.append("    end")
    out.append("    local function ray3d_hitscan(max_range, opts)")
    out.append("        local pl = RayCast3D.getPlayer()")
    out.append("        if not pl then return {kind = \"none\", distance = 0, x = 0, y = 0, col = -1, row = -1} end")
    out.append("        return ray3d_trace(pl.x or 0, pl.y or 0, pl.angle or 0, max_range, opts)")
    out.append("    end")
    out.append("    local function ray3d_hitscan_player(max_range, opts)")
    out.append("        return ray3d_hitscan(max_range, opts)")
    out.append("    end")
    out.append("    local function ray3d_trace_actor(id, max_range, opts)")
    out.append("        local entry = actor3d_sync_entry(id)")
    out.append("        if not entry then return {kind = \"none\", distance = 0, x = 0, y = 0, col = -1, row = -1} end")
    out.append("        local trace_opts = {}")
    out.append("        if type(opts) == \"table\" then")
    out.append("            for k, v in pairs(opts) do trace_opts[k] = v end")
    out.append("        end")
    out.append("        if trace_opts.ignore_self ~= false and tostring(trace_opts.ignore_actor_id or \"\") == \"\" then")
    out.append("            trace_opts.ignore_actor_id = entry.id")
    out.append("        end")
    out.append("        return ray3d_trace(entry.x or 0, entry.y or 0, entry.angle or 0, max_range, trace_opts)")
    out.append("    end")


def _get_raycast3d_config(scene):
    comp = next((c for c in scene.components if c.component_type == "Raycast3DConfig"), None)
    return comp.config if comp else {}


def _resolve_3d_patrol_component(scene, placed_object):
    patrol_id = str(getattr(placed_object, "actor_patrol_path_id", "") or "").strip()
    if not patrol_id:
        return None
    for comp in getattr(scene, "components", []) or []:
        if getattr(comp, "component_type", "") == "Path" and getattr(comp, "id", "") == patrol_id:
            return comp
    return None


def _filter_3d_path_points(raw_points: list[dict], md) -> list[dict]:
    tile = max(1, int(getattr(md, "tile_size", 64) or 64))
    filtered: list[dict] = []
    for point in raw_points or []:
        if not isinstance(point, dict):
            continue
        try:
            x = float(point.get("x", 0))
            y = float(point.get("y", 0))
        except Exception:
            continue
        col = int(x // tile)
        row = int(y // tile)
        if not (0 <= col < md.width and 0 <= row < md.height):
            continue
        if md.get(col, row) != 0:
            continue
        filtered.append(point)
    return filtered


def _scene_3d_to_lua(scene, scene_num: int, project) -> str:
    out = []
    out.append(f"-- scenes/scene_{scene_num:03d}.lua")
    out.append(f"-- 3D Scene {scene_num}: {scene.name or 'Unnamed'}")
    out.append("")
    out.append(f"function scene_{scene_num}()")
    md         = scene.map_data
    rcfg       = _get_raycast3d_config(scene)
    mode       = rcfg.get("movement_mode", scene.movement_mode)
    control_profile = rcfg.get("control_profile", "free_modern" if mode == "free" else "grid_strafe")
    move_speed = rcfg.get("move_speed", scene.move_speed)
    turn_speed = rcfg.get("turn_speed", scene.turn_speed)
    interact_distance = int(rcfg.get("interact_distance", 80) or 80)
    view_size = int(rcfg.get("render_view_size", 60) or 60)
    default_object_interact_distance = int(rcfg.get("default_object_interact_distance", 80) or 80)
    cells_str = ", ".join(str(c) for c in md.cells)
    out.append(f"    local map_cells = {{ {cells_str} }}")
    out.append(f"    for i = 1, #map_cells do")
    out.append(f"        if map_cells[i] >= 2 then")
    out.append(f"            local tex_key = map_tex_keys[map_cells[i] - 1]")
    out.append(f"            if tex_key and images[tex_key] then")
    out.append(f"                map_cells[i] = images[tex_key]")
    out.append(f"            else")
    out.append(f"                map_cells[i] = 1")
    out.append(f"            end")
    out.append(f"        end")
    out.append(f"    end")
    fr, fg, fb = int(md.floor_color[1:3], 16), int(md.floor_color[3:5], 16), int(md.floor_color[5:7], 16)
    sr, sg, sb = int(md.sky_color[1:3], 16),   int(md.sky_color[3:5], 16),   int(md.sky_color[5:7], 16)
    wr, wg, wb = int(md.wall_color[1:3], 16),  int(md.wall_color[3:5], 16),  int(md.wall_color[5:7], 16)
    out.append(f"    RayCast3D.setResolution(960, 544)")
    out.append(f"    RayCast3D.setViewsize({view_size})")
    out.append(f"    RayCast3D.loadMap(map_cells, {md.width}, {md.height}, {md.tile_size}, {md.wall_height})")
    out.append(f"    RayCast3D.setWallColor(Color.new({wr}, {wg}, {wb}))")
    out.append(f"    RayCast3D.setFloorColor(Color.new({fr}, {fg}, {fb}))")
    out.append(f"    RayCast3D.setSkyColor(Color.new({sr}, {sg}, {sb}))")
    out.append(f"    RayCast3D.enableFloor({_lua_bool(md.floor_on)})")
    out.append(f"    RayCast3D.enableSky({_lua_bool(md.sky_on)})")
    out.append(f"    RayCast3D.useShading({_lua_bool(md.shading)})")
    out.append(f"    RayCast3D.setAccuracy({md.accuracy})")
    # ── Tile metadata (doors, exits, triggers) ──
    # Must come after loadMap so loadTileMeta can read initial map cell values.
    has_tile_meta = _emit_tile_meta_table(out, md, project, indent="    ")
    # Derive flags for what tile types are present — drives loop emit below
    has_exits    = any(tm.type == "exit"    for tm in md.tile_meta.values())
    has_doors    = any(tm.type == "door"    for tm in md.tile_meta.values())
    has_triggers = any(tm.type in ("trigger", "switch") for tm in md.tile_meta.values())
    has_interact = has_doors or has_exits or has_triggers
    # ── S10: emit door state helpers if any behavior uses door actions ──
    # Scan each placed object's effective behavior graph so we only emit the
    # helpers when they're actually needed.
    _DOOR_ACTIONS = {"open_door", "close_door", "toggle_door"}
    _needs_door_helpers = False
    for _po in scene.placed_objects:
        _od = project.get_object_def(_po.object_def_id)
        _all = effective_placed_behaviors(_po, _od)
        for _b in _all:
            for _a in _b.actions:
                if (isinstance(_a, dict) and _a.get("action_type") in _DOOR_ACTIONS) or \
                   (hasattr(_a, "action_type") and _a.action_type in _DOOR_ACTIONS):
                    _needs_door_helpers = True
                    break
            if _needs_door_helpers:
                break
        if _needs_door_helpers:
            break
    if _needs_door_helpers:
        _emit_3d_door_helpers(out, md)
    spawn_world_x = md.spawn_x * md.tile_size + md.tile_size // 2
    spawn_world_y = md.spawn_y * md.tile_size + md.tile_size // 2
    out.append(f"    RayCast3D.spawnPlayer({spawn_world_x}, {spawn_world_y}, {md.spawn_angle})")
    out.append("    RayCast3D.clearSprites()")
    out.append("    RayCast3D.clearObjects()")
    out.append("    scene_paths = {}")
    for comp in scene.components:
        if comp.component_type == "Path":
            pname = _safe_name(comp.config.get("path_name", "path"))
            raw_points = _filter_3d_path_points(comp.config.get("points", []), md)
            is_closed = comp.config.get("closed", False)
            baked = _bake_bezier_points(raw_points, is_closed, interval=2.0)
            if baked:
                pts_str = ", ".join([f"{{x={int(pt['x'])}, y={int(pt['y'])}}}" for pt in baked])
                out.append(f'    scene_paths["{pname}"] = {{{pts_str}}}')
    _emit_3d_actor_helpers(out, md)
    # ── Register 3D billboard sprites ──
    sprite_objects = [po for po in scene.placed_objects if getattr(po, "is_3d", False) and not getattr(po, "hud_mode", False)]
    _hud_ordered = [
        (idx, po) for idx, po in enumerate(scene.placed_objects)
        if getattr(po, "is_3d", False) and getattr(po, "hud_mode", False)
    ]
    _hud_ordered.sort(key=lambda item: (getattr(item[1], "draw_layer", 2), item[0]))
    hud_objects = [po for _, po in _hud_ordered]
    has_blocking = False
    # sprite_idx_map: instance_id → 1-based sprite index, for registerObject
    sprite_idx_map: dict[str, int] = {}
    valid_sprite_objects = []  # only POs that actually emit an addSprite call
    skipped_sprite_objects: list[tuple[Any, str]] = []
    for po in sprite_objects:
        od = project.get_object_def(po.object_def_id)
        kind, detail = _classify_3d_billboard(od, project)
        if not kind:
            skipped_sprite_objects.append((po, detail))
            continue
        vname = _placed_var_name(po)
        world_x = int((po.grid_x + po.offset_x) * md.tile_size)
        world_y = int((po.grid_y + po.offset_y) * md.tile_size)
        sprite_idx = len(valid_sprite_objects) + 1  # 1-based, matches addSprite return
        opacity_255 = int(round(po.opacity * 255))
        if kind == "animation":
            first_slot = _first_animation_slot(od, project)
            if first_slot is None:
                skipped_sprite_objects.append((po, "Animation object has no valid animation slot"))
                continue
            slot_name, ani_id, _ani_export = first_slot
            ani_playing = "true" if od.ani_play_on_spawn and not od.ani_start_paused else "false"
            start_frame = od.ani_pause_frame if od.ani_start_paused else 0
            out.append(
                f"    RayCast3D.addSprite({world_x}, {world_y}, "
                f"((ani_sheets[{_lua_str(ani_id)}] and ani_sheets[{_lua_str(ani_id)}][1]) or nil), "
                f"{po.scale}, {po.vertical_offset}, {_lua_bool(po.blocking)})"
            )
            out.append(f"    {vname}_x = {world_x}")
            out.append(f"    {vname}_y = {world_y}")
            out.append(f"    {vname}_visible = {_lua_bool(po.visible)}")
            out.append(f"    {vname}_scale = {po.scale}")
            out.append(f"    {vname}_rotation = {po.rotation}")
            out.append(f"    {vname}_angle = {po.rotation}")
            out.append(f"    {vname}_opacity = {opacity_255}")
            out.append(f"    {vname}_blocking = {_lua_bool(po.blocking)}")
            out.append(f"    {vname}_start_x = {world_x}")
            out.append(f"    {vname}_start_y = {world_y}")
            out.append(f"    {vname}_spin_speed = 0.0")
            out.append(f"    {vname}_interactable = true")
            out.append(f"    {vname}_ani_slots = {{")
            for slot in od.ani_slots:
                sname = str(slot.get("name", "")).strip()
                sfid = str(slot.get("ani_file_id", "")).strip()
                if not sname or not sfid or not project.get_animation_export(sfid):
                    continue
                out.append(f"        [{_lua_str(sname)}] = {_lua_str(sfid)},")
            out.append(f"    }}")
            out.append(f"    {vname}_ani_id = {_lua_str(ani_id)}")
            out.append(f"    {vname}_ani_slot_name = {_lua_str(slot_name)}")
            out.append(f"    {vname}_ani_frame = {start_frame}")
            out.append(f"    {vname}_ani_playing = {ani_playing}")
            out.append(f"    {vname}_ani_timer = 0")
            out.append(f"    {vname}_ani_loop = {_lua_bool(od.ani_loop)}")
            out.append(f"    {vname}_ani_fps = {od.ani_fps_override}")
            out.append(f"    {vname}_ani_done = false")
            out.append(f"    {vname}_flip_h = {_lua_bool(od.ani_flip_h)}")
            out.append(f"    {vname}_flip_v = {_lua_bool(od.ani_flip_v)}")
            out.append("    do")
            out.append(f"        local _sheet, _sx, _sy, _sw, _sh = ani_get_sheet_and_rect({vname}_ani_id, {vname}_ani_frame)")
            out.append("        if _sheet then")
            out.append(f"            RayCast3D.setSpriteFrame({sprite_idx}, _sheet, _sx, _sy, _sw, _sh)")
            out.append("        end")
            out.append("    end")
        elif kind == "frame_anim":
            fname = _regular_frame_image_name(od, project, 0)
            out.append(f"    RayCast3D.addSprite({world_x}, {world_y}, images[{_lua_str(fname)}], {po.scale}, {po.vertical_offset}, {_lua_bool(po.blocking)})")
            out.append(f"    {vname}_x = {world_x}")
            out.append(f"    {vname}_y = {world_y}")
            out.append(f"    {vname}_visible = {_lua_bool(po.visible)}")
            out.append(f"    {vname}_scale = {po.scale}")
            out.append(f"    {vname}_rotation = {po.rotation}")
            out.append(f"    {vname}_angle = {po.rotation}")
            out.append(f"    {vname}_opacity = {opacity_255}")
            out.append(f"    {vname}_blocking = {_lua_bool(po.blocking)}")
            out.append(f"    {vname}_start_x = {world_x}")
            out.append(f"    {vname}_start_y = {world_y}")
            out.append(f"    {vname}_spin_speed = 0.0")
            out.append(f"    {vname}_interactable = true")
            out.append(f"    {vname}_frames = {{")
            for fi, fr in enumerate(od.frames):
                fname = _regular_frame_image_name(od, project, fi)
                dur = max(1, fr.duration_frames)
                out.append(f"        [{fi}] = {{img={_lua_str(fname)}, dur={dur}}},")
            out.append(f"    }}")
            out.append(f"    {vname}_frame = 0")
            out.append(f"    {vname}_frame_timer = 0")
            out.append(f"    {vname}_frame_playing = false")
            out.append(f"    {vname}_frame_loop = true")
        else:
            fname = _regular_frame_image_name(od, project, 0)
            out.append(f"    RayCast3D.addSprite({world_x}, {world_y}, images[{_lua_str(fname)}], {po.scale}, {po.vertical_offset}, {_lua_bool(po.blocking)})")
            out.append(f"    {vname}_x = {world_x}")
            out.append(f"    {vname}_y = {world_y}")
            out.append(f"    {vname}_visible = {_lua_bool(po.visible)}")
            out.append(f"    {vname}_scale = {po.scale}")
            out.append(f"    {vname}_rotation = {po.rotation}")
            out.append(f"    {vname}_angle = {po.rotation}")
            out.append(f"    {vname}_opacity = {opacity_255}")
            out.append(f"    {vname}_blocking = {_lua_bool(po.blocking)}")
            out.append(f"    {vname}_start_x = {world_x}")
            out.append(f"    {vname}_start_y = {world_y}")
            out.append(f"    {vname}_spin_speed = 0.0")
            out.append(f"    {vname}_interactable = true")
        valid_sprite_objects.append(po)
        sprite_idx_map[po.instance_id] = sprite_idx
        if po.blocking:
            has_blocking = True
    for po, reason in skipped_sprite_objects:
        out.append(f"    -- skipped 3D object {po.instance_id}: {reason}")
    # ── Named object registry ──
    # registerObject binds each sprite to its instance_id string so the scene
    # loop can look up behaviors by id via getInteractableObject().
    # interact_range defaults to 80 (tile_size * 1.25); S8 will expose this
    # per-object in the editor and pass getattr(po, "interact_range", 80) here.
    has_3d_objects = bool(valid_sprite_objects)
    if has_3d_objects:
        out.append("    -- Named 3D object registry")
        for po in valid_sprite_objects:
            sidx = sprite_idx_map[po.instance_id]
            interact_range = getattr(po, "interact_range", default_object_interact_distance)
            out.append(f"    RayCast3D.registerObject({_lua_str(po.instance_id)}, {sidx}, {interact_range})")
            od = project.get_object_def(po.object_def_id)
            vname = _placed_var_name(po)
            actor_state = getattr(od, "actor_start_state", "idle") if od else "idle"
            actor_faction = getattr(od, "actor_faction", "") if od else ""
            actor_health = int(getattr(od, "actor_max_health", 100) or 100) if od else 100
            actor_speed = float(getattr(od, "actor_move_speed", 1.0) or 1.0) if od else 1.0
            actor_radius = float(getattr(od, "actor_radius", 16.0) or 16.0) if od else 16.0
            actor_sight = float(getattr(od, "actor_sight_range", 160.0) or 160.0) if od else 160.0
            actor_attack = float(getattr(od, "actor_attack_range", 48.0) or 48.0) if od else 48.0
            patrol_comp = _resolve_3d_patrol_component(scene, po)
            actor_patrol_raw = ""
            if patrol_comp is not None:
                actor_patrol_raw = str(patrol_comp.config.get("path_name", "") or "").strip()
            elif od:
                actor_patrol_raw = str(getattr(od, "actor_patrol_path", "") or "").strip()
            actor_patrol = _safe_name(actor_patrol_raw) if actor_patrol_raw else ""
            out.append(
                f"    actor3d_register({_lua_str(po.instance_id)}, {_lua_str(po.object_def_id)}, {_lua_str(vname)}, {sidx}, "
                f"{{x={vname}_x, y={vname}_y, angle={vname}_angle, visible={vname}_visible, blocking={vname}_blocking, "
                f"interactable={vname}_interactable, alive=true, state={_lua_str(actor_state)}, faction={_lua_str(actor_faction)}, health={actor_health}, "
                f"max_health={actor_health}, speed={actor_speed}, radius={actor_radius}, sight_range={actor_sight}, "
                f"attack_range={actor_attack}, patrol_path={_lua_str(actor_patrol)}, scale={vname}_scale}})"
            )
            if actor_patrol:
                out.append(f"    actor3d_start_patrol({_lua_str(po.instance_id)}, {_lua_str(actor_patrol)}, {actor_speed}, true)")
        # ── Object interact dispatch table ──
        # Each entry is a function called when the player interacts with that object.
        # S9 will populate on_3d_interact behaviors here; for now the table exists
        # so the scene loop can call it safely even with no behaviors wired yet.
        out.append("    local _obj_dispatch = {}")
        for po in valid_sprite_objects:
            od = project.get_object_def(po.object_def_id)
            vname = _placed_var_name(po)
            all_behs = effective_placed_behaviors(po, od)
            interact_behs = [b for b in all_behs if b.trigger == "on_3d_interact"]
            if interact_behs:
                out.append(f"    _obj_dispatch[{_lua_str(po.instance_id)}] = function()")
                for beh in interact_behs:
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"        {line}")
                out.append(f"    end")
    # ── HUD object visibility variables ──
    for po in hud_objects:
        vname = f"hud_{po.instance_id}"
        out.append(f"    local {vname}_visible = {_lua_bool(po.visible)}")
    out.append(f"    local _ceil_c  = Color.new({sr}, {sg}, {sb})")
    out.append(f"    local _floor_c = Color.new({fr}, {fg}, {fb})")
    out.append("    app_ui_reset()")
    for line in _plugin_scene_hook_lines(scene, project, "lua_scene_init"):
        out.append(f"    {line}")
    out.append("    local advance = false")
    out.append("    while not advance do")

    # ── Frame header: input + quit ──
    _emit_3d_loop_header(out)
    for line in _plugin_scene_hook_lines(scene, project, "lua_scene_loop"):
        out.append(f"        {line}")

    # ── Movement + sprite collision rollback ──
    _emit_3d_loop_movement(out, mode, move_speed, turn_speed, md, has_blocking, control_profile)

    # ── Tile interact + 3D object interact (Cross button) ──
    _emit_3d_loop_interact(out, has_interact, has_exits, has_triggers, has_3d_objects, interact_distance)

    # ── Exit-on-step (walk onto exit tile, no button press) ──
    _emit_3d_loop_exit_on_step(out, has_exits, md)

    # ── 3D actor patrol + canonical state sync (before behavior queries) ──
    out.append("        actor3d_tick_runtime()")
    out.append("        nav3d_update_followers()")
    out.append("        actor3d_update_patrols()")
    out.append("        actor3d_sync_all()")

    # ── Per-sprite per-frame behavior dispatch ──
    _emit_3d_loop_sprite_dispatch(out, valid_sprite_objects, project)

    # ── Actor animation/frame state updates ──
    _emit_3d_actor_animation_updates(out, valid_sprite_objects, project)

    # ── Sync canonical actor state back into the raycaster ──
    out.append("        actor3d_sync_all()")
    _emit_3d_actor_sync(out, valid_sprite_objects, sprite_idx_map, project)

    # ── Render block: background, raycaster, sprites, HUD ──
    _emit_3d_loop_render(
        out,
        md,
        hud_objects,
        project,
        skybox_img=_resolve_skybox(md, project),
        plugin_draw_lines=_plugin_scene_hook_lines(scene, project, "lua_scene_draw"),
    )

    out.append("    end")
    out.append("end")
    out.append("")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
#  COLLISION LIB
# ─────────────────────────────────────────────────────────────

def _make_collision_lib() -> str:
    lines = [
        "-- Collision grid helpers",
        "collision_grids = {}",
        "obj_collision = {}",
        "obj_collision_bounds = {}",
        "solid_object_defs = {}",
        "",
        "function collision_cell_index(grid, col, row)",
        "    if not grid then return nil end",
        "    local c = math.floor(tonumber(col) or 0)",
        "    local r = math.floor(tonumber(row) or 0)",
        "    if c < 0 or c >= grid.map_width or r < 0 or r >= grid.map_height then",
        "        return nil",
        "    end",
        "    return r * grid.map_width + c + 1",
        "end",
        "",
        "function read_collision_cell(grid, col, row)",
        "    local idx = collision_cell_index(grid, col, row)",
        "    if not idx then return nil end",
        "    return grid.cells[idx] or 0",
        "end",
        "",
        "function write_collision_cell(grid, col, row, value)",
        "    local idx = collision_cell_index(grid, col, row)",
        "    if not idx then return false end",
        "    grid.cells[idx] = (tonumber(value) or 0) ~= 0 and 1 or 0",
        "    return true",
        "end",
        "",
        "function toggle_collision_cell(grid, col, row)",
        "    local idx = collision_cell_index(grid, col, row)",
        "    if not idx then return nil end",
        "    local next_value = (grid.cells[idx] or 0) == 1 and 0 or 1",
        "    grid.cells[idx] = next_value",
        "    return next_value",
        "end",
        "",
        "function check_collision(grid, wx, wy)",
        "    local col = math.floor(wx / grid.tile_size)",
        "    local row = math.floor(wy / grid.tile_size)",
        "    local value = read_collision_cell(grid, col, row)",
        "    if value == nil then return true end",
        "    return value == 1",
        "end",
        "",
        "function check_collision_rect(grid, wx, wy, w, h)",
        "    if check_collision(grid, wx,     wy    ) then return true end",
        "    if check_collision(grid, wx+w-1, wy    ) then return true end",
        "    if check_collision(grid, wx,     wy+h-1) then return true end",
        "    if check_collision(grid, wx+w-1, wy+h-1) then return true end",
        "    return false",
        "end",
        "",
        "-- Object collision box helpers",
        "function aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)",
        "    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by",
        "end",
        "",
        "function def_frame_boxes(def_id, slot_name, frame)",
        "    local frames = obj_collision[def_id]",
        "    if not frames then return {} end",
        "    local wanted = tostring(slot_name or \"\")",
        "    if wanted ~= \"\" then",
        "        local slot_frames = frames[wanted]",
        "        if slot_frames then",
        "            frames = slot_frames",
        "        elseif frames[1] == nil then",
        "            return {}",
        "        end",
        "    end",
        "    return frames[(tonumber(frame) or 0) + 1] or {}",
        "end",
        "",
        "function collision_role_matches(box_role, wanted)",
        "    local target = tostring(wanted or \"\")",
        "    if target == \"\" or target == \"Any\" then return true end",
        "    local role = tostring(box_role or \"Physics\")",
        "    if role == \"\" then role = \"Physics\" end",
        "    return role == target",
        "end",
        "",
        "function filter_boxes_by_role(boxes, wanted)",
        "    if wanted == nil or wanted == \"\" or wanted == \"Any\" then",
        "        return boxes or {}, boxes ~= nil and #boxes > 0",
        "    end",
        "    local filtered = {}",
        "    for _, b in ipairs(boxes or {}) do",
        "        if collision_role_matches(b.role, wanted) then",
        "            filtered[#filtered + 1] = b",
        "        end",
        "    end",
        "    return filtered, #filtered > 0",
        "end",
        "",
        "function def_frame_boxes_by_role(def_id, slot_name, frame, role_name)",
        "    return filter_boxes_by_role(def_frame_boxes(def_id, slot_name, frame), role_name)",
        "end",
        "",
        "function def_has_frame_boxes(def_id, slot_name, frame)",
        "    local boxes = def_frame_boxes(def_id, slot_name, frame)",
        "    return boxes ~= nil and #boxes > 0, boxes or {}",
        "end",
        "",
        "function def_bounds(def_id)",
        "    local bounds = obj_collision_bounds[def_id] or {}",
        "    return bounds.w or 0, bounds.h or 0",
        "end",
        "",
        "function boxes_overlap_rect(boxes, ox, oy, rx, ry, rw, rh)",
        "    for _, b in ipairs(boxes or {}) do",
        "        if aabb_overlap(ox + b.x, oy + b.y, b.w, b.h, rx, ry, rw, rh) then",
        "            return true",
        "        end",
        "    end",
        "    return false",
        "end",
        "",
        "function boxes_overlap_boxes(boxes_a, ax, ay, boxes_b, bx, by)",
        "    for _, a in ipairs(boxes_a or {}) do",
        "        for _, b in ipairs(boxes_b or {}) do",
        "            if aabb_overlap(ax + a.x, ay + a.y, a.w, a.h, bx + b.x, by + b.y, b.w, b.h) then",
        "                return true",
        "            end",
        "        end",
        "    end",
        "    return false",
        "end",
        "",
        "function check_obj_collision(def_id_a, ax, ay, aslot, af, def_id_b, bx, by, bslot, bf)",
        "    local boxes_a = def_frame_boxes(def_id_a, aslot, af)",
        "    local boxes_b = def_frame_boxes(def_id_b, bslot, bf)",
        "    return boxes_overlap_boxes(boxes_a, ax, ay, boxes_b, bx, by)",
        "end",
        "",
        "function check_def_collision(def_id_a, ax, ay, aslot, af, def_id_b, bx, by, bslot, bf)",
        "    local has_a, boxes_a = def_has_frame_boxes(def_id_a, aslot, af)",
        "    local has_b, boxes_b = def_has_frame_boxes(def_id_b, bslot, bf)",
        "    if has_a and has_b then",
        "        return check_obj_collision(def_id_a, ax, ay, aslot, af, def_id_b, bx, by, bslot, bf)",
        "    end",
        "    local aw, ah = def_bounds(def_id_a)",
        "    local bw, bh = def_bounds(def_id_b)",
        "    if has_a then",
        "        return boxes_overlap_rect(boxes_a, ax, ay, bx, by, bw, bh)",
        "    elseif has_b then",
        "        return boxes_overlap_rect(boxes_b, bx, by, ax, ay, aw, ah)",
        "    end",
        "    return aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)",
        "end",
        "",
        "function check_def_collision_filtered(def_id_a, ax, ay, aslot, af, role_a, def_id_b, bx, by, bslot, bf, role_b)",
        "    local allow_bounds_a = role_a == nil or role_a == \"\" or role_a == \"Any\"",
        "    local allow_bounds_b = role_b == nil or role_b == \"\" or role_b == \"Any\"",
        "    local boxes_a, has_a = def_frame_boxes_by_role(def_id_a, aslot, af, role_a)",
        "    local boxes_b, has_b = def_frame_boxes_by_role(def_id_b, bslot, bf, role_b)",
        "    if has_a and has_b then",
        "        return boxes_overlap_boxes(boxes_a, ax, ay, boxes_b, bx, by)",
        "    end",
        "    local aw, ah = def_bounds(def_id_a)",
        "    local bw, bh = def_bounds(def_id_b)",
        "    if has_a and allow_bounds_b then",
        "        return boxes_overlap_rect(boxes_a, ax, ay, bx, by, bw, bh)",
        "    elseif has_b and allow_bounds_a then",
        "        return boxes_overlap_rect(boxes_b, bx, by, ax, ay, aw, ah)",
        "    elseif allow_bounds_a and allow_bounds_b then",
        "        return aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)",
        "    end",
        "    return false",
        "end",
        "",
        "function check_def_collision_physics(def_id_a, ax, ay, aslot, af, def_id_b, bx, by, bslot, bf)",
        "    local boxes_a, has_a = def_frame_boxes_by_role(def_id_a, aslot, af, \"Physics\")",
        "    local boxes_b, has_b = def_frame_boxes_by_role(def_id_b, bslot, bf, \"Physics\")",
        "    local aw, ah = def_bounds(def_id_a)",
        "    local bw, bh = def_bounds(def_id_b)",
        "    if has_a and has_b then",
        "        return boxes_overlap_boxes(boxes_a, ax, ay, boxes_b, bx, by)",
        "    elseif has_a then",
        "        return boxes_overlap_rect(boxes_a, ax, ay, bx, by, bw, bh)",
        "    elseif has_b then",
        "        return boxes_overlap_rect(boxes_b, bx, by, ax, ay, aw, ah)",
        "    end",
        "    return aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)",
        "end",
        "",
        "function check_obj_vs_grid(grid, def_id, ox, oy, slot_name, frame)",
        "    local boxes, has_boxes = def_frame_boxes_by_role(def_id, slot_name, frame, \"Physics\")",
        "    if has_boxes then",
        "        for _, b in ipairs(boxes) do",
        "            if check_collision_rect(grid, ox + b.x, oy + b.y, b.w, b.h) then",
        "                return true",
        "            end",
        "        end",
        "        return false",
        "    end",
        "    local w, h = def_bounds(def_id)",
        "    if w <= 0 or h <= 0 then return false end",
        "    return check_collision_rect(grid, ox, oy, w, h)",
        "end",
        "",
        "function check_obj_vs_solids(self_handle, def_id, ox, oy, slot_name, frame)",
        "    local self_key = tostring(self_handle or \"\")",
        "    for handle, entry in pairs(runtime_objects or {}) do",
        "        if entry and entry.kind == \"placed\" and handle ~= self_key and solid_object_defs[entry.def_id] then",
        "            local tx = prim and prim.get_x and prim.get_x(handle) or nil",
        "            local ty = prim and prim.get_y and prim.get_y(handle) or nil",
        "            if tx ~= nil and ty ~= nil then",
        "                local target_frame = 0",
        "                local target_slot = \"\"",
        "                if entry.var and entry.var ~= \"\" then",
        "                    target_frame = _G[entry.var .. \"_ani_frame\"] or 0",
        "                    target_slot = _G[entry.var .. \"_ani_slot_name\"] or \"\"",
        "                end",
        "                if check_def_collision_physics(def_id, ox, oy, slot_name, frame, entry.def_id, tx, ty, target_slot, target_frame) then",
        "                    return true",
        "                end",
        "            end",
        "        end",
        "    end",
        "    return false",
        "end",
        "",
        "function overlap_target_matches(entry, target_id)",
        "    local wanted = tostring(target_id or \"\")",
        "    if wanted == \"\" then return true end",
        "    return entry ~= nil and (entry.def_id == wanted or entry.instance_id == wanted)",
        "end",
        "",
        "function entry_anim_state(entry)",
        "    local target_frame = 0",
        "    local target_slot = \"\"",
        "    if entry and entry.var and entry.var ~= \"\" then",
        "        target_frame = _G[entry.var .. \"_ani_frame\"] or 0",
        "        target_slot = _G[entry.var .. \"_ani_slot_name\"] or \"\"",
        "    end",
        "    return target_slot, target_frame",
        "end",
        "",
        "function count_object_overlaps(self_handle, def_id, ox, oy, slot_name, frame, target_id, source_role, target_role)",
        "    local total = 0",
        "    local self_key = tostring(self_handle or \"\")",
        "    for handle, entry in pairs(runtime_objects or {}) do",
        "        if entry and handle ~= self_key and overlap_target_matches(entry, target_id) then",
        "            local tx = prim and prim.get_x and prim.get_x(handle) or nil",
        "            local ty = prim and prim.get_y and prim.get_y(handle) or nil",
        "            if tx ~= nil and ty ~= nil then",
        "                local target_slot, target_frame = entry_anim_state(entry)",
        "                if check_def_collision_filtered(def_id, ox, oy, slot_name, frame, source_role, entry.def_id, tx, ty, target_slot, target_frame, target_role) then",
        "                    total = total + 1",
        "                end",
        "            end",
        "        end",
        "    end",
        "    return total",
        "end",
        "",
        "function any_object_overlap(self_handle, def_id, ox, oy, slot_name, frame, target_id, source_role, target_role)",
        "    return count_object_overlaps(self_handle, def_id, ox, oy, slot_name, frame, target_id, source_role, target_role) > 0",
        "end",
    ]
    return "\n".join(lines)

def _make_lightmap_lib() -> str:
    lines = [
        "-- Lightmap helpers",
        "light_grids = {}",
        "",
        "function draw_light_grid(grid)",
        "    if not grid or not grid.visible then return end",
        "    local ts = grid.tile_size or 32",
        "    local mw = grid.map_width or 0",
        "    local mh = grid.map_height or 0",
        "    local op = grid.opacity or 255",
        "    local cr = grid.color_r or 0",
        "    local cg = grid.color_g or 0",
        "    local cb = grid.color_b or 0",
        "    for row = 0, mh - 1 do",
        "        local col = 0",
        "        while col < mw do",
        "            local idx = row * mw + col + 1",
        "            local dark = grid.cells[idx] or 0",
        "            if dark <= 0 then",
        "                col = col + 1",
        "            else",
        "                local start_col = col",
        "                col = col + 1",
        "                while col < mw do",
        "                    local next_idx = row * mw + col + 1",
        "                    local next_dark = grid.cells[next_idx] or 0",
        "                    if next_dark ~= dark then break end",
        "                    col = col + 1",
        "                end",
        "                local alpha = math.floor(dark * (op / 255))",
        "                if alpha > 255 then alpha = 255 end",
        "                if alpha > 0 then",
        "                    local x1 = (start_col * ts - camera.x) * camera.zoom + 480 + shake_offset_x",
        "                    local x2 = (col * ts - camera.x) * camera.zoom + 480 + shake_offset_x",
        "                    local y1 = (row * ts - camera.y) * camera.zoom + 272 + shake_offset_y",
        "                    local y2 = (((row + 1) * ts) - camera.y) * camera.zoom + 272 + shake_offset_y",
        "                    Graphics.fillRect(x1, x2, y1, y2, Color.new(cr, cg, cb, alpha))",
        "                end",
        "            end",
        "        end",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _make_group_lib() -> str:
    lines = [
        "-- lib/groups.lua",
        "-- Runtime group membership helpers.",
        "-- _groups is rebuilt per-scene from design-time declarations.",
        "-- group_add / group_remove allow runtime modification.",
        "_groups = {}",
        "",
        "function group_add(group_name, obj_name)",
        "    if not _groups[group_name] then _groups[group_name] = {} end",
        "    for _, v in ipairs(_groups[group_name]) do",
        "        if v == obj_name then return end",
        "    end",
        "    table.insert(_groups[group_name], obj_name)",
        "end",
        "",
        "function group_remove(group_name, obj_name)",
        "    local g = _groups[group_name]",
        "    if not g then return end",
        "    for i, v in ipairs(g) do",
        "        if v == obj_name then table.remove(g, i) return end",
        "    end",
        "end",
        "",
        "function group_has(group_name, obj_name)",
        "    local g = _groups[group_name]",
        "    if not g then return false end",
        "    for _, v in ipairs(g) do",
        "        if v == obj_name then return true end",
        "    end",
        "    return false",
        "end",
        "",
        "function group_count(group_name)",
        "    local g = _groups[group_name]",
        "    return g and #g or 0",
        "end",
    ]
    return "\n".join(lines)


def _make_primitives_lib() -> str:
    lines = [
        "-- lib/primitives.lua",
        "prim = prim or {}",
        "runtime_objects = runtime_objects or {}",
        "spawn_object_defs = spawn_object_defs or {}",
        "",
        "local function _prim_cleanup_spawned(handle, entry)",
        "    if entry and entry.kind == \"spawned\" and (_live_objects == nil or _live_objects[handle] == nil) then",
        "        runtime_objects[handle] = nil",
        "        return nil",
        "    end",
        "    return entry",
        "end",
        "",
        "function prim.reset_scene()",
        "    runtime_objects = {}",
        "end",
        "",
        "function prim.register_placed(handle, def_id, instance_id, var_name)",
        "    runtime_objects[handle] = {",
        "        handle = handle,",
        "        kind = \"placed\",",
        "        def_id = def_id or \"\",",
        "        instance_id = instance_id or handle,",
        "        var = var_name or \"\",",
        "    }",
        "    return runtime_objects[handle]",
        "end",
        "",
        "function prim.register_spawned(handle, def_id, state, tags)",
        "    runtime_objects[handle] = {",
        "        handle = handle,",
        "        kind = \"spawned\",",
        "        def_id = def_id or \"\",",
        "        instance_id = nil,",
        "        state = state,",
        "        tags = tags or {},",
        "    }",
        "    return runtime_objects[handle]",
        "end",
        "",
        "function prim.unregister(handle)",
        "    runtime_objects[handle] = nil",
        "end",
        "",
        "function prim.entry(handle)",
        "    if handle == nil then return nil end",
        "    return _prim_cleanup_spawned(handle, runtime_objects[handle])",
        "end",
        "",
        "function prim.exists(handle)",
        "    return prim.entry(handle) ~= nil",
        "end",
        "",
        "function prim.var_name(handle)",
        "    local entry = prim.entry(handle)",
        "    return entry and entry.var or nil",
        "end",
        "",
        "function prim.handle_from_var(var_name)",
        "    local wanted = tostring(var_name or \"\")",
        "    if wanted == \"\" then return nil end",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if entry and entry.var == wanted then",
        "            return handle",
        "        end",
        "    end",
        "    return nil",
        "end",
        "",
        "function prim.handles_by_def(def_id)",
        "    local out = {}",
        "    local wanted = tostring(def_id or \"\")",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if entry and (wanted == \"\" or entry.def_id == wanted) then",
        "            out[#out + 1] = handle",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.handles_in_group(group_name)",
        "    local out = {}",
        "    local src = _groups and _groups[group_name] or nil",
        "    if not src then return out end",
        "    for i = 1, #src do",
        "        if prim.exists(src[i]) then",
        "            out[#out + 1] = src[i]",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.handle_for_object(target_id)",
        "    local wanted = tostring(target_id or \"\")",
        "    if wanted == \"\" then return nil end",
        "    if prim.exists(wanted) then return wanted end",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if entry and (entry.instance_id == wanted or entry.def_id == wanted) then",
        "            return handle",
        "        end",
        "    end",
        "    return nil",
        "end",
        "",
        "local function _prim_has_tag(entry, tag)",
        "    if not entry or not entry.tags or tag == nil or tag == \"\" then return false end",
        "    if entry.tags[tag] == true then return true end",
        "    for _, value in pairs(entry.tags) do",
        "        if value == tag then return true end",
        "    end",
        "    return false",
        "end",
        "",
        "local function _prim_matches(handle, entry, filter)",
        "    if not entry then return false end",
        "    filter = filter or {}",
        "    if filter.kind and filter.kind ~= \"\" and entry.kind ~= filter.kind then return false end",
        "    if filter.def_id and filter.def_id ~= \"\" and entry.def_id ~= filter.def_id then return false end",
        "    if filter.exclude_handle and filter.exclude_handle == handle then return false end",
        "    if filter.group_name and filter.group_name ~= \"\" and not group_has(filter.group_name, handle) then return false end",
        "    if filter.tag and filter.tag ~= \"\" and not _prim_has_tag(entry, filter.tag) then return false end",
        "    return true",
        "end",
        "",
        "function prim.get_x(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return nil end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_x\"]",
        "    end",
        "    return entry.state and entry.state.x or nil",
        "end",
        "",
        "function prim.get_y(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return nil end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_y\"]",
        "    end",
        "    return entry.state and entry.state.y or nil",
        "end",
        "",
        "function prim.set_x(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_x\"] = value",
        "    elseif entry.state then",
        "        entry.state.x = value",
        "    end",
        "end",
        "",
        "function prim.set_y(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_y\"] = value",
        "    elseif entry.state then",
        "        entry.state.y = value",
        "    end",
        "end",
        "",
        "function prim.set_position(handle, x, y)",
        "    prim.set_x(handle, x)",
        "    prim.set_y(handle, y)",
        "end",
        "",
        "function prim.get_visible(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return false end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_visible\"] ~= false",
        "    end",
        "    return entry.state and entry.state.visible ~= false",
        "end",
        "",
        "function prim.set_visible(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_visible\"] = value and true or false",
        "    elseif entry.state then",
        "        entry.state.visible = value and true or false",
        "    end",
        "end",
        "",
        "function prim.set_interactable(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_interactable\"] = value and true or false",
        "    elseif entry.state then",
        "        entry.state.interactable = value and true or false",
        "    end",
        "end",
        "",
        "function prim.set_scale(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_scale\"] = value",
        "    elseif entry.state then",
        "        entry.state.scale = value",
        "    end",
        "end",
        "",
        "function prim.set_rotation(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_rotation\"] = value",
        "    elseif entry.state then",
        "        entry.state.rotation = value",
        "        entry.state.angle = value",
        "    end",
        "end",
        "",
        "function prim.set_opacity(handle, value)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"placed\" then",
        "        _G[entry.var .. \"_opacity\"] = value",
        "    elseif entry.state then",
        "        entry.state.opacity = value",
        "    end",
        "end",
        "",
        "function prim.get_rotation(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return 0 end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_rotation\"] or 0",
        "    end",
        "    if entry.state then",
        "        return entry.state.rotation or entry.state.angle or 0",
        "    end",
        "    return 0",
        "end",
        "",
        "function prim.get_vx(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return 0 end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_vx\"] or 0",
        "    end",
        "    return entry.state and entry.state.vx or 0",
        "end",
        "",
        "function prim.get_vy(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return 0 end",
        "    if entry.kind == \"placed\" then",
        "        return _G[entry.var .. \"_vy\"] or 0",
        "    end",
        "    return entry.state and entry.state.vy or 0",
        "end",
        "",
        "function prim.set_velocity(handle, vx, vy, set_x, set_y)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    local use_x = set_x ~= false",
        "    local use_y = set_y ~= false",
        "    if entry.kind == \"placed\" then",
        "        if use_x then _G[entry.var .. \"_vx\"] = vx or 0 end",
        "        if use_y then _G[entry.var .. \"_vy\"] = vy or 0 end",
        "    elseif entry.state then",
        "        if use_x then entry.state.vx = vx or 0 end",
        "        if use_y then entry.state.vy = vy or 0 end",
        "        if use_x or use_y then",
        "            entry.state.speed = nil",
        "            entry.state.angle = nil",
        "        end",
        "    end",
        "end",
        "",
        "function prim.add_velocity(handle, vx, vy, set_x, set_y)",
        "    prim.set_velocity(",
        "        handle,",
        "        prim.get_vx(handle) + (vx or 0),",
        "        prim.get_vy(handle) + (vy or 0),",
        "        set_x,",
        "        set_y",
        "    )",
        "end",
        "",
        "function prim.distance_points(ax, ay, bx, by)",
        "    local dx = (bx or 0) - (ax or 0)",
        "    local dy = (by or 0) - (ay or 0)",
        "    return math.sqrt(dx * dx + dy * dy)",
        "end",
        "",
        "function prim.angle_points(ax, ay, bx, by)",
        "    local dx = (bx or 0) - (ax or 0)",
        "    local dy = (by or 0) - (ay or 0)",
        "    return math.deg(math.atan2(dy, dx))",
        "end",
        "",
        "function prim.distance_handles(a, b)",
        "    return prim.distance_points(prim.get_x(a), prim.get_y(a), prim.get_x(b), prim.get_y(b))",
        "end",
        "",
        "function prim.angle_handles(a, b)",
        "    return prim.angle_points(prim.get_x(a), prim.get_y(a), prim.get_x(b), prim.get_y(b))",
        "end",
        "",
        "function prim.random_int(min_value, max_value)",
        "    local lo = math.floor(tonumber(min_value) or 0)",
        "    local hi = math.floor(tonumber(max_value) or lo)",
        "    if hi < lo then lo, hi = hi, lo end",
        "    return math.random(lo, hi)",
        "end",
        "",
        "function prim.random_float(min_value, max_value)",
        "    local lo = tonumber(min_value) or 0",
        "    local hi = tonumber(max_value) or lo",
        "    if hi < lo then lo, hi = hi, lo end",
        "    return lo + math.random() * (hi - lo)",
        "end",
        "",
        "function prim.list_objects(filter)",
        "    local out = {}",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            out[#out + 1] = handle",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.count_objects(filter)",
        "    local total = 0",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            total = total + 1",
        "        end",
        "    end",
        "    return total",
        "end",
        "",
        "function prim.find_object(filter)",
        "    local items = prim.list_objects(filter)",
        "    return items[1]",
        "end",
        "",
        "function prim.find_nearest(source_handle, filter)",
        "    local sx, sy = prim.get_x(source_handle), prim.get_y(source_handle)",
        "    if sx == nil or sy == nil then return nil end",
        "    filter = filter or {}",
        "    filter.exclude_handle = filter.exclude_handle or source_handle",
        "    local best_handle = nil",
        "    local best_dist = nil",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            local dist = prim.distance_points(sx, sy, prim.get_x(handle), prim.get_y(handle))",
        "            if dist and (best_dist == nil or dist < best_dist) then",
        "                best_handle = handle",
        "                best_dist = dist",
        "            end",
        "        end",
        "    end",
        "    return best_handle, best_dist",
        "end",
        "",
        "function prim.set_velocity_toward(handle, tx, ty, speed)",
        "    local sx, sy = prim.get_x(handle), prim.get_y(handle)",
        "    if sx == nil or sy == nil then return end",
        "    local dist = prim.distance_points(sx, sy, tx, ty)",
        "    if not dist or dist <= 0 then",
        "        prim.set_velocity(handle, 0, 0, true, true)",
        "        return",
        "    end",
        "    local vx = ((tx - sx) / dist) * (tonumber(speed) or 0)",
        "    local vy = ((ty - sy) / dist) * (tonumber(speed) or 0)",
        "    prim.set_velocity(handle, vx, vy, true, true)",
        "end",
        "",
        "function prim.set_velocity_polar(handle, angle_deg, speed)",
        "    local radians = (tonumber(angle_deg) or 0) * math.pi / 180",
        "    local mag = tonumber(speed) or 0",
        "    prim.set_velocity(handle, math.cos(radians) * mag, math.sin(radians) * mag, true, true)",
        "end",
        "",
        "function prim.spawn_object(def_id, options)",
        "    options = options or {}",
        "    local wanted = tostring(def_id or \"\")",
        "    local template = spawn_object_defs and spawn_object_defs[wanted] or nil",
        "    if not template then return nil end",
        "    local handle = tostring(options.handle or (\"spawn_\" .. tostring(os.clock()):gsub(\"%.\", \"\") .. \"_\" .. tostring(math.random(1000, 9999))))",
        "    local x = tonumber(options.x)",
        "    local y = tonumber(options.y)",
        "    local source_handle = options.source_handle and prim.handle_for_object(options.source_handle) or nil",
        "    local target_handle = options.target_handle and prim.handle_for_object(options.target_handle) or nil",
        "    local position_mode = tostring(options.position_mode or \"position\")",
        "    if position_mode == \"self\" and source_handle then",
        "        x = prim.get_x(source_handle)",
        "        y = prim.get_y(source_handle)",
        "    elseif position_mode == \"target\" and target_handle then",
        "        x = prim.get_x(target_handle)",
        "        y = prim.get_y(target_handle)",
        "    end",
        "    x = (tonumber(x) or 0) + (tonumber(options.offset_x) or 0)",
        "    y = (tonumber(y) or 0) + (tonumber(options.offset_y) or 0)",
        "    local state = {",
        "        def_id = wanted,",
        "        x = x,",
        "        y = y,",
        "        visible = options.visible ~= false,",
        "        scale = tonumber(options.scale) or 1.0,",
        "        rotation = tonumber(options.rotation) or 0.0,",
        "        opacity = tonumber(options.opacity) or 255,",
        "        spin_speed = tonumber(options.spin_speed) or 0.0,",
        "        interactable = options.interactable ~= false,",
        "        image = options.image or template.image or \"\",",
        "        vx = tonumber(options.vx) or 0,",
        "        vy = tonumber(options.vy) or 0,",
        "        speed = tonumber(options.speed) or 0,",
        "        angle = tonumber(options.angle) or tonumber(options.rotation) or 0,",
        "    }",
        "    _live_objects[handle] = state",
        "    prim.register_spawned(handle, wanted, state, options.tags or {})",
        "    return handle",
        "end",
        "",
        "function prim.radial_pattern(count, start_angle)",
        "    local total = math.max(1, math.floor(tonumber(count) or 1))",
        "    local base = tonumber(start_angle) or 0",
        "    local out = {}",
        "    for i = 0, total - 1 do",
        "        out[#out + 1] = base + (360 / total) * i",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.cone_pattern(count, center_angle, spread_angle)",
        "    local total = math.max(1, math.floor(tonumber(count) or 1))",
        "    local center = tonumber(center_angle) or 0",
        "    local spread = tonumber(spread_angle) or 0",
        "    local out = {}",
        "    if total == 1 then",
        "        out[1] = center",
        "        return out",
        "    end",
        "    local start_angle = center - spread * 0.5",
        "    local step = spread / (total - 1)",
        "    for i = 0, total - 1 do",
        "        out[#out + 1] = start_angle + step * i",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.spray_pattern(count, center_angle, spread_angle)",
        "    return prim.cone_pattern(count, center_angle, spread_angle)",
        "end",
        "",
        "function prim.update_motion()",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if entry then",
        "            local vx = prim.get_vx(handle)",
        "            local vy = prim.get_vy(handle)",
        "            if vx ~= 0 or vy ~= 0 then",
        "                prim.set_position(handle, (prim.get_x(handle) or 0) + vx, (prim.get_y(handle) or 0) + vy)",
        "            elseif entry.kind == \"spawned\" and entry.state and entry.state.speed and entry.state.speed > 0 then",
        "                local radians = (entry.state.angle or 0) * math.pi / 180",
        "                entry.state.x = (entry.state.x or 0) + math.sin(radians) * entry.state.speed",
        "                entry.state.y = (entry.state.y or 0) - math.cos(radians) * entry.state.speed",
        "            end",
        "        end",
        "    end",
        "end",
        "",
        "function prim.destroy_handle(handle)",
        "    local entry = prim.entry(handle)",
        "    if not entry then return end",
        "    if entry.kind == \"spawned\" then",
        "        if _live_objects then _live_objects[handle] = nil end",
        "        prim.unregister(handle)",
        "    else",
        "        prim.set_visible(handle, false)",
        "        prim.set_interactable(handle, false)",
        "        if entry.var and entry.var ~= \"\" then",
        "            if parents_destroy_children then parents_destroy_children(entry.var) end",
        "            if _parents then _parents[entry.var] = nil end",
        "            if path_followers then path_followers[entry.var] = nil end",
        "        end",
        "        prim.unregister(handle)",
        "    end",
        "end",
        "",
        "function prim.destroy_handles(handles)",
        "    for i = 1, #(handles or {}) do",
        "        prim.destroy_handle(handles[i])",
        "    end",
        "end",
        "",
        "function prim.destroy_filtered(filter)",
        "    prim.destroy_handles(prim.list_objects(filter))",
        "end",
        "",
        "function prim.query_in_radius(cx, cy, radius, filter)",
        "    local out = {}",
        "    local r = tonumber(radius) or 0",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            local dist = prim.distance_points(cx, cy, prim.get_x(handle), prim.get_y(handle))",
        "            if dist and dist <= r then",
        "                out[#out + 1] = handle",
        "            end",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.query_in_rect(x, y, w, h, filter)",
        "    local out = {}",
        "    local x2 = (tonumber(x) or 0) + (tonumber(w) or 0)",
        "    local y2 = (tonumber(y) or 0) + (tonumber(h) or 0)",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            local ox = prim.get_x(handle) or 0",
        "            local oy = prim.get_y(handle) or 0",
        "            if ox >= x and ox <= x2 and oy >= y and oy <= y2 then",
        "                out[#out + 1] = handle",
        "            end",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "local function _prim_dist_to_segment(px, py, x1, y1, x2, y2)",
        "    local dx = x2 - x1",
        "    local dy = y2 - y1",
        "    if dx == 0 and dy == 0 then return prim.distance_points(px, py, x1, y1) end",
        "    local t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)",
        "    if t < 0 then t = 0 elseif t > 1 then t = 1 end",
        "    local cx = x1 + t * dx",
        "    local cy = y1 + t * dy",
        "    return prim.distance_points(px, py, cx, cy)",
        "end",
        "",
        "function prim.query_in_line(x1, y1, x2, y2, width, filter)",
        "    local out = {}",
        "    local limit = tonumber(width) or 0",
        "    for handle, entry in pairs(runtime_objects) do",
        "        entry = _prim_cleanup_spawned(handle, entry)",
        "        if _prim_matches(handle, entry, filter) then",
        "            local dist = _prim_dist_to_segment(prim.get_x(handle) or 0, prim.get_y(handle) or 0, x1, y1, x2, y2)",
        "            if dist <= limit then",
        "                out[#out + 1] = handle",
        "            end",
        "        end",
        "    end",
        "    return out",
        "end",
        "",
        "function prim.any_in_radius(cx, cy, radius, filter)",
        "    return #prim.query_in_radius(cx, cy, radius, filter) > 0",
        "end",
        "",
        "function prim.any_in_rect(x, y, w, h, filter)",
        "    return #prim.query_in_rect(x, y, w, h, filter) > 0",
        "end",
        "",
        "function prim.any_in_line(x1, y1, x2, y2, width, filter)",
        "    return #prim.query_in_line(x1, y1, x2, y2, width, filter) > 0",
        "end",
        "",
        "function prim.world_to_grid_cell(grid_name, wx, wy)",
        "    local grid = _scene_grids and _scene_grids[tostring(grid_name or \"\")] or nil",
        "    if not grid then return nil, nil end",
        "    local col = math.floor(((tonumber(wx) or 0) - grid.ox) / grid.cw)",
        "    local row = math.floor(((tonumber(wy) or 0) - grid.oy) / grid.ch)",
        "    return col, row",
        "end",
        "",
        "function prim.grid_cell_to_world(grid_name, col, row)",
        "    local grid = _scene_grids and _scene_grids[tostring(grid_name or \"\")] or nil",
        "    if not grid then return nil, nil end",
        "    local c = tonumber(col) or 0",
        "    local r = tonumber(row) or 0",
        "    return grid.ox + c * grid.cw + math.floor(grid.cw / 2), grid.oy + r * grid.ch + math.floor(grid.ch / 2)",
        "end",
        "",
        "function prim.read_grid_cell(grid_name, col, row)",
        "    local grid = _scene_grids and _scene_grids[tostring(grid_name or \"\")] or nil",
        "    if not grid then return nil end",
        "    local c = tonumber(col) or 0",
        "    local r = tonumber(row) or 0",
        "    if c < 0 or c >= grid.cols or r < 0 or r >= grid.rows then return nil end",
        "    return grid.cells[r][c]",
        "end",
        "",
        "function prim.write_grid_cell(grid_name, col, row, value)",
        "    local grid = _scene_grids and _scene_grids[tostring(grid_name or \"\")] or nil",
        "    if not grid then return false end",
        "    local c = tonumber(col) or 0",
        "    local r = tonumber(row) or 0",
        "    if c < 0 or c >= grid.cols or r < 0 or r >= grid.rows then return false end",
        "    grid.cells[r][c] = value",
        "    return true",
        "end",
        "",
        "function prim.read_collision_cell(layer_id, col, row)",
        "    local grid = collision_grids and collision_grids[layer_id] or nil",
        "    if not grid then return nil end",
        "    return read_collision_cell(grid, col, row)",
        "end",
        "",
        "function prim.write_collision_cell(layer_id, col, row, value)",
        "    local grid = collision_grids and collision_grids[layer_id] or nil",
        "    if not grid then return false end",
        "    return write_collision_cell(grid, col, row, value)",
        "end",
        "",
        "function prim.toggle_collision_cell(layer_id, col, row)",
        "    local grid = collision_grids and collision_grids[layer_id] or nil",
        "    if not grid then return nil end",
        "    return toggle_collision_cell(grid, col, row)",
        "end",
        "",
        "function prim.collision_at(layer_id, wx, wy)",
        "    local grid = collision_grids and collision_grids[layer_id] or nil",
        "    if not grid then return false end",
        "    return check_collision(grid, tonumber(wx) or 0, tonumber(wy) or 0)",
        "end",
        "",
        "function prim.light_value_at(layer_id, wx, wy)",
        "    local grid = light_grids and light_grids[layer_id] or nil",
        "    if not grid then return 0 end",
        "    local col = math.floor((tonumber(wx) or 0) / grid.tile_size)",
        "    local row = math.floor((tonumber(wy) or 0) / grid.tile_size)",
        "    if col < 0 or col >= grid.map_width or row < 0 or row >= grid.map_height then return 0 end",
        "    local idx = row * grid.map_width + col + 1",
        "    return grid.cells[idx] or 0",
        "end",
        "",
        "function prim.sample_path_point(path_name, index)",
        "    local pts = scene_paths and scene_paths[tostring(path_name or \"\")] or nil",
        "    if not pts or #pts == 0 then return nil end",
        "    local idx = math.floor(tonumber(index) or 1)",
        "    if idx < 1 then idx = 1 end",
        "    if idx > #pts then idx = #pts end",
        "    return idx, pts[idx]",
        "end",
        "",
        "function prim.find_nearest_path_point(path_name, wx, wy)",
        "    local pts = scene_paths and scene_paths[tostring(path_name or \"\")] or nil",
        "    if not pts or #pts == 0 then return nil, nil end",
        "    local best_idx = nil",
        "    local best_dist = nil",
        "    for i = 1, #pts do",
        "        local dist = prim.distance_points(wx, wy, pts[i].x, pts[i].y)",
        "        if best_dist == nil or dist < best_dist then",
        "            best_dist = dist",
        "            best_idx = i",
        "        end",
        "    end",
        "    return best_idx, pts[best_idx]",
        "end",
    ]
    return "\n".join(lines)


def _make_path_lib() -> str:
    lines = [
        "-- lib/paths.lua",
        "-- Baked path data and runtime follower system.",
        "-- Path points are pre-sampled from bezier curves at export time.",
        "scene_paths = {}",
        "path_followers = {}",
        "",
        "function path_start(obj_var, path_name, speed, should_loop)",
        "    -- Guard: don't restart if already following this path",
        "    local existing = path_followers[obj_var]",
        "    if existing and existing.path == path_name then",
        "        return",
        "    end",
        "    path_followers[obj_var] = {",
        "        path   = path_name,",
        "        index  = 1,",
        "        speed  = speed,",
        "        accum  = 0,",
        "        loop   = should_loop,",
        "        paused = false,",
        "    }",
        "    local pts = scene_paths[path_name]",
        "    if pts and #pts > 0 then",
        "        _G[obj_var .. \"_x\"] = pts[1].x",
        "        _G[obj_var .. \"_y\"] = pts[1].y",
        "    end",
        "end",
        "",
        "function path_stop(obj_var)",
        "    if path_followers[obj_var] then",
        "        path_followers[obj_var].paused = true",
        "    end",
        "end",
        "",
        "function path_resume(obj_var)",
        "    if path_followers[obj_var] then",
        "        path_followers[obj_var].paused = false",
        "    end",
        "end",
        "",
        "function path_set_speed(obj_var, new_speed)",
        "    if path_followers[obj_var] then",
        "        path_followers[obj_var].speed = new_speed",
        "    end",
        "end",
        "",
        "function path_update()",
        "    for obj_var, pf in pairs(path_followers) do",
        "        if not pf.paused then",
        "            local pts = scene_paths[pf.path]",
        "            if pts then",
        "                pf.accum = pf.accum + pf.speed",
        "                while pf.accum >= 1 and pf.index <= #pts do",
        "                    pf.index = pf.index + 1",
        "                    pf.accum = pf.accum - 1",
        "                end",
        "                if pf.index > #pts then",
        "                    if pf.loop then",
        "                        pf.index = 1",
        "                        pf.accum = 0",
        "                    else",
        "                        emit_signal(\"path_complete_\" .. pf.path)",
        "                        path_followers[obj_var] = nil",
        "                    end",
        "                else",
        "                    _G[obj_var .. \"_x\"] = pts[pf.index].x",
        "                    _G[obj_var .. \"_y\"] = pts[pf.index].y",
        "                end",
        "            end",
        "        end",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _make_parent_lib() -> str:
    lines = [
        "-- lib/parents.lua",
        "-- Runtime parent/child transform system.",
        "-- _parents[child_var] = {parent_var, offset_x, offset_y, rotation_offset,",
        "--   inherit_position, inherit_rotation, inherit_scale, destroy_with_parent}",
        "_parents = {}",
        "",
        "function parents_update()",
        "    for child_var, rel in pairs(_parents) do",
        "        local px = _G[rel.parent_var .. \"_x\"]",
        "        local py = _G[rel.parent_var .. \"_y\"]",
        "        if px == nil or py == nil then",
        "            -- parent no longer exists; detach child",
        "            _parents[child_var] = nil",
        "        else",
        "            -- Read parent rotation (degrees). Used for both position and rotation inheritance.",
        "            local pr = _G[rel.parent_var .. \"_rotation\"] or 0",
        "            if rel.inherit_position then",
        "                -- Positions are stored as top-left, but sprites rotate around their center.",
        "                -- We must rotate the offset around the parent's visual center (top-left + pivot),",
        "                -- otherwise the child orbits the wrong point and swings out like an arm.",
        "                local _pcx  = px + rel.pivot_x",
        "                local _pcy  = py + rel.pivot_y",
        "                local _rad   = pr * math.pi / 180",
        "                local _cos_r = math.cos(_rad)",
        "                local _sin_r = math.sin(_rad)",
        "                local _wox = rel.offset_x * _cos_r - rel.offset_y * _sin_r",
        "                local _woy = rel.offset_x * _sin_r + rel.offset_y * _cos_r",
        "                -- Place child top-left so it too rotates around its own center correctly.",
        "                _G[child_var .. \"_x\"] = _pcx + _wox - rel.child_pivot_x",
        "                _G[child_var .. \"_y\"] = _pcy + _woy - rel.child_pivot_y",
        "            end",
        "            if rel.inherit_rotation then",
        "                _G[child_var .. \"_rotation\"] = pr + rel.rotation_offset",
        "            end",
        "            -- inherit_scale: stub",
        "            -- requires multiplying offset distance by parent scale; implement when needed",
        "        end",
        "    end",
        "end",
        "",
        "function parents_destroy_children(parent_var)",
        "    for child_var, rel in pairs(_parents) do",
        "        if rel.parent_var == parent_var then",
        "            if rel.destroy_with_parent then",
        "                _G[child_var .. \"_visible\"] = false",
        "                _G[child_var .. \"_interactable\"] = false",
        "                _parents[child_var] = nil",
        "                -- recursive: destroy this child's children too",
        "                parents_destroy_children(child_var)",
        "            else",
        "                -- detach but leave in place",
        "                _parents[child_var] = nil",
        "            end",
        "        end",
        "    end",
        "end",
    ]
    return "\n".join(lines)


def _bake_bezier_points(path_points: list[dict], closed: bool, interval: float = 2.0) -> list[dict]:
    """Sample a cubic bezier path into evenly-spaced {x, y} waypoints."""
    import math
    anchors = path_points
    if len(anchors) < 2:
        return [{"x": round(a["x"]), "y": round(a["y"])} for a in anchors]

    def _cubic(p0, c0, c1, p1, t):
        u = 1 - t
        return (u*u*u*p0 + 3*u*u*t*c0 + 3*u*t*t*c1 + t*t*t*p1)

    # Build segments
    segments = []
    n = len(anchors)
    count = n if closed else n - 1
    for i in range(count):
        a = anchors[i]
        b = anchors[(i + 1) % n]
        # out-handle of a, in-handle of b
        cx0 = a["x"] + a.get("cx2", 0)
        cy0 = a["y"] + a.get("cy2", 0)
        cx1 = b["x"] + b.get("cx1", 0)
        cy1 = b["y"] + b.get("cy1", 0)
        segments.append((a["x"], a["y"], cx0, cy0, cx1, cy1, b["x"], b["y"]))

    # Sample each segment
    baked = []
    for seg in segments:
        p0x, p0y, c0x, c0y, c1x, c1y, p1x, p1y = seg
        # Estimate length by sampling finely
        prev_x, prev_y = p0x, p0y
        length = 0
        for s in range(1, 101):
            t = s / 100.0
            sx = _cubic(p0x, c0x, c1x, p1x, t)
            sy = _cubic(p0y, c0y, c1y, p1y, t)
            length += math.sqrt((sx - prev_x)**2 + (sy - prev_y)**2)
            prev_x, prev_y = sx, sy
        # Number of baked points for this segment
        num = max(1, int(round(length / interval)))
        for j in range(num):
            t = j / num
            bx = _cubic(p0x, c0x, c1x, p1x, t)
            by = _cubic(p0y, c0y, c1y, p1y, t)
            baked.append({"x": round(bx), "y": round(by)})

    # Always include the final point
    last_anchor = anchors[0] if closed else anchors[-1]
    baked.append({"x": round(last_anchor["x"]), "y": round(last_anchor["y"])})
    return baked


# ─────────────────────────────────────────────────────────────
#  MAIN EXPORT ENTRY POINT
# ─────────────────────────────────────────────────────────────

def export_lpp(project: Project, title_id: str | None = None) -> dict[str, str]:
    files: dict[str, str] = {}
    tid = title_id or project.title_id
    registry = _plugin_registry(project)

    files["lib/controls.lua"] = _make_controls_lib(
        dpad_mirror_stick=project.game_data.dpad_mirror_stick,
        dpad_mirror_deadzone=project.game_data.dpad_mirror_deadzone,
    )
    files["lib/tween.lua"]    = _make_tween_lib()
    files["lib/camera.lua"]   = _make_camera_lib()
    files["lib/shake.lua"]    = _make_shake_lib()
    files["lib/flash.lua"]    = _make_flash_lib()
    files["lib/app_ui.lua"]   = _make_app_ui_lib()
    files["lib/groups.lua"]   = _make_group_lib()
    files["lib/primitives.lua"] = _make_primitives_lib()
    files["lib/paths.lua"]    = _make_path_lib()
    files["lib/parents.lua"]  = _make_parent_lib()
    plugin_libs = registry.collect_project_component_libs(project) if registry else {}
    for plugin_id, lua_lib in plugin_libs.items():
        files[f"lib/{plugin_id}.lua"] = lua_lib

    has_3d = any(getattr(s, "scene_type", "2d") == "3d" for s in project.scenes)

    # Detect SaveGame component anywhere in the project
    active_save_component = _find_active_savegame_component(project)
    has_save_system = active_save_component is not None

    if has_save_system:
        files["lib/save.lua"] = _make_save_lib_new(tid, project)
        save_scene_num = len(project.scenes) + 1
        files["scenes/save_scene.lua"] = _export_save_scene(project, save_scene_num, active_save_component)

    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        scene_key = f"scenes/scene_{scene_num:03d}.lua"
        _set_active_export_scene(project, scene)
        if getattr(scene, "scene_type", "2d") == "3d":
            files[scene_key] = _scene_3d_to_lua(scene, scene_num, project)
        else:
            files[scene_key] = _scene_to_lua(scene, scene_num, project)
    _set_active_export_scene(project, None)

    idx = []
    idx.append("-- =====================================================")
    idx.append(f"-- {project.title}")
    idx.append(f"-- Title ID : {tid}")
    idx.append(f"-- Author   : {project.author}")
    idx.append(f"-- Version  : {project.version}")
    idx.append("-- Generated by Vita Adventure Creator (LPP Export)")
    idx.append("-- =====================================================")
    idx.append("")
    idx.append("require('lib/tween')")
    idx.append("require('lib/camera')")
    idx.append("require('lib/shake')")
    idx.append("require('lib/flash')")
    idx.append("require('lib/app_ui')")
    idx.append("require('lib/controls')")
    idx.append("require('lib/groups')")
    idx.append("require('lib/primitives')")
    idx.append("require('lib/paths')")
    idx.append("require('lib/parents')")
    for plugin_id in sorted(plugin_libs):
        idx.append(f"require('lib/{plugin_id}')")
    if has_save_system:
        idx.append("require('lib/save')")
    if has_3d:
        idx.append("dofile('app0:/files/raycast3d.lua')")
        idx.append("System.setCpuSpeed(444)")
    idx.append("")
    idx.append("Sound.init()")
    idx.append("")
    idx.append(_make_ani_lib())
    idx.append("")
    idx.append(_make_pdoll_lib())
    idx.append("")
    idx.append("-- ─── ASSETS ─────────────────────────────────────────────")
    idx.append('deff = Font.load("app0:/assets/fonts/font.ttf")')
    idx.append("")

    if project.fonts:
        idx.append("fonts = {}")
        for fnt in project.fonts:
            if fnt.path:
                fname = _asset_filename(fnt.path)
                idx.append(f'fonts[{_lua_str(fname)}] = Font.load("app0:/assets/fonts/{fname}")')
        idx.append("")

    all_image_paths = _collect_all_image_paths(project)
    idx.append("images = {}")
    for path in all_image_paths:
        fname = _asset_filename(path)
        idx.append(f'images[{_lua_str(fname)}] = Graphics.loadImage("app0:/assets/images/{fname}")')
    idx.append("")
    idx.append("spawn_object_defs = {}")
    for od in project.object_defs:
        image_name = ""
        if od.frames and od.frames[0].image_id:
            img = project.get_image(od.frames[0].image_id)
            if img and img.path:
                image_name = _asset_filename(img.path)
        idx.append(
            f'spawn_object_defs[{_lua_str(od.id)}] = {{image={_lua_str(image_name)}, width={od.width}, height={od.height}}}'
        )
    idx.append("")

    if has_3d:
        idx.append("-- Texture key lookup for 3D map cells")
        idx.append("map_tex_keys = {}")
        for i, path in enumerate(_collect_3d_texture_paths(project)):
            fname = _asset_filename(path)
            idx.append(f'map_tex_keys[{i+1}] = {_lua_str(fname)}')
        idx.append("")

    has_tilelayers = any(
        comp.component_type == "TileLayer"
        for scene in project.scenes
        for comp in scene.components
    )
    if has_tilelayers:
        import math
        idx.append("-- ─── TILE CHUNKS ────────────────────────────────────────")
        idx.append("tile_chunks = {}")
        for scene in project.scenes:
            for comp in scene.components:
                if comp.component_type != "TileLayer":
                    continue
                ts_id = comp.config.get("tileset_id")
                if not ts_id:
                    continue
                ts = project.get_tileset(ts_id)
                if ts is None or ts.tile_size == 0:
                    continue
                map_w   = comp.config.get("map_width",  30)
                map_h   = comp.config.get("map_height", 17)
                world_w = map_w * ts.tile_size
                world_h = map_h * ts.tile_size
                chunks_x = math.ceil(world_w / CHUNK_SIZE)
                chunks_y = math.ceil(world_h / CHUNK_SIZE)
                safe_id  = comp.id.replace("-", "_")
                for cy in range(chunks_y):
                    for cx in range(chunks_x):
                        fname = f"tl_{safe_id}_{cx}_{cy}.png"
                        key   = f"tl_{safe_id}_{cx}_{cy}"
                        idx.append(
                            f'tile_chunks[{_lua_str(key)}] = '
                            f'Graphics.loadImage("app0:/assets/tilechunks/{fname}")'
                        )
        idx.append("")

    defs_with_collision = [
        od for od in project.object_defs
        if _object_has_collision_boxes(od)
    ]
    defs_with_solid_collision = [
        od for od in project.object_defs
        if getattr(od, "blocks_2d_movement", False)
    ]
    has_collision_layers = any(
        comp.component_type == "CollisionLayer"
        for scene in project.scenes
        for comp in scene.components
    )
    needs_collision_lib = has_collision_layers or bool(defs_with_collision) or bool(defs_with_solid_collision)
    if needs_collision_lib:
        idx.append("-- ─── COLLISION GRIDS ────────────────────────────────────")
        idx.append(_make_collision_lib())
        if has_collision_layers:
            for scene in project.scenes:
                for comp in scene.components:
                    if comp.component_type != "CollisionLayer":
                        continue
                    safe_id  = comp.id.replace("-", "_")
                    map_w    = comp.config.get("map_width",  30)
                    map_h    = comp.config.get("map_height", 17)
                    tile_sz  = comp.config.get("tile_size",  32)
                    tiles    = comp.config.get("tiles", [])
                    needed   = map_w * map_h
                    cells    = list(tiles[:needed])
                    while len(cells) < needed:
                        cells.append(0)
                    cells_str = ", ".join(str(c) for c in cells)
                    lname = comp.config.get("layer_name", "") or safe_id
                    idx.append(f'-- CollisionLayer: {lname}')
                    idx.append(f'collision_grids[{_lua_str(comp.id)}] = {{')
                    idx.append(f'    map_width  = {map_w},')
                    idx.append(f'    map_height = {map_h},')
                    idx.append(f'    tile_size  = {tile_sz},')
                    idx.append(f'    cells      = {{ {cells_str} }},')
                    idx.append(f'}}')
        for od in project.object_defs:
            idx.append(f'obj_collision_bounds[{_lua_str(od.id)}] = {{w={od.width}, h={od.height}}}')
        if defs_with_solid_collision:
            for od in defs_with_solid_collision:
                idx.append(f'solid_object_defs[{_lua_str(od.id)}] = true')
        if defs_with_collision:
            for od in defs_with_collision:
                idx.append(f'obj_collision[{_lua_str(od.id)}] = {{')
                if od.behavior_type == "Animation":
                    for slot_name, frames in _object_collision_slots(od).items():
                        idx.append(f'    [{_lua_str(slot_name)}] = {{')
                        for frame_boxes in frames:
                            if frame_boxes:
                                rects = ", ".join(
                                    f"{{x={cb.x},y={cb.y},w={cb.width},h={cb.height},role={_lua_str(getattr(cb, 'role', 'Physics'))}}}"
                                    for cb in frame_boxes
                                )
                                idx.append(f"        {{ {rects} }},")
                            else:
                                idx.append(f"        {{}},")
                        idx.append("    },")
                else:
                    for frame_boxes in od.collision_boxes:
                        if frame_boxes:
                            rects = ", ".join(
                                f"{{x={cb.x},y={cb.y},w={cb.width},h={cb.height},role={_lua_str(getattr(cb, 'role', 'Physics'))}}}"
                                for cb in frame_boxes
                            )
                            idx.append(f"    {{ {rects} }},")
                        else:
                            idx.append(f"    {{}},")
                idx.append("}")
        idx.append("")

    has_lightmap_layers = any(
        comp.component_type == "LightmapLayer"
        for scene in project.scenes
        for comp in scene.components
    )
    if has_lightmap_layers:
        idx.append("-- Lightmap grids")
        idx.append(_make_lightmap_lib())
        for scene in project.scenes:
            for comp in scene.components:
                if comp.component_type != "LightmapLayer":
                    continue
                safe_id  = comp.id.replace("-", "_")
                map_w    = comp.config.get("map_width", 30)
                map_h    = comp.config.get("map_height", 17)
                tile_sz  = comp.config.get("tile_size", 32)
                opacity  = max(0, min(255, int(comp.config.get("opacity", 255))))
                visible  = str(bool(comp.config.get("visible", True))).lower()
                cells    = comp.config.get("cells", [])
                needed   = map_w * map_h
                values   = [max(0, min(255, int(c or 0))) for c in list(cells[:needed])]
                while len(values) < needed:
                    values.append(0)
                cells_str = ", ".join(str(v) for v in values)
                color_hex = comp.config.get("blend_color", "#000000").lstrip("#")
                color_hex = (color_hex + "000000")[:6]
                cr, cg, cb = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
                lname = comp.config.get("layer_name", "") or safe_id
                idx.append(f'-- LightmapLayer: {lname}')
                idx.append(f'light_grids[{_lua_str(comp.id)}] = {{')
                idx.append(f'    map_width  = {map_w},')
                idx.append(f'    map_height = {map_h},')
                idx.append(f'    tile_size  = {tile_sz},')
                idx.append(f'    opacity    = {opacity},')
                idx.append(f'    visible    = {visible},')
                idx.append(f'    color_r    = {cr},')
                idx.append(f'    color_g    = {cg},')
                idx.append(f'    color_b    = {cb},')
                idx.append(f'    cells      = {{ {cells_str} }},')
                idx.append(f'}}')
        idx.append("")

    ani_files = list(set(
        slot.get("ani_file_id", "")
        for od in project.object_defs
        if od.behavior_type == "Animation"
        for slot in od.ani_slots
        if slot.get("ani_file_id", "")
    ))
    if ani_files:
        for ani_id in sorted(ani_files):
            ani_obj = project.get_animation_export(ani_id)
            if ani_obj:
                idx.append(f'ani_data[{_lua_str(ani_id)}] = {{')
                idx.append(f'    frame_count  = {ani_obj.frame_count},')
                idx.append(f'    frame_width  = {ani_obj.frame_width},')
                idx.append(f'    frame_height = {ani_obj.frame_height},')
                idx.append(f'    sheet_width  = {ani_obj.sheet_width},')
                idx.append(f'    sheet_height = {ani_obj.sheet_height},')
                idx.append(f'    frames_per_sheet = {ani_obj.frames_per_sheet},')
                idx.append(f'    fps          = {ani_obj.fps},')
                idx.append(f'}}')
                # Load sheets into a table (works for single or multi-sheet)
                paths = ani_obj.spritesheet_paths if ani_obj.spritesheet_paths else [ani_obj.spritesheet_path]
                idx.append(f'ani_sheets[{_lua_str(ani_id)}] = {{')
                for sp in paths:
                    sheet_name = _asset_filename(sp)
                    idx.append(f'    Graphics.loadImage("app0:/assets/animations/{sheet_name}"),')
                idx.append(f'}}')
        idx.append("")

    trans_files = list(set(
        comp.config.get("trans_file_id", "")
        for scene in project.scenes
        for comp in scene.components
        if comp.component_type == "Transition" and comp.config.get("trans_file_id", "")
    ))
    if trans_files:
        for trans_id in sorted(trans_files):
            trans_obj = project.get_transition_export(trans_id)
            if trans_obj:
                idx.append(f'trans_data[{_lua_str(trans_id)}] = {{')
                idx.append(f'    frame_count  = {trans_obj.frame_count},')
                idx.append(f'    frame_width  = 240,')
                idx.append(f'    frame_height = 136,')
                idx.append(f'    sheet_width  = {trans_obj.sheet_width},')
                idx.append(f'    sheet_height = {trans_obj.sheet_height},')
                idx.append(f'    fps          = {trans_obj.fps},')
                idx.append(f'}}')
                sheet_name = _asset_filename(trans_obj.spritesheet_path)
                idx.append(f'trans_sheets[{_lua_str(trans_id)}] = Graphics.loadImage("app0:/assets/animations/{sheet_name}")')
        idx.append("")

    # Paper doll definitions
    used_dolls = list(set(
        od.layer_anim_id
        for od in project.object_defs
        if od.behavior_type == "LayerAnimation" and od.layer_anim_id
    ))
    if used_dolls:
        for doll_id in sorted(used_dolls):
            doll = project.get_paper_doll(doll_id)
            if doll:
                idx.append(f'pdoll_defs[{_lua_str(doll.id)}] = {{')
                idx.append(f'    name = {_lua_str(doll.name)},')
                # Blink config
                idx.append(f'    blink = {{')
                idx.append(f'        layer_id     = {_lua_str(doll.blink.layer_id)},')
                alt_img = project.get_image(doll.blink.alt_image_id) if doll.blink.alt_image_id else None
                alt_fname = _lua_str(_asset_filename(alt_img.path)) if alt_img and alt_img.path else "nil"
                idx.append(f'        alt_image    = {alt_fname},')
                idx.append(f'        interval_min = {doll.blink.interval_min},')
                idx.append(f'        interval_max = {doll.blink.interval_max},')
                idx.append(f'        duration     = {doll.blink.blink_duration},')
                idx.append(f'        hook_mode    = {_lua_str(getattr(doll.blink, "node_hook_mode", "builtin"))},')
                idx.append(f'    }},')
                # Mouth config
                idx.append(f'    mouth = {{')
                idx.append(f'        layer_id    = {_lua_str(doll.mouth.layer_id)},')
                mouth_image_ids = doll.mouth.image_ids or ([doll.mouth.alt_image_id] if doll.mouth.alt_image_id else [])
                mouth_files = []
                for mouth_image_id in mouth_image_ids:
                    mouth_img = project.get_image(mouth_image_id)
                    if mouth_img and mouth_img.path:
                        mouth_files.append(_lua_str(_asset_filename(mouth_img.path)))
                mouth_images_lua = "{" + ", ".join(mouth_files) + "}" if mouth_files else "{}"
                idx.append(f'        images      = {mouth_images_lua},')
                idx.append(f'        cycle_speed = {doll.mouth.cycle_speed},')
                idx.append(f'        hook_mode   = {_lua_str(getattr(doll.mouth, "node_hook_mode", "builtin"))},')
                idx.append(f'    }},')
                # Idle breathing config
                idx.append(f'    idle = {{')
                idx.append(f'        layer_id        = {_lua_str(doll.idle_breathing.layer_id)},')
                idx.append(f'        scale_amount    = {doll.idle_breathing.scale_amount},')
                idx.append(f'        speed           = {doll.idle_breathing.speed},')
                idx.append(f'        affect_children = {_lua_bool(doll.idle_breathing.affect_children)},')
                idx.append(f'        hook_mode       = {_lua_str(getattr(doll.idle_breathing, "node_hook_mode", "builtin"))},')
                idx.append(f'    }},')
                # Layer tree
                idx.append(f'    layers = {{')
                _emit_pdoll_layers(idx, doll.root_layers, project, 2)
                idx.append(f'    }},')
                # Macros
                if doll.macros:
                    idx.append(f'    macros = {{')
                    for macro in doll.macros:
                        idx.append(f'        [{_lua_str(macro.name)}] = {{')
                        idx.append(f'            duration = {macro.duration},')
                        idx.append(f'            loop     = {_lua_bool(macro.loop)},')
                        idx.append(f'            keyframes = {{')
                        for kf in macro.keyframes:
                            idx.append(f'                {{ time={kf.time}, layer_id={_lua_str(kf.layer_id)}, x={kf.x}, y={kf.y}, rotation={kf.rotation}, scale={kf.scale} }},')
                        idx.append(f'            }},')
                        idx.append(f'        }},')
                    idx.append(f'    }},')
                idx.append(f'}}')
        idx.append("")

    all_audio_paths: set[str] = set()
    for aud in project.audio:
        if aud.path:
            all_audio_paths.add(aud.path)
    if all_audio_paths:
        idx.append("audio_tracks = {}")
        for path in sorted(all_audio_paths):
            fname = _asset_filename(path)
            idx.append(f'audio_tracks[{_lua_str(fname)}] = Sound.open("app0:/assets/audio/{fname}")')
        idx.append("")

    # ── Object collision box data ────────────────────────────────
    idx.append("-- ─── STATE ──────────────────────────────────────────────")
    idx.append("current_scene = 1")
    idx.append("current_music = nil")
    idx.append("running       = true")
    idx.append("_signals      = {}")
    idx.append("_live_objects = {}")
    if has_save_system:
        idx.append("_prev_scene        = 1")
        idx.append("_save_scene_leaving = false")
        idx.append("_save_just_loaded  = false")
        idx.append(f"_SAVE_SCENE_NUM = {save_scene_num}")
    idx.append("")
    idx.append("-- ─── INVENTORY ──────────────────────────────────────────")
    idx.append("inventory = {}")
    idx.append("function inventory_has(name)")
    idx.append("    for _, v in ipairs(inventory) do")
    idx.append("        if v == name then return true end")
    idx.append("    end")
    idx.append("    return false")
    idx.append("end")
    idx.append("function inventory_add(name)")
    idx.append("    if not inventory_has(name) then")
    idx.append("        inventory[#inventory + 1] = name")
    idx.append("    end")
    idx.append("end")
    idx.append("function inventory_remove(name)")
    idx.append("    for i, v in ipairs(inventory) do")
    idx.append("        if v == name then")
    idx.append("            table.remove(inventory, i)")
    idx.append("            return")
    idx.append("        end")
    idx.append("    end")
    idx.append("end")
    idx.append("")

    if project.game_data.variables:
        idx.append("-- ─── VARIABLES ─────────────────────────────────────────")
        for v in project.game_data.variables:
            if v.var_type == "string":
                default = _lua_str(str(v.default_value))
            elif v.var_type == "bool":
                default = _lua_bool(bool(v.default_value))
            else:
                default = str(v.default_value) if v.default_value else "0"
            idx.append(f"{_safe_name(v.name)} = {default}")
        idx.append("")

    idx.append("-- ─── SCENES ─────────────────────────────────────────────")
    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        idx.append(f"dofile('app0:/scenes/scene_{scene_num:03d}.lua')")
    if has_save_system:
        idx.append("dofile('app0:/scenes/save_scene.lua')")
    idx.append("")

    idx.append("-- ─── MAIN LOOP ──────────────────────────────────────────")
    idx.append("while running do")
    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        prefix    = "    if" if si == 0 else "    elseif"
        idx.append(f"{prefix} current_scene == {scene_num} then scene_{scene_num}()")
    if has_save_system:
        idx.append(f"    elseif current_scene == {save_scene_num} then scene_save_scene()")
    idx.append("    else")
    idx.append("        running = false")
    idx.append("    end")
    idx.append("end")
    idx.append("")
    idx.append("if current_music then Sound.close(current_music) end")
    idx.append("os.exit()")
    idx.append("")

    files["index.lua"] = "\n".join(idx)
    return files


# ─────────────────────────────────────────────────────────────
#  ASSET PATH MAPPING
# ─────────────────────────────────────────────────────────────

def get_asset_mapping(project: Project) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for img in project.images:
        if img.path:
            mapping[img.path] = f"assets/images/{_asset_filename(img.path)}"

    for aud in project.audio:
        if aud.path:
            mapping[aud.path] = f"assets/audio/{_asset_filename(aud.path)}"

    for fnt in project.fonts:
        if fnt.path:
            mapping[fnt.path] = f"assets/fonts/{_asset_filename(fnt.path)}"

    for od in project.object_defs:
        if od.behavior_type == "Animation":
            seen_ids = set()
            for slot in od.ani_slots:
                fid = slot.get("ani_file_id", "")
                if not fid or fid in seen_ids:
                    continue
                seen_ids.add(fid)
                ani_obj = project.get_animation_export(fid)
                if ani_obj:
                    paths = ani_obj.spritesheet_paths if ani_obj.spritesheet_paths else (
                        [ani_obj.spritesheet_path] if ani_obj.spritesheet_path else []
                    )
                    for sp in paths:
                        if sp:
                            if project.project_folder:
                                full_path = os.path.join(
                                    project.project_folder, "animations", sp
                                )
                            else:
                                full_path = sp
                            mapping[full_path] = f"assets/animations/{sp}"

    for trans in project.transition_exports:
        if trans.spritesheet_path:
            if project.project_folder:
                full_path = os.path.join(
                    project.project_folder, "animations", trans.spritesheet_path
                )
            else:
                full_path = trans.spritesheet_path
            mapping[full_path] = f"assets/animations/{trans.spritesheet_path}"

    return mapping

# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — LPP Exporter
Generates a multi-file Lua project using the LPP-Vita API.
"""

from __future__ import annotations
import os
from pathlib import Path
from models import Project, Scene, Behavior, BehaviorAction


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

def _asset_filename(path: str) -> str:
    return Path(path).name if path else ""

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

def _event_check(event: str) -> str:
    return {
        "pressed":  "controls_pressed",
        "released": "controls_released",
        "held":     "controls_held",
    }.get(event, "controls_pressed")

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

def _make_controls_lib() -> str:
    lines = [
        "-- lib/controls.lua",
        "local _pad_old = 0",
        "local _pad_cur = 0",
        "",
        "function controls_update()",
        "    _pad_old = _pad_cur",
        "    _pad_cur = Controls.read()",
        "end",
        "",
        "function controls_held(btn)",
        "    return Controls.check(_pad_cur, btn)",
        "end",
        "",
        "function controls_pressed(btn)",
        "    return Controls.check(_pad_cur, btn) and not Controls.check(_pad_old, btn)",
        "end",
        "",
        "function controls_released(btn)",
        "    return not Controls.check(_pad_cur, btn) and Controls.check(_pad_old, btn)",
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
        "function touch_update()",
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


def _make_save_lib(title_id: str) -> str:
    save_path = f"ux0:data/{title_id}_save.dat"
    lines = [
        "-- lib/save.lua",
        f'local SAVE_PATH = "{save_path}"',
        "",
        "function save_progress(scene_num)",
        '    local f = io.open(SAVE_PATH, "w")',
        "    if f then f:write(tostring(scene_num)); f:close() end",
        "end",
        "",
        "function load_progress()",
        '    local f = io.open(SAVE_PATH, "r")',
        '    if f then local val = tonumber(f:read("*n")); f:close(); return val end',
        "    return nil",
        "end",
        "",
        "function delete_save()",
        "    os.remove(SAVE_PATH)",
        "end",
        "",
        "function save_exists()",
        "    local f = io.open(SAVE_PATH, 'r')",
        "    if f then f:close(); return true end",
        "    return false",
        "end",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  INLINE ACTION → LUA
# ─────────────────────────────────────────────────────────────

def _resolve_target_name(target_id: str, project) -> str:
    if not target_id:
        return ""
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


def _resolve_layer_anim_target(layer_anim_id: str, project) -> str:
    """Resolve a PaperDollAsset id to the variable name of the object that uses it."""
    if not layer_anim_id or not project:
        return ""
    for od in project.object_defs:
        if od.behavior_type == "LayerAnimation" and od.layer_anim_id == layer_anim_id:
            return _safe_name(od.name)
    return ""


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
    t = action.action_type
    lines = []
    spd = action.movement_speed  # int, always present

    if t == "four_way_movement":
        lines.append(f"if controls_held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")

    elif t == "four_way_movement_collide":
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
        _has_cboxes = obj_def and any(boxes for boxes in obj_def.collision_boxes)
        if grid_id and obj_var:
            lines.append(f"do")
            lines.append(f"    local _grid = collision_grids[{_lua_str(grid_id)}]")
            lines.append(f"    if _grid then")
            if _has_cboxes:
                _cframe = f"{obj_var}_ani_frame" if obj_def.behavior_type == "Animation" else "0"
                _cid = _lua_str(obj_def.id)
                lines.append(f"        if controls_held(SCE_CTRL_LEFT) then")
                lines.append(f"            local _nx = {obj_var}_x - {spd}")
                lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cframe}) then {obj_var}_x = _nx end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_RIGHT) then")
                lines.append(f"            local _nx = {obj_var}_x + {spd}")
                lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cframe}) then {obj_var}_x = _nx end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_UP) then")
                lines.append(f"            local _ny = {obj_var}_y - {spd}")
                lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cframe}) then {obj_var}_y = _ny end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_DOWN) then")
                lines.append(f"            local _ny = {obj_var}_y + {spd}")
                lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cframe}) then {obj_var}_y = _ny end")
                lines.append(f"        end")
            else:
                lines.append(f"        if controls_held(SCE_CTRL_LEFT) then")
                lines.append(f"            local _nx = {obj_var}_x - {spd}")
                lines.append(f"            if not check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}) then {obj_var}_x = _nx end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_RIGHT) then")
                lines.append(f"            local _nx = {obj_var}_x + {spd}")
                lines.append(f"            if not check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}) then {obj_var}_x = _nx end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_UP) then")
                lines.append(f"            local _ny = {obj_var}_y - {spd}")
                lines.append(f"            if not check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}) then {obj_var}_y = _ny end")
                lines.append(f"        end")
                lines.append(f"        if controls_held(SCE_CTRL_DOWN) then")
                lines.append(f"            local _ny = {obj_var}_y + {spd}")
                lines.append(f"            if not check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}) then {obj_var}_y = _ny end")
                lines.append(f"        end")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            lines.append(f"if controls_held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
            lines.append(f"if controls_held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")
            lines.append(f"if controls_held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
            lines.append(f"if controls_held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")

    elif t == "two_way_movement":
        axis = action.two_way_axis
        if axis == "horizontal":
            lines.append(f"if controls_held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
            lines.append(f"if controls_held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")
        else:
            lines.append(f"if controls_held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
            lines.append(f"if controls_held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")

    elif t == "two_way_movement_collide":
        axis    = action.two_way_axis
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
        _has_cboxes = obj_def and any(boxes for boxes in obj_def.collision_boxes)
        if grid_id and obj_var:
            lines.append(f"do")
            lines.append(f"    local _grid = collision_grids[{_lua_str(grid_id)}]")
            lines.append(f"    if _grid then")
            if _has_cboxes:
                _cframe = f"{obj_var}_ani_frame" if obj_def.behavior_type == "Animation" else "0"
                _cid = _lua_str(obj_def.id)
                if axis == "horizontal":
                    lines.append(f"        if controls_held(SCE_CTRL_LEFT) then")
                    lines.append(f"            local _nx = {obj_var}_x - {spd}")
                    lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cframe}) then {obj_var}_x = _nx end")
                    lines.append(f"        end")
                    lines.append(f"        if controls_held(SCE_CTRL_RIGHT) then")
                    lines.append(f"            local _nx = {obj_var}_x + {spd}")
                    lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, _nx, {obj_var}_y, {_cframe}) then {obj_var}_x = _nx end")
                    lines.append(f"        end")
                else:
                    lines.append(f"        if controls_held(SCE_CTRL_UP) then")
                    lines.append(f"            local _ny = {obj_var}_y - {spd}")
                    lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cframe}) then {obj_var}_y = _ny end")
                    lines.append(f"        end")
                    lines.append(f"        if controls_held(SCE_CTRL_DOWN) then")
                    lines.append(f"            local _ny = {obj_var}_y + {spd}")
                    lines.append(f"            if not check_obj_vs_grid(_grid, {_cid}, {obj_var}_x, _ny, {_cframe}) then {obj_var}_y = _ny end")
                    lines.append(f"        end")
            else:
                if axis == "horizontal":
                    lines.append(f"        if controls_held(SCE_CTRL_LEFT) then")
                    lines.append(f"            local _nx = {obj_var}_x - {spd}")
                    lines.append(f"            if not check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}) then {obj_var}_x = _nx end")
                    lines.append(f"        end")
                    lines.append(f"        if controls_held(SCE_CTRL_RIGHT) then")
                    lines.append(f"            local _nx = {obj_var}_x + {spd}")
                    lines.append(f"            if not check_collision_rect(_grid, _nx, {obj_var}_y, {pw}, {ph}) then {obj_var}_x = _nx end")
                    lines.append(f"        end")
                else:
                    lines.append(f"        if controls_held(SCE_CTRL_UP) then")
                    lines.append(f"            local _ny = {obj_var}_y - {spd}")
                    lines.append(f"            if not check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}) then {obj_var}_y = _ny end")
                    lines.append(f"        end")
                    lines.append(f"        if controls_held(SCE_CTRL_DOWN) then")
                    lines.append(f"            local _ny = {obj_var}_y + {spd}")
                    lines.append(f"            if not check_collision_rect(_grid, {obj_var}_x, _ny, {pw}, {ph}) then {obj_var}_y = _ny end")
                    lines.append(f"        end")
            lines.append(f"    end")
            lines.append(f"end")
        else:
            if axis == "horizontal":
                lines.append(f"if controls_held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
                lines.append(f"if controls_held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")
            else:
                lines.append(f"if controls_held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
                lines.append(f"if controls_held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")

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

    elif t == "restart_scene":
        lines.append("advance = true  -- current_scene unchanged; main loop re-calls this scene")

    elif t == "emit_signal":
        sig = getattr(action, "signal_name", "") or action.var_name or ""
        if sig:
            lines.append(f"emit_signal({_lua_str(sig)})")
        else:
            lines.append("-- emit_signal: no signal name set")

    elif t == "go_to_next":
        lines.append("current_scene = current_scene + 1")
        lines.append("advance = true")

    elif t == "go_to_prev":
        lines.append("current_scene = current_scene - 1")
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
        for sa in action.sub_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_button_held":
        btn = _button_constant(action.button)
        lines.append(f"if controls_held({btn}) then")
        for sa in action.sub_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        lines.append("end")

    elif t == "if_button_released":
        btn = _button_constant(action.button)
        lines.append(f"if controls_released({btn}) then")
        for sa in action.sub_actions:
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
            lines.append(f"{target}_ani_playing = true")
            lines.append(f"{target}_ani_done = false")

    elif t == "ani_pause":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_ani_playing = false")

    elif t == "ani_stop":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_ani_playing = false")
            lines.append(f"{target}_ani_frame = 0")
            lines.append(f"{target}_ani_done = false")

    elif t == "ani_set_frame":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        frame  = action.frame_index
        if target:
            lines.append(f"{target}_ani_frame = {frame}")

    elif t == "ani_set_speed":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        fps    = action.ani_fps
        if target:
            lines.append(f"{target}_ani_fps = {fps}")

    elif t == "set_anim_speed":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        fps    = action.anim_fps
        if target:
            lines.append(f"{target}_ani_fps = {fps}")

    elif t == "play_anim":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_ani_playing = true")
            lines.append(f"{target}_ani_done = false")

    elif t == "stop_anim":
        target = _resolve_target_name(action.object_def_id, project) if (project and action.object_def_id) else obj_var
        if target:
            lines.append(f"{target}_ani_playing = false")

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
                    x_expr = f"{obj_var}_x + {off_x}" if off_x else f"{obj_var}_x"
                    y_expr = f"{obj_var}_y + {off_y}" if off_y else f"{obj_var}_y"
                else:
                    x_expr = str(tx + off_x) if off_x else str(tx)
                    y_expr = str(ty + off_y) if off_y else str(ty)
                lines.append(f"do")
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
                lines.append(f"    }}")
                lines.append(f"end")
            else:
                lines.append(f"-- create_object: def {_lua_str(def_id)} not found")
        else:
            lines.append("-- create_object: no object_def_id specified")

    elif t == "destroy_object":
        def_id  = action.object_def_id or ""
        inst_id = action.instance_id or ""
        if inst_id:
            lines.append(f"_live_objects[{_lua_str(inst_id)}] = nil")
        elif def_id and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f"{vname}_visible = false")
                lines.append(f"{vname}_interactable = false")
            else:
                lines.append(f"-- destroy_object: def {_lua_str(def_id)} not found")
        else:
            lines.append("-- destroy_object: no target specified")

    elif t == "destroy_all_type":
        def_id = action.object_def_id or ""
        if def_id and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f"{vname}_visible = false")
                lines.append(f"{vname}_interactable = false")
            else:
                lines.append(f"-- destroy_all_type: def {_lua_str(def_id)} not found")
        else:
            lines.append("-- destroy_all_type: no object_def_id specified")

    elif t == "enable_interact" and obj_var:
        lines.append(f"{obj_var}_interactable = true")

    elif t == "disable_interact" and obj_var:
        lines.append(f"{obj_var}_interactable = false")

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

    elif t == "if_save_exists":
        lines.append("if save_exists() then")
        for sa in action.true_actions:
            for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                lines.append(f"    {sl}")
        if action.false_actions:
            lines.append("else")
            for sa in action.false_actions:
                for sl in _action_to_lua_inline(sa, obj_var, project, obj_def=obj_def):
                    lines.append(f"    {sl}")
        lines.append("end")

    elif t == "set_label_text":
        def_id = action.object_def_id or ""
        tgt = _resolve_target_name(def_id, project) if (project and def_id) else _safe_name(def_id)
        new_text = action.dialogue_text or ""
        if tgt:
            lines.append(f"{tgt}_text = {_lua_str(new_text)}")
        else:
            lines.append("-- set_label_text: no label object specified")

    elif t == "set_label_text_var":
        def_id = action.object_def_id or ""
        tgt = _resolve_target_name(def_id, project) if (project and def_id) else _safe_name(def_id)
        vn = _safe_name(action.var_name or "")
        if tgt and vn:
            lines.append(f'{tgt}_text = tostring({vn} or "")')
        else:
            lines.append("-- set_label_text_var: missing label or variable name")

    elif t == "set_label_color":
        def_id = action.object_def_id or ""
        tgt = _resolve_target_name(def_id, project) if (project and def_id) else _safe_name(def_id)
        hx = (action.color or "#ffffff").lstrip('#')
        try:
            cr, cg, cb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except (ValueError, IndexError):
            cr, cg, cb = 255, 255, 255
        if tgt:
            lines.append(f"{tgt}_text_r = {cr}")
            lines.append(f"{tgt}_text_g = {cg}")
            lines.append(f"{tgt}_text_b = {cb}")
        else:
            lines.append("-- set_label_color: no label object specified")

    elif t == "set_label_size":
        def_id = action.object_def_id or ""
        tgt = _resolve_target_name(def_id, project) if (project and def_id) else _safe_name(def_id)
        size = action.frame_index
        if tgt:
            lines.append(f"{tgt}_font_size = {size}")
        else:
            lines.append("-- set_label_size: no label object specified")

    elif t == "log_message":
        lines.append(f"-- LOG: {action.log_message}")

    elif t == "add_to_group":
        def_id = action.object_def_id or ""
        gname  = action.group_name or ""
        if def_id and gname and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'group_add({_lua_str(gname)}, {_lua_str(vname)})')
            else:
                lines.append(f"-- add_to_group: object def {_lua_str(def_id)} not found")
        else:
            lines.append("-- add_to_group: missing object or group name")

    elif t == "remove_from_group":
        def_id = action.object_def_id or ""
        gname  = action.group_name or ""
        if def_id and gname and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'group_remove({_lua_str(gname)}, {_lua_str(vname)})')
            else:
                lines.append(f"-- remove_from_group: object def {_lua_str(def_id)} not found")
        else:
            lines.append("-- remove_from_group: missing object or group name")

    elif t == "call_action_on_group":
        gname    = action.group_name or ""
        sub_type = action.group_action_type or ""
        if gname and sub_type:
            # Emit a loop over _groups[gname].  _gv holds the string variable name
            # of each member (e.g. "guard").  We use _G[_gv .. "_field"] to reach
            # their runtime state — do NOT recurse into _action_to_lua_inline here
            # because obj_var is a literal prefix, not a runtime string.
            lines.append(f"do")
            lines.append(f"    local _g = _groups[{_lua_str(gname)}]")
            lines.append(f"    if _g then")
            lines.append(f"        for _gi = 1, #_g do")
            lines.append(f"            local _gv = _g[_gi]")
            if sub_type == "show_object":
                lines.append(f'            _G[_gv .. "_visible"] = true')
            elif sub_type == "hide_object":
                lines.append(f'            _G[_gv .. "_visible"] = false')
            elif sub_type == "destroy_object":
                lines.append(f'            _G[_gv .. "_visible"] = false')
                lines.append(f'            _G[_gv .. "_interactable"] = false')
            elif sub_type == "enable_interact":
                lines.append(f'            _G[_gv .. "_interactable"] = true')
            elif sub_type == "disable_interact":
                lines.append(f'            _G[_gv .. "_interactable"] = false')
            elif sub_type == "set_opacity":
                val = int(float(action.target_opacity) * 255)
                lines.append(f'            _G[_gv .. "_opacity"] = {val}')
            elif sub_type == "set_scale":
                lines.append(f'            _G[_gv .. "_scale"] = {action.target_scale}')
            elif sub_type == "set_rotation":
                lines.append(f'            _G[_gv .. "_rotation"] = {action.target_rotation}')
            elif sub_type == "move_to":
                lines.append(f'            _G[_gv .. "_x"] = {action.target_x}')
                lines.append(f'            _G[_gv .. "_y"] = {action.target_y}')
            elif sub_type == "move_by":
                lines.append(f'            _G[_gv .. "_x"] = (_G[_gv .. "_x"] or 0) + {action.offset_x}')
                lines.append(f'            _G[_gv .. "_y"] = (_G[_gv .. "_y"] or 0) + {action.offset_y}')
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
            if od:
                vname = _safe_name(od.name)
                lines.append(f"if group_has({_lua_str(gname)}, {_lua_str(vname)}) then")
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

    elif t == "cancel_all":
        def_id = action.object_def_id or ""
        if def_id and project:
            tgt = _resolve_target_name(def_id, project)
        elif obj_var:
            tgt = obj_var
        else:
            tgt = ""
        if tgt:
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
        if def_id and pname and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'path_start("{vname}", "{pname}", {speed}, {loop})')
            else:
                lines.append(f"-- follow_path: object def not found")
        else:
            lines.append("-- follow_path: missing object or path name")

    elif t == "stop_path":
        def_id = action.object_def_id or ""
        if def_id and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'path_stop("{vname}")')
            else:
                lines.append("-- stop_path: object def not found")
        else:
            lines.append("-- stop_path: missing object")

    elif t == "resume_path":
        def_id = action.object_def_id or ""
        if def_id and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'path_resume("{vname}")')
            else:
                lines.append("-- resume_path: object def not found")
        else:
            lines.append("-- resume_path: missing object")

    elif t == "set_path_speed":
        def_id = action.object_def_id or ""
        speed  = getattr(action, "path_speed", 1.0) or 1.0
        if def_id and project:
            od = project.get_object_def(def_id)
            if od:
                vname = _safe_name(od.name)
                lines.append(f'path_set_speed("{vname}", {speed})')
            else:
                lines.append("-- set_path_speed: object def not found")
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
        if target:
            lines.append(f"{target}_ani_frame = {frame}")
        else:
            lines.append("-- set_frame: no target specified")

    elif t == "pause_music":
        lines.append("if current_music then Sound.pause(current_music) end")

    elif t == "resume_music":
        lines.append("if current_music then Sound.resume(current_music) end")

    elif t == "stop_all_sounds":
        lines.append("if current_music then Sound.close(current_music) end")
        lines.append("current_music = nil")

    elif t == "save_game":
        lines.append("save_progress(current_scene)")

    elif t == "load_game":
        lines.append("do")
        lines.append("    local _saved = load_progress()")
        lines.append(f"    if _saved then")
        lines.append(f"        current_scene = _saved")
        lines.append(f"        advance = true")
        lines.append(f"    end")
        lines.append("end")

    elif t == "delete_save":
        lines.append("delete_save()")

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

    # ── Grid actions ─────────────────────────────────────────

    elif t == "grid_place_at":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        cv = action.grid_col_var.strip()
        rv = action.grid_row_var.strip()
        col_expr = _safe_name(cv) if cv else str(action.grid_col)
        row_expr = _safe_name(rv) if rv else str(action.grid_row)
        if target:
            lines.append("do")
            lines.append(f'    local _g = _scene_grids["{gname}"]')
            lines.append(f"    if _g then")
            lines.append(f"        local _c = {col_expr}")
            lines.append(f"        local _r = {row_expr}")
            lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
            lines.append(f"            _g.cells[_r][_c] = {_lua_str(target)}")
            lines.append(f"            {target}_x = _g.ox + _c * _g.cw + math.floor(_g.cw / 2)")
            lines.append(f"            {target}_y = _g.oy + _r * _g.ch + math.floor(_g.ch / 2)")
            lines.append(f"        end")
            lines.append(f"    end")
            lines.append("end")
        else:
            lines.append("-- grid_place_at: no target object")

    elif t == "grid_snap_to":
        gname  = _safe_name(action.grid_name) if action.grid_name else "grid1"
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        if target:
            lines.append("do")
            lines.append(f'    local _g = _scene_grids["{gname}"]')
            lines.append(f"    if _g then")
            lines.append(f"        local _c = math.floor(({target}_x - _g.ox) / _g.cw)")
            lines.append(f"        local _r = math.floor(({target}_y - _g.oy) / _g.ch)")
            lines.append(f"        if _c >= 0 and _c < _g.cols and _r >= 0 and _r < _g.rows then")
            lines.append(f"            _g.cells[_r][_c] = {_lua_str(target)}")
            lines.append(f"            {target}_x = _g.ox + _c * _g.cw + math.floor(_g.cw / 2)")
            lines.append(f"            {target}_y = _g.oy + _r * _g.ch + math.floor(_g.ch / 2)")
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
        def_id = action.object_def_id or ""
        target = _resolve_target_name(def_id, project) if (project and def_id) else obj_var
        direction = action.grid_direction or "right"
        dist = action.grid_distance or 1
        dc, dr = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(direction, (1, 0))
        if target:
            lines.append("do")
            lines.append(f'    local _g = _scene_grids["{gname}"]')
            lines.append(f"    if _g then")
            lines.append(f"        local _fc, _fr = nil, nil")
            lines.append(f"        for _r=0, _g.rows-1 do")
            lines.append(f"            for _c=0, _g.cols-1 do")
            lines.append(f'                if _g.cells[_r][_c] == {_lua_str(target)} then _fc = _c; _fr = _r end')
            lines.append(f"            end")
            lines.append(f"        end")
            lines.append(f"        if _fc then")
            lines.append(f"            local _nc = _fc + {dc * dist}")
            lines.append(f"            local _nr = _fr + {dr * dist}")
            lines.append(f"            if _nc >= 0 and _nc < _g.cols and _nr >= 0 and _nr < _g.rows and _g.cells[_nr][_nc] == nil then")
            lines.append(f"                _g.cells[_fr][_fc] = nil")
            lines.append(f"                _g.cells[_nr][_nc] = {_lua_str(target)}")
            lines.append(f"                {target}_x = _g.ox + _nc * _g.cw + math.floor(_g.cw / 2)")
            lines.append(f"                {target}_y = _g.oy + _nr * _g.ch + math.floor(_g.ch / 2)")
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
        lines.append(f"                _G[_g.cells[_r1][_c1] .. '_x'] = _g.ox + _c1 * _g.cw + math.floor(_g.cw / 2)")
        lines.append(f"                _G[_g.cells[_r1][_c1] .. '_y'] = _g.oy + _r1 * _g.ch + math.floor(_g.ch / 2)")
        lines.append(f"            end")
        lines.append(f"            if _g.cells[_r2][_c2] then")
        lines.append(f"                _G[_g.cells[_r2][_c2] .. '_x'] = _g.ox + _c2 * _g.cw + math.floor(_g.cw / 2)")
        lines.append(f"                _G[_g.cells[_r2][_c2] .. '_y'] = _g.oy + _r2 * _g.ch + math.floor(_g.ch / 2)")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("end")

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
        "local function ani_get_frame_rect(ani_id, frame)",
        "    local data = ani_data[ani_id]",
        "    if not data then return 0, 0, 64, 64 end",
        "    local cols = math.floor(data.sheet_width / data.frame_width)",
        "    if cols < 1 then cols = 1 end",
        "    local col = frame % cols",
        "    local row = math.floor(frame / cols)",
        "    return col * data.frame_width, row * data.frame_height,",
        "           data.frame_width, data.frame_height",
        "end",
        "",
        "function ani_draw(ani_id, frame, x, y)",
        "    local sheet = ani_sheets[ani_id]",
        "    if not sheet then return end",
        "    local sx, sy, sw, sh = ani_get_frame_rect(ani_id, frame)",
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
        "        -- idle state",
        "        idle_time     = 0,",
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
        "",
        "    -- Blink",
        "    if p.blink_enabled and def.blink and def.blink.layer_id ~= '' then",
        "        local bl = pdoll_find_layer(p.layers, def.blink.layer_id)",
        "        if bl then",
        "            if p.blink_active then",
        "                p.blink_dur = p.blink_dur + dt",
        "                if p.blink_dur >= def.blink.duration then",
        "                    bl.image = bl.base_image",
        "                    p.blink_active = false",
        "                    p.blink_timer  = 0",
        "                    p.blink_next   = def.blink.interval_min + math.random() * (def.blink.interval_max - def.blink.interval_min)",
        "                end",
        "            else",
        "                p.blink_timer = p.blink_timer + dt",
        "                if p.blink_timer >= p.blink_next then",
        "                    if def.blink.alt_image and images[def.blink.alt_image] then",
        "                        bl.image = def.blink.alt_image",
        "                    end",
        "                    p.blink_active = true",
        "                    p.blink_dur    = 0",
        "                end",
        "            end",
        "        end",
        "    end",
        "",
        "    -- Talk (mouth cycle)",
        "    if p.talk_enabled and p.talk_active and def.mouth and def.mouth.layer_id ~= '' then",
        "        local ml = pdoll_find_layer(p.layers, def.mouth.layer_id)",
        "        if ml then",
        "            p.talk_cycle = p.talk_cycle + dt",
        "            if p.talk_cycle >= def.mouth.cycle_speed then",
        "                p.talk_cycle = 0",
        "                p.talk_open = not p.talk_open",
        "                if p.talk_open and def.mouth.alt_image and images[def.mouth.alt_image] then",
        "                    ml.image = def.mouth.alt_image",
        "                else",
        "                    ml.image = ml.base_image",
        "                end",
        "            end",
        "            -- decrement talk_for timer",
        "            if p.talk_timer > 0 then",
        "                p.talk_timer = p.talk_timer - dt",
        "                if p.talk_timer <= 0 then",
        "                    p.talk_timer  = 0",
        "                    p.talk_active = false",
        "                    p.talk_open   = false",
        "                    ml.image = ml.base_image",
        "                end",
        "            end",
        "        end",
        "    end",
        "",
        "    -- Idle breathing (sine wave scale pulse)",
        "    if p.idle_enabled and def.idle and def.idle.layer_id ~= '' then",
        "        p.idle_time = p.idle_time + dt",
        "        local phase   = (p.idle_time / def.idle.speed) * math.pi * 2",
        "        local ds      = math.sin(phase) * def.idle.scale_amount",
        "        local il      = pdoll_find_layer(p.layers, def.idle.layer_id)",
        "        if il then",
        "            il.dscale = ds",
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
    if camera_obj:
        if camera_placed:
            out.append(f"    camera.x = {camera_placed.x}")
            out.append(f"    camera.y = {camera_placed.y}")
        else:
            for po in scene.placed_objects:
                od = project.get_object_def(po.object_def_id)
                if od:
                    for beh in list(od.behaviors) + list(po.instance_behaviors):
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
            vname = _safe_name(od.name)
            opacity_255 = int(round(po.opacity * 255))
            out.append(f"    {vname}_x          = {po.x}")
            out.append(f"    {vname}_y          = {po.y}")
            out.append(f"    {vname}_visible    = {_lua_bool(po.visible)}")
            is_sprite = od.behavior_type not in ("GUI_Panel", "GUI_Label", "GUI_Button")
            if is_sprite:
                out.append(f"    {vname}_start_x   = {po.x}")
                out.append(f"    {vname}_start_y   = {po.y}")
                out.append(f"    {vname}_scale     = {po.scale}")
                out.append(f"    {vname}_rotation  = {po.rotation}")
                out.append(f"    {vname}_opacity   = {opacity_255}")
                out.append(f"    {vname}_spin_speed = 0.0")
                out.append(f"    {vname}_interactable = true")
            if od.behavior_type == "GUI_Label":
                out.append(f'    {vname}_text = {_lua_str(od.gui_text)}')
                hx = od.gui_text_color.lstrip('#')
                lr, lg, lb = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
                out.append(f'    {vname}_text_r = {lr}')
                out.append(f'    {vname}_text_g = {lg}')
                out.append(f'    {vname}_text_b = {lb}')
                out.append(f'    {vname}_font_size = {od.gui_font_size}')
            if od.behavior_type == "Animation" and od.ani_file_id:
                ani_playing = "true" if od.ani_play_on_spawn and not od.ani_start_paused else "false"
                start_frame = od.ani_pause_frame if od.ani_start_paused else 0
                out.append(f"    {vname}_ani_id      = {_lua_str(od.ani_file_id)}")
                out.append(f"    {vname}_ani_frame   = {start_frame}")
                out.append(f"    {vname}_ani_playing = {ani_playing}")
                out.append(f"    {vname}_ani_timer   = 0")
                out.append(f"    {vname}_ani_loop    = {_lua_bool(od.ani_loop)}")
                out.append(f"    {vname}_ani_fps     = {od.ani_fps_override}")
                out.append(f"    {vname}_ani_done    = false")

            if od.behavior_type == "LayerAnimation" and od.layer_anim_id:
                doll = project.get_paper_doll(od.layer_anim_id)
                if doll:
                    out.append(f"    {vname}_pdoll = pdoll_create({_lua_str(doll.id)})")
                    out.append(f"    {vname}_pdoll.blink_enabled = {_lua_bool(od.layer_anim_blink)}")
                    out.append(f"    {vname}_pdoll.talk_enabled  = {_lua_bool(od.layer_anim_talk)}")
                    out.append(f"    {vname}_pdoll.idle_enabled  = {_lua_bool(od.layer_anim_idle)}")

    # Initialise gravity velocity for objects that opt in
    gravity_comp = scene.get_component("Gravity")
    if gravity_comp:
        _gdir = gravity_comp.config.get("gravity_direction", "down")
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and getattr(od, "affected_by_gravity", False) and od.behavior_type != "Camera":
                vname = _safe_name(od.name)
                if _gdir in ("down", "up"):
                    out.append(f"    {vname}_vy = 0")
                else:
                    out.append(f"    {vname}_vx = 0")

    # Initialise _groups from design-time group membership for objects placed in this scene.
    # Groups are rebuilt fresh each scene load — scene-scoped at runtime, global in the editor.
    group_map: dict[str, list[str]] = {}
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.groups:
            vname = _safe_name(od.name)
            for gname in od.groups:
                gname = gname.strip()
                if gname:
                    group_map.setdefault(gname, [])
                    if vname not in group_map[gname]:
                        group_map[gname].append(vname)
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

    # Initialise on_timer and on_timer_variable counters, and
    # on_variable_threshold state for all behaviors in the scene.
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od or od.behavior_type == "Camera":
            continue
        vname = _safe_name(od.name)
        all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
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

    zone_objects = []
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if not od:
            continue
        all_behs = list(od.behaviors) + list(po.instance_behaviors)
        if any(b.trigger in ZONE_TRIGGERS for b in all_behs):
            zone_objects.append(po)
    if zone_objects:
        out.append("    local _zone_prev = {}")
        for zpo in zone_objects:
            out.append(f"    _zone_prev[{_lua_str(zpo.instance_id)}] = false")

    scene_layers = sorted(
        [c for c in scene.components if c.component_type == "Layer"],
        key=lambda c: c.config.get("layer", 0)
    )
    for lc in scene_layers:
        lname = _safe_name(lc.config.get("layer_name", "") or lc.id)
        visible_init = "true" if lc.config.get("visible", True) else "false"
        out.append(f"    layer_{lname}_visible = {visible_init}")

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
        if project.game_data.save_enabled:
            out.append("            delete_save()")
        out.append(f"            current_scene = {scene_num + 1}")
        out.append("            chosen = true")
        out.append("        elseif controls_released(SCE_CTRL_TRIANGLE) then")
        if project.game_data.save_enabled:
            out.append("            local saved = load_progress()")
            out.append(f"            if saved and saved >= 1 and saved <= {len(project.scenes)} then")
            out.append("                current_scene = saved")
            out.append("            else")
            out.append(f"                current_scene = {scene_num + 1}")
            out.append("            end")
        else:
            out.append(f"            current_scene = {scene_num + 1}")
        out.append("            chosen = true")
        out.append("        end")
        out.append("    end")

    elif scene.role == "end":
        if project.game_data.save_enabled:
            out.append("    delete_save()")
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

        out.append("    local advance = false")
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
            if cfg_vn.get("auto_advance", False):
                out.append("    local auto_advance_timer = 0")

        # ── on_scene_start / on_create  (run once before main loop) ──────────
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _safe_name(od.name)
            all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
            for bi, beh in enumerate(all_behaviors):
                if beh.trigger in ("on_scene_start", "on_create"):
                    out.append(f"    -- {beh.trigger} [{od.name}]")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"    {line}")

        # ── Wait / fade state ───────────────────────────────────────────────
        out.append("    local _scene_timer = Timer.new()")
        out.append("    Timer.reset(_scene_timer)")
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname = _safe_name(od.name)
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
        out.append("        tween_update()")
        out.append("        path_update()")
        out.append("        shake_update()")
        out.append("        flash_update()")

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
            out.append("                for _i = 1, #_cp.lines do _total = _total + string.len(_cp.lines[_i]) end")
            out.append("                _vn_char_idx = _vn_char_idx + _cp.tw_speed * _dt")
            out.append("                if _vn_char_idx >= _total then")
            out.append("                    _vn_char_idx = _total")
            out.append("                    _vn_tw_done = true")
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

        # ── Per-frame behavior dispatch ─────────────────────────────────────
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _safe_name(od.name)
            all_behaviors = list(od.behaviors) + list(po.instance_behaviors)

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
                    btn = _button_constant(beh.button)
                    out.append(f"            if controls_pressed({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_button_held" and beh.button:
                    btn = _button_constant(beh.button)
                    out.append(f"            if controls_held({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project, obj_def=od):
                            out.append(f"                {line}")
                    out.append(f"            end")

                elif beh.trigger == "on_button_released" and beh.button:
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

                elif beh.trigger == "on_touch_tap":
                    if od.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                        tw = od.gui_width
                        th = od.gui_height
                    else:
                        tw = int(od.width * po.scale)
                        th = int(od.height * po.scale)
                    out.append(f"            if {vname}_visible and touch_in_rect({vname}_x, {vname}_y, {tw}, {th}) then")
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

            out.append(f"        end  -- wait guard [{od.name}]")

        out.append("        camera_update_follow()")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            if od.behavior_type in ("GUI_Panel", "GUI_Label", "GUI_Button"):
                continue
            vname = _safe_name(od.name)
            out.append(f"        if {vname}_spin_speed ~= 0 then {vname}_rotation = {vname}_rotation + {vname}_spin_speed end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "Animation" and od.ani_file_id:
                vname = _safe_name(od.name)
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

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "LayerAnimation" and od.layer_anim_id:
                doll = project.get_paper_doll(od.layer_anim_id)
                if doll:
                    vname = _safe_name(od.name)
                    out.append(f"        if {vname}_pdoll then pdoll_update({vname}_pdoll, 1/60) end")

        if zone_objects:
            zone_instance_ids = {zpo.instance_id for zpo in zone_objects}
            mover_objects = [
                (_po, project.get_object_def(_po.object_def_id))
                for _po in scene.placed_objects
                if _po.instance_id not in zone_instance_ids
                and project.get_object_def(_po.object_def_id) is not None
                and project.get_object_def(_po.object_def_id).behavior_type != "Camera"
            ]
            for zpo in zone_objects:
                zod = project.get_object_def(zpo.object_def_id)
                if not zod:
                    continue
                zname = _safe_name(zod.name)
                zw = int(zod.width * zpo.scale)
                zh = int(zod.height * zpo.scale)
                all_zbeh = list(zod.behaviors) + list(zpo.instance_behaviors)
                has_zone_behs = any(b.trigger in ("on_enter","on_exit","on_overlap","on_interact_zone") for b in all_zbeh)
                if not has_zone_behs:
                    continue
                out.append(f"        -- zone: {zname}")
                _zone_has_cboxes = any(boxes for boxes in zod.collision_boxes)
                if not _zone_has_cboxes:
                    out.append(f"        local _zx1_{zname} = {zname}_x")
                    out.append(f"        local _zy1_{zname} = {zname}_y")
                    out.append(f"        local _zx2_{zname} = {zname}_x + {zw}")
                    out.append(f"        local _zy2_{zname} = {zname}_y + {zh}")
                out.append(f"        local _znow_{zname} = false")
                for mpo, mod in mover_objects:
                    mname = _safe_name(mod.name)
                    mw = int(mod.width * mpo.scale)
                    mh = int(mod.height * mpo.scale)
                    _mover_has_cboxes = any(boxes for boxes in mod.collision_boxes)
                    out.append(f"        if not _znow_{zname} then")
                    if _zone_has_cboxes and _mover_has_cboxes:
                        # Both have collision boxes — use check_obj_collision
                        _zframe = f"{zname}_ani_frame" if zod.behavior_type == "Animation" else "0"
                        _mframe = f"{mname}_ani_frame" if mod.behavior_type == "Animation" else "0"
                        out.append(f"            _znow_{zname} = check_obj_collision({_lua_str(zod.id)}, {zname}_x, {zname}_y, {_zframe}, {_lua_str(mod.id)}, {mname}_x, {mname}_y, {_mframe})")
                    elif _zone_has_cboxes:
                        # Zone has boxes, mover uses bounding box — check each zone box vs mover AABB
                        _zframe = f"{zname}_ani_frame" if zod.behavior_type == "Animation" else "0"
                        out.append(f"            local _zboxes = (obj_collision[{_lua_str(zod.id)}] or {{}})[({_zframe}) + 1] or {{}}")
                        out.append(f"            for _, _zb in ipairs(_zboxes) do")
                        out.append(f"                if aabb_overlap({zname}_x + _zb.x, {zname}_y + _zb.y, _zb.w, _zb.h, {mname}_x, {mname}_y, {mw}, {mh}) then")
                        out.append(f"                    _znow_{zname} = true")
                        out.append(f"                    break")
                        out.append(f"                end")
                        out.append(f"            end")
                    elif _mover_has_cboxes:
                        # Mover has boxes, zone uses bounding box — check each mover box vs zone AABB
                        _mframe = f"{mname}_ani_frame" if mod.behavior_type == "Animation" else "0"
                        out.append(f"            local _mboxes = (obj_collision[{_lua_str(mod.id)}] or {{}})[({_mframe}) + 1] or {{}}")
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
                    gravity_objects.append(od)
            if gravity_objects:
                out.append("        -- gravity")
                for od in gravity_objects:
                    vname = _safe_name(od.name)
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
                    for beh in od.behaviors:
                        for act in beh.actions:
                            if act.action_type in ("four_way_movement_collide", "two_way_movement_collide"):
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

                    if _grav_grid_id:
                        _has_cboxes = od.collision_boxes and any(boxes for boxes in od.collision_boxes)
                        if gdir in ("down", "up"):
                            new_pos_expr = f"{pos_var} + {vel_var}"
                            if _has_cboxes:
                                _cframe = f"{vname}_ani_frame" if od.behavior_type == "Animation" else "0"
                                _cid = _lua_str(od.id)
                                check_expr = f"check_obj_vs_grid(_ggrid, {_cid}, {other_pos}, _gnp, {_cframe})"
                            else:
                                check_expr = f"check_collision_rect(_ggrid, {other_pos}, _gnp, {_grav_pw}, {_grav_ph})"
                        else:
                            new_pos_expr = f"{pos_var} + {vel_var}"
                            if _has_cboxes:
                                _cframe = f"{vname}_ani_frame" if od.behavior_type == "Animation" else "0"
                                _cid = _lua_str(od.id)
                                check_expr = f"check_obj_vs_grid(_ggrid, {_cid}, _gnp, {other_pos}, {_cframe})"
                            else:
                                check_expr = f"check_collision_rect(_ggrid, _gnp, {other_pos}, {_grav_pw}, {_grav_ph})"
                        out.append(f"        do")
                        out.append(f"            local _ggrid = collision_grids[{_lua_str(_grav_grid_id)}]")
                        out.append(f"            local _gnp = {new_pos_expr}")
                        out.append(f"            if _ggrid and {check_expr} then")
                        out.append(f"                {vel_var} = 0")
                        out.append(f"            else")
                        out.append(f"                {pos_var} = _gnp")
                        out.append(f"            end")
                        out.append(f"        end")
                    else:
                        out.append(f"        {pos_var} = {pos_var} + {vel_var}")

        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")

        layer_by_id = {lc.id: lc for lc in scene_layers}

        def _emit_layer_image(lc):
            lname = _safe_name(lc.config.get("layer_name", "") or lc.id)
            img = project.get_image(lc.config.get("image_id", ""))
            if not img or not img.path:
                return
            fname = _asset_filename(img.path)
            locked = lc.config.get("screen_space_locked", False)
            parallax = lc.config.get("parallax", 1.0)
            out.append(f"        if layer_{lname}_visible and images[{_lua_str(fname)}] then")
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
            vname = _safe_name(od.name)
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
                hx_tx = od.gui_text_color.lstrip('#')
                tr, tg, tb = int(hx_tx[0:2], 16), int(hx_tx[2:4], 16), int(hx_tx[4:6], 16)
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
                if od.gui_text:
                    text = _lua_str(od.gui_text)
                    out.append(f'            if {font_var} then')
                    out.append(f'                local _tc = Color.new({tr}, {tg}, {tb})')
                    out.append(f'                Font.print({font_var}, {vname}_x + 8{shk_x}, {vname}_y + 8{shk_y}, {text}, _tc)')
                    out.append(f'            end')
                out.append(f'        end')
            elif od.behavior_type == "Animation":
                if od.ani_file_id:
                    # Compute scale ratio: object size vs animation frame size
                    # so the animation fills the object's intended dimensions
                    ani_export = project.get_animation_export(od.ani_file_id)
                    if ani_export and ani_export.frame_width > 0 and ani_export.frame_height > 0:
                        ani_sx = od.width / ani_export.frame_width
                        ani_sy = od.height / ani_export.frame_height
                    else:
                        ani_sx = 1.0
                        ani_sy = 1.0
                    out.append(f'        if {vname}_visible then')
                    out.append(f'            {ws_call}')
                    out.append(f'            local _ani_d = ani_data[{vname}_ani_id]')
                    out.append(f'            local _sheet = ani_sheets[{vname}_ani_id]')
                    out.append(f'            if _ani_d and _sheet then')
                    out.append(f'                local _cols = math.floor(_ani_d.sheet_width / _ani_d.frame_width)')
                    out.append(f'                if _cols < 1 then _cols = 1 end')
                    out.append(f'                local _fcol = {vname}_ani_frame % _cols')
                    out.append(f'                local _frow = math.floor({vname}_ani_frame / _cols)')
                    out.append(f'                local _fsx  = _fcol * _ani_d.frame_width')
                    out.append(f'                local _fsy  = _frow * _ani_d.frame_height')
                    # vita2d scale_rotate uses (x,y) as center; editor stores top-left
                    # ani_sx/ani_sy map frame pixels → object pixels (e.g. 256→960)
                    out.append(f'                local _asx  = {ani_sx}')
                    out.append(f'                local _asy  = {ani_sy}')
                    out.append(f'                local _fw   = _ani_d.frame_width * _asx * {vname}_scale * camera.zoom')
                    out.append(f'                local _fh   = _ani_d.frame_height * _asy * {vname}_scale * camera.zoom')
                    out.append(f'                local _ox   = _sx + _fw * 0.5{shk_x}')
                    out.append(f'                local _oy   = _sy + _fh * 0.5{shk_y}')
                    out.append(f'                local _tc   = Color.new(255, 255, 255, {vname}_opacity)')
                    out.append(f'                Graphics.drawImageExtended(_ox, _oy, _sheet, _fsx, _fsy, _ani_d.frame_width, _ani_d.frame_height, {vname}_rotation * (math.pi / 180), _asx * {vname}_scale * camera.zoom, _asy * {vname}_scale * camera.zoom, _tc)')
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
                    img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
                    if img and img.path:
                        fname = _asset_filename(img.path)
                        out.append(f'        if {vname}_visible and images[{_lua_str(fname)}] then')
                        out.append(f'            {ws_call}')
                        out.append(f'            local _iw = Graphics.getImageWidth(images[{_lua_str(fname)}])')
                        out.append(f'            local _ih = Graphics.getImageHeight(images[{_lua_str(fname)}])')
                        out.append(f'            local _tc = Color.new(255, 255, 255, {vname}_opacity)')
                        # vita2d scale_rotate uses (x,y) as center; editor stores top-left
                        out.append(f'            local _sw = _iw * {vname}_scale * camera.zoom')
                        out.append(f'            local _sh = _ih * {vname}_scale * camera.zoom')
                        out.append(f'            local _ox = _sx + _sw * 0.5{shk_x}')
                        out.append(f'            local _oy = _sy + _sh * 0.5{shk_y}')
                        out.append(f'            Graphics.drawImageExtended(_ox, _oy, images[{_lua_str(fname)}], 0, 0, _iw, _ih, {vname}_rotation * (math.pi / 180), {vname}_scale * camera.zoom, {vname}_scale * camera.zoom, _tc)')
                        out.append(f'        end')
                else:
                    all_behs = list(od.behaviors) + list(po.instance_behaviors)
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
            out.append(f'        for _li = 1, #_cp.lines do')
            out.append(f'            local _ln = _cp.lines[_li]')
            out.append(f'            if _ln ~= "" then')
            out.append(f'                local _show = _ln')
            out.append(f'                if _cp.typewriter and not _vn_tw_done then')
            out.append(f'                    if _chars_left <= 0 then _show = "" ')
            out.append(f'                    elseif _chars_left < string.len(_ln) then _show = string.sub(_ln, 1, _chars_left)')
            out.append(f'                    end')
            out.append(f'                    _chars_left = _chars_left - string.len(_ln)')
            out.append(f'                end')
            out.append(f'                if _show ~= "" then')
            if shadow:
                out.append(f'                    if {font_var} then Font.print({font_var}, 62 + shake_offset_x, _ly + 2 + shake_offset_y, _show, Color.new(0,0,0)) end')
            out.append(f'                    if {font_var} then Font.print({font_var}, 60 + shake_offset_x, _ly + shake_offset_y, _show, txt_col) end')
            out.append(f'                end')
            out.append(f'            end')
            out.append(f'            _ly = _ly + {vn_line_spacing}')
            out.append(f'        end')

        out.append("        -- draw dynamically created objects")
        out.append("        for _liid, _lo in pairs(_live_objects) do")
        out.append("            if _lo.visible then")
        out.append("                local _lsx, _lsy = world_to_screen(_lo.x, _lo.y)")
        out.append("                local _limg = _lo.image and images[_lo.image]")
        out.append("                if _limg then")
        out.append("                    local _liw = Graphics.getImageWidth(_limg)")
        out.append("                    local _lih = Graphics.getImageHeight(_limg)")
        out.append("                    local _ltc = Color.new(255, 255, 255, _lo.opacity)")
        # vita2d scale_rotate uses (x,y) as center; editor stores top-left
        out.append("                    local _lsw = _liw * _lo.scale * camera.zoom")
        out.append("                    local _lsh = _lih * _lo.scale * camera.zoom")
        out.append("                    local _lox = _lsx + _lsw * 0.5 + shake_offset_x")
        out.append("                    local _loy = _lsy + _lsh * 0.5 + shake_offset_y")
        out.append("                    Graphics.drawImageExtended(_lox, _loy, _limg, 0, 0, _liw, _lih, _lo.rotation * (math.pi / 180), _lo.scale * camera.zoom, _lo.scale * camera.zoom, _ltc)")
        out.append("                end")
        out.append("            end")
        out.append("        end")

        out.append("        flash_draw()")
        out.append("        if _fade_alpha > 0 then")
        out.append("            local _fa = math.floor(_fade_alpha)")
        out.append("            if _fa > 255 then _fa = 255 end")
        out.append("            Graphics.fillRect(0, 960, 0, 544, Color.new(0, 0, 0, _fa))")
        out.append("        end")
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")

        out.append("        if controls_released(SCE_CTRL_START) then")
        if project.game_data.save_enabled:
            out.append("            save_progress(current_scene)")
        out.append("            if current_music then Sound.close(current_music) end")
        out.append("            os.exit()")
        out.append("        end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname         = _safe_name(od.name)
                all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
                for beh in all_behaviors:
                    if beh.trigger == "on_input" and beh.input_action_name:
                        ia = next((a for a in project.game_data.input_actions
                                   if a.name == beh.input_action_name), None)
                        if ia:
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
            out.append(f"                for _i = 1, #_cp.lines do _total = _total + string.len(_cp.lines[_i]) end")
            out.append(f"                _vn_char_idx = _total")
            out.append(f"            elseif _cp.advance_to_next then")
            out.append(f"                current_scene = current_scene + 1")
            out.append(f"                advance = true")
            out.append(f"            elseif _vn_page < _vn_page_count then")
            out.append(f"                _vn_page = _vn_page + 1")
            out.append(f"                _vn_char_idx = 0")
            out.append(f"                _vn_tw_done = false")
            out.append(f"                _vn_prev_time = Timer.getTime(_scene_timer)")
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

def _scene_3d_to_lua(scene, scene_num: int, project) -> str:
    out = []
    out.append(f"-- scenes/scene_{scene_num:03d}.lua")
    out.append(f"-- 3D Scene {scene_num}: {scene.name or 'Unnamed'}")
    out.append("")
    out.append(f"function scene_{scene_num}()")
    md         = scene.map_data
    mode       = scene.movement_mode
    move_speed = scene.move_speed
    turn_speed = scene.turn_speed
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
    out.append(f"    RayCast3D.setViewsize(60)")
    out.append(f"    RayCast3D.loadMap(map_cells, {md.width}, {md.height}, {md.tile_size}, {md.wall_height})")
    out.append(f"    RayCast3D.setWallColor(Color.new({wr}, {wg}, {wb}))")
    out.append(f"    RayCast3D.setFloorColor(Color.new({fr}, {fg}, {fb}))")
    out.append(f"    RayCast3D.setSkyColor(Color.new({sr}, {sg}, {sb}))")
    out.append(f"    RayCast3D.enableFloor({_lua_bool(md.floor_on)})")
    out.append(f"    RayCast3D.enableSky({_lua_bool(md.sky_on)})")
    out.append(f"    RayCast3D.useShading({_lua_bool(md.shading)})")
    out.append(f"    RayCast3D.setAccuracy({md.accuracy})")
    spawn_world_x = md.spawn_x * md.tile_size + md.tile_size // 2
    spawn_world_y = md.spawn_y * md.tile_size + md.tile_size // 2
    out.append(f"    RayCast3D.spawnPlayer({spawn_world_x}, {spawn_world_y}, {md.spawn_angle})")
    # ── Register 3D billboard sprites ──
    sprite_objects = [po for po in scene.placed_objects if getattr(po, "is_3d", False) and not getattr(po, "hud_mode", False)]
    hud_objects = [po for po in scene.placed_objects if getattr(po, "is_3d", False) and getattr(po, "hud_mode", False)]
    has_blocking = False
    for i, po in enumerate(sprite_objects):
        od = project.get_object_def(po.object_def_id)
        if not od or not od.frames:
            continue
        img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
        if not img or not img.path:
            continue
        fname = _asset_filename(img.path)
        world_x = int((po.grid_x + po.offset_x) * md.tile_size)
        world_y = int((po.grid_y + po.offset_y) * md.tile_size)
        out.append(f"    RayCast3D.addSprite({world_x}, {world_y}, images[{_lua_str(fname)}], {po.scale}, {po.vertical_offset}, {_lua_bool(po.blocking)})")
        if not po.visible:
            out.append(f"    RayCast3D.setSpriteVisible({i + 1}, false)")
        if po.blocking:
            has_blocking = True
    # ── HUD object visibility variables ──
    for po in hud_objects:
        vname = f"hud_{po.instance_id}"
        out.append(f"    local {vname}_visible = {_lua_bool(po.visible)}")
    out.append(f"    local _ceil_c  = Color.new({sr}, {sg}, {sb})")
    out.append(f"    local _floor_c = Color.new({fr}, {fg}, {fb})")
    out.append("    local advance = false")
    out.append("    while not advance do")
    out.append("        controls_update()")
    out.append("        touch_update()")
    out.append("        _signals = {}")
    out.append("        if controls_released(SCE_CTRL_START) then")
    if project.game_data.save_enabled:
        out.append("            save_progress(current_scene)")
    out.append("            if current_music then Sound.close(current_music) end")
    out.append("            os.exit()")
    out.append("        end")
    if has_blocking:
        out.append("        local _save_px, _save_py = RayCast3D.getPlayer().x, RayCast3D.getPlayer().y")
    if mode == "free":
        out.append(f"        if controls_held(SCE_CTRL_UP)    then RayCast3D.movePlayer(FORWARD, {move_speed}) end")
        out.append(f"        if controls_held(SCE_CTRL_DOWN)  then RayCast3D.movePlayer(BACK,    {move_speed}) end")
        out.append(f"        if controls_held(SCE_CTRL_LEFT)  then RayCast3D.rotateCamera(LEFT,  {turn_speed}) end")
        out.append(f"        if controls_held(SCE_CTRL_RIGHT) then RayCast3D.rotateCamera(RIGHT, {turn_speed}) end")
    elif mode == "grid":
        out.append(f"        if controls_pressed(SCE_CTRL_UP)    then RayCast3D.movePlayer(FORWARD, {md.tile_size}) end")
        out.append(f"        if controls_pressed(SCE_CTRL_DOWN)  then RayCast3D.movePlayer(BACK,    {md.tile_size}) end")
        out.append(f"        if controls_pressed(SCE_CTRL_LEFT)  then RayCast3D.rotateCamera(LEFT,  {90 * (960 // 60)}) end")
        out.append(f"        if controls_pressed(SCE_CTRL_RIGHT) then RayCast3D.rotateCamera(RIGHT, {90 * (960 // 60)}) end")
    if has_blocking:
        out.append("        if RayCast3D.checkSpriteCollision(16) > 0 then")
        out.append("            RayCast3D.setPlayerPos(_save_px, _save_py)")
        out.append("        end")
    out.append("        Graphics.initBlend()")
    # Skybox: if a skybox image is set, draw it full-screen; otherwise fillRect sky+floor
    skybox_img = None
    if md.skybox_image_id and project:
        skybox_reg = project.get_image(md.skybox_image_id)
        if skybox_reg and skybox_reg.path:
            skybox_img = _asset_filename(skybox_reg.path)
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
    # ── HUD draws (screen-space, after all 3D rendering) ──
    for po in hud_objects:
        od = project.get_object_def(po.object_def_id)
        if not od or not od.frames:
            continue
        img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
        if not img or not img.path:
            continue
        fname = _asset_filename(img.path)
        vname = f"hud_{po.instance_id}"
        if po.hud_anchor == "top_left":
            x_expr = str(po.hud_x)
            y_expr = str(po.hud_y)
        elif po.hud_anchor == "top_right":
            x_expr = f"960 - Graphics.getImageWidth(images[{_lua_str(fname)}]) - {po.hud_x}"
            y_expr = str(po.hud_y)
        elif po.hud_anchor == "bottom_left":
            x_expr = str(po.hud_x)
            y_expr = f"544 - Graphics.getImageHeight(images[{_lua_str(fname)}]) - {po.hud_y}"
        elif po.hud_anchor == "bottom_right":
            x_expr = f"960 - Graphics.getImageWidth(images[{_lua_str(fname)}]) - {po.hud_x}"
            y_expr = f"544 - Graphics.getImageHeight(images[{_lua_str(fname)}]) - {po.hud_y}"
        elif po.hud_anchor == "center":
            x_expr = f"480 - Graphics.getImageWidth(images[{_lua_str(fname)}]) / 2 + {po.hud_x}"
            y_expr = f"272 - Graphics.getImageHeight(images[{_lua_str(fname)}]) / 2 + {po.hud_y}"
        else:
            x_expr = str(po.hud_x)
            y_expr = str(po.hud_y)
        out.append(f"        if {vname}_visible then")
        out.append(f"            Graphics.drawImage({x_expr}, {y_expr}, images[{_lua_str(fname)}])")
        out.append(f"        end")
    out.append("        Graphics.termBlend()")
    out.append("        Screen.flip()")
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
        "",
        "function check_collision(grid, wx, wy)",
        "    local col = math.floor(wx / grid.tile_size)",
        "    local row = math.floor(wy / grid.tile_size)",
        "    if col < 0 or col >= grid.map_width or row < 0 or row >= grid.map_height then",
        "        return true",
        "    end",
        "    local idx = row * grid.map_width + col + 1",
        "    return (grid.cells[idx] or 0) == 1",
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
        "obj_collision = {}",
        "",
        "function aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)",
        "    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by",
        "end",
        "",
        "function check_obj_collision(def_id_a, ax, ay, af, def_id_b, bx, by, bf)",
        "    local ca = obj_collision[def_id_a]",
        "    local cb = obj_collision[def_id_b]",
        "    if not ca or not cb then return false end",
        "    local boxes_a = ca[af + 1] or {}",
        "    local boxes_b = cb[bf + 1] or {}",
        "    for _, a in ipairs(boxes_a) do",
        "        for _, b in ipairs(boxes_b) do",
        "            if aabb_overlap(ax + a.x, ay + a.y, a.w, a.h,",
        "                            bx + b.x, by + b.y, b.w, b.h) then",
        "                return true",
        "            end",
        "        end",
        "    end",
        "    return false",
        "end",
        "",
        "function check_obj_vs_grid(grid, def_id, ox, oy, frame)",
        "    local c = obj_collision[def_id]",
        "    if not c then return false end",
        "    local boxes = c[frame + 1] or {}",
        "    for _, b in ipairs(boxes) do",
        "        if check_collision_rect(grid, ox + b.x, oy + b.y, b.w, b.h) then",
        "            return true",
        "        end",
        "    end",
        "    return false",
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

    files["lib/controls.lua"] = _make_controls_lib()
    files["lib/tween.lua"]    = _make_tween_lib()
    files["lib/camera.lua"]   = _make_camera_lib()
    files["lib/shake.lua"]    = _make_shake_lib()
    files["lib/flash.lua"]    = _make_flash_lib()
    files["lib/groups.lua"]   = _make_group_lib()
    files["lib/paths.lua"]    = _make_path_lib()
    if project.game_data.save_enabled:
        files["lib/save.lua"] = _make_save_lib(tid)

    has_3d = any(getattr(s, "scene_type", "2d") == "3d" for s in project.scenes)

    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        scene_key = f"scenes/scene_{scene_num:03d}.lua"
        if getattr(scene, "scene_type", "2d") == "3d":
            files[scene_key] = _scene_3d_to_lua(scene, scene_num, project)
        else:
            files[scene_key] = _scene_to_lua(scene, scene_num, project)

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
    idx.append("require('lib/controls')")
    idx.append("require('lib/groups')")
    idx.append("require('lib/paths')")
    if project.game_data.save_enabled:
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
    # Collect skybox images from 3D scenes
    for scene in project.scenes:
        if getattr(scene, "scene_type", "2d") == "3d":
            skybox_id = getattr(scene.map_data, "skybox_image_id", "")
            if skybox_id:
                img = project.get_image(skybox_id)
                if img and img.path:
                    all_image_paths.add(img.path)
    # Collect images from 3D scene placed objects
    for scene in project.scenes:
        if getattr(scene, "scene_type", "2d") == "3d":
            for po in scene.placed_objects:
                if getattr(po, "is_3d", False):
                    od = project.get_object_def(po.object_def_id)
                    if od:
                        for fr in od.frames:
                            img = project.get_image(fr.image_id) if fr.image_id else None
                            if img and img.path:
                                all_image_paths.add(img.path)

    # Collect images from paper doll layer trees, blink alt, mouth alt
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
        if doll.mouth.alt_image_id:
            img = project.get_image(doll.mouth.alt_image_id)
            if img and img.path:
                all_image_paths.add(img.path)

    idx.append("images = {}")
    for path in sorted(all_image_paths):
        fname = _asset_filename(path)
        idx.append(f'images[{_lua_str(fname)}] = Graphics.loadImage("app0:/assets/images/{fname}")')
    idx.append("")

    if has_3d:
        idx.append("-- Texture key lookup for 3D map cells")
        idx.append("map_tex_keys = {}")
        for i, path in enumerate(sorted(all_image_paths)):
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

    has_collision_layers = any(
        comp.component_type == "CollisionLayer"
        for scene in project.scenes
        for comp in scene.components
    )
    if has_collision_layers:
        idx.append("-- ─── COLLISION GRIDS ────────────────────────────────────")
        idx.append(_make_collision_lib())
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
        idx.append("")

    ani_files = list(set(
        od.ani_file_id
        for od in project.object_defs
        if od.behavior_type == "Animation" and od.ani_file_id
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
                idx.append(f'    fps          = {ani_obj.fps},')
                idx.append(f'}}')
                sheet_name = _asset_filename(ani_obj.spritesheet_path)
                idx.append(f'ani_sheets[{_lua_str(ani_id)}] = Graphics.loadImage("app0:/assets/animations/{sheet_name}")')
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
                idx.append(f'    }},')
                # Mouth config
                idx.append(f'    mouth = {{')
                idx.append(f'        layer_id    = {_lua_str(doll.mouth.layer_id)},')
                mouth_img = project.get_image(doll.mouth.alt_image_id) if doll.mouth.alt_image_id else None
                mouth_fname = _lua_str(_asset_filename(mouth_img.path)) if mouth_img and mouth_img.path else "nil"
                idx.append(f'        alt_image   = {mouth_fname},')
                idx.append(f'        cycle_speed = {doll.mouth.cycle_speed},')
                idx.append(f'    }},')
                # Idle breathing config
                idx.append(f'    idle = {{')
                idx.append(f'        layer_id        = {_lua_str(doll.idle_breathing.layer_id)},')
                idx.append(f'        scale_amount    = {doll.idle_breathing.scale_amount},')
                idx.append(f'        speed           = {doll.idle_breathing.speed},')
                idx.append(f'        affect_children = {_lua_bool(doll.idle_breathing.affect_children)},')
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
    defs_with_collision = [
        od for od in project.object_defs
        if any(boxes for boxes in od.collision_boxes)
    ]
    if defs_with_collision:
        for od in defs_with_collision:
            idx.append(f'obj_collision[{_lua_str(od.id)}] = {{')
            for frame_boxes in od.collision_boxes:
                if frame_boxes:
                    rects = ", ".join(
                        f"{{x={cb.x},y={cb.y},w={cb.width},h={cb.height}}}"
                        for cb in frame_boxes
                    )
                    idx.append(f"    {{ {rects} }},")
                else:
                    idx.append(f"    {{}},")
            idx.append("}")
        idx.append("")

    idx.append("-- ─── STATE ──────────────────────────────────────────────")
    idx.append("current_scene = 1")
    idx.append("current_music = nil")
    idx.append("running       = true")
    idx.append("_signals      = {}")
    idx.append("_live_objects = {}")
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
    idx.append("")

    idx.append("-- ─── MAIN LOOP ──────────────────────────────────────────")
    idx.append("while running do")
    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        prefix    = "    if" if si == 0 else "    elseif"
        idx.append(f"{prefix} current_scene == {scene_num} then scene_{scene_num}()")
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
        if od.behavior_type == "Animation" and od.ani_file_id:
            ani_obj = project.get_animation_export(od.ani_file_id)
            if ani_obj and ani_obj.spritesheet_path:
                if project.project_folder:
                    full_path = os.path.join(
                        project.project_folder, "animations", ani_obj.spritesheet_path
                    )
                else:
                    full_path = ani_obj.spritesheet_path
                mapping[full_path] = f"assets/animations/{ani_obj.spritesheet_path}"

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
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
    """
    Bake every TileLayer component in every scene into 512x512 PNG chunks.
    Writes chunks to build_dir/assets/tilechunks/.
    Returns list of (scene_index, comp_id, cx, cy, filename).

    Tiles with index -1 (eraser) are left transparent.
    Edge chunks are cropped to actual size — Lua draws them as-is.
    """
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
    ]
    return "\n".join(lines)


def _make_camera_lib() -> str:
    lines = [
        "-- lib/camera.lua",
        "camera = {",
        "    x               = 480,",
        "    y               = 272,",
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
        "    return wx - camera.x + 480, wy - camera.y + 272",
        "end",
        "",
        "function camera_bg_offset(parallax)",
        "    return -(camera.x - 480) * parallax, -(camera.y - 272) * parallax",
        "end",
        "",
        "function camera_apply_bounds()",
        "    if not camera.bounds_enabled then return end",
        "    if camera.x < 480 then camera.x = 480 end",
        "    if camera.y < 272 then camera.y = 272 end",
        "    if camera.x > camera.bounds_width  - 480 then camera.x = camera.bounds_width  - 480 end",
        "    if camera.y > camera.bounds_height - 272 then camera.y = camera.bounds_height - 272 end",
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


def _action_to_lua_inline(action: BehaviorAction, obj_var: str | None, project=None) -> list[str]:
    t = action.action_type
    lines = []
    spd = getattr(action, "movement_speed", 4)

    if t == "four_way_movement":
        lines.append(f"if controls_held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
        lines.append(f"if controls_held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")
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
    elif t == "increment_var":
        vn    = _safe_name(action.var_name) if action.var_name else "unknown"
        delta = getattr(action, "var_delta", 1)
        lines.append(f"{vn} = {vn} + {delta}")
    elif t == "if_button_pressed":
        btn = _button_constant(action.button)
        lines.append(f"if controls_pressed({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var, project):
                lines.append(f"    {sl}")
        lines.append("end")
    elif t == "if_button_held":
        btn = _button_constant(action.button)
        lines.append(f"if controls_held({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var, project):
                lines.append(f"    {sl}")
        lines.append("end")
    elif t == "if_button_released":
        btn = _button_constant(action.button)
        lines.append(f"if controls_released({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var, project):
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
        intensity = getattr(action, "shake_intensity", 5.0)
        duration  = getattr(action, "shake_duration",  0.5)
        frames    = int(duration * 60)
        lines.append(f"shake_intensity = {intensity}")
        lines.append(f"shake_timer = {frames}")
    elif t == "ani_play":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        if target:
            lines.append(f"{target}_ani_playing = true")
            lines.append(f"{target}_ani_done = false")
    elif t == "ani_pause":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        if target:
            lines.append(f"{target}_ani_playing = false")
    elif t == "ani_stop":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        if target:
            lines.append(f"{target}_ani_playing = false")
            lines.append(f"{target}_ani_frame = 0")
            lines.append(f"{target}_ani_done = false")
    elif t == "ani_set_frame":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        frame  = getattr(action, "ani_target_frame", 0)
        if target:
            lines.append(f"{target}_ani_frame = {frame}")
    elif t == "ani_set_speed":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        fps    = getattr(action, "ani_fps", 12)
        if target:
            lines.append(f"{target}_ani_fps = {fps}")
    elif t == "layer_show":
        lname = _safe_name(getattr(action, "layer_name", "") or "")
        if lname:
            lines.append(f"layer_{lname}_visible = true")
        else:
            lines.append("-- layer_show: no layer name specified")
    elif t == "layer_hide":
        lname = _safe_name(getattr(action, "layer_name", "") or "")
        if lname:
            lines.append(f"layer_{lname}_visible = false")
        else:
            lines.append("-- layer_hide: no layer name specified")
    elif t == "layer_set_image":
        lname = _safe_name(getattr(action, "layer_name", "") or "")
        lines.append(f"-- layer_set_image: runtime image swap not yet supported for layer_{lname}")
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


# ─────────────────────────────────────────────────────────────
#  TILELAYER CHUNK DRAW HELPER — emitted into scene Lua
# ─────────────────────────────────────────────────────────────

def _emit_tilelayer_draws(scene, project, out: list, indent: str = "        "):
    """
    Emit draw calls for all TileLayer components in a scene, sorted by draw_layer.
    Draws _cx0-1 to _cx0+2 horizontally (4 columns) so chunks are buffered one
    column ahead in both horizontal directions before the camera center reaches them.
    Vertically draws 2 rows (_cy0 to _cy0+1).
    """
    tile_layers = sorted(
        [c for c in scene.components if c.component_type == "TileLayer"],
        key=lambda c: c.config.get("draw_layer", 0)
    )
    if not tile_layers:
        return

    for comp in tile_layers:
        ts_id = comp.config.get("tileset_id")
        if not ts_id:
            continue
        ts = project.get_tileset(ts_id)
        if ts is None:
            continue

        safe_id   = comp.id.replace("-", "_")
        tile_size = ts.tile_size
        map_w     = comp.config.get("map_width",  30)
        map_h     = comp.config.get("map_height", 17)
        world_w   = map_w * tile_size
        world_h   = map_h * tile_size

        import math
        chunks_x = math.ceil(world_w / CHUNK_SIZE)
        chunks_y = math.ceil(world_h / CHUNK_SIZE)

        out.append(f"{indent}-- TileLayer {safe_id} (draw_layer {comp.config.get('draw_layer', 0)})")
        out.append(f"{indent}do")
        out.append(f"{indent}    local _cam_left = camera.x - 480")
        out.append(f"{indent}    local _cam_top  = camera.y - 272")
        out.append(f"{indent}    local _cx0 = math.floor(_cam_left / {CHUNK_SIZE})")
        out.append(f"{indent}    local _cy0 = math.floor(_cam_top  / {CHUNK_SIZE})")
        out.append(f"{indent}    for _dcy = _cy0, _cy0 + 1 do")
        out.append(f"{indent}        for _dcx = _cx0 - 1, _cx0 + 2 do")
        out.append(f"{indent}            if _dcx >= 0 and _dcx < {chunks_x} and _dcy >= 0 and _dcy < {chunks_y} then")
        out.append(f"{indent}                local _key = 'tl_{safe_id}_' .. _dcx .. '_' .. _dcy")
        out.append(f"{indent}                local _img = tile_chunks[_key]")
        out.append(f"{indent}                if _img then")
        out.append(f"{indent}                    local _dx = _dcx * {CHUNK_SIZE} - _cam_left + shake_offset_x")
        out.append(f"{indent}                    local _dy = _dcy * {CHUNK_SIZE} - _cam_top  + shake_offset_y")
        out.append(f"{indent}                    Graphics.drawImage(_dx, _dy, _img)")
        out.append(f"{indent}                end")
        out.append(f"{indent}            end")
        out.append(f"{indent}        end")
        out.append(f"{indent}    end")
        out.append(f"{indent}end")


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
        if camera_obj.camera_bounds_enabled:
            out.append(f"    camera.bounds_enabled = true")
            out.append(f"    camera.bounds_width   = {camera_obj.camera_bounds_width}")
            out.append(f"    camera.bounds_height  = {camera_obj.camera_bounds_height}")
        else:
            out.append(f"    camera.bounds_enabled = false")
        out.append(f"    camera.follow_lag = {camera_obj.camera_follow_lag}")

    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.behavior_type != "Camera":
            vname = _safe_name(od.name)
            out.append(f"    {vname}_x       = {po.x}")
            out.append(f"    {vname}_y       = {po.y}")
            out.append(f"    {vname}_visible = {_lua_bool(po.visible)}")
            if od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
                ani_play_on_spawn = getattr(od, "ani_play_on_spawn", True)
                ani_start_paused  = getattr(od, "ani_start_paused",  False)
                ani_pause_frame   = getattr(od, "ani_pause_frame",   0)
                ani_fps_override  = getattr(od, "ani_fps_override",  0)
                ani_loop          = getattr(od, "ani_loop",          True)
                ani_playing       = "true" if ani_play_on_spawn and not ani_start_paused else "false"
                start_frame       = ani_pause_frame if ani_start_paused else 0
                out.append(f"    {vname}_ani_id      = {_lua_str(od.ani_file_id)}")
                out.append(f"    {vname}_ani_frame   = {start_frame}")
                out.append(f"    {vname}_ani_playing = {ani_playing}")
                out.append(f"    {vname}_ani_timer   = 0")
                out.append(f"    {vname}_ani_loop    = {_lua_bool(ani_loop)}")
                out.append(f"    {vname}_ani_fps     = {ani_fps_override}")
                out.append(f"    {vname}_ani_done    = false")

    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od:
            all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
            for beh in all_behaviors:
                if beh.trigger == "on_input" and getattr(beh, "input_action_name", ""):
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

    scene_bg          = None
    scene_bg_parallax = 1.0
    for comp in scene.components:
        if comp.component_type == "Background":
            img = project.get_image(comp.config.get("image_id", ""))
            if img and img.path:
                scene_bg          = _asset_filename(img.path)
                scene_bg_parallax = comp.config.get("parallax", 1.0)
                break

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
        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")
        if scene_bg:
            out.append(f'        if images[{_lua_str(scene_bg)}] then Graphics.drawImage(0, 0, images[{_lua_str(scene_bg)}]) end')
        out.append('        if deff then')
        out.append('            Font.print(deff, 62, 452, "Cross: New Game    Triangle: Continue", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 450, "Cross: New Game    Triangle: Continue", Color.new(255,255,255))')
        out.append('        end')
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")
        out.append("        controls_update()")
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
        out.append("        Graphics.initBlend()")
        out.append("        Screen.clear()")
        if scene_bg:
            out.append(f'        if images[{_lua_str(scene_bg)}] then Graphics.drawImage(0, 0, images[{_lua_str(scene_bg)}]) end')
        out.append('        if deff then')
        out.append('            Font.print(deff, 62, 262, "--- THE END ---", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 260, "--- THE END ---", Color.new(255,255,255))')
        out.append('            Font.print(deff, 62, 302, "Press START to exit", Color.new(0,0,0))')
        out.append('            Font.print(deff, 60, 300, "Press START to exit", Color.new(255,255,255))')
        out.append('        end')
        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")
        out.append("        controls_update()")
        out.append("        if controls_released(SCE_CTRL_START) then")
        out.append("            if current_music then Sound.close(current_music) end")
        out.append("            waiting = false")
        out.append("            running = false")
        out.append("        end")
        out.append("    end")

    else:
        vn_comp = next((c for c in scene.components if c.component_type == "VNDialogBox"), None)

        out.append("    local advance = false")
        if vn_comp and vn_comp.config.get("auto_advance", False):
            out.append("    local auto_advance_timer = 0")
        out.append("    while not advance do")
        out.append("        tween_update()")
        out.append("        shake_update()")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od or od.behavior_type == "Camera":
                continue
            vname = _safe_name(od.name)
            all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
            for beh in all_behaviors:
                if beh.trigger == "on_frame":
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project):
                            out.append(f"        {line}")
                elif beh.trigger == "on_button_pressed" and beh.button:
                    btn = _button_constant(beh.button)
                    out.append(f"        if controls_pressed({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project):
                            out.append(f"            {line}")
                    out.append(f"        end")
                elif beh.trigger == "on_button_held" and beh.button:
                    btn = _button_constant(beh.button)
                    out.append(f"        if controls_held({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project):
                            out.append(f"            {line}")
                    out.append(f"        end")
                elif beh.trigger == "on_button_released" and beh.button:
                    btn = _button_constant(beh.button)
                    out.append(f"        if controls_released({btn}) then")
                    for action in beh.actions:
                        for line in _action_to_lua_inline(action, vname, project):
                            out.append(f"            {line}")
                    out.append(f"        end")

        out.append("        camera_update_follow()")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
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

        if zone_objects:
            zone_instance_ids = {zpo.instance_id for zpo in zone_objects}
            mover_objects = [
                (_po, project.get_object_def(_po.object_def_id))
                for _po in scene.placed_objects
                if _po.instance_id not in zone_instance_ids
                and (lambda _od: _od and _od.behavior_type != "Camera")(project.get_object_def(_po.object_def_id))
            ]
            for zpo in zone_objects:
                zod = project.get_object_def(zpo.object_def_id)
                zname = _safe_name(zod.name)
                zw = int(zod.width * zpo.scale)
                zh = int(zod.height * zpo.scale)
                all_zbeh = list(zod.behaviors) + list(zpo.instance_behaviors)
                has_zone_behs = any(b.trigger in ("on_enter","on_exit","on_overlap","on_interact_zone") for b in all_zbeh)
                if not has_zone_behs:
                    continue
                out.append(f"        -- zone: {zname}")
                out.append(f"        local _zx1_{zname} = {zname}_x")
                out.append(f"        local _zy1_{zname} = {zname}_y")
                out.append(f"        local _zx2_{zname} = {zname}_x + {zw}")
                out.append(f"        local _zy2_{zname} = {zname}_y + {zh}")
                out.append(f"        local _znow_{zname} = false")
                for mpo, mod in mover_objects:
                    mname = _safe_name(mod.name)
                    mw = int(mod.width * mpo.scale)
                    mh = int(mod.height * mpo.scale)
                    out.append(f"        if not _znow_{zname} then")
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
                            for line in _action_to_lua_inline(action, zname, project):
                                out.append(f"            {line}")
                    out.append(f"        end")
                exit_behs = [b for b in all_zbeh if b.trigger == "on_exit"]
                if exit_behs:
                    out.append(f"        if not _znow_{zname} and _zprev_{zname} then")
                    for beh in exit_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project):
                                out.append(f"            {line}")
                    out.append(f"        end")
                overlap_behs = [b for b in all_zbeh if b.trigger == "on_overlap"]
                if overlap_behs:
                    out.append(f"        if _znow_{zname} then")
                    for beh in overlap_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project):
                                out.append(f"            {line}")
                    out.append(f"        end")
                iz_behs = [b for b in all_zbeh if b.trigger == "on_interact_zone"]
                if iz_behs:
                    out.append(f"        if _znow_{zname} and controls_released(SCE_CTRL_CROSS) then")
                    for beh in iz_behs:
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, zname, project):
                                out.append(f"            {line}")
                    out.append(f"        end")
                out.append(f"        _zone_prev[{_lua_str(zpo.instance_id)}] = _znow_{zname}")

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
                out.append(f"            Graphics.drawImage(0, 0, images[{_lua_str(fname)}])")
            else:
                out.append(f"            local _lox, _loy = camera_bg_offset({parallax})")
                out.append(f"            Graphics.drawImage(_lox + shake_offset_x, _loy + shake_offset_y, images[{_lua_str(fname)}])")
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
                pr, pg, pb = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
                out.append(f'        if {vname}_visible then')
                out.append(f'            local _pc = Color.new({pr}, {pg}, {pb}, {od.gui_bg_opacity})')
                out.append(f'            Graphics.fillRect({vname}_x{shk_x}, {vname}_x + {od.gui_width}{shk_x}, {vname}_y{shk_y}, {vname}_y + {od.gui_height}{shk_y}, _pc)')
                out.append(f'        end')
            elif od.behavior_type == "GUI_Label":
                hx = od.gui_text_color.lstrip('#')
                lr, lg, lb = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'
                text = _lua_str(od.gui_text)
                out.append(f'        if {vname}_visible and {font_var} then')
                out.append(f'            local _lc = Color.new({lr}, {lg}, {lb})')
                out.append(f'            Font.print({font_var}, {vname}_x{shk_x}, {vname}_y{shk_y}, {text}, _lc)')
                out.append(f'        end')
            elif od.behavior_type == "GUI_Button":
                hx_bg = od.gui_bg_color.lstrip('#')
                br, bg_g, bb = int(hx_bg[0:2],16), int(hx_bg[2:4],16), int(hx_bg[4:6],16)
                hx_tx = od.gui_text_color.lstrip('#')
                tr, tg, tb = int(hx_tx[0:2],16), int(hx_tx[2:4],16), int(hx_tx[4:6],16)
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'
                out.append(f'        if {vname}_visible then')
                bg_img = None
                if getattr(od, "gui_bg_image_id", ""):
                    bi = project.get_image(od.gui_bg_image_id)
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
                if getattr(od, "ani_file_id", ""):
                    out.append(f'        if {vname}_visible then')
                    out.append(f'            {ws_call}')
                    out.append(f'            ani_draw({vname}_ani_id, {vname}_ani_frame, _sx{shk_x}, _sy{shk_y})')
                    out.append(f'        end')
            else:
                if od.frames:
                    img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
                    if img and img.path:
                        fname = _asset_filename(img.path)
                        out.append(f'        if {vname}_visible and images[{_lua_str(fname)}] then')
                        out.append(f'            {ws_call}')
                        out.append(f'            Graphics.drawImage(_sx{shk_x}, _sy{shk_y}, images[{_lua_str(fname)}])')
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

        # ── Background (legacy, always first) ─────────────────
        if scene_bg:
            out.append(f"        local _bg_ox, _bg_oy = camera_bg_offset({scene_bg_parallax})")
            out.append(f'        if images[{_lua_str(scene_bg)}] then')
            out.append(f'            Graphics.drawImage(_bg_ox + shake_offset_x, _bg_oy + shake_offset_y, images[{_lua_str(scene_bg)}])')
            out.append(f'        end')

        # ── Build interleaved draw order ──────────────────────
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
                        out.append(f"                            local _dx = _dcx * {CHUNK_SIZE} - _cl + shake_offset_x")
                        out.append(f"                            local _dy = _dcy * {CHUNK_SIZE} - _ct + shake_offset_y")
                        out.append(f"                            Graphics.drawImage(_dx, _dy, _im)")
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
            speaker   = cfg.get("speaker_name", "")
            lines_raw = cfg.get("lines", [])
            non_empty = [l for l in lines_raw if l.strip()]
            fill      = cfg.get("fill_color", "#000000")
            opacity   = cfg.get("opacity", 150)
            r, g, b   = int(fill[1:3],16), int(fill[3:5],16), int(fill[5:7],16)
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
                br2, bg2, bb2 = int(bc[1:3],16), int(bc[3:5],16), int(bc[5:7],16)
                thick         = cfg.get("border_thickness", 2)
                out.append(f'        local border_col = Color.new({br2}, {bg2}, {bb2})')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, {335+thick} + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 920 + shake_offset_x, {535-thick} + shake_offset_y, 535 + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, {40+thick} + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, border_col)')
                out.append(f'        Graphics.fillRect({920-thick} + shake_offset_x, 920 + shake_offset_x, 335 + shake_offset_y, 535 + shake_offset_y, border_col)')
            tc            = cfg.get("text_color", "#ffffff")
            tr2, tg2, tb2 = int(tc[1:3],16), int(tc[3:5],16), int(tc[5:7],16)
            shadow        = cfg.get("shadow", True)
            out.append(f'        local txt_col = Color.new({tr2}, {tg2}, {tb2})')
            font_id  = cfg.get("font_id")
            font_var = "deff"
            if font_id:
                fnt = project.get_font(font_id)
                if fnt and fnt.path:
                    fname    = _asset_filename(fnt.path)
                    font_var = f'fonts[{_lua_str(fname)}]'
            if speaker:
                nametag_pos = cfg.get("nametag_position", "inside box top")
                nc          = cfg.get("nametag_color", "#333333")
                nr, ng, nb  = int(nc[1:3],16), int(nc[3:5],16), int(nc[5:7],16)
                name_y      = 345 if nametag_pos == "inside box top" else 320
                tag_bg_y    = name_y - 5
                out.append(f'        local tag_col = Color.new({nr}, {ng}, {nb}, 200)')
                out.append(f'        Graphics.fillRect(40 + shake_offset_x, 240 + shake_offset_x, {tag_bg_y} + shake_offset_y, {tag_bg_y+26} + shake_offset_y, tag_col)')
                if shadow:
                    out.append(f'        if {font_var} then Font.print({font_var}, 62 + shake_offset_x, {name_y+2} + shake_offset_y, {_lua_str(speaker)}, Color.new(0,0,0)) end')
                out.append(f'        if {font_var} then Font.print({font_var}, 60 + shake_offset_x, {name_y} + shake_offset_y, {_lua_str(speaker)}, txt_col) end')
            line_y = 383
            for ln in non_empty:
                if shadow:
                    out.append(f'        if {font_var} then Font.print({font_var}, 62 + shake_offset_x, {line_y+2} + shake_offset_y, {_lua_str(ln)}, Color.new(0,0,0)) end')
                out.append(f'        if {font_var} then Font.print({font_var}, 60 + shake_offset_x, {line_y} + shake_offset_y, {_lua_str(ln)}, txt_col) end')
                line_y += 35

        out.append("        Graphics.termBlend()")
        out.append("        Screen.flip()")
        out.append("        controls_update()")
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
                    if beh.trigger == "on_input" and getattr(beh, "input_action_name", ""):
                        ia = next((a for a in project.game_data.input_actions
                                   if a.name == beh.input_action_name), None)
                        if ia:
                            btn = _button_constant(ia.button)
                            if ia.event == "hold_for":
                                timer_var = f"_hold_{_safe_name(ia.name)}_timer"
                                frames    = int(getattr(ia, "hold_duration", 2.0) * 60)
                                out.append(f"        if controls_held({btn}) then")
                                out.append(f"            {timer_var} = {timer_var} + 1")
                                out.append(f"            if {timer_var} == {frames} then")
                                for action in beh.actions:
                                    for line in _action_to_lua_inline(action, vname, project):
                                        out.append(f"                {line}")
                                out.append(f"            end")
                                out.append(f"        else")
                                out.append(f"            {timer_var} = 0")
                                out.append(f"        end")
                            else:
                                fn_check = _event_check(ia.event)
                                out.append(f"        if {fn_check}({btn}) then")
                                for action in beh.actions:
                                    for line in _action_to_lua_inline(action, vname, project):
                                        out.append(f"            {line}")
                                out.append(f"        end")

        if vn_comp:
            cfg = vn_comp.config
            if cfg.get("advance", True):
                btn_const = {
                    "cross":    "SCE_CTRL_CROSS",
                    "circle":   "SCE_CTRL_CIRCLE",
                    "square":   "SCE_CTRL_SQUARE",
                    "triangle": "SCE_CTRL_TRIANGLE",
                }.get(cfg.get("advance_button", "cross"), "SCE_CTRL_CROSS")
                out.append(f"        if controls_released({btn_const}) then")
                out.append(f"            current_scene = current_scene + 1")
                out.append(f"            advance = true")
                out.append(f"        end")
            if cfg.get("auto_advance", False):
                secs   = cfg.get("auto_advance_secs", 3.0)
                frames = int(secs * 60)
                out.append(f"        if auto_advance_timer >= {frames} then")
                out.append(f"            current_scene = current_scene + 1")
                out.append(f"            advance = true")
                out.append(f"        end")
                out.append(f"        auto_advance_timer = auto_advance_timer + 1")

        out.append("    end")

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
    mode       = getattr(scene, "movement_mode", "free")
    move_speed = getattr(scene, "move_speed", 5)
    turn_speed = getattr(scene, "turn_speed", 50)
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
    fr, fg, fb = int(md.floor_color[1:3],16), int(md.floor_color[3:5],16), int(md.floor_color[5:7],16)
    sr, sg, sb = int(md.sky_color[1:3],16),   int(md.sky_color[3:5],16),   int(md.sky_color[5:7],16)
    wr, wg, wb = int(md.wall_color[1:3],16),  int(md.wall_color[3:5],16),  int(md.wall_color[5:7],16)
    out.append(f"    RayCast3D.setResolution(960, 544)")
    out.append(f"    RayCast3D.setViewsize(60)")
    out.append(f"    RayCast3D.loadMap(map_cells, {md.width}, {md.height}, {md.tile_size}, {md.wall_height})")
    out.append(f"    RayCast3D.setWallColor(Color.new({wr}, {wg}, {wb}))")
    out.append(f"    RayCast3D.useShading({_lua_bool(md.shading)})")
    out.append(f"    RayCast3D.setAccuracy(3)")
    spawn_world_x = md.spawn_x * md.tile_size + md.tile_size // 2
    spawn_world_y = md.spawn_y * md.tile_size + md.tile_size // 2
    out.append(f"    RayCast3D.spawnPlayer({spawn_world_x}, {spawn_world_y}, {md.spawn_angle})")
    out.append(f"    local _ceil_c  = Color.new({sr}, {sg}, {sb})")
    out.append(f"    local _floor_c = Color.new({fr}, {fg}, {fb})")
    out.append("    local advance = false")
    out.append("    while not advance do")
    out.append("        controls_update()")
    out.append("        if controls_released(SCE_CTRL_START) then")
    if project.game_data.save_enabled:
        out.append("            save_progress(current_scene)")
    out.append("            if current_music then Sound.close(current_music) end")
    out.append("            os.exit()")
    out.append("        end")
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
    out.append("        Graphics.initBlend()")
    out.append(f"        Graphics.fillRect(0, 960, 0, 272, _ceil_c)")
    out.append(f"        Graphics.fillRect(0, 960, 272, 544, _floor_c)")
    out.append("        RayCast3D.renderScene(0, 0)")
    out.append("        Graphics.termBlend()")
    out.append("        Screen.flip()")
    out.append("    end")
    out.append("end")
    out.append("")
    return "\n".join(out)


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
    idx.append("require('lib/controls')")
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
            if comp.component_type in ("Background", "Foreground", "Layer"):
                img = project.get_image(comp.config.get("image_id", ""))
                if img and img.path:
                    all_image_paths.add(img.path)
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od:
                for fr in od.frames:
                    img = project.get_image(fr.image_id) if fr.image_id else None
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

    ani_files = list(set(
        od.ani_file_id
        for od in project.object_defs
        if od.behavior_type == "Animation" and getattr(od, "ani_file_id", "")
    ))
    if ani_files:
        for ani_id in sorted(ani_files):
            ani_obj = project.get_animation_export(ani_id) if hasattr(project, 'get_animation_export') else None
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
            trans_obj = project.get_transition_export(trans_id) if hasattr(project, 'get_transition_export') else None
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

    idx.append("-- ─── STATE ──────────────────────────────────────────────")
    idx.append("current_scene = 1")
    idx.append("current_music = nil")
    idx.append("running       = true")
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
        if od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
            ani_obj = project.get_animation_export(od.ani_file_id) if hasattr(project, 'get_animation_export') else None
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
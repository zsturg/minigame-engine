# -*- coding: utf-8 -*-
"""
Vita Adventure Creator — Lua Exporter
Generates a self-contained main.lua using the lifelua API directly.
No engine.lua abstraction — everything runs natively on the Vita.
"""

from __future__ import annotations
from pathlib import Path
from models import Project, Scene, Behavior, BehaviorAction
import json


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
        "cross":     "SCE_CTRL_CROSS",
        "circle":    "SCE_CTRL_CIRCLE",
        "square":    "SCE_CTRL_SQUARE",
        "triangle":  "SCE_CTRL_TRIANGLE",
        "dpad_up":   "SCE_CTRL_UP",
        "dpad_down": "SCE_CTRL_DOWN",
        "dpad_left": "SCE_CTRL_LEFT",
        "dpad_right":"SCE_CTRL_RIGHT",
        "l":         "SCE_CTRL_LTRIGGER",
        "r":         "SCE_CTRL_RTRIGGER",
        "start":     "SCE_CTRL_START",
        "select":    "SCE_CTRL_SELECT",
    }.get(button, "SCE_CTRL_CROSS")

def _event_check(event: str) -> str:
    return {
        "pressed":  "controls.pressed",
        "released": "controls.released",
        "held":     "controls.held",
    }.get(event, "controls.pressed")


# ─────────────────────────────────────────────────────────────
#  INLINE ACTION → LUA
# ─────────────────────────────────────────────────────────────

def _action_to_lua_inline(action: BehaviorAction, obj_var: str | None) -> list[str]:
    t = action.action_type
    lines = []
    spd = getattr(action, "movement_speed", 4)

    if t == "four_way_movement":
        lines.append(f"if controls.held(SCE_CTRL_UP)    then {obj_var}_y = {obj_var}_y - {spd} end")
        lines.append(f"if controls.held(SCE_CTRL_DOWN)  then {obj_var}_y = {obj_var}_y + {spd} end")
        lines.append(f"if controls.held(SCE_CTRL_LEFT)  then {obj_var}_x = {obj_var}_x - {spd} end")
        lines.append(f"if controls.held(SCE_CTRL_RIGHT) then {obj_var}_x = {obj_var}_x + {spd} end")
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
        lines.append("if current_music then audio.stop(current_music) end")
        lines.append("os.exit()")
    elif t == "stop_music":
        lines.append("if current_music then audio.stop(current_music) end")
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
        vn = _safe_name(action.var_name) if action.var_name else "unknown"
        val = _lua_str(action.var_value) if isinstance(action.var_value, str) else str(action.var_value)
        lines.append(f"{vn} = {val}")
    elif t == "increment_var":
        vn = _safe_name(action.var_name) if action.var_name else "unknown"
        delta = getattr(action, "var_delta", 1)
        lines.append(f"{vn} = {vn} + {delta}")
    elif t == "if_button_pressed":
        btn = _button_constant(action.button)
        lines.append(f"if controls.pressed({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var):
                lines.append(f"    {sl}")
        lines.append("end")
    elif t == "if_button_held":
        btn = _button_constant(action.button)
        lines.append(f"if controls.held({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var):
                lines.append(f"    {sl}")
        lines.append("end")
    elif t == "if_button_released":
        btn = _button_constant(action.button)
        lines.append(f"if controls.released({btn}) then")
        for sa in getattr(action, "sub_actions", []):
            for sl in _action_to_lua_inline(sa, obj_var):
                lines.append(f"    {sl}")
        lines.append("end")

    # ── Camera actions ───────────────────────────────────────
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
        target_var = _safe_name(action.camera_follow_target_def_id) if action.camera_follow_target_def_id else ""
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
        duration = getattr(action, "shake_duration", 0.5)
        frames = int(duration * 60)
        lines.append(f"shake_intensity = {intensity}")
        lines.append(f"shake_timer = {frames}")

    # ── Animation object actions ─────────────────────────────
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
        frame = getattr(action, "ani_target_frame", 0)
        if target:
            lines.append(f"{target}_ani_frame = {frame}")

    elif t == "ani_set_speed":
        target = _safe_name(action.object_def_id) if action.object_def_id else obj_var
        fps = getattr(action, "ani_fps", 12)
        if target:
            lines.append(f"{target}_ani_fps = {fps}")

    elif t not in ("none", ""):
        lines.append(f"-- [{t}]")

    return lines


# ─────────────────────────────────────────────────────────────
#  SCENE FUNCTION → LUA
# ─────────────────────────────────────────────────────────────

def _scene_to_lua(scene: Scene, scene_num: int, project: Project) -> list[str]:
    out = []
    out.append(f"-- Scene {scene_num}: {scene.name or 'Unnamed'}")
    out.append(f"function scene_{scene_num}()")

    # ── Camera initialization for this scene ─────────────────
    camera_obj = None
    camera_placed = None
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.behavior_type == "Camera":
            camera_obj = od
            camera_placed = po
            break

    bg_width, bg_height = 960, 544
    for comp in scene.components:
        if comp.component_type == "Background":
            img = project.get_image(comp.config.get("image_id", ""))
            if img and img.path:
                pass

    out.append("    -- Camera reset for scene")
    out.append("    camera_reset_state()")

    if camera_obj:
        if camera_placed:
            out.append(f"    camera.x = {camera_placed.x}")
            out.append(f"    camera.y = {camera_placed.y}")
        if camera_obj.camera_bounds_enabled:
            out.append(f"    camera.bounds_enabled = true")
            out.append(f"    camera.bounds_width = {camera_obj.camera_bounds_width}")
            out.append(f"    camera.bounds_height = {camera_obj.camera_bounds_height}")
        else:
            out.append(f"    camera.bounds_enabled = false")
        out.append(f"    camera.follow_lag = {camera_obj.camera_follow_lag}")

    # Object position locals
    for po in scene.placed_objects:
        od = project.get_object_def(po.object_def_id)
        if od and od.behavior_type != "Camera":
            vname = _safe_name(od.name)
            out.append(f"    local {vname}_x       = {po.x}")
            out.append(f"    local {vname}_y       = {po.y}")
            out.append(f"    local {vname}_visible = {_lua_bool(po.visible)}")

            # Animation object state
            if od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
                ani_play_on_spawn = getattr(od, "ani_play_on_spawn", True)
                ani_start_paused = getattr(od, "ani_start_paused", False)
                ani_pause_frame = getattr(od, "ani_pause_frame", 0)
                ani_fps_override = getattr(od, "ani_fps_override", 0)
                ani_loop = getattr(od, "ani_loop", True)

                ani_playing = "true" if ani_play_on_spawn and not ani_start_paused else "false"
                start_frame = ani_pause_frame if ani_start_paused else 0

                out.append(f"    local {vname}_ani_id = {_lua_str(od.ani_file_id)}")
                out.append(f"    local {vname}_ani_frame = {start_frame}")
                out.append(f"    local {vname}_ani_playing = {ani_playing}")
                out.append(f"    local {vname}_ani_timer = 0")
                out.append(f"    local {vname}_ani_loop = {_lua_bool(ani_loop)}")
                out.append(f"    local {vname}_ani_fps = {ani_fps_override}")
                out.append(f"    local {vname}_ani_done = false")

    # Hold-timer locals for any "hold_for" input actions on objects
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
                        out.append(f"    local {timer_var} = 0")

    # Background filename and parallax
    scene_bg = None
    scene_bg_parallax = 1.0
    for comp in scene.components:
        if comp.component_type == "Background":
            img = project.get_image(comp.config.get("image_id", ""))
            if img and img.path:
                scene_bg = _asset_filename(img.path)
                scene_bg_parallax = comp.config.get("parallax", 1.0)
                break

    # Music setup
    for comp in scene.components:
        if comp.component_type == "Music":
            action = comp.config.get("action", "keep")
            if action == "change":
                aud = project.get_audio(comp.config.get("audio_id", ""))
                if aud and aud.path:
                    fname = _asset_filename(aud.path)
                    out.append(f"    if current_music then audio.stop(current_music) end")
                    out.append(f"    current_music = audio_tracks[{_lua_str(fname)}]")
                    out.append(f"    if current_music then audio.play(current_music, true) end")
            elif action == "stop":
                out.append(f"    if current_music then audio.stop(current_music) end")
                out.append(f"    current_music = nil")

    # ── Start screen ─────────────────────────────────────────
    if scene.role == "start":
        out.append("    local chosen = false")
        out.append("    while not chosen do")
        if scene_bg:
            out.append(f'        if images[{_lua_str(scene_bg)}] then images[{_lua_str(scene_bg)}]:display(0, 0) end')
        out.append('        if deff then')
        out.append('            draw.text(62, 452, "Cross: New Game    Triangle: Continue", black, deff)')
        out.append('            draw.text(60, 450, "Cross: New Game    Triangle: Continue", white, deff)')
        out.append('        end')
        out.append("        controls.update()")
        out.append("        if controls.released(SCE_CTRL_START) then os.exit() end")
        out.append("        if controls.released(SCE_CTRL_CROSS) then")
        if project.game_data.save_enabled:
            out.append("            delete_save()")
        out.append(f"            current_scene = {scene_num + 1}")
        out.append("            chosen = true")
        out.append("        elseif controls.released(SCE_CTRL_TRIANGLE) then")
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
        out.append("        draw.swapbuffers()")
        out.append("    end")

    # ── End screen ───────────────────────────────────────────
    elif scene.role == "end":
        if project.game_data.save_enabled:
            out.append("    delete_save()")
        out.append("    local waiting = true")
        out.append("    while waiting do")
        if scene_bg:
            out.append(f'        if images[{_lua_str(scene_bg)}] then images[{_lua_str(scene_bg)}]:display(0, 0) end')
        out.append('        if deff then')
        out.append('            draw.text(62, 262, "--- THE END ---", black, deff)')
        out.append('            draw.text(60, 260, "--- THE END ---", white, deff)')
        out.append('            draw.text(62, 302, "Press START to exit", black, deff)')
        out.append('            draw.text(60, 300, "Press START to exit", white, deff)')
        out.append('        end')
        out.append("        controls.update()")
        out.append("        if controls.released(SCE_CTRL_START) then")
        out.append("            if current_music then audio.stop(current_music) end")
        out.append("            waiting = false")
        out.append("            running = false")
        out.append("        end")
        out.append("        draw.swapbuffers()")
        out.append("    end")

    # ── Normal scene ─────────────────────────────────────────
    else:
        vn_comp = next((c for c in scene.components if c.component_type == "VNDialogBox"), None)

        out.append("    local advance = false")
        if vn_comp and vn_comp.config.get("auto_advance", False):
            out.append("    local auto_advance_timer = 0")
        out.append("    while not advance do")

        # ── Per-frame updates: tweens, camera, shake, animations ─
        out.append("        tween_update()")
        out.append("        camera_update_follow()")
        out.append("        shake_update()")

        # Update animation objects
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
                vname = _safe_name(od.name)
                out.append(f"        -- Update animation: {vname}")
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

        # Background with parallax and camera offset
        if scene_bg:
            out.append(f"        -- Background (parallax={scene_bg_parallax})")
            out.append(f"        local _bg_ox, _bg_oy = camera_bg_offset({scene_bg_parallax})")
            out.append(f'        if images[{_lua_str(scene_bg)}] then images[{_lua_str(scene_bg)}]:display(_bg_ox + shake_offset_x, _bg_oy + shake_offset_y) end')

        # Per-frame object behaviors (movement etc.)
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname = _safe_name(od.name)
                all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
                for beh in all_behaviors:
                    if beh.trigger == "on_frame":
                        for action in beh.actions:
                            for line in _action_to_lua_inline(action, vname):
                                out.append(f"        {line}")

        # SelectionGroup state
        sel_group = next((c for c in scene.components if c.component_type == "SelectionGroup"), None)
        if sel_group:
            sel_ids = sel_group.config.get("selectable_ids", [])
            if sel_ids:
                out.append(f"        local _sel_idx = 1")
                out.append(f"        local _sel_count = {len(sel_ids)}")

        # Draw placed objects
        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if not od:
                continue
            if od.behavior_type == "Camera":
                continue

            vname = _safe_name(od.name)

            if od.behavior_type == "GUI_Panel":
                hx = od.gui_bg_color.lstrip('#')
                pr, pg, pb = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
                out.append(f'        if {vname}_visible then')
                out.append(f'            local _pc = color.new({pr}, {pg}, {pb}, {od.gui_bg_opacity})')
                out.append(f'            draw.gradientrect({vname}_x + shake_offset_x, {vname}_y + shake_offset_y, {od.gui_width}, {od.gui_height}, _pc, _pc, _pc, _pc)')
                out.append(f'        end')

            elif od.behavior_type == "GUI_Label":
                hx = od.gui_text_color.lstrip('#')
                lr, lg, lb = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'
                out.append(f'        if {vname}_visible and {font_var} then')
                out.append(f'            local _lc = color.new({lr}, {lg}, {lb})')
                text = _lua_str(od.gui_text)
                out.append(f'            draw.text({vname}_x + shake_offset_x, {vname}_y + shake_offset_y, {text}, _lc, {font_var})')
                out.append(f'        end')

            elif od.behavior_type == "GUI_Button":
                hx_bg = od.gui_bg_color.lstrip('#')
                br, bg_g, bb = int(hx_bg[0:2],16), int(hx_bg[2:4],16), int(hx_bg[4:6],16)
                hx_tc = od.gui_text_color.lstrip('#')
                tr, tg, tb = int(hx_tc[0:2],16), int(hx_tc[2:4],16), int(hx_tc[4:6],16)
                font_var = "deff"
                if od.gui_font_id:
                    fnt = project.get_font(od.gui_font_id)
                    if fnt and fnt.path:
                        font_var = f'fonts[{_lua_str(_asset_filename(fnt.path))}]'

                out.append(f'        if {vname}_visible then')

                if sel_group:
                    sel_ids = sel_group.config.get("selectable_ids", [])
                    if po.instance_id in sel_ids:
                        btn_sel_idx = sel_ids.index(po.instance_id) + 1
                        hx_hl = od.gui_highlight_color.lstrip('#')
                        hr, hg, hb = int(hx_hl[0:2],16), int(hx_hl[2:4],16), int(hx_hl[4:6],16)
                        out.append(f'            if _sel_idx == {btn_sel_idx} then')
                        out.append(f'                local _hc = color.new({hr}, {hg}, {hb})')
                        out.append(f'                draw.gradientrect({vname}_x - 3 + shake_offset_x, {vname}_y - 3 + shake_offset_y, {od.gui_width + 6}, {od.gui_height + 6}, _hc, _hc, _hc, _hc)')
                        out.append(f'            end')

                bg_img = None
                if od.gui_image_id:
                    bi = project.get_image(od.gui_image_id)
                    if bi and bi.path:
                        bg_img = _asset_filename(bi.path)
                if bg_img:
                    out.append(f'            if images[{_lua_str(bg_img)}] then images[{_lua_str(bg_img)}]:display({vname}_x + shake_offset_x, {vname}_y + shake_offset_y) end')
                else:
                    out.append(f'            local _bc = color.new({br}, {bg_g}, {bb}, {od.gui_bg_opacity})')
                    out.append(f'            draw.gradientrect({vname}_x + shake_offset_x, {vname}_y + shake_offset_y, {od.gui_width}, {od.gui_height}, _bc, _bc, _bc, _bc)')

                if od.gui_text:
                    text = _lua_str(od.gui_text)
                    out.append(f'            if {font_var} then')
                    out.append(f'                local _tc = color.new({tr}, {tg}, {tb})')
                    out.append(f'                draw.text({vname}_x + 8 + shake_offset_x, {vname}_y + 8 + shake_offset_y, {text}, _tc, {font_var})')
                    out.append(f'            end')

                out.append(f'        end')

            elif od.behavior_type == "Animation":
                # Animation object — moves with camera
                if getattr(od, "ani_file_id", ""):
                    out.append(f'        if {vname}_visible then')
                    out.append(f'            local _sx, _sy = world_to_screen({vname}_x, {vname}_y)')
                    out.append(f'            ani_draw({vname}_ani_id, {vname}_ani_frame, _sx + shake_offset_x, _sy + shake_offset_y)')
                    out.append(f'        end')

            else:
                # Default sprite object — these DO move with camera
                if od.frames:
                    img = project.get_image(od.frames[0].image_id) if od.frames[0].image_id else None
                    if img and img.path:
                        fname = _asset_filename(img.path)
                        out.append(f'        if {vname}_visible and images[{_lua_str(fname)}] then')
                        out.append(f'            local _sx, _sy = world_to_screen({vname}_x, {vname}_y)')
                        out.append(f'            images[{_lua_str(fname)}]:display(_sx + shake_offset_x, _sy + shake_offset_y)')
                        out.append(f'        end')

        # VN dialogue (GUI — fixed to screen, affected by shake only)
        if vn_comp:
            cfg = vn_comp.config
            speaker = cfg.get("speaker_name", "")
            lines_raw = cfg.get("lines", [])
            non_empty = [l for l in lines_raw if l.strip()]

            fill = cfg.get("fill_color", "#000000")
            opacity = cfg.get("opacity", 150)
            r, g, b = int(fill[1:3],16), int(fill[3:5],16), int(fill[5:7],16)

            tex_id = cfg.get("texture_image_id")
            if tex_id:
                tex_img = project.get_image(tex_id)
                if tex_img and tex_img.path:
                    fname = _asset_filename(tex_img.path)
                    out.append(f'        if images[{_lua_str(fname)}] then')
                    out.append(f'            images[{_lua_str(fname)}]:blit(40 + shake_offset_x, 335 + shake_offset_y, 0, 0, 880, 200)')
                    out.append(f'        else')
                    out.append(f'            local box_col = color.new({r}, {g}, {b}, {opacity})')
                    out.append(f'            draw.gradientrect(40 + shake_offset_x, 335 + shake_offset_y, 880, 200, box_col, box_col, box_col, box_col)')
                    out.append(f'        end')
            else:
                out.append(f'        local box_col = color.new({r}, {g}, {b}, {opacity})')
                out.append(f'        draw.gradientrect(40 + shake_offset_x, 335 + shake_offset_y, 880, 200, box_col, box_col, box_col, box_col)')

            if cfg.get("border", False):
                bc = cfg.get("border_color", "#ffffff")
                br, bg, bb = int(bc[1:3],16), int(bc[3:5],16), int(bc[5:7],16)
                t = cfg.get("border_thickness", 2)
                out.append(f'        local border_col = color.new({br}, {bg}, {bb})')
                out.append(f'        draw.rect(40 + shake_offset_x, 335 + shake_offset_y, 880, {t}, border_col)')
                out.append(f'        draw.rect(40 + shake_offset_x, {335+200-t} + shake_offset_y, 880, {t}, border_col)')
                out.append(f'        draw.rect(40 + shake_offset_x, 335 + shake_offset_y, {t}, 200, border_col)')
                out.append(f'        draw.rect({40+880-t} + shake_offset_x, 335 + shake_offset_y, {t}, 200, border_col)')

            tc = cfg.get("text_color", "#ffffff")
            tr, tg, tb = int(tc[1:3],16), int(tc[3:5],16), int(tc[5:7],16)
            shadow = cfg.get("shadow", True)
            out.append(f'        local txt_col = color.new({tr}, {tg}, {tb})')

            font_id = cfg.get("font_id")
            font_var = "deff"
            if font_id:
                fnt = project.get_font(font_id)
                if fnt and fnt.path:
                    fname = _asset_filename(fnt.path)
                    font_var = f'fonts[{_lua_str(fname)}]'

            if speaker:
                nametag_pos = cfg.get("nametag_position", "inside box top")
                nc = cfg.get("nametag_color", "#333333")
                nr, ng, nb = int(nc[1:3],16), int(nc[3:5],16), int(nc[5:7],16)
                name_y = 345 if nametag_pos == "inside box top" else 320
                tag_bg_y = name_y - 5
                out.append(f'        local tag_col = color.new({nr}, {ng}, {nb}, 200)')
                out.append(f'        draw.gradientrect(40 + shake_offset_x, {tag_bg_y} + shake_offset_y, 200, 26, tag_col, tag_col, tag_col, tag_col)')
                if shadow:
                    out.append(f'        if {font_var} then draw.text(62 + shake_offset_x, {name_y+2} + shake_offset_y, {_lua_str(speaker)}, black, {font_var}) end')
                out.append(f'        if {font_var} then draw.text(60 + shake_offset_x, {name_y} + shake_offset_y, {_lua_str(speaker)}, txt_col, {font_var}) end')

            line_y = 383
            for ln in non_empty:
                if shadow:
                    out.append(f'        if {font_var} then draw.text(62 + shake_offset_x, {line_y+2} + shake_offset_y, {_lua_str(ln)}, black, {font_var}) end')
                out.append(f'        if {font_var} then draw.text(60 + shake_offset_x, {line_y} + shake_offset_y, {_lua_str(ln)}, txt_col, {font_var}) end')
                line_y += 35

            advance_btn = cfg.get("advance_button", "cross")
            btn_const = {
                "cross": "SCE_CTRL_CROSS", "circle": "SCE_CTRL_CIRCLE",
                "square": "SCE_CTRL_SQUARE", "triangle": "SCE_CTRL_TRIANGLE"
            }.get(advance_btn, "SCE_CTRL_CROSS")

        out.append("        controls.update()")

        out.append("        if controls.released(SCE_CTRL_START) then")
        if project.game_data.save_enabled:
            out.append("            save_progress(current_scene)")
        out.append("            if current_music then audio.stop(current_music) end")
        out.append("            os.exit()")
        out.append("        end")

        if sel_group:
            sel_ids = sel_group.config.get("selectable_ids", [])
            if sel_ids:
                cycle = sel_group.config.get("cycle_buttons", "updown")
                if cycle == "updown":
                    prev_btn, next_btn = "SCE_CTRL_UP", "SCE_CTRL_DOWN"
                else:
                    prev_btn, next_btn = "SCE_CTRL_LEFT", "SCE_CTRL_RIGHT"

                out.append(f"        if controls.released({next_btn}) then")
                out.append(f"            _sel_idx = _sel_idx + 1")
                out.append(f"            if _sel_idx > _sel_count then _sel_idx = 1 end")
                out.append(f"        end")
                out.append(f"        if controls.released({prev_btn}) then")
                out.append(f"            _sel_idx = _sel_idx - 1")
                out.append(f"            if _sel_idx < 1 then _sel_idx = _sel_count end")
                out.append(f"        end")

                confirm = sel_group.config.get("confirm_button", "cross")
                confirm_const = {"cross": "SCE_CTRL_CROSS", "circle": "SCE_CTRL_CIRCLE"}.get(confirm, "SCE_CTRL_CROSS")
                out.append(f"        if controls.released({confirm_const}) then")
                for i, sid in enumerate(sel_ids):
                    po_match = next((p for p in scene.placed_objects if p.instance_id == sid), None)
                    if po_match:
                        od_match = project.get_object_def(po_match.object_def_id)
                        if od_match:
                            vname_m = _safe_name(od_match.name)
                            all_beh = list(od_match.behaviors) + list(po_match.instance_behaviors)
                            interact_actions = []
                            for beh in all_beh:
                                if beh.trigger == "on_interact":
                                    interact_actions.extend(beh.actions)
                            if interact_actions:
                                out.append(f"            if _sel_idx == {i + 1} then")
                                for action in interact_actions:
                                    for line in _action_to_lua_inline(action, vname_m):
                                        out.append(f"                {line}")
                                out.append(f"            end")
                out.append(f"        end")

        for po in scene.placed_objects:
            od = project.get_object_def(po.object_def_id)
            if od and od.behavior_type != "Camera":
                vname = _safe_name(od.name)
                all_behaviors = list(od.behaviors) + list(po.instance_behaviors)
                for beh in all_behaviors:
                    if beh.trigger == "on_input" and getattr(beh, "input_action_name", ""):
                        ia = next((a for a in project.game_data.input_actions
                                   if a.name == beh.input_action_name), None)
                        if ia:
                            btn = _button_constant(ia.button)
                            if ia.event == "hold_for":
                                timer_var = f"_hold_{_safe_name(ia.name)}_timer"
                                frames = int(getattr(ia, "hold_duration", 2.0) * 60)
                                out.append(f"        if controls.held({btn}) then")
                                out.append(f"            {timer_var} = {timer_var} + 1")
                                out.append(f"            if {timer_var} == {frames} then")
                                for action in beh.actions:
                                    for line in _action_to_lua_inline(action, vname):
                                        out.append(f"                {line}")
                                out.append(f"            end")
                                out.append(f"        else")
                                out.append(f"            {timer_var} = 0")
                                out.append(f"        end")
                            else:
                                fn_check = _event_check(ia.event)
                                out.append(f"        if {fn_check}({btn}) then")
                                for action in beh.actions:
                                    for line in _action_to_lua_inline(action, vname):
                                        out.append(f"            {line}")
                                out.append(f"        end")

        if vn_comp is not None:
            cfg = vn_comp.config
            if cfg.get("advance", True):
                btn_const = {
                    "cross": "SCE_CTRL_CROSS", "circle": "SCE_CTRL_CIRCLE",
                    "square": "SCE_CTRL_SQUARE", "triangle": "SCE_CTRL_TRIANGLE"
                }.get(cfg.get("advance_button", "cross"), "SCE_CTRL_CROSS")
                out.append(f"        if controls.released({btn_const}) then")
                out.append(f"            current_scene = current_scene + 1")
                out.append(f"            advance = true")
                out.append(f"        end")
            if cfg.get("auto_advance", False):
                secs = cfg.get("auto_advance_secs", 3.0)
                frames = int(secs * 60)
                out.append(f"        if auto_advance_timer >= {frames} then")
                out.append(f"            current_scene = current_scene + 1")
                out.append(f"            advance = true")
                out.append(f"        end")
                out.append(f"        auto_advance_timer = auto_advance_timer + 1")
        else:
            has_advance = any(
                any(a.action_type in ("go_to_scene", "go_to_next", "go_to_prev") for a in b.actions)
                for b in scene.behaviors
            )
            if not has_advance:
                pass

        out.append("        draw.swapbuffers()")
        out.append("    end")

        # Play transition if scene has Transition component
        trans_comp = next((c for c in scene.components if c.component_type == "Transition"), None)
        if trans_comp:
            trans_id = trans_comp.config.get("trans_file_id", "")
            fps_override = trans_comp.config.get("trans_fps_override", 0)
            if trans_id:
                out.append(f"    -- Play scene transition")
                if fps_override > 0:
                    out.append(f"    play_transition({_lua_str(trans_id)}, {fps_override})")
                else:
                    out.append(f"    play_transition({_lua_str(trans_id)}, nil)")

    out.append("end")
    out.append("")
    return out


# ─────────────────────────────────────────────────────────────
#  MAIN EXPORT ENTRY POINT
# ─────────────────────────────────────────────────────────────

def export_main_lua(project: Project) -> str:
    out = []

    # Header
    out.append("-- =====================================================")
    out.append(f"-- {project.title}")
    out.append(f"-- Title ID : {project.title_id}")
    out.append(f"-- Author   : {project.author}")
    out.append(f"-- Version  : {project.version}")
    out.append("-- Generated by Vita Adventure Creator")
    out.append("-- =====================================================")
    out.append("")

    # ── Tween system ─────────────────────────────────────────
    out.append("-- ─── TWEEN SYSTEM ──────────────────────────────────────")
    out.append("local tweens = {}")
    out.append("")
    out.append("local function ease_linear(t) return t end")
    out.append("local function ease_in(t) return t * t end")
    out.append("local function ease_out(t) return 1 - (1 - t) * (1 - t) end")
    out.append("local function ease_in_out(t)")
    out.append("    if t < 0.5 then return 2 * t * t")
    out.append("    else return 1 - 2 * (1 - t) * (1 - t) end")
    out.append("end")
    out.append("")
    out.append("local easing_funcs = {")
    out.append("    linear = ease_linear,")
    out.append("    ease_in = ease_in,")
    out.append("    ease_out = ease_out,")
    out.append("    ease_in_out = ease_in_out")
    out.append("}")
    out.append("")
    out.append("local function tween_add(id, target_table, key, target_value, duration_frames, easing)")
    out.append("    tweens[id] = {")
    out.append("        target = target_table,")
    out.append("        key = key,")
    out.append("        start_value = target_table[key],")
    out.append("        end_value = target_value,")
    out.append("        duration = duration_frames,")
    out.append("        elapsed = 0,")
    out.append("        easing = easing_funcs[easing] or ease_linear")
    out.append("    }")
    out.append("end")
    out.append("")
    out.append("local function tween_update()")
    out.append("    for id, tw in pairs(tweens) do")
    out.append("        tw.elapsed = tw.elapsed + 1")
    out.append("        local t = tw.elapsed / tw.duration")
    out.append("        if t >= 1 then")
    out.append("            tw.target[tw.key] = tw.end_value")
    out.append("            tweens[id] = nil")
    out.append("        else")
    out.append("            local eased = tw.easing(t)")
    out.append("            tw.target[tw.key] = tw.start_value + (tw.end_value - tw.start_value) * eased")
    out.append("        end")
    out.append("    end")
    out.append("end")
    out.append("")

    # ── Camera system ────────────────────────────────────────
    out.append("-- ─── CAMERA ────────────────────────────────────────────")
    out.append("local camera = {")
    out.append("    x = 480,")
    out.append("    y = 272,")
    out.append("    bounds_enabled = false,")
    out.append("    bounds_width = 960,")
    out.append("    bounds_height = 544,")
    out.append("    follow_target = nil,")
    out.append("    follow_offset_x = 0,")
    out.append("    follow_offset_y = 0,")
    out.append("    follow_lag = 0")
    out.append("}")
    out.append("")
    out.append("local function camera_reset_state()")
    out.append("    camera.x = 480")
    out.append("    camera.y = 272")
    out.append("    camera.bounds_enabled = false")
    out.append("    camera.bounds_width = 960")
    out.append("    camera.bounds_height = 544")
    out.append("    camera.follow_target = nil")
    out.append("    camera.follow_offset_x = 0")
    out.append("    camera.follow_offset_y = 0")
    out.append("    camera.follow_lag = 0")
    out.append("end")
    out.append("")
    out.append("local function world_to_screen(wx, wy)")
    out.append("    local sx = wx - camera.x + 480")
    out.append("    local sy = wy - camera.y + 272")
    out.append("    return sx, sy")
    out.append("end")
    out.append("")
    out.append("local function camera_bg_offset(parallax)")
    out.append("    local ox = -(camera.x - 480) * parallax")
    out.append("    local oy = -(camera.y - 272) * parallax")
    out.append("    return ox, oy")
    out.append("end")
    out.append("")
    out.append("local function camera_apply_bounds()")
    out.append("    if not camera.bounds_enabled then return end")
    out.append("    local half_w = 480")
    out.append("    local half_h = 272")
    out.append("    if camera.x < half_w then camera.x = half_w end")
    out.append("    if camera.y < half_h then camera.y = half_h end")
    out.append("    if camera.x > camera.bounds_width - half_w then camera.x = camera.bounds_width - half_w end")
    out.append("    if camera.y > camera.bounds_height - half_h then camera.y = camera.bounds_height - half_h end")
    out.append("end")
    out.append("")
    out.append("local function camera_update_follow()")
    out.append("    if not camera.follow_target then return end")
    out.append("    local tx = _G[camera.follow_target .. '_x']")
    out.append("    local ty = _G[camera.follow_target .. '_y']")
    out.append("    if tx == nil or ty == nil then return end")
    out.append("    tx = tx + camera.follow_offset_x")
    out.append("    ty = ty + camera.follow_offset_y")
    out.append("    if camera.follow_lag <= 0 then")
    out.append("        camera.x = tx")
    out.append("        camera.y = ty")
    out.append("    else")
    out.append("        camera.x = camera.x + (tx - camera.x) * (1 - camera.follow_lag)")
    out.append("        camera.y = camera.y + (ty - camera.y) * (1 - camera.follow_lag)")
    out.append("    end")
    out.append("    camera_apply_bounds()")
    out.append("end")
    out.append("")

    # ── Animation system ─────────────────────────────────────
    out.append("-- ─── ANIMATION SYSTEM ──────────────────────────────────")
    out.append("local ani_data = {}")
    out.append("local ani_sheets = {}")
    out.append("local trans_data = {}")
    out.append("local trans_sheets = {}")
    out.append("")
    out.append("local function ani_get_frame_quad(ani_id, frame)")
    out.append("    local data = ani_data[ani_id]")
    out.append("    if not data then return 0, 0, 64, 64 end")
    out.append("    local cols = math.floor(data.sheet_width / data.frame_width)")
    out.append("    if cols < 1 then cols = 1 end")
    out.append("    local col = frame % cols")
    out.append("    local row = math.floor(frame / cols)")
    out.append("    local sx = col * data.frame_width")
    out.append("    local sy = row * data.frame_height")
    out.append("    return sx, sy, data.frame_width, data.frame_height")
    out.append("end")
    out.append("")
    out.append("local function ani_draw(ani_id, frame, x, y)")
    out.append("    local sheet = ani_sheets[ani_id]")
    out.append("    if not sheet then return end")
    out.append("    local sx, sy, sw, sh = ani_get_frame_quad(ani_id, frame)")
    out.append("    sheet:blit(x, y, sx, sy, sw, sh)")
    out.append("end")
    out.append("")
    out.append("local function trans_draw_frame(trans_id, frame)")
    out.append("    local sheet = trans_sheets[trans_id]")
    out.append("    local data = trans_data[trans_id]")
    out.append("    if not sheet or not data then return end")
    out.append("    local cols = math.floor(data.sheet_width / 960)")
    out.append("    if cols < 1 then cols = 1 end")
    out.append("    local col = frame % cols")
    out.append("    local row = math.floor(frame / cols)")
    out.append("    local sx = col * 960")
    out.append("    local sy = row * 544")
    out.append("    sheet:blit(0, 0, sx, sy, 960, 544)")
    out.append("end")
    out.append("")
    out.append("local function play_transition(trans_id, fps_override)")
    out.append("    local data = trans_data[trans_id]")
    out.append("    if not data then return end")
    out.append("    local fps = fps_override or data.fps or 12")
    out.append("    local frame_delay = math.floor(60 / fps)")
    out.append("    if frame_delay < 1 then frame_delay = 1 end")
    out.append("    local frame = 0")
    out.append("    local timer = 0")
    out.append("    while frame < data.frame_count do")
    out.append("        trans_draw_frame(trans_id, frame)")
    out.append("        draw.swapbuffers()")
    out.append("        timer = timer + 1")
    out.append("        if timer >= frame_delay then")
    out.append("            timer = 0")
    out.append("            frame = frame + 1")
    out.append("        end")
    out.append("    end")
    out.append("end")
    out.append("")

    # ── Screen shake ─────────────────────────────────────────
    out.append("-- ─── SCREEN SHAKE ──────────────────────────────────────")
    out.append("local shake_intensity = 0")
    out.append("local shake_timer = 0")
    out.append("local shake_offset_x = 0")
    out.append("local shake_offset_y = 0")
    out.append("")
    out.append("local function shake_update()")
    out.append("    if shake_timer > 0 then")
    out.append("        shake_offset_x = math.random(-shake_intensity, shake_intensity)")
    out.append("        shake_offset_y = math.random(-shake_intensity, shake_intensity)")
    out.append("        shake_timer = shake_timer - 1")
    out.append("    else")
    out.append("        shake_offset_x = 0")
    out.append("        shake_offset_y = 0")
    out.append("    end")
    out.append("end")
    out.append("")

    # Save system
    if project.game_data.save_enabled:
        save_path = f"ux0:data/{project.title_id}_save.dat"
        out.append("-- ─── SAVE SYSTEM ───────────────────────────────────────")
        out.append(f'local SAVE_PATH = "{save_path}"')
        out.append("local function save_progress(scene_num)")
        out.append("    local f = io.open(SAVE_PATH, \"w\")")
        out.append("    if f then f:write(tostring(scene_num)); f:close() end")
        out.append("end")
        out.append("local function load_progress()")
        out.append("    local f = io.open(SAVE_PATH, \"r\")")
        out.append("    if f then local val = tonumber(f:read(\"*n\")); f:close(); return val end")
        out.append("    return nil")
        out.append("end")
        out.append("local function delete_save() os.remove(SAVE_PATH) end")
        out.append("")

    # Fonts and colors
    out.append("-- ─── ASSETS ─────────────────────────────────────────────")
    out.append('deff     = font.load("app0:font.ttf")')
    out.append('psexchar = font.load("sa0:data/font/pvf/psexchar.pvf")')
    out.append("white  = color.new(255, 255, 255)")
    out.append("black  = color.new(0, 0, 0)")
    out.append("box_bg = color.new(0, 0, 0, 150)")
    out.append("")

    # Collect animation files (.ani)
    ani_files = []
    for od in project.object_defs:
        if od.behavior_type == "Animation" and getattr(od, "ani_file_id", ""):
            ani_files.append(od.ani_file_id)
    ani_files = list(set(ani_files))

    # Collect transition files (.trans)
    trans_files = []
    for scene in project.scenes:
        for comp in scene.components:
            if comp.component_type == "Transition":
                tid = comp.config.get("trans_file_id", "")
                if tid:
                    trans_files.append(tid)
    trans_files = list(set(trans_files))

    # Load .ani metadata and spritesheets
    if ani_files:
        out.append("-- Load animation files")
        for ani_id in sorted(ani_files):
            ani_obj = project.get_animation_export(ani_id) if hasattr(project, 'get_animation_export') else None
            if ani_obj:
                out.append(f'ani_data[{_lua_str(ani_id)}] = {{')
                out.append(f'    frame_count = {ani_obj.frame_count},')
                out.append(f'    frame_width = {ani_obj.frame_width},')
                out.append(f'    frame_height = {ani_obj.frame_height},')
                out.append(f'    sheet_width = {ani_obj.sheet_width},')
                out.append(f'    sheet_height = {ani_obj.sheet_height},')
                out.append(f'    fps = {ani_obj.fps}')
                out.append(f'}}')
                sheet_name = _asset_filename(ani_obj.spritesheet_path)
                out.append(f'ani_sheets[{_lua_str(ani_id)}] = image.load("app0:{sheet_name}")')
        out.append("")

    # Load .trans metadata and spritesheets
    if trans_files:
        out.append("-- Load transition files")
        for trans_id in sorted(trans_files):
            trans_obj = project.get_transition_export(trans_id) if hasattr(project, 'get_transition_export') else None
            if trans_obj:
                out.append(f'trans_data[{_lua_str(trans_id)}] = {{')
                out.append(f'    frame_count = {trans_obj.frame_count},')
                out.append(f'    sheet_width = {trans_obj.sheet_width},')
                out.append(f'    sheet_height = {trans_obj.sheet_height},')
                out.append(f'    fps = {trans_obj.fps}')
                out.append(f'}}')
                sheet_name = _asset_filename(trans_obj.spritesheet_path)
                out.append(f'trans_sheets[{_lua_str(trans_id)}] = image.load("app0:{sheet_name}")')
        out.append("")

    # Collect all unique image filenames
    all_image_paths = set()
    for scene in project.scenes:
        for comp in scene.components:
            if comp.component_type in ("Background", "Foreground"):
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

    out.append("images = {}")
    for path in sorted(all_image_paths):
        fname = _asset_filename(path)
        out.append(f'images[{_lua_str(fname)}] = image.load("app0:{fname}")')
    out.append("")

    # Fonts (registered fonts beyond the default)
    if project.fonts:
        out.append("fonts = {}")
        for fnt in project.fonts:
            if fnt.path:
                fname = _asset_filename(fnt.path)
                out.append(f'fonts[{_lua_str(fname)}] = font.load("app0:{fname}")')
        out.append("")

    # Audio
    all_audio_paths = set()
    for aud in project.audio:
        if aud.path:
            all_audio_paths.add(aud.path)
    if all_audio_paths:
        out.append("audio_tracks = {}")
        for path in sorted(all_audio_paths):
            fname = _asset_filename(path)
            out.append(f'audio_tracks[{_lua_str(fname)}] = audio.load("app0:{fname}")')
        out.append("")

    # Global state
    out.append("-- ─── STATE ──────────────────────────────────────────────")
    out.append("current_scene = 1")
    out.append("current_music = nil")
    out.append("running       = true")
    out.append("")

    # Variables
    if project.game_data.variables:
        out.append("-- ─── VARIABLES ─────────────────────────────────────────")
        for v in project.game_data.variables:
            if v.var_type == "string":
                default = _lua_str(str(v.default_value))
            elif v.var_type == "bool":
                default = _lua_bool(bool(v.default_value))
            else:
                default = str(v.default_value) if v.default_value else "0"
            out.append(f"{_safe_name(v.name)} = {default}")
        out.append("")

    # Scene functions
    out.append("-- ─── SCENES ─────────────────────────────────────────────")
    out.append("")
    for si, scene in enumerate(project.scenes):
        out.extend(_scene_to_lua(scene, si + 1, project))

    # Main loop
    out.append("-- ─── MAIN LOOP ──────────────────────────────────────────")
    out.append("while running do")
    for si, scene in enumerate(project.scenes):
        scene_num = si + 1
        prefix = "    if" if si == 0 else "    elseif"
        out.append(f"{prefix} current_scene == {scene_num} then scene_{scene_num}()")
    out.append("    else")
    out.append("        running = false")
    out.append("    end")
    out.append("end")
    out.append("")
    out.append("if current_music then audio.stop(current_music) end")
    out.append("os.exit()")
    out.append("")

    return "\n".join(out)
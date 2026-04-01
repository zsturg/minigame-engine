from __future__ import annotations


def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}


def _safe_ident(name: str, fallback: str) -> str:
    out = []
    for char in str(name or ""):
        out.append(char if char.isalnum() or char == "_" else "_")
    text = "".join(out) or fallback
    if text[0].isdigit():
        text = "_" + text
    return text


def _lua_str(value: str) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _handle_expr(object_id: str, obj_var: str | None) -> str:
    if object_id:
        return f"prim.handle_for_object({_lua_str(object_id)})"
    if obj_var:
        return f"prim.handle_from_var({_lua_str(obj_var)})"
    return "nil"


def _filter_expr(data: dict) -> str:
    parts: list[str] = []
    object_id = str(data.get("filter_object_id", "") or "")
    group_name = str(data.get("group_name", "") or "")
    object_kind = str(data.get("object_kind", "any") or "any")
    tag = str(data.get("tag", "") or "")
    if object_id:
        parts.append(f"def_id = {_lua_str(object_id)}")
    if group_name:
        parts.append(f"group_name = {_lua_str(group_name)}")
    if object_kind and object_kind != "any":
        parts.append(f"kind = {_lua_str(object_kind)}")
    if tag:
        parts.append(f"tag = {_lua_str(tag)}")
    return "{ " + ", ".join(parts) + " }" if parts else "{}"


def _tags_expr(tag_text: str) -> str:
    tags = [part.strip() for part in str(tag_text or "").split(",") if part.strip()]
    if not tags:
        return "{}"
    inner = ", ".join(f"[{_lua_str(tag)}] = true" for tag in tags)
    return "{ " + inner + " }"


def _emit_nested_actions(actions, obj_var, project):
    from lpp_exporter import _action_to_lua_inline

    lines: list[str] = []
    for action in actions or []:
        for line in _action_to_lua_inline(action, obj_var, project):
            lines.append(str(line))
    return lines


def _spawn_lines(data: dict, obj_var: str | None, result_var: str | None) -> list[str]:
    spawn_def_id = str(data.get("spawn_object_id", "") or "")
    position_mode = str(data.get("position_mode", "self") or "self")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    target_expr = _handle_expr(str(data.get("target_object_id", "") or ""), None)
    x = float(data.get("spawn_x", 0) or 0)
    y = float(data.get("spawn_y", 0) or 0)
    offset_x = float(data.get("offset_x", 0) or 0)
    offset_y = float(data.get("offset_y", 0) or 0)
    angle = float(data.get("angle", 0) or 0)
    speed = float(data.get("speed", 0) or 0)
    tags_expr = _tags_expr(str(data.get("tags", "") or ""))
    store_var = result_var or "_spawned_handle"
    lines = [
        "do",
        f"    local _source_handle = {source_expr}",
        f"    local _target_handle = {target_expr}",
        f"    local _spawned = prim.spawn_object({_lua_str(spawn_def_id)}, {{"
        f"position_mode = {_lua_str(position_mode)}, "
        f"source_handle = _source_handle, "
        f"target_handle = _target_handle, "
        f"x = {x}, y = {y}, offset_x = {offset_x}, offset_y = {offset_y}, "
        f"angle = {angle}, rotation = {angle}, tags = {tags_expr}"
        f"}})",
        "    if _spawned then",
        f"        prim.set_velocity_polar(_spawned, {angle}, {speed})",
        "    end",
        f"    {store_var} = _spawned or \"\"",
        "end",
    ]
    return lines


def _center_lines(data: dict, obj_var: str | None) -> tuple[list[str], str, str]:
    center_mode = str(data.get("center_mode", "self") or "self")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    center_x = float(data.get("center_x", 0) or 0)
    center_y = float(data.get("center_y", 0) or 0)
    lines = [
        "do",
        f"    local _center_handle = {source_expr}",
    ]
    if center_mode == "self":
        lines.extend(
            [
                "    local _cx = _center_handle and prim.get_x(_center_handle) or 0",
                "    local _cy = _center_handle and prim.get_y(_center_handle) or 0",
            ]
        )
    else:
        lines.extend(
            [
                f"    local _cx = {center_x}",
                f"    local _cy = {center_y}",
            ]
        )
    return lines, "_cx", "_cy"


def _spawn_object_advanced_export(action, obj_var, project):
    data = _action_data(action, "prim_spawn_object_advanced")
    result_var = _safe_ident(data.get("result_var", "spawned_object"), "spawned_object")
    return _spawn_lines(data, obj_var, result_var)


def _set_velocity_polar_export(action, obj_var, project):
    data = _action_data(action, "prim_set_velocity_polar")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    angle = float(data.get("angle", 0) or 0)
    speed = float(data.get("speed", 0) or 0)
    return [
        "do",
        f"    local _source_handle = {source_expr}",
        "    if _source_handle then",
        f"        prim.set_velocity_polar(_source_handle, {angle}, {speed})",
        "    end",
        "end",
    ]


def _spray_projectiles_export(action, obj_var, project):
    data = _action_data(action, "prim_spray_projectiles")
    result_var = _safe_ident(data.get("result_var", "spawned_projectiles"), "spawned_projectiles")
    pattern_mode = str(data.get("pattern_mode", "spray") or "spray")
    count = int(data.get("count", 6) or 1)
    center_angle = float(data.get("center_angle", 0) or 0)
    spread_angle = float(data.get("spread_angle", 45) or 0)
    start_angle = float(data.get("start_angle", 0) or 0)
    spawn_lines = [
        "do",
        f"    {result_var} = {{}}",
        f"    local _angles = prim.spray_pattern({count}, {center_angle}, {spread_angle})",
    ]
    if pattern_mode == "radial":
        spawn_lines[2] = f"    local _angles = prim.radial_pattern({count}, {start_angle})"
    elif pattern_mode == "cone":
        spawn_lines[2] = f"    local _angles = prim.cone_pattern({count}, {center_angle}, {spread_angle})"
    spawn_lines.append("    for _pi = 1, #_angles do")
    spawn_lines.extend("        " + line for line in _spawn_lines(data, obj_var, "_spawned_handle"))
    spawn_lines.append("        if _spawned_handle ~= \"\" then")
    spawn_lines.append("            prim.set_velocity_polar(_spawned_handle, _angles[_pi], " + str(float(data.get("speed", 6.0) or 0)) + ")")
    spawn_lines.append(f"            {result_var}[#{result_var} + 1] = _spawned_handle")
    spawn_lines.append("        end")
    spawn_lines.append("    end")
    spawn_lines.append("end")
    return spawn_lines


def _query_objects_in_radius_export(action, obj_var, project):
    data = _action_data(action, "prim_query_objects_in_radius")
    result_var = _safe_ident(data.get("result_var", "query_results"), "query_results")
    radius = float(data.get("radius", 96) or 0)
    lines, cx, cy = _center_lines(data, obj_var)
    lines.append(f"    {result_var} = prim.query_in_radius({cx}, {cy}, {radius}, {_filter_expr(data)})")
    lines.append("end")
    return lines


def _query_objects_in_rectangle_export(action, obj_var, project):
    data = _action_data(action, "prim_query_objects_in_rectangle")
    result_var = _safe_ident(data.get("result_var", "query_results"), "query_results")
    x = float(data.get("rect_x", 0) or 0)
    y = float(data.get("rect_y", 0) or 0)
    width = float(data.get("rect_w", 64) or 0)
    height = float(data.get("rect_h", 64) or 0)
    return [f"{result_var} = prim.query_in_rect({x}, {y}, {width}, {height}, {_filter_expr(data)})"]


def _if_any_objects_in_radius_export(action, obj_var, project):
    data = _action_data(action, "prim_if_any_objects_in_radius")
    radius = float(data.get("radius", 96) or 0)
    lines, cx, cy = _center_lines(data, obj_var)
    lines.append(f"    if prim.any_in_radius({cx}, {cy}, {radius}, {_filter_expr(data)}) then")
    for line in _emit_nested_actions(action.true_actions, obj_var, project):
        lines.append(f"        {line}")
    if action.false_actions:
        lines.append("    else")
        for line in _emit_nested_actions(action.false_actions, obj_var, project):
            lines.append(f"        {line}")
    lines.append("    end")
    lines.append("end")
    return lines


def _for_each_queried_object_export(action, obj_var, project):
    data = _action_data(action, "prim_for_each_queried_object")
    query_var = _safe_ident(data.get("query_var", "query_results"), "query_results")
    handle_var = _safe_ident(data.get("handle_var", "queried_handle"), "queried_handle")
    lines = [
        f"for _qi = 1, #({query_var} or {{}}) do",
        f"    {handle_var} = {query_var}[_qi]",
    ]
    for line in _emit_nested_actions(action.sub_actions, obj_var, project):
        lines.append(f"    {line}")
    lines.append("end")
    return lines


def _destroy_objects_in_radius_export(action, obj_var, project):
    data = _action_data(action, "prim_destroy_objects_in_radius")
    radius = float(data.get("radius", 96) or 0)
    lines, cx, cy = _center_lines(data, obj_var)
    lines.append(f"    prim.destroy_handles(prim.query_in_radius({cx}, {cy}, {radius}, {_filter_expr(data)}))")
    lines.append("end")
    return lines


PLUGIN = {
    "name": "Built-in Combat Pack",
    "actions": [
        {
            "key": "prim_spawn_object_advanced",
            "label": "Spawn Object Advanced",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "spawn_object_id", "type": "object", "label": "Spawn Object", "default": ""},
                {"key": "position_mode", "type": "combo", "label": "Spawn At", "options": ["self", "target", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "target_object_id", "type": "object", "label": "Target Object", "default": ""},
                {"key": "spawn_x", "type": "float", "label": "X", "default": 0.0, "step": 1.0},
                {"key": "spawn_y", "type": "float", "label": "Y", "default": 0.0, "step": 1.0},
                {"key": "offset_x", "type": "float", "label": "Offset X", "default": 0.0, "step": 1.0},
                {"key": "offset_y", "type": "float", "label": "Offset Y", "default": 0.0, "step": 1.0},
                {"key": "angle", "type": "float", "label": "Angle", "default": 0.0, "step": 1.0},
                {"key": "speed", "type": "float", "label": "Speed", "default": 0.0, "step": 0.25},
                {"key": "tags", "type": "str", "label": "Tags (CSV)", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "spawned_object"},
            ],
            "lua_export": _spawn_object_advanced_export,
        },
        {
            "key": "prim_set_velocity_polar",
            "label": "Set Velocity Polar",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "source_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "angle", "type": "float", "label": "Angle", "default": 0.0, "step": 1.0},
                {"key": "speed", "type": "float", "label": "Speed", "default": 6.0, "step": 0.25},
            ],
            "lua_export": _set_velocity_polar_export,
        },
        {
            "key": "prim_spray_projectiles",
            "label": "Spray Projectiles",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "spawn_object_id", "type": "object", "label": "Spawn Object", "default": ""},
                {"key": "position_mode", "type": "combo", "label": "Spawn At", "options": ["self", "target", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "target_object_id", "type": "object", "label": "Target Object", "default": ""},
                {"key": "spawn_x", "type": "float", "label": "X", "default": 0.0, "step": 1.0},
                {"key": "spawn_y", "type": "float", "label": "Y", "default": 0.0, "step": 1.0},
                {"key": "offset_x", "type": "float", "label": "Offset X", "default": 0.0, "step": 1.0},
                {"key": "offset_y", "type": "float", "label": "Offset Y", "default": 0.0, "step": 1.0},
                {"key": "pattern_mode", "type": "combo", "label": "Pattern", "options": ["spray", "cone", "radial"], "default": "spray"},
                {"key": "count", "type": "int", "label": "Count", "default": 6, "min": 1, "max": 512},
                {"key": "center_angle", "type": "float", "label": "Center Angle", "default": 0.0, "step": 1.0},
                {"key": "spread_angle", "type": "float", "label": "Spread Angle", "default": 45.0, "step": 1.0},
                {"key": "start_angle", "type": "float", "label": "Start Angle", "default": 0.0, "step": 1.0},
                {"key": "speed", "type": "float", "label": "Speed", "default": 6.0, "step": 0.25},
                {"key": "tags", "type": "str", "label": "Tags (CSV)", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "spawned_projectiles"},
            ],
            "lua_export": _spray_projectiles_export,
        },
        {
            "key": "prim_query_objects_in_radius",
            "label": "Query Objects In Radius",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "center_mode", "type": "combo", "label": "Center", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Center Object", "default": ""},
                {"key": "center_x", "type": "float", "label": "Center X", "default": 0.0, "step": 1.0},
                {"key": "center_y", "type": "float", "label": "Center Y", "default": 0.0, "step": 1.0},
                {"key": "radius", "type": "float", "label": "Radius", "default": 96.0, "step": 1.0},
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "query_results"},
            ],
            "lua_export": _query_objects_in_radius_export,
        },
        {
            "key": "prim_query_objects_in_rectangle",
            "label": "Query Objects In Rectangle",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "rect_x", "type": "float", "label": "X", "default": 0.0, "step": 1.0},
                {"key": "rect_y", "type": "float", "label": "Y", "default": 0.0, "step": 1.0},
                {"key": "rect_w", "type": "float", "label": "Width", "default": 64.0, "step": 1.0},
                {"key": "rect_h", "type": "float", "label": "Height", "default": 64.0, "step": 1.0},
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "query_results"},
            ],
            "lua_export": _query_objects_in_rectangle_export,
        },
        {
            "key": "prim_if_any_objects_in_radius",
            "label": "If Any Objects In Radius",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "center_mode", "type": "combo", "label": "Center", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Center Object", "default": ""},
                {"key": "center_x", "type": "float", "label": "Center X", "default": 0.0, "step": 1.0},
                {"key": "center_y", "type": "float", "label": "Center Y", "default": 0.0, "step": 1.0},
                {"key": "radius", "type": "float", "label": "Radius", "default": 96.0, "step": 1.0},
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
            ],
            "has_branches": True,
            "lua_export": _if_any_objects_in_radius_export,
        },
        {
            "key": "prim_for_each_queried_object",
            "label": "For Each Queried Object",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "query_var", "type": "str", "label": "Query Variable", "default": "query_results"},
                {"key": "handle_var", "type": "str", "label": "Handle Variable", "default": "queried_handle"},
            ],
            "has_loop_body": True,
            "lua_export": _for_each_queried_object_export,
        },
        {
            "key": "prim_destroy_objects_in_radius",
            "label": "Destroy Objects In Radius",
            "category": "Engine Primitives/Combat",
            "fields": [
                {"key": "center_mode", "type": "combo", "label": "Center", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Center Object", "default": ""},
                {"key": "center_x", "type": "float", "label": "Center X", "default": 0.0, "step": 1.0},
                {"key": "center_y", "type": "float", "label": "Center Y", "default": 0.0, "step": 1.0},
                {"key": "radius", "type": "float", "label": "Radius", "default": 96.0, "step": 1.0},
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
            ],
            "lua_export": _destroy_objects_in_radius_export,
        },
    ],
}

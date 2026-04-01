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


def _find_object_export(action, obj_var, project):
    data = _action_data(action, "prim_find_object")
    result_var = _safe_ident(data.get("result_var", "found_object"), "found_object")
    return [f"{result_var} = prim.find_object({_filter_expr(data)}) or \"\""]


def _find_nearest_object_export(action, obj_var, project):
    data = _action_data(action, "prim_find_nearest_object")
    result_var = _safe_ident(data.get("result_var", "nearest_object"), "nearest_object")
    distance_var = _safe_ident(data.get("distance_var", "nearest_distance"), "nearest_distance")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    lines = [
        "do",
        f"    local _source_handle = {source_expr}",
        "    if _source_handle then",
        f"        local _found, _dist = prim.find_nearest(_source_handle, {_filter_expr(data)})",
        f"        {result_var} = _found or \"\"",
        f"        {distance_var} = _dist or 0",
        "    else",
        f"        {result_var} = \"\"",
        f"        {distance_var} = 0",
        "    end",
        "end",
    ]
    return lines


def _count_objects_export(action, obj_var, project):
    data = _action_data(action, "prim_count_objects")
    result_var = _safe_ident(data.get("result_var", "object_count"), "object_count")
    return [f"{result_var} = prim.count_objects({_filter_expr(data)})"]


def _get_distance_export(action, obj_var, project):
    data = _action_data(action, "prim_get_distance")
    result_var = _safe_ident(data.get("result_var", "distance_value"), "distance_value")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    target_expr = _handle_expr(str(data.get("target_object_id", "") or ""), None)
    lines = [
        "do",
        f"    local _source_handle = {source_expr}",
        f"    local _target_handle = {target_expr}",
        "    if _source_handle and _target_handle then",
        f"        {result_var} = prim.distance_handles(_source_handle, _target_handle)",
        "    else",
        f"        {result_var} = 0",
        "    end",
        "end",
    ]
    return lines


def _get_angle_export(action, obj_var, project):
    data = _action_data(action, "prim_get_angle_to_object")
    result_var = _safe_ident(data.get("result_var", "angle_value"), "angle_value")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    target_expr = _handle_expr(str(data.get("target_object_id", "") or ""), None)
    lines = [
        "do",
        f"    local _source_handle = {source_expr}",
        f"    local _target_handle = {target_expr}",
        "    if _source_handle and _target_handle then",
        f"        {result_var} = prim.angle_handles(_source_handle, _target_handle)",
        "    else",
        f"        {result_var} = 0",
        "    end",
        "end",
    ]
    return lines


def _set_velocity_toward_export(action, obj_var, project):
    data = _action_data(action, "prim_set_velocity_toward_target")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    target_expr = _handle_expr(str(data.get("target_object_id", "") or ""), None)
    speed = float(data.get("speed", 4.0) or 0)
    lines = [
        "do",
        f"    local _source_handle = {source_expr}",
        f"    local _target_handle = {target_expr}",
        "    if _source_handle and _target_handle then",
        f"        prim.set_velocity_toward(_source_handle, prim.get_x(_target_handle), prim.get_y(_target_handle), {speed})",
        "    end",
        "end",
    ]
    return lines


def _random_integer_export(action, obj_var, project):
    data = _action_data(action, "prim_random_integer")
    result_var = _safe_ident(data.get("result_var", "random_int"), "random_int")
    minimum = int(data.get("minimum", 0) or 0)
    maximum = int(data.get("maximum", 10) or 0)
    return [f"{result_var} = prim.random_int({minimum}, {maximum})"]


def _random_float_export(action, obj_var, project):
    data = _action_data(action, "prim_random_float")
    result_var = _safe_ident(data.get("result_var", "random_float"), "random_float")
    minimum = float(data.get("minimum", 0.0) or 0.0)
    maximum = float(data.get("maximum", 1.0) or 0.0)
    return [f"{result_var} = prim.random_float({minimum}, {maximum})"]


PLUGIN = {
    "name": "Built-in Core Pack",
    "actions": [
        {
            "key": "prim_find_object",
            "label": "Find Object",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "found_object"},
            ],
            "lua_export": _find_object_export,
        },
        {
            "key": "prim_find_nearest_object",
            "label": "Find Nearest Object",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "nearest_object"},
                {"key": "distance_var", "type": "str", "label": "Distance Variable", "default": "nearest_distance"},
            ],
            "lua_export": _find_nearest_object_export,
        },
        {
            "key": "prim_count_objects",
            "label": "Count Objects",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "filter_object_id", "type": "object", "label": "Object", "default": ""},
                {"key": "group_name", "type": "str", "label": "Group", "default": ""},
                {"key": "object_kind", "type": "combo", "label": "Kind", "options": ["any", "placed", "spawned"], "default": "any"},
                {"key": "tag", "type": "str", "label": "Tag", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "object_count"},
            ],
            "lua_export": _count_objects_export,
        },
        {
            "key": "prim_get_distance",
            "label": "Get Distance",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "target_object_id", "type": "object", "label": "Target Object", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "distance_value"},
            ],
            "lua_export": _get_distance_export,
        },
        {
            "key": "prim_get_angle_to_object",
            "label": "Get Angle To Object",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "target_object_id", "type": "object", "label": "Target Object", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "angle_value"},
            ],
            "lua_export": _get_angle_export,
        },
        {
            "key": "prim_set_velocity_toward_target",
            "label": "Set Velocity Toward Target",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "target_object_id", "type": "object", "label": "Target Object", "default": ""},
                {"key": "speed", "type": "float", "label": "Speed", "default": 4.0, "min": -1000.0, "max": 1000.0, "step": 0.25},
            ],
            "lua_export": _set_velocity_toward_export,
        },
        {
            "key": "prim_random_integer",
            "label": "Random Integer",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "minimum", "type": "int", "label": "Minimum", "default": 0, "min": -999999, "max": 999999},
                {"key": "maximum", "type": "int", "label": "Maximum", "default": 10, "min": -999999, "max": 999999},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "random_int"},
            ],
            "lua_export": _random_integer_export,
        },
        {
            "key": "prim_random_float",
            "label": "Random Float",
            "category": "Engine Primitives/Core",
            "fields": [
                {"key": "minimum", "type": "float", "label": "Minimum", "default": 0.0, "min": -999999.0, "max": 999999.0, "step": 0.1},
                {"key": "maximum", "type": "float", "label": "Maximum", "default": 1.0, "min": -999999.0, "max": 999999.0, "step": 0.1},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "random_float"},
            ],
            "lua_export": _random_float_export,
        },
    ],
}

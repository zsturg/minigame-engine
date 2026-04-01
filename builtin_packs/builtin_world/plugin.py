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


def _position_lines(data: dict, obj_var: str | None) -> tuple[list[str], str, str]:
    source_mode = str(data.get("source_mode", "self") or "self")
    source_expr = _handle_expr(str(data.get("source_object_id", "") or ""), obj_var)
    x = float(data.get("world_x", 0) or 0)
    y = float(data.get("world_y", 0) or 0)
    lines = ["do", f"    local _source_handle = {source_expr}"]
    if source_mode == "self":
        lines.extend(
            [
                "    local _wx = _source_handle and prim.get_x(_source_handle) or 0",
                "    local _wy = _source_handle and prim.get_y(_source_handle) or 0",
            ]
        )
    else:
        lines.extend([f"    local _wx = {x}", f"    local _wy = {y}"])
    return lines, "_wx", "_wy"


def _grid_value_expr(data: dict, obj_var: str | None) -> str:
    value_mode = str(data.get("value_mode", "current") or "current")
    if value_mode == "current":
        return _handle_expr("", obj_var)
    if value_mode == "object":
        return _handle_expr(str(data.get("value_object_id", "") or ""), None)
    if value_mode == "variable":
        return _safe_ident(data.get("value_var", "grid_value"), "grid_value")
    if value_mode == "literal":
        return _lua_str(str(data.get("literal_value", "") or ""))
    return "nil"


def _grid_index_exprs(data: dict) -> tuple[str, str]:
    col_var = str(data.get("col_var_name", "") or "")
    row_var = str(data.get("row_var_name", "") or "")
    col_expr = _safe_ident(col_var, "grid_col") if col_var else str(int(data.get("col", 0) or 0))
    row_expr = _safe_ident(row_var, "grid_row") if row_var else str(int(data.get("row", 0) or 0))
    return col_expr, row_expr


def _emit_nested_actions(actions, obj_var, project):
    from lpp_exporter import _action_to_lua_inline

    lines: list[str] = []
    for action in actions or []:
        for line in _action_to_lua_inline(action, obj_var, project):
            lines.append(str(line))
    return lines


def _world_position_to_grid_cell_export(action, obj_var, project):
    data = _action_data(action, "prim_world_position_to_grid_cell")
    grid_name = str(data.get("grid_name", "grid1") or "grid1")
    col_var = _safe_ident(data.get("col_var", "grid_col"), "grid_col")
    row_var = _safe_ident(data.get("row_var", "grid_row"), "grid_row")
    lines, wx, wy = _position_lines(data, obj_var)
    lines.append(f"    {col_var}, {row_var} = prim.world_to_grid_cell({_lua_str(grid_name)}, {wx}, {wy})")
    lines.append("end")
    return lines


def _grid_cell_to_world_position_export(action, obj_var, project):
    data = _action_data(action, "prim_grid_cell_to_world_position")
    grid_name = str(data.get("grid_name", "grid1") or "grid1")
    x_var = _safe_ident(data.get("world_x_var", "world_x"), "world_x")
    y_var = _safe_ident(data.get("world_y_var", "world_y"), "world_y")
    col_expr, row_expr = _grid_index_exprs(data)
    return [f"{x_var}, {y_var} = prim.grid_cell_to_world({_lua_str(grid_name)}, {col_expr}, {row_expr})"]


def _read_grid_cell_export(action, obj_var, project):
    data = _action_data(action, "prim_read_grid_cell")
    grid_name = str(data.get("grid_name", "grid1") or "grid1")
    result_var = _safe_ident(data.get("result_var", "grid_value"), "grid_value")
    col_expr, row_expr = _grid_index_exprs(data)
    return [f"{result_var} = prim.read_grid_cell({_lua_str(grid_name)}, {col_expr}, {row_expr})"]


def _write_grid_cell_export(action, obj_var, project):
    data = _action_data(action, "prim_write_grid_cell")
    grid_name = str(data.get("grid_name", "grid1") or "grid1")
    col_expr, row_expr = _grid_index_exprs(data)
    value_expr = _grid_value_expr(data, obj_var)
    return [f"prim.write_grid_cell({_lua_str(grid_name)}, {col_expr}, {row_expr}, {value_expr})"]


def _if_collision_at_position_export(action, obj_var, project):
    data = _action_data(action, "prim_if_collision_at_position")
    layer_id = str(data.get("layer_id", "") or "")
    lines, wx, wy = _position_lines(data, obj_var)
    lines.append(f"    if prim.collision_at({_lua_str(layer_id)}, {wx}, {wy}) then")
    for line in _emit_nested_actions(action.true_actions, obj_var, project):
        lines.append(f"        {line}")
    if action.false_actions:
        lines.append("    else")
        for line in _emit_nested_actions(action.false_actions, obj_var, project):
            lines.append(f"        {line}")
    lines.append("    end")
    lines.append("end")
    return lines


def _read_light_value_export(action, obj_var, project):
    data = _action_data(action, "prim_read_light_value")
    layer_id = str(data.get("light_layer_id", "") or "")
    result_var = _safe_ident(data.get("result_var", "light_value"), "light_value")
    lines, wx, wy = _position_lines(data, obj_var)
    lines.append(f"    {result_var} = prim.light_value_at({_lua_str(layer_id)}, {wx}, {wy})")
    lines.append("end")
    return lines


def _sample_path_point_export(action, obj_var, project):
    data = _action_data(action, "prim_sample_path_point")
    path_name = str(data.get("path_name", "") or "")
    index_var_name = str(data.get("index_var_name", "") or "")
    index_expr = _safe_ident(index_var_name, "path_index") if index_var_name else str(int(data.get("index", 1) or 1))
    x_var = _safe_ident(data.get("world_x_var", "path_point_x"), "path_point_x")
    y_var = _safe_ident(data.get("world_y_var", "path_point_y"), "path_point_y")
    return [
        "do",
        f"    local _idx, _pt = prim.sample_path_point({_lua_str(path_name)}, {index_expr})",
        f"    {x_var} = _pt and _pt.x or 0",
        f"    {y_var} = _pt and _pt.y or 0",
        "end",
    ]


def _find_nearest_path_point_export(action, obj_var, project):
    data = _action_data(action, "prim_find_nearest_path_point")
    path_name = str(data.get("path_name", "") or "")
    index_var = _safe_ident(data.get("index_var", "nearest_path_index"), "nearest_path_index")
    x_var = _safe_ident(data.get("world_x_var", "path_point_x"), "path_point_x")
    y_var = _safe_ident(data.get("world_y_var", "path_point_y"), "path_point_y")
    distance_var = _safe_ident(data.get("distance_var", "path_point_distance"), "path_point_distance")
    lines, wx, wy = _position_lines(data, obj_var)
    lines.extend(
        [
            f"    local _idx, _pt = prim.find_nearest_path_point({_lua_str(path_name)}, {wx}, {wy})",
            f"    {index_var} = _idx or 0",
            f"    {x_var} = _pt and _pt.x or 0",
            f"    {y_var} = _pt and _pt.y or 0",
            f"    {distance_var} = _pt and prim.distance_points({wx}, {wy}, _pt.x, _pt.y) or 0",
            "end",
        ]
    )
    return lines


PLUGIN = {
    "name": "Built-in World Pack",
    "actions": [
        {
            "key": "prim_world_position_to_grid_cell",
            "label": "World Position To Grid Cell",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "grid_name", "type": "str", "label": "Grid", "default": "grid1"},
                {"key": "source_mode", "type": "combo", "label": "Source", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "world_x", "type": "float", "label": "World X", "default": 0.0, "step": 1.0},
                {"key": "world_y", "type": "float", "label": "World Y", "default": 0.0, "step": 1.0},
                {"key": "col_var", "type": "str", "label": "Column Variable", "default": "grid_col"},
                {"key": "row_var", "type": "str", "label": "Row Variable", "default": "grid_row"},
            ],
            "lua_export": _world_position_to_grid_cell_export,
        },
        {
            "key": "prim_grid_cell_to_world_position",
            "label": "Grid Cell To World Position",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "grid_name", "type": "str", "label": "Grid", "default": "grid1"},
                {"key": "col", "type": "int", "label": "Column", "default": 0, "min": -9999, "max": 9999},
                {"key": "row", "type": "int", "label": "Row", "default": 0, "min": -9999, "max": 9999},
                {"key": "col_var_name", "type": "str", "label": "Column Variable", "default": ""},
                {"key": "row_var_name", "type": "str", "label": "Row Variable", "default": ""},
                {"key": "world_x_var", "type": "str", "label": "World X Variable", "default": "world_x"},
                {"key": "world_y_var", "type": "str", "label": "World Y Variable", "default": "world_y"},
            ],
            "lua_export": _grid_cell_to_world_position_export,
        },
        {
            "key": "prim_read_grid_cell",
            "label": "Read Grid Cell",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "grid_name", "type": "str", "label": "Grid", "default": "grid1"},
                {"key": "col", "type": "int", "label": "Column", "default": 0, "min": -9999, "max": 9999},
                {"key": "row", "type": "int", "label": "Row", "default": 0, "min": -9999, "max": 9999},
                {"key": "col_var_name", "type": "str", "label": "Column Variable", "default": ""},
                {"key": "row_var_name", "type": "str", "label": "Row Variable", "default": ""},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "grid_value"},
            ],
            "lua_export": _read_grid_cell_export,
        },
        {
            "key": "prim_write_grid_cell",
            "label": "Write Grid Cell",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "grid_name", "type": "str", "label": "Grid", "default": "grid1"},
                {"key": "col", "type": "int", "label": "Column", "default": 0, "min": -9999, "max": 9999},
                {"key": "row", "type": "int", "label": "Row", "default": 0, "min": -9999, "max": 9999},
                {"key": "col_var_name", "type": "str", "label": "Column Variable", "default": ""},
                {"key": "row_var_name", "type": "str", "label": "Row Variable", "default": ""},
                {"key": "value_mode", "type": "combo", "label": "Value", "options": ["current", "object", "variable", "literal", "clear"], "default": "current"},
                {"key": "value_object_id", "type": "object", "label": "Value Object", "default": ""},
                {"key": "value_var", "type": "str", "label": "Value Variable", "default": "grid_value"},
                {"key": "literal_value", "type": "str", "label": "Literal Value", "default": ""},
            ],
            "lua_export": _write_grid_cell_export,
        },
        {
            "key": "prim_if_collision_at_position",
            "label": "If Collision At Position",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "layer_id", "type": "collision_layer", "label": "Collision Layer", "default": ""},
                {"key": "source_mode", "type": "combo", "label": "Source", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "world_x", "type": "float", "label": "World X", "default": 0.0, "step": 1.0},
                {"key": "world_y", "type": "float", "label": "World Y", "default": 0.0, "step": 1.0},
            ],
            "has_branches": True,
            "lua_export": _if_collision_at_position_export,
        },
        {
            "key": "prim_read_light_value",
            "label": "Read Light Value",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "light_layer_id", "type": "str", "label": "Light Layer ID", "default": ""},
                {"key": "source_mode", "type": "combo", "label": "Source", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "world_x", "type": "float", "label": "World X", "default": 0.0, "step": 1.0},
                {"key": "world_y", "type": "float", "label": "World Y", "default": 0.0, "step": 1.0},
                {"key": "result_var", "type": "str", "label": "Result Variable", "default": "light_value"},
            ],
            "lua_export": _read_light_value_export,
        },
        {
            "key": "prim_sample_path_point",
            "label": "Sample Path Point",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "path_name", "type": "str", "label": "Path Name", "default": ""},
                {"key": "index", "type": "int", "label": "Index", "default": 1, "min": 1, "max": 999999},
                {"key": "index_var_name", "type": "str", "label": "Index Variable", "default": ""},
                {"key": "world_x_var", "type": "str", "label": "World X Variable", "default": "path_point_x"},
                {"key": "world_y_var", "type": "str", "label": "World Y Variable", "default": "path_point_y"},
            ],
            "lua_export": _sample_path_point_export,
        },
        {
            "key": "prim_find_nearest_path_point",
            "label": "Find Nearest Path Point",
            "category": "Engine Primitives/World",
            "fields": [
                {"key": "path_name", "type": "str", "label": "Path Name", "default": ""},
                {"key": "source_mode", "type": "combo", "label": "Source", "options": ["self", "position"], "default": "self"},
                {"key": "source_object_id", "type": "object", "label": "Source Object", "default": ""},
                {"key": "world_x", "type": "float", "label": "World X", "default": 0.0, "step": 1.0},
                {"key": "world_y", "type": "float", "label": "World Y", "default": 0.0, "step": 1.0},
                {"key": "index_var", "type": "str", "label": "Index Variable", "default": "nearest_path_index"},
                {"key": "world_x_var", "type": "str", "label": "World X Variable", "default": "path_point_x"},
                {"key": "world_y_var", "type": "str", "label": "World Y Variable", "default": "path_point_y"},
                {"key": "distance_var", "type": "str", "label": "Distance Variable", "default": "path_point_distance"},
            ],
            "lua_export": _find_nearest_path_point_export,
        },
    ],
}

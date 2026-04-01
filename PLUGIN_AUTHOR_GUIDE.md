# Plugin Author Guide

This engine supports project-scoped plugins. A plugin lives inside the project folder and is loaded from:

`plugins/<plugin_id>/plugin.py`

This guide is written for plugin authors who do not have engine source access. Use the Calendar example as the working reference.

## V1 Scope

Plugins can add:

- Scene components
- Behavior triggers
- Behavior actions

Plugins cannot yet add:

- Custom Qt widgets
- New loop-parent action types
- Extra lifecycle hooks beyond the current scene/component/action/trigger hooks

Keep plugins headless. A plugin should not depend on editor-only Qt imports.

## File Layout

Each plugin folder should contain at minimum:

- `plugin.py`
- `PLUGIN_AUTHOR_GUIDE.md`
- `README.md`

Recommended layout:

```text
plugins/
  my_plugin/
    plugin.py
    README.md
    PLUGIN_AUTHOR_GUIDE.md
```

## Top-Level Contract

Your `plugin.py` must expose a top-level `PLUGIN` dict.

Supported top-level keys:

- `name`
- `components`
- `triggers`
- `actions`

Optional metadata such as `version` or `description` may exist, but v1 does not use it functionally.

Example:

```python
PLUGIN = {
    "name": "My Plugin",
    "components": [],
    "triggers": [],
    "actions": [],
}
```

## Components

Component descriptors support:

- `type`
- `label`
- `color`
- `singleton`
- `defaults`
- `fields`
- `editor_tools`
- `lua_lib`
- `lua_scene_init`
- `lua_scene_loop`
- `lua_scene_draw`

Example:

```python
{
    "type": "Weather",
    "label": "Weather",
    "color": "#3b82f6",
    "singleton": True,
    "defaults": {
        "enabled": True,
        "rain_strength": 0.5,
    },
    "fields": [
        {"type": "section", "label": "GENERAL"},
        {"key": "enabled", "type": "bool", "label": "Enabled", "default": True},
        {"key": "rain_strength", "type": "float", "label": "Rain Strength", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1},
    ],
}
```

Supported component field types in v1:

- `bool`
- `int`
- `float`
- `str`
- `combo`
- `color`
- `section`

## Editor Tools

Component descriptors may declare optional declarative editor tools through `editor_tools`.

Supported tool kinds in v1:

- `grid_map`
- `path`

These tools are metadata only.

- Do not import Qt.
- Do not provide callbacks.
- Do not assume access to `tab_editor` internals.

Unknown tool kinds or missing required keys will fail plugin loading with a plugin error.

### `grid_map`

Required keys:

- `kind` with value `"grid_map"`
- `data_key`
- `width_key`
- `height_key`
- `cell_size_key`
- `mode`

If `mode` is `"binary"`, you may also set:

- `default_cell`
- `active_value`
- `overlay_color`
- `paint_label`
- `erase_label`

If `mode` is `"scalar"`, you must also set:

- `paint_value_key`
- `brush_mode_key`
- `brush_radius_key`
- `brush_strength_key`

Optional scalar keys:

- `default_cell`
- `overlay_color`
- `overlay_color_key`
- `opacity_key`
- `paint_label`
- `erase_label`

Example:

```python
{
    "type": "DangerZones",
    "label": "Danger Zones",
    "color": "#ef4444",
    "defaults": {
        "map_width": 30,
        "map_height": 17,
        "tile_size": 32,
        "danger_cells": [],
    },
    "fields": [
        {"key": "map_width", "type": "int", "label": "Map Width", "default": 30, "min": 1, "max": 500},
        {"key": "map_height", "type": "int", "label": "Map Height", "default": 17, "min": 1, "max": 500},
        {"key": "tile_size", "type": "int", "label": "Cell Size", "default": 32, "min": 4, "max": 512},
    ],
    "editor_tools": [
        {
            "kind": "grid_map",
            "data_key": "danger_cells",
            "width_key": "map_width",
            "height_key": "map_height",
            "cell_size_key": "tile_size",
            "mode": "binary",
            "default_cell": 0,
            "active_value": 1,
            "overlay_color": "#ef4444",
            "paint_label": "Paint Danger",
            "erase_label": "Erase Danger",
        }
    ],
}
```

### `path`

Required keys:

- `kind` with value `"path"`
- `points_key`
- `closed_key`
- `name_key`

Optional keys:

- `draw_label`
- `supports_bezier`

Example:

```python
{
    "type": "PatrolRoute",
    "label": "Patrol Route",
    "color": "#06b6d4",
    "defaults": {
        "route_name": "Route A",
        "route_closed": False,
        "route_points": [],
    },
    "fields": [
        {"key": "route_name", "type": "str", "label": "Route Name", "default": "Route A"},
        {"key": "route_closed", "type": "bool", "label": "Closed Loop", "default": False},
    ],
    "editor_tools": [
        {
            "kind": "path",
            "points_key": "route_points",
            "closed_key": "route_closed",
            "name_key": "route_name",
            "draw_label": "Draw Route",
            "supports_bezier": True,
        }
    ],
}
```

## Triggers

Trigger descriptors support:

- `key`
- `label`
- `category`
- `fields`
- `lua_condition`

`lua_condition(behavior, vname, project) -> str` must return a Lua boolean expression string.

Example:

```python
{
    "key": "on_weather_change",
    "label": "On Weather Change",
    "category": "Weather",
    "fields": [
        {"key": "weather_type", "type": "combo", "label": "Type", "options": ["sun", "rain"], "default": "rain"},
    ],
    "lua_condition": my_condition_function,
}
```

Supported trigger/action field types in v1:

- `bool`
- `int`
- `float`
- `str`
- `combo`

Do not rely on `section` or custom widget types inside trigger/action node editors in v1.

## Actions

Action descriptors support:

- `key`
- `label`
- `category`
- `fields`
- `has_branches`
- `lua_export`

`lua_export(action, vname, project) -> list[str]` must return Lua lines.

Example:

```python
{
    "key": "set_weather",
    "label": "Set Weather",
    "category": "Weather",
    "fields": [
        {"key": "weather_type", "type": "combo", "label": "Type", "options": ["sun", "rain"], "default": "rain"},
    ],
    "lua_export": my_export_function,
}
```

If `has_branches` is `True`, your action behaves like a branching node and should emit a full Lua `if ... then ... else ... end` block inside `lua_export`.

## Data Access

Plugin-only trigger and action values are stored under `plugin_data`.

Use helper patterns like the Calendar plugin:

```python
def _behavior_data(behavior, trigger_key: str) -> dict:
    plugin_data = getattr(behavior, "plugin_data", {}) or {}
    bucket = plugin_data.get(trigger_key, {})
    return bucket if isinstance(bucket, dict) else {}

def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}
```

Important rule:

- Read your plugin values from the bucket keyed by your trigger key or action key.

## Naming Guidance

Choose field keys that are plugin-specific enough to stay readable and avoid confusion.

Good:

- `calendar_trigger_unit`
- `calendar_var`
- `weather_type`

Avoid overly generic keys like:

- `unit`
- `value`
- `name`

## Lua Hook Rules

`lua_lib`

- A string containing Lua helper code written to `lib/<plugin_id>.lua`

`lua_scene_init(config, project) -> list[str]`

- Runs during scene setup for scenes that use your component

`lua_scene_loop(config, project) -> list[str]`

- Runs every frame for scenes that use your component

`lua_scene_draw(config, project) -> list[str]`

- Runs during scene rendering for scenes that use your component

These functions should return Lua lines, not one large opaque blob.

## Compatibility Rules

Expect older saved projects to exist.

Your plugin should:

- Provide stable defaults
- Tolerate missing config keys
- Migrate old names when practical

The Calendar plugin is the reference example:

- It accepts old `ms_per_minute`
- It prefers new `ms_per_second`
- It supplies defaults for missing `start_second` and `seconds_per_minute`

## Trigger Design Rule

Do not build triggers that let one listener steal an event from another listener.

The first Calendar version used a shared consume flag. That caused one behavior node to eat the event before another node could see it. The fixed version uses listener-specific change tracking.

Good patterns:

- Return a pure boolean expression
- Use listener-specific bookkeeping keyed by a listener id
- Keep multiple behaviors safe to run in the same frame

Avoid:

- Shared global consume flags unless only one listener can ever exist

## Return Type Rules

`lua_condition`

- Return only a Lua boolean expression string

`lua_export`

- Return `list[str]`

Avoid returning mixed expression/block formats from the same function.

## Recommended Workflow

1. Copy the Calendar structure.
2. Rename the component, triggers, and actions.
3. Replace the Lua helper library with your own runtime code.
4. Keep your first plugin small.
5. Test save, reopen, and export before expanding the feature set.

## Testing Checklist

- Add the plugin component to a scene.
- Save and reopen the project.
- Confirm component settings persist.
- Create trigger/action nodes and confirm values persist after clicking away and reopening the graph.
- If multiple nodes listen to the same event, confirm they all fire.
- Export and inspect generated Lua.
- Verify your plugin lib is emitted once and required once.

## Calendar Lessons

Calendar is a good model because it demonstrates:

- A singleton scene component
- Trigger fields stored in `plugin_data`
- Action fields stored in `plugin_data`
- Scene init and loop hooks
- Exported Lua helper library
- Backward-compatible config handling
- Safe multi-listener trigger behavior

If you are unsure how to structure your plugin, start by copying Calendar and removing features until only your core behavior remains.

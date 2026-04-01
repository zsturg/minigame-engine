# Calendar Plugin

This folder is both a usable plugin and the reference example for future plugin authors.

## What It Adds

- A singleton `Calendar` scene component
- `On Calendar Unit Change` trigger
- `On Calendar Unit Equals` trigger
- `Advance Time` action
- `Set Time Unit` action
- `Store Time Unit` action
- `If Time Equals` branching action
- `If Time In Range` branching action

## Why This Plugin Exists

Calendar is intentionally small but complete. It demonstrates the full v1 plugin path:

- component registration
- auto-generated component UI
- behavior trigger fields
- behavior action fields
- scene init and scene loop hooks
- exported Lua helper library
- backward-compatible config handling

## Important Lessons From This Example

### 1. Use stable defaults

Older projects may not have newer config keys. Calendar handles that by:

- keeping component defaults in one place
- filling missing values during export
- accepting old `ms_per_minute` while preferring `ms_per_second`

### 2. Make triggers safe for multiple listeners

Two different behaviors may react to the same time change in the same frame.

Calendar originally used a shared consume flag, which caused one listener to block the other. The fixed version uses listener-specific tracking through `calendar_on_change(...)`.

If you build event-style triggers, design them so multiple behaviors can respond without interfering with one another.

### 3. Keep plugin data names explicit

Calendar uses names like:

- `calendar_trigger_unit`
- `calendar_var`
- `calendar_amount`

This makes saved project data easier to read and reduces ambiguity.

## Author Workflow

If you are making a new plugin:

1. Read `PLUGIN_AUTHOR_GUIDE.md`.
2. Copy this folder somewhere outside the active `plugins/` scan path.
3. Rename the plugin ids, labels, component types, and Lua helpers.
4. Strip Calendar-specific behavior until only your own feature remains.
5. Test save, reopen, and export.

## Runtime Notes

- `lua_lib` is emitted once as `lib/calendar.lua`
- scene hooks run only when a scene actually uses the `Calendar` component
- trigger and action settings round-trip through `plugin_data`

## Supported Units

Calendar supports:

- `second`
- `minute`
- `hour`
- `day`
- `month`
- `year`

If you open an older project that still uses minute-based timing config, the plugin will still export working Lua using fallback defaults and compatibility logic.

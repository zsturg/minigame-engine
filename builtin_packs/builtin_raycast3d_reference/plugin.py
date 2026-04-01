from __future__ import annotations


def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}


def _lua_bool(value: bool) -> str:
    return "true" if value else "false"


def _lua_str(value: str) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _hitscan_kill_export(action, obj_var, project):
    data = _action_data(action, "ray3d_reference_hitscan_kill")
    max_range = float(data.get("max_range", 192.0) or 192.0)
    ignore_nonblocking = bool(data.get("ignore_nonblocking", True))
    death_state = str(data.get("death_state", "dead") or "dead")
    return [
        "do",
        f"    local _hit = ray3d_hitscan({max_range}, {{ignore_nonblocking = {_lua_bool(ignore_nonblocking)}}})",
        "    if _hit and _hit.kind == \"actor\" and _hit.actor_id and actor3d_is_alive(_hit.actor_id) then",
        f"        actor3d_kill(_hit.actor_id, {_lua_str(death_state)})",
        "    end",
        "end",
    ]


PLUGIN = {
    "name": "Built-in Raycast3D Reference Pack",
    "actions": [
        {
            "key": "ray3d_reference_hitscan_kill",
            "label": "Reference 3D Hitscan Kill",
            "category": "3D Examples",
            "fields": [
                ("max_range", "Max Range", "dspin", {"min": 1.0, "max": 4096.0, "step": 8.0}),
                ("ignore_nonblocking", "Ignore Non-Blocking", "check", {}),
                ("death_state", "Death State", "text", {}),
            ],
            "lua_export": _hitscan_kill_export,
        }
    ],
}

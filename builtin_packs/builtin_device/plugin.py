from __future__ import annotations


def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}


def _safe_ident(name: str) -> str:
    text = "".join(char if char.isalnum() or char == "_" else "_" for char in str(name or ""))
    if text and text[0].isdigit():
        text = "_" + text
    return text


def _lua_str(value: str) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _assign_if_target(lines: list[str], target_name: str, expr: str) -> None:
    ident = _safe_ident(target_name)
    if ident:
        lines.append(f"    {ident} = {expr}")


def _device_store_power_info_export(action, obj_var, project):
    data = _action_data(action, "device_store_power_info")
    lines = ["do"]
    _assign_if_target(lines, data.get("battery_percent_var", ""), "device_battery_percent()")
    _assign_if_target(lines, data.get("charging_var", ""), "device_is_charging()")
    _assign_if_target(lines, data.get("battery_life_minutes_var", ""), "device_battery_life_minutes()")
    lines.append("end")
    return [] if len(lines) == 2 else lines


def _device_store_profile_info_export(action, obj_var, project):
    data = _action_data(action, "device_store_profile_info")
    lines = ["do"]
    _assign_if_target(lines, data.get("username_var", ""), "device_username()")
    _assign_if_target(lines, data.get("language_var", ""), "device_language()")
    _assign_if_target(lines, data.get("model_var", ""), "device_model()")
    lines.append("end")
    return [] if len(lines) == 2 else lines


def _device_store_app_info_export(action, obj_var, project):
    data = _action_data(action, "device_store_app_info")
    lines = ["do"]
    _assign_if_target(lines, data.get("title_var", ""), "device_app_title()")
    _assign_if_target(lines, data.get("title_id_var", ""), "device_app_title_id()")
    _assign_if_target(lines, data.get("safe_mode_var", ""), "device_is_safe_mode()")
    lines.append("end")
    return [] if len(lines) == 2 else lines


def _device_execute_uri_export(action, obj_var, project):
    data = _action_data(action, "device_execute_uri")
    uri = str(data.get("uri", "") or "")
    if not uri:
        return []
    return [f"device_execute_uri({_lua_str(uri)})"]


DEVICE_LUA = """
local _device_language_names = {
    [0] = "Japanese",
    [1] = "English (US)",
    [2] = "French",
    [3] = "Spanish",
    [4] = "German",
    [5] = "Italian",
    [6] = "Dutch",
    [7] = "Portuguese (PT)",
    [8] = "Russian",
    [9] = "Korean",
    [10] = "Traditional Chinese",
    [11] = "Simplified Chinese",
    [12] = "Finnish",
    [13] = "Swedish",
    [14] = "Danish",
    [15] = "Norwegian",
    [16] = "Polish",
    [17] = "Portuguese (BR)",
    [18] = "English (UK)",
    [19] = "Turkish",
}

function device_battery_percent()
    return System.getBatteryPercentage() or 0
end

function device_is_charging()
    return System.isBatteryCharging() == true
end

function device_battery_life_minutes()
    return System.getBatteryLife() or 0
end

function device_username()
    return System.getUsername() or ""
end

function device_language()
    local lang_id = tonumber(System.getLanguage())
    return _device_language_names[lang_id] or ("Unknown (" .. tostring(lang_id or "?") .. ")")
end

function device_model()
    local model_id = tonumber(System.getModel())
    if model_id == 65536 then return "PS Vita" end
    if model_id == 131072 then return "PSTV" end
    return "Unknown (" .. tostring(model_id or "?") .. ")"
end

function device_app_title()
    return System.getTitle() or ""
end

function device_app_title_id()
    return System.getTitleID() or ""
end

function device_is_safe_mode()
    return System.isSafeMode() == true
end

function device_execute_uri(uri)
    local target = tostring(uri or "")
    if target ~= "" then
        System.executeUri(target)
    end
end
""".strip()


PLUGIN = {
    "name": "Built-in Device Pack",
    "components": [
        {
            "type": "DeviceService",
            "label": "Device Service",
            "color": "#10b981",
            "singleton": True,
            "defaults": {},
            "fields": [],
            "lua_lib": DEVICE_LUA,
        }
    ],
    "actions": [
        {
            "key": "device_store_power_info",
            "label": "Store Power Info",
            "category": "Device",
            "fields": [
                {"key": "battery_percent_var", "type": "str", "label": "Battery Percent Variable", "default": ""},
                {"key": "charging_var", "type": "str", "label": "Charging Variable", "default": ""},
                {"key": "battery_life_minutes_var", "type": "str", "label": "Battery Life Minutes Variable", "default": ""},
            ],
            "lua_export": _device_store_power_info_export,
        },
        {
            "key": "device_store_profile_info",
            "label": "Store Profile Info",
            "category": "Device",
            "fields": [
                {"key": "username_var", "type": "str", "label": "Username Variable", "default": ""},
                {"key": "language_var", "type": "str", "label": "Language Variable", "default": ""},
                {"key": "model_var", "type": "str", "label": "Model Variable", "default": ""},
            ],
            "lua_export": _device_store_profile_info_export,
        },
        {
            "key": "device_store_app_info",
            "label": "Store App Info",
            "category": "Device",
            "fields": [
                {"key": "title_var", "type": "str", "label": "Title Variable", "default": ""},
                {"key": "title_id_var", "type": "str", "label": "Title ID Variable", "default": ""},
                {"key": "safe_mode_var", "type": "str", "label": "Safe Mode Variable", "default": ""},
            ],
            "lua_export": _device_store_app_info_export,
        },
        {
            "key": "device_execute_uri",
            "label": "Execute URI",
            "category": "Device",
            "fields": [
                {"key": "uri", "type": "str", "label": "URI", "default": ""},
            ],
            "lua_export": _device_execute_uri_export,
        },
    ],
}

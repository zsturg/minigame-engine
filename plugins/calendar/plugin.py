from __future__ import annotations


def _behavior_data(behavior, trigger_key: str) -> dict:
    plugin_data = getattr(behavior, "plugin_data", {}) or {}
    bucket = plugin_data.get(trigger_key, {})
    return bucket if isinstance(bucket, dict) else {}


def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}


def _safe_lua_ident(name: str) -> str:
    out = []
    for char in str(name or ""):
        out.append(char if char.isalnum() or char == "_" else "_")
    text = "".join(out) or "calendar_value"
    if text[0].isdigit():
        text = "_" + text
    return text


def _lua_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _lua_config_table(config: dict) -> str:
    items = []
    for key in (
        "auto_advance",
        "ms_per_second",
        "ms_per_minute",
        "seconds_per_minute",
        "start_second",
        "start_minute",
        "start_hour",
        "start_day",
        "start_month",
        "start_year",
        "days_per_week",
        "days_per_month",
        "months_per_year",
        "weekday_names",
        "month_names",
    ):
        items.append(f"{key} = {_lua_value(config.get(key, CALENDAR_COMPONENT_DEFAULTS.get(key))) }")
    return "{ " + ", ".join(items) + " }"


def _emit_nested_actions(actions, obj_var, project):
    from lpp_exporter import _action_to_lua_inline

    lines = []
    for action in actions or []:
        for line in _action_to_lua_inline(action, obj_var, project):
            lines.append(str(line))
    return lines


def _calendar_scene_init(config, project):
    return [
        "calendar_reset()",
        f"calendar_configure({_lua_config_table(config)})",
        "_calendar_timer = Timer.new()",
        "Timer.reset(_calendar_timer)",
        "_calendar_prev_ms = nil",
    ]


def _calendar_scene_loop(config, project):
    return [
        "local _calendar_now = Timer.getTime(_calendar_timer)",
        "if _calendar_prev_ms == nil then _calendar_prev_ms = _calendar_now end",
        "calendar_tick(_calendar_now - _calendar_prev_ms)",
        "_calendar_prev_ms = _calendar_now",
    ]


def _on_time_change_condition(behavior, vname, project):
    data = _behavior_data(behavior, "on_time_change")
    unit = data.get("calendar_trigger_unit", "hour")
    listener_id = _safe_lua_ident(f"{vname}_{unit}_{id(behavior)}")
    return f'calendar_on_change("{unit}", "{listener_id}")'


def _on_time_equals_condition(behavior, vname, project):
    data = _behavior_data(behavior, "on_time_equals")
    unit = data.get("calendar_trigger_unit", "hour")
    value = int(data.get("calendar_trigger_value", 0) or 0)
    return f'calendar_get("{unit}") == {value}'


def _advance_time_export(action, vname, project):
    data = _action_data(action, "advance_time")
    unit = data.get("calendar_unit", "minute")
    amount = int(data.get("calendar_amount", 1) or 0)
    return [f'calendar_advance("{unit}", {amount})']


def _set_time_export(action, vname, project):
    data = _action_data(action, "set_time")
    unit = data.get("calendar_unit", "hour")
    value = int(data.get("calendar_value", 0) or 0)
    return [f'calendar_set("{unit}", {value})']


def _get_time_unit_export(action, vname, project):
    data = _action_data(action, "get_time_unit")
    unit = data.get("calendar_unit", "hour")
    variable_name = _safe_lua_ident(data.get("calendar_var", "calendar_value"))
    return [f'{variable_name} = calendar_get("{unit}")']


def _if_time_equals_export(action, vname, project):
    data = _action_data(action, "if_time_equals")
    unit = data.get("calendar_unit", "hour")
    value = int(data.get("calendar_value", 0) or 0)
    lines = [f'if calendar_get("{unit}") == {value} then']
    for line in _emit_nested_actions(action.true_actions, vname, project):
        lines.append(f"    {line}")
    if action.false_actions:
        lines.append("else")
        for line in _emit_nested_actions(action.false_actions, vname, project):
            lines.append(f"    {line}")
    lines.append("end")
    return lines


def _if_time_range_export(action, vname, project):
    data = _action_data(action, "if_time_range")
    unit = data.get("calendar_unit", "hour")
    minimum = int(data.get("calendar_min", 0) or 0)
    maximum = int(data.get("calendar_max", 0) or 0)
    lines = [f'if calendar_is_range("{unit}", {minimum}, {maximum}) then']
    for line in _emit_nested_actions(action.true_actions, vname, project):
        lines.append(f"    {line}")
    if action.false_actions:
        lines.append("else")
        for line in _emit_nested_actions(action.false_actions, vname, project):
            lines.append(f"    {line}")
    lines.append("end")
    return lines


CALENDAR_LUA = """
calendar_state = calendar_state or { second = 0, minute = 0, hour = 8, day = 1, month = 1, year = 1 }
calendar_cfg = calendar_cfg or {
    auto_advance = true,
    ms_per_second = 1000,
    seconds_per_minute = 60,
    days_per_week = 7,
    days_per_month = 30,
    months_per_year = 12,
    weekday_names = {"Sun","Mon","Tue","Wed","Thu","Fri","Sat"},
    month_names = {"Month 1","Month 2","Month 3","Month 4","Month 5","Month 6","Month 7","Month 8","Month 9","Month 10","Month 11","Month 12"},
}
calendar_accum_ms = calendar_accum_ms or 0
calendar_changed = calendar_changed or {}
calendar_change_count = calendar_change_count or {}
calendar_listener_seen = calendar_listener_seen or {}

local function calendar_split_csv(text)
    local items = {}
    for part in string.gmatch(tostring(text or ""), "([^,]+)") do
        local trimmed = part:gsub("^%s+", ""):gsub("%s+$", "")
        if trimmed ~= "" then
            items[#items + 1] = trimmed
        end
    end
    return items
end

function calendar_reset()
    calendar_accum_ms = 0
    calendar_changed = {}
    calendar_change_count = {}
    calendar_listener_seen = {}
end

function calendar_configure(cfg)
    calendar_cfg.auto_advance = cfg.auto_advance ~= false
    calendar_cfg.ms_per_second = tonumber(cfg.ms_per_second) or tonumber(cfg.ms_per_minute) or 1000
    calendar_cfg.seconds_per_minute = math.max(1, tonumber(cfg.seconds_per_minute) or 60)
    calendar_cfg.days_per_week = math.max(1, tonumber(cfg.days_per_week) or 7)
    calendar_cfg.days_per_month = math.max(1, tonumber(cfg.days_per_month) or 30)
    calendar_cfg.months_per_year = math.max(1, tonumber(cfg.months_per_year) or 12)

    local weekdays = calendar_split_csv(cfg.weekday_names)
    local months = calendar_split_csv(cfg.month_names)
    if #weekdays > 0 then calendar_cfg.weekday_names = weekdays end
    if #months > 0 then calendar_cfg.month_names = months end

    calendar_state.second = tonumber(cfg.start_second) or 0
    calendar_state.minute = tonumber(cfg.start_minute) or 0
    calendar_state.hour = tonumber(cfg.start_hour) or 8
    calendar_state.day = math.max(1, tonumber(cfg.start_day) or 1)
    calendar_state.month = math.max(1, tonumber(cfg.start_month) or 1)
    calendar_state.year = math.max(1, tonumber(cfg.start_year) or 1)
    calendar_reset()
end

local function calendar_mark(unit)
    calendar_changed[unit] = true
    calendar_change_count[unit] = (calendar_change_count[unit] or 0) + 1
end

local function calendar_wrap_forward()
    while calendar_state.second >= calendar_cfg.seconds_per_minute do
        calendar_state.second = calendar_state.second - calendar_cfg.seconds_per_minute
        calendar_state.minute = calendar_state.minute + 1
        calendar_mark("minute")
    end
    while calendar_state.minute >= 60 do
        calendar_state.minute = calendar_state.minute - 60
        calendar_state.hour = calendar_state.hour + 1
        calendar_mark("hour")
    end
    while calendar_state.hour >= 24 do
        calendar_state.hour = calendar_state.hour - 24
        calendar_state.day = calendar_state.day + 1
        calendar_mark("day")
    end
    while calendar_state.day > calendar_cfg.days_per_month do
        calendar_state.day = calendar_state.day - calendar_cfg.days_per_month
        calendar_state.month = calendar_state.month + 1
        calendar_mark("month")
    end
    while calendar_state.month > calendar_cfg.months_per_year do
        calendar_state.month = calendar_state.month - calendar_cfg.months_per_year
        calendar_state.year = calendar_state.year + 1
        calendar_mark("year")
    end
end

function calendar_get(unit)
    return calendar_state[unit] or 0
end

function calendar_set(unit, value)
    local amount = tonumber(value) or 0
    if unit == "second" then
        calendar_state.second = amount
        calendar_mark("second")
        calendar_wrap_forward()
    elseif unit == "minute" then
        calendar_state.minute = amount
        calendar_mark("minute")
        calendar_wrap_forward()
    elseif unit == "hour" then
        calendar_state.hour = amount
        calendar_mark("hour")
        calendar_wrap_forward()
    elseif unit == "day" then
        calendar_state.day = math.max(1, amount)
        calendar_mark("day")
        calendar_wrap_forward()
    elseif unit == "month" then
        calendar_state.month = math.max(1, amount)
        calendar_mark("month")
        calendar_wrap_forward()
    elseif unit == "year" then
        calendar_state.year = math.max(1, amount)
        calendar_mark("year")
    end
end

function calendar_advance(unit, amount)
    local delta = tonumber(amount) or 0
    if unit == "second" then
        calendar_state.second = calendar_state.second + delta
        calendar_mark("second")
    elseif unit == "minute" then
        calendar_state.minute = calendar_state.minute + delta
        calendar_mark("minute")
    elseif unit == "hour" then
        calendar_state.hour = calendar_state.hour + delta
        calendar_mark("hour")
    elseif unit == "day" then
        calendar_state.day = calendar_state.day + delta
        calendar_mark("day")
    elseif unit == "month" then
        calendar_state.month = calendar_state.month + delta
        calendar_mark("month")
    elseif unit == "year" then
        calendar_state.year = math.max(1, calendar_state.year + delta)
        calendar_mark("year")
    end
    calendar_wrap_forward()
end

function calendar_tick(delta_ms)
    if not calendar_cfg.auto_advance then
        return false
    end
    calendar_accum_ms = calendar_accum_ms + (tonumber(delta_ms) or 0)
    local changed = false
    while calendar_accum_ms >= calendar_cfg.ms_per_second do
        calendar_accum_ms = calendar_accum_ms - calendar_cfg.ms_per_second
        calendar_advance("second", 1)
        changed = true
    end
    return changed
end

function calendar_consume_changed(unit)
    if calendar_changed[unit] then
        calendar_changed[unit] = false
        return true
    end
    return false
end

function calendar_on_change(unit, listener_id)
    local current = calendar_change_count[unit] or 0
    if current <= 0 then
        return false
    end
    local key = tostring(listener_id or "")
    local seen = calendar_listener_seen[key] or 0
    if current ~= seen then
        calendar_listener_seen[key] = current
        return true
    end
    return false
end

function calendar_is_range(unit, minimum, maximum)
    local value = calendar_get(unit)
    return value >= minimum and value <= maximum
end
""".strip()


CALENDAR_COMPONENT_DEFAULTS = {
    "auto_advance": True,
    "ms_per_second": 1000.0,
    "seconds_per_minute": 60,
    "start_second": 0,
    "start_minute": 0,
    "start_hour": 8,
    "start_day": 1,
    "start_month": 1,
    "start_year": 1,
    "days_per_week": 7,
    "days_per_month": 30,
    "months_per_year": 12,
    "weekday_names": "Sun,Mon,Tue,Wed,Thu,Fri,Sat",
    "month_names": "Month 1,Month 2,Month 3,Month 4,Month 5,Month 6,Month 7,Month 8,Month 9,Month 10,Month 11,Month 12",
}


PLUGIN = {
    "name": "Calendar",
    "components": [
        {
            "type": "Calendar",
            "label": "Calendar",
            "color": "#f97316",
            "singleton": True,
            "defaults": dict(CALENDAR_COMPONENT_DEFAULTS),
            "fields": [
                {"type": "section", "label": "TIME"},
                {"key": "auto_advance", "type": "bool", "label": "Auto Advance", "default": True},
                {"key": "ms_per_second", "type": "float", "label": "Milliseconds per Second", "default": 1000.0, "min": 1.0, "max": 600000.0, "step": 50.0},
                {"key": "seconds_per_minute", "type": "int", "label": "Seconds per Minute", "default": 60, "min": 1, "max": 3600},
                {"type": "section", "label": "START"},
                {"key": "start_second", "type": "int", "label": "Start Second", "default": 0, "min": 0, "max": 59},
                {"key": "start_minute", "type": "int", "label": "Start Minute", "default": 0, "min": 0, "max": 59},
                {"key": "start_hour", "type": "int", "label": "Start Hour", "default": 8, "min": 0, "max": 23},
                {"key": "start_day", "type": "int", "label": "Start Day", "default": 1, "min": 1, "max": 9999},
                {"key": "start_month", "type": "int", "label": "Start Month", "default": 1, "min": 1, "max": 9999},
                {"key": "start_year", "type": "int", "label": "Start Year", "default": 1, "min": 1, "max": 9999},
                {"type": "section", "label": "CALENDAR"},
                {"key": "days_per_week", "type": "int", "label": "Days per Week", "default": 7, "min": 1, "max": 31},
                {"key": "days_per_month", "type": "int", "label": "Days per Month", "default": 30, "min": 1, "max": 365},
                {"key": "months_per_year", "type": "int", "label": "Months per Year", "default": 12, "min": 1, "max": 24},
                {"key": "weekday_names", "type": "str", "label": "Weekday Names (CSV)", "default": "Sun,Mon,Tue,Wed,Thu,Fri,Sat"},
                {"key": "month_names", "type": "str", "label": "Month Names (CSV)", "default": "Month 1,Month 2,Month 3,Month 4,Month 5,Month 6,Month 7,Month 8,Month 9,Month 10,Month 11,Month 12"},
            ],
            "lua_lib": CALENDAR_LUA,
            "lua_scene_init": _calendar_scene_init,
            "lua_scene_loop": _calendar_scene_loop,
        },
    ],
    "triggers": [
        {
            "key": "on_time_change",
            "label": "On Calendar Unit Change",
            "category": "Calendar",
            "fields": [
                {
                    "key": "calendar_trigger_unit",
                    "type": "combo",
                    "label": "Unit",
                    "options": ["second", "minute", "hour", "day", "month", "year"],
                    "default": "hour",
                },
            ],
            "lua_condition": _on_time_change_condition,
        },
        {
            "key": "on_time_equals",
            "label": "On Calendar Unit Equals",
            "category": "Calendar",
            "fields": [
                {
                    "key": "calendar_trigger_unit",
                    "type": "combo",
                    "label": "Unit",
                    "options": ["second", "minute", "hour", "day", "month", "year"],
                    "default": "hour",
                },
                {
                    "key": "calendar_trigger_value",
                    "type": "int",
                    "label": "Value",
                    "default": 12,
                    "min": 0,
                    "max": 9999,
                },
            ],
            "lua_condition": _on_time_equals_condition,
        },
    ],
    "actions": [
        {
            "key": "advance_time",
            "label": "Advance Time",
            "category": "Calendar",
            "fields": [
                {"key": "calendar_unit", "type": "combo", "label": "Unit", "options": ["second", "minute", "hour", "day", "month", "year"], "default": "second"},
                {"key": "calendar_amount", "type": "int", "label": "Amount", "default": 1, "min": 1, "max": 9999},
            ],
            "lua_export": _advance_time_export,
        },
        {
            "key": "set_time",
            "label": "Set Time Unit",
            "category": "Calendar",
            "fields": [
                {"key": "calendar_unit", "type": "combo", "label": "Unit", "options": ["second", "minute", "hour", "day", "month", "year"], "default": "hour"},
                {"key": "calendar_value", "type": "int", "label": "Value", "default": 0, "min": 0, "max": 9999},
            ],
            "lua_export": _set_time_export,
        },
        {
            "key": "get_time_unit",
            "label": "Store Time Unit",
            "category": "Calendar",
            "fields": [
                {"key": "calendar_unit", "type": "combo", "label": "Unit", "options": ["second", "minute", "hour", "day", "month", "year"], "default": "hour"},
                {"key": "calendar_var", "type": "str", "label": "Variable Name", "default": "calendar_value"},
            ],
            "lua_export": _get_time_unit_export,
        },
        {
            "key": "if_time_equals",
            "label": "If Time Equals",
            "category": "Calendar",
            "fields": [
                {"key": "calendar_unit", "type": "combo", "label": "Unit", "options": ["second", "minute", "hour", "day", "month", "year"], "default": "hour"},
                {"key": "calendar_value", "type": "int", "label": "Value", "default": 12, "min": 0, "max": 9999},
            ],
            "has_branches": True,
            "lua_export": _if_time_equals_export,
        },
        {
            "key": "if_time_range",
            "label": "If Time In Range",
            "category": "Calendar",
            "fields": [
                {"key": "calendar_unit", "type": "combo", "label": "Unit", "options": ["second", "minute", "hour", "day", "month", "year"], "default": "hour"},
                {"key": "calendar_min", "type": "int", "label": "Min", "default": 9, "min": 0, "max": 9999},
                {"key": "calendar_max", "type": "int", "label": "Max", "default": 17, "min": 0, "max": 9999},
            ],
            "has_branches": True,
            "lua_export": _if_time_range_export,
        },
    ],
}

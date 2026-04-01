# plugins/vitals_manager/plugin.py

def _action_data(action, action_key: str) -> dict:
    plugin_data = getattr(action, "plugin_data", {}) or {}
    bucket = plugin_data.get(action_key, {})
    return bucket if isinstance(bucket, dict) else {}

def export_modify_stat(action, vname, project):
    data = _action_data(action, "modify_stat")
    target = data.get("vitals_target", "self")
    stat = data.get("vitals_stat", "health")
    op = data.get("vitals_op", "add")
    val = data.get("vitals_value", "1")
    
    # Returns Lua lines to the engine
    return [f"Vitals.modify('{target}', '{stat}', '{op}', {val})"]

def condition_stat_check(behavior, vname, project):
    plugin_data = getattr(behavior, "plugin_data", {}) or {}
    data = plugin_data.get("on_stat_threshold", {})
    
    stat = data.get("vitals_stat", "health")
    comp = data.get("vitals_compare", "<=")
    val = data.get("vitals_value", "0")
    
    # Return a pure Lua boolean expression
    return f"Vitals.check(self, '{stat}', '{comp}', {val})"

PLUGIN = {
    "name": "Vitals Manager",
    "components": [
        {
            "type": "Vitals",
            "label": "Vitals (Stats)",
            "color": "#ef4444",
            "singleton": False,
            "defaults": {"health": 100, "max_health": 100, "mana": 50, "max_mana": 50},
            "fields": [
                {"type": "section", "label": "BASE STATS"},
                {"key": "health", "type": "int", "label": "Start Health", "default": 100},
                {"key": "max_health", "type": "int", "label": "Max Health", "default": 100},
                {"key": "mana", "type": "int", "label": "Start Mana", "default": 50},
                {"key": "max_mana", "type": "int", "label": "Max Mana", "default": 50},
            ],
            "lua_lib": """
-- Vitals Runtime Library
Vitals = {}
function Vitals.modify(target, stat, op, val)
    local current = get_var(target, stat) or 0
    local max = get_var(target, "max_" .. stat) or 100
    if op == "add" then current = current + val
    elseif op == "sub" then current = current - val
    elseif op == "set" then current = val end
    -- Clamp between 0 and Max
    current = math.max(0, math.min(current, max))
    set_var(target, stat, current)
end

function Vitals.check(obj, stat, comp, val)
    local cur = get_var(obj, stat) or 0
    if comp == "==" then return cur == val
    elseif comp == "<=" then return cur <= val
    elseif comp == ">=" then return cur >= val
    end
    return false
end
            """,
        }
    ],
    "triggers": [
        {
            "key": "on_stat_threshold",
            "label": "On Stat Threshold",
            "category": "Vitals",
            "fields": [
                {"key": "vitals_stat", "type": "combo", "label": "Stat", "options": ["health", "mana"], "default": "health"},
                {"key": "vitals_compare", "type": "combo", "label": "When", "options": ["<=", "==", ">="], "default": "<="},
                {"key": "vitals_value", "type": "int", "label": "Value", "default": 0},
            ],
            "lua_condition": condition_stat_check,
        }
    ],
    "actions": [
        {
            "key": "modify_stat",
            "label": "Modify Vital Stat",
            "category": "Vitals",
            "fields": [
                {"key": "vitals_target", "type": "str", "label": "Target ID", "default": "self"},
                {"key": "vitals_stat", "type": "combo", "label": "Stat", "options": ["health", "mana"], "default": "health"},
                {"key": "vitals_op", "type": "combo", "label": "Operation", "options": ["add", "sub", "set"], "default": "sub"},
                {"key": "vitals_value", "type": "int", "label": "Amount", "default": 10},
            ],
            "lua_export": export_modify_stat,
        }
    ],
}
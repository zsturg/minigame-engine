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


_EMPTY_LUA_STRING = '""'


def _source_expr(var_name: str, fallback: str) -> str:
    ident = _safe_ident(var_name)
    return f"{ident}" if ident else fallback


def _assign_target(lines: list[str], target_name: str, expr: str) -> None:
    ident = _safe_ident(target_name)
    if ident:
        lines.append(f"{ident} = {expr}")


def _storage_set_string_export(action, obj_var, project):
    data = _action_data(action, "storage_set_string")
    key = str(data.get("key", "") or "")
    source_var = str(data.get("source_var", "") or "")
    return [f"storage_set_string({_lua_str(key)}, tostring({_source_expr(source_var, _EMPTY_LUA_STRING)} or \"\"))"]


def _storage_get_string_export(action, obj_var, project):
    data = _action_data(action, "storage_get_string")
    key = str(data.get("key", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_get_string({_lua_str(key)})")
    return lines


def _storage_set_number_export(action, obj_var, project):
    data = _action_data(action, "storage_set_number")
    key = str(data.get("key", "") or "")
    source_var = str(data.get("source_var", "") or "")
    return [f"storage_set_number({_lua_str(key)}, {_source_expr(source_var, '0')})"]


def _storage_get_number_export(action, obj_var, project):
    data = _action_data(action, "storage_get_number")
    key = str(data.get("key", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_get_number({_lua_str(key)})")
    return lines


def _storage_set_bool_export(action, obj_var, project):
    data = _action_data(action, "storage_set_bool")
    key = str(data.get("key", "") or "")
    source_var = str(data.get("source_var", "") or "")
    return [f"storage_set_bool({_lua_str(key)}, {_source_expr(source_var, 'false')})"]


def _storage_get_bool_export(action, obj_var, project):
    data = _action_data(action, "storage_get_bool")
    key = str(data.get("key", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_get_bool({_lua_str(key)})")
    return lines


def _storage_delete_value_export(action, obj_var, project):
    data = _action_data(action, "storage_delete_value")
    key = str(data.get("key", "") or "")
    return [f"storage_delete_value({_lua_str(key)})"]


def _storage_has_value_export(action, obj_var, project):
    data = _action_data(action, "storage_has_value")
    key = str(data.get("key", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_has_value({_lua_str(key)})")
    return lines


def _storage_save_document_export(action, obj_var, project):
    data = _action_data(action, "storage_save_document")
    document_id = str(data.get("document_id", "") or "")
    source_var = str(data.get("source_var", "") or "")
    return [f"storage_save_document({_lua_str(document_id)}, tostring({_source_expr(source_var, _EMPTY_LUA_STRING)} or \"\"))"]


def _storage_load_document_export(action, obj_var, project):
    data = _action_data(action, "storage_load_document")
    document_id = str(data.get("document_id", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_load_document({_lua_str(document_id)})")
    return lines


def _storage_delete_document_export(action, obj_var, project):
    data = _action_data(action, "storage_delete_document")
    document_id = str(data.get("document_id", "") or "")
    return [f"storage_delete_document({_lua_str(document_id)})"]


def _storage_document_exists_export(action, obj_var, project):
    data = _action_data(action, "storage_document_exists")
    document_id = str(data.get("document_id", "") or "")
    target_var = str(data.get("target_var", "") or "")
    lines: list[str] = []
    _assign_target(lines, target_var, f"storage_document_exists({_lua_str(document_id)})")
    return lines


STORAGE_LUA = """
local function _storage_root()
    return "ux0:data/" .. tostring(System.getTitleID() or "APP") .. "/storage/"
end

local function _storage_valid_ident(name)
    local text = tostring(name or "")
    if text == "" then return false end
    return string.match(text, "^[%w_-]+$") ~= nil
end

local function _storage_ensure_dir(path)
    local dir = tostring(path or "")
    if dir ~= "" and not System.doesDirExist(dir) then
        System.createDirectory(dir)
    end
end

local function _storage_ensure_kv_dir(kind)
    local root = _storage_root()
    local kv_root = root .. "kv/"
    local kind_root = kv_root .. tostring(kind or "") .. "/"
    _storage_ensure_dir(root)
    _storage_ensure_dir(kv_root)
    _storage_ensure_dir(kind_root)
    return kind_root
end

local function _storage_ensure_documents_dir()
    local root = _storage_root()
    local docs = root .. "documents/"
    _storage_ensure_dir(root)
    _storage_ensure_dir(docs)
    return docs
end

local function _storage_kv_path(kind, key)
    if not _storage_valid_ident(key) then return nil end
    return _storage_root() .. "kv/" .. tostring(kind or "") .. "/" .. tostring(key) .. ".txt"
end

local function _storage_document_path(document_id)
    if not _storage_valid_ident(document_id) then return nil end
    return _storage_root() .. "documents/" .. tostring(document_id) .. ".txt"
end

local function _storage_write_text(path, text)
    local handle = System.openFile(path, FCREATE)
    if handle == nil then return false end
    local payload = tostring(text or "")
    System.writeFile(handle, payload, string.len(payload))
    System.closeFile(handle)
    return true
end

local function _storage_read_text(path)
    if not path or not System.doesFileExist(path) then return nil end
    local handle = System.openFile(path, FREAD)
    if handle == nil then return nil end
    local size = tonumber(System.sizeFile(handle)) or 0
    local text = ""
    if size > 0 then
        text = System.readFile(handle, size) or ""
    end
    System.closeFile(handle)
    return text
end

local function _storage_delete_file(path)
    if path and System.doesFileExist(path) then
        System.deleteFile(path)
    end
end

local function _storage_bool_value(value)
    if type(value) == "boolean" then return value end
    if type(value) == "number" then return value ~= 0 end
    local text = string.lower(tostring(value or ""))
    return text == "true" or text == "1" or text == "yes" or text == "on"
end

function storage_set_string(key, value)
    if not _storage_valid_ident(key) then return false end
    _storage_ensure_kv_dir("string")
    return _storage_write_text(_storage_kv_path("string", key), tostring(value or ""))
end

function storage_get_string(key)
    local path = _storage_kv_path("string", key)
    local text = _storage_read_text(path)
    return text or ""
end

function storage_set_number(key, value)
    if not _storage_valid_ident(key) then return false end
    _storage_ensure_kv_dir("number")
    return _storage_write_text(_storage_kv_path("number", key), tostring(tonumber(value) or 0))
end

function storage_get_number(key)
    local path = _storage_kv_path("number", key)
    local text = _storage_read_text(path)
    return tonumber(text) or 0
end

function storage_set_bool(key, value)
    if not _storage_valid_ident(key) then return false end
    _storage_ensure_kv_dir("bool")
    return _storage_write_text(_storage_kv_path("bool", key), _storage_bool_value(value) and "1" or "0")
end

function storage_get_bool(key)
    local path = _storage_kv_path("bool", key)
    local text = _storage_read_text(path)
    if text == nil then return false end
    return _storage_bool_value(text)
end

function storage_delete_value(key)
    if not _storage_valid_ident(key) then return false end
    _storage_delete_file(_storage_kv_path("string", key))
    _storage_delete_file(_storage_kv_path("number", key))
    _storage_delete_file(_storage_kv_path("bool", key))
    return true
end

function storage_has_value(key)
    if not _storage_valid_ident(key) then return false end
    return System.doesFileExist(_storage_kv_path("string", key))
        or System.doesFileExist(_storage_kv_path("number", key))
        or System.doesFileExist(_storage_kv_path("bool", key))
end

function storage_save_document(document_id, text)
    if not _storage_valid_ident(document_id) then return false end
    _storage_ensure_documents_dir()
    return _storage_write_text(_storage_document_path(document_id), tostring(text or ""))
end

function storage_load_document(document_id)
    local path = _storage_document_path(document_id)
    local text = _storage_read_text(path)
    return text or ""
end

function storage_delete_document(document_id)
    if not _storage_valid_ident(document_id) then return false end
    _storage_delete_file(_storage_document_path(document_id))
    return true
end

function storage_document_exists(document_id)
    local path = _storage_document_path(document_id)
    return path ~= nil and System.doesFileExist(path)
end
""".strip()


PLUGIN = {
    "name": "Built-in Storage Pack",
    "components": [
        {
            "type": "StorageService",
            "label": "Storage Service",
            "color": "#22c55e",
            "singleton": True,
            "defaults": {},
            "fields": [],
            "lua_lib": STORAGE_LUA,
        }
    ],
    "actions": [
        {
            "key": "storage_set_string",
            "label": "Set String",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "source_var", "type": "str", "label": "Source Variable", "default": ""},
            ],
            "lua_export": _storage_set_string_export,
        },
        {
            "key": "storage_get_string",
            "label": "Get String",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_get_string_export,
        },
        {
            "key": "storage_set_number",
            "label": "Set Number",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "source_var", "type": "str", "label": "Source Variable", "default": ""},
            ],
            "lua_export": _storage_set_number_export,
        },
        {
            "key": "storage_get_number",
            "label": "Get Number",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_get_number_export,
        },
        {
            "key": "storage_set_bool",
            "label": "Set Bool",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "source_var", "type": "str", "label": "Source Variable", "default": ""},
            ],
            "lua_export": _storage_set_bool_export,
        },
        {
            "key": "storage_get_bool",
            "label": "Get Bool",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_get_bool_export,
        },
        {
            "key": "storage_delete_value",
            "label": "Delete Value",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
            ],
            "lua_export": _storage_delete_value_export,
        },
        {
            "key": "storage_has_value",
            "label": "Has Value",
            "category": "Storage",
            "fields": [
                {"key": "key", "type": "str", "label": "Key", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_has_value_export,
        },
        {
            "key": "storage_save_document",
            "label": "Save Document",
            "category": "Storage",
            "fields": [
                {"key": "document_id", "type": "str", "label": "Document ID", "default": ""},
                {"key": "source_var", "type": "str", "label": "Source Variable", "default": ""},
            ],
            "lua_export": _storage_save_document_export,
        },
        {
            "key": "storage_load_document",
            "label": "Load Document",
            "category": "Storage",
            "fields": [
                {"key": "document_id", "type": "str", "label": "Document ID", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_load_document_export,
        },
        {
            "key": "storage_delete_document",
            "label": "Delete Document",
            "category": "Storage",
            "fields": [
                {"key": "document_id", "type": "str", "label": "Document ID", "default": ""},
            ],
            "lua_export": _storage_delete_document_export,
        },
        {
            "key": "storage_document_exists",
            "label": "Document Exists",
            "category": "Storage",
            "fields": [
                {"key": "document_id", "type": "str", "label": "Document ID", "default": ""},
                {"key": "target_var", "type": "str", "label": "Target Variable", "default": ""},
            ],
            "lua_export": _storage_document_exists_export,
        },
    ],
}

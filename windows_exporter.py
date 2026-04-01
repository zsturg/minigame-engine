"""Windows / LOVE2D export support for Vita Adventure Creator."""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from lpp_exporter import bake_tile_chunks, export_lpp, get_asset_mapping
from resource_path import resource_path

LOVE_RUNTIME_DIR = Path(resource_path("love_runtime"))
RAYCAST_RUNTIME_FILE = Path(resource_path("raycast3d.lua"))
WINDOWS_PREVIEW_WIDTH = 960
WINDOWS_PREVIEW_HEIGHT = 544


LOVE_ENGINE_SHIM_TEMPLATE = r"""
-- engine.lua - LPP-Vita API shim for LOVE 11+

local PROJECT_TITLE = __PROJECT_TITLE__
local PROJECT_TITLE_ID = __PROJECT_TITLE_ID__

SCE_CTRL_CROSS = "cross"
SCE_CTRL_CIRCLE = "circle"
SCE_CTRL_SQUARE = "square"
SCE_CTRL_TRIANGLE = "triangle"
SCE_CTRL_UP = "up"
SCE_CTRL_DOWN = "down"
SCE_CTRL_LEFT = "left"
SCE_CTRL_RIGHT = "right"
SCE_CTRL_START = "start"
SCE_CTRL_SELECT = "select"
SCE_CTRL_LTRIGGER = "l"
SCE_CTRL_RTRIGGER = "r"

RUNNING = "running"
FINISHED = "finished"
CANCELED = "canceled"

BUTTON_OK = "button_ok"
BUTTON_YES_NO = "button_yes_no"
TYPE_DEFAULT = "type_default"
MODE_TEXT = "mode_text"
OPT_NO_AUTOCAP = "opt_no_autocap"

FREAD = "fread"
FCREATE = "fcreate"

local _window_width = 960
local _window_height = 544

local _key_map = {
    z = "cross",
    space = "cross",
    x = "circle",
    a = "square",
    s = "triangle",
    up = "up",
    down = "down",
    left = "left",
    right = "right",
    ["return"] = "start",
    escape = "select",
    q = "l",
    e = "r",
}

local _pressed = {}
local _held = {}
local _released = {}
local _mouse_down = false
local _default_font = nil
local _game_co = nil

local _message_modal = {
    active = false,
    state = FINISHED,
    text = "",
    buttons = BUTTON_OK,
}

local _keyboard_modal = {
    active = false,
    state = FINISHED,
    title = "",
    input = "",
    max_length = 240,
}

local _save_root = nil
local _orig_io_open = io.open

local function _normalize_path(path)
    return tostring(path or ""):gsub("\\", "/")
end

local function _archive_path(path)
    local text = _normalize_path(path)
    text = text:gsub("^app0:/", "")
    text = text:gsub("^sa0:data/font/pvf/", "assets/fonts/")
    return text
end

local function _save_relative_path(path)
    local text = _normalize_path(path)
    if text:match("^ux0:data/") then
        local rest = text:sub(#"ux0:data/" + 1)
        local slash = rest:find("/", 1, true)
        if slash then
            return rest:sub(slash + 1)
        end
        return ""
    end
    if text:match("^app0:/") or text:match("^sa0:data/font/pvf/") then
        return nil
    end
    if text:match("^[A-Za-z]:/") or text:match("^/") then
        return nil
    end
    return text
end

local function _join_path(base, rel)
    local clean_base = _normalize_path(base)
    local clean_rel = _normalize_path(rel)
    if clean_rel == "" then
        return clean_base
    end
    if clean_base:sub(-1) == "/" then
        return clean_base .. clean_rel
    end
    return clean_base .. "/" .. clean_rel
end

local function _save_absolute_path(path)
    local rel = _save_relative_path(path)
    if rel ~= nil then
        return _join_path(_save_root, rel)
    end
    return _normalize_path(path)
end

local function _save_parent(path)
    local rel = _save_relative_path(path)
    if rel == nil or rel == "" then
        return ""
    end
    return rel:match("^(.*)/[^/]+$") or ""
end

local function _ensure_save_directory(rel)
    rel = _normalize_path(rel)
    if rel == "" then
        return true
    end
    local current = ""
    for segment in rel:gmatch("[^/]+") do
        current = current == "" and segment or (current .. "/" .. segment)
        local ok = love.filesystem.createDirectory(current)
        if not ok and not love.filesystem.getInfo(current, "directory") then
            return false
        end
    end
    return true
end

local function _is_modal_active()
    return _keyboard_modal.active or _message_modal.active
end

local function _analog_axis(negative_btn, positive_btn)
    local negative_down = _held[negative_btn] == true
    local positive_down = _held[positive_btn] == true
    if negative_down and not positive_down then
        return 0
    end
    if positive_down and not negative_down then
        return 255
    end
    return 128
end

local function _pop_last_utf8(text)
    if utf8 and utf8.offset then
        local byte_offset = utf8.offset(text, -1)
        if byte_offset then
            return text:sub(1, byte_offset - 1)
        end
    end
    return text:sub(1, math.max(#text - 1, 0))
end

local function _handle_keyboard_keypress(key)
    if not _keyboard_modal.active or _keyboard_modal.state ~= RUNNING then
        return false
    end
    if key == "return" or key == "kpenter" then
        _keyboard_modal.state = FINISHED
        return true
    end
    if key == "escape" then
        _keyboard_modal.state = CANCELED
        return true
    end
    if key == "backspace" then
        _keyboard_modal.input = _pop_last_utf8(_keyboard_modal.input)
        return true
    end
    return true
end

local function _handle_message_keypress(key)
    if not _message_modal.active or _message_modal.state ~= RUNNING then
        return false
    end
    if _message_modal.buttons == BUTTON_YES_NO then
        if key == "return" or key == "kpenter" or key == "space" or key == "z" then
            _message_modal.state = FINISHED
        elseif key == "escape" or key == "x" then
            _message_modal.state = CANCELED
        end
        return true
    end
    if key == "return" or key == "kpenter" or key == "space" or key == "z" or key == "escape" or key == "x" then
        _message_modal.state = FINISHED
    end
    return true
end

local function _handle_message_mousepress(button)
    if not _message_modal.active or _message_modal.state ~= RUNNING then
        return false
    end
    if _message_modal.buttons == BUTTON_YES_NO and button == 2 then
        _message_modal.state = CANCELED
        return true
    end
    if button == 1 or button == 2 then
        _message_modal.state = FINISHED
        return true
    end
    return false
end

local function _draw_modal_backdrop()
    love.graphics.setColor(0, 0, 0, 0.65)
    love.graphics.rectangle("fill", 0, 0, _window_width, _window_height)
end

local function _draw_message_modal()
    if not _message_modal.active then
        return
    end
    _draw_modal_backdrop()
    love.graphics.setColor(0.12, 0.12, 0.12, 0.96)
    love.graphics.rectangle("fill", 120, 168, 720, 208, 10, 10)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.printf(_message_modal.text or "", 156, 214, 648, "center")
    local prompt = "[Enter/Z] OK"
    if _message_modal.buttons == BUTTON_YES_NO then
        prompt = "[Enter/Z] Yes    [Esc/X] No"
    end
    love.graphics.printf(prompt, 156, 320, 648, "center")
end

local function _draw_keyboard_modal()
    if not _keyboard_modal.active then
        return
    end
    _draw_modal_backdrop()
    love.graphics.setColor(0.12, 0.12, 0.12, 0.96)
    love.graphics.rectangle("fill", 96, 136, 768, 272, 10, 10)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.printf(_keyboard_modal.title or "Keyboard Input", 132, 176, 696, "center")
    love.graphics.setColor(0.18, 0.18, 0.18, 1)
    love.graphics.rectangle("fill", 144, 238, 672, 72, 8, 8)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.printf(_keyboard_modal.input or "", 168, 262, 624, "left")
    love.graphics.printf("[Type] Enter to submit    Esc to cancel", 144, 344, 672, "center")
end

Color = {}

function Color.new(r, g, b, a)
    return {
        (r or 255) / 255,
        (g or 255) / 255,
        (b or 255) / 255,
        (a ~= nil and a or 255) / 255,
    }
end

local _font_cache = {}
local _font_paths = {}
local _font_sizes = {}

Font = {}

function Font.load(path)
    local clean = _archive_path(path)
    local key = clean .. ":20"
    if not _font_cache[key] then
        local ok, font = pcall(love.graphics.newFont, clean, 20)
        if not ok then
            font = love.graphics.newFont(20)
        end
        _font_cache[key] = font
        _font_paths[font] = clean
        _font_sizes[font] = 20
    end
    return _font_cache[key]
end

function Font.setPixelSizes(font_obj, size)
    if not font_obj then
        return
    end
    _font_sizes[font_obj] = size or 20
end

local function _get_sized_font(font_obj, size)
    local path = _font_paths[font_obj]
    if not path then
        return font_obj
    end
    local key = path .. ":" .. tostring(size)
    if not _font_cache[key] then
        local ok, font = pcall(love.graphics.newFont, path, size)
        if not ok then
            font = love.graphics.newFont(size)
        end
        _font_cache[key] = font
        _font_paths[font] = path
        _font_sizes[font] = size
    end
    return _font_cache[key]
end

function Font.print(font_obj, x, y, text, color)
    if not font_obj then
        return
    end
    local size = _font_sizes[font_obj]
    local actual = (size and size ~= 20) and _get_sized_font(font_obj, size) or font_obj
    love.graphics.setFont(actual)
    if color then
        love.graphics.setColor(color)
    else
        love.graphics.setColor(1, 1, 1, 1)
    end
    love.graphics.print(tostring(text), x, y)
end

function Font.getTextWidth(font_obj, text)
    if not font_obj then
        return 0
    end
    local size = _font_sizes[font_obj]
    local actual = (size and size ~= 20) and _get_sized_font(font_obj, size) or font_obj
    return actual:getWidth(tostring(text))
end

local ImageWrapper = {}
ImageWrapper.__index = ImageWrapper

function ImageWrapper:getWidth()
    return self._w
end

function ImageWrapper:getHeight()
    return self._h
end

local _image_cache = {}

Graphics = {}

function Graphics.loadImage(path)
    local clean = _archive_path(path)
    if _image_cache[clean] then
        return _image_cache[clean]
    end
    local ok, image = pcall(love.graphics.newImage, clean)
    if not ok then
        print("[engine] Graphics.loadImage failed: " .. clean)
        return nil
    end
    local wrapper = setmetatable(
        {
            _data = image,
            _w = image:getWidth(),
            _h = image:getHeight(),
        },
        ImageWrapper
    )
    _image_cache[clean] = wrapper
    return wrapper
end

function Graphics.getImageWidth(image)
    if image and image._w then
        return image._w
    end
    return 0
end

function Graphics.getImageHeight(image)
    if image and image._h then
        return image._h
    end
    return 0
end

function Graphics.initBlend()
end

function Graphics.termBlend()
end

function Graphics.drawImage(x, y, image)
    if not image or not image._data then
        return
    end
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(image._data, x, y)
end

function Graphics.drawPartialImage(x, y, image, sx, sy, sw, sh)
    if not image or not image._data then
        return
    end
    love.graphics.setColor(1, 1, 1, 1)
    local quad = love.graphics.newQuad(sx, sy, sw, sh, image._w, image._h)
    love.graphics.draw(image._data, quad, x, y)
end

function Graphics.drawImageExtended(cx, cy, image, sx, sy, sw, sh, angle_deg, xscale, yscale, color)
    if not image or not image._data then
        return
    end
    if color then
        love.graphics.setColor(color)
    else
        love.graphics.setColor(1, 1, 1, 1)
    end
    local quad = love.graphics.newQuad(sx, sy, sw, sh, image._w, image._h)
    local radians = (angle_deg or 0) * math.pi / 180
    love.graphics.draw(
        image._data,
        quad,
        cx,
        cy,
        radians,
        xscale or 1,
        yscale or 1,
        sw * 0.5,
        sh * 0.5
    )
end

function Graphics.drawScaleImage(x, y, image, xscale, yscale, color)
    if not image or not image._data then
        return
    end
    if color then
        love.graphics.setColor(color)
    else
        love.graphics.setColor(1, 1, 1, 1)
    end
    love.graphics.draw(image._data, x, y, 0, xscale or 1, yscale or 1)
end

function Graphics.fillRect(x1, x2, y1, y2, color)
    if color then
        love.graphics.setColor(color)
    else
        love.graphics.setColor(0, 0, 0, 1)
    end
    love.graphics.rectangle("fill", x1, y1, x2 - x1, y2 - y1)
end

Screen = {}

function Screen.clear(color)
    if color then
        love.graphics.setBackgroundColor(color)
    end
    love.graphics.clear()
end

function Screen.flip()
    coroutine.yield()
end

function Screen.waitVblankStart()
    coroutine.yield()
end

local _sound_sources = {}

Sound = {}

function Sound.init()
end

function Sound.open(path)
    local clean = _archive_path(path)
    if _sound_sources[clean] then
        return _sound_sources[clean]
    end
    local source_type = (clean:find("music") or clean:find("bgm")) and "stream" or "static"
    local ok, source = pcall(love.audio.newSource, clean, source_type)
    if not ok then
        print("[engine] Sound.open failed: " .. clean)
        return nil
    end
    _sound_sources[clean] = source
    return source
end

function Sound.play(source, loop)
    if not source then
        return
    end
    source:setLooping(loop == true)
    if source:isPlaying() then
        source:stop()
    end
    source:play()
end

function Sound.stop(source)
    if source then
        source:stop()
    end
end

function Sound.close(source)
    if source then
        source:stop()
    end
end

function Sound.pause(source)
    if source and source:isPlaying() then
        source:pause()
    end
end

function Sound.resume(source)
    if source and not source:isPlaying() then
        source:play()
    end
end

function Sound.setVolume(source, lpp_volume)
    if source then
        source:setVolume((lpp_volume or 32767) / 32767)
    end
end

function Sound.getVolume(source)
    if source then
        return math.floor(source:getVolume() * 32767)
    end
    return 0
end

Timer = {}

function Timer.new()
    return { _start = love.timer.getTime() }
end

function Timer.reset(timer_obj)
    if timer_obj then
        timer_obj._start = love.timer.getTime()
    end
end

function Timer.getTime(timer_obj)
    if not timer_obj then
        return 0
    end
    return math.floor((love.timer.getTime() - timer_obj._start) * 1000)
end

function Timer.destroy(timer_obj)
end

Controls = {}

function Controls.read()
    local snapshot = {}
    for key, value in pairs(_held) do
        snapshot[key] = value
    end
    return snapshot
end

function Controls.check(snapshot, button)
    if type(snapshot) == "table" then
        return snapshot[button] == true
    end
    return false
end

function Controls.readLeftAnalog()
    return _analog_axis("left", "right"), _analog_axis("up", "down")
end

function Controls.readRightAnalog()
    return _analog_axis("l", "r"), 128
end

function Controls.readTouch()
    if _mouse_down then
        local mx, my = love.mouse.getPosition()
        return mx, my
    end
    return 0, 0
end

Keyboard = {}

function Keyboard.start(title, text, max_length, keyboard_type, keyboard_mode, keyboard_option)
    local limit = math.max(1, tonumber(max_length) or 240)
    local initial = tostring(text or "")
    if #initial > limit then
        initial = initial:sub(1, limit)
    end
    _keyboard_modal.active = true
    _keyboard_modal.state = RUNNING
    _keyboard_modal.title = tostring(title or "Keyboard Input")
    _keyboard_modal.input = initial
    _keyboard_modal.max_length = limit
end

function Keyboard.getState()
    return _keyboard_modal.state or FINISHED
end

function Keyboard.getInput()
    return _keyboard_modal.input or ""
end

function Keyboard.clear()
    _keyboard_modal.active = false
    _keyboard_modal.state = FINISHED
    _keyboard_modal.title = ""
    _keyboard_modal.input = ""
    _keyboard_modal.max_length = 240
end

System = {}

function System.setCpuSpeed(mhz)
end

function System.getTitleID()
    return PROJECT_TITLE_ID
end

function System.getDate()
    local now = os.date("*t")
    return now.wday, now.day, now.month, now.year
end

function System.getTime()
    local now = os.date("*t")
    return now.hour, now.min, now.sec
end

function System.wait(ms)
    if coroutine.running() then
        coroutine.yield()
    elseif ms and ms > 0 then
        love.timer.sleep(ms / 1000)
    end
end

function System.setMessage(text, unused_allow_cancel, buttons)
    _message_modal.active = true
    _message_modal.state = RUNNING
    _message_modal.text = tostring(text or "")
    _message_modal.buttons = buttons or BUTTON_OK
end

function System.getMessageState()
    return _message_modal.state or FINISHED
end

function System.closeMessage()
    _message_modal.active = false
    _message_modal.state = FINISHED
    _message_modal.text = ""
    _message_modal.buttons = BUTTON_OK
end

function System.createDirectory(path)
    local rel = _save_relative_path(path)
    if rel == nil then
        return false
    end
    return _ensure_save_directory(rel)
end

function System.doesDirExist(path)
    local rel = _save_relative_path(path)
    if rel ~= nil then
        return love.filesystem.getInfo(rel, "directory") ~= nil
    end
    return love.filesystem.getInfo(_archive_path(path), "directory") ~= nil
end

function System.doesFileExist(path)
    local rel = _save_relative_path(path)
    if rel ~= nil then
        return love.filesystem.getInfo(rel, "file") ~= nil
    end
    return love.filesystem.getInfo(_archive_path(path), "file") ~= nil
end

function System.openFile(path, mode)
    local abs = _save_absolute_path(path)
    local parent = _save_parent(path)
    if mode == FCREATE then
        _ensure_save_directory(parent)
        return _orig_io_open(abs, "wb")
    end
    return _orig_io_open(abs, "rb")
end

function System.writeFile(handle, payload, size)
    if not handle then
        return false
    end
    local text = tostring(payload or "")
    if size ~= nil then
        text = text:sub(1, size)
    end
    handle:write(text)
    return true
end

function System.readFile(handle, size)
    if not handle then
        return nil
    end
    if size ~= nil then
        return handle:read(size)
    end
    return handle:read("*a")
end

function System.sizeFile(handle)
    if not handle then
        return 0
    end
    local cursor = handle:seek()
    local size = handle:seek("end")
    handle:seek("set", cursor)
    return size or 0
end

function System.closeFile(handle)
    if handle then
        handle:close()
    end
end

function System.deleteFile(path)
    local rel = _save_relative_path(path)
    if rel == nil then
        return false
    end
    return love.filesystem.remove(rel)
end

function io.open(path, mode)
    local text = _normalize_path(path)
    if text:match("^ux0:data/") then
        return _orig_io_open(_save_absolute_path(text), mode)
    end
    return _orig_io_open(path, mode)
end

local _orig_exit = os.exit

function os.exit(code)
    love.event.quit(code or 0)
end

function love.load()
    _save_root = _normalize_path(love.filesystem.getSaveDirectory())
    love.window.setTitle(PROJECT_TITLE .. " - Windows Preview")
    _default_font = love.graphics.newFont(20)
    love.graphics.setFont(_default_font)
    if main_game_loop then
        _game_co = coroutine.create(main_game_loop)
    else
        print("[engine] main_game_loop not defined - check index.lua")
    end
end

function love.keypressed(key, scancode, isrepeat)
    if _handle_keyboard_keypress(key) then
        return
    end
    if _handle_message_keypress(key) then
        return
    end
    local button = _key_map[key]
    if button then
        _pressed[button] = true
        _held[button] = true
    end
end

function love.keyreleased(key)
    local button = _key_map[key]
    if button then
        _held[button] = false
        if not _is_modal_active() then
            _released[button] = true
        end
    end
end

function love.textinput(text)
    if not _keyboard_modal.active or _keyboard_modal.state ~= RUNNING then
        return
    end
    if #_keyboard_modal.input >= _keyboard_modal.max_length then
        return
    end
    local remaining = _keyboard_modal.max_length - #_keyboard_modal.input
    _keyboard_modal.input = _keyboard_modal.input .. text:sub(1, remaining)
end

function love.mousepressed(x, y, button)
    if _handle_message_mousepress(button) then
        return
    end
    if button == 1 then
        _mouse_down = true
    end
end

function love.mousereleased(x, y, button)
    if button == 1 then
        _mouse_down = false
    end
end

function love.update(dt)
end

function love.draw()
    if _game_co and coroutine.status(_game_co) ~= "dead" then
        local ok, err = coroutine.resume(_game_co)
        if not ok then
            love.graphics.setColor(1, 0, 0, 1)
            love.graphics.print("Game error:\n" .. tostring(err), 20, 20)
        end
    end
    _draw_message_modal()
    _draw_keyboard_modal()
    _pressed = {}
    _released = {}
end
"""


def _lua_string(value: str) -> str:
    text = str(value or "")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _project_has_3d(project) -> bool:
    return any(getattr(scene, "scene_type", "2d") == "3d" for scene in getattr(project, "scenes", []))


def _render_engine_shim(project) -> str:
    return (
        LOVE_ENGINE_SHIM_TEMPLATE.replace("__PROJECT_TITLE__", _lua_string(project.title))
        .replace("__PROJECT_TITLE_ID__", _lua_string(project.title_id))
    )


def _patch_index_for_love(index_source: str) -> str:
    source = re.sub(
        r"require\(['\"]lib/([^'\"]+)['\"]\)",
        lambda match: f"require('lib.{match.group(1)}')",
        index_source,
    )
    source = re.sub(
        r"dofile\(['\"](?:app0:/)?scenes/([^'\"]+)['\"]\)",
        lambda match: f"assert(love.filesystem.load('scenes/{match.group(1)}'))()",
        source,
    )
    source = re.sub(
        r"dofile\(['\"](?:app0:/)?files/([^'\"]+)['\"]\)",
        lambda match: f"assert(love.filesystem.load('files/{match.group(1)}'))()",
        source,
    )
    if "function main_game_loop()" not in source and "while running do" in source:
        source = source.replace("while running do", "function main_game_loop()\nwhile running do", 1)
        source = source.rstrip() + "\nend -- main_game_loop\n"
    return source


def _love_conf_source(project) -> str:
    return (
        "function love.conf(t)\n"
        f"    t.identity = {_lua_string(project.title_id)}\n"
        f"    t.window.title = {_lua_string(project.title)}\n"
        f"    t.window.width = {WINDOWS_PREVIEW_WIDTH}\n"
        f"    t.window.height = {WINDOWS_PREVIEW_HEIGHT}\n"
        "    t.console = true\n"
        "end\n"
    )


def _love_main_source() -> str:
    return (
        "-- Auto-generated by Vita Adventure Creator (Windows Export)\n"
        "\n"
        "table.insert(package.loaders or package.searchers, 1, function(name)\n"
        '    local path = name:gsub("%.", "/") .. ".lua"\n'
        "    if love.filesystem.getInfo(path) then\n"
        "        return function(...)\n"
        "            return assert(love.filesystem.load(path))(...)\n"
        "        end\n"
        "    end\n"
        "end)\n"
        "\n"
        'assert(love.filesystem.load("engine.lua"))()\n'
        'assert(love.filesystem.load("index.lua"))()\n'
    )


def _write_generated_lua(project, build_dir: Path) -> dict[str, str]:
    lua_files = export_lpp(project)
    lua_files["index.lua"] = _patch_index_for_love(lua_files["index.lua"])

    for rel_path, source in lua_files.items():
        destination = build_dir / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")

    (build_dir / "engine.lua").write_text(_render_engine_shim(project), encoding="utf-8")
    (build_dir / "conf.lua").write_text(_love_conf_source(project), encoding="utf-8")
    (build_dir / "main.lua").write_text(_love_main_source(), encoding="utf-8")

    if _project_has_3d(project):
        if not RAYCAST_RUNTIME_FILE.exists():
            raise FileNotFoundError("raycast3d.lua not found next to the exporter")
        raycast_destination = build_dir / "files" / "raycast3d.lua"
        raycast_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAYCAST_RUNTIME_FILE, raycast_destination)

    return lua_files


def _copy_project_assets(project, build_dir: Path) -> None:
    for src_path, rel_dest in get_asset_mapping(project).items():
        if os.path.exists(src_path):
            destination = build_dir / rel_dest
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src_path, destination)

    default_font_src = Path(resource_path("assets/fonts/font.ttf"))
    default_font_dst = build_dir / "assets" / "fonts" / "font.ttf"
    if default_font_src.exists():
        default_font_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(default_font_src, default_font_dst)

    if project.project_folder:
        animation_src = Path(project.project_folder) / "animations"
        animation_dst = build_dir / "assets" / "animations"
        if animation_src.exists():
            animation_dst.mkdir(parents=True, exist_ok=True)
            for source_file in animation_src.iterdir():
                if source_file.is_file():
                    shutil.copy(source_file, animation_dst / source_file.name)


def _bake_project_tile_chunks(project, build_dir: Path) -> None:
    try:
        bake_tile_chunks(project, build_dir)
    except ImportError:
        print("[windows_exporter] Pillow not installed - tile chunks skipped.")
    except Exception as exc:  # pragma: no cover - defensive logging for local builds
        print(f"[windows_exporter] Tile chunk bake error: {exc}")


def _package_love_archive(build_dir: Path, love_file: Path) -> None:
    with zipfile.ZipFile(love_file, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in build_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(build_dir))


def _fuse_windows_executable(runtime_dir: Path, love_file: Path, final_exe: Path) -> None:
    love_exe = runtime_dir / "love.exe"
    if not love_exe.exists():
        raise FileNotFoundError("love.exe not found in the LOVE runtime directory")

    with open(final_exe, "wb") as output_file:
        output_file.write(love_exe.read_bytes())
        output_file.write(love_file.read_bytes())


def _copy_runtime_support_files(runtime_dir: Path, export_root: Path) -> None:
    for runtime_file in runtime_dir.iterdir():
        if runtime_file.suffix.lower() == ".dll" or runtime_file.name.lower() in {"license.txt", "readme.txt"}:
            shutil.copy(runtime_file, export_root / runtime_file.name)


def _build_windows_export_bundle(
    project,
    export_root: Path | str,
    runtime_dir: Path | str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Path]:
    runtime_dir = Path(runtime_dir or LOVE_RUNTIME_DIR)
    if not runtime_dir.exists():
        raise FileNotFoundError("The 'love_runtime' folder was not found.")

    export_root = Path(export_root)
    build_dir = export_root / "build"
    love_file = export_root / f"{project.title}.love"
    final_exe = export_root / f"{project.title}.exe"

    if export_root.exists():
        shutil.rmtree(export_root)
    build_dir.mkdir(parents=True)

    _write_generated_lua(project, build_dir)
    _copy_project_assets(project, build_dir)
    _bake_project_tile_chunks(project, build_dir)
    _package_love_archive(build_dir, love_file)
    _fuse_windows_executable(runtime_dir, love_file, final_exe)
    _copy_runtime_support_files(runtime_dir, export_root)

    result = {
        "export_root": export_root,
        "build_dir": build_dir,
        "love_file": love_file,
        "final_exe": final_exe,
    }

    if not keep_intermediates:
        shutil.rmtree(build_dir)
        love_file.unlink()

    return result


def export_windows_game(project, parent_window) -> None:
    """Export the project as a fused Windows executable."""

    if not LOVE_RUNTIME_DIR.exists():
        QMessageBox.critical(
            parent_window,
            "Missing LOVE Runtime",
            "The 'love_runtime' folder was not found.\n\n"
            "Download LOVE 11 for Windows (64-bit zip), extract it, "
            "and rename the folder to 'love_runtime' next to this script.",
        )
        return

    export_folder = QFileDialog.getExistingDirectory(parent_window, "Select Export Folder")
    if not export_folder:
        return

    export_root = Path(export_folder) / project.title

    try:
        _build_windows_export_bundle(project, export_root)
        QMessageBox.information(
            parent_window,
            "Export Complete",
            f"Windows build created at:\n{export_root}",
        )
    except Exception as exc:
        import traceback

        traceback.print_exc()
        QMessageBox.critical(parent_window, "Export Failed", str(exc))

# ===== FILE: windows_exporter.py =====
"""
Windows / LÖVE2D export for Vita Adventure Creator.
Mirrors the multi-file structure produced by lpp_exporter.export_lpp():

  index.lua          ← main entry / asset loader / main loop
  lib/controls.lua
  lib/tween.lua
  lib/camera.lua
  lib/shake.lua
  lib/flash.lua
  lib/save.lua       (optional)
  scenes/scene_NNN.lua  (one per scene)
  assets/images/
  assets/audio/
  assets/fonts/
  assets/animations/
  assets/tilechunks/

The LOVE_ENGINE_SHIM replaces every LPP-Vita API call with LÖVE equivalents
so the generated Lua runs unmodified on Windows.
"""

import os
import math
import shutil
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QFileDialog
from lpp_exporter import export_lpp, bake_tile_chunks, get_asset_mapping

LOVE_RUNTIME_DIR = Path("love_runtime")


# ─────────────────────────────────────────────────────────────────────────────
#  LÖVE ENGINE SHIM
#  Maps every LPP-Vita global (Graphics, Sound, Font, Controls, Screen, Color,
#  RayCast3D, System …) onto LÖVE equivalents.
#  Uses a coroutine so the Vita-style "while running do … Screen.flip()" loop
#  yields once per frame instead of blocking LÖVE's update/draw cycle.
# ─────────────────────────────────────────────────────────────────────────────
LOVE_ENGINE_SHIM = r"""
-- ============================================================
--  engine.lua  –  LPP-Vita API shim for LÖVE 11+
-- ============================================================

-- ── Button constants ────────────────────────────────────────
SCE_CTRL_CROSS    = "cross"
SCE_CTRL_CIRCLE   = "circle"
SCE_CTRL_SQUARE   = "square"
SCE_CTRL_TRIANGLE = "triangle"
SCE_CTRL_UP       = "up"
SCE_CTRL_DOWN     = "down"
SCE_CTRL_LEFT     = "left"
SCE_CTRL_RIGHT    = "right"
SCE_CTRL_START    = "start"
SCE_CTRL_SELECT   = "select"
SCE_CTRL_LTRIGGER = "l"
SCE_CTRL_RTRIGGER = "r"

-- 3D movement constants (used by RayCast3D shim)
FORWARD = "forward"
BACK    = "back"
LEFT    = "left_dir"
RIGHT   = "right_dir"

-- ── Input ───────────────────────────────────────────────────
local _key_map = {
    z         = "cross",   space  = "cross",
    x         = "circle",
    a         = "square",
    s         = "triangle",
    up        = "up",
    down      = "down",
    left      = "left",
    right     = "right",
    ["return"]= "start",
    escape    = "select",
    q         = "l",
    e         = "r",
}
local _pressed = {}   -- set once per frame
local _held    = {}   -- held until key-up
local _released = {}  -- set once per frame on key-up

-- ── Color ───────────────────────────────────────────────────
Color = {}
function Color.new(r, g, b, a)
    return { (r or 255)/255, (g or 255)/255, (b or 255)/255, (a ~= nil and a or 255)/255 }
end

-- ── Font ────────────────────────────────────────────────────
local _font_cache  = {}
local _font_sizes  = {}   -- font object → current pixel size
local _default_font = nil

Font = {}
function Font.load(path)
    -- strip Vita-specific prefixes
    local clean = path:gsub("app0:/", ""):gsub("sa0:data/font/pvf/", ""):gsub("ux0:data/", "")
    if not _font_cache[clean] then
        local ok, f = pcall(love.graphics.newFont, clean, 20)
        if not ok then
            f = love.graphics.newFont(20)
        end
        _font_cache[clean] = f
    end
    return _font_cache[clean]
end

function Font.setPixelSizes(fobj, size)
    _font_sizes[fobj] = size or 20
end

function Font.print(fobj, x, y, text, col)
    if not fobj then return end
    love.graphics.setFont(fobj)
    if col then love.graphics.setColor(col) else love.graphics.setColor(1,1,1,1) end
    love.graphics.print(tostring(text), x, y)
end

function Font.getTextWidth(fobj, text)
    if not fobj then return 0 end
    return fobj:getWidth(tostring(text))
end

-- ── Image wrapper ───────────────────────────────────────────
-- LPP returns image objects; LÖVE returns Drawable userdata.
-- We wrap in a table so callers get the same API.
local ImageWrapper = {}
ImageWrapper.__index = ImageWrapper

function ImageWrapper:getWidth()  return self._w end
function ImageWrapper:getHeight() return self._h end

local _img_cache = {}

-- ── Graphics ────────────────────────────────────────────────
Graphics = {}

function Graphics.loadImage(path)
    local clean = path:gsub("app0:/", ""):gsub("ux0:data/", "")
    if _img_cache[clean] then return _img_cache[clean] end
    local ok, img = pcall(love.graphics.newImage, clean)
    if not ok then
        print("[engine] loadImage failed: " .. clean)
        return nil
    end
    local w = img:getWidth()
    local h = img:getHeight()
    local wrapper = setmetatable({ _data=img, _w=w, _h=h }, ImageWrapper)
    _img_cache[clean] = wrapper
    return wrapper
end

function Graphics.getImageWidth(img)
    if img and img._w then return img._w end
    return 0
end

function Graphics.getImageHeight(img)
    if img and img._h then return img._h end
    return 0
end

function Graphics.initBlend()
    -- In LÖVE blending is always on; nothing to do.
end

function Graphics.termBlend()
    -- Nothing to do.
end

function Graphics.drawImage(x, y, img)
    if not img or not img._data then return end
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img._data, x, y)
end

function Graphics.drawPartialImage(x, y, img, sx, sy, sw, sh)
    if not img or not img._data then return end
    love.graphics.setColor(1, 1, 1, 1)
    local quad = love.graphics.newQuad(sx, sy, sw, sh, img._w, img._h)
    love.graphics.draw(img._data, quad, x, y)
end

-- drawImageExtended(cx, cy, img, sx, sy, sw, sh, angle_deg, sx_scale, sy_scale, col)
-- LPP passes the *centre* of the image as (cx, cy) and angle in degrees.
function Graphics.drawImageExtended(cx, cy, img, sx, sy, sw, sh, angle_deg, xscale, yscale, col)
    if not img or not img._data then return end
    if col then love.graphics.setColor(col) else love.graphics.setColor(1,1,1,1) end
    local rad = (angle_deg or 0) * math.pi / 180
    local quad = love.graphics.newQuad(sx, sy, sw, sh, img._w, img._h)
    -- LÖVE draw(img, quad, x, y, r, sx, sy, ox, oy)
    -- ox/oy are the origin offsets; we want to rotate around the sprite centre.
    love.graphics.draw(img._data, quad, cx, cy, rad, xscale or 1, yscale or 1,
                       sw * 0.5, sh * 0.5)
end

function Graphics.fillRect(x1, x2, y1, y2, col)
    -- LPP: fillRect(x1, x2, y1, y2, color)  ← note x1/x2 then y1/y2
    if col then love.graphics.setColor(col) else love.graphics.setColor(0,0,0,1) end
    love.graphics.rectangle("fill", x1, y1, x2 - x1, y2 - y1)
end

-- ── Screen ──────────────────────────────────────────────────
Screen = {}
function Screen.clear(col)
    if col then
        love.graphics.setBackgroundColor(col)
    end
    love.graphics.clear()
end

function Screen.flip()
    -- This is the coroutine yield point – one frame passes each time.
    coroutine.yield()
end

function Screen.waitVblankStart()
    coroutine.yield()
end

-- ── Sound / Audio ────────────────────────────────────────────
local _sound_sources = {}   -- path → love.Source

Sound = {}
function Sound.init() end  -- no-op in LÖVE

function Sound.open(path)
    local clean = path:gsub("app0:/", ""):gsub("ux0:data/", "")
    if _sound_sources[clean] then return _sound_sources[clean] end
    -- Heuristic: music files get stream type; everything else static
    local stype = (clean:find("music") or clean:find("bgm")) and "stream" or "static"
    local ok, src = pcall(love.audio.newSource, clean, stype)
    if ok then
        _sound_sources[clean] = src
        return src
    end
    print("[engine] Sound.open failed: " .. clean)
    return nil
end

function Sound.play(src, loop)
    if not src then return end
    src:setLooping(loop == true)
    if src:isPlaying() then src:stop() end
    src:play()
end

function Sound.stop(src)
    if src then src:stop() end
end

function Sound.close(src)
    if src then src:stop() end
    -- LÖVE GCs the source when no references remain.
end

function Sound.setVolume(src, lpp_vol)
    -- LPP volume range: 0-32767
    if src then src:setVolume((lpp_vol or 32767) / 32767) end
end

function Sound.getVolume(src)
    if src then return math.floor(src:getVolume() * 32767) end
    return 0
end

-- ── Controls ────────────────────────────────────────────────
Controls = {}

-- These functions are called by the generated lib/controls.lua
-- which stores a bitmask. We fake a bitmask with a table keyed by
-- button-string. controls_update() swaps _pressed → _old.
local _pad_cur_bits = {}
local _pad_old_bits = {}

-- LPP API used in generated code:
function Controls.read()
    -- Return a *snapshot table* (not a real bitmask).
    -- We copy _held so lib/controls.lua can compare old vs cur.
    local snap = {}
    for k, v in pairs(_held) do snap[k] = v end
    return snap
end

function Controls.check(pad_snap, btn)
    -- btn is e.g. SCE_CTRL_CROSS = "cross"
    if type(pad_snap) == "table" then
        return pad_snap[btn] == true
    end
    return false
end

-- ── System ──────────────────────────────────────────────────
System = {}
function System.setCpuSpeed(mhz) end  -- no-op

-- ── RayCast3D stub ──────────────────────────────────────────
-- Provides a flat-floor renderer so 3D scenes don't crash.
local _rc = {
    px=480, py=272, angle=0,
    map=nil, map_w=16, map_h=16, tile_size=64, wall_height=1.0,
    fov=60, wall_col={0.5,0.5,0.5,1}, ceil_col={0.4,0.6,1,1}, floor_col={0.3,0.3,0.3,1},
    shading=true,
}

RayCast3D = {}
function RayCast3D.setResolution(w,h) end
function RayCast3D.setViewsize(fov) _rc.fov = fov end
function RayCast3D.loadMap(cells, w, h, tile_size, wall_height)
    _rc.map=cells; _rc.map_w=w; _rc.map_h=h
    _rc.tile_size=tile_size; _rc.wall_height=wall_height
end
function RayCast3D.setWallColor(col)  _rc.wall_col  = col end
function RayCast3D.useShading(b)      _rc.shading   = b   end
function RayCast3D.setAccuracy(n)     end
function RayCast3D.spawnPlayer(x,y,a) _rc.px=x; _rc.py=y; _rc.angle=a end

function RayCast3D.movePlayer(dir, spd)
    local rad = _rc.angle * math.pi / 180
    if dir == FORWARD then
        _rc.px = _rc.px + math.cos(rad) * spd
        _rc.py = _rc.py + math.sin(rad) * spd
    elseif dir == BACK then
        _rc.px = _rc.px - math.cos(rad) * spd
        _rc.py = _rc.py - math.sin(rad) * spd
    end
end

function RayCast3D.rotateCamera(dir, deg)
    if dir == LEFT_DIR  then _rc.angle = _rc.angle - deg end
    if dir == RIGHT_DIR then _rc.angle = _rc.angle + deg end
end

function RayCast3D.renderScene(ox, oy)
    -- Minimal wireframe so the scene is at least visible.
    love.graphics.setColor(_rc.ceil_col  or {0.4,0.6,1,1})
    love.graphics.rectangle("fill", ox, oy, 960, 272)
    love.graphics.setColor(_rc.floor_col or {0.3,0.3,0.3,1})
    love.graphics.rectangle("fill", ox, oy+272, 960, 272)
    -- Simple column raycaster (DDA) – good enough for testing.
    if not _rc.map then return end
    local num_rays = 120
    local half_fov = math.rad(_rc.fov / 2)
    for col = 0, num_rays - 1 do
        local ray_ang = _rc.angle * math.pi/180 - half_fov + (col / num_rays) * math.rad(_rc.fov)
        local dx, dy  = math.cos(ray_ang), math.sin(ray_ang)
        local dist    = 0.5
        local hit     = false
        for _step = 1, 200 do
            dist  = dist + 1
            local wx = math.floor((_rc.px + dx * dist) / _rc.tile_size)
            local wy = math.floor((_rc.py + dy * dist) / _rc.tile_size)
            if wx < 0 or wy < 0 or wx >= _rc.map_w or wy >= _rc.map_h then break end
            local cell = _rc.map[wy * _rc.map_w + wx + 1]
            if cell and cell ~= 0 then hit = true; break end
        end
        if hit then
            local corrected = dist * math.cos(ray_ang - _rc.angle * math.pi/180)
            local wall_h    = math.min(544, (544 * _rc.tile_size * _rc.wall_height) / corrected)
            local shade     = _rc.shading and math.max(0.2, 1 - dist/400) or 1
            local wc        = _rc.wall_col or {0.5,0.5,0.5,1}
            love.graphics.setColor(wc[1]*shade, wc[2]*shade, wc[3]*shade, 1)
            local col_w   = 960 / num_rays
            local screen_x = ox + col * col_w
            local top_y    = oy + 272 - wall_h * 0.5
            love.graphics.rectangle("fill", screen_x, top_y, col_w + 1, wall_h)
        end
    end
end

-- ── os.exit override ────────────────────────────────────────
local _orig_exit = os.exit
function os.exit(code)
    love.event.quit(code or 0)
end

-- ── LÖVE callbacks ──────────────────────────────────────────
local _game_co = nil

function love.load()
    love.window.setTitle("Vita Adventure Creator – Windows Preview")
    -- Build the default font fallback
    _default_font = love.graphics.newFont(20)
    if main_game_loop then
        _game_co = coroutine.create(main_game_loop)
    else
        print("[engine] WARNING: main_game_loop not defined – check index.lua")
    end
end

function love.keypressed(k, scancode, isrepeat)
    local btn = _key_map[k]
    if btn then
        _pressed[btn] = true
        _held[btn]    = true
    end
end

function love.keyreleased(k)
    local btn = _key_map[k]
    if btn then
        _held[btn]    = false
        _released[btn] = true
    end
end

function love.update(dt)
    -- Nothing; coroutine is driven from love.draw so draw order matches LPP.
end

function love.draw()
    if _game_co and coroutine.status(_game_co) ~= "dead" then
        local ok, err = coroutine.resume(_game_co)
        if not ok then
            love.graphics.setColor(1, 0, 0, 1)
            love.graphics.print("Game error:\n" .. tostring(err), 20, 20)
        end
    end
    -- Clear single-frame input flags after the frame ran.
    _pressed  = {}
    _released = {}
end
"""


# ─────────────────────────────────────────────────────────────────────────────
#  PATH FIXUP
#  Rewrites every LPP-specific asset path prefix to bare relative paths
#  that LÖVE can load from the .love archive root.
# ─────────────────────────────────────────────────────────────────────────────
_PATH_REPLACEMENTS = [
    ("app0:/assets/",      "assets/"),
    ("app0:/scenes/",      "scenes/"),
    ("app0:/lib/",         "lib/"),
    ("app0:/files/",       "files/"),
    ("app0:/",             ""),
    ("ux0:data/",          ""),
    ("sa0:data/font/pvf/", ""),
]

def _fix_paths(lua_source: str) -> str:
    for old, new in _PATH_REPLACEMENTS:
        lua_source = lua_source.replace(old, new)
    return lua_source


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def export_windows_game(project, parent_window):
    """Export the project as a fused Windows .exe (love.exe + .love archive)."""

    if not LOVE_RUNTIME_DIR.exists():
        QMessageBox.critical(
            parent_window, "Missing LÖVE Runtime",
            "The 'love_runtime' folder was not found.\n\n"
            "Download LÖVE 11 for Windows (64-bit .zip), extract it, "
            "and rename the folder to 'love_runtime' next to this script."
        )
        return

    export_folder = QFileDialog.getExistingDirectory(parent_window, "Select Export Folder")
    if not export_folder:
        return

    export_root = Path(export_folder) / project.title
    build_dir   = export_root / "build"
    love_file   = export_root / f"{project.title}.love"
    final_exe   = export_root / f"{project.title}.exe"

    try:
        # ── 0. Clean slate ───────────────────────────────────────────────────
        if export_root.exists():
            shutil.rmtree(export_root)
        build_dir.mkdir(parents=True)

        # ── 1. Generate all Lua files via the LPP exporter ───────────────────
        #       This gives us the exact same logic that ships to the Vita.
        lua_files: dict[str, str] = export_lpp(project)

        # ── 2. Write engine shim ─────────────────────────────────────────────
        (build_dir / "engine.lua").write_text(LOVE_ENGINE_SHIM, encoding="utf-8")

        # ── 3. Write every generated Lua file (with path fixup) ──────────────
        for rel_path, source in lua_files.items():
            dest = build_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_fix_paths(source), encoding="utf-8")

        # ── 4. Patch index.lua ───────────────────────────────────────────────
        #
        #  Three things need fixing in the generated index.lua:
        #
        #  a) require('lib/tween') etc. — LÖVE require() uses dot-separated
        #     module paths, NOT slash-separated. Convert slashes to dots and
        #     drop the leading 'lib/' so the Lua package path resolves correctly
        #     (we set package.path in main.lua to include all needed dirs).
        #
        #  b) dofile('scenes/scene_NNN.lua') — plain dofile() uses the OS
        #     filesystem and cannot see inside a .love archive.  Replace with
        #     the LÖVE-safe idiom:
        #         assert(love.filesystem.load('scenes/scene_NNN.lua'))()
        #
        #  c) Wrap the "while running do … os.exit()" block in
        #     main_game_loop() so love.draw() can drive it as a coroutine.
        #
        index_path = build_dir / "index.lua"
        index_src  = index_path.read_text(encoding="utf-8")

        # (a) Fix require paths: require('lib/X') → require('lib.X')
        #     LÖVE sets up package.path to include the .love root, so
        #     'lib.X' resolves to 'lib/X.lua' automatically.
        import re
        index_src = re.sub(
            r"require\(['\"]lib/([^'\"]+)['\"]\)",
            lambda m: f"require('lib.{m.group(1)}')",
            index_src
        )

        # (b) Fix scene dofile calls → love.filesystem.load
        index_src = re.sub(
            r"dofile\(['\"]scenes/([^'\"]+)['\"]\)",
            lambda m: f"assert(love.filesystem.load('scenes/{m.group(1)}'))()",
            index_src
        )

        # (c) Wrap the main loop in a function for coroutine use
        if "while running do" in index_src:
            index_src = index_src.replace(
                "while running do",
                "function main_game_loop()\nwhile running do",
                1
            )
            index_src = index_src.rstrip() + "\nend -- main_game_loop\n"

        index_path.write_text(index_src, encoding="utf-8")

        # ── 5. Write LÖVE conf + main entry point ────────────────────────────
        #
        #  main.lua must use love.filesystem.load() to pull in index.lua —
        #  plain dofile() or require() cannot reach files inside a .love archive.
        #  We also extend package.path so that require('lib.X') works.
        #
        (build_dir / "conf.lua").write_text(
            f'function love.conf(t)\n'
            f'    t.window.title  = {repr(project.title)}\n'
            f'    t.window.width  = 960\n'
            f'    t.window.height = 544\n'
            f'    t.console       = true\n'
            f'end\n',
            encoding="utf-8"
        )

        (build_dir / "main.lua").write_text(
            '-- Auto-generated by Vita Adventure Creator (Windows Export)\n'
            '\n'
            '-- Make love.filesystem.load work for require() calls inside\n'
            '-- the .love archive by injecting a custom loader.\n'
            'table.insert(package.loaders or package.searchers, 1, function(name)\n'
            '    local path = name:gsub("%.", "/") .. ".lua"\n'
            '    if love.filesystem.getInfo(path) then\n'
            '        return function(...)\n'
            '            return assert(love.filesystem.load(path))(...)\n'
            '        end\n'
            '    end\n'
            'end)\n'
            '\n'
            '-- Load engine shim first so all LPP globals are defined\n'
            'assert(love.filesystem.load("engine.lua"))()\n'
            '\n'
            '-- Load generated game code\n'
            'assert(love.filesystem.load("index.lua"))()\n',
            encoding="utf-8"
        )

        # ── 6. Copy assets using the same mapping the LPP exporter uses ──────
        asset_map = get_asset_mapping(project)
        for src_path, rel_dest in asset_map.items():
            if os.path.exists(src_path):
                dest_file = build_dir / rel_dest
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_path, dest_file)

        # Bundled default font (font.ttf) – copy if present next to the script
        default_font_src = Path("assets/fonts/font.ttf")
        default_font_dst = build_dir / "assets" / "fonts" / "font.ttf"
        if default_font_src.exists():
            default_font_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(default_font_src, default_font_dst)

        # ── 7. Bake tile chunks (PIL) ─────────────────────────────────────────
        try:
            bake_tile_chunks(project, build_dir)
        except ImportError:
            print("[windows_exporter] Pillow not installed – tile chunks skipped.")
        except Exception as e:
            print(f"[windows_exporter] Tile chunk bake error: {e}")

        # ── 8. Copy animation spritesheets ───────────────────────────────────
        if project.project_folder:
            ani_src_dir = Path(project.project_folder) / "animations"
            ani_dst_dir = build_dir / "assets" / "animations"
            if ani_src_dir.exists():
                ani_dst_dir.mkdir(parents=True, exist_ok=True)
                for f in ani_src_dir.iterdir():
                    if f.is_file():
                        shutil.copy(f, ani_dst_dir / f.name)

        # ── 9. Pack .love archive ─────────────────────────────────────────────
        with zipfile.ZipFile(love_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in build_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(build_dir))

        # ── 10. Fuse love.exe + .love → final .exe ────────────────────────────
        love_exe = LOVE_RUNTIME_DIR / "love.exe"
        if not love_exe.exists():
            raise FileNotFoundError("love.exe not found in love_runtime/")

        with open(final_exe, "wb") as out_f:
            out_f.write(love_exe.read_bytes())
            out_f.write(love_file.read_bytes())

        # ── 11. Copy required DLLs next to the .exe ───────────────────────────
        for f in LOVE_RUNTIME_DIR.iterdir():
            if f.suffix.lower() == ".dll" or f.name.lower() in ("license.txt", "readme.txt"):
                shutil.copy(f, export_root / f.name)

        # ── 12. Cleanup intermediates ─────────────────────────────────────────
        shutil.rmtree(build_dir)
        love_file.unlink()

        QMessageBox.information(
            parent_window, "Export Complete",
            f"Windows build created at:\n{export_root}"
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.critical(parent_window, "Export Failed", str(e))
        # Leave build_dir intact on failure so the developer can inspect it.
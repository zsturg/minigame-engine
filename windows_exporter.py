# ===== FILE: windows_exporter.py =====
import os
import shutil
import zipfile
from pathlib import Path
from PyQt6.QtWidgets import QMessageBox, QFileDialog
from lua_exporter import export_main_lua

LOVE_RUNTIME_DIR = Path("love_runtime")

# -----------------------------------------------------------------------------
# ENGINE SHIM (The "Emulator" for Windows)
# -----------------------------------------------------------------------------
# 1. Wraps Images in tables to allow :display() methods.
# 2. Uses Coroutines to handle the Vita 'while' loop inside LÖVE's callback system.
# -----------------------------------------------------------------------------
LOVE_ENGINE_SHIM = r"""
local engine = {}

-- GLOBAL CONSTANTS FOR VITA CONTROLS
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

-- Key mappings (Keyboard -> Vita)
local key_map = {
    z = "cross", space = "cross",
    x = "circle",
    a = "square",
    s = "triangle",
    up = "up",
    down = "down",
    left = "left",
    right = "right",
    ["return"] = "start",
    escape = "select"
}

-- Input state
local input_pressed = {}
local input_held = {}

engine.assets = { images = {}, audio = {} }

-- --------------------------------------------------
-- FONT
-- --------------------------------------------------
font = {}
function font.load(path)
    -- Return a dummy font object or real love font
    return love.graphics.newFont(20)
end

-- --------------------------------------------------
-- COLOR
-- --------------------------------------------------
color = {}
function color.new(r,g,b,a)
    return { (r or 255)/255, (g or 255)/255, (b or 255)/255, (a or 255)/255 }
end

-- --------------------------------------------------
-- IMAGE WRAPPER
-- --------------------------------------------------
-- We cannot setmetatable on love userdata directly in LuaJIT/5.1 in this context easily.
-- We wrap the love image in a table.
local ImageWrapper = {}
ImageWrapper.__index = ImageWrapper

function ImageWrapper:display(x, y)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(self._data, x, y)
end

function ImageWrapper:blit(x, y, sx, sy, w, h)
    -- Simple blit implementation using quads could go here
    -- For now, just draw the whole thing to prevent crashes
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(self._data, x, y)
end

image = {}
function image.load(path)
    if not engine.assets.images[path] then
        local success, img = pcall(love.graphics.newImage, path)
        if success then
            local wrapper = { _data = img }
            setmetatable(wrapper, ImageWrapper)
            engine.assets.images[path] = wrapper
        else
            print("Failed to load image: " .. path)
            return nil
        end
    end
    return engine.assets.images[path]
end

-- --------------------------------------------------
-- AUDIO
-- --------------------------------------------------
audio = {}
function audio.load(path)
    if not engine.assets.audio[path] then
        local type = "static" -- sfx
        -- heuristic for music
        if path:find("music") or path:find("bgm") then type = "stream" end
        local success, src = pcall(love.audio.newSource, path, type)
        if success then
            engine.assets.audio[path] = src
        end
    end
    return engine.assets.audio[path]
end

function audio.play(src, loop)
    if src then
        src:setLooping(loop or false)
        src:play()
    end
end

function audio.stop(src)
    if src then src:stop() end
end

-- --------------------------------------------------
-- DRAWING
-- --------------------------------------------------
draw = {}
function draw.gradientrect(x,y,w,h,c1,c2,c3,c4)
    love.graphics.setColor(c1)
    love.graphics.rectangle("fill", x, y, w, h)
end

function draw.rect(x,y,w,h,col)
    love.graphics.setColor(col)
    love.graphics.rectangle("fill", x, y, w, h)
end

function draw.text(x,y,text,col,fontobj)
    love.graphics.setColor(col)
    love.graphics.print(text, x, y)
end

function draw.swapbuffers()
    -- This is the magic. In Vita, this swaps buffers.
    -- In LÖVE, we yield the coroutine to let LÖVE finish the frame.
    coroutine.yield()
end

-- --------------------------------------------------
-- CONTROLS
-- --------------------------------------------------
controls = {}

function controls.update()
    -- LÖVE handles input polling automatically
end

function controls.pressed(btn)
    return input_pressed[btn] == true
end

function controls.released(btn)
    -- For simplicity in this shim, we treat love.keyreleased as 'released'
    return input_pressed[btn] == true -- Mapping simplified for adventure games
end

function controls.held(btn)
    return input_held[btn] == true
end

-- LÖVE Callbacks to feed the input system
function love.keypressed(k)
    local btn = key_map[k]
    if btn then
        input_pressed[btn] = true
        input_held[btn] = true
    end
end

function love.keyreleased(k)
    local btn = key_map[k]
    if btn then
        input_held[btn] = false
    end
end

-- --------------------------------------------------
-- OS
-- --------------------------------------------------
function os.exit()
    love.event.quit()
end

-- --------------------------------------------------
-- GAME LOOP COROUTINE
-- --------------------------------------------------
local game_co = nil

function love.load()
    -- Initialize the game logic in a coroutine
    -- 'main_game_loop' is defined in the generated game_script.lua
    if main_game_loop then
        game_co = coroutine.create(main_game_loop)
    end
end

function love.update(dt)
    -- We don't advance the coroutine here, we do it in draw 
    -- to match the immediate mode 'draw, then swap' flow.
end

function love.draw()
    -- Reset one-frame inputs
    -- (In a real engine this is more complex, but works for simple VNs)
    
    if game_co and coroutine.status(game_co) ~= "dead" then
        local ok, err = coroutine.resume(game_co)
        if not ok then
            print("Game Error: " .. tostring(err))
        end
    end
    
    -- Clear "pressed" flags after the frame logic ran
    for k,v in pairs(input_pressed) do
        input_pressed[k] = false
    end
end

return engine
"""

def export_windows_game(project, parent_window):

    if not LOVE_RUNTIME_DIR.exists():
        QMessageBox.critical(
            parent_window,
            "Error",
            "love_runtime folder not found.\n\nPlease download LÖVE for Windows (64-bit zip), extract it, and rename the folder to 'love_runtime' next to this python script."
        )
        return

    export_folder = QFileDialog.getExistingDirectory(parent_window, "Select Export Folder")
    if not export_folder:
        return

    export_root = Path(export_folder) / project.title
    build_dir = export_root / "build"
    love_file = export_root / f"{project.title}.love"
    final_exe = export_root / f"{project.title}.exe"

    try:
        # Cleanup previous export
        if export_root.exists():
            shutil.rmtree(export_root)
        build_dir.mkdir(parents=True)

        # 1. Copy Assets
        for img in project.images:
            if img.path and os.path.exists(img.path):
                shutil.copy(img.path, build_dir / Path(img.path).name)

        for aud in getattr(project, "audio", []):
            if aud.path and os.path.exists(aud.path):
                shutil.copy(aud.path, build_dir / Path(aud.path).name)
        
        # Copy font if exists, else skip
        for font in project.fonts:
             if font.path and os.path.exists(font.path):
                shutil.copy(font.path, build_dir / Path(font.path).name)

        # 2. Generate Lua Code
        raw_lua = export_main_lua(project)

        cleaned = []
        # Fix file paths (remove Vita specific prefixes)
        for line in raw_lua.split("\n"):
            if '"' in line:
                # Basic string replacement for asset paths
                line = line.replace("app0:", "")
                line = line.replace("sa0:data/font/pvf/", "")
                line = line.replace("ux0:data/", "") 
            cleaned.append(line)
        
        full_script = "\n".join(cleaned)

        # 3. Inject Coroutine Loop
        # We need to wrap the infinite "while running do" loop in a function
        # so LÖVE can call it as a coroutine.
        if "while running do" in full_script:
            full_script = full_script.replace(
                "while running do", 
                "function main_game_loop()\nwhile running do"
            )
            # Find the last "os.exit()" or end of file to close the function
            # Simplest way: append 'end' at the very end of the file logic block
            full_script += "\nend"
        
        # Write the scripts
        (build_dir / "game_script.lua").write_text(full_script, encoding="utf-8")
        (build_dir / "engine.lua").write_text(LOVE_ENGINE_SHIM, encoding="utf-8")
        
        # Main entry point for LÖVE
        (build_dir / "main.lua").write_text(r"""
require("engine")
require("game_script")
""", encoding="utf-8")

        # Config file
        (build_dir / "conf.lua").write_text(f"""
function love.conf(t)
    t.window.title = "{project.title}"
    t.window.width = 960
    t.window.height = 544
    t.console = true -- Enable console for debug prints
end
""", encoding="utf-8")

        # 4. Create .love archive
        with zipfile.ZipFile(love_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            for f in build_dir.iterdir():
                zipf.write(f, f.name)

        # 5. Fuse with love.exe
        love_exe = LOVE_RUNTIME_DIR / "love.exe"
        if not love_exe.exists():
             raise Exception("love.exe not found in love_runtime folder.")

        with open(final_exe, "wb") as out:
            # Write love.exe
            with open(love_exe, "rb") as f: 
                out.write(f.read())
            # Append .love content
            with open(love_file, "rb") as f: 
                out.write(f.read())

        # 6. Copy DLLs
        for file in LOVE_RUNTIME_DIR.iterdir():
            if file.suffix.lower() == ".dll" or file.name.lower() in ["license.txt"]:
                shutil.copy(file, export_root / file.name)

        # Cleanup
        shutil.rmtree(build_dir)
        love_file.unlink()

        QMessageBox.information(parent_window, "Export Complete", f"Windows Game created at:\n{export_root}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.critical(parent_window, "Export Failed", str(e))
        # Don't delete export root on error so user can debug if needed
-- lib/controls.lua
local _pad_old = 0
local _pad_cur = 0

function controls_update()
    _pad_old = _pad_cur
    _pad_cur = Controls.read()
end

function controls_held(btn)
    return Controls.check(_pad_cur, btn)
end

function controls_pressed(btn)
    return Controls.check(_pad_cur, btn) and not Controls.check(_pad_old, btn)
end

function controls_released(btn)
    return not Controls.check(_pad_cur, btn) and Controls.check(_pad_old, btn)
end
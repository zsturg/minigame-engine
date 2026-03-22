--[[
 This file is part of:
   ______            _____           _   ___________ 
   | ___ \          /  __ \         | | |____ |  _  \
   | |_/ /__ _ _   _| /  \/ __ _ ___| |_    / / | | |
   |    // _` | | | | |    / _` / __| __|   \ \ | | |
   | |\ \ (_| | |_| | \__/\ (_| \__ \ |_.___/ / |/ / 
   \_| \_\__,_|\__, |\____/\__,_|___/\__\____/|___/  
               __/ |                                
              |___/            by Rinnegatamante

 Lua Game Engine made to create 3D games using Ray-Casting
 algorithm.
]]--

-- Movements globals
LEFT = 0
RIGHT = 1
FORWARD = 2
BACK = 3

-- Screen Globals
local vwidth = 960 -- Pixels
local vheight = 544 -- Pixels
local viewsize = 60 -- Degrees

-- Map Globals
local wall_height = 64
local tile_size = 64
local tile_shift = 6
local map_width = 1
local map_height = 1
local map = { 
	0 
}

-- Player Globals
local pl_x = 0
local pl_y = 0
local pl_angle = 0
 
-- Local used variables (Slight speedup)
local tmp
local scale_y
local scale_x

-- bit32 polyfill for Lua 5.1 (LPP-Vita)
if not bit32 then
	bit32 = {}
	function bit32.rshift(x, n)
		return math.floor(x / (2 ^ n))
	end
	function bit32.lshift(x, n)
		return math.floor(x * (2 ^ n))
	end
	function bit32.band(a, b)
		local result, bit = 0, 1
		for i = 0, 31 do
			if a % 2 == 1 and b % 2 == 1 then
				result = result + bit
			end
			a = math.floor(a / 2)
			b = math.floor(b / 2)
			bit = bit * 2
		end
		return result
	end
	function bit32.bxor(a, b)
		local result, bit = 0, 1
		for i = 0, 31 do
			local ab, bb = a % 2, b % 2
			if ab ~= bb then
				result = result + bit
			end
			a = math.floor(a / 2)
			b = math.floor(b / 2)
			bit = bit * 2
		end
		return result
	end
end

-- Local funcs definitions (Slight speedup)
local floor_num = math.floor
local ceil_num = math.ceil
local drawImage = Graphics.drawImageExtended
local drawRect = Graphics.fillRect
local getHeight = Graphics.getImageHeight
local getWidth = Graphics.getImageWidth
local rad2deg = math.deg
local deg2rad = math.rad
local genColor = Color.new
local doTan = math.tan
local doSin = math.sin
local doCos = math.cos
local doMin = math.min
local PI = math.pi
local shift_r = bit32.rshift
local shift_l = bit32.lshift

 -- Colors Globals
local floor_c = genColor(255, 255, 255, 255)
local sky_c = genColor(0, 0, 0, 255)
local wall_c = genColor(0, 0, 255, 255)
local player_c = genColor(255, 255, 0, 255)
local shad_r = 0
local shad_g = 0
local shad_b = 0

-- Angles Globals (DON'T EDIT)
local ANGLE60 = vwidth
local ANGLE30 = shift_r(ANGLE60,1)
local ANGLE15 = shift_r(ANGLE30,1)
local ANGLE5 = ANGLE15 / 3
local ANGLE10 = shift_l(ANGLE5,1)
local ANGLE0 = 0
local ANGLE90 = ANGLE30 * 3
local ANGLE180 = shift_l(ANGLE90,1)
local ANGLE270 = ANGLE90 * 3
local ANGLE360 = shift_l(ANGLE180,1)

-- PreCalculated Trigonometric Tables (DON'T EDIT)
local sintable = {}
local sintable2 = {}
local costable = {}
local costable2 = {}
local tantable = {}
local tantable2 = {}
local fishtable = {} -- Anti-fishbowl effect values
local xsteptable = {}
local ysteptable = {}

-- Internal Globals (DON'T EDIT)
local ycenter = shift_r(vheight,1)
local dist_proj =  (shift_r(vwidth,1)) / doTan(deg2rad(shift_r(viewsize,1)))
local accuracy = 2
local shad_val = 500
local floors = false
local sky = false
local noclip = false
local shading = false
RayCast3D = {}

-- Sprite / Billboard Globals
local zbuffer = {}       -- per-column wall distance, populated by renderScene
local sprites = {}       -- array of sprite entries
local sprite_count = 0   -- number of active sprites
local sprite_order = {}  -- reusable sort buffer

-- Internal Functions (DON'T EDIT)
local function arc2rad(val)
	return (val*PI)/ANGLE180
end
local function rad2arc(val)
	return (val*ANGLE180)/PI
end

local function WallRender(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
end
local function WallRenderShad(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy+1, getHeight(tmp), 0, 1.0, scale_y)
	end
	scale_y = wh / tile_size
	drawRect(x+stride-2,x+stride+accuracy+2,y+top_wall,y+top_wall+wh,genColor(shad_r,shad_g,shad_b,doMin(255,floor_num(shad_val / scale_y))))
end
local function WallFloorRender(x,y,stride,top_wall,wh,cell_idx,offs)
	drawRect(x+stride,x+stride+accuracy,y+top_wall+wh,vheight,floor_c)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
end
local function WallFloorRenderShad(x,y,stride,top_wall,wh,cell_idx,offs)
	drawRect(x+stride,x+stride+accuracy,y+top_wall+wh,vheight,floor_c)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
	scale_y = wh / tile_size
	drawRect(x+stride-2,x+stride+accuracy+2,y+top_wall,y+top_wall+wh,genColor(shad_r,shad_g,shad_b,doMin(255,floor_num(shad_val / scale_y))))
end
local function WallSkyRender(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
	scale_y = wh / tile_size
	drawRect(x+stride,x+stride+accuracy,y+top_wall,y,floor_c)
end
local function WallSkyRenderShad(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	drawRect(x+stride,x+stride+accuracy,y+top_wall,y,floor_c)
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
	scale_y = wh / tile_size
	drawRect(x+stride-2,x+stride+accuracy+2,y+top_wall,y+top_wall+wh,genColor(shad_r,shad_g,shad_b,doMin(255,floor_num(shad_val / scale_y))))
end
local function WallFloorSkyRender(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
	drawRect(x+stride,x+stride+accuracy,y+top_wall+wh,vheight,floor_c)
	drawRect(x+stride,x+stride+accuracy,y+top_wall,y,sky_c)
end
local function WallFloorSkyRenderShad(x,y,stride,top_wall,wh,cell_idx,offs)
	tmp = map[cell_idx]
	drawRect(x+stride,x+stride+accuracy,y+top_wall+wh,vheight,floor_c)
	drawRect(x+stride,x+stride+accuracy,y+top_wall,y,sky_c)
	if tmp == nil then
		return
	end
	if tmp == 1 or tmp == 0 then
		drawRect(x+stride,x+stride+accuracy,y+top_wall,y+top_wall+wh,wall_c)
	else
		scale_y = wh / getHeight(tmp)
		scale_x = getWidth(tmp) / tile_size
		drawImage(x+stride,y+top_wall+wh/2, tmp, offs * scale_x, 0, accuracy, getHeight(tmp), 0, 1.0, scale_y)
	end
	scale_y = wh / tile_size
	drawRect(x+stride-2,x+stride+accuracy+2,y+top_wall,y+top_wall+wh,genColor(shad_r,shad_g,shad_b,doMin(255,floor_num(shad_val / scale_y))))
end
local RenderRay = WallRender
local function ResetAngles()
	ANGLE60 = vwidth
	ANGLE30 = shift_r(ANGLE60,1)
	ANGLE15 = shift_r(ANGLE30,1)
	ANGLE5 = floor_num(ANGLE30 / 6)
	ANGLE10 = shift_l(ANGLE5,1)
	ANGLE0 = 0
	ANGLE90 = ANGLE30 * 3
	ANGLE180 = shift_l(ANGLE90,1)
	ANGLE270 = ANGLE90 * 3
	ANGLE360 = shift_l(ANGLE180,1)
	local i = 0
	local v
	sintable = {}
	sintable2 = {}
	costable = {}
	costable2 = {}
	tantable = {}
	tantable2 = {}
	fishtable = {}
	xsteptable = {}
	ysteptable = {}
	while i <= ANGLE360 do
		v = arc2rad(i) + 0.0001 -- avoid asymptotics values
		sintable[i] = doSin(v)
		sintable2[i] = (1.0/(sintable[i]))
		costable[i] = doCos(v)
		costable2[i] = (1.0/(costable[i]))
		tantable[i] = sintable[i] / costable[i]
		tantable2[i] = (1.0/(tantable[i]))
		if (i >= ANGLE90 and i < ANGLE270) then
			xsteptable[i] = -math.abs(tile_size / tantable[i])
		else
			xsteptable[i] = math.abs(tile_size / tantable[i])
		end
		if (i >= ANGLE0 and i < ANGLE180) then
			ysteptable[i] = math.abs(tile_size * tantable[i])
		else
			ysteptable[i] = -math.abs(tile_size * tantable[i])
		end
		i = i + 1
	end
	i = -ANGLE30
	while i <= ANGLE30 do
		v = arc2rad(i)
		fishtable[i+ANGLE30] =  1.0 / doCos(v)
		i = i + 1
	end
end
local function ResetProjections()
	dist_proj =  (shift_r(vwidth,1)) / doTan(deg2rad(shift_r(viewsize,1)))
end
local function ResetRenderer()
	if floors then
		if sky then
			if shading then
				RenderRay = WallFloorSkyRenderShad
			else
				RenderRay = WallFloorSkyRender
			end
		else
			if shading then
				RenderRay = WallFloorRenderShad
			else
				RenderRay = WallFloorRender
			end
		end
	else
		if sky then
			if shading then
				RenderRay = WallSkyRenderShad
			else
				RenderRay = WallSkyRender
			end
		else
			if shading then
				RenderRay = WallRenderShad
			else
				RenderRay = WallRender
			end
		end
	end
end
local function ResetEngine()
	ResetAngles()
	ResetProjections()
	ycenter = shift_r(vheight,1)
end

--[[setResolution: Sets renderer resolution]]--
function RayCast3D.setResolution(w, h)

	-- Change screen resolution
	vwidth = w
	vheight = h
	
	-- Reset engine with new values
	ResetEngine()
	
end

--[[setViewsize: Sets FOV]]--
function RayCast3D.setViewsize(angle)
	viewsize = angle
	ResetProjections()
end

--[[renderScene: Render viewport scene using GPU]]--
function RayCast3D.renderScene(x, y)
	local castArc = pl_angle - ANGLE30
	if castArc < 0 then
		castArc = ANGLE360 + castArc
	end
	local stride = 0
	local hgrid
	local vgrid
	local xtmp
	local xinter
	local yinter
	local ytmp
	local dist_next_hgrid
	local dist_next_vgrid
	local dist_hgrid_hit
	local dist_vgrid_hit
	local cell_idx
	local cell_idx_x
	local cell_idx_y
	while stride < vwidth do
		if (castArc > ANGLE0 and castArc < ANGLE180) then
			hgrid = (shift_l((shift_r(pl_y,tile_shift)),tile_shift)) + tile_size
			dist_next_hgrid = tile_size
			xtmp = tantable2[castArc]*(hgrid-pl_y)
			xinter = xtmp + pl_x
		else
			hgrid = (shift_l((shift_r(pl_y,tile_shift)),tile_shift))
			dist_next_hgrid = -tile_size
			xtmp = tantable2[castArc]*(hgrid-pl_y)
			xinter = xtmp + pl_x
			hgrid = hgrid - 1
		end
		if (castArc == ANGLE0 or castArc == ANGLE180) then -- Prevent asymptotics values
			dist_hgrid_hit = 99999
		else
			local dist_next_xinter = xsteptable[castArc]
			while true do
				xgrid_index = shift_r(floor_num(xinter),tile_shift)
				ygrid_index = shift_r(hgrid,tile_shift)
				cell_idx_x = ygrid_index*map_width+xgrid_index+1
				if (xgrid_index >= map_width or ygrid_index >= map_height or xgrid_index < 0 or ygrid_index < 0) then
					dist_hgrid_hit = 9999
					break
				elseif (map[cell_idx_x] ~= 0) then
					dist_hgrid_hit = (xinter - pl_x) * costable2[castArc]
					break
				else
					xinter = xinter + dist_next_xinter
					hgrid = hgrid + dist_next_hgrid
				end
			end
		end
		if castArc < ANGLE90 or castArc > ANGLE270 then
			vgrid = tile_size + (shift_l(shift_r(pl_x,tile_shift),tile_shift))
			dist_next_vgrid = tile_size
			ytmp = tantable[castArc]*(vgrid - pl_x)
			yinter = ytmp + pl_y
		else
			vgrid = shift_l(shift_r(pl_x,tile_shift),tile_shift)
			dist_next_vgrid = 0 - tile_size
			ytmp = tantable[castArc]*(vgrid-pl_x)
			yinter = ytmp + pl_y
			vgrid = vgrid - 1
		end
		if (castArc == ANGLE90 or castArc == ANGLE270) then
			dist_vgrid_hit = 99999
		else
			local dist_next_yinter = ysteptable[castArc]
			dist_vgrid_hit = 0
			while dist_vgrid_hit <= dist_hgrid_hit do
				xgrid_index = shift_r(vgrid,tile_shift)
				ygrid_index = shift_r(floor_num(yinter),tile_shift)
				cell_idx_y = ygrid_index*map_width+xgrid_index+1
				if (xgrid_index >= map_width or ygrid_index >= map_height or xgrid_index < 0 or ygrid_index < 0) then
					dist_vgrid_hit = 9999
					break
				elseif (map[cell_idx_y] ~= 0) then
					dist_vgrid_hit = (yinter-pl_y)*sintable2[castArc]
					break
				else
					yinter = yinter + dist_next_yinter
					vgrid = vgrid + dist_next_vgrid
				end
			end
		end
		if (dist_hgrid_hit < dist_vgrid_hit) then
			dist = dist_hgrid_hit
			xinter = floor_num(xinter)
			offs = xinter - (shift_l((shift_r(xinter,tile_shift)),tile_shift))			
			cell_idx = cell_idx_x
		else
			dist = dist_vgrid_hit
			yinter = floor_num(yinter)
			offs = yinter - shift_l(shift_r(yinter,tile_shift),tile_shift)
			cell_idx = cell_idx_y
		end
		dist = dist / fishtable[stride]
		zbuffer[stride] = dist
		wh = floor_num(wall_height * dist_proj / dist)
		bot_wall = ycenter + floor_num(wh * 0.5)
		top_wall = vheight-bot_wall
		if (bot_wall >= vheight) then
			bot_wall = vheight - 1
		end
		RenderRay(x,y,stride,top_wall,wh,cell_idx,offs)
		stride = stride + accuracy
		castArc = castArc + accuracy
		if castArc >= ANGLE360 then
			castArc = castArc - ANGLE360
		end
	end
end

--[[renderMap: Render 2D map scene using GPU]]--
function RayCast3D.renderMap(x, y, width)
	local u = 0
	local v = 0
	while (u < map_width) do
		v = 0
		while (v < map_height) do
			tmp = map[v*map_width+u+1]
			if (tmp==0) then
				color = floor_c
			else
				if tmp == 1 then
					color = wall_c
				else
					
				end
			end
			xp = x + u * width
			yp = y + v * width
			if tmp == 1 or tmp == 0 then
				drawRect(xp, xp + width, yp, yp + width, color)
			else
				w = getWidth(tmp)
				s = width / w
				Graphics.drawScaleImage(xp, yp, tmp, s, s)
			end
			v = v + 1
		end
		u = u + 1
	end
	local xpp = x + (pl_x / tile_size) * width
	local ypp = y + (pl_y /tile_size) * width
	drawRect(xpp,xpp+2,ypp,ypp+2,player_c)
end

--[[enableFloors: Enable floor rendering]]--
function RayCast3D.enableFloor(val)
	floors = val
	ResetRenderer()
end

--[[enableSky: Enable sky rendering]]--
function RayCast3D.enableSky(val)
	sky = val
	ResetRenderer()
end

--[[spawnPlayer: Spawn player on the map]]--
function RayCast3D.spawnPlayer(x, y, angle)
	pl_x = x
	pl_y = y
	pl_angle = floor_num(rad2arc(deg2rad(angle)))
	ycenter = shift_r(vheight,1)
end

function convertAngle(angle)
	return floor_num(rad2arc(deg2rad(angle)))
end

--[[getPlayer: Gets player status]]--
function RayCast3D.getPlayer()
	return {["x"] = pl_x, ["y"] = pl_y, ["angle"] = rad2deg(arc2rad(pl_angle))}
end

--[[movePlayer: Moves player]]--
function RayCast3D.movePlayer(dir, speed)
	xmov = ceil_num((costable[pl_angle] * speed) - .5)
	ymov = ceil_num((sintable[pl_angle] * speed) - .5)
	old_x = pl_x
	old_y = pl_y
	if dir == FORWARD then
		pl_x = pl_x + xmov
		pl_y = pl_y + ymov
	elseif dir == BACK then
		pl_x = pl_x - xmov
		pl_y = pl_y - ymov
	elseif dir == LEFT then
		pl_x = pl_x + ymov
		pl_y = pl_y - xmov
	elseif dir == RIGHT then
		pl_x = pl_x - ymov
		pl_y = pl_y + xmov
	end
	if noclip then
		return
	end
	ytmp = shift_r(pl_y,tile_shift)
	xtmp = shift_r(pl_x,tile_shift)
	new_cell = 1 + (xtmp) + (ytmp * map_width)
	if map[new_cell] ~= 0 then
		old2_x = pl_x
		old2_y = pl_y
		ydiff = shift_r(old_y,tile_shift)
		ydiff2 = ydiff - ytmp
		xdiff = shift_r(old_x,tile_shift)
		xdiff2 = xdiff - xtmp
		if  map[1 + (xdiff) + (ytmp * map_width)] ~= 0 then
			if ydiff2 > 0 then
				pl_y = shift_l(ytmp,tile_shift) + (tile_size + 1)
			elseif ydiff2 < 0 then
				pl_y = shift_l(ytmp,tile_shift) - 1
			end
		end
		xdiff = shift_r(old_x,tile_shift)
		xdiff2 = xdiff - xtmp
		if map[1 + (xtmp) + (ydiff * map_width)] ~= 0 then
			if xdiff2 > 0 then
				pl_x = shift_l(xtmp,tile_shift) + (tile_size + 1)
			elseif xdiff2 < 0 then
				pl_x = shift_l(xtmp,tile_shift) - 1
			end
		end
		if old2_x == pl_x and old2_y == pl_y then
			pl_x = old_x
			pl_y = old_y
		end
	end
end

--[[rotateCamera: Rotates camera]]--
function RayCast3D.rotateCamera(dir, speed)
	if dir == LEFT then
		pl_angle = pl_angle - speed
		if pl_angle < ANGLE0 then
			pl_angle = floor_num(pl_angle + ANGLE360)
		end
	elseif dir == RIGHT then
		pl_angle = pl_angle + speed
		if pl_angle >= ANGLE360 then
			pl_angle = floor_num(pl_angle - ANGLE360)
		end
	elseif dir == FORWARD then
		ycenter = ycenter - shift_r(speed,2)
		if ycenter < 0 then
			ycenter = 0
		end
	elseif dir == BACK then
		ycenter = ycenter + shift_r(speed,2)
		if ycenter > vheight then
			ycenter = vheight
		end
	end
end

--[[loadMap: Loads a map in the engine]]--
function RayCast3D.loadMap(map_table, m_width, m_height, t_size, w_height)
	wall_height = w_height
	if t_size ~= tile_size then
		tile_size = t_size
		tmp = 2
		i = 1
		while tmp < tile_size do
			tmp = shift_l(tmp,1)
			i = i + 1
		end
		if tmp ~= tile_size then
			error("Map tile-size must be 2^n pixels.")
		end
		tile_shift = i
		ResetAngles()
	end
	map_width = m_width
	map_height = m_height
	map = map_table
end

--[[setAccuracy: Sets renderer accuracy]]--
function RayCast3D.setAccuracy(val)
	accuracy = val
end

--[[setFloorColor: Sets floor color]]--
function RayCast3D.setFloorColor(val)
	floor_c = val
end

--[[setSkyColor: Sets sky color]]--
function RayCast3D.setSkyColor(val)
	sky_c = val
end

--[[setWallColor: Sets wall color]]--
function RayCast3D.setWallColor(val)
	wall_c = val
end

--[[setSkyColor: Sets player color]]--
function RayCast3D.setPlayerColor(val)
	player_c = val
end

--[[noClipMode: Sets noClip mode status]]--
function RayCast3D.noClipMode(val)
	noclip = val
end

--[[useShading: Sets Shading status]]--
function RayCast3D.useShading(val)
	shading = val
	ResetRenderer()
end

--[[setDepth: Sets Shading depth of field]]--
function RayCast3D.setDepth(val)
	shad_val = val
end

--[[setDepth: Sets Shading color]]--
function RayCast3D.setShadingColor(r, g, b)
	shad_r = r
	shad_g = g
	shad_b = b
end

--[[shoot: Shoot a ray and returns cell x,y values of first wall]]--
function RayCast3D.shoot(x, y, angle)
	local castArc = floor_num(rad2arc(deg2rad(angle)))
	local hgrid
	local vgrid
	local xtmp
	local xinter
	local yinter
	local ytmp
	local dist_next_hgrid
	local dist_next_vgrid
	local dist_next_xinter
	local dist_next_yinter
	local dist_hgrid_hit
	local dist_vgrid_hit
	local cell_idx
	local cell_idx_x
	local cell_idx_y
	if (castArc > ANGLE0 and castArc < ANGLE180) then
		hgrid = shift_l(shift_r(y,tile_shift),tile_shift) + tile_size
		dist_next_hgrid = tile_size
		xtmp = tantable2[castArc]*(hgrid-y)
		xinter = xtmp + x
	else
		hgrid = shift_l(shift_r(y,tile_shift),tile_shift)
		dist_next_hgrid = -tile_size
		xtmp = tantable2[castArc]*(hgrid-y)
		xinter = xtmp + x
		hgrid = hgrid - 1
	end
	if (castArc == ANGLE0 or castArc == ANGLE180) then -- Prevent asymptotics values
		dist_hgrid_hit = 99999
	else
		dist_next_xinter = xsteptable[castArc]
		while true do
			xgrid_index = shift_r(floor_num(xinter),tile_shift)
			ygrid_index = shift_r(hgrid,tile_shift)
			cell_idx_x = ygrid_index*map_width+xgrid_index+1
			if (xgrid_index >= map_width or ygrid_index >= map_height or xgrid_index < 0 or ygrid_index < 0) then
				dist_hgrid_hit = 9999
				break
			elseif (map[cell_idx_x] ~= 0) then
				dist_hgrid_hit = (xinter - x) * costable2[castArc]
				break
			else
				xinter = xinter + dist_next_xinter
				hgrid = hgrid + dist_next_hgrid
			end
		end
		xx = xgrid_index
		xy = ygrid_index
	end
	if castArc < ANGLE90 or castArc > ANGLE270 then
		vgrid = tile_size + shift_l(shift_r(x,tile_shift),tile_shift)
		dist_next_vgrid = tile_size
		ytmp = tantable[castArc]*(vgrid - x)
		yinter = ytmp + y
	else
		vgrid = shift_l(shift_r(x,tile_shift),tile_shift)
		dist_next_vgrid = 0 - tile_size
		ytmp = tantable[castArc]*(vgrid-x)
		yinter = ytmp + y
		vgrid = vgrid - 1
	end
	if (castArc == ANGLE90 or castArc == ANGLE270) then
		dist_vgrid_hit = 99999
	else
		dist_next_yinter = ysteptable[castArc]
		dist_vgrid_hit = 0
		while dist_vgrid_hit <= dist_hgrid_hit do
			xgrid_index = shift_r(vgrid,tile_shift)
			ygrid_index = shift_r(floor_num(yinter),tile_shift)
			cell_idx_y = ygrid_index*map_width+xgrid_index+1
			if (xgrid_index >= map_width or ygrid_index >= map_height or xgrid_index < 0 or ygrid_index < 0) then
				dist_vgrid_hit = 9999
				break
			elseif (map[cell_idx_y] ~= 0) then
				dist_vgrid_hit = (yinter-y)*sintable2[castArc]
				break
			else
				yinter = yinter + dist_next_yinter
				vgrid = vgrid + dist_next_vgrid
			end
		end
		yx = xgrid_index
		yy = ygrid_index
	end
	if (dist_hgrid_hit < dist_vgrid_hit) then
		x = xx
		y = xy
	else
		x = yx
		y = yy
	end
	return {["x"] = x, ["y"] = y}
end

-- ═══════════════════════════════════════════════════════════════
--  SPRITE / BILLBOARD SYSTEM
-- ═══════════════════════════════════════════════════════════════

--[[addSprite: Add a billboard sprite, returns 1-based index]]--
function RayCast3D.addSprite(wx, wy, img, scl, voff, blocking)
	sprite_count = sprite_count + 1
	sprites[sprite_count] = {
		x = wx, y = wy, img = img,
		scale = scl or 1.0, voff = voff or 0.0,
		visible = true, blocking = blocking or false,
	}
	return sprite_count
end

--[[removeSprite: Remove sprite by index]]--
function RayCast3D.removeSprite(idx)
	if idx >= 1 and idx <= sprite_count then
		table.remove(sprites, idx)
		sprite_count = sprite_count - 1
	end
end

--[[moveSprite: Set sprite world position]]--
function RayCast3D.moveSprite(idx, wx, wy)
	if sprites[idx] then
		sprites[idx].x = wx
		sprites[idx].y = wy
	end
end

--[[setSpriteVisible: Show/hide a sprite]]--
function RayCast3D.setSpriteVisible(idx, vis)
	if sprites[idx] then
		sprites[idx].visible = vis
	end
end

--[[setSpriteImage: Change a sprite's image]]--
function RayCast3D.setSpriteImage(idx, img)
	if sprites[idx] then
		sprites[idx].img = img
	end
end

--[[clearSprites: Remove all sprites]]--
function RayCast3D.clearSprites()
	sprites = {}
	sprite_count = 0
end

--[[getSpriteCount: Returns active sprite count]]--
function RayCast3D.getSpriteCount()
	return sprite_count
end

--[[setPlayerPos: Reposition player without resetting ycenter]]--
function RayCast3D.setPlayerPos(nx, ny)
	pl_x = nx
	pl_y = ny
end

--[[checkSpriteCollision: Check if player overlaps a blocking sprite.
    Returns the sprite index (1-based) or 0.]]--
function RayCast3D.checkSpriteCollision(radius)
	radius = radius or 16
	local rsq = radius * radius
	for i = 1, sprite_count do
		local s = sprites[i]
		if s and s.blocking and s.visible then
			local dx = pl_x - s.x
			local dy = pl_y - s.y
			if dx * dx + dy * dy < rsq then
				return i
			end
		end
	end
	return 0
end

--[[renderSprites: Render all visible billboard sprites using the
    z-buffer populated by renderScene. Call AFTER renderScene.]]--
function RayCast3D.renderSprites(x, y)
	if sprite_count == 0 then
		return
	end

	-- Camera direction vectors derived from pl_angle
	local dirX = costable[pl_angle]
	local dirY = sintable[pl_angle]
	-- Camera plane perpendicular to direction, scaled by FOV
	-- For 60° FOV: plane half-length = tan(30°) ≈ 0.57735
	local planeX = -dirY * 0.57735
	local planeY =  dirX * 0.57735

	local invDet = 1.0 / (planeX * dirY - dirX * planeY)

	-- Build list of visible sprites with distance
	local count = 0
	for i = 1, sprite_count do
		local s = sprites[i]
		if s and s.visible then
			local dx = s.x - pl_x
			local dy = s.y - pl_y
			local dist_sq = dx * dx + dy * dy
			count = count + 1
			sprite_order[count] = { idx = i, dist = dist_sq }
		end
	end

	-- Insertion sort far-to-near (descending distance)
	for i = 2, count do
		local key = sprite_order[i]
		local j = i - 1
		while j >= 1 and sprite_order[j].dist < key.dist do
			sprite_order[j + 1] = sprite_order[j]
			j = j - 1
		end
		sprite_order[j + 1] = key
	end

	local half_w = vwidth * 0.5

	-- Render each sprite
	for i = 1, count do
		local s = sprites[sprite_order[i].idx]
		local dx = s.x - pl_x
		local dy = s.y - pl_y

		-- Transform sprite position into camera space
		local transformX = invDet * (dirY * dx - dirX * dy)
		local transformY = invDet * (-planeY * dx + planeX * dy)

		-- Skip sprites behind the camera
		if transformY > 0.1 then
			local spriteScreenX = floor_num(half_w * (1.0 + transformX / transformY))
			local spriteHeight = floor_num(math.abs(wall_height * dist_proj / transformY) * s.scale)
			local spriteWidth = spriteHeight  -- square billboard

			-- Vertical centering on horizon, shifted by vertical offset
			local voff_px = floor_num(s.voff * dist_proj / transformY)
			local drawStartY = ycenter - floor_num(spriteHeight * 0.5) - voff_px
			local drawStartX = spriteScreenX - floor_num(spriteWidth * 0.5)

			-- Simple whole-sprite z-test at center column
			local testCol = spriteScreenX
			if testCol >= 0 and testCol < vwidth then
				-- Only draw if sprite is closer than the wall at this column
				-- zbuffer is keyed by stride values (0, accuracy, 2*accuracy, ...)
				-- snap to nearest stride column
				local snapCol = floor_num(testCol / accuracy) * accuracy
				if zbuffer[snapCol] and transformY < zbuffer[snapCol] then
					local img = s.img
					if img then
						local iw = getWidth(img)
						local ih = getHeight(img)
						local sx = spriteWidth / iw
						local sy = spriteHeight / ih
						-- drawImageExtended anchor quirk: subtract full scaled dimensions
						local dstX = drawStartX - (iw * sx)
						local dstY = drawStartY - (ih * sy)
						drawImage(dstX + x, dstY + y, img, 0, 0, iw, ih, 0, sx, sy)
					end
				end
			end
		end
	end

	-- Clear sort buffer references for GC
	for i = 1, count do
		sprite_order[i] = nil
	end
end
from __future__ import annotations

import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

from lpp_exporter import _action_to_lua_inline, export_lpp
from models import (
    AnimationExport,
    Behavior,
    BehaviorAction,
    CollisionBox,
    ObjectDefinition,
    PaperDollAsset,
    PaperDollLayer,
    PlacedObject,
    Project,
    RegisteredAudio,
    RegisteredImage,
    Scene,
    effective_placed_behaviors,
    make_component,
    seed_instance_behaviors_from_definition,
)
from plugin_registry import scan_plugins
from windows_exporter import _build_windows_export_bundle


def _project_with_registry(project_folder: str | Path | None = None) -> Project:
    project = Project()
    project.project_folder = str(project_folder) if project_folder else None
    project.plugin_registry = scan_plugins(project_folder)
    project.scenes = []
    project.object_defs = []
    return project


def _write_fake_love_runtime(root: Path) -> Path:
    runtime_dir = root / "fake_love_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "love.exe").write_bytes(b"LOVE-EXE")
    (runtime_dir / "love.dll").write_bytes(b"LOVE-DLL")
    (runtime_dir / "license.txt").write_text("license", encoding="utf-8")
    (runtime_dir / "readme.txt").write_text("readme", encoding="utf-8")
    return runtime_dir


def _windows_export_project(root: Path, scene_type: str = "2d", include_save: bool = False, include_storage: bool = False) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    project = _project_with_registry(root)
    project.title = "Windows Preview"
    project.title_id = "WPRE00001"
    project.author = "Codex"
    project.version = "1.0"

    scene = Scene(name="Preview Scene")
    components = []
    if include_save:
        components.append(make_component("SaveGame"))
    if include_storage:
        components.append(make_component("StorageService"))

    if scene_type == "3d":
        scene.scene_type = "3d"
        scene.map_data.width = 3
        scene.map_data.height = 3
        scene.map_data.cells = [
            1, 1, 1,
            1, 0, 1,
            1, 1, 1,
        ]
        components.append(make_component("Raycast3DConfig"))

    scene.components = components
    project.scenes = [scene]
    return project


def _paperdoll_project_fixture() -> tuple[Project, PaperDollAsset]:
    project = _project_with_registry()
    project.images = [
        RegisteredImage(id="img_base", name="Base Mouth", path="base_mouth.png", category="character"),
        RegisteredImage(id="img_blink", name="Blink", path="blink.png", category="character"),
        RegisteredImage(id="img_mouth_1", name="Mouth 1", path="mouth_1.png", category="character"),
        RegisteredImage(id="img_mouth_2", name="Mouth 2", path="mouth_2.png", category="character"),
        RegisteredImage(id="img_mouth_3", name="Mouth 3", path="mouth_3.png", category="character"),
    ]
    project.audio = [
        RegisteredAudio(id="aud_dialog", name="Dialog Tick", path="dialog_tick.wav", audio_type="sfx")
    ]

    doll = PaperDollAsset(id="doll_1", name="Hero Puppet")
    doll.root_layers = [
        PaperDollLayer(id="mouth_layer", name="Mouth", image_id="img_base")
    ]
    doll.blink.enabled = True
    doll.blink.layer_id = "mouth_layer"
    doll.blink.alt_image_id = "img_blink"
    doll.blink.interval_min = 0.5
    doll.blink.interval_max = 1.0
    doll.blink.blink_duration = 0.2
    doll.blink.node_hook_mode = "supplement"

    doll.mouth.enabled = True
    doll.mouth.layer_id = "mouth_layer"
    doll.mouth.image_ids = ["img_mouth_1", "img_mouth_2", "img_mouth_3"]
    doll.mouth.alt_image_id = "img_mouth_1"
    doll.mouth.cycle_speed = 0.15
    doll.mouth.node_hook_mode = "replace"

    doll.idle_breathing.enabled = True
    doll.idle_breathing.layer_id = "mouth_layer"
    doll.idle_breathing.scale_amount = 0.03
    doll.idle_breathing.speed = 2.5
    doll.idle_breathing.node_hook_mode = "supplement"

    project.paper_dolls = [doll]

    puppet = ObjectDefinition(
        id="puppet_def",
        name="Puppet",
        behavior_type="LayerAnimation",
        layer_anim_id=doll.id,
        layer_anim_blink=True,
        layer_anim_talk=True,
        layer_anim_idle=True,
        behaviors=[
            Behavior(
                trigger="on_layer_anim_blink",
                actions=[BehaviorAction(action_type="emit_signal", signal_name="blink_evt")],
            ),
            Behavior(
                trigger="on_layer_anim_talk_step",
                actions=[BehaviorAction(action_type="emit_signal", signal_name="talk_evt")],
            ),
            Behavior(
                trigger="on_layer_anim_idle_cycle",
                actions=[BehaviorAction(action_type="emit_signal", signal_name="idle_evt")],
            ),
            Behavior(
                trigger="on_scene_start",
                actions=[
                    BehaviorAction(
                        action_type="vn_dialog_sound",
                        vn_dialog_sound_id="aud_dialog",
                        vn_dialog_sound_mode="repeat_on_cycle",
                    )
                ],
            ),
        ],
    )
    project.object_defs = [puppet]

    scene = Scene(name="Paperdoll Scene")
    scene.components = [make_component("VNDialogBox")]
    scene.placed_objects = [
        PlacedObject(instance_id="puppet_1", object_def_id="puppet_def", x=32, y=48)
    ]
    project.scenes = [scene]
    return project, doll


class EnginePrimitivesTests(unittest.TestCase):
    def test_builtin_packs_load_and_project_conflicts_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plugin_dir = root / "plugins" / "conflict_pack"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.py").write_text(
                textwrap.dedent(
                    """
                    def _noop(action, obj_var, project):
                        return []

                    PLUGIN = {
                        "name": "Conflict Pack",
                        "actions": [
                            {
                                "key": "prim_find_object",
                                "label": "Conflict",
                                "lua_export": _noop,
                            }
                        ],
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = scan_plugins(root)

            self.assertIn("prim_find_object", registry.action_descriptors)
            self.assertTrue(
                any(
                    plugin_id == "conflict_pack" and "Duplicate action key 'prim_find_object'" in message
                    for plugin_id, message in registry.errors
                )
            )

    def test_plugin_component_editor_tools_normalize_for_grid_and_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plugin_dir = root / "plugins" / "editor_tools_pack"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.py").write_text(
                textwrap.dedent(
                    """
                    PLUGIN = {
                        "name": "Editor Tools Pack",
                        "components": [
                            {
                                "type": "DangerZones",
                                "label": "Danger Zones",
                                "defaults": {
                                    "map_width": 8,
                                    "map_height": 6,
                                    "tile_size": 16,
                                    "danger_cells": [],
                                },
                                "fields": [],
                                "editor_tools": [
                                    {
                                        "kind": "grid_map",
                                        "data_key": "danger_cells",
                                        "width_key": "map_width",
                                        "height_key": "map_height",
                                        "cell_size_key": "tile_size",
                                        "mode": "binary",
                                        "default_cell": 0,
                                        "active_value": 1,
                                        "overlay_color": "#ef4444",
                                    }
                                ],
                            },
                            {
                                "type": "PatrolRoute",
                                "label": "Patrol Route",
                                "defaults": {
                                    "route_name": "Route A",
                                    "route_closed": False,
                                    "route_points": [],
                                },
                                "fields": [],
                                "editor_tools": [
                                    {
                                        "kind": "path",
                                        "points_key": "route_points",
                                        "closed_key": "route_closed",
                                        "name_key": "route_name",
                                        "draw_label": "Draw Route",
                                        "supports_bezier": True,
                                    }
                                ],
                            },
                        ],
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = scan_plugins(root)

            self.assertFalse(
                any(plugin_id == "editor_tools_pack" for plugin_id, _message in registry.errors)
            )
            grid_desc = registry.get_component_descriptor("DangerZones")
            path_desc = registry.get_component_descriptor("PatrolRoute")
            self.assertIsNotNone(grid_desc)
            self.assertIsNotNone(path_desc)
            self.assertEqual(grid_desc["editor_tools"][0]["kind"], "grid_map")
            self.assertEqual(grid_desc["editor_tools"][0]["data_key"], "danger_cells")
            self.assertEqual(path_desc["editor_tools"][0]["kind"], "path")
            self.assertTrue(path_desc["editor_tools"][0]["supports_bezier"])

    def test_plugin_component_editor_tools_validate_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plugin_dir = root / "plugins" / "broken_editor_tools"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.py").write_text(
                textwrap.dedent(
                    """
                    PLUGIN = {
                        "name": "Broken Editor Tools",
                        "components": [
                            {
                                "type": "BrokenGrid",
                                "label": "Broken Grid",
                                "defaults": {},
                                "fields": [],
                                "editor_tools": [
                                    {
                                        "kind": "grid_map",
                                        "data_key": "cells",
                                        "width_key": "map_width",
                                        "height_key": "map_height",
                                        "cell_size_key": "tile_size",
                                        "mode": "scalar",
                                    }
                                ],
                            }
                        ],
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = scan_plugins(root)

            self.assertTrue(
                any(
                    plugin_id == "broken_editor_tools" and "paint_value_key" in message
                    for plugin_id, message in registry.errors
                )
            )
            self.assertIsNone(registry.get_component_descriptor("BrokenGrid"))

    def test_export_uses_unique_instance_vars_and_broadcasts_legacy_targets(self):
        project = _project_with_registry()

        enemy = ObjectDefinition()
        enemy.id = "enemy_def"
        enemy.name = "Enemy"
        enemy.width = 16
        enemy.height = 16

        projectile = ObjectDefinition()
        projectile.id = "projectile_def"
        projectile.name = "Projectile"
        projectile.width = 8
        projectile.height = 8

        controller = ObjectDefinition()
        controller.id = "controller_def"
        controller.name = "Controller"
        controller.width = 16
        controller.height = 16
        controller.behaviors = [
            Behavior(
                trigger="on_scene_start",
                actions=[
                    BehaviorAction(action_type="destroy_object", object_def_id="enemy_def"),
                    BehaviorAction(action_type="create_object", object_def_id="projectile_def", target_x=40, target_y=60),
                ],
            )
        ]

        scene = Scene()
        scene.name = "Foundation"
        scene.placed_objects = [
            PlacedObject(instance_id="controller_inst", object_def_id="controller_def", x=10, y=10),
            PlacedObject(instance_id="enemy_a", object_def_id="enemy_def", x=100, y=120),
            PlacedObject(instance_id="enemy_b", object_def_id="enemy_def", x=180, y=220),
        ]

        project.object_defs = [controller, enemy, projectile]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]
        index_lua = files["index.lua"]

        self.assertIn("obj_enemy_a_x", scene_lua)
        self.assertIn("obj_enemy_b_x", scene_lua)
        self.assertIn('prim.register_placed("enemy_a", "enemy_def", "enemy_a", "obj_enemy_a")', scene_lua)
        self.assertIn('prim.register_placed("enemy_b", "enemy_def", "enemy_b", "obj_enemy_b")', scene_lua)
        self.assertIn('prim.destroy_handle("enemy_a")', scene_lua)
        self.assertIn('prim.destroy_handle("enemy_b")', scene_lua)
        self.assertIn('prim.register_spawned(_iid, "projectile_def", _live_objects[_iid])', scene_lua)
        self.assertIn("lib/primitives.lua", files)
        self.assertIn("require('lib/primitives')", index_lua)
        self.assertIn('spawn_object_defs["projectile_def"]', index_lua)

    def test_builtin_pack_actions_emit_prim_calls(self):
        project = _project_with_registry()

        core_action = BehaviorAction(
            action_type="prim_find_nearest_object",
            plugin_data={
                "prim_find_nearest_object": {
                    "result_var": "nearest_target",
                    "distance_var": "nearest_distance",
                }
            },
        )
        combat_action = BehaviorAction(
            action_type="prim_spawn_object_advanced",
            plugin_data={
                "prim_spawn_object_advanced": {
                    "spawn_object_id": "projectile_def",
                    "position_mode": "self",
                    "speed": 8.0,
                    "angle": 90.0,
                    "result_var": "spawned_handle",
                }
            },
        )
        world_action = BehaviorAction(
            action_type="prim_world_position_to_grid_cell",
            plugin_data={
                "prim_world_position_to_grid_cell": {
                    "grid_name": "grid1",
                    "col_var": "grid_col",
                    "row_var": "grid_row",
                }
            },
        )

        core_lines = "\n".join(_action_to_lua_inline(core_action, "obj_player", project))
        combat_lines = "\n".join(_action_to_lua_inline(combat_action, "obj_player", project))
        world_lines = "\n".join(_action_to_lua_inline(world_action, "obj_player", project))

        self.assertIn("prim.find_nearest", core_lines)
        self.assertIn("prim.spawn_object", combat_lines)
        self.assertIn("prim.set_velocity_polar", combat_lines)
        self.assertIn("prim.world_to_grid_cell", world_lines)

    def test_collision_cell_actions_emit_runtime_collision_calls(self):
        project = _project_with_registry()

        set_lines = "\n".join(
            _action_to_lua_inline(
                BehaviorAction(
                    action_type="collision_set_cell",
                    collision_layer_id="collision_main",
                    grid_col=2,
                    grid_row=3,
                    collision_value=0,
                ),
                "obj_player",
                project,
            )
        )
        toggle_lines = "\n".join(
            _action_to_lua_inline(
                BehaviorAction(
                    action_type="collision_toggle_cell",
                    collision_layer_id="collision_main",
                    grid_col_var="cell_x",
                    grid_row_var="cell_y",
                ),
                "obj_player",
                project,
            )
        )
        get_lines = "\n".join(
            _action_to_lua_inline(
                BehaviorAction(
                    action_type="collision_get_cell",
                    collision_layer_id="collision_main",
                    grid_col=5,
                    grid_row=6,
                    grid_result_var="cell_value",
                ),
                "obj_player",
                project,
            )
        )

        self.assertIn('prim.write_collision_cell("collision_main", 2, 3, 0)', set_lines)
        self.assertIn('prim.toggle_collision_cell("collision_main", cell_x, cell_y)', toggle_lines)
        self.assertIn('cell_value = prim.read_collision_cell("collision_main", 5, 6) or 0', get_lines)

    def test_object_definition_round_trips_blocks_2d_movement(self):
        obj = ObjectDefinition(
            id="brick_def",
            name="Brick",
            width=32,
            height=16,
            blocks_2d_movement=True,
        )

        loaded = ObjectDefinition.from_dict(obj.to_dict())

        self.assertTrue(loaded.blocks_2d_movement)

    def test_animation_collision_slots_round_trip(self):
        obj = ObjectDefinition(
            id="runner_def",
            name="Runner",
            behavior_type="Animation",
            ani_slots=[
                {"name": "idle", "ani_file_id": "ani_idle"},
                {"name": "run", "ani_file_id": "ani_idle"},
            ],
            ani_collision_boxes={
                "idle": [[CollisionBox(x=0, y=0, width=16, height=16)]],
                "run": [[CollisionBox(x=4, y=0, width=12, height=16)]],
            },
        )

        loaded = ObjectDefinition.from_dict(obj.to_dict())

        self.assertEqual(sorted(loaded.ani_collision_boxes.keys()), ["idle", "run"])
        self.assertEqual(loaded.ani_collision_boxes["idle"][0][0].x, 0)
        self.assertEqual(loaded.ani_collision_boxes["run"][0][0].x, 4)

    def test_animation_collision_slots_migrate_from_legacy_collision_boxes(self):
        legacy = {
            "id": "runner_def",
            "name": "Runner",
            "behavior_type": "Animation",
            "ani_slots": [
                {"name": "idle", "ani_file_id": "ani_idle"},
                {"name": "run", "ani_file_id": "ani_run"},
            ],
            "collision_boxes": [[{"x": 1, "y": 2, "width": 10, "height": 12}]],
        }

        loaded = ObjectDefinition.from_dict(legacy)

        self.assertEqual(sorted(loaded.ani_collision_boxes.keys()), ["idle", "run"])
        self.assertEqual(loaded.ani_collision_boxes["idle"][0][0].x, 1)
        self.assertEqual(loaded.ani_collision_boxes["run"][0][0].height, 12)

    def test_collision_box_roles_round_trip_and_legacy_default_to_physics(self):
        obj = ObjectDefinition(
            id="fighter_def",
            name="Fighter",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_idle"}],
            ani_collision_boxes={
                "idle": [[
                    CollisionBox(x=0, y=0, width=16, height=16, role="Physics"),
                    CollisionBox(x=2, y=2, width=12, height=12, role="Hurtbox"),
                    CollisionBox(x=8, y=4, width=10, height=6, role="Hitbox"),
                ]]
            },
        )

        loaded = ObjectDefinition.from_dict(obj.to_dict())
        self.assertEqual(loaded.ani_collision_boxes["idle"][0][0].role, "Physics")
        self.assertEqual(loaded.ani_collision_boxes["idle"][0][1].role, "Hurtbox")
        self.assertEqual(loaded.ani_collision_boxes["idle"][0][2].role, "Hitbox")

        legacy = CollisionBox.from_dict({"x": 1, "y": 2, "width": 3, "height": 4})
        self.assertEqual(legacy.role, "Physics")

    def test_export_emits_collision_runtime_helpers_and_solid_object_checks(self):
        project = _project_with_registry()

        player = ObjectDefinition(
            id="player_def",
            name="Player",
            width=16,
            height=24,
            affected_by_gravity=True,
            behaviors=[
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(
                            action_type="four_way_movement_collide",
                            movement_speed=3,
                            collision_layer_id="collision_main",
                            player_width=16,
                            player_height=24,
                        )
                    ],
                ),
                Behavior(
                    trigger="on_button_pressed",
                    actions=[
                        BehaviorAction(
                            action_type="jump",
                            jump_strength=8,
                            jump_max_count=2,
                            jump_collision_layer_id="collision_main",
                            jump_player_width=16,
                            jump_player_height=24,
                        )
                    ],
                ),
            ],
            collision_boxes=[[CollisionBox(x=0, y=0, width=16, height=24)]],
        )
        brick = ObjectDefinition(
            id="brick_def",
            name="Brick",
            width=32,
            height=16,
            blocks_2d_movement=True,
        )

        scene = Scene(name="Collision Test")
        collision = make_component("CollisionLayer")
        collision.id = "collision_main"
        collision.config["map_width"] = 4
        collision.config["map_height"] = 4
        collision.config["tile_size"] = 16
        collision.config["tiles"] = [
            1, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
        ]
        gravity = make_component("Gravity")
        gravity.config["gravity_direction"] = "down"
        gravity.config["gravity_strength"] = 0.5
        gravity.config["terminal_velocity"] = 10
        scene.components = [collision, gravity]
        scene.placed_objects = [
            PlacedObject(instance_id="player_1", object_def_id="player_def", x=16, y=16),
            PlacedObject(instance_id="brick_1", object_def_id="brick_def", x=32, y=64),
        ]

        project.object_defs = [player, brick]
        project.scenes = [scene]

        files = export_lpp(project)
        index_lua = files["index.lua"]
        primitives_lua = files["lib/primitives.lua"]
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("function prim.read_collision_cell(layer_id, col, row)", primitives_lua)
        self.assertIn("function prim.write_collision_cell(layer_id, col, row, value)", primitives_lua)
        self.assertIn("function prim.toggle_collision_cell(layer_id, col, row)", primitives_lua)
        self.assertIn("return write_collision_cell(grid, col, row, value)", primitives_lua)
        self.assertNotIn("_scene_grids[layer_id]", primitives_lua)
        self.assertIn('collision_grids["collision_main"] = {', index_lua)
        self.assertIn('solid_object_defs["brick_def"] = true', index_lua)
        self.assertIn('obj_collision_bounds["brick_def"] = {w=32, h=16}', index_lua)
        self.assertIn('obj_collision["player_def"] = {', index_lua)
        self.assertIn("function check_obj_vs_solids(self_handle, def_id, ox, oy, slot_name, frame)", index_lua)
        self.assertIn("check_obj_vs_solids(_self_handle, \"player_def\"", scene_lua)
        self.assertIn("local function _grav_hits(_gtest)", scene_lua)
        self.assertIn("obj_player_1_y = _resolved", scene_lua)
        self.assertIn("local _probe = obj_player_1_y + 1", scene_lua)
        self.assertIn("if not _landed and check_obj_vs_solids(\"player_1\", \"player_def\", obj_player_1_x, _probe, \"\", 0)", scene_lua)
        self.assertIn('role="Physics"', index_lua)
        self.assertIn('def_frame_boxes_by_role(def_id, slot_name, frame, "Physics")', index_lua)
        self.assertIn("function check_def_collision_physics(", index_lua)

    def test_export_uses_animation_slot_collision_tables_and_runtime_slot_tracking(self):
        project = _project_with_registry()

        runner = ObjectDefinition(
            id="runner_def",
            name="Runner",
            width=32,
            height=32,
            behavior_type="Animation",
            ani_slots=[
                {"name": "idle", "ani_file_id": "ani_idle"},
                {"name": "run", "ani_file_id": "ani_run"},
            ],
            ani_collision_boxes={
                "idle": [[CollisionBox(x=0, y=0, width=16, height=24)]],
                "run": [[CollisionBox(x=4, y=0, width=20, height=24)]],
            },
            behaviors=[
                Behavior(
                    trigger="on_button_pressed",
                    button="square",
                    actions=[BehaviorAction(action_type="ani_switch_slot", ani_slot_name="run")],
                ),
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(
                            action_type="four_way_movement_collide",
                            movement_speed=2,
                            collision_layer_id="collision_main",
                            player_width=32,
                            player_height=32,
                        )
                    ],
                ),
            ],
        )
        project.object_defs = [runner]
        project.animation_exports = [
            AnimationExport(
                id="ani_idle",
                name="Idle",
                spritesheet_path="idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=32,
                sheet_width=32,
                sheet_height=32,
                fps=12,
            ),
            AnimationExport(
                id="ani_run",
                name="Run",
                spritesheet_path="run.png",
                frame_count=1,
                frame_width=32,
                frame_height=32,
                sheet_width=32,
                sheet_height=32,
                fps=12,
            ),
        ]

        scene = Scene(name="Animation Slot Collision")
        collision = make_component("CollisionLayer")
        collision.id = "collision_main"
        collision.config["map_width"] = 2
        collision.config["map_height"] = 2
        collision.config["tile_size"] = 32
        collision.config["tiles"] = [0, 0, 0, 0]
        scene.components = [collision]
        scene.placed_objects = [
            PlacedObject(instance_id="runner_1", object_def_id="runner_def", x=0, y=0)
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        index_lua = files["index.lua"]
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("function def_frame_boxes(def_id, slot_name, frame)", index_lua)
        self.assertIn('obj_collision["runner_def"] = {', index_lua)
        self.assertIn('["idle"] = {', index_lua)
        self.assertIn('["run"] = {', index_lua)
        self.assertIn('obj_runner_1_ani_slot_name = "idle"', scene_lua)
        self.assertIn('obj_runner_1_ani_slot_name = "run"', scene_lua)
        self.assertIn('check_obj_vs_grid(_grid, "runner_def", _nx, obj_runner_1_y, obj_runner_1_ani_slot_name, obj_runner_1_ani_frame)', scene_lua)

    def test_app_essentials_export_async_triggers_and_runtime_lib(self):
        project = _project_with_registry()

        app_object = ObjectDefinition(
            id="app_def",
            name="App Controller",
            behaviors=[
                Behavior(
                    trigger="on_scene_start",
                    actions=[
                        BehaviorAction(
                            action_type="open_keyboard",
                            plugin_data={
                                "open_keyboard": {
                                    "request_id": "note_input",
                                    "title": "New Note",
                                    "target_var": "note_text",
                                    "initial_text_var": "note_seed",
                                    "max_length": 240,
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="show_confirm",
                            plugin_data={
                                "show_confirm": {
                                    "request_id": "delete_note",
                                    "message_text": "Delete this note?",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="show_message",
                            plugin_data={"show_message": {"message_text": "Saved."}},
                        ),
                        BehaviorAction(
                            action_type="store_current_date",
                            plugin_data={
                                "store_current_date": {
                                    "year_var": "year_value",
                                    "month_var": "month_value",
                                    "day_var": "day_value",
                                    "weekday_var": "weekday_value",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="store_current_time",
                            plugin_data={
                                "store_current_time": {
                                    "hour_var": "hour_value",
                                    "minute_var": "minute_value",
                                    "second_var": "second_value",
                                }
                            },
                        ),
                    ],
                ),
                Behavior(
                    trigger="on_keyboard_submit",
                    plugin_data={"on_keyboard_submit": {"request_id": "note_input"}},
                    actions=[BehaviorAction(action_type="emit_signal", signal_name="kb_submit")],
                ),
                Behavior(
                    trigger="on_keyboard_cancel",
                    plugin_data={"on_keyboard_cancel": {"request_id": "note_input"}},
                    actions=[BehaviorAction(action_type="emit_signal", signal_name="kb_cancel")],
                ),
                Behavior(
                    trigger="on_confirm_yes",
                    plugin_data={"on_confirm_yes": {"request_id": "delete_note"}},
                    actions=[BehaviorAction(action_type="emit_signal", signal_name="confirm_yes")],
                ),
                Behavior(
                    trigger="on_confirm_no",
                    plugin_data={"on_confirm_no": {}},
                    actions=[BehaviorAction(action_type="emit_signal", signal_name="confirm_no")],
                ),
            ],
        )

        scene = Scene(name="App Scene")
        scene.placed_objects = [
            PlacedObject(instance_id="app_inst", object_def_id="app_def", x=32, y=48)
        ]
        project.object_defs = [app_object]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]
        index_lua = files["index.lua"]
        app_ui_lua = files["lib/app_ui.lua"]

        self.assertIn("require('lib/app_ui')", index_lua)
        self.assertIn("app_ui_begin_frame()", scene_lua)
        self.assertIn('app_ui_open_keyboard("note_input", "New Note", "note_text", (note_seed or ""), 240)', scene_lua)
        self.assertIn('app_ui_show_confirm("delete_note", "Delete this note?")', scene_lua)
        self.assertIn('app_ui_show_message("Saved.")', scene_lua)
        self.assertIn("local _weekday, _day, _month, _year = System.getDate()", scene_lua)
        self.assertIn("local _hour, _minute, _second = System.getTime()", scene_lua)
        self.assertIn('if app_ui_keyboard_submitted("note_input") then', scene_lua)
        self.assertIn('if app_ui_keyboard_canceled("note_input") then', scene_lua)
        self.assertIn('if app_ui_confirmed_yes("delete_note") then', scene_lua)
        self.assertIn('if app_ui_confirmed_no("") then', scene_lua)
        self.assertIn("function app_ui_open_keyboard", app_ui_lua)
        self.assertIn("function app_ui_show_confirm", app_ui_lua)
        self.assertIn("function app_ui_show_message", app_ui_lua)

    def test_gui_button_uses_runtime_text_color_and_font_state(self):
        project = _project_with_registry()

        button = ObjectDefinition(
            id="button_def",
            name="Action Button",
            behavior_type="GUI_Button",
            gui_text="Launch",
            gui_text_color="#336699",
            gui_font_size=20,
            gui_width=160,
            gui_height=48,
            behaviors=[
                Behavior(
                    trigger="on_scene_start",
                    actions=[
                        BehaviorAction(action_type="set_label_text", object_def_id="button_def", dialogue_text="Open"),
                        BehaviorAction(action_type="set_label_color", object_def_id="button_def", color="#112233"),
                        BehaviorAction(action_type="set_label_size", object_def_id="button_def", frame_index=28),
                    ],
                )
            ],
        )

        scene = Scene(name="Buttons")
        scene.placed_objects = [
            PlacedObject(instance_id="button_inst", object_def_id="button_def", x=100, y=120)
        ]
        project.object_defs = [button]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn('obj_button_inst_text = "Launch"', scene_lua)
        self.assertIn("obj_button_inst_text_r = 51", scene_lua)
        self.assertIn("obj_button_inst_font_size = 20", scene_lua)
        self.assertIn('obj_button_inst_text = "Open"', scene_lua)
        self.assertIn("obj_button_inst_text_r = 17", scene_lua)
        self.assertIn("obj_button_inst_text_g = 34", scene_lua)
        self.assertIn("obj_button_inst_text_b = 51", scene_lua)
        self.assertIn("obj_button_inst_font_size = 28", scene_lua)
        self.assertIn("Font.setPixelSizes(deff, obj_button_inst_font_size)", scene_lua)
        self.assertIn("tostring(obj_button_inst_text or \"\")", scene_lua)
        self.assertNotIn('Font.print(deff, obj_button_inst_x + 8 + shake_offset_x, obj_button_inst_y + 8 + shake_offset_y, "Launch"', scene_lua)

    def test_builtin_device_and_storage_packs_export_with_service_components(self):
        project = _project_with_registry()

        controller = ObjectDefinition(
            id="controller_def",
            name="Service Controller",
            behaviors=[
                Behavior(
                    trigger="on_scene_start",
                    actions=[
                        BehaviorAction(
                            action_type="device_store_power_info",
                            plugin_data={
                                "device_store_power_info": {
                                    "battery_percent_var": "battery_pct",
                                    "charging_var": "battery_charging",
                                    "battery_life_minutes_var": "battery_minutes",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="device_store_profile_info",
                            plugin_data={
                                "device_store_profile_info": {
                                    "username_var": "account_name",
                                    "language_var": "language_name",
                                    "model_var": "model_name",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="device_store_app_info",
                            plugin_data={
                                "device_store_app_info": {
                                    "title_var": "app_title",
                                    "title_id_var": "app_title_id",
                                    "safe_mode_var": "app_safe_mode",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="storage_set_string",
                            plugin_data={
                                "storage_set_string": {
                                    "key": "selected_tab",
                                    "source_var": "current_tab",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="storage_get_bool",
                            plugin_data={
                                "storage_get_bool": {
                                    "key": "show_help",
                                    "target_var": "show_help_var",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="storage_save_document",
                            plugin_data={
                                "storage_save_document": {
                                    "document_id": "today_note",
                                    "source_var": "note_body",
                                }
                            },
                        ),
                        BehaviorAction(
                            action_type="storage_document_exists",
                            plugin_data={
                                "storage_document_exists": {
                                    "document_id": "today_note",
                                    "target_var": "note_exists",
                                }
                            },
                        ),
                    ],
                )
            ],
        )

        scene = Scene(name="Services")
        scene.components = [make_component("DeviceService"), make_component("StorageService")]
        scene.placed_objects = [
            PlacedObject(instance_id="controller_inst", object_def_id="controller_def", x=0, y=0)
        ]
        project.object_defs = [controller]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]
        index_lua = files["index.lua"]
        device_lua = files["lib/builtin_device.lua"]
        storage_lua = files["lib/builtin_storage.lua"]

        self.assertIn("require('lib/builtin_device')", index_lua)
        self.assertIn("require('lib/builtin_storage')", index_lua)
        self.assertIn("device_battery_percent()", scene_lua)
        self.assertIn("device_username()", scene_lua)
        self.assertIn("device_app_title()", scene_lua)
        self.assertIn('storage_set_string("selected_tab", tostring(current_tab or ""))', scene_lua)
        self.assertIn('show_help_var = storage_get_bool("show_help")', scene_lua)
        self.assertIn('storage_save_document("today_note", tostring(note_body or ""))', scene_lua)
        self.assertIn('note_exists = storage_document_exists("today_note")', scene_lua)
        self.assertIn('return "ux0:data/" .. tostring(System.getTitleID() or "APP") .. "/storage/"', storage_lua)
        self.assertIn('string.match(text, "^[%w_-]+$")', storage_lua)
        self.assertIn('return System.getBatteryPercentage() or 0', device_lua)
        self.assertIn('if model_id == 65536 then return "PS Vita" end', device_lua)

    def test_export_emits_role_filtered_object_overlap_queries_and_triggers(self):
        project = _project_with_registry()

        player = ObjectDefinition(
            id="player_def",
            name="Player",
            width=24,
            height=24,
            collision_boxes=[[
                CollisionBox(x=0, y=0, width=12, height=24, role="Physics"),
                CollisionBox(x=2, y=2, width=10, height=20, role="Hurtbox"),
            ]],
            behaviors=[
                Behavior(
                    trigger="on_object_overlap",
                    overlap_object_id="enemy_def",
                    overlap_source_role="Hurtbox",
                    overlap_target_role="Hitbox",
                    actions=[BehaviorAction(action_type="set_flag", bool_name="player_hit", bool_value=True)],
                ),
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(
                            action_type="if_object_overlap",
                            object_def_id="enemy_def",
                            collision_source_role="Hurtbox",
                            collision_target_role="Hitbox",
                            true_actions=[BehaviorAction(action_type="set_flag", bool_name="touching_enemy", bool_value=True)],
                            false_actions=[BehaviorAction(action_type="set_flag", bool_name="touching_enemy", bool_value=False)],
                        ),
                        BehaviorAction(
                            action_type="get_object_overlap_count",
                            object_def_id="enemy_def",
                            collision_source_role="Hurtbox",
                            collision_target_role="Hitbox",
                            var_name="enemy_overlap_count",
                        ),
                    ],
                ),
            ],
        )
        enemy = ObjectDefinition(
            id="enemy_def",
            name="Enemy",
            width=24,
            height=24,
            collision_boxes=[[
                CollisionBox(x=0, y=0, width=12, height=24, role="Physics"),
                CollisionBox(x=8, y=2, width=10, height=20, role="Hitbox"),
            ]],
        )

        scene = Scene(name="Overlap Test")
        scene.placed_objects = [
            PlacedObject(instance_id="player_1", object_def_id="player_def", x=0, y=0),
            PlacedObject(instance_id="enemy_1", object_def_id="enemy_def", x=0, y=0),
        ]
        project.object_defs = [player, enemy]
        project.scenes = [scene]

        files = export_lpp(project)
        index_lua = files["index.lua"]
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("function count_object_overlaps(self_handle, def_id, ox, oy, slot_name, frame, target_id, source_role, target_role)", index_lua)
        self.assertIn("function check_def_collision_filtered(", index_lua)
        self.assertIn('player_def", obj_player_1_x, obj_player_1_y, "", 0, "enemy_def", "Hurtbox", "Hitbox"', scene_lua)
        self.assertIn('enemy_overlap_count = count_object_overlaps(', scene_lua)
        self.assertIn('if _overlap_now then', scene_lua)
        self.assertIn('obj_player_1_obj_overlap_prev_', scene_lua)

    def test_instance_jump_behaviors_initialize_jump_state_for_gravity_objects(self):
        project = _project_with_registry()

        runner = ObjectDefinition(
            id="runner_def",
            name="Runner",
            width=32,
            height=32,
            affected_by_gravity=True,
            behavior_type="Animation",
        )

        scene = Scene(name="Instance Jump Init")
        collision = make_component("CollisionLayer")
        collision.id = "collision_main"
        collision.config["map_width"] = 2
        collision.config["map_height"] = 2
        collision.config["tile_size"] = 32
        collision.config["tiles"] = [0, 0, 0, 0]
        gravity = make_component("Gravity")
        gravity.config["gravity_direction"] = "down"
        scene.components = [collision, gravity]
        scene.placed_objects = [
            PlacedObject(
                instance_id="runner_1",
                object_def_id="runner_def",
                x=0,
                y=0,
                instance_behaviors=[
                    Behavior(
                        trigger="on_frame",
                        actions=[
                            BehaviorAction(
                                action_type="four_way_movement_collide",
                                collision_layer_id="collision_main",
                                player_width=32,
                                player_height=32,
                            )
                        ],
                    ),
                    Behavior(
                        trigger="on_button_pressed",
                        button="cross",
                        actions=[
                            BehaviorAction(
                                action_type="jump",
                                jump_strength=5,
                                jump_max_count=1,
                                jump_collision_layer_id="collision_main",
                                jump_player_width=32,
                                jump_player_height=32,
                            )
                        ],
                    ),
                ],
            )
        ]

        project.object_defs = [runner]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("obj_runner_1_jump_count = 0", scene_lua)
        self.assertIn("obj_runner_1_jump_max = 1", scene_lua)
        self.assertIn("obj_runner_1_jump_button_held = false", scene_lua)
        self.assertIn("if obj_runner_1_jump_count < 1 then", scene_lua)

    def test_instance_behaviors_seed_from_definition_and_override_shared_graph(self):
        shared = Behavior(
            trigger="on_scene_start",
            actions=[BehaviorAction(action_type="destroy_object", object_def_id="enemy_def")],
        )
        object_def = ObjectDefinition(id="enemy_def", name="Enemy", behaviors=[shared])
        placed = PlacedObject(instance_id="enemy_a", object_def_id="enemy_def")

        self.assertEqual(effective_placed_behaviors(placed, object_def)[0].trigger, "on_scene_start")
        self.assertTrue(seed_instance_behaviors_from_definition(placed, object_def))
        self.assertEqual(len(placed.instance_behaviors), 1)
        self.assertIsNot(placed.instance_behaviors[0], shared)

        placed.instance_behaviors[0].trigger = "on_timer"
        self.assertEqual(object_def.behaviors[0].trigger, "on_scene_start")
        self.assertEqual(effective_placed_behaviors(placed, object_def)[0].trigger, "on_timer")
        self.assertFalse(seed_instance_behaviors_from_definition(placed, object_def))

    def test_export_emits_animation_backed_3d_actor_state_and_sprite_frames(self):
        project = _project_with_registry()

        runner = ObjectDefinition(
            id="runner_def",
            name="Runner",
            width=32,
            height=48,
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_idle"}],
            ani_loop=True,
            ani_play_on_spawn=True,
        )
        project.object_defs = [runner]
        project.animation_exports = [
            AnimationExport(
                id="ani_idle",
                name="Idle",
                spritesheet_path="idle.png",
                frame_count=4,
                frame_width=32,
                frame_height=48,
                sheet_width=64,
                sheet_height=96,
                fps=12,
            )
        ]

        scene = Scene(name="3D Animation")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.map_data.spawn_x = 0
        scene.map_data.spawn_y = 0
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [
            PlacedObject(
                instance_id="runner_3d",
                object_def_id="runner_def",
                is_3d=True,
                grid_x=0,
                grid_y=0,
                offset_x=0.5,
                offset_y=0.5,
                scale=1.25,
            )
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("RayCast3D.clearSprites()", scene_lua)
        self.assertIn('RayCast3D.addSprite(32, 32, ((ani_sheets["ani_idle"] and ani_sheets["ani_idle"][1]) or nil), 1.25, 0.0, false)', scene_lua)
        self.assertIn('obj_runner_3d_ani_slot_name = "idle"', scene_lua)
        self.assertIn("RayCast3D.setSpriteFrame(1, _sheet, _sx, _sy, _sw, _sh)", scene_lua)
        self.assertIn('local _actor = actor3d_sync_entry("runner_3d")', scene_lua)
        self.assertIn('RayCast3D.moveObject("runner_3d", _actor.x, _actor.y)', scene_lua)
        self.assertIn("RayCast3D.setSpriteScale(1, _actor.scale)", scene_lua)

    def test_export_routes_3d_actor_behaviors_through_canonical_object_state(self):
        project = _project_with_registry()

        guard = ObjectDefinition(
            id="guard_def",
            name="Guard",
            width=32,
            height=48,
            behavior_type="Animation",
            ani_slots=[
                {"name": "idle", "ani_file_id": "ani_idle"},
                {"name": "alert", "ani_file_id": "ani_alert"},
            ],
            behaviors=[
                Behavior(
                    trigger="on_frame",
                    actions=[BehaviorAction(action_type="move_by", offset_x=4, offset_y=-2)],
                ),
                Behavior(
                    trigger="on_timer",
                    frame_count=12,
                    actions=[BehaviorAction(action_type="hide_object")],
                ),
                Behavior(
                    trigger="on_signal",
                    bool_var="alarm",
                    actions=[BehaviorAction(action_type="show_object")],
                ),
                Behavior(
                    trigger="on_3d_interact",
                    actions=[BehaviorAction(action_type="play_anim", ani_slot_name="alert")],
                ),
            ],
        )
        project.object_defs = [guard]
        project.animation_exports = [
            AnimationExport(
                id="ani_idle",
                name="Idle",
                spritesheet_path="idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                fps=12,
            ),
            AnimationExport(
                id="ani_alert",
                name="Alert",
                spritesheet_path="alert.png",
                frame_count=2,
                frame_width=32,
                frame_height=48,
                sheet_width=64,
                sheet_height=48,
                fps=12,
            ),
        ]

        scene = Scene(name="3D Guard")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [
            PlacedObject(instance_id="guard_1", object_def_id="guard_def", is_3d=True, grid_x=0, grid_y=0)
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("obj_guard_1_x = obj_guard_1_x + 4", scene_lua)
        self.assertIn("obj_guard_1_y = obj_guard_1_y + -2", scene_lua)
        self.assertIn("if signal_fired(\"alarm\") then", scene_lua)
        self.assertIn("obj_guard_1_visible = false", scene_lua)
        self.assertIn("obj_guard_1_visible = true", scene_lua)
        self.assertIn('_obj_dispatch["guard_1"] = function()', scene_lua)
        self.assertIn('obj_guard_1_ani_id = _new_id', scene_lua)
        self.assertIn('RayCast3D.setSpriteVisible(1, _actor.visible)', scene_lua)

    def test_export_skips_unsupported_3d_objects_with_explicit_comment(self):
        project = _project_with_registry()

        panel = ObjectDefinition(
            id="panel_def",
            name="Panel",
            behavior_type="GUI_Panel",
            gui_width=120,
            gui_height=40,
        )
        project.object_defs = [panel]

        scene = Scene(name="Unsupported 3D")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [
            PlacedObject(instance_id="panel_3d", object_def_id="panel_def", is_3d=True, grid_x=0, grid_y=0)
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("-- skipped 3D object panel_3d: GUI_Panel objects cannot render as 3D billboards", scene_lua)
        self.assertNotIn('RayCast3D.registerObject("panel_3d"', scene_lua)

    def test_export_3d_scene_keeps_supported_runtime_knobs_and_ignores_deferred_ones(self):
        project = _project_with_registry()

        scene = Scene(name="3D Config")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        rcfg = make_component("Raycast3DConfig")
        rcfg.config["movement_mode"] = "grid"
        rcfg.config["control_profile"] = "grid_strafe"
        rcfg.config["interact_distance"] = 96
        rcfg.config["render_view_size"] = 72
        rcfg.config["grid_step_duration"] = 0.45
        rcfg.config["rail_path_name"] = "patrol_route"
        rcfg.config["camera_pitch_enabled"] = True
        scene.components = [rcfg]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("RayCast3D.setViewsize(72)", scene_lua)
        self.assertNotIn("patrol_route", scene_lua)
        self.assertNotIn("camera_pitch_enabled", scene_lua)
        self.assertNotIn("turn_duration", scene_lua)

    def test_object_definition_round_trips_3d_actor_config(self):
        obj = ObjectDefinition(
            id="wolf_def",
            name="Wolf",
            is_3d_actor=True,
            actor_faction="enemy",
            actor_max_health=75,
            actor_move_speed=1.5,
            actor_radius=18.0,
            actor_sight_range=224.0,
            actor_attack_range=56.0,
            actor_patrol_path="route_main",
            actor_start_state="patrol",
        )

        loaded = ObjectDefinition.from_dict(obj.to_dict())

        self.assertTrue(loaded.is_3d_actor)
        self.assertEqual(loaded.actor_faction, "enemy")
        self.assertEqual(loaded.actor_max_health, 75)
        self.assertEqual(loaded.actor_move_speed, 1.5)
        self.assertEqual(loaded.actor_radius, 18.0)
        self.assertEqual(loaded.actor_sight_range, 224.0)
        self.assertEqual(loaded.actor_attack_range, 56.0)
        self.assertEqual(loaded.actor_patrol_path, "route_main")
        self.assertEqual(loaded.actor_start_state, "patrol")

    def test_placed_object_round_trips_actor_patrol_path_id(self):
        placed = PlacedObject(
            instance_id="wolf_1",
            object_def_id="wolf_def",
            is_3d=True,
            grid_x=1,
            grid_y=2,
            actor_patrol_path_id="path_route_main",
        )

        loaded = PlacedObject.from_dict(placed.to_dict())

        self.assertEqual(loaded.actor_patrol_path_id, "path_route_main")

    def test_export_emits_3d_actor_registry_helpers_and_per_instance_patrol_binding(self):
        project = _project_with_registry()

        wolf = ObjectDefinition(
            id="wolf_def",
            name="Wolf",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_wolf_idle"}],
            is_3d_actor=True,
            actor_faction="enemy",
            actor_max_health=90,
            actor_move_speed=1.5,
            actor_radius=20.0,
            actor_sight_range=256.0,
            actor_attack_range=64.0,
            actor_patrol_path="legacy_route",
            actor_start_state="patrol",
        )
        project.object_defs = [wolf]
        project.animation_exports = [
            AnimationExport(
                id="ani_wolf_idle",
                name="Wolf Idle",
                spritesheet_path="wolf_idle.png",
                frame_count=2,
                frame_width=32,
                frame_height=48,
                sheet_width=64,
                sheet_height=48,
                frames_per_sheet=2,
                fps=10,
            )
        ]

        scene = Scene(name="3D Wolf Patrol")
        scene.scene_type = "3d"
        scene.map_data.width = 3
        scene.map_data.height = 3
        scene.map_data.cells = [0] * 9
        path = make_component("Path")
        path.id = "path_route_main"
        path.config["path_name"] = "route_main"
        path.config["points"] = [
            {"x": 32, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 96, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
        ]
        scene.components = [make_component("Raycast3DConfig"), path]
        scene.placed_objects = [
            PlacedObject(
                instance_id="wolf_1",
                object_def_id="wolf_def",
                is_3d=True,
                grid_x=0,
                grid_y=0,
                actor_patrol_path_id="path_route_main",
            )
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("local _actors3d = {}", scene_lua)
        self.assertIn("local function actor3d_can_see_player(id, max_range)", scene_lua)
        self.assertIn('actor3d_register("wolf_1", "wolf_def", "obj_wolf_1", 1, {x=obj_wolf_1_x, y=obj_wolf_1_y', scene_lua)
        self.assertIn('state="patrol"', scene_lua)
        self.assertIn('faction="enemy"', scene_lua)
        self.assertIn('patrol_path="route_main"', scene_lua)
        self.assertIn('actor3d_start_patrol("wolf_1", "route_main", 1.5, true)', scene_lua)
        self.assertIn('scene_paths["route_main"]', scene_lua)
        self.assertNotIn("legacy_route", scene_lua)

    def test_export_keeps_patrol_binding_stable_when_path_is_renamed(self):
        project = _project_with_registry()

        wolf = ObjectDefinition(
            id="wolf_def",
            name="Wolf",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_wolf_idle"}],
            is_3d_actor=True,
            actor_move_speed=1.25,
        )
        project.object_defs = [wolf]
        project.animation_exports = [
            AnimationExport(
                id="ani_wolf_idle",
                name="Wolf Idle",
                spritesheet_path="wolf_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=10,
            )
        ]

        scene = Scene(name="3D Renamed Path")
        scene.scene_type = "3d"
        scene.map_data.width = 4
        scene.map_data.height = 4
        scene.map_data.cells = [0] * 16
        path = make_component("Path")
        path.id = "path_rename"
        path.config["path_name"] = "renamed_route"
        path.config["points"] = [
            {"x": 32, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 96, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
        ]
        scene.components = [make_component("Raycast3DConfig"), path]
        scene.placed_objects = [
            PlacedObject(
                instance_id="wolf_1",
                object_def_id="wolf_def",
                is_3d=True,
                grid_x=0,
                grid_y=0,
                actor_patrol_path_id="path_rename",
            )
        ]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn('scene_paths["renamed_route"]', scene_lua)
        self.assertIn('actor3d_start_patrol("wolf_1", "renamed_route", 1.25, true)', scene_lua)

    def test_export_falls_back_to_object_definition_patrol_when_no_instance_path_is_set(self):
        project = _project_with_registry()

        wolf = ObjectDefinition(
            id="wolf_def",
            name="Wolf",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_wolf_idle"}],
            is_3d_actor=True,
            actor_move_speed=1.5,
            actor_patrol_path="route_main",
        )
        project.object_defs = [wolf]
        project.animation_exports = [
            AnimationExport(
                id="ani_wolf_idle",
                name="Wolf Idle",
                spritesheet_path="wolf_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=10,
            )
        ]

        scene = Scene(name="3D Legacy Patrol")
        scene.scene_type = "3d"
        scene.map_data.width = 3
        scene.map_data.height = 3
        scene.map_data.cells = [0] * 9
        path = make_component("Path")
        path.config["path_name"] = "route_main"
        path.config["points"] = [
            {"x": 32, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 96, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
        ]
        scene.components = [make_component("Raycast3DConfig"), path]
        scene.placed_objects = [
            PlacedObject(instance_id="wolf_1", object_def_id="wolf_def", is_3d=True, grid_x=0, grid_y=0)
        ]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn('actor3d_start_patrol("wolf_1", "route_main", 1.5, true)', scene_lua)

    def test_export_skips_blocked_or_out_of_bounds_3d_path_points(self):
        project = _project_with_registry()

        wolf = ObjectDefinition(
            id="wolf_def",
            name="Wolf",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_wolf_idle"}],
            is_3d_actor=True,
            actor_move_speed=1.0,
        )
        project.object_defs = [wolf]
        project.animation_exports = [
            AnimationExport(
                id="ani_wolf_idle",
                name="Wolf Idle",
                spritesheet_path="wolf_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=10,
            )
        ]

        scene = Scene(name="3D Invalid Path")
        scene.scene_type = "3d"
        scene.map_data.width = 4
        scene.map_data.height = 4
        scene.map_data.cells = [
            0, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
        ]
        path = make_component("Path")
        path.id = "path_invalid"
        path.config["path_name"] = "route_main"
        path.config["points"] = [
            {"x": 32, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 96, "y": 96, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 288, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 160, "y": 32, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
        ]
        scene.components = [make_component("Raycast3DConfig"), path]
        scene.placed_objects = [
            PlacedObject(
                instance_id="wolf_1",
                object_def_id="wolf_def",
                is_3d=True,
                grid_x=0,
                grid_y=0,
                actor_patrol_path_id="path_invalid",
            )
        ]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn('scene_paths["route_main"]', scene_lua)
        self.assertIn("{x=160, y=32}", scene_lua)
        self.assertNotIn("{x=96, y=96}", scene_lua)
        self.assertNotIn("{x=288, y=32}", scene_lua)

    def test_export_uses_3d_actor_nodes_without_reusing_2d_path_runtime_calls(self):
        project = _project_with_registry()

        guard = ObjectDefinition(
            id="guard_def",
            name="Guard",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_guard_idle"}],
            behaviors=[
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(action_type="actor3d_set_state", actor_3d_state="alert"),
                        BehaviorAction(action_type="actor3d_start_patrol", path_name="route_main", path_speed=2.5, path_loop=True),
                        BehaviorAction(action_type="actor3d_face_player"),
                        BehaviorAction(action_type="actor3d_get_distance_to_player", var_name="player_dist"),
                        BehaviorAction(
                            action_type="if_actor3d_player_in_sight",
                            actor_3d_query_range=192.0,
                            true_actions=[BehaviorAction(action_type="actor3d_set_angle", actor_3d_angle=90.0)],
                        ),
                    ],
                )
            ],
        )
        project.object_defs = [guard]
        project.animation_exports = [
            AnimationExport(
                id="ani_guard_idle",
                name="Guard Idle",
                spritesheet_path="guard_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=12,
            )
        ]

        scene = Scene(name="3D Guard Brain")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [
            PlacedObject(instance_id="guard_1", object_def_id="guard_def", is_3d=True, grid_x=0, grid_y=0)
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn('local _actor3d_id = actor3d_id_from_var("obj_guard_1")', scene_lua)
        self.assertIn('actor3d_set_state(_actor3d_id, "alert")', scene_lua)
        self.assertIn('actor3d_start_patrol(_actor3d_id, "route_main", 2.5, true)', scene_lua)
        self.assertIn('actor3d_face_player(_actor3d_id)', scene_lua)
        self.assertIn('player_dist = actor3d_distance_to_player(_actor3d_id)', scene_lua)
        self.assertIn('if actor3d_can_see_player(_actor3d_id, 192.0) then _actor3d_ok = true end', scene_lua)
        self.assertNotIn('path_start("obj_guard_1"', scene_lua)

    def test_export_does_not_inject_3d_actor_runtime_into_2d_scenes(self):
        project = _project_with_registry()

        mover = ObjectDefinition(
            id="mover_def",
            name="Mover",
            behaviors=[
                Behavior(
                    trigger="on_scene_start",
                    actions=[BehaviorAction(action_type="follow_path", object_def_id="mover_def", path_name="route_main", path_speed=1.0)],
                )
            ],
        )
        project.object_defs = [mover]

        scene = Scene(name="2D Path Scene")
        path = make_component("Path")
        path.config["path_name"] = "route_main"
        path.config["points"] = [
            {"x": 0, "y": 0, "cx1": 0, "cy1": 0, "cx2": 0, "cy2": 0},
            {"x": 32, "y": 0, "cx1": 32, "cy1": 0, "cx2": 32, "cy2": 0},
        ]
        scene.components = [path]
        scene.placed_objects = [PlacedObject(instance_id="mover_1", object_def_id="mover_def", x=0, y=0)]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn('path_start("obj_mover_1", "route_main", 1.0, false)', scene_lua)
        self.assertNotIn("local _actors3d = {}", scene_lua)
        self.assertNotIn("actor3d_start_patrol(", scene_lua)

    def test_export_rejects_camera_defs_from_3d_actor_registry(self):
        project = _project_with_registry()

        camera = ObjectDefinition(
            id="camera_def",
            name="Scene Camera",
            behavior_type="Camera",
        )
        project.object_defs = [camera]

        scene = Scene(name="3D Camera Reject")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [
            PlacedObject(instance_id="camera_3d", object_def_id="camera_def", is_3d=True, grid_x=0, grid_y=0)
        ]
        project.scenes = [scene]

        files = export_lpp(project)
        scene_lua = files["scenes/scene_001.lua"]

        self.assertIn("-- skipped 3D object camera_3d: Camera objects cannot render as 3D billboards", scene_lua)
        self.assertNotIn('actor3d_register("camera_3d"', scene_lua)

    def test_export_emits_raycast3d_primitive_helpers_and_runtime_tick_order(self):
        project = _project_with_registry()

        guard = ObjectDefinition(
            id="guard_def",
            name="Guard",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_guard_idle"}],
            is_3d_actor=True,
        )
        project.object_defs = [guard]
        project.animation_exports = [
            AnimationExport(
                id="ani_guard_idle",
                name="Guard Idle",
                spritesheet_path="guard_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=12,
            )
        ]

        scene = Scene(name="3D Primitive Helpers")
        scene.scene_type = "3d"
        scene.map_data.width = 4
        scene.map_data.height = 4
        scene.map_data.cells = [0] * 16
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [PlacedObject(instance_id="guard_1", object_def_id="guard_def", is_3d=True, grid_x=1, grid_y=1)]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn("local function actor3d_kill(id, death_state)", scene_lua)
        self.assertIn("local function actor3d_set_alive(id, alive)", scene_lua)
        self.assertIn("local function actor3d_set_blocking(id, blocking)", scene_lua)
        self.assertIn("local function actor3d_set_interactable(id, interactable)", scene_lua)
        self.assertIn("local function actor3d_tick_runtime()", scene_lua)
        self.assertIn("local function ray3d_trace(wx, wy, angle, max_range, opts)", scene_lua)
        self.assertIn("local function ray3d_hitscan_player(max_range, opts)", scene_lua)
        self.assertIn("local function nav3d_find_path(start_wx, start_wy, goal_wx, goal_wy, opts)", scene_lua)
        self.assertIn("local function nav3d_follow_to(id, goal_wx, goal_wy, speed, opts)", scene_lua)
        self.assertIn("interactable=obj_guard_1_interactable", scene_lua)
        self.assertIn("actor3d_tick_runtime()", scene_lua)
        self.assertIn("nav3d_update_followers()", scene_lua)

    def test_export_supports_actor3d_lifecycle_nodes_without_touching_2d_nodes(self):
        project = _project_with_registry()

        guard = ObjectDefinition(
            id="guard_def",
            name="Guard",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_guard_idle"}],
            behaviors=[
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(action_type="actor3d_set_patrol_enabled", actor_3d_patrol_enabled=False),
                        BehaviorAction(action_type="actor3d_set_alive", actor_3d_alive=False),
                        BehaviorAction(action_type="actor3d_kill", actor_3d_state="corpse"),
                        BehaviorAction(action_type="actor3d_set_blocking", actor_3d_blocking=False),
                        BehaviorAction(action_type="actor3d_set_interactable", actor_3d_interactable=False),
                        BehaviorAction(
                            action_type="if_actor3d_alive",
                            true_actions=[BehaviorAction(action_type="actor3d_set_state", actor_3d_state="alert")],
                            false_actions=[BehaviorAction(action_type="actor3d_set_state", actor_3d_state="dead")],
                        ),
                    ],
                )
            ],
        )
        project.object_defs = [guard]
        project.animation_exports = [
            AnimationExport(
                id="ani_guard_idle",
                name="Guard Idle",
                spritesheet_path="guard_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=12,
            )
        ]

        scene = Scene(name="3D Lifecycle Nodes")
        scene.scene_type = "3d"
        scene.map_data.width = 2
        scene.map_data.height = 2
        scene.map_data.cells = [0, 0, 0, 0]
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [PlacedObject(instance_id="guard_1", object_def_id="guard_def", is_3d=True, grid_x=0, grid_y=0)]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn('actor3d_set_patrol_enabled(_actor3d_id, false)', scene_lua)
        self.assertIn('actor3d_set_alive(_actor3d_id, false)', scene_lua)
        self.assertIn('actor3d_kill(_actor3d_id, "corpse")', scene_lua)
        self.assertIn('actor3d_set_blocking(_actor3d_id, false)', scene_lua)
        self.assertIn('actor3d_set_interactable(_actor3d_id, false)', scene_lua)
        self.assertIn('if actor3d_is_alive(_actor3d_id) then _actor3d_ok = true end', scene_lua)
        self.assertNotIn('path_start("obj_guard_1"', scene_lua)

    def test_export_does_not_inject_new_raycast3d_primitives_into_2d_scenes(self):
        project = _project_with_registry()

        mover = ObjectDefinition(id="mover_def", name="Mover")
        project.object_defs = [mover]

        scene = Scene(name="2D No 3D Primitives")
        scene.placed_objects = [PlacedObject(instance_id="mover_1", object_def_id="mover_def", x=32, y=32)]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertNotIn("local function ray3d_trace(", scene_lua)
        self.assertNotIn("local function nav3d_find_path(", scene_lua)
        self.assertNotIn("local function actor3d_kill(", scene_lua)

    def test_builtin_reference_pack_can_call_raycast3d_primitives(self):
        project = _project_with_registry()

        actor = ObjectDefinition(
            id="guard_def",
            name="Guard",
            behavior_type="Animation",
            ani_slots=[{"name": "idle", "ani_file_id": "ani_guard_idle"}],
            behaviors=[
                Behavior(
                    trigger="on_frame",
                    actions=[
                        BehaviorAction(
                            action_type="ray3d_reference_hitscan_kill",
                            plugin_data={
                                "ray3d_reference_hitscan_kill": {
                                    "max_range": 256.0,
                                    "ignore_nonblocking": True,
                                    "death_state": "dead",
                                }
                            },
                        )
                    ],
                )
            ],
        )
        project.object_defs = [actor]
        project.animation_exports = [
            AnimationExport(
                id="ani_guard_idle",
                name="Guard Idle",
                spritesheet_path="guard_idle.png",
                frame_count=1,
                frame_width=32,
                frame_height=48,
                sheet_width=32,
                sheet_height=48,
                frames_per_sheet=1,
                fps=12,
            )
        ]

        scene = Scene(name="3D Reference Plugin")
        scene.scene_type = "3d"
        scene.map_data.width = 3
        scene.map_data.height = 3
        scene.map_data.cells = [0] * 9
        scene.components = [make_component("Raycast3DConfig")]
        scene.placed_objects = [PlacedObject(instance_id="guard_1", object_def_id="guard_def", is_3d=True, grid_x=1, grid_y=1)]
        project.scenes = [scene]

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn("ray3d_hitscan(256.0, {ignore_nonblocking = true})", scene_lua)
        self.assertIn('actor3d_kill(_hit.actor_id, "dead")', scene_lua)


    def test_paperdoll_mouth_config_migrates_legacy_alt_image_and_preserves_alias(self):
        doll = PaperDollAsset.from_dict(
            {
                "id": "doll_legacy",
                "name": "Legacy Puppet",
                "root_layers": [],
                "blink": {"node_hook_mode": "supplement"},
                "mouth": {
                    "layer_id": "mouth_layer",
                    "alt_image_id": "img_mouth_legacy",
                    "cycle_speed": 0.2,
                    "node_hook_mode": "replace",
                },
                "idle_breathing": {"node_hook_mode": "supplement"},
                "macros": [],
            }
        )

        self.assertEqual(doll.mouth.image_ids, ["img_mouth_legacy"])
        self.assertEqual(doll.mouth.alt_image_id, "img_mouth_legacy")
        self.assertEqual(doll.blink.node_hook_mode, "supplement")
        self.assertEqual(doll.mouth.node_hook_mode, "replace")
        self.assertEqual(doll.idle_breathing.node_hook_mode, "supplement")

        doll.mouth.image_ids = ["img_mouth_1", "img_mouth_2"]
        doll.mouth.alt_image_id = None
        saved = doll.to_dict()
        self.assertEqual(saved["mouth"]["image_ids"], ["img_mouth_1", "img_mouth_2"])
        self.assertEqual(saved["mouth"]["alt_image_id"], "img_mouth_1")

    def test_export_paperdoll_emits_ordered_mouth_images_and_hook_modes(self):
        project, _doll = _paperdoll_project_fixture()

        files = export_lpp(project)
        index_lua = files["index.lua"]

        self.assertIn('images      = {"mouth_1.png", "mouth_2.png", "mouth_3.png"}', index_lua)
        self.assertIn('hook_mode    = "supplement"', index_lua)
        self.assertIn('hook_mode   = "replace"', index_lua)
        self.assertIn('hook_mode       = "supplement"', index_lua)
        self.assertIn('images["mouth_1.png"] = Graphics.loadImage("app0:/assets/images/mouth_1.png")', index_lua)
        self.assertIn('images["mouth_2.png"] = Graphics.loadImage("app0:/assets/images/mouth_2.png")', index_lua)
        self.assertIn('images["mouth_3.png"] = Graphics.loadImage("app0:/assets/images/mouth_3.png")', index_lua)
        self.assertIn("local talk_images = def.mouth.images or {}", index_lua)
        self.assertIn("if blink_hook_mode ~= 'builtin' then", index_lua)
        self.assertIn("if ml and talk_hook_mode ~= 'replace' then", index_lua)
        self.assertIn("if idle_hook_mode ~= 'builtin' and next_cycle > prev_cycle then", index_lua)

    def test_export_paperdoll_dispatches_new_hook_triggers_and_keeps_vn_cycle_sound(self):
        project, _doll = _paperdoll_project_fixture()

        scene_lua = export_lpp(project)["scenes/scene_001.lua"]

        self.assertIn("if obj_puppet_1_pdoll and obj_puppet_1_pdoll.event_blink then", scene_lua)
        self.assertIn('emit_signal("blink_evt")', scene_lua)
        self.assertIn("if obj_puppet_1_pdoll and obj_puppet_1_pdoll.event_talk_step then", scene_lua)
        self.assertIn('emit_signal("talk_evt")', scene_lua)
        self.assertIn("if obj_puppet_1_pdoll and obj_puppet_1_pdoll.event_idle_cycle then", scene_lua)
        self.assertIn('emit_signal("idle_evt")', scene_lua)
        self.assertIn('if obj_puppet_1_pdoll.event_talk_step then', scene_lua)
        self.assertIn('local _ds = audio_tracks["dialog_tick.wav"]', scene_lua)
        self.assertNotIn("talk_open and not _prev_open", scene_lua)

    def test_windows_export_builds_bundle_and_patches_bootstrap_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = _write_fake_love_runtime(root)
            project = _windows_export_project(root / "project_2d")

            result = _build_windows_export_bundle(
                project,
                root / "export_2d",
                runtime_dir=runtime_dir,
                keep_intermediates=True,
            )

            self.assertTrue(result["final_exe"].exists())
            self.assertTrue((result["export_root"] / "love.dll").exists())
            self.assertTrue((result["export_root"] / "license.txt").exists())
            self.assertTrue((result["export_root"] / "readme.txt").exists())

            index_lua = (result["build_dir"] / "index.lua").read_text(encoding="utf-8")
            main_lua = (result["build_dir"] / "main.lua").read_text(encoding="utf-8")
            conf_lua = (result["build_dir"] / "conf.lua").read_text(encoding="utf-8")
            engine_lua = (result["build_dir"] / "engine.lua").read_text(encoding="utf-8")

            self.assertIn("require('lib.controls')", index_lua)
            self.assertIn("assert(love.filesystem.load('scenes/scene_001.lua'))()", index_lua)
            self.assertIn("function main_game_loop()", index_lua)
            self.assertIn("table.insert(package.loaders or package.searchers, 1, function(name)", main_lua)
            self.assertIn('t.identity = "WPRE00001"', conf_lua)
            self.assertIn("function Controls.readLeftAnalog()", engine_lua)
            self.assertIn("function Controls.readRightAnalog()", engine_lua)
            self.assertIn("function Keyboard.start(title, text, max_length, keyboard_type, keyboard_mode, keyboard_option)", engine_lua)
            self.assertIn("function System.openFile(path, mode)", engine_lua)
            self.assertIn("function System.getTitleID()", engine_lua)
            self.assertNotIn("function RayCast3D.renderScene", engine_lua)

            with zipfile.ZipFile(result["love_file"]) as archive:
                names = set(archive.namelist())

            self.assertIn("engine.lua", names)
            self.assertIn("main.lua", names)
            self.assertIn("conf.lua", names)
            self.assertIn("index.lua", names)
            self.assertIn("lib/controls.lua", names)
            self.assertIn("scenes/scene_001.lua", names)

    def test_windows_export_copies_real_raycast_runtime_and_rewrites_loader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = _write_fake_love_runtime(root)
            project = _windows_export_project(root / "project_3d", scene_type="3d")

            result = _build_windows_export_bundle(
                project,
                root / "export_3d",
                runtime_dir=runtime_dir,
                keep_intermediates=True,
            )

            index_lua = (result["build_dir"] / "index.lua").read_text(encoding="utf-8")
            engine_lua = (result["build_dir"] / "engine.lua").read_text(encoding="utf-8")
            raycast_lua = (result["build_dir"] / "files" / "raycast3d.lua").read_text(encoding="utf-8")

            self.assertIn("assert(love.filesystem.load('files/raycast3d.lua'))()", index_lua)
            self.assertTrue((result["build_dir"] / "files" / "raycast3d.lua").exists())
            self.assertIn("function RayCast3D.renderScene", raycast_lua)
            self.assertNotIn("function RayCast3D.renderScene", engine_lua)

            with zipfile.ZipFile(result["love_file"]) as archive:
                names = set(archive.namelist())

            self.assertIn("files/raycast3d.lua", names)

    def test_windows_export_preserves_save_and_storage_paths_for_shim_translation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = _write_fake_love_runtime(root)
            project = _windows_export_project(
                root / "project_storage",
                include_save=True,
                include_storage=True,
            )

            result = _build_windows_export_bundle(
                project,
                root / "export_storage",
                runtime_dir=runtime_dir,
                keep_intermediates=True,
            )

            index_lua = (result["build_dir"] / "index.lua").read_text(encoding="utf-8")
            save_lua = (result["build_dir"] / "lib" / "save.lua").read_text(encoding="utf-8")
            storage_lua = (result["build_dir"] / "lib" / "builtin_storage.lua").read_text(encoding="utf-8")
            engine_lua = (result["build_dir"] / "engine.lua").read_text(encoding="utf-8")

            self.assertIn("require('lib.save')", index_lua)
            self.assertIn("require('lib.builtin_storage')", index_lua)
            self.assertIn('local _SAVE_BASE = "ux0:data/WPRE00001"', save_lua)
            self.assertIn('return "ux0:data/" .. tostring(System.getTitleID() or "APP") .. "/storage/"', storage_lua)
            self.assertIn("function System.setMessage(text, unused_allow_cancel, buttons)", engine_lua)
            self.assertIn("function System.wait(ms)", engine_lua)
            self.assertIn("coroutine.yield()", engine_lua)
            self.assertIn("function love.textinput(text)", engine_lua)
            self.assertIn('if text:match("^ux0:data/") then', engine_lua)
            self.assertIn("love.filesystem.getSaveDirectory()", engine_lua)


if __name__ == "__main__":
    unittest.main()

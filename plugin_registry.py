from __future__ import annotations

import copy
import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import models


_BASE_COMPONENT_TYPES = list(models.COMPONENT_TYPES)
_BASE_COMPONENT_DEFAULTS = copy.deepcopy(models.COMPONENT_DEFAULTS)
_BUILTIN_PLUGIN_PREFIX = "builtin_"
_BUILTIN_PACKS_ROOT = Path(__file__).resolve().parent / "builtin_packs"

_UI_BASES: dict[str, dict[str, Any]] = {}


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _clone_nested_mapping(source: dict[str, Any]) -> dict[str, Any]:
    return {k: _deepcopy(v) for k, v in source.items()}


def _clone_nested_sequence(source: dict[str, list[Any]]) -> dict[str, list[Any]]:
    return {k: list(v) for k, v in source.items()}


def _required_str(raw: dict[str, Any], key: str, *, context: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"{context} is missing '{key}'")
    return value


def _normalize_editor_tool(component_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Component '{component_type}' editor_tools entries must be dicts")

    kind = str(raw.get("kind", "")).strip()
    if kind == "grid_map":
        mode = str(raw.get("mode", "")).strip()
        if mode not in {"binary", "scalar"}:
            raise ValueError(
                f"Component '{component_type}' grid_map editor tool must use mode 'binary' or 'scalar'"
            )
        tool = {
            "kind": "grid_map",
            "data_key": _required_str(raw, "data_key", context=f"Component '{component_type}' grid_map editor tool"),
            "width_key": _required_str(raw, "width_key", context=f"Component '{component_type}' grid_map editor tool"),
            "height_key": _required_str(raw, "height_key", context=f"Component '{component_type}' grid_map editor tool"),
            "cell_size_key": _required_str(raw, "cell_size_key", context=f"Component '{component_type}' grid_map editor tool"),
            "mode": mode,
            "default_cell": raw.get("default_cell", 0),
            "overlay_color": str(raw.get("overlay_color", "") or "").strip(),
            "overlay_color_key": str(raw.get("overlay_color_key", "") or "").strip(),
            "opacity_key": str(raw.get("opacity_key", "") or "").strip(),
            "paint_label": str(raw.get("paint_label", "Paint")),
            "erase_label": str(raw.get("erase_label", "Erase")),
        }
        if mode == "binary":
            tool["active_value"] = raw.get("active_value", 1)
        else:
            tool["paint_value_key"] = _required_str(raw, "paint_value_key", context=f"Component '{component_type}' grid_map editor tool")
            tool["brush_mode_key"] = _required_str(raw, "brush_mode_key", context=f"Component '{component_type}' grid_map editor tool")
            tool["brush_radius_key"] = _required_str(raw, "brush_radius_key", context=f"Component '{component_type}' grid_map editor tool")
            tool["brush_strength_key"] = _required_str(raw, "brush_strength_key", context=f"Component '{component_type}' grid_map editor tool")
        return tool

    if kind == "path":
        return {
            "kind": "path",
            "points_key": _required_str(raw, "points_key", context=f"Component '{component_type}' path editor tool"),
            "closed_key": _required_str(raw, "closed_key", context=f"Component '{component_type}' path editor tool"),
            "name_key": _required_str(raw, "name_key", context=f"Component '{component_type}' path editor tool"),
            "draw_label": str(raw.get("draw_label", "Draw Path")),
            "supports_bezier": bool(raw.get("supports_bezier", False)),
        }

    raise ValueError(f"Component '{component_type}' uses unknown editor tool kind '{kind}'")


def normalize_component_editor_tools(component_type: str, editor_tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in editor_tools or []:
        normalized.append(_normalize_editor_tool(component_type, raw))
    return normalized


def _behavior_widget_type(field_type: str) -> str:
    mapping = {
        "bool": "check",
        "int": "spin",
        "float": "dspin",
        "str": "text",
        "combo": "combo",
        "color": "text",
        "audio": "audio",
        "image": "image",
        "object": "object",
        "scene_num": "scene_num",
        "signal": "signal",
        "collision_layer": "collision_layer",
    }
    return mapping.get(field_type, "text")


def normalize_behavior_fields(field_schema: list[dict[str, Any]] | None) -> list[tuple[str, str, str, dict[str, Any]]]:
    normalized: list[tuple[str, str, str, dict[str, Any]]] = []
    for raw in field_schema or []:
        if not isinstance(raw, dict):
            continue
        field_type = str(raw.get("type", "str"))
        if field_type == "section":
            continue
        key = str(raw.get("key", "")).strip()
        if not key:
            continue
        label = str(raw.get("label", key))
        extra: dict[str, Any] = {}
        if "min" in raw:
            extra["min"] = raw["min"]
        if "max" in raw:
            extra["max"] = raw["max"]
        if "step" in raw:
            extra["step"] = raw["step"]
        if "options" in raw:
            extra["options"] = list(raw.get("options", []))
        if "placeholder" in raw:
            extra["placeholder"] = raw["placeholder"]
        if "default" in raw:
            extra["default"] = _deepcopy(raw["default"])
        normalized.append((key, label, _behavior_widget_type(field_type), extra))
    return normalized


@dataclass
class PluginRegistry:
    project_folder: str = ""
    errors: list[tuple[str, str]] = field(default_factory=list)
    component_descriptors: dict[str, dict[str, Any]] = field(default_factory=dict)
    trigger_descriptors: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_descriptors: dict[str, dict[str, Any]] = field(default_factory=dict)
    component_plugin_ids: dict[str, str] = field(default_factory=dict)
    component_order: list[str] = field(default_factory=list)

    def add_error(self, plugin_id: str, message: str) -> None:
        self.errors.append((plugin_id, message))

    def get_component_descriptor(self, component_type: str) -> dict[str, Any] | None:
        return self.component_descriptors.get(component_type)

    def get_trigger_descriptor(self, trigger_key: str) -> dict[str, Any] | None:
        return self.trigger_descriptors.get(trigger_key)

    def get_action_descriptor(self, action_key: str) -> dict[str, Any] | None:
        return self.action_descriptors.get(action_key)

    def get_plugin_id_for_component_type(self, component_type: str) -> str | None:
        return self.component_plugin_ids.get(component_type)

    def get_component_label(self, component_type: str) -> str:
        desc = self.get_component_descriptor(component_type)
        return str(desc.get("label", component_type)) if desc else component_type

    def get_component_color(self, component_type: str) -> str | None:
        desc = self.get_component_descriptor(component_type)
        if not desc:
            return None
        color = str(desc.get("color", "")).strip()
        return color or None

    def is_component_singleton(self, component_type: str) -> bool:
        desc = self.get_component_descriptor(component_type)
        return bool(desc and desc.get("singleton"))

    def iter_scene_plugin_components(self, scene) -> list[tuple[Any, dict[str, Any], str]]:
        items: list[tuple[Any, dict[str, Any], str]] = []
        for component in getattr(scene, "components", []):
            desc = self.get_component_descriptor(component.component_type)
            if not desc:
                continue
            plugin_id = self.component_plugin_ids.get(component.component_type, "")
            items.append((component, desc, plugin_id))
        return items

    def collect_project_component_libs(self, project) -> dict[str, str]:
        libs: dict[str, str] = {}
        for scene in getattr(project, "scenes", []):
            for _component, desc, plugin_id in self.iter_scene_plugin_components(scene):
                lua_lib = desc.get("lua_lib")
                if plugin_id and isinstance(lua_lib, str) and lua_lib.strip():
                    libs.setdefault(plugin_id, lua_lib)
        return libs


def make_empty_registry(project_folder: str = "") -> PluginRegistry:
    return PluginRegistry(project_folder=project_folder)


def clear_plugins() -> None:
    models.COMPONENT_TYPES[:] = list(_BASE_COMPONENT_TYPES)
    models.COMPONENT_DEFAULTS.clear()
    models.COMPONENT_DEFAULTS.update(copy.deepcopy(_BASE_COMPONENT_DEFAULTS))


def _load_plugin_module(plugin_id: str, plugin_path: Path) -> ModuleType:
    module_name = f"minigame_plugin_{plugin_id}_{abs(hash(str(plugin_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_component_descriptor(plugin_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    component_type = str(raw.get("type", "")).strip()
    if not component_type:
        raise ValueError("Component descriptor is missing 'type'")
    defaults = raw.get("defaults", {})
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise ValueError(f"Component '{component_type}' defaults must be a dict")
    fields = raw.get("fields", [])
    if fields is None:
        fields = []
    if not isinstance(fields, list):
        raise ValueError(f"Component '{component_type}' fields must be a list")
    editor_tools = raw.get("editor_tools", [])
    if editor_tools is None:
        editor_tools = []
    if not isinstance(editor_tools, list):
        raise ValueError(f"Component '{component_type}' editor_tools must be a list")
    return {
        "plugin_id": plugin_id,
        "type": component_type,
        "label": str(raw.get("label", component_type)),
        "color": str(raw.get("color", "#7a7890")),
        "singleton": bool(raw.get("singleton", False)),
        "defaults": copy.deepcopy(defaults),
        "fields": copy.deepcopy(fields),
        "editor_tools": normalize_component_editor_tools(component_type, editor_tools),
        "lua_lib": raw.get("lua_lib"),
        "lua_scene_init": raw.get("lua_scene_init"),
        "lua_scene_loop": raw.get("lua_scene_loop"),
        "lua_scene_draw": raw.get("lua_scene_draw"),
    }


def _normalize_trigger_descriptor(plugin_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    key = str(raw.get("key", "")).strip()
    if not key:
        raise ValueError("Trigger descriptor is missing 'key'")
    lua_condition = raw.get("lua_condition")
    if not callable(lua_condition):
        raise ValueError(f"Trigger '{key}' is missing callable lua_condition")
    fields = raw.get("fields", [])
    if fields is None:
        fields = []
    if not isinstance(fields, list):
        raise ValueError(f"Trigger '{key}' fields must be a list")
    return {
        "plugin_id": plugin_id,
        "key": key,
        "label": str(raw.get("label", key)),
        "category": str(raw.get("category", "Plugin")),
        "fields": copy.deepcopy(fields),
        "normalized_fields": normalize_behavior_fields(fields),
        "lua_condition": lua_condition,
    }


def _normalize_action_descriptor(plugin_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    key = str(raw.get("key", "")).strip()
    if not key:
        raise ValueError("Action descriptor is missing 'key'")
    lua_export = raw.get("lua_export")
    if not callable(lua_export):
        raise ValueError(f"Action '{key}' is missing callable lua_export")
    fields = raw.get("fields", [])
    if fields is None:
        fields = []
    if not isinstance(fields, list):
        raise ValueError(f"Action '{key}' fields must be a list")
    return {
        "plugin_id": plugin_id,
        "key": key,
        "label": str(raw.get("label", key)),
        "category": str(raw.get("category", "Plugin")),
        "fields": copy.deepcopy(fields),
        "normalized_fields": normalize_behavior_fields(fields),
        "has_branches": bool(raw.get("has_branches", False)),
        "has_loop_body": bool(raw.get("has_loop_body", False)),
        "lua_export": lua_export,
    }


def _register_plugin_descriptors(
    registry: PluginRegistry,
    plugin_id: str,
    plugin: dict[str, Any],
    *,
    builtin: bool,
) -> None:
    if builtin and not plugin_id.startswith(_BUILTIN_PLUGIN_PREFIX):
        raise ValueError(f"Built-in pack id '{plugin_id}' must start with '{_BUILTIN_PLUGIN_PREFIX}'")
    if not builtin and plugin_id.startswith(_BUILTIN_PLUGIN_PREFIX):
        raise ValueError(f"Project plugin id '{plugin_id}' uses reserved '{_BUILTIN_PLUGIN_PREFIX}' prefix")

    for raw_component in plugin.get("components", []) or []:
        desc = _normalize_component_descriptor(plugin_id, raw_component)
        component_type = desc["type"]
        if component_type in registry.component_descriptors or component_type in _BASE_COMPONENT_DEFAULTS:
            raise ValueError(f"Duplicate component type '{component_type}'")
        registry.component_descriptors[component_type] = desc
        registry.component_plugin_ids[component_type] = plugin_id
        registry.component_order.append(component_type)
        models.COMPONENT_TYPES.append(component_type)
        models.COMPONENT_DEFAULTS[component_type] = copy.deepcopy(desc["defaults"])

    for raw_trigger in plugin.get("triggers", []) or []:
        desc = _normalize_trigger_descriptor(plugin_id, raw_trigger)
        key = desc["key"]
        if key in registry.trigger_descriptors:
            raise ValueError(f"Duplicate trigger key '{key}'")
        registry.trigger_descriptors[key] = desc

    for raw_action in plugin.get("actions", []) or []:
        desc = _normalize_action_descriptor(plugin_id, raw_action)
        key = desc["key"]
        if key in registry.action_descriptors:
            raise ValueError(f"Duplicate action key '{key}'")
        registry.action_descriptors[key] = desc


def _scan_plugin_root(registry: PluginRegistry, plugins_root: Path, *, builtin: bool) -> None:
    if not plugins_root.exists() or not plugins_root.is_dir():
        return

    for entry in sorted(plugins_root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir():
            continue
        plugin_path = entry / "plugin.py"
        if not plugin_path.is_file():
            continue
        plugin_id = entry.name
        try:
            module = _load_plugin_module(plugin_id, plugin_path)
            plugin = getattr(module, "PLUGIN", None)
            if not isinstance(plugin, dict):
                raise ValueError("PLUGIN must be a dict")
            _register_plugin_descriptors(registry, plugin_id, plugin, builtin=builtin)
        except Exception as exc:
            registry.add_error(plugin_id, str(exc))


def scan_plugins(project_folder: str | Path | None) -> PluginRegistry:
    folder = Path(project_folder) if project_folder else None
    clear_plugins()
    registry = make_empty_registry(str(folder) if folder else "")
    _scan_plugin_root(registry, _BUILTIN_PACKS_ROOT, builtin=True)
    if folder is not None:
        _scan_plugin_root(registry, folder / "plugins", builtin=False)

    return registry


def _snapshot_behavior_node_graph(module) -> dict[str, Any]:
    return {
        "OBJECT_TRIGGERS": dict(module.OBJECT_TRIGGERS),
        "TRIGGER_CATEGORIES": _clone_nested_sequence(module.TRIGGER_CATEGORIES),
        "TRIGGER_FIELDS": _clone_nested_mapping(module.TRIGGER_FIELDS),
        "ACTION_PALETTE": _clone_nested_sequence(module.ACTION_PALETTE),
        "ACTION_FIELDS": _clone_nested_mapping(module.ACTION_FIELDS),
        "ACTION_NAMES": dict(module.ACTION_NAMES),
        "BRANCH_TYPES": set(module.BRANCH_TYPES),
        "LOOP_TYPES": set(module.LOOP_TYPES),
    }


def _restore_behavior_node_graph(module, base: dict[str, Any]) -> None:
    module.OBJECT_TRIGGERS.clear()
    module.OBJECT_TRIGGERS.update(base["OBJECT_TRIGGERS"])
    module.TRIGGER_CATEGORIES.clear()
    module.TRIGGER_CATEGORIES.update(_clone_nested_sequence(base["TRIGGER_CATEGORIES"]))
    module.TRIGGER_FIELDS.clear()
    module.TRIGGER_FIELDS.update(_clone_nested_mapping(base["TRIGGER_FIELDS"]))
    module.ACTION_PALETTE.clear()
    module.ACTION_PALETTE.update(_clone_nested_sequence(base["ACTION_PALETTE"]))
    module.ACTION_FIELDS.clear()
    module.ACTION_FIELDS.update(_clone_nested_mapping(base["ACTION_FIELDS"]))
    module.ACTION_NAMES.clear()
    module.ACTION_NAMES.update(base["ACTION_NAMES"])
    module.BRANCH_TYPES.clear()
    module.BRANCH_TYPES.update(set(base["BRANCH_TYPES"]))
    module.LOOP_TYPES.clear()
    module.LOOP_TYPES.update(set(base["LOOP_TYPES"]))


def _apply_behavior_runtime(module, registry: PluginRegistry) -> None:
    for key, desc in registry.trigger_descriptors.items():
        module.OBJECT_TRIGGERS[key] = desc["label"]
        module.TRIGGER_CATEGORIES.setdefault(desc["category"], []).append(key)
        module.TRIGGER_FIELDS[key] = copy.deepcopy(desc["normalized_fields"])

    for key, desc in registry.action_descriptors.items():
        module.ACTION_PALETTE.setdefault(desc["category"], []).append((key, desc["label"]))
        module.ACTION_FIELDS[key] = copy.deepcopy(desc["normalized_fields"])
        module.ACTION_NAMES[key] = desc["label"]
        if desc.get("has_branches"):
            module.BRANCH_TYPES.add(key)
        if desc.get("has_loop_body"):
            module.LOOP_TYPES.add(key)


def _snapshot_scene_options(module) -> dict[str, Any]:
    return {
        "COMPONENT_COLORS": dict(module.COMPONENT_COLORS),
    }


def _restore_scene_options(module, base: dict[str, Any]) -> None:
    module.COMPONENT_COLORS.clear()
    module.COMPONENT_COLORS.update(base["COMPONENT_COLORS"])


def _apply_scene_options_runtime(module, registry: PluginRegistry) -> None:
    for component_type, desc in registry.component_descriptors.items():
        color = str(desc.get("color", "")).strip()
        if color:
            module.COMPONENT_COLORS[component_type] = color


def sync_runtime_modules(registry: PluginRegistry | None) -> None:
    runtime_registry = registry or make_empty_registry()
    module = importlib.import_module("behavior_node_graph")
    if "behavior_node_graph" not in _UI_BASES:
        _UI_BASES["behavior_node_graph"] = _snapshot_behavior_node_graph(module)
    _restore_behavior_node_graph(module, _UI_BASES["behavior_node_graph"])
    _apply_behavior_runtime(module, runtime_registry)

    scene_module = importlib.import_module("tab_scene_options")
    if "tab_scene_options" not in _UI_BASES:
        _UI_BASES["tab_scene_options"] = _snapshot_scene_options(scene_module)
    _restore_scene_options(scene_module, _UI_BASES["tab_scene_options"])
    _apply_scene_options_runtime(scene_module, runtime_registry)


def build_auto_panel(
    field_schema: list[dict[str, Any]] | None,
    component,
    project,
    changed_callback: Callable[[], None] | None = None,
    field_changed_callback: Callable[[str], None] | None = None,
):
    from PySide6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QLabel,
        QLineEdit,
        QComboBox,
        QCheckBox,
        QSpinBox,
        QDoubleSpinBox,
        QPushButton,
        QHBoxLayout,
        QColorDialog,
    )

    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    style = """
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background: #1e1e28;
            color: #e8e6f0;
            border: 1px solid #2e2e42;
            border-radius: 4px;
            padding: 5px 8px;
        }
        QCheckBox {
            color: #e8e6f0;
            spacing: 6px;
        }
        QPushButton {
            background: #26263a;
            color: #e8e6f0;
            border: 1px solid #2e2e42;
            border-radius: 4px;
            padding: 5px 10px;
        }
    """

    def emit_changed() -> None:
        if changed_callback:
            changed_callback()

    def emit_field_changed(field_key: str) -> None:
        if field_changed_callback:
            field_changed_callback(field_key)

    for raw in field_schema or []:
        if not isinstance(raw, dict):
            continue
        field_type = str(raw.get("type", "str"))
        if field_type == "section":
            label = QLabel(str(raw.get("label", "")))
            label.setStyleSheet("color: #7a7890; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; padding-top: 6px;")
            layout.addWidget(label)
            continue

        key = str(raw.get("key", "")).strip()
        if not key:
            continue
        current = component.config.get(key, _deepcopy(raw.get("default")))

        label = QLabel(str(raw.get("label", key)))
        label.setStyleSheet("color: #7a7890; font-size: 11px;")
        layout.addWidget(label)

        if field_type == "bool":
            widget = QCheckBox()
            widget.setStyleSheet(style)
            widget.setChecked(bool(current))

            def _update_bool(value: bool, field_key: str = key) -> None:
                component.config[field_key] = bool(value)
                emit_field_changed(field_key)
                emit_changed()

            widget.toggled.connect(_update_bool)
            layout.addWidget(widget)
            continue

        if field_type == "int":
            widget = QSpinBox()
            widget.setStyleSheet(style)
            widget.setRange(int(raw.get("min", -999999)), int(raw.get("max", 999999)))
            widget.setValue(int(current if current is not None else raw.get("default", 0)))

            def _update_int(value: int, field_key: str = key) -> None:
                component.config[field_key] = int(value)
                emit_field_changed(field_key)
                emit_changed()

            widget.valueChanged.connect(_update_int)
            layout.addWidget(widget)
            continue

        if field_type == "float":
            widget = QDoubleSpinBox()
            widget.setStyleSheet(style)
            widget.setRange(float(raw.get("min", -999999.0)), float(raw.get("max", 999999.0)))
            widget.setSingleStep(float(raw.get("step", 0.1)))
            widget.setDecimals(3)
            widget.setValue(float(current if current is not None else raw.get("default", 0.0)))

            def _update_float(value: float, field_key: str = key) -> None:
                component.config[field_key] = float(value)
                emit_field_changed(field_key)
                emit_changed()

            widget.valueChanged.connect(_update_float)
            layout.addWidget(widget)
            continue

        if field_type == "combo":
            widget = QComboBox()
            widget.setStyleSheet(style)
            options = [str(opt) for opt in raw.get("options", [])]
            for option in options:
                widget.addItem(option)
            current_text = str(current if current is not None else raw.get("default", ""))
            if current_text in options:
                widget.setCurrentText(current_text)
            elif options:
                widget.setCurrentIndex(0)
                component.config[key] = widget.currentText()

            def _update_combo(value: str, field_key: str = key) -> None:
                component.config[field_key] = value
                emit_field_changed(field_key)
                emit_changed()

            widget.currentTextChanged.connect(_update_combo)
            layout.addWidget(widget)
            continue

        if field_type == "color":
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            edit = QLineEdit(str(current or raw.get("default", "#ffffff")))
            edit.setStyleSheet(style)
            button = QPushButton("Pick")
            button.setStyleSheet(style)

            def _update_color_text(value: str, field_key: str = key) -> None:
                component.config[field_key] = value
                emit_field_changed(field_key)
                emit_changed()

            def _pick_color(field_key: str = key, line_edit: QLineEdit = edit) -> None:
                chosen = QColorDialog.getColor()
                if chosen.isValid():
                    line_edit.setText(chosen.name())
                    component.config[field_key] = chosen.name()
                    emit_field_changed(field_key)
                    emit_changed()

            edit.textChanged.connect(_update_color_text)
            button.clicked.connect(_pick_color)
            row_layout.addWidget(edit, stretch=1)
            row_layout.addWidget(button)
            layout.addWidget(row)
            continue

        edit = QLineEdit("" if current is None else str(current))
        edit.setStyleSheet(style)
        placeholder = str(raw.get("placeholder", "")).strip()
        if placeholder:
            edit.setPlaceholderText(placeholder)

        def _update_text(value: str, field_key: str = key) -> None:
            component.config[field_key] = value
            emit_field_changed(field_key)
            emit_changed()

        edit.textChanged.connect(_update_text)
        layout.addWidget(edit)

    layout.addStretch(1)
    return panel

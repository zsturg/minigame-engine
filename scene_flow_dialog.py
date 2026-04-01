# -*- coding: utf-8 -*-
"""
scene_flow_dialog.py
Non-modal dialog that visualises all scenes as draggable nodes on a zoomable/
pannable canvas, with directed edges representing go_to_scene connections.
"""

import copy
import math
import tempfile
import shutil
import zipfile
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsTextItem,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton, QMenu,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QLinearGradient,
    QPainterPath, QPainterPathStroker,
)

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────

MIN_ZOOM = 0.20
MAX_ZOOM = 3.0
GRID_SIZE = 20

NODE_W        = 200
THUMB_H       = 112
HEADER_H      = 28
FOOTER_H      = 20
PORT_RADIUS   = 6
PORT_SPACING  = 20

MENU_STYLE = """
    QMenu { background: #1e1e28; color: #e8e6f0; border: 1px solid #2e2e42;
            font: 11px 'Segoe UI'; }
    QMenu::item { padding: 5px 24px 5px 14px; }
    QMenu::item:selected { background: #4a4860; color: #ffffff; }
    QMenu::separator { height: 1px; background: #2e2e42; margin: 3px 0; }
"""

COLOR_BG          = QColor("#0f0f12")
COLOR_NODE_BODY   = QColor("#16161c")
COLOR_NODE_BORDER = QColor("#3b6ea8")
COLOR_NODE_SEL    = QColor("#fcd34d")
COLOR_HEADER_TOP  = QColor("#1e3a5f")
COLOR_HEADER_BOT  = QColor("#172d4a")
COLOR_PORT_IN     = QColor("#4a4860")
COLOR_PORT_OUT    = QColor("#f59e0b")
COLOR_PORT_HOVER  = QColor("#ffffff")
COLOR_EDGE        = QColor("#f59e0b")
COLOR_TITLE       = QColor("#f0eeff")
COLOR_DIM         = QColor("#7a7890")
COLOR_PORT_BORDER = QColor("#1a1a24")

COMPONENT_PILL_COLORS = {
    "VNDialogBox":     "#e879f9",
    "Music":           "#fb923c",
    "Grid":            "#4ade80",
    "Raycast3DConfig": "#38bdf8",
    "Path":            "#06b6d4",
}
COMPONENT_PILL_DEFAULT = "#4a4860"


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _snap(v: float, grid: int = GRID_SIZE) -> float:
    return round(v / grid) * grid


def _bezier(p1: QPointF, p2: QPointF) -> QPainterPath:
    path = QPainterPath(p1)
    dx = max(abs(p2.x() - p1.x()) * 0.55, 60)
    path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
    return path


# ─────────────────────────────────────────────────────────────
#  DATA PARSING
# ─────────────────────────────────────────────────────────────

def collect_flow_connections(project) -> list:
    """Return a list of connection record dicts for every go_to_scene / tile exit."""
    records = []

    def walk_actions(actions, path_prefix, scene_idx, behavior_idx,
                     object_instance_id, obj_behavior_idx):
        for i, action in enumerate(actions):
            current_path = path_prefix + [i]
            if getattr(action, "action_type", None) == "go_to_scene":
                target = getattr(action, "target_scene", None)
                if target is not None and 0 <= target < len(project.scenes):
                    records.append({
                        "from_scene_idx":      scene_idx,
                        "to_scene_idx":        target,
                        "label":               f"→ {target + 1}",
                        "owner":               "object_behavior" if object_instance_id else "scene_behavior",
                        "scene_idx":           scene_idx,
                        "behavior_idx":        behavior_idx,
                        "object_instance_id":  object_instance_id,
                        "obj_behavior_idx":    obj_behavior_idx,
                        "action_path":         current_path,
                        "tile_key":            None,
                    })
            # Recurse
            ta = getattr(action, "true_actions",  None) or []
            fa = getattr(action, "false_actions", None) or []
            sa = getattr(action, "sub_actions",   None) or []
            if ta:
                walk_actions(ta, current_path + ["true_actions"],  scene_idx, behavior_idx,
                             object_instance_id, obj_behavior_idx)
            if fa:
                walk_actions(fa, current_path + ["false_actions"], scene_idx, behavior_idx,
                             object_instance_id, obj_behavior_idx)
            if sa:
                walk_actions(sa, current_path + ["sub_actions"],   scene_idx, behavior_idx,
                             object_instance_id, obj_behavior_idx)

    for scene_idx, scene in enumerate(project.scenes):
        # 1. Scene-level behaviors
        for bi, behavior in enumerate(getattr(scene, "behaviors", [])):
            walk_actions(behavior.actions, [], scene_idx, bi, None, None)

        # 2. Placed object instance behaviors
        for po in getattr(scene, "placed_objects", []):
            for obi, behavior in enumerate(getattr(po, "instance_behaviors", [])):
                walk_actions(behavior.actions, [], scene_idx, None,
                             po.instance_id, obi)

        # 3. Tile exits
        map_data = getattr(scene, "map_data", None)
        if map_data:
            for key, tile_meta in (getattr(map_data, "tile_meta", None) or {}).items():
                if getattr(tile_meta, "type", None) == "exit":
                    target = getattr(tile_meta, "target_scene", None)
                    if target is not None and 0 <= target < len(project.scenes):
                        records.append({
                            "from_scene_idx":      scene_idx,
                            "to_scene_idx":        target,
                            "label":               f"Exit {key}",
                            "owner":               "tile_exit",
                            "scene_idx":           scene_idx,
                            "behavior_idx":        None,
                            "object_instance_id":  None,
                            "obj_behavior_idx":    None,
                            "action_path":         [],
                            "tile_key":            key,
                        })
    return records


def resolve_action(behavior, path):
    """Walk an action_path list and return the target BehaviorAction."""
    actions = behavior.actions
    action = None
    i = 0
    while i < len(path):
        step = path[i]
        if isinstance(step, int):
            action = actions[step]
            i += 1
        else:
            branch_name = step
            branch_idx  = path[i + 1]
            actions = getattr(action, branch_name)
            action  = actions[branch_idx]
            i += 2
    return action


def apply_connection_change(project, record, new_to_scene_idx: int):
    """Write new_to_scene_idx back into the project data referenced by record."""
    scene = project.scenes[record["scene_idx"]]

    if record["tile_key"] is not None:
        tile = scene.map_data.tile_meta[record["tile_key"]]
        tile.target_scene = new_to_scene_idx
        return

    if record["object_instance_id"] is not None:
        po = next(p for p in scene.placed_objects
                  if p.instance_id == record["object_instance_id"])
        behavior = po.instance_behaviors[record["obj_behavior_idx"]]
    else:
        behavior = scene.behaviors[record["behavior_idx"]]

    action = resolve_action(behavior, record["action_path"])
    action.target_scene = new_to_scene_idx


# ─────────────────────────────────────────────────────────────
#  PORT ITEM  (unchanged from template, embedded here)
# ─────────────────────────────────────────────────────────────

class PortItem(QGraphicsEllipseItem):
    RADIUS = PORT_RADIUS

    def __init__(self, node, is_output: bool, port_id: str = "default", label: str = ""):
        r = self.RADIUS
        super().__init__(-r, -r, r * 2, r * 2, node)
        self.node       = node
        self.is_output  = is_output
        self.port_id    = port_id
        self.label      = label
        self.edges: list = []
        self._label_item = None
        self._update_color()
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setZValue(2)
        if label:
            self._label_item = QGraphicsTextItem(label, node)
            self._label_item.setDefaultTextColor(COLOR_DIM)
            self._label_item.setFont(QFont("Segoe UI", 8))
            self._label_item.setZValue(3)

    def _update_color(self):
        fill = COLOR_PORT_OUT if self.is_output else COLOR_PORT_IN
        self._normal_fill = fill
        self.setBrush(QBrush(fill))
        self.setPen(QPen(COLOR_PORT_BORDER, 1.5))

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(COLOR_PORT_HOVER))
        self.setScale(1.3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(self._normal_fill))
        self.setScale(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_output:
            views = self.scene().views()
            if views:
                views[0].start_edge_drag(self)
            event.accept()
        else:
            event.ignore()


# ─────────────────────────────────────────────────────────────
#  SCENE NODE
# ─────────────────────────────────────────────────────────────

class SceneNode(QGraphicsItem):

    def __init__(self, scene_idx: int, scene,
                 thumbnail,         # QPixmap | None
                 connections: list, # records where from_scene_idx == scene_idx
                 x: float = 0, y: float = 0):
        super().__init__()
        self.scene_idx   = scene_idx
        self._scene_data = scene
        self.thumbnail   = thumbnail
        self.connections = connections
        self._canvas_dialog = None  # set after construction

        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )

        # Build ports
        self.in_port = PortItem(self, is_output=False, port_id="in", label="")
        self.out_ports: list[PortItem] = []
        for i, rec in enumerate(connections):
            port = PortItem(self, is_output=True, port_id=f"out_{i}", label=rec["label"])
            self.out_ports.append(port)

        self._layout_ports()

    # ── port layout ──────────────────────────────────────────

    def _layout_ports(self):
        in_y = HEADER_H + THUMB_H // 2
        self.in_port.setPos(0, in_y)
        # label item for in_port (none needed)

        footer_top = HEADER_H + THUMB_H + FOOTER_H
        for i, port in enumerate(self.out_ports):
            y = footer_top + i * PORT_SPACING + PORT_SPACING // 2
            port.setPos(NODE_W, y)
            if port._label_item:
                lw = port._label_item.boundingRect().width()
                port._label_item.setPos(NODE_W - lw - PORT_RADIUS - 4,
                                        y - 9)

    def _total_height(self) -> int:
        return HEADER_H + THUMB_H + FOOTER_H + max(1, len(self.out_ports)) * PORT_SPACING

    def boundingRect(self):
        return QRectF(-2, -2, NODE_W + 4, self._total_height() + 4)

    # ── painting ─────────────────────────────────────────────

    def paint(self, painter, _option=None, _widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        selected = self.isSelected()
        w = NODE_W
        h = self._total_height()
        r = 8

        # Body background
        border_color = COLOR_NODE_SEL if selected else COLOR_NODE_BORDER
        painter.setBrush(QBrush(COLOR_NODE_BODY))
        painter.setPen(QPen(border_color, 2 if selected else 1.5))
        painter.drawRoundedRect(0, 0, w, h, r, r)

        # Header gradient
        grad = QLinearGradient(0, 0, 0, HEADER_H)
        grad.setColorAt(0, COLOR_HEADER_TOP)
        grad.setColorAt(1, COLOR_HEADER_BOT)
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        hp = QPainterPath()
        hp.addRoundedRect(0, 0, w, HEADER_H + r, r, r)
        clip = QPainterPath()
        clip.addRect(0, 0, w, HEADER_H)
        painter.drawPath(hp.intersected(clip))

        # Header text
        painter.setPen(QPen(COLOR_TITLE))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        scene_label = f"Scene {self.scene_idx + 1}"
        fm = painter.fontMetrics()
        label_w = fm.horizontalAdvance(scene_label)
        painter.drawText(8, 0, label_w + 4, HEADER_H, Qt.AlignVCenter, scene_label)

        name = getattr(self._scene_data, "name", "") or ""
        if name:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(COLOR_DIM))
            name_x = 8 + label_w + 6
            painter.drawText(name_x, 0, w - name_x - 6, HEADER_H,
                             Qt.AlignVCenter | Qt.TextSingleLine, name)

        # Thumbnail area
        thumb_rect_y = HEADER_H
        if self.thumbnail is not None:
            painter.drawPixmap(QRectF(0, thumb_rect_y, w, THUMB_H).toRect(), self.thumbnail)
        else:
            painter.setBrush(QBrush(QColor("#0a0a10")))
            painter.setPen(Qt.NoPen)
            painter.drawRect(0, thumb_rect_y, w, THUMB_H)
            painter.setFont(QFont("Segoe UI", 20, QFont.Bold))
            painter.setPen(QPen(COLOR_DIM))
            painter.drawText(0, thumb_rect_y, w, THUMB_H,
                             Qt.AlignCenter, f"Scene {self.scene_idx + 1}")

        # Separator line
        painter.setPen(QPen(QColor("#2e2e42"), 1))
        sep_y = HEADER_H + THUMB_H
        painter.drawLine(0, sep_y, w, sep_y)

        # Footer component pills
        components = getattr(self._scene_data, "components", []) or []
        seen_types = []
        for comp in components:
            ct = getattr(comp, "component_type", None) or ""
            if ct and ct not in seen_types:
                seen_types.append(ct)

        pill_x = 6
        pill_y = sep_y + 3
        pill_h = FOOTER_H - 6
        painter.setFont(QFont("Segoe UI", 6))
        for ct in seen_types:
            color_str = COMPONENT_PILL_COLORS.get(ct, COMPONENT_PILL_DEFAULT)
            pfm = painter.fontMetrics()
            pill_w = pfm.horizontalAdvance(ct) + 8
            if pill_x + pill_w > w - 4:
                break
            pill_color = QColor(color_str)
            bg = QColor(pill_color.red(), pill_color.green(), pill_color.blue(), 60)
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(pill_color, 1))
            painter.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, 3, 3)
            painter.setPen(pill_color)
            painter.drawText(pill_x, pill_y, pill_w, pill_h, Qt.AlignCenter, ct)
            pill_x += pill_w + 4

        # Selection highlight
        if selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(COLOR_NODE_SEL, 1.5))
            painter.drawRoundedRect(0, 0, w, h, r, r)

    # ── item change ──────────────────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                if getattr(view, "_snap_enabled", False):
                    value = QPointF(_snap(value.x()), _snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            for port in self.all_ports():
                for edge in port.edges:
                    edge.refresh()
        return super().itemChange(change, value)

    def all_ports(self):
        return [self.in_port] + self.out_ports

    # ── context menu ─────────────────────────────────────────

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLE)
        go_action     = menu.addAction(f"Go to Scene {self.scene_idx + 1}")
        menu.addSeparator()
        export_action = menu.addAction("Export Scene as VPK…")
        chosen = menu.exec(event.screenPos())
        if chosen == go_action and self._canvas_dialog:
            self._canvas_dialog.main_window.on_scene_selected(self.scene_idx)
        if chosen == export_action and self._canvas_dialog:
            self._canvas_dialog.export_single_scene(self.scene_idx)


# ─────────────────────────────────────────────────────────────
#  FLOW EDGE
# ─────────────────────────────────────────────────────────────

class FlowEdge(QGraphicsPathItem):

    def __init__(self, src: PortItem, dst: PortItem, record: dict, dialog: "SceneFlowDialog"):
        super().__init__()
        self.src    = src
        self.dst    = dst
        self.record = record
        self.dialog = dialog
        src.edges.append(self)
        dst.edges.append(self)
        self.setPen(QPen(COLOR_EDGE, 2))
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.refresh()

    def refresh(self):
        if self.src is not None and self.dst is not None:
            self.setPath(_bezier(self.src.scene_center(), self.dst.scene_center()))
        elif self.src is not None:
            self.setPath(QPainterPath(self.src.scene_center()))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)
        # Draw arrowhead at dst
        if self.dst is None:
            return
        p2 = self.dst.scene_center()
        path = self.path()
        if path.isEmpty():
            return
        # Approximate tangent near destination
        t_val = 0.95
        # Sample a point slightly before the end to get tangent direction
        p_near = path.pointAtPercent(t_val)
        dx = p2.x() - p_near.x()
        dy = p2.y() - p_near.y()
        length = math.hypot(dx, dy)
        if length < 0.001:
            return
        ux, uy = dx / length, dy / length
        arrow_size = 10
        perp_x, perp_y = -uy, ux
        tip   = p2
        base1 = QPointF(p2.x() - ux * arrow_size + perp_x * arrow_size * 0.5,
                        p2.y() - uy * arrow_size + perp_y * arrow_size * 0.5)
        base2 = QPointF(p2.x() - ux * arrow_size - perp_x * arrow_size * 0.5,
                        p2.y() - uy * arrow_size - perp_y * arrow_size * 0.5)
        arrow = QPainterPath()
        arrow.moveTo(tip); arrow.lineTo(base1); arrow.lineTo(base2); arrow.closeSubpath()
        painter.setBrush(QBrush(COLOR_EDGE))
        painter.setPen(Qt.NoPen)
        painter.drawPath(arrow)

    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(14)
        return s.createStroke(self.path())

    def hoverEnterEvent(self, event):
        self.setPen(QPen(COLOR_EDGE, 3.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(COLOR_EDGE, 2))
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLE)
        da = menu.addAction("✕  Delete Connection")
        if menu.exec(event.screenPos()) == da:
            self._delete_and_writeback()

    def _delete_and_writeback(self):
        apply_connection_change(self.dialog.project, self.record, new_to_scene_idx=0)
        self.dialog.main_window._mark_unsaved()
        self.detach()
        if self.scene():
            self.scene().removeItem(self)

    def detach(self):
        if self.src and self in self.src.edges:
            self.src.edges.remove(self)
        if self.dst and self in self.dst.edges:
            self.dst.edges.remove(self)


# ─────────────────────────────────────────────────────────────
#  SCENE FLOW CANVAS
# ─────────────────────────────────────────────────────────────

class SceneFlowCanvas(QGraphicsView):

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene()
        self._scene.setSceneRect(-4000, -4000, 8000, 8000)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setBackgroundBrush(QBrush(COLOR_BG))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet("border: none;")
        self.setFocusPolicy(Qt.StrongFocus)

        self._panning    = False
        self._pan_start  = QPointF()
        self._drag_source: PortItem | None     = None
        self._drag_edge: QGraphicsPathItem | None = None
        self._reroute_edge: FlowEdge | None    = None
        self._snap_enabled = False
        self._nodes: dict[int, SceneNode]      = {}
        self._canvas_dialog: "SceneFlowDialog | None" = None

        self._draw_grid()

    # ── grid ─────────────────────────────────────────────────

    def _draw_grid(self):
        minor = QPen(QColor("#16161e"), 1)
        major = QPen(QColor("#1e1e2a"), 1)
        step  = 40
        for x in range(-4000, 4001, step):
            self._scene.addLine(x, -4000, x, 4000, major if x % (step * 4) == 0 else minor)
        for y in range(-4000, 4001, step):
            self._scene.addLine(-4000, y, 4000, y, major if y % (step * 4) == 0 else minor)

    # ── rebuild ──────────────────────────────────────────────

    def rebuild(self, project, thumbnail_cache: dict, node_positions: dict):
        self._scene.clear()
        self._draw_grid()

        connections = collect_flow_connections(project)

        self._nodes = {}
        for idx, scene in enumerate(project.scenes):
            thumbnail = thumbnail_cache.get(idx)
            scene_connections = [c for c in connections if c["from_scene_idx"] == idx]
            scene_id = getattr(scene, "id", str(idx))
            if scene_id in node_positions:
                x, y = node_positions[scene_id]
            else:
                col = idx % 5
                row = idx // 5
                x = col * (NODE_W + 60)
                y = row * 320
            node = SceneNode(idx, scene, thumbnail, scene_connections, x, y)
            node._canvas_dialog = self._canvas_dialog
            self._scene.addItem(node)
            self._nodes[idx] = node

        for record in connections:
            from_node = self._nodes.get(record["from_scene_idx"])
            to_node   = self._nodes.get(record["to_scene_idx"])
            if from_node is None or to_node is None:
                continue
            src_port = None
            for i, c in enumerate(from_node.connections):
                if c is record:
                    src_port = from_node.out_ports[i]
                    break
            if src_port is None:
                continue
            dst_port = to_node.in_port
            edge = FlowEdge(src_port, dst_port, record, self._canvas_dialog)
            self._scene.addItem(edge)

    # ── edge drag (new edges from output ports) ───────────────

    def start_edge_drag(self, source: PortItem):
        self._drag_source = source
        self._drag_edge   = QGraphicsPathItem()
        self._drag_edge.setPen(QPen(COLOR_EDGE, 2, Qt.DashLine))
        self._drag_edge.setZValue(10)
        self._scene.addItem(self._drag_edge)

    # ── zoom ──────────────────────────────────────────────────

    def wheelEvent(self, event):
        cur    = self.transform().m11()
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new    = cur * factor
        if new < MIN_ZOOM:   factor = MIN_ZOOM / cur
        elif new > MAX_ZOOM: factor = MAX_ZOOM / cur
        self.scale(factor, factor)

    # ── mouse events ──────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning   = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            # Check if clicking near the dst end of an existing FlowEdge
            for item in self.items(event.pos()):
                if isinstance(item, FlowEdge) and item.dst is not None:
                    dst_screen = self.mapFromScene(item.dst.scene_center())
                    if (event.pos() - dst_screen).manhattanLength() < 16:
                        self._reroute_edge = item
                        if item in item.dst.edges:
                            item.dst.edges.remove(item)
                        item.dst = None
                        self._drag_edge   = item
                        self._drag_source = item.src
                        event.accept()
                        return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._drag_source is not None:
            self._drag_edge.setPath(
                _bezier(self._drag_source.scene_center(),
                        self.mapToScene(event.pos())))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        # Reroute of existing edge
        if self._reroute_edge is not None and event.button() == Qt.LeftButton:
            target_port = None
            for item in self.items(event.pos()):
                if isinstance(item, PortItem) and not item.is_output:
                    target_port = item
                    break
            edge = self._reroute_edge
            self._reroute_edge = None
            self._drag_source  = None
            self._drag_edge    = None
            if target_port and target_port.node is not edge.src.node:
                new_to_idx = target_port.node.scene_idx
                apply_connection_change(
                    self._canvas_dialog.project, edge.record, new_to_idx)
                self._canvas_dialog.main_window._mark_unsaved()
                edge.record["to_scene_idx"] = new_to_idx
                edge.dst = target_port
                target_port.edges.append(edge)
                edge.refresh()
                # Update label on src port
                edge.src.label = f"→ {new_to_idx + 1}"
                if edge.src._label_item:
                    edge.src._label_item.setPlainText(edge.src.label)
            else:
                # Cancelled — rebuild to restore consistency
                if self._canvas_dialog:
                    self._canvas_dialog._rebuild()
            event.accept()
            return

        # New edge from drag
        if self._drag_source is not None and event.button() == Qt.LeftButton:
            target = None
            for item in self.items(event.pos()):
                if isinstance(item, PortItem):
                    target = item
                    break
            # For new edges we just remove the temp drag — actual connections
            # are stored in the data model, not created on-the-fly here.
            self._scene.removeItem(self._drag_edge)
            self._drag_edge = self._drag_source = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None and not isinstance(item, QGraphicsPathItem):
            super().contextMenuEvent(event)
            return
        # Background right-click — nothing for now
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        menu.exec(event.globalPos())


# ─────────────────────────────────────────────────────────────
#  SINGLE-SCENE VPK EXPORT
# ─────────────────────────────────────────────────────────────

def export_single_scene_vpk(project, scene_idx: int, output_path: str):
    """
    Build a minimal stub project containing only scene_idx and its dependencies,
    then call the normal LPP exporter to produce a VPK at output_path.
    """
    from models import Project

    target_scene = project.scenes[scene_idx]

    # ── collect dependency IDs ────────────────────────────────
    ref_image_ids  = set()
    ref_audio_ids  = set()
    ref_font_ids   = set()
    ref_tileset_ids = set()
    ref_obj_ids    = set()
    ref_ani_ids    = set()
    ref_trans_ids  = set()
    ref_pd_ids     = set()

    def _scan_actions(actions):
        for a in actions:
            if getattr(a, "audio_id",      None): ref_audio_ids.add(a.audio_id)
            if getattr(a, "image_id",      None): ref_image_ids.add(a.image_id)
            if getattr(a, "object_def_id", None): ref_obj_ids.add(a.object_def_id)
            _scan_actions(getattr(a, "sub_actions",   None) or [])
            _scan_actions(getattr(a, "true_actions",  None) or [])
            _scan_actions(getattr(a, "false_actions", None) or [])

    def _scan_behaviors(behaviors):
        for b in behaviors:
            _scan_actions(b.actions)

    for po in getattr(target_scene, "placed_objects", []):
        if getattr(po, "object_def_id", None):
            ref_obj_ids.add(po.object_def_id)
        _scan_behaviors(getattr(po, "instance_behaviors", []))
    _scan_behaviors(getattr(target_scene, "behaviors", []))

    for comp in getattr(target_scene, "components", []):
        if getattr(comp, "image_id",            None): ref_image_ids.add(comp.image_id)
        if getattr(comp, "audio_id",            None): ref_audio_ids.add(comp.audio_id)
        if getattr(comp, "font_id",             None): ref_font_ids.add(comp.font_id)
        if getattr(comp, "tileset_id",          None): ref_tileset_ids.add(comp.tileset_id)
        if getattr(comp, "animation_export_id", None): ref_ani_ids.add(comp.animation_export_id)
        if getattr(comp, "transition_id",       None): ref_trans_ids.add(comp.transition_id)
        if getattr(comp, "paper_doll_id",       None): ref_pd_ids.add(comp.paper_doll_id)

    # ── build stub project ────────────────────────────────────
    stub = Project.new()
    stub_scene = copy.deepcopy(target_scene)

    # Patch go_to_scene references: keep 0 if it was scene_idx, zero others
    def _patch_actions(actions):
        for a in actions:
            if getattr(a, "action_type", None) == "go_to_scene":
                if getattr(a, "target_scene", None) == scene_idx:
                    a.target_scene = 0
                else:
                    a.target_scene = 0  # out-of-stub → also zero
            _patch_actions(getattr(a, "sub_actions",   None) or [])
            _patch_actions(getattr(a, "true_actions",  None) or [])
            _patch_actions(getattr(a, "false_actions", None) or [])

    def _patch_behaviors(behaviors):
        for b in behaviors:
            _patch_actions(b.actions)

    _patch_behaviors(getattr(stub_scene, "behaviors", []))
    for po in getattr(stub_scene, "placed_objects", []):
        _patch_behaviors(getattr(po, "instance_behaviors", []))

    map_data = getattr(stub_scene, "map_data", None)
    if map_data:
        for tile_meta in (getattr(map_data, "tile_meta", None) or {}).values():
            if getattr(tile_meta, "type", None) == "exit":
                tile_meta.target_scene = 0

    stub.scenes = [stub_scene]
    stub.images = [img for img in (getattr(project, "images", []) or [])
                   if getattr(img, "id", None) in ref_image_ids]
    stub.audio  = [a for a in (getattr(project, "audio",  []) or [])
                   if getattr(a, "id", None) in ref_audio_ids]
    stub.fonts  = [f for f in (getattr(project, "fonts",  []) or [])
                   if getattr(f, "id", None) in ref_font_ids]
    stub.tilesets = [t for t in (getattr(project, "tilesets", []) or [])
                     if getattr(t, "id", None) in ref_tileset_ids]
    stub.object_defs = [o for o in (getattr(project, "object_defs", []) or [])
                        if getattr(o, "id", None) in ref_obj_ids]

    if hasattr(stub, "animation_exports"):
        stub.animation_exports = [a for a in (getattr(project, "animation_exports", []) or [])
                                  if getattr(a, "id", None) in ref_ani_ids]
    if hasattr(stub, "transition_exports"):
        stub.transition_exports = [t for t in (getattr(project, "transition_exports", []) or [])
                                   if getattr(t, "id", None) in ref_trans_ids]
    if hasattr(stub, "paper_dolls"):
        stub.paper_dolls = [p for p in (getattr(project, "paper_dolls", []) or [])
                            if getattr(p, "id", None) in ref_pd_ids]

    stub.game_data = copy.deepcopy(getattr(project, "game_data", None))
    stub.title     = (getattr(project, "title", "") or "") + f" — Scene {scene_idx + 1} Test"
    stub.title_id  = getattr(project, "title_id", "TEST00001") or "TEST00001"
    stub.project_folder = getattr(project, "project_folder", None)

    # ── call the exporter ─────────────────────────────────────
    try:
        from lpp_exporter import export_lpp, bake_tile_chunks
    except ImportError:
        raise RuntimeError("lpp_exporter module not found.")

    from resource_path import resource_path
    base_path      = Path(resource_path("."))
    template_folder = base_path / "lpptemplate"

    with tempfile.TemporaryDirectory() as temp_dir:
        build_dir = Path(temp_dir)

        if template_folder.exists():
            shutil.copytree(template_folder, build_dir, dirs_exist_ok=True)

        try:
            bake_tile_chunks(stub, build_dir)
        except Exception:
            pass

        lua_files = export_lpp(stub, title_id=stub.title_id)
        for rel_path, content in lua_files.items():
            dest_abs = build_dir / rel_path
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_abs, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED) as zipf:
            for root, _, files in os.walk(build_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname   = file_path.relative_to(build_dir)
                    zipf.write(file_path, arcname)


# ─────────────────────────────────────────────────────────────
#  SCENE FLOW DIALOG
# ─────────────────────────────────────────────────────────────

class SceneFlowDialog(QDialog):

    def __init__(self, main_window, thumbnail_cache: dict):
        super().__init__(main_window, Qt.Window)  # non-modal separate window
        self.main_window     = main_window
        self.project         = main_window.project
        self.thumbnail_cache = thumbnail_cache
        self._node_positions: dict[str, tuple] = {}

        self.setWindowTitle("Scene Flow")
        self.setMinimumSize(900, 600)
        self.resize(1200, 750)

        self._build_ui()
        self._rebuild()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setFixedHeight(40)
        tb.setStyleSheet("background: #16161c; border-bottom: 1px solid #2e2e42;")
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(10, 0, 10, 0)
        tb_layout.setSpacing(8)

        btn_style = """
            QPushButton {
                background: #26263a; color: #e8e6f0;
                border: 1px solid #2e2e42; padding: 5px 14px;
                border-radius: 4px; font: 11px 'Segoe UI';
            }
            QPushButton:hover { background: #2e2e42; border-color: #4a4860; }
            QPushButton:pressed { background: #1e1e28; }
        """

        rebuild_btn = QPushButton("↺ Rebuild")
        rebuild_btn.setStyleSheet(btn_style)
        rebuild_btn.clicked.connect(self._rebuild)
        tb_layout.addWidget(rebuild_btn)

        auto_layout_btn = QPushButton("⊞ Auto Layout")
        auto_layout_btn.setStyleSheet(btn_style)
        auto_layout_btn.clicked.connect(self._auto_layout)
        tb_layout.addWidget(auto_layout_btn)

        tb_layout.addStretch()

        hint = QLabel(
            "Middle-drag to pan  •  Scroll to zoom  •  Drag port to reroute  •  Right-click for options"
        )
        hint.setStyleSheet("color: #4a4860; font: 10px 'Segoe UI';")
        tb_layout.addWidget(hint)

        layout.addWidget(tb)

        # Canvas
        self.canvas = SceneFlowCanvas()
        self.canvas._canvas_dialog = self
        layout.addWidget(self.canvas, stretch=1)

    # ── rebuild / layout ──────────────────────────────────────

    def _rebuild(self):
        # Save current node positions before clearing
        if hasattr(self.canvas, "_nodes") and self.canvas._nodes:
            for idx, node in self.canvas._nodes.items():
                if idx < len(self.project.scenes):
                    scene_id = getattr(self.project.scenes[idx], "id", str(idx))
                    self._node_positions[scene_id] = (node.pos().x(), node.pos().y())
        self.project = self.main_window.project
        self.canvas.rebuild(self.project, self.thumbnail_cache, self._node_positions)

    def _auto_layout(self):
        self._node_positions.clear()
        self._rebuild()

    # ── export ────────────────────────────────────────────────

    def export_single_scene(self, scene_idx: int):
        scene = self.project.scenes[scene_idx]
        name  = getattr(scene, "name", None) or f"Scene_{scene_idx + 1}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export Scene {scene_idx + 1} as VPK",
            f"{name}_test.vpk",
            "VPK Files (*.vpk)",
        )
        if not path:
            return
        try:
            export_single_scene_vpk(self.project, scene_idx, path)
            QMessageBox.information(self, "Export Complete", f"Exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

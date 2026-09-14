from __future__ import annotations

from html import escape

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from .constants import (
    EXPAND_YEAR_BUFFER,
    EXPAND_YEAR_RANGE,
    HEADER_MONTH_HEIGHT,
    HEADER_QUARTER_HEIGHT,
    HEADER_WEEK_HEIGHT,
    HEADER_YEAR_HEIGHT,
    INITIAL_YEAR_RANGE,
    TEXTBOX_MIN_HEIGHT,
    TEXTBOX_MIN_WIDTH,
    WEEKS_PER_YEAR,
)
from .items import (
    BoxItem,
    CircleItem,
    ConnectorItem,
    DeadlineItem,
    GridItem,
    LinkItem,
    MilestoneItem,
    TextboxItem,
)
from .layout import Layout
from .week_format import format_year_week


class DependencyEdgeItem(QGraphicsPathItem):
    """Selectable interaction surface for one model dependency."""

    def __init__(self, successor_id: str, predecessor_id: str) -> None:
        super().__init__()
        self.successor_id = successor_id
        self.predecessor_id = predecessor_id
        self._hovered = False
        self._dependency_hovered = False
        self.setData(1, "dependency_edge")
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(-499.0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def relationship_key(self) -> tuple[str, str]:
        return self.successor_id, self.predecessor_id

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect()

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        scene = self.scene()
        if scene is not None:
            scene.set_dependency_hover_edge(self.relationship_key)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        scene = self.scene()
        if scene is not None and self._dependency_hovered:
            scene.clear_dependency_hover()
        self.update()
        super().hoverLeaveEvent(event)

    def set_interaction_enabled(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
            if enabled
            else Qt.MouseButton.NoButton
        )
        self.setAcceptHoverEvents(enabled)
        if not enabled:
            self._hovered = False
            self._dependency_hovered = False
            self.setSelected(False)
            self.update()

    def set_dependency_hovered(self, hovered: bool) -> None:
        self._dependency_hovered = bool(hovered)
        self.update()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        # The aggregate dependency layer supplies the normal dashed rendering.
        if getattr(self.scene(), 'exporting', False):
            return
        if not self.isSelected() and not self._hovered and not self._dependency_hovered:
            return
        if self.isSelected():
            color, width, style = QColor("#00b1eb"), 2.8, Qt.PenStyle.SolidLine
        elif self._dependency_hovered:
            color, width, style = QColor("#00b1eb"), 2.6, Qt.PenStyle.SolidLine
        else:
            color, width, style = QColor("#7c3aed"), 2.2, Qt.PenStyle.DashLine
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())


class CanvasScene(QGraphicsScene):
    label_width_changed = pyqtSignal(float)
    status_message = pyqtSignal(str)

    def __init__(self, model, controller) -> None:
        super().__init__()
        self.model = model
        self.controller = controller
        self.layout = Layout(model)
        if self.controller and hasattr(self.controller, "set_layout"):
            self.controller.set_layout(self.layout)
        self.items_by_id = {}
        self._object_cache = {}
        self.related_ids: set[str] = set()
        self.dimmed_ids: set[str] = set()
        self._dependency_hover_object_id: str | None = None
        self._dependency_hover_predecessor_ids: set[str] = set()
        self._dependency_hover_successor_ids: set[str] = set()
        self._dependency_hover_edge_keys: set[tuple[str, str]] = set()
        self.selected_row_id: str | None = None
        self.selected_row_ids: set[str] = set()
        self.row_selection_anchor_id: str | None = None
        self.focused_row_id: str | None = None
        self.snap_weeks = True
        self.snap_rows = True
        self.edit_mode = True
        self.dark_mode = False
        self.show_current_week = True
        self.show_missing_scope = False
        self.show_textboxes = True
        self.connector_cache = {}
        self.header_year_height = HEADER_YEAR_HEIGHT
        self.header_quarter_height = HEADER_QUARTER_HEIGHT
        self.header_month_height = HEADER_MONTH_HEIGHT
        self.header_week_height = HEADER_WEEK_HEIGHT
        self.min_week = self.layout.origin_week - (WEEKS_PER_YEAR * INITIAL_YEAR_RANGE)
        self.max_week = self.layout.origin_week + (WEEKS_PER_YEAR * INITIAL_YEAR_RANGE)
        self.week_expand = WEEKS_PER_YEAR * EXPAND_YEAR_RANGE
        self.week_expand_buffer = WEEKS_PER_YEAR * EXPAND_YEAR_BUFFER

        self.grid_item = GridItem(self)
        self.addItem(self.grid_item)

        self.dependency_layer = QGraphicsPathItem()
        self.dependency_layer.setZValue(-500)
        self.dependency_layer.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.addItem(self.dependency_layer)
        self.dependency_items_by_key: dict[tuple[str, str], DependencyEdgeItem] = {}

        self.show_initiative_rollup = False
        self._initiative_items: list = []

        self.model.rows_changed.connect(self.rebuild_layout)
        self.model.objects_changed.connect(self.refresh_items)
        self.model.metadata_changed.connect(self.update_headers)

        self.rebuild_layout()
        self.refresh_items()

    def update_headers(self) -> None:
        self.grid_item.update()

    def update_risk_badges(self) -> None:
        for obj_id, item in self.items_by_id.items():
            if not isinstance(item, BoxItem):
                continue
            obj = self.model.objects.get(obj_id)
            if obj is None:
                continue
            rect = item.rect()
            item._update_risk_badge(
                obj,
                rect.width(),
                rect.height(),
                show_missing_scope=self.show_missing_scope,
            )

    def rebuild_layout(self) -> None:
        self.layout.rebuild(self.model)
        self.selected_row_ids = {
            row_id
            for row_id in self.selected_row_ids
            if row_id in self.layout.row_map and self.layout.row_map[row_id].kind == "deliverable"
        }
        if self.selected_row_id and self.selected_row_id not in self.layout.row_map:
            self.selected_row_id = None
        if self.selected_row_id is not None:
            row = self.layout.row_map.get(self.selected_row_id)
            if row is None:
                self.selected_row_id = None
            elif row.kind == "topic":
                self.selected_row_ids.clear()
            elif self.selected_row_id not in self.selected_row_ids:
                self.selected_row_id = None
        if self.selected_row_id is None and self.selected_row_ids:
            ordered = self.ordered_deliverable_ids(self.selected_row_ids)
            self.selected_row_id = ordered[0] if ordered else None
        if (
            self.row_selection_anchor_id
            and self.row_selection_anchor_id not in self.layout.row_map
        ):
            self.row_selection_anchor_id = None
        if self.row_selection_anchor_id is not None:
            anchor_row = self.layout.row_map.get(self.row_selection_anchor_id)
            if anchor_row is None or anchor_row.kind != "deliverable":
                self.row_selection_anchor_id = None
        if self.row_selection_anchor_id is None and self.selected_row_ids:
            ordered = self.ordered_deliverable_ids(self.selected_row_ids)
            self.row_selection_anchor_id = ordered[0] if ordered else None
        if self.focused_row_id and self.focused_row_id not in self.layout.row_map:
            self.focused_row_id = None
        self._update_scene_rect()
        self.grid_item.update()
        self.refresh_items(force_sync=True)

    def set_label_width(self, width: float) -> None:
        width = float(width)
        if width <= 0:
            return
        if abs(self.layout.label_width - width) < 0.5:
            return
        self.layout.label_width = width
        self._update_scene_rect()
        self.grid_item.update()
        self.refresh_items(force_sync=True)
        self.label_width_changed.emit(width)

    def _update_scene_rect(self) -> None:
        height = self.layout.header_height + self.layout.total_height
        min_y = 0.0
        max_y = height
        min_x = self.layout.week_left_x(self.min_week)
        max_x = self.layout.week_left_x(self.max_week) + self.layout.week_width
        for obj in self.model.objects.values():
            if not self.show_textboxes or obj.kind != "textbox" or obj.y is None:
                continue
            box_width = obj.width if obj.width is not None else TEXTBOX_MIN_WIDTH
            box_height = obj.height if obj.height is not None else TEXTBOX_MIN_HEIGHT
            if obj.x is not None:
                min_x = min(min_x, obj.x)
                max_x = max(max_x, obj.x + box_width)
            min_y = min(min_y, obj.y)
            max_y = max(max_y, obj.y + box_height)
        grid_rect = QRectF(
            self.layout.week_left_x(self.min_week),
            0,
            (self.layout.week_left_x(self.max_week) + self.layout.week_width)
            - self.layout.week_left_x(self.min_week),
            height,
        )
        self.setSceneRect(min_x, min_y, max_x - min_x, max_y - min_y)
        self.grid_item.set_rect(grid_rect)
        self.grid_item.update()

    def ensure_week_range(self, week: int) -> None:
        changed = False
        while week < self.min_week + self.week_expand_buffer:
            self.min_week -= self.week_expand
            changed = True
        while week > self.max_week - self.week_expand_buffer:
            self.max_week += self.week_expand
            changed = True
        if changed:
            self._update_scene_rect()

    def _ensure_range_for_objects(self) -> None:
        for obj in self.model.objects.values():
            if obj.kind in ("textbox", "link"):
                continue
            if obj.kind in ("connector", "arrow") and obj.connector_source_id and obj.connector_target_id:
                continue
            self.ensure_week_range(obj.start_week)
            self.ensure_week_range(obj.end_week)
            if obj.target_week is not None:
                self.ensure_week_range(obj.target_week)

    def refresh_items(self, force_sync: bool = False) -> None:
        self._ensure_range_for_objects()
        self.layout.rebuild(self.model)
        self._update_scene_rect()
        selected_ids = {item.data(0) for item in self.selectedItems() if item.data(0)}
        existing_items = self.items_by_id
        existing_cache = self._object_cache
        new_items: dict[str, object] = {}
        new_cache: dict[str, object] = {}

        def should_display(obj) -> bool:
            if obj.kind == "textbox":
                return self.show_textboxes
            if obj.kind == "link":
                return self.show_textboxes
            if obj.kind == "deadline":
                return True
            if obj.kind in ("connector", "arrow"):
                if not (obj.connector_source_id and obj.connector_target_id):
                    # Free connectors/arrows are only shown when both rows exist.
                    if obj.row_id not in self.layout.row_map:
                        return False
                    target_row = obj.target_row_id or obj.row_id
                    return target_row in self.layout.row_map
                return True
            return obj.row_id in self.layout.row_map

        def item_matches_kind(item, kind: str) -> bool:
            if kind == "textbox":
                return isinstance(item, TextboxItem)
            if kind == "deadline":
                return isinstance(item, DeadlineItem)
            if kind == "link":
                return isinstance(item, LinkItem)
            if kind in ("connector", "arrow"):
                return isinstance(item, ConnectorItem)
            if kind == "box":
                return isinstance(item, BoxItem)
            if kind == "milestone":
                return isinstance(item, MilestoneItem)
            if kind == "circle":
                return isinstance(item, CircleItem)
            return False

        def create_item(obj):
            if obj.kind == "textbox":
                return TextboxItem(obj.id)
            if obj.kind == "deadline":
                return DeadlineItem(obj.id)
            if obj.kind == "link":
                return LinkItem(obj.id, self)
            if obj.kind in ("connector", "arrow"):
                return ConnectorItem(obj.id, self)
            if obj.kind == "box":
                return BoxItem(obj.id)
            if obj.kind == "milestone":
                return MilestoneItem(obj.id)
            if obj.kind == "circle":
                return CircleItem(obj.id)
            return None

        for obj in self.model.objects.values():
            if not should_display(obj):
                continue
            item = existing_items.get(obj.id)
            if item is not None and not item_matches_kind(item, obj.kind):
                self.removeItem(item)
                item = None
            if item is None:
                item = create_item(obj)
                if item is None:
                    continue
                self.addItem(item)
            item.setData(0, obj.id)
            if not self.edit_mode:
                item.setFlag(item.GraphicsItemFlag.ItemIsMovable, False)
            cached_obj = existing_cache.get(obj.id)
            needs_sync = force_sync or cached_obj is None or cached_obj is not obj
            if obj.kind in ("link", "connector", "arrow"):
                needs_sync = True
            if needs_sync:
                if isinstance(item, BoxItem):
                    item.sync_from_model(obj, self.layout, self.show_missing_scope)
                else:
                    item.sync_from_model(obj, self.layout)
            geometry = self.layout.object_geometry.get(obj.id)
            if geometry is not None:
                if needs_sync or getattr(item, '_applied_geometry', None) != geometry:
                    # Layout changes also move unchanged objects and later rows.
                    # Do not reset their text documents or active inline editors.
                    item.setPos(geometry.x, geometry.y)
                    item._applied_geometry = geometry
                    if isinstance(item, BoxItem):
                        item._notify_dependency_handle_geometry_changed()
            new_items[obj.id] = item
            new_cache[obj.id] = obj
            if obj.id in selected_ids and not item.isSelected():
                item.setSelected(True)

        for obj_id, item in existing_items.items():
            if obj_id not in new_items:
                self.removeItem(item)
        self.items_by_id = new_items
        for obj_id, item in new_items.items():
            obj = self.model.objects[obj_id]
            y1, w1 = self.layout.week_index_to_year_week(self.model.year, obj.start_week)
            y2, w2 = self.layout.week_index_to_year_week(self.model.year, obj.end_week)
            fallback = "Event" if obj.kind == "circle" else obj.kind.title()
            item.setToolTip(
                f"<b>{escape(obj.text or fallback)}</b><br>"
                f"{format_year_week(y1, w1)} → {format_year_week(y2, w2)}"
            )
        self._object_cache = new_cache
        connector_ids = {
            obj.id for obj in self.model.objects.values() if obj.kind in ("connector", "arrow")
        }
        for connector_id in list(self.connector_cache.keys()):
            if connector_id not in connector_ids:
                del self.connector_cache[connector_id]
        self._update_dependency_layer()
        self._update_initiative_rollup()

    def _update_dependency_layer(self) -> None:
        path = QPainterPath()
        selected_keys = set(self.selected_dependency_keys())
        old_items = self.dependency_items_by_key
        new_items: dict[tuple[str, str], DependencyEdgeItem] = {}
        for obj in self.model.objects.values():
            item = self.items_by_id.get(obj.id)
            if item is None:
                continue
            for pred_id in getattr(obj, "predecessors", []) or []:
                pred_item = self.items_by_id.get(pred_id)
                if pred_item is None:
                    continue
                start_rect = pred_item.sceneBoundingRect()
                end_rect = item.sceneBoundingRect()
                start = QPointF(start_rect.right(), start_rect.center().y())
                end = QPointF(end_rect.left(), end_rect.center().y())
                edge_path = QPainterPath()
                edge_path.moveTo(start)
                # If date ranges touch or overlap, the usual midpoint dogleg
                # would run through one of the bars.  Route around the union
                # of both bounds with a small deterministic clearance.
                overlaps_horizontally = start_rect.left() <= end_rect.right() and end_rect.left() <= start_rect.right()
                if overlaps_horizontally:
                    margin = 12.0
                    # Use the actual space between the two rows.  Choosing a
                    # fixed position above the successor can send the first
                    # vertical leg back through the predecessor when it is
                    # located on the higher row.
                    if start_rect.bottom() <= end_rect.top():
                        gap_y = (start_rect.bottom() + end_rect.top()) / 2.0
                    elif end_rect.bottom() <= start_rect.top():
                        gap_y = (end_rect.bottom() + start_rect.top()) / 2.0
                    else:
                        # Rows overlap vertically: use a safe corridor just
                        # outside the union on the side nearest the successor.
                        gap_y = end_rect.top() - margin if end_rect.center().y() > start_rect.center().y() else end_rect.bottom() + margin
                    entry_x = end_rect.left() - margin
                    edge_path.lineTo(start.x(), gap_y)
                    edge_path.lineTo(entry_x, gap_y)
                    edge_path.lineTo(entry_x, end.y())
                    edge_path.lineTo(end)
                else:
                    mid_x = (start.x() + end.x()) / 2.0
                    edge_path.lineTo(mid_x, start.y())
                    edge_path.lineTo(mid_x, end.y())
                    edge_path.lineTo(end)
                # Arrowhead
                edge_path.moveTo(end)
                edge_path.lineTo(end.x() - 7, end.y() - 4)
                edge_path.moveTo(end)
                edge_path.lineTo(end.x() - 7, end.y() + 4)
                path.addPath(edge_path)
                key = (obj.id, pred_id)
                edge_item = old_items.get(key)
                if edge_item is None:
                    edge_item = DependencyEdgeItem(*key)
                    self.addItem(edge_item)
                edge_item.setPath(edge_path)
                edge_item.set_interaction_enabled(self.edit_mode)
                if key in selected_keys and self.edit_mode:
                    edge_item.setSelected(True)
                new_items[key] = edge_item
        for key, edge_item in old_items.items():
            if key not in new_items:
                self.removeItem(edge_item)
        self.dependency_items_by_key = new_items
        pen = QPen(QColor("#8b5cf6"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.6)
        pen.setCosmetic(True)
        self.dependency_layer.setPen(pen)
        self.dependency_layer.setPath(path)

        self._update_dependency_hover_visuals()

    def set_dependency_hover_object(self, object_id: str | None) -> None:
        if object_id is not None and object_id not in self.model.objects:
            object_id = None
        self._dependency_hover_object_id = object_id
        self._dependency_hover_predecessor_ids = set()
        self._dependency_hover_successor_ids = set()
        self._dependency_hover_edge_keys = set()
        if object_id is not None:
            obj = self.model.objects.get(object_id)
            predecessors = set(getattr(obj, "predecessors", []) or []) if obj else set()
            successors = {
                candidate.id
                for candidate in self.model.objects.values()
                if object_id in (getattr(candidate, "predecessors", []) or [])
            }
            self._dependency_hover_predecessor_ids = predecessors
            self._dependency_hover_successor_ids = successors
            self._dependency_hover_edge_keys = {
                (object_id, predecessor_id) for predecessor_id in predecessors
            } | {
                (successor_id, object_id) for successor_id in successors
            }
        self._update_dependency_hover_visuals()

    def set_dependency_hover_edge(self, key: tuple[str, str] | None) -> None:
        if key is None or key not in self.dependency_items_by_key:
            self.clear_dependency_hover()
            return
        successor_id, predecessor_id = key
        self._dependency_hover_object_id = successor_id
        self._dependency_hover_predecessor_ids = {predecessor_id}
        self._dependency_hover_successor_ids = set()
        self._dependency_hover_edge_keys = {key}
        self._update_dependency_hover_visuals()

    def clear_dependency_hover(self) -> None:
        self.set_dependency_hover_object(None)

    def is_dependency_hovered_object(self, object_id: str) -> bool:
        return object_id in {
            self._dependency_hover_object_id,
            *self._dependency_hover_predecessor_ids,
            *self._dependency_hover_successor_ids,
        }

    def is_dependency_hovered_focus(self, object_id: str) -> bool:
        return object_id == self._dependency_hover_object_id

    def is_dependency_hovered_edge(self, successor_id: str, predecessor_id: str) -> bool:
        return (successor_id, predecessor_id) in self._dependency_hover_edge_keys

    def _update_dependency_hover_visuals(self) -> None:
        if self._dependency_hover_object_id not in self.model.objects:
            self._dependency_hover_object_id = None
            self._dependency_hover_predecessor_ids.clear()
            self._dependency_hover_successor_ids.clear()
            self._dependency_hover_edge_keys.clear()
        else:
            self._dependency_hover_predecessor_ids.intersection_update(self.model.objects)
            self._dependency_hover_successor_ids.intersection_update(self.model.objects)
            self._dependency_hover_edge_keys.intersection_update(self.dependency_items_by_key)
        for item in self.items_by_id.values():
            item.update()
        for edge_item in self.dependency_items_by_key.values():
            edge_item.set_dependency_hovered(
                edge_item.relationship_key in self._dependency_hover_edge_keys
            )

    def selected_dependency_keys(self) -> list[tuple[str, str]]:
        return [
            key
            for key, item in self.dependency_items_by_key.items()
            if item.isSelected()
        ]

    def dependency_edge_for_item(self, item) -> DependencyEdgeItem | None:
        current = item
        while current is not None:
            if isinstance(current, DependencyEdgeItem):
                return current
            current = current.parentItem()
        return None

    def dependency_interaction_items(self) -> list[DependencyEdgeItem]:
        return list(self.dependency_items_by_key.values())

    def set_initiative_rollup(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.show_initiative_rollup:
            return
        self.show_initiative_rollup = enabled
        self.refresh_items(force_sync=True)

    def _update_initiative_rollup(self) -> None:
        for item in self._initiative_items:
            if item.scene() is not None:
                self.removeItem(item)
        self._initiative_items = []
        member_ids: set[str] = set()
        for initiative in self.model.initiatives:
            member_ids.update(initiative.member_ids)
        if not self.show_initiative_rollup:
            for item in self.items_by_id.values():
                item.setVisible(True)
            return
        for obj_id, item in self.items_by_id.items():
            item.setVisible(obj_id not in member_ids)
        for initiative in self.model.initiatives:
            member_objs = [
                self.model.objects[m] for m in initiative.member_ids
                if m in self.model.objects
            ]
            spans = [
                (o.start_week, o.end_week, o.row_id) for o in member_objs
                if o.row_id in self.layout.row_map
            ]
            if not spans:
                continue
            start = min(s[0] for s in spans)
            end = max(s[1] for s in spans)
            row_id = spans[0][2]
            top = self.layout.row_top_y(row_id)
            height = max(14.0, self.layout.row_height(row_id) * 0.45)
            rect_item = QGraphicsRectItem()
            rect_item.setRect(
                self.layout.week_left_x(start),
                top,
                (end - start + 1) * self.layout.week_width,
                height,
            )
            rect_item.setBrush(QColor(initiative.color))
            pen = QPen(QColor("#ffffff"))
            pen.setCosmetic(True)
            rect_item.setPen(pen)
            rect_item.setZValue(40)
            label = QGraphicsSimpleTextItem(
                f"{initiative.name} ({len(member_objs)})", rect_item
            )
            label.setBrush(QColor("#ffffff"))
            label.setPos(self.layout.week_left_x(start) + 6, top + 1)
            self.addItem(rect_item)
            self._initiative_items.append(rect_item)

    def set_edit_mode(self, enabled: bool) -> None:
        self.clear_dependency_hover()
        self.edit_mode = enabled
        for edge_item in self.dependency_items_by_key.values():
            edge_item.set_interaction_enabled(enabled)
        for item in self.items_by_id.values():
            obj_id = item.data(0)
            obj = self.model.objects.get(obj_id) if obj_id else None
            if obj and obj.kind == "link":
                item.setFlag(item.GraphicsItemFlag.ItemIsMovable, False)
            elif obj and obj.kind in ("connector", "arrow") and (
                obj.connector_source_id and obj.connector_target_id
            ):
                # Attached connectors are locked; free connectors stay movable.
                item.setFlag(item.GraphicsItemFlag.ItemIsMovable, False)
            else:
                item.setFlag(item.GraphicsItemFlag.ItemIsMovable, enabled)

    def commit_object_change(self, obj_id: str, changes: dict, description: str) -> None:
        if not self.controller:
            return
        self.controller.update_object(obj_id, changes, description)

    def toggle_topic(self, topic_id: str) -> None:
        if not self.controller:
            return
        self.controller.toggle_topic_collapsed(topic_id)

    def ordered_deliverable_ids(self, row_ids: set[str] | None = None) -> list[str]:
        target_ids = self.selected_row_ids if row_ids is None else set(row_ids)
        ordered: list[str] = []
        for row in self.layout.rows:
            if row.kind == "deliverable" and row.row_id in target_ids:
                ordered.append(row.row_id)
        return ordered

    def highlighted_row_ids(self) -> list[str]:
        highlighted: list[str] = []
        if self.selected_row_id and self.selected_row_id in self.layout.row_map:
            row = self.layout.row_map[self.selected_row_id]
            if row.kind == "topic":
                highlighted.append(row.row_id)
        for row_id in self.ordered_deliverable_ids():
            if row_id not in highlighted:
                highlighted.append(row_id)
        return highlighted

    def selected_deliverable_ids(self) -> list[str]:
        return self.ordered_deliverable_ids()

    def set_selected_row(self, row_id: str | None) -> None:
        if row_id is not None and row_id not in self.layout.row_map:
            row_id = None
        selected_ids: set[str] = set()
        anchor_row_id: str | None = None
        if row_id is not None:
            row = self.layout.row_map[row_id]
            if row.kind == "deliverable":
                selected_ids = {row_id}
                anchor_row_id = row_id
        if (
            row_id == self.selected_row_id
            and selected_ids == self.selected_row_ids
            and anchor_row_id == self.row_selection_anchor_id
        ):
            return
        self.selected_row_id = row_id
        self.selected_row_ids = selected_ids
        self.row_selection_anchor_id = anchor_row_id
        self.update()

    def set_selected_deliverables(
        self,
        row_ids: set[str],
        *,
        active_row_id: str | None = None,
        anchor_row_id: str | None = None,
    ) -> None:
        valid_ids = {
            row_id
            for row_id in row_ids
            if row_id in self.layout.row_map and self.layout.row_map[row_id].kind == "deliverable"
        }
        ordered = self.ordered_deliverable_ids(valid_ids)
        active = active_row_id if active_row_id in valid_ids else None
        if active is None and ordered:
            active = ordered[-1]
        anchor = None
        if anchor_row_id in self.layout.row_map:
            anchor_row = self.layout.row_map[anchor_row_id]
            if anchor_row.kind == "deliverable":
                anchor = anchor_row_id
        if anchor is None and ordered:
            anchor = active or ordered[0]
        if (
            active == self.selected_row_id
            and valid_ids == self.selected_row_ids
            and anchor == self.row_selection_anchor_id
        ):
            return
        self.selected_row_id = active
        self.selected_row_ids = valid_ids
        self.row_selection_anchor_id = anchor
        self.update()

    def set_focused_row(self, row_id: str | None) -> None:
        if row_id and row_id not in self.layout.row_map:
            row_id = None
        if row_id == self.focused_row_id:
            return
        self.focused_row_id = row_id
        self.grid_item.update()
        self.update()

    # --- Visual relation state (selection / focus / dimming) ---------------
    def set_visual_relations(
        self,
        related: set[str] | None = None,
        dimmed: set[str] | None = None,
    ) -> None:
        related = set(related or ())
        dimmed = set(dimmed or ())
        if related == self.related_ids and dimmed == self.dimmed_ids:
            return
        self.related_ids = related
        self.dimmed_ids = dimmed
        for obj_id, item in self.items_by_id.items():
            if obj_id in dimmed:
                item.setOpacity(0.28)
            else:
                obj = self.model.objects.get(obj_id)
                base = 1.0
                if obj is not None and obj.kind == "textbox":
                    base = obj.opacity if obj.opacity is not None else 1.0
                item.setOpacity(base)
            item.update()

    def clear_visual_relations(self) -> None:
        self.set_visual_relations(set(), set())

    def item_visual_state(self, obj_id: str) -> str:
        if obj_id in self.dimmed_ids:
            return "dimmed"
        if obj_id in self.related_ids:
            return "related"
        return "normal"

    def set_status(self, message: str) -> None:
        self.status_message.emit(message)

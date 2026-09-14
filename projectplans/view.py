from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PyQt6 import sip
from PyQt6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTextEdit,
)
from .week_format import format_year_week

from .constants import (
    CANVAS_ROW_ID,
    CONNECTOR_DEFAULT_COLOR,
    LINK_LINE_WIDTH,
    MAX_ZOOM,
    MIN_ZOOM,
    TEXT_SIZE_MAX,
    TEXT_SIZE_MIN,
    TEXT_SIZE_STEP,
    TEXTBOX_ANCHOR_MARGIN,
    TEXTBOX_MIN_HEIGHT,
    TEXTBOX_MIN_WIDTH,
)
from .text_shortcuts import apply_text_action, extract_text_payload, text_shortcut_action
from . import theme

CONVERTIBLE_OBJECT_TYPES = (
    ("box", "Activity"),
    ("milestone", "Milestone"),
    ("deadline", "Deadline"),
    ("circle", "Event"),
)
LABEL_RESIZE_MARGIN = 6
LABEL_RESIZE_MIN_WIDTH = 80
DEPENDENCY_VALID_COLOR = "#00b1eb"
DEPENDENCY_INVALID_COLOR = "#dc4457"


class _DependencyPortItem(QGraphicsEllipseItem):
    """Dependency port that keeps its plus mark crisp at every zoom level."""

    def __init__(self, rect: QRectF, color: QColor | None = None, parent=None) -> None:
        super().__init__(rect, parent)
        self._color = QColor(color or QColor(0, 177, 235))
        self._hit_hovered = False
        self._apply_style()

    def _apply_style(self) -> None:
        fill = QColor(self._color)
        fill.setAlpha(85 if self._hit_hovered else 45)
        edge = QColor(self._color)
        edge.setAlpha(150)
        self.setBrush(fill)
        pen = QPen(edge, 1)
        pen.setCosmetic(True)
        self.setPen(pen)

    def set_port_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self._apply_style()
        self.update()

    def set_hit_hovered(self, hovered):
        if self._hit_hovered != hovered:
            self._hit_hovered = hovered
            self._apply_style()
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        rect = self.rect()
        arm = min(rect.width(), rect.height()) * 0.22
        center = rect.center()
        plus = QColor(self._color)
        plus.setAlpha(230)
        pen = QPen(plus, 1.5)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(center.x() - arm, center.y()),
            QPointF(center.x() + arm, center.y()),
        )
        painter.drawLine(
            QPointF(center.x(), center.y() - arm),
            QPointF(center.x(), center.y() + arm),
        )


class _InlineTextEdit(QTextEdit):
    def __init__(self, commit_cb, cancel_cb, allow_newlines: bool, parent=None) -> None:
        super().__init__(parent)
        self._commit_cb = commit_cb
        self._cancel_cb = cancel_cb
        self._allow_newlines = allow_newlines
        self._done = False

    def _commit(self) -> None:
        if self._done:
            return
        self._done = True
        self._commit_cb()

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._cancel_cb()

    def keyPressEvent(self, event) -> None:
        action = text_shortcut_action(event)
        if action:
            cursor = self.textCursor()
            if apply_text_action(
                cursor,
                action,
                self.font(),
                min_size=TEXT_SIZE_MIN,
                max_size=TEXT_SIZE_MAX,
                step=TEXT_SIZE_STEP,
            ):
                self.setTextCursor(cursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._allow_newlines and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                super().keyPressEvent(event)
                self.ensureCursorVisible()
                return
            self._commit()
            event.accept()
            return
        super().keyPressEvent(event)
        self.ensureCursorVisible()

    def insertFromMimeData(self, source) -> None:
        text = source.text()
        if not self._allow_newlines:
            text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        self.insertPlainText(text)

    def focusOutEvent(self, event) -> None:
        self._commit()
        super().focusOutEvent(event)


class CanvasView(QGraphicsView):
    viewport_changed = pyqtSignal()
    tool_changed = pyqtSignal(object)
    def __init__(self, scene, controller) -> None:
        super().__init__(scene)
        self.controller = controller
        self.current_zoom = 1.0
        self.last_scene_pos = None
        self._space_pan = False
        self._right_pan = False
        self._right_pan_pos = None
        self._right_click_pending = False
        self._right_click_pos = None
        self._group_drag = False
        self._group_drag_start = None
        self._group_drag_positions = {}
        self._create_preview = None
        self._snap_guide = None
        self._initial_name_id = None
        self._initial_name_edited = False
        self._create_tool = None
        self._create_start = None
        self._create_start_row = None
        self._create_start_week = None
        self._auto_create = False
        self._auto_create_moved = False
        self._marquee_start = None
        self._marquee_active = False
        self._marquee_rect = None
        self._row_drag_start = None
        self._row_drag_ids = []
        self._row_drag_active = False
        self._reset_cursor()
        self._row_drag_marker = None
        self._row_drag_target = None
        self._row_drag_target_row_id = None
        self._row_drag_target_descriptor = None
        self._connector_dragging = False
        self._connector_preview = None
        self._connector_start_item = None
        self._connector_start_obj_id = None
        self._connector_start_side = None
        self._connector_start_offset = None
        self._connector_start_scene = None
        self._dependency_handles = []
        self._dependency_handle_source = None
        self._dependency_handle_direction = None
        self._dependency_link_mode = False
        self._dependency_source_side = None
        self._dependency_source_offset = None
        self._dependency_dragging = False
        self._dependency_preview = None
        self._dependency_target_port = None
        self._dependency_target_outline = None
        self._dependency_target_id = None
        self._dependency_target_valid = False
        self._label_resize_active = False
        self._label_resize_hover = False
        self._inline_editor = None
        self._inline_editor_item = None
        self._inline_editor_text_item = None
        self._inline_editor_obj_id = None
        self._inline_editor_original = ""
        self._inline_editor_original_html = None
        self._inline_editor_original_font = None
        self._last_pointer_pos = None
        self._position_guidance_enabled = True
        self._position_hint = QLabel(self.viewport())
        self._position_hint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._position_hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._position_hint.setTextFormat(Qt.TextFormat.RichText)
        self._position_hint.setStyleSheet(
            "QLabel { background: rgba(24, 32, 45, 235); color: white; "
            "border: 1px solid rgba(255,255,255,55); border-radius: 5px; "
            "padding: 5px 8px; }"
        )
        self._position_hint.hide()
        self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _position_guidance_suppressed(self) -> bool:
        scene = self.scene()
        return bool(
            scene is None
            or not scene.edit_mode
            or self._space_pan
            or self._right_pan
            or self._row_drag_start is not None
            or self._dependency_dragging
            or self._connector_dragging
            or self._inline_editor is not None
        )

    def set_position_guidance_enabled(self, enabled: bool) -> None:
        self._position_guidance_enabled = bool(enabled)
        if self._position_guidance_enabled:
            self._update_position_guidance()
        else:
            self._position_hint.hide()

    def _pointer_location(self, pos):
        scene = self.scene()
        if scene is None:
            return None
        scene_pos = self.mapToScene(pos)
        if scene_pos.x() <= scene.layout.label_width:
            return None
        row_id = scene.layout.row_at_y(scene_pos.y())
        row = scene.layout.row_map.get(row_id) if row_id else None
        if row is None or getattr(row, "divider", False):
            return None
        week = scene.layout.week_from_x(scene_pos.x(), snap=False)
        year, week_number = scene.layout.week_index_to_year_week(
            scene.model.year, week
        )
        if row.kind == "topic":
            row_label = row.name
        else:
            topic = scene.model.get_topic(row.topic_id)
            row_label = (
                f"{topic.name} › {row.name}" if topic is not None else row.name
            )
        return {
            "scene_pos": scene_pos,
            "row_id": row.row_id,
            "week": week,
            "week_label": f"{year} · W{week_number:02d}",
            "row_label": row_label,
        }

    def _update_position_guidance(self, pos=None) -> None:
        scene = self.scene()
        if pos is None:
            pos = self._last_pointer_pos
        if pos is None or not self._position_guidance_enabled or self._position_guidance_suppressed():
            self._position_hint.hide()
            return
        location = self._pointer_location(pos)
        if location is None:
            self._position_hint.hide()
            return
        def is_movable(item) -> bool:
            checker = getattr(item, "isMovable", None)
            if callable(checker):
                return bool(checker())
            return bool(item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)

        active_placement = bool(
            self._create_tool
            or self._group_drag
            or (
                QApplication.mouseButtons() & Qt.MouseButton.LeftButton
                and any(
                    item.isSelected() and is_movable(item)
                    for item in scene.items_by_id.values()
                )
            )
        )
        if not active_placement and self._object_item_at_scene(location["scene_pos"]) is not None:
            self._position_hint.hide()
            return
        scene_pos = location["scene_pos"]
        if self._create_tool in ("box", "milestone", "deadline", "circle"):
            start = self._create_start_week
            if start is not None:
                end = scene.layout.week_from_x(scene_pos.x(), self._create_tool == "box")
                first, last = sorted((start, end))
                y1, w1 = scene.layout.week_index_to_year_week(scene.model.year, first)
                y2, w2 = scene.layout.week_index_to_year_week(scene.model.year, last)
                if self._create_tool == "box" and first != last:
                    location["week_label"] = (
                        f"{y1} · W{w1:02d}–{y2} · W{w2:02d}"
                    )
        self._position_hint.setText(
            f"<b>{location['week_label']}</b><br>{location['row_label']}"
        )
        self._position_hint.adjustSize()
        margin = 8
        offset = 16
        x = pos.x() + offset
        y = pos.y() + offset
        if x + self._position_hint.width() > self.viewport().width() - margin:
            x = pos.x() - self._position_hint.width() - offset
        if y + self._position_hint.height() > self.viewport().height() - margin:
            y = pos.y() - self._position_hint.height() - offset
        self._position_hint.move(max(margin, x), max(margin, y))
        self._position_hint.show()

    def activate_create_tool(self, kind: str | None) -> None:
        self._finish_inline_edit(True)
        self._clear_create_preview()
        self._create_tool = kind
        self.tool_changed.emit(kind)
        self._create_start = None
        self._create_start_row = None
        self._create_start_week = None
        self._auto_create = False
        self._auto_create_moved = False
        self._clear_marquee()
        self._cancel_connector_drag()
        self._cancel_dependency_drag()
        if kind:
            self._apply_cursor(Qt.CursorShape.CrossCursor)
        else:
            self._apply_cursor(Qt.CursorShape.ArrowCursor)
        self._update_position_guidance()

    def _feedback_connection(self, preview, position, source_id):
        target = self._object_item_at_scene(position, skip_id=source_id)
        obj = self.scene().model.objects.get(target.data(0)) if target else None
        valid = obj is not None and obj.kind not in ('link', 'connector', 'arrow', 'textbox')
        pen = preview.pen()
        pen.setColor(QColor('#00b1eb' if valid else '#94a3b8'))
        preview.setPen(pen)
        self.tool_changed.emit('Release on this object to connect' if valid else 'Move to a valid target object')

    def _clear_create_preview(self):
        if self._create_preview is not None:
            if self._create_preview.scene():
                self._create_preview.scene().removeItem(self._create_preview)
            self._create_preview = None
        self._clear_snap_guide()

    def _clear_marquee(self) -> None:
        if self._marquee_rect is not None:
            if self._marquee_rect.scene():
                self._marquee_rect.scene().removeItem(self._marquee_rect)
            self._marquee_rect = None
        self._marquee_start = None
        self._marquee_active = False

    def _clear_row_drag(self) -> None:
        if self._row_drag_marker is not None:
            if self._row_drag_marker.scene():
                self._row_drag_marker.scene().removeItem(self._row_drag_marker)
            self._row_drag_marker = None
        if self._row_drag_target is not None:
            if self._row_drag_target.scene():
                self._row_drag_target.scene().removeItem(self._row_drag_target)
            self._row_drag_target = None
        self._row_drag_start = None
        self._row_drag_ids = []
        self._row_drag_active = False
        self._row_drag_target_row_id = None
        self._row_drag_target_descriptor = None
        self.viewport().update()

    def _row_drop_target(self, scene_pos: QPointF):
        """Return the authoritative target used by preview and drop."""
        scene = self.scene()
        layout = scene.layout
        row_id = layout.row_at_y(scene_pos.y())
        row = layout.row_map.get(row_id) if row_id else None
        if row is None or row.kind not in ("topic", "deliverable"):
            return None
        moving_ids = list(self._row_drag_ids)
        if not moving_ids or (row.kind == "deliverable" and row.row_id in moving_ids):
            return None
        target_topic = scene.model.get_topic(row.topic_id)
        if target_topic is None:
            return None
        remaining = [d.id for d in target_topic.deliverables if d.id not in moving_ids]
        if row.kind == "deliverable":
            target_index = next(
                (index for index, deliverable_id in enumerate(remaining) if deliverable_id == row.row_id),
                len(remaining),
            )
            row_top = layout.row_top_y(row.row_id)
            insert_after = scene_pos.y() > row_top + (row.height / 2.0)
            boundary_y = row_top + row.height if insert_after else row_top
            if insert_after:
                target_index += 1
        else:
            target_index = 0
            boundary_y = (
                layout.row_top_y(target_topic.deliverables[0].id)
                if target_topic.deliverables
                else layout.row_top_y(row.row_id) + row.height
            )
        current_sequences = {
            topic.id: [deliverable.id for deliverable in topic.deliverables]
            for topic in scene.model.topics
        }
        new_sequences = {
            topic_id: [deliverable_id for deliverable_id in deliverable_ids if deliverable_id not in moving_ids]
            for topic_id, deliverable_ids in current_sequences.items()
        }
        new_sequences[row.topic_id][target_index:target_index] = moving_ids
        return {
            "topic_id": row.topic_id,
            "index": target_index,
            "boundary_y": boundary_y,
            "row_id": row.row_id,
            "valid": new_sequences != current_sequences,
        }

    def _update_row_drag(self, pos) -> None:
        if self._row_drag_start is None:
            return
        scene_pos = self.mapToScene(pos)
        if not self._row_drag_active:
            self._row_drag_active = (scene_pos - self._row_drag_start).manhattanLength() >= 8
        if not self._row_drag_active:
            return
        target = self._row_drop_target(scene_pos)
        if target is None or not target["valid"]:
            self._row_drag_target_descriptor = target
            self._row_drag_target_row_id = None
            if self._row_drag_target is not None:
                self._row_drag_target.setVisible(False)
            if self._row_drag_marker is not None:
                self._row_drag_marker.setVisible(False)
            self.viewport().update()
            return
        self._row_drag_target_descriptor = target
        self._row_drag_target_row_id = target["row_id"]
        layout = self.scene().layout
        row = layout.row_map[target["row_id"]]
        row_top = layout.row_top_y(row.row_id)
        if self._row_drag_target is None:
            self._row_drag_target = QGraphicsRectItem()
            self._row_drag_target.setData(1, "row_drag_target")
            self._row_drag_target.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._row_drag_target.setZValue(1e8)
            self.scene().addItem(self._row_drag_target)
            self._row_drag_target.setPen(QPen(Qt.PenStyle.NoPen))
            self._row_drag_target.setBrush(QColor(0, 177, 235, 38))
        self._row_drag_target.setVisible(True)
        self._row_drag_target.setRect(0.0, row_top, layout.label_width, row.height)
        if self._row_drag_marker is None:
            self._row_drag_marker = QGraphicsLineItem()
            self._row_drag_marker.setData(1, "row_drag_marker")
            self._row_drag_marker.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._row_drag_marker.setZValue(1e9)
            self.scene().addItem(self._row_drag_marker)
            pen = QPen(QColor("#00b1eb")); pen.setCosmetic(True); pen.setWidthF(2.0)
            self._row_drag_marker.setPen(pen)
        self._row_drag_marker.setVisible(True)
        self._row_drag_marker.setLine(
            0.0, target["boundary_y"], self.scene().layout.label_width, target["boundary_y"]
        )
        self._apply_cursor(Qt.CursorShape.ClosedHandCursor)
        self.viewport().update()

    def _finish_row_drag(self, pos) -> None:
        if self._row_drag_start is None:
            return
        if not self._row_drag_active:
            self._clear_row_drag()
            return
        target = self._row_drop_target(self.mapToScene(pos))
        if target is not None and target["valid"]:
            self.controller.move_deliverables_to(
                self._row_drag_ids, target["topic_id"], target["index"]
            )
        self._clear_row_drag()

    def _update_marquee(self, pos) -> None:
        if self._marquee_start is None:
            return
        current = self.mapToScene(pos)
        rect = QRectF(self._marquee_start, current).normalized()
        if self._marquee_rect is None:
            self._marquee_rect = QGraphicsRectItem()
            self._marquee_rect.setData(1, "selection_marquee")
            self._marquee_rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._marquee_rect.setZValue(1e9)
            self.scene().addItem(self._marquee_rect)
            pen = QPen(QColor("#00b1eb"))
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._marquee_rect.setPen(pen)
            self._marquee_rect.setBrush(QColor(0, 177, 235, 35))
        self._marquee_rect.setRect(rect)
        self._marquee_active = (current - self._marquee_start).manhattanLength() >= 8

    def _finish_marquee(self) -> None:
        if self._marquee_start is None:
            return
        if self._marquee_active and self._marquee_rect is not None:
            rect = self._marquee_rect.rect()
            for item in self.scene().items_by_id.values():
                if item.isVisible() and item.sceneBoundingRect().intersects(rect):
                    item.setSelected(True)
            for item in self.scene().dependency_interaction_items():
                if item.isVisible() and item.mapToScene(item.shape()).intersects(rect):
                    item.setSelected(True)
        self._clear_marquee()

    def _clear_snap_guide(self):
        if self._snap_guide is not None:
            if self._snap_guide.scene():
                self._snap_guide.scene().removeItem(self._snap_guide)
            self._snap_guide = None

    def _update_snap_guide(self, x: float, top: float, bottom: float) -> None:
        scene = self.scene()
        if scene is None:
            return
        if self._snap_guide is None:
            self._snap_guide = QGraphicsLineItem()
            self._snap_guide.setData(1, 'snap_guide')
            self._snap_guide.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._snap_guide.setZValue(1e9)
            scene.addItem(self._snap_guide)
        pen = QPen(QColor('#8b5cf6'))
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._snap_guide.setPen(pen)
        self._snap_guide.setLine(x, top, x, bottom)
        self._snap_guide.setVisible(True)

    def _update_create_preview(self, pos):
        if self._create_start is None or self._create_tool not in ('box', 'connector', 'textbox', 'milestone', 'deadline', 'circle'):
            return
        scene = self.scene()
        layout = scene.layout
        end = self.mapToScene(pos)
        first = self._create_start_week
        last = layout.week_from_x(end.x(), scene.snap_weeks)
        if self._create_tool == 'textbox':
            rect = QRectF(self._create_start, end).normalized()
        else:
            row_id = self._create_start_row
            top = layout.row_top_y(row_id) if row_id else layout.header_height
            height = layout.row_height(row_id) if row_id else max(28, layout.total_height)
            if self._create_tool in ('milestone', 'deadline', 'circle'):
                last = first
            left, right = sorted((first, last))
            rect = QRectF(layout.week_left_x(left), top, (right-left+1)*layout.week_width, height)
        if self._create_preview is None:
            self._create_preview = QGraphicsRectItem()
            self._create_preview.setData(1, 'creation_preview')
            self._create_preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._create_preview.setZValue(1e9)
            scene.addItem(self._create_preview)
        pen = QPen(QColor('#00b1eb'))
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._create_preview.setPen(pen)
        self._create_preview.setBrush(QColor(0, 177, 235, 45))
        self._create_preview.setRect(rect)
        self._update_snap_guide(
            layout.week_left_x(max(first, last) + 1), rect.top(), rect.bottom()
        )
        y1, w1 = layout.week_index_to_year_week(scene.model.year, min(first, last))
        y2, w2 = layout.week_index_to_year_week(scene.model.year, max(first, last))
        self.tool_changed.emit(
            f'{format_year_week(y1, w1)} → {format_year_week(y2, w2)} · '
            f'{abs(last-first)+1} weeks'
        )

    def active_create_tool(self) -> str | None:
        return self._create_tool

    def _cancel_connector_drag(self) -> None:
        if self._connector_preview is not None:
            scene = self.scene()
            if scene:
                scene.removeItem(self._connector_preview)
            self._connector_preview = None
        self._connector_dragging = False
        self._connector_start_item = None
        self._connector_start_obj_id = None
        self._connector_start_side = None
        self._connector_start_offset = None
        self._connector_start_scene = None

    def _connector_edge_margin(self) -> float:
        scale = max(0.01, self.transform().m11())
        return TEXTBOX_ANCHOR_MARGIN / scale

    def _object_item_from_graphics_item(self, item):
        current = item
        while current is not None and not current.data(0):
            current = current.parentItem()
        if current is not None and current.data(0):
            return current
        return None

    def _object_item_at_scene(self, scene_pos: QPointF, skip_id: str | None = None):
        scene = self.scene()
        if scene is None:
            return None
        for item in scene.items(scene_pos):
            if item.data(0) == "__dependency_handle__":
                continue
            obj_item = self._object_item_from_graphics_item(item)
            if obj_item is None:
                continue
            obj_id = obj_item.data(0)
            if obj_id and obj_id != skip_id:
                return obj_item
        return None

    def _clear_dependency_handles(self) -> None:
        scene = self.scene()
        handles = self._dependency_handles
        self._dependency_handles = []
        self._dependency_handle_source = None
        self._dependency_handle_direction = None
        self._dependency_link_mode = False
        self._dependency_source_side = None
        self._dependency_source_offset = None
        for handle in handles:
            if sip.isdeleted(handle):
                continue
            if handle.parentItem() is not None:
                handle.setParentItem(None)
            if scene and handle.scene() is scene:
                scene.removeItem(handle)
        if not self._dependency_dragging:
            self._reset_cursor()

    def _prune_dependency_handles(self) -> None:
        live_handles = [
            handle for handle in self._dependency_handles if not sip.isdeleted(handle)
        ]
        if len(live_handles) == len(self._dependency_handles):
            return
        self._dependency_handles = live_handles
        if not live_handles:
            self._dependency_handle_source = None
            self._dependency_handle_direction = None

    def _clear_dependency_target_feedback(self) -> None:
        scene = self.scene()
        for overlay in (self._dependency_target_port, self._dependency_target_outline):
            if overlay is not None and scene and overlay.scene():
                scene.removeItem(overlay)
        self._dependency_target_port = None
        self._dependency_target_outline = None
        self._dependency_target_id = None
        self._dependency_target_valid = False

    def transient_dependency_items(self) -> list:
        self._prune_dependency_handles()
        return [
            item
            for item in (
                *self._dependency_handles,
                self._dependency_preview,
                self._dependency_target_port,
                self._dependency_target_outline,
            )
            if item is not None
        ]

    def _layout_dependency_handles_for_item(self, item) -> None:
        self._prune_dependency_handles()
        if (
            item is None
            or item.data(0) != self._dependency_handle_source
            or not self._dependency_handles
        ):
            return
        bounds = item.boundingRect()
        size = max(8.0, min(14.0, 10.0 / max(0.01, self.transform().m11())))
        gap = 10.0
        for handle in self._dependency_handles:
            handle.setRect(0.0, 0.0, size, size)
            direction = handle.data(2)
            if direction == "left":
                x = bounds.left() - gap - size
                y = bounds.center().y() - (size / 2.0)
                handle.setPos(x, y)
            elif direction == "right":
                x = bounds.right() + gap
                y = bounds.center().y() - (size / 2.0)
                handle.setPos(bounds.right() + gap, y)
            elif direction == "top":
                x = bounds.center().x() - (size / 2.0)
                y = bounds.top() - gap - size
                handle.setPos(x, y)
            else:  # bottom
                x = bounds.center().x() - (size / 2.0)
                y = bounds.bottom() + gap
                handle.setPos(x, y)

    def _show_dependency_handles(self, item) -> None:
        self._prune_dependency_handles()
        scene = self.scene()
        if scene is None or item is None or not scene.edit_mode:
            self._clear_dependency_handles()
            return
        obj = scene.model.objects.get(item.data(0))
        if obj is None or obj.kind in ("link", "connector", "arrow"):
            self._clear_dependency_handles()
            return
        if self._dependency_handle_source == obj.id and self._dependency_handles:
            self._layout_dependency_handles_for_item(item)
            return
        self._clear_dependency_handles()
        size = max(8.0, min(14.0, 10.0 / max(.01, self.transform().m11())))
        directions = ("left", "right", "top", "bottom") if obj.kind == "textbox" else ("left", "right")
        for direction in directions:
            handle = _DependencyPortItem(QRectF(0.0, 0.0, size, size), parent=item)
            handle.setZValue(10_000.0)
            handle.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            handle.setData(0, "__dependency_handle__")
            handle.setData(1, obj.id)
            handle.setData(2, direction)
            handle.setToolTip(
                (
                    "Drag to create textbox link"
                    if obj.kind == "textbox"
                    else (
                        "Drag to add predecessor"
                        if direction == "left"
                        else "Drag to add successor"
                    )
                )
            )
            self._dependency_handles.append(handle)
        self._dependency_handle_source = obj.id
        self._layout_dependency_handles_for_item(item)

    def _dependency_handle_at(self, scene_pos):
        self._prune_dependency_handles()
        if not self.scene().edit_mode:
            return None
        handles = [h for h in self._dependency_handles if h.isVisible() and h.isEnabled()]
        for handle in handles:
            if handle.contains(handle.mapFromScene(scene_pos)):
                return handle
        if self._object_item_at_scene(scene_pos) is not None:
            return None
        point = self.mapFromScene(scene_pos)
        candidates = [h for h in handles if self._dependency_handle_hit_rect(h).contains(QPointF(point))]
        return min(candidates, key=lambda h: (self.mapFromScene(h.sceneBoundingRect().center()) - point).manhattanLength(), default=None)

    def _dependency_handle_hit_rect(self, handle):
        center = self.mapFromScene(handle.sceneBoundingRect().center())
        return QRectF(center.x() - 12, center.y() - 12, 24, 24)

    def _resolve_dependency_target(self, scene_pos):
        source_kind = None
        if self._dependency_handle_source:
            source = self.scene().model.objects.get(self._dependency_handle_source)
            source_kind = source.kind if source is not None else None
        target_kinds = (
            ('box', 'milestone', 'circle', 'deadline')
            if source_kind == 'textbox'
            else ('box', 'milestone', 'circle')
        )
        items = [item for item in self.scene().items_by_id.values()
                 if item.isVisible() and item.isEnabled()
                 and self.scene().model.objects[item.data(0)].kind in target_kinds]
        point = QPointF(self.mapFromScene(scene_pos))
        ranked = []
        for item in items:
            rect = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
            dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
            dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
            distance = (dx * dx + dy * dy) ** 0.5
            ranked.append((distance, -item.zValue(), str(item.data(0)), item))
        direct = [entry for entry in ranked if entry[0] == 0]
        if direct:
            return min(direct, key=lambda e: e[:3])[3]
        retained = next((e for e in ranked if e[2] == self._dependency_target_id and e[0] <= 18), None)
        if retained:
            return retained[3]
        eligible = [e for e in ranked if e[0] <= 12 and self._dependency_candidate(e[2])[2]]
        return min(eligible, key=lambda e: e[:3])[3] if eligible else None

    def _start_dependency_drag(self, handle) -> bool:
        scene = self.scene()
        if scene is None:
            return False
        self._dependency_dragging = True
        self._dependency_handle_source = handle.data(1)
        self._dependency_handle_direction = handle.data(2)
        source = scene.model.objects.get(self._dependency_handle_source)
        self._dependency_link_mode = source is not None and source.kind == "textbox"
        if self._dependency_link_mode:
            source_item = scene.items_by_id.get(self._dependency_handle_source)
            if source_item is not None:
                local_center = source_item.mapFromScene(handle.sceneBoundingRect().center())
                bounds = source_item.boundingRect()
                self._dependency_source_side = self._dependency_handle_direction
                offset_axis = (
                    local_center.y() - bounds.top()
                    if self._dependency_handle_direction in ("left", "right")
                    else local_center.x() - bounds.left()
                )
                offset_extent = (
                    bounds.height()
                    if self._dependency_handle_direction in ("left", "right")
                    else bounds.width()
                )
                self._dependency_source_offset = max(
                    0.0,
                    min(1.0, offset_axis / max(1.0, offset_extent)),
                )
        start = handle.sceneBoundingRect().center()
        preview = QGraphicsLineItem(QLineF(start, start))
        pen = QPen(QColor("#8b5cf6")); pen.setStyle(Qt.PenStyle.DashLine); pen.setWidthF(1.2)
        preview.setPen(pen); preview.setZValue(9999); preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scene.addItem(preview); self._dependency_preview = preview
        self._apply_cursor(Qt.CursorShape.CrossCursor)
        return True

    def _dependency_candidate(self, target_id: str) -> tuple[str, str, bool]:
        source_id = self._dependency_handle_source
        if self._dependency_link_mode:
            target = self.scene().model.objects.get(target_id)
            valid = bool(
                source_id
                and target is not None
                and source_id != target_id
                and target.kind in ("box", "milestone", "circle", "deadline")
            )
            return source_id, target_id, valid
        if self._dependency_handle_direction == "left":
            successor_id, predecessor_id = source_id, target_id
        else:
            successor_id, predecessor_id = target_id, source_id
        valid = bool(
            successor_id
            and predecessor_id
            and self.controller
            and self.controller.can_add_predecessor(successor_id, predecessor_id)
        )
        return successor_id, predecessor_id, valid

    def _update_dependency_target_feedback(self, scene_pos: QPointF) -> None:
        scene = self.scene()
        if scene is None:
            return
        target = self._resolve_dependency_target(scene_pos)
        target_id = target.data(0) if target is not None else None
        if not target_id:
            self._clear_dependency_target_feedback()
            if self._dependency_preview is not None:
                pen = self._dependency_preview.pen()
                pen.setColor(QColor("#8b5cf6"))
                self._dependency_preview.setPen(pen)
            self.tool_changed.emit("Move to a dependency target")
            return

        _, _, valid = self._dependency_candidate(target_id)
        color = QColor(DEPENDENCY_VALID_COLOR if valid else DEPENDENCY_INVALID_COLOR)
        if (
            target_id == self._dependency_target_id
            and valid == self._dependency_target_valid
            and self._dependency_target_port is not None
            and self._dependency_target_outline is not None
        ):
            if self._dependency_preview is not None:
                pen = self._dependency_preview.pen()
                pen.setColor(color)
                self._dependency_preview.setPen(pen)
            return
        self._clear_dependency_target_feedback()

        target_path = target.sceneTransform().map(target.shape())
        if target_path.isEmpty():
            target_path = QPainterPath()
            target_path.addRect(target.sceneBoundingRect())
        outline = QGraphicsPathItem(target_path)
        outline_pen = QPen(color, 2)
        outline_pen.setCosmetic(True)
        outline.setPen(outline_pen)
        outline.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        outline.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        outline.setZValue(target.zValue() + 20)
        outline.setData(1, "dependency_target_outline")
        scene.addItem(outline)

        bounds = target.sceneBoundingRect()
        scale = max(0.01, self.transform().m11())
        size = max(8.0, min(14.0, 10.0 / scale))
        direction = self._dependency_handle_direction
        if direction == "left":
            receptor_center = QPointF(bounds.right(), bounds.center().y())
        elif direction == "right":
            receptor_center = QPointF(bounds.left(), bounds.center().y())
        elif direction == "top":
            receptor_center = QPointF(bounds.center().x(), bounds.bottom())
        else:  # bottom
            receptor_center = QPointF(bounds.center().x(), bounds.top())
        receptor = _DependencyPortItem(
            QRectF(
                receptor_center.x() - (size / 2.0),
                receptor_center.y() - (size / 2.0),
                size,
                size,
            ),
            color,
        )
        receptor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        receptor.setZValue(target.zValue() + 21)
        receptor.setData(1, "dependency_target_port")
        scene.addItem(receptor)

        self._dependency_target_outline = outline
        self._dependency_target_port = receptor
        self._dependency_target_id = target_id
        self._dependency_target_valid = valid
        if self._dependency_preview is not None:
            pen = self._dependency_preview.pen()
            pen.setColor(color)
            self._dependency_preview.setPen(pen)
        self.tool_changed.emit(
            (
                "Release to create textbox link"
                if valid and self._dependency_link_mode
                else "Release to create dependency"
            )
            if valid
            else (
                "Textbox link cannot be created"
                if self._dependency_link_mode
                else "Dependency cannot be created"
            )
        )

    def _cancel_dependency_drag(self):
        self._dependency_pending = None
        self._clear_dependency_target_feedback()
        scene = self.scene()
        if self._dependency_preview is not None and scene and self._dependency_preview.scene():
            scene.removeItem(self._dependency_preview)
        self._dependency_preview = None
        self._dependency_dragging = False
        self._dependency_handle_source = None
        self._dependency_handle_direction = None
        self._dependency_link_mode = False
        self._dependency_source_side = None
        self._dependency_source_offset = None

    def _finish_dependency_drag(self, scene_pos):
        if not self._dependency_dragging:
            return
        source_id, direction = self._dependency_handle_source, self._dependency_handle_direction
        link_mode = self._dependency_link_mode
        target = self._resolve_dependency_target(scene_pos)
        target_id = target.data(0) if target else None
        created = False
        if source_id and target_id:
            if self._dependency_link_mode:
                source_side = self._dependency_source_side or direction
                source_offset = self._dependency_source_offset
                before_ids = set(self.scene().model.objects)
                _, _, valid = self._dependency_candidate(target_id)
                if valid:
                    self.controller.add_anchor_link(
                        source_id, target_id, source_side, source_offset
                    )
                    created = bool(set(self.scene().model.objects) - before_ids)
            elif direction == "left":
                created = self.controller.add_predecessor(source_id, target_id)
            else:
                created = self.controller.add_predecessor(target_id, source_id)
        self._cancel_dependency_drag()
        if created:
            self.tool_changed.emit(
                "Textbox link created" if link_mode else "Dependency created"
            )
        self._reset_cursor()

    def _edge_anchor_for_item(
        self, item, scene_pos: QPointF, *, require_edge: bool
    ) -> tuple[str, float] | None:
        pos = item.mapFromScene(scene_pos)
        bounds = item.boundingRect()
        margin = self._connector_edge_margin()
        if require_edge and not bounds.adjusted(-margin, -margin, margin, margin).contains(pos):
            return None
        if not bounds.contains(pos) and require_edge:
            return None
        left = bounds.left()
        right = bounds.right()
        top = bounds.top()
        bottom = bounds.bottom()
        distances = {
            "left": abs(pos.x() - left),
            "right": abs(right - pos.x()),
            "top": abs(pos.y() - top),
            "bottom": abs(bottom - pos.y()),
        }
        side, dist = min(distances.items(), key=lambda entry: entry[1])
        if require_edge and dist > margin:
            return None
        width = max(1.0, bounds.width())
        height = max(1.0, bounds.height())
        if side in ("left", "right"):
            offset = (pos.y() - top) / height
        else:
            offset = (pos.x() - left) / width
        offset = max(0.0, min(1.0, offset))
        return side, offset

    def _anchor_point_for_item(self, item, side: str, offset: float) -> QPointF:
        custom_anchor = getattr(item, "anchor_local_point", None)
        if callable(custom_anchor):
            return item.mapToScene(custom_anchor(side, offset))
        bounds = item.boundingRect()
        width = max(1.0, bounds.width())
        height = max(1.0, bounds.height())
        left = bounds.left()
        top = bounds.top()
        right = bounds.right()
        bottom = bounds.bottom()
        if side == "left":
            local = QPointF(left, top + (height * offset))
        elif side == "top":
            local = QPointF(left + (width * offset), top)
        elif side == "bottom":
            local = QPointF(left + (width * offset), bottom)
        else:
            local = QPointF(right, top + (height * offset))
        return item.mapToScene(local)

    def _start_connector_drag(self, scene_pos: QPointF) -> bool:
        item = self._object_item_at_scene(scene_pos)
        if item is None:
            return False
        obj_id = item.data(0)
        scene = self.scene()
        if scene is None or not obj_id:
            return False
        obj = scene.model.objects.get(obj_id)
        if obj is None or obj.kind in ("link", "connector", "arrow"):
            return False
        anchor = self._edge_anchor_for_item(item, scene_pos, require_edge=True)
        if anchor is None:
            return False
        side, offset = anchor
        start_scene = self._anchor_point_for_item(item, side, offset)
        preview = QGraphicsLineItem(QLineF(start_scene, start_scene))
        default_color = (
            self.controller.connector_default_color
            if self.controller is not None
            else CONNECTOR_DEFAULT_COLOR
        )
        preview_color = QColor(default_color)
        if not preview_color.isValid():
            preview_color = QColor(CONNECTOR_DEFAULT_COLOR)
        pen = QPen(preview_color)
        pen.setWidth(LINK_LINE_WIDTH)
        preview.setPen(pen)
        preview.setZValue(item.zValue() + 1)
        preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scene.addItem(preview)
        self._connector_dragging = True
        self._connector_preview = preview
        self._connector_start_item = item
        self._connector_start_obj_id = obj_id
        self._connector_start_side = side
        self._connector_start_offset = offset
        self._connector_start_scene = start_scene
        return True

    def _finish_connector_drag(self, scene_pos: QPointF) -> None:
        if not self._connector_dragging:
            return
        scene = self.scene()
        if scene is None:
            self._cancel_connector_drag()
            self._reset_cursor()
            return
        if self._connector_preview is not None:
            scene.removeItem(self._connector_preview)
        self._connector_preview = None
        source_id = self._connector_start_obj_id
        source_side = self._connector_start_side
        source_offset = self._connector_start_offset
        target_item = self._object_item_at_scene(scene_pos, skip_id=source_id)
        target_id = target_item.data(0) if target_item else None
        created = False
        if (
            source_id
            and target_id
            and source_side is not None
            and source_offset is not None
            and target_item is not None
        ):
            target_anchor = self._edge_anchor_for_item(
                target_item, scene_pos, require_edge=False
            )
            if target_anchor:
                target_side, target_offset = target_anchor
                self.controller.add_connector_arrow(
                    source_id,
                    target_id,
                    source_side,
                    source_offset,
                    target_side,
                    target_offset,
                )
                created = True
        self._connector_dragging = False
        self._connector_start_item = None
        self._connector_start_obj_id = None
        self._connector_start_side = None
        self._connector_start_offset = None
        self._connector_start_scene = None
        if created:
            self.activate_create_tool(None)
        self._reset_cursor()

    def set_navigation_mode(self, enabled: bool) -> None:
        if enabled:
            self._cancel_dependency_drag()
            self._clear_dependency_handles()
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._update_position_guidance()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.1 if delta > 0 else 0.9
            self.zoom_by(factor)
            return
        super().wheelEvent(event)

    def zoom_by(self, factor: float) -> None:
        new_zoom = self.current_zoom * factor
        if new_zoom < MIN_ZOOM or new_zoom > MAX_ZOOM:
            return
        if not self._dependency_dragging:
            self._clear_dependency_handles()
        self.current_zoom = new_zoom
        self.scale(factor, factor)
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def set_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if not self._dependency_dragging:
            self._clear_dependency_handles()
        self.resetTransform()
        self.current_zoom = zoom
        self.scale(zoom, zoom)
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def zoom_to_fit(self) -> None:
        fit_rect = self._fit_content_rect()
        if fit_rect.isNull():
            return
        self.fitInView(fit_rect, Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.transform()
        self.current_zoom = transform.m11()
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center.x(), fit_rect.top() + self.viewport().height() / (2 * self.current_zoom))
        self.viewport_changed.emit()
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def _fit_content_rect(self) -> QRectF:
        scene = self.scene()
        if scene is None:
            return QRectF()
        layout = scene.layout

        content_rect = QRectF()
        non_textbox_rect = QRectF()

        for obj_id, item in scene.items_by_id.items():
            if not item.isVisible():
                continue
            obj = scene.model.objects.get(obj_id)
            if obj is None:
                continue
            item_rect = self._item_scene_rect(item)
            if item_rect.isNull():
                continue
            content_rect = item_rect if content_rect.isNull() else content_rect.united(item_rect)
            if obj.kind not in ("textbox", "link"):
                non_textbox_rect = (
                    item_rect if non_textbox_rect.isNull() else non_textbox_rect.united(item_rect)
                )

        fit_rect = QRectF(content_rect)
        if layout.rows:
            fit_rect = self._row_header_fit_rect(non_textbox_rect).united(fit_rect)
        elif fit_rect.isNull():
            fit_rect = self._quarter_fallback_rect()

        if fit_rect.isNull():
            return fit_rect

        padding_x = max(24.0, layout.week_width * 0.5)
        padding_y = max(16.0, min(60.0, fit_rect.height() * 0.05))
        return fit_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

    def _item_scene_rect(self, item) -> QRectF:
        rect = item.sceneBoundingRect()
        for child in item.childItems():
            if not child.isVisible():
                continue
            child_rect = self._item_scene_rect(child)
            if child_rect.isNull():
                continue
            rect = child_rect if rect.isNull() else rect.united(child_rect)
        return rect

    def _row_header_fit_rect(self, non_textbox_rect: QRectF) -> QRectF:
        scene = self.scene()
        if scene is None:
            return QRectF()
        layout = scene.layout
        if non_textbox_rect.isNull():
            span_rect = self._quarter_fallback_rect()
        else:
            span_rect = non_textbox_rect
        left = span_rect.left() - layout.label_width
        right = span_rect.right()
        return QRectF(left, 0.0, max(1.0, right - left), layout.header_height + layout.total_height)

    def _quarter_fallback_rect(self) -> QRectF:
        scene = self.scene()
        if scene is None:
            return QRectF()
        layout = scene.layout
        iso = datetime.now().isocalendar()
        quarter = min(4, ((iso.week - 1) // 13) + 1)
        base_week = layout.week_index_for_iso_year(scene.model.year, iso.year)
        quarter_offset = (quarter - 1) * 13
        quarter_start = base_week + quarter_offset
        quarter_length = min(13, layout.weeks_in_year(iso.year) - quarter_offset)
        quarter_end = quarter_start + max(1, quarter_length) - 1
        left = layout.week_left_x(quarter_start)
        right = layout.week_left_x(quarter_end) + layout.week_width
        height = max(1.0, layout.header_height + layout.total_height)
        return QRectF(left, 0.0, max(1.0, right - left), height)

    def zoom_to_selection(self) -> None:
        items = self.scene().selectedItems()
        if not items:
            return
        rect = None
        for item in items:
            item_rect = item.sceneBoundingRect()
            rect = item_rect if rect is None else rect.united(item_rect)
        if rect is None or rect.isNull():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.transform()
        self.current_zoom = transform.m11()
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center.x(), fit_rect.top() + self.viewport().height() / (2 * self.current_zoom))
        self.viewport_changed.emit()
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def center_on_base_year(self) -> None:
        layout = self.scene().layout
        weeks = layout.weeks_in_year(self.scene().model.year)
        week = layout.origin_week + (weeks // 2)
        self.centerOn(layout.week_center_x(week), layout.header_height)

    def drawForeground(self, painter, rect) -> None:
        super().drawForeground(painter, rect)
        scene = self.scene()
        layout = scene.layout
        if not layout.rows:
            return
        scale = max(0.01, self.transform().m11())
        label_width = self._label_width_pixels()
        viewport_rect = self.viewport().rect()
        header_top = self.mapFromScene(0, 0).y()
        header_bottom = self.mapFromScene(0, layout.header_height).y()

        painter.save()
        painter.resetTransform()
        painter.setClipRect(QRectF(0, 0, label_width, viewport_rect.height()))

        t = theme.tokens(getattr(scene, "dark_mode", False))
        painter.fillRect(QRectF(0, 0, label_width, viewport_rect.height()), QColor(t['card']))
        painter.fillRect(QRectF(0, header_top, label_width, header_bottom - header_top), QColor(t['soft']))

        # Draw row-drag feedback in the foreground so it remains visible above
        # the scene's temporary graphics items and the timeline grid.
        if (
            self._row_drag_active
            and self._row_drag_target_row_id
            and self._row_drag_target_descriptor
            and self._row_drag_target_descriptor.get("valid")
        ):
            target = layout.row_map.get(self._row_drag_target_row_id)
            if target is not None:
                target_top = self.mapFromScene(0, layout.row_top_y(target.row_id)).y()
                target_bottom = self.mapFromScene(0, layout.row_top_y(target.row_id) + target.height).y()
                target_fill = QColor(t['cyan'])
                target_fill.setAlpha(42)
                painter.fillRect(QRectF(0, target_top, label_width, target_bottom - target_top), target_fill)
                marker_y = self.mapFromScene(
                    0, self._row_drag_target_descriptor["boundary_y"]
                ).y()
                marker_pen = QPen(QColor(t['cyan']))
                marker_pen.setWidth(2)
                painter.setPen(marker_pen)
                painter.drawLine(0, int(marker_y), int(label_width), int(marker_y))

        topic_fill = QColor(t['soft'])
        topic_fill.setAlpha(30)
        deliverable_fill = QColor(t['soft'])
        deliverable_fill.setAlpha(28)
        for row in layout.rows:
            row_top = self.mapFromScene(0, layout.header_height + row.y).y()
            row_bottom = self.mapFromScene(0, layout.header_height + row.y + row.height).y()
            if row_bottom < 0 or row_top > viewport_rect.height():
                continue
            if row.kind == 'topic' and not getattr(row, 'divider', False):
                painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), topic_fill)
                topic = scene.model.get_topic(row.row_id)
                if topic:
                    accent = QColor(topic.color)
                    accent.setAlpha(220)
                    painter.fillRect(QRectF(0, row_top, max(3.0, 3.0 * scale), row_bottom - row_top), accent)
            elif row.kind == 'deliverable' and (layout.row_index(row.row_id) or 0) % 2 == 0:
                painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), deliverable_fill)

        focused_row_id = getattr(scene, "focused_row_id", None)
        if focused_row_id and focused_row_id in layout.row_map:
            row = layout.row_map[focused_row_id]
            row_top = self.mapFromScene(0, layout.header_height + row.y).y()
            row_bottom = self.mapFromScene(0, layout.header_height + row.y + row.height).y()
            fill = QColor(t['warning'])
            fill.setAlpha(44)
            painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), fill)

        for highlighted_row_id in scene.highlighted_row_ids():
            row = layout.row_map.get(highlighted_row_id)
            if row is None:
                continue
            row_top = self.mapFromScene(0, layout.header_height + row.y).y()
            row_bottom = self.mapFromScene(0, layout.header_height + row.y + row.height).y()
            painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), QColor(t['hover']))

        grid_color = QColor(t['grid'])
        grid_color.setAlpha(150)
        pen_grid = QPen(grid_color)
        pen_grid.setWidth(1)
        painter.setPen(pen_grid)
        painter.drawLine(int(label_width), 0, int(label_width), int(viewport_rect.height()))
        painter.drawLine(0, int(header_bottom), int(label_width), int(header_bottom))
        for row in layout.rows:
            row_bottom = self.mapFromScene(0, layout.header_height + row.y + row.height).y()
            if row_bottom < 0 or row_bottom > viewport_rect.height() + 1:
                continue
            boundary_color = QColor(t['grid'])
            if row.kind == 'topic' and not getattr(row, 'divider', False):
                boundary_color = QColor(t['text'])
                boundary_color.setAlpha(90)
            painter.setPen(QPen(boundary_color))
            painter.drawLine(0, int(row_bottom), int(label_width), int(row_bottom))
            painter.setPen(pen_grid)

        painter.setPen(QPen(QColor(t['text'])))
        font = QFont(painter.font())
        base_size = font.pointSizeF()
        if base_size > 0:
            font.setPointSizeF(max(1.0, base_size * scale))
        elif font.pixelSize() > 0:
            font.setPixelSize(max(1, int(font.pixelSize() * scale)))
        painter.setFont(font)

        topic_font = QFont(font)
        topic_font.setBold(True)
        indicator_font = QFont(topic_font)
        if indicator_font.pointSizeF() > 0:
            indicator_font.setPointSizeF(max(1.0, indicator_font.pointSizeF() * 0.8))
        indent_step = 14 * scale
        indicator_offset = 6 * scale
        indicator_gap = 16 * scale
        padding = 6 * scale

        for row in layout.rows:
            row_top = self.mapFromScene(0, layout.header_height + row.y).y()
            row_bottom = self.mapFromScene(0, layout.header_height + row.y + row.height).y()
            if row_bottom < 0 or row_top > viewport_rect.height():
                continue
            row_height = row_bottom - row_top
            label_rect = QRectF(0, row_top, label_width, row_height)
            text_x = (8 * scale) + (row.indent * indent_step)

            if row.kind == "topic":
                painter.setFont(indicator_font)
                if getattr(row, "divider", False):
                    # Divider rows draw a dash instead of a collapse indicator.
                    indicator = "—"
                else:
                    topic = scene.model.get_topic(row.row_id)
                    indicator = "▸" if topic and topic.collapsed else "▾"
                indicator_pen = QColor(t['muted'])
                painter.setPen(indicator_pen)
                painter.drawText(
                    label_rect.adjusted(indicator_offset, 0, 0, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    indicator,
                )
                painter.setPen(QColor(t['text']))
                painter.setFont(topic_font)
                text_x += indicator_gap
            else:
                painter.setFont(font)

            text_rect = QRectF(text_x, row_top, label_width - text_x - padding, row_height)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, row.name)

        painter.restore()

        painter.save()
        painter.resetTransform()
        tag_text = scene.model.classification_label()
        font = QFont(painter.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(float(scene.model.classification_size))
        elif font.pixelSize() > 0:
            font.setPixelSize(max(1, int(scene.model.classification_size)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        margin = 12
        max_width = max(1, viewport_rect.width() - (margin * 2))
        tag_text = metrics.elidedText(tag_text, Qt.TextElideMode.ElideRight, int(max_width))
        painter.setPen(QColor(t['muted']))
        overlay_rect = QRectF(
            margin,
            margin,
            max(1.0, viewport_rect.width() - (margin * 2)),
            max(1.0, viewport_rect.height() - (margin * 2)),
        )
        painter.drawText(
            overlay_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            tag_text,
        )
        painter.restore()

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if event.button() == Qt.MouseButton.LeftButton and scene and scene.edit_mode and not self._create_tool:
            handle = self._dependency_handle_at(self.mapToScene(event.pos()))
            if handle is not None:
                self._dependency_pending = (handle, QPoint(event.pos()))
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and self._is_over_label_resize_handle(event.pos()):
            self._label_resize_active = True
            self._label_resize_hover = False
            self._apply_cursor(Qt.CursorShape.SplitHCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._right_click_pending = True
            self._right_pan = False
            self._right_pan_pos = None
            self._right_click_pos = event.pos()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.pos().x() <= self._label_width_pixels():
                scene_pos = self.mapToScene(event.pos())
                row_id = self.scene().layout.row_at_y(scene_pos.y())
                self.scene().clearSelection()
                self._select_row_from_click(row_id, event.modifiers())
                row = self.scene().layout.row_map.get(row_id) if row_id else None
                if row is not None and row.kind == "deliverable" and self.scene().edit_mode:
                    self._row_drag_start = scene_pos
                    self._row_drag_ids = self.scene().selected_deliverable_ids()
                event.accept()
                return
            if self.scene().edit_mode and not self._create_tool:
                modifiers = event.modifiers()
                clicked = self.itemAt(event.pos())
                dependency_edge = self.scene().dependency_edge_for_item(clicked)
                if dependency_edge is not None:
                    toggle = modifiers & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                    if toggle:
                        dependency_edge.setSelected(not dependency_edge.isSelected())
                    else:
                        self.scene().clearSelection()
                        dependency_edge.setSelected(True)
                    event.accept()
                    return
                if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                    obj_item = self._object_item_from_graphics_item(clicked) if clicked else None
                    if obj_item is not None and obj_item.data(0):
                        obj_item.setSelected(not obj_item.isSelected())
                        event.accept()
                        return
                selected = self.scene().selectedItems()
                if len(selected) > 1:
                    item = self.itemAt(event.pos())
                    movable_selection = {
                        sel: QPointF(sel.pos())
                        for sel in selected
                        if sel.data(0) in self.scene().model.objects
                    }
                    if item and item.isSelected() and movable_selection:
                        self._group_drag = True
                        self._group_drag_start = self.mapToScene(event.pos())
                        self._group_drag_positions = movable_selection
                        self._apply_cursor(Qt.CursorShape.SizeHorCursor)
                        event.accept()
                        return
                if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                    scene_pos = self.mapToScene(event.pos())
                    if (
                        scene_pos.y() >= self.scene().layout.header_height
                        and self._object_item_at_scene(scene_pos) is None
                    ):
                        self._marquee_start = scene_pos
                        event.accept()
                        return
                # An empty calendar cell starts a normal activity creation drag.
                # Existing objects and labels retain their ordinary interactions.
                scene_pos = self.mapToScene(event.pos())
                row_id = self.scene().layout.row_at_y(scene_pos.y())
                if row_id and self._object_item_at_scene(scene_pos) is None:
                    self.scene().clearSelection()
                    self.activate_create_tool("box")
                    self._auto_create = True
                    self._auto_create_moved = False
                    self._create_start = scene_pos
                    self._create_start_row = row_id
                    self._create_start_week = self.scene().layout.week_from_x(
                        scene_pos.x(), snap=False
                    )
                    event.accept()
                    return
                if (
                    scene_pos.y() >= self.scene().layout.header_height
                    and self._object_item_at_scene(scene_pos) is None
                ):
                    self.scene().clearSelection()
        if (
            self._create_tool
            and event.button() == Qt.MouseButton.LeftButton
            and self.scene().edit_mode
        ):
            if self._create_tool == "connector":
                scene_pos = self.mapToScene(event.pos())
                if self._start_connector_drag(scene_pos):
                    event.accept()
                    return
                # No object edge under the cursor: fall through to the generic
                # drag-create flow to make a free connector.
            if self._create_tool != "textbox" and event.pos().x() <= self._label_width_pixels():
                super().mousePressEvent(event)
                return
            self._create_start = self.mapToScene(event.pos())
            layout = self.scene().layout
            if self._create_tool in ("textbox", "deadline"):
                self._create_start_row = None
            else:
                self._create_start_row = layout.row_at_y(self._create_start.y())
            self._create_start_week = layout.week_from_x(
                self._create_start.x(), self.scene().snap_weeks
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._last_pointer_pos = event.pos()
        self._update_position_guidance(event.pos())
        pending = getattr(self, '_dependency_pending', None)
        if pending is not None:
            handle, origin = pending
            if sip.isdeleted(handle) or not self.scene().edit_mode:
                self._dependency_pending = None
                self._reset_cursor()
                return
            if (event.pos() - origin).manhattanLength() < QApplication.startDragDistance():
                event.accept()
                return
            self._dependency_pending = None
            self._start_dependency_drag(handle)
        if self._dependency_dragging and self._dependency_preview is not None:
            scene_pos = self.mapToScene(event.pos())
            self._dependency_preview.setLine(QLineF(self._dependency_preview.line().p1(), scene_pos))
            self._update_dependency_target_feedback(scene_pos)
            if self._dependency_target_port is not None:
                self._dependency_preview.setLine(QLineF(
                    self._dependency_preview.line().p1(), self._dependency_target_port.sceneBoundingRect().center()))
            event.accept()
            return
        if self._row_drag_start is not None:
            self._update_row_drag(event.pos())
            if self._row_drag_active:
                event.accept()
                return
        if self._marquee_start is not None:
            self._update_marquee(event.pos())
            event.accept()
            return
        if self._auto_create and self._create_start is not None:
            if (event.pos() - self.mapFromScene(self._create_start)).manhattanLength() >= 8:
                self._auto_create_moved = True
            if not self._auto_create_moved:
                event.accept()
                return
        self._update_create_preview(event.pos())
        if self._label_resize_active:
            self._apply_label_resize(event.pos())
            event.accept()
            return
        if (
            not self._right_click_pending
            and not self._right_pan
            and not self._group_drag
            and not self._connector_dragging
            and not self._space_pan
        ):
            if self._is_over_label_resize_handle(event.pos()):
                if not self._label_resize_hover:
                    self._label_resize_hover = True
                    self._apply_cursor(Qt.CursorShape.SplitHCursor)
            elif self._label_resize_hover:
                self._label_resize_hover = False
                self._reset_cursor()
        if self._connector_dragging and self._connector_preview and self._connector_start_scene:
            scene_pos = self.mapToScene(event.pos())
            self._connector_preview.setLine(QLineF(self._connector_start_scene, scene_pos))
            self._feedback_connection(self._connector_preview, scene_pos, self._connector_start_obj_id)
            event.accept()
            return
        if self._group_drag and self._group_drag_start:
            scene_pos = self.mapToScene(event.pos())
            delta_x = scene_pos.x() - self._group_drag_start.x()
            for item, start_pos in self._group_drag_positions.items():
                item.setPos(QPointF(start_pos.x() + delta_x, start_pos.y()))
            event.accept()
            return
        if self._right_click_pending:
            if not self._right_pan and self._right_click_pos is not None:
                if (event.pos() - self._right_click_pos).manhattanLength() > 6:
                    self._right_pan = True
                    self._right_pan_pos = event.pos()
                    self._apply_cursor(Qt.CursorShape.ClosedHandCursor)
            if self._right_pan and self._right_pan_pos is not None:
                delta = event.pos() - self._right_pan_pos
                self._right_pan_pos = event.pos()
                hbar = self.horizontalScrollBar()
                vbar = self.verticalScrollBar()
                hbar.setValue(hbar.value() - int(delta.x()))
                vbar.setValue(vbar.value() - int(delta.y()))
                event.accept()
                return
        self.last_scene_pos = self.mapToScene(event.pos())
        self.last_scene_pos = self.mapToScene(event.pos())
        if not self._connector_dragging and not self._create_tool and not self._marquee_start:
            handle = self._dependency_handle_at(self.last_scene_pos)
            for port in self._dependency_handles:
                port.set_hit_hovered(port is handle)
            if handle is not None:
                self._apply_cursor(Qt.CursorShape.CrossCursor)
            else:
                hovered = self._object_item_at_scene(self.last_scene_pos)
                if hovered is not None:
                    self._show_dependency_handles(hovered)
                    resize_edge = getattr(hovered, "_resize_edge_at", lambda _pos: None)(
                        hovered.mapFromScene(self.last_scene_pos)
                    )
                    if resize_edge is not None and self.scene().edit_mode:
                        self._apply_cursor(Qt.CursorShape.SizeHorCursor)
                    else:
                        self._reset_cursor()
                elif self._dependency_handle_source and self._dependency_handles:
                    # Keep the handles alive while crossing the intentional
                    # gap between the object edge and its handle.
                    source_item = self.scene().items_by_id.get(self._dependency_handle_source)
                    keep_zone = source_item.sceneBoundingRect().adjusted(-24, -12, 24, 12) if source_item else QRectF()
                    if not keep_zone.contains(self.last_scene_pos):
                        self._clear_dependency_handles()
                    self._reset_cursor()
                else:
                    self._reset_cursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._last_pointer_pos = None
        self._position_hint.hide()
        if not self._dependency_dragging and not self._label_resize_active:
            self._reset_cursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, '_dependency_pending', None) is not None:
            self._dependency_pending = None
            self._reset_cursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dependency_dragging:
            self._finish_dependency_drag(self.mapToScene(event.pos()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._row_drag_start is not None:
            self._finish_row_drag(event.pos())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._marquee_start is not None:
            self._finish_marquee()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._label_resize_active:
            self._label_resize_active = False
            self._reset_cursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._connector_dragging:
            self._finish_connector_drag(self.mapToScene(event.pos()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._group_drag:
            scene = self.scene()
            layout = scene.layout
            scene_pos = self.mapToScene(event.pos())
            delta_x = scene_pos.x() - (self._group_drag_start.x() if self._group_drag_start else 0.0)
            start_week = layout.week_from_x(
                self._group_drag_start.x() if self._group_drag_start else 0.0, scene.snap_weeks
            )
            end_week = layout.week_from_x(
                (self._group_drag_start.x() if self._group_drag_start else 0.0) + delta_x,
                scene.snap_weeks,
            )
            delta_week = end_week - start_week
            moving_ids = set()
            moved_textbox_ids = set()
            for item in self._group_drag_positions.keys():
                obj_id = item.data(0)
                if not obj_id or obj_id not in scene.model.objects:
                    continue
                obj = scene.model.objects[obj_id]
                attached_connector = obj.kind in ("connector", "arrow") and (
                    obj.connector_source_id and obj.connector_target_id
                )
                if obj.kind == "link" or attached_connector:
                    continue
                if obj.kind == "textbox" or delta_week:
                    moving_ids.add(obj_id)
                if obj.kind == "textbox":
                    moved_textbox_ids.add(obj_id)
            self.controller.undo_stack.beginMacro("Move selection")
            try:
                for item, start_pos in self._group_drag_positions.items():
                    obj_id = item.data(0)
                    if not obj_id or obj_id not in scene.model.objects:
                        continue
                    obj = scene.model.objects[obj_id]
                    attached_connector = obj.kind in ("connector", "arrow") and (
                        obj.connector_source_id and obj.connector_target_id
                    )
                    if obj.kind == "link" or attached_connector:
                        item.setPos(start_pos)
                        continue
                    if obj.kind == "textbox":
                        new_x = (obj.x or start_pos.x()) + delta_x
                        width = obj.width or TEXTBOX_MIN_WIDTH
                        start_wk = layout.week_from_x(new_x, snap=False)
                        end_wk = layout.week_from_x(new_x + width, snap=False)
                        self.controller.update_object(
                            obj.id,
                            {"x": new_x, "start_week": start_wk, "end_week": end_wk},
                            "Move Textbox",
                            skip_anchor_sources=moving_ids,
                            defer_link_updates=True,
                        )
                    elif delta_week:
                        self._move_object(
                            obj,
                            delta_week,
                            0,
                            skip_anchor_sources=moving_ids,
                            defer_link_updates=True,
                        )
                    else:
                        item.setPos(start_pos)
                self._group_drag = False
                self._group_drag_start = None
                self._group_drag_positions = {}
                if moved_textbox_ids:
                    self.controller.refresh_anchor_offsets(moved_textbox_ids)
            finally:
                self.controller.undo_stack.endMacro()
            if self._space_pan:
                self._apply_cursor(Qt.CursorShape.OpenHandCursor)
            else:
                self._apply_cursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self._right_click_pending:
            if self._right_pan:
                self._right_pan = False
                self._right_pan_pos = None
                if self._space_pan:
                    self._apply_cursor(Qt.CursorShape.OpenHandCursor)
                else:
                    self._apply_cursor(Qt.CursorShape.ArrowCursor)
            else:
                self._show_context_menu(event.pos())
            self._right_click_pending = False
            self._right_click_pos = None
            event.accept()
            return
        if (
            self._create_tool
            and self._create_start
            and event.button() == Qt.MouseButton.LeftButton
            and self.scene().edit_mode
        ):
            if self._auto_create:
                if not self._auto_create_moved:
                    self.activate_create_tool(None)
                    event.accept()
                    return
                end_scene = self.mapToScene(event.pos())
                end_week = self.scene().layout.week_from_x(
                    end_scene.x(), self.scene().snap_weeks
                )
                if end_week == self._create_start_week:
                    self.activate_create_tool(None)
                    event.accept()
                    return
            self._finish_create(event.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.scene().dependency_edge_for_item(self.itemAt(event.pos())) is not None:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.pos().x() <= self._label_width_pixels():
                scene_pos = self.mapToScene(event.pos())
                layout = self.scene().layout
                row_id = layout.row_at_y(scene_pos.y())
                if row_id:
                    row = layout.row_map.get(row_id)
                    if row and row.kind == "topic":
                        self.scene().toggle_topic(row_id)
                        return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        focus_item = self.scene().focusItem()
        if event.key() == Qt.Key.Key_Escape and getattr(self, '_dependency_pending', None) is not None:
            self._cancel_dependency_drag()
            self._reset_cursor()
            event.accept()
            return
        if (
            isinstance(focus_item, QGraphicsTextItem)
            and focus_item.textInteractionFlags()
            & Qt.TextInteractionFlag.TextEditorInteraction
        ):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_F11:
            window = self.window()
            toggle_fullscreen = getattr(window, "_toggle_canvas_fullscreen", None)
            if callable(toggle_fullscreen):
                toggle_fullscreen()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self._row_drag_start is not None:
            self._clear_row_drag()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._marquee_start is not None:
            self._clear_marquee()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._dependency_dragging:
            self._cancel_dependency_drag()
            self._reset_cursor()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and (
            self._create_tool or self._connector_dragging
        ):
            self.activate_create_tool(None)
            self._reset_cursor()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            window = self.window()
            exit_fullscreen = getattr(window, "_apply_canvas_fullscreen", None)
            if getattr(window, "_canvas_fullscreen", False) and callable(exit_fullscreen):
                exit_fullscreen(False)
                event.accept()
                return
        if event.key() == Qt.Key.Key_F2 and self._start_inline_edit():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and not self._space_pan:
            self._space_pan = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._apply_cursor(Qt.CursorShape.OpenHandCursor)
            return

        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
            return

        if event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.duplicate_selected()
            return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._nudge_selected(event)
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and self._space_pan:
            self._space_pan = False
            self._apply_cursor(Qt.CursorShape.ArrowCursor)
            if self.scene().edit_mode:
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
            else:
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            return
        super().keyReleaseEvent(event)

    def begin_inline_edit(self, text_item: QGraphicsTextItem) -> bool:
        if not self.scene().edit_mode:
            return False
        parent = text_item.parentItem()
        if parent is None:
            return False
        obj_id = parent.data(0)
        if not obj_id:
            return False
        obj = self.scene().model.objects.get(obj_id)
        if obj is None:
            return False
        self._finish_inline_edit(True)
        self._inline_editor_item = parent
        self._inline_editor_text_item = text_item
        self._inline_editor_obj_id = obj_id
        self._inline_editor_original = obj.text
        self._inline_editor_original_html = obj.text_html
        self._inline_editor_original_font = QFont(text_item.font())
        text_item.setVisible(False)

        allow_newlines = obj.kind == "textbox"
        editor = _InlineTextEdit(
            self._commit_inline_edit, self._cancel_inline_edit, allow_newlines, self.viewport()
        )
        editor.setObjectName('canvasInlineEditor')
        editor.setAcceptRichText(True)
        editor.setFrameStyle(QFrame.Shape.NoFrame)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if allow_newlines:
            editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        else:
            editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        if obj.text_html:
            editor.setHtml(obj.text_html)
        else:
            editor.setPlainText(obj.text)
        editor.document().setDefaultFont(text_item.font())
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        text_color = text_item.defaultTextColor().name()
        editor.setStyleSheet(
            'QTextEdit#canvasInlineEditor {'
            f'color: {text_color}; background: transparent; '
            'border: none; border-radius: 0; padding: 0; margin: 0; min-height: 0;'
            '}'
            'QTextEdit#canvasInlineEditor:focus { border: none; }'
        )
        editor.setFont(text_item.font())
        if obj.text_align == "left":
            alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif obj.text_align == "right":
            alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        editor.setAlignment(alignment)

        self._inline_editor = editor
        editor.textChanged.connect(self._mark_initial_name_edited)
        self._update_inline_editor_geometry()
        editor.show()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        editor.update()
        return True

    def _commit_inline_edit(self) -> None:
        self._finish_inline_edit(True)

    def _cancel_inline_edit(self) -> None:
        initial_name_id = self._initial_name_id
        remove_new_object = (
            initial_name_id is not None
            and not self._initial_name_edited
            and initial_name_id == self._inline_editor_obj_id
        )
        self._finish_inline_edit(False)
        if remove_new_object:
            self.controller.remove_object(initial_name_id)

    def _mark_initial_name_edited(self) -> None:
        if self._initial_name_id is not None and self._inline_editor is not None:
            self._initial_name_edited = True

    def _finish_inline_edit(self, accept: bool) -> None:
        editor = self._inline_editor
        if editor is None:
            return
        obj_id = self._inline_editor_obj_id
        text_item = self._inline_editor_text_item
        original = self._inline_editor_original
        original_html = self._inline_editor_original_html
        base_font = self._inline_editor_original_font or editor.document().defaultFont()
        new_text = None
        new_html = None
        if isinstance(editor, QTextEdit):
            new_text, new_html = extract_text_payload(editor.document(), base_font)
        if (
            accept
            and obj_id
            and new_text is not None
            and (new_text != original or new_html != original_html)
        ):
            if obj_id == self._initial_name_id:
                self.controller.name_created_object(obj_id, new_text, new_html)
            else:
                self.controller.update_object(obj_id, {"text": new_text, "text_html": new_html}, "Edit Text")
        if text_item is not None:
            current_obj = self.scene().model.objects.get(obj_id) if obj_id else None
            show_text = not (
                current_obj is not None
                and current_obj.kind == 'deadline'
                and not (current_obj.text or '').strip()
            )
            text_item.setVisible(show_text)
            text_item.update()
        self._initial_name_id = None
        self._initial_name_edited = False
        editor.hide()
        editor.deleteLater()
        self._inline_editor = None
        self._inline_editor_item = None
        self._inline_editor_text_item = None
        self._inline_editor_obj_id = None
        self._inline_editor_original = ""
        self._inline_editor_original_html = None
        self._inline_editor_original_font = None
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _inline_editor_scene_rect(self) -> QRectF | None:
        text_item = self._inline_editor_text_item
        if text_item is None:
            return None
        obj_id = self._inline_editor_obj_id
        obj = self.scene().model.objects.get(obj_id) if obj_id else None
        parent = text_item.parentItem()
        if obj is not None and obj.kind == 'textbox' and parent is not None:
            rect = parent.boundingRect().adjusted(4.0, 4.0, -4.0, -4.0)
            return parent.mapRectToScene(rect)
        rect = text_item.boundingRect()
        rect = rect.adjusted(-1, -1, 1, 1)
        return text_item.mapRectToScene(rect)

    def _update_inline_editor_geometry(self) -> None:
        self.viewport_changed.emit()
        editor = getattr(self, "_inline_editor", None)
        if editor is None:
            return
        rect_scene = self._inline_editor_scene_rect()
        if rect_scene is None:
            return
        rect_view = self.mapFromScene(rect_scene).boundingRect()
        obj_id = self._inline_editor_obj_id
        obj = self.scene().model.objects.get(obj_id) if obj_id else None
        if obj is None:
            return
        if obj.kind != 'textbox':
            center = rect_view.center()
            line_height = editor.fontMetrics().height() + 2
            rect_view.setHeight(max(1, min(line_height, rect_view.height())))
            rect_view.moveCenter(center)
        if obj.kind in ('milestone', 'circle', 'deadline', 'connector', 'arrow') \
                and rect_view.width() < 40:
            center = rect_view.center()
            rect_view.setWidth(40)
            rect_view.moveCenter(center)
        if obj.kind == 'deadline':
            header_top = self.mapFromScene(QPointF(0.0, 0.0)).y()
            rect_view.moveTop(max(rect_view.top(), header_top))
        editor.setGeometry(rect_view)

    def _start_inline_edit(self) -> bool:
        if not self.scene().edit_mode:
            return False
        selected = self.scene().selectedItems()
        if not selected:
            return False
        for item in selected:
            text_item = getattr(item, "text_item", None)
            if text_item is not None and hasattr(text_item, "start_edit"):
                text_item.start_edit()
                return True
        return False

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport_changed.emit()
        super().scrollContentsBy(dx, dy)
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def resizeEvent(self, event) -> None:
        self.viewport_changed.emit()
        anchor_scene = self.mapToScene(self._viewport_anchor())
        super().resizeEvent(event)
        self._restore_view_anchor(anchor_scene, self._viewport_anchor())
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self._update_position_guidance()

    def _selected_object(self):
        items = self.scene().selectedItems()
        for item in items:
            obj_id = item.data(0)
            if obj_id:
                return self.scene().model.objects.get(obj_id)
        return None

    def selected_object_ids(self):
        if not hasattr(self.scene(), 'model'):
            return []
        selected = {item.data(0) for item in self.scene().selectedItems() if item.data(0)}
        return [obj_id for obj_id in self.scene().model.objects if obj_id in selected]

    def _delete_selected(self) -> None:
        if self.scene().edit_mode:
            self._finish_inline_edit(True)
            object_ids = self.selected_object_ids()
            dependency_keys = self.scene().selected_dependency_keys()
            if not object_ids and not dependency_keys:
                return
            self.controller.undo_stack.beginMacro("Delete selection")
            try:
                self.controller.remove_predecessors(dependency_keys)
                self.controller.remove_objects(object_ids)
            finally:
                self.controller.undo_stack.endMacro()

    def duplicate_selected(self) -> None:
        if not self.scene().edit_mode:
            return
        self._finish_inline_edit(True)
        ids = self.controller.duplicate_objects(self.selected_object_ids())
        self.scene().clearSelection()
        for obj_id in ids:
            item = self.scene().items_by_id.get(obj_id)
            if item:
                item.setSelected(True)

    def _nudge_selected(self, event) -> None:
        if not self.scene().edit_mode:
            return
        items = self.scene().selectedItems()
        objects = []
        for item in items:
            obj_id = item.data(0)
            if obj_id and obj_id in self.scene().model.objects:
                obj = self.scene().model.objects[obj_id]
                if obj.kind in ("link", "connector"):
                    continue
                objects.append(obj)
        if not objects:
            return
        layout = self.scene().layout
        delta_week = 0
        delta_row = 0
        if event.key() == Qt.Key.Key_Left:
            delta_week = -1
        elif event.key() == Qt.Key.Key_Right:
            delta_week = 1
        elif event.key() == Qt.Key.Key_Up:
            delta_row = -1
        elif event.key() == Qt.Key.Key_Down:
            delta_row = 1

        if len(objects) > 1:
            if delta_week == 0:
                return
            selected_ids = {obj.id for obj in objects}
            moved_textbox_ids = {obj.id for obj in objects if obj.kind == "textbox"}
            self.controller.undo_stack.beginMacro("Move selection")
            try:
                for obj in objects:
                    self._move_object(
                        obj,
                        delta_week,
                        0,
                        skip_anchor_sources=selected_ids,
                        defer_link_updates=True,
                    )
                if moved_textbox_ids:
                    self.controller.refresh_anchor_offsets(moved_textbox_ids)
            finally:
                self.controller.undo_stack.endMacro()
            return

        obj = objects[0]
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._resize_object(obj, delta_week, delta_row)
        else:
            self._move_object(obj, delta_week, delta_row)

    def _move_object(
        self,
        obj,
        delta_week: int,
        delta_row: int,
        *,
        skip_anchor_sources: set[str] | None = None,
        defer_link_updates: bool = False,
    ) -> None:
        layout = self.scene().layout
        attached_connector = obj.kind in ("connector", "arrow") and (
            obj.connector_source_id and obj.connector_target_id
        )
        if obj.kind == "link" or attached_connector:
            return
        if obj.kind == "textbox":
            dx = delta_week * layout.week_width
            dy = delta_row * 20
            new_x = (obj.x or 0.0) + dx
            new_y = (obj.y or 0.0) + dy
            width = obj.width or TEXTBOX_MIN_WIDTH
            start_week = layout.week_from_x(new_x, snap=False)
            end_week = layout.week_from_x(new_x + width, snap=False)
            updates = {
                "x": new_x,
                "y": new_y,
                "start_week": start_week,
                "end_week": end_week,
            }
            self.controller.update_object(
                obj.id,
                updates,
                "Move Textbox",
                skip_anchor_sources=skip_anchor_sources,
                defer_link_updates=defer_link_updates,
            )
            return
        updates = {}
        if delta_week:
            updates["start_week"] = obj.start_week + delta_week
            updates["end_week"] = obj.end_week + delta_week
            if obj.kind in ("connector", "arrow"):
                target_week = obj.target_week if obj.target_week is not None else obj.end_week
                updates["target_week"] = target_week + delta_week
                updates["end_week"] = target_week + delta_week
                if obj.arrow_mid_week is not None:
                    updates["arrow_mid_week"] = obj.arrow_mid_week + delta_week
        if delta_row:
            new_row = layout.adjacent_row(obj.row_id, delta_row)
            if new_row:
                updates["row_id"] = new_row
            if obj.kind in ("connector", "arrow"):
                target_row = obj.target_row_id or obj.row_id
                new_target = layout.adjacent_row(target_row, delta_row)
                if new_target:
                    updates["target_row_id"] = new_target
        if updates:
            self.controller.update_object(
                obj.id,
                updates,
                "Nudge Object",
                skip_anchor_sources=skip_anchor_sources,
                defer_link_updates=defer_link_updates,
            )

    def _resize_object(self, obj, delta_week: int, delta_row: int) -> None:
        if obj.kind == "textbox":
            width = obj.width or TEXTBOX_MIN_WIDTH
            height = obj.height or TEXTBOX_MIN_HEIGHT
            width = max(TEXTBOX_MIN_WIDTH, width + (delta_week * self.scene().layout.week_width))
            height = max(TEXTBOX_MIN_HEIGHT, height + (delta_row * 10))
            x = obj.x or 0.0
            start_week = self.scene().layout.week_from_x(x, snap=False)
            end_week = self.scene().layout.week_from_x(x + width, snap=False)
            self.controller.update_object(
                obj.id,
                {"width": width, "height": height, "start_week": start_week, "end_week": end_week},
                "Resize Textbox",
            )
            return
        if obj.kind == "box":
            updates = {"end_week": obj.end_week + delta_week}
            if updates["end_week"] < obj.start_week:
                updates["end_week"] = obj.start_week
            self.controller.update_object(obj.id, updates, "Resize Object")
            return
        attached_connector = obj.kind in ("connector", "arrow") and (
            obj.connector_source_id and obj.connector_target_id
        )
        if attached_connector:
            return
        if obj.kind in ("connector", "arrow"):
            updates = {}
            if delta_week:
                target_week = obj.target_week if obj.target_week is not None else obj.end_week
                updates["target_week"] = target_week + delta_week
                updates["end_week"] = target_week + delta_week
            if delta_row:
                layout = self.scene().layout
                target_row = obj.target_row_id or obj.row_id
                new_target = layout.adjacent_row(target_row, delta_row)
                if new_target:
                    updates["target_row_id"] = new_target
            if updates:
                self.controller.update_object(obj.id, updates, "Resize Connector")

    def _finish_create(self, pos) -> None:
        scene = self.scene()
        layout = scene.layout
        end_pos = self.mapToScene(pos)

        kind = self._create_tool
        obj = None
        self._clear_create_preview()
        if kind == "textbox":
            if not scene.show_textboxes:
                self.activate_create_tool(None)
                return
            start = self._create_start or end_pos
            x1 = min(start.x(), end_pos.x())
            x2 = max(start.x(), end_pos.x())
            y1 = min(start.y(), end_pos.y())
            y2 = max(start.y(), end_pos.y())
            width = max(TEXTBOX_MIN_WIDTH, x2 - x1)
            height = max(TEXTBOX_MIN_HEIGHT, y2 - y1)
            obj = self.controller.make_textbox(x1, y1, width, height)
            start_wk = layout.week_from_x(x1, snap=False)
            end_wk = layout.week_from_x(x1 + width, snap=False)
            obj = replace(obj, start_week=start_wk, end_week=end_wk)
            self.controller.add_object(obj, "Add Textbox")
        else:
            if not layout.rows and kind not in ("deadline",):
                self.activate_create_tool(None)
                return

            start_row = self._create_start_row or layout.row_at_y(end_pos.y())
            end_row = layout.row_at_y(end_pos.y()) or start_row
            if kind != "deadline":
                if not start_row:
                    start_row = layout.rows[0].row_id
                if not end_row:
                    end_row = start_row

            start_week = self._create_start_week if self._create_start_week is not None else layout.week_from_x(
                self._create_start.x(), scene.snap_weeks
            )
            end_week = layout.week_from_x(end_pos.x(), scene.snap_weeks)

            if kind == "box":
                if end_week < start_week:
                    start_week, end_week = end_week, start_week
                obj = self.controller.make_default_object(kind, start_row, start_week, end_week)
                self.controller.add_object(obj, f"Add {kind.title()}")
            elif kind == "milestone":
                obj = self.controller.make_default_object(kind, start_row, start_week, start_week)
                self.controller.add_object(obj, "Add Milestone")
            elif kind == "deadline":
                obj = self.controller.make_default_object(kind, CANVAS_ROW_ID, start_week, start_week)
                self.controller.add_object(obj, "Add Deadline")
            elif kind == "circle":
                obj = self.controller.make_default_object(kind, start_row, start_week, start_week)
                self.controller.add_object(obj, "Add Event")
            elif kind in ("connector", "arrow"):
                # Free connector (attached connectors are created by
                # _finish_connector_drag when the drag starts on an item edge).
                if end_week == start_week and end_row == start_row:
                    end_week = start_week + 1
                obj = self.controller.make_default_object(
                    "connector", start_row, start_week, end_week
                )
                obj = replace(
                    obj,
                    target_row_id=end_row,
                    target_week=end_week,
                    end_week=end_week,
                )
                self.controller.add_object(obj, "Add Connector")

        self.activate_create_tool(None)
        if obj is not None:
            scene.clearSelection()
            item = scene.items_by_id.get(obj.id)
            if item:
                item.setSelected(True)
                text_item = getattr(item, 'text_item', None)
                if obj.kind == "box" and text_item is not None and self.begin_inline_edit(text_item):
                    self._initial_name_id = obj.id
                    self._initial_name_edited = False

    def _label_width_pixels(self) -> float:
        layout = self.scene().layout
        return max(1.0, layout.label_width * self.transform().m11())

    def _is_over_label_resize_handle(self, pos) -> bool:
        label_edge = self._label_width_pixels()
        return abs(pos.x() - label_edge) <= LABEL_RESIZE_MARGIN

    def _apply_label_resize(self, pos) -> None:
        scene = self.scene()
        if scene is None:
            return
        scale = max(0.01, self.transform().m11())
        width = max(LABEL_RESIZE_MIN_WIDTH, pos.x() / scale)
        old_width = scene.layout.label_width
        if abs(old_width - width) < 0.5:
            return
        delta = width - old_width
        scene.set_label_width(width)
        if abs(delta) > 0.0:
            hbar = self.horizontalScrollBar()
            hbar.setValue(hbar.value() + int(round(delta * scale)))
        self._maybe_extend_scene()
        self._update_inline_editor_geometry()
        self.viewport().update()

    def _reset_cursor(self) -> None:
        if self._space_pan:
            self._apply_cursor(Qt.CursorShape.OpenHandCursor)
        elif self._right_pan:
            self._apply_cursor(Qt.CursorShape.ClosedHandCursor)
        elif self._create_tool:
            self._apply_cursor(Qt.CursorShape.CrossCursor)
        else:
            self._apply_cursor(Qt.CursorShape.ArrowCursor)

    def _apply_cursor(self, cursor: Qt.CursorShape) -> None:
        self.setCursor(cursor)
        self.viewport().setCursor(cursor)

    def _viewport_anchor(self) -> QPoint:
        return self.viewport().rect().center()

    def _restore_view_anchor(self, anchor_scene: QPointF, anchor_view: QPoint) -> None:
        new_view = self.mapFromScene(anchor_scene)
        delta = new_view - anchor_view
        if delta.x() == 0 and delta.y() == 0:
            return
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        hbar.setValue(hbar.value() + delta.x())
        vbar.setValue(vbar.value() + delta.y())

    def _maybe_extend_scene(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        layout = scene.layout
        left_scene = self.mapToScene(0, 0).x()
        right_scene = self.mapToScene(self.viewport().width(), 0).x()
        scene.ensure_week_range(layout.week_from_x(left_scene, snap=False))
        scene.ensure_week_range(layout.week_from_x(right_scene, snap=False))

    def set_selected_row(self, row_id: str | None) -> None:
        scene = self.scene()
        if scene is None:
            return
        scene.set_selected_row(row_id)
        self.viewport().update()

    def set_selected_deliverables(
        self,
        row_ids: set[str],
        *,
        active_row_id: str | None = None,
        anchor_row_id: str | None = None,
    ) -> None:
        scene = self.scene()
        if scene is None:
            return
        scene.set_selected_deliverables(
            row_ids, active_row_id=active_row_id, anchor_row_id=anchor_row_id
        )
        self.viewport().update()

    def set_focused_row(self, row_id: str | None) -> None:
        scene = self.scene()
        if scene is None:
            return
        scene.set_focused_row(row_id)
        self.viewport().update()

    def _deliverable_range_ids(self, anchor_row_id: str, row_id: str) -> set[str]:
        scene = self.scene()
        if scene is None:
            return set()
        deliverable_ids = [
            row.row_id for row in scene.layout.rows if row.kind == "deliverable"
        ]
        try:
            start_index = deliverable_ids.index(anchor_row_id)
            end_index = deliverable_ids.index(row_id)
        except ValueError:
            return {row_id}
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return set(deliverable_ids[start_index : end_index + 1])

    def _select_row_from_click(self, row_id: str | None, modifiers) -> None:
        scene = self.scene()
        if scene is None or row_id is None:
            self.set_selected_row(row_id)
            return
        row = scene.layout.row_map.get(row_id)
        if row is None or row.kind != "deliverable":
            self.set_selected_row(row_id)
            return
        if modifiers & Qt.KeyboardModifier.ShiftModifier and scene.row_selection_anchor_id:
            self.set_selected_deliverables(
                self._deliverable_range_ids(scene.row_selection_anchor_id, row_id),
                active_row_id=row_id,
                anchor_row_id=scene.row_selection_anchor_id,
            )
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            selected_ids = set(scene.selected_row_ids)
            if row_id in selected_ids:
                selected_ids.remove(row_id)
                ordered = scene.ordered_deliverable_ids(selected_ids)
                active_row_id = ordered[-1] if ordered else None
            else:
                selected_ids.add(row_id)
                active_row_id = row_id
            self.set_selected_deliverables(
                selected_ids,
                active_row_id=active_row_id,
                anchor_row_id=row_id,
            )
            return
        self.set_selected_row(row_id)

    def _prepare_row_context_selection(self, row_id: str, kind: str) -> None:
        scene = self.scene()
        if scene is None:
            return
        scene.clearSelection()
        if kind == "topic":
            self.set_selected_row(row_id)
            return
        if row_id in scene.selected_row_ids:
            self.set_selected_deliverables(
                set(scene.selected_row_ids),
                active_row_id=row_id,
                anchor_row_id=scene.row_selection_anchor_id or row_id,
            )
            return
        self.set_selected_deliverables({row_id}, active_row_id=row_id, anchor_row_id=row_id)

    def _show_context_menu(self, pos) -> None:
        scene = self.scene()
        if scene is None:
            return
        if pos.x() <= self._label_width_pixels():
            row_id = scene.layout.row_at_y(self.mapToScene(pos).y())
            row = scene.layout.row_map.get(row_id) if row_id else None
            if row and row.kind in ("topic", "deliverable"):
                self._show_row_context_menu(pos, row.row_id, row.kind)
                return
        item = self.itemAt(pos)
        dependency_edge = scene.dependency_edge_for_item(item)
        obj_item = self._object_item_from_graphics_item(item) if item else None
        if dependency_edge is not None:
            if not dependency_edge.isSelected():
                scene.clearSelection()
                dependency_edge.setSelected(True)
            obj_item = None
        elif obj_item and obj_item.data(0):
            if not obj_item.isSelected():
                scene.clearSelection()
                obj_item.setSelected(True)
        selected_ids = self.selected_object_ids()
        duplicable_ids = [
            obj_id for obj_id in selected_ids
            if scene.model.objects.get(obj_id) is not None
            and scene.model.objects[obj_id].kind not in ("link", "connector", "arrow")
        ]
        selected_dependencies = scene.selected_dependency_keys()

        menu = QMenu(self)
        insert_menu = menu.addMenu("Insert")
        can_insert = scene.edit_mode
        has_rows = bool(scene.layout.rows)
        insert_actions = {}
        insert_actions[insert_menu.addAction("Activity")] = "box"
        insert_actions[insert_menu.addAction("Milestone")] = "milestone"
        insert_actions[insert_menu.addAction("Deadline")] = "deadline"
        insert_actions[insert_menu.addAction("Event")] = "circle"
        insert_actions[insert_menu.addAction("Connector")] = "connector"
        insert_actions[insert_menu.addAction("Text Box")] = "textbox"
        for action, kind in insert_actions.items():
            if kind == "textbox":
                action.setEnabled(can_insert and scene.show_textboxes)
            elif kind in ("deadline", "connector"):
                action.setEnabled(can_insert)
            else:
                action.setEnabled(can_insert and has_rows)

        convert_actions: dict[QAction, str] = {}
        convert_obj_id = obj_item.data(0) if obj_item and obj_item.data(0) else None
        convert_row_id = None
        if convert_obj_id and not selected_dependencies:
            obj = scene.model.objects.get(convert_obj_id)
            if obj and obj.kind in {kind for kind, _ in CONVERTIBLE_OBJECT_TYPES}:
                convert_menu = menu.addMenu("Convert To")
                convert_row_id = scene.layout.row_at_y(self.mapToScene(pos).y())
                for kind, label in CONVERTIBLE_OBJECT_TYPES:
                    if kind == obj.kind:
                        continue
                    action = convert_menu.addAction(label)
                    convert_actions[action] = kind
                    if kind == "deadline":
                        action.setEnabled(scene.edit_mode)
                    else:
                        action.setEnabled(scene.edit_mode and has_rows)

        menu.addSeparator()
        bring_front = menu.addAction("Bring to Front")
        bring_forward = menu.addAction("Bring Forward")
        send_backward = menu.addAction("Send Backward")
        send_back = menu.addAction("Send to Back")
        menu.addSeparator()
        duplicate_action = menu.addAction(
            "Duplicate" if len(duplicable_ids) == 1 else "Duplicate Selection"
        )
        delete_selection = menu.addAction("Delete Selection")

        enabled = bool(selected_ids or selected_dependencies)
        delete_selection.setEnabled(can_insert and enabled)
        duplicate_action.setEnabled(can_insert and bool(duplicable_ids) and not selected_dependencies)
        ordering_enabled = bool(selected_ids) and not selected_dependencies
        bring_front.setEnabled(ordering_enabled)
        bring_forward.setEnabled(ordering_enabled)
        send_backward.setEnabled(ordering_enabled)
        send_back.setEnabled(ordering_enabled)

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if not action:
            return
        if action in insert_actions:
            self._create_from_context(insert_actions[action], pos)
            return
        if action in convert_actions:
            self._convert_object_kind(convert_obj_id, convert_actions[action], convert_row_id)
            return
        if action == delete_selection:
            self._delete_selected()
            return
        if action == duplicate_action:
            self.duplicate_selected()
            return
        if not selected_ids:
            return
        if action == bring_front:
            self.controller.reorder_objects(selected_ids, "front")
        elif action == bring_forward:
            self.controller.reorder_objects(selected_ids, "forward")
        elif action == send_backward:
            self.controller.reorder_objects(selected_ids, "backward")
        elif action == send_back:
            self.controller.reorder_objects(selected_ids, "back")

    def _show_row_context_menu(self, pos, row_id: str, kind: str) -> None:
        scene = self.scene()
        if scene is None:
            return
        self._prepare_row_context_selection(row_id, kind)

        menu = QMenu(self)
        if kind == "topic":
            topic = scene.model.get_topic(row_id)
            is_divider = bool(topic and topic.kind == "divider")
            menu.addSection("Create")
            add_deliverable_action = menu.addAction("Add Deliverable")
            add_above_action = menu.addAction("Insert Section Above")
            add_below_action = menu.addAction("Insert Section Below")
            menu.addSection("Appearance")
            edit_color_action = menu.addAction("Edit Section Color")
            apply_topic_color_action = menu.addAction("Apply Section Color to Elements")
            menu.addSection("Organize")
            move_up_action = menu.addAction("Move Section Up")
            move_down_action = menu.addAction("Move Section Down")
            menu.addSection("View")
            collapse_action = menu.addAction("Expand Section" if topic and topic.collapsed else "Collapse Section")
            focus_action = None
            indent_action = None
            outdent_action = None
            move_section_action = None
            rename_action = menu.addAction("Rename")
            remove_action = menu.addAction("Delete Section")
            if is_divider:
                for action in (add_deliverable_action, add_above_action, add_below_action,
                               apply_topic_color_action, edit_color_action, move_up_action,
                               move_down_action, collapse_action):
                    action.setVisible(False)
        else:
            edit_color_action = collapse_action = None
            apply_topic_color_action = None
            menu.addSection("Create")
            add_deliverable_action = menu.addAction("Add Above")
            add_above_action = add_deliverable_action
            add_above_action.setText("Add Deliverable Above")
            add_below_action = menu.addAction("Add Deliverable Below")
            menu.addSection("Organize")
            move_up_action = menu.addAction("Move Deliverable(s) Up")
            move_down_action = menu.addAction("Move Deliverable(s) Down")
            move_section_action = menu.addAction("Move to Section…")
            indent_action = menu.addAction("Indent")
            outdent_action = menu.addAction("Outdent")
            menu.addSection("View")
            is_focused = scene.focused_row_id == row_id
            focus_label = "Unfocus" if is_focused else "Focus on this"
            focus_action = menu.addAction(focus_label)
            menu.addSection("Edit")
            rename_action = menu.addAction("Rename Deliverable")
            remove_action = menu.addAction("Delete Deliverable(s)")

        can_edit = scene.edit_mode
        selected_deliverable_ids = scene.selected_deliverable_ids()
        if kind == "topic":
            topic_index = self.controller._topic_index(scene.model.topics, row_id)
            add_deliverable_action.setEnabled(can_edit)
            topic = scene.model.get_topic(row_id)
            topic_row_ids = {row_id} | {d.id for d in topic.deliverables} if topic else set()
            has_topic_activities = bool(topic and any(
                obj.kind in ("box", "circle", "milestone")
                and obj.row_id in topic_row_ids
                for obj in scene.model.objects.values()
            ))
            apply_topic_color_action.setEnabled(
                can_edit and topic is not None and topic.kind != "divider" and has_topic_activities
            )
            edit_color_action.setEnabled(can_edit and not is_divider)
            collapse_action.setEnabled(can_edit and not is_divider)
            add_above_action.setEnabled(can_edit)
            add_below_action.setEnabled(can_edit)
            move_up_action.setEnabled(can_edit and topic_index is not None and topic_index > 0)
            move_down_action.setEnabled(
                can_edit
                and topic_index is not None
                and topic_index < (len(scene.model.topics) - 1)
            )
        else:
            add_above_action.setEnabled(can_edit)
            add_below_action.setEnabled(can_edit)
            move_up_action.setEnabled(can_edit and bool(selected_deliverable_ids))
            move_down_action.setEnabled(can_edit and bool(selected_deliverable_ids))
            indent_action.setEnabled(can_edit and bool(selected_deliverable_ids))
            outdent_action.setEnabled(can_edit and bool(selected_deliverable_ids))
            available_sections = [
                section for section in scene.model.topics
                if section.id != scene.model.topic_for_row(row_id).id
                and section.kind != "divider"
            ] if scene.model.topic_for_row(row_id) else []
            move_section_action.setEnabled(can_edit and bool(selected_deliverable_ids) and bool(available_sections))
        rename_action.setEnabled(can_edit)
        remove_action.setEnabled(can_edit)
        if kind != "topic" and len(selected_deliverable_ids) != 1:
            rename_action.setEnabled(False)

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if not action:
            return
        if kind == "topic" and action == add_deliverable_action:
            self._add_deliverable(row_id)
            return
        if kind == "topic" and action == apply_topic_color_action:
            topic = scene.model.get_topic(row_id)
            if topic is not None:
                row_ids = {row_id} | {deliverable.id for deliverable in topic.deliverables}
                activity_ids = [
                    obj.id for obj in scene.model.objects.values()
                    if obj.kind in ("box", "circle", "milestone") and obj.row_id in row_ids
                ]
                self.controller.update_objects(
                    activity_ids,
                    {"color": topic.color},
                    "Apply Section Color to Elements",
                )
            return
        if kind == "topic" and action == edit_color_action:
            self.set_selected_row(row_id)
            # The section editor belongs to the main window; CanvasView only
            # owns row context-menu interaction.
            editor = getattr(self.window(), "edit_topic", None)
            if editor is not None:
                editor(row_id)
            return
        if kind == "topic" and action == collapse_action:
            self.controller.toggle_topic_collapsed(row_id)
            return
        if kind == "topic" and action == add_above_action:
            self._insert_topic_relative(row_id, below=False)
            return
        if kind == "topic" and action == add_below_action:
            self._insert_topic_relative(row_id, below=True)
            return
        if kind == "topic" and action == move_up_action:
            self.controller.move_topic(row_id, -1)
            return
        if kind == "topic" and action == move_down_action:
            self.controller.move_topic(row_id, 1)
            return
        if action == add_above_action:
            self._add_deliverable_relative(row_id, below=False)
            return
        if action == add_below_action:
            self._add_deliverable_relative(row_id, below=True)
            return
        if action == move_up_action:
            self.controller.move_deliverables(selected_deliverable_ids, -1)
            return
        if action == move_down_action:
            self.controller.move_deliverables(selected_deliverable_ids, 1)
            return
        if action == indent_action:
            self.controller.adjust_deliverable_indent(selected_deliverable_ids, 1)
            return
        if action == outdent_action:
            self.controller.adjust_deliverable_indent(selected_deliverable_ids, -1)
            return
        if kind != "topic" and action == move_section_action:
            source = scene.model.topic_for_row(row_id)
            sections = [
                section for section in scene.model.topics
                if section.kind != "divider" and (source is None or section.id != source.id)
            ]
            if sections:
                labels = [section.name or "Unnamed Section" for section in sections]
                choice, ok = QInputDialog.getItem(
                    self, "Move Deliverable(s) to Section", "Target Section:", labels, 0, False
                )
                if ok:
                    target = sections[labels.index(choice)]
                    ids = selected_deliverable_ids or [row_id]
                    self.controller.move_deliverables_to(ids, target.id, len(target.deliverables))
            return
        if focus_action is not None and action == focus_action:
            if scene.focused_row_id == row_id:
                self.set_focused_row(None)
            else:
                self.set_focused_row(row_id)
            return
        if action == rename_action:
            if kind == "topic":
                self._rename_topic(row_id)
            else:
                self._rename_deliverable(row_id)
        elif action == remove_action:
            if kind == "topic":
                self._remove_topic(row_id)
            else:
                self._remove_deliverables(selected_deliverable_ids)

    def _create_from_context(self, kind: str, pos) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        if kind == "textbox" and not scene.show_textboxes:
            return
        if kind not in ("textbox", "deadline", "connector") and not scene.layout.rows:
            QMessageBox.information(self, "Add Object", "Add a section or deliverable first.")
            return
        if kind in ("connector", "arrow"):
            self.activate_create_tool(kind)
            return
        scene_pos = self.mapToScene(pos)
        self._create_tool = kind
        self._create_start = scene_pos
        layout = scene.layout
        if kind in ("textbox", "deadline"):
            self._create_start_row = None
        else:
            self._create_start_row = layout.row_at_y(scene_pos.y())
        self._create_start_week = layout.week_from_x(scene_pos.x(), scene.snap_weeks)
        self._finish_create(pos)

    def _convert_object_kind(self, obj_id: str | None, new_kind: str, row_id: str | None) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        if not obj_id:
            return
        obj = scene.model.objects.get(obj_id)
        if obj is None or obj.kind == new_kind:
            return
        allowed = {kind for kind, _ in CONVERTIBLE_OBJECT_TYPES}
        if obj.kind not in allowed or new_kind not in allowed:
            return
        changes: dict[str, object] = {"kind": new_kind}
        if new_kind == "deadline":
            changes["row_id"] = CANVAS_ROW_ID
        else:
            target_row_id = obj.row_id
            if target_row_id == CANVAS_ROW_ID or target_row_id not in scene.layout.row_map:
                target_row_id = row_id
            if target_row_id is None and scene.layout.rows:
                target_row_id = scene.layout.rows[0].row_id
            if target_row_id is None:
                return
            changes["row_id"] = target_row_id
        label_map = {kind: label for kind, label in CONVERTIBLE_OBJECT_TYPES}
        description = f"Convert to {label_map.get(new_kind, new_kind)}"
        self.controller.update_object(obj_id, changes, description)

    def _add_deliverable(self, topic_id: str) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        topic = scene.model.get_topic(topic_id)
        if topic is None:
            return
        name, ok = QInputDialog.getText(
            self, "Add Deliverable", "Deliverable Name"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        self.controller.add_deliverable(topic_id, name)

    def _add_deliverable_relative(self, deliverable_id: str, *, below: bool) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        found = scene.model.find_deliverable(deliverable_id)
        if found is None:
            return
        topic, index, deliverable = found
        title = "Add Below" if below else "Add Above"
        name, ok = QInputDialog.getText(self, title, "Name")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        insert_index = index
        if below:
            insert_index = index + 1
            while insert_index < len(topic.deliverables):
                candidate = topic.deliverables[insert_index]
                if candidate.indent <= deliverable.indent:
                    break
                insert_index += 1
        self.controller.add_deliverable(
            topic.id,
            name,
            index=insert_index,
            indent=deliverable.indent,
            description="Add Deliverable",
        )

    def _insert_topic_relative(self, topic_id: str, *, below: bool) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        topic_index = self.controller._topic_index(scene.model.topics, topic_id)
        if topic_index is None:
            return
        title = "Insert Below" if below else "Insert Above"
        name, ok = QInputDialog.getText(self, title, "Section Name")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        insert_index = topic_index + 1 if below else topic_index
        topic = self.controller.add_topic(
            name,
            index=insert_index,
            description="Add Section",
        )
        if topic is not None:
            self.set_selected_row(topic.id)

    def _rename_topic(self, topic_id: str) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        topic = scene.model.get_topic(topic_id)
        if topic is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Section", "Section Name", text=topic.name
        )
        if not ok:
            return
        name = name.strip()
        if not name or name == topic.name:
            return
        new_topic = type(topic)(
            id=topic.id,
            name=name,
            color=topic.color,
            collapsed=topic.collapsed,
            deliverables=topic.deliverables,
        )
        self.controller.update_topic(new_topic)

    def _rename_deliverable(self, deliverable_id: str) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        found = scene.model.find_deliverable(deliverable_id)
        if found is None:
            return
        _topic, _index, deliverable = found
        name, ok = QInputDialog.getText(self, "Rename", "Name", text=deliverable.name)
        if not ok:
            return
        name = name.strip()
        if not name or name == deliverable.name:
            return
        new_deliverable = replace(deliverable, name=name)
        self.controller.update_deliverable(new_deliverable)

    def _remove_deliverables(self, deliverable_ids: list[str]) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        selected_ids = list(dict.fromkeys(deliverable_ids))
        if not selected_ids:
            return
        affected_objects = self._objects_for_rows(set(selected_ids))
        detail = ""
        if affected_objects:
            detail = f"\n\nThis will remove {len(affected_objects)} related object(s) on the canvas."
        if len(selected_ids) == 1:
            found = scene.model.find_deliverable(selected_ids[0])
            if found is None:
                return
            topic, _index, deliverable = found
            message = f"Delete deliverable '{deliverable.name}' from '{topic.name}'?{detail}"
        else:
            message = f"Delete {len(selected_ids)} selected deliverables?{detail}"
        if QMessageBox.question(
            self,
            "Confirm Delete",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self.controller.remove_deliverables(selected_ids)

    def _remove_topic(self, topic_id: str) -> None:
        scene = self.scene()
        if scene is None or not scene.edit_mode:
            return
        topic = scene.model.get_topic(topic_id)
        if topic is None:
            return
        deliverable_count = len(topic.deliverables)
        row_ids = {topic.id, *[d.id for d in topic.deliverables]}
        affected_objects = self._objects_for_rows(row_ids)
        detail_parts = []
        if deliverable_count:
            detail_parts.append(f"{deliverable_count} deliverable(s)")
        if affected_objects:
            detail_parts.append(f"{len(affected_objects)} object(s)")
        detail = ""
        if detail_parts:
            detail = "\n\nThis will remove " + " and ".join(detail_parts) + "."
        message = f"Remove section '{topic.name}'?{detail}"
        if QMessageBox.question(
            self,
            "Confirm Remove Section",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self.controller.remove_topic(topic_id)

    def _objects_for_rows(self, row_ids: set[str]) -> list:
        scene = self.scene()
        if scene is None:
            return []
        return self.controller.objects_for_rows(row_ids)

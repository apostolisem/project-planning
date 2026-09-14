from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QLineF
from datetime import date, timedelta
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsDropShadowEffect,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QToolTip,
    QStyle,
    QStyleOptionGraphicsItem,
)

from .constants import (
    CONNECTOR_DEFAULT_COLOR,
    HEADER_YEAR_HEIGHT,
    LINK_ARROW_SIZE,
    LINK_LINE_COLOR,
    LINK_LINE_WIDTH,
    RAG_AMBER_COLOR,
    RAG_GREEN_COLOR,
    TEXT_SIZE_MAX,
    TEXT_SIZE_MIN,
    TEXT_SIZE_STEP,
    TEXTBOX_ANCHOR_MARGIN,
    TEXTBOX_MIN_HEIGHT,
    TEXTBOX_MIN_WIDTH,
)
from .layout import row_item_height, row_item_size
from .text_shortcuts import apply_text_action, extract_text_payload, text_shortcut_action
from .theme import (
    CYAN,
    BORDER,
    adaptive_text_color,
    composite_color,
    tokens as theme_tokens,
)

MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _iso_week_month(layout, base_year: int, week_index: int) -> tuple[int, int]:
    week_start = layout.week_index_to_date(base_year, week_index)
    anchor_day = week_start + timedelta(days=3)
    return anchor_day.year, anchor_day.month


def _draw_arrowhead(
    painter: QPainter, start: QPointF, end: QPointF, color: QColor, size: float, *, outline: bool
) -> None:
    angle = end - start
    length = (angle.x() ** 2 + angle.y() ** 2) ** 0.5
    if length == 0:
        return
    ux = angle.x() / length
    uy = angle.y() / length
    left = QPointF(end.x() - ux * size - uy * (size / 2.0), end.y() - uy * size + ux * (size / 2.0))
    right = QPointF(end.x() - ux * size + uy * (size / 2.0), end.y() - uy * size - ux * (size / 2.0))
    painter.save()
    painter.setBrush(color)
    if not outline:
        painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon(QPolygonF([end, left, right]))
    painter.restore()


def _normalize_arrow_direction(value: object) -> str:
    direction = str(value or "none").strip().lower()
    if direction not in ("none", "left", "right"):
        return "none"
    return direction


def _arrow_tip_depth(width: float, height: float) -> float:
    depth = max(8.0, height * 0.35)
    return min(depth, max(1.0, width * 0.45))


def _textbox_anchor_point(obj, side: str | None, offset: float | None) -> QPointF:
    width = obj.width if obj.width is not None else TEXTBOX_MIN_WIDTH
    height = obj.height if obj.height is not None else TEXTBOX_MIN_HEIGHT
    x = obj.x if obj.x is not None else 0.0
    y = obj.y if obj.y is not None else 0.0
    offset_value = float(offset or 0.5)
    if offset_value < 0.0:
        offset_value = 0.0
    if offset_value > 1.0:
        offset_value = 1.0
    if side == "left":
        return QPointF(x, y + (height * offset_value))
    if side == "top":
        return QPointF(x + (width * offset_value), y)
    if side == "bottom":
        return QPointF(x + (width * offset_value), y + height)
    return QPointF(x + width, y + (height * offset_value))


def _object_center_for_link(obj, layout) -> QPointF | None:
    if obj.kind == "textbox":
        width = obj.width if obj.width is not None else TEXTBOX_MIN_WIDTH
        height = obj.height if obj.height is not None else TEXTBOX_MIN_HEIGHT
        x = obj.x if obj.x is not None else 0.0
        y = obj.y if obj.y is not None else 0.0
        return QPointF(x + (width / 2.0), y + (height / 2.0))
    if obj.kind == "milestone":
        if obj.row_id not in layout.row_map:
            return None
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        center_x = layout.week_right_x(obj.end_week)
        center_y = layout.row_center_y(obj.row_id) + layout.object_vertical_offset(obj.id)
        return QPointF(center_x, center_y)
    if obj.kind == "circle":
        if obj.row_id not in layout.row_map:
            return None
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        center_x = layout.week_center_x(obj.start_week)
        center_y = layout.row_center_y(obj.row_id) + layout.object_vertical_offset(obj.id)
        return QPointF(center_x, center_y)
    if obj.kind == "deadline":
        center_x = layout.week_right_x(obj.end_week)
        center_y = layout.header_height + (layout.total_height / 2.0)
        return QPointF(center_x, center_y)
    if obj.kind in ("connector", "arrow") and not (
        obj.connector_source_id and obj.connector_target_id
    ):
        if obj.row_id not in layout.row_map:
            return None
        target_row = obj.target_row_id or obj.row_id
        if target_row not in layout.row_map:
            return None
        start_x = layout.week_center_x(obj.start_week)
        start_y = layout.row_center_y(obj.row_id)
        target_week = obj.target_week if obj.target_week is not None else obj.end_week
        end_x = layout.week_center_x(target_week)
        end_y = layout.row_center_y(target_row)
        return QPointF((start_x + end_x) / 2.0, (start_y + end_y) / 2.0)
    if obj.row_id not in layout.row_map:
        return None
    row_height = layout.row_height(obj.row_id)
    height = layout.object_item_height(obj.id, row_height, obj.size)
    width = max(1, obj.end_week - obj.start_week + 1) * layout.week_width
    x = layout.week_left_x(obj.start_week)
    y = layout.row_top_y(obj.row_id) + ((row_height - height) / 2.0) + layout.object_vertical_offset(obj.id)
    return QPointF(x + (width / 2.0), y + (height / 2.0))


def _object_bounds_for_connector(obj, layout) -> QRectF | None:
    if obj.kind in ("link", "connector"):
        return None
    if obj.kind == "textbox":
        width = obj.width if obj.width is not None else TEXTBOX_MIN_WIDTH
        height = obj.height if obj.height is not None else TEXTBOX_MIN_HEIGHT
        x = obj.x if obj.x is not None else 0.0
        y = obj.y if obj.y is not None else 0.0
        return QRectF(x, y, width, height)
    if obj.kind == "milestone":
        if obj.row_id not in layout.row_map:
            return None
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        half = size / 2.0
        center_x = layout.week_right_x(obj.end_week)
        center_y = layout.row_center_y(obj.row_id) + layout.object_vertical_offset(obj.id)
        return QRectF(center_x - half, center_y - half, size, size)
    if obj.kind == "circle":
        if obj.row_id not in layout.row_map:
            return None
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        half = size / 2.0
        center_x = layout.week_center_x(obj.start_week)
        center_y = layout.row_center_y(obj.row_id) + layout.object_vertical_offset(obj.id)
        return QRectF(center_x - half, center_y - half, size, size)
    if obj.kind == "deadline":
        center_x = layout.week_right_x(obj.end_week)
        line_height = layout.header_height + layout.total_height
        width = max(1.0, float(obj.size))
        return QRectF(center_x - (width / 2.0), 0.0, width, line_height)
    if obj.kind == "arrow":
        if obj.row_id not in layout.row_map:
            return None
        target_row = obj.target_row_id or obj.row_id
        if target_row not in layout.row_map:
            return None
        start_x = layout.week_center_x(obj.start_week)
        start_y = layout.row_center_y(obj.row_id)
        target_week = obj.target_week if obj.target_week is not None else obj.end_week
        end_x = layout.week_center_x(target_week)
        end_y = layout.row_center_y(target_row)
        left = min(start_x, end_x)
        top = min(start_y, end_y)
        width = max(1.0, abs(end_x - start_x))
        height = max(1.0, abs(end_y - start_y))
        return QRectF(left, top, width, height)
    if obj.row_id not in layout.row_map:
        return None
    row_height = layout.row_height(obj.row_id)
    height = layout.object_item_height(obj.id, row_height, obj.size)
    width = max(1, obj.end_week - obj.start_week + 1) * layout.week_width
    x = layout.week_left_x(obj.start_week)
    y = layout.row_top_y(obj.row_id) + ((row_height - height) / 2.0) + layout.object_vertical_offset(obj.id)
    return QRectF(x, y, width, height)


def _anchor_point_for_bounds(
    bounds: QRectF,
    side: str | None,
    offset: float | None,
    *,
    arrow_direction: str = "none",
) -> QPointF:
    offset_value = float(offset or 0.5)
    if offset_value < 0.0:
        offset_value = 0.0
    if offset_value > 1.0:
        offset_value = 1.0
    width = max(1.0, bounds.width())
    height = max(1.0, bounds.height())
    left = bounds.left()
    top = bounds.top()
    right = bounds.right()
    bottom = bounds.bottom()
    direction = _normalize_arrow_direction(arrow_direction)
    depth = _arrow_tip_depth(width, height)
    edge_factor = abs((offset_value * 2.0) - 1.0)
    center_factor = 1.0 - edge_factor
    if side == "left":
        x = left
        if direction == "left":
            x = left + (depth * edge_factor)
        elif direction == "right":
            x = left + (depth * center_factor)
        return QPointF(x, top + (height * offset_value))
    if side == "top":
        return QPointF(left + (width * offset_value), top)
    if side == "bottom":
        return QPointF(left + (width * offset_value), bottom)
    x = right
    if direction == "right":
        x = right - (depth * edge_factor)
    elif direction == "left":
        x = right - (depth * center_factor)
    return QPointF(x, top + (height * offset_value))


LINK_BOW_SPACING = 26.0


def _mid_anchor_point(bounds: QRectF, other_center: QPointF) -> QPointF:
    """Edge midpoint on the side facing `other_center` (the item's centreline)."""
    center = bounds.center()
    if abs(other_center.x() - center.x()) >= abs(other_center.y() - center.y()):
        x = bounds.right() if other_center.x() >= center.x() else bounds.left()
        return QPointF(x, center.y())
    y = bounds.bottom() if other_center.y() >= center.y() else bounds.top()
    return QPointF(center.x(), y)


def _opposite_link_side(side: str | None) -> str | None:
    return {
        "left": "right",
        "right": "left",
        "top": "bottom",
        "bottom": "top",
    }.get(side)


def _side_anchor_point(bounds: QRectF, side: str) -> QPointF:
    if side == "left":
        return QPointF(bounds.left(), bounds.center().y())
    if side == "right":
        return QPointF(bounds.right(), bounds.center().y())
    if side == "top":
        return QPointF(bounds.center().x(), bounds.top())
    return QPointF(bounds.center().x(), bounds.bottom())


def _smooth_curve(start: QPointF, end: QPointF, bow: float = 0.0) -> QPainterPath:
    """Smooth cubic connector between midpoint anchors.

    `bow` offsets both control points perpendicular to the straight line so
    parallel links between the same item pair fan out instead of overlapping.
    """
    path = QPainterPath(start)
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    if abs(dx) >= abs(dy):
        span = max(36.0, abs(dx) * 0.5)
        sign = 1.0 if dx >= 0 else -1.0
        c1 = QPointF(start.x() + span * sign, start.y() + bow)
        c2 = QPointF(end.x() - span * sign, end.y() + bow)
    else:
        span = max(28.0, abs(dy) * 0.5)
        sign = 1.0 if dy >= 0 else -1.0
        c1 = QPointF(start.x() + bow, start.y() + span * sign)
        c2 = QPointF(end.x() + bow, end.y() - span * sign)
    path.cubicTo(c1, c2, end)
    return path


def _link_endpoints(obj) -> tuple[str | None, str | None]:
    return (
        obj.connector_source_id or obj.link_source_id,
        obj.connector_target_id or obj.link_target_id,
    )


def _parallel_bow(model, obj) -> float:
    """Deterministic perpendicular offset for links sharing the same pair.

    All connectors/arrows/textbox-links between the same unordered pair are
    ordered by id; each gets a distinct offset so their midpoint anchors stay
    aligned while the curves no longer overlap.
    """
    source_id, target_id = _link_endpoints(obj)
    if not source_id or not target_id or model is None:
        return 0.0
    key = tuple(sorted((source_id, target_id)))
    peer_ids = []
    for other in model.objects.values():
        if other.kind not in ("connector", "arrow", "link"):
            continue
        osource, otarget = _link_endpoints(other)
        if not osource or not otarget:
            continue
        if tuple(sorted((osource, otarget))) == key:
            peer_ids.append(other.id)
    peer_ids.sort()
    if not peer_ids:
        return 0.0
    try:
        index = peer_ids.index(obj.id)
    except ValueError:
        index = 0
    return (index - (len(peer_ids) - 1) / 2.0) * LINK_BOW_SPACING


def _path_tangent(path: QPainterPath, at_start: bool) -> tuple[QPointF, QPointF]:
    """Return (tip, previous) points for arrowhead orientation on curves."""
    if at_start:
        return path.pointAtPercent(0.0), path.pointAtPercent(0.02)
    return path.pointAtPercent(1.0), path.pointAtPercent(0.98)


def _apply_text_alignment(text_item: QGraphicsTextItem, align: str) -> None:
    option = QTextOption()
    if align == "left":
        option.setAlignment(Qt.AlignmentFlag.AlignLeft)
    elif align == "right":
        option.setAlignment(Qt.AlignmentFlag.AlignRight)
    else:
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    text_item.document().setDefaultTextOption(option)


def _position_point_label(
    text_item: QGraphicsTextItem,
    symbol_rect: QRectF,
    align: str,
    gap: float = 4.0,
) -> None:
    """Place a single-line label relative to a milestone or circle symbol."""
    text_item.setTextWidth(-1)
    label_rect = text_item.boundingRect()
    if align == "left":
        label_x = symbol_rect.left() - gap - label_rect.width()
    elif align == "right":
        label_x = symbol_rect.right() + gap
    else:
        label_x = symbol_rect.center().x() - (label_rect.width() / 2.0)
    label_y = symbol_rect.center().y() - (label_rect.height() / 2.0)
    text_item.setPos(label_x, label_y)


def _apply_text_color_override(text_item: QGraphicsTextItem, color: QColor) -> None:
    doc = text_item.document()
    if doc is None:
        return
    cursor = QTextCursor(doc)
    cursor.select(QTextCursor.SelectionType.Document)
    fmt = QTextCharFormat()
    fmt.setForeground(QBrush(color))
    cursor.mergeCharFormat(fmt)


def _apply_adaptive_text(
    text_item: QGraphicsTextItem,
    backgrounds,
    *,
    halo: bool,
) -> QColor:
    foreground = adaptive_text_color(backgrounds)
    text_item.setDefaultTextColor(foreground)
    _apply_text_color_override(text_item, foreground)
    if halo:
        effect = text_item.graphicsEffect()
        if not isinstance(effect, QGraphicsDropShadowEffect):
            effect = QGraphicsDropShadowEffect()
            text_item.setGraphicsEffect(effect)
        halo_color = adaptive_text_color([foreground])
        halo_color.setAlpha(210)
        effect.setColor(halo_color)
        effect.setBlurRadius(2.0)
        effect.setOffset(0.0, 0.0)
        effect.setEnabled(True)
    elif text_item.graphicsEffect() is not None:
        text_item.setGraphicsEffect(None)
    return foreground


def _apply_colored_text_with_halo(
    text_item: QGraphicsTextItem, color: QColor
) -> QColor:
    foreground = QColor(color)
    text_item.setDefaultTextColor(foreground)
    _apply_text_color_override(text_item, foreground)
    effect = text_item.graphicsEffect()
    if not isinstance(effect, QGraphicsDropShadowEffect):
        effect = QGraphicsDropShadowEffect()
        text_item.setGraphicsEffect(effect)
    halo_color = adaptive_text_color([foreground])
    halo_color.setAlpha(210)
    effect.setColor(halo_color)
    effect.setBlurRadius(2.0)
    effect.setOffset(0.0, 0.0)
    effect.setEnabled(True)
    return foreground


def _canvas_surface(item: QGraphicsTextItem) -> QColor:
    scene = item.scene()
    dark = bool(getattr(scene, 'dark_mode', False)) if scene else False
    return QColor(theme_tokens(dark)['card'])


def _set_text_content(text_item: QGraphicsTextItem, obj) -> None:
    if obj.text_html:
        text_item.setHtml(obj.text_html)
    else:
        text_item.setPlainText(obj.text)
    text_item.document().setDefaultFont(text_item.font())


def _active_create_tool(scene) -> str | None:
    if scene is None:
        return None
    views = scene.views()
    if not views:
        return None
    return getattr(views[0], "_create_tool", None)


class InlineTextItem(QGraphicsTextItem):
    def __init__(self, parent, object_id: str, allow_newlines: bool) -> None:
        super().__init__(parent)
        self._object_id = object_id
        self._allow_newlines = allow_newlines
        self._editing = False
        self._original_text = ""
        self._original_html = None
        self._original_font = None
        self._parent_movable = False
        self._cursor_kick_attempts = 0
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsFocusable, True)

    def start_edit(self) -> None:
        scene = self.scene()
        if scene is None or not getattr(scene, "edit_mode", True):
            return
        views = scene.views()
        if views:
            begin_edit = getattr(views[0], "begin_inline_edit", None)
            if callable(begin_edit) and begin_edit(self):
                return
        if self._editing:
            return
        self._editing = True
        self._original_font = QFont(self.font())
        self._original_text, self._original_html = extract_text_payload(
            self.document(), self._original_font
        )
        parent = self.parentItem()
        if parent is not None:
            self._parent_movable = bool(parent.flags() & parent.GraphicsItemFlag.ItemIsMovable)
            parent.setFlag(parent.GraphicsItemFlag.ItemIsMovable, False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        scene.setFocusItem(self)
        views = scene.views()
        if views:
            views[0].setFocus(Qt.FocusReason.OtherFocusReason)
        if QApplication.cursorFlashTime() <= 0:
            QApplication.setCursorFlashTime(1000)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.update()
        self._cursor_kick_attempts = 0
        QTimer.singleShot(0, self._ensure_cursor_visible)

    def paint(self, painter, option, widget=None) -> None:
        painter.save()
        parent = self.parentItem()
        scene = self.scene()
        obj = scene.model.objects.get(self._object_id) if scene and hasattr(scene, 'model') else None
        if obj and obj.kind == 'box' and parent is not None and not self._editing:
            painter.setClipRect(parent.rect().translated(-self.pos()), Qt.ClipOperation.IntersectClip)
        if option is not None:
            opt = QStyleOptionGraphicsItem(option)
            opt.state &= ~(
                QStyle.StateFlag.State_Selected
                | QStyle.StateFlag.State_HasFocus
            )
            super().paint(painter, opt, widget)
        else:
            super().paint(painter, option, widget)
        painter.restore()

    def _ensure_cursor_visible(self) -> None:
        if not self._editing:
            return
        scene = self.scene()
        if scene is None:
            return
        self._cursor_kick_attempts += 1
        views = scene.views()
        if views:
            views[0].setFocus(Qt.FocusReason.OtherFocusReason)
        if scene.focusItem() is not self:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            scene.setFocusItem(self)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        if self.textInteractionFlags() != Qt.TextInteractionFlag.TextEditorInteraction:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setTextCursor(self.textCursor())
        doc = self.document()
        if doc is not None:
            doc.markContentsDirty(0, max(1, doc.characterCount()))
        self.update()
        if self._cursor_kick_attempts < 4:
            QTimer.singleShot(60 * self._cursor_kick_attempts, self._ensure_cursor_visible)


    def _finish_edit(self, accept: bool) -> None:
        if not self._editing:
            return
        self._editing = False
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.unsetCursor()
        self.clearFocus()
        parent = self.parentItem()
        if parent is not None and self._parent_movable:
            parent.setFlag(parent.GraphicsItemFlag.ItemIsMovable, True)
        if not accept:
            if self._original_html:
                self.setHtml(self._original_html)
            else:
                self.setPlainText(self._original_text)
            if self._original_font is not None:
                self.setFont(self._original_font)
            self.document().setDefaultFont(self.font())
            return
        base_font = self._original_font or self.font()
        new_text, new_html = extract_text_payload(self.document(), base_font)
        if new_text == self._original_text and new_html == self._original_html:
            return
        scene = self.scene()
        if scene and hasattr(scene, "commit_object_change"):
            scene.commit_object_change(
                self._object_id, {"text": new_text, "text_html": new_html}, "Edit Text"
            )
        if self._original_font is not None:
            self.setFont(self._original_font)

    def focusOutEvent(self, event) -> None:
        self._finish_edit(True)
        super().focusOutEvent(event)

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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._allow_newlines and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                super().keyPressEvent(event)
                return
            self._finish_edit(True)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._finish_edit(False)
            event.accept()
            return
        super().keyPressEvent(event)


class GridItem(QGraphicsObject):
    def __init__(self, scene_ref) -> None:
        super().__init__()
        self.scene_ref = scene_ref
        self.setZValue(-1000)
        self._rect = QRectF()
        self._hover_week: int | None = None
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        return QRectF(self._rect)

    def set_rect(self, rect: QRectF) -> None:
        if rect == self._rect:
            return
        self.prepareGeometryChange()
        self._rect = QRectF(rect)

    def _week_for_hover_pos(self, pos: QPointF) -> int | None:
        scene = self.scene_ref
        layout = scene.layout
        week_y = (
            scene.header_year_height
            + scene.header_quarter_height
            + scene.header_month_height
        )
        if not (week_y <= pos.y() < (week_y + scene.header_week_height)):
            return None
        if pos.x() < layout.label_width:
            return None
        return layout.week_from_x(pos.x(), snap=False)

    def _clear_week_tooltip(self) -> None:
        if self._hover_week is None:
            return
        self._hover_week = None
        QToolTip.hideText()

    def hoverMoveEvent(self, event) -> None:
        week = self._week_for_hover_pos(event.pos())
        if week is None:
            self._clear_week_tooltip()
            super().hoverMoveEvent(event)
            return
        if week != self._hover_week:
            self._hover_week = week
            week_start = self.scene_ref.layout.week_index_to_date(
                self.scene_ref.model.year, week
            )
            QToolTip.showText(event.screenPos(), week_start.isoformat())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._clear_week_tooltip()
        super().hoverLeaveEvent(event)

    @staticmethod
    def _aligned_text_bounds(
        font: QFont, text: str, target: QRectF, *, centered: bool
    ) -> QRectF:
        """Return the actual single-line glyph area used for overlap checks."""
        metrics = QFontMetricsF(font)
        width = metrics.horizontalAdvance(text)
        height = metrics.height()
        x = target.center().x() - (width / 2.0) if centered else target.left()
        y = target.center().y() - (height / 2.0)
        return QRectF(x, y, width, height)

    @staticmethod
    def _year_label_color(
        label_bounds: QRectF,
        foreground_bounds: list[QRectF],
        normal: QColor,
        muted: QColor,
    ) -> QColor:
        if any(label_bounds.intersects(bounds) for bounds in foreground_bounds):
            faded = QColor(muted)
            faded.setAlphaF(0.32)
            return faded
        return QColor(normal)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        scene = self.scene_ref
        layout = scene.layout
        model = scene.model
        rect = option.exposedRect if option else self.boundingRect()

        dark = getattr(scene, "dark_mode", False)
        t = theme_tokens(dark)
        surface = QColor(t['card'])
        header_fill = QColor(t['soft'])
        band_a = QColor(t['soft'])
        band_b = QColor(t['hover'])
        grid_pen = QColor(t['grid'])
        text_color = QColor(t['text'])
        current_week_fill = QColor(t['cyan'])
        current_week_fill.setAlpha(55 if dark else 38)
        boundary_pen = QColor(t['border'])
        today_color = QColor(t['cyan'])

        painter.fillRect(rect, surface)

        header_rect = QRectF(rect.left(), 0, rect.width(), layout.header_height)
        painter.fillRect(header_rect, header_fill)

        current_week_x: float | None = None
        if scene.show_current_week:
            today = date.today()
            iso_year, iso_week, _ = today.isocalendar()
            base_week = layout.week_index_for_iso_year(model.year, iso_year)
            current_week = base_week + (iso_week - 1)
            current_week_x = layout.week_left_x(current_week)
            current_week_rect = QRectF(
                current_week_x, rect.top(), layout.week_width, rect.height()
            )
            painter.fillRect(current_week_rect, current_week_fill)

        pen_grid = QPen(grid_pen)
        pen_grid.setWidth(1)
        painter.setPen(pen_grid)

        focused_row_id = getattr(scene, "focused_row_id", None)
        if focused_row_id and focused_row_id in layout.row_map:
            row = layout.row_map[focused_row_id]
            row_top = layout.header_height + row.y
            row_height = row.height
            focus_rect = QRectF(rect.left(), row_top, rect.width(), row_height)
            focus_fill = QColor(t['warning'])
            focus_fill.setAlpha(48 if dark else 28)
            painter.fillRect(focus_rect, focus_fill)

        # Vertical week lines
        left_week = layout.week_from_x(rect.left(), snap=False) - 1
        right_week = layout.week_from_x(rect.right(), snap=False) + 1
        for week in range(left_week, right_week + 1):
            if week == layout.origin_week:
                continue
            x = layout.week_left_x(week)
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

        # Horizontal row lines
        painter.drawLine(int(rect.left()), int(layout.header_height), int(rect.right()), int(layout.header_height))
        row_y_min = rect.top() - layout.header_height
        row_y_max = rect.bottom() - layout.header_height
        start_index, end_index = layout.row_index_range(row_y_min, row_y_max)
        for row in layout.rows[start_index:end_index]:
            y = layout.header_height + row.y + row.height
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        # Header labels and bands
        painter.setPen(QPen(text_color))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)

        foreground_text_bounds = []
        for obj_id, item in scene.items_by_id.items():
            obj = model.objects.get(obj_id)
            text_item = getattr(item, 'text_item', None)
            if (
                obj is not None
                and obj.kind == 'deadline'
                and text_item is not None
                and text_item.isVisible()
            ):
                foreground_text_bounds.append(text_item.sceneBoundingRect())

        now_rect = None
        now_font = None
        today_text_bounds = None
        if current_week_x is not None:
            now_rect = QRectF(
                current_week_x, 0, layout.week_width, scene.header_year_height
            )
            now_font = QFont(font)
            max_label_width = max(0.0, now_rect.width() - 4.0)
            if max_label_width > 0.0:
                min_point_size = 6.0
                point_size = now_font.pointSizeF()
                if point_size <= 0.0:
                    point_size = 10.0
                    now_font.setPointSizeF(point_size)
                metrics = QFontMetricsF(now_font)
                while (
                    metrics.horizontalAdvance("TODAY") > max_label_width
                    and point_size > min_point_size
                ):
                    point_size = max(min_point_size, point_size - 0.5)
                    now_font.setPointSizeF(point_size)
                    metrics = QFontMetricsF(now_font)
            today_text_bounds = self._aligned_text_bounds(
                now_font, "TODAY", now_rect, centered=True
            )
            foreground_text_bounds.append(today_text_bounds)

        left_year, _ = layout.week_index_to_year_week(model.year, left_week)
        right_year, _ = layout.week_index_to_year_week(model.year, right_week)
        quarter_y = scene.header_year_height
        year_index = 0
        for year in range(left_year, right_year + 1):
            year_weeks = layout.weeks_in_year(year)
            year_week = layout.week_index_for_iso_year(model.year, year)
            year_rect = QRectF(
                layout.week_left_x(year_week),
                0,
                layout.week_width * year_weeks,
                scene.header_year_height,
            )
            year_fill = band_a if year_index % 2 == 0 else band_b
            painter.fillRect(year_rect, year_fill)

            visible_year = year_rect.intersected(rect)
            if visible_year.width() > layout.week_width * 2:
                week_label = "week" if year_weeks == 1 else "weeks"
                year_label = f"{year} ({year_weeks} {week_label})"
                label_rect = QRectF(
                    visible_year.left() + 4,
                    year_rect.top(),
                    visible_year.width() - 8,
                    year_rect.height(),
                )
                label_bounds = self._aligned_text_bounds(
                    font, year_label, label_rect, centered=False
                )
                painter.setPen(QPen(self._year_label_color(
                    label_bounds,
                    foreground_text_bounds,
                    text_color,
                    QColor(t['muted']),
                )))
                painter.drawText(
                    label_rect,
                    Qt.AlignmentFlag.AlignVCenter,
                    year_label,
                )
                painter.setPen(QPen(text_color))

            year_short = year % 100
            for q in range(4):
                quarter_offset = q * 13
                if quarter_offset >= year_weeks:
                    break
                quarter_length = min(13, year_weeks - quarter_offset)
                quarter_week = year_week + quarter_offset
                quarter_rect = QRectF(
                    layout.week_left_x(quarter_week),
                    quarter_y,
                    layout.week_width * quarter_length,
                    scene.header_quarter_height,
                )
                quarter_fill = band_a if q % 2 == 0 else band_b
                painter.fillRect(quarter_rect, quarter_fill)

                visible_quarter = quarter_rect.intersected(rect)
                if visible_quarter.width() > layout.week_width * 2:
                    label_rect = QRectF(
                        visible_quarter.left() + 4,
                        quarter_rect.top(),
                        visible_quarter.width() - 8,
                        quarter_rect.height(),
                    )
                    painter.drawText(
                        label_rect,
                        Qt.AlignmentFlag.AlignVCenter,
                        f"{year_short:02d}Q{q + 1}",
                    )
            year_index += 1

        font.setBold(False)
        painter.setFont(font)

        # Months
        month_y = scene.header_year_height + scene.header_quarter_height
        month_height = scene.header_month_height
        month_segments: list[tuple[int, int, int]] = []
        current_month = None
        segment_start = left_week
        for week in range(left_week, right_week + 1):
            month_key = _iso_week_month(layout, model.year, week)
            if current_month is None:
                current_month = month_key
                segment_start = week
                continue
            if month_key != current_month:
                month_segments.append((segment_start, week - 1, current_month[1]))
                segment_start = week
                current_month = month_key
        if current_month is not None:
            month_segments.append((segment_start, right_week, current_month[1]))

        text_pen = QPen(text_color)
        for index, (start_week, end_week, month_index) in enumerate(month_segments):
            month_rect = QRectF(
                layout.week_left_x(start_week),
                month_y,
                layout.week_width * (end_week - start_week + 1),
                month_height,
            )
            month_fill = band_a if index % 2 == 0 else band_b
            painter.fillRect(month_rect, month_fill)
            if index > 0:
                painter.setPen(pen_grid)
                boundary_x = layout.week_left_x(start_week)
                painter.drawLine(
                    int(boundary_x),
                    int(month_y),
                    int(boundary_x),
                    int(month_y + month_height),
                )
            painter.setPen(text_pen)
            visible_month = month_rect.intersected(rect)
            if visible_month.width() > layout.week_width * 0.6:
                label_rect = QRectF(
                    visible_month.left(),
                    month_rect.top(),
                    visible_month.width(),
                    month_rect.height(),
                )
                painter.drawText(
                    label_rect,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter,
                    MONTH_NAMES[month_index - 1],
                )

        # Weeks
        week_y = scene.header_year_height + scene.header_quarter_height + month_height
        for week in range(left_week, right_week + 1):
            _, week_in_year = layout.week_index_to_year_week(model.year, week)
            x = layout.week_left_x(week)
            rect_wk = QRectF(x, week_y, layout.week_width, scene.header_week_height)
            painter.drawText(rect_wk, Qt.AlignmentFlag.AlignCenter, f"wk{week_in_year:02d}")

        # Emphasize quarter/year boundaries
        pen_quarter = QPen(boundary_pen)
        pen_quarter.setWidth(1)
        pen_year = QPen(boundary_pen)
        pen_year.setWidth(2)
        for year in range(left_year, right_year + 1):
            year_week = layout.week_index_for_iso_year(model.year, year)
            year_weeks = layout.weeks_in_year(year)
            x_year = layout.week_left_x(year_week)
            painter.setPen(pen_year)
            painter.drawLine(int(x_year), int(rect.top()), int(x_year), int(rect.bottom()))
            for q in range(1, 4):
                quarter_offset = q * 13
                if quarter_offset >= year_weeks:
                    break
                quarter_week = year_week + quarter_offset
                x_quarter = layout.week_left_x(quarter_week)
                painter.setPen(pen_quarter)
                painter.drawLine(int(x_quarter), int(rect.top()), int(x_quarter), int(rect.bottom()))

        if now_rect is not None and now_font is not None:
            painter.setFont(now_font)
            painter.setPen(QPen(today_color))
            painter.drawText(now_rect, Qt.AlignmentFlag.AlignCenter, "TODAY")

def _visual_state(scene, object_id: str) -> str:
    """Return 'normal' | 'related' | 'dimmed' for an object in a scene."""
    if scene is None:
        return "normal"
    if object_id in getattr(scene, "dimmed_ids", ()):
        return "dimmed"
    if object_id in getattr(scene, "related_ids", ()):
        return "related"
    return "normal"


class BoxItem(QGraphicsRectItem):
    def __init__(self, object_id: str) -> None:
        super().__init__()
        self.object_id = object_id
        self._hovered = False
        self._drag_start = None
        self._drag_start_pos = None
        self._resizing = False
        self._resize_edge = None
        self._resize_start_pos = None
        self._resize_start_rect = None
        self._resize_start_obj = None
        self._resize_offset = 0.0
        self._arrow_direction = "none"
        self.text_item = InlineTextItem(self, object_id, allow_newlines=True)
        self._risk_badge = QGraphicsEllipseItem(self)
        self._risk_badge.setVisible(False)
        self._risk_badge.setBrush(QColor(255, 193, 7))
        badge_pen = QPen(QColor(80, 80, 80))
        badge_pen.setWidthF(0.6)
        badge_pen.setCosmetic(True)
        self._risk_badge.setPen(badge_pen)
        self._risk_badge.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)

    def sync_from_model(self, obj, layout, show_missing_scope: bool | None = None) -> None:
        self.setZValue(obj.z_index)
        self._arrow_direction = _normalize_arrow_direction(
            getattr(obj, "arrow_direction", "none")
        )
        row_height = layout.row_height(obj.row_id)
        height = layout.object_item_height(obj.id, row_height, obj.size)
        width = max(1, obj.end_week - obj.start_week + 1) * layout.week_width
        x = layout.week_left_x(obj.start_week)
        y = (
            layout.row_top_y(obj.row_id)
            + ((row_height - height) / 2.0)
            + layout.object_vertical_offset(obj.id)
        )
        self.setRect(0, 0, width, height)
        self.setPos(x, y)
        self.setBrush(QColor(obj.color))
        # A restrained edge derived from the fill separates activities from
        # grid lines and the current-week band without changing their model
        # colour.
        edge = QColor(obj.color)
        edge = edge.darker(135) if edge.lightness() > 145 else edge.lighter(135)
        edge.setAlpha(220)
        activity_pen = QPen(edge)
        activity_pen.setWidthF(0.8)
        activity_pen.setCosmetic(True)
        self.setPen(activity_pen)
        _set_text_content(self.text_item, obj)
        _apply_adaptive_text(self.text_item, [QColor(obj.color)], halo=False)
        _apply_text_alignment(self.text_item, obj.text_align)
        self._update_text_layout()
        self._update_risk_badge(obj, width, height, show_missing_scope=show_missing_scope)
        self._notify_dependency_handle_geometry_changed()

    def _notify_dependency_handle_geometry_changed(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        for view in scene.views():
            layout_handles = getattr(
                view, "_layout_dependency_handles_for_item", None
            )
            if callable(layout_handles):
                layout_handles(self)

    def _arrow_edge_insets(self, width: float, height: float) -> tuple[float, float]:
        depth = _arrow_tip_depth(width, height)
        if self._arrow_direction in ("left", "right"):
            return depth, depth
        return 0.0, 0.0

    def _resize_grip_x_positions(self, scale: float) -> tuple[float, float]:
        rect = self.rect()
        width = max(0.0, rect.width())
        safe_scale = max(0.01, scale)
        screen_inset = 4.0 / safe_scale
        if self._arrow_direction == "none":
            inset = min(width / 4.0, screen_inset)
            return rect.left() + inset, rect.right() - inset

        depth = _arrow_tip_depth(width, rect.height())
        shoulder_padding = 2.0 / safe_scale
        center_x = rect.center().x()
        half_gap = min(2.0 / safe_scale, width * 0.1)
        left_x = min(
            rect.left() + depth + shoulder_padding,
            center_x - half_gap,
        )
        right_x = max(
            rect.right() - depth - shoulder_padding,
            center_x + half_gap,
        )
        return left_x, right_x

    def _shape_polygon(self) -> QPolygonF:
        rect = self.rect()
        width = rect.width()
        height = rect.height()
        if width <= 0.0 or height <= 0.0:
            return QPolygonF()
        left = rect.left()
        top = rect.top()
        right = left + width
        bottom = top + height
        middle_y = top + (height / 2.0)
        left_inset, right_inset = self._arrow_edge_insets(width, height)
        if self._arrow_direction == "left":
            return QPolygonF(
                [
                    QPointF(left + left_inset, top),
                    QPointF(right, top),
                    QPointF(right - right_inset, middle_y),
                    QPointF(right, bottom),
                    QPointF(left + left_inset, bottom),
                    QPointF(left, middle_y),
                ]
            )
        if self._arrow_direction == "right":
            return QPolygonF(
                [
                    QPointF(left, top),
                    QPointF(right - right_inset, top),
                    QPointF(right, middle_y),
                    QPointF(right - right_inset, bottom),
                    QPointF(left, bottom),
                    QPointF(left + left_inset, middle_y),
                ]
            )
        return QPolygonF(
            [
                QPointF(left, top),
                QPointF(right, top),
                QPointF(right, bottom),
                QPointF(left, bottom),
            ]
        )

    def anchor_local_point(self, side: str, offset: float) -> QPointF:
        rect = self.rect()
        return _anchor_point_for_bounds(
            rect,
            side,
            offset,
            arrow_direction=self._arrow_direction,
        )

    def _update_text_layout(self) -> None:
        rect = self.rect()
        width = rect.width()
        height = rect.height()
        left_inset, right_inset = self._arrow_edge_insets(width, height)
        left_padding = 3.0 + left_inset
        total_padding = 6.0 + left_inset + right_inset
        available = max(1.0, width - total_padding)
        self.text_item.setTextWidth(available)
        label_width = self.text_item.document().idealWidth()
        # Very short activities cannot contain a readable title.  Let the
        # natural single-line label sit just outside the bar, retaining its
        # vertical anchor and making the association obvious.
        if label_width > available + 1.0 and label_width > 0:
            self.text_item.setTextWidth(-1)
            natural = self.text_item.boundingRect()
            self.text_item.setPos(width + 4.0, (height - natural.height()) / 2.0)
        else:
            self.text_item.setTextWidth(available)
            self.text_item.setPos(left_padding, max(0.0, (height - self.text_item.boundingRect().height()) / 2.0))

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        polygon = self._shape_polygon()
        if not polygon.isEmpty():
            path.addPolygon(polygon)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        polygon = self._shape_polygon()
        if polygon.isEmpty():
            return
        painter.save()
        scene = self.scene()
        state = _visual_state(scene, self.object_id)
        pen = QPen(self.pen())
        pen.setColor(QColor(BORDER))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(self.brush())
        if self._arrow_direction == 'none':
            painter.drawRoundedRect(self.rect(), 3, 3)
        else:
            painter.drawPolygon(polygon)
        if state == "related":
            pen.setColor(QColor("#8b5cf6"))
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._arrow_direction == 'none':
                painter.drawRoundedRect(self.rect(), 3, 3)
            else:
                painter.drawPolygon(polygon)
        dependency_focus = bool(
            scene is not None
            and not getattr(scene, 'exporting', False)
            and getattr(scene, "is_dependency_hovered_focus", lambda _id: False)(self.object_id)
        )
        dependency_related = bool(
            scene is not None
            and not getattr(scene, 'exporting', False)
            and getattr(scene, "is_dependency_hovered_object", lambda _id: False)(self.object_id)
        )
        if dependency_related and not self.isSelected() and not dependency_focus:
            pen.setColor(QColor("#8b5cf6"))
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._arrow_direction == 'none':
                painter.drawRoundedRect(self.rect(), 3, 3)
            else:
                painter.drawPolygon(polygon)
        if dependency_focus and not self.isSelected():
            pen.setColor(QColor(CYAN))
            pen.setWidthF(2.6)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._arrow_direction == 'none':
                painter.drawRoundedRect(self.rect(), 3, 3)
            else:
                painter.drawPolygon(polygon)
        if not getattr(scene, 'exporting', False) and (self.isSelected() or self._hovered):
            pen.setColor(QColor(CYAN))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)
            if scene and scene.edit_mode:
                scale = max(.01, painter.transform().m11())
                grip_x_positions = self._resize_grip_x_positions(scale)
                grip_top = self.rect().height() * 0.25
                grip_bottom = self.rect().height() * 0.75
                backing = adaptive_text_color([self.brush().color()])
                backing.setAlpha(210)
                backing_pen = QPen(backing)
                backing_pen.setWidthF(4.0)
                backing_pen.setCosmetic(True)
                backing_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(backing_pen)
                for x in grip_x_positions:
                    painter.drawLine(QPointF(x, grip_top), QPointF(x, grip_bottom))
                grip_pen = QPen(QColor(CYAN))
                grip_pen.setWidthF(2.0)
                grip_pen.setCosmetic(True)
                grip_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(grip_pen)
                for x in grip_x_positions:
                    painter.drawLine(QPointF(x, grip_top), QPointF(x, grip_bottom))
        painter.restore()

    def _update_risk_badge(
        self,
        obj,
        width: float,
        height: float,
        *,
        show_missing_scope: bool | None = None,
    ) -> None:
        has_scope = bool(obj.scope and obj.scope.strip())
        has_risks = bool(obj.risks and obj.risks.strip())
        if show_missing_scope is None:
            scene = self.scene()
            show_missing_scope = (
                bool(getattr(scene, "show_missing_scope", False)) if scene else False
            )
        if has_risks:
            badge_color = QColor(RAG_AMBER_COLOR)
        elif has_scope:
            badge_color = QColor(RAG_GREEN_COLOR)
        else:
            if not show_missing_scope:
                self._risk_badge.setVisible(False)
                return
            badge_color = QColor(RAG_GREEN_COLOR)
        missing_scope = not has_scope and show_missing_scope
        if missing_scope:
            self._risk_badge.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            badge_pen = QPen(badge_color)
            badge_pen.setStyle(Qt.PenStyle.DashLine)
            badge_pen.setWidthF(0.8)
            badge_pen.setCosmetic(True)
        else:
            self._risk_badge.setBrush(badge_color)
            badge_pen = QPen(QColor(80, 80, 80))
            badge_pen.setWidthF(0.6)
            badge_pen.setCosmetic(True)
        self._risk_badge.setPen(badge_pen)
        left_inset, right_inset = self._arrow_edge_insets(width, height)
        badge_size = min(12.0, max(6.0, height * 0.3))
        padding = 3.0
        usable_width = max(1.0, width - left_inset - right_inset - (padding * 2))
        badge_size = min(badge_size, usable_width)
        x = max(
            left_inset + padding,
            width - right_inset - badge_size - padding,
        )
        y = padding
        self._risk_badge.setRect(x, y, badge_size, badge_size)
        self._risk_badge.setVisible(True)

    def _view_scale(self) -> float:
        scene = self.scene()
        if scene is None:
            return 1.0
        views = scene.views()
        if not views:
            return 1.0
        return max(0.01, views[0].transform().m11())

    def _resize_margin(self) -> float:
        return 6.0 / self._view_scale()

    def _resize_grip_hit_areas(self) -> tuple[tuple[str, QRectF], ...]:
        rect = self.rect()
        if rect.isNull():
            return ()
        scale = self._view_scale()
        left_x, right_x = self._resize_grip_x_positions(scale)
        half_width = 6.0 / scale
        vertical_padding = 4.0 / scale
        top = rect.top() + (rect.height() * 0.25) - vertical_padding
        bottom = rect.top() + (rect.height() * 0.75) + vertical_padding
        return (
            (
                "left",
                QRectF(left_x - half_width, top, half_width * 2.0, bottom - top)
                .intersected(rect),
            ),
            (
                "right",
                QRectF(right_x - half_width, top, half_width * 2.0, bottom - top)
                .intersected(rect),
            ),
        )

    def _resize_edge_at(self, pos: QPointF) -> str | None:
        rect = self.rect()
        if rect.isNull():
            return None
        if pos.y() < rect.top() or pos.y() > rect.bottom():
            return None
        margin = self._resize_margin()
        hits = []
        if (pos.x() - rect.left()) <= margin:
            hits.append((abs(pos.x() - rect.left()), "left"))
        if (rect.right() - pos.x()) <= margin:
            hits.append((abs(rect.right() - pos.x()), "right"))
        grip_positions = self._resize_grip_x_positions(self._view_scale())
        hits.extend(
            (abs(pos.x() - grip_x), edge)
            for (edge, area), grip_x in zip(
                self._resize_grip_hit_areas(), grip_positions
            )
            if area.contains(pos)
        )
        if hits:
            return min(hits, key=lambda hit: hit[0])[1]
        return None

    def _start_resize(self, scene, edge: str, event) -> None:
        rect = self.rect()
        pos = self.pos()
        left = pos.x()
        right = pos.x() + rect.width()
        scene_x = event.scenePos().x()
        self._resizing = True
        self._resize_edge = edge
        self._resize_start_pos = QPointF(pos)
        self._resize_start_rect = QRectF(rect)
        self._resize_start_obj = scene.model.objects.get(self.object_id)
        self._resize_offset = scene_x - (left if edge == "left" else right)
        self._drag_start = None
        self._drag_start_pos = None
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def hoverMoveEvent(self, event) -> None:
        self._hovered = True
        self.update()
        scene = self.scene()
        if scene and _active_create_tool(scene) in ("arrow", "connector"):
            self.unsetCursor()
            super().hoverMoveEvent(event)
            return
        if (
            scene
            and scene.edit_mode
            and self._resize_edge_at(event.pos())
        ):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        scene = self.scene()
        if scene is not None:
            scene.set_dependency_hover_object(self.object_id)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        scene = self.scene()
        if scene is not None:
            scene.clear_dependency_hover()
        self.update()
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if (
            scene
            and scene.edit_mode
            and event.button() == Qt.MouseButton.LeftButton
        ):
            edge = self._resize_edge_at(event.pos())
            if edge:
                self._start_resize(scene, edge, event)
                event.accept()
                return
        if scene:
            self._drag_start = scene.model.objects.get(self.object_id)
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing and self._resize_start_pos and self._resize_start_rect:
            scene = self.scene()
            if scene is None:
                return
            layout = scene.layout
            snap = scene.snap_weeks
            start_pos = self._resize_start_pos
            start_rect = self._resize_start_rect
            left = start_pos.x()
            right = start_pos.x() + start_rect.width()
            min_width = layout.week_width
            scene_x = event.scenePos().x() - self._resize_offset
            if self._resize_edge == "left":
                if snap:
                    week = layout.week_from_x(scene_x, True)
                    scene_x = layout.week_left_x(week)
                new_left = min(scene_x, right - min_width)
                width = max(min_width, right - new_left)
                new_left = right - width
                self.setPos(new_left, start_pos.y())
                self.setRect(0, 0, width, start_rect.height())
            elif self._resize_edge == "right":
                if snap:
                    week = layout.week_from_x(scene_x, True)
                    scene_x = layout.week_left_x(week) + layout.week_width
                new_right = max(scene_x, left + min_width)
                width = max(min_width, new_right - left)
                self.setPos(left, start_pos.y())
                self.setRect(0, 0, width, start_rect.height())
            self._update_text_layout()
            if self._resize_start_obj:
                self._update_risk_badge(
                    self._resize_start_obj, self.rect().width(), self.rect().height()
                )
            self._notify_dependency_handle_geometry_changed()
            try:
                start_week = layout.week_from_x(self.pos().x(), snap)
                end_week = layout.week_from_x(
                    self.pos().x() + self.rect().width() - 1, snap
                )
                _, w1 = layout.week_index_to_year_week(scene.model.year, start_week)
                _, w2 = layout.week_index_to_year_week(scene.model.year, end_week)
                scene.set_status(f"Resize · W{w1:02d} → W{w2:02d}")
            except Exception:
                pass
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            scene = self.scene()
            if scene and self._resize_start_obj:
                layout = scene.layout
                obj = self._resize_start_obj
                pos = self.pos()
                width = self.rect().width()
                snap_week = scene.snap_weeks
                duration = max(1, int(round(width / layout.week_width)))
                start_week = layout.week_from_x(pos.x(), snap_week)
                end_week = start_week + duration - 1
                if (start_week, end_week) != (obj.start_week, obj.end_week):
                    scene.commit_object_change(
                        self.object_id,
                        {"start_week": start_week, "end_week": end_week},
                        "Resize Box",
                    )
                else:
                    self.sync_from_model(obj, layout)
            self._resizing = False
            self._resize_edge = None
            self._resize_start_pos = None
            self._resize_start_rect = None
            self._resize_start_obj = None
            self._resize_offset = 0.0
            self.unsetCursor()
            if scene:
                scene.set_status("")
            event.accept()
            return
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start:
            return
        layout = scene.layout
        obj = self._drag_start
        pos = self.pos()
        width = self.rect().width()
        height = self.rect().height()

        snap_week = scene.snap_weeks
        snap_row = scene.snap_rows

        duration = max(1, int(round(width / layout.week_width)))
        start_week = layout.week_from_x(pos.x(), snap_week)
        end_week = start_week + duration - 1

        row_id = layout.row_at_y(pos.y() + height / 2.0)
        if row_id is None:
            row_id = obj.row_id

        if (start_week, end_week, row_id) != (obj.start_week, obj.end_week, obj.row_id):
            scene.commit_object_change(
                self.object_id,
                {
                    "start_week": start_week,
                    "end_week": end_week,
                    "row_id": row_id,
                },
                "Move Box",
            )
        else:
            self.sync_from_model(obj, layout)
        self._drag_start = None
        self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TextboxItem(QGraphicsRectItem):
    def __init__(self, object_id: str) -> None:
        super().__init__()
        self.object_id = object_id
        self._drag_start = None
        self._drag_start_pos = None
        self._resizing = False
        self._resize_start = None
        self._resize_start_rect = None
        self._resize_start_obj = None
        self._resize_handle_size = 10.0
        self._link_dragging = False
        self._link_preview = None
        self._link_start_side = None
        self._link_start_offset = None
        self._link_start_scene = None
        self.text_item = InlineTextItem(self, object_id, allow_newlines=True)
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        width = obj.width if obj.width is not None else TEXTBOX_MIN_WIDTH
        height = obj.height if obj.height is not None else TEXTBOX_MIN_HEIGHT
        x = obj.x if obj.x is not None else 0.0
        y = obj.y if obj.y is not None else 0.0
        opacity = max(0.0, min(1.0, float(getattr(obj, "opacity", 1.0))))
        alpha = int(opacity * 255)
        self.setRect(0, 0, width, height)
        self.setPos(x, y)
        fill = QColor(obj.color)
        if not fill.isValid():
            fill = QColor(255, 255, 255)
        fill.setAlpha(alpha)
        border = fill.darker(130)
        border.setAlpha(alpha)
        self.setBrush(fill)
        self.setPen(QPen(border))
        _set_text_content(self.text_item, obj)
        surface = _canvas_surface(self.text_item)
        visible_fill = composite_color(fill, surface, opacity)
        _apply_adaptive_text(self.text_item, [visible_fill], halo=False)
        _apply_text_alignment(self.text_item, obj.text_align)
        self._update_text_layout(width)

    def _notify_dependency_handle_geometry_changed(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        for view in scene.views():
            layout_handles = getattr(
                view, "_layout_dependency_handles_for_item", None
            )
            if callable(layout_handles):
                layout_handles(self)

    def _update_text_layout(self, width: float) -> None:
        self.text_item.setTextWidth(max(1.0, width - 8))
        self.text_item.setPos(4, 4)
        self._notify_dependency_handle_geometry_changed()

    def _resize_handle_rect(self) -> QRectF:
        rect = self.rect()
        size = self._resize_handle_size
        return QRectF(rect.width() - size, rect.height() - size, size, size)

    def _anchor_local_point(self, side: str, offset: float) -> QPointF:
        rect = self.rect()
        offset_value = max(0.0, min(1.0, float(offset)))
        if side == "left":
            return QPointF(0.0, rect.height() * offset_value)
        if side == "top":
            return QPointF(rect.width() * offset_value, 0.0)
        if side == "bottom":
            return QPointF(rect.width() * offset_value, rect.height())
        return QPointF(rect.width(), rect.height() * offset_value)

    def _edge_anchor_at(self, pos: QPointF) -> tuple[str, float] | None:
        rect = self.rect()
        if rect.isNull():
            return None
        margin = TEXTBOX_ANCHOR_MARGIN
        if not rect.adjusted(-margin, -margin, margin, margin).contains(pos):
            return None
        distances = {
            "left": pos.x(),
            "right": rect.width() - pos.x(),
            "top": pos.y(),
            "bottom": rect.height() - pos.y(),
        }
        side, dist = min(distances.items(), key=lambda item: item[1])
        if dist > margin:
            return None
        if side in ("left", "right"):
            offset = pos.y() / max(1.0, rect.height())
        else:
            offset = pos.x() / max(1.0, rect.width())
        offset = max(0.0, min(1.0, offset))
        return side, offset

    def _start_link_drag(self, side: str, offset: float) -> None:
        scene = self.scene()
        if scene is None:
            return
        self._link_dragging = True
        self._link_start_side = side
        self._link_start_offset = offset
        self._link_start_scene = self.mapToScene(self._anchor_local_point(side, offset))
        pen = QPen(QColor(LINK_LINE_COLOR))
        pen.setWidth(LINK_LINE_WIDTH)
        preview = QGraphicsLineItem(QLineF(self._link_start_scene, self._link_start_scene))
        preview.setPen(pen)
        preview.setZValue(self.zValue() + 1)
        preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scene.addItem(preview)
        self._link_preview = preview
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _finish_link_drag(self, scene_pos: QPointF) -> None:
        scene = self.scene()
        if scene is None:
            return
        if self._link_preview is not None:
            scene.removeItem(self._link_preview)
        self._link_preview = None
        self.unsetCursor()
        self._link_dragging = False
        self._link_start_scene = None
        side = self._link_start_side
        offset = self._link_start_offset
        self._link_start_side = None
        self._link_start_offset = None
        if side is None or offset is None:
            return
        target_id = None
        for item in scene.items(scene_pos):
            if item is self or item is self.text_item:
                continue
            obj_id = item.data(0)
            if not obj_id or obj_id == self.object_id:
                continue
            target_obj = scene.model.objects.get(obj_id)
            if target_obj is None or target_obj.kind in ("link", "textbox", "connector"):
                continue
            target_id = obj_id
            break
        if target_id and scene.controller:
            scene.controller.add_anchor_link(self.object_id, target_id, side, offset)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        if self.isSelected():
            handle = self._resize_handle_rect()
            painter.setBrush(QColor(230, 230, 230))
            painter.setPen(QPen(QColor(140, 140, 140)))
            painter.drawRect(handle)

    def hoverMoveEvent(self, event) -> None:
        scene = self.scene()
        if scene and _active_create_tool(scene) in ("arrow", "connector"):
            self.unsetCursor()
            super().hoverMoveEvent(event)
            return
        if (
            scene
            and scene.edit_mode
            and self.isSelected()
            and self._resize_handle_rect().contains(event.pos())
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if (
            scene
            and scene.edit_mode
            and event.button() == Qt.MouseButton.LeftButton
            and self.isSelected()
            and self._resize_handle_rect().contains(event.pos())
        ):
            self._resizing = True
            self._resize_start = QPointF(event.pos())
            self._resize_start_rect = QRectF(self.rect())
            self._resize_start_obj = scene.model.objects.get(self.object_id)
            self._drag_start = None
            self._drag_start_pos = None
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            event.accept()
            return
        if scene and scene.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_anchor_at(event.pos())
            if edge:
                self.setSelected(True)
                self._drag_start = None
                self._drag_start_pos = None
                self._start_link_drag(edge[0], edge[1])
                event.accept()
                return
        if scene:
            self._drag_start = scene.model.objects.get(self.object_id)
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._link_dragging and self._link_preview and self._link_start_scene:
            scene_pos = self.mapToScene(event.pos())
            self._link_preview.setLine(QLineF(self._link_start_scene, scene_pos))
            event.accept()
            return
        if self._resizing and self._resize_start and self._resize_start_rect:
            delta = event.pos() - self._resize_start
            width = max(TEXTBOX_MIN_WIDTH, self._resize_start_rect.width() + delta.x())
            height = max(TEXTBOX_MIN_HEIGHT, self._resize_start_rect.height() + delta.y())
            self.setRect(0, 0, width, height)
            self._update_text_layout(width)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._link_dragging:
            self._finish_link_drag(self.mapToScene(event.pos()))
            event.accept()
            return
        if self._resizing:
            scene = self.scene()
            if scene and self._resize_start_obj:
                layout = scene.layout
                obj = self._resize_start_obj
                pos = self.pos()
                width = self.rect().width()
                height = self.rect().height()
                start_week = layout.week_from_x(pos.x(), snap=False)
                end_week = layout.week_from_x(pos.x() + width, snap=False)
                updates = {
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": width,
                    "height": height,
                    "start_week": start_week,
                    "end_week": end_week,
                }
                if (
                    pos.x() != (obj.x or 0.0)
                    or pos.y() != (obj.y or 0.0)
                    or width != (obj.width or width)
                    or height != (obj.height or height)
                ):
                    scene.commit_object_change(self.object_id, updates, "Resize Textbox")
            self._resizing = False
            self._resize_start = None
            self._resize_start_rect = None
            self._resize_start_obj = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start:
            return
        layout = scene.layout
        obj = self._drag_start
        pos = self.pos()
        width = self.rect().width()
        height = self.rect().height()

        start_week = layout.week_from_x(pos.x(), snap=False)
        end_week = layout.week_from_x(pos.x() + width, snap=False)

        updates = {
            "x": pos.x(),
            "y": pos.y(),
            "width": width,
            "height": height,
            "start_week": start_week,
            "end_week": end_week,
        }
        if (
            pos.x() != (obj.x or 0.0)
            or pos.y() != (obj.y or 0.0)
            or width != (obj.width or width)
            or height != (obj.height or height)
        ):
            scene.commit_object_change(self.object_id, updates, "Move Textbox")
        self._drag_start = None
        self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MilestoneItem(QGraphicsPolygonItem):
    def __init__(self, object_id: str) -> None:
        super().__init__()
        self.object_id = object_id
        self._drag_start = None
        self._drag_start_pos = None
        self.text_item = InlineTextItem(self, object_id, allow_newlines=False)
        self.text_item.document().setDocumentMargin(0.0)
        self.setFlags(
            QGraphicsPolygonItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsPolygonItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        half = size / 2.0
        center_x = layout.week_right_x(obj.end_week)
        x = center_x - half
        y = layout.row_center_y(obj.row_id) - half + layout.object_vertical_offset(obj.id)
        polygon = QPolygonF(
            [
                QPointF(half, 0),
                QPointF(size, half),
                QPointF(half, size),
                QPointF(0, half),
            ]
        )
        self.setPolygon(polygon)
        self.setPos(x, y)
        self.setBrush(QColor(obj.color))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        _set_text_content(self.text_item, obj)
        _apply_adaptive_text(
            self.text_item,
            [QColor(obj.color), _canvas_surface(self.text_item)],
            halo=True,
        )
        _apply_text_alignment(self.text_item, obj.text_align)
        _position_point_label(self.text_item, self.polygon().boundingRect(), obj.text_align)

    def hoverEnterEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None:
            scene.set_dependency_hover_object(self.object_id)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None:
            scene.clear_dependency_hover()
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        scene = self.scene()
        dependency_hovered = (
            scene is not None
            and getattr(scene, 'is_dependency_hovered_object', lambda _id: False)(self.object_id)
        )
        if scene is None or getattr(scene, 'exporting', False) or not (self.isSelected() or dependency_hovered):
            return
        focus = getattr(scene, 'is_dependency_hovered_focus', lambda _id: False)(self.object_id)
        selected = self.isSelected()
        pen = QPen(QColor(CYAN if focus or selected else "#8b5cf6"))
        pen.setWidthF(2.8 if selected else (2.6 if focus else 2.0))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(self.polygon())

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if scene:
            self._drag_start = scene.model.objects.get(self.object_id)
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start:
            return
        layout = scene.layout
        obj = self._drag_start
        pos = self.pos()
        size = self.polygon().boundingRect().width()

        # A press/release without movement is a selection click, not a move.
        # The point is anchored on a week divider, so re-snapping the rounded
        # mouse position would otherwise change its week.
        if self._drag_start_pos is not None and (
            abs(pos.x() - self._drag_start_pos.x()) < 0.1
            and abs(pos.y() - self._drag_start_pos.y()) < 0.1
        ):
            self._drag_start = None
            self._drag_start_pos = None
            return

        snap_week = scene.snap_weeks
        snap_row = scene.snap_rows

        # The visual center is the right divider of the assigned week.  Convert
        # that anchor back to the week's left edge before applying snapping;
        # feeding the divider directly to week_from_x() would select the next
        # week on every click.
        week = layout.week_from_x(
            pos.x() + (size / 2.0) - layout.week_width + 0.5, snap_week
        )
        row_id = layout.row_at_y(pos.y() + (size / 2.0)) if snap_row else layout.row_at_y(pos.y())
        if row_id is None:
            row_id = obj.row_id

        if (week, row_id) != (obj.start_week, obj.row_id):
            scene.commit_object_change(
                self.object_id,
                {
                    "start_week": week,
                    "end_week": week,
                    "row_id": row_id,
                },
                "Move Milestone",
            )
        else:
            self.sync_from_model(obj, layout)
        self._drag_start = None
        self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class CircleItem(QGraphicsEllipseItem):
    def __init__(self, object_id: str) -> None:
        super().__init__()
        self.object_id = object_id
        self._drag_start = None
        self._drag_start_pos = None
        self.text_item = InlineTextItem(self, object_id, allow_newlines=False)
        self.setFlags(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        row_height = layout.row_height(obj.row_id)
        size = layout.object_item_size(obj.id, row_height, obj.size)
        half = size / 2.0
        center_x = layout.week_center_x(obj.start_week)
        x = center_x - half
        y = layout.row_center_y(obj.row_id) - half + layout.object_vertical_offset(obj.id)
        self.setRect(0, 0, size, size)
        self.setPos(x, y)
        self.setBrush(QColor(obj.color))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        _set_text_content(self.text_item, obj)
        _apply_adaptive_text(
            self.text_item,
            [QColor(obj.color), _canvas_surface(self.text_item)],
            halo=True,
        )
        _apply_text_alignment(self.text_item, obj.text_align)
        _position_point_label(self.text_item, self.rect(), obj.text_align)

    def hoverEnterEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None:
            scene.set_dependency_hover_object(self.object_id)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None:
            scene.clear_dependency_hover()
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        scene = self.scene()
        dependency_hovered = (
            scene is not None
            and getattr(scene, 'is_dependency_hovered_object', lambda _id: False)(self.object_id)
        )
        if scene is None or getattr(scene, 'exporting', False) or not (self.isSelected() or dependency_hovered):
            return
        focus = getattr(scene, 'is_dependency_hovered_focus', lambda _id: False)(self.object_id)
        selected = self.isSelected()
        pen = QPen(QColor(CYAN if focus or selected else "#8b5cf6"))
        pen.setWidthF(2.8 if selected else (2.6 if focus else 2.0))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self.rect())

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if scene:
            self._drag_start = scene.model.objects.get(self.object_id)
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start:
            return
        layout = scene.layout
        obj = self._drag_start
        pos = self.pos()
        size = self.rect().width()

        snap_week = scene.snap_weeks
        snap_row = scene.snap_rows

        week = layout.week_from_center_x(pos.x() + (size / 2.0), snap_week)
        row_id = layout.row_at_y(pos.y() + (size / 2.0)) if snap_row else layout.row_at_y(pos.y())
        if row_id is None:
            row_id = obj.row_id

        if (week, row_id) != (obj.start_week, obj.row_id):
            scene.commit_object_change(
                self.object_id,
                {
                    "start_week": week,
                    "end_week": week,
                    "row_id": row_id,
                },
                "Move Event",
            )
        else:
            self.sync_from_model(obj, layout)
        self._drag_start = None
        self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class DeadlineItem(QGraphicsLineItem):
    def __init__(self, object_id: str) -> None:
        super().__init__()
        self.object_id = object_id
        self._drag_start = None
        self._drag_start_pos = None
        self.text_item = InlineTextItem(self, object_id, allow_newlines=False)
        self.setFlags(
            QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable
        )

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        center_x = layout.week_right_x(obj.end_week)
        line_height = layout.header_height + layout.total_height
        self.setPos(center_x, 0.0)
        pen = QPen(QColor(obj.color))
        pen.setWidth(max(2, int(obj.size)))
        pen.setCosmetic(True)
        self.setPen(pen)
        label_font = QFont(self.text_item.font())
        label_font.setBold(True)
        self.text_item.setFont(label_font)
        _set_text_content(self.text_item, obj)
        _apply_colored_text_with_halo(self.text_item, QColor(obj.color))
        # Deadline titles share the top calendar band with the TODAY label.
        # Natural width keeps the title on one line without a badge or lane.
        self.text_item.setTextWidth(-1)
        label_width = self.text_item.boundingRect().width()
        label_height = self.text_item.boundingRect().height()
        label_x = -(label_width / 2.0)
        label_y = (HEADER_YEAR_HEIGHT - label_height) / 2.0
        self.text_item.setPos(label_x, label_y)
        has_title = bool((obj.text or '').strip())
        self.text_item.setVisible(has_title)
        line_start = label_y + label_height if has_title else 0.0
        self.setLine(0.0, line_start, 0.0, line_height)

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if scene:
            self._drag_start = scene.model.objects.get(self.object_id)
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start:
            return
        layout = scene.layout
        obj = self._drag_start
        pos = self.pos()
        snap_week = scene.snap_weeks
        if self._drag_start_pos is not None and (
            abs(pos.x() - self._drag_start_pos.x()) < 0.1
            and abs(pos.y() - self._drag_start_pos.y()) < 0.1
        ):
            self._drag_start = None
            self._drag_start_pos = None
            return
        # Deadlines use the same right-divider anchor as milestones.
        week = layout.week_from_x(pos.x() - layout.week_width + 0.5, snap_week)
        if week != obj.start_week:
            scene.commit_object_change(
                self.object_id,
                {"start_week": week, "end_week": week},
                "Move Deadline",
            )
        else:
            self.sync_from_model(obj, layout)
        self._drag_start = None
        self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ConnectorItem(QGraphicsPathItem):
    """Unified connector (schema v3).

    Attached mode uses connector_source_id/connector_target_id with
    automatic midpoint anchors. Free mode (no source/target) is anchored to
    week/row coordinates and can be dragged and endpoint-resized like the
    old arrow object. Both modes support an editable text label.
    """

    def __init__(self, object_id: str, scene_ref) -> None:
        super().__init__()
        self.object_id = object_id
        self.scene_ref = scene_ref
        self._arrow_head_start = False
        self._arrow_head_end = True
        self._drag_start = None
        self._drag_start_pos = None
        self._drag_start_geom = None
        self.text_item = InlineTextItem(self, object_id, allow_newlines=False)
        self.setFlags(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable)

    @staticmethod
    def is_attached(obj) -> bool:
        return bool(obj.connector_source_id and obj.connector_target_id)

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        self._arrow_head_start = bool(getattr(obj, "arrow_head_start", False))
        self._arrow_head_end = bool(getattr(obj, "arrow_head_end", True))
        model = self.scene_ref.model
        attached = self.is_attached(obj)
        start_x = start_y = end_x = end_y = None
        bow = 0.0
        if attached:
            start_point, end_point = self._attached_endpoints(obj, layout, model)
            if start_point is None or end_point is None:
                self.setPath(QPainterPath())
                return
            start_x, start_y = start_point.x(), start_point.y()
            end_x, end_y = end_point.x(), end_point.y()
            bow = _parallel_bow(model, obj)
        else:
            if obj.row_id not in layout.row_map:
                self.setPath(QPainterPath())
                return
            target_row = obj.target_row_id or obj.row_id
            if target_row not in layout.row_map:
                self.setPath(QPainterPath())
                return
            start_x = layout.week_center_x(obj.start_week)
            start_y = layout.row_center_y(obj.row_id)
            target_week = obj.target_week if obj.target_week is not None else obj.end_week
            end_x = layout.week_center_x(target_week)
            end_y = layout.row_center_y(target_row)
        path = _smooth_curve(QPointF(start_x, start_y), QPointF(end_x, end_y), bow)
        self.setPos(0, 0)
        self.setPath(path)
        color = QColor(obj.color)
        if not color.isValid():
            color = QColor(CONNECTOR_DEFAULT_COLOR)
        pen = QPen(color)
        pen.setWidth(max(1, obj.size))
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        # Attached connectors are locked; free connectors move with the grid.
        self.setFlag(
            QGraphicsPathItem.GraphicsItemFlag.ItemIsMovable,
            (not attached) and bool(self.scene() and self.scene().edit_mode),
        )
        self._update_label(obj, layout, path, abs(end_x - start_x))

    def _attached_endpoints(self, obj, layout, model):
        source = model.objects.get(obj.connector_source_id)
        target = model.objects.get(obj.connector_target_id)
        if (
            source is None
            or target is None
            or source.kind in ("link", "connector")
            or target.kind in ("link", "connector")
        ):
            return None, None
        source_bounds = _object_bounds_for_connector(source, layout)
        target_bounds = _object_bounds_for_connector(target, layout)
        cache = self.scene_ref.connector_cache.setdefault(obj.id, {})
        start_point = None
        end_point = None
        source_visible = source_bounds is not None
        target_visible = target_bounds is not None
        # Anchor strictly at the midpoint of the edge facing the other item.
        if source_bounds is not None:
            other_center = (
                target_bounds.center()
                if target_bounds is not None
                else cache.get("target", source_bounds.center())
            )
            start_point = _mid_anchor_point(source_bounds, other_center)
            cache["source"] = start_point
        if target_bounds is not None:
            other_center = (
                source_bounds.center()
                if source_bounds is not None
                else cache.get("source", target_bounds.center())
            )
            end_point = _mid_anchor_point(target_bounds, other_center)
            cache["target"] = end_point
        if not source_visible and not target_visible:
            return None, None
        if start_point is None:
            start_point = cache.get("source")
        if end_point is None:
            end_point = cache.get("target")
        return start_point, end_point

    def _update_label(self, obj, layout, path, span: float) -> None:
        mid = path.pointAtPercent(0.5)
        label_width = max(layout.week_width * 3, span)
        if obj.row_id in layout.row_map:
            row_height = layout.row_height(obj.row_id)
        elif layout.rows:
            row_height = layout.row_height(layout.rows[0].row_id)
        else:
            row_height = 20.0
        _set_text_content(self.text_item, obj)
        _apply_adaptive_text(
            self.text_item,
            [_canvas_surface(self.text_item)],
            halo=True,
        )
        _apply_text_alignment(self.text_item, obj.text_align)
        self.text_item.setTextWidth(label_width)
        self.text_item.setPos(mid.x() - (label_width / 2.0), mid.y() - (row_height * 0.6))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        path = self.path()
        if path.elementCount() < 2:
            return
        line_width = self.pen().widthF()
        if line_width <= 0.0:
            line_width = float(self.pen().width())
        if line_width <= 0.0:
            line_width = 1.0
        size = max(LINK_ARROW_SIZE, line_width * 2.5)
        pen_color = self.pen().color()
        if self._arrow_head_end:
            end, prev = _path_tangent(path, at_start=False)
            _draw_arrowhead(painter, prev, end, pen_color, size, outline=False)
        if self._arrow_head_start:
            start, nxt = _path_tangent(path, at_start=True)
            _draw_arrowhead(painter, nxt, start, pen_color, size, outline=False)

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if scene:
            obj = scene.model.objects.get(self.object_id)
            if obj and not self.is_attached(obj):
                layout = scene.layout
                start_pos = QPointF(
                    layout.week_center_x(obj.start_week), layout.row_center_y(obj.row_id)
                )
                target_week = obj.target_week if obj.target_week is not None else obj.end_week
                target_row = obj.target_row_id or obj.row_id
                end_pos = QPointF(
                    layout.week_center_x(target_week), layout.row_center_y(target_row)
                )
                self._drag_start_geom = (start_pos, end_pos)
            self._drag_start = obj
            self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if not scene or not self._drag_start or not self._drag_start_geom:
            return
        obj = self._drag_start
        if self.is_attached(obj):
            self._drag_start = None
            self._drag_start_pos = None
            self._drag_start_geom = None
            return
        layout = scene.layout
        start_pos, end_pos = self._drag_start_geom
        delta = self.pos() - (self._drag_start_pos or QPointF(0, 0))
        snap_week = scene.snap_weeks
        snap_row = scene.snap_rows
        start_week = layout.week_from_center_x(start_pos.x() + delta.x(), snap_week)
        start_row = layout.row_at_y(start_pos.y() + delta.y()) if snap_row else layout.row_at_y(start_pos.y())
        if start_row is None:
            start_row = obj.row_id
        target_week = layout.week_from_center_x(end_pos.x() + delta.x(), snap_week)
        target_row = layout.row_at_y(end_pos.y() + delta.y()) if snap_row else layout.row_at_y(end_pos.y())
        if target_row is None:
            target_row = obj.target_row_id or obj.row_id
        updates = {
            "start_week": start_week,
            "row_id": start_row,
            "end_week": target_week,
            "target_week": target_week,
            "target_row_id": target_row,
        }
        if obj.arrow_mid_week is not None:
            delta_weeks = start_week - obj.start_week
            updates["arrow_mid_week"] = obj.arrow_mid_week + delta_weeks
        if (
            start_week != obj.start_week
            or target_week != (obj.target_week if obj.target_week is not None else obj.end_week)
            or start_row != obj.row_id
            or target_row != (obj.target_row_id or obj.row_id)
        ):
            scene.commit_object_change(self.object_id, updates, "Move Connector")
        else:
            self.sync_from_model(obj, layout)
        self._drag_start = None
        self._drag_start_pos = None
        self._drag_start_geom = None

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if scene and scene.edit_mode:
            self.text_item.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LinkItem(QGraphicsPathItem):
    def __init__(self, object_id: str, scene_ref) -> None:
        super().__init__()
        self.object_id = object_id
        self.scene_ref = scene_ref
        self.setFlags(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable)

    def sync_from_model(self, obj, layout) -> None:
        self.setZValue(obj.z_index)
        model = self.scene_ref.model
        source_id = obj.link_source_id
        target_id = obj.link_target_id
        if not source_id or not target_id:
            self.setPath(QPainterPath())
            return
        source = model.objects.get(source_id)
        target = model.objects.get(target_id)
        if (
            source is None
            or target is None
            or source.kind != "textbox"
            or target.kind in ("link", "connector")
        ):
            self.setPath(QPainterPath())
            return
        start = _textbox_anchor_point(source, obj.link_source_side, obj.link_source_offset)
        end = _object_center_for_link(target, layout)
        if end is None:
            self.setPath(QPainterPath())
            return
        # Curved link anchored at the target's facing-edge midpoint.
        target_item = self.scene_ref.items_by_id.get(target.id)
        target_bounds = (
            target_item.mapRectToScene(target_item.boundingRect())
            if target_item is not None
            else _object_bounds_for_connector(target, layout)
        )
        if target_bounds is not None:
            target_side = _opposite_link_side(obj.link_source_side)
            if target_side is not None:
                end = _side_anchor_point(target_bounds, target_side)
            else:
                end = _mid_anchor_point(target_bounds, start)
        path = _smooth_curve(start, end, _parallel_bow(model, obj))
        self.setPos(0, 0)
        self.setPath(path)
        color = QColor(obj.color)
        if not color.isValid():
            color = QColor(LINK_LINE_COLOR)
        pen = QPen(color)
        pen.setWidth(LINK_LINE_WIDTH)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        path = self.path()
        if path.elementCount() < 2:
            return
        end, prev = _path_tangent(path, at_start=False)
        angle = (end - prev)
        length = (angle.x() ** 2 + angle.y() ** 2) ** 0.5
        if length == 0:
            return
        ux = angle.x() / length
        uy = angle.y() / length
        size = LINK_ARROW_SIZE
        left = QPointF(end.x() - ux * size - uy * (size / 2.0), end.y() - uy * size + ux * (size / 2.0))
        right = QPointF(end.x() - ux * size + uy * (size / 2.0), end.y() - uy * size - ux * (size / 2.0))
        painter.setBrush(self.pen().color())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([end, left, right]))

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
import math

from .constants import (
    DEFAULT_WEEK_WIDTH,
    DELIVERABLE_ROW_HEIGHT,
    DIVIDER_ROW_HEIGHT,
    HEADER_MONTH_HEIGHT,
    HEADER_QUARTER_HEIGHT,
    HEADER_WEEK_HEIGHT,
    HEADER_YEAR_HEIGHT,
    LABEL_WIDTH,
    ROW_ITEM_VERTICAL_PADDING,
    TOPIC_ROW_HEIGHT,
)
from .model import ProjectModel


def size_scale(size: int) -> float:
    """Map the 1–5+ size setting to a 0.6–1.0 scale of the available row height."""
    scale = 0.5 + (0.1 * size)
    return min(1.0, max(0.6, scale))


def row_item_height(row_height: float, size: int) -> float:
    """Height for a row-spanning item (activity/box) leaving vertical padding."""
    available = max(6.0, row_height - (2 * ROW_ITEM_VERTICAL_PADDING))
    return available * size_scale(size)


def row_item_size(row_height: float, size: int, max_dimension: float | None = None) -> float:
    """Edge length for square/diamond items (milestone/circle) with padding."""
    available = row_height - (2 * ROW_ITEM_VERTICAL_PADDING)
    if max_dimension is not None:
        available = min(available, max_dimension)
    return max(6.0, available) * size_scale(size)


@dataclass(frozen=True)
class ObjectGeometry:
    x: float
    y: float
    width: float
    height: float
    lane: int


@dataclass
class RowLayout:
    row_id: str
    name: str
    kind: str
    topic_id: str
    y: float
    height: float
    indent: int
    divider: bool = False


class Layout:
    def __init__(self, model: ProjectModel, week_width: int = DEFAULT_WEEK_WIDTH) -> None:
        self.week_width = week_width
        self.label_width = LABEL_WIDTH
        self.header_height = (
            HEADER_YEAR_HEIGHT
            + HEADER_QUARTER_HEIGHT
            + HEADER_MONTH_HEIGHT
            + HEADER_WEEK_HEIGHT
        )
        self.origin_week = 1
        self.rows: list[RowLayout] = []
        self.row_map: dict[str, RowLayout] = {}
        self._row_start_positions: list[float] = []
        self._row_end_positions: list[float] = []
        self._row_index_map: dict[str, int] = {}
        self.total_height = 0.0
        self.object_offsets: dict[str, float] = {}
        self.object_heights: dict[str, float] = {}
        self.rebuild(model)

    def rebuild(self, model: ProjectModel) -> None:
        self.rows = []
        self.row_map = {}
        self._row_start_positions = []
        self._row_end_positions = []
        self._row_index_map = {}
        y = 0.0
        for topic in model.topics:
            # "Add divider" creates a topic with kind="divider"; it renders as a
            # thin separator row and never shows deliverables.
            is_divider = getattr(topic, "kind", "lane") == "divider"
            topic_height = DIVIDER_ROW_HEIGHT if is_divider else TOPIC_ROW_HEIGHT
            topic_row = RowLayout(
                row_id=topic.id,
                name=topic.name,
                kind="topic",
                topic_id=topic.id,
                y=y,
                height=topic_height,
                indent=0,
                divider=is_divider,
            )
            self.rows.append(topic_row)
            self.row_map[topic.id] = topic_row
            y += topic_height
            if topic.collapsed or is_divider:
                continue
            for deliverable in topic.deliverables:
                deliverable_row = RowLayout(
                    row_id=deliverable.id,
                    name=deliverable.name,
                    kind="deliverable",
                    topic_id=topic.id,
                    y=y,
                    height=DELIVERABLE_ROW_HEIGHT,
                    indent=1 + max(0, int(getattr(deliverable, "indent", 0))),
                )
                self.rows.append(deliverable_row)
                self.row_map[deliverable.id] = deliverable_row
                y += DELIVERABLE_ROW_HEIGHT
        self.object_offsets = {}
        self.object_heights = {}
        self.object_lanes = {}
        self._apply_object_lanes(model)
        y = 0.0
        for row in self.rows:
            row.y = y
            y += row.height
        self.total_height = y
        self.object_geometry = {}
        for obj in model.objects.values():
            if obj.kind not in ("box", "milestone", "circle") or obj.row_id not in self.row_map:
                continue
            row_height = self.row_height(obj.row_id)
            if obj.kind == "box":
                height = self.object_item_height(obj.id, row_height, obj.size)
                width = max(1, obj.end_week - obj.start_week + 1) * self.week_width
                x = self.week_left_x(obj.start_week)
            else:
                height = width = self.object_item_size(obj.id, row_height, obj.size)
                center = (self.week_right_x(obj.end_week) if obj.kind == "milestone"
                          else self.week_center_x(obj.start_week))
                x = center - width / 2
            self.object_geometry[obj.id] = ObjectGeometry(
                x, self.row_center_y(obj.row_id) + self.object_vertical_offset(obj.id) - height / 2,
                width, height, self.object_lanes.get(obj.id, 0),
            )
        for index, row in enumerate(self.rows):
            self._row_start_positions.append(row.y)
            self._row_end_positions.append(row.y + row.height)
            self._row_index_map[row.row_id] = index

    def object_vertical_offset(self, object_id: str) -> float:
        return self.object_offsets.get(object_id, 0.0)

    def object_item_height(self, object_id: str, row_height: float, size: int) -> float:
        return self.object_heights.get(object_id, row_item_height(row_height, size))

    def object_item_size(self, object_id: str, row_height: float, size: int) -> float:
        return self.object_heights.get(
            object_id, row_item_size(row_height, size, self.week_width)
        )

    def _apply_object_lanes(self, model: ProjectModel) -> None:
        """Assign deterministic visual lanes without changing model positions."""
        scheduled = {
            obj.id: obj
            for obj in model.objects.values()
            if obj.kind in ("box", "milestone", "circle")
            and obj.row_id in self.row_map
        }
        by_row: dict[str, list] = {}
        for obj in scheduled.values():
            by_row.setdefault(obj.row_id, []).append(obj)

        gap = 6.0
        padding = float(ROW_ITEM_VERTICAL_PADDING)
        for row_id, objects in by_row.items():
            if self.row_map[row_id].divider:
                continue
            row = self.row_map[row_id]
            base_height = row.height
            entries = []
            labels = {}
            for obj in objects:
                if obj.kind == "box":
                    left = self.week_left_x(obj.start_week)
                    right = self.week_left_x(obj.end_week) + self.week_width
                    height = row_item_height(base_height, obj.size)
                else:
                    center = (
                        self.week_center_x(obj.start_week)
                        if obj.kind == "circle"
                        else self.week_right_x(obj.end_week)
                    )
                    half = row_item_size(
                        base_height, obj.size, self.week_width
                    ) / 2.0
                    left = center - half
                    right = center + half
                    height = row_item_size(base_height, obj.size, self.week_width)
                self.object_heights[obj.id] = height
                if obj.kind in ("milestone", "circle") and (obj.text or obj.text_html):
                    # Measure committed text with the renderer's document and placement rules.
                    from PyQt6.QtCore import QRectF
                    from PyQt6.QtWidgets import QGraphicsTextItem
                    from .items import _set_text_content, _apply_text_alignment, _position_point_label
                    text_item = QGraphicsTextItem()
                    if obj.kind == "milestone":
                        text_item.document().setDocumentMargin(0.0)
                    _set_text_content(text_item, obj)
                    _apply_text_alignment(text_item, obj.text_align)
                    _position_point_label(text_item, QRectF(0, 0, height, height), obj.text_align)
                    if text_item.toPlainText().strip():
                        bounds = text_item.boundingRect().translated(text_item.pos())
                        labels[obj.id] = (left + bounds.left(), left + bounds.right(), bounds.height())
                entries.append((obj.start_week, obj.end_week, obj.kind, obj.id, left, right, height))
            entries.sort(key=lambda entry: entry[:4])

            def conflicts(a, b):
                def intersects(left, right, other_left, other_right):
                    return min(right, other_right) > max(left, other_left)
                for source, target in ((a, b), (b, a)):
                    label = labels.get(source[3])
                    if label and intersects(label[0], label[1], target[4], target[5]):
                        return True
                la, lb = labels.get(a[3]), labels.get(b[3])
                if la and lb and intersects(la[0], la[1], lb[0], lb[1]):
                    return True
                penetration = min(a[5], b[5]) - max(a[4], b[4])
                if {a[2], b[2]} == {"milestone", "circle"}:
                    allowed = min(a[5] - a[4], b[5] - b[4]) * model.symbol_overlap_tolerance_percent / 100
                    return penetration > allowed + 1e-9
                return penetration > 1e-9

            lanes: list[list[tuple]] = []
            for entry in entries:
                lane = next((lane for lane in lanes if all(
                    not conflicts(entry, placed) for placed in lane
                )), None)
                if lane is None:
                    lane = []
                    lanes.append(lane)
                lane.append(entry)

            lane_heights = [max(max(item[6], labels.get(item[3], (0, 0, 0))[2]) for item in lane) for lane in lanes]
            content_height = sum(lane_heights) + gap * (len(lanes) - 1)
            row.height = max(row.height, content_height + (2.0 * padding))
            cursor = -content_height / 2.0
            for lane_index, (lane_height, lane) in enumerate(zip(lane_heights, lanes)):
                lane_center = cursor + lane_height / 2.0
                for entry in lane:
                    self.object_offsets[entry[3]] = lane_center
                    self.object_lanes[entry[3]] = lane_index
                cursor += lane_height + gap

    def week_left_x(self, week: int) -> float:
        return self.label_width + (week - self.origin_week) * self.week_width

    def week_center_x(self, week: int) -> float:
        return self.week_left_x(week) + (self.week_width / 2.0)

    def week_right_x(self, week: int) -> float:
        """Return the right-hand divider of a calendar week."""
        return self.week_left_x(week) + self.week_width

    def row_top_y(self, row_id: str) -> float:
        row = self.row_map[row_id]
        return self.header_height + row.y

    def row_center_y(self, row_id: str) -> float:
        row = self.row_map[row_id]
        return self.header_height + row.y + (row.height / 2.0)

    def row_height(self, row_id: str) -> float:
        return self.row_map[row_id].height

    def row_at_y(self, scene_y: float) -> str | None:
        y_rel = scene_y - self.header_height
        if y_rel < 0:
            return None
        if not self.rows:
            return None
        index = bisect_right(self._row_end_positions, y_rel)
        if index >= len(self.rows):
            return None
        row = self.rows[index]
        if row.y <= y_rel < row.y + row.height:
            return row.row_id
        return None

    def row_index(self, row_id: str) -> int | None:
        return self._row_index_map.get(row_id)

    def row_index_range(self, y_min: float, y_max: float) -> tuple[int, int]:
        if not self.rows:
            return 0, 0
        start = bisect_left(self._row_end_positions, y_min)
        end = bisect_right(self._row_end_positions, y_max)
        return start, end

    def adjacent_row(self, row_id: str, direction: int) -> str | None:
        index = self.row_index(row_id)
        if index is None:
            return None
        new_index = index + direction
        if new_index < 0 or new_index >= len(self.rows):
            return None
        return self.rows[new_index].row_id

    def week_from_x(self, scene_x: float, snap: bool = True) -> int:
        x_rel = scene_x - self.label_width
        ratio = x_rel / self.week_width
        if snap:
            if ratio >= 0:
                week_offset = int(ratio + 0.5)
            else:
                week_offset = int(ratio - 0.5)
        else:
            week_offset = int(math.floor(ratio))
        return week_offset + self.origin_week

    def week_from_center_x(self, scene_x: float, snap: bool = True) -> int:
        return self.week_from_x(scene_x - (self.week_width / 2.0), snap)

    def week_index_to_year_week(self, base_year: int, week_index: int) -> tuple[int, int]:
        week_date = self.week_index_to_date(base_year, week_index)
        iso = week_date.isocalendar()
        return iso.year, iso.week

    def week_index_to_date(self, base_year: int, week_index: int) -> date:
        base_date = self.base_week_start(base_year)
        return base_date + timedelta(weeks=week_index - self.origin_week)

    def week_index_for_iso_year(self, base_year: int, year: int) -> int:
        base_date = self.base_week_start(base_year)
        year_start = self.base_week_start(year)
        delta_weeks = (year_start - base_date).days // 7
        return self.origin_week + delta_weeks

    @staticmethod
    def base_week_start(year: int) -> date:
        return date.fromisocalendar(year, 1, 1)

    @staticmethod
    def weeks_in_year(year: int) -> int:
        return date(year, 12, 28).isocalendar().week

    @staticmethod
    def quarter_for_week(week_in_year: int) -> int:
        return min(4, ((week_in_year - 1) // 13) + 1)

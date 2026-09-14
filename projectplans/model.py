from __future__ import annotations

from dataclasses import dataclass, field, replace
import uuid

from PyQt6.QtCore import QObject, pyqtSignal

from .constants import (
    CLASSIFICATION_SIZE_DEFAULT,
    CLASSIFICATION_SIZE_MAX,
    CLASSIFICATION_SIZE_MIN,
    DEFAULT_CLASSIFICATION,
    DEFAULT_SIZE,
    SCHEMA_VERSION,
    TEXTBOX_DEFAULT_OPACITY,
)

DEFAULT_TOPIC_COLORS = [
    # Okabe-Ito-inspired categorical colors: distinguishable for the
    # common forms of red/green colour-vision deficiency.
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # green
    "#CC79A7",  # purple
    "#D55E00",  # vermilion
    "#56B4E9",  # sky
    "#F0E442",  # yellow
    "#000000",  # ink (last resort, still distinct)
]


def normalize_arrow_direction(value: object) -> str:
    direction = str(value or "none").strip().lower()
    if direction not in ("none", "left", "right"):
        return "none"
    return direction


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Deliverable:
    id: str
    name: str
    indent: int = 0

    def to_dict(self) -> dict:
        data = {"id": self.id, "name": self.name}
        if self.indent:
            data["indent"] = self.indent
        return data

    @staticmethod
    def from_dict(data: dict) -> "Deliverable":
        indent = data.get("indent", 0)
        try:
            indent_value = int(indent)
        except (TypeError, ValueError):
            indent_value = 0
        return Deliverable(id=data["id"], name=data["name"], indent=max(0, indent_value))


@dataclass
class ProjectSubject:
    """Colour-coded category orthogonal to rows."""

    id: str
    name: str
    color: str = DEFAULT_TOPIC_COLORS[0]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color}

    @staticmethod
    def from_dict(data: dict) -> "ProjectSubject":
        return ProjectSubject(
            id=data["id"],
            name=data.get("name", "Subject"),
            color=data.get("color", DEFAULT_TOPIC_COLORS[0]),
        )


@dataclass
class Initiative:
    """Optional grouping across rows, rendered as a rollup at low zoom."""

    id: str
    name: str
    color: str = DEFAULT_TOPIC_COLORS[0]
    row_id: str | None = None
    member_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "row_id": self.row_id,
            "member_ids": list(self.member_ids),
        }

    @staticmethod
    def from_dict(data: dict) -> "Initiative":
        return Initiative(
            id=data["id"],
            name=data.get("name", "Initiative"),
            color=data.get("color", DEFAULT_TOPIC_COLORS[0]),
            row_id=data.get("row_id"),
            member_ids=list(data.get("member_ids", [])),
        )


@dataclass
class Topic:
    id: str
    name: str
    color: str
    collapsed: bool = False
    deliverables: list[Deliverable] = field(default_factory=list)
    kind: str = "lane"

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "collapsed": self.collapsed,
            "deliverables": [d.to_dict() for d in self.deliverables],
        }
        if self.kind != "lane":
            data["kind"] = self.kind
        return data

    @staticmethod
    def from_dict(data: dict) -> "Topic":
        deliverables = [Deliverable.from_dict(d) for d in data.get("deliverables", [])]
        kind = str(data.get("kind", "lane")).lower()
        if kind not in ("lane", "divider"):
            kind = "lane"
        return Topic(
            id=data["id"],
            name=data["name"],
            color=data.get("color", DEFAULT_TOPIC_COLORS[0]),
            collapsed=bool(data.get("collapsed", False)),
            deliverables=deliverables,
            kind=kind,
        )


@dataclass
class CanvasObject:
    id: str
    kind: str
    row_id: str
    start_week: int
    end_week: int
    text: str = ""
    text_align: str = "center"
    text_html: str | None = None
    notes: str = ""
    notes_html: str | None = None
    scope: str = ""
    scope_html: str | None = None
    risks: str = ""
    risks_html: str | None = None
    color: str = DEFAULT_TOPIC_COLORS[0]
    size: int = DEFAULT_SIZE
    z_index: int = 0
    target_row_id: str | None = None
    target_week: int | None = None
    arrow_mid_week: int | None = None
    arrow_head_start: bool = False
    arrow_head_end: bool = True
    arrow_direction: str = "none"
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    opacity: float = TEXTBOX_DEFAULT_OPACITY
    link_source_id: str | None = None
    link_target_id: str | None = None
    link_source_side: str | None = None
    link_source_offset: float | None = None
    link_offset_x: float | None = None
    link_offset_y: float | None = None
    connector_source_id: str | None = None
    connector_target_id: str | None = None
    connector_source_side: str | None = None
    connector_source_offset: float | None = None
    connector_target_side: str | None = None
    connector_target_offset: float | None = None
    subject_id: str | None = None
    predecessors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        arrow_direction = (
            normalize_arrow_direction(self.arrow_direction) if self.kind == "box" else "none"
        )
        # v3 merged "arrow" into the unified "connector"; normalize on write so
        # in-memory legacy arrows round-trip as connectors.
        persisted_kind = "connector" if self.kind == "arrow" else self.kind
        data = {
            "id": self.id,
            "kind": persisted_kind,
            "row_id": self.row_id,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "text": self.text,
            "text_align": self.text_align,
            "text_html": self.text_html,
            "notes": self.notes,
            "notes_html": self.notes_html,
            "scope": self.scope,
            "scope_html": self.scope_html,
            "risks": self.risks,
            "risks_html": self.risks_html,
            "color": self.color,
            "size": self.size,
            "z_index": self.z_index,
            "target_row_id": self.target_row_id,
            "target_week": self.target_week,
            "arrow_mid_week": self.arrow_mid_week,
            "arrow_direction": arrow_direction,
        }
        if self.text_html is None:
            data.pop("text_html")
        if not self.notes:
            data.pop("notes")
        if self.notes_html is None:
            data.pop("notes_html")
        if not self.scope:
            data.pop("scope")
        if self.scope_html is None:
            data.pop("scope_html")
        if not self.risks:
            data.pop("risks")
        if self.risks_html is None:
            data.pop("risks_html")
        if self.x is not None:
            data["x"] = self.x
        if self.y is not None:
            data["y"] = self.y
        if self.width is not None:
            data["width"] = self.width
        if self.height is not None:
            data["height"] = self.height
        if self.opacity != TEXTBOX_DEFAULT_OPACITY:
            data["opacity"] = self.opacity
        if self.link_source_id is not None:
            data["link_source_id"] = self.link_source_id
        if self.link_target_id is not None:
            data["link_target_id"] = self.link_target_id
        if self.link_source_side is not None:
            data["link_source_side"] = self.link_source_side
        if self.link_source_offset is not None:
            data["link_source_offset"] = self.link_source_offset
        if self.link_offset_x is not None:
            data["link_offset_x"] = self.link_offset_x
        if self.link_offset_y is not None:
            data["link_offset_y"] = self.link_offset_y
        if self.connector_source_id is not None:
            data["connector_source_id"] = self.connector_source_id
        if self.connector_target_id is not None:
            data["connector_target_id"] = self.connector_target_id
        if self.connector_source_side is not None:
            data["connector_source_side"] = self.connector_source_side
        if self.connector_source_offset is not None:
            data["connector_source_offset"] = self.connector_source_offset
        if self.connector_target_side is not None:
            data["connector_target_side"] = self.connector_target_side
        if self.connector_target_offset is not None:
            data["connector_target_offset"] = self.connector_target_offset
        if self.arrow_head_start:
            data["arrow_head_start"] = self.arrow_head_start
        if not self.arrow_head_end:
            data["arrow_head_end"] = self.arrow_head_end
        if data.get("arrow_direction") == "none":
            data.pop("arrow_direction")
        if self.subject_id is not None:
            data["subject_id"] = self.subject_id
        if self.predecessors:
            data["predecessors"] = list(self.predecessors)
        return data

    @staticmethod
    def from_dict(data: dict) -> "CanvasObject":
        color = data.get("color")
        if color is None and data.get("kind") == "textbox":
            color = "#FFFFFF"
        arrow_direction = normalize_arrow_direction(data.get("arrow_direction", "none"))
        if data.get("kind") != "box":
            arrow_direction = "none"
        return CanvasObject(
            id=data["id"],
            kind=data["kind"],
            row_id=data["row_id"],
            start_week=int(data["start_week"]),
            end_week=int(data.get("end_week", data["start_week"])),
            text=data.get("text", ""),
            text_align=data.get("text_align", "center"),
            text_html=data.get("text_html"),
            notes=data.get("notes", ""),
            notes_html=data.get("notes_html"),
            scope=data.get("scope", "")
            if "scope" in data
            else data.get("assumptions", ""),
            scope_html=data.get("scope_html")
            if "scope_html" in data
            else data.get("assumptions_html"),
            risks=data.get("risks", ""),
            risks_html=data.get("risks_html"),
            color=color or DEFAULT_TOPIC_COLORS[0],
            size=int(data.get("size", DEFAULT_SIZE)),
            z_index=int(data.get("z_index", 0)),
            target_row_id=data.get("target_row_id"),
            target_week=data.get("target_week"),
            arrow_mid_week=data.get("arrow_mid_week"),
            arrow_head_start=bool(data.get("arrow_head_start", False)),
            arrow_head_end=bool(data.get("arrow_head_end", True)),
            arrow_direction=arrow_direction,
            x=data.get("x"),
            y=data.get("y"),
            width=data.get("width"),
            height=data.get("height"),
            opacity=float(data.get("opacity", TEXTBOX_DEFAULT_OPACITY)),
            link_source_id=data.get("link_source_id"),
            link_target_id=data.get("link_target_id"),
            link_source_side=data.get("link_source_side"),
            link_source_offset=data.get("link_source_offset"),
            link_offset_x=data.get("link_offset_x"),
            link_offset_y=data.get("link_offset_y"),
            connector_source_id=data.get("connector_source_id"),
            connector_target_id=data.get("connector_target_id"),
            connector_source_side=data.get("connector_source_side"),
            connector_source_offset=data.get("connector_source_offset"),
            connector_target_side=data.get("connector_target_side"),
            connector_target_offset=data.get("connector_target_offset"),
            subject_id=data.get("subject_id"),
            predecessors=[str(p) for p in data.get("predecessors", [])],
        )


class ProjectModel(QObject):
    model_reset = pyqtSignal()
    objects_changed = pyqtSignal()
    rows_changed = pyqtSignal()
    metadata_changed = pyqtSignal()

    def __init__(self, year: int) -> None:
        super().__init__()
        self.year = year
        self.topics: list[Topic] = []
        self.objects: dict[str, CanvasObject] = {}
        self.classification = DEFAULT_CLASSIFICATION
        self.symbol_overlap_tolerance_percent = 20
        self.classification_size = CLASSIFICATION_SIZE_DEFAULT
        self.subjects: list[ProjectSubject] = []
        self.initiatives: list[Initiative] = []
        self.dependencies_auto_reschedule = False
        self.ignored_issues: list[str] = []

    @staticmethod
    def normalize_overlap_tolerance(value) -> int:
        try:
            if isinstance(value, bool):
                return 20
            return max(0, min(30, int(value)))
        except (ValueError, TypeError, OverflowError):
            return 20

    # --- Subjects ----------------------------------------------------------
    def add_subject(self, name: str, color: str | None = None) -> ProjectSubject:
        if color is None:
            color = DEFAULT_TOPIC_COLORS[len(self.subjects) % len(DEFAULT_TOPIC_COLORS)]
        subject = ProjectSubject(id=new_id(), name=name, color=color)
        self.subjects.append(subject)
        self.metadata_changed.emit()
        return subject

    def get_subject(self, subject_id: str | None) -> ProjectSubject | None:
        if subject_id is None:
            return None
        for subject in self.subjects:
            if subject.id == subject_id:
                return subject
        return None

    def set_subjects(self, subjects: list[ProjectSubject]) -> None:
        self.subjects = list(subjects)
        self.metadata_changed.emit()

    # --- Initiatives -------------------------------------------------------
    def add_initiative(self, name: str, color: str | None = None,
                       row_id: str | None = None) -> Initiative:
        if color is None:
            color = DEFAULT_TOPIC_COLORS[len(self.initiatives) % len(DEFAULT_TOPIC_COLORS)]
        initiative = Initiative(id=new_id(), name=name, color=color, row_id=row_id)
        self.initiatives.append(initiative)
        self.metadata_changed.emit()
        return initiative

    def get_initiative(self, initiative_id: str | None) -> Initiative | None:
        if initiative_id is None:
            return None
        for initiative in self.initiatives:
            if initiative.id == initiative_id:
                return initiative
        return None

    def set_initiatives(self, initiatives: list[Initiative]) -> None:
        self.initiatives = list(initiatives)
        self.metadata_changed.emit()

    def set_year(self, year: int) -> None:
        if self.year != year:
            self.year = year
            self.metadata_changed.emit()

    def normalize_classification(
        self, text: str | None, size: int | None
    ) -> tuple[str, int]:
        cleaned = (text or "").strip()
        if not cleaned:
            cleaned = DEFAULT_CLASSIFICATION
        if size is None:
            size_value = self.classification_size
        else:
            try:
                size_value = int(size)
            except (TypeError, ValueError):
                size_value = self.classification_size
        size_value = max(CLASSIFICATION_SIZE_MIN, min(CLASSIFICATION_SIZE_MAX, size_value))
        return cleaned, size_value

    def set_classification(self, text: str | None, size: int | None = None) -> None:
        cleaned, size_value = self.normalize_classification(text, size)
        if cleaned == self.classification and size_value == self.classification_size:
            return
        self.classification = cleaned
        self.classification_size = size_value
        self.metadata_changed.emit()

    def classification_label(self) -> str:
        return (self.classification or "").strip() or DEFAULT_CLASSIFICATION

    def add_topic(self, name: str, color: str | None = None) -> Topic:
        if color is None:
            color = DEFAULT_TOPIC_COLORS[len(self.topics) % len(DEFAULT_TOPIC_COLORS)]
        topic = Topic(id=new_id(), name=name, color=color)
        self.insert_topic(topic)
        return topic

    def update_topic(self, topic_id: str, new_topic: Topic) -> None:
        for index, topic in enumerate(self.topics):
            if topic.id == topic_id:
                self.topics[index] = new_topic
                self.rows_changed.emit()
                return

    def insert_topic(self, topic: Topic, index: int | None = None) -> None:
        if index is None:
            self.topics.append(topic)
        else:
            self.topics.insert(index, topic)
        self.rows_changed.emit()

    def set_topics(self, topics: list[Topic]) -> None:
        self.topics = list(topics)
        self.rows_changed.emit()

    def remove_topic(self, topic_id: str) -> Topic | None:
        for index, topic in enumerate(self.topics):
            if topic.id == topic_id:
                removed = self.topics.pop(index)
                self.rows_changed.emit()
                return removed
        return None

    def add_deliverable(self, topic_id: str, name: str) -> Deliverable | None:
        topic = self.get_topic(topic_id)
        if topic is None:
            return None
        deliverable = Deliverable(id=new_id(), name=name)
        self.insert_deliverable(topic_id, deliverable)
        return deliverable

    def insert_deliverable(self, topic_id: str, deliverable: Deliverable, index: int | None = None) -> None:
        topic = self.get_topic(topic_id)
        if topic is None:
            return
        if index is None:
            topic.deliverables.append(deliverable)
        else:
            topic.deliverables.insert(index, deliverable)
        self.rows_changed.emit()

    def update_deliverable(self, deliverable_id: str, new_deliverable: Deliverable) -> None:
        for topic in self.topics:
            for index, deliverable in enumerate(topic.deliverables):
                if deliverable.id == deliverable_id:
                    topic.deliverables[index] = new_deliverable
                    self.rows_changed.emit()
                    return

    def remove_deliverable(self, deliverable_id: str) -> Deliverable | None:
        for topic in self.topics:
            for index, deliverable in enumerate(topic.deliverables):
                if deliverable.id == deliverable_id:
                    removed = topic.deliverables.pop(index)
                    self.rows_changed.emit()
                    return removed
        return None

    def find_deliverable(self, deliverable_id: str) -> tuple[Topic, int, Deliverable] | None:
        for topic in self.topics:
            for index, deliverable in enumerate(topic.deliverables):
                if deliverable.id == deliverable_id:
                    return topic, index, deliverable
        return None

    def move_deliverable(self, deliverable_id: str, new_index: int) -> bool:
        found = self.find_deliverable(deliverable_id)
        if found is None:
            return False
        topic, index, deliverable = found
        if not topic.deliverables:
            return False
        new_index = max(0, min(new_index, len(topic.deliverables) - 1))
        if new_index == index:
            return False
        topic.deliverables.pop(index)
        topic.deliverables.insert(new_index, deliverable)
        self.rows_changed.emit()
        return True

    def move_deliverable_to_topic(
        self,
        deliverable_id: str,
        target_topic_id: str,
        target_index: int | None = None,
    ) -> bool:
        found = self.find_deliverable(deliverable_id)
        if found is None:
            return False
        source_topic, source_index, deliverable = found
        target_topic = self.get_topic(target_topic_id)
        if target_topic is None:
            return False
        if source_topic.id == target_topic_id:
            if target_index is None:
                return False
            new_index = max(0, min(target_index, len(source_topic.deliverables) - 1))
            if new_index == source_index:
                return False
            source_topic.deliverables.pop(source_index)
            source_topic.deliverables.insert(new_index, deliverable)
            self.rows_changed.emit()
            return True

        source_topic.deliverables.pop(source_index)
        if target_index is None:
            target_index = len(target_topic.deliverables)
        target_index = max(0, min(target_index, len(target_topic.deliverables)))
        target_topic.deliverables.insert(target_index, deliverable)
        self.rows_changed.emit()
        return True

    def toggle_topic_collapsed(self, topic_id: str) -> None:
        topic = self.get_topic(topic_id)
        if topic is None:
            return
        topic.collapsed = not topic.collapsed
        self.rows_changed.emit()

    def get_topic(self, topic_id: str) -> Topic | None:
        for topic in self.topics:
            if topic.id == topic_id:
                return topic
        return None

    def find_row(self, row_id: str) -> tuple[str, Topic, Deliverable | None] | None:
        for topic in self.topics:
            if topic.id == row_id:
                return "topic", topic, None
            for deliverable in topic.deliverables:
                if deliverable.id == row_id:
                    return "deliverable", topic, deliverable
        return None

    def topic_for_row(self, row_id: str) -> Topic | None:
        result = self.find_row(row_id)
        if result is None:
            return None
        return result[1]

    def add_object(self, obj: CanvasObject) -> None:
        self.objects[obj.id] = obj
        self.objects_changed.emit()

    def update_object(self, obj_id: str, new_obj: CanvasObject) -> None:
        if obj_id not in self.objects:
            return
        self.objects[obj_id] = new_obj
        self.objects_changed.emit()

    def remove_object(self, obj_id: str) -> None:
        if obj_id not in self.objects:
            return
        del self.objects[obj_id]
        self.objects_changed.emit()

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "year": self.year,
            "classification": self.classification,
            "symbol_overlap_tolerance_percent": self.symbol_overlap_tolerance_percent,
            "classification_size": self.classification_size,
            "topics": [topic.to_dict() for topic in self.topics],
            "objects": [obj.to_dict() for obj in self.objects.values()],
            "subjects": [subject.to_dict() for subject in self.subjects],
            "initiatives": [initiative.to_dict() for initiative in self.initiatives],
            "dependencies_auto_reschedule": self.dependencies_auto_reschedule,
            "ignored_issues": list(self.ignored_issues),
        }

    @staticmethod
    def from_dict(data: dict) -> "ProjectModel":
        schema_version = data.get("schema_version", 0)
        if schema_version not in (1, 2, SCHEMA_VERSION):
            raise ValueError(f"Unsupported schema version: {schema_version}")
        model = ProjectModel(year=int(data.get("year", 2026)))
        model.symbol_overlap_tolerance_percent = model.normalize_overlap_tolerance(
            data.get("symbol_overlap_tolerance_percent", 20)
        )
        classification, classification_size = model.normalize_classification(
            data.get("classification"), data.get("classification_size")
        )
        model.classification = classification
        model.classification_size = classification_size
        model.topics = [Topic.from_dict(t) for t in data.get("topics", [])]

        def _load_object(raw: dict) -> "CanvasObject":
            # v3 merged the free-standing "arrow" into the unified "connector".
            payload = dict(raw)
            if payload.get("kind") == "arrow":
                payload["kind"] = "connector"
            return CanvasObject.from_dict(payload)

        # The standalone "Activity Text" object was removed from the app; legacy
        # instances in older files are dropped on load rather than resurrected.
        model.objects = {
            obj.id: obj
            for obj in (_load_object(o) for o in data.get("objects", []))
            if obj.kind != "text"
        }
        model.subjects = [ProjectSubject.from_dict(s) for s in data.get("subjects", [])]
        model.initiatives = [Initiative.from_dict(i) for i in data.get("initiatives", [])]
        model.dependencies_auto_reschedule = bool(
            data.get("dependencies_auto_reschedule", False)
        )
        model.ignored_issues = [str(k) for k in data.get("ignored_issues", [])]
        # v1 files predate dependencies; keep behavior unchanged by not inventing links.
        return model

    def clone_object(self, obj_id: str, **overrides) -> CanvasObject | None:
        obj = self.objects.get(obj_id)
        if obj is None:
            return None
        return replace(obj, id=new_id(), **overrides)

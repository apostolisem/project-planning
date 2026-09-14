"""Read-only tabular projection of the plan, synced to the canvas selection."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTableView, QVBoxLayout, QWidget
from .week_format import format_year_week

_NON_PLANNABLE = {"link", "connector", "arrow"}


def _object_type_label(obj) -> str:
    return "Event" if obj.kind == "circle" else obj.kind.title()


class PlanTableModel(QAbstractTableModel):
    COLUMNS = [
        "Type", "Title", "Section", "Subject", "Start", "End",
        "Weeks", "Predecessors", "Initiative",
    ]

    def __init__(self, model, layout=None, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.layout = layout
        self._rows: list = []

    def refresh(self) -> None:
        self.beginResetModel()
        objects = [
            obj for obj in self.model.objects.values()
            if obj.kind not in _NON_PLANNABLE
        ]

        def row_order(obj):
            if self.layout is not None and obj.row_id in self.layout.row_map:
                return self.layout.row_map[obj.row_id].y
            return 1e9

        objects.sort(key=lambda o: (row_order(o), o.start_week, o.row_id))
        self._rows = objects
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return section + 1

    def object_id(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].id
        return None

    def _week_label(self, week: int) -> str:
        if self.layout is None:
            return str(week)
        year, week_in_year = self.layout.week_index_to_year_week(self.model.year, week)
        return format_year_week(year, week_in_year)

    def _row_name(self, row_id: str) -> str:
        if self.layout is not None and row_id in self.layout.row_map:
            return self.layout.row_map[row_id].name
        return row_id

    def _initiative_name(self, obj_id: str) -> str:
        for initiative in self.model.initiatives:
            if obj_id in initiative.member_ids:
                return initiative.name
        return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        obj = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return _object_type_label(obj)
        if column == 1:
            return obj.text or ""
        if column == 2:
            return self._row_name(obj.row_id)
        if column == 3:
            subject = self.model.get_subject(obj.subject_id)
            return subject.name if subject else ""
        if column == 4:
            return self._week_label(obj.start_week)
        if column == 5:
            return self._week_label(obj.end_week)
        if column == 6:
            return max(1, obj.end_week - obj.start_week + 1)
        if column == 7:
            labels = []
            for pred_id in obj.predecessors or []:
                pred = self.model.objects.get(pred_id)
                labels.append((pred.text or _object_type_label(pred)) if pred else f"{pred_id} (missing)")
            return ", ".join(labels)
        if column == 8:
            return self._initiative_name(obj.id)
        return None


class PlanTableDialog(QDialog):
    object_activated = pyqtSignal(str)

    def __init__(self, model, layout, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plan table")
        self.resize(1000, 520)
        layout_v = QVBoxLayout(self)
        hint = QLabel("Double-click a row to reveal it on the canvas.")
        hint.setObjectName("dialogHint")
        layout_v.addWidget(hint)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table_model = PlanTableModel(model, layout, self)
        self.table_model.refresh()
        self.table.setModel(self.table_model)
        self.table.doubleClicked.connect(self._activate)
        layout_v.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout_v.addWidget(buttons)

    def _activate(self, index) -> None:
        obj_id = self.table_model.object_id(index.row())
        if obj_id:
            self.object_activated.emit(obj_id)

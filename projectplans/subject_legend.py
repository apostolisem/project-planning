"""Subject colour legend with click-to-focus filtering."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget

from . import theme


class SubjectLegend(QWidget):
    filter_changed = pyqtSignal(object)  # subject id or None to clear
    add_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("subjectLegend")
        self._dark_mode = False
        self._model = None
        self._active_id: str | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)
        title = QLabel("SUBJECTS")
        title.setObjectName("legendTitle")
        layout.addWidget(title)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setFixedHeight(34)
        self._chips_host = QWidget()
        self._chips = QHBoxLayout(self._chips_host)
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(6)
        self._chips.addStretch()
        self._scroll.setWidget(self._chips_host)
        layout.addWidget(self._scroll, 1)
        self._empty = QLabel("No subjects yet")
        self._empty.setObjectName("legendEmpty")
        layout.addWidget(self._empty)
        add = QPushButton("+")
        add.setObjectName("legendAdd")
        add.setFixedSize(26, 26)
        add.setToolTip("Add subject")
        add.clicked.connect(self.add_requested.emit)
        layout.addWidget(add)

    def set_model(self, model) -> None:
        self._model = model
        t = theme.tokens(self._dark_mode)
        while self._chips.count() > 1:
            item = self._chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        subjects = list(getattr(model, "subjects", []))
        self._empty.setVisible(not subjects)
        for subject in subjects:
            chip = QPushButton(f"● {subject.name}")
            chip.setCheckable(True)
            chip.setChecked(subject.id == self._active_id)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { text-align: left; padding: 3px 9px; font-size: 11px;"
                f" border: 1px solid {subject.color}; border-radius: 12px;"
                f" color: {t['text']}; background: {t['card']}; }}"
                f"QPushButton:checked {{ background: {t['hover']}; font-weight: 700; }}"
            )
            chip.setProperty("subjectId", subject.id)
            chip.clicked.connect(lambda _=False, sid=subject.id: self._toggle(sid))
            self._chips.insertWidget(self._chips.count() - 1, chip)

    def set_dark_mode(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        if self._model is not None:
            self.set_model(self._model)

    def _toggle(self, subject_id: str) -> None:
        self._active_id = None if self._active_id == subject_id else subject_id
        for index in range(self._chips.count()):
            widget = self._chips.itemAt(index).widget()
            if isinstance(widget, QPushButton) and widget.property("subjectId"):
                widget.setChecked(widget.property("subjectId") == self._active_id)
        self.filter_changed.emit(self._active_id)

    def active_subject_id(self) -> str | None:
        return self._active_id

    def clear_filter(self) -> None:
        if self._active_id is None:
            return
        self._active_id = None
        if hasattr(self, "_model"):
            self.set_model(self._model)
        self.filter_changed.emit(None)

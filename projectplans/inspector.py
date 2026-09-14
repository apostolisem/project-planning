from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
    QColorDialog,
    QTextEdit,
)

from .constants import TEXT_SIZE_MAX, TEXT_SIZE_MIN, TEXT_SIZE_STEP, WEEK_INDEX_MAX, WEEK_INDEX_MIN
from .text_shortcuts import apply_text_action, extract_text_payload, text_shortcut_action


from .edit_fields import RichField as _MetadataTextEdit, WeekField as _WeekSpinBox, SessionSpinBox
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QHBoxLayout, QToolButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt


class InspectorPanel(QWidget):
    draft_changed = pyqtSignal()
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self._current_obj_id = None
        self._row_ids = []
        self._suppress_metadata_refresh = {"scope": None, "risks": None, "notes": None}

        self.type_label = QLabel("-")
        self.text_input = _MetadataTextEdit(single_line=True)
        self.start_week = _WeekSpinBox()
        self.duration_weeks = SessionSpinBox()
        self.row_combo = QComboBox()
        self.target_week = _WeekSpinBox()
        self.end_week = _WeekSpinBox()
        self.feedback = QLabel()
        self.endpoints = QLabel()
        self.endpoints.setWordWrap(True)
        self._selected_ids = []
        self._refreshing = False
        self._committing = False
        self.target_row_combo = QComboBox()
        self.size_spin = SessionSpinBox()
        self.subject_combo = QComboBox()
        self.subject_combo.setObjectName("subjectCombo")
        self.subject_combo.setMinimumWidth(120)
        self.subject_combo.setAccessibleName("Subject")
        self.arrowheads_combo = QComboBox()
        self.arrow_direction_combo = QComboBox()
        self.reverse_direction_button = QPushButton("Reverse")
        self.align_combo = QComboBox()
        self.color_button = QPushButton("Color")
        self.opacity_spin = SessionSpinBox()
        self.scope_edit = _MetadataTextEdit()
        self.risks_edit = _MetadataTextEdit()
        self.notes_edit = _MetadataTextEdit()
        self.predecessor_combo = QComboBox()
        self.predecessor_list = QListWidget()
        self.predecessor_combo.setAccessibleName("Add predecessor")
        self.predecessor_list.setAccessibleName("Predecessors")
        self.add_predecessor_button = QPushButton("Add")
        self.remove_predecessor_button = QPushButton("Remove")
        self.risks_help = QLabel(
            "One per line. Optional ;probability;impact (h/m/l). "
            "Example: development of helper script;m;l"
        )
        self.risks_help.setWordWrap(True)
        help_font = self.risks_help.font()
        if help_font.pointSize() > 0:
            help_font.setPointSize(max(8, help_font.pointSize() - 2))
        self.risks_help.setFont(help_font)

        self.start_week.setRange(WEEK_INDEX_MIN, WEEK_INDEX_MAX)
        self.duration_weeks.setRange(1, WEEK_INDEX_MAX - WEEK_INDEX_MIN + 1)
        self.target_week.setRange(WEEK_INDEX_MIN, WEEK_INDEX_MAX)
        self.size_spin.setRange(1, 5)
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix("%")

        self.setObjectName("contextEditor")
        self._details_visible = True
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(10)
        self.type_label.setObjectName("inspectorContext")
        outer.addWidget(self.type_label)

        self.empty_state = QLabel("Select an object to edit its details.")
        self.empty_state.setObjectName("inspectorEmptyState")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.empty_state, 1)

        self.editor_body = QWidget()
        self.editor_body.setObjectName("inspectorEditorBody")
        editor_layout = QVBoxLayout(self.editor_body)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)

        self.title_group = QWidget()
        title_layout = QVBoxLayout(self.title_group)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        self.title_label = QLabel("TITLE")
        self.title_label.setObjectName("sectionCaption")
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.text_input)
        editor_layout.addWidget(self.title_group)

        self.quick_group = QWidget()
        self.quick_group.setObjectName("inspectorSection")
        quick_layout = QGridLayout(self.quick_group)
        quick_layout.setContentsMargins(10, 9, 10, 10)
        quick_layout.setHorizontalSpacing(8)
        quick_layout.setVerticalSpacing(6)
        quick_caption = QLabel("STYLE & ASSIGNMENT")
        quick_caption.setObjectName("sectionCaption")
        quick_layout.addWidget(quick_caption, 0, 0, 1, 2)
        self.color_label = QLabel("Color")
        quick_layout.addWidget(self.color_label, 1, 0)
        quick_layout.addWidget(self.color_button, 1, 1)
        self.size_label = QLabel("Size")
        quick_layout.addWidget(self.size_label, 2, 0)
        quick_layout.addWidget(self.size_spin, 2, 1)
        self.subject_label = QLabel("Subject")
        quick_layout.addWidget(self.subject_label, 3, 0)
        quick_layout.addWidget(self.subject_combo, 3, 1)
        self.context_labels = {
            self.text_input: self.title_label,
            self.color_button: self.color_label,
            self.size_spin: self.size_label,
            self.subject_combo: self.subject_label,
        }
        for row, (label, field) in enumerate([
            ("Arrow direction", self.arrow_direction_combo),
            ("Alignment", self.align_combo),
            ("Opacity", self.opacity_spin),
        ], start=4):
            caption = QLabel(label)
            self.context_labels[field] = caption
            quick_layout.addWidget(caption, row, 0)
            quick_layout.addWidget(field, row, 1)
        quick_layout.setColumnStretch(1, 1)
        editor_layout.addWidget(self.quick_group)

        self.schedule_group = QWidget()
        self.schedule_group.setObjectName("inspectorSection")
        schedule_layout = QVBoxLayout(self.schedule_group)
        schedule_layout.setContentsMargins(10, 9, 10, 10)
        schedule_layout.setSpacing(6)
        schedule_caption = QLabel("SCHEDULE")
        schedule_caption.setObjectName("sectionCaption")
        schedule_layout.addWidget(schedule_caption)
        schedule = QFormLayout()
        schedule.setContentsMargins(0, 0, 0, 0)
        schedule.setHorizontalSpacing(8)
        schedule.setVerticalSpacing(6)
        schedule.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label, field in [("Row", self.row_combo), ("Start", self.start_week),
                             ("End", self.end_week), ("Duration", self.duration_weeks)]:
            caption = QLabel(label)
            self.context_labels[field] = caption
            schedule.addRow(caption, field)
        for label, field in [("Target week", self.target_week), ("Target row", self.target_row_combo)]:
            caption = QLabel(label)
            self.context_labels[field] = caption
            schedule.addRow(caption, field)
        self.endpoints_label = QLabel("Connection")
        schedule.addRow(self.endpoints_label, self.endpoints)
        self.arrowheads_label = QLabel("Arrowheads")
        self.context_labels[self.arrowheads_combo] = self.arrowheads_label
        schedule.addRow(self.arrowheads_label, self.arrowheads_combo)
        schedule_layout.addLayout(schedule)
        schedule_layout.addWidget(self.reverse_direction_button)
        editor_layout.addWidget(self.schedule_group)

        self.feedback.setObjectName("inspectorFeedback")
        editor_layout.addWidget(self.feedback)
        self.details = QTabWidget()
        for label, field in [("Scope", self.scope_edit), ("Risks", self.risks_edit), ("Notes", self.notes_edit)]:
            tab = QWidget()
            box = QVBoxLayout(tab)
            formatting = QHBoxLayout()
            for text, action in [("B", "bold"), ("I", "italic"), ("U", "underline"), ("S", "strikethrough"), ("A+", "increase"), ("A−", "decrease")]:
                button = QToolButton()
                button.setText(text)
                button.setToolTip(action.replace('_', ' ').title())
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.clicked.connect(lambda checked=False, f=field, a=action: f.format_action(a))
                formatting.addWidget(button)
            formatting.addStretch()
            box.addLayout(formatting)
            box.addWidget(field)
            if label == "Risks":
                box.addWidget(self.risks_help)
            self.details.addTab(tab, label)
        # Dependencies tab (appended after Notes so tab indices stay stable).
        deps_tab = QWidget()
        deps_layout = QVBoxLayout(deps_tab)
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Add predecessor"))
        add_row.addWidget(self.predecessor_combo, 1)
        add_row.addWidget(self.add_predecessor_button)
        deps_layout.addLayout(add_row)
        deps_layout.addWidget(self.predecessor_list, 1)
        deps_layout.addWidget(self.remove_predecessor_button)
        self.details.addTab(deps_tab, "Dependencies")
        self.add_predecessor_button.clicked.connect(self._apply_add_predecessor)
        self.remove_predecessor_button.clicked.connect(self._apply_remove_predecessor)
        self.details.setObjectName("inspectorTabs")
        self.details.setMinimumHeight(220)
        editor_layout.addWidget(self.details, 1)
        outer.addWidget(self.editor_body, 1)
        self._set_editor_mode("empty")
        self.end_week.valueChanged.connect(self._apply_end_week)
        for week_field in (self.start_week, self.end_week, self.target_week):
            week_field.invalid.connect(self.feedback.setText)

        self.text_input.editingFinished.connect(self._apply_text)
        self.start_week.valueChanged.connect(self._apply_start_week)
        self.duration_weeks.editingFinished.connect(self._apply_duration)
        self.row_combo.currentIndexChanged.connect(self._apply_row)
        self.target_week.valueChanged.connect(self._apply_target_week)
        self.target_row_combo.currentIndexChanged.connect(self._apply_target_row)
        self.size_spin.editingFinished.connect(self._apply_size)
        self.subject_combo.currentIndexChanged.connect(self._apply_subject)
        self.arrowheads_combo.currentIndexChanged.connect(self._apply_arrowheads)
        self.arrow_direction_combo.currentIndexChanged.connect(self._apply_arrow_direction)
        self.reverse_direction_button.clicked.connect(self._reverse_direction)
        self.align_combo.currentIndexChanged.connect(self._apply_alignment)
        self.color_button.clicked.connect(self._pick_color)
        self.opacity_spin.editingFinished.connect(self._apply_opacity)
        self.scope_edit.commit_requested.connect(self._apply_scope)
        self.risks_edit.commit_requested.connect(self._apply_risks)
        self.notes_edit.commit_requested.connect(self._apply_notes)

        for field in (self.text_input, self.scope_edit, self.risks_edit, self.notes_edit):
            field.textChanged.connect(lambda: self.draft_changed.emit() if not self._refreshing else None)
        self.set_enabled(False)
        self.align_combo.addItem("Left", "left")
        self.align_combo.addItem("Center", "center")
        self.align_combo.addItem("Right", "right")
        self.arrowheads_combo.addItem("End", "end")
        self.arrowheads_combo.addItem("Start", "start")
        self.arrowheads_combo.addItem("Both", "both")
        self.arrow_direction_combo.addItem("None", "none")
        self.arrow_direction_combo.addItem("Left", "left")
        self.arrow_direction_combo.addItem("Right", "right")

    def set_details_visible(self, visible: bool) -> None:
        """Compatibility helper for showing the secondary editor tabs."""
        self._details_visible = bool(visible)
        self.details.setVisible(self._details_visible)

    def details_visible(self) -> bool:
        return self._details_visible

    def _set_editor_mode(self, mode: str) -> None:
        empty = mode == "empty"
        bulk = mode == "bulk"
        self.empty_state.setVisible(empty)
        self.editor_body.setVisible(not empty)
        self.title_group.setVisible(not bulk)
        self.schedule_group.setVisible(not bulk)
        self.details.setVisible(not bulk)
        self._details_visible = not bulk
        self.subject_label.setVisible(not bulk)
        self.subject_combo.setVisible(not bulk)

    def set_enabled(self, enabled: bool) -> None:
        self.text_input.setEnabled(enabled)
        self.start_week.setEnabled(enabled)
        self.duration_weeks.setEnabled(enabled)
        self.row_combo.setEnabled(enabled)
        self.target_week.setEnabled(enabled)
        self.target_row_combo.setEnabled(enabled)
        self.size_spin.setEnabled(enabled)
        self.arrowheads_combo.setEnabled(enabled)
        self.arrow_direction_combo.setEnabled(enabled)
        self.reverse_direction_button.setEnabled(enabled)
        self.align_combo.setEnabled(enabled)
        self.color_button.setEnabled(enabled)
        self.opacity_spin.setEnabled(enabled)
        self.subject_combo.setEnabled(enabled)
        self.predecessor_combo.setEnabled(enabled)
        self.add_predecessor_button.setEnabled(enabled)
        self.predecessor_list.setEnabled(enabled)
        self.remove_predecessor_button.setEnabled(enabled)
        self.scope_edit.setEnabled(enabled)
        self.risks_edit.setEnabled(enabled)
        self.notes_edit.setEnabled(enabled)

    def refresh_rows(self, layout, model) -> None:
        self.start_week.set_context(layout, model)
        self.end_week.set_context(layout, model)
        self.target_week.set_context(layout, model)
        rows = layout.rows
        self._row_ids = [row.row_id for row in rows]
        current_obj = model.objects.get(self._current_obj_id) if self._current_obj_id else None
        row_value = current_obj.row_id if current_obj else self.row_combo.currentData()
        target_value = (
            (current_obj.target_row_id or current_obj.row_id)
            if current_obj
            else self.target_row_combo.currentData()
        )
        with QSignalBlocker(self.row_combo), QSignalBlocker(self.target_row_combo):
            self.row_combo.clear()
            self.target_row_combo.clear()
            for row in rows:
                label = row.name
                if row.indent:
                    label = "  " * row.indent + label
                self.row_combo.addItem(label, row.row_id)
                self.target_row_combo.addItem(label, row.row_id)
            if row_value:
                self._set_combo_value(self.row_combo, row_value)
            if target_value:
                self._set_combo_value(self.target_row_combo, target_value)
        self._populate_subjects(model, current_obj)

    def _populate_subjects(self, model, current_obj) -> None:
        subject_id = current_obj.subject_id if current_obj else None
        with QSignalBlocker(self.subject_combo):
            self.subject_combo.clear()
            self.subject_combo.addItem("No subject", None)
            for subject in model.subjects:
                self.subject_combo.addItem(subject.name, subject.id)
            self._set_combo_value(self.subject_combo, subject_id)

    def has_pending(self):
        if not self._current_obj_id:
            return False
        return any(field.toHtml() != field._loaded_html for field in
                   (self.text_input, self.scope_edit, self.risks_edit, self.notes_edit))

    def commit_pending(self):
        if self._committing or self._refreshing or not self._current_obj_id:
            return
        self._committing = True
        try:
            self._apply_text()
            for field, method in [(self.scope_edit, self._apply_scope), (self.risks_edit, self._apply_risks),
                                  (self.notes_edit, self._apply_notes)]:
                method()
            for field in (self.start_week, self.end_week, self.target_week):
                if not field.isHidden():
                    field._commit()
            self._apply_size()
            if not self.duration_weeks.isHidden():
                self._apply_duration()
            if not self.opacity_spin.isHidden():
                self._apply_opacity()
        finally:
            self._committing = False

    def set_selected_objects(self, ids):
        if self._committing:
            return
        if ids != self._selected_ids:
            self.commit_pending()
        self._selected_ids = list(ids)
        obj = self.controller.model.objects.get(ids[0]) if len(ids) == 1 else None
        self.set_selected_object(obj)
        if len(ids) > 1:
            self._set_editor_mode("bulk")
            self.type_label.setText(f"{len(ids)} objects selected")
            objects = [self.controller.model.objects[i] for i in ids]
            self.color_button.setEnabled(all(o.kind != 'link' for o in objects))
            self.size_spin.setEnabled(all(o.kind not in ('link', 'textbox') for o in objects))
            colors = {o.color for o in objects}
            self.color_button.setText("Mixed colors" if len(colors) > 1 else "Color")
            self.size_spin.setMinimum(0)
            self.size_spin.setSpecialValueText("Mixed")
            with QSignalBlocker(self.size_spin):
                sizes = {o.size for o in objects}
                self.size_spin.setValue(next(iter(sizes)) if len(sizes) == 1 else 0)
        else:
            self.size_spin.setMinimum(1)
            self.color_button.setText("Color")

    def set_selected_object(self, obj) -> None:
        self._refreshing = True
        try:
            self._current_obj_id = obj.id if obj else None
            self.set_enabled(obj is not None)
            self.end_week.setEnabled(obj is not None)
            self.details.setEnabled(obj is not None)
            self.feedback.clear()
            if obj is None:
                self._set_editor_mode("empty")
                for field in (self.row_combo, self.start_week, self.end_week, self.duration_weeks):
                    self._set_field_visible(field, False)
                self.color_button.show()
                self.size_spin.show()
                self.text_input.show()
                self.arrowheads_combo.hide()
                self.reverse_direction_button.hide()
                self.type_label.setText("No selection")
                for field in (self.text_input, self.scope_edit, self.risks_edit, self.notes_edit):
                    field.load_payload('', None)
                self.endpoints.clear()
                self._populate_predecessors(None)
                return
            self._set_editor_mode("single")
            names = {
                "box": "Task",
                "circle": "Event",
                "connector": "Connector",
                "arrow": "Connector",
                "link": "Textbox link",
            }
            self.type_label.setText(names.get(obj.kind, obj.kind.title()))
            for field, text, html in [(self.text_input, obj.text, obj.text_html),
                                      (self.scope_edit, obj.scope, obj.scope_html),
                                      (self.risks_edit, obj.risks, obj.risks_html),
                                      (self.notes_edit, obj.notes, obj.notes_html)]:
                field.load_payload(text, html)
            for field, value in [(self.start_week, obj.start_week), (self.end_week, obj.end_week),
                                 (self.duration_weeks, max(1, obj.end_week - obj.start_week + 1)),
                                 (self.target_week, obj.target_week if obj.target_week is not None else obj.end_week),
                                 (self.size_spin, obj.size), (self.opacity_spin, round(obj.opacity * 100))]:
                with QSignalBlocker(field):
                    field.setValue(value)
            for combo, value in [(self.row_combo, obj.row_id), (self.target_row_combo, obj.target_row_id or obj.row_id),
                                 (self.align_combo, obj.text_align), (self.arrowheads_combo, self._arrowheads_value(obj)),
                                 (self.arrow_direction_combo, self._arrow_direction_value(obj)),
                                 (self.subject_combo, obj.subject_id)]:
                with QSignalBlocker(combo):
                    self._set_combo_value(combo, value)
            self._set_color_button(obj.color)
            self._toggle_fields_for_kind(obj.kind)
            point_object = obj.kind in ('milestone', 'deadline')
            self._set_field_visible(self.start_week, not point_object)
            self._set_field_visible(self.end_week, obj.kind == 'box' or point_object)
            self._set_field_visible(self.duration_weeks, obj.kind == 'box')
            self.context_labels[self.end_week].setText('End')
            source = self.controller.model.objects.get(obj.connector_source_id or obj.link_source_id)
            target = self.controller.model.objects.get(obj.connector_target_id or obj.link_target_id)
            self.endpoints.setText(f"{source.text or source.kind} → {target.text or target.kind}" if source and target else '')
            has_endpoints = bool(source and target)
            self.endpoints.setVisible(has_endpoints)
            self.endpoints_label.setVisible(has_endpoints)
            free_connector = obj.kind in ("connector", "arrow") and not (
                obj.connector_source_id and obj.connector_target_id
            )
            if free_connector:
                # Free connectors are week/row anchored and expose those fields.
                self._set_field_visible(self.start_week, True)
                self._set_field_visible(self.row_combo, True)
                self._set_field_visible(self.target_week, True)
                self._set_field_visible(self.target_row_combo, True)
            self._populate_predecessors(obj)
        finally:
            self._refreshing = False

    def _apply_end_week(self):
        obj = self.controller.model.objects.get(self._current_obj_id)
        if not obj:
            return
        point_object = obj.kind in ('milestone', 'deadline')
        if point_object:
            week = self.end_week.value()
            self.controller.update_object(
                obj.id,
                {"start_week": week, "end_week": week},
                "Edit End Week",
            )
            return
        if self.end_week.value() < obj.start_week:
            self.feedback.setText("End week must be on or after start week.")
            self.end_week.setValue(obj.end_week)
            return
        self.controller.update_object(obj.id, {"end_week": self.end_week.value()}, "Edit End Week")
        with QSignalBlocker(self.duration_weeks):
            self.duration_weeks.setValue(self.end_week.value() - obj.start_week + 1)

    def _toggle_fields_for_kind(self, kind: str) -> None:
        is_arrow = kind == "arrow"
        is_milestone = kind == "milestone"
        is_circle = kind == "circle"
        is_deadline = kind == "deadline"
        is_textbox = kind == "textbox"
        is_link = kind == "link"
        is_connector = kind == "connector"
        is_box = kind == "box"
        self._set_field_visible(self.text_input, not is_link)
        self._set_field_visible(
            self.duration_weeks,
            not is_link
            and not is_connector
            and not is_arrow
            and not is_milestone
            and not is_circle
            and not is_deadline
            and not is_textbox,
        )
        self._set_field_visible(self.target_week, False)
        self._set_field_visible(self.target_row_combo, False)
        self._set_field_visible(
            self.row_combo,
            not is_link
            and not is_connector
            and not is_textbox
            and not is_deadline
            and not is_arrow,
        )
        self._set_field_visible(
            self.start_week,
            not is_link and not is_connector and not is_textbox and not is_arrow,
        )
        self._set_field_visible(self.size_spin, not is_link and not is_textbox)
        self._set_field_visible(self.arrowheads_combo, is_arrow or is_connector)
        self._set_field_visible(self.arrow_direction_combo, is_box)
        self._set_field_visible(self.reverse_direction_button, is_arrow or is_connector)
        self._set_field_visible(self.align_combo, not is_link and not is_connector)
        self._set_field_visible(self.color_button, not is_link)
        self._set_field_visible(self.opacity_spin, not is_link and is_textbox)

    def _set_field_visible(self, widget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self.context_labels.get(widget)
        if label is not None:
            label.setVisible(visible)

    def _apply_text(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        text, html = self.text_input.extract_payload()
        self.controller.update_object(self._current_obj_id, {"text": text, "text_html": html}, "Edit Text")
        self.text_input._original = (text, html)
        self.text_input._loaded_html = self.text_input.toHtml()

    def _apply_start_week(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        start_week = self.start_week.value()
        if not self.duration_weeks.isHidden():
            duration = self._sync_duration_widget(start_week, self.duration_weeks.value())
            end_week = start_week + duration - 1
            with QSignalBlocker(self.end_week):
                self.end_week.setValue(end_week)
            self.controller.update_object(
                self._current_obj_id,
                {"start_week": start_week, "end_week": end_week},
                "Edit Start Week",
            )
            return
        self.controller.update_object(
            self._current_obj_id, {"start_week": start_week}, "Edit Start Week"
        )

    def _apply_duration(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        start_week = self.start_week.value()
        duration = self._sync_duration_widget(start_week, self.duration_weeks.value())
        end_week = start_week + duration - 1
        self.controller.update_object(
            self._current_obj_id, {"end_week": end_week}, "Edit Duration"
        )

    def _apply_row(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        row_id = self.row_combo.currentData()
        if row_id:
            self.controller.update_object(
                self._current_obj_id, {"row_id": row_id}, "Edit Row"
            )

    def _apply_target_week(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        self.controller.update_object(
            self._current_obj_id,
            {"target_week": self.target_week.value(), "end_week": self.target_week.value()},
            "Edit Target Week",
        )

    def _apply_target_row(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        row_id = self.target_row_combo.currentData()
        if row_id:
            self.controller.update_object(
                self._current_obj_id, {"target_row_id": row_id}, "Edit Target Row"
            )

    def _apply_size(self) -> None:
        if self._refreshing or self.size_spin.value() == 0:
            return
        ids = self._selected_ids or ([self._current_obj_id] if self._current_obj_id else [])
        if ids and self.size_spin.isEnabled():
            self.controller.update_objects(ids, {"size": self.size_spin.value()}, "Edit Size")

    def _apply_subject(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        self.controller.assign_subject(self._current_obj_id, self.subject_combo.currentData())

    @staticmethod
    def _object_label(obj) -> str:
        if obj is None:
            return ""
        fallback = "Event" if obj.kind == "circle" else obj.kind.title()
        return (obj.text or fallback).strip() or fallback

    def _populate_predecessors(self, obj) -> None:
        with QSignalBlocker(self.predecessor_combo), QSignalBlocker(self.predecessor_list):
            self.predecessor_combo.clear()
            self.predecessor_list.clear()
            if obj is None:
                return
            predecessors = list(getattr(obj, "predecessors", []) or [])
            for pred_id in predecessors:
                pred = self.controller.model.objects.get(pred_id)
                label = self._object_label(pred) if pred else f"{pred_id} (missing)"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, pred_id)
                self.predecessor_list.addItem(item)
            for candidate in self.controller.model.objects.values():
                if candidate.id == obj.id or candidate.id in predecessors:
                    continue
                if candidate.kind in ("link", "connector"):
                    continue
                self.predecessor_combo.addItem(self._object_label(candidate), candidate.id)

    def _apply_add_predecessor(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        pred_id = self.predecessor_combo.currentData()
        if not pred_id:
            return
        if not self.controller.add_predecessor(self._current_obj_id, pred_id):
            self.feedback.setText("Cannot add that predecessor (cycle or duplicate).")

    def _apply_remove_predecessor(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        item = self.predecessor_list.currentItem()
        if item is None:
            return
        self.controller.remove_predecessor(
            self._current_obj_id, item.data(Qt.ItemDataRole.UserRole)
        )

    def _apply_arrowheads(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        value = self.arrowheads_combo.currentData()
        if value == "both":
            start = True
            end = True
        elif value == "start":
            start = True
            end = False
        else:
            start = False
            end = True
        self.controller.update_object(
            self._current_obj_id,
            {"arrow_head_start": start, "arrow_head_end": end},
            "Edit Arrowheads",
        )

    def _apply_arrow_direction(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        value = self.arrow_direction_combo.currentData()
        if value is None:
            return
        self.controller.update_object(
            self._current_obj_id,
            {"arrow_direction": value},
            "Edit Arrow Direction",
        )

    def _reverse_direction(self) -> None:
        if not self._current_obj_id:
            return
        obj = self.controller.model.objects.get(self._current_obj_id)
        if obj is None or obj.kind not in ("arrow", "connector"):
            return
        changes: dict[str, object] = {}
        free_connector = obj.kind in ("connector", "arrow") and not (
            obj.connector_source_id and obj.connector_target_id
        )
        if free_connector:
            target_week = obj.target_week if obj.target_week is not None else obj.end_week
            new_row_id = obj.target_row_id or obj.row_id
            new_target_row_id = obj.row_id
            if new_row_id == new_target_row_id:
                new_target_row_id = None
            changes["start_week"] = target_week
            changes["end_week"] = obj.start_week
            changes["target_week"] = obj.start_week
            changes["row_id"] = new_row_id
            changes["target_row_id"] = new_target_row_id
        if obj.connector_source_id and obj.connector_target_id:
            changes.update(
                {
                    "connector_source_id": obj.connector_target_id,
                    "connector_target_id": obj.connector_source_id,
                    "connector_source_side": obj.connector_target_side,
                    "connector_target_side": obj.connector_source_side,
                    "connector_source_offset": obj.connector_target_offset,
                    "connector_target_offset": obj.connector_source_offset,
                }
            )
        if changes:
            self.controller.update_object(self._current_obj_id, changes, "Reverse Arrow")

    def _apply_alignment(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        align = self.align_combo.currentData()
        if align:
            self.controller.update_object(
                self._current_obj_id, {"text_align": align}, "Edit Alignment"
            )

    def _pick_color(self) -> None:
        ids = self._selected_ids or ([self._current_obj_id] if self._current_obj_id else [])
        if not ids:
            return
        color = QColorDialog.getColor(QColor(self.color_button.property("color") or "#4E79A7"), self)
        if color.isValid():
            self.controller.update_objects(ids, {"color": color.name().upper()}, "Edit Color")

    def _apply_opacity(self) -> None:
        if self._refreshing or not self._current_obj_id:
            return
        opacity = self.opacity_spin.value() / 100.0
        self.controller.update_object(
            self._current_obj_id, {"opacity": opacity}, "Edit Opacity"
        )

    def _commit_metadata(self, key, field):
        if self._refreshing or not self._current_obj_id:
            return
        obj_id = self._current_obj_id
        text, html = field.extract_payload()
        field._original = (text, html)
        field._loaded_html = field.toHtml()
        self.controller.update_object(obj_id, {key: text, key + '_html': html}, 'Edit ' + key.title())

    def _apply_scope(self) -> None:
        self._commit_metadata('scope', self.scope_edit)

    def _apply_risks(self) -> None:
        self._commit_metadata('risks', self.risks_edit)

    def _apply_notes(self) -> None:
        self._commit_metadata('notes', self.notes_edit)

    def _sync_duration_widget(self, start_week: int, duration: int) -> int:
        max_duration = max(1, WEEK_INDEX_MAX - start_week + 1)
        duration = max(1, min(duration, max_duration))
        with QSignalBlocker(self.duration_weeks):
            self.duration_weeks.setRange(1, max_duration)
            self.duration_weeks.setValue(duration)
        return duration

    def _set_color_button(self, color: str) -> None:
        self.color_button.setProperty("color", color)
        self.color_button.setStyleSheet(f"background-color: {color};")

    @staticmethod
    def _field_has_focus(field: QTextEdit) -> bool:
        return field.hasFocus() or field.viewport().hasFocus()

    def _mark_metadata_refresh(self, field: str) -> None:
        if self._current_obj_id:
            self._suppress_metadata_refresh[field] = self._current_obj_id

    def _should_refresh_metadata(self, field: str, obj_id: str) -> bool:
        if self._suppress_metadata_refresh.get(field) == obj_id:
            self._suppress_metadata_refresh[field] = None
            return False
        return True

    def _clear_metadata_suppression(self) -> None:
        for key in self._suppress_metadata_refresh:
            self._suppress_metadata_refresh[key] = None

    @staticmethod
    def _arrowheads_value(obj) -> str:
        start = bool(getattr(obj, "arrow_head_start", False))
        end = bool(getattr(obj, "arrow_head_end", True))
        if start and end:
            return "both"
        if start:
            return "start"
        return "end"

    @staticmethod
    def _arrow_direction_value(obj) -> str:
        value = str(getattr(obj, "arrow_direction", "none") or "none").lower()
        if value not in ("none", "left", "right"):
            return "none"
        return value

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

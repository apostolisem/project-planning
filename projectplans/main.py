from __future__ import annotations

import csv
import math
import os
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QMarginsF,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QStandardPaths,
    QUrl,
    QSignalBlocker,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QPen,
    QUndoStack,
)
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsTextItem,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .constants import (
    CANVAS_ROW_ID,
    CLASSIFICATION_SIZE_DEFAULT,
    CLASSIFICATION_SIZE_MAX,
    CLASSIFICATION_SIZE_MIN,
    DEFAULT_CLASSIFICATION,
    SCHEMA_VERSION,
)
from .controller import ProjectController
from .inspector import InspectorPanel
from .model import ProjectModel
from .persistence import load_project, save_project
from .planning_issues import compute_issues, issue_summary
from .scene import CanvasScene
from .view import CanvasView
from .planning_toolbar import PlanningToolBar
from .toast import ToastOverlay
from .subject_legend import SubjectLegend
from .table_view import PlanTableDialog
from .widgets import BrandLabel, ClickableStatusLabel, ElidedLabel
from . import icons, theme

RECENT_FILES_LIMIT = 10
UNNAMED_LABEL = "Unnamed"
AUTO_EXPORT_DEFAULT_ADDITIONAL_QUARTERS = 2
AUTO_EXPORT_VIEW_KEY = "auto_export"
AUTO_EXPORT_VIEW_ENABLED_KEY = "enabled"
AUTO_EXPORT_VIEW_PATH_KEY = "path"
AUTO_EXPORT_VIEW_ADDITIONAL_QUARTERS_KEY = "additional_quarters"
EXPORT_CONTENT_PADDING_X = 16.0
EXPORT_CONTENT_PADDING_Y = 16.0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("ProjectPlans", "ProjectPlans")
        self.undo_stack = QUndoStack(self)

        self.model = ProjectModel(year=datetime.now().year)
        self.controller = ProjectController(self.model, self.undo_stack)
        self.scene = CanvasScene(self.model, self.controller)
        self.view = CanvasView(self.scene, self.controller)
        self.setCentralWidget(self.view)
        self._save_failed = False
        self._dark_mode = False
        self._search_matches: list[str] = []

        self.inspector = InspectorPanel(self.controller)
        self.inspector.draft_changed.connect(self._update_title)
        central = QWidget()
        central.setObjectName("workspace")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(10, 10, 10, 10)
        central_layout.setSpacing(0)
        self.takeCentralWidget()
        self.timeline_card = QWidget()
        self.timeline_card.setObjectName("timelineCard")
        timeline_layout = QVBoxLayout(self.timeline_card)
        timeline_layout.setContentsMargins(1, 1, 1, 1)
        timeline_layout.setSpacing(0)
        timeline_layout.addWidget(self.view, 1)
        self.subject_legend = SubjectLegend(self)
        self.subject_legend.filter_changed.connect(self._filter_by_subject)
        self.subject_legend.add_requested.connect(self.add_subject_dialog)
        timeline_layout.addWidget(self.subject_legend)
        central_layout.addWidget(self.timeline_card, 1)
        self.setCentralWidget(central)
        self.inspector.details.setCurrentIndex(int(self.settings.value("view/details_tab", 0)))
        self.inspector.details.currentChanged.connect(lambda index: self.settings.setValue("view/details_tab", index))
        self.toast = ToastOverlay(self)

        self.current_path: Path | None = None
        self._nav_mode_before_presentation = False
        self._canvas_fullscreen = False
        self._fullscreen_previous_state = None
        self._fullscreen_previous_chrome = None
        self._fullscreen_previous_mode = None
        self._fullscreen_previous_margins = None
        self._restore_maximized = False
        self._has_saved_geometry = False
        self._last_window_maximized = False
        self._is_closing = False
        self._window_handle_connected = False
        self._maximize_attempts = 0
        self._restoring_window_state = False
        self._suppress_properties_sync = False
        self._header_layout_needs_normalize = False
        self._view_dirty = False
        self._suppress_view_dirty = False
        self._auto_export_enabled = False
        self._auto_export_path: Path | None = None
        self._auto_export_additional_quarters = AUTO_EXPORT_DEFAULT_ADDITIONAL_QUARTERS
        self._shortcut_actions: dict[str, QAction] = {}
        self._setup_actions()
        self._setup_details_dock()
        self.setStyleSheet(theme.build_stylesheet(self._dark_mode))
        self.header = QWidget()
        self.header.setObjectName("planHeader")
        header_layout = QHBoxLayout(self.header)
        # The tool bar stylesheet owns the header padding; keep the identity
        # group flush with it and vertically centred inside the ribbon.
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(theme.HEADER_SPACING + 2)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.plan_name = BrandLabel(
            "Project Plans", reserve_full_width=True
        )
        self.plan_name.setObjectName("planName")
        self.plan_name.setMinimumWidth(145)
        self.plan_name.setMaximumWidth(205)
        identity_separator = QFrame()
        identity_separator.setObjectName("headerGroupSeparator")
        identity_separator.setFrameShape(QFrame.Shape.VLine)
        identity_separator.setFrameShadow(QFrame.Shadow.Plain)
        self.project_identity = QWidget()
        self.project_identity.setObjectName("projectIdentity")
        identity_layout = QHBoxLayout(self.project_identity)
        identity_layout.setContentsMargins(8, 0, 8, 0)
        identity_layout.setSpacing(theme.HEADER_SPACING)
        self.save_status = ClickableStatusLabel("Unsaved")
        self.save_status.setObjectName("savePill")
        self.save_status.setProperty("state", "unsaved")
        self.save_status.setAccessibleName("Save status")
        self.save_status.clicked.connect(self.save_project)
        self.project_label = ElidedLabel(
            "Untitled", elide_mode=Qt.TextElideMode.ElideMiddle, reserve_full_width=True
        )
        self.project_label.setObjectName("projectFileLabel")
        # Let the identity container size to the current title; the maximum
        # width still bounds long names and preserves ElidedLabel behavior.
        self.project_label.setMinimumWidth(0)
        self.project_label.setMaximumWidth(theme.HEADER_PROJECT_MAX_WIDTH)
        self.project_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        identity_layout.addWidget(self.project_label)
        identity_layout.addWidget(self.save_status)
        header_layout.addWidget(self.plan_name)
        header_layout.addWidget(identity_separator)
        header_layout.addWidget(self.project_identity)
        from PyQt6.QtWidgets import QToolBar
        self.header_bar = QToolBar("Plan", self)
        self.header_bar.setObjectName("plan_header")
        self.header_bar.setMovable(False)
        self.header_bar.setFloatable(False)
        self.header_bar.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        self.header_bar.setIconSize(QSize(theme.HEADER_ICON_SIZE, theme.HEADER_ICON_SIZE))
        self.header_bar.addWidget(self.header)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.header_bar)
        self.planning_toolbar = PlanningToolBar(self)
        self.planning_toolbar.issues_requested.connect(self.show_planning_issues)
        self.planning_toolbar.search_changed.connect(self._search_changed)
        self.planning_toolbar.search_next.connect(self._search_next)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.planning_toolbar)
        self.view.tool_changed.connect(self._tool_changed)
        self.undo_action.triggered.disconnect()
        self.redo_action.triggered.disconnect()
        self.undo_action.triggered.connect(lambda: self._history_action(False))
        self.redo_action.triggered.connect(lambda: self._history_action(True))
        self._connect_model_signals()
        self.undo_stack.cleanChanged.connect(self._update_title)
        self._refresh_rows()
        self.subject_legend.set_model(self.model)
        self._update_title()
        self._load_last_file()
        self._restore_window_settings()
        self._restore_view_settings()

    def _setup_actions(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        export_menu = self.menuBar().addMenu("Export")
        edit_menu = self.menuBar().addMenu("Edit")
        view_menu = self.menuBar().addMenu("View")
        self.overlap_layout_action = QAction("Overlap Layout…", self)
        self.overlap_layout_action.triggered.connect(self.edit_overlap_layout)
        view_menu.addAction(self.overlap_layout_action)
        project_menu = self.menuBar().addMenu("Project")
        insert_menu = self.menuBar().addMenu("Insert")
        help_menu = self.menuBar().addMenu("Help")

        new_action = QAction("New", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_project)
        file_menu.addAction(new_action)

        open_action = QAction("Open", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)

        self.recent_menu = file_menu.addMenu("Open Recent")
        self._refresh_recent_menu()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save As", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_project_as)
        file_menu.addAction(save_as_action)

        planning_export_menu = export_menu.addMenu("Export Planning")
        data_export_menu = export_menu.addMenu("Export Data")
        automatic_export_menu = export_menu.addMenu("Automatic Export")

        export_scope_action = QAction("Scope as Markdown…", self)
        export_scope_action.triggered.connect(self.export_scope)
        export_scope_action.setToolTip("Export plan scope as Markdown")
        data_export_menu.addAction(export_scope_action)

        export_risks_action = QAction("Risks as CSV…", self)
        export_risks_action.triggered.connect(self.export_risks)
        export_risks_action.setToolTip("Export plan risks as CSV")
        data_export_menu.addAction(export_risks_action)

        export_png_action = QAction("Planning as PNG…", self)
        export_png_action.triggered.connect(self.export_png)
        export_png_action.setToolTip("Export selected planning quarters as PNG")
        planning_export_menu.addAction(export_png_action)

        copy_image_clipboard_action = QAction("Copy Image to Clipboard", self)
        copy_image_clipboard_action.triggered.connect(self.copy_image_to_clipboard)
        copy_image_clipboard_action.setToolTip("Copy selected planning quarters as an image")
        planning_export_menu.addAction(copy_image_clipboard_action)

        export_pdf_action = QAction("Planning as PDF…", self)
        export_pdf_action.triggered.connect(self.export_pdf)
        export_pdf_action.setToolTip("Export selected planning quarters as PDF")
        planning_export_menu.addAction(export_pdf_action)

        self.auto_export_action = QAction("Enable Automatic PNG Export", self)
        self.auto_export_action.setCheckable(True)
        self.auto_export_action.toggled.connect(self._toggle_auto_export)
        automatic_export_menu.addAction(self.auto_export_action)

        auto_export_preferences_action = QAction("Automatic Export Settings…", self)
        auto_export_preferences_action.triggered.connect(self.show_auto_export_preferences)
        automatic_export_menu.addAction(auto_export_preferences_action)

        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        shortcuts_action = QAction("Shortcuts", self)
        shortcuts_action.triggered.connect(self.show_shortcuts_dialog)
        help_menu.addAction(shortcuts_action)

        how_to_action = QAction("How to Use", self)
        how_to_action.triggered.connect(self.show_how_to_dialog)
        help_menu.addAction(how_to_action)

        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut("Ctrl+Z")
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut("Ctrl+Y")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        self.history_action = QAction("History...", self)
        self.history_action.triggered.connect(self.show_history_dialog)
        edit_menu.addAction(self.history_action)

        self.find_action = QAction("Find", self)
        self.find_action.setShortcut("Ctrl+F")
        self.find_action.triggered.connect(self._focus_search)
        edit_menu.addAction(self.find_action)

        self.delete_action = QAction("Delete", self)
        self.delete_action.setShortcut("Delete")
        self.delete_action.triggered.connect(self.delete_selected)
        edit_menu.addAction(self.delete_action)

        self.duplicate_action = QAction("Duplicate", self)
        self.duplicate_action.setShortcut("Ctrl+D")
        self.duplicate_action.triggered.connect(self.duplicate_selected)
        edit_menu.addAction(self.duplicate_action)

        navigate_menu = view_menu.addMenu("Navigate")
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(lambda: self.view.zoom_by(1.1))
        navigate_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(lambda: self.view.zoom_by(0.9))
        navigate_menu.addAction(zoom_out_action)

        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(lambda: self.view.set_zoom(1.0))
        navigate_menu.addAction(reset_zoom_action)

        zoom_selection_action = QAction("Zoom to Selection", self)
        self.zoom_selection_action = zoom_selection_action
        zoom_selection_action.setEnabled(False)
        zoom_selection_action.triggered.connect(self.view.zoom_to_selection)
        navigate_menu.addAction(zoom_selection_action)

        fit_action = QAction("Zoom to Fit", self)
        self.fit_action = fit_action
        fit_action.triggered.connect(self.view.zoom_to_fit)
        navigate_menu.addAction(fit_action)

        goto_today_action = QAction("Today", self)
        self.today_action = goto_today_action
        goto_today_action.triggered.connect(self.goto_today)
        navigate_menu.addAction(goto_today_action)

        view_menu.addSeparator()
        interaction_menu = view_menu.addMenu("Interaction")
        self.presentation_mode_action = QAction("Presentation Mode", self)
        self.presentation_mode_action.setCheckable(True)
        self.presentation_mode_action.triggered.connect(self._toggle_presentation_mode)

        self.canvas_fullscreen_action = QAction("Canvas Full Screen", self)
        self.canvas_fullscreen_action.setCheckable(True)
        self.canvas_fullscreen_action.setShortcut("F11")
        self.canvas_fullscreen_action.setToolTip(
            "Show only the planning canvas in full screen (F11)"
        )
        self.canvas_fullscreen_action.triggered.connect(self._toggle_canvas_fullscreen)

        self.nav_mode_action = QAction("Navigation Mode", self)
        self.nav_mode_action.setCheckable(True)
        self.nav_mode_action.triggered.connect(self._toggle_navigation_mode)

        self.edit_mode_action = QAction("Edit Mode", self)
        self.edit_mode_action.setCheckable(True)
        self.edit_mode_action.setChecked(True)
        self.edit_mode_action.triggered.connect(self._toggle_edit_mode)
        interaction_menu.addAction(self.edit_mode_action)
        interaction_menu.addAction(self.nav_mode_action)
        interaction_menu.addAction(self.presentation_mode_action)
        interaction_menu.addAction(self.canvas_fullscreen_action)
        self._interaction_mode_group = QActionGroup(self)
        self._interaction_mode_group.setExclusive(True)
        for mode_action in (
            self.presentation_mode_action,
            self.nav_mode_action,
            self.edit_mode_action,
        ):
            self._interaction_mode_group.addAction(mode_action)

        self.properties_pane_action = QAction("Details", self)
        self.properties_pane_action.setCheckable(True)
        self.properties_pane_action.setChecked(False)
        self.properties_pane_action.setIcon(icons.details_panel_icon())
        self.properties_pane_action.setShortcut("Ctrl+Shift+D")
        self.properties_pane_action.setToolTip("Show or hide Details (Ctrl+Shift+D)")
        self.properties_pane_action.triggered.connect(self._toggle_properties_pane)
        panels_menu = view_menu.addMenu("Panels and Alternate Views")
        panels_menu.addAction(self.properties_pane_action)

        self.plan_table_action = QAction("Plan Table...", self)
        self.plan_table_action.triggered.connect(self.show_plan_table)
        panels_menu.addAction(self.plan_table_action)

        self.period_overview_action = QAction("Period Overview...", self)
        self.period_overview_action.triggered.connect(self.show_period_overview)
        panels_menu.addAction(self.period_overview_action)

        self.snap_grid_action = QAction("Snap Weeks and Rows", self)
        self.snap_grid_action.setCheckable(True)
        self.snap_grid_action.setChecked(True)
        self.snap_grid_action.setToolTip(
            "Snap activity creation, movement, resizing, symbols, and connectors to weeks and rows"
        )
        self.snap_grid_action.triggered.connect(self._toggle_snap_grid)
        interaction_menu.addAction(self.snap_grid_action)

        self.current_week_action = QAction("Highlight Current Week", self)
        self.current_week_action.setCheckable(True)
        self.current_week_action.setChecked(True)
        self.current_week_action.triggered.connect(self._toggle_current_week_line)
        display_menu = view_menu.addMenu("Display")
        display_menu.addAction(self.current_week_action)

        self.position_guidance_action = QAction("Show Position Guidance", self)
        self.position_guidance_action.setCheckable(True)
        self.position_guidance_action.setChecked(True)
        self.position_guidance_action.setToolTip(
            "Show the week and row under the pointer while editing"
        )
        self.position_guidance_action.triggered.connect(self._toggle_position_guidance)
        display_menu.addAction(self.position_guidance_action)

        self.missing_scope_action = QAction("Show Missing Scope", self)
        self.missing_scope_action.setCheckable(True)
        self.missing_scope_action.setChecked(False)
        self.missing_scope_action.triggered.connect(self._toggle_missing_scope)
        display_menu.addAction(self.missing_scope_action)

        self.auto_reschedule_action = QAction("Auto-reschedule Dependencies", self)
        self.auto_reschedule_action.setCheckable(True)
        self.auto_reschedule_action.setChecked(False)
        self.auto_reschedule_action.triggered.connect(self._toggle_auto_reschedule)
        planning_menu = view_menu.addMenu("Planning Behavior")
        planning_menu.addAction(self.auto_reschedule_action)

        self.initiative_rollup_action = QAction("Initiative Rollup", self)
        self.initiative_rollup_action.setCheckable(True)
        self.initiative_rollup_action.setChecked(False)
        self.initiative_rollup_action.triggered.connect(self._toggle_initiative_rollup)
        planning_menu.addAction(self.initiative_rollup_action)

        self.dark_mode_action = QAction("Dark Mode", self)
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setChecked(False)
        self.dark_mode_action.triggered.connect(self._toggle_dark_mode)
        display_menu.addAction(self.dark_mode_action)

        self.text_boxes_action = QAction("Show Text Boxes", self)
        self.text_boxes_action.setCheckable(True)
        self.text_boxes_action.setChecked(True)
        self.text_boxes_action.triggered.connect(self._toggle_text_boxes)
        display_menu.addAction(self.text_boxes_action)

        # Naming follows the WeekFlow add menu: swimlane == existing Topic.
        self.add_topic_action = QAction("Add Section", self)
        self.add_topic_action.setIcon(icons.swimlane_icon())
        self.add_topic_action.triggered.connect(self.add_topic)

        # "Add divider" creates a thin section row (Topic.kind == "divider").
        self.add_divider_action = QAction("Add divider", self)
        self.add_divider_action.setIcon(icons.divider_icon())
        self.add_divider_action.triggered.connect(self.add_divider)
        project_menu.addAction(self.add_divider_action)

        self.add_deliverable_action = QAction("Add Deliverable", self)
        self.add_deliverable_action.triggered.connect(self.add_deliverable)

        self.edit_topic_action = QAction("Edit Section(s)", self)
        self.edit_topic_action.triggered.connect(self.edit_topic)

        self.edit_deliverable_action = QAction("Edit Deliverable(s)", self)
        self.edit_deliverable_action.triggered.connect(self.edit_deliverable)

        self.move_deliverable_up_action = QAction("Move Deliverable Up", self)
        self.move_deliverable_up_action.setShortcut("Alt+Shift+Up")
        self.move_deliverable_up_action.triggered.connect(self.move_deliverable_up)

        self.move_deliverable_down_action = QAction("Move Deliverable Down", self)
        self.move_deliverable_down_action.setShortcut("Alt+Shift+Down")
        self.move_deliverable_down_action.triggered.connect(self.move_deliverable_down)

        self.remove_deliverable_action = QAction("Delete Deliverable(s)", self)
        self.remove_deliverable_action.triggered.connect(self.remove_deliverable)

        self.remove_topic_action = QAction("Remove Section", self)
        self.remove_topic_action.triggered.connect(self.remove_topic)

        project_menu.addAction(self.add_topic_action)
        project_menu.addAction(self.edit_topic_action)
        project_menu.addAction(self.remove_topic_action)
        project_menu.addSeparator()
        project_menu.addAction(self.add_deliverable_action)
        project_menu.addAction(self.edit_deliverable_action)
        project_menu.addAction(self.move_deliverable_up_action)
        project_menu.addAction(self.move_deliverable_down_action)
        project_menu.addAction(self.remove_deliverable_action)
        project_menu.addSeparator()

        self.edit_classification_action = QAction("Edit Classification Tag...", self)
        self.edit_classification_action.triggered.connect(self.edit_classification_tag)
        project_menu.addAction(self.edit_classification_action)

        self.add_subject_action = QAction("Add Subject...", self)
        self.add_subject_action.triggered.connect(self.add_subject_dialog)
        project_menu.addAction(self.add_subject_action)

        self.manage_subjects_action = QAction("Manage Subjects...", self)
        self.manage_subjects_action.triggered.connect(self.manage_subjects_dialog)
        project_menu.addAction(self.manage_subjects_action)

        self.add_initiative_action = QAction("Add initiative", self)
        self.add_initiative_action.setIcon(icons.initiative_icon())
        self.add_initiative_action.triggered.connect(self.add_initiative_dialog)
        project_menu.addAction(self.add_initiative_action)

        self.link_initiative_action = QAction("Link Selection to Initiative...", self)
        self.link_initiative_action.triggered.connect(self.link_selection_to_initiative)
        project_menu.addAction(self.link_initiative_action)

        # Task/milestone reuse the existing box/milestone object kinds; only the
        # user-facing names follow the HTML add menu.
        self.add_box_action = QAction("Add task", self)
        self.add_box_action.setIcon(icons.task_icon())
        self.add_box_action.setShortcut("B")
        self.add_box_action.triggered.connect(lambda: self.create_object("box"))
        insert_menu.addAction(self.add_box_action)

        self.add_milestone_action = QAction("Add milestone", self)
        self.add_milestone_action.setIcon(icons.milestone_icon())
        self.add_milestone_action.setShortcut("M")
        self.add_milestone_action.triggered.connect(lambda: self.create_object("milestone"))
        insert_menu.addAction(self.add_milestone_action)

        self.add_deadline_action = QAction("Deadline", self)
        self.add_deadline_action.setShortcut("D")
        self.add_deadline_action.triggered.connect(lambda: self.create_object("deadline"))
        insert_menu.addAction(self.add_deadline_action)

        self.add_circle_action = QAction("Event", self)
        self.add_circle_action.setShortcut("C")
        self.add_circle_action.triggered.connect(lambda: self.create_object("circle"))
        insert_menu.addAction(self.add_circle_action)

        # "Arrow" and "Connector Arrow" merged into one connector tool;
        # both legacy shortcut keys stay bound to it.
        self.add_connector_action = QAction("Connector", self)
        self.add_connector_action.setShortcuts(["A", "F"])
        self.add_connector_action.triggered.connect(lambda: self.create_object("connector"))
        insert_menu.addAction(self.add_connector_action)

        self.add_textbox_action = QAction("Text Box", self)
        self.add_textbox_action.setShortcut("X")
        self.add_textbox_action.triggered.connect(lambda: self.create_object("textbox"))
        insert_menu.addAction(self.add_textbox_action)

        self._edit_actions = [
            self.overlap_layout_action,
            self.undo_action,
            self.redo_action,
            self.delete_action,
            self.duplicate_action,
            self.edit_classification_action,
            self.add_topic_action,
            self.add_divider_action,
            self.add_deliverable_action,
            self.add_initiative_action,
            self.edit_topic_action,
            self.edit_deliverable_action,
            self.move_deliverable_up_action,
            self.move_deliverable_down_action,
            self.remove_deliverable_action,
            self.remove_topic_action,
            self.add_box_action,
            self.add_milestone_action,
            self.add_deadline_action,
            self.add_circle_action,
            self.add_connector_action,
            self.add_textbox_action,
            self.edit_mode_action,
        ]
        self._shortcut_actions = {
            "new": new_action,
            "open": open_action,
            "save": save_action,
            "save_as": save_as_action,
            "quit": quit_action,
            "undo": self.undo_action,
            "redo": self.redo_action,
            "delete": self.delete_action,
            "duplicate": self.duplicate_action,
            "zoom_in": zoom_in_action,
            "zoom_out": zoom_out_action,
            "reset_zoom": reset_zoom_action,
            "move_deliverable_up": self.move_deliverable_up_action,
            "move_deliverable_down": self.move_deliverable_down_action,
            "insert_box": self.add_box_action,
            "insert_milestone": self.add_milestone_action,
            "insert_deadline": self.add_deadline_action,
            "insert_circle": self.add_circle_action,
            "insert_connector": self.add_connector_action,
            "insert_textbox": self.add_textbox_action,
        }

        self._sync_textbox_insert_action()

    def _shortcut_sections(self) -> list[tuple[str, list[tuple[QAction | str, str]]]]:
        actions = self._shortcut_actions
        return [
            (
                "File",
                [
                    (actions["new"], "Create a new project."),
                    (actions["open"], "Open an existing project file."),
                    (actions["save"], "Save the current project."),
                    (actions["save_as"], "Save the current project to a new file."),
                    (actions["quit"], "Close the application."),
                ],
            ),
            (
                "Edit",
                [
                    (actions["undo"], "Undo the last change."),
                    (actions["redo"], "Redo the last undone change."),
                    (actions["delete"], "Delete the selected object."),
                    (actions["duplicate"], "Duplicate the selected object."),
                ],
            ),
            (
                "View",
                [
                    (actions["zoom_in"], "Zoom in on the canvas."),
                    (actions["zoom_out"], "Zoom out on the canvas."),
                    (actions["reset_zoom"], "Reset zoom to 100%."),
                ],
            ),
            (
                "Project",
                [
                    (
                        actions["move_deliverable_up"],
                        "Move the selected deliverable up within its section.",
                    ),
                    (
                        actions["move_deliverable_down"],
                        "Move the selected deliverable down within its section.",
                    ),
                ],
            ),
            (
                "Insert",
                [
                    (actions["insert_box"], "Start placing an activity box."),
                    (actions["insert_milestone"], "Start placing a milestone."),
                    (actions["insert_deadline"], "Start placing a deadline."),
                    (actions["insert_circle"], "Start placing an event."),
                    (actions["insert_connector"], "Start placing a connector (edge-to-edge, or drag empty space for a free connector)."),
                    (actions["insert_textbox"], "Start placing a text box."),
                ],
            ),
            (
                "Text Editing",
                [
                    ("Ctrl+B", "Toggle bold in inline text and metadata fields."),
                    ("Ctrl+I", "Toggle italic in inline text and metadata fields."),
                    ("Ctrl+U", "Toggle underline in inline text and metadata fields."),
                    ("Alt+Shift+S", "Toggle strikethrough in inline text and metadata fields."),
                    ("Ctrl+]", "Increase selected text size."),
                    ("Ctrl+[", "Decrease selected text size."),
                    ("F2", "Start inline editing for the selected object's text."),
                    (
                        "Enter",
                        "Commit single-line inline edits, or insert a newline in multiline inline editors.",
                    ),
                    ("Ctrl+Enter", "Commit multiline inline text edits."),
                    ("Esc", "Cancel inline text editing without saving changes."),
                ],
            ),
            (
                "Quick Controls",
                [
                    ("Ctrl+Mouse Wheel", "Zoom the canvas in or out."),
                    ("Arrow Keys", "Nudge the selected object by week or row."),
                    (
                        "Shift+Arrow Keys",
                        "Resize a single selected box item or adjust a free connector target.",
                    ),
                    ("Space", "Pan while held in edit mode."),
                    (
                        "Double-click",
                        "Edit an item's text, or collapse and expand section labels.",
                    ),
                    ("Right-click drag", "Pan the canvas."),
                    ("Esc", "Cancel active object placement or connector dragging."),
                ],
            ),
        ]

    @staticmethod
    def _shortcut_text(source: QAction | str) -> str:
        if isinstance(source, QAction):
            shortcut = source.shortcut()
            if shortcut.isEmpty():
                return ""
            return shortcut.toString()
        return source

    def show_shortcuts_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Shortcuts")
        dialog.resize(760, 560)

        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Available keyboard shortcuts and quick controls for working in Project Plans."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tree = QTreeWidget(dialog)
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Shortcut", "What it does"])
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        for section_name, entries in self._shortcut_sections():
            section_item = QTreeWidgetItem(tree, [section_name, ""])
            section_item.setFirstColumnSpanned(True)
            section_item.setExpanded(True)
            section_item.setFlags(section_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            section_font = section_item.font(0)
            section_font.setBold(True)
            section_item.setFont(0, section_font)
            for source, description in entries:
                entry_item = QTreeWidgetItem(
                    section_item, [self._shortcut_text(source), description]
                )
                entry_item.setFlags(entry_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tree.expandAll()
        tree.resizeColumnToContents(0)
        tree.header().setStretchLastSection(True)
        layout.addWidget(tree)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def _recent_file_entries(self) -> list[str]:
        value = self.settings.value("recent_files", [])
        if isinstance(value, str):
            entries = [value]
        elif isinstance(value, list):
            entries = [str(item) for item in value]
        else:
            entries = []
        cleaned: list[str] = []
        seen = set()
        for entry in entries:
            entry = entry.strip()
            if not entry or entry in seen:
                continue
            seen.add(entry)
            cleaned.append(entry)
        return cleaned

    def _write_recent_files(self, entries: list[str]) -> None:
        self.settings.setValue("recent_files", entries)
        self.settings.sync()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        entries = self._recent_file_entries()
        existing_entries = [entry for entry in entries if Path(entry).exists()]
        if existing_entries != entries:
            self._write_recent_files(existing_entries)
        if not existing_entries:
            empty_action = QAction("No Recent Files", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for entry in existing_entries:
            path = Path(entry)
            label = f"{path.name} ({path.parent})"
            action = QAction(label, self)
            action.setData(entry)
            action.triggered.connect(self._open_recent_action)
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _add_recent_file(self, path: Path) -> None:
        path = Path(path).expanduser()
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path.absolute()
        path_str = str(resolved)
        entries = [entry for entry in self._recent_file_entries() if entry != path_str]
        entries.insert(0, path_str)
        entries = entries[:RECENT_FILES_LIMIT]
        self._write_recent_files(entries)
        self._refresh_recent_menu()

    def _remove_recent_file(self, path: Path) -> None:
        path_str = str(path)
        entries = [entry for entry in self._recent_file_entries() if entry != path_str]
        self._write_recent_files(entries)
        self._refresh_recent_menu()

    def _clear_recent_files(self) -> None:
        self._write_recent_files([])
        self._refresh_recent_menu()

    def _open_recent_action(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        entry = action.data()
        if not entry:
            return
        path = Path(str(entry))
        if not path.exists():
            QMessageBox.warning(self, "Open Recent", "Recent file no longer exists.")
            self._remove_recent_file(path)
            return
        if not self.maybe_save():
            return
        try:
            self._load_from_path(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open Failed", f"Could not open project file.\n{exc}")

    def _disconnect_model_signals(self) -> None:
        try:
            self.scene.selectionChanged.disconnect(self._update_inspector_selection)
        except TypeError:
            pass
        try:
            self.scene.selectionChanged.disconnect(self._update_zoom_selection_enabled)
        except TypeError:
            pass
        try:
            self.scene.label_width_changed.disconnect(self._on_label_width_changed)
        except TypeError:
            pass
        try:
            self.model.rows_changed.disconnect(self._refresh_rows)
        except TypeError:
            pass
        try:
            self.model.objects_changed.disconnect(self._update_inspector_selection)
        except TypeError:
            pass
        try:
            self.scene.status_message.disconnect(self._on_scene_status)
        except TypeError:
            pass
        try:
            self.model.metadata_changed.disconnect(self._refresh_subjects)
        except TypeError:
            pass
        try:
            self.model.objects_changed.disconnect(self._update_issue_badge)
        except TypeError:
            pass

    def _connect_model_signals(self) -> None:
        self.scene.selectionChanged.connect(self._update_inspector_selection)
        self.scene.selectionChanged.connect(self._update_zoom_selection_enabled)
        self.scene.label_width_changed.connect(self._on_label_width_changed)
        self.scene.status_message.connect(self._on_scene_status)
        self.model.rows_changed.connect(self._refresh_rows)
        self.model.objects_changed.connect(self._update_inspector_selection)
        self.model.metadata_changed.connect(self._refresh_subjects)
        self.model.objects_changed.connect(self._update_issue_badge)

    def _update_zoom_selection_enabled(self) -> None:
        if hasattr(self, "zoom_selection_action"):
            self.zoom_selection_action.setEnabled(
                bool(self.scene.selectedItems()) or bool(self.scene.selected_row_ids)
            )

    def _on_scene_status(self, message: str) -> None:
        if message:
            self.statusBar().showMessage(message)
        else:
            self.statusBar().clearMessage()

    def _refresh_rows(self) -> None:
        self.inspector.refresh_rows(self.scene.layout, self.model)
        self._update_issue_badge()

    def _refresh_subjects(self) -> None:
        if not hasattr(self, "subject_legend"):
            return
        self.subject_legend.set_model(self.model)
        self.inspector.refresh_rows(self.scene.layout, self.model)
        self._update_issue_badge()

    def _update_issue_badge(self, *_args) -> None:
        if not hasattr(self, "planning_toolbar"):
            return
        try:
            issues = compute_issues(self.model, set(self.model.ignored_issues))
        except Exception:
            issues = []
        active, total = issue_summary(issues)
        self.planning_toolbar.set_issue_count(active, total)

    def show_planning_issues(self) -> None:
        issues = compute_issues(self.model, set(self.model.ignored_issues))
        active, total = issue_summary(issues)
        dialog = QDialog(self)
        dialog.setWindowTitle("Planning issues")
        layout = QVBoxLayout(dialog)
        header = QLabel(
            f"{active} active issue(s) · {total} total" if total
            else "No planning issues found."
        )
        layout.addWidget(header)
        listing = QTreeWidget()
        listing.setHeaderLabels(["Type", "Issue", "Detail"])
        listing.setRootIsDecorated(False)
        for issue in issues:
            item = QTreeWidgetItem([issue["type"], issue["title"], issue.get("detail", "")])
            item.setData(0, Qt.ItemDataRole.UserRole, issue)
            if issue.get("ignored"):
                item.setForeground(0, QColor("#94a3b8"))
            listing.addTopLevelItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox()
        toggle_button = buttons.addButton("Ignore / Restore", QDialogButtonBox.ButtonRole.ActionRole)
        open_button = buttons.addButton("Go to item", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        def toggle_ignored():
            item = listing.currentItem()
            if item is None:
                return
            issue = item.data(0, Qt.ItemDataRole.UserRole)
            ignored = set(self.model.ignored_issues)
            if issue["key"] in ignored:
                ignored.discard(issue["key"])
            else:
                ignored.add(issue["key"])
            self.model.ignored_issues = sorted(ignored)
            self.model.metadata_changed.emit()
            self._update_issue_badge()
            dialog.accept()
            self.show_planning_issues()

        def go_to_item():
            item = listing.currentItem()
            if item is None:
                return
            issue = item.data(0, Qt.ItemDataRole.UserRole)
            obj_id = issue.get("object_id")
            target = self.scene.items_by_id.get(obj_id) if obj_id else None
            if target is not None:
                self.scene.clearSelection()
                target.setSelected(True)
                self.view.centerOn(target)
            dialog.accept()

        toggle_button.clicked.connect(toggle_ignored)
        open_button.clicked.connect(go_to_item)
        buttons.rejected.connect(dialog.reject)
        dialog.resize(760, 420)
        dialog.exec()

    def _reveal_object(self, obj_id: str) -> None:
        item = self.scene.items_by_id.get(obj_id)
        if item is None:
            return
        self.scene.clearSelection()
        item.setSelected(True)
        self.view.centerOn(item)

    def show_plan_table(self) -> None:
        dialog = PlanTableDialog(self.model, self.scene.layout, self)
        dialog.object_activated.connect(self._reveal_object)
        dialog.exec()

    def show_period_overview(self) -> None:
        entries = self._quarter_entries(0)
        if not entries:
            QMessageBox.information(self, "Period Overview", "No periods available.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Period Overview")
        outer = QVBoxLayout(dialog)
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Period"))
        picker = QComboBox()
        for entry in entries:
            picker.addItem(entry["label"], entry)
        picker_row.addWidget(picker)
        outer.addLayout(picker_row)
        summary = QLabel()
        outer.addWidget(summary)
        listing = QTreeWidget()
        listing.setHeaderLabels(["Type", "Title", "Start", "End", "Weeks"])
        listing.setRootIsDecorated(False)
        outer.addWidget(listing, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        outer.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)

        def refresh(*_):
            entry = picker.currentData()
            if not entry:
                return
            listing.clear()
            start, end = entry["start_week"], entry["end_week"]
            overlapping = [
                obj for obj in self.model.objects.values()
                if obj.kind not in ("link", "connector")
                and obj.start_week <= end and obj.end_week >= start
            ]
            milestones = sum(1 for o in overlapping if o.kind == "milestone")
            summary.setText(
                f"{len(overlapping)} item(s) · {milestones} milestone(s) · "
                f"weeks {start}–{end}"
            )
            for obj in sorted(overlapping, key=lambda o: (o.start_week, o.row_id)):
                item = QTreeWidgetItem([
                    self._scope_object_type(obj), obj.text or "",
                    str(obj.start_week), str(obj.end_week),
                    str(max(1, obj.end_week - obj.start_week + 1)),
                ])
                item.setData(0, Qt.ItemDataRole.UserRole, obj.id)
                listing.addTopLevelItem(item)

        def activate(item, _column):
            obj_id = item.data(0, Qt.ItemDataRole.UserRole)
            if obj_id:
                self._reveal_object(obj_id)

        picker.currentIndexChanged.connect(refresh)
        listing.itemDoubleClicked.connect(activate)
        refresh()
        dialog.resize(640, 460)
        dialog.exec()

    def _filter_by_subject(self, subject_id: object) -> None:
        if not subject_id:
            self.scene.clear_visual_relations()
            return
        related = {obj.id for obj in self.model.objects.values() if obj.subject_id == subject_id}
        dimmed = {obj.id for obj in self.model.objects.values() if obj.subject_id != subject_id}
        self.scene.set_visual_relations(related, dimmed)

    def _search_changed(self, text: str) -> None:
        query = (text or "").strip().lower()
        if not query:
            self._search_matches = []
            self.scene.clear_visual_relations()
            return
        matches = []
        for obj in self.model.objects.values():
            haystack = " ".join(
                part for part in (obj.text, obj.notes, obj.scope, obj.risks) if part
            ).lower()
            if query in haystack:
                matches.append(obj.id)
        self._search_matches = matches
        if not matches:
            self.scene.clear_visual_relations()
            return
        related = set(matches)
        dimmed = set(self.model.objects) - related
        self.scene.set_visual_relations(related, dimmed)
        if len(matches) == 1:
            self._reveal_object(matches[0])

    def _search_next(self) -> None:
        if not self._search_matches:
            return
        order = self._search_matches
        current = [o for o in self.view.selected_object_ids() if o in order]
        index = order.index(current[0]) if current else -1
        self.scene.clearSelection()
        self._reveal_object(order[(index + 1) % len(order)])

    def _focus_search(self) -> None:
        if not hasattr(self, "planning_toolbar"):
            return
        self.planning_toolbar.search_edit.setFocus()
        self.planning_toolbar.search_edit.selectAll()

    @staticmethod
    def _help_shortcut(action: QAction) -> str:
        shortcuts = [shortcut.toString() for shortcut in action.shortcuts() if not shortcut.isEmpty()]
        return " / ".join(shortcuts)

    @staticmethod
    def _help_page(title: str, introduction: str, sections) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("howToPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 24, 20)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("howToPageTitle")
        heading_font = QFont(heading.font())
        heading_font.setPointSize(16)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)

        intro = QLabel(introduction)
        intro.setObjectName("howToPageIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for section_title, body in sections:
            section_heading = QLabel(section_title)
            section_heading.setObjectName("howToSectionTitle")
            section_font = QFont(section_heading.font())
            section_font.setPointSize(11)
            section_font.setBold(True)
            section_heading.setFont(section_font)
            layout.addSpacing(8)
            layout.addWidget(section_heading)

            content = QLabel(body)
            content.setObjectName("howToSectionBody")
            content.setTextFormat(Qt.TextFormat.RichText)
            content.setWordWrap(True)
            content.setOpenExternalLinks(False)
            content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(content)

        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _create_how_to_dialog(self) -> QDialog:
        actions = self._shortcut_actions
        key = lambda name: self._help_shortcut(actions[name])
        pages = [
            (
                "Getting Started",
                "Start with the plan structure, then choose the interaction mode that fits your task.",
                [
                    (
                        "Build the structure",
                        "<ol><li>Choose <b>Add &gt; Add Section</b> for a planning section.</li>"
                        "<li>Add deliverables inside the section to create planning rows.</li>"
                        "<li>Place work and planning markers on those rows in the timeline.</li></ol>",
                    ),
                    (
                        "Choose a mode",
                        "<b>Edit</b> creates and changes plan content. <b>Navigation</b> is for "
                        "reviewing and panning without accidental edits. <b>Presentation</b> hides "
                        "editing affordances for a clean read-only view. <b>Canvas Full Screen</b> "
                        "hides application chrome for a read-only canvas; press <b>Esc</b> or <b>F11</b> "
                        "to exit.",
                    ),
                    (
                        "Move around",
                        "Use the date controls to page through time, <b>Today</b> to return to the "
                        "current week, and <b>Fit</b> to frame the plan. Hold <b>Space</b> or drag "
                        "with the right mouse button to pan in Edit mode. In Edit mode, <b>View &gt; "
                        "Display &gt; Show Position Guidance</b> shows the week and row beside the pointer.",
                    ),
                ],
            ),
            (
                "Build & Edit",
                "Create objects from Add or with a shortcut, then drag on the canvas to place them.",
                [
                    (
                        "Insert objects",
                        f"<b>{key('insert_box')}</b> task &nbsp; <b>{key('insert_milestone')}</b> milestone &nbsp; "
                        f"<b>{key('insert_deadline')}</b> deadline &nbsp; <b>{key('insert_circle')}</b> event<br>"
                        f"<b>{key('insert_connector')}</b> connector &nbsp; <b>{key('insert_textbox')}</b> text box. "
                        "Press <b>Esc</b> to cancel placement. Dragging an empty planning row also creates a task.",
                    ),
                    (
                        "Select and arrange",
                        "Click an object to select it. Use <b>Ctrl/Cmd-click</b> to toggle objects in a "
                        "multi-selection, or <b>Ctrl/Cmd-drag</b> empty canvas for a marquee. Drag selected "
                        "objects to move them; drag the visible edge grips to resize tasks. Use "
                        f"<b>{key('duplicate')}</b> to duplicate and <b>{key('delete')}</b> to delete. "
                        "Duplicates do not inherit dependencies, connectors, or text-box links.",
                    ),
                    (
                        "Edit details",
                        "Double-click text or press <b>F2</b> to edit it inline. Open <b>Details</b> "
                        "(<b>Ctrl+Shift+D</b>) for dates, style, notes, scope, risks, subjects, and dependencies. "
                        f"Use <b>{key('undo')}</b> and <b>{key('redo')}</b> to revisit changes.",
                    ),
                    (
                        "Control placement",
                        "Keep <b>View &gt; Interaction &gt; Snap Weeks and Rows</b> enabled for aligned "
                        "creation, movement, resizing, and connectors; disable it for free positioning.",
                    ),
                ],
            ),
            (
                "Dependencies",
                "Dependencies are finish-to-start links between planning objects.",
                [
                    (
                        "Create a link",
                        "<ol><li>Hover an object to reveal its left and right <b>+</b> ports.</li>"
                        "<li>Drag the left port to choose a predecessor, or the right port to choose a successor.</li>"
                        "<li>Drop on a cyan receptor to create the link. Red feedback means the link is rejected, "
                        "for example because it is a duplicate or would create a cycle.</li></ol>"
                        "Text boxes have four link handles and may connect to multiple objects.",
                    ),
                    (
                        "Review and remove links",
                        "Click a dependency path to select it; use <b>Ctrl/Cmd-click</b> or a marquee for "
                        "multiple paths. Press <b>Delete</b> or use <b>Delete Selection</b> from the context "
                        "menu to remove selected links. You can also manage predecessors in "
                        "<b>Details &gt; Dependencies</b>.",
                    ),
                    (
                        "Scheduling behavior",
                        "Enable <b>View &gt; Planning Behavior &gt; Auto-reschedule Dependencies</b> to push "
                        "successors later when a predecessor moves. Planning issues flag conflicts, missing "
                        "references, and cycles.",
                    ),
                ],
            ),
            (
                "Organize",
                "Use plan metadata and row tools to keep large plans understandable.",
                [
                    (
                        "Subjects and legend",
                        "Create subjects from <b>Project</b>, then assign them in <b>Details</b> to colour-code "
                        "work. Use the legend below the canvas to filter the visible subjects.",
                    ),
                    (
                        "Initiatives",
                        "Create an initiative, select the related objects, and choose "
                        "<b>Project &gt; Link Selection to Initiative</b>. Toggle <b>Initiative Rollup</b> "
                        "to review grouped work at a higher level.",
                    ),
                    (
                        "Rows and plan quality",
                        "Right-click sections and deliverables to rename, reorder, move, indent, focus, or "
                        "collapse them. Add dividers between major areas. Enable <b>Show Missing Scope</b> "
                        "to identify tasks that still need scope information.",
                    ),
                ],
            ),
            (
                "Review & Export",
                "Inspect plan quality from several views, then share either the timeline or its supporting data.",
                [
                    (
                        "Review",
                        f"Use the <b>!</b> button for planning issues and <b>{self.find_action.shortcut().toString()}</b> "
                        "to search. <b>Edit &gt; History</b> jumps to an earlier change. <b>Plan Table</b> "
                        "provides a structured object list, while <b>Period Overview</b> summarizes the plan by period.",
                    ),
                    (
                        "Frame the plan",
                        f"Zoom with <b>{key('zoom_in')}</b> and <b>{key('zoom_out')}</b>, reset with "
                        f"<b>{key('reset_zoom')}</b>, or use <b>Zoom to Selection</b> and <b>Fit</b>. "
                        "Use Presentation mode when reviewing with others.",
                    ),
                    (
                        "Export and share",
                        "Export selected planning periods as <b>PNG</b> or <b>PDF</b>, or copy the image to "
                        "the clipboard. Export scope as <b>Markdown</b> and risks as <b>CSV</b>. Automatic "
                        "PNG export can keep an image current whenever the project is saved.",
                    ),
                ],
            ),
        ]

        dialog = QDialog(self)
        dialog.setObjectName("howToDialog")
        dialog.setWindowTitle("How to Use Project Plans")
        dialog.resize(820, 600)
        dialog.setMinimumSize(680, 480)

        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)
        title = QLabel("How to Use Project Plans")
        title.setObjectName("howToTitle")
        title_font = QFont(title.font())
        title_font.setPointSize(17)
        title_font.setBold(True)
        title.setFont(title_font)
        outer.addWidget(title)
        subtitle = QLabel("Practical guidance for building, organizing, reviewing, and sharing a plan.")
        subtitle.setObjectName("howToSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(0)
        navigation = QListWidget(dialog)
        navigation.setObjectName("howToNavigation")
        navigation.setFixedWidth(176)
        navigation.setSpacing(2)
        navigation.setAccessibleName("How to topics")
        stack = QStackedWidget(dialog)
        stack.setObjectName("howToPages")
        for page_title, introduction, sections in pages:
            navigation.addItem(page_title)
            stack.addWidget(self._help_page(page_title, introduction, sections))
        navigation.currentRowChanged.connect(stack.setCurrentIndex)
        navigation.currentRowChanged.connect(
            lambda row: setattr(self, "_how_to_last_page", max(0, row))
        )
        navigation.setCurrentRow(
            min(getattr(self, "_how_to_last_page", 0), navigation.count() - 1)
        )
        body.addWidget(navigation)
        body.addWidget(stack, 1)
        outer.addLayout(body, 1)

        buttons = QDialogButtonBox(dialog)
        shortcuts_button = buttons.addButton(
            "Keyboard Shortcuts", QDialogButtonBox.ButtonRole.ActionRole
        )
        close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close_button.setDefault(True)
        buttons.rejected.connect(dialog.reject)

        def show_shortcuts() -> None:
            dialog.accept()
            QTimer.singleShot(0, self.show_shortcuts_dialog)

        shortcuts_button.clicked.connect(show_shortcuts)
        outer.addWidget(buttons)
        return dialog

    def show_how_to_dialog(self) -> None:
        self._create_how_to_dialog().exec()

    def add_subject_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Subject", "Subject name:")
        if not ok or not name.strip():
            return
        self.controller.add_subject(name.strip())
        self.notify(f"Subject '{name.strip()}' added", "success")
        self._refresh_subjects()

    def manage_subjects_dialog(self) -> None:
        if not self.model.subjects:
            QMessageBox.information(self, "Manage Subjects", "No subjects yet. Add one first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage Subjects")
        layout = QVBoxLayout(dialog)
        listbox = QTreeWidget()
        listbox.setHeaderLabels(["Subject", "Color"])
        listbox.setRootIsDecorated(False)
        for subject in self.model.subjects:
            item = QTreeWidgetItem([subject.name, subject.color])
            item.setData(0, Qt.ItemDataRole.UserRole, subject.id)
            listbox.addTopLevelItem(item)
        layout.addWidget(listbox)
        buttons = QDialogButtonBox()
        rename_button = buttons.addButton("Rename", QDialogButtonBox.ButtonRole.ActionRole)
        recolor_button = buttons.addButton("Color...", QDialogButtonBox.ButtonRole.ActionRole)
        delete_button = buttons.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        def rename():
            item = listbox.currentItem()
            if item is None:
                return
            new_name, ok = QInputDialog.getText(self, "Rename Subject", "Name:", text=item.text(0))
            if ok and new_name.strip():
                self.controller.update_subject(item.data(0, Qt.ItemDataRole.UserRole), name=new_name.strip())
                self._refresh_subjects()
                self.manage_dialog_refresh(listbox)

        def recolor():
            item = listbox.currentItem()
            if item is None:
                return
            color = QColorDialog.getColor(QColor(item.text(1)), self, "Subject Color")
            if color.isValid():
                self.controller.update_subject(item.data(0, Qt.ItemDataRole.UserRole), color=color.name())
                self._refresh_subjects()
                self.manage_dialog_refresh(listbox)

        def delete():
            item = listbox.currentItem()
            if item is None:
                return
            subject_id = item.data(0, Qt.ItemDataRole.UserRole)
            self.controller.remove_subject(subject_id)
            self._refresh_subjects()
            self.subject_legend.clear_filter()
            dialog.accept()

        rename_button.clicked.connect(rename)
        recolor_button.clicked.connect(recolor)
        delete_button.clicked.connect(delete)
        buttons.rejected.connect(dialog.reject)
        dialog.resize(360, 260)
        dialog.exec()

    def manage_dialog_refresh(self, listbox) -> None:
        listbox.clear()
        for subject in self.model.subjects:
            item = QTreeWidgetItem([subject.name, subject.color])
            item.setData(0, Qt.ItemDataRole.UserRole, subject.id)
            listbox.addTopLevelItem(item)

    def _toggle_initiative_rollup(self) -> None:
        self.scene.set_initiative_rollup(self.initiative_rollup_action.isChecked())

    def show_history_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("History")
        layout = QVBoxLayout(dialog)
        header = QLabel("Jump to a point in the edit history (click a step).")
        layout.addWidget(header)
        listing = QListWidget()
        for index in range(self.undo_stack.count() + 1):
            label = "Start" if index == 0 else self.undo_stack.text(index - 1)
            item = QListWidgetItem(f"{index}. {label}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            if index == self.undo_stack.index():
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setText(item.text() + "   ← current")
            listing.addItem(item)
        listing.setCurrentRow(self.undo_stack.index())
        layout.addWidget(listing, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)

        def jump(item):
            self.undo_stack.setIndex(int(item.data(Qt.ItemDataRole.UserRole)))
            dialog.accept()

        listing.itemClicked.connect(jump)
        dialog.resize(520, 420)
        dialog.exec()

    def add_initiative_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Initiative", "Initiative name:")
        if not ok or not name.strip():
            return
        self.controller.add_initiative(name.strip())
        self.notify(f"Initiative '{name.strip()}' added", "success")

    def link_selection_to_initiative(self) -> None:
        ids = self.view.selected_object_ids()
        if not ids:
            QMessageBox.information(self, "Link to Initiative", "Select one or more objects first.")
            return
        if not self.model.initiatives:
            self.add_initiative_dialog()
            if not self.model.initiatives:
                return
        names = [i.name for i in self.model.initiatives]
        name, ok = QInputDialog.getItem(self, "Link to Initiative", "Initiative:", names, 0, False)
        if not ok:
            return
        initiative = next((i for i in self.model.initiatives if i.name == name), None)
        if initiative is not None:
            self.controller.link_to_initiative(initiative.id, ids)
            self.notify(f"Linked {len(ids)} item(s) to '{initiative.name}'", "success")

    def _update_inspector_selection(self) -> None:
        if getattr(self, "_selection_refreshing", False) or not hasattr(self.view.scene(), 'model'):
            return
        self._selection_refreshing = True
        try:
            ids = self.view.selected_object_ids()
            self.inspector.set_selected_objects(ids)
            if len(ids) == 1:
                self.view.set_selected_row(self.model.objects[ids[0]].row_id)
        finally:
            self._selection_refreshing = False

    def _set_view_dirty(self, dirty: bool) -> None:
        if self._view_dirty == dirty:
            return
        self._view_dirty = dirty
        self._update_title()

    def _on_label_width_changed(self, _width: float) -> None:
        if self._suppress_view_dirty:
            return
        self._set_view_dirty(True)

    def _update_title(self) -> None:
        if self.current_path:
            name = self.current_path.name
            project_name = self.current_path.stem
        else:
            name = "Untitled"
            project_name = "Untitled"
        if not self.undo_stack.isClean() or self._view_dirty:
            name = f"*{name}"
        self.setWindowTitle(f"Project Plans - {name}")
        if hasattr(self, "plan_name"):
            self.plan_name.setText("Project Plans")
            if hasattr(self, "planning_toolbar"):
                self.planning_toolbar.set_project_name(project_name)
            dirty = not self.undo_stack.isClean() or self._view_dirty or not self.current_path or self.inspector.has_pending()
            if self._save_failed:
                state, label = "error", "Save failed"
            elif dirty:
                state, label = "unsaved", "Unsaved"
            else:
                state, label = "saved", "Saved"
            self.save_status.setText(label)
            self.save_status.setProperty("state", state)
            self.save_status.setClickable(state == "unsaved")
            self.save_status.style().unpolish(self.save_status)
            self.save_status.style().polish(self.save_status)

    def notify(self, message: str, severity: str = "info", *, status: bool = False) -> None:
        """Show a non-blocking toast (and optionally the status bar)."""
        if message:
            self.toast.show_toast(message, severity)
        if status:
            self.statusBar().showMessage(message, 3000)

    def _load_last_file(self) -> None:
        path = self.settings.value("last_file", "")
        if path:
            path = Path(path)
            if path.exists():
                try:
                    self._load_from_path(path)
                    return
                except Exception:
                    QMessageBox.warning(self, "Load Failed", "Could not load the last project file.")
        self._update_title()

    def _set_model(self, model: ProjectModel, view_state: dict | None = None) -> None:
        self._disconnect_model_signals()
        self.model = model
        self.controller = ProjectController(self.model, self.undo_stack)
        self.scene = CanvasScene(self.model, self.controller)
        self.view.setScene(self.scene)
        self.view.controller = self.controller
        self.inspector._current_obj_id = None
        self.inspector.controller = self.controller
        if hasattr(self, "auto_reschedule_action"):
            with QSignalBlocker(self.auto_reschedule_action):
                self.auto_reschedule_action.setChecked(self.model.dependencies_auto_reschedule)
        if hasattr(self, "initiative_rollup_action"):
            with QSignalBlocker(self.initiative_rollup_action):
                self.initiative_rollup_action.setChecked(False)

        self._connect_model_signals()
        self._refresh_rows()
        if hasattr(self, "subject_legend"):
            self.subject_legend._active_id = None
            self.subject_legend.set_model(self.model)
        self._search_matches = []
        if hasattr(self, "planning_toolbar"):
            with QSignalBlocker(self.planning_toolbar.search_edit):
                self.planning_toolbar.search_edit.clear()
        self.inspector._selected_ids = []
        self.inspector.set_selected_object(None)
        if view_state is not None:
            label_width_value = view_state.get("label_width")
            if label_width_value is not None:
                try:
                    label_width = float(label_width_value)
                except (TypeError, ValueError):
                    label_width = None
                if label_width is not None:
                    self._suppress_view_dirty = True
                    try:
                        self.scene.set_label_width(label_width)
                    finally:
                        self._suppress_view_dirty = False
        self._apply_auto_export_settings(view_state)
        if self.presentation_mode_action.isChecked():
            self.scene.set_edit_mode(False)
            self.view.set_navigation_mode(True)
        else:
            enabled = self.nav_mode_action.isChecked()
            self.scene.set_edit_mode(not enabled)
            self.view.set_navigation_mode(enabled)
        self._apply_presentation_mode(self.presentation_mode_action.isChecked())
        self._apply_text_boxes_visibility()
        self.scene.show_missing_scope = self.missing_scope_action.isChecked()
        self.scene.update_risk_badges()

        if view_state:
            zoom = float(view_state.get("zoom", 1.0))
            self.view.set_zoom(zoom)
            self.view.horizontalScrollBar().setValue(int(view_state.get("scroll_x", 0)))
            self.view.verticalScrollBar().setValue(int(view_state.get("scroll_y", 0)))
        else:
            self.view.set_zoom(1.0)
            self.view.center_on_base_year()

    def _toggle_properties_pane(self) -> None:
        if not self.properties_pane_action.isChecked():
            self.flush_editors()
        self._apply_properties_visibility()

    def _apply_properties_visibility(self) -> None:
        show_properties = self.properties_pane_action.isChecked()
        visible = show_properties and not self.presentation_mode_action.isChecked()
        self.details_dock.setVisible(visible)

    def _setup_details_dock(self) -> None:
        self.details_dock = QDockWidget("Details", self)
        self.details_dock.setObjectName("detailsDock")
        self.details_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.details_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.details_dock.setMinimumWidth(300)
        self.details_dock.setMaximumWidth(520)
        self.inspector.setMinimumWidth(300)
        self.inspector.setMaximumWidth(520)
        details_scroll = QScrollArea()
        details_scroll.setObjectName("detailsScroll")
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_scroll.setWidget(self.inspector)
        self.details_dock.setWidget(details_scroll)

        title_bar = QWidget()
        title_bar.setObjectName("detailsDockHeader")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 7, 8, 7)
        title_layout.setSpacing(6)
        title = QLabel("Details")
        title.setObjectName("detailsDockTitle")
        title_layout.addWidget(title)
        title_layout.addStretch()
        collapse = QToolButton()
        collapse.setObjectName("detailsDockCollapse")
        collapse.setText("›")
        collapse.setToolTip("Hide Details")
        collapse.setAccessibleName("Hide Details")
        collapse.clicked.connect(self.properties_pane_action.trigger)
        title_layout.addWidget(collapse)
        self.details_dock.setTitleBarWidget(title_bar)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)
        self.resizeDocks([self.details_dock], [360], Qt.Orientation.Horizontal)
        self.details_dock.visibilityChanged.connect(self._on_details_dock_visibility_changed)
        self.details_dock.setVisible(self.properties_pane_action.isChecked())

    def _on_details_dock_visibility_changed(self, visible: bool) -> None:
        if self._suppress_properties_sync or self.presentation_mode_action.isChecked():
            return
        with QSignalBlocker(self.properties_pane_action):
            self.properties_pane_action.setChecked(visible)

    def _toggle_navigation_mode(self) -> None:
        self.flush_editors()
        enabled = self.nav_mode_action.isChecked()
        if not enabled:
            # One interaction mode must always remain active.
            with QSignalBlocker(self.nav_mode_action):
                self.nav_mode_action.setChecked(True)
            return
        self._apply_interaction_mode("navigation")

    def _toggle_edit_mode(self) -> None:
        self.flush_editors()
        enabled = self.edit_mode_action.isChecked()
        if not enabled:
            with QSignalBlocker(self.edit_mode_action):
                self.edit_mode_action.setChecked(True)
            return
        self._apply_interaction_mode("edit")

    def _toggle_presentation_mode(self) -> None:
        self.flush_editors()
        enabled = self.presentation_mode_action.isChecked()
        self._apply_interaction_mode("presentation" if enabled else "edit")

    def _apply_interaction_mode(self, mode: str) -> None:
        """Apply one complete interaction state, including inspector locking."""
        if mode not in {"edit", "navigation", "presentation"}:
            raise ValueError(f"Unknown interaction mode: {mode}")
        presentation = mode == "presentation"
        editing = mode == "edit"
        with QSignalBlocker(self.edit_mode_action), QSignalBlocker(
            self.nav_mode_action
        ), QSignalBlocker(self.presentation_mode_action):
            self.edit_mode_action.setChecked(editing)
            self.nav_mode_action.setChecked(mode == "navigation")
            self.presentation_mode_action.setChecked(presentation)
        self.scene.set_edit_mode(editing)
        self.view.set_navigation_mode(not editing)
        if not editing:
            self.view.activate_create_tool(None)
        self._apply_presentation_mode(presentation)

    def _toggle_canvas_fullscreen(self) -> None:
        self._apply_canvas_fullscreen(not self._canvas_fullscreen)

    def interaction_mode_index(self) -> int:
        if self._canvas_fullscreen:
            return 3
        if self.presentation_mode_action.isChecked():
            return 2
        if self.nav_mode_action.isChecked():
            return 1
        return 0

    def set_interaction_mode(self, index: int) -> None:
        if index == 3:
            if not self._canvas_fullscreen:
                self._apply_canvas_fullscreen(True)
            return
        if self._canvas_fullscreen:
            self._apply_canvas_fullscreen(False)
        self.flush_editors()
        with QSignalBlocker(self.presentation_mode_action):
            self.presentation_mode_action.setChecked(index == 2)
        self._toggle_presentation_mode()
        if index != 2:
            with QSignalBlocker(self.nav_mode_action):
                self.nav_mode_action.setChecked(index == 1)
            self._toggle_navigation_mode()

    def _apply_canvas_fullscreen(self, enabled: bool) -> None:
        if enabled == self._canvas_fullscreen:
            return
        if enabled:
            self.flush_editors()
            self._canvas_fullscreen = True
            self._fullscreen_previous_state = self.windowState()
            self._fullscreen_previous_chrome = {
                "menu": self.menuBar().isVisible(),
                "header": self.header_bar.isVisible(),
                "planning_toolbar": self.planning_toolbar.isVisible(),
                "status": self.statusBar().isVisible(),
                "details": self.details_dock.isVisible(),
                "legend": self.subject_legend.isVisible(),
            }
            self._fullscreen_previous_mode = {
                "presentation": self.presentation_mode_action.isChecked(),
                "navigation": self.nav_mode_action.isChecked(),
            }
            workspace_layout = self.centralWidget().layout()
            timeline_layout = self.timeline_card.layout()
            self._fullscreen_previous_margins = (
                workspace_layout.contentsMargins(),
                timeline_layout.contentsMargins(),
            )
            workspace_layout.setContentsMargins(0, 0, 0, 0)
            timeline_layout.setContentsMargins(0, 0, 0, 0)
            self.menuBar().hide()
            self.header_bar.hide()
            self.planning_toolbar.hide()
            self.statusBar().hide()
            self.details_dock.hide()
            self.subject_legend.hide()
            with QSignalBlocker(self.canvas_fullscreen_action):
                self.canvas_fullscreen_action.setChecked(True)
            if not self.presentation_mode_action.isChecked():
                with QSignalBlocker(self.presentation_mode_action):
                    self.presentation_mode_action.setChecked(True)
                self._toggle_presentation_mode()
            self.showFullScreen()
            self.toast.show_fullscreen_hint()
            self.view.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        self._canvas_fullscreen = False
        self.showNormal()
        if self._fullscreen_previous_state is not None:
            self.setWindowState(self._fullscreen_previous_state)
        workspace_layout = self.centralWidget().layout()
        timeline_layout = self.timeline_card.layout()
        if self._fullscreen_previous_margins is not None:
            workspace_layout.setContentsMargins(self._fullscreen_previous_margins[0])
            timeline_layout.setContentsMargins(self._fullscreen_previous_margins[1])
        chrome = self._fullscreen_previous_chrome or {}
        self.menuBar().setVisible(chrome.get("menu", True))
        self.header_bar.setVisible(chrome.get("header", True))
        self.planning_toolbar.setVisible(chrome.get("planning_toolbar", True))
        self.statusBar().setVisible(chrome.get("status", True))
        self.subject_legend.setVisible(chrome.get("legend", True))
        previous_mode = self._fullscreen_previous_mode or {}
        if previous_mode.get("presentation", False):
            self._apply_interaction_mode("presentation")
        elif previous_mode.get("navigation", False):
            self._apply_interaction_mode("navigation")
        else:
            self._apply_interaction_mode("edit")
        self._apply_properties_visibility()
        self.details_dock.setVisible(chrome.get("details", False))
        with QSignalBlocker(self.canvas_fullscreen_action):
            self.canvas_fullscreen_action.setChecked(False)
        self._fullscreen_previous_state = None
        self._fullscreen_previous_chrome = None
        self._fullscreen_previous_mode = None
        self._fullscreen_previous_margins = None
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_presentation_mode(self, enabled: bool) -> None:
        self.nav_mode_action.setEnabled(not enabled)
        self.properties_pane_action.setEnabled(not enabled)
        for action in self._edit_actions:
            action.setEnabled(not enabled)
        self.inspector.setEnabled(not enabled)
        self.inspector.details.setEnabled(not enabled and self.inspector._current_obj_id is not None)
        self._apply_properties_visibility()
        if enabled:
            self.view.activate_create_tool(None)
        self._sync_textbox_insert_action()

    def _sync_textbox_insert_action(self) -> None:
        enabled = self.scene.show_textboxes and not self.presentation_mode_action.isChecked()
        self.add_textbox_action.setEnabled(enabled)

    def _apply_text_boxes_visibility(self) -> None:
        show_textboxes = self.text_boxes_action.isChecked()
        visibility_changed = self.scene.show_textboxes != show_textboxes
        self.scene.show_textboxes = show_textboxes
        if not show_textboxes and self.view.active_create_tool() == "textbox":
            self.view.activate_create_tool(None)
        if visibility_changed:
            self.scene.refresh_items(force_sync=True)
        self._sync_textbox_insert_action()

    def _toggle_snap_grid(self) -> None:
        enabled = self.snap_grid_action.isChecked()
        self.scene.snap_weeks = enabled
        self.scene.snap_rows = enabled
        if not enabled:
            self.view._clear_snap_guide()
            self.scene.set_status("")

    def _toggle_position_guidance(self) -> None:
        self.view.set_position_guidance_enabled(
            self.position_guidance_action.isChecked()
        )

    def _toggle_current_week_line(self) -> None:
        self.scene.show_current_week = self.current_week_action.isChecked()
        self.scene.update_headers()

    def _toggle_missing_scope(self) -> None:
        self.scene.show_missing_scope = self.missing_scope_action.isChecked()
        self.scene.update_risk_badges()

    def _toggle_auto_reschedule(self) -> None:
        if hasattr(self, "controller"):
            self.controller.set_auto_reschedule(self.auto_reschedule_action.isChecked())

    def _toggle_text_boxes(self) -> None:
        self._apply_text_boxes_visibility()

    def _toggle_dark_mode(self) -> None:
        self._apply_dark_mode(self.dark_mode_action.isChecked(), persist=True)

    def _apply_dark_mode(self, enabled: bool, *, persist: bool = False) -> None:
        self._dark_mode = bool(enabled)
        app = QApplication.instance()
        if app is not None:
            theme.apply_palette(app, self._dark_mode)
        self.setStyleSheet(theme.build_stylesheet(self._dark_mode))
        if hasattr(self, "scene") and self.scene is not None:
            self.scene.dark_mode = self._dark_mode
            self.scene.update()
            self.scene.grid_item.update()
        if hasattr(self, "subject_legend"):
            self.subject_legend.set_dark_mode(self._dark_mode)
        if hasattr(self, "planning_toolbar"):
            self.planning_toolbar.refresh_theme_icons(self._dark_mode)
        if persist:
            self.settings.setValue("view/dark_mode", self._dark_mode)

    def _toggle_auto_export(self) -> None:
        enabled = self.auto_export_action.isChecked()
        previous_enabled = self._auto_export_enabled
        if enabled and self._auto_export_path is None:
            if not self._configure_auto_export(require_path=True):
                with QSignalBlocker(self.auto_export_action):
                    self.auto_export_action.setChecked(False)
                enabled = False
        self._auto_export_enabled = enabled
        if enabled != previous_enabled:
            self._set_view_dirty(True)
        if enabled:
            self._warn_auto_export_constraints()

    def maybe_save(self) -> bool:
        self.flush_editors()
        if self.undo_stack.isClean() and not self._view_dirty:
            return True
        result = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save changes before continuing?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Yes:
            return self.save_project()
        if result == QMessageBox.StandardButton.Cancel:
            return False
        return True

    def new_project(self) -> None:
        if not self.maybe_save():
            return
        year, ok = QInputDialog.getInt(self, "New Project", "Year", datetime.now().year)
        if not ok:
            return
        self.undo_stack.clear()
        self.current_path = None
        self._save_failed = False
        self._set_model(ProjectModel(year=year))
        self.undo_stack.setClean()
        self._set_view_dirty(False)
        self._update_title()

    def open_project(self) -> None:
        if not self.maybe_save():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "Project Plans (*.json)")
        if not filename:
            return
        try:
            self._load_from_path(Path(filename))
        except Exception as exc:
            QMessageBox.warning(self, "Open Failed", f"Could not open project file.\n{exc}")

    def _load_from_path(self, path: Path) -> None:
        self.flush_editors()
        model, view_state = load_project(path)
        self.undo_stack.clear()
        self.current_path = path
        self._save_failed = False
        self._set_model(model, view_state)
        self.undo_stack.setClean()
        self._set_view_dirty(False)
        self.settings.setValue("last_file", str(path))
        self._add_recent_file(path)
        self._update_title()

    def _history_action(self, redo):
        self.flush_editors()
        if not self.presentation_mode_action.isChecked():
            self.undo_stack.redo() if redo else self.undo_stack.undo()

    def flush_editors(self) -> None:
        self.view._finish_inline_edit(True)
        if hasattr(self.inspector, "commit_pending"):
            self.inspector.commit_pending()
        if hasattr(self, "context_editor"):
            self.context_editor.commit_pending()
        focused = QApplication.focusWidget()
        if focused and self.inspector.isAncestorOf(focused):
            focused.clearFocus()

    def _tool_changed(self, kind) -> None:
        names = {"box": "activity", "textbox": "textbox"}
        if kind:
            self.statusBar().showMessage(f"Place {names.get(kind, kind)} · Drag to create · Esc to cancel")
        else:
            self.statusBar().clearMessage()

    def _save_to_path(self, path: Path) -> bool:
        self.flush_editors()
        while True:
            try:
                save_project(path, self.model, self._view_state())
                break
            except Exception as exc:
                self._save_failed = True
                self._set_view_dirty(True)
                self._update_title()
                dialog = QMessageBox(QMessageBox.Icon.Warning, "Save failed", str(exc), parent=self)
                retry = dialog.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
                save_as = dialog.addButton("Save As…", QMessageBox.ButtonRole.ActionRole)
                dialog.addButton(QMessageBox.StandardButton.Cancel)
                dialog.exec()
                if dialog.clickedButton() == retry:
                    continue
                if dialog.clickedButton() == save_as:
                    return self.save_project_as()
                return False
        self.current_path = path
        self._save_failed = False
        self.undo_stack.setClean()
        self._set_view_dirty(False)
        self._update_title()
        self.settings.setValue("last_file", str(path))
        self._add_recent_file(path)
        self.notify("Plan saved", "success", status=True)
        self._maybe_auto_export_png()
        return True

    def save_project(self) -> bool:
        self.flush_editors()
        return self._save_to_path(self.current_path) if self.current_path else self.save_project_as()

    def save_project_as(self) -> bool:
        self.flush_editors()
        filename, _ = QFileDialog.getSaveFileName(self, "Save Project As", "", "Project Plans (*.json)")
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        return self._save_to_path(path)

    def show_auto_export_preferences(self) -> None:
        self._configure_auto_export(require_path=False)

    def _configure_auto_export(self, require_path: bool) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Automatic Export Settings")
        layout = QFormLayout(dialog)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        dialog.setMinimumWidth(520)
        layout.addRow(QLabel("Automatic PNG export runs after eligible plan changes."))
        path_input = QLineEdit(dialog)
        path_input.setMinimumWidth(320)
        if self._auto_export_path is not None:
            path_input.setText(str(self._auto_export_path))
        else:
            path_input.setPlaceholderText("Select a PNG file")
        browse_button = QPushButton("Browse...", dialog)
        path_row = QWidget(dialog)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(path_input)
        path_layout.addWidget(browse_button)

        def _browse() -> None:
            start_path = path_input.text().strip()
            if not start_path:
                start_path = self._default_auto_export_path()
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Select Auto-export File",
                start_path,
                "PNG Files (*.png)",
            )
            if filename:
                normalized = self._normalize_auto_export_path(Path(filename))
                path_input.setText(str(normalized))

        browse_button.clicked.connect(_browse)
        layout.addRow("Destination file", path_row)

        quarters_spin = QSpinBox(dialog)
        quarters_spin.setRange(0, 12)
        quarters_spin.setValue(self._auto_export_additional_quarters)
        quarters_spin.setSuffix(" quarters")
        layout.addRow("Additional quarters", quarters_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)

        def _accept() -> None:
            path_value = path_input.text().strip()
            needs_path = require_path or self._auto_export_enabled
            if needs_path and not path_value:
                QMessageBox.warning(
                    dialog, "Automatic Export Settings", "Select a destination file."
                )
                return
            if path_value:
                raw_candidate = Path(path_value).expanduser()
                if raw_candidate.exists() and raw_candidate.is_dir():
                    QMessageBox.warning(
                        dialog,
                        "Automatic Export Settings",
                        "Destination must be a file.",
                    )
                    return
                candidate = self._normalize_auto_export_path(raw_candidate)
                if candidate.parent.exists() and not candidate.parent.is_dir():
                    QMessageBox.warning(
                        dialog,
                        "Automatic Export Settings",
                        "Destination folder is invalid.",
                    )
                    return
                path_input.setText(str(candidate))
            dialog.accept()

        buttons.accepted.connect(_accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        path_value = path_input.text().strip()
        if path_value:
            path = self._normalize_auto_export_path(Path(path_value).expanduser())
        else:
            path = None
        additional_quarters = quarters_spin.value()
        previous_path = self._auto_export_path
        previous_quarters = self._auto_export_additional_quarters
        self._auto_export_path = path
        self._auto_export_additional_quarters = additional_quarters
        if path != previous_path or additional_quarters != previous_quarters:
            self._set_view_dirty(True)
        if self._auto_export_enabled:
            self._warn_auto_export_constraints()
        return True

    def _warn_auto_export_constraints(self) -> None:
        message = self._auto_export_warning_message()
        if message:
            QMessageBox.warning(self, "Auto-export", message)

    def _auto_export_warning_message(self) -> str | None:
        if not self._auto_export_enabled:
            return None
        path = self._auto_export_path
        if path is None:
            return "Auto-export is enabled but no destination file is configured."
        if path.exists() and path.is_dir():
            return f"Auto-export destination must be a file:\n{path}"
        path = self._normalize_auto_export_path(path)
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            return f"Auto-export destination folder is invalid:\n{parent}"
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return (
                    "Auto-export cannot create the destination folder:\n"
                    f"{parent}\n{exc}"
                )
        if path.exists():
            if not os.access(path, os.W_OK):
                return f"Auto-export destination is not writable:\n{path}"
        else:
            if not os.access(parent, os.W_OK):
                return f"Auto-export folder is not writable:\n{parent}"
        return None

    def _maybe_auto_export_png(self) -> None:
        if not self._auto_export_enabled:
            return
        if self._auto_export_path is None:
            return
        try:
            self._auto_export_png()
        except Exception as exc:
            QMessageBox.warning(self, "Auto-export", f"Could not auto-export PNG.\n{exc}")

    def _auto_export_png(self) -> None:
        source_rect = self._auto_export_range()
        if source_rect is None:
            return
        path = self._auto_export_path
        if path is None:
            return
        if path.exists() and path.is_dir():
            QMessageBox.warning(
                self, "Auto-export", f"Destination must be a file.\n{path}"
            )
            return
        path = self._normalize_auto_export_path(path)
        folder = path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(
                self, "Auto-export", f"Could not create export folder.\n{exc}"
            )
            return
        if not self._export_png_to_path(path, source_rect):
            QMessageBox.warning(
                self, "Auto-export", f"Could not save auto-export PNG.\n{path}"
            )

    def _auto_export_range(self) -> QRectF | None:
        additional_quarters = max(0, int(self._auto_export_additional_quarters))
        entries = self._quarter_entries(additional_quarters)
        if not entries:
            return None
        current_year, current_quarter = self._current_iso_quarter()
        end_year, end_quarter = self._add_quarters(
            current_year, current_quarter, additional_quarters
        )
        entry_index = {
            (entry["year"], entry["quarter"]): idx for idx, entry in enumerate(entries)
        }
        start_entry = entries[entry_index.get((current_year, current_quarter), 0)]
        end_entry = entries[entry_index.get((end_year, end_quarter), len(entries) - 1)]
        return self._export_rect_for_entries(start_entry, end_entry)

    def _choose_export_rect(self) -> QRectF | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Planning Export Range")
        form = QFormLayout(dialog)
        mode_combo = QComboBox(dialog)
        mode_combo.addItem("Entire plan", "plan")
        mode_combo.addItem("Visible canvas", "visible")
        mode_combo.addItem("Quarter range...", "quarters")
        form.addRow("Range", mode_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        mode = mode_combo.currentData()
        if mode == "plan":
            return self.view._fit_content_rect()
        if mode == "visible":
            return self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        return self._select_export_range()

    def export_png(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export PNG",
            self._default_export_path("png"),
            "PNG Files (*.png)",
        )
        if not filename:
            return
        path = Path(filename)
        source_rect = self._choose_export_rect()
        if source_rect is None:
            return
        if self._export_png_to_path(path, source_rect):
            self._prompt_open_export_folder("Export PNG", path)

    def copy_image_to_clipboard(self) -> None:
        source_rect = self._select_export_range()
        if source_rect is None:
            return
        image = self._render_export_png_image(source_rect)
        if image.isNull():
            QMessageBox.warning(
                self, "Copy Image to Clipboard", "Could not render planning image."
            )
            return
        clipboard = QApplication.clipboard()
        clipboard.setImage(image)
        self.notify("Planning image copied to clipboard.", "success")

    def export_pdf(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF",
            self._default_export_path("pdf"),
            "PDF Files (*.pdf)",
        )
        if not filename:
            return
        path = Path(filename)
        source_rect = self._choose_export_rect()
        if source_rect is None:
            return
        pdf_source_rect = self._pdf_safe_source_rect(source_rect)
        writer = QPdfWriter(str(path))
        writer.setResolution(72)
        writer.setPageSize(QPageSize(pdf_source_rect.size(), QPageSize.Unit.Point))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        painter = QPainter(writer)
        target = QRectF(writer.pageLayout().paintRectPixels(writer.resolution()))
        self._render_export(painter, pdf_source_rect, target)
        painter.end()
        if path.exists():
            self._prompt_open_export_folder("Export PDF", path)

    def _export_png_to_path(self, path: Path, source_rect: QRectF) -> bool:
        image = self._render_export_png_image(source_rect)
        return image.save(str(path))

    def _render_export_png_image(self, source_rect: QRectF) -> QImage:
        image_width = max(1, math.ceil(source_rect.width()))
        image_height = max(1, math.ceil(source_rect.height()))
        image = QImage(image_width, image_height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        target = QRectF(0, 0, image.width(), image.height())
        self._render_export(painter, source_rect, target)
        painter.end()
        return image

    def export_risks(self) -> None:
        rows = self._collect_risk_rows()
        if not rows:
            QMessageBox.information(self, "Export Risks", "No risks to export.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Risks",
            self._default_risks_export_path(),
            "CSV Files (*.csv)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["week", "deliverable", "risk", "probability", "impact"])
                writer.writerows(rows)
        except Exception as exc:
            QMessageBox.warning(self, "Export Risks", f"Could not export risks.\n{exc}")
            return
        count = len(rows)
        self.notify(f"Exported {count} risk{'s' if count != 1 else ''} to {path.name}", "success")
        self._prompt_open_export_folder("Export Risks", path)

    def export_scope(self) -> None:
        selected_rows = self._select_scope_rows()
        if not selected_rows:
            return
        lines, count = self._collect_scope_lines(selected_rows)
        if count == 0:
            QMessageBox.information(self, "Export Scope", "No scope entries to export.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Scope",
            self._default_scope_export_path(),
            "Markdown Files (*.md)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".md":
            path = path.with_suffix(".md")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join(lines)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Export Scope", f"Could not export scope.\n{exc}")
            return
        self.notify(f"Exported {count} scope item{'s' if count != 1 else ''} to {path.name}", "success")
        self._prompt_open_export_folder("Export Scope", path)

    def _render_export(self, painter: QPainter, source_rect: QRectF, target_rect: QRectF) -> None:
        selected = list(self.scene.selectedItems())
        overlays = [
            item
            for item in (
                self.view._create_preview,
                self.view._connector_preview,
                *self.view.transient_dependency_items(),
                *self.scene.dependency_interaction_items(),
                getattr(self.scene, "dependency_layer", None),
            )
            if item is not None and item.isVisible()
        ]
        self.scene.exporting = True
        try:
            with QSignalBlocker(self.scene):
                for item in selected:
                    item.setSelected(False)
                for item in overlays:
                    item.setVisible(False)
                self.scene.render(painter, target_rect, source_rect)
                self._draw_export_labels(painter, source_rect, target_rect)
        finally:
            with QSignalBlocker(self.scene):
                for item in selected:
                    item.setSelected(True)
                for item in overlays:
                    item.setVisible(True)
            self.scene.exporting = False

    def _pdf_safe_source_rect(self, source_rect: QRectF) -> QRectF:
        safe_rect = QRectF(source_rect)
        for obj_id, item in self.scene.items_by_id.items():
            if not item.isVisible():
                continue
            if self.model.objects.get(obj_id) is None:
                continue
            item_rect = item.sceneBoundingRect()
            if item_rect.isNull() or not item_rect.intersects(source_rect):
                continue
            text_rect = self._pdf_text_bounds(item)
            if text_rect.isNull():
                continue
            safe_rect = safe_rect.united(text_rect)
        return safe_rect

    def _pdf_text_bounds(self, item) -> QRectF:
        rect = QRectF()
        if isinstance(item, QGraphicsTextItem):
            text_rect = item.sceneBoundingRect()
            if not text_rect.isNull():
                bleed_left, bleed_top, bleed_right, bleed_bottom = self._pdf_text_bleed(item)
                rect = text_rect.adjusted(
                    -bleed_left,
                    -bleed_top,
                    bleed_right,
                    bleed_bottom,
                )
        for child in item.childItems():
            if not child.isVisible():
                continue
            child_rect = self._pdf_text_bounds(child)
            if child_rect.isNull():
                continue
            rect = child_rect if rect.isNull() else rect.united(child_rect)
        return rect

    def _pdf_text_bleed(self, text_item: QGraphicsTextItem) -> tuple[float, float, float, float]:
        document = text_item.document()
        margin = float(document.documentMargin()) if document is not None else 0.0
        base_font = QFont(document.defaultFont()) if document is not None else QFont(text_item.font())
        fonts: list[QFont] = []
        seen: set[tuple[float, int, str, int, bool]] = set()

        def _add_font(font: QFont | None) -> None:
            candidate = QFont(font) if font is not None else QFont(base_font)
            if candidate.pointSizeF() <= 0 and candidate.pixelSize() <= 0:
                candidate = QFont(base_font)
            key = (
                round(candidate.pointSizeF(), 2),
                candidate.pixelSize(),
                candidate.family(),
                candidate.weight(),
                candidate.italic(),
            )
            if key in seen:
                return
            seen.add(key)
            fonts.append(candidate)

        _add_font(text_item.font())
        _add_font(base_font)

        if document is not None:
            block = document.begin()
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid():
                        _add_font(fragment.charFormat().font())
                    iterator += 1
                block = block.next()

        max_ascent = 0.0
        max_descent = 0.0
        max_leading = 0.0
        for font in fonts:
            metrics = QFontMetricsF(font)
            max_ascent = max(max_ascent, metrics.ascent())
            max_descent = max(max_descent, metrics.descent())
            max_leading = max(max_leading, metrics.leading())

        horizontal_bleed = (margin * 0.5) + max(1.0, max_ascent * 0.05)
        top_bleed = margin + max(1.0, (max_ascent * 0.15) + (max_leading * 0.5))
        bottom_bleed = (margin * 0.5) + max(1.0, (max_descent * 0.6) + (max_leading * 0.5))
        return horizontal_bleed, top_bleed, horizontal_bleed, bottom_bleed

    def _prompt_open_export_folder(self, title: str, path: Path) -> None:
        folder = path.parent
        result = QMessageBox.question(
            self,
            title,
            f"Open the save folder?\n{folder}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _default_export_path(self, extension: str) -> str:
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if not download_dir:
            download_dir = str(Path.home() / "Downloads")
        base = self.current_path.stem if self.current_path else "untitled"
        timestamp = datetime.now().strftime("%Y_%m_%d_%H-%M-%S")
        filename = f"export_{base}_{timestamp}.{extension}"
        return str(Path(download_dir) / filename)

    def _default_auto_export_path(self) -> str:
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if not download_dir:
            download_dir = str(Path.home() / "Downloads")
        base = self.current_path.stem if self.current_path else "untitled"
        filename = f"auto_export_{base}.png"
        return str(Path(download_dir) / filename)

    @staticmethod
    def _normalize_auto_export_path(path: Path) -> Path:
        if path.suffix.lower() != ".png":
            return path.with_suffix(".png")
        return path

    def _default_risks_export_path(self) -> str:
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if not download_dir:
            download_dir = str(Path.home() / "Downloads")
        base = self.current_path.stem if self.current_path else "untitled"
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        filename = f"risks_{base}_{timestamp}.csv"
        return str(Path(download_dir) / filename)

    def _default_scope_export_path(self) -> str:
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if not download_dir:
            download_dir = str(Path.home() / "Downloads")
        base = self.current_path.stem if self.current_path else "untitled"
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        filename = f"scope_{base}_{timestamp}.md"
        return str(Path(download_dir) / filename)

    def _collect_risk_rows(self) -> list[list[str]]:
        layout = self.scene.layout
        include_textboxes = self.scene.show_textboxes
        rows: list[list[str]] = []
        for obj in self.model.objects.values():
            if not include_textboxes and obj.kind == "textbox":
                continue
            if not obj.risks or not obj.risks.strip():
                continue
            week_label = self._week_label(layout, obj.start_week)
            row_label = self._row_label(obj.row_id)
            for line in obj.risks.splitlines():
                risk_text, probability, impact = self._parse_risk_line(line)
                if not risk_text:
                    continue
                rows.append([week_label, row_label, risk_text, probability, impact])
        return rows

    def _collect_scope_lines(self, selected_rows: set[str]) -> tuple[list[str], int]:
        layout = self.scene.layout
        include_textboxes = self.scene.show_textboxes
        selected_rows = set(selected_rows)
        selected_rows.add(CANVAS_ROW_ID)
        objects_by_row: dict[str, list] = {}
        all_objects: list = []
        base_text_by_id: dict[str, list[str]] = {}
        for obj in self.model.objects.values():
            if obj.kind in ("link", "connector", "arrow"):
                continue
            if not include_textboxes and obj.kind == "textbox":
                continue
            if obj.row_id not in selected_rows:
                continue
            base_lines = self._normalize_lines(obj.text)
            base_text_by_id[obj.id] = base_lines
            objects_by_row.setdefault(obj.row_id, []).append(obj)
            all_objects.append(obj)
        for row_id, row_objects in objects_by_row.items():
            row_objects.sort(key=lambda obj: (obj.start_week, obj.end_week, obj.id))

        linked_text: dict[str, list[str]] = {}
        if include_textboxes:
            for link in self.model.objects.values():
                if link.kind != "link":
                    continue
                source_id = link.link_source_id
                target_id = link.link_target_id
                if not source_id or not target_id:
                    continue
                source = self.model.objects.get(source_id)
                if source is None or source.kind != "textbox":
                    continue
                text = source.text.strip()
                if not text:
                    continue
                linked_text.setdefault(target_id, []).append(text)

        text_lines_by_id: dict[str, list[str]] = {}
        for obj_id, base_lines in base_text_by_id.items():
            lines = list(base_lines)
            for entry in linked_text.get(obj_id, []):
                lines.extend(self._normalize_lines(entry))
            text_lines_by_id[obj_id] = lines

        objects_by_id = {obj.id: obj for obj in all_objects}
        name_by_id: dict[str, str] = {}
        for obj_id, obj in objects_by_id.items():
            lines = text_lines_by_id.get(obj_id, [])
            if lines:
                name_by_id[obj_id] = lines[0]
            else:
                name_by_id[obj_id] = self._scope_unnamed_label(obj)

        dependencies = self._collect_scope_dependencies(selected_rows, objects_by_row)

        included_topics = []
        for topic in self.model.topics:
            topic_objects = objects_by_row.get(topic.id, [])
            include_topic_row = topic.id in selected_rows and bool(topic_objects)
            deliverables = [
                d
                for d in topic.deliverables
                if d.id in selected_rows and objects_by_row.get(d.id)
            ]
            if include_topic_row or deliverables:
                included_topics.append((topic, include_topic_row, deliverables))
        canvas_objects = objects_by_row.get(CANVAS_ROW_ID, [])

        lines: list[str] = []
        if all_objects:
            min_week = min(obj.start_week for obj in all_objects)
            ref_label = self._week_label(layout, min_week)
            ref_date = layout.week_index_to_date(self.model.year, min_week).isoformat()
            lines.extend(
                [
                    "## Calendar",
                    "- Interpretation: continuous_weeks",
                    "- Week standard: ISO-8601",
                    "- Reference:",
                    f"  - {ref_label}: {ref_date}",
                    "",
                    "> **Note on unnamed items**  ",
                    "> Some planning objects intentionally have no explicit name.  ",
                    '> These are exported as "(Unnamed ...)" to preserve full traceability.',
                    "",
                    "## Plan Metadata",
                    f"- Year: {self.model.year}",
                    f"- Classification: {self.model.classification}",
                    f"- Schema version: {SCHEMA_VERSION}",
                    "",
                ]
            )
        count = 0
        for index, (topic, include_topic_row, deliverables) in enumerate(included_topics):
            if index:
                lines.append("---")
                lines.append("")
            topic_title = topic.name.strip() or self._scope_unnamed_item_label("section")
            lines.append(f"# {topic_title}")
            lines.append("")
            if include_topic_row:
                topic_objects = objects_by_row.get(topic.id, [])
                week_lines, section_count = self._scope_week_groups_lines(
                    topic_objects, layout, text_lines_by_id
                )
                if week_lines:
                    lines.extend(week_lines)
                    count += section_count
                    lines.append("")
            for deliverable in deliverables:
                deliverable_title = (
                    deliverable.name.strip()
                    or self._scope_unnamed_item_label("deliverable")
                )
                section_lines, section_count = self._scope_deliverable_section(
                    deliverable_title,
                    objects_by_row.get(deliverable.id, []),
                    layout,
                    text_lines_by_id,
                )
                if section_lines:
                    lines.extend(section_lines)
                    count += section_count

        if canvas_objects:
            if included_topics:
                lines.append("---")
                lines.append("")
            lines.append("# Canvas")
            lines.append("")
            week_lines, section_count = self._scope_week_groups_lines(
                canvas_objects, layout, text_lines_by_id
            )
            if week_lines:
                lines.extend(week_lines)
                count += section_count
                lines.append("")

        dependency_section = self._scope_dependency_section(dependencies, name_by_id)
        if dependency_section:
            lines.extend(dependency_section)
            lines.append("")

        deadline_section = self._scope_deadline_section(
            list(self.model.objects.values()), layout, name_by_id
        )
        if deadline_section:
            lines.extend(deadline_section)
            lines.append("")

        reference_section = self._scope_reference_section(
            objects_by_id, text_lines_by_id, layout
        )
        if reference_section:
            lines.extend(reference_section)
            lines.append("")

        while lines and lines[-1] == "":
            lines.pop()
        return lines, count

    def _scope_deliverable_section(
        self,
        title: str,
        objects: list,
        layout,
        text_lines_by_id: dict[str, list[str]],
    ) -> tuple[list[str], int]:
        week_lines, count = self._scope_week_groups_lines(
            objects, layout, text_lines_by_id
        )
        if not week_lines:
            return [], 0
        lines: list[str] = [f"## {title}", ""]
        lines.extend(week_lines)
        lines.append("")
        return lines, count

    def _scope_week_groups_lines(
        self,
        objects: list,
        layout,
        text_lines_by_id: dict[str, list[str]],
    ) -> tuple[list[str], int]:
        lines: list[str] = []
        if not objects:
            return lines, 0
        week_groups: dict[int, list] = {}
        for obj in objects:
            week_groups.setdefault(obj.start_week, []).append(obj)
        count = 0
        for week in sorted(week_groups):
            week_label = self._week_label(layout, week)
            lines.append(f"### {week_label}")
            lines.append("")
            week_objects = week_groups[week]
            show_roles = len(week_objects) > 1
            role_groups: dict[str, list] = {}
            for obj in week_objects:
                role_groups.setdefault(self._scope_role_for_object(obj), []).append(obj)
            for role in self._scope_role_order():
                group = role_groups.get(role)
                if not group:
                    continue
                if show_roles:
                    lines.append(f"#### {role}")
                    lines.append("")
                for obj in group:
                    lines.extend(self._scope_object_lines(obj, text_lines_by_id))
                    count += 1
                lines.append("")
            if lines and lines[-1] == "":
                lines.pop()
            lines.append("")
        if lines and lines[-1] == "":
            lines.pop()
        return lines, count

    def _scope_object_lines(
        self,
        obj,
        text_lines_by_id: dict[str, list[str]],
    ) -> list[str]:
        lines: list[str] = []
        duration = self._scope_object_duration(obj)
        if duration is not None:
            suffix = "week" if duration == 1 else "weeks"
            duration_line = f"Duration: {duration} {suffix}"
        else:
            duration_line = None

        text_lines = text_lines_by_id.get(obj.id, [])
        if text_lines:
            lines.append(f"- {text_lines[0]}")
        else:
            lines.append(f"- {self._scope_unnamed_label(obj)}")

        if len(text_lines) > 1:
            lines.append("  - Text (cont.):")
            for line in text_lines[1:]:
                lines.append(f"    - {line}")

        type_label = self._scope_object_type(obj)
        lines.append(f"  - Type: {type_label}")
        if duration_line:
            lines.append(f"  - {duration_line}")

        lines.append("  - Timing:")
        lines.append(f"    - Start offset: {obj.start_week}")
        lines.append(f"    - End offset: {obj.end_week}")

        scope_lines = self._normalize_lines(
            obj.scope, drop_labels={"scope", "scopes"}
        )
        if scope_lines:
            lines.append("  - Scope:")
            for line in scope_lines:
                lines.append(f"    - {line}")

        risk_lines = self._normalize_lines(
            obj.risks, drop_labels={"risk", "risks"}
        )
        if risk_lines:
            lines.append("  - Risks:")
            for line in risk_lines:
                lines.append(f"    - {line}")
        return lines

    def _normalize_lines(
        self, text: str, drop_labels: set[str] | None = None
    ) -> list[str]:
        lines: list[str] = []
        for raw_line in text.splitlines():
            cleaned = raw_line.strip()
            if not cleaned:
                continue
            cleaned = self._strip_bullet_prefix(cleaned)
            if drop_labels:
                cleaned = self._strip_label_prefix(cleaned, drop_labels)
                if not cleaned:
                    continue
                cleaned = self._strip_bullet_prefix(cleaned)
            if cleaned:
                lines.append(cleaned)
        return lines

    @staticmethod
    def _strip_bullet_prefix(line: str) -> str:
        cleaned = line.lstrip()
        bullet_prefixes = ("- ", "* ", "+ ")
        while True:
            original = cleaned
            for prefix in bullet_prefixes:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix) :].lstrip()
                    break
            else:
                idx = 0
                while idx < len(cleaned) and cleaned[idx].isdigit():
                    idx += 1
                if (
                    idx
                    and idx < len(cleaned)
                    and cleaned[idx] in (".", ")")
                    and idx + 1 < len(cleaned)
                    and cleaned[idx + 1].isspace()
                ):
                    cleaned = cleaned[idx + 1 :].lstrip()
                else:
                    break
            if cleaned == original:
                break
        return cleaned

    @staticmethod
    def _strip_label_prefix(line: str, labels: set[str]) -> str:
        cleaned = line.strip()
        lower = cleaned.lower()
        for label in labels:
            if lower == label or lower == f"{label}:":
                return ""
        for label in labels:
            for separator in (":", " -"):
                prefix = f"{label}{separator}"
                if lower.startswith(prefix):
                    return cleaned[len(prefix) :].strip()
        return cleaned

    def _match_dependency_object(self, objects: list, week: int):
        best = None
        for obj in objects:
            if obj.kind in ("arrow", "connector", "link"):
                continue
            if not (obj.start_week <= week <= obj.end_week):
                continue
            if week == obj.end_week:
                score = 0
                rel = "finish"
            elif week == obj.start_week:
                score = 1
                rel = "start"
            else:
                dist_start = abs(week - obj.start_week)
                dist_end = abs(obj.end_week - week)
                if dist_end <= dist_start:
                    score = 2 + dist_end
                    rel = "finish"
                else:
                    score = 2 + dist_start
                    rel = "start"
            if best is None or score < best[0]:
                best = (score, obj, rel)
        if best is None:
            return None, None
        return best[1], best[2]

    def _collect_scope_dependencies(
        self,
        selected_rows: set[str],
        objects_by_row: dict[str, list],
    ) -> list[tuple[str, str, str]]:
        dependencies: list[tuple[str, str, str]] = []
        exportable_ids = {
            obj.id for row_objects in objects_by_row.values() for obj in row_objects
        }

        def _add_dep(source, target, dep_type: str) -> None:
            if source.id not in exportable_ids or target.id not in exportable_ids:
                return
            dependencies.append((source.id, target.id, dep_type))

        for connector in self.model.objects.values():
            if connector.kind not in ("connector", "arrow"):
                continue
            source_id = connector.connector_source_id
            target_id = connector.connector_target_id
            if source_id and target_id:
                # Attached connector: dependency from explicit endpoints.
                source = self.model.objects.get(source_id)
                target = self.model.objects.get(target_id)
                if source is None or target is None:
                    continue
                if source.row_id not in selected_rows or target.row_id not in selected_rows:
                    continue
                source_rel = "start" if connector.connector_source_side == "left" else "finish"
                target_rel = "start" if connector.connector_target_side == "left" else "finish"
                dep_type = "SS" if source_rel == "start" and target_rel == "start" else "FS"
                _add_dep(source, target, dep_type)
                continue
            # Free connector: infer the dependency from row/week positions.
            source_row = connector.row_id
            target_row = connector.target_row_id or connector.row_id
            if source_row not in selected_rows or target_row not in selected_rows:
                continue
            source_obj, source_rel = self._match_dependency_object(
                objects_by_row.get(source_row, []), connector.start_week
            )
            target_week = (
                connector.target_week
                if connector.target_week is not None
                else connector.end_week
            )
            target_obj, target_rel = self._match_dependency_object(
                objects_by_row.get(target_row, []), target_week
            )
            if (
                source_obj is None
                or target_obj is None
                or source_obj.id == target_obj.id
                or source_rel is None
                or target_rel is None
            ):
                continue
            dep_type = "SS" if source_rel == "start" and target_rel == "start" else "FS"
            _add_dep(source_obj, target_obj, dep_type)

        return dependencies

    @staticmethod
    def _scope_object_type(obj) -> str:
        kind = obj.kind
        if kind == "box":
            return "Activity"
        if kind == "milestone":
            return "Milestone"
        if kind == "circle":
            return "Event"
        if kind == "deadline":
            return "Deadline"
        if kind == "textbox":
            return "Textbox"
        if kind == "arrow":
            return "Connector"
        return kind.replace("_", " ").title()

    @staticmethod
    def _scope_unnamed_item_label(item: str) -> str:
        return f"({UNNAMED_LABEL} {item})"

    def _scope_unnamed_label(self, obj) -> str:
        type_label = self._scope_object_type(obj)
        return self._scope_unnamed_item_label(type_label.lower())

    def _scope_unnamed_reference_label(self, obj, layout) -> str:
        type_label = self._scope_object_type(obj)
        week_label = self._week_label(layout, obj.start_week)
        return self._scope_unnamed_item_label(f"{type_label.lower()} @ {week_label}")

    @staticmethod
    def _scope_object_duration(obj) -> int | None:
        if obj.kind == "box":
            return max(1, obj.end_week - obj.start_week + 1)
        return None

    @staticmethod
    def _scope_role_for_object(obj) -> str:
        kind = obj.kind
        if kind in ("milestone", "circle"):
            return "Milestones"
        if kind == "box":
            return "Activities starting"
        if kind == "deadline":
            return "Deadlines"
        if kind == "textbox":
            return "Annotations"
        return "Other"

    @staticmethod
    def _scope_role_order() -> list[str]:
        return ["Milestones", "Activities starting", "Deadlines", "Annotations", "Other"]

    def _scope_deadline_section(
        self,
        objects: list,
        layout,
        name_by_id: dict[str, str],
    ) -> list[str]:
        deadlines: list[tuple[int, int, str]] = []
        for obj in objects:
            if obj.kind != "deadline":
                continue
            name = name_by_id.get(obj.id, self._scope_unnamed_label(obj))
            deadlines.append((obj.start_week, obj.end_week, name))
        if not deadlines:
            return []
        lines = ["## Deadlines", ""]
        dash = "\u2014"
        for start_week, end_week, name in sorted(
            deadlines, key=lambda item: (item[0], item[2].lower())
        ):
            week_label = self._week_label(layout, start_week)
            lines.append(f"- {name} {dash} {week_label}")
            lines.append("  - Timing:")
            lines.append(f"    - Start offset: {start_week}")
            lines.append(f"    - End offset: {end_week}")
        return lines

    @staticmethod
    def _scope_dependency_section(
        dependencies: list[tuple[str, str, str]],
        name_by_id: dict[str, str],
    ) -> list[str]:
        entries: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for source_id, target_id, dep_type in dependencies:
            source_name = name_by_id.get(source_id)
            target_name = name_by_id.get(target_id)
            if not source_name or not target_name:
                continue
            key = (source_id, target_id, dep_type)
            if key in seen:
                continue
            seen.add(key)
            entries.append((source_name, target_name, dep_type))
        if not entries:
            return []
        entries.sort(key=lambda item: (item[0].lower(), item[1].lower(), item[2]))
        lines = ["## Dependencies", ""]
        arrow = "\u2192"
        for source_name, target_name, dep_type in entries:
            lines.append(f"- {source_name} {arrow} {target_name} ({dep_type})")
        return lines

    def _scope_reference_section(
        self,
        objects_by_id: dict[str, object],
        text_lines_by_id: dict[str, list[str]],
        layout,
    ) -> list[str]:
        if not objects_by_id:
            return []
        entries: list[tuple[str, str]] = []
        for obj_id, obj in objects_by_id.items():
            lines = text_lines_by_id.get(obj_id, [])
            if lines:
                label = lines[0]
            else:
                label = self._scope_unnamed_reference_label(obj, layout)
            entries.append((label, obj_id))
        entries.sort(key=lambda item: (item[0].lower(), item[1]))
        lines = ["## Object Reference (Appendix)", ""]
        for label, obj_id in entries:
            lines.append(f"- {label}: {obj_id}")
        return lines

    def _week_label(self, layout, week_index: int) -> str:
        year, week_in_year = layout.week_index_to_year_week(self.model.year, week_index)
        return f"wk{year % 100:02d}{week_in_year:02d}"

    def _row_label(self, row_id: str) -> str:
        if row_id == CANVAS_ROW_ID:
            return "Canvas"
        result = self.model.find_row(row_id)
        if result is None:
            return ""
        _kind, topic, deliverable = result
        if deliverable is not None:
            return deliverable.name
        return topic.name

    @staticmethod
    def _normalize_risk_level(value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned in ("h", "high"):
            return "high"
        if cleaned in ("l", "low"):
            return "low"
        if cleaned in ("m", "med", "medium"):
            return "medium"
        return "medium"

    def _parse_risk_line(self, line: str) -> tuple[str, str, str]:
        parts = [part.strip() for part in line.split(";")]
        if not parts:
            return ("", "medium", "medium")
        risk_text = parts[0].strip()
        probability = self._normalize_risk_level(parts[1] if len(parts) > 1 else "")
        impact = self._normalize_risk_level(parts[2] if len(parts) > 2 else "")
        return (risk_text, probability, impact)

    def _select_scope_rows(self) -> set[str] | None:
        if not self.model.topics:
            QMessageBox.information(self, "Export Scope", "No sections or deliverables available.")
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Scope Rows")
        dialog.resize(420, 320)
        layout = QVBoxLayout(dialog)
        intro = QLabel("Select the sections and deliverables to include in the export.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tree = QTreeWidget(dialog)
        tree.setHeaderHidden(True)
        layout.addWidget(tree)

        items: list[tuple[str, QTreeWidgetItem]] = []
        topic_items: list[QTreeWidgetItem] = []
        for topic in self.model.topics:
            topic_item = QTreeWidgetItem(tree, [topic.name])
            topic_item.setFlags(topic_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            topic_item.setCheckState(0, Qt.CheckState.Unchecked)
            items.append((topic.id, topic_item))
            topic_items.append(topic_item)
            for deliverable in topic.deliverables:
                deliverable_item = QTreeWidgetItem(topic_item, [deliverable.name])
                deliverable_item.setFlags(
                    deliverable_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                deliverable_item.setCheckState(0, Qt.CheckState.Unchecked)
                items.append((deliverable.id, deliverable_item))

        tree.expandAll()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(button_box)

        updating = False

        def _apply_topic_state(topic_item: QTreeWidgetItem, checked: bool) -> None:
            for index in range(topic_item.childCount()):
                child = topic_item.child(index)
                child.setDisabled(checked)
                child.setCheckState(
                    0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )

        def _on_item_changed(item: QTreeWidgetItem, _column: int) -> None:
            nonlocal updating
            if updating:
                return
            if item.parent() is not None:
                return
            updating = True
            _apply_topic_state(item, item.checkState(0) == Qt.CheckState.Checked)
            updating = False

        tree.itemChanged.connect(_on_item_changed)

        updating = True
        for topic_item in topic_items:
            topic_item.setCheckState(0, Qt.CheckState.Checked)
            _apply_topic_state(topic_item, True)
        updating = False

        def _selected_row_ids() -> set[str]:
            return {
                row_id
                for row_id, item in items
                if item.checkState(0) == Qt.CheckState.Checked
            }

        def _accept() -> None:
            if not _selected_row_ids():
                QMessageBox.warning(
                    dialog,
                    "Export Scope",
                    "Select at least one section or deliverable.",
                )
                return
            dialog.accept()

        button_box.accepted.connect(_accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return _selected_row_ids()

    def _draw_export_labels(
        self, painter: QPainter, source_rect: QRectF, target_rect: QRectF
    ) -> None:
        layout = self.scene.layout
        model = self.model
        scale_x = target_rect.width() / max(1.0, source_rect.width())
        scale_y = target_rect.height() / max(1.0, source_rect.height())
        scale = min(scale_x, scale_y)
        label_width = layout.label_width * scale_x
        viewport_height = target_rect.height()
        header_top = (0.0 - source_rect.top()) * scale_y
        header_bottom = (layout.header_height - source_rect.top()) * scale_y
        gutter_top = max(0.0, header_top)
        gutter_height = max(0.0, viewport_height - gutter_top)

        painter.save()
        painter.translate(target_rect.left(), target_rect.top())

        export_theme = theme.tokens(False)
        painter.fillRect(
            QRectF(0, gutter_top, label_width, gutter_height),
            QColor(export_theme['card']),
        )
        painter.fillRect(
            QRectF(0, header_top, label_width, header_bottom - header_top),
            QColor(export_theme['soft']),
        )

        topic_fill = QColor(export_theme['soft'])
        topic_fill.setAlpha(30)
        deliverable_fill = QColor(export_theme['soft'])
        deliverable_fill.setAlpha(28)
        for row in layout.rows:
            row_top = (layout.header_height + row.y - source_rect.top()) * scale_y
            row_bottom = row_top + (row.height * scale_y)
            if row_bottom < 0 or row_top > viewport_height:
                continue
            if row.kind == 'topic' and not getattr(row, 'divider', False):
                painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), topic_fill)
                topic = model.get_topic(row.row_id)
                if topic:
                    accent = QColor(topic.color)
                    accent.setAlpha(220)
                    painter.fillRect(QRectF(0, row_top, max(3.0, 3.0 * scale), row_bottom - row_top), accent)
            elif row.kind == 'deliverable' and (layout.row_index(row.row_id) or 0) % 2 == 0:
                painter.fillRect(QRectF(0, row_top, label_width, row_bottom - row_top), deliverable_fill)

        for highlighted_row_id in self.scene.highlighted_row_ids():
            row = layout.row_map.get(highlighted_row_id)
            if row is None:
                continue
            row_top = (layout.header_height + row.y - source_rect.top()) * scale_y
            row_bottom = row_top + (row.height * scale_y)
            painter.fillRect(
                QRectF(0, row_top, label_width, row_bottom - row_top),
                QColor(export_theme['hover']),
            )

        grid_color = QColor(export_theme['grid'])
        grid_color.setAlpha(150)
        pen_grid = QPen(grid_color)
        pen_grid.setWidth(1)
        painter.setPen(pen_grid)
        painter.drawLine(int(label_width), int(gutter_top), int(label_width), int(viewport_height))
        painter.drawLine(0, int(header_bottom), int(label_width), int(header_bottom))
        for row in layout.rows:
            row_bottom = (layout.header_height + row.y + row.height - source_rect.top()) * scale_y
            if row_bottom < 0 or row_bottom > viewport_height + 1:
                continue
            boundary_color = QColor(export_theme['grid'])
            if row.kind == 'topic' and not getattr(row, 'divider', False):
                boundary_color = QColor(export_theme['text'])
                boundary_color.setAlpha(90)
            painter.setPen(QPen(boundary_color))
            painter.drawLine(0, int(row_bottom), int(label_width), int(row_bottom))
            painter.setPen(pen_grid)

        painter.setPen(QPen(QColor(export_theme['text'])))
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
            row_top = (layout.header_height + row.y - source_rect.top()) * scale_y
            row_bottom = row_top + (row.height * scale_y)
            if row_bottom < 0 or row_top > viewport_height:
                continue
            row_height = row_bottom - row_top
            label_rect = QRectF(0, row_top, label_width, row_height)
            text_x = (8 * scale) + (row.indent * indent_step)

            if row.kind == "topic":
                painter.setFont(indicator_font)
                if getattr(row, "divider", False):
                    # Divider rows export a dash rather than a collapse marker.
                    indicator = "—"
                else:
                    topic = model.get_topic(row.row_id)
                    indicator = "▸" if topic and topic.collapsed else "▾"
                indicator_pen = QColor(export_theme['muted'])
                painter.setPen(indicator_pen)
                painter.drawText(
                    label_rect.adjusted(indicator_offset, 0, 0, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    indicator,
                )
                painter.setPen(QColor(export_theme['text']))
                painter.setFont(topic_font)
                text_x += indicator_gap
            else:
                painter.setFont(font)

            text_rect = QRectF(
                text_x,
                row_top,
                max(0.0, label_width - text_x - padding),
                row_height,
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, row.name)

        painter.restore()

    def _select_export_range(self) -> QRectF | None:
        entries = self._quarter_entries()
        if not entries:
            QMessageBox.information(self, "Export", "No quarters available to export.")
            return None
        current_year, current_quarter = self._current_iso_quarter()
        end_year, end_quarter = self._add_quarters(current_year, current_quarter, 1)
        entry_index = {(entry["year"], entry["quarter"]): idx for idx, entry in enumerate(entries)}
        start_index = entry_index.get((current_year, current_quarter), 0)
        end_index = entry_index.get((end_year, end_quarter), min(start_index + 1, len(entries) - 1))

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Planning Export Range")
        layout = QFormLayout(dialog)
        start_combo = QComboBox(dialog)
        end_combo = QComboBox(dialog)
        for entry in entries:
            start_combo.addItem(entry["label"])
            end_combo.addItem(entry["label"])
        start_combo.setCurrentIndex(start_index)
        end_combo.setCurrentIndex(end_index)

        layout.addRow("From", start_combo)
        layout.addRow("To", end_combo)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(button_box)

        def _accept() -> None:
            if start_combo.currentIndex() > end_combo.currentIndex():
                QMessageBox.warning(
                    dialog,
                    "Invalid Range",
                    "The end quarter must be the same as or after the start quarter.",
                )
                return
            dialog.accept()

        button_box.accepted.connect(_accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        start_entry = entries[start_combo.currentIndex()]
        end_entry = entries[end_combo.currentIndex()]
        return self._export_rect_for_entries(start_entry, end_entry)

    def _export_rect_for_entries(self, start_entry: dict, end_entry: dict) -> QRectF:
        layout = self.scene.layout
        start_week = start_entry["start_week"] - 1
        end_week = end_entry["end_week"] + 1
        self.scene.ensure_week_range(start_week)
        self.scene.ensure_week_range(end_week)
        base_rect = self._base_export_rect_for_weeks(start_week, end_week)
        content_rect = self._export_content_rect_for_weeks(start_week, end_week)
        merged_rect = base_rect if content_rect.isNull() else base_rect.united(content_rect)
        left = base_rect.left() if layout.rows else merged_rect.left() - EXPORT_CONTENT_PADDING_X
        top = merged_rect.top() - EXPORT_CONTENT_PADDING_Y
        right = merged_rect.right() + EXPORT_CONTENT_PADDING_X
        bottom = merged_rect.bottom() + EXPORT_CONTENT_PADDING_Y
        return QRectF(
            left,
            top,
            max(1.0, right - left),
            max(1.0, bottom - top),
        )

    def _base_export_rect_for_weeks(self, start_week: int, end_week: int) -> QRectF:
        layout_obj = self.scene.layout
        start_x = layout_obj.week_left_x(start_week)
        end_x = layout_obj.week_left_x(end_week) + layout_obj.week_width
        x1 = start_x - layout_obj.label_width
        width = (end_x - start_x) + layout_obj.label_width
        height = max(1.0, layout_obj.header_height + layout_obj.total_height)
        return QRectF(x1, 0.0, width, height)

    def _export_content_rect_for_weeks(self, start_week: int, end_week: int) -> QRectF:
        layout_obj = self.scene.layout
        start_x = layout_obj.week_left_x(start_week)
        end_x = layout_obj.week_left_x(end_week) + layout_obj.week_width
        content_rect = QRectF()
        for obj_id, item in self.scene.items_by_id.items():
            if not item.isVisible():
                continue
            if self.model.objects.get(obj_id) is None:
                continue
            item_rect = item.sceneBoundingRect()
            if item_rect.isNull():
                continue
            if item_rect.right() < start_x or item_rect.left() > end_x:
                continue
            full_rect = self._visible_item_bounds(item)
            if full_rect.isNull():
                continue
            content_rect = full_rect if content_rect.isNull() else content_rect.united(full_rect)
        return content_rect

    def _visible_item_bounds(self, item) -> QRectF:
        rect = item.sceneBoundingRect()
        for child in item.childItems():
            if not child.isVisible():
                continue
            child_rect = self._visible_item_bounds(child)
            if child_rect.isNull():
                continue
            rect = child_rect if rect.isNull() else rect.united(child_rect)
        return rect

    def _quarter_entries(self, future_quarters: int = 3) -> list[dict]:
        layout = self.scene.layout
        min_year, _ = layout.week_index_to_year_week(self.model.year, self.scene.min_week)
        max_year, _ = layout.week_index_to_year_week(self.model.year, self.scene.max_week)
        current_year, current_quarter = self._current_iso_quarter()
        end_year, _ = self._add_quarters(
            current_year, current_quarter, max(0, int(future_quarters))
        )
        min_year = min(min_year, current_year)
        max_year = max(max_year, end_year)

        entries = []
        for year in range(min_year, max_year + 1):
            year_weeks = layout.weeks_in_year(year)
            base_week = layout.week_index_for_iso_year(self.model.year, year)
            for quarter in range(1, 5):
                quarter_offset = (quarter - 1) * 13
                if quarter_offset >= year_weeks:
                    break
                quarter_length = min(13, year_weeks - quarter_offset)
                start_week = base_week + quarter_offset
                end_week = start_week + quarter_length - 1
                entries.append(
                    {
                        "year": year,
                        "quarter": quarter,
                        "label": f"{year} Q{quarter}",
                        "start_week": start_week,
                        "end_week": end_week,
                    }
                )
        return entries

    def _current_iso_quarter(self) -> tuple[int, int]:
        iso = datetime.now().isocalendar()
        quarter = min(4, ((iso.week - 1) // 13) + 1)
        return iso.year, quarter

    @staticmethod
    def _add_quarters(year: int, quarter: int, offset: int) -> tuple[int, int]:
        total = (year * 4) + (quarter - 1) + offset
        new_year = total // 4
        new_quarter = (total % 4) + 1
        return new_year, new_quarter

    def _view_state(self) -> dict:
        return {
            "zoom": self.view.current_zoom,
            "scroll_x": self.view.horizontalScrollBar().value(),
            "scroll_y": self.view.verticalScrollBar().value(),
            "label_width": self.scene.layout.label_width,
            AUTO_EXPORT_VIEW_KEY: self._auto_export_state(),
        }

    def _auto_export_state(self) -> dict:
        return {
            AUTO_EXPORT_VIEW_ENABLED_KEY: self._auto_export_enabled,
            AUTO_EXPORT_VIEW_PATH_KEY: str(self._auto_export_path)
            if self._auto_export_path is not None
            else "",
            AUTO_EXPORT_VIEW_ADDITIONAL_QUARTERS_KEY: int(self._auto_export_additional_quarters),
        }

    def goto_today(self) -> None:
        iso = datetime.now().isocalendar()
        layout = self.scene.layout
        base_week = layout.week_index_for_iso_year(self.model.year, iso.year)
        week_index = base_week + (iso.week - 1)
        self.scene.ensure_week_range(week_index)
        week_center_x = layout.week_center_x(week_index)
        viewport_width = self.view.viewport().width()
        scale = max(0.01, self.view.transform().m11())
        if viewport_width <= 0:
            self.view.centerOn(week_center_x, layout.header_height)
            return
        label_width_view = layout.label_width * scale
        grid_width_view = max(0.0, viewport_width - label_width_view)
        target_view_x = label_width_view + (grid_width_view / 6.0)
        target_view_x = max(0.0, min(float(viewport_width), target_view_x))
        delta_view = (viewport_width / 2.0) - target_view_x
        delta_scene = delta_view / scale
        self.view.centerOn(week_center_x + delta_scene, layout.header_height)

    def delete_selected(self) -> None:
        self.view._delete_selected()

    def duplicate_selected(self) -> None:
        if not self.scene.edit_mode:
            return
        self.view.duplicate_selected()

    def edit_overlap_layout(self) -> None:
        if not self.scene.edit_mode:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Overlap Layout")
        layout = QFormLayout(dialog)
        value = QSpinBox(dialog)
        value.setRange(0, 30)
        value.setSuffix("%")
        value.setValue(self.model.symbol_overlap_tolerance_percent)
        layout.addRow("Allowed milestone/event overlap", value)
        explanation = QLabel("Small symbol intersections are allowed. Overlapping labels always move objects to separate levels.")
        explanation.setWordWrap(True)
        layout.addRow(explanation)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults, dialog
        )
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            lambda: value.setValue(20)
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.update_overlap_tolerance(value.value())

    def edit_classification_tag(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Classification Tag")
        layout = QFormLayout(dialog)
        text_input = QLineEdit(dialog)
        text_input.setText(self.model.classification_label())
        text_input.setPlaceholderText(DEFAULT_CLASSIFICATION)
        size_spin = QSpinBox(dialog)
        size_spin.setRange(CLASSIFICATION_SIZE_MIN, CLASSIFICATION_SIZE_MAX)
        size_spin.setValue(
            self.model.classification_size or CLASSIFICATION_SIZE_DEFAULT
        )
        size_spin.setSuffix(" pt")

        layout.addRow("Label", text_input)
        layout.addRow("Size", size_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.update_classification(text_input.text(), size_spin.value())

    def add_topic(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Section", "Section Name")
        if not ok or not name:
            return
        self.controller.add_topic(name)

    def add_divider(self) -> None:
        # Divider rows are label-only separators (Topic.kind == "divider").
        name, ok = QInputDialog.getText(self, "Add divider", "Divider Label", text="Divider")
        if not ok or not name:
            return
        self.controller.add_divider(name)

    def edit_topic(self, topic_id: str | None = None) -> None:
        if not self.model.topics:
            QMessageBox.information(self, "Edit Section(s)", "No sections available.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Section(s)")
        layout = QFormLayout(dialog)
        topic_combo = QComboBox(dialog)
        for topic in self.model.topics:
            topic_combo.addItem(topic.name, topic.id)
        name_input = QLineEdit(dialog)
        color_input = QPushButton("Pick Color", dialog)
        color_display = QLabel(dialog)
        color_display.setMinimumWidth(80)

        def _sync_fields(index: int) -> None:
            topic_id = topic_combo.itemData(index)
            topic = self.model.get_topic(topic_id)
            if topic is None:
                return
            name_input.setText(topic.name)
            color_display.setStyleSheet(f"background-color: {topic.color};")
            color_display.setProperty("color", topic.color)

        def _pick_color() -> None:
            topic_id = topic_combo.currentData()
            topic = self.model.get_topic(topic_id)
            if topic is None:
                return
            from PyQt6.QtWidgets import QColorDialog

            color = QColorDialog.getColor()
            if not color.isValid():
                return
            color_display.setStyleSheet(f"background-color: {color.name()};")
            color_display.setProperty("color", color.name().upper())

        topic_combo.currentIndexChanged.connect(_sync_fields)
        color_input.clicked.connect(_pick_color)

        layout.addRow("Section", topic_combo)
        layout.addRow("Name", name_input)
        layout.addRow("Color", color_input)
        layout.addRow("Preview", color_display)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        _sync_fields(0)
        if topic_id:
            selected_index = topic_combo.findData(topic_id)
            if selected_index >= 0:
                topic_combo.setCurrentIndex(selected_index)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            topic_id = topic_combo.currentData()
            topic = self.model.get_topic(topic_id)
            if topic is None:
                return
            new_color = color_display.property("color") or topic.color
            new_topic = type(topic)(
                id=topic.id,
                name=name_input.text() or topic.name,
                color=new_color,
                collapsed=topic.collapsed,
                deliverables=topic.deliverables,
            )
            self.controller.update_topic(new_topic)

    def edit_deliverable(self) -> None:
        entries = []
        for topic in self.model.topics:
            for deliverable in topic.deliverables:
                entries.append((topic, deliverable))
        if not entries:
            QMessageBox.information(self, "Edit Deliverable(s)", "No deliverables available.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Deliverable(s)")
        layout = QFormLayout(dialog)
        deliverable_combo = QComboBox(dialog)
        for topic, deliverable in entries:
            label = f"{topic.name} - {deliverable.name}"
            deliverable_combo.addItem(label, deliverable.id)
        name_input = QLineEdit(dialog)

        def _sync_fields(index: int) -> None:
            deliverable_id = deliverable_combo.itemData(index)
            found = self.model.find_deliverable(deliverable_id)
            if found is None:
                return
            _topic, _index, deliverable = found
            name_input.setText(deliverable.name)

        deliverable_combo.currentIndexChanged.connect(_sync_fields)

        layout.addRow("Deliverable", deliverable_combo)
        layout.addRow("Name", name_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        selected_id = self._selected_deliverable_id()
        if selected_id:
            index = deliverable_combo.findData(selected_id)
            if index != -1:
                deliverable_combo.setCurrentIndex(index)
        _sync_fields(deliverable_combo.currentIndex())

        if dialog.exec() == QDialog.DialogCode.Accepted:
            deliverable_id = deliverable_combo.currentData()
            found = self.model.find_deliverable(deliverable_id)
            if found is None:
                return
            _topic, _index, deliverable = found
            name = name_input.text().strip() or deliverable.name
            if name == deliverable.name:
                return
            new_deliverable = replace(deliverable, name=name)
            self.controller.update_deliverable(new_deliverable)

    def add_deliverable(self) -> None:
        if not self.model.topics:
            QMessageBox.information(self, "Add Deliverable", "Add a section first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Deliverable")
        layout = QFormLayout(dialog)
        topic_combo = QComboBox(dialog)
        for topic in self.model.topics:
            topic_combo.addItem(topic.name, topic.id)
        name_input = QLineEdit(dialog)
        layout.addRow("Section", topic_combo)
        layout.addRow("Deliverable", name_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_input.text().strip()
            if not name:
                return
            topic_id = topic_combo.currentData()
            self.controller.add_deliverable(topic_id, name)

    def move_deliverable_up(self) -> None:
        deliverable_ids = self._selected_deliverable_ids()
        if not deliverable_ids:
            QMessageBox.information(
                self,
                "Move Deliverable",
                "Select one or more deliverable rows by clicking their names in the left column.",
            )
            return
        self.controller.move_deliverables(deliverable_ids, -1)

    def move_deliverable_down(self) -> None:
        deliverable_ids = self._selected_deliverable_ids()
        if not deliverable_ids:
            QMessageBox.information(
                self,
                "Move Deliverable",
                "Select one or more deliverable rows by clicking their names in the left column.",
            )
            return
        self.controller.move_deliverables(deliverable_ids, 1)

    def remove_deliverable(self) -> None:
        deliverable_ids = self._selected_deliverable_ids()
        if not deliverable_ids:
            QMessageBox.information(
                self,
                "Delete Deliverable",
                "Select one or more deliverable rows by clicking their names in the left column.",
            )
            return
        affected_objects = self._objects_for_rows(set(deliverable_ids))
        detail = ""
        if affected_objects:
            detail = f"\n\nThis will remove {len(affected_objects)} related object(s) on the canvas."
        if len(deliverable_ids) == 1:
            found = self.model.find_deliverable(deliverable_ids[0])
            if found is None:
                return
            topic, _index, deliverable = found
            message = f"Delete deliverable '{deliverable.name}' from '{topic.name}'?{detail}"
        else:
            message = f"Delete {len(deliverable_ids)} selected deliverables?{detail}"
        if QMessageBox.question(
            self,
            "Confirm Delete",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self.controller.remove_deliverables(deliverable_ids)

    def remove_topic(self) -> None:
        topic_id = self._selected_topic_id()
        if not topic_id:
            QMessageBox.information(
                self,
                "Remove Section",
                "Select a section row by clicking its name in the left column.",
            )
            return
        topic = self.model.get_topic(topic_id)
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
        return self.controller.objects_for_rows(row_ids)

    def _selected_deliverable_ids(self) -> list[str]:
        selected_rows = self.scene.selected_deliverable_ids()
        if selected_rows:
            return selected_rows
        selected_id = self._selected_deliverable_id()
        if selected_id:
            return [selected_id]
        return []

    def _selected_deliverable_id(self) -> str | None:
        row_id = self._selected_row_id()
        if not row_id:
            return None
        row = self.scene.layout.row_map.get(row_id)
        if not row or row.kind != "deliverable":
            return None
        return row_id

    def _selected_topic_id(self) -> str | None:
        row_id = self._selected_row_id()
        if not row_id:
            return None
        row = self.scene.layout.row_map.get(row_id)
        if not row or row.kind != "topic":
            return None
        return row_id

    def _selected_row_id(self) -> str | None:
        if self.scene.selected_row_id:
            return self.scene.selected_row_id
        selected = self.scene.selectedItems()
        for item in selected:
            obj_id = item.data(0)
            if obj_id and obj_id in self.model.objects:
                return self.model.objects[obj_id].row_id
        return None

    def create_object(self, kind: str) -> None:
        if kind == "textbox" and not self.scene.show_textboxes:
            return
        if not self.scene.layout.rows and kind not in ("textbox", "deadline", "connector"):
            QMessageBox.information(self, "Add Object", "Add a section or deliverable first.")
            return
        if self.presentation_mode_action.isChecked():
            QMessageBox.information(self, "Presentation Mode", "Exit presentation mode to edit.")
            return
        if self.nav_mode_action.isChecked():
            self.nav_mode_action.setChecked(False)
            self._toggle_navigation_mode()
        self.view.activate_create_tool(kind)
        if kind in ("connector", "arrow"):
            message = (
                "Drag from an object edge to another to connect, "
                "or drag empty grid for a free connector."
            )
        else:
            # "task" matches the WeekFlow naming; box is the internal kind.
            noun = {"box": "task", "circle": "event"}.get(kind, kind)
            article = "an" if kind == "circle" else "a"
            message = f"Click and drag to place {article} {noun}."
        self.statusBar().showMessage(f"{message} Press Esc to cancel.")

    def closeEvent(self, event) -> None:
        self._is_closing = True
        if self._canvas_fullscreen:
            self._apply_canvas_fullscreen(False)
        if not self.maybe_save():
            self._is_closing = False
            event.ignore()
            return
        self._save_window_settings()
        event.accept()

    def _restore_window_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry:
            self._has_saved_geometry = True
            self.restoreGeometry(geometry)
        state = self.settings.value("window/state")
        if state:
            self._suppress_properties_sync = True
            try:
                self.restoreState(state)
            finally:
                self._suppress_properties_sync = False
        self._header_layout_needs_normalize = True
        self._normalize_header_toolbars()
        maximized = self.settings.value("window/maximized", False)
        if isinstance(maximized, bool):
            self._restore_maximized = maximized
        else:
            self._restore_maximized = str(maximized).lower() in ("1", "true", "yes")
        self._last_window_maximized = self._restore_maximized
        self._apply_properties_visibility()

    def _normalize_header_toolbars(self) -> None:
        """Keep the non-customizable header in one row after legacy state restore."""
        self.removeToolBarBreak(self.header_bar)
        self.removeToolBarBreak(self.planning_toolbar)

    def _restore_view_settings(self) -> None:
        zoom_value = self.settings.value("view/zoom")
        if zoom_value is None:
            zoom_value = None
        try:
            zoom = float(zoom_value)
        except (TypeError, ValueError):
            zoom = None
        if zoom is not None:
            self.view.set_zoom(zoom)

        current_week_value = self.settings.value("view/current_week_line", True)
        if isinstance(current_week_value, bool):
            current_week = current_week_value
        else:
            current_week = str(current_week_value).lower() in ("1", "true", "yes")
        self.current_week_action.setChecked(current_week)
        self.scene.show_current_week = current_week
        self.scene.update_headers()

        missing_scope_value = self.settings.value("view/show_missing_scope", False)
        if isinstance(missing_scope_value, bool):
            missing_scope = missing_scope_value
        else:
            missing_scope = str(missing_scope_value).lower() in ("1", "true", "yes")
        self.missing_scope_action.setChecked(missing_scope)
        self.scene.show_missing_scope = missing_scope
        self.scene.update_risk_badges()

        text_boxes_value = self.settings.value("view/show_text_boxes", True)
        if isinstance(text_boxes_value, bool):
            show_text_boxes = text_boxes_value
        else:
            show_text_boxes = str(text_boxes_value).lower() in ("1", "true", "yes")
        with QSignalBlocker(self.text_boxes_action):
            self.text_boxes_action.setChecked(show_text_boxes)
        self._apply_text_boxes_visibility()

        properties_value = self.settings.value("view/show_properties_pane", False)
        if isinstance(properties_value, bool):
            show_properties = properties_value
        else:
            show_properties = str(properties_value).lower() in ("1", "true", "yes")
        with QSignalBlocker(self.properties_pane_action):
            self.properties_pane_action.setChecked(show_properties)
        self._apply_properties_visibility()

        dark_value = self.settings.value("view/dark_mode", False)
        if isinstance(dark_value, bool):
            dark = dark_value
        else:
            dark = str(dark_value).lower() in ("1", "true", "yes")
        with QSignalBlocker(self.dark_mode_action):
            self.dark_mode_action.setChecked(dark)
        self._apply_dark_mode(dark)

    def _apply_auto_export_settings(self, view_state: dict | None) -> None:
        auto_export = None
        if isinstance(view_state, dict):
            auto_export = view_state.get(AUTO_EXPORT_VIEW_KEY)
        if isinstance(auto_export, dict):
            enabled_value = auto_export.get(AUTO_EXPORT_VIEW_ENABLED_KEY, False)
            if isinstance(enabled_value, bool):
                enabled = enabled_value
            else:
                enabled = str(enabled_value).lower() in ("1", "true", "yes")

            path_value = auto_export.get(AUTO_EXPORT_VIEW_PATH_KEY, "")
            if path_value:
                path = self._normalize_auto_export_path(
                    Path(str(path_value)).expanduser()
                )
            else:
                path = None

            quarters_value = auto_export.get(
                AUTO_EXPORT_VIEW_ADDITIONAL_QUARTERS_KEY,
                AUTO_EXPORT_DEFAULT_ADDITIONAL_QUARTERS,
            )
            try:
                additional_quarters = int(quarters_value)
            except (TypeError, ValueError):
                additional_quarters = AUTO_EXPORT_DEFAULT_ADDITIONAL_QUARTERS
        else:
            enabled = False
            path = None
            additional_quarters = AUTO_EXPORT_DEFAULT_ADDITIONAL_QUARTERS

        self._auto_export_path = path
        self._auto_export_additional_quarters = max(0, additional_quarters)
        self._auto_export_enabled = enabled
        with QSignalBlocker(self.auto_export_action):
            self.auto_export_action.setChecked(enabled)
        if enabled:
            self._warn_auto_export_constraints()

    def _save_window_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.setValue("window/maximized", self._last_window_maximized)
        self.settings.setValue("view/zoom", self.view.current_zoom)
        self.settings.setValue("view/current_week_line", self.scene.show_current_week)
        self.settings.setValue("view/show_missing_scope", self.scene.show_missing_scope)
        self.settings.setValue("view/show_text_boxes", self.scene.show_textboxes)
        self.settings.setValue(
            "view/show_properties_pane", self.properties_pane_action.isChecked()
        )
        self.settings.sync()

    def show_with_restore(self) -> None:
        if not self._has_saved_geometry:
            self.resize(1200, 800)
        self._restoring_window_state = self._restore_maximized
        self._maximize_attempts = 0
        self.show()
        if not self._restore_maximized:
            self._restoring_window_state = False
        QTimer.singleShot(0, self._hook_window_state)
        if self._restore_maximized:
            QTimer.singleShot(50, self._ensure_window_restore)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._header_layout_needs_normalize:
            # The main-window layout applies restored toolbar breaks when shown.
            self._normalize_header_toolbars()
            self._header_layout_needs_normalize = False

    def _is_effectively_maximized(self) -> bool:
        if not self.isMaximized():
            return False
        handle = self.windowHandle()
        if handle is None or handle.screen() is None:
            return False
        available = handle.screen().availableGeometry()
        frame = self.frameGeometry()
        margin = 8
        return (
            abs(frame.width() - available.width()) <= margin
            and abs(frame.height() - available.height()) <= margin
        )

    def _ensure_window_restore(self) -> None:
        if self._is_closing or not self._restore_maximized:
            self._restoring_window_state = False
            return
        if self._is_effectively_maximized():
            self._restoring_window_state = False
            self._last_window_maximized = True
            return
        self._maximize_attempts += 1
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self.showMaximized()
        if self._maximize_attempts < 10:
            QTimer.singleShot(200, self._ensure_window_restore)
        else:
            self._restoring_window_state = False

    def _hook_window_state(self) -> None:
        if self._window_handle_connected:
            return
        handle = self.windowHandle()
        if handle is None:
            QTimer.singleShot(0, self._hook_window_state)
            return
        handle.windowStateChanged.connect(self._on_window_state_changed)
        self._window_handle_connected = True
        self._on_window_state_changed(handle.windowState())

    def _on_window_state_changed(self, state: Qt.WindowState) -> None:
        if self._is_closing or self._restoring_window_state:
            return
        if state & Qt.WindowState.WindowMinimized:
            return
        maximized = bool(state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen))
        if maximized == self._last_window_maximized:
            return
        self._last_window_maximized = maximized
        self.settings.setValue("window/maximized", self._last_window_maximized)
        self.settings.sync()


def run() -> int:
    app = QApplication(sys.argv)
    theme.apply_item_view_focus_style(app)
    if app.cursorFlashTime() <= 0:
        app.setCursorFlashTime(1000)
    window = MainWindow()
    window.show_with_restore()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

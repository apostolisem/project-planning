"""Native planning controls sharing the main window's QAction instances."""
import math
from PyQt6.QtCore import QEvent, QPoint, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from . import icons, theme
from .widgets import ElidedLabel
from .week_format import format_year_week


def format_visible_duration(weeks: int) -> str:
    """Format a visible week count using the most useful calendar-scale unit."""
    if weeks < 13:
        value = str(weeks)
        unit = "week"
    elif weeks < 52:
        value = f"{weeks / 13:.1f}".removesuffix(".0")
        unit = "quarter"
    else:
        value = f"{weeks / 52:.1f}".removesuffix(".0")
        unit = "year"
    suffix = unit if value == "1" else f"{unit}s"
    return f"~{value} {suffix}"


class _HeaderActionButton(QToolButton):
    """Header tool button that pins its icon to a header-legible glyph.

    Qt re-applies the default action's icon on every action change (toggling
    ``checked`` included), so the header variant is kept here while the shared
    QAction keeps the darker glyph it needs inside menus.
    """

    def __init__(self, icon, parent=None) -> None:
        self._header_icon = icon
        super().__init__(parent)
        super().setIcon(icon)

    def setIcon(self, _icon) -> None:  # noqa: N802 - Qt API
        super().setIcon(self._header_icon)

    def setHeaderIcon(self, icon) -> None:  # noqa: N802 - Qt-style helper
        self._header_icon = icon
        super().setIcon(icon)


class PlanningToolBar(QToolBar):
    issues_requested = pyqtSignal()
    search_changed = pyqtSignal(str)
    search_next = pyqtSignal()

    # Widest range readout the label has to show without clipping.
    RANGE_SAMPLE = 'wk2635 – wk2706 · ~3.9 quarters'

    def __init__(self, window):
        super().__init__('Planning', window)
        self.setObjectName('planning_toolbar')
        self.setMovable(False)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        self.setIconSize(QSize(theme.HEADER_ICON_SIZE, theme.HEADER_ICON_SIZE))
        self.window = window
        # Kept as an alias for callers; the project label now lives in the identity header.
        self.project_label = window.project_label

        # --- Left: Add menu -------------------------------------------------
        # Structure mirrors the WeekFlow HTML add menu: Add task, Add milestone,
        # Add initiative, Add swimlane, Add divider. Additional drawing tools stay
        # below a separator so the primary five keep the image's order/format.
        add = QToolButton()
        add.setText('Add')
        add.setObjectName('addTrigger')
        add.setIcon(icons.add_menu_icon('#ffffff'))
        add.setToolTip('Add a plan object')
        add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add)
        menu.setToolTipsVisible(True)
        primary_actions = (
            window.add_box_action,          # Add task      (CanvasObject kind='box')
            window.add_milestone_action,    # Add milestone (kind='milestone')
            window.add_initiative_action,   # Add initiative (Initiative dataclass)
            window.add_topic_action,        # Add swimlane  (Topic / Deliverable)
            window.add_divider_action,      # Add divider   (Topic.kind='divider')
        )
        for action in primary_actions:
            menu.addAction(action)
        menu.addSeparator()
        for key in (
            'insert_deadline',
            'insert_circle',
            'insert_connector',
            'insert_textbox',
        ):
            action = window._shortcut_actions.get(key)
            if action is not None:
                menu.addAction(action)
        menu.addAction(window.add_deliverable_action)
        add.setMenu(menu)
        self.addWidget(add)
        self.addWidget(self._group_gap())

        # --- Center: date / range navigation --------------------------------
        previous = self.addAction('‹', lambda: self.page(-1))
        self._decorate_pager(previous, 'Previous weeks',
                             'Scroll back one screen of weeks')
        self.addAction(window.today_action)
        self.range = ElidedLabel(
            elide_mode=Qt.TextElideMode.ElideRight, reserve_full_width=True
        )
        self.range.setObjectName('rangeLabel')
        self.range.setMinimumWidth(theme.HEADER_RANGE_MIN_WIDTH)
        self.range.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.addWidget(self.range)
        following = self.addAction('›', lambda: self.page(1))
        self._decorate_pager(following, 'Next weeks',
                             'Scroll forward one screen of weeks')
        self._sync_range_width()
        self.addWidget(self._group_gap())

        # --- Right: zoom, tools, history ------------------------------------
        self.addWidget(self._proxy_action_button(window._shortcut_actions['zoom_out'], '−', 'Zoom out'))
        self.addWidget(self._proxy_action_button(window._shortcut_actions['zoom_in'], '+', 'Zoom in'))
        self.addWidget(self._proxy_action_button(window.fit_action, 'Fit', 'Zoom to fit', width=44))
        self.addSeparator()

        self.mode = QComboBox()
        self.mode.addItems(['Edit', 'Navigation', 'Presentation', 'Canvas Full Screen'])
        self.mode.setObjectName('modeSelector')
        self.mode.setAccessibleName('Plan mode')
        self.mode.setFixedWidth(142)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.addWidget(self.mode)

        self.addAction(window.undo_action)
        self.addAction(window.redo_action)

        self.addWidget(self._stretch())

        utilities = QWidget()
        utilities.setObjectName('headerUtilities')
        # Hug the contents so the trailing stretch keeps the group flush right.
        utilities.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        utilities_layout = QHBoxLayout(utilities)
        utilities_layout.setContentsMargins(0, 0, 0, 0)
        utilities_layout.setSpacing(theme.HEADER_SPACING)
        utilities_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.issues_button = QToolButton()
        self.issues_button.setObjectName('issuesButton')
        self.issues_button.setText('!')
        self.issues_button.setToolTip('Planning issues')
        self.issues_button.setAccessibleName('Planning issues')
        self.issues_button.clicked.connect(self.issues_requested.emit)
        utilities_layout.addWidget(self.issues_button)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName('headerSearch')
        self.search_edit.setPlaceholderText('Search…')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(100)
        self.search_edit.setMaximumWidth(115)
        self.search_edit.setAccessibleName('Search plan')
        self.search_edit.textChanged.connect(self.search_changed.emit)
        self.search_edit.returnPressed.connect(self.search_next.emit)
        utilities_layout.addWidget(self.search_edit)

        utilities_layout.addWidget(self._separator())
        self.details_button = _HeaderActionButton(
            icons.details_panel_icon(theme.tokens(window._dark_mode)['text'])
        )
        self.details_button.setDefaultAction(window.properties_pane_action)
        self.details_button.setObjectName('detailsToggle')
        self.details_button.setAccessibleName('Show or hide Details')
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.details_button.setFixedWidth(theme.HEADER_CONTROL_HEIGHT + 2)
        utilities_layout.addWidget(self.details_button)
        self.addWidget(utilities)

        window.view.viewport_changed.connect(self.refresh)
        window.nav_mode_action.toggled.connect(self.refresh)
        window.presentation_mode_action.toggled.connect(self.refresh)

    def set_project_name(self, name: str) -> None:
        """Display the active project name, separate from app identity."""
        label = name or 'Untitled'
        self.project_label.setText(label)
        # Preserve full visibility for short names while allowing the Saved
        # pill to follow immediately after the title instead of a fixed gutter.
        natural_width = self.project_label.fontMetrics().horizontalAdvance(label) + 16
        self.project_label.setMinimumWidth(
            min(self.project_label.maximumWidth(), max(0, natural_width))
        )

    def refresh_theme_icons(self, dark: bool) -> None:
        self.details_button.setHeaderIcon(
            icons.details_panel_icon(theme.tokens(dark)['text'])
        )

    @staticmethod
    def _stretch() -> QWidget:
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return spacer

    @staticmethod
    def _group_gap() -> QWidget:
        """Elastic gap between control groups.

        It grows up to ``HEADER_GROUP_GAP_MAX`` so groups read as separate
        clusters on wide windows, and shrinks to ``HEADER_GROUP_GAP_MIN`` on
        narrow ones so the row stays complete instead of overflowing.
        """
        gap = QWidget()
        gap.setObjectName('headerGroupGap')
        gap.setMinimumWidth(theme.HEADER_GROUP_GAP_MIN)
        gap.setMaximumWidth(theme.HEADER_GROUP_GAP_MAX)
        gap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return gap

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName('headerGroupSeparator')
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        return separator

    def _decorate_pager(self, action, name: str, tooltip: str) -> None:
        """Name the chevron pagers so they are styled and announced properly."""
        action.setToolTip(tooltip)
        button = self.widgetForAction(action)
        if button is not None:
            button.setObjectName('pagerButton')
            button.setAccessibleName(name)

    def _proxy_action_button(self, action, text: str, name: str, width: int | None = None) -> QToolButton:
        """Compact ribbon button that triggers an existing QAction."""
        button = QToolButton()
        button.setObjectName('zoomButton')
        button.setText(text)
        button.setToolTip(action.toolTip() or name)
        button.setAccessibleName(name)
        button.clicked.connect(action.trigger)
        button.setEnabled(action.isEnabled())
        action.changed.connect(lambda checked=False, b=button, a=action: b.setEnabled(a.isEnabled()))
        if width is not None:
            button.setFixedWidth(width)
        return button

    def _sync_range_width(self) -> None:
        """Cap the range readout at its widest text so it never over-reserves.

        The label reserves room for its full text and elides only when the
        header runs out of space, so the readout stays legible at any width.
        """
        width = self.range.fontMetrics().horizontalAdvance(self.RANGE_SAMPLE) + 10
        self.range.setMaximumWidth(max(width, theme.HEADER_RANGE_MIN_WIDTH))
        self.range.updateGeometry()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            # The stylesheet resolves header fonts after construction.
            self._sync_range_width()

    def set_issue_count(self, active: int, total: int) -> None:
        state = 'none'
        if total <= 0:
            self.issues_button.setText('!')
            self.issues_button.setToolTip('No planning issues')
        else:
            state = 'active' if active else 'reviewed'
            label = '!' if active <= 0 else str(active)
            self.issues_button.setText(label)
            self.issues_button.setToolTip(
                f'{active} active planning issue(s), {total} total' if active
                else f'{total} issue(s) reviewed'
            )
        self.issues_button.setProperty('issueState', state)
        self.issues_button.style().unpolish(self.issues_button)
        self.issues_button.style().polish(self.issues_button)
        self.issues_button.update()

    def change_mode(self, index):
        w = self.window
        w.set_interaction_mode(index)
        self.refresh()

    def bounds(self):
        view = self.window.view
        layout = view.scene().layout
        left = view.mapToScene(QPoint(int(view._label_width_pixels()), 0)).x()
        right = view.mapToScene(QPoint(view.viewport().width(), 0)).x()
        first = layout.week_from_x(left, False)
        last = layout.week_from_x(right, False)
        fully = max(1, math.floor((right - left) / layout.week_width) - 1)
        # Count only complete grid cells, not the clipped cells at either edge.
        fully = max(1, sum(layout.week_left_x(i) >= left and
                           layout.week_left_x(i + 1) <= right
                           for i in range(first, last + 1)))
        return first, last, fully

    def page(self, direction):
        view = self.window.view
        count = self.bounds()[2]
        bar = view.horizontalScrollBar()
        bar.setValue(bar.value() + round(direction * count * view.scene().layout.week_width * view.current_zoom))

    def refresh(self, *_):
        w = self.window
        if not hasattr(w.view.scene(), 'layout'):
            return
        first, last, count = self.bounds()
        def label(index):
            year, week = w.scene.layout.week_index_to_year_week(w.model.year, index)
            return format_year_week(year, week)
        duration = format_visible_duration(count)
        spoken_duration = duration.removeprefix('~')
        self.range.setText(f'{label(first)} – {label(last)} · {duration}')
        self.range.setToolTip(
            f'Approximately {spoken_duration} shown · {w.view.current_zoom:.0%}'
        )
        self.range.setAccessibleName(
            f'{self.range.text()}, approximately {spoken_duration} shown'
        )
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(w.interaction_mode_index())

"""Shared desktop and canvas presentation tokens (no document geometry).

Light/dark design tokens mirror the WeekFlow HTML tool's CSS custom properties.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QAbstractItemView, QProxyStyle, QStyle

# Seed palette (kept for backwards compatibility with existing imports).
BLUE = '#004c97'
CYAN = '#00b1eb'
TEXT = '#172033'
BORDER = '#dce5ef'

LIGHT = {
    'bg': '#f1f5f9',
    'card': '#ffffff',
    'text': '#172033',
    'muted': '#64748b',
    'border': '#dce5ef',
    'soft': '#f8fafc',
    'hover': '#eef5fb',
    'blue': '#004c97',
    'blue_hover': '#003b77',
    'cyan': '#00b1eb',
    'focus': '#00b1eb',
    'selected': '#00b1eb',
    'danger': '#dc2626',
    'danger_bg': '#fff1f3',
    'success': '#059669',
    'success_bg': '#daf5ec',
    'warning': '#d97706',
    'warning_bg': '#fff7ed',
    'grid': '#e2e8f0',
    'header': '#004c97',
    'header_text': '#ffffff',
    'disabled': '#94a3b8',
    'scrollbar': '#cbd5e1',
}

DARK = {
    'bg': '#0f172a',
    'card': '#1e293b',
    'text': '#f8fafc',
    'muted': '#94a3b8',
    'border': '#334155',
    'soft': '#152033',
    'hover': '#29384c',
    'blue': '#0067a8',
    'blue_hover': '#0080c7',
    'cyan': '#38bdf8',
    'focus': '#38bdf8',
    'selected': '#38bdf8',
    'danger': '#f87171',
    'danger_bg': '#3d2028',
    'success': '#34d399',
    'success_bg': '#0f2e26',
    'warning': '#fbbf24',
    'warning_bg': '#3b2718',
    'grid': '#22304a',
    'header': '#004c97',
    'header_text': '#ffffff',
    'disabled': '#475569',
    'scrollbar': '#475569',
}

# Layout tokens (shared across themes).
RADIUS_TAG = 4
RADIUS_CONTROL = 7
RADIUS_CARD = 9
RADIUS_PANEL = 12
RADIUS = RADIUS_CONTROL
RADIUS_SM = RADIUS_TAG
SPACING = 6
ROW_HEIGHT = 32

# --- Application header ------------------------------------------------------
# The header row is a compact ribbon built from two non-movable tool bars that
# share one neutral surface. Every metric below is
# derived from one control height so both bars stay the same height and every
# control stays vertically centred with room to breathe.
#
# Qt derives a tool bar's item margins from the horizontal stylesheet padding,
# so HEADER_PADDING is used on both axes: that is what keeps the controls
# optically centred inside the band.
HEADER_CONTROL_HEIGHT = 30       # QSS content height; 32px painted with borders
HEADER_CONTROL_PADDING_H = 6     # inner label padding of header buttons
HEADER_ADD_ARROW_INSET = 7       # clear space between menu arrow and button edge
HEADER_ADD_RIGHT_PADDING = 18    # reserve a distinct gutter for that arrow
HEADER_FONT_SIZE = 12
HEADER_ICON_SIZE = 18
HEADER_PADDING = 10              # breathing room around the control row
HEADER_SPACING = 6               # gap between neighbouring controls of a group
HEADER_GROUP_GAP_MIN = 4         # elastic gap between control groups
HEADER_GROUP_GAP_MAX = 10
HEADER_RANGE_MIN_WIDTH = 140     # week-range readout elides below this width
HEADER_PROJECT_MIN_WIDTH = 140   # common project names remain fully readable
HEADER_PROJECT_MAX_WIDTH = 240   # long names elide without crowding commands
HEADER_CONTENT_HEIGHT = HEADER_CONTROL_HEIGHT + 4   # room for 2px focus rings
HEADER_HEIGHT = HEADER_CONTENT_HEIGHT + 2 * HEADER_PADDING + 1  # + bottom border

# Header-specific surfaces.
HEADER_GLYPH = '#ffffff'
HEADER_HOVER = 'rgba(255, 255, 255, 0.16)'
HEADER_ACTIVE = 'rgba(255, 255, 255, 0.26)'
HEADER_LINE = 'rgba(255, 255, 255, 0.38)'
HEADER_MUTED_TEXT = 'rgba(255, 255, 255, 0.82)'
HEADER_DISABLED_TEXT = 'rgba(255, 255, 255, 0.45)'
HEADER_SURFACE = '#ffffff'          # inputs and the primary Add button
HEADER_SURFACE_HOVER = LIGHT['hover']
HEADER_SURFACE_PRESSED = LIGHT['bg']
HEADER_SURFACE_TEXT = LIGHT['text']
HEADER_SURFACE_MUTED = LIGHT['muted']
HEADER_ACCENT_TEXT = LIGHT['blue']  # label of the primary Add button
RIBBON_BUTTON_BG = '#eef5fb'
RIBBON_BUTTON_HOVER = '#e2edf8'
RIBBON_BUTTON_PRESSED = '#d8e7f6'


def tokens(dark: bool = False) -> dict:
    return dict(DARK if dark else LIGHT)


def qcolor(token: str, dark: bool = False) -> QColor:
    return QColor(tokens(dark)[token])


class ItemViewFocusStyle(QProxyStyle):
    """Suppress Qt's dotted/dashed item-view focus rectangle.

    Qt draws a secondary ``PE_FrameFocusRect`` around the current row/cell when a
    ``QAbstractItemView`` has focus, on top of the solid selection highlight.
    Skipping that primitive removes only the dashed box; selection state, the
    highlight, and keyboard navigation are untouched.
    """

    @staticmethod
    def _is_item_view(widget) -> bool:
        if isinstance(widget, QAbstractItemView):
            return True
        parent = widget.parent() if widget is not None else None
        return isinstance(parent, QAbstractItemView)

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if (
            element == QStyle.PrimitiveElement.PE_FrameFocusRect
            and self._is_item_view(widget)
        ):
            return
        super().drawPrimitive(element, option, painter, widget)


def apply_item_view_focus_style(app) -> None:
    """Install :class:`ItemViewFocusStyle` once, wrapping the current base style."""
    if getattr(app, "_item_view_focus_style", None) is not None:
        return
    style = ItemViewFocusStyle(app.style())
    app.setStyle(style)
    app._item_view_focus_style = style


def relative_luminance(color) -> float:
    """Return WCAG 2 relative luminance for an sRGB color."""
    c = QColor(color)
    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in (c.redF(), c.greenF(), c.blueF())
    ]
    return sum(value * weight for value, weight in zip(channels, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(first, second) -> float:
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def adaptive_text_color(backgrounds) -> QColor:
    """Choose the ink with the best worst-case contrast across backgrounds."""
    colors = [QColor(color) for color in backgrounds]
    if not colors:
        colors = [QColor('#ffffff')]
    candidates = (QColor('#172033'), QColor('#ffffff'))
    return QColor(max(candidates, key=lambda ink: min(contrast_ratio(ink, bg) for bg in colors)))


def composite_color(foreground, background, opacity: float | None = None) -> QColor:
    """Composite a foreground color over an opaque background."""
    fg = QColor(foreground)
    bg = QColor(background)
    alpha = fg.alphaF() if opacity is None else max(0.0, min(1.0, float(opacity)))
    return QColor.fromRgbF(
        fg.redF() * alpha + bg.redF() * (1.0 - alpha),
        fg.greenF() * alpha + bg.greenF() * (1.0 - alpha),
        fg.blueF() * alpha + bg.blueF() * (1.0 - alpha),
        1.0,
    )


def composite_color(foreground, background, opacity: float | None = None) -> QColor:
    """Composite a foreground color over an opaque background."""
    fg = QColor(foreground)
    bg = QColor(background)
    alpha = fg.alphaF() if opacity is None else max(0.0, min(1.0, float(opacity)))
    return QColor.fromRgbF(
        fg.redF() * alpha + bg.redF() * (1.0 - alpha),
        fg.greenF() * alpha + bg.greenF() * (1.0 - alpha),
        fg.blueF() * alpha + bg.blueF() * (1.0 - alpha),
        1.0,
    )


def contrast_text(color):
    """Backward-compatible single-background adaptive text helper."""
    return adaptive_text_color([color])


def build_stylesheet(dark: bool = False) -> str:
    """Generate the application QSS from design tokens."""
    t = tokens(dark)
    # Status chips carry their own background, so pick the readable ink for it.
    unsaved_ink = contrast_text(t['warning']).name()
    return f'''
QMainWindow, QDialog {{ background: {t['bg']}; color: {t['text']}; }}
QWidget {{ color: {t['text']}; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }}
QMenuBar {{ background: {t['card']}; color: {t['text']}; border-bottom: 1px solid {t['border']}; }}
QMenuBar::item {{ padding: 5px 9px; background: transparent; }}
QMenuBar::item:selected {{ background: {t['hover']}; }}
QMenu {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: {RADIUS_SM}px; }}
QMenu::item:selected {{ background: {t['hover']}; color: {t['blue']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}

QToolBar {{ background: {t['card']}; border: 0; border-bottom: 1px solid {t['border']};
            spacing: {SPACING}px; padding: 4px 8px; }}
QToolBar::separator {{ width: 1px; background: {t['border']}; margin: 4px 6px; }}
QToolButton {{ min-height: 22px; padding: 4px 7px; border: 1px solid transparent; border-radius: {RADIUS_CONTROL}px;
               background: transparent; color: {t['text']}; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {t['hover']}; border-color: {t['cyan']}; }}
QToolButton:disabled {{ color: {t['disabled']}; }}

QPushButton {{ min-height: 22px; padding: 4px 10px; border: 1px solid {t['border']}; border-radius: {RADIUS_CONTROL}px;
               background: {t['soft']}; color: {t['text']}; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['card']}; }}
QPushButton:disabled {{ color: {t['disabled']}; }}
QPushButton:default {{ border-color: {t['cyan']}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {{
    background: {t['soft']}; color: {t['text']}; border: 1px solid {t['border']};
    min-height: 22px; border-radius: {RADIUS_CONTROL}px; padding: 4px 7px; selection-background-color: {t['blue']};
    selection-color: #ffffff; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus {{ border-color: {t['focus']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled {{ color: {t['disabled']}; }}
QComboBox QAbstractItemView {{ background: {t['card']}; color: {t['text']};
    border: 1px solid {t['border']}; selection-background-color: {t['hover']};
    selection-color: {t['blue']}; }}

QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: {RADIUS_CONTROL}px;
    background: {t['card']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 6px 12px;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['blue']}; border-bottom-color: {t['cyan']}; }}
QDockWidget#detailsDock QTabBar::tab {{ padding: 6px 7px; font-size: 11px; }}

QDockWidget {{ color: {t['text']}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{ background: {t['soft']}; border-bottom: 1px solid {t['border']};
    padding: 5px 8px; text-align: left; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['scrollbar']}; border-radius: 6px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t['focus']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t['scrollbar']}; border-radius: 6px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['focus']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTableView, QTreeWidget, QListWidget {{ background: {t['card']}; color: {t['text']};
    border: 1px solid {t['border']}; gridline-color: {t['border']};
    selection-background-color: {t['hover']}; selection-color: {t['text']};
    alternate-background-color: {t['soft']}; }}
QHeaderView::section {{ background: {t['soft']}; color: {t['muted']}; padding: 5px 8px;
    border: 0; border-bottom: 1px solid {t['border']}; font-weight: 700; }}

QStatusBar {{ background: {t['card']}; color: {t['muted']}; border-top: 1px solid {t['border']}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {t['text']}; color: {t['card']}; border: 0; padding: 4px 6px; }}

/* --- Task-oriented in-app help ------------------------------------------ */
QDialog#howToDialog QLabel#howToSubtitle,
QDialog#howToDialog QLabel#howToPageIntro {{ color: {t['muted']}; }}
QDialog#howToDialog QListWidget#howToNavigation {{
    background: {t['soft']}; border: 1px solid {t['border']}; border-right: 0;
    padding: 6px; outline: 0; }}
QDialog#howToDialog QListWidget#howToNavigation::item {{
    min-height: 24px; padding: 7px 9px; border-left: 3px solid transparent; }}
QDialog#howToDialog QListWidget#howToNavigation::item:hover {{
    background: {t['hover']}; }}
QDialog#howToDialog QListWidget#howToNavigation::item:selected {{
    background: {t['hover']}; color: {t['blue']}; border-left-color: {t['cyan']}; }}
QDialog#howToDialog QStackedWidget#howToPages,
QDialog#howToDialog QWidget#howToPage {{
    background: {t['card']}; border: 1px solid {t['border']}; }}
QDialog#howToDialog QWidget#howToPage {{ border: 0; }}
QDialog#howToDialog QLabel#howToSectionBody {{ color: {t['text']}; }}

/* --- Application header: one continuous neutral command ribbon ----------- */
QToolBar#plan_header {{
    min-height: {HEADER_CONTENT_HEIGHT}px; max-height: {HEADER_CONTENT_HEIGHT}px;
    padding: {HEADER_PADDING}px; spacing: {HEADER_SPACING}px;
    background: {t['card']}; border: 0; border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']}; }}
QToolBar#planning_toolbar {{
    min-height: {HEADER_CONTENT_HEIGHT}px; max-height: {HEADER_CONTENT_HEIGHT}px;
    padding: {HEADER_PADDING}px; spacing: {HEADER_SPACING}px;
    background: {t['card']}; border: 0; border-bottom: 1px solid {t['border']}; }}
QToolBar#plan_header QLabel {{ color: {t['text']}; }}
QToolBar#planning_toolbar QLabel {{ color: {t['text']}; }}
QWidget#planHeader {{ background: transparent; }}
QWidget#planHeader QLabel#planName {{ font-size: 20px; font-weight: 750; }}
QLabel#savePill {{ color: {t['muted']}; background: {t['soft']};
    border-radius: {RADIUS_TAG}px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#savePill[state="saved"] {{ background: {t['success_bg']}; color: {t['success']}; }}
QLabel#savePill[state="unsaved"] {{ background: {t['warning_bg']}; color: {t['warning']}; }}
QLabel#savePill[state="error"] {{ background: {t['danger_bg']}; color: {t['danger']}; }}

QToolBar#planning_toolbar::separator, QFrame#headerGroupSeparator {{
    width: 1px; background: {t['border']}; }}
QToolBar#planning_toolbar::separator {{ margin: 2px {HEADER_SPACING}px; }}
QFrame#headerGroupSeparator {{ min-width: 1px; max-width: 1px;
    min-height: {HEADER_CONTROL_HEIGHT - 8}px; max-height: {HEADER_CONTROL_HEIGHT - 8}px;
    border: 0; margin: 0 {HEADER_SPACING}px; color: {t['border']}; }}

QToolBar#planning_toolbar QToolButton {{
    min-height: {HEADER_CONTROL_HEIGHT}px; max-height: {HEADER_CONTROL_HEIGHT}px;
    padding: 0 {HEADER_CONTROL_PADDING_H}px; border: 1px solid {t['border']};
    border-radius: {RADIUS_TAG}px; background: {t['soft']};
    color: {t['text']}; font-size: {HEADER_FONT_SIZE}px; }}
QToolBar#planning_toolbar QToolButton:hover {{ background: {t['hover']}; }}
QToolBar#planning_toolbar QToolButton:pressed {{ background: {t['card']}; }}
QToolBar#planning_toolbar QToolButton:checked {{ background: {t['hover']};
    border-color: {t['cyan']}; }}
QToolBar#planning_toolbar QToolButton:disabled {{ color: {t['disabled']}; }}
QToolBar#planning_toolbar QToolButton#pagerButton {{ font-size: {HEADER_FONT_SIZE + 3}px;
    min-width: {HEADER_CONTROL_HEIGHT - 12}px; }}
QToolBar#planning_toolbar QToolButton#addTrigger {{ color: #ffffff;
    background: {t['blue']}; border-color: {t['blue']}; font-weight: 700;
    padding-left: {HEADER_CONTROL_PADDING_H + 3}px;
    padding-right: {HEADER_ADD_RIGHT_PADDING}px; }}
QToolBar#planning_toolbar QToolButton#addTrigger:hover {{ background: {t['blue_hover']};
    border-color: {t['blue_hover']}; }}
QToolBar#planning_toolbar QToolButton#addTrigger:pressed {{ background: {t['blue']};
    border-color: {t['blue']}; }}
QToolBar#planning_toolbar QToolButton#addTrigger::menu-indicator {{
    subcontrol-origin: padding; subcontrol-position: center right;
    right: {HEADER_ADD_ARROW_INSET}px; width: 8px; }}
QToolBar#planning_toolbar QLabel#rangeLabel {{ color: {t['muted']};
    font-size: {HEADER_FONT_SIZE}px; }}
QToolBar#planning_toolbar QLabel#projectFileLabel {{ color: {t['text']};
    background: {t['soft']}; border: 1px solid {t['border']};
    border-radius: {RADIUS_TAG}px; padding: 0 8px; font-weight: 700;
    font-size: {HEADER_FONT_SIZE}px; }}
QToolBar#planning_toolbar QComboBox#modeSelector,
QToolBar#planning_toolbar QLineEdit#headerSearch {{
    min-height: {HEADER_CONTROL_HEIGHT}px; max-height: {HEADER_CONTROL_HEIGHT}px;
    background: {t['card']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: {RADIUS_TAG}px; padding: 0 7px;
    selection-background-color: {LIGHT['blue']}; selection-color: #ffffff; }}
QComboBox#modeSelector QAbstractItemView {{ background: {t['card']};
    color: {t['text']}; border: 1px solid {t['border']};
    selection-background-color: {t['hover']}; selection-color: {t['blue']}; }}
QToolBar#planning_toolbar QToolButton:focus, QToolBar#planning_toolbar QComboBox:focus,
QToolBar#planning_toolbar QLineEdit:focus {{ border: 2px solid {t['cyan']}; }}
QToolBar#planning_toolbar QToolButton#issuesButton {{ min-width: {HEADER_CONTROL_HEIGHT - 6}px;
    max-width: {HEADER_CONTROL_HEIGHT + 8}px; padding: 0 4px; font-weight: 900;
    border: 1px solid {t['border']}; }}
QToolBar#planning_toolbar QToolButton#issuesButton[issueState="active"] {{
    color: {unsaved_ink}; background: {t['warning']}; border-color: {t['warning']}; }}
QToolBar#planning_toolbar QToolButton#issuesButton[issueState="reviewed"] {{
    color: {t['text']}; background: {t['soft']};
    border-color: {t['border']}; }}

QWidget#workspace {{ background: {t['bg']}; }}
QWidget#timelineCard {{ background: {t['card']}; border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px; }}

QDockWidget#detailsDock {{ background: {t['card']}; border-left: 1px solid {t['border']}; }}
QScrollArea#detailsScroll {{ background: {t['card']}; border: 0; }}
QWidget#detailsDockHeader {{ background: {t['soft']}; border-bottom: 1px solid {t['border']}; }}
QLabel#detailsDockTitle {{ font-size: 16px; font-weight: 700; }}
QToolButton#detailsDockCollapse {{ color: {t['muted']}; font-size: 18px; padding: 1px 5px; }}
QWidget#contextEditor {{ background: {t['card']}; }}
QLabel#inspectorContext {{ color: {t['muted']}; font-size: 11px; font-weight: 700; }}
QLabel#inspectorEmptyState {{ color: {t['muted']}; font-size: 13px; padding: 18px 8px; }}
QWidget#inspectorSection {{ background: {t['soft']}; border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px; }}
QLabel#sectionCaption {{ color: {t['muted']}; font-size: 10px; font-weight: 700; }}
QLabel#inspectorFeedback {{ color: {t['danger']}; font-size: 11px; }}

QWidget#subjectLegend {{ background: {t['card']}; border-top: 1px solid {t['border']}; }}
QLabel#legendTitle {{ color: {t['muted']}; font-size: 10px; font-weight: 700; }}
QLabel#legendEmpty {{ color: {t['muted']}; font-size: 11px; }}
QPushButton#legendAdd {{ min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; padding: 0; }}

QLabel#dialogHint {{ color: {t['muted']}; font-size: 11px; }}

QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t['focus']}; }}
'''


def apply_palette(app, dark: bool = False) -> None:
    """Apply a QPalette so native widgets/dialogs follow the theme."""
    t = tokens(dark)
    palette = QPalette()
    from PyQt6.QtGui import QPalette as _QP
    palette.setColor(_QP.ColorRole.Window, QColor(t['bg']))
    palette.setColor(_QP.ColorRole.WindowText, QColor(t['text']))
    palette.setColor(_QP.ColorRole.Base, QColor(t['card']))
    palette.setColor(_QP.ColorRole.AlternateBase, QColor(t['soft']))
    palette.setColor(_QP.ColorRole.Text, QColor(t['text']))
    palette.setColor(_QP.ColorRole.Button, QColor(t['soft']))
    palette.setColor(_QP.ColorRole.ButtonText, QColor(t['text']))
    palette.setColor(_QP.ColorRole.Highlight, QColor(t['blue']))
    palette.setColor(_QP.ColorRole.HighlightedText, QColor('#ffffff'))
    palette.setColor(_QP.ColorRole.ToolTipBase, QColor(t['card']))
    palette.setColor(_QP.ColorRole.ToolTipText, QColor(t['text']))
    palette.setColor(_QP.ColorRole.PlaceholderText, QColor(t['muted']))
    app.setPalette(palette)


STYLE = build_stylesheet(False)

"""Hand-drawn vector icons for the "Add" menu (no image assets).

The glyphs mirror the WeekFlow HTML add menu: a task bar, milestone diamond,
initiative ring, swimlane grid and divider dash.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

_SIZE = 24
_GLYPH = "#1f5f9e"
_MUTED = "#4b5563"


def _canvas():
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def task_icon() -> QIcon:
    """Filled parallelogram - matches the HTML "Add task" glyph."""
    pixmap, painter = _canvas()
    skew = 4.0
    top, bottom = 6.0, 18.0
    left, right = 5.0 + skew, 19.0 + skew
    polygon = QPolygonF([
        QPointF(left, top), QPointF(right, top),
        QPointF(right - skew, bottom), QPointF(left - skew, bottom),
    ])
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_GLYPH))
    painter.drawPolygon(polygon)
    painter.end()
    return QIcon(pixmap)


def milestone_icon() -> QIcon:
    """Outlined diamond - matches the HTML "Add milestone" glyph."""
    pixmap, painter = _canvas()
    polygon = QPolygonF([
        QPointF(12, 4), QPointF(20, 12), QPointF(12, 20), QPointF(4, 12),
    ])
    pen = QPen(QColor(_GLYPH))
    pen.setWidthF(2.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(polygon)
    painter.end()
    return QIcon(pixmap)


def initiative_icon() -> QIcon:
    """Ring - matches the HTML "Add initiative" glyph."""
    pixmap, painter = _canvas()
    path = QPainterPath()
    path.addEllipse(QRectF(4, 4, 16, 16))
    path.addEllipse(QRectF(9, 9, 6, 6))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_GLYPH))
    painter.drawPath(path.simplified())
    painter.end()
    return QIcon(pixmap)


def swimlane_icon() -> QIcon:
    """Grid - matches the HTML "Add swimlane" glyph."""
    pixmap, painter = _canvas()
    pen = QPen(QColor(_GLYPH))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawRoundedRect(QRectF(4, 6, 16, 12), 2, 2)
    painter.drawLine(QPointF(9, 6), QPointF(9, 18))
    painter.drawLine(QPointF(4, 10), QPointF(20, 10))
    painter.drawLine(QPointF(4, 14), QPointF(20, 14))
    painter.end()
    return QIcon(pixmap)


def divider_icon() -> QIcon:
    """Short dash - matches the HTML "Add divider" glyph."""
    pixmap, painter = _canvas()
    pen = QPen(QColor(_MUTED))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(6, 12), QPointF(18, 12))
    painter.end()
    return QIcon(pixmap)


def add_menu_icon(color: str | None = None) -> QIcon:
    """Plus glyph for the "Add" toolbar trigger."""
    pixmap, painter = _canvas()
    pen = QPen(QColor(color or _GLYPH))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(12, 5), QPointF(12, 19))
    painter.drawLine(QPointF(5, 12), QPointF(19, 12))
    painter.end()
    return QIcon(pixmap)


def details_panel_icon(color: str | None = None) -> QIcon:
    """Window outline with a right sidebar for the Details toggle.

    ``color`` overrides the default blue glyph so the same shape stays legible
    on the blue application header as well as on light menu backgrounds.
    """
    pixmap, painter = _canvas()
    glyph = QColor(color or _GLYPH)
    pen = QPen(glyph)
    pen.setWidthF(1.9)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(3.5, 5.0, 17.0, 14.0), 2.0, 2.0)
    painter.drawLine(QPointF(14.5, 5.5), QPointF(14.5, 18.5))
    painter.fillRect(QRectF(16.4, 8.0, 2.2, 1.6), glyph)
    painter.fillRect(QRectF(16.4, 11.2, 2.2, 1.6), glyph)
    painter.end()
    return QIcon(pixmap)

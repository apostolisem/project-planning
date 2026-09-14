"""Small shared widgets for the application header."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLabel


class ClickableStatusLabel(QLabel):
    """A label that adds activation without changing label styling."""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._clickable = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def setClickable(self, clickable: bool) -> None:  # noqa: N802 - Qt API
        self._clickable = bool(clickable)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor
        )
        self.setAccessibleDescription(
            "Click to save unsaved changes." if self._clickable else "Save status."
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        event.ignore()


class ElidedLabel(QLabel):
    """Width-bounded label that elides its text and keeps the full text accessible.

    ``reserve_full_width`` controls how much room the label asks its layout for:

    * ``False`` (default) keeps Qt's behaviour of hinting the currently visible
      text, so the label stays as compact as the surrounding controls allow.
    * ``True`` hints the untruncated text - bounded by ``maximumWidth()`` - and
      reports no minimum of its own, so the label shows its text in full when
      the header is roomy and elides gracefully when it is tight.
    """

    # Hint a little more than the text measures so rounding never forces an
    # ellipsis on a label that was given exactly its preferred width.
    _HINT_PADDING = 4
    _ELIDE_PADDING = 2

    def __init__(
        self,
        text: str = "",
        parent=None,
        elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        reserve_full_width: bool = False,
    ) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = elide_mode
        self._reserve_full_width = reserve_full_width
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)
        self._update_elision()
        if self._reserve_full_width:
            self.updateGeometry()

    def fullText(self) -> str:  # noqa: N802 - Qt-style helper
        return self._full_text

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        hint = super().sizeHint()
        if not self._reserve_full_width:
            return hint
        width = self.fontMetrics().horizontalAdvance(self._full_text) + self._HINT_PADDING
        return QSize(min(width, self.maximumWidth()), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        hint = super().minimumSizeHint()
        if not self._reserve_full_width:
            return hint
        # Let the layout shrink the label; ``minimumWidth`` remains the floor.
        return QSize(0, hint.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_elision()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self._update_elision()

    def _update_elision(self) -> None:
        available = max(1, self.width() - self._ELIDE_PADDING)
        visible = self.fontMetrics().elidedText(
            self._full_text, self._elide_mode, available
        )
        QLabel.setText(self, visible)


class BrandLabel(ElidedLabel):
    """Premium monochrome wordmark with normal label accessibility semantics."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        visible = self.text()
        primary = self.palette().color(self.palette().ColorRole.WindowText)
        metrics = painter.fontMetrics()
        baseline = self.rect().top() + (self.rect().height() + metrics.ascent() - metrics.descent()) / 2.0
        painter.setPen(primary)
        painter.drawText(0, int(baseline), visible)
        painter.end()

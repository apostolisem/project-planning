"""Non-blocking toast notifications anchored to the bottom-right of a window."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme

_SEVERITY_ICON = {
    'info': 'i',
    'success': '✓',
    'warning': '!',
    'error': '×',
}


class _Toast(QFrame):
    def __init__(self, text: str, severity: str, on_dismiss, rich_text: bool = False) -> None:
        super().__init__(None)
        self._on_dismiss = on_dismiss
        self._dismissed = False
        colors = theme.tokens(True)
        accents = {
            'info': colors['cyan'],
            'success': colors['success'],
            'warning': colors['warning'],
            'error': colors['danger'],
        }
        accent = accents.get(severity, colors['cyan'])
        self.setObjectName('toast')
        self.setStyleSheet(
            f"QFrame#toast {{ background: rgba(15, 23, 42, 0.94); border-radius: 8px;"
            f" border-left: 4px solid {accent}; }}"
            "QFrame#toast QLabel { color: #f8fafc; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 8, 13, 8)
        layout.setSpacing(9)
        icon = QLabel(_SEVERITY_ICON.get(severity, 'i'))
        icon.setStyleSheet(f"color: {accent}; font-weight: 900;")
        label = QLabel(text)
        if rich_text:
            label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(False)
        layout.addWidget(icon)
        layout.addWidget(label)

    def dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.hide()
        self.setParent(None)
        self.deleteLater()
        self._on_dismiss(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.dismiss()
        event.accept()


class ToastOverlay(QWidget):
    """A small, self-sizing host for stacked toasts."""

    MARGIN = 18

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self._toasts: list[_Toast] = []
        self._fullscreen_hint = None
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return super().eventFilter(obj, event)

    def show_toast(self, text: str, severity: str = 'info', duration: int = 3800) -> None:
        if not text:
            return
        toast = _Toast(text, severity, self._remove)
        self._toasts.append(toast)
        self._layout.addWidget(toast)
        toast.show()
        self.show()
        self.raise_()
        self._reposition()
        if duration > 0:
            QTimer.singleShot(duration, toast.dismiss)

    def show_fullscreen_hint(self, duration: int = 1800) -> None:
        """Show a short, top-centered hint without covering the canvas."""
        if self._fullscreen_hint is not None:
            self._fullscreen_hint.dismiss()
        hint = _Toast(
            "To exit full screen, press <b>Esc</b> or <b>F11</b>",
            'info',
            self._remove_fullscreen_hint,
            rich_text=True,
        )
        self._fullscreen_hint = hint
        hint.setParent(self)
        hint.show()
        self.show()
        self.raise_()
        self._reposition()
        if duration > 0:
            QTimer.singleShot(duration, hint.dismiss)

    def clear(self) -> None:
        for toast in list(self._toasts):
            toast.dismiss()
        if self._fullscreen_hint is not None:
            self._fullscreen_hint.dismiss()

    def _remove(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        if not self._toasts:
            self.hide()

    def _remove_fullscreen_hint(self, hint: _Toast) -> None:
        if self._fullscreen_hint is hint:
            self._fullscreen_hint = None
        if not self._toasts:
            self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        if self._fullscreen_hint is not None:
            self._fullscreen_hint.adjustSize()
            hint_width = self._fullscreen_hint.width()
            hint_height = self._fullscreen_hint.height()
            x = max(0, (parent.width() - hint_width) // 2)
            y = self.MARGIN
            # Keep the overlay limited to the hint bounds. Clicks anywhere
            # else continue directly to the canvas underneath.
            self.setGeometry(x, y, hint_width, hint_height)
            self._fullscreen_hint.setGeometry(0, 0, hint_width, hint_height)
            self._fullscreen_hint.raise_()
            return
        self.adjustSize()
        x = max(self.MARGIN, parent.width() - self.width() - self.MARGIN)
        y = max(self.MARGIN, parent.height() - self.height() - self.MARGIN - 28)
        self.move(x, y)

"""Focus-scoped editors; unchanged rich text is never serialized again."""
from datetime import date
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QTextEdit, QLineEdit
from .text_shortcuts import apply_text_action, extract_text_payload, text_shortcut_action
from .constants import TEXT_SIZE_MIN, TEXT_SIZE_MAX, TEXT_SIZE_STEP
from .week_format import format_year_week


class RichField(QTextEdit):
    commit_requested = pyqtSignal()
    editingFinished = pyqtSignal()

    def __init__(self, single_line=False):
        super().__init__()
        self.single_line = single_line
        self._base_font = self.font()
        self._original = ('', None)
        self._loaded_html = ''
        self.setAcceptRichText(True)
        if single_line:
            self.setFixedHeight(34)
            self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def load_payload(self, text, html):
        self._original = (text or '', html)
        if html:
            self.setHtml(html)
        else:
            self.setPlainText(text or '')
        self.document().setDefaultFont(self._base_font)
        self._loaded_html = self.toHtml()
        self.document().setModified(False)

    def extract_payload(self):
        if self.toHtml() == self._loaded_html:
            return self._original
        return extract_text_payload(self.document(), self._base_font)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.load_payload(text, None)

    def format_action(self, action):
        cursor = self.textCursor()
        apply_text_action(cursor, action, self._base_font, min_size=TEXT_SIZE_MIN,
                          max_size=TEXT_SIZE_MAX, step=TEXT_SIZE_STEP)
        self.setTextCursor(cursor)
        self.setFocus()

    def keyPressEvent(self, event):
        action = text_shortcut_action(event)
        if action:
            self.format_action(action)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.load_payload(*self._original)
            self.clearFocus()
            event.accept()
        elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) and (self.single_line or event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit_requested.emit()
            self.editingFinished.emit()
            self.clearFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.commit_requested.emit()
        self.editingFinished.emit()
        super().focusOutEvent(event)

    def insertFromMimeData(self, source):
        text = source.text()
        if self.single_line:
            text = ' '.join(text.splitlines())
        self.insertPlainText(text)


class WeekField(QLineEdit):
    """Strict ISO-week input retaining an integer-index adapter for the inspector."""
    valueChanged = pyqtSignal()
    invalid = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._layout = self._model = None
        self._value = 1
        self._minimum, self._maximum = -200, 99999
        self.setMinimumWidth(100)
        self.setMaximumWidth(130)
        self.editingFinished.connect(self._commit)

    def set_context(self, layout, model):
        self._layout, self._model = layout, model
        self.setValue(self._value)

    def setRange(self, low, high):
        self._minimum, self._maximum = low, high

    def setValue(self, value):
        self._value = int(value)
        if self._layout:
            year, week = self._layout.week_index_to_year_week(self._model.year, self._value)
            self.setText(format_year_week(year, week))
        else:
            self.setText(str(value))
        self.setStyleSheet('')

    def value(self):
        return self._value

    def _commit(self):
        if not self._layout:
            return
        try:
            import re
            match = re.fullmatch(r'wk(\d{2})(\d{2})', self.text().strip(), re.IGNORECASE)
            if not match:
                raise ValueError()
            short_year, week = map(int, match.groups())
            base_century = (self._model.year // 100) * 100
            year = base_century + short_year
            if year - self._model.year > 50:
                year -= 100
            elif self._model.year - year > 50:
                year += 100
            date.fromisocalendar(year, week, 1)
            value = self._layout.week_index_for_iso_year(self._model.year, year) + week - 1
            if not self._minimum <= value <= self._maximum:
                raise ValueError()
        except ValueError:
            self.setStyleSheet('border: 1px solid #dc2626;')
            self.setToolTip('Enter a valid ISO week, for example wk2639.')
            self.invalid.emit(self.toolTip())
            return
        if value != self._value:
            self._value = value
            self.valueChanged.emit()
        self.setStyleSheet('')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.setValue(self._value)
            self.clearFocus()
            event.accept()
        else:
            super().keyPressEvent(event)


from PyQt6.QtWidgets import QSpinBox


class SessionSpinBox(QSpinBox):
    """A numeric edit commits on focus loss/Enter and can be cancelled with Escape."""
    def focusInEvent(self, event):
        self._session_value = self.value()
        super().focusInEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.setValue(getattr(self, '_session_value', self.value()))
            self.clearFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

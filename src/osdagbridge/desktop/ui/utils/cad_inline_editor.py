"""Open a temporary input box over a double-clicked CAD label."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QLocale, QObject, QRectF, Qt
from PySide6.QtGui import QDoubleValidator, QFont
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from osdagbridge.core.utils.common import CAD_EDITABLE_PARAMETERS


def label_rect(painter, x: float, y: float, text: str,
               font_size: int = 9, bold: bool = False) -> QRectF:
    """Return the area a user can double-click."""
    font = QFont("Arial", max(1, font_size), QFont.Bold if bold else QFont.Normal)
    painter.save()
    painter.setFont(font)
    metrics = painter.fontMetrics()
    lines = str(text).split("\n")
    line_height = metrics.height()
    width = max(metrics.boundingRect(line).width() for line in lines)
    height = line_height * len(lines)
    painter.restore()
    padding = 2
    return QRectF(x - padding, y - height - padding,
                  width + 2 * padding, height + 2 * padding)


class CadInlineEditor(QObject):
    def __init__(self, host, on_commit):
        super().__init__(host)
        self.host = host
        self.on_commit = on_commit
        self.enabled = True
        self._regions: dict[str, list[QRectF]] = {}
        self._editor: QLineEdit | None = None
        self._current_key: str | None = None

    def clear_regions(self) -> None:
        self._regions.clear()

    def register(self, label_key: str | None, rect: QRectF) -> None:
        if label_key in CAD_EDITABLE_PARAMETERS:
            self._regions.setdefault(label_key, []).append(rect)

    def hit_test(self, pos):
        for label_key, rects in self._regions.items():
            for rect in rects:
                if rect.contains(pos):
                    return label_key, rect
        return None

    def handle_double_click(self, event) -> bool:
        if not self.enabled or event.button() != Qt.LeftButton:
            return False
        self.finish(commit=True)
        hit = self.hit_test(event.position())
        if hit is None:
            return False
        label_key, rect = hit
        self._open(label_key, rect)
        return True

    def _open(self, label_key: str, rect: QRectF) -> None:
        spec = CAD_EDITABLE_PARAMETERS[label_key]
        current = self.host.params.get(spec["cad_param"], 0.0)
        try:
            displayed = float(current) / spec["display_divisor"]
        except (TypeError, ValueError):
            displayed = 0.0

        editor = QLineEdit(self.host)
        editor.setObjectName(f"{label_key}.inline_editor")
        validator = QDoubleValidator(0.0, 1e9, 8, editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        locale = QLocale.c()
        locale.setNumberOptions(QLocale.RejectGroupSeparator)
        validator.setLocale(locale)
        editor.setValidator(validator)
        self._initial_text = format(displayed, '.12g')
        editor.setText(self._initial_text)
        editor.setAccessibleName(spec["label"])
        editor.selectAll()

        bounds = rect.adjusted(-4, -4, 4, 4).toRect()
        bounds.setWidth(max(bounds.width(), 80))
        editor.setGeometry(bounds)

        self._editor = editor
        self._current_key = label_key
        QApplication.instance().installEventFilter(self)
        editor.show()
        editor.setFocus()

    def eventFilter(self, obj, event) -> bool:
        editor = self._editor
        if editor is None:
            return False
        event_type = event.type()
        if obj is editor and event_type == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish(commit=True)
                return True
            if event.key() == Qt.Key_Escape:
                self.finish(commit=False)
                return True
        elif obj is editor and event_type == QEvent.FocusOut:
            if event.reason() != Qt.PopupFocusReason:
                self.finish(commit=True)
        elif event_type in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            if isinstance(obj, QWidget) and obj is not editor and not editor.isAncestorOf(obj):
                self.finish(commit=True)
        return False

    def finish(self, commit: bool = True) -> None:
        editor = self._editor
        if editor is None:
            return

        text = editor.text().strip()
        acceptable = editor.hasAcceptableInput()
        label_key = self._current_key
        # Clear the editor before hiding it to avoid a second commit on focus loss.
        self._editor = None
        self._current_key = None
        QApplication.instance().removeEventFilter(self)
        editor.hide()
        editor.deleteLater()

        if not commit or not label_key or not acceptable or text == self._initial_text:
            return

        value = float(text)
        if value > 0:
            self.on_commit(CAD_EDITABLE_PARAMETERS[label_key]["key"], value)

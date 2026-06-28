"""Small UI helpers for keeping the interface responsive during heavy work."""
from contextlib import contextmanager

from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import Qt, QObject, QEvent


class _ViewportResizeFilter(QObject):
    """Keeps an empty-state label filling its table's viewport on resize."""
    def __init__(self, label):
        super().__init__(label)
        self._label = label

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self._label.resize(obj.size())
        return False


def attach_empty_state(table, message: str) -> QLabel:
    """Show a friendly centered placeholder over a table when it has no rows,
    instead of a blank grid. Call refresh_empty_state(table) after (re)populating.
    Returns the label."""
    lbl = QLabel(message, table.viewport())
    lbl.setObjectName("empty-state")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#94a3b8; font-size:14px; background:transparent;")
    lbl.resize(table.viewport().size())
    filt = _ViewportResizeFilter(lbl)
    table.viewport().installEventFilter(filt)
    lbl._resize_filter = filt          # keep a reference alive
    table._empty_label = lbl
    lbl.setVisible(table.rowCount() == 0)
    return lbl


def refresh_empty_state(table):
    """Toggle the table's empty-state placeholder based on its current rows."""
    lbl = getattr(table, "_empty_label", None)
    if lbl is None:
        return
    empty = table.rowCount() == 0
    lbl.setVisible(empty)
    if empty:
        lbl.resize(table.viewport().size())
        lbl.raise_()


@contextmanager
def busy_cursor():
    """Show a wait cursor around a blocking operation and force a fresh repaint
    before it starts, so the window stays visibly 'alive' (Windows won't ghost
    it to a black 'not responding' frame for a short block) and signals to the
    user that work is in progress."""
    app = QApplication.instance()
    if app is not None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()   # flush a clean paint before we block
    try:
        yield
    finally:
        if app is not None:
            QApplication.restoreOverrideCursor()
            QApplication.processEvents()

"""Small UI helpers for keeping the interface responsive during heavy work."""
from contextlib import contextmanager

from PyQt6.QtWidgets import QApplication, QLabel, QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QObject, QEvent, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon


# ── Coloured "pill" badges for table cells (priority / status) ─────────────────
PRIORITY_BADGES = {
    "קבוע":   ("#e3f2fd", "#1565c0"),
    "ראשונה": ("#ffebee", "#b71c1c"),
    "שנייה":  ("#fff8e1", "#e65100"),
    "בירור":  ("#f3e5f5", "#7b1fa2"),
}
STATUS_BADGES = {
    "פעיל":   ("#e8f5e9", "#1b5e20"),
    "מושהה":  ("#fff8e1", "#8b6914"),
    "הסתיים": ("#eceff1", "#546e7a"),
}


def search_icon(size: int = 16) -> QIcon:
    """A small magnifier icon drawn at runtime (no bundled asset)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#94a3b8")); pen.setWidthF(1.6)
    p.setPen(pen)
    p.drawEllipse(2, 2, 8, 8)
    p.drawLine(11, 11, 14, 14)
    p.end()
    return QIcon(pm)


class BadgeDelegate(QStyledItemDelegate):
    """Paint a cell's text as a soft rounded pill, coloured by its value
    (color_map: text → (bg_hex, fg_hex)). Unmapped/empty values render normally."""
    def __init__(self, color_map: dict, parent=None):
        super().__init__(parent)
        self._colors = color_map

    def paint(self, painter, option, index):
        text = (index.data() or "").strip()
        colors = self._colors.get(text)
        if not text or colors is None:
            super().paint(painter, option, index)
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        bg, fg = colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = option.fontMetrics
        tw = fm.horizontalAdvance(text) + 20
        th = fm.height() + 6
        r = option.rect
        x = r.right() - tw - 10                 # RTL: hug the right edge
        y = r.center().y() - th / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(x, y, tw, th), th / 2, th / 2)
        painter.setPen(QColor(fg))
        painter.drawText(QRect(int(x), int(y), int(tw), int(th)),
                         Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


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

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


class FeedbackDialog:
    """תיבת דו-שיח קטנה לשליחת הודעה/דיווח-תקלה למפתח.

    בנויה כפונקציה שמרימה QDialog (כדי לא לייבא QtWidgets הכבדים בראש הקובץ).
    ההודעה נשמרת דרך utils.feedback.save_feedback (קובץ JSONL מקומי שרק המפתח
    קורא). אין מסך שמציג הודעות למשתמש — זה ערוץ חד-כיווני בכוונה.
    """
    @staticmethod
    def open(parent=None):
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPlainTextEdit, QPushButton, QMessageBox,
        )
        from utils.feedback import save_feedback

        dlg = QDialog(parent)
        dlg.setWindowTitle("השארת הודעה למפתח")
        dlg.setMinimumWidth(440)
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.setContentsMargins(18, 16, 18, 16)

        title = QLabel("נתקלת בבעיה? יש בקשה לשיפור?")
        title.setObjectName("title")
        lay.addWidget(title)

        hint = QLabel(
            "כתוב כאן בחופשיות מה קרה או מה היית רוצה שישתפר. ההודעה נשמרת "
            "ותגיע למפתח התוכנה, שיתקן לפי הצורך. אפשר להשאיר שם — לא חובה."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("שם (לא חובה):"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("אפשר להשאיר ריק")
        name_row.addWidget(name_edit)
        lay.addLayout(name_row)

        msg = QPlainTextEdit()
        msg.setPlaceholderText("תאר כאן את הבעיה או הבקשה...")
        msg.setMinimumHeight(120)
        lay.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("ביטול")
        cancel.setObjectName("neutral")
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        send = QPushButton("שליחה")
        send.setObjectName("primary")
        btn_row.addWidget(send)
        lay.addLayout(btn_row)

        def _do_send():
            text = msg.toPlainText().strip()
            if not text:
                QMessageBox.information(dlg, "", "נא לכתוב הודעה לפני השליחה.")
                return
            try:
                save_feedback(text, name_edit.text())
            except Exception as e:
                QMessageBox.warning(dlg, "שגיאה", f"שמירת ההודעה נכשלה:\n{e}")
                return
            QMessageBox.information(dlg, "תודה!", "ההודעה נשמרה ותטופל. תודה רבה!")
            dlg.accept()

        send.clicked.connect(_do_send)
        msg.setFocus()
        return dlg.exec()


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

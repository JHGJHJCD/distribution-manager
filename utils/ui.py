"""Small UI helpers for keeping the interface responsive during heavy work."""
from contextlib import contextmanager

from PyQt6.QtWidgets import QApplication, QLabel, QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QObject, QEvent, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon


# ── RTL-safe right alignment ────────────────────────────────────────────────
# In an RTL widget Qt flips logical AlignRight to VISUAL-LEFT, so Hebrew table
# text drifted to the left edge of wide columns. AlignAbsolute disables the
# flip: this constant always means "hug the right edge on screen".
ALIGN_RIGHT = (Qt.AlignmentFlag.AlignRight
               | Qt.AlignmentFlag.AlignAbsolute
               | Qt.AlignmentFlag.AlignVCenter)


def rtl_text_area(te) -> None:
    """Make a QTextEdit/QPlainTextEdit start Hebrew-style: empty-state cursor on
    the right and RTL paragraph flow (Qt otherwise parks the cursor left)."""
    opt = te.document().defaultTextOption()
    opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
    te.document().setDefaultTextOption(opt)


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


# ── Dignified line-icons (drawn at runtime; no emoji, no bundled assets) ───────
from PyQt6.QtCore import QRectF, QPointF, QLineF   # noqa: E402


def line_icon(name: str, size: int = 18, color: str = "#475569") -> QPixmap:
    """Return a crisp, minimal line-icon pixmap for the given name. Used across
    the UI wherever a small dignified glyph is wanted instead of an emoji."""
    scale = 3   # supersample for crisp edges at small sizes
    S = size * scale
    pm = QPixmap(S, S)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color)); pen.setWidthF(1.7 * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def R(x, y, w, h):
        return QRectF(x * S, y * S, w * S, h * S)

    def L(x1, y1, x2, y2):
        p.drawLine(QPointF(x1 * S, y1 * S), QPointF(x2 * S, y2 * S))

    if name == "phone":
        path = R(0.24, 0.16, 0.30, 0.68)
        p.drawRoundedRect(path, 0.06 * S, 0.06 * S)
        L(0.34, 0.74, 0.44, 0.74)
    elif name == "id":
        p.drawRoundedRect(R(0.14, 0.24, 0.72, 0.52), 0.06 * S, 0.06 * S)
        p.drawEllipse(R(0.22, 0.36, 0.16, 0.16))
        L(0.46, 0.40, 0.74, 0.40); L(0.46, 0.52, 0.74, 0.52); L(0.22, 0.62, 0.60, 0.62)
    elif name in ("home", "address"):
        p.drawPolyline([QPointF(0.16 * S, 0.48 * S), QPointF(0.50 * S, 0.20 * S),
                        QPointF(0.84 * S, 0.48 * S)])
        p.drawRect(R(0.26, 0.48, 0.48, 0.34))
    elif name in ("users", "souls"):
        p.drawEllipse(R(0.30, 0.20, 0.24, 0.24))
        p.drawArc(R(0.22, 0.50, 0.40, 0.40), 0, 180 * 16)
        p.drawArc(R(0.52, 0.30, 0.28, 0.24), 30 * 16, 120 * 16)
        p.drawArc(R(0.56, 0.52, 0.30, 0.34), 300 * 16, 150 * 16)
    elif name in ("calendar", "date"):
        p.drawRoundedRect(R(0.18, 0.22, 0.64, 0.60), 0.05 * S, 0.05 * S)
        L(0.18, 0.38, 0.82, 0.38)
        L(0.32, 0.14, 0.32, 0.28); L(0.68, 0.14, 0.68, 0.28)
    elif name in ("mail", "email"):
        p.drawRoundedRect(R(0.16, 0.28, 0.68, 0.44), 0.04 * S, 0.04 * S)
        p.drawPolyline([QPointF(0.16 * S, 0.32 * S), QPointF(0.50 * S, 0.54 * S),
                        QPointF(0.84 * S, 0.32 * S)])
    elif name in ("synagogue", "building"):
        L(0.50, 0.12, 0.50, 0.26)                       # spire
        L(0.44, 0.19, 0.56, 0.19)
        p.drawRect(R(0.28, 0.30, 0.44, 0.52))
        L(0.50, 0.42, 0.50, 0.82)
        L(0.28, 0.56, 0.72, 0.56)
    elif name in ("area", "pin", "map"):
        p.drawArc(R(0.28, 0.16, 0.44, 0.44), 0, 360 * 16)
        p.drawPolyline([QPointF(0.32 * S, 0.46 * S), QPointF(0.50 * S, 0.84 * S),
                        QPointF(0.68 * S, 0.46 * S)])
        p.drawEllipse(R(0.43, 0.30, 0.14, 0.14))
    elif name in ("freq", "repeat"):
        p.drawArc(R(0.22, 0.22, 0.56, 0.56), 40 * 16, 260 * 16)
        p.drawPolyline([QPointF(0.66 * S, 0.16 * S), QPointF(0.80 * S, 0.28 * S),
                        QPointF(0.64 * S, 0.36 * S)])
    elif name in ("note", "notes"):
        p.drawRoundedRect(R(0.24, 0.16, 0.52, 0.68), 0.05 * S, 0.05 * S)
        L(0.34, 0.34, 0.66, 0.34); L(0.34, 0.48, 0.66, 0.48); L(0.34, 0.62, 0.54, 0.62)
    elif name in ("hash", "count"):
        L(0.34, 0.18, 0.28, 0.82); L(0.66, 0.18, 0.60, 0.82)
        L(0.20, 0.38, 0.78, 0.38); L(0.18, 0.62, 0.76, 0.62)
    elif name == "security":
        p.drawPolyline([QPointF(0.50 * S, 0.14 * S), QPointF(0.80 * S, 0.26 * S),
                        QPointF(0.80 * S, 0.52 * S)])
        p.drawArc(R(0.20, 0.14, 0.60, 0.74), 0, -140 * 16)
        L(0.20, 0.26, 0.20, 0.52); L(0.50, 0.14, 0.20, 0.26)
        p.drawPolyline([QPointF(0.38 * S, 0.48 * S), QPointF(0.47 * S, 0.58 * S),
                        QPointF(0.64 * S, 0.38 * S)])
    elif name == "update":
        p.drawArc(R(0.22, 0.22, 0.56, 0.56), 40 * 16, 280 * 16)
        p.drawPolyline([QPointF(0.64 * S, 0.14 * S), QPointF(0.80 * S, 0.24 * S),
                        QPointF(0.62 * S, 0.34 * S)])
        L(0.50, 0.36, 0.50, 0.62)
        p.drawPolyline([QPointF(0.40 * S, 0.52 * S), QPointF(0.50 * S, 0.64 * S),
                        QPointF(0.60 * S, 0.52 * S)])
    elif name in ("weights", "sliders"):
        for yy, kx in ((0.30, 0.40), (0.50, 0.62), (0.70, 0.34)):
            L(0.20, yy, 0.80, yy)
            p.drawEllipse(R(kx - 0.05, yy - 0.05, 0.10, 0.10))
    elif name in ("backup", "save"):
        p.drawArc(R(0.20, 0.30, 0.60, 0.44), 0, 180 * 16)
        L(0.20, 0.52, 0.20, 0.30); L(0.80, 0.52, 0.80, 0.30)
        L(0.50, 0.20, 0.50, 0.58)
        p.drawPolyline([QPointF(0.38 * S, 0.46 * S), QPointF(0.50 * S, 0.60 * S),
                        QPointF(0.62 * S, 0.46 * S)])
    elif name in ("danger", "warning"):
        p.drawPolyline([QPointF(0.50 * S, 0.16 * S), QPointF(0.84 * S, 0.80 * S),
                        QPointF(0.16 * S, 0.80 * S), QPointF(0.50 * S, 0.16 * S)])
        L(0.50, 0.38, 0.50, 0.60)
        p.drawEllipse(R(0.48, 0.68, 0.04, 0.04))
    elif name == "lock":
        p.drawRoundedRect(R(0.28, 0.44, 0.44, 0.38), 0.05 * S, 0.05 * S)
        p.drawArc(R(0.34, 0.20, 0.32, 0.40), 0, 180 * 16)
    else:
        p.drawEllipse(R(0.2, 0.2, 0.6, 0.6))
    p.end()
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


def section_header(text: str, icon_name: str, color: str = "#475569",
                   text_color: str = None, line_color: str = "#e8ecf2"):
    """Build a section-header row = a dignified line-icon + the header label,
    styled like the app's QLabel#section-header. Returns a QWidget."""
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
    box = QWidget()
    box.setObjectName("section-header-box")
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(7)
    ic = QLabel()
    ic.setPixmap(line_icon(icon_name, 18, color))
    ic.setStyleSheet("background:transparent; border:none;")
    lbl = QLabel(text)
    lbl.setObjectName("section-header")
    lbl.setStyleSheet(f"border:none; color:{text_color};" if text_color else "border:none;")
    row.addWidget(ic)
    row.addWidget(lbl)
    row.addStretch()
    box.setStyleSheet(
        "QWidget#section-header-box { border-bottom:2px solid %s; margin-bottom:2px; }" % line_color)
    return box


def add_glow(widget, color: str = "#22c55e", base: float = 10.0, peak: float = 26.0):
    """Give a widget a soft coloured halo that gently pulses (like a breathing
    glow) to draw the eye — used e.g. on the 'חשב המלצה' button. Returns the
    running animation (kept referenced on the widget so it isn't GC'd)."""
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
    eff = QGraphicsDropShadowEffect(widget)
    eff.setColor(QColor(color))
    eff.setOffset(0, 0)
    eff.setBlurRadius(base)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"blurRadius", widget)
    anim.setDuration(1300)
    anim.setStartValue(base)
    anim.setKeyValueAt(0.5, peak)
    anim.setEndValue(base)
    anim.setLoopCount(-1)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.start()
    widget._glow_anim = anim
    widget._glow_effect = eff
    return anim


def enable_touch_scroll(widget) -> None:
    """Make a scrollable widget (table/list/scroll-area) draggable by finger on a
    touch screen — a left-press-and-drag kinetically scrolls it. Harmless with a
    mouse (a normal click still selects; only a drag scrolls)."""
    try:
        from PyQt6.QtWidgets import QScroller, QAbstractItemView
        target = widget.viewport() if hasattr(widget, "viewport") else widget
        QScroller.grabGesture(
            target, QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        if isinstance(widget, QAbstractItemView):
            # a drag scrolls smoothly instead of rubber-band selecting
            widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            widget.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    except Exception:
        pass


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


class HighlightDelegate(QStyledItemDelegate):
    """Render a cell's text, highlighting the substring that matches the current
    search query (bold + soft-yellow background). Set the query with set_query();
    empty query renders normally."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._query = ""

    def set_query(self, q: str):
        self._query = (q or "").strip().lower()

    # Horizontal cell padding — matches the QSS `QTableWidget::item { padding }`
    # so the highlight rectangle lines up with where the text is actually drawn.
    _PAD = 12

    def paint(self, painter, option, index):
        # Draw the cell normally first (background, alternating rows, selection,
        # text) — then overlay a highlight on just the matched substring.
        super().paint(painter, option, index)
        text = index.data() or ""
        q = self._query
        pos = text.lower().find(q) if q else -1
        if pos < 0 or not text:
            return

        painter.save()
        fm = option.fontMetrics
        before, match = text[:pos], text[pos:pos + len(q)]
        r = option.rect
        # RTL, right-aligned text: it starts at (right - pad) and runs leftwards.
        x_text_right = r.right() - self._PAD
        w_before = fm.horizontalAdvance(before)
        w_match = fm.horizontalAdvance(match)
        x_match_right = x_text_right - w_before
        seg_rect = QRect(int(x_match_right - w_match), r.top(), int(w_match), r.height())
        painter.fillRect(seg_rect, QColor(255, 235, 59, 150))   # translucent yellow
        f = painter.font(); f.setBold(True); painter.setFont(f)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(option.palette.highlightedText().color() if selected else QColor("#7a5900"))
        painter.drawText(seg_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, match)
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
        rtl_text_area(msg)
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

"""Small UI helpers for keeping the interface responsive during heavy work."""
from contextlib import contextmanager

from PyQt6.QtWidgets import (QApplication, QLabel, QStyledItemDelegate, QStyle,
                             QDialog, QVBoxLayout, QHBoxLayout, QFrame, QPushButton,
                             QScrollArea, QWidget)
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
    elif name in ("user", "person", "name"):
        p.drawEllipse(R(0.36, 0.18, 0.28, 0.28))          # head
        p.drawArc(R(0.24, 0.52, 0.52, 0.52), 0, 180 * 16)  # shoulders
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
    elif name in ("download", "export"):
        L(0.50, 0.16, 0.50, 0.58)
        p.drawPolyline([QPointF(0.36 * S, 0.44 * S), QPointF(0.50 * S, 0.60 * S),
                        QPointF(0.64 * S, 0.44 * S)])
        p.drawPolyline([QPointF(0.22 * S, 0.72 * S), QPointF(0.22 * S, 0.82 * S),
                        QPointF(0.78 * S, 0.82 * S), QPointF(0.78 * S, 0.72 * S)])
    elif name in ("upload", "import"):
        L(0.50, 0.60, 0.50, 0.18)
        p.drawPolyline([QPointF(0.36 * S, 0.32 * S), QPointF(0.50 * S, 0.18 * S),
                        QPointF(0.64 * S, 0.32 * S)])
        p.drawPolyline([QPointF(0.22 * S, 0.72 * S), QPointF(0.22 * S, 0.82 * S),
                        QPointF(0.78 * S, 0.82 * S), QPointF(0.78 * S, 0.72 * S)])
    elif name == "print":
        p.drawPolyline([QPointF(0.30 * S, 0.34 * S), QPointF(0.30 * S, 0.16 * S),
                        QPointF(0.70 * S, 0.16 * S), QPointF(0.70 * S, 0.34 * S)])
        p.drawRoundedRect(R(0.18, 0.34, 0.64, 0.30), 0.05 * S, 0.05 * S)
        p.drawRect(R(0.30, 0.60, 0.40, 0.24))
        p.drawEllipse(R(0.70, 0.42, 0.05, 0.05))
    elif name == "send":
        p.drawPolyline([QPointF(0.84 * S, 0.16 * S), QPointF(0.16 * S, 0.46 * S),
                        QPointF(0.46 * S, 0.56 * S), QPointF(0.84 * S, 0.16 * S)])
        p.drawPolyline([QPointF(0.46 * S, 0.56 * S), QPointF(0.46 * S, 0.82 * S),
                        QPointF(0.60 * S, 0.64 * S)])
    elif name in ("plus", "add"):
        L(0.50, 0.22, 0.50, 0.78); L(0.22, 0.50, 0.78, 0.50)
    elif name in ("doc", "file"):
        p.drawPolyline([QPointF(0.28 * S, 0.14 * S), QPointF(0.60 * S, 0.14 * S),
                        QPointF(0.74 * S, 0.30 * S), QPointF(0.74 * S, 0.86 * S),
                        QPointF(0.28 * S, 0.86 * S), QPointF(0.28 * S, 0.14 * S)])
        p.drawPolyline([QPointF(0.60 * S, 0.14 * S), QPointF(0.60 * S, 0.30 * S),
                        QPointF(0.74 * S, 0.30 * S)])
        L(0.38, 0.50, 0.64, 0.50); L(0.38, 0.64, 0.58, 0.64)
    elif name in ("box", "package", "products"):
        p.drawPolyline([QPointF(0.50 * S, 0.14 * S), QPointF(0.82 * S, 0.32 * S),
                        QPointF(0.82 * S, 0.68 * S), QPointF(0.50 * S, 0.86 * S),
                        QPointF(0.18 * S, 0.68 * S), QPointF(0.18 * S, 0.32 * S),
                        QPointF(0.50 * S, 0.14 * S)])
        p.drawPolyline([QPointF(0.18 * S, 0.32 * S), QPointF(0.50 * S, 0.50 * S),
                        QPointF(0.82 * S, 0.32 * S)])
        L(0.50, 0.50, 0.50, 0.86)
    elif name in ("check", "tick"):
        p.drawPolyline([QPointF(0.20 * S, 0.54 * S), QPointF(0.42 * S, 0.76 * S),
                        QPointF(0.80 * S, 0.26 * S)])
    elif name in ("trash", "delete"):
        L(0.22, 0.28, 0.78, 0.28)
        p.drawPolyline([QPointF(0.40 * S, 0.28 * S), QPointF(0.40 * S, 0.20 * S),
                        QPointF(0.60 * S, 0.20 * S), QPointF(0.60 * S, 0.28 * S)])
        p.drawPolyline([QPointF(0.30 * S, 0.28 * S), QPointF(0.34 * S, 0.82 * S),
                        QPointF(0.66 * S, 0.82 * S), QPointF(0.70 * S, 0.28 * S)])
        L(0.44, 0.40, 0.45, 0.72); L(0.56, 0.40, 0.55, 0.72)
    else:
        p.drawEllipse(R(0.2, 0.2, 0.6, 0.6))
    p.end()
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


def reveal_in_folder(path: str) -> None:
    """Open the file's containing folder in Windows Explorer with the file
    selected, so the user sees exactly where their export landed. Fails quietly
    (never raises) — an export is still a success even if the folder won't open."""
    import os
    import sys
    import subprocess
    try:
        norm = os.path.normpath(path)
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", norm])
        else:
            # non-Windows fallback: just open the containing directory
            folder = os.path.dirname(norm) or "."
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, folder])
    except Exception:
        try:
            os.startfile(os.path.dirname(os.path.normpath(path)))  # type: ignore[attr-defined]
        except Exception:
            pass


# Map a column-header text → a line-icon name, by keyword. Ordered: the FIRST
# keyword found in the header wins, so more specific terms come before generic
# ones (e.g. 'בית כנסת' before a bare fallback).
_HEADER_ICON_RULES = [
    ("בית כנסת", "synagogue"),
    ("מה חולק", "box"),
    ("אימייל", "mail"), ("מייל", "mail"),
    ("טלפון", "phone"), ("נייד", "phone"),
    ("כתובת", "address"), ("רחוב", "address"),
    ("אזור", "area"), ("קהילה", "area"),
    ("נפשות", "users"), ("ילד", "users"),
    ("תדירות", "freq"),
    ("חלוקה הבאה", "calendar"), ("חלוקה אחרונה", "calendar"),
    ("תאריך", "calendar"), ("לידה", "calendar"),
    ("הער", "note"),   # matches both הערה and הערות
    ("מחלק", "user"),
    ("שם", "user"),
    ("סטטוס", "security"),
    ("כמות", "hash"), ("ניקוד", "hash"),
    ("מספר", "hash"), ("מס'", "hash"),
]


def _header_icon_name(text: str):
    t = (text or "").strip()
    if not t:
        return None
    for kw, icon in _HEADER_ICON_RULES:
        if kw in t:
            return icon
    return None


def apply_header_icons(table, color: str = "#64748b", size: int = 16) -> None:
    """Add a dignified line-icon to each column header of a QTableWidget, chosen
    from the header text by keyword (see _HEADER_ICON_RULES). Columns with no
    matching keyword (checkbox column, 'סוג', 'עדיפות', ...) are left icon-less —
    a wrong icon reads worse than none. Reuses the app's built-in line_icon set,
    so there is no external icon-library dependency."""
    from PyQt6.QtWidgets import QTableWidgetItem
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        text = item.text() if item is not None else ""
        icon_name = _header_icon_name(text)
        if not icon_name:
            continue
        if item is None:
            item = QTableWidgetItem(text)
            table.setHorizontalHeaderItem(c, item)
        item.setIcon(QIcon(line_icon(icon_name, size, color)))


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
            QPlainTextEdit, QPushButton, QMessageBox, QCheckBox,
        )
        from utils import feedback as _feedback
        from utils.feedback import save_feedback
        from utils import email_utils

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

        # Optional: also email the message straight to the developer (bug #20).
        # Enabled only when the app's email is configured.
        _mail_ready = email_utils.is_configured()
        chk_email = QCheckBox("שלח את ההודעה גם למייל של המפתח")
        chk_email.setChecked(_mail_ready)
        chk_email.setEnabled(_mail_ready)
        if not _mail_ready:
            chk_email.setToolTip("כדי לשלוח במייל יש להגדיר תחילה מייל בלשונית "
                                 "הגדרות ← מייל למתנדבים")
        lay.addWidget(chk_email)

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
            note = "ההודעה נשמרה ותטופל. תודה רבה!"
            if chk_email.isChecked():
                with busy_cursor():
                    ok, err = _feedback.email_to_dev(text, name_edit.text())
                note += ("\n\nההודעה נשלחה גם למייל של המפתח ✓" if ok
                         else f"\n\n⚠ שליחת המייל למפתח נכשלה: {err}\n"
                              "(ההודעה נשמרה בכל זאת ותגיע דרך ערוץ אחר.)")
            QMessageBox.information(dlg, "תודה!", note)
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


def show_score_breakdown(parent, rec: dict):
    """Popup explaining how a recipient's need-score was computed (the per-factor
    value, weight and points). Shared by the 'חד פעמי' and 'חלוקה ורישום' tabs so
    both show an identical, RTL-correct breakdown. `rec` must carry the
    '_score_parts' the scoring pass fills in."""
    import html as _html
    from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                 QPushButton, QLabel, QMessageBox)

    name = rec.get("full_name", "")
    parts = rec.get("_score_parts")
    if not parts:
        QMessageBox.information(
            parent, "פירוט ניקוד",
            f"ל{name} אין ניקוד צורך בחלוקה זו.")
        return
    # QTextDocument ignores dir='rtl' for table COLUMN order (known project
    # pitfall), so the columns are written in reverse manually: the source order
    # is תרומה→משקל→ערך→גורם so that on screen it reads right-to-left with the
    # 'גורם' (factor) column on the right, matching the Hebrew reading direction.
    rows_html = "".join(
        "<tr>"
        f"<td align='center'><b>{p['points']}</b></td>"
        f"<td align='center'>{p['weight_pct']}%</td>"
        f"<td align='center'>{_html.escape(str(p['value']))}</td>"
        f"<td align='right'>{_html.escape(str(p['label']))}</td>"
        "</tr>"
        for p in parts
    )
    body = (
        "<div dir='rtl' style='font-family:Segoe UI;'>"
        "<p>ניקוד צורך כולל: <b style='color:#1565c0;font-size:15px'>"
        f"{rec.get('need_score')}</b> / 100 &nbsp;(גבוה = נזקק יותר)</p>"
        "<table dir='rtl' border='1' cellpadding='6' cellspacing='0' width='100%' "
        "style='border-collapse:collapse;'>"
        "<tr style='background:#e3f2fd;color:#1565c0;'>"
        "<th>תרומה לניקוד</th><th>משקל</th><th>ערך</th><th align='right'>גורם</th></tr>"
        f"{rows_html}</table>"
        "<p style='color:#6b7280;font-size:11px'>ערך חסר או הוצאה אפסית אינם תורמים "
        "לניקוד. המשקלים נקבעים בהגדרות ← משקלי ניקוד עדיפות.</p></div>"
    )
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"פירוט ניקוד — {name}")
    dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dlg.setMinimumWidth(460)
    v = QVBoxLayout(dlg)
    lbl = QLabel(body)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    row = QHBoxLayout()
    row.addStretch()
    btn = QPushButton("סגור")
    btn.setObjectName("neutral")
    btn.clicked.connect(dlg.accept)
    row.addWidget(btn)
    v.addLayout(row)
    dlg.exec()


def _fmt_criterion(lo, hi) -> str:
    """A human range label for a filter bound (min/max), e.g. 'עד 3,000',
    'לפחות 2', '1,000–3,000'."""
    def _n(x):
        try:
            xf = float(x)
            return f"{int(xf):,}" if xf == int(xf) else f"{xf:,.1f}"
        except (TypeError, ValueError):
            return str(x)
    if lo is not None and hi is not None:
        return f"{_n(lo)}–{_n(hi)}"
    if hi is not None:
        return f"עד {_n(hi)}"
    if lo is not None:
        return f"לפחות {_n(lo)}"
    return "—"


def show_filter_breakdown(parent, rec: dict, criteria: dict):
    """Popup explaining why a recipient is on the FILTER/BALANCE list — i.e. the
    criteria (income / children / per-soul) and this family's value for each, with
    a ✓/✗ per criterion. This replaces the need-score popup in 'filter' mode, where
    people are chosen by meeting the criteria (and community balance), NOT by score
    — so the operator sees the real reason (bug #6clvq)."""
    import html as _html
    import selection
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

    name = rec.get("full_name", "")
    rows = []
    for field, label in selection.FILTER_FIELDS:
        b = (criteria or {}).get(field) or {}
        lo, hi = b.get("min"), b.get("max")
        if lo is None and hi is None:
            continue
        val = selection.to_number(rec.get(field))
        raw = rec.get(field)
        val_txt = _html.escape(str(raw).strip()) if (raw not in (None, "")) else "— חסר —"
        if val is None:
            ok, mark, color = False, "✗", "#b91c1c"
        else:
            ok = (lo is None or val >= lo) and (hi is None or val <= hi)
            mark = "✓" if ok else "✗"
            color = "#334155" if ok else "#b91c1c"
        rows.append(
            "<tr>"
            f"<td align='center' style='color:{color};font-weight:800'>{mark}</td>"
            f"<td align='center'>{val_txt}</td>"
            f"<td align='center'>{_html.escape(_fmt_criterion(lo, hi))}</td>"
            f"<td align='right'>{_html.escape(label)}</td>"
            "</tr>")

    # Header note: how this person landed on the list.
    if rec.get("_balance_fill"):
        why = ("<b style='color:#b45309'>נוסף להשלמת מכסת הקהילה</b> — "
               "אמנם לא עומד בכל הסינון, אבל הוא מהקרובים ביותר לעמוד בו בקהילה שלו.")
    elif not rows:
        why = "בחלוקה זו לא הוגדר סינון פעיל — הרשימה כוללת את כל המקבלים."
    else:
        why = "נמצא ברשימה כי הוא <b style='color:#334155'>עומד בקריטריוני הסינון</b>:"

    rep = (rec.get("representative") or "").strip()
    community_line = (f"<p style='margin:2px 0'>קהילה (נציג): <b>{_html.escape(rep)}</b></p>"
                      if rep else "")
    regular_line = ("<p style='margin:2px 0;color:#92400e'>◆ מקבל <b>קבוע</b></p>"
                    if rec.get("_balance_regular") else "")

    table = ""
    if rows:
        table = (
            "<table dir='rtl' border='1' cellpadding='6' cellspacing='0' width='100%' "
            "style='border-collapse:collapse;margin-top:8px'>"
            "<tr style='background:#eef2f8;color:#334155;'>"
            "<th>עומד?</th><th>הערך של המשפחה</th><th>הסינון</th><th align='right'>קריטריון</th></tr>"
            + "".join(rows) + "</table>")

    body = (
        "<div dir='rtl' style='font-family:Segoe UI;font-size:13px;color:#1f2937'>"
        f"<p style='margin:0 0 6px 0'>{why}</p>"
        f"{community_line}{regular_line}{table}"
        "<p style='color:#6b7280;font-size:11px;margin-top:8px'>במצב 'סינון מותאם' "
        "הבחירה היא לפי עמידה בקריטריונים ואיזון בין קהילות — לא לפי ניקוד צורך.</p></div>")

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"למה ברשימה — {name}")
    dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dlg.setMinimumWidth(470)
    v = QVBoxLayout(dlg)
    lbl = QLabel(body)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    row = QHBoxLayout()
    row.addStretch()
    btn = QPushButton("סגור")
    btn.setObjectName("neutral")
    btn.clicked.connect(dlg.accept)
    row.addWidget(btn)
    v.addLayout(row)
    dlg.exec()


# ── Update-offer dialog (v2.60) ──────────────────────────────────────────────

def _release_notes_html(notes: str) -> str:
    """Release-notes text → styled RTL HTML for the update dialog (v2.81).

    Handles both formats this project's releases use: a one-line commit message
    ("גרסה X — כותרת: פריט, פריט, פריט") which becomes a headline + a bullet per
    item, and multi-line notes where -/*/• lines become styled bullets. All text
    is escaped and right-aligned."""
    import html as _html
    import re

    def inline(s: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _html.escape(s))

    def p_head(s: str) -> str:
        return ("<p dir='rtl' align='right' style='margin:2px 0 8px 0;"
                " color:#064e3b; font-weight:700;'>" + s + "</p>")

    def p_bullet(s: str) -> str:
        return ("<p dir='rtl' align='right' style='margin:4px 0;'>"
                "<span style='color:#0f9d78; font-weight:700;'>●</span>&nbsp; "
                "<span style='color:#334155;'>" + s + "</span></p>")

    def p_text(s: str) -> str:
        return ("<p dir='rtl' align='right' style='margin:5px 0;"
                " color:#334155;'>" + s + "</p>")

    lines = [ln.strip() for ln in (notes or "").splitlines() if ln.strip()]
    if not lines:
        return ""

    parts = []
    if len(lines) == 1:
        # One-line commit style: split the headline from the item list so a long
        # sentence becomes a readable bulleted list.
        m = re.match(r"^(.+?)\s*[:：]\s*(.+)$", lines[0])
        items = re.split(r"\s*[·;]\s*|,\s+", m.group(2)) if m else []
        items = [i.strip(" .") for i in items if i.strip(" .")]
        if len(items) >= 2:
            parts.append(p_head(inline(m.group(1))))
            parts += [p_bullet(inline(i)) for i in items]
        else:
            parts.append(p_text(inline(lines[0])))
    else:
        for i, ln in enumerate(lines):
            if ln[:1] in "-*•":
                parts.append(p_bullet(inline(ln[1:].strip())))
            elif ln.startswith("#"):
                parts.append(p_head(inline(ln.lstrip("#").strip())))
            elif i == 0:
                parts.append(p_head(inline(ln)))
            else:
                parts.append(p_text(inline(ln)))

    return ("<div dir='rtl' style='font-size:13px;'>" + "".join(parts) + "</div>")


class UpdateOfferDialog(QDialog):
    """A friendly, styled 'new version available' dialog (replaces the plain
    QMessageBox). Shows the playful greeting the operator asked for, the two
    versions side by side, and the release notes. exec() → Accepted means
    'download and install now'."""

    GREETING = "הנה העדכון שחלמת עליו.. (או שלא) 😄"

    def __init__(self, parent, new_version: str, current_version: str, notes: str = ""):
        super().__init__(parent)
        self.setWindowTitle("עדכון תוכנה")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(430)
        # Resizable window with a comfortable default so the full change list is
        # visible; the operator can drag it bigger. Height is capped to the screen.
        self.setSizeGripEnabled(True)
        scr = QApplication.primaryScreen()
        max_h = int(scr.availableGeometry().height() * 0.85) if scr else 700
        self.setMaximumHeight(max_h)
        self.resize(480, min(560, max_h))
        self.setStyleSheet("QDialog{background:#ffffff;}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QFrame()
        head.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 #064e3b, stop:1 #0f9d78); border:none;}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(22, 18, 22, 16)
        hl.setSpacing(4)
        t1 = QLabel("🎁 עדכון חדש זמין!")
        t1.setStyleSheet("color:#ffffff; font-size:18px; font-weight:800; background:transparent;")
        t2 = QLabel(self.GREETING)
        t2.setStyleSheet("color:rgba(255,255,255,0.92); font-size:13.5px; font-weight:600;"
                         " background:transparent;")
        hl.addWidget(t1)
        hl.addWidget(t2)
        lay.addWidget(head)

        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 20)
        body.setSpacing(12)

        vers = QHBoxLayout()
        vers.setSpacing(8)
        for i, (label, ver, bg, fg) in enumerate((
                ("הגרסה שלך", current_version, "#f1f5f4", "#5f7a70"),
                ("גרסה חדשה", new_version, "#e2f6ee", "#0f766e"))):
            if i:
                # RTL layout: the arrow sits between the pills, pointing from the
                # current version (right) to the new one (left).
                arrow = QLabel("←")
                arrow.setStyleSheet("color:#0f9d78; font-size:18px; font-weight:800;"
                                    " background:transparent;")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vers.addWidget(arrow)
            pill = QFrame()
            pill.setStyleSheet(f"QFrame{{background:{bg}; border:none; border-radius:10px;}}")
            pl = QVBoxLayout(pill)
            pl.setContentsMargins(12, 8, 12, 8)
            pl.setSpacing(2)
            a = QLabel(label)
            a.setStyleSheet(f"color:{fg}; font-size:12px; background:transparent;")
            a.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b = QLabel(f"v{ver}")
            b.setStyleSheet("color:#064e3b; font-size:15px; font-weight:800; background:transparent;")
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pl.addWidget(a)
            pl.addWidget(b)
            vers.addWidget(pill, 1)
        body.addLayout(vers)

        notes = (notes or "").strip()
        if notes:
            # Full release notes — shown in their entirety inside a scroll area so
            # a long change list is never truncated or clipped by a small window
            # (the operator asked to always see all the changes).
            cap = QLabel("מה חדש בגרסה זו:")
            cap.setStyleSheet("color:#0f766e; font-size:12.5px; font-weight:700;")
            body.addWidget(cap)

            nbox = QLabel(_release_notes_html(notes))
            nbox.setTextFormat(Qt.TextFormat.RichText)
            nbox.setWordWrap(True)
            nbox.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            nbox.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            nbox.setStyleSheet(
                "QLabel{background:transparent; color:#334155; font-size:12.5px;"
                " padding:8px 10px;}")

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(nbox)
            scroll.setMinimumHeight(120)
            scroll.setStyleSheet(
                "QScrollArea{background:#f4faf7; border:1px solid #d7ebe2;"
                " border-radius:10px;}"
                "QScrollArea > QWidget > QWidget{background:transparent;}")
            # Let the notes area take the extra space when the user enlarges the
            # window, so more of the change list shows at once.
            body.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        ok = QPushButton("⬇ הורד והתקן עכשיו")
        ok.setObjectName("primary")
        ok.setMinimumHeight(42)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        later = QPushButton("אחר כך")
        later.setObjectName("neutral")
        later.setMinimumHeight(42)
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.clicked.connect(self.reject)
        btns.addWidget(ok, 1)
        btns.addWidget(later)
        body.addLayout(btns)
        lay.addLayout(body)

    @staticmethod
    def offer(parent, new_version: str, current_version: str, notes: str = "") -> bool:
        """Convenience: show the dialog; True = install now."""
        dlg = UpdateOfferDialog(parent, new_version, current_version, notes)
        return dlg.exec() == QDialog.DialogCode.Accepted

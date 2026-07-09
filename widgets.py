"""
Shared date-input widgets used across all tabs.

WednesdayCalendar — QCalendarWidget with:
  - RTL layout, week starts on Sunday (system locale = Windows Hebrew)
  - Wednesday cells highlighted (blue dot + bold blue text)
  - Navigates to current month when opened on an empty/sentinel date

DateEdit — QDateEdit backed by WednesdayCalendar:
  - allow_empty=True  → sentinel QDate(2000,1,1), shows "לא מוגדר"
  - allow_empty=False → defaults to today, no empty state
  - get_iso() / set_from_iso() helpers for DB round-trips
"""

from PyQt6.QtWidgets import (QCalendarWidget, QDateEdit, QAbstractItemView,
                             QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QSpinBox, QPushButton, QLabel, QSizePolicy, QLayout,
                             QGraphicsOpacityEffect)
from PyQt6.QtCore import Qt, QDate, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QTextCharFormat, QBrush, QColor, QPainter, QFont


class WednesdayCalendar(QCalendarWidget):
    _SENTINEL = QDate(2000, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Rely on Windows system locale (Hebrew/Israel for this user).
        # Explicitly setting Hebrew locale here propagates back to the parent
        # QDateEdit and overrides setDisplayFormat — so we leave locale alone.
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFirstDayOfWeek(Qt.DayOfWeek.Sunday)
        self.setGridVisible(False)

        # ── Fix "two-digit dates vanish" bug ─────────────────────────────────
        # In the QDateEdit popup the calendar sized its columns too narrow, so
        # Qt elided two-digit day numbers (10–31) down to nothing while single
        # digits still fit. Give the popup a comfortable minimum size and stop
        # the inner view from eliding / clipping cell text.
        self.setMinimumSize(380, 340)
        view = self.findChild(QAbstractItemView, "qt_calendar_calendarview")
        if view is not None:
            view.setTextElideMode(Qt.TextElideMode.ElideNone)
            view.setWordWrap(False)
            view.setFont(QFont("Segoe UI", 10))

        # Wednesday column: bold blue text
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(QColor("#1565c0")))
        fmt.setFontWeight(700)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Wednesday, fmt)

    def paintCell(self, painter: QPainter, rect, date: QDate):
        super().paintCell(painter, rect, date)
        # Blue dot at the bottom of every Wednesday cell
        if date.dayOfWeek() == Qt.DayOfWeek.Wednesday:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1976d2"))
            r = 2
            cx = rect.center().x()
            cy = rect.bottom() - r - 2
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            painter.restore()

    def showEvent(self, event):
        if self.selectedDate() <= self._SENTINEL:
            today = QDate.currentDate()
            self.setCurrentPage(today.year(), today.month())
        super().showEvent(event)


class DateEdit(QDateEdit):
    """Smart date editor: Wednesday highlighting, optional empty state."""

    EMPTY = QDate(2000, 1, 1)

    def __init__(self, parent=None, allow_empty: bool = True):
        super().__init__(parent)
        self.setCalendarPopup(True)
        # QDateEdit in RTL mode reverses the section order, showing yyyy/MM/dd
        # instead of dd/MM/yyyy. Explicitly LTR keeps the format correct while
        # the parent layout stays RTL for positioning purposes.
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setCalendarWidget(WednesdayCalendar(self))
        # Must be set AFTER setCalendarWidget (which can reset the format)
        self.setDisplayFormat("dd/MM/yyyy")

        if allow_empty:
            self.setSpecialValueText("לא מוגדר")
            self.setMinimumDate(self.EMPTY)
            self.setDate(self.EMPTY)
        else:
            self.setMinimumDate(QDate(2020, 1, 1))
            self.setDate(QDate.currentDate())

    def is_empty(self) -> bool:
        return self.date() == self.EMPTY

    def clear_date(self):
        self.setDate(self.EMPTY)

    def get_iso(self) -> str:
        return "" if self.is_empty() else self.date().toString("yyyy-MM-dd")

    def set_from_iso(self, iso_str: str):
        if iso_str:
            d = QDate.fromString(str(iso_str)[:10], "yyyy-MM-dd")
            if d.isValid() and d > self.EMPTY:
                self.setDate(d)
                return
        self.setDate(self.EMPTY)


# Column widths shared by the header and every product row so they line up like
# a real table. In RTL the first-added widget sits on the right.
_QTY_W = 116     # "כמות" column (rightmost)
_DEL_W = 52      # "מחק" column (leftmost)
_ROW_H = 46


class ProductsEditor(QWidget):
    """Table-style editor for the multiple products handed out in one distribution.

    Rendered as a small table — כמות | סוג פריט | מחק — one row per product, each
    with a per-person quantity. Produces a human-readable summary string
    ('סל מזון ×1, עוף ×2') stored in the distribution's what_dist, plus a total
    used for the legacy quantity column. Starts with one empty line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._outer.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._anims = []   # keep fade animations alive

        # ── Header row (column titles) ────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(34)
        hh = QHBoxLayout(header)
        hh.setContentsMargins(4, 0, 4, 0)
        hh.setSpacing(10)

        def _htext(text, w=None, center=False):
            l = QLabel(text)
            l.setStyleSheet("color:#94a3b8; font-size:11px; font-weight:700; "
                            "letter-spacing:.03em; background:transparent; border:none;")
            if w:
                l.setFixedWidth(w)
            if center:
                l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return l

        hh.addWidget(_htext("כמות", _QTY_W, center=True))
        hh.addWidget(_htext("סוג פריט"), 1)
        hh.addWidget(_htext("מחק", _DEL_W, center=True))
        header.setStyleSheet("QWidget{border-bottom:1px solid #e6eaf2;}")
        self._outer.addWidget(header)

        self._rows_box = QVBoxLayout()
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._outer.addLayout(self._rows_box)

        self._rows = []   # list of dicts: {"widget", "name", "qty", "remove"}

        add_btn = QPushButton("הוסף פריט")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            "QPushButton{background:#f0f5fc; color:#1565c0; border:1px dashed #b8c6de;"
            " border-radius:9px; padding:7px 16px; font-size:13px; font-weight:700;"
            " margin-top:10px;}"
            "QPushButton:hover{background:#e4eefb; border-color:#8fb0e0;}")
        add_btn.clicked.connect(lambda: self.add_row())
        self._outer.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.add_row(animate=False)   # start with one line

    def add_row(self, name: str = "", qty: int = 1, animate: bool = True):
        row = QWidget()
        row.setFixedHeight(_ROW_H)
        row.setObjectName("prod-row")
        row.setStyleSheet("QWidget#prod-row{border-bottom:1px solid #f1f4f9;}")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(10)

        # ── כמות (rightmost) ──────────────────────────────────────────────────
        qty_spin = QSpinBox()
        qty_spin.setRange(1, 9999)
        qty_spin.setValue(max(1, int(qty or 1)))
        qty_spin.setFixedWidth(_QTY_W)
        qty_spin.setMinimumHeight(36)
        qty_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qty_spin.setStyleSheet(
            "QSpinBox{background:#ffffff; color:#1f2937; border:1px solid #d7dfea;"
            " border-radius:8px; padding:2px 8px; font-size:14px; font-weight:700;}"
            "QSpinBox:focus{border-color:#1e88e5;}")
        qty_spin.setToolTip("כמות לאדם — כמה יחידות מהמוצר הזה מקבל כל אחד")
        h.addWidget(qty_spin)

        # ── סוג פריט (stretch) ────────────────────────────────────────────────
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("סל מזון, עוף, שמן...")
        name_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        name_edit.setText(name)
        name_edit.setMinimumHeight(36)
        name_edit.setStyleSheet(
            "QLineEdit{background:#ffffff; color:#1f2937; border:1px solid #d7dfea;"
            " border-radius:8px; padding:4px 12px; font-size:13.5px;}"
            "QLineEdit:focus{border-color:#1e88e5;}")
        h.addWidget(name_edit, 1)

        # ── מחק (leftmost) ────────────────────────────────────────────────────
        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(34, 34)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("הסר פריט")
        remove_btn.setStyleSheet(
            "QPushButton{background:#fdecec; color:#dc2626; border:none;"
            " border-radius:9px; font-weight:700; min-width:34px; max-width:34px;"
            " font-size:14px; padding:0;}"
            "QPushButton:hover{background:#fbd5d5;}")
        del_wrap = QWidget()
        del_wrap.setFixedWidth(_DEL_W)
        dw = QHBoxLayout(del_wrap)
        dw.setContentsMargins(0, 0, 0, 0)
        dw.addWidget(remove_btn, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(del_wrap)

        entry = {"widget": row, "name": name_edit, "qty": qty_spin, "remove": remove_btn}
        remove_btn.clicked.connect(lambda: self._remove_row(entry))

        self._rows.append(entry)
        self._rows_box.addWidget(row)
        self._sync_remove_buttons()
        self._update_height()
        if animate:
            self._fade_in(row)
        return entry

    def _fade_in(self, widget):
        """Subtle fade-in when a product row appears."""
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Drop the effect when done so it never interferes with painting later.
        anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
        self._anims.append(anim)
        anim.start()

    def _update_height(self):
        """Pin the editor to exactly the height its header + rows + add-button need
        so the parent card allocates the right space, then re-flow ancestors."""
        self.setFixedHeight(34 + len(self._rows) * _ROW_H + 52)
        self.updateGeometry()
        p = self.parentWidget()
        while p is not None:
            lay = p.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            p = p.parentWidget()

    def _remove_row(self, entry):
        if len(self._rows) <= 1:
            entry["name"].clear()
            entry["qty"].setValue(1)
            return
        self._rows.remove(entry)
        entry["widget"].setParent(None)
        entry["widget"].deleteLater()
        self._sync_remove_buttons()
        self._update_height()

    def _sync_remove_buttons(self):
        # A single remaining line can't be removed (it just clears).
        only_one = len(self._rows) <= 1
        for e in self._rows:
            e["remove"].setVisible(not only_one)

    def clear(self):
        for e in list(self._rows):
            e["widget"].setParent(None)
            e["widget"].deleteLater()
        self._rows = []
        self.add_row()

    def set_products(self, items):
        """Replace the lines with (name, qty) pairs. Empty → a single blank line."""
        for e in list(self._rows):
            e["widget"].setParent(None)
            e["widget"].deleteLater()
        self._rows = []
        for name, qty in (items or []):
            self.add_row(name, qty, animate=False)
        if not self._rows:
            self.add_row(animate=False)

    def products_list(self):
        """Non-empty product lines as (name, qty) tuples."""
        out = []
        for e in self._rows:
            nm = e["name"].text().strip()
            if nm:
                out.append((nm, e["qty"].value()))
        return out

    def products_display(self) -> str:
        return ", ".join(f"{nm} ×{q}" for nm, q in self.products_list())

    def total_qty(self) -> int:
        return sum(q for _, q in self.products_list())

    def is_empty(self) -> bool:
        return not self.products_list()

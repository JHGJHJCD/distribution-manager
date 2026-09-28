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
                             QGraphicsOpacityEffect, QDialog, QComboBox, QTableWidget,
                             QTableWidgetItem, QHeaderView)
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

        # ── Fix "the whole calendar is black" bug ────────────────────────────
        # Inside the QDateEdit popup the calendar inherited a dark palette (white
        # text on a near-black surface, so it read as an all-black box). Pin an
        # explicit light theme: white day grid with dark text and a blue header.
        self.setStyleSheet(
            "QCalendarWidget QWidget{ background:#ffffff; }"
            "QCalendarWidget QAbstractItemView:enabled{"
            " background:#ffffff; color:#1f2937;"
            " selection-background-color:#0d9488; selection-color:#ffffff;"
            " outline:0; }"
            "QCalendarWidget QAbstractItemView:disabled{ color:#c7cdd6; }"
            "QCalendarWidget QWidget#qt_calendar_navigationbar{"
            " background:#0f766e; }"
            "QCalendarWidget QToolButton{"
            " color:#ffffff; background:transparent; font-size:14px;"
            " font-weight:700; padding:4px 10px; }"
            "QCalendarWidget QToolButton:hover{ background:#0d9488;"
            " border-radius:6px; }"
            "QCalendarWidget QToolButton::menu-indicator{ image:none; }"
            "QCalendarWidget QMenu{ background:#ffffff; color:#1f2937; }"
            "QCalendarWidget QSpinBox{ background:#ffffff; color:#1f2937;"
            " selection-background-color:#0d9488; }")

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
        fmt.setForeground(QBrush(QColor("#0f766e")))
        fmt.setFontWeight(700)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Wednesday, fmt)

    def paintCell(self, painter: QPainter, rect, date: QDate):
        super().paintCell(painter, rect, date)
        # Blue dot at the bottom of every Wednesday cell
        if date.dayOfWeek() == Qt.DayOfWeek.Wednesday:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#0d9488"))
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

    def get_iso(self) -> str:
        return "" if self.is_empty() else self.date().toString("yyyy-MM-dd")

    def set_from_iso(self, iso_str: str):
        if iso_str:
            d = QDate.fromString(str(iso_str)[:10], "yyyy-MM-dd")
            if d.isValid() and d > self.EMPTY:
                self.setDate(d)
                return
        self.setDate(self.EMPTY)


# ─── היסטוריית שינויים בכרטיס (v3.63, בקשת רון 22/9/2026) ───────────────────
from database import change_source_label   # noqa: E402  (pure, shared with Excel)


def change_line(ch: dict, with_when: bool = True) -> str:
    """One change as a short Hebrew line: 'הכנסות: 1,000 → 2,000' (+ מתי/מחשב)."""
    from database import change_value_label
    old = change_value_label(ch.get("field"), ch.get("old_value"))
    new = change_value_label(ch.get("field"), ch.get("new_value"))
    label = ch.get("field_changed") or ch.get("field") or ""
    core = f"{label}: {old} ← {new}"
    if not with_when:
        return core
    from utils import timefmt
    when = timefmt.datetime_str(ch.get("changed_at") or "")
    dev = ch.get("device") or ""
    return f"{when} · {core}" + (f" ({dev})" if dev else "")


class ChangeHistoryDialog(QDialog):
    """כל השינויים שנעשו בכרטיס של מקבל אחד — מתי, איזה שדה, מה היה, מה הפך,
    איך (עריכה/ייבוא/ביטול/אוטומטי) ובאיזה מחשב. תצוגה בלבד."""

    _COLS = ["מתי", "שדה", "היה", "הפך ל", "איך", "מחשב"]

    def __init__(self, rec: dict, parent=None, changes: list | None = None):
        super().__init__(parent)
        import database as db
        self.setWindowTitle("היסטוריית שינויים")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(820, 520)
        self._changes = changes if changes is not None else db.get_changes_for_recipient(
            rec.get("id") or 0, rec.get("guid") or "")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        title = QLabel(f"היסטוריית שינויים — {rec.get('full_name') or ''}")
        title.setStyleSheet("font-size:18px; font-weight:800; color:#0f172a;")
        lay.addWidget(title)
        self.lbl_sub = QLabel()
        self.lbl_sub.setStyleSheet("font-size:12px; color:#64748b;")
        lay.addWidget(self.lbl_sub)
        row = QHBoxLayout()
        row.addWidget(QLabel("הצג שדה:"))
        self.cmb_field = QComboBox()
        self.cmb_field.addItem("כל השדות", "")
        seen = []
        for ch in self._changes:
            key = ch.get("field") or ch.get("field_changed") or ""
            if key and key not in seen:
                seen.append(key)
                self.cmb_field.addItem(ch.get("field_changed") or key, key)
        self.cmb_field.currentIndexChanged.connect(self._fill)
        row.addWidget(self.cmb_field)
        row.addStretch()
        lay.addLayout(row)
        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self.lbl_empty = QLabel("עדיין לא נרשמו שינויים בכרטיס הזה.\n"
                                "מעכשיו כל שינוי בפרטים יירשם כאן — מה היה, מה הפך ומתי.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("color:#64748b; font-size:13.5px; padding:24px;")
        lay.addWidget(self.lbl_empty)
        btn = QPushButton("סגור")
        btn.setObjectName("neutral")
        btn.setMinimumHeight(38)
        btn.clicked.connect(self.accept)
        b = QHBoxLayout(); b.addStretch(); b.addWidget(btn); lay.addLayout(b)
        self._fill()

    def _fill(self):
        from utils import timefmt
        import database as db
        key = self.cmb_field.currentData() or ""
        rows = [c for c in self._changes
                if not key or (c.get("field") or c.get("field_changed")) == key]
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, ch in enumerate(rows):
            when = QTableWidgetItem(timefmt.datetime_str(ch.get("changed_at") or ""))
            when.setToolTip(timefmt.relative(ch.get("changed_at") or ""))
            vals = [when, QTableWidgetItem(ch.get("field_changed") or ch.get("field") or ""),
                    QTableWidgetItem(db.change_value_label(ch.get("field"), ch.get("old_value"))),
                    QTableWidgetItem(db.change_value_label(ch.get("field"), ch.get("new_value"))),
                    QTableWidgetItem(change_source_label(ch.get("source"))),
                    QTableWidgetItem(ch.get("device") or "")]
            vals[3].setForeground(QBrush(QColor("#0f766e")))
            f = vals[3].font(); f.setBold(True); vals[3].setFont(f)
            for c, it in enumerate(vals):
                self.table.setItem(r, c, it)
        n = len(self._changes)
        self.lbl_sub.setText("אין שינויים רשומים" if not n else
                             f"{n} שינויים" + (f" · מוצגים {len(rows)}" if len(rows) != n else ""))
        self.table.setVisible(bool(rows))
        self.lbl_empty.setVisible(not rows)

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

from PyQt6.QtWidgets import QCalendarWidget, QDateEdit, QAbstractItemView
from PyQt6.QtCore import Qt, QDate
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

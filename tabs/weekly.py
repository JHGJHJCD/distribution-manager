from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox,
    QAbstractItemView, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from datetime import date
import database as db
from styles import (OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG,
                    SELECTED_BG, SELECTED_FG)

# colours for one-time picks (+ reserve) merged into the weekly issuance list
_RESERVE_BG, _RESERVE_FG = "#ede7f6", "#5e35b1"

# Compact styling for the small Excel / print action buttons.
_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"


def _fdate(s: str) -> str:
    """'2026-06-03' → '03/06/2026'"""
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""


def _days_to_next_wednesday() -> int:
    """How many days from today until the nearest distribution day (Wednesday).
    0 when today is Wednesday. Used to scope the list to the closest week."""
    return (2 - date.today().weekday()) % 7


from utils.excel_utils import export_distribution_to_excel
from utils.print_view import print_distribution_list
from utils.ui import busy_cursor, attach_empty_state, refresh_empty_state

COLS = ["מס'", "שם מלא", "טלפון 1", "טלפון 2", "טלפון 3",
        "אזור", "תדירות", "חלוקה הבאה"]


class WeeklyTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._rows_data = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("חלוקה השבוע — הרשימה לשבוע הקרוב")
        title.setObjectName("title")
        lay.addWidget(title)

        # Filter row — area only (the list is always the nearest week)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("סנן אזור:"))
        self.area_combo = QComboBox()
        self.area_combo.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.area_combo)
        self._reload_areas()

        filter_row.addStretch()

        btn_export = QPushButton("ייצא ל-Excel")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet(_SMALL_BTN)
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)

        btn_print = QPushButton("הדפסה")
        btn_print.setObjectName("neutral")
        btn_print.setStyleSheet(_SMALL_BTN)
        btn_print.clicked.connect(self._print)
        filter_row.addWidget(btn_print)

        lay.addLayout(filter_row)

        # Compact legend — only the merged one-time / reserve markers
        legend = QHBoxLayout()
        for color, text in [(SELECTED_FG, "● חד-פעמי"), (_RESERVE_FG, "● רזרבה")]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color};")
            legend.addWidget(lbl)
        legend.addStretch()
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("subtitle")
        legend.addWidget(self.lbl_count)
        lay.addLayout(legend)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "אין חלוקות לשבוע הקרוב")

    def _reload_areas(self):
        """Populate the area filter from the areas that actually exist."""
        prev = self.area_combo.currentText() if self.area_combo.count() else "הכל"
        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        self.area_combo.addItem("הכל")
        for a in db.get_areas():
            self.area_combo.addItem(a)
        idx = self.area_combo.findText(prev)
        self.area_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.area_combo.blockSignals(False)

    def refresh(self):
        # Keep the area list in sync with the data, then show the nearest week.
        self._reload_areas()
        area = self.area_combo.currentText() or "הכל"
        days = _days_to_next_wednesday()
        self._rows_data = db.get_weekly_list(days_ahead=days, area_filter=area)
        # Merge in the one-time picks (+ reserve) chosen in the 'חד פעמי' tab, so
        # this is the full issuance list for the week. They live on group_tab.
        gt = getattr(self.main_win, "group_tab", None)
        if gt is not None:
            base_ids = {r.get("id") for r in self._rows_data}
            picks = [r for r in gt._rows_data
                     if r.get("id") in gt._extra_ids and r.get("id") not in base_ids
                     and (area == "הכל" or r.get("area", "") == area)]
            self._rows_data = self._rows_data + picks
        self._populate()

    def _populate(self):
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))
        onetime = 0

        for r, rec in enumerate(self._rows_data):
            if rec.get("frequency") == "חד-פעמי":   # a one-time pick / reserve
                onetime += 1
                if rec.get("_reserve"):
                    bg, fg, freq_disp = QColor(_RESERVE_BG), QColor(_RESERVE_FG), "חד-פעמי · רזרבה"
                else:
                    bg, fg, freq_disp = QColor(SELECTED_BG), QColor(SELECTED_FG), "חד-פעמי"
                next_disp = ""
            else:
                days_left = rec.get("days_left", 0)
                if days_left < 0:
                    bg, fg = QColor(OVERDUE_BG), QColor(OVERDUE_FG)
                elif days_left <= 1:
                    bg, fg = QColor(TODAY_BG), QColor(TODAY_FG)
                else:
                    bg, fg = QColor(WEEK_BG), QColor(WEEK_FG)
                next_disp = _fdate(rec.get("next_distribution", ""))
                freq_disp = rec.get("frequency", "")

            vals = [str(r + 1), rec.get("full_name", ""),
                    rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", ""),
                    rec.get("area", ""), freq_disp, next_disp]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setBackground(bg)
                item.setForeground(fg)
                item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
                if c == 1:   # name — bold
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c, item)

        extra = f"  ·  חד-פעמי: {onetime}" if onetime else ""
        self.lbl_count.setText(f"סה\"כ: {len(self._rows_data)}{extra}")
        refresh_empty_state(self.table)

    def _get_export_rows(self):
        return self._rows_data

    def _export(self):
        rows = self._get_export_rows()
        if not rows:
            QMessageBox.information(self, "", "אין נתונים לייצוא")
            return
        try:
            with busy_cursor():
                path = export_distribution_to_excel(rows, date.today().strftime("%d/%m/%Y"))
            QMessageBox.information(self, "ייצוא הושלם", f"נשמר:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    def _print(self):
        rows = self._get_export_rows()
        print_distribution_list(rows, date.today().strftime("%d/%m/%Y"), self)

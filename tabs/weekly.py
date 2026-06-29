from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QSpinBox,
    QAbstractItemView, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from datetime import date
import database as db
from styles import OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG

def _fdate(s: str) -> str:
    """'2026-06-03' → '03/06/2026'"""
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""
from utils.excel_utils import export_distribution_to_excel
from utils.print_view import print_distribution_list
from utils.ui import busy_cursor, attach_empty_state, refresh_empty_state

COLS = ["מס'", "שם מלא", "טלפון 1", "טלפון 2", "טלפון 3",
        "אזור", "נפשות", "תדירות", "חלוקה הבאה", "ימים", "✓ ביצוע"]

STATUS_OPTS = ["", "✓", "✗", "–"]


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

        title = QLabel("חלוקה השבוע — מי מקבל בקרוב")
        title.setObjectName("title")
        lay.addWidget(title)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("הצג עד (ימים):"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 90)
        self.days_spin.setValue(30)
        self.days_spin.setFixedWidth(70)
        self.days_spin.valueChanged.connect(self.refresh)
        filter_row.addWidget(self.days_spin)

        filter_row.addWidget(QLabel("סנן אזור:"))
        self.area_combo = QComboBox()
        self.area_combo.addItems(["הכל", "בעלז", "נתיב"])
        self.area_combo.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.area_combo)

        filter_row.addStretch()

        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("subtitle")
        filter_row.addWidget(self.lbl_stats)

        btn_export = QPushButton("ייצא לExcel")
        btn_export.setObjectName("neutral")
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)

        btn_print = QPushButton("הדפסה")
        btn_print.setObjectName("neutral")
        btn_print.clicked.connect(self._print)
        filter_row.addWidget(btn_print)

        btn_sync = QPushButton("שמור סימונים")
        btn_sync.setObjectName("primary")
        btn_sync.clicked.connect(self._save_statuses)
        filter_row.addWidget(btn_sync)

        lay.addLayout(filter_row)

        # Legend
        legend = QHBoxLayout()
        for color, text in [(OVERDUE_FG, "● באיחור"), (TODAY_FG, "● היום/מחר"), (WEEK_FG, "● השבוע")]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color};")
            legend.addWidget(lbl)
        legend.addStretch()
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
        self.table.cellDoubleClicked.connect(self._toggle_status)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "אין חלוקות קרובות בטווח שנבחר")

    def refresh(self):
        days = self.days_spin.value()
        area = self.area_combo.currentText()
        self._rows_data = db.get_weekly_list(days_ahead=days, area_filter=area)
        self._populate()

    def _populate(self):
        today = date.today()
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))
        overdue = today_cnt = week_cnt = 0

        for r, rec in enumerate(self._rows_data):
            days_left = rec.get("days_left", 0)

            if days_left < 0:
                bg = QColor(OVERDUE_BG)
                fg = QColor(OVERDUE_FG)
                overdue += 1
            elif days_left <= 1:
                bg = QColor(TODAY_BG)
                fg = QColor(TODAY_FG)
                today_cnt += 1
            else:
                bg = QColor(WEEK_BG)
                fg = QColor(WEEK_FG)
                week_cnt += 1

            vals = [str(r + 1), rec.get("full_name", ""),
                    rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", ""),
                    rec.get("area", ""), str(rec.get("souls", "") or ""),
                    rec.get("frequency", ""), _fdate(rec.get("next_distribution", "")),
                    str(days_left), rec.get("_status", "")]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setBackground(bg)
                item.setForeground(fg)
                item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
                if c == 1:   # name — bold
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c, item)

        self.lbl_stats.setText(
            f"⏰ באיחור: {overdue}  |  🔥 היום/מחר: {today_cnt}  |  ✅ השבוע: {week_cnt}  |  סה\"כ: {len(self._rows_data)}"
        )
        refresh_empty_state(self.table)

    def _toggle_status(self, row, col):
        if col != 10:
            return
        item = self.table.item(row, col)
        if not item:
            return
        current = item.text()
        idx = STATUS_OPTS.index(current) if current in STATUS_OPTS else 0
        next_val = STATUS_OPTS[(idx + 1) % len(STATUS_OPTS)]
        item.setText(next_val)
        self._rows_data[row]["_status"] = next_val
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        if rec_id:
            db.update_recipient(rec_id, {"weekly_status": next_val})
            self._rows_data[row]["weekly_status"] = next_val

    def _save_statuses(self):
        saved = 0
        for row, rec in enumerate(self._rows_data):
            status = rec.get("_status", "") or rec.get("weekly_status", "") or ""
            rec_id = rec.get("id")
            if rec_id is None:
                continue
            db.update_recipient(rec_id, {"weekly_status": status})
            saved += 1
        QMessageBox.information(self, "שמור", f"נשמרו סימונים עבור {saved} מקבלים")

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

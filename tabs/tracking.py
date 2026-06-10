from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QComboBox, QAbstractItemView, QPushButton,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
import database as db

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""

COLS = ["מס'", "שם מקבל", "תאריך", "אזור", "נפשות", "מה חולק", "כמות", "מחלק", "הערות"]


class TrackingTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._build_ui()
        self._all_rows = []

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("מעקב חלוקות — היסטוריה מלאה")
        title.setObjectName("title")
        lay.addWidget(title)

        # Filter
        frow = QHBoxLayout()
        frow.addWidget(QLabel("חיפוש שם:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("הקלד שם...")
        self.search.setMaximumWidth(200)
        self.search.textChanged.connect(lambda: self._filter_timer.start(220))
        frow.addWidget(self.search)
        frow.addStretch()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        frow.addWidget(self.count_lbl)
        lay.addLayout(frow)

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
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)

        # Change log section
        log_title = QLabel("היסטוריית שינויי סטטוס")
        log_title.setObjectName("subtitle")
        lay.addWidget(log_title)

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["תאריך", "מקבל", "שדה", "ישן", "חדש"])
        self.log_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.log_table.setMaximumHeight(150)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr2 = self.log_table.horizontalHeader()
        hdr2.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        lay.addWidget(self.log_table)

        self._all_rows = []

    def refresh(self):
        self._all_rows = db.get_distributions(limit=1000)
        self._populate(self._all_rows)
        self._load_log()

    def _populate(self, rows):
        _ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            vals = [str(r + 1), rec.get("recipient_name", ""),
                    _fdate(rec.get("dist_date", "")), rec.get("area", ""),
                    str(rec.get("souls", "") or ""), rec.get("what_dist", ""),
                    str(rec.get("quantity", "") or ""), rec.get("distributor", ""),
                    rec.get("notes", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(_ALIGN)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        self.count_lbl.setText(f"סה\"כ רשומות: {len(rows)}")

    def _apply_filter(self):
        text = self.search.text().strip().lower()
        if not text:
            self._populate(self._all_rows)
            return
        filtered = [r for r in self._all_rows if text in (r.get("recipient_name") or "").lower()]
        self._populate(filtered)

    def _filter(self, text):
        self._apply_filter()

    def _load_log(self):
        _ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        logs = db.get_change_log(limit=100)
        self.log_table.blockSignals(True)
        self.log_table.setRowCount(len(logs))
        for r, entry in enumerate(logs):
            vals = [entry.get("changed_at", "")[:16], entry.get("recipient_name", ""),
                    entry.get("field_changed", ""), entry.get("old_value", ""),
                    entry.get("new_value", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(_ALIGN)
                self.log_table.setItem(r, c, item)
        self.log_table.blockSignals(False)

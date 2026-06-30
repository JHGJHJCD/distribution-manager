from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QLineEdit,
    QSpinBox, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt
from widgets import DateEdit

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""
from PyQt6.QtGui import QColor, QFont
from datetime import date
import database as db
from utils.backup import auto_backup_async
from utils.excel_utils import export_distribution_to_excel
from utils.print_view import print_distribution_list
from utils.ui import busy_cursor

COLS = ["✔", "שם מלא", "טלפון 1", "טלפון 2", "טלפון 3", "אזור", "נפשות", "הערות"]


class GroupUpdateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._rows_data = []
        self._extra_ids: set = set()  # IDs added manually from one_time tab
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        # Title
        title = QLabel("עדכון קבוצתי — רישום חלוקה")
        title.setObjectName("title")
        lay.addWidget(title)

        # Distribution details — panel card
        # NOTE: use objectName selector so the rule applies ONLY to this widget
        # and does NOT cascade to child inputs (QLineEdit, QDateEdit, QSpinBox).
        details_card = QWidget()
        details_card.setObjectName("details-card")
        details_card.setStyleSheet(
            "QWidget#details-card { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }"
        )
        details_row = QHBoxLayout(details_card)
        details_row.setSpacing(14)
        details_row.setContentsMargins(12, 8, 12, 8)

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet("font-weight:700; color:#374151; background:transparent; border:none;")
            return l

        details_row.addWidget(_lbl("תאריך:"))
        self.date_edit = DateEdit(allow_empty=False)
        self.date_edit.setMinimumWidth(130)
        self.date_edit.setToolTip("תאריך ביצוע החלוקה — ימי רביעי מסומנים בכחול")
        details_row.addWidget(self.date_edit)

        details_row.addWidget(_lbl("מה חולק:"))
        self.what_input = QLineEdit()
        self.what_input.setPlaceholderText("סל מזון, עוף, ...")
        self.what_input.setMinimumWidth(150)
        self.what_input.setToolTip("תיאור המוצר שחולק")
        details_row.addWidget(self.what_input, 2)

        details_row.addWidget(_lbl("כמות:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 9999)
        self.qty_spin.setMinimumWidth(70)
        self.qty_spin.setToolTip("כמות יחידות שחולקו")
        details_row.addWidget(self.qty_spin)

        details_row.addWidget(_lbl("מחלק:"))
        self.dist_input = QLineEdit()
        self.dist_input.setPlaceholderText("שם המחלק")
        self.dist_input.setMinimumWidth(130)
        self.dist_input.setToolTip("שם האדם שביצע את החלוקה")
        details_row.addWidget(self.dist_input, 1)

        lay.addWidget(details_card)

        # Stats row
        stats_row = QHBoxLayout()
        self.lbl_total = QLabel("סה\"כ ברשימה: 0")
        self.lbl_checked = QLabel("סומנו: 0")
        self.lbl_souls = QLabel("נפשות: 0")
        for lbl in [self.lbl_total, self.lbl_checked, self.lbl_souls]:
            lbl.setObjectName("subtitle")
            stats_row.addWidget(lbl)
        stats_row.addStretch()

        btn_check_all = QPushButton("בחר הכל")
        btn_check_all.setObjectName("neutral")
        btn_check_all.clicked.connect(self._check_all)
        stats_row.addWidget(btn_check_all)

        btn_uncheck_all = QPushButton("בטל הכל")
        btn_uncheck_all.setObjectName("neutral")
        btn_uncheck_all.clicked.connect(self._uncheck_all)
        stats_row.addWidget(btn_uncheck_all)

        lay.addLayout(stats_row)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._update_counts)
        lay.addWidget(self.table)

        # Bottom buttons
        bot = QHBoxLayout()
        bot.setSpacing(8)

        btn_save = QPushButton("שמור חלוקה למעקב")
        btn_save.setObjectName("primary")
        btn_save.setMinimumHeight(34)
        btn_save.setToolTip("שמור את הסימונים כחלוקה מבוצעת ועדכן תאריכים")
        btn_save.clicked.connect(self._save)
        bot.addWidget(btn_save)

        btn_export = QPushButton("ייצא לExcel")
        btn_export.setObjectName("neutral")
        btn_export.setToolTip("ייצא את הרשימה הנוכחית לקובץ Excel")
        btn_export.clicked.connect(self._export_excel)
        bot.addWidget(btn_export)

        btn_print = QPushButton("הדפסה")
        btn_print.setObjectName("neutral")
        btn_print.setToolTip("הדפס רשימת חלוקה (A4 לאורך)")
        btn_print.clicked.connect(self._print)
        bot.addWidget(btn_print)

        bot.addStretch()
        lay.addLayout(bot)

    def refresh(self):
        # Exclude one-time recipients — they appear only when explicitly added from the one-time tab
        base = [r for r in db.get_all_recipients(status_filter="פעיל")
                if r.get("frequency") != "חד-פעמי"]
        base_ids = {r["id"] for r in base}
        # Keep manually added one-time recipients that were selected from the one-time tab
        extras = [r for r in self._rows_data if r["id"] in self._extra_ids and r["id"] not in base_ids]
        self._rows_data = base + extras
        self._populate()

    def _populate(self):
        self.table.blockSignals(True)
        # Drop old items in one batch BEFORE re-sizing. Calling setItem() over an
        # existing checkable cell is pathologically slow (≈8s for 1000 rows); a
        # clear first makes every refresh O(n) instead of freezing the app.
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))
        for r, rec in enumerate(self._rows_data):
            # Checkbox column
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            # One-time recipients explicitly added from the "חד פעמי" tab arrive
            # PRE-CHECKED (they were deliberately selected), so they're included in
            # the issued/saved list. Regulars start unchecked (mark who came).
            chk.setCheckState(Qt.CheckState.Checked if rec.get("id") in self._extra_ids
                              else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk.setData(Qt.ItemDataRole.UserRole, rec["id"])
            self.table.setItem(r, 0, chk)

            vals = [rec.get("full_name", ""), rec.get("phone1", ""),
                    rec.get("phone2", ""), rec.get("phone3", ""),
                    rec.get("area", ""), str(rec.get("souls", "") or ""), ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c < len(vals) - 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:   # name — bold
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c + 1, item)

        self.table.blockSignals(False)
        self._update_counts()

    def _update_counts(self):
        total = self.table.rowCount()
        checked = 0
        souls = 0
        for r in range(total):
            chk = self.table.item(r, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                checked += 1
                souls_item = self.table.item(r, 6)
                try:
                    souls += int(souls_item.text()) if souls_item else 0
                except ValueError:
                    pass
        self.lbl_total.setText(f"סה\"כ ברשימה: {total}")
        self.lbl_checked.setText(f"סומנו: {checked}")
        self.lbl_souls.setText(f"נפשות: {souls}")

    def _check_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk:
                chk.setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._update_counts()

    def _uncheck_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk:
                chk.setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_counts()

    def _get_checked_recipients(self):
        result = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                rec_id = chk.data(Qt.ItemDataRole.UserRole)
                rec = next((x for x in self._rows_data if x["id"] == rec_id), None)
                if rec:
                    notes_item = self.table.item(r, 7)
                    rec_copy = dict(rec)
                    rec_copy["notes"] = notes_item.text() if notes_item else ""
                    result.append(rec_copy)
        return result

    def _save(self):
        checked = self._get_checked_recipients()
        if not checked:
            QMessageBox.information(self, "", "לא סומן אף מקבל")
            return

        dist_date   = self.date_edit.get_iso()
        what        = self.what_input.text().strip()
        qty         = self.qty_spin.value()
        distributor = self.dist_input.text().strip()

        # ── אימות שדות חובה ─────────────────────────────────────────────────
        _ERR = "border: 2px solid #dc2626; background-color: #fff5f5;"
        errors = []

        if not what:
            self.what_input.setStyleSheet(_ERR)
            self.what_input.setToolTip("חובה למלא מה חולק")
            errors.append("מה חולק: שדה חובה")
        else:
            self.what_input.setStyleSheet("")
            self.what_input.setToolTip("תיאור המוצר שחולק")

        if not distributor:
            self.dist_input.setStyleSheet(_ERR)
            self.dist_input.setToolTip("חובה למלא שם המחלק")
            errors.append("שם המחלק: שדה חובה")
        else:
            self.dist_input.setStyleSheet("")
            self.dist_input.setToolTip("שם האדם שביצע את החלוקה")

        if errors:
            QMessageBox.warning(self, "שדות חסרים", "• " + "\n• ".join(errors))
            return

        with busy_cursor():
            db.bulk_add_distributions(checked, dist_date, what, qty, distributor)
            auto_backup_async()

        # The added one-time recipients have now been distributed — drop them from
        # the group list so they aren't shown (or re-saved) again next time.
        self._extra_ids.clear()

        msg = f"נשמרה חלוקה ל-{len(checked)} מקבלים"
        QMessageBox.information(self, "הצלחה", msg)
        self._uncheck_all()

        if self.main_win:
            self.main_win.status_msg(msg)
            self.main_win.refresh_all()

    def _export_excel(self):
        checked = self._get_checked_recipients()
        if not checked:
            checked = self._rows_data
        dist_date = _fdate(self.date_edit.get_iso())
        try:
            with busy_cursor():
                path = export_distribution_to_excel(checked, dist_date)
            QMessageBox.information(self, "ייצוא הושלם", f"הקובץ נשמר:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    def _print(self):
        checked = self._get_checked_recipients()
        if not checked:
            checked = self._rows_data
        dist_date = _fdate(self.date_edit.get_iso())
        print_distribution_list(checked, dist_date, self)

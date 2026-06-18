from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QSpinBox,
    QAbstractItemView, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from datetime import date
import database as db
from styles import OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG, SELECTED_BG, SELECTED_FG

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""

COLS = ["בחר", "שם מלא", "טלפון", "אזור", "נפשות", "חלוקה אחרונה", "ימים מאז"]


class OneTimeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._rows_data = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("ניהול חד-פעמיים — עדיפות חלוקה")
        title.setObjectName("title")
        lay.addWidget(title)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("סנן אזור:"))
        self.area_combo = QComboBox()
        self.area_combo.addItems(["הכל", "בעלז", "נתיב"])
        self.area_combo.currentTextChanged.connect(self.refresh)
        ctrl.addWidget(self.area_combo)

        ctrl.addWidget(QLabel("מוצרים זמינים:"))
        self.products_spin = QSpinBox()
        self.products_spin.setRange(0, 9999)
        self.products_spin.setValue(0)
        self.products_spin.setToolTip("הכנס כמה מוצרים יש — המערכת תחשב כמה לחד-פעמיים")
        self.products_spin.setFixedWidth(90)
        ctrl.addWidget(self.products_spin)

        btn_calc = QPushButton("חשב המלצה")
        btn_calc.clicked.connect(self._calc_suggestion)
        ctrl.addWidget(btn_calc)

        ctrl.addStretch()

        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("subtitle")
        ctrl.addWidget(self.lbl_stats)
        lay.addLayout(ctrl)

        # Legend
        legend = QHBoxLayout()
        for color, text in [(OVERDUE_FG,   "● מעל 30 יום / לא קיבל"),
                             (TODAY_FG,    "● 14–30 יום"),
                             (WEEK_FG,     "● פחות מ-14 יום"),
                             (SELECTED_FG, "● נבחר לחלוקה")]:
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
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_check_changed)
        lay.addWidget(self.table)

        # Bottom
        bot = QHBoxLayout()
        self.lbl_selected = QLabel("נבחרו: 0")
        bot.addWidget(self.lbl_selected)
        bot.addStretch()

        btn_add = QPushButton("הוסף נבחרים לעדכון קבוצתי")
        btn_add.setObjectName("success")
        btn_add.setMinimumHeight(36)
        btn_add.clicked.connect(self._add_to_group_update)
        bot.addWidget(btn_add)
        lay.addLayout(bot)

    def refresh(self):
        area = self.area_combo.currentText()
        self._rows_data = db.get_one_time_list(area_filter=area)
        self._populate()

    def _populate(self, suggested_n: int = -1):
        self.table.blockSignals(True)
        # Clear old items first — re-using existing checkable cells is very slow.
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))
        today = date.today()

        for r, rec in enumerate(self._rows_data):
            days_since = rec.get("days_since", 0)
            selected = (suggested_n >= 0 and r < suggested_n)

            if selected:
                bg = QColor(SELECTED_BG)
                fg = QColor(SELECTED_FG)
            elif days_since >= 30:
                bg = QColor(OVERDUE_BG)
                fg = QColor(OVERDUE_FG)
            elif days_since >= 14:
                bg = QColor(TODAY_BG)
                fg = QColor(TODAY_FG)
            else:
                bg = QColor(WEEK_BG)
                fg = QColor(WEEK_FG)

            # Checkbox
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, rec["id"])
            chk.setBackground(bg)
            chk.setForeground(fg)
            self.table.setItem(r, 0, chk)

            ld_raw = rec.get("last_distribution", "") or ""
            ld_display = (_fdate(ld_raw) if ld_raw else "לא קיבל")
            days_display = str(days_since) if ld_raw else "—"
            vals = [rec.get("full_name", ""), rec.get("phone1", ""), rec.get("area", ""),
                    str(rec.get("souls", "") or ""), ld_display, days_display]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(bg)
                item.setForeground(fg)
                self.table.setItem(r, c + 1, item)

        self.table.blockSignals(False)
        self._update_selected_count()
        self.lbl_stats.setText(f"סה\"כ חד-פעמיים: {len(self._rows_data)}")

    def _on_check_changed(self):
        self._update_selected_count()

    def _update_selected_count(self):
        count = sum(
            1 for r in range(self.table.rowCount())
            if (chk := self.table.item(r, 0)) and chk.checkState() == Qt.CheckState.Checked
        )
        self.lbl_selected.setText(f"נבחרו: {count}")

    def _calc_suggestion(self):
        total = self.products_spin.value()
        if total <= 0:
            QMessageBox.information(self, "", "הכנס מספר מוצרים זמינים")
            return
        n, regular_count = db.compute_suggested_n(total)
        self._populate(suggested_n=n)
        QMessageBox.information(
            self, "המלצת מערכת",
            f"סה\"כ מוצרים: {total}\n"
            f"קבועים פעילים: {regular_count}\n"
            f"מוצרים לחד-פעמיים: {n}\n\n"
            f"סומנו {n} ראשונים לפי עדיפות (מי שקיבל הכי מזמן)"
        )

    def _add_to_group_update(self):
        selected = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                rec_id = chk.data(Qt.ItemDataRole.UserRole)
                rec = next((x for x in self._rows_data if x["id"] == rec_id), None)
                if rec:
                    selected.append(rec)

        if not selected:
            QMessageBox.information(self, "", "לא נבחרו מקבלים")
            return

        if self.main_win and hasattr(self.main_win, "group_tab"):
            gt = self.main_win.group_tab
            added = 0
            for rec in selected:
                if not any(r["id"] == rec["id"] for r in gt._rows_data):
                    gt._rows_data.append(rec)
                    gt._extra_ids.add(rec["id"])
                    added += 1
            gt._populate()
            self.main_win.tabs.setCurrentWidget(gt)
            self.main_win.status_msg(f"נוספו {added} חד-פעמיים לעדכון קבוצתי")

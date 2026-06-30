import html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QSpinBox,
    QAbstractItemView, QMessageBox, QDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from datetime import date
import database as db
from utils.ui import attach_empty_state, refresh_empty_state
from styles import OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG, SELECTED_BG, SELECTED_FG

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""

COLS = ["בחר", "שם מלא", "עדיפות", "ניקוד", "חלוקה אחרונה"]

# Priority code → label shown in the table.
_PRIORITY_LABEL = {3: "ראשונה", 2: "שנייה"}

# Reserve (standby) row colours — distinct from the main "selected" tint.
RESERVE_BG = "#ede7f6"
RESERVE_FG = "#5e35b1"


def _priority_label(rec: dict) -> str:
    pr = rec.get("priority")
    if pr in _PRIORITY_LABEL:
        return _PRIORITY_LABEL[pr]
    raw = (rec.get("priority_raw") or "").strip()
    if "בירור" in raw:
        return "בירור"
    return "—"


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

        ctrl.addWidget(QLabel("רזרבה:"))
        self.reserve_spin = QSpinBox()
        self.reserve_spin.setRange(0, 999)
        try:
            self.reserve_spin.setValue(int(db.get_setting("reserve_count") or 5))
        except (ValueError, TypeError):
            self.reserve_spin.setValue(5)
        self.reserve_spin.setToolTip("כמה אנשי רזרבה (הבאים בתור לפי עדיפות) להוסיף לרשימה")
        self.reserve_spin.setFixedWidth(70)
        ctrl.addWidget(self.reserve_spin)

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
        for color, text in [(OVERDUE_FG,   "● עדיפות ראשונה (3)"),
                             (TODAY_FG,    "● עדיפות שנייה (2)"),
                             (WEEK_FG,     "● לא בחלוקה (1 / בירור)"),
                             (SELECTED_FG, "● נבחר לחלוקה"),
                             (RESERVE_FG,  "● רזרבה")]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color};")
            legend.addWidget(lbl)
        legend.addStretch()
        lay.addLayout(legend)

        hint = QLabel("💡 לחיצה על שם מקבל מציגה את פירוט חישוב הניקוד")
        hint.setObjectName("subtitle")
        lay.addWidget(hint)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        _score_hdr = self.table.horizontalHeaderItem(3)  # "ניקוד"
        if _score_hdr:
            _score_hdr.setToolTip("ניקוד הצורך — משוקלל לפי 'משקלי ניקוד' בלשונית הגדרות")
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # שם מלא column
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_check_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "אין חד-פעמיים פעילים להצגה")

        # Bottom
        bot = QHBoxLayout()
        self.lbl_selected = QLabel("נבחרו: 0")
        bot.addWidget(self.lbl_selected)
        bot.addStretch()

        btn_add = QPushButton("הוסף נבחרים לעדכון קבוצתי")
        btn_add.setObjectName("primary")
        btn_add.setMinimumHeight(36)
        btn_add.clicked.connect(self._add_to_group_update)
        bot.addWidget(btn_add)
        lay.addLayout(bot)

    def refresh(self):
        area = self.area_combo.currentText()
        self._rows_data = db.get_one_time_list(area_filter=area)
        self._populate()

    def _populate(self, suggested_n: int = -1, reserve_n: int = 0):
        self.table.blockSignals(True)
        # Clear old items first — re-using existing checkable cells is very slow.
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))

        # By priority order: the first `suggested_n` distribution rows are MAIN,
        # the next `reserve_n` are RESERVE (standby). Both are checked/included;
        # reserve is flagged + tinted so it prints as a separate section.
        main_so_far = 0
        reserve_so_far = 0
        for r, rec in enumerate(self._rows_data):
            in_dist = rec.get("in_distribution")
            is_main = (suggested_n >= 0 and in_dist and main_so_far < suggested_n)
            is_reserve = False
            if is_main:
                main_so_far += 1
            elif suggested_n >= 0 and in_dist and reserve_so_far < reserve_n:
                is_reserve = True
                reserve_so_far += 1
            rec["_reserve"] = is_reserve
            selected = is_main or is_reserve

            pr = rec.get("priority")
            if is_reserve:
                bg, fg = QColor(RESERVE_BG), QColor(RESERVE_FG)
            elif is_main:
                bg, fg = QColor(SELECTED_BG), QColor(SELECTED_FG)
            elif pr == 3:
                bg, fg = QColor(OVERDUE_BG), QColor(OVERDUE_FG)
            elif pr == 2:
                bg, fg = QColor(TODAY_BG), QColor(TODAY_FG)
            else:
                bg, fg = QColor(WEEK_BG), QColor(WEEK_FG)

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
            score = rec.get("need_score")
            score_display = f"{score:.0f}" if isinstance(score, (int, float)) else "—"
            prio_label = _priority_label(rec) + (" · רזרבה" if is_reserve else "")
            vals = [rec.get("full_name", ""), prio_label, score_display, ld_display]

            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(bg)
                item.setForeground(fg)
                if c == 0:   # name column — bold + clickable for the score breakdown
                    item.setToolTip("לחץ על השם לפירוט חישוב הניקוד")
                    nf = item.font(); nf.setUnderline(True); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c + 1, item)

        self.table.blockSignals(False)
        refresh_empty_state(self.table)
        self._update_selected_count()
        if suggested_n >= 0:
            self.lbl_stats.setText(
                f"עיקרי: {main_so_far}  ·  רזרבה: {reserve_so_far}  |  סה\"כ ברשימה: {len(self._rows_data)}")
        else:
            in_dist_count = sum(1 for x in self._rows_data if x.get("in_distribution"))
            self.lbl_stats.setText(
                f"בחלוקה (עדיפות 1+2): {in_dist_count}  |  סה\"כ ברשימה: {len(self._rows_data)}")

    def _on_check_changed(self):
        self._update_selected_count()

    def _update_selected_count(self):
        count = sum(
            1 for r in range(self.table.rowCount())
            if (chk := self.table.item(r, 0)) and chk.checkState() == Qt.CheckState.Checked
        )
        self.lbl_selected.setText(f"נבחרו: {count}")

    def _on_cell_clicked(self, row, col):
        # Clicking a name (column 1) opens the score breakdown for that person.
        if col != 1 or row < 0 or row >= len(self._rows_data):
            return
        self._show_score_breakdown(self._rows_data[row])

    def _show_score_breakdown(self, rec):
        name = rec.get("full_name", "")
        parts = rec.get("_score_parts")
        if not parts:
            QMessageBox.information(
                self, "פירוט ניקוד",
                f"{name} אינו ברשימת החלוקה (עדיפות 3/2), ולכן אין לו ניקוד צורך.")
            return
        rows_html = "".join(
            f"<tr>"
            f"<td>{html.escape(str(p['label']))}</td>"
            f"<td align='center'>{html.escape(str(p['value']))}</td>"
            f"<td align='center'>{p['weight_pct']}%</td>"
            f"<td align='center'><b>{p['points']}</b></td>"
            f"</tr>"
            for p in parts
        )
        body = (
            f"<div dir='rtl' style='font-family:Rubik,Segoe UI;'>"
            f"<p>ניקוד צורך כולל: <b style='color:#1565c0;font-size:15px'>"
            f"{rec.get('need_score')}</b> / 100 &nbsp;(גבוה = נזקק יותר)</p>"
            f"<table border='1' cellpadding='6' cellspacing='0' width='100%' "
            f"style='border-collapse:collapse;'>"
            f"<tr style='background:#e3f2fd;color:#1565c0;'>"
            f"<th align='right'>גורם</th><th>ערך</th><th>משקל</th><th>תרומה לניקוד</th></tr>"
            f"{rows_html}</table>"
            f"<p style='color:#6b7280;font-size:11px'>ערך חסר מחושב כניטרלי. "
            f"המשקלים נקבעים בהגדרות ← משקלי ניקוד עדיפות.</p></div>"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(f"פירוט ניקוד — {name}")
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dlg.setMinimumWidth(440)
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

    def _calc_suggestion(self):
        total = self.products_spin.value()
        if total <= 0:
            QMessageBox.information(self, "", "הכנס מספר מוצרים זמינים")
            return
        n, regular_count = db.compute_suggested_n(total)
        reserve_n = self.reserve_spin.value()
        db.set_setting("reserve_count", str(reserve_n))   # remember as default
        in_dist_count = sum(1 for x in self._rows_data if x.get("in_distribution"))
        picked = min(n, in_dist_count)
        reserve_picked = max(0, min(reserve_n, in_dist_count - picked))
        self._populate(suggested_n=n, reserve_n=reserve_n)
        msg = (
            f"סה\"כ מוצרים: {total}\n"
            f"קבועים (קוד 4): {regular_count}\n"
            f"נותר לחד-פעמיים: {n}\n"
            f"מועמדים בעדיפות (1+2): {in_dist_count}\n\n"
            f"סומנו {picked} עיקריים + {reserve_picked} רזרבה — לפי סדר עדיפות\n"
            f"(ראשונה (3) קודם, אחר כך שנייה (2), ובתוך כל דרגה לפי ניקוד הצורך)."
        )
        if n > in_dist_count:
            msg += (f"\n\n⚠ יש יותר מוצרים ({n}) ממועמדי העדיפות ({in_dist_count}). "
                    f"את השאר אפשר לסמן ידנית.")
        QMessageBox.information(self, "המלצת מערכת", msg)

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
                    gt._rows_data.append(dict(rec))   # snapshot incl. _reserve flag
                    gt._extra_ids.add(rec["id"])
                    added += 1
            gt._populate()
            # they also join the weekly issuance list — refresh it next time it opens
            if hasattr(self.main_win, "weekly_tab"):
                self.main_win.weekly_tab._needs_refresh = True
            self.main_win.tabs.setCurrentWidget(gt)
            self.main_win.status_msg(f"נוספו {added} חד-פעמיים לרשימת החלוקה")

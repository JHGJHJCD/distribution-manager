import html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QSpinBox,
    QAbstractItemView, QMessageBox, QDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from datetime import date
import database as db
import selection
from utils.ui import (attach_empty_state, refresh_empty_state, ALIGN_RIGHT,
                      search_icon, add_glow, enable_touch_scroll, apply_header_icons,
                      show_score_breakdown)
from styles import OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG, SELECTED_BG, SELECTED_FG

_SMALL_GREEN_BTN = (
    "QPushButton{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "  stop:0 #43b563, stop:1 #2e9e4f); color:#ffffff; border:none;"
    "  border-radius:9px; font-weight:800; font-size:12px;"
    "  min-height:24px; min-width:70px; padding:3px 16px; }"
    "QPushButton:hover{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "  stop:0 #4fc06e, stop:1 #1b7a37); }"
    "QPushButton:pressed{ background:#1b7a37; }"
)

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
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("חיפוש: שם, טלפון, ת״ז, כתובת, אזור...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(240)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(lambda: self._search_timer.start(180))
        ctrl.addWidget(self.search_input)

        # 'מוצרים זמינים' + 'רזרבה' now live in the 'חלוקה ורישום' tab (single
        # source of truth). Here we only READ and display them.
        self.lbl_products_info = QLabel("")
        self.lbl_products_info.setStyleSheet("color:#475569; font-weight:700;")
        self.lbl_products_info.setToolTip(
            "מספר המוצרים והרזרבה נקבעים בלשונית 'חלוקה ורישום'")
        ctrl.addWidget(self.lbl_products_info)

        btn_calc = QPushButton("חשב המלצה")
        btn_calc.setStyleSheet(_SMALL_GREEN_BTN)
        btn_calc.setToolTip("סמן אוטומטית את המומלצים לחלוקה לפי מספר המוצרים והעדיפות")
        btn_calc.clicked.connect(self._calc_suggestion)
        ctrl.addWidget(btn_calc)
        add_glow(btn_calc, "#22c55e")   # gentle green halo to draw the eye

        ctrl.addStretch()

        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("subtitle")
        ctrl.addWidget(self.lbl_stats)
        lay.addLayout(ctrl)

        # Legend
        legend = QHBoxLayout()
        for color, text in [(OVERDUE_FG,   "● עדיפות ראשונה"),
                             (TODAY_FG,    "● עדיפות שנייה"),
                             (WEEK_FG,     "● לא בחלוקה / בירור"),
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
        apply_header_icons(self.table)
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
        enable_touch_scroll(self.table)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "אין חד-פעמיים פעילים להצגה")

        # Bottom
        bot = QHBoxLayout()
        self.lbl_selected = QLabel("נבחרו: 0")
        bot.addWidget(self.lbl_selected)
        bot.addStretch()

        btn_add = QPushButton("הוסף נבחרים לעדכון קבוצתי")
        btn_add.setObjectName("primary")
        btn_add.setMinimumHeight(34)
        btn_add.clicked.connect(self._add_to_group_update)
        bot.addWidget(btn_add)
        lay.addLayout(bot)

    def refresh(self):
        # Only real distribution candidates (priority ראשונה/שנייה) are shown —
        # data-only one-timers with no priority are no longer listed here (bug #5;
        # they also used to show a stray 'received' date, now fixed at the source).
        self._rows_data = [r for r in db.get_one_time_list(area_filter="הכל")
                           if r.get("in_distribution")]
        self._update_products_info()
        # Land pre-marked: auto-apply the recommendation from the shared product
        # count so the operator (who arrives here from 'חלוקה ורישום') just reviews
        # and adds. If no count is set yet, show the list unmarked.
        total = self._shared_total()
        if total > 0:
            n, _regs = db.compute_suggested_n(total)
            reserve_n = self._shared_reserve()
            self._populate(suggested_n=n, reserve_n=reserve_n)
        else:
            self._populate()

    @staticmethod
    def _shared_total() -> int:
        try:
            return int(db.get_setting("available_products") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _shared_reserve() -> int:
        try:
            return int(db.get_setting("reserve_count") or 0)
        except (TypeError, ValueError):
            return 0

    def _update_products_info(self):
        total = self._shared_total()
        if total <= 0:
            self.lbl_products_info.setText("מוצרים זמינים: לא הוגדר (נקבע ב'חלוקה ורישום')")
            return
        n, regs = db.compute_suggested_n(total)
        self.lbl_products_info.setText(
            f"מוצרים זמינים: {total} · קבועים: {regs} · לחד-פעמיים: {n} · רזרבה: {self._shared_reserve()}")

    _SEARCH_KEYS = ("full_name", "phone1", "phone2", "phone3", "area",
                    "id_number", "spouse_id_number", "address", "external_id",
                    "priority_raw", "synagogue", "representative")

    def _apply_search(self):
        """Hide rows that don't match the free-text query (any field). Works as a
        visibility filter so 'חשב המלצה' still ranks against the full list."""
        q = self.search_input.text().strip().lower()
        for r in range(self.table.rowCount()):
            if r >= len(self._rows_data):
                continue
            if not q:
                self.table.setRowHidden(r, False)
                continue
            rec = self._rows_data[r]
            hay = " ".join(str(rec.get(k) or "") for k in self._SEARCH_KEYS).lower()
            self.table.setRowHidden(r, q not in hay)

    def _populate(self, suggested_n: int = -1, reserve_n: int = 0):
        self.table.blockSignals(True)
        # Clear old items first — re-using existing checkable cells is very slow.
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))

        # Role assignment (main / reserve / out) is the pure selection core — the
        # SAME logic the tests pin down. The list is already need-ordered by
        # database.get_one_time_list; here we just split it by available portions.
        # The first `suggested_n` candidates are MAIN, the next `reserve_n` are
        # RESERVE (standby). Reserve is checked here so it transfers to the group
        # tab, but it is NOT recorded on save (RULE 3, enforced in group_update).
        candidates = [rec for rec in self._rows_data if rec.get("in_distribution")]
        if suggested_n >= 0:
            selection.assign_roles(candidates, suggested_n, reserve_n)
        else:
            for rec in candidates:            # nothing marked until 'חשב המלצה'
                rec["_role"] = selection.ROLE_OUT
                rec["_reserve"] = False
        for rec in self._rows_data:
            if not rec.get("in_distribution"):
                rec["_role"] = selection.ROLE_OUT
                rec["_reserve"] = False
        main_so_far = sum(1 for r in candidates if r.get("_role") == selection.ROLE_MAIN)
        reserve_so_far = sum(1 for r in candidates if r.get("_role") == selection.ROLE_RESERVE)

        for r, rec in enumerate(self._rows_data):
            role = rec.get("_role", selection.ROLE_OUT)
            is_main = role == selection.ROLE_MAIN
            is_reserve = role == selection.ROLE_RESERVE
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
                item.setTextAlignment(ALIGN_RIGHT)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(bg)
                item.setForeground(fg)
                if c == 0:   # name column — bold + clickable for the score breakdown
                    item.setToolTip("לחץ על השם לפירוט חישוב הניקוד")
                    nf = item.font(); nf.setUnderline(True); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c + 1, item)

        self.table.blockSignals(False)
        refresh_empty_state(self.table)
        if hasattr(self, "search_input"):
            self._apply_search()   # keep the active text filter after a rebuild
        self._update_selected_count()
        if suggested_n >= 0:
            self.lbl_stats.setText(
                f"עיקרי: {main_so_far}  ·  רזרבה: {reserve_so_far}  |  סה\"כ ברשימה: {len(self._rows_data)}")
        else:
            in_dist_count = sum(1 for x in self._rows_data if x.get("in_distribution"))
            self.lbl_stats.setText(
                f"בחלוקה (ראשונה+שנייה): {in_dist_count}  |  סה\"כ ברשימה: {len(self._rows_data)}")

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
        show_score_breakdown(self, self._rows_data[row])

    def _calc_suggestion(self):
        total = self._shared_total()
        if total <= 0:
            QMessageBox.information(
                self, "",
                "לא הוגדר מספר מוצרים.\nהגדר 'מוצרים זמינים' בלשונית 'חלוקה ורישום'.")
            return
        # Regulars are served first from the same pool; only the REMAINDER goes to
        # the one-time list — so a product is never counted twice.
        n, regular_count = db.compute_suggested_n(total)
        reserve_n = self._shared_reserve()
        in_dist_count = len(self._rows_data)
        picked = min(n, in_dist_count)
        reserve_picked = max(0, min(reserve_n, in_dist_count - picked))
        self._populate(suggested_n=n, reserve_n=reserve_n)
        msg = f"מוצרים זמינים: {total}\n"
        if regular_count:
            msg += f"קבועים שנצרכים קודם: {regular_count}  →  נשאר לחד-פעמיים: {n}\n"
        msg += (
            f"\nסומנו {picked} עיקריים + {reserve_picked} רזרבה — לפי סדר עדיפות\n"
            f"(ראשונה קודם, אחר כך שנייה, ובתוך כל דרגה לפי ניקוד הצורך)."
        )
        if n > in_dist_count:
            msg += (f"\n\n⚠ נשארו יותר מוצרים ({n}) ממועמדי העדיפות ({in_dist_count}). "
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
            # Records the picks (persisted so they survive restart) and refreshes.
            added = gt.add_one_time_picks(selected)
            self.main_win.tabs.setCurrentWidget(gt)
            self.main_win.status_msg(f"נוספו {added} חד-פעמיים לרשימת החלוקה")

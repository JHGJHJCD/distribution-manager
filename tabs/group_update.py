from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QLineEdit,
    QSpinBox, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from datetime import date
from widgets import DateEdit
import database as db
from utils.backup import auto_backup_async
from utils.excel_utils import export_distribution_to_excel, export_full_distribution_to_excel
from utils.print_view import print_distribution_list
from utils.ui import busy_cursor, attach_empty_state, refresh_empty_state
from styles import (OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG,
                    SELECTED_BG, SELECTED_FG)

# colours for one-time picks (+ reserve)
_RESERVE_BG, _RESERVE_FG = "#ede7f6", "#5e35b1"
_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"


def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""


# Merged tab: viewing the week's list AND checking who received + recording it.
COLS = ["✔", "שם מלא", "טלפון 1", "טלפון 2", "טלפון 3", "אזור",
        "תדירות", "חלוקה הבאה", "נפשות", "הערות"]
_COL_SOULS = 8
_COL_NOTES = 9

SCOPE_WEEK = "חלוקת השבוע"
SCOPE_ALL = "כל הקבועים"


class GroupUpdateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._rows_data = []
        self._extra_ids: set = set()     # one-time picks added from the one-time tab
        self._reserve_ids: set = set()   # which of those are reserves
        self._load_extras()
        self._build_ui()
        self.refresh()

    # ── one-time-pick persistence (survive restart + save) ─────────────────────
    def _load_extras(self):
        def _parse(key):
            raw = db.get_setting(key) or ""
            return {int(x) for x in raw.split(",") if x.strip().isdigit()}
        self._extra_ids = _parse("weekly_extra_ids")
        self._reserve_ids = _parse("weekly_reserve_ids")

    def _persist_extras(self):
        db.set_setting("weekly_extra_ids", ",".join(str(i) for i in sorted(self._extra_ids)))
        db.set_setting("weekly_reserve_ids", ",".join(str(i) for i in sorted(self._reserve_ids)))

    def add_one_time_picks(self, recs: list) -> int:
        """Called by the one-time tab. Records picks (persisted) and refreshes."""
        added = 0
        for rec in recs:
            rid = rec.get("id")
            if rid is None:
                continue
            if rid not in self._extra_ids:
                added += 1
            self._extra_ids.add(rid)
            if rec.get("_reserve"):
                self._reserve_ids.add(rid)
            else:
                self._reserve_ids.discard(rid)
        self._persist_extras()
        self.refresh()
        return added

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("חלוקה ורישום — רשימת החלוקה")
        title.setObjectName("title")
        lay.addWidget(title)

        # Distribution details — panel card (needed to record a distribution)
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

        details_row.addWidget(_lbl("שם החלוקה:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("לדוגמה: חלוקת פסח")
        self.name_input.setMinimumWidth(150)
        self.name_input.setToolTip("שם/מטרת החלוקה — חובה למלא לפני הדפסה")
        details_row.addWidget(self.name_input, 2)

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

        # Filter row — scope toggle + area filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(_lbl("הצג:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([SCOPE_WEEK, SCOPE_ALL])
        self.scope_combo.setToolTip("חלוקת השבוע = מי שאמור לקבל השבוע · כל הקבועים = כל המקבלים הקבועים")
        self.scope_combo.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.scope_combo)

        filter_row.addWidget(_lbl("אזור:"))
        self.area_combo = QComboBox()
        self.area_combo.currentTextChanged.connect(self.refresh)
        filter_row.addWidget(self.area_combo)
        self._reload_areas()

        # legend
        for color, text in [(SELECTED_FG, "● חד-פעמי"), (_RESERVE_FG, "● רזרבה")]:
            l = QLabel(text); l.setStyleSheet(f"color:{color};")
            filter_row.addWidget(l)

        filter_row.addStretch()
        self.lbl_total = QLabel("סה\"כ ברשימה: 0")
        self.lbl_checked = QLabel("סומנו: 0")
        self.lbl_souls = QLabel("נפשות: 0")
        for lbl in [self.lbl_total, self.lbl_checked, self.lbl_souls]:
            lbl.setObjectName("subtitle")
            filter_row.addWidget(lbl)

        btn_check_all = QPushButton("בחר הכל")
        btn_check_all.setObjectName("neutral")
        btn_check_all.setStyleSheet(_SMALL_BTN)
        btn_check_all.clicked.connect(self._check_all)
        filter_row.addWidget(btn_check_all)

        btn_uncheck_all = QPushButton("בטל הכל")
        btn_uncheck_all.setObjectName("neutral")
        btn_uncheck_all.setStyleSheet(_SMALL_BTN)
        btn_uncheck_all.clicked.connect(self._uncheck_all)
        filter_row.addWidget(btn_uncheck_all)

        lay.addLayout(filter_row)

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
        attach_empty_state(self.table, "אין מקבלים להצגה")

        # Bottom buttons
        bot = QHBoxLayout()
        bot.setSpacing(8)

        btn_save = QPushButton("שמור חלוקה למעקב")
        btn_save.setObjectName("primary")
        btn_save.setMinimumHeight(34)
        btn_save.setToolTip("שמור את הסימונים כחלוקה מבוצעת ועדכן תאריכים")
        btn_save.clicked.connect(self._save)
        bot.addWidget(btn_save)

        btn_export = QPushButton("ייצא ל-Excel")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet(_SMALL_BTN)
        btn_export.setToolTip("ייצא רשימה בסיסית (המסומנים, או הכל אם אין סימון)")
        btn_export.clicked.connect(self._export_excel)
        bot.addWidget(btn_export)

        btn_export_full = QPushButton("ייצוא מלא לאקסל")
        btn_export_full.setObjectName("success")
        btn_export_full.setStyleSheet(_SMALL_BTN)
        btn_export_full.setToolTip("ייצוא כל פרטי המקבל למי שסומן שקיבל (חובה לסמן ✔ תחילה)")
        btn_export_full.clicked.connect(self._export_full)
        bot.addWidget(btn_export_full)

        btn_print = QPushButton("הדפסה")
        btn_print.setObjectName("neutral")
        btn_print.setStyleSheet(_SMALL_BTN)
        btn_print.setToolTip("הדפס רשימת חלוקה (A4 לאורך)")
        btn_print.clicked.connect(self._print)
        bot.addWidget(btn_print)

        bot.addStretch()
        lay.addLayout(bot)

    def _reload_areas(self):
        prev = self.area_combo.currentText() if self.area_combo.count() else "הכל"
        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        self.area_combo.addItem("הכל")
        for a in db.get_areas():
            self.area_combo.addItem(a)
        idx = self.area_combo.findText(prev)
        self.area_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.area_combo.blockSignals(False)

    # ── data ───────────────────────────────────────────────────────────────────
    def _extra_recipients(self, area: str, base_ids: set) -> list:
        """Fetch the persisted one-time picks from the DB (so they survive
        restart), area-filtered, excluding any already in the base list."""
        out = []
        for rid in self._extra_ids:
            if rid in base_ids:
                continue
            rec = db.get_recipient(rid)
            if not rec:
                continue
            if area != "הכל" and (rec.get("area") or "") != area:
                continue
            rec = dict(rec)
            rec["_reserve"] = rid in self._reserve_ids
            out.append(rec)
        return out

    def refresh(self):
        self._reload_areas()
        area = self.area_combo.currentText() or "הכל"
        scope = self.scope_combo.currentText() if hasattr(self, "scope_combo") else SCOPE_WEEK

        if scope == SCOPE_ALL:
            base = [r for r in db.get_all_recipients(status_filter="פעיל")
                    if (r.get("frequency") or "") not in ("", "חד-פעמי")
                    and (area == "הכל" or (r.get("area") or "") == area)]
        else:  # nearest week
            base = db.get_weekly_list(area_filter=area)

        base_ids = {r["id"] for r in base}
        extras = self._extra_recipients(area, base_ids)
        self._rows_data = base + extras
        self._populate()

    def _row_style(self, rec: dict):
        """Return (bg, fg, freq_disp, next_disp) for a row."""
        rid = rec.get("id")
        freq = rec.get("frequency", "") or ""
        is_pick = rid in self._extra_ids or freq == "חד-פעמי"
        if is_pick:
            if rec.get("_reserve") or rid in self._reserve_ids:
                return QColor(_RESERVE_BG), QColor(_RESERVE_FG), "חד-פעמי · רזרבה", ""
            return QColor(SELECTED_BG), QColor(SELECTED_FG), "חד-פעמי", ""
        # regular — colour by urgency
        nd = rec.get("next_distribution") or ""
        days_left = rec.get("days_left")
        if days_left is None and nd:
            try:
                days_left = (date.fromisoformat(nd) - date.today()).days
            except ValueError:
                days_left = None
        if days_left is not None and days_left < 0:
            bg, fg = QColor(OVERDUE_BG), QColor(OVERDUE_FG)
        elif days_left is not None and days_left <= 1:
            bg, fg = QColor(TODAY_BG), QColor(TODAY_FG)
        else:
            bg, fg = QColor(WEEK_BG), QColor(WEEK_FG)
        return bg, fg, freq, _fdate(nd)

    def _populate(self):
        # Preserve the operator's current check marks across a rebuild (refresh
        # fires on every scope/area change). Otherwise a pick that was unchecked
        # would be silently re-checked and could be recorded by mistake.
        prev = {}
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                prev[it.data(Qt.ItemDataRole.UserRole)] = it.checkState()

        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows_data))
        for r, rec in enumerate(self._rows_data):
            bg, fg, freq_disp, next_disp = self._row_style(rec)
            rid = rec.get("id")

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            # Keep a row's existing mark if we've seen it before; a freshly-added
            # one-time pick (not seen yet) arrives PRE-CHECKED, regulars unchecked.
            if rid in prev:
                chk.setCheckState(prev[rid])
            else:
                chk.setCheckState(Qt.CheckState.Checked if rid in self._extra_ids
                                  else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
            self.table.setItem(r, 0, chk)

            vals = [rec.get("full_name", ""), rec.get("phone1", ""),
                    rec.get("phone2", ""), rec.get("phone3", ""),
                    rec.get("area", ""), freq_disp, next_disp,
                    str(rec.get("souls", "") or ""), ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setBackground(bg)
                item.setForeground(fg)
                col = c + 1
                if col != _COL_NOTES:   # everything but notes is read-only
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:   # name — bold
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, col, item)

        self.table.blockSignals(False)
        self._update_counts()
        refresh_empty_state(self.table)

    def _update_counts(self):
        total = self.table.rowCount()
        checked = 0
        souls = 0
        for r in range(total):
            chk = self.table.item(r, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                checked += 1
                souls_item = self.table.item(r, _COL_SOULS)
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
                    notes_item = self.table.item(r, _COL_NOTES)
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

        # The one-time picks have now been distributed — drop them so they aren't
        # shown or re-saved next time. Persist the cleared state.
        self._extra_ids.clear()
        self._reserve_ids.clear()
        self._persist_extras()

        msg = f"נשמרה חלוקה ל-{len(checked)} מקבלים"
        QMessageBox.information(self, "הצלחה", msg)

        if self.main_win:
            self.main_win.status_msg(msg)
            self.main_win.refresh_all()

    def _get_export_rows(self):
        """Rows to export/print: the checked set if any, else the whole list."""
        checked = self._get_checked_recipients()
        return checked if checked else list(self._rows_data)

    def _export_excel(self):
        checked = self._get_export_rows()
        dist_date = _fdate(self.date_edit.get_iso())
        try:
            with busy_cursor():
                path = export_distribution_to_excel(checked, dist_date)
            QMessageBox.information(self, "ייצוא הושלם", f"הקובץ נשמר:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    def _export_full(self):
        # The full export certifies who RECEIVED — so it requires the operator to
        # tick the ✔ column first. Without any marks it is blocked (unlike the
        # basic export, which falls back to the whole list).
        rows = self._get_checked_recipients()
        if not rows:
            QMessageBox.warning(
                self, "לא סומן מי קיבל",
                "הייצוא המלא מאשר מי קיבל חלוקה.\n"
                "יש לסמן תחילה בעמודת ✔ את מי שקיבל, ואז לייצא.")
            return
        dist_date = _fdate(self.date_edit.get_iso())
        try:
            with busy_cursor():
                path = export_full_distribution_to_excel(rows, dist_date)
            QMessageBox.information(self, "ייצוא הושלם", f"הקובץ (עם כל הפרטים) נשמר:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    def _print(self):
        name = self.name_input.text().strip()
        if not name:
            self.name_input.setStyleSheet(
                "border: 2px solid #dc2626; background-color:#fff5f5;")
            self.name_input.setToolTip("חובה לרשום שם חלוקה לפני הדפסה")
            QMessageBox.warning(
                self, "חסר שם חלוקה",
                "יש לרשום שם חלוקה (למשל 'חלוקת פסח') בשדה 'שם החלוקה' לפני ההדפסה.")
            self.name_input.setFocus()
            return
        self.name_input.setStyleSheet("")
        self.name_input.setToolTip("שם/מטרת החלוקה — חובה למלא לפני הדפסה")
        checked = self._get_export_rows()
        dist_date = _fdate(self.date_edit.get_iso())
        print_distribution_list(checked, dist_date, self, dist_name=name)

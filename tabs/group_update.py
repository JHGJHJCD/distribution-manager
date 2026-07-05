import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QLineEdit,
    QSpinBox, QMessageBox, QAbstractItemView, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from datetime import date
from widgets import DateEdit
import database as db
from utils.backup import auto_backup_async
from utils.excel_utils import (export_distribution_to_excel, export_full_distribution_to_excel,
                               export_volunteer_checklist_to_excel, import_volunteer_checklist)
from utils.print_view import print_distribution_list
from utils.ui import busy_cursor, attach_empty_state, refresh_empty_state, ALIGN_RIGHT
from utils import email_utils
from styles import (OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG,
                    SELECTED_BG, SELECTED_FG)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

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

    # ── remembered names for quick fill (distributor / distribution name) ──────
    _HIST_MAX = 15

    def _load_history(self, key: str) -> list:
        raw = db.get_setting(key) or ""
        return [x for x in raw.split("\n") if x.strip()]

    def _push_history(self, key: str, value: str):
        value = (value or "").strip()
        if not value:
            return
        hist = [value] + [x for x in self._load_history(key) if x != value]
        db.set_setting(key, "\n".join(hist[:self._HIST_MAX]))

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
        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name_input.setMinimumWidth(150)
        self.name_input.lineEdit().setPlaceholderText("לדוגמה: חלוקת פסח")
        self.name_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.name_input.setToolTip("שם/מטרת החלוקה — חובה למלא לפני הדפסה. אפשר לבחור משמות קודמים.")
        self.name_input.addItems(self._load_history("dist_names_history"))
        self.name_input.setCurrentText("")
        details_row.addWidget(self.name_input, 2)

        details_row.addWidget(_lbl("תאריך:"))
        self.date_edit = DateEdit(allow_empty=False)
        self.date_edit.setMinimumWidth(130)
        self.date_edit.setToolTip("תאריך ביצוע החלוקה — ימי רביעי מסומנים בכחול")
        details_row.addWidget(self.date_edit)

        details_row.addWidget(_lbl("מה חולק:"))
        self.what_input = QLineEdit()
        self.what_input.setPlaceholderText("סל מזון, עוף, ...")
        self.what_input.setAlignment(ALIGN_RIGHT)
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
        self.dist_input = QComboBox()
        self.dist_input.setEditable(True)
        self.dist_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.dist_input.setMinimumWidth(130)
        self.dist_input.lineEdit().setPlaceholderText("שם המחלק")
        self.dist_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.dist_input.setToolTip("שם האדם שביצע את החלוקה — נזכר ומוצע אוטומטית")
        self.dist_input.addItems(self._load_history("distributors_history"))
        self.dist_input.setCurrentText(db.get_setting("last_distributor") or "")
        details_row.addWidget(self.dist_input, 1)

        lay.addWidget(details_card)

        # Volunteer card — send the current list to a volunteer to fill by email
        # (they never touch the app), and import their filled results back.
        vol_card = QWidget()
        vol_card.setObjectName("volunteer-card")
        vol_card.setStyleSheet(
            "QWidget#volunteer-card { background:#f5f3ff; border:1px solid #ddd6fe; border-radius:8px; }"
        )
        vol_row = QHBoxLayout(vol_card)
        vol_row.setSpacing(10)
        vol_row.setContentsMargins(12, 7, 12, 7)

        def _vlbl(text):
            l = QLabel(text)
            l.setStyleSheet("font-weight:700; color:#5b21b6; background:transparent; border:none;")
            return l

        vol_row.addWidget(_vlbl("שליחה למתנדב:"))
        self.volunteer_email_input = QComboBox()
        self.volunteer_email_input.setEditable(True)
        self.volunteer_email_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.volunteer_email_input.setMinimumWidth(180)
        self.volunteer_email_input.lineEdit().setPlaceholderText("אימייל המתנדב")
        self.volunteer_email_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.volunteer_email_input.setToolTip("כתובת המייל של המתנדב שימלא את הרשימה")
        self.volunteer_email_input.addItems(self._load_history("volunteer_emails_history"))
        self.volunteer_email_input.setCurrentText("")
        vol_row.addWidget(self.volunteer_email_input, 1)

        btn_send_vol = QPushButton("שלח למתנדב למילוי")
        btn_send_vol.setObjectName("primary")
        btn_send_vol.setStyleSheet(_SMALL_BTN)
        btn_send_vol.setToolTip("שולח למתנדב במייל קובץ מעוצב עם הרשימה, למילוי בלי לגעת בתוכנה")
        btn_send_vol.clicked.connect(self._send_to_volunteer)
        vol_row.addWidget(btn_send_vol)

        btn_import_vol = QPushButton("ייבוא תוצאות ממתנדב")
        btn_import_vol.setObjectName("neutral")
        btn_import_vol.setStyleSheet(_SMALL_BTN)
        btn_import_vol.setToolTip("בחר את קובץ ה-Excel שהמתנדב מילא והחזיר — יירשם ישירות להיסטוריה")
        btn_import_vol.clicked.connect(self._import_volunteer_results)
        vol_row.addWidget(btn_import_vol)

        lay.addWidget(vol_card)

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

        btn_save = QPushButton("שמור חלוקה למעקב + ייצוא לאקסל")
        btn_save.setObjectName("primary")
        btn_save.setMinimumHeight(34)
        btn_save.setToolTip("רושם את החלוקה למעקב ומייצא אוטומטית אקסל מלא לתיקיית ההורדות")
        btn_save.clicked.connect(self._save)
        bot.addWidget(btn_save)

        btn_export = QPushButton("ייצא ל-Excel (רשימה קצרה)")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet(_SMALL_BTN)
        btn_export.setToolTip("ייצא רשימה בסיסית (המסומנים, או הכל אם אין סימון)")
        btn_export.clicked.connect(self._export_excel)
        bot.addWidget(btn_export)

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
                item.setTextAlignment(ALIGN_RIGHT)
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
        distributor = self.dist_input.currentText().strip()
        dist_name   = self.name_input.currentText().strip()

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
            self.dist_input.setToolTip("שם האדם שביצע את החלוקה — נזכר ומוצע אוטומטית")
        if errors:
            QMessageBox.warning(self, "שדות חסרים", "• " + "\n• ".join(errors))
            return

        export_path = None
        export_err = None
        with busy_cursor():
            db.bulk_add_distributions(checked, dist_date, what, qty, distributor)
            auto_backup_async()
            # Merged action: also export a full Excel (of who received) to Downloads.
            try:
                export_path = export_full_distribution_to_excel(
                    checked, _fdate(dist_date), dist_name)
            except Exception as e:
                export_err = str(e)

        # Remember the distributor + distribution name and refresh the suggestions.
        db.set_setting("last_distributor", distributor)
        self._push_history("distributors_history", distributor)
        self._push_history("dist_names_history", dist_name)
        self._reload_name_history()

        # One-time picks distributed — drop them so they aren't re-saved next time.
        self._extra_ids.clear()
        self._reserve_ids.clear()
        self._persist_extras()

        msg = f"נשמרה חלוקה ל-{len(checked)} מקבלים."
        if export_path:
            msg += f"\n\nקובץ אקסל מלא נשמר בתיקיית ההורדות:\n{export_path}"
        elif export_err:
            msg += f"\n\n⚠ הרישום נשמר, אך ייצוא האקסל נכשל:\n{export_err}"
        QMessageBox.information(self, "הצלחה", msg)

        if self.main_win:
            self.main_win.status_msg(f"נשמרה חלוקה ל-{len(checked)} מקבלים")
            self.main_win.refresh_all()

    def _reload_name_history(self):
        """Refresh the dropdown suggestions of the distributor + name combos,
        keeping whatever text is currently typed."""
        for combo, key in ((self.dist_input, "distributors_history"),
                           (self.name_input, "dist_names_history")):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._load_history(key))
            combo.setCurrentText(cur)
            combo.blockSignals(False)

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

    # ── send list to a volunteer by email / import their filled results ────────

    def _send_to_volunteer(self):
        dist_name   = self.name_input.currentText().strip()
        what        = self.what_input.text().strip()
        distributor = self.dist_input.currentText().strip()
        to_addr     = self.volunteer_email_input.currentText().strip()

        _ERR = "border: 2px solid #dc2626; background-color: #fff5f5;"
        errors = []
        for widget, val, label in (
            (self.name_input, dist_name, "שם החלוקה"),
            (self.what_input, what, "מה חולק"),
            (self.dist_input, distributor, "שם המחלק"),
        ):
            if not val:
                widget.setStyleSheet(_ERR)
                errors.append(f"{label}: שדה חובה")
            else:
                widget.setStyleSheet("")
        if not to_addr:
            self.volunteer_email_input.setStyleSheet(_ERR)
            errors.append("אימייל מתנדב: שדה חובה")
        elif not _EMAIL_RE.match(to_addr):
            self.volunteer_email_input.setStyleSheet(_ERR)
            errors.append("אימייל מתנדב: כתובת לא תקינה")
        else:
            self.volunteer_email_input.setStyleSheet("")
        if errors:
            QMessageBox.warning(self, "שדות חסרים", "• " + "\n• ".join(errors))
            return

        if not email_utils.is_configured():
            QMessageBox.warning(
                self, "שליחת מייל לא הוגדרה",
                "יש להגדיר תחילה כתובת מייל שולח וסיסמת אפליקציה בלשונית הגדרות.")
            return

        if not self._rows_data:
            QMessageBox.information(self, "", "אין מקבלים ברשימה לשליחה")
            return

        if self._dispatch_volunteer_email(to_addr, dist_name, what, distributor):
            QMessageBox.information(self, "נשלח", f"הרשימה נשלחה למתנדב בהצלחה ל-{to_addr}.")

    def _dispatch_volunteer_email(self, to_addr, dist_name, what, distributor) -> bool:
        """Build the volunteer checklist and email it. Returns True on success.
        Shared by the 'שלח למתנדב' button and the post-print prompt."""
        dist_date_iso = self.date_edit.get_iso()
        dist_date_disp = _fdate(dist_date_iso)
        qty = self.qty_spin.value()
        try:
            with busy_cursor():
                # Store the ISO date (not the dd/mm/yyyy display string) so a
                # later import can hand it straight to bulk_add_distributions /
                # calculate_next_dist, which require ISO format.
                path = export_volunteer_checklist_to_excel(
                    self._rows_data, dist_date_iso, dist_name, what, qty, distributor)
                html = (
                    "<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
                    "<div style='text-align:center;margin-bottom:10px;'>"
                    "<img src='cid:logo' style='max-width:160px;'></div>"
                    f"<p>שלום {distributor},</p>"
                    f"<p>מצורפת רשימת החלוקה \"<b>{dist_name}</b>\" מתאריך {dist_date_disp}.</p>"
                    "<p>נא לסמן ליד כל שם אם הגיע (\"כן\"/\"לא\"), ניתן להוסיף הערה לכל אחד, "
                    "ובסוף למלא הערה כללית על החלוקה בקובץ עצמו.</p>"
                    "<p>לאחר המילוי — נא לשלוח את הקובץ המצורף בחזרה למייל הזה.</p>"
                    "<p style='color:#6b7280;font-size:12px;'>תודה על ההתנדבות!</p>"
                    "</div>"
                )
                from utils.print_view import _resource_path
                import os
                logo_path = _resource_path("org_logo.png")
                email_utils.send_email(
                    to_addr, subject=f"רשימת חלוקה — {dist_name} ({dist_date_disp})",
                    html_body=html, attachment_path=path,
                    inline_logo_path=logo_path if os.path.exists(logo_path) else None,
                )
        except Exception as e:
            QMessageBox.critical(self, "שגיאת שליחה", f"השליחה נכשלה:\n{e}")
            return False

        self._push_history("volunteer_emails_history", to_addr)
        self.volunteer_email_input.blockSignals(True)
        self.volunteer_email_input.clear()
        self.volunteer_email_input.addItems(self._load_history("volunteer_emails_history"))
        self.volunteer_email_input.setCurrentText(to_addr)
        self.volunteer_email_input.blockSignals(False)
        return True

    def _import_volunteer_results(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ שחזר מהמתנדב", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            with busy_cursor():
                result = import_volunteer_checklist(path)
        except Exception as e:
            QMessageBox.critical(self, "שגיאה בקריאת הקובץ", str(e))
            return

        received = result["received"]
        unmatched = result["unmatched"]
        meta = result["meta"]

        if not received:
            msg = "לא נמצא אף מקבל שסומן \"כן\" בקובץ."
            if unmatched:
                msg += f"\n\n⚠ {len(unmatched)} שורות לא זוהו: " + ", ".join(unmatched[:10])
            QMessageBox.information(self, "אין מה לייבא", msg)
            return

        summary = (
            f"חלוקה: {meta.get('dist_name') or '—'}\n"
            f"תאריך: {meta.get('dist_date') or '—'}\n"
            f"מה חולק: {meta.get('what') or '—'}  ·  מחלק: {meta.get('distributor') or '—'}\n\n"
            f"יירשמו {len(received)} חלוקות שסומנו כ'הגיע'."
        )
        if meta.get("general_note"):
            summary += f"\n\nהערה כללית מהמתנדב: {meta['general_note']}"
        if unmatched:
            summary += (f"\n\n⚠ {len(unmatched)} שורות לא זוהו ולא ייובאו: "
                       + ", ".join(unmatched[:10]))
        summary += "\n\nלאשר ייבוא להיסטוריה?"

        reply = QMessageBox.question(
            self, "אישור ייבוא", summary,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        general_suffix = (f" | הערה כללית: {meta['general_note']}"
                          if meta.get("general_note") else "")
        records = []
        for r in received:
            rec = dict(r)
            rec["notes"] = (r.get("notes") or "") + general_suffix
            records.append(rec)

        with busy_cursor():
            db.bulk_add_distributions(
                records, meta.get("dist_date") or self.date_edit.get_iso(),
                meta.get("what") or "", meta.get("qty") or 0,
                meta.get("distributor") or "")
            auto_backup_async()

        QMessageBox.information(
            self, "הצלחה", f"נרשמו {len(records)} חלוקות מהמתנדב להיסטוריה ✓")
        if self.main_win:
            self.main_win.status_msg(f"יובאו {len(records)} חלוקות ממתנדב")
            self.main_win.refresh_all()

    def _print(self):
        name = self.name_input.currentText().strip()
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
        self.name_input.setToolTip("שם/מטרת החלוקה — חובה למלא לפני הדפסה. אפשר לבחור משמות קודמים.")
        # Remember the name typed for print too, so it's suggested next time.
        self._push_history("dist_names_history", name)
        checked = self._get_export_rows()
        dist_date = _fdate(self.date_edit.get_iso())
        print_distribution_list(checked, dist_date, self, dist_name=name)

        # After printing, offer to also email the list to the volunteer — but only
        # when email is set up and a volunteer address is present (else stay quiet).
        to_addr = self.volunteer_email_input.currentText().strip()
        if email_utils.is_configured() and to_addr and _EMAIL_RE.match(to_addr):
            what = self.what_input.text().strip()
            distributor = self.dist_input.currentText().strip()
            if not what or not distributor:
                return   # can't build a proper email without these; skip silently
            reply = QMessageBox.question(
                self, "שליחה למתנדב",
                f"לשלוח את הרשימה גם למתנדב במייל ({to_addr})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self._dispatch_volunteer_email(to_addr, name, what, distributor):
                    QMessageBox.information(self, "נשלח", f"הרשימה נשלחה למתנדב ל-{to_addr}.")

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QLabel, QComboBox,
    QDialog, QFormLayout, QMessageBox, QFileDialog, QSpinBox,
    QTextEdit, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, QDate, QTimer
from widgets import DateEdit
from PyQt6.QtGui import QColor
from collections import Counter
import re
from pathlib import Path
import database as db
from styles import SUSPENDED_FG, ENDED_FG

# ── Validation helpers ────────────────────────────────────────────────────────
_ERR_STYLE = "border: 2px solid #dc2626; background-color: #fff5f5;"
_RE_PHONE  = re.compile(r'^0\d{8,9}$')

def _phone_valid(raw: str) -> bool:
    """9-10 digit Israeli number starting with 0 (strips spaces/dashes)."""
    raw = raw.strip()
    if not raw:
        return True
    return bool(_RE_PHONE.match(re.sub(r'[\s\-()+]', '', raw)))

def _mark(widget, error: bool, tip: str = ""):
    widget.setStyleSheet(_ERR_STYLE if error else "")
    widget.setToolTip(tip if error else "")

def _fdate(s: str) -> str:
    """'2026-06-03' → '03/06/2026'"""
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""
from utils.backup import auto_backup_async, auto_backup
from utils.excel_utils import import_from_excel, _FULL_FIELDS

# key → Hebrew label for the import-review dialog (reuses the export labels).
_FIELD_LABELS = {k: v for k, v in _FULL_FIELDS}


class ImportReviewDialog(QDialog):
    """Single summary of an import before it's applied (#hlcmj). Lists how many
    brand-new recipients will be added, and shows every proposed CHANGE to an
    existing recipient as one checkable row (name + field: old → new). All rows
    are checked by default; the operator unchecks any change to skip. One
    confirmation applies everything selected — no per-recipient prompts."""

    def __init__(self, diff: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("אישור ייבוא — מה ישתנה")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(720, 560)
        self._diff = diff
        self._rows = []   # (update_dict, field, checkbox_item_row)
        outer = QVBoxLayout(self)

        n_new = len(diff.get("new", []))
        n_upd = len(diff.get("updates", []))
        summary = QLabel(
            f"📥 <b>{n_new}</b> מקבלים חדשים יתווספו · "
            f"<b>{n_upd}</b> מקבלים קיימים עם שינויים מוצעים.")
        summary.setTextFormat(Qt.TextFormat.RichText)
        summary.setStyleSheet("font-size:13.5px; color:#0f172a;")
        outer.addWidget(summary)

        hint = QLabel("סמן אילו שינויים לבצע במקבלים הקיימים. מה שלא יסומן — יישאר "
                      "כפי שהוא. מקבלים חדשים נוספים תמיד. (שדה ריק בקובץ לעולם "
                      "לא מוחק נתון קיים.)")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        outer.addWidget(hint)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["בצע", "שם", "שדה", "שינוי"])
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        enable_touch_scroll(self._table)
        outer.addWidget(self._table, 1)
        self._fill_updates()

        row_btns = QHBoxLayout()
        btn_all = QPushButton("סמן הכל")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("נקה הכל")
        btn_none.clicked.connect(lambda: self._set_all(False))
        for b in (btn_all, btn_none):
            b.setStyleSheet("font-size:12px; padding:4px 12px;")
        row_btns.addWidget(btn_all)
        row_btns.addWidget(btn_none)
        row_btns.addStretch()
        outer.addLayout(row_btns)

        btns = QHBoxLayout()
        btn_ok = QPushButton("בצע ייבוא")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("ביטול")
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        outer.addLayout(btns)

    def _fmt(self, field, val):
        s = "" if val is None else str(val).strip()
        if field == "priority":
            return {4: "קבוע", 3: "עדיפות ראשונה", 2: "עדיפות שנייה"}.get(
                int(val) if str(val).strip().isdigit() else None, s or "—")
        return s or "—"

    def _fill_updates(self):
        updates = self._diff.get("updates", [])
        total = sum(len(u["changes"]) for u in updates)
        self._table.setRowCount(total)
        r = 0
        for u in updates:
            for field, ch in u["changes"].items():
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(Qt.CheckState.Checked)
                self._table.setItem(r, 0, chk)
                it_name = QTableWidgetItem(u["full_name"])
                it_field = QTableWidgetItem(_FIELD_LABELS.get(field, field))
                it_change = QTableWidgetItem(
                    f"{self._fmt(field, ch['old'])}  →  {self._fmt(field, ch['new'])}")
                for it in (it_name, it_field, it_change):
                    it.setTextAlignment(ALIGN_RIGHT)
                self._table.setItem(r, 1, it_name)
                self._table.setItem(r, 2, it_field)
                self._table.setItem(r, 3, it_change)
                self._rows.append((u["id"], field))
                r += 1

    def _set_all(self, checked: bool):
        st = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for r in range(self._table.rowCount()):
            self._table.item(r, 0).setCheckState(st)

    def selected_updates(self) -> list:
        """The updates the operator kept, in apply_import_confirmed's shape:
        [{'id', 'changes': {field: {'old','new'}}}]."""
        keep = {}
        for r, (rid, field) in enumerate(self._rows):
            if self._table.item(r, 0).checkState() == Qt.CheckState.Checked:
                ch = next(u["changes"][field] for u in self._diff["updates"]
                          if u["id"] == rid and field in u["changes"])
                keep.setdefault(rid, {})[field] = ch
        return [{"id": rid, "changes": chs} for rid, chs in keep.items()]
from utils.ui import (busy_cursor, attach_empty_state, refresh_empty_state,
                      BadgeDelegate, PRIORITY_BADGES, STATUS_BADGES, search_icon,
                      ALIGN_RIGHT, rtl_text_area, enable_touch_scroll,
                      apply_header_icons)

COLS = ["מס'", "שם מלא", "עדיפות", "טלפון 1", "טלפון 2", "טלפון 3",
        "כתובת", "אזור", "נפשות", "תדירות", "חלוקה אחרונה",
        "חלוקה הבאה", "סטטוס", "הערות",
        "מס' מזהה", "מקור", "ת. לידה", "ת. לידה בן/בת זוג",
        "ת.ז. בעל", "ת.ז. אשה",
        "ילדים בבית", "ילדים נשואים", "מספר ילדים",
        "מצב אישי", "אימייל", "בית כנסת",
        "הוצ' דיור", "הוצ' רפואיות", "הכנסות", "פנוי לנפש",
        "היקף משרה", "סוג הורה", "עיסוק בעל", "שם נציג"]

COL_KEYS = ["id", "full_name", "priority", "phone1", "phone2", "phone3",
            "address", "area", "souls", "frequency", "last_distribution",
            "next_distribution", "status", "notes",
            "external_id", "source", "birth_date", "spouse_birth_date",
            "id_number", "spouse_id_number",
            "children_home", "children_married", "children_total",
            "marital_status", "email", "synagogue",
            "housing_expenses", "medical_expenses", "income", "per_soul",
            "work_scope", "parent_type", "occupation", "representative"]

# Priority editor options: (display label, priority int | None, priority_raw).
# No raw numbers — those were only the original spreadsheet's codes. Codes 1/0
# carry no real meaning ("not in distribution"), so they are NOT offered here and
# a recipient imported as 1/0 simply shows no priority.
_PRIORITY_OPTIONS = [
    ("ללא",              None, ""),
    ("קבוע",             4,    "4"),
    ("עדיפות ראשונה",    3,    "3"),
    ("עדיפות שנייה",     2,    "2"),
    ("חובת בירור",       None, "חובת בירור"),
]


def _priority_display(rec: dict) -> str:
    """Short label for the recipients table priority cell — Hebrew status only,
    never the raw import code. Codes 1/0/none show as blank."""
    pr = rec.get("priority")
    labels = {4: "קבוע", 3: "ראשונה", 2: "שנייה"}
    if pr in labels:
        return labels[pr]
    raw = (rec.get("priority_raw") or "").strip()
    return "בירור" if "בירור" in raw else ""


def _clean_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 9:
        digits = "0" + digits
    return digits


def _import_quality_report(rows: list[dict]) -> dict:
    names = [str((row.get("full_name") or "")).strip() for row in rows if (row.get("full_name") or "").strip()]
    name_counts = Counter(names)
    missing_phone = 0
    missing_frequency = 0
    suspicious_phone = 0
    for row in rows:
        phones = [_clean_phone(row.get("phone1")), _clean_phone(row.get("phone2")), _clean_phone(row.get("phone3"))]
        if not any(phones):
            missing_phone += 1
        if not (row.get("frequency") or "").strip():
            missing_frequency += 1
        for phone in phones:
            if phone and len(phone) not in (9, 10, 11):
                suspicious_phone += 1
                break
    duplicates = [name for name, count in name_counts.items() if count > 1]
    return {
        "rows": len(rows),
        "missing_phone": missing_phone,
        "missing_frequency": missing_frequency,
        "suspicious_phone": suspicious_phone,
        "duplicate_names": duplicates,
    }


def _format_conflict(conflict: dict) -> str:
    return (
        f"שורה {conflict.get('row', '?')}: {conflict.get('full_name', '')}\n"
        f"סיבה: {conflict.get('reason', '')}\n"
        f"קיים: {conflict.get('existing_phone1', '')} | {conflict.get('existing_phone2', '')} | {conflict.get('existing_phone3', '')}\n"
        f"נכנס: {conflict.get('incoming_phone1', '')} | {conflict.get('incoming_phone2', '')} | {conflict.get('incoming_phone3', '')}"
    )


class RecipientsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        # Title + actions row
        top = QHBoxLayout()
        title = QLabel("רשימת מקבלים")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("חיפוש לפי שם...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.setMaximumWidth(220)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(lambda: self._filter_timer.start(220))
        top.addWidget(self.search_input)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["הכל", "פעיל", "מושהה", "הסתיים"])
        self.status_filter.currentTextChanged.connect(self.refresh)
        top.addWidget(self.status_filter)

        # Priority filter — map label → priority code (None = no filter)
        self.priority_filter = QComboBox()
        self._PRIORITY_FILTERS = [
            ("כל העדיפויות", None),
            ("קבוע", 4),
            ("עדיפות ראשונה", 3),
            ("עדיפות שנייה", 2),
        ]
        self.priority_filter.addItems([o[0] for o in self._PRIORITY_FILTERS])
        # Colour the dropdown options as rounded pills, same palette as the table's
        # priority badges, so each group is recognisable at a glance (#ld7lr).
        _prio_chip = {
            "קבוע":          PRIORITY_BADGES["קבוע"],
            "עדיפות ראשונה": PRIORITY_BADGES["ראשונה"],
            "עדיפות שנייה":  PRIORITY_BADGES["שנייה"],
        }
        self.priority_filter.setItemDelegate(
            BadgeDelegate(_prio_chip, self.priority_filter))
        self.priority_filter.currentTextChanged.connect(self.refresh)
        top.addWidget(self.priority_filter)

        btn_add = QPushButton("+ הוסף מקבל")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)

        # Match the 'הוסף מקבל' button's size and look — it used to be a smaller,
        # differently-styled button beside it, which read as out of place (#eiqat).
        btn_import = QPushButton("+ יבוא מ-Excel")
        btn_import.setObjectName("success")
        btn_import.setToolTip("ייבוא מקובץ Excel (פורמט תבנית ליהודה)")
        btn_import.clicked.connect(self._import_excel)
        top.addWidget(btn_import)

        lay.addLayout(top)

        # Count label
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        lay.addWidget(self.count_lbl)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        apply_header_icons(self.table)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        # פעולות המקבל (עריכה / הפעלה / השהיה / מחיקה) עברו לתפריט לחיצה-ימנית על
        # השורה (#wtfnh) — כדי לפנות את סרגל הכפתורים העמוס. סטטוס ניתן לשנות גם
        # בעריכה (לחיצה כפולה).
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # "שם מלא" — give it a generous fixed-but-resizable width so long names
        # are never clipped (Stretch got squeezed to nothing next to 30+ columns).
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # Sample only a few rows when auto-sizing columns. Default samples up to
        # 1000 rows × every column on each refresh — with thousands of recipients
        # that O(rows×cols) scan froze/crashed the app. A small precision keeps
        # the auto-fit look at constant cost.
        hdr.setResizeContentsPrecision(20)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(1, 230)   # roomy name column (see resize mode above)
        enable_touch_scroll(self.table)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "אין מקבלים להצגה")
        # coloured pill badges for priority + status columns
        self.table.setItemDelegateForColumn(2, BadgeDelegate(PRIORITY_BADGES, self.table))
        self.table.setItemDelegateForColumn(12, BadgeDelegate(STATUS_BADGES, self.table))

        # Bottom bar — the per-row action buttons (הפעל/השהה/מחק) were removed
        # (#wtfnh, redundant) and moved to a right-click menu on the row. What
        # stays: exporting the whole list (#thmir) and the duplicate check.
        bot = QHBoxLayout()
        bot.setSpacing(8)

        btn_export = QPushButton("ייצוא לאקסל")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet("font-size:11px; min-height:24px; min-width:0; padding:3px 12px;")
        btn_export.setToolTip("ייצוא כל רשימת המקבלים המוצגת לקובץ Excel בתיקיית ההורדות")
        btn_export.clicked.connect(self._export_excel)
        bot.addWidget(btn_export)

        bot.addStretch()

        btn_dup = QPushButton("בדיקת כפילויות")
        btn_dup.setObjectName("neutral")
        btn_dup.setStyleSheet("font-size:11px; min-height:24px; min-width:0; padding:3px 12px;")
        btn_dup.setToolTip("סריקת שמות/טלפונים כפולים")
        btn_dup.clicked.connect(self._open_dup_check)
        bot.addWidget(btn_dup)

        lay.addLayout(bot)

    def _show_row_menu(self, pos):
        """Right-click menu on a recipient row: edit / activate / suspend / delete.
        Replaces the old always-on button bar (#wtfnh)."""
        if self.table.rowAt(pos.y()) < 0:
            return
        menu = QMenu(self)
        act_edit    = menu.addAction("עריכה…")
        menu.addSeparator()
        act_activate = menu.addAction("הפעל")
        act_suspend  = menu.addAction("השהה")
        menu.addSeparator()
        act_delete   = menu.addAction("מחק")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._edit()
        elif chosen == act_activate:
            self._set_status("פעיל")
        elif chosen == act_suspend:
            self._set_status("מושהה")
        elif chosen == act_delete:
            self._delete()

    def _export_excel(self):
        """Export the currently displayed recipients list to an Excel file in
        Downloads (#thmir)."""
        from utils.excel_utils import export_recipients_to_excel
        from utils.ui import reveal_in_folder
        rows = getattr(self, "_rows_data", None) or []
        if not rows:
            QMessageBox.information(self, "", "אין מקבלים לייצוא")
            return
        try:
            with busy_cursor():
                path = export_recipients_to_excel(rows)
            reveal_in_folder(path)
            QMessageBox.information(self, "ייצוא הושלם",
                                    f"רשימת המקבלים נשמרה בתיקיית ההורדות ונפתחה התיקייה:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה בייצוא", str(e))

    def _open_dup_check(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        from tabs.review import ReviewTab
        dlg = QDialog(self)
        dlg.setWindowTitle("בדיקת נתונים — כפילויות")
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dlg.resize(900, 600)
        v = QVBoxLayout(dlg)
        rev = ReviewTab(self.main_win)   # main_win so its edit/delete refresh work
        rev.refresh()
        v.addWidget(rev)
        dlg.exec()
        self.refresh()   # a duplicate may have been deleted

        self._rows_data = []

    def refresh(self):
        sf = self.status_filter.currentText()
        status = sf if sf != "הכל" else None
        rows = db.get_all_recipients(status_filter=status)
        # Priority filter (in-memory) — match the selected priority code.
        pcode = next((c for label, c in self._PRIORITY_FILTERS
                      if label == self.priority_filter.currentText()), None)
        if pcode is not None:
            rows = [r for r in rows if r.get("priority") == pcode]
        self._rows_data = rows
        self._populate(self._rows_data)

    @staticmethod
    def _sv(rec: dict, key: str) -> str:
        v = rec.get(key, "")
        return str(v) if v not in (None, 0, "") else ""

    def _populate(self, rows):
        _SUSPENDED = QColor(SUSPENDED_FG)
        _ENDED     = QColor(ENDED_FG)
        _ALIGN     = ALIGN_RIGHT

        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            rec_id = rec.get("id")
            status = rec.get("status", "")
            color  = (_SUSPENDED if status == "מושהה"
                      else _ENDED if status == "הסתיים"
                      else None)
            sv = lambda key, _r=rec: self._sv(_r, key)

            vals = [str(rec_id or ""), rec.get("full_name", ""), _priority_display(rec),
                    rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", ""),
                    rec.get("address", ""), rec.get("area", ""),
                    str(rec.get("souls", "") or ""), rec.get("frequency", ""),
                    _fdate(rec.get("last_distribution", "")),
                    _fdate(rec.get("next_distribution", "")),
                    status, rec.get("notes", ""),
                    sv("external_id"), sv("source"),
                    _fdate(rec.get("birth_date", "")), _fdate(rec.get("spouse_birth_date", "")),
                    sv("id_number"), sv("spouse_id_number"),
                    sv("children_home"), sv("children_married"), sv("children_total"),
                    sv("marital_status"), sv("email"), sv("synagogue"),
                    sv("housing_expenses"), sv("medical_expenses"), sv("income"), sv("per_soul"),
                    sv("work_scope"), sv("parent_type"), sv("occupation"), sv("representative")]
            for c, v in enumerate(vals):
                # Skip empty cells — most of the 33 admin columns are blank for a
                # typical recipient, and an empty QTableWidgetItem still costs.
                # Column 0 always carries the row id, so it is never skipped.
                if not v and c != 0:
                    continue
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(_ALIGN)
                # The row id is only read back from column 0 (see _selected_id),
                # so tag just that cell instead of all 33 — saves ~32 setData
                # calls per row, which adds up to seconds on thousands of rows.
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, rec_id)
                if c == 1:   # name — bold everywhere
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                if color:
                    item.setForeground(color)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        self.count_lbl.setText(f"סה\"כ: {len(rows)} מקבלים")
        refresh_empty_state(self.table)

    def _apply_filter(self):
        text = self.search_input.text().strip().lower()
        if not text:
            self._populate(self._rows_data)
            return
        filtered = [r for r in self._rows_data if text in (r.get("full_name") or "").lower()]
        self._populate(filtered)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _add(self):
        dlg = RecipientDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            db.add_recipient(dlg.get_data())
            auto_backup_async()
            self.refresh()
            if self.main_win:
                self.main_win.refresh_all()
                self.main_win.status_msg("מקבל חדש נוסף")

    def _edit(self):
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        rec = db.get_recipient(rec_id)
        dlg = RecipientDialog(self, rec)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            db.update_recipient(rec_id, dlg.get_data())
            auto_backup_async()
            self.refresh()
            if self.main_win:
                self.main_win.refresh_all()
                self.main_win.status_msg("פרטי מקבל עודכנו")

    def _delete(self):
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        rec = db.get_recipient(rec_id)
        name = rec["full_name"] if rec else "?"
        reply = QMessageBox.question(
            self, "מחיקה", f"למחוק את {name}?\nפעולה זו אינה הפיכה!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                db.delete_recipient(rec_id)
                auto_backup_async()
                self.refresh()
                if self.main_win:
                    self.main_win.refresh_all()
                    self.main_win.status_msg(f"{name} נמחק")
            except ValueError as e:
                force_reply = QMessageBox.question(
                    self, "מחיקה כוללת היסטוריה",
                    f"{str(e)}\n\n⚠ האם למחוק את המקבל כולל כל ההיסטוריה?\n"
                    "פעולה זו אינה הפיכה!",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if force_reply == QMessageBox.StandardButton.Yes:
                    db.force_delete_recipient(rec_id)
                    auto_backup_async()
                    self.refresh()
                    if self.main_win:
                        self.main_win.refresh_all()
                        self.main_win.status_msg(f"{name} נמחק (כולל היסטוריה)")

    def _set_status(self, status: str):
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        db.update_recipient(rec_id, {"status": status})
        auto_backup_async()
        self.refresh()
        if self.main_win:
            self.main_win.refresh_all()
            self.main_win.status_msg(f"סטטוס שונה ל: {status}")

    def _import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר קובץ Excel", "", "Excel (*.xlsx *.xls)")
        if not path:
            return
        self._run_import(path)

    def _run_import(self, path: str):
        # Choose import mode: full replace vs merge into existing data.
        choice = QMessageBox.question(
            self, "אופן ייבוא",
            "להחליף את כל הנתונים הקיימים, או למזג עם הקיים?\n\n"
            "• כן  = החלפה מלאה (מוחק הכל ומייבא מחדש)\n"
            "• לא  = מיזוג (מוסיף חדשים; שינויים במקבלים קיימים — רק לאחר אישור)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        replace = (choice == QMessageBox.StandardButton.Yes)
        if not replace:
            self._run_merge_import(path)
            return
        if replace:
            confirm = QMessageBox.warning(
                self, "אישור החלפה מלאה",
                "כל המקבלים הקיימים יימחקו ויוחלפו בתוכן הקובץ.\n"
                "פעולה בלתי הפיכה — ייווצר גיבוי אוטומטי לפני המחיקה.\n\nלהמשיך?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        try:
            with busy_cursor():
                rows = import_from_excel(path)
                report = _import_quality_report(rows)
                if replace:
                    # Safety backup BEFORE wiping — into the durable safety_ bucket
                    # (not the routine one), so it can't be churned out by ordinary
                    # backups later (R2). Abort if it cannot be made.
                    if auto_backup(kind="safety") is not True:
                        raise RuntimeError(
                            "גיבוי הבטיחות נכשל — הייבוא בוטל כדי לא לאבד נתונים.")
                    db.reset_all_data()
                    # Insert everything (keep duplicates for the review tab).
                    added = db.bulk_insert_recipients(rows)
                    updated, conflicts = 0, []
                else:
                    added, updated, conflicts = db.import_recipients_from_list(rows)
                auto_backup_async()
                self.refresh()
            dup = len(report["duplicate_names"])
            msg = f"{'(החלפה מלאה) ' if replace else ''}\nנוספו {added} מקבלים חדשים\n"
            if not replace:
                msg += (f"עודכנו {updated} מקבלים קיימים\n"
                        f"נמצאו {len(conflicts)} התנגשויות ייבוא\n")
            msg += (f"\nבדיקת איכות קובץ:\n"
                    f"• חסרי טלפון: {report['missing_phone']}\n"
                    f"• חסרי תדירות: {report['missing_frequency']}\n"
                    f"• טלפון חשוד: {report['suspicious_phone']}\n"
                    f"• שמות כפולים בקובץ: {dup}")
            if replace and dup:
                msg += "\n\nℹ הכפילויות נשמרו — בדוק ונקה אותן בלשונית 'בדיקת נתונים'."
            QMessageBox.information(self, "ייבוא הושלם", msg)
            if conflicts:
                conflict_preview = "\n\n".join(_format_conflict(c) for c in conflicts[:10])
                if len(conflicts) > 10:
                    conflict_preview += f"\n\nועוד {len(conflicts) - 10} התנגשויות..."
                QMessageBox.warning(self, "התנגשויות ייבוא", conflict_preview)
            if self.main_win:
                self.main_win.status_msg(f"ייבוא הושלם: {added} נוספו")
                self.main_win.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "שגיאה ביבוא", str(e))

    def _run_merge_import(self, path: str):
        """Merge import with a single review-and-confirm step (#hlcmj): parse the
        file (auto-detects the app's own export or the source template), compute
        the exact changes to existing recipients, and let the operator approve
        them in one summary dialog. New recipients are always added."""
        try:
            with busy_cursor():
                rows = import_from_excel(path)
                diff = db.diff_incoming_recipients(rows)
        except Exception as e:
            QMessageBox.critical(self, "שגיאה ביבוא", str(e))
            return
        n_new, n_upd = len(diff["new"]), len(diff["updates"])
        if not n_new and not n_upd:
            QMessageBox.information(self, "ייבוא", "אין נתונים חדשים או שינויים — "
                                    "הקובץ תואם למידע הקיים.")
            return
        dlg = ImportReviewDialog(diff, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.selected_updates()
        try:
            with busy_cursor():
                auto_backup_async()
                added, updated = db.apply_import_confirmed(diff["new"], updates)
                self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "שגיאה ביבוא", str(e))
            return
        extra = (f"\n\nℹ {diff['unmatched_dupes']} רשומות דולגו — שם כפול "
                 "בתוכנה, לא ברור למי לשייך.") if diff.get("unmatched_dupes") else ""
        QMessageBox.information(
            self, "ייבוא הושלם",
            f"נוספו {added} מקבלים חדשים.\nעודכנו {updated} מקבלים קיימים." + extra)
        if self.main_win:
            self.main_win.status_msg(f"ייבוא: {added} נוספו, {updated} עודכנו")
            self.main_win.refresh_all()


# ─── Add/Edit dialog ──────────────────────────────────────────────────────────

class RecipientDialog(QDialog):
    def __init__(self, parent=None, rec: dict = None):
        super().__init__(parent)
        self.setWindowTitle("הוספת מקבל" if rec is None else "עריכת מקבל")
        self.setMinimumSize(600, 560)
        self.resize(640, 620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build(rec)

    def _build(self, rec):
        from PyQt6.QtWidgets import QScrollArea, QTabWidget
        outer = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        # The 4 tab titles didn't fit the dialog width → the last tab ('מידע מנהלי')
        # was clipped to 'מידע' behind scroll-arrows (bug #7y8o0). Let the bar share
        # the width evenly with compact tabs and no scroll buttons, so all four are
        # always fully readable.
        tabs.setObjectName("recip-tabs")
        tabs.setStyleSheet(
            "QTabWidget#recip-tabs QTabBar::tab{min-width:0; padding:8px 12px; margin:2px;}")
        tabs.setUsesScrollButtons(False)
        tabs.tabBar().setExpanding(True)
        outer.addWidget(tabs)

        def _tab(title):
            w = QWidget()
            w.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            scroll = QScrollArea()
            scroll.setWidget(w)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(scroll.Shape.NoFrame)
            tabs.addTab(scroll, title)
            form = QFormLayout(w)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            form.setFormAlignment(Qt.AlignmentFlag.AlignRight)
            form.setSpacing(8)
            form.setContentsMargins(10, 10, 10, 10)
            return form

        def field(placeholder=""):
            w = QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setAlignment(Qt.AlignmentFlag.AlignRight)
            return w

        # ── Tab 1: פרטים בסיסיים ─────────────────────────────────────────────
        f1 = _tab("פרטים בסיסיים")
        self._form1 = f1

        self.f_name    = field("שם מלא (חובה)")
        self.f_phone1  = field("טלפון ראשי")
        self.f_phone2  = field("טלפון 2")
        self.f_phone3  = field("טלפון 3")
        self.f_address = field("כתובת")

        self.f_area = QComboBox()
        self.f_area.addItems(["", "בעלז", "נתיב"])
        self.f_area.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.f_souls = QSpinBox()
        self.f_souls.setRange(0, 99)

        # Frequency = a SCHEDULE, which only a 'קבוע' recipient has. So the combo
        # offers only the three real schedules (no blank, no 'חד-פעמי') and the
        # whole row is shown only while priority = קבוע (see _toggle_frequency_row).
        # For priority ראשונה/שנייה the stored frequency is derived as 'חד-פעמי',
        # for ללא/בירור it is '' — see _effective_frequency(). This removes the
        # confusing empty option (#fw5s2) and the frequency-without-קבוע case (#j6czs).
        self.f_freq = QComboBox()
        self.f_freq.addItems(["שבועי", "דו-שבועי", "חודשי"])
        self.f_freq.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.f_status = QComboBox()
        self.f_status.addItems(["פעיל", "מושהה", "הסתיים"])
        self.f_status.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.f_priority = QComboBox()
        self.f_priority.addItems([o[0] or "—" for o in _PRIORITY_OPTIONS])
        self.f_priority.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.f_priority.setToolTip("עדיפות בחלוקה: קבוע · עדיפות ראשונה · עדיפות שנייה · "
                                   "חובת בירור (ריק = לא בחלוקה)")

        self.f_last_dist  = DateEdit(allow_empty=True)
        self.f_next_dist  = DateEdit(allow_empty=True)
        self.f_next_dist.setToolTip("מחושב אוטומטית לפי תדירות — ניתן לשנות")

        self.f_notes = QTextEdit()
        self.f_notes.setMaximumHeight(60)
        self.f_notes.setPlaceholderText("הערות")
        rtl_text_area(self.f_notes)

        self.f_freq.currentTextChanged.connect(self._suggest_next)
        self.f_last_dist.dateChanged.connect(self._suggest_next)
        # Frequency is a קבוע-only concept — show/hide its row with the priority,
        # and re-suggest the next date when the effective frequency changes.
        self.f_priority.currentIndexChanged.connect(self._toggle_frequency_row)
        self.f_priority.currentIndexChanged.connect(self._suggest_next)

        for w in (self.f_phone1, self.f_phone2, self.f_phone3):
            w.textChanged.connect(lambda t, fw=w: _mark(fw, bool(t.strip()) and not _phone_valid(t),
                                                        "מספר לא תקני — 9-10 ספרות, מתחיל ב-0"))

        # Most recipients have one number — show a single 'טלפון' field by default
        # and reveal the extra two only on demand, so the form isn't cluttered with
        # three phone rows (#4y193). The '+ הוסף מספר' link reveals the next one.
        self.btn_add_phone = QPushButton("＋ הוסף מספר")
        self.btn_add_phone.setObjectName("neutral")
        self.btn_add_phone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_phone.setStyleSheet(
            "QPushButton{border:none; background:transparent; color:#0f766e;"
            " font-size:12px; font-weight:600; padding:2px 0; text-align:right;}"
            "QPushButton:hover{color:#0b5c55; text-decoration:underline;}")
        self.btn_add_phone.clicked.connect(self._reveal_next_phone)

        f1.addRow("שם מלא:", self.f_name)
        f1.addRow("טלפון:", self.f_phone1)
        f1.addRow("טלפון נוסף:", self.f_phone2)
        f1.addRow("טלפון נוסף:", self.f_phone3)
        f1.addRow("", self.btn_add_phone)
        f1.addRow("כתובת:", self.f_address)
        f1.addRow("אזור:", self.f_area)
        f1.addRow("נפשות:", self.f_souls)
        # עדיפות מעל תדירות (#3jiq8): התדירות נגזרת מהעדיפות ונפתחת רק כשהיא 'קבוע',
        # לכן העדיפות באה קודם — ואז שורת התדירות מופיעה/נעלמת מתחתיה.
        f1.addRow("עדיפות:", self.f_priority)
        f1.addRow("תדירות:", self.f_freq)
        f1.addRow("סטטוס:", self.f_status)
        # On ADD these are meaningless and only add noise: 'חלוקה אחרונה' is set
        # automatically when a distribution is recorded (a new recipient has none
        # yet) and 'חלוקה הבאה' is auto-computed from the frequency (✦). Keep them
        # only when editing an existing recipient (to view or correct). The widgets
        # are still created above, so get_data()/validation keep working.
        if rec is not None:
            f1.addRow("חלוקה אחרונה:", self.f_last_dist)
            f1.addRow("חלוקה הבאה ✦:", self.f_next_dist)
        f1.addRow("הערות:", self.f_notes)

        # ── Tab 2: פרטים אישיים ─────────────────────────────────────────────
        f2 = _tab("פרטים אישיים")

        self.f_birth_date        = DateEdit(allow_empty=True)
        self.f_spouse_birth_date = DateEdit(allow_empty=True)
        self.f_id_number         = field("תעודת זהות בעל")
        self.f_spouse_id_number  = field("תעודת זהות אשה")
        self.f_marital_status    = field("מצב אישי")
        self.f_email             = field("אימייל")
        self.f_synagogue         = field("בית כנסת")
        self.f_occupation        = field("עיסוק בעל")
        self.f_work_scope        = field("היקף משרה / לימודים")
        self.f_parent_type       = field("סוג הורה")

        f2.addRow("ת. לידה (בעל):", self.f_birth_date)
        f2.addRow("ת. לידה (אשה):", self.f_spouse_birth_date)
        f2.addRow("ת.ז. בעל:", self.f_id_number)
        f2.addRow("ת.ז. אשה:", self.f_spouse_id_number)
        f2.addRow("מצב אישי:", self.f_marital_status)
        f2.addRow("אימייל:", self.f_email)
        f2.addRow("בית כנסת:", self.f_synagogue)
        f2.addRow("עיסוק בעל:", self.f_occupation)
        f2.addRow("היקף משרה:", self.f_work_scope)
        f2.addRow("סוג הורה:", self.f_parent_type)

        # ── Tab 3: ילדים וכלכלה ─────────────────────────────────────────────
        f3 = _tab("ילדים וכלכלה")

        self.f_children_home    = QSpinBox(); self.f_children_home.setRange(0, 30)
        self.f_children_married = QSpinBox(); self.f_children_married.setRange(0, 30)
        self.f_children_total   = QSpinBox(); self.f_children_total.setRange(0, 30)
        self.f_housing_expenses = field("הוצאות דיור")
        self.f_medical_expenses = field("הוצאות רפואיות")
        self.f_income           = field("הכנסות")
        self.f_per_soul         = field("פנוי לנפש")

        f3.addRow("ילדים בבית:", self.f_children_home)
        f3.addRow("ילדים נשואים:", self.f_children_married)
        f3.addRow("מספר ילדים:", self.f_children_total)
        f3.addRow("הוצאות דיור:", self.f_housing_expenses)
        f3.addRow("הוצאות רפואיות:", self.f_medical_expenses)
        f3.addRow("הכנסות:", self.f_income)
        f3.addRow("פנוי לנפש:", self.f_per_soul)

        # ── Tab 4: מידע מנהלי ───────────────────────────────────────────────
        f4 = _tab("מידע מנהלי")

        self.f_external_id  = field("מספר מזהה חיצוני")
        self.f_source       = field("מקור הפנייה")
        self.f_representative = field("שם נציג")

        f4.addRow("מס' מזהה:", self.f_external_id)
        f4.addRow("מקור:", self.f_source)
        f4.addRow("שם נציג:", self.f_representative)
        # Marker shown when the נציג was filled by the synagogue-majority auto-fill
        # (#lejmr) — so the operator can see it's a guess and correct it. Editing
        # the field clears the flag on save.
        self.lbl_rep_auto = QLabel("↳ שויך אוטומטית לפי בית הכנסת — בדוק ותקן במידת הצורך")
        self.lbl_rep_auto.setStyleSheet("color:#b45309; font-size:11px;")
        self.lbl_rep_auto.setVisible(False)
        f4.addRow("", self.lbl_rep_auto)

        # ── fill values ──────────────────────────────────────────────────────
        if rec:
            self.f_name.setText(rec.get("full_name") or "")
            self.f_phone1.setText(rec.get("phone1") or "")
            self.f_phone2.setText(rec.get("phone2") or "")
            self.f_phone3.setText(rec.get("phone3") or "")
            self.f_address.setText(rec.get("address") or "")
            self.f_area.setCurrentIndex(max(0, self.f_area.findText(rec.get("area") or "")))
            self.f_souls.setValue(int(rec.get("souls") or 0))
            self.f_freq.setCurrentIndex(max(0, self.f_freq.findText(rec.get("frequency") or "")))
            self.f_status.setCurrentIndex(max(0, self.f_status.findText(rec.get("status") or "פעיל")))
            self.f_notes.setPlainText(rec.get("notes") or "")
            self.f_last_dist.set_from_iso(rec.get("last_distribution") or "")
            self.f_next_dist.set_from_iso(rec.get("next_distribution") or "")

            self.f_birth_date.set_from_iso(rec.get("birth_date") or "")
            self.f_spouse_birth_date.set_from_iso(rec.get("spouse_birth_date") or "")
            self.f_id_number.setText(rec.get("id_number") or "")
            self.f_spouse_id_number.setText(rec.get("spouse_id_number") or "")
            self.f_marital_status.setText(rec.get("marital_status") or "")
            self.f_email.setText(rec.get("email") or "")
            self.f_synagogue.setText(rec.get("synagogue") or "")
            self.f_occupation.setText(rec.get("occupation") or "")
            self.f_work_scope.setText(rec.get("work_scope") or "")
            self.f_parent_type.setText(rec.get("parent_type") or "")

            self.f_children_home.setValue(int(rec.get("children_home") or 0))
            self.f_children_married.setValue(int(rec.get("children_married") or 0))
            self.f_children_total.setValue(int(rec.get("children_total") or 0))
            self.f_housing_expenses.setText(rec.get("housing_expenses") or "")
            self.f_medical_expenses.setText(rec.get("medical_expenses") or "")
            self.f_income.setText(rec.get("income") or "")
            self.f_per_soul.setText(rec.get("per_soul") or "")

            self.f_external_id.setText(rec.get("external_id") or "")
            self.f_source.setText(rec.get("source") or "")
            self.f_representative.setText(rec.get("representative") or "")
            self.lbl_rep_auto.setVisible(bool(rec.get("representative_auto")))

            # priority: match by number, else by 'חובת בירור', else blank
            pr = rec.get("priority")
            raw = rec.get("priority_raw") or ""
            p_idx = 0
            if pr is not None:
                p_idx = next((i for i, o in enumerate(_PRIORITY_OPTIONS) if o[1] == pr), 0)
            elif "בירור" in raw:
                p_idx = next((i for i, o in enumerate(_PRIORITY_OPTIONS) if "בירור" in o[0]), 0)
            self.f_priority.setCurrentIndex(p_idx)
        else:
            # Add mode: default to a WEEKLY / קבוע recipient so a newly added
            # person actually enters the distribution list. With the previous
            # blank defaults, the recipient was saved but filtered out of the
            # weekly issuance (get_weekly_list drops frequency='') — so it looked
            # like "adding from the software doesn't work, only Excel does".
            self.f_freq.setCurrentText("שבועי")
            self.f_priority.setCurrentText("קבוע")

        btns = QHBoxLayout()
        btn_ok = QPushButton("שמור")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate_and_accept)
        btn_cancel = QPushButton("ביטול")
        btn_cancel.setObjectName("neutral")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        outer.addLayout(btns)

        # Set the initial visibility of the frequency row (setCurrentIndex above
        # doesn't fire the signal when the value was already index 0 = ללא).
        self._toggle_frequency_row()
        # Collapse the extra phone rows; on edit, keep any already-filled ones open.
        self._init_phone_rows()

    def _init_phone_rows(self):
        """Show only 'טלפון' by default; reveal 'טלפון נוסף' rows that already hold
        a value (edit mode). The '+ הוסף מספר' link is hidden once all three show."""
        show2 = bool(self.f_phone2.text().strip())
        show3 = bool(self.f_phone3.text().strip())
        # A value in phone3 but not phone2 shouldn't leave a gap — reveal both.
        show2 = show2 or show3
        self._form1.setRowVisible(self.f_phone2, show2)
        self._form1.setRowVisible(self.f_phone3, show3)
        self._form1.setRowVisible(self.btn_add_phone, not (show2 and show3))

    def _reveal_next_phone(self):
        """Reveal the next hidden phone row (phone2, then phone3)."""
        if not self._form1.isRowVisible(self.f_phone2):
            self._form1.setRowVisible(self.f_phone2, True)
            self.f_phone2.setFocus()
        elif not self._form1.isRowVisible(self.f_phone3):
            self._form1.setRowVisible(self.f_phone3, True)
            self.f_phone3.setFocus()
        # Hide the link once all three are showing.
        if self._form1.isRowVisible(self.f_phone2) and self._form1.isRowVisible(self.f_phone3):
            self._form1.setRowVisible(self.btn_add_phone, False)

    def _is_regular_selected(self) -> bool:
        """True when the priority combo currently points at 'קבוע' (4)."""
        return _PRIORITY_OPTIONS[self.f_priority.currentIndex()][1] == 4

    def _toggle_frequency_row(self):
        """Show the 'תדירות' row only for a קבוע recipient (#j6czs)."""
        self._form1.setRowVisible(self.f_freq, self._is_regular_selected())

    def _effective_frequency(self) -> str:
        """The frequency actually stored, derived from the priority:
        קבוע → the chosen schedule · ראשונה/שנייה → 'חד-פעמי' · else → ''."""
        pr = _PRIORITY_OPTIONS[self.f_priority.currentIndex()][1]
        if pr == 4:
            return self.f_freq.currentText()
        if pr in (3, 2):
            return "חד-פעמי"
        return ""

    def _suggest_next(self):
        """Auto-fill next_distribution when it's empty and we have enough info."""
        if not self.f_next_dist.is_empty():
            return  # user already set it manually — don't overwrite
        freq = self._effective_frequency()
        if not freq or freq == "חד-פעמי":
            return
        nd = db.calculate_next_dist(self.f_last_dist.get_iso(), freq)
        self.f_next_dist.setDate(QDate(nd.year, nd.month, nd.day))

    def _validate_and_accept(self):
        errors = self._collect_errors()
        if errors:
            QMessageBox.warning(self, "יש לתקן לפני שמירה",
                                "• " + "\n• ".join(errors))
            return
        # Safety net: priority ללא/חובת בירור yields no frequency, so the recipient
        # will not appear in any distribution list. Warn instead of silently hiding
        # them (a קבוע always has a schedule; ראשונה/שנייה go to the one-time list).
        if not self._effective_frequency().strip():
            reply = QMessageBox.question(
                self, "לא בחלוקה",
                "העדיפות שנבחרה (ללא / חובת בירור) אינה נכללת בחלוקה — "
                "המקבל יישמר אבל לא יופיע בשום רשימת חלוקה.\n\n"
                "לשמור בכל זאת?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def _collect_errors(self) -> list[str]:
        errors: list[str] = []
        today = QDate.currentDate()

        # ── שם מלא ──────────────────────────────────────────────────────────
        name = self.f_name.text().strip()
        if not name:
            _mark(self.f_name, True, "שם מלא הוא שדה חובה")
            errors.append("שם מלא: שדה חובה")
        elif len(name) < 2:
            _mark(self.f_name, True, "שם חייב להכיל לפחות 2 תווים")
            errors.append("שם מלא: קצר מדי (לפחות 2 תווים)")
        elif len(name) > 60:
            _mark(self.f_name, True, "שם ארוך מדי (עד 60 תווים)")
            errors.append("שם מלא: ארוך מדי (עד 60 תווים)")
        else:
            _mark(self.f_name, False)

        # ── טלפונים ─────────────────────────────────────────────────────────
        for w, label in ((self.f_phone1, "טלפון 1"),
                         (self.f_phone2, "טלפון 2"),
                         (self.f_phone3, "טלפון 3")):
            raw = w.text().strip()
            if raw and not _phone_valid(raw):
                _mark(w, True, f"{label}: מספר לא תקני — 9-10 ספרות, מתחיל ב-0")
                errors.append(f"{label}: מספר לא תקני ({raw})")
            else:
                _mark(w, False)

        # ── תאריכים ─────────────────────────────────────────────────────────
        EMPTY = DateEdit.EMPTY
        last_q  = self.f_last_dist.date()
        next_q  = self.f_next_dist.date()

        # חלוקה אחרונה לא בעתיד
        if last_q > EMPTY and last_q > today:
            _mark(self.f_last_dist, True, "חלוקה אחרונה לא יכולה להיות בעתיד")
            errors.append("חלוקה אחרונה: תאריך עתידי")
        else:
            _mark(self.f_last_dist, False)

        # חלוקה הבאה אחרי האחרונה
        if next_q > EMPTY and last_q > EMPTY and next_q < last_q:
            _mark(self.f_next_dist, True, "חלוקה הבאה חייבת להיות אחרי החלוקה האחרונה")
            errors.append("חלוקה הבאה: קודמת לחלוקה האחרונה")
        else:
            if next_q <= EMPTY or last_q <= EMPTY or next_q >= last_q:
                _mark(self.f_next_dist, False)

        return errors

    def get_data(self) -> dict:
        return {
            "full_name":          self.f_name.text().strip(),
            "phone1":             self.f_phone1.text().strip(),
            "phone2":             self.f_phone2.text().strip(),
            "phone3":             self.f_phone3.text().strip(),
            "address":            self.f_address.text().strip(),
            "area":               self.f_area.currentText(),
            "souls":              self.f_souls.value(),
            "frequency":          self._effective_frequency(),
            "status":             self.f_status.currentText(),
            "last_distribution":  self.f_last_dist.get_iso(),
            "next_distribution":  self.f_next_dist.get_iso(),
            "notes":              self.f_notes.toPlainText().strip(),
            "birth_date":         self.f_birth_date.get_iso(),
            "spouse_birth_date":  self.f_spouse_birth_date.get_iso(),
            "id_number":          self.f_id_number.text().strip(),
            "spouse_id_number":   self.f_spouse_id_number.text().strip(),
            "marital_status":     self.f_marital_status.text().strip(),
            "email":              self.f_email.text().strip(),
            "synagogue":          self.f_synagogue.text().strip(),
            "occupation":         self.f_occupation.text().strip(),
            "work_scope":         self.f_work_scope.text().strip(),
            "parent_type":        self.f_parent_type.text().strip(),
            "children_home":      self.f_children_home.value(),
            "children_married":   self.f_children_married.value(),
            "children_total":     self.f_children_total.value(),
            "housing_expenses":   self.f_housing_expenses.text().strip(),
            "medical_expenses":   self.f_medical_expenses.text().strip(),
            "income":             self.f_income.text().strip(),
            "per_soul":           self.f_per_soul.text().strip(),
            "external_id":        self.f_external_id.text().strip(),
            "source":             self.f_source.text().strip(),
            "representative":     self.f_representative.text().strip(),
            "priority":           _PRIORITY_OPTIONS[self.f_priority.currentIndex()][1],
            "priority_raw":       _PRIORITY_OPTIONS[self.f_priority.currentIndex()][2],
        }


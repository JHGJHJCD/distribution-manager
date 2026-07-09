from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QLabel, QComboBox,
    QDialog, QFormLayout, QMessageBox, QFileDialog, QSpinBox,
    QTextEdit, QAbstractItemView
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
from utils.excel_utils import import_from_excel
from utils.ui import (busy_cursor, attach_empty_state, refresh_empty_state,
                      BadgeDelegate, PRIORITY_BADGES, STATUS_BADGES, search_icon,
                      ALIGN_RIGHT, rtl_text_area, enable_touch_scroll)

# Compact action buttons (≈50% shorter) — glossy gradients come from the
# success/danger object names; this only tightens the size.
_ACTION_BTN = "font-size:12px; min-height:24px; min-width:64px; padding:3px 14px;"
# 'השהה' — a glossy amber button (its own gradient, no object name).
_SUSPEND_BTN = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "  stop:0 #fbbf24, stop:1 #f59e0b); color:#ffffff; border:none;"
    "  border-radius:9px; font-weight:700; font-size:12px;"
    "  min-height:24px; min-width:64px; padding:3px 14px; }"
    "QPushButton:hover{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "  stop:0 #fcd34d, stop:1 #d97706); }"
    "QPushButton:pressed{ background:#b45309; }"
)

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
        self.priority_filter.currentTextChanged.connect(self.refresh)
        top.addWidget(self.priority_filter)

        btn_add = QPushButton("+ הוסף מקבל")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)

        btn_import = QPushButton("יבוא מ-Excel")
        btn_import.setObjectName("success")
        btn_import.setStyleSheet("font-size:11px; min-height:24px; min-width:0; padding:3px 12px;")
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
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
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

        # Bottom buttons — trimmed to the three core actions (הפעל / השהה / מחק),
        # smaller and glossy. Editing is still available by double-clicking a row.
        bot = QHBoxLayout()
        bot.setSpacing(8)

        btn_activate = QPushButton("הפעל")
        btn_activate.setObjectName("success")
        btn_activate.setStyleSheet(_ACTION_BTN)
        btn_activate.setToolTip("סמן את המקבל הנבחר כפעיל")
        btn_activate.clicked.connect(lambda: self._set_status("פעיל"))
        bot.addWidget(btn_activate)

        btn_suspend = QPushButton("השהה")
        btn_suspend.setStyleSheet(_SUSPEND_BTN)
        btn_suspend.setToolTip("השהה זמנית את המקבל הנבחר")
        btn_suspend.clicked.connect(lambda: self._set_status("מושהה"))
        bot.addWidget(btn_suspend)

        btn_del = QPushButton("מחק")
        btn_del.setObjectName("danger")
        btn_del.setStyleSheet(_ACTION_BTN)
        btn_del.setToolTip("מחק את המקבל הנבחר")
        btn_del.clicked.connect(self._delete)
        bot.addWidget(btn_del)

        bot.addStretch()

        btn_dup = QPushButton("בדיקת כפילויות")
        btn_dup.setObjectName("neutral")
        btn_dup.setStyleSheet("font-size:11px; min-height:24px; min-width:0; padding:3px 12px;")
        btn_dup.setToolTip("סריקת שמות/טלפונים כפולים")
        btn_dup.clicked.connect(self._open_dup_check)
        bot.addWidget(btn_dup)

        lay.addLayout(bot)

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
            "• לא  = מיזוג (מוסיף חדשים, משלים שדות ריקים בקיימים)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        replace = (choice == QMessageBox.StandardButton.Yes)
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
                    # Safety backup BEFORE wiping — abort if it cannot be made.
                    if auto_backup() is not True:
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


# ─── Add/Edit dialog ──────────────────────────────────────────────────────────

class RecipientDialog(QDialog):
    def __init__(self, parent=None, rec: dict = None):
        super().__init__(parent)
        self.setWindowTitle("הוספת מקבל" if rec is None else "עריכת מקבל")
        self.setMinimumSize(520, 560)
        self.resize(560, 620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build(rec)

    def _build(self, rec):
        from PyQt6.QtWidgets import QScrollArea, QTabWidget
        outer = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
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

        self.f_freq = QComboBox()
        self.f_freq.addItems(["", "שבועי", "דו-שבועי", "חודשי", "חד-פעמי"])
        self.f_freq.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.f_status = QComboBox()
        self.f_status.addItems(["פעיל", "מושהה", "הסתיים"])
        self.f_status.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.f_priority = QComboBox()
        self.f_priority.addItems([o[0] or "—" for o in _PRIORITY_OPTIONS])
        self.f_priority.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.f_priority.setToolTip("עדיפות בחלוקה: קבוע · עדיפות ראשונה · עדיפות שנייה · "
                                   "חובת בירור (ריק = לא בחלוקה)")

        self.f_start_date = DateEdit(allow_empty=True)
        self.f_last_dist  = DateEdit(allow_empty=True)
        self.f_next_dist  = DateEdit(allow_empty=True)
        self.f_next_dist.setToolTip("מחושב אוטומטית לפי תדירות — ניתן לשנות")

        self.f_notes = QTextEdit()
        self.f_notes.setMaximumHeight(60)
        self.f_notes.setPlaceholderText("הערות")
        rtl_text_area(self.f_notes)

        self.f_freq.currentTextChanged.connect(self._suggest_next)
        self.f_last_dist.dateChanged.connect(self._suggest_next)

        for w in (self.f_phone1, self.f_phone2, self.f_phone3):
            w.textChanged.connect(lambda t, fw=w: _mark(fw, bool(t.strip()) and not _phone_valid(t),
                                                        "מספר לא תקני — 9-10 ספרות, מתחיל ב-0"))

        f1.addRow("שם מלא:", self.f_name)
        f1.addRow("טלפון 1:", self.f_phone1)
        f1.addRow("טלפון 2:", self.f_phone2)
        f1.addRow("טלפון 3:", self.f_phone3)
        f1.addRow("כתובת:", self.f_address)
        f1.addRow("אזור:", self.f_area)
        f1.addRow("נפשות:", self.f_souls)
        f1.addRow("תדירות:", self.f_freq)
        f1.addRow("עדיפות:", self.f_priority)
        f1.addRow("סטטוס:", self.f_status)
        # On ADD these are meaningless and only add noise: 'חלוקה אחרונה' is set
        # automatically when a distribution is recorded (a new recipient has none
        # yet), 'חלוקה הבאה' is auto-computed from the frequency (✦), and
        # 'תאריך התחלה' isn't used by any scheduling/display logic. Keep them only
        # when editing an existing recipient (to view or correct). The widgets are
        # still created above, so get_data()/validation keep working (empty on add).
        if rec is not None:
            f1.addRow("תאריך התחלה:", self.f_start_date)
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
            self.f_start_date.set_from_iso(rec.get("start_date") or "")
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

    def _suggest_next(self):
        """Auto-fill next_distribution when it's empty and we have enough info."""
        if not self.f_next_dist.is_empty():
            return  # user already set it manually — don't overwrite
        freq = self.f_freq.currentText()
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
        # Safety net: a blank frequency means the recipient will NOT show up in
        # the weekly distribution list. Warn instead of silently hiding them.
        if not self.f_freq.currentText().strip():
            reply = QMessageBox.question(
                self, "ללא תדירות",
                "לא נבחרה תדירות חלוקה — המקבל יישמר אבל לא יופיע ברשימת החלוקה.\n\n"
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
            "frequency":          self.f_freq.currentText(),
            "status":             self.f_status.currentText(),
            "start_date":         self.f_start_date.get_iso(),
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


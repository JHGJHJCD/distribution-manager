import html as _html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QAbstractItemView, QFrame,
    QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
import database as db
from utils.ui import (search_icon, busy_cursor, BadgeDelegate, HighlightDelegate,
                      PRIORITY_BADGES, STATUS_BADGES, ALIGN_RIGHT)
from utils.excel_utils import export_recipients_to_excel
from utils.print_view import print_recipient_card

_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"


def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""


HIST_COLS = ["תאריך", "מה חולק", "כמות", "מחלק", "הערות"]
RESULT_COLS = ["שם מלא", "טלפון", "עדיפות", "אזור", "סטטוס", "ת״ז בעל", "ת״ז אשה"]
_COL_NAME, _COL_PHONE, _COL_PRIORITY, _COL_AREA, _COL_STATUS = 0, 1, 2, 3, 4


def _first_phone(rec: dict) -> str:
    for k in ("phone1", "phone2", "phone3"):
        v = rec.get(k)
        if v:
            return str(v)
    return ""


def _priority_display(rec: dict) -> str:
    labels = {4: "קבוע", 3: "ראשונה", 2: "שנייה"}
    pr = rec.get("priority")
    if pr in labels:
        return labels[pr]
    return "בירור" if "בירור" in (rec.get("priority_raw") or "") else ""


def _badge_span(text: str, colors: dict) -> str:
    c = colors.get(text)
    if not text or not c:
        return ""
    bg, fg = c
    return (f"<span style='background:{bg};color:{fg};padding:2px 12px;"
            f"border-radius:9px;font-weight:700;font-size:12px'>{_html.escape(text)}</span>")


class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows: list = []
        self._results: list = []
        self._current_rec_id = None
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._run_search)
        self._build_ui()
        self._show_empty_profile()

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("חיפוש מהיר")
        title.setObjectName("title")
        lay.addWidget(title)

        # Search bar
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setMinimumHeight(38)
        self.search_input.setPlaceholderText("חיפוש: שם, טלפון, ת״ז, כתובת, אימייל...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(lambda: self._filter_timer.start(200))
        search_row.addWidget(self.search_input, 1)

        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        self.count_lbl.setMinimumWidth(90)
        search_row.addWidget(self.count_lbl)

        btn_export = QPushButton("ייצוא לאקסל")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet(_SMALL_BTN)
        btn_export.setToolTip("ייצא את הרשימה המסוננת (התוצאות שמוצגות) לאקסל בתיקיית ההורדות")
        btn_export.clicked.connect(self._export_results)
        search_row.addWidget(btn_export)
        lay.addLayout(search_row)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(len(RESULT_COLS))
        self.results_table.setHorizontalHeaderLabels(RESULT_COLS)
        self.results_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setMinimumHeight(170)
        self.results_table.setMaximumHeight(250)
        rhdr = self.results_table.horizontalHeader()
        rhdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        rhdr.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        rhdr.setResizeContentsPrecision(20)
        self.results_table.verticalHeader().setVisible(False)
        self._hl = HighlightDelegate(self.results_table)
        self.results_table.setItemDelegateForColumn(_COL_NAME, self._hl)
        self.results_table.setItemDelegateForColumn(_COL_PHONE, self._hl)
        self._pri_badge = BadgeDelegate(PRIORITY_BADGES, self.results_table)
        self._st_badge = BadgeDelegate(STATUS_BADGES, self.results_table)
        self.results_table.setItemDelegateForColumn(_COL_PRIORITY, self._pri_badge)
        self.results_table.setItemDelegateForColumn(_COL_STATUS, self._st_badge)
        self.results_table.itemSelectionChanged.connect(self._on_result_selected)
        lay.addWidget(self.results_table)

        # Profile card (rich HTML) — the selected recipient's details
        self.profile_card = QFrame()
        self.profile_card.setObjectName("panel")
        pc_lay = QVBoxLayout(self.profile_card)
        pc_lay.setContentsMargins(16, 12, 16, 12)
        self.profile_lbl = QLabel("")
        self.profile_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.profile_lbl.setWordWrap(True)
        self.profile_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.profile_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        pc_lay.addWidget(self.profile_lbl)
        lay.addWidget(self.profile_card)

        # History header row + print-card button
        hist_row = QHBoxLayout()
        self.hist_title = QLabel("היסטוריית חלוקות")
        self.hist_title.setObjectName("section-header")
        hist_row.addWidget(self.hist_title)
        hist_row.addStretch()
        self.btn_print_card = QPushButton("🖨 הדפס כרטיס")
        self.btn_print_card.setObjectName("neutral")
        self.btn_print_card.setStyleSheet(_SMALL_BTN)
        self.btn_print_card.setToolTip("הדפס כרטיס עם פרטי המקבל + היסטוריית החלוקות שלו")
        self.btn_print_card.clicked.connect(self._print_card)
        self.btn_print_card.setEnabled(False)
        hist_row.addWidget(self.btn_print_card)
        lay.addLayout(hist_row)

        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(len(HIST_COLS))
        self.hist_table.setHorizontalHeaderLabels(HIST_COLS)
        self.hist_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.hist_table.setAlternatingRowColors(True)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.hist_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)
        self.hist_table.verticalHeader().setVisible(False)
        lay.addWidget(self.hist_table, 1)

    # ── data ───────────────────────────────────────────────────────────────────
    def refresh(self):
        self._all_rows = db.get_all_recipients()
        self._run_search()

    def _run_search(self):
        query = self.search_input.text()
        self._hl.set_query(query)
        self._results = db.filter_recipients(self._all_rows, query)
        self._populate_results()

    def _populate_results(self):
        _ALIGN = ALIGN_RIGHT
        self.results_table.blockSignals(True)
        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.results_table.setRowCount(len(self._results))
        for r, rec in enumerate(self._results):
            vals = [rec.get("full_name", ""), _first_phone(rec),
                    _priority_display(rec), rec.get("area", "") or "",
                    rec.get("status", ""),
                    rec.get("id_number", "") or "", rec.get("spouse_id_number", "") or ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v) or "")
                item.setTextAlignment(_ALIGN)
                if c == _COL_NAME:
                    item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.results_table.setItem(r, c, item)
        self.results_table.blockSignals(False)
        self.count_lbl.setText(f"נמצאו: {len(self._results)}")

        if self._results:
            self.results_table.setCurrentCell(0, 0)
        else:
            self.results_table.clearSelection()
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self._show_empty_profile("לא נמצאו תוצאות")

    def _on_result_selected(self):
        row = self.results_table.currentRow()
        if row < 0:
            return
        item = self.results_table.item(row, _COL_NAME)
        rec_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if rec_id:
            self._show_recipient(rec_id)

    def _show_empty_profile(self, msg="בחר מקבל מהרשימה כדי לראות את פרטיו"):
        self.profile_lbl.setText(
            f"<div dir='rtl' style='color:#94a3b8;font-size:13px;padding:14px 0;'>{msg}</div>")
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_title.setText("היסטוריית חלוקות")

    def _profile_html(self, rec: dict, hist_count: int) -> str:
        def esc(v):
            return _html.escape(str(v if v is not None else ""))

        name = esc(rec.get("full_name", ""))
        pri = _badge_span(_priority_display(rec), PRIORITY_BADGES)
        status = _badge_span(rec.get("status", ""), STATUS_BADGES)
        phones = " / ".join(p for p in [rec.get("phone1"), rec.get("phone2"), rec.get("phone3")] if p)

        # Two info columns: contact/household (right) + distribution/meta (left)
        def cell(label, value, ltr=False):
            value = esc(value)
            v = f"<span dir='ltr'>{value}</span>" if (ltr and value) else (value or "—")
            return (f"<tr><td style='color:#64748b;padding:3px 0 3px 10px;white-space:nowrap'>{label}</td>"
                    f"<td style='color:#1f2937;font-weight:600;padding:3px 0'>{v}</td></tr>")

        right = ("<table cellspacing='0' width='100%'>"
                 + cell("טלפונים", phones, ltr=True)
                 + cell("ת״ז בעל", rec.get("id_number"), ltr=True)
                 + cell("ת״ז אשה", rec.get("spouse_id_number"), ltr=True)
                 + cell("כתובת", rec.get("address"))
                 + cell("אזור", rec.get("area"))
                 + cell("נפשות", rec.get("souls"))
                 + "</table>")
        left = ("<table cellspacing='0' width='100%'>"
                + cell("תדירות", rec.get("frequency"))
                + cell("חלוקה אחרונה", _fdate(rec.get("last_distribution") or ""))
                + cell("חלוקה הבאה", _fdate(rec.get("next_distribution") or ""))
                + cell("סה״כ חלוקות", hist_count)
                + cell("אימייל", rec.get("email"), ltr=True)
                + cell("בית כנסת", rec.get("synagogue"))
                + "</table>")

        notes = esc(rec.get("notes") or "")
        notes_block = (f"<div style='margin-top:8px;padding:8px 10px;background:#fffbeb;"
                       f"border:1px solid #fde68a;border-radius:6px;color:#78350f'>"
                       f"<b>הערות:</b> {notes}</div>") if notes else ""

        return f"""
        <div dir='rtl' style='font-family:Segoe UI,Arial;'>
          <div style='font-size:19px;font-weight:800;color:#0d2a4a;'>
            {name} &nbsp; {pri} &nbsp; {status}
          </div>
          <hr style='border:none;border-top:1px solid #e5e7eb;margin:8px 0;'>
          <table width='100%'><tr>
            <td width='50%' valign='top' style='padding-left:14px;'>{right}</td>
            <td width='50%' valign='top'>{left}</td>
          </tr></table>
          {notes_block}
        </div>
        """

    def _show_recipient(self, rec_id):
        rec = db.get_recipient(rec_id)
        if not rec:
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self._show_empty_profile()
            return
        self._current_rec_id = rec_id
        self.btn_print_card.setEnabled(True)

        hist = db.get_distributions_for_recipient(rec["id"])
        self.profile_lbl.setText(self._profile_html(rec, len(hist)))
        self.hist_title.setText(f"היסטוריית חלוקות ({len(hist)})")

        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_table.setRowCount(len(hist))
        for r, entry in enumerate(hist):
            vals = [_fdate(entry.get("dist_date", "")), entry.get("what_dist", ""),
                    str(entry.get("quantity", "") or ""), entry.get("distributor", ""),
                    entry.get("notes", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(ALIGN_RIGHT)
                self.hist_table.setItem(r, c, item)

    # ── actions ────────────────────────────────────────────────────────────────
    def _export_results(self):
        if not self._results:
            QMessageBox.information(self, "", "אין תוצאות לייצוא")
            return
        try:
            with busy_cursor():
                path = export_recipients_to_excel(self._results)
            QMessageBox.information(self, "ייצוא הושלם", f"הרשימה נשמרה בתיקיית ההורדות:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    def _print_card(self):
        if not self._current_rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        rec = db.get_recipient(self._current_rec_id)
        if not rec:
            return
        hist = db.get_distributions_for_recipient(self._current_rec_id)
        print_recipient_card(rec, hist, self)

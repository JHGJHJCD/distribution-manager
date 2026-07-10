import html as _html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QAbstractItemView,
    QFrame, QPushButton, QMessageBox, QListWidget, QListWidgetItem, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
import database as db
from utils.ui import (search_icon, busy_cursor, line_icon, enable_touch_scroll,
                      PRIORITY_BADGES, STATUS_BADGES, ALIGN_RIGHT, reveal_in_folder,
                      apply_header_icons)
from utils.excel_utils import export_recipients_to_excel
from utils.print_view import print_recipient_card

_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"


def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""


HIST_COLS = ["תאריך", "מה חולק", "כמות", "מחלק", "הערות"]


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
            f"border-radius:9px;font-weight:700;font-size:13px'>{_html.escape(text)}</span>")


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

        # Two columns: RIGHT = search + name list · LEFT = full details of the
        # best match. (In an RTL layout the first-added widget sits on the right.)
        main = QHBoxLayout()
        main.setSpacing(12)
        lay.addLayout(main, 1)

        # ── Right column: the search box + name results ────────────────────────
        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_panel.setFixedWidth(330)
        lp = QVBoxLayout(left_panel)
        lp.setContentsMargins(12, 12, 12, 12)
        lp.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setMinimumHeight(40)
        self.search_input.setPlaceholderText("חיפוש: שם, טלפון, ת״ז, כתובת, אימייל...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(lambda: self._filter_timer.start(180))
        lp.addWidget(self.search_input)

        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        lp.addWidget(self.count_lbl)

        self.results_list = QListWidget()
        self.results_list.setObjectName("names-list")
        self.results_list.setStyleSheet(
            "QListWidget#names-list { border:1px solid #e5e7eb; border-radius:8px; }"
            "QListWidget#names-list::item { padding:9px 12px; border-bottom:1px solid #f1f5f9; }"
            "QListWidget#names-list::item:selected {"
            "  background:#e7f1fd; color:#0d2a4a; border-left:3px solid #1565c0; }")
        self.results_list.currentItemChanged.connect(self._on_result_selected)
        enable_touch_scroll(self.results_list)
        lp.addWidget(self.results_list, 1)

        btn_export = QPushButton("ייצוא הרשימה לאקסל")
        btn_export.setObjectName("success")
        btn_export.setStyleSheet(_SMALL_BTN)
        btn_export.setToolTip("ייצא את הרשימה המסוננת (התוצאות) לאקסל בתיקיית ההורדות")
        btn_export.clicked.connect(self._export_results)
        lp.addWidget(btn_export)

        main.addWidget(left_panel)

        # ── Left column: details of the selected / best-matching recipient ─────
        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)
        main.addLayout(right_panel, 1)

        # Header (name + badges)
        self.detail_header = QLabel("")
        self.detail_header.setTextFormat(Qt.TextFormat.RichText)
        self.detail_header.setWordWrap(True)
        right_panel.addWidget(self.detail_header)

        # Scrollable detail rows (icon + label + value)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.detail_scroll.setMaximumHeight(300)
        enable_touch_scroll(self.detail_scroll)
        self.detail_card = QFrame()
        self.detail_card.setObjectName("panel")
        self._detail_lay = QVBoxLayout(self.detail_card)
        self._detail_lay.setContentsMargins(16, 12, 16, 12)
        self._detail_lay.setSpacing(2)
        self.detail_scroll.setWidget(self.detail_card)
        right_panel.addWidget(self.detail_scroll)

        # History header row + print-card button
        hist_row = QHBoxLayout()
        self.hist_title = QLabel("היסטוריית חלוקות")
        self.hist_title.setObjectName("section-header")
        hist_row.addWidget(self.hist_title)
        hist_row.addStretch()
        self.btn_print_card = QPushButton("הדפס כרטיס")
        self.btn_print_card.setObjectName("neutral")
        self.btn_print_card.setStyleSheet(_SMALL_BTN)
        self.btn_print_card.setToolTip("הדפס כרטיס עם פרטי המקבל + היסטוריית החלוקות שלו")
        self.btn_print_card.clicked.connect(self._print_card)
        self.btn_print_card.setEnabled(False)
        hist_row.addWidget(self.btn_print_card)
        right_panel.addLayout(hist_row)

        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(len(HIST_COLS))
        self.hist_table.setHorizontalHeaderLabels(HIST_COLS)
        apply_header_icons(self.hist_table)
        self.hist_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.hist_table.setAlternatingRowColors(True)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.hist_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)
        self.hist_table.verticalHeader().setVisible(False)
        enable_touch_scroll(self.hist_table)
        right_panel.addWidget(self.hist_table, 1)

    # ── data ───────────────────────────────────────────────────────────────────
    def refresh(self):
        self._all_rows = db.get_all_recipients()
        self._run_search()

    def _run_search(self):
        query = self.search_input.text()
        self._results = db.filter_recipients(self._all_rows, query)
        self._populate_results()

    def _populate_results(self):
        self.results_list.blockSignals(True)
        self.results_list.clear()
        for rec in self._results:
            name = rec.get("full_name", "") or "—"
            area = rec.get("area", "") or ""
            label = f"{name}    ·  {area}" if area else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.results_list.addItem(item)
        self.results_list.blockSignals(False)
        self.count_lbl.setText(f"נמצאו: {len(self._results)}")

        if self._results:
            self.results_list.setCurrentRow(0)   # auto-show the best match
        else:
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self._show_empty_profile("לא נמצאו תוצאות")

    def _on_result_selected(self, cur, _prev=None):
        if cur is None:
            return
        rec_id = cur.data(Qt.ItemDataRole.UserRole)
        if rec_id:
            self._show_recipient(rec_id)

    # ── details rendering ──────────────────────────────────────────────────────
    def _clear_details(self):
        while self._detail_lay.count():
            it = self._detail_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _add_detail_row(self, icon_name, label, value, ltr=False):
        value = (str(value).strip() if value not in (None, "") else "")
        if not value:
            return
        row = QWidget()
        g = QHBoxLayout(row)
        g.setContentsMargins(0, 4, 0, 4)
        g.setSpacing(9)
        ic = QLabel()
        ic.setPixmap(line_icon(icon_name, 17, "#1565c0"))
        ic.setFixedWidth(20)
        ic.setStyleSheet("background:transparent; border:none;")
        g.addWidget(ic)
        lab = QLabel(label)
        lab.setStyleSheet("color:#64748b; background:transparent; border:none;")
        lab.setFixedWidth(96)
        g.addWidget(lab)
        val = QLabel(value)
        val.setStyleSheet("color:#1f2937; font-weight:600; background:transparent; border:none;")
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if ltr:
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        g.addWidget(val, 1)
        self._detail_lay.addWidget(row)

    def _show_empty_profile(self, msg="בחר מקבל מהרשימה כדי לראות את פרטיו"):
        self.detail_header.setText(
            f"<div dir='rtl' style='color:#94a3b8;font-size:13px;padding:14px 0;'>{msg}</div>")
        self._clear_details()
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_title.setText("היסטוריית חלוקות")

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

        # Header — name + priority + status badges
        name = _html.escape(rec.get("full_name", "") or "")
        pri = _badge_span(_priority_display(rec), PRIORITY_BADGES)
        status = _badge_span(rec.get("status", ""), STATUS_BADGES)
        self.detail_header.setText(
            f"<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
            f"<span style='font-size:20px;font-weight:800;color:#0d2a4a;'>{name}</span>"
            f" &nbsp; {pri} &nbsp; {status}</div>")

        # Detail rows with dignified icons
        self._clear_details()
        phones = " / ".join(p for p in [rec.get("phone1"), rec.get("phone2"),
                                        rec.get("phone3")] if p)
        self._add_detail_row("phone", "טלפונים", phones, ltr=True)
        self._add_detail_row("id", "ת״ז בעל", rec.get("id_number"), ltr=True)
        self._add_detail_row("id", "ת״ז אשה", rec.get("spouse_id_number"), ltr=True)
        self._add_detail_row("home", "כתובת", rec.get("address"))
        self._add_detail_row("area", "אזור", rec.get("area"))
        self._add_detail_row("users", "נפשות", rec.get("souls"))
        self._add_detail_row("freq", "תדירות", rec.get("frequency"))
        self._add_detail_row("calendar", "חלוקה אחרונה", _fdate(rec.get("last_distribution") or ""))
        self._add_detail_row("calendar", "חלוקה הבאה", _fdate(rec.get("next_distribution") or ""))
        self._add_detail_row("hash", "סה״כ חלוקות", len(hist))
        self._add_detail_row("mail", "אימייל", rec.get("email"), ltr=True)
        self._add_detail_row("synagogue", "בית כנסת", rec.get("synagogue"))
        notes = (rec.get("notes") or "").strip()
        if notes:
            box = QFrame()
            box.setStyleSheet("background:#fffbeb; border:1px solid #fde68a; border-radius:6px;")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            bl.setSpacing(9)
            ic = QLabel(); ic.setPixmap(line_icon("note", 17, "#92400e"))
            ic.setFixedWidth(20); ic.setStyleSheet("background:transparent; border:none;")
            bl.addWidget(ic)
            nl = QLabel(notes)
            nl.setWordWrap(True)
            nl.setStyleSheet("color:#78350f; background:transparent; border:none;")
            bl.addWidget(nl, 1)
            self._detail_lay.addWidget(box)
        self._detail_lay.addStretch()

        # History
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
            reveal_in_folder(path)   # open Downloads with the file selected
            QMessageBox.information(self, "ייצוא הושלם",
                                    f"הרשימה נשמרה בתיקיית ההורדות ונפתחה התיקייה:\n{path}")
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

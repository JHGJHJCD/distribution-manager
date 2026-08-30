from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QAbstractItemView,
    QFrame, QPushButton, QMessageBox, QListWidget, QListWidgetItem, QScrollArea,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor
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


def _priority_display(rec: dict) -> str:
    labels = {4: "קבוע", 3: "ראשונה", 2: "שנייה"}
    pr = rec.get("priority")
    if pr in labels:
        return labels[pr]
    return "בירור" if "בירור" in (rec.get("priority_raw") or "") else ""


def _make_badge(text: str, colors: dict):
    """A rounded 'pill' QLabel for a priority/status tag (real widget QSS → truly
    round, never clipped — unlike an HTML span in a QLabel)."""
    c = colors.get(text)
    if not text or not c:
        return None
    bg, fg = c
    lab = QLabel(text)
    lab.setStyleSheet(
        f"background:{bg}; color:{fg}; padding:3px 14px; border-radius:11px;"
        f"font-weight:700; font-size:13px;")
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


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
        lay.setSpacing(10)
        lay.setContentsMargins(12, 12, 12, 12)

        title = QLabel("חיפוש מהיר")
        title.setObjectName("title")
        lay.addWidget(title)

        # Two columns: RIGHT = search + name list · LEFT = the selected person's
        # profile (details + history). In an RTL layout the first-added widget
        # sits on the right.
        main = QHBoxLayout()
        main.setSpacing(14)
        lay.addLayout(main, 1)

        # ── Right column: the search box + name results ────────────────────────
        search_panel = QFrame()
        search_panel.setObjectName("panel")
        search_panel.setFixedWidth(320)
        lp = QVBoxLayout(search_panel)
        lp.setContentsMargins(14, 14, 14, 14)
        lp.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setMinimumHeight(44)
        self.search_input.setPlaceholderText("חיפוש: שם, טלפון, ת״ז, כתובת, אימייל...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setStyleSheet(
            "QLineEdit{border:1.5px solid #cbd5e1; border-radius:10px; padding:0 12px;"
            " font-size:14px; background:#ffffff;}"
            "QLineEdit:focus{border-color:#0f766e;}")
        self.search_input.textChanged.connect(lambda: self._filter_timer.start(180))
        lp.addWidget(self.search_input)

        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#64748b; font-size:12px; font-weight:600;"
                                     " background:transparent; padding-right:2px;")
        lp.addWidget(self.count_lbl)

        self.results_list = QListWidget()
        self.results_list.setObjectName("names-list")
        self.results_list.setStyleSheet(
            "QListWidget#names-list { border:1px solid #e5e7eb; border-radius:10px;"
            "  background:#ffffff; outline:none; }"
            "QListWidget#names-list::item { padding:11px 14px; border-bottom:1px solid #f1f5f9;"
            "  color:#1f2937; }"
            "QListWidget#names-list::item:hover { background:#f4faf7; }"
            "QListWidget#names-list::item:selected {"
            "  background:#d3ede1; color:#0d2a4a; border-right:3px solid #0f766e; }")
        self.results_list.currentItemChanged.connect(self._on_result_selected)
        enable_touch_scroll(self.results_list)
        lp.addWidget(self.results_list, 1)

        btn_export = QPushButton("⭳  ייצוא הרשימה לאקסל")
        btn_export.setObjectName("neutral")
        btn_export.setMinimumHeight(34)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setToolTip("ייצא את הרשימה המסוננת (התוצאות) לאקסל בתיקיית ההורדות")
        btn_export.clicked.connect(self._export_results)
        lp.addWidget(btn_export)

        main.addWidget(search_panel)

        # ── Left column: the selected person's profile ─────────────────────────
        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)
        main.addLayout(right_panel, 1)

        # Profile header card: a soft green banner with the name, badges and the
        # phone(s) shown big — the two things looked up most often. Real QLabel
        # "pill" badges (not HTML spans) so the rounded corners never clip (#r92nz).
        self.detail_header = QFrame()
        self.detail_header.setObjectName("profile-head")
        self.detail_header.setStyleSheet(
            "QFrame#profile-head{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 #f0faf6, stop:1 #e3f3ec); border:1px solid #cfe8de;"
            " border-radius:14px;}")
        head_v = QVBoxLayout(self.detail_header)
        head_v.setContentsMargins(18, 14, 18, 14)
        head_v.setSpacing(8)
        # Row 1: name + badges (the layout the render code fills).
        name_row = QWidget()
        name_row.setStyleSheet("background:transparent;")
        self._hdr_lay = QHBoxLayout(name_row)
        self._hdr_lay.setContentsMargins(0, 0, 0, 0)
        self._hdr_lay.setSpacing(8)
        head_v.addWidget(name_row)
        # Row 2: the hero phone line (filled by _show_recipient).
        self._hero_phone = QLabel("")
        self._hero_phone.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._hero_phone.setStyleSheet("background:transparent; border:none;")
        self._hero_phone.setVisible(False)
        head_v.addWidget(self._hero_phone)
        right_panel.addWidget(self.detail_header)

        # Details card — hugs its content (no forced height, no empty filler) so
        # the history below can take the remaining room (the old sparse half-empty
        # card is gone).
        self.detail_card = QFrame()
        self.detail_card.setObjectName("panel")
        self._detail_lay = QGridLayout(self.detail_card)
        self._detail_lay.setContentsMargins(18, 14, 18, 14)
        self._detail_lay.setHorizontalSpacing(28)
        self._detail_lay.setVerticalSpacing(3)
        self._detail_lay.setColumnStretch(0, 1)
        self._detail_lay.setColumnStretch(1, 1)
        self._detail_count = 0
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.detail_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.detail_scroll.setMaximumHeight(300)
        enable_touch_scroll(self.detail_scroll)
        self.detail_scroll.setWidget(self.detail_card)
        right_panel.addWidget(self.detail_scroll)

        # History header row + actions. History gets generous room (stretch=1) —
        # the operator asked to see it comfortably.
        hist_row = QHBoxLayout()
        self.hist_title = QLabel("היסטוריית חלוקות")
        self.hist_title.setObjectName("section-header")
        hist_row.addWidget(self.hist_title)
        hist_row.addStretch()
        self.btn_print_card = QPushButton("🖶  הדפס כרטיס")
        self.btn_print_card.setObjectName("primary")
        self.btn_print_card.setMinimumHeight(34)
        self.btn_print_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_print_card.setToolTip("הדפס כרטיס עם פרטי המקבל + היסטוריית החלוקות שלו")
        self.btn_print_card.clicked.connect(self._print_card)
        self.btn_print_card.setEnabled(False)
        hist_row.addWidget(self.btn_print_card)

        self.btn_export_card = QPushButton("⭳  ייצוא לאקסל")
        self.btn_export_card.setObjectName("success")
        self.btn_export_card.setMinimumHeight(34)
        self.btn_export_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_card.setToolTip("ייצוא כל פרטי המקבל + היסטוריית החלוקות שלו לקובץ Excel נפרד")
        self.btn_export_card.clicked.connect(self._export_card)
        self.btn_export_card.setEnabled(False)
        hist_row.addWidget(self.btn_export_card)

        self.btn_del_hist = QPushButton("מחק רישום")
        self.btn_del_hist.setObjectName("danger")
        self.btn_del_hist.setStyleSheet(_SMALL_BTN)
        self.btn_del_hist.setToolTip("מחק את רישום החלוקה המסומן מההיסטוריה של המקבל "
                                     "(למחיקת חלוקה נמחקת/ישנה שנשארה)")
        self.btn_del_hist.clicked.connect(self._delete_hist_record)
        self.btn_del_hist.setEnabled(False)
        hist_row.addWidget(self.btn_del_hist)
        right_panel.addLayout(hist_row)

        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(len(HIST_COLS))
        self.hist_table.setHorizontalHeaderLabels(HIST_COLS)
        apply_header_icons(self.hist_table)
        self.hist_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.hist_table.setAlternatingRowColors(True)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist_table.verticalHeader().setDefaultSectionSize(30)
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
            self.btn_export_card.setEnabled(False)
            self.btn_del_hist.setEnabled(False)
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
        self._detail_lay.setRowStretch(self._detail_count // 2 + 2, 0)
        self._detail_count = 0

    def _add_detail_row(self, icon_name, label, value, ltr=False):
        value = (str(value).strip() if value not in (None, "") else "")
        if not value:
            return
        row = QWidget()
        g = QHBoxLayout(row)
        g.setContentsMargins(0, 4, 0, 4)
        g.setSpacing(9)
        ic = QLabel()
        ic.setPixmap(line_icon(icon_name, 17, "#0f766e"))
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
        # RTL: first field on the right (col 1), second on the left (col 0).
        r, c = divmod(self._detail_count, 2)
        self._detail_lay.addWidget(row, r, 1 - c)
        self._detail_count += 1

    def _clear_header(self):
        while self._hdr_lay.count():
            it = self._hdr_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _show_empty_profile(self, msg="בחר מקבל מהרשימה כדי לראות את פרטיו"):
        self._clear_header()
        lab = QLabel(msg)
        lab.setStyleSheet("color:#64748b; font-size:14px; padding:6px 0; background:transparent;")
        lab.setWordWrap(True)
        self._hdr_lay.addWidget(lab)
        self._hdr_lay.addStretch()
        if hasattr(self, "_hero_phone"):
            self._hero_phone.setVisible(False)
        self._clear_details()
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_title.setText("היסטוריית חלוקות")
        if hasattr(self, "btn_del_hist"):
            self.btn_del_hist.setEnabled(False)
        if hasattr(self, "btn_export_card"):
            self.btn_export_card.setEnabled(False)

    def _show_recipient(self, rec_id):
        rec = db.get_recipient(rec_id)
        if not rec:
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self.btn_export_card.setEnabled(False)
            self.btn_del_hist.setEnabled(False)
            self._show_empty_profile()
            return
        self._current_rec_id = rec_id
        self.btn_print_card.setEnabled(True)
        self.btn_export_card.setEnabled(True)
        self.btn_del_hist.setEnabled(True)

        hist = db.get_distributions_for_recipient(rec["id"])

        # Header — name + priority + status badges (real pill widgets)
        self._clear_header()
        name_lbl = QLabel(rec.get("full_name", "") or "")
        name_lbl.setStyleSheet(
            "font-size:20px; font-weight:800; color:#0d2a4a; background:transparent;")
        name_lbl.setWordWrap(True)
        self._hdr_lay.addWidget(name_lbl)
        for text, colors in ((_priority_display(rec), PRIORITY_BADGES),
                             (rec.get("status", ""), STATUS_BADGES)):
            badge = _make_badge(text, colors)
            if badge is not None:
                self._hdr_lay.addWidget(badge)
        self._hdr_lay.addStretch()

        # Hero phone line in the header — the number is what's looked up most.
        phones = "   ·   ".join(p for p in [rec.get("phone1"), rec.get("phone2"),
                                            rec.get("phone3")] if p)
        if phones:
            self._hero_phone.setText(f"📞  {phones}")
            self._hero_phone.setStyleSheet(
                "color:#0d2a4a; font-size:16px; font-weight:700; background:transparent;"
                " border:none;")
            self._hero_phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self._hero_phone.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._hero_phone.setVisible(True)
        else:
            self._hero_phone.setText("אין מספר טלפון")
            self._hero_phone.setStyleSheet("color:#94a3b8; font-size:13px; background:transparent;"
                                           " border:none;")
            self._hero_phone.setVisible(True)

        # Detail rows with dignified icons
        self._clear_details()
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
        # No-show alert (v2.60): a red banner when the recipient is on a run of
        # consecutive recorded "לא הגיע" at/over the Settings threshold.
        thr = db.get_no_show_threshold()
        streak = db.consecutive_no_shows(rec["id"]) if thr else 0
        if thr and streak >= thr:
            warn = QFrame()
            warn.setStyleSheet("background:#fee2e2; border:1px solid #fecaca; border-radius:6px;")
            wl = QHBoxLayout(warn)
            wl.setContentsMargins(10, 8, 10, 8)
            wl.setSpacing(9)
            wi = QLabel("⚠")
            wi.setFixedWidth(20)
            wi.setStyleSheet("color:#b91c1c; font-weight:800; background:transparent; border:none;")
            wl.addWidget(wi)
            wt = QLabel(f"לא הגיע לקחת {streak} פעמים ברצף — כדאי לבדוק מולו אם עדיין זקוק לחלוקה.")
            wt.setWordWrap(True)
            wt.setStyleSheet("color:#7f1d1d; font-weight:700; background:transparent; border:none;")
            wl.addWidget(wt, 1)
            warn_row = (self._detail_count + 1) // 2
            self._detail_lay.addWidget(warn, warn_row, 0, 1, 2)
            self._detail_count = (warn_row + 1) * 2

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
            # Notes span the full width, on their own row below the field pairs.
            note_row = (self._detail_count + 1) // 2
            self._detail_lay.addWidget(box, note_row, 0, 1, 2)
            self._detail_count = (note_row + 1) * 2

        # History
        self.hist_title.setText(f"היסטוריית חלוקות ({len(hist)})")
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_table.setRowCount(len(hist))
        for r, entry in enumerate(hist):
            # received=0 → a recorded no-show (#yjcny); mark it clearly instead of
            # letting it read like an ordinary receipt. Older rows lack the flag
            # (default 1 = received).
            missed = (entry.get("received", 1) or 0) == 0
            what = "✗ לא קיבל" if missed else entry.get("what_dist", "")
            vals = [_fdate(entry.get("dist_date", "")), what,
                    str(entry.get("quantity", "") or ""), entry.get("distributor", ""),
                    entry.get("notes", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(ALIGN_RIGHT)
                if missed:
                    item.setForeground(QColor("#b91c1c"))
                # Keep the record id on every cell so a selected row can be deleted.
                item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
                self.hist_table.setItem(r, c, item)

    def _delete_hist_record(self):
        """Remove the selected distribution record from this recipient's history.
        Fixes stale/old records that linger in search (e.g. legacy rows with no
        batch link, which the 'חלוקות' tab can't delete)."""
        if not self._current_rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        row = self.hist_table.currentRow()
        item = self.hist_table.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.information(self, "", "בחר שורת חלוקה למחיקה")
            return
        dist_id = item.data(Qt.ItemDataRole.UserRole)
        if dist_id is None:
            return
        when = self.hist_table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "מחיקת רישום חלוקה",
            f"למחוק את רישום החלוקה מתאריך {when} מההיסטוריה של המקבל?\n"
            "פעולה זו אינה הפיכה (מוחקת רק את הרישום, לא את המקבל).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        db.delete_distribution(dist_id)
        self._show_recipient(self._current_rec_id)   # re-render the history
        if self.main_win:
            self.main_win.status_msg("רישום החלוקה נמחק")

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

    def _export_card(self):
        """Export the selected recipient — all fields + distribution history — to
        its own Excel file in the recipients export folder."""
        if not self._current_rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        rec = db.get_recipient(self._current_rec_id)
        if not rec:
            return
        hist = db.get_distributions_for_recipient(self._current_rec_id)
        try:
            from utils.excel_utils import export_single_recipient_to_excel
            with busy_cursor():
                path = export_single_recipient_to_excel(rec, hist)
            reveal_in_folder(path)
            QMessageBox.information(self, "ייצוא הושלם",
                                   f"פרטי המקבל נשמרו בקובץ Excel נפרד ונפתחה התיקייה:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה בייצוא", str(e))

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QAbstractItemView,
    QFrame, QPushButton, QMessageBox, QListWidget, QListWidgetItem, QScrollArea,
    QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QFont, QColor
import database as db
from utils.ui import (search_icon, busy_cursor, line_icon, enable_touch_scroll,
                      PRIORITY_BADGES, STATUS_BADGES, HOLIDAY_BADGES, ALIGN_RIGHT,
                      reveal_in_folder, apply_header_icons, attach_empty_state,
                      refresh_empty_state)
from utils import timefmt
import holidays
from utils.excel_utils import export_recipients_to_excel
from utils.print_view import print_recipient_card

_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"


from utils.timefmt import fdate as _fdate   # one shared copy (סקירת בשלות 26/9/2026)


HIST_COLS = ["תאריך", "מה חולק", "כמות", "מחלק", "הערות", ""]
_HIST_DEL_COL = len(HIST_COLS) - 1      # the "🗑 מחק" cell at the end of every history row (task 10)
_HIST_DEL_W = 74


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


_DETAIL_COLS = 3        # the profile card shows its details in three columns (v3.78)
_DETAIL_MAX_H = 420     # safety cap — beyond this the card scrolls (tiny windows only)


class _DeleteCellDelegate(QStyledItemDelegate):
    """Paints the history row's "🗑 מחק" cell: red bold text centred in the WHOLE cell.
    The app stylesheet forces `color` + 11/14px padding on every table item (so
    setForeground is ignored and a 30px row leaves ~8px for text) — painting the
    text ourselves keeps it red and never clipped."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        f = QFont(opt.font); f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor("#b91c1c"))
        painter.drawText(option.rect, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()


class _FitScrollArea(QScrollArea):
    """A QScrollArea whose height follows its content's height-for-width, so the
    details card is exactly as tall as its three columns need — no scrollbar and no
    empty room. Qt's own hasHeightForWidth is not overridable, so fit() measures the
    content and publishes it as the preferred AND maximum height (on every resize and
    after every refill). Only in a really short window does it give way: down to a
    small minimum it then scrolls, instead of overlapping the history below."""

    _MIN_H = 84

    def __init__(self, *a):
        super().__init__(*a)
        self._want_h = 0

    def fit(self):
        w = self.widget()
        if w is None or w.layout() is None:
            return
        width = self.viewport().width()
        if width <= 1:
            return
        h = min(w.layout().totalHeightForWidth(width) + 2 * self.frameWidth(), _DETAIL_MAX_H)
        if h != self._want_h:
            self._want_h = h
            self.setMinimumHeight(min(h, self._MIN_H))
            self.setMaximumHeight(h)
            self.updateGeometry()

    def sizeHint(self):
        sh = super().sizeHint()
        if self._want_h:
            sh.setHeight(self._want_h)
        return sh

    def setWidget(self, w):
        super().setWidget(w)
        w.installEventFilter(self)      # content re-laid-out (rows shown/added) → re-fit

    def eventFilter(self, obj, ev):
        if obj is self.widget() and ev.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, self.fit)      # after Qt has shown the new child rows
        return super().eventFilter(obj, ev)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()


class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent      # היה חסר — מחיקת רישום חלוקה קרסה ב-AttributeError
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
        btn_export.setToolTip("ייצוא התוצאות המוצגות לאקסל (בתיקיית ההורדות)")
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

        # Details card — THREE columns grouped by meaning (v3.78, משימה 9: קשר וכתובת ·
        # משפחה · חלוקות), hugging its content (no forced height, no empty filler) so
        # the history below can take the remaining room. The scroll area is only a
        # safety net for absurdly small windows: it asks for exactly the card's
        # height-for-width, so normally there is nothing to scroll.
        self.detail_card = QFrame()
        self.detail_card.setObjectName("panel")
        self._detail_lay = QGridLayout(self.detail_card)
        self._detail_lay.setContentsMargins(18, 8, 18, 8)
        self._detail_lay.setHorizontalSpacing(22)
        self._detail_lay.setVerticalSpacing(1)
        # contact & address (e-mail, address, synagogue) holds the longest values →
        # a bit more room than the family / distributions columns.
        for c, stretch in enumerate((4, 3, 3)):
            self._detail_lay.setColumnStretch(c, stretch)
            self._detail_lay.setColumnMinimumWidth(c, 0)
        self._detail_count = 0
        self._col_rows = [0] * _DETAIL_COLS
        self.detail_scroll = _FitScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.btn_print_card.setToolTip("הדפסת כרטיס: פרטי המקבל והיסטוריית החלוקות שלו")
        self.btn_print_card.clicked.connect(self._print_card)
        self.btn_print_card.setEnabled(False)
        hist_row.addWidget(self.btn_print_card)

        self.btn_export_card = QPushButton("⭳  ייצוא לאקסל")
        self.btn_export_card.setObjectName("success")
        self.btn_export_card.setMinimumHeight(34)
        self.btn_export_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_card.setToolTip("ייצוא פרטי המקבל והיסטוריית החלוקות שלו לקובץ אקסל")
        self.btn_export_card.clicked.connect(self._export_card)
        self.btn_export_card.setEnabled(False)
        hist_row.addWidget(self.btn_export_card)

        right_panel.addLayout(hist_row)

        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(len(HIST_COLS))
        self.hist_table.setHorizontalHeaderLabels(HIST_COLS)
        apply_header_icons(self.hist_table)
        self.hist_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.hist_table.setAlternatingRowColors(True)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # an explained empty state instead of bare column headers over nothing
        attach_empty_state(self.hist_table, "עדיין לא נרשמו חלוקות למקבל זה")
        self.hist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist_table.verticalHeader().setDefaultSectionSize(30)
        hdr = self.hist_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)
        # task 10: the delete cell is plain text + cellClicked (a widget in a cell gets
        # clipped / not measured here) in a Fixed column ResizeToContents can't shrink.
        hdr.setSectionResizeMode(_HIST_DEL_COL, QHeaderView.ResizeMode.Fixed)
        self.hist_table.setColumnWidth(_HIST_DEL_COL, _HIST_DEL_W)
        self.hist_table.setItemDelegateForColumn(_HIST_DEL_COL, _DeleteCellDelegate(self.hist_table))
        self.hist_table.cellClicked.connect(self._on_hist_cell_clicked)
        self.hist_table.verticalHeader().setVisible(False)
        # In a short window the history is the part that gives way (it scrolls on its
        # own); the details card above never gets squeezed into overlapping it.
        self.hist_table.setMinimumHeight(60)
        enable_touch_scroll(self.hist_table)
        right_panel.addWidget(self.hist_table, 1)
        # v3.39 — מיילים שנשלחו למקבל הזה (מסך 'מיילים')
        self.lbl_mails = QLabel("")
        self.lbl_mails.setWordWrap(True)
        self.lbl_mails.setStyleSheet("color:#475569; font-size:12.5px; background:transparent;")
        right_panel.addWidget(self.lbl_mails)
        # v3.63 — היסטוריית שינויים בכרטיס (בקשת רון): השינויים האחרונים + "הכל…"
        chg_row = QHBoxLayout()
        chg_row.setSpacing(8)
        self.lbl_changes = QLabel("")
        self.lbl_changes.setWordWrap(True)
        self.lbl_changes.setStyleSheet("color:#475569; font-size:12.5px; background:transparent;")
        chg_row.addWidget(self.lbl_changes, 1)
        self.btn_changes = QPushButton("היסטוריית שינויים…")
        self.btn_changes.setObjectName("neutral")
        self.btn_changes.setStyleSheet(_SMALL_BTN)      # compact: every pixel of height counts here
        self.btn_changes.setToolTip("היסטוריית השינויים בכרטיס: מה השתנה, מתי ובאיזה מחשב")
        self.btn_changes.clicked.connect(self._open_changes)
        self.btn_changes.setEnabled(False)
        chg_row.addWidget(self.btn_changes, 0, Qt.AlignmentFlag.AlignTop)
        right_panel.addLayout(chg_row)

    # ── data ───────────────────────────────────────────────────────────────────
    def refresh(self):
        self._all_rows = db.get_all_recipients()
        self._run_search(keep_id=self._current_rec_id)

    def _run_search(self, keep_id=None):
        query = self.search_input.text()
        self._results = db.filter_recipients(self._all_rows, query)
        self._populate_results(keep_id)

    def _populate_results(self, keep_id=None):
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
            # רענון (סנכרון/שמירה במסך אחר) לא מחליף את הכרטיס שהמשתמש קורא:
            # אם המקבל המוצג עדיין בתוצאות — נשארים עליו; אחרת ההתאמה הטובה ביותר.
            keep = keep_id if keep_id is not None else None
            row = next((i for i, r in enumerate(self._results)
                        if keep is not None and r.get("id") == keep), 0)
            self.results_list.setCurrentRow(row)
        else:
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self.btn_export_card.setEnabled(False)
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
        self._detail_count = 0
        self._col_rows = [0] * _DETAIL_COLS

    def _grid_col(self, col):
        """Logical column 0 = the first (right-most in Hebrew) → the grid column.
        QGridLayout already mirrors itself under RTL, so this is the identity;
        kept as one named place in case the layout direction is ever forced."""
        return col

    def _add_detail_row(self, icon_name, label, value, ltr=False, col=0):
        """One 'icon · label · value' line in logical column `col` (0 = right-most).
        Rows stack down the column; empty values are skipped (no gap)."""
        value = (str(value).strip() if value not in (None, "") else "")
        if not value:
            return
        row = QWidget()
        g = QHBoxLayout(row)
        g.setContentsMargins(0, 2, 0, 2)
        g.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(line_icon(icon_name, 16, "#0f766e"))
        ic.setFixedWidth(18)
        ic.setStyleSheet("background:transparent; border:none;")
        g.addWidget(ic)
        lab = QLabel(label)
        lab.setStyleSheet("color:#64748b; background:transparent; border:none;")
        lab.setFixedWidth(lab.fontMetrics().horizontalAdvance(label) + 4)
        g.addWidget(lab)
        val = QLabel(value)
        val.setStyleSheet("color:#1f2937; font-weight:600; background:transparent; border:none;")
        val.setWordWrap(True)
        val.setToolTip(value)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Ignored → a long unbreakable value (e-mail) is clipped instead of pushing
        # the whole column wider than its share; the full text is in the tooltip.
        val.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        val.setMinimumWidth(0)
        # Always flush against the label (the physical right edge): a bare number or
        # date is LTR text and would otherwise drift to the far LEFT of its wide
        # cell — next to the neighbouring column, reading as that column's value.
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
                         | Qt.AlignmentFlag.AlignVCenter)
        if ltr:
            val.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        g.addWidget(val, 1)
        # +1: row 0 of every column is the group caption.
        self._detail_lay.addWidget(row, self._col_rows[col] + 1, self._grid_col(col))
        self._col_rows[col] += 1
        self._detail_count += 1

    def _add_group_caption(self, col, text):
        """Small muted caption on top of a column (only when the column has rows)."""
        cap = QLabel(text)
        cap.setStyleSheet("color:#0f766e; font-size:12px; font-weight:700;"
                          " background:transparent; border:none;")
        self._detail_lay.addWidget(cap, 0, self._grid_col(col))

    def _add_span_widget(self, widget):
        """Full-width banner (no-show alert, notes) on its own row below all three
        columns; later rows/banners continue below it."""
        row = max(self._col_rows) + 1
        self._detail_lay.addWidget(widget, row, 0, 1, _DETAIL_COLS)
        self._col_rows = [row] * _DETAIL_COLS
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
        refresh_empty_state(self.hist_table)
        self.hist_title.setText("היסטוריית חלוקות")
        if hasattr(self, "lbl_changes"):
            self.lbl_changes.setText("")
            self.btn_changes.setEnabled(False)
        if hasattr(self, "btn_export_card"):
            self.btn_export_card.setEnabled(False)

    def _show_recipient(self, rec_id):
        rec = db.get_recipient(rec_id)
        if not rec:
            self._current_rec_id = None
            self.btn_print_card.setEnabled(False)
            self.btn_export_card.setEnabled(False)
            self._show_empty_profile()
            return
        self._current_rec_id = rec_id
        self.btn_print_card.setEnabled(True)
        self.btn_export_card.setEnabled(True)

        hist = db.get_distributions_for_recipient(rec["id"])

        # Header — name + priority + status badges (real pill widgets)
        self._clear_header()
        name_lbl = QLabel(rec.get("full_name", "") or "")
        name_lbl.setStyleSheet(
            "font-size:20px; font-weight:800; color:#0d2a4a; background:transparent;")
        name_lbl.setWordWrap(True)
        self._hdr_lay.addWidget(name_lbl)
        for text, colors in ((_priority_display(rec), PRIORITY_BADGES),
                             ("חגים" if holidays.is_supported(rec) else "", HOLIDAY_BADGES),
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
        # Three columns, right → left: contact & address · family · distributions.
        # (Which fields go where is a design call — grouped by meaning, balanced
        # to 4/4/5 rows; the header already carries name, badges and phones.)
        groups = (
            ("קשר וכתובת", (
                ("home", "כתובת", rec.get("address"), False),
                ("area", "אזור", rec.get("area"), False),
                ("mail", "אימייל", rec.get("email"), True),
                ("synagogue", "בית כנסת", rec.get("synagogue"), False))),
            ("משפחה", (
                ("id", "ת״ז בעל", rec.get("id_number"), True),
                ("id", "ת״ז אשה", rec.get("spouse_id_number"), True),
                ("users", "נפשות", rec.get("souls"), False))),
            ("חלוקות", (
                ("freq", "תדירות", rec.get("frequency"), False),
                ("calendar", "נתמך חגים", holidays.display(rec), False),
                ("calendar", "חלוקה אחרונה", _fdate(rec.get("last_distribution") or ""), False),
                ("calendar", "חלוקה הבאה", _fdate(rec.get("next_distribution") or ""), False),
                ("hash", "סה״כ חלוקות", len(hist), False))),
        )
        for col, (caption, fields) in enumerate(groups):
            for icon_name, label, value, ltr in fields:
                self._add_detail_row(icon_name, label, value, ltr=ltr, col=col)
            if self._col_rows[col]:
                self._add_group_caption(col, caption)
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
            self._add_span_widget(warn)

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
            # Notes span the full width, on their own row below the three columns.
            self._add_span_widget(box)

        # History
        self.hist_title.setText(f"היסטוריית חלוקות ({len(hist)})")
        try:
            mails = db.get_mails_for_recipient(rec["id"], rec.get("guid") or "")
        except Exception:
            mails = []
        if mails:
            last = mails[0]
            self.lbl_mails.setText(
                f"✉ מיילים שנשלחו: {len(mails)} · אחרון: {timefmt.datetime_str(last['sent_at'])} — "
                f"{last['subject']}" + (" (נכשל)" if last.get('status') == 'failed' else ""))
        else:
            self.lbl_mails.setText("")
        # v3.63 — the last card changes, newest first (full list in the dialog).
        try:
            changes = db.get_changes_for_recipient(rec["id"], rec.get("guid") or "")
        except Exception:
            changes = []
        if changes:
            from widgets import change_line
            self.lbl_changes.setText(
                f"📝 שינויים בכרטיס: {len(changes)} · אחרון: {change_line(changes[0])}")
        else:
            self.lbl_changes.setText("📝 עדיין לא נרשמו שינויים בכרטיס")
        self.btn_changes.setEnabled(True)
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_table.setRowCount(len(hist))
        for r, entry in enumerate(hist):
            # received=0 → a recorded no-show (#yjcny); mark it clearly instead of
            # letting it read like an ordinary receipt. Older rows lack the flag
            # (default 1 = received).
            missed = (entry.get("received", 1) or 0) == 0
            what = "✗ לא קיבל" if missed else entry.get("what_dist", "")
            # v3.75: a holiday distribution is tagged in the family's history
            hol = holidays.dist_label(entry.get("holiday"))
            if hol:
                what = f"🎉 {hol}" + (f" · {what}" if what else "")
            vals = [_fdate(entry.get("dist_date", "")), what,
                    str(entry.get("quantity", "") or ""), entry.get("distributor", ""),
                    entry.get("notes", "")]
            vals.append("🗑 מחק")        # task 10 — delete this very row
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(ALIGN_RIGHT)
                if c == _HIST_DEL_COL:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor("#b91c1c"))
                    f = item.font(); f.setBold(True); item.setFont(f)
                    item.setToolTip("מחיקת רישום החלוקה הזה מההיסטוריה של המקבל")
                    item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
                    self.hist_table.setItem(r, c, item)
                    continue
                if c == 0:
                    # "לפני שבועיים" on hover — like the other history tables
                    item.setToolTip(timefmt.relative(entry.get("dist_date", "") or ""))
                if missed:
                    item.setForeground(QColor("#b91c1c"))
                # Keep the record id on every cell (the delete cell reads it too).
                item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
                self.hist_table.setItem(r, c, item)
        refresh_empty_state(self.hist_table)

    def _on_hist_cell_clicked(self, row, col):
        """task 10 — a click on the "🗑 מחק" cell deletes THAT row's record."""
        if col == _HIST_DEL_COL:
            self._delete_hist_record(row)

    def _delete_hist_record(self, row=None):
        """Remove one distribution record from this recipient's history (the row whose
        delete cell was clicked; row=None → the currently selected row). Fixes
        stale/old records that linger in search (e.g. legacy rows with no batch link,
        which the 'חלוקות' tab can't delete). Goes through db.delete_distribution —
        the one path that re-derives last/next dates and logs the sync op."""
        if not self._current_rec_id:
            QMessageBox.information(self, "", "בחר מקבל תחילה")
            return
        if row is None:
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
        # המחיקה משנה את "חלוקה אחרונה/הבאה" של המקבל — רשימת השבוע, כל המקבלים
        # וחלוקות קודמות חייבים להתרענן, לא רק הכרטיס הזה.
        if self.main_win:
            self.main_win.refresh_all()
        else:
            self._show_recipient(self._current_rec_id)
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

    def _open_changes(self):
        """v3.63 — the full change history of the shown recipient."""
        if not self._current_rec_id:
            return
        rec = db.get_recipient(self._current_rec_id)
        if not rec:
            return
        from widgets import ChangeHistoryDialog
        ChangeHistoryDialog(rec, self).exec()

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
                path = export_single_recipient_to_excel(
                    rec, hist, db.get_changes_for_recipient(rec["id"], rec.get("guid") or ""))
            reveal_in_folder(path)
            QMessageBox.information(self, "ייצוא הושלם",
                                   f"פרטי המקבל נשמרו בקובץ Excel נפרד ונפתחה התיקייה:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה בייצוא", str(e))

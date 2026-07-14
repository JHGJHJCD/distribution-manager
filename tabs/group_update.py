import os
import re
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QLineEdit,
    QSpinBox, QMessageBox, QAbstractItemView, QFileDialog, QSizePolicy,
    QFrame, QGridLayout, QGraphicsDropShadowEffect, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QIcon
from datetime import date
from widgets import DateEdit, ProductsEditor
import database as db
import selection
from utils.backup import auto_backup_async
from utils.excel_utils import (export_distribution_to_excel, export_full_distribution_to_excel,
                               export_volunteer_checklist_to_excel, import_volunteer_checklist)
from utils.print_view import print_distribution_list
from utils.ui import (busy_cursor, attach_empty_state, refresh_empty_state, ALIGN_RIGHT,
                      enable_touch_scroll, search_icon, line_icon, reveal_in_folder,
                      apply_header_icons, show_score_breakdown)
from utils import email_utils


class _InboxWorker(QThread):
    """Polls the Gmail inbox (off the UI thread) for volunteer-checklist replies
    and hands back the saved file paths."""
    found = pyqtSignal(object)   # list[str] of saved file paths (may be empty)

    def __init__(self, save_dir, parent=None):
        super().__init__(parent)
        self._save_dir = save_dir

    def run(self):
        try:
            self.found.emit(email_utils.fetch_unseen_checklists(self._save_dir))
        except Exception:
            self.found.emit([])
from styles import (OVERDUE_BG, OVERDUE_FG, TODAY_BG, TODAY_FG, WEEK_BG, WEEK_FG,
                    SELECTED_BG, SELECTED_FG)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# colours for one-time picks (+ reserve)
_RESERVE_BG, _RESERVE_FG = "#ede7f6", "#5e35b1"
_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"

# Glossy "glass" select-all / clear-all buttons (green = select, red = clear).
_GLASS_GREEN_BTN = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #34d399, stop:0.5 #10b981, stop:1 #059669);"
    " color:white; font-weight:800; font-size:12px; border:none;"
    " border-radius:9px; padding:5px 16px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #6ee7b7, stop:0.5 #34d399, stop:1 #10b981);}"
    "QPushButton:pressed{background:#047857; padding-top:6px;}")
_GLASS_RED_BTN = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #f87171, stop:0.5 #ef4444, stop:1 #dc2626);"
    " color:white; font-weight:800; font-size:12px; border:none;"
    " border-radius:9px; padding:5px 16px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #fca5a5, stop:0.5 #f87171, stop:1 #ef4444);}"
    "QPushButton:pressed{background:#b91c1c; padding-top:6px;}")

# ── 2026 redesign palette + reusable button styles (visual only) ─────────────
_BG          = "#f5f7fb"
_CARD_QSS    = ("QFrame#ui-card{background:#ffffff; border:1px solid #e6eaf2;"
                " border-radius:12px;}")
_BTN_PRIMARY = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2b95ef,stop:1 #1565c0);"
    " color:#fff; border:none; border-radius:9px; font-weight:800; font-size:13.5px;"
    " padding:0 18px; min-height:38px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #3ba0f5,stop:1 #1976d2);}"
    "QPushButton:pressed{background:#0d47a1;}")
_BTN_SUCCESS = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #34d399,stop:1 #059669);"
    " color:#fff; border:none; border-radius:9px; font-weight:800; font-size:13.5px;"
    " padding:0 18px; min-height:38px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #6ee7b7,stop:1 #10b981);}"
    "QPushButton:pressed{background:#047857;}")
_BTN_DANGER  = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f87171,stop:1 #dc2626);"
    " color:#fff; border:none; border-radius:9px; font-weight:800; font-size:13.5px;"
    " padding:0 18px; min-height:38px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fca5a5,stop:1 #ef4444);}"
    "QPushButton:pressed{background:#b91c1c;}")
_BTN_GHOST   = (
    "QPushButton{background:#ffffff; color:#1f2937; border:1px solid #d7dfea;"
    " border-radius:9px; font-weight:700; font-size:13.5px; padding:0 16px; min-height:38px;}"
    "QPushButton:hover{background:#f8fafc; border-color:#c2cee0;}"
    "QPushButton:pressed{background:#eef2f8;}")
# The hero action of this screen — printing the distribution list. A rich indigo
# gradient, larger size and heavier weight make it the single most prominent
# button in the bottom bar (paired with a soft drop-shadow, added in code).
_BTN_PRINT   = (
    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #6366f1,stop:1 #4338ca);"
    " color:#fff; border:none; border-radius:12px; font-weight:900; font-size:16px;"
    " letter-spacing:0.3px; padding:0 30px; min-height:52px;}"
    "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #818cf8,stop:1 #4f46e5);}"
    "QPushButton:pressed{background:#3730a3;}")
_CHIP_QSS    = ("QLabel{background:#eef2f8; color:#475569; border:none; border-radius:16px;"
                " padding:5px 13px; font-size:12.5px; font-weight:700;}")
_CHIP_GREEN  = ("QLabel{background:#e6f6ef; color:#059669; border:none; border-radius:16px;"
                " padding:5px 13px; font-size:12.5px; font-weight:700;}")


def _card_shadow(widget):
    """Subtle elevation — a soft outer shadow drawn by a wrapper, NOT a
    QGraphicsDropShadowEffect (that effect breaks a card's minimum-height
    negotiation inside a flex layout and squeezes the content). The card's own
    hairline border plus this shadow read as a lifted card."""
    widget.setStyleSheet(widget.styleSheet() +
                         " QFrame#ui-card, QFrame#bottom-bar{}")  # no-op hook
    # Real soft shadow via a graphics effect is avoided; the hairline border on
    # the card already defines it on the grey surface.


def _make_card(title: str, icon_name: str = None, hint: str = None, shadow: bool = True):
    """A white rounded card with a header row. Returns (frame, content_layout)
    where content_layout is a QVBoxLayout to add the card's body into."""
    frame = QFrame()
    frame.setObjectName("ui-card")
    frame.setStyleSheet(_CARD_QSS)
    # Fixed height (= content) so a card never balloons to fill spare space and
    # open big internal gaps; spare vertical space goes to the list instead.
    frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    if shadow:
        _card_shadow(frame)
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(18, 9, 18, 9)
    outer.setSpacing(7)

    head = QHBoxLayout()
    head.setSpacing(9)
    if icon_name:
        ic = QLabel()
        ic.setPixmap(line_icon(icon_name, 20, "#1e78d6"))
        ic.setStyleSheet("background:transparent; border:none;")
        head.addWidget(ic)
    tl = QLabel(title)
    tl.setStyleSheet("color:#0d3b73; font-size:15px; font-weight:800; background:transparent; border:none;")
    head.addWidget(tl)
    if hint:
        hl = QLabel(hint)
        hl.setStyleSheet("color:#94a3b8; font-size:12px; background:transparent; border:none;")
        head.addStretch()
        head.addWidget(hl)
    else:
        head.addStretch()
    outer.addLayout(head)
    return frame, outer


def _field(label_text: str, widget, maxw: int = None):
    """Label-over-field column (returns a QVBoxLayout) with a uniform field height."""
    box = QVBoxLayout()
    box.setSpacing(5)
    lab = QLabel(label_text)
    lab.setStyleSheet("color:#64748b; font-size:12.5px; font-weight:700; background:transparent; border:none;")
    box.addWidget(lab)
    widget.setMinimumHeight(38)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    if maxw:
        widget.setMaximumWidth(maxw)
    box.addWidget(widget)
    return box


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
        self._rows_data = []             # full weekly + one-time list (unfiltered)
        self._checked_ids: set = set()   # who is currently ticked (survives search)
        self._seen_ids: set = set()      # ids already shown (for pre-checking new picks)
        self._search_text = ""           # quick-search filter over the list
        self._extra_ids: set = set()     # one-time picks added from the one-time tab
        self._reserve_ids: set = set()   # which of those are reserves
        self._load_extras()
        self._build_ui()
        self._update_mode_controls()
        self.refresh()
        self._setup_inbox_poller()

    # ── Auto-import: watch the inbox for volunteer replies ─────────────────────
    def _setup_inbox_poller(self):
        """Poll Gmail for volunteer-checklist replies and import them
        automatically, so the operator never has to touch a file. Runs quietly in
        the background whenever email is configured."""
        self._inbox_worker = None
        self._inbox_dir = os.path.join(tempfile.gettempdir(), "ManhalHaluka_inbox")
        self._inbox_timer = QTimer(self)
        self._inbox_timer.timeout.connect(self._poll_inbox)
        # first check ~15s after launch, then every 2 minutes
        QTimer.singleShot(15000, self._poll_inbox)
        self._inbox_timer.start(120000)

    def _poll_inbox(self):
        if self._inbox_worker is not None and self._inbox_worker.isRunning():
            return
        if not email_utils.is_configured():
            return
        self._inbox_worker = _InboxWorker(self._inbox_dir, self)
        self._inbox_worker.found.connect(self._on_inbox_found)
        self._inbox_worker.start()

    def _on_inbox_found(self, paths):
        if not paths:
            return
        total = 0
        names = []
        received_ids = []
        for p in paths:
            try:
                n, meta, ids = self._apply_checklist_file(p, confirm=False)
            except Exception:
                n, meta, ids = 0, {}, []
            total += n
            received_ids += ids
            if meta.get("dist_name"):
                names.append(meta["dist_name"])
            try:
                os.remove(p)
            except Exception:
                pass
        if total:
            if self.main_win:
                self.main_win.status_msg(f"התקבלו {total} חלוקות ממתנדב במייל ונרשמו אוטומטית ✓")
                self.main_win.refresh_all()
            # Tick the people the volunteer marked as 'הגיע' right here in the
            # list, so the operator sees at a glance who received.
            self._mark_received_in_table(received_ids)
            title = " · ".join(dict.fromkeys(names)) or "רשימת חלוקה"
            QMessageBox.information(
                self, "תוצאות מתנדב התקבלו במייל",
                f"התקבלה במייל רשימה שמולאה על ידי המתנדב ({title}).\n"
                f"נרשמו אוטומטית {total} חלוקות להיסטוריה ✓\n"
                f"המקבלים שהגיעו סומנו ברשימה.")

    def _mark_received_in_table(self, ids):
        """Check the checkbox of every recipient the volunteer reported as
        received, if they're present in the current list."""
        idset = {int(i) for i in ids if i is not None}
        if not idset:
            return
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk is not None and chk.data(Qt.ItemDataRole.UserRole) in idset:
                chk.setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._update_counts()

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
        # ── 2026 redesign: cards on a soft grey surface + a sticky bottom bar.
        #    Layout/visuals only — every widget, signal and method is unchanged.
        self.setObjectName("group-tab")
        self.setStyleSheet(f"QWidget#group-tab{{background:{_BG};}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The detail/product/volunteer cards live in their own scroll region (so
        # a long product list never squeezes anything else); the recipient list
        # gets the remaining vertical space (stretch=1) with its own internal
        # scroll. The bottom bar stays pinned below everything.
        surface = QVBoxLayout()
        surface.setContentsMargins(20, 16, 20, 6)
        surface.setSpacing(10)

        top_content = QWidget()
        top_content.setStyleSheet("background:transparent;")
        top_col = QVBoxLayout(top_content)
        top_col.setContentsMargins(0, 0, 0, 0)
        top_col.setSpacing(10)

        # ── Card 1: distribution details ──────────────────────────────────────
        card1, c1 = _make_card("פרטי החלוקה", "doc")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name_input.setMinimumWidth(150)
        self.name_input.lineEdit().setPlaceholderText("לדוגמה: חלוקת פסח")
        self.name_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.name_input.setToolTip("שם/מטרת החלוקה — חובה למלא לפני הדפסה. אפשר לבחור משמות קודמים.")
        self.name_input.addItems(self._load_history("dist_names_history"))
        self.name_input.setCurrentText("")

        self.date_edit = DateEdit(allow_empty=False)
        self.date_edit.setMinimumWidth(130)
        self.date_edit.setToolTip("תאריך ביצוע החלוקה — ימי רביעי מסומנים בכחול")

        self.dist_input = QComboBox()
        self.dist_input.setEditable(True)
        self.dist_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.dist_input.setMinimumWidth(130)
        self.dist_input.lineEdit().setPlaceholderText("שם המחלק")
        self.dist_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.dist_input.setToolTip("שם האדם שביצע את החלוקה — נזכר ומוצע אוטומטית")
        self.dist_input.addItems(self._load_history("distributors_history"))
        self.dist_input.setCurrentText(db.get_setting("last_distributor") or "")

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("הערה כללית שתישמר עם החלוקה (לא חובה)")
        self.note_input.setAlignment(ALIGN_RIGHT)
        self.note_input.setToolTip("הערה על כל החלוקה — נשמרת בלשונית 'חלוקות' ומצורפת לכל מקבל")

        grid.addLayout(_field("שם החלוקה", self.name_input), 0, 0)
        grid.addLayout(_field("תאריך", self.date_edit), 0, 1)
        grid.addLayout(_field("מחלק", self.dist_input), 0, 2)
        grid.addLayout(_field("הערה כללית לחלוקה", self.note_input), 1, 0, 1, 3)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        c1.addLayout(grid)
        top_col.addWidget(card1)

        # ── Card 2: products ──────────────────────────────────────────────────
        card2, c2 = _make_card("מה מחלקים", "box", hint="הכמות היא לכל אדם")
        self.products = ProductsEditor()
        self.products.setToolTip("רשום כל מוצר שחולק ואת הכמות שכל אדם מקבל ממנו. "
                                 "אפשר להוסיף כמה מוצרים לאותה חלוקה.")
        c2.addWidget(self.products)
        top_col.addWidget(card2)

        # ── Card 3: volunteer messaging ───────────────────────────────────────
        card3, c3 = _make_card("שליחה למתנדב", "mail")
        vol_row = QHBoxLayout()
        vol_row.setSpacing(12)
        self.volunteer_email_input = QComboBox()
        self.volunteer_email_input.setEditable(True)
        self.volunteer_email_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.volunteer_email_input.setMinimumWidth(150)
        self.volunteer_email_input.setMaximumWidth(300)
        self.volunteer_email_input.lineEdit().setPlaceholderText("אימייל המתנדב")
        self.volunteer_email_input.lineEdit().setAlignment(ALIGN_RIGHT)
        self.volunteer_email_input.setToolTip("כתובת המייל של המתנדב שימלא את הרשימה")
        self.volunteer_email_input.addItems(self._load_history("volunteer_emails_history"))
        self.volunteer_email_input.setCurrentText("")
        vol_row.addLayout(_field("אימייל המתנדב", self.volunteer_email_input, maxw=300))

        btn_send_vol = QPushButton(" שלח למתנדב")
        btn_send_vol.setObjectName("primary")
        btn_send_vol.setStyleSheet(_BTN_PRIMARY)
        btn_send_vol.setIcon(QIcon(line_icon("send", 18, "#ffffff")))
        btn_send_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_send_vol.setToolTip("שולח למתנדב במייל קובץ מעוצב עם הרשימה, למילוי בלי לגעת בתוכנה")
        btn_send_vol.clicked.connect(self._send_to_volunteer)
        vol_row.addWidget(btn_send_vol, 0, Qt.AlignmentFlag.AlignBottom)

        btn_import_vol = QPushButton(" יבוא ידני")
        btn_import_vol.setObjectName("neutral")
        btn_import_vol.setStyleSheet(_BTN_GHOST)
        btn_import_vol.setIcon(QIcon(line_icon("upload", 18, "#475569")))
        btn_import_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import_vol.setToolTip("בדרך כלל לא צריך — תוצאות שהמתנדב שולח חזרה במייל נקלטות אוטומטית. "
                                  "כפתור זה נועד לייבוא ידני של קובץ Excel שהתקבל בדרך אחרת.")
        btn_import_vol.clicked.connect(self._import_volunteer_results)
        vol_row.addWidget(btn_import_vol, 0, Qt.AlignmentFlag.AlignBottom)
        vol_row.addStretch()
        c3.addLayout(vol_row)

        auto_hint = QLabel("↻ תוצאות שהמתנדב שולח חזרה במייל נקלטות אוטומטית")
        auto_hint.setStyleSheet("color:#7c3aed; font-size:12px; background:transparent; border:none;")
        c3.addWidget(auto_hint)
        top_col.addWidget(card3)

        # ── ONE scroll region for the entire body ─────────────────────────────
        # The detail cards + toolbar + recipient list all live inside a single
        # QScrollArea, and the table is sized to its own rows (its scrollbars are
        # off). Result: exactly ONE scrollbar on the screen — it shows only when
        # the content doesn't fit, and disappears on a large screen. As the user
        # scrolls, the fixed-height cards move up out of the way so the list fills
        # the view (15 rows and well beyond), which the cards' hard minimum height
        # never allowed when they were pinned in place.
        self._scroll_body = QScrollArea()
        self._scroll_body.setWidgetResizable(True)
        self._scroll_body.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_body.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._scroll_body.viewport().setStyleSheet("background:transparent;")
        enable_touch_scroll(self._scroll_body)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background:transparent;")
        body = QVBoxLayout(scroll_content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addWidget(top_content)

        # ── Toolbar over the recipient list ───────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        # Regulars distribution mode: schedule / none / scored-by-need
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumHeight(42)
        self.mode_combo.setToolTip(
            "כיצד להתייחס לקבועים בחלוקה זו:\n"
            "• רגיל — קבועים אוטומטית לפי לוח זמנים\n"
            "• בלי קבועים — קבועים לא מקבלים\n"
            "• קבועים לפי ניקוד — כל הקבועים מדורגים לפי ניקוד צורך, כמו חד-פעמי")
        for label, val in (("רגיל — קבועים לפי לוח זמנים", "schedule"),
                           ("בלי קבועים", "none"),
                           ("קבועים לפי ניקוד", "scored")):
            self.mode_combo.addItem(label, val)
        cur_mode = db.get_regulars_mode()
        idx = self.mode_combo.findData(cur_mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addLayout(_field("מצב חלוקה לקבועים", self.mode_combo, maxw=240))

        # Scored-mode only: mark the top-N leaders by available portions
        self.portions_spin = QSpinBox()
        self.portions_spin.setRange(0, 100000)
        self.portions_spin.setMinimumHeight(42)
        self.portions_spin.setToolTip("כמה מנות זמינות לחלוקה — מסמן את המובילים בניקוד עד למספר זה.\n"
                                      "המספר משותף עם 'מוצרים זמינים' בלשונית חד-פעמי.")
        try:
            self.portions_spin.setValue(int(db.get_setting("available_products") or 0))
        except (TypeError, ValueError):
            self.portions_spin.setValue(0)
        self._portions_field = _field("מנות זמינות", self.portions_spin, maxw=130)
        toolbar.addLayout(self._portions_field)

        self.btn_mark_leaders = QPushButton("סמן מובילים")
        self.btn_mark_leaders.setStyleSheet(_BTN_SUCCESS)
        self.btn_mark_leaders.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mark_leaders.setToolTip("מסמן את בעלי הניקוד הגבוה ביותר עד למספר המנות הזמינות")
        self.btn_mark_leaders.clicked.connect(self._mark_leaders)
        toolbar.addWidget(self.btn_mark_leaders)

        self.search_input = QLineEdit()
        self.search_input.setMinimumHeight(42)
        self.search_input.setMaximumWidth(520)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("חיפוש מהיר ברשימה: שם, טלפון, אזור, ת״ז...")
        self.search_input.setAlignment(ALIGN_RIGHT)
        self.search_input.addAction(search_icon(20), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setStyleSheet(
            "QLineEdit{background:#ffffff; border:1px solid #d7dfea; border-radius:11px;"
            " padding:0 14px; font-size:14px;} QLineEdit:focus{border-color:#1e78d6;}")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search)
        self.search_input.textChanged.connect(lambda: self._search_timer.start(180))
        toolbar.addWidget(self.search_input, 1)

        btn_check_all = QPushButton("בחר הכל")
        btn_check_all.setStyleSheet(_BTN_SUCCESS)
        btn_check_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_check_all.clicked.connect(self._check_all)
        toolbar.addWidget(btn_check_all)

        btn_uncheck_all = QPushButton("בטל הכל")
        btn_uncheck_all.setStyleSheet(_BTN_DANGER)
        btn_uncheck_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_uncheck_all.clicked.connect(self._uncheck_all)
        toolbar.addWidget(btn_uncheck_all)

        toolbar.addStretch()
        body.addLayout(toolbar)

        # Count chips live on their OWN row (not crammed into the toolbar) so the
        # extra scored-mode controls can never squeeze/clip the 'סה"כ' chip.
        counts_row = QHBoxLayout()
        counts_row.setSpacing(8)
        self.lbl_checked = QLabel("סומנו: 0")
        self.lbl_total = QLabel("סה\"כ ברשימה: 0")
        self.lbl_souls = QLabel("נפשות: 0")
        self.lbl_checked.setStyleSheet(_CHIP_GREEN)
        self.lbl_total.setStyleSheet(_CHIP_QSS)
        self.lbl_souls.setStyleSheet(_CHIP_QSS)
        for lbl in (self.lbl_checked, self.lbl_total, self.lbl_souls):
            lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            counts_row.addWidget(lbl)
        counts_row.addStretch()
        body.addLayout(counts_row)

        # ── Recipient list (tall card, sticky header, internal scroll) ────────
        list_card = QFrame()
        list_card.setObjectName("ui-card")
        list_card.setStyleSheet(_CARD_QSS)
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(1, 1, 1, 1)
        lc.setSpacing(0)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        apply_header_icons(self.table)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(
            "QTableWidget{background:#ffffff; border:none; border-radius:12px; gridline-color:#eef2f7;}"
            "QHeaderView::section{background:#f4f7fc; color:#64748b; font-weight:700;"
            " border:none; border-bottom:1px solid #e6eaf2; padding:11px 10px;}"
            "QTableWidget::item{padding:6px 8px; border-bottom:1px solid #f1f4f9;}"
            "QTableWidget::item:selected{background:#eaf3ff; color:#0d3b73;}")
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)  # uniform row height
        # The table has NO vertical scrollbar of its own — it is sized to fit all
        # its rows and the single body scrollbar does the scrolling. This is what
        # removes the second scrollbar the user complained about.
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        lc.addWidget(self.table)
        attach_empty_state(self.table, "אין מקבלים להצגה")
        body.addWidget(list_card)
        body.addStretch(0)   # keep everything top-aligned when the body is short

        self._scroll_body.setWidget(scroll_content)
        surface.addWidget(self._scroll_body, 1)

        root.addLayout(surface, 1)

        # ── Sticky bottom action bar ──────────────────────────────────────────
        bottom_wrap = QWidget()
        bw = QHBoxLayout(bottom_wrap)
        bw.setContentsMargins(20, 4, 20, 12)
        bw.setSpacing(0)
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottom-bar")
        bottom_bar.setStyleSheet(
            "QFrame#bottom-bar{background:#ffffff; border:1px solid #e6eaf2; border-radius:14px;}")
        _card_shadow(bottom_bar)
        bar = QHBoxLayout(bottom_bar)
        bar.setContentsMargins(16, 10, 16, 10)
        bar.setSpacing(12)

        btn_save = QPushButton(" שמור חלוקה")
        btn_save.setObjectName("primary")
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.setMinimumHeight(46)
        btn_save.setMinimumWidth(170)
        btn_save.setIcon(QIcon(line_icon("save", 18, "#ffffff")))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setToolTip("רושם את החלוקה למעקב ומייצא אוטומטית אקסל מלא לתיקיית ההורדות")
        btn_save.clicked.connect(self._save)
        bar.addWidget(btn_save)

        btn_print = QPushButton("  הדפסה לחלוקה")
        btn_print.setObjectName("primary")
        btn_print.setStyleSheet(_BTN_PRINT)
        btn_print.setMinimumHeight(54)
        btn_print.setMinimumWidth(230)
        btn_print.setIcon(QIcon(line_icon("print", 22, "#ffffff")))
        btn_print.setIconSize(QSize(22, 22))
        btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_print.setToolTip("הדפס את רשימת החלוקה המסומנת (A4)")
        _print_glow = QGraphicsDropShadowEffect(btn_print)
        _print_glow.setBlurRadius(22)
        _print_glow.setXOffset(0)
        _print_glow.setYOffset(4)
        _print_glow.setColor(QColor(67, 56, 202, 120))
        btn_print.setGraphicsEffect(_print_glow)
        btn_print.clicked.connect(self._print)
        bar.addWidget(btn_print)

        bar.addStretch()
        bw.addWidget(bottom_bar)
        root.addWidget(bottom_wrap)

    # ── data ───────────────────────────────────────────────────────────────────
    def _extra_recipients(self, base_ids: set) -> list:
        """Fetch the persisted one-time picks from the DB (so they survive
        restart), excluding any already in the base list."""
        out = []
        for rid in self._extra_ids:
            if rid in base_ids:
                continue
            rec = db.get_recipient(rid)
            # Drop a saved one-time pick that was since deleted OR is no longer
            # active (suspended/ended) — otherwise a recipient removed from the
            # active roster would silently reappear on the list and in the print.
            if not rec or rec.get("status") != "פעיל":
                continue
            rec = dict(rec)
            rec["_reserve"] = rid in self._reserve_ids
            # Give picks the same recency fields the scored/weekly lists carry, so
            # that in 'scored' mode they can be re-scored on the SAME scale as
            # everyone else (a missing days_since would wrongly zero their ותק).
            ld_str = rec.get("last_distribution") or ""
            try:
                ld = date.fromisoformat(ld_str) if ld_str else date(2000, 1, 1)
            except ValueError:
                ld = date(2000, 1, 1)
            rec["last_dist_date"] = ld
            rec["days_since"] = db.recency_days(rec)   # registration-based ותק
            out.append(rec)
        return out

    # ── distribution-mode for regulars (schedule / none / scored) ──────────────
    def _current_mode(self) -> str:
        data = self.mode_combo.currentData()
        return data if data in ("schedule", "none", "scored") else "schedule"

    def _on_mode_changed(self, *_):
        db.set_setting("dist_regulars_mode", self._current_mode())
        # Start each mode with a clean selection so ticks don't bleed across modes
        # (schedule re-ticks everyone; scored starts empty for 'סמן מובילים').
        self._checked_ids.clear()
        self._seen_ids.clear()
        self._update_mode_controls()
        self.refresh()

    def _update_mode_controls(self):
        """Show the 'available portions' spin + 'mark leaders' button only in the
        scored mode, where ranking-by-need is what drives the selection."""
        scored = self._current_mode() == "scored"
        self.portions_spin.setVisible(scored)
        self.btn_mark_leaders.setVisible(scored)
        for i in range(self._portions_field.count()):
            w = self._portions_field.itemAt(i).widget()
            if w is not None:
                w.setVisible(scored)

    def _mark_leaders(self):
        """Check the top-N recipients by need-score, N = available portions."""
        n = self.portions_spin.value()
        db.set_setting("available_products", str(n))   # shared with the חד-פעמי tab
        # _rows_data is already need-ordered (scored mode) with the SAME name
        # tie-break as the display, so the top-N here matches exactly what's shown.
        ranked = self._rows_data
        self._checked_ids = {r.get("id") for r in ranked[:n] if r.get("id") is not None}
        self._populate()

    def refresh(self):
        mode = self._current_mode()
        if mode == "none":
            base = []
        elif mode == "scored":
            # Merged mode: regulars AND one-time candidates on one need-score scale.
            base = db.get_scored_all(area_filter="הכל")
        else:
            base = db.get_weekly_list(area_filter="הכל")
        if mode == "scored":
            # Pick up the shared product count if the חד-פעמי tab changed it.
            try:
                self.portions_spin.blockSignals(True)
                self.portions_spin.setValue(int(db.get_setting("available_products") or 0))
            except (TypeError, ValueError):
                pass
            finally:
                self.portions_spin.blockSignals(False)
        base_ids = {r["id"] for r in base}
        extras = self._extra_recipients(base_ids)
        self._rows_data = base + extras
        if mode == "scored":
            # Score EVERYONE (base + picks) together on ONE need scale, then order
            # by need (highest first), ties by name. Scoring the picks separately
            # would rank them on a different 0–100 scale and mis-order the merge.
            self._rows_data = selection.rank_by_need(self._rows_data, db.get_need_weights())
        live = {r.get("id") for r in self._rows_data}
        # In the schedule/receipt workflow everyone starts marked as 'received'
        # (the operator only UNticks the no-shows, bug 6). In 'scored' mode the
        # job is to PICK the top-N by portions, so rows start unticked there and
        # 'סמן מובילים' selects them. Either way, a row the operator explicitly
        # unticked keeps its state across search/refresh.
        default_checked = (mode != "scored")
        if default_checked:
            for rid in live:
                # RULE 3: reserve picks are standby — they ride along on the list
                # (and print as a separate section) but are NOT ticked-for-record,
                # so a reserve is only saved if the operator activates them for a
                # no-show. Everyone else starts ticked as 'received'.
                if rid not in self._seen_ids and rid not in self._reserve_ids:
                    self._checked_ids.add(rid)
        self._seen_ids = set(live)
        self._checked_ids &= live      # forget ticks for people no longer listed
        self._populate()

    def _visible_rows(self):
        """The list rows currently shown — the whole list, or the quick-search
        subset when a search term is active (matches any recipient field)."""
        if not self._search_text:
            return self._rows_data
        return db.filter_recipients(self._rows_data, self._search_text, limit=100000)

    def _apply_search(self):
        self._search_text = self.search_input.text().strip()
        self._populate()

    def _row_style(self, rec: dict):
        """Return (bg, fg, freq_disp, next_disp) for a row."""
        rid = rec.get("id")
        freq = rec.get("frequency", "") or ""
        score = rec.get("need_score")
        score_txt = f"ניקוד {round(score)}" if score is not None else ""
        is_pick = rid in self._extra_ids or freq == "חד-פעמי"
        if is_pick:
            if rec.get("_reserve") or rid in self._reserve_ids:
                return QColor(_RESERVE_BG), QColor(_RESERVE_FG), "חד-פעמי · רזרבה", score_txt
            return QColor(SELECTED_BG), QColor(SELECTED_FG), "חד-פעמי", score_txt
        # scored regular — neutral tint, ranked by need-score not by date
        if rec.get("_scored_regular"):
            return QColor("#f1f5f9"), QColor("#334155"), freq, score_txt
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
        rows = self._visible_rows()
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            bg, fg, freq_disp, next_disp = self._row_style(rec)
            rid = rec.get("id")

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            # Tick state is held in _checked_ids so it survives search filtering
            # (a checked person hidden by a search stays checked and gets saved).
            chk.setCheckState(Qt.CheckState.Checked if rid in self._checked_ids
                              else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk.setData(Qt.ItemDataRole.UserRole, rid)
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
        self._resize_table_height()

    def _resize_table_height(self):
        """Size the table to hold ALL its rows (no inner scroll) so the single
        body scrollbar is the only one. Grows with the list; a small floor keeps
        the empty-state readable."""
        rows = self.table.rowCount()
        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height() or 44
        total = header_h + max(rows, 4) * row_h + 4
        self.table.setFixedHeight(total)

    def _on_cell_clicked(self, row, col):
        """Clicking a name (col 1) opens the need-score breakdown — same as the
        'חד פעמי' tab — for any row that has a score (scored regulars + picks)."""
        if col != 1:
            return
        rows = self._visible_rows()
        if 0 <= row < len(rows) and rows[row].get("_score_parts"):
            show_score_breakdown(self, rows[row])

    def _on_item_changed(self, item):
        """Keep _checked_ids in sync when the operator ticks/unticks a row."""
        if item.column() == 0:
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid is not None:
                if item.checkState() == Qt.CheckState.Checked:
                    self._checked_ids.add(rid)
                else:
                    self._checked_ids.discard(rid)
        self._update_counts()

    def _update_counts(self):
        total = len(self._rows_data)
        checked = len(self._checked_ids)
        souls = 0
        for rec in self._rows_data:
            if rec.get("id") in self._checked_ids:
                try:
                    souls += int(rec.get("souls", 0) or 0)
                except (ValueError, TypeError):
                    pass
        self.lbl_total.setText(f"סה\"כ ברשימה: {total}")
        self.lbl_checked.setText(f"סומנו: {checked}")
        self.lbl_souls.setText(f"נפשות: {souls}")

    def _check_all(self):
        """Tick every row currently shown (respects an active search)."""
        for rec in self._visible_rows():
            rid = rec.get("id")
            if rid is not None:
                self._checked_ids.add(rid)
        self._populate()

    def _uncheck_all(self):
        for rec in self._visible_rows():
            self._checked_ids.discard(rec.get("id"))
        self._populate()

    def _get_checked_recipients(self):
        # Inline-edited notes come from the visible table; checked-but-hidden
        # rows fall back to their stored notes.
        note_by_id = {}
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk is not None:
                note_it = self.table.item(r, _COL_NOTES)
                note_by_id[chk.data(Qt.ItemDataRole.UserRole)] = note_it.text() if note_it else ""
        result = []
        for rec in self._rows_data:
            rid = rec.get("id")
            if rid in self._checked_ids:
                rec_copy = dict(rec)
                if rid in note_by_id:
                    rec_copy["notes"] = note_by_id[rid]
                result.append(rec_copy)
        return result

    def _save(self):
        checked = self._get_checked_recipients()
        if not checked:
            QMessageBox.information(self, "", "לא סומן אף מקבל")
            return

        dist_date    = self.date_edit.get_iso()
        what         = self.products.products_display()
        qty          = self.products.total_qty()
        distributor  = self.dist_input.currentText().strip()
        dist_name    = self.name_input.currentText().strip()
        general_note = self.note_input.text().strip()

        _ERR = "border: 2px solid #dc2626; background-color: #fff5f5;"
        errors = []
        if self.products.is_empty():
            self.products.setStyleSheet("QLineEdit{" + _ERR + "}")
            errors.append("מה חולק: יש לרשום לפחות מוצר אחד")
        else:
            self.products.setStyleSheet("")
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

        # A general note is recorded on the batch AND appended to each recipient.
        if general_note:
            suffix = f" | הערה כללית: {general_note}"
            for rec in checked:
                rec["notes"] = (rec.get("notes") or "") + suffix

        export_path = None
        export_err = None
        with busy_cursor():
            db.bulk_add_distributions(checked, dist_date, what, qty, distributor,
                                      dist_name=dist_name, general_note=general_note)
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
        # Reset the entry fields + ticks for a clean next distribution. Clearing
        # _seen_ids too means the next refresh re-ticks everyone as 'received'.
        self._checked_ids.clear()
        self._seen_ids.clear()
        self.note_input.clear()
        self.products.clear()

        if export_path:
            reveal_in_folder(export_path)   # open Downloads with the file selected
        msg = f"נשמרה חלוקה ל-{len(checked)} מקבלים."
        if export_path:
            msg += f"\n\nקובץ אקסל מלא נשמר בתיקיית ההורדות ונפתחה התיקייה:\n{export_path}"
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
        """Rows to print/export: everyone ticked as 'received', PLUS the reserve
        (standby) picks even though they're unticked — RULE 3: reserve is not
        recorded, but it must still appear on the printed list as its own section
        so the distributor has backups on hand for no-shows."""
        checked = self._get_checked_recipients()
        checked_ids = {r.get("id") for r in checked}
        reserve = []
        for rec in self._rows_data:
            rid = rec.get("id")
            if (rec.get("_reserve") or rid in self._reserve_ids) and rid not in checked_ids:
                r = dict(rec)
                r["_reserve"] = True
                reserve.append(r)
        rows = checked + reserve
        return rows if rows else list(self._rows_data)

    def _export_excel(self):
        checked = self._get_export_rows()
        dist_date = _fdate(self.date_edit.get_iso())
        try:
            with busy_cursor():
                path = export_distribution_to_excel(checked, dist_date)
            reveal_in_folder(path)   # open Downloads with the file selected
            QMessageBox.information(self, "ייצוא הושלם",
                                    f"הקובץ נשמר בתיקיית ההורדות ונפתחה התיקייה:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", str(e))

    # ── send list to a volunteer by email / import their filled results ────────

    def _send_to_volunteer(self):
        dist_name   = self.name_input.currentText().strip()
        what        = self.products.products_display()
        distributor = self.dist_input.currentText().strip()
        to_addr     = self.volunteer_email_input.currentText().strip()

        _ERR = "border: 2px solid #dc2626; background-color: #fff5f5;"
        errors = []
        for widget, val, label in (
            (self.name_input, dist_name, "שם החלוקה"),
            (self.dist_input, distributor, "שם המחלק"),
        ):
            if not val:
                widget.setStyleSheet(_ERR)
                errors.append(f"{label}: שדה חובה")
            else:
                widget.setStyleSheet("")
        if self.products.is_empty():
            self.products.setStyleSheet("QLineEdit{" + _ERR + "}")
            errors.append("מה חולק: יש לרשום לפחות מוצר אחד")
        else:
            self.products.setStyleSheet("")
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
        qty = self.products.total_qty()
        try:
            with busy_cursor():
                # Store the ISO date (not the dd/mm/yyyy display string) so a
                # later import can hand it straight to bulk_add_distributions /
                # calculate_next_dist, which require ISO format.
                path = export_volunteer_checklist_to_excel(
                    self._rows_data, dist_date_iso, dist_name, what, qty, distributor)
                file_pw = email_utils.get_checklist_password()
                # NOTE: the password itself is deliberately NOT written in the
                # email — anyone with access to the mailbox would otherwise see
                # it. The volunteer receives the password out-of-band (phone /
                # WhatsApp, once). We only note that the file is protected.
                pw_block = (
                    "<p style='background:#fffbeb;border:1px solid #fde68a;"
                    "border-radius:6px;padding:8px 10px;'>"
                    "🔒 הקובץ המצורף מוגן בסיסמה. הזן את הסיסמה שנמסרה לך כדי לפתוח אותו ב-Excel.</p>"
                ) if file_pw else ""
                html = (
                    "<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
                    "<div style='text-align:center;margin-bottom:10px;'>"
                    "<img src='cid:logo' style='max-width:160px;'></div>"
                    f"<p>שלום {distributor},</p>"
                    f"<p>מצורפת רשימת החלוקה \"<b>{dist_name}</b>\" מתאריך {dist_date_disp}.</p>"
                    f"{pw_block}"
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

    def _apply_checklist_file(self, path: str, confirm: bool):
        """Read a filled volunteer checklist and record the received rows to
        history. When confirm=True, ask the operator first (manual file import);
        when confirm=False, import silently (automatic email pull). Returns
        (records_written, meta, received_ids)."""
        result = import_volunteer_checklist(path)
        received = result["received"]
        unmatched = result["unmatched"]
        meta = result["meta"]

        if not received:
            if confirm:
                msg = "לא נמצא אף מקבל שסומן \"כן\" בקובץ."
                if unmatched:
                    msg += f"\n\n⚠ {len(unmatched)} שורות לא זוהו: " + ", ".join(unmatched[:10])
                QMessageBox.information(self, "אין מה לייבא", msg)
            return 0, meta, []

        if confirm:
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
                return 0, meta, []

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
                meta.get("distributor") or "",
                dist_name=meta.get("dist_name") or "",
                general_note=meta.get("general_note") or "")
            auto_backup_async()
        return len(records), meta, [r.get("id") for r in received]

    def _import_volunteer_results(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ שחזר מהמתנדב", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            n, _meta, ids = self._apply_checklist_file(path, confirm=True)
        except Exception as e:
            QMessageBox.critical(self, "שגיאה בקריאת הקובץ", str(e))
            return
        if n:
            if self.main_win:
                self.main_win.refresh_all()
                self.main_win.status_msg(f"יובאו {n} חלוקות ממתנדב")
            # Mark AFTER refresh (refresh rebuilds the table and would clear marks).
            self._mark_received_in_table(ids)
            QMessageBox.information(
                self, "הצלחה", f"נרשמו {n} חלוקות מהמתנדב להיסטוריה ✓\n"
                               f"המקבלים שהגיעו סומנו ברשימה.")

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
            what = self.products.products_display()
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

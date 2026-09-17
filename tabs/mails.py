# -*- coding: utf-8 -*-
"""לשונית "מיילים" (v3.39) — שליחת מייל לקבוצת מקבלים או לאנשים בודדים,
ישירות מהתוכנה, מחשבון ה-Gmail של הקופה (חיבור Google או סיסמת אפליקציה).

הזרימה (באותה שפה עיצובית של הצינתוקים / חלוקה ורישום):
  כותרת + צ'יפ חשבון
  ① למי שולחים — כל המקבלים / רשימת החלוקה הנוכחית / בחירה ידנית, הוספת אדם
     או כתובת חיצונית, טבלת הנמענים עם סיבת-דילוג למי שאין לו מייל
  ② ההודעה  — תבנית, נושא, תוכן עם {שם} {תאריך חלוקה} {פרשה}, קובץ מצורף,
     תצוגה-מקדימה חיה
  היסטוריה — כל שליחה, פירוט לפי נמען, "שלח שוב לנכשלים"
  סרגל תחתון ③ — סיכום, "שלח בדיקה אליי", "שלח עכשיו", מד-התקדמות

הלוגיקה (placeholders, יעדים, שליחה) ב-`utils/mailer.py` (טהור); ה-DB
וה-סנכרון ב-`database.py` (`mail_campaigns`/`mail_templates`).
"""
import html
import json
import os

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextListFormat, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QTextBrowser, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QDialog, QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QInputDialog, QProgressBar, QAbstractItemView, QSizePolicy, QFrame, QButtonGroup,
    QColorDialog, QToolButton)

import database as db
from utils import email_utils, mailer, richtext, sync, timefmt
from utils.ui import busy_cursor, enable_touch_scroll, FlowLayout
from tabs.group_update import (_BG, _CARD_QSS, _CHIP_QSS, _CHIP_GREEN, _CHIP_AMBER, _LBL,
                               _BTN_PRIMARY, _BTN_GHOST, _BTN_PRINT, _BTN_ACCENT,
                               _BTN_DANGER, _step_badge, _step_card, _metric, _set_metric)
from tabs.tzintukim import (_set_step_done, _CARD_DONE_QSS, _HCHIP_GREEN, _HCHIP_AMBER,
                            _CHIPBTN_AMBER)

_CHIP_RED = ("QLabel{background:#fde2e2; color:#991b1b; border:none; border-radius:16px;"
             " padding:5px 13px; font-size:12.5px; font-weight:700;}")
_TOGGLE = ("QPushButton{background:#fafcfb; color:#334155; border:2px solid #e2e8f0;"
           " border-radius:10px; font-weight:700; font-size:13.5px; padding:0 16px; min-height:40px;}"
           "QPushButton:hover{border-color:#94d3c0;}"
           "QPushButton:checked{background:#e6f5ef; color:#0f766e; border-color:#0f9d78;}")
_BTN_LINK = ("QPushButton{background:transparent; color:#0f766e; border:none;"
             " font-weight:700; text-decoration:underline; padding:2px 6px;}"
             "QPushButton:hover{color:#065f46;}")
_MAX_TABLE_ROWS = 14
_FMT_BAR_QSS = ("QWidget#fmtbar{background:#f1f5f9; border:1px solid #e2e8f0; border-bottom:none;"
                " border-top-left-radius:8px; border-top-right-radius:8px;}"
                "QToolButton{background:transparent; border:none; border-radius:6px; min-width:30px;"
                " min-height:28px; font-size:14px; color:#334155; padding:0 4px;}"
                "QToolButton:hover{background:#e2e8f0;}"
                "QToolButton:checked{background:#c7ede0; color:#0f766e;}"
                "QComboBox{min-height:26px; font-size:12.5px; padding:0 6px; min-width:64px;}")


MAIL_LOGO_PX = 88   # 2× של 44px בתצוגה — חד גם במסכי רטינה, כמה KB במקום 34KB (או MB של לוגו מותאם)


def _source_logo_path() -> str:
    if os.path.exists(db.USER_LOGO_PATH):
        return db.USER_LOGO_PATH
    try:
        from utils.print_view import _resource_path
        p = _resource_path("org_logo.png")
        return p if os.path.exists(p) else ""
    except Exception:
        return ""


def _logo_path() -> str:
    """v3.45: הלוגו שמצורף לכל מייל — עותק מוקטן (MAIL_LOGO_PX) שנשמר ליד ה-DB ומתחדש
    כשהמקור השתנה. המקור (725px / 34KB, או לוגו מותאם שיכול להיות צילום של כמה MB) נשלח
    קודם כמו שהוא ל-500 נמענים — איטי, מנפח את המכסה, ומוצג ממילא ב-44px."""
    src = _source_logo_path()
    if not src:
        return ""
    try:
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import Qt
        out = os.path.join(os.path.dirname(db.DB_PATH), "logo_mail.png")   # ליד ה-DB (בבדיקות: DB זמני)
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
            return out
        img = QImage(src)
        if img.isNull():
            return src
        img = img.scaled(MAIL_LOGO_PX, MAIL_LOGO_PX, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        return out if img.save(out, "PNG") else src
    except Exception:
        return src


class _BgWorker(QThread):
    """קריאה חוסמת אחת מחוץ ל-thread של ה-UI; פולט תוצאה או חריגה."""
    done = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:                                # noqa: BLE001
            self.done.emit(e)


class _SendWorker(QThread):
    """שולח ברקע (מייל אחרי מייל) — המסך לא קופא."""
    progress = pyqtSignal(int, int, object)     # done, total, row
    finished_rows = pyqtSignal(object)          # list[dict] | Exception

    def __init__(self, targets, subject, body, ctx, attachment, with_header, rec_by_id,
                 parent=None):
        super().__init__(parent)
        self._a = (targets, subject, body, ctx, attachment, with_header, rec_by_id)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        targets, subject, body, ctx, attachment, with_header, rec_by_id = self._a
        try:
            rows = mailer.send_batch(
                targets, subject, body, ctx, attachment_path=attachment,
                logo_path=_logo_path(), with_header=with_header, rec_by_id=rec_by_id,
                progress=lambda d, t, r: self.progress.emit(d, t, r),
                should_stop=lambda: self._stop)
            self.finished_rows.emit(rows)
        except Exception as e:
            self.finished_rows.emit(e)


class _PickPersonDialog(QDialog):
    """בחירת מקבל להוספה לרשימת המיילים (מציג את כתובת המייל שלו)."""

    def __init__(self, exclude_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הוסף אדם לרשימת המיילים")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(460, 500)
        self.picked = None
        self._all = [r for r in db.get_all_recipients("פעיל") if r["id"] not in exclude_ids]
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("חיפוש לפי שם / מייל…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(lambda _i: self._accept())
        lay.addWidget(self.listw, 1)
        btns = QHBoxLayout()
        ok = QPushButton("הוסף")
        ok.setStyleSheet(_BTN_PRIMARY)
        ok.clicked.connect(self._accept)
        cancel = QPushButton("ביטול")
        cancel.setStyleSheet(_BTN_GHOST)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        btns.addStretch()
        lay.addLayout(btns)
        self._filter()

    def _filter(self):
        text = self.search.text().strip().lower()
        rows = self._all
        if text:
            rows = [r for r in rows if text in (r.get("full_name") or "").lower()
                    or text in (r.get("email") or "").lower()]
        self.listw.clear()
        for r in rows[:300]:
            email = (r.get("email") or "").strip()
            it = QListWidgetItem(r["full_name"] + ("  ·  " + email if email else "  ·  (אין מייל)"))
            it.setData(Qt.ItemDataRole.UserRole, dict(r))
            self.listw.addItem(it)

    def _accept(self):
        it = self.listw.currentItem()
        if it is None:
            return
        self.picked = it.data(Qt.ItemDataRole.UserRole)
        self.accept()


class _NamesDialog(QDialog):
    """רשימה פשוטה של שמות (למשל: מי בלי מייל)."""

    def __init__(self, title: str, lines: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(420, 480)
        lay = QVBoxLayout(self)
        lw = QListWidget()
        for ln in lines:
            lw.addItem(ln)
        lay.addWidget(lw, 1)
        b = QPushButton("סגור")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self.accept)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)


class _HistoryDetailDialog(QDialog):
    """פירוט שליחה אחת — שורה לכל נמען."""

    def __init__(self, camp: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("פירוט שליחה — " + (camp.get("subject") or ""))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{html.escape(camp.get('subject') or '')}</b> · {timefmt.datetime_str(camp.get('sent_at',''))}"
                      f" · {html.escape(camp.get('audience') or '')} · נשלחו {camp.get('sent',0)} · נכשלו {camp.get('failed',0)}")
        head.setWordWrap(True)
        lay.addWidget(head)
        body = QTextBrowser()
        body.setMaximumHeight(120)
        richtext.load_into(body, camp.get("body") or "")
        lay.addWidget(body)
        try:
            rows = json.loads(camp.get("report_json") or "[]")
        except Exception:
            rows = []
        t = QTableWidget(len(rows), 4)
        t.setHorizontalHeaderLabels(["שם", "מייל", "מצב", "הערה"])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for i, r in enumerate(rows):
            for c, v in enumerate((r.get("name", ""), r.get("email", ""),
                                   mailer.STATUS_HE.get(r.get("status", ""), r.get("status", "")),
                                   r.get("error", ""))):
                t.setItem(i, c, QTableWidgetItem(str(v)))
        lay.addWidget(t, 1)
        b = QPushButton("סגור")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self.accept)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)


class MailsTab(QWidget):
    MODE_ALL, MODE_CURRENT, MODE_MANUAL = "all", "current", "manual"
    _HIST_ACT = 6            # עמודת הפעולות בהיסטוריה (v3.55: נוספה עמודת "מצב")
    _MODE_TEXT = {"all": "כל המקבלים", "current": "רשימת החלוקה הנוכחית", "manual": "בחירה ידנית"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main = parent
        self._mode = self.MODE_ALL
        self._picked = []        # מקבלים שנוספו ידנית (dict)
        self._removed = set()    # ids שהוסרו מהרשימה האוטומטית
        self._extra = []         # כתובות חיצוניות
        self._targets = []
        self._recs = {}          # id → rec
        self._attachment = ""
        self._worker = None
        self._test_worker = None
        self._active_guid = ""
        self._templates = []
        self._current_tpl_guid = ""
        self._preview_idx = 0    # v3.55: איזה נמען מוצג בתצוגה המקדימה ("נמען אחר")
        self._build_ui()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._update_preview)
        QTimer.singleShot(4000, self._close_stale_campaigns)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        surface = QWidget()
        surface.setObjectName("mail-surface")
        surface.setStyleSheet(f"QWidget#mail-surface{{background:{_BG};}}")
        root.addWidget(surface, 1)
        s_lay = QVBoxLayout(surface)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        enable_touch_scroll(scroll)
        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 12, 20, 8)
        s_lay.addWidget(scroll, 1)

        # header
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("מיילים")
        title.setStyleSheet("color:#064e3b; font-size:22px; font-weight:800; " + _LBL)
        head.addWidget(title)
        sub = QLabel("הודעה במייל לקבוצה או לאדם בודד, מחשבון הקופה")
        sub.setStyleSheet("color:#64748b; font-size:13px; " + _LBL)
        head.addWidget(sub)
        head.addStretch()
        self.btn_settings = QPushButton("חבר חשבון מייל בהגדרות  ←")
        self.btn_settings.setStyleSheet(_BTN_ACCENT)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._goto_settings)
        head.addWidget(self.btn_settings)
        lay.addLayout(head)
        # v3.55: החיוויים החיים בשורה משלהם, עוטפים לשורה נוספת בגודל-טקסט גדול
        self.chips_row = QWidget()
        chips = FlowLayout(self.chips_row, 8, 6)
        self.chip_account = QLabel("")
        self.chip_account.setStyleSheet(_HCHIP_GREEN)
        chips.addWidget(self.chip_account)
        self.chip_with_mail = QLabel("")
        self.chip_with_mail.setStyleSheet(_CHIP_QSS)
        chips.addWidget(self.chip_with_mail)
        self.chip_ready = QLabel("")
        self.chip_ready.setStyleSheet(_HCHIP_AMBER)
        chips.addWidget(self.chip_ready)
        self.chip_msg = QLabel("")
        self.chip_msg.setStyleSheet(_HCHIP_AMBER)
        chips.addWidget(self.chip_msg)
        self.chip_sending = QLabel("")
        self.chip_sending.setStyleSheet(_HCHIP_AMBER)
        self.chip_sending.hide()
        chips.addWidget(self.chip_sending)
        lay.addWidget(self.chips_row)

        # ① למי
        card, c_lay, c_head = _step_card("1", "למי שולחים?", "הרשימה נבנית מהכרטיסים — רק מי שיש לו מייל יקבל")
        card.setStyleSheet(_CARD_DONE_QSS)
        self.card_list = card
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self.btn_mode_all = self._mode_btn("כל המקבלים", self.MODE_ALL, modes)
        self.btn_mode_current = self._mode_btn("רשימת החלוקה הנוכחית", self.MODE_CURRENT, modes)
        self.btn_mode_manual = self._mode_btn("בחירה ידנית", self.MODE_MANUAL, modes)
        self.btn_mode_all.setChecked(True)
        modes.addSpacing(16)
        self.btn_add_person = QPushButton("＋ הוסף אדם")
        self.btn_add_person.setStyleSheet(_BTN_ACCENT)
        self.btn_add_person.clicked.connect(self._add_person)
        modes.addWidget(self.btn_add_person)
        self.btn_add_addr = QPushButton("＋ כתובת מייל חיצונית")
        self.btn_add_addr.setStyleSheet(_BTN_GHOST)
        self.btn_add_addr.setToolTip("למי שאינו מקבל בתוכנה — מתנדב, חבר הנהלה, תורם")
        self.btn_add_addr.clicked.connect(self._add_address)
        modes.addWidget(self.btn_add_addr)
        modes.addStretch()
        c_lay.addLayout(modes)

        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.m_total = _metric("ברשימה", _CHIP_QSS)
        self.m_ok = _metric("יקבלו מייל", _CHIP_GREEN)
        self.m_bad = _metric("בלי מייל", _CHIP_AMBER)
        for m in (self.m_total, self.m_ok, self.m_bad):
            mrow.addWidget(m["frame"])
        # v3.55: "בלי מייל" = מסנן בלחיצה (במקום חלון נפרד) + חיפוש ברשימה
        self.btn_show_bad = QPushButton("⚠ הצג רק את מי שבלי מייל")
        self.btn_show_bad.setCheckable(True)
        self.btn_show_bad.setStyleSheet(_CHIPBTN_AMBER)
        self.btn_show_bad.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_bad.setToolTip("מסנן את הרשימה למי שלא יקבל — לחיצה כפולה על שורה פותחת את הכרטיס להוספת מייל")
        self.btn_show_bad.toggled.connect(self._apply_filter)
        mrow.addWidget(self.btn_show_bad)
        mrow.addStretch()
        self.list_search = QLineEdit()
        self.list_search.setPlaceholderText("🔍 חיפוש ברשימה — שם או מייל")
        self.list_search.setClearButtonEnabled(True)
        self.list_search.setMinimumWidth(260)
        self.list_search.textChanged.connect(self._apply_filter)
        mrow.addWidget(self.list_search)
        c_lay.addLayout(mrow)

        self.lbl_list_empty = QLabel("")
        self.lbl_list_empty.setWordWrap(True)
        self.lbl_list_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_list_empty.setStyleSheet("QLabel{background:#fafcfe; border:1.5px dashed #cbd5e1; border-radius:12px;"
                                          " color:#475569; font-size:14px; padding:22px;}")
        self.lbl_list_empty.hide()
        c_lay.addWidget(self.lbl_list_empty)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["שם", "מייל", "מצב", ""])
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._open_row_card)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 80)
        self.table.setStyleSheet("QTableWidget{background:#fff; border:1px solid #e6eaf2; border-radius:8px;}")
        c_lay.addWidget(self.table)
        self.lbl_list_hint = QLabel("לחיצה כפולה על שורה פותחת את כרטיס המקבל — להוספה או לתיקון של כתובת המייל.")
        self.lbl_list_hint.setStyleSheet("color:#94a3b8; font-size:12px; " + _LBL)
        c_lay.addWidget(self.lbl_list_hint)
        lay.addWidget(card)

        # ② ההודעה
        card, c_lay, c_head = _step_card("2", "מה כותבים?", "אפשר לשמור כתבנית לפעם הבאה")
        card.setStyleSheet(_CARD_DONE_QSS)
        self.card_msg = card
        two = QHBoxLayout()
        two.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(6)
        trow = QHBoxLayout()
        trow.addWidget(self._lbl("תבנית"))
        self.tpl_combo = QComboBox()
        self.tpl_combo.setMinimumWidth(240)
        self.tpl_combo.currentIndexChanged.connect(self._tpl_selected)
        trow.addWidget(self.tpl_combo)
        self.btn_tpl_save = QPushButton("שמור כתבנית")
        self.btn_tpl_save.setStyleSheet(_BTN_GHOST)
        self.btn_tpl_save.clicked.connect(self._save_template)
        trow.addWidget(self.btn_tpl_save)
        self.btn_tpl_del = QPushButton("מחק תבנית")
        self.btn_tpl_del.setStyleSheet(_BTN_GHOST)
        self.btn_tpl_del.clicked.connect(self._delete_template)
        trow.addWidget(self.btn_tpl_del)
        trow.addStretch()
        left.addLayout(trow)
        left.addWidget(self._lbl("נושא"))
        self.subject = QLineEdit()
        self.subject.setPlaceholderText("למשל: תזכורת — חלוקה ביום רביעי {תאריך חלוקה}")
        self.subject.textChanged.connect(self._schedule_preview)
        left.addWidget(self.subject)
        left.addWidget(self._lbl("תוכן ההודעה"))
        self.body = QTextEdit()
        self.body.setAcceptRichText(False)
        self.body.setMinimumHeight(180)
        self.body.setPlaceholderText("שלום {שם},\n…")
        self.body.textChanged.connect(self._schedule_preview)
        # v3.50: סרגל עיצוב (כמו ב-Gmail); הדבקה נכנסת כטקסט-רגיל, העיצוב רק מהסרגל
        self.body.currentCharFormatChanged.connect(self._sync_format_bar)
        self.body.cursorPositionChanged.connect(self._sync_format_bar)
        left.addWidget(self._build_format_bar())
        left.addWidget(self.body)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(self._lbl("הוסף:"))
        for ph, tip in mailer.PLACEHOLDERS:
            b = QPushButton(ph)
            b.setStyleSheet(_BTN_GHOST)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c, p=ph: self.body.insertPlainText(p))
            prow.addWidget(b)
        prow.addSpacing(12)
        self.btn_attach = QPushButton("📎 צרף קובץ")
        self.btn_attach.setStyleSheet(_BTN_GHOST)
        self.btn_attach.clicked.connect(self._pick_attachment)
        prow.addWidget(self.btn_attach)
        self.lbl_attach = QLabel("")
        self.lbl_attach.setStyleSheet("color:#64748b; font-size:12px; " + _LBL)
        prow.addWidget(self.lbl_attach)
        self.btn_attach_clear = QPushButton("✕")
        self.btn_attach_clear.setStyleSheet(_BTN_LINK)
        self.btn_attach_clear.setToolTip("הסר את הקובץ המצורף")
        self.btn_attach_clear.clicked.connect(lambda: self._set_attachment(""))
        self.btn_attach_clear.hide()
        prow.addWidget(self.btn_attach_clear)
        prow.addStretch()
        left.addLayout(prow)
        self.chk_header = QCheckBox("להוסיף כותרת עם הלוגו של הקופה")
        self.chk_header.setChecked(True)
        self.chk_header.toggled.connect(self._schedule_preview)
        left.addWidget(self.chk_header)
        two.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        ptitle = QHBoxLayout()
        self.lbl_preview_title = self._lbl("כך זה ייראה")
        ptitle.addWidget(self.lbl_preview_title)
        ptitle.addStretch()
        self.btn_preview_next = QPushButton("נמען אחר ◂")
        self.btn_preview_next.setStyleSheet(_BTN_LINK)
        self.btn_preview_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview_next.setToolTip("הצג איך ההודעה תיראה אצל הנמען הבא ברשימה")
        self.btn_preview_next.clicked.connect(self._preview_next)
        ptitle.addWidget(self.btn_preview_next)
        right.addLayout(ptitle)
        self.preview = QTextBrowser()
        self.preview.setMinimumWidth(300)
        self.preview.setOpenExternalLinks(False)
        # font-size ב-QSS = גופן-הבסיס של המסמך (ה-QSS הכללי של האפליקציה דורס setDefaultFont)
        self.preview.setStyleSheet("QTextBrowser{background:#fcfefd; border:1px dashed #cbd5e1; border-radius:8px;"
                                   " padding:8px; font-size:15px;}")
        right.addWidget(self.preview, 1)
        two.addLayout(right, 2)
        c_lay.addLayout(two)
        lay.addWidget(card)

        # היסטוריה
        card, c_lay, c_head = _step_card("", "היסטוריית שליחות", "כל מייל שנשלח מהתוכנה, משני המחשבים")
        self.hist = QTableWidget(0, 7)
        self.hist.setHorizontalHeaderLabels(["מתי", "נושא", "למי", "מצב", "נשלחו", "נכשלו", ""])
        self.hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist.verticalHeader().setVisible(False)
        hh = self.hist.horizontalHeader()
        for i in (0, 2, 3, 4, 5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self._HIST_ACT, QHeaderView.ResizeMode.Fixed)
        self.hist.setColumnWidth(self._HIST_ACT, 230)
        self.hist.setStyleSheet("QTableWidget{background:#fff; border:1px solid #e6eaf2; border-radius:8px;}")
        self.hist.cellDoubleClicked.connect(lambda r, _c: self._show_details(r))
        c_lay.addWidget(self.hist)
        self.lbl_hist_empty = QLabel("עדיין לא נשלחו מיילים מהתוכנה.")
        self.lbl_hist_empty.setStyleSheet("color:#94a3b8; " + _LBL)
        c_lay.addWidget(self.lbl_hist_empty)
        lay.addWidget(card)
        lay.addStretch()

        # ③ סרגל תחתון
        bar = QFrame()
        bar.setObjectName("ui-card")
        bar.setStyleSheet(_CARD_QSS + "QFrame#ui-card{border-radius:0; border-left:none; border-right:none; border-bottom:none;}")
        b_lay = QVBoxLayout(bar)
        b_lay.setContentsMargins(20, 10, 20, 10)
        b_lay.setSpacing(6)
        srow = QHBoxLayout()
        srow.setSpacing(12)
        srow.addWidget(_step_badge("3"))
        self.lbl_summary = QLabel("")
        self.lbl_summary.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_summary.setStyleSheet("color:#334155; font-size:13.5px; " + _LBL)
        self.lbl_summary.setWordWrap(True)
        srow.addWidget(self.lbl_summary, 1)
        b_lay.addLayout(srow)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addStretch()
        self.btn_test = QPushButton("שלח בדיקה אליי")
        self.btn_test.setStyleSheet(_BTN_ACCENT)
        self.btn_test.setToolTip("שולח את ההודעה (עם השם של הנמען הראשון) לכתובת של חשבון הקופה")
        self.btn_test.clicked.connect(self._send_test)
        row.addWidget(self.btn_test)
        self.btn_send = QPushButton("שלח עכשיו  ✉")
        self.btn_send.setStyleSheet(_BTN_PRINT)
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        b_lay.addLayout(row)
        self.prog_box = QWidget()
        p_lay = QHBoxLayout(self.prog_box)
        p_lay.setContentsMargins(40, 0, 0, 0)
        p_lay.setSpacing(10)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(10)
        p_lay.addWidget(self.prog, 1)
        self.lbl_prog = QLabel("")
        self.lbl_prog.setStyleSheet("color:#475569; font-size:12.5px; " + _LBL)
        p_lay.addWidget(self.lbl_prog)
        self.btn_stop = QPushButton("עצור")
        self.btn_stop.setStyleSheet(_BTN_DANGER)
        self.btn_stop.clicked.connect(self._stop)
        p_lay.addWidget(self.btn_stop)
        self.prog_box.hide()
        b_lay.addWidget(self.prog_box)
        s_lay.addWidget(bar)

    def _mode_btn(self, text, mode, layout):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setStyleSheet(_TOGGLE)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c, m=mode: self._set_mode(m))
        self._mode_group.addButton(b)
        layout.addWidget(b)
        return b

    # ---- v3.50: סרגל עיצוב (כמו ב-Gmail) ------------------------------------
    _SIZES = [("קטן", 11), ("רגיל", 0), ("גדול", 15), ("ענק", 20)]

    def _build_format_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("fmtbar")
        bar.setStyleSheet(_FMT_BAR_QSS)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        self._fmt_btns = {}

        def tb(key, text, tip, slot, checkable=False, bold=False, italic=False,
               underline=False, strike=False):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            f = b.font()
            f.setBold(bold); f.setItalic(italic); f.setUnderline(underline); f.setStrikeOut(strike)
            b.setFont(f)
            b.clicked.connect(slot)
            lay.addWidget(b)
            self._fmt_btns[key] = b
            return b

        def sep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setStyleSheet("color:#cbd5e1; margin:2px 4px;")
            lay.addWidget(s)

        tb("undo", "↶", "בטל", lambda: self.body.undo())
        tb("redo", "↷", "בצע שוב", lambda: self.body.redo())
        sep()
        self.size_combo = QComboBox()
        self.size_combo.setToolTip("גודל טקסט")
        for name, _pt in self._SIZES:
            self.size_combo.addItem(name)
        self.size_combo.setCurrentIndex(1)
        self.size_combo.activated.connect(self._apply_size)
        lay.addWidget(self.size_combo)
        sep()
        tb("bold", "B", "מודגש (Ctrl+B)", self._toggle_bold, checkable=True, bold=True)
        tb("italic", "I", "נטוי (Ctrl+I)", self._toggle_italic, checkable=True, italic=True)
        tb("underline", "U", "קו תחתון (Ctrl+U)", self._toggle_underline, checkable=True, underline=True)
        tb("strike", "S", "קו חוצה", self._toggle_strike, checkable=True, strike=True)
        sep()
        tb("color", "A", "צבע טקסט", self._pick_color, bold=True)
        tb("bg", "🖍", "צבע הדגשה (מרקר)", self._pick_bg)
        sep()
        tb("right", "⇥", "יישור לימין", lambda: self._align(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute), checkable=True)
        tb("center", "☰", "מרכוז", lambda: self._align(Qt.AlignmentFlag.AlignHCenter), checkable=True)
        tb("left", "⇤", "יישור לשמאל", lambda: self._align(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute), checkable=True)
        sep()
        tb("ul", "•≡", "רשימת נקודות", lambda: self._list(QTextListFormat.Style.ListDisc), checkable=True)
        tb("ol", "1≡", "רשימה ממוספרת", lambda: self._list(QTextListFormat.Style.ListDecimal), checkable=True)
        sep()
        tb("link", "🔗", "הוסף קישור", self._insert_link)
        tb("clear", "Tx", "נקה עיצוב", self._clear_format)
        lay.addStretch()
        return bar

    def _body_markup(self) -> str:
        """גוף ההודעה כפי שנשמר/נשלח: טקסט-רגיל, או HTML נקי כשיש עיצוב."""
        return richtext.document_to_markup(self.body.document())

    def _merge(self, fmt: QTextCharFormat):
        cur = self.body.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.SelectionType.WordUnderCursor)
        cur.mergeCharFormat(fmt)
        self.body.mergeCurrentCharFormat(fmt)
        self.body.setFocus()

    def _toggle_bold(self):
        f = QTextCharFormat()
        on = self.body.fontWeight() < QFont.Weight.DemiBold.value
        f.setFontWeight(QFont.Weight.Bold.value if on else QFont.Weight.Normal.value)
        self._merge(f)

    def _toggle_italic(self):
        f = QTextCharFormat(); f.setFontItalic(not self.body.fontItalic()); self._merge(f)

    def _toggle_underline(self):
        f = QTextCharFormat(); f.setFontUnderline(not self.body.fontUnderline()); self._merge(f)

    def _toggle_strike(self):
        f = QTextCharFormat()
        f.setFontStrikeOut(not self.body.currentCharFormat().fontStrikeOut())
        self._merge(f)

    def _apply_size(self, idx: int):
        pt = self._SIZES[idx][1]
        f = QTextCharFormat()
        f.setFontPointSize(pt)   # 0 = "רגיל": בלי גודל מפורש (הגודל הבסיסי של העורך/המייל)
        self._merge(f)

    def _pick_color(self):
        c = QColorDialog.getColor(self.body.textColor(), self, "צבע טקסט")
        if c.isValid():
            f = QTextCharFormat(); f.setForeground(c); self._merge(f)

    def _pick_bg(self):
        c = QColorDialog.getColor(QColor("#fff59d"), self, "צבע הדגשה")
        if c.isValid():
            f = QTextCharFormat(); f.setBackground(c); self._merge(f)

    def _align(self, a):
        self.body.setAlignment(a)
        self.body.setFocus()
        self._sync_format_bar()

    def _list(self, style):
        cur = self.body.textCursor()
        lst = cur.currentList()
        if lst is not None and lst.format().style() == style:
            # כבר רשימה מהסוג הזה — לחיצה שנייה מבטלת
            lst.remove(cur.block())
            bf = cur.blockFormat(); bf.setIndent(0); cur.setBlockFormat(bf)
        else:
            cur.createList(style)
        self.body.setFocus()
        self._sync_format_bar()

    def _insert_link(self):
        cur = self.body.textCursor()
        sel = cur.selectedText().strip()
        url, okk = QInputDialog.getText(self, "הוסף קישור", "כתובת (למשל https://…):",
                                        text=sel if sel.startswith("http") else "")
        url = (url or "").strip()
        if not okk or not url:
            return
        if not url.lower().startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        f = QTextCharFormat()
        f.setAnchor(True); f.setAnchorHref(url)
        f.setForeground(QColor("#0f766e")); f.setFontUnderline(True)
        if cur.hasSelection():
            cur.mergeCharFormat(f)
        else:
            cur.insertText(url, f)
        cur.setCharFormat(QTextCharFormat())
        self.body.setTextCursor(cur)
        self.body.setCurrentCharFormat(QTextCharFormat())
        self.body.setFocus()

    def _clear_format(self):
        cur = self.body.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.SelectionType.Document)
        cur.setCharFormat(QTextCharFormat())
        bf = cur.blockFormat(); bf.setAlignment(Qt.AlignmentFlag.AlignLeading); bf.setIndent(0)
        cur.setBlockFormat(bf)
        lst = cur.currentList()
        if lst is not None:
            lst.remove(cur.block())
        self.body.setCurrentCharFormat(QTextCharFormat())
        self.body.setFocus()
        self._sync_format_bar()

    def _sync_format_bar(self, *_a):
        if not getattr(self, "_fmt_btns", None):
            return
        cf = self.body.currentCharFormat()
        b = self._fmt_btns
        b["bold"].setChecked(cf.fontWeight() >= QFont.Weight.DemiBold.value)
        b["italic"].setChecked(cf.fontItalic())
        b["underline"].setChecked(cf.fontUnderline() and not cf.isAnchor())
        b["strike"].setChecked(cf.fontStrikeOut())
        al = richtext.align_kind(self.body.alignment())
        b["center"].setChecked(al == "center")
        b["left"].setChecked(al == "left")
        b["right"].setChecked(al == "")
        lst = self.body.textCursor().currentList()
        st = lst.format().style() if lst is not None else None
        b["ul"].setChecked(st == QTextListFormat.Style.ListDisc)
        b["ol"].setChecked(st == QTextListFormat.Style.ListDecimal)
        ps = cf.fontPointSize()
        idx = next((i for i, (_n, pt) in enumerate(self._SIZES) if pt and abs(pt - ps) < 0.5), 1)
        self.size_combo.setCurrentIndex(idx)

    @staticmethod
    def _lbl(text):
        l = QLabel(text)
        l.setStyleSheet("color:#64748b; font-size:12.5px; font-weight:700; " + _LBL)
        return l

    def _goto_settings(self):
        if self.main and hasattr(self.main, "navigate_to_tab"):
            self.main.navigate_to_tab(self.main.settings_tab)

    # ── refresh / state ───────────────────────────────────────────────────────

    def refresh(self):
        self._refresh_account()
        self._load_templates()
        self._rebuild_targets()
        self._refresh_history()

    def _refresh_account(self):
        if email_utils.google_connected():
            self.chip_account.setText("✓ מחובר ל-Google: " + (email_utils.sender_email() or "מחובר"))
            self.chip_account.setStyleSheet(_HCHIP_GREEN)
        elif email_utils.smtp_configured():
            self.chip_account.setText("✓ שולח מהחשבון " + email_utils.sender_email())
            self.chip_account.setStyleSheet(_HCHIP_GREEN)
        else:
            self.chip_account.setText("●  עוד לא חובר חשבון מייל")
            self.chip_account.setStyleSheet(_HCHIP_AMBER)
        self.btn_settings.setVisible(not email_utils.is_configured())
        active = db.get_all_recipients("פעיל")
        n = sum(1 for r in active if (r.get("email") or "").strip())
        self.chip_with_mail.setText(f"{n} מתוך {len(active)} מקבלים עם כתובת מייל")
        self.chip_with_mail.setToolTip("כמה מהמקבלים הפעילים רשומים עם כתובת מייל בכרטיס")
        # v3.55: כל כפתור-מקור אומר כמה אנשים יש בו — לפני שלוחצים
        self.btn_mode_all.setText(f"{self._MODE_TEXT['all']} · {len(active)}")
        gt = getattr(self.main, "group_tab", None)
        try:
            reserve_ids = getattr(gt, "_reserve_ids", set()) or set()
            cur_n = sum(1 for r in (gt._rows_data or [])
                        if not r.get("_reserve") and r.get("id") not in reserve_ids)
        except Exception:
            cur_n = None
        self.btn_mode_current.setText(self._MODE_TEXT["current"] + (f" · {cur_n}" if cur_n else ""))

    def _set_mode(self, mode):
        self._mode = mode
        self._removed.clear()
        self._preview_idx = 0
        self.list_search.clear()
        self.btn_show_bad.setChecked(False)
        self._rebuild_targets()

    def _source_recs(self) -> list[dict]:
        if self._mode == self.MODE_ALL:
            return db.get_all_recipients("פעיל")
        if self._mode == self.MODE_CURRENT:
            gt = getattr(self.main, "group_tab", None)
            if gt is None:
                return []
            try:
                if not gt._rows_data:
                    gt.refresh()
            except Exception:
                pass
            reserve_ids = getattr(gt, "_reserve_ids", set()) or set()
            ids = [r.get("id") for r in (gt._rows_data or [])
                   if not r.get("_reserve") and r.get("id") not in reserve_ids]
            out = []
            for i in ids:
                rec = db.get_recipient(i)
                if rec:
                    out.append(dict(rec))
            return out
        return []

    def _dist_iso(self) -> str:
        gt = getattr(self.main, "group_tab", None)
        try:
            return gt.date_edit.get_iso() or db.next_wednesday().isoformat()
        except Exception:
            try:
                return db.next_wednesday().isoformat()
            except Exception:
                return ""

    def _rebuild_targets(self):
        recs = [r for r in self._source_recs() if r["id"] not in self._removed]
        ids = {r["id"] for r in recs}
        for p in self._picked:
            if p["id"] not in ids and p["id"] not in self._removed:
                fresh = db.get_recipient(p["id"])
                if fresh:
                    recs.append(dict(fresh))
                    ids.add(p["id"])
        self._recs = {r["id"]: r for r in recs}
        self._targets = mailer.build_targets(recs, self._extra)
        self._fill_table()
        self._update_metrics()
        self._schedule_preview()

    def _fill_table(self):
        t = self.table
        t.setRowCount(0)
        t.setRowCount(len(self._targets))
        for i, tg in enumerate(self._targets):
            name = QTableWidgetItem(tg["name"] + ("  (חיצוני)" if tg.get("external") else ""))
            t.setItem(i, 0, name)
            t.setItem(i, 1, QTableWidgetItem(tg["email"]))
            fixable = not tg["ok"] and tg.get("rec_id") is not None
            st = QTableWidgetItem("● יקבל" if tg["ok"] else
                                  "⚠ " + tg["reason"] + (" · תקן…" if fixable else ""))
            st.setForeground(QColor("#15803d") if tg["ok"] else QColor("#92600a"))
            if fixable:
                st.setToolTip("לחיצה פותחת את כרטיס המקבל — להוספה או לתיקון של כתובת המייל")
            t.setItem(i, 2, st)
            # v3.55: פריט-טקסט + cellClicked במקום 500 כפתורים (מהיר, ולא נחתך בתא)
            rm = QTableWidgetItem("✕ הסר")
            rm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            rm.setForeground(QColor("#0f766e"))
            rm.setToolTip("הסר מהשליחה הזו (הכרטיס עצמו לא נמחק)")
            t.setItem(i, 3, rm)
            if not tg["ok"]:                       # שורת-חריג כולה בענבר בהיר
                for c in range(4):
                    t.item(i, c).setBackground(QColor("#fff8e6"))
        self._apply_filter()

    def _apply_filter(self, *_a):
        """v3.55 — חיפוש ברשימה + "הצג רק את מי שבלי מייל"; גובה הטבלה לפי השורות הגלויות."""
        t = self.table
        text = self.list_search.text().strip().lower()
        only_bad = self.btn_show_bad.isChecked()
        shown = 0
        for i, tg in enumerate(self._targets):
            hide = (only_bad and tg["ok"]) or bool(
                text and text not in tg["name"].lower() and text not in (tg["email"] or "").lower())
            t.setRowHidden(i, hide)
            shown += 0 if hide else 1
        rows = min(shown, _MAX_TABLE_ROWS)
        h = t.horizontalHeader().height() + rows * (t.verticalHeader().defaultSectionSize()) + 6
        t.setFixedHeight(max(h, 60))
        empty = not self._targets
        if empty:
            self.lbl_list_empty.setText(
                "הרשימה ריקה — בחר אנשים עם <b>＋ הוסף אדם</b>, או הוסף <b>כתובת מייל חיצונית</b>."
                if self._mode == self.MODE_MANUAL else
                "אין כרגע רשימת חלוקה — הכן את החלוקה במסך \"חלוקה\", או בחר \"כל המקבלים\"."
                if self._mode == self.MODE_CURRENT else "אין עדיין מקבלים פעילים בתוכנה.")
        self.lbl_list_empty.setVisible(empty)
        t.setVisible(not empty)
        self.lbl_list_hint.setVisible(not empty)
        self.list_search.setVisible(len(self._targets) > 8 or bool(text))

    def _on_cell_clicked(self, r: int, c: int):
        if not (0 <= r < len(self._targets)):
            return
        tg = self._targets[r]
        if c == 3:
            self._remove_target(tg)
        elif c == 2 and not tg["ok"]:
            self._open_row_card(r, c)

    def _open_row_card(self, r: int, c: int = 0):
        """v3.55 — פותח את כרטיס המקבל מתוך הרשימה, כדי להוסיף/לתקן מייל בלי לעזוב את המסך."""
        if c == 3 or not (0 <= r < len(self._targets)):
            return
        rec_id = self._targets[r].get("rec_id")
        rec = db.get_recipient(rec_id) if rec_id is not None else None
        if not rec:
            return
        from tabs.recipients import RecipientDialog
        from utils.backup import auto_backup_async
        dlg = RecipientDialog(self, rec)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        db.update_recipient(rec_id, dlg.get_data())
        auto_backup_async()
        if self.main is not None and hasattr(self.main, "refresh_all"):
            self.main.refresh_all()
        self.refresh()

    def _update_metrics(self):
        ok = sum(1 for t in self._targets if t["ok"])
        _set_metric(self.m_total, len(self._targets))
        _set_metric(self.m_ok, ok)
        _set_metric(self.m_bad, len(self._targets) - ok)
        bad = len(self._targets) - ok
        if not bad and self.btn_show_bad.isChecked():
            self.btn_show_bad.setChecked(False)
        self.btn_show_bad.setVisible(bad > 0)
        sending = self._worker is not None
        has_subj = bool(self.subject.text().strip())
        has_body = bool(self.body.toPlainText().strip())     # noqa — רק "ריק?", התוכן דרך _body_markup
        # חיוויי הכותרת + ✓ ירוק בתגי השלבים
        if ok:
            self.chip_ready.setText(f"✓ {ok} יקבלו מייל")
            self.chip_ready.setStyleSheet(_HCHIP_GREEN)
        else:
            self.chip_ready.setText("●  אין עדיין נמענים")
            self.chip_ready.setStyleSheet(_HCHIP_AMBER)
        if has_subj and has_body:
            self.chip_msg.setText("✓ ההודעה מוכנה")
            self.chip_msg.setStyleSheet(_HCHIP_GREEN)
        else:
            self.chip_msg.setText("●  " + ("עוד לא נכתבה הודעה" if not (has_subj or has_body)
                                           else "חסר נושא" if not has_subj else "חסר תוכן"))
            self.chip_msg.setStyleSheet(_HCHIP_AMBER)
        self.chip_sending.setVisible(sending)
        if sending:
            self.chip_sending.setText("✉ שליחה רצה עכשיו…")
        _set_step_done(self.card_list, "1", ok > 0)
        _set_step_done(self.card_msg, "2", has_subj and has_body)
        self._refresh_summary(ok, bad, has_subj, has_body, sending)
        testing = getattr(self, "_test_worker", None) is not None
        self.btn_send.setEnabled(email_utils.is_configured() and ok > 0 and not sending)
        self.btn_test.setEnabled(email_utils.is_configured() and not sending and not testing)

    def _refresh_summary(self, ok, bad, has_subj, has_body, sending):
        """v3.55 — שורת המוכנות של ③: מה מוכן ומה חסר (כמו בצינתוקים)."""
        good, warn, mut = "#15803d", "#92600a", "#64748b"

        def part(done, yes, no):
            return (f"<span style='color:{good}'>☑ {yes}</span>" if done
                    else f"<span style='color:{warn}'>☐ {no}</span>")

        parts = [part(email_utils.is_configured(),
                      "מהחשבון " + html.escape(email_utils.sender_email() or ""),
                      "חבר חשבון מייל בהגדרות (\"התחבר עם Google\")"),
                 part(ok > 0, f"{ok} נמענים — כל אחד מקבל מייל אישי ורואה רק את עצמו",
                      "אין נמענים עם כתובת מייל (שלב 1)"),
                 part(has_subj and has_body, "ההודעה כתובה",
                      "כתוב נושא ותוכן (שלב 2)" if not (has_subj or has_body)
                      else "חסר נושא (שלב 2)" if not has_subj else "חסר תוכן (שלב 2)")]
        if self._attachment:
            parts.append(f"<span style='color:{mut}'>📎 {html.escape(os.path.basename(self._attachment))}</span>")
        tail = ""
        if sending:
            tail = "השליחה רצה — הכפתורים נעולים עד הסיום"
        elif bad:
            tail = f"{bad} בלי כתובת מייל — לא יישלח להם"
        if tail:
            parts.append(f"<span style='color:{mut}'>{tail}</span>")
        self.lbl_summary.setText(" &nbsp;·&nbsp; ".join(parts))
        self.btn_send.setText(f"שלח עכשיו ל-{ok}  ✉" if ok else "שלח עכשיו  ✉")

    def _remove_target(self, tg):
        if tg.get("external"):
            self._extra = [a for a in self._extra if a.lower() != tg["email"].lower()]
        else:
            self._removed.add(tg["rec_id"])
            self._picked = [p for p in self._picked if p["id"] != tg["rec_id"]]
        self._rebuild_targets()

    def _show_bad(self):
        lines = [f"{t['name']} — {t['reason']}" for t in self._targets if not t["ok"]]
        _NamesDialog("בלי מייל / לא יישלח", lines, self).exec()

    def _add_person(self):
        dlg = _PickPersonDialog({t["rec_id"] for t in self._targets if t.get("rec_id") is not None}, self)
        if dlg.exec() and dlg.picked:
            self._removed.discard(dlg.picked["id"])
            self._picked.append(dlg.picked)
            if not (dlg.picked.get("email") or "").strip():
                QMessageBox.information(self, "אין מייל",
                                        f"ל{dlg.picked['full_name']} אין כתובת מייל בכרטיס — "
                                        "הוא יופיע ברשימה אבל לא יקבל. אפשר להוסיף מייל בכרטיס המקבל.")
            self._rebuild_targets()

    def _add_address(self):
        addr, ok = QInputDialog.getText(self, "כתובת מייל חיצונית", "כתובת מייל:")
        if not ok:
            return
        addr = addr.strip()
        if not mailer.valid_email(addr):
            QMessageBox.warning(self, "", "הכתובת לא נראית תקינה (צריך משהו כמו name@gmail.com).")
            return
        self._extra.append(addr)
        self._rebuild_targets()

    # ── message / templates ───────────────────────────────────────────────────

    def _schedule_preview(self, *_):
        self._preview_timer.start()

    def _ctx(self):
        return mailer.default_context(self._dist_iso())

    def _update_preview(self):
        self._update_metrics()
        oks = [t for t in self._targets if t["ok"]]
        first = oks[self._preview_idx % len(oks)] if oks else None
        self.btn_preview_next.setVisible(len(oks) > 1)
        rec = self._recs.get(first["rec_id"]) if first and first.get("rec_id") is not None else None
        ctx = dict(self._ctx(), fallback_name=first["name"] if first else "ישראל ישראלי")
        subj = mailer.render(self.subject.text(), rec, ctx)
        logo_url = QUrl.fromLocalFile(_logo_path()).toString() if _logo_path() else ""
        body = mailer.html_body(mailer.render(self._body_markup(), rec, ctx),
                                self.chk_header.isChecked()).replace("src='cid:logo'", f"src='{logo_url}'")
        who = first["name"] if first else "נמען לדוגמה"
        self.lbl_preview_title.setText(f"כך זה ייראה אצל {who}")
        self.preview.setHtml(f"<div dir='rtl'><div style='color:#64748b;font-size:12px'>נושא:</div>"
                             f"<div style='font-weight:700;margin-bottom:10px'>{html.escape(subj)}</div>{body}</div>")

    def _preview_next(self):
        self._preview_idx += 1
        self._update_preview()

    def _load_templates(self):
        self._templates = db.get_mail_templates()
        self.tpl_combo.blockSignals(True)
        self.tpl_combo.clear()
        self.tpl_combo.addItem("— בלי תבנית —", "")
        sel = 0
        for i, t in enumerate(self._templates, 1):
            self.tpl_combo.addItem(t["name"], t["guid"])
            if t["guid"] == self._current_tpl_guid:
                sel = i
        self.tpl_combo.setCurrentIndex(sel)
        self.tpl_combo.blockSignals(False)
        self.btn_tpl_del.setEnabled(bool(self._current_tpl_guid))

    def _tpl_selected(self, _i):
        guid = self.tpl_combo.currentData() or ""
        self._current_tpl_guid = guid
        self.btn_tpl_del.setEnabled(bool(guid))
        t = next((x for x in self._templates if x["guid"] == guid), None)
        if t:
            self.subject.setText(t["subject"])
            richtext.load_into(self.body, t["body"])

    def _save_template(self):
        if not self.subject.text().strip() and not self.body.toPlainText().strip():  # noqa
            QMessageBox.information(self, "", "אין מה לשמור — כתוב נושא ותוכן קודם.")
            return
        cur = next((x for x in self._templates if x["guid"] == self._current_tpl_guid), None)
        name, ok = QInputDialog.getText(self, "שמירת תבנית", "שם התבנית:",
                                        text=cur["name"] if cur else self.subject.text()[:40])
        if not ok or not name.strip():
            return
        name = name.strip()
        guid = cur["guid"] if cur and cur["name"] == name else ""
        if not guid:
            # v3.47: שם של תבנית קיימת (לא זו שנבחרה) → מעדכנים אותה, לא יוצרים כפילות-שם
            same = next((x for x in self._templates if x["name"].strip().lower() == name.lower()), None)
            if same:
                if QMessageBox.question(self, "תבנית קיימת",
                                        f"כבר יש תבנית בשם \"{name}\" — להחליף את התוכן שלה?") \
                        != QMessageBox.StandardButton.Yes:
                    return
                guid = same["guid"]
        self._current_tpl_guid = db.upsert_mail_template(
            name, self.subject.text(), self._body_markup(), guid=guid)
        self._load_templates()

    def _delete_template(self):
        if not self._current_tpl_guid:
            return
        if QMessageBox.question(self, "מחיקת תבנית", "למחוק את התבנית הזו (בשני המחשבים)?") \
                != QMessageBox.StandardButton.Yes:
            return
        db.delete_mail_template(self._current_tpl_guid)
        self._current_tpl_guid = ""
        self._load_templates()

    def _pick_attachment(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר קובץ לצירוף")
        if path:
            # v3.46: Gmail מגבילה ל-25MB *אחרי* קידוד (×1.37) ⇒ קובץ עד 18MB
            if os.path.getsize(path) > email_utils.MAX_ATTACHMENT_BYTES:
                mb = os.path.getsize(path) / (1024 * 1024)
                QMessageBox.warning(self, "", f"הקובץ גדול מדי ({mb:.0f}MB). Gmail מקבלת מייל עד 25MB "
                                    "כולל הקידוד, לכן הקובץ המצורף יכול להיות עד 18MB.")
                return
            self._set_attachment(path)

    def _set_attachment(self, path):
        self._attachment = path or ""
        self.lbl_attach.setText(os.path.basename(path) if path else "")
        self.btn_attach_clear.setVisible(bool(path))
        self._update_metrics()

    # ── sending ───────────────────────────────────────────────────────────────

    def _audience_text(self) -> str:
        base = {self.MODE_ALL: "כל המקבלים", self.MODE_CURRENT: "רשימת החלוקה הנוכחית",
                self.MODE_MANUAL: "בחירה ידנית"}[self._mode]
        extra = []
        if self._picked and self._mode != self.MODE_MANUAL:
            extra.append(f"+{len(self._picked)} שנוספו")
        if self._removed:
            extra.append(f"−{len(self._removed)} שהוסרו")
        if self._extra:
            extra.append(f"+{len(self._extra)} חיצוניים")
        return base + (" (" + ", ".join(extra) + ")" if extra else "")

    def _validate_message(self, subject: str | None = None, body: str | None = None) -> bool:
        subject = self.subject.text() if subject is None else subject
        body = self._body_markup() if body is None else body
        if not subject.strip():
            QMessageBox.warning(self, "", "חסר נושא להודעה.")
            return False
        if not mailer.to_plain(body).strip():
            QMessageBox.warning(self, "", "ההודעה ריקה.")
            return False
        if not email_utils.is_configured():
            QMessageBox.warning(self, "", "חבר קודם חשבון מייל בהגדרות.")
            return False
        return True

    def _send_test(self):
        if not self._validate_message():
            return
        if self._attachment and not os.path.exists(self._attachment):
            QMessageBox.warning(self, "", "הקובץ המצורף לא נמצא (נמחק או הועבר). הסר אותו או צרף מחדש.")
            return
        me = email_utils.sender_email()
        first = next((t for t in self._targets if t["ok"]), None)
        rec = self._recs.get(first["rec_id"]) if first and first.get("rec_id") is not None else None
        ctx = dict(self._ctx(), fallback_name=first["name"] if first else "ישראל ישראלי")
        subj = "[בדיקה] " + mailer.render(self.subject.text(), rec, ctx)
        rendered = mailer.render(self._body_markup(), rec, ctx)
        plain = mailer.to_plain(rendered)
        html = mailer.html_body(rendered, self.chk_header.isChecked())
        attach = self._attachment or None
        logo = _logo_path() if self.chk_header.isChecked() else None
        # ברקע — חיבור לשרת (במיוחד מאחורי נטפרי) יכול לקחת דקות; המסך לא קופא
        self.btn_test.setEnabled(False)
        self.btn_test.setText("שולח בדיקה…")
        self._test_worker = _BgWorker(
            lambda: email_utils.send_email(me, subj, html, attachment_path=attach,
                                           inline_logo_path=logo, text_body=plain), self)
        self._test_worker.done.connect(lambda res: self._test_done(res, me))
        self._test_worker.start()

    def _test_done(self, res, me):
        self._test_worker = None
        self.btn_test.setText("שלח בדיקה אליי")
        self._update_metrics()
        if isinstance(res, Exception):
            QMessageBox.warning(self, "בדיקה נכשלה", str(res))
        else:
            QMessageBox.information(
                self, "נשלח", f"מייל הבדיקה נשלח אל {me} ✓" + chr(10) + "בדוק בתיבת הדואר איך זה נראה.")

    def _send(self, targets=None, audience=None, subject=None, body=None,
              attachment=None, with_header=None):
        # v3.46: subject/body מפורשים = שליחה-חוזרת של הודעה ישנה; בלעדיהם = הטיוטה שבשדות.
        # כך "שלח שוב לנכשלים" לא דורס את מה שהמפעיל כתב (גם כשהוא מבטל בחלון האישור).
        # v3.47: גם attachment/with_header מפורשים — שליחה-חוזרת עם הקובץ *המקורי*.
        subject = self.subject.text() if subject is None else subject
        body = self._body_markup() if body is None else body
        attachment = (self._attachment or "") if attachment is None else (attachment or "")
        with_header = self.chk_header.isChecked() if with_header is None else bool(with_header)
        if self._worker is not None or not self._validate_message(subject, body):
            return
        targets = targets if targets is not None else [t for t in self._targets if t["ok"]]
        if not targets:
            return
        if attachment and not os.path.exists(attachment):
            QMessageBox.warning(self, "", "הקובץ המצורף לא נמצא (נמחק או הועבר). הסר אותו או צרף מחדש.")
            return
        audience = audience or self._audience_text()
        facts = [("נושא", html.escape(subject.strip())),
                 ("נמענים", f"<b>{len(targets)}</b> — {html.escape(audience)}"),
                 ("מהחשבון", html.escape(email_utils.sender_email() or "")),
                 ("כותרת עם לוגו", "כן" if with_header else "לא")]
        if attachment:
            facts.append(("קובץ מצורף", "📎 " + html.escape(os.path.basename(attachment))))
        msg = ("<div dir='rtl'><b style='font-size:15px'>לשלוח את המייל עכשיו?</b>"
               "<table cellspacing='0' cellpadding='4' style='margin-top:8px'>"
               + "".join(f"<tr><td style='color:#64748b'>{k}</td><td>{v}</td></tr>" for k, v in facts)
               + "</table><div style='color:#64748b; margin-top:6px'>כל נמען מקבל מייל אישי ורואה רק את עצמו."
                 " אפשר לעצור באמצע.</div></div>")
        if QMessageBox.question(self, "אישור שליחה", msg) != QMessageBox.StandardButton.Yes:
            return
        self._active_guid = db.add_mail_campaign(
            subject.strip(), body, audience,
            email_utils.sender_email(), len(targets), device=sync.device_name() or "",
            attachment=attachment, with_header=1 if with_header else 0)
        self._worker = _SendWorker(targets, subject.strip(), body,
                                   self._ctx(), attachment or None,
                                   with_header, dict(self._recs), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_rows.connect(self._on_finished)
        self.prog.setRange(0, len(targets))
        self.prog.setValue(0)
        self.lbl_prog.setText(f"שולח… 0 מתוך {len(targets)}")
        self.prog_box.show()
        self._sent_n = self._failed_n = 0
        # v3.43: כל הנמענים נרשמים מראש כ"ממתין" — שליחה שנקטעה יודעת את מי לא ניסתה
        self._rows_acc = mailer.pending_rows(targets)
        db.update_mail_campaign(self._active_guid, 0, 0, "sending",
                                json.dumps(self._rows_acc, ensure_ascii=False), sync=False)
        self.btn_stop.setEnabled(True)
        self._update_metrics()
        self._worker.start()

    def _on_progress(self, done, total, row):
        if row.get("status") == "sent":
            self._sent_n += 1
        elif row.get("status") == "failed":
            self._failed_n += 1
        self.prog.setValue(done)
        self.lbl_prog.setText(f"שולח… {done} מתוך {total} · נשלחו {self._sent_n} · נכשלו {self._failed_n}")
        # v3.42: התקדמות נשמרת מקומית (בלי סנכרון) — אם התוכנה תיסגר באמצע,
        # הרשומה שתיסגר כ"נקטע" תדע מי כבר קיבל ומי לא ("שלח שוב לנכשלים").
        if 0 < done <= len(self._rows_acc):
            self._rows_acc[done - 1] = dict(row)      # מחליף את שורת ה"ממתין"
        else:
            self._rows_acc.append(dict(row))
        if self._active_guid:
            db.update_mail_campaign(self._active_guid, self._sent_n, self._failed_n, "sending",
                                    json.dumps(self._rows_acc, ensure_ascii=False), sync=False)

    def _on_finished(self, rows):
        guid, self._active_guid = self._active_guid, ""
        self._worker = None
        self.prog_box.hide()
        if isinstance(rows, Exception):
            # v3.43: מי שכבר קיבל נשאר בדוח; מי שלא נוסה מסומן לשליחה חוזרת
            kept = mailer.close_pending(getattr(self, "_rows_acc", []), str(rows))
            sent, failed = mailer.summarize(kept)
            db.update_mail_campaign(guid, sent, failed, "failed", json.dumps(kept, ensure_ascii=False))
            QMessageBox.warning(self, "השליחה נכשלה", str(rows))
        else:
            sent, failed = mailer.summarize(rows)
            stopped = any(r.get("status") == "skipped" for r in rows)
            db.update_mail_campaign(guid, sent, failed, "stopped" if stopped else "done",
                                    json.dumps(rows, ensure_ascii=False))
            txt = f"נשלחו {sent} מיילים בהצלחה."
            if failed:
                txt += f"\n{failed} נכשלו — ראה \"פרטים\" בהיסטוריה, ואפשר \"שלח שוב לנכשלים\"."
            reason = mailer.stop_reason(rows)
            if reason:
                # תקלה כללית (אין אינטרנט / סיסמה / מכסה) — עצרנו לבד, לא ניסינו לכולם
                skipped = sum(1 for r in rows if r.get("status") == "skipped")
                txt += (f"\n\nהשליחה נעצרה אחרי תקלה שתחזור אצל כולם ({skipped} לא נוסו):\n{reason}"
                        "\n\nאחרי שהבעיה נפתרת — \"שלח שוב לנכשלים\" בהיסטוריה ישלח להם.")
                QMessageBox.warning(self, "השליחה נעצרה", txt)
            else:
                if stopped:
                    txt += "\nהשליחה נעצרה לפני הסוף."
                QMessageBox.information(self, "סיום שליחה", txt)
        self._refresh_history()
        self._update_metrics()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self.lbl_prog.setText("עוצר אחרי המייל הנוכחי…")

    # ── סגירת התוכנה באמצע שליחה (v3.46) ─────────────────────────────────────

    def sending_active(self) -> bool:
        return self._worker is not None

    def confirm_close(self) -> bool:
        """נקרא מ-MainWindow.closeEvent כשיש שליחה פעילה. False = לא לסגור.
        True = המפעיל אישר; השליחה נעצרה אחרי המייל הנוכחי והרשומה נסגרה כ'נקטע'
        (מי שקיבל נשאר, מי שלא נוסה מסומן לשליחה חוזרת) — במקום להישאר "בתהליך"
        עד ההפעלה הבאה."""
        if self._worker is None:
            return True
        total = max(self.prog.maximum(), 1)
        ans = QMessageBox.question(
            self, "שליחת מיילים פעילה",
            f"יש שליחת מיילים באמצע — נשלחו {self._sent_n} מתוך {total}.\n"
            "לסגור את התוכנה בכל זאת?\n\nמי שעדיין לא קיבל יסומן \"לא נשלח\", ואפשר יהיה "
            "לשלוח לו דרך \"שלח שוב לנכשלים\" בהיסטוריה.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return False
        self._abort_for_close()
        return True

    def guard_update(self) -> bool:
        """v3.47: התקנת עדכון-תוכנה יוצאת ב-`QApplication.quit()` — *לא* עוברת ב-closeEvent,
        ולכן שליחה פעילה הייתה נהרגת בשקט (thread מת עם התהליך, הרשומה "בתהליך" עד
        ההפעלה הבאה). ההורדה וההתקנה שואלות כאן קודם; אישור = עצירה מסודרת (כמו סגירה)."""
        return self.confirm_close()

    def _abort_for_close(self, wait_ms: int = 8000):
        w, self._worker = self._worker, None
        guid, self._active_guid = self._active_guid, ""
        if w is None:
            return
        try:
            w.finished_rows.disconnect(self._on_finished)   # לא לפתוח הודעת-סיום על מסך שנסגר
        except Exception:
            pass
        w.stop()
        try:
            w.wait(wait_ms)                                   # מחכים למייל הנוכחי (לא קוטעים באמצע)
            from PyQt6.QtCore import QCoreApplication
            QCoreApplication.processEvents()                  # progress שממתין בתור → _rows_acc
        except Exception:
            pass
        if guid:
            rows = mailer.close_pending(getattr(self, "_rows_acc", []))
            sent, failed = mailer.summarize(rows)
            db.update_mail_campaign(guid, sent, failed, "interrupted",
                                    json.dumps(rows, ensure_ascii=False))

    def _close_stale_campaigns(self):
        """שליחה שנקטעה (התוכנה נסגרה באמצע) — לא להשאיר "בתהליך" לנצח."""
        me = sync.device_name() or ""
        for c in db.get_mail_campaigns():
            if c.get("status") == "sending" and (c.get("device") or "") == me \
                    and c.get("guid") != self._active_guid:
                try:
                    rows = json.loads(c.get("report_json") or "[]")
                except Exception:
                    rows = []
                # v3.43: מי שנשאר "ממתין" → "לא נשלח" עם סיבה, כדי ששליחה-חוזרת תאסוף אותו
                rows = mailer.close_pending(rows)
                sent, failed = mailer.summarize(rows)
                db.update_mail_campaign(c["guid"], sent, failed, "interrupted",
                                        json.dumps(rows, ensure_ascii=False))

    # ── history ───────────────────────────────────────────────────────────────

    _STATUS_HE = {"sending": "בתהליך…", "done": "הושלם", "stopped": "נעצר",
                  "interrupted": "נקטע", "failed": "נכשל"}
    # v3.55: עמודת "מצב" בהיסטוריה — (טקסט, צבע)
    _HIST_STATUS = {"sending": ("⏳ נשלח עכשיו…", "#92600a"), "done": ("✓ הושלם", "#15803d"),
                    "stopped": ("⛔ נעצר באמצע", "#b45309"), "interrupted": ("⚠ נקטע באמצע", "#b45309"),
                    "failed": ("✗ נכשל", "#b91c1c")}

    def _refresh_history(self):
        self._camps = db.get_mail_campaigns(limit=200)
        h = self.hist
        h.setRowCount(0)
        h.setRowCount(len(self._camps))
        for i, c in enumerate(self._camps):
            full = timefmt.datetime_str(c.get("sent_at", ""))
            when = QTableWidgetItem(timefmt.relative(c.get("sent_at", "")) or full)
            when.setToolTip(full)
            h.setItem(i, 0, when)
            subj = QTableWidgetItem(("📎 " if (c.get("attachment") or "").strip() else "") + c.get("subject", ""))
            subj.setToolTip("לחיצה כפולה — פירוט לפי נמען")
            h.setItem(i, 1, subj)
            h.setItem(i, 2, QTableWidgetItem(c.get("audience", "")))
            txt, color = self._HIST_STATUS.get(c.get("status", ""), ("", "#334155"))
            if c.get("status") == "done" and c.get("failed"):
                txt, color = "✓ הושלם, חלק נכשלו", "#b45309"
            st = QTableWidgetItem(txt)
            st.setForeground(QColor(color))
            h.setItem(i, 3, st)
            n_sent = QTableWidgetItem(f"{c.get('sent', 0)} מתוך {c.get('total', 0) or c.get('sent', 0)}")
            n_sent.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            h.setItem(i, 4, n_sent)
            f = QTableWidgetItem(str(c.get("failed", 0)) if c.get("failed") else "—")
            f.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c.get("failed"):
                f.setForeground(QColor("#b91c1c"))
            h.setItem(i, 5, f)
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(4)
            b1 = QPushButton("פרטים")
            b1.setStyleSheet(_BTN_LINK)
            b1.clicked.connect(lambda _c, r=i: self._show_details(r))
            wl.addWidget(b1)
            try:
                _rows = json.loads(c.get("report_json") or "[]")
            except Exception:
                _rows = []
            # v3.43: גם כשנכשלו=0 — עצירה ידנית / נקטע משאירים 'לא נשלח' שצריך לשלוח שוב
            if c.get("failed") or mailer.resendable(_rows):
                b2 = QPushButton("שלח שוב לנכשלים")
                b2.setStyleSheet(_BTN_LINK)
                b2.clicked.connect(lambda _c, r=i: self._resend_failed(r))
                wl.addWidget(b2)
            wl.addStretch()
            h.setCellWidget(i, self._HIST_ACT, w)
        rows = min(len(self._camps), 8)
        hh = h.horizontalHeader().height() + rows * h.verticalHeader().defaultSectionSize() + 6
        h.setFixedHeight(max(hh, 40))
        h.setVisible(bool(self._camps))
        self.lbl_hist_empty.setVisible(not self._camps)

    def _show_details(self, row):
        if 0 <= row < len(self._camps):
            _HistoryDetailDialog(self._camps[row], self).exec()

    def _resend_failed(self, row):
        if not (0 <= row < len(self._camps)):
            return
        if self._worker is not None:
            # v3.43: לא לדרוס את הטיוטה שבשדות באמצע שליחה פעילה
            QMessageBox.information(self, "", "יש שליחה פעילה — המתן לסיומה ואז שלח שוב לנכשלים.")
            return
        c = self._camps[row]
        try:
            rows = json.loads(c.get("report_json") or "[]")
        except Exception:
            rows = []
        failed = [r for r in rows if r.get("status") in ("failed", "skipped")]
        if not failed:
            QMessageBox.information(self, "", "אין נכשלים לשלוח שוב.")
            return
        # v3.46: ההודעה המקורית נשלחת כמו שהיא — הטיוטה שבשדות לא נדרסת
        recs = {}
        targets = []
        me = sync.device_name() or ""
        for r in failed:
            # v3.44: הכרטיס לפי guid (יציב בין המחשבים). rec_id הוא מזהה *מקומי* —
            # בדוח שהגיע מהמחשב השני אותו מספר = אדם אחר ⇒ רק כשהשליחה הייתה שלנו.
            rec = None
            if r.get("guid"):
                rec = db.get_recipient_by_guid(r["guid"])
            elif r.get("rec_id") is not None and (c.get("device") or "") == me:
                rec = db.get_recipient(r["rec_id"])
            if rec:
                rec = dict(rec)
                recs[rec["id"]] = rec
                targets.append({"rec_id": rec["id"], "guid": rec.get("guid", ""),
                                "name": rec["full_name"], "email": (rec.get("email") or "").strip(),
                                "ok": mailer.valid_email(rec.get("email") or ""), "reason": ""})
            else:
                targets.append({"rec_id": None, "guid": "", "name": r.get("name", ""),
                                "email": r.get("email", ""), "ok": mailer.valid_email(r.get("email", "")),
                                "reason": "", "external": True})
        dropped = [t["name"] for t in targets if not t["ok"]]
        targets = [t for t in targets if t["ok"]]
        if not targets:
            QMessageBox.information(self, "", "לנכשלים אין כתובת מייל תקינה בכרטיס.")
            return
        if dropped:
            QMessageBox.information(
                self, "", f"{len(dropped)} מהנכשלים בלי כתובת מייל תקינה בכרטיס — לא יישלח להם:\n"
                + "\n".join(dropped[:15]) + ("\n…" if len(dropped) > 15 else ""))
        # v3.47: הקובץ המצורף ומצב הכותרת של השליחה *המקורית* — לא של הטיוטה שבמסך.
        # הנתיב מקומי: במחשב השני (או אחרי מחיקה) הקובץ חסר → שואלים, לא שולחים בשקט בלעדיו.
        attachment = (c.get("attachment") or "").strip()
        if attachment and not os.path.exists(attachment):
            if QMessageBox.question(
                    self, "הקובץ המקורי חסר",
                    f"השליחה המקורית כללה קובץ מצורף (\"{os.path.basename(attachment)}\") "
                    "שלא נמצא במחשב הזה.\nלשלוח שוב לנכשלים בלי הקובץ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            attachment = ""
        self._recs.update(recs)
        self._send(targets, audience=f"שליחה חוזרת לנכשלים ({c.get('audience', '')})",
                   subject=c.get("subject", ""), body=c.get("body", ""),
                   attachment=attachment, with_header=int(c.get("with_header", 1) or 0))

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
import json
import os

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QTextBrowser, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QDialog, QListWidget, QListWidgetItem, QMessageBox, QFileDialog,
    QInputDialog, QProgressBar, QAbstractItemView, QSizePolicy, QFrame, QButtonGroup)

import database as db
from utils import email_utils, mailer, sync, timefmt
from utils.ui import busy_cursor, enable_touch_scroll
from tabs.group_update import (_BG, _CARD_QSS, _CHIP_QSS, _CHIP_GREEN, _CHIP_AMBER, _LBL,
                               _BTN_PRIMARY, _BTN_GHOST, _BTN_PRINT, _BTN_ACCENT,
                               _BTN_DANGER, _step_badge, _step_card, _metric, _set_metric)

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


def _logo_path() -> str:
    if os.path.exists(db.USER_LOGO_PATH):
        return db.USER_LOGO_PATH
    try:
        from utils.print_view import _resource_path
        p = _resource_path("org_logo.png")
        return p if os.path.exists(p) else ""
    except Exception:
        return ""


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
        head = QLabel(f"<b>{camp.get('subject','')}</b> · {timefmt.datetime_str(camp.get('sent_at',''))}"
                      f" · {camp.get('audience','')} · נשלחו {camp.get('sent',0)} · נכשלו {camp.get('failed',0)}")
        head.setWordWrap(True)
        lay.addWidget(head)
        body = QTextBrowser()
        body.setMaximumHeight(120)
        body.setPlainText(camp.get("body") or "")
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
        self.chip_with_mail = QLabel("")
        self.chip_with_mail.setStyleSheet(_CHIP_QSS)
        head.addWidget(self.chip_with_mail)
        self.chip_account = QLabel("")
        self.chip_account.setStyleSheet(_CHIP_GREEN)
        head.addWidget(self.chip_account)
        self.btn_settings = QPushButton("פתח הגדרות")
        self.btn_settings.setStyleSheet(_BTN_GHOST)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._goto_settings)
        head.addWidget(self.btn_settings)
        lay.addLayout(head)

        # ① למי
        card, c_lay, c_head = _step_card("1", "למי שולחים?", "הרשימה נבנית מהכרטיסים — רק מי שיש לו מייל יקבל")
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
        self.btn_show_bad = QPushButton("מי בלי מייל?")
        self.btn_show_bad.setStyleSheet(_BTN_LINK)
        self.btn_show_bad.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_bad.clicked.connect(self._show_bad)
        mrow.addWidget(self.btn_show_bad)
        mrow.addStretch()
        c_lay.addLayout(mrow)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["שם", "מייל", "מצב", ""])
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
        lay.addWidget(card)

        # ② ההודעה
        card, c_lay, c_head = _step_card("2", "מה כותבים?", "אפשר לשמור כתבנית לפעם הבאה")
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
        self.lbl_preview_title = self._lbl("כך זה ייראה")
        right.addWidget(self.lbl_preview_title)
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
        self.hist = QTableWidget(0, 6)
        self.hist.setHorizontalHeaderLabels(["תאריך", "נושא", "למי", "נשלחו", "נכשלו", ""])
        self.hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist.verticalHeader().setVisible(False)
        hh = self.hist.horizontalHeader()
        for i in (0, 2, 3, 4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.hist.setColumnWidth(5, 230)
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
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_step_badge("3"))
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color:#334155; font-size:13.5px; " + _LBL)
        self.lbl_summary.setWordWrap(True)
        row.addWidget(self.lbl_summary, 1)
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
            self.chip_account.setText("✓ Google: " + (email_utils.sender_email() or "מחובר"))
            self.chip_account.setStyleSheet(_CHIP_GREEN)
        elif email_utils.smtp_configured():
            self.chip_account.setText("✓ שולח מ: " + email_utils.sender_email())
            self.chip_account.setStyleSheet(_CHIP_GREEN)
        else:
            self.chip_account.setText("●  עוד לא חובר חשבון מייל")
            self.chip_account.setStyleSheet(_CHIP_AMBER)
        self.btn_settings.setVisible(not email_utils.is_configured())
        n = sum(1 for r in db.get_all_recipients("פעיל") if (r.get("email") or "").strip())
        self.chip_with_mail.setText(f"{n} מקבלים עם כתובת מייל")

    def _set_mode(self, mode):
        self._mode = mode
        self._removed.clear()
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
            st = QTableWidgetItem("✓ יקבל" if tg["ok"] else "⚠ " + tg["reason"])
            st.setForeground(Qt.GlobalColor.darkGreen if tg["ok"] else Qt.GlobalColor.darkYellow)
            t.setItem(i, 2, st)
            b = QPushButton("הסר")
            b.setStyleSheet(_BTN_LINK)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c, tg=tg: self._remove_target(tg))
            t.setCellWidget(i, 3, b)
        rows = min(len(self._targets), _MAX_TABLE_ROWS)
        h = t.horizontalHeader().height() + rows * (t.verticalHeader().defaultSectionSize()) + 6
        t.setFixedHeight(max(h, 60))

    def _update_metrics(self):
        ok = sum(1 for t in self._targets if t["ok"])
        _set_metric(self.m_total, len(self._targets))
        _set_metric(self.m_ok, ok)
        _set_metric(self.m_bad, len(self._targets) - ok)
        self.btn_show_bad.setVisible(len(self._targets) - ok > 0)
        sender = email_utils.sender_email()
        if not email_utils.is_configured():
            self.lbl_summary.setText("כדי לשלוח צריך קודם לחבר חשבון מייל בהגדרות (\"התחבר עם Google\").")
        elif ok == 0:
            self.lbl_summary.setText("אין אף נמען עם כתובת מייל ברשימה.")
        else:
            self.lbl_summary.setText(
                f"יישלחו <b>{ok}</b> מיילים אישיים (כל אחד רואה רק את עצמו) מהחשבון <b>{sender}</b>")
        sending = self._worker is not None
        testing = getattr(self, "_test_worker", None) is not None
        self.btn_send.setEnabled(email_utils.is_configured() and ok > 0 and not sending)
        self.btn_test.setEnabled(email_utils.is_configured() and not sending and not testing)

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
        first = next((t for t in self._targets if t["ok"]), None)
        rec = self._recs.get(first["rec_id"]) if first and first.get("rec_id") is not None else None
        ctx = dict(self._ctx(), fallback_name=first["name"] if first else "ישראל ישראלי")
        subj = mailer.render(self.subject.text(), rec, ctx)
        logo_url = QUrl.fromLocalFile(_logo_path()).toString() if _logo_path() else ""
        body = mailer.html_body(mailer.render(self.body.toPlainText(), rec, ctx),
                                self.chk_header.isChecked()).replace("src='cid:logo'", f"src='{logo_url}'")
        who = first["name"] if first else "נמען לדוגמה"
        self.lbl_preview_title.setText(f"כך זה ייראה אצל {who}")
        self.preview.setHtml(f"<div dir='rtl'><div style='color:#64748b;font-size:12px'>נושא:</div>"
                             f"<div style='font-weight:700;margin-bottom:10px'>{subj}</div>{body}</div>")

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
            self.body.setPlainText(t["body"])

    def _save_template(self):
        if not self.subject.text().strip() and not self.body.toPlainText().strip():
            QMessageBox.information(self, "", "אין מה לשמור — כתוב נושא ותוכן קודם.")
            return
        cur = next((x for x in self._templates if x["guid"] == self._current_tpl_guid), None)
        name, ok = QInputDialog.getText(self, "שמירת תבנית", "שם התבנית:",
                                        text=cur["name"] if cur else self.subject.text()[:40])
        if not ok or not name.strip():
            return
        guid = cur["guid"] if cur and cur["name"] == name.strip() else ""
        self._current_tpl_guid = db.upsert_mail_template(
            name.strip(), self.subject.text(), self.body.toPlainText(), guid=guid)
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
            if os.path.getsize(path) > 20 * 1024 * 1024:
                QMessageBox.warning(self, "", "הקובץ גדול מדי (Gmail מגביל ל-25MB).")
                return
            self._set_attachment(path)

    def _set_attachment(self, path):
        self._attachment = path or ""
        self.lbl_attach.setText(os.path.basename(path) if path else "")
        self.btn_attach_clear.setVisible(bool(path))

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

    def _validate_message(self) -> bool:
        if not self.subject.text().strip():
            QMessageBox.warning(self, "", "חסר נושא להודעה.")
            return False
        if not self.body.toPlainText().strip():
            QMessageBox.warning(self, "", "ההודעה ריקה.")
            return False
        if not email_utils.is_configured():
            QMessageBox.warning(self, "", "חבר קודם חשבון מייל בהגדרות.")
            return False
        return True

    def _send_test(self):
        if not self._validate_message():
            return
        me = email_utils.sender_email()
        first = next((t for t in self._targets if t["ok"]), None)
        rec = self._recs.get(first["rec_id"]) if first and first.get("rec_id") is not None else None
        ctx = dict(self._ctx(), fallback_name=first["name"] if first else "ישראל ישראלי")
        subj = "[בדיקה] " + mailer.render(self.subject.text(), rec, ctx)
        html = mailer.html_body(mailer.render(self.body.toPlainText(), rec, ctx),
                                self.chk_header.isChecked())
        attach = self._attachment or None
        logo = _logo_path() if self.chk_header.isChecked() else None
        # ברקע — חיבור לשרת (במיוחד מאחורי נטפרי) יכול לקחת דקות; המסך לא קופא
        self.btn_test.setEnabled(False)
        self.btn_test.setText("שולח בדיקה…")
        self._test_worker = _BgWorker(
            lambda: email_utils.send_email(me, subj, html, attachment_path=attach,
                                           inline_logo_path=logo), self)
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

    def _send(self, targets=None, audience=None):
        if self._worker is not None or not self._validate_message():
            return
        targets = targets if targets is not None else [t for t in self._targets if t["ok"]]
        if not targets:
            return
        audience = audience or self._audience_text()
        msg = (f"לשלוח את ההודעה <b>\"{self.subject.text().strip()}\"</b><br>"
               f"ל-<b>{len(targets)}</b> נמענים ({audience})<br>"
               f"מהחשבון <b>{email_utils.sender_email()}</b>?"
               + ("<br>עם קובץ מצורף: " + os.path.basename(self._attachment) if self._attachment else ""))
        if QMessageBox.question(self, "אישור שליחה", msg) != QMessageBox.StandardButton.Yes:
            return
        self._active_guid = db.add_mail_campaign(
            self.subject.text().strip(), self.body.toPlainText(), audience,
            email_utils.sender_email(), len(targets), device=sync.device_name() or "")
        self._worker = _SendWorker(targets, self.subject.text().strip(), self.body.toPlainText(),
                                   self._ctx(), self._attachment or None,
                                   self.chk_header.isChecked(), dict(self._recs), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_rows.connect(self._on_finished)
        self.prog.setRange(0, len(targets))
        self.prog.setValue(0)
        self.lbl_prog.setText(f"שולח… 0 מתוך {len(targets)}")
        self.prog_box.show()
        self._sent_n = self._failed_n = 0
        self._update_metrics()
        self._worker.start()

    def _on_progress(self, done, total, row):
        if row.get("status") == "sent":
            self._sent_n += 1
        elif row.get("status") == "failed":
            self._failed_n += 1
        self.prog.setValue(done)
        self.lbl_prog.setText(f"שולח… {done} מתוך {total} · נשלחו {self._sent_n} · נכשלו {self._failed_n}")

    def _on_finished(self, rows):
        guid, self._active_guid = self._active_guid, ""
        self._worker = None
        self.prog_box.hide()
        if isinstance(rows, Exception):
            db.update_mail_campaign(guid, 0, 0, "failed", json.dumps([], ensure_ascii=False))
            QMessageBox.warning(self, "השליחה נכשלה", str(rows))
        else:
            sent, failed = mailer.summarize(rows)
            stopped = any(r.get("status") == "skipped" for r in rows)
            db.update_mail_campaign(guid, sent, failed, "stopped" if stopped else "done",
                                    json.dumps(rows, ensure_ascii=False))
            txt = f"נשלחו {sent} מיילים בהצלחה."
            if failed:
                txt += f"\n{failed} נכשלו — ראה \"פרטים\" בהיסטוריה, ואפשר \"שלח שוב לנכשלים\"."
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

    def _close_stale_campaigns(self):
        """שליחה שנקטעה (התוכנה נסגרה באמצע) — לא להשאיר "בתהליך" לנצח."""
        me = sync.device_name() or ""
        for c in db.get_mail_campaigns():
            if c.get("status") == "sending" and (c.get("device") or "") == me \
                    and c.get("guid") != self._active_guid:
                db.update_mail_campaign(c["guid"], c.get("sent", 0), c.get("failed", 0),
                                        "interrupted", c.get("report_json") or "")

    # ── history ───────────────────────────────────────────────────────────────

    _STATUS_HE = {"sending": "בתהליך…", "done": "הושלם", "stopped": "נעצר",
                  "interrupted": "נקטע", "failed": "נכשל"}

    def _refresh_history(self):
        self._camps = db.get_mail_campaigns(limit=200)
        h = self.hist
        h.setRowCount(0)
        h.setRowCount(len(self._camps))
        for i, c in enumerate(self._camps):
            h.setItem(i, 0, QTableWidgetItem(timefmt.datetime_str(c.get("sent_at", ""))))
            h.setItem(i, 1, QTableWidgetItem(c.get("subject", "")))
            h.setItem(i, 2, QTableWidgetItem(c.get("audience", "")))
            st = self._STATUS_HE.get(c.get("status", ""), "")
            h.setItem(i, 3, QTableWidgetItem(f"{c.get('sent', 0)}" + (f"  ({st})" if st and st != "הושלם" else "")))
            f = QTableWidgetItem(str(c.get("failed", 0)))
            if c.get("failed"):
                f.setForeground(Qt.GlobalColor.red)
            h.setItem(i, 4, f)
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(4)
            b1 = QPushButton("פרטים")
            b1.setStyleSheet(_BTN_LINK)
            b1.clicked.connect(lambda _c, r=i: self._show_details(r))
            wl.addWidget(b1)
            if c.get("failed"):
                b2 = QPushButton("שלח שוב לנכשלים")
                b2.setStyleSheet(_BTN_LINK)
                b2.clicked.connect(lambda _c, r=i: self._resend_failed(r))
                wl.addWidget(b2)
            wl.addStretch()
            h.setCellWidget(i, 5, w)
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
        c = self._camps[row]
        try:
            rows = json.loads(c.get("report_json") or "[]")
        except Exception:
            rows = []
        failed = [r for r in rows if r.get("status") in ("failed", "skipped")]
        if not failed:
            QMessageBox.information(self, "", "אין נכשלים לשלוח שוב.")
            return
        # ההודעה המקורית חוזרת לשדות (אפשר לתקן לפני השליחה)
        self.subject.setText(c.get("subject", ""))
        self.body.setPlainText(c.get("body", ""))
        recs = {}
        targets = []
        for r in failed:
            rec = db.get_recipient(r["rec_id"]) if r.get("rec_id") is not None else None
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
        targets = [t for t in targets if t["ok"]]
        if not targets:
            QMessageBox.information(self, "", "לנכשלים אין כתובת מייל תקינה בכרטיס.")
            return
        self._recs.update(recs)
        self._send(targets, audience=f"שליחה חוזרת לנכשלים ({c.get('audience', '')})")

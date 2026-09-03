import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QMessageBox, QFileDialog, QInputDialog, QLineEdit,
    QProgressDialog, QApplication, QSpinBox, QScrollArea, QDoubleSpinBox,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QAbstractSpinBox, QCheckBox
)

import database as db
from utils.backup import auto_backup, restore_from_backup
from utils.ui import busy_cursor, ALIGN_RIGHT, section_header, line_icon, enable_touch_scroll
from utils import updater
from utils import email_utils
from utils import sync
from version import APP_VERSION
import json

# ── v3.01 design language — shared with "חלוקה ורישום" / "צינתוקים" ──────────
from PyQt6.QtWidgets import QSizePolicy
from tabs.group_update import (_BG, _CARD_QSS, _CHIP_QSS, _CHIP_GREEN, _BTN_PRIMARY,
                               _BTN_GHOST, _BTN_DANGER, _BTN_ACCENT)

_LBL = "background:transparent; border:none;"
_CHIP_AMBER = ("QLabel{background:#fdf0d5; color:#92600a; border:none; border-radius:16px;"
               " padding:5px 13px; font-size:12.5px; font-weight:700;}")
_CHIP_RED = ("QLabel{background:#fee2e2; color:#b91c1c; border:none; border-radius:16px;"
             " padding:5px 13px; font-size:12.5px; font-weight:700;}")
_DESC = "color:#64748b; font-size:12.5px; " + _LBL
_FLABEL = "color:#475569; font-size:12.5px; font-weight:700; " + _LBL
_NOTE_AMBER = ("QLabel{color:#92400e; font-size:12px; font-weight:600; background:#fffbeb;"
               " border:1px solid #fde68a; border-radius:8px; padding:7px 10px;}")
_CARD_DANGER_QSS = ("QFrame#ui-card{background:#fffafa; border:1.5px solid #fca5a5;"
                    " border-radius:12px;}")
_BTN_SMALL = ("QPushButton{min-height:30px; font-size:12.5px; padding:0 12px;}")
_INPUT_H = 36


def _section(text: str) -> QHBoxLayout:
    """A short muted heading with a hairline that runs to the far edge —
    groups two related cards under one label."""
    h = QHBoxLayout()
    h.setSpacing(10)
    h.setContentsMargins(4, 8, 4, 0)
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#0f766e; font-size:12.5px; font-weight:800; letter-spacing:0.5px; " + _LBL)
    h.addWidget(lbl)
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background:#d9e2ec; border:none;")
    h.addWidget(line, 1)
    return h


def _row() -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(12)
    return h


def _card(title: str, icon_name: str = None, hint: str = "", danger: bool = False):
    """A white rounded card with icon + title + muted hint. Returns
    (frame, body_layout, header_layout)."""
    frame = QFrame()
    frame.setObjectName("ui-card")
    frame.setStyleSheet(_CARD_DANGER_QSS if danger else _CARD_QSS)
    frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(18, 12, 18, 12)
    outer.setSpacing(9)
    head = QHBoxLayout()
    head.setSpacing(9)
    color = "#dc2626" if danger else "#0f9d78"
    if icon_name:
        ic = QLabel()
        ic.setPixmap(line_icon(icon_name, 20, color))
        ic.setStyleSheet(_LBL)
        head.addWidget(ic)
    tl = QLabel(title)
    tl.setStyleSheet(f"color:{'#b91c1c' if danger else '#064e3b'}; font-size:15px; font-weight:800; " + _LBL)
    head.addWidget(tl)
    if hint:
        hl = QLabel(hint)
        hl.setStyleSheet("color:#94a3b8; font-size:12px; " + _LBL)
        head.addWidget(hl)
    head.addStretch()
    outer.addLayout(head)
    return frame, outer, head


def _place(row: QHBoxLayout, card: QFrame, body: QVBoxLayout):
    """Put a card into a two-card row. Both cards of a row share the row's
    height (equal, tidy edges); each card's content packs to its top."""
    body.addStretch()
    row.addWidget(card, 1)


def _desc(text: str) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setStyleSheet(_DESC)
    return l


def _hint(text: str, color: str = "#94a3b8") -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setStyleSheet(f"color:{color}; font-size:11.5px; " + _LBL)
    return l


def _flabel(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_FLABEL)
    return l


def _btn(text: str, style: str, slot, tip: str = None, small: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(style + (_BTN_SMALL if small else ""))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    b.clicked.connect(slot)
    return b


def _btn_row(*widgets) -> QHBoxLayout:
    """Buttons (and an optional trailing status label) in one line, packed to the
    start side of the card."""
    h = QHBoxLayout()
    h.setSpacing(8)
    h.setContentsMargins(0, 4, 0, 0)
    for w in widgets:
        if isinstance(w, QLabel):
            h.addWidget(w, 1)
        else:
            h.addWidget(w)
    h.addStretch()
    return h


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    f.setHorizontalSpacing(12)
    f.setVerticalSpacing(7)
    f.setContentsMargins(0, 0, 0, 0)
    return f


def _form_row(form: QFormLayout, label: str, widget):
    widget.setMinimumHeight(_INPUT_H)
    form.addRow(_flabel(label), widget)



class _UpdateWorker(QThread):
    """Runs the network check / download off the UI thread."""
    checked = pyqtSignal(object)      # dict | None | Exception
    progress = pyqtSignal(int)
    finished_dl = pyqtSignal(object)  # path str | Exception

    def __init__(self, mode, url=None, dest=None):
        super().__init__()
        self.mode = mode
        self.url = url
        self.dest = dest
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self.mode == "check":
                self.checked.emit(updater.check_latest())
            else:
                updater.download(self.url, self.dest,
                                 progress_cb=lambda p: self.progress.emit(p),
                                 cancel_cb=lambda: self._cancel)
                self.finished_dl.emit(self.dest)
        except Exception as e:
            (self.checked if self.mode == "check" else self.finished_dl).emit(e)


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._build_ui()

    def _build_ui(self):
        """v3.01 — the settings screen rebuilt in the design language of the
        'חלוקה ורישום' / 'צינתוקים' screens: a soft page surface, a title row
        with live status chips, and white rounded cards grouped under short
        section headings (two cards per row). Every attribute the logic uses
        (spins, labels, buttons) keeps its name."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        surface = QWidget()
        surface.setObjectName("st-surface")
        surface.setStyleSheet(f"QWidget#st-surface{{background:{_BG};}}"
                              "QWidget#st-surface QLabel{background:transparent; border:none;}")
        root.addWidget(surface, 1)
        s_lay = QVBoxLayout(surface)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        enable_touch_scroll(scroll)   # finger-drag scrolling on a touch screen
        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 12, 20, 16)
        s_lay.addWidget(scroll, 1)

        from PyQt6.QtCore import QTimer

        # ── Header: title · subtitle · live status chips ──────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("הגדרות")
        title.setObjectName("title")
        title.setStyleSheet("color:#064e3b; font-size:22px; font-weight:800; " + _LBL)
        head.addWidget(title)
        sub = QLabel("התאמה אישית, גיבויים, חיבורים ועבודה משני מחשבים")
        sub.setStyleSheet("color:#64748b; font-size:13px; " + _LBL)
        head.addWidget(sub)
        head.addStretch()
        self.chip_version = QLabel(f"גרסה {APP_VERSION}")
        self.chip_version.setStyleSheet(_CHIP_QSS)
        head.addWidget(self.chip_version)
        self.chip_sync = QLabel("")
        head.addWidget(self.chip_sync)
        self.chip_yemot = QLabel("")
        head.addWidget(self.chip_yemot)
        self.chip_mail = QLabel("")
        head.addWidget(self.chip_mail)
        lay.addLayout(head)

        # ═════════════════════════ כללי ומראה ═════════════════════════
        lay.addLayout(_section("כללי ומראה"))
        row = _row(); lay.addLayout(row)

        # ── כללי: text size · no-show alerts · password ──
        card, body, _h = _card("כללי", "sliders", "גודל טקסט, התראות וסיסמה")
        g = QGridLayout()
        g.setHorizontalSpacing(12); g.setVerticalSpacing(8)
        g.setColumnStretch(2, 1)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(80, 150)
        self.font_spin.setSingleStep(5)
        self.font_spin.setSuffix(" %")
        self.font_spin.setFixedWidth(110)
        self.font_spin.setMinimumHeight(_INPUT_H)
        self.font_spin.setValue(db.get_ui_font_percent())
        self.font_spin.setToolTip("מגדיל או מקטין את הטקסט בכל התוכנה מיידית "
                                  "(100% = הגודל הרגיל)")
        self._font_apply_timer = QTimer(self)
        self._font_apply_timer.setSingleShot(True)
        self._font_apply_timer.setInterval(250)
        self._font_apply_timer.timeout.connect(self._apply_font_percent)
        self.font_spin.valueChanged.connect(lambda *_: self._font_apply_timer.start())
        g.addWidget(_flabel("גודל הטקסט בתוכנה"), 0, 0)
        g.addWidget(self.font_spin, 0, 1)
        g.addWidget(_hint("משתנה מיד בכל המסכים"), 0, 2)

        self.no_show_spin = QSpinBox()
        self.no_show_spin.setRange(0, 20)
        self.no_show_spin.setSuffix(" פעמים ברצף")
        self.no_show_spin.setFixedWidth(160)
        self.no_show_spin.setMinimumHeight(_INPUT_H)
        try:
            self.no_show_spin.setValue(db.get_no_show_threshold())
        except Exception:
            self.no_show_spin.setValue(3)
        self.no_show_spin.setToolTip(
            "מי שנרשם לו \"לא הגיע\" כך-וכך פעמים ברצף יסומן באדום ברשימת החלוקה "
            "ובכרטיס המקבל. 0 = בלי התראות.")
        self.no_show_spin.valueChanged.connect(
            lambda v: db.set_setting("no_show_alert_threshold", str(v)))
        g.addWidget(_flabel("התראה על מי שלא הגיע"), 1, 0)
        g.addWidget(self.no_show_spin, 1, 1)
        g.addWidget(_hint("0 = בלי התראות"), 1, 2)

        self.lbl_password = QLabel("••••")
        self.lbl_password.setStyleSheet("color:#475569; letter-spacing:2px; font-size:15px; " + _LBL)
        g.addWidget(_flabel("סיסמת כניסה"), 2, 0)
        g.addWidget(self.lbl_password, 2, 1)
        btn_pwd = _btn("שנה סיסמה…", _BTN_GHOST, self._change_password,
                       "שנה את סיסמת הכניסה לאפליקציה", small=True)
        g.addWidget(btn_pwd, 2, 2, alignment=Qt.AlignmentFlag.AlignLeft)
        body.addLayout(g)
        _place(row, card, body)

        # ── שם הארגון ולוגו ──
        card, body, _h = _card("שם הארגון ולוגו", "building", "הכיתוב והלוגו שבראש התוכנה")
        body.addWidget(_desc("מתאים את התוכנה לכל קופת צדקה — הכותרת מופיעה בסרגל העליון, "
                             "הלוגו גם בהדפסות."))
        form = _form()
        self.org_title = QLineEdit()
        self.org_title.setPlaceholderText("מנהל חלוקה")
        self.org_title.setAlignment(ALIGN_RIGHT)
        self.org_subtitle = QLineEdit()
        self.org_subtitle.setPlaceholderText("שם הקופה · יישוב")
        self.org_subtitle.setAlignment(ALIGN_RIGHT)
        _form_row(form, "כותרת", self.org_title)
        _form_row(form, "כותרת משנה", self.org_subtitle)
        body.addLayout(form)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_row.addWidget(_flabel("לוגו"))
        self.lbl_logo_status = QLabel("")
        self.lbl_logo_status.setStyleSheet(_CHIP_QSS)
        logo_row.addWidget(self.lbl_logo_status)
        logo_row.addStretch()
        logo_row.addWidget(_btn("החלף לוגו…", _BTN_GHOST, self._choose_logo, small=True))
        self.btn_logo_reset = _btn("אפס", _BTN_GHOST, self._reset_logo, small=True)
        logo_row.addWidget(self.btn_logo_reset)
        body.addLayout(logo_row)
        body.addLayout(_btn_row(_btn("שמור", _BTN_PRIMARY, self._save_branding)))
        _place(row, card, body)

        # ═════════════════════════ נתונים וגיבוי ═════════════════════════
        lay.addLayout(_section("נתונים וגיבוי"))
        row = _row(); lay.addLayout(row)

        # ── גיבויים ──
        card, body, _h = _card("גיבויים", "backup", "צילום מלא של כל הנתונים בקובץ אחד")
        body.addWidget(_desc(
            "התוכנה מגבה לבד בכל פתיחה ולפני כל פעולה מסוכנת. אם המחשב נשבר, הנתונים "
            "נמחקו בטעות או עוברים למחשב חדש — משחזרים הכול מגיבוי. אפשר גם לשמור עותק "
            "לתיקייה שתבחר (כונן חיצוני / דיסק-און-קי)."))
        g = QGridLayout()
        g.setHorizontalSpacing(12); g.setVerticalSpacing(6)
        g.setColumnStretch(1, 1)
        self.lbl_backup_folder = QLabel("")
        self.lbl_backup_folder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_backup_folder.setWordWrap(True)
        self.lbl_last_backup = QLabel("")
        g.addWidget(_flabel("תיקיית גיבוי"), 0, 0, alignment=Qt.AlignmentFlag.AlignTop)
        g.addWidget(self.lbl_backup_folder, 0, 1)
        g.addWidget(_flabel("גיבוי אחרון"), 1, 0)
        g.addWidget(self.lbl_last_backup, 1, 1)
        body.addLayout(g)
        self.btn_backup_now = _btn("גבה עכשיו", _BTN_PRIMARY, self._backup_now,
                                   "שמור עכשיו צילום מלא של כל הנתונים לתיקייה שנבחרה")
        body.addLayout(_btn_row(
            self.btn_backup_now,
            _btn("שחזר מגיבוי קודם…", _BTN_GHOST, self._open_backup_list,
                 "רשימת כל הגיבויים השמורים — שחזור בלחיצה אחת"),
            _btn("שחזר מקובץ…", _BTN_GHOST, self._restore_backup,
                 "החזר את כל הנתונים מקובץ גיבוי .db שתבחר ידנית"),
            _btn("בחר תיקיית גיבוי…", _BTN_GHOST, self._choose_backup_folder,
                 "בחר לאן לשמור עותק גיבוי נוסף (למשל כונן חיצוני)")))
        _place(row, card, body)

        # ── תיקיות ייצוא (#5e1jc) ──
        from utils.excel_utils import EXPORT_KINDS
        card, body, _h = _card("תיקיות ייצוא", "download", "לאן נשמרים קבצי האקסל וה-PDF")
        body.addWidget(_desc("אפשר לבחור תיקייה נפרדת לכל סוג — למשל תיקייה קבועה לכל "
                             "החלוקות. ברירת המחדל: תיקיית ההורדות."))
        self._export_path_lbls = {}
        g = QGridLayout()
        g.setHorizontalSpacing(10); g.setVerticalSpacing(6)
        g.setColumnStretch(1, 1)
        for i, (kind, label) in enumerate(EXPORT_KINDS):
            g.addWidget(_flabel(label), i, 0)
            path_lbl = QLabel("")
            path_lbl.setWordWrap(True)
            self._export_path_lbls[kind] = path_lbl
            g.addWidget(path_lbl, i, 1)
            g.addWidget(_btn("בחר…", _BTN_GHOST,
                             lambda _=False, k=kind: self._choose_export_dir(k), small=True), i, 2)
            g.addWidget(_btn("ברירת מחדל", _BTN_GHOST,
                             lambda _=False, k=kind: self._reset_export_dir(k),
                             "החזר לתיקיית ההורדות", small=True), i, 3)
        body.addLayout(g)
        _place(row, card, body)
        self._refresh_export_labels()

        # ═════════════════════════ חיבורים ═════════════════════════
        lay.addLayout(_section("חיבורים"))
        row = _row(); lay.addLayout(row)

        # ── מייל למתנדבים ──
        card, body, _h = _card("מייל למתנדבים", "mail", "שליחת רשימה למתנדב וקליטת התוצאות")
        body.addWidget(_desc(
            "משמש לשליחת רשימת חלוקה למתנדב ולקליטה אוטומטית של התוצאות שהוא מחזיר "
            "במייל (מסך \"חלוקה ורישום\"). דורש סיסמת אפליקציה של Gmail."))
        mail_links = QLabel(
            "הגדרה חד-פעמית ב-Gmail (לפי הסדר):<br>"
            "1. <a href=\"https://authenticator.cc/\">התקנת אפליקציית מאמת (Authenticator)</a><br>"
            "2. <a href=\"https://myaccount.google.com/signinoptions/two-step-verification?hl=he\">"
            "הפעלת אימות דו-שלבי</a> "
            "<span style=\"color:#b45309;\">— בעת ההפעלה הורידו את קודי הגיבוי ושמרו במקום בטוח</span><br>"
            "3. <a href=\"https://myaccount.google.com/apppasswords\">הפקת סיסמת אפליקציה</a>")
        mail_links.setTextFormat(Qt.TextFormat.RichText)
        mail_links.setOpenExternalLinks(True)
        mail_links.setWordWrap(True)
        mail_links.setStyleSheet("color:#334155; font-size:12px; " + _LBL)
        body.addWidget(mail_links)
        mail_warn = QLabel(
            "⚠ אל תשנה הגדרות אבטחה בחשבון Google (אימות דו-שלבי / סיסמאות אפליקציה) "
            "בלי להתייעץ עם מישהו שמבין בכך — שינוי שגוי עלול לחסום את הכניסה לחשבון.")
        mail_warn.setWordWrap(True)
        mail_warn.setStyleSheet(_NOTE_AMBER)
        body.addWidget(mail_warn)

        form = _form()
        self.mail_email = QLineEdit()
        self.mail_email.setPlaceholderText("your@gmail.com")
        self.mail_email.setAlignment(ALIGN_RIGHT)
        self.mail_password = QLineEdit()
        self.mail_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.mail_password.setPlaceholderText("סיסמת אפליקציה")
        self.mail_password.setAlignment(ALIGN_RIGHT)
        self.mail_file_pw = QLineEdit()
        self.mail_file_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.mail_file_pw.setPlaceholderText("ריק = הקובץ לא מוגן")
        self.mail_file_pw.setAlignment(ALIGN_RIGHT)
        self.mail_file_pw.setToolTip(
            "הקובץ המצורף למתנדב יינעל בסיסמה זו (צריך אותה כדי לפתוח ב-Excel). "
            "הסיסמה לא נכתבת במייל — מסרו אותה למתנדב פעם אחת בעל-פה / בווטסאפ.")
        _form_row(form, "כתובת שולח", self.mail_email)
        _form_row(form, "סיסמת אפליקציה", self.mail_password)
        _form_row(form, "סיסמה לקובץ המתנדב", self.mail_file_pw)
        body.addLayout(form)
        body.addWidget(_hint("סיסמת הקובץ נמסרת למתנדב פעם אחת בעל-פה; השאר ריק כדי לא להגן על הקובץ."))
        self.lbl_mail_status = QLabel("")
        self.lbl_mail_status.setWordWrap(True)
        body.addLayout(_btn_row(
            _btn("שמור", _BTN_PRIMARY, self._save_mail_settings),
            _btn("שלח מייל בדיקה", _BTN_GHOST, self._test_mail_settings),
            self.lbl_mail_status))
        _place(row, card, body)

        # ── צינתוקים — ימות המשיח (v2.81) ──
        card, body, _h = _card("צינתוקים (ימות המשיח)", "phone", "החיבור למערכת הטלפונית")
        body.addWidget(_desc(
            "לשליחת הודעה קולית לזכאי החלוקה ממסך \"צינתוקים\". הזן את מספר המערכת "
            "(077…) ואת הסיסמה של ימות ולחץ \"בדוק חיבור\". אם מופעל אימות דו-שלבי — "
            "צור \"מפתח API\" בממשק ימות (חומת אש) והדבק אותו בשדה הסיסמה."))
        form = _form()
        self.ym_system = QLineEdit()
        self.ym_system.setPlaceholderText("למשל 0773137770")
        self.ym_system.setAlignment(ALIGN_RIGHT)
        self.ym_system.setText(db.get_setting("yemot_system") or "")
        self.ym_password = QLineEdit()
        self.ym_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ym_password.setPlaceholderText("הסיסמה של המערכת בימות")
        self.ym_password.setAlignment(ALIGN_RIGHT)
        self.ym_password.setText(db.get_setting("yemot_password") or "")
        self.ym_caller = QLineEdit()
        self.ym_caller.setPlaceholderText("048691834")
        self.ym_caller.setAlignment(ALIGN_RIGHT)
        self.ym_caller.setToolTip(
            "המספר שהזכאים רואים כשהמערכת מחייגת אליהם. מספר 04 עובר בפלאפונים "
            "כשרים; אם משאירים ריק — נשלח מ-048691834.")
        self.ym_caller.setText(db.get_setting("yemot_caller_id") or "")
        self.ym_gemini_key = QLineEdit()
        self.ym_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ym_gemini_key.setPlaceholderText("לקול המשופר ב\"צור הקלטה מטקסט\" (לא חובה)")
        self.ym_gemini_key.setToolTip(
            "מפתח API חינמי של Google Gemini — משמש רק ליצירת הקלטה מטקסט "
            "בקול המשופר. בלעדיו עדיין עובדים הקולות הרגילים (אברי/הילה).")
        self.ym_gemini_key.setAlignment(ALIGN_RIGHT)
        self.ym_gemini_key.setText(db.get_setting("gemini_api_key") or "")
        _form_row(form, "מספר מערכת", self.ym_system)
        _form_row(form, "סיסמה", self.ym_password)
        _form_row(form, "מספר מזוהה ביוצא", self.ym_caller)
        _form_row(form, "מפתח Gemini", self.ym_gemini_key)
        body.addLayout(form)
        body.addWidget(_hint(
            "\"מספר מזוהה ביוצא\" = המספר שהזכאי רואה כשהצינתוק מגיע. מספר 04 "
            "עובר בפלאפונים כשרים (המספר הראשי 079 חסום); ריק ⇐ 048691834."))
        self.lbl_ym_status = QLabel("")
        self.lbl_ym_status.setWordWrap(True)
        self.lbl_ym_status.setStyleSheet("color:#334155; font-size:12.5px; " + _LBL)
        body.addLayout(_btn_row(
            _btn("שמור", _BTN_PRIMARY, self._save_yemot_settings),
            _btn("בדוק חיבור", _BTN_GHOST, self._test_yemot_connection,
                 "מתחבר לימות המשיח ומוודא שהפרטים נכונים"),
            self.lbl_ym_status))
        # ── סקר אישור הגעה (v3.02): שלוחה 77 בקו — 1 מגיע / 2 לא מגיע / 3 לא יודע ──
        from utils import yemot as _ym
        body.addWidget(_desc(
            f"סקר אישור הגעה: מי שמקבל צינתוק מחייג חזרה לקו, מקיש {_ym.SURVEY_EXT} "
            "ועונה במקש אחד. כאן קובעים מה כל מקש אומר (התוויות מופיעות בתוכנה) "
            "ואת השאלה שהקו מקריא. אחרי שינוי השאלה — \"עדכן את הסקר בקו\"."))
        sform = _form()
        self.ym_ans = {}
        for key in _ym.ANSWER_KEYS:
            w = QLineEdit()
            w.setPlaceholderText(_ym.DEFAULT_ANSWER_LABELS[key])
            w.setAlignment(ALIGN_RIGHT)
            w.setMaxLength(24)
            self.ym_ans[key] = w
            _form_row(sform, f"מקש {key} =", w)
        self.ym_survey_prompt = QLineEdit()
        self.ym_survey_prompt.setPlaceholderText(_ym.DEFAULT_SURVEY_PROMPT)
        self.ym_survey_prompt.setAlignment(ALIGN_RIGHT)
        self.ym_survey_prompt.setToolTip("הטקסט שהקו מקריא למי שמקיש "
                                         f"{_ym.SURVEY_EXT} (הקראה ממוחשבת)")
        _form_row(sform, "השאלה בטלפון", self.ym_survey_prompt)
        body.addLayout(sform)
        self._load_survey_settings()
        self.lbl_survey_status = QLabel("")
        self.lbl_survey_status.setWordWrap(True)
        self.lbl_survey_status.setStyleSheet("color:#334155; font-size:12.5px; " + _LBL)
        body.addLayout(_btn_row(
            _btn("עדכן את הסקר בקו", _BTN_GHOST, self._upload_survey_prompt,
                 "שומר את התוויות והשאלה, ומעלה את השאלה לשלוחת הסקר בקו"),
            self.lbl_survey_status))
        _place(row, card, body)

        # ═════════════════════════ עבודה משני מחשבים ═════════════════════════
        lay.addLayout(_section("עבודה משני מחשבים"))
        row = _row(); lay.addLayout(row)

        # ── סנכרון (v2.61) ──
        card, body, _h = _card("סנכרון בין שני מחשבים", "update", "אותם נתונים בשני מקומות, דרך Google Drive")
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.sync_dot = QLabel("")
        self.sync_dot.setFixedSize(14, 14)
        head_row.addWidget(self.sync_dot)
        self.sync_headline = QLabel("")
        head_row.addWidget(self.sync_headline)
        head_row.addStretch()
        body.addLayout(head_row)
        self.sync_chips_lay = QHBoxLayout()
        self.sync_chips_lay.setSpacing(6)
        self.sync_chips_lay.addStretch()
        body.addLayout(self.sync_chips_lay)
        self.lbl_sync_folder = QLabel("")
        self.lbl_sync_folder.setWordWrap(True)
        self.lbl_sync_folder.setStyleSheet("color:#64748b; font-size:11.5px; " + _LBL)
        body.addWidget(self.lbl_sync_folder)
        body.addWidget(_hint("הסנכרון פועל אוטומטית ברקע כל הזמן — אין צורך ללחוץ על כלום.",
                             color="#0f766e"))
        self.btn_sync_setup = _btn("הגדרת סנכרון…", _BTN_PRIMARY, self._open_sync_setup)
        body.addLayout(_btn_row(self.btn_sync_setup))
        _place(row, card, body)
        self._refresh_sync_status()

        # ── מחשב מנהל (#5rhe9) ──
        card, body, _h = _card("מחשב מנהל ובקרת שינויים", "security", "מי שולט בנתוני האמת")
        mgr_desc = QLabel(
            "אפשר להגדיר מחשב אחד כ<b>מחשב המנהל</b>. במחשב המנהל מופיע <b>יומן "
            "שינויים</b> עם כל שינוי שנקלט מהמחשב השני (מי/מה/מתי) ואפשרות <b>לבטל</b> "
            "אותו ולהחזיר את המצב הקודם. ההגדרה מוגנת בקוד.")
        mgr_desc.setTextFormat(Qt.TextFormat.RichText)
        mgr_desc.setWordWrap(True)
        mgr_desc.setStyleSheet(_DESC)
        body.addWidget(mgr_desc)
        self.lbl_mgr_status = QLabel("")
        self.lbl_mgr_status.setWordWrap(True)
        body.addWidget(self.lbl_mgr_status)
        self.btn_mgr_toggle = _btn("", _BTN_PRIMARY, self._toggle_manager)
        self.btn_mgr_log = _btn("יומן שינויים…", _BTN_GHOST, self._open_manager_log)
        body.addLayout(_btn_row(self.btn_mgr_toggle, self.btn_mgr_log))
        _place(row, card, body)
        self._refresh_manager_status()

        # ═════════════════════════ חישוב החלוקה ═════════════════════════
        lay.addLayout(_section("חישוב החלוקה"))
        row = _row(); lay.addLayout(row)

        # ── משקלי ניקוד ──
        card, body, _h = _card("משקלי ניקוד הצורך", "weights", "מה משפיע על דירוג המקבלים")
        body.addWidget(_desc(
            "המשקל של כל נתון בחישוב 'ניקוד הצורך' שלפיו מדורגים המקבלים. המשקלים הם "
            "אחוזים שמסתכמים תמיד ל-100% — הגדלת אחד מקטינה אוטומטית את האחרים. "
            "0% = להתעלם מהנתון."))
        self._balancing = False
        self._weight_spins = {}
        g = QGridLayout()
        g.setHorizontalSpacing(14); g.setVerticalSpacing(6)
        # Two columns of (label, spin) pairs — compact instead of a tall list.
        for i, f in enumerate(db.NEED_FACTORS):
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix("%")
            spin.setFixedWidth(90)
            spin.setMinimumHeight(_INPUT_H)
            spin.valueChanged.connect(lambda _v, k=f["key"]: self._rebalance(k))
            self._weight_spins[f["key"]] = spin
            r, c = i % 3, (i // 3) * 2
            g.addWidget(_flabel(f["label"]), r, c)
            g.addWidget(spin, r, c + 1, alignment=Qt.AlignmentFlag.AlignRight)
        g.setColumnStretch(4, 1)
        g.setColumnMinimumWidth(4, 0)
        body.addLayout(g)
        self.lbl_weight_preview = QLabel("")
        self.lbl_weight_preview.setWordWrap(True)
        self.lbl_weight_preview.setStyleSheet(_DESC)
        body.addWidget(self.lbl_weight_preview)
        body.addLayout(_btn_row(
            _btn("שמור משקלים", _BTN_PRIMARY, self._save_weights,
                 "שמור את המשקלים וחשב מחדש את ניקוד העדיפות"),
            _btn("אפס לברירת מחדל", _BTN_GHOST, self._reset_weights)))
        _place(row, card, body)

        # ── איזון קהילות (#lejmr) ──
        card, body, _h = _card("איזון קהילות", "users", "חלוקה הוגנת בין הקהילות")
        body.addWidget(_desc(
            "כשמחלקים לפי סינון מותאם עם 'איזון בין קהילות', כל קהילה מקבלת חלק יחסי "
            "לגודלה. כאן אפשר לקבוע ידנית אחוז קבוע לקהילה מסוימת — השאר יחולק יחסית "
            "בין הקהילות הנותרות."))
        body.addLayout(_btn_row(
            _btn("כוונון אחוזים לקהילות…", _BTN_GHOST, self._open_community_quotas)))
        _place(row, card, body)

        # ═════════════════════════ התוכנה ═════════════════════════
        lay.addLayout(_section("התוכנה"))
        row = _row(); lay.addLayout(row)

        # ── עדכון תוכנה ──
        card, body, _h = _card("עדכון תוכנה", "update", "גרסאות חדשות מגיעות לבד")
        ver_row = QHBoxLayout()
        ver_row.setSpacing(10)
        ver_row.addWidget(_flabel("גרסה נוכחית"))
        self.lbl_version = QLabel(f"v{APP_VERSION}")
        self.lbl_version.setStyleSheet(_CHIP_GREEN)
        ver_row.addWidget(self.lbl_version)
        ver_row.addStretch()
        self.btn_check_update = _btn("בדוק עדכונים", _BTN_GHOST, self._check_updates,
                                     "בדוק אם קיימת גרסה חדשה יותר", small=True)
        ver_row.addWidget(self.btn_check_update)
        body.addLayout(ver_row)
        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setStyleSheet(_DESC)
        body.addWidget(self.lbl_update_status)
        # v2.96 — per-machine flag for download / peer-update balloons.
        self.chk_dl_notify = QCheckBox(
            "קבל התראות במחשב זה על הורדות גרסה ועדכוני המחשב השני")
        self.chk_dl_notify.setToolTip(
            "כשמסומן: המחשב הזה (ורק הוא) יציג התראת Windows כשמישהו מוריד "
            "את התוכנה מגיטהאב, וכשהמחשב השני מתעדכן לגרסה חדשה.")
        self.chk_dl_notify.setChecked(sync.notify_downloads())
        self.chk_dl_notify.toggled.connect(sync.set_notify_downloads)
        body.addWidget(self.chk_dl_notify)
        _place(row, card, body)

        # ── הודעות למפתח ──
        card, body, _h = _card("הודעות למפתח", "send", "דיווח על תקלה או בקשה")
        body.addWidget(_desc("נתקלת בבעיה או יש רעיון? כתוב למפתח מכאן. כל ההודעות "
                             "שנשלחו משני המחשבים נשמרות ואפשר לסמן אותן כטופלו."))
        self.btn_feedback = _btn("✉ השאר הודעה למפתח", _BTN_ACCENT, self._open_feedback,
                                 "דווח על בעיה או השאר בקשה — נשלח למפתח")
        self.btn_feedback_inbox = _btn("📥 הודעות שנשלחו", _BTN_GHOST, self._open_feedback_inbox,
                                       "כל ההודעות שנשלחו למפתח משני המחשבים — צפייה, העתקה וסימון כטופל")
        body.addLayout(_btn_row(self.btn_feedback, self.btn_feedback_inbox))
        self._refresh_feedback_inbox_btn()
        _place(row, card, body)

        # ═════════════════════════ אזור מסוכן ═════════════════════════
        card, body, _h = _card("אזור מסוכן", "danger", "פעולות בלתי הפיכות", danger=True)
        d_row = QHBoxLayout()
        d_row.setSpacing(12)
        d_row.addWidget(_desc("מחיקת כל הנתונים — המקבלים, ההיסטוריה ויומן השינויים. "
                              "ההגדרות (סיסמה, תיקיית גיבוי, חיבורים) נשמרות. "
                              "כשהסנכרון פעיל, הנתונים נמשכים מחדש מהמחשב השני."), 1)
        d_row.addWidget(_btn("אפס את כל הנתונים", _BTN_DANGER, self._reset_data,
                             "מוחק את כל המקבלים, ההיסטוריה ויומן השינויים"))
        body.addLayout(d_row)
        lay.addWidget(card)
        lay.addStretch()
        self._refresh_header_chips()

    def _refresh_header_chips(self):
        """The title-row chips: sync / yemot / mail state at a glance."""
        from utils import yemot
        if sync.is_enabled():
            ok = sync.folder_available()
            self.chip_sync.setText("●  סנכרון פעיל" if ok else "●  סנכרון — התיקייה לא נמצאה")
            self.chip_sync.setStyleSheet(_CHIP_GREEN if ok else _CHIP_RED)
        else:
            self.chip_sync.setText("●  סנכרון כבוי")
            self.chip_sync.setStyleSheet(_CHIP_QSS)
        ym = yemot.is_configured()
        self.chip_yemot.setText("●  ימות המשיח מחובר" if ym else "●  ימות המשיח לא חובר")
        self.chip_yemot.setStyleSheet(_CHIP_GREEN if ym else _CHIP_AMBER)
        ml = email_utils.is_configured()
        self.chip_mail.setText("●  מייל מוגדר" if ml else "●  מייל לא הוגדר")
        self.chip_mail.setStyleSheet(_CHIP_GREEN if ml else _CHIP_AMBER)

    def refresh(self):
        # Show the password masked with the RIGHT number of dots (matches the
        # real length) instead of a fixed 8. Length is recorded on login / change;
        # if unknown yet, fall back to a neutral placeholder.
        try:
            plen = int(db.get_setting("password_len") or 0)
        except (ValueError, TypeError):
            plen = 0
        self.lbl_password.setText("•" * plen if plen > 0 else "•••• (מוגדרת)")
        self._load_weights()

        folder = db.get_setting("backup_folder") or ""
        if folder:
            self.lbl_backup_folder.setText(folder)
        else:
            # Backups still happen automatically to the default location.
            self.lbl_backup_folder.setText(f"{db.BACKUP_DIR}  (ברירת מחדל)")
        self.lbl_backup_folder.setStyleSheet("color:#374151;")
        self.btn_backup_now.setEnabled(True)

        last_backup = db.get_setting("last_backup_at") or ""
        if last_backup:
            try:
                parsed = datetime.fromisoformat(last_backup)
                last_backup = parsed.strftime("%d/%m/%Y %H:%M")
                self.lbl_last_backup.setStyleSheet("color:#334155;")
            except ValueError:
                pass
        else:
            last_backup = "לא בוצע עדיין"
            self.lbl_last_backup.setStyleSheet("color:#9ca3af;")
        self.lbl_last_backup.setText(last_backup)

        self.org_title.setText(db.get_setting("org_title") or "")
        self.org_subtitle.setText(db.get_setting("org_subtitle") or "")
        self._refresh_logo_status()

        cfg = email_utils.get_smtp_config()
        self.mail_email.setText(cfg["email"])
        self.mail_password.setText(cfg["app_password"])
        self.mail_file_pw.setText(email_utils.get_checklist_password())
        if email_utils.is_configured():
            self.lbl_mail_status.setText("מוגדר ✓")
            self.lbl_mail_status.setStyleSheet("color:#334155;")
        else:
            self.lbl_mail_status.setText("לא הוגדר עדיין")
            self.lbl_mail_status.setStyleSheet("color:#9ca3af;")

        # Live statuses each time the tab is opened (v2.80).
        self._refresh_sync_status()
        self._refresh_manager_status()
        self._refresh_feedback_inbox_btn()
        self._refresh_header_chips()
        self._load_survey_settings()      # v3.02 — may have synced from the other PC

    def _refresh_feedback_inbox_btn(self):
        try:
            n = db.open_feedback_count()
        except Exception:
            n = 0
        self.btn_feedback_inbox.setText(
            f"📥 הודעות שנשלחו ({n} פתוחות)" if n else "📥 הודעות שנשלחו")

    def _open_feedback_inbox(self):
        FeedbackInboxDialog(self).exec()
        self._refresh_feedback_inbox_btn()

    # ── Need-score weights ────────────────────────────────────────────────────

    @staticmethod
    def _even_split(total: int, keys: list) -> dict:
        base, rem = divmod(total, len(keys))
        return {k: base + (1 if i < rem else 0) for i, k in enumerate(keys)}

    @staticmethod
    def _scale_to_100(vals: dict) -> dict:
        keys = list(vals)
        s = sum(vals.values())
        if s <= 0:
            return SettingsTab._even_split(100, keys)
        raw = {k: 100 * vals[k] / s for k in keys}
        out = {k: int(raw[k]) for k in keys}
        rem = 100 - sum(out.values())
        for k in sorted(keys, key=lambda k: raw[k] - out[k], reverse=True)[:rem]:
            out[k] += 1
        return out

    def _load_weights(self):
        weights = db.get_need_weights()
        keys = [f["key"] for f in db.NEED_FACTORS]
        self._balancing = True
        try:
            vals = self._scale_to_100({k: weights.get(k, 0) for k in keys})
            for k in keys:
                self._weight_spins[k].setValue(vals[k])
        finally:
            self._balancing = False
        self._update_weight_total()

    def _rebalance(self, changed: str):
        """Keep the weights summing to 100%: when one changes, distribute the
        remaining budget across the others in proportion to their current values
        (so raising one lowers the rest, which is what users expect)."""
        if self._balancing:
            return
        self._balancing = True
        try:
            keys = [f["key"] for f in db.NEED_FACTORS]
            v = self._weight_spins[changed].value()
            others = [k for k in keys if k != changed]
            budget = 100 - v
            osum = sum(self._weight_spins[o].value() for o in others)
            if budget <= 0:
                newvals = {o: 0 for o in others}
            elif osum <= 0:
                newvals = self._even_split(budget, others)
            else:
                raw = {o: budget * self._weight_spins[o].value() / osum for o in others}
                newvals = {o: int(raw[o]) for o in others}
                rem = budget - sum(newvals.values())
                for o in sorted(others, key=lambda o: raw[o] - newvals[o], reverse=True)[:rem]:
                    newvals[o] += 1
            for o in others:
                self._weight_spins[o].setValue(newvals[o])
        finally:
            self._balancing = False
        self._update_weight_total()

    def _update_weight_total(self):
        total = sum(s.value() for s in self._weight_spins.values())
        self.lbl_weight_preview.setText(f"סה\"כ: {total}%")
        self.lbl_weight_preview.setStyleSheet(
            "color:#334155;" if total == 100 else "color:#b45309;")

    def _save_weights(self):
        db.set_need_weights({k: s.value() for k, s in self._weight_spins.items()})
        if self.main_win:
            self.main_win.status_msg("משקלי הניקוד נשמרו")
            self.main_win.refresh_all()
        QMessageBox.information(
            self, "נשמר", "משקלי הניקוד עודכנו וניקוד העדיפות חושב מחדש ✓")

    def _reset_weights(self):
        db.set_need_weights(db.DEFAULT_NEED_WEIGHTS)
        self._load_weights()
        if self.main_win:
            self.main_win.refresh_all()
        QMessageBox.information(self, "אופס", "המשקלים אופסו לברירת המחדל ✓")

    def _backup_now(self):
        result = auto_backup()
        if result is True:
            self.refresh()
            QMessageBox.information(self, "גיבוי הושלם", "הגיבוי הושלם בהצלחה ✓")
        else:
            QMessageBox.warning(self, "שגיאה בגיבוי",
                "הגיבוי נכשל.\nוודא שתיקיית הגיבוי קיימת ונגישה.")

    def _ensure_safety_backup(self) -> bool:
        """Make a safety backup before a destructive action.
        Returns True if it is safe to proceed, False if the user aborted.

        - Backup succeeded            → proceed silently.
        - No backup folder configured → warn, let the user choose to proceed anyway.
        - Backup failed (folder set)  → abort; do NOT risk data loss.
        """
        # Safety bucket ('safety_*') — kept separate from routine backups so
        # ordinary churn can never evict this pre-destructive recovery point (C1).
        result = auto_backup(kind="safety")
        if result is True:
            return True

        if result is None:
            reply = QMessageBox.warning(
                self, "אין גיבוי בטיחות",
                "לא הוגדרה תיקיית גיבוי, ולכן לא ייווצר גיבוי בטיחות לפני הפעולה.\n\n"
                "מומלץ להגדיר תיקיית גיבוי תחילה.\nלהמשיך בכל זאת?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            return reply == QMessageBox.StandardButton.Yes

        # result is False — backup folder is set but the backup failed.
        QMessageBox.critical(
            self, "גיבוי בטיחות נכשל",
            "יצירת גיבוי הבטיחות נכשלה — הפעולה בוטלה כדי למנוע אובדן נתונים.\n"
            "ודא שתיקיית הגיבוי קיימת ונגישה ונסה שוב."
        )
        return False

    def _open_backup_list(self):
        """#69pen: every saved backup in one list with a 'שחזר' button per row."""
        dlg = BackupListDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen_path:
            self._restore_path(dlg.chosen_path)

    def _restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ גיבוי", "", "קבצי גיבוי (*.db);;הכל (*.*)"
        )
        if not path:
            return
        self._restore_path(path)

    def _restore_path(self, path: str):
        reply = QMessageBox.warning(
            self, "שחזור מגיבוי",
            f"הנתונים הנוכחיים יוחלפו לחלוטין בתוכן הגיבוי:\n{path}\n\n"
            "פעולה זו אינה הפיכה!\nלהמשיך?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Safety backup before overwriting — abort if it cannot be made.
        if not self._ensure_safety_backup():
            return

        with busy_cursor():
            ok = restore_from_backup(path)
            if ok:
                self.refresh()
                if self.main_win:
                    self.main_win.refresh_all()
        if ok:
            QMessageBox.information(self, "שחזור הושלם", "הנתונים שוחזרו בהצלחה מהגיבוי ✓")
        else:
            QMessageBox.critical(self, "שגיאה", "שחזור נכשל — ודא שהקובץ תקין ונגיש.")

    def _reset_data(self):
        synced = sync.is_enabled()
        text = "פעולה זו תמחק את כל המקבלים וההיסטוריה לצמיתות.\n\n"
        if synced:
            # Reset = "start over from the other computer" (user decision 2/9/2026):
            # the wipe is local only, and everything is pulled again from the peer.
            text = ("פעולה זו תמחק את כל המקבלים וההיסטוריה במחשב הזה,\n"
                    "ואחר כך תמשוך מחדש את כל הנתונים מהמחשב השני.\n"
                    "(המחיקה אינה משפיעה על המחשב השני.)\n\n")
        confirm, ok = QInputDialog.getText(
            self, "אפוס נתונים", text + "הקלד   אפס   לאישור:",
            QLineEdit.EchoMode.Normal
        )
        if not ok or confirm.strip() != "אפס":
            return

        # Safety backup before wiping — abort if it cannot be made.
        if not self._ensure_safety_backup():
            return

        pulled = 0
        with busy_cursor():
            db.reset_all_data()
            if synced:
                pulled = sync.restart_from_peer()
            if self.main_win:
                self.main_win.refresh_all()
        msg = "כל הנתונים נמחקו. הגדרות המערכת נשמרו."
        if synced:
            msg += (f"\n\nנקלטו מחדש {pulled} רשומות מהמחשב השני. "
                    "אם המחשב השני כבוי, שאר הנתונים יגיעו אוטומטית כשיופעל.")
        QMessageBox.information(self, "אופס הושלם", msg)

    def _change_password(self):
        if self.main_win and hasattr(self.main_win, "change_password"):
            self.main_win.change_password()

    def _open_feedback(self):
        from utils.ui import FeedbackDialog
        FeedbackDialog.open(self)

    # ── Community balance percentages (#lejmr) ───────────────────────────────
    def _open_community_quotas(self):
        CommunityQuotasDialog(self).exec()

    # ── Two-computer sync ────────────────────────────────────────────────────
    def _set_sync_dot(self, color: str):
        self.sync_dot.setStyleSheet(
            f"background-color:{color}; border-radius:7px; border:2px solid #ffffff;")

    def _clear_sync_chips(self):
        while self.sync_chips_lay.count() > 1:   # keep the trailing stretch
            item = self.sync_chips_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_sync_chip(self, text: str, fg: str = "#334155", bg: str = "#eef4f1"):
        chip = QLabel(text)
        chip.setStyleSheet(
            f"QLabel{{background:{bg}; color:{fg}; border:none; border-radius:14px; "
            "padding:4px 12px; font-size:12px; font-weight:700;}}")
        self.sync_chips_lay.insertWidget(self.sync_chips_lay.count() - 1, chip)

    def _refresh_sync_status(self):
        """Visual sync status (v2.80, #n02fc): a colored state dot + headline and
        chips for device / last run / pending / peers — not a wall of text."""
        self._clear_sync_chips()
        if not sync.is_enabled():
            self._set_sync_dot("#94a3b8")
            self.sync_headline.setText("סנכרון כבוי")
            self.sync_headline.setStyleSheet(
                "font-size:13.5px; font-weight:700; color:#64748b;")
            self.lbl_sync_folder.setText(
                "הגדר תיקיית Google Drive משותפת כדי לעבוד משני מחשבים על אותם נתונים.")
            return
        from utils import timefmt
        info = sync.last_run_info()
        folder = sync.get_folder()
        avail = sync.folder_available()
        name = sync.device_name() or "מחשב זה"
        others = sync.other_device_count() if avail else 0
        pending = int(info.get("pending", 0) or 0)
        if not avail:
            self._set_sync_dot("#dc2626")
            self.sync_headline.setText("התיקייה המשותפת לא נמצאה כרגע")
            hl_color = "#b91c1c"
        elif others > 0:
            self._set_sync_dot("#16a34a")
            self.sync_headline.setText("מסונכרן — המחשב השני מחובר")
            hl_color = "#166534"
        else:
            self._set_sync_dot("#f59e0b")
            self.sync_headline.setText("פעיל — עדיין לא זוהה מחשב שני")
            hl_color = "#b45309"
        self.sync_headline.setStyleSheet(
            f"font-size:13.5px; font-weight:700; color:{hl_color};")
        last_rel = timefmt.relative(info.get("last_run") or "")
        self._add_sync_chip(f"🖥 {name}")
        self._add_sync_chip("⏱ סונכרן " + last_rel if last_rel else "⏱ טרם סונכרן",
                            fg="#334155" if last_rel else "#b45309",
                            bg="#eef4f1" if last_rel else "#fef3c7")
        if pending:
            self._add_sync_chip(f"📤 ממתינים לשליחה: {pending}",
                                fg="#b45309", bg="#fef3c7")
        else:
            self._add_sync_chip("✓ הכול נשלח", fg="#166534", bg="#dcfce7")
        if avail:
            self._add_sync_chip(f"💻 מחשבים נוספים: {others}",
                                fg="#166534" if others else "#b45309",
                                bg="#dcfce7" if others else "#fef3c7")
        note = "" if avail else "  ⚠ ודא ש-Google Drive פועל ושהתיקייה קיימת"
        hint = ("" if others or not avail else
                "\nודא ששני המחשבים מצביעים לאותה תיקייה בתוך «Drive שלי».")
        self.lbl_sync_folder.setText(f"תיקייה: {folder}{note}{hint}")

    def _open_sync_setup(self):
        SyncSetupDialog(self).exec()
        self._refresh_sync_status()
        self._refresh_header_chips()
        if self.main_win and hasattr(self.main_win, "_refresh_sync_led"):
            self.main_win._refresh_sync_led()

    # ── Arrival survey (v3.02) ──────────────────────────────────────────────────
    def _load_survey_settings(self):
        from utils import yemot
        try:
            saved = json.loads(db.get_setting(yemot.SET_ANSWER_LABELS) or "{}")
        except ValueError:
            saved = {}
        for key, w in self.ym_ans.items():
            w.setText(str((saved or {}).get(key) or ""))
        self.ym_survey_prompt.setText(db.get_setting(yemot.SET_SURVEY_PROMPT) or "")

    def _save_survey_settings(self):
        """Labels + question text → synced settings (blank = default)."""
        from utils import yemot
        labels = {k: w.text().strip() for k, w in self.ym_ans.items() if w.text().strip()}
        db.set_setting(yemot.SET_ANSWER_LABELS, json.dumps(labels, ensure_ascii=False))
        db.set_setting(yemot.SET_SURVEY_PROMPT, self.ym_survey_prompt.text().strip())

    def _upload_survey_prompt(self):
        from utils import yemot
        self._save_survey_settings()
        if not yemot.is_configured():
            self.lbl_survey_status.setText("⚠ קודם הזן את פרטי ימות ולחץ \"שמור\".")
            return
        try:
            with busy_cursor():
                yemot.upload_survey_prompt()
            self.lbl_survey_status.setText(
                f"✓ השאלה עודכנה בקו (שלוחה {yemot.SURVEY_EXT}). "
                "התוויות נשמרו ומופיעות בתוכנה.")
        except Exception as e:
            self.lbl_survey_status.setText(f"⚠ העדכון בקו נכשל: {e}")

    # ── Manager computer + change control (#5rhe9) ──────────────────────────────
    def _refresh_manager_status(self):
        from utils import sync
        is_mgr = sync.is_manager_device()
        if is_mgr:
            self.lbl_mgr_status.setText("✓ מחשב זה מוגדר כמחשב המנהל — יומן השינויים והביטול זמינים כאן.")
            self.lbl_mgr_status.setStyleSheet("color:#0f766e; font-size:12.5px; font-weight:600;")
            self.btn_mgr_toggle.setText("בטל הגדרת מנהל")
        else:
            self.lbl_mgr_status.setText("מחשב זה אינו מוגדר כמחשב המנהל.")
            self.lbl_mgr_status.setStyleSheet("color:#64748b; font-size:12.5px;")
            self.btn_mgr_toggle.setText("הגדר מחשב זה כמנהל")
        self.btn_mgr_log.setVisible(is_mgr)

    def _toggle_manager(self):
        from utils import sync
        if sync.is_manager_device():
            if QMessageBox.question(
                    self, "ביטול הגדרת מנהל",
                    "לבטל את הגדרת מחשב זה כמחשב המנהל?\nיומן השינויים לא יופיע יותר כאן.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                sync.set_manager_device(False)
                self._refresh_manager_status()
            return
        self._become_manager()

    def _become_manager(self):
        from utils import sync
        if not db.manager_code_is_set():
            # First time: define the manager code (entered twice).
            code, ok = QInputDialog.getText(
                self, "הגדרת קוד מנהל",
                "עדיין לא הוגדר קוד מנהל.\nבחר קוד להגדרת מחשב כמנהל (זכור אותו — "
                "צריך אותו גם במחשב השני):", QLineEdit.EchoMode.Password)
            if not ok:
                return
            code = (code or "").strip()
            if len(code) < 3:
                QMessageBox.warning(self, "קוד קצר מדי", "הקוד חייב להכיל לפחות 3 תווים.")
                return
            code2, ok = QInputDialog.getText(
                self, "אישור קוד מנהל", "הקלד שוב את הקוד לאישור:",
                QLineEdit.EchoMode.Password)
            if not ok:
                return
            if (code2 or "").strip() != code:
                QMessageBox.warning(self, "אי-התאמה", "הקודים אינם תואמים. נסה שוב.")
                return
            db.set_manager_code(code)
            sync.set_manager_device(True)
            QMessageBox.information(self, "הוגדר", "קוד המנהל נקבע ומחשב זה הוגדר כמחשב המנהל ✓")
        else:
            code, ok = QInputDialog.getText(
                self, "קוד מנהל", "הזן את קוד המנהל כדי להגדיר מחשב זה כמנהל:",
                QLineEdit.EchoMode.Password)
            if not ok:
                return
            if db.verify_manager_code((code or "").strip()):
                sync.set_manager_device(True)
                QMessageBox.information(self, "הוגדר", "מחשב זה הוגדר כמחשב המנהל ✓")
            else:
                QMessageBox.warning(self, "קוד שגוי", "קוד המנהל שגוי.")
                return
        self._refresh_manager_status()

    def _open_manager_log(self):
        dlg = ManagerLogDialog(self)
        dlg.exec()
        if self.main_win and hasattr(self.main_win, "refresh_all"):
            self.main_win.refresh_all()
        else:
            QMessageBox.information(
                self, "סנכרון הושלם",
                f"נשלחו {res['pushed']} שינויים, נקלטו {res['applied']} שינויים "
                "מהמחשב השני.")
            if res["applied"] and self.main_win:
                self.main_win.refresh_all()

    def _choose_backup_folder(self):
        if self.main_win and hasattr(self.main_win, "choose_backup_folder"):
            self.main_win.choose_backup_folder()
            self.refresh()

    # ── Export folders (#5e1jc) ─────────────────────────────────────────────────
    def _refresh_export_labels(self):
        for kind, lbl in getattr(self, "_export_path_lbls", {}).items():
            saved = (db.get_setting(f"export_dir_{kind}") or "").strip()
            if saved:
                lbl.setText(saved)
                lbl.setStyleSheet("color:#0f766e;")
            else:
                lbl.setText("תיקיית ההורדות (ברירת מחדל)")
                lbl.setStyleSheet("color:#94a3b8;")

    def _choose_export_dir(self, kind: str):
        start = ((db.get_setting(f"export_dir_{kind}") or "").strip()
                 or os.path.join(os.path.expanduser("~"), "Downloads"))
        path = QFileDialog.getExistingDirectory(self, "בחר תיקיית ייצוא", start)
        if path:
            db.set_setting(f"export_dir_{kind}", path)
            self._refresh_export_labels()

    def _reset_export_dir(self, kind: str):
        db.set_setting(f"export_dir_{kind}", "")
        self._refresh_export_labels()

    # ── Organization / branding ─────────────────────────────────────────────────

    def _save_branding(self):
        db.set_setting("org_title", self.org_title.text().strip())
        db.set_setting("org_subtitle", self.org_subtitle.text().strip())
        # Live-update the top bar without a restart.
        mw = self.main_win
        if mw is not None and hasattr(mw, "_appbar_title_lbl"):
            mw._appbar_title_lbl.setText(self.org_title.text().strip() or "מנהל חלוקה")
            mw._appbar_sub_lbl.setText(
                self.org_subtitle.text().strip() or "קופה של צדקה הר יונה · נוף הגליל")
        QMessageBox.information(self, "נשמר", "שם הארגון עודכן ✓")

    def _choose_logo(self):
        import shutil
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר תמונת לוגו", "", "תמונות (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            shutil.copyfile(path, db.USER_LOGO_PATH)
        except Exception as e:
            QMessageBox.warning(self, "שגיאה", f"לא ניתן להעתיק את הלוגו:\n{e}")
            return
        self._apply_logo_change()

    def _reset_logo(self):
        import os
        try:
            if os.path.exists(db.USER_LOGO_PATH):
                os.remove(db.USER_LOGO_PATH)
        except Exception:
            pass
        self._apply_logo_change()

    def _apply_logo_change(self):
        mw = self.main_win
        if mw is not None and hasattr(mw, "_load_appbar_logo"):
            mw._load_appbar_logo()
        self._refresh_logo_status()

    def _refresh_logo_status(self):
        import os
        custom = os.path.exists(db.USER_LOGO_PATH)
        self.lbl_logo_status.setText("לוגו מותאם אישית ✓" if custom else "לוגו ברירת מחדל")
        self.btn_logo_reset.setEnabled(custom)

    # ── Volunteer email settings ────────────────────────────────────────────────

    def _save_mail_settings(self):
        email = self.mail_email.text().strip()
        password = self.mail_password.text()
        # The file password is independent of the SMTP login — save it either way.
        email_utils.set_checklist_password(self.mail_file_pw.text())
        if not email or not password:
            QMessageBox.warning(self, "", "יש למלא כתובת מייל וסיסמת אפליקציה.")
            return
        email_utils.set_smtp_config(email, password)
        self.refresh()
        QMessageBox.information(self, "נשמר", "הגדרות המייל נשמרו ✓")

    def _test_mail_settings(self):
        # Actually SEND a real test email (to the sender's own address) and report
        # success only if the send truly went through — a login-only check could
        # look "ok" while a real send still fails (bug #19). No internet / bad
        # password / blocked SMTP all surface here as a failure.
        self._save_mail_settings_silent()
        cfg = email_utils.get_smtp_config()
        if not (cfg["email"] and cfg["app_password"]):
            QMessageBox.warning(self, "בדיקת מייל",
                                "יש למלא כתובת מייל וסיסמת אפליקציה תחילה.")
            return
        with busy_cursor():
            try:
                email_utils.send_email(
                    cfg["email"],
                    subject="בדיקת מייל — מנהל חלוקה",
                    html_body="<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
                              "זוהי הודעת בדיקה. אם קיבלת אותה — שליחת המייל מוגדרת כראוי ✓</div>")
                ok, msg = True, (f"נשלח מייל בדיקה בהצלחה אל {cfg['email']} ✓\n"
                                 "בדוק שההודעה הגיעה לתיבת הדואר.")
            except Exception as e:
                ok, msg = False, f"השליחה נכשלה — ודא חיבור לאינטרנט וסיסמת אפליקציה תקינה.\n\n{e}"
        if ok:
            QMessageBox.information(self, "בדיקת מייל", msg)
        else:
            QMessageBox.warning(self, "בדיקת מייל", msg)

    def _save_mail_settings_silent(self):
        email = self.mail_email.text().strip()
        password = self.mail_password.text()
        email_utils.set_checklist_password(self.mail_file_pw.text())
        if email and password:
            email_utils.set_smtp_config(email, password)

    # ── Tzintukim — Yemot HaMashiach (v2.81) ─────────────────────────────────

    def _save_yemot_settings(self, silent: bool = False):
        from utils import yemot
        system = self.ym_system.text().strip()
        password = self.ym_password.text().strip()
        # An API key stands on its own; a regular password needs the system no.
        if not silent and not password:
            QMessageBox.warning(self, "", "יש למלא סיסמה (או מפתח API) של ימות המשיח.")
            return
        db.set_setting(yemot.SET_SYSTEM, system)
        db.set_setting(yemot.SET_PASSWORD, password)
        db.set_setting(yemot.SET_CALLER_ID, self.ym_caller.text().strip())
        db.set_setting("gemini_api_key", self.ym_gemini_key.text().strip())
        self._save_survey_settings()      # v3.02 — labels + question text
        self._refresh_header_chips()
        if not silent:
            self.lbl_ym_status.setText("הפרטים נשמרו ✓ — עכשיו לחץ \"בדוק חיבור\"")

    def _test_yemot_connection(self):
        from utils import yemot
        self._save_yemot_settings(silent=True)
        if not yemot.is_configured():
            QMessageBox.warning(self, "בדיקת חיבור",
                                "יש למלא מספר מערכת וסיסמה תחילה.")
            return
        with busy_cursor():
            try:
                yemot.check_connection()
                balance = None
                try:
                    balance = yemot.get_balance()
                except Exception:
                    pass
                ok, msg = True, "החיבור לימות המשיח תקין ✓"
                if balance is not None:
                    msg += f"\nיתרת יחידות במערכת: {balance:,.1f}"
            except yemot.YemotError as e:
                ok, msg = False, str(e)
            except Exception as e:
                ok, msg = False, f"שגיאה לא צפויה: {e}"
        self.lbl_ym_status.setText(("✓ " if ok else "✗ ") + msg.replace("\n", " · "))
        if ok:
            QMessageBox.information(self, "בדיקת חיבור", msg)
        else:
            QMessageBox.warning(self, "בדיקת חיבור", msg)

    def _apply_font_percent(self):
        """Persist + apply the chosen UI text size to the WHOLE app right now
        (v2.80, #x2yn5): the entire stylesheet is re-applied with every font-size
        scaled, so open screens update instantly — no restart needed."""
        pct = self.font_spin.value()
        db.set_setting("ui_font_scale", str(pct))
        app = QApplication.instance()
        if app is not None:
            import styles
            with busy_cursor():
                styles.apply_app_theme(app, pct)
        if self.main_win:
            self.main_win.status_msg(f"גודל הטקסט: {pct}%")

    # ── Software update ───────────────────────────────────────────────────────

    def _check_updates(self):
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setStyleSheet("")
        self.lbl_update_status.setText("בודק עדכונים מול GitHub...")
        self._worker = _UpdateWorker("check")
        self._worker.checked.connect(self._on_checked)
        self._worker.start()

    def _on_checked(self, result):
        self.btn_check_update.setEnabled(True)
        if isinstance(result, Exception):
            self.lbl_update_status.setStyleSheet("color:#dc2626;")
            self.lbl_update_status.setText("בדיקת העדכונים נכשלה — ודא חיבור לאינטרנט ונסה שוב.")
            return
        if not result or not result.get("url"):
            self.lbl_update_status.setText("לא נמצאה גרסה זמינה.")
            return
        if updater.is_newer(result["version"], APP_VERSION):
            from utils.ui import UpdateOfferDialog
            if UpdateOfferDialog.offer(self, result["version"], APP_VERSION,
                                       result.get("notes") or ""):
                self._start_download(result)
            else:
                self.lbl_update_status.setStyleSheet("color:#b45309;")
                self.lbl_update_status.setText(f"גרסה v{result['version']} זמינה — ניתן לעדכן בכל עת.")
        else:
            self.lbl_update_status.setStyleSheet("color:#334155;")
            self.lbl_update_status.setText(f"התוכנה מעודכנת (v{APP_VERSION}) ✓")

    def _start_download(self, result):
        if not updater.current_exe():
            QMessageBox.information(
                self, "עדכון",
                "עדכון אוטומטי זמין רק בגרסת התוכנה המותקנת (EXE).\n"
                f"ניתן להוריד ידנית את גרסה v{result['version']} מ-GitHub.")
            return
        dest = updater.download_target()
        self._progress = QProgressDialog("מוריד עדכון...", "ביטול", 0, 100, self)
        self._progress.setWindowTitle("עדכון תוכנה")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._worker = _UpdateWorker("download", url=result["url"], dest=dest)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.finished_dl.connect(self._on_downloaded)
        self._progress.canceled.connect(self._worker.cancel)
        self._progress.setValue(0)
        self._worker.start()

    def _on_downloaded(self, result):
        if hasattr(self, "_progress") and self._progress is not None:
            self._progress.close()
        if isinstance(result, Exception):
            if isinstance(result, InterruptedError):
                self.lbl_update_status.setText("העדכון בוטל.")
            else:
                QMessageBox.critical(self, "שגיאת עדכון",
                                     f"הורדת העדכון נכשלה:\n{result}")
            return
        # Release the single-instance lock BEFORE relaunching, otherwise the new
        # (updated) child process would see the lock still held and refuse to start.
        _app = QApplication.instance()
        _sm = getattr(_app, "_single_instance", None)
        if _sm is not None:
            try:
                _sm.detach()
            except Exception:
                pass

        err = updater.apply_update(result)
        if err:
            QMessageBox.critical(self, "שגיאת עדכון", err)
            return
        # #ko0a0: no confirmation click — the app closes itself and the updated
        # version opens automatically (apply_update already relaunched it).
        QApplication.quit()


class FeedbackInboxDialog(QDialog):
    """'הודעות שנשלחו למפתח' (v2.80, #ce6a0): כל הודעות המשוב — משני המחשבים —
    מוצגות בתוך התוכנה, עם העתקה וסימון 'טופל'. כך המפעיל יודע אילו תקלות
    דווחו בלי ללכת לגיטהאב."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הודעות שנשלחו למפתח")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(760, 540)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self)
        head = QLabel("כל ההודעות שנשלחו למפתח דרך \"השאר הודעה למפתח\" — משני "
                      "המחשבים. לחיצה על שורה מציגה את ההודעה המלאה; אפשר להעתיק "
                      "אותה ולסמן שטופלה.")
        head.setWordWrap(True)
        head.setStyleSheet("color:#334155; font-size:13px;")
        lay.addWidget(head)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["מתי", "מאת", "מחשב", "ההודעה", "פעולה"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        for c in (0, 1, 2, 4):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selected)
        lay.addWidget(self.table, 2)

        from PyQt6.QtWidgets import QPlainTextEdit
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("בחר הודעה ברשימה כדי לראות אותה במלואה")
        self.preview.setMinimumHeight(110)
        try:
            from utils.ui import rtl_text_area
            rtl_text_area(self.preview)
        except Exception:
            pass
        lay.addWidget(self.preview, 1)

        btns = QHBoxLayout()
        self.btn_copy = QPushButton("העתק הודעה")
        self.btn_copy.setObjectName("neutral")
        self.btn_copy.clicked.connect(self._copy_selected)
        btns.addWidget(self.btn_copy)
        self.btn_copy_open = QPushButton("העתק את כל הפתוחות")
        self.btn_copy_open.setObjectName("neutral")
        self.btn_copy_open.setToolTip("מעתיק את כל ההודעות שטרם טופלו — נוח "
                                      "להדבקה בבקשת תיקון אחת")
        self.btn_copy_open.clicked.connect(self._copy_open)
        btns.addWidget(self.btn_copy_open)
        btns.addStretch()
        close = QPushButton("סגור")
        close.setObjectName("neutral")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        lay.addLayout(btns)

        self._rows = []
        self._reload()

    @staticmethod
    def _entry_text(fb: dict) -> str:
        from utils import timefmt
        when = timefmt.datetime_str(fb.get("created_at") or "") or (fb.get("created_at") or "")
        meta = " · ".join(x for x in (
            when, fb.get("author_name") or "", fb.get("host") or "",
            f"v{fb['version']}" if fb.get("version") else "") if x)
        return f"[{meta}]\n{fb.get('body') or ''}"

    def _reload(self, keep_row: int = -1):
        from utils import timefmt
        self._rows = db.get_feedback()
        self.table.setRowCount(len(self._rows))
        for r, fb in enumerate(self._rows):
            done = (fb.get("status") == "done")
            when = QTableWidgetItem(timefmt.datetime_str(fb.get("created_at") or "")
                                    or (fb.get("created_at") or ""))
            when.setToolTip(timefmt.relative(fb.get("created_at") or ""))
            self.table.setItem(r, 0, when)
            self.table.setItem(r, 1, QTableWidgetItem(fb.get("author_name") or "—"))
            self.table.setItem(r, 2, QTableWidgetItem(fb.get("host") or ""))
            body = (fb.get("body") or "").replace("\n", " ")
            body_item = QTableWidgetItem(body if len(body) <= 90 else body[:90] + "…")
            body_item.setToolTip(fb.get("body") or "")
            self.table.setItem(r, 3, body_item)
            if done:
                for c in range(4):
                    it = self.table.item(r, c)
                    if it:
                        it.setForeground(QColor("#9aa7b8"))
            btn = QPushButton("החזר לפתוח" if done else "סמן כטופל")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:%s; color:#ffffff; border:none;"
                "border-radius:8px; padding:4px 12px; font-weight:700;}"
                "QPushButton:hover{background:%s;}"
                % (("#94a3b8", "#64748b") if done else ("#0f9d78", "#0b7e60")))
            btn.clicked.connect(lambda _=False, g=fb.get("guid"), d=done:
                                self._set_status(g, "open" if d else "done"))
            self.table.setCellWidget(r, 4, btn)
        self.table.resizeRowsToContents()
        if 0 <= keep_row < len(self._rows):
            # setCurrentCell (not selectRow) — with SelectRows behavior it
            # highlights the whole row AND reliably fires itemSelectionChanged.
            self.table.setCurrentCell(keep_row, 0)

    def _selected_fb(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _show_selected(self):
        fb = self._selected_fb()
        self.preview.setPlainText(self._entry_text(fb) if fb else "")

    def _set_status(self, guid, status):
        row = self.table.currentRow()
        db.set_feedback_status(guid or "", status)
        self._reload(keep_row=row)

    def _flash(self, btn, text="הועתק ✓"):
        from PyQt6.QtCore import QTimer
        orig = btn.text()
        btn.setText(text)
        QTimer.singleShot(1500, lambda: btn.setText(orig))

    def _copy_selected(self):
        fb = self._selected_fb()
        if not fb:
            QMessageBox.information(self, "", "בחר קודם הודעה ברשימה.")
            return
        QApplication.clipboard().setText(self._entry_text(fb))
        self._flash(self.btn_copy)

    def _copy_open(self):
        open_fbs = [fb for fb in self._rows if fb.get("status") != "done"]
        if not open_fbs:
            QMessageBox.information(self, "", "אין הודעות פתוחות להעתקה.")
            return
        QApplication.clipboard().setText(
            "\n\n———\n\n".join(self._entry_text(fb) for fb in open_fbs))
        self._flash(self.btn_copy_open)


class ManagerLogDialog(QDialog):
    """The manager's change-log (#5rhe9): every change received from the other
    computer, newest first, each with an 'undo' that restores the previous state
    and syncs the correction back. Only opened on the manager computer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("יומן שינויים — בקרת מנהל")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(760, 520)
        lay = QVBoxLayout(self)
        head = QLabel("שינויים שנקלטו מהמחשב השני. אפשר לבטל שינוי — התוכנה תחזיר "
                      "את הערך הקודם והתיקון יסתנכרן חזרה לכל המחשבים.")
        head.setWordWrap(True)
        head.setStyleSheet("color:#334155; font-size:13px;")
        lay.addWidget(head)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["מתי", "מקבל", "מה השתנה", "פעולה"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        close = QPushButton("סגור")
        close.setObjectName("neutral")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        lay.addLayout(btns)

        self._reload()

    def _reload(self):
        from utils import timefmt
        rows = db.get_incoming_log(limit=300)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            undone = bool(rec.get("undone"))
            t = QTableWidgetItem(timefmt.datetime_str(rec.get("applied_at")))
            t.setToolTip(timefmt.relative(rec.get("applied_at")))
            self.table.setItem(r, 0, t)
            self.table.setItem(r, 1, QTableWidgetItem(rec.get("target_name") or ""))
            summ = QTableWidgetItem(rec.get("summary") or "")
            summ.setToolTip(rec.get("summary") or "")
            self.table.setItem(r, 2, summ)
            if undone:
                done = QTableWidgetItem("בוטל ✓")
                done.setForeground(QColor("#94a3b8"))
                self.table.setItem(r, 3, done)
                for c in range(3):
                    it = self.table.item(r, c)
                    if it:
                        it.setForeground(QColor("#9aa7b8"))
            else:
                btn = QPushButton("בטל")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton{background:#f59e0b; color:#ffffff; border:none;"
                    "border-radius:8px; padding:4px 14px; font-weight:700;}"
                    "QPushButton:hover{background:#d97706;}")
                btn.clicked.connect(lambda _=False, i=rec.get("id"): self._undo(i))
                self.table.setCellWidget(r, 3, btn)
        self.table.resizeRowsToContents()

    def _undo(self, incoming_id):
        rec = next((x for x in db.get_incoming_log(limit=300)
                    if x.get("id") == incoming_id), None)
        name = (rec or {}).get("target_name") or "המקבל"
        if QMessageBox.question(
                self, "ביטול שינוי",
                f"לבטל את השינוי על '{name}' ולהחזיר את הערך הקודם?\n"
                "התיקון יסתנכרן חזרה לכל המחשבים.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        ok, msg = db.undo_incoming(incoming_id)
        if ok:
            QMessageBox.information(self, "בוטל", msg)
        else:
            QMessageBox.warning(self, "לא בוטל", msg)
        self._reload()


class CommunityQuotasDialog(QDialog):
    """Pin an optional fixed percentage per community (#lejmr). A blank/0 percent
    means 'automatic' — that community shares the leftover percent proportionally
    to size. Manual percentages over 100 in total are normalised down when the
    distribution is built."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("כוונון אחוזים לקהילות")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(560, 560)
        self._spins = {}
        outer = QVBoxLayout(self)
        intro = QLabel("קבע אחוז קבוע לקהילה (לפי שם נציג). קהילה שנשארת על 0 = "
                       "אוטומטי (חלק יחסי לגודלה). סכום מעל 100% ינורמל אוטומטית.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569; font-size:12.5px;")
        outer.addWidget(intro)

        sizes = db.get_community_sizes()
        pinned = db.get_community_quotas()
        communities = sorted(c for c in sizes if c)   # skip the '' (no-community) key
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["קהילה (נציג)", "גודל", "אחוז קבוע"])
        table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Give the size + percent columns real room so the spinbox value isn't
        # cramped and unreadable (#7aaaf).
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(2, 150)
        table.verticalHeader().setDefaultSectionSize(46)
        table.setRowCount(len(communities))
        for r, c in enumerate(communities):
            it_name = QTableWidgetItem(c)
            it_size = QTableWidgetItem(str(sizes.get(c, 0)))
            for it in (it_name, it_size):
                it.setTextAlignment(ALIGN_RIGHT)
            table.setItem(r, 0, it_name)
            table.setItem(r, 1, it_size)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setDecimals(1)
            spin.setSuffix(" %")
            spin.setValue(float(pinned.get(c, 0) or 0))
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
            spin.setMinimumHeight(34)
            spin.setStyleSheet(
                "QDoubleSpinBox{font-size:15px; font-weight:700; padding:2px 6px;"
                " margin:4px 8px; min-width:110px;}")
            table.setCellWidget(r, 2, spin)
            self._spins[c] = spin
        enable_touch_scroll(table)
        outer.addWidget(table, 1)
        if not communities:
            outer.addWidget(QLabel("עדיין אין קהילות (שם נציג) במקבלים."))

        btns = QHBoxLayout()
        btn_save = QPushButton("שמור")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("ביטול")
        btn_cancel.setObjectName("neutral")
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_save)
        btns.addWidget(btn_cancel)
        outer.addLayout(btns)

    def _save(self):
        quotas = {c: spin.value() for c, spin in self._spins.items() if spin.value() > 0}
        db.set_community_quotas(quotas)
        QMessageBox.information(self, "נשמר", "אחוזי הקהילות נשמרו ✓")
        self.accept()


class SyncSetupDialog(QDialog):
    """Set up (or turn off) syncing this computer's data with a second computer
    through a shared Google Drive folder (v2.61). Walks the operator through
    picking the folder, naming this computer, and seeding the data."""

    # Official Google direct installer (downloads the setup .exe immediately);
    # the info page is a fallback.
    DRIVE_INSTALLER_URL = "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe"
    DRIVE_PAGE_URL = "https://www.google.com/drive/download/"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הגדרת סנכרון בין מחשבים")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)

        guide = QLabel(
            "<div dir='rtl'>"
            "סנכרון מאפשר לעבוד על <b>אותם נתונים משני מחשבים</b>. "
            "צריך רק ש-<b>Google Drive למחשב</b> יהיה מותקן בשני המחשבים ומחובר "
            "לאותו חשבון גוגל.<br>"
            "לחצו על הכפתור הירוק בכל מחשב — התוכנה תסדר את הכול לבד. "
            "מאותו רגע כל שינוי מסונכרן אוטומטית; עבודה בו-זמנית בטוחה.</div>")
        guide.setTextFormat(Qt.TextFormat.RichText)
        guide.setWordWrap(True)
        guide.setStyleSheet("font-size:12.5px; color:#334155;")
        outer.addWidget(guide)

        # ── The easy path: one click sets up everything ──────────────────────
        self.btn_auto = QPushButton("🔄  הפעל סנכרון אוטומטי  (מומלץ)")
        self.btn_auto.setObjectName("primary")
        self.btn_auto.setStyleSheet("font-size:14px; padding:10px;")
        self.btn_auto.clicked.connect(self._auto_enable)
        outer.addWidget(self.btn_auto)

        auto_hint = QLabel(
            "<div dir='rtl' style='color:#475569; font-size:11.5px;'>"
            "התוכנה תמצא לבד את «Drive שלי», תיצור בתוכו תיקייה משותפת בשם קבוע, "
            "ותיתן למחשב שם אוטומטית. עשו את אותו הדבר במחשב השני — והם יתחברו לבד."
            "</div>")
        auto_hint.setWordWrap(True)
        outer.addWidget(auto_hint)

        # Always-visible direct download of Google Drive for Desktop, in case it
        # isn't installed yet on this computer.
        dl_link = QLabel(
            "<div dir='rtl' style='font-size:11.5px;'>"
            "עדיין לא מותקן במחשב? "
            f"<a href='{self.DRIVE_INSTALLER_URL}'>הורדת Google Drive למחשב ⭳</a></div>")
        dl_link.setTextFormat(Qt.TextFormat.RichText)
        dl_link.setOpenExternalLinks(True)
        dl_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        outer.addWidget(dl_link)

        # ── Advanced: manual folder / name (hidden by default) ───────────────
        self.btn_advanced = QPushButton("▾ אפשרויות מתקדמות (בחירת תיקייה ידנית)")
        self.btn_advanced.setObjectName("neutral")
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setStyleSheet("text-align:right; border:none; color:#475569;")
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        outer.addWidget(self.btn_advanced)

        self.adv = QWidget()
        adv_lay = QVBoxLayout(self.adv)
        adv_lay.setContentsMargins(0, 0, 0, 0)

        adv_guide = QLabel(
            "<div dir='rtl' style='font-size:11.5px; color:#334155;'>"
            "בחרו תיקייה <b>בתוך «Drive שלי» (My Drive)</b> — אותה תיקייה בדיוק "
            "בשני המחשבים.<br>"
            "<b style='color:#b45309;'>⚠</b> אל תבחרו תיקייה בתוך "
            "<b>הורדות/שולחן העבודה/מסמכים</b> — את אלה Drive מגבה בנפרד לכל מחשב "
            "ולא משתף, והסנכרון לא יעבוד.</div>")
        adv_guide.setWordWrap(True)
        adv_lay.addWidget(adv_guide)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("תיקייה משותפת:"))
        self.folder_edit = QLineEdit(sync.get_folder())
        self.folder_edit.setPlaceholderText("נתיב לתיקייה בתוך Google Drive")
        folder_row.addWidget(self.folder_edit, 1)
        btn_browse = QPushButton("עיון…")
        btn_browse.setObjectName("neutral")
        btn_browse.clicked.connect(self._browse)
        folder_row.addWidget(btn_browse)
        adv_lay.addLayout(folder_row)

        found = sync.detect_drive_folders()
        if found:
            hint = QLabel("נמצאו תיקיות Drive: " + "  |  ".join(found[:3]))
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#475569; font-size:11.5px;")
            adv_lay.addWidget(hint)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("שם המחשב הזה:"))
        self.name_edit = QLineEdit(sync.device_name())
        self.name_edit.setPlaceholderText("למשל: בית / נקודת החלוקה")
        name_row.addWidget(self.name_edit, 1)
        adv_lay.addLayout(name_row)

        self.btn_enable = QPushButton("הפעל סנכרון (ידני)")
        self.btn_enable.setObjectName("primary")
        self.btn_enable.clicked.connect(self._enable)
        adv_lay.addWidget(self.btn_enable)

        self.adv.setVisible(False)
        outer.addWidget(self.adv)

        # ── Footer buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()
        if sync.is_enabled():
            btn_disable = QPushButton("כבה סנכרון")
            btn_disable.setObjectName("danger")
            btn_disable.clicked.connect(self._disable)
            btns.addWidget(btn_disable)
        btn_close = QPushButton("סגור")
        btn_close.setObjectName("neutral")
        btn_close.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_close)
        outer.addLayout(btns)

    def _toggle_advanced(self, on: bool):
        self.adv.setVisible(on)
        self.btn_advanced.setText(
            ("▴ " if on else "▾ ") + "אפשרויות מתקדמות (בחירת תיקייה ידנית)")
        self.adjustSize()

    def _no_drive_message(self):
        import webbrowser
        ans = QMessageBox.warning(
            self, "Google Drive לא נמצא",
            "<div dir='rtl'>לא נמצאה תיקיית <b>«Drive שלי»</b> במחשב הזה.<br><br>"
            "כדי לסנכרן צריך להתקין את <b>Google Drive למחשב</b> ולהתחבר "
            "לחשבון גוגל (אותו חשבון בשני המחשבים).<br><br>"
            "להוריד עכשיו את Google Drive למחשב?</div>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ans == QMessageBox.StandardButton.Yes:
            webbrowser.open(self.DRIVE_INSTALLER_URL)

    def _auto_enable(self):
        if not sync.drive_installed():
            self._no_drive_message()
            return
        try:
            with busy_cursor():
                res = sync.auto_setup()
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", f"הפעלת הסנכרון נכשלה:\n{e}")
            return
        if not res.get("ok"):
            self._no_drive_message()
            return
        if res.get("others", 0) == 0:
            tail = ("\n\n⚠ עדיין לא זוהה מחשב שני. זה תקין אם זהו המחשב הראשון — "
                    "הפעילו סנכרון אוטומטי גם במחשב השני (עם אותו חשבון גוגל), "
                    "והם יתחברו לבד תוך דקות.")
        else:
            tail = "\n\n✓ זוהה מחשב שני — הסנכרון מחובר."
        QMessageBox.information(
            self, "סנכרון הופעל",
            f"הסנכרון הופעל אוטומטית ✓\n\nתיקייה משותפת:\n{res.get('folder','')}\n\n"
            f"נשלחו {res.get('seeded',0)} רשומות, ונקלטו {res.get('applied',0)} "
            f"שינויים מהמחשב השני." + tail
            + "\n\nהתוכנה תסנכרן אוטומטית מעתה והלאה.")
        if self.parent() and hasattr(self.parent(), "main_win") and self.parent().main_win:
            self.parent().main_win.refresh_all()
        self.accept()

    def _browse(self):
        start = sync.get_folder() or (sync.detect_drive_folders() or [""])[0]
        path = QFileDialog.getExistingDirectory(self, "בחר תיקייה משותפת ב-Drive", start)
        if path:
            self.folder_edit.setText(path)

    def _enable(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "חסר", "בחר תיקייה משותפת תחילה.")
            return
        import os
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "תיקייה לא קיימת",
                                "התיקייה לא נמצאה. ודא ש-Google Drive מותקן ומסונכרן.")
            return
        # Guard against the #1 real-world failure: picking a per-computer *backup*
        # folder (Downloads/Desktop/Documents) that Drive never shares between
        # machines. If no second computer is present there yet AND the path looks
        # like a backup location, make the operator confirm — this is exactly the
        # case where sync silently stays disconnected.
        if sync.looks_like_backup_folder(folder) and sync.other_device_count(folder) == 0:
            ans = QMessageBox.warning(
                self, "התיקייה כנראה לא משותפת",
                "התיקייה שבחרת נמצאת ב<b>הורדות/שולחן העבודה/מסמכים</b>.<br><br>"
                "את התיקיות האלה Google Drive <b>מגבה בנפרד לכל מחשב</b> — הן "
                "<b>לא משותפות</b> בין שני המחשבים, ולכן הסנכרון לא יעבוד "
                "(כל מחשב יישאר עם הנתונים שלו).<br><br>"
                "מומלץ מאוד לבחור תיקייה בתוך <b>«Drive שלי» (My Drive)</b>.<br><br>"
                "להמשיך בכל זאת עם התיקייה הזו?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        sync.set_device_name(self.name_edit.text().strip())
        # enable_sync seeds THIS computer's data into the shared folder; run_sync
        # then pulls whatever the other computer already put there — so joining an
        # existing folder merges both directions without overwriting.
        try:
            with busy_cursor():
                n = sync.enable_sync(folder, seed=True)
                res = sync.run_sync()
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", f"הפעלת הסנכרון נכשלה:\n{e}")
            return
        others = sync.other_device_count(folder)
        if others == 0:
            tail = ("\n\n⚠ עדיין לא זוהה מחשב שני בתיקייה. זה תקין אם זהו המחשב "
                    "הראשון שמפעיל סנכרון — הפעל את המחשב השני על אותה תיקייה. "
                    "אם כבר הפעלת את השני וזה לא מזוהה — כנראה התיקייה אינה "
                    "באמת משותפת (בדוק שהיא בתוך «Drive שלי», לא תיקיית גיבוי).")
        else:
            tail = f"\n\n✓ זוהה מחשב שני בתיקייה — הסנכרון מחובר."
        QMessageBox.information(
            self, "סנכרון הופעל",
            f"הסנכרון הופעל ✓\nנשלחו {n} רשומות לתיקייה המשותפת, "
            f"ונקלטו {res.get('applied', 0)} שינויים מהמחשב השני."
            + tail + "\n\nהתוכנה תסנכרן אוטומטית מעתה והלאה.")
        if self.parent() and hasattr(self.parent(), "main_win") and self.parent().main_win:
            self.parent().main_win.refresh_all()
        self.accept()

    def _disable(self):
        sync.disable_sync()
        QMessageBox.information(self, "סנכרון כבוי",
                                "הסנכרון כובה במחשב זה. הנתונים נשארים כפי שהם.")
        self.accept()


class BackupListDialog(QDialog):
    """All saved backups (default %APPDATA% folder + the operator's chosen
    folder) in one table, newest first, with a 'שחזר' button on every row —
    restore in one click instead of hunting for a .db file (#69pen).
    The dialog only PICKS the file (chosen_path); the caller runs the usual
    confirm → safety backup → restore flow."""

    _KINDS = (("safety_", "לפני פעולה מסוכנת"), ("daily_", "יומי"),
              ("backup_", "אוטומטי"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("שחזור מגיבוי קודם")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(720, 520)
        self.chosen_path = ""
        lay = QVBoxLayout(self)
        intro = QLabel("כל הגיבויים השמורים, מהחדש לישן. לחץ 'שחזר' ליד הגיבוי הרצוי — "
                       "לפני השחזור נשמר גיבוי-ביטחון של המצב הנוכחי.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569; font-size:12.5px;")
        lay.addWidget(intro)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["תאריך ושעה", "סוג", "גודל", "תיקייה", ""])
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 120)
        self._table.verticalHeader().setDefaultSectionSize(44)
        lay.addWidget(self._table, 1)
        btn_close = QPushButton("סגור")
        btn_close.setObjectName("neutral")
        btn_close.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn_close)
        lay.addLayout(row)
        self._fill()

    @classmethod
    def list_backups(cls) -> list:
        """[(mtime, path, kind_label)] newest first, from every backup folder."""
        folders = [db.BACKUP_DIR]
        custom = db.get_setting("backup_folder") or ""
        if custom and os.path.isdir(custom) and os.path.normcase(
                os.path.abspath(custom)) != os.path.normcase(os.path.abspath(db.BACKUP_DIR)):
            folders.append(custom)
        out = []
        for folder in folders:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if not name.lower().endswith(".db"):
                    continue
                path = os.path.join(folder, name)
                kind = "ידני"
                for prefix, label in cls._KINDS:
                    if name.startswith(prefix):
                        kind = label
                        break
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                out.append((st.st_mtime, path, kind, st.st_size))
        out.sort(key=lambda t: t[0], reverse=True)
        return out

    def _fill(self):
        from datetime import datetime as _dt
        rows = self.list_backups()
        self._table.setRowCount(len(rows))
        for r, (mtime, path, kind, size) in enumerate(rows):
            when = _dt.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            size_txt = f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size // 1024} KB"
            folder = os.path.dirname(path)
            is_default = os.path.normcase(os.path.abspath(folder)) == os.path.normcase(
                os.path.abspath(db.BACKUP_DIR))
            folder_txt = "תיקיית התוכנה (ברירת מחדל)" if is_default else "התיקייה שנבחרה"
            for c, txt in enumerate((when, kind, size_txt, folder_txt)):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                it.setToolTip(path)
                self._table.setItem(r, c, it)
            btn = QPushButton("שחזר")
            btn.setStyleSheet(
                "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #55e2c8,"
                "stop:0.49 #16b599,stop:0.51 #109a80,stop:1 #085047); color:#fff; border:none;"
                " border-radius:8px; font-weight:800; font-size:13px; min-height:30px;"
                " max-height:30px; padding:0 18px; margin:4px 8px;}"
                "QPushButton:hover{background:#0c8a69;}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, p=path: self._pick(p))
            self._table.setCellWidget(r, 4, btn)
        if not rows:
            self._table.setRowCount(1)
            it = QTableWidgetItem("לא נמצאו גיבויים שמורים")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(0, 0, it)
            self._table.setSpan(0, 0, 1, 5)

    def _pick(self, path: str):
        self.chosen_path = path
        self.accept()

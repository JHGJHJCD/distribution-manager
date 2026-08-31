import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QMessageBox, QFileDialog, QInputDialog, QLineEdit,
    QProgressDialog, QApplication, QSpinBox, QScrollArea, QDoubleSpinBox,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QAbstractSpinBox
)

import database as db
from utils.backup import auto_backup, restore_from_backup
from utils.ui import busy_cursor, ALIGN_RIGHT, section_header, line_icon, enable_touch_scroll
from utils import updater
from utils import email_utils
from utils import sync
from version import APP_VERSION


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
        # The settings page has many sections — wrap it in a scroll area so every
        # section stays fully visible (and reachable) on shorter windows instead
        # of being squeezed/clipped.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        enable_touch_scroll(scroll)   # finger-drag scrolling on a touch screen
        content = QWidget()
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setSpacing(6)
        lay.setContentsMargins(10, 8, 10, 8)

        title = QLabel("הגדרות מערכת")
        title.setObjectName("title")
        lay.addWidget(title)

        # Two INDEPENDENT columns (not a shared-row grid): each column packs its
        # panels top-to-bottom with no gaps. A grid tied both columns' rows to the
        # same height, so the short 'גיבויים' panel left a big void beneath it next
        # to the tall weights panel, pushing 'מייל למתנדבים' way down (bug #nfp9i).
        # The 'אזור מסוכן' strip stays full-width below both columns.
        cols = QHBoxLayout()
        cols.setSpacing(8)
        right_col = QVBoxLayout(); right_col.setSpacing(8)
        left_col = QVBoxLayout(); left_col.setSpacing(8)
        cols.addLayout(right_col, 1)
        cols.addLayout(left_col, 1)
        lay.addLayout(cols)
        _AT = Qt.AlignmentFlag.AlignTop   # (retained for compatibility)

        # ── Security section ──────────────────────────────
        sec_frame = QFrame()
        sec_frame.setObjectName("panel")
        sec_lay = QVBoxLayout(sec_frame)
        sec_lay.setContentsMargins(10, 7, 10, 7)
        sec_lay.setSpacing(6)

        sec_lay.addWidget(section_header("אבטחה", "security", "#0f766e"))

        pwd_row = QHBoxLayout()
        self.lbl_password = QLabel("••••")
        self.lbl_password.setStyleSheet("color:#6b7280; letter-spacing:2px; font-size:15px;")
        pwd_row.addWidget(QLabel("סיסמה נוכחית:"))
        pwd_row.addWidget(self.lbl_password)
        pwd_row.addStretch()
        btn_pwd = QPushButton("שנה סיסמה")
        btn_pwd.setObjectName("neutral")
        btn_pwd.setToolTip("שנה את סיסמת הכניסה לאפליקציה")
        btn_pwd.clicked.connect(self._change_password)
        pwd_row.addWidget(btn_pwd)
        sec_lay.addLayout(pwd_row)
        right_col.addWidget(sec_frame)

        # ── General (v2.60): UI font size + no-show alert threshold ────────────
        gen_frame = QFrame()
        gen_frame.setObjectName("panel")
        gen_lay = QVBoxLayout(gen_frame)
        gen_lay.setContentsMargins(10, 7, 10, 7)
        gen_lay.setSpacing(6)
        gen_lay.addWidget(section_header("כללי", "doc", "#0f766e"))

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("גודל הטקסט בתוכנה:"))
        # v2.80 (#x2yn5): percent-based, applied INSTANTLY to the whole app.
        self.font_spin = QSpinBox()
        self.font_spin.setRange(80, 150)
        self.font_spin.setSingleStep(5)
        self.font_spin.setSuffix(" %")
        self.font_spin.setMinimumWidth(90)
        self.font_spin.setValue(db.get_ui_font_percent())
        self.font_spin.setToolTip("מגדיל או מקטין את הטקסט בכל התוכנה מיידית "
                                  "(100% = הגודל הרגיל)")
        from PyQt6.QtCore import QTimer
        self._font_apply_timer = QTimer(self)
        self._font_apply_timer.setSingleShot(True)
        self._font_apply_timer.setInterval(250)
        self._font_apply_timer.timeout.connect(self._apply_font_percent)
        self.font_spin.valueChanged.connect(
            lambda *_: self._font_apply_timer.start())
        font_row.addWidget(self.font_spin)
        font_row.addStretch()
        gen_lay.addLayout(font_row)

        ns_row = QHBoxLayout()
        ns_row.addWidget(QLabel("התראה על מי שלא הגיע — אחרי:"))
        self.no_show_spin = QSpinBox()
        self.no_show_spin.setRange(0, 20)
        self.no_show_spin.setSuffix(" פעמים ברצף")
        self.no_show_spin.setMinimumWidth(140)
        try:
            self.no_show_spin.setValue(db.get_no_show_threshold())
        except Exception:
            self.no_show_spin.setValue(3)
        self.no_show_spin.setToolTip(
            "מי שנרשם לו \"לא הגיע\" כך-וכך פעמים ברצף יסומן באדום ברשימת החלוקה "
            "ובכרטיס המקבל. 0 = בלי התראות.")
        self.no_show_spin.valueChanged.connect(
            lambda v: db.set_setting("no_show_alert_threshold", str(v)))
        ns_row.addWidget(self.no_show_spin)
        ns_row.addStretch()
        gen_lay.addLayout(ns_row)
        right_col.addWidget(gen_frame)

        # ── Software update section ───────────────────────
        upd_frame = QFrame()
        upd_frame.setObjectName("panel")
        upd_lay = QVBoxLayout(upd_frame)
        upd_lay.setContentsMargins(10, 7, 10, 7)
        upd_lay.setSpacing(6)

        upd_lay.addWidget(section_header("עדכון תוכנה", "update", "#0f766e"))

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("גרסה נוכחית:"))
        self.lbl_version = QLabel(f"v{APP_VERSION}")
        self.lbl_version.setStyleSheet("font-weight:700; color:#334155;")
        ver_row.addWidget(self.lbl_version)
        ver_row.addStretch()
        self.btn_check_update = QPushButton("בדוק עדכונים")
        self.btn_check_update.setObjectName("neutral")
        self.btn_check_update.setToolTip("בדוק אם קיימת גרסה חדשה יותר ב-GitHub")
        self.btn_check_update.clicked.connect(self._check_updates)
        ver_row.addWidget(self.btn_check_update)
        upd_lay.addLayout(ver_row)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setObjectName("subtitle")
        self.lbl_update_status.setWordWrap(True)
        upd_lay.addWidget(self.lbl_update_status)
        left_col.addWidget(upd_frame)

        # ── Need-score weights section ────────────────────
        w_frame = QFrame()
        w_frame.setObjectName("panel")
        w_lay = QVBoxLayout(w_frame)
        w_lay.setContentsMargins(10, 7, 10, 7)
        w_lay.setSpacing(6)

        w_lay.addWidget(section_header("משקלי ניקוד עדיפות", "weights", "#0f766e"))

        w_desc = QLabel(
            "קביעת המשקל של כל נתון בחישוב 'ניקוד הצורך' שלפיו מדורגים המקבלים "
            "בלשונית \"חד פעמי\". המשקלים הם אחוזים שמסתכמים תמיד ל-100% — "
            "הגדלת אחד מקטינה אוטומטית את האחרים. 0% = להתעלם מהנתון.")
        w_desc.setObjectName("subtitle")
        w_desc.setWordWrap(True)
        w_lay.addWidget(w_desc)

        w_form = QFormLayout()
        w_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        w_form.setSpacing(6)
        self._balancing = False
        self._weight_spins = {}
        for f in db.NEED_FACTORS:
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix("%")
            spin.setFixedWidth(90)
            spin.valueChanged.connect(lambda _v, k=f["key"]: self._rebalance(k))
            self._weight_spins[f["key"]] = spin
            w_form.addRow(f["label"] + ":", spin)
        w_lay.addLayout(w_form)

        self.lbl_weight_preview = QLabel("")
        self.lbl_weight_preview.setObjectName("subtitle")
        self.lbl_weight_preview.setWordWrap(True)
        w_lay.addWidget(self.lbl_weight_preview)

        w_btns = QHBoxLayout()
        btn_save_w = QPushButton("שמור משקלים")
        btn_save_w.setObjectName("primary")
        btn_save_w.setToolTip("שמור את המשקלים וחשב מחדש את ניקוד העדיפות")
        btn_save_w.clicked.connect(self._save_weights)
        w_btns.addWidget(btn_save_w)
        btn_reset_w = QPushButton("אפס לברירת מחדל")
        btn_reset_w.setObjectName("neutral")
        btn_reset_w.clicked.connect(self._reset_weights)
        w_btns.addWidget(btn_reset_w)
        w_btns.addStretch()
        w_lay.addLayout(w_btns)
        left_col.addWidget(w_frame)

        # ── Backup section ────────────────────────────────
        bk_frame = QFrame()
        bk_frame.setObjectName("panel")
        bk_lay = QVBoxLayout(bk_frame)
        bk_lay.setContentsMargins(10, 7, 10, 7)
        bk_lay.setSpacing(6)

        bk_lay.addWidget(section_header("גיבויים", "backup", "#0f766e"))

        bk_desc = QLabel(
            "<b>מה זה?</b> גיבוי הוא צילום מלא של כל הנתונים שלך — כל המקבלים, כל "
            "החלוקות שנרשמו, וכל ההגדרות — בקובץ אחד.<br>"
            "<b>מתי זה מציל אותך?</b> אם המחשב נשבר או נגנב, אם הנתונים נמחקו או "
            "השתבשו בטעות, או כשעוברים למחשב חדש — אפשר לשחזר הכול חזרה מגיבוי.<br>"
            "<b>אוטומטי:</b> התוכנה מגבה לבד בכל פתיחה ולפני כל פעולה מסוכנת. "
            "כאן אפשר גם לשמור עותק לתיקייה שתבחר (למשל כונן חיצוני / דיסק-און-קי), "
            "לגבות ידנית עכשיו, או לשחזר מקובץ גיבוי.")
        bk_desc.setObjectName("subtitle")
        bk_desc.setTextFormat(Qt.TextFormat.RichText)
        bk_desc.setWordWrap(True)
        bk_lay.addWidget(bk_desc)

        form_bk = QFormLayout()
        form_bk.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_bk.setSpacing(6)
        form_bk.setContentsMargins(0, 0, 0, 0)

        self.lbl_backup_folder = QLabel("")
        self.lbl_backup_folder.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_backup_folder.setStyleSheet("color:#374151;")
        self.lbl_backup_folder.setWordWrap(True)

        self.lbl_last_backup = QLabel("")
        self.lbl_last_backup.setStyleSheet("color:#374151;")

        form_bk.addRow("תיקיית גיבוי:", self.lbl_backup_folder)
        form_bk.addRow("גיבוי אחרון:", self.lbl_last_backup)
        bk_lay.addLayout(form_bk)

        bk_btns = QHBoxLayout()
        bk_btns.setSpacing(6)
        btn_folder = QPushButton("בחר תיקיית גיבוי")
        btn_folder.setObjectName("neutral")
        btn_folder.setToolTip("בחר לאן לשמור עותק גיבוי נוסף (למשל כונן חיצוני)")
        btn_folder.clicked.connect(self._choose_backup_folder)
        bk_btns.addWidget(btn_folder)

        self.btn_backup_now = QPushButton("גבה עכשיו")
        self.btn_backup_now.setObjectName("primary")
        self.btn_backup_now.setToolTip("שמור עכשיו צילום מלא של כל הנתונים לתיקייה שנבחרה")
        self.btn_backup_now.clicked.connect(self._backup_now)
        bk_btns.addWidget(self.btn_backup_now)

        btn_restore = QPushButton("שחזר נתונים מגיבוי")
        btn_restore.setObjectName("neutral")
        btn_restore.setToolTip("החזר את כל הנתונים ממצב גיבוי קודם (בחר קובץ גיבוי .db)")
        btn_restore.clicked.connect(self._restore_backup)
        bk_btns.addWidget(btn_restore)

        bk_btns.addStretch()
        bk_lay.addLayout(bk_btns)
        right_col.addWidget(bk_frame)

        # ── Export folders section (#5e1jc) ───────────────────────────────────
        from utils.excel_utils import EXPORT_KINDS
        exp_frame = QFrame()
        exp_frame.setObjectName("panel")
        exp_lay = QVBoxLayout(exp_frame)
        exp_lay.setContentsMargins(10, 7, 10, 7)
        exp_lay.setSpacing(6)
        exp_lay.addWidget(section_header("תיקיות ייצוא", "download", "#0f766e"))
        exp_desc = QLabel("לאן יישמרו הקבצים שהתוכנה מייצאת. אפשר לבחור תיקייה נפרדת "
                          "לכל סוג — למשל תיקייה קבועה לכל החלוקות. ברירת המחדל: תיקיית ההורדות.")
        exp_desc.setObjectName("subtitle")
        exp_desc.setWordWrap(True)
        exp_lay.addWidget(exp_desc)

        self._export_path_lbls = {}
        for kind, label in EXPORT_KINDS:
            row = QHBoxLayout()
            row.setSpacing(6)
            name_lbl = QLabel(label + ":")
            name_lbl.setMinimumWidth(150)
            name_lbl.setStyleSheet("font-weight:600; color:#334155;")
            row.addWidget(name_lbl)
            path_lbl = QLabel("")
            path_lbl.setStyleSheet("color:#475569;")
            path_lbl.setWordWrap(True)
            self._export_path_lbls[kind] = path_lbl
            row.addWidget(path_lbl, 1)
            btn_pick = QPushButton("בחר")
            btn_pick.setObjectName("neutral")
            btn_pick.clicked.connect(lambda _=False, k=kind: self._choose_export_dir(k))
            row.addWidget(btn_pick)
            btn_reset = QPushButton("ברירת מחדל")
            btn_reset.setObjectName("neutral")
            btn_reset.setToolTip("החזר לתיקיית ההורדות")
            btn_reset.clicked.connect(lambda _=False, k=kind: self._reset_export_dir(k))
            row.addWidget(btn_reset)
            exp_lay.addLayout(row)
        right_col.addWidget(exp_frame)
        self._refresh_export_labels()

        # ── Danger zone section ───────────────────────────
        danger_frame = QFrame()
        danger_frame.setObjectName("panel")
        danger_frame.setStyleSheet(
            "QFrame#panel { border: 1.5px solid #fca5a5; }"
        )
        danger_lay = QVBoxLayout(danger_frame)
        danger_lay.setContentsMargins(10, 7, 10, 7)
        danger_lay.setSpacing(6)

        danger_lay.addWidget(section_header(
            "אזור מסוכן", "danger", "#dc2626",
            text_color="#dc2626", line_color="#fca5a5"))

        danger_desc = QLabel("מחיקת כל הנתונים — פעולה בלתי הפיכה. הגדרות המערכת (סיסמה, תיקיית גיבוי) נשמרות.")
        danger_desc.setObjectName("subtitle")
        danger_desc.setWordWrap(True)
        danger_lay.addWidget(danger_desc)

        danger_btns = QHBoxLayout()
        btn_reset = QPushButton("אפס את כל הנתונים")
        btn_reset.setObjectName("danger")
        btn_reset.setToolTip("מוחק את כל המקבלים, ההיסטוריה ויומן השינויים")
        btn_reset.clicked.connect(self._reset_data)
        danger_btns.addWidget(btn_reset)
        danger_btns.addStretch()
        danger_lay.addLayout(danger_btns)
        # Placed in the right column, under 'מייל למתנדבים' (#nbbwj) — half-width and
        # compact instead of a full-width strip. The actual addWidget happens after
        # mail_frame is built, below.

        # ── Volunteer email section ────────────────────────
        mail_frame = QFrame()
        mail_frame.setObjectName("panel")
        mail_lay = QVBoxLayout(mail_frame)
        mail_lay.setContentsMargins(10, 7, 10, 7)
        mail_lay.setSpacing(6)

        mail_lay.addWidget(section_header("מייל למתנדבים", "mail", "#0f766e"))

        mail_desc = QLabel(
            "משמש לשליחת רשימת חלוקה למתנדב, ולקליטה אוטומטית של התוצאות שהוא שולח "
            "בחזרה במייל (לשונית \"חלוקה ורישום\"). "
            "ב-Gmail: הגדרות חשבון Google ← אבטחה ← אימות דו-שלבי ← סיסמאות אפליקציה.")
        mail_desc.setObjectName("subtitle")
        mail_desc.setWordWrap(True)
        mail_lay.addWidget(mail_desc)

        # Helpful links for the one-time Gmail setup (2FA → authenticator → app
        # password). External links open in the browser.
        mail_links = QLabel(
            "הגדרה חד-פעמית ב-Gmail (לפי הסדר):<br>"
            "1. <a href=\"https://authenticator.cc/\">התקנת אפליקציית מאמת (Authenticator)</a><br>"
            "2. <a href=\"https://myaccount.google.com/signinoptions/two-step-verification?hl=he\">"
            "הפעלת אימות דו-שלבי</a> "
            "<span style=\"color:#b45309;\">— חשוב! בעת ההפעלה הורידו את קודי הגיבוי "
            "ושמרו אותם במקום בטוח</span><br>"
            "3. <a href=\"https://myaccount.google.com/apppasswords\">הפקת סיסמת אפליקציה</a>")
        mail_links.setTextFormat(Qt.TextFormat.RichText)
        mail_links.setOpenExternalLinks(True)
        mail_links.setWordWrap(True)
        mail_links.setStyleSheet("font-size:12px;")
        mail_lay.addWidget(mail_links)

        mail_warn_row = QHBoxLayout()
        mail_warn_row.setContentsMargins(0, 0, 0, 0)
        mail_warn_row.setSpacing(6)
        warn_ic = QLabel()
        warn_ic.setPixmap(line_icon("danger", 16, "#b45309"))
        warn_ic.setStyleSheet("background:transparent; border:none;")
        warn_ic.setFixedWidth(18)
        mail_warn_row.addWidget(warn_ic, 0, Qt.AlignmentFlag.AlignTop)
        mail_warn = QLabel(
            "אזהרה: אל תשנה הגדרות אבטחה בחשבון Google (אימות דו-שלבי / סיסמאות אפליקציה) "
            "בלי להתייעץ עם מישהו שמבין בכך. שינוי שגוי עלול לחסום את הכניסה לחשבון.")
        mail_warn.setWordWrap(True)
        mail_warn.setStyleSheet("color:#b45309; font-size:12px; font-weight:600; "
                                "background:#fffbeb; border:1px solid #fde68a; "
                                "border-radius:6px; padding:6px 8px;")
        mail_warn_row.addWidget(mail_warn, 1)
        mail_lay.addLayout(mail_warn_row)

        mail_form = QFormLayout()
        mail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mail_form.setSpacing(6)
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
        mail_form.addRow("כתובת שולח:", self.mail_email)
        mail_form.addRow("סיסמת אפליקציה:", self.mail_password)
        mail_form.addRow("סיסמה לקובץ המתנדב:", self.mail_file_pw)
        mail_lay.addLayout(mail_form)

        mail_file_pw_hint = QLabel(
            "הקובץ המצורף למתנדב יינעל בסיסמה זו (צריך אותה כדי לפתוח ב-Excel). "
            "הסיסמה לא נכתבת במייל — מסרו אותה למתנדב פעם אחת בעל-פה / בווטסאפ. "
            "השאר ריק כדי לא להגן על הקובץ.")
        mail_file_pw_hint.setObjectName("subtitle")
        mail_file_pw_hint.setWordWrap(True)
        mail_file_pw_hint.setStyleSheet("font-size:11px;")
        mail_lay.addWidget(mail_file_pw_hint)

        mail_btns = QHBoxLayout()
        btn_mail_save = QPushButton("שמור")
        btn_mail_save.setObjectName("primary")
        btn_mail_save.clicked.connect(self._save_mail_settings)
        mail_btns.addWidget(btn_mail_save)
        btn_mail_test = QPushButton("שלח מייל בדיקה")
        btn_mail_test.setObjectName("neutral")
        btn_mail_test.clicked.connect(self._test_mail_settings)
        mail_btns.addWidget(btn_mail_test)
        mail_btns.addStretch()
        mail_lay.addLayout(mail_btns)

        self.lbl_mail_status = QLabel("")
        self.lbl_mail_status.setObjectName("subtitle")
        self.lbl_mail_status.setWordWrap(True)
        mail_lay.addWidget(self.lbl_mail_status)
        right_col.addWidget(mail_frame)
        right_col.addWidget(danger_frame)   # 'אזור מסוכן' — half-width, under the mail panel (#nbbwj)

        # ── Organization / branding section ───────────────────
        # Makes the app charity-agnostic: the name shown on the top bar is data,
        # not a hardcoded string, so the same program fits any tzedaka fund.
        org_frame = QFrame()
        org_frame.setObjectName("panel")
        org_lay = QVBoxLayout(org_frame)
        org_lay.setContentsMargins(10, 7, 10, 7)
        org_lay.setSpacing(6)
        org_lay.addWidget(section_header("שם הארגון (סרגל עליון)", "org", "#0f766e"))
        org_desc = QLabel("הכיתוב שמופיע בראש התוכנה. שנה אותו כדי להתאים לכל קופת צדקה.")
        org_desc.setObjectName("subtitle")
        org_desc.setWordWrap(True)
        org_lay.addWidget(org_desc)

        org_form = QFormLayout()
        org_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        org_form.setSpacing(6)
        self.org_title = QLineEdit()
        self.org_title.setPlaceholderText("מנהל חלוקה")
        self.org_title.setAlignment(ALIGN_RIGHT)
        self.org_subtitle = QLineEdit()
        self.org_subtitle.setPlaceholderText("שם הקופה · יישוב")
        self.org_subtitle.setAlignment(ALIGN_RIGHT)
        org_form.addRow("כותרת:", self.org_title)
        org_form.addRow("כותרת משנה:", self.org_subtitle)
        org_lay.addLayout(org_form)

        # Logo row: pick an image file → copied into the data dir and shown live.
        logo_row = QHBoxLayout()
        logo_row.setSpacing(6)
        logo_lbl = QLabel("לוגו:")
        logo_row.addWidget(logo_lbl)
        self.lbl_logo_status = QLabel("")
        self.lbl_logo_status.setObjectName("subtitle")
        logo_row.addWidget(self.lbl_logo_status, 1)
        btn_logo = QPushButton("החלף לוגו…")
        btn_logo.setObjectName("neutral")
        btn_logo.clicked.connect(self._choose_logo)
        logo_row.addWidget(btn_logo)
        self.btn_logo_reset = QPushButton("אפס")
        self.btn_logo_reset.setObjectName("neutral")
        self.btn_logo_reset.clicked.connect(self._reset_logo)
        logo_row.addWidget(self.btn_logo_reset)
        org_lay.addLayout(logo_row)

        org_btns = QHBoxLayout()
        btn_org_save = QPushButton("שמור")
        btn_org_save.setObjectName("primary")
        btn_org_save.clicked.connect(self._save_branding)
        org_btns.addWidget(btn_org_save)
        org_btns.addStretch()
        org_lay.addLayout(org_btns)
        left_col.addWidget(org_frame)

        # ── Community balance percentages (#lejmr) ────────────────────────────
        comm_frame = QFrame()
        comm_frame.setObjectName("panel")
        comm_lay = QVBoxLayout(comm_frame)
        comm_lay.setContentsMargins(10, 7, 10, 7)
        comm_lay.setSpacing(6)
        comm_lay.addWidget(section_header("איזון קהילות", "users", "#0f766e"))
        comm_info = QLabel(
            "כשמחלקים לפי סינון מותאם עם 'איזון בין קהילות', כל קהילה מקבלת "
            "חלק יחסי לגודלה. כאן אפשר לקבוע ידנית אחוז קבוע לקהילה מסוימת "
            "(השאר יחולק יחסית בין הקהילות הנותרות).")
        comm_info.setWordWrap(True)
        comm_info.setStyleSheet("color:#475569; font-size:12px;")
        comm_lay.addWidget(comm_info)
        btn_comm = QPushButton("כוונון אחוזים לקהילות…")
        btn_comm.setObjectName("neutral")
        btn_comm.clicked.connect(self._open_community_quotas)
        comm_lay.addWidget(btn_comm, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(comm_frame)

        # ── Two-computer sync (Google Drive) — v2.61 ──────────────────────────
        sync_frame = QFrame()
        sync_frame.setObjectName("panel")
        sync_lay = QVBoxLayout(sync_frame)
        sync_lay.setContentsMargins(10, 7, 10, 7)
        sync_lay.setSpacing(6)
        sync_lay.addWidget(section_header("סנכרון בין שני מחשבים", "update", "#0f766e"))
        # Visual status card (v2.80, #n02fc): colored dot + headline + stat chips
        # instead of a static block of text lines.
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.sync_dot = QLabel("")
        self.sync_dot.setFixedSize(14, 14)
        head_row.addWidget(self.sync_dot)
        self.sync_headline = QLabel("")
        self.sync_headline.setStyleSheet("font-size:13.5px; font-weight:700;")
        head_row.addWidget(self.sync_headline)
        head_row.addStretch()
        sync_lay.addLayout(head_row)
        self.sync_chips_lay = QHBoxLayout()
        self.sync_chips_lay.setSpacing(6)
        self.sync_chips_lay.addStretch()
        sync_lay.addLayout(self.sync_chips_lay)
        self.lbl_sync_folder = QLabel("")
        self.lbl_sync_folder.setWordWrap(True)
        self.lbl_sync_folder.setStyleSheet("color:#64748b; font-size:11.5px;")
        sync_lay.addWidget(self.lbl_sync_folder)
        # Sync runs continuously in the background (every 10s) — no manual
        # 'sync now' button is needed any more (#hd4as).
        sync_note = QLabel("הסנכרון פועל אוטומטית ברקע כל הזמן — אין צורך ללחוץ על כלום.")
        sync_note.setWordWrap(True)
        sync_note.setStyleSheet("color:#0f766e; font-size:12px;")
        sync_lay.addWidget(sync_note)
        sync_btns = QHBoxLayout()
        self.btn_sync_setup = QPushButton("הגדרת סנכרון…")
        self.btn_sync_setup.setObjectName("primary")
        self.btn_sync_setup.clicked.connect(self._open_sync_setup)
        sync_btns.addWidget(self.btn_sync_setup)
        sync_btns.addStretch()
        sync_lay.addLayout(sync_btns)
        left_col.addWidget(sync_frame)
        self._refresh_sync_status()

        # ── Manager computer + change control (#5rhe9) ────────────────────────
        mgr_frame = QFrame()
        mgr_frame.setObjectName("panel")
        mgr_lay = QVBoxLayout(mgr_frame)
        mgr_lay.setContentsMargins(10, 7, 10, 7)
        mgr_lay.setSpacing(6)
        mgr_lay.addWidget(section_header("מחשב מנהל ובקרת שינויים", "security", "#0f766e"))
        mgr_desc = QLabel(
            "אפשר להגדיר מחשב אחד כ<b>מחשב המנהל</b>. במחשב המנהל מופיע <b>יומן "
            "שינויים</b> שמראה כל שינוי שנקלט מהמחשב השני (מי/מה/מתי), עם אפשרות "
            "<b>לבטל</b> שינוי ולהחזיר את המצב הקודם — כך המנהל שולט בנתוני האמת. "
            "הגדרת מחשב כמנהל מוגנת בקוד.")
        mgr_desc.setObjectName("subtitle")
        mgr_desc.setTextFormat(Qt.TextFormat.RichText)
        mgr_desc.setWordWrap(True)
        mgr_lay.addWidget(mgr_desc)
        self.lbl_mgr_status = QLabel("")
        self.lbl_mgr_status.setWordWrap(True)
        self.lbl_mgr_status.setStyleSheet("font-size:12.5px;")
        mgr_lay.addWidget(self.lbl_mgr_status)
        mgr_btns = QHBoxLayout()
        self.btn_mgr_toggle = QPushButton("")
        self.btn_mgr_toggle.setObjectName("primary")
        self.btn_mgr_toggle.clicked.connect(self._toggle_manager)
        mgr_btns.addWidget(self.btn_mgr_toggle)
        self.btn_mgr_log = QPushButton("יומן שינויים…")
        self.btn_mgr_log.setObjectName("neutral")
        self.btn_mgr_log.clicked.connect(self._open_manager_log)
        mgr_btns.addWidget(self.btn_mgr_log)
        mgr_btns.addStretch()
        mgr_lay.addLayout(mgr_btns)
        left_col.addWidget(mgr_frame)
        self._refresh_manager_status()

        # ── Tzintukim — Yemot HaMashiach credentials (v2.81) ──────────────────
        ym_frame = QFrame()
        ym_frame.setObjectName("panel")
        ym_lay = QVBoxLayout(ym_frame)
        ym_lay.setContentsMargins(10, 7, 10, 7)
        ym_lay.setSpacing(6)
        ym_lay.addWidget(section_header("צינתוקים (ימות המשיח)", "phone", "#0f766e"))
        ym_desc = QLabel(
            "חיבור למערכת הטלפונית של ימות המשיח — לשליחת הודעה קולית לזכאי "
            "החלוקה מתוך לשונית \"צינתוקים\". הזן את מספר המערכת (077…) ואת "
            "הסיסמה של ימות, ולחץ \"בדוק חיבור\".")
        ym_desc.setObjectName("subtitle")
        ym_desc.setWordWrap(True)
        ym_lay.addWidget(ym_desc)
        ym_form = QFormLayout()
        ym_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        ym_form.setSpacing(6)
        self.ym_system = QLineEdit()
        self.ym_system.setPlaceholderText("למשל 0773137770")
        self.ym_system.setAlignment(ALIGN_RIGHT)
        self.ym_system.setText(db.get_setting("yemot_system") or "")
        self.ym_password = QLineEdit()
        self.ym_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ym_password.setPlaceholderText("הסיסמה של המערכת בימות")
        self.ym_password.setAlignment(ALIGN_RIGHT)
        self.ym_password.setText(db.get_setting("yemot_password") or "")
        self.ym_test_phone = QLineEdit()
        self.ym_test_phone.setPlaceholderText("המספר שלך — לצינתוק ניסיון")
        self.ym_test_phone.setAlignment(ALIGN_RIGHT)
        self.ym_test_phone.setText(db.get_setting("yemot_test_phone") or "")
        ym_form.addRow("מספר מערכת:", self.ym_system)
        ym_form.addRow("סיסמה:", self.ym_password)
        ym_form.addRow("מספר לבדיקות:", self.ym_test_phone)
        ym_lay.addLayout(ym_form)
        ym_btns = QHBoxLayout()
        btn_ym_save = QPushButton("שמור")
        btn_ym_save.setObjectName("primary")
        btn_ym_save.clicked.connect(self._save_yemot_settings)
        ym_btns.addWidget(btn_ym_save)
        btn_ym_test = QPushButton("בדוק חיבור")
        btn_ym_test.setObjectName("neutral")
        btn_ym_test.setToolTip("מתחבר לימות המשיח ומוודא שהפרטים נכונים")
        btn_ym_test.clicked.connect(self._test_yemot_connection)
        ym_btns.addWidget(btn_ym_test)
        ym_btns.addStretch()
        ym_lay.addLayout(ym_btns)
        self.lbl_ym_status = QLabel("")
        self.lbl_ym_status.setObjectName("subtitle")
        self.lbl_ym_status.setWordWrap(True)
        ym_lay.addWidget(self.lbl_ym_status)
        left_col.addWidget(ym_frame)

        # Trailing stretch keeps each column's panels packed to the top so the
        # shorter column doesn't stretch its panels to fill the taller one.
        right_col.addStretch()
        left_col.addStretch()

        # ── Bottom row: feedback ──────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        # A second, easy-to-find entry point to the feedback dialog (the small
        # one lives in the status bar; users look for it here in Settings).
        self.btn_feedback = QPushButton("✉ השאר הודעה למפתח")
        self.btn_feedback.setObjectName("primary")
        self.btn_feedback.setToolTip("דווח על בעיה או השאר בקשה — נשלח למפתח")
        self.btn_feedback.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_feedback.clicked.connect(self._open_feedback)
        bottom_row.addWidget(self.btn_feedback)
        # v2.80 (#ce6a0): the operator can review every message INSIDE the app —
        # from both computers — copy it, and mark it handled. No GitHub needed.
        self.btn_feedback_inbox = QPushButton("📥 הודעות שנשלחו")
        self.btn_feedback_inbox.setObjectName("neutral")
        self.btn_feedback_inbox.setToolTip(
            "כל ההודעות שנשלחו למפתח משני המחשבים — צפייה, העתקה וסימון כטופל")
        self.btn_feedback_inbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_feedback_inbox.clicked.connect(self._open_feedback_inbox)
        bottom_row.addWidget(self.btn_feedback_inbox)
        self._refresh_feedback_inbox_btn()
        bottom_row.addStretch()
        # (The manual "רענן" button was removed — the settings screen reloads
        # itself every time the tab is opened, so it served no purpose.)
        lay.addLayout(bottom_row)
        lay.addStretch()

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

    def _restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ גיבוי", "", "קבצי גיבוי (*.db);;הכל (*.*)"
        )
        if not path:
            return

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
        confirm, ok = QInputDialog.getText(
            self, "אפוס נתונים",
            "פעולה זו תמחק את כל המקבלים וההיסטוריה לצמיתות.\n\n"
            "הקלד   אפס   לאישור:",
            QLineEdit.EchoMode.Normal
        )
        if not ok or confirm.strip() != "אפס":
            return

        # Safety backup before wiping — abort if it cannot be made.
        if not self._ensure_safety_backup():
            return

        with busy_cursor():
            db.reset_all_data()
            if self.main_win:
                self.main_win.refresh_all()
        QMessageBox.information(self, "אופס הושלם", "כל הנתונים נמחקו. הגדרות המערכת נשמרו.")

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
            f"background-color:{bg}; color:{fg}; border-radius:10px; "
            "padding:3px 10px; font-size:12px; font-weight:600;")
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
        if self.main_win and hasattr(self.main_win, "_refresh_sync_led"):
            self.main_win._refresh_sync_led()

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
        test_phone = self.ym_test_phone.text().strip()
        if not silent and (not system or not password):
            QMessageBox.warning(self, "", "יש למלא מספר מערכת וסיסמה של ימות המשיח.")
            return
        db.set_setting(yemot.SET_SYSTEM, system)
        db.set_setting(yemot.SET_PASSWORD, password)
        db.set_setting(yemot.SET_TEST_PHONE, test_phone)
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
        QMessageBox.information(
            self, "מתעדכן",
            "העדכון הותקן בהצלחה.\nהתוכנה תיסגר כעת ותיפתח מחדש בגרסה החדשה.")
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

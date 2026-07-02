from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QMessageBox, QFileDialog, QInputDialog, QLineEdit,
    QProgressDialog, QApplication, QSpinBox, QScrollArea
)

import database as db
from utils.backup import auto_backup, restore_from_backup
from utils.ui import busy_cursor
from utils import updater
from utils import email_utils
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
        content = QWidget()
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setSpacing(6)
        lay.setContentsMargins(10, 8, 10, 8)

        title = QLabel("הגדרות מערכת")
        title.setObjectName("title")
        lay.addWidget(title)

        # Two-column block layout — compact, instead of full-width rows.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        _AT = Qt.AlignmentFlag.AlignTop   # blocks sit at the top of their cell

        # ── Security section ──────────────────────────────
        sec_frame = QFrame()
        sec_frame.setObjectName("panel")
        sec_lay = QVBoxLayout(sec_frame)
        sec_lay.setContentsMargins(10, 7, 10, 7)
        sec_lay.setSpacing(6)

        sec_title = QLabel("אבטחה")
        sec_title.setObjectName("section-header")
        sec_lay.addWidget(sec_title)

        pwd_row = QHBoxLayout()
        self.lbl_password = QLabel("●●●●●●●●")
        self.lbl_password.setStyleSheet("color:#6b7280; letter-spacing:3px; font-size:14px;")
        pwd_row.addWidget(QLabel("סיסמה נוכחית:"))
        pwd_row.addWidget(self.lbl_password)
        pwd_row.addStretch()
        btn_pwd = QPushButton("שנה סיסמה")
        btn_pwd.setObjectName("neutral")
        btn_pwd.setToolTip("שנה את סיסמת הכניסה לאפליקציה")
        btn_pwd.clicked.connect(self._change_password)
        pwd_row.addWidget(btn_pwd)
        sec_lay.addLayout(pwd_row)
        grid.addWidget(sec_frame, 0, 0, _AT)

        # ── Software update section ───────────────────────
        upd_frame = QFrame()
        upd_frame.setObjectName("panel")
        upd_lay = QVBoxLayout(upd_frame)
        upd_lay.setContentsMargins(10, 7, 10, 7)
        upd_lay.setSpacing(6)

        upd_title = QLabel("עדכון תוכנה")
        upd_title.setObjectName("section-header")
        upd_lay.addWidget(upd_title)

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("גרסה נוכחית:"))
        self.lbl_version = QLabel(f"v{APP_VERSION}")
        self.lbl_version.setStyleSheet("font-weight:700; color:#1565c0;")
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
        grid.addWidget(upd_frame, 0, 1, _AT)

        # ── Need-score weights section ────────────────────
        w_frame = QFrame()
        w_frame.setObjectName("panel")
        w_lay = QVBoxLayout(w_frame)
        w_lay.setContentsMargins(10, 7, 10, 7)
        w_lay.setSpacing(6)

        w_title = QLabel("משקלי ניקוד עדיפות")
        w_title.setObjectName("section-header")
        w_lay.addWidget(w_title)

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
        grid.addWidget(w_frame, 2, 0, _AT)

        # ── Backup section ────────────────────────────────
        bk_frame = QFrame()
        bk_frame.setObjectName("panel")
        bk_lay = QVBoxLayout(bk_frame)
        bk_lay.setContentsMargins(10, 7, 10, 7)
        bk_lay.setSpacing(6)

        bk_title = QLabel("גיבויים")
        bk_title.setObjectName("section-header")
        bk_lay.addWidget(bk_title)

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
        btn_folder = QPushButton("בחר תיקייה")
        btn_folder.setObjectName("neutral")
        btn_folder.setToolTip("בחר את תיקיית הגיבוי האוטומטי")
        btn_folder.clicked.connect(self._choose_backup_folder)
        bk_btns.addWidget(btn_folder)

        self.btn_backup_now = QPushButton("גבה עכשיו")
        self.btn_backup_now.setObjectName("primary")
        self.btn_backup_now.setToolTip("בצע גיבוי ידני מיידי לתיקייה שנבחרה")
        self.btn_backup_now.clicked.connect(self._backup_now)
        bk_btns.addWidget(self.btn_backup_now)

        btn_restore = QPushButton("שחזר מגיבוי")
        btn_restore.setObjectName("neutral")
        btn_restore.setToolTip("בחר קובץ גיבוי (.db) ושחזר ממנו את כל הנתונים")
        btn_restore.clicked.connect(self._restore_backup)
        bk_btns.addWidget(btn_restore)

        bk_btns.addStretch()
        bk_lay.addLayout(bk_btns)
        grid.addWidget(bk_frame, 1, 0, _AT)

        # ── Danger zone section ───────────────────────────
        danger_frame = QFrame()
        danger_frame.setObjectName("panel")
        danger_frame.setStyleSheet(
            "QFrame#panel { border: 1.5px solid #fca5a5; }"
        )
        danger_lay = QVBoxLayout(danger_frame)
        danger_lay.setContentsMargins(10, 7, 10, 7)
        danger_lay.setSpacing(6)

        danger_title = QLabel("⚠️ אזור מסוכן")
        danger_title.setObjectName("section-header")
        danger_title.setStyleSheet("color:#dc2626; border-bottom-color:#fca5a5;")
        danger_lay.addWidget(danger_title)

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
        grid.addWidget(danger_frame, 2, 1, _AT)

        # ── System info section ───────────────────────────
        db_frame = QFrame()
        db_frame.setObjectName("panel")
        db_lay = QFormLayout(db_frame)
        db_lay.setContentsMargins(10, 7, 10, 7)
        db_lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        db_lay.setSpacing(6)

        db_title = QLabel("מידע מערכת")
        db_title.setObjectName("section-header")
        db_lay.addRow(db_title)

        self.lbl_db_path = QLabel("")
        self.lbl_db_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_db_path.setStyleSheet("color:#6b7280; font-size:11px;")
        self.lbl_db_path.setWordWrap(True)
        db_lay.addRow("מסד נתונים:", self.lbl_db_path)
        grid.addWidget(db_frame, 1, 1, _AT)

        # ── Volunteer email section ────────────────────────
        mail_frame = QFrame()
        mail_frame.setObjectName("panel")
        mail_lay = QVBoxLayout(mail_frame)
        mail_lay.setContentsMargins(10, 7, 10, 7)
        mail_lay.setSpacing(6)

        mail_title = QLabel("מייל למתנדבים")
        mail_title.setObjectName("section-header")
        mail_lay.addWidget(mail_title)

        mail_desc = QLabel(
            "משמש לשליחה אוטומטית של רשימת חלוקה למתנדב (לשונית \"חלוקה ורישום\"). "
            "ב-Gmail: הגדרות חשבון Google ← אבטחה ← אימות דו-שלבי ← סיסמאות אפליקציה.")
        mail_desc.setObjectName("subtitle")
        mail_desc.setWordWrap(True)
        mail_lay.addWidget(mail_desc)

        mail_form = QFormLayout()
        mail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mail_form.setSpacing(6)
        self.mail_email = QLineEdit()
        self.mail_email.setPlaceholderText("your@gmail.com")
        self.mail_password = QLineEdit()
        self.mail_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.mail_password.setPlaceholderText("סיסמת אפליקציה")
        mail_form.addRow("כתובת שולח:", self.mail_email)
        mail_form.addRow("סיסמת אפליקציה:", self.mail_password)
        mail_lay.addLayout(mail_form)

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
        grid.addWidget(mail_frame, 3, 0, _AT)

        # ── Refresh ───────────────────────────────────────
        btn_refresh = QPushButton("רענן")
        btn_refresh.setObjectName("neutral")
        btn_refresh.setMaximumWidth(110)
        btn_refresh.setToolTip("טען מחדש את פרטי ההגדרות")
        btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(btn_refresh, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()

    def refresh(self):
        self.lbl_db_path.setText(db.DB_PATH)
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
                self.lbl_last_backup.setStyleSheet("color:#16a34a;")
            except ValueError:
                pass
        else:
            last_backup = "לא בוצע עדיין"
            self.lbl_last_backup.setStyleSheet("color:#9ca3af;")
        self.lbl_last_backup.setText(last_backup)

        cfg = email_utils.get_smtp_config()
        self.mail_email.setText(cfg["email"])
        self.mail_password.setText(cfg["app_password"])
        if email_utils.is_configured():
            self.lbl_mail_status.setText("מוגדר ✓")
            self.lbl_mail_status.setStyleSheet("color:#16a34a;")
        else:
            self.lbl_mail_status.setText("לא הוגדר עדיין")
            self.lbl_mail_status.setStyleSheet("color:#9ca3af;")

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
            "color:#16a34a;" if total == 100 else "color:#b45309;")

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
        result = auto_backup()
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

    def _choose_backup_folder(self):
        if self.main_win and hasattr(self.main_win, "choose_backup_folder"):
            self.main_win.choose_backup_folder()
            self.refresh()

    # ── Volunteer email settings ────────────────────────────────────────────────

    def _save_mail_settings(self):
        email = self.mail_email.text().strip()
        password = self.mail_password.text()
        if not email or not password:
            QMessageBox.warning(self, "", "יש למלא כתובת מייל וסיסמת אפליקציה.")
            return
        email_utils.set_smtp_config(email, password)
        self.refresh()
        QMessageBox.information(self, "נשמר", "הגדרות המייל נשמרו ✓")

    def _test_mail_settings(self):
        self._save_mail_settings_silent()
        with busy_cursor():
            ok, msg = email_utils.test_connection()
        if ok:
            QMessageBox.information(self, "בדיקת מייל", msg)
        else:
            QMessageBox.warning(self, "בדיקת מייל", msg)

    def _save_mail_settings_silent(self):
        email = self.mail_email.text().strip()
        password = self.mail_password.text()
        if email and password:
            email_utils.set_smtp_config(email, password)

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
            notes = (result.get("notes") or "").strip()
            if len(notes) > 300:
                notes = notes[:300] + "..."
            ask = QMessageBox.question(
                self, "עדכון זמין",
                f"גרסה חדשה זמינה: v{result['version']}\n"
                f"הגרסה שלך: v{APP_VERSION}\n\n"
                + (notes + "\n\n" if notes else "")
                + "להוריד ולהתקין עכשיו?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ask == QMessageBox.StandardButton.Yes:
                self._start_download(result)
            else:
                self.lbl_update_status.setStyleSheet("color:#b45309;")
                self.lbl_update_status.setText(f"גרסה v{result['version']} זמינה — ניתן לעדכן בכל עת.")
        else:
            self.lbl_update_status.setStyleSheet("color:#16a34a;")
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

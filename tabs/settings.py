from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QFrame, QMessageBox, QFileDialog, QInputDialog, QLineEdit,
    QProgressDialog, QApplication
)

import database as db
from utils.backup import auto_backup, restore_from_backup
from utils.ui import busy_cursor
from utils import updater
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
        lay = QVBoxLayout(self)
        lay.setSpacing(16)
        lay.setContentsMargins(16, 16, 16, 16)

        title = QLabel("הגדרות מערכת")
        title.setObjectName("title")
        lay.addWidget(title)

        # ── Security section ──────────────────────────────
        sec_frame = QFrame()
        sec_frame.setObjectName("panel")
        sec_lay = QVBoxLayout(sec_frame)
        sec_lay.setContentsMargins(14, 12, 14, 12)
        sec_lay.setSpacing(10)

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
        lay.addWidget(sec_frame)

        # ── Software update section ───────────────────────
        upd_frame = QFrame()
        upd_frame.setObjectName("panel")
        upd_lay = QVBoxLayout(upd_frame)
        upd_lay.setContentsMargins(14, 12, 14, 12)
        upd_lay.setSpacing(10)

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
        lay.addWidget(upd_frame)

        # ── Backup section ────────────────────────────────
        bk_frame = QFrame()
        bk_frame.setObjectName("panel")
        bk_lay = QVBoxLayout(bk_frame)
        bk_lay.setContentsMargins(14, 12, 14, 12)
        bk_lay.setSpacing(10)

        bk_title = QLabel("גיבויים")
        bk_title.setObjectName("section-header")
        bk_lay.addWidget(bk_title)

        form_bk = QFormLayout()
        form_bk.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_bk.setSpacing(8)
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
        bk_btns.setSpacing(8)
        btn_folder = QPushButton("בחר תיקייה")
        btn_folder.setObjectName("neutral")
        btn_folder.setToolTip("בחר את תיקיית הגיבוי האוטומטי")
        btn_folder.clicked.connect(self._choose_backup_folder)
        bk_btns.addWidget(btn_folder)

        self.btn_backup_now = QPushButton("גבה עכשיו")
        self.btn_backup_now.setObjectName("success")
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
        lay.addWidget(bk_frame)

        # ── Danger zone section ───────────────────────────
        danger_frame = QFrame()
        danger_frame.setObjectName("panel")
        danger_frame.setStyleSheet(
            "QFrame#panel { border: 1.5px solid #fca5a5; }"
        )
        danger_lay = QVBoxLayout(danger_frame)
        danger_lay.setContentsMargins(14, 12, 14, 12)
        danger_lay.setSpacing(10)

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
        lay.addWidget(danger_frame)

        # ── System info section ───────────────────────────
        db_frame = QFrame()
        db_frame.setObjectName("panel")
        db_lay = QFormLayout(db_frame)
        db_lay.setContentsMargins(14, 12, 14, 12)
        db_lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        db_lay.setSpacing(8)

        db_title = QLabel("מידע מערכת")
        db_title.setObjectName("section-header")
        db_lay.addRow(db_title)

        self.lbl_db_path = QLabel("")
        self.lbl_db_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_db_path.setStyleSheet("color:#6b7280; font-size:11px;")
        self.lbl_db_path.setWordWrap(True)
        db_lay.addRow("מסד נתונים:", self.lbl_db_path)
        lay.addWidget(db_frame)

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
        err = updater.apply_update(result)
        if err:
            QMessageBox.critical(self, "שגיאת עדכון", err)
            return
        QMessageBox.information(
            self, "מתעדכן",
            "העדכון הותקן בהצלחה.\nהתוכנה תיסגר כעת ותיפתח מחדש בגרסה החדשה.")
        QApplication.quit()

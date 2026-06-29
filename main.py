import sys
import os

# Fix working dir when running as EXE
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QWidget, QStatusBar, QFrame, QSplashScreen
)
from PyQt6.QtCore import Qt, QRect, QTimer, QEventLoop
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap, QPainter, QLinearGradient

import database as db
from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
from tabs.recipients import RecipientsTab
from tabs.group_update import GroupUpdateTab
from tabs.weekly import WeeklyTab
from tabs.one_time import OneTimeTab
from tabs.tracking import TrackingTab
from tabs.search import SearchTab
from tabs.review import ReviewTab
from tabs.settings import SettingsTab, _UpdateWorker

from version import APP_VERSION
from utils import updater


def resource_path(relative: str) -> str:
    """Resolve path for both dev mode and frozen EXE."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _load_app_fonts() -> str:
    """Register bundled fonts (fonts/*.ttf) so the UI uses a proper Hebrew
    typeface. Returns the primary family ('Rubik') if available, else 'Segoe UI'
    so the app still looks fine if the font is missing."""
    from PyQt6.QtGui import QFontDatabase
    fonts_dir = resource_path("fonts")
    primary = "Segoe UI"
    if os.path.isdir(fonts_dir):
        for fn in os.listdir(fonts_dir):
            if fn.lower().endswith((".ttf", ".otf")):
                fid = QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))
                fams = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
                if "Rubik" in fams:
                    primary = "Rubik"
    return primary


# ─── Splash screen ───────────────────────────────────────────────────────────

def _make_splash_pix(W=520, H=290) -> QPixmap:
    pix = QPixmap(W, H)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Gradient background
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0.0, QColor(21, 101, 192))
    g.setColorAt(1.0, QColor(30, 136, 229))
    p.fillRect(0, 0, W, H, g)

    # App icon
    ico = resource_path("icon.ico")
    if os.path.exists(ico):
        p.drawPixmap((W - 72) // 2, 22, QIcon(ico).pixmap(72, 72))

    # App name
    p.setPen(QColor(255, 255, 255, 255))
    f = QFont("Segoe UI", 26, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(QRect(0, 106, W, 44), Qt.AlignmentFlag.AlignCenter, "מנהל חלוקה")

    # Subtitle
    p.setPen(QColor(255, 255, 255, 185))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRect(0, 156, W, 28), Qt.AlignmentFlag.AlignCenter,
               "מערכת ניהול חלוקת מצרכים")

    # Bottom strip
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 55))
    p.drawRect(0, H - 38, W, 38)
    p.setPen(QColor(255, 255, 255, 140))
    p.setFont(QFont("Segoe UI", 9))
    p.drawText(QRect(10, H - 38, W - 20, 38),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "טוען...")
    p.drawText(QRect(10, H - 38, W - 20, 38),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
               f"גרסה {APP_VERSION}")
    p.end()
    return pix


def _show_splash(app: "QApplication") -> QSplashScreen:
    splash = QSplashScreen(_make_splash_pix(),
                           Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash


def _wait_ms(ms: int):
    """Block the event loop for ms milliseconds (keeps UI responsive)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ─── Login dialog ─────────────────────────────────────────────────────────────

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("מנהל חלוקה")
        self.setFixedSize(400, 320)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        _set_window_icon(self)

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Blue header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("login-header")
        header.setFixedHeight(118)
        header.setStyleSheet(
            "QFrame#login-header {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "    stop:0 #1565c0, stop:1 #1e88e5);"
            "  border:none;"
            "}"
        )
        h_lay = QVBoxLayout(header)
        h_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_lay.setSpacing(2)
        h_lay.setContentsMargins(0, 14, 0, 14)


        title_lbl = QLabel("מנהל חלוקה")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ft = title_lbl.font(); ft.setPointSize(17); ft.setBold(True)
        title_lbl.setFont(ft)
        title_lbl.setStyleSheet("color:white; background:transparent; border:none;")
        h_lay.addWidget(title_lbl)

        ver_lbl = QLabel(f"v{APP_VERSION}  •  מערכת ניהול חלוקת מצרכים")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(
            "color:rgba(255,255,255,0.75); background:transparent; "
            "border:none; font-size:11px;"
        )
        h_lay.addWidget(ver_lbl)

        outer.addWidget(header)

        # ── Thin accent line ─────────────────────────────────────────────────
        line = QFrame()
        line.setFixedHeight(3)
        line.setStyleSheet("background:#42a5f5; border:none;")
        outer.addWidget(line)

        # ── White body ───────────────────────────────────────────────────────
        body = QWidget()
        body.setObjectName("login-body")
        body.setStyleSheet("QWidget#login-body { background:#ffffff; }")
        b_lay = QVBoxLayout(body)
        b_lay.setSpacing(12)
        b_lay.setContentsMargins(36, 26, 36, 26)

        pwd_lbl = QLabel("סיסמה:")
        pwd_lbl.setStyleSheet(
            "color:#374151; font-weight:700; font-size:13px; "
            "background:transparent; border:none;"
        )
        b_lay.addWidget(pwd_lbl)

        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("הזן סיסמה")
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.pwd_input.setMinimumHeight(38)
        self.pwd_input.returnPressed.connect(self.try_login)
        b_lay.addWidget(self.pwd_input)

        btn = QPushButton("כניסה  ←")
        btn.setMinimumHeight(40)
        btn.setStyleSheet(
            "QPushButton{"
            "  background:#1565c0; color:white; font-weight:700;"
            "  font-size:14px; border-radius:6px; border:none;"
            "}"
            "QPushButton:hover  { background:#1976d2; }"
            "QPushButton:pressed{ background:#0d47a1; padding-top:2px; }"
        )
        btn.clicked.connect(self.try_login)
        b_lay.addWidget(btn)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            "color:#dc2626; background:transparent; font-size:12px; border:none;"
        )
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_lay.addWidget(self.error_lbl)

        outer.addWidget(body)

    def try_login(self):
        entered = self.pwd_input.text()
        if db.verify_password(entered):
            self.accept()
        else:
            self.error_lbl.setText("❌  סיסמה שגויה — נסה שוב")
            self.pwd_input.clear()
            self.pwd_input.setFocus()


# ─── Main window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"מנהל חלוקה  v{APP_VERSION}")
        self.setMinimumSize(1100, 700)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        _set_window_icon(self)

        self._build_tabs()
        self._build_statusbar()

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tabs.setMovable(True)   # tabs can be reordered by dragging

        self.group_tab      = GroupUpdateTab(self)
        self.weekly_tab     = WeeklyTab(self)
        self.recipients_tab = RecipientsTab(self)
        self.one_time_tab   = OneTimeTab(self)
        self.tracking_tab   = TrackingTab(self)
        self.search_tab     = SearchTab(self)
        self.review_tab     = ReviewTab(self)
        self.settings_tab   = SettingsTab(self)

        # (widget, label, stable key). The key — not the position — is what we
        # persist, so a saved order survives even if tabs are later added/removed.
        tab_specs = [
            (self.group_tab,      "עדכון קבוצתי",  "group"),
            (self.weekly_tab,     "חלוקה השבוע",   "weekly"),
            (self.recipients_tab, "מקבלים",        "recipients"),
            (self.one_time_tab,   "חד פעמי",       "one_time"),
            (self.tracking_tab,   "מעקב חלוקות",   "tracking"),
            (self.search_tab,     "חיפוש מהיר",    "search"),
            (self.review_tab,     "בדיקת נתונים",  "review"),
            (self.settings_tab,   "הגדרות",        "settings"),
        ]
        for widget, label, key in tab_specs:
            widget.setObjectName("tab_" + key)
            self.tabs.addTab(widget, label)

        # Tab 0 (group_update) loaded in __init__; others lazy-load on first click
        for i in range(self.tabs.count()):
            self.tabs.widget(i)._needs_refresh = (i != 0)

        self._restore_tab_order()
        # Save the new order whenever the user drags a tab.
        self.tabs.tabBar().tabMoved.connect(lambda *_: self._save_tab_order())
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        # After restoring a custom order the tab now at position 0 may not be the
        # one that self-refreshed in __init__, so refresh whatever is shown first.
        cur = self.tabs.currentWidget()
        if cur is not None and getattr(cur, "_needs_refresh", False) and hasattr(cur, "refresh"):
            cur.refresh()
            cur._needs_refresh = False

        self._apply_rtl_polish()

    def _apply_rtl_polish(self):
        """Right-align every table header so the whole UI reads consistently RTL
        (Qt centers header text by default, which looks LTR in a Hebrew app)."""
        from PyQt6.QtWidgets import QTableView
        for tv in self.findChildren(QTableView):
            tv.horizontalHeader().setDefaultAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _save_tab_order(self):
        order = [self.tabs.widget(i).objectName() for i in range(self.tabs.count())]
        db.set_setting("tab_order", ",".join(order))

    def _restore_tab_order(self):
        saved = db.get_setting("tab_order")
        if not saved:
            return
        bar = self.tabs.tabBar()
        for target_pos, key in enumerate(k for k in saved.split(",") if k):
            cur = next((i for i in range(self.tabs.count())
                        if self.tabs.widget(i).objectName() == key), None)
            if cur is not None and cur != target_pos:
                bar.moveTab(cur, target_pos)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        from datetime import date
        today    = date.today()
        days     = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        day_name = days[today.weekday()]
        sb.showMessage(f"  {day_name}, {today.strftime('%d/%m/%Y')}  |  מנהל חלוקה")

        ver_lbl = QLabel(f"v{APP_VERSION}  ")
        ver_lbl.setStyleSheet("color:#9ca3af; font-size:11px;")
        sb.addPermanentWidget(ver_lbl)

    def _on_tab_changed(self, idx):
        tab = self.tabs.widget(idx)
        if hasattr(tab, "refresh") and getattr(tab, "_needs_refresh", True):
            tab.refresh()
            tab._needs_refresh = False

    def refresh_all(self):
        for i in range(self.tabs.count()):
            self.tabs.widget(i)._needs_refresh = True
        current = self.tabs.currentWidget()
        if current and hasattr(current, "refresh"):
            current.refresh()
            current._needs_refresh = False

    def status_msg(self, msg: str):
        self.statusBar().showMessage(msg, 4000)

    # ── Automatic update check on startup ─────────────────────────────────────
    def _auto_check_updates(self):
        """Silently check GitHub for a newer version on startup. If one exists,
        offer a one-click install. No-op when running from source (can't self-
        replace a script) and silent on any network failure."""
        if not updater.current_exe():
            return
        self._auto_worker = _UpdateWorker("check")
        self._auto_worker.checked.connect(self._on_auto_update_checked)
        self._auto_worker.start()

    def _on_auto_update_checked(self, result):
        # Background check — stay quiet on errors / no newer version.
        if isinstance(result, Exception) or not result or not result.get("url"):
            return
        if not updater.is_newer(result["version"], APP_VERSION):
            return
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
            # Reuse the Settings tab's full download → install → restart flow.
            self.settings_tab._start_download(result)

    def change_password(self):
        from PyQt6.QtWidgets import QInputDialog
        old, ok = QInputDialog.getText(
            self, "שינוי סיסמה", "סיסמה נוכחית:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        if not db.verify_password(old):
            QMessageBox.warning(self, "שגיאה", "סיסמה נוכחית שגויה")
            return
        new1, ok = QInputDialog.getText(
            self, "שינוי סיסמה", "סיסמה חדשה:", QLineEdit.EchoMode.Password)
        if not ok or not new1:
            return
        new2, ok = QInputDialog.getText(
            self, "שינוי סיסמה", "אמת סיסמה חדשה:", QLineEdit.EchoMode.Password)
        if not ok or new1 != new2:
            QMessageBox.warning(self, "שגיאה", "הסיסמאות אינן תואמות")
            return
        db.set_password(new1)
        QMessageBox.information(self, "הצלחה", "הסיסמה שונתה בהצלחה ✓")

    def choose_backup_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "בחר תיקיית גיבוי")
        if folder:
            db.set_setting("backup_folder", folder)
            QMessageBox.information(self, "הגדרות", f"תיקיית גיבוי נקבעה:\n{folder}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F5:
            self.refresh_all()
        super().keyPressEvent(event)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _set_windows_dpi_awareness():
    """Make the process per-monitor DPI-aware BEFORE Qt starts, so Windows renders
    the UI at the screen's native resolution instead of bitmap-stretching it —
    which is what makes the app look blurry on 125%/150% display scaling.
    Falls back gracefully on older Windows; safe to call once at startup."""
    if sys.platform != "win32":
        return
    import ctypes
    for attempt in (
        lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),  # PER_MONITOR_V2 (Win10 1703+)
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),  # PER_MONITOR (Win8.1+)
        lambda: ctypes.windll.user32.SetProcessDPIAware(),       # system aware (Vista+)
    ):
        try:
            attempt()
            return
        except Exception:
            continue


def _set_window_icon(widget):
    ico = resource_path("icon.ico")
    if os.path.exists(ico):
        widget.setWindowIcon(QIcon(ico))


# ─── Entry point ─────────────────────────────────────────────────────────────

def _apply_theme(app: "QApplication"):
    """Apply qt_material theme; fall back to plain QSS on any failure."""
    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme="light_blue.xml", invert_secondary=True,
                         extra=QT_MATERIAL_EXTRA)
        app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
    except Exception:
        app.setStyleSheet(EXTRA_QSS)


def _crash_dialog(msg: str):
    """Show a plain error dialog without relying on any app-level styling."""
    try:
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setWindowTitle("שגיאת הפעלה — מנהל חלוקה")
        box.setText("האפליקציה נתקלה בשגיאה בעת ההפעלה:\n\n" + msg)
        box.setIcon(QMessageBox.Icon.Critical)
        box.exec()
    except Exception:
        pass


def _write_crash_log(msg: str):
    """Write crash details next to the executable so the user can send them."""
    try:
        log_path = os.path.join(_app_dir_str(), "crash_log.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now().isoformat()}]\n{msg}\n")
    except Exception:
        pass


def _app_dir_str() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    _set_windows_dpi_awareness()   # before any Qt init — fixes blurry UI on scaled displays
    try:
        _run()
    except Exception:
        import traceback
        msg = traceback.format_exc()
        _write_crash_log(msg)
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            _crash_dialog(msg)
        except Exception:
            pass
        sys.exit(1)


def _run():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    _ico = resource_path("icon.ico")
    if os.path.exists(_ico):
        app.setWindowIcon(QIcon(_ico))

    _apply_theme(app)

    # Segoe UI renders Hebrew crisply at every DPI; the bundled variable font
    # (Rubik) looked soft/blurry, so the UI uses the system font.
    app.setFont(QFont("Segoe UI", 11))

    import time
    splash = _show_splash(app)
    t0 = time.time()

    db.init_db()

    # Startup safety backup (non-blocking) — a restore point on every launch.
    try:
        from utils.backup import auto_backup_async
        auto_backup_async()
    except Exception:
        pass

    # Remove the previous EXE left behind by a self-update, if any.
    try:
        from utils.updater import cleanup_old
        cleanup_old()
    except Exception:
        pass

    # Keep splash visible for at least 1.8 s
    remaining = max(0, 1800 - int((time.time() - t0) * 1000))
    if remaining:
        _wait_ms(remaining)

    login = LoginDialog()
    splash.finish(login)

    if login.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    win = MainWindow()
    win.show()
    # Check for updates shortly after the UI is up (background; non-blocking).
    QTimer.singleShot(1500, win._auto_check_updates)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

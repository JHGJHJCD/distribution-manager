"""סיור מודרך (onboarding) למשתמש חדש.

שכבת-על שקופה-למחצה מעל החלון הראשי עם "זרקור" מוקפץ על כל אזור בתורו,
ותיבת הסבר בעברית פשוטה עם כפתורי הבא / הקודם / דלג. השלבים מצביעים על
הלשוניות העיקריות כדי שמשתמש שרואה את התוכנה לראשונה יבין מה יש בכל מקום.

השימוש: ``GuidedTour(main_window).start()``. נשמר דגל ``tour_seen`` ב-settings
כדי שההצעה האוטומטית בהפעלה הראשונה תופיע רק פעם אחת (הכפתור ? תמיד זמין).
"""
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
)
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QEvent
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen

import database as db


# ── helpers to locate a highlight rectangle in the main window's coordinates ──

def _widget_rect(win, w):
    """Rectangle of widget `w` expressed in `win` coordinates, or None if it is
    not currently visible."""
    if w is None or not w.isVisible():
        return None
    tl = win.mapFromGlobal(w.mapToGlobal(QPoint(0, 0)))
    return QRect(tl, w.size())


def _tab_rect(win, key):
    """Switch to the tab identified by its objectName key and return the
    rectangle of its tab-button (in `win` coordinates)."""
    tabs = win.tabs
    idx = next((i for i in range(tabs.count())
                if tabs.widget(i).objectName() == "tab_" + key), None)
    if idx is None:
        return None
    tabs.setCurrentIndex(idx)
    bar = tabs.tabBar()
    r = bar.tabRect(idx)
    tl = win.mapFromGlobal(bar.mapToGlobal(r.topLeft()))
    return QRect(tl, r.size())


def build_default_steps(win):
    """The default guided-tour script for the main window. Each step is a dict:
    title, text and a `rect(win)` callable returning the highlight rectangle
    (or None for a centered, spotlight-free slide)."""
    return [
        {
            "title": "ברוך הבא למנהל חלוקה! 👋",
            "text": ("סיור קצר יראה לך מה יש בכל חלק בתוכנה. זה לוקח פחות מדקה. "
                     "אפשר לדלג בכל שלב, ולפתוח את הסיור שוב מהכפתור ❓ למעלה."),
            "rect": lambda w: None,
        },
        {
            "title": "לשונית \"חלוקה ורישום\"",
            "text": ("הלב של התוכנה. כאן מפיקים את רשימת החלוקה, שולחים אותה למתנדב "
                     "במייל, ובסוף קולטים בחזרה מי קיבל — הכל במקום אחד."),
            "rect": lambda w: _tab_rect(w, "dist"),
        },
        {
            "title": "לשונית \"מקבלים\"",
            "text": ("רשימת כל המשפחות/המקבלים. כאן מוסיפים, עורכים (לחיצה כפולה), "
                     "מייבאים מאקסל ובודקים כפילויות."),
            "rect": lambda w: _tab_rect(w, "recipients"),
        },
        {
            "title": "לשונית \"חד פעמי\"",
            "text": ("לחלוקה חד-פעמית: התוכנה ממליצה מי הכי זקוק לפי ניקוד צורך, "
                     "ואתה בוחר את הרשימה."),
            "rect": lambda w: _tab_rect(w, "one_time"),
        },
        {
            "title": "לשונית \"חיפוש מהיר\"",
            "text": ("מחפשים מקבל לפי שם ורואים מיד את כל הפרטים וההיסטוריה שלו — "
                     "מה קיבל ומתי."),
            "rect": lambda w: _tab_rect(w, "search"),
        },
        {
            "title": "לשונית \"הגדרות\"",
            "text": ("סיסמת כניסה, גיבויים אוטומטיים, הגדרות המייל למתנדבים "
                     "(כולל סיסמה לקובץ), ועדכוני תוכנה."),
            "rect": lambda w: _tab_rect(w, "settings"),
        },
        {
            "title": "נתקעת? השאר הודעה",
            "text": ("הכפתור הזה שולח דיווח על בעיה או בקשה למפתח. תמיד זמין בתחתית "
                     "המסך."),
            "rect": lambda w: _widget_rect(w, getattr(w, "_fb_btn", None)),
        },
        {
            "title": "זהו — אפשר להתחיל! ✓",
            "text": ("סיימנו את הסיור. בכל פעם שתרצה לחזור עליו — לחץ על הכפתור ❓ "
                     "שלמעלה מימין. בהצלחה!"),
            "rect": lambda w: None,
        },
    ]


class GuidedTour(QWidget):
    """Semi-transparent spotlight overlay that walks the user through `steps`."""

    def __init__(self, win, steps=None):
        super().__init__(win)
        self.win = win
        self.steps = steps if steps is not None else build_default_steps(win)
        self.i = 0
        self._spot = None

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # The callout card (title + text + buttons). A real child widget so its
        # text stays crisp and its buttons are clickable.
        self.box = QFrame(self)
        self.box.setObjectName("tourBox")
        self.box.setStyleSheet(
            "#tourBox{background:#ffffff; border:1px solid #dbe3ef;"
            "border-radius:12px;}")
        self.box.setFixedWidth(390)

        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size:16px; font-weight:700; color:#0d2a4a;")
        self.lbl_title.setWordWrap(True)
        self.lbl_text = QLabel()
        self.lbl_text.setStyleSheet("font-size:13px; color:#374151;")
        self.lbl_text.setWordWrap(True)
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_text)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.lbl_prog = QLabel()
        self.lbl_prog.setStyleSheet("font-size:12px; color:#9ca3af;")
        self.btn_skip = QPushButton("דלג")
        self.btn_prev = QPushButton("הקודם")
        self.btn_next = QPushButton("הבא")
        for b in (self.btn_skip, self.btn_prev):
            b.setStyleSheet(
                "QPushButton{background:#eef2f7; color:#334155; border:none;"
                "border-radius:8px; padding:6px 14px; font-size:13px;}"
                "QPushButton:hover{background:#e2e8f0;}")
        self.btn_next.setStyleSheet(
            "QPushButton{background:#1565c0; color:white; border:none;"
            "border-radius:8px; padding:6px 18px; font-size:13px; font-weight:600;}"
            "QPushButton:hover{background:#1976d2;}")
        for b in (self.btn_skip, self.btn_prev, self.btn_next):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self.finish)
        self.btn_prev.clicked.connect(self._prev)
        self.btn_next.clicked.connect(self._next)

        # RTL order: progress on the right, then skip, prev, next on the left.
        btn_row.addWidget(self.lbl_prog)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_skip)
        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_next)
        lay.addLayout(btn_row)

        self.win.installEventFilter(self)

    # ── public ────────────────────────────────────────────────────────────────
    def start(self):
        self.setGeometry(self.win.rect())
        self.show()
        self.raise_()
        self._apply_step()

    # ── navigation ──────────────────────────────────────────────────────────────
    def _next(self):
        if self.i >= len(self.steps) - 1:
            self.finish()
            return
        self.i += 1
        self._apply_step()

    def _prev(self):
        if self.i > 0:
            self.i -= 1
            self._apply_step()

    def finish(self):
        try:
            db.set_setting("tour_seen", "1")
        except Exception:
            pass
        self.win.removeEventFilter(self)
        self.close()
        self.deleteLater()

    def _apply_step(self):
        step = self.steps[self.i]
        self.lbl_title.setText(step["title"])
        self.lbl_text.setText(step["text"])
        self.lbl_prog.setText(f"{self.i + 1} / {len(self.steps)}")
        self.btn_prev.setVisible(self.i > 0)
        self.btn_next.setText("סיום ✓" if self.i == len(self.steps) - 1 else "הבא ←")
        try:
            self._spot = step["rect"](self.win)
        except Exception:
            self._spot = None
        self.setGeometry(self.win.rect())
        self._place_box()
        self.update()

    def _place_box(self):
        """Position the callout so it never sits on top of the spotlight."""
        self.box.adjustSize()
        bw, bh = self.box.width(), self.box.height()
        W, H = self.width(), self.height()
        margin = 20
        if self._spot is None:
            x = (W - bw) // 2
            y = (H - bh) // 2
        else:
            s = self._spot
            x = min(max(margin, s.center().x() - bw // 2), W - bw - margin)
            below = s.bottom() + 16
            if below + bh <= H - margin:
                y = below
            else:
                y = max(margin, s.top() - bh - 16)
        self.box.move(x, y)

    # keep the overlay glued to the window if it is resized/moved mid-tour
    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(self.win.rect())
            # recompute the spotlight (tab positions may shift on resize)
            try:
                self._spot = self.steps[self.i]["rect"](self.win)
            except Exception:
                self._spot = None
            self._place_box()
            self.update()
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.finish()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right):
            self._next()
        elif e.key() == Qt.Key.Key_Left:
            self._prev()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if self._spot is not None:
            pad = 6
            r = QRectF(self._spot.adjusted(-pad, -pad, pad, pad))
            path.addRoundedRect(r, 10, 10)
        # OddEven fill turns the inner rounded rect into a see-through hole.
        p.fillPath(path, QColor(15, 23, 42, 175))
        if self._spot is not None:
            pad = 6
            r = self._spot.adjusted(-pad, -pad, pad, pad)
            p.setPen(QPen(QColor("#facc15"), 3))
            p.drawRoundedRect(r, 10, 10)

"""סיור מודרך (onboarding) למשתמש חדש.

שכבת-על שקופה-למחצה מעל החלון הראשי עם "זרקור" מוקפץ על כל אזור בתורו,
ותיבת הסבר בעברית פשוטה עם כפתורי הבא / הקודם / דלג. השלבים מצביעים על
הלשוניות העיקריות כדי שמשתמש שרואה את התוכנה לראשונה יבין מה יש בכל מקום.

השימוש: ``GuidedTour(main_window).start()``. נשמר דגל ``tour_seen`` ב-settings
כדי שההצעה האוטומטית בהפעלה הראשונה תופיע רק פעם אחת (הכפתור ? תמיד זמין).
"""
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QEvent
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen

import database as db


# ── helpers to locate a highlight rectangle in the main window's coordinates ──

def _widget_rect(win, w):
    """Rectangle of widget `w` expressed in `win` coordinates, or None if it has
    no real size yet (e.g. not laid out)."""
    if w is None or w.width() <= 0 or w.height() <= 0:
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


# ── deep-tour helpers: switch to a tab, then spotlight a control inside it ─────

def _tab_widget(win, key):
    """Switch to the tab identified by `key` and return its content widget."""
    tabs = win.tabs
    for i in range(tabs.count()):
        w = tabs.widget(i)
        if w.objectName() == "tab_" + key:
            tabs.setCurrentIndex(i)
            return w
    return None


def _ensure_visible(w):
    """If `w` lives inside a scroll area, scroll it into view so the spotlight
    lands on something the user can actually see."""
    from PyQt6.QtWidgets import QScrollArea
    p = w.parent()
    while p is not None:
        if isinstance(p, QScrollArea):
            try:
                p.ensureWidgetVisible(w, 60, 60)
            except Exception:
                pass
            return
        p = p.parent()


def _attr_rect(win, key, attr):
    """Spotlight the widget stored as `tab.<attr>` on the given tab."""
    tw = _tab_widget(win, key)
    if tw is None:
        return None
    w = getattr(tw, attr, None)
    if w is None:
        return None
    _ensure_visible(w)
    return _widget_rect(win, w)


def _btn_rect(win, key, text):
    """Spotlight a QPushButton on the given tab, matched by its label. Prefers an
    exact text match, then a 'contains' match (so 'שמור' won't grab
    'שמור משקלים')."""
    from PyQt6.QtWidgets import QPushButton
    tw = _tab_widget(win, key)
    if tw is None:
        return None
    btns = [b for b in tw.findChildren(QPushButton)]
    target = next((b for b in btns if b.text().replace("&", "").strip() == text), None)
    if target is None:
        target = next((b for b in btns if text in b.text().replace("&", "")), None)
    if target is None:
        return None
    _ensure_visible(target)
    return _widget_rect(win, target)


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
            "title": "נתקעת? השאר הודעה 💬",
            "text": ("<b>בתחתית המסך</b> (משמאל למטה) יש כפתור <b>\"✉ השאר הודעה\"</b>. "
                     "לחיצה עליו פותחת חלון קטן שבו אפשר לכתוב בקשה או לדווח על בעיה — "
                     "וזה נשלח ישירות למפתח."),
            "rect": lambda w: _widget_rect(w, getattr(w, "_fb_btn", None)),
        },
        {
            "title": "זהו — אפשר להתחיל! ✓",
            "text": ("סיימנו את הסיור. בכל פעם שתרצה לחזור עליו — לחץ על הכפתור ❓ "
                     "שלמעלה מימין. בהצלחה!"),
            "rect": lambda w: None,
        },
    ]


def build_extended_steps(win):
    """The deep 'explain every button' tour. Walks tab-by-tab and spotlights each
    important control with a detailed plain-Hebrew explanation. If a target can't
    be located its callout is simply shown centered (no spotlight)."""
    S = []

    def step(title, text, rect):
        S.append({"title": title, "text": text, "rect": rect})

    step("סיור מורחב — כל כפתור בתוכנה 📖",
         "בסיור הזה נעבור <b>אחד-אחד</b> על הכפתורים והשדות החשובים בכל לשונית, "
         "עם הסבר מלא מה כל אחד עושה. אפשר לדלג או לחזור אחורה בכל שלב.",
         lambda w: None)

    # ── לשונית: חלוקה ורישום ─────────────────────────────────────────────────
    step("לשונית \"חלוקה ורישום\"",
         "כאן עושים את כל תהליך החלוקה: בוחרים את המקבלים, ממלאים את פרטי החלוקה, "
         "שולחים למתנדב, מדפיסים, ורושמים מי קיבל. נעבור על השדות לפי הסדר.",
         lambda w: _tab_rect(w, "dist"))
    step("שם החלוקה",
         "שם/מטרת החלוקה — למשל \"חלוקת פסח\". חובה למלא לפני הדפסה או שליחה. "
         "אפשר לבחור משמות קודמים מהרשימה הנפתחת.",
         lambda w: _attr_rect(w, "dist", "name_input"))
    step("תאריך החלוקה",
         "התאריך שבו מבוצעת החלוקה. ימי רביעי מסומנים בכחול (יום החלוקה הקבוע).",
         lambda w: _attr_rect(w, "dist", "date_edit"))
    step("שם המחלק",
         "מי מבצע את החלוקה בפועל. נשמר במעקב ומופיע במייל למתנדב.",
         lambda w: _attr_rect(w, "dist", "dist_input"))
    step("הערה כללית לחלוקה",
         "הערה על כל החלוקה (לא חובה) — נשמרת בלשונית \"חלוקות\" ומצורפת לכל מקבל.",
         lambda w: _attr_rect(w, "dist", "note_input"))
    step("מה מחלקים",
         "כאן רושמים כל פריט שמחלקים ואת הכמות שכל אדם מקבל ממנו — אפשר להוסיף "
         "כמה פריטים לאותה חלוקה (סל מזון, עוף, שמן...). הכפתור \"הוסף פריט\" מוסיף שורה.",
         lambda w: _attr_rect(w, "dist", "products"))
    step("חיפוש מהיר ברשימה",
         "מסננים את רשימת החלוקה לפי כל פרט של המקבל — שם, טלפון, אזור או ת״ז. "
         "הסימונים נשמרים גם כשמסננים.",
         lambda w: _attr_rect(w, "dist", "search_input"))
    step("אימייל המתנדב",
         "כתובת המייל של המתנדב שיקבל את הרשימה למילוי. אפשר לבחור מכתובות "
         "קודמות. נדרש רק לשליחה במייל.",
         lambda w: _attr_rect(w, "dist", "volunteer_email_input"))
    step("כפתור \"שלח למתנדב\"",
         "שולח למתנדב מייל עם קובץ אקסל של הרשימה. הוא מסמן מי הגיע, ממלא הערות, "
         "ושולח חזרה — והתוכנה קולטת את זה אוטומטית. (הקובץ יכול להיות נעול בסיסמה — "
         "ראה הגדרות ← מייל למתנדבים.)",
         lambda w: _btn_rect(w, "dist", "שלח למתנדב"))
    step("כפתור \"יבוא ידני\"",
         "אם קיבלת את קובץ האקסל הממולא בדרך אחרת (לא במייל) — כאן בוחרים אותו "
         "ידנית מהמחשב כדי לרשום מי קיבל.",
         lambda w: _btn_rect(w, "dist", "יבוא ידני"))
    step("כפתורי \"בחר הכל\" / \"בטל הכל\"",
         "מסמנים או מבטלים את כל השורות בטבלה בבת אחת — מהיר כשרוצים לכלול/להוציא "
         "את כולם ואז לתקן ידנית מעטים.",
         lambda w: _btn_rect(w, "dist", "בחר הכל"))
    step("כפתור \"שמור חלוקה\"",
         "רושם את החלוקה הזו בהיסטוריה (מי קיבל, מתי, מה) <b>וגם</b> מוריד קובץ "
         "אקסל של הרשימה לתיקיית ההורדות. זה הכפתור המרכזי לתיעוד חלוקה.",
         lambda w: _btn_rect(w, "dist", "שמור חלוקה"))
    step("כפתור \"יצוא לאקסל\"",
         "מוריד רק את הרשימה (בלי לרשום למעקב) — נוח להדפסה או שליחה מהירה.",
         lambda w: _btn_rect(w, "dist", "יצוא לאקסל"))
    step("כפתור \"הדפסה\"",
         "מדפיס את רשימת החלוקה בעימוד מסודר עם הלוגו — מוכן לחלוקה ידנית.",
         lambda w: _btn_rect(w, "dist", "הדפסה"))

    # ── לשונית: מקבלים ───────────────────────────────────────────────────────
    step("לשונית \"מקבלים\"",
         "מאגר כל המשפחות/המקבלים. כאן מוסיפים, עורכים, מסננים ובודקים כפילויות.",
         lambda w: _tab_rect(w, "recipients"))
    step("שדה החיפוש",
         "מקלידים שם, טלפון, ת\"ז או כתובת — הטבלה מסתננת מיד למי שמתאים.",
         lambda w: _attr_rect(w, "recipients", "search_input"))
    step("סינון לפי סטטוס / עדיפות",
         "מציג רק מקבלים פעילים/מושהים, או לפי דרגת עדיפות — למיקוד מהיר ברשימה.",
         lambda w: _attr_rect(w, "recipients", "status_filter"))
    step("כפתור \"+ הוסף מקבל\"",
         "פותח טופס להוספת משפחה/מקבל חדש — שם, טלפונים, כתובת, נפשות, ועדיפות.",
         lambda w: _btn_rect(w, "recipients", "הוסף מקבל"))
    step("כפתור \"יבוא מ-Excel\"",
         "מייבא רשימת מקבלים שלמה מקובץ אקסל בבת אחת — חוסך הקלדה ידנית.",
         lambda w: _btn_rect(w, "recipients", "יבוא מ-Excel"))
    step("כפתורי \"הפעל\" / \"השהה\" / \"מחק\"",
         "פועלים על השורה המסומנת: <b>הפעל/השהה</b> מכניס או מוציא מקבל מהחלוקות "
         "בלי למחוק את הנתונים; <b>מחק</b> מוחק לצמיתות. לעריכת פרטים — לחיצה כפולה "
         "על השורה.",
         lambda w: _btn_rect(w, "recipients", "השהה"))
    step("כפתור \"בדיקת כפילויות\"",
         "מזהה מקבלים שאולי הוזנו פעמיים (שם/טלפון דומים) כדי לנקות את הרשימה.",
         lambda w: _btn_rect(w, "recipients", "בדיקת כפילויות"))

    # ── לשונית: חד פעמי ──────────────────────────────────────────────────────
    step("לשונית \"חד פעמי\"",
         "לחלוקה חד-פעמית: התוכנה מדרגת מי הכי זקוק לפי ניקוד צורך, ואתה בוחר.",
         lambda w: _tab_rect(w, "one_time"))
    step("שדה החיפוש",
         "מסנן את הרשימה לפי שם/טלפון/כתובת/אזור — בלי לשנות את החישוב.",
         lambda w: _attr_rect(w, "one_time", "search_input"))
    step("כפתור \"חשב המלצה\"",
         "מריץ את ניקוד הצורך ומדרג את המקבלים — מי שהכי מזמן לא קיבל ובעל עדיפות "
         "גבוהה עולה למעלה.",
         lambda w: _btn_rect(w, "one_time", "חשב המלצה"))
    step("כפתור \"הוסף נבחרים לעדכון קבוצתי\"",
         "מעביר את מי שסימנת ללשונית \"חלוקה ורישום\" כדי לשלוח/להדפיס/לרשום אותם.",
         lambda w: _btn_rect(w, "one_time", "הוסף נבחרים"))

    # ── לשונית: חיפוש מהיר ───────────────────────────────────────────────────
    step("לשונית \"חיפוש מהיר\"",
         "חיפוש מקבל בודד וצפייה בכל הפרטים וההיסטוריה שלו במקום אחד.",
         lambda w: _tab_rect(w, "search"))
    step("שדה החיפוש",
         "מקלידים שם והרשימה מימין מציגה התאמות. לחיצה על שם מציגה את כל פרטיו.",
         lambda w: _attr_rect(w, "search", "search_input"))
    step("כפתור \"ייצוא הרשימה לאקסל\"",
         "מוריד את תוצאות החיפוש הנוכחיות לקובץ אקסל.",
         lambda w: _btn_rect(w, "search", "ייצוא הרשימה"))
    step("כפתור \"הדפס כרטיס\"",
         "מדפיס כרטיס מסודר של המקבל שנבחר — פרטים והיסטוריית חלוקות.",
         lambda w: _btn_rect(w, "search", "הדפס כרטיס"))

    # ── לשונית: הגדרות ───────────────────────────────────────────────────────
    step("לשונית \"הגדרות\"",
         "כל ההגדרות: סיסמה, משקלי ניקוד, גיבויים, מייל למתנדבים, עדכונים.",
         lambda w: _tab_rect(w, "settings"))
    step("כפתור \"שנה סיסמה\"",
         "משנה את סיסמת הכניסה לתוכנה. צריך להזין קודם את הסיסמה הנוכחית.",
         lambda w: _btn_rect(w, "settings", "שנה סיסמה"))
    step("כפתור \"בדוק עדכונים\"",
         "בודק מול השרת אם יש גרסה חדשה של התוכנה ומתקין בלחיצה. (קורה גם "
         "אוטומטית בכל פתיחה.)",
         lambda w: _btn_rect(w, "settings", "בדוק עדכונים"))
    step("הגדרות המייל למתנדבים",
         "כתובת השולח וסיסמת האפליקציה (Gmail) שדרכן נשלחים המיילים. כאן גם "
         "<b>הסיסמה לקובץ המתנדב</b> — נעילת קובץ האקסל שנשלח.",
         lambda w: _attr_rect(w, "settings", "mail_email"))
    step("כפתורי \"שמור\" / \"שלח מייל בדיקה\"",
         "<b>שמור</b> — שומר את הגדרות המייל. <b>שלח מייל בדיקה</b> — בודק שהחיבור "
         "עובד לפני שליחה אמיתית.",
         lambda w: _btn_rect(w, "settings", "שלח מייל בדיקה"))
    step("גיבוי: \"בחר תיקייה\" / \"גבה עכשיו\" / \"שחזר מגיבוי\"",
         "התוכנה מגבה אוטומטית בכל פתיחה. כאן אפשר לבחור תיקיית גיבוי, לגבות "
         "עכשיו ידנית, או לשחזר נתונים מגיבוי קודם.",
         lambda w: _btn_rect(w, "settings", "גבה עכשיו"))
    step("כפתור \"אפס את כל הנתונים\" ⚠",
         "מוחק את <b>כל</b> המקבלים וההיסטוריה ומחזיר את התוכנה למצב ריק. פעולה "
         "מסוכנת — יש להשתמש רק אם באמת רוצים להתחיל מאפס (יש גיבוי לפני).",
         lambda w: _btn_rect(w, "settings", "אפס את כל הנתונים"))
    step("כפתור \"✉ השאר הודעה למפתח\"",
         "<b>זה הכפתור שחיפשת!</b> לחיצה עליו פותחת חלון לכתיבת בקשה או דיווח על "
         "בעיה, שנשלח ישירות למפתח. (יש כפתור נוסף זהה גם בתחתית המסך, משמאל.)",
         lambda w: _btn_rect(w, "settings", "השאר הודעה"))

    step("סיימנו את הסיור המורחב! 🎉",
         "עכשיו אתה מכיר כל כפתור בתוכנה. אפשר לפתוח שוב כל סיור מהכפתור ❓ "
         "שלמעלה מימין. בהצלחה!",
         lambda w: None)
    return S


class GuidedTour(QWidget):
    """Semi-transparent spotlight overlay that walks the user through `steps`."""

    _BOX_W = 460   # callout card width (px)

    def __init__(self, win, steps=None):
        super().__init__(win)
        self.win = win
        self.steps = steps if steps is not None else build_default_steps(win)
        self.i = 0
        self._spot = None

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        # ── The callout card ─────────────────────────────────────────────────
        # A real child widget so text stays crisp and buttons are clickable.
        # Fixed width, height grows to fit the (word-wrapped) text — see
        # _apply_step, which pins the label widths so nothing gets clipped.
        self.box = QFrame(self)
        self.box.setObjectName("tourBox")
        self.box.setStyleSheet(
            "#tourBox{background:#ffffff; border:1px solid #e2e8f0;"
            "border-radius:16px;}")
        self.box.setFixedWidth(self._BOX_W)
        shadow = QGraphicsDropShadowEffect(self.box)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(15, 23, 42, 120))
        self.box.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header band (navy→blue) with the step title, rounded to match the card.
        header = QFrame()
        header.setObjectName("tourHead")
        header.setStyleSheet(
            "#tourHead{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #0d2a4a, stop:1 #1565c0);"
            "border-top-left-radius:16px; border-top-right-radius:16px;}")
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(22, 14, 22, 14)
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:17px; font-weight:800; color:#ffffff; background:transparent;")
        self.lbl_title.setWordWrap(True)
        h_lay.addWidget(self.lbl_title)
        lay.addWidget(header)

        # Body: the explanation text.
        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 6)
        self.lbl_text = QLabel()
        self.lbl_text.setStyleSheet(
            "font-size:14px; color:#334155; background:transparent;")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self.lbl_text)
        lay.addLayout(body)

        # Footer: progress on the right, navigation on the left.
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 8, 18, 16)
        foot.setSpacing(8)
        self.lbl_prog = QLabel()
        self.lbl_prog.setStyleSheet(
            "font-size:12px; color:#94a3b8; background:transparent; font-weight:600;")
        self.btn_skip = QPushButton("דלג")
        self.btn_prev = QPushButton("→ הקודם")
        self.btn_next = QPushButton("הבא")
        self.btn_skip.setStyleSheet(
            "QPushButton{background:transparent; color:#94a3b8; border:none;"
            "padding:8px 10px; font-size:13px;}"
            "QPushButton:hover{color:#475569;}")
        self.btn_prev.setStyleSheet(
            "QPushButton{background:#eef2f7; color:#334155; border:none;"
            "border-radius:9px; padding:8px 16px; font-size:13px; font-weight:600;}"
            "QPushButton:hover{background:#e2e8f0;}")
        self.btn_next.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #1976d2, stop:1 #1565c0); color:white; border:none;"
            "border-radius:9px; padding:8px 22px; font-size:14px; font-weight:700;}"
            "QPushButton:hover{background:#1565c0;}")
        for b in (self.btn_skip, self.btn_prev, self.btn_next):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self.finish)
        self.btn_prev.clicked.connect(self._prev)
        self.btn_next.clicked.connect(self._next)

        foot.addWidget(self.lbl_prog)
        foot.addStretch()
        foot.addWidget(self.btn_skip)
        foot.addWidget(self.btn_prev)
        foot.addWidget(self.btn_next)
        lay.addLayout(foot)

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
        self.lbl_prog.setText(f"שלב {self.i + 1} מתוך {len(self.steps)}")
        self.btn_prev.setVisible(self.i > 0)
        self.btn_next.setText("סיום ✓" if self.i == len(self.steps) - 1 else "הבא ←")
        # Pin the label widths to the card's inner width so word-wrap reports the
        # correct height — without this the box can size too short and clip text.
        inner = self._BOX_W - 44
        self.lbl_title.setFixedWidth(inner)
        self.lbl_text.setFixedWidth(inner)
        self.lbl_title.setMinimumHeight(self.lbl_title.heightForWidth(inner))
        self.lbl_text.setMinimumHeight(self.lbl_text.heightForWidth(inner))
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

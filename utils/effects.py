"""
שכבת עומק ותנועה (depth + motion) — נותנת לתוכנה מראה מודרני של אפליקציה
"אמיתית" במקום טופס שטוח: צללים רכים תחת כרטיסים וסרגל-העל, "הרמה" מונפשת של
כפתורים ראשיים במעבר עכבר, ומעבר-דהייה עדין כשמחליפים לשונית.

הכול idempotent: apply_depth() אפשר לקרוא שוב ושוב על אותו עץ ווידג'טים והוא
ידלג על מה שכבר עוטר. אין תלות בערכת-הצבעים — עובד לכל קופה/מיתוג.
"""
from PyQt6.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                             QPushButton, QFrame, QWidget)
from PyQt6.QtCore import (QObject, QEvent, QPropertyAnimation, QParallelAnimationGroup,
                          QEasingCurve)
from PyQt6.QtGui import QColor

# צל "אווירי" רך — כחול-דיו שקוף, יורד מעט כלפי מטה (מקור-אור מלמעלה)
_SHADOW_INK = QColor(23, 42, 77)


def soft_shadow(widget: QWidget, blur: int = 34, dy: int = 11, alpha: int = 42):
    """מצמיד צל-הטלה רך לווידג'ט (כרטיס / סרגל). מחזיר את האפקט."""
    col = QColor(_SHADOW_INK)
    col.setAlpha(alpha)
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setXOffset(0)
    eff.setYOffset(dy)
    eff.setColor(col)
    widget.setGraphicsEffect(eff)
    return eff


class _HoverLift(QObject):
    """Event-filter יחיד המשותף לכל הכפתורים: במעבר-עכבר מגדיל את הצל ומרים אותו
    מעט (תחושת "ריחוף"), וביציאה מחזיר. QSS לבדו לא יודע להנפיש — לכן אפקט+אנימציה."""

    # מצב-מנוחה מול מצב-ריחוף (blur, yOffset, alpha)
    _REST = (16, 5, 55)
    _HOVER = (30, 10, 90)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._to(obj, self._HOVER)
        elif t == QEvent.Type.Leave:
            self._to(obj, self._REST)
        return False

    def _to(self, btn, target):
        eff = btn.graphicsEffect()
        if not isinstance(eff, QGraphicsDropShadowEffect):
            return
        blur, dy, alpha = target
        col = QColor(_SHADOW_INK)
        col.setAlpha(alpha)
        grp = QParallelAnimationGroup(btn)
        a1 = QPropertyAnimation(eff, b"blurRadius")
        a1.setEndValue(blur)
        a2 = QPropertyAnimation(eff, b"yOffset")
        a2.setEndValue(dy)
        a3 = QPropertyAnimation(eff, b"color")
        a3.setEndValue(col)
        for a in (a1, a2, a3):
            a.setDuration(150)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            grp.addAnimation(a)
        # שמירת רפרנס כדי שהאנימציה לא תיאסף מיד ע"י ה-GC
        btn._lift_grp = grp
        grp.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)


_LIFT = _HoverLift()               # instance משותף אחד
_LIFTED_NAMES = {"primary", "success", "danger"}
_SHADOW_NAMES = {"panel", "appbar"}


def apply_depth(root: QWidget):
    """עובר על עץ הווידג'טים ומעטר: צל רך לכרטיסים/סרגל, והרמה מונפשת לכפתורים
    ראשיים. בטוח לקרוא שוב — כל ווידג'ט מעוטר פעם אחת בלבד."""
    if root is None:
        return
    for w in root.findChildren(QFrame):
        if w.objectName() in _SHADOW_NAMES and not w.property("_depth"):
            w.setProperty("_depth", True)
            big = w.objectName() == "appbar"
            soft_shadow(w, blur=32 if big else 30, dy=9 if big else 9,
                        alpha=46 if big else 34)
    for b in root.findChildren(QPushButton):
        if b.objectName() in _LIFTED_NAMES and not b.property("_depth"):
            b.setProperty("_depth", True)
            eff = soft_shadow(b, blur=16, dy=5, alpha=55)
            eff.setColor(_rest_color())
            b.installEventFilter(_LIFT)


def _rest_color():
    col = QColor(_SHADOW_INK)
    col.setAlpha(55)
    return col


def fade_in(widget: QWidget, duration: int = 170):
    """מעבר דהייה קצר (0→1) — נעים לעין כשלשונית חדשה נכנסת. האפקט מוסר בסיום כדי
    שלא יפריע לרינדור הטקסט (ClearType) בהמשך."""
    if widget is None:
        return
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._fade_anim = anim
    anim.start()

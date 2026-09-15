# -*- coding: utf-8 -*-
"""v3.50: עיצוב-טקסט במייל (הדגשה/קו תחתון/נטוי/גודל/צבע/יישור/רשימות/קישור).

עורך ה-QTextEdit במסך המיילים הופך ל-"מסמך" (QTextDocument), והמודול הזה מתרגם
אותו ל-HTML **מינימלי ונקי** (לא ה-toHtml של Qt שמנפח כל מילה ב-span+font).
כשאין שום עיצוב — מוחזר טקסט-רגיל בדיוק כמו קודם (תאימות מלאה: תבניות ישנות,
היסטוריה, המחשב השני עם גרסה קודמת). כשיש עיצוב — התוצאה מסומנת ב-`mailer.RICH_PREFIX`
ושאר המערכת (`mailer.render`/`html_body`/`to_plain`) מזהה זאת.

תלוי ב-PyQt6.QtGui בלבד (בלי widgets) — רץ גם ב-offscreen/בדיקות.
"""
import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument, QTextFormat, QTextListFormat, QFont

from utils import mailer


def _frag_html(cf, text: str) -> tuple[str, bool]:
    """קטע-טקסט עם עיצוב-תווים → HTML; מחזיר (html, האם היה עיצוב כלשהו)."""
    t = html.escape(text).replace("\u2028", "<br>").replace("\n", "<br>").replace("\xa0", "&nbsp;")
    styled = False
    styles = []
    if cf.hasProperty(QTextFormat.Property.ForegroundBrush):
        c = cf.foreground().color()
        if c.isValid() and c.alpha() > 0:
            styles.append(f"color:{c.name()}")
    if cf.hasProperty(QTextFormat.Property.BackgroundBrush):
        c = cf.background().color()
        if c.isValid() and c.alpha() > 0:
            styles.append(f"background:{c.name()}")
    ps = cf.fontPointSize()
    if ps and ps > 0:
        styles.append(f"font-size:{ps:g}pt")
    if styles:
        t = f"<span style='{';'.join(styles)}'>{t}</span>"
        styled = True
    if cf.fontStrikeOut():
        t, styled = f"<s>{t}</s>", True
    if cf.fontUnderline() and not cf.isAnchor():
        t, styled = f"<u>{t}</u>", True
    if cf.fontItalic():
        t, styled = f"<i>{t}</i>", True
    if cf.fontWeight() >= QFont.Weight.DemiBold.value:
        t, styled = f"<b>{t}</b>", True
    if cf.isAnchor() and cf.anchorHref():
        href = html.escape(cf.anchorHref(), quote=True)
        t, styled = f"<a href='{href}' style='color:#0f766e'>{t}</a>", True
    return t, styled


def align_kind(al) -> str:
    """יישור-פסקה → "" (ברירת-מחדל = ימין בעברית) / "center" / "left".
    ב-Qt, AlignLeft בלי AlignAbsolute הוא "מוביל" (=ימין בפסקה עברית) ו-AlignRight בלי
    AlignAbsolute הוא "עוקב" (=שמאל). לכן הסרגל קובע יישור עם AlignAbsolute."""
    al = al & (Qt.AlignmentFlag.AlignHorizontal_Mask | Qt.AlignmentFlag.AlignAbsolute)
    absolute = bool(al & Qt.AlignmentFlag.AlignAbsolute)
    h = al & Qt.AlignmentFlag.AlignHorizontal_Mask
    if h == Qt.AlignmentFlag.AlignHCenter:
        return "center"
    if absolute:
        return "left" if h == Qt.AlignmentFlag.AlignLeft else ""
    return "left" if h == Qt.AlignmentFlag.AlignRight else ""


def document_to_markup(doc: QTextDocument) -> str:
    """המסמך → טקסט-רגיל (כשאין עיצוב) או `RICH_PREFIX`+HTML נקי (כשיש)."""
    plain = doc.toPlainText().replace("\u2029", "\n").replace("\u2028", "\n")
    out = []
    styled = False
    open_list = None          # (QTextList, tag)
    block = doc.begin()
    while block.isValid():
        lst = block.textList()
        if open_list and (lst is None or lst is not open_list[0]):
            out.append(f"</{open_list[1]}>")
            open_list = None
        parts = []
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                h, s = _frag_html(frag.charFormat(), frag.text())
                parts.append(h)
                styled = styled or s
            it += 1
        inner = "".join(parts)
        talign = align_kind(block.blockFormat().alignment())
        styled = styled or bool(talign)
        style = f" style='text-align:{talign}'" if talign else ""
        if lst is not None:
            styled = True
            if open_list is None:
                tag = ("ol" if lst.format().style() in (
                    QTextListFormat.Style.ListDecimal, QTextListFormat.Style.ListLowerAlpha,
                    QTextListFormat.Style.ListUpperAlpha, QTextListFormat.Style.ListLowerRoman,
                    QTextListFormat.Style.ListUpperRoman) else "ul")
                open_list = (lst, tag)
                out.append(f"<{tag} dir='rtl' style='margin:0 0 12px;padding-right:24px'>")
            out.append(f"<li{style}>{inner}</li>")
        else:
            pstyle = "margin:0 0 12px" + (f";text-align:{talign}" if talign else "")
            out.append(f"<p style='{pstyle}'>{inner or '&nbsp;'}</p>")
        block = block.next()
    if open_list:
        out.append(f"</{open_list[1]}>")
    if not styled or not plain.strip():
        return plain
    return mailer.RICH_PREFIX + "".join(out)


def load_into(edit, body: str) -> None:
    """טעינת גוף-הודעה (רגיל או מעוצב) לעורך."""
    if mailer.is_rich(body):
        edit.setHtml(f"<div dir='rtl'>{body[len(mailer.RICH_PREFIX):]}</div>")
    else:
        edit.setPlainText(body or "")

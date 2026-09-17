# -*- coding: utf-8 -*-
"""צילום מסך "מיילים" (v3.39) + כרטיס "חשבון Google" בהגדרות, על DB זמני.
הרצה: python dev/_shot_mails.py  → dev/_shots/mails_tab.png, mails_settings.png
"""
import os, sys, json
os.environ["PYTHONUTF8"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                ".claude", "skills", "visual-check", "scripts"))
from shot import boot   # noqa: E402

app, win = boot()
import database as db   # noqa: E402
from PyQt6.QtCore import Qt   # noqa: E402
from PyQt6.QtWidgets import QScrollArea   # noqa: E402

# seed
names = [("כהן ישראל", "cohen@example.com"), ("לוי משה", "levi@example.com"),
         ("פרידמן שרה", ""), ("גולדברג דוד", "gold@example.com"),
         ("מזרחי רחל", "לא-מייל"), ("אברהם יוסף", "cohen@example.com")]
for n, e in names:
    db.add_recipient({"full_name": n, "email": e, "status": "פעיל", "priority": 4,
                      "frequency": "שבועי", "phone1": "0501234567"})
db.set_setting("smtp_email", "kupa.haryona@gmail.com")
db.set_setting("smtp_app_password", "xxxx")
g = db.add_mail_campaign("תזכורת: חלוקה ביום רביעי", "שלום {שם},\nתזכורת…", "כל המקבלים",
                         "kupa.haryona@gmail.com", 4, device="A")
db.update_mail_campaign(g, 3, 1, "done", json.dumps(
    [{"rec_id": 1, "name": "כהן ישראל", "email": "cohen@example.com", "status": "sent", "error": ""},
     {"rec_id": 2, "name": "לוי משה", "email": "levi@example.com", "status": "failed", "error": "כתובת שגויה"}],
    ensure_ascii=False))
# v3.43: שליחה שנעצרה ידנית — נכשלו 0 אבל יש "לא נשלח" → חייב כפתור "שלח שוב לנכשלים"
g2 = db.add_mail_campaign("חג שמח", "שלום {שם}", "כל המקבלים", "kupa.haryona@gmail.com", 3, device="A")
db.update_mail_campaign(g2, 1, 0, "stopped", json.dumps(
    [{"rec_id": 1, "name": "כהן ישראל", "email": "cohen@example.com", "status": "sent", "error": ""},
     {"rec_id": 2, "name": "לוי משה", "email": "levi@example.com", "status": "skipped", "error": "השליחה נעצרה"},
     {"rec_id": 4, "name": "גולדברג דוד", "email": "gold@example.com", "status": "skipped", "error": "השליחה נעצרה"}],
    ensure_ascii=False))
db.upsert_mail_template("תזכורת לחלוקה", "תזכורת: חלוקה ביום רביעי {תאריך חלוקה}",
                        "שלום {שם},\nתזכורת שהחלוקה תתקיים ביום רביעי {תאריך חלוקה}.\n\nנשמח לראותכם,\nקופה של צדקה הר יונה")

win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1400, 1000)
win.show()
for _ in range(4):
    app.processEvents()

tab = win.mails_tab
win.navigate_to_tab(tab)
tab.refresh()
tab.tpl_combo.setCurrentIndex(1)
# v3.50: עיצוב — הדגשה אדומה + קו תחתון + רשימה, כדי שהסרגל והתצוגה המקדימה יראו אותו
from PyQt6.QtGui import QTextCursor, QTextListFormat, QColor, QTextCharFormat
_c = tab.body.textCursor(); _c.setPosition(0); _c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
tab.body.setTextCursor(_c); tab._toggle_bold()
_f = QTextCharFormat(); _f.setForeground(QColor("#b91c1c")); tab._merge(_f)
_c = tab.body.textCursor(); _c.movePosition(QTextCursor.MoveOperation.End); tab.body.setTextCursor(_c)
tab._list(QTextListFormat.Style.ListDisc)
assert tab._fmt_btns["ul"].isChecked()
_c.movePosition(QTextCursor.MoveOperation.Start); tab.body.setTextCursor(_c)
assert tab._fmt_btns["bold"].isChecked(), "bold button should reflect cursor format"
from utils import mailer as _mailer
assert _mailer.is_rich(tab._body_markup()) and "<b>" in tab._body_markup()
tab._update_preview()
for _ in range(6):
    app.processEvents()
os.makedirs("dev/_shots", exist_ok=True)
inner = tab.findChild(QScrollArea).widget()
inner.grab().save("dev/_shots/mails_tab.png")
tab.grab().save("dev/_shots/mails_tab_full.png")
tab.preview.grab().save("dev/_shots/mails_preview.png")
# v3.41: הלוגו בתצוגה המקדימה חייב להיות קטן (44px) — לא בגודל הקובץ (725px)
from PyQt6.QtGui import QTextImageFormat
doc = tab.preview.document()
blk = doc.begin(); imgs = []
while blk.isValid():
    it = blk.begin()
    while not it.atEnd():
        fr = it.fragment().charFormat()
        if fr.isImageFormat():
            imgs.append((fr.toImageFormat().width(), fr.toImageFormat().height()))
        it += 1
    blk = blk.next()
assert imgs and all(w == 44 and h == 44 for w, h in imgs), imgs
assert doc.defaultFont().pixelSize() >= 15, doc.defaultFont().pixelSize()

# assert-ים בסיסיים
oks = [t for t in tab._targets if t["ok"]]
assert len(tab._targets) == 6, tab._targets
assert len(oks) == 3, [t["reason"] for t in tab._targets]     # cohen, levi, gold (כפול/ריק/שבור נפסלים)
assert tab.btn_send.isEnabled(), "send should be enabled with SMTP configured"
assert "3" in tab.lbl_summary.text()
assert tab.hist.rowCount() == 2
from PyQt6.QtWidgets import QPushButton
_row_stopped = next(i for i, c in enumerate(tab._camps) if c["guid"] == g2)
_btns = [b.text() for b in tab.hist.cellWidget(_row_stopped, tab._HIST_ACT).findChildren(QPushButton)]
assert "שלח שוב לנכשלים" in _btns, _btns          # v3.43: גם כשנכשלו=0
assert tab.lbl_preview_title.text().startswith("כך זה ייראה אצל ") and len(tab.lbl_preview_title.text()) > 18, tab.lbl_preview_title.text()

# ── v3.55: המסך המעוצב — חיוויים, ✓ בשלבים, מסנן, חיפוש, מצבים, 130% ────────────
import styles   # noqa: E402
from PyQt6.QtCore import QPoint   # noqa: E402


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def grab_ok(widget, path, min_bytes=40_000, pct=100):
    for _attempt in range(4):
        widget.grab().save(path)
        if os.path.getsize(path) >= min_bytes:
            return
        styles.apply_app_theme(app, pct)
        widget.repaint()
        pump(12)
    raise AssertionError(f"blank grab: {path}")


def fits(w, host):
    p = w.mapTo(host, QPoint(0, 0))
    return p.x() >= 0 and p.x() + w.width() <= host.width() + 1


assert "3" in tab.chip_ready.text() and "יקבלו" in tab.chip_ready.text(), tab.chip_ready.text()
assert "מוכנה" in tab.chip_msg.text(), tab.chip_msg.text()
assert tab.card_list.badge.text() == "✓" and tab.card_msg.badge.text() == "✓"
assert "ל-3" in tab.btn_send.text(), tab.btn_send.text()
assert "☑" in tab.lbl_summary.text() and "☐" not in tab.lbl_summary.text(), tab.lbl_summary.text()
assert "6" in tab.btn_mode_all.text(), tab.btn_mode_all.text()
assert tab.hist.columnCount() == 7 and "נעצר" in tab.hist.item(_row_stopped, 3).text()
assert tab.btn_preview_next.isVisible()
_t0 = tab.lbl_preview_title.text(); tab._preview_next(); pump()
assert tab.lbl_preview_title.text() != _t0, "preview should move to another recipient"
# מסנן "בלי מייל" + חיפוש
assert tab.btn_show_bad.isVisible()
tab.btn_show_bad.setChecked(True); pump()
_vis = [i for i in range(tab.table.rowCount()) if not tab.table.isRowHidden(i)]
assert len(_vis) == 3 and all(not tab._targets[i]["ok"] for i in _vis), _vis
assert "תקן" in tab.table.item(_vis[0], 2).text()
grab_ok(inner, "dev/_shots/mails_v355_filter.png")
tab.btn_show_bad.setChecked(False)
tab.list_search.setVisible(True); tab.list_search.setText("לוי"); pump()
assert sum(1 for i in range(tab.table.rowCount()) if not tab.table.isRowHidden(i)) == 1
tab.list_search.clear()
# הסרה בלחיצה על "✕ הסר"
tab._on_cell_clicked(0, 3); pump()
assert len(tab._targets) == 5
tab._set_mode(tab.MODE_ALL); pump()
assert len(tab._targets) == 6
for w_ in (tab.btn_send, tab.btn_test, tab.chips_row, tab.table, tab.hist, tab.preview):
    assert fits(w_, tab), w_
grab_ok(inner, "dev/_shots/mails_v355_loaded.png")
grab_ok(tab, "dev/_shots/mails_v355_window.png")

# מצב ריק: בחירה ידנית, בלי נושא/תוכן
tab.btn_mode_manual.click(); tab.tpl_combo.setCurrentIndex(0)
tab.subject.clear(); tab.body.clear(); tab._update_preview(); pump()
assert tab.lbl_list_empty.isVisible() and not tab.table.isVisible()
assert tab.card_list.badge.text() == "1" and tab.card_msg.badge.text() == "2"
assert "☐" in tab.lbl_summary.text() and not tab.btn_send.isEnabled()
assert "אין עדיין" in tab.chip_ready.text() and "עוד לא" in tab.chip_msg.text()
grab_ok(inner, "dev/_shots/mails_v355_empty.png")

# 130% — שום דבר לא חורג מרוחב החלון
tab.btn_mode_all.click(); tab.tpl_combo.setCurrentIndex(1)
styles.apply_app_theme(app, 130); pump(12)
tab._update_preview(); pump(8)
for w_ in (tab.btn_send, tab.btn_test, tab.chips_row, tab.table, tab.hist, tab.preview, tab.lbl_summary):
    assert fits(w_, tab), ("130%", w_)
grab_ok(tab, "dev/_shots/mails_v355_130.png", pct=130)
styles.apply_app_theme(app, 100); pump(8)

# הגדרות — כרטיס Google
st = win.settings_tab
win.navigate_to_tab(st)
st.refresh()
for _ in range(6):
    app.processEvents()
st.findChild(QScrollArea).widget().grab().save("dev/_shots/mails_settings.png")
assert not st.btn_google_connect.isEnabled(), "no client id → button disabled"
assert st.btn_google_client.isVisible() and st.lbl_google_help.isVisible()
inner_s = st.findChild(QScrollArea).widget()
assert inner_s.minimumSizeHint().width() <= 1200, inner_s.minimumSizeHint().width()
print("OK shots + asserts")

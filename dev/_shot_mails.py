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
tab._update_preview()
for _ in range(6):
    app.processEvents()
os.makedirs("dev/_shots", exist_ok=True)
inner = tab.findChild(QScrollArea).widget()
inner.grab().save("dev/_shots/mails_tab.png")
tab.grab().save("dev/_shots/mails_tab_full.png")

# assert-ים בסיסיים
oks = [t for t in tab._targets if t["ok"]]
assert len(tab._targets) == 6, tab._targets
assert len(oks) == 3, [t["reason"] for t in tab._targets]     # cohen, levi, gold (כפול/ריק/שבור נפסלים)
assert tab.btn_send.isEnabled(), "send should be enabled with SMTP configured"
assert "3" in tab.lbl_summary.text()
assert tab.hist.rowCount() == 1
assert tab.lbl_preview_title.text().startswith("כך זה ייראה אצל ") and len(tab.lbl_preview_title.text()) > 18, tab.lbl_preview_title.text()

# הגדרות — כרטיס Google
st = win.settings_tab
win.navigate_to_tab(st)
st.refresh()
for _ in range(6):
    app.processEvents()
st.findChild(QScrollArea).widget().grab().save("dev/_shots/mails_settings.png")
assert not st.btn_google_connect.isEnabled(), "no client id → button disabled"
print("OK shots + asserts")

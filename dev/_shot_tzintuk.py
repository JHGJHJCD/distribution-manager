# -*- coding: utf-8 -*-
"""צילום אימות למסך הצינתוקים המחודש (v3.53, /שפר-מסך):
מצב ריק (שלושה אריחים) · רשימה טעונה + תזמון ממתין + כרטיס "ההודעה הנוכחית" ·
בזמן שליחה · עמוד מלא · וגם ב-130% גודל-טקסט. עם assert-ים על המבנה
(ווידג'טים קיימים, גלויים, בלי גלילה אופקית).
⚠ אימות ה-PNG רק דרך gemini_task.py -f — לא לקרוא PNG לתוך הצ'אט (נטפרי)."""
import os, sys, json, tempfile, importlib.util
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

# המאגר וההיסטוריה של המחשב האמיתי לא נוגעים — תיקייה זמנית
from utils import tts, yemot, call_history
_tmp = tempfile.mkdtemp()
tts.recordings_dir = lambda: _tmp
call_history.cache_path = lambda: os.path.join(_tmp, "yemot_history.json")

import tabs.tzintukim as tzmod
tzmod._PollWorker.start = lambda self: None
tzmod._TaskWorker.start = lambda self: None
tzmod._CallbackWorker.start = lambda self: None
tzmod.TzintukimTab._probe_connection = lambda self, force=False: None   # בלי רשת

app, win = shot.boot()
import database as db

names = [("כהן יוסף", "052-1234567", "053-9876543"), ("לוי שרה", "050-7654321", ""),
         ("פרידמן משה", "04-6543210", ""), ("אברהם דוד", "", ""),
         ("מזרחי רחל", "054-1112233", ""), ("ביטון אליהו", "058-4445566", "052-1234567"),
         ("שלום חנה", "053-7778899", ""), ("גולדברג יעקב", "050-2223344", "")]
for nm, p1, p2 in names:
    db.add_recipient({"full_name": nm, "phone1": p1, "phone2": p2, "status": "פעיל",
                      "frequency": "שבועי", "priority": 4, "souls": 4})
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "1234")
db.set_setting("yemot_template_id", "1430692")
yemot.set_recording_info("חלוקת פרשת כי-תבוא", source="tts", device="מחשב המנהל")
wav = os.path.join(_tmp, "src.wav")
with open(wav, "wb") as f:
    f.write(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x10\x00\x00\x00\x01\x00\x01\x00"
            b"\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
tts.library_add(wav, "חלוקת פרשת כי-תבוא", source="tts")   # → "השמע במחשב"

now = datetime.now(timezone.utc)
week = db.next_wednesday().isoformat()
entries_ok = [{"phone": "0521234567", "name": "כהן יוסף", "ok": True, "status": "done", "answer": "1"},
              {"phone": "0507654321", "name": "לוי שרה", "ok": True, "status": "amd", "answer": "2"},
              {"phone": "0466543210", "name": "פרידמן משה", "failed": True, "status": "no_answer",
               "answer": ""}]


def _done(name, days, entries, dl=6, fl=2):
    g = db.add_tzintuk_campaign(name, "2026-09-02", "1430692", f"camp-{days}", 8,
                                device="מחשב המנהל",
                                sent_at=(now - timedelta(days=days)).isoformat())
    db.update_tzintuk_campaign(g, dl, fl, "done", json.dumps(entries, ensure_ascii=False))


_done("חלוקת פרשת כי-תבוא", 4, entries_ok)
_done("חלוקת פרשת כי-תצא", 11, entries_ok)
_done("חלוקת פרשת שופטים", 18,
      entries_ok[:1] + [{"phone": "0541112233", "name": "מזרחי רחל", "status": "pending",
                         "stopped": True}], dl=3, fl=1)
db.add_tzintuk_campaign("צינתוק מתוזמן — חלוקה של השבוע", week, "5001", "s-0", 8,
                        sent_at=((datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)).isoformat(),
                        device="מחשב המנהל", status="scheduled")

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QScrollArea, QPushButton
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900)
win.show()
app.processEvents(); app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)


def pump(n=8):
    for _ in range(n):
        app.processEvents()


import styles
_pct = [100]


def grab_ok(widget, path, min_bytes=40_000):
    """Grab with a retry: a WA_DontShowOnScreen grab sometimes paints black
    (visual-check trap) — re-apply the theme to wake the widget and try again."""
    for _attempt in range(4):
        widget.grab().save(path)
        if os.path.getsize(path) >= min_bytes:
            return
        styles.apply_app_theme(app, _pct[0])
        widget.repaint()
        pump(12)
    raise AssertionError(f"blank grab: {path}")


def fits(w, host):
    """The widget sits fully inside the host (no overflow past the edges)."""
    p = w.mapTo(host, QPoint(0, 0))
    return p.x() >= 0 and p.x() + w.width() <= host.width() + 1


win.group_tab.refresh()            # the recipients were seeded after the window was built
win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz.refresh()
tz._apply_conn_state({"ok": True, "units": 1834})
tz._refresh_sched_banner()
pump(30)
scroll = tz.findChild(QScrollArea)

# ── מצב ריק: אריחים, תגי-שלב, צ'יפים ────────────────────────────────────────
assert tz.load_frame.isVisible() and not tz.list_frame.isVisible(), "empty state: tiles"
assert tz.card_list.badge.text() == "1", tz.card_list.badge.text()
assert tz.card_msg.badge.text() == "✓", "message badge should be ✓ (a recording exists)"
assert "עוד לא נטענה" in tz.chip_ready.text(), tz.chip_ready.text()
assert tz.chip_msg.isVisible() and "הודעה מוכנה" in tz.chip_msg.text(), tz.chip_msg.text()
assert tz.chip_sched.isVisible() and "תזמון" in tz.chip_sched.text(), tz.chip_sched.text()
assert not tz.btn_switch.isVisible(), "switch button hidden while nothing is loaded"
assert "«חלוקת פרשת כי-תבוא»" in tz.lbl_rec_name.text(), tz.lbl_rec_name.text()
assert tz.btn_play_local.isVisible(), "a local copy exists → the play button shows"
assert not tz.btn_send.isEnabled()
assert "טען רשימת נמענים" in tz.lbl_summary.text(), tz.lbl_summary.text()
# v3.54 — one "later ▾" menu button; the two schedule buttons live on as hidden attributes
assert tz.btn_later.isVisible() and not tz.btn_later.isEnabled(), "later menu (empty)"
assert tz.btn_sched.isHidden() and tz.btn_smart.isHidden()
assert tz.chips_row.isVisible() and tz.lbl_ok.parentWidget() is tz.chips_row
assert "יתרה: 1,834 יחידות" in tz.lbl_ok.text(), tz.lbl_ok.text()
assert tz.btn_hist_sync.text() == "רענן עכשיו", tz.btn_hist_sync.text()
assert scroll.horizontalScrollBar().maximum() == 0, "no horizontal scroll (empty)"
assert "משפחות" in tz.lbl_tile_week.text(), tz.lbl_tile_week.text()
grab_ok(tz, os.path.join(out,"tzintuk_v354_empty.png"))

# ── רשימה טעונה ─────────────────────────────────────────────────────────────
tz._load_week_list()
pump(12)
assert tz.list_frame.isVisible() and not tz.load_frame.isVisible()
assert tz.card_list.badge.text() == "✓"
assert tz.btn_switch.isVisible() and tz.week_frame.isVisible() and tz.batch_frame.isHidden()
assert "רשימת החלוקה הנוכחית" in tz.lbl_week.text(), tz.lbl_week.text()
assert tz.table.rowCount() == 8, tz.table.rowCount()
bad = sum(1 for r in tz._rows if r["why"]); ready = len(tz._ready_rows())
assert (bad, ready) == (1, 7), (bad, ready)
assert tz.btn_send.isEnabled() and "שלח עכשיו ל-7" in tz.btn_send.text(), tz.btn_send.text()
assert "7 מוכנים" in tz.chip_ready.text(), tz.chip_ready.text()
assert "☑ 7 נמענים" in tz.lbl_summary.text() and "חריג" in tz.lbl_summary.text(), tz.lbl_summary.text()
rows_names = [tz.table.item(r, 1).text() for r in range(tz.table.rowCount())]
i_bad = next(r for r, n in enumerate(rows_names) if n.startswith("אברהם"))
assert tz.table.item(i_bad, 3).text().startswith("⚠ אין מספר"), tz.table.item(i_bad, 3).text()
assert "תקן…" in tz.table.item(i_bad, 3).text(), tz.table.item(i_bad, 3).text()
assert tz.btn_later.isEnabled(), "later menu enabled with a loaded list"
i_ok = next(r for r, row in enumerate(tz._rows) if row["checked"] and row["send"])
assert "תקן" not in tz.table.item(i_ok, 3).text()
assert tz.table.item(i_ok, 3).text() == "● מוכן", tz.table.item(i_ok, 3).text()
# צ'יפ החריגים כמסנן
tz.m_bad["frame"].setChecked(True); pump(3)
visible = [r for r in range(tz.table.rowCount()) if not tz.table.isRowHidden(r)]
assert visible == [i_bad], visible
assert "הצג את כולם" in tz.m_bad["frame"].text(), tz.m_bad["frame"].text()
tz.m_bad["frame"].setChecked(False); pump(3)
assert all(not tz.table.isRowHidden(r) for r in range(tz.table.rowCount()))
# ביטול סימון של שורה מעדכן את תא המצב חי
it0 = tz.table.item(i_ok, 0)
it0.setCheckState(Qt.CheckState.Unchecked); pump(2)
assert tz.table.item(i_ok, 3).text().startswith("לא נשלח"), tz.table.item(i_ok, 3).text()
assert "6 מוכנים" in tz.chip_ready.text(), tz.chip_ready.text()
it0.setCheckState(Qt.CheckState.Checked); pump(2)
assert tz.table.item(i_ok, 3).text() == "● מוכן"
# היסטוריה: 7 עמודות, עמודת מצב, "מחר HH:MM", "לא הגיבו"
assert tz.hist.columnCount() == 7 and tz.hist.rowCount() == 4, (tz.hist.columnCount(), tz.hist.rowCount())
statuses = [tz.hist.item(r, 2).text() for r in range(tz.hist.rowCount())]
assert "⏳ מתוזמן" in statuses and "✓ הסתיים" in statuses and "⛔ נעצר באמצע" in statuses, statuses
whens = [tz.hist.item(r, 0).text() for r in range(tz.hist.rowCount())]
assert any(w.startswith("מחר") for w in whens), whens
assert any("לא הגיבו" in tz.hist.item(r, 6).text() for r in range(tz.hist.rowCount()))
assert scroll.horizontalScrollBar().maximum() == 0, "no horizontal scroll (loaded)"
for w in (tz.chip_ready, tz.chip_msg, tz.chip_sched, tz.lbl_ok, tz.btn_send, tz.btn_switch):
    assert fits(w, tz), f"{w.objectName() or w.text()} overflows"
grab_ok(tz, os.path.join(out,"tzintuk_v354_loaded.png"))
grab_ok(scroll.widget(), os.path.join(out, "tzintuk_v354_fullpage.png"))

# ── חלון האישור (v3.54: כרטיס-עובדות + שני אריחים, קלאסי כברירת מחדל) ───────
facts, warns = tz._send_facts(7, 9, 1, None)
dlg = tzmod._SendModeDialog("סיכום", tz, facts=facts, warnings=warns)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(620, dlg.sizeHint().height()); dlg.show(); pump(8)
assert dlg.rb_classic.isChecked() and not dlg.rb_voice.isChecked(), "classic is the default"
assert dlg.btn_cancel.isDefault() and not dlg.btn_ok.isDefault()
dlg.rb_voice.setChecked(True); pump(2)
assert dlg._tiles[dlg.rb_voice].property("on") == "true"
grab_ok(dlg, os.path.join(out, "tzintuk_v354_confirm.png"))
dlg.close()

# ── בזמן שליחה (רצועת ההתקדמות; ויזואלי בלבד) ───────────────────────────────
tz.prog_frame.setVisible(True)
tz.lbl_prog.setText("שולח בזמן אמת… אפשר להמשיך לעבוד, אל תסגור את התוכנה")
tz.progress.setRange(0, 9); tz.progress.setValue(4)
tz.lbl_ans.setText(tz._answers_html({"1": 1, "2": 0, "3": 0, "": 0}))
tz.lbl_done.setText("הצליחו 4"); tz.lbl_fail.setText("נכשלו 1"); tz.lbl_wait.setText("ממתינים 4")
tz.btn_stop_send.setVisible(True)
pump(6)
grab_ok(tz, os.path.join(out,"tzintuk_v354_sending.png"))
tz.prog_frame.setVisible(False); tz.btn_stop_send.setVisible(False)

# ── 130% גודל-טקסט — הפריסה לא נשברת ─────────────────────────────────────────
_pct[0] = 130
styles.apply_app_theme(app, 130)
pump(10)
tz.refresh(); tz._apply_conn_state({"ok": True, "units": 1834})
pump(12)
assert scroll.horizontalScrollBar().maximum() == 0, "130%: no horizontal scroll"
for w in (tz.chip_ready, tz.chip_msg, tz.chip_sched, tz.lbl_ok, tz.btn_send, tz.btn_switch,
          tz.btn_later, tz.lbl_summary):
    assert fits(w, tz), f"130%: {w.text()} overflows"
print("chips row height @130%:", tz.chips_row.height(), "one chip:", tz.lbl_ok.height())
grab_ok(tz, os.path.join(out,"tzintuk_v354_130.png"))
print("scroll content height:", scroll.widget().height(), "viewport:", scroll.viewport().height())
print("table rows:", tz.table.rowCount(), "hist rows:", tz.hist.rowCount())
print("OK")

# -*- coding: utf-8 -*-
"""בדיקות שרת המענה לחזרה-לצינתוק (utils/callback_server.py, v3.33) — בלי רשת:
התחבורה מוזרקת (callback_server._TRANSPORT) ומחזירה תשובות-שרת מוקלטות.

מכסה: גוף הדחיפה (נרמול + כפולים), פירוק התשובות לצורת השורה של הסקר, דילוג על
שורות פגומות, זיהוי נטפרי (418 → קוד -3), סוד שגוי (403), backoff אחרי כישלון,
ומיזוג לתוך yemot.fetch_survey_rows — כבוי = לא נוגע, דלוק = מאוחד, כישלון = שקט.
"""
import os, sys, json, tempfile, urllib.error
from datetime import datetime, timezone
from utils import call_history   # המטמון האמיתי של המחשב לא נכנס לבדיקות
import tempfile as _tf
_hist_dir = _tf.mkdtemp(prefix="yhist_")
call_history.cache_path = lambda: os.path.join(_hist_dir, "yemot_history.json")
call_history._memo.update(path=None, mtime=None, data=None)
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

import database as db
from utils import yemot, netblock
from utils import callback_server as cb

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


root = tempfile.mkdtemp(prefix="cb_test_")
db.DB_PATH = os.path.join(root, "data.db")
db.BACKUP_DIR = os.path.join(root, "backups")
db.init_db()

# ── 1. גוף הדחיפה ────────────────────────────────────────────────────────────
print("— גוף הדחיפה (/push) —")
body = cb.push_payload("2026-09-09", {"052-123-4567": "כהן", "+972521234567": "כפול",
                                     "לא מספר": "פסול", "04-6543210": ""})
ok("dist_date עובר", body["dist_date"] == "2026-09-09")
ok("מספרים מנורמלים", [p["phone"] for p in body["phones"]] == ["0521234567", "046543210"])
ok("כפול אחרי נרמול נשמט", len(body["phones"]) == 2)
ok("שם ריק → מחרוזת ריקה", body["phones"][1]["name"] == "")

# ── 2. פירוק התשובות (/answers) ─────────────────────────────────────────────
print("— פירוק התשובות —")
payload = {"answers": [
    {"phone": "0521234567", "answer": "1", "at": "2026-09-08 10:15:00", "dist_date": "2026-09-09"},
    {"phone": "972501112233", "answer": "2", "at": "2026-09-08T11:00:00Z"},
    {"phone": "", "answer": "1", "at": "2026-09-08 10:15:00"},            # בלי טלפון
    {"phone": "0501112233", "answer": "", "at": "2026-09-08 10:15:00"},   # בלי תשובה
    {"phone": "0501112233", "answer": "3", "at": "לא זמן"},               # זמן פגום
    "junk",
]}
rows = cb.parse_answer_rows(json.dumps(payload).encode("utf-8"))
ok("שתי שורות תקינות בלבד", len(rows) == 2, str(len(rows)))
ok("צורת השורה = של הסקר", set(rows[0]) == {"phone", "at", "answer"})
ok("זמן SQLite נקרא כ-UTC aware",
   rows[0]["at"] == datetime(2026, 9, 8, 10, 15, tzinfo=timezone.utc))
ok("ISO עם Z נקרא", rows[1]["at"] == datetime(2026, 9, 8, 11, 0, tzinfo=timezone.utc))
ok("972 מנורמל ל-05", rows[1]["phone"] == "0501112233")
ok("תשובה נשמרת כמחרוזת", rows[0]["answer"] == "1")
ok("payload פגום → []", cb.parse_answer_rows(b"not json") == [])

# ── 3. תחבורה: הצלחה, נטפרי, סוד שגוי ───────────────────────────────────────
print("— תחבורה —")
db.set_setting(cb.SET_URL, "https://example.invalid")
db.set_setting(cb.SET_SECRET, "S3CRET")
db.set_setting(cb.SET_ENABLED, "1")
calls = []
def transport_ok(url, data):
    calls.append((url, data))
    if "/push" in url:
        return b'{"ok":true,"count":2}'
    return json.dumps(payload).encode("utf-8")
cb._TRANSPORT = transport_ok
cb._backoff_until = 0.0
n = cb.push_week_list("2026-09-09", {"0521234567": "כהן", "046543210": "לוי"})
ok("push מחזיר את הספירה של השרת", n == 2)
ok("push נשלח ל-/push עם הסוד", calls[-1][0].startswith("https://example.invalid/push?") and "secret=S3CRET" in calls[-1][0])
sent = json.loads(calls[-1][1].decode("utf-8"))
ok("גוף ה-push = JSON עם הרשימה", sent["dist_date"] == "2026-09-09" and len(sent["phones"]) == 2)
ok("fetch_answer_rows קורא /answers", len(cb.fetch_answer_rows()) == 2 and "/answers?" in calls[-1][0])
ok("check_connection מחזיר כמות", cb.check_connection() == 2)

def transport_418(url, data):
    raise urllib.error.HTTPError(url, 418, "I'm a teapot", {}, None)
cb._TRANSPORT = transport_418
cb._backoff_until = 0.0
try:
    cb.push_week_list("2026-09-09", {"0521234567": ""})
    ok("418 מעלה CallbackError", False)
except cb.CallbackError as e:
    ok("418 = נטפרי, קוד -3, הודעה אחידה", e.code == -3 and str(e) == netblock.NETFREE_MSG)

def transport_403(url, data):
    raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
cb._TRANSPORT = transport_403
cb._backoff_until = 0.0
try:
    cb.fetch_answer_rows()
    ok("403 מעלה CallbackError", False)
except cb.CallbackError as e:
    ok("403 = סוד שגוי, בעברית", e.code == 403 and "סוד" in str(e))
ok("אחרי כישלון — backoff פעיל (בלי קריאה נוספת)", cb.fetch_answer_rows() == [])

# ── 4. מיזוג לתוך yemot.fetch_survey_rows ───────────────────────────────────
print("— מיזוג עם הסקר —")
survey_txt = "Phone#0509998877%Date#08/09/2026%Time#12:00:00%P050#1"
yemot._TRANSPORT = lambda url, data: survey_txt.encode("utf-8")
db.set_setting(yemot.SET_SYSTEM, "0771234567"); db.set_setting(yemot.SET_PASSWORD, "x")

db.set_setting(cb.SET_ENABLED, "0")
cb._TRANSPORT = transport_ok; cb._backoff_until = 0.0
before = len(calls)
rows = yemot.fetch_survey_rows()
ok("כבוי: רק שורות הסקר, השרת לא נקרא", len(rows) == 1 and len(calls) == before)

db.set_setting(cb.SET_ENABLED, "1")
cb._backoff_until = 0.0
rows = yemot.fetch_survey_rows()
ok("דלוק: שורות הסקר + השרת מאוחדות", len(rows) == 3, str(len(rows)))
ok("כל השורות באותה צורה", all(set(r) == {"phone", "at", "answer"} for r in rows))

cb._TRANSPORT = transport_418; cb._backoff_until = 0.0
rows = yemot.fetch_survey_rows()
ok("השרת נכשל: הסקר ממשיך לעבוד (שקט)", len(rows) == 1)

# merge_survey_answers מקבל את השורות של השרת כמו של הסקר
cb._TRANSPORT = transport_ok; cb._backoff_until = 0.0
entries = [{"phone": "0521234567"}, {"phone": "0501112233"}, {"phone": "0509998877"}]
entries, changed = yemot.merge_survey_answers(entries, yemot.fetch_survey_rows(),
                                              since_iso="2026-09-08T00:00:00+00:00")
ok("תשובה מהשרת נחתמת על הרשומה", entries[0]["answer"] == "1" and entries[1]["answer"] == "2")
ok("תשובת הסקר עדיין נחתמת", entries[2]["answer"] == "1")

print()
if fails:
    print(f"FAILED: {len(fails)}")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CALLBACK-SERVER TESTS PASSED")

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

# ── 5. שלוחת ה-API בקו (v3.34): בדיקה לפני חיוג + תיקון של הקובץ שלה בלבד ────
print("— שלוחה 76 בקו —")
db.set_setting(cb.SET_URL, "https://example.workers.dev/")
good = "type=api\ntitle=שרת המענה (מנהל חלוקה) — בדיקה\napi_link=https://example.workers.dev\n"
ok("שלוחה תקינה (כותרת אחרת לא מפריעה)", cb.extension_problem(good) == "")
ok("CRLF + סלאש בסוף הכתובת = תקין",
   cb.extension_problem(good.replace("\n", "\r\n").replace("workers.dev\r\n", "workers.dev/\r\n").encode("utf-8")) == "")
ok("אין קובץ (JSON מהשרת) = לא קיימת", "לא קיימת" in cb.extension_problem('{"responseStatus":"ERROR"}'))
ok("ריק = לא קיימת", "לא קיימת" in cb.extension_problem(b""))
ok("סוג אחר = שונתה", "לא שלוחת API" in cb.extension_problem("type=menu\napi_link=https://example.workers.dev"))
ok("כתובת אחרת = מצביעה לשרת אחר",
   "כתובת אחרת" in cb.extension_problem("type=api\napi_link=https://other.example.com"))
exp = cb.expected_ext_ini()
ok("ה-ext.ini הצפוי תקין בעצמו", cb.extension_problem(exp) == "" and "type=api" in exp)
ok("ה-ext.ini הצפוי: בלי מוזיקת המתנה + חזרה לתפריט (כל מתקשר ל-04 עובר דרכה)",
   "api_wait_answer_music_on_hold=no" in exp and "api_end_goto=/" in exp)

# verify_extension קורא דרך DownloadFile של ימות; repair_extension כותב רק ivr2:/76/ext.ini
ycalls = []
def ytransport(url, data):
    ycalls.append((url, data))
    if "DownloadFile" in url:
        return good.encode("utf-8")
    return b'{"responseStatus":"OK"}'
yemot._TRANSPORT = ytransport
ok("verify_extension: קריאה בלבד, תקין", cb.verify_extension() == "" and "DownloadFile" in ycalls[-1][0]
   and "ivr2%3A%2F76%2Fext.ini" in ycalls[-1][0])
ycalls.clear()
cb.repair_extension()
ok("repair_extension: כתיבה אחת בלבד", len(ycalls) == 1 and "UploadFile" in ycalls[0][0])
body = ycalls[0][1] or b""
ok("repair_extension: הנתיב הוא של שלוחה 76 בלבד",
   b"ivr2:/76/ext.ini" in body and b"ivr2:/ext.ini" not in body and b'name="convertAudio"\r\n\r\n0' in body)
ok("repair_extension: התוכן = הצפוי", exp.encode("utf-8") in body)
yemot._TRANSPORT = lambda url, data: b'{"responseStatus":"ERROR","message":"file not found"}'
ok("verify_extension: השרת ענה JSON = לא קיימת", "לא קיימת" in cb.verify_extension())
def ynet(url, data):
    raise urllib.error.URLError("down")
yemot._TRANSPORT = ynet
try:
    cb.verify_extension(); ok("verify_extension: תקלת רשת מעלה חריגה", False)
except yemot.YemotError as e:
    ok("verify_extension: תקלת רשת מעלה חריגה (לא 'לא קיימת')", e.code == -1)
yemot._TRANSPORT = None

# החיבור למסך: הבדיקה רצה אחרי _recording_ready בכל 5 פעולות החיוג, ולא חוסמת כשאין קריאה
src = open("tabs/tzintukim.py", encoding="utf-8").read()
ok("_callback_ext_ready מחובר ל-5 פעולות החיוג", src.count("if not self._callback_ext_ready(") == 5)
body_fn = src.split("def _callback_ext_ready")[1].split("\n    def ")[0]
ok("_callback_ext_ready: תקלת קריאה לא חוסמת חיוג", "except Exception:\n            return True" in body_fn)
ok("_callback_ext_ready: ברירת-מחדל = ביטול", "box.setDefaultButton(cancel)" in body_fn)
ok("_callback_ext_ready: כבוי = לא נוגע בקו", "if not self._cb_server_on():\n            return True" in body_fn)

# ── 6. v3.36 — רשימה לכל חלוקה + active_from (תזמון / שיגור חכם) + החיבור למסך ──
print("— v3.36: push בתזמון ובשיגור חכם —")
from datetime import datetime as _dt
body = cb.push_payload("2026-09-16", {"0521234567": "כהן", "0501112233": "לוי"})
ok("שליחה מיידית: בלי active_from בכלל", "active_from" not in body
   and all("active_from" not in p for p in body["phones"]))
when = _dt(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
body = cb.push_payload("2026-09-16", {"0521234567": "כהן"}, active_from=when)
ok("תזמון: active_from כללי ב-ISO UTC", body["active_from"] == "2026-09-16T10:00:00+00:00")
body = cb.push_payload("2026-09-16", {"0521234567": "כהן"}, active_from="2026-09-16T07:00:00+00:00")
ok("active_from כמחרוזת עובר כמו שהוא", body["active_from"] == "2026-09-16T07:00:00+00:00")
body = cb.push_payload("2026-09-16", {"052-123-4567": "כהן", "0501112233": "לוי", "0541111111": "בלי"},
                       active_by_phone={"0521234567": when, "+972501112233": "2026-09-16T12:00:00+00:00"})
per = {p["phone"]: p.get("active_from") for p in body["phones"]}
ok("שיגור חכם: active_from אישי לכל מספר (מנורמל בשני הצדדים)",
   per["0521234567"] == "2026-09-16T10:00:00+00:00" and per["0501112233"] == "2026-09-16T12:00:00+00:00")
ok("מספר בלי שעה אישית = בלי active_from (פעיל מיד / לפי הכללי)", per["0541111111"] is None
   and "active_from" not in body)
ok("naive datetime נחשב UTC", cb._iso_utc(_dt(2026, 1, 1, 8, 0)) == "2026-01-01T08:00:00+00:00")

cb._TRANSPORT = transport_ok; cb._backoff_until = 0.0
calls.clear()
cb.clear_week_list("2026-09-16")
sent = json.loads(calls[-1][1].decode("utf-8"))
ok("clear_week_list = push של רשימה ריקה לאותו תאריך", "/push" in calls[-1][0]
   and sent["dist_date"] == "2026-09-16" and sent["phones"] == [])

# החיבור למסך: push אחרי כל דרך חיוג-מרובה (שליחה/תזמון/שיגור חכם), פעם אחת לשיגור חכם,
# מחיקה בביטול, ולעולם לא בשליחה חוזרת (הרשימה של התאריך כבר מכילה את הנכשלים).
def _body(name):
    return src.split("def " + name)[1].split("\n    def ")[0]
ok("_send דוחף דרך _push_list", 'self._push_list(dist_date, phones, "הצינתוק יצא"' in _body("_send("))
ok("_schedule דוחף עם active_from=שעת השיגור",
   "self._push_list(dist_date, phones, \"התזמון נקבע\"" in _body("_schedule(") and "active_from=self._to_utc_iso(when)" in _body("_schedule("))
sm = _body("_smart_schedule(")
ok("_smart_schedule: push אחד עם active_by_phone", sm.count("self._push_list(") == 1 and "active_by_phone=active_by_phone" in sm)
ok("_resend_failed לא דוחף (היה מוחק את הרשימה המלאה)", "_push_list(" not in _body("_resend_failed(") and "_push_week_list(" not in _body("_resend_failed("))
ok("_cancel_sched מנקה בשרת דרך _clear_server_list", "self._clear_server_list(d)" in _body("_cancel_sched("))
pl = _body("_push_list(")
ok("_push_list: כבוי = לא נוגע; רץ ב-_run_blocking", "if not self._cb_server_on():\n            return" in pl and "self._run_blocking(" in pl)
cl = _body("_clear_server_list(")
ok("_clear_server_list: מוחק רק כשלא נשאר שום צינתוק לתאריך", '"scheduled", "sending", "stopping", "done"' in cl and "if left:\n            return" in cl)

# ── 7. v3.37 — מצב ההשמעה בחזרה לקו + העתקת ההקלטה לשלוחה 76 ─────────────────
print("— v3.37: מצב השמעה + הקלטה בשלוחה —")
db.set_setting(cb.SET_REC_STAMP, "")
db.set_setting(yemot.SET_REC_INFO, json.dumps({"name": "הודעה", "at": "2026-09-10T10:00:00+00:00"}))
body = cb.push_payload("2026-09-16", {"0521234567": "כהן"})
ok("ברירת מחדל: mode=both, recording=False כשלא הועתקה", body["mode"] == "both" and body["recording"] is False)
body = cb.push_payload("2026-09-16", {"0521234567": "כהן"}, mode="message")
ok("mode=message עובר", body["mode"] == "message")
body = cb.push_payload("2026-09-16", {"0521234567": "כהן"}, mode="junk")
ok("mode לא מוכר → both", body["mode"] == "both")
db.set_setting(cb.SET_REC_STAMP, "2026-09-10T10:00:00+00:00")
ok("חותמת תואמת = recording=True", cb.push_payload("d", {"0521234567": ""})["recording"] is True)
db.set_setting(yemot.SET_REC_INFO, json.dumps({"name": "חדשה", "at": "2026-09-11T10:00:00+00:00"}))
ok("הקלטה חדשה שטרם הועתקה = recording=False", cb.push_payload("d", {"0521234567": ""})["recording"] is False)
ok("last_mode ברירת מחדל both", cb.last_mode() == "both")
cb.remember_mode("message"); ok("remember_mode נשמר", cb.last_mode() == "message")
cb.remember_mode("bogus"); ok("remember_mode דוחה ערך לא מוכר", cb.last_mode() == "message")
cb.remember_mode("both")

# publish_recording: DownloadFile tpl:<id> → UploadFile ivr2:/76/msg.wav בלבד, בלי המרה, וחותמת
ycalls.clear()
def ytr(url, data):
    ycalls.append((url, data))
    if "DownloadFile" in url:
        return b"RIFF....WAVEfake"
    return b'{"responseStatus":"OK"}'
yemot._TRANSPORT = ytr
db.set_setting(yemot.SET_TEMPLATE, "1430692")
path = cb.publish_recording()
ups = [c for c in ycalls if "UploadFile" in c[0]]
ok("publish_recording: כתיבה אחת בלבד, ל-ivr2:/76/msg.wav", len(ups) == 1 and b"ivr2:/76/msg.wav" in (ups[0][1] or b"")
   and path == cb.REC_PATH)
ok("publish_recording: בלי המרה (כבר WAV טלפוני)", b'name="convertAudio"\r\n\r\n0' in (ups[0][1] or b""))
ok("publish_recording: החותמת = ה-at של ההקלטה", cb.recording_on_line())
yemot._TRANSPORT = None

# החיבור למסך: _CallbackModeBox בשלושת הדיאלוגים, המצב מועבר ל-_push_list, "none" מנקה
ok("_CallbackModeBox בשלושת הדיאלוגים", src.count("self.cb_box = _CallbackModeBox(self)") == 3)
ok("שלושת הדיאלוגים חושפים cb_mode", src.count("self.cb_mode = self.cb_box.mode") == 3)
ok("_send/_schedule/_smart_schedule מעבירים mode=dlg.cb_mode", src.count("mode=dlg.cb_mode or \"\"") == 3)
pw = src.split("def _push_week_list")[1].split("\n    def ")[0]
ok("mode=none → clear_week_list (לא push)", 'if mode == "none":' in pw and "callback_server.clear_week_list(dist_date)" in pw)
up = open("utils/yemot.py", encoding="utf-8").read().split("def upload_message_wav")[1].split("\ndef ")[0]
ok("upload_message_wav מעתיק ל-76 (publish_recording) ולא ל-78", "callback_server.publish_recording(" in up and "publish_callback_message(" not in up)

print()
if fails:
    print(f"FAILED: {len(fails)}")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CALLBACK-SERVER TESTS PASSED")

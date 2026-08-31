# -*- coding: utf-8 -*-
"""בדיקות מערכת הצינתוקים (utils/yemot.py + DB + sync, v2.81) — בלי רשת:
התחבורה מוזרקת (yemot._TRANSPORT) ומחזירה תשובות-שרת מוקלטות.

מכסה: נרמול טלפונים, בחירת מספרים למקבל, חוקי שעות-שליחה, בניית בקשות
(תבנית/קמפיין/סטטוס), מיפוי שגיאות לעברית, פירוק סטטוס קמפיין, רישום
היסטוריה ב-DB (idempotence + LWW), שומר שליחה-כפולה, וסנכרון בין 2 מחשבים.
"""
import os, sys, json, tempfile, urllib.parse
from datetime import datetime
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

import database as db
from utils import sync, yemot

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


root = tempfile.mkdtemp(prefix="tz_test_")
dir_a = os.path.join(root, "pc_a"); os.makedirs(dir_a)
dir_b = os.path.join(root, "pc_b"); os.makedirs(dir_b)
shared = os.path.join(root, "drive"); os.makedirs(shared)


def use_machine(d):
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")


use_machine(dir_a)
db.init_db()

# ── 1. נרמול טלפונים ─────────────────────────────────────────────────────────
print("— נרמול טלפונים —")
ok("נייד עם מקפים", yemot.normalize_phone("052-123-4567") == "0521234567")
ok("נייד עם רווחים", yemot.normalize_phone("050 765 4321") == "0507654321")
ok("קידומת ‎+972", yemot.normalize_phone("+972521234567") == "0521234567")
ok("קידומת 972 בלי פלוס", yemot.normalize_phone("972521234567") == "0521234567")
ok("קו נייח 9 ספרות", yemot.normalize_phone("04-6543210") == "046543210")
ok("מספר 077 (כשר/VOIP)", yemot.normalize_phone("077-3137770") == "0773137770")
ok("קצר מדי נפסל", yemot.normalize_phone("05-12") == "")
ok("אותיות נפסלות", yemot.normalize_phone("לא ידוע") == "")
ok("ריק/None נפסל", yemot.normalize_phone(None) == "" and yemot.normalize_phone("") == "")
ok("נייח בלי אזור נפסל", yemot.normalize_phone("6543210") == "")

rec = {"phone1": "052-1234567", "phone2": "052-1234567", "phone3": "04-6543210"}
ok("pick_phones מסיר כפולים ושומר סדר",
   yemot.pick_phones(rec) == ["0521234567", "046543210"])
ok("pick_phones בלי מספרים", yemot.pick_phones({"phone1": "אין"}) == [])

# ── 2. חוקי שעות שליחה ───────────────────────────────────────────────────────
print("— שעות שליחה —")
ok("יום חול בבוקר מותר",
   yemot.send_block_reason(datetime(2026, 9, 2, 10, 0)) == "")          # רביעי
ok("לילה חסום (23:00)", "21:00" in yemot.send_block_reason(datetime(2026, 9, 2, 23, 0)))
ok("בוקר מוקדם חסום (07:00)", "21:00" in yemot.send_block_reason(datetime(2026, 9, 2, 7, 0)))
ok("שבת חסומה", "שבת" in yemot.send_block_reason(datetime(2026, 9, 5, 11, 0)))     # שבת
ok("ערב שבת אחה\"צ חסום", "ערב שבת" in yemot.send_block_reason(datetime(2026, 9, 4, 14, 0)))
ok("שישי בבוקר מותר", yemot.send_block_reason(datetime(2026, 9, 4, 9, 0)) == "")

# ── 3. תחבורה מדומה — בקשות ותשובות ─────────────────────────────────────────
print("— בקשות API (מדומה) —")
calls = []          # (command, params dict)
canned = {}         # command → dict answer


def fake_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if data:
        try:
            params.update({k: v[0] for k, v in
                           urllib.parse.parse_qs(data.decode("utf-8")).items()})
        except UnicodeDecodeError:
            params["_raw"] = data          # multipart upload
    calls.append((command, params))
    answer = canned.get(command, {"responseStatus": "OK"})
    return json.dumps(answer, ensure_ascii=False).encode("utf-8")


yemot._TRANSPORT = fake_transport

ok("is_configured שלילי לפני הזנה", not yemot.is_configured())
try:
    yemot.check_connection()
    ok("בלי פרטי גישה — חריגה", False)
except yemot.YemotError as e:
    ok("בלי פרטי גישה — חריגה", "בהגדרות" in str(e))

db.set_setting(yemot.SET_SYSTEM, "0771234567")
db.set_setting(yemot.SET_PASSWORD, "123456")
ok("is_configured חיובי", yemot.is_configured())

canned["GetSession"] = {"responseStatus": "OK", "units": 512.5}
yemot.check_connection()
ok("GetSession נשלח עם token", calls[-1][0] == "GetSession"
   and calls[-1][1].get("token") == "0771234567:123456")
ok("get_balance קורא יחידות", yemot.get_balance() == 512.5)

canned["GetSession"] = {"responseStatus": "ERROR", "messageCode": 1,
                        "message": "Username or password is incorrect"}
try:
    yemot.check_connection()
    ok("סיסמה שגויה → שגיאה בעברית", False)
except yemot.YemotError as e:
    ok("סיסמה שגויה → שגיאה בעברית", "סיסמה שגויים" in str(e) and e.code == 1)

# תבנית: נוצרת פעם אחת בלבד ונשמרת ב-settings
canned["CreateTemplate"] = {"responseStatus": "OK", "templateId": 1117319}
tid = yemot.ensure_template()
ok("ensure_template יוצר ושומר", tid == "1117319"
   and db.get_setting(yemot.SET_TEMPLATE) == "1117319")
upd = [c for c in calls if c[0] == "UpdateTemplate"]
ok("סוג הקמפיין הוגדר REPEAT (מקשי אישור הגעה)",
   len(upd) == 1 and upd[0][1].get("yemotContext") == "REPEAT"
   and db.get_setting(yemot.SET_CONFIRM_CTX) == "1117319")
n_before = len(calls)
ok("ensure_template לא פונה שוב לשרת",
   yemot.ensure_template() == "1117319" and len(calls) == n_before)

# קמפיין: מספרים לא תקינים נופלים, שמות נכנסים ל-JSON
canned["RunCampaign"] = {"responseStatus": "OK", "templateId": 1117319,
                         "campaignId": "0771234567-1117319-2026-09-02-API",
                         "entriesCount": 2, "pending": 2, "blocked": 0,
                         "estimatedPrice": 2.0, "customerUnits": 510.5}
res = yemot.run_campaign({"0521234567": "כהן יוסף", "0507654321": "לוי שרה",
                          "05-12": "מספר שבור"})
sent = json.loads(calls[-1][1]["phones"])
ok("RunCampaign שולח רק תקינים", set(sent) == {"0521234567", "0507654321"})
ok("RunCampaign כולל שמות", sent["0521234567"]["name"] == "כהן יוסף")
ok("RunCampaign עם templateId", calls[-1][1].get("templateId") == "1117319")
ok("RunCampaign מחזיר campaignId", res["campaignId"].endswith("API"))
try:
    yemot.run_campaign({"05-12": "שבור"})
    ok("קמפיין בלי אף מספר תקין נחסם", False)
except yemot.YemotError:
    ok("קמפיין בלי אף מספר תקין נחסם", True)

# callerId נשלח רק כשהוגדר
db.set_setting(yemot.SET_CALLER_ID, "0771234567")
yemot.run_campaign({"0521234567": "כהן"})
ok("callerId נשלח כשמוגדר", calls[-1][1].get("callerId") == "0771234567")
db.set_setting(yemot.SET_CALLER_ID, "")

# שגיאת יחידות (103) בעברית
canned["RunCampaign"] = {"responseStatus": "ERROR", "messageCode": 103,
                         "message": "not enough units"}
try:
    yemot.run_campaign({"0521234567": "כהן"})
    ok("שגיאת יחידות בעברית", False)
except yemot.YemotError as e:
    ok("שגיאת יחידות בעברית", "יחידות" in str(e) and e.code == 103)

# מפתח API (ארוך/עם אותיות) נשלח לבדו כ-token, בלי מספר המערכת
db.set_setting(yemot.SET_PASSWORD, "AbCd1234EfGh5678IjKl")
canned["GetSession"] = {"responseStatus": "OK", "units": 1}
yemot.check_connection()
ok("מפתח API נשלח לבדו", calls[-1][1].get("token") == "AbCd1234EfGh5678IjKl")
db.set_setting(yemot.SET_SYSTEM, "")
ok("מפתח API מספיק בלי מספר מערכת", yemot.is_configured())
db.set_setting(yemot.SET_SYSTEM, "0771234567")
db.set_setting(yemot.SET_PASSWORD, "123456")
yemot.check_connection()
ok("סיסמה רגילה חוזרת לפורמט מספר:סיסמה",
   calls[-1][1].get("token") == "0771234567:123456")

# MFA_REQUIRED → הסבר בעברית על מפתח API
canned["GetSession"] = {"responseStatus": "ERROR", "message": "MFA_REQUIRED"}
try:
    yemot.check_connection()
    ok("שגיאת MFA מוסברת", False)
except yemot.YemotError as e:
    ok("שגיאת MFA מוסברת", "מפתח API" in str(e))
canned["GetSession"] = {"responseStatus": "OK", "units": 512.5}

# נפילה לשרת התאום: כשל רשת ב-www → private עונה
def flaky_transport(url, data):
    if "www.call2all" in url:
        raise yemot.YemotError("אין חיבור", code=-1)
    return fake_transport(url.replace("private.call2all", "www.call2all"), data)
yemot._TRANSPORT = flaky_transport
st_ok = yemot.check_connection()
ok("נפילה אוטומטית לשרת private", st_ok.get("responseStatus") == "OK")
yemot._TRANSPORT = fake_transport

# סטטוס קמפיין: ספירה, דגל סיום
canned["GetCampaignStatus"] = {"responseStatus": "OK", "campaign": {
    "campaignId": "x", "campaignStatus": "RUNNING", "templateId": 1117319,
    "blockedEntries": 0, "pendingEntries": 1, "activeEntries": 1,
    "doneEntries": 2, "totalEntries": 4, "entries": [
        {"phone": "0521111111", "name": "א", "entryStatus": "accepted"},
        {"phone": "0522222222", "name": "ב", "entryStatus": "no_answer"},
        {"phone": "0523333333", "name": "ג", "entryStatus": "ringing"},
        {"phone": "0524444444", "name": "ד", "entryStatus": "pending"},
    ]}}
st = yemot.get_campaign_status("x")
ok("סטטוס רץ — לא סיים", not st["finished"])
ok("ספירת נמסרו/נכשלו", st["delivered"] == 1 and st["failed"] == 1
   and st["pending"] == 2, str(st))
ok("הקשת אישור (7) נספרת ומסומנת", st["confirmed"] == 1
   and st["entries"][0]["confirmed"] and not st["entries"][1]["confirmed"])
canned["GetCampaignStatus"]["campaign"].update(
    {"campaignStatus": "DONE", "pendingEntries": 0, "activeEntries": 0,
     "entries": [
         {"phone": "0521111111", "entryStatus": "accepted"},
         {"phone": "0522222222", "entryStatus": "no_answer"},
         {"phone": "0523333333", "entryStatus": "amd"},
         {"phone": "0524444444", "entryStatus": "busy"},
     ]})
st = yemot.get_campaign_status("x")
ok("סטטוס סיים", st["finished"])
ok("משיבון נספר כנמסר", st["delivered"] == 2 and st["failed"] == 2, str(st))
ok("משיבון אינו אישור הגעה", st["confirmed"] == 1, str(st))

try:
    yemot.run_test("שטויות")
    ok("בדיקה עם מספר שבור נחסמת", False)
except yemot.YemotError:
    ok("בדיקה עם מספר שבור נחסמת", True)

# ── 4. היסטוריה ב-DB + שומר שליחה-כפולה ─────────────────────────────────────
print("— היסטוריה ושומר כפילות —")
g1 = db.add_tzintuk_campaign("חלוקה שבועית 02/09/2026", "2026-09-02",
                             "1117319", "camp-1", 48, device="מחשב א")
ok("קמפיין נרשם", any(c["guid"] == g1 for c in db.get_tzintuk_campaigns()))
ok("רישום חוזר באותו guid לא מכפיל",
   db.add_tzintuk_campaign("כפול", "2026-09-02", "t", "c", 1, guid=g1) == g1
   and len([c for c in db.get_tzintuk_campaigns() if c["guid"] == g1]) == 1)
db.update_tzintuk_campaign(g1, 45, 3, "done", json.dumps({"x": 1}))
row = db.tzintuk_campaign_for_date("2026-09-02")
ok("שומר כפילות מוצא לפי תאריך", row is not None and row["delivered"] == 45
   and row["status"] == "done")
ok("תאריך בלי קמפיין — אין שומר", db.tzintuk_campaign_for_date("2026-09-09") is None)
ok("עדכון guid לא קיים נכשל בשקט", not db.update_tzintuk_campaign("אין", 0, 0, "done"))

# אישורי הגעה מהדוח השמור (confirmed_phones — מזין את התגים במסך החלוקה)
report = json.dumps([
    {"phone": "0521111111", "name": "א", "status": "accepted", "confirmed": True},
    {"phone": "0522222222", "name": "ב", "status": "no_answer"},
    {"phone": "052-111-1111", "name": "כפול-פורמט", "status": "accepted"},
], ensure_ascii=False)
db.update_tzintuk_campaign(g1, 45, 3, "done", report)
ok("confirmed_phones מחלץ את המאשרים (מנורמל)",
   yemot.confirmed_phones("2026-09-02") == {"0521111111"})
ok("confirmed_phones לתאריך בלי קמפיין ריק",
   yemot.confirmed_phones("2026-09-09") == set())
ok("confirmed_phones עמיד ל-json שבור",
   db.update_tzintuk_campaign(g1, 45, 3, "done", "{שבור")
   and yemot.confirmed_phones("2026-09-02") == set()
   and db.update_tzintuk_campaign(g1, 45, 3, "done", report))

# ── 5. סנכרון בין 2 מחשבים ──────────────────────────────────────────────────
print("— סנכרון 2 מחשבים —")
n_seed = sync.enable_sync(shared, seed=True)
ok("A זרע snapshot כולל צינתוקים", n_seed >= 2, f"records={n_seed}")

use_machine(dir_b)
db.init_db()
sync.enable_sync(shared, seed=True)
res = sync.run_sync()
ok("B קלט רשומות", res["applied"] >= 2, str(res))
camps_b = db.get_tzintuk_campaigns()
ok("B רואה את הקמפיין של A", len(camps_b) == 1 and camps_b[0]["guid"] == g1,
   f"count={len(camps_b)}")
ok("B קיבל גם את התוצאות (tz_update)",
   camps_b and camps_b[0]["delivered"] == 45 and camps_b[0]["status"] == "done")
guard_b = db.tzintuk_campaign_for_date("2026-09-02")
ok("שומר הכפילות פועל גם במחשב B", guard_b is not None)

# B שולח קמפיין משלו → A רואה אותו
g2 = db.add_tzintuk_campaign("חלוקה שבועית 09/09/2026", "2026-09-09",
                             "1117319", "camp-2", 30, device="מחשב ב")
db.update_tzintuk_campaign(g2, 30, 0, "done")
use_machine(dir_a)
res = sync.run_sync()
camps_a = db.get_tzintuk_campaigns()
ok("A רואה את הקמפיין של B", any(c["guid"] == g2 and c["delivered"] == 30
                                  for c in camps_a), f"count={len(camps_a)}")

# LWW: עדכון ישן לא דורס חדש
with db.get_connection() as conn:
    sync._apply_tz_update(conn, {"guid": g2, "delivered": 1, "failed": 99,
                                 "status": "sending", "ts": "2000-01-01T00:00:00"})
row2 = [c for c in db.get_tzintuk_campaigns() if c["guid"] == g2][0]
ok("LWW: עדכון ישן נדחה", row2["delivered"] == 30 and row2["status"] == "done")

print()
if fails:
    print(f"✗ {len(fails)} בדיקות נכשלו: {fails}")
    sys.exit(1)
print("✓ כל בדיקות הצינתוקים עברו")
sys.exit(0)

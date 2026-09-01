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

# ── 2. שעות שליחה — אין חסימה (#n6wte, הכרעת המשתמש 31/08/2026) ─────────────
print("— שעות שליחה —")
ok("כל השעות פתוחות — יום חול",
   yemot.send_block_reason(datetime(2026, 9, 2, 10, 0)) == "")
ok("כל השעות פתוחות — לילה",
   yemot.send_block_reason(datetime(2026, 9, 2, 23, 0)) == "")
ok("כל השעות פתוחות — שבת",
   yemot.send_block_reason(datetime(2026, 9, 5, 11, 0)) == "")
ok("כל השעות פתוחות — בלי ארגומנט", yemot.send_block_reason() == "")

# ── 2ב. חלוקת מספרים — כל המספרים של כל מקבל (#gaira) ───────────────────────
print("— כל המספרים למשפחה —")
alloc = yemot.allocate_phones([["0521", "0522"], ["0523"], ["0522", "0524"], []])
ok("כל המספרים נשמרים לכל שורה", alloc[0] == ["0521", "0522"] and alloc[1] == ["0523"])
ok("מספר כפול בין שורות מצולצל פעם אחת", alloc[2] == ["0524"])
ok("שורה בלי מספרים נשארת ריקה", alloc[3] == [])
ok("שורה שכל מספריה כפולים מתרוקנת",
   yemot.allocate_phones([["0521"], ["0521"]])[1] == [])

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

# ── 3ב. store_list — הרשימה נשמרת בתבנית לפני שליחה (#z4xy9) ────────────────
print("— שמירת הרשימה בתבנית + פרסום בשלוחה —")
canned["RunCampaign"] = {"responseStatus": "OK", "campaignId": "c-x",
                         "entriesCount": 1}
canned["ClearTemplateEntries"] = {"responseStatus": "OK"}
canned["UploadPhoneList"] = {"responseStatus": "OK"}
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
seq = [c[0] for c in calls[n0:]]
ok("store_list: ניקוי+העלאת רשימה לפני RunCampaign",
   seq[:2] == ["ClearTemplateEntries", "UploadPhoneList"]
   and seq[-1] == "RunCampaign", str(seq))
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"})
ok("בלי store_list — אין נגיעה ברשימה",
   [c[0] for c in calls[n0:]] == ["RunCampaign"])

# publish_to_extension (#kx6wd): הורדת ההקלטה מהתבנית → מספר פנוי → העלאה
WAV = b"RIFF\xff\x00fake-wav"
def media_transport(url, data):
    if "DownloadFile" in url:
        calls.append(("DownloadFile",
                      {k: v[0] for k, v in urllib.parse.parse_qs(
                          urllib.parse.urlparse(url).query).items()}))
        return WAV
    return fake_transport(url, data)
yemot._TRANSPORT = media_transport
canned["GetIVR2Dir"] = {"responseStatus": "OK", "files": [
    {"name": "007.wav"}, {"name": "003.ogg"}, {"name": "בלי-מספר.wav"}]}
canned["UploadFile"] = {"responseStatus": "OK", "path": "x"}
name = yemot.publish_to_extension()
ok("publish: מוריד את הקלטת התבנית", any(
    c[0] == "DownloadFile" and c[1].get("path", "").startswith("tpl:")
    for c in calls))
ok("publish: הקובץ מקבל את המספר הפנוי הבא", name == "008.wav")
up_call = calls[-1]
ok("publish: הועלה לשלוחה 1 בלי המרה", up_call[0] == "UploadFile"
   and b"ivr2:/1/008.wav" in (up_call[1].get("_raw") or b""))

# שלוחה ריקה → הקובץ הראשון 001; תבנית בלי הקלטה → שגיאה ברורה
canned["GetIVR2Dir"] = {"responseStatus": "OK", "files": []}
ok("publish לשלוחה ריקה — 001", yemot.publish_to_extension() == "001.wav")
def no_media_transport(url, data):
    if "DownloadFile" in url:
        return json.dumps({"responseStatus": "ERROR"}).encode()
    return fake_transport(url, data)
yemot._TRANSPORT = no_media_transport
try:
    yemot.publish_to_extension()
    ok("publish בלי הקלטה — שגיאה ברורה", False)
except yemot.YemotError as e:
    ok("publish בלי הקלטה — שגיאה ברורה", "הקלטה" in str(e))
yemot._TRANSPORT = fake_transport

# ── 3ג. צינתוק קלאסי + שמירת מספר-הבדיקה (דוח 1/9) ──────────────────────────
print("— צינתוק קלאסי ובדיקה —")
canned["GetTemplates"] = {"responseStatus": "OK", "templates": [
    {"templateId": 1117319, "description": yemot.TEMPLATE_DESCRIPTION},
    {"templateId": 1117320, "description": yemot.TEMPLATE_DESCRIPTION}]}
canned["UpdateTemplate"] = {"responseStatus": "OK"}
cid = yemot.ensure_classic_template()
ok("תבנית קלאסית מאמצת את התבנית היתומה", cid == "1117320"
   and db.get_setting(yemot.SET_CLASSIC_TEMPLATE) == "1117320")
cfg = [c for c in calls if c[0] == "UpdateTemplate"
       and c[1].get("templateId") == "1117320"][-1]
ok("התבנית הקלאסית הוגדרה לצלצול קצר",
   cfg[1].get("originateTimeout") == str(yemot.CLASSIC_RING_SECONDS)
   and cfg[1].get("maxDialAttempts") == "1")
n0 = len(calls)
ok("ensure_classic_template לא פונה שוב לשרת",
   yemot.ensure_classic_template() == "1117320" and len(calls) == n0)

# קלאסי דרך RunTzintuk — צינתוק אמיתי שאי אפשר לענות לו
canned["RunTzintuk"] = {"responseStatus": "OK"}
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"}, classic=True)
seq = [c[0] for c in calls[n0:]]
ok("קלאסי: יוצא דרך RunTzintuk ולא RunCampaign",
   seq[-1] == "RunTzintuk" and "RunCampaign" not in seq, str(seq))
tz = calls[-1]
ok("קלאסי: מספרים + זמן צלצול, בלי sayInfoOnAnswer (שלא יהיה מענה)",
   tz[1].get("phones") == "0521234567"
   and tz[1].get("TzintukTimeOut") == str(yemot.TZINTUK_RING_SECONDS)
   and "sayInfoOnAnswer" not in tz[1])
stored = [c for c in calls[n0:] if c[0] == "UploadPhoneList"][-1]
ok("קלאסי: הרשימה נשמרה בתבנית הראשית (להתקשרות חוזרת)",
   stored[1].get("templateId") == "1117319")

# הקו בלי שירות צינתוקים → נפילה חזרה לצלצול-קצר מהתבנית הקלאסית
canned["RunTzintuk"] = {"responseStatus": "ERROR", "messageCode": 3,
                        "message": "no tzintuk service"}
yemot._TRANSPORT = media_transport      # DownloadFile מחזיר WAV
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"}, classic=True)
seq = [c[0] for c in calls[n0:]]
ok("נפילה: ההקלטה מועתקת לתבנית הקלאסית",
   "DownloadFile" in seq and "UploadFile" in seq, str(seq))
run = [c for c in calls[n0:] if c[0] == "RunCampaign"][-1]
ok("נפילה: החיוג יוצא מהתבנית הקלאסית",
   run[1].get("templateId") == "1117320")
canned["RunTzintuk"] = {"responseStatus": "OK"}
yemot._TRANSPORT = fake_transport

n0 = len(calls)
yemot.run_test("0501234567")
seq = [c[0] for c in calls[n0:]]
ok("בדיקה: המספר נוסף לרשימה בלי ניקוי (התקשרות חוזרת עובדת)",
   seq == ["UploadPhoneList", "RunCampaign"], str(seq))
upl = [c for c in calls[n0:] if c[0] == "UploadPhoneList"][0]
ok("בדיקה: עדכון בלי מחיקת הרשימה (UPDATE)",
   upl[1].get("updateType") == "UPDATE")

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

# ── 6. תזמון צינתוקים (#xi85i) — ScheduleCampaign בצד השרת ──────────────────
print("— תזמון צינתוקים —")
canned["ScheduleCampaign"] = {"responseStatus": "OK", "schedId": 777}
canned["ClearTemplateEntries"] = {"responseStatus": "OK"}
canned["UploadPhoneList"] = {"responseStatus": "OK"}
n_sched = len(calls)
res = yemot.schedule_campaign(datetime(2026, 9, 16, 9, 0),
                              {"0521234567": "כהן יוסף", "05-12": "שבור"})
ok("schedule_campaign מחזיר schedId", res["schedId"] == "777")
sched_calls = [c for c in calls[n_sched:] if c[0] in
               ("ClearTemplateEntries", "UploadPhoneList", "ScheduleCampaign")]
ok("הרשימה נוקתה לפני העלאה", sched_calls[0][0] == "ClearTemplateEntries"
   and sched_calls[0][1].get("templateId") == "1117319")
up = sched_calls[1]
ok("UploadPhoneList עם המספרים התקינים בלבד",
   up[0] == "UploadPhoneList" and "0521234567\tכהן יוסף" in up[1].get("data", "")
   and "05-12" not in up[1].get("data", ""))
ok("UploadPhoneList בפורמט TAB/NEW", up[1].get("delimiter") == "TAB"
   and up[1].get("updateType") == "NEW")
sc = sched_calls[2]
ok("ScheduleCampaign עם זמן בפורמט הנכון",
   sc[0] == "ScheduleCampaign" and sc[1].get("time") == "2026-09-16 09:00"
   and sc[1].get("templateId") == "1117319")
try:
    yemot.schedule_campaign(datetime(2026, 9, 16, 9, 0), {"05-12": "שבור"})
    ok("תזמון בלי מספרים נחסם", False)
except yemot.YemotError:
    ok("תזמון בלי מספרים נחסם", True)

# schedId לא הוחזר → איתור ברשימת הממתינים
canned["ScheduleCampaign"] = {"responseStatus": "OK"}
canned["GetScheduledCampaigns"] = {"responseStatus": "OK", "scheduled": [
    {"schedId": 555, "templateId": 1117319, "time": "2026-09-16 09:00"}]}
res = yemot.schedule_campaign(datetime(2026, 9, 16, 9, 0), {"0521234567": "כהן"})
ok("schedId מאותר ברשימה כשלא הוחזר", res["schedId"] == "555")

# find_scheduled לפי סוג הרשימה שהשרת מחזיר
def typed_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if command == "GetScheduledCampaigns":
        items = ([{"schedId": 777, "templateId": 1117319,
                   "campaignId": "camp-777"}]
                 if params.get("type") == "SUCCESSFUL" else [])
        return json.dumps({"responseStatus": "OK",
                           "scheduled": items}).encode("utf-8")
    return fake_transport(url, data)
yemot._TRANSPORT = typed_transport
state, rec777 = yemot.find_scheduled(777)
ok("find_scheduled מזהה שהתזמון רץ (SUCCESSFUL)",
   state == "successful" and rec777.get("campaignId") == "camp-777")
ok("find_scheduled לתזמון שאינו קיים", yemot.find_scheduled(999)[0] == "missing")
yemot._TRANSPORT = fake_transport

# ביטול תזמון + שגיאות בעברית
canned["DeleteScheduledCampaign"] = {"responseStatus": "OK"}
yemot.delete_scheduled_campaign(777)
ok("DeleteScheduledCampaign נשלח", calls[-1][0] == "DeleteScheduledCampaign"
   and calls[-1][1].get("schedId") == "777")
canned["DeleteScheduledCampaign"] = {"responseStatus": "ERROR",
                                     "messageCode": 106,
                                     "message": "schedId is not pending"}
try:
    yemot.delete_scheduled_campaign(777)
    ok("ביטול תזמון שכבר רץ → הודעה ברורה", False)
except yemot.YemotError as e:
    ok("ביטול תזמון שכבר רץ → הודעה ברורה", "כבר בוצע" in str(e) and e.code == 106)
canned["DeleteScheduledCampaign"] = {"responseStatus": "ERROR",
                                     "messageCode": 105,
                                     "message": "invalid schedId"}
try:
    yemot.delete_scheduled_campaign(777)
    ok("ביטול תזמון לא קיים → הודעה ברורה", False)
except yemot.YemotError as e:
    ok("ביטול תזמון לא קיים → הודעה ברורה", "לא נמצא" in str(e) and e.code == 105)

# DB: רשומת תזמון, ואז ריצה → campaignId אמיתי + זמן ריצה
g3 = db.add_tzintuk_campaign("צינתוק מתוזמן", "2026-09-16", "1117319",
                             "777", 12, sent_at="2026-09-16T06:00:00+00:00",
                             device="מחשב א", status="scheduled")
row3 = [c for c in db.get_tzintuk_campaigns() if c["guid"] == g3][0]
ok("רשומת תזמון נשמרת בסטטוס scheduled", row3["status"] == "scheduled"
   and row3["campaign_id"] == "777")
ok("שומר הכפילות רואה גם תזמון",
   (db.tzintuk_campaign_for_date("2026-09-16") or {}).get("guid") == g3)
db.update_tzintuk_campaign(g3, 0, 0, "sending", campaign_id="camp-777",
                           sent_at="2026-09-16T06:01:00+00:00")
row3 = [c for c in db.get_tzintuk_campaigns() if c["guid"] == g3][0]
ok("כשהתזמון רץ — campaignId אמיתי נשמר", row3["campaign_id"] == "camp-777"
   and row3["status"] == "sending")
db.update_tzintuk_campaign(g3, 0, 0, "canceled")
ok("תזמון מבוטל לא נחשב בשומר הכפילות",
   db.tzintuk_campaign_for_date("2026-09-16") is None)
ok("update בלי campaign_id לא דורס אותו",
   [c for c in db.get_tzintuk_campaigns() if c["guid"] == g3][0]["campaign_id"]
   == "camp-777")

# סנכרון: תזמון עובר בין המחשבים עם הסטטוס והחלפת ה-campaignId
with db.get_connection() as conn:
    sync._apply_tz_add(conn, {"guid": "sched-guid-b", "name": "מתוזמן מ-B",
                              "sent_at": "2026-09-23T06:00:00+00:00",
                              "dist_date": "2026-09-23", "template_id": "1117319",
                              "campaign_id": "888", "device": "מחשב ב",
                              "total": 5, "status": "scheduled"})
    sync._apply_tz_update(conn, {"guid": "sched-guid-b", "delivered": 0,
                                 "failed": 0, "status": "sending",
                                 "ts": "2026-09-23T06:02:00+00:00",
                                 "campaign_id": "camp-888",
                                 "sent_at": "2026-09-23T06:01:30+00:00"})
rowb = [c for c in db.get_tzintuk_campaigns() if c["guid"] == "sched-guid-b"][0]
ok("tz_add עם סטטוס scheduled מסונכרן", True)
ok("tz_update מעדכן campaign_id וזמן ריצה", rowb["campaign_id"] == "camp-888"
   and rowb["status"] == "sending"
   and rowb["sent_at"] == "2026-09-23T06:01:30+00:00")
with db.get_connection() as conn:
    sync._apply_tz_add(conn, {"guid": "old-ver-guid", "name": "ממחשב ישן",
                              "sent_at": "2026-09-23T07:00:00+00:00",
                              "dist_date": "2026-09-24", "template_id": "t",
                              "campaign_id": "c-old", "device": "", "total": 3})
rowo = [c for c in db.get_tzintuk_campaigns() if c["guid"] == "old-ver-guid"][0]
ok("payload ישן בלי status → ברירת מחדל sending", rowo["status"] == "sending")

# ── 7. סטטיסטיקת שעות מענה (#y7jr0 שלב 1) ───────────────────────────────────
print("— שעות מענה —")
P_HOT, P_NEW = "0529999999", "0528888888"


def _hist_campaign(i, hour, status_hot):
    g = db.add_tzintuk_campaign(f"היסטוריה {i}", f"2026-07-{i + 1:02d}",
                                "t", f"h-{i}", 2,
                                sent_at=f"2026-07-{i + 1:02d}T{hour:02d}:00:00+03:00")
    report = [{"phone": P_HOT, "status": status_hot,
               "ok": status_hot == "done", "failed": status_hot != "done"}]
    if i < 3:                       # למספר החדש יש רק 3 ניסיונות
        report.append({"phone": P_NEW, "status": "done", "ok": True})
    db.update_tzintuk_campaign(g, 1, 1, "done",
                               json.dumps(report, ensure_ascii=False))


# 8 שליחות ב-18:00 (6 ענו) + 4 שליחות ב-10:00 (ענה אחת) = 12 ניסיונות
for i in range(8):
    _hist_campaign(i, 18, "done" if i < 6 else "no_answer")
for i in range(8, 12):
    _hist_campaign(i, 10, "done" if i == 8 else "busy")
stats = yemot.answer_stats()
hot = stats.get(P_HOT) or {}
ok("נספרו כל הניסיונות", hot.get("attempts") == 12 and hot.get("answered") == 7,
   str(hot))
ok("השעה המומלצת = השעה עם אחוז המענה הגבוה", hot.get("best_hour") == 18)
new = stats.get(P_NEW) or {}
ok(f"מתחת ל-{yemot.MIN_SMART_HISTORY} שליחות אין המלצה",
   new.get("attempts") == 3 and new.get("best_hour") is None)
ok("מי שלא הופיע בדוחות — אין רשומה", "0520000000" not in stats)

# ── 8. מעקב חזרה-לשיחה אחרי צינתוק קלאסי (v2.96) ────────────────────────────
print("— מעקב צינתוק קלאסי —")


def calls_transport(url, data):
    if "GetIncomingCalls" in url:
        return json.dumps({"responseStatus": "OK", "did": "0795378810",
                           "calls": [
                               {"callerIdNum": "052-1111222", "did": "048691834",
                                "duration": 4.2, "path": "/"},
                               {"callerIdNum": "0500000000", "did": "0795378810",
                                "duration": 9.0, "path": "/2"},
                           ], "callsCount": 2}).encode("utf-8")
    return fake_transport(url, data)


yemot._TRANSPORT = calls_transport
live = yemot.get_incoming_calls()
ok("GetIncomingCalls מפורק ומנורמל",
   live and live[0]["phone"] == "0521111222" and live[0]["path"] == "/"
   and live[0]["duration"] == 4.2, str(live))
yemot._TRANSPORT = fake_transport

tr = yemot.CallbackTracker({"0521111222": "משפחת בדיקה", "0533334444": "שנייה"})
ok("לפני עדכון — אף אחד לא חזר", tr.counts() == (0, 0))
ch1 = tr.update([{"phone": "0521111222", "duration": 3.0, "path": "/"}],
                "2026-09-01T10:00:00+00:00")
ok("מתקשר-חוזר חדש = שינוי", ch1 and tr.counts() == (1, 0))
ch2 = tr.update([{"phone": "0521111222", "duration": 11.0, "path": "/"}])
ok("רק גדילת משך שיחה ≠ שינוי מהותי", not ch2
   and tr.state["0521111222"]["duration"] == 11.0)
ch3 = tr.update([{"phone": "0521111222", "duration": 14.0, "path": "/7"}])
ok("מעבר לשלוחה 7 = אישור הגעה", ch3 and tr.counts() == (1, 1))
tr.update([{"phone": "0509999999", "duration": 5.0, "path": "/"}])
ok("מספר שאינו ברשימה לא נספר", tr.counts() == (1, 1))
ents = {e["phone"]: e for e in tr.entries()}
ok("סטטוסים בדוח: accepted / no_callback",
   ents["0521111222"]["status"] == "accepted"
   and ents["0521111222"]["confirmed"] and ents["0521111222"]["ok"]
   and ents["0533334444"]["status"] == "no_callback"
   and not ents["0533334444"]["failed"], str(ents))

tr2 = yemot.CallbackTracker({"0521111222": "א", "0533334444": "ב"})
tr2.seed(tr.entries())
ok("seed משחזר מצב אחרי סגירת התוכנה", tr2.counts() == (1, 1))
tr2.update([{"phone": "0533334444", "duration": 2.0, "path": "/"}])
ok("אחרי seed ממשיכים לצבור", tr2.counts() == (2, 1)
   and {e["phone"]: e["status"] for e in tr2.entries()}["0533334444"] == "callback")
ok("נתיב 7/תת-שלוחה נחשב אישור; 70 לא",
   yemot.CallbackTracker._is_confirm_path("/7/1")
   and not yemot.CallbackTracker._is_confirm_path("/70"))

print()
if fails:
    print(f"✗ {len(fails)} בדיקות נכשלו: {fails}")
    sys.exit(1)
print("✓ כל בדיקות הצינתוקים עברו")
sys.exit(0)

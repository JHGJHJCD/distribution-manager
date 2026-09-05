# -*- coding: utf-8 -*-
"""בדיקות מערכת הצינתוקים (utils/yemot.py + DB + sync, v2.81) — בלי רשת:
התחבורה מוזרקת (yemot._TRANSPORT) ומחזירה תשובות-שרת מוקלטות.

מכסה: נרמול טלפונים, בחירת מספרים למקבל, חוקי שעות-שליחה, בניית בקשות
(תבנית/קמפיין/סטטוס), מיפוי שגיאות לעברית, פירוק סטטוס קמפיין, רישום
היסטוריה ב-DB (idempotence + LWW), שומר שליחה-כפולה, וסנכרון בין 2 מחשבים.
"""
import os, sys, json, tempfile, urllib.parse
from datetime import date, datetime
import os
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
ok("v3.02: אין יותר ניסיון REPEAT (השרת דוחה; האישור עבר לסקר בשלוחה 77)",
   len(upd) == 0)
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

# ── 3ב. store_list — הרשימה נשמרת בתבנית + מסלול ההתקשרות-החוזרת (v3.06) ────
print("— שמירת הרשימה בתבנית + שלוחת ההתקשרות החוזרת —")
canned["RunCampaign"] = {"responseStatus": "OK", "campaignId": "c-x",
                         "entriesCount": 1}
canned["ClearTemplateEntries"] = {"responseStatus": "OK"}
canned["UploadPhoneList"] = {"responseStatus": "OK"}
# מי שברשימת התבנית ומחייג לקו מופנה מהשורש לשלוחה 78 (check_template_filter);
# מספר הרשימה = המיקום ברשימת התבניות (1-based).
_main_tid = yemot.ensure_template()
canned["GetTemplates"] = {"responseStatus": "OK", "templates": [
    {"templateId": 900001, "description": "קופה"},
    {"templateId": 900002, "description": "נעליים"},
    {"templateId": int(_main_tid), "description": yemot.TEMPLATE_DESCRIPTION}]}
import io, re, wave
def make_wav(frames, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x01\x00" * frames)
    return buf.getvalue()
MSG_WAV, WELCOME_WAV = make_wav(800), make_wav(1600)
ROOT_INI = ("type=menu\n; הערה של המנהל\nplay_campaign_message=yes\n"
            "campaign_message_to_play=0-ACTIVE,3-ACTIVE-1-1h,\n"
            "campaign_message_to_play_file_by_template=yes\ngo_to_folder=/2\n"
            "check_did_and_go_to_folder=yes\n")
line_files = {"ivr2:/ext.ini": ROOT_INI, "ivr2:/M0000.wav": WELCOME_WAV,
              f"tpl:{_main_tid}": MSG_WAV}
ext78 = {"exists": True, "dirs": [{"name": "1", "exists": True}], "files": []}
listings = {"ivr2:/78": ext78}          # /78/menu נוצרת רק ע"י UploadFile
uploads = []            # (path, bytes) של UploadFile


def line_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if command == "DownloadFile":
        calls.append(("DownloadFile", {"path": params.get("path")}))
        v = line_files.get(params.get("path"))
        if v is None:
            return json.dumps({"responseStatus": "ERROR"}).encode()
        return v.encode("utf-8") if isinstance(v, str) else v
    if command == "GetIVR2Dir":
        calls.append(("GetIVR2Dir", params))
        if params.get("path") == "ivr2:/":
            return json.dumps({"responseStatus": "OK", "dirs": [
                {"name": n, "exists": True} for n in ("0", "1", "2", "77", "Log", "78")],
                "files": []}).encode()
        lst = listings.get(params.get("path"))
        if lst and lst.get("exists", True):
            return json.dumps({"responseStatus": "OK", "dirs": lst["dirs"],
                               "files": lst["files"]}).encode()
        return json.dumps({"responseStatus": "ERROR", "messageCode": 0,
                           "message": "extension does not exist"}).encode()
    if command == "UploadTextFile" and data:
        p = {k: v[0] for k, v in urllib.parse.parse_qs(data.decode("utf-8")).items()}
        line_files[p["what"]] = p["contents"]
    if command == "UploadFile" and data:
        m = re.search(rb'name="path"\r\n\r\n(.+?)\r\n', data)
        path = m.group(1).decode() if m else ""
        body = data.split(b"\r\n\r\n", 5)[-1].rsplit(b"\r\n--", 1)[0]
        uploads.append((path, body))
        mm = re.fullmatch(r"(ivr2:/78(?:/menu)?)/(\w+)/ext\.ini", path)
        if path == "ivr2:/78/ext.ini":
            line_files[path] = body.decode("utf-8", "replace")
        elif path == "ivr2:/78/menu/ext.ini":
            listings.setdefault("ivr2:/78/menu", {"dirs": [], "files": []})
            line_files[path] = body.decode("utf-8", "replace")
        elif mm:
            listings[mm.group(1)]["dirs"].append({"name": mm.group(2), "exists": True})
            line_files[path] = body.decode("utf-8", "replace")
        elif path.endswith("/M0000.wav"):
            listings[path.rsplit("/", 1)[0]]["files"].append({"name": "M0000.wav"})
    return fake_transport(url, data)


yemot._TRANSPORT = line_transport
db.set_setting(yemot.SET_CALLBACK_READY, "")
# נעילה (תקרית 3/9/2026 14:38): כברירת מחדל המנגנון כבוי — שליחה לא נוגעת בשורש
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
seq = [c[0] for c in calls[n0:]]
ok("נעילה: כשהמנגנון כבוי השליחה לא קוראת ולא כותבת דבר בשורש הקו",
   not yemot.CALLBACK_ENABLED and "DownloadFile" not in seq and "FileAction" not in seq
   and "UploadFile" not in seq and line_files["ivr2:/ext.ini"] == ROOT_INI, str(seq))
yemot.CALLBACK_ENABLED = True
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
seq = [c[0] for c in calls[n0:]]
ok("store_list: ניקוי+העלאת רשימה לפני RunCampaign",
   seq[:2] == ["ClearTemplateEntries", "UploadPhoneList"]
   and seq[-1] == "RunCampaign", str(seq))
root_now = yemot._ini_items(line_files["ivr2:/ext.ini"])
ok("השורש: פילטר רשימת-תפוצה (מיקום 3) → שלוחה 78, כל השאר נכנסים כרגיל",
   root_now.get("check_template_filter") == "3"
   and root_now.get("check_template_filter_active_go_to") == "/78"
   and all(root_now.get(k) == "yes" for k in (
       "check_template_filter_none_enter", "check_template_filter_blocked_enter",
       "check_template_filter_error_enter")), str(root_now))
ok("השורש: הרשומה הישנה של התוכנה הוסרה מהשורה של המנהל, הרשומה שלו נשארה",
   root_now.get("campaign_message_to_play") == "0-ACTIVE,"
   and "campaign_message_to_play_file_by_template" not in root_now)
ok("השורש: שאר השורות (הערות, ניתוב DID, go_to_folder) לא נגעו",
   "; הערה של המנהל" in line_files["ivr2:/ext.ini"]
   and root_now.get("check_did_and_go_to_folder") == "yes"
   and root_now.get("go_to_folder") == "/2"
   and line_files["ivr2:/ext.ini"].startswith("type=menu\n; הערה"))
linked = sorted(p.split("/")[2] for p, _ in uploads
                if re.fullmatch(r"ivr2:/78/\d+/ext\.ini", p))
ok("שלוחה 78: קישור לכל שלוחת-ספרות בשורש שחסרה (לא 1 שכבר קיימת, לא Log, לא 78 עצמה)",
   linked == ["0", "2", "77"], str(linked))
ok("הקישור מפנה לשלוחה המקבילה בשורש",
   "go_to_folder=/77" in line_files.get("ivr2:/78/77/ext.ini", ""))
sub_linked = sorted(p.split("/")[3] for p, _ in uploads
                    if re.fullmatch(r"ivr2:/78/menu/\w+/ext\.ini", p))
ok("78/menu (מי שכבר שמע): נוצרה עם כל קישורי המקשים ובלי אקסס-פילטר",
   sub_linked == ["0", "1", "2", "77"]
   and "check_access_filter" not in line_files.get("ivr2:/78/menu/ext.ini", ""),
   str(sub_linked))
ok("78: אקסס-פילטר — פעם אחת ל-30 יום, מי שכבר שמע → 78/menu",
   "access_filter_1=g.*.*.*.*.*.30d.1.30d" in line_files.get("ivr2:/78/ext.ini", "")
   and "access_filter_no_goto=/78/menu" in line_files.get("ivr2:/78/ext.ini", ""))
msg_up = [b for p, b in uploads if p == "ivr2:/78/M0000.wav"]
sub_up = [b for p, b in uploads if p == "ivr2:/78/menu/M0000.wav"]
ok("שלוחה 78: קובץ הפתיחה = ההודעה + פתיח התפריט הראשי; 78/menu = הפתיח בלבד",
   len(msg_up) == 1 and len(msg_up[0]) > len(MSG_WAV) + len(WELCOME_WAV) - 100
   and sub_up == [WELCOME_WAV])
fa = [c for c in calls[n0:] if c[0] == "FileAction"]
ok("בכל שליחה: זיכרון 'כבר שמע' של 78 נמחק לפני החיוג",
   len(fa) == 1 and fa[0][1].get("what") == "ivr2:/78/AccessFilterLogTime.ini"
   and fa[0][1].get("action") == "delete"
   and seq.index("FileAction") < seq.index("RunCampaign"), str(fa))
ok("template_position: לא ברשימה = 0", yemot.template_position("123") == 0)

# ריצה שנייה באותו יום: רק בדיקת השורש (הורדה אחת), בלי כתיבות
n0 = len(calls); n_up = len(uploads)
yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
seq = [c[0] for c in calls[n0:]]
ok("ריצה חוזרת: השורש רק נבדק והזיכרון מאופס, שום דבר לא נכתב שוב",
   seq.count("DownloadFile") == 1 and "UploadTextFile" not in seq
   and seq.count("FileAction") == 1
   and len(uploads) == n_up and seq[-1] == "RunCampaign", str(seq))
# המנהל שינה את השורש מהממשק ומחק את השורות שלנו → מתוקן בשליחה הבאה
line_files["ivr2:/ext.ini"] = "type=menu\ncampaign_message_to_play=6-ACTIVE,\n"
yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
ok("השורות שלנו חזרו אחרי שהמנהל מחק אותן (השורה שלו נשמרה)",
   "check_template_filter=3" in line_files["ivr2:/ext.ini"]
   and "campaign_message_to_play=6-ACTIVE," in line_files["ivr2:/ext.ini"])
# שלוחה 78 נמחקה מהקו → השליחה עצמה ממשיכה (best-effort)
ext78["exists"] = False
db.set_setting(yemot.SET_CALLBACK_READY, "")
n0 = len(calls)
res_missing = yemot.run_campaign({"0521234567": "כהן"}, store_list=True)
ok("שלוחה 78 חסרה — לא חוסם שליחה",
   [c[0] for c in calls[n0:]][-1] == "RunCampaign" and res_missing.get("campaignId") == "c-x")
try:
    yemot.ensure_callback_extension()
    ok("שלוחה 78 חסרה — הודעה ברורה ב-ensure", False)
except yemot.YemotError as e:
    ok("שלוחה 78 חסרה — הודעה ברורה ב-ensure", "78" in str(e))
ext78["exists"] = True
ok("strip: הרשומה שלנו יוצאת, של המנהר נשארת",
   yemot._strip_campaign_entry("0-ACTIVE,17-ACTIVE-1-1h,", 17) == "0-ACTIVE,"
   and yemot._strip_campaign_entry("17-ACTIVE", 17) == ""
   and yemot._strip_campaign_entry("6-ACTIVE, 17-ACTIVE-1-6d", 17) == "6-ACTIVE"
   and yemot._strip_campaign_entry("6-ACTIVE,7-ACTIVE", 17) == "6-ACTIVE,7-ACTIVE")
ok("concat: פורמט שונה → ההודעה לבד",
   yemot._concat_wavs(MSG_WAV, make_wav(10, rate=16000)) == MSG_WAV
   and yemot._concat_wavs(MSG_WAV, b"not-a-wav") == MSG_WAV)
yemot._TRANSPORT = fake_transport
del canned["GetTemplates"]
n0 = len(calls)
yemot.run_campaign({"0521234567": "כהן"})
ok("בלי store_list — אין נגיעה ברשימה",
   [c[0] for c in calls[n0:]] == ["RunCampaign"])
yemot.CALLBACK_ENABLED = False

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
ok("קלאסי: הרשימה נשמרת לפני הצינתוק, ובלי נגיעה בשורש הקו (המנגנון נעול)",
   seq.index("UploadPhoneList") < seq.index("RunTzintuk")
   and "DownloadFile" not in seq and "FileAction" not in seq, str(seq))
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
ok("בדיקה: המספר נוסף לרשימה בלי ניקוי, בלי נגיעה בשורש (המנגנון נעול)",
   seq[0] == "UploadPhoneList" and "DownloadFile" not in seq and seq[-1] == "RunCampaign",
   str(seq))
upl = [c for c in calls[n0:] if c[0] == "UploadPhoneList"][0]
ok("בדיקה: עדכון בלי מחיקת הרשימה (UPDATE)",
   upl[1].get("updateType") == "UPDATE")
n0 = len(calls)
yemot.run_test("0501234567", store=False)
seq = [c[0] for c in calls[n0:]]
ok("בדיקה בזמן תזמון ממתין (store=False): לא נוגעים ברשימת התבנית",
   "UploadPhoneList" not in seq and seq[-1] == "RunCampaign", str(seq))

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

# v3.14 — רשומת תזמון בלי schedId: הביטול מאתר את המזהה לפי התבנית ברשימת
# הממתינים (ובלי מזהה — לא מסמן "בוטל" בזמן שהשרת עדיין מחייג)
ok("find_pending_sched_id מאתר לפי התבנית",
   yemot.find_pending_sched_id(1117319) == "555")
ok("find_pending_sched_id — תבנית בלי תזמון ממתין", yemot.find_pending_sched_id(42) == "")
ok("find_pending_sched_id — בלי תבנית", yemot.find_pending_sched_id("") == "")

# v3.14 — מיזוג תוצאות של כמה קמפיינים על אותה רשימה (שיגור חכם / שליחה חוזרת)
from tabs.tzintukim import TzintukimTab as _TT
_m = _TT._merge_entries([{"phone": "0521111111", "failed": True},
                         {"phone": "0522222222", "ok": True}],
                        [{"phone": "0521111111", "ok": True}, {"phone": ""}])
_by = {e["phone"]: e for e in _m}
ok("מיזוג תוצאות: החדש גובר לאותו מספר, הישן נשאר לשאר",
   set(_by) == {"0521111111", "0522222222"} and _by["0521111111"].get("ok") is True)

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
ok("שעה אישית באה משיחות נכנסות בלבד — ניסיונות-חיוג לא נותנים המלצה "
   "(מוטים לשעת השליחה שלנו)", hot.get("best_hour") is None, str(hot))
new = stats.get(P_NEW) or {}
ok("מספר בלי שיחות נכנסות — אין שעה אישית", new.get("best_hour") is None)
ok("מי שלא הופיע בדוחות — אין רשומה", "0520000000" not in stats)

# v3.09 — שעה אמיתית לכל מספר + התקשרויות חוזרות לקו
P_CALL = "0527777777"
for i in range(3):
    g = db.add_tzintuk_campaign(f"קלאסי {i}", f"2026-08-{i + 1:02d}", "t",
                                f"cb-{i}", 1,
                                sent_at=f"2026-08-{i + 1:02d}T10:00:00+03:00")
    report = [{"phone": P_CALL, "status": "callback", "ok": True,
               "failed": False, "survey_reached": True,
               # חזר לקו ב-20:xx שעון ישראל (17:xx UTC)
               "returned_at": f"2026-08-{i + 1:02d}T17:05:00+00:00",
               "answer_at": f"2026-08-{i + 1:02d}T17:06:00+00:00", "answer": "1"},
              # לחלוקה נשלח ב-10:00 אבל המספר הזה חויג בפועל ב-12:30
              {"phone": P_NEW, "status": "done", "ok": True,
               "at": f"2026-08-{i + 1:02d}T09:30:00+00:00"}]
    db.update_tzintuk_campaign(g, 1, 0, "done", json.dumps(report, ensure_ascii=False))
stats = yemot.answer_stats()
cb = stats.get(P_CALL) or {}
ok("שורת 'חזר לשיחה' אינה ניסיון-חיוג אלא התקשרות חוזרת",
   cb.get("attempts") == 0 and cb.get("calls") == 3, str(cb))
ok("שעת ההתקשרות החוזרת = שעון ישראל (20:00)",
   cb.get("by_call_hour") == {20: 3} and yemot.usual_call_hour(cb) == 20, str(cb))
ok("3 התקשרויות חוזרות מספיקות להמלצה אישית", cb.get("best_hour") == 20)
new = stats.get(P_NEW) or {}
ok("שעת החיוג האמיתית של המספר גוברת על שעת הקמפיין",
   new.get("by_hour", {}).get(12) == [3, 3], str(new))
# v3.10 — היסטוריה מהשרת של ימות (utils/call_history)
canned["GetIVR2Dir"] = {"responseStatus": "OK", "files": [
    {"name": "LogFolderEnterExit-2026-05.ymgr", "size": 100, "exists": True},
    {"name": "LogFolderEnterExit-2026-06.ymgr", "size": 500, "exists": True},
    {"name": "LogFolderEnterExit-2025-01.ymgr", "size": 7, "exists": True},
    {"name": "STT_LOG-2026-05.ymgr", "size": 3, "exists": True}]}
ok("available_months — רק קובצי היומן, עם גודל",
   call_history.available_months(yemot) == {"2026-05": 100, "2026-06": 500, "2025-01": 7})
_log = (
    "Folder#main%Phone#0534196458%IncomingDID#048691834%EnterDate#01/06/2026%EnterTime#08:10:36%ExitTime#08:10:43%TimeTotal#7%CallId#aaa%PathTitle#\n"
    "Folder#1%Phone#0534196458%IncomingDID#048691834%EnterDate#01/06/2026%EnterTime#08:10:43%ExitTime#08:10:49%TimeTotal#6%CallId#aaa%PathTitle#\n"
    "Folder#main%Phone#972533163581%IncomingDID#048691834%EnterDate#02/06/2026%EnterTime#20:47:16%ExitTime#20:47:19%TimeTotal#3%CallId#bbb%PathTitle#\n"
    "Folder#main%Phone#%EnterDate#02/06/2026%EnterTime#20:47:16%CallId#ccc\n")
rows = call_history.parse_enter_exit(_log)
ok("parse_enter_exit — שיחה אחת לכל CallId, מספר מנורמל, בלי מספר חסוי",
   rows == [["0534196458", "2026-06-01 08:10"], ["0533163581", "2026-06-02 20:47"]], str(rows))

P_OLD = "0536666666"
canned["GetTransactions"] = {"responseStatus": "OK", "transactions": [
    {"transactionTime": "2026-06-10 13:00:30", "campaignId": "old-camp-1"},
    {"transactionTime": "2026-06-10 12:59:00", "campaignId": None},
    {"transactionTime": "2025-01-01 10:00:00", "campaignId": "ancient"},
]}
canned["GetCampaignStatus"] = {"responseStatus": "OK", "campaign": {
    "campaignStatus": "FINISHED", "totalEntries": 2, "pendingEntries": 0, "activeEntries": 0,
    "entries": [
        {"phone": P_OLD, "entryStatus": "done", "duration": 15000, "startTime": "2026-06-10 13:03:00",
         "redials": [{"entryStatus": "busy", "startTime": "2026-06-10 13:00:30"}]},
        {"phone": P_NEW, "entryStatus": "no_answer", "startTime": "2026-06-10 13:00:31"},
    ]}}
_dl_old = canned.get("DownloadFile")


def _hist_transport(url, data):
    if "DownloadFile" in url and "LogFolderEnterExit-2026-06" in urllib.parse.unquote(url):
        return _log.encode("utf-8")
    if "DownloadFile" in url:
        return b'{"responseStatus":"ERROR"}'
    return fake_transport(url, data)


yemot._TRANSPORT = _hist_transport
calls.clear()
res = call_history.sync_from_server(months=2)
ok("sync — כל הקמפיינים מאז ומעולם נמשכים (גם ישנים)",
   res["new_campaigns"] == 2 and "old-camp-1" in call_history.load()["campaigns"]
   and "ancient" in call_history.load()["campaigns"], str(res))
ok("sync — חודשי היומן נקראו ונצברו לפי מספר→שעה (החודש הריק נשמר)",
   res["months_fetched"] == 2 and res["calls"] == 2
   and call_history.load()["months"]["2026-06"]["hours"] == {"0534196458": {"08": 1}, "0533163581": {"20": 1}},
   str(res))
n_status = sum(1 for c, _ in calls if c == "GetCampaignStatus")
res2 = call_history.sync_from_server(months=2)
ok("sync חוזר — קמפיין שכבר במטמון לא נמשך שוב, חודש שגודלו לא השתנה לא נקרא שוב",
   sum(1 for c, _ in calls if c == "GetCampaignStatus") == n_status
   and res2["months_fetched"] == 0 and res2["new_campaigns"] == 0, str(res2))
canned["GetIVR2Dir"]["files"][1]["size"] = 600
res3 = call_history.sync_from_server(months=2)
ok("קובץ יומן שגדל בשרת נקרא מחדש", res3["months_fetched"] == 1, str(res3))
yemot._TRANSPORT = fake_transport

stats = call_history_stats = yemot.answer_stats()
old_s = stats.get(P_OLD) or {}
ok("2 קמפיינים מהשרת (לפני התוכנה) נספרים: ניסיון + חיוג חוזר בכל אחד = 4 ניסיונות, 2 מענים",
   old_s.get("attempts") == 4 and old_s.get("answered") == 2
   and old_s.get("by_hour", {}).get(13) == [2, 4], str(old_s))
c1 = stats.get("0534196458") or {}
ok("שיחה נכנסת מהיומן = התקשרות בשעה 08",
   c1.get("calls") == 1 and c1.get("by_call_hour") == {8: 1}, str(c1))
# קמפיין שכבר ב-DB לא נספר פעמיים דרך המטמון
g_dup = db.add_tzintuk_campaign("כפול", "2026-06-10", "t", "old-camp-1", 1,
                                sent_at="2026-06-10T10:00:00+00:00")
db.update_tzintuk_campaign(g_dup, 1, 0, "done",
                           json.dumps([{"phone": P_OLD, "status": "done", "ok": True,
                                        "at": "2026-06-10T10:03:00+00:00"}]))
old_s2 = (yemot.answer_stats().get(P_OLD) or {})
ok("campaign_id שכבר ב-DB — המטמון לא סופר אותו שוב (נשאר: הדוח ב-DB + הקמפיין השני)",
   old_s2.get("attempts") == 3 and old_s2.get("answered") == 2, str(old_s2))
# התקשרות חוזרת שנרשמה בתוכנה בחודש שהיומן מכסה — לא נספרת פעמיים
g_cb = db.add_tzintuk_campaign("קלאסי יוני", "2026-06-11", "t", "cb-june", 1,
                               sent_at="2026-06-11T10:00:00+00:00")
db.update_tzintuk_campaign(g_cb, 1, 0, "done",
                           json.dumps([{"phone": "0534196458", "status": "callback", "ok": True,
                                        "returned_at": "2026-06-01T05:10:00+00:00"}]))
c1b = yemot.answer_stats().get("0534196458") or {}
ok("callback של התוכנה בחודש מכוסה ביומן — לא נספר פעמיים",
   c1b.get("calls") == 1, str(c1b))
ok("summary/is_stale", call_history.summary()["campaigns"] == 2
   and call_history.summary()["since"] == "2026-05" and not call_history.is_stale())
if _dl_old is not None:
    canned["DownloadFile"] = _dl_old

ok("_israel_str_to_utc_iso: startTime של השרת → UTC",
   yemot._israel_str_to_utc_iso("2026-09-03 14:50:43").startswith("2026-09-03T11:50:43")
   and yemot._israel_str_to_utc_iso("") == "" and yemot._israel_str_to_utc_iso("xx") == "")

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
ch3 = tr.update([{"phone": "0521111222", "duration": 14.0, "path": "/77"}])
ok("מעבר לשלוחת הסקר 77 = נכנס לסקר", ch3 and tr.counts() == (1, 1))
tr.update([{"phone": "0509999999", "duration": 5.0, "path": "/"}])
ok("מספר שאינו ברשימה לא נספר", tr.counts() == (1, 1))
ents = {e["phone"]: e for e in tr.entries()}
ok("סטטוסים בדוח: callback+survey_reached / no_callback (בלי 'accepted' מזויף)",
   ents["0521111222"]["status"] == "callback"
   and ents["0521111222"]["survey_reached"] and ents["0521111222"]["ok"]
   and not ents["0521111222"]["confirmed"]
   and ents["0533334444"]["status"] == "no_callback"
   and not ents["0533334444"]["failed"], str(ents))

tr2 = yemot.CallbackTracker({"0521111222": "א", "0533334444": "ב"})
tr2.seed(tr.entries())
ok("seed משחזר מצב אחרי סגירת התוכנה", tr2.counts() == (1, 1))
tr2.update([{"phone": "0533334444", "duration": 2.0, "path": "/"}])
ok("אחרי seed ממשיכים לצבור", tr2.counts() == (2, 1)
   and {e["phone"]: e["status"] for e in tr2.entries()}["0533334444"] == "callback")
ok("נתיב 77/תת-שלוחה נחשב כניסה לסקר; 770 ו-7 לא",
   yemot.CallbackTracker._is_confirm_path("/77/1")
   and not yemot.CallbackTracker._is_confirm_path("/770")
   and not yemot.CallbackTracker._is_confirm_path("/7"))

# ── 9. v2.97 — תיקוני סקירה ────────────────────────────────────────────────
print("— v2.97: רשימה עצמאית, תוצאות מנורמלות, ביטול תזמון מסונכרן —")
ok("מספר עם רווחים מזוהה בטקסט חופשי",
   yemot.find_phones("050 123 4567 משפחת כהן")[:2] == (["0501234567"], "משפחת כהן"))
ok("+972 עם רווחים + שני מספרים בשורה",
   yemot.find_phones("+972 52 111 2222, 03-9876543 לוי")[0]
   == ["0521112222", "039876543"])
ok("אקסל: בלי אפס מוביל / עם .0 (loose בלבד)",
   yemot.normalize_phone_loose("501234567") == "0501234567"
   and yemot.normalize_phone_loose("521112222.0") == "0521112222"
   and yemot.normalize_phone("501234567") == "")
ok("קטע מספרי שאינו טלפון מדווח כפסול",
   "12345" in yemot.find_phones("12345 אבג")[2])
ok("שני מספרים צמודים בשורה (רווח בלבד) — שניהם מזוהים",
   yemot.find_phones("0501234567 0521111222 כהן")[:2] == (["0501234567", "0521111222"], "כהן"))
ok("שני מספרים מפוצלים ברווחים בשורה אחת",
   yemot.find_phones("050 123 4567 052 111 2222")[0] == ["0501234567", "0521112222"])
ok("ספרה בודדת בשם אינה 'פסול'",
   yemot.find_phones("0501234567 כהן דירה 5")[:2] == (["0501234567"], "כהן דירה 5")
   and yemot.find_phones("0501234567 כהן דירה 5")[2] == [])
from tabs.tzintukim import _FreeListDialog
ents, bad = _FreeListDialog._parse_text(
    "050 123 4567\tכהן\n501234567;לוי\nabc 99")
ok("_parse_text: רווחים + בלי אפס מוביל + פסול",
   ents == [("0501234567", "כהן"), ("0501234567", "לוי")] and bad == ["99"], str((ents, bad)))

use_machine(dir_a)
canned["GetCampaignStatus"] = {"responseStatus": "OK", "campaign": {
    "campaignStatus": "DONE", "totalEntries": 1, "pendingEntries": 0,
    "activeEntries": 0, "entries": [{"phone": "972521111111", "entryStatus": "accepted"}]}}
st = yemot.get_campaign_status("x")
ok("תוצאות מהשרת בפורמט 972 מנורמלות ל-05",
   st["entries"][0]["phone"] == "0521111111" and st["confirmed"] == 1)

# ביטול תזמון חייב להגיע למחשב השני גם כשהמועד המתוכנן עדיין בעתיד
g_s = db.add_tzintuk_campaign("מתוזמן", "2031-01-01", "1", "S9", 3,
                              sent_at="2031-01-01T09:00:00+00:00", status="scheduled")
row = db.get_tzintuk_campaigns()[0]
ok("status_ts של תזמון = עכשיו, לא המועד המתוכנן", row["status_ts"] < "2031")
sync.run_sync()
db.update_tzintuk_campaign(g_s, 0, 0, "canceled")
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
rb = [c for c in db.get_tzintuk_campaigns() if c["guid"] == g_s]
ok("B רואה את התזמון כמבוטל", rb and rb[0]["status"] == "canceled", str(rb[:1]))
# רשומה ישנה (לפני 2.97) עם חותמת עתידית — עדכון עדיין מתקבל
with db.get_connection() as conn:
    conn.execute("UPDATE tzintuk_campaigns SET status='scheduled', "
                 "status_ts='2031-01-01T09:00:00+00:00' WHERE guid=?", (g_s,))
    sync._apply_tz_update(conn, {"guid": g_s, "delivered": 0, "failed": 0,
                                 "status": "canceled", "ts": db._utc_now(),
                                 "report_json": ""})
ok("רשומה ישנה עם חותמת עתידית מקבלת עדכון",
   [c for c in db.get_tzintuk_campaigns() if c["guid"] == g_s][0]["status"] == "canceled")

# ── 12. סקר אישור הגעה (v3.02) — שלוחה 77: 1 מגיע / 2 לא מגיע / 3 לא יודע ──
print("— סקר אישור הגעה —")
use_machine(dir_a)
yemot._TRANSPORT = fake_transport
_L = ("Status#OK%Folder#77%DID#0795378810%IncomingDID#048691834%Phone#{p}%Date#{d}"
      "%Time#{t}%HebrewDate#י׳ אלול%var#Folder-77%Booking#{b}%Data#%P050#{a}")
ymgr = "\r\n".join([
    _L.format(p="0501234567", d="02/09/2026", t="19:40:12", b=1001, a="2"),
    _L.format(p="972501234567", d="02/09/2026", t="20:05:00", b=1002, a="1"),   # שינה דעתו, פורמט 972
    _L.format(p="0529999999", d="26/08/2026", t="10:00:00", b=1003, a="1"),     # שבוע שעבר
    _L.format(p="0521111222", d="02/09/2026", t="21:00:00", b=1004, a="3"),
    "Status#OK%Folder#77%Phone#0500000000%Date#02/09/2026%Time#21:00:00%Data#",  # בלי תשובה
    "Status#OK%Folder#77%Phone#0500000001%Date#bad%Time#x%P050#1",               # תאריך שבור
    "",
])
rows = yemot.parse_approval_rows(ymgr)
ok("פרסר: 4 שורות תקינות (בלי תשובה/תאריך שבור נזרקות)", len(rows) == 4, str(len(rows)))
ok("פרסר: 972 מנורמל ל-05", rows[1]["phone"] == "0501234567")
ok("פרסר: שעון ישראל → UTC (19:40 IDT = 16:40Z)",
   rows[0]["at"].isoformat() == "2026-09-02T16:40:12+00:00", rows[0]["at"].isoformat())
ok("פרסר: התשובה נשמרת כספרה", [r["answer"] for r in rows] == ["2", "1", "1", "3"])

entries = [{"phone": "0501234567", "name": "כהן", "status": "done", "ok": True},
           {"phone": "0529999999", "name": "לוי", "status": "done", "ok": True},
           {"phone": "0521111222", "name": "מזרחי", "status": "no_answer", "failed": True},
           {"phone": "0538888888", "name": "שקט", "status": "done", "ok": True}]
sent = "2026-09-02T15:00:00+00:00"          # הצינתוק יצא היום 18:00 ישראל
entries, changed = yemot.merge_survey_answers(entries, rows, sent)
by = {e["phone"]: e for e in entries}
ok("merge: התשובה האחרונה גוברת (2 ואז 1 → 1)", by["0501234567"]["answer"] == "1")
ok("merge: תשובה משבוע שעבר לא נספרת", by["0529999999"]["answer"] == "")
ok("merge: לא-נענה שהקיש 3 בהתקשרות חוזרת", by["0521111222"]["answer"] == "3")
ok("merge: מי שלא הקיש = מפתח answer ריק (לא הגיב)",
   by["0538888888"]["answer"] == "" and "answer_at" in by["0538888888"])
ok("merge: changed בפעם הראשונה", changed)
_, changed2 = yemot.merge_survey_answers(entries, rows, sent)
ok("merge: אותם נתונים שוב → changed=False", not changed2)
ok("survey_checked אחרי merge", yemot.survey_checked(entries) and not yemot.survey_checked([{"phone": "1"}]))
cnt = yemot.answer_counts(entries)
ok("answer_counts", cnt == {"1": 1, "2": 0, "3": 1, "": 2}, str(cnt))

# תוויות ניתנות לעריכה + ברירות מחדל
ok("תוויות ברירת מחדל", yemot.answer_labels() == {"1": "מגיע", "2": "לא מגיע", "3": "לא יודע"})
db.set_setting(yemot.SET_ANSWER_LABELS, json.dumps({"2": "לא מגיע השבוע", "3": ""}))
ok("דריסת תווית + ריק=ברירת מחדל",
   yemot.answer_labels() == {"1": "מגיע", "2": "לא מגיע השבוע", "3": "לא יודע"})
ok("answer_label", yemot.answer_label("2") == "לא מגיע השבוע" and yemot.answer_label("9") == "")
db.set_setting(yemot.SET_ANSWER_LABELS, "")
ok("טקסט השאלה — ברירת מחדל", yemot.survey_prompt_text() == yemot.DEFAULT_SURVEY_PROMPT)
db.set_setting(yemot.SET_SURVEY_PROMPT, "  מגיעים? 1 כן 2 לא  ")
ok("טקסט השאלה — מההגדרה", yemot.survey_prompt_text() == "מגיעים? 1 כן 2 לא")
calls.clear()
what = yemot.upload_survey_prompt()
up = [p for c, p in calls if c == "UploadTextFile"]
ok("upload_survey_prompt → UploadTextFile לשלוחה 77", what == "ivr2:/77/050.tts" and up
   and up[0].get("what") == "ivr2:/77/050.tts" and up[0].get("contents") == "מגיעים? 1 כן 2 לא",
   str(up[:1]))

# הורדת קובץ התשובות: בייטים → שורות; JSON (אין קובץ) → []
def survey_transport(url, data):
    if "DownloadFile" in url:
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        calls.append(("DownloadFile", q))
        return ymgr.encode("utf-8") if q.get("path") == "ivr2:/77/ApprovalAll.ymgr" else b'{"responseStatus":"ERROR"}'
    return fake_transport(url, data)
yemot._TRANSPORT = survey_transport
calls.clear()
fetched = yemot.fetch_survey_rows()
ok("fetch_survey_rows קורא מ-ivr2:/77/ApprovalAll.ymgr", len(fetched) == 4
   and calls and calls[0][1].get("path") == "ivr2:/77/ApprovalAll.ymgr")
yemot.SURVEY_EXT = "78"
ok("אין קובץ (תשובת JSON) → רשימה ריקה", yemot.fetch_survey_rows() == [])
yemot.SURVEY_EXT = "77"
yemot._TRANSPORT = fake_transport

# תשובות לפי תאריך חלוקה מהדוחות השמורים + סנכרון בין 2 מחשבים
g1 = db.add_tzintuk_campaign("ישן", "2026-09-09", "1", "c-old", 2, device="A")
db.update_tzintuk_campaign(g1, 2, 0, "done", json.dumps(
    [{"phone": "0501234567", "answer": "2", "answer_at": "2026-09-02T16:40:12+00:00"},
     {"phone": "0547777777", "answer": "1", "answer_at": "2026-09-02T16:41:00+00:00"}]))
g2 = db.add_tzintuk_campaign("חדש", "2026-09-09", "1", "c-new", 1, device="A")
db.update_tzintuk_campaign(g2, 1, 0, "done", json.dumps(
    [{"phone": "0501234567", "answer": "1", "answer_at": "2026-09-02T18:00:00+00:00"},
     {"phone": "0509999999", "status": "accepted", "confirmed": True}]))
ans = yemot.answers_for_date("2026-09-09")
ok("answers_for_date — הקמפיין החדש גובר", ans.get("0501234567") == "1" and ans.get("0547777777") == "1")
ok("answers_for_date — תאריך אחר ריק", yemot.answers_for_date("2026-09-16") == {})
conf = yemot.confirmed_phones("2026-09-09")
ok("confirmed_phones = תשובה 1 + accepted ישן",
   conf == {"0501234567", "0547777777", "0509999999"}, str(conf))
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("התשובות מגיעות למחשב השני דרך הסנכרון",
   yemot.answers_for_date("2026-09-09").get("0501234567") == "1")
use_machine(dir_a)

# ── 8. שעה אישית בשיטת החריגה + שיגור חכם פר-שעה (#y7jr0 שלב 2) ──────────────
print("— שיטת החריגה + שיגור חכם —")
# 13:00 היא שעת השיא הכללית (כי אז שולחים). שיטת החריגה בוחרת שעה שבה האדם
# בולט מול הכלל — לא את 13:00 שכולם נופלים עליה.
gshare = {h: (0.5 if h == 13 else 0.5 / 23) for h in range(24)}
ok("החריגה בוחרת שעה שבה האדם בולט, לא את שעת השיא הכללית (13:00)",
   yemot.personal_hour({13: 5, 8: 3}, gshare) == 8)
ok("שעה נדירה עם מסה קטנה מדי (שיחה אחת) לא מנצחת",
   yemot.personal_hour({13: 5, 8: 1}, gshare) == 13)
ok("מתחת ל-3 שיחות נכנסות אין שעה אישית",
   yemot.personal_hour({8: 2}, gshare) is None)

stats_l = {"a": {"by_hour": {13: [8, 10], 19: [6, 12]}},
           "b": {"by_hour": {19: [2, 5]}}}
ok("list_best_hour = שעת השיא של הרשימה (fallback כללי)",
   yemot.list_best_hour(["a", "b"], stats_l) == 13)

buckets = yemot.bucket_by_hour(
    {"05x": "a", "05y": "b", "05z": "c"},
    {"05x": {"best_hour": 9}, "05y": {"best_hour": 9}}, 13)
ok("bucket_by_hour: קיבוץ לפי שעה אישית + נפילה לשעה הכללית",
   sorted(buckets) == [9, 13] and set(buckets[9]) == {"05x", "05y"}
   and list(buckets[13]) == ["05z"])

# --- ensure_hour_template + schedule_smart (תחבורה מדומה) ---
_tpl = [9000]
canned["ScheduleCampaign"] = {"responseStatus": "OK"}   # schedId ייווצר בתחבורה


def smart_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if data:
        try:
            params.update({k: v[0] for k, v in
                           urllib.parse.parse_qs(data.decode("utf-8")).items()})
        except UnicodeDecodeError:
            params["_raw"] = data
    calls.append((command, params))
    if command == "DownloadFile":
        return b"RIFF....WAVEmessage-bytes"          # הודעת התבנית הראשית
    if command == "GetTemplates":
        return json.dumps({"responseStatus": "OK", "templates": []}).encode("utf-8")
    if command == "CreateTemplate":
        _tpl[0] += 1
        return json.dumps({"responseStatus": "OK",
                           "templateId": _tpl[0]}).encode("utf-8")
    if command == "ScheduleCampaign":
        return json.dumps({"responseStatus": "OK",
                           "schedId": 5000 + _tpl[0]}).encode("utf-8")
    return json.dumps(canned.get(command, {"responseStatus": "OK"})).encode("utf-8")


yemot._TRANSPORT = smart_transport
db.set_setting(yemot.SET_HOUR_TEMPLATES, "")            # מתחילים נקי
buckets = {9: {"0521111111": "א"}, 13: {"0522222222": "ב", "0523333333": "ג"}}
n0 = len(calls)
results = yemot.schedule_smart(date(2027, 1, 6), buckets)
seq = [c[0] for c in calls[n0:]]
ok("schedule_smart מחזיר רשומה לכל קבוצת-שעה", len(results) == 2)
ok("כל קבוצה קיבלה תבנית ייעודית משלה (בלי דריסה)",
   results[0]["template_id"] != results[1]["template_id"])
ok("לכל קבוצה יש schedId", all(r["schedId"] for r in results))
scheds = [c for c in calls[n0:] if c[0] == "ScheduleCampaign"]
ok("שיגור אחד לכל שעה בשעה הנכונה",
   len(scheds) == 2
   and {c[1].get("time") for c in scheds}
   == {"2027-01-06 09:00", "2027-01-06 13:00"})
ok("ההודעה הועתקה לכל תבנית-שעה (UploadFile)",
   seq.count("UploadFile") == 2)
ok("רשימת הנמענים הועלתה לכל תבנית-שעה",
   seq.count("UploadPhoneList") == 2)
counts = {r["hour"]: r["count"] for r in results}
ok("מספר הנמענים פר-שעה נכון", counts == {9: 1, 13: 2}, str(counts))
saved = json.loads(db.get_setting(yemot.SET_HOUR_TEMPLATES) or "{}")
ok("תבניות-השעה נשמרו בהגדרה מסונכרנת", set(saved) == {"9", "13"})

# ריצה שנייה מאמצת את התבניות השמורות — בלי CreateTemplate נוסף
n1 = len(calls)
yemot.schedule_smart(date(2027, 1, 6), {9: {"0521111111": "א"}})
ok("ריצה שנייה משתמשת בתבנית השמורה (בלי יצירת תבנית חדשה)",
   "CreateTemplate" not in [c[0] for c in calls[n1:]])

# תקלה באמצע: הקבוצות שכבר נקבעו בשרת חוזרות על החריגה (כדי שיירשמו ויוכלו להתבטל)
_sched_n = [0]


def failing_smart_transport(url, data):
    command = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    if command == "ScheduleCampaign":
        _sched_n[0] += 1
        if _sched_n[0] == 2:
            return json.dumps({"responseStatus": "ERROR", "messageCode": 1,
                               "message": "boom"}).encode("utf-8")
    return smart_transport(url, data)


yemot._TRANSPORT = failing_smart_transport
try:
    yemot.schedule_smart(date(2027, 1, 6),
                         {9: {"0521111111": "א"}, 13: {"0522222222": "ב"},
                          16: {"0523333333": "ג"}})
    ok("תקלה באמצע שיגור חכם מעלה חריגה", False)
except yemot.YemotError as e:
    partial = getattr(e, "partial_results", None)
    ok("תקלה באמצע שיגור חכם: הקבוצה שכבר נקבעה מוחזרת על החריגה",
       isinstance(partial, list) and [r["hour"] for r in partial] == [9], str(partial))
yemot._TRANSPORT = fake_transport

# ── 13. v3.15 — פקודות חיוג נשלחות פעם אחת (בלי ניסיון חוזר / שרת תאום) ─────
print("— v3.15: פקודות חיוג יוצאות פעם אחת —")
import urllib.error as _uerr
import time as _time
from utils import timefmt
_real_sleep = _time.sleep
yemot.time.sleep = lambda s: None          # the transient-retry pause
attempts = []


def dead_transport(url, data):
    attempts.append(url)
    raise _uerr.URLError("timed out")


yemot._TRANSPORT = dead_transport
try:
    yemot.check_connection()
    ok("קריאה רגילה: ניסיון חוזר + שרת תאום", False)
except yemot.YemotError as e:
    ok("קריאה רגילה: ניסיון חוזר + שרת תאום (4 ניסיונות)",
       len(attempts) == 4 and e.code == -1
       and sum("private.call2all" in u for u in attempts) == 2, str(len(attempts)))
attempts.clear()
try:
    yemot.run_campaign({"0521111111": "א"}, "1117319")
    ok("RunCampaign: ניסיון אחד בלבד", False)
except yemot.YemotError as e:
    ok("RunCampaign: ניסיון אחד בלבד + הודעת 'ייתכן שהשליחה כבר יצאה'",
       len(attempts) == 1 and "RunCampaign" in attempts[0]
       and "ייתכן שהשליחה" in str(e) and e.code == -1, f"{len(attempts)} {e}")
attempts.clear()
try:
    yemot.run_tzintuk(["0521111111"])
    ok("RunTzintuk: ניסיון אחד בלבד", False)
except yemot.YemotError as e:
    ok("RunTzintuk: ניסיון אחד בלבד", len(attempts) == 1 and e.code == -1)
attempts.clear()
try:
    yemot._call("ScheduleCampaign", {"templateId": "1117319", "time": "2026-10-07 09:00"}, post=True)
    ok("ScheduleCampaign: ניסיון אחד בלבד", False)
except yemot.YemotError as e:
    ok("ScheduleCampaign: ניסיון אחד בלבד", len(attempts) == 1 and e.code == -1)
# a transient hiccup on a READ still recovers on the retry
_n = {"i": 0}


def once_flaky(url, data):
    _n["i"] += 1
    if _n["i"] == 1:
        raise _uerr.URLError("connection reset")
    return fake_transport(url, data)


yemot._TRANSPORT = once_flaky
yemot.check_connection()
ok("תקלה חולפת בקריאה רגילה — הניסיון החוזר מצליח", _n["i"] == 2)
yemot.time.sleep = _real_sleep
yemot._TRANSPORT = fake_transport

# ── 14. v3.15 — מסך הצינתוקים: מעקבים לא דורסים זה את זה; מעבר בין רשימות ──
print("— v3.15: מעקבים ומעבר בין רשימות —")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
import tabs.tzintukim as tzmod
tzmod._PollWorker.start = lambda self: None          # no real threads in tests
tzmod._CallbackWorker.start = lambda self: None
tzmod._TaskWorker.start = lambda self: None
tab = tzmod.TzintukimTab(None)
tab._retire_trackers()
ok("retire בלי מעקבים — שקט", tab._worker is None and tab._cb_worker is None)


def _camp(guid):
    return next(c for c in db.get_tzintuk_campaigns() if c["guid"] == guid)


# (א) מעקב-חזרה של צינתוק קלאסי רץ (למשל של המחשב השני, שנקלט בסנכרון) —
#     ואז שליחה רגילה: המעקב הישן נסגר, מה שאסף נשמר ברשומה *שלו*.
gA = db.add_tzintuk_campaign("צינתוק קלאסי — א", "2026-10-07", "1117319", "", 2,
                             status="sending")
tab._start_callback_tracking(gA, {"0521111111": "א", "0522222222": "ב"},
                             _time.time() + 1800)
cbA = tab._cb_worker
cbA.tracker.update([{"phone": "0521111111", "path": "", "duration": 4.0}], "2026-10-07T10:00:00+00:00")
cbA._snapshot(False)
ok("מעקב קלאסי פעיל עם snapshot", cbA is not None and cbA.last_snapshot["returned"] == 1)
gB = db.add_tzintuk_campaign("חלוקה ב", "2026-10-07", "1117319", "camp-B", 3)
tab._active_guid = gB
tab._start_tracking("camp-B", 3, "")
wB = tab._worker
ok("שליחה רגילה מפטרת מעקב קלאסי שרץ", tab._cb_worker is None and cbA._stop and wB is not None)
rA, rB = _camp(gA), _camp(gB)
ok("מה שהמעקב הקלאסי אסף נשמר ברשומה שלו (sending, לחידוש)",
   rA["status"] == "sending" and rA["delivered"] == 1
   and any(e.get("status") == "callback" and e["phone"] == "0521111111"
           for e in json.loads(rA["report_json"])), str(rA))
ok("הרשומה של השליחה החדשה לא נגעה", rB["status"] == "sending" and rB["delivered"] == 0)
# tick מאוחר של המעקב שפוטר — מתעלמים
tab._on_cb_tick({"done": True, "returned": 2, "entries": [], "answers": {}, "remaining": 0}, cbA)
ok("tick מאוחר של מעקב שפוטר לא נכתב לשום רשומה",
   _camp(gA)["delivered"] == 1 and _camp(gB)["delivered"] == 0)
fin = {"finished": True, "total": 3, "delivered": 2, "failed": 1, "pending": 0,
       "entries": [{"phone": "0521111111", "ok": True, "status": "done"},
                   {"phone": "0523333333", "failed": True, "status": "no_answer"}]}
tab._on_tick(fin, wB)
ok("tick של המעקב הנוכחי נכתב לרשומה הנכונה",
   _camp(gB)["status"] == "done" and _camp(gB)["delivered"] == 2
   and _camp(gA)["status"] == "sending")
# (ב) ההפך: סקר-קמפיין רץ, ואז צינתוק קלאסי — הסקר נסגר ו-tick מאוחר שלו
#     לא נכתב לרשומת הקלאסי.
gC = db.add_tzintuk_campaign("חלוקה ג", "2026-10-14", "1117319", "camp-C", 2)
tab._active_guid = gC
tab._start_tracking("camp-C", 2, "")
wC = tab._worker
gD = db.add_tzintuk_campaign("צינתוק קלאסי — ד", "2026-10-14", "1117319", "", 1,
                             status="sending")
tab._start_callback_tracking(gD, {"0529999999": "ד"}, _time.time() + 1800)
ok("צינתוק קלאסי מפטר סקר-קמפיין שרץ", tab._worker is None and wC._stop
   and tab._cb_worker is not None and tab._cb_worker.guid == gD)
tab._on_tick(dict(fin, delivered=1), wC)
ok("tick מאוחר של הסקר לא נכתב לרשומת הקלאסי",
   _camp(gD)["status"] == "sending" and _camp(gD)["delivered"] == 0
   and _camp(gC)["status"] == "sending")
# מעקב קלאסי שני מחליף את הראשון (עד עכשיו נבלע בשקט)
gE = db.add_tzintuk_campaign("צינתוק קלאסי — ה", "2026-10-14", "1117319", "", 1,
                             status="sending")
cbD = tab._cb_worker
tab._start_callback_tracking(gE, {"0528888888": "ה"}, _time.time() + 1800)
ok("מעקב קלאסי שני מחליף את הראשון ולא נבלע",
   tab._cb_worker is not None and tab._cb_worker.guid == gE and cbD._stop)
tab._retire_trackers()

# (ג) "רשימת החלוקה הנוכחית" יוצאת מחלוקה קודמת / רשימה עצמאית ומנקה תוצאות
tab.load_batch({"id": 424242, "dist_name": "חלוקת פסח", "dist_date": "2026-04-01"})
ok("חלוקה קודמת נטענת (רצועת מקור גלויה)",
   tab._batch is not None and not tab.batch_frame.isHidden()
   and tab._dist_date_iso() == "2026-04-01")
tab._last_entries = [{"phone": "0521111111", "ok": True}]
tab._last_final = True
tab._load_week_list()
ok("'רשימת החלוקה הנוכחית' עוזבת את החלוקה הקודמת",
   tab._batch is None and tab._free is None and tab._list_loaded
   and tab.batch_frame.isHidden()
   and tab._dist_date_iso() == db.next_wednesday().isoformat())
ok("תוצאות הרשימה הקודמת לא זולגות לרשימה החדשה",
   tab._last_entries == [] and not tab._last_final)
tab._free = [("0521111111", "x")]
tab.refresh()
tab._clear_batch()
ok("'נקה את הרשימה' (רשימה עצמאית) → מצב לא-טעון", not tab._list_loaded and tab._free is None)
tab.load_batch({"id": 424242, "dist_name": "חלוקת פסח", "dist_date": "2026-04-01"})
tab._clear_batch()
ok("'חזור לרשימת השבוע' (חלוקה קודמת) → רשימת השבוע טעונה",
   tab._list_loaded and tab._batch is None and tab.batch_frame.isHidden())

# ── 15. סקירה 5/9/2026 — שליחה חוזרת אחרי החלפת רשימה, תזמון בלי מזהה, מעקב שנפל ──
print("— סקירה 5/9: שליחה חוזרת / תזמון בלי מזהה / מעקב שנפל —")
# (א) קמפיין נגמר עם נכשלים על חלוקה קודמת → המפעיל עובר לרשימת השבוע:
#     כפתור "שלח שוב לנכשלים" חייב להיעלם — אחרת השליחה החוזרת יוצאת לאנשי
#     הרשימה הקודמת ונרשמת על תאריך החלוקה של הרשימה החדשה.
tab.load_batch({"id": 424242, "dist_name": "חלוקת פסח", "dist_date": "2026-04-01"})
gF = db.add_tzintuk_campaign("חלוקה פסח", "2026-04-01", "1117319", "camp-F", 2)
tab._active_guid = gF
tab._start_tracking("camp-F", 2, "")
tab._on_tick({"finished": True, "total": 2, "delivered": 1, "failed": 1, "pending": 0,
              "entries": [{"phone": "0521111111", "ok": True, "status": "done"},
                          {"phone": "0523333333", "failed": True, "status": "no_answer"}]},
             tab._worker)
tab._on_worker_done()
ok("אחרי סיום עם נכשלים — כפתור שליחה חוזרת גלוי",
   tab._last_failed and not tab.btn_resend.isHidden())
tab._load_week_list()
ok("מעבר לרשימת השבוע מנקה את רשימת הנכשלים של הרשימה הקודמת",
   tab._last_failed == [] and tab.btn_resend.isHidden())
# (א2) שיגור חכם: הנכשלים של *כל* הקבוצות נשמרים לשליחה חוזרת (לא רק האחרונה)
gG = db.add_tzintuk_campaign("קבוצה 10", "2026-10-21", "T10", "camp-G", 1)
tab._active_guid = gG
tab._start_tracking("camp-G", 1, "")
tab._on_tick({"finished": True, "total": 1, "delivered": 0, "failed": 1, "pending": 0,
              "entries": [{"phone": "0524444444", "failed": True, "status": "no_answer"}]},
             tab._worker)
tab._on_worker_done()
gH = db.add_tzintuk_campaign("קבוצה 12", "2026-10-21", "T12", "camp-H", 1)
tab._active_guid = gH
tab._start_tracking("camp-H", 1, "")
tab._on_tick({"finished": True, "total": 1, "delivered": 0, "failed": 1, "pending": 0,
              "entries": [{"phone": "0525555555", "failed": True, "status": "no_answer"}]},
             tab._worker)
tab._on_worker_done()
ok("שיגור חכם — הנכשלים של כל הקבוצות נצברים לשליחה חוזרת",
   {e["phone"] for e in tab._last_failed} == {"0524444444", "0525555555"},
   str(tab._last_failed))
tab._retire_trackers()

# (ב) תזמון שהשרת לא החזיר לו schedId (campaign_id ריק) ורץ בינתיים:
#     עד עכשיו find_scheduled("") = "לא קיים" → אחרי שעה סומן "התזמון נכשל"
#     בזמן שהשרת כבר חייג, והתוצאות מעולם לא נעקבו. האיתור לפי התבנית+השעה.
from datetime import timedelta as _td, timezone as _tz
_planned = datetime.now(_tz.utc) - _td(hours=2)
_planned_local = _planned.astimezone(timefmt._israel_zone()).strftime("%Y-%m-%d %H:%M:%S")
gS = db.add_tzintuk_campaign("צינתוק מתוזמן — בלי מזהה", "2026-11-04", "T-H09", "", 3,
                             sent_at=_planned.isoformat(), status="scheduled")
def sched_by_type_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if command == "GetScheduledCampaigns":
        items = []
        if params.get("type") == "SUCCESSFUL":
            items = [{"schedId": 900, "templateId": "T-H09", "campaignId": "camp-old",
                      "startTime": "2026-01-01 09:00:00"},        # ריצה ישנה של אותה תבנית
                     {"schedId": 901, "templateId": "T-H09", "campaignId": "camp-901",
                      "startTime": _planned_local}]
        return json.dumps({"responseStatus": "OK", "scheduled": items}).encode("utf-8")
    return fake_transport(url, data)
yemot._TRANSPORT = sched_by_type_transport
tab._check_scheduled()
ok("בודק-התזמונים יצא לדרך", tab._sched_checker is not None)
tab._sched_checker.run()          # start() מנוטרל — מריצים את הבדיקה כאן
recS = _camp(gS)
ok("תזמון בלי מזהה שרץ — מזוהה לפי התבנית והשעה (לא 'נכשל')",
   recS["status"] == "sending" and recS["campaign_id"] == "camp-901", str(recS))
ok("…והמעקב אחרי התוצאות מתחיל", tab._worker is not None
   and tab._worker.campaign_id == "camp-901")
tab._retire_trackers()
# תזמון בלי מזהה שעדיין ממתין בשרת (פורמט `time` של PENDING) — המזהה נשמר
# ברשומה כדי ש"בטל תזמון" ידע למי לפנות; הסטטוס נשאר "מתוזמן"
_soon = datetime.now(_tz.utc) - _td(minutes=2)
_soon_local = _soon.astimezone(timefmt._israel_zone()).strftime("%Y-%m-%d %H:%M")
gP = db.add_tzintuk_campaign("צינתוק מתוזמן — ממתין בלי מזהה", "2026-11-18", "T-H10", "", 2,
                             sent_at=_soon.isoformat(), status="scheduled")
def pending_by_time_transport(url, data):
    q = urllib.parse.urlparse(url)
    command = q.path.rsplit("/", 1)[-1]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if command == "GetScheduledCampaigns":
        items = ([{"schedId": 910, "templateId": "T-H10", "time": _soon_local}]
                 if params.get("type") == "PENDING" else [])
        return json.dumps({"responseStatus": "OK", "scheduled": items}).encode("utf-8")
    return fake_transport(url, data)
yemot._TRANSPORT = pending_by_time_transport
tab._check_scheduled()
tab._sched_checker.run()
recP = _camp(gP)
ok("תזמון ממתין בלי מזהה — המזהה מאותר ונשמר, הסטטוס נשאר מתוזמן",
   recP["status"] == "scheduled" and recP["campaign_id"] == "910", str(recP))
db.update_tzintuk_campaign(gP, 0, 0, "canceled")
db.update_tzintuk_campaign(gS, 0, 0, "done")
yemot._TRANSPORT = fake_transport

# (ג) מעקב חי שנפל (5 כשלי רשת) — הרשומה נשארת 'sending' והמסך "המעקב נכשל"
#     עד ביקור מקרי בלשונית. עכשיו: ניסיון חידוש אוטומטי אחרי דקה.
_shots = []
_orig_single = tzmod.QTimer.singleShot
tzmod.QTimer.singleShot = staticmethod(lambda ms, fn: _shots.append((ms, fn)))
try:
    gX = db.add_tzintuk_campaign("חלוקה X", "2026-11-11", "1117319", "camp-X", 1)
    tab._active_guid = gX
    tab._start_tracking("camp-X", 1, "")
    wX = tab._worker
    wX.failed = True
    tab._on_tick(RuntimeError("net"), wX)
    tab._on_worker_done()
    ok("מעקב שנפל מתזמן חידוש אוטומטי (~דקה)",
       any(ms >= 30000 and getattr(fn, "__name__", "") == "_maybe_resume_tracking"
           for ms, fn in _shots), str([(ms, getattr(fn, "__name__", fn)) for ms, fn in _shots]))
finally:
    tzmod.QTimer.singleShot = _orig_single
tab._retire_trackers()

print()
if fails:
    print(f"✗ {len(fails)} בדיקות נכשלו: {fails}")
    sys.exit(1)
print("✓ כל בדיקות הצינתוקים עברו")
sys.exit(0)

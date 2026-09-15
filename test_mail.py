# -*- coding: utf-8 -*-
"""בדיקות מסך המיילים (v3.39) — בלי רשת:
utils/google_auth (OAuth עם תחבורה מדומה), utils/mailer (placeholders, יעדים,
HTML, שליחה עם ניתוב Google/SMTP), DB (mail_campaigns/mail_templates) וסנכרון
בין 2 מחשבים (mail_add/mail_update/mtpl_upsert + seed).
"""
import os, sys, json, tempfile, base64, urllib.parse
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

import database as db
from utils import sync, google_auth, mailer, email_utils

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

root = tempfile.mkdtemp(prefix="mail_test_")
dir_a = os.path.join(root, "pc_a"); os.makedirs(dir_a)
dir_b = os.path.join(root, "pc_b"); os.makedirs(dir_b)
shared = os.path.join(root, "drive"); os.makedirs(shared)


def use_machine(d):
    db.DB_PATH = os.path.join(d, "data.db")
    sync.STATE_PATH = os.path.join(d, "sync_state.json")
    sync.OUTBOX_PATH = os.path.join(d, "sync_outbox.jsonl")
    sync._state_cache = None
    db.init_db()


use_machine(dir_a)

# ─── 1. google_auth — זרימת התחברות עם שרת מדומה ────────────────────────────
calls = []
def fake_transport(method, url, data, headers):
    calls.append((method, url, data, headers))
    if url == google_auth.TOKEN_URL:
        form = urllib.parse.parse_qs((data or b"").decode())
        if form.get("grant_type") == ["authorization_code"]:
            assert form.get("code_verifier"), "PKCE verifier missing"
            payload = base64.urlsafe_b64encode(json.dumps({"email": "kupa@gmail.com"}).encode()).rstrip(b"=").decode()
            return 200, json.dumps({"access_token": "AT1", "refresh_token": "RT1",
                                    "expires_in": 3600, "id_token": f"h.{payload}.s"}).encode()
        if form.get("grant_type") == ["refresh_token"]:
            if form.get("refresh_token") == ["DEAD"]:
                return 400, json.dumps({"error": "invalid_grant"}).encode()
            return 200, json.dumps({"access_token": "AT2", "expires_in": 3600}).encode()
    if url == google_auth.GMAIL_SEND_URL:
        tok = headers.get("Authorization", "")
        if tok == "Bearer STALE":
            return 401, b'{"error":{"message":"Invalid Credentials"}}'
        body = json.loads(data)
        raw = base64.urlsafe_b64decode(body["raw"] + "==")
        if b"bad@" in raw:
            return 400, b'{"error":{"message":"Invalid to header / recipient address"}}'
        return 200, json.dumps({"id": "msg-%d" % len(calls)}).encode()
    if url == google_auth.REVOKE_URL:
        return 200, b""
    return 404, b""

google_auth._TRANSPORT = fake_transport
seen_urls = []
google_auth._CODE_PROVIDER = lambda url: (seen_urls.append(url) or "CODE123")

# בלי זיהוי-לקוח — ההתחברות מסבירה במקום לקרוס
try:
    from utils import _secret
    _secret.GOOGLE_CLIENT_ID = ""; _secret.GOOGLE_CLIENT_SECRET = ""
except Exception:
    pass
ok("is_available()=False בלי client_id", not google_auth.is_available())
try:
    google_auth.connect(); ok("connect בלי client_id מעלה שגיאה", False)
except google_auth.GoogleAuthError as e:
    ok("connect בלי client_id מעלה שגיאה בעברית", "לא הופעל" in str(e))

# קובץ google_client.json ליד ה-DB (fallback לפיתוח)
with open(os.path.join(dir_a, google_auth.CLIENT_FILE), "w", encoding="utf-8") as f:
    json.dump({"installed": {"client_id": "CID.apps", "client_secret": "SEC"}}, f)
ok("is_available()=True מקובץ ליד ה-DB", google_auth.is_available())
email = google_auth.connect()
ok("connect מחזיר את המייל מה-id_token", email == "kupa@gmail.com", email)
ok("refresh_token נשמר ב-settings", db.get_setting(google_auth.SET_REFRESH) == "RT1")
ok("is_connected()", google_auth.is_connected())
q = urllib.parse.parse_qs(urllib.parse.urlparse(seen_urls[0]).query)
ok("URL ההתחברות: gmail.send + offline + consent + S256",
   "gmail.send" in q["scope"][0] and q["access_type"] == ["offline"]
   and q["prompt"] == ["consent"] and q["code_challenge_method"] == ["S256"])
ok("ההרשאה לא כוללת קריאת מיילים", "readonly" not in q["scope"][0] and "mail.google.com" not in q["scope"][0])

# ─── 2. email_utils מנתב דרך Gmail API כשמחובר ─────────────────────────────
ok("email_utils.is_configured() דרך Google בלבד", email_utils.is_configured() and not email_utils.smtp_configured())
ok("sender_email = חשבון גוגל", email_utils.sender_email() == "kupa@gmail.com")
n0 = len(calls)
email_utils.send_email("dest@example.com", "נושא", "<div>גוף</div>")
sent_calls = [c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]
ok("send_email → Gmail API (בלי SMTP)", len(sent_calls) == 1)
raw = base64.urlsafe_b64decode(json.loads(sent_calls[0][2])["raw"] + "==")
ok("MIME: From=חשבון גוגל (עם שם הקופה), To=נמען", b"<kupa@gmail.com>" in raw and b"To: dest@example.com" in raw)
# טוקן ישן → ריענון וניסיון שני
google_auth._cache.update(token="STALE", exp=9e12)
n0 = len(calls)
email_utils.send_email("dest2@example.com", "x", "y")
ok("401 → ריענון טוקן ושליחה חוזרת", google_auth._cache["token"] == "AT2"
   and sum(1 for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL) == 2)
try:
    email_utils.send_email("bad@x.com", "x", "y"); ok("כתובת שגויה → שגיאה", False)
except Exception as e:
    ok("כתובת שגויה → שגיאה בעברית", "שגויה" in str(e), str(e))
# refresh שמת בגוגל → מנותק + הודעה
db.set_setting(google_auth.SET_REFRESH, "DEAD"); google_auth._cache.update(token="", exp=0)
try:
    google_auth.access_token(); ok("invalid_grant מעלה", False)
except google_auth.GoogleAuthError as e:
    ok("invalid_grant → הודעה 'פג או בוטל' + ניתוק", "פג" in str(e) and not google_auth.is_connected())
google_auth.connect()   # מתחברים שוב להמשך הבדיקות

# ─── 3. mailer — placeholders, יעדים, HTML ─────────────────────────────────
rec = {"id": 1, "full_name": "כהן ישראל", "first_name": "ישראל", "email": "a@x.com"}
ctx = {"dist_date": "16/09/2026", "parsha": "נצבים"}
ok("render {שם}/{שם פרטי}/{תאריך חלוקה}/{פרשה}",
   mailer.render("שלום {שם} ({שם פרטי}) — {תאריך חלוקה}, {פרשה}", rec, ctx)
   == "שלום כהן ישראל (ישראל) — 16/09/2026, נצבים")
ok("שם פרטי נגזר מ-full_name משפחה-קודם", mailer.render("{שם פרטי}", {"full_name": "לוי משה"}) == "משה")
ok("כתובת חיצונית: {שם} = fallback", mailer.render("{שם}", None, {"fallback_name": "x@y.com"}) == "x@y.com")
recs = [rec, {"id": 2, "full_name": "בלי מייל", "email": ""},
        {"id": 3, "full_name": "שבור", "email": "לא-מייל"},
        {"id": 4, "full_name": "כפול", "email": "A@X.com"}]
tg = mailer.build_targets(recs, ["ext@z.com", "a@x.com", "bad"])
ok("build_targets: 2 תקינים (מקבל + חיצוני)", sum(1 for t in tg if t["ok"]) == 2, [t["reason"] for t in tg])
ok("סיבות דילוג בעברית", [t["reason"] for t in tg if not t["ok"]]
   == ["אין כתובת מייל בכרטיס", "כתובת מייל לא תקינה", "אותה כתובת כבר ברשימה",
       "אותה כתובת כבר ברשימה", "כתובת מייל לא תקינה"])
h = mailer.html_body("שורה <b>\nשנייה\n\nפסקה", True)
ok("html_body: RTL, escape, פסקאות, לוגו cid", "dir='rtl'" in h and "&lt;b&gt;" in h
   and h.count("<p") == 2 and "cid:logo" in h)
ok("html_body בלי כותרת — בלי לוגו", "cid:logo" not in mailer.html_body("x", False))

# send_batch עם עצירה ודוח
prog = []
rows = mailer.send_batch([t for t in tg if t["ok"]] + [{"rec_id": 9, "name": "רע", "email": "bad@x.com", "ok": True}],
                         "נושא {שם}", "גוף {שם}", ctx, rec_by_id={1: rec},
                         progress=lambda d, t, r: prog.append((d, t)))
ok("send_batch: 2 נשלחו, 1 נכשל", mailer.summarize(rows) == (2, 1), rows)
ok("progress נקרא לכל נמען", prog == [(1, 3), (2, 3), (3, 3)])
ok("שורת הדוח נושאת rec_id/שם/מייל/שגיאה", rows[2]["rec_id"] == 9 and rows[2]["error"])
stop_after = {"n": 0}
def should_stop():
    stop_after["n"] += 1
    return stop_after["n"] > 1
rows = mailer.send_batch([t for t in tg if t["ok"]], "s", "b", should_stop=should_stop)
ok("עצירה: הראשון נשלח, השני skipped", [r["status"] for r in rows] == ["sent", "skipped"])

# ─── 4. DB + סנכרון בין 2 מחשבים ──────────────────────────────────────────
sync.enable_sync(shared, seed=False)
sync.set_device_name("A") if hasattr(sync, "set_device_name") else None
g = db.add_mail_campaign("נושא", "גוף", "כל המקבלים", "kupa@gmail.com", 3, device="A")
ok("add_mail_campaign idempotent", db.add_mail_campaign("x", "y", "z", "w", 1, guid=g) == g
   and db.get_mail_campaign(g)["subject"] == "נושא")
report = json.dumps([{"rec_id": 1, "name": "כהן ישראל", "email": "a@x.com", "status": "sent", "error": ""},
                     {"rec_id": 2, "name": "לוי", "email": "b@x.com", "status": "failed", "error": "שגויה"}],
                    ensure_ascii=False)
db.update_mail_campaign(g, 1, 1, "done", report)
ok("update_mail_campaign", db.get_mail_campaign(g)["status"] == "done")
m = db.get_mails_for_recipient(1)
ok("get_mails_for_recipient", len(m) == 1 and m[0]["status"] == "sent" and m[0]["subject"] == "נושא")
ok("get_mails_for_recipient — מי שלא נשלח לו", db.get_mails_for_recipient(7) == [])
tg1 = db.upsert_mail_template("תזכורת", "נושא", "גוף")
db.upsert_mail_template("תזכורת 2", "נושא2", "גוף2", guid=tg1)
ok("upsert template לפי guid", [t["name"] for t in db.get_mail_templates()] == ["תזכורת 2"])
tg2 = db.upsert_mail_template("למחיקה", "a", "b")
db.delete_mail_template(tg2)
ok("delete template = deleted=1 (לא מוצג)", [t["guid"] for t in db.get_mail_templates()] == [tg1])
sync.push_changes() if hasattr(sync, "push_changes") else None

# מחשב B מצטרף — מקבל seed
use_machine(dir_b)
sync.enable_sync(shared, seed=False)
sync.pull_changes()
cb = db.get_mail_campaign(g)
ok("B רואה את השליחה של A", cb is not None and cb["status"] == "done" and cb["sent"] == 1)
ok("B רואה את הדוח לפי נמען", db.get_mails_for_recipient(1) and db.get_mails_for_recipient(1)[0]["status"] == "sent")
ok("B רואה תבניות (ולא את המחוקה)", [t["name"] for t in db.get_mail_templates()] == ["תזכורת 2"])
# LWW: B מעדכן תבנית, A מקבל
db.upsert_mail_template("תזכורת B", "נושאB", "גוףB", guid=tg1)
use_machine(dir_a)
sync.pull_changes()
ok("A מקבל את עדכון התבנית מ-B (LWW)", db.get_mail_templates()[0]["name"] == "תזכורת B")
# עדכון ישן לא דורס חדש
old = {"guid": g, "sent": 0, "failed": 0, "status": "sending", "ts": "2000-01-01T00:00:00", "report_json": ""}
with db.get_connection() as conn:
    sync._apply_mail_update(conn, old)
ok("mail_update ישן נדחה (LWW)", db.get_mail_campaign(g)["status"] == "done")
# seed מלא ל-C
sync.snapshot()
dir_c = os.path.join(root, "pc_c"); os.makedirs(dir_c)
use_machine(dir_c)
sync.enable_sync(shared, seed=False)
sync.pull_changes()
ok("מחשב חדש מקבל היסטוריה+תבניות מה-seed", db.get_mail_campaign(g) is not None
   and [t["name"] for t in db.get_mail_templates()] == ["תזכורת B"])
ok("מחשב חדש מחובר לגוגל דרך הסנכרון (setting משותף ב-seed)",
   db.get_setting(google_auth.SET_REFRESH) == "RT1"
   and db.get_setting(google_auth.SET_EMAIL) == "kupa@gmail.com")
# reset (כולל היסטוריה) מוחק היסטוריית מיילים
db.reset_all_data(tzintuk=True)
ok("reset_all_data מנקה mail_campaigns", db.get_mail_campaigns() == [])

# ─── v3.41: קובץ-זיהוי מגוגל שנטען בהגדרות (settings מסונכרנות) ─────────────
use_machine(dir_a)
h = mailer.html_body("שלום", True)
ok("כותרת המייל: לוגו עם width/height כאטריבוטים ובלי flex",
   "width='44' height='44'" in h and "display:flex" not in h and "<table" in h)
ok("בלי כותרת — אין לוגו", "cid:logo" not in mailer.html_body("שלום", False))
cdir = tempfile.mkdtemp(prefix="gclient_")
def _w(name, obj):
    pth = os.path.join(cdir, name)
    with open(pth, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return pth
try:
    from utils import _secret
    _had = getattr(_secret, "GOOGLE_CLIENT_ID", None)
    _secret.GOOGLE_CLIENT_ID = ""
except Exception:
    _secret = None
db.set_setting(google_auth.SET_CLIENT_ID, ""); db.set_setting(google_auth.SET_CLIENT_SECRET, "")
os.remove(os.path.join(dir_a, google_auth.CLIENT_FILE))   # הקובץ מהמקטע הראשון
ok("בלי קובץ זיהוי — לא זמין", not google_auth.is_available())
cid = google_auth.import_client_file(_w("installed.json", {"installed": {
    "client_id": "123-abc.apps.googleusercontent.com", "client_secret": "S1"}}))
ok("טעינת קובץ installed → זמין + settings", cid.endswith(".apps.googleusercontent.com")
   and google_auth.is_available() and google_auth.client_credentials() == (cid, "S1"))
for name, obj, why in (("flat.json", {"client_id": "9-x.apps.googleusercontent.com", "client_secret": "S2"}, "שטוח"),):
    ok("פורמט " + why, google_auth.import_client_file(_w(name, obj)) == "9-x.apps.googleusercontent.com")
for name, obj in (("web.json", {"web": {"client_id": "w.apps.googleusercontent.com", "client_secret": "x"}}),
                  ("junk.json", {"foo": "bar"})):
    try:
        google_auth.import_client_file(_w(name, obj)); bad = False
    except google_auth.GoogleAuthError:
        bad = True
    ok("קובץ לא מתאים נדחה בעברית: " + name, bad)
with open(os.path.join(cdir, "notjson.json"), "w") as f:
    f.write("hello")
try:
    google_auth.import_client_file(os.path.join(cdir, "notjson.json")); bad = False
except google_auth.GoogleAuthError:
    bad = True
ok("קובץ שאינו JSON נדחה", bad)
# הזיהוי מסתנכרן למחשב B
use_machine(dir_b); sync.pull_changes()
ok("קובץ הזיהוי מגיע למחשב B דרך הסנכרון", google_auth.client_credentials()[0] == "9-x.apps.googleusercontent.com")
# loopback: בקשת favicon לפני ה-redirect לא שוברת את ההמתנה לקוד
import http.server, threading, urllib.request
srv = http.server.HTTPServer(("127.0.0.1", 0), google_auth._OneShotHandler)
srv.expected_state = "ST"; srv.got_it = threading.Event(); srv.timeout = 1.0
google_auth._OneShotHandler.result = {}
port = srv.server_port
def _client():
    import time as _t; _t.sleep(0.2)
    try: urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico", timeout=3)
    except Exception: pass
    urllib.request.urlopen(f"http://127.0.0.1:{port}/?state=ST&code=CODE9", timeout=3).read()
threading.Thread(target=_client, daemon=True).start()
google_auth._TRANSPORT = None
google_auth.webbrowser.open = lambda *a, **k: None
try:
    code = google_auth._wait_for_code("about:blank", srv, 8)
finally:
    srv.server_close(); google_auth._TRANSPORT = fake_transport
ok("loopback: favicon לפני הקוד לא מאבד את הקוד", code == "CODE9")
if _secret is not None and _had is not None:
    _secret.GOOGLE_CLIENT_ID = _had

# ─── 6. v3.42 — תקלה כללית עוצרת את האצווה; SMTP: סיסמה שגויה ≠ "אין אינטרנט";
#        התקדמות נשמרת מקומית כדי ששליחה שנקטעה תדע מי כבר קיבל ─────────────────
print("— v3.42: עצירה על תקלה כללית / הודעות SMTP / התקדמות שנשמרת —")
use_machine(dir_a)
# (א) מכסת Gmail (429) אצל הנמען הראשון — השאר לא מנסים 500 פעם, מסומנים skipped עם הסיבה
_orig_transport = google_auth._TRANSPORT
def _quota_transport(method, url, data, headers):
    if url == google_auth.GMAIL_SEND_URL:
        calls.append((method, url, data, headers))
        return 429, b'{"error":{"message":"User-rate limit exceeded"}}'
    return fake_transport(method, url, data, headers)
google_auth._TRANSPORT = _quota_transport
tg6 = [{"rec_id": None, "guid": "", "name": f"n{i}", "email": f"p{i}@x.com", "ok": True, "reason": ""}
       for i in range(5)]
n0 = len(calls)
rows6 = mailer.send_batch(tg6, "s", "b")
sends6 = sum(1 for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL)
ok("מכסה (429) → ניסיון שליחה אחד בלבד, לא לכל 5 הנמענים", sends6 == 1, sends6)
ok("הראשון failed, השאר skipped", [r["status"] for r in rows6] == ["failed"] + ["skipped"] * 4,
   [r["status"] for r in rows6])
ok("ה-skipped נושאים את סיבת העצירה (המכסה), לא 'נעצר' סתם",
   all("מכסת" in r["error"] for r in rows6[1:]), rows6[1]["error"])
ok("mailer.stop_reason מחזיר את הסיבה", "מכסת" in mailer.stop_reason(rows6))
google_auth._TRANSPORT = _orig_transport
# (ב) כתובת שגויה של נמען אחד = כישלון מקומי, האצווה ממשיכה
tg6b = [{"rec_id": None, "guid": "", "name": "a", "email": "bad@x.com", "ok": True, "reason": ""},
        {"rec_id": None, "guid": "", "name": "b", "email": "good@x.com", "ok": True, "reason": ""}]
rows6b = mailer.send_batch(tg6b, "s", "b")
ok("כתובת שגויה לא עוצרת את האצווה", [r["status"] for r in rows6b] == ["failed", "sent"])
ok("בלי עצירה כללית — stop_reason ריק", mailer.stop_reason(rows6b) == "")
# עצירה ידנית ("עצור") נשארת עם ההודעה הרגילה ובלי סיבת-תקלה
_flag = {"stop": False}
rows6c = mailer.send_batch(tg6b[1:] * 3, "s", "b", progress=lambda d, t, r: _flag.update(stop=True),
                           should_stop=lambda: _flag["stop"])
ok("עצור ידני → skipped עם 'נעצר', stop_reason ריק",
   [r["status"] for r in rows6c] == ["sent", "skipped", "skipped"] and mailer.stop_reason(rows6c) == "")
# (ג) SMTP — סיסמת-אפליקציה שגויה חייבת להגיד את זה, לא "אין חיבור לאינטרנט"
import smtplib
google_auth.disconnect(revoke=False)
email_utils.set_smtp_config("kupa@gmail.com", "app-pass")
_orig_connect = email_utils._connect
def _bad_login(cfg):
    raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
email_utils._connect = _bad_login
try:
    email_utils.send_email("dest@example.com", "x", "y"); ok("סיסמה שגויה מעלה", False)
except Exception as e:
    ok("SMTP: סיסמה שגויה → 'סיסמת האפליקציה' (לא 'אין חיבור לאינטרנט')",
       "סיסמ" in str(e) and "אינטרנט" not in str(e), str(e))
    ok("סיסמה שגויה = תקלה כללית (עוצרת אצווה)", mailer.is_fatal(e))
rows6d = mailer.send_batch(tg6b, "s", "b")
ok("SMTP סיסמה שגויה: ניסיון אחד, השאר skipped", [r["status"] for r in rows6d] == ["failed", "skipped"])
class _RefuseSMTP:
    def sendmail(self, frm, to, msg):
        raise smtplib.SMTPRecipientsRefused({to[0]: (550, b"5.1.1 The email account does not exist")})
    def quit(self): pass
email_utils._connect = lambda cfg: _RefuseSMTP()
try:
    email_utils.send_email("dest@example.com", "x", "y"); ok("נמען שסורב מעלה", False)
except Exception as e:
    ok("SMTP: נמען שסורב → הודעה בעברית (לא repr של dict)", "כתובת" in str(e) and "{" not in str(e), str(e))
    ok("נמען שסורב = תקלה מקומית (לא עוצרת אצווה)", not mailer.is_fatal(e))
class _LimitSMTP:
    def sendmail(self, frm, to, msg):
        raise smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded")
    def quit(self): pass
email_utils._connect = lambda cfg: _LimitSMTP()
try:
    email_utils.send_email("dest@example.com", "x", "y"); ok("מכסה SMTP מעלה", False)
except Exception as e:
    ok("SMTP: מכסה יומית → הודעה בעברית + תקלה כללית", "מכסת" in str(e) and mailer.is_fatal(e), str(e))
email_utils._connect = _orig_connect
email_utils.set_smtp_config("", "")
google_auth.connect()
# (ד) עדכון מקומי (בלי סנכרון) של ההתקדמות — שליחה שנקטעה יודעת מי כבר קיבל
g6 = db.add_mail_campaign("s", "b", "כולם", "kupa@gmail.com", 3, device="PC-A")
_before = os.path.getsize(sync.OUTBOX_PATH) if os.path.exists(sync.OUTBOX_PATH) else 0
_jn = [f for f in os.listdir(shared) if f.startswith("journal-")]
_jsize = sum(os.path.getsize(os.path.join(shared, f)) for f in _jn)
db.update_mail_campaign(g6, 1, 0, "sending", json.dumps([{"rec_id": None, "name": "a", "email": "a@x.com",
                                                          "status": "sent", "error": ""}]), sync=False)
_jsize2 = sum(os.path.getsize(os.path.join(shared, f)) for f in
              [f for f in os.listdir(shared) if f.startswith("journal-")])
_after = os.path.getsize(sync.OUTBOX_PATH) if os.path.exists(sync.OUTBOX_PATH) else 0
ok("update_mail_campaign(sync=False) כותב מקומית", db.get_mail_campaign(g6)["sent"] == 1)
ok("…ולא מוסיף רשומה ליומן הסנכרון / ל-outbox", _jsize2 == _jsize and _after == _before)
db.update_mail_campaign(g6, 1, 0, "interrupted", db.get_mail_campaign(g6)["report_json"])
use_machine(dir_b); sync.pull_changes()
cb6 = db.get_mail_campaign(g6)
ok("B רואה את השליחה שנקטעה עם מי שכבר קיבל", cb6 and cb6["status"] == "interrupted"
   and cb6["sent"] == 1 and "a@x.com" in (cb6["report_json"] or ""))

# (ה) המסך: ההתקדמות נכתבת ל-DB בכל נמען, וסיום עם תקלה כללית מציג אזהרה עם הסיבה
use_machine(dir_a)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
import tabs.mails as mmod
_msgs = []
mmod.QMessageBox.information = staticmethod(lambda *a, **k: _msgs.append(("info", str(a[2]))) or 0)
mmod.QMessageBox.warning = staticmethod(lambda *a, **k: _msgs.append(("warn", str(a[2]))) or 0)
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.Yes)
mmod._SendWorker.start = lambda self: None
tab = mmod.MailsTab(None)
tab.refresh()
tab._extra = ["q1@x.com", "q2@x.com", "q3@x.com"]
tab._rebuild_targets()
tab.subject.setText("נושא"); tab.body.setPlainText("גוף")
tab._send()
g7 = tab._active_guid
ok("המסך: רשומת השליחה נוצרה לפני ההתחלה", bool(g7) and db.get_mail_campaign(g7)["status"] == "sending")
r1 = {"rec_id": None, "guid": "", "name": "q1@x.com", "email": "q1@x.com", "status": "sent", "error": ""}
tab._on_progress(1, 3, r1)
c7 = db.get_mail_campaign(g7)
ok("המסך: אחרי נמען אחד ה-DB כבר יודע שהוא קיבל (בלי לחכות לסוף)",
   c7["sent"] == 1 and "q1@x.com" in c7["report_json"], c7["report_json"][:60])
rows7 = [r1,
         {"rec_id": None, "guid": "", "name": "q2@x.com", "email": "q2@x.com", "status": "failed",
          "error": "אין חיבור לאינטרנט — המייל לא נשלח."},
         {"rec_id": None, "guid": "", "name": "q3@x.com", "email": "q3@x.com", "status": "skipped",
          "error": "אין חיבור לאינטרנט — המייל לא נשלח."}]
tab._worker.finished_rows.emit(rows7) if False else tab._on_finished(rows7)
c7 = db.get_mail_campaign(g7)
ok("המסך: סיום עם תקלה כללית → סטטוס 'נעצר' + דוח מלא", c7["status"] == "stopped" and c7["sent"] == 1
   and c7["failed"] == 1 and "q3@x.com" in c7["report_json"])
ok("המסך: ההודעה למפעיל היא אזהרה עם סיבת העצירה ומספר מי שלא נוסה",
   _msgs and _msgs[-1][0] == "warn" and "אינטרנט" in _msgs[-1][1] and "1 לא נוסו" in _msgs[-1][1],
   _msgs[-1] if _msgs else "")
ok("המסך: אחרי הסיום אין שליחה פעילה", tab._worker is None and tab._active_guid == "")
tab.deleteLater()

# ─── 7. v3.43 — סקירת /בדוק-מיילים 14/9/2026 ─────────────────────────────────
print("— v3.43: שליחה שנקטעה זוכרת את מי שלא נוסה / כפתור שליחה-חוזרת / עצור / קובץ עברי —")
use_machine(dir_a)
tab = mmod.MailsTab(None)
tab.refresh()
tab._extra = ["p1@x.com", "p2@x.com", "p3@x.com"]
tab._rebuild_targets()
tab.subject.setText("נושא 7"); tab.body.setPlainText("גוף 7")
# (א) הדוח מכיל את *כל* הנמענים מרגע ההתחלה (pending) — לא רק מי שכבר טופל
tab._send()
g8 = tab._active_guid
rows8 = json.loads(db.get_mail_campaign(g8)["report_json"] or "[]")
ok("הדוח נוצר מראש עם כל 3 הנמענים במצב 'ממתין'", len(rows8) == 3
   and all(r["status"] == "pending" for r in rows8), rows8)
tab._on_progress(1, 3, {"rec_id": None, "guid": "", "name": "p1@x.com", "email": "p1@x.com",
                        "status": "sent", "error": ""})
rows8 = json.loads(db.get_mail_campaign(g8)["report_json"] or "[]")
ok("אחרי נמען אחד: הראשון נשלח, השניים האחרים עדיין ממתינים (לא נעלמו)",
   [r["status"] for r in rows8] == ["sent", "pending", "pending"], rows8)
# התוכנה "נסגרה" באמצע → הפעלה הבאה סוגרת כ'נקטע' ומי שלא נוסה מסומן לשליחה חוזרת
tab2 = mmod.MailsTab(None)
tab2._close_stale_campaigns()
c8 = db.get_mail_campaign(g8)
rows8 = json.loads(c8["report_json"] or "[]")
ok("שליחה שנקטעה: סטטוס 'נקטע', נשלח 1", c8["status"] == "interrupted" and c8["sent"] == 1)
ok("מי שלא נוסה מסומן 'לא נשלח' עם סיבה (כדי ש'שלח שוב לנכשלים' יאסוף אותו)",
   [r["status"] for r in rows8] == ["sent", "skipped", "skipped"] and rows8[1]["error"], rows8)
ok("mailer.resendable מזהה שיש למי לשלוח שוב", mailer.resendable(rows8))
# (ב) כפתור "שלח שוב לנכשלים" מופיע גם כשנכשלו=0 (עצירה ידנית / נקטע)
tab2._refresh_history()
idx8 = next(i for i, c in enumerate(tab2._camps) if c["guid"] == g8)
w8 = tab2.hist.cellWidget(idx8, 5)
btns8 = [b.text() for b in w8.findChildren(mmod.QPushButton)] if w8 else []
ok("היסטוריה: כפתור 'שלח שוב לנכשלים' מופיע לשליחה שנקטעה בלי כישלונות", "שלח שוב לנכשלים" in btns8, btns8)
# שליחה חוזרת אוספת בדיוק את 2 המדולגים
_sent_args = {}
tab2._send = lambda targets=None, audience=None, **kw: _sent_args.update(t=targets, a=audience, **kw)
tab2._resend_failed(idx8)
ok("שליחה חוזרת: בדיוק 2 היעדים שלא נוסו", sorted(t["email"] for t in _sent_args.get("t") or []) == ["p2@x.com", "p3@x.com"],
   _sent_args)
tab2.deleteLater()
# (ג) "עצור" חוזר להיות פעיל בשליחה הבאה
tab._active_guid = g8
tab._stop()
ok("אחרי לחיצה על עצור הכפתור נעול", not tab.btn_stop.isEnabled())
tab._on_finished([{"rec_id": None, "guid": "", "name": "p1@x.com", "email": "p1@x.com", "status": "sent", "error": ""},
                  {"rec_id": None, "guid": "", "name": "p2@x.com", "email": "p2@x.com", "status": "skipped", "error": mailer.STOP_MSG},
                  {"rec_id": None, "guid": "", "name": "p3@x.com", "email": "p3@x.com", "status": "skipped", "error": mailer.STOP_MSG}])
tab._send()
ok("בשליחה הבאה 'עצור' פעיל שוב", tab.btn_stop.isEnabled() and tab._worker is not None)
# (ד) "שלח שוב לנכשלים" באמצע שליחה פעילה לא דורס את הטיוטה
tab._refresh_history()
tab.subject.setText("טיוטה חיה")
tab._resend_failed(next(i for i, c in enumerate(tab._camps) if c["guid"] == g8))
ok("שליחה פעילה: שליחה-חוזרת נחסמת בלי לדרוס את הנושא", tab.subject.text() == "טיוטה חיה"
   and _msgs[-1][0] in ("info", "warn"), _msgs[-1])
# (ה) חריגה כללית בסיום לא מוחקת את ההתקדמות שכבר נרשמה
g9 = tab._active_guid
tab._on_progress(1, 3, {"rec_id": None, "guid": "", "name": "p1@x.com", "email": "p1@x.com", "status": "sent", "error": ""})
tab._on_finished(RuntimeError("קרס"))
c9 = db.get_mail_campaign(g9)
rows9 = json.loads(c9["report_json"] or "[]")
ok("חריגה בסיום: מי שכבר קיבל נשאר בדוח, השאר מסומנים לשליחה חוזרת",
   c9["status"] == "failed" and c9["sent"] == 1 and [r["status"] for r in rows9] == ["sent", "skipped", "skipped"], rows9)
# (ו) קובץ מצורף שנמחק מהדיסק → אזהרה, לא שליחה בלי הקובץ
tab._set_attachment(os.path.join(dir_a, "nothere.pdf"))
n_before = len(db.get_mail_campaigns())
tab._send()
ok("קובץ מצורף חסר: אזהרה ולא נוצרה שליחה", len(db.get_mail_campaigns()) == n_before and tab._worker is None
   and "מצורף" in _msgs[-1][1], _msgs[-1])
tab._set_attachment("")
tab.deleteLater()
# (ז) קובץ מצורף בשם עברי — כותרת תקנית (RFC 2231), לא כותרת מקודדת שבורה
heb = os.path.join(dir_a, "רשימת חלוקה.pdf")
open(heb, "wb").write(b"%PDF-1.4 test")
n0 = len(calls)
email_utils.send_email("dest@example.com", "עם קובץ", "<p>x</p>", attachment_path=heb)
sent = [c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]
raw = base64.urlsafe_b64decode(json.loads(sent[0][2])["raw"] + "==").decode("utf-8", "replace")
cd = next((l for l in raw.splitlines() if l.startswith("Content-Disposition") and "attachment" in l.lower()), "")
ok("שם קובץ עברי: Content-Disposition תקני (filename*=utf-8) ולא =?utf-8?b?",
   "filename*=utf-8''" in raw and not cd.startswith("Content-Disposition: =?"), cd or raw[:300])

# ─── 8. v3.44 — סקירת /בדוק-מיילים 14/9/2026, סבב שלישי ─────────────────────
print("— v3.44: דוח חוצה-מחשבים לפי guid / ניתוק SMTP באמצע / קובץ חסר במייל-בדיקה —")
# (א) rec_id הוא מזהה *מקומי*: במחשב השני אותו מספר = אדם אחר.
shared2 = os.path.join(root, "drive2"); os.makedirs(shared2)
dir_d = os.path.join(root, "pc_d"); os.makedirs(dir_d)
dir_e = os.path.join(root, "pc_e"); os.makedirs(dir_e)
use_machine(dir_e)                                   # E: "לוי" מקבל id=1
sync.enable_sync(shared2, seed=False)
levi_id = db.add_recipient({"full_name": "לוי משה", "email": "levi@x.com", "status": "פעיל"})
use_machine(dir_d)                                   # D: "כהן" מקבל id=1
sync.enable_sync(shared2, seed=False)
cohen_id = db.add_recipient({"full_name": "כהן ישראל", "email": "cohen@x.com", "status": "פעיל"})
cohen_guid = db.get_recipient(cohen_id)["guid"]
ok("תנאי הבדיקה: אותו id מקומי לשני אנשים שונים", cohen_id == levi_id == 1)
gd = db.add_mail_campaign("חוצה", "גוף", "כולם", "kupa@gmail.com", 1, device="D")
db.update_mail_campaign(gd, 0, 1, "done", json.dumps(
    [{"rec_id": cohen_id, "guid": cohen_guid, "name": "כהן ישראל", "email": "cohen@x.com",
      "status": "failed", "error": "x"}], ensure_ascii=False))
sync.push_changes() if hasattr(sync, "push_changes") else None
use_machine(dir_e)
sync.pull_changes()
cohen_e = db.get_recipient_by_guid(cohen_guid)
ok("E קיבל את כהן עם id מקומי אחר", cohen_e is not None and cohen_e["id"] != levi_id, cohen_e and cohen_e["id"])
ok("כרטיס לוי ב-E: לא מציג מייל שנשלח לכהן (אותו rec_id)",
   db.get_mails_for_recipient(levi_id, db.get_recipient(levi_id)["guid"]) == [])
ok("כרטיס כהן ב-E: כן מציג את המייל (לפי guid)",
   len(db.get_mails_for_recipient(cohen_e["id"], cohen_e["guid"])) == 1)
# "שלח שוב לנכשלים" ב-E — לכהן, לא ללוי
tabE = mmod.MailsTab(None)
tabE.refresh()
_sentE = {}
tabE._send = lambda targets=None, audience=None, **kw: _sentE.update(t=targets)
tabE._resend_failed(next(i for i, c in enumerate(tabE._camps) if c["guid"] == gd))
tE = _sentE.get("t") or []
ok("E: שליחה חוזרת הולכת לכהן (לפי guid), לא ללוי (לפי rec_id)",
   [t["email"] for t in tE] == ["cohen@x.com"] and tE[0]["rec_id"] == cohen_e["id"], tE)
# דוח ישן בלי guid ממחשב אחר → לא מנחשים כרטיס לפי rec_id; שולחים לכתובת שבדוח
db.update_mail_campaign(gd, 0, 1, "done", json.dumps(
    [{"rec_id": 1, "guid": "", "name": "כהן ישראל", "email": "cohen@x.com", "status": "failed", "error": "x"}],
    ensure_ascii=False))
tabE._refresh_history()
tabE._resend_failed(next(i for i, c in enumerate(tabE._camps) if c["guid"] == gd))
tE = _sentE.get("t") or []
ok("E: דוח בלי guid ממחשב אחר → לכתובת שבדוח, בלי כרטיס לפי rec_id",
   [t["email"] for t in tE] == ["cohen@x.com"] and tE[0]["rec_id"] is None, tE)
tabE.deleteLater()
# (ב) SMTP: ניתוק באמצע sendmail (אחרי חיבור מוצלח) → עברית, לא חריגה גולמית
use_machine(dir_a)
google_auth.disconnect(revoke=False)
email_utils.set_smtp_config("kupa@gmail.com", "app-pass")
class _DropSMTP:
    def sendmail(self, frm, to, msg):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    def quit(self): pass
email_utils._connect = lambda cfg: _DropSMTP()
try:
    email_utils.send_email("dest@example.com", "x", "y"); ok("ניתוק באמצע מעלה", False)
except Exception as e:
    ok("SMTP: ניתוק באמצע השליחה → הודעה בעברית", "נותק" in str(e) and not mailer.is_fatal(e), str(e))
class _TimeoutSMTP:
    def sendmail(self, frm, to, msg):
        raise TimeoutError("timed out")
    def quit(self): pass
email_utils._connect = lambda cfg: _TimeoutSMTP()
try:
    email_utils.send_email("dest@example.com", "x", "y"); ok("timeout באמצע מעלה", False)
except Exception as e:
    ok("SMTP: timeout באמצע השליחה → הודעה בעברית", "נותק" in str(e), str(e))
email_utils._connect = _orig_connect
email_utils.set_smtp_config("", "")
google_auth.connect()
# (ג) מייל-בדיקה עם קובץ מצורף שנמחק → אזהרה, לא שליחה בלי הקובץ
tabT = mmod.MailsTab(None)
tabT.refresh()
tabT.subject.setText("נ"); tabT.body.setPlainText("ג")
tabT._set_attachment(os.path.join(dir_a, "gone.pdf"))
mmod._BgWorker.start = lambda self: None
tabT._send_test()
ok("מייל-בדיקה: קובץ מצורף חסר → אזהרה ולא נשלח", tabT._test_worker is None and "מצורף" in _msgs[-1][1], _msgs[-1])
tabT.deleteLater()

# disconnect
use_machine(dir_a)
google_auth.disconnect()
ok("disconnect מנקה settings + revoke", not google_auth.is_connected()
   and any(c[1] == google_auth.REVOKE_URL for c in calls))

# ── 9. v3.45: המייל עצמו — טקסט-רגיל חלופי, שם שולח, Date/Message-ID, לוגו קטן ──
print("— v3.45: מבנה המייל (alternative + plain), שם השולח, Date/Message-ID, לוגו מוקטן —")
use_machine(dir_a)
import email as _em
from email.header import decode_header as _dh
_raw9 = {}
class _CapSMTP:
    def sendmail(self, frm, to, msg): _raw9["msg"] = msg; return {}
    def quit(self): pass
_orig_gc9 = email_utils.google_connected
_orig_cfg9 = email_utils.get_smtp_config
email_utils.google_connected = lambda: False
email_utils.get_smtp_config = lambda: {"email": "kupa@gmail.com", "app_password": "x",
                                       "host": "smtp.gmail.com", "port": 587}
email_utils._connect = lambda cfg: _CapSMTP()
_rec9 = {"id": 1, "full_name": "כהן דוד", "first_name": "דוד", "email": "d@x.co"}
_ctx9 = mailer.default_context("2026-09-16")
_txt9 = mailer.render("שלום {שם פרטי},\n\nיש חלוקה ב-{תאריך חלוקה}.\nפרטים: https://example.com/a?b=1&c=2", _rec9, _ctx9)
email_utils.send_email("d@x.co", "תזכורת", mailer.html_body(_txt9), text_body=_txt9,
                       inline_logo_path=os.path.join(root, "nologo.png"))
_m9 = _em.message_from_string(_raw9["msg"])
_types9 = [p.get_content_type() for p in _m9.walk()]
ok("המייל כולל גרסת טקסט-רגיל לצד ה-HTML (multipart/alternative)",
   "multipart/alternative" in _types9 and "text/plain" in _types9 and "text/html" in _types9, _types9)
_plain9 = next((p for p in _m9.walk() if p.get_content_type() == "text/plain"), None)
_ptext9 = _plain9.get_payload(decode=True).decode("utf-8") if _plain9 else ""
ok("הטקסט-הרגיל = הטקסט המרונדר (שם + תאריך)", "שלום דוד" in _ptext9 and "16/09/2026" in _ptext9)
_html9 = next(p for p in _m9.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode("utf-8")
ok("קישור בגוף המייל הופך ל-<a> לחיץ", "<a href='https://example.com/a?b=1&amp;c=2'" in _html9
   or "<a href=\"https://example.com/a?b=1&amp;c=2\"" in _html9, _html9[-200:])
def _dec9(v):
    return "".join(b.decode(c or "ascii") if isinstance(b, bytes) else b for b, c in _dh(v))
ok("From נושא את שם הקופה (לא רק כתובת)", "קופה של צדקה הר יונה" in _dec9(_m9["From"])
   and "kupa@gmail.com" in _dec9(_m9["From"]), _dec9(_m9["From"]))
ok("כותרות Date ו-Message-ID קיימות", bool(_m9["Date"]) and bool(_m9["Message-ID"]))
ok("Message-ID לא מדליף את שם המחשב (דומיין מכתובת השולח)", "@gmail.com>" in (_m9["Message-ID"] or ""))
# בלי text_body (זרימת המתנדבים) — נגזר מה-HTML
email_utils.send_email("d@x.co", "x", "<div dir='rtl'><p>שורה א</p><p>שורה &amp; ב</p></div>")
_m9b = _em.message_from_string(_raw9["msg"])
_p9b = next(p for p in _m9b.walk() if p.get_content_type() == "text/plain").get_payload(decode=True).decode("utf-8")
ok("בלי text_body — טקסט-רגיל נגזר מה-HTML (בלי תגים, ישויות מפוענחות)",
   "שורה א" in _p9b and "שורה & ב" in _p9b and "<" not in _p9b, _p9b)
email_utils.google_connected = _orig_gc9
email_utils.get_smtp_config = _orig_cfg9
email_utils._connect = _orig_connect
# לוגו מוקטן לשליחה — _logo_path (tabs/mails) מחזיר עותק קטן, לא את הקובץ המקורי (725px / 34KB)
from tabs import mails as _mails_mod
_lp9 = _mails_mod._logo_path()
ok("לוגו למייל קיים ונשמר ליד ה-DB הזמני (לא בתיקייה האמיתית)", bool(_lp9) and os.path.exists(_lp9) and _lp9.startswith(dir_a), _lp9)
ok("לוגו למייל מוקטן (≤ 12KB) — לא הקובץ המקורי", bool(_lp9) and os.path.getsize(_lp9) <= 12 * 1024,
   os.path.getsize(_lp9) if _lp9 else -1)

# ── 10. v3.46: 4 באגים קריטיים — סגירה באמצע שליחה / מייל גדול ב-Gmail API /
#        שליחה-חוזרת דורסת טיוטה / התנתקות מגוגל מקפיאה את המסך ──────────────────
print("— v3.46: סגירה באמצע שליחה / מייל גדול / טיוטה בשליחה-חוזרת / התנתקות ברקע —")
use_machine(dir_a)
google_auth._TRANSPORT = fake_transport
if not google_auth.is_connected():
    google_auth.connect()
_orig_q10 = mmod.QMessageBox.question
# (א) סגירת התוכנה באמצע שליחה — אזהרה; אישור → הרשומה נסגרת כ'נקטע' עם מי שקיבל ומי שלא נוסה
tab = mmod.MailsTab(None)
tab.refresh()
tab._extra = ["c1@x.com", "c2@x.com", "c3@x.com"]
tab._rebuild_targets()
tab.subject.setText("נושא 10"); tab.body.setPlainText("גוף 10")
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.Yes)
tab._send()
g10 = tab._active_guid
tab._on_progress(1, 3, {"rec_id": None, "guid": "", "name": "c1@x.com", "email": "c1@x.com",
                        "status": "sent", "error": ""})
ok("המסך יודע שיש שליחה פעילה (sending_active)", hasattr(tab, "sending_active") and tab.sending_active())
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.No)
_r = tab.confirm_close() if hasattr(tab, "confirm_close") else None
ok("סגירה באמצע שליחה: המפעיל מסרב → לא סוגרים, השליחה ממשיכה",
   _r is False and tab._worker is not None and db.get_mail_campaign(g10)["status"] == "sending")
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.Yes)
_r = tab.confirm_close() if hasattr(tab, "confirm_close") else None
c10 = db.get_mail_campaign(g10)
rows10 = json.loads((c10 or {}).get("report_json") or "[]")
ok("סגירה באמצע שליחה: אישור → הרשומה נסגרת כ'נקטע' (לא נשארת 'בתהליך' עד ההפעלה הבאה)",
   _r is True and c10 and c10["status"] == "interrupted" and c10["sent"] == 1
   and [r["status"] for r in rows10] == ["sent", "skipped", "skipped"] and tab._worker is None, (c10 or {}).get("status"))
ok("…והרשומה הסגורה מסתנכרנת (status_ts חדש מהתחלה)", c10 and c10["status_ts"] > c10["sent_at"])
ok("main.py: closeEvent שואל את מסך המיילים לפני סגירה",
   "confirm_close()" in open("main.py", encoding="utf-8").read())
tab.deleteLater()
mmod.QMessageBox.question = _orig_q10

# (ב) מייל גדול דרך Gmail API — הבקשה ב-JSON מוגבלת ל-10MB; מעבר לזה → נתיב upload (message/rfc822)
_up_calls = []
def _size_transport(method, url, data, headers):
    if url.startswith("https://gmail.googleapis.com/upload/"):
        _up_calls.append((method, url, data, headers))
        if len(data or b"") > 30 * 1024 * 1024:
            return 413, b'{"error":{"message":"Request Entity Too Large"}}'
        return 200, b'{"id":"up-1"}'
    return fake_transport(method, url, data, headers)
google_auth._TRANSPORT = _size_transport
_big = b"x" * (6 * 1024 * 1024)
n0 = len(calls)
google_auth.gmail_send_raw(_big)
ok("מייל של 6MB נשלח בנתיב ה-upload של Gmail (message/rfc822), לא כ-JSON (מגבלת 10MB)",
   len(_up_calls) == 1 and _up_calls[0][3].get("Content-Type") == "message/rfc822"
   and _up_calls[0][2] == _big and len([c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]) == 0,
   (len(_up_calls), _up_calls[0][3] if _up_calls else None))
n0 = len(calls); _up_calls.clear()
google_auth.gmail_send_raw(b"small")
ok("מייל קטן עדיין נשלח כ-JSON (הנתיב שאומת בשטח)", not _up_calls
   and len([c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]) == 1)
try:
    google_auth.gmail_send_raw(b"x" * (31 * 1024 * 1024)); ok("413 מעלה", False)
except Exception as e:
    ok("413 (גדול מדי) = תקלה כללית בעברית — עוצרת את האצווה, לא 500 העלאות ענק",
       mailer.is_fatal(e) and "גדול" in str(e), str(e))
# הגנה לפני השליחה: מייל שחורג מ-25MB (מגבלת Gmail) נעצר בתוכנה, בלי להעלות בכלל
_huge = os.path.join(dir_a, "huge.bin")
with open(_huge, "wb") as f:
    f.write(b"\0" * (20 * 1024 * 1024))     # 20MB → ~27MB אחרי base64
n0 = len(calls); _up_calls.clear()
try:
    email_utils.send_email("d@x.co", "גדול", "<p>x</p>", attachment_path=_huge); ok("מייל ענק מעלה", False)
except Exception as e:
    ok("קובץ 20MB → נעצר בתוכנה לפני שליחה (בלי בקשת רשת), תקלה כללית בעברית",
       mailer.is_fatal(e) and "גדול" in str(e) and not _up_calls
       and len([c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]) == 0, str(e))
ok("תקרת הקובץ המצורף במסך ≤ 18MB (20MB × base64 = 27MB > 25MB של Gmail)",
   getattr(email_utils, "MAX_ATTACHMENT_BYTES", 0) and email_utils.MAX_ATTACHMENT_BYTES <= 18 * 1024 * 1024
   and "MAX_ATTACHMENT_BYTES" in open("tabs/mails.py", encoding="utf-8").read())
os.remove(_huge)
google_auth._TRANSPORT = fake_transport

# (ג) "שלח שוב לנכשלים" לא דורס את הטיוטה שבשדות — גם כשמבטלים בחלון האישור
tab = mmod.MailsTab(None)
tab.refresh()
_me = sync.device_name() or ""
g11 = db.add_mail_campaign("נושא ישן", "גוף ישן", "כולם", "kupa@gmail.com", 2, device=_me)
db.update_mail_campaign(g11, 1, 1, "done", json.dumps([
    {"rec_id": None, "guid": "", "name": "ok@x.com", "email": "ok@x.com", "status": "sent", "error": ""},
    {"rec_id": None, "guid": "", "name": "f@x.com", "email": "f@x.com", "status": "failed", "error": "x"}],
    ensure_ascii=False))
tab._refresh_history()
idx11 = next(i for i, c in enumerate(tab._camps) if c["guid"] == g11)
tab.subject.setText("טיוטה חדשה"); tab.body.setPlainText("גוף הטיוטה")
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.No)
n_before = len(db.get_mail_campaigns())
tab._resend_failed(idx11)
ok("ביטול בחלון האישור של שליחה-חוזרת: הטיוטה בשדות נשארת (לא נדרסה)",
   tab.subject.text() == "טיוטה חדשה" and tab.body.toPlainText() == "גוף הטיוטה"
   and len(db.get_mail_campaigns()) == n_before and tab._worker is None, tab.subject.text())
mmod.QMessageBox.question = staticmethod(lambda *a, **k: mmod.QMessageBox.StandardButton.Yes)
tab._resend_failed(idx11)
c11 = db.get_mail_campaign(tab._active_guid) if tab._active_guid else None
ok("אישור: השליחה-החוזרת יוצאת עם הנושא והגוף *המקוריים*",
   c11 and c11["subject"] == "נושא ישן" and c11["body"] == "גוף ישן" and c11["total"] == 1, c11 and c11["subject"])
ok("…והטיוטה בשדות עדיין שלמה", tab.subject.text() == "טיוטה חדשה" and tab.body.toPlainText() == "גוף הטיוטה")
tab._on_finished([{"rec_id": None, "guid": "", "name": "f@x.com", "email": "f@x.com", "status": "sent", "error": ""}])
tab.deleteLater()
mmod.QMessageBox.question = _orig_q10

# (ד) התנתקות מגוגל: הניתוק המקומי מיידי, ביטול הטוקן בגוגל (רשת) ברקע — לא על ה-UI
google_auth.connect()
n0 = len(calls)
_tok = google_auth.disconnect(revoke=False)
ok("disconnect(revoke=False): מנתק מקומית בלי בקשת רשת ומחזיר את הטוקן לביטול-ברקע",
   not google_auth.is_connected() and len(calls) == n0 and _tok == "RT1", _tok)
google_auth.revoke(_tok)
ok("revoke(token) פונה לגוגל לביטול", calls[-1][1] == google_auth.REVOKE_URL and b"RT1" in (calls[-1][2] or b""))
_st_src = open("tabs/settings.py", encoding="utf-8").read()
_dis = _st_src[_st_src.index("def _google_disconnect"):]
_dis = _dis[:_dis.index("\n    def ")]
ok("הגדרות: 'התנתק' לא קורא לרשת על ה-UI (revoke=False + _BgWorker)",
   "disconnect(revoke=False)" in _dis and "_BgWorker" in _dis and "busy_cursor" not in _dis)
google_auth.connect()

print()
if fails:
    print(f"FAILED ({len(fails)}):"); [print("  -", f) for f in fails]
    sys.exit(1)
print("ALL MAIL TESTS PASSED")

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
ok("MIME: From=חשבון גוגל, To=נמען", b"From: kupa@gmail.com" in raw and b"To: dest@example.com" in raw)
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

# disconnect
use_machine(dir_a)
google_auth.disconnect()
ok("disconnect מנקה settings + revoke", not google_auth.is_connected()
   and any(c[1] == google_auth.REVOKE_URL for c in calls))

print()
if fails:
    print(f"FAILED ({len(fails)}):"); [print("  -", f) for f in fails]
    sys.exit(1)
print("ALL MAIL TESTS PASSED")

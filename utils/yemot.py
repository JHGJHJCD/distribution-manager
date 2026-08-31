# -*- coding: utf-8 -*-
"""לקוח ה-API החיצוני של ימות המשיח (call2all) — מערכת הצינתוקים.

מודול טהור (בלי Qt): בניית בקשות, נרמול טלפונים, פירוק תשובות, וחוקי
שעות-שליחה. פרטי הגישה (מספר מערכת + סיסמה) נשמרים ב-settings ומוזנים ע"י
המשתמש בלשונית ההגדרות — המודול רק קורא אותם.

התחבורה (HTTP) ניתנת להזרקה דרך ``_TRANSPORT`` כדי שהבדיקות ירוצו בלי רשת.
"""
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import database as db
from utils import timefmt

BASE_URL = "https://www.call2all.co.il/ym/api"
# Official twin endpoint (f2.freeivr.co.il/topic/55) — tried automatically when
# the main host fails at the network level.
ALT_URL = "https://private.call2all.co.il/ym/api"
TEMPLATE_DESCRIPTION = "מנהל חלוקה — צינתוקים"

# settings keys (synced between the computers, like the SMTP credentials)
SET_SYSTEM = "yemot_system"
SET_PASSWORD = "yemot_password"
SET_TEMPLATE = "yemot_template_id"
SET_CALLER_ID = "yemot_caller_id"
SET_TEST_PHONE = "yemot_test_phone"
# Which template already got the REPEAT campaign type (arrival-confirm keys).
SET_CONFIRM_CTX = "yemot_confirm_ctx"


class YemotError(Exception):
    """A non-OK answer from the Yemot server (or no connection).
    code -1 = network-level failure (no server answer at all)."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


# ─── Transport ───────────────────────────────────────────────────────────────

_TRANSPORT = None          # tests inject: callable(url, data_bytes|None) -> bytes
_SSL_FALLBACK = False      # switched on after the first SSLCertVerificationError


def _http(url: str, data: bytes | None = None) -> bytes:
    if _TRANSPORT is not None:
        return _TRANSPORT(url, data)
    global _SSL_FALLBACK
    req = urllib.request.Request(url, data=data,
                                 headers={"User-Agent": "ManhalHaluka"})
    last_err = None
    retried = False
    while True:
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read()
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            # NetFree machines may need the Windows cert store (truststore) —
            # any SSL trouble gets one retry with it injected (doesn't count
            # as the transient retry below).
            if not _SSL_FALLBACK and isinstance(reason, ssl.SSLError):
                _SSL_FALLBACK = True
                try:
                    import truststore
                    truststore.inject_into_ssl()
                    continue
                except ImportError:
                    pass
            last_err = reason if reason is not None else e
        except (TimeoutError, OSError) as e:
            last_err = e
        if not retried:          # one automatic retry for transient hiccups
            retried = True
            time.sleep(1.5)
            continue
        # Surface the real cause — "check the internet" alone hides whether it
        # was DNS, SSL, a timeout or a filter block (learned in the v2.82 E2E).
        detail = str(last_err) or type(last_err).__name__
        raise YemotError("אין חיבור לשרת ימות המשיח — בדוק את האינטרנט.\n"
                         f"פרטים טכניים: {detail}", code=-1) from (
            last_err if isinstance(last_err, BaseException) else None)


def _is_api_key(password: str) -> bool:
    """An API key (made in Yemot's 'חומת אש' screen) is long/lettered and is
    sent ALONE as the token; the classic short numeric password needs the
    system number prefixed (system:password)."""
    return bool(re.search(r"[A-Za-z]", password)) or len(password) >= 20


def _token() -> str:
    system = (db.get_setting(SET_SYSTEM) or "").strip()
    password = (db.get_setting(SET_PASSWORD) or "").strip()
    if not password:
        raise YemotError("חסרים פרטי גישה לימות המשיח — הזן אותם בהגדרות")
    if _is_api_key(password):
        return password
    if not system:
        raise YemotError("חסר מספר מערכת — הזן אותו בהגדרות")
    return f"{system}:{password}"


def is_configured() -> bool:
    password = (db.get_setting(SET_PASSWORD) or "").strip()
    if not password:
        return False
    return _is_api_key(password) or bool((db.get_setting(SET_SYSTEM) or "").strip())


def _call(command: str, params: dict | None = None, post: bool = False) -> dict:
    """One API request. Raises YemotError on any non-OK answer. A network-level
    failure on the main host is retried once against the official twin host."""
    query = {"token": _token()}
    query.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
    encoded = urllib.parse.urlencode(query)

    def _fetch(base):
        if post:
            return _http(f"{base}/{command}", encoded.encode("utf-8"))
        return _http(f"{base}/{command}?{encoded}")

    try:
        raw = _fetch(BASE_URL)
    except YemotError as e:
        if e.code != -1:
            raise
        raw = _fetch(ALT_URL)
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        body = raw[:200].decode("utf-8", errors="replace")
        # NetFree blocks answer with an HTML page, not JSON — surface that clearly.
        if "NetFree" in body or "<html" in body.lower():
            raise YemotError("החיבור נחסם בדרך (ייתכן ע\"י הסינון) — נסה שוב או פנה לנטפרי")
        raise YemotError("תשובה לא מובנת משרת ימות המשיח")
    if data.get("responseStatus") != "OK":
        raise YemotError(_hebrew_error(data), int(data.get("messageCode") or 0))
    return data


_ERROR_HE = {
    1: "מספר מערכת או סיסמה שגויים",
    100: "תבנית הקמפיין לא נמצאה — נסה 'בדוק חיבור' ליצירה מחדש",
    101: "מודול הקמפיינים לא מוגדר במערכת — פנה לימות המשיח",
    102: "אין אף מספר טלפון תקין לשליחה",
    103: "אין מספיק יחידות במערכת — יש לטעון יחידות בימות המשיח",
    104: "ימות המשיח חוסמים שליחה בשבת וחג",
    120: "מספר המזהה (Caller ID) אינו מורשה במערכת",
}


def _hebrew_error(data: dict) -> str:
    code = int(data.get("messageCode") or 0)
    if code in _ERROR_HE:
        return _ERROR_HE[code]
    msg = data.get("message") or "שגיאה לא ידועה"
    low = msg.lower()
    # covers "Username or password is incorrect" AND the login-token variant
    # "creating login token error(user name or password do not match)"
    if "password" in low and ("incorrect" in low or "do not match" in low):
        return _ERROR_HE[1]
    if "mfa" in low:
        return ("המערכת בימות דורשת אימות דו-שלבי לכניסה. הפתרון: היכנס לממשק "
                "הניהול של ימות ← \"חומת אש\" ← צור מפתח API, והדבק את המפתח "
                "בשדה הסיסמה בהגדרות התוכנה (במקום הסיסמה הרגילה).")
    return f"שגיאה משרת ימות המשיח: {msg}"


# ─── Phone normalization ─────────────────────────────────────────────────────

def normalize_phone(raw) -> str:
    """Israeli phone → digits only ('0501234567'), or '' when not a valid
    dialable number. Accepts spaces/dashes/dots/parens and a +972 prefix."""
    s = re.sub(r"[\s\-().]", "", str(raw or ""))
    if s.startswith("+972"):
        s = "0" + s[4:]
    elif s.startswith("972") and len(s) >= 11:
        s = "0" + s[3:]
    if not s.isdigit():
        return ""
    # Mobile 05X/07X = 10 digits; landline 0X = 9 digits.
    if len(s) == 10 and s[0] == "0" and s[1] in "57":
        return s
    if len(s) == 9 and s[0] == "0" and s[1] in "23489":
        return s
    return ""


def pick_phones(rec: dict) -> list:
    """The recipient's valid, deduped phone numbers in field order
    (phone1 first — the default number to ring)."""
    out = []
    for f in ("phone1", "phone2", "phone3"):
        p = normalize_phone(rec.get(f))
        if p and p not in out:
            out.append(p)
    return out


# ─── Legal sending hours ─────────────────────────────────────────────────────

def send_block_reason(now: datetime | None = None) -> str:
    """'' when sending is allowed now, else a Hebrew reason. The law forbids
    automated calls 21:00–08:00; Friday afternoon and Saturday are blocked for
    Shabbat (Yemot also blocks Shabbat/chag server-side — error 104 — but we
    stop earlier, with a clear message). Times are Israel clock."""
    if now is None:
        zone = timefmt._israel_zone()
        now = datetime.now(zone) if zone is not None else datetime.now()
    wd, hour = now.weekday(), now.hour        # Mon=0 … Fri=4, Sat=5, Sun=6
    if wd == 5:
        return "אי אפשר לשלוח בשבת"
    if wd == 4 and hour >= 12:
        return "אי אפשר לשלוח בערב שבת (מהצהריים)"
    if hour >= 21 or hour < 8:
        return "החוק אוסר שיחות אוטומטיות בין 21:00 ל-08:00"
    return ""


# ─── API commands ────────────────────────────────────────────────────────────

def check_connection() -> dict:
    """Validate the credentials (GetSession). Returns the raw session info —
    raises YemotError when the details are wrong / no connection."""
    return _call("GetSession")


def get_balance() -> float | None:
    """Units left in the account, when the server reports it (best effort)."""
    try:
        data = _call("GetSession")
    except YemotError:
        raise
    for key in ("units", "customerUnits", "money", "balance"):
        val = _dig(data, key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _dig(obj, key):
    """Find `key` anywhere in a nested dict/list answer (schema is loose)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _dig(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _dig(v, key)
            if found is not None:
                return found
    return None


def ensure_template() -> str:
    """The campaign template the app sends with. Created once via the API and
    remembered in settings; the recording is then attached to this template."""
    tid = (db.get_setting(SET_TEMPLATE) or "").strip()
    if not tid:
        data = _call("CreateTemplate", {"description": TEMPLATE_DESCRIPTION}, post=True)
        tid = str(_dig(data, "templateId") or "").strip()
        if not tid:
            raise YemotError("יצירת תבנית קמפיין נכשלה — לא התקבל מזהה")
        db.set_setting(SET_TEMPLATE, tid)
    _ensure_confirm_context(tid)
    return tid


def _ensure_confirm_context(template_id: str):
    """One-time per template: set the campaign type to REPEAT so key presses
    work during the message (Yemot's built-in keys: 1 = replay, 7 = confirm →
    the entry becomes entryStatus 'accepted' in the report). Non-fatal — a
    failure never blocks sending; retried on the next send."""
    if (db.get_setting(SET_CONFIRM_CTX) or "").strip() == str(template_id):
        return
    try:
        _call("UpdateTemplate", {"templateId": template_id,
                                 "yemotContext": "REPEAT"}, post=True)
        db.set_setting(SET_CONFIRM_CTX, str(template_id))
    except YemotError:
        pass


def upload_message_wav(file_path: str, template_id: str | None = None) -> dict:
    """Attach a recording file to the campaign template (converted to the
    telephony WAV format server-side). The campaign-file path uses the
    documented ``tpl:`` prefix; older servers may want ``ivr2:``, so a path
    error triggers one retry with that form."""
    template_id = template_id or ensure_template()
    with open(file_path, "rb") as f:
        content = f.read()
    try:
        return _upload_multipart(f"tpl:{template_id}", content)
    except YemotError as e:
        if e.code in (107, 109, 110):     # path not accepted — try the other form
            return _upload_multipart(f"ivr2:{template_id}.wav", content)
        raise


def _upload_multipart(path: str, content: bytes) -> dict:
    boundary = "----ManhalHaluka"
    fields = {"token": _token(), "path": path, "convertAudio": "1"}
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"message.wav\"\r\nContent-Type: application/octet-stream"
             f"\r\n\r\n").encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode()

    def _post(base):
        if _TRANSPORT is not None:
            return _TRANSPORT(f"{base}/UploadFile", body)
        req = urllib.request.Request(
            f"{base}/UploadFile", data=body,
            headers={"User-Agent": "ManhalHaluka",
                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()

    try:
        raw = _post(BASE_URL)
    except YemotError as e:
        if e.code != -1:
            raise
        raw = _post(ALT_URL)
    except (urllib.error.URLError, TimeoutError, OSError):
        raw = _post(ALT_URL)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if data.get("responseStatus") != "OK":
        raise YemotError(_hebrew_error(data), int(data.get("messageCode") or 0))
    return data


def run_campaign(phones: dict, template_id: str | None = None) -> dict:
    """Send the voice message to `phones` ({'0501234567': 'שם', ...}).
    Returns the server answer: campaignId, entriesCount, estimatedPrice,
    customerUnits…  Refuses an empty list locally."""
    numbers = {p: n for p, n in phones.items() if normalize_phone(p)}
    if not numbers:
        raise YemotError("אין אף מספר תקין לשליחה")
    template_id = template_id or ensure_template()
    payload = json.dumps({p: {"name": (n or "")[:60]} for p, n in numbers.items()},
                         ensure_ascii=False)
    params = {"templateId": template_id, "phones": payload}
    caller = (db.get_setting(SET_CALLER_ID) or "").strip()
    if caller:
        params["callerId"] = caller
    return _call("RunCampaign", params, post=True)


# ─── Scheduled campaigns (server-side — run even when this computer is off) ──

def set_template_entries(phones: dict, template_id: str) -> int:
    """Store `phones` ({'0501234567': 'שם', …}) as the template's distribution
    list. A scheduled campaign dials the STORED list (ScheduleCampaign has no
    inline phones param like RunCampaign), so this must run before scheduling.
    Returns how many numbers were stored."""
    numbers = {p: n for p, n in phones.items() if normalize_phone(p)}
    if not numbers:
        raise YemotError("אין אף מספר תקין לשליחה")
    _call("ClearTemplateEntries", {"templateId": template_id}, post=True)
    data = "\n".join(f"{p}\t{(n or '')[:60]}" for p, n in numbers.items())
    _call("UploadPhoneList", {"templateId": template_id, "data": data,
                              "delimiter": "TAB", "nameColumns": "1",
                              "updateType": "NEW"}, post=True)
    # A scheduled run takes the caller-id from the template (no per-run param).
    caller = (db.get_setting(SET_CALLER_ID) or "").strip()
    if caller:
        try:
            _call("UpdateTemplate", {"templateId": template_id,
                                     "callerId": caller}, post=True)
        except YemotError:
            pass                      # cosmetic — never blocks the scheduling
    return len(numbers)


def schedule_campaign(when: datetime, phones: dict,
                      template_id: str | None = None) -> dict:
    """Schedule the campaign on Yemot's server for `when` (Israel local time) —
    it dials at that moment even when this computer is completely off.
    Returns {'schedId', 'count'}."""
    template_id = template_id or ensure_template()
    count = set_template_entries(phones, template_id)
    data = _call("ScheduleCampaign",
                 {"templateId": template_id,
                  "time": when.strftime("%Y-%m-%d %H:%M")}, post=True)
    sched_id = str(_dig(data, "schedId") or _dig(data, "id") or "").strip()
    if not sched_id:
        # Server variants may not echo the id — find the newest pending one
        # for our template in the scheduled list.
        for c in reversed(get_scheduled_campaigns("PENDING")):
            if str(_dig(c, "templateId") or "") == str(template_id):
                sched_id = str(_dig(c, "schedId") or _dig(c, "id") or "").strip()
                break
    return {"schedId": sched_id, "count": count, "raw": data}


def get_scheduled_campaigns(sched_type: str = "PENDING") -> list:
    """The account's scheduled campaigns of one type
    (PENDING / SUCCESSFUL / FAILED)."""
    data = _call("GetScheduledCampaigns", {"type": sched_type})
    for v in data.values():
        if isinstance(v, list):
            return v
    return []


def find_scheduled(sched_id) -> tuple:
    """Locate a scheduled campaign by its id on the server →
    ('pending'|'successful'|'failed'|'missing', record|None)."""
    sid = str(sched_id or "").strip()
    if not sid:
        return "missing", None
    for typ, word in (("PENDING", "pending"), ("SUCCESSFUL", "successful"),
                      ("FAILED", "failed")):
        for c in get_scheduled_campaigns(typ):
            if str(_dig(c, "schedId") or _dig(c, "id") or "") == sid:
                return word, c
    return "missing", None


def delete_scheduled_campaign(sched_id) -> None:
    """Cancel a pending scheduled campaign. Raises a clear Hebrew error when it
    already ran (106) or is not on the server (105)."""
    try:
        _call("DeleteScheduledCampaign", {"schedId": str(sched_id)}, post=True)
    except YemotError as e:
        if e.code == 106:
            raise YemotError("הקמפיין המתוזמן כבר בוצע — אי אפשר לבטל אותו", 106)
        if e.code == 105:
            raise YemotError("התזמון לא נמצא בשרת ימות (ייתכן שכבר בוטל)", 105)
        raise


# entryStatus → coarse bucket for the live counters / results screen.
_DELIVERED = {"accepted", "done", "up", "bridged", "amd"}
_FAILED = {"failed", "no_answer", "busy", "canceled", "error", "blocked",
           "remove_request"}


def get_campaign_status(campaign_id: str) -> dict:
    """Live campaign status → {'finished': bool, 'total': n, 'delivered': n,
    'confirmed': n, 'failed': n, 'pending': n,
    'entries': [{'phone','name','status','ok','confirmed'}…]}.
    'confirmed' = pressed the confirm key (7) during the message —
    entryStatus 'accepted' ("אישרו מסירה"); always a subset of delivered."""
    data = _call("GetCampaignStatus", {"campaignId": campaign_id, "entries": "all"})
    camp = data.get("campaign") or data
    entries = []
    for e in camp.get("entries") or []:
        status = str(e.get("entryStatus") or e.get("status") or "").lower()
        entries.append({
            "phone": str(e.get("phone") or ""),
            "name": e.get("name") or "",
            "status": status,
            "ok": status in _DELIVERED,
            "confirmed": status == "accepted",
            "failed": status in _FAILED,
        })
    delivered = sum(1 for e in entries if e["ok"])
    confirmed = sum(1 for e in entries if e["confirmed"])
    failed = sum(1 for e in entries if e["failed"])
    total = int(camp.get("totalEntries") or len(entries) or 0)
    pending = max(0, total - delivered - failed)
    # Finished = nothing pending/active any more (safer than matching the exact
    # campaignStatus string, which is not fully documented).
    running = int(camp.get("pendingEntries") or 0) + int(camp.get("activeEntries") or 0)
    status_word = str(camp.get("campaignStatus") or "").upper()
    finished = running == 0 and status_word not in ("RUNNING", "ACTIVE", "")
    if running == 0 and pending == 0 and entries:
        finished = True
    return {"finished": finished, "total": total, "delivered": delivered,
            "confirmed": confirmed, "failed": failed, "pending": pending,
            "entries": entries, "campaign_status": status_word}


def confirmed_phones(dist_date: str) -> set:
    """Phones that pressed the confirm key (entryStatus 'accepted') in any
    campaign sent for this distribution date — parsed from the reports stored
    in tzintuk_campaigns.report_json (synced, so both computers see them)."""
    out = set()
    if not dist_date:
        return out
    for camp in db.get_tzintuk_campaigns():
        if (camp.get("dist_date") or "") != dist_date:
            continue
        try:
            entries = json.loads(camp.get("report_json") or "[]")
        except ValueError:
            continue
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            if e.get("confirmed") or str(e.get("status") or "").lower() == "accepted":
                p = normalize_phone(e.get("phone"))
                if p:
                    out.add(p)
    return out


def run_test(phone: str) -> dict:
    """Ring one number (the operator's own) so they can hear the recording."""
    p = normalize_phone(phone)
    if not p:
        raise YemotError("מספר הבדיקה אינו תקין")
    return run_campaign({p: "בדיקה"})

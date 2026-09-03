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
from datetime import datetime, timezone

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
# The number recipients see when the line dials them. The line's main DID is an
# 079 number that kosher phones block, so a caller-back is impossible. Default to
# the line's 04 landline DID (048691834 — verified approved for outgoing on this
# line), overridable in Settings. A public phone number, not a secret.
DEFAULT_CALLER_ID = "048691834"
# Arrival survey (v3.01): the recipient calls the line back, dials SURVEY_EXT
# from the main menu and answers ONE key — 1 coming / 2 not coming / 3 unsure.
# The old "press 7 during the campaign message" path (yemotContext=REPEAT) is
# gone: this line's server rejects REPEAT (verified live 2/9/2026), and a
# classic tzintuk can't be answered anyway. Labels + the question text are
# operator-editable settings (synced between the computers).
SURVEY_EXT = "77"
SURVEY_Q = "050"                        # the key-press question inside the extension
SET_ANSWER_LABELS = "tzintuk_answer_labels"   # JSON {"1": "מגיע", "2": …, "3": …}
SET_SURVEY_PROMPT = "tzintuk_survey_prompt"   # the question played on the extension
ANSWER_KEYS = ("1", "2", "3")
DEFAULT_ANSWER_LABELS = {"1": "מגיע", "2": "לא מגיע", "3": "לא יודע"}
DEFAULT_SURVEY_PROMPT = ("אם אתם מגיעים לחלוקה הקישו 1. אם אינכם מגיעים הקישו 2. "
                         "אם עדיין לא יודעים הקישו 3.")
# Classic-tzintuk (ring-only) support: a second template configured for a short
# unanswered ring; callers hear the message only when they dial back.
SET_CLASSIC_TEMPLATE = "yemot_classic_template_id"
SET_CLASSIC_READY = "yemot_classic_ready"
CLASSIC_DESCRIPTION = "מנהל חלוקה — צינתוק קלאסי"
CLASSIC_RING_SECONDS = 8          # ~2 rings, then give up (no answer = no cost)
TZINTUK_RING_SECONDS = 16         # RunTzintuk ring length — unanswerable anyway


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


def normalize_phone_loose(raw) -> str:
    """normalize_phone for text that came out of Excel/pasting: a cell stored
    as a NUMBER loses its leading zero (501234567) or gains '.0'
    (501234567.0) — both are restored here. Only for free-text lists, not
    for the recipients' cards."""
    p = normalize_phone(raw)
    if p:
        return p
    s = re.sub(r"\.0+$", "", str(raw or "").strip())
    s = re.sub(r"[\s\-().]", "", s)
    if s.isdigit() and s[:1] != "0" and len(s) in (8, 9):
        return normalize_phone("0" + s)
    return normalize_phone(s)


_NUMERIC_TOK = re.compile(r"[+\d][\d\-().]*")
_MAX_PHONE_TOKENS = 4      # "+972 52 111 2222" — the longest sensible split


def find_phones(line: str) -> tuple:
    """Pull every phone number out of a free-text line ('050 123 4567 כהן',
    '+972 52-111-2222, 03 9876543', '0501234567 0521111222 כהן')
    → (phones, rest_of_line, bad_tokens).

    A number may be split by spaces into up to 4 pieces; the SHORTEST run of
    numeric tokens that forms a valid phone wins, so two numbers written
    side by side stay two numbers. Leftover numeric tokens of 4+ digits are
    reported as bad (they look like a phone but are not); shorter ones
    ('דירה 5') are just part of the name."""
    phones, bad, words, short_nums = [], [], [], []
    toks = [t.strip(",;") for t in line.split()]
    toks = [t for t in toks if t]
    i = 0
    while i < len(toks):
        tok = toks[i]
        if not _NUMERIC_TOK.fullmatch(tok):
            words.append(tok)
            i += 1
            continue
        matched = 0
        for k in range(1, _MAX_PHONE_TOKENS + 1):
            if i + k > len(toks) or not _NUMERIC_TOK.fullmatch(toks[i + k - 1]):
                break
            p = normalize_phone_loose("".join(toks[i:i + k]))
            if p:
                phones.append(p)
                matched = k
                break
        if matched:
            i += matched
            continue
        if sum(ch.isdigit() for ch in tok) >= 4:
            bad.append(tok)
        else:
            words.append(tok)
            short_nums.append(tok)
        i += 1
    if not phones and short_nums:
        # A line with NO phone at all: its numeric bits are the reason it was
        # skipped — report them instead of hiding them inside a "name".
        bad.extend(short_nums)
        words = [w for w in words if w not in short_nums]
    return phones, " ".join(words), bad


def pick_phones(rec: dict) -> list:
    """The recipient's valid, deduped phone numbers in field order
    (phone1 first — the default number to ring)."""
    out = []
    for f in ("phone1", "phone2", "phone3"):
        p = normalize_phone(rec.get(f))
        if p and p not in out:
            out.append(p)
    return out


def allocate_phones(phone_lists: list) -> list:
    """Cross-row dedupe for the all-numbers send (#gaira): every recipient gets
    ALL their numbers, but a number shared by two list rows rings only for the
    first row. Input: [[phones of row 0], [phones of row 1], …] → same shape,
    with already-claimed numbers removed from later rows."""
    seen, out = set(), []
    for phones in phone_lists:
        mine = [p for p in (phones or []) if p not in seen]
        seen.update(mine)
        out.append(mine)
    return out


# ─── Sending hours ───────────────────────────────────────────────────────────

def send_block_reason(now: datetime | None = None) -> str:
    """Always '' — the operator asked for every hour to be open (#n6wte,
    user decision 31/08/2026): no night/Shabbat block and no warning. Yemot's
    own server still refuses Shabbat/chag (error 104), which stays the only
    guard. The function is kept so existing call sites need no change."""
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
    return tid


def ensure_classic_template() -> str:
    """The second template used for a classic tzintuk (short unanswered ring —
    the recipient sees a missed call, dials back, and hears the message).
    Adopts an existing spare template when one exists (an orphan created by the
    other computer before the settings synced), otherwise creates one, and
    configures it once for the short ring."""
    tid = (db.get_setting(SET_CLASSIC_TEMPLATE) or "").strip()
    if not tid:
        main = (db.get_setting(SET_TEMPLATE) or "").strip()
        data = _call("GetTemplates")
        for t in (data.get("templates") or []):
            desc = str(t.get("description") or "")
            cand = str(t.get("templateId") or "").strip()
            if not cand or cand == main:
                continue
            if desc in (CLASSIC_DESCRIPTION, TEMPLATE_DESCRIPTION):
                tid = cand
                break
        if not tid:
            created = _call("CreateTemplate",
                            {"description": CLASSIC_DESCRIPTION}, post=True)
            tid = str(_dig(created, "templateId") or "").strip()
            if not tid:
                raise YemotError("יצירת תבנית לצינתוק קלאסי נכשלה — לא התקבל מזהה")
        db.set_setting(SET_CLASSIC_TEMPLATE, tid)
    if (db.get_setting(SET_CLASSIC_READY) or "").strip() != tid:
        _call("UpdateTemplate",
              {"templateId": tid, "description": CLASSIC_DESCRIPTION,
               "originateTimeout": str(CLASSIC_RING_SECONDS),
               "maxDialAttempts": "1"}, post=True)
        db.set_setting(SET_CLASSIC_READY, tid)
    return tid


def add_template_entry(phone: str, name: str = "",
                       template_id: str | None = None) -> None:
    """Add ONE number to the template's stored list without clearing it —
    so a caller-back hears the campaign message (campaign_message_to_play).
    Used by the test send; a real send stores the whole list instead."""
    p = normalize_phone(phone)
    if not p:
        raise YemotError("המספר אינו תקין")
    template_id = template_id or ensure_template()
    _call("UploadPhoneList", {"templateId": template_id,
                              "data": f"{p}\t{(name or '')[:60]}",
                              "delimiter": "TAB", "nameColumns": "1",
                              "updateType": "UPDATE"}, post=True)


def template_position(template_id: str) -> int:
    """1-based position of `template_id` in the line's template list — the
    number the entry menu's campaign_message_to_play line refers to (verified
    statistically on the live line 2/9/2026: 17 = 1430692). 0 = not found."""
    data = _call("GetTemplates")
    for i, t in enumerate(data.get("templates") or [], start=1):
        if str(t.get("templateId") or "").strip() == str(template_id):
            return i
    return 0


def reset_callback_memory(template_id: str | None = None) -> str:
    """Forget who already heard this template's message when calling the line
    back — so after EVERY send each recipient hears the current message once
    (3/9/2026: a caller who heard last week's message stayed silent for the
    whole `-1-6d` window). The line root keeps that memory per campaign in
    ``CampaignMessageAmountPlay-Template-<N>.ini`` (needs
    ``campaign_message_to_play_file_by_template=yes`` in the root ext.ini);
    deleting only OUR file never touches the manager's own campaign entries.
    Returns the deleted path ("" when the template is not in the list)."""
    template_id = template_id or ensure_template()
    pos = template_position(template_id)
    if not pos:
        return ""
    what = f"ivr2:/CampaignMessageAmountPlay-Template-{pos}.ini"
    try:
        _call("FileAction", {"what": what, "action": "delete"}, post=True)
    except YemotError as e:
        if e.code == -1:
            raise
        # a missing file (nobody called back yet) is not a failure
    return what


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


def _upload_multipart(path: str, content: bytes, convert: str = "1") -> dict:
    boundary = "----ManhalHaluka"
    fields = {"token": _token(), "path": path, "convertAudio": convert}
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


def _caller_id() -> str:
    """The outgoing caller-id for every dial path — the operator's setting, or
    the 04 default when it is empty (so a caller-back is never blocked on a
    kosher phone). Both computers share the synced setting."""
    return (db.get_setting(SET_CALLER_ID) or DEFAULT_CALLER_ID).strip()


def run_tzintuk(phones_list: list, timeout: int | None = None) -> dict:
    """A TRUE tzintuk via the dedicated RunTzintuk API — the phone rings and
    the call is never connected, so answering is impossible (the user's
    requirement for 'רק צינתוק'). sayInfoOnAnswer is deliberately NOT sent —
    passing it true is what would make the call answerable. ~0.1 unit per
    number. Raises YemotError when the line has no tzintuk service — the
    caller falls back to the short-ring campaign."""
    if not phones_list:
        raise YemotError("אין אף מספר תקין לשליחה")
    params = {"phones": ",".join(phones_list),
              "TzintukTimeOut": str(timeout or TZINTUK_RING_SECONDS),
              "callerId": _caller_id()}
    return _call("RunTzintuk", params, post=True)


def run_campaign(phones: dict, template_id: str | None = None,
                 store_list: bool = False, classic: bool = False) -> dict:
    """Send the voice message to `phones` ({'0501234567': 'שם', ...}).
    Returns the server answer: campaignId, entriesCount, estimatedPrice,
    customerUnits…  Refuses an empty list locally.

    store_list=True (#z4xy9): before dialing, also store the numbers as the
    template's distribution list. The line's entry menu plays the campaign
    message to callers whose number is ACTIVE in that list
    (campaign_message_to_play) — so someone who missed the call can dial the
    line and hear the message. Best-effort: a storing failure never blocks
    the actual send.

    classic=True: a classic tzintuk — a ring that CANNOT be answered. First
    choice is the dedicated RunTzintuk API (the server never connects the
    call, ~0.1 unit per number); if the server refuses it (not every line
    has the tzintuk service enabled) we fall back to the old short-ring
    campaign from the second template. Either way the list is stored on the
    MAIN template so calling back plays the message."""
    numbers = {p: n for p, n in phones.items() if normalize_phone(p)}
    if not numbers:
        raise YemotError("אין אף מספר תקין לשליחה")
    main_id = template_id or ensure_template()
    dial_id = main_id
    if store_list or classic:
        try:
            set_template_entries(numbers, main_id)
        except YemotError:
            pass
        try:
            reset_callback_memory(main_id)   # everyone hears the NEW message once
        except YemotError:
            pass
    fallback = False
    if classic:
        try:
            return run_tzintuk(list(numbers))
        except YemotError as e:
            # Fall back to the short-ring campaign ONLY when the server itself
            # refused the command (no tzintuk service on this line). A network
            # failure (-1) may mean the server already dialed — ringing everyone
            # again would be worse; no units (103) / Shabbat (104) would fail
            # the fallback too. Those propagate to the operator instead.
            if e.code in (-1, 103, 104):
                raise
            fallback = True
        dial_id = ensure_classic_template()
        content = _download_template_message(main_id)
        try:
            _upload_multipart(f"tpl:{dial_id}", content, convert="0")
        except YemotError as e:
            if e.code in (107, 109, 110):   # same path fallback as the upload
                _upload_multipart(f"ivr2:{dial_id}.wav", content, convert="0")
            else:
                raise
    payload = json.dumps({p: {"name": (n or "")[:60]} for p, n in numbers.items()},
                         ensure_ascii=False)
    params = {"templateId": dial_id, "phones": payload,
              "callerId": _caller_id()}
    res = _call("RunCampaign", params, post=True)
    if fallback and isinstance(res, dict):
        res["classic_fallback"] = True   # the UI tells the operator it is answerable
    return res


# ─── Classic-tzintuk callback tracking (v2.96) ───────────────────────────────
# Yemot has NO call-history API (probed 1/9/2026: GetCallHistory/GetCalls/
# HistoryFile all unknown commands) — GetIncomingCalls returns only the calls
# LIVE right now. So "who called back" can only be caught while the app polls
# during a tracking window after the send; there is nothing to fetch later.

CLASSIC_TRACK_SECONDS = 30 * 60      # default watch window after a classic send


def get_incoming_calls() -> list:
    """The calls connected to the line RIGHT NOW:
    [{'phone', 'did', 'duration', 'path'}] (phone normalized, '' when hidden)."""
    data = _call("GetIncomingCalls")
    out = []
    for c in data.get("calls") or []:
        if not isinstance(c, dict):
            continue
        out.append({
            "phone": normalize_phone(c.get("callerIdNum") or c.get("callerId")
                                     or c.get("phone")),
            "did": str(c.get("did") or ""),
            "duration": float(c.get("duration") or 0),
            "path": str(c.get("path") or c.get("folder") or ""),
        })
    return out


class CallbackTracker:
    """Pure accumulator (no Qt/HTTP): feed it get_incoming_calls() snapshots
    and it remembers, per target number, whether the person called the line
    back after the classic tzintuk, how long the call lasted, and whether they
    reached the survey extension. The survey ANSWER itself (1/2/3) is not
    known from the live call — merge_survey_answers() adds it from the
    extension's data file."""

    def __init__(self, targets: dict):
        # {'0501234567': 'שם', …} — the numbers the classic tzintuk rang.
        self.targets = {p: (n or "") for p, n in (targets or {}).items() if p}
        self.state = {}    # phone → {'returned_at', 'duration', 'confirmed'}

    @staticmethod
    def _is_confirm_path(path: str) -> bool:
        p = (path or "").strip("/")
        return p == SURVEY_EXT or p.startswith(SURVEY_EXT + "/")

    def seed(self, entries: list):
        """Restore previous results (resume after the app was closed
        mid-window) from a stored report_json entries list."""
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            p = normalize_phone(e.get("phone"))
            status = str(e.get("status") or "").lower()
            if p in self.targets and (e.get("ok") or e.get("survey_reached")
                                      or e.get("confirmed")
                                      or status in ("callback", "accepted")):
                self.state[p] = {
                    "returned_at": e.get("returned_at") or "",
                    "duration": float(e.get("duration") or 0),
                    # 'confirmed' here = reached the survey extension (legacy
                    # reports: pressed 7 / 'accepted')
                    "confirmed": bool(e.get("survey_reached") or e.get("confirmed")
                                      or status == "accepted"),
                }

    def update(self, live_calls: list, now_iso: str = "") -> bool:
        """One live snapshot in → True when something MEANINGFUL changed
        (a new caller-back, or a first key-7 confirmation)."""
        changed = False
        for c in live_calls or []:
            p = (c or {}).get("phone") or ""
            if p not in self.targets:
                continue
            s = self.state.get(p)
            if s is None:
                s = self.state[p] = {"returned_at": now_iso, "duration": 0.0,
                                     "confirmed": False}
                changed = True
            dur = float(c.get("duration") or 0)
            if dur > s["duration"]:
                s["duration"] = dur
            if self._is_confirm_path(c.get("path")) and not s["confirmed"]:
                s["confirmed"] = True
                changed = True
        return changed

    def counts(self) -> tuple:
        returned = len(self.state)
        confirmed = sum(1 for s in self.state.values() if s["confirmed"])
        return returned, confirmed

    def entries(self) -> list:
        """report_json-shaped rows — same keys the regular campaign report
        uses, so history / Excel export / answers_for_date all work as-is.
        'callback' = returned and heard ('survey_reached' = also entered the
        survey extension — the answer itself comes from
        merge_survey_answers); 'no_callback' has ok=failed=False so
        answer_stats ignores it."""
        out = []
        for p, name in self.targets.items():
            s = self.state.get(p)
            out.append({"phone": p, "name": name,
                        "status": "callback" if s else "no_callback",
                        "ok": bool(s), "confirmed": False,
                        "survey_reached": bool(s and s["confirmed"]),
                        "failed": False,
                        "duration": round(s["duration"], 1) if s else 0,
                        "returned_at": (s or {}).get("returned_at") or ""})
        return out


# ─── Publishing the message on the line itself ───────────────────────────────

MESSAGES_EXT = "1"          # שלוחת ההודעות המרכזית בקו (הכרעת המשתמש, #kx6wd)


def _download(path: str) -> bytes:
    """Raw DownloadFile of any line path (``tpl:<id>`` / ``ivr2:/…``) — the
    answer is the file's bytes; a JSON body (starts with ``{``) means the
    server answered with an error/empty instead of a file."""
    query = urllib.parse.urlencode({"token": _token(), "path": path})
    try:
        return _http(f"{BASE_URL}/DownloadFile?{query}")
    except YemotError as e:
        if e.code != -1:
            raise
        return _http(f"{ALT_URL}/DownloadFile?{query}")


def _download_template_message(template_id: str) -> bytes:
    """The template's current recording, as bytes (telephony WAV)."""
    content = _download(f"tpl:{template_id}")
    if not content or content[:1] == b"{":
        raise YemotError("להודעת הצינתוק אין הקלטה בשרת — העלה קודם הקלטה")
    return content


def publish_to_extension(ext: str = MESSAGES_EXT,
                         template_id: str | None = None) -> str:
    """Copy the campaign's recording into the line's central messages
    extension as an ADDITIONAL file (#kx6wd) — server-side copy, so it works
    from either computer: DownloadFile tpl:<id> → next free number in the
    extension (GetIVR2Dir) → UploadFile ivr2:/<ext>/<n>.wav.
    Returns the uploaded file name."""
    template_id = template_id or ensure_template()
    content = _download_template_message(template_id)
    listing = _call("GetIVR2Dir", {"path": f"ivr2:/{ext}"})
    highest = 0
    for f in _dig(listing, "files") or []:
        m = re.match(r"^(\d+)\.", str(f.get("name") or ""))
        if m:
            highest = max(highest, int(m.group(1)))
    name = f"{highest + 1:03d}.wav"
    # Already in telephony WAV format (it came from the template) — no convert.
    _upload_multipart(f"ivr2:/{ext}/{name}", content, convert="0")
    return name


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
    try:
        _call("UpdateTemplate", {"templateId": template_id,
                                 "callerId": _caller_id()}, post=True)
    except YemotError:
        pass                          # cosmetic — never blocks the scheduling
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
        raw_phone = str(e.get("phone") or "")
        entries.append({
            # normalized so the results match the rows we dialed even when the
            # server echoes the number as 972…/+972…
            "phone": normalize_phone(raw_phone) or raw_phone,
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


# ─── Arrival survey (v3.01) — the answers live on extension 77 ────────────────
# The extension is a Yemot "recording_and_entering_data" module with ONE key
# question (file 050). Every completed entry is appended to ApprovalAll.ymgr in
# the extension folder — one line per call, '%'-separated 'key#value' pairs
# (verified live on this line, 2/9/2026):
#   Status#OK%Folder#77%DID#…%Phone#0501234567%Date#02/09/2026%Time#19:40:12%…%P050#1
# Times are Israel local time; the app keeps everything else in UTC.

_YMGR_TS = "%d/%m/%Y %H:%M:%S"


def answer_labels() -> dict:
    """{'1': 'מגיע', '2': 'לא מגיע', '3': 'לא יודע'} — operator overrides from
    the synced setting merged over the defaults (blank override = default)."""
    out = dict(DEFAULT_ANSWER_LABELS)
    try:
        data = json.loads(db.get_setting(SET_ANSWER_LABELS) or "{}")
    except ValueError:
        data = {}
    if isinstance(data, dict):
        for k in ANSWER_KEYS:
            v = str(data.get(k) or "").strip()
            if v:
                out[k] = v
    return out


def answer_label(digit) -> str:
    return answer_labels().get(str(digit or ""), "")


def survey_prompt_text() -> str:
    return (db.get_setting(SET_SURVEY_PROMPT) or "").strip() or DEFAULT_SURVEY_PROMPT


def upload_survey_prompt(text: str | None = None) -> str:
    """Write the question text the line reads out on the survey extension
    (file 050.tts — Yemot's TTS prompt). Returns the server path written."""
    text = (survey_prompt_text() if text is None else str(text)).strip()
    if not text:
        raise YemotError("טקסט השאלה ריק")
    what = f"ivr2:/{SURVEY_EXT}/{SURVEY_Q}.tts"
    try:
        _call("UploadTextFile", {"what": what, "contents": text}, post=True)
    except YemotError as e:
        if e.code == -1:
            raise
        _upload_multipart(what, text.encode("utf-8"), convert="0")
    return what


def _ymgr_kv(line: str) -> dict:
    """'Status#OK%Folder#77%Phone#05…%P050#1' → {'Status': 'OK', …}."""
    out = {}
    for part in line.split("%"):
        if "#" in part:
            k, v = part.split("#", 1)
            out[k.strip()] = v.strip()
    return out


def parse_approval_rows(text: str) -> list:
    """ApprovalAll.ymgr text → [{'phone', 'at' (aware UTC datetime), 'answer'}]
    in file order. Lines without a phone / answer / parsable time are skipped."""
    zone = timefmt._israel_zone()
    rows = []
    for raw in (text or "").splitlines():
        kv = _ymgr_kv(raw.strip())
        phone = normalize_phone(kv.get("Phone"))
        answer = (kv.get("P" + SURVEY_Q) or "").strip()
        if not phone or not answer:
            continue
        try:
            local = datetime.strptime(f"{kv.get('Date', '')} {kv.get('Time', '')}", _YMGR_TS)
        except ValueError:
            continue
        at = local.replace(tzinfo=zone) if zone is not None else local.astimezone()
        rows.append({"phone": phone, "at": at.astimezone(timezone.utc), "answer": answer})
    return rows


def fetch_survey_rows() -> list:
    """Download + parse the survey data file. No file yet (the server answers
    JSON instead of bytes, or nothing) → []."""
    raw = _download(f"ivr2:/{SURVEY_EXT}/ApprovalAll.ymgr")
    if not raw or raw[:1] == b"{":
        return []
    return parse_approval_rows(raw.decode("utf-8", errors="replace"))


def _parse_since(since_iso):
    if not since_iso:
        return None
    try:
        dt = datetime.fromisoformat(since_iso)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def merge_survey_answers(entries: list, rows: list, since_iso: str = "") -> tuple:
    """Stamp each report entry with the person's LATEST survey answer given
    after `since_iso` (the campaign's send time — last week's answers must not
    leak into this week): entry['answer'] = '1'/'2'/'3', or '' = the survey was
    checked and the person did not answer ("לא הגיב"); entry['answer_at'] =
    UTC iso. Returns (entries, changed)."""
    since = _parse_since(since_iso)
    latest = {}
    for r in rows or []:
        if since is not None and r["at"] < since:
            continue
        cur = latest.get(r["phone"])
        if cur is None or r["at"] >= cur[0]:
            latest[r["phone"]] = (r["at"], r["answer"])
    changed = False
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        hit = latest.get(normalize_phone(e.get("phone")))
        answer = hit[1] if hit else ""
        at = hit[0].isoformat() if hit else ""
        if "answer" not in e or e.get("answer") != answer or (e.get("answer_at") or "") != at:
            changed = True
        e["answer"] = answer
        e["answer_at"] = at
    return entries, changed


def survey_checked(entries) -> bool:
    """True once merge_survey_answers ran on these entries (the 'answer' key
    exists) — only then does 'no answer' mean 'did not respond'."""
    return any(isinstance(e, dict) and "answer" in e for e in entries or [])


def answer_counts(entries) -> dict:
    """{'1': n, '2': n, '3': n, '': n} — '' = checked, did not answer."""
    out = {k: 0 for k in ANSWER_KEYS}
    out[""] = 0
    for e in entries or []:
        if not isinstance(e, dict) or "answer" not in e:
            continue
        a = str(e.get("answer") or "")
        if a in out:
            out[a] += 1
    return out


def _report_entries(camp: dict) -> list:
    try:
        entries = json.loads(camp.get("report_json") or "[]")
    except ValueError:
        return []
    return [e for e in entries or [] if isinstance(e, dict)]


def answers_for_date(dist_date: str) -> dict:
    """{phone: '1'/'2'/'3'} for the distribution date, from the synced campaign
    reports — the newest campaign's answer wins when a number was rung twice."""
    out = {}
    if not dist_date:
        return out
    camps = [c for c in db.get_tzintuk_campaigns()
             if (c.get("dist_date") or "") == dist_date]
    for camp in reversed(camps):          # get_tzintuk_campaigns is newest-first
        for e in _report_entries(camp):
            p = normalize_phone(e.get("phone"))
            a = str(e.get("answer") or "")
            if p and a:
                out[p] = a
    return out


def confirmed_phones(dist_date: str) -> set:
    """Phones that said "coming" (survey answer 1) in any campaign of this
    distribution date — plus the legacy key-7 'accepted' status of old reports."""
    out = set()
    if not dist_date:
        return out
    for camp in db.get_tzintuk_campaigns():
        if (camp.get("dist_date") or "") != dist_date:
            continue
        for e in _report_entries(camp):
            if (str(e.get("answer") or "") == "1" or e.get("confirmed")
                    or str(e.get("status") or "").lower() == "accepted"):
                p = normalize_phone(e.get("phone"))
                if p:
                    out.add(p)
    return out


# ─── Smart-timing statistics (#y7jr0, stage 1) ───────────────────────────────

MIN_SMART_HISTORY = 10   # attempts needed before a personal best hour is shown


def answer_stats() -> dict:
    """Per-phone answer history, built from the campaign reports already stored
    (and synced) in tzintuk_campaigns — nothing new is recorded:
    {phone: {"attempts": n, "answered": n, "by_hour": {hour: [answered, tries]},
             "best_hour": int|None}}.
    The hour is the campaign's send hour on the Israel clock (the reports hold
    no per-entry time). best_hour appears only after MIN_SMART_HISTORY
    attempts — the hour with the highest answer rate among hours tried at
    least twice. Stage 2 (a future version) will use it to auto-split the
    send by personal hours."""
    stats = {}
    for camp in db.get_tzintuk_campaigns():
        if camp.get("status") != "done":
            continue
        try:
            entries = json.loads(camp.get("report_json") or "[]")
        except ValueError:
            continue
        when = timefmt.to_israel(camp.get("sent_at") or "")
        if when is None or not entries:
            continue
        hour = when.hour
        for e in entries:
            if not isinstance(e, dict):
                continue
            status = str(e.get("status") or "").lower()
            answered = bool(e.get("ok")) or status in _DELIVERED
            failed = bool(e.get("failed")) or status in _FAILED
            if not answered and not failed:
                continue               # pending/unknown — not an attempt
            p = normalize_phone(e.get("phone"))
            if not p:
                continue
            s = stats.setdefault(p, {"attempts": 0, "answered": 0,
                                     "by_hour": {}, "best_hour": None})
            s["attempts"] += 1
            s["answered"] += 1 if answered else 0
            bucket = s["by_hour"].setdefault(hour, [0, 0])
            bucket[1] += 1
            bucket[0] += 1 if answered else 0
    for s in stats.values():
        if s["attempts"] < MIN_SMART_HISTORY:
            continue
        candidates = [(a / t, t, h) for h, (a, t) in s["by_hour"].items() if t >= 2]
        if candidates:
            s["best_hour"] = max(candidates)[2]
    return stats


def run_test(phone: str) -> dict:
    """Ring one number (the operator's own) so they can hear the recording.
    The number is also added to the template's stored list (without clearing
    it) so calling the line back plays the message — the field test of 1/9
    found a callback after a test heard nothing because tests never stored
    the number."""
    p = normalize_phone(phone)
    if not p:
        raise YemotError("מספר הבדיקה אינו תקין")
    try:
        add_template_entry(p, "בדיקה")
        reset_callback_memory()   # the tester hears the message on callback
    except YemotError:
        pass                      # best-effort — never blocks the test ring
    return run_campaign({p: "בדיקה"})

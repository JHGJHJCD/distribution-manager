# -*- coding: utf-8 -*-
"""לקוח ה-API החיצוני של ימות המשיח (call2all) — מערכת הצינתוקים.

מודול טהור (בלי Qt): בניית בקשות, נרמול טלפונים, פירוק תשובות, וחוקי
שעות-שליחה. פרטי הגישה (מספר מערכת + סיסמה) נשמרים ב-settings ומוזנים ע"י
המשתמש בלשונית ההגדרות — המודול רק קורא אותם.

התחבורה (HTTP) ניתנת להזרקה דרך ``_TRANSPORT`` כדי שהבדיקות ירוצו בלי רשת.
"""
import json
import os
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
# Smart per-hour scheduling (#y7jr0 stage 2): one dedicated template per hour so
# each hour's list never overwrites another's. Synced JSON {str(hour): id}.
SET_HOUR_TEMPLATES = "yemot_hour_templates"
HOUR_TEMPLATE_DESC = "מנהל חלוקה — צינתוק חכם שעה {:02d}"
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
# v3.15 — commands that DIAL (or arm a dial) are sent exactly ONCE: no automatic
# retry and no twin-host fallback. A lost answer (timeout after the server
# already accepted the request) used to be retried up to 4 times (main ×2,
# private ×2) — every family rung again for each repeat. Reads/uploads stay
# idempotent and keep the retries.
_DIAL_COMMANDS = frozenset({"RunCampaign", "RunTzintuk", "ScheduleCampaign"})
_DIAL_LOST_MSG = ("לא התקבלה תשובה משרת ימות המשיח על פקודת השליחה.\n"
                  "ייתכן שהשליחה כבר יצאה — לפני שליחה חוזרת בדוק בממשק ימות "
                  "(קמפיינים) או המתן לתוצאות בתוכנה, כדי לא לצלצל לכולם פעמיים.\n"
                  "פרטים טכניים: {detail}")


def _http(url: str, data: bytes | None = None, retry: bool = True) -> bytes:
    global _SSL_FALLBACK
    req = None
    last_err = None
    retried = not retry            # retry=False → a single attempt
    while True:
        try:
            if _TRANSPORT is not None:
                return _TRANSPORT(url, data)
            if req is None:
                req = urllib.request.Request(url, data=data,
                                             headers={"User-Agent": "ManhalHaluka"})
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
        msg = (_DIAL_LOST_MSG.format(detail=detail) if not retry else
               "אין חיבור לשרת ימות המשיח — בדוק את האינטרנט.\n"
               f"פרטים טכניים: {detail}")
        raise YemotError(msg, code=-1) from (
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
    once = command in _DIAL_COMMANDS     # v3.15 — a dial goes out exactly once

    def _fetch(base):
        if post:
            return _http(f"{base}/{command}", encoded.encode("utf-8"), retry=not once)
        return _http(f"{base}/{command}?{encoded}", retry=not once)

    try:
        raw = _fetch(BASE_URL)
    except YemotError as e:
        if e.code != -1 or once:
            if once and e.code == -1 and "ייתכן שהשליחה" not in str(e):
                # a test transport raised the bare network error — same rule
                raise YemotError(_DIAL_LOST_MSG.format(detail=str(e)), code=-1) from e
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


# ─── Callback message — extension CALLBACK_EXT (v3.06) ───────────────────────
# Someone who missed the call dials the line back. The main menu (root ext.ini)
# runs a documented entry filter — check_template_filter (f2 post/124) — that
# looks the caller up in OUR template's stored list and sends list members to
# CALLBACK_EXT; everyone else enters the main menu exactly as before.
# CALLBACK_EXT is a menu whose welcome file (M0000.wav) is
# [the campaign message + the line's regular welcome], and whose digit
# sub-extensions are links back to the main menu's extensions — so after the
# message the caller gets the normal menu (77 = arrival survey) without ever
# re-entering the root filter (no loop). Nothing in the flow depends on the
# opaque campaign_message_to_play mechanism (v2.88–v3.05), which never played
# reliably on this line. Restore path: dev/callback_line.py restore.
CALLBACK_EXT = "78"
CALLBACK_TITLE = "הודעת החלוקה (מנהל חלוקה)"
CALLBACK_ENABLED = False     # kill switch — see ensure_callback_extension (3/9/2026 incident)
SET_CALLBACK_READY = "yemot_callback_ready"      # "<template position>:<date>"
ROOT_EXT_INI = "ivr2:/ext.ini"
_ROOT_LEGACY_KEYS = ("campaign_message_to_play_file_by_template",)


def _root_filter_wanted(pos: int) -> dict:
    """The root ext.ini keys that route our list members to CALLBACK_EXT. The
    list number is the template's position in the line's template list (the
    same numbering campaign_message_to_play used, verified statistically
    2/9/2026). Everyone else keeps entering the menu (…_enter=yes)."""
    return {"check_template_filter": str(pos),
            "check_template_filter_active_go_to": f"/{CALLBACK_EXT}",
            "check_template_filter_blocked_enter": "yes",
            "check_template_filter_none_enter": "yes",
            "check_template_filter_error_enter": "yes"}


CALLBACK_MENU_SUB = "menu"      # /78/menu — the plain main-menu clone (message already heard)
ACCESS_LOG_FILE = "AccessFilterLogTime.ini"   # the per-caller "already passed" memory


def _callback_menu_ini() -> str:
    # Same key behaviour as the main menu (2 digits, then the human transfer),
    # gated by an access filter (f2 topic/6165): each caller passes ONCE per
    # 30 days — the second call goes straight to the plain menu clone. The
    # memory file is deleted at every send, so a new message is heard once.
    return (f"type=menu\ntitle={CALLBACK_TITLE}\ndigits=2\ntimeout=1\n"
            f"timeout_goto=/2\ncheck_access_filter=yes\n"
            f"access_filter_1=g.*.*.*.*.*.30d.1.30d\n"
            f"access_filter_no_goto=/{CALLBACK_EXT}/{CALLBACK_MENU_SUB}\n")


def _callback_submenu_ini() -> str:
    return (f"type=menu\ntitle={CALLBACK_TITLE} — תפריט\ndigits=2\ntimeout=1\n"
            f"timeout_goto=/2\n")


def reset_callback_memory() -> bool:
    """Forget who already heard the message (delete the access-filter memory
    of CALLBACK_EXT) — so after a new send every list member hears the new
    message once. A missing file (nobody called back yet) is not a failure."""
    try:
        _call("FileAction", {"what": f"ivr2:/{CALLBACK_EXT}/{ACCESS_LOG_FILE}",
                             "action": "delete"}, post=True)
        return True
    except YemotError as e:
        if e.code == -1:
            raise
        return False


def _read_text(path: str) -> str | None:
    """A text file from the line, or None when it does not exist."""
    try:
        raw = _download(path)
    except YemotError as e:
        if e.code == -1 and "Not Found" not in str(e):
            raise
        return None
    if not raw or raw[:1] == b"{":
        return None
    return raw.decode("utf-8", errors="replace")


def _write_text(path: str, text: str) -> None:
    _call("UploadTextFile", {"what": path, "contents": text}, post=True)


def _ini_items(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith(";") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _ini_apply(text: str, updates: dict, drop=()) -> str:
    """Rewrite `text` with `updates` (in place when the key exists, appended
    otherwise) and without `drop` keys — every other line, comment and order
    is preserved. Adding a key never rewrites the manager's own lines."""
    lines, seen = [], set()
    for line in (text or "").splitlines():
        s = line.strip()
        key = s.split("=", 1)[0].strip() if "=" in s and not s.startswith(";") else None
        if key in drop:
            continue
        if key in updates and key not in seen:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
        if key in seen:
            continue                      # a duplicate of a key we just wrote
        lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _strip_campaign_entry(value: str, pos: int) -> str:
    """Remove OUR template's entry (`<pos>-…`) from the manager's
    campaign_message_to_play line — the old mechanism. Other entries and the
    trailing comma style stay as they are."""
    parts = [p for p in value.split(",")]
    kept = [p for p in parts if p.strip() and p.strip().split("-", 1)[0].strip() != str(pos)]
    trailing = value.rstrip().endswith(",")
    return ",".join(kept) + ("," if trailing and kept else "")


def _backup_root(text: str) -> str:
    """Keep a copy of the root ext.ini next to the DB before any rewrite —
    the manager edits this file from the Yemot site, so every version matters."""
    import os
    folder = os.path.join(os.path.dirname(db.DB_PATH), "line_backups")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"root_ext.ini.{time.strftime('%Y%m%d-%H%M%S')}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def ensure_root_filter(pos: int) -> bool:
    """Make the root ext.ini route our list members to CALLBACK_EXT (and drop
    the leftovers of the old mechanism). Writes ONLY when something differs,
    and then only the keys that are ours. Returns True when it wrote."""
    text = _read_text(ROOT_EXT_INI)
    if text is None:
        raise YemotError("לא ניתן לקרוא את הגדרות השלוחה הראשית של הקו")
    cur = _ini_items(text)
    wanted = _root_filter_wanted(pos)
    if "campaign_message_to_play" in cur:
        stripped = _strip_campaign_entry(cur["campaign_message_to_play"], pos)
        if stripped != cur["campaign_message_to_play"]:
            wanted["campaign_message_to_play"] = stripped
    drop = [k for k in _ROOT_LEGACY_KEYS if k in cur]
    if not drop and all(cur.get(k) == v for k, v in wanted.items()):
        return False
    _backup_root(text)
    _write_text(ROOT_EXT_INI, _ini_apply(text, wanted, drop))
    return True


def _concat_wavs(first: bytes, second: bytes | None, gap_s: float = 0.6) -> bytes:
    """[first + silence + second] as one WAV — when both are plain PCM with the
    same format (the line's files: 8 kHz / 16-bit / mono). Otherwise `first`."""
    import io
    import wave
    if not second:
        return first
    try:
        with wave.open(io.BytesIO(first)) as a, wave.open(io.BytesIO(second)) as b:
            if (a.getparams()[:3] != b.getparams()[:3]
                    or a.getcomptype() != "NONE" or b.getcomptype() != "NONE"):
                return first
            pa, fa, fb = a.getparams(), a.readframes(a.getnframes()), b.readframes(b.getnframes())
        gap = b"\x00" * int(pa.framerate * gap_s) * pa.nchannels * pa.sampwidth
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(pa.nchannels)
            w.setsampwidth(pa.sampwidth)
            w.setframerate(pa.framerate)
            w.writeframes(fa + gap + fb)
        return out.getvalue()
    except (wave.Error, EOFError):
        return first


def publish_callback_message(template_id: str | None = None) -> str:
    """Build CALLBACK_EXT's welcome file: the template's current recording
    followed by the main menu's own welcome (root M0000.wav — the manager's
    "press 1 for…" prompt), so the caller-back hears the message and then the
    familiar menu. Returns the uploaded path."""
    template_id = template_id or ensure_template()
    message = _download_template_message(template_id)
    try:
        welcome = _download("ivr2:/M0000.wav")
        if welcome[:4] != b"RIFF":
            welcome = None
    except YemotError:
        welcome = None
    what = f"ivr2:/{CALLBACK_EXT}/M0000.wav"
    _upload_multipart(what, _concat_wavs(message, welcome), convert="0")
    if welcome:      # the plain clone greets like the main menu, without the message
        _upload_multipart(f"ivr2:/{CALLBACK_EXT}/{CALLBACK_MENU_SUB}/M0000.wav",
                          welcome, convert="0")
    return what


def _link_ini(target: str) -> str:
    return f"type=go_to_folder\ngo_to_folder=/{target}\n"


def ensure_callback_extension(template_id: str | None = None) -> dict:
    """Verify (and repair) the whole callback path before a send:
    root filter → CALLBACK_EXT menu → digit links to the main menu's
    extensions → welcome file. Cheap when nothing changed: the root ext.ini is
    compared every time, the rest once a day per template position
    (SET_CALLBACK_READY). Raises YemotError when the extension itself is
    missing — it is created once (dev/callback_line.py) and never by a send."""
    if not CALLBACK_ENABLED:
        # 3/9/2026 14:38 incident: check_template_filter=17 matched template
        # 1430693 (the OTHER computer's list, 363 real recipients) instead of
        # 1430692 — Yemot's list numbering is not GetTemplates' 1-based order —
        # and ~140 callers heard the test recording. Disabled until the
        # numbering is verified against the right list on the live line.
        return {"disabled": True}
    template_id = template_id or ensure_template()
    pos = template_position(template_id)
    if not pos:
        raise YemotError("תבנית הצינתוק לא נמצאה ברשימת התבניות של הקו")
    result = {"position": pos, "root_changed": ensure_root_filter(pos),
              "memory_reset": reset_callback_memory(),
              "links_added": [], "message_published": False}
    stamp = f"v2:{pos}:{time.strftime('%Y-%m-%d')}"
    if (db.get_setting(SET_CALLBACK_READY) or "") == stamp:
        return result
    try:
        ext = _call("GetIVR2Dir", {"path": f"ivr2:/{CALLBACK_EXT}"})
    except YemotError as e:
        if e.code == -1:
            raise
        raise YemotError(f"שלוחה {CALLBACK_EXT} (הודעת החלוקה) לא קיימת בקו — "
                         f"יש ליצור אותה פעם אחת: dev/callback_line.py apply")
    root = _call("GetIVR2Dir", {"path": "ivr2:/"})
    digit_exts = [d.get("name") for d in root.get("dirs") or []
                  if d.get("exists") and re.fullmatch(r"\d+", str(d.get("name") or ""))]
    sub = f"{CALLBACK_EXT}/{CALLBACK_MENU_SUB}"
    for path, wanted in ((CALLBACK_EXT, _callback_menu_ini()), (sub, _callback_submenu_ini())):
        cur = _ini_items(_read_text(f"ivr2:/{path}/ext.ini") or "")
        if any(cur.get(k) != v for k, v in _ini_items(wanted).items()):
            # UploadFile also creates a missing folder; UploadTextFile does not.
            _upload_multipart(f"ivr2:/{path}/ext.ini", wanted.encode("utf-8"), convert="0")
        listing = ext if path == CALLBACK_EXT else _call("GetIVR2Dir", {"path": f"ivr2:/{path}"})
        have = {d.get("name") for d in listing.get("dirs") or [] if d.get("exists")}
        for name in digit_exts:
            if name == CALLBACK_EXT or name in have:
                continue
            _upload_multipart(f"ivr2:/{path}/{name}/ext.ini",
                              _link_ini(name).encode("utf-8"), convert="0")
            result["links_added"].append(f"{path}/{name}")
        if not any(str(f.get("name")) == "M0000.wav" for f in listing.get("files") or []):
            result["message_published"] = True
    if result["message_published"]:
        publish_callback_message(template_id)
    db.set_setting(SET_CALLBACK_READY, stamp)
    return result


def upload_message_wav(file_path: str, template_id: str | None = None) -> dict:
    """Attach a recording file to the campaign template (converted to the
    telephony WAV format server-side). The campaign-file path uses the
    documented ``tpl:`` prefix; older servers may want ``ivr2:``, so a path
    error triggers one retry with that form."""
    template_id = template_id or ensure_template()
    with open(file_path, "rb") as f:
        content = f.read()
    try:
        res = _upload_multipart(f"tpl:{template_id}", content)
    except YemotError as e:
        if e.code not in (107, 109, 110):   # path not accepted — try the other form
            raise
        res = _upload_multipart(f"ivr2:{template_id}.wav", content)
    try:
        publish_callback_message(template_id)   # the caller-back hears the NEW message
    except YemotError:
        pass                                    # repaired again at the next send
    return res


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
            ensure_callback_extension(main_id)   # list members → message on callback
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


def bucket_by_hour(phones: dict, stats: dict, fallback_hour: int) -> dict:
    """Split {phone: name} into {hour: {phone: name}} by each phone's personal
    best hour (answer_stats' de-biased best_hour); phones without one go to
    `fallback_hour` (the list's crowd hour). Pure — unit-tested."""
    buckets: dict = {}
    for p, name in phones.items():
        s = (stats or {}).get(p)
        h = s.get("best_hour") if s else None
        if h is None:
            h = fallback_hour
        buckets.setdefault(int(h), {})[p] = name
    return buckets


def ensure_hour_template(hour: int) -> str:
    """The dedicated campaign template for one send hour, created once and
    remembered in a synced setting. Adopts an existing same-named template first
    (the other computer may have made it) so the two machines converge instead
    of breeding twin templates — the mistake that broke the callback filter."""
    hour = int(hour)
    raw = (db.get_setting(SET_HOUR_TEMPLATES) or "").strip()
    try:
        mapping = json.loads(raw) if raw else {}
    except ValueError:
        mapping = {}
    tid = str(mapping.get(str(hour)) or "").strip()
    if tid:
        return tid
    desc = HOUR_TEMPLATE_DESC.format(hour)
    used = {str(v) for v in mapping.values()}
    used.add((db.get_setting(SET_TEMPLATE) or "").strip())
    used.add((db.get_setting(SET_CLASSIC_TEMPLATE) or "").strip())
    data = _call("GetTemplates")
    for t in (data.get("templates") or []):
        cand = str(t.get("templateId") or "").strip()
        if cand and cand not in used and str(t.get("description") or "") == desc:
            tid = cand
            break
    if not tid:
        created = _call("CreateTemplate", {"description": desc}, post=True)
        tid = str(_dig(created, "templateId") or "").strip()
        if not tid:
            raise YemotError(f"יצירת תבנית לשעה {hour:02d}:00 נכשלה")
    mapping[str(hour)] = tid
    db.set_setting(SET_HOUR_TEMPLATES, json.dumps(mapping))
    return tid


def _attach_message_bytes(template_id: str, content: bytes) -> None:
    """Attach an already-telephony-WAV recording (bytes) to a template, with the
    same tpl:/ivr2: path fallback as upload_message_wav (no local file needed)."""
    try:
        _upload_multipart(f"tpl:{template_id}", content, convert="0")
    except YemotError as e:
        if e.code not in (107, 109, 110):
            raise
        _upload_multipart(f"ivr2:{template_id}.wav", content, convert="0")


def schedule_smart(date, buckets: dict, progress=None) -> list:
    """Server-side scheduling that dials each hour's group at ITS hour — so each
    recipient is rung at their own best time, even when this computer is off.
    `date` is a datetime/date/'YYYY-MM-DD' for the send day; `buckets` is
    {hour: {phone: name}} (from bucket_by_hour). Any bucket whose time is already
    in the past is pushed to a few minutes from now. Each hour uses its own
    dedicated template (lists never overwrite), seeded with the current recording
    copied server-side from the main template. Returns one dict per bucket:
    {'hour','when' (datetime),'schedId','count','template_id','pushed' (bool)}."""
    from datetime import datetime, date as _date, time as _time, timedelta
    if isinstance(date, str):
        d = datetime.strptime(date[:10], "%Y-%m-%d").date()
    elif isinstance(date, datetime):
        d = date.date()
    elif isinstance(date, _date):
        d = date
    else:
        raise YemotError("תאריך שליחה לא תקין")
    zone = timefmt._israel_zone()
    now = datetime.now(zone) if zone is not None else datetime.now()
    now = now.replace(tzinfo=None)
    main = ensure_template()
    message = _download_template_message(main)      # raises if no recording yet
    results = []
    hours = sorted(int(h) for h, ph in buckets.items() if ph)
    for i, hour in enumerate(hours):
        phones = buckets[hour]
        if progress:
            progress(i, len(hours), hour)
        when = datetime.combine(d, _time(hour, 0))
        pushed = False
        if when <= now:
            when = now.replace(second=0, microsecond=0) + timedelta(minutes=3)
            pushed = True
        try:
            tid = ensure_hour_template(hour)
            _attach_message_bytes(tid, message)
            count = set_template_entries(phones, tid)
            data = _call("ScheduleCampaign",
                         {"templateId": tid,
                          "time": when.strftime("%Y-%m-%d %H:%M")}, post=True)
        except Exception as e:
            # A failure in the middle leaves the EARLIER hours scheduled on the
            # server. Hand them to the caller on the exception so they get
            # recorded (and can be canceled) instead of ringing people with no
            # trace in the app.
            e.partial_results = results        # noqa: B010
            raise
        sched_id = str(_dig(data, "schedId") or _dig(data, "id") or "").strip()
        if not sched_id:
            for c in reversed(get_scheduled_campaigns("PENDING")):
                if str(_dig(c, "templateId") or "") == str(tid):
                    sched_id = str(_dig(c, "schedId") or _dig(c, "id") or "").strip()
                    break
        results.append({"hour": hour, "when": when, "schedId": sched_id,
                        "count": count, "template_id": tid, "pushed": pushed})
    return results


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


def _sched_time_local(rec) -> datetime | None:
    """The run/planned time of a scheduled-campaign record as naive Israel
    local time — PENDING rows carry `time` ('YYYY-MM-DD HH:MM'), SUCCESSFUL/
    FAILED rows carry `startTime` ('YYYY-MM-DD HH:MM:SS')."""
    raw = str(_dig(rec, "startTime") or _dig(rec, "time") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def find_scheduled_by_template(template_id, planned_iso: str,
                               tolerance_min: int = 20) -> tuple:
    """Locate a scheduled campaign whose schedId we never got: the run of
    `template_id` closest to the planned time (UTC iso, within `tolerance_min`)
    → ('pending'|'successful'|'failed'|'missing', record|None). A template is
    reused week after week, so the time — not the template alone — picks the
    right run."""
    tid = str(template_id or "").strip()
    planned = _parse_since(planned_iso)
    if not tid or planned is None:
        return "missing", None
    zone = timefmt._israel_zone()
    local = (planned.astimezone(zone) if zone is not None
             else planned.astimezone()).replace(tzinfo=None)
    best = None                                   # (delta, word, rec)
    for typ, word in (("PENDING", "pending"), ("SUCCESSFUL", "successful"),
                      ("FAILED", "failed")):
        for c in get_scheduled_campaigns(typ):
            if str(_dig(c, "templateId") or "") != tid:
                continue
            at = _sched_time_local(c)
            if at is None:
                continue
            delta = abs((at - local).total_seconds())
            if delta <= tolerance_min * 60 and (best is None or delta < best[0]):
                best = (delta, word, c)
    return (best[1], best[2]) if best else ("missing", None)


def find_pending_sched_id(template_id) -> str:
    """The schedId of the PENDING run of `template_id` on the server ('' when
    none) — recovers a record whose ScheduleCampaign answer carried no id."""
    tid = str(template_id or "").strip()
    if not tid:
        return ""
    for c in reversed(get_scheduled_campaigns("PENDING")):
        if str(_dig(c, "templateId") or "") == tid:
            return str(_dig(c, "schedId") or _dig(c, "id") or "").strip()
    return ""


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


def _israel_str_to_utc_iso(text) -> str:
    """'2026-09-03 14:50:43' (server = Israel local time) → UTC iso; '' when
    missing/unparsable."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        local = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    zone = timefmt._israel_zone()
    at = local.replace(tzinfo=zone) if zone is not None else local.astimezone()
    return at.astimezone(timezone.utc).isoformat()


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
            # v3.09 — the real dial time of THIS number (Israel clock on the
            # server → UTC iso) and how long they listened, in seconds; feeds
            # the per-person hour statistics (answer_stats)
            "at": _israel_str_to_utc_iso(e.get("startTime")),
            "duration": round(float(e.get("duration") or 0) / 1000.0, 1),
            # earlier attempts of the same number (maxDialAttempts>1) — each
            # one is a real "rang at that hour, no answer" observation
            "redials": [{"status": str(r.get("entryStatus") or "").lower(),
                         "at": _israel_str_to_utc_iso(r.get("startTime"))}
                        for r in (e.get("redials") or []) if isinstance(r, dict)],
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


def merge_survey_answers(entries: list, rows: list, since_iso: str = "",
                         until_by_phone: dict | None = None) -> tuple:
    """Stamp each report entry with the person's LATEST survey answer given
    after `since_iso` (the campaign's send time — last week's answers must not
    leak into this week): entry['answer'] = '1'/'2'/'3', or '' = the survey was
    checked and the person did not answer ("לא הגיב"); entry['answer_at'] =
    UTC iso. Returns (entries, changed).

    until_by_phone (v3.20): {phone: UTC iso} — the moment a LATER campaign
    rang that number. An answer given after it belongs to that later campaign,
    not to this one (until now this week's answers were also stamped onto
    last week's campaign, rewriting its history and its "אישר הגעה" tags)."""
    since = _parse_since(since_iso)
    until = {}
    for p, iso in (until_by_phone or {}).items():
        dt = _parse_since(iso) if isinstance(iso, str) else iso
        if dt is not None:
            until[p] = dt
    latest = {}
    for r in rows or []:
        if since is not None and r["at"] < since:
            continue
        stop = until.get(r["phone"])
        if stop is not None and r["at"] >= stop:
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


def answer_windows(camps: list) -> dict:
    """{guid: {phone: sent_at iso of the NEXT campaign that rang this phone}}
    for a newest-first campaign list — the per-phone upper bound handed to
    merge_survey_answers, so every survey answer is credited to the most
    recent campaign that rang the number (canceled / failed / still-future
    schedules ring nobody and are ignored). Pure — unit-tested."""
    out = {}
    latest = {}                       # phone → sent_at of the nearest LATER campaign
    for camp in camps or []:
        if camp.get("status") not in ("sending", "done"):
            continue
        sent = camp.get("sent_at") or ""
        phones = {normalize_phone(e.get("phone")) for e in _report_entries(camp)}
        phones.discard("")
        out[camp.get("guid") or ""] = {p: latest[p] for p in phones if p in latest}
        if sent:
            for p in phones:
                latest[p] = sent
    return out


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


# ─── Smart-timing statistics (#y7jr0, stage 1 · v3.09 real hours) ──────────

MIN_SMART_HISTORY = 10   # dial attempts needed before a personal best hour is shown
MIN_CALLBACK_HISTORY = 3  # …or this many times the person called the line back


def _entry_hour(iso: str):
    """UTC iso → Israel hour, or None."""
    when = timefmt.to_israel(iso or "")
    return None if when is None else when.hour


def answer_stats() -> dict:
    """Per-phone reachability history:
    {phone: {"attempts": n, "answered": n, "calls": n,
             "by_hour": {hour: [good, tries]}, "by_call_hour": {hour: n},
             "best_hour": int|None}}.
    Sources (all on the Israel clock):
    * the app's own campaign reports (tzintuk_campaigns, synced) — the hour the
      server actually rang THIS number (entry 'at', v3.09; older reports fall
      back to the campaign's send hour), its redials, and whether it answered;
    * v3.10/v3.11: the Yemot server's history cached by utils.call_history —
      every campaign the line ever ran (even before the app) and every
      INCOMING call to the line from the folder log, since the line began
      (aggregated phone→hour counts per month). A campaign already stored in the
      DB is not counted twice (campaign_id), and the app's own call-back
      stamps ('answer_at'/'returned_at') are skipped for months the server log
      covers.
    Calling in is the strongest signal that the person is reachable at that
    hour, so it counts as a success in by_hour too. best_hour appears after
    MIN_SMART_HISTORY attempts or MIN_CALLBACK_HISTORY calls — the hour with
    the highest success rate among hours seen at least twice."""
    from utils import call_history
    camps = db.get_tzintuk_campaigns()
    # memo: seven years of history take ~1.5 s to fold — recompute only when
    # the server cache file or the app's own campaign rows changed
    try:
        cache_mtime = os.path.getmtime(call_history.cache_path())
    except OSError:
        cache_mtime = None
    key = (cache_mtime, len(camps),
           max((str(c.get("status_ts") or "") for c in camps), default=""),
           tuple(c.get("status") for c in camps[:3]))
    if _STATS_MEMO.get("key") == key:
        return _STATS_MEMO["stats"]
    stats = {}

    def _rec(p):
        return stats.setdefault(p, {"attempts": 0, "answered": 0, "calls": 0,
                                    "by_hour": {}, "by_call_hour": {},
                                    "best_hour": None})

    def _attempt(p, hour, answered):
        s = _rec(p)
        s["attempts"] += 1
        s["answered"] += 1 if answered else 0
        bucket = s["by_hour"].setdefault(hour, [0, 0])
        bucket[1] += 1
        bucket[0] += 1 if answered else 0

    def _call_in(p, hour):
        s = _rec(p)
        s["calls"] += 1
        s["by_call_hour"][hour] = s["by_call_hour"].get(hour, 0) + 1
        bucket = s["by_hour"].setdefault(hour, [0, 0])
        bucket[1] += 1
        bucket[0] += 1

    def _entries(entries, camp_hour, callbacks: bool, covered: set):
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            p = normalize_phone(e.get("phone"))
            if not p:
                continue
            status = str(e.get("status") or "").lower()
            # (a) a real dial attempt (classic 'callback'/'no_callback' rows
            #     are not attempts — the tzintuk never connects)
            answered = (bool(e.get("ok")) or status in _DELIVERED) and status != "callback"
            failed = bool(e.get("failed")) or status in _FAILED
            hour = _entry_hour(e.get("at") or "")
            if hour is None:
                hour = camp_hour
            if (answered or failed) and hour is not None:
                _attempt(p, hour, answered)
                for r in e.get("redials") or []:
                    rh = _entry_hour((r or {}).get("at") or "")
                    if rh is not None:
                        _attempt(p, rh, False)
            # (b) the person called the line back (one event per campaign)
            if not callbacks:
                continue
            call_iso = e.get("answer_at") or e.get("returned_at") or ""
            when = timefmt.to_israel(call_iso)
            if when is None or when.strftime("%Y-%m") in covered:
                continue
            _call_in(p, when.hour)

    hist = call_history.load()
    covered = set(hist.get("months") or {})
    seen_ids = set()
    for camp in camps:
        if camp.get("status") != "done":
            continue
        try:
            entries = json.loads(camp.get("report_json") or "[]")
        except ValueError:
            continue
        if camp.get("campaign_id"):
            seen_ids.add(str(camp["campaign_id"]))
        _entries(entries, _entry_hour(camp.get("sent_at") or ""), True, covered)
    for cid, camp in (hist.get("campaigns") or {}).items():
        if cid in seen_ids or not isinstance(camp, dict):
            continue
        _entries(camp.get("entries"), _entry_hour(camp.get("at") or ""), False, covered)
    for month in (hist.get("months") or {}).values():
        for p, hours in ((month or {}).get("hours") or {}).items():
            for h, n in (hours or {}).items():
                try:
                    hour, n = int(h), int(n)
                except (TypeError, ValueError):
                    continue
                if p and 0 <= hour < 24 and n > 0:
                    s = _rec(p)
                    s["calls"] += n
                    s["by_call_hour"][hour] = s["by_call_hour"].get(hour, 0) + n
                    bucket = s["by_hour"].setdefault(hour, [0, 0])
                    bucket[1] += n
                    bucket[0] += n
    # ── personal best hour — the "deviation" method ──────────────────────────
    # Raw hour counts are useless here: because the line almost always sends its
    # tzintuk around one hour (13:00), EVERY signal piles up there — people call
    # the line back at 13:00, and they can only ANSWER at hours we actually rang
    # (13:00). Taking each person's busiest hour therefore returns the line's
    # global peak for almost everyone (a self-fulfilling loop). Instead we score
    # each hour by how much THIS person stands out at it versus the whole line
    # (personal share ÷ global share), using only INBOUND calls — the one signal
    # the person initiates themselves, independent of when we choose to dial. It
    # sharpens on its own once we start sending at varied hours.
    gcall = {}
    for s in stats.values():
        for h, n in s["by_call_hour"].items():
            gcall[h] = gcall.get(h, 0) + n
    gt = sum(gcall.values())
    gshare = {h: (gcall.get(h, 0) + 1) / (gt + 24) for h in range(24)}
    for s in stats.values():
        s["best_hour"] = personal_hour(s["by_call_hour"], gshare)
    _STATS_MEMO.update(key=key, stats=stats)
    return stats


_STATS_MEMO = {"key": None, "stats": {}}

PERSONAL_HOUR_MIN_MASS = 2      # at least this many of the person's calls at the hour
PERSONAL_HOUR_MIN_FRAC = 0.15   # …and at least this share of all their calls


def personal_hour(by_call_hour: dict, gshare: dict):
    """The hour a person is relatively most active at, vs the line as a whole
    (the "deviation" method — see answer_stats). `gshare` is the line-wide hour
    distribution {hour: fraction}. None until MIN_CALLBACK_HISTORY inbound calls
    and one hour that carries real personal mass. Pure — unit-tested."""
    total = sum((by_call_hour or {}).values())
    if total < MIN_CALLBACK_HISTORY:
        return None
    cand = [h for h, n in by_call_hour.items()
            if n >= PERSONAL_HOUR_MIN_MASS and n / total >= PERSONAL_HOUR_MIN_FRAC]
    if not cand:
        return None
    return max(cand, key=lambda h: (by_call_hour[h] / total) / gshare.get(h, 1e-9))


def usual_call_hour(s: dict):
    """Kept for callers/tooltips: the person's relative best hour (same value as
    best_hour), or None when there is not enough personal signal yet."""
    return (s or {}).get("best_hour")


def list_best_hour(phones, stats) -> int | None:
    """The single hour that historically works best for the WHOLE list (highest
    answer rate across everyone with history) — the fallback bucket for people
    who have no personal hour yet. This is the crowd's peak (typically ~13:00),
    which is a sensible default when we know nothing personal about someone."""
    by_hour = {}
    for p in phones:
        s = (stats or {}).get(p)
        if not s:
            continue
        for h, (a, t) in s["by_hour"].items():
            b = by_hour.setdefault(h, [0, 0])
            b[0] += a
            b[1] += t
    best = [(a / t, t, h) for h, (a, t) in by_hour.items() if t >= 10]
    return max(best)[2] if best else None


def run_test(phone: str, store: bool = True) -> dict:
    """Ring one number (the operator's own) so they can hear the recording.
    The number is also added to the template's stored list (without clearing
    it) so calling the line back plays the message — the field test of 1/9
    found a callback after a test heard nothing because tests never stored
    the number. store=False skips that (a pending SCHEDULE dials the stored
    list — the test number must not sneak into it)."""
    p = normalize_phone(phone)
    if not p:
        raise YemotError("מספר הבדיקה אינו תקין")
    if store:
        try:
            add_template_entry(p, "בדיקה")
            ensure_callback_extension()   # the tester hears the message on callback
        except YemotError:
            pass                          # best-effort — never blocks the test ring
    return run_campaign({p: "בדיקה"})

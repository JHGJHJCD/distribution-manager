# -*- coding: utf-8 -*-
"""שרת המענה לחזרה-לצינתוק (Cloudflare Worker) — לקוח טהור, בלי Qt (v3.33).

הרעיון: צינתוק קלאסי (0.1) מצלצל ← הזכאי מחייג חזרה לקו ← שלוחת ``type=api`` בקו
פונה לשרת שלנו ← השרת עונה אישית ("יש לך חלוקה, 1 מגיע / 2 לא / 3 לא יודע") ושומר
את ההקשה. זה מחליף את שלוחה 78 + סקר 77 השבירים (סאגת v3.06–v3.08) בשרת קטן שלנו.
קוד השרת: ``dev/cloudflare/api_link_worker.js`` (פרוס דרך "פיתוחים אישיים" בפתרונאי).

התוכנה מדברת עם השרת בשתי דלתות (שתיהן מוגנות בסוד):
  * ``POST /push``    — דוחפת את רשימת הזכאים של השבוע (בזמן השליחה).
  * ``GET  /answers`` — קוראת מי ענה. השורות מוחזרות **באותה צורה בדיוק** של
    ``yemot.parse_approval_rows`` ({phone, at (UTC aware), answer}) — ולכן הן מתמזגות
    לתוך ``yemot.fetch_survey_rows`` וכל המנגנון הקיים (merge_survey_answers, תגי
    "אישר הגעה", היסטוריה, אקסל, "לא הגיב") עובד בלי שינוי.

הגדרות (מסונכרנות, כמו ``yemot_password`` — שני המחשבים משתמשים באותו שרת):
``cb_server_url`` · ``cb_server_secret`` · ``cb_server_enabled`` ("1"/"0"). כבוי כברירת
מחדל עד שיאומת בשטח. הסוד לא נכתב לשום קובץ שנכנס ל-git.

אף פקודה כאן **לא מחייגת** — push הוא החלפת-רשימה אידמפוטנטית ו-answers קריאה,
לכן retry בטוח. חסימת נטפרי (418) מזוהה דרך ``utils.netblock`` (קוד -3).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from utils import netblock

SET_URL = "cb_server_url"
SET_SECRET = "cb_server_secret"
SET_ENABLED = "cb_server_enabled"
DEFAULT_URL = "https://pai-dev-s-api-link.pai-ffff542b.workers.dev"

TIMEOUT_S = 10             # קצר: הדחיפה רצה בתוך דיאלוג "שולח…" אחרי שהחיוג כבר יצא
_FAIL_BACKOFF_S = 60       # אחרי כישלון קריאה — לא להציק לשרת בכל טיק של המעקב
_TRANSPORT = None          # tests inject: callable(url, data_bytes|None) -> bytes
_backoff_until = 0.0


class CallbackError(Exception):
    """code -1 = אין תשובה מהשרת · -3 = נטפרי חסם · 403 = סוד שגוי · אחר = HTTP."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


# ─── Settings ────────────────────────────────────────────────────────────────

def _get(key: str) -> str:
    import database as db
    return (db.get_setting(key) or "").strip()


def base_url() -> str:
    return (_get(SET_URL) or DEFAULT_URL).rstrip("/")


def secret() -> str:
    return _get(SET_SECRET)


def is_enabled() -> bool:
    return _get(SET_ENABLED) == "1"


def is_configured() -> bool:
    return bool(base_url() and secret())


# ─── Transport ───────────────────────────────────────────────────────────────

def _url(path: str, **query) -> str:
    q = {"secret": secret()}
    q.update({k: v for k, v in query.items() if v})
    return f"{base_url()}{path}?{urllib.parse.urlencode(q)}"


def _http(url: str, data: bytes | None = None) -> bytes:
    """בקשה אחת + ניסיון חוזר יחיד על תקלה חולפת. 418 = נטפרי, בלי ניסיון חוזר."""
    last = None
    for attempt in (0, 1):
        try:
            if _TRANSPORT is not None:
                return _TRANSPORT(url, data)
            req = urllib.request.Request(
                url, data=data,
                headers={"User-Agent": "ManhalHaluka",
                         "Content-Type": "application/json; charset=utf-8"},
                method="POST" if data is not None else "GET")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if netblock.is_blocked(e):
                raise CallbackError(netblock.NETFREE_MSG, code=-3) from e
            if e.code == 403:
                raise CallbackError("שרת המענה דחה את הסוד (403) — בדוק שהסוד בהגדרות "
                                    "זהה לסוד APP_SECRET שבשרת.", code=403) from e
            raise CallbackError(f"שרת המענה החזיר שגיאה {e.code}.", code=e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt == 0:
                time.sleep(1.0)
                continue
    if netblock.is_blocked(last):
        raise CallbackError(netblock.NETFREE_MSG, code=-3) from last
    detail = str(last) or type(last).__name__
    raise CallbackError("אין חיבור לשרת המענה — בדוק את האינטרנט.\n"
                        f"פרטים טכניים: {detail}", code=-1) from last


# ─── API ─────────────────────────────────────────────────────────────────────

def push_payload(dist_date: str, phones: dict) -> dict:
    """{phone: name} → גוף הבקשה ל-/push (טהור — נבדק)."""
    from utils.yemot import normalize_phone
    seen, out = set(), []
    for p, n in (phones or {}).items():
        np_ = normalize_phone(p)
        if not np_ or np_ in seen:
            continue
        seen.add(np_)
        out.append({"phone": np_, "name": n or ""})
    return {"dist_date": dist_date or "", "phones": out}


def push_week_list(dist_date: str, phones: dict) -> int:
    """דוחפת את רשימת השבוע לשרת (מחליפה את הקודמת). מחזירה כמה מספרים נקלטו."""
    body = json.dumps(push_payload(dist_date, phones), ensure_ascii=False).encode("utf-8")
    raw = _http(_url("/push"), body)
    try:
        res = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except ValueError as e:
        raise CallbackError("שרת המענה החזיר תשובה לא צפויה לדחיפת הרשימה.") from e
    if not res.get("ok"):
        raise CallbackError("שרת המענה לא אישר את קליטת הרשימה.")
    return int(res.get("count") or 0)


def _parse_at(value) -> datetime | None:
    """'YYYY-MM-DD HH:MM:SS' (SQLite datetime('now') = UTC) או ISO → UTC aware."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def parse_answer_rows(payload) -> list:
    """תשובת /answers → [{'phone', 'at' (UTC aware), 'answer'}] — אותה צורה של
    ``yemot.parse_approval_rows``. שורות בלי טלפון/תשובה/זמן תקינים מדולגות."""
    from utils.yemot import normalize_phone
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except ValueError:
            return []
    items = payload.get("answers") if isinstance(payload, dict) else payload
    rows = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        phone = normalize_phone(it.get("phone"))
        answer = str(it.get("answer") or "").strip()
        at = _parse_at(it.get("at"))
        if not phone or not answer or at is None:
            continue
        rows.append({"phone": phone, "at": at, "answer": answer})
    return rows


def fetch_answer_rows(dist_date: str = "") -> list:
    """קריאת התשובות מהשרת. אחרי כישלון — שקט ל-60 שנ' (המעקב קורא כל ~20 שנ')."""
    global _backoff_until
    if time.time() < _backoff_until:
        return []
    try:
        raw = _http(_url("/answers", dist_date=dist_date))
    except CallbackError:
        _backoff_until = time.time() + _FAIL_BACKOFF_S
        raise
    _backoff_until = 0.0
    return parse_answer_rows(raw)


def check_connection() -> int:
    """"בדוק חיבור" בהגדרות: קורא את התשובות; מחזיר כמה יש. מעלה CallbackError."""
    global _backoff_until
    _backoff_until = 0.0
    return len(fetch_answer_rows())


# ─── שלוחת ה-API בקו (v3.34) ─────────────────────────────────────────────────
# הקו משותף עם מערכת אחרת; מי שמחזיק את סיסמת הקו יכול למחוק/לשנות את השלוחה
# בטעות (או לשחזר גיבוי ישן של הקו). לפני חיוג התוכנה קוראת את השלוחה ומשווה;
# "תקן" כותב מחדש **רק** את הקובץ של השלוחה הזו — לעולם לא את השורש.
EXT = "76"
EXT_PATH = f"ivr2:/{EXT}/ext.ini"
EXT_TITLE = "שרת המענה (מנהל חלוקה)"


def expected_ext_ini(url: str | None = None) -> str:
    """תוכן ה-ext.ini של השלוחה כפי שהתוכנה מצפה לו (טהור)."""
    link = (url or base_url()).rstrip("/")
    # api_wait_answer_music_on_hold=no — ב-ivr.ini של הקו מוזיקת-המתנה דלוקה לכל שלוחת
    # API; כאן השרת עונה תוך ~0.5 שנ' וכל מתקשר ל-04 עובר דרכה (Did_Go_To) — בלי מוזיקה.
    # api_end_goto=/ — גם כשהשרת לא קבע יעד, המתקשר ממשיך לתפריט הראשי.
    return (f"type=api\ntitle={EXT_TITLE}\napi_link={link}\n"
            "api_wait_answer_music_on_hold=no\napi_end_goto=/\n")


def parse_ext_ini(text: str) -> dict:
    """``key=value`` לכל שורה → dict (טהור; שורות ריקות/הערות מדולגות)."""
    out = {}
    for line in (text or "").replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def extension_problem(text: str | bytes | None, url: str | None = None) -> str:
    """"" = השלוחה תקינה; אחרת סיבה בעברית פשוטה (טהור). הכותרת לא נבדקת —
    רק הסוג וכתובת השרת (זה מה שקובע לאן המתקשר מגיע)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = (text or "").strip()
    if not text or text.startswith("{"):        # DownloadFile החזיר JSON = אין קובץ
        return f"שלוחה {EXT} לא קיימת בקו (נמחקה או שוחזר גיבוי ישן של הקו)."
    ini = parse_ext_ini(text)
    if ini.get("type", "").lower() != "api":
        return (f"שלוחה {EXT} שונתה בקו — היא כבר לא שלוחת API "
                f"(סוג נוכחי: {ini.get('type') or 'לא מוגדר'}).")
    want = (url or base_url()).rstrip("/")
    have = ini.get("api_link", "").rstrip("/")
    if have != want:
        return (f"שלוחה {EXT} מצביעה לכתובת אחרת ולא לשרת המענה שלנו.\n"
                f"בקו: {have or '(ריק)'}\nצפוי: {want}")
    return ""


def verify_extension() -> str:
    """קורא את השלוחה מהקו (קריאה בלבד) ומחזיר "" / סיבה. מעלה YemotError על תקלת רשת."""
    from utils import yemot
    try:
        raw = yemot._download(EXT_PATH)
    except yemot.YemotError as e:
        if e.code in (-1, -3):
            raise
        raw = b""                               # השרת ענה "אין קובץ" כשגיאה
    return extension_problem(raw)


def repair_extension() -> None:
    """כותב מחדש את ext.ini של שלוחה EXT בלבד (לא נוגע בשום קובץ אחר בקו)."""
    from utils import yemot
    yemot._upload_multipart(EXT_PATH, expected_ext_ini().encode("utf-8"), convert="0")

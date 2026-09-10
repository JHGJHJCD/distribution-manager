# -*- coding: utf-8 -*-
"""חיבור לחשבון Google ("התחבר עם Google") — v3.39.

OAuth 2.0 לאפליקציית-מחשב (PKCE + loopback), רק ספריית-הסטנדרט (urllib,
http.server). בלי Qt — כך שניתן לבדוק עם תחבורה מוזרקת (`_TRANSPORT`).

מה יש כאן:
  * זיהוי-לקוח (client_id/secret) — מ-`utils/_secret.py` (נכנס ל-EXE, לא ל-git)
    או מקובץ `google_client.json` ליד ה-DB (לפיתוח/בדיקה בלי בנייה מחדש).
  * `connect()` — פותח דפדפן במסך ההסכמה של גוגל, מאזין על 127.0.0.1 לקוד,
    ממיר לטוקנים ושומר refresh_token + כתובת המייל ב-settings (מסונכרנות —
    הכרעת המשתמש 10/9/2026: חיבור אחד משותף לשני המחשבים).
  * `access_token()` — טוקן-גישה תקף (מרענן לבד, מטמון בזיכרון).
  * `gmail_send_raw(mime_bytes)` — שליחה דרך Gmail API (users.messages.send).

הרשאות שמבוקשות: gmail.send בלבד (+ כתובת המייל לזיהוי). אין קריאת מיילים.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import database as db
from utils import netblock

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPES = ("https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/userinfo.email", "openid")

SET_REFRESH = "google_refresh_token"
SET_EMAIL = "google_email"
CLIENT_FILE = "google_client.json"      # ליד ה-DB — fallback לפיתוח

# תחבורה ניתנת-להזרקה: fn(method, url, data_bytes|None, headers) -> (status, body_bytes)
_TRANSPORT = None
# מטמון טוקן-גישה בזיכרון: {"token": str, "exp": epoch}
_cache = {"token": "", "exp": 0.0}
# לבדיקות: במקום לפתוח דפדפן ולחכות לקוד — פונקציה שמקבלת את ה-URL ומחזירה קוד
_CODE_PROVIDER = None


class GoogleAuthError(RuntimeError):
    """שגיאה בעברית, מוכנה להצגה למפעיל."""


# ─── זיהוי-לקוח ───────────────────────────────────────────────────────────────

def client_credentials() -> tuple[str, str]:
    """(client_id, client_secret) — מ-_secret.py, ואם ריק מקובץ google_client.json
    ליד ה-DB (הפורמט שגוגל מורידה: {"installed": {...}} או שטוח)."""
    cid = sec = ""
    try:
        from utils import _secret
        cid = (getattr(_secret, "GOOGLE_CLIENT_ID", "") or "").strip()
        sec = (getattr(_secret, "GOOGLE_CLIENT_SECRET", "") or "").strip()
    except Exception:
        pass
    if cid:
        return cid, sec
    path = os.path.join(os.path.dirname(db.DB_PATH), CLIENT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data.get("installed") or data.get("web") or data
        return ((data.get("client_id") or "").strip(),
                (data.get("client_secret") or "").strip())
    except Exception:
        return "", ""


def is_available() -> bool:
    """האם לגרסה הזו יש זיהוי-לקוח של גוגל (בלעדיו כפתור ההתחברות נעול)."""
    return bool(client_credentials()[0])


def is_connected() -> bool:
    return bool((db.get_setting(SET_REFRESH) or "").strip())


def connected_email() -> str:
    return (db.get_setting(SET_EMAIL) or "").strip()


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def _urllib_transport(method, url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        return e.code, body


def _http(method, url, data=None, headers=None):
    fn = _TRANSPORT or _urllib_transport
    try:
        return fn(method, url, data, headers or {})
    except (OSError, socket.timeout) as e:
        raise GoogleAuthError(
            "אין חיבור לאינטרנט — לא ניתן לפנות לגוגל. בדוק את הרשת ונסה שוב.") from e


def _post_form(url, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    status, raw = _http("POST", url, body,
                        {"Content-Type": "application/x-www-form-urlencoded"})
    if netblock.is_blocked(status) or netblock.is_blocked(raw):
        raise GoogleAuthError(netblock.explain(raw, netblock.NETFREE_MSG))
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        data = {}
    if status != 200:
        err = data.get("error") or f"HTTP {status}"
        if err == "invalid_grant":
            raise GoogleAuthError(
                "החיבור לגוגל פג או בוטל — יש ללחוץ שוב על \"התחבר עם Google\" בהגדרות.")
        if err == "invalid_client":
            raise GoogleAuthError("זיהוי האפליקציה מול גוגל שגוי (client_id/secret).")
        raise GoogleAuthError(f"גוגל דחתה את הבקשה ({err}: {data.get('error_description', '')})")
    return data


# ─── התחברות ─────────────────────────────────────────────────────────────────

_DONE_HTML = ("<!doctype html><html dir='rtl' lang='he'><meta charset='utf-8'>"
              "<body style='font-family:Segoe UI,Arial;background:#f4faf7;text-align:center;"
              "padding-top:80px;color:#0f766e'><h1>✓ החיבור הצליח</h1>"
              "<p style='font-size:18px;color:#334155'>אפשר לסגור את החלון הזה ולחזור לתוכנה "
              "\"מנהל חלוקה\".</p></body></html>")
_FAIL_HTML = ("<!doctype html><html dir='rtl' lang='he'><meta charset='utf-8'>"
              "<body style='font-family:Segoe UI,Arial;text-align:center;padding-top:80px;"
              "color:#991b1b'><h1>החיבור לא הושלם</h1><p>חזור לתוכנה ונסה שוב.</p></body></html>")


class _OneShotHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (q.get("code") or [""])[0]
        state = (q.get("state") or [""])[0]
        ok = bool(code) and state == self.server.expected_state
        _OneShotHandler.result = {"code": code if ok else "",
                                  "error": (q.get("error") or [""])[0]}
        body = (_DONE_HTML if ok else _FAIL_HTML).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.got_it.set()

    def log_message(self, *a):   # שקט
        pass


def _wait_for_code(auth_url: str, server, timeout: float) -> str:
    """פותח דפדפן וממתין לקוד שגוגל מחזירה ל-loopback."""
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    server.got_it.wait(timeout)
    res = _OneShotHandler.result or {}
    if not res.get("code"):
        if res.get("error") == "access_denied":
            raise GoogleAuthError("ההתחברות בוטלה בדפדפן (לא אושרה הגישה).")
        raise GoogleAuthError(
            "לא התקבל אישור מגוגל בזמן. ודא שהדפדפן נפתח, בחר את חשבון הקופה, "
            "אשר את הגישה, ואז נסה שוב.")
    return res["code"]


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {"client_id": client_id, "redirect_uri": redirect_uri,
              "response_type": "code", "scope": " ".join(SCOPES),
              "access_type": "offline", "prompt": "consent",
              "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def _id_token_email(id_token: str) -> str:
    """כתובת המייל מתוך ה-id_token (JWT) — בלי בקשת רשת נוספת."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return (json.loads(base64.urlsafe_b64decode(payload)).get("email") or "").strip()
    except Exception:
        return ""


def connect(timeout: float = 240) -> str:
    """זרימת ההתחברות המלאה. חוסמת (להריץ ב-thread מה-UI). מחזירה את כתובת
    המייל שחוברה. מעלה GoogleAuthError בעברית בכל כישלון."""
    cid, sec = client_credentials()
    if not cid:
        raise GoogleAuthError(
            "החיבור לגוגל עדיין לא הופעל בגרסה זו של התוכנה (חסר זיהוי אפליקציה).")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    if _CODE_PROVIDER is not None:          # בדיקות
        redirect = "http://127.0.0.1:1/"
        code = _CODE_PROVIDER(build_auth_url(cid, redirect, state, challenge))
    else:
        server = http.server.HTTPServer(("127.0.0.1", 0), _OneShotHandler)
        server.expected_state = state
        server.got_it = threading.Event()
        _OneShotHandler.result = {}
        redirect = f"http://127.0.0.1:{server.server_port}/"
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            code = _wait_for_code(build_auth_url(cid, redirect, state, challenge),
                                  server, timeout)
        finally:
            try:
                server.server_close()
            except Exception:
                pass

    tok = _post_form(TOKEN_URL, {"code": code, "client_id": cid, "client_secret": sec,
                                 "redirect_uri": redirect,
                                 "grant_type": "authorization_code",
                                 "code_verifier": verifier})
    refresh = tok.get("refresh_token") or ""
    if not refresh:
        raise GoogleAuthError(
            "גוגל לא החזירה הרשאה קבועה. נסה שוב, ובמסך של גוגל ודא שסימנת את "
            "האישור לשליחת מיילים.")
    email = _id_token_email(tok.get("id_token") or "")
    if not email and tok.get("access_token"):
        st, raw = _http("GET", USERINFO_URL, None,
                        {"Authorization": "Bearer " + tok["access_token"]})
        if st == 200:
            try:
                email = (json.loads(raw).get("email") or "").strip()
            except Exception:
                email = ""
    db.set_setting(SET_REFRESH, refresh)
    db.set_setting(SET_EMAIL, email)
    _cache.update(token=tok.get("access_token") or "",
                  exp=time.time() + float(tok.get("expires_in") or 0) - 60)
    return email


def disconnect(revoke: bool = True):
    """ניתוק: מוחק את ההרשאה מקומית (ובסנכרון) ומבטל אותה בגוגל כמיטב היכולת."""
    refresh = (db.get_setting(SET_REFRESH) or "").strip()
    db.set_setting(SET_REFRESH, "")
    db.set_setting(SET_EMAIL, "")
    _cache.update(token="", exp=0.0)
    if revoke and refresh:
        try:
            _http("POST", REVOKE_URL, urllib.parse.urlencode({"token": refresh}).encode(),
                  {"Content-Type": "application/x-www-form-urlencoded"})
        except Exception:
            pass


def access_token(force: bool = False) -> str:
    """טוקן-גישה תקף; מרענן מה-refresh_token כשצריך."""
    if not force and _cache["token"] and time.time() < _cache["exp"]:
        return _cache["token"]
    refresh = (db.get_setting(SET_REFRESH) or "").strip()
    if not refresh:
        raise GoogleAuthError("חשבון Google לא מחובר — התחבר בהגדרות (\"התחבר עם Google\").")
    cid, sec = client_credentials()
    if not cid:
        raise GoogleAuthError("החיבור לגוגל לא הופעל בגרסה זו של התוכנה.")
    try:
        tok = _post_form(TOKEN_URL, {"client_id": cid, "client_secret": sec,
                                     "refresh_token": refresh,
                                     "grant_type": "refresh_token"})
    except GoogleAuthError as e:
        if "פג או בוטל" in str(e):
            # ההרשאה מתה בצד גוגל — לא להשאיר "מחובר" מטעה
            db.set_setting(SET_REFRESH, "")
        raise
    _cache.update(token=tok.get("access_token") or "",
                  exp=time.time() + float(tok.get("expires_in") or 3600) - 60)
    return _cache["token"]


# ─── Gmail API ────────────────────────────────────────────────────────────────

def gmail_send_raw(mime_bytes: bytes) -> str:
    """שולח הודעת MIME מוכנה דרך Gmail API. מחזיר את מזהה ההודעה.
    מעלה GoogleAuthError בעברית על כישלון (כתובת שגויה, מכסה, הרשאה)."""
    raw = base64.urlsafe_b64encode(mime_bytes).decode()
    body = json.dumps({"raw": raw}).encode()
    for attempt in (0, 1):
        tok = access_token(force=(attempt == 1))
        status, resp = _http("POST", GMAIL_SEND_URL, body,
                             {"Authorization": "Bearer " + tok,
                              "Content-Type": "application/json"})
        if status == 401 and attempt == 0:
            continue
        break
    if netblock.is_blocked(status) or netblock.is_blocked(resp):
        raise GoogleAuthError(netblock.explain(resp, netblock.NETFREE_MSG))
    try:
        data = json.loads(resp.decode("utf-8", "replace") or "{}")
    except Exception:
        data = {}
    if status == 200:
        return data.get("id") or ""
    msg = ((data.get("error") or {}).get("message") or "") if isinstance(data, dict) else ""
    low = msg.lower()
    if status == 400 and ("recipient" in low or "address" in low or "invalid to" in low):
        raise GoogleAuthError("כתובת המייל של הנמען שגויה.")
    if status == 403 and ("insufficient" in low or "scope" in low):
        raise GoogleAuthError("חסרה הרשאת שליחה — התנתק והתחבר מחדש לגוגל בהגדרות.")
    if status == 429 or "quota" in low or "limit" in low:
        raise GoogleAuthError("גוגל עצרה זמנית את השליחה (חריגה ממכסת המיילים היומית). נסה מחר.")
    if status == 401:
        raise GoogleAuthError("החיבור לגוגל פג — התחבר מחדש בהגדרות.")
    raise GoogleAuthError(f"השליחה דרך Gmail נכשלה ({status}): {msg or 'שגיאה לא ידועה'}")

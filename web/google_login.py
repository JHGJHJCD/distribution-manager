# -*- coding: utf-8 -*-
"""Entering the site with a Google account (the server stage).

Only the e-mail addresses that were allowed on the server enter:
    <python> -m web.auth allow <email> <name>      (also: disallow <email>, list)
Google is asked only who the person is ("openid email") — the site gets no access to his
mail, files or anything else.

Settings, from the environment (all three, or this way of entering is off):
    HALUKA_WEB_URL               the site's own address, e.g. https://haluka.example.org
    HALUKA_GOOGLE_CLIENT_ID      a "Web application" OAuth client of Google Cloud whose
    HALUKA_GOOGLE_CLIENT_SECRET  redirect address is  <HALUKA_WEB_URL>/auth/google/callback

The flow is the standard one (authorization code): the browser goes to Google with a random
`state` and `nonce` that are also kept in a short-lived cookie; Google sends it back with a
code; the SERVER exchanges the code with Google directly (so the answer needs no signature
check: it came over the encrypted connection from Google itself) and reads who it is.
"""
import base64
import hmac
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import auth

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_COOKIE = "__Host-haluka-g"      # lives for the few minutes of the visit to Google
STATE_SECONDS = 600
CALLBACK = "/auth/google/callback"


class Refused(Exception):
    """The person did not get in; `.why` is a fixed word for the login page (never a detail)."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def settings() -> dict:
    """{} unless all three settings are there and the address is https."""
    base = os.environ.get("HALUKA_WEB_URL", "").strip().rstrip("/")
    cid = os.environ.get("HALUKA_GOOGLE_CLIENT_ID", "").strip()
    secret = os.environ.get("HALUKA_GOOGLE_CLIENT_SECRET", "").strip()
    if not (base.startswith("https://") and cid and secret):
        return {}
    return {"base": base, "client_id": cid, "client_secret": secret, "redirect": base + CALLBACK}


def enabled() -> bool:
    return bool(settings())


def start() -> tuple:
    """(the address at Google to send the browser to, the value of the state cookie)."""
    cfg = settings()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "redirect_uri": cfg["redirect"], "response_type": "code",
        "scope": "openid email", "state": state, "nonce": nonce, "prompt": "select_account"})
    return f"{AUTH_URL}?{query}", f"{state}.{nonce}"


def fetch_token(code: str, cfg: dict) -> dict:
    """Exchange the code with Google, server to server. (The tests replace this one function.)"""
    body = urllib.parse.urlencode({
        "code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect"], "grant_type": "authorization_code"}).encode("ascii")
    request = urllib.request.Request(TOKEN_URL, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=15) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _claims(id_token: str) -> dict:
    part = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8"))


def _same(got: str, want: str) -> bool:
    return bool(got) and bool(want) and hmac.compare_digest(str(got), str(want))


def finish(code: str, state: str, cookie: str, now: datetime) -> tuple:
    """(session token, the person's name) — or Refused. `cookie` is what start() gave."""
    cfg = settings()
    if not cfg:
        raise Refused("off")
    want_state, _, want_nonce = (cookie or "").partition(".")
    if not code or not _same(state, want_state):
        raise Refused("again")                    # not the visit this browser started
    try:
        claims = _claims(fetch_token(code, cfg)["id_token"])
    except Exception:
        raise Refused("again")
    utc_now = datetime.now(timezone.utc).timestamp()
    if (claims.get("iss") not in ISSUERS or claims.get("aud") != cfg["client_id"]
            or not _same(claims.get("nonce", ""), want_nonce)
            or float(claims.get("exp", 0)) < utc_now):
        raise Refused("again")
    email = str(claims.get("email", "")).strip().casefold()
    if not email or claims.get("email_verified") not in (True, "true"):
        raise Refused("not_allowed")
    person = auth.google_allowed().get(email)
    if person is None:
        raise Refused("not_allowed")
    return auth.start_session(auth.GOOGLE_PREFIX + email, now), person["name"]

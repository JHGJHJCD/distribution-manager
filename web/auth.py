# -*- coding: utf-8 -*-
"""Who may enter the site once it is on the server.

On this computer (127.0.0.1) there is no login and nothing here is used. On the server
(`config.login_required()`) every page and every route answers only to someone who entered
with a name and a password.

- **Passwords** are kept only as a salted scrypt hash, in `users.json` in the data folder
  (never in git). They are set from the server's own terminal, never through the site:
      <python> -m web.auth set <name>        (asks for the password twice)
      <python> -m web.auth list | remove <name>
- **A session** is a long random token in a cookie; the server keeps only its SHA-256, in
  `auth.db` beside the site's database (a file of its own, so a backup holds no sessions and
  a restore logs nobody out). Leaving deletes it on the server, not only in the browser.
- **Wrong passwords** are counted per name: after MAX_FAILS within LOCK_MINUTES the name
  is locked for LOCK_MINUTES, even for the right password.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta

from . import config

COOKIE = "__Host-haluka"              # the prefix makes the browser insist on https and this host only
SESSION_DAYS = 30                     # a session ends this long after it was last used
MAX_FAILS = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
MAX_NAME = 40
MAX_PASSWORD = 200
_TOUCH = timedelta(minutes=10)        # "last used" is rewritten at most this often
_N, _R, _P, _LEN = 2 ** 14, 8, 1, 32  # scrypt

WRONG = "השם או הסיסמה לא נכונים"


class Locked(Exception):
    """Too many wrong passwords for this name; `.minutes` until it opens again."""

    def __init__(self, minutes: int):
        super().__init__(f"יותר מדי ניסיונות. אפשר לנסות שוב בעוד {minutes} דקות.")
        self.minutes = minutes


class Wrong(Exception):
    pass


# ── passwords ─────────────────────────────────────────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_LEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(want))
    except Exception:
        return False
    return hmac.compare_digest(got, want)


_DUMMY = hash_password(secrets.token_urlsafe(16))      # an unknown name costs the same time


# ── the users ─────────────────────────────────────────────────────────────────
def users_path() -> str:
    return os.path.join(config.data_dir(), "users.json")


def auth_db_path() -> str:
    return os.path.join(config.data_dir(), "auth.db")


def _key(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


def _private(path: str) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def users() -> dict:
    """{key: {"name": as typed when set, "hash": ...}}; empty when nobody was set yet."""
    try:
        with open(users_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.get("users", {}).items() if isinstance(v, dict) and v.get("hash")}
    except (OSError, ValueError):
        return {}


def _write_users(found: dict) -> None:
    os.makedirs(config.data_dir(), exist_ok=True)
    tmp = users_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"users": found}, f, ensure_ascii=False, indent=1)
    _private(tmp)
    os.replace(tmp, users_path())


def set_user(name: str, password: str) -> None:
    """Add a user or change his password. A new password ends every session he had."""
    key = _key(name)
    if not key or len(key) > MAX_NAME:
        raise ValueError("שם לא תקין")
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise ValueError(f"הסיסמה צריכה להיות באורך של {MIN_PASSWORD} תווים לפחות")
    found = users()
    found[key] = {"name": " ".join(name.split()), "hash": hash_password(password)}
    _write_users(found)
    end_sessions(key)


def remove_user(name: str) -> bool:
    found = users()
    if found.pop(_key(name), None) is None:
        return False
    _write_users(found)
    end_sessions(_key(name))
    return True


# ── sessions and wrong tries ──────────────────────────────────────────────────
def _db() -> sqlite3.Connection:
    os.makedirs(config.data_dir(), exist_ok=True)
    path = auth_db_path()
    fresh = not os.path.exists(path)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user TEXT NOT NULL, "
                 "created TEXT NOT NULL, last_seen TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS failures (user TEXT NOT NULL, at TEXT NOT NULL)")
    if fresh:
        _private(path)
    return conn


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def locked_minutes(conn, key: str, now: datetime) -> int:
    """0 when the name is open; otherwise the minutes until it opens again."""
    since = _stamp(now - timedelta(minutes=LOCK_MINUTES))
    rows = conn.execute("SELECT at FROM failures WHERE user = ? AND at > ? ORDER BY at DESC LIMIT ?",
                        (key, since, MAX_FAILS)).fetchall()
    if len(rows) < MAX_FAILS:
        return 0
    opens = datetime.strptime(rows[0][0], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=LOCK_MINUTES)
    return max(1, int((opens - now).total_seconds() + 59) // 60)


def login(name: str, password: str, now: datetime) -> tuple:
    """(token, the user's name). Raises Wrong or Locked; an unknown name and a wrong
    password are the same answer."""
    key = _key(name)[:MAX_NAME]
    conn = _db()
    try:
        minutes = locked_minutes(conn, key, now)
        if minutes:
            raise Locked(minutes)
        user = users().get(key)
        good = verify_password(password[:MAX_PASSWORD], user["hash"] if user else _DUMMY) and user is not None
        if not good:
            conn.execute("DELETE FROM failures WHERE at < ?", (_stamp(now - timedelta(days=1)),))
            conn.execute("INSERT INTO failures (user, at) VALUES (?, ?)", (key, _stamp(now)))
            raise Wrong(WRONG)
        conn.execute("DELETE FROM failures WHERE user = ?", (key,))
        conn.execute("DELETE FROM sessions WHERE last_seen < ?", (_stamp(now - timedelta(days=SESSION_DAYS)),))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (token_hash, user, created, last_seen) VALUES (?, ?, ?, ?)",
                     (_token_hash(token), key, _stamp(now), _stamp(now)))
        return token, user["name"]
    finally:
        conn.close()


def session_user(token: str, now: datetime) -> str:
    """The name of whoever holds this session, or '' — unknown, left, expired, or a user
    who was removed since."""
    if not token or len(token) > 200 or not os.path.exists(auth_db_path()):
        return ""
    conn = _db()
    try:
        row = conn.execute("SELECT user, last_seen FROM sessions WHERE token_hash = ?",
                           (_token_hash(token),)).fetchone()
        if not row:
            return ""
        key, seen = row[0], datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
        user = users().get(key)
        if user is None or now - seen > timedelta(days=SESSION_DAYS):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            return ""
        if now - seen > _TOUCH:
            conn.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (_stamp(now), _token_hash(token)))
        return user["name"]
    finally:
        conn.close()


def logout(token: str) -> None:
    if token and os.path.exists(auth_db_path()):
        conn = _db()
        try:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        finally:
            conn.close()


def end_sessions(key: str) -> None:
    if os.path.exists(auth_db_path()):
        conn = _db()
        try:
            conn.execute("DELETE FROM sessions WHERE user = ?", (key,))
        finally:
            conn.close()


# ── from the server's terminal ────────────────────────────────────────────────
def _main(argv: list) -> int:
    import getpass
    if len(argv) == 1 and argv[0] == "list":
        found = users()
        print("\n".join(u["name"] for u in found.values()) or "(no users yet)")
        return 0
    if len(argv) == 2 and argv[0] == "remove":
        print("removed" if remove_user(argv[1]) else "no such user")
        return 0
    if len(argv) == 2 and argv[0] == "set":
        first = getpass.getpass(f"Password for {argv[1]} (at least {MIN_PASSWORD} characters): ")
        if first != getpass.getpass("Again: "):
            print("The two passwords are not the same. Nothing was changed.")
            return 1
        try:
            set_user(argv[1], first)
        except ValueError as e:
            print(f"Nothing was changed: {e}")
            return 1
        print(f"Saved. {argv[1]} can enter with the new password; older sessions of this user were ended.")
        return 0
    print("usage: python -m web.auth set <name> | remove <name> | list")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

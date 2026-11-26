# -*- coding: utf-8 -*-
"""The daily copy that leaves the server goes to Google Drive, encrypted.

Connected from the settings screen ("חבר ל-Google Drive"), with the same Google client as the
login (web/google_login.py) and the narrowest permission Google has: `drive.file` — the site
sees ONLY the files it put there itself, nothing else of the Drive.

- Every copy is encrypted on the server before it leaves (Fernet: AES + a signature), so
  Google holds nothing readable. The key is made here on the first connection, shown ONCE on
  the screen for the owner to keep, and stays on the server for the daily run.
  **Without the key a backup cannot be opened** — not by Google, and not by us.
- Opening a backup that was downloaded from the Drive, on any computer:
      <python> -m web.drive open <file.enc> <new-file.db>      (asks for the key)
- Nothing is ever deleted from the Drive.

Kept in `drive.json` in the data folder (never in git, never in a backup, never sent to a page
except the key, once).
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import config, google_login

SCOPE = "https://www.googleapis.com/auth/drive.file"
CALLBACK = "/auth/drive/callback"
STATE_COOKIE = "__Host-haluka-d"
FOLDER_NAME = "גיבוי מנהל חלוקה"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,size,md5Checksum"


class Refused(Exception):
    pass


def state_path() -> str:
    return os.path.join(config.data_dir(), "drive.json")


def _read() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    os.makedirs(config.data_dir(), exist_ok=True)
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, state_path())


def _settings() -> dict:
    cfg = google_login.settings()
    return dict(cfg, redirect=cfg["base"] + CALLBACK) if cfg else {}


def available() -> bool:
    return bool(_settings())


def connected() -> bool:
    state = _read()
    return bool(state.get("refresh_token") and state.get("key"))


def view() -> dict:
    """What the settings screen gets. The key is in it only until the owner said he kept it."""
    state = _read()
    return {"available": available() and config.login_required(), "connected": connected(),
            "since": state.get("connected_at", ""),
            "key": state.get("key", "") if connected() and not state.get("key_kept") else ""}


def key_kept() -> dict:
    state = _read()
    if state.get("key"):
        state["key_kept"] = True
        _write(state)
    return view()


def disconnect() -> dict:
    """Stop sending. The key stays on the server: the copies already on the Drive need it."""
    state = _read()
    state.pop("refresh_token", None)
    state.pop("folder_id", None)
    _write(state)
    return view()


# ── connecting ────────────────────────────────────────────────────────────────
def start() -> tuple:
    cfg = _settings()
    if not cfg:
        raise Refused("off")
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "redirect_uri": cfg["redirect"], "response_type": "code",
        "scope": SCOPE, "state": state, "access_type": "offline", "prompt": "consent"})
    return f"{google_login.AUTH_URL}?{query}", state


def finish(code: str, state: str, cookie: str, now: datetime) -> None:
    cfg = _settings()
    if not cfg or not code or not google_login._same(state, cookie):
        raise Refused("again")
    try:
        answer = google_login.fetch_token(code, cfg)
    except Exception:
        raise Refused("again")
    if not answer.get("refresh_token") or SCOPE not in str(answer.get("scope", "")).split():
        raise Refused("no_permission")              # the permission box was not ticked at Google
    saved = _read()
    if not saved.get("key"):
        from cryptography.fernet import Fernet
        saved["key"] = Fernet.generate_key().decode("ascii")
        saved["key_kept"] = False
    saved.update(refresh_token=answer["refresh_token"], connected_at=now.strftime("%Y-%m-%d %H:%M"))
    saved.pop("folder_id", None)                    # another account may have been chosen
    _write(saved)


# ── sending ───────────────────────────────────────────────────────────────────
def _http(method: str, url: str, headers: dict, body: bytes = None) -> tuple:
    """(status, body). The one place that talks to Google; the tests replace it."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _json(method, url, headers, body=None) -> dict:
    status, raw = _http(method, url, headers, body)
    if status >= 300:
        raise OSError(f"Google Drive answered {status}")
    return json.loads(raw.decode("utf-8"))


def _access_token(cfg: dict, state: dict) -> str:
    body = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                   "refresh_token": state["refresh_token"], "grant_type": "refresh_token"}).encode()
    status, raw = _http("POST", google_login.TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status >= 300:
        raise OSError("the connection to Google Drive is no longer valid (connect again from the settings screen)")
    return json.loads(raw.decode("utf-8"))["access_token"]


def _multipart(meta: dict, content: bytes) -> tuple:
    edge = "haluka" + secrets.token_hex(12)
    body = (f"--{edge}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{edge}\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8") + content + f"\r\n--{edge}--".encode()
    return body, f"multipart/related; boundary={edge}"


def encrypt(plain: bytes, key: str) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key.encode("ascii")).encrypt(plain)


def decrypt(sealed: bytes, key: str) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key.strip().encode("ascii")).decrypt(sealed)


def _arrived(done: dict, sealed: bytes) -> bool:
    return done.get("md5Checksum") == hashlib.md5(sealed).hexdigest() and int(done.get("size", -1)) == len(sealed)


def send(path: str) -> None:
    """Encrypt the file, put it in the site's folder on the Drive, and check what arrived."""
    cfg, state = _settings(), _read()
    if not cfg or not connected():
        raise OSError("Google Drive is not connected")
    with open(path, "rb") as f:
        sealed = encrypt(f.read(), state["key"])
    auth = {"Authorization": "Bearer " + _access_token(cfg, state)}
    if not state.get("folder_id"):
        made = _json("POST", API + "?fields=id", dict(auth, **{"Content-Type": "application/json; charset=UTF-8"}),
                     json.dumps({"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}).encode("utf-8"))
        state["folder_id"] = made["id"]
        _write(state)
    body, kind = _multipart({"name": os.path.basename(path) + ".enc", "parents": [state["folder_id"]]}, sealed)
    done = _json("POST", UPLOAD, dict(auth, **{"Content-Type": kind}), body)
    if not _arrived(done, sealed):
        raise OSError("the copy that arrived at Google Drive is not the same as the one that was sent")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "open":
        import getpass
        try:
            with open(sys.argv[2], "rb") as f:
                plain = decrypt(f.read(), getpass.getpass("The recovery key: "))
        except Exception:
            print("Could not open the file: the key is wrong, or the file is damaged.")
            sys.exit(1)
        with open(sys.argv[3], "xb") as f:
            f.write(plain)
        print("Opened:", sys.argv[3])
        sys.exit(0)
    print("usage: python -m web.drive open <file.enc> <new-file.db>")
    sys.exit(2)

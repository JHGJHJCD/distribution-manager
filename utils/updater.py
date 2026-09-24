"""Built-in updater — checks GitHub Releases and self-replaces the EXE.

Uses only the standard library (urllib/json/ssl) so no extra dependency is
bundled. Network work is meant to be driven from a worker thread by the UI so
the interface never blocks. The self-replace uses the standard Windows trick of
renaming the running EXE (allowed) and dropping the new one in its place.
"""
import os
import sys
import json
import ssl
import subprocess
import urllib.request
import urllib.error

REPO = "JHGJHJCD/distribution-manager"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_UA = "ManhalHaluka-Updater"
_DOWNLOAD_NAME = "update_download.exe"


# ─── version comparison ───────────────────────────────────────────────────────

def parse_version(s: str) -> tuple:
    """'v1.2' / '1.2.3' → (1,2) / (1,2,3). Non-numeric parts become 0."""
    s = (s or "").strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_version(remote), parse_version(local)
    n = max(len(r), len(l))
    r += (0,) * (n - len(r))
    l += (0,) * (n - len(l))
    return r > l


# ─── GitHub release lookup ────────────────────────────────────────────────────

def _ssl_ctx():
    try:
        return ssl.create_default_context()
    except Exception:
        return None


_ETAGS: dict = {}      # url → (etag, parsed json) — v3.51 conditional requests


def _get_json(url: str, timeout: int):
    """GET a GitHub API url with `If-None-Match`. A 304 answer does not count
    against GitHub's 60 requests/hour per address (the app polls every 2 min
    from two computers that may share one connection — without this, the
    quota could run out and updates would go unnoticed for the rest of the
    hour). Raises on network error / HTTP error other than 304."""
    headers = {"User-Agent": _UA, "Accept": "application/vnd.github+json"}
    cached = _ETAGS.get(url)
    if cached:
        headers["If-None-Match"] = cached[0]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            etag = resp.headers.get("ETag") or ""
    except urllib.error.HTTPError as e:
        if e.code == 304 and cached:
            return cached[1]
        raise
    if etag:
        _ETAGS[url] = (etag, data)
    return data


def check_latest(timeout: int = 10):
    """Return dict {version, tag, url, size, notes} for the latest release, or
    None if it cannot be determined / has no .exe asset. Raises on network error."""
    data = _get_json(API_LATEST, timeout)

    tag = data.get("tag_name") or ""
    # prefer the canonical asset name, else the first .exe
    assets = data.get("assets", []) or []
    asset = next((a for a in assets if str(a.get("name", "")) == "Manhal-Haluka.exe"), None)
    if asset is None:
        asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    if asset is None:
        return None
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "url": asset.get("browser_download_url"),
        "size": int(asset.get("size", 0) or 0),
        "notes": data.get("body", "") or "",
    }


API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=100"


def fetch_download_stats(timeout: int = 10) -> dict:
    """{tag: exe-download-count} for the recent releases — GitHub counts every
    download of the release asset (auto-updates by the app included). Used by
    the manager machine to notice 'someone downloaded a version' (v2.96).
    Raises on network error (caller stays silent)."""
    data = _get_json(API_RELEASES, timeout)
    out = {}
    for rel in data or []:
        tag = str(rel.get("tag_name") or "")
        if not tag:
            continue
        out[tag] = sum(int(a.get("download_count") or 0)
                       for a in rel.get("assets") or []
                       if str(a.get("name", "")).lower().endswith(".exe"))
    return out


def record_self_download(tag: str):
    """v3.40: remember that THIS computer downloaded release `tag` itself
    (auto-update), as a synced per-device setting `self_dl_<device>` =
    {tag: count}. The manager machine subtracts these from the GitHub
    counters so only downloads by OTHER people trigger a balloon."""
    if not tag:
        return
    try:
        import database as db
        from utils import sync
        key = "self_dl_" + sync.device_id()
        try:
            cur = json.loads(db.get_setting(key) or "{}")
        except Exception:
            cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur[tag] = int(cur.get(tag) or 0) + 1
        db.set_setting(key, json.dumps(cur, ensure_ascii=False))
    except Exception:
        pass


def self_download_totals(rows) -> dict:
    """Sum the per-device `self_dl_*` settings → {tag: count}."""
    out = {}
    for _key, val in rows or []:
        try:
            d = json.loads(val or "{}")
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for tag, n in d.items():
            out[tag] = out.get(tag, 0) + int(n or 0)
    return out


def others_downloads(stats: dict, self_totals: dict) -> dict:
    """GitHub counters minus our own auto-update downloads (never below 0)."""
    return {tag: max(0, int(n) - int(self_totals.get(tag) or 0))
            for tag, n in (stats or {}).items()}


# ─── download ─────────────────────────────────────────────────────────────────

def download(url: str, dest: str, progress_cb=None, cancel_cb=None, timeout: int = 30) -> str:
    """Stream `url` to `dest`. progress_cb(percent) is called as data arrives;
    cancel_cb() returning True aborts (partial file is removed). Returns dest."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                if cancel_cb and cancel_cb():
                    f.close()
                    try:
                        os.remove(dest)
                    except OSError:
                        pass
                    raise InterruptedError("בוטל על ידי המשתמש")
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(min(100, int(done * 100 / total)))
    # Guard against a truncated download silently replacing the running EXE.
    if total and os.path.getsize(dest) != total:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise IOError("ההורדה לא הושלמה במלואה — נסה שוב")
    return dest


# ─── self-replace ─────────────────────────────────────────────────────────────

def current_exe():
    """Path to the running EXE, or None when running from source (dev)."""
    return sys.executable if getattr(sys, "frozen", False) else None


def download_dir() -> str:
    exe = current_exe()
    return os.path.dirname(exe) if exe else os.getcwd()


def download_target() -> str:
    return os.path.join(download_dir(), _DOWNLOAD_NAME)


def cleanup_old():
    """Best-effort removal of the previous EXE left behind by an update."""
    exe = current_exe()
    if not exe:
        return
    for stale in (exe + ".old", download_target()):
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass


def apply_update(downloaded_path: str):
    """Swap the running EXE for the downloaded one and relaunch.
    Returns None on success (caller should exit) or an error string."""
    exe = current_exe()
    if not exe:
        return "עדכון אוטומטי זמין רק בגרסת התוכנה (EXE)."
    if not (downloaded_path and os.path.exists(downloaded_path)):
        return "קובץ העדכון לא נמצא."

    old = exe + ".old"
    try:
        if os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
        os.replace(exe, old)              # rename the running EXE (OK on Windows)
        os.replace(downloaded_path, exe)  # move the new EXE into place
    except OSError as e:
        # roll back if the original name ended up missing
        try:
            if not os.path.exists(exe) and os.path.exists(old):
                os.replace(old, exe)
        except OSError:
            pass
        return f"לא ניתן להחליף את קובץ התוכנה: {e}"

    env = _child_env()
    # #dy6yq (23/9/2026): the user already typed the password in THIS session —
    # the relaunched build lets them straight in, once, via a one-time token.
    token = arm_autologin()
    if token:
        env[AUTOLOGIN_ENV] = token
    if not _relaunch(exe, env):
        return "העדכון הותקן, אך ההפעלה מחדש נכשלה. הפעל את התוכנה ידנית."
    return None


def _relaunch(exe: str, env: dict) -> bool:
    """Start the updated EXE as a fully independent process that survives this
    one's exit. Returns True on success.

    Two hard-won robustness points (the 'closes but never reopens' report,
    24/9/2026):
    • creationflags DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — without them the
      child stays tied to this process's console/group, and our immediate hard
      exit could take it down before its window ever appears.
    • retry + ShellExecute fallback — the EXE was written to disk milliseconds
      ago, and an on-access scanner (NetFree / Defender) can hold a brief lock on
      it, so the first Popen can fail with a sharing violation. We retry, then
      fall back to os.startfile (the double-click path, very tolerant). The
      fallback cannot carry the auto-login env var, so the user is asked for the
      password once — reopening beats not reopening."""
    import time
    flags = 0
    if sys.platform == "win32":
        # 0x08 DETACHED_PROCESS | 0x200 CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200
    for attempt in range(6):
        try:
            subprocess.Popen([exe], close_fds=True, env=env, creationflags=flags)
            return True
        except OSError:
            time.sleep(0.4)
    try:
        os.startfile(exe)   # Windows ShellExecute — reopens without the token
        return True
    except (OSError, AttributeError):
        return False


# ─── one-time auto-login after a self-update (#dy6yq) ─────────────────────────
AUTOLOGIN_ENV = "MH_AUTOLOGIN"
AUTOLOGIN_MAX_AGE_S = 180


def _autologin_path() -> str:
    import database as db
    return os.path.join(os.path.dirname(db.DB_PATH), "autologin.token")


def arm_autologin() -> str:
    """Write a fresh one-time token next to the DB and return it ('' on failure).
    The relaunched process must present the SAME token in its environment
    within AUTOLOGIN_MAX_AGE_S — the file is deleted on first use, so it can't
    be replayed, and a stale file is ignored."""
    import secrets, time
    token = secrets.token_hex(16)
    try:
        with open(_autologin_path(), "w", encoding="utf-8") as f:
            f.write(f"{token} {int(time.time())}")
    except OSError:
        return ""
    return token


def autologin_pending() -> bool:
    """True when this process was launched by a self-update relaunch (the env
    token is present) — WITHOUT consuming it. Lets startup shorten the splash so
    the reopen after an update feels instant."""
    return bool(os.environ.get(AUTOLOGIN_ENV))


def consume_autologin() -> bool:
    """True exactly once, right after a self-update relaunch, if the env token
    matches the fresh file. Always removes the file."""
    import time
    token = os.environ.pop(AUTOLOGIN_ENV, "")
    path = _autologin_path()
    try:
        with open(path, encoding="utf-8") as f:
            saved, ts = f.read().split()
    except (OSError, ValueError):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        fresh = (time.time() - int(ts)) <= AUTOLOGIN_MAX_AGE_S
    except ValueError:
        return False
    return bool(token) and token == saved and fresh


# ─── relaunch environment ─────────────────────────────────────────────────────

# PyInstaller onefile marks its extraction with these env vars. If the freshly
# launched EXE inherits them, its bootloader thinks it is already a "second
# stage" and re-uses the CURRENT process's _MEI temp dir instead of extracting
# its own. When this (old) process then exits, its bootloader deletes that _MEI,
# and the new process dies on its first lazy import — the FileNotFoundError from
# zipimport at startup that appeared after every update. Scrubbing them forces a
# clean, independent extraction for the child.
_PYI_ENV_VARS = (
    "_MEIPASS2",                  # classic (<6)
    "_PYI_ARCHIVE_FILE",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_PARENT_PID",
    "_PYI_ONEFILE_TEMPDIR",
    "_PYI_SPLASH_IPC",
    "_PYI_LINK_TARGET",
)


def _child_env():
    env = dict(os.environ)
    for var in _PYI_ENV_VARS:
        env.pop(var, None)
    return env

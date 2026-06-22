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


def check_latest(timeout: int = 10):
    """Return dict {version, tag, url, size, notes} for the latest release, or
    None if it cannot be determined / has no .exe asset. Raises on network error."""
    req = urllib.request.Request(
        API_LATEST,
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        data = json.loads(resp.read().decode("utf-8"))

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

    try:
        subprocess.Popen([exe], close_fds=True)
    except OSError as e:
        return f"העדכון הותקן, אך ההפעלה מחדש נכשלה. הפעל את התוכנה ידנית.\n({e})"
    return None

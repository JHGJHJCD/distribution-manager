# -*- coding: utf-8 -*-
"""Verify the in-app updater: version compare, GitHub check, download, and the
self-replace swap (simulated — never touches the real EXE)."""
import os, sys, tempfile, shutil
os.environ["PYTHONUTF8"] = "1"
from utils import updater

ok = True
def check(label, cond):
    global ok; ok = ok and cond
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")

# ── 1. version comparison ──────────────────────────────────────────────────────
check("v1.1 > v1.0", updater.is_newer("1.1", "1.0"))
check("v1.0 not > v1.1", not updater.is_newer("1.0", "1.1"))
check("v1.0 not > v1.0", not updater.is_newer("1.0", "1.0"))
check("v2.0 > v1.9", updater.is_newer("2.0", "1.9"))
check("v1.10 > v1.9 (numeric, not lexical)", updater.is_newer("1.10", "1.9"))
check("'v1.2.1' > '1.2'", updater.is_newer("v1.2.1", "1.2"))
check("parse strips v", updater.parse_version("v1.2") == (1, 2))

# ── 2. live GitHub check ───────────────────────────────────────────────────────
try:
    latest = updater.check_latest(timeout=15)
    check("check_latest returned a release", isinstance(latest, dict))
    if isinstance(latest, dict):
        check("has a version", bool(latest.get("version")))
        check("asset url is an .exe on the repo",
              str(latest.get("url", "")).endswith(".exe") and "distribution-manager" in latest.get("url", ""))
        print(f"       latest on GitHub: v{latest.get('version')}  size={latest.get('size')}  url={latest.get('url')}")
except Exception as e:
    check(f"check_latest network call (got: {type(e).__name__}: {e})", False)

# ── 3. download a small file with progress ─────────────────────────────────────
WORK = os.path.join(tempfile.gettempdir(), "upd_test"); shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
seen = {"max": 0}
try:
    dest = os.path.join(WORK, "small.json")
    updater.download("https://api.github.com/repos/JHGJHJCD/distribution-manager",
                     dest, progress_cb=lambda p: seen.__setitem__("max", max(seen["max"], p)))
    check("download wrote a non-empty file", os.path.exists(dest) and os.path.getsize(dest) > 0)
except Exception as e:
    check(f"download small file (got {type(e).__name__}: {e})", False)

# cancel mid-download removes the partial file
try:
    dest2 = os.path.join(WORK, "cancel.bin")
    updater.download("https://api.github.com/repos/JHGJHJCD/distribution-manager",
                     dest2, cancel_cb=lambda: True)
    check("cancel should have raised", False)
except InterruptedError:
    check("cancel raised InterruptedError + removed partial", not os.path.exists(dest2))
except Exception as e:
    check(f"cancel raised unexpected {type(e).__name__}", False)

# ── 4. self-replace swap (simulated) ───────────────────────────────────────────
fake_exe = os.path.join(WORK, "app.exe")
with open(fake_exe, "w") as f: f.write("OLD-BINARY")
new_dl = os.path.join(WORK, "update_download.exe")
with open(new_dl, "w") as f: f.write("NEW-BINARY")

_orig_current = updater.current_exe
_orig_popen = updater.subprocess.Popen
updater.current_exe = lambda: fake_exe
launched = {"called": False}
updater.subprocess.Popen = lambda *a, **k: launched.__setitem__("called", True)
try:
    err = updater.apply_update(new_dl)
    check("apply_update returned no error", err is None)
    check("exe now holds the NEW binary", open(fake_exe).read() == "NEW-BINARY")
    check("old binary preserved as .old", os.path.exists(fake_exe + ".old") and open(fake_exe + ".old").read() == "OLD-BINARY")
    check("relaunch was invoked", launched["called"])
    # cleanup_old removes the .old
    updater.cleanup_old()
    check("cleanup_old removed the .old file", not os.path.exists(fake_exe + ".old"))
finally:
    updater.current_exe = _orig_current
    updater.subprocess.Popen = _orig_popen


# ── #dy6yq (v3.64): one-time auto-login right after a self-update relaunch ──
import time as _time
_tmpdir = tempfile.mkdtemp()
updater._autologin_path = lambda: os.path.join(_tmpdir, "autologin.token")
os.environ.pop(updater.AUTOLOGIN_ENV, None)
check("AL1 no token file -> no auto-login", updater.consume_autologin() is False)
tok = updater.arm_autologin()
check("AL2 arm writes a 32-hex token", len(tok) == 32 and os.path.exists(updater._autologin_path()))
os.environ[updater.AUTOLOGIN_ENV] = "wrong"
check("AL3 wrong env token -> refused, file consumed",
      updater.consume_autologin() is False and not os.path.exists(updater._autologin_path()))
tok = updater.arm_autologin(); os.environ[updater.AUTOLOGIN_ENV] = tok
check("AL4 matching fresh token -> auto-login once", updater.consume_autologin() is True)
check("AL5 and never twice (file gone, env popped)",
      updater.consume_autologin() is False and updater.AUTOLOGIN_ENV not in os.environ)
tok = updater.arm_autologin(); os.environ[updater.AUTOLOGIN_ENV] = tok
with open(updater._autologin_path(), "w", encoding="utf-8") as _f:
    _f.write(f"{tok} {int(_time.time()) - updater.AUTOLOGIN_MAX_AGE_S - 5}")
check("AL6 stale token (older than the window) -> refused", updater.consume_autologin() is False)
shutil.rmtree(_tmpdir, ignore_errors=True)

# ── reopen robustness (24/9/2026): retry + detach flags + ShellExecute fallback ──
import time as _t2
_orig_sleep = _t2.sleep
_t2.sleep = lambda *_a, **_k: None      # don't actually wait during the retries
_orig_popen2 = updater.subprocess.Popen
_orig_startfile = getattr(updater.os, "startfile", None)

# 1) Popen succeeds → returns True and (on win32) passes detach creationflags.
captured = {}
def _fake_popen_ok(*a, **k):
    captured.update(k); return object()
updater.subprocess.Popen = _fake_popen_ok
check("RL1 relaunch True when spawn succeeds", updater._relaunch("x.exe", {}) is True)
if sys.platform == "win32":
    check("RL2 spawn is detached (creationflags set)", bool(captured.get("creationflags")))

# 2) Popen always fails → retries, then falls back to ShellExecute (os.startfile).
tries = {"n": 0}
def _fake_popen_fail(*a, **k):
    tries["n"] += 1; raise OSError(32, "locked by scanner")
updater.subprocess.Popen = _fake_popen_fail
sf = {"called": False}
updater.os.startfile = lambda *a, **k: sf.__setitem__("called", True)
check("RL3 fallback reopens when spawn keeps failing", updater._relaunch("x.exe", {}) is True)
check("RL4 it retried the direct spawn before falling back", tries["n"] >= 2)
check("RL5 fallback used ShellExecute", sf["called"] is True)

# 3) both paths fail → False (caller shows 'launch manually').
updater.os.startfile = lambda *a, **k: (_ for _ in ()).throw(OSError("no shell"))
check("RL6 returns False only when every launch path fails",
      updater._relaunch("x.exe", {}) is False)

# 4) autologin_pending peeks at the env without consuming it.
updater.os.environ.pop(updater.AUTOLOGIN_ENV, None)
check("RL7 pending False without env token", updater.autologin_pending() is False)
updater.os.environ[updater.AUTOLOGIN_ENV] = "abc"
check("RL8 pending True with env token (not consumed)",
      updater.autologin_pending() is True and updater.os.environ.get(updater.AUTOLOGIN_ENV) == "abc")
updater.os.environ.pop(updater.AUTOLOGIN_ENV, None)

updater.subprocess.Popen = _orig_popen2
if _orig_startfile is not None:
    updater.os.startfile = _orig_startfile
_t2.sleep = _orig_sleep

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)

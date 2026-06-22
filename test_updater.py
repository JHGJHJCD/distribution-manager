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

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)

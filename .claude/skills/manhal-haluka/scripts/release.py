#!/usr/bin/env python3
"""End-to-end release orchestrator for מנהל חלוקה.

Runs the exact, easy-to-fat-finger release chain deterministically and aborts on
the first failure so no step is ever skipped. Output is kept ASCII so it reads
correctly in the Windows terminal (which mojibakes Hebrew).

Usage (run with ANY python; it re-dispatches build/test to the pinned 3.12):
    python release.py test                       # run the standalone test suite
    python release.py build                      # build EXE + ASCII copy (local verify)
    python release.py bump 2.79                  # rewrite APP_VERSION only
    python release.py ship 2.79 -m "commit msg"  # bump -> test -> build -> commit/push -> gh release

`ship` is the only outward-facing command (push + publish). Confirm the version and
commit message with the user before running it, unless they already said "release it".
"""
import argparse
import os
import re
import subprocess
import sys

# --- Pinned locations (see CLAUDE.md / SKILL.md) --------------------------------
REPO = r"C:\Users\יהודה\Desktop\מנהל_חלוקה"
PY312 = r"C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe"
GH = r"C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe"
SPEC = "מנהל_חלוקה.spec"
EXE_SRC = os.path.join("dist", "מנהל_חלוקה.exe")
EXE_ASCII = os.path.join("dist", "Manhal-Haluka.exe")
GH_REPO = "JHGJHJCD/distribution-manager"
VERSION_FILE = "version.py"

# Test files to run for a release. Keep in sync with the repo's test_*.py set.
TESTS = [
    "test_all.py", "test_deep.py", "test_selection.py", "test_data_safety.py",
    "test_scenarios.py", "test_search.py", "test_priority_import.py",
    "test_volunteer_flow.py", "test_updater.py", "test_sync.py",
    "test_score_scale.py", "test_fixes.py",
]


def log(msg):
    print("[release] " + msg, flush=True)


def die(msg, code=1):
    print("[release][FAIL] " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def run(cmd, **kw):
    """Run a command, streaming output; raise on non-zero."""
    log("$ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=REPO, check=True, **kw)


# --- Steps ----------------------------------------------------------------------
def read_version():
    with open(os.path.join(REPO, VERSION_FILE), encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', txt)
    if not m:
        die("could not find APP_VERSION in version.py")
    return m.group(1)


def bump(version):
    path = os.path.join(REPO, VERSION_FILE)
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    new = re.sub(r'(APP_VERSION\s*=\s*")[^"]+(")', r"\g<1>" + version + r"\g<2>", txt, count=1)
    if new == txt:
        die("APP_VERSION unchanged — check version.py format")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    log("bumped APP_VERSION -> " + version)


def test():
    failed = []
    for t in TESTS:
        if not os.path.exists(os.path.join(REPO, t)):
            log("skip (missing): " + t)
            continue
        log("running " + t)
        env = dict(os.environ, PYTHONUTF8="1")
        r = subprocess.run([PY312, t], cwd=REPO, env=env)
        if r.returncode != 0:
            failed.append(t)
            log("  -> FAILED (" + str(r.returncode) + ")")
        else:
            log("  -> ok")
    if failed:
        die("tests failed: " + ", ".join(failed))
    log("all tests passed")


def build():
    # Unlock a running EXE (WinError 5) before building.
    for p in (EXE_SRC, EXE_ASCII):
        fp = os.path.join(REPO, p)
        if os.path.exists(fp):
            try:
                os.remove(fp)
                log("removed stale " + p)
            except OSError as e:
                die("cannot remove locked EXE (" + p + ") — close the running app: " + str(e))
    run([PY312, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC])
    if not os.path.exists(os.path.join(REPO, EXE_SRC)):
        die("build finished but " + EXE_SRC + " is missing")
    # ASCII copy for the updater asset.
    import shutil
    shutil.copyfile(os.path.join(REPO, EXE_SRC), os.path.join(REPO, EXE_ASCII))
    log("copied -> " + EXE_ASCII)


def ship(version, message):
    bump(version)
    test()
    build()
    tag = "v" + version
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", message])   # commit-msg hook strips any Claude credit
    run(["git", "push"])
    run([GH, "release", "create", tag, EXE_ASCII, "--repo", GH_REPO,
         "--latest", "--title", tag, "--notes", message])
    log("released " + tag + " with asset " + EXE_ASCII)


# --- CLI ------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="מנהל חלוקה release orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    sub.add_parser("build")
    b = sub.add_parser("bump"); b.add_argument("version")
    s = sub.add_parser("ship")
    s.add_argument("version")
    s.add_argument("-m", "--message", required=True)
    args = p.parse_args()

    if args.cmd == "test":
        test()
    elif args.cmd == "build":
        build()
    elif args.cmd == "bump":
        bump(args.version)
    elif args.cmd == "ship":
        ship(args.version, args.message)
    log("done: " + args.cmd)


if __name__ == "__main__":
    main()

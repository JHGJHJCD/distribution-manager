#!/usr/bin/env python3
"""End-to-end release orchestrator for מנהל חלוקה.

Runs the exact, easy-to-fat-finger release chain deterministically and aborts on
the first failure so no step is ever skipped. Output is kept ASCII so it reads
correctly in the Windows terminal (which mojibakes Hebrew).

Usage (run with ANY python; it re-dispatches build/test to the pinned 3.12):
    python release.py test                       # run the standalone test suite
    python release.py build                      # build EXE + ASCII copy (local verify)
    python release.py bump 2.79                  # rewrite APP_VERSION only
    python release.py ship 2.79 -m "commit msg"  # bump -> test -> commit/push -> tag; the EXE is built + released in the GitHub cloud
    python release.py ship 2.79 -m "..." --local # old flow: build here + gh release create

`ship` is the only outward-facing command (push + publish). Confirm the version and
commit message with the user before running it, unless they already said "release it".
"""
import argparse
import os
import re
import subprocess
import sys

# --- Pinned locations (see CLAUDE.md / SKILL.md) --------------------------------
# Resolved from this file's location / the running interpreter so the same script
# also runs inside the GitHub Actions build (.github/workflows/build.yml); on this
# machine the pinned paths win.
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
_PY312_LOCAL = r"C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe"
PY312 = _PY312_LOCAL if os.path.exists(_PY312_LOCAL) else sys.executable
_GH_LOCAL = r"C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe"
GH = _GH_LOCAL if os.path.exists(_GH_LOCAL) else "gh"
SPEC = "מנהל_חלוקה.spec"
EXE_SRC = os.path.join("dist", "מנהל_חלוקה.exe")
EXE_ASCII = os.path.join("dist", "Manhal-Haluka.exe")
GH_REPO = "JHGJHJCD/distribution-manager"
VERSION_FILE = "version.py"

# Test files to run for a release. Keep in sync with the repo's test_*.py set.
TESTS = [
    "test_all.py", "test_deep.py", "test_selection.py", "test_data_safety.py",
    "test_scenarios.py", "test_search.py", "test_priority_import.py",
    "test_volunteer_flow.py", "test_updater.py", "test_sync.py", "test_sync_resilience.py",
    "test_score_scale.py", "test_fixes.py", "test_tzintuk.py", "test_tts.py",
    "test_mail.py", "test_callback_server.py", "test_refresh.py",
    "test_calendar_today.py", "test_hebrew_buttons.py", "test_onetime_button.py",
    "test_card_print.py", "test_mode_reset.py", "test_status_simple.py",
    "test_merge_same_name.py", "test_products_limit.py", "test_settings_report.py", "test_group_report.py",
    "test_bonus_dist.py", "test_date_follow.py", "test_plan_selection.py",
    "test_plans.py", "test_plan_screen.py",
]


# The Windows console is cp1255: a character outside it (✓, ☑, emoji) in a commit
# message crashed the log line *between build and commit* (v3.55). Logging must
# never be able to abort a release — unencodable characters become "?".
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:                                  # noqa: BLE001
        pass


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
        # Already at this version (e.g. bumped in the working tree earlier) is fine;
        # only a missing/odd APP_VERSION line is an error.
        if re.search(r'APP_VERSION\s*=\s*"' + re.escape(version) + '"', txt):
            log("APP_VERSION already " + version)
            return
        die("APP_VERSION unchanged — check version.py format")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    log("bumped APP_VERSION -> " + version)


# Tests that read a private file that exists only on Yehuda's computer (real
# recipient data, never in git). They still run locally in `ship`; in the GitHub
# cloud build they are skipped on purpose and the log says so.
LOCAL_ONLY_TESTS = {"test_priority_import.py"}


def test():
    failed = []
    in_cloud = os.environ.get("GITHUB_ACTIONS") == "true"
    for t in TESTS:
        if not os.path.exists(os.path.join(REPO, t)):
            log("skip (missing): " + t)
            continue
        if in_cloud and t in LOCAL_ONLY_TESTS:
            log("skip (needs a private local file, runs on Yehuda's computer only): " + t)
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


def gen_changelog(version=None, message=None):
    """Regenerate changelog.txt (bundled into the EXE; shown in Settings →
    "יומן שינויים"). The commit being shipped is not in git yet, so its own
    note is prepended explicitly."""
    cmd = [PY312, os.path.join("dev", "gen_changelog.py")]
    if version and message:
        cmd += ["--prepend", version, message]
    env = dict(os.environ, PYTHONUTF8="1")
    run(cmd, env=env)


def ship(version, message, local=False):
    """Default = cloud build: tests here, then commit + push + push the tag; the
    GitHub Actions workflow (build.yml) builds the EXE and creates the Release.
    `local=True` keeps the old flow (build on this machine + gh release create)."""
    bump(version)
    gen_changelog(version, message)   # before the build so the EXE carries it
    test()
    tag = "v" + version
    if local:
        build()
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", message])   # commit-msg hook strips any Claude credit
    run(["git", "push"])
    if local:
        run([GH, "release", "create", tag, EXE_ASCII, "--repo", GH_REPO,
             "--latest", "--title", tag, "--notes", message])
        log("released " + tag + " with asset " + EXE_ASCII)
        return
    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])
    log("tag pushed; waiting for the cloud build (build.yml)")
    watch_cloud_build(tag)


def watch_cloud_build(tag):
    """Follow the Actions run that the tag push started; fail if it fails."""
    import time
    run_id = None
    for _ in range(12):
        r = subprocess.run(
            [GH, "run", "list", "--repo", GH_REPO, "--workflow", "build.yml",
             "--branch", tag, "--limit", "1", "--json", "databaseId", "-q", ".[0].databaseId"],
            cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            run_id = r.stdout.strip()
            break
        time.sleep(5)
    if not run_id:
        die("cloud run not found — check https://github.com/" + GH_REPO + "/actions")
    log("cloud run: https://github.com/" + GH_REPO + "/actions/runs/" + run_id)
    run([GH, "run", "watch", run_id, "--repo", GH_REPO, "--exit-status", "--interval", "15"])
    log("released " + tag + " (built in the cloud)")


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
    s.add_argument("--local", action="store_true",
                   help="build on this machine instead of the GitHub cloud")
    args = p.parse_args()

    if args.cmd == "test":
        test()
    elif args.cmd == "build":
        build()
    elif args.cmd == "bump":
        bump(args.version)
    elif args.cmd == "ship":
        ship(args.version, args.message, local=args.local)
    log("done: " + args.cmd)


if __name__ == "__main__":
    main()

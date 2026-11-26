# -*- coding: utf-8 -*-
"""Run every test of the website and print one line per file.

    <python 3.12> web/tests/run_all.py

(The two "does the test bite" checks — mutation_check.py, mutation_vs_old.py — and the
comparison on real data — local_check_real.py, which test_compare.py tests on invented
people — are run by hand; see web/README.md.)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_planner.py", "test_store.py", "test_api.py", "test_cards.py", "test_history.py", "test_settings.py",
         "test_backup.py", "test_compare.py", "test_auth.py",
         "test_vs_old.py"]

failed = []
for name in TESTS:
    proc = subprocess.run([sys.executable, os.path.join(HERE, name)], capture_output=True,
                          env=dict(os.environ, PYTHONUTF8="1"))
    out = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    last = next((ln for ln in reversed(out) if ln.startswith("RESULT")), out[-1] if out else "(no output)")
    print(f"{'OK  ' if proc.returncode == 0 else 'FAIL'} {name:<18} {last}")
    if proc.returncode != 0:
        failed.append(name)
        for ln in out:
            if ln.startswith("FAIL"):
                print("      ", ln)
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        for ln in err[-6:]:
            print("      ", ln)
if failed:
    print(f"\nRESULT: {len(failed)} of {len(TESTS)} website test files FAILED: {', '.join(failed)}")
    sys.exit(1)
print(f"\nRESULT: ALL {len(TESTS)} WEBSITE TEST FILES PASS ✓")

# -*- coding: utf-8 -*-
"""
ON-SCREEN render benchmark — uses the REAL Windows Qt platform (not offscreen),
so the QHeaderView ResizeToContents painting cost is actually paid. This is the
path that freezes / crashes the EXE on large recipient lists.

Run WITHOUT QT_QPA_PLATFORM=offscreen:
    python benchmark_render.py
"""
import os
import sys
import time
import random
import tempfile

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

import database as db
_TMP = os.path.join(tempfile.gettempdir(), "bench_data.db")
for _ext in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP + _ext)
    except OSError:
        pass
db.DB_PATH = _TMP

from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import Qt

from tabs.recipients import RecipientsTab
from tabs.group_update import GroupUpdateTab, SCOPE_WEEK, SCOPE_ALL

HEB = "אבגדהוזחטיכלמנסעפצקרשת"
FREQS = ["שבועי", "דו-שבועי", "חודשי", "חד-פעמי"]


def seed(n, rng):
    db.reset_all_data()
    with db.get_connection() as conn:
        cols = db._RECIPIENT_FIELDS
        sql = f"INSERT INTO recipients ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})"
        for i in range(n):
            data = {
                "full_name": "".join(rng.choice(HEB) for _ in range(rng.randint(4, 10))),
                "phone1": "05" + "".join(str(rng.randint(0, 9)) for _ in range(8)),
                "address": "רחוב " + "".join(rng.choice(HEB) for _ in range(6)) + f" {rng.randint(1, 200)}",
                "area": rng.choice(["בעלז", "נתיב"]),
                "souls": rng.randint(1, 12),
                "frequency": rng.choice(FREQS),
                "status": "פעיל",
                "last_distribution": "2026-05-01",
                "next_distribution": "2026-06-10",
            }
            conn.execute(sql, [db._coerce(c, data.get(c, "")) for c in cols])


class FakeMain(QMainWindow):
    def status_msg(self, *a, **k): pass
    def refresh_all(self, *a, **k): pass


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    db.init_db()

    win = QMainWindow()
    win.resize(1280, 800)
    rng = random.Random(7)
    LIMIT = 2.5  # seconds — any single refresh slower than this is a fail
    worst = 0.0
    fails = 0

    for n in (1000, 2000, 3000, 5000):
        seed(n, rng)

        # Build each tab ONCE, then refresh it REPEATEDLY on the same instance —
        # this is the real usage where refresh_all() fires after every save and
        # re-populates an already-populated table (the path that froze the app).
        rec = RecipientsTab(win); win.setCentralWidget(rec); win.show(); app.processEvents()
        # WeeklyTab was merged into GroupUpdateTab. The old weekly-list render is
        # now the SCOPE_WEEK scope; the full "all regulars" render is SCOPE_ALL.
        wk = GroupUpdateTab(win); wk.scope_combo.setCurrentText(SCOPE_WEEK)
        gp = GroupUpdateTab(win); gp.scope_combo.setCurrentText(SCOPE_ALL)

        for tab, label in ((rec, "recipients"), (wk, "weekly"), (gp, "group")):
            win.setCentralWidget(tab)
            app.processEvents()
            times = []
            for _ in range(5):  # 5 consecutive re-populates
                t0 = time.perf_counter()
                tab.refresh()
                app.processEvents()
                times.append(time.perf_counter() - t0)
            mx = max(times)
            worst = max(worst, mx)
            flag = "  <<< FAIL" if mx > LIMIT else ""
            if mx > LIMIT:
                fails += 1
            print(f"n={n:<5} {label:<11} refreshes max={mx:5.2f}s avg={sum(times)/len(times):5.2f}s{flag}")

    win.close()
    print(f"\nworst single refresh: {worst:.2f}s   fails(> {LIMIT}s): {fails}")
    print("RESULT:", "PASS ✓" if fails == 0 else f"FAIL ({fails})")
    print("done")


if __name__ == "__main__":
    main()

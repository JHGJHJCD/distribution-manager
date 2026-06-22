# -*- coding: utf-8 -*-
"""
Headless stress / edge-load harness for מנהל חלוקה.

Runs the REAL Qt tabs off-screen against escalating, randomized datasets,
exercises every user-facing operation, and times each table refresh so that
a UI freeze (the classic ResizeToContents blow-up) shows up as a measurable
failure rather than an invisible hang.

Run:
    set QT_QPA_PLATFORM=offscreen
    python stress_test.py [rounds]
"""
import os
import sys
import time
import random
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# ── isolate the database in a temp file so real data is never touched ──────────
import database as db
_TMP = os.path.join(tempfile.gettempdir(), "stress_data.db")
for _ext in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP + _ext)
    except OSError:
        pass
db.DB_PATH = _TMP

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Tabs under test
from tabs.group_update import GroupUpdateTab
from tabs.weekly import WeeklyTab
from tabs.recipients import RecipientsTab
from tabs.one_time import OneTimeTab
from tabs.tracking import TrackingTab
from tabs.search import SearchTab

# ── data generation ────────────────────────────────────────────────────────────
HEB = "אבגדהוזחטיכלמנסעפצקרשת"
AREAS = ["", "בעלז", "נתיב"]
FREQS = ["שבועי", "דו-שבועי", "חודשי", "חד-פעמי", ""]
STATUSES = ["פעיל", "פעיל", "פעיל", "מושהה", "הסתיים"]  # mostly active


def _rand_name(rng):
    return "".join(rng.choice(HEB) for _ in range(rng.randint(2, 6))) + " " + \
           "".join(rng.choice(HEB) for _ in range(rng.randint(2, 8)))


def _rand_date(rng):
    """Return an ISO date string, or one of several malformed / empty edge values."""
    roll = rng.random()
    if roll < 0.15:
        return ""                       # empty
    if roll < 0.18:
        return "not-a-date"             # malformed
    if roll < 0.20:
        return "2026-13-40"             # impossible date
    y = rng.randint(2023, 2027)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _rand_recipient(rng, i):
    # occasionally inject nasty edge values
    long_note = ("נ" * 4000) if rng.random() < 0.02 else "הערה " * rng.randint(0, 4)
    return {
        "full_name": _rand_name(rng) if rng.random() > 0.01 else "x",  # 1-char name edge
        "phone1": "05" + "".join(str(rng.randint(0, 9)) for _ in range(8)),
        "phone2": "" if rng.random() < 0.5 else "0" + "".join(str(rng.randint(0, 9)) for _ in range(8)),
        "phone3": "",
        "address": "רחוב " + "".join(rng.choice(HEB) for _ in range(rng.randint(3, 10))) + f" {rng.randint(1, 200)}",
        "area": rng.choice(AREAS),
        "souls": rng.randint(0, 25),
        "frequency": rng.choice(FREQS),
        "status": rng.choice(STATUSES),
        "start_date": _rand_date(rng),
        "last_distribution": _rand_date(rng),
        "next_distribution": _rand_date(rng),
        "notes": long_note,
        "email": "" if rng.random() < 0.7 else "test@example.com",
        "id_number": "".join(str(rng.randint(0, 9)) for _ in range(9)),
    }


def seed(n, rng):
    db.reset_all_data()
    # use a single transaction for speed
    with db.get_connection() as conn:
        cols = db._RECIPIENT_FIELDS
        sql = f"INSERT INTO recipients ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})"
        for i in range(n):
            data = _rand_recipient(rng, i)
            conn.execute(sql, [db._coerce(c, data.get(c, "")) for c in cols])


# ── fake main window so tabs can call back into it ─────────────────────────────
from PyQt6.QtWidgets import QWidget as _QWidget


class FakeMain(_QWidget):
    def __init__(self):
        super().__init__()
        self.tabs = None
        self.group_tab = None

    def status_msg(self, *a, **k):
        pass

    def refresh_all(self, *a, **k):
        pass


# ── harness ────────────────────────────────────────────────────────────────────
# A refresh is O(rows): more rows legitimately take longer. The bug we fixed was
# SUPER-linear (≈8s to re-populate 1000 rows). So the failure bar is a per-row
# budget with a floor — this flags freezes/super-linear blow-ups while allowing
# honest linear cost at high row counts.
SLOW_FLOOR = 3.5        # seconds — minimum allowance regardless of size
SLOW_PER_ROW = 0.0025   # seconds per row (2.5 ms/row); tolerant of CPU contention
                        # but still catches super-linear freezes (the 8s-per-1000
                        # group bug fails this easily).


def slow_limit(n: int) -> float:
    return max(SLOW_FLOOR, n * SLOW_PER_ROW)


class Report:
    def __init__(self):
        self.errors = []
        self.timings = []   # (label, n, seconds)

    def err(self, label, n, exc):
        self.errors.append((label, n, exc))

    def slow(self, label, n, secs):
        self.timings.append((label, n, secs))


def timed(report, label, n, fn):
    """Run fn(); record exceptions and slow refreshes."""
    t0 = time.perf_counter()
    try:
        fn()
    except Exception:
        report.err(label, n, traceback.format_exc())
        return
    dt = time.perf_counter() - t0
    report.slow(label, n, dt)
    limit = slow_limit(n)
    if dt > limit:
        report.err(label, n, f"SLOW: took {dt:.2f}s (budget {limit:.2f}s) at n={n}")


def exercise(app, n, rng, report):
    fm = FakeMain()

    # group_update refreshes itself in __init__
    group = GroupUpdateTab(fm)
    fm.group_tab = group
    weekly = WeeklyTab(fm)
    recipients = RecipientsTab(fm)
    one_time = OneTimeTab(fm)
    tracking = TrackingTab(fm)
    search = SearchTab(fm)

    timed(report, "recipients.refresh", n, recipients.refresh)
    timed(report, "weekly.refresh", n, weekly.refresh)
    timed(report, "one_time.refresh", n, one_time.refresh)
    timed(report, "tracking.refresh", n, tracking.refresh)
    timed(report, "search.refresh", n, search.refresh)
    timed(report, "group.refresh", n, group.refresh)

    # Re-populate the SAME instances several times — this is the refresh_all()
    # path (fires after every save) that re-fills an already-populated table.
    for tab, label in ((recipients, "recipients"), (weekly, "weekly"),
                       (one_time, "one_time"), (group, "group"), (tracking, "tracking")):
        for k in range(3):
            timed(report, f"{label}.repopulate", n, tab.refresh)

    # ── REAL render path: show the widget + lay out + process events. ──────────
    # This forces the header's resize-mode cost that off-screen population skips,
    # which is exactly where a visible window freezes / crashes on large data.
    def _render(tab):
        tab.resize(1200, 760)
        tab.show()
        tab.table.resizeColumnsToContents() if hasattr(tab, "table") else None
        app.processEvents()
        tab.hide()
    timed(report, "recipients.render", n, lambda: _render(recipients))
    timed(report, "weekly.render", n, lambda: _render(weekly))
    timed(report, "group.render", n, lambda: _render(group))

    # filters / searches
    def _filter_recipients():
        recipients.search_input.setText(rng.choice(HEB))
        recipients._apply_filter()
        recipients.search_input.setText("")
        recipients._apply_filter()
        recipients.status_filter.setCurrentText("מושהה")
        recipients.status_filter.setCurrentText("הכל")
    timed(report, "recipients.filter", n, _filter_recipients)

    def _weekly_controls():
        weekly.days_spin.setValue(90)
        weekly.area_combo.setCurrentText("בעלז")
        weekly.area_combo.setCurrentText("הכל")
        weekly.days_spin.setValue(7)
    timed(report, "weekly.controls", n, _weekly_controls)

    def _one_time_calc():
        one_time.products_spin.setValue(rng.randint(0, n))
        n_sug, _ = db.compute_suggested_n(one_time.products_spin.value())
        one_time._populate(suggested_n=n_sug)
    timed(report, "one_time.calc", n, _one_time_calc)

    def _tracking_filter():
        tracking.search.setText(rng.choice(HEB))
        tracking._apply_filter()
        tracking.search.setText("")
        tracking._apply_filter()
    timed(report, "tracking.filter", n, _tracking_filter)

    def _search_select():
        # multi-field search: names, partial text, and digit (phone/id) queries
        for _ in range(10):
            search.search_input.setText(rng.choice(HEB))
            search._run_search()
        search.search_input.setText("05" + str(rng.randint(0, 9)))
        search._run_search()
        search.search_input.setText(str(rng.randint(100, 999)))
        search._run_search()
        search.search_input.setText("")
        search._run_search()
    timed(report, "search.select", n, _search_select)

    # group: select all, then save a real bulk distribution
    def _group_distribute():
        group._check_all()
        checked = group._get_checked_recipients()
        if checked:
            db.bulk_add_distributions(checked, "2026-06-10", "סל מזון", 5, "בודק")
        group.refresh()
    timed(report, "group.distribute", n, _group_distribute)

    # summary + queries after distributions exist
    timed(report, "db.get_summary", n, db.get_summary)
    timed(report, "tracking.refresh.post", n, tracking.refresh)

    # excel export of a large list
    def _export():
        rows = db.get_all_recipients(status_filter="פעיל")
        from utils.excel_utils import export_distribution_to_excel
        path = export_distribution_to_excel(rows, "10/06/2026")
        try:
            os.remove(path)
        except OSError:
            pass
    timed(report, "excel.export", n, _export)

    # clean up widgets
    for w in (group, weekly, recipients, one_time, tracking, search):
        w.deleteLater()
    app.processEvents()


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sizes = [200, 1000, 2000, 4000]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    db.init_db()
    report = Report()
    seed_seed = 12345

    for rnd in range(1, rounds + 1):
        for n in sizes:
            rng = random.Random(seed_seed + rnd * 1000 + n)
            try:
                seed(n, rng)
            except Exception:
                report.err("seed", n, traceback.format_exc())
                continue
            exercise(app, n, rng, report)
            print(f"  round {rnd}  n={n:<5}  ok so far: {len(report.errors)} errors")

    # ── report ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SLOWEST REFRESHES (top 12):")
    for label, n, secs in sorted(report.timings, key=lambda x: -x[2])[:12]:
        flag = "  <<< SLOW" if secs > slow_limit(n) else ""
        print(f"  {secs:7.3f}s  n={n:<5} {label}{flag}")

    print("\n" + "=" * 70)
    if report.errors:
        print(f"RESULT: {len(report.errors)} ERRORS / FAILURES\n")
        seen = set()
        for label, n, exc in report.errors:
            key = (label, exc.splitlines()[-1] if "\n" in exc else exc)
            if key in seen:
                continue
            seen.add(key)
            print(f"--- {label} (n={n}) ---")
            print(exc if len(exc) < 1500 else exc[:1500] + " ...")
            print()
        sys.exit(1)
    else:
        print("RESULT: 0 errors — all tiers passed cleanly. ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()

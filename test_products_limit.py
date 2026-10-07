# -*- coding: utf-8 -*-
"""RULE 8 (7/10/2026) — the distribution list never runs past the product count,
in EVERY mode (bug: 'schedule' showed 29 regulars for 5 products).

  schedule            short of products → who waited longest + reserve, rest off
  scored              products + reserve by need-score (#c9k0m — unchanged)
  filter, balanced    exactly the products, split between communities (unchanged)
  filter, unbalanced  products + reserve by who waited longest

Standalone (not pytest):  python test_products_limit.py
"""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date, timedelta
import database as db
import selection
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()

from PyQt6.QtWidgets import QApplication, QMessageBox
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

today = date.today()
# 8 weekly regulars, all due; "קבוע 7" waited longest … "קבוע 0" the shortest.
REG = {}
for i in range(8):
    REG[i] = db.add_recipient({
        "full_name": f"קבוע {i}", "status": "פעיל", "frequency": "שבועי", "priority": 4,
        "souls": 3, "children_total": 3, "representative": "קהילה א" if i % 2 else "קהילה ב",
        "last_distribution": (today - timedelta(days=14 + 7 * i)).isoformat()})
# a monthly regular whose turn has NOT come (served last week) — for the manual add
NOT_DUE = db.add_recipient({
    "full_name": "חודשי לא בתור", "status": "פעיל", "frequency": "חודשי", "priority": 4,
    "souls": 2, "last_distribution": (today - timedelta(days=7)).isoformat()})
ONE = [db.add_recipient({"full_name": f"חדפ {i}", "status": "פעיל", "frequency": "חד-פעמי",
                         "priority": 3, "souls": 4}) for i in range(3)]

from main import MainWindow
win = MainWindow()
gt = win.group_tab

def set_mode(mode):
    gt.mode_combo.setCurrentIndex(gt.mode_combo.findData(mode))

def rows():
    return [(r["id"], bool(r.get("_reserve") or r["id"] in gt._reserve_ids))
            for r in gt._rows_data]

def mains():
    return [rid for rid, res in rows() if not res]

def reserves():
    return [rid for rid, res in rows() if res]

# ── schedule ──────────────────────────────────────────────────────────────────
set_mode("schedule")
gt.reserve_spin.setValue(2)
gt.products_spin.setValue(3)
ok("S1 schedule, 3 products / 8 due → 3 on the list + 2 reserve",
   len(mains()) == 3 and len(reserves()) == 2, str(rows()))
ok("S1b the 3 are the ones who waited LONGEST", mains() == [REG[7], REG[6], REG[5]], str(mains()))
ok("S1c the reserve are the next in line", reserves() == [REG[4], REG[3]], str(reserves()))
ok("S1d other screens (צינתוקים/מיילים) get only the 3",
   [r["id"] for r in gt.week_rows()] == [REG[7], REG[6], REG[5]])
ok("S1e the screen SAYS why (red hint names who stayed)",
   "אין מספיק מוצרים" in gt.lbl_leftover.text() and "3 לא נכנסו" in gt.lbl_leftover.text(),
   gt.lbl_leftover.text())
ok("S1f the count label keeps the real number due", "8" in gt.lbl_regulars_count.text()
   and "מוצגים 5" in gt.lbl_regulars_count.text(), gt.lbl_regulars_count.text())
ok("S1g 'בחר הכל' ticks the 3, never the reserve",
   (gt._check_all(), set(gt._checked_ids) == {REG[7], REG[6], REG[5]})[1], str(gt._checked_ids))
gt._uncheck_all()

gt.reserve_spin.setValue(0)
ok("S2 reserve 0 → exactly the products", len(rows()) == 3 and not reserves(), str(rows()))
gt.reserve_spin.setValue(2)

gt.products_spin.setValue(8)
ok("S3 enough products → all 8, nobody reserve", len(mains()) == 8 and not reserves(), str(rows()))
gt.products_spin.setValue(0)
ok("S4 products not set (0) → everyone due is listed", len(mains()) == 8, str(rows()))

# a regular added by hand takes a product from the last one in line (#fuzpd)
gt.products_spin.setValue(8)
gt.add_one_time_picks([{"id": NOT_DUE, "_reserve": False}])
ok("S5 manual regular in: 7 due + him = 8 main, the shortest wait → reserve",
   len(mains()) == 8 and NOT_DUE in mains() and reserves() == [REG[0]], str(rows()))
gt._extra_ids.clear(); gt._reserve_ids.clear(); gt._persist_extras()

# one-timers picked, then the products drop: regulars are never pushed out
gt.products_spin.setValue(10)
gt.add_one_time_picks([{"id": ONE[0], "_reserve": False}, {"id": ONE[1], "_reserve": False}])
ok("S6 10 products → 8 regulars + 2 one-timers", len(mains()) == 10, str(rows()))
gt.products_spin.setValue(9)
ok("S6b products drop to 9: all 8 regulars stay, the picks are flagged in red",
   all(REG[i] in mains() for i in range(8)) and "יותר מדי" in gt.lbl_leftover.text(),
   gt.lbl_leftover.text())
gt._extra_ids.clear(); gt._reserve_ids.clear(); gt._persist_extras()

# ── the SCHEDULE decides first; the wait only orders those whose turn it is ────
# (יהודה 7/10/2026: "מה שקובע בעיקר זה הלוח זמנים… ודו-שבועי שהזמן שלו השבוע יקבל")
wed = selection.upcoming_wednesday()
BI_DUE = db.add_recipient({          # bi-weekly, served 2 cycles ago → his turn is NOW
    "full_name": "דו-שבועי בתור", "status": "פעיל", "frequency": "דו-שבועי", "priority": 4,
    "souls": 3, "last_distribution": (wed - timedelta(days=14)).isoformat()})
BI_WAIT = db.add_recipient({         # bi-weekly, served last cycle → NOT his turn
    "full_name": "דו-שבועי לא בתור", "status": "פעיל", "frequency": "דו-שבועי", "priority": 4,
    "souls": 3, "last_distribution": (wed - timedelta(days=7)).isoformat()})
MON_WAIT = db.add_recipient({        # monthly, served 3 cycles ago → NOT his turn yet,
    "full_name": "חודשי מחכה", "status": "פעיל", "frequency": "חודשי", "priority": 4,   # though
    "souls": 3, "last_distribution": (wed - timedelta(days=21)).isoformat()})           # he waited
WK_FRESH = db.add_recipient({        # weekly, served last cycle → due, shortest wait
    "full_name": "שבועי טרי", "status": "פעיל", "frequency": "שבועי", "priority": 4,
    "souls": 3, "last_distribution": (wed - timedelta(days=7)).isoformat()})
gt.reserve_spin.setValue(0)
gt.products_spin.setValue(50)        # plenty of products
listed = {rid for rid, _ in rows()}
ok("T1 plenty of products: a bi-weekly whose turn is this week IS on the list",
   BI_DUE in listed and WK_FRESH in listed)
ok("T1b …and whoever's turn has not come is NOT — even with products to spare",
   BI_WAIT not in listed and MON_WAIT not in listed and NOT_DUE not in listed, str(listed))
gt.products_spin.setValue(9)         # 10 due (8 + BI_DUE + WK_FRESH) → one short
ok("T2 one product short: the due bi-weekly (14 days) receives; the weekly served last"
   " week (7 days) is the one left out",
   BI_DUE in mains() and WK_FRESH not in mains() and len(mains()) == 9, str(mains()))
ok("T2b a NOT-due monthly who waited 21 days never jumps the queue (schedule first)",
   MON_WAIT not in mains() and BI_WAIT not in mains())
gt.products_spin.setValue(1)
ok("T3 a single product goes to the due regular who waited longest", mains() == [REG[7]],
   str(mains()))
for _rid in (BI_DUE, BI_WAIT, MON_WAIT, WK_FRESH):
    db.update_recipient(_rid, {"status": "מושהה"})
gt.reserve_spin.setValue(2)

# ── scored (unchanged, #c9k0m) ────────────────────────────────────────────────
gt.products_spin.setValue(3)
set_mode("scored")
ok("M1 scored: 3 products + 2 reserve", len(mains()) == 3 and len(reserves()) == 2, str(rows()))

# ── filter ────────────────────────────────────────────────────────────────────
db.set_filter_criteria({"children_total": {"min": 1, "max": None}, "balance_communities": True})
set_mode("filter")
ok("F1 filter + community balance: exactly the 3 products", len(rows()) == 3, str(rows()))

db.set_filter_criteria({"children_total": {"min": 1, "max": None}, "balance_communities": False})
gt.refresh()
ok("F2 filter, no balance: 3 products + 2 reserve (was: everyone matching)",
   len(mains()) == 3 and len(reserves()) == 2, str(rows()))
ok("F2b …ordered by who waited longest", mains() == [REG[7], REG[6], REG[5]], str(mains()))
ok("F2c the hint says so", "מחכה הכי הרבה זמן" in gt.lbl_leaders_hint.text()
   and not gt.lbl_leaders_hint.isHidden())
gt.products_spin.setValue(0)
ok("F3 filter, products not set → everyone matching", len(rows()) == 8, str(rows()))

# ── none ──────────────────────────────────────────────────────────────────────
gt.products_spin.setValue(3)
set_mode("none")
ok("N1 'בלי קבועים' → empty until someone is added by hand", rows() == [], str(rows()))

set_mode("schedule")
print("\nRESULT:", "ALL PRODUCT-LIMIT TESTS PASS ✓" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)

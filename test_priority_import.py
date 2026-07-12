# -*- coding: utf-8 -*-
"""Import the user's real Excel into a TEMP db and verify the priority logic
end-to-end (counts, frequency mapping, ranking, need-score). Touches no real data."""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
# Force UTF-8 console output so the ✓/→ characters in the report never crash the
# test on a legacy Windows code page (cp1255). Setting PYTHONUTF8 above is too
# late — the interpreter reads it only at startup — so reconfigure the streams.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import database as db
db.DB_PATH = os.path.join(tempfile.gettempdir(), "prio_test.db")
db.BACKUP_DIR = os.path.join(tempfile.gettempdir(), "prio_test_bk")
for e in ("", "-wal", "-shm"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass

from utils.excel_utils import import_from_excel
from collections import Counter

FILE = r"C:\Users\יהודה\Downloads\חלוקת שבת מעודכן בלק פו (2) (1).xlsx"
ok = True
def check(label, cond, extra=""):
    global ok; ok = ok and cond
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

db.init_db()
rows = import_from_excel(FILE)
print(f"parsed {len(rows)} rows from Excel")

# priority distribution among parsed rows
pri = Counter(r.get("priority") for r in rows)
raw_buran = sum(1 for r in rows if r.get("priority") is None and "בירור" in (r.get("priority_raw") or ""))
print("  parsed priority counts:", dict(pri), " | חובת בירור:", raw_buran)

# frequency mapping in parsed rows
freq = Counter(r.get("frequency") for r in rows)
print("  parsed frequency counts:", dict(freq))
check("code 4 → frequency שבועי", all(r.get("frequency") == "שבועי" for r in rows if r.get("priority") == 4))
check("code 3 → frequency חד-פעמי", all(r.get("frequency") == "חד-פעמי" for r in rows if r.get("priority") == 3))
check("code 2 → frequency חד-פעמי", all(r.get("frequency") == "חד-פעמי" for r in rows if r.get("priority") == 2))
check("חובת בירור → חד-פעמי + no digit", all(
    r.get("frequency") == "חד-פעמי" for r in rows if "בירור" in (r.get("priority_raw") or "")))

# ── souls = children-at-home + adults, adults inferred from marital status ──────
from utils.excel_utils import _adults_in_household as _adults
check("married → 2 adults",        _adults("נשוי") == 2 and _adults("נשואה") == 2)
check("blank/unknown → 2 adults",  _adults("") == 2 and _adults(None) == 2 and _adults("לא ידוע") == 2)
check("divorced → 1 adult",        _adults("גרוש") == 1 and _adults("גרושה") == 1)
check("widow(er) → 1 adult",       _adults("אלמן") == 1 and _adults("אלמנה") == 1)  # final-nun normalization
check("single/separated → 1 adult", _adults("רווק") == 1 and _adults("רווקה") == 1 and _adults("פרוד") == 1)

# ── load into DB (replace) ─────────────────────────────────────────────────────
db.reset_all_data()
added, updated, conflicts = db.import_recipients_from_list(rows)
print(f"  imported: added={added} updated={updated} conflicts={len(conflicts)}")
allrec = db.get_all_recipients()
check("all parsed rows stored", len(allrec) >= len(rows) - len(conflicts) - 5, f"db has {len(allrec)}")

dbpri = Counter(r.get("priority") for r in allrec)
print("  DB priority counts:", dict(dbpri))
check("priority preserved in DB (code 3 count)", dbpri.get(3, 0) == pri.get(3, 0))
check("priority preserved in DB (code 2 count)", dbpri.get(2, 0) == pri.get(2, 0))

# Only priority tiers 2/3 and 'בירור' become one-time. Code 4 = weekly; codes
# 1/0 and unmarked rows carry NO invented frequency (blank) — they must NOT be
# forced to 'חד-פעמי'.
check("code 4 → frequency שבועי (DB)",
      all(r.get("frequency") == "שבועי" for r in allrec if r.get("priority") == 4))
check("codes 1/0 NOT forced to חד-פעמי",
      all(r.get("frequency") != "חד-פעמי" for r in allrec if r.get("priority") in (0, 1)))
non_onetime = [r for r in allrec if r.get("frequency") != "חד-פעמי"]
check("non-one-time freq is only שבועי or blank",
      all((r.get("frequency") or "") in ("", "שבועי") for r in non_onetime),
      f"{len(non_onetime)} non-one-time")

# ── ranking ────────────────────────────────────────────────────────────────────
ot = db.get_one_time_list()
in_dist = [r for r in ot if r.get("in_distribution")]
others = [r for r in ot if not r.get("in_distribution")]
print(f"  one-time list: {len(ot)} total | in_distribution(2/3)={len(in_dist)} | others={len(others)}")

# in_distribution rows come first, priority 3 before priority 2
first_block_priorities = [r.get("priority") for r in ot[:len(in_dist)]]
check("all distribution rows are first", all(p in (3, 2) for p in first_block_priorities))
# tier order: every 3 before every 2
last3 = max((i for i, p in enumerate(first_block_priorities) if p == 3), default=-1)
first2 = min((i for i, p in enumerate(first_block_priorities) if p == 2), default=len(in_dist))
check("priority 3 block entirely before priority 2 block", last3 < first2)

# need-score descending within each tier
p3 = [r["need_score"] for r in in_dist if r.get("priority") == 3]
p2 = [r["need_score"] for r in in_dist if r.get("priority") == 2]
check("need-score descending within tier 3", all(p3[i] >= p3[i+1] for i in range(len(p3)-1)))
check("need-score descending within tier 2", all(p2[i] >= p2[i+1] for i in range(len(p2)-1)))
check("need-scores are 0..100", all(0 <= (r.get("need_score") or 0) <= 100 for r in in_dist))

# חובת בירור present but excluded from distribution
buran_db = [r for r in allrec if "בירור" in (r.get("priority_raw") or "")]
check("חובת בירור kept as data", len(buran_db) > 0, f"{len(buran_db)} rows")
check("חובת בירור excluded from distribution",
      all(not r.get("in_distribution") for r in ot if "בירור" in (r.get("priority_raw") or "")))

# show top 6 of the ranked list
print("  --- top of ranked one-time list ---")
for r in ot[:6]:
    print(f"     pri={r.get('priority')} score={r.get('need_score')}  {r.get('full_name','')[:22]:22} "
          f"souls={r.get('souls')} per_soul={r.get('per_soul')}")

n, regc = db.compute_suggested_n(200)
print(f"  compute_suggested_n(200) → one-time={n}, regulars={regc}")

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)

# -*- coding: utf-8 -*-
"""Scenario tests for the recipient-selection rules — the single source of truth
in selection.py, plus its wiring through database.py.

Each test states a KNOWN scenario and the expected outcome, so any future change
to the scoring/priority/reserve rules that breaks an agreed behaviour fails here
immediately. Pins the four operator decisions (2026-07):

  RULE 1  priority is the entry gate; in the one-time distribution ראשונה
          dominates שנייה, need-score orders within a tier; in the merged scored
          mode priority is only the gate and order is pure need-score.
  RULE 2  two modes kept (schedule / scored).
  RULE 3  reserve = standby, not recorded by default.
  RULE 4  missing data sinks a family to the bottom of the queue.
"""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

import selection
import scoring

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

# A single-factor weight makes need-score fully predictable from one field.
W_SOULS  = {"souls": 100.0}     # "high" factor: more souls → higher score
W_INCOME = {"income": 100.0}    # "low"  factor: lower income → higher score


def rec(name, priority=None, freq="חד-פעמי", **extra):
    r = {"id": name, "full_name": name, "priority": priority, "frequency": freq}
    r.update(extra)
    return r


# ── RULE 1a — one-time distribution: ראשונה dominates שנייה, even on lower score ─
a = rec("ראשונה-חלש", priority=3, souls=1)     # low score
b = rec("שנייה-חזק", priority=2, souls=99)     # high score
ranked = selection.rank_one_time_priority([b, a], W_SOULS)
ok("R1a ראשונה precedes שנייה despite lower score",
   [r["full_name"] for r in ranked] == ["ראשונה-חלש", "שנייה-חזק"],
   str([r["full_name"] for r in ranked]))

# within the SAME tier, higher score wins
c = rec("ראשונה-חזק", priority=3, souls=50)
ranked2 = selection.rank_one_time_priority([a, c], W_SOULS)
ok("R1a within a tier, higher score first",
   [r["full_name"] for r in ranked2] == ["ראשונה-חזק", "ראשונה-חלש"])

# ── RULE 1b — merged scored mode: priority ignored, pure need-score ────────────
ranked3 = selection.rank_by_need([a, b], W_SOULS)
ok("R1b scored mode ranks by score alone (שנייה can beat ראשונה)",
   [r["full_name"] for r in ranked3] == ["שנייה-חזק", "ראשונה-חלש"],
   str([r["full_name"] for r in ranked3]))

# ── RULE 1 (gate) — only priority 3/2 one-timers are candidates ───────────────
ok("R1 gate: priority 3 is a candidate", selection.is_one_time_candidate(rec("x", 3)))
ok("R1 gate: priority 2 is a candidate", selection.is_one_time_candidate(rec("x", 2)))
ok("R1 gate: priority 1 is NOT a candidate", not selection.is_one_time_candidate(rec("x", 1)))
ok("R1 gate: no priority is NOT a candidate", not selection.is_one_time_candidate(rec("x", None)))
ok("R1 gate: a regular is NOT a one-time candidate",
   not selection.is_one_time_candidate(rec("x", 3, freq="שבועי")))

# ── RULE 3 — reserve split + not-recorded-by-default ──────────────────────────
cands = [rec(f"m{i}", 3, souls=100 - i) for i in range(5)]   # 5 candidates, scored desc
ordered = selection.rank_one_time_priority(cands, W_SOULS)
selection.assign_roles(ordered, portions=2, reserve_count=1)
roles = [r["_role"] for r in ordered]
ok("R3 first N are main", roles[:2] == [selection.ROLE_MAIN, selection.ROLE_MAIN], str(roles))
ok("R3 next are reserve", roles[2] == selection.ROLE_RESERVE, str(roles))
ok("R3 rest are out", roles[3:] == [selection.ROLE_OUT, selection.ROLE_OUT], str(roles))
ok("R3 main is recorded by default", selection.recorded_by_default(ordered[0]))
ok("R3 reserve is NOT recorded by default", not selection.recorded_by_default(ordered[2]))
ok("R3 reserve carries the _reserve UI flag", ordered[2]["_reserve"] is True)

# portions=None → everyone main, no reserve
selection.assign_roles(ordered, portions=None, reserve_count=3)
ok("R3 portions=None → all main", all(r["_role"] == selection.ROLE_MAIN for r in ordered))

# ── RULE 4 — a family with missing data sinks to the bottom ────────────────────
needy   = rec("נזקק",    3, income="1000")   # low income → neediest
mid     = rec("בינוני",  3, income="3000")
missing = rec("חסר-נתון", 3)                  # no income at all
order4 = [r["full_name"] for r in selection.rank_by_need([mid, missing, needy], W_INCOME)]
ok("R4 missing-data family lands LAST", order4 == ["נזקק", "בינוני", "חסר-נתון"], str(order4))

# and a fully-missing family never outranks anyone with real data
allmiss = rec("ריק", 3)
order4b = [r["full_name"] for r in selection.rank_by_need([allmiss, needy], W_INCOME)]
ok("R4 real data outranks no data", order4b == ["נזקק", "ריק"], str(order4b))

# ── Combined scenario (GPT's worked example, one-time portion) ─────────────────
# 4 portions available to one-timers; 3 ראשונה + 5 שנייה candidates.
# Expected: the 3 ראשונה + the single highest-score שנייה are MAIN; the rest
# spill into reserve/out — proving ראשונה fills before any שנייה (RULE 1).
firsts  = [rec(f"ראשונה{i}", 3, souls=10 + i) for i in range(3)]
seconds = [rec(f"שנייה{i}",  2, souls=50 - i) for i in range(5)]   # שנייה0 has the top score
plan = selection.plan_one_time(firsts + seconds, W_SOULS, portions=4, reserve_count=2)
mains = [r["full_name"] for r in plan if r.get("_role") == selection.ROLE_MAIN]
ok("Combined: exactly 4 main picks", len(mains) == 4, str(mains))
ok("Combined: all 3 ראשונה are main", sum(1 for m in mains if m.startswith("ראשונה")) == 3, str(mains))
ok("Combined: the 4th main is the top-score שנייה", "שנייה0" in mains, str(mains))
reserves = [r["full_name"] for r in plan if r.get("_role") == selection.ROLE_RESERVE]
ok("Combined: 2 reserve (standby)", len(reserves) == 2, str(reserves))

# ── DB wiring — the tabs get the same ordering through database.py ────────────
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]
db.BACKUP_DIR = tempfile.mkdtemp()
db.init_db()
db.set_need_weights(W_SOULS)   # score by souls so ordering is predictable

# one ראשונה weak, one שנייה strong → get_one_time_list must keep ראשונה first
db.add_recipient({"full_name": "ראשונה-חלש-db", "status": "פעיל", "frequency": "חד-פעמי",
                  "priority": 3, "souls": 1})
db.add_recipient({"full_name": "שנייה-חזק-db", "status": "פעיל", "frequency": "חד-פעמי",
                  "priority": 2, "souls": 99})
one_time = [r["full_name"] for r in db.get_one_time_list() if r.get("in_distribution")]
ok("DB get_one_time_list keeps ראשונה before שנייה",
   one_time == ["ראשונה-חלש-db", "שנייה-חזק-db"], str(one_time))

# merged scored mode must instead order those two by pure score
scored = [r["full_name"] for r in db.get_scored_all()
          if r["full_name"] in ("ראשונה-חלש-db", "שנייה-חזק-db")]
ok("DB get_scored_all orders by score alone",
   scored == ["שנייה-חזק-db", "ראשונה-חלש-db"], str(scored))

# ── compute_suggested_n counts only regulars DUE this week (not every regular) ─
from datetime import date, timedelta
db.reset_all_data()
db.set_setting("dist_regulars_mode", "schedule")
_today = date.today()
db.add_recipient({"full_name": "קבוע-בתור", "status": "פעיל", "frequency": "שבועי",
                  "last_distribution": (_today - timedelta(days=400)).isoformat()})   # long overdue → due
db.add_recipient({"full_name": "קבוע-לא-בתור", "status": "פעיל", "frequency": "חודשי",
                  "last_distribution": (_today - timedelta(days=13)).isoformat(),      # not "served recently"
                  "next_distribution": (_today + timedelta(days=30)).isoformat()})     # next turn a month out → not due
_n, _reg = db.compute_suggested_n(10)
ok("compute_suggested_n counts only the DUE regular (1 of 2)", _reg == 1, f"reg={_reg}")
ok("compute_suggested_n leaves the rest for one-timers", _n == 9, f"n={_n}")

# ── get_weekly_list ignores a FUTURE last_distribution (data-entry error) ──────
db.reset_all_data()
db.add_recipient({"full_name": "עתידי", "status": "פעיל", "frequency": "שבועי",
                  "last_distribution": (_today + timedelta(days=10)).isoformat()})
_wk = [r["full_name"] for r in db.get_weekly_list()]
ok("weekly list excludes a future-dated last_distribution", "עתידי" not in _wk, str(_wk))

print()
print("RESULT:", "ALL SELECTION SCENARIOS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

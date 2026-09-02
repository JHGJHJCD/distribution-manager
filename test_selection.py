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

# ── ותק: never-received counts from REGISTRATION date, not the year-2000 epoch ─
_vet = {"last_distribution": "", "start_date": (_today - timedelta(days=500)).isoformat()}
_new = {"last_distribution": "", "start_date": (_today - timedelta(days=5)).isoformat()}
ok("recency: veteran (registered long ago) waits ~500d", db.recency_days(_vet) == 500, str(db.recency_days(_vet)))
ok("recency: newcomer waits ~5d (not 26 years)", db.recency_days(_new) == 5, str(db.recency_days(_new)))
ok("recency: a received date takes precedence over registration",
   db.recency_days({"last_distribution": (_today - timedelta(days=3)).isoformat(),
                    "start_date": (_today - timedelta(days=500)).isoformat()}) == 3)
ok("recency: future registration clamps to 0",
   db.recency_days({"start_date": (_today + timedelta(days=9)).isoformat()}) == 0)
# and in a real ranking, the veteran outranks the newcomer on ותק alone
_rank = selection.rank_by_need(
    [{"id": "new", "full_name": "חדש", "frequency": "חד-פעמי", "priority": 3,
      "days_since": db.recency_days(_new)},
     {"id": "vet", "full_name": "ותיק", "frequency": "חד-פעמי", "priority": 3,
      "days_since": db.recency_days(_vet)}],
    {"recency": 100.0})
ok("recency: veteran outranks newcomer on ותק", [r["id"] for r in _rank] == ["vet", "new"],
   str([r["id"] for r in _rank]))

# ── tie-break: EQUAL need → longest-waiting wins, not the alphabet ─────────────
_tie = selection.rank_by_need(
    [{"id": "early", "full_name": "אבי", "souls": "5", "days_since": 10},
     {"id": "late",  "full_name": "תמר", "souls": "5", "days_since": 900}],
    {"souls": 100.0})   # recency weight 0 → identical score; only the tie-break differs
ok("tie-break: equal need → longest-waiting first (beats alphabetical 'אבי')",
   [r["id"] for r in _tie] == ["late", "early"], str([r["full_name"] for r in _tie]))

# ── broad custom filter (mode 'filter', #vq4fx) ───────────────────────────────
# A distribution over the WHOLE list by numeric thresholds, ignoring priority.
ok("to_number: text shekels parse", selection.to_number("4,500 ₪") == 4500.0)
ok("to_number: blank/None → None", selection.to_number("") is None and selection.to_number(None) is None)
ok("to_number: non-numeric → None", selection.to_number("לא ידוע") is None)
ok("to_number: keeps decimals", selection.to_number("2,500.50") == 2500.5)

_pool = [
    {"id": 1, "full_name": "גדולה-ענייה", "children_total": 7, "income": "2000", "per_soul": "250"},
    {"id": 2, "full_name": "קטנה-אמידה", "children_total": 2, "income": "9000", "per_soul": "2000"},
    {"id": 3, "full_name": "חסרת-הכנסה", "children_total": 8, "income": "",     "per_soul": "100"},
    {"id": 4, "full_name": "גבולית",      "children_total": 5, "income": "3000", "per_soul": "250"},
]
_crit = {"children_total": {"min": 5, "max": None},
         "income":         {"min": None, "max": 3000},
         "per_soul":       {"min": None, "max": None}}
_res = selection.filter_by_criteria(_pool, _crit)
ok("filter: children≥5 AND income≤3000 keeps only qualifying rows",
   sorted(r["id"] for r in _res) == [1, 4], str([r["id"] for r in _res]))
ok("filter: missing value in a CONSTRAINED field excludes the row (hard gate)",
   3 not in {r["id"] for r in _res})
ok("filter: priority/frequency are IGNORED — a one-timer can qualify",
   {r["id"] for r in selection.filter_by_criteria(
       [{"id": 9, "frequency": "חד-פעמי", "priority": 3, "children_total": 6, "income": "1000"}],
       {"children_total": {"min": 5, "max": None}})} == {9})
ok("filter: no active bound → list unchanged",
   len(selection.filter_by_criteria(_pool, {"children_total": {"min": None, "max": None}})) == 4)
ok("criteria_is_active: empty vs set",
   not selection.criteria_is_active({}) and selection.criteria_is_active(_crit))

# ── community balance in filter mode (#lejmr, v2.61) ─────────────────────────
# Operator decisions (08/2026): quota per community proportional to its TOTAL
# size (community of 200 gets double a community of 100); a community whose
# quota exceeds its filter-qualifiers fills the gap from its OWN members by need
# score; manual percent pins normalise at the others' expense; rep-less people
# are their own "ללא קהילה" group; the auto-fill infers a rep by synagogue
# majority.

def crec(name, rep, income, syn="", children=5):
    return {"id": name, "full_name": name, "representative": rep,
            "synagogue": syn, "income": str(income), "children_total": children}

# Community sizes: א=2, ב=4 → quotas for 3 products ∝ size → א=1, ב=2
_ca = [crec("א-עני", "נציג א", 1000), crec("א-עשיר", "נציג א", 9000)]
_cb = [crec("ב-עני1", "נציג ב", 500), crec("ב-עני2", "נציג ב", 800),
       crec("ב-בינוני", "נציג ב", 2000), crec("ב-עשיר", "נציג ב", 9500)]
_crit_inc = {"income": {"min": None, "max": 3000}}
_picked = selection.balance_by_community(_ca + _cb, _crit_inc, W_INCOME, 3)
_names = {r["full_name"] for r in _picked}
ok("C1 quotas ∝ community size (א=1, ב=2 of 3 products)",
   len(_picked) == 3
   and sum(1 for r in _picked if r["representative"] == "נציג א") == 1
   and sum(1 for r in _picked if r["representative"] == "נציג ב") == 2, str(_names))
ok("C2 inside a community the poorest (by need) win",
   "ב-עני1" in _names and "ב-עני2" in _names and "א-עני" in _names, str(_names))
ok("C3 the 'richer' of the big community fell off (original report's ask)",
   "ב-בינוני" not in _names and "ב-עשיר" not in _names)

# Quota bigger than qualifiers → top-up from the SAME community by need
_small = [crec("ק-עני", "נציג ק", 1000), crec("ק-עשיר1", "נציג ק", 8000),
          crec("ק-עשיר2", "נציג ק", 9000)]
_picked2 = selection.balance_by_community(_small, _crit_inc, W_INCOME, 2)
_n2 = [r["full_name"] for r in _picked2]
ok("C4 quota gap filled from the community's own non-qualifiers by need",
   len(_picked2) == 2 and "ק-עני" in _n2 and "ק-עשיר1" in _n2, str(_n2))
ok("C4b the fill rows are marked (_balance_fill)",
   any(r.get("_balance_fill") for r in _picked2 if r["full_name"] == "ק-עשיר1"))

# C4c the top-up is ordered by CLOSENESS to the filter, NOT by need score, even
# when the two disagree (#lejmr). Filter = children ≥ 6 (nobody qualifies here);
# need is driven by income (W_INCOME). "כמעט" misses by one child (5) but is rich
# (low need); "רחוק" misses by four (2) but is poor (high need). The near-miss
# must be filled first — proving gap beats need.
_gap = [crec("כמעט", "נציג ג", 9000, children=5),
        crec("רחוק", "נציג ג", 500, children=2)]
_pg = selection.balance_by_community(_gap, {"children_total": {"min": 6, "max": None}},
                                     W_INCOME, 1)
ok("C4c top-up picks the near-miss (closest to the filter), not the neediest",
   len(_pg) == 1 and _pg[0]["full_name"] == "כמעט", str([r["full_name"] for r in _pg]))

# C4d a regular swept into the top-up is flagged (_balance_regular) so the screen
# can highlight it — monthly counts as regular too.
_reg = [dict(crec("קבוע-חודשי", "נציג ד", 8000), frequency="חודשי"),
        crec("חדפ", "נציג ד", 9000)]
_pr = selection.balance_by_community(_reg, _crit_inc, W_INCOME, 1)
ok("C4d a regular in the top-up is flagged _balance_regular",
   any(r.get("_balance_regular") for r in _pr if r["full_name"] == "קבוע-חודשי"),
   str([(r["full_name"], r.get("_balance_regular")) for r in _pr]))

# Manual percent pin: community א pinned to 75% of 4 products → 3; ב gets 1
_pin = selection.balance_by_community(
    [crec(f"א{i}", "נציג א", 1000) for i in range(4)]
    + [crec(f"ב{i}", "נציג ב", 1000) for i in range(4)],
    _crit_inc, W_INCOME, 4, manual_pcts={"נציג א": 75})
ok("C5 manual percent pin honoured (א=3, ב=1)",
   sum(1 for r in _pin if r["representative"] == "נציג א") == 3
   and sum(1 for r in _pin if r["representative"] == "נציג ב") == 1)

# Over-100 manual pins normalise
_q = selection.community_quotas(10, {"א": 10, "ב": 10}, {"א": 80, "ב": 120})
ok("C6 over-100 manual pins normalise to 100 (4/6 of 10)",
   _q == {"א": 4, "ב": 6}, str(_q))

# Rep-less people are their own group with a proportional share
_mixed = ([crec(f"נ{i}", "נציג נ", 1000) for i in range(3)]
          + [crec(f"ללא{i}", "", 1000) for i in range(3)])
_picked3 = selection.balance_by_community(_mixed, _crit_inc, W_INCOME, 2)
ok("C7 'ללא קהילה' competes as its own group (1 of 2 picks)",
   sum(1 for r in _picked3 if not r["representative"]) == 1
   and all(r.get("_community") for r in _picked3))

# Quota caps at community size (more products than people → everyone, no more)
_q2 = selection.community_quotas(10, {"א": 2, "ב": 3})
ok("C8 quota capped at community size (א=2, ב=3 despite 10 products)",
   _q2 == {"א": 2, "ב": 3}, str(_q2))
# A pinned community that can't absorb its percent frees the rest to the other
_q3 = selection.community_quotas(10, {"א": 2, "ב": 20}, {"א": 80})
ok("C8b pinned-but-small community caps at its size, rest flows on",
   _q3["א"] == 2 and _q3["ב"] == 8, str(_q3))

# No products count → plain filtered list (no balance)
_plain = selection.balance_by_community(_ca + _cb, _crit_inc, W_INCOME, 0)
ok("C9 products=0 → plain filter (everyone qualifying listed)",
   {r["full_name"] for r in _plain} == {"א-עני", "ב-עני1", "ב-עני2", "ב-בינוני"})

# Synagogue-majority inference for rep-less recipients
_inf_rows = [
    {"id": 1, "representative": "נציג א", "synagogue": "בית כנסת המרכזי"},
    {"id": 2, "representative": "נציג א", "synagogue": "בית כנסת המרכזי"},
    {"id": 3, "representative": "נציג ב", "synagogue": "בית כנסת המרכזי"},
    {"id": 4, "representative": "",       "synagogue": "בית כנסת המרכזי"},
    {"id": 5, "representative": "",       "synagogue": "בית כנסת אחר"},
    {"id": 6, "representative": "",       "synagogue": ""},
]
_sug = selection.infer_communities(_inf_rows)
ok("C10 rep inferred by synagogue majority (2/3 נציג א)", _sug.get(4) == "נציג א", str(_sug))
ok("C10b no inference without a synagogue signal", 5 not in _sug and 6 not in _sug)
_thin = selection.infer_communities([
    {"id": 1, "representative": "נציג א", "synagogue": "קטן"},
    {"id": 2, "representative": "", "synagogue": "קטן"}])
ok("C10c a lone rep in a synagogue is too thin to infer from", 2 not in _thin)

# ── #c9k0m: scored modes show only products + reserve ─────────────────────────
_lim = [{"id": i, "full_name": f"מ{i}", "need_score": 100 - i} for i in range(1, 11)]
_out = selection.limit_to_products(_lim, 3, 2)
ok("L1 products=3 + reserve=2 → 5 rows shown, rest dropped",
   [r["id"] for r in _out] == [1, 2, 3, 4, 5], str([r["id"] for r in _out]))
ok("L1b first 3 main, next 2 reserve",
   [r["_reserve"] for r in _out] == [False, False, False, True, True])
_lim2 = [{"id": i, "full_name": f"מ{i}", "need_score": 100 - i} for i in range(1, 11)]
_out2 = selection.limit_to_products(_lim2, 3, 1, keep_ids={9}, reserve_ids={10})
ok("L2 manual add (9) kept as MAIN and takes a slot; reserve pick (10) kept as reserve",
   [r["id"] for r in _out2] == [1, 2, 3, 9, 10]
   and not _out2[3]["_reserve"] and _out2[4]["_reserve"], str([r["id"] for r in _out2]))
_lim3 = [{"id": i, "full_name": f"מ{i}"} for i in range(1, 6)]
ok("L3 products=0 → no limit (everyone stays)",
   len(selection.limit_to_products(_lim3, 0, 5)) == 5)

print()
print("RESULT:", "ALL SELECTION SCENARIOS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

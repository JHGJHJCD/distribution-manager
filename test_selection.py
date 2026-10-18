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

# ── a FUTURE last_distribution (data-entry error) is IGNORED — the regular is due ──
# (user decision 27/9/2026; until v3.74 the person vanished from the list until
#  the typo date passed, with nowhere to fix it)
db.reset_all_data()
db.add_recipient({"full_name": "עתידי", "status": "פעיל", "frequency": "שבועי",
                  "last_distribution": (_today + timedelta(days=10)).isoformat()})
_wk = [r["full_name"] for r in db.get_weekly_list()]
ok("weekly list IGNORES a future-dated last_distribution (person is due)", "עתידי" in _wk, str(_wk))

# …on EVERY weekday (a typo 1–6 days past next Wednesday must not count as
# "served now" either — it's a typo like any other future date).
import datetime as _dt_mod
_RealDate = db.date
for _wd_off in range(7):
    _fake_today = _today + timedelta(days=_wd_off)
    class _FakeDate(_RealDate):
        @classmethod
        def today(cls, _d=_fake_today):
            return _RealDate(_d.year, _d.month, _d.day)
    db.date = _FakeDate
    try:
        db.reset_all_data()
        for _k in range(1, 13):
            db.add_recipient({"full_name": f"עתידי-{_k}", "status": "פעיל", "frequency": "שבועי",
                              "last_distribution": (_fake_today + timedelta(days=_k + 7)).isoformat()})
        _wk2 = [r["full_name"] for r in db.get_weekly_list()]
    finally:
        db.date = _RealDate
    ok(f"weekly list ignores future-dated typos → all 12 due (weekday {_fake_today.weekday()})",
       len(_wk2) == 12, str(_wk2))

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

# C4e RULE 4 in the top-up: a family with MISSING data on a constrained field
# never edges out a measurable one — even one far over the threshold (a known
# gap of 1.5 used to lose to the flat 1.0 given for "no data").
_mis = [crec("ידוע-רחוק", "נציג ה", 3000), crec("חסר", "נציג ה", ""),
        crec("עומד", "נציג ה", 500)]
_pm = selection.balance_by_community(_mis, {"income": {"min": None, "max": 1200}}, W_INCOME, 2)
ok("C4e top-up takes the measurable near-miss before the missing-data card",
   [r["full_name"] for r in _pm] == ["עומד", "ידוע-רחוק"], str([r["full_name"] for r in _pm]))

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

# ── RULE 8 (7/10/2026): fewer products than due regulars → longest wait first ─
def _wr(i, days, souls=1):
    return {"id": i, "full_name": f"ק{i}", "frequency": "שבועי", "priority": 4,
            "days_since": days, "souls": souls}

_w = selection.rank_by_wait([_wr(1, 14), _wr(2, 44), _wr(3, 14, souls=9), _wr(4, 0)], W_SOULS)
ok("W1 longest wait first; equal wait → higher need-score",
   [r["id"] for r in _w] == [2, 3, 1, 4], str([r["id"] for r in _w]))
_w_name = selection.rank_by_wait([_wr(2, 7), _wr(1, 7)], W_SOULS)
ok("W1b equal wait and score → by name", [r["id"] for r in _w_name] == [1, 2])

_due = [_wr(i, d) for i, d in ((1, 14), (2, 44), (3, 21), (4, 14), (5, 30), (6, 7))]
_cut = selection.limit_due_regulars(_due, W_SOULS, 2, 2)
ok("W2 2 products + 2 reserve of 6 due → 4 rows, by wait",
   [r["id"] for r in _cut] == [2, 5, 3, 1], str([r["id"] for r in _cut]))
ok("W2b first 2 main, next 2 reserve",
   [bool(r["_reserve"]) for r in _cut] == [False, False, True, True])
_same = [_wr(i, 7) for i in (3, 1, 2)]
_keep = selection.limit_due_regulars(_same, W_SOULS, 3, 5)
ok("W3 enough products → list unchanged (same order, nobody reserve)",
   _keep is _same and [r["id"] for r in _keep] == [3, 1, 2]
   and not any(r.get("_reserve") for r in _keep))
ok("W4 products=0 (not set) → no limit",
   len(selection.limit_due_regulars([_wr(i, i) for i in range(1, 6)], W_SOULS, 0, 2)) == 5)
_man = selection.limit_due_regulars([_wr(i, i) for i in range(1, 6)], W_SOULS, 5, 1,
                                    manual_regulars=2)
ok("W5 a manual regular takes a product: 5 products, 2 manual → 3 main + 1 reserve",
   [r["id"] for r in _man] == [5, 4, 3, 2]
   and [bool(r["_reserve"]) for r in _man] == [False, False, False, True],
   str([(r["id"], r["_reserve"]) for r in _man]))
ok("W6 no reserve asked → exactly the products",
   len(selection.limit_due_regulars([_wr(i, i) for i in range(1, 6)], W_SOULS, 2, 0)) == 2)
ok("W7 empty list is safe", selection.limit_due_regulars([], W_SOULS, 3, 2) == [])

# ── v3.52: נתמך חגים — general mark + per-holiday subset, holiday gate ───────
import holidays
_h_all  = {"id": 1, "full_name": "כללי",  "holiday_support": 1, "holidays": ""}
_h_some = {"id": 2, "full_name": "חלקי",  "holiday_support": 1, "holidays": "פסח,סוכות"}
_h_none = {"id": 3, "full_name": "לא",    "holiday_support": 0, "holidays": "פסח"}
_h_pool = [_h_all, _h_some, _h_none]
ok("H1 general mark: supports() any holiday when subset empty",
   holidays.supports(_h_all) and holidays.supports(_h_all, "חנוכה"))
ok("H2 subset: only the listed holidays",
   holidays.supports(_h_some, "פסח") and not holidays.supports(_h_some, "חנוכה")
   and holidays.supports(_h_some))
ok("H3 mark off → never supported, even with a subset text",
   not holidays.supports(_h_none) and not holidays.supports(_h_none, "פסח"))
ok("H4 display text", holidays.display(_h_all) == "כל החגים"
   and holidays.display(_h_some) == "סוכות, פסח" and holidays.display(_h_none) == "")
ok("H5 to_field: all ticked = '' ; canonical order; unknown dropped",
   holidays.to_field(holidays.HOLIDAYS) == "" and holidays.to_field(["פסח", "סוכות", "זבל"]) == "סוכות,פסח")
ok("H6 from_text round-trip (Excel import)",
   holidays.from_text("כל החגים") == (1, "") and holidays.from_text("פסח, סוכות") == (1, "סוכות,פסח")
   and holidays.from_text("") == (0, "") and holidays.from_text("לא") == (0, ""))
ok("H7 criteria: no holiday key → no gate, not active",
   len(selection.holiday_filter(_h_pool, {})) == 3 and not selection.criteria_is_active({}))
ok("H8 criteria '*' → everyone with the mark; active",
   [r["id"] for r in selection.holiday_filter(_h_pool, {"holiday": "*"})] == [1, 2]
   and selection.criteria_is_active({"holiday": "*"}))
ok("H9 criteria 'חנוכה' → only marks covering it; matches_criteria ANDs it",
   [r["id"] for r in selection.holiday_filter(_h_pool, {"holiday": "חנוכה"})] == [1]
   and not selection.matches_criteria(_h_some, {"holiday": "חנוכה"})
   and selection.matches_criteria(_h_some, {"holiday": "פסח"}))
ok("H10 holiday_label", selection.holiday_label({"holiday": "*"}) == "נתמכי חגים"
   and selection.holiday_label({"holiday": "פסח"}) == "נתמכי פסח" and selection.holiday_label({}) == "")

# Excel import of the mark: a NEGATIVE text must not turn the mark on, and a list
# written with "/" or "ו" must keep its holidays.
import holidays as _hol
ok("H11 from_text: 'לא נתמך' → not supported", _hol.from_text("לא נתמך") == (0, ""), str(_hol.from_text("לא נתמך")))
ok("H11 from_text: 'לא' / 'no' → not supported", _hol.from_text("לא") == (0, "") and _hol.from_text("no") == (0, ""))
ok("H11 from_text: positives still work", _hol.from_text("כן") == (1, "") and _hol.from_text("נתמך חגים") == (1, "")
   and _hol.from_text("V") == (1, "") and _hol.from_text("כל החגים") == (1, ""))
ok("H12 from_text: 'פסח וסוכות' / 'פסח / סוכות' keep both",
   _hol.from_text("פסח וסוכות") == (1, "סוכות,פסח") and _hol.from_text("פסח / סוכות") == (1, "סוכות,פסח"),
   f"{_hol.from_text('פסח וסוכות')} {_hol.from_text('פסח / סוכות')}")
ok("H12 'ראש השנה ושבועות' keeps a two-word name", _hol.parse_list("ראש השנה ושבועות") == ["ראש השנה", "שבועות"])

# ── RULE 6 (v3.76, יהודה 28/9/2026) — frequency is a HARD gate in every mode ──
# A דו-שבועי/תלת-שבועי/חודשי regular whose turn has not come is OUT of the list
# and the reserve, even with products to spare. Pure checks on selection.is_due.
from datetime import date as _d, timedelta as _tdl
_WED = _d(2026, 7, 1)                       # the Wednesday being prepared
assert _WED.weekday() == 2
def _reg(name, freq, last=None, nxt=None, **kw):
    r = rec(name, priority=4, freq=freq, **kw)
    r["last_distribution"] = last.isoformat() if last else ""
    r["next_distribution"] = nxt.isoformat() if nxt else ""
    return r
ok("F1 דו-שבועי שקיבל שבוע שעבר — לא בתור",
   not selection.is_due(_reg("a", "דו-שבועי", _WED - _tdl(days=7)), _WED))
ok("F1 דו-שבועי שקיבל לפני שבועיים — בתור",
   selection.is_due(_reg("a", "דו-שבועי", _WED - _tdl(days=14)), _WED))
ok("F1 גבול: קיבל שבוע שעבר ביום חמישי (נרשם באיחור) — עדיין לא בתור",
   not selection.is_due(_reg("a", "דו-שבועי", _WED - _tdl(days=6)), _WED))
ok("F2 תלת-שבועי: לפני 14 ימים לא / לפני 21 כן",
   not selection.is_due(_reg("a", "תלת-שבועי", _WED - _tdl(days=14)), _WED)
   and selection.is_due(_reg("a", "תלת-שבועי", _WED - _tdl(days=21)), _WED))
ok("F2 חודשי: לפני 21 ימים לא / לפני 28 כן",
   not selection.is_due(_reg("a", "חודשי", _WED - _tdl(days=21)), _WED)
   and selection.is_due(_reg("a", "חודשי", _WED - _tdl(days=28)), _WED))
ok("F3 שבועי תמיד בתור (גם קיבל שבוע שעבר)",
   selection.is_due(_reg("a", "שבועי", _WED - _tdl(days=7)), _WED))
ok("F3 קבוע בלי תדירות — שער התדירות לא חל",
   selection.is_due(_reg("b", "", _WED - _tdl(days=7)), _WED))
ok("F3 חד-פעמי / בלי עדיפות — בלי הפסקה (0) השער לא חל",
   selection.is_due(rec("o", priority=3, last_distribution=(_WED - _tdl(days=7)).isoformat()), _WED, 0)
   and selection.is_due(rec("c", priority=None, freq="", last_distribution=(_WED - _tdl(days=7)).isoformat()), _WED, 0))
# ── RULE 7 (v3.76, יהודה 28/9/2026) — one-timers rotate: cooldown after receiving ──
_ot = lambda days: rec("o", priority=3, last_distribution=(_WED - _tdl(days=days)).isoformat())
ok("F11 הפסקה 3 שבועות: קיבל לפני 7/14 ימים — לא; לפני 21 — כן",
   not selection.is_due(_ot(7), _WED, 3) and not selection.is_due(_ot(14), _WED, 3)
   and selection.is_due(_ot(21), _WED, 3))
ok("F11 ברירת המחדל = 4 שבועות (יהודה 7/10/2026, היה 3)", selection.ONE_TIME_COOLDOWN_WEEKS_DEFAULT == 4
   and not selection.is_due(_ot(21), _WED) and selection.is_due(_ot(28), _WED))
# N = "חוזר לרשימה N שבועות אחרי שקיבל": 2 = לא פעמיים ברצף; 1 = בלי השפעה בפועל.
ok("F11 הפסקה שבועיים: קיבל שבוע שעבר לא, לפני שבועיים כן",
   not selection.is_due(_ot(7), _WED, 2) and selection.is_due(_ot(14), _WED, 2))
ok("F11 קיבל שבוע שעבר ביום חמישי (נרשם באיחור) — נספר למחזור של שבוע שעבר",
   not selection.is_due(_ot(6), _WED, 2) and selection.is_due(_ot(13), _WED, 2))
ok("F12 חד-פעמי שקיבל במחזור הזה — יוצא מיד (הכרעה 5, 7/10/2026); מעולם לא קיבל — בתור",
   not selection.is_due(_ot(0), _WED, 3) and selection.is_due(rec("n", priority=3), _WED, 3))
ok("F12 ההפסקה חלה גם על מי שאינו קבוע ובלי עדיפות (במצב סינון)",
   not selection.is_due(rec("c", priority=None, freq="", last_distribution=(_WED - _tdl(days=7)).isoformat()), _WED, 3))
ok("F12 ההפסקה לא נוגעת בקבוע שבועי",
   selection.is_due(_reg("w", "שבועי", _WED - _tdl(days=7)), _WED, 3))
ok("F13 not_due_reason לחד-פעמי", selection.not_due_reason(_ot(7), _WED, 3) == "קיבל ב-24/06 · הפסקה של 3 שבועות · חוזר ב-15/07",
   selection.not_due_reason(_ot(7), _WED, 3))
ok("F13 due_filter עם הפסקה: מי שקיבל שבוע שעבר יוצא, ומי שקיבל לפני חודש נשאר",
   [r["id"] for r in selection.due_filter([_ot(7), dict(_ot(28), id="old")], _WED, cooldown_weeks=3)] == ["old"])
ok("F4 קבוע שמעולם לא קיבל — בתור", selection.is_due(_reg("a", "חודשי"), _WED))
# F5 שונה ב-18/10/2026 (כלל 9, הכרעת יהודה): קבוע שקיבל בשבוע החלוקה כבר לא "נשאר ברשימה" —
# הוא יוצא מכל רשימה נוספת של אותו שבוע (היה: is_due(...) == True). ראו R9c.
ok("F5 קיבל במחזור הזה (הרביעי עצמו) — יוצא מרשימה נוספת של אותו שבוע (כלל 9)",
   not selection.is_due(_reg("a", "דו-שבועי", _WED), _WED))
ok("F6 next_distribution הנגזר גובר על החישוב (חלוקת חג לא הזיזה את התור)",
   selection.is_due(_reg("a", "דו-שבועי", _WED - _tdl(days=7), nxt=_WED), _WED)
   and not selection.is_due(_reg("a", "דו-שבועי", _WED - _tdl(days=14), nxt=_WED + _tdl(days=7)), _WED))
ok("F7 due_filter מסנן; ignore=True (חלוקת חג) לא מסנן",
   [r["id"] for r in selection.due_filter(
       [_reg("x", "דו-שבועי", _WED - _tdl(days=7)), _reg("y", "שבועי", _WED - _tdl(days=7))], _WED)] == ["y"]
   and len(selection.due_filter([_reg("x", "דו-שבועי", _WED - _tdl(days=7))], _WED, ignore=True)) == 1)
ok("F8 not_due_reason מסביר בעברית",
   selection.not_due_reason(_reg("a", "דו-שבועי", _WED - _tdl(days=7)), _WED) == "דו-שבועי · קיבל ב-24/06 · התור הבא 08/07"
   and selection.not_due_reason(_reg("a", "שבועי", _WED - _tdl(days=7)), _WED) == "",
   selection.not_due_reason(_reg("a", "דו-שבועי", _WED - _tdl(days=7)), _WED))
ok("F9 next_due = הטבלה האחת: שבועי/דו/תלת/חודשי מרביעי 17/06",
   [selection.next_due("2026-06-17", f).isoformat() for f in ("שבועי", "דו-שבועי", "תלת-שבועי", "חודשי")]
   == ["2026-06-24", "2026-07-01", "2026-07-08", "2026-07-15"],
   str([selection.next_due("2026-06-17", f).isoformat() for f in ("שבועי", "דו-שבועי", "תלת-שבועי", "חודשי")]))
# F10 — the gate runs BEFORE the community balance: a community whose members
# are all not-due can't fill its quota, and the slots move to the others (the
# app never pulls a not-yet-due regular back to fill).
_pool = [dict(_reg(f"A{i}", "דו-שבועי", _WED - _tdl(days=7)), representative="א", souls=5) for i in range(3)] + \
        [dict(_reg(f"B{i}", "שבועי", _WED - _tdl(days=7)), representative="ב", souls=3) for i in range(3)]
_gated = selection.due_filter(_pool, _WED)
_picked = selection.balance_by_community(_gated, {}, W_SOULS, 4)
ok("F10 קהילה שכולה לא-בתור: המכסה עוברת לאחרות ואף לא-בתור לא נשאב להשלמה",
   sorted(r["id"] for r in _picked) == ["B0", "B1", "B2"], str([r["id"] for r in _picked]))

# G — משימה 13: ספירת "נשאר לחד-פעמיים" אחרי הוספה ידנית של קבוע שלא בתורו
_man = [dict(_reg("m1", "דו-שבועי", _WED - _tdl(days=7)), _extra=True),     # קבוע ידני — תופס מקום
        dict(_reg("m2", "חודשי", _WED - _tdl(days=7)), _extra=True, _reserve=True),  # רזרבה — לא תופס
        dict(rec("o1", 3), _extra=True),                                   # חד-פעמי — לא "קבוע ידני"
        _reg("w1", "שבועי", _WED - _tdl(days=7))]                          # בסיס (לא ידני)
ok("G1 manual_regular_ids: רק קבוע שנוסף ידנית ולא רזרבה",
   selection.manual_regular_ids(_man, reserve_ids={"m2"}) == {"m1"},
   str(selection.manual_regular_ids(_man, reserve_ids={"m2"})))
ok("G2 manual_regular_ids: אין ידניים → ריק", selection.manual_regular_ids([_reg("w", "שבועי", None)]) == set())
ok("G3 one_time_slots: 15 מוצרים, 10 קבועים → 5; עם 1 ידני → 4",
   selection.one_time_slots(15, 10) == 5 and selection.one_time_slots(15, 10, 1) == 4)
ok("G4 one_time_slots: לא יורד מתחת ל-0", selection.one_time_slots(10, 10, 3) == 0 and selection.one_time_slots(0, 5) == 0)

# ── 7/10/2026 (יהודה): נוסחה קבועה לתור החד-פעמיים; רזרבה ב-filter; חד-פעמי שקיבל ──
print("\n── חבילה א' (7/10/2026) ──")
_W_IGN = {"money": 0, "souls": 100, "recency": 0, "income": 0, "housing": 0, "medical": 0}
_x = rec("x-נפשות", 3, souls=9, days_since=1, per_soul="1000")
_y = rec("y-המתנה", 3, souls=1, days_since=400, per_soul="1000")
_o1 = [r["full_name"] for r in selection.rank_one_time_priority([dict(_x), dict(_y)], _W_IGN)]
_o2 = [r["full_name"] for r in selection.rank_one_time_priority([dict(_x), dict(_y)], {"souls": 0, "recency": 100})]
ok("A2 תור חד-פעמיים: משקלי ההגדרות מתעלמים — אותו סדר בכל משקל; המתנה (50%) גוברת על נפשות (25%)",
   _o1 == _o2 == ["y-המתנה", "x-נפשות"], f"{_o1} {_o2}")
ok("A2 הקבוע = 50/25/25", scoring.ONE_TIME_QUEUE_WEIGHTS["recency"] == 50
   and scoring.ONE_TIME_QUEUE_WEIGHTS["money"] == 25 and scoring.ONE_TIME_QUEUE_WEIGHTS["souls"] == 25)
# א1 — חריג קיצוני לא משטח את השאר (גם במצבי scored/filter/none)
_ext = [dict(rec("e%d" % i, None, per_soul=str(1000 + 100 * i))) for i in range(4)] + \
       [dict(rec("חריג", None, per_soul="-9999999"))]
_sc = {r["full_name"]: r["need_score"] for r in selection.rank_by_need(_ext, {"money": 100, "souls": 0, "recency": 0, "income": 0, "housing": 0, "medical": 0})}
ok("A1 חריג קיצוני לא משטח: ארבעת האחרים עדיין שונים זה מזה ובמדרגות שוות",
   _sc["חריג"] == 100 and len({_sc["e%d" % i] for i in range(4)}) == 4
   and abs((_sc["e0"] - _sc["e1"]) - (_sc["e1"] - _sc["e2"])) < 0.2, str(_sc))
# א4 — חד-פעמי שקיבל היום יוצא; (עד 18/10/2026 גם: קבוע שבועי שקיבל היום נשאר —
# שונה בכלל 9: גם הוא יוצא מרשימה נוספת של אותו שבוע, ראו R9b/R9c)
_today_s = _WED.isoformat()
ok("A4 חד-פעמי שקיבל היום — לא ב-is_due; גם קבוע שבועי שקיבל היום — לא (כלל 9)",
   not selection.is_due(rec("ot", 3, last_distribution=_today_s), _WED)
   and not selection.is_due(_reg("wk", "שבועי", _WED), _WED))
# א5 — רזרבה ב-filter, עם ובלי איזון קהילות
_rows5 = [crec("א%d" % i, "נציג א", 500 + 100 * i) for i in range(3)] + \
         [crec("ב%d" % i, "נציג ב", 900 + 100 * i) for i in range(5)]
_crit5 = {"income": {"min": None, "max": 5000}}
_bal = selection.balance_by_community([dict(r) for r in _rows5], _crit5, W_INCOME, 4, None, reserve_count=2)
_mains = [r for r in _bal if not r["_reserve"]]; _res = [r for r in _bal if r["_reserve"]]
ok("A5 filter + איזון קהילות: N=4 ראשיים + R=2 רזרבה מסומנים, ללא חפיפה",
   len(_mains) == 4 and len(_res) == 2 and not ({r["id"] for r in _mains} & {r["id"] for r in _res})
   and _bal[-2:] == _res, str([(r["id"], r["_reserve"]) for r in _bal]))
ok("A5 הרזרבה היא מכל הקהילות יחד (לא מכסה לכל קהילה)",
   len(_bal) == 6 and all(r["_role"] in (selection.ROLE_MAIN, selection.ROLE_RESERVE) for r in _bal))
_nb = selection.balance_by_community([dict(r) for r in _rows5], _crit5, W_INCOME, 4, None)
ok("A5 בלי רזרבה (R=0) — בדיוק N, בלי סימון רזרבה", len(_nb) == 4 and not any(r.get("_reserve") for r in _nb))

# ── כלל 9 (יהודה 18/10/2026) — מי שכבר קיבל בשבוע החלוקה לא נכנס לרשימה נוספת ──
# התקרית: רון הוציא שתי חלוקות ביום ראשון; הראשונה נרשמה (חלוקה נוספת — התור לא זז),
# ואותם חודשיים/דו-שבועיים נכנסו שוב לשנייה (ובביום רביעי היו נכנסים בפעם השלישית).
print("\n── כלל 9: קיבל בשבוע החלוקה (א'–ד') — לא ברשימה נוספת ──")
_sun9 = _WED - _tdl(days=3)
ok("R9a חודשי שקיבל ביום ראשון (חלוקה נוספת, התור עדיין ברביעי) — לא בתור [המקרה של רון]",
   not selection.is_due(_reg("a", "חודשי", _sun9, nxt=_WED), _WED))
ok("R9a דו-שבועי שקיבל ביום ראשון — לא בתור",
   not selection.is_due(_reg("a", "דו-שבועי", _sun9, nxt=_WED), _WED))
ok("R9b שבועי שקיבל ביום שני / שלישי — לא בתור",
   not selection.is_due(_reg("w", "שבועי", _WED - _tdl(days=2)), _WED)
   and not selection.is_due(_reg("w", "שבועי", _WED - _tdl(days=1)), _WED))
ok("R9c קיבל ברביעי עצמו — לא בתור (במקום 'נשאר ברשימה' הישן)",
   not selection.is_due(_reg("a", "דו-שבועי", _WED), _WED)
   and not selection.is_due(_reg("w", "שבועי", _WED), _WED))
ok("R9d גבול: חמישי / שבת שלפני (נרשם באיחור לרביעי הקודם) — שבועי עדיין בתור",
   selection.is_due(_reg("w", "שבועי", _WED - _tdl(days=6)), _WED)
   and selection.is_due(_reg("w", "שבועי", _WED - _tdl(days=4)), _WED))
ok("R9d גבול: יום ראשון הקודם (שבוע לפני) — שבועי בתור, חודשי שתורו הגיע בתור",
   selection.is_due(_reg("w", "שבועי", _sun9 - _tdl(days=7)), _WED)
   and selection.is_due(_reg("m", "חודשי", _sun9 - _tdl(days=7), nxt=_WED), _WED))
ok("R9e קבוע שמעולם לא קיבל — בתור", selection.is_due(_reg("n", "שבועי"), _WED))
ok("R9f חלוקת חג (ignore=True) לא מסננת גם את מי שקיבל השבוע",
   len(selection.due_filter([_reg("x", "דו-שבועי", _sun9, nxt=_WED)], _WED, ignore=True)) == 1)
ok("R9g הכלל חל על קבועים: חד-פעמי עם הפסקה כבויה (0) שקיבל ביום ראשון — כמו קודם, בתור",
   selection.is_due(rec("o", priority=3, last_distribution=_sun9.isoformat()), _WED, 0))
ok("R9h not_due_reason מסביר מי שקיבל השבוע",
   selection.not_due_reason(_reg("a", "חודשי", _sun9, nxt=_WED), _WED) == "חודשי · קיבל ב-28/06 · כבר בחלוקה של השבוע",
   selection.not_due_reason(_reg("a", "חודשי", _sun9, nxt=_WED), _WED))
ok("R9i received_this_round: טהור — חלון ראשון עד רביעי בלבד",
   selection.received_this_round(_reg("a", "חודשי", _sun9), _WED)
   and selection.received_this_round(_reg("a", "חודשי", _WED), _WED)
   and not selection.received_this_round(_reg("a", "חודשי", _sun9 - _tdl(days=1)), _WED)
   and not selection.received_this_round(_reg("a", "חודשי"), _WED))

# ── אותו כלל דרך ה-DB, בכל יום בשבוע (גם get_weekly_list של מצב 'רגיל') ──
from datetime import date as _dr9
_Real9 = db.date
for _off9 in range(7):
    _ft9 = _dr9.today() + timedelta(days=_off9)
    class _Fake9(_Real9):
        @classmethod
        def today(cls, _d=_ft9):
            return _Real9(_d.year, _d.month, _d.day)
    db.date = _Fake9
    try:
        db.reset_all_data()
        _bw9 = _ft9 if _ft9.weekday() == 2 else selection.next_wednesday(_ft9)
        # היום הראשון האחרון שלא אחרי היום (בפועל: מה שאפשר כבר לרשום)
        _rsun = _ft9 - timedelta(days=(_ft9.weekday() + 1) % 7)
        _in_window = _bw9 - timedelta(days=3) <= _rsun <= _bw9
        _ids9 = {}
        for _nm, _fq, _wk in (("חודשי", "חודשי", 28), ("דו-שבועי", "דו-שבועי", 14), ("שבועי", "שבועי", 7)):
            _rid = db.add_recipient({"full_name": f"ר9-{_nm}", "status": "פעיל", "frequency": _fq, "priority": 4})
            _row9 = [{"id": _rid, "full_name": f"ר9-{_nm}", "frequency": _fq}]
            db.bulk_add_distributions(_row9, (_bw9 - timedelta(days=_wk)).isoformat(), "", 1, "")   # רביעי רגיל → תורו ברביעי הקרוב
            db.bulk_add_distributions(_row9, _rsun.isoformat(), "", 1, "")                          # ראשון = חלוקה נוספת (רישום של רון)
            _ids9[_nm] = _rid
        _ctl = db.add_recipient({"full_name": "ר9-ביקורת", "status": "פעיל", "frequency": "חודשי", "priority": 4})
        db.bulk_add_distributions([{"id": _ctl, "full_name": "ר9-ביקורת", "frequency": "חודשי"}],
                                  (_bw9 - timedelta(days=28)).isoformat(), "", 1, "")                # תורו הגיע, לא קיבל השבוע
        _wk9 = {r["full_name"] for r in db.get_weekly_list()}
        _got = {n for n in ("ר9-חודשי", "ר9-דו-שבועי", "ר9-שבועי") if n in _wk9}
    finally:
        db.date = _Real9
    # בשבוע החלוקה: אף אחד מהם לא ברשימה. בשבוע הבא (חמישי–שבת): חלוקת הראשון הייתה רגילה (לא סומנה בונוס)
    # ולכן הזיזה את התור — השבועי חוזר, החודשי והדו-שבועי לא (התור שלהם התקדם מהראשון).
    ok(f"R9j get_weekly_list [יום {_ft9.weekday()}, ראשון האחרון {_rsun}, רביעי {_bw9}]: "
       + ("מי שקיבל ביום ראשון של השבוע הזה — לא ברשימה" if _in_window
          else "ראשון רגיל של שבוע קודם — השבועי חוזר, החודשי והדו-שבועי התור שלהם התקדם"),
       (_got == set() if _in_window else _got == {"ר9-שבועי"}) and "ר9-ביקורת" in _wk9,
       f"in_window={_in_window} got={sorted(_got)} all={sorted(_wk9)}")

# ── בונוס / חג: חלוקה שסומנה כנוספת לא מבטלת ולא מזיזה (הכרעת יהודה 18/10/2026) ──
import holidays as _hol9
_wedT = _dr9.today() + timedelta(days=(2 - _dr9.today().weekday()) % 7)      # רביעי הקרוב (או היום)
class _FakeB(_Real9):                                    # "היום" = יום הרביעי עצמו, כדי שהסבב כולו כבר קרה
    @classmethod
    def today(cls):
        return _Real9(_wedT.year, _wedT.month, _wedT.day)
for _code, _lbl in ((_hol9.BONUS, "בונוס"), (_hol9.ANY, "חג")):
    for _gap, _day in ((3, "ראשון"), (0, "רביעי")):
        db.date = _FakeB
        try:
            db.reset_all_data()
            _recb = {}
            for _nm, _fq, _wk in (("חודשי", "חודשי", 28), ("דו-שבועי", "דו-שבועי", 14), ("שבועי", "שבועי", 7)):
                _rid = db.add_recipient({"full_name": f"ב-{_nm}", "status": "פעיל", "frequency": _fq, "priority": 4})
                _rw = [{"id": _rid, "full_name": f"ב-{_nm}", "frequency": _fq}]
                db.bulk_add_distributions(_rw, (_wedT - timedelta(days=_wk)).isoformat(), "", 1, "")   # רביעי רגיל — תורו ברביעי
                db.bulk_add_distributions(_rw, (_wedT - timedelta(days=_gap)).isoformat(), "", 1, "", holiday=_code)
                _recb[_nm] = _rid
            _wkb = {r["full_name"] for r in db.get_weekly_list()}
            _nxt = {n: db.get_recipient(i)["next_distribution"] for n, i in _recb.items()}
        finally:
            db.date = _Real9
        ok(f"R9l חלוקת {_lbl} שנרשמה ב{_day} לא מוציאה מהרשימה ולא מזיזה את התור",
           _wkb == {"ב-חודשי", "ב-דו-שבועי", "ב-שבועי"}
           and _nxt["חודשי"] == _wedT.isoformat() and _nxt["דו-שבועי"] == _wedT.isoformat(),
           f"list={sorted(_wkb)} next={_nxt} wed={_wedT}")

# חלוקה רגילה (לא מסומנת) ביום ראשון נספרת לרביעי שאחריה: הכרטיס והרשימה מתאימים — לא "באיחור"
db.date = _FakeB
try:
    db.reset_all_data()
    _rn = db.add_recipient({"full_name": "ר9-שבועי-ראשון", "status": "פעיל", "frequency": "שבועי", "priority": 4})
    _rnw = [{"id": _rn, "full_name": "ר9-שבועי-ראשון", "frequency": "שבועי"}]
    db.bulk_add_distributions(_rnw, (_wedT - timedelta(days=7)).isoformat(), "", 1, "")
    db.bulk_add_distributions(_rnw, (_wedT - timedelta(days=3)).isoformat(), "", 1, "")      # ראשון רגיל
    _nn = db.get_recipient(_rn)["next_distribution"]
    _onlist = "ר9-שבועי-ראשון" in {r["full_name"] for r in db.get_weekly_list()}
finally:
    db.date = _Real9
ok("R9n שבועי שנרשם ביום ראשון (רגיל): לא ברשימת הרביעי, והחלוקה הבאה בכרטיס = הרביעי שאחריו",
   not _onlist and _nn == (_wedT + timedelta(days=7)).isoformat(), f"onlist={_onlist} next={_nn} wed={_wedT}")

# …ולפני 18/10/2026 חלוקה בימים א'–ג' עדיין "נוספת" אוטומטית (שום תור עבר לא זז)
class _FakeLeg(_Real9):
    @classmethod
    def today(cls):
        return _Real9(2026, 10, 14)                       # רביעי
db.date = _FakeLeg
try:
    db.reset_all_data()
    _rl = db.add_recipient({"full_name": "ישן-חודשי", "status": "פעיל", "frequency": "חודשי", "priority": 4})
    _rwl = [{"id": _rl, "full_name": "ישן-חודשי", "frequency": "חודשי"}]
    db.bulk_add_distributions(_rwl, "2026-09-16", "", 1, "")          # רביעי רגיל → התור 14/10
    db.bulk_add_distributions(_rwl, "2026-10-11", "", 1, "")          # ראשון ישן, לא מסומן → נוספת אוטומטית (לפני החיתוך)
    _lw = {r["full_name"] for r in db.get_weekly_list()}
    _ln = db.get_recipient(_rl)["next_distribution"]
finally:
    db.date = _Real9
ok("R9m חלוקת ראשון לפני 18/10/2026 (לא מסומנת) עדיין נוספת: התור לא זז והמקבל ברשימה",
   "ישן-חודשי" in _lw and _ln == "2026-10-14", f"list={sorted(_lw)} next={_ln}")

# …ועל התאריך האמיתי גם שאר המצבים (ניקוד / כל המקבלים) — אותה שער
db.reset_all_data()
_todayR = _dr9.today()
_bwR = _todayR if _todayR.weekday() == 2 else selection.next_wednesday(_todayR)
_rsunR = _todayR - timedelta(days=(_todayR.weekday() + 1) % 7)
_inR = _bwR - timedelta(days=3) <= _rsunR <= _bwR
_ridR = db.add_recipient({"full_name": "ר9-מצבים", "status": "פעיל", "frequency": "חודשי", "priority": 4})
_rowR = [{"id": _ridR, "full_name": "ר9-מצבים", "frequency": "חודשי"}]
db.bulk_add_distributions(_rowR, (_bwR - timedelta(days=28)).isoformat(), "", 1, "")
db.bulk_add_distributions(_rowR, _rsunR.isoformat(), "", 1, "")
ok("R9k get_scored_all / get_regulars_scored מסננים כמו get_weekly_list",
   (("ר9-מצבים" in {r["full_name"] for r in db.get_scored_all()}) != _inR)
   and (("ר9-מצבים" in {r["full_name"] for r in db.get_regulars_scored()}) != _inR),
   f"in_window={_inR}")

# ── הכנה קדימה, שלב 1 (יהודה 18/10/2026): הרשימה עוקבת אחרי התאריך שנבחר (on_date) ──
# אחרי שנרשמה חלוקת השבוע, רשימת השבוע הבא מציגה רק מי שתורו הגיע ביום ההוא —
# ובלי לכתוב ל-DB שום תאריך נגזר (התחזית קריאה-בלבד).
print("\n── הכנה קדימה: on_date ──")
db.date = _FakeB                                         # "היום" = רביעי הקרוב (או היום)
try:
    db.reset_all_data()
    _ids10 = {}
    for _nm, _fq in (("שבועי", "שבועי"), ("דו-שבועי", "דו-שבועי"), ("חודשי", "חודשי")):
        _r10 = db.add_recipient({"full_name": f"ק-{_nm}", "status": "פעיל", "frequency": _fq, "priority": 4, "souls": 3})
        db.bulk_add_distributions([{"id": _r10, "full_name": f"ק-{_nm}", "frequency": _fq}], _wedT.isoformat(), "", 1, "")
        _ids10[_nm] = _r10
    _never = db.add_recipient({"full_name": "ק-טרם-קיבל", "status": "פעיל", "frequency": "שבועי", "priority": 4})
    _nd_before = db.get_recipient(_never)["next_distribution"]
    _names = lambda rows: {r["full_name"] for r in rows}
    _cur = _names(db.get_weekly_list())
    _w1 = _names(db.get_weekly_list(on_date=_wedT + timedelta(days=7)))
    _w2 = _names(db.get_weekly_list(on_date=_wedT + timedelta(days=14)))
    _w4 = _names(db.get_weekly_list(on_date=_wedT + timedelta(days=28)))
    _nd_after = db.get_recipient(_never)["next_distribution"]
    _sa1 = _names(db.get_scored_all(on_date=_wedT + timedelta(days=7)))
    _rs1 = _names(db.get_regulars_scored(on_date=_wedT + timedelta(days=7)))
    _n_sug, _reg_sug = db.compute_suggested_n(10, on_date=_wedT + timedelta(days=7))
finally:
    db.date = _Real9
ok("R10a השבוע הנוכחי (בלי on_date): מי שנרשם עכשיו לא ברשימה, רק מי שטרם קיבל",
   _cur == {"ק-טרם-קיבל"}, str(sorted(_cur)))
ok("R10b שבוע הבא: השבועי חוזר, הדו-שבועי והחודשי עוד לא (התור שלהם מתקדם)",
   _w1 == {"ק-שבועי", "ק-טרם-קיבל"}, str(sorted(_w1)))
ok("R10c בעוד שבועיים: גם הדו-שבועי; בעוד 4 שבועות: גם החודשי",
   _w2 == {"ק-שבועי", "ק-דו-שבועי", "ק-טרם-קיבל"} and _w4 == {"ק-שבועי", "ק-דו-שבועי", "ק-חודשי", "ק-טרם-קיבל"},
   f"{sorted(_w2)} | {sorted(_w4)}")
ok("R10d התחזית לשבוע עתידי לא כותבת next_distribution של מי שטרם קיבל",
   _nd_before == _nd_after, f"{_nd_before} -> {_nd_after}")
ok("R10e גם 'כל המקבלים' ו'קבועים לפי ניקוד' עוקבים אחרי התאריך",
   {"ק-שבועי"} <= _sa1 and "ק-חודשי" not in _sa1 and "ק-דו-שבועי" not in _sa1
   and {"ק-שבועי"} <= _rs1 and "ק-חודשי" not in _rs1, f"{sorted(_sa1)} | {sorted(_rs1)}")
ok("R10f compute_suggested_n לפי התאריך: 2 קבועים בתור בשבוע הבא (שבועי + טרם קיבל)",
   _reg_sug == 2 and _n_sug == 8, f"reg={_reg_sug} n={_n_sug}")

print()
print("RESULT:", "ALL SELECTION SCENARIOS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

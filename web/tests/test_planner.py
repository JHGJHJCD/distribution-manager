# -*- coding: utf-8 -*-
"""The forward planner (web/planner.py) — pure, invented people only.

Run:  <python 3.12> web/tests/test_planner.py
Each block names the rule it protects (numbers = the rules in CLAUDE.md / rules.md).
"""
import copy
import random
from datetime import date, timedelta

from _util import Checker, W0, got, guids, person, wk

from web import planner
from web.engine import scoring, selection

t = Checker("web planner")
WEIGHTS = planner.need_weights({})
INTERVAL = {"שבועי": 7, "דו-שבועי": 14, "תלת-שבועי": 21, "חודשי": 28}


def plan(recs, hist, weeks=1, portions=52, reserve=0, cooldown=4, start=W0, horizon=None, per_week=None):
    return planner.plan_weeks(recs, hist, start=start, weeks=weeks, horizon=horizon or start,
                              weights=WEIGHTS, cooldown_weeks=cooldown, portions=portions,
                              reserve=reserve, per_week=per_week)


# ── P1: one ordinary week ─────────────────────────────────────────────────────
recs = [person(1, "שבועי"), person(2, "שבועי"), person(3, "שבועי"),
        person(4, "דו-שבועי"), person(5, "דו-שבועי"), person(6, "חודשי"),
        person(11, "חד-פעמי", 3, per_soul="100"), person(12, "חד-פעמי", 3, per_soul="900"),
        person(13, "חד-פעמי", 2, per_soul="50"), person(14, "חד-פעמי", 2, per_soul="700"),
        person(15, "חד-פעמי", 2, per_soul="800"),
        person(16, "חד-פעמי", None), person(17, "", 1), person(18, "שבועי", status="מושהה")]
hist = ([got(f"g{n:04d}", wk(-1)) for n in (1, 2, 3, 5)]
        + [got("g0004", wk(-2)), got("g0006", wk(-2))])
w = plan(recs, hist, portions=6, reserve=2)[0]
t.ok("P1 due regulars = 3 weekly + the bi-weekly of two weeks ago",
     sorted(e["guid"] for e in w["main"] if e["kind"] == "regular") == ["g0001", "g0002", "g0003", "g0004"],
     str(guids(w["main"])))
t.ok("P1 the two remaining portions go to one-timers, first priority first",
     [e["guid"] for e in w["main"] if e["kind"] == "onetime"] == ["g0011", "g0012"], str(guids(w["main"])))
t.ok("P1 list = exactly the portions", len(w["main"]) == 6 and w["empty_portions"] == 0)
t.ok("P1 reserve = the next two in the one-timers' queue", len(w["reserve_list"]) == 2
     and all(e["kind"] == "onetime" and e["priority"] == 2 for e in w["reserve_list"]))
out = {e["guid"]: e for e in w["out"]}
t.ok("P1 bi-weekly served last week is out, with the next turn in the reason",
     "g0005" in out and out["g0005"]["group"] == planner.OUT_REG_WAIT and wk(1).strftime("%d/%m") in out["g0005"]["why"],
     out.get("g0005", {}).get("why", ""))
t.ok("P1 monthly served two weeks ago is out until his turn",
     "g0006" in out and wk(2).strftime("%d/%m") in out["g0006"]["why"], out.get("g0006", {}).get("why", ""))
t.ok("P1 the last one-timer waits in the queue", sum(1 for e in w["out"] if e["group"] == planner.OUT_ONE_QUEUE) == 1)
everyone = set(guids(w["main"])) | set(guids(w["reserve_list"])) | set(out)
t.ok("P1 a one-timer without priority, a card without frequency and a paused card are on no list",
     not ({"g0016", "g0017", "g0018"} & everyone))
t.ok("P1 every entry carries an explanation",
     all(e["why"].strip() for e in w["main"] + w["reserve_list"] + w["out"]))
t.ok("P1 counts by type", w["main_regulars"] == 4 and w["main_one_timers"] == 2 and w["regulars_due"] == 4
     and w["counts"].get("שבועי") == 3 and w["counts"].get("דו-שבועי") == 1 and w["counts"].get("חד-פעמי") == 2)

# ── P2: turns over many weeks (rule 6) ────────────────────────────────────────
recs = [person(1, "שבועי"), person(2, "דו-שבועי"), person(3, "תלת-שבועי"), person(4, "חודשי")]
hist = [got("g0001", wk(-1)), got("g0002", wk(-1)), got("g0003", wk(-1)), got("g0004", wk(-1))]
weeks = plan(recs, hist, weeks=12)
when = {g: [i for i, w in enumerate(weeks) if g in guids(w["main"])] for g in ("g0001", "g0002", "g0003", "g0004")}
t.ok("P2 weekly receives every week", when["g0001"] == list(range(12)), str(when["g0001"]))
t.ok("P2 bi-weekly every second week, first one week after last week's", when["g0002"] == [1, 3, 5, 7, 9, 11], str(when["g0002"]))
t.ok("P2 tri-weekly every third week", when["g0003"] == [2, 5, 8, 11], str(when["g0003"]))
t.ok("P2 monthly every fourth week (28 days)", when["g0004"] == [3, 7, 11], str(when["g0004"]))

# ── P3: never served -> due at once; an extra round does not move the turn ────
recs = [person(1, "חודשי"), person(2, "חודשי"), person(3, "חודשי"), person(4, "שבועי")]
hist = [got("g0002", wk(-1), holiday="פסח"), got("g0003", wk(-1), holiday="בונוס")]
w = plan(recs, hist)[0]
t.ok("P3 a monthly regular who never received is due at once", "g0001" in guids(w["main"]))
t.ok("P3 a holiday round last week does not move the turn", "g0002" in guids(w["main"]))
t.ok("P3 a bonus round last week does not move the turn", "g0003" in guids(w["main"]))
t.ok("P3 is_extra_round: marked rounds, and Sun–Tue before the cut-over only",
     planner.is_extra_round("2026-11-22", "חג") and planner.is_extra_round("2026-10-11", "")
     and not planner.is_extra_round("2026-10-18", "") and not planner.is_extra_round("2026-11-22", "")
     and not planner.is_extra_round("2026-10-07", ""))

# ── P4: rule 9 — one portion per distribution week ────────────────────────────
recs = [person(1, "שבועי"), person(2, "שבועי"), person(3, "שבועי"), person(4, "דו-שבועי")]
monday = W0 - timedelta(days=2)
hist = [got("g0001", monday), got("g0002", monday, holiday="בונוס"), got("g0003", W0 - timedelta(days=4)),
        got("g0004", monday)]
weeks = plan(recs, hist, weeks=3)
t.ok("P4 a regular served on Monday of this week is not on Wednesday's list",
     "g0001" not in guids(weeks[0]["main"]) and "כבר בחלוקה של השבוע" in
     next(e["why"] for e in weeks[0]["out"] if e["guid"] == "g0001"))
t.ok("P4 ...and is back next week", "g0001" in guids(weeks[1]["main"]))
t.ok("P4 a bonus round on Monday does not take him off the list", "g0002" in guids(weeks[0]["main"]))
t.ok("P4 a round on Saturday belongs to LAST week (weekly is due again)", "g0003" in guids(weeks[0]["main"]))
t.ok("P4 a Monday round moves a bi-weekly turn from THIS Wednesday", [("g0004" in guids(w["main"])) for w in weeks] == [False, False, True])

# ── P5: a no-show row and a typo date in the future never count ───────────────
recs = [person(1, "חודשי"), person(2, "חודשי"), person(3, "חודשי", last_dist_base=wk(5).isoformat())]
hist = [got("g0001", wk(-1), received=0), got("g0002", wk(3)), {"recipient_guid": "g0002", "dist_date": "25/11/2026", "received": 1, "holiday": ""}]
w = plan(recs, hist)[0]
t.ok("P5 a recorded no-show did not receive: still due", "g0001" in guids(w["main"]))
t.ok("P5 a history date after the upcoming Wednesday is ignored, junk dates too", "g0002" in guids(w["main"]))
t.ok("P5 a base date in the future is ignored", "g0003" in guids(w["main"]))
recs = [person(1, "חודשי", last_dist_base=wk(-1).isoformat())]
t.ok("P5 an imported base date counts like a regular round", plan(recs, [])[0]["main"] == []
     and [bool(w["main"]) for w in plan(recs, [], weeks=4)] == [False, False, False, True])

# ── P6: rule 8 — never more people than portions; who waited longest ──────────
recs = [person(n, "שבועי") for n in range(1, 11)] + [person(n, "חד-פעמי", 3) for n in range(21, 27)]
hist = [got(f"g{n:04d}", wk(-n)) for n in range(1, 11)]           # g0010 waited longest
w = plan(recs, hist, portions=4, reserve=3)[0]
t.ok("P6 four portions -> the four who waited longest", guids(w["main"]) == ["g0010", "g0009", "g0008", "g0007"], str(guids(w["main"])))
t.ok("P6 reserve = the next three regulars", guids(w["reserve_list"]) == ["g0006", "g0005", "g0004"], str(guids(w["reserve_list"])))
t.ok("P6 the other three are off the list, marked as cut",
     sorted(e["guid"] for e in w["out"] if e["group"] == planner.OUT_REG_CUT) == ["g0001", "g0002", "g0003"])
t.ok("P6 a one-timer never pushes a regular out: none on the list", w["main_one_timers"] == 0 and w["cut"] and w["warnings"])
w = plan(recs, hist, portions=8, reserve=5)[0]
t.ok("P6 rule 3: reserve is topped up from the one-timers' queue (2 regulars + 3 one-timers)",
     [e["kind"] for e in w["reserve_list"]] == ["regular", "regular", "onetime", "onetime", "onetime"],
     str([e["kind"] for e in w["reserve_list"]]))
# the same reserve the engine's own top_up_reserve gives for the list as shown
people = planner.active_people(recs)
led = planner.Ledger(W0).load(hist)
due = [planner.week_row(p, W0, led) for p in people if selection.is_regular(p)]
kept = selection.limit_due_regulars(due, WEIGHTS, 8, 5, 0)
queue = selection.rank_one_time_priority([planner.week_row(p, W0, led) for p in people if selection.is_one_time_candidate(p)])
shown = selection.top_up_reserve(kept, 5, 8, queue)
t.ok("P6 ...identical to selection.top_up_reserve", [r["guid"] for r in shown if r.get("_reserve")] == guids(w["reserve_list"]))
weeks = plan(recs, hist, weeks=3, portions=4, reserve=3)
t.ok("P6 next week the ones who were cut come first (the reserve did not receive)",
     set(guids(weeks[1]["main"])) == {"g0006", "g0005", "g0004", "g0003"}, str(guids(weeks[1]["main"])))

# ── P7: rule 7 — one-timers rotate ────────────────────────────────────────────
recs = [person(1, "שבועי")] + [person(n, "חד-פעמי", 3) for n in range(21, 24)]
weeks = plan(recs, [], weeks=10, portions=2, reserve=0, cooldown=4)
seq = [next((e["guid"] for e in w["main"] if e["kind"] == "onetime"), None) for w in weeks]
t.ok("P7 three one-timers, one portion a week, pause of 4 weeks: each returns after 4 weeks, one week stays empty",
     seq[:3].count(None) == 0 and len(set(seq[:3])) == 3 and seq[3] is None and seq[4:7] == seq[:3] and seq[7] is None, str(seq))
gaps_ok = all((j - i) >= 4 for g in set(filter(None, seq))
              for i, j in zip([k for k, s in enumerate(seq) if s == g], [k for k, s in enumerate(seq) if s == g][1:]))
t.ok("P7 nobody returns inside the pause", gaps_ok, str(seq))
t.ok("P7 the empty week says so", weeks[3]["empty_portions"] == 1 and any("בלי מקבל" in x for x in weeks[3]["warnings"]))
pause = next(e for e in weeks[1]["out"] if e["group"] == planner.OUT_ONE_PAUSE)
t.ok("P7 the reason names the day he is back", wk(4).strftime("%d/%m") in pause["why"] and "הפסקה של 4 שבועות" in pause["why"], pause["why"])
weeks = plan(recs, [], weeks=6, portions=2, cooldown=0)
seq0 = [next((e["guid"] for e in w["main"] if e["kind"] == "onetime"), None) for w in weeks]
t.ok("P7 pause 0 = no forced pause: no empty week, the queue itself still takes turns (waiting is half the score)",
     all(seq0) and len(set(seq0[:3])) == 3 and seq0[3:] == seq0[:3], str(seq0))
recs = [person(21, "חד-פעמי", 3), person(22, "חד-פעמי", 2)]
w = plan(recs, [got("g0021", wk(-1), holiday="פסח"), got("g0022", wk(-1), holiday="בונוס")], portions=5)[0]
t.ok("P7 a holiday or bonus portion is an extra: it starts no pause (decision 26/11/2026, 'חג לא נספר')",
     guids(w["main"]) == ["g0021", "g0022"])
w = plan(recs, [got("g0021", wk(-1), holiday="פסח"), got("g0021", wk(-2))], portions=5)[0]
t.ok("P7 ...the pause is counted from his last REGULAR round, whatever extra he got since",
     guids(w["main"]) == ["g0022"] and wk(2).strftime("%d/%m") in next(e["why"] for e in w["out"] if e["guid"] == "g0021"))

# ── P8: rule 1 — priority first in the one-timers' queue ──────────────────────
recs = ([person(n, "חד-פעמי", 2, per_soul="10", souls=9) for n in range(1, 5)]
        + [person(n, "חד-פעמי", 3, per_soul="5000", souls=1) for n in range(5, 8)])
w = plan(recs, [], portions=4)[0]
t.ok("P8 every first priority before any second, whatever the score",
     [e["priority"] for e in w["main"]] == [3, 3, 3, 2], str([e["priority"] for e in w["main"]]))
t.ok("P8 the queue place is shown", [e["place"] for e in w["main"]] == [1, 2, 3, 4])

# ── P9: 0 portions; a single week with its own number of portions ─────────────
recs = [person(1, "שבועי"), person(2, "שבועי"), person(21, "חד-פעמי", 3)]
weeks = plan(recs, [got("g0001", wk(-1)), got("g0002", wk(-1))], weeks=3, portions=5,
             per_week={wk(1): {"portions": 0}})
t.ok("P9 a week with 0 portions is empty and says why", weeks[1]["main"] == [] and weeks[1]["reserve_list"] == []
     and all(e["group"] == planner.OUT_NO_PORTIONS for e in weeks[1]["out"] if e["guid"] in ("g0001", "g0002")))
t.ok("P9 nobody was recorded for it: the same people are due the week after", set(guids(weeks[2]["main"])) >= {"g0001", "g0002"})
weeks = plan(recs, [], weeks=3, portions=5, per_week={wk(1): {"portions": 1, "reserve": 1}})
t.ok("P9 one week with 1 portion: one receives, one is reserve, the other weeks are untouched",
     len(weeks[0]["main"]) == 3 and len(weeks[1]["main"]) == 1 and len(weeks[1]["reserve_list"]) == 1 and len(weeks[2]["main"]) >= 2)

# ── P10: a regular marked 'קבוע' (priority 4) without a frequency = weekly ────
recs = [person(1, "", 4), person(2, "", 1)]
weeks = plan(recs, [got("g0001", wk(-1))], weeks=3)
t.ok("P10 priority 4 without a frequency receives every week", all(guids(w["main"]) == ["g0001"] for w in weeks))

# ── P11: pure — inputs untouched, same answer twice, "now" data decides ───────
recs = [person(n, f) for n, f in enumerate(["שבועי", "דו-שבועי", "חודשי", "תלת-שבועי"] * 3, 1)] + \
       [person(n, "חד-פעמי", random.Random(n).choice([3, 2]), per_soul=str(n * 37 % 900)) for n in range(40, 70)]
hist = [got(f"g{n:04d}", wk(-(n % 4) - 1)) for n in range(1, 13)]
before = copy.deepcopy((recs, hist))
a = plan(recs, hist, weeks=8, portions=14, reserve=4)
b = plan(recs, hist, weeks=8, portions=14, reserve=4)
t.ok("P11 the inputs are not modified", (recs, hist) == before)
t.ok("P11 the same inputs give the same lists", a == b)
more = recs + [person(99, "שבועי")]
c = plan(more, hist, weeks=8, portions=14, reserve=4)
t.ok("P11 a card added now is in every coming week", all("g0099" in guids(w["main"]) for w in c))
paused = [dict(r, status="מושהה") if r["guid"] == "g0001" else r for r in recs]
t.ok("P11 a card paused now is in none", not any("g0001" in guids(w["main"]) + guids(w["reserve_list"]) + guids(w["out"])
                                                  for w in plan(paused, hist, weeks=8, portions=14, reserve=4)))

# ── P12: the ledger ───────────────────────────────────────────────────────────
led = planner.Ledger(W0).load([got("a", wk(-3)), got("a", wk(-1), holiday="חג"), got("b", wk(2)), got("c", wk(-2), received=0)])
t.ok("P12 an extra round moves 'last' but not the regular turn", led.last_any("a") == wk(-1) and led.last_regular("a") == wk(-3))
t.ok("P12 future and no-show rows are not loaded", led.last_any("b") is None and led.last_any("c") is None)
led.add_regular("a", wk(1)); led.add_regular("a", W0)
t.ok("P12 laid-out weeks are kept in order", led.last_regular("a") == wk(1) and led.regular_between("a", W0, W0)
     and not led.regular_between("a", wk(-2), wk(-1)) and led.regular_between("a", wk(-3), wk(-3)))


def _raises():
    try:
        plan([], [], start=W0 + timedelta(days=1))
    except ValueError:
        return True
    return False


t.ok("P12 start must be a Wednesday", _raises())

# ── P13: random populations — the rules hold every week ───────────────────────
FREQS = list(INTERVAL)
bad = []
for seed in range(60):
    rng = random.Random(seed)
    recs, hist = [], []
    for n in range(1, rng.randint(5, 45)):
        recs.append(person(n, rng.choice(FREQS), per_soul=str(rng.randint(0, 2000)), souls=rng.randint(1, 12),
                           status=rng.choice(["פעיל"] * 9 + ["מושהה"])))
        if rng.random() < 0.8:
            hist.append(got(f"g{n:04d}", wk(-rng.randint(1, 6)) - timedelta(days=rng.choice([0, 0, 0, 1, 3]))))
    for n in range(100, 100 + rng.randint(0, 60)):
        recs.append(person(n, "חד-פעמי", rng.choice([3, 2, 2, None]), per_soul=str(rng.randint(0, 2000)),
                           souls=rng.randint(1, 12)))
        if rng.random() < 0.3:
            hist.append(got(f"g{n:04d}", wk(-rng.randint(1, 8))))
    portions, reserve, cooldown = rng.randint(0, 50), rng.randint(0, 8), rng.choice([0, 1, 4, 4, 6])
    weeks = plan(recs, hist, weeks=10, portions=portions, reserve=reserve, cooldown=cooldown)
    by = {r["guid"]: r for r in recs}
    last_reg = {}
    for h in hist:
        d = date.fromisoformat(h["dist_date"])
        last_reg[h["recipient_guid"]] = max(last_reg.get(h["recipient_guid"], d), d)
    got_on = {g: ([selection.round_wednesday(last_reg[g])] if g in last_reg else []) for g in by}
    participants = {r["guid"] for r in recs if r["status"] == "פעיל" and planner.participation(r)}
    for i, w in enumerate(weeks):
        m, r_, o = guids(w["main"]), guids(w["reserve_list"]), guids(w["out"])
        if len(m) > portions:
            bad.append((seed, i, "more people than portions"))
        if len(r_) > reserve:
            bad.append((seed, i, "reserve longer than set"))
        if len(set(m + r_ + o)) != len(m + r_ + o) or set(m + r_ + o) != participants:
            bad.append((seed, i, "not everybody is in exactly one column"))
        if w["empty_portions"] and w["one_time_slots"] and any(e["group"] == planner.OUT_ONE_QUEUE for e in w["out"]):
            bad.append((seed, i, "an empty portion while somebody waits in the queue"))
        if not w["cut"] and portions > 0 and w["regulars_due"] != w["main_regulars"]:
            bad.append((seed, i, "a due regular left out although the portions suffice"))
        for g in m:
            rec, d = by[g], w["date"]
            gap = (d - got_on[g][-1]).days if got_on[g] else None
            if rec["frequency"] in INTERVAL:
                if gap is not None and gap < INTERVAL[rec["frequency"]]:
                    bad.append((seed, i, f"{rec['frequency']} twice within {gap} days"))
            elif cooldown and gap is not None and gap < 7 * cooldown:
                bad.append((seed, i, f"one-timer back after {gap} days, pause {cooldown} weeks"))
            got_on[g].append(d)
        for e in w["out"]:
            if e["group"] == planner.OUT_REG_WAIT and not w["cut"] and portions > 0:
                rec = by[e["guid"]]
                gap = (w["date"] - got_on[e["guid"]][-1]).days if got_on[e["guid"]] else None
                if gap is None or (rec["frequency"] in INTERVAL and gap >= INTERVAL[rec["frequency"]]
                                   and gap > 3):
                    bad.append((seed, i, f"a regular whose turn came is waiting ({rec['frequency']}, gap {gap})"))
t.ok("P13 sixty random populations x 10 weeks: portions, reserve, turns, pause, one column each", not bad, str(bad[:5]))

# ── P14: what the manager sets by hand for one week ───────────────────────────
recs = ([person(n, "שבועי") for n in (1, 2, 3)] + [person(4, "דו-שבועי")]
        + [person(n, "חד-פעמי", 3, per_soul=str(n)) for n in (21, 22, 23, 24)] + [person(40, "", 1), person(41, "שבועי", status="מושהה")])
hist = [got(f"g{n:04d}", wk(-1)) for n in (1, 2, 3, 4)]


def mplan(manual, weeks=3, portions=5, reserve=1):
    return planner.plan_weeks(recs, hist, start=W0, weeks=weeks, horizon=W0, weights=WEIGHTS, cooldown_weeks=4,
                              portions=portions, reserve=reserve, manual=manual)


base = mplan(None)
t.ok("P14 without anything set by hand: 3 regulars + 2 one-timers, one in reserve",
     base[0]["main_regulars"] == 3 and base[0]["main_one_timers"] == 2 and len(base[0]["reserve_list"]) == 1
     and "g0004" in guids(base[0]["out"]))
w = mplan({W0: {"g0004": "add"}})
add = next((e for e in w[0]["main"] if e["guid"] == "g0004"), {})
t.ok("P14 add: a bi-weekly whose turn has not come is on the list, marked as set by hand",
     add.get("manual") == "add" and "נוסף ביד" in add.get("why", "") and len(w[0]["main"]) == 5)
t.ok("P14 add: he takes a portion from the one-timers, never from a regular",
     w[0]["main_regulars"] == 4 and w[0]["main_one_timers"] == 1 and {"g0001", "g0002", "g0003"} <= set(guids(w[0]["main"])))
t.ok("P14 add: he counts as having received — his next turn is two weeks from now",
     [("g0004" in guids(x["main"])) for x in w] == [True, False, True]
     and [("g0004" in guids(x["main"])) for x in base] == [False, True, False])
w = mplan({W0: {"g0001": "reserve"}})
t.ok("P14 reserve: first on the reserve, not on the list, and the reserve is not longer than set",
     guids(w[0]["reserve_list"]) == ["g0001"] and "g0001" not in guids(w[0]["main"]) and w[0]["reserve_list"][0]["manual"] == "reserve")
t.ok("P14 reserve: his portion goes to the next in the queue, and he is back next week",
     len(w[0]["main"]) == 5 and w[0]["main_one_timers"] == 3 and "g0001" in guids(w[1]["main"]))
w = mplan({W0: {"g0001": "remove"}})
rm = next((e for e in w[0]["out"] if e["guid"] == "g0001"), {})
t.ok("P14 remove: on no list this week, shown first in 'not this week' with the reason",
     rm.get("group") == planner.OUT_REMOVED and rm.get("manual") == "remove" and w[0]["out"][0]["guid"] == "g0001"
     and "g0001" not in guids(w[0]["main"]) + guids(w[0]["reserve_list"]))
t.ok("P14 remove: he did not receive, so he is on next week's list", "g0001" in guids(w[1]["main"]) and len(w[0]["main"]) == 5)
w = mplan({wk(1): {"g0001": "remove"}})
t.ok("P14 a change set for one week leaves the weeks before it untouched", w[0] == base[0] and w[1] != base[1])
# the bi-weekly is due on week 1 only: taken off it by hand he did NOT receive, so his turn stays
w = mplan({wk(1): {"g0004": "remove"}})
t.ok("P14 remove: a bi-weekly taken off his own week keeps his turn — he is on the very next list",
     [("g0004" in guids(x["main"])) for x in w] == [False, False, True]
     and [("g0004" in guids(x["main"])) for x in base] == [False, True, False])
w = mplan({wk(1): {"g0004": "reserve"}})
t.ok("P14 reserve: a bi-weekly moved to the reserve of his own week did not receive — he is on the very next list",
     [("g0004" in guids(x["main"])) for x in w] == [False, False, True] and guids(w[1]["reserve_list"]) == ["g0004"])
w = mplan({W0: {"g0004": "add"}, wk(1): {"g0004": "add"}}, weeks=4)
t.ok("P14 the same person can be set by hand in two weeks, each week on its own",
     [("g0004" in guids(x["main"])) for x in w] == [True, True, False, True]
     and [x["main"][0].get("manual") for x in w[:2]] == ["add", "add"])
w = mplan({W0: {"g0040": "add", "g0041": "add"}})
t.ok("P14 a card that takes no part can be added by hand; a paused card cannot",
     "g0040" in guids(w[0]["main"]) and "g0041" not in guids(w[0]["main"]) + guids(w[0]["reserve_list"]) + guids(w[0]["out"]))
w = mplan({W0: {"g0021": "add"}}, portions=3, reserve=0)
t.ok("P14 a one-timer added by hand never pushes a regular out: the list is one too long, with a warning",
     len(w[0]["main"]) == 4 and w[0]["main_regulars"] == 3 and any("יותר מדי" in x for x in w[0]["warnings"]))
w = mplan({W0: {"g0004": "add"}}, portions=3, reserve=1)
t.ok("P14 a regular added by hand when the regulars alone exceed the portions: the one who waited least moves to the reserve",
     len(w[0]["main"]) == 3 and "g0004" in guids(w[0]["main"]) and len(w[0]["reserve_list"]) == 1
     and w[0]["reserve_list"][0]["kind"] == "regular" and w[0]["cut"])
bad = []
for seed in range(40):
    rng = random.Random(500 + seed)
    manual = {wk(i): {r["guid"]: rng.choice(planner.MANUAL_ACTIONS) for r in recs if rng.random() < 0.3} for i in range(3)}
    for i, x in enumerate(mplan(manual, weeks=4, portions=rng.randint(0, 7), reserve=rng.randint(0, 3))):
        cols = guids(x["main"]) + guids(x["reserve_list"]) + guids(x["out"])
        if len(cols) != len(set(cols)):
            bad.append((seed, i, "somebody is in two columns"))
        for g, action in manual.get(x["date"], {}).items():
            if g == "g0041" or x["portions"] == 0:
                continue
            where = "main" if g in guids(x["main"]) else "reserve" if g in guids(x["reserve_list"]) else "out"
            if where != {"add": "main", "reserve": "reserve", "remove": "out"}[action]:
                bad.append((seed, i, f"{action} landed in {where}"))
t.ok("P14 forty random sets of hand changes: each lands where it was set, nobody twice", not bad, str(bad[:4]))


# ══ stage 4: a holiday event — an EXTRA round on the same time line as the weeks ══
SUN = W0 - timedelta(days=3)                 # the Sunday before W0
CRIT_KEYS = [f for f, _label in selection.FILTER_FIELDS]


def ev(day, holiday="*", portions=50, reserve=0, criteria=None, manual=None, guid="e1", **kw):
    return dict({"guid": guid, "date": day, "holiday": holiday, "portions": portions, "reserve": reserve,
                 "criteria": criteria or {}, "manual": manual or {}}, **kw)


def line(recs, hist, events, weeks=1, portions=52, reserve=0, cooldown=4, start=W0, manual=None):
    return planner.plan_timeline(recs, hist, start=start, weeks=weeks, horizon=start, weights=WEIGHTS,
                                 cooldown_weeks=cooldown, portions=portions, reserve=reserve,
                                 manual=manual, events=events)


def where(e):
    """{guid: 'main' | 'reserve' | the reason group} for everybody an event's answer lists."""
    out = {x["guid"]: "main" for x in e["main"]}
    out.update({x["guid"]: "reserve" for x in e["reserve_list"]})
    out.update({x["guid"]: x["group"] for x in e["out"]})
    return out


# ── P15: who is on a holiday list — the mark is the gate, the turn is not ─────
recs = [person(1, "שבועי", holiday_support=1), person(2, "חודשי", holiday_support=1), person(3, "שבועי"),
        person(4, "שבועי", holiday_support=1, holidays="סוכות"),
        person(5, "דו-שבועי", holiday_support=1, holidays="סוכות,פסח"),
        person(11, "חד-פעמי", 3, holiday_support=1), person(12, "חד-פעמי", 2),
        person(20, "", None, holiday_support=1), person(21, "חד-פעמי", None, holiday_support=1),
        person(30, "שבועי", holiday_support=1, status="מושהה")]
hist = [got(g, wk(-1)) for g in ("g0001", "g0002", "g0005", "g0011")]
e = line(recs, hist, [ev(SUN, "*")])["events"][0]
t.ok("P15 '*' = everybody marked נתמך חגים, whatever the holidays listed on the card",
     set(guids(e["main"])) == {"g0001", "g0002", "g0004", "g0005", "g0011", "g0020", "g0021"}, str(guids(e["main"])))
t.ok("P15 the turn gates are skipped: a monthly served last week and a one-timer inside his pause are on it",
     {"g0002", "g0011"} <= set(guids(e["main"])))
kinds = {x["guid"]: x["kind"] for x in e["main"]}
t.ok("P15 a marked card that takes no part in the weekly lists receives too, shown as its own kind",
     kinds["g0020"] == kinds["g0021"] == planner.KIND_OTHER and kinds["g0001"] == "regular" and kinds["g0011"] == "onetime")
t.ok("P15 whoever is not marked is on no list and is only counted; a paused card is nowhere",
     not ({"g0003", "g0012", "g0030"} & set(where(e))) and e["unmarked"] == 2 and e["marked"] == 7)
e = line(recs, hist, [ev(SUN, "פסח")])["events"][0]
w_ = where(e)
t.ok("P15 a named holiday: the cards marked for all holidays, or for this one",
     {g for g, x in w_.items() if x == "main"} == {"g0001", "g0002", "g0005", "g0011", "g0020", "g0021"})
other = next(x for x in e["out"] if x["guid"] == "g0004")
t.ok("P15 marked for other holidays only: outside, and the reason names them",
     w_["g0004"] == planner.OUT_EV_OTHER and "סוכות" in other["why"] and e["marked"] == 6)
e = line(recs, hist, [ev(SUN, "חנוכה")])["events"][0]
t.ok("P15 a card listing two holidays is outside a third one",
     where(e).get("g0005") == planner.OUT_EV_OTHER and where(e).get("g0001") == "main")
t.ok("P15 every entry of an event carries a reason", all(x["why"].strip() for x in e["main"] + e["out"]))

# ── P16: the event's filter — every threshold, and a missing value never passes ──
frecs = [person(1, "שבועי", holiday_support=1, children_total=5, income="3000", per_soul="400"),
         person(2, "שבועי", holiday_support=1, children_total=2, income="3000", per_soul="400"),
         person(3, "שבועי", holiday_support=1, children_total=5, income="9111", per_soul="400"),
         person(4, "שבועי", holiday_support=1, children_total=5, income="", per_soul="400"),
         person(5, "שבועי", holiday_support=1, children_total=5, income="0", per_soul="400"),
         person(6, "שבועי", holiday_support=1, children_total=5, income="3000", per_soul="-200"),
         person(7, "שבועי", holiday_support=1, children_total=0, income="", per_soul=""),
         person(8, "שבועי", children_total=9, income="100", per_soul="1")]
crit = {"children_total": {"min": 3, "max": None}, "income": {"min": None, "max": 5000},
        "per_soul": {"min": None, "max": 500}}
e = line(frecs, [], [ev(SUN, "*", criteria=crit)])["events"][0]
w_ = where(e)
t.ok("P16 on the list: only who passes every threshold (a debt passes 'up to')",
     {g for g, x in w_.items() if x == "main"} == {"g0001", "g0006"}, str(w_))
t.ok("P16 a missing value, and a 0 where 0 means 'unknown', do not pass — and are set apart as MISSING DATA",
     w_["g0004"] == w_["g0005"] == planner.OUT_EV_MISSING and e["missing"] == 2
     and any("חסר להם נתון" in x for x in e["warnings"]))
why = {x["guid"]: x["why"] for x in e["out"]}
t.ok("P16 the missing field is named", "הכנסה חודשית" in why["g0004"] and "מספר ילדים" not in why["g0004"])
t.ok("P16 outside a threshold: the reason says which, in words",
     w_["g0002"] == w_["g0003"] == planner.OUT_EV_FILTER and "מספר ילדים מתחת ל-3" in why["g0002"]
     and "הכנסה חודשית מעל 5,000" in why["g0003"])
t.ok("P16 somebody who fails a threshold is not called 'missing data', whatever else is blank on his card",
     w_["g0007"] == planner.OUT_EV_FILTER)
t.ok("P16 the card's own numbers are never quoted in a reason", not any(
    n in x["why"] for x in e["main"] + e["out"] for n in ("9111", "9,111", "3000", "3,000", "400", "200")))
t.ok("P16 perfect numbers do not help a card that is not marked", "g0008" not in w_ and e["unmarked"] == 1)
full = dict(crit, holiday="*")
t.ok("P16 on the list = exactly what the engine's own filter says (selection.matches_criteria)",
     all((r["guid"] in guids(e["main"])) == selection.matches_criteria(dict(r), full) for r in frecs))
e = line(frecs, [], [ev(SUN, "*", criteria={"income": {"min": 1000, "max": 4000}})])["events"][0]
t.ok("P16 a 'from' and an 'up to' on one field both hold", set(guids(e["main"])) == {"g0001", "g0002", "g0006"})

# ── P17: short of portions -> who waited longest; the reserve is never topped up from outside ──
recs = [person(n, "שבועי", holiday_support=1) for n in range(1, 9)] + [person(n, "חד-פעמי", 3) for n in (21, 22, 23)]
hist = [got(f"g{n:04d}", wk(-n)) for n in range(1, 9)]                    # g0008 waited longest
e = line(recs, hist, [ev(SUN, "*", portions=3, reserve=2)])["events"][0]
t.ok("P17 three portions -> the three who waited longest", guids(e["main"]) == ["g0008", "g0007", "g0006"], str(guids(e["main"])))
t.ok("P17 the reserve = the next two in the same line", guids(e["reserve_list"]) == ["g0005", "g0004"])
t.ok("P17 the rest are off this list, in their order, and the event says so",
     [x["guid"] for x in e["out"] if x["group"] == planner.OUT_EV_CUT] == ["g0003", "g0002", "g0001"]
     and e["cut"] and "מחכים הכי הרבה זמן" in e["warnings"][0])
rows = [planner.event_row(p, SUN, planner.Ledger(W0).load(hist)) for p in planner.active_people(recs) if p.get("holiday_support")]
t.ok("P17 the order is the engine's own (selection.rank_by_wait)",
     [r["guid"] for r in selection.rank_by_wait(rows, WEIGHTS)][:5] == guids(e["main"]) + guids(e["reserve_list"]))
e = line(recs, hist, [ev(SUN, "*", portions=20, reserve=5)])["events"][0]
t.ok("P17 portions to spare: everybody marked receives, and nobody UNMARKED fills the reserve (the mark is a hard gate)",
     len(e["main"]) == 8 and e["reserve_list"] == [] and not ({"g0021", "g0022", "g0023"} & set(where(e)))
     and e["empty_portions"] == 12 and not e["cut"])
e0 = line(recs, hist, [ev(SUN, "*", portions=0, reserve=3)])["events"][0]
t.ok("P17 0 portions: an empty list, and everybody is told why",
     e0["main"] == [] and e0["reserve_list"] == [] and all(x["group"] == planner.OUT_NO_PORTIONS for x in e0["out"])
     and len(e0["out"]) == 8)

# ── P18: an extra round never moves a regular's turn (and is no "round of the week") ──
recs = [person(1, "שבועי", holiday_support=1), person(2, "דו-שבועי", holiday_support=1),
        person(3, "תלת-שבועי", holiday_support=1), person(4, "חודשי", holiday_support=1)]
hist = [got(f"g000{n}", wk(-1)) for n in (1, 2, 3, 4)]
plain = [guids(w["main"]) for w in plan(recs, hist, weeks=9)]
for label, day in (("on a Monday", wk(1) - timedelta(days=2)), ("on the Wednesday itself", wk(1)),
                   ("on a Friday", wk(1) + timedelta(days=2))):
    tl = line(recs, hist, [ev(day, "*")], weeks=9)
    t.ok(f"P18 an event {label}: all four receive in it, and every regular list is exactly as without it",
         len(tl["events"][0]["main"]) == 4 and [guids(w["main"]) for w in tl["weeks"]] == plain)
tl = line(recs, hist, [ev(wk(1) - timedelta(days=2), "*")], weeks=3)
t.ok("P18 a holiday portion on Monday does not take a weekly regular off that Wednesday (rule 9 counts regular rounds)",
     "g0001" in guids(tl["weeks"][1]["main"]))

# ── P19: ...and a one-timer's either: "חג לא נספר" (decision 26/11/2026) ──────
recs = [person(1, "שבועי"), person(21, "חד-פעמי", 3, holiday_support=1), person(22, "חד-פעמי", 3)]
plain = plan(recs, [], weeks=6, portions=3)
for label, day in (("on the Sunday before", SUN), ("on a Thursday", W0 + timedelta(days=1)), ("on a Wednesday", wk(2))):
    tl = line(recs, [], [ev(day, "*")], weeks=6, portions=3)
    t.ok(f"P19 a one-timer received a holiday portion {label}: every week is exactly as without the event — no pause, the same place in the queue",
         guids(tl["events"][0]["main"]) == ["g0021"] and tl["weeks"] == plain)
t.ok("P19 the pause itself still works: after a REGULAR portion both one-timers wait 4 weeks",
     [("g0021" in guids(w["main"])) for w in plain] == [True, False, False, False, True, False])

# ── P20: the order of the rounds on the time line ─────────────────────────────
recs = [person(n, "שבועי", holiday_support=1) for n in (1, 2, 3, 4)]
hist = [got(f"g000{n}", wk(-n)) for n in (1, 2, 3, 4)]                     # g0004 waited longest
tl = line(recs, hist, [ev(SUN, "*", portions=2)], weeks=1, portions=2)
t.ok("P20 an event BEFORE the Wednesday is laid out first: it takes the two who waited longest",
     guids(tl["events"][0]["main"]) == ["g0004", "g0003"])
t.ok("P20 ...and that Wednesday does not see it: also in a week short of portions a holiday portion costs nobody his place",
     guids(tl["weeks"][0]["main"]) == guids(plan(recs, hist, portions=2)[0]["main"]) == ["g0004", "g0003"],
     str(guids(tl["weeks"][0]["main"])))
tl = line(recs, hist, [ev(W0, "*", portions=2)], weeks=1, portions=2)
t.ok("P20 an event ON the Wednesday is the extra round of that day: the regular list is laid out first, as if there were no event",
     guids(tl["weeks"][0]["main"]) == guids(plan(recs, hist, portions=2)[0]["main"]) == ["g0004", "g0003"])
t.ok("P20 ...and the event sees it: its two portions go to the two who did not receive that day",
     guids(tl["events"][0]["main"]) == ["g0002", "g0001"])
tl = line(recs, hist, [ev(wk(3), "*", guid="far"), ev(SUN, "*", guid="near")], weeks=2)
t.ok("P20 an event after the last Wednesday asked for is not laid out (its list depends on weeks nobody asked for)",
     [x["guid"] for x in tl["events"]] == ["near"] and [x["guid"] for x in tl["later"]] == ["far"])
tl = line(recs, hist, [ev(SUN, "*", guid="near"), ev(W0, "*", guid="same-day")], weeks=0)
t.ok("P20 with no week asked for, only the events before the first Wednesday are laid out",
     [x["guid"] for x in tl["events"]] == ["near"] and tl["weeks"] == [])
tl = line(recs, hist, [ev(SUN, "*", guid="b", created_at="2026-11-01 10:00:00", portions=1),
                       ev(SUN, "*", guid="a", created_at="2026-11-02 10:00:00", portions=1)], weeks=0)
t.ok("P20 two events on one day: in the order they were set up, the second sees the first",
     [x["guid"] for x in tl["events"]] == ["b", "a"] and guids(tl["events"][0]["main"]) == ["g0004"]
     and guids(tl["events"][1]["main"]) == ["g0003"])

# ── P21: what the manager sets by hand for an event ───────────────────────────
recs = [person(1, "שבועי", holiday_support=1), person(2, "שבועי", holiday_support=1), person(3, "שבועי"),
        person(21, "חד-פעמי", 3), person(22, "חד-פעמי", 3, holiday_support=1), person(40, "שבועי", status="מושהה")]
hand = {"g0003": "add", "g0021": "add", "g0001": "remove", "g0002": "reserve", "g0040": "add"}
tl = line(recs, [], [ev(SUN, "*", portions=3, reserve=1, manual=hand)], weeks=6, portions=5)
e = tl["events"][0]
t.ok("P21 add: somebody who is not marked is on the list, marked as set by hand, and takes a portion",
     guids(e["main"]) == ["g0003", "g0021", "g0022"] and [x.get("manual") for x in e["main"]] == ["add", "add", None]
     and "נוסף ביד" in e["main"][0]["why"])
t.ok("P21 reserve: first on the reserve; remove: on no list, shown first with the reason",
     guids(e["reserve_list"]) == ["g0002"] and e["reserve_list"][0]["manual"] == "reserve"
     and e["out"][0]["guid"] == "g0001" and e["out"][0]["group"] == planner.OUT_REMOVED)
t.ok("P21 a paused card cannot be put on an event's list", "g0040" not in where(e))
t.ok("P21 whatever is set by hand for an event, the weeks are exactly as without it (a holiday portion is not counted in them)",
     tl["weeks"] == plan(recs, [], weeks=6, portions=5))
two = line(recs, [], [ev(SUN, "*", portions=3, manual={"g0021": "add"}), ev(SUN + timedelta(days=1), "*", portions=1, guid="e2",
                                                                            manual={"g0021": "reserve"})], weeks=0)["events"]
t.ok("P21 added by hand = received in that event: a later holiday list sees it (he waited less than who did not receive)",
     "g0021" in guids(two[0]["main"]) and guids(two[1]["reserve_list"]) == ["g0021"] and len(two[1]["main"]) == 1)
e = line(recs, [], [ev(SUN, "*", portions=1, manual={"g0003": "add", "g0021": "add"})])["events"][0]
t.ok("P21 more added by hand than portions: the list is longer, with a warning, and nobody else gets in",
     guids(e["main"]) == ["g0003", "g0021"] and any("יותר מדי" in x for x in e["warnings"])
     and where(e)["g0001"] == planner.OUT_EV_CUT)
e = line(recs, [], [ev(SUN, "*", portions=0, manual={"g0003": "add"})])["events"][0]
t.ok("P21 0 portions: also what was set by hand waits outside", e["main"] == [] and where(e)["g0003"] == planner.OUT_NO_PORTIONS)

# ── P22: pure — inputs untouched, the same answer twice ───────────────────────
events = [ev(SUN, "*", portions=4, reserve=2, criteria={"income": {"min": None, "max": 5000}}, manual={"g0003": "add"})]
before = copy.deepcopy((frecs, hist, events))
a = line(frecs, hist, events, weeks=5, portions=4, reserve=2)
b = line(frecs, hist, events, weeks=5, portions=4, reserve=2)
t.ok("P22 the cards, the history and the events are not modified", (frecs, hist, events) == before)
t.ok("P22 the same inputs give the same weeks and the same event lists", a == b)
t.ok("P22 plan_weeks = the weeks of the time line (the events among them are laid out too)",
     planner.plan_weeks(frecs, hist, start=W0, weeks=5, horizon=W0, weights=WEIGHTS, cooldown_weeks=4,
                        portions=4, reserve=2, events=events) == a["weeks"])
t.ok("P22 how many weeks an event needs: every Wednesday up to its day",
     [planner.weeks_through(W0, d) for d in (SUN, W0, W0 + timedelta(days=1), wk(1), wk(3) - timedelta(days=1))] == [0, 1, 1, 2, 3])

# ── P23: random populations with events — the rules hold ──────────────────────
HOLS = ["", "", "פסח", "סוכות", "פסח,חנוכה"]
bad = []
for seed in range(50):
    rng = random.Random(7000 + seed)
    recs, hist = [], []
    for n in range(1, rng.randint(6, 40)):
        freq = rng.choice(FREQS + ["חד-פעמי", "חד-פעמי", ""])
        recs.append(person(n, freq, rng.choice([3, 2, None]) if freq in ("חד-פעמי", "") else 4,
                           holiday_support=rng.choice([0, 1, 1]), holidays=rng.choice(HOLS),
                           children_total=rng.randint(0, 8), income=rng.choice(["", "0", str(rng.randint(500, 9000))]),
                           per_soul=rng.choice(["", "0", "-100", str(rng.randint(50, 2000))]),
                           status=rng.choice(["פעיל"] * 9 + ["מושהה"])))
        if rng.random() < 0.7:
            hist.append(got(f"g{n:04d}", wk(-rng.randint(1, 6)) - timedelta(days=rng.choice([0, 0, 1, 3])),
                            holiday=rng.choice(["", "", "", "פסח"])))
    cooldown = rng.choice([0, 3, 4])
    events = []
    for k in range(rng.randint(1, 2)):
        c = {}
        if rng.random() < 0.6:
            c["children_total"] = {"min": rng.randint(0, 4), "max": None}
        if rng.random() < 0.5:
            c["income"] = {"min": None, "max": rng.choice([3000, 6000])}
        if rng.random() < 0.3:
            c["per_soul"] = {"min": None, "max": 800}
        events.append(ev(W0 + timedelta(days=rng.randint(-3, 30)), rng.choice(["*", "*", "פסח", "סוכות"]),
                         portions=rng.randint(0, 25), reserve=rng.randint(0, 4), criteria=c, guid=f"e{k}"))
    tl = line(recs, hist, events, weeks=7, portions=200, cooldown=cooldown)
    no_events = line(recs, hist, [], weeks=7, portions=200, cooldown=cooldown)["weeks"]
    by = {r["guid"]: r for r in recs}
    active = {g for g, r in by.items() if r["status"] == "פעיל"}
    if len(tl["events"]) + len(tl["later"]) != len(events):
        bad.append((seed, "an event was lost"))
    for e in tl["events"]:
        full = dict(planner.event_criteria(e))
        m, r_, o = guids(e["main"]), guids(e["reserve_list"]), guids(e["out"])
        passing = {g for g in active if selection.matches_criteria(dict(by[g]), full)}
        marked = {g for g in active if selection.holiday_matches(by[g], full)}
        if len(set(m + r_ + o)) != len(m + r_ + o):
            bad.append((seed, "somebody is listed twice in an event"))
        if len(m) > e["portions"] or len(r_) > e["reserve"]:
            bad.append((seed, "more people than portions / reserve"))
        if not set(m + r_) <= passing:
            bad.append((seed, "somebody who does not pass is on the list or the reserve"))
        if passing - set(m + r_ + o) or (marked - passing) - set(o):
            bad.append((seed, "a marked card is nowhere"))
        if (e["marked"], e["eligible"], e["unmarked"]) != (len(marked), len(passing), len(active - {g for g in active if by[g].get("holiday_support")})):
            bad.append((seed, f"the event's numbers are wrong {(e['marked'], e['eligible'], e['unmarked'])}"))
        if e["portions"] and set(m) != passing and len(m) < e["portions"]:
            bad.append((seed, "an empty portion while somebody who passes is outside"))
        days = lambda xs: [x["days_since"] for x in xs]                                  # noqa: E731
        cut_out = [x for x in e["out"] if x["group"] == planner.OUT_EV_CUT]
        if (e["main"] and e["reserve_list"] and min(days(e["main"])) < max(days(e["reserve_list"]))) or \
           (e["reserve_list"] and cut_out and min(days(e["reserve_list"])) < max(days(cut_out))) or \
           (e["main"] and cut_out and min(days(e["main"])) < max(days(cut_out))):
            bad.append((seed, "somebody who waited less is ahead of somebody who waited more"))
    if tl["weeks"] != no_events:
        bad.append((seed, "an event changed a regular week"))
t.ok("P23 fifty random populations with holiday events: the gate, the filter, the order, the numbers — and every week exactly as without the events",
     not bad, str(bad[:4]))
portions_small = line(recs, hist, events, weeks=7, portions=6, reserve=2, cooldown=cooldown)
t.ok("P23 ...also when the weeks are short of portions",
     portions_small["weeks"] == line(recs, hist, [], weeks=7, portions=6, reserve=2, cooldown=cooldown)["weeks"])

# ══ after stage 4: a week by need score, and a holiday list split between the communities ══
MONEY = dict.fromkeys(WEIGHTS, 0.0)
MONEY["money"] = 100.0                       # the score is the money alone: who has less is first


def sweeks(recs, hist, modes, weeks=1, portions=3, reserve=1, manual=None, weights=MONEY):
    return planner.plan_weeks(recs, hist, start=W0, weeks=weeks, horizon=W0, weights=weights, cooldown_weeks=4,
                              portions=portions, reserve=reserve, manual=manual, modes=modes)


# ── P24: a week that is marked "by score" ─────────────────────────────────────
# five weekly regulars who received last week, and a bi-weekly who waited longest and has the most money
srecs = ([person(n, "שבועי", per_soul=str(money)) for n, money in ((1, 350), (2, 900), (3, 200), (4, 1200), (5, 600))]
         + [person(6, "דו-שבועי", per_soul="5000"), person(7, "דו-שבועי", per_soul="1"),
            person(21, "חד-פעמי", 3, per_soul="10"), person(22, "חד-פעמי", 3, per_soul="20")])
shist = [got(f"g000{n}", wk(-1)) for n in (1, 2, 3, 4, 5, 7)] + [got("g0006", wk(-2))]
SCORED = {W0: planner.MODE_SCORED}
plain = sweeks(srecs, shist, None)[0]
scored = sweeks(srecs, shist, SCORED)[0]
t.ok("P24 the ordinary way, three portions for six regulars: who waited longest is in first, then by score",
     guids(plain["main"]) == ["g0006", "g0003", "g0001"] and plain["by_score"] is False, str(guids(plain["main"])))
t.ok("P24 by score: the three with the highest need are in, in that order — also ahead of who waited longest",
     guids(scored["main"]) == ["g0003", "g0001", "g0005"] and scored["by_score"] is True and scored["cut"] is True,
     str(guids(scored["main"])))
t.ok("P24 the reserve is the next by score, and the rest are off the list",
     guids(scored["reserve_list"]) == ["g0002"]
     and [e["guid"] for e in scored["out"] if e["group"] == planner.OUT_REG_CUT] == ["g0004", "g0006"])
t.ok("P24 the turn is still a hard gate: a bi-weekly who received last week is out, however great his need",
     next(e for e in scored["out"] if e["guid"] == "g0007")["group"] == planner.OUT_REG_WAIT and scored["regulars_due"] == 6)
whys = {e["guid"]: e["why"] for e in scored["main"] + scored["reserve_list"] + scored["out"]}
t.ok("P24 the reasons say the place by score, and the week says that it was cut by score",
     "מקום 1 מתוך 6" in whys["g0003"] and "מקום 4 מתוך 6" in whys["g0002"] and "נמוך יותר" in whys["g0006"]
     and any("לפי ניקוד" in x for x in scored["warnings"]), str(whys["g0003"]))
t.ok("P24 a reason never quotes the score or the money of the card",
     not any(money in why for why in whys.values() for money in ("350", "900", "200", "1200", "600", "5000")))
enough_plain = sweeks(srecs, shist, None, portions=8, reserve=1)[0]
enough = sweeks(srecs, shist, SCORED, portions=8, reserve=1)[0]
t.ok("P24 with a portion for every regular in turn the mark changes nobody: the same people, the same one-timers, the same reserve",
     set(guids(enough["main"])) == set(guids(enough_plain["main"])) and enough["cut"] is False and enough["warnings"] == enough_plain["warnings"]
     and [e["guid"] for e in enough["main"] if e["kind"] == "onetime"] == [e["guid"] for e in enough_plain["main"] if e["kind"] == "onetime"]
     and guids(enough["reserve_list"]) == guids(enough_plain["reserve_list"]) and enough["main_regulars"] == 6)
two = sweeks(srecs, shist, SCORED, weeks=2)
t.ok("P24 only the week that was marked is cut by score; the week after it goes the ordinary way",
     two[0]["by_score"] is True and two[1]["by_score"] is False and two[0] == scored)
t.ok("P24 who was left out by score is first in the ordinary week after it (he waits longest)",
     guids(two[1]["main"])[0] == "g0006", str(guids(two[1]["main"])))
hand = sweeks(srecs, shist, SCORED, manual={W0: {"g0021": "add"}})[0]
hand_plain = sweeks(srecs, shist, None, manual={W0: {"g0021": "add"}})[0]
t.ok("P24 by score, whoever is added by hand takes the place of the lowest: two regulars are left of the three",
     guids(hand["main"]) == ["g0021", "g0003", "g0001"] and guids(hand["reserve_list"]) == ["g0005"], str(guids(hand["main"])))
t.ok("P24 ...in the ordinary way a one-timer added by hand never pushes a regular out (the list is longer, with a warning)",
     len(hand_plain["main"]) == 4 and hand_plain["main_regulars"] == 3 and any("יותר מדי" in x for x in hand_plain["warnings"]))
t.ok("P24 by score and no portions: an empty list", sweeks(srecs, shist, SCORED, portions=0)[0]["main"] == [])
keep = (copy.deepcopy(srecs), copy.deepcopy(shist))
again = sweeks(srecs, shist, SCORED)[0]
t.ok("P24 pure: the inputs are untouched and the same question gives the same answer", (srecs, shist) == keep and again == scored)
t.ok("P24 a mark that is not a known way is the ordinary way",
     sweeks(srecs, shist, {W0: "something"})[0] == plain and sweeks(srecs, shist, {W0: planner.MODE_WAIT})[0] == plain)

# ── P25: a holiday list that is split between the communities ─────────────────
# community A: six marked (five pass the filter); community B: three marked (one passes);
# one member of B is not marked at all. The filter: income up to 3,000.
A, B = "קהילה א", "קהילה ב"
brecs = ([person(n, "שבועי", holiday_support=1, representative=A, income="2000", per_soul=str(100 * n)) for n in (1, 2, 3, 4, 5)]
         + [person(6, "שבועי", holiday_support=1, representative=A, income="5000", per_soul="50"),
            person(11, "שבועי", holiday_support=1, representative=B, income="2000", per_soul="700"),
            person(12, "שבועי", holiday_support=1, representative=B, income="3100", per_soul="800"),
            person(13, "שבועי", holiday_support=1, representative=B, income="9000", per_soul="10"),
            person(14, "שבועי", representative=B, income="100", per_soul="1")])
bhist = [got(r["guid"], wk(-1)) for r in brecs]
CRIT = {"income": {"min": None, "max": 3000}}


def bev(balance=True, portions=6, reserve=0, criteria=CRIT, manual=None, pinned=None):
    return planner.plan_timeline(brecs, bhist, start=W0, weeks=0, horizon=W0, weights=MONEY, cooldown_weeks=4,
                                 events=[ev(SUN, "*", portions, reserve, criteria, manual, balance=balance)],
                                 pinned=pinned)["events"][0]


flat, e = bev(False), bev()
t.ok("P25 without the split: the six who pass the filter take the six portions",
     set(guids(flat["main"])) == {"g0001", "g0002", "g0003", "g0004", "g0005", "g0011"} and flat["communities"] == []
     and flat["balance"] is False)
comm = {c["name"]: c for c in e["communities"]}
t.ok("P25 with the split, each community gets a share by the number of its marked members: 4 and 2 of the 6",
     (comm[A]["size"], comm[A]["quota"], comm[B]["size"], comm[B]["quota"]) == (6, 4, 3, 2) and e["balance"] is True,
     str(e["communities"]))
t.ok("P25 inside a community the ones who pass the filter come first, by need score: the four with the least money",
     [g for g in guids(e["main"]) if g < "g0010"] == ["g0001", "g0002", "g0003", "g0004"], str(guids(e["main"])))
fills = [x["guid"] for x in e["main"] if x.get("fill")]
t.ok("P25 a share the passing ones cannot fill is topped up from the SAME community — the nearest to the filter, not the neediest",
     fills == ["g0012"] and {"g0011", "g0012"} <= set(guids(e["main"])) and "g0013" not in guids(e["main"])
     and (comm[B]["passing"], comm[B]["main"], comm[B]["filled"]) == (1, 2, 1), str(fills))
w_ = where(e)
left = next(x for x in e["out"] if x["guid"] == "g0005")
t.ok("P25 so somebody who passes the filter can be left without a place while another community is topped up — and the reason says why",
     w_["g0005"] == planner.OUT_EV_CUT and A in left["why"] and "4 מנות" in left["why"] and e["cut"] is True)
fill = next(x for x in e["main"] if x["guid"] == "g0012")
t.ok("P25 the topped-up one says so: outside which threshold, and for which community — never the card's own number",
     "להשלים" in fill["why"] and B in fill["why"] and "3,000" in fill["why"] and "3100" not in fill["why"]
     and fill["community"] == B, fill["why"])
t.ok("P25 the event warns that somebody came in without passing the filter",
     any("בלי לעבור את הסינון" in x for x in e["warnings"]) and any("בין הקהילות" in x for x in e["warnings"]))
t.ok("P25 the mark stays a hard gate: a member who is not marked for the holidays never fills a share",
     "g0014" not in w_ and e["unmarked"] == 1 and e["marked"] == 9)
t.ok("P25 what the screen shows for the communities adds up to the list",
     sum(c["main"] for c in e["communities"]) == len(e["main"]) == 6 and all(c["main"] <= c["quota"] for c in e["communities"]))
r = bev(reserve=2)
t.ok("P25 the reserve is the next in line of ALL the communities together: first who passes the filter, then the nearest to it",
     guids(r["reserve_list"]) == ["g0005", "g0006"] and guids(r["main"]) == guids(e["main"]), str(guids(r["reserve_list"])))
pin = bev(pinned={B: 50.0})
pc = {c["name"]: c for c in pin["communities"]}
t.ok("P25 a percentage fixed for a community replaces its share by size: half of the six portions",
     (pc[B]["quota"], pc[A]["quota"], pc[B]["pinned"], pc[A]["pinned"]) == (3, 3, True, False)
     and {"g0011", "g0012", "g0013"} <= set(guids(pin["main"])) and pc[B]["filled"] == 2
     and [g for g in guids(pin["main"]) if g < "g0010"] == ["g0001", "g0002", "g0003"], str(pin["communities"]))
hand = bev(manual={"g0014": "add"})
hc = {c["name"]: c for c in hand["communities"]}
t.ok("P25 who is added by hand takes a portion before the split: five are left to share",
     hand["main"][0]["guid"] == "g0014" and len(hand["main"]) == 6 and hc[A]["quota"] + hc[B]["quota"] == 5)
nof = bev(criteria={})
t.ok("P25 with no filter everybody marked passes: the shares are filled by need score, and nobody is a top-up",
     not any(x.get("fill") for x in nof["main"]) and [c["quota"] for c in nof["communities"]] == [4, 2]
     and [g for g in guids(nof["main"]) if g < "g0010"] == ["g0006", "g0001", "g0002", "g0003"], str(guids(nof["main"])))
t.ok("P25 no portions: an empty list, with the split or without it", bev(portions=0)["main"] == [] and bev(portions=0)["communities"] == [])
allhand = bev(portions=1, reserve=1, manual={"g0014": "add"})
t.ok("P25 when every portion was given by hand, nobody else is on the list — only the reserve is left",
     guids(allhand["main"]) == ["g0014"] and guids(allhand["reserve_list"]) == ["g0001"])
t.ok("P25 every entry of a split list carries a reason, and who is on it carries his community",
     all(x["why"].strip() for x in e["main"] + e["out"]) and all(x.get("community") for x in e["main"]))
keep = (copy.deepcopy(brecs), copy.deepcopy(bhist))
t.ok("P25 pure: the inputs are untouched and the same question gives the same answer", bev() == e and (brecs, bhist) == keep)

# ── P26: random populations — the split always adds up, and never lets the unmarked in ──
bad = []
for seed in range(40):
    rng = random.Random(7700 + seed)
    recs = [person(n, rng.choice(["שבועי", "חודשי", "חד-פעמי", ""]), rng.choice([4, 3, 2, None]),
                   holiday_support=rng.choice([0, 1, 1]), representative=rng.choice([A, A, B, "קהילה ג", ""]),
                   income=rng.choice(["", "0", str(rng.randint(500, 9000))]), per_soul=str(rng.randint(-200, 2000)),
                   children_total=rng.randint(0, 8)) for n in range(1, rng.randint(8, 45))]
    hist = [got(r["guid"], wk(-rng.randint(1, 6))) for r in recs if rng.random() < 0.7]
    crit = rng.choice([{}, {"income": {"min": None, "max": 4000}}, {"children_total": {"min": 3, "max": None}}])
    portions, reserve = rng.choice([1, 4, 10, 30]), rng.choice([0, 3])
    pinned = rng.choice([None, {A: 60.0}, {B: 100.0}])
    e = planner.plan_timeline(recs, hist, start=W0, weeks=0, horizon=W0, weights=WEIGHTS, cooldown_weeks=4, pinned=pinned,
                              events=[ev(SUN, "*", portions, reserve, crit, balance=True)])["events"][0]
    marked = {r["guid"] for r in recs if r["holiday_support"]}
    on = guids(e["main"]) + guids(e["reserve_list"])
    if not set(on) <= marked:
        bad.append((seed, "somebody who is not marked is on a split list"))
    if len(on) != len(set(on)) or set(on) & set(guids(e["out"])):
        bad.append((seed, "somebody is listed twice"))
    if len(e["main"]) != min(portions, len(marked)) or len(e["main"]) > portions:
        bad.append((seed, f"the list is {len(e['main'])} for {portions} portions and {len(marked)} marked"))
    if sum(c["main"] for c in e["communities"]) != len(e["main"]) or any(c["main"] > c["quota"] or c["quota"] > c["size"] for c in e["communities"]):
        bad.append((seed, "the split does not add up"))
    if sum(c["size"] for c in e["communities"]) != len(marked) or sum(c["quota"] for c in e["communities"]) != len(e["main"]):
        bad.append((seed, "the shares do not cover the portions"))
    if any(x.get("fill") and x["guid"] not in marked for x in e["main"]):
        bad.append((seed, "a top-up from outside the marked"))
t.ok("P26 forty random populations: a split list is exactly the portions (or everybody marked), from the marked only, "
     "and the shares of the communities add up to it", not bad, str(bad[:4]))

t.done()

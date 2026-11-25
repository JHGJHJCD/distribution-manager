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
w = plan(recs, [got("g0021", wk(-1), holiday="פסח")], portions=5)[0]
t.ok("P7 a one-timer who received a holiday round is paused too (as in the desktop program)", guids(w["main"]) == ["g0022"])

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

t.done()

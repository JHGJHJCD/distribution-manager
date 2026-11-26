# -*- coding: utf-8 -*-
"""The settings screen's answers — the ordinary numbers of a week, the weights of the need
score, and "what would change?" — on a throw-away database with invented people.

Run:  <python 3.12> web/tests/test_settings.py
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta

from _util import Checker, W0, person, wk

from web import event_service, service, settings_service, store
from web.service import Refused

t = Checker("web settings")
TMP = tempfile.mkdtemp(prefix="haluka_settings_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")
NOW = datetime(W0.year, W0.month, W0.day, 10, 0)


def refusal(fn) -> str:
    try:
        fn()
    except Refused as e:
        return str(e)
    return ""


# five weekly regulars who all wait the same time and differ in money and in family size,
# and one-timers behind them
recs = ([person(n, "שבועי", per_soul=str(money), souls=souls)
         for n, money, souls in ((1, 350, 4), (2, 900, 9), (3, 200, 3), (4, 1200, 8), (5, 600, 5))]
        # one-timers whose money and family size pull in opposite directions
        + [person(n, "חד-פעמי", 3, per_soul=str(100 * (n - 20)), souls=n - 19) for n in range(21, 27)])
path = os.path.join(TMP, "s", "haluka.db")
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for r in recs:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in r]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols])
    for i, g in enumerate(("g0001", "g0002", "g0003", "g0004", "g0005")):
        conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES (?,?,?, 'test')",
                     (f"h{i}", g, wk(-1).isoformat()))
    store.set_meta(conn, "closed_through", wk(-1).isoformat())


def mains(weeks=2):
    return [w["main"] for w in service.plan_overview(conn, NOW, weeks, path)["weeks"]]


# ── T1: what the screen shows on a database that never set anything ───────────
v = settings_service.view(conn, NOW, path)
t.ok("T1 the numbers fall back to the site's ordinary ones: 52 portions, 10 on the reserve, 4 weeks of pause",
     v["numbers"] == {"portions": 52, "reserve": 10, "cooldown_weeks": 4} and v["number_defaults"] == v["numbers"])
t.ok("T1 the six weights are the engine's: 34 / 33 / 33 and three at 0, and they add up to 100",
     [(w["key"], w["value"]) for w in v["weights"]] == [("money", 34), ("souls", 33), ("recency", 33), ("income", 0), ("housing", 0), ("medical", 0)]
     and v["weights_sum"] == 100 and all(w["label"] and w["value"] == w["default"] for w in v["weights"]))
t.ok("T1 the one-timers' queue is shown as the fixed formula it is (it has no setting)",
     sorted(q["value"] for q in v["one_time_queue"]) == [25, 25, 50] and store.get_settings(conn) == {})

# ── T2: the ordinary numbers ──────────────────────────────────────────────────
before = mains()
settings_service.save_numbers(conn, NOW, {"portions": 3, "reserve": 2, "cooldown_weeks": 4}, path)
ov = service.plan_overview(conn, NOW, 2, path)
t.ok("T2 saved numbers are what the screen shows, and every coming week is computed with them at once",
     settings_service.view(conn, NOW, path)["numbers"] == {"portions": 3, "reserve": 2, "cooldown_weeks": 4}
     and ov["defaults"]["portions"] == 3 and [len(w["main"]) for w in ov["weeks"]] == [3, 3]
     and [len(w["reserve_list"]) for w in ov["weeks"]] == [2, 2])
service.set_numbers(conn, NOW, wk(1), 5, None, path)
settings_service.save_numbers(conn, NOW, {"portions": 4, "reserve": 0, "cooldown_weeks": 4}, path)
ov = service.plan_overview(conn, NOW, 2, path)
t.ok("T2 a week that was given a number of its own keeps it when the ordinary number changes",
     [len(w["main"]) for w in ov["weeks"]] == [4, 5] and ov["weeks"][1]["numbers_set"] is True)
service.set_numbers(conn, NOW, wk(1), None, None, path)
bad_numbers = {
    "a negative number": {"portions": -1, "reserve": 0, "cooldown_weeks": 4},
    "a number above the ceiling": {"portions": 2001, "reserve": 0, "cooldown_weeks": 4},
    "a pause of more than a year": {"portions": 5, "reserve": 0, "cooldown_weeks": 53},
    "text": {"portions": "5", "reserve": 0, "cooldown_weeks": 4},
    "a fraction": {"portions": 5.5, "reserve": 0, "cooldown_weeks": 4},
    "true instead of a number": {"portions": True, "reserve": 0, "cooldown_weeks": 4},
    "a missing number": {"portions": 5, "reserve": 0},
    "nothing at all": None,
}
said = {what: refusal(lambda d=d: settings_service.save_numbers(conn, NOW, d, path)) for what, d in bad_numbers.items()}
for what, words in said.items():
    t.ok(f"T2 refused: {what}", bool(words), "it was accepted")
t.ok("T2 a refusal names the field, and nothing of a refused save is written",
     "מנות" in said["a negative number"] and "מחכה" in said["a pause of more than a year"]
     and settings_service.view(conn, NOW, path)["numbers"] == {"portions": 4, "reserve": 0, "cooldown_weeks": 4})

# ── T3: the pause of the one-timers ───────────────────────────────────────────
# six one-timers and two portions a week for them: after three weeks everybody received once
settings_service.save_numbers(conn, NOW, {"portions": 7, "reserve": 0, "cooldown_weeks": 4}, path)
with_pause = mains(5)
settings_service.save_numbers(conn, NOW, {"portions": 7, "reserve": 0, "cooldown_weeks": 0}, path)
no_pause = mains(5)
t.ok("T3 a pause of 4 weeks: in the fourth week nobody may return yet (two portions stay empty), in the fifth the first two are back",
     [len(m) for m in with_pause] == [7, 7, 7, 5, 7] and with_pause[4][5:] == with_pause[0][5:], str([m[5:] for m in with_pause]))
t.ok("T3 a pause of 0 weeks: the first two are back already in the fourth week",
     [len(m) for m in no_pause] == [7, 7, 7, 7, 7] and no_pause[3][5:] == no_pause[0][5:] and no_pause[:3] == with_pause[:3],
     str([m[5:] for m in no_pause]))
settings_service.save_numbers(conn, NOW, {"portions": 3, "reserve": 0, "cooldown_weeks": 4}, path)

# ── T4: the weights ───────────────────────────────────────────────────────────
ALL_MONEY = {"money": 100, "souls": 0, "recency": 0, "income": 0, "housing": 0, "medical": 0}
ALL_SOULS = dict(ALL_MONEY, money=0, souls=100)
settings_service.save_weights(conn, NOW, ALL_MONEY, path)
by_money = mains(1)[0]
settings_service.save_weights(conn, NOW, ALL_SOULS, path)
by_souls = mains(1)[0]
t.ok("T4 five regulars who wait the same time and three portions: the weights decide who is in — the least money, or the largest families",
     set(by_money) == {"g0003", "g0001", "g0005"} and set(by_souls) == {"g0002", "g0004", "g0005"}, str((by_money, by_souls)))
t.ok("T4 saved weights are what the screen shows",
     {w["key"]: w["value"] for w in settings_service.view(conn, NOW, path)["weights"]} == ALL_SOULS)
settings_service.save_weights(conn, NOW, dict(ALL_MONEY, money=33.3, souls=33.3, recency=33.4), path)
t.ok("T4 one decimal place is kept as it was typed",
     {w["key"]: w["value"] for w in settings_service.view(conn, NOW, path)["weights"]}["recency"] == 33.4
     and settings_service.view(conn, NOW, path)["weights_sum"] == 100)
bad_weights = {
    "a sum below 100": dict(ALL_MONEY, money=90),
    "a sum above 100": dict(ALL_MONEY, souls=1),
    "a sum that is 100 only after rounding": dict(ALL_MONEY, money=99.96),
    "a negative weight": dict(ALL_MONEY, money=110, souls=-10),
    "a weight above 100": dict(ALL_MONEY, money=150, souls=0),
    "a weight that is text": dict(ALL_MONEY, money="100"),
    "a weight that is not a number at all": dict(ALL_MONEY, money=float("nan")),
    "a missing factor": {k: v for k, v in ALL_MONEY.items() if k != "medical"},
    "a factor that does not exist": dict(ALL_MONEY, luck=0),
    "nothing at all": None,
}
kept = settings_service.view(conn, NOW, path)["weights"]
said = {what: refusal(lambda d=d: settings_service.save_weights(conn, NOW, d, path)) for what, d in bad_weights.items()}
for what, words in said.items():
    t.ok(f"T4 refused: {what}", bool(words), "it was accepted")
t.ok("T4 a refusal says what the sum is, and nothing of a refused save is written",
     "100" in said["a sum below 100"] and "90" in said["a sum below 100"] and settings_service.view(conn, NOW, path)["weights"] == kept)
def one_timers():
    d = service.week_detail(conn, NOW, W0, path)
    return [e["guid"] for e in d["main"] + d["reserve_list"] + d["out"] if e["kind"] == "onetime"]


settings_service.save_numbers(conn, NOW, {"portions": 8, "reserve": 2, "cooldown_weeks": 4}, path)
settings_service.save_weights(conn, NOW, ALL_MONEY, path)
queue_money = one_timers()
settings_service.save_weights(conn, NOW, ALL_SOULS, path)
t.ok("T4 the weights do not touch the one-timers' queue: its order is the same under opposite weights (the formula is fixed)",
     len(queue_money) == 6 and one_timers() == queue_money, str((queue_money, one_timers())))
settings_service.save_numbers(conn, NOW, {"portions": 3, "reserve": 0, "cooldown_weeks": 4}, path)

# ── T5: "what would change?" — nothing is saved ───────────────────────────────
settings_service.save_weights(conn, NOW, ALL_MONEY, path)
stored = store.get_settings(conn)
same = settings_service.preview(conn, NOW, {"weights": ALL_MONEY}, path)
t.ok("T5 the settings as they are change nothing", same["same"] is True and same["changed"] == [] and same["weeks"] == 8)
p = settings_service.preview(conn, NOW, {"weights": ALL_SOULS}, path)
first = (p["changed"] or [{}])[0]
t.ok("T5 other weights: the first week would trade two names (two come in, two go out), and the answer says so",
     p["same"] is False and (first.get("kind"), first.get("date"), first.get("enter"), first.get("leave")) == ("week", W0.isoformat(), 2, 2)
     and (first.get("main_before"), first.get("main_after")) == (3, 3), str(first))
p = settings_service.preview(conn, NOW, {"numbers": {"portions": 5, "reserve": 1, "cooldown_weeks": 4}}, path)
t.ok("T5 more portions: every coming week would grow by two names and gain a reserve",
     len(p["changed"]) == 8 and all((c["enter"], c["leave"], c["main_after"], c["reserve_after"]) == (2, 0, 5, 1) for c in p["changed"]))
t.ok("T5 asking changed nothing: the settings and the lists are as they were",
     store.get_settings(conn) == stored and set(mains(1)[0]) == {"g0003", "g0001", "g0005"})
g = event_service.save(conn, NOW, {"date": (wk(11) + timedelta(days=1)).isoformat(), "holiday": "*", "portions": 2,
                                   "reserve": 0, "criteria": {}}, path)["guid"]
with store.tx(conn):
    conn.execute("UPDATE recipients SET holiday_support=1")
p = settings_service.preview(conn, NOW, {"numbers": {"portions": 5, "reserve": 0, "cooldown_weeks": 4}}, path)
t.ok("T5 the look ahead reaches a holiday event that is further than eight weeks away",
     p["weeks"] == 12 and len([c for c in p["changed"] if c["kind"] == "week"]) == 12)
bad_preview = [None, {}, {"numbers": None, "weights": None}, {"weights": dict(ALL_MONEY, money=50)},
               {"numbers": {"portions": -1, "reserve": 0, "cooldown_weeks": 4}}]
t.ok("T5 a look ahead at nothing, or at settings that could not be saved, is refused",
     all(refusal(lambda d=d: settings_service.preview(conn, NOW, d, path)) for d in bad_preview))
conn.close()

shutil.rmtree(TMP, ignore_errors=True)
t.done()

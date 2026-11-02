# -*- coding: utf-8 -*-
"""סימולציית שנה אקראית של חלוקות — בדיקה מבוססת-מודל (Hypothesis, 2/11/2026).

במקום תרחישים שכתבתי מראש, Hypothesis מייצרת אלפי רצפים אקראיים של פעולות שרון עושה
במשך שנה — הוספת קבוע/חד-פעמי, רישום חלוקת רביעי (עם מי שלא הגיע), חלוקה נוספת
בראשון, בונוס, חג, השהיה/החזרה, שינוי תדירות, מעבר ימים — ואחרי **כל** צעד בודקת
שכללי "מי מקבל" (CLAUDE.md, כללים 6/7/9) נשמרים ב-DB האמיתי:

  I1  בלי כפילויות; רק פעילים; ברשימה השבועית רק קבועים; ברשימת החד-פעמיים רק חד-פעמיים
  I2  כלל 9: קבוע שקיבל חלוקה רגילה בראשון–רביעי של הרביעי הקרוב — לא ברשימה
  I3  כלל 6 בשני הכיוונים: קבוע ברשימה ⇔ תורו הגיע (ולא קיבל השבוע) — תופס גם "נעלם"
  I4  כלל 7 בשני הכיוונים: חד-פעמי מועמד ⇔ לא קיבל ב-4 השבועות האחרונים
  I5  last/next_distribution בכרטיס נגזרים נכון מההיסטוריה (next = רביעי, לפי התדירות,
      חג/בונוס לא מזיזים את התור)

המודל נכתב כאן מחדש מהתיעוד (לא קורא ל-selection) — כך שסתירה = באג בקוד או בתיעוד.
כשנמצא כשל, Hypothesis מכווצת את הרצף למינימום ומדפיסה אותו (ומזכירה אותו ב-.hypothesis/).

הרצה: python test_simulation.py [דוגמאות]   (Python 3.12; ברירת מחדל 40 דוגמאות)
"""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date as _real_date, timedelta

import database as db
import selection
import holidays
from hypothesis import settings, HealthCheck, Phase
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, precondition, run_state_machine_as_test

_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups")

START = _real_date(2026, 11, 2)            # אחרי EXTRA_BY_WEEKDAY_BEFORE (18/10/2026)
COOLDOWN = 4
INTERVAL = {"שבועי": 7, "דו-שבועי": 14, "תלת-שבועי": 21, "חודשי": 28}
FREQS = list(INTERVAL)
_SIM = {"today": START}


class _FakeDate(_real_date):
    @classmethod
    def today(cls):
        t = _SIM["today"]
        return _real_date(t.year, t.month, t.day)


db.date = _FakeDate
selection._date = _FakeDate


# ── מודל עצמאי (מהתיעוד) ──────────────────────────────────────────────────────────
def wed_of(d):
    """הרביעי שחלוקה בתאריך d שייכת לו: ה׳–ש׳ → הרביעי שלפני; א׳–ג׳ → הרביעי שאחרי."""
    wd = d.weekday()
    if wd == 2:
        return d
    if wd in (3, 4, 5):
        return d - timedelta(days=wd - 2)
    return d + timedelta(days=(2 - wd) % 7)


def upcoming_wed(d):
    return d if d.weekday() == 2 else d + timedelta(days=(2 - d.weekday()) % 7)


def model_next(last_regular, freq):
    """תורו הבא של קבוע לפי התיעוד: רביעי המחזור + המרווח."""
    if last_regular is None:
        return None
    return wed_of(last_regular) + timedelta(days=INTERVAL[freq])


class Sim(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        d = tempfile.mkdtemp()                       # DB חדש לכל ריצה (Windows לא משחרר קובץ פתוח)
        db.DB_PATH = os.path.join(d, "data.db"); db.BACKUP_DIR = os.path.join(d, "backups")
        _SIM["today"] = START
        db.init_db()
        db.set_setting("onetime_cooldown_weeks", str(COOLDOWN))
        self.people = {}        # id -> {"kind": "reg"/"one", "freq", "active": bool, "name"}
        self.rounds = []        # (rec_id, date, extra: bool)   — received=1 בלבד
        self.n = 0
        self.weeks = 0

    # ── עזרים ──
    def _active(self, kind):
        return [i for i, p in self.people.items() if p["kind"] == kind and p["active"]]

    def _served(self, rid, regular_only=False):
        return [d for (r, d, extra) in self.rounds if r == rid and (not extra or not regular_only)]

    def _record(self, ids, when, no_show_ids=(), holiday=""):
        rows = [{"id": i, "full_name": self.people[i]["name"], "frequency": self.people[i]["freq"]}
                for i in ids]
        miss = [{"id": i, "full_name": self.people[i]["name"]} for i in no_show_ids]
        db.bulk_add_distributions(rows, when.isoformat(), "מצרכים", 1, "סימולציה",
                                  not_received=miss, holiday=holiday)
        extra = bool(holiday)
        for i in ids:
            self.rounds.append((i, when, extra))

    # ── פעולות ──
    @rule(freq=st.sampled_from(FREQS), served_ago=st.integers(0, 60) | st.none(),
          souls=st.integers(1, 9))
    def add_regular(self, freq, served_ago, souls):
        self.n += 1
        name = f"קבוע {self.n}"
        rid = db.add_recipient({"full_name": name, "status": "פעיל", "frequency": freq,
                                "priority": 4, "souls": souls})
        self.people[rid] = {"kind": "reg", "freq": freq, "active": True, "name": name}
        if served_ago is not None:                          # היסטוריה ישנה (לפני START)
            when = _SIM["today"] - timedelta(days=served_ago)
            if when >= START:
                self._record([rid], when)

    @rule(prio=st.sampled_from([3, 2]), souls=st.integers(1, 9), kids=st.integers(0, 6))
    def add_one_timer(self, prio, souls, kids):
        self.n += 1
        name = f"חדפ {self.n}"
        rid = db.add_recipient({"full_name": name, "status": "פעיל", "frequency": "חד-פעמי",
                                "priority": prio, "souls": souls, "children_total": kids})
        self.people[rid] = {"kind": "one", "freq": "חד-פעמי", "active": True, "name": name}

    @rule(days=st.integers(1, 7))
    def advance(self, days):
        _SIM["today"] = _SIM["today"] + timedelta(days=days)

    @precondition(lambda self: self.people)
    @rule(data=st.data(), day_offset=st.integers(0, 2))
    def record_wednesday_round(self, data, day_offset):
        """רון רושם את חלוקת הרביעי (אולי יום-יומיים אחרי): הרשימה שהתוכנה הציעה
        + כמה חד-פעמיים מהתור; חלק לא הגיעו."""
        today = _SIM["today"]
        wed = upcoming_wed(today)
        when = wed + timedelta(days=day_offset)          # רביעי / חמישי / שישי
        if when > today + timedelta(days=0) and day_offset:
            when = wed
        if wed > today:
            _SIM["today"] = wed                          # מגיעים ליום החלוקה
            when = wed
        listed = [r["id"] for r in db.get_weekly_list()]
        ones = [r["id"] for r in db.get_one_time_list() if r.get("in_distribution")][:3]
        ids = listed + ones
        if not ids:
            return
        miss = data.draw(st.lists(st.sampled_from(ids), unique=True, max_size=len(ids)))
        got = [i for i in ids if i not in miss]
        self._record(got, when, no_show_ids=miss)
        self.weeks += 1

    @precondition(lambda self: self._active("reg"))
    @rule(data=st.data(), kind=st.sampled_from(["sunday", "bonus", "holiday"]))
    def record_extra_round(self, data, kind):
        """חלוקה נוספת: ראשון רגיל (מזיז תור!), בונוס או חג (לא מזיזים)."""
        today = _SIM["today"]
        pool = self._active("reg") + self._active("one")
        ids = data.draw(st.lists(st.sampled_from(pool), unique=True, min_size=1, max_size=6))
        if kind == "sunday":
            when = today - timedelta(days=(today.weekday() + 1) % 7)       # הראשון האחרון
            if when < START:
                return
            self._record(ids, when)
        elif kind == "bonus":
            self._record(ids, today, holiday=holidays.BONUS)
        else:
            self._record(ids, today, holiday="פסח")

    @precondition(lambda self: self.people)
    @rule(data=st.data())
    def toggle_status(self, data):
        rid = data.draw(st.sampled_from(sorted(self.people)))
        p = self.people[rid]
        p["active"] = not p["active"]
        db.update_recipient(rid, {"status": "פעיל" if p["active"] else "מושהה"})

    @precondition(lambda self: self._active("reg"))
    @rule(data=st.data(), freq=st.sampled_from(FREQS))
    def change_frequency(self, data, freq):
        rid = data.draw(st.sampled_from(self._active("reg")))
        self.people[rid]["freq"] = freq
        db.update_recipient(rid, {"frequency": freq})

    # ── אינווריאנטים ──
    @invariant()
    def lists_are_sane(self):
        today = _SIM["today"]
        base = upcoming_wed(today)
        weekly = db.get_weekly_list()
        ones = db.get_one_time_list()
        wids = [r["id"] for r in weekly]
        assert len(wids) == len(set(wids)), f"I1 כפילות ברשימה השבועית: {wids}"
        for r in weekly:
            p = self.people[r["id"]]
            assert p["active"] and p["kind"] == "reg", f"I1 {p['name']} לא קבוע-פעיל אבל ברשימה"
        for r in ones:
            p = self.people[r["id"]]
            assert p["active"] and p["kind"] == "one", f"I1 {p['name']} לא חד-פעמי-פעיל אבל ברשימת החד-פעמיים"

        # I2 + I3 — כללים 9 ו-6, בשני הכיוונים
        onlist = set(wids)
        for rid in self._active("reg"):
            p = self.people[rid]
            reg = self._served(rid, regular_only=True)
            served_this_week = any(base - timedelta(days=3) <= d <= base for d in reg)
            last_reg = max((d for d in reg if d <= base), default=None)
            nxt = model_next(last_reg, p["freq"])
            due = (nxt is None or nxt <= base) and not served_this_week
            assert (rid in onlist) == due, (
                f"{'I2/I3' if served_this_week else 'I3'} {p['name']} ({p['freq']}): "
                f"ברשימה={rid in onlist} אבל לפי המודל due={due}; "
                f"היום={today} רביעי={base} אחרונה-רגילה={last_reg} תור={nxt} קיבל-השבוע={served_this_week}")

        # I4 — כלל 7 בשני הכיוונים
        cand = {r["id"] for r in ones if r.get("in_distribution")}
        for rid in self._active("one"):
            p = self.people[rid]
            srv = self._served(rid)
            last = max((d for d in srv if d <= base), default=None)
            eligible = last is None or wed_of(last) + timedelta(weeks=COOLDOWN) <= base
            assert (rid in cand) == eligible, (
                f"I4 {p['name']}: מועמד={rid in cand} אבל לפי המודל זכאי={eligible}; "
                f"היום={today} רביעי={base} אחרונה={last}")

    @invariant()
    def card_dates_derived(self):
        base = upcoming_wed(_SIM["today"])
        for rid, p in self.people.items():
            rec = db.get_recipient(rid)
            srv = [d for d in self._served(rid) if d <= base]
            last = max(srv, default=None)
            got = rec.get("last_distribution") or ""
            assert got == (last.isoformat() if last else ""), \
                f"I5 {p['name']}: last_distribution={got!r} צפוי {last}"
            nxt = rec.get("next_distribution") or ""
            if p["kind"] == "reg":
                reg = [d for d in self._served(rid, regular_only=True) if d <= base]
                if reg:
                    exp = model_next(max(reg), p["freq"])
                    assert nxt == exp.isoformat() and exp.weekday() == 2, \
                        f"I5 {p['name']} ({p['freq']}): next_distribution={nxt!r} צפוי {exp} (אחרונה-רגילה={max(reg)})"
                else:
                    # קבוע שטרם קיבל: "חייב מיד". הערך השמור = הרביעי הקרוב בזמן הכתיבה,
                    # ומתעדכן עצלנית (init_db / get_weekly_list) — מותר רביעי שעבר, לא עתידי.
                    n = _real_date.fromisoformat(nxt)
                    assert n.weekday() == 2 and n <= base, \
                        f"I5 {p['name']}: טרם קיבל אבל next_distribution={nxt!r} אחרי {base}"
            else:
                assert nxt == "", f"I5 {p['name']}: לחד-פעמי אין next_distribution, יש {nxt!r}"


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    Sim.TestCase.settings = settings(
        max_examples=n, stateful_step_count=40, deadline=None,
        suppress_health_check=list(HealthCheck), print_blob=True,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink))
    try:
        run_state_machine_as_test(Sim, settings=Sim.TestCase.settings)
    except AssertionError as e:
        print("\n✗ הסימולציה מצאה הפרת כלל:\n", e)
        sys.exit(1)
    print(f"Ran {n} simulated runs (up to {Sim.TestCase.settings.stateful_step_count} steps each) … OK")

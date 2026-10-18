# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 2, S1: הליבה הטהורה של נעילת רשימות (selection.py).

מוכיח (P1–P12) את הכללים שבתוכנית docs/plans/הכנה_קדימה_נעילה.md סעיף 3:
  • round_wednesday   — לאיזה רביעי שייך תאריך (ראשון–רביעי קדימה, חמישי–שבת אחורה)
  • plan_interval_days / planned_elsewhere — "תפוס בתכנון", סימטרי, לפי התדירות
  • plan_state        — נעולה / עתידית / בוצעה / פגה (נגזר, לא נשמר)
  • התג planned_elsewhere בתוך is_due ו-not_due_reason, ונכשל-פתוח בלי התג

פונקציות טהורות — אין DB, אין Qt, אין שעון. הרצה: python test_plan_selection.py
"""
import os, sys, inspect
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

from datetime import date, timedelta

import selection as sel

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


D = date.fromisoformat
W0, W1, W2, W3, W4, W5 = (D(s) for s in
                          ("2026-10-14", "2026-10-21", "2026-10-28", "2026-11-04", "2026-11-11", "2026-11-18"))
assert all(w.weekday() == 2 for w in (W0, W1, W2, W3, W4, W5)), "הרביעים בבדיקה חייבים להיות ימי רביעי"


def R(guid, freq, **kw):
    r = {"id": guid, "guid": guid, "full_name": guid, "frequency": freq, "priority": 4 if freq != "חד-פעמי" else 3}
    r.update(kw)
    return r


def blocked_on(rec, weeks, locks, cooldown=4):
    """אילו מהשבועות חסומים לאדם כשהוא נעול ב-`locks`."""
    idx = {rec["guid"]: list(locks)}
    return [w for w in weeks if sel.planned_elsewhere(rec, w, idx, cooldown)]


# ── P1 — round_wednesday ──────────────────────────────────────────────────────
exp = {"2026-10-18": W1, "2026-10-19": W1, "2026-10-20": W1, "2026-10-21": W1,       # ראשון..רביעי ← קדימה
       "2026-10-22": W1, "2026-10-23": W1, "2026-10-24": W1,                          # חמישי..שבת ← אחורה
       "2026-10-25": W2}                                                               # ראשון הבא
bad = {k: sel.round_wednesday(D(k)) for k, v in exp.items() if sel.round_wednesday(D(k)) != v}
ok("P1a ראשון–רביעי ← הרביעי שבו/אחריו, חמישי–שבת ← הרביעי שלפניהם", not bad, str(bad))
ok("P1b גבול שנה: 28–30/12 ← 30/12; 31/12, 1/1, 2/1 ← 30/12; 3/1 ← 6/1",
   [sel.round_wednesday(D(s)) for s in ("2026-12-28", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03")]
   == [D("2026-12-30")] * 5 + [D("2027-01-06")])
ok("P1c התוצאה תמיד רביעי, ו-100 ימים רצופים מתנהגים אחיד",
   all(sel.round_wednesday(W0 + timedelta(days=i)).weekday() == 2
       and -3 <= (sel.round_wednesday(W0 + timedelta(days=i)) - (W0 + timedelta(days=i))).days <= 3
       for i in range(100)))
ok("P1d עקבי עם next_due/כלל 9: ראשון נספר לרביעי שאחריו (בניגוד ל-cycle_wednesday)",
   sel.round_wednesday(D("2026-10-18")) == W1 and sel.cycle_wednesday(D("2026-10-18")) == W0)

# ── P2 — plan_interval_days ───────────────────────────────────────────────────
iv = sel.plan_interval_days
ok("P2a תדירויות: שבועי 7 · דו 14 · תלת 21 · חודשי 28",
   [iv(R("a", f)) for f in ("שבועי", "דו-שבועי", "תלת-שבועי", "חודשי")] == [7, 14, 21, 28])
ok("P2b קבוע בלי תדירות (עדיפות 4) ← 7",
   iv({"guid": "a", "frequency": "", "priority": 4}) == 7)
ok("P2c חד-פעמי: הפסקה 4 ← 28 · 2 ← 14 · 0 / None / זבל ← 7",
   [iv(R("a", "חד-פעמי"), c) for c in (4, 2, 0, None, "x")] == [28, 14, 7, 7, 7])
ok("P2d ברירת מחדל = הפסקת החד-פעמיים הרשמית", iv(R("a", "חד-פעמי")) == 7 * sel.ONE_TIME_COOLDOWN_WEEKS_DEFAULT)

# ── P3 — planned_elsewhere, חודשי ─────────────────────────────────────────────
Ym = R("ym", "חודשי")
weeks = [W0, W1, W2, W3, W4, W5]
ok("P3a חודשי נעול ב-W1: W2, W3, W4 חסומים; W0 (−1) חסום; W5 (+4) מותר",
   blocked_on(Ym, weeks, [W1]) == [W0, W2, W3, W4], str(blocked_on(Ym, weeks, [W1])))
ok("P3b חודשי: חסום ב-±7/14/21 ימים, מותר ב-±28 בדיוק",
   all(sel.planned_elsewhere(Ym, W2 + timedelta(days=d), {"ym": [W2]}) for d in (-21, -14, -7, 7, 14, 21))
   and not any(sel.planned_elsewhere(Ym, W2 + timedelta(days=d), {"ym": [W2]}) for d in (-28, 28, -35, 35)))
ok("P3c אותו שבוע של הנעילה לא נחסם (d=0), והתשובה היא תאריך הנעילה",
   sel.planned_elsewhere(Ym, W1, {"ym": [W1]}) is None and sel.planned_elsewhere(Ym, W2, {"ym": [W1]}) == W1)

# ── P4 — דו-שבועי / תלת-שבועי / שבועי ─────────────────────────────────────────
Yb, Yt, Yw = R("yb", "דו-שבועי"), R("yt", "תלת-שבועי"), R("yw", "שבועי")
ok("P4a דו-שבועי נעול ב-W2: W1 ו-W3 חסומים (±7), W0 ו-W4 מותרים (±14)",
   blocked_on(Yb, weeks, [W2]) == [W1, W3], str(blocked_on(Yb, weeks, [W2])))
ok("P4b תלת-שבועי נעול ב-W2: ±7 ו-±14 חסומים, ±21 מותר",
   blocked_on(Yt, [W0, W1, W3, W4, W5], [W2]) == [W0, W1, W3, W4], str(blocked_on(Yt, [W0, W1, W3, W4, W5], [W2])))
ok("P4c שבועי: אף פעם לא נחסם (גם לא קבוע בלי תדירות)",
   blocked_on(Yw, weeks, [W2]) == []
   and blocked_on({"guid": "yn", "frequency": "", "priority": 4}, weeks, [W2]) == [])

# ── P5 — is_due עם התג, ובלי התג כמו היום ─────────────────────────────────────
Z = R("z", "שבועי", last_distribution="2026-10-14")            # שבועי שקיבל ב-W0
M = R("m", "חודשי", last_distribution="2026-10-14")            # חודשי שקיבל ב-W0 ← התור ב-11/11
B = R("b", "דו-שבועי", last_distribution="2026-10-14")         # דו-שבועי שקיבל ב-W0 ← התור ב-28/10
O = R("o", "חד-פעמי", last_distribution="2026-10-14")          # חד-פעמי שקיבל ב-W0 ← חוזר ב-11/11
table = [("שבועי W1", Z, W1, True), ("חודשי W1", M, W1, False), ("חודשי W4", M, W4, True),
         ("דו-שבועי W1", B, W1, False), ("דו-שבועי W2", B, W2, True),
         ("חד-פעמי W1", O, W1, False), ("חד-פעמי W4", O, W4, True),
         ("חד-פעמי הפסקה 0", O, W1, True)]
got = [(n, sel.is_due(r, w, 0 if "הפסקה 0" in n else 4)) for n, r, w, _ in table]
ok("P5a בלי תג — is_due כמו היום (8 מקרי ייחוס)", all(g[1] == t[3] for g, t in zip(got, table)), str(got))
ok("P5b תג ריק/None/'' לא משנה כלום",
   all(sel.is_due({**r, "planned_elsewhere": v}, w, 4) == (t if "הפסקה 0" not in n else sel.is_due(r, w, 0))
       for n, r, w, t in table[:7] for v in (None, "", False)))
ok("P5c עם תג — לא בתור, גם מי שתורו הגיע (שבועי / דו-שבועי W2 / חד-פעמי W4)",
   not sel.is_due({**Z, "planned_elsewhere": W2.isoformat()}, W1, 4)
   and not sel.is_due({**B, "planned_elsewhere": W3}, W2, 4)
   and not sel.is_due({**O, "planned_elsewhere": "2026-11-18"}, W4, 4))
ok("P5d due_filter: עם תג מסונן; חלוקת חג (ignore=True) מדלגת על השער ולא מסננת",
   [r["guid"] for r in sel.due_filter([{**Z, "planned_elsewhere": W2}, B], W2, cooldown_weeks=4)] == ["b"]
   and len(sel.due_filter([{**Z, "planned_elsewhere": W2}, B], W2, ignore=True)) == 2)

# ── P6 — מעולם לא קיבל + נעול בשבוע אחר ← חסום ────────────────────────────────
Nm = R("nm", "חודשי")                                          # בלי last_distribution
tag = sel.planned_elsewhere(Nm, W2, {"nm": [W1]})
ok("P6a חודשי שטרם קיבל: בלי תג חייב מיד (כמו היום)", sel.is_due(Nm, W2, 4) and sel.is_due(Nm, W1, 4))
ok("P6b חודשי שטרם קיבל + נעול ב-W1 ← חסום ב-W2 (התג לפני 'last is None')",
   tag == W1 and not sel.is_due({**Nm, "planned_elsewhere": tag}, W2, 4))

# ── P7 — not_due_reason ───────────────────────────────────────────────────────
ok("P7a עם תג: 'נעול ברשימה של 21/10' (תאריך / ISO)",
   sel.not_due_reason({**B, "planned_elsewhere": W1}, W2, 4) == "נעול ברשימה של 21/10"
   and sel.not_due_reason({**B, "planned_elsewhere": "2026-10-21"}, W2, 4) == "נעול ברשימה של 21/10")
ok("P7b תג שאינו תאריך ← 'נעול ברשימה של שבוע אחר' (לא קורס)",
   sel.not_due_reason({**B, "planned_elsewhere": True}, W2, 4) == "נעול ברשימה של שבוע אחר")
ok("P7c בלי תג — הסיבות הקיימות לא השתנו",
   sel.not_due_reason(B, W1, 4) == "דו-שבועי · קיבל ב-14/10 · התור הבא 28/10"
   and sel.not_due_reason(M, W1, 4) == "חודשי · קיבל ב-14/10 · התור הבא 11/11"
   and sel.not_due_reason(O, W1, 4) == "קיבל ב-14/10 · הפסקה של 4 שבועות · חוזר ב-11/11")
ok("P7d מי שבתור — סיבה ריקה (בלי תג)", sel.not_due_reason(Z, W1, 4) == "")
ok("P7e חד-פעמי שטרם קיבל + תג ← גם הוא מוסבר", "נעול" in sel.not_due_reason(
    {**R("n1", "חד-פעמי"), "planned_elsewhere": W3}, W2, 4))

# ── P8 — plan_state ───────────────────────────────────────────────────────────
ps = sel.plan_state
ok("P8a השבוע שמכינים ← current (ראשון, רביעי)", ps(W1, D("2026-10-18"), False) == "current"
   and ps(W1, W1, False) == "current")
ok("P8b שבוע אחרי ← future (גם ברביעי עצמו של השבוע שלפניו)",
   ps(W2, D("2026-10-18"), False) == "future" and ps(W2, W1, False) == "future")
ok("P8c גבול: שבת (wed+3) עדיין חיה ותופסת, ראשון (wed+4) פגה",
   ps(W1, D("2026-10-24"), False) == "current" and ps(W1, D("2026-10-25"), False) == "stale")
ok("P8d חלון הרישום: חמישי–שבת אחרי W1 ← W1 עדיין current ו-W2 עכשיו current (הרביעי הקרוב)",
   ps(W1, D("2026-10-22"), False) == "current" and ps(W2, D("2026-10-22"), False) == "current")
ok("P8e executed גובר על הכול (גם על פגה ועל עתידית)",
   ps(W1, D("2026-12-01"), True) == "executed" and ps(W5, D("2026-10-18"), True) == "executed")
ok("P8f רק current/future תופסות (stale/executed — לא)",
   {s for s in ("current", "future")} == {ps(W1, W1, False), ps(W3, W1, False)}
   and {ps(W1, D("2026-11-30"), False), ps(W1, W1, True)} == {"stale", "executed"})

# ── P9 — שרשרת (הדוגמה של 3.3 + נעילות W1,W3) ─────────────────────────────────
X, Y, Zz = R("x", "דו-שבועי"), R("y", "חודשי"), R("z9", "שבועי")
idx = {"x": [W1], "y": [W1], "z9": [W1]}                       # נועלים W1 עם X, Y, Z
def on(wk, rec): return sel.planned_elsewhere(rec, wk, idx, 4) is not None
ok("P9a אחרי נעילת W1: W2 — X חסום, Y חסום, Z נכנס", on(W2, X) and on(W2, Y) and not on(W2, Zz))
ok("P9b W3: X נכנס (d=14), Y חסום", not on(W3, X) and on(W3, Y))
ok("P9c W5: Y נכנס (d=28)", not on(W5, Y))
idx2 = {"x": [W1, W3], "y": [W1, W5]}                           # שרשרת: W1+W3 לדו-שבועי, W1+W5 לחודשי
ok("P9d נעילות W1,W3: W2 ו-W4 חסומים לדו-שבועי, W5 מותר",
   all(sel.planned_elsewhere(X, w, idx2, 4) for w in (W2, W4)) and not sel.planned_elsewhere(X, W5, idx2, 4))
ok("P9e חודשי נעול ב-W1 וב-W5: W2, W3, W4 חסומים",
   all(sel.planned_elsewhere(Y, w, idx2, 4) for w in (W2, W3, W4)))
ok("P9f כמה נעילות מחזיקות — מוחזרת הקרובה (שוויון ← המוקדמת)",
   sel.planned_elsewhere(X, W2, idx2, 4) == W1 and sel.planned_elsewhere(X, W4, idx2, 4) == W3)

# ── P10 — סימטריה: נעילה מאוחרת חוסמת שבוע מוקדם ──────────────────────────────
Ys = R("ys", "חודשי", last_distribution="2026-09-30")          # תורו ב-28/10 = W2
tag10 = sel.planned_elsewhere(Ys, W2, {"ys": [W4]}, 4)
ok("P10a חודשי שתורו הגיע ב-W2 ונעול ב-W4 ← נחסם ב-W2 (d=14)",
   sel.is_due(Ys, W2, 4) and tag10 == W4 and not sel.is_due({**Ys, "planned_elsewhere": tag10}, W2, 4))
ok("P10b ההסבר מצביע על הנעילה המאוחרת", sel.not_due_reason({**Ys, "planned_elsewhere": tag10}, W2, 4)
   == "נעול ברשימה של 11/11")
ok("P10c נעילה ב-W4 חוסמת גם את W1 (d=21), W3, W5 — ומשחררת את W0 (d=28)",
   blocked_on(Ym, [W0, W1, W2, W3, W5], [W4]) == [W1, W2, W3, W5])

# ── P11 — חד-פעמי תופס ארבעה שבועות; מי שלא באינדקס לא נחסם ───────────────────
On = R("on", "חד-פעמי")
ok("P11a חד-פעמי main נעול ב-W1 (הפסקה 4): W2, W3, W4 חסומים, W5 מותר",
   blocked_on(On, [W2, W3, W4, W5], [W1], 4) == [W2, W3, W4])
ok("P11b הפסקה 2: רק W2 חסום · הפסקה 0 (כבוי): אף שבוע",
   blocked_on(On, [W2, W3, W4], [W1], 2) == [W2] and blocked_on(On, [W2, W3, W4], [W1], 0) == [])
ok("P11c מי שאינו באינדקס (למשל רזרבה, שאינה נכנסת ל-live_plan_index) לא נחסם",
   sel.planned_elsewhere(R("res", "חודשי"), W2, {"other-guid": [W1]}) is None)

# ── P12 — בלי שעון, ונכשל-פתוח ────────────────────────────────────────────────
src = "".join(inspect.getsource(f) for f in
              (sel.round_wednesday, sel.plan_interval_days, sel.planned_elsewhere, sel.plan_state))
ok("P12a אין קריאה ל-date.today() בפונקציות החדשות (today מועבר)", "today()" not in src and ".today" not in src)
ok("P12b נכשל-פתוח: אין guid / אינדקס ריק או None / תאריך זבל באינדקס ← None",
   sel.planned_elsewhere({"frequency": "חודשי", "priority": 4}, W2, {"ym": [W1]}) is None
   and sel.planned_elsewhere(Ym, W2, {}) is None and sel.planned_elsewhere(Ym, W2, None) is None
   and sel.planned_elsewhere(Ym, W2, {"ym": ["לא-תאריך", None]}) is None)
ok("P12c האינדקס יכול להחזיק תאריכי ISO (טקסט) כמו מה שנקרא מ-JSON",
   sel.planned_elsewhere(Ym, W2, {"ym": ["2026-10-21"]}) == W1)
ok("P12d האינדקס עצמו לא משתנה בקריאה (קריאה בלבד)",
   (lambda i: (sel.planned_elsewhere(Ym, W2, i), i)[1] == {"ym": [W1, W5]})({"ym": [W1, W5]}))

print()
print("RESULT:", "ALL PLAN-SELECTION TESTS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

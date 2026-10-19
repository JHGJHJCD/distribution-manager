# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 2, נעילת רשימות: שכבת הנתונים (database.py).

מוכיח (D1–D12, docs/plans/הכנה_קדימה_נעילה.md סעיף 7.2):
  • נעילה = מפתח אחד בהגדרות (`planned_dist:<רביעי>`), ערך JSON עם guid בלבד
  • updated_at = "עכשיו" (לא תאריך עסקי), אסימון התנגשות
  • "בוצעה"/"פגה" נגזרות מההיסטוריה, רק נעילה חיה "תופסת", רק main
  • שכבת קריאה בלבד: אף כתיבה לנתוני המקבלים/החלוקות
  • חיבור השער לחמש הרשימות, ובלי שום נעילה — הרשימות זהות לקודם

תמיד DB זמני — לעולם לא %APPDATA%. הרצה: python test_plans.py
"""
import os, sys, tempfile, json, copy
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

from datetime import date, datetime, timedelta, timezone

import database as db
import selection
import holidays

_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db")
db.BACKUP_DIR = os.path.join(_d, "backups")
db.init_db()

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


D = date.fromisoformat
W0, W1, W2, W3, W4, W5 = (D(s) for s in
                          ("2026-10-14", "2026-10-21", "2026-10-28", "2026-11-04", "2026-11-11", "2026-11-18"))
TODAY = D("2026-10-18")                      # ראשון — W1 הוא הרביעי הקרוב


def mk(name, freq, **kw):
    rid = db.add_recipient({"full_name": name, "status": "פעיל", "frequency": freq,
                            "priority": 4 if freq != "חד-פעמי" else 3, "souls": 3, **kw})
    return rid, db.get_recipient(rid)["guid"]


def snapshot():
    with db.get_connection() as c:
        return {t: [dict(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY id")]
                for t in ("recipients", "distributions", "dist_batches")}


def raw_plan(wed):
    with db.get_connection() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (db.PLAN_PREFIX + wed.isoformat(),)).fetchone()
    return r["value"] if r else None


def batch(dist_date, holiday="", rids=()):
    recs = [{"id": i, "full_name": f"x{i}", "area": "", "souls": 1} for i in rids]
    return db.bulk_add_distributions(recs, dist_date, "מנה", 1, "בדיקה", dist_name="בדיקה", holiday=holiday)


def P(wed, members, **kw):
    return {"week_wed": wed, "members": members, "products": 5, "reserve": 1, **kw}


def M(g, role="main", kind="reg", note="", n=""):
    return {"g": g, "role": role, "kind": kind, "note": note, "n": n}


# ─── נתוני בדיקה ───────────────────────────────────────────────────────────────
r_mon, g_mon = mk("חודשי", "חודשי")
r_biw, g_biw = mk("דו שבועי", "דו-שבועי")
r_wk, g_wk = mk("שבועי", "שבועי")
r_one, g_one = mk("חד פעמי", "חד-פעמי")
r_res, g_res = mk("רזרבה חודשי", "חודשי")

# ── D1 — save / get / list / delete, מפתח ייחודי, רק רביעי, רק שדות מותרים ────
before = snapshot()
ok("D1a אין נעילות בהתחלה", db.list_plans() == [] and db.get_plan(W1) is None and db.live_plan_index(TODAY) == {})
doc = db.save_plan(P(W1, [M(g_mon), M(g_wk, kind="man", note="הערה", n="שבועי")]))
got = db.get_plan(W1)
ok("D1b שמירה וקריאה: אותם חברים בסדר, הערה נשמרה",
   [m["g"] for m in got["members"]] == [g_mon, g_wk] and got["members"][1]["note"] == "הערה"
   and got["products"] == 5 and got["reserve"] == 1, str(got["members"]))
ok("D1c המפתח היחיד בהגדרות הוא planned_dist:<רביעי>",
   raw_plan(W1) is not None and raw_plan(W1) and json.loads(raw_plan(W1))["week_wed"] == "2026-10-21")
db.save_plan(P(W1, [M(g_mon)]))
ok("D1d שמירה שנייה לאותו רביעי מחליפה (אין כפילות)", len(db.list_plans()) == 1
   and [m["g"] for m in db.get_plan(W1)["members"]] == [g_mon])
db.save_plan(P(W3, [M(g_biw)]))
ok("D1e list_plans ממוין לפי תאריך ו-from_wed מסנן",
   [p["week_wed"] for p in db.list_plans()] == ["2026-10-21", "2026-11-04"]
   and [p["week_wed"] for p in db.list_plans(from_wed=W2)] == ["2026-11-04"])
try:
    db.save_plan(P(D("2026-10-22"), [M(g_mon)])); bad_thu = False
except ValueError:
    bad_thu = True
try:
    db.save_plan({"members": []}); bad_none = False
except (ValueError, TypeError):
    bad_none = True
ok("D1f תאריך שאינו רביעי (או חסר) נדחה", bad_thu and bad_none)
db.save_plan(P(W2, [{"g": g_mon, "role": "main", "kind": "reg", "frequency": "חודשי", "phone1": "050",
                     "need_score": 99, "last_distribution": "2026-01-01", "id": 7}, {"g": ""}, "junk", None, M(g_mon)]))
stored = json.loads(raw_plan(W2))
ok("D1g מה שנשמר: רק g/role/kind/note/n — בלי תדירות, תאריכים, ניקוד, טלפון, id; בלי ריקים וכפולים",
   [set(m) for m in stored["members"]] == [{"g", "role", "kind", "note", "n"}] and len(stored["members"]) == 1
   and not ({"frequency", "last_distribution", "next_distribution", "need_score"} & set(stored)))
ok("D1h מחיקה רכה: get ו-list לא מראים; המפתח נשאר עם ערך מינימלי; מחיקה חוזרת = False",
   db.delete_plan(W2) is True and db.get_plan(W2) is None and "2026-10-28" not in [p["week_wed"] for p in db.list_plans()]
   and json.loads(raw_plan(W2))["deleted"] == 1 and json.loads(raw_plan(W2))["members"] == []
   and db.delete_plan(W2) is False and db.get_plan(W2, include_deleted=True)["deleted"] == 1)
ok("D1i נעילה שבורה/ריקה בהגדרות = לא נעילה (לא מפילה רשימה)",
   (db.set_setting(db.PLAN_PREFIX + "2026-11-18", "{לא json"), db.get_plan(W5) is None
    and "2026-11-18" not in [p["week_wed"] for p in db.list_plans()])[1])
db.set_setting(db.PLAN_PREFIX + "2026-11-18", "")
db.delete_plan(W3)
ok("D1j חידוש אחרי מחיקה = נעילה חדשה (created_at חדש)",
   db.save_plan(P(W3, [M(g_wk)]))["members"][0]["g"] == g_wk and db.get_plan(W3) is not None)

# ── D2 — updated_at = עכשיו, לא תאריך עסקי ──────────────────────────────────────
far = db.save_plan(P(D("2026-11-25"), [M(g_mon)]))                # נעילה ל-+38 יום
stamp = datetime.fromisoformat(far["updated_at"])
now = datetime.now(timezone.utc)
ok("D2a updated_at = זמן הכתיבה (בטווח דקה מעכשיו), לא הרביעי של הנעילה",
   abs((now - stamp).total_seconds()) < 60 and far["updated_at"][:10] != far["week_wed"])
first = db.get_plan(D("2026-11-25"))
import time as _time
_time.sleep(0.05)       # two saves in the same clock tick got the same stamp (flaky ~1 in 6 runs)
second = db.save_plan(P(D("2026-11-25"), [M(g_mon), M(g_wk)]))
ok("D2b עריכה מאוחרת: updated_at גדל ו-created_at נשמר", second["updated_at"] > first["updated_at"]
   and second["created_at"] == first["created_at"])

# ── D3 — אסימון התנגשות ────────────────────────────────────────────────────────
base = db.save_plan(P(D("2026-12-02"), [M(g_mon)]), expected_updated_at="")       # חדשה: מצפה לשום נעילה
ok("D3a יצירה עם אסימון '' מצליחה כשאין נעילה חיה", base["week_wed"] == "2026-12-02")
step = db.save_plan(P(D("2026-12-02"), [M(g_mon), M(g_wk)]), expected_updated_at=base["updated_at"])
ok("D3b שמירה עם האסימון הנוכחי מצליחה ומחליפה אסימון", step["updated_at"] != base["updated_at"])
try:
    db.save_plan(P(D("2026-12-02"), [M(g_mon)]), expected_updated_at=base["updated_at"]); c1 = False
except db.PlanConflict:
    c1 = True
ok("D3c שמירה עם אסימון ישן ← PlanConflict, והנעילה לא נדרסה",
   c1 and [m["g"] for m in db.get_plan(D("2026-12-02"))["members"]] == [g_mon, g_wk])
try:
    db.save_plan(P(D("2026-12-02"), [M(g_mon)]), expected_updated_at=""); c2 = False
except db.PlanConflict:
    c2 = True
ok("D3d אסימון '' כשכבר יש נעילה חיה ← PlanConflict", c2)
db.delete_plan(D("2026-12-02"))
try:
    db.save_plan(P(D("2026-12-02"), [M(g_mon)]), expected_updated_at=step["updated_at"]); c3 = False
except db.PlanConflict:
    c3 = True
ok("D3e מי שטען נעילה שנמחקה בינתיים (במחשב אחר) ← PlanConflict", c3)
ok("D3f expected=None מדלג על הבדיקה", db.save_plan(P(D("2026-12-02"), [M(g_mon)]))["deleted"] == 0)

# ── D4 — live_plan_index: רק חיה, רק main, exclude_wed ─────────────────────────
for p in db.list_plans(include_deleted=True):
    db.delete_plan(p["week_wed"])
db.save_plan(P(W1, [M(g_mon), M(g_res, role="reserve")]))          # current
db.save_plan(P(W2, [M(g_mon), M(g_biw), M(g_one, kind="one")]))     # future
db.save_plan(P(D("2026-10-07"), [M(g_wk)]))                         # פגה (עבר + חלון)
db.save_plan(P(W4, [M(g_wk)]))
db.delete_plan(W4)                                                   # נמחקה
states = db.plan_states(TODAY)
ok("D4a מצבים נגזרים: W1 current · W2 future · 7/10 stale",
   states == {W1: "current", W2: "future", D("2026-10-07"): "stale"}, str(states))
idx = db.live_plan_index(TODAY)
ok("D4b האינדקס: רק main בנעילות חיות (רזרבה, פגה ונמחקה לא תופסות)",
   idx == {g_mon: [W1, W2], g_biw: [W2], g_one: [W2]}, str(idx))
ok("D4c exclude_wed מוציא נעילה של אותו שבוע",
   db.live_plan_index(TODAY, exclude_wed=W1) == {g_mon: [W2], g_biw: [W2], g_one: [W2]}
   and db.live_plan_index(TODAY, exclude_wed="2026-10-28") == {g_mon: [W1]})
ok("D4d גבול החלון: בשבת (wed+3) הנעילה עוד תופסת, בראשון (wed+4) פגה",
   g_mon in db.live_plan_index(D("2026-10-24")) and
   db.live_plan_index(D("2026-10-24")) == {g_mon: [W1, W2], g_biw: [W2], g_one: [W2]}
   and db.live_plan_index(D("2026-10-25")) == {g_mon: [W2], g_biw: [W2], g_one: [W2]})

# ── D5 — "בוצעה" נגזרת מהיסטוריה של חלוקה רגילה ────────────────────────────────
def state_of(wed, today=TODAY):
    return db.plan_states(today).get(wed)

ok("D5a לפני כל חלוקה: W1 current", state_of(W1) == "current")
b_wed = batch("2026-10-21", rids=[r_mon])
ok("D5b חלוקה רגילה ברביעי ← W1 בוצעה, ואינה תופסת עוד",
   state_of(W1) == "executed"
   and db.live_plan_index(TODAY) == {g_mon: [W2], g_biw: [W2], g_one: [W2]}, str(db.live_plan_index(TODAY)))
db.delete_batch(b_wed)
ok("D5c מחיקת האצווה מחזירה את הנעילה לחיים", state_of(W1) == "current"
   and g_mon in db.live_plan_index(TODAY))
b_sun = batch("2026-10-25", rids=[r_mon])
ok("D5d חלוקה רגילה ביום ראשון (25/10) שייכת ל-W2 ← W2 בוצעה", state_of(W2, D("2026-10-26")) == "executed")
db.delete_batch(b_sun)
b_thu = batch("2026-10-22", rids=[r_mon])
ok("D5e רישום באיחור בחמישי (22/10) שייך ל-W1 ולא ל-W2 (W2 הוא כבר הרביעי הקרוב, לא בוצע)",
   state_of(W1, D("2026-10-23")) == "executed" and state_of(W2, D("2026-10-23")) == "current")
db.delete_batch(b_thu)
b_bonus = batch("2026-10-21", holiday=holidays.BONUS, rids=[r_mon])
ok("D5f חלוקת בונוס לא מבצעת נעילה", state_of(W1) == "current")
b_hol = batch("2026-10-21", holiday="*", rids=[r_wk])
ok("D5g חלוקת חג לא מבצעת נעילה", state_of(W1) == "current")
db.delete_batch(b_bonus); db.delete_batch(b_hol)
b_far = batch("2026-11-25", rids=[r_wk])
ok("D5h חלוקה בשבוע אחר לא מבצעת את W1", state_of(W1) == "current" and state_of(W2) == "future")
db.delete_batch(b_far)
db.save_plan(P(W1, [M(g_mon)]))                                      # חזרה לבסיס (בלי הרזרבה)

# ── D7 — שכבת קריאה בלבד: אף כתיבה לנתוני המקבלים/החלוקות ────────────────────────
snap0 = snapshot()
db.save_plan(P(W5, [M(g_mon), M(g_biw)]))
db.save_plan(P(W5, [M(g_mon)], note="עריכה"))
db.live_plan_index(TODAY); db.plan_states(TODAY); db.list_plans()
db.tag_planned([dict(db.get_recipient(r_mon))], W2, TODAY)
db.delete_plan(W5)
ok("D7 צילום recipients/distributions/dist_batches זהה אחרי יצירה/עריכה/קריאה/מחיקה (גם last/next_distribution)",
   snapshot() == snap0)

# ── D9 — התפיסה נקראת חי מהכרטיסים ─────────────────────────────────────────────
for p in db.list_plans():                                  # מנקים נעילות של הסעיפים הקודמים
    db.delete_plan(p["week_wed"])
db.save_plan(P(W1, [M(g_mon), M(g_biw), M(g_wk)]))
def tagged_for(wed, rid):
    row = dict(db.get_recipient(rid))
    return db.tag_planned([row], wed, TODAY)[0].get("planned_elsewhere")

ok("D9a חודשי נעול ב-W1: מסומן ב-W2 (d=7), לא ב-W5 (d=28), ולא ב-W1 עצמו",
   tagged_for(W2, r_mon) == "2026-10-21" and tagged_for(W5, r_mon) is None and tagged_for(W1, r_mon) is None)
db.update_recipient(r_mon, {"frequency": "שבועי"})
ok("D9b תדירות שהשתנתה אחרי הנעילה משפיעה מיד: שבועי כבר לא תפוס", tagged_for(W2, r_mon) is None)
db.update_recipient(r_mon, {"frequency": "חודשי"})
ok("D9c ובחזרה לחודשי — תפוס שוב", tagged_for(W2, r_mon) == "2026-10-21")
ok("D9d דו-שבועי: תפוס ב-W2 (d=7), חופשי ב-W3 (d=14)", tagged_for(W2, r_biw) == "2026-10-21"
   and tagged_for(W3, r_biw) is None)
ok("D9e שבועי לעולם לא תפוס", tagged_for(W2, r_wk) is None and tagged_for(W3, r_wk) is None)
r_gone, g_gone = mk("ימחק", "חודשי")
db.save_plan(P(W1, [M(g_mon), M(g_gone)]))
db.delete_recipient(r_gone)
ok("D9f כרטיס שנמחק אחרי הנעילה: אין שורה ← אין השפעה, וכלום לא קורס",
   db.tag_planned([dict(db.get_recipient(r_mon))], W2, TODAY)[0].get("planned_elsewhere") == "2026-10-21"
   and g_gone in db.live_plan_index(TODAY))
ok("D9g חד-פעמי main: תפוס ב-W2 (הפסקה ברירת מחדל 4), חופשי אחרי 4 שבועות",
   (db.save_plan(P(W1, [M(g_mon), M(g_one, kind="one")])), tagged_for(W2, r_one) == "2026-10-21"
    and tagged_for(W4, r_one) == "2026-10-21" and tagged_for(W5, r_one) is None)[1])
ok("D9h רזרבה לא תופסת", (db.save_plan(P(W1, [M(g_mon), M(g_res, role="reserve")])),
                         tagged_for(W2, r_res) is None)[1])

# ═══ S3 — השער בחמש הרשימות ═══════════════════════════════════════════════════
# הרשימות קוראות את השעון האמיתי (מצב נעילה נגזר מ"היום"), לכן כאן התאריכים יחסיים להיום.
for p in db.list_plans():
    db.delete_plan(p["week_wed"])
real_today = date.today()
Wa = selection.upcoming_wednesday(real_today)
Wb = Wa + timedelta(days=7)
Wc = Wa + timedelta(days=14)
Wfar = Wb + timedelta(days=28)
old = (real_today - timedelta(days=120)).isoformat()
sm_id, sm_g = mk("ס-חודשי", "חודשי", last_distribution=old, souls=4, children_total=4)
sb_id, sb_g = mk("ס-דו", "דו-שבועי", last_distribution=old, souls=4, children_total=4)
sw_id, sw_g = mk("ס-שבועי", "שבועי", last_distribution=old, souls=4, children_total=4)
so_id, so_g = mk("ס-חדפ", "חד-פעמי", souls=4, children_total=4)
S_IDS = {sm_id, sb_id, sw_id, so_id}
CRIT = {"balance_communities": False}

def lists(wed):
    """מי מבין S_IDS מופיע בכל אחת מהרשימות לשבוע wed."""
    out = {
        "weekly": db.get_weekly_list(on_date=wed),
        "regulars_scored": db.get_regulars_scored(on_date=wed),
        "scored_all": db.get_scored_all(on_date=wed),
        "filtered": db.get_filtered_list(dict(CRIT), on_date=wed),
        "one_time": [r for r in db.get_one_time_list(on_date=wed) if r.get("in_distribution")],
    }
    return {k: {r["id"] for r in v} & S_IDS for k, v in out.items()}, out

base_sets, base_rows = lists(Wb)
ok("D6a בלי נעילות: חודשי/דו/שבועי/חד-פעמי מופיעים בכל הרשימות הרלוונטיות",
   base_sets["weekly"] == {sm_id, sb_id, sw_id} and base_sets["regulars_scored"] == {sm_id, sb_id, sw_id}
   and base_sets["scored_all"] == S_IDS and S_IDS <= base_sets["filtered"] and base_sets["one_time"] == {so_id},
   str(base_sets))
ok("D6b בלי נעילות אף שורה לא מקבלת מפתח planned_elsewhere (הרשימות זהות לגרסה הקודמת)",
   not any("planned_elsewhere" in r for v in base_rows.values() for r in v))
# נעילות שלא אמורות להשפיע: נמחקה, רזרבה בלבד, פגה, בוצעה, ושל אותו שבוע עצמו
db.save_plan(P(Wc, [M(sm_g)])); db.delete_plan(Wc)
db.save_plan(P(Wc, [M(sm_g, role="reserve"), M(sb_g, role="reserve")]))
db.save_plan(P(Wa - timedelta(days=35), [M(sm_g), M(sb_g), M(so_g)]))             # פגה
weak_sets, weak_rows = lists(Wb)
ok("D6c נעילה שנמחקה / רזרבה בלבד / פגה — הרשימות זהות בדיוק (שורות מלאות, לא רק מי נכנס)",
   weak_sets == base_sets and all(
       [(r["id"], r.get("need_score"), r.get("days_since")) for r in weak_rows[k]]
       == [(r["id"], r.get("need_score"), r.get("days_since")) for r in base_rows[k]] for k in base_rows)
   and not any("planned_elsewhere" in r for v in weak_rows.values() for r in v))
for p in db.list_plans():
    db.delete_plan(p["week_wed"])

# נעילה חיה של Wb עם כולם כ-main
db.save_plan(P(Wb, [M(sm_g), M(sb_g), M(sw_g), M(so_g, kind="one")]))
a_sets, a_rows = lists(Wa)                   # שבוע לפני הנעילה (סימטרי)
ok("D6d נעילה ב-Wb חוסמת את Wa בכל חמש הרשימות: רק השבועי נשאר",
   a_sets["weekly"] == {sw_id} and a_sets["regulars_scored"] == {sw_id} and a_sets["scored_all"] == {sw_id}
   and a_sets["filtered"] & S_IDS == {sw_id} and a_sets["one_time"] == set(), str(a_sets))
b_sets, _ = lists(Wb)
ok("D6e בשבוע של הנעילה עצמה אף אחד לא נחסם", b_sets == base_sets, str(b_sets))
f_sets, _ = lists(Wfar)
ok("D6f ארבעה שבועות אחרי הנעילה (Wfar): החודשי והחד-פעמי חופשיים, הדו-שבועי חופשי",
   {sm_id, sb_id, sw_id} <= f_sets["weekly"], str(f_sets))
ok("D6g חד-פעמי חסום מסומן _planned (לא _cooldown) ונשאר ברשימה אחרי המועמדים",
   (lambda r: r is not None and r.get("_planned") and not r.get("_cooldown") and not r["in_distribution"])(
       next((x for x in db.get_one_time_list(on_date=Wa) if x["id"] == so_id), None)))
n_b, regs_b = db.compute_suggested_n(50, on_date=Wb)
n_a, regs_a = db.compute_suggested_n(50, on_date=Wa)
ok("D6h compute_suggested_n יורש את הסינון: ב-Wa חסרים הקבועים הנעולים (חודשי + דו-שבועי; לא השבועי)", regs_b - regs_a == 2,
   f"{regs_b} -> {regs_a}")
db.update_recipient(sm_id, {"holiday_support": 1})
hol = db.get_filtered_list({"balance_communities": False, "holiday": "*"}, on_date=Wa)
reg = db.get_filtered_list(dict(CRIT), on_date=Wa)
ok("D6i חלוקת חג מדלגת על השער: החודשי הנעול נכנס לחג (נתמך חגים), אבל לא לחלוקה רגילה",
   sm_id in {r["id"] for r in hol} and sm_id not in {r["id"] for r in reg}, str({r["id"] for r in hol}))
rowm = dict(db.get_recipient(sm_id))
db.tag_planned([rowm], Wa)
ok("D6j not_due_reason (החלון 'מקבל שלא בתור') מסביר: 'נעול ברשימה של DD/MM'",
   selection.not_due_reason(rowm, Wa, 4) == "נעול ברשימה של " + Wb.strftime("%d/%m"),
   selection.not_due_reason(rowm, Wa, 4))

# ── D8 — תחזית לשבוע לא-אמיתי לא כותבת next_distribution, גם כשיש נעילות ────────
with db.get_connection() as c:
    nd0 = {r["id"]: r["next_distribution"] for r in c.execute("SELECT id, next_distribution FROM recipients")}
db.get_weekly_list(on_date=Wfar); db.get_weekly_list(on_date=Wb + timedelta(days=21))
with db.get_connection() as c:
    nd1 = {r["id"]: r["next_distribution"] for r in c.execute("SELECT id, next_distribution FROM recipients")}
ok("D8 רשימה לשבוע לא-אמיתי (עם נעילות) לא כותבת next_distribution", nd0 == nd1)

# ── D12 — אפס נתונים: הנעילות נשארות ונשארות יתומות (אין תפיסה) ────────────────
ok("D12a לפני האיפוס יש נעילה חיה", db.get_plan(Wb) is not None and sm_g in db.live_plan_index())
db.reset_all_data()
ok("D12b אחרי reset_all_data הנעילה עדיין בהגדרות", db.get_plan(Wb) is not None)
n_id, n_g = mk("חדש-חודשי", "חודשי", last_distribution=old)
ok("D12c כרטיס חדש (guid חדש) לא נתפס על ידי נעילה יתומה, והרשימות עובדות",
   n_id in {r["id"] for r in db.get_weekly_list(on_date=Wa)}
   and not any("planned_elsewhere" in r for r in db.get_weekly_list(on_date=Wa)))

# ── סיום ──────────────────────────────────────────────────────────────────────
print()
print("RESULT:", "ALL PLAN-DATA TESTS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

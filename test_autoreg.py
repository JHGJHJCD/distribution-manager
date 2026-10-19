# -*- coding: utf-8 -*-
"""כלל 11 — רישום אוטומטי של רשימה נעולה: שכבת הנתונים (docs/plans/הכנה_קדימה_נעילה.md נספח ב׳).

מוכיח:
  • החלון: לא לפני חמישי 06:00, כן עד סוף שבת, לא ביום ראשון
  • נרשם: כל חברי main הפעילים כ-received=1 בתאריך הרביעי, רזרבה/נמחק/מושהה מדולגים ונספרים
  • לא פעמיים — גם אחרי תיקון (מחיקת האצווה); לא כשיש אצווה רגילה; לא כשהמתג כבוי
  • בונוס/חג לא נחשבים "רישום אמיתי"
  • last/next זהים לרישום ידני זהה; כתיבה רק דרך bulk_add_distributions
  • שני מחשבים שרצים יחד ← אצווה אחת (guid דטרמיניסטי)
  • מחיקת אצווה אוטומטית (תיקון) מחשבת תאריכים; נעילה שנוצרה מחדש מתחילה נקייה

תמיד DB זמני — לעולם לא %APPDATA%. הרצה: python test_autoreg.py  (Python 3.12)"""
import os, sys, tempfile, json
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")
import datetime as _dtm
from datetime import date, datetime, timedelta

import database as db
import selection
import holidays
from utils import sync

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


_Real = _dtm.date
class _Fake(_Real):
    _today = _Real(2026, 10, 22)                       # חמישי — אחרי רביעי 21/10
    @classmethod
    def today(cls):
        t = cls._today
        return _Real(t.year, t.month, t.day)
db.date = _Fake; selection._date = _Fake

D = date.fromisoformat
W1, W2, W3 = D("2026-10-21"), D("2026-10-28"), D("2026-11-04")
WED_EVE = datetime(2026, 10, 21, 23, 59)
THU_0559, THU_0600 = datetime(2026, 10, 22, 5, 59), datetime(2026, 10, 22, 6, 0)
SAT_2359, SUN_0000 = datetime(2026, 10, 24, 23, 59), datetime(2026, 10, 25, 0, 0)

root = tempfile.mkdtemp(prefix="autoreg_")
_n = [0]


def fresh(label=None):
    """DB זמני חדש (ריק) — מחזיר את תיקייתו."""
    _n[0] += 1
    d = os.path.join(root, label or f"db{_n[0]}")
    os.makedirs(d, exist_ok=True)
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")
    db.init_db()
    return d


def use(d):
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")


def snapshot():
    with db.get_connection() as c:
        return {t: [dict(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY id")]
                for t in ("recipients", "distributions", "dist_batches")}


def batches():
    return db.get_distribution_batches()


def mk(name, freq, phone, **kw):
    rid = db.add_recipient({"full_name": name, "phone1": phone, "status": "פעיל", "frequency": freq,
                            "priority": 4 if freq != "חד-פעמי" else 3, "souls": 3, "area": "צפון", **kw})
    return rid, db.get_recipient(rid)["guid"]


def M(g, role="main", kind="reg", note="", n=""):
    return {"g": g, "role": role, "kind": kind, "note": note, "n": n}


NAMES = (("שבועי א", "שבועי"), ("שבועי ב", "שבועי"), ("חודשי", "חודשי"), ("דו שבועי", "דו-שבועי"),
         ("חד פעמי", "חד-פעמי"), ("רזרבה", "שבועי"), ("מושהה", "שבועי"), ("נמחק", "שבועי"))


def people_in_current_db():
    return {nm: mk(nm, fr, f"05000000{i:02d}") for i, (nm, fr) in enumerate(NAMES)}


def lock(people, wed=W1, **kw):
    mem = [M(people["שבועי א"][1], note="הערה א"), M(people["שבועי ב"][1]),
           M(people["חודשי"][1]), M(people["דו שבועי"][1]),
           M(people["חד פעמי"][1], kind="one"),
           M(people["רזרבה"][1], role="reserve"),
           M(people["מושהה"][1]), M(people["נמחק"][1])]
    return db.save_plan({"week_wed": wed.isoformat(), "members": mem, "products": 7, "reserve": 1, **kw},
                        expected_updated_at="")


def rec_one(people, nm, **kw):
    return {"id": people[nm][0], "full_name": nm, "area": "", "souls": 1, **kw}


def dates_of(people):
    out = {}
    for nm, (rid, _g) in people.items():
        r = db.get_recipient(rid)
        if r:
            out[nm] = (r["last_distribution"] or "", r["next_distribution"] or "")
    return out


# ═══ A1 — החלון (פונקציה טהורה) ═════════════════════════════════════════════════
w = selection.auto_register_window_open
ok("A1a רביעי בערב — עדיין לא", not w(W1, WED_EVE))
ok("A1b חמישי 05:59 — לא", not w(W1, THU_0559))
ok("A1c חמישי 06:00 — כן", w(W1, THU_0600))
ok("A1d שבת 23:59 — כן (סוף חלון הרישום)", w(W1, SAT_2359))
ok("A1e ראשון 00:00 — לא (פגה)", not w(W1, SUN_0000))
ok("A1f שבוע אחר: חמישי של W1 לא פותח את W2", not w(W2, THU_0600))
ok("A1g גבול שנה: רביעי 30/12/2026 ← חמישי 31/12 06:00 כן, ראשון 3/1 לא",
   w(D("2026-12-30"), datetime(2026, 12, 31, 6, 0)) and not w(D("2026-12-30"), datetime(2027, 1, 3, 0, 0)))

# ═══ A2–A5 — מחשב אחד, מסלול מלא ═════════════════════════════════════════════════
dir_main = fresh("main")
people = people_in_current_db()
plan = lock(people, distributor="מחלק הנעילה", name="חלוקה מיוחדת")
st0 = db.get_autoreg(plan)
ok("A2a ברירת מחדל: המתג דלוק, עוד לא נרשם", st0["enabled"] and st0["registered"] is None)
ok("A2b המפתח הנפרד לא נוצר סתם", db.get_setting(db.AUTOREG_PREFIX + W1.isoformat()) == "")
ok("A2c הנעילה שומרת מחלק", db.get_plan(W1)["distributor"] == "מחלק הנעילה")

# מושהה / נמחק אחרי הנעילה
db.update_recipient(people["מושהה"][0], {"status": "מושהה"})
with db.get_connection() as c:
    c.execute("DELETE FROM recipients WHERE id=?", (people["נמחק"][0],))

before = snapshot()
ok("A3a לפני החלון (חמישי 05:59): שום רישום", db.auto_register_due_plans(THU_0559) == [] and snapshot() == before)
ok("A3b רביעי בערב: שום רישום", db.auto_register_due_plans(WED_EVE) == [] and snapshot() == before)

res = db.auto_register_due_plans(THU_0600)
bs = batches()
ok("A4a נרשמה אצווה אחת", len(res) == 1 and res[0]["status"] == "registered" and len(bs) == 1, str(res))
b = bs[0] if bs else {}
rows = db.get_batch_recipients(b["id"]) if b else []
names = {r["recipient_name"]: r for r in rows}
ok("A4b התאריך = רביעי הנעילה", b.get("dist_date") == W1.isoformat())
ok("A4c חמישה main פעילים נרשמו כקיבלו (שבועי א/ב, חודשי, דו-שבועי, חד-פעמי)",
   set(names) == {"שבועי א", "שבועי ב", "חודשי", "דו שבועי", "חד פעמי"}
   and all(r["received"] == 1 for r in rows), str(sorted(names)))
ok("A4d אין שורות 'לא הגיע' (אין מידע)", not any(r["received"] == 0 for r in rows))
ok("A4e רזרבה לא נרשמה; מושהה ונמחק מדולגים", "רזרבה" not in names and "מושהה" not in names and "נמחק" not in names)
ok("A4f הדיווח סופר: רזרבה 1, מושהה 1, נמחק (לא נמצא) 1, נרשמו 5",
   (res[0]["reserve"], res[0]["inactive"], res[0]["missing"], res[0]["n"]) == (1, 1, 1, 5), str(res[0]))
ok("A4g שם = שם הנעילה, מחלק = מחלק הנעילה", b.get("dist_name") == "חלוקה מיוחדת" and b.get("distributor") == "מחלק הנעילה")
ok("A4h ההערה הכללית מתחילה ב-'נרשם אוטומטית מרשימה נעולה' והאצווה מזוהה כאוטומטית",
   (b.get("general_note") or "").startswith(db.AUTO_NOTE) and db.is_auto_batch(b))
ok("A4i הערת השורה מהנעילה עברה", names["שבועי א"]["notes"] == "הערה א")
ok("A4j חלוקה רגילה (holiday ריק) ולכן הנעילה נחשבת 'בוצעה'",
   (b.get("holiday") or "") == "" and db.plan_states(THU_0600.date()).get(W1) == "executed")
ok("A4k סימון נרשם: מפתח נפרד, עם guid האצווה, והנעילה עצמה לא נגעה",
   db.get_autoreg(db.get_plan(W1))["registered"]["batch_guid"] == b.get("guid")
   and db.get_plan(W1)["updated_at"] == plan["updated_at"])
ok("A4l נשמר גיבוי safety לפני הרישום",
   os.path.isdir(db.BACKUP_DIR) and any(f.startswith("safety_") for f in os.listdir(db.BACKUP_DIR)))
ok("A4m הבאנר: הרישום ממתין לבדיקה (לא אושר), עם הספירה",
   [(x["week_wed"], x["n"]) for x in db.auto_registrations_to_review(THU_0600.date())] == [(W1, 5)])
ok("A4n find_auto_batch מוצא לפי תאריך החלוקה", (db.find_auto_batch(W1.isoformat()) or {}).get("id") == b["id"]
   and db.find_auto_batch((W1 + timedelta(days=1)).isoformat()) is not None)

snap = snapshot()
ok("A5a קריאה שנייה (אותה דקה ואחר כך): כלום", db.auto_register_due_plans(THU_0600) == []
   and db.auto_register_due_plans(SAT_2359) == [] and snapshot() == snap)
ok("A5b delete_auto_batch מוחק את האצווה האוטומטית", db.delete_auto_batch(b["id"]) and not batches())
ok("A5c אחרי המחיקה הנעילה חיה שוב (current) — נכשל פתוח", db.plan_states(THU_0600.date()).get(W1) == "current")
ok("A5d ...אבל לא נרשמת שוב (הסימון שרד)", db.auto_register_due_plans(THU_0600) == [] and not batches())
ok("A5e הבאנר נעלם כשהאצווה נמחקה", db.auto_registrations_to_review(THU_0600.date()) == [])
ok("A5f last/next של מי שנרשם חזרו לריק", dates_of(people)["שבועי א"][0] == "")
manual = db.bulk_add_distributions([{"id": people["חודשי"][0], "full_name": "חודשי", "area": "", "souls": 3}],
                                   W1.isoformat(), "", 0, "רון", dist_name="ידני")
ok("A5g delete_auto_batch מסרב לאצווה רגילה", db.delete_auto_batch(manual) is False and len(batches()) == 1)

# ═══ A6 — מקבל סימון 'הכול נכון' ════════════════════════════════════════════════════
fresh(); pe = people_in_current_db(); lock(pe)
db.auto_register_due_plans(THU_0600)
rv = db.auto_registrations_to_review(THU_0600.date())
ok("A6a ממתין לבדיקה", len(rv) == 1)
db.mark_autoreg_reviewed(W1)
ok("A6b 'הכול נכון' מסתיר את הבאנר; האצווה נשארת", db.auto_registrations_to_review(THU_0600.date()) == [] and len(batches()) == 1)
_doc = json.loads(db.get_setting(db.AUTOREG_PREFIX + W1.isoformat())); _doc["reviewed_at"] = ""
db.set_setting(db.AUTOREG_PREFIX + W1.isoformat(), json.dumps(_doc))
ok("A6c באנר לא מוצג אחרי 21 יום גם בלי אישור",
   db.auto_registrations_to_review(THU_0600.date()) != [] and db.auto_registrations_to_review(W1 + timedelta(days=22)) == [])

# ═══ A7 — אצווה רגילה / בונוס / חג / מתג ═════════════════════════════════════════════
fresh(); pe = people_in_current_db(); lock(pe)
db.bulk_add_distributions([rec_one(pe, "שבועי א")], W1.isoformat(), "", 0, "רון", dist_name="בונוס", holiday=holidays.BONUS)
r7 = db.auto_register_due_plans(THU_0600)
ok("A7a חלוקת בונוס באותו שבוע לא נחשבת רישום אמיתי — הרישום האוטומטי כן קורה", len(r7) == 1 and len(batches()) == 2, str(r7))

fresh(); pe = people_in_current_db(); lock(pe)
db.bulk_add_distributions([rec_one(pe, "שבועי א")], W1.isoformat(), "", 0, "רון", dist_name="חג", holiday="*")
ok("A7b חלוקת חג באותו שבוע גם היא לא חוסמת", len(db.auto_register_due_plans(THU_0600)) == 1)

fresh(); pe = people_in_current_db(); lock(pe)
db.bulk_add_distributions([rec_one(pe, "שבועי א")], (W1 + timedelta(days=1)).isoformat(), "", 0, "רון", dist_name="ידני חמישי")
ok("A7c רישום רגיל אמיתי ביום חמישי (שייך לרביעי שלפניו) ← אין רישום אוטומטי",
   db.auto_register_due_plans(THU_0600) == [] and len(batches()) == 1)

fresh(); pe = people_in_current_db(); pl = lock(pe)
db.set_autoreg_enabled(pl, False)
ok("A7d מתג כבוי ← אין רישום", db.auto_register_due_plans(THU_0600) == [] and not batches()
   and db.get_autoreg(db.get_plan(W1))["enabled"] is False)
ok("A7e הנעילה לא נגעה במתג (updated_at זהה)", db.get_plan(W1)["updated_at"] == pl["updated_at"])
db.set_autoreg_enabled(db.get_plan(W1), True)
ok("A7f מתג דלוק שוב ← נרשמת", len(db.auto_register_due_plans(THU_0600)) == 1)

fresh(); pe = people_in_current_db(); lock(pe)
ok("A7g שבת 23:59 — עדיין נרשמת", len(db.auto_register_due_plans(SAT_2359)) == 1)
fresh(); pe = people_in_current_db(); lock(pe)
ok("A7h ראשון 00:00 — פגה, לא נרשמת (נכשל פתוח)", db.auto_register_due_plans(SUN_0000) == [] and not batches())

fresh(); pe = people_in_current_db(); lock(pe, W3)
ok("A7i נעילה לשבוע עתידי (תחזית) לא נרשמת", db.auto_register_due_plans(THU_0600) == [] and not batches())

fresh(); pe = people_in_current_db(); lock(pe)
db.delete_plan(W1)
ok("A7j נעילה שבוטלה לא נרשמת", db.auto_register_due_plans(THU_0600) == [] and not batches())

fresh(); pe = people_in_current_db()
db.save_plan({"week_wed": W1.isoformat(), "members": [M(pe["רזרבה"][1], role="reserve")], "products": 1}, expected_updated_at="")
ok("A7k נעילה בלי אף main פעיל ← אין מה לרשום, לא נוצרת אצווה ריקה", db.auto_register_due_plans(THU_0600) == [] and not batches())

# ═══ A8 — last/next זהים לרישום ידני זהה ═════════════════════════════════════════════
fresh(); pa = people_in_current_db(); lock(pa)
db.auto_register_due_plans(THU_0600)
auto_dates = dates_of(pa)
fresh(); pm = people_in_current_db()
recs = [{"id": pm[nm][0], "full_name": nm, "area": "צפון", "souls": 3, "notes": ""}
        for nm in ("שבועי א", "שבועי ב", "חודשי", "דו שבועי", "חד פעמי")]
db.bulk_add_distributions(recs, W1.isoformat(), "", 0, "רון", dist_name="ידני")
five = ("שבועי א", "שבועי ב", "חודשי", "דו שבועי", "חד פעמי", "רזרבה")
ok("A8a last/next אחרי הרישום האוטומטי = אחרי רישום ידני של אותם אנשים באותו תאריך",
   {k: auto_dates[k] for k in five} == {k: dates_of(pm)[k] for k in five}, f"{auto_dates} / {dates_of(pm)}")
ok("A8b ודוגמה: חודשי ← 18/11 (28 יום), דו-שבועי ← 4/11, שבועי ← 28/10",
   (auto_dates["חודשי"][1], auto_dates["דו שבועי"][1], auto_dates["שבועי א"][1]) == ("2026-11-18", "2026-11-04", "2026-10-28"),
   str((auto_dates["חודשי"], auto_dates["דו שבועי"], auto_dates["שבועי א"])))

# ═══ A9 — כתיבה רק לטבלאות החלוקות; מקבלים משתנים רק ב-last/next/weekly_status ═══════════
fresh(); pe = people_in_current_db(); lock(pe)
s0 = snapshot()
db.auto_register_due_plans(THU_0600)
s1 = snapshot()
changed_cols = set()
for a, bb in zip(s0["recipients"], s1["recipients"]):
    for k in a:
        if a[k] != bb[k]:
            changed_cols.add(k)
ok("A9 ברשומות המקבלים השתנו רק last/next (נגזרים) ו-weekly_status — כמו רישום ידני",
   changed_cols <= {"last_distribution", "next_distribution", "weekly_status"}, str(changed_cols))

# ═══ A10 — בחירות השבוע: מי שנרשם יוצא מ-weekly_extra_ids ורק הוא ═══════════════════════
fresh(); pe = people_in_current_db(); lock(pe)
other = mk("אחר", "חד-פעמי", "0509999999")
db.set_setting("weekly_extra_ids", ",".join([pe["חד פעמי"][1], other[1], str(pe["שבועי ב"][0])]))
db.set_setting("weekly_reserve_ids", pe["רזרבה"][1])
db.auto_register_due_plans(THU_0600)
left = [t for t in db.get_setting("weekly_extra_ids").split(",") if t]
ok("A10a מי שנרשם (חד-פעמי + שבועי ב לפי מספר מקומי) הוסר מהבחירות; 'אחר' נשאר", left == [other[1]], str(left))
ok("A10b רשימת הרזרבה לא נגעה", db.get_setting("weekly_reserve_ids") == pe["רזרבה"][1])

# ═══ A11 — נעילה שנוצרה מחדש מתחילה נקייה, וה-guid שונה ═════════════════════════════════
fresh(); pe = people_in_current_db(); p1 = lock(pe)
db.auto_register_due_plans(THU_0600)
g1 = batches()[0]["guid"]
db.delete_auto_batch(batches()[0]["id"])
db.delete_plan(W1)
import time as _t; _t.sleep(0.01)
p2 = lock(pe)
ok("A11a נעילה חדשה לאותו רביעי: created_at שונה, הסימון הישן לא חל", p2["created_at"] != p1["created_at"]
   and db.get_autoreg(p2)["registered"] is None and db.get_autoreg(p2)["enabled"])
r = db.auto_register_due_plans(THU_0600)
ok("A11b והיא נרשמת עם guid אחר (אין התנגשות batch_delete/batch_add באותו guid)",
   len(r) == 1 and batches()[0]["guid"] != g1)

# ═══ A12 — ריפוי: אצווה עם ה-guid הנגזר קיימת אבל הסימון חסר ═══════════════════════════
fresh(); pe = people_in_current_db(); pl = lock(pe)
db.auto_register_due_plans(THU_0600)
db.set_setting(db.AUTOREG_PREFIX + W1.isoformat(), "")            # הסימון אבד
ok("A12a בלי סימון אבל האצווה קיימת — הנעילה 'בוצעה' ולכן שום דבר לא נרשם שוב",
   db.get_autoreg(pl)["registered"] is None and db.plan_states(THU_0600.date()).get(W1) == "executed")
r12 = db.auto_register_plan(W1, THU_0600)
ok("A12b auto_register_plan מרפא את הסימון בלי ליצור אצווה נוספת",
   r12["status"] == "healed" and len(batches()) == 1 and db.get_autoreg(pl)["registered"] is not None, str(r12))
ok("A12c ובקריאה הבאה — כלום", db.auto_register_due_plans(THU_0600) == [] and len(batches()) == 1)

# ═══ A13 — שני מחשבים שרצים יחד ← אצווה אחת ════════════════════════════════════════════
root2 = tempfile.mkdtemp(prefix="autoreg_sync_")
da, dbb = os.path.join(root2, "a"), os.path.join(root2, "b")
shared = os.path.join(root2, "drive")
for p in (da, dbb, shared):
    os.makedirs(p)
use(da); db.init_db()
pa2 = people_in_current_db()
sync.enable_sync(shared, seed=True)
use(dbb); db.init_db(); sync.enable_sync(shared, seed=True); sync.run_sync()
lock_g = pa2                                                      # אותם guid בשני המחשבים
use(da); lock(pa2, distributor="רון"); sync.run_sync()
use(dbb); sync.run_sync()
ok("A13a B קיבל את הנעילה ואת אותם guid", db.get_plan(W1) is not None
   and db.get_recipient_by_guid(pa2["שבועי א"][1]) is not None)
use(da); ra = db.auto_register_due_plans(THU_0600)                # שניהם רצים באותה דקה, לפני שהסנכרון הגיע
use(dbb); rb = db.auto_register_due_plans(THU_0600)
ga = (use(da), batches()[0]["guid"])[1]
gb = (use(dbb), batches()[0]["guid"])[1]
ok("A13b שניהם יצרו את אותה אצווה (guid דטרמיניסטי)", len(ra) == 1 and len(rb) == 1 and ga == gb, f"{ga} / {gb}")
rows_a = sorted((r["recipient_name"], r["guid"]) for r in (use(da), db.get_batch_recipients(batches()[0]["id"]))[1])
rows_b = sorted((r["recipient_name"], r["guid"]) for r in (use(dbb), db.get_batch_recipients(batches()[0]["id"]))[1])
ok("A13c ואותם guid לשורות", rows_a == rows_b and len(rows_a) == 7)
for n in (da, dbb, da, dbb):
    use(n); sync.run_sync()
use(da); na = (len(batches()), len(db.get_distributions()))
use(dbb); nb = (len(batches()), len(db.get_distributions()))
ok("A13d אחרי סנכרון הדדי: אצווה אחת ו-7 שורות בכל מחשב (בלי כפילות)", na == (1, 7) == nb, f"{na} / {nb}")
use(da); da_dates = dates_of(pa2)
use(dbb); db_dates = dates_of(pa2)
ok("A13e וה-last/next זהים בשני המחשבים", da_dates == db_dates)
ok("A13f הסימון הגיע לשני המחשבים", (use(da), db.get_autoreg(db.get_plan(W1))["registered"]["batch_guid"])[1] == ga
   and (use(dbb), db.get_autoreg(db.get_plan(W1))["registered"]["batch_guid"])[1] == ga)

# מחשב שלישי שרץ אחרי שהסנכרון הגיע — לא נרשם שוב ('בוצעה')
use(dbb); ok("A13g מחשב שנפתח אחרי שהאצווה הגיעה לא רושם שוב", db.auto_register_due_plans(THU_0600) == [])

print()
print("FAILED:" if fails else "ALL OK", *fails)
sys.exit(1 if fails else 0)

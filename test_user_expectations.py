# -*- coding: utf-8 -*-
"""בדיקות קבלה — "מה שיהודה מצפה לראות" (21/10/2026).

בדיקה זו שונה מהאחרות: היא לא בודקת "הקוד עושה מה שנכתב בו" אלא "אם הגדרתי X — רואים Y",
דרך המסך עצמו (כמו שהמפעיל עובד), בנוסח הציפייה של יהודה. אחרי באג הרזרבה (שבו בדיקה קיימת
אכפה בדיוק את ההתנהגות השגויה) — כל כלל מרכזי מקבל כאן ציפייה בלשון המשתמש.
כשנכשלת בדיקה כאן: לפני ש"מתקנים את הבדיקה" שואלים את יהודה אם הציפייה עדיין נכונה.

  E1  רזרבה: הגדרתי N — רואים N, בכל מצב, גם כשמוסיפים חד-פעמיים אחרי הקבועים
  E2  הרשימה לעולם לא ארוכה ממספר המוצרים; מוצרים 0 = טבלה ריקה
  E3  מי שמחכה הכי הרבה זמן נכנס ראשון כשחסרים מוצרים
  E4  קבוע שתורו לא הגיע — לא ברשימה ולא ברזרבה
  E5  מי שקיבל נעלם מהרשימה; מי שלא סומן נרשם "לא הגיע" (ונשאר); רזרבה לא נרשמת בכלל
  E6  חד-פעמי שקיבל לא חוזר (גם לא כרזרבה) עד שעוברות 4 שבועות
  E7  🗑 מוריד מהרשימה בלי לרשום "לא הגיע", והבא בתור נכנס
  E8  מושהה לא מופיע בשום מקום
  E9  צינתוקים/מיילים/"בחר הכל" לא נוגעים ברזרבה
  E10 נעילה: מה שרואים נשמר (כולל רזרבה); נעול בשבוע אחד לא נכנס לשבוע סמוך; רזרבה לא תופסת
  E11 תחזית לא נוגעת בשבוע האמיתי
הרצה: python test_user_expectations.py  (Python 3.12)"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date, timedelta
import database as db
import selection
_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups"); db.init_db()

from PyQt6.QtWidgets import QApplication, QMessageBox
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

import tabs.group_update as gu
gu.export_full_distribution_to_excel = lambda *a, **k: None       # לא כותבים קבצים בבדיקה
gu.reveal_in_folder = lambda *a, **k: None
from main import MainWindow
win = MainWindow()
gt = win.group_tab

today = date.today()
WED = selection.upcoming_wednesday(today)

def fresh():
    """DB נקי, מצב רגיל, הגדרות נקיות."""
    db.reset_all_data()
    for k in ("available_products", "reserve_count", "weekly_extra_ids", "weekly_reserve_ids"):
        db.set_setting(k, "")
    db.set_setting("dist_regulars_mode", "schedule")
    db.set_setting("last_distributor", "מחלק בדיקה")
    db.set_filter_criteria({"children_total": {"min": 1, "max": None}, "balance_communities": False})
    gt._extra_ids.clear(); gt._reserve_ids.clear(); gt._removed_ids.clear(); gt._checked_ids.clear()
    gt._plan = None

def regs(n, prefix="קבוע", freq="שבועי", last_days_ago=None, start=0):
    """n קבועים שתורם הגיע (אלא אם ביקשו אחרת); i גדול = מחכה יותר זמן."""
    out = []
    for i in range(start, start + n):
        ago = last_days_ago if last_days_ago is not None else 14 + i
        out.append(db.add_recipient({
            "full_name": f"{prefix} {i}", "status": "פעיל", "frequency": freq, "priority": 4,
            "souls": 3, "children_total": 3, "representative": "א" if i % 2 else "ב",
            "last_distribution": (today - timedelta(days=ago)).isoformat()}))
    return out

def ones(n, prefix="חדפ"):
    return [db.add_recipient({"full_name": f"{prefix} {i}", "status": "פעיל", "frequency": "חד-פעמי",
                              "priority": 3 if i % 2 else 2, "souls": 3 + i % 5}) for i in range(n)]

def screen(mode="schedule", products=0, reserve=0):
    db.set_setting("dist_regulars_mode", mode)
    gt.refresh()
    gt.reserve_spin.setValue(reserve); gt.products_spin.setValue(products)
    return view()

def view():
    rows = [(r["id"], bool(r.get("_reserve") or r["id"] in gt._reserve_ids)) for r in gt._rows_data]
    return [i for i, res in rows if not res], [i for i, res in rows if res]

def record(ticked, name="חלוקת בדיקה"):
    """כמו המפעיל: שלב הרישום, סימון מי שקיבל, שמירה."""
    gt._set_stage("record")
    gt._checked_ids.clear(); gt._checked_ids |= set(ticked)
    gt._populate()
    gt.dist_input.setCurrentText("מחלק בדיקה"); gt.name_input.setCurrentText(name)
    gt._save()

def history(rid):
    return db.get_distributions_for_recipient(rid)

# ═══ E1 — "הגדרתי רזרבה N — רואים N" ═══════════════════════════════════════════════
# המספרים של יהודה: 52 מוצרים, 10 רזרבה, מצב רגיל. 30 קבועים + חד-פעמיים אחריהם, ואחריהם רזרבה.
for n_reg, label in ((30, "פחות קבועים ממוצרים"), (52, "בדיוק כמספר המוצרים"),
                     (55, "קצת יותר קבועים ממוצרים"), (70, "הרבה יותר קבועים ממוצרים")):
    fresh(); R = regs(n_reg); O = ones(80)
    main, res = screen("schedule", 52, 10)
    ok(f"E1 רגיל, {n_reg} קבועים ({label}), 52 מוצרים, רזרבה 10 → רזרבה 10", len(res) == 10, f"main={len(main)} res={len(res)}")
    ok(f"E1b …והרזרבה לא כוללת קבוע שכבר ברשימה", not (set(res) & set(main)))

fresh(); R = regs(30); O = ones(80)
main, res = screen("schedule", 52, 10)
queue = [r["id"] for r in db.get_reserve_candidates()]
gt.add_one_time_picks([{"id": i, "_reserve": False} for i in queue[:22]])
main2, res2 = view()
ok("E1c 30 קבועים + 22 חד-פעמיים שבחרתי = 52 ברשימה, ועוד 10 רזרבה", len(main2) == 52 and len(res2) == 10, f"{len(main2)}/{len(res2)}")
ok("E1d הרזרבה היא 10 האנשים שבתור מיד אחרי ה-22 שנבחרו, ולא השתנתה בעקבות הבחירה",
   res2 == queue[22:32] and res == res2, f"{res} / {res2}")

for mode in ("scored", "filter", "none"):
    fresh(); R = regs(10); O = ones(20)
    if mode == "none":
        db.set_setting("dist_regulars_mode", "none"); gt.refresh()
        gt.add_one_time_picks([{"id": O[0], "_reserve": False}])
    main, res = screen(mode, 30, 4)
    ok(f"E1e מצב {mode}: רזרבה 4 → 4 רזרבות", len(res) == 4, f"main={len(main)} res={len(res)}")

# ═══ E2 — לעולם לא ארוך ממספר המוצרים ═════════════════════════════════════════════
for mode in ("schedule", "scored", "filter"):
    fresh(); R = regs(70); O = ones(5)
    main, res = screen(mode, 52, 10)
    ok(f"E2 מצב {mode}: 70 זכאים, 52 מוצרים → ברשימה לא יותר מ-52", len(main) <= 52, f"main={len(main)}")
    main, res = screen(mode, 0, 10)
    ok(f"E2b מצב {mode}: מוצרים 0 → טבלה ריקה", main == [] and res == [])

# ═══ E3 — מי שמחכה הכי הרבה זמן נכנס ראשון ═══════════════════════════════════════
fresh(); R = regs(8)                    # קבוע 7 מחכה הכי הרבה, קבוע 0 הכי מעט
main, res = screen("schedule", 3, 2)
ok("E3 3 מוצרים ל-8 קבועים → נכנסים השלושה שמחכים הכי הרבה", main == [R[7], R[6], R[5]], str(main))
ok("E3b …והרזרבה היא הבאים אחריהם בהמתנה", res == [R[4], R[3]], str(res))

# ═══ E4 — קבוע שתורו לא הגיע לא מופיע, גם לא כרזרבה ═══════════════════════════════
for freq, ago in (("דו-שבועי", 7), ("חודשי", 14)):
    fresh(); R = regs(3); X = regs(1, prefix=f"{freq} לא בתור", freq=freq)
    # קיבל `ago` ימים לפני הרביעי הקרוב — פחות מהמחזור (14 / 28) ולכן תורו לא הגיע
    db.update_recipient(X[0], {"last_distribution": (WED - timedelta(days=ago)).isoformat()})
    ones(4)
    for mode in ("schedule", "scored", "filter"):
        main, res = screen(mode, 50, 5)
        ok(f"E4 {freq} שתורו לא הגיע — לא ברשימה ולא ברזרבה (מצב {mode})", X[0] not in main + res, f"main={len(main)} res={len(res)}")

# ═══ E5 — רישום: מי שקיבל נעלם, מי שלא סומן "לא הגיע", רזרבה לא נרשמת ═════════════
fresh(); R = regs(6); O = ones(10)
main, res = screen("schedule", 6, 3)
ticked = main[:4]; not_ticked = main[4:]
record(ticked)
ok("E5 מי שסומן נרשם כמי שקיבל", all(any(h.get("received") for h in history(i)) for i in ticked))
ok("E5b מי שלא סומן נרשם 'לא הגיע' (received=0)",
   all(history(i) and not any(h.get("received") for h in history(i)) for i in not_ticked), str([history(i) for i in not_ticked][:1]))
ok("E5c הרזרבה לא נרשמה בכלל (לא קיבל ולא 'לא הגיע')", all(history(i) == [] for i in res), str(res))
main_after, res_after = screen("schedule", 6, 3)
ok("E5d מי שקיבל לא חוזר לרשימה של אותו שבוע (גם לא כרזרבה)", not (set(ticked) & set(main_after + res_after)),
   str(set(ticked) & set(main_after + res_after)))
ok("E5e מי שנרשם 'לא הגיע' נשאר בתור", set(not_ticked) <= set(main_after), str(main_after))

# ═══ E6 — חד-פעמי שקיבל לא חוזר עד שעוברות 4 שבועות ═══════════════════════════════
fresh(); R = regs(2); O = ones(6)
db.update_recipient(O[0], {"last_distribution": (WED - timedelta(days=14)).isoformat()})     # לפני שבועיים
db.update_recipient(O[1], {"last_distribution": (WED - timedelta(days=35)).isoformat()})     # לפני 5 שבועות
cand = [r["id"] for r in db.get_reserve_candidates()]
ok("E6 חד-פעמי שקיבל לפני שבועיים לא בתור (גם לא כרזרבה)", O[0] not in cand, str(cand))
ok("E6b חד-פעמי שקיבל לפני 5 שבועות חוזר לתור", O[1] in cand, str(cand))
main, res = screen("schedule", 5, 6)
ok("E6c …וכך גם על המסך", O[0] not in main + res and O[1] in main + res, f"{main}/{res}")

# ═══ E7 — 🗑 מוריד בלי לרשום "לא הגיע", והבא בתור נכנס ═══════════════════════════
fresh(); R = regs(8)
main, res = screen("schedule", 5, 0)
victim = main[0]; nxt = [r for r in selection.rank_by_wait(db.get_weekly_list(), db.get_need_weights())][5]["id"]
gt._remove_from_list({"id": victim}); main2, res2 = view()
ok("E7 🗑 מוריד אותו מהרשימה", victim not in main2 + res2)
ok("E7b …ולא נרשם 'לא הגיע'", history(victim) == [])
ok("E7c …והמוצר שהתפנה עובר לבא בתור (עדיין 5 ברשימה)", len(main2) == 5 and nxt in main2, f"{len(main2)}")

# ═══ E8 — מושהה לא מופיע בשום מקום ═══════════════════════════════════════════════
fresh(); R = regs(4); O = ones(8)
db.update_recipient(R[0], {"status": "מושהה"}); db.update_recipient(O[0], {"status": "מושהה"})
for mode in ("schedule", "scored", "filter"):
    main, res = screen(mode, 50, 6)
    ok(f"E8 מושהה (קבוע וחד-פעמי) לא ברשימה ולא ברזרבה — מצב {mode}", not ({R[0], O[0]} & set(main + res)))

# ═══ E9 — צינתוקים/מיילים/"בחר הכל" לא נוגעים ברזרבה ═════════════════════════════
fresh(); R = regs(5); O = ones(8)
main, res = screen("schedule", 5, 3)
ok("E9 יש רזרבה על המסך", len(res) == 3)
ok("E9b רשימת השבוע לצינתוקים/מיילים (week_rows) בלי הרזרבה", {r["id"] for r in gt.week_rows()} == set(main), str(len(gt.week_rows())))
gt._set_stage("record"); gt._uncheck_all(); gt._check_all()
ok("E9c 'בחר הכל' מסמן רק את הרשימה, לא את הרזרבה", set(gt._checked_ids) == set(main), f"{len(gt._checked_ids)}")
gt._uncheck_all(); gt._set_stage("prep")

# ═══ E10 — נעילה ═════════════════════════════════════════════════════════════════
fresh()
W_DAYS = [WED - timedelta(days=14)]
R = regs(5)
BI = regs(2, prefix="דו-שבועי בתור", freq="דו-שבועי", last_days_ago=1)        # יתוקן מיד לתאריך
for b in BI:
    db.update_recipient(b, {"last_distribution": (WED - timedelta(days=14)).isoformat()})
O = ones(10)
main, res = screen("schedule", 7, 3)
ok("E10 דו-שבועי שהגיע תורו ברשימה", set(BI) <= set(main), str(main))
gt._lock_plan()
plan = db.get_plan(WED)
roles = [m["role"] for m in plan["members"]] if plan else []
ok("E10b נעילה שומרת בדיוק מה שרואים: 7 עיקריים + 3 רזרבה", roles.count("main") == 7 and roles.count("reserve") == 3, str(roles))
gt.refresh()
m3, r3 = view()
ok("E10c נטען מחדש — אותה רשימה ואותה רזרבה", set(m3) == set(main) and set(r3) == set(res), f"{len(m3)}/{len(r3)}")
nxt_week = WED + timedelta(days=7)
fm, fr = (lambda: (gt.date_edit.set_from_iso(nxt_week.isoformat()), gt.refresh(), view())[2])()
ok("E10d נעול בשבוע אחד (דו-שבועי) → לא נכנס לשבוע שאחריו", not (set(BI) & set(fm + fr)), f"{len(fm)}/{len(fr)}")
cand_next = {r["guid"] for r in db.get_reserve_candidates(on_date=nxt_week)}
res_guids = {m["g"] for m in plan["members"] if m["role"] == "reserve"}
ok("E10e רזרבה בנעילה לא תופסת אף אחד — הם עדיין זמינים לשבוע הבא", res_guids <= cand_next, f"{len(res_guids & cand_next)}/{len(res_guids)}")
gt.date_edit.set_from_iso(WED.isoformat()); gt.refresh()
gt._unlock_plan()
gt.date_edit.set_from_iso(nxt_week.isoformat()); gt.refresh()
fm2, fr2 = view()
ok("E10f בקרה: בלי הנעילה אותם דו-שבועיים כן היו נכנסים לשבוע הבא (הבדיקה E10d באמת תופסת)",
   set(BI) <= set(fm2 + fr2), f"{len(fm2)}/{len(fr2)}")
gt.date_edit.set_from_iso(WED.isoformat()); gt.refresh()

# ═══ E11 — תחזית לא נוגעת בשבוע האמיתי ══════════════════════════════════════════════
fresh(); R = regs(6); O = ones(8)
screen("schedule", 20, 2)
real = {k: db.get_setting(k) for k in ("available_products", "reserve_count", "weekly_extra_ids", "weekly_reserve_ids")}
gt.date_edit.set_from_iso((WED + timedelta(days=7)).isoformat()); gt.refresh()
gt.products_spin.setValue(9); gt.reserve_spin.setValue(4)
fm, fr = view()
ok("E11 בתחזית רואים את המספרים של התחזית (4 רזרבה)", len(fr) == 4, f"{len(fm)}/{len(fr)}")
ok("E11b …וההגדרות של השבוע האמיתי לא השתנו",
   {k: db.get_setting(k) for k in real} == real, str({k: db.get_setting(k) for k in real}))
gt.date_edit.set_from_iso(WED.isoformat()); gt.refresh()
ok("E11c חזרה לשבוע האמיתי — המספרים האמיתיים", (gt.products_spin.value(), gt.reserve_spin.value()) == (20, 2))

print("\nRESULT:", "ALL USER-EXPECTATION CHECKS PASS ✓" if not fails else f"FAILURES: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)

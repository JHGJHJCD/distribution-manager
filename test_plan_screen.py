# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 2, נעילת רשימות: המסך (offscreen, DB זמני, "היום" מזויף).

S0 — בידוד התחזית מההגדרות של השבוע האמיתי (U3) ופלטים שנכשלים סגור (U8):
  • בתחזית "מוצרים זמינים"/"רזרבה" נשמרים בזיכרון בלבד — לא נכתבים ל-available_products /
    reserve_count / weekly_extra_ids; תחזית חדשה מתחילה מהמספרים של השבוע האמיתי
  • "חלוקה חדשה" בתחזית לא נוגעת בכלום
  • week_rows() ריק בתחזית (צינתוק ומייל לא מגיעים לשבוע אחר)
הרצה: python test_plan_screen.py  (Python 3.12)"""
import os, sys, tempfile, copy
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups"); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
shown = []
for _m in ("information", "critical", "warning"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: shown.append(" ".join(str(x) for x in a[1:3]))))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

import datetime as _dtm
import selection
import tabs.group_update as gu
_Real = _dtm.date
class _Fake(_Real):
    _today = _Real(2026, 10, 18)                      # יום ראשון; הרביעי הקרוב = 21/10
    @classmethod
    def today(cls):
        t = cls._today
        return _Real(t.year, t.month, t.day)
db.date = _Fake; selection._date = _Fake; gu.date = _Fake
D = _Real
SUN, W1, W2, W3 = D(2026, 10, 18), D(2026, 10, 21), D(2026, 10, 28), D(2026, 11, 4)

db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "50"); db.set_setting("reserve_count", "3")
db.set_setting("weekly_extra_ids", ""); db.set_setting("weekly_reserve_ids", "")
for i in range(6):
    db.add_recipient({"full_name": f"שבועי {i}", "status": "פעיל", "frequency": "שבועי", "priority": 4,
                      "souls": 3, "children_total": 3})

from main import MainWindow
win = MainWindow()
gt, tz, ml = win.group_tab, win.tzintukim_tab, win.mails_tab

def set_date(d):
    gt.date_edit.set_from_iso(d.isoformat())

def settings():
    return {k: db.get_setting(k) for k in ("available_products", "reserve_count",
                                            "weekly_extra_ids", "weekly_reserve_ids")}

set_date(SUN); gt.refresh(); gt._needs_refresh = False
real0 = settings()
ok("U3a השבוע האמיתי: הספינרים = ההגדרות המשותפות", (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))

# ── U3 — תחזית לא כותבת להגדרות של השבוע האמיתי ───────────────────────────────────
set_date(W2)
ok("U3b תחזית חדשה מתחילה מהמספרים של השבוע האמיתי (הצעה גלויה)",
   gt.list_is_future() and (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))
gt.products_spin.setValue(4); gt.reserve_spin.setValue(1)
ok("U3c שינוי מוצרים/רזרבה בתחזית לא כותב ל-available_products / reserve_count / הבחירות", settings() == real0, str(settings()))
ok("U3d הרשימה בתחזית עוקבת אחרי המספרים שבזיכרון (4 + רזרבה 1 = 5 שורות)", len(gt._rows_data) == 5, str(len(gt._rows_data)))
set_date(W3)
ok("U3e תחזית של שבוע אחר מתחילה מחדש מהשבוע האמיתי (50/3) — לא מדליפה מהתחזית הקודמת",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))
set_date(W2)
ok("U3f חזרה לאותה תחזית: הערכים שלה נשמרו בזיכרון (4/1)",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (4, 1))
set_date(SUN)
ok("U3g חזרה לשבוע האמיתי: הערכים האמיתיים כפי שהיו, וההגדרות לא נגעו",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3) and settings() == real0)
gt.products_spin.setValue(40)
ok("U3h בשבוע האמיתי שינוי כן נכתב להגדרות (כמו תמיד)", db.get_setting("available_products") == "40")
gt.products_spin.setValue(50)
real0 = settings()

# מצב סינון: החיתוך ב-DB משתמש במספרים של התחזית, לא בהגדרות
set_date(W2)
db.set_setting("dist_regulars_mode", "filter")      # דרך ההגדרה — בחירה בקומבו פותחת דיאלוג סינון
db.set_filter_criteria({"balance_communities": False})
gt.products_spin.setValue(2); gt.reserve_spin.setValue(0)
gt.refresh()
ok("U3i 'סינון מותאם' בתחזית נחתך למספר המוצרים של התחזית (2), וההגדרות לא נגעו",
   len(gt._rows_data) == 2 and settings() == real0, f"{len(gt._rows_data)} / {settings()}")
db.set_setting("dist_regulars_mode", "schedule"); gt.refresh()

# "חלוקה חדשה" בתחזית לא נוגעת בכלום
shown.clear()
gt._reset_for_new()
ok("U3j 'חלוקה חדשה' בתחזית נחסמת בהסבר ולא מאפסת את השבוע האמיתי", settings() == real0 and len(shown) == 1, str(shown))

# ── U8 — פלטים נכשלים סגור ───────────────────────────────────────────────────────
ok("U8a week_rows() בתחזית ריק", gt.list_is_future() and gt.week_rows() == [])
set_date(SUN)
gt.refresh()
ok("U8b week_rows() בשבוע הנוכחי רגיל (בלי רזרבות)", len(gt.week_rows()) >= 1
   and all(not r.get("_reserve") for r in gt.week_rows()))


# ═══ S4 — נעילת רשימה במסך ═══════════════════════════════════════════════════════
from PyQt6.QtWidgets import QDialog
gu.OneTimePickerDialog.exec = lambda self: QDialog.DialogCode.Accepted      # ההצעה מסומנת מראש; "אישור"
questions = []
def ask(answer):
    QMessageBox.question = staticmethod(lambda *a, **k: (questions.append(a[1] if len(a) > 1 else ""),
                                                          QMessageBox.StandardButton.Yes if answer else QMessageBox.StandardButton.No)[1])
ask(True)

# נתוני S4: מחדש את הטבלאות (שומר על המסך), קבועים שבועיים + חודשי ודו-שבועי שטרם קיבלו + חד-פעמיים
db.reset_all_data()
db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "50"); db.set_setting("reserve_count", "3")
db.set_setting("weekly_extra_ids", ""); db.set_setting("weekly_reserve_ids", "")
def mk(name, freq, prio=4, **kw):
    return db.add_recipient({"full_name": name, "status": "פעיל", "frequency": freq, "priority": prio,
                             "souls": 3, "children_total": 3, **kw})
WK = [mk(f"ש-{i}", "שבועי") for i in range(5)]
R_M = mk("חודשי-ב", "חודשי"); R_B = mk("דו-ב", "דו-שבועי")
ONE = [mk(f"חד-{i}", "חד-פעמי", prio=3, souls=4) for i in range(4)]
def guid(rid): return db.get_recipient(rid)["guid"]

set_date(SUN); gt._set_stage("prep", clear=False); gt.refresh()

# ── U1 — מטריצת נראות ────────────────────────────────────────────────────────────
ok("U1a שבוע נוכחי חי: כפתור 'נעל' גלוי ופעיל, בלי באנר",
   gt.btn_lock_plan.isVisibleTo(gt) and gt.btn_lock_plan.isEnabled() and gt.btn_lock_plan.text() == "🔒 נעל רשימה"
   and not gt.plan_banner_frame.isVisibleTo(gt), gt.btn_lock_plan.text())
gt.products_spin.setValue(0)
ok("U1b מוצרים=0: הכפתור נעול עם הסבר", not gt.btn_lock_plan.isEnabled() and "מוצרים" in gt.btn_lock_plan.toolTip())
gt.products_spin.setValue(50)
gt.chk_bonus.setChecked(True)
gt._plan_refresh_ui()
ok("U1c בונוס מסומן: הכפתור נעול ('רק לחלוקה רגילה')", not gt.btn_lock_plan.isEnabled() and "רגילה" in gt.btn_lock_plan.toolTip())
gt.chk_bonus.setChecked(False); gt._plan_refresh_ui()
set_date(D(2026, 10, 14))
ok("U1d תאריך עבר (רישום בדיעבד): הכפתור מוסתר", not gt.btn_lock_plan.isVisibleTo(gt))
set_date(SUN)
gt._set_stage("record", clear=False)
ok("U1e שלב רישום: הכפתור מוסתר", not gt.btn_lock_plan.isVisibleTo(gt))
gt._set_stage("prep", clear=False)

# ── U2 — נעילת השבוע הנוכחי שומרת בדיוק את מה שבמסך, והגלובליים לא נגעו ───────────
gt.add_one_time_picks([{"id": ONE[0]}])                 # בחירה אמיתית של השבוע (הגדרה גלובלית)
glob0 = settings()
rows_before = [r["id"] for r in gt._rows_data]
n_rows = len(rows_before)
gt._lock_plan()
plan = db.get_plan(W1)
ok("U2a נוצרה נעילה ל-21/10 עם כל מה שהיה על המסך (כולל הבחירה החד-פעמית)",
   plan is not None and len(plan["members"]) == n_rows
   and {m["g"] for m in plan["members"]} == {guid(i) for i in rows_before}
   and [m["kind"] for m in plan["members"] if m["g"] == guid(ONE[0])] == ["one"], str(n_rows))
ok("U2b מוצרים/רזרבה נשמרו בנעילה", plan["products"] == 50 and plan["reserve"] == 3)
ok("U2c המסך במצב נעילה: באנר, כפתור 'בטל נעילה', צ'יפ, מצב הקומבו מושבת",
   gt._plan_mode() and gt.plan_banner_frame.isVisibleTo(gt) and "רשימה נעולה לרביעי 21/10" in gt.lbl_plan_banner.text()
   and gt.btn_lock_plan.text() == "🔓 בטל נעילה" and "21/10" in gt.chip_plans.text()
   and not gt.mode_combo.isEnabled(), gt.lbl_plan_banner.text())
ok("U2d ההגדרות הגלובליות לא נגעו (בחירות, מוצרים, רזרבה)", settings() == glob0, str(settings()))
ok("U2e week_rows (צינתוק/מייל/הדפסה) = חברי הנעילה בלי רזרבות", {r["id"] for r in gt.week_rows()} ==
   {r["id"] for r in gt._rows_data if not r.get("_reserve")})
ok("U2f כפתור 'נעל' כשכבר נעול הופך ל'בטל' (אין כפילות)", db.get_plan(W1) is not None and len(db.list_plans()) == 1)

# ── U4 — עריכות כותבות מיד ל נעילה ────────────────────────────────────────────────
victim = next(r for r in gt._rows_data if r["id"] in WK)
gt._remove_from_list(victim)
p1 = db.get_plan(W1)
ok("U4a 🗑 מעבירה מהחברים ל-removed ומוציאה מהטבלה, והגלובליים לא נגעו",
   guid(victim["id"]) in p1["removed"] and guid(victim["id"]) not in {m["g"] for m in p1["members"]}
   and victim["id"] not in {r["id"] for r in gt._rows_data} and settings() == glob0)
extra_r = mk("נוסף-ידנית", "שבועי")
gt._plan_add_members([{"id": extra_r}], "man"); gt.refresh()
p2 = db.get_plan(W1)
ok("U4b הוספה ידנית נכנסת כ-man/main ונראית במסך", any(m["g"] == guid(extra_r) and m["kind"] == "man" and m["role"] == "main"
                                                       for m in p2["members"]) and extra_r in {r["id"] for r in gt._rows_data})
gt._plan_add_members([{"id": victim["id"]}], "man"); gt.refresh()
ok("U4c החזרת מי שהוסר: יוצא מ-removed וחוזר לרשימה", guid(victim["id"]) not in db.get_plan(W1)["removed"]
   and victim["id"] in {r["id"] for r in gt._rows_data})
gt._plan_set_note(extra_r, "הערה לשורה"); gt.refresh()
ok("U4d הערה נשמרת בנעילה וחוזרת למסך", [m["note"] for m in db.get_plan(W1)["members"] if m["g"] == guid(extra_r)] == ["הערה לשורה"]
   and gt._row_notes.get(extra_r) == "הערה לשורה")
gt.products_spin.setValue(5); gt.reserve_spin.setValue(1)
p3 = db.get_plan(W1)
ok("U4e שינוי מוצרים/רזרבה נכתב לנעילה (חברים לא נגעו) ולא להגדרות הגלובליות",
   (p3["products"], p3["reserve"]) == (5, 1) and len(p3["members"]) == len(p2["members"]) + 1
   and settings() == glob0, str((p3["products"], p3["reserve"], settings())))
ok("U4f הבאנר מציין חברים מעל המוצרים", "בנעילה" in gt.lbl_plan_banner.text() and "מוצרים" in gt.lbl_plan_banner.text(),
   gt.lbl_plan_banner.text())
gt.products_spin.setValue(50); gt.reserve_spin.setValue(3)

# ── U5 — קפואה אך לא עיוורת: השוואה לנתונים החיים ─────────────────────────────────
late = mk("מאוחר-קבוע", "שבועי")                                      # נוסף אחרי הנעילה — חייב מיד
moved = next(r["id"] for r in gt._rows_data if r["id"] in WK)
db.update_recipient(moved, {"frequency": "חודשי", "last_distribution": "2026-10-15"})  # כבר לא בתור
paused = next(r["id"] for r in gt._rows_data if r["id"] in WK and r["id"] != moved)
db.update_recipient(paused, {"status": "מושהה"})
before_plan = copy.deepcopy(db.get_plan(W1)) if False else db.get_plan(W1)
gt.refresh()
cmp_ = gt._plan_cmp
ok("U5a השוואה: החדש בתור מסומן, מי שכבר לא בתור מסומן, ומושהה לא נכלל במסך",
   [r["id"] for r in cmp_["new"]] == [late] and [r["id"] for r in cmp_["gone"]] == [moved]
   and paused not in {r["id"] for r in gt._rows_data} and gt._plan_info["inactive"] == 1,
   f"{[r['full_name'] for r in cmp_['new']]} / {[r['full_name'] for r in cmp_['gone']]} / {gt._plan_info}")
ok("U5b הבאנר מציג את ההבדל וכפתור 'עדכן' גלוי", "חדשים בתור" in gt.lbl_plan_banner.text()
   and gt.btn_plan_refresh.isVisibleTo(gt), gt.lbl_plan_banner.text())
ok("U5c הנעילה עצמה לא השתנתה לבד", db.get_plan(W1)["updated_at"] == before_plan["updated_at"])
ask(False); gt._plan_apply_compare()
ok("U5d 'עדכן' עם סירוב — לא כותב", db.get_plan(W1)["updated_at"] == before_plan["updated_at"])
ask(True); gt._plan_apply_compare()
p5 = db.get_plan(W1)
ok("U5e 'עדכן' באישור: החדש נכנס, מי שיצא מהתור יוצא, הוספה ידנית (man) נשארת",
   guid(late) in {m["g"] for m in p5["members"]} and guid(moved) not in {m["g"] for m in p5["members"]}
   and any(m["g"] == guid(extra_r) for m in p5["members"]))
ok("U5f אחרי העדכון אין הבדלים", not gt._plan_cmp["new"] and not gt._plan_cmp["gone"])
db.update_recipient(paused, {"status": "פעיל"})

# ── U9/U10 — התנגשות בין מחשבים ורענון אחרי סנכרון ────────────────────────────────
other = copy.deepcopy(db.get_plan(W1))                                   # "המחשב השני" כותב לנעילה
other["note"] = "מהמחשב השני"
other["members"] = [m for m in other["members"] if m["g"] != guid(late)]
db.save_plan(other)
ok("U10 רענון אחרי סנכרון: השינוי מהמחשב השני מוצג בלי הפעלה מחדש", (gt.refresh(), late not in {r["id"] for r in gt._rows_data})[1])
stale_plan = copy.deepcopy(gt._plan)
db.save_plan(copy.deepcopy(db.get_plan(W1)))                             # עוד כתיבה "מרחוק" — האסימון שלנו ישן
gt._plan = stale_plan
ask(True)                                                                # טען מחדש: העריכה שלי אובדת
gt._plan_set_note(extra_r, "שלי-אובדת")
ok("U9a אסימון ישן + 'טען מחדש' — העריכה לא נכתבת", [m["note"] for m in db.get_plan(W1)["members"]
                                                   if m["g"] == guid(extra_r)] != ["שלי-אובדת"])
gt.refresh()
gt._plan = copy.deepcopy(gt._plan)
db.save_plan(copy.deepcopy(db.get_plan(W1)))
ask(False)                                                               # לדרוס: העריכה נשמרת על המצב החדש
gt._plan_set_note(extra_r, "שלי-דורסת")
ok("U9b אסימון ישן + 'לא' — העריכה נשמרת על המצב העדכני", [m["note"] for m in db.get_plan(W1)["members"]
                                                          if m["g"] == guid(extra_r)] == ["שלי-דורסת"])
ask(True); gt.refresh()

# ── U7 — 'חלוקה חדשה' על שבוע נעול ────────────────────────────────────────────────
ask(False); gt._reset_for_new()
ok("U7a 'חלוקה חדשה' על נעילה ובתשובה 'לא' — לא נוגעת בכלום", db.get_plan(W1) is not None and settings() == glob0)

# ── ביטול נעילה: חוזרים לטיוטה כפי שהייתה ──────────────────────────────────────────
ask(True); gt._unlock_plan()
ok("U4g ביטול נעילה: חישוב חי חוזר, הבחירה האמיתית (חד-פעמי) כפי שהייתה, הקומבו פעיל",
   not gt._plan_mode() and db.get_plan(W1) is None and ONE[0] in gt._extra_ids and settings() == glob0
   and gt.mode_combo.isEnabled() and not gt.plan_banner_frame.isVisibleTo(gt))
ok("U4h ההסרות בזיכרון של הטיוטה לא דלפו מהנעילה", victim["id"] in {r["id"] for r in gt._rows_data})

# ── תחזית: אזהרת "שבוע שלפני" והצעת חד-פעמיים אוטומטית (U11, U12) ───────────────────
set_date(W2)
ok("U11a תחזית ל-28/10 כש-21/10 לא נעול ולא נרשם: אזהרה על 21/10",
   "השבוע של 21/10 עדיין לא נעול" in gt.lbl_future_note.text(), gt.lbl_future_note.text())
set_date(W1); gt.refresh(); gt._lock_plan()
set_date(W2)
ok("U11b אחרי נעילת 21/10 האזהרה נעלמת", "עדיין לא נעול" not in gt.lbl_future_note.text(), gt.lbl_future_note.text())
glob1 = settings()
ok("U11c בלי שבוע ביניים (תחזית ל-21/10 עצמו) אין אזהרה", (set_date(W1), "עדיין לא נעול" not in gt.lbl_future_note.text())[1])
set_date(W2)
ok("U12a תחזית לא נעולה לא מציעה חד-פעמיים (קבועים בלבד)", not any(r["id"] in ONE for r in gt._rows_data))
gt.products_spin.setValue(8); gt.reserve_spin.setValue(0)                # 8 מוצרים: 7 קבועים בתור ← מקום לחד-פעמי אחד
gt._lock_plan()
p_w2 = db.get_plan(W2)
ones = [m for m in p_w2["members"] if m["kind"] == "one"]
n_slots, _regs = db.compute_suggested_n(8, 0, on_date=W2)
ok("U12b נעילת תחזית: חד-פעמיים נוספו אוטומטית (kind=one) בגודל compute_suggested_n",
   len(ones) == n_slots and n_slots >= 1 and all(m["g"] in {guid(i) for i in ONE} for m in ones),
   f"{len(ones)} / {n_slots}")
ok("U12c נעילת תחזית לא נגעה בהגדרות הגלובליות", settings() == glob1, str(settings()))
ok("U12d תחזית נעולה: עריכה מותרת (🗑) וכותבת לנעילה בלבד",
   (gt._remove_from_list(next(r for r in gt._rows_data if r["id"] in WK)), settings() == glob1
    and len(db.get_plan(W2)["removed"]) == 1)[1])
set_date(W3)
picker = gu.OneTimePickerDialog(gt, on_date=W3, counts=(8, 0))
offered = {r["id"] for r in picker._rows}
ok("U12e תחזית של השבוע שאחריו לא מציעה את אותם חד-פעמיים (הפסקה 4 שבועות)",
   not (offered & {i for i in ONE if guid(i) in {m["g"] for m in ones}}) and offered, f"{sorted(offered)}")
set_date(W2)
shown.clear(); gt._on_stage_toggle("record")
ok("U6a רישום בתחזית נעולה חסום", gt._stage == "prep" and shown, str(shown))
shown.clear(); gt._set_stage("record", clear=False); gt._save(); gt._set_stage("prep", clear=False)
ok("U6b גם _save בכוח חסום", bool(shown))

# ── U6 — רישום בשבוע הנוכחי הנעול: הנעילה "בוצעה" והמסך חוזר לטיוטה ─────────────────
set_date(W1); gt.refresh()
ok("U6c חזרה לשבוע הנוכחי: הנעילה שלו מוצגת", gt._plan_mode() and gt._plan["week_wed"] == W1.isoformat())
gt.add_one_time_picks([{"id": ONE[3]}]) if False else None
tick = next(r["id"] for r in gt._rows_data if not r.get("_reserve"))
gt._set_stage("record", clear=True); gt._checked_ids.add(tick); gt._populate()
gt.dist_input.setCurrentText("מחלק בדיקה")
gt._save()
batches = db.get_distribution_batches()
ok("U6d נרשמה אצווה ב-21/10 וה-W1 נגזרת 'בוצעה'", any(b["dist_date"] == W1.isoformat() for b in batches)
   and db.plan_states(W1).get(W1) == "executed", str(db.plan_states(W1)))
ok("U6e אחרי הרישום המסך יצא ממצב נעילה והבחירות הגלובליות נוקו כמו תמיד",
   not gt._plan_mode() and db.get_setting("weekly_extra_ids") == "", str(settings()))
ok("U6f נעילת W2 נשארה חיה ותופסת (נעילה עתידית)", db.get_plan(W2) is not None
   and db.plan_states(SUN).get(W2) == "future")

print()
print("RESULT:", "ALL PLAN-SCREEN CHECKS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

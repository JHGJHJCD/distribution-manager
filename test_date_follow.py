# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 1 (יהודה 18/10/2026): מסך "חלוקה ורישום" עוקב אחרי התאריך שנבחר.
תאריך של שבוע הבא מציג תחזית קריאה-בלבד (הרשימה של הרביעי ההוא, לפי מה שנרשם עד היום);
רישום חלוקה חסום עליה, צינתוקים לא מצלצלים אליה; שבוע נוכחי / תאריך עבר / רישום בדיעבד — בלי שינוי.
offscreen, DB זמני, "היום" מזויף (FakeDate).  הרצה: python test_date_follow.py  (Python 3.12)"""
import os, sys, tempfile
from datetime import timedelta
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
warned = []
for _m in ("information", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(" ".join(str(x) for x in a[1:3])))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

# ── "היום" מזויף: db + selection + המסך (שלושתם קוראים date.today() משלהם) ───────────
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
def set_today(d):
    _Fake._today = d

D = _Real
SUN, W0, W1, W2 = D(2026, 10, 18), D(2026, 10, 21), D(2026, 10, 28), D(2026, 11, 4)

# הייצואים (אקסל אחרי שמירה, קובץ מתנדב) לא נוחתים בתיקיית ההורדות של המשתמש ו-Explorer לא נפתח
_EXPORTS = tempfile.mkdtemp()
for _k in ("dist", "volunteers", "recipients"):
    db.set_setting(f"export_dir_{_k}", _EXPORTS)
gu.reveal_in_folder = lambda *a, **k: None

def add_regular(name, freq):
    return db.add_recipient({"full_name": name, "status": "פעיל", "frequency": freq, "priority": 4,
                             "souls": 3, "phone1": "05" + str(abs(hash(name)) % 10**8).zfill(8)})

def setup_week(round_iso):
    """שבועי / דו-שבועי / חודשי שנרשמו בחלוקה רגילה ב-round_iso, ועוד שבועי שטרם קיבל."""
    db.reset_all_data()
    db.set_setting("dist_regulars_mode", "schedule")
    db.set_setting("available_products", "50")
    db.set_setting("reserve_count", "0")
    db.set_setting("weekly_extra_ids", ""); db.set_setting("weekly_reserve_ids", "")
    ids = {}
    for nm, fq in (("ק-שבועי", "שבועי"), ("ק-דו-שבועי", "דו-שבועי"), ("ק-חודשי", "חודשי")):
        rid = add_regular(nm, fq)
        db.bulk_add_distributions([{"id": rid, "full_name": nm, "frequency": fq}], round_iso, "", 1, "מחלק")
        ids[nm] = rid
    ids["ק-חדש"] = add_regular("ק-חדש", "שבועי")
    return ids

ids = setup_week(SUN.isoformat())
from main import MainWindow
win = MainWindow()
gt, tz, ml = win.group_tab, win.tzintukim_tab, win.mails_tab

def names(rows):
    return {r.get("full_name") for r in rows}

def set_date(d):
    gt.date_edit.set_from_iso(d.isoformat())

set_date(SUN); gt.refresh(); gt._needs_refresh = False

# ── 1. ברירת מחדל: שבוע נוכחי — בלי תחזית ─────────────────────────────────────────
ok("D1 התאריך שבמסך = היום (ראשון)", gt.date_edit.get_iso() == SUN.isoformat(), gt.date_edit.get_iso())
ok("D1 _list_date() == None והרשימה אינה תחזית", gt._list_date() is None and gt.list_is_future() is False)
ok("D1 תווית התחזית קיימת (lbl_future_note) ומוסתרת", gt.lbl_future_note.objectName() == "lbl_future_note"
   and gt.lbl_future_note.isHidden())
cur_names = names(gt._rows_data)
ok("D1 הרשימה הנוכחית: מי שנרשם ביום ראשון לא בה, רק מי שטרם קיבל", cur_names == {"ק-חדש"}, str(sorted(cur_names)))
ok("D1 הכיתוב בספירה בלי 'תחזית'", "תחזית" not in gt.lbl_regulars_count.text(), gt.lbl_regulars_count.text())
ok("D1 הסתרת התחזית לא נוגעת בטקסט הקיים: 'קבועים השבוע: 1'", "קבועים השבוע: 1" in gt.lbl_regulars_count.text())

# ── 2. מתי זו תחזית (הנוסחה: הרביעי של התאריך שנבחר אחרי הרביעי הקרוב האמיתי) ───────────
def kind(d):
    set_date(d)
    return gt._list_date(), gt.list_is_future()
ok("D2 הרביעי הקרוב עצמו — לא תחזית", kind(W0) == (None, False))
ok("D2 שני תאריכי עבר (רביעי שעבר, חודש אחורה) — לא תחזית", kind(D(2026, 10, 14)) == (None, False)
   and kind(D(2026, 9, 1)) == (None, False))
ok("D2 שני/שלישי של השבוע הנוכחי — לא תחזית", kind(D(2026, 10, 19)) == (None, False)
   and kind(D(2026, 10, 20)) == (None, False))
ok("D2 הרביעי הבא — תחזית, והתאריך הוא התאריך שנבחר", kind(W1) == (W1, True))
ok("D2 גם חמישי אחרי הרביעי הקרוב נחשב לשבוע הבא (הרביעי שאחריו)", kind(D(2026, 10, 22)) == (D(2026, 10, 22), True))
ok("D2 רחוק קדימה (חודש) — תחזית", kind(D(2026, 11, 18)) == (D(2026, 11, 18), True))

# ── 3. שינוי התאריך לשבוע הבא מרענן את הרשימה (אחרי שנרשמה חלוקת השבוע) ─────────────
calls = []
_orig_refresh = gt.refresh
gt.refresh = lambda *a, **k: (calls.append(1), _orig_refresh(*a, **k))[1]
set_date(SUN)                                    # חזרה לשבוע נוכחי
calls.clear()
set_date(W1)
ok("D3 שינוי תאריך אחד = רענון אחד בדיוק (בלי רענון כפול)", len(calls) == 1, str(len(calls)))
fut = names(gt._rows_data)
ok("D3 תחזית 28/10: השבועי והחדש כן; הדו-שבועי והחודשי (נרשמו השבוע) לא",
   fut == {"ק-שבועי", "ק-חדש"}, str(sorted(fut)))
calls.clear(); set_date(W1)
ok("D3 תאריך זהה לא מרענן שוב", len(calls) == 0, str(len(calls)))
set_date(W2); calls.clear()
fut2 = names(gt._rows_data)
ok("D3 תחזית 4/11: גם הדו-שבועי, עדיין לא החודשי", fut2 == {"ק-שבועי", "ק-דו-שבועי", "ק-חדש"}, str(sorted(fut2)))
set_date(D(2026, 11, 18))
ok("D3 תחזית 18/11: גם החודשי", names(gt._rows_data) == {"ק-שבועי", "ק-דו-שבועי", "ק-חודשי", "ק-חדש"},
   str(sorted(names(gt._rows_data))))
gt.refresh = _orig_refresh
del gt.refresh
set_date(W1)
ok("D3 week_rows() (מקור הצינתוקים והמיילים) הוא הרשימה העתידית", names(gt.week_rows()) == {"ק-שבועי", "ק-חדש"},
   str(sorted(names(gt.week_rows()))))
ok("D3 תחזית לא כתבה next_distribution של מי שטרם קיבל",
   db.get_recipient(ids["ק-חדש"])["next_distribution"] in ("", W0.isoformat(), None),
   str(db.get_recipient(ids["ק-חדש"])["next_distribution"]))

# ── 4. אינדיקציה: סיומת בשורת הספירה + תווית ענבר ─────────────────────────────────────
ok("D4 שורת הספירה: סיומת '· תחזית לרביעי 28/10'", gt.lbl_regulars_count.text().endswith("תחזית לרביעי 28/10"),
   gt.lbl_regulars_count.text())
ok("D4 תווית התחזית מוצגת עם התאריך המלא והניסוח המוסכם",
   (not gt.lbl_future_note.isHidden()) and "תצוגה מקדימה לרביעי 28/10/2026" in gt.lbl_future_note.text()
   and "לפי מה שנרשם עד היום" in gt.lbl_future_note.text()
   and "רישום חלוקה אפשרי רק בתאריך של החלוקה הקרובה" in gt.lbl_future_note.text(), gt.lbl_future_note.text())
ok("D4 התווית בצבע הענבר של הצ'יפים האזהרתיים ו-RTL", "#fdf0d5" in gt.lbl_future_note.styleSheet()
   and "#92600a" in gt.lbl_future_note.styleSheet()
   and gt.lbl_future_note.layoutDirection() == gu.Qt.LayoutDirection.RightToLeft)
set_date(D(2026, 11, 4))
ok("D4 תאריך אחר: התווית והסיומת מתעדכנות ל-4/11", "04/11/2026" in gt.lbl_future_note.text()
   and gt.lbl_regulars_count.text().endswith("תחזית לרביעי 04/11"), gt.lbl_regulars_count.text())
set_date(SUN)
ok("D4 חזרה לשבוע הנוכחי: התווית נעלמת והסיומת יורדת", gt.lbl_future_note.isHidden()
   and "תחזית" not in gt.lbl_regulars_count.text(), gt.lbl_regulars_count.text())
ok("D4 וחוזרת הרשימה הנוכחית", names(gt._rows_data) == {"ק-חדש"}, str(sorted(names(gt._rows_data))))

# ── 5. שם אוטומטי מתחדש לתאריך החדש; שם שהוקלד נשאר ──────────────────────────────────
from utils import hebdate
set_date(W0)
n0 = gt._effective_dist_name()
ok("D5 שם אוטומטי נוצר לתאריך הנוכחי ונכנס לשדה", gt._is_auto_name(n0) and gt.name_input.currentText() == n0, n0)
set_date(W1)
ok("D5 שינוי תאריך מנקה את השם האוטומטי הישן", gt.name_input.currentText() == "", repr(gt.name_input.currentText()))
n1 = gt._effective_dist_name()
exp1 = hebdate.auto_weekly_name(D(2026, 10, 28)) or (gt._AUTO_NAME_PREFIX + "28/10/2026")
ok("D5 השם נוצר מחדש לפי התאריך החדש (ושונה מהישן)", n1 == exp1 and n1 != n0, f"{n0!r} → {n1!r}")
gt.name_input.setCurrentText("חלוקת סוכות מיוחדת")
set_date(W2)
ok("D5 שם שהוקלד ידנית לא נמחק", gt.name_input.currentText() == "חלוקת סוכות מיוחדת", gt.name_input.currentText())
gt.name_input.setCurrentText(""); set_date(SUN)

# ── 6. תחזית: רישום חסום; מעבר לשלב הרישום חסום; ההדפסה/ייצוא לא נחסמים ───────────────
set_date(SUN); gt.refresh()
gt._set_stage("record")
tick = ids["ק-חדש"]
gt._checked_ids.add(tick); gt._populate()
gt.dist_input.setCurrentText("מחלק בדיקה")
batches_before = len(db.get_distribution_batches())
set_date(W1)
ok("D6 מעבר לתחזית חוזר לשלב ההכנה (תחזית לא נרשמת)", gt._stage == "prep", gt._stage)
ok("D6 הסימונים של הרשימה האמיתית נשמרו בתחזית (גלגלת עכבר לא מוחקת עבודה)", tick in gt._checked_ids,
   str(gt._checked_ids))
warned.clear()
gt._on_stage_toggle("record")
ok("D6 לחיצה על 'רישום' בתחזית: אזהרה, נשארים בהכנה", gt._stage == "prep" and len(warned) == 1
   and "רשימה לשבוע עתידי" in warned[0] and "החזר את התאריך לחלוקה הקרובה" in warned[0], str(warned))
warned.clear()
gt._set_stage("record")                          # גם בכוח (קוד) — השמירה עדיין חסומה
gt._save()
ok("D6 _save בתחזית: אזהרה בעברית פשוטה ושום דבר לא נרשם",
   len(warned) == 1 and "זו רשימה לשבוע עתידי" in warned[0]
   and "אי אפשר לרשום עליה חלוקה לפני שהיא מתקיימת" in warned[0],
   str(warned))
ok("D6 לא נוספה אצווה", len(db.get_distribution_batches()) == batches_before)
rows_exp = gt._get_export_rows()
ok("D6 ייצוא/הדפסה לוקחים את הרשימה העתידית", names(rows_exp) == {"ק-שבועי", "ק-חדש"}, str(sorted(names(rows_exp))))
gt._set_stage("prep", clear=False)

# ── 7. חזרה לתאריך הנוכחי: הסימון חזר ו-_save רושם כרגיל ─────────────────────────────
set_date(SUN)
ok("D7 חזרה לשבוע הנוכחי: הסימון עדיין שם", tick in gt._checked_ids)
gt._set_stage("record", clear=False)
warned.clear()
gt._save()
ok("D7 _save בתאריך הנוכחי לא נחסם", not any("שבוע עתידי" in w for w in warned), str(warned))
bs = db.get_distribution_batches()
ok("D7 נרשמה אצווה אחת חדשה בתאריך הנוכחי", len(bs) == batches_before + 1 and bs[0]["dist_date"] == SUN.isoformat(),
   f"{len(bs)} / {bs[0]['dist_date'] if bs else ''}")
ok("D7 אחרי הרישום הרשימה הנוכחית ריקה, והתחזית של 28/10 כוללת גם את החדש",
   names(gt._rows_data) == set() and (set_date(W1) or True) and names(gt._rows_data) == {"ק-שבועי", "ק-חדש"},
   str(sorted(names(gt._rows_data))))

# ── 8. רישום בדיעבד (תאריך עבר) ממשיך לעבוד כמו היום ─────────────────────────────────
past = D(2026, 10, 14)
set_date(past)
ok("D8 תאריך עבר: לא תחזית", gt._list_date() is None and not gt.list_is_future())
gt.refresh()
retro_name = "ק-בדיעבד"
rid_retro = add_regular(retro_name, "שבועי")
gt.refresh()
gt._set_stage("record", clear=True)
gt._checked_ids.add(rid_retro); gt._populate()
gt.dist_input.setCurrentText("מחלק בדיקה")
warned.clear(); n_b = len(db.get_distribution_batches())
gt._save()
bs = db.get_distribution_batches()
ok("D8 _save בתאריך עבר רושם (לא נחסם)", not any("שבוע עתידי" in w for w in warned) and len(bs) == n_b + 1
   and any(b["dist_date"] == past.isoformat() for b in bs), f"{len(bs)} / {[b['dist_date'] for b in bs]} / {warned}")

# ── 9. ייבוא קובץ מתנדב: נחסם לפי התאריך שיירשם (לא נמחק), קובץ של השבוע הנוכחי נקלט ─────
from utils.excel_utils import export_volunteer_checklist_to_excel
import shutil
rec_a = db.get_recipient(ids["ק-שבועי"])
def vfile(d_iso, name):
    return export_volunteer_checklist_to_excel([rec_a], d_iso, name, "סל מזון", 25, "מתנדב")
set_date(SUN)
f_fut = vfile(W1.isoformat(), "קובץ עתידי")
warned.clear(); n_b = len(db.get_distribution_batches())
res = gt._apply_checklist_file(f_fut, confirm=True)
ok("D9 קובץ בתאריך של שבוע עתידי: לא נקלט, אזהרה, הקובץ נשאר",
   res[0] == 0 and len(warned) == 1 and os.path.exists(f_fut) and len(db.get_distribution_batches()) == n_b,
   f"{res[0]} / {warned}")
res = gt._apply_checklist_file(f_fut, confirm=False)
ok("D9 קליטה אוטומטית של קובץ כזה: נשלחת לשאלת המפעיל (needs_review) ולא נרשמת",
   res[0] == 0 and res[3] is True and len(db.get_distribution_batches()) == n_b, str(res[:1] + res[3:]))
keep_copy = os.path.join(tempfile.mkdtemp(), "inbox.xlsx"); shutil.copyfile(f_fut, keep_copy)
gt._on_inbox_found([keep_copy])
ok("D9 _on_inbox_found לא מוחק קובץ שנחסם (התשובות של המתנדב לא הולכות לאיבוד)",
   os.path.exists(keep_copy) and len(db.get_distribution_batches()) == n_b)
f_now = vfile(W0.isoformat(), "קובץ השבוע")
n = gt._apply_checklist_file(f_now, confirm=True)[0]
ok("D9 קובץ של הרביעי הקרוב נקלט כרגיל (גם כשהמסך על תחזית)",
   (set_date(W1) or True) and gt._apply_checklist_file(vfile(W0.isoformat(), "קובץ השבוע 2"), confirm=True)[0] == 1
   and n == 1, f"n={n}")
import glob
for p in [f_fut, f_now, keep_copy] + glob.glob(os.path.join(_EXPORTS, "*.xlsx")):
    try: os.remove(p)
    except OSError: pass

# ── 10. הדיאלוגים והחישובים מקבלים את התאריך ─────────────────────────────────────────
set_date(W1)
slots_f = gt._slots()
set_date(SUN)
slots_c = gt._slots()
ok("D10 _slots: מספר הקבועים בתור לפי התאריך (תחזית ≠ השבוע הנוכחי)", slots_f[1] != slots_c[1] or slots_f[1] == 2,
   f"forecast={slots_f} current={slots_c}")
seen = {}
class _Spy:
    def __init__(self, *a, **k):
        seen.update(k)
    def exec(self):
        return QDialog.DialogCode.Rejected
_orig_man, _orig_ot = gu._ManualAddDialog, gu.OneTimePickerDialog
gu._ManualAddDialog = gu.OneTimePickerDialog = _Spy
try:
    # (18/10/2026) בתחזית שני הדיאלוגים נחסמים לגמרי — הבחירות הידניות הן הגדרה אחת של הרשימה
    # האמיתית (ראו D14); ה-on_date של הדיאלוגים נשמר לשלב 2 (בחירות פר-שבוע)
    set_date(W1); seen.clear(); gt._add_manual()
    ok("D10 _add_manual בתחזית: נחסם — הדיאלוג לא נפתח", seen == {}, str(seen))
    seen.clear(); gt._open_one_time_picker()
    ok("D10 בחירת חד-פעמיים בתחזית: נחסמת — הדיאלוג לא נפתח", seen == {}, str(seen))
    set_date(SUN); seen.clear(); gt._add_manual()
    ok("D10 בשבוע הנוכחי on_date=None (בלי שינוי)", seen.get("on_date") is None and "on_date" in seen, str(seen))
finally:
    gu._ManualAddDialog, gu.OneTimePickerDialog = _orig_man, _orig_ot
dlg = gu._ManualAddDialog(None, exclude_ids=set(), on_date=W1)
ok("D10 _ManualAddDialog: הרביעי של התחזית ('לא בתור' נמדד מולו)", dlg._base_wed == W1, str(dlg._base_wed))
dlg2 = gu._ManualAddDialog(None, exclude_ids=set())
ok("D10 _ManualAddDialog בלי תאריך: הרביעי הקרוב האמיתי", dlg2._base_wed == W0, str(dlg2._base_wed))
db.add_recipient({"full_name": "חד-א", "status": "פעיל", "frequency": "חד-פעמי", "priority": 3, "souls": 4,
                  "phone1": "0501234567"})
otd = gu.OneTimePickerDialog(None, on_date=W1)
ok("D10 OneTimePickerDialog נבנה בתחזית (רשימת חד-פעמיים לפי התאריך)", len(otd._rows) >= 1 and otd._on_date == W1,
   str(len(otd._rows)))

# ── 11. צינתוקים: רשימה ריקה בתחזית; חוזרת כשחוזרים לתאריך הקרוב ────────────────────────
set_date(SUN); gt.refresh(); gt._needs_refresh = False
tz._load_week_list()
ok("D11 צינתוקים בשבוע הנוכחי: יש נמענים ברשימה", len(tz._distribution_rows()) >= 1,
   str(len(tz._distribution_rows())))
set_date(W1)
ok("D11 בתחזית: מקור הרשימה ריק", tz._distribution_rows() == [])
tz.refresh()
ok("D11 בתחזית: הטבלה ריקה, ואזהרה מוצגת בבאנר", tz._rows == [] and not tz.week_frame.isHidden()
   and "שבוע עתידי" in tz.lbl_week.text() and "החזר אותו לתאריך של החלוקה הקרובה" in tz.lbl_week.text(),
   tz.lbl_week.text())
tz._list_loaded = False; tz.refresh()
ok("D11 בתחזית: הכרטיסייה 'טען את הרשימה' מסבירה במקום למנות משפחות",
   "שבוע עתידי" in tz.lbl_tile_week.text() and "משפחות ברשימה" not in tz.lbl_tile_week.text(),
   tz.lbl_tile_week.text())
ok("D11 קמפיין מתויג תמיד לרביעי הקרוב האמיתי", tz._dist_date_iso() == db.next_wednesday().isoformat())
set_date(SUN)
tz._load_week_list()
ok("D11 חזרה לתאריך הקרוב: הרשימה חוזרת והבאנר רגיל", len(tz._rows) >= 1 and "שבוע עתידי" not in tz.lbl_week.text()
   and tz.lbl_week.text().startswith("📋"), f"{len(tz._rows)} / {tz.lbl_week.text()}")
tz._list_loaded = False; tz.refresh()
ok("D11 הכרטיסייה חזרה למנות משפחות", "שבוע עתידי" not in tz.lbl_tile_week.text(), tz.lbl_tile_week.text())

# ── 12. מיילים: הרשימה והתאריך של התחזית (לא נשבר) ───────────────────────────────────
ml._mode = ml.MODE_CURRENT
set_date(W1)
src = {r.get("full_name") for r in ml._source_recs()}
ok("D12 מיילים 'רשימת החלוקה הנוכחית' = הרשימה העתידית, והתאריך = התאריך שבמסך",
   src == names(gt.week_rows()) and ml._dist_iso() == W1.isoformat(), f"{sorted(src)} / {ml._dist_iso()}")
set_date(SUN)
ok("D12 בשבוע הנוכחי התאריך = התאריך שבמסך", ml._dist_iso() == SUN.isoformat())

# ── 13. כל יום בשבוע כ"היום": הכלל זהה, וגם התחזית שונה מהשבוע הנוכחי ──────────────────────
for off in range(7):
    t = SUN + timedelta(days=off)
    set_today(t)
    real_wed = t if t.weekday() == 2 else selection.next_wednesday(t)
    set_date(t); a = gt._list_date()
    set_date(t + timedelta(days=7)); b = gt._list_date()
    set_date(t - timedelta(days=7)); c = gt._list_date()
    ok(f"D13 [היום יום {t.weekday()}, רביעי קרוב {real_wed}]: היום — לא תחזית; בעוד שבוע — תחזית; לפני שבוע — לא",
       a is None and b == t + timedelta(days=7) and c is None, f"{a} / {b} / {c}")
set_today(SUN)

# תרחיש נוסף ביום שישי: הרביעי הקרוב 28/10, חלוקה רגילה נרשמה ברביעי 21/10 (שבוע שעבר)
FRI = D(2026, 10, 23)
set_today(FRI)
ids2 = setup_week(W0.isoformat())
set_date(FRI); gt.refresh()
cur = names(gt._rows_data)
set_date(D(2026, 10, 30))                         # שישי הבא ⇒ הרביעי 4/11
fut = names(gt._rows_data)
ok("D13b יום שישי: הרשימה הנוכחית (28/10) — השבועי והחדש; הדו-שבועי והחודשי עוד לא",
   cur == {"ק-שבועי", "ק-חדש"}, str(sorted(cur)))
ok("D13b ... ובתחזית ל-4/11 גם הדו-שבועי (התור שלו הגיע), עדיין לא החודשי",
   fut == {"ק-שבועי", "ק-דו-שבועי", "ק-חדש"} and gt.list_is_future(), str(sorted(fut)))
set_date(FRI)
ok("D13b חזרה ליום שישי: התחזית נעלמה והרשימה חזרה", gt.lbl_future_note.isHidden() and names(gt._rows_data) == cur)

# ── 14. בחירות ידניות (חד-פעמיים / הוספה / הסרה 🗑) הן הגדרה אחת של הרשימה האמיתית ─────────
# בתחזית הן נחסמות (אחרת יידלפו לרשימת השבוע ולמחשב השני — עד שבשלב 2 לכל שבוע יהיו בחירות משלו)
set_today(SUN)
setup_week(SUN.isoformat()); set_date(SUN); gt.refresh()
_dialogs = []
_orig_exec = QDialog.exec
QDialog.exec = lambda self, *a, **k: (_dialogs.append(type(self).__name__), QDialog.DialogCode.Rejected)[1]
try:
    set_date(W1); gt.refresh()
    ok("D14 בתחזית: זו תחזית", gt.list_is_future())
    _row = next(iter(gt._rows_data), None)
    _before = set(gt._removed_ids)
    if _row is not None:
        gt._remove_from_list(_row)
    ok("D14 בתחזית: הסרה (🗑) נחסמת — לא נרשמת", gt._removed_ids == _before, str(gt._removed_ids))
    gt._open_one_time_picker(); gt._add_manual()
    ok("D14 בתחזית: 'בחר חד-פעמיים' ו'הוסף מקבל' לא פותחים דיאלוג", _dialogs == [], str(_dialogs))
    db.set_setting("weekly_extra_ids", "keep-me")
    gt._extra_ids = {ids["ק-שבועי"]}
    gt._persist_extras()
    ok("D14 בתחזית: _persist_extras לא כותבת את ההגדרה האמיתית", db.get_setting("weekly_extra_ids") == "keep-me",
       db.get_setting("weekly_extra_ids"))
    gt._extra_ids = set()
    set_date(SUN); gt.refresh()                       # חזרה לשבוע האמיתי: הכל עובד
    ok("D14 חזרה לשבוע האמיתי: הוספה ידנית פותחת דיאלוג", (gt._add_manual(), _dialogs)[1] == ["_ManualAddDialog"], str(_dialogs))
    _row2 = next(iter(gt._rows_data), None)
    if _row2 is not None:
        gt._remove_from_list(_row2)
    ok("D14 חזרה לשבוע האמיתי: הסרה (🗑) עובדת", _row2 is None or _row2.get("id") in gt._removed_ids)
finally:
    QDialog.exec = _orig_exec
    db.set_setting("weekly_extra_ids", "")

# ── 15. שער 'בחר חד-פעמיים' (חוסם הדפסה כשנשארו מנות פנויות) לא חוסם הדפסת תחזית ──────────
# בתחזית אי אפשר לבחור חד-פעמיים (D14), ולכן השער לא היה ניתן לסיפוק והדפסה מראש הייתה נתקעת
set_today(SUN)
setup_week(SUN.isoformat()); db.set_setting("available_products", "50"); db.set_setting("dist_regulars_mode", "schedule")
set_date(SUN); gt.refresh()
ok("D15 שבוע נוכחי עם מנות פנויות וללא בחירה: השער חוסם (כמו תמיד)",
   gt._one_time_remainder() > 0 and gt._one_time_gate_ok("הדפסה") is False)
set_date(W1); gt.refresh()
ok("D15 תחזית: השער לא חוסם הדפסה", gt.list_is_future() and gt._one_time_gate_ok("הדפסה") is True)
set_date(SUN); gt.refresh()

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL DATE-FOLLOW CHECKS PASS ✓")
sys.exit(1 if fails else 0)

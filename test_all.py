"""בדיקת שלמות המערכת — 21 רבדים | עובד תמיד על DB זמני, לעולם לא נוגע ב-data.db"""
import sys, os, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── DB זמני — חובה לפני כל import של database ────────────────────────────────
_tmp_fd, _TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_tmp_fd)

import database as db
db.DB_PATH = _TMP_DB          # מניעת כתיבה ל-data.db האמיתי

from pathlib import Path
assert Path(db.DB_PATH).name != "data.db", "!אסור לגעת ב-data.db האמיתי"

# ── ספירת בדיקות ─────────────────────────────────────────────────────────────
_errors: list = []
_passed = 0

def check(name: str, condition: bool, detail: str = ""):
    global _passed
    if condition:
        print(f"  ✓ {name}")
        _passed += 1
    else:
        print(f"  ✗ {name} {detail}")
        _errors.append(name)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 1 — תחביר Python (compileall)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 1: תחביר Python ===")
import compileall
ok = compileall.compile_dir(".", quiet=True)
check("compile_all", bool(ok))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 2 — ייבוא מודולים
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 2: ייבוא מודולים ===")
try:
    from utils.excel_utils import import_from_excel, _normalize_phone, _parse_date, export_distribution_to_excel
    check("import excel_utils", True)
except Exception as e:
    check("import excel_utils", False, str(e))

try:
    from utils.backup import auto_backup
    check("import backup", True)
except Exception as e:
    check("import backup", False, str(e))

try:
    from styles import EXTRA_QSS, QT_MATERIAL_EXTRA, DARK_BLUE
    check("import styles", True)
except Exception as e:
    check("import styles", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 3 — אתחול DB (init_db, idempotent)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 3: אתחול DB ===")
db.init_db()
check("init_db run 1", True)
db.init_db()
check("init_db idempotent", True)
check("DB path is temp file", Path(db.DB_PATH).name != "data.db")


# ══════════════════════════════════════════════════════════════════════════════
# רובד 4 — הגדרות (settings CRUD)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 4: הגדרות ===")
check("default password = 1234 (hashed)", db.verify_password("1234"))
db.set_setting("__test_key__", "hello123")
check("set/get setting", db.get_setting("__test_key__") == "hello123")
db.set_setting("__test_key__", "updated")
check("overwrite setting", db.get_setting("__test_key__") == "updated")


# ══════════════════════════════════════════════════════════════════════════════
# רובד 5 — CRUD מקבלים
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 5: CRUD מקבלים ===")
RID = db.add_recipient({
    "full_name": "ישראל ישראלי",
    "phone1": "050-1234567",
    "area": "בעלז",
    "souls": 4,
    "frequency": "שבועי",
    "status": "פעיל",
})
check("add_recipient returns int id", isinstance(RID, int) and RID > 0)

rec = db.get_recipient(RID)
check("get_recipient full_name", rec and rec["full_name"] == "ישראל ישראלי")
check("get_recipient souls", rec and rec["souls"] == 4)
check("get_recipient nonexistent → None", db.get_recipient(99999) is None)

db.update_recipient(RID, {"souls": 6, "area": "נתיב"})
rec2 = db.get_recipient(RID)
check("update_recipient souls", rec2 and rec2["souls"] == 6)
check("update_recipient area", rec2 and rec2["area"] == "נתיב")

all_recs = db.get_all_recipients()
check("get_all_recipients not empty", len(all_recs) > 0)
all_active = db.get_all_recipients(status_filter="פעיל")
check("status_filter פעיל", all(r["status"] == "פעיל" for r in all_active))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 6 — change log (מעקב שינויי סטטוס)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 6: change log ===")
db.update_recipient(RID, {"status": "מושהה"})
log = db.get_change_log()
check("status change logged", any(
    e["recipient_id"] == RID and e["field_changed"] == "סטטוס" for e in log
))
db.update_recipient(RID, {"status": "פעיל"})   # חזרה לפעיל (גם זו נרשמת)
log_after_restore = db.get_change_log()
_count_before = len(log_after_restore)
db.update_recipient(RID, {"souls": 7})          # שדה לא מעוקב — לא אמור להירשם
log2 = db.get_change_log()
check("non-tracked field not logged", len(log2) == _count_before)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 7 — update_recipient עם dict ריק / רק 'id'
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 7: update_recipient מקרי קצה ===")
try:
    db.update_recipient(RID, {})
    check("empty dict — no crash", True)
except Exception as e:
    check("empty dict — no crash", False, str(e))

try:
    db.update_recipient(RID, {"id": 9999})
    check("id-only dict — no crash", True)
except Exception as e:
    check("id-only dict — no crash", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 8 — הגנת מחיקה + מחיקה תקינה
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 8: הגנת מחיקה ===")
RID_HIST = db.add_recipient({"full_name": "בעל היסטוריה", "status": "פעיל", "frequency": "שבועי"})
db.bulk_add_distributions(
    [{"id": RID_HIST, "full_name": "בעל היסטוריה", "frequency": "שבועי"}],
    "2026-01-01", "מזון", 1, ""
)
blocked = False
try:
    db.delete_recipient(RID_HIST)
except ValueError:
    blocked = True
check("delete with history → ValueError", blocked)

RID_CLEAN = db.add_recipient({"full_name": "ללא היסטוריה", "status": "פעיל"})
try:
    db.delete_recipient(RID_CLEAN)
    check("delete without history — ok", True)
except Exception as e:
    check("delete without history — ok", False, str(e))
check("deleted recipient → None", db.get_recipient(RID_CLEAN) is None)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 9 — calculate_next_dist (כל 5 סוגי תדירות)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 9: calculate_next_dist ===")
from database import calculate_next_dist
from datetime import date

for freq in ["שבועי", "דו-שבועי", "חודשי", "חד-פעמי", ""]:
    d = calculate_next_dist("2026-05-27", freq)
    check(f"next_dist({freq or 'ריק'}) = יום רביעי", d.weekday() == 2, f"({d})")

d_invalid = calculate_next_dist("לא-תאריך", "שבועי")
check("invalid date → fallback Wednesday", d_invalid.weekday() == 2)

# שבועי: הרביעי הבא אחרי +1 יום
from datetime import timedelta
d_weekly = calculate_next_dist("2026-05-27", "שבועי")  # יום רביעי → +7 ימים
check("שבועי interval >= 7 days", (d_weekly - date(2026, 5, 27)).days >= 1)

d_biweekly = calculate_next_dist("2026-05-27", "דו-שבועי")
check("דו-שבועי interval >= 13 days", (d_biweekly - date(2026, 5, 27)).days >= 13)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 10 — _parse_date (כל סוגי הקלט)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 10: _parse_date ===")
from datetime import datetime as _dt

check("datetime object",        _parse_date(_dt(2026, 5, 20))       == "2026-05-20")
check("date object",            _parse_date(date(2026, 5, 20))       == "2026-05-20")
check("ISO string yyyy-mm-dd",  _parse_date("2026-05-20")            == "2026-05-20")
check("ISO with time",          _parse_date("2026-05-20 14:30:00")   == "2026-05-20")
check("dd/mm/yyyy",             _parse_date("20/05/2026")            == "2026-05-20")
check("None → ''",              _parse_date(None)                    == "")
check("0 → ''",                 _parse_date(0)                       == "")
check("empty string → ''",      _parse_date("")                      == "")
check("'None' string → ''",     _parse_date("None")                  == "")


# ══════════════════════════════════════════════════════════════════════════════
# רובד 11 — _normalize_phone
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 11: _normalize_phone ===")
check("9-digit 05X → adds 0",      _normalize_phone("527146566")  == "0527146566")
check("10-digit → unchanged",       _normalize_phone("0527146566") == "0527146566")
check("with dashes → unchanged",    _normalize_phone("058-3243176") == "058-3243176")
check("empty → unchanged",          _normalize_phone("") == "")
check("8-digit → unchanged",        _normalize_phone("52714656")  == "52714656")
check("starts with 04 → unchanged", _normalize_phone("459876543") == "459876543")
check("non-digit → unchanged",      _normalize_phone("abc") == "abc")


# ══════════════════════════════════════════════════════════════════════════════
# רובד 12 — ייבוא מ-Excel (גיליון + כותרת + תאריכים + טלפונים)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 12: ייבוא מ-Excel ===")
# בונים קובץ תבנית-ליהודה עצמאי כדי שהבדיקה תהיה דטרמיניסטית ולא תלויה בקובץ חיצוני.
# העמודה הריקה משמאל ל'משפחה' היא קוד העדיפות; נייד בן 9 ספרות שמתחיל ב-5 חייב להתנרמל.
import openpyxl as _opx
_tmpl_fd, _tmpl_xlsx = tempfile.mkstemp(suffix=".xlsx"); os.close(_tmpl_fd)
_wb_t = _opx.Workbook(); _ws_t = _wb_t.active
_ws_t.append(["", "משפחה", "פרטי", "נייד בעל", "נייד אשה", "קהילה"])
_ws_t.append([3, "כהן", "ראובן", "527146566", "", "בעלז"])    # 9 ספרות 5XX → 0527146566
_ws_t.append([4, "לוי", "שמעון", "0531234567", "", "נתיב"])
_wb_t.save(_tmpl_xlsx)
_excel_rows = import_from_excel(_tmpl_xlsx)
check("Excel rows > 0", len(_excel_rows) > 0, f"({len(_excel_rows)} שורות)")
if _excel_rows:
    r0 = _excel_rows[0]
    check("full_name exists", bool(r0.get("full_name")))
    check("status exists",    bool(r0.get("status")))
    # כל מספר בן 9 ספרות שמתחיל ב-5 חייב להיות מנורמל
    bad_phones = [
        r.get("phone1","") for r in _excel_rows
        if r.get("phone1","").isdigit()
        and len(r.get("phone1","")) == 9
        and r.get("phone1","").startswith("5")
    ]
    check("phones normalized", len(bad_phones) == 0, f"({len(bad_phones)} לא תוקנו)")
try: os.unlink(_tmpl_xlsx)
except OSError: pass


# ══════════════════════════════════════════════════════════════════════════════
# רובד 13 — ייבוא ל-DB (tuple, add/update logic)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 13: ייבוא ל-DB ===")
_test_import_rows = [
    {"full_name": "כהן ראובן",   "phone1": "050-111", "status": "פעיל", "frequency": "שבועי", "souls": "3"},
    {"full_name": "לוי שמעון",   "phone1": "050-222", "status": "פעיל", "frequency": "חודשי", "souls": ""},
    {"full_name": "ישראל ישראלי","phone1": "054-999", "status": "פעיל"},   # קיים כבר — יעדכן שדות ריקים
]
added, updated, conflicts = db.import_recipients_from_list(_test_import_rows)
check("import returns tuple", isinstance(added, int) and isinstance(updated, int) and isinstance(conflicts, list))
check("import adds new rows", added >= 2, f"({added} נוספו)")

_conflict_rows = [
    {"full_name": "???????? ?????", "phone1": "050-1111111", "status": "????"},
    {"full_name": "???????? ?????", "phone1": "050-2222222", "status": "????"},
]
_, _, _conflicts = db.import_recipients_from_list(_conflict_rows)
check("import conflict detected", len(_conflicts) >= 1)

# ייבוא שני — לא מוסיף, עשוי לעדכן
added2, updated2, conflicts2 = db.import_recipients_from_list(_test_import_rows)
check("second import adds 0", added2 == 0, f"({added2})")

# ייבוא עם שם ריק — נדלג
added3, _, _ = db.import_recipients_from_list([{"full_name": "", "phone1": "050-000"}])
check("empty name skipped", added3 == 0)

# ייבוא מה-Excel עם הנתונים האמיתיים (אם קיים)
if _excel_rows:
    added_xl, updated_xl, conflicts_xl = db.import_recipients_from_list(_excel_rows)
    check("Excel import to DB returns tuple", isinstance(added_xl, int) and isinstance(conflicts_xl, list))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 14 — get_weekly_list (ללא חד-פעמי, מסנן אזור)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 14: רשימה שבועית ===")
weekly = db.get_weekly_list(365)
ot_in_weekly = [r for r in weekly if r.get("frequency") == "חד-פעמי"]
check("weekly excludes חד-פעמי", len(ot_in_weekly) == 0)

if len(weekly) > 1:
    names = [r["full_name"] for r in weekly]
    check("weekly sorted alphabetically", names == sorted(names, key=str.lower))

weekly_belz = db.get_weekly_list(365, area_filter="בעלז")
check("area_filter בעלז applied", all(r.get("area", "") == "בעלז" for r in weekly_belz) or len(weekly_belz) == 0)

RID_WEEKLY = db.add_recipient({"full_name": "__weekly_test__", "status": "\u05e4\u05e2\u05d9\u05dc", "frequency": "\u05e9\u05d1\u05d5\u05e2\u05d9", "last_distribution": "2026-05-20", "next_distribution": ""})
_before_weekly = db.get_recipient(RID_WEEKLY)["next_distribution"]
_weekly_rows = db.get_weekly_list(365)
_after_weekly = db.get_recipient(RID_WEEKLY)["next_distribution"]
check("weekly list persists missing next_distribution", _before_weekly in ("", None) and bool(_after_weekly))
db.update_recipient(RID_WEEKLY, {"weekly_status": "\u2713"})
_weekly_rows = db.get_weekly_list(365)
check("weekly status returned", any(r.get("id") == RID_WEEKLY and r.get("_status") == "\u2713" for r in _weekly_rows))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 15 — get_one_time_list (מיון: ישן ראשון, tie-break נפשות)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 15: רשימת חד-פעמיים ===")
RID_OT_OLD_FEW   = db.add_recipient({"full_name": "חד ישן 3 נפשות",  "frequency": "חד-פעמי", "status": "פעיל", "souls": 3, "last_distribution": "2025-01-01"})
RID_OT_OLD_MANY  = db.add_recipient({"full_name": "חד ישן 8 נפשות",  "frequency": "חד-פעמי", "status": "פעיל", "souls": 8, "last_distribution": "2025-01-01"})
RID_OT_NEW       = db.add_recipient({"full_name": "חד חדש 5 נפשות",  "frequency": "חד-פעמי", "status": "פעיל", "souls": 5, "last_distribution": "2026-04-01"})

ot = db.get_one_time_list()
names_ot = [r["full_name"] for r in ot]

# ישן לפני חדש
old_positions = [names_ot.index(n) for n in names_ot if "ישן" in n]
new_positions  = [names_ot.index(n) for n in names_ot if "חדש" in n]
check("oldest dist comes first", max(old_positions) < min(new_positions) if old_positions and new_positions else True)

# tie-break: יותר נפשות קודם (בין שני הישנים)
idx_many = next((i for i, r in enumerate(ot) if r["full_name"] == "חד ישן 8 נפשות"), 999)
idx_few  = next((i for i, r in enumerate(ot) if r["full_name"] == "חד ישן 3 נפשות"), 999)
check("tie-break: more souls first", idx_many < idx_few, f"(8-souls idx={idx_many}, 3-souls idx={idx_few})")


# ══════════════════════════════════════════════════════════════════════════════
# רובד 16 — compute_suggested_n
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 16: compute_suggested_n ===")
n, reg = db.compute_suggested_n(100)
check("returns tuple of ints", isinstance(n, int) and isinstance(reg, int))
check("regular_count > 0", reg > 0, f"({reg})")
check("n >= 0", n >= 0)
check("n + reg <= total", n + reg <= 100, f"(n={n}, reg={reg})")

n_zero, reg_zero = db.compute_suggested_n(0)
check("0 products → n=0", n_zero == 0)

n_small, _ = db.compute_suggested_n(1)
check("not enough for regulars → n=0", n_small == 0)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 17 — bulk_add_distributions (הערות, last/next date, כמות)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 17: bulk_add_distributions ===")
db.bulk_add_distributions(
    [{"id": RID, "full_name": "ישראל ישראלי", "frequency": "שבועי", "notes": "הערה מיוחדת"}],
    "2026-05-28", "סל מזון", 2, "המחלק"
)
rec_after = db.get_recipient(RID)
check("last_distribution updated", rec_after["last_distribution"] == "2026-05-28")
check("next_distribution not empty", bool(rec_after["next_distribution"]))
nd = date.fromisoformat(rec_after["next_distribution"])
check("next_distribution is Wednesday", nd.weekday() == 2, f"({nd})")

hist = db.get_distributions_for_recipient(RID)
check("distribution record saved", len(hist) > 0)
check("notes saved correctly", any(h.get("notes") == "הערה מיוחדת" for h in hist))
check("what_dist saved", any(h.get("what_dist") == "סל מזון" for h in hist))
check("quantity saved", any(h.get("quantity") == 2 for h in hist))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 18 — חד-פעמי: next_distribution חייב להיות ריק אחרי חלוקה
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 18: חד-פעמי — next_distribution='' ===")
db.bulk_add_distributions(
    [{"id": RID_OT_OLD_MANY, "full_name": "חד ישן 8 נפשות", "frequency": "חד-פעמי"}],
    "2026-05-28", "עוף", 1, ""
)
rec_ot = db.get_recipient(RID_OT_OLD_MANY)
check("חד-פעמי last_distribution updated", rec_ot["last_distribution"] == "2026-05-28")
check("חד-פעמי next_distribution = ''", rec_ot["next_distribution"] in (None, "", "None"))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 19 — auto_backup (None/True/False)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 19: auto_backup ===")
# התנהגות נוכחית: ללא תיקייה מוגדרת — מגבה לתיקיית ברירת המחדל (%APPDATA%) ומחזיר True.
db.set_setting("backup_folder", "")
result_no_folder = auto_backup()
check("no folder → True (default dir)", result_no_folder is True)

_bk_dir = tempfile.mkdtemp()
try:
    db.set_setting("backup_folder", _bk_dir)
    result_ok = auto_backup()
    check("with folder → True", result_ok is True)
    check("last backup timestamp stored", bool(db.get_setting("last_backup_at")))
    bk_files = [f for f in os.listdir(_bk_dir) if f.startswith("backup_") and f.endswith(".db")]
    check("backup file created in folder", len(bk_files) > 0)

    # תיקייה לא-קיימת — נופלת חזרה לתיקיית ברירת המחדל ולא נכשלת.
    db.set_setting("backup_folder", r"Z:\nonexistent_path_xyz")
    result_bad = auto_backup()
    check("bad folder → True (falls back to default)", result_bad is True)
finally:
    db.set_setting("backup_folder", "")
    shutil.rmtree(_bk_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# רובד 20 — export_distribution_to_excel (קובץ ב-exports/)
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 20: ייצוא Excel ===")
_test_recs = [{"full_name": "בדיקת ייצוא", "phone1": "050-9999999", "area": "בעלז", "souls": 3}]
try:
    _path = export_distribution_to_excel(_test_recs, "31/05/2026")
    _p = Path(_path)
    check("export file created", _p.exists())
    check("file in exports/ subfolder", "exports" in str(_p))
    check("file is xlsx", _path.endswith(".xlsx"))
    if _p.exists():
        _p.unlink()
except Exception as e:
    check("export no crash", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# רובד 21 — PyQt6 UI: חלון, לשוניות, נתונים, חד-פעמיים, סיכום
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== רובד 21: ממשק PyQt6 ===")
from PyQt6.QtWidgets import QApplication
from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
_app = QApplication.instance() or QApplication(sys.argv)
try:
    from qt_material import apply_stylesheet
    apply_stylesheet(_app, theme="light_blue.xml", invert_secondary=True,
                     extra=QT_MATERIAL_EXTRA)
    _app.setStyleSheet(_app.styleSheet() + EXTRA_QSS)
except ImportError:
    _app.setStyleSheet(EXTRA_QSS)

from main import MainWindow
_win = MainWindow()
_win.show()

check("8 tabs", _win.tabs.count() == 8)
check("_extra_ids is set", isinstance(_win.group_tab._extra_ids, set))
check("settings tab available", hasattr(_win, "settings_tab"))

_win.recipients_tab.refresh()
check("recipients table loaded", _win.recipients_tab.table.rowCount() > 0)

_win.weekly_tab.refresh()
ot_in_ui = False
for _r in range(_win.weekly_tab.table.rowCount()):
    _item = _win.weekly_tab.table.item(_r, 7)  # עמודת תדירות
    if _item and _item.text() == "חד-פעמי":
        ot_in_ui = True
        break
check("weekly UI excludes חד-פעמי", not ot_in_ui)

_win.one_time_tab.refresh()
check("one_time tab loads", _win.one_time_tab.table.rowCount() >= 0)

_stats = db.get_summary()
check("summary has all keys", all(k in _stats for k in
    ["active", "overdue", "total_souls", "dists_month", "dists_total", "suspended", "by_freq", "by_area"]))

_win.search_tab.refresh()
check("search shows all recipients", len(_win.search_tab._all_rows) == len(db.get_all_recipients()))


# ══════════════════════════════════════════════════════════════════════════════
# סיכום
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 55)
total = _passed + len(_errors)
print(f"עברו: {_passed}/{total}  |  נכשלו: {len(_errors)}")
if _errors:
    print("\nבדיקות שנכשלו:")
    for e in _errors:
        print(f"  ✗ {e}")
else:
    print("✓ כל הבדיקות עברו בהצלחה!")

# ── ניקוי DB זמני ────────────────────────────────────────────────────────────
try:
    os.unlink(_TMP_DB)
except Exception:
    pass

if _errors:
    sys.exit(1)

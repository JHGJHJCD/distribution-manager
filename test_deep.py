"""
בדיקות עומק — מקרים שtest_all.py לא מכסה:
  - גבולות חישוב תאריך (רביעי ביום רביעי עצמו)
  - migration של DB ישן (עמודת weekly_status)
  - דיוק נתוני סיכום
  - מחיקה כוללת עם cascade
  - רוטציית גיבויים (מגבלת 30)
  - תאימות unicode / עברית עם ניקוד
  - ביצועי DB עם 200 רשומות
  - גיבוי WAL integrity (לאחר תיקון)
  - שמירת הגדרות בין חיבורים
  - ייצוא Excel — שם קובץ + תוכן
"""
import sys, os, tempfile, shutil, sqlite3, time
sys.stdout.reconfigure(encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# DB זמני
_tmp_fd, _TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_tmp_fd)
import database as db
db.DB_PATH = _TMP_DB
from pathlib import Path
assert Path(db.DB_PATH).name != "data.db"

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


# ══════════════════════════════════════════════════
# רובד A — גבולות חישוב תאריך
# ══════════════════════════════════════════════════
print("\n=== A: גבולות חישוב תאריך ===")
from database import calculate_next_dist, next_wednesday
from datetime import date, timedelta

# כשהיום הוא רביעי — הרביעי הבא הוא +7 ימים (לא היום)
wed = date(2026, 6, 3)   # רביעי ידוע
assert wed.weekday() == 2
d = next_wednesday(wed)
check("next_wednesday(רביעי) → +7 (לא היום)", (d - wed).days == 7, f"got {d}")

# כשהיום הוא שלישי — הרביעי הבא הוא +1
tue = date(2026, 6, 2)
d2 = next_wednesday(tue)
check("next_wednesday(שלישי) → +1", (d2 - tue).days == 1, f"got {d2}")

# כשהיום הוא חמישי — הרביעי הבא הוא +6
thu = date(2026, 6, 4)
d3 = next_wednesday(thu)
check("next_wednesday(חמישי) → +6", (d3 - thu).days == 6, f"got {d3}")

# calculate_next_dist: שבועי מרביעי → רביעי הבא
d4 = calculate_next_dist("2026-06-03", "שבועי")   # מרביעי שבועי
check("שבועי מרביעי → +7", d4.weekday() == 2 and (d4 - wed).days == 7)

# calculate_next_dist: דו-שבועי
d5 = calculate_next_dist("2026-06-03", "דו-שבועי")
check("דו-שבועי ≥ +13 ימים", (d5 - wed).days >= 13)

# calculate_next_dist: חודשי
d6 = calculate_next_dist("2026-06-03", "חודשי")
check("חודשי = כל 4 שבועות (+28)", (d6 - wed).days == 28, f"got {d6}")

# calculate_next_dist: חד-פעמי → רביעי הקרוב מהיום (לא מתאריך ניתן)
d7 = calculate_next_dist("2026-06-03", "חד-פעמי")
check("חד-פעמי → רביעי הקרוב מהיום", d7.weekday() == 2)

# חלוקה שנרשמה באיחור (חמישי–שבת אחרי רביעי) שייכת למחזור של אותו רביעי —
# אסור שתדחה את התור הבא בשבוע שלם (דו-שבועי הפך ל-3 שבועות, תלת-שבועי ל-4).
for _late in ("2026-06-04", "2026-06-05", "2026-06-06"):   # חמישי / שישי / שבת
    check(f"שבועי שנרשם באיחור ({_late}) → רביעי 10/06",
          calculate_next_dist(_late, "שבועי") == date(2026, 6, 10))
    check(f"דו-שבועי שנרשם באיחור ({_late}) → רביעי 17/06",
          calculate_next_dist(_late, "דו-שבועי") == date(2026, 6, 17),
          f"got {calculate_next_dist(_late, 'דו-שבועי')}")
    check(f"תלת-שבועי שנרשם באיחור ({_late}) → רביעי 24/06",
          calculate_next_dist(_late, "תלת-שבועי") == date(2026, 6, 24),
          f"got {calculate_next_dist(_late, 'תלת-שבועי')}")
    check(f"חודשי שנרשם באיחור ({_late}) → כמו מרביעי",
          calculate_next_dist(_late, "חודשי") == d6,
          f"got {calculate_next_dist(_late, 'חודשי')}")
# ראשון–שלישי לפני החלוקה: ההתנהגות הקיימת נשמרת (לא משתנה בתיקון)
check("דו-שבועי מיום שלישי → רביעי שאחרי שבועיים",
      calculate_next_dist("2026-06-02", "דו-שבועי") == date(2026, 6, 17))
check("שבועי מיום ראשון → רביעי הקרוב (חלוקה מיוחדת לא מבטלת את רביעי)",
      calculate_next_dist("2026-05-31", "שבועי") == date(2026, 6, 3))

# ── A2: דו-שבועי שקיבל שבוע שעבר לא חוזר לרשימת השבוע — גם אם החלוקה נרשמה
#        באיחור (חמישי/שישי/ראשון). זו הייתה תקלה חמורה: חלון "6 ימים אחורה"
#        גרר את כל מקבלי השבוע שעבר (דו-שבועי/חודשי) חזרה לרשימה השבוע. ─────────
from datetime import timedelta as _td
_a2_prev = db.DB_PATH                       # רץ על DB מבודד כדי לא לזהם רבדים אחרים
_a2_fd, _a2_db = tempfile.mkstemp(suffix=".db"); os.close(_a2_fd)
db.DB_PATH = _a2_db
db.init_db()
_today = date.today()
_base_wed = _today if _today.weekday() == 2 else next_wednesday(_today)
_last_wed = _base_wed - _td(days=7)
def _mk_bw(name):
    return db.add_recipient({"full_name": name, "status": "פעיל", "souls": 3,
                             "frequency": "דו-שבועי", "priority": 4})
def _serve(rid, name, d):
    db.bulk_add_distributions(
        [{"id": rid, "full_name": name, "frequency": "דו-שבועי", "souls": 3, "area": ""}],
        d.isoformat(), "", 1, "בודק", dist_name="A2")
# (ראשון–שלישי = חלוקה נוספת, לא איחור — הכרעת יהודה 25/9/2026; נבדק ב-D3)
for _off, _lbl in ((0, "רביעי"), (1, "חמישי"), (3, "שבת")):
    _n = f"דושב-שבוע-שעבר-{_lbl}"
    _r = _mk_bw(_n)
    _serve(_r, _n, _last_wed + _td(days=_off))
    _wk = {x["full_name"] for x in db.get_weekly_list()}
    check(f"דו-שבועי שקיבל שבוע שעבר ({_lbl}) לא ברשימת השבוע", _n not in _wk,
          f"appears; next={db.get_recipient(_r)['next_distribution']}")
# מנגד: מקבל שקיבל את מחזור השבוע (רביעי הקרוב) כן נשאר ברשימה — כדי שלא ייעלם
# מיד אחרי הרישום ואפשר עדיין לתת לו סבב נוסף.
_wn = "דושב-השבוע"
_wr = _mk_bw(_wn)
_serve(_wr, _wn, _base_wed)
check("דו-שבועי שקיבל את מחזור השבוע כן נשאר ברשימת השבוע",
      _wn in {x["full_name"] for x in db.get_weekly_list()})
db.DB_PATH = _a2_prev                        # החזרת ה-DB המשותף לרבדים הבאים
try:
    os.remove(_a2_db)
except OSError:
    pass

# ══════════════════════════════════════════════════
# רובד B — Migration: DB ישן בלי עמודת weekly_status
# ══════════════════════════════════════════════════
print("\n=== B: Migration DB ישן ===")
fd2, old_db = tempfile.mkstemp(suffix=".db"); os.close(fd2)
old_conn = sqlite3.connect(old_db)
old_conn.executescript("""
    CREATE TABLE recipients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        status TEXT DEFAULT 'פעיל',
        frequency TEXT DEFAULT '',
        last_distribution TEXT,
        next_distribution TEXT,
        phone1 TEXT, phone2 TEXT, phone3 TEXT,
        address TEXT, area TEXT DEFAULT '',
        souls INTEGER DEFAULT 0,
        start_date TEXT, notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
    INSERT INTO settings VALUES ('password', '1234');
    INSERT INTO settings VALUES ('backup_folder', '');
    INSERT INTO settings VALUES ('last_backup_at', '');
    INSERT INTO recipients (full_name, status) VALUES ('ישן', 'פעיל');
""")
old_conn.close()

# הפעל init_db על DB ישן → צריך להוסיף weekly_status
orig_path = db.DB_PATH
db.DB_PATH = old_db
db.init_db()

_mc = sqlite3.connect(old_db)
cols = {r[1] for r in _mc.execute("PRAGMA table_info(recipients)")}  # col[1] = name
rows = _mc.execute("SELECT full_name FROM recipients").fetchall()
_mc.close()
check("weekly_status column added by migration", "weekly_status" in cols)
check("existing data preserved after migration", any(r[0] == "ישן" for r in rows))

db.DB_PATH = orig_path
try: os.unlink(old_db)
except PermissionError: pass   # WAL keeps file open on Windows


# ══════════════════════════════════════════════════
# רובד C — דיוק נתוני סיכום
# ══════════════════════════════════════════════════
print("\n=== C: דיוק נתוני סיכום ===")
db.init_db()

ids = []
for i in range(5):
    rid = db.add_recipient({"full_name": f"פעיל {i}", "status": "פעיל",
                            "frequency": "שבועי", "souls": i+1})
    ids.append(rid)

db.add_recipient({"full_name": "מושהה", "status": "מושהה", "souls": 10})
db.add_recipient({"full_name": "הסתיים", "status": "הסתיים", "souls": 10})

# הוסף חלוקה לשניים
db.bulk_add_distributions(
    [{"id": ids[0], "full_name": "פעיל 0", "frequency": "שבועי"},
     {"id": ids[1], "full_name": "פעיל 1", "frequency": "שבועי"}],
    "2026-06-01", "מזון", 1, ""
)

stats = db.get_summary()
check("active count = 5", stats["active"] == 5, f"got {stats['active']}")
check("suspended count = 1", stats["suspended"] == 1, f"got {stats['suspended']}")
check("ended count = 1", stats["ended"] == 1, f"got {stats['ended']}")
check("total_souls = 1+2+3+4+5 = 15", stats["total_souls"] == 15, f"got {stats['total_souls']}")
check("dists_total = 2", stats["dists_total"] == 2, f"got {stats['dists_total']}")


# ══════════════════════════════════════════════════
# רובד D — force_delete cascade מלא
# ══════════════════════════════════════════════════
print("\n=== D: force_delete cascade ===")
rid_del = db.add_recipient({"full_name": "למחיקה", "status": "פעיל", "frequency": "שבועי"})
db.bulk_add_distributions(
    [{"id": rid_del, "full_name": "למחיקה", "frequency": "שבועי"}],
    "2026-06-01", "עוף", 1, ""
)
db.update_recipient(rid_del, {"status": "מושהה"})  # יוצר change_log

conn_check = sqlite3.connect(db.DB_PATH)
dist_before = conn_check.execute(
    "SELECT COUNT(*) FROM distributions WHERE recipient_id=?", (rid_del,)).fetchone()[0]
log_before = conn_check.execute(
    "SELECT COUNT(*) FROM change_log WHERE recipient_id=?", (rid_del,)).fetchone()[0]
conn_check.close()

check("dist before force_delete > 0", dist_before > 0, f"({dist_before})")
check("change_log before force_delete > 0", log_before > 0, f"({log_before})")

db.force_delete_recipient(rid_del)

conn_check2 = sqlite3.connect(db.DB_PATH)
rec_after   = conn_check2.execute("SELECT id FROM recipients WHERE id=?", (rid_del,)).fetchone()
dist_after  = conn_check2.execute(
    "SELECT COUNT(*) FROM distributions WHERE recipient_id=?", (rid_del,)).fetchone()[0]
log_after   = conn_check2.execute(
    "SELECT COUNT(*) FROM change_log WHERE recipient_id=?", (rid_del,)).fetchone()[0]
conn_check2.close()

check("recipient deleted", rec_after is None)
check("distributions deleted", dist_after == 0, f"({dist_after} remain)")
check("change_log deleted", log_after == 0, f"({log_after} remain)")


# ══════════════════════════════════════════════════
# רובד D2 — רישום חלוקה ישנה בדיעבד לא מחזיר את "חלוקה אחרונה" אחורה
# ══════════════════════════════════════════════════
print("\n=== D2: רישום חלוקה בדיעבד ===")
rid_bd = db.add_recipient({"full_name": "בדיעבד", "status": "פעיל", "frequency": "דו-שבועי"})
_bd = [{"id": rid_bd, "full_name": "בדיעבד", "frequency": "דו-שבועי"}]
db.bulk_add_distributions(_bd, "2026-06-17", "עוף", 1, "")
db.bulk_add_distributions(_bd, "2026-06-03", "עוף", 1, "")   # נרשמה באיחור — חלוקה ישנה יותר
_r = db.get_recipient(rid_bd)
check("חלוקה אחרונה נשארת החדשה (17/06)", _r["last_distribution"] == "2026-06-17",
      f"got {_r['last_distribution']}")
check("חלוקה הבאה לפי החדשה (01/07)", _r["next_distribution"] == "2026-07-01",
      f"got {_r['next_distribution']}")

# D3 — חלוקה ביום א'–ג' = חלוקה נוספת (הכרעת יהודה 25/9/2026): לא מזיזה את התור הקבוע
rid_ex = db.add_recipient({"full_name": "נוספת", "status": "פעיל", "frequency": "דו-שבועי"})
_ex = [{"id": rid_ex, "full_name": "נוספת", "frequency": "דו-שבועי"}]
db.bulk_add_distributions(_ex, "2026-06-17", "עוף", 1, "")      # רביעי — חלוקה רגילה
db.bulk_add_distributions(_ex, "2026-06-21", "עוף", 1, "")      # ראשון — חלוקה נוספת
_r = db.get_recipient(rid_ex)
check("D3 חלוקה נוספת נשמרת כחלוקה אחרונה (21/06)", _r["last_distribution"] == "2026-06-21",
      f"got {_r['last_distribution']}")
check("D3 התור הקבוע לא זז — שבועיים מהרביעי (01/07)", _r["next_distribution"] == "2026-07-01",
      f"got {_r['next_distribution']}")
rid_ex2 = db.add_recipient({"full_name": "נוספת-ראשונה", "status": "פעיל", "frequency": "שבועי"})
db.bulk_add_distributions([{"id": rid_ex2, "full_name": "נוספת-ראשונה", "frequency": "שבועי"}],
                          (date.today() - timedelta(days=(date.today().weekday() + 1) % 7)).isoformat(),
                          "עוף", 1, "")
check("D3 קבוע שקיבל רק חלוקה נוספת — עדיין ברשימת הרביעי הקרוב",
      any(r["id"] == rid_ex2 for r in db.get_weekly_list()))

# D4 — תאריך ישן בפורמט "16/09/2026" מומר לבד בהפעלה (הכרעת יהודה 25/9/2026), אחרי גיבוי
_bk_prev = db.BACKUP_DIR
db.BACKUP_DIR = tempfile.mkdtemp()                 # לא לגעת בגיבויים האמיתיים
rid_lg = db.add_recipient({"full_name": "תאריך-ישן", "status": "פעיל", "frequency": "חודשי"})
db.bulk_add_distributions([{"id": rid_lg, "full_name": "תאריך-ישן", "frequency": "חודשי"}],
                          "2026-06-03", "עוף", 1, "")
_c = sqlite3.connect(db.DB_PATH)
_c.execute("UPDATE distributions SET dist_date='17/06/2026' WHERE recipient_id=?", (rid_lg,))
_c.execute("INSERT INTO distributions (recipient_id, recipient_name, dist_date, received) "
           "VALUES (?, 'תאריך-ישן', 'שטויות', 1)", (rid_lg,))
_c.commit(); _c.close()
db.init_db()
_c = sqlite3.connect(db.DB_PATH)
_dates = sorted(r[0] for r in _c.execute(
    "SELECT dist_date FROM distributions WHERE recipient_id=?", (rid_lg,)))
_c.close()
check("D4 '17/06/2026' הומר ל-2026-06-17 (וערך לא-תאריך לא נגע)",
      _dates == ["2026-06-17", "שטויות"], str(_dates))
_r = db.get_recipient(rid_lg)
check("D4 התור מחושב מהתאריך שהומר (חודשי → 15/07)",
      _r["last_distribution"] == "2026-06-17" and _r["next_distribution"] == "2026-07-15",
      f"{_r['last_distribution']} / {_r['next_distribution']}")
check("D4 נעשה גיבוי-ביטחון לפני ההמרה",
      any(n.startswith("safety_") for n in os.listdir(db.BACKUP_DIR)), str(os.listdir(db.BACKUP_DIR)))
db.BACKUP_DIR = _bk_prev

# חודשי שהתור שלו נשמר לפי הכלל הישן (5 שבועות) — מתקן את עצמו ונכנס לרשימה אחרי 4
_today = date.today()
_bw = _today if _today.weekday() == 2 else next_wednesday(_today)
rid_m = db.add_recipient({"full_name": "חודשי-ישן", "status": "פעיל", "frequency": "חודשי"})
_c = sqlite3.connect(db.DB_PATH)
_c.execute("UPDATE recipients SET last_distribution=?, next_distribution=? WHERE id=?",
           ((_bw - timedelta(days=28)).isoformat(), (_bw + timedelta(days=7)).isoformat(), rid_m))
_c.commit(); _c.close()
check("חודשי אחרי 4 שבועות ברשימת השבוע (תיקון-עצמי של תור ישן)",
      any(r["id"] == rid_m for r in db.get_weekly_list()))
check("התור התעדכן ב-DB", db.get_recipient(rid_m)["next_distribution"] == _bw.isoformat())


# ══════════════════════════════════════════════════
# רובד E — רוטציית גיבויים (מגבלת 30)
# ══════════════════════════════════════════════════
print("\n=== E: רוטציית גיבויים ===")
bk_dir = tempfile.mkdtemp()
db.set_setting("backup_folder", bk_dir)

from utils.backup import auto_backup

# צור 32 גיבויים רצופים
for i in range(32):
    time.sleep(0.02)   # הפרש זמן כדי לוודא שמות שונים
    auto_backup()

bk_files = sorted([f for f in os.listdir(bk_dir) if f.startswith("backup_")])
check("backup rotation keeps ≤30 files", len(bk_files) <= 30, f"({len(bk_files)} files)")
check("newest backup exists", len(bk_files) > 0)
db.set_setting("backup_folder", "")
shutil.rmtree(bk_dir, ignore_errors=True)


# ══════════════════════════════════════════════════
# רובד F — WAL Backup Integrity (לאחר תיקון)
# ══════════════════════════════════════════════════
print("\n=== F: WAL Backup Integrity ===")
fd3, wal_db = tempfile.mkstemp(suffix=".db"); os.close(fd3)
orig_path2 = db.DB_PATH
db.DB_PATH = wal_db
db.init_db()

# הוסף נתונים (ישבו ב-WAL לפני checkpoint)
wal_rid = db.add_recipient({"full_name": "WAL test", "souls": 7, "status": "פעיל"})
db.set_setting("last_backup_at", "")  # נקה

bk_dir2 = tempfile.mkdtemp()
db.set_setting("backup_folder", bk_dir2)
result = auto_backup()
check("WAL backup returns True", result is True)

bk_files2 = [f for f in os.listdir(bk_dir2) if f.startswith("backup_")]
if bk_files2:
    bk_path = os.path.join(bk_dir2, bk_files2[0])
    bk_conn = sqlite3.connect(bk_path)
    rows_bk = bk_conn.execute(
        "SELECT full_name, souls FROM recipients WHERE full_name='WAL test'").fetchall()
    bk_conn.close()
    check("WAL data in backup", len(rows_bk) == 1, f"({len(rows_bk)} rows)")
    check("WAL souls preserved", rows_bk[0][1] == 7 if rows_bk else False)
else:
    check("backup file created", False)

db.DB_PATH = orig_path2
shutil.rmtree(bk_dir2, ignore_errors=True)
try: os.unlink(wal_db)
except: pass


# ══════════════════════════════════════════════════
# רובד G — Unicode / עברית עם ניקוד ותווים מיוחדים
# ══════════════════════════════════════════════════
print("\n=== G: Unicode / עברית מיוחדת ===")
unicode_cases = [
    ("שָׁם עִם נִקּוּד", "050-1234567"),           # ניקוד
    ("Ó'Brien מקבל", "050-9876543"),              # Latin mixed
    ("מקבל עם 'גרשיים'", "052-1111111"),           # apostrophe
    ("אברהם    רבה", "053-2222222"),               # spaces
    ("🕍 ישראל", "054-3333333"),                   # emoji
]
for name, phone in unicode_cases:
    try:
        uid = db.add_recipient({"full_name": name, "phone1": phone, "status": "פעיל"})
        rec = db.get_recipient(uid)
        check(f"unicode name stored: {name[:12]}...", rec and rec["full_name"] == name)
    except Exception as e:
        check(f"unicode name stored: {name[:12]}...", False, str(e))

# חיפוש ב-get_all_recipients עם שם unicode
all_recs = db.get_all_recipients()
nikud_found = any("נִקּוּד" in r["full_name"] for r in all_recs)
check("ניקוד searchable in get_all_recipients", nikud_found)


# ══════════════════════════════════════════════════
# רובד H — ביצועי DB עם 200 רשומות
# ══════════════════════════════════════════════════
print("\n=== H: ביצועים עם 200 רשומות ===")
rows_to_add = [
    {"full_name": f"מקבל {i:03d}", "status": "פעיל",
     "frequency": ["שבועי","דו-שבועי","חודשי"][i % 3],
     "area": ["בעלז","נתיב",""][i % 3],
     "souls": (i % 5) + 1}
    for i in range(200)
]
t0 = time.perf_counter()
added, updated, conflicts = db.import_recipients_from_list(rows_to_add)
t1 = time.perf_counter()
check("200 rows imported", added == 200, f"({added})")
check("import 200 rows < 1 sec", (t1 - t0) < 1.0, f"({(t1-t0)*1000:.0f}ms)")

t2 = time.perf_counter()
all_r = db.get_all_recipients()
t3 = time.perf_counter()
check("get_all_recipients < 50ms", (t3 - t2) < 0.05, f"({(t3-t2)*1000:.0f}ms)")

t4 = time.perf_counter()
weekly = db.get_weekly_list(365)
t5 = time.perf_counter()
check("get_weekly_list < 100ms", (t5 - t4) < 0.1, f"({(t5-t4)*1000:.0f}ms)")
check("weekly list not empty", len(weekly) > 0, f"({len(weekly)})")


# ══════════════════════════════════════════════════
# רובד I — הגדרות שורדות חיבור חדש
# ══════════════════════════════════════════════════
print("\n=== I: הגדרות שורדות חיבור חדש ===")
db.set_setting("test_persist", "ערך_לשמירה")
# פתח חיבור חדש לאותו DB
conn_new = sqlite3.connect(db.DB_PATH)
conn_new.row_factory = sqlite3.Row
val = conn_new.execute("SELECT value FROM settings WHERE key='test_persist'").fetchone()
conn_new.close()
check("setting persists in new connection", val and val["value"] == "ערך_לשמירה")

# הגדרת סיסמא ברירת מחדל קיימת (מאוחסנת כ-hash PBKDF2, מאומתת דרך verify_password)
check("default password = 1234 persists", db.verify_password("1234"))


# ══════════════════════════════════════════════════
# רובד J — Excel Export: שם קובץ ותוכן
# ══════════════════════════════════════════════════
print("\n=== J: Excel Export קובץ ותוכן ===")
from utils.excel_utils import export_distribution_to_excel
import openpyxl

test_recs = [
    {"full_name": "כהן ראובן",  "phone1": "050-111", "area": "בעלז", "souls": 3},
    {"full_name": "לוי שמעון",  "phone1": "050-222", "area": "נתיב", "souls": 5},
]

path = export_distribution_to_excel(test_recs, "04/06/2026")
p = Path(path)
check("export file exists", p.exists())
check("filename has no spaces", " " not in p.name)
check("export saved to Downloads", "Downloads" in str(p) or "exports" in str(p))

# בדוק תוכן הקובץ
if p.exists():
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    # שורה 1 = כותרת, שורה 2 = header עמודות, שורות 3+ = נתונים
    names_in_file = [ws.cell(r, 2).value for r in range(3, ws.max_row + 1)]
    check("both names in Excel", "כהן ראובן" in names_in_file and "לוי שמעון" in names_in_file,
          f"found: {names_in_file}")
    p.unlink()


# ══════════════════════════════════════════════════
# רובד K — שמירת weekly_status ב-DB
# ══════════════════════════════════════════════════
print("\n=== K: שמירת weekly_status ===")
wrid = db.add_recipient({"full_name": "שבועי טסט", "status": "פעיל", "frequency": "שבועי"})
db.update_recipient(wrid, {"weekly_status": "✓"})
rec_w = db.get_recipient(wrid)
check("weekly_status saved", rec_w and rec_w["weekly_status"] == "✓",
      f"got {rec_w.get('weekly_status') if rec_w else 'None'}")

# אפס
db.update_recipient(wrid, {"weekly_status": ""})
rec_w2 = db.get_recipient(wrid)
check("weekly_status clearable", rec_w2 and rec_w2["weekly_status"] == "")

# בדוק שה-change_log לא רושם weekly_status (אינו שדה מעוקב)
log_before = len(db.get_change_log())
db.update_recipient(wrid, {"weekly_status": "✗"})
log_after = len(db.get_change_log())
check("weekly_status NOT logged in change_log", log_after == log_before)


# ══════════════════════════════════════════════════
# רובד L — get_one_time_list: מקבל ללא last_distribution
# ══════════════════════════════════════════════════
print("\n=== L: חד-פעמי ללא תאריך קודם ===")
ot1 = db.add_recipient({"full_name": "חד ללא תאריך", "frequency": "חד-פעמי",
                         "status": "פעיל", "souls": 3})
ot2 = db.add_recipient({"full_name": "חד עם תאריך",  "frequency": "חד-פעמי",
                         "status": "פעיל", "souls": 5, "last_distribution": "2025-01-01"})

ot_list = db.get_one_time_list()
ot_names = [r["full_name"] for r in ot_list]

check("both one-time appear", "חד ללא תאריך" in ot_names and "חד עם תאריך" in ot_names)

# ללא תאריך → date(2000,1,1) → הכי ישן → ראשון
idx_no_date   = next(i for i, r in enumerate(ot_list) if r["full_name"] == "חד ללא תאריך")
idx_with_date = next(i for i, r in enumerate(ot_list) if r["full_name"] == "חד עם תאריך")
check("no-date appears before 2025 date", idx_no_date < idx_with_date,
      f"idx_no={idx_no_date}, idx_with={idx_with_date}")


# ══════════════════════════════════════════════════
# רובד M — get_distributions filter by name
# ══════════════════════════════════════════════════
print("\n=== M: get_distributions לפי שם ===")
target_id = db.add_recipient({"full_name": "מטרה לסינון", "status": "פעיל", "frequency": "שבועי"})
other_id  = db.add_recipient({"full_name": "אחר לסינון",  "status": "פעיל", "frequency": "שבועי"})
db.bulk_add_distributions(
    [{"id": target_id, "full_name": "מטרה לסינון", "frequency": "שבועי"}],
    "2026-06-01", "מזון", 1, ""
)
db.bulk_add_distributions(
    [{"id": other_id, "full_name": "אחר לסינון", "frequency": "שבועי"}],
    "2026-06-01", "עוף", 2, ""
)

dists_target = db.get_distributions(recipient_name="מטרה לסינון")
dists_other  = db.get_distributions(recipient_name="אחר לסינון")

check("filter by name — target only", all(d["recipient_name"] == "מטרה לסינון" for d in dists_target))
check("filter by name — other only",  all(d["recipient_name"] == "אחר לסינון"  for d in dists_other))
check("no cross-contamination", len(dists_target) >= 1 and len(dists_other) >= 1)


# ══════════════════════════════════════════════════
# רובד N — משקלי ניקוד מתכווננים
# ══════════════════════════════════════════════════
print("\n=== N: משקלי ניקוד מתכווננים ===")
db.set_need_weights(db.DEFAULT_NEED_WEIGHTS)
_wd = db.get_need_weights()
check("default weights: money=34", _wd["money"] == 34.0, f"got {_wd['money']}")
check("default weights: financial fields 0", _wd["income"] == 0 and _wd["medical"] == 0)
check("default weights sum to 100", abs(sum(_wd.values()) - 100) < 0.01, f"sum={sum(_wd.values())}")
check("no separate children factor (avoids double-count with souls)", "children" not in _wd)
check("money parser '5,000 ₪' → 5000", db._need_num("5,000 ₪", "money") == 5000.0)
db.set_need_weights({"income": -3})
check("negative weight clamped to 0", db.get_need_weights()["income"] == 0.0)

# the chosen weight drives the ranking
db.reset_all_data()
db.add_recipient({"full_name": "גדולה", "frequency": "חד-פעמי", "status": "פעיל",
                  "priority": 3, "souls": 12, "income": "9000"})
db.add_recipient({"full_name": "עניה", "frequency": "חד-פעמי", "status": "פעיל",
                  "priority": 3, "souls": 3, "income": "1000"})
db.set_need_weights({"souls": 100, "money": 0, "recency": 0,
                     "income": 0, "housing": 0, "medical": 0})
check("souls-weighted → big family first", db.get_one_time_list()[0]["full_name"] == "גדולה")
db.set_need_weights({"income": 100, "souls": 0, "money": 0,
                     "recency": 0, "housing": 0, "medical": 0})
check("income-weighted → low income first", db.get_one_time_list()[0]["full_name"] == "עניה")
db.set_need_weights(db.DEFAULT_NEED_WEIGHTS)   # restore default


# ══════════════════════════════════════════════════
# רובד O — חוסן ופיצ'רים חדשים
# ══════════════════════════════════════════════════
print("\n=== O: חוסן ופיצ'רים ===")
from tabs.recipients import _priority_display
check("priority 4 → קבוע", _priority_display({"priority": 4}) == "קבוע")
check("priority 3 → ראשונה", _priority_display({"priority": 3}) == "ראשונה")
check("priority 1 → ריק", _priority_display({"priority": 1}) == "")
check("priority 0 → ריק", _priority_display({"priority": 0}) == "")

db.reset_all_data()
db.set_need_weights(db.DEFAULT_NEED_WEIGHTS)
db.add_recipient({"full_name": "חד A", "frequency": "חד-פעמי", "status": "פעיל",
                  "priority": 3, "souls": 8})
_ot = db.get_one_time_list()
_t = next((r for r in _ot if r["full_name"] == "חד A"), None)
check("one-time row carries _score_parts",
      _t is not None and isinstance(_t.get("_score_parts"), list) and len(_t["_score_parts"]) >= 1)

# bulk_add_distributions must tolerate a record without an 'id'
try:
    db.bulk_add_distributions([{"full_name": "ללא מזהה", "frequency": "חד-פעמי"}],
                              "2026-06-10", "סל", 1, "בודק")
    check("bulk_add_distributions tolerates missing id", True)
except Exception as e:
    check("bulk_add_distributions tolerates missing id", False, str(e))

# merge-import must tolerate a non-numeric 'souls' (no crash)
db.reset_all_data()
db.add_recipient({"full_name": "קיים", "status": "פעיל"})
try:
    db.import_recipients_from_list([{"full_name": "קיים", "souls": "לא-מספר"}])
    check("import tolerates bad souls (no crash)", True)
except Exception as e:
    check("import tolerates bad souls (no crash)", False, str(e))

# printed list splits reserve into its own marked section, after the main list
from utils.print_view import _build_html
_ph = _build_html([{"full_name": "עיקרי", "_reserve": False},
                   {"full_name": "רזרבה1", "_reserve": True}], "10/06/2026")
check("print: reserve section present", "רזרבה — לפי סדר עדיפות" in _ph)
check("print: main listed before reserve", _ph.index("עיקרי") < _ph.index("רזרבה1"))

# restore safety: refuse a non-DB file (don't clobber real data); accept a valid one
from utils.backup import restore_from_backup
db.reset_all_data()
db.add_recipient({"full_name": "סימן שחזור", "status": "פעיל"})
_bfd, _bad = tempfile.mkstemp(suffix=".db"); os.close(_bfd)
with open(_bad, "w", encoding="utf-8") as _bf:
    _bf.write("this is not a database")
check("restore refuses a non-DB file", restore_from_backup(_bad) is False)
check("data intact after refused restore",
      any(r["full_name"] == "סימן שחזור" for r in db.get_all_recipients()))
_gfd, _good = tempfile.mkstemp(suffix=".db"); os.close(_gfd)
_s = sqlite3.connect(db.DB_PATH); _d = sqlite3.connect(_good); _s.backup(_d); _d.close(); _s.close()
db.reset_all_data()
check("restore from a valid backup succeeds", restore_from_backup(_good) is True)
check("marker present after valid restore",
      any(r["full_name"] == "סימן שחזור" for r in db.get_all_recipients()))
for _f in (_bad, _good):
    try: os.unlink(_f)
    except OSError: pass

# settings weight helpers always normalise to a 100-sum (the auto-rebalance math)
from tabs.settings import SettingsTab
check("scale_to_100 already-100 stays 100", sum(SettingsTab._scale_to_100(
    {"a": 34, "b": 33, "c": 33, "d": 0}).values()) == 100)
check("scale_to_100 arbitrary → 100", sum(SettingsTab._scale_to_100(
    {"a": 7, "b": 3, "c": 90, "d": 50}).values()) == 100)
check("scale_to_100 all-zero → even 100", sum(SettingsTab._scale_to_100(
    {"a": 0, "b": 0, "c": 0}).values()) == 100)
check("even_split sums to total", sum(SettingsTab._even_split(100, ["a", "b", "c"]).values()) == 100)


# ══════════════════════════════════════════════════
# v3.60 — מקור אמת אחד לתאריכי החלוקה בכרטיס
# ══════════════════════════════════════════════════
_wed = date.today() if date.today().weekday() == 2 else next_wednesday(date.today())
_imported = (_wed - timedelta(days=7)).isoformat()
_sid = db.add_recipient({"full_name": "אמת מיובא", "phone1": "0507770001", "frequency": "שבועי",
                         "status": "פעיל", "priority": 4, "last_distribution": _imported})
check("S1 imported last kept + next derived on add",
      db.get_recipient(_sid)["last_distribution"] == _imported
      and db.get_recipient(_sid)["next_distribution"] == calculate_next_dist(_imported, "שבועי").isoformat())
_sb = db.bulk_add_distributions([db.get_recipient(_sid)], _wed.isoformat(), "", 1, "", dist_name="S")
db.delete_batch(_sb)
check("S2 deleting the only batch falls back to the imported date (not blank)",
      db.get_recipient(_sid)["last_distribution"] == _imported,
      str(db.get_recipient(_sid)["last_distribution"]))
db.bulk_add_distributions([db.get_recipient(_sid)], _wed.isoformat(), "", 1, "", dist_name="S")
db.update_recipient(_sid, {"frequency": "חודשי"})
check("S3 frequency change re-derives next_distribution",
      db.get_recipient(_sid)["next_distribution"] == calculate_next_dist(_wed.isoformat(), "חודשי").isoformat(),
      str(db.get_recipient(_sid)["next_distribution"]))
db.update_recipient(_sid, {"phone2": "0507770002", "last_distribution": _imported,
                           "next_distribution": "2020-01-01"})
check("S4 a stale date riding on a card edit can't roll the dates back",
      db.get_recipient(_sid)["last_distribution"] == _wed.isoformat()
      and db.get_recipient(_sid)["next_distribution"] == calculate_next_dist(_wed.isoformat(), "חודשי").isoformat())

# v3.61 — /בודק-באגים "מקור אמת אחד", סבב שני
import json as _json
_g = lambda i: db.get_recipient(i)
_h = db.add_recipient({"full_name": "אמת ישן", "phone1": "0507770003", "frequency": "דו-שבועי",
                       "status": "פעיל", "priority": 4})
db.bulk_add_distributions([_g(_h)], _wed.isoformat(), "", 1, "", dist_name="S5")
_stale = (_wed - timedelta(days=14)).isoformat()
with db.get_connection() as _c:
    _c.execute("UPDATE recipients SET last_distribution=?, next_distribution=? WHERE id=?",
               (_stale, _wed.isoformat(), _h))
db.init_db()
check("S5 a card left stale by an older version heals at startup",
      _g(_h)["last_distribution"] == _wed.isoformat()
      and _g(_h)["next_distribution"] == calculate_next_dist(_wed.isoformat(), "דו-שבועי").isoformat(),
      str(_g(_h)["last_distribution"]))
with db.get_connection() as _c:
    _c.execute("INSERT INTO distributions (recipient_id, recipient_name, dist_date, received) "
               "VALUES (?,?,?,1)", (_h, "אמת ישן", "26/08/2026"))
    db._recompute_recipient_dates(_c, _h)
check("S6 a junk (non-ISO) history date can't hide the real history",
      _g(_h)["last_distribution"] == _wed.isoformat(), repr(_g(_h)["last_distribution"]))
_n = db.add_recipient({"full_name": "אמת חדש", "phone1": "0507770004", "frequency": "שבועי",
                       "status": "פעיל", "priority": 4})
_n1 = _g(_n)["next_distribution"]
db.get_weekly_list()
_n2 = _g(_n)["next_distribution"]
db.update_recipient(_n, {"notes": "x"})
check("S7 never-served regular: same 'next' from add / weekly list / edit",
      _n1 == _n2 == _g(_n)["next_distribution"] == _wed.isoformat(), f"{_n1}/{_n2}")
_before = dict(_g(_sid))
_before["last_distribution"] = _imported          # what the card said back then
_before["last_dist_base"] = ""
with db.get_connection() as _c:
    _c.execute("UPDATE recipients SET last_dist_base='' WHERE id=?", (_sid,))
    _cur = _c.execute("INSERT INTO sync_incoming (op, target_guid, before_json) VALUES (?,?,?)",
                      ("rec_upsert", _before["guid"], _json.dumps(_before)))
    _inc = _cur.lastrowid
db.undo_incoming(_inc)
check("S9 undoing a peer's edit doesn't turn an old derived date into a base",
      (_g(_sid)["last_dist_base"] or "") == "" and _g(_sid)["last_distribution"] == _wed.isoformat(),
      repr(_g(_sid)["last_dist_base"]))
_log = []
_orig_log = db._sync_log
db._sync_log = lambda op, p: _log.append((op, (p.get("data") or {}).get("full_name")))
try:
    db.import_recipients_from_list([
        {"full_name": "אמת ממוזג", "frequency": "שבועי", "last_distribution": _imported},
        {"full_name": "אמת חדש", "address": "רחוב 1"}])
    _cnt = db.bulk_insert_recipients([{"full_name": "אמת מוחלף", "frequency": "שבועי",
                                       "last_distribution": _imported}])
finally:
    db._sync_log = _orig_log
_m = [r for r in db.get_all_recipients() if r["full_name"] == "אמת ממוזג"][0]
check("S10 merge-import: new card gets guid + stamp and both cards reach the other computer",
      bool(_m.get("guid")) and bool(_m.get("updated_at"))
      and ("rec_upsert", "אמת ממוזג") in _log and ("rec_upsert", "אמת חדש") in _log, str(_log))
_r = [r for r in db.get_all_recipients() if r["full_name"] == "אמת מוחלף"][0]
_rb = db.bulk_add_distributions([_r], _wed.isoformat(), "", 1, "", dist_name="S11")
db.delete_batch(_rb)
check("S11 replace-import keeps the Excel date as the base (survives a batch delete)",
      _g(_r["id"])["last_distribution"] == _imported, repr(_g(_r["id"])["last_distribution"]))


# ══════════════════════════════════════════════════
# CH — היסטוריית שינויים בכרטיס (v3.63, בקשת רון 22/9/2026)
# ══════════════════════════════════════════════════
print("\n=== CH: היסטוריית שינויים בכרטיס ===")
_ch_id = db.add_recipient({"full_name": "הלוי חיים", "phone1": "0501234567",
                           "income": "1000", "souls": 4, "priority": 4, "frequency": "שבועי"})
_ch_rec = db.get_recipient(_ch_id)
check("CH1 מקבל חדש — בלי היסטוריה (אין 'קודם')",
      db.get_changes_for_recipient(_ch_id, _ch_rec["guid"]) == [])
db.update_recipient(_ch_id, {"income": "2000", "souls": 4, "address": "רחוב א 5"})
_chs = db.get_changes_for_recipient(_ch_id, _ch_rec["guid"])
_by = {c["field"]: c for c in _chs}
check("CH2 הכנסה 1000→2000 נרשמה עם תווית עברית",
      _by.get("income", {}).get("old_value") == "1000" and _by["income"]["new_value"] == "2000"
      and _by["income"]["field_changed"] == "הכנסות", str(_by.get("income")))
check("CH3 כתובת ריקה→ערך נרשמה; נפשות ללא שינוי לא נרשמו",
      "address" in _by and "souls" not in _by and len(_chs) == 2, str(sorted(_by)))
check("CH4 לשורה יש guid/rec_guid/source=edit/changed_at",
      all(c["guid"] and c["rec_guid"] == _ch_rec["guid"] and c["source"] == "edit"
          and c["changed_at"] for c in _chs))
db.update_recipient(_ch_id, {"income": "2000 "})     # אותו ערך אחרי רווח — לא שינוי
check("CH5 ערך זהה (רווחים) לא נרשם", len(db.get_changes_for_recipient(_ch_id, _ch_rec["guid"])) == 2)
db.update_recipient(_ch_id, {"frequency": "חודשי"})   # מחשב מחדש next — נגזרים לא נרשמים
_chs = db.get_changes_for_recipient(_ch_id, _ch_rec["guid"])
check("CH6 תדירות נרשמה, תאריכי-חלוקה נגזרים לא",
      any(c["field"] == "frequency" for c in _chs)
      and not any(c["field"] in ("last_distribution", "next_distribution", "last_dist_base")
                  for c in _chs))
check("CH7 החדש ראשון (DESC) ו-limit עובד",
      db.get_changes_for_recipient(_ch_id, _ch_rec["guid"], limit=1)[0]["field"] == "frequency")
# ייבוא-מיזוג ממלא שדה ריק → נרשם עם source=import
_a, _u, _c = db.import_recipients_from_list(
    [{"full_name": "הלוי חיים", "phone1": "0501234567", "synagogue": "בית אל"}])
_imp = [c for c in db.get_changes_for_recipient(_ch_id, _ch_rec["guid"]) if c["source"] == "import"]
check("CH8 ייבוא-מיזוג רושם שינוי עם source=import",
      _u == 1 and len(_imp) == 1 and _imp[0]["field"] == "synagogue" and _imp[0]["old_value"] == "",
      f"updated={_u} imp={_imp}")
# מחיקה כפויה מנקה את ההיסטוריה (גם לפי guid)
db.force_delete_recipient(_ch_id)
check("CH9 מחיקה כפויה מנקה את ההיסטוריה",
      db.get_changes_for_recipient(_ch_id, _ch_rec["guid"]) == [])
# ייצוא אקסל של מקבל בודד — גיליון שלישי
_x_id = db.add_recipient({"full_name": "אקסל בדיקה", "phone1": "0509999999", "income": "5"})
db.update_recipient(_x_id, {"income": "6"})
_xr = db.get_recipient(_x_id)
from utils.excel_utils import export_single_recipient_to_excel as _exp1
_xp = _exp1(_xr, [], db.get_changes_for_recipient(_x_id, _xr["guid"]))
_xwb = openpyxl.load_workbook(_xp)
check("CH10 ייצוא מקבל בודד כולל גיליון 'היסטוריית שינויים'",
      "היסטוריית שינויים" in _xwb.sheetnames
      and _xwb["היסטוריית שינויים"].cell(2, 3).value == "5"
      and _xwb["היסטוריית שינויים"].cell(2, 4).value == "6", str(_xwb.sheetnames))
try: os.unlink(_xp)
except OSError: pass


# ══════════════════════════════════════════════════
# IM: ייבוא-מיזוג מאקסל (diff_incoming_recipients / apply_import_confirmed)
# ══════════════════════════════════════════════════
import utils.excel_utils as _xu, openpyxl as _opx, pathlib as _pl
_im_dir = tempfile.mkdtemp()
_orig_dl, _orig_ed = _xu._downloads_dir, _xu.export_dir
_xu._downloads_dir = lambda: _pl.Path(_im_dir)
_xu.export_dir = lambda kind="": _pl.Path(_im_dir)
try:
    _im_id = db.add_recipient({"full_name": "ייבוא כהן", "phone1": "0521234567", "souls": 7,
                               "frequency": "שבועי", "status": "פעיל", "children_home": 5,
                               "children_total": 8, "children_married": 3})
    _im_path = _xu.export_recipients_to_excel([db.get_recipient(_im_id)])
    _wb = _opx.load_workbook(_im_path); _ws = _wb.active
    _hr = next(r for r in range(1, 10) if any(_ws.cell(r, c).value == "שם מלא" for c in range(1, 60)))
    for _c in range(1, _ws.max_column + 1):
        if _ws.cell(_hr, _c).value in ("מספר ילדים", "ילדים נשואים", "ילדים בבית", "נפשות"):
            _ws.cell(_hr + 1, _c).value = None
    _wb.save(_im_path)
    _d = db.diff_incoming_recipients(_xu.import_from_excel(_im_path))
    check("IM1 blank number cells in the file do not propose zeroing souls/children",
          _d["updates"] == [], str(_d["updates"]))
finally:
    _xu._downloads_dir, _xu.export_dir = _orig_dl, _orig_ed
    shutil.rmtree(_im_dir, ignore_errors=True)

_d = db.diff_incoming_recipients([{"full_name": "ייבוא כהן", "address": "הרצל 5"},
                                  {"full_name": "ייבוא לוי", "phone1": "0501111111"},
                                  {"full_name": "ייבוא לוי", "phone1": "0501111111", "address": "גפן 2"}])
db.apply_import_confirmed(_d["new"], [{"id": u["id"], "changes": u["changes"]} for u in _d["updates"]])
_im_ch = db.get_changes_for_recipient(_im_id, db.get_recipient(_im_id)["guid"])
check("IM2 merge-import history is tagged 'ייבוא מאקסל' (source=import), not 'עריכה'",
      [c["source"] for c in _im_ch if c["field"] == "address"] == ["import"],
      str([(c["field"], c["source"]) for c in _im_ch]))
_im_levi = [r for r in db.get_all_recipients() if r["full_name"] == "ייבוא לוי"]
check("IM3 the same new person twice in one file → ONE card (details merged)",
      len(_im_levi) == 1 and _im_levi[0]["address"] == "גפן 2", str([(r["id"], r["address"]) for r in _im_levi]))


# ══════════════════════════════════════════════════
# סיכום
# ══════════════════════════════════════════════════
print()
print("=" * 55)
total = _passed + len(_errors)
print(f"עברו: {_passed}/{total}  |  נכשלו: {len(_errors)}")
if _errors:
    print("\nנכשלו:")
    for e in _errors:
        print(f"  ✗ {e}")
else:
    print("✓ כל הבדיקות עברו בהצלחה!")

try: os.unlink(_TMP_DB)
except: pass

if _errors:
    sys.exit(1)

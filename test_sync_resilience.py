# -*- coding: utf-8 -*-
"""עמידות הסנכרון (6/10/2026) — הסיבות שבגללן הסנכרון "מת" אצל יהודה ואיך הן נסגרות.

DB זמני בלבד (לעולם לא ה-DB/מצב-הסנכרון האמיתי ב-APPDATA; גם הדמיית "מצב אמיתי" נעשית על תיקייה זמנית).
  • מספר הסידור (seq) לא יכול לרדת מתחת למה שכבר פורסם (דריסת sync_state.json ב-27/9 → המחשב השני זרק הכול)
  • סקריפט/בדיקה זרים לא נוגעים במצב הסנכרון האמיתי
  • נעילת מסד חולפת לא בולעת רשומה לצמיתות; ושגיאה ישנה מתנקה אחרי סבב תקין
  • גוגל דרייב: גרסה נכונה (מספרית), הפעלה מחדש עם ניסיון חוזר, תיקון רישום-הפעלה ישן, אות כונן שהשתנה
"""
import os, sys, json, tempfile, shutil, sqlite3, glob
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

import database as db
from utils import sync

fails = []


def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


root = tempfile.mkdtemp(prefix="sync_resil_")
dir_a = os.path.join(root, "pc_a"); os.makedirs(dir_a)
dir_b = os.path.join(root, "pc_b"); os.makedirs(dir_b)
shared = os.path.join(root, "drive"); os.makedirs(shared)
_real_data_dir = db._data_dir


def use_machine(d):
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")


def jsonl_lines(path):
    try:
        return [json.loads(x) for x in open(path, "r", encoding="utf-8").read().splitlines() if x.strip()]
    except OSError:
        return []


# ═══ 1. מספר הסידור לא יורד אחורה ═════════════════════════════════════════════
use_machine(dir_a)
db.init_db()
db.add_recipient({"full_name": "ישראל כהן", "phone1": "0501111111", "frequency": "שבועי", "priority": 4})
sync.enable_sync(shared, seed=True)
own = sync._journal_path(sync.device_id())
with open(own, "a", encoding="utf-8") as f:       # מה שכבר פורסם בעבר: seq גבוה
    f.write(json.dumps({"seq": 2547, "ts": "2026-08-27T18:11:39+00:00", "dev": sync.device_id(),
                        "op": "setting", "key": "x", "value": "1"}) + "\n")
st = sync._load_state(); st["seq"] = 802; sync._save_state(st)          # ← דריסת המצב
new = sync.repair_seq(force=True)
ok("seq שנדרס (802) מתוקן לפי היומן המשותף (2547)", new == 2547 and sync._load_state()["seq"] == 2547, str(new))
sync.log_change("setting", {"key": "probe_seq", "value": "1"})
last = jsonl_lines(own)[-1]
ok("הרשומה החדשה אחרי התיקון מקבלת seq גבוה מהמפורסם", last.get("seq") == 2548, str(last.get("seq")))

# גם התור המקומי (outbox) נספר
st = sync._load_state(); st["seq"] = 802; sync._save_state(st)
with open(sync._outbox_path(), "w", encoding="utf-8") as f:
    f.write(json.dumps({"seq": 4970, "ts": "x", "dev": "d", "op": "setting", "key": "k", "value": "v"}) + "\n")
ok("seq מתוקן גם לפי מה שמחכה בתור המקומי", sync.repair_seq(force=True) == 4970)
os.remove(sync._outbox_path())
ok("שום שינוי כשהמונה כבר תקין", sync.repair_seq(force=True) == 0)
sync._seq_checked = None
st = sync._load_state(); st["seq"] = 10; sync._save_state(st)
res = sync.run_sync()
ok("run_sync מתקן seq בעצמו בסבב הראשון", sync._load_state()["seq"] >= 2548 and not res["error"],
   str(sync._load_state()["seq"]))

# ═══ 2. סקריפט זר לא נוגע במצב-הסנכרון האמיתי ═════════════════════════════════
fake_real = os.path.join(root, "real_appdata"); os.makedirs(fake_real)
db._data_dir = lambda: fake_real                      # "המצב האמיתי" = תיקייה זמנית
try:
    db.DB_PATH = os.path.join(fake_real, "data.db")
    db.BACKUP_DIR = os.path.join(fake_real, "backups")
    sync._save_state({"folder": shared, "enabled": True, "device_id": "realdev00001", "seq": 4970})
    before = open(sync._state_path(), "rb").read()
    old_argv, old_frozen = sys.argv, getattr(sys, "frozen", None)
    sys.argv = ["some_test.py"]
    ok("זיהוי: תהליך זר על המצב האמיתי", sync._foreign_on_real_state())
    sync.log_change("rec_upsert", {"guid": "g1", "data": {"full_name": "בדיקה כהן"}})
    ok("log_change זר: לא נכתב תור ולא נגע במצב",
       not os.path.exists(sync._outbox_path()) and open(sync._state_path(), "rb").read() == before)
    ok("flush/pull/compact/enable/disable/restart זרים — לא עושים כלום",
       sync.flush() == 0 and sync.pull_changes() == 0 and sync.compact_journal() == 0
       and sync.enable_sync(shared, seed=True) == 0 and sync.restart_from_peer() == 0
       and (sync.disable_sync() or True) and open(sync._state_path(), "rb").read() == before
       and sync.repair_seq(force=True) == 0)
    sys.argv = ["main.py"]
    ok("`python main.py` = האפליקציה עצמה (מותר)", not sync._foreign_on_real_state())
    sys.argv = ["some_test.py"]; sys.frozen = True
    ok("EXE מקומפל = האפליקציה עצמה (מותר)", not sync._foreign_on_real_state())
    del sys.frozen
    os.environ["MANHAL_ALLOW_REAL_SYNC"] = "1"
    ok("תיקון ידני מכוון (משתנה סביבה) מותר", not sync._foreign_on_real_state())
    del os.environ["MANHAL_ALLOW_REAL_SYNC"]
    sys.argv = old_argv
    if old_frozen is not None:
        sys.frozen = old_frozen
finally:
    db._data_dir = _real_data_dir
use_machine(dir_a)
ok("מכונה מדומה (תיקייה זמנית) אינה 'המצב האמיתי' — הבדיקות הרגילות לא נחסמות",
   not sync._foreign_on_real_state())

# ═══ 3. נעילת מסד חולפת / ניקוי שגיאה ═════════════════════════════════════════
use_machine(dir_a)
db.add_recipient({"full_name": "לוי יעקב", "phone1": "0502222222", "frequency": "שבועי", "priority": 4})
sync.snapshot()
sync.flush()
use_machine(dir_b)
db.init_db()
sync.enable_sync(shared, seed=False)
orig = sync._APPLIERS["rec_upsert"]


def locked(conn, rec):
    raise sqlite3.OperationalError("database is locked")


sync._APPLIERS["rec_upsert"] = locked
res = sync.run_sync()
st = sync._load_state()
ok("נעילה חולפת: הסבב נעצר (לא בולע) ונרשמת שגיאה", "locked" in (res["error"] or "") and st.get("last_error"))
ok("נעילה חולפת: מיקום הקריאה לא התקדם — הרשומות ייקראו שוב", not st.get("offsets") and not st.get("applied"))
ok("נעילה חולפת: דבר לא נקלט למסד", len(db.get_all_recipients()) == 0)


def bad(conn, rec):
    raise ValueError("רשומה פגומה")


sync._APPLIERS["rec_upsert"] = bad
res = sync.run_sync()
ok("רשומה פגומה (לא נעילה) לא עוצרת את הזרם — כמו קודם", not res["error"])
sync._APPLIERS["rec_upsert"] = orig
# התקנה מחדש של היסטוגרמה כדי לקרוא שוב את אותם שורות (הפגומה כבר "נצרכה" — התנהגות קיימת)
st = sync._load_state(); st["applied"] = {}; st["offsets"] = {}; st["epochs"] = {}; st["last_error"] = "ישנה"
sync._save_state(st)
res = sync.run_sync()
ok("סבב תקין מנקה שגיאה ישנה (הנורית לא נשארת אדומה)", sync._load_state().get("last_error") == "")
ok("אחרי הנעילה הרשומות נקלטות", len(db.get_all_recipients()) == 2, str(len(db.get_all_recipients())))

# ═══ 4. גוגל דרייב ════════════════════════════════════════════════════════════
fake_pf = os.path.join(root, "pf", "Drive File Stream"); os.makedirs(fake_pf)
for sub in ("99.0.1.0", "131.0.2.0", "Drivers", "130.0.2.0"):
    os.makedirs(os.path.join(fake_pf, sub))
    if sub != "Drivers":
        open(os.path.join(fake_pf, sub, "GoogleDriveFS.exe"), "w").close()
exe = sync._find_drive_exe([fake_pf])
ok("הגרסה החדשה לפי מספרים (131 ולא 99 ולא 'Drivers')", exe.endswith(os.path.join("131.0.2.0", "GoogleDriveFS.exe")), exe)
os.remove(os.path.join(fake_pf, "131.0.2.0", "GoogleDriveFS.exe"))
ok("הגרסה הישנה נבחרת רק כשהחדשה נעלמה", sync._find_drive_exe([fake_pf]).endswith(os.path.join("130.0.2.0", "GoogleDriveFS.exe")))
ok("תיקיית 'Drivers' לא נבחרת בטעות כגרסה", sync._version_key("Drivers") is None and sync._version_key("131.0.2.0") == (131, 0, 2, 0))
ok("חילוץ נתיב מפקודת Run",
   sync._exe_from_command('"C:\\Program Files\\G\\131.0.2.0\\GoogleDriveFS.exe" --startup_mode').endswith("GoogleDriveFS.exe")
   and sync._exe_from_command("C:\\x\\a.exe /s") == "C:\\x\\a.exe" and sync._exe_from_command("") == "")

if sys.platform == "win32":
    import winreg
    key_path = r"Software\ManhalHalukaTest_%d" % os.getpid()
    good_exe = os.path.join(fake_pf, "130.0.2.0", "GoogleDriveFS.exe")
    try:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(k, "GoogleDriveFS", 0, winreg.REG_SZ,
                          '"C:\\Program Files\\Google\\Drive File Stream\\130.0.2.0-gone\\GoogleDriveFS.exe" --startup_mode')
        ok("רישום-הפעלה שמצביע על גרסה שנמחקה — מתוקן", sync.ensure_drive_autostart(key_path, exe=good_exe) == "fixed")
        val = winreg.QueryValueEx(k, "GoogleDriveFS")[0]
        ok("הערך החדש כמו שדרייב רושם את עצמו", val == f'"{good_exe}" --startup_mode', val)
        ok("רישום תקין לא נוגעים בו", sync.ensure_drive_autostart(key_path, exe=good_exe) == "")
        winreg.DeleteValue(k, "GoogleDriveFS")

        def _has_value():
            try:
                winreg.QueryValueEx(k, "GoogleDriveFS")
                return True
            except FileNotFoundError:
                return False

        ok("אין רישום בכלל = המשתמש כיבה, לא מוסיפים",
           sync.ensure_drive_autostart(key_path, exe=good_exe) == "" and not _has_value())
        winreg.CloseKey(k)
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass

    # הפעלה מחדש עם ניסיון חוזר
    launches = []

    class _P:
        def __init__(self, cmd, **kw):
            launches.append(cmd)

    real_popen, real_detect, real_running, real_find = (sync.subprocess.Popen, sync.detect_drive_folders,
                                                        sync.drive_running, sync._find_drive_exe)
    try:
        sync.subprocess.Popen = _P
        sync.detect_drive_folders = lambda: []
        sync.drive_running = lambda: False
        sync._find_drive_exe = lambda roots=None: "C:\\fake\\GoogleDriveFS.exe"
        sync._drive_last_try = 0.0
        sync.ensure_drive_running()
        ok("דרייב לא רץ ואין כונן: מופעל (עם --startup_mode)", launches == [["C:\\fake\\GoogleDriveFS.exe", "--startup_mode"]], str(launches))
        sync.ensure_drive_running()
        ok("לא מפעילים שוב תוך הזמן שנקבע (בלי הצפת חלונות)", len(launches) == 1)
        sync._drive_last_try -= sync.DRIVE_RETRY_S + 1
        sync.ensure_drive_running()
        ok("אחרי הזמן שנקבע — ניסיון חוזר (לא פעם אחת לכל ההפעלה)", len(launches) == 2)
        sync.drive_running = lambda: True
        sync.ensure_drive_running(force=True)
        ok("דרייב כבר רץ (אולי עוד מתחבר) — לא מפעילים עותק שני", len(launches) == 2)
        sync.drive_running = lambda: False
        sync.detect_drive_folders = lambda: ["G:\\האחסון שלי"]
        ok("הכונן כבר מחובר — לא עושים כלום ומחזירים True", sync.ensure_drive_running(force=True) is True and len(launches) == 2)
    finally:
        sync.subprocess.Popen, sync.detect_drive_folders, sync.drive_running, sync._find_drive_exe = (
            real_popen, real_detect, real_running, real_find)

# אות הכונן השתנה (G: → H:)
use_machine(dir_a)
new_root = os.path.join(root, "H_drive", "האחסון שלי")
new_shared = os.path.join(new_root, "מנהל חלוקה סינכרון"); os.makedirs(new_shared)
open(os.path.join(new_shared, "journal-abc123.jsonl"), "w").close()
old_folder = os.path.join(root, "gone_drive", "האחסון שלי", "מנהל חלוקה סינכרון").replace("\\", "/")
st = sync._load_state()
st["folder"] = old_folder          # a path that cannot exist here (NOT the real G: of this PC)
st["enabled"] = True
sync._save_state(st)
real_detect = sync.detect_drive_folders
try:
    sync.detect_drive_folders = lambda: [new_root]
    sync._heal_last = 0.0
    ok("הנתיב השמור לא קיים (G: נעלם)", not os.path.isdir(sync.get_folder()))
    ok("folder_available מוצא את אותה תיקייה תחת הכונן החדש", sync.folder_available())
    ok("הנתיב השמור עודכן (בסגנון הקודם עם / )", sync.get_folder() == new_shared.replace("\\", "/"), sync.get_folder())
    # תיקייה דומה בלי יומנים / שתי מועמדות — לא מאמצים
    st = sync._load_state(); st["folder"] = old_folder; sync._save_state(st)
    os.remove(os.path.join(new_shared, "journal-abc123.jsonl"))
    ok("תיקייה דומה בלי יומני סנכרון — לא מאמצים", not sync.heal_folder(force=True)
       and sync.get_folder() == old_folder)
    open(os.path.join(new_shared, "journal-abc123.jsonl"), "w").close()
    other = os.path.join(root, "I_drive", "האחסון שלי", "מנהל חלוקה סינכרון"); os.makedirs(other)
    open(os.path.join(other, "journal-zzz999.jsonl"), "w").close()
    sync.detect_drive_folders = lambda: [new_root, os.path.join(root, "I_drive", "האחסון שלי")]
    ok("שתי מועמדות — לא ניחוש, לא מאמצים", not sync.heal_folder(force=True) and sync.get_folder() == old_folder)
    ok("נתיב מחוץ ל'האחסון שלי' לא מתוקן", sync._rel_inside_my_drive("D:/Backups/x") == ""
       and sync._rel_inside_my_drive("G:/My Drive/a/b") == os.path.join("a", "b"))
finally:
    sync.detect_drive_folders = real_detect

print()
shutil.rmtree(root, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL SYNC-RESILIENCE TESTS PASSED")
sys.exit(0)

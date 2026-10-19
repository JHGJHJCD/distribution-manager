# -*- coding: utf-8 -*-
"""הכנה קדימה, נעילה — סנכרון בין שני מחשבים (Y1–Y12 של docs/plans/הכנה_קדימה_נעילה.md, סעיף 7.3).

כמו test_sync.py: שני מחשבים מדומים (שני DB זמניים) שחולקים תיקיית "דרייב" אחת. הנעילה היא מפתח
אחד בהגדרות (`planned_dist:<רביעי>`) שנוסע ב-op `setting` הקיים — אין op חדש, ולכן גרסה ישנה
במחשב השני שומרת את המפתח בשקט ומכבדת אותו מיד כשתתעדכן. הרצה: python test_plan_sync.py"""
import os, sys, json, tempfile, time
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")
from datetime import date, timedelta

import database as db
import selection
from utils import sync

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


D = date.fromisoformat
TODAY = D("2026-10-18")
W1, W2, W3 = D("2026-10-21"), D("2026-10-28"), D("2026-11-04")
root = tempfile.mkdtemp(prefix="plan_sync_")
dirs = {n: os.path.join(root, n) for n in ("a", "b", "c", "d")}
for p in dirs.values():
    os.makedirs(p)
shared = os.path.join(root, "drive"); os.makedirs(shared)


def use(name):
    db.DB_PATH = os.path.join(dirs[name], "data.db")
    db.BACKUP_DIR = os.path.join(dirs[name], "backups")


def raw(wed):
    with db.get_connection() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (db.PLAN_PREFIX + wed.isoformat(),)).fetchone()
    return r["value"] if r else None


def P(wed, guids, **kw):
    return {"week_wed": wed, "members": [{"g": g, "role": "main", "kind": "reg"} for g in guids],
            "products": 9, "reserve": 0, **kw}


def sync_all(*names):
    for n in names:
        use(n)
        sync.run_sync()


# ── מחשב A: נתונים + סנכרון; מחשב B מצטרף ─────────────────────────────────────────
use("a"); db.init_db()
rid = {}
for key, name, freq in (("m", "חודשי", "חודשי"), ("b", "דו שבועי", "דו-שבועי"), ("z", "שבועי", "שבועי")):
    rid[key] = db.add_recipient({"full_name": name, "phone1": "05" + str(abs(hash(name)) % 10**8).zfill(8),
                                 "status": "פעיל", "frequency": freq, "priority": 4, "souls": 3})
g = {k: db.get_recipient(v)["guid"] for k, v in rid.items()}
sync.enable_sync(shared, seed=True)
use("b"); db.init_db(); sync.enable_sync(shared, seed=True); sync.run_sync()
ok("הכנה: B קיבל את שלושת המקבלים עם אותם guid", {r["guid"] for r in db.get_all_recipients()} == set(g.values()))

# ── Y1 — נעילה מ-A מגיעה ל-B, ואותה חסימה ברשימות ────────────────────────────────
use("a")
db.save_plan(P(W1, [g["m"], g["b"]], note="מ-A"))
sync_all("a", "b")                                   # a דוחף, b מושך
use("b")
ok("Y1a B רואה את הנעילה עם אותם חברים", db.get_plan(W1) is not None
   and [m["g"] for m in db.get_plan(W1)["members"]] == [g["m"], g["b"]])
ok("Y1b אינדקס ה'תפוס' זהה בשני המחשבים", db.live_plan_index(TODAY) == {g["m"]: [W1], g["b"]: [W1]}
   and (use("a"), db.live_plan_index(TODAY) == {g["m"]: [W1], g["b"]: [W1]})[1])
use("b")
row_m = dict(db.get_recipient_by_guid(g["m"]))
db.tag_planned([row_m], W2, TODAY)
ok("Y1c ב-B החודשי הנעול חסום ב-W2 (אותה חסימה ברשימות)", row_m.get("planned_elsewhere") == W1.isoformat())

# ── Y6 — "גרסה ישנה": המפתח נשמר בהגדרות בלי קריאה לפונקציות הנעילה; אחרי "השדרוג" פועל ─────
use("b")
with db.get_connection() as c:
    keys = [r["key"] for r in c.execute("SELECT key FROM settings WHERE key GLOB 'planned_dist:*'")]
ok("Y6a הרשומה היא שורת הגדרה רגילה (גרסה ישנה פשוט שומרת אותה), ואין op חדש",
   keys == [db.PLAN_PREFIX + "2026-10-21"] and not any("plan" in k for k in sync._APPLIERS))
ok("Y6b 'שדרוג': הנעילה נקראת מיד בלי שליחה חוזרת", db.get_plan(W1)["note"] == "מ-A")

# ── Y2 — LWW לפי "עכשיו", גם לשבוע עתידי רחוק ─────────────────────────────────────
far = D("2026-12-02")
use("a")
db.save_plan(P(far, [g["z"]], note="A-מוקדם"))
sync_all("a", "b")
time.sleep(0.05)
use("b")
db.save_plan(P(far, [g["z"]], note="B-מאוחר"))
sync_all("b", "a")
use("a")
ok("Y2a עריכה מאוחרת ב-B מנצחת ב-A", db.get_plan(far)["note"] == "B-מאוחר")
time.sleep(0.05)
db.save_plan(P(far, [g["z"]], note="A-הכי-מאוחר"))
sync_all("a", "b")
use("b")
ok("Y2b ובסדר הפוך: העריכה המאוחרת ביותר (A) מנצחת ב-B — לא מושפעת מתאריך הרביעי (+45 יום)",
   db.get_plan(far)["note"] == "A-הכי-מאוחר")

# ── Y3 — מחיקה רכה ויצירה מחדש ────────────────────────────────────────────────────
use("a"); db.delete_plan(far)
sync_all("a", "b")
use("b")
ok("Y3a מחיקה ב-A ← ב-B הנעילה לא חיה", db.get_plan(far) is None and far not in db.plan_states(TODAY))
time.sleep(0.05)
db.save_plan(P(far, [g["z"], g["b"]], note="חדשה ב-B"))
sync_all("b", "a")
use("a")
ok("Y3b יצירה מחדש ב-B (מאוחרת) ← A רואה אותה חיה", db.get_plan(far) is not None and db.get_plan(far)["note"] == "חדשה ב-B")

# ── Y7 — שני מחשבים יוצרים לאותו רביעי באופליין: מפתח אחד, המאוחרת מנצחת ─────────────
use("a"); db.save_plan(P(W3, [g["z"]], note="A-אופליין"))
time.sleep(0.05)
use("b"); db.save_plan(P(W3, [g["b"]], note="B-אופליין"))
sync_all("a", "b", "a", "b")
for n in ("a", "b"):
    use(n)
    with db.get_connection() as c:
        cnt = c.execute("SELECT COUNT(*) FROM settings WHERE key=?", (db.PLAN_PREFIX + W3.isoformat(),)).fetchone()[0]
    ok(f"Y7 {n}: מפתח אחד לרביעי, המאוחרת (B) מנצחת", cnt == 1 and db.get_plan(W3)["note"] == "B-אופליין")

# ── Y9 — אסימון התנגשות בין מחשבים ────────────────────────────────────────────────
use("a")
token = db.get_plan(W1)["updated_at"]
time.sleep(0.05)
use("b"); db.save_plan(dict(db.get_plan(W1), note="B דורס")); sync_all("b", "a")
use("a")
try:
    db.save_plan(dict(db.get_plan(W1), note="A ישן"), expected_updated_at=token); conflict = False
except db.PlanConflict:
    conflict = True
ok("Y9 A טען, B דרס והסתנכרן, A שומר עם האסימון הישן ← PlanConflict", conflict and db.get_plan(W1)["note"] == "B דורס")

# ── Y8 — B רושם חלוקה ← אצל A הנעילה 'בוצעה' אחרי סנכרון ──────────────────────────
use("b")
db.bulk_add_distributions([{"id": db.get_recipient_by_guid(g["z"])["id"], "full_name": "שבועי", "area": "", "souls": 1}],
                          W1.isoformat(), "מנה", 1, "בדיקה", dist_name="בדיקה")
sync_all("b", "a")
use("a")
ok("Y8 אצל A הנעילה של 21/10 'בוצעה' ואינה תופסת", db.plan_states(TODAY).get(W1) == "executed"
   and W1 not in db.live_plan_index(TODAY).get(g["m"], []))

# ── Y10 — הרצה כפולה של אותו יומן: בלי שינוי ──────────────────────────────────────
use("a"); before = {w: raw(w) for w in (W1, far, W3)}
sync.run_sync(); sync.run_sync()
ok("Y10 סנכרון חוזר לא משנה את הנעילות (אידמפוטנטי)", before == {w: raw(w) for w in (W1, far, W3)})

# ── Y4/Y5 — דחיסה והצטרפות מחשבים ─────────────────────────────────────────────────
use("a"); sync.compact_journal()
use("c"); db.init_db(); sync.enable_sync(shared, seed=False); sync.run_sync()
ok("Y4 אחרי דחיסה ב-A, מחשב חדש מקבל את הנעילות מהראש",
   db.get_plan(far) is not None and db.get_plan(W3) is not None and db.get_plan(W3)["note"] == "B-אופליין"
   and db.get_plan(W1) is not None)
use("d"); db.init_db(); sync.enable_sync(shared, seed=True); sync.run_sync()
ok("Y5 מחשב ריק שמצטרף עם seed=True מקבל נעילות", db.get_plan(W3) is not None and db.get_plan(far) is not None)

# ── Y11 — restart_from_peer לא מאבד נעילות מקומיות ───────────────────────────────
use("b")
db.save_plan(P(W2, [g["z"]], note="מקומית ב-B"))
db.reset_all_data(); sync.restart_from_peer()
ok("Y11 'התחל מחדש מהמחשב השני' משאיר את הנעילות המקומיות", db.get_plan(W2) is not None
   and db.get_plan(W2)["note"] == "מקומית ב-B")
sync_all("b", "a")
use("a")
ok("Y11b והיא מגיעה גם ל-A", db.get_plan(W2) is not None)

# ── Y12 — שער הגרסאות של כפתור הנעילה ─────────────────────────────────────────────
from tabs.plan_lock import PlanLockMixin, PLAN_MIN_VERSION
use("a")
db.set_setting("app_version_otherdev", "3.80|המחשב השני")
blocked = PlanLockMixin._plan_peer_block(object())
db.set_setting("app_version_otherdev", f"{PLAN_MIN_VERSION}|המחשב השני")
open_ = PlanLockMixin._plan_peer_block(object())
db.set_setting("app_version_otherdev", "")
unknown = PlanLockMixin._plan_peer_block(object())
db.set_setting("app_version_otherdev", f"{PLAN_MIN_VERSION}|המחשב השני")
sync.disable_sync() if hasattr(sync, "disable_sync") else None
no_sync = PlanLockMixin._plan_peer_block(object())
ok("Y12a גרסה ישנה במחשב השני ← אזהרה עם הסבר (לא חסימה; נשאלים בלחיצה)", "3.80" in blocked and "לא יכבד" in blocked, blocked)
ok("Y12b גרסה חדשה ← פתוח", open_ == "")
ok("Y12c גרסה לא ידועה (ריקה) ← נעול (שמרני)", unknown != "")
ok("Y12d בלי סנכרון אין מחשב שני ← פתוח", no_sync == "")

print()
print("RESULT:", "ALL PLAN-SYNC TESTS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

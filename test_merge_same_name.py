# -*- coding: utf-8 -*-
"""משימה 7 — מיזוג מקבלים כששם זהה והטלפון שונה (v3.78).

DB זמני בלבד (לעולם לא ה-DB האמיתי ב-APPDATA). שני מחשבים מדומים כמו ב-test_sync:
מיזוג שעובר סנכרון חייב להתכנס לאותה תוצאה בשניהם, בלי לאבד טלפון/חלוקה/היסטוריה.
"""
import os, sys, json, tempfile, time
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


root = tempfile.mkdtemp(prefix="merge_test_")
dir_a = os.path.join(root, "pc_a"); os.makedirs(dir_a)
dir_b = os.path.join(root, "pc_b"); os.makedirs(dir_b)
shared = os.path.join(root, "drive"); os.makedirs(shared)
dir_l = os.path.join(root, "local"); os.makedirs(dir_l)


def use_machine(d):
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")


def by_name(name):
    return [r for r in db.get_all_recipients() if r["full_name"] == name]


def phones(rec):
    return [p for p in (rec.get("phone1"), rec.get("phone2"), rec.get("phone3")) if p]


def n_hist(rec_id):
    return len(db.get_distributions_for_recipient(rec_id))


def batch(rec, date_iso, name):
    return db.bulk_add_distributions([dict(rec)], date_iso, "מארז", 1, "משה", dist_name=name)


# ══ חלק 1 — לוגיקה מקומית ═══════════════════════════════════════════════════
use_machine(dir_l)
db.init_db()
NAME = "כהן דוד"
xid = db.add_recipient({"full_name": NAME, "phone1": "0501111111", "frequency": "שבועי",
                        "priority": 4, "souls": 5, "address": "רחוב א 1"})
yid = db.add_recipient({"full_name": NAME, "phone1": "0522222222", "phone2": "039999999",
                        "address": "רחוב ב 2", "email": "d@example.com", "notes": "הערה של Y",
                        "souls": 0})
x, y = db.get_recipient(xid), db.get_recipient(yid)
batch(x, "2026-08-05", "א"); batch(x, "2026-08-12", "ב"); batch(y, "2026-08-19", "ג")
x, y = db.get_recipient(xid), db.get_recipient(yid)

ok("pick_merge_keep: יותר היסטוריה נשאר",
   hasattr(db, "pick_merge_keep") and db.pick_merge_keep(x, y)[0]["id"] == xid
   and db.pick_merge_keep(y, x)[0]["id"] == xid)

# זיהוי "אותו שם, טלפון שונה"
cand = db.same_name_conflicts(NAME, ["0533333333"]) if hasattr(db, "same_name_conflicts") else []
ok("same_name_conflicts מוצא את שני הכרטיסים כשהטלפון שונה", len(cand) == 2, str(len(cand)))
cand = db.same_name_conflicts(NAME, ["050-1111111"]) if hasattr(db, "same_name_conflicts") else None
ok("same_name_conflicts: טלפון משותף = לא התנגשות (אותו אדם כבר)", cand == [] or
   (cand is not None and all(c["id"] == yid for c in cand)), str([c["id"] for c in (cand or [])]))
ok("same_name_conflicts: בלי טלפון בנכנס — לא מציע מיזוג",
   hasattr(db, "same_name_conflicts") and db.same_name_conflicts(NAME, []) == [])

res = db.merge_recipients(xid, yid)
left = by_name(NAME)
ok("אחרי מיזוג נשאר כרטיס אחד", len(left) == 1 and left[0]["id"] == xid, str(len(left)))
k = left[0] if left else {}
ok("שני הטלפונים נשמרים (וגם הטלפון השלישי של Y)",
   {"0501111111", "0522222222", "039999999"} <= set(phones(k)), str(phones(k)))
ok("הטלפון הראשי של הכרטיס שנשאר לא זז", k.get("phone1") == "0501111111")
ok("שדה ריק מתמלא מהשני (אימייל)", k.get("email") == "d@example.com")
ok("שדה שיש בשניהם נשאר של הכרטיס שנשאר (כתובת)", k.get("address") == "רחוב א 1")
ok("נפשות: 5 נשאר (לא נדרס ב-0)", k.get("souls") == 5)
ok("הערה של השני עוברת", "הערה של Y" in (k.get("notes") or ""))
ok("היסטוריית החלוקות מתאחדת (3)", n_hist(xid) == 3, str(n_hist(xid)))
ok("אף שורת חלוקה לא נשארה יתומה", not [d for d in db.get_distributions()
                                         if d["recipient_id"] not in (xid,)])
ok("חלוקה אחרונה = המאוחרת משני הכרטיסים", k.get("last_distribution") == "2026-08-19",
   str(k.get("last_distribution")))
dl = [r for r in db.get_deleted_recipients() if r["guid"] == y["guid"]]
ok("הכרטיס שנמחק נשמר ב'מקבלים שנמחקו' עם מקור מיזוג",
   len(dl) == 1 and dl[0]["source"] == "merge" and "0522222222" in dl[0]["card_json"], str(dl))
ok("מקור המיזוג מתורגם", db.SOURCE_LABELS_DELETE.get("merge"))
ch = db.get_changes_for_recipient(xid, k.get("guid"))
ok("נרשם ב-change_log (שורת מיזוג + שדות)",
   any(c.get("field") == "merge" for c in ch) and any(c.get("field") == "phone2" for c in ch),
   str([c.get("field") for c in ch]))
ok("תווית מקור 'מיזוג'", db.change_source_label("merge") == "מיזוג")
with db.get_connection() as conn:
    tomb = conn.execute("SELECT 1 FROM sync_deleted WHERE guid=?", (y["guid"],)).fetchone()
    mg = conn.execute("SELECT keep_guid FROM merged_guids WHERE drop_guid=?", (y["guid"],)).fetchone()
ok("שומר תחיית-מתים נרשם לכרטיס שנמחק", tomb is not None)
ok("merged_guids מצביע לכרטיס שנשאר", mg is not None and mg["keep_guid"] == k.get("guid"))
# שחזור מהיומן מחזיר את הכרטיס (חדש), ההיסטוריה נשארת בכרטיס המאוחד
nid, msg = db.restore_deleted_recipient(y["guid"])
ok("שחזור מ'מקבלים שנמחקו' מחזיר כרטיס", nid is not None and len(by_name(NAME)) == 2, str(msg))
ok("אחרי שחזור ההיסטוריה נשארת בכרטיס המאוחד", n_hist(xid) == 3 and n_hist(nid) == 0)

# ארבעה טלפונים ויותר — שום מספר לא הולך לאיבוד
use_machine(dir_l)
aid = db.add_recipient({"full_name": "לוי משה", "phone1": "0501000001", "phone2": "0501000002",
                        "phone3": "0501000003"})
bid = db.add_recipient({"full_name": "לוי משה", "phone1": "0501000004", "phone2": "0501000005"})
db.merge_recipients(aid, bid)
m = by_name("לוי משה")[0]
blob = " ".join(phones(m)) + " " + (m.get("notes") or "")
ok("5 מספרים: כולם מופיעים (3 בשדות, השאר בהערות)",
   all(p in blob for p in ("0501000001", "0501000002", "0501000003", "0501000004", "0501000005")), blob)
ok("אין יותר מ-3 שדות טלפון", len(phones(m)) == 3)

# מיזוג לכרטיס קיים (ייבוא / הוספה ידנית) — ללא מחיקה, ללא op חדש
cid = db.add_recipient({"full_name": "גולד אבי", "phone1": "0541111111", "address": "כתובת קיימת"})
changed = db.merge_into_recipient(cid, {"full_name": "גולד אבי", "phone1": "0542222222",
                                        "address": "כתובת אחרת", "email": "g@example.com"})
g = db.get_recipient(cid)
ok("merge_into_recipient: מספר חדש נכנס ל-phone2", g["phone1"] == "0541111111" and g["phone2"] == "0542222222")
ok("merge_into_recipient: כתובת קיימת לא נדרסת, אימייל ריק מתמלא",
   g["address"] == "כתובת קיימת" and g["email"] == "g@example.com")
ok("merge_into_recipient מחזיר True כששונה משהו", changed is True)
ok("merge_into_recipient אידמפוטנטי", db.merge_into_recipient(
    cid, {"full_name": "גולד אבי", "phone1": "0542222222"}) is False)
ok("עדיין כרטיס אחד", len(by_name("גולד אבי")) == 1)
ok("נרשם בהיסטוריה כמיזוג", any(c.get("source") == "merge"
                                for c in db.get_changes_for_recipient(cid, g.get("guid"))))

# ייבוא אקסל — אותו שם, טלפון שונה
rows = [{"full_name": "גולד אבי", "phone1": "0549999999", "email": "x@example.com"},
        {"full_name": "רבין חיים", "phone1": "0501234567"},
        {"full_name": "כהן יוסי", "phone1": "0503333333", "address": "חדש"}]
db.add_recipient({"full_name": "רבין חיים", "phone1": "0501234567", "address": "ישן"})
db.add_recipient({"full_name": "כהן יוסי", "phone1": "0508888888", "address": "בית ישן"})
diff = db.diff_incoming_recipients([dict(r) for r in rows])
sn = diff.get("same_name") or []
ok("diff: אותו שם + טלפון שונה → same_name (אבי וגם יוסי)",
   sorted(s["full_name"] for s in sn) == ["גולד אבי", "כהן יוסי"], str(sn))
ok("diff: טלפון זהה (רבין) לא נחשב same_name", all(s["full_name"] != "רבין חיים" for s in sn))
upd_fields = {(u["full_name"], f) for u in diff["updates"] for f in u["changes"]}
ok("diff: הטלפון המתנגש לא מוצע יותר כ'שינוי' שידרוס",
   not any(f in ("phone1", "phone2", "phone3") and n in ("גולד אבי", "כהן יוסי")
           for n, f in upd_fields), str(upd_fields))
ok("diff: שינוי שאינו טלפון נשאר כשינוי רגיל (כתובת של כהן יוסי)", ("כהן יוסי", "address") in upd_fields)

n_before = len(db.get_all_recipients())
decisions = []
for s in sn:
    decisions.append({"id": s["id"], "row": s["row"],
                      "choice": "merge" if s["full_name"] == "גולד אבי" else "separate"})
added, updated = db.apply_import_confirmed(diff["new"], [], same_name=decisions)
ok("ייבוא: 'מזג' הוסיף טלפון לכרטיס הקיים",
   "0549999999" in phones(db.get_recipient(cid)) or "0549999999" in (db.get_recipient(cid).get("notes") or ""))
ok("ייבוא: 'שני אנשים שונים' הוסיף כרטיס חדש", len(by_name("כהן יוסי")) == 2)
ok("ייבוא: סך הכרטיסים עלה ב-1 בלבד", len(db.get_all_recipients()) == n_before + 1,
   f"{n_before}->{len(db.get_all_recipients())}")
d2 = db.apply_import_confirmed([], [], same_name=[{"id": cid, "row": rows[0], "choice": "skip"}])
ok("ייבוא: 'דלג' לא עושה כלום", d2 == (0, 0))

# ══ חלק 2 — שני מחשבים ══════════════════════════════════════════════════════
use_machine(dir_a)
db.init_db()
sync.set_device_name("מחשב-א")
ax = db.add_recipient({"full_name": NAME, "phone1": "0501111111", "frequency": "שבועי", "priority": 4,
                       "address": "רחוב א 1"})
ay = db.add_recipient({"full_name": NAME, "phone1": "0522222222", "email": "d@example.com"})
az = db.add_recipient({"full_name": "אחר אדם", "phone1": "0507777777"})
rx, ry = db.get_recipient(ax), db.get_recipient(ay)
batch(rx, "2026-08-05", "א"); batch(rx, "2026-08-12", "ב"); batch(ry, "2026-08-19", "ג")
sync.enable_sync(shared, seed=True)

use_machine(dir_b)
db.init_db()
sync.set_device_name("מחשב-ב")
sync.enable_sync(shared, seed=True)
sync.run_sync()
ok("B קיבל שני כרטיסים באותו שם", len(by_name(NAME)) == 2, str(len(by_name(NAME))))


def state():
    """תמונת מצב להשוואה בין המחשבים (בלי מזהים מקומיים)."""
    out = {}
    for r in db.get_all_recipients():
        out[r["guid"]] = (r["full_name"], tuple(phones(r)), n_hist(r["id"]),
                          r.get("email") or "", r.get("last_distribution") or "")
    return out


# A ממזג → B מקבל
use_machine(dir_a)
time.sleep(0.02)
db.merge_recipients(ax, ay)
sync.run_sync()
state_a = state()
use_machine(dir_b)
res = sync.run_sync()
state_b = state()
ok("B קיבל את המיזוג", res["applied"] >= 1, str(res))
ok("B: כרטיס אחד בשם, אותם נתונים כמו ב-A (התכנסות)", state_a == state_b, f"\nA={state_a}\nB={state_b}")
kb = by_name(NAME)
ok("B: שני הטלפונים והיסטוריה מאוחדת (3)", len(kb) == 1 and len(phones(kb[0])) >= 2 and n_hist(kb[0]["id"]) == 3,
   str([(phones(r), n_hist(r["id"])) for r in kb]))
ok("B: היסטוריית השינויים כוללת את שורת המיזוג",
   any(c.get("field") == "merge" for c in db.get_changes_for_recipient(kb[0]["id"], kb[0]["guid"])))
dlb = [r for r in db.get_deleted_recipients() if r["source"] == "merge"]
ok("B: 'מקבלים שנמחקו' רושם מיזוג עם שם המחשב של A",
   len(dlb) == 1 and dlb[0]["device"] == "מחשב-א", str(dlb))
# הרצה חוזרת — אין שינוי
use_machine(dir_b); sync.run_sync(); st2 = state()
use_machine(dir_a); sync.run_sync(); st3 = state()
ok("סנכרון חוזר לא משנה כלום (אידמפוטנטי)", st2 == state_b and st3 == state_a)

# חלוקה שנרשמה ב-B על הכרטיס הנמחק לפני שקיבל את המיזוג
use_machine(dir_a)
bx = [db.get_recipient(db.add_recipient({"full_name": "בדיקה ראשון", "phone1": "0501100001"}))]
by_ = db.get_recipient(db.add_recipient({"full_name": "בדיקה ראשון", "phone1": "0501100002"}))
batch(bx[0], "2026-09-02", "ד")
sync.run_sync()
use_machine(dir_b); sync.run_sync()
b_keep = by_name("בדיקה ראשון")
ok("B קיבל את שני כרטיסי 'בדיקה ראשון'", len(b_keep) == 2)
use_machine(dir_a)
time.sleep(0.02)
db.merge_recipients(bx[0]["id"], by_["id"])         # A: ממזג ושולח
sync.run_sync()
use_machine(dir_b)                                  # B עוד לא משך את המיזוג — רושם חלוקה על הכרטיס שיימחק
drop_b = [r for r in by_name("בדיקה ראשון") if r["phone1"] == "0501100002"][0]
batch(drop_b, "2026-09-09", "ה")
sync.run_sync()                                     # שולח את החלוקה ומושך את המיזוג
use_machine(dir_a)
sync.run_sync()
sa = state()
ka = by_name("בדיקה ראשון")
ka_hist = [(r["phone1"], n_hist(r["id"])) for r in ka]
use_machine(dir_b); sb = state()
ok("A: כרטיס אחד ו-2 חלוקות (גם זו ש-B רשם על הכרטיס שנמחק)",
   len(ka) == 1 and ka_hist[0][1] == 2, str(ka_hist))
use_machine(dir_b)
kb2 = by_name("בדיקה ראשון")
ok("B: כרטיס אחד ו-2 חלוקות", len(kb2) == 1 and n_hist(kb2[0]["id"]) == 2,
   str([(r["phone1"], n_hist(r["id"])) for r in kb2]))
ok("A ו-B מתכנסים לאותו מצב", sa == sb, f"\nA={sa}\nB={sb}")

# צילום ישן של הכרטיס שנמחק (ממחשב שלישי) לא מחיה אותו
use_machine(dir_a)
drop_guid = by_["guid"]
with db.get_connection() as conn:
    sync._apply_rec_upsert(conn, {"guid": drop_guid, "ts": "2000-01-01T00:00:00+00:00",
                                  "data": {"full_name": "בדיקה ראשון", "phone1": "0501100002",
                                           "updated_at": "2000-01-01T00:00:00+00:00"}})
ok("שומר תחיית-מתים: כרטיס ישן של הנמחק לא חוזר", len(by_name("בדיקה ראשון")) == 1)

# B ערך את הכרטיס הנמחק אחרי המיזוג, לפני שמשך — לא מוחקים עריכה טרייה
use_machine(dir_a)
p1 = db.get_recipient(db.add_recipient({"full_name": "עריכה מאוחרת", "phone1": "0502000001"}))
p2 = db.get_recipient(db.add_recipient({"full_name": "עריכה מאוחרת", "phone1": "0502000002"}))
sync.run_sync()
use_machine(dir_b); sync.run_sync()
use_machine(dir_a)
time.sleep(0.02)
db.merge_recipients(p1["id"], p2["id"])
sync.run_sync()
use_machine(dir_b)
time.sleep(0.02)
b_p2 = [r for r in by_name("עריכה מאוחרת") if r["phone1"] == "0502000002"][0]
db.update_recipient(b_p2["id"], {"notes": "עריכה חשובה אחרי המיזוג"})
sync.run_sync()
left_b = by_name("עריכה מאוחרת")
ok("B: עריכה טרייה של הכרטיס הנמחק לא אבדה (עדיף כפילות על אובדן)",
   any("עריכה חשובה" in (r.get("notes") or "") for r in left_b), str([(r["phone1"], r.get("notes")) for r in left_b]))

# מיזוג בכיוונים הפוכים במקביל — בלי קריסה ובלי אובדן חלוקות
use_machine(dir_a)
q1 = db.get_recipient(db.add_recipient({"full_name": "מקביל זוג", "phone1": "0503000001"}))
q2 = db.get_recipient(db.add_recipient({"full_name": "מקביל זוג", "phone1": "0503000002"}))
batch(q1, "2026-09-16", "ו"); batch(q2, "2026-09-23", "ז")
sync.run_sync()
use_machine(dir_b); sync.run_sync()
use_machine(dir_a)
db.merge_recipients(q1["id"], q2["id"])
use_machine(dir_b)
bq = {r["phone1"]: r for r in by_name("מקביל זוג")}
db.merge_recipients(bq["0503000002"]["id"], bq["0503000001"]["id"])
for _ in range(2):
    use_machine(dir_a); sync.run_sync()
    use_machine(dir_b); sync.run_sync()
use_machine(dir_a); ra = by_name("מקביל זוג"); ha = sum(n_hist(r["id"]) for r in ra)
use_machine(dir_b); rb = by_name("מקביל זוג"); hb = sum(n_hist(r["id"]) for r in rb)
ok("מיזוג הפוך במקביל: אף חלוקה לא אבדה ואין מחיקה כפולה", ha == 2 and hb == 2 and ra and rb,
   f"A={[(r['phone1'], n_hist(r['id'])) for r in ra]} B={[(r['phone1'], n_hist(r['id'])) for r in rb]}")
ok("מיזוג הפוך במקביל: שני המספרים שמורים בכל מחשב",
   all({"0503000001", "0503000002"} <= {p for r in rs for p in phones(r)} for rs in (ra, rb)))

# דחיסת journal: מחשב שהיה מנותק בזמן המיזוג והדחיסה עדיין מתכנס; מחשב שמצטרף אחרי — מקבל מצב עקבי
use_machine(dir_a)
c1 = db.get_recipient(db.add_recipient({"full_name": "מנותק זוג", "phone1": "0504000001"}))
c2 = db.get_recipient(db.add_recipient({"full_name": "מנותק זוג", "phone1": "0504000002"}))
batch(c1, "2026-09-30", "ח"); batch(c2, "2026-10-01", "ט")
sync.run_sync()
use_machine(dir_b); sync.run_sync()
ok("B מחזיק את שני הכרטיסים לפני המיזוג", len(by_name("מנותק זוג")) == 2)
use_machine(dir_a)
time.sleep(0.02)
db.merge_recipients(c1["id"], c2["id"])
sync.run_sync()
sync.compact_journal()
state_a2 = state()
use_machine(dir_b)
sync.run_sync()
ok("אחרי דחיסת journal: B (שהיה מנותק) התכנס לאותו מצב",
   [v for v in state().values() if v[0] == 'מנותק זוג'] == [v for v in state_a2.values() if v[0] == 'מנותק זוג'],
   "A=%s B=%s" % ([v for v in state_a2.values() if v[0] == 'מנותק זוג'],
                  [v for v in state().values() if v[0] == 'מנותק זוג']))
dir_c = os.path.join(root, "pc_c"); os.makedirs(dir_c)
use_machine(dir_c)
db.init_db(); sync.set_device_name("מחשב-ג")
sync.enable_sync(shared, seed=True)
sync.run_sync(); sync.run_sync()
st_c = state()
ok("מחשב חדש שמצטרף אחרי המיזוג והדחיסה: כרטיס אחד, היסטוריה מאוחדת",
   [v for v in st_c.values() if v[0] == "מנותק זוג"] == [v for v in state_a2.values() if v[0] == "מנותק זוג"],
   str([v for v in st_c.values() if v[0] == "מנותק זוג"]))

# מיזוג — דחיסת journal: ה-op נשמר ב-tombstones
ok("rec_merge ב-_TOMBSTONE_OPS ובמחילים", "rec_merge" in sync._TOMBSTONE_OPS and "rec_merge" in sync._APPLIERS)

print()
if fails:
    print("FAILED:", len(fails)); [print(" -", f) for f in fails]
    sys.exit(1)
print("ALL MERGE TESTS PASSED")
sys.exit(0)

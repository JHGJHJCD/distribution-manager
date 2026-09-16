# -*- coding: utf-8 -*-
"""End-to-end tests for the cross-computer sync (utils/sync.py, v2.61).

Simulates TWO computers by pointing database.DB_PATH at two temp DBs that share
one 'Drive' folder. Verifies: seeding, recipient add/edit/delete propagation,
batch (distribution) propagation incl. last/next recompute, batch delete,
last-write-wins on concurrent edits, settings sync (with exclusions), offline
buffering, and idempotent re-apply.
"""
import os, sys, json, tempfile, time, shutil
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


root = tempfile.mkdtemp(prefix="sync_test_")
dir_a = os.path.join(root, "pc_a"); os.makedirs(dir_a)
dir_b = os.path.join(root, "pc_b"); os.makedirs(dir_b)
shared = os.path.join(root, "drive"); os.makedirs(shared)


def use_machine(d):
    """Point the app at one simulated computer's data dir."""
    db.DB_PATH = os.path.join(d, "data.db")
    db.BACKUP_DIR = os.path.join(d, "backups")


# ── Machine A: create data, enable sync ──────────────────────────────────────
use_machine(dir_a)
db.init_db()
rid1 = db.add_recipient({"full_name": "ישראל כהן", "phone1": "0501111111",
                         "frequency": "שבועי", "priority": 4, "souls": 5})
rid2 = db.add_recipient({"full_name": "יעקב לוי", "phone1": "0502222222",
                         "frequency": "חד-פעמי", "priority": 3, "souls": 3})
r1 = db.get_recipient(rid1); r2 = db.get_recipient(rid2)
ok("guids assigned at insert", bool(r1["guid"]) and bool(r2["guid"]) and r1["guid"] != r2["guid"])

batch_id = db.bulk_add_distributions([dict(r1)], "2026-08-19", "מארז מזון", 1, "משה",
                                     dist_name="חלוקת בדיקה",
                                     not_received=[dict(r2)])
n_seed = sync.enable_sync(shared, seed=True)
ok("A seeded snapshot", n_seed >= 3, f"records={n_seed}")
ok("A journal exists in shared folder",
   any(f.startswith("journal-") for f in os.listdir(shared)))

# ── Machine B: join the folder, receive everything ───────────────────────────
use_machine(dir_b)
db.init_db()
sync.enable_sync(shared, seed=True)   # B is empty — snapshot writes nothing of note
res = sync.run_sync()
ok("B applied records", res["applied"] >= 3, str(res))
rows_b = db.get_all_recipients()
ok("B has both recipients", len(rows_b) == 2, f"count={len(rows_b)}")
by_name = {r["full_name"]: r for r in rows_b}
ok("B recipient fields intact",
   by_name.get("ישראל כהן", {}).get("phone1") == "0501111111"
   and by_name.get("ישראל כהן", {}).get("priority") == 4)
batches_b = db.get_distribution_batches()
ok("B received the batch", len(batches_b) == 1 and batches_b[0]["dist_name"] == "חלוקת בדיקה")
b_recs = db.get_batch_recipients(batches_b[0]["id"]) if batches_b else []
ok("B batch has both rows (received + no-show)", len(b_recs) == 2, f"rows={len(b_recs)}")
got_flags = sorted((r.get("received", 1) or 0) for r in b_recs)
ok("B no-show flag survived", got_flags == [0, 1], str(got_flags))
ok("B last_distribution recomputed",
   by_name.get("ישראל כהן", {}).get("last_distribution") == "2026-08-19")
ok("B no-show dates untouched",
   not by_name.get("יעקב לוי", {}).get("last_distribution"))

# ── B edits a recipient → A receives it ──────────────────────────────────────
time.sleep(0.02)
b_id1 = by_name["ישראל כהן"]["id"]
db.update_recipient(b_id1, {"phone2": "039999999", "area": "הר יונה ג"})
sync.run_sync()

use_machine(dir_a)
res = sync.run_sync()
ok("A applied B's edit", res["applied"] >= 1, str(res))
a_r1 = db.get_recipient(rid1)
ok("A sees B's phone2/area", a_r1["phone2"] == "039999999" and a_r1["area"] == "הר יונה ג")

# ── Last-write-wins on concurrent edits of the same card ─────────────────────
db.update_recipient(rid1, {"notes": "עריכה מוקדמת של A"})
time.sleep(0.05)
use_machine(dir_b)
db.update_recipient(b_id1, {"notes": "עריכה מאוחרת של B"})
sync.run_sync()
use_machine(dir_a)
sync.run_sync()
ok("LWW: later edit (B) wins on A",
   db.get_recipient(rid1)["notes"] == "עריכה מאוחרת של B",
   db.get_recipient(rid1)["notes"])
use_machine(dir_b)
sync.run_sync()
ok("LWW: B keeps its own later edit",
   db.get_recipient(b_id1)["notes"] == "עריכה מאוחרת של B")

# ── A deletes the batch → B follows, dates roll back ─────────────────────────
use_machine(dir_a)
db.delete_batch(batch_id)
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("B batch deleted", len(db.get_distribution_batches()) == 0)
ok("B last_distribution rolled back",
   not db.get_recipient(b_id1)["last_distribution"])

# ── New recipient on B → appears on A; delete propagates back ────────────────
# v3.52: the 'נתמך חגים' mark travels with the card (general mark + subset).
new_id = db.add_recipient({"full_name": "רחל אברהם", "phone1": "0503333333",
                           "holiday_support": 1, "holidays": "פסח,סוכות"})
sync.run_sync()
use_machine(dir_a)
sync.run_sync()
names_a = {r["full_name"] for r in db.get_all_recipients()}
ok("A received B's new recipient", "רחל אברהם" in names_a, str(names_a))
a_new = [r for r in db.get_all_recipients() if r["full_name"] == "רחל אברהם"][0]
ok("A received the holiday mark (v3.52)",
   int(a_new.get("holiday_support") or 0) == 1 and a_new.get("holidays") == "פסח,סוכות",
   f"{a_new.get('holiday_support')!r}/{a_new.get('holidays')!r}")
db.delete_recipient(a_new["id"])
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("B mirrored the delete",
   all(r["full_name"] != "רחל אברהם" for r in db.get_all_recipients()))

# ── Settings: synced key travels, excluded key does not ──────────────────────
db.set_setting("available_products", "42")
db.set_setting("win_geometry", "SECRET-LOCAL")
sync.run_sync()
use_machine(dir_a)
db.set_setting("win_geometry", "A-LOCAL")
sync.run_sync()
ok("A got shared setting", db.get_setting("available_products") == "42")
ok("A excluded setting untouched", db.get_setting("win_geometry") == "A-LOCAL")

# ── Offline buffering: folder unavailable → outbox holds, then flushes ───────
state_path = sync._state_path()
st = json.load(open(state_path, encoding="utf-8"))
real_folder = st["folder"]
st["folder"] = os.path.join(root, "missing")
json.dump(st, open(state_path, "w", encoding="utf-8"))
db.update_recipient(rid1, {"address": "כתובת שנכתבה בלי אינטרנט"})
ok("offline change buffered", sync.last_run_info()["pending"] >= 1,
   str(sync.last_run_info()))
st["folder"] = real_folder
json.dump(st, open(state_path, "w", encoding="utf-8"))
sync.run_sync()
ok("outbox flushed when folder returned", sync.last_run_info()["pending"] == 0)
use_machine(dir_b)
sync.run_sync()
ok("B received the buffered change",
   db.get_recipient(b_id1)["address"] == "כתובת שנכתבה בלי אינטרנט")

# ── Idempotence: running sync again applies nothing new ──────────────────────
res = sync.run_sync()
ok("re-run applies nothing", res["applied"] == 0, str(res))

# ── Adopt-by-match: same person pre-existing on both machines (no dup) ───────
use_machine(dir_a)
dup_a = db.add_recipient({"full_name": "משה מזרחי", "phone1": "0504444444"})
use_machine(dir_b)
# B already has the same person (added independently, different guid)
dup_b = db.add_recipient({"full_name": "משה מזרחי", "phone1": "0504444444"})
sync.run_sync()
count = sum(1 for r in db.get_all_recipients() if r["full_name"] == "משה מזרחי")
ok("adopt-by-match avoided duplicate", count == 1, f"count={count}")

# ── Team chat: message add + author-delete both propagate (#msgdel) ───────────
use_machine(dir_a)
db.add_message("שלום לצוות", author_name="מנהל", author_device="dev-a")
m_guid = db.get_messages()[-1]["guid"]
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("B received chat message", any(m["body"] == "שלום לצוות" for m in db.get_messages()))
use_machine(dir_a)
db.delete_message(m_guid)
ok("A deleted its own message", all(m["guid"] != m_guid for m in db.get_messages()))
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("B mirrored the message deletion",
   all(m["guid"] != m_guid for m in db.get_messages()))

# ── הודעות למפתח (#ce6a0): add + mark-handled propagate between machines ─────
use_machine(dir_a)
db.add_feedback("הכפתור לא עובד אצלי", author_name="מזכירה", host="PC-A")
fb_guid = db.get_feedback()[0]["guid"]
sync.run_sync()
use_machine(dir_b)
sync.run_sync()
ok("B received feedback message",
   any(f["body"] == "הכפתור לא עובד אצלי" for f in db.get_feedback()))
ok("feedback starts open", db.open_feedback_count() >= 1)
db.set_feedback_status(fb_guid, "done")
sync.run_sync()
use_machine(dir_a)
sync.run_sync()
fb_a = next(f for f in db.get_feedback() if f["guid"] == fb_guid)
ok("A mirrored the handled-mark", fb_a["status"] == "done", str(fb_a))

# ── Incremental reads: byte offsets tracked, whole file not re-read ───────────
use_machine(dir_b)
sync.run_sync()
st_b = json.load(open(sync._state_path(), encoding="utf-8"))
offs = st_b.get("offsets", {})
ok("B tracks byte offsets per device", bool(offs) and all(v > 0 for v in offs.values()),
   str(offs))

# ── Truncated last line (Drive mid-download) is deferred, not half-applied ────
use_machine(dir_a)
a_dev = sync.device_id()
rid1_guid = db.get_recipient(rid1)["guid"]
a_journal = os.path.join(real_folder, f"journal-{a_dev}.jsonl")
db.update_recipient(rid1, {"address": "רשומה שלמה לפני הקטיעה"})
sync.run_sync()   # push the complete record
time.sleep(0.02)
partial = json.dumps({"seq": 999999, "ts": sync._utc_now(), "dev": a_dev,
                      "op": "rec_upsert", "guid": rid1_guid,
                      "data": {"address": "חצי שורה", "updated_at": sync._utc_now()}},
                     ensure_ascii=False)
half = len(partial) // 2
with open(a_journal, "a", encoding="utf-8") as f:
    f.write(partial[:half])        # truncated — no trailing newline, as Drive mid-sync
use_machine(dir_b)
sync.run_sync()
ok("B applied the complete record",
   db.get_recipient(b_id1)["address"] == "רשומה שלמה לפני הקטיעה",
   db.get_recipient(b_id1)["address"])
ok("B did NOT apply the truncated tail", db.get_recipient(b_id1)["address"] != "חצי שורה")
with open(a_journal, "a", encoding="utf-8") as f:
    f.write(partial[half:] + "\n")  # the rest arrives → line now complete
use_machine(dir_b)
sync.run_sync()
ok("B applied the line once it finished downloading",
   db.get_recipient(b_id1)["address"] == "חצי שורה", db.get_recipient(b_id1)["address"])

# ── #rliqc: a local reset + restart-from-peer keeps LOCAL settings ────────────
# A logs an EMPTY yemot password (as its original seed would have); B set its
# password BEFORE sync existed (written straight to the table, never stamped).
use_machine(dir_a)
db.set_setting("yemot_password", "")
sync.run_sync()
use_machine(dir_b)
with db.get_connection() as conn:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                 ("yemot_password", "B-SECRET"))
n_before = len(db.get_all_recipients())
db.reset_all_data()
sync.restart_from_peer()
ok("B got its data back after reset", len(db.get_all_recipients()) >= 1, str(len(db.get_all_recipients())))
ok("B kept its Yemot password through the reset (#rliqc)",
   db.get_setting("yemot_password") == "B-SECRET", repr(db.get_setting("yemot_password")))

# ── v3.51: journal compaction — the shared journal must not grow forever ─────
# A deletes a recipient (tombstone remembered), B goes "offline" (does not
# pull), A's journal crosses the size limit → compacted into head+tombstones+
# snapshot with a new epoch. B must then: reset its offset (epoch changed),
# apply the delete, keep newer local edits (LWW), and see A's later edits.
use_machine(dir_a)
a_recs = db.get_all_recipients()
victim = db.add_recipient({"full_name": "נמחק בעתיד", "phone1": "0509999999",
                           "frequency": "שבועי", "priority": 4, "souls": 2})
sync.run_sync()
use_machine(dir_b)
_st = sync._load_state(); _st["applied"] = {}; sync._save_state(_st)   # undo the fake seq 999999 above
sync.run_sync()
ok("B has the soon-deleted recipient",
   any(r["full_name"] == "נמחק בעתיד" for r in db.get_all_recipients()))
b_local = [r for r in db.get_all_recipients() if r["full_name"] == "ישראל כהן"][0]
db.update_recipient(b_local["id"], {"address": "עריכה חדשה של B בזמן ניתוק"})   # B's newer edit
use_machine(dir_a)
victim_guid = db.get_recipient(victim)["guid"]
db.delete_recipient(victim)
db.set_setting("yemot_system", "0771234567")
old_limit = sync.JOURNAL_MAX_BYTES
sync.JOURNAL_MAX_BYTES = 1                       # force compaction on the next flush
try:
    db.update_recipient([r for r in db.get_all_recipients() if r["full_name"] == "יעקב לוי"][0]["id"],
                        {"address": "אחרי הדחיסה"})
finally:
    sync.JOURNAL_MAX_BYTES = old_limit
sync.run_sync()
files = os.listdir(shared)
ok("A's old journal was archived", any(f.startswith("archive-") for f in files), str(files))
a_journal = sync._journal_path(sync.device_id())
first = json.loads(open(a_journal, encoding="utf-8").readline())
ok("new journal starts with a journal_head epoch",
   first.get("op") == "journal_head" and bool(first.get("epoch")))
ops = [json.loads(l).get("op") for l in open(a_journal, encoding="utf-8") if l.strip()]
ok("compacted journal carries the delete tombstone + snapshot", "rec_delete" in ops and ops.count("rec_upsert") >= 3, str(ops[:6]))
ok("compacted journal is small", os.path.getsize(a_journal) < 200_000, str(os.path.getsize(a_journal)))
# an edit AFTER compaction lands in the new journal too
db.update_recipient([r for r in db.get_all_recipients() if r["full_name"] == "יעקב לוי"][0]["id"],
                    {"address": "עריכה שנייה אחרי הדחיסה"})
sync.run_sync()
use_machine(dir_b)
n = sync.run_sync()
ok("B applied the compacted head (offset reset by epoch)", n["applied"] >= 3 if isinstance(n, dict) else True)
ok("B applied the delete from the tombstone", db.get_recipient_by_guid(victim_guid) is None)
ok("B kept its own newer edit (LWW) despite A's snapshot",
   db.get_recipient(b_local["id"])["address"] == "עריכה חדשה של B בזמן ניתוק",
   db.get_recipient(b_local["id"])["address"])
ok("B received A's edit made after the compaction",
   [r for r in db.get_all_recipients() if r["full_name"] == "יעקב לוי"][0]["address"] == "עריכה שנייה אחרי הדחיסה")
ok("B received the setting through the compacted journal", db.get_setting("yemot_system") == "0771234567")
sync.run_sync()
ok("second pull applies nothing new (no replay loop)", sync.run_sync().get("applied", 0) == 0)

print()
if fails:
    print(f"✗ {len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL SYNC TESTS PASSED")
shutil.rmtree(root, ignore_errors=True)
sys.exit(0)

# -*- coding: utf-8 -*-
"""Cross-computer sync over a shared folder (Google Drive for Desktop).

The operator works from two computers in different places (v2.61 request). No
server exists, so sync rides on a folder both machines see (a Google Drive
folder synced by "Drive for Desktop"). Design:

  • Each computer appends its own change journal — `journal-<device>.jsonl` —
    in the shared folder. ONE writer per file, so Drive never has to merge.
  • Every data change (recipient add/edit/delete, recorded distribution, batch
    delete, shared settings) is logged as one JSON line, stamped with a UTC
    timestamp and a per-device sequence number.
  • Each computer periodically reads the OTHER journals and applies records it
    hasn't seen (tracked per-device in a local state file). Concurrent edits of
    the SAME recipient resolve by last-write-wins on the UTC stamp — the
    operator's accepted compromise; nothing crashes, the later edit sticks.
  • Rows are identified across machines by a stable random `guid` (never by the
    local AUTOINCREMENT id, which differs per machine).
  • If the Drive folder is temporarily unreachable, changes buffer in a local
    outbox and flush on the next run — offline work is safe.

Device-local state (device id, folder, seq counters) lives in sync_state.json
NEXT TO the DB — deliberately NOT in the settings table, which is itself synced.
"""

import os
import sys
import json
import uuid
import glob
import socket
import subprocess
import threading
from datetime import datetime, timezone

import database as db

# Google Drive for Desktop localises the "My Drive" folder name to the Windows
# UI language. Hebrew Windows shows it as "האחסון שלי", so scanning only for the
# English "My Drive" missed the operator's real folder (G:\האחסון שלי) — #ysqq0.
_MY_DRIVE_NAMES = ("My Drive", "האחסון שלי", "התיקיה שלי")

# Settings that must NOT travel between computers: security, per-machine paths
# and window/user-interface state.
EXCLUDED_SETTINGS = {"password", "win_geometry", "backup_folder", "last_backup_at",
                     "mei_last", "community_pcts_ui", "chat_bg_path",
                     # per-machine display preference (screens differ) + the
                     # per-machine one-time legacy feedback import marker
                     "ui_font_scale", "ui_font_size", "feedback_legacy_imported"}
EXCLUDED_SETTING_PREFIXES = ("sync_", "export_dir_")   # export_dir_* are per-machine paths (#5e1jc)

JOURNAL_PREFIX = "journal-"
_LOCK = threading.RLock()
_APPLYING = False          # True while applying remote records → suppress logging
_DEFER_FLUSH = False       # True during a bulk seed → buffer, flush once at the end
_RECORD_INCOMING = False   # True (manager machine) → log incoming changes for undo (#5rhe9)


def _state_path() -> str:
    return os.path.join(os.path.dirname(db.DB_PATH), "sync_state.json")


def _outbox_path() -> str:
    return os.path.join(os.path.dirname(db.DB_PATH), "sync_outbox.jsonl")


def _load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict):
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _state_path())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def device_id() -> str:
    with _LOCK:
        state = _load_state()
        dev = state.get("device_id")
        if not dev:
            dev = uuid.uuid4().hex[:12]
            state["device_id"] = dev
            _save_state(state)
        return dev


def get_folder() -> str:
    return _load_state().get("folder") or ""


def is_enabled() -> bool:
    return bool(_load_state().get("enabled")) and bool(get_folder())


def folder_available() -> bool:
    return bool(get_folder()) and os.path.isdir(get_folder())


def device_name() -> str:
    return _load_state().get("device_name") or ""


def set_device_name(name: str):
    with _LOCK:
        state = _load_state()
        state["device_name"] = (name or "").strip()
        _save_state(state)


def messages_read_ts() -> str:
    """UTC stamp of the newest chat message this computer has seen (local — the
    read marker is per-machine, never synced). '' = nothing read yet."""
    return _load_state().get("messages_read_ts") or ""


def set_messages_read_ts(ts: str):
    with _LOCK:
        state = _load_state()
        # Never move the marker backwards.
        if (ts or "") > (state.get("messages_read_ts") or ""):
            state["messages_read_ts"] = ts or ""
            _save_state(state)


def local_get(key: str, default=None):
    """Read one per-machine value from sync_state.json (never synced)."""
    return _load_state().get(key, default)


def local_set(key: str, value):
    """Write one per-machine value to sync_state.json (never synced)."""
    with _LOCK:
        state = _load_state()
        state[key] = value
        _save_state(state)


def notify_downloads() -> bool:
    """True when THIS computer shows the download/peer-update notifications
    (v2.96) — a per-machine flag ('רק אני'), toggled in the settings screen."""
    return bool(_load_state().get("notify_downloads"))


def set_notify_downloads(on: bool):
    local_set("notify_downloads", bool(on))


def is_manager_device() -> bool:
    """True if THIS computer was designated the manager (#5rhe9). Local flag — the
    manager's change-log + undo controls only appear here."""
    return bool(_load_state().get("is_manager"))


def set_manager_device(on: bool):
    with _LOCK:
        state = _load_state()
        state["is_manager"] = bool(on)
        _save_state(state)


def last_run_info() -> dict:
    s = _load_state()
    return {"last_run": s.get("last_run") or "", "last_error": s.get("last_error") or "",
            "pending": _pending_count()}


def _pending_count() -> int:
    try:
        with open(_outbox_path(), "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def detect_drive_folders() -> list:
    """Best-effort discovery of a Google Drive for Desktop root on this machine.
    Handles both the English 'My Drive' and the Hebrew 'האחסון שלי' folder names
    (Drive localises this to the Windows language — #ysqq0)."""
    found = []
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        for name in _MY_DRIVE_NAMES:
            p = f"{letter}:\\{name}"
            if os.path.isdir(p):
                found.append(p)
    home = os.path.expanduser("~")
    for pat in ("Google Drive", "GoogleDrive", *_MY_DRIVE_NAMES):
        p = os.path.join(home, pat)
        if os.path.isdir(p):
            found.append(p)
    return found


def _find_drive_exe() -> str:
    """Locate GoogleDriveFS.exe (the Drive for Desktop client) so we can start it
    if it isn't running. Checks the standard Program Files install and its
    version-stamped subfolders. Returns '' when not found."""
    roots = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "Google", "Drive File Stream"))
    for d in roots:
        direct = os.path.join(d, "GoogleDriveFS.exe")
        if os.path.isfile(direct):
            return direct
        if os.path.isdir(d):
            # Newest version subfolder first (e.g. '105.0.3.0').
            for sub in sorted(os.listdir(d), reverse=True):
                exe = os.path.join(d, sub, "GoogleDriveFS.exe")
                if os.path.isfile(exe):
                    return exe
    return ""


_drive_launch_tried = False


def ensure_drive_running() -> bool:
    """If no Drive root is mounted (Drive for Desktop hasn't started yet — common
    right after a reboot, #kzuo2), try to launch it in the background. Best-effort
    and non-blocking: returns True if a Drive root is already present, otherwise
    fires the launcher once per app session and returns False (the mount appears a
    few seconds later, and the periodic sync picks it up automatically)."""
    global _drive_launch_tried
    if sys.platform != "win32":
        return bool(detect_drive_folders())
    if detect_drive_folders():
        return True
    if _drive_launch_tried:
        return False
    _drive_launch_tried = True
    exe = _find_drive_exe()
    if not exe:
        return False
    try:
        flags = 0x00000008 | 0x08000000    # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen([exe], creationflags=flags, close_fds=True)
    except Exception:
        return False
    return False


# A FIXED subfolder name. Because both computers derive the same canonical name
# under "My Drive", they land on the exact same shared folder with zero manual
# coordination — no path typing, no name matching, no backup-folder trap.
SHARED_SUBFOLDER = "מנהל-חלוקה-משותף"


def drive_installed() -> bool:
    """True when Google Drive for Desktop appears to be present on this machine
    (a 'My Drive' root exists)."""
    return bool(detect_drive_folders())


def default_shared_folder() -> str:
    """The canonical shared-folder path inside 'My Drive' for one-click setup.
    Returns '' when no Drive root is found. Does NOT create it (caller decides)."""
    roots = detect_drive_folders()
    if not roots:
        return ""
    return os.path.join(roots[0], SHARED_SUBFOLDER)


def suggested_device_name() -> str:
    """A friendly default name for this computer — its Windows hostname."""
    existing = device_name()
    if existing:
        return existing
    try:
        host = socket.gethostname() or ""
    except OSError:
        host = ""
    return host.strip() or "מחשב"


def auto_setup() -> dict:
    """One-click sync setup: find 'My Drive', create the canonical shared folder
    inside it, name this computer after its hostname (if unnamed), enable + seed,
    then pull whatever the other computer already put there.

    Returns {'ok': bool, 'reason': str, 'folder': str, 'seeded': int,
             'applied': int, 'others': int}. reason='no_drive' when Drive for
     Desktop is not installed; the caller shows the download guidance."""
    folder = default_shared_folder()
    if not folder:
        return {"ok": False, "reason": "no_drive", "folder": "", "seeded": 0,
                "applied": 0, "others": 0}
    if not device_name():
        set_device_name(suggested_device_name())
    seeded = enable_sync(folder, seed=True)
    res = run_sync()
    return {"ok": True, "reason": "", "folder": folder, "seeded": seeded,
            "applied": res.get("applied", 0), "others": other_device_count(folder)}


# ─── Writing changes (the local journal) ─────────────────────────────────────

def _setting_syncable(key: str) -> bool:
    if key in EXCLUDED_SETTINGS:
        return False
    return not any(key.startswith(p) for p in EXCLUDED_SETTING_PREFIXES)


def log_change(op: str, payload: dict):
    """Called by database.py after every successful data write. Appends one
    record to the local outbox and tries to flush it to the shared folder.
    No-ops while sync is disabled or while APPLYING remote records."""
    global _APPLYING
    if _APPLYING or not is_enabled():
        return
    if op == "setting" and not _setting_syncable(payload.get("key", "")):
        return
    with _LOCK:
        state = _load_state()
        # Device id is created inside THIS state dict — calling device_id() here
        # would save a separate copy that our own _save_state below overwrites.
        dev = state.get("device_id")
        if not dev:
            dev = uuid.uuid4().hex[:12]
            state["device_id"] = dev
        seq = int(state.get("seq") or 0) + 1
        state["seq"] = seq
        rec = {"seq": seq, "ts": _utc_now(), "dev": dev, "op": op, **payload}
        if op == "setting":
            state.setdefault("setting_ts", {})[payload.get("key", "")] = rec["ts"]
        with open(_outbox_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _save_state(state)
    if _DEFER_FLUSH:
        return     # a bulk seed is running — it flushes once when done
    try:
        flush()
    except Exception:
        pass   # stays in the outbox for the next run


def _journal_path(dev: str) -> str:
    return os.path.join(get_folder(), f"{JOURNAL_PREFIX}{dev}.jsonl")


def flush() -> int:
    """Move buffered outbox records into this device's journal in the shared
    folder. Returns how many were pushed (0 when offline/nothing pending)."""
    if not is_enabled() or not folder_available():
        return 0
    with _LOCK:
        try:
            with open(_outbox_path(), "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            return 0
        if not lines:
            return 0
        with open(_journal_path(device_id()), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        # Truncate the outbox only after the shared write succeeded. A crash in
        # between would duplicate lines — harmless, dedup'd by seq on apply.
        with open(_outbox_path(), "w", encoding="utf-8") as f:
            f.write("")
        return len(lines)


# ─── Applying remote changes ─────────────────────────────────────────────────

def _read_new_lines(path: str, offset: int):
    """Read only the bytes appended since `offset`, returning
    (complete_lines, new_offset). Stops at the last newline so a line that is
    still mid-download by Drive is left for the next cycle (never half-parsed).
    Byte offsets are safe on UTF-8 because a newline byte never appears inside a
    multibyte character. If the file shrank (rotated/rewritten), re-read from 0."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size < offset:
            offset = 0
        f.seek(offset)
        chunk = f.read()
    nl = chunk.rfind(b"\n")
    if nl == -1:
        return [], offset          # no complete line yet
    complete = chunk[:nl + 1]
    text = complete.decode("utf-8", errors="replace")
    return [ln for ln in text.split("\n") if ln.strip()], offset + len(complete)


def _recipient_columns(conn) -> set:
    return {row["name"] for row in conn.execute("PRAGMA table_info(recipients)")}


def _find_recipient_by_guid(conn, guid: str):
    if not guid:
        return None
    return conn.execute("SELECT * FROM recipients WHERE guid=?", (guid,)).fetchone()


def _adopt_match(conn, data: dict):
    """When a guid is unknown, try to recognise the same PERSON that already
    exists locally (both machines started from a copy of the same data):
    external_id first, else exact full_name + phone1. Returns the row or None."""
    ext = (data.get("external_id") or "").strip()
    if ext:
        row = conn.execute(
            "SELECT * FROM recipients WHERE TRIM(COALESCE(external_id,''))=?",
            (ext,)).fetchone()
        if row:
            return row
    name = (data.get("full_name") or "").strip()
    phone = (data.get("phone1") or "").strip()
    if name:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE TRIM(full_name)=?", (name,)).fetchall()
        if len(rows) == 1 and (not phone or (rows[0]["phone1"] or "").strip() == phone):
            return rows[0]
    return None


# Human labels for the change-log summary (#5rhe9).
_FIELD_LABELS_HE = {
    "full_name": "שם", "first_name": "שם פרטי", "last_name": "שם משפחה",
    "phone1": "טלפון", "phone2": "טלפון 2", "phone3": "טלפון 3",
    "address": "כתובת", "area": "אזור", "souls": "נפשות", "frequency": "תדירות",
    "status": "סטטוס", "notes": "הערות", "priority": "עדיפות",
    "id_number": "ת.ז. בעל", "spouse_id_number": "ת.ז. אשה",
    "children_total": "מספר ילדים", "marital_status": "מצב אישי",
    "email": "אימייל", "synagogue": "בית כנסת", "income": "הכנסות",
    "representative": "נציג", "external_id": "מס' מזהה",
}


def _record_incoming(conn, op, guid, name, summary, before, after, dev):
    """Log an applied incoming change so the manager can review/undo it (#5rhe9).
    Only runs on the manager computer (guarded by _RECORD_INCOMING)."""
    try:
        conn.execute(
            "INSERT INTO sync_incoming (applied_at, author_device, author_name, op, "
            "target_guid, target_name, summary, before_json, after_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_utc_now(), dev or "", "", op, guid or "", name or "", summary or "",
             json.dumps(before, ensure_ascii=False) if before is not None else "",
             json.dumps(after, ensure_ascii=False) if after is not None else ""))
    except Exception:
        pass


def _diff_summary(before: dict, fields: dict) -> str:
    """Short Hebrew description of what changed in a recipient upsert."""
    changed = []
    for k, v in fields.items():
        old = "" if before is None else before.get(k, "")
        if str(old or "") != str(v or ""):
            label = _FIELD_LABELS_HE.get(k)
            if label:
                changed.append(f"{label}: '{old}' ← '{v}'")
    if not changed:
        return "עודכן"
    return " · ".join(changed[:6]) + (" ועוד…" if len(changed) > 6 else "")


def _apply_rec_upsert(conn, rec: dict):
    guid = rec.get("guid") or ""
    data = rec.get("data") or {}
    if not guid or not data:
        return
    cols = _recipient_columns(conn)
    fields = {k: v for k, v in data.items() if k in cols and k not in ("id", "guid")}
    local = _find_recipient_by_guid(conn, guid)
    if local is None:
        match = _adopt_match(conn, data)
        if match is not None:
            conn.execute("UPDATE recipients SET guid=? WHERE id=?", (guid, match["id"]))
            local = _find_recipient_by_guid(conn, guid)
    name = data.get("full_name") or (dict(local).get("full_name") if local else "") or ""
    if local is not None:
        # Last-write-wins: apply only if the incoming edit is newer than ours.
        local_ts = local["updated_at"] or ""
        incoming_ts = data.get("updated_at") or rec.get("ts") or ""
        if local_ts and incoming_ts and incoming_ts <= local_ts:
            return
        before = dict(local)
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE recipients SET {sets} WHERE id=?",
                     list(fields.values()) + [local["id"]])
        if _RECORD_INCOMING:
            _record_incoming(conn, "rec_upsert", guid, name,
                             _diff_summary(before, fields), before, fields, rec.get("dev"))
    else:
        fields["guid"] = guid
        keys = list(fields.keys())
        conn.execute(
            f"INSERT INTO recipients ({','.join(keys)}) VALUES ({','.join(['?'] * len(keys))})",
            [fields[k] for k in keys])
        if _RECORD_INCOMING:
            _record_incoming(conn, "rec_upsert", guid, name,
                             f"נוסף מקבל חדש: {name}", None, fields, rec.get("dev"))


def _apply_rec_delete(conn, rec: dict):
    local = _find_recipient_by_guid(conn, rec.get("guid") or "")
    if local is None:
        return
    before = dict(local)
    rid = local["id"]
    deleted = False
    if rec.get("force"):
        conn.execute("DELETE FROM distributions WHERE recipient_id=?", (rid,))
        conn.execute("DELETE FROM change_log WHERE recipient_id=?", (rid,))
        conn.execute("DELETE FROM recipients WHERE id=?", (rid,))
        deleted = True
    else:
        n = conn.execute("SELECT COUNT(*) AS c FROM distributions WHERE recipient_id=?",
                         (rid,)).fetchone()["c"]
        if n == 0:
            conn.execute("DELETE FROM recipients WHERE id=?", (rid,))
            deleted = True
    if deleted and _RECORD_INCOMING:
        _record_incoming(conn, "rec_delete", rec.get("guid") or "",
                         before.get("full_name", ""),
                         f"נמחק מקבל: {before.get('full_name','')}", before, None, rec.get("dev"))


def _apply_batch_add(conn, rec: dict):
    guid = rec.get("guid") or ""
    if not guid:
        return
    if conn.execute("SELECT 1 FROM dist_batches WHERE guid=?", (guid,)).fetchone():
        return   # already applied (idempotent)
    b = rec.get("batch") or {}
    cur = conn.execute(
        "INSERT INTO dist_batches (dist_name, dist_date, products, quantity, "
        "distributor, general_note, recipient_count, souls_total, guid) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (b.get("dist_name", ""), b.get("dist_date", ""), b.get("products", ""),
         b.get("quantity", 0), b.get("distributor", ""), b.get("general_note", ""),
         b.get("recipient_count", 0), b.get("souls_total", 0), guid))
    batch_id = cur.lastrowid
    affected = []
    for row in rec.get("rows") or []:
        if row.get("guid") and conn.execute(
                "SELECT 1 FROM distributions WHERE guid=?", (row["guid"],)).fetchone():
            continue
        local = _find_recipient_by_guid(conn, row.get("rec_guid") or "")
        rid = local["id"] if local is not None else None
        conn.execute(
            "INSERT INTO distributions (recipient_id, recipient_name, dist_date, "
            "area, souls, what_dist, quantity, distributor, notes, batch_id, "
            "received, guid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, row.get("recipient_name", ""), b.get("dist_date", ""),
             row.get("area", ""), row.get("souls", 0), b.get("products", ""),
             b.get("quantity", 0) if row.get("received", 1) else 0,
             b.get("distributor", ""), row.get("notes", ""), batch_id,
             1 if row.get("received", 1) else 0, row.get("guid") or uuid.uuid4().hex))
        if rid is not None:
            affected.append((rid, bool(row.get("received", 1))))
    # Re-derive each affected recipient's last/next from the history that now
    # exists locally (idempotent, uses the LOCAL frequency), and clear the weekly
    # tick for those who actually received — mirroring bulk_add_distributions.
    for rid, got in affected:
        db._recompute_recipient_dates(conn, rid)
        if got:
            conn.execute("UPDATE recipients SET weekly_status='' WHERE id=?", (rid,))


def _apply_dist_add(conn, rec: dict):
    """A single legacy history row (no batch) from the initial snapshot."""
    guid = rec.get("guid") or ""
    d = rec.get("data") or {}
    if not guid or conn.execute("SELECT 1 FROM distributions WHERE guid=?",
                                (guid,)).fetchone():
        return
    local = _find_recipient_by_guid(conn, rec.get("rec_guid") or "")
    rid = local["id"] if local is not None else None
    conn.execute(
        "INSERT INTO distributions (recipient_id, recipient_name, dist_date, area, "
        "souls, what_dist, quantity, distributor, notes, batch_id, received, guid) "
        "VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?)",
        (rid, d.get("recipient_name", ""), d.get("dist_date", ""), d.get("area", ""),
         d.get("souls", 0), d.get("what_dist", ""), d.get("quantity", 0),
         d.get("distributor", ""), d.get("notes", ""),
         1 if d.get("received", 1) else 0, guid))
    if rid is not None:
        db._recompute_recipient_dates(conn, rid)


def _apply_batch_delete(conn, rec: dict):
    row = conn.execute("SELECT id FROM dist_batches WHERE guid=?",
                       (rec.get("guid") or "",)).fetchone()
    if not row:
        return
    batch_id = row["id"]
    rec_ids = [r["recipient_id"] for r in conn.execute(
        "SELECT DISTINCT recipient_id FROM distributions "
        "WHERE batch_id=? AND recipient_id IS NOT NULL", (batch_id,))]
    conn.execute("DELETE FROM distributions WHERE batch_id=?", (batch_id,))
    conn.execute("DELETE FROM dist_batches WHERE id=?", (batch_id,))
    for rid in rec_ids:
        db._recompute_recipient_dates(conn, rid)


def _apply_dist_delete(conn, rec: dict):
    row = conn.execute("SELECT id, recipient_id FROM distributions WHERE guid=?",
                       (rec.get("guid") or "",)).fetchone()
    if not row:
        return
    conn.execute("DELETE FROM distributions WHERE id=?", (row["id"],))
    if row["recipient_id"] is not None:
        db._recompute_recipient_dates(conn, row["recipient_id"])


def _apply_msg_add(conn, rec: dict):
    """A chat message from another computer (#ya4f7). Idempotent by guid."""
    guid = rec.get("guid") or ""
    body = rec.get("body") or ""
    if not guid or not body:
        return
    if conn.execute("SELECT 1 FROM messages WHERE guid=?", (guid,)).fetchone():
        return
    conn.execute(
        "INSERT INTO messages (guid, author_device, author_name, body, created_at) "
        "VALUES (?,?,?,?,?)",
        (guid, rec.get("author_device", ""), rec.get("author_name", ""),
         body, rec.get("created_at", "")))


def _apply_msg_delete(conn, rec: dict):
    """A chat message deleted by its author on another computer (#msgdel)."""
    guid = rec.get("guid") or ""
    if not guid:
        return
    conn.execute("DELETE FROM messages WHERE guid=?", (guid,))


def _apply_msg_read(conn, rec: dict):
    """A chat read-marker from another computer (#ya4f7 ✓✓). LWW by read_ts."""
    dev = rec.get("device") or ""
    read_ts = rec.get("read_ts") or ""
    if not dev or not read_ts:
        return
    row = conn.execute("SELECT read_ts FROM message_reads WHERE device=?", (dev,)).fetchone()
    if row and (row["read_ts"] or "") >= read_ts:
        return
    conn.execute(
        "INSERT INTO message_reads (device, device_name, read_ts) VALUES (?,?,?) "
        "ON CONFLICT(device) DO UPDATE SET device_name=excluded.device_name, "
        "read_ts=excluded.read_ts",
        (dev, rec.get("device_name", ""), read_ts))


def _apply_fb_add(conn, rec: dict):
    """A feedback message ('הודעה למפתח') from another computer (#ce6a0).
    Idempotent by guid."""
    guid = rec.get("guid") or ""
    body = rec.get("body") or ""
    if not guid or not body:
        return
    if conn.execute("SELECT 1 FROM feedback WHERE guid=?", (guid,)).fetchone():
        return
    conn.execute(
        "INSERT INTO feedback (guid, author_name, host, version, body, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (guid, rec.get("author_name", ""), rec.get("host", ""),
         rec.get("version", ""), body, rec.get("created_at", "")))


def _apply_fb_status(conn, rec: dict):
    """A handled/open mark on a feedback message from another computer (#ce6a0).
    LWW by status_ts."""
    guid = rec.get("guid") or ""
    status = rec.get("status") or ""
    ts = rec.get("ts") or ""
    if not guid or status not in ("open", "done"):
        return
    row = conn.execute("SELECT status_ts FROM feedback WHERE guid=?", (guid,)).fetchone()
    if not row or (row["status_ts"] or "") >= ts:
        return
    conn.execute("UPDATE feedback SET status=?, status_ts=? WHERE guid=?",
                 (status, ts, guid))


def _apply_tz_add(conn, rec: dict):
    """A tzintuk campaign sent from another computer (v2.81). Idempotent by
    guid — also powers the cross-machine double-send guard."""
    guid = rec.get("guid") or ""
    if not guid:
        return
    if conn.execute("SELECT 1 FROM tzintuk_campaigns WHERE guid=?",
                    (guid,)).fetchone():
        return
    # A seed snapshot carries the final results inside tz_add itself (its
    # tz_update has the same stamp and would be rejected as "not newer").
    conn.execute(
        "INSERT INTO tzintuk_campaigns (guid, name, sent_at, dist_date, "
        "template_id, campaign_id, device, total, status, status_ts, "
        "delivered, failed, report_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (guid, rec.get("name", ""), rec.get("sent_at", ""),
         rec.get("dist_date", ""), str(rec.get("template_id", "")),
         rec.get("campaign_id", ""), rec.get("device", ""),
         int(rec.get("total") or 0), rec.get("status") or "sending",
         rec.get("status_ts") or rec.get("sent_at", ""),
         int(rec.get("delivered") or 0), int(rec.get("failed") or 0),
         rec.get("report_json") or ""))


def _apply_tz_update(conn, rec: dict):
    """Progress/result of a tzintuk campaign from another computer. LWW by
    status_ts."""
    guid = rec.get("guid") or ""
    ts = rec.get("ts") or ""
    if not guid:
        return
    row = conn.execute("SELECT status_ts FROM tzintuk_campaigns WHERE guid=?",
                       (guid,)).fetchone()
    if not row:
        return
    local_ts = row["status_ts"] or ""
    # Records written before v2.97 stamped a scheduled campaign with its
    # planned (future) time — no genuine update can be "older" than that, so a
    # future local stamp is treated as stale instead of blocking forever.
    if local_ts > db._utc_now():
        local_ts = ""
    if local_ts >= ts:
        return
    sets = "delivered=?, failed=?, status=?, status_ts=?, report_json=?"
    args = [int(rec.get("delivered") or 0), int(rec.get("failed") or 0),
            rec.get("status", "sending"), ts, rec.get("report_json", "")]
    # A scheduled campaign that ran carries the real campaignId + run time
    # (#xi85i); older-version payloads simply don't have these keys.
    if rec.get("campaign_id"):
        sets += ", campaign_id=?"
        args.append(str(rec.get("campaign_id")))
    if rec.get("sent_at"):
        sets += ", sent_at=?"
        args.append(rec.get("sent_at"))
    conn.execute(f"UPDATE tzintuk_campaigns SET {sets} WHERE guid=?",
                 (*args, guid))


def _apply_setting(conn, rec: dict, state: dict):
    key = rec.get("key") or ""
    if not key or not _setting_syncable(key):
        return
    known = state.setdefault("setting_ts", {})
    if (rec.get("ts") or "") <= (known.get(key) or ""):
        return   # our own (or a later) write already covers this key
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                 (key, rec.get("value", "")))
    known[key] = rec.get("ts") or ""


_APPLIERS = {
    "rec_upsert":   _apply_rec_upsert,
    "rec_delete":   _apply_rec_delete,
    "batch_add":    _apply_batch_add,
    "batch_delete": _apply_batch_delete,
    "dist_delete":  _apply_dist_delete,
    "dist_add":     _apply_dist_add,
    "msg_add":      _apply_msg_add,
    "msg_delete":   _apply_msg_delete,
    "msg_read":     _apply_msg_read,
    "fb_add":       _apply_fb_add,
    "fb_status":    _apply_fb_status,
    "tz_add":       _apply_tz_add,
    "tz_update":    _apply_tz_update,
}


def pull_changes() -> int:
    """Read the OTHER devices' journals and apply every record not yet seen.
    Returns how many records were applied."""
    global _APPLYING, _RECORD_INCOMING
    if not is_enabled() or not folder_available():
        return 0
    applied = 0
    with _LOCK:
        state = _load_state()
        my_dev = device_id()
        seen = state.setdefault("applied", {})       # dev → highest seq applied (safety dedup)
        offsets = state.setdefault("offsets", {})    # dev → byte position already read
        _APPLYING = True
        # On the manager machine, record incoming recipient changes for undo (#5rhe9).
        _RECORD_INCOMING = bool(state.get("is_manager"))
        try:
            with db.get_connection() as conn:
                for path in sorted(glob.glob(os.path.join(get_folder(),
                                                          JOURNAL_PREFIX + "*.jsonl"))):
                    dev = os.path.basename(path)[len(JOURNAL_PREFIX):-len(".jsonl")]
                    if dev == my_dev:
                        continue
                    last = int(seen.get(dev) or 0)
                    off = int(offsets.get(dev) or 0)
                    try:
                        lines, new_off = _read_new_lines(path, off)
                    except OSError:
                        continue
                    for ln in lines:
                        try:
                            rec = json.loads(ln)
                        except ValueError:
                            continue
                        seq = int(rec.get("seq") or 0)
                        if seq <= last:
                            continue   # already applied (offset reset / overlap)
                        op = rec.get("op")
                        try:
                            if op == "setting":
                                _apply_setting(conn, rec, state)
                                applied += 1
                            elif op in _APPLIERS:
                                _APPLIERS[op](conn, rec)
                                applied += 1
                        except Exception:
                            pass   # one bad record must not stall the stream
                        last = seq
                    seen[dev] = last
                    offsets[dev] = new_off
        finally:
            _APPLYING = False
            _RECORD_INCOMING = False
        state["last_run"] = _utc_now()
        _save_state(state)
    return applied


def run_sync() -> dict:
    """One full cycle: push buffered changes, then pull+apply the others'.
    Returns {'pushed': n, 'applied': n, 'error': str}."""
    out = {"pushed": 0, "applied": 0, "error": ""}
    try:
        out["pushed"] = flush()
        out["applied"] = pull_changes()
    except Exception as e:
        out["error"] = str(e)
        with _LOCK:
            state = _load_state()
            state["last_error"] = str(e)
            _save_state(state)
    return out


# ─── Enable / seed ───────────────────────────────────────────────────────────

def snapshot() -> int:
    """Write the ENTIRE current dataset into the journal, so a second computer
    joining the folder receives everything. Idempotent on the receiving side
    (guids dedupe). Returns the number of records written."""
    global _DEFER_FLUSH
    n = 0
    _DEFER_FLUSH = True   # buffer every record, then flush the whole seed at once
    try:
        return _snapshot_body()
    finally:
        _DEFER_FLUSH = False
        try:
            flush()
        except Exception:
            pass   # stays in the outbox for the next run


def _snapshot_body() -> int:
    n = 0
    with db.get_connection() as conn:
        recs = [dict(r) for r in conn.execute("SELECT * FROM recipients")]
        batches = [dict(r) for r in conn.execute("SELECT * FROM dist_batches")]
        dists = [dict(r) for r in conn.execute("SELECT * FROM distributions")]
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    guid_by_id = {r["id"]: r.get("guid") or "" for r in recs}
    for r in recs:
        data = {k: v for k, v in r.items() if k != "id"}
        if not data.get("updated_at"):
            data["updated_at"] = data.get("created_at") or _utc_now()
        log_change("rec_upsert", {"guid": r.get("guid") or "", "data": data})
        n += 1
    rows_by_batch = {}
    for d in dists:
        if d.get("batch_id"):
            rows_by_batch.setdefault(d["batch_id"], []).append(d)
    for b in batches:
        rows = [{"guid": d.get("guid") or "", "rec_guid": guid_by_id.get(d.get("recipient_id"), ""),
                 "recipient_name": d.get("recipient_name", ""), "area": d.get("area", ""),
                 "souls": d.get("souls", 0), "notes": d.get("notes", ""),
                 "received": d.get("received", 1)} for d in rows_by_batch.get(b["id"], [])]
        log_change("batch_add", {
            "guid": b.get("guid") or "",
            "batch": {k: b.get(k, "") for k in ("dist_name", "dist_date", "products",
                                                "quantity", "distributor", "general_note",
                                                "recipient_count", "souls_total")},
            "rows": rows})
        n += 1
    for d in dists:
        if not d.get("batch_id"):
            log_change("dist_add", {
                "guid": d.get("guid") or "",
                "rec_guid": guid_by_id.get(d.get("recipient_id"), ""),
                "data": {k: d.get(k, "") for k in ("recipient_name", "dist_date", "area",
                                                   "souls", "what_dist", "quantity",
                                                   "distributor", "notes", "received")}})
            n += 1
    for key, value in settings.items():
        if _setting_syncable(key):
            log_change("setting", {"key": key, "value": value})
            n += 1
    # Chat history so a joining computer sees past messages (#ya4f7).
    with db.get_connection() as conn:
        msgs = [dict(r) for r in conn.execute(
            "SELECT * FROM messages ORDER BY created_at ASC")]
    for m in msgs:
        log_change("msg_add", {"guid": m.get("guid") or "",
                               "author_device": m.get("author_device", ""),
                               "author_name": m.get("author_name", ""),
                               "body": m.get("body", ""),
                               "created_at": m.get("created_at", "")})
        n += 1
    with db.get_connection() as conn:
        reads = [dict(r) for r in conn.execute("SELECT * FROM message_reads")]
    for rd in reads:
        log_change("msg_read", {"device": rd.get("device", ""),
                                "device_name": rd.get("device_name", ""),
                                "read_ts": rd.get("read_ts", "")})
        n += 1
    # Feedback messages ('הודעות למפתח') so the manager sees reports left on the
    # other computer, including their handled-marks (#ce6a0).
    with db.get_connection() as conn:
        fbs = [dict(r) for r in conn.execute("SELECT * FROM feedback ORDER BY created_at ASC")]
    for fb in fbs:
        log_change("fb_add", {"guid": fb.get("guid") or "",
                              "author_name": fb.get("author_name", ""),
                              "host": fb.get("host", ""),
                              "version": fb.get("version", ""),
                              "body": fb.get("body", ""),
                              "created_at": fb.get("created_at", "")})
        n += 1
        if fb.get("status") == "done" and fb.get("status_ts"):
            log_change("fb_status", {"guid": fb.get("guid") or "",
                                     "status": "done", "ts": fb.get("status_ts", "")})
            n += 1
    # Tzintuk-campaign history (v2.81) — so a joining computer sees past sends
    # and its double-send guard covers campaigns sent from this machine.
    with db.get_connection() as conn:
        camps = [dict(r) for r in conn.execute(
            "SELECT * FROM tzintuk_campaigns ORDER BY sent_at ASC")]
    for c in camps:
        log_change("tz_add", {k: c.get(k, "") for k in
                              ("guid", "name", "sent_at", "dist_date",
                               "template_id", "campaign_id", "device", "total",
                               "status", "status_ts", "delivered", "failed",
                               "report_json")})
        n += 1
        if c.get("status_ts"):
            log_change("tz_update", {"guid": c.get("guid") or "",
                                     "delivered": c.get("delivered", 0),
                                     "failed": c.get("failed", 0),
                                     "status": c.get("status", "sending"),
                                     "ts": c.get("status_ts", ""),
                                     "report_json": c.get("report_json", "")})
            n += 1
    return n


def enable_sync(folder: str, seed: bool = True) -> int:
    """Turn sync on against the given shared folder. When seed=True the whole
    current dataset is journaled so other computers receive it. Returns the
    number of seeded records."""
    os.makedirs(folder, exist_ok=True)
    with _LOCK:
        state = _load_state()
        state["folder"] = folder
        state["enabled"] = True
        _save_state(state)
    n = snapshot() if seed else 0
    flush()
    return n


def disable_sync():
    with _LOCK:
        state = _load_state()
        state["enabled"] = False
        _save_state(state)


def other_device_count(folder: str = "") -> int:
    """How many OTHER devices have written a journal into the shared folder.
    0 means this computer is alone there — a strong sign the folder is not truly
    shared with the second computer (e.g. a per-machine Drive *backup* folder)."""
    folder = folder or get_folder()
    if not folder or not os.path.isdir(folder):
        return 0
    my = device_id()
    devs = set()
    for path in glob.glob(os.path.join(folder, JOURNAL_PREFIX + "*.jsonl")):
        dev = os.path.basename(path)[len(JOURNAL_PREFIX):-len(".jsonl")]
        if dev and dev != my:
            devs.add(dev)
    return len(devs)


def looks_like_backup_folder(path: str) -> bool:
    """Heuristic: does this path look like a Google Drive *per-computer backup*
    location (Downloads/Desktop/Documents) rather than a genuinely SHARED
    'My Drive' / 'Shared drives' folder? Backup folders sync to the cloud but are
    NOT mirrored to the other computer, so sync silently never connects. We warn
    when the path sits under a known backup root and shows no 'My Drive' marker."""
    p = (path or "").replace("\\", "/").lower()
    if not p:
        return False
    shared_markers = ("my drive", "/mydrive", "shared drives", "shareddrives",
                      "drive/משותף", "google drive/my drive",
                      "האחסון שלי", "התיקיה שלי")   # Hebrew 'My Drive' (#ysqq0)
    if any(m in p for m in shared_markers):
        return False
    backup_markers = ("/downloads", "/desktop", "/documents",
                      "/הורדות", "/שולחן העבודה", "/מסמכים")
    return any(m in p for m in backup_markers)

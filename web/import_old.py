# -*- coding: utf-8 -*-
"""One-time import: a COPY of the desktop program's data.db -> the site's database.

    <python 3.12> -m web.import_old --from <path to a copy of data.db>
                  [--sent-history <sent_history.json>] [--replace]

The source file is opened read-only and is never changed. Everything is carried over as it
is (cards, every history row — no-shows and rows without a card included — the batches, the
need weights and the one-timers' pause); nothing is "cleaned". The only things left behind
are the three columns the desktop program derived (last / next distribution, the weekly
tick): here they are computed, not stored.

`--sent-history`: lists that were sent to the manager as files and are taken as having
happened (decision 15/11/2026) — [{"date": "YYYY-MM-DD", "guids": [...]}, ...].

The report printed at the end holds numbers only — no names.
"""
import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta

from . import config, planner, service, store
from .engine import selection


class ImportRefused(Exception):
    """The import was refused; nothing was written."""


def _ro_connect(path: str) -> sqlite3.Connection:
    if not os.path.isfile(path):
        raise ImportRefused(f"source database not found: {path}")
    conn = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table: str) -> list:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def assert_not_publishable(folder: str) -> None:
    """The data folder holds personal data and the repository is public: when the folder
    sits inside a git work tree it must be ignored by git, or the import refuses to run."""
    if os.environ.get("HALUKA_WEB_SKIP_GIT_GUARD") == "1":
        return
    os.makedirs(folder, exist_ok=True)
    probe = os.path.join(folder, "haluka.db")
    try:
        inside = subprocess.run(["git", "-C", folder, "rev-parse", "--is-inside-work-tree"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return                                       # no git here: nothing can be published
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return
    ignored = subprocess.run(["git", "-C", folder, "check-ignore", "-q", probe],
                             capture_output=True, timeout=15)
    if ignored.returncode != 0:
        raise ImportRefused(
            f"refusing to put personal data in {folder}: the folder is inside a git "
            "repository and is NOT ignored (add it to .gitignore first)")


def _derived(seed: str, old) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"manhal-haluka/web/import/{seed}/{old}").hex


def import_old(src: str, dest: str, *, sent_history: str = None, replace: bool = False,
               now: datetime = None, backup_dir: str = None, closed_through: date = None) -> dict:
    """Build `dest` from the copy at `src`. Returns the report (numbers only)."""
    now = now or config.now()
    dest_dir = os.path.dirname(os.path.abspath(dest))
    assert_not_publishable(dest_dir)
    if os.path.exists(dest):
        if not replace:
            raise ImportRefused(f"{dest} already exists — pass --replace to rebuild it "
                               "(the existing file is backed up first)")
        store.backup(dest, backup_dir or os.path.join(dest_dir, "backups"), "before-reimport", now)

    sent = []
    if sent_history:
        with open(sent_history, encoding="utf-8") as f:
            sent = json.load(f)
        ok = isinstance(sent, list) and all(
            isinstance(i, dict) and planner.valid_iso(str(i.get("date") or "")[:10])
            and isinstance(i.get("guids") or [], list) for i in sent)
        if not ok:
            raise ImportRefused("sent-history file must be a list of {date: YYYY-MM-DD, guids: [...]}")

    src_conn = _ro_connect(src)
    try:
        rec_cols = _columns(src_conn, "recipients")
        if "guid" not in rec_cols:
            raise ImportRefused("the source has no guid column — too old a version to import")
        old_recs = [dict(r) for r in src_conn.execute("SELECT * FROM recipients ORDER BY id")]
        old_dist = [dict(r) for r in src_conn.execute("SELECT * FROM distributions ORDER BY id")]
        old_batches = [dict(r) for r in src_conn.execute("SELECT * FROM dist_batches ORDER BY id")]
        old_settings = {r["key"]: r["value"] for r in src_conn.execute("SELECT key, value FROM settings")}
    finally:
        src_conn.close()

    guids = [(r.get("guid") or "").strip() for r in old_recs]
    if any(not g for g in guids):
        raise ImportRefused(f"{sum(1 for g in guids if not g)} cards have no guid — refusing to guess")
    if len(set(guids)) != len(guids):
        raise ImportRefused("two cards share one guid — the source is damaged")

    tmp = dest + ".importing"
    for leftover in (tmp, tmp + "-journal"):
        if os.path.exists(leftover):
            os.remove(leftover)
    store.create(tmp)
    report = {"source": os.path.basename(src), "imported_at": now.strftime("%Y-%m-%d %H:%M")}
    conn = store.connect(tmp)
    try:
        with store.tx(conn):
            # ── cards ──
            id_to_guid = {}
            for r in old_recs:
                id_to_guid[r["id"]] = r["guid"].strip()
                vals = []
                for c in store.RECIPIENT_COLUMNS:
                    v = r.get(c)
                    if v is None and c != "priority":
                        v = 0 if c in store._INT_COLUMNS else ""
                    vals.append(v)
                conn.execute(
                    f"INSERT INTO recipients (id, guid, {', '.join(store.RECIPIENT_COLUMNS)}) "
                    f"VALUES (?, ?, {', '.join('?' * len(store.RECIPIENT_COLUMNS))})",
                    [r["id"], r["guid"].strip()] + vals)
            # ── batches ──
            batch_guid = {}
            for b in old_batches:
                g = (b.get("guid") or "").strip() or _derived("batch", b["id"])
                batch_guid[b["id"]] = g
                conn.execute(
                    "INSERT INTO batches (guid, dist_name, dist_date, products, quantity, distributor, "
                    "general_note, recipient_count, souls_total, holiday, created_at, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,'import')",
                    (g, b.get("dist_name") or "", b.get("dist_date") or "", b.get("products") or "",
                     b.get("quantity") or 0, b.get("distributor") or "", b.get("general_note") or "",
                     b.get("recipient_count") or 0, b.get("souls_total") or 0,
                     (b.get("holiday") or "").strip(), b.get("created_at")))
            # ── history: every row, as it is ──
            seen = set()
            orphans = no_show = bad_date = 0
            for d in old_dist:
                g = (d.get("guid") or "").strip() or _derived("dist", d["id"])
                if g in seen:
                    g = _derived("dist-dup", d["id"])
                seen.add(g)
                rg = id_to_guid.get(d.get("recipient_id"))
                received = 1 if d.get("received") is None else int(bool(d.get("received")))
                orphans += rg is None
                no_show += received == 0
                bad_date += not planner.valid_iso(d.get("dist_date"))
                conn.execute(
                    "INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, received, "
                    "holiday, what_dist, quantity, distributor, notes, area, souls, batch_guid, "
                    "created_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'import')",
                    (g, rg, d.get("recipient_name") or "", d.get("dist_date") or "", received,
                     (d.get("holiday") or "").strip(), d.get("what_dist"), d.get("quantity"),
                     d.get("distributor"), d.get("notes"), d.get("area"), d.get("souls"),
                     batch_guid.get(d.get("batch_id")), d.get("created_at")))
            # ── settings the rules read ──
            for k, v in old_settings.items():
                if (k.startswith("need_w_") or k == "onetime_cooldown_weeks") and v is not None:
                    store.set_setting(conn, k, v)
            store.set_setting(conn, "default_portions", config.DEFAULT_PORTIONS)
            store.set_setting(conn, "default_reserve", config.DEFAULT_RESERVE)

            # ── do the dates computed here agree with the ones the desktop program kept? ──
            horizon = selection.upcoming_wednesday(now.date())
            ledger = planner.Ledger(horizon).load(store.load_received(conn))
            agree = differ = 0
            for r in old_recs:
                mine = planner.week_row(r, horizon, ledger)["last_distribution"]
                theirs = planner.valid_iso(r.get("last_distribution"))
                if mine == theirs:
                    agree += 1
                else:
                    differ += 1
            report["last_date_check"] = {"agree": agree, "differ": differ}

            # ── lists that were sent as files and count as having happened ──
            known = set(guids)
            names = {r["guid"].strip(): r.get("full_name") or "" for r in old_recs}
            sent_rows = sent_unknown = 0
            for item in sent:
                wed = selection.round_wednesday(date.fromisoformat(str(item["date"])[:10]))
                bg = _derived("sent-batch", wed.isoformat())
                members = [g for g in item.get("guids") or [] if g in known]
                sent_unknown += len(item.get("guids") or []) - len(members)
                conn.execute(
                    "INSERT INTO batches (guid, dist_name, dist_date, recipient_count, created_at, source) "
                    "VALUES (?,?,?,?,?,'sent-list')",
                    (bg, f"רשימה שנשלחה {wed.strftime('%d/%m/%Y')}", wed.isoformat(), len(members),
                     now.strftime("%Y-%m-%d %H:%M:%S")))
                for g in dict.fromkeys(members):
                    conn.execute(
                        "INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, received, "
                        "holiday, batch_guid, created_at, source) VALUES (?,?,?,?,1,'',?,?,'sent-list')",
                        (_derived("sent", f"{wed.isoformat()}/{g}"), g, names[g], wed.isoformat(), bg,
                         now.strftime("%Y-%m-%d %H:%M:%S")))
                    sent_rows += 1

            # ── where the history ends: weeks up to here are closed ──
            cur = service.current_week(now)
            last_round = None
            for row in store.load_received(conn):
                iso = planner.valid_iso(row["dist_date"])
                if not iso or planner.is_extra_round(iso, row["holiday"] or ""):
                    continue
                wed = selection.round_wednesday(date.fromisoformat(iso))
                if wed <= cur and (last_round is None or wed > last_round):
                    last_round = wed
            through = closed_through or last_round or (cur - timedelta(days=7))
            if through.weekday() != 2 or through > cur:
                raise ImportRefused("closed-through must be a Wednesday, not after the current week")
            store.set_meta(conn, "closed_through", through.isoformat())
            store.set_meta(conn, "imported_at", report["imported_at"])
            store.set_meta(conn, "imported_from", report["source"])

            active = [r for r in old_recs if planner.is_active(r)]
            by_freq = {}
            for r in active:
                if selection.is_regular(r):
                    k = (r.get("frequency") or "").strip() or "(קבוע בלי תדירות)"
                    by_freq[k] = by_freq.get(k, 0) + 1
            report.update({
                "cards": len(old_recs), "active": len(active),
                "regulars_by_frequency": by_freq,
                "one_time_first_or_second_priority": sum(1 for r in active if selection.is_one_time_candidate(r)),
                "not_taking_part": sum(1 for r in active if not planner.participation(r)),
                "history_rows": len(old_dist), "history_no_show_rows": no_show,
                "history_rows_without_card": orphans, "history_rows_bad_date": bad_date,
                "batches": len(old_batches),
                "sent_lists": len(sent), "sent_list_rows": sent_rows, "sent_list_unknown_guids": sent_unknown,
                "closed_through": through.isoformat(), "current_week": cur.isoformat(),
                "WARNING_current_week_counts_as_done": through >= cur,   # a round was already recorded this week: pass --closed-through to keep this Wednesday open
                "weeks_that_will_close_on_first_open": max(0, ((cur - through).days // 7) - 1),
            })
    except BaseException:
        conn.close()
        for leftover in (tmp, tmp + "-journal"):
            if os.path.exists(leftover):
                os.remove(leftover)
        raise
    conn.close()
    os.replace(tmp, dest)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import a copy of the desktop data.db into the site")
    ap.add_argument("--from", dest="src", required=True, help="path to a COPY of data.db")
    ap.add_argument("--sent-history", help="json of lists already sent (taken as received)")
    ap.add_argument("--replace", action="store_true", help="rebuild an existing site database")
    ap.add_argument("--to", dest="dest", default=None, help="site database (default: the data folder)")
    ap.add_argument("--closed-through", default=None,
                    help="the last Wednesday that already happened (default: the last regular round in the data)")
    args = ap.parse_args(argv)
    try:
        report = import_old(args.src, args.dest or config.db_path(),
                            sent_history=args.sent_history, replace=args.replace,
                            closed_through=date.fromisoformat(args.closed_through) if args.closed_through else None)
    except ImportRefused as e:
        print("IMPORT REFUSED:", e)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

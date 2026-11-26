# -*- coding: utf-8 -*-
"""A copy of the site's data that leaves the server, once a day.

The backups of web/backup_service.py live beside the database: if the server is lost, they
are lost with it. This sends a fresh, whole copy somewhere else. Run by the server's timer:
    <python> -m web.offsite            (exit 0 = a copy left and was checked, 1 = it did not)

Where to: Google Drive, when it was connected from the settings screen (web/drive.py) — or,
from the environment (one of the two, and then they come first):
    HALUKA_OFFSITE_DIR   a folder that is not on this server's own disk (a mounted drive).
                         The copy is written there, read back and compared, byte for byte.
    HALUKA_OFFSITE_CMD   a command that takes the file away; the word {file} is replaced by
                         the file's path. No shell. Exit 0 = it left.
The copy holds phones: where it goes must be private, and encrypted if it is not ours.
Nothing is ever deleted at the destination. The last result is kept in `offsite.json` in
the data folder, and the settings screen shows it (and says when no copy left for 2 days).
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime

from . import backup_service, config, drive, store

LATE_DAYS = 2                        # no copy for this many days = the screen warns
CMD_SECONDS = 900
_STAMP = "%Y-%m-%d %H:%M"


def target() -> tuple:
    """("dir", folder) / ("cmd", command) / ("drive", "") when Google Drive was connected / ("", "")."""
    folder, cmd = os.environ.get("HALUKA_OFFSITE_DIR", "").strip(), os.environ.get("HALUKA_OFFSITE_CMD", "").strip()
    if folder or cmd:
        return ("dir", folder) if folder else ("cmd", cmd)
    return ("drive", "") if drive.connected() else ("", "")


def status_path() -> str:
    return os.path.join(config.data_dir(), "offsite.json")


def _read() -> dict:
    try:
        with open(status_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    tmp = status_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, status_path())


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _inside(child: str, parent: str) -> bool:
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def _to_folder(src: str, folder: str) -> None:
    if _inside(folder, config.data_dir()):
        raise OSError("the destination is inside the site's own data folder")
    if not os.path.isdir(folder):
        raise OSError("the destination folder is not there (is the drive connected?)")
    dest = os.path.join(folder, os.path.basename(src))
    part = dest + ".part"
    try:
        shutil.copyfile(src, part)
        if _sha(part) != _sha(src):
            raise OSError("the copy that arrived is not the same as the one that was sent")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)


def _to_command(src: str, cmd: str) -> None:
    words = shlex.split(cmd)
    if not any("{file}" in w for w in words):
        raise OSError("the command does not say where the file goes ({file})")
    done = subprocess.run([w.replace("{file}", src) for w in words], capture_output=True, timeout=CMD_SECONDS)
    if done.returncode != 0:
        print(done.stderr.decode("utf-8", "replace")[-2000:], file=sys.stderr)   # to the server's log only
        raise OSError(f"the command failed (exit {done.returncode})")


def run(now: datetime) -> dict:
    """Take a fresh copy and send it. Returns the new status; never raises."""
    kind, where = target()
    state = _read()
    state["last_try"] = now.strftime(_STAMP)
    outbox = os.path.join(config.data_dir(), "outbox")
    made = ""
    try:
        if not kind:
            raise OSError("no destination was set")
        made = store.backup(config.db_path(), outbox, "offsite", now)
        if not made:
            raise OSError("there is no data yet")
        backup_service.check(made)                           # never send a copy that cannot be restored
        if kind == "drive":
            drive.send(made)                                 # encrypted there, checked on arrival
        else:
            (_to_folder if kind == "dir" else _to_command)(made, where)
        state.update(last_ok=now.strftime(_STAMP), last_file=os.path.basename(made),
                     last_size_kb=max(1, round(os.path.getsize(made) / 1024)), error="")
    except Exception as e:                                   # whatever went wrong: say so, change nothing
        state["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        if made and os.path.exists(made):
            os.remove(made)                                  # the outbox copy is not a backup of its own
    os.makedirs(config.data_dir(), exist_ok=True)
    _write(state)
    return status(now)


def status(now: datetime) -> dict:
    """What the settings screen shows. No path and no command: only when, and whether."""
    state = _read()
    on = bool(target()[0])
    days = None
    try:
        days = (now.date() - datetime.strptime(state.get("last_ok", ""), _STAMP).date()).days
    except ValueError:
        pass
    return {"on": on, "show": on or config.login_required(), "last_ok": state.get("last_ok", ""), "days": days,
            "late": on and (days is None or days >= LATE_DAYS), "failed": bool(state.get("error"))}


if __name__ == "__main__":
    result = run(config.now())
    good = not result["failed"] and result["days"] == 0
    print("offsite backup:", "a copy left the server" if good else "NO COPY LEFT: " + _read().get("error", ""))
    sys.exit(0 if good else 1)

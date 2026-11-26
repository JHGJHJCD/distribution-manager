# -*- coding: utf-8 -*-
"""Is this server ready to run the site?  Run on the server, with the site's environment:

    <python> -m web.server_check           (exit 0 = nothing is wrong)

One line per thing: OK / WARN (works, but look at it) / FAIL (do not open the site yet).
It changes nothing and prints no name, no password and no address.
"""
import os
import stat
import sys

from . import auth, config, offsite


def checks() -> list:
    """[(level, text)] — level is "OK", "WARN" or "FAIL"."""
    out = []

    def add(ok, good, bad, level="FAIL"):
        out.append(("OK", good) if ok else (level, bad))

    add(sys.version_info >= (3, 10), "Python 3.10 or newer", "Python is older than 3.10")
    missing = []
    for module in ("fastapi", "uvicorn", "openpyxl"):
        try:
            __import__(module)
        except Exception:
            missing.append(module)
    add(not missing, "the libraries are installed", "missing libraries: " + ", ".join(missing))
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(config.TIMEZONE)
        zone = True
    except Exception:
        zone = False
    add(zone, "the clock of Israel is available", "no time-zone data (pip install tzdata): weeks would close at the wrong hour")

    data = config.data_dir()
    add(os.path.isdir(data) and os.access(data, os.W_OK), "the data folder exists and can be written",
        "the data folder is missing or cannot be written (HALUKA_WEB_DATA)")
    if os.path.isdir(data) and os.name == "posix":
        mode = stat.S_IMODE(os.stat(data).st_mode)
        add(not mode & 0o077, "the data folder is closed to other users of the server",
            "other users of the server can read the data folder (chmod 700)")
    add(os.path.exists(config.db_path()), "the site's data is in place",
        "there is no data yet (the site will say so until it is brought in)", "WARN")

    add(config.login_required(), "the login is on", "the login is OFF: set HALUKA_WEB_HOSTS to the site's name")
    add(any(h not in config.LOCAL_HOSTS for h in config.allowed_hosts()), "the site's own name is set",
        "the site answers only to this computer's name (HALUKA_WEB_HOSTS)", "WARN")
    count = len(auth.users())
    add(count >= 1, f"{count} user(s) can enter", "nobody can enter yet (python -m web.auth set <name>)")
    if count and os.name == "posix":
        mode = stat.S_IMODE(os.stat(auth.users_path()).st_mode)
        add(not mode & 0o077, "the users file is closed to other users of the server",
            "other users of the server can read the users file (chmod 600)")

    kind = offsite.target()[0]
    add(bool(kind), "a backup leaves the server (" + (kind or "") + ")",
        "no backup leaves the server yet (HALUKA_OFFSITE_DIR or HALUKA_OFFSITE_CMD)", "WARN")
    if kind:
        state = offsite.status(config.now())
        add(not state["late"] and not state["failed"], "the last backup left the server on time",
            "the last backup did not leave the server (python -m web.offsite)", "WARN")
    return out


if __name__ == "__main__":
    found = checks()
    for level, text in found:
        print(f"{level:<4} {text}")
    bad = sum(1 for level, _ in found if level == "FAIL")
    print("\nRESULT:", "ready" if not bad else f"{bad} thing(s) must be fixed before the site is opened")
    sys.exit(1 if bad else 0)

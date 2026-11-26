# -*- coding: utf-8 -*-
"""Where the site keeps its data and the few numbers it starts from.

Nothing here is specific to one computer: the data folder and the allowed host names can
be set from the environment, so the same code runs on this PC now and on the server later.
"""
import os
from datetime import datetime

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(WEB_DIR)

TIMEZONE = "Asia/Jerusalem"          # the fund's clock, whatever the server's own clock says
DEFAULT_PORTIONS = 52                # portions in an ordinary week
DEFAULT_RESERVE = 10                 # waiting list after them (as in the lists sent so far)
MAX_WEEKS = 1040                     # technical ceiling of one request: twenty years ahead
PORT = 8787


def data_dir() -> str:
    """The folder of the site's database and its backups. Personal data — it is listed in
    .gitignore and must never be published (the repository is public)."""
    return os.environ.get("HALUKA_WEB_DATA") or os.path.join(WEB_DIR, "data")


def db_path() -> str:
    return os.path.join(data_dir(), "haluka.db")


def backup_dir() -> str:
    return os.path.join(data_dir(), "backups")


def allowed_hosts() -> list:
    raw = os.environ.get("HALUKA_WEB_HOSTS") or "127.0.0.1,localhost"
    return [h.strip() for h in raw.split(",") if h.strip()]


LOCAL_HOSTS = ("127.0.0.1", "localhost")


def login_required() -> bool:
    """On this computer only: no login. Login is on when it is asked for (HALUKA_WEB_LOGIN=1)
    and ALWAYS when the site answers to any name other than this computer's own — a site
    that can be reached from outside can never be left open by forgetting a setting."""
    return os.environ.get("HALUKA_WEB_LOGIN") == "1" or any(h not in LOCAL_HOSTS for h in allowed_hosts())


def now() -> datetime:
    """The current time in Israel, as a plain (naive) datetime."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    except Exception:                      # no time-zone database on this machine
        global _warned
        if not _warned:
            _warned = True
            print(f"WARNING: time zone {TIMEZONE} is not available (pip install tzdata); "
                  "using this computer's own clock", flush=True)
        return datetime.now()


_warned = False

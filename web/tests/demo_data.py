# -*- coding: utf-8 -*-
"""An invented database for LOOKING at the site without the real data.

    <python 3.12> web/tests/demo_data.py <empty folder>
    set HALUKA_WEB_DATA=<that folder>   and run the site (web/run_local.bat)

Every person here is made up. It refuses to write into a folder that already has a
database, so it can never overwrite real data.
"""
import os
import sys
from datetime import datetime, timedelta

from _util import person

from web import config, service, store

FAMILIES = ["אלון", "ברוש", "גפן", "דקל", "הדס", "ורד", "זית", "חרוב", "תאנה", "יסמין", "כרמל", "לבנה",
            "מורן", "נרקיס", "סביון", "ערבה", "צבר", "רימון", "שקד", "תמר"]
GIVEN = ["בדיקה", "דוגמה", "ניסיון", "הדגמה", "תרגול", "מבחן"]
KINDS = [("שבועי", 4)] * 3 + [("דו-שבועי", 4)] * 4 + [("תלת-שבועי", 4)] * 2 + [("חודשי", 4)] * 3 + \
        [("חד-פעמי", 3)] * 5 + [("חד-פעמי", 2)] * 4 + [("חד-פעמי", None), ("", None)]


def build(folder: str, now: datetime = None) -> str:
    now = now or config.now()
    path = os.path.join(folder, "haluka.db")
    if os.path.exists(path):
        raise SystemExit(f"there is already a database in {folder} — choose an empty folder")
    store.create(path)
    conn = store.connect(path)
    cur = service.current_week(now)
    with store.tx(conn):
        n = 0
        for fam in FAMILIES:
            for giv in GIVEN:
                n += 1
                freq, prio = KINDS[n % len(KINDS)]
                rec = person(n, freq, prio, full_name=f"{fam} {giv}", last_name=fam, first_name=giv,
                             phone1=f"050-{5550000 + n}", souls=2 + n % 7,
                             status="מושהה" if n % 23 == 0 else "פעיל")
                rec.pop("id")
                guid = rec.pop("guid")
                store.insert_recipient(conn, {k: v for k, v in rec.items() if k in store.RECIPIENT_COLUMNS
                                              and v is not None}, now, guid=guid)
                if freq in ("שבועי", "דו-שבועי", "חודשי") and n % 3:
                    for back in (1, 3, 5):
                        d = (cur - timedelta(days=7 * back)).isoformat()
                        conn.execute("INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, source) "
                                     "VALUES (?,?,?,?, 'demo')", (f"h{n}-{back}", guid, rec["full_name"], d))
        # two look-alikes, so the suggestions screen has something to show
        store.insert_recipient(conn, {"full_name": "אלון בדיקה", "last_name": "אלון", "first_name": "בדיקה",
                                      "phone1": "052-7770001", "frequency": "חד-פעמי", "priority": 3, "souls": 5},
                               now, guid="g9001")
        store.insert_recipient(conn, {"full_name": "שדה דוגמה", "last_name": "שדה", "first_name": "דוגמה",
                                      "phone1": "0505550002", "frequency": "חודשי", "priority": 4, "souls": 3},
                               now, guid="g9002")
        store.set_setting(conn, "default_portions", 30)
        store.set_setting(conn, "default_reserve", 6)
        store.set_meta(conn, "closed_through", (cur - timedelta(days=7)).isoformat())
    conn.close()
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print("invented database:", build(os.path.abspath(sys.argv[1])))

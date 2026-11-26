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
from web.engine import holidays

FAMILIES = ["אלון", "ברוש", "גפן", "דקל", "הדס", "ורד", "זית", "חרוב", "תאנה", "יסמין", "כרמל", "לבנה",
            "מורן", "נרקיס", "סביון", "ערבה", "צבר", "רימון", "שקד", "תמר"]
GIVEN = ["בדיקה", "דוגמה", "ניסיון", "הדגמה", "תרגול", "מבחן"]
COMMUNITIES = ["קהילת האלון"] * 5 + ["קהילת הברוש"] * 3 + ["קהילת הגפן"] * 2 + ["קהילת הדקל"]
SOME_HOLIDAYS = [["ראש השנה", "פסח"], ["פסח"], ["סוכות", "פורים"], ["חנוכה", "פסח"], ["ראש השנה", "חנוכה", "שבועות"]]
KINDS = [("שבועי", 4)] * 3 + [("דו-שבועי", 4)] * 4 + [("תלת-שבועי", 4)] * 2 + [("חודשי", 4)] * 3 + \
        [("חד-פעמי", 3)] * 5 + [("חד-פעמי", 2)] * 4 + [("חד-פעמי", None), ("", None)]


def stage4_fields(n: int) -> dict:
    """What the holiday events, the filter and the community balance read from a card: is it
    marked for the holidays (about a third are not, some only for certain holidays), how many
    children, the income and the money left per soul (missing on some cards, a debt on a
    few), and the community."""
    m = (n * 3 + n // 20) % 20
    some = SOME_HOLIDAYS[n % len(SOME_HOLIDAYS)] if m >= 16 else []
    return {
        "holiday_support": 0 if m < 7 else 1, "holidays": holidays.to_field(some),
        "children_total": [4, 6, 3, 5, 7, 2, 4, 8, 3, 5, 9, 4, 6, 3, 5, 3, 4, 7, 1, 6][(n * 3) % 20],
        "income": "" if (n * 11 + 6) % 25 < 3 else str(2500 + ((n * 23) % 40) * 95),
        "per_soul": "" if (n * 7 + 2) % 10 == 0 else str(-250 if n % 37 == 0 else 150 + ((n * 29) % 50) * 20),
        "representative": COMMUNITIES[(n * 7) % len(COMMUNITIES)],
    }


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
                             status="מושהה" if n % 23 == 0 else "פעיל", **stage4_fields(n))
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
        # a holiday round that already happened (nine weeks ago, a Thursday), and one that is ahead
        feast = cur - timedelta(days=7 * 9 - 1)
        got = [r for r in store.load_recipients(conn) if holidays.supports(r, "סוכות") and r["id"] % 4]
        conn.execute("INSERT INTO batches (guid, dist_name, dist_date, quantity, recipient_count, holiday, created_at, source) "
                     "VALUES ('b-sukkot', ?, ?, ?, ?, 'סוכות', ?, 'demo')",
                     (f"חלוקת סוכות {feast.strftime('%d/%m/%Y')}", feast.isoformat(), len(got), len(got),
                      now.strftime("%Y-%m-%d %H:%M:%S")))
        for r in got:
            conn.execute("INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, holiday, batch_guid, source) "
                         "VALUES (?,?,?,?, 'סוכות', 'b-sukkot', 'demo')",
                         (f"hs{r['id']}", r["guid"], r["full_name"], feast.isoformat()))
        store.save_event(conn, None, cur + timedelta(days=1), "חנוכה", 25, 4,
                         {"children_total": {"min": 3, "max": None}}, now)
        store.set_setting(conn, "default_portions", 30)
        store.set_setting(conn, "default_reserve", 6)
        store.set_meta(conn, "closed_through", (cur - timedelta(days=7)).isoformat())
    conn.close()
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print("invented database:", build(os.path.abspath(sys.argv[1])))

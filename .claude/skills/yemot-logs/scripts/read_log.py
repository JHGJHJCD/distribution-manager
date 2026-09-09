# -*- coding: utf-8 -*-
"""קריאה קלה של יומני ימות המשיח — מוריד, מפענח, מסנן ומציג טבלה קריאה.

הלוגים יכולים להיות ענקיים (LogApi ~3.8MB, LogRouting ~1MB) — הסקריפט מפענח
שורה-שורה ומדפיס רק את המסונן/האחרון, לעולם לא מציף את כל הקובץ.

הרצה (py312):
    <py>  read_log.py list                      # רשימת קובצי היומן + גדלים
    <py>  read_log.py api     [filters]         # LogApi.ymgr — כל קריאות ה-API
    <py>  read_log.py routing [filters]         # LogRouting.ymgr — ניתובי שיחות
    <py>  read_log.py folder  [YYYY-MM] [filters]# LogFolderEnterExit — כניסה/יציאה לשלוחות
    <py>  read_log.py file ivr2:/Log/<name>.ymgr [filters]   # קובץ לוג כלשהו

filters:
    --tail N        כמה שורות אחרונות (ברירת מחדל 30; --tail 0 = הכל)
    --head N        N הראשונות במקום האחרונות
    --phone NUM     רק שורות של מספר (נרמול ישראלי)
    --folder F      רק שורות של שלוחה F
    --module M      רק שורות שה-Module/Type מכיל M
    --since HH:MM   רק מהשעה הזו (היום); או DD/MM/YYYY; או "DD/MM HH:MM"
    --grep TEXT     רק שורות גולמיות שמכילות TEXT (substring)
    --fields a,b,c  אילו מפתחות להציג בטבלה (ברירת מחדל: זמן/טלפון/שלוחה/מודול)
    --raw           הדפס את השורה הגולמית (key#value%…) במקום טבלה
    --keys          הצג רק אילו מפתחות קיימים בלוג (לחקירת פורמט לא-מוכר)
"""
import os
import re
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DATE_KEYS = ("Date", "EnterDate", "ExitDate")
_TIME_KEYS = ("Time", "EnterTime", "ExitTime")


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def _has(name):
    return name in sys.argv


def parse_line(raw):
    """'k#v%k#v%…' → dict. שומר גם ערכים ריקים."""
    kv = {}
    for part in raw.strip().split("%"):
        if "#" in part:
            k, v = part.split("#", 1)
            kv[k.strip()] = v.strip()
    return kv


def _first(kv, keys):
    for k in keys:
        if kv.get(k):
            return kv[k]
    return ""


def _dt(kv):
    """datetime מהשדות (לסינון/מיון), או None."""
    d, t = _first(kv, _DATE_KEYS), _first(kv, _TIME_KEYS)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    if not m:
        return None
    dd, mm, yy = m.groups()
    tm = re.match(r"(\d{2}):(\d{2})(?::(\d{2}))?", t or "")
    hh, mi, ss = (tm.groups() if tm else ("00", "00", "00"))
    try:
        return datetime(int(yy), int(mm), int(dd), int(hh), int(mi), int(ss or 0))
    except ValueError:
        return None


def _parse_since(s):
    if not s:
        return None
    now = datetime.now()
    for fmt, fill in (("%d/%m/%Y %H:%M", {}), ("%d/%m/%Y", {}), ("%d/%m %H:%M", {"year": now.year}),
                      ("%H:%M", {"year": now.year, "month": now.month, "day": now.day})):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(**fill) if fill else dt
        except ValueError:
            continue
    return None


def fetch(path):
    from utils import yemot
    raw = yemot._download(path)
    if not raw or raw[:1] == b"{":
        return ""
    return raw.decode("utf-8", errors="replace")


def list_logs():
    from utils import yemot
    d = yemot._call("GetIVR2Dir", {"path": "ivr2:/Log"})
    files = sorted((d.get("files") or []), key=lambda f: str(f.get("name") or ""))
    print("=== קובצי יומן ב-ivr2:/Log ===")
    for f in files:
        nm = f.get("name") or ""
        if nm.lower().endswith((".ymgr", ".ini", ".log")):
            sz = f.get("size")
            szs = f"{int(sz)/1024:.0f}KB" if isinstance(sz, (int, float)) and sz else str(sz)
            print(f"  {nm:<40} {szs:>8}   {f.get('mtime','')}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    mode = sys.argv[1]
    if mode == "list":
        list_logs()
        return 0

    if mode == "api":
        path = "ivr2:/Log/LogApi.ymgr"
    elif mode == "routing":
        path = "ivr2:/Log/LogRouting.ymgr"
    elif mode == "folder":
        month = None
        for a in sys.argv[2:]:
            if re.fullmatch(r"\d{4}-\d{2}", a):
                month = a
                break
        month = month or datetime.now().strftime("%Y-%m")
        path = f"ivr2:/Log/LogFolderEnterExit-{month}.ymgr"
    elif mode == "file":
        path = sys.argv[2]
    else:
        print("מצב לא מוכר:", mode)
        print(__doc__)
        return 2

    from utils.yemot import normalize_phone
    text = fetch(path)
    if not text:
        print(f"(אין תוכן / הקובץ לא קיים: {path})")
        return 0

    phone = normalize_phone(_arg("--phone")) if _has("--phone") else None
    folder = _arg("--folder")
    module = _arg("--module")
    grep = _arg("--grep")
    since = _parse_since(_arg("--since"))
    show_keys = _has("--keys")
    raw_out = _has("--raw")
    fields = (_arg("--fields") or "").split(",") if _has("--fields") else None

    rows, keyset = [], set()
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if grep and grep not in raw:
            continue
        kv = parse_line(raw)
        if not kv:
            continue
        keyset.update(kv.keys())
        if phone and normalize_phone(kv.get("Phone") or kv.get("phone")) != phone:
            continue
        if folder and kv.get("Folder") != folder:
            continue
        if module and module not in (kv.get("Module", "") + kv.get("Type", "")):
            continue
        if since:
            dt = _dt(kv)
            if dt and dt < since:
                continue
        rows.append((raw, kv))

    if show_keys:
        print(f"=== מפתחות שנמצאו ב-{os.path.basename(path)} ===")
        print("  " + ", ".join(sorted(keyset)))
        print(f"  ({len(rows)} שורות תואמות)")
        return 0

    if _has("--head"):
        rows = rows[:int(_arg("--head", "30"))]
    else:
        n = int(_arg("--tail", "30"))
        rows = rows if n == 0 else rows[-n:]

    print(f"=== {os.path.basename(path)} — {len(rows)} שורות ===")
    for raw, kv in rows:
        if raw_out:
            print("  " + raw.strip())
        elif fields:
            print("  " + " | ".join(f"{f}={kv.get(f,'')}" for f in fields))
        else:
            t = (_first(kv, _DATE_KEYS) + " " + _first(kv, _TIME_KEYS)).strip()
            ph = kv.get("Phone") or kv.get("phone") or ""
            fo = kv.get("Folder") or ""
            mo = kv.get("Module") or kv.get("Type") or kv.get("Url") or kv.get("ApiUrl") or ""
            print(f"  {t:<20} {ph:<12} שלוחה={fo:<6} {mo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

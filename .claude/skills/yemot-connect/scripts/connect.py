# -*- coding: utf-8 -*-
"""בנה חיבור — מוודא (ובמידת הצורך משלים) את החיבור בין מנהל חלוקה לימות המשיח.

הרצה:
    <python312> .claude/skills/yemot-connect/scripts/connect.py [אפשרויות]

ברירת המחדל = **קריאה בלבד** מול הקו (GetSession / GetCustomerData / GetTemplates /
DownloadFile). שום שלב לא מחייג ולא כותב לשורש הקו — יש גדר בקוד (`_guard`) שמפילה
כל פקודת חיוג/רשימה גם אם מישהו יקרא לה בטעות.

אפשרויות:
    --set SYSTEM PASSWORD   כתיבת פרטי הגישה ל-settings של התוכנה (מסונכרנות לשני
                            המחשבים) לפני הבדיקה — כשהתוכנה עדיין לא חוברה.
    --caller NUMBER         שמירת "מספר מזוהה ביוצא" (נשמר רק אם הקו מאשר אותו).
    --fix                   השלמות בטוחות: יצירת/תיקון תבנית הקמפיין (CreateTemplate /
                            UpdateTemplate) — לא חיוג, לא שורש, לא שלוחות.
    --refresh-state         מרענן גם את STATE.md של הסקיל הפרטי yemot-line-state.
    --json                  פלט מכונה (לצד הדוח).

יציאה 0 = כל השלבים ירוקים; אחרת מספר השלבים האדומים.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, APP)
os.chdir(APP)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                   # noqa: BLE001
    pass

import database as db                               # noqa: E402
db.init_db()
from utils import yemot                             # noqa: E402
from utils import callback_server as cb             # noqa: E402

PY312 = r"C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe"
ROOT_ROUTE_LINE = f"{yemot.DEFAULT_CALLER_ID}=/{cb.EXT}"     # 048691834=/76

# ─── גדר בטיחות: הסקריפט לעולם לא מחייג ולא נוגע בשורש ─────────────────────
_FORBIDDEN = set(yemot._DIAL_COMMANDS) | {"UploadPhoneList", "RunTzintuk"}
_orig_call = yemot._call


def _guard(command, params=None, post=False):
    if command in _FORBIDDEN:
        raise RuntimeError(f"connect.py: פקודת חיוג '{command}' חסומה בכלי הזה")
    return _orig_call(command, params, post)


yemot._call = _guard
_orig_upload = yemot._upload_multipart


def _guard_upload(path, content, convert="1"):
    if "ext.ini" in str(path) and str(path).count("/") <= 1:
        raise RuntimeError("connect.py: כתיבה לשורש הקו חסומה")
    return _orig_upload(path, content, convert)


yemot._upload_multipart = _guard_upload

# ─── דוח ─────────────────────────────────────────────────────────────────────
STEPS = []          # (ok: True/False/None, title, detail, remedy)


def step(ok, title, detail="", remedy=""):
    STEPS.append({"ok": ok, "title": title, "detail": detail, "remedy": remedy})
    mark = "✓" if ok else ("•" if ok is None else "✗")
    line = f"  {mark}  {title}"
    if detail:
        line += f" — {detail}"
    print(line)
    if remedy and ok is False:
        print(f"       ↳ {remedy}")


def _err_text(e) -> str:
    return str(e).replace("\n", " · ")


# ─── השלבים ──────────────────────────────────────────────────────────────────

def s1_credentials(args):
    if args.set:
        system, password = args.set
        db.set_setting(yemot.SET_SYSTEM, system.strip())
        db.set_setting(yemot.SET_PASSWORD, password.strip())
        print("  ⚙  פרטי הגישה נכתבו להגדרות התוכנה (מסתנכרנים לשני המחשבים)")
    if not yemot.is_configured():
        step(False, "פרטי גישה לימות", "חסרים בהגדרות התוכנה",
             "הרץ עם --set <מספר-מערכת> <סיסמה> (הפרטים בסקיל הפרטי yemot-line-knowledge), "
             "או הזן בהגדרות → צינתוקים")
        return False
    sysno = (db.get_setting(yemot.SET_SYSTEM) or "").strip()
    pw = (db.get_setting(yemot.SET_PASSWORD) or "").strip()
    kind = "מפתח API" if yemot._is_api_key(pw) else "סיסמת מערכת"
    step(True, "פרטי גישה לימות", f"מערכת {sysno or '(מפתח API)'} · {kind}")
    return True


def s2_session():
    try:
        info = yemot.session_info()
    except yemot.YemotError as e:
        remedy = ""
        if e.code == -3:
            remedy = "נטפרי חוסם — לפתוח את call2all.co.il בהגדרות הסינון או לנסות ממחשב אחר"
        elif e.code == -1:
            remedy = "אין תשובה מהשרת — לבדוק אינטרנט; אם יש אינטרנט, ימות אולי מושבתים זמנית"
        elif e.code == 1 or "סיסמה" in str(e):
            remedy = "לעדכן את הסיסמה (או מפתח API) בהגדרות; אם הסיסמה שונתה בימות — גם בשלוחה 555/4"
        elif "דו-שלבי" in str(e):
            remedy = "ליצור מפתח API בממשק ימות (חומת אש) ולהדביק בשדה הסיסמה"
        step(False, "כניסה לשרת ימות (GetSession)", _err_text(e), remedy)
        return None
    units = info.get("units")
    detail = f"יתרת יחידות: {units:,.0f}" if units is not None else "השרת ענה"
    warn = ""
    if units is not None and units < 500:
        warn = " ⚠ יתרה נמוכה"
    step(True, "כניסה לשרת ימות (GetSession)", detail + warn)
    return info


def s3_caller_id(args):
    if args.caller:
        db.set_setting(yemot.SET_CALLER_ID, "")          # נשמר רק אם מאושר (למטה)
    wanted = (args.caller or yemot._caller_id()).strip()
    try:
        allowed = yemot.allowed_caller_ids()
    except yemot.YemotError as e:
        step(None, "מספר מזוהה ביוצא", f"לא ניתן לאמת מול הקו ({_err_text(e)})")
        return
    if not allowed:
        step(None, "מספר מזוהה ביוצא", f"{wanted} — השרת לא החזיר רשימת מספרים מאושרים")
        return
    p = yemot.normalize_phone(wanted)
    if p in allowed:
        if args.caller:
            db.set_setting(yemot.SET_CALLER_ID, p)
        step(True, "מספר מזוהה ביוצא", f"{p} מאושר בקו (מאושרים: {', '.join(allowed)})")
    else:
        step(False, "מספר מזוהה ביוצא", f"{wanted} אינו מאושר בקו — שליחה תיכשל בשגיאה 120",
             f"לבחור אחד מהמאושרים: {', '.join(allowed)} (--caller <מספר>) או להשאיר ריק ⇐ {yemot.DEFAULT_CALLER_ID}")


def s4_template(args):
    tid = (db.get_setting(yemot.SET_TEMPLATE) or "").strip()
    try:
        data = _guard("GetTemplates")
        templates = data.get("templates") or yemot._dig(data, "templates") or []
    except yemot.YemotError as e:
        step(None, "תבנית הקמפיין של התוכנה", f"לא ניתן לקרוא תבניות ({_err_text(e)})")
        return
    ids = {str(t.get("templateId") or t.get("id") or "") for t in templates if isinstance(t, dict)}
    if tid and tid in ids:
        ready = (db.get_setting(yemot.SET_TEMPLATE_READY) or "") == f"{yemot._TEMPLATE_READY_STAMP}:{tid}"
        step(True, "תבנית הקמפיין של התוכנה",
             f"מזהה {tid} קיים בקו" + ("" if ready else " · מדיניות החיוג תאומת בשליחה הבאה"))
    elif args.fix:
        if tid and tid not in ids:
            db.set_setting(yemot.SET_TEMPLATE, "")          # התבנית נמחקה בקו — ליצור חדשה
            db.set_setting(yemot.SET_TEMPLATE_READY, "")
        try:
            new_tid = yemot.ensure_template()
            step(True, "תבנית הקמפיין של התוכנה", f"נוצרה/תוקנה: מזהה {new_tid}")
        except yemot.YemotError as e:
            step(False, "תבנית הקמפיין של התוכנה", _err_text(e),
                 "אם השגיאה 101 — מודול הקמפיינים לא פעיל בקו; לפנות לימות")
    else:
        why = "לא נוצרה עדיין" if not tid else f"מזהה {tid} לא נמצא בקו (נמחקה?)"
        step(False, "תבנית הקמפיין של התוכנה", why,
             "הרץ עם --fix ליצירה (CreateTemplate — לא מחייג), או 'בדוק חיבור'/שליחה ראשונה בתוכנה")
    ctid = (db.get_setting(yemot.SET_CLASSIC_TEMPLATE) or "").strip()
    if ctid:
        step(True if ctid in ids else False, "תבנית הצינתוק הקלאסי",
             f"מזהה {ctid}" + ("" if ctid in ids else " לא נמצא בקו — תיווצר מחדש בשליחה הקלאסית הבאה"))


def s5_recording():
    info = yemot.recording_info()
    if info:
        step(True, "הקלטת ההודעה", f"«{info.get('name')}» (הועלתה {str(info.get('at') or '')[:16]})")
    elif yemot.has_recording():
        step(None, "הקלטת ההודעה", "קיימת הקלטה ישנה (לפני 3.26) — שמה לא ידוע")
    else:
        step(None, "הקלטת ההודעה", "עדיין לא הועלתה — צינתוק קלאסי לא זקוק לה; 'עם הודעה' כן")


def s6_callback():
    try:
        problem = cb.verify_extension()
    except yemot.YemotError as e:
        step(None, f"שלוחת המענה /{cb.EXT} בקו", f"לא ניתן לקרוא ({_err_text(e)})")
        problem = None
    if problem == "":
        step(True, f"שלוחת המענה /{cb.EXT} בקו", "type=api ומצביעה לשרת המענה")
    elif problem:
        step(False, f"שלוחת המענה /{cb.EXT} בקו", problem.replace("\n", " · "),
             "בהגדרות → שרת המענה → 'בדוק את שלוחת המענה (76)' → 'תקן' (כותב רק את /76)")
    enabled = cb.is_enabled()
    if cb.is_configured():
        try:
            n = cb.check_connection()
            step(True, "שרת המענה (Cloudflare)", f"עונה · {n} תשובות שמורות"
                 + ("" if enabled else " · המתג בתוכנה כבוי"))
        except Exception as e:                       # noqa: BLE001
            step(False, "שרת המענה (Cloudflare)", _err_text(e),
                 "לבדוק שה-Worker פרוס (פתרונאי → פיתוחים אישיים) ושהסוד בהגדרות נכון")
    else:
        step(None, "שרת המענה (Cloudflare)", "לא הוגדר סוד בתוכנה — המסלול כבוי")
    # ניתוב בשורש — מידע בלבד (התוכנה לעולם לא כותבת לשורש)
    try:
        raw = yemot._download("ivr2:/Did_Go_To.ini")
        text = raw.decode("utf-8", errors="replace") if not raw.startswith(b"{") else ""
        routed = ROOT_ROUTE_LINE in text.replace(" ", "")
        step(True if routed else None, "ניתוב חזרה-לצינתוק בשורש הקו",
             f"{ROOT_ROUTE_LINE} " + ("קיים" if routed else "לא קיים — חיווט ידני בלבד (סקיל tzintuk-callback-server)"))
    except yemot.YemotError as e:
        step(None, "ניתוב חזרה-לצינתוק בשורש הקו", f"לא ניתן לקרוא ({_err_text(e)})")


def s7_refresh_state():
    script = os.path.join(APP, ".claude", "skills", "yemot-line-state", "scripts", "refresh_state.py")
    if not os.path.exists(script):
        step(None, "רענון STATE.md", "הסקיל הפרטי yemot-line-state לא קיים במחשב הזה")
        return
    r = subprocess.run([PY312, script], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600)
    step(r.returncode == 0, "רענון STATE.md (yemot-line-state)",
         "עודכן" if r.returncode == 0 else (r.stderr or r.stdout)[-300:].replace("\n", " · "))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--set", nargs=2, metavar=("SYSTEM", "PASSWORD"))
    ap.add_argument("--caller", default="")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--refresh-state", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    args = ap.parse_args()
    if args.help:
        print(__doc__)
        return 0

    print("בנה חיבור — מנהל חלוקה ↔ ימות המשיח (קריאה בלבד; בלי חיוג)")
    print(f"  DB: {db.DB_PATH}")
    if s1_credentials(args):
        if s2_session() is not None:
            s3_caller_id(args)
            s4_template(args)
            s5_recording()
            s6_callback()
            if args.refresh_state:
                s7_refresh_state()
    bad = [s for s in STEPS if s["ok"] is False]
    print()
    if bad:
        print(f"✗ {len(bad)} שלבים דורשים טיפול: " + " · ".join(s["title"] for s in bad))
    else:
        print("✓ החיבור לימות המשיח שלם — התוכנה מוכנה לשלוח צינתוקים")
    if args.json:
        print(json.dumps(STEPS, ensure_ascii=False))
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())

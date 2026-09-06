# -*- coding: utf-8 -*-
"""בודק לוגיקת הצינתוקים — לינט אינווריאנטים סטטי + הרצת הבדיקות.

הרצה (מ-root של הפרויקט או מכל מקום):
    python .claude/skills/tzintuk-check/scripts/check_tzintuk.py [--lint-only] [--tests-only]

כל לינט = כלל מ-references/invariants.md שנלמד מבאג אמיתי. לינט אדום = מישהו החזיר באג ישן.
יציאה 0 = הכל ירוק.
"""
import os, re, subprocess, sys

PY312 = r"C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TESTS = ["test_tzintuk.py", "test_sync.py"]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _func_body(src, name, sig_hint="", kind="def"):
    """גוף פונקציה/מתודה/מחלקה (עד ההגדרה הבאה באותה הזחה או נמוכה ממנה).
    חתימה רב-שורתית נתמכת; sig_hint בוחר בין כמה הגדרות באותו שם."""
    pat = r"^([ \t]*)" + kind + r" " + re.escape(name) + r"\b([^\n]*?(?:\([^)]*\))?[^\n]*?):[ \t]*\n"
    for m in re.finditer(pat, src, re.M):
        if sig_hint and sig_hint not in m.group(2):
            continue
        indent = m.group(1)
        rest = src[m.end():]
        end = re.search(r"^" + indent + r"(?:def |class |@)", rest, re.M)
        return rest[:end.start()] if end else rest
    return ""


def _class_body(src, name):
    return _func_body(src, name, kind="class")


def _has(src, pattern):
    return re.search(pattern, src, re.M) is not None


# (מזהה, תיאור, פונקציה שמחזירה (ok, פירוט))
LINTS = []


def lint(ident, desc):
    def deco(fn):
        LINTS.append((ident, desc, fn))
        return fn
    return deco


@lint("I1", "CALLBACK_ENABLED = False (שלוחה 78 נעולה)")
def _(y, t, test, rel):
    return _has(y, r"^CALLBACK_ENABLED\s*=\s*False\b"), ""


@lint("I2", "פקודות חיוג יוצאות פעם אחת — _DIAL_COMMANDS + retry=False")
def _(y, t, test, rel):
    ok = _has(y, r'^_DIAL_COMMANDS\s*=\s*frozenset\(\{"RunCampaign",\s*"RunTzintuk",\s*"ScheduleCampaign"\}\)')
    body = _func_body(y, "_call")
    ok = ok and "once = command in _DIAL_COMMANDS" in body and "retry=not once" in body
    return ok, ""


@lint("I3", "_start_tracking ו-_start_callback_tracking קוראים _retire_trackers() ראשונים")
def _(y, t, test, rel):
    bad = [n for n in ("_start_tracking", "_start_callback_tracking")
           if "self._retire_trackers()" not in _func_body(t, n)]
    return not bad, ", ".join(bad)


@lint("I4", "tick נושא worker: _on_tick(st, worker) / _on_cb_tick(st, worker)")
def _(y, t, test, rel):
    return (_has(t, r"def _on_tick\(self, st, worker=None\)")
            and _has(t, r"def _on_cb_tick\(self, st, worker=None\)")), ""


@lint("I5", "_PollWorker.timed_out + חידוש דרך _chain_next ב-_on_worker_done")
def _(y, t, test, rel):
    body = _func_body(t, "_on_worker_done")
    return "self.timed_out" in _class_body(t, "_PollWorker") \
        and "timed_out" in body and "_chain_next" in body, ""


@lint("I6", "מעקב שנפל על רשת מתחדש אחרי דקה (singleShot 60_000)")
def _(y, t, test, rel):
    body = _func_body(t, "_on_worker_done")
    return "failed" in body and _has(body, r"singleShot\(60_?000"), ""


@lint("I7", "_reset_results מאפס _last_failed/btn_resend/_last_final/_last_entries")
def _(y, t, test, rel):
    body = _func_body(t, "_reset_results")
    missing = [k for k in ("_last_failed", "_last_final", "_last_entries")
               if not _has(body, r"self\." + k + r"\s*=")]
    if "btn_resend.setVisible(False)" not in body:
        missing.append("btn_resend")
    return not missing, ", ".join(missing)


@lint("I8", "_load_week_list מאפס _batch/_free וקורא _reset_results")
def _(y, t, test, rel):
    body = _func_body(t, "_load_week_list")
    return all(k in body for k in ("self._batch = None", "self._free = None", "_reset_results()")), ""


@lint("I9", "_cancel_sched עם מזהה ריק ⇒ find_pending_sched_id")
def _(y, t, test, rel):
    return "find_pending_sched_id" in _func_body(t, "_cancel_sched"), ""


@lint("I10", "_check_scheduled בלי schedId ⇒ find_scheduled_by_template")
def _(y, t, test, rel):
    body = _func_body(t, "_check_scheduled")
    return "find_scheduled_by_template" in body and 'find_scheduled("")' not in body, ""


@lint("I11", "ציור תוצאות רק דרך _results_belong_here ב-_on_tick וב-_on_cb_tick")
def _(y, t, test, rel):
    bad = [n for n in ("_on_tick", "_on_cb_tick")
           if "_results_belong_here(" not in _func_body(t, n, sig_hint="worker")]
    return not bad, ", ".join(bad)


@lint("I12", "_maybe_resume_tracking מדלג על צינתוק קלאסי של מחשב אחר (_is_own_campaign)")
def _(y, t, test, rel):
    return "_is_own_campaign(" in _func_body(t, "_maybe_resume_tracking"), ""


@lint("I13", "_changed_meanwhile נבדק בשליחה, בתזמון ובשיגור חכם")
def _(y, t, test, rel):
    bad = [n for n in ("_send", "_schedule", "_smart_schedule")
           if "_changed_meanwhile(" not in _func_body(t, n)]
    return not bad, ", ".join(bad)


@lint("I14", "_answer_campaigns סורק limit=200 (לא 30)")
def _(y, t, test, rel):
    return "get_tzintuk_campaigns(limit=200)" in _func_body(t, "_answer_campaigns"), ""


@lint("I15", "merge_survey_answers מקבל until_by_phone; answer_windows בשימוש ב-tzintukim")
def _(y, t, test, rel):
    return ("until_by_phone" in _func_body(y, "merge_survey_answers")
            and "yemot.answer_windows(" in t and "until_by_phone" in _class_body(t, "_PollWorker")), ""


@lint("I17", "_send חסום כשיש תזמון ממתין על התבנית הראשית (_pending_main_sched)")
def _(y, t, test, rel):
    return "_pending_main_sched()" in _func_body(t, "_send"), ""


@lint("I30", "v3.22 — תזמון רגיל על תבנית ייעודית (schedule_campaign_dedicated), לא על הראשית")
def _(y, t, test, rel):
    body = _func_body(t, "_schedule")
    return ("schedule_campaign_dedicated(" in body
            and "yemot.schedule_campaign(" not in body), ""


@lint("I31", "v3.22 — כפתור העצירה נעלם ב-_retire_trackers ובסיום קמפיין")
def _(y, t, test, rel):
    return ("btn_stop_send.setVisible(False)" in _func_body(t, "_retire_trackers")
            and "btn_stop_send.setVisible(False)" in _func_body(t, "_on_tick", sig_hint="worker")), ""


@lint("I32", "v3.22 — חסימת נטפרי (418) מזוהה ב-_http/_upload_multipart דרך netblock, בלי שרת תאום")
def _(y, t, test, rel):
    return ("netblock.is_blocked(" in _func_body(y, "_http")
            and "netblock.is_blocked(" in _func_body(y, "_upload_multipart")
            and "code=-3" in _func_body(y, "_http")), ""


@lint("I33", "v3.22 — ensure_template מאשר מדיניות חיוג פעם אחת (SET_TEMPLATE_READY, בלי yemotContext)")
def _(y, t, test, rel):
    body = _func_body(y, "ensure_template")
    return ("SET_TEMPLATE_READY" in body and "maxDialAttempts" in body
            and "yemotContext" not in body), ""


@lint("I18", "run_test לא מנקה את רשימת התבנית (בלי ClearTemplateEntries)")
def _(y, t, test, rel):
    body = _func_body(y, "run_test")
    return "ClearTemplateEntries" not in body and "set_template_entries" not in body, ""


@lint("I19", "publish_to_extension נקרא פעם אחת בלבד בטאב (הכפתור הידני)")
def _(y, t, test, rel):
    n = len(re.findall(r"yemot\.publish_to_extension", t))
    return n == 1, f"{n} קריאות"


@lint("I20", "פקודות חיוג/העלאה בטאב רצות דרך _run_blocking (לא inline)")
def _(y, t, test, rel):
    # קריאה ישירה ל-run_campaign/run_tzintuk/schedule_* בטאב מחוץ ל-lambda/_run_blocking = קפיאת מסך
    bad = [m.group(0) for m in re.finditer(
        r"^\s*(?:\w+\s*=\s*)?yemot\.(run_campaign|run_tzintuk|schedule_campaign|schedule_smart|upload_message_wav)\(",
        t, re.M)]
    return not bad, "; ".join(b.strip() for b in bad)


@lint("I21", "since_iso בכל worker")
def _(y, t, test, rel):
    return ("since_iso" in _class_body(t, "_PollWorker")
            and "since_iso" in _class_body(t, "_CallbackWorker")), ""


@lint("I22", "QDateTimeEdit: LeftToRight לפני setDisplayFormat")
def _(y, t, test, rel):
    for m in re.finditer(r"setDisplayFormat\(", t):
        before = t[max(0, m.start() - 400):m.start()]
        if "LeftToRight" not in before:
            return False, f"offset {m.start()}"
    return True, ""


@lint("I23", "test_tzintuk מפנה call_history.cache_path לפני ייבוא yemot")
def _(y, t, test, rel):
    a = test.find("call_history.cache_path =")
    b = test.find("from utils import sync, yemot")
    return 0 < a < b, ""


@lint("I24", "בדיקות ה-Qt מחליפות start של 3 ה-workers ב-no-op")
def _(y, t, test, rel):
    missing = [w for w in ("_PollWorker", "_CallbackWorker", "_TaskWorker")
               if f"tzmod.{w}.start = lambda self: None" not in test]
    return not missing, ", ".join(missing)


@lint("I25", "test_tzintuk.py ו-test_sync.py ברשימת TESTS של release.py")
def _(y, t, test, rel):
    missing = [x for x in TESTS if f'"{x}"' not in rel]
    return not missing, ", ".join(missing)


@lint("I26", "כל רשומת קמפיין נזרעת במספרים שלה (_seed_json); _on_sched_checked משמר report_json")
def _(y, t, test, rel):
    n_add = len(re.findall(r"db\.add_tzintuk_campaign\(", t))
    n_seed = len(re.findall(r"self\._seed_json\(", t))
    keep = _func_body(t, "_on_sched_checked").count('camp.get("report_json") or ""')
    # classic sends seed through tracker.entries(); every other creation site → _seed_json
    return n_seed >= n_add - 1 and keep >= 2, f"add={n_add} seed={n_seed} keep={keep}"


@lint("I27", "סיום מעקב-חזרה (קלאסי) מחדש מעקב שפוטר; _resume_classic מחזיר bool והלולאה ממשיכה")
def _(y, t, test, rel):
    return ("_maybe_resume_tracking()" in _func_body(t, "_on_cb_worker_done")
            and "if self._resume_classic(c):" in _func_body(t, "_maybe_resume_tracking")
            and "-> bool" in re.search(r"def _resume_classic\([^\n]*", t).group(0)), ""


@lint("I28", "_start_tracking מסרב למזהה קמפיין ריק (אין מה לסקור)")
def _(y, t, test, rel):
    return 'if not str(campaign_id or "").strip():' in _func_body(t, "_start_tracking"), ""


@lint("I29", "until_by_phone גם ב-_CallbackWorker (חלון v3.20 חל על מעקב קלאסי)")
def _(y, t, test, rel):
    return "until_by_phone" in _class_body(t, "_CallbackWorker"), ""


def run_lints() -> bool:
    y = _read("utils/yemot.py")
    t = _read("tabs/tzintukim.py")
    test = _read("test_tzintuk.py")
    rel = _read(".claude/skills/manhal-haluka/scripts/release.py")
    print("— לינט אינווריאנטים —")
    all_ok = True
    for ident, desc, fn in LINTS:
        try:
            ok, extra = fn(y, t, test, rel)
        except Exception as e:      # לינט שבור = אדום, לא שקט
            ok, extra = False, f"lint error: {e!r}"
        all_ok &= bool(ok)
        print(("  OK  " if ok else "  ✗   ") + f"{ident} {desc}" + (f"  [{extra}]" if extra else ""))
    return all_ok


def run_tests() -> bool:
    py = PY312 if os.path.exists(PY312) else sys.executable
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    all_ok = True
    for tf in TESTS:
        print(f"\n— {tf} —", flush=True)
        r = subprocess.run([py, tf], cwd=ROOT, env=env)
        ok = r.returncode == 0
        all_ok &= ok
        print(("  OK  " if ok else "  ✗   ") + tf)
    return all_ok


if __name__ == "__main__":
    args = set(sys.argv[1:])
    ok = True
    if "--tests-only" not in args:
        ok &= run_lints()
    if "--lint-only" not in args:
        ok &= run_tests()
    print("\n" + ("✓ בודק הצינתוקים: הכל ירוק" if ok else "✗ בודק הצינתוקים: יש בעיות"))
    sys.exit(0 if ok else 1)

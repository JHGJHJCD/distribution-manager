# -*- coding: utf-8 -*-
"""בודק לוגיקת המיילים — לינט אינווריאנטים סטטי + הרצת הבדיקות.

הרצה (מ-root של הפרויקט או מכל מקום):
    python .claude/skills/mail-check/scripts/check_mail.py [--lint-only] [--tests-only]

כל לינט = כלל מ-references/invariants.md שנלמד מבאג אמיתי / הכרעת המשתמש.
לינט אדום = מישהו החזיר באג ישן. יציאה 0 = הכל ירוק.
"""
import os, re, subprocess, sys

PY312 = r"C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TESTS = ["test_mail.py", "test_sync.py"]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _func_body(src, name, sig_hint="", kind="def"):
    """גוף פונקציה/מתודה/מחלקה (עד ההגדרה הבאה באותה הזחה או נמוכה ממנה)."""
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


# ctx: dict עם המקורות — m=mails.py, ml=mailer.py, ga=google_auth.py, eu=email_utils.py,
# st=settings.py, dbs=database.py, sy=sync.py, test=test_mail.py, rel=release.py
LINTS = []


def lint(ident, desc):
    def deco(fn):
        LINTS.append((ident, desc, fn))
        return fn
    return deco


# ── שליחה ──────────────────────────────────────────────────────────────────

@lint("M1", "send_batch: חריגה לכל נמען בנפרד (failed), should_stop → skipped")
def _(c):
    body = _func_body(c["ml"], "send_batch")
    return ("except Exception as e:" in body and 'row["status"] = "failed"' in body
            and 'row["status"] = "skipped"' in body and "should_stop()" in body), ""


@lint("M2", "SMTP: נמען שסורב = כישלון (if refused: raise); אין-אינטרנט → הודעה בעברית")
def _(c):
    body = _func_body(c["eu"], "send_email")
    conn = _func_body(c["eu"], "_connect_checked")     # 3.47: מיפוי שגיאות-החיבור עבר לכאן
    return ("if refused:" in body and "raise RuntimeError" in body
            and "except (OSError, smtplib.SMTPConnectError" in conn
            and "אין חיבור לאינטרנט" in conn), ""


@lint("M3", "gmail_send_raw: 401 → ריענון (force=True) וניסיון אחד נוסף; netblock נבדק")
def _(c):
    body = _func_body(c["ga"], "gmail_send_raw")
    return ("for attempt in (0, 1):" in body and "force=(attempt == 1)" in body
            and "if status == 401 and attempt == 0:" in body
            and "netblock.is_blocked(" in body), ""


@lint("M4", "_validate_message רץ ב-_send וב-_send_test")
def _(c):
    bad = [n for n in ("_send", "_send_test")
           if "self._validate_message(" not in _func_body(c["m"], n)]
    return not bad, ", ".join(bad)


@lint("M5", "btn_send פעיל רק: is_configured() and ok > 0 and not sending")
def _(c):
    return "btn_send.setEnabled(email_utils.is_configured() and ok > 0 and not sending)" \
        in _func_body(c["m"], "_update_metrics"), ""


@lint("M6", "_send: חסימת שליחה כפולה, add_mail_campaign לפני start(); _on_finished מעדכן בשני המסלולים")
def _(c):
    send = _func_body(c["m"], "_send")
    fin = _func_body(c["m"], "_on_finished")
    okk = ("if self._worker is not None or not self._validate_message(subject, body):" in send
           and "db.add_mail_campaign(" in send and "self._worker.start()" in send
           and send.index("db.add_mail_campaign(") < send.index("self._worker.start()"))
    okk = okk and fin.count("db.update_mail_campaign(") >= 2 and "isinstance(rows, Exception)" in fin
    return okk, ""


@lint("M7", "_close_stale_campaigns: רק המחשב הזה, לא השליחה הפעילה (_active_guid)")
def _(c):
    body = _func_body(c["m"], "_close_stale_campaigns")
    return ('c.get("status") == "sending"' in body and "== me" in body
            and 'c.get("guid") != self._active_guid' in body
            and '"interrupted"' in body), ""


@lint("M8", "_resend_failed: רק failed/skipped, valid_email, דרך _send")
def _(c):
    body = _func_body(c["m"], "_resend_failed")
    return ('in ("failed", "skipped")' in body and "mailer.valid_email(" in body
            and "self._send(targets, audience=" in body), ""


# ── UI לא קופא ─────────────────────────────────────────────────────────────

@lint("M9", "mails.py: אין send_email/send_batch/google_auth.connect inline (רק בתוך worker/lambda)")
def _(c):
    bad = []
    outside = c["m"].replace(_class_body(c["m"], "_SendWorker"), "")
    for m in re.finditer(r"^\s*(?:\w+\s*=\s*)?(email_utils\.send_email|mailer\.send_batch|google_auth\.connect)\(",
                         outside, re.M):
        # קריאה שמתחילה שורה (לא lambda/worker) = inline
        bad.append(m.group(1))
    # send_batch מותר רק בתוך _SendWorker.run
    if "mailer.send_batch(" not in _class_body(c["m"], "_SendWorker"):
        bad.append("send_batch not in _SendWorker")
    return not bad, ", ".join(bad)


@lint("M10", "settings.py: google_auth.connect ומייל-בדיקה דרך _BgWorker בלבד")
def _(c):
    st = c["st"]
    okk = "_BgWorker(google_auth.connect, self)" in _func_body(st, "_google_connect")
    okk = okk and "_BgWorker(" in _func_body(st, "_test_mail_settings")
    inline = re.findall(r"^\s*(?:\w+\s*=\s*)?google_auth\.connect\(", st, re.M)
    return okk and not inline, ""


# ── חיבור Google ───────────────────────────────────────────────────────────

@lint("M11", "loopback: 404 לבקשה בלי code/error (favicon) + לולאת handle_request עד got_it")
def _(c):
    h = _func_body(c["ga"], "do_GET")
    w = _func_body(c["ga"], "_wait_for_code")
    return ("self.send_response(404)" in h and 'if not q.get("code") and not q.get("error"):' in h
            and "while not server.got_it.is_set()" in w and "server.handle_request()" in w), ""


@lint("M12", "connect: PKCE code_verifier + state == expected_state + refresh_token חובה")
def _(c):
    body = _func_body(c["ga"], "connect")
    h = _func_body(c["ga"], "do_GET")
    return ('"code_verifier": verifier' in body and "state == self.server.expected_state" in h
            and "if not refresh:" in body and "raise GoogleAuthError" in body), ""


@lint("M13", "access_token: invalid_grant ('פג או בוטל') מנקה SET_REFRESH")
def _(c):
    body = _func_body(c["ga"], "access_token")
    return ('if "פג או בוטל" in str(e):' in body and 'db.set_setting(SET_REFRESH, "")' in body), ""


@lint("M14", "client_credentials: _secret → settings → json; import_client_file דוחה web/לא-גוגל")
def _(c):
    cc = _func_body(c["ga"], "client_credentials")
    imp = _func_body(c["ga"], "import_client_file")
    okk = (cc.index("from utils import _secret") < cc.index("db.get_setting(SET_CLIENT_ID)")
           < cc.index("CLIENT_FILE"))
    okk = okk and ".apps.googleusercontent.com" in imp and '"web" in data and "installed" not in data' in imp
    return okk, ""


@lint("M15", "google_refresh_token/google_email/google_client_id מסונכרנים (לא ב-EXCLUDED_SETTINGS)")
def _(c):
    m = re.search(r"EXCLUDED_SETTINGS\s*=\s*\{.*?\}", c["sy"], re.S)
    ex = m.group(0) if m else ""
    bad = [k for k in ("google_refresh_token", "google_email", "google_client_id", "google_client_secret")
           if k in ex]
    pref = re.search(r"EXCLUDED_SETTING_PREFIXES\s*=\s*\(([^)]*)\)", c["sy"])
    if pref and '"google' in pref.group(1):
        bad.append("prefix google_")
    return not bad, ", ".join(bad)


@lint("M16", "_secret.py ב-.gitignore; אין סוד גוגל/סיסמת-אפליקציה בקוד או בבדיקות")
def _(c):
    gi = _read(".gitignore")
    okk = _has(gi, r"^_secret\.py$") or _has(gi, r"_secret\.py")
    leaks = []
    for name in ("m", "ml", "ga", "eu", "st", "test"):
        src = c[name]
        if re.search(r"GOCSPX-[A-Za-z0-9_-]{10,}", src):
            leaks.append(name + ":client_secret")
        if re.search(r"1//0[A-Za-z0-9_-]{20,}", src):
            leaks.append(name + ":refresh_token")
    return okk and not leaks, ", ".join(leaks)


@lint("M17", "email_utils: is_configured = Google או SMTP; send_email הולך ל-Gmail API כשמחובר")
def _(c):
    eu = c["eu"]
    body = _func_body(eu, "send_email")
    return ("google_connected() or smtp_configured()" in _func_body(eu, "is_configured")
            and "if via_google:" in body and "google_auth.gmail_send_raw(" in body
            and body.index("gmail_send_raw(") < body.index("sess.server(cfg)")), ""


# ── נתונים וסנכרון ─────────────────────────────────────────────────────────

@lint("M18", "update_mail_campaign: status_ts = _utc_now(); _apply_mail_update דוחה >= ts")
def _(c):
    up = _func_body(c["dbs"], "update_mail_campaign")
    ap = _func_body(c["sy"], "_apply_mail_update")
    return ("ts = _utc_now()" in up and "sent_at" not in up
            and '(row["status_ts"] or "") >= ts' in ap), ""


@lint("M19", "_apply_mail_add idempotent לפי guid; seed נושא sent/failed/report_json ב-mail_add")
def _(c):
    ap = _func_body(c["sy"], "_apply_mail_add")
    snap = _func_body(c["sy"], "_snapshot_body")
    okk = "SELECT 1 FROM mail_campaigns WHERE guid=?" in ap and "return" in ap
    seg = snap[snap.find('log_change("mail_add"'):snap.find('log_change("mail_add"') + 400]
    okk = okk and all(k in seg for k in ('"sent"', '"failed"', '"report_json"'))
    return okk, ""


@lint("M20", "תבניות: LWW לפי updated_at בשני הצדדים, מחיקה רכה, get_mail_templates מסנן deleted=0")
def _(c):
    up = _func_body(c["dbs"], "upsert_mail_template")
    ap = _func_body(c["sy"], "_apply_mtpl_upsert")
    de = _func_body(c["dbs"], "delete_mail_template")
    ge = _func_body(c["dbs"], "get_mail_templates")
    return ('(row["updated_at"] or "") > ts' in up and '(row["updated_at"] or "") >= ts' in ap
            and "deleted=1" in de and "DELETE FROM mail_templates" not in de
            and "WHERE deleted=0" in ge), ""


@lint("M21", "_APPLIERS: mail_add/mail_update/mtpl_upsert; snapshot זורע mail_campaigns + mail_templates")
def _(c):
    sy = c["sy"]
    m = re.search(r"_APPLIERS\s*=\s*\{.*?\n\}", sy, re.S)
    ap = m.group(0) if m else ""
    snap = _func_body(sy, "_snapshot_body")
    missing = [k for k in ('"mail_add"', '"mail_update"', '"mtpl_upsert"') if k not in ap]
    if "FROM mail_campaigns" not in snap or "FROM mail_templates" not in snap:
        missing.append("seed")
    return not missing, ", ".join(missing)


@lint("M22", "reset_all_data מנקה mail_campaigns")
def _(c):
    return 'conn.execute("DELETE FROM mail_campaigns")' in _func_body(c["dbs"], "reset_all_data"), ""


@lint("M23", "כרטיס המקבל בחיפוש מהיר מציג מיילים (get_mails_for_recipient ב-search.py)")
def _(c):
    return "db.get_mails_for_recipient(" in _read("tabs/search.py"), ""


# ── מנוע הטקסט ─────────────────────────────────────────────────────────────

@lint("M24", "build_targets: dedupe לא-רגיש לאותיות + סיבת-דילוג לכל מי שלא נשלח")
def _(c):
    body = _func_body(c["ml"], "build_targets")
    return ("email.lower() in seen" in body and "addr.lower() in seen" in body
            and body.count('t["reason"] = ') >= 5), ""


@lint("M25", "render: {שם פרטי} = החלק השני של full_name (משפחה-קודם)")
def _(c):
    body = _func_body(c["ml"], "render")
    return ("full.split(None, 1)" in body and "parts[1] if len(parts) > 1 else parts[0]" in body), ""


@lint("M26", "html_body: כותרת = טבלה + width/height אטריבוטים על הלוגו, בלי flex/CSS height")
def _(c):
    body = "\n".join(l for l in _func_body(c["ml"], "html_body").splitlines()
                     if not l.strip().startswith("#"))
    return ("<table dir='rtl'" in body and "width='44' height='44'" in body
            and "display:flex" not in body and not _has(body, r"img[^>]*style='[^']*height")), ""


# ── בדיקות ─────────────────────────────────────────────────────────────────

@lint("M27", "test_mail.py: _TRANSPORT + _CODE_PROVIDER מוזרקים, DB זמני (tempfile) — אפס רשת")
def _(c):
    t = c["test"]
    return ("google_auth._TRANSPORT = " in t and "google_auth._CODE_PROVIDER = " in t
            and "tempfile.mkdtemp(" in t and "db.DB_PATH = os.path.join(" in t), ""


@lint("M28", "test_mail.py ו-test_sync.py ברשימת TESTS של release.py")
def _(c):
    missing = [x for x in TESTS if f'"{x}"' not in c["rel"]]
    return not missing, ", ".join(missing)


# ── v3.42: תקלה כללית עוצרת אצווה; הודעות SMTP נכונות; התקדמות נשמרת ─────────

@lint("M29", "send_batch: תקלה כללית (is_fatal) עוצרת את האצווה — השאר skipped עם הסיבה")
def _(c):
    body = _func_body(c["ml"], "send_batch")
    return ("if is_fatal(e):" in body and "fatal_msg = str(e)" in body
            and 'row["error"] = fatal_msg or STOP_MSG' in body
            and _has(c["ml"], r"^def stop_reason\(")), ""


@lint("M30", "SMTP: SMTPAuthenticationError נתפסת *לפני* OSError (יורשת ממנו) → הודעת סיסמה, "
             "MailFatalError; SMTPRecipientsRefused/SMTPDataError → עברית")
def _(c):
    body = _func_body(c["eu"], "send_email")
    conn = _func_body(c["eu"], "_connect_checked")     # 3.47: החיבור (ושגיאותיו) ב-_connect_checked
    i_auth = conn.find("except smtplib.SMTPAuthenticationError")
    i_os = conn.find("except (OSError, smtplib.SMTPConnectError")
    return (0 <= i_auth < i_os and "raise MailFatalError" in conn
            and "except smtplib.SMTPRecipientsRefused" in body
            and "except (smtplib.SMTPDataError, smtplib.SMTPSenderRefused)" in body
            and "fatal = True" in _class_body(c["eu"], "MailFatalError")), ""


@lint("M31", "GoogleAuthError.fatal: כתובת-נמען שגויה ושגיאה לא-מזוהה = fatal=False; "
             "מכסה/הרשאה/רשת = כללי (ברירת מחדל)")
def _(c):
    ga = c["ga"]
    body = _func_body(ga, "gmail_send_raw")
    return ("fatal: bool = True" in _class_body(ga, "GoogleAuthError")
            and 'raise GoogleAuthError("כתובת המייל של הנמען שגויה.", fatal=False)' in body
            and body.count("fatal=False") == 2), ""


@lint("M32", "המסך: _on_progress שומר התקדמות מקומית (sync=False); _on_finished מציג stop_reason")
def _(c):
    m = c["m"]
    prog = _func_body(m, "_on_progress")
    fin = _func_body(m, "_on_finished")
    # החתימה על שתי שורות — _func_body לא תופס אותה; חותכים ידנית
    i = c["dbs"].find("def update_mail_campaign(")
    upd = c["dbs"][i:i + 1500] if i >= 0 else ""
    return ("sync=False" in prog and "self._rows_acc[done - 1] = dict(row)" in prog
            and "mailer.stop_reason(rows)" in fin
            and "sync: bool = True" in upd and "if not sync:" in upd), ""


# ── v3.43: שליחה שנקטעה זוכרת את מי שלא נוסה; שליחה-חוזרת; עצור; קובץ עברי ─────

@lint("M33", "_send רושם את כל היעדים כ-pending (mailer.pending_rows) לפני start(); "
             "_close_stale_campaigns/_on_finished(Exception) → close_pending")
def _(c):
    m = c["m"]
    send = _func_body(m, "_send")
    stale = _func_body(m, "_close_stale_campaigns")
    fin = _func_body(m, "_on_finished")
    okk = ("mailer.pending_rows(targets)" in send
           and send.index("mailer.pending_rows(targets)") < send.index("self._worker.start()")
           and "mailer.close_pending(" in stale and "mailer.summarize(rows)" in stale
           and "mailer.close_pending(" in fin
           and _has(c["ml"], r"^def pending_rows\(") and _has(c["ml"], r"^def close_pending\(")
           and '"pending"' in c["ml"])
    return okk, ""


@lint("M34", "היסטוריה: כפתור 'שלח שוב לנכשלים' לפי תוכן הדוח (mailer.resendable) — לא רק failed>0")
def _(c):
    body = _func_body(c["m"], "_refresh_history")
    return ("mailer.resendable(" in body and _has(c["ml"], r"^def resendable\(")), ""


@lint("M35", "_send מפעיל מחדש btn_stop; _resend_failed נחסם באמצע שליחה פעילה (לא דורס טיוטה); "
             "קובץ מצורף חסר → אזהרה")
def _(c):
    m = c["m"]
    send = _func_body(m, "_send")
    res = _func_body(m, "_resend_failed")
    return ("self.btn_stop.setEnabled(True)" in send
            and "if self._worker is not None:" in res
            and res.index("if self._worker is not None:") < res.index("self._send(")
            and ("not os.path.exists(self._attachment)" in send
                 or "not os.path.exists(attachment)" in send)), ""


@lint("M36", "קובץ מצורף: add_header('Content-Disposition', 'attachment', filename=…) — לא השמה ישירה "
             "(שם עברי → כותרת שבורה)")
def _(c):
    body = _func_body(c["eu"], "send_email")
    return ('part.add_header("Content-Disposition", "attachment"' in body
            and 'part["Content-Disposition"] =' not in body), ""


@lint("M37", "דוח חוצה-מחשבים לפי guid: get_mails_for_recipient מתאים לפי guid; _resend_failed פותר "
             "כרטיס דרך get_recipient_by_guid, ו-rec_id רק כשהשליחה של המחשב הזה")
def _(c):
    dbs = _func_body(c["dbs"], "get_mails_for_recipient")
    res = _func_body(c["m"], "_resend_failed")
    return ("guid" in dbs and 'rg == guid' in dbs
            and "db.get_recipient_by_guid(" in res and "device" in res
            and 'db.get_mails_for_recipient(rec["id"], rec.get("guid")' in c["search"]), ""


@lint("M38", "SMTP: ניתוק/timeout באמצע sendmail נתפס (OSError/SMTPException) → עברית, לא חריגה גולמית")
def _(c):
    body = _func_body(c["eu"], "send_email")
    i = body.find("server.sendmail(")
    return i > 0 and "except (OSError, smtplib.SMTPException) as e:" in body[i:], ""


@lint("M39", "_send_test בודק שהקובץ המצורף קיים בדיסק (כמו _send)")
def _(c):
    body = _func_body(c["m"], "_send_test")
    return "os.path.exists(self._attachment)" in body, ""


@lint("M40", "המייל = mixed › alternative › [text/plain, related › [html, לוגו]] — תמיד גרסת טקסט-רגיל (3.45)")
def _(c):
    body = _func_body(c["eu"], "send_email")
    return ('MIMEMultipart("alternative")' in body and '"plain", "utf-8"' in body
            and "html_to_text(html_body)" in body and "alt.attach(related)" in body
            and "root.attach(alt)" in body), ""


@lint("M41", "From = formataddr((SENDER_NAME, כתובת)) + Date + Message-ID עם דומיין השולח (לא hostname)")
def _(c):
    body = _func_body(c["eu"], "send_email")
    return ("formataddr((SENDER_NAME, from_addr))" in body and 'root["Date"] = formatdate(' in body
            and 'root["Message-ID"] = make_msgid(domain=' in body), ""


@lint("M42", "send_batch ו-_send_test מעבירים text_body=הטקסט המרונדר (אותה זרימה בשני המקומות)")
def _(c):
    return ("text_body=plain" in _func_body(c["ml"], "send_batch")
            and "text_body=plain" in _func_body(c["m"], "_send_test")), ""


@lint("M43", "לוגו למייל = עותק מוקטן (MAIL_LOGO_PX) ליד ה-DB (DB_PATH, לא USER_LOGO_PATH) — לא המקור")
def _(c):
    body = _func_body(c["m"], "_logo_path")
    return ("MAIL_LOGO_PX" in body and "os.path.dirname(db.DB_PATH)" in body
            and "SmoothTransformation" in body), ""


@lint("M44", "html_body: כתובות אינטרנט הופכות לקישור (_linkify אחרי html.escape)")
def _(c):
    return "_linkify(html.escape(p))" in _func_body(c["ml"], "html_body"), ""


@lint("M45", "סגירת התוכנה באמצע שליחה: closeEvent שואל (confirm_close), ו-_abort_for_close עוצר, "
             "מחכה למייל הנוכחי וסוגר את הרשומה כ-interrupted עם close_pending (3.46)")
def _(c):
    main = _read("main.py")
    ce = _func_body(main, "closeEvent")
    ab = _func_body(c["m"], "_abort_for_close")
    cc = _func_body(c["m"], "confirm_close")
    return ("mt.sending_active() and not mt.confirm_close()" in ce and "e.ignore()" in ce
            and "w.stop()" in ab and "w.wait(" in ab and "mailer.close_pending(" in ab
            and '"interrupted"' in ab and "QMessageBox.StandardButton.No)" in cc), ""


@lint("M46", "Gmail API: מייל > JSON_RAW_LIMIT → GMAIL_UPLOAD_URL עם message/rfc822 (JSON מוגבל ל-10MB); "
             "413/too large = תקלה כללית (fatal) (3.46)")
def _(c):
    ga = c["ga"]
    body = _func_body(ga, "gmail_send_raw")
    return ("uploadType=media" in ga and "len(mime_bytes) > JSON_RAW_LIMIT" in body
            and '"message/rfc822"' in body and "status == 413" in body
            and "fatal=False" not in body.split("status == 413")[1].split("raise")[1]), ""


@lint("M47", "גודל מייל: send_email עוצר מייל > MAX_MAIL_BYTES (25MB) כ-MailFatalError לפני כל שליחה; "
             "תקרת הקובץ במסך = email_utils.MAX_ATTACHMENT_BYTES ≤ 18MB (base64 ×1.37) (3.46)")
def _(c):
    eu, m = c["eu"], c["m"]
    se = _func_body(eu, "send_email")
    mx = re.search(r"^MAX_ATTACHMENT_BYTES\s*=\s*(\d+)", eu, re.M)
    return ("len(mime_bytes) > MAX_MAIL_BYTES" in se and se.index("MAX_MAIL_BYTES") < se.index("if via_google:")
            and "raise MailFatalError(" in se.split("MAX_MAIL_BYTES")[1][:400]
            and mx and int(mx.group(1)) <= 18 and "email_utils.MAX_ATTACHMENT_BYTES" in _func_body(m, "_pick_attachment")), ""


@lint("M48", "שליחה-חוזרת לא דורסת טיוטה: _send(subject=, body=) מפורשים; _resend_failed לא קורא "
             "subject.setText/body.setPlainText; 'התנתק' = disconnect(revoke=False) + revoke_token ב-_BgWorker (3.46)")
def _(c):
    m, st = c["m"], c["st"]
    res = _func_body(m, "_resend_failed")
    send = _func_body(m, "_send", sig_hint="subject=None")
    dis = _func_body(st, "_google_disconnect")
    return (bool(send) and "self.subject.setText(" not in res and "self.body.setPlainText(" not in res
            and "subject=c.get(" in res and "self.subject.text()" not in send.split("def")[0].replace(
                "subject = self.subject.text() if subject is None else subject", "")
            and "disconnect(revoke=False)" in dis and "_BgWorker" in dis and "busy_cursor" not in dis), ""


@lint("M49", "שליחה-חוזרת עם הקובץ *המקורי*: mail_campaigns.attachment/with_header (DB+mail_add+seed+applier); "
             "_send(attachment=, with_header=); _resend_failed לוקח c.get('attachment'), קובץ חסר → שאלה (3.47)")
def _(c):
    m, dbs, sy = c["m"], c["dbs"], c["sy"]
    res = _func_body(m, "_resend_failed")
    send = _func_body(m, "_send", sig_hint="targets=None")
    add = _func_body(dbs, "add_mail_campaign")
    return (bool(send) and "attachment=attachment" in send and "with_header=1 if with_header" in send
            and 'c.get("attachment")' in res and "not os.path.exists(attachment)" in res
            and "QMessageBox.question" in res.split("self._send(")[0]
            and "attachment" in add.split("_sync_log")[1] and "with_header" in add.split("_sync_log")[1]
            and "attachment" in _func_body(sy, "_apply_mail_add")
            and '"attachment", "with_header"' in _func_body(sy, "_snapshot_body")
            and "ADD COLUMN attachment" in dbs and "ADD COLUMN with_header" in dbs), ""


@lint("M50", "SMTP: חיבור+login *אחד* לכל האצווה (SmtpSession דרך mail_session ב-send_batch); ניתוק של חיבור "
             "ותיק באמצע sendmail → reset + ניסיון נוסף אחד לאותו נמען (3.47)")
def _(c):
    eu, ml = c["eu"], c["ml"]
    body = _func_body(eu, "send_email")
    batch = _func_body(ml, "send_batch")
    return ("class SmtpSession" in eu and "session: \"SmtpSession | None\" = None" in eu
            and "for attempt in (0, 1):" in body and "sess.reset()" in body
            and "stale and attempt == 0" in body and "if own:" in body
            and "with email_utils.mail_session() as session:" in batch and "session=session" in batch), ""


@lint("M51", "עדכון-תוכנה באמצע שליחה: settings._start_download ו-_on_downloaded (לפני apply_update) עוברים "
             "דרך MailsTab.guard_update (quit() לא עובר ב-closeEvent) (3.47)")
def _(c):
    st, m = c["st"], c["m"]
    sd = _func_body(st, "_start_download")
    od = _func_body(st, "_on_downloaded")
    return ("_mails_guard_ok" in sd and "_mails_guard_ok" in od.split("apply_update(")[0]
            and "guard_update" in _func_body(st, "_mails_guard_ok")
            and "return self.confirm_close()" in _func_body(m, "guard_update")), ""


@lint("M53", "v3.50 עיצוב-טקסט: גוף ההודעה נקרא רק דרך _body_markup (לא toPlainText — מאבד עיצוב); "
             "render מבריח ערכים בגוף rich; html_body/to_plain/send_batch מכירים RICH_PREFIX")
def _m53(c):
    m = c["m"]
    reads = [ln for ln in m.splitlines() if "self.body.toPlainText()" in ln and "_body_plain" not in ln
             and "# noqa" not in ln]
    okk = (not reads and "richtext.document_to_markup(self.body.document())" in m
           and "richtext.load_into(" in m
           and "esc = html.escape if is_rich(out)" in _func_body(c["ml"], "render")
           and "if is_rich(text):" in _func_body(c["ml"], "html_body")
           and "text_body=to_plain(rendered)" in _func_body(c["ml"], "send_batch"))
    return okk, "; ".join(reads)[:200]


@lint("M52", "'שמור כתבנית' בשם של תבנית קיימת מעדכן אותה (guid של הקיימת) אחרי שאלה — לא כפילות-שם (3.47)")
def _(c):
    body = _func_body(c["m"], "_save_template")
    return ("x[\"name\"].strip().lower() == name.lower()" in body and "guid = same[\"guid\"]" in body
            and "QMessageBox.question" in body), ""


def run_lints() -> bool:
    ctx = {
        "m": _read("tabs/mails.py"), "ml": _read("utils/mailer.py"),
        "ga": _read("utils/google_auth.py"), "eu": _read("utils/email_utils.py"),
        "st": _read("tabs/settings.py"), "dbs": _read("database.py"),
        "sy": _read("utils/sync.py"), "test": _read("test_mail.py"),
        "search": _read("tabs/search.py"),
        "rel": _read(".claude/skills/manhal-haluka/scripts/release.py"),
    }
    print("— לינט אינווריאנטים (מיילים) —")
    all_ok = True
    for ident, desc, fn in LINTS:
        try:
            ok, extra = fn(ctx)
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
    print("\n" + ("✓ בודק המיילים: הכל ירוק" if ok else "✗ בודק המיילים: יש בעיות"))
    sys.exit(0 if ok else 1)

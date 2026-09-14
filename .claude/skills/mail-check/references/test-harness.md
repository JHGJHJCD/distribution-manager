# מתכון לבדיקה מדומה — `test_mail.py`

הקובץ הוא סקריפט עצמאי (לא pytest; `sys.exit` בסוף). מוסיפים **סעיף ממוספר חדש** בסוף
(לפני בלוק ה-`disconnect` והסיכום), בסגנון:

```python
# ─── 6. v3.42 — <כותרת קצרה> ─────────────────────────────────────────────
print("— v3.42: <כותרת> —")
```

## עוגנים שכבר קיימים בקובץ (השתמש, אל תשכפל)
- `ok(name, cond, extra="")` — רושם OK/✗ ומצטבר ל-`fails`.
- `use_machine(dir_a | dir_b)` — מחליף DB/sync_state/outbox = "מחשב A"/"מחשב B"; `shared` = תיקיית Drive מדומה.
- `fake_transport(method, url, data, headers)` + `calls` — תשובות מוקלטות ל-`TOKEN_URL` (code/refresh,
  `DEAD` → invalid_grant), `GMAIL_SEND_URL` (`Bearer STALE` → 401; נמען `bad@` → 400), `REVOKE_URL`.
  מוזרק ב-`google_auth._TRANSPORT`; `google_auth._CODE_PROVIDER` מחזיר קוד בלי דפדפן.
- `google_auth.connect()` כבר רץ בסעיף 1 → המכונה "מחוברת" (`kupa@gmail.com`).

## דפוסים
**שליחה מדומה דרך Gmail (מה יצא בפועל):**
```python
n0 = len(calls)
rows = mailer.send_batch(targets, "נושא {שם}", "גוף", ctx, rec_by_id=recs)
sent = [c for c in calls[n0:] if c[1] == google_auth.GMAIL_SEND_URL]
raw = base64.urlsafe_b64decode(json.loads(sent[0][2])["raw"] + "==")   # ה-MIME עצמו
```
**כישלון בנמען אחד בלי להפיל את האצווה:** יעד עם `bad@x.com` (ה-transport מחזיר 400) → `status=failed`, השאר `sent`.

**עצירה באמצע:**
```python
flag = {"stop": False}
def prog(d, t, r): flag["stop"] = True      # אחרי הראשון
rows = mailer.send_batch(targets, "s", "b", progress=prog, should_stop=lambda: flag["stop"])
ok("השאר skipped", [r["status"] for r in rows] == ["sent", "skipped", ...])
```
**מסלול SMTP (בלי גוגל):** `google_auth.disconnect(revoke=False)` + `email_utils.set_smtp_config(...)`,
ואז להחליף `email_utils._connect = lambda cfg: FakeSMTP()` (אובייקט עם `sendmail` שמחזיר dict-סירוב ו-`quit`).
**תמיד** להחזיר את המקורי בסוף הסעיף.

**מחשב שני:** `use_machine(dir_b)`; `sync.pull_changes()`; להשוות `db.get_mail_campaign(guid)`.
LWW נבדק לפי `status_ts` (עדכון ישן לא דורס חדש).

**מסך (Qt, offscreen):** כמו בסעיפי ה-Qt של `test_tzintuk.py` —
`import tabs.mails as mmod`, `mmod._SendWorker.start = lambda self: None`, `tab = mmod.MailsTab(None)`,
ואז לקרוא ל-`tab._on_progress(...)`/`tab._on_finished(rows)` ידנית. `QMessageBox.question` → להחליף
ב-`lambda *a, **k: QMessageBox.StandardButton.Yes` לפני `tab._send()`.

## הרצה
```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_mail.py
```
או הבודק המלא: `python .claude\skills\mail-check\scripts\check_mail.py` (לינט + mail + sync).
כל הבדיקות: `release.py` מריץ את `TESTS` — `test_mail.py` חייב להישאר שם (לינט M28).

# מתכון לבדיקה מדומה — `test_tzintuk.py`

הקובץ הוא סקריפט עצמאי (לא pytest; `sys.exit` בסוף). מוסיפים **סעיף ממוספר חדש** בסוף, בסגנון:

```python
# ── 20. v3.21 — <כותרת קצרה> ──
print("— v3.21: <כותרת> —")
```

## עוגנים שכבר קיימים בקובץ (השתמש, אל תשכפל)
- `ok(name, cond, extra="")` — רושם OK/✗ ומצטבר ל-`fails`.
- `fake_transport(command, params)` + `canned` + `calls` — תשובות מוקלטות לכל פקודת API; `calls` = מה נשלח.
  **תמיד** להחזיר `yemot._TRANSPORT = fake_transport` אחרי transport מיוחד.
- DB זמני (מופנה בראש הקובץ) · `call_history.cache_path` → תיקייה זמנית **בראש** (I23).
- סעיף 14 ואילך: `QApplication` offscreen, `import tabs.tzintukim as tzmod`,
  `_PollWorker/_CallbackWorker/_TaskWorker.start = lambda self: None`, `tab = tzmod.TzintukimTab(None)`.
- `_camp(guid)` — שולף רשומת קמפיין מה-DB.

## דפוסים
**transport שזורק (רשת):**
```python
def dead_transport(command, params):
    raise urllib.error.URLError("timeout")
yemot._TRANSPORT = dead_transport
try:
    yemot.run_campaign({...}); ok("…", False)
except Exception as e:
    ok("חיוג = ניסיון אחד", sum(c[0] == "RunCampaign" for c in calls) == 1, str(e))
yemot._TRANSPORT = fake_transport
```
**tick ידני על worker בלי thread:**
```python
tab._active_guid = g
tab._start_tracking("camp-X", 3, since_iso)
w = tab._worker
tab._on_tick({"finished": True, "total": 3, "delivered": 2, "failed": 1, "pending": 0,
              "entries": [{"phone": "0521111111", "ok": True, "status": "done"}]}, w)
```
**מחשב שני:** כמו בסעיף "סנכרון 2 מחשבים" — LWW נבדק לפי `status_ts`.
**סקר 77:** `yemot.merge_survey_answers(entries, rows, since, until_by_phone)` עם שורות
`{"phone": …, "answer": "1", "at": iso}`.

## הרצה
```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_tzintuk.py
```
או הבודק המלא: `python .claude\skills\tzintuk-check\scripts\check_tzintuk.py` (לינט + tzintuk + sync).
כל הבדיקות: `release.py` מריץ את `TESTS` — קובץ בדיקה חדש חייב להתווסף שם (מלכודת ידועה).

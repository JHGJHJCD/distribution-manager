# תוכנית-מגירה — מעקב שינויים בתצורת קו ימות ("מצלמת אבטחה לקו")

> סטטוס: **תוכנית בלבד, לא מומש.** נשמר 9/9/2026 אחרי חקירה, לפי בקשת המשתמש לעצור
> ולהשאיר תוכנית מפורטת. כל הממצאים כאן אומתו חי מול הקו דרך MCP `pitron-ivr` (קריאה בלבד).
> כשמרימים את זה — לטעון קודם את הסקילים `feature-impact`, `tzintuk-check`, `db-migration`,
> `manhal-haluka`, ולקרוא את המקטע "צינתוקים" ב-`CLAUDE.md`.

## 1. מה המשתמש ביקש (וההכרעות שכבר התקבלו)
בקשה: "מערכת שתעקוב אחר כל שינוי שקורה בהגדרות ובכלל בימות המשיח, כך שאם תהיה תקלה נוכל
לראות **מי** שינה, **מתי** שינה — ולתקן." + "שאם יהיה שינוי תוכל לקרוא לוגים הכי מדויקים,
יותר ממה שכבר מובנה בימות."

הכרעות המשתמש (דרך שאלות ממוקדות):
- **מה עוקבים:** תצורת הקו **בימות עצמו** (שלוחות, ניתובים בשורש, תבניות/קמפיינים, הקלטות).
  לא הגדרות התוכנה ולא יומן-הכתיבות-שלנו.
- **כיסוי:** **גם 24/7 בענן וגם בתוך התוכנה** (בחר "גם 24/7 בענן"). כלומר שתי שכבות.
- **איפה רואים:** במקום הכי נגיש — מסך בתוך התוכנה + התראה, "כמו מצלמה שרואה כל תזוזה".
- **קצב:** "תבנה ותשחרר הכל" (לא דוגמה קודם).

## 2. הבשורה הגדולה — לימות יש יומנים מובנים שאפשר למשוך
זה נותן **"מי + מתי" אמיתי**, לא רק השוואת-צילומים שלנו. אומת חי שקיימים בקו:

| מקור | מה נותן | איך מושכים |
|------|---------|-----------|
| **`GetLoginLog`** (Management API) | מי נכנס לניהול הקו ומתי — זה ה"מי שינה" | חתימה: `GetLoginLog(limit, username)` → `list[GetLoginLogEntry]`. מקור: f2 post/64050. **את מבנה ה-Entry (זמן/מספר/IP) עדיין צריך לאמת חי** — אין כלי MCP ישיר, לממש ב-`yemot.py` דרך `_call("GetLoginLog", {...})` ולהדפיס פעם אחת מה חוזר. |
| **`ivr2:/Log/LogApi.ymgr`** | יומן כל קריאות ה-API לקו (מתעדכן חי, כולל היום — 3.8MB) | `_download("ivr2:/Log/LogApi.ymgr")` |
| **`ivr2:/Log/LogRouting.ymgr`** | יומן ניתובי שיחות (מתעדכן חי) | `_download(...)` |
| **`ivr2:/Log/LogFolderEnterExit-YYYY-MM.ymgr`** | כניסה/יציאה לכל שלוחה | כבר מנוצל ב-`utils/call_history.py` — לחקות |
| **`GetTasksLogs(task_id)`** | יומן משימה מתוזמנת | f2 post/78443 |

⚠ הערה: לא מצאתי ב-API של ימות "audit log של עריכות שדות" שמראה *איזה שדה* שונה ובידי מי.
לכן ה"מה בדיוק השתנה" חייב לבוא מ**השוואת-צילומים שלנו** (סעיף 4), וה"מי + מתי" מ-`GetLoginLog`
+ mtime של הקובץ ששונה. השילוב = "שלוחה 76 השתנתה ב-14:38, וב-14:37 נכנס לניהול המספר X".

## 3. מבנה הקו (אומת חי 9/9/2026) — מה בעצם מצלמים
- הקו **משותף**: `lineId=4054668f-…`, מערכת "קופה של צדקה הר יונה", ~27,272 יחידות.
- שלוחות הקופה (מנהל חלוקה): **76** (שרת המענה, type=api) · **77** (אישור הגעה, recording_and_entering_data)
  · **78** (הודעת החלוקה, menu — מת).
- שלוחות של **גורמים אחרים על אותו קו**: `555` "מערכת חדשה למתרימים", `7` "סקר", `13` "שאלון חדש",
  `50` "קמפיין בין המצרים", `10/12` api, `2` routing, `3` routing_time, `4` record, ועוד — כל
  שינוי שלהם ייתפס גם הוא (זו בדיוק הסכנה: מי שיש לו סיסמת הקו יכול לשנות/למחוק את 76/77 בטעות).
- קבצי לוג בשורש `ivr2:/Log/` (173 קבצים) — ראה טבלה למעלה.

צילום תצורה = לכל שלוחה `ivr2:/<ext>/ext.ini` (טקסט) + קבצי השורש (`ext.ini`, `Did_Go_To.ini`,
`ExtensionNumbersAndAssociations.ini`) + `GetTemplates` (שמות/הגדרות תבניות) + עץ הקבצים עם mtime/size.

## 4. הארכיטקטורה המתוכננת

### שכבה A — בתוך התוכנה (ניתן לבנות ולאמת מלא)
1. **`utils/line_watch.py`** — מודול **טהור** (בלי Qt/רשת). callbacks מוזרקים (`list_dir`,
   `read_text`, `get_templates`) → בדיק בקלות עם transport מדומה.
   - `capture(readers) -> snapshot` : `{at, files:{path:{text,mtime,size}}, templates:{id:{...}}, ext_titles:{ext:title}}`.
   - `diff(old, new) -> [changes]` : לכל ini שהשתנה — diff **שורה-שורה** (`key=value`) כדי לדעת
     איזה מפתח בדיוק (added/removed/modified + old/new). גם שלוחה/תבנית/קובץ שנוסף/נמחק.
   - `describe(change) -> str` עברית: "שלוחה 76 (שרת המענה) — השדה `api_link` שונה מ-… ל-…".
   - ה"מי/מתי" (login-match) **לא** כאן — בשכבה מעל.
2. **`utils/yemot.py`** — פונקציות **קריאה בלבד** (לא ב-`_DIAL_COMMANDS`, retry בטוח, 418=נטפרי):
   - `capture_line_config()` — עוטף את `line_watch.capture` עם `_call("GetIVR2Dir")` (מחזיר
     `{"dirs":[{name,exists}], "files":[...]}`), `_read_text(path)`, `_call("GetTemplates")`.
     ייעול: אפשר קודם לצלם עץ+mtime, ולהוריד תוכן ini רק לשלוחות שה-mtime שלהן זז.
   - `get_login_log(limit=50)` — `_call("GetLoginLog", {...})`, מיפוי לרשומות {at, who, ...}.
   - `login_hint_for(mtime)` — מהיומן, מי נכנס סמוך ל-mtime של הקובץ ששונה.
3. **`database.py`** (לפי `db-migration`):
   - טבלה מסונכרנת `line_changes` (guid, detected_at, changed_at(mtime), device, source
     [ours/external/unknown], summary, details_json, login_hint, status[new/reviewed], status_ts).
   - הצילום המלא האחרון = **מקומי בלבד** בקובץ ליד ה-DB (`%APPDATA%\ManhalHaluka\line_snapshot.json`,
     כמו `yemot_history.json`) — **לא** בסנכרון (כבד; השרת הוא מקור-האמת).
   - `add_line_change(...)` → `_sync_log("lw_add", {...})` ; `mark_line_change_reviewed(guid)` → `lw_status`.
   - **חובה seed ב-`snapshot()`** אחרת מחשב שמצטרף לא יקבל את ההיסטוריה.
4. **`utils/sync.py`** — `_apply_lw_add` + `_apply_lw_status` (LWW לפי status_ts) ב-`_APPLIERS`,
   ו-seed ב-`snapshot()`. `EXCLUDED_SETTINGS`: אם יהיה טוקן/סוד לשרת הענן — לא לסנכרן אותו לקבצים
   שנכנסים ל-git (כמו `yemot_password`).
5. **worker רקע + התראה** — לחקות את `_SyncWorker(QThread)` ב-`main.py` / `_TaskWorker` ב-
   `tabs/tzintukim.py`: צילום בעליית התוכנה (השהיה קצרה) + כל כמה שעות. שינוי חדש ⇒ `QSystemTrayIcon`
   balloon (כמו `_notify_update`/התראות ההורדה הקיימות ב-`main.py`), פעם אחת לכל שינוי.
   ⚠ אסור לגעת בווידג'טים מתוך ה-thread.
6. **מסך UI** — דיאלוג "יומן שינויים בקו" בהגדרות, לחקות את **`ManagerLogDialog`** הקיים
   (`tabs/settings.py`, כבר יש "יומן מנהל" עם before/after). עמודות: מתי · מה השתנה · מי (login) ·
   מקור. כפתור **"החזר את המצב הקודם"** — כותב חזרה את הערך הישן דרך `_upload_multipart`
   (⚠ **רק לשלוחות של מנהל חלוקה** / באישור מפורש; **אף פעם לא לשורש הקו** בלי diff ואישור).

### שכבה B — ענן 24/7 (כותבים קוד + מדריך; הפעלה ידנית, לא ניתן לאמת מכאן)
- **`dev/cloudflare/line_watch_worker.js`** (או הרחבת ה-Worker הקיים `api_link_worker.js`):
  - **Cron Trigger** (Cloudflare) כל כמה שעות → `capture` את הקו דרך `fetch` ל-`call2all.co.il/ym/api`,
    משווה ל-snapshot הקודם ב-**D1** (כבר בשימוש ל-week_lists), כותב `line_changes` ומושך `GetLoginLog`.
  - endpoint `GET /line-changes?secret=` שהתוכנה קוראת ממנו וממזגת ל-`line_changes` המקומי (כמו
    ש-`callback_server._callback_server_rows` ממזג תשובות סקר — אותו דפוס בדיוק).
  - טוקן ימות נשמר כ-**secret** של ה-Worker (`env.YEMOT_TOKEN`).
- **מדריך פריסה** (README): הדבקת ה-JS ב"פיתוחים אישיים" בפתרונאי, הזנת `YEMOT_TOKEN` +
  `APP_SECRET` כ-secrets, הפעלת Cron, יצירת טבלאות D1.
- ⚠⚠ **סיכון אבטחה שהמשתמש אישר במפורש:** להחזיק את סיסמת/טוקן הקו המלא בענן = מי שמפרוץ
  ל-Worker/D1 שולט בקו (כולל 27K יחידות). לשקול: טוקן ייעודי אם ימות תומכים, או לפחות סוד חזק
  ולתעד. **נטפרי כבר פתחו את `workers.dev`** (v3.36) אז התוכנה יכולה לדבר עם ה-Worker.

## 5. מגבלות כנות (להגיד למשתמש)
- **"מי" הוא קירוב:** ימות לא נותנים "מי ערך את השדה הזה". הכי מדויק שאפשר = `GetLoginLog`
  (מי נכנס לניהול) + mtime של הקובץ. אם שני אנשים נכנסו סמוך — נראה את שניהם.
- **פריסת שכבה B ידנית** דרך פתרונאי — לא ניתן לאמת מהצ'אט; שכבה A לבדה כבר נותנת "מצלמה"
  מלאה (מי/מתי/מה/התראה/שחזור) בכל פעם שהתוכנה פתוחה באחד המחשבים (וזה כמעט תמיד).
- אם שינוי נעשה **ובוטל** בזמן ששני המחשבים כבויים — שכבה A לבדה תפספס אותו; רק שכבה B תתפוס.

## 6. סדר בנייה מוצע + Definition of Done
1. שכבה A מלאה (מודול טהור → yemot → DB+מיגרציה → sync → worker → UI) ואימות:
   `test_line_watch.py` (transport מדומה) + `test_sync.py` + `test_data_safety.py` עוברים,
   `python .claude/skills/tzintuk-check/scripts/check_tzintuk.py` ירוק, צילום מסך דרך `visual-check`.
2. שכבה B: קוד ה-Worker + מדריך פריסה (בלי הפעלה — לתעד "נותר לפרוס ולאמת בשטח" ב-`NEXT_TASK.md`).
3. תיעוד: שורת `vX.YZ` ב-`CLAUDE.md` (מקטע חדש "מעקב תצורת קו"), `NEXT_TASK.md`, `דיווח_תקלות.html`.
4. בנייה (`manhal-haluka`) + שחרור.

## 7. נקודות חיבור בקוד (כדי לא לחפש מחדש)
- `utils/yemot.py`: `_call(command, params)` (~191) · `_download(path)` (~1205) · `_read_text` (~661) ·
  `_upload_multipart` (~961, ה-*רק* כתיבה) · `GetIVR2Dir` מחזיר `dirs`/`files` (דוגמה ~836-853) ·
  `GetTemplates` (למשל ~544). קריאה בטוחה ל-retry; פקודות חיוג בלבד ב-`_DIAL_COMMANDS`.
- `database.py`: `_sync_log(op, payload)` (17) · `add_tzintuk_campaign`+`tz_add` (1799) = תבנית ל-op חדש
  (status_ts=now לעולם לא תאריך-עסקי; לשאת שדות סופיים בתוך ה-add). `init_db()` = מיגרציה additive.
- `utils/sync.py`: `_APPLIERS` (handlers) · `snapshot(include_settings=...)` (seed) · `EXCLUDED_SETTINGS`.
- `tabs/settings.py`: `ManagerLogDialog` = תבנית למסך היומן. `main.py`: `_SyncWorker`, `_notify_update`,
  התראות ההורדה = תבנית ל-worker+balloon.
- `dev/cloudflare/api_link_worker.js` + `utils/callback_server.py` = תבנית לשכבת הענן (D1, secret,
  `/push`+`/answers`, מיזוג רשומות מהשרת). נטפרי: `utils/netblock.py`.

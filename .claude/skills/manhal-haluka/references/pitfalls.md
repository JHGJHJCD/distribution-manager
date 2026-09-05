# Known Pitfalls — מנהל חלוקה

Traps that have cost us time before. Check the relevant one before touching that area.

## Environment / build
- **Python:** build & test only with `C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`.
  The PATH `python` is 3.14 and lacks PyQt6/openpyxl/qt-material — it fails silently.
- **EXE locked (WinError 5):** if the app is running it holds `dist/*.exe`. Delete first:
  `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"` (the release script does this automatically).
- **`.bat` files must be CRLF** — an edit that leaves LF breaks them; normalize line endings after editing.

## UI / rendering
- **Font: Segoe UI only.** Do **not** bring back Rubik (blurry render) and do **not** add
  `AA_EnableHighDpiScaling` (removed in PyQt6).
- **Never use `QGraphicsDropShadowEffect`** on a card inside a flexible layout — it breaks
  height negotiation and squashes content.
- **Hebrew screenshots:** run **without** the offscreen platform (offscreen renders squares).
  Use `WA_DontShowOnScreen` + `grab()`.
- Keep full RTL and user-facing simplicity on every UI change.

- **App-wide text size (v2.80):** most text sizes live in the QSS, so `app.setFont` alone changes
  almost nothing. The ONLY way to change text size is `styles.apply_app_theme(app, percent)`
  (rebuilds qt-material + EXTRA_QSS with every `font-size: Npx` scaled, then sets the font).
  Setting key: `ui_font_scale` (percent, per-machine, excluded from sync).
- **`QTableWidget.selectRow()` can silently no-op** — in dialog tables AND in main-tab
  tables (v2.93: it broke the right-click menu on 'חלוקות קודמות' — `_selected_batch`
  saw currentRow=-1 and the menu never opened). Always use `setCurrentCell(row, 0)`;
  with SelectRows behavior it selects the row AND fires `itemSelectionChanged` reliably.

- **QDateEdit/QDateTimeEdit in RTL:** the app-wide RTL direction reverses the date/time
  SECTION order (dd/MM/yyyy renders as yyyy/MM/dd, time and date swap). Fix: set the field
  `setLayoutDirection(LeftToRight)` **before** `setDisplayFormat(...)` — LTR after the format
  does NOT fix it. Canonical example: `widgets.DateEdit`; hit again in v2.87 `_ScheduleDialog`.

## Excel / printing
- **openpyxl:** use `get_column_letter(col)` only — `.column_letter` crashes on `MergedCell`.
- **Printing:** `QTextDocument` ignores `dir` → RTL columns must be written in reverse order manually
  (see `utils/print_view.py`). Values go through `html.escape`.

## Tests / data
- **Tests are standalone, not pytest:** each `test_*.py` calls `sys.exit` at module level, so
  pytest crashes on collection. Run each with the py312 interpreter directly (or `release.py test`).
- **Settings leak:** a script that runs `init_db()` on a real DB can leak. Clean with
  `DELETE FROM settings WHERE key LIKE 'need_w_%'`.
- All source files are UTF-8; the terminal shows Hebrew as mojibake but the data is fine.

## Exit / _MEI (decided — do not touch)
- The "**_MEI / Failed to remove temporary directory**" message comes from PyInstaller's
  onefile **bootloader parent process** cleaning `_MEI` after the child exits — it **cannot be
  blocked from code** (`os._exit`/`_hard_exit` run in the child). On this machine NetFree holds
  the folder for scanning so the delete fails. It does **not** harm data. The only real fix is a
  onedir build, which would break the single-EXE updater. **User's decision (27/08/2026): leave
  it as is — do not invest in blocking it again.**
- **v2.84 (31/08/2026): `_cleanup_prev_mei` gutted a LIVE instance's _MEI dir** in the
  update-relaunch window (`mei_last` pointed at a running instance's dir; rmtree removed its
  unlocked files incl. `base_library.zip` → the app's first lazy import — the tzintuk
  connection check — died with "[Errno 2] ... base_library.zip", masquerading as a network
  error). Fixes, keep BOTH: (1) delete only after an **atomic `os.rename` liveness probe** —
  renaming a dir fails on Windows while any file inside is open/mapped, so a live (or
  NetFree-held) dir is skipped; (2) main.py **warms lazy network imports** (`ssl`,
  `http.client`, `urllib.request`, `encodings.idna`) at startup so a damaged _MEI can't break
  networking mid-run. Diagnostic that cracked it: the surviving files in the gutted dir were
  exactly the LOCKED ones (mapped DLLs/pyds) — the rmtree(ignore_errors) signature.
- **v2.91 (31/08/2026): ROOT CAUSE of the update-relaunch _MEI crash — PyInstaller env-var
  inheritance.** Symptom: `FileNotFoundError [Errno 2]` from **zipimport at startup** (main.py's
  top imports, e.g. `encodings.idna`) — **every time after an update**. Cause: `apply_update`
  relaunched the new EXE with `subprocess.Popen([exe])` **inheriting the parent's environment**,
  including PyInstaller's onefile markers (`_PYI_APPLICATION_HOME_DIR`, `_PYI_ARCHIVE_FILE`,
  `_PYI_PARENT_PID`, `_MEIPASS2`, …). The child bootloader then **reused the OLD process's `_MEI`
  dir instead of extracting its own**; when the old process hard-exited, its bootloader deleted
  that dir → the new process's `base_library.zip` vanished → crash on the first import. Fix
  (`utils/updater.py` `_child_env`): scrub all `_PYI_*`/`_MEIPASS2` vars from the env passed to
  `Popen`, forcing a clean independent extraction. **Whenever a frozen onefile app spawns another
  onefile EXE (self-relaunch included), always pass a scrubbed env** — never a bare `Popen([exe])`.
  This is the real fix; the v2.84 liveness-probe + import-warming are belt-and-suspenders.

## NetFree (network)
- NetFree can inject **HTTP 418 "Blocked by NetFree"** and break builds/downloads with no obvious
  cause. If something fails on the network for no reason, check whether the error body contains
  "Blocked by NetFree". Full workaround guide is in memory `reference-netfree`.

## Parallel Claude sessions on this repo (learned 30/08/2026, v2.81)
- The user sometimes opens **several chats working on the repo at once**. Before releasing,
  check `git status` — if there are modified/untracked files you didn't touch, they belong to
  another live session. **Do not** use `release.py ship` then (it runs `git add -A` and would
  sweep foreign WIP into your commit), and do not build from the main tree (the EXE would embed
  their half-done code).
- The safe recipe: commit **only your files** (`git add <paths>` + commit + push), then build
  and release from a clean detached worktree:
  `git worktree add --detach <scratchpad>/wt HEAD` → run the full test suite there → PyInstaller
  there → `gh release create v<X> <wt>/dist/Manhal-Haluka.exe --latest` → `git worktree remove`.
- Do **not** stash the other session's files even briefly — it yanks them out from under the
  live session. (Tried it; user flagged it.) Leave foreign WIP untouched in the working tree.
- Shared docs (`CLAUDE.md`, `NEXT_TASK.md`, `דיווח_תקלות.html`) may already hold the other
  session's uncommitted lines — edit them freely but leave them uncommitted for the next
  quiet commit, unless you can commit only your own file.
- When the user says the parallel sessions **finished**, the opposite applies: the next release
  should sweep in their completed work too (`git add -A`), with their change mentioned in the
  release notes (happened in v2.82 — the horizontal single-recipient Excel export rode along).

## QComboBox inside a QTableWidget cell (learned 31/08/2026, v2.82)
- Repopulating a table that uses `setCellWidget` combos **must call `clearContents()` first** —
  otherwise old combos survive and "float" over the new rows (seen in the tzintukim tab).
- Don't `setItem` on a cell that got a widget; give the widget `setFixedHeight(40)` and the rows
  `verticalHeader().setDefaultSectionSize(48)` — the qt-material combo is taller than default rows.
- A column holding cell widgets needs `ResizeMode.Fixed` + explicit width (`setColumnWidth`) —
  `ResizeToContents` ignores cell widgets and clips them.
- Never rebuild the table synchronously from the combo's own signal (`currentTextChanged` →
  repopulate destroys the emitting combo mid-emit) — defer with `QTimer.singleShot(0, ...)`.

## רקע מ-QSS `background-image` נכשל בשקט (נלמד 31/08/2026, #uvee0)
- `setStyleSheet("background-image:url(...)")` על ווידג'ט רגיל עלול פשוט לא להציג כלום —
  בלי שגיאה — כשהתמונה/הנתיב לא נטענים (וגם אין דרך לגלות שנכשל). ב-QSS גם אי אפשר
  למתוח את התמונה (scale-to-cover).
- הדפוס הנכון (מיושם ב-`tabs/messages.py::_WallpaperArea`): לטעון `QPixmap` בקוד —
  אם `isNull()` מציגים הודעת שגיאה למשתמש — ולצייר ב-`paintEvent` עם
  `KeepAspectRatioByExpanding` (מילוי מרכזי כמו וואטסאפ). לבדוק את ה-pixmap **לפני**
  שמירת הקובץ/ההגדרה, כדי שכישלון לא ייראה כ"לא קרה כלום".

## דיאלוגים: שורת כפתורים צפופה מקצצת טקסט (v2.86)
חמישה כפתורים ב-QHBoxLayout אחד בדיאלוג צר — כפתור ה-primary מכווץ מתחת ל-sizeHint
והטקסט נחתך משני הצדדים (גם setMinimumWidth לא עוזר כשהשורה כולה over-constrained).
הפתרון: לפצל לשתי שורות (כלי-עזר למעלה, primary+סגור למטה) או להרחיב את הדיאלוג.

## רשימת ה-TESTS ב-release.py לא מתעדכנת לבד
כשמוסיפים קובץ test_*.py חדש — להוסיף אותו גם ל-TESTS ב-
`.claude/skills/manhal-haluka/scripts/release.py`, אחרת ship לא מריץ אותו
(test_tzintuk.py היה חסר שם עד v2.86).

## נטפרי חוסם את הצ'אט עצמו על קריאת PNG מסוים (1/9/2026 — 3 צ'אטים אבדו)
נטפרי סורק את גוף הבקשות ל-`api.anthropic.com` **כולל תמונות** (קטגוריית badwords, HTTP 418).
`Read` של צילום מסך מסוים (קרה עם `dev/shots_classic_track/*.png`) מקפיץ חסימה — ומאותו
רגע הצ'אט מת לצמיתות: התמונה נשלחת מחדש בכל בקשה, וגם "המשך שיחה" יורש אותה ונחסם מיד.
החסימה תלוית-קובץ (רוב הצילומים בפרויקט עוברים).
**כללים:** (1) צ'אט נחסם מיד אחרי קריאת צילום → לא לקרוא את הקובץ שוב באף צ'אט; לאמת דרך
ראיית Gemini: `gemini_task.py -f <png> "תאר..."` (בתיקיית "תיקיות שונות למיון\חוסך טוקנים").
(2) אחרי חסימה — צ'אט חדש נקי שמתחיל מ-NEXT_TASK.md, לא "המשך". (3) לעדכן את NEXT_TASK.md
לפני צעדים מסוכנים. (4) לא להדביק לצ'אט דפי-חסימה של נטפרי / JSON גולמי גדול.

## refresh() נקרא בכל סנכרון — מצב שהמפעיל בחר חייב לשרוד אותו (נלמד ב-3.13)
`MainWindow.refresh_all` מרענן את הלשונית הפתוחה בכל פעם שמגיע שינוי מהמחשב השני (כל ~20 שנ' כשהוא פעיל).
לשונית ש-`refresh()` שלה בונה את השורות מחדש **מוחקת סימוני V / תוצאות / בחירות** של המפעיל.
בצינתוקים: `prev_checked` לפי `_row_key` (id או צמד המספרים) + `_last_final`. **כלל:** בכל `refresh()`
שבונה מחדש — לשמור קודם את מצב-המשתמש במפה ולהחיל אותו על השורות החדשות.

## שני "עוקבים" שחולקים רצועת-התקדמות ו-`_active_guid` — לא במקביל (נלמד ב-3.13)
`_check_scheduled` (תזמון שהגיע זמנו) חייב להיבדק מול **כל** ה-workers (`_worker` וגם `_cb_worker`),
אחרת מעקב קלאסי ותזמון-שהבשיל כותבים תוצאות אחד לרשומת ה-DB של השני.

## התחלת מעקב חדש חייבת לפטר את הקודם (נלמד ב-3.14)
דיאלוג מודאלי (אישור שליחה) לא עוצר את טיימר הסנכרון — `refresh()` רץ בתוכו ויכול להתחיל worker
(`_maybe_resume_tracking`/תזמון שהבשיל). כל נקודה ש**יוצרת** worker בלי guard (`_send`/`_resend_failed`)
חייבת לנתק+לעצור את הקודם, אחרת שני workers על אותה רצועה כותבים ל-`_active_guid` הלא-נכון.

## worker עם תקציב זמן — סיום בלי תוצאה = לחדש, לא לשתוק (נלמד ב-3.14)
`_PollWorker` מסתיים אחרי N סבבים גם כשהקמפיין עדיין רץ; בלי דגל (`timed_out`) המסך נשאר "שולח…"
והרשומה 'sending' עד רענון מקרי. כלל: כל לולאת-סקר מוגבלת מסמנת שפגה, וה-slot של `finished` מחדש.

## "לא נמצא" מהשרת ≠ "בוטל" כשהמזהה ריק (נלמד ב-3.14)
ביטול תזמון עם `campaign_id=""` מקבל 105 ומסומן 'canceled' — בזמן שהשרת עדיין מחייג בשעה המתוכננת.
לפני שמסמנים ביטול/כישלון על סמך "לא קיים" — לוודא שבכלל היה מזהה לשאול עליו.

## פקודה שמחייגת נשלחת פעם אחת — בלי retry ובלי שרת תאום (נלמד ב-3.15)
`_http` עשה ניסיון חוזר על כל כשל רשת ו-`_call` נפל לשרת private — גם ל-`RunCampaign`/`RunTzintuk`/
`ScheduleCampaign`. timeout **אחרי** שהשרת קיבל את הבקשה = הקמפיין כבר יצא, והחזרה שולחת אותו שוב
(עד ×4). כלל: פקודה לא-אידמפוטנטית נכנסת ל-`yemot._DIAL_COMMANDS` ויוצאת פעם אחת; הודעת השגיאה
אומרת "ייתכן שהשליחה כבר יצאה". קריאות/העלאות (אידמפוטנטיות) שומרות על ה-retry.

## כל התחלת מעקב מפטרת את *כל* המעקבים, לא רק מאותו סוג (נלמד ב-3.15)
ב-3.14 `_start_tracking` פיטר `_worker` בלבד; `_start_callback_tracking` עשה `return` שקט אם `_cb_worker`
רץ ולא נגע ב-`_worker`. תוצאה: קלאסי מעל סקר / שליחה מעל מעקב-חזרה — שניהם חיים, `_active_guid` אחד,
תוצאות נכתבות לרשומה הלא-נכונה, ומעקב שני נבלע. כלל: נקודת-כניסה אחת (`_retire_trackers`) לפני כל
worker חדש; worker נושא את ה-guid שלו וה-tick נושא את ה-worker (`lambda st, w=w:`), כדי ש-tick
שכבר בתור אחרי הפיטורים לא ינחת על הקמפיין החדש. מעקב שפוטר שומר מה שאסף ברשומה *שלו*.

## כפתור שמחליף מקור-רשימה חייב לאפס את המקורות האחרים (נלמד ב-3.15)
`_distribution_rows` בוחר לפי עדיפות `_free` → `_batch` → רשימת השבוע. `_load_week_list` איפס רק `_free`
⇒ עם batch טעון הכפתור "רשימת החלוקה הנוכחית" לא עשה כלום (והמפעיל שלח לאנשי החלוקה הקודמת).
כלל: מעבר מקור = איפוס כל המקורות האחרים + `_reset_results()` (תוצאות של רשימה קודמת לא צובעות שורות חדשות).

## מעבר רשימה חייב לאפס גם את "שלח שוב לנכשלים" (נלמד ב-3.16)
`_last_failed` + `btn_resend` נשארו מהקמפיין של הרשימה הקודמת אחרי `_reset_results` — לחיצה שלחה
לנכשלי החלוקה הקודמת ורשמה את הקמפיין על `dist_date` של הרשימה החדשה (שומר הכפילות ותשובות-הסקר
של השבוע זוהמו). כלל: כל מצב-משתמש שנגזר מקמפיין (תוצאות, נכשלים, כפתורי-המשך) מתאפס ב-`_reset_results`,
לא רק הטבלה. ובשיגור חכם — הנכשלים נגזרים מה-`_last_entries` **הממוזגים** (כל הקבוצות), לא מה-tick האחרון.

## "לא נמצא בשרת" על מזהה ריק — גם בבדיקת תזמון-שהבשיל, לא רק בביטול (נלמד ב-3.16)
3.14 תיקן את `_cancel_sched`; `_check_scheduled` עדיין שלח `find_scheduled("")` ⇒ "missing" ⇒ אחרי שעה
`sched_failed` בזמן שהשרת חייג, והתוצאות מעולם לא נעקבו. כלל: רשומת תזמון בלי `campaign_id` מאותרת לפי
**תבנית + שעה מתוכננת** (`yemot.find_scheduled_by_template`, ±20 דק' — התבנית משותפת בין שבועות, השעה בוחרת
את הריצה); PENDING נושא `time` ("YYYY-MM-DD HH:MM"), SUCCESSFUL/FAILED נושאים `startTime` (עם שניות).
מזהה שאותר בזמן PENDING נשמר לרשומה.

## מעקב שנפל על רשת = לחדש אחרי דקה, לא לחכות לביקור בלשונית (נלמד ב-3.16)
`_PollWorker` שוויתר אחרי 5 כשלים השאיר "החיבור למעקב נכשל" ורשומת 'sending' עד `refresh()` מקרי
(סנכרון/מעבר לשונית). דגל `failed` + `QTimer.singleShot(60s, _maybe_resume_tracking)` ב-`_on_worker_done`.

## מעקב שמתחדש יכול לעקוב אחרי קמפיין של *רשימה אחרת* — התוצאות לא שייכות למסך (נלמד ב-3.17)
`_maybe_resume_tracking` בוחר את רשומת ה-'sending' החדשה ביותר (גם של המחשב השני, גם של חלוקה קודמת
או רשימה עצמאית) — בלי קשר לרשימה שטעונה על המסך. `_on_tick`/`_on_cb_tick` צבעו את התוצאות על השורות
לפי מספר, ו"שלח שוב לנכשלים" רשם את השליחה החוזרת על `_dist_date_iso()` של הרשימה הטעונה ⇒ שומר-הכפילות
ותגי "אישר הגעה" של השבוע זוהמו מקמפיין של שבוע אחר. כלל: כל worker נושא `guid` + `dist_date` של הקמפיין
שלו; הכתיבה ל-DB לפי `worker.guid`; ציור לטבלה / `_last_failed` רק כש-`_results_belong_here(worker)`
(תאריך הקמפיין == תאריך הרשימה הטעונה); השליחה החוזרת נרשמת על `_last_failed_date` (תאריך הקמפיין), לא על
הרשימה. (`_apply_answer_rows` כבר סינן לפי תאריך — המעקבים החיים לא.)

## רשומת 'sending' בלי `campaign_id` = תקועה לנצח (נלמד ב-3.17)
`_maybe_resume_tracking` מדלג על רשומה רגילה בלי מזהה (אין מה לסקור) ⇒ "בתהליך" לנצח בהיסטוריה. כלל: מה
שאי-אפשר לסקור נסגר אחרי שעה כ-'done' (אותו כלל של `_on_sched_checked` לריצה בלי `campaignId`).

## שיגור חכם להיום — לומר *לפני* האישור על שעות שכבר עברו (נלמד ב-3.17)
`schedule_smart` דוחף קבוצה של שעה שעברה ל-+3 דק'; ההודעה על כך הופיעה רק *אחרי* השליחה. כל דחיפה/שינוי
שהשרת עושה לבקשת המפעיל חייב להופיע בדיאלוג האישור (`_past_hour_count`), לא בהודעת הסיום.

## מעקב-חזרה של צינתוק קלאסי — רק במחשב ששלח (הכרעת המשתמש 5/9/2026, v3.18)
רשומת 'sending' של צינתוק קלאסי מהמחשב השני נראית כמו "מעקב שנקטע" והתוכנה חידשה אותו כאן ⇒ שני
עוקבים כתבו snapshot-ים מתחרים לאותה רשומה (LWW) ותצפיות של השולח נמחקו. כלל: `_maybe_resume_tracking`
מדלג (continue, לא break) על צינתוק קלאסי שה-`device` שלו אינו `sync.device_name()`; לא כותבים לרשומה זרה.

## בדיקות-קדם לפני דיאלוג מודאלי מתיישנות בתוכו — לבדוק שוב אחרי האישור (נלמד ב-3.19)
`_send`/`_schedule`/`_smart_schedule` בדקו "תזמון ממתין?" ו"כבר נשלח לתאריך?" *לפני* חלון האישור;
טיימר הסנכרון ממשיך לרוץ בתוך `exec()` של הדיאלוג, והמחשב השני יכול לתזמן/לשלוח בינתיים. שליחה מיידית
עם `store_list=True` מחליפה את רשימת התבנית שהתזמון של המחשב השני עומד לחייג אליה. כלל: כל בדיקת-קדם
שתלויה במצב מסונכרן חוזרת על עצמה אחרי שהדיאלוג נסגר (`_changed_meanwhile` — מזהה רשומה *חדשה* לפי guid,
לא "יש/אין") ומבטלת עם הסבר.

## רשימות עצמאיות חולקות `dist_date=""` — התאמה לפי תאריך לא מבדילה ביניהן (נלמד ב-3.19)
`_results_belong_here`/`_apply_answer_rows` השוו `dist_date` — לכל הרשימות העצמאיות "" ⇒ תוצאות של רשימה
עצמאית א' נצבעו על ב' ו"שלח שוב לנכשלים" הציע את נכשלי א'. כלל: רשימה בלי תאריך מזוהה לפי guid הקמפיינים
שנשלחו *ממנה* (`_list_guids`, מתאפס ב-`_reset_results`, נרשם בכל שליחה/תזמון) — `_belongs_here(date, guid)`.

## `limit=30` בסריקת ההיסטוריה — שיגור חכם לבדו עושה 24 רשומות (נלמד ב-3.19)
`_answer_campaigns(limit=30)` (רענון תשובות-סקר של 14 יום) איבד קמפיינים מהשבוע שעבר אחרי שיגור חכם + כמה
שליחות. כלל: סינון לפי זמן — לא לפי מספר רשומות קטן; כל `get_tzintuk_campaigns(limit=N)` צריך N ≫ 24×שבועיים.

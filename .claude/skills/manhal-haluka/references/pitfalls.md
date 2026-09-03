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

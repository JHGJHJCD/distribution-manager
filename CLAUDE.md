# CLAUDE.md

הנחיות ל-Claude Code בעבודה על מאגר זה. סטטוס שוטף ("איפה עצרנו") — ב-`NEXT_TASK.md`, לא כאן.

> תחזוקה עצמית: בשינוי מבני משמעותי (לשונית/פיצ'ר גדול/שינוי בבנייה-שחרור) — עדכן קובץ זה באותה הזדמנות. סטטוס זמני → `NEXT_TASK.md`.

## עקרונות עבודה
- **המשתמש לא מתכנת** — לעבוד ולשחרר, לא להסביר צעדים טכניים. הערת-שחרור קצרה בעברית פשוטה בסוף.
- אל תשבור תאימות לאחור; אל תשנה שמות עמודות/שדות ב-DB בלי מיגרציה.
- שמור RTL מלא ופשטות למשתמש בכל שינוי UI.
- לפני מחיקת קוד — ודא שאינו בשימוש.
- כשאפשר לאמת — אמת בעצמך (בדיקה/צילום מסך אמיתי), אל תבקש מהמשתמש.

## Architecture Rules
- העדף שימוש בקוד קיים על פני כתיבת חדש; אל תשכפל לוגיקה — חלץ helper משותף.
- לוגיקה עסקית מחוץ ל-UI כשאפשר (`scoring.py`/`database.py` — מודולים טהורים), הלשוניות רק מציגות.
- שמור על הפרדה קיימת: `scoring` = חישוב, `database` = נתונים, `tabs/` = תצוגה, `utils/` = שירותים.

## סדר עדיפויות בהתנגשות
**שלמות נתונים → כללים עסקיים → יציבות → חוויית משתמש → איכות קוד.** כששניים מתנגשים, המוקדם מנצח.

## לפני סיום משימה (Before completing a task)
- הרץ את הבדיקות הרלוונטיות (`python test_X.py` הנוגעים לשינוי).
- אם נגעת ב-UI — אמת ויזואלית (צילום מסך אמיתי / הרצה), לא רק שהקוד רץ.
- בשינוי מבני — עדכן `CLAUDE.md`; בשינוי סטטוס — עדכן `NEXT_TASK.md`.

**Definition of Done:** השינוי עובד ואומת בפועל (לא רק "לא קרס"), הבדיקות הרלוונטיות עוברות, לא נשברה תאימות/שלמות נתונים, והתיעוד עודכן אם צריך.

## ⚠️ מלכודות ידועות (Known Pitfalls)
- **Python:** בנה/בדוק רק עם `C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`. ה-`python` שב-PATH הוא 3.14 וחסר PyQt6/openpyxl/qt-material.
- **גופן:** Segoe UI בלבד. **אל** תחזיר Rubik (רונדר מטושטש) ואל תוסיף `AA_EnableHighDpiScaling` (הוסר ב-PyQt6).
- **אל תשתמש ב-`QGraphicsDropShadowEffect`** על כרטיס בתוך layout גמיש — שובר את משא-ומתן הגובה ומכווץ תוכן.
- **openpyxl:** `get_column_letter(col)` בלבד — `.column_letter` קורס על MergedCell.
- **הדפסה:** `QTextDocument` מתעלם מ-`dir` → עמודות RTL נכתבות בסדר הפוך ידנית.
- **צילומי מסך עברית:** להריץ **בלי** offscreen (offscreen מרנדר ריבועים) — עם `WA_DontShowOnScreen` + `grab()`.
- **בדיקות:** קובצי `test_*.py` קוראים `sys.exit` ברמת המודול → pytest קורס באיסוף. הרץ כל אחד `python test_X.py`.
- **דליפת הגדרות:** סקריפט שמריץ `init_db()` על DB אמיתי עלול לדלוף — נקה `DELETE FROM settings WHERE key LIKE 'need_w_%'`.

## עץ הפרויקט
```
main.py            # tab_specs, splash, single-instance, DPI, יציאה
database.py         # SQLite + re-export של scoring
scoring.py          # מודול טהור: annotate_need_scores, NEED_FACTORS
widgets.py          # ProductsEditor ועוד
styles.py · version.py
tabs/
  group_update.py   # "חלוקה ורישום" (לשונית פתיחה)
  recipients.py     # CRUD מקבלים
  one_time.py       # חד-פעמי + ניקוד + רזרבה
  search.py         # "חיפוש מהיר" מאוחד
  distributions.py  # "חלוקות" (אצוות)
  settings.py       # סיסמה/עדכון/משקלים/SMTP
  review.py         # בדיקת כפילויות (דיאלוג בלבד)
  summary.py        # לא מחובר — אל תסתמך עליו
utils/
  email_utils.py · excel_utils.py   # זרימת מתנדבים
  print_view.py · updater.py · backup.py · feedback.py · ui.py · tour.py
dev/                # probe/screenshot/benchmark/stress/create_icon
test_*.py           # בשורש
```

## מה הפרויקט
אפליקציית Windows בעברית (RTL מלא) לניהול חלוקת מצרכים ל"קופה של צדקה הר יונה" (נוף הגליל), ~500 מקבלים. המנהל מפעיל **מתנדבים** שמחלקים בנקודה קבועה; המתנדבים לא נוגעים בתוכנה — מקבלים רשימה במייל, ממלאים מי הגיע, והקובץ מיובא חזרה.

## Tech Stack, הרצה ובנייה
- Python 3.12, PyQt6 6.11, SQLite, openpyxl, qt-material (theme light_blue). מייל דרך `smtplib`/`email.mime` (stdlib בלבד).
- אין שרת — EXE יחיד (PyInstaller, `מנהל_חלוקה.spec`), DB מקומי.
```
python main.py                                              # הפעלה (סיסמה: 1234)
python -m PyInstaller --noconfirm --clean מנהל_חלוקה.spec   # → dist/מנהל_חלוקה.exe
```
אם ה-EXE נעול (WinError 5) לפני בנייה: `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"`.

## נתונים ואבטחה
- DB + גיבויים ב-`%APPDATA%\ManhalHaluka\` (data.db, backups/) — נפרד מה-EXE, שורד עדכונים, מהגר DB ישן אוטומטית.
- סיסמה מגובבת PBKDF2 (`database.verify_password/set_password`), ברירת מחדל `1234`.
- גיבוי אוטומטי בהפעלה ולפני כל פעולה הרסנית (Online Backup API — הגיבוי הוא עותק). שחזור מאמת שהקובץ DB תקין לפני דריסה.

## לשוניות (6, סדר נגרר לפי `tab_order`)
מוגדרות ב-`main.py` `tab_specs`: חלוקה ורישום · מקבלים · חד פעמי · חיפוש מהיר · חלוקות · הגדרות.
- **`group_update.py` — "חלוקה ורישום"** (לשונית פתיחה, מיזוג weekly+group). מרובה מוצרים (`widgets.ProductsEditor` — כמות|סוג|מחק, כל שורה עם "כמות לאדם", נשמר כמחרוזת ב-`what_dist`) + הערה כללית. חיפוש מהיר מסנן את רשימת השבוע (`db.filter_recipients`). סימון מוחזק ב-`_checked_ids` (שורד סינון) + `_seen_ids` לסימון-מראש של חד-פעמיים. רישום → `bulk_add_distributions(..., dist_name, general_note)` (יוצר גם שורת אצווה). זרימת מתנדבים: `_dispatch_volunteer_email`/`_import_volunteer_results`.
  עיצוב (v2.37+): כרטיסים לבנים (`_make_card`/`_field`) על רקע `#f5f7fb`, כפתורים `_BTN_PRIMARY/_SUCCESS/_DANGER/_GHOST`, אייקוני-קו (`utils.ui.line_icon`), סרגל פעולות תחתון קבוע. כרטיסי פרטים+מוצרים+מתנדב עטופים ב-`QScrollArea` פנימי (`top_scroll`) כך שרשימת המקבלים (`list_card`, stretch=1) מקבלת את רוב הגובה — ויזואלי בלבד.
- **`recipients.py`** — CRUD מקבלים + דיאלוג, סינון עדיפות. כפתור "בדיקת כפילויות" → `review.py` כדיאלוג.
- **`one_time.py`** — חלוקת עדיפות לחד-פעמיים: ניקוד צורך, רזרבה, לחיצה על שם → פירוט ניקוד.
- **`search.py`** — "חיפוש מהיר" מאוחד. רשימה → כרטיס-פרופיל HTML + היסטוריה. `HighlightDelegate`, `BadgeDelegate`, ייצוא, `print_recipient_card`.
- **`distributions.py`** — "חלוקות": שורה לכל אצווה מ-`dist_batches`. לחיצה כפולה → `BatchDetailsDialog`, מחיקה `db.delete_batch`.
- **`settings.py`** — סיסמה, עדכון, משקלי ניקוד, גיבויים, איפוס, פאנל "מייל למתנדבים" (SMTP), פריסת 2 טורים.

## זרימת המתנדבים (`utils/email_utils.py` + `utils/excel_utils.py`)
- **שליחה:** `export_volunteer_checklist_to_excel` — אקסל מינימלי, עמודה מוסתרת `id` להתאמה, גיליון `meta` מוסתר, עמודת "הגיע?" עם DataValidation "כן,לא" וברירת מחדל "כן" (המתנדב רק מבטל מי שלא הגיע). `send_email` — multipart + לוגו inline (cid), STARTTLS.
- **ייבוא:** `import_volunteer_checklist` מתאים לפי id המוסתר (fallback לשם), `received = not (ריק/"לא")` — ייבוא ישיר להיסטוריה.
- SMTP דורש **App Password של Gmail** (myaccount.google.com/apppasswords, מצריך 2FA) שמזין המשתמש בהגדרות.
- כל ייצואי האקסל → תיקיית **הורדות** (`_downloads_dir`). לניקוי תא בטסט: `ws.cell(r,c).value = None`.

## עדיפות וניקוד צורך
- קוד מקור (מאקסל): 4=קבוע→שבועי · 3=ראשונה · 2=שנייה (3/2 = `PRIORITY_TIERS` לחד-פעמי) · 1/0/בירור/**ריק = נתונים בלבד, לא מסומנים ולא בשבועי**. נשמר כ-`priority`+`priority_raw`. **המספרים לא מוצגים** — רק תוויות עברית (תואמות `PRIORITY_BADGES` ב-`utils/ui.py`).
- `scoring.annotate_need_scores(rows, weights)`: 0–100 = שקלול 6 גורמים (`NEED_FACTORS`), משקלים מתכווננים (`need_w_*`, סכום 100). מאכלס `_score_parts` לפירוט בלחיצה.
- רזרבה: `one_time` עם `reserve_count` — N עיקריים + K הבאים; ההדפסה מפצלת ל"חלוקה"/"רזרבה" (landscape).

## כללים עסקיים קריטיים
- חד-פעמיים לא ברשימה השבועית. שם-חלוקה חובה לפני הדפסה/שליחה (למשל "חלוקת פסח").
- `calculate_next_dist`: שבועי≈+7, דו-שבועי≈+13, חודשי≈+29 — תמיד רביעי הקרוב. `get_weekly_list` מבטיח שרביעי הקרוב נכלל בכל יום בשבוע.
- מחיקת מקבל עם היסטוריה → `ValueError` (שנה סטטוס / מחיקה כפויה).
- הדפסה (`utils/print_view.py`): טבלה RTL (עמודות בסדר הפוך), לוגו + "קופה של צדקה הר יונה", ☐ בעמודת ביצוע, כיווץ גופן 11→6 למינימום דפים, ערכים דרך `html.escape`.

## עדכון אוטומטי (`utils/updater.py`) ושחרור
- repo `JHGJHJCD/distribution-manager`. בודק `releases/latest`, מוריד `Manhal-Haluka.exe`, מאמת שלמות, מחליף EXE רץ ומפעיל מחדש. בדיקה בהפעלה + כפתור בהגדרות.
- **משמעת שחרור:** `version.py` `APP_VERSION` → בנה → `cp dist/מנהל_חלוקה.exe dist/Manhal-Haluka.exe` (asset ASCII) → `git add/commit/push` → `gh release create vX.Y dist/Manhal-Haluka.exe --latest`.
- **`gh` לא ב-PATH:** `C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe` — הרץ `& $gh ...` מ-PowerShell (git עצמו ב-PATH). **רק Release** — לא לגעת בתיקיות/ZIP בשולחן. commit מסתיים ב-`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## יציבות והפעלה
- per-monitor-v2 DPI awareness ב-`main._set_windows_dpi_awareness`.
- מופע יחיד: `QSharedMemory` guard ב-`main._run` (משוחרר לפני self-update relaunch). חלון `showMaximized` + זוכר גאומטריה (`win_geometry`).
- יציאה: ב-frozen build `os._exit(code)` (`_hard_exit`) לדילוג על ניקוי `_MEI` בעייתי; `_cleanup_prev_mei` מנקה דליפה קודמת (`mei_last`). בטוח לנתונים.
- לוגו הקופה (`org_logo.png`): כותרת הדפסה, splash, רצועת מיתוג. אייקון EXE/taskbar נשאר `icon.ico`.
- משוב: `utils/feedback.py` → Google Form + JSONL מקומי.

## בדיקות
סקריפטים עצמאיים (לא pytest): `test_all`, `test_deep`, `test_data_safety`, `test_scenarios`, `test_search`, `test_priority_import`, `test_volunteer_flow`, `test_updater`. `dev/stress_test.py [rounds]` (offscreen, `PYTHONUTF8=1`). כל הקבצים UTF-8 (טרמינל מציג mojibake אך הנתונים תקינים).

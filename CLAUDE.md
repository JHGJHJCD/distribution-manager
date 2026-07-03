# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> תחזוקה עצמית: כשמתבצע שינוי מבני משמעותי (לשונית חדשה/מוסרת, פיצ'ר גדול, שינוי בזרימת בנייה/שחרור) — עדכן את הקובץ הזה באותה הזדמנות, בלי לחכות שיבקשו.

## מה הפרויקט
אפליקציית Windows בעברית (RTL מלא) לניהול חלוקת מצרכים ל"קופה של צדקה הר יונה" (נוף הגליל). המנהל מפעיל **מתנדבים** שמחלקים בנקודה קבועה; המתנדבים לא נוגעים בתוכנה — הם מקבלים רשימה במייל, ממלאים מי הגיע, והקובץ מיובא חזרה. ~500 מקבלים. המשתמש **לא מתכנת** — לעבוד ולשחרר עדכונים ברורים, בלי להסביר צעדים טכניים.

## Tech Stack
- Python **3.12**, PyQt6 6.11, SQLite, openpyxl, qt-material (theme light_blue). מייל דרך `smtplib`/`email.mime` (stdlib בלבד — אין תלות חדשה).
- אין שרת — EXE יחיד (PyInstaller, `מנהל_חלוקה.spec`), מסד נתונים מקומי.
- **בנייה/בדיקות: השתמש ב-`C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`.** ה-`python` שעל ה-PATH הוא 3.14 וחסר PyQt6/openpyxl/qt-material.

## הרצה ובנייה
```
python main.py                                     # הפעלה (סיסמה ברירת מחדל: 1234)
python -m PyInstaller --noconfirm --clean מנהל_חלוקה.spec   # בניית EXE → dist/מנהל_חלוקה.exe
```
לפני בנייה, אם ה-EXE נעול (WinError 5) מחק קודם: `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"`.

## נתונים ואבטחה
- DB + גיבויים ב-`%APPDATA%\ManhalHaluka\` (data.db, backups/) — נפרד מה-EXE, שורד עדכונים. מהגר DB ישן אוטומטית.
- סיסמה מגובבת **PBKDF2** (`database.verify_password/set_password`), ברירת מחדל `1234`.
- גיבוי אוטומטי בהפעלה ולפני כל פעולה הרסנית (Online Backup API — גיבוי הוא עותק, לא המקור). שחזור מאמת שהקובץ הוא DB תקין לפני דריסה.

## לשוניות בפועל — 5 בלבד (סדר נשמר בגרירה לפי מפתח יציב ב-`tab_order`)
מוגדרות ב-`main.py` `tab_specs`. הסדר: חלוקה ורישום · מקבלים · חד פעמי · חיפוש מהיר · הגדרות.
- `tabs/group_update.py` — **"חלוקה ורישום"** (לשונית פתיחה; מיזוג של weekly+group). scope combo (השבוע / הכל), סינון אזור, רישום קבוצתי, ייצוא אקסל מלא אוטומטי בשמירה, והדפסה. **זרימת מתנדבים:** "שלח למתנדב למילוי" / "ייבוא תוצאות ממתנדב" (`_dispatch_volunteer_email`, `_import_volunteer_results`); אחרי הדפסה מציע לשלוח גם למתנדב.
- `tabs/recipients.py` — CRUD מקבלים + דיאלוג. סינון עדיפות (קבוע/ראשונה/שנייה). כפתור "בדיקת כפילויות" פותח את `review.py` כדיאלוג (`_open_dup_check`).
- `tabs/one_time.py` — חלוקת עדיפות לחד-פעמיים: ניקוד צורך, **רזרבה**, לחיצה על שם → פירוט ניקוד.
- `tabs/search.py` — **"חיפוש מהיר" מאוחד** (נבנה מחדש ב-v2.24-2.25). רשימת אנשים → לחיצה מציגה כרטיס-פרופיל עשיר (HTML) + היסטוריית חלוקות. הדגשת מילת החיפוש (`HighlightDelegate`), תגי-צבע עדיפות/סטטוס (`BadgeDelegate`), ייצוא לאקסל, הדפסת כרטיס בודד (`print_recipient_card`).
- `tabs/settings.py` — סיסמה, עדכון תוכנה, **משקלי ניקוד**, גיבויים, איפוס, ופאנל **"מייל למתנדבים"** (SMTP). פריסה חסכונית ב-2 טורים (QGridLayout).
- **קוד מת שנשאר במקום:** `tabs/weekly.py` נמחק; `tabs/tracking.py` ו-`tabs/summary.py` כבר לא לשוניות/לא מחוברים (אל תסתמך עליהם). `review.py` נפתח כדיאלוג בלבד.

## זרימת המתנדבים (excel round-trip — `utils/email_utils.py` + `utils/excel_utils.py`)
- **שליחה:** `export_volunteer_checklist_to_excel` בונה אקסל מינימלי — עמודה מוסתרת `id` להתאמה, גיליון `meta` מוסתר (תאריך ISO/מוצר/כמות/מחלק/שם חלוקה), עמודת "הגיע?" עם DataValidation "כן,לא" **וברירת מחדל "כן"** (המתנדב רק מבטל מי שלא הגיע). `send_email` שולח multipart + לוגו inline (cid), STARTTLS.
- **ייבוא:** `import_volunteer_checklist` מתאים לפי ה-id המוסתר (fallback לשם אם התאמה יחידה), `received = not (ריק/"לא")`, שדה הערה כללית — **ייבוא ישיר להיסטוריה בלי בדיקה נוספת**.
- SMTP דורש **App Password של Gmail** (myaccount.google.com/apppasswords, מצריך 2FA) שמזין המשתמש בהגדרות. Google Sheets/Form נדחו (מיילים חוסמים טפסים).
- כל ייצואי האקסל נשמרים לתיקיית **הורדות** (`_downloads_dir`). `openpyxl`: להשתמש ב-`get_column_letter(col)` (לא `.column_letter` — קורס על MergedCell); לניקוי תא בטסט: `ws.cell(r,c).value = None`.

## עדיפות וניקוד צורך
- קוד מקור (מאקסל בלבד): 4=קבוע→שבועי · 3=עדיפות ראשונה · 2=עדיפות שנייה (3/2 = `PRIORITY_TIERS` לחד-פעמי) · 1/0/חובת בירור/**ריק = נתונים בלבד, לא מסומנים ולא נכנסים לשבועי**. נשמר כ-`priority` (INT) + `priority_raw`. **המספרים לא מוצגים** — רק תוויות עברית (ללא/קבוע/ראשונה/שנייה/בירור), תואמות למפתחות `PRIORITY_BADGES` ב-`utils/ui.py`.
- `_annotate_need_scores` (database.py): ניקוד 0–100 = שקלול 6 גורמים (`NEED_FACTORS`). משקלים מתכווננים בהגדרות (`need_w_*`, מסתכמים ל-100). מאכלס `_score_parts` לפירוט בלחיצה.
- רזרבה: `one_time` עם `reserve_count` — N עיקריים + K הבאים בתור; ההדפסה מפצלת ל"חלוקה" ול"רזרבה" (כתום, לרוחב/landscape).

## עדכון אוטומטי (utils/updater.py)
- repo: `JHGJHJCD/distribution-manager`. בודק `releases/latest`, מוריד `Manhal-Haluka.exe`, מאמת שלמות, מחליף EXE רץ (rename) ומפעיל מחדש. בדיקה אוטומטית בהפעלה + כפתור בהגדרות.
- **משמעת שחרור:** עדכן `version.py` `APP_VERSION` → בנה → `cp dist/מנהל_חלוקה.exe dist/Manhal-Haluka.exe` (asset ב-ASCII) → `git add/commit/push` → `gh release create vX.Y dist/Manhal-Haluka.exe --latest`.
- **`gh` לא ב-PATH** — הנתיב המלא: `C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe`. הרץ אותו מ-PowerShell עם `& $gh ...` (git עצמו כן ב-PATH ומחובר לדחיפה). **לפרסם רק Release** — לא לגעת בתיקיות/ZIP בשולחן העבודה. הודעת commit מסתיימת ב-`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## כללים עסקיים קריטיים
- חד-פעמיים לא מופיעים ברשימה השבועית. שם-חלוקה חובה לפני הדפסה/שליחה (למשל "חלוקת פסח").
- `calculate_next_dist`: שבועי≈+7, דו-שבועי≈+13, חודשי≈+29 — תמיד רביעי הקרוב. `get_weekly_list` דואג שרביעי הקרוב תמיד נכלל בכל יום בשבוע.
- מחיקת מקבל עם היסטוריה → `ValueError` (שנה סטטוס / מחיקה כפויה מפורשת).
- הדפסה (`utils/print_view.py`): טבלה RTL (עמודות בסדר הפוך — QTextDocument מתעלם מ-dir), לוגו + "קופה של צדקה הר יונה", ריבועי ☐ בעמודת ביצוע, כיווץ גופן אוטומטי 11→6 כדי שהכל ייכנס למינימום דפים, ערכים עוברים `html.escape`.

## תצוגה, יציבות והפעלה
- גופן **Segoe UI** (Rubik נוסה ב-v1.5 והוחזר ב-v1.8 — רונדר מטושטש). per-monitor-v2 **DPI awareness** ב-`main._set_windows_dpi_awareness` (אל תוסיף `AA_EnableHighDpiScaling` — הוסר ב-PyQt6).
- **מופע יחיד:** `QSharedMemory` guard ב-`main._run` (משוחרר לפני self-update relaunch). חלון נפתח `showMaximized` + זוכר גאומטריה (`win_geometry`).
- **יציאה:** ב-frozen build `os._exit(code)` (`_hard_exit`) כדי לדלג על ניקוי `_MEI` הבעייתי; `_cleanup_prev_mei` מנקה דליפה קודמת (`mei_last`). בטוח לנתונים (DB נשמר לכל פעולה).
- לוגו הקופה (`org_logo.png`) משולב: כותרת הדפסה, splash, ורצועת מיתוג מעל הלשוניות. אייקון EXE/taskbar נשאר `icon.ico` (מחסן).
- משוב משתמשים: `utils/feedback.py` שולח ל-Google Form + JSONL מקומי (גישת GitHub token ננטשה).

## בדיקות
**סקריפטים עצמאיים, לא pytest** — הרץ כל אחד `python test_X.py` (קוראים `sys.exit` ברמת המודול → pytest קורס באיסוף). מרכזיים: `test_all`, `test_deep`, `test_data_safety`, `test_scenarios`, `test_search`, `test_priority_import`, `test_volunteer_flow`, `test_updater`. `stress_test.py [rounds]` (offscreen) — הרץ עם `PYTHONUTF8=1`.
- **צילומי מסך עברית אמיתיים:** הרץ **בלי** offscreen, עם `WA_DontShowOnScreen` + `grab()` (offscreen מרנדר ריבועים במקום עברית).
- סקריפטים שמריצים `db.init_db()` על ה-DB האמיתי עלולים לדלוף הגדרות — נקה `DELETE FROM settings WHERE key LIKE 'need_w_%'`. כל הקבצים UTF-8; טרמינל מציג mojibake אבל הנתונים תקינים.

## איפה עצרנו
v2.25 משוחרר: מסך "חיפוש מהיר" נבנה מחדש עם כרטיס-פרופיל HTML עשיר. פתוח להמשך (טרם אושר): ייבוא-אוטומטי (IMAP) של מיילים חוזרים ממתנדבים. תלוי-משתמש: הזנת App Password של Gmail בהגדרות כדי לבדוק שליחת מייל אמיתית מקצה-לקצה.

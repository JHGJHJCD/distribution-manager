# מנהל חלוקה — Claude Context File

## מה הפרויקט
אפליקציית Windows לניהול חלוקת מצרכים לקהילה חרדית. חלוקה כל יום **רביעי** בנקודה קבועה, 2 אזורים: **בעלז** ו-**נתיב**. נדיב שולח מוצרים, אנשים באים לאסוף. ~500 מקבלים בפועל.

## Tech Stack
- Python **3.12**, PyQt6 6.11, SQLite, openpyxl, qt-material (theme light_blue).
- אין שרת — EXE יחיד (PyInstaller, `מנהל_חלוקה.spec`), מסד נתונים מקומי.
- **בנייה/בדיקות: השתמש ב-`C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`.** ה-`python` שעל ה-PATH הוא 3.14 וחסר PyQt6/openpyxl/qt-material.

## הרצה ובנייה
```
python main.py                                   # הפעלה (סיסמה: 1234)
python -m PyInstaller --noconfirm מנהל_חלוקה.spec  # בניית EXE → dist/מנהל_חלוקה.exe
```

## נתונים ואבטחה
- DB + גיבויים ב-`%APPDATA%\ManhalHaluka\` (data.db, backups/) — נפרד מה-EXE, שורד עדכונים. מהגר DB ישן אוטומטית.
- סיסמה מגובבת **PBKDF2** (`database.verify_password/set_password`), ברירת מחדל `1234`.
- גיבוי אוטומטי בהפעלה ולפני כל פעולה הרסנית; שחזור מאמת שהקובץ הוא DB תקין לפני דריסה.

## לשוניות (8, ניתנות לסידור מחדש בגרירה — הסדר נשמר ב-`tab_order`)
- `group_update.py` — רישום חלוקה קבוצתית (לשונית פתיחה). פעולה ראשית כחולה `#primary`.
- `weekly.py` — מי מקבל השבוע, צבעי דחיפות.
- `recipients.py` — CRUD מקבלים + דיאלוג 4-לשוניות. עדיפות בלשונית הראשית.
- `one_time.py` — חלוקת עדיפות לחד-פעמיים: ניקוד צורך, **רזרבה**, לחיצה על שם → פירוט ניקוד.
- `tracking.py` — היסטוריית חלוקות + change log.
- `search.py` — חיפוש מהיר רב-שדות + היסטוריית אדם.
- `review.py` — "בדיקת נתונים": כפילויות שמות/טלפונים.
- `settings.py` — סיסמה, עדכון תוכנה, **משקלי ניקוד**, גיבויים, איפוס.
- `summary.py` — קיים אך **לא מחובר** (orphaned; `get_summary` בשימוש בבדיקות/דשבורד-לשעבר).

## עדיפות וניקוד צורך
- קוד מקור (מאקסל בלבד): 4=קבוע→שבועי · 3=עדיפות ראשונה · 2=עדיפות שנייה (3/2 = `PRIORITY_TIERS` לחלוקת חד-פעמי) · 1/0/חובת בירור = נתונים בלבד. נשמר כ-`priority` (INT) + `priority_raw`. **המספרים לא מוצגים** — רק תוויות עברית (ללא/קבוע/ראשונה/שנייה/בירור).
- `_annotate_need_scores` (database.py): ניקוד 0–100 = שקלול 6 גורמים (`NEED_FACTORS`: per_soul/נפשות/ותק/הכנסות/דיור/רפואיות). משקלים מתכווננים בהגדרות, נשמרים כ-`need_w_*` ומסתכמים ל-100. מאכלס גם `_score_parts` לפירוט בלחיצה.
- רזרבה: `one_time` עם כמות (`reserve_count`) — N עיקריים + K הבאים בתור; ההדפסה מפצלת לקטע "חלוקה" וקטע "רזרבה" (כתום, לפי סדר עדיפות).

## עדכון אוטומטי (utils/updater.py)
- repo: `JHGJHJCD/distribution-manager`. בודק `releases/latest`, מוריד `Manhal-Haluka.exe`, מאמת שלמות הורדה, ומחליף את ה-EXE הרץ (rename trick) + הפעלה מחדש.
- בדיקה אוטומטית בהפעלה (`MainWindow._auto_check_updates`) + כפתור בהגדרות.
- **משמעת שחרור:** לעדכן `version.py` `APP_VERSION`, `gh release create vX.Y dist/Manhal-Haluka.exe --latest` (asset ASCII `Manhal-Haluka.exe`). **לפרסם רק את ה-Release** — לא לעדכן תיקיית/ZIP בשולחן העבודה.

## כללים עסקיים קריטיים
- חד-פעמיים לא מופיעים ברשימה השבועית.
- `calculate_next_dist`: שבועי≈+7, דו-שבועי≈+13, חודשי≈+29 — תמיד יום רביעי הקרוב.
- מחיקת מקבל עם היסטוריה → `ValueError` (שנה סטטוס / מחיקה כפויה מפורשת).
- RTL מלא: שמות מקבלים מודגשים בכל הטבלאות; כותרות מיושרות לימין (`MainWindow._apply_rtl_polish`).
- הדפסה (print_view): טבלה RTL (עמודות בסדר הפוך כי QTextDocument מתעלם מ-dir), שם הקופה "קופה של צדקה הר יונה", הבהרת מערכת-בהרצה, ללא עמודת נפשות, ערכים עוברים `html.escape`.

## תצוגה (Display)
- גופן **Segoe UI** (Rubik נוסה ב-v1.5 והוחזר ב-v1.8 — רונדר מטושטש).
- per-monitor-v2 **DPI awareness** נקבע בהפעלה (`main._set_windows_dpi_awareness`) — חיוני לחדות בצגים עם הגדלה.

## בדיקות
**סקריפטים עצמאיים, לא pytest** — הרץ כל אחד: `python test_X.py` (קוראים `sys.exit` ברמת המודול → pytest קורס באיסוף). 6 קבצים: test_all, test_deep, test_data_safety, test_search, test_updater, test_priority_import. `stress_test.py [rounds]` (offscreen, עומס מדורג) — הרץ עם `PYTHONUTF8=1`.

## נקודות דיבאג
- `AA_EnableHighDpiScaling` הוסר ב-PyQt6 — אל תוסיף (DPI מטופל ב-`_set_windows_dpi_awareness`).
- כל הקבצים UTF-8; הטרמינל מציג mojibake אבל הנתונים תקינים.
- סקריפטים שמריצים `db.init_db()` על ה-DB האמיתי עלולים לדלוף הגדרות (`need_w_*` וכו') — נקה עם `DELETE FROM settings WHERE key LIKE 'need_w_%'`.

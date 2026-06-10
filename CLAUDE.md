# מנהל חלוקה — Claude Context File

## מה הפרויקט
אפליקציית Windows לניהול חלוקת מצרכים לקהילה חרדית. חלוקה כל יום **רביעי** בנקודה קבועה. ~100 מקבלים, 2 אזורים: **בעלז** ו-**נתיב**. נדיב שולח מוצרים לנקודה, אנשים באים לאסוף.

## Tech Stack
- Python 3.12, PyQt6 6.11, SQLite (openpyxl לייצוא/ייבוא)
- אין שרת — קובץ EXE יחיד, מסד נתונים מקומי `data.db`

## הרצה
```
cd מנהל_חלוקה
python main.py        # הפעלה רגילה
run.bat               # הפעלה עם double-click
build_exe.bat         # בניית EXE עם PyInstaller
```
סיסמא ברירת מחדל: `1234`

## מבנה תיקיות
```
מנהל_חלוקה/
├── main.py           ← entry point, LoginDialog, MainWindow
├── database.py       ← כל פעולות SQLite (אין ORM)
├── styles.py         ← QSS dark blue theme + color constants
├── data.db           ← SQLite DB (נוצר אוטומטית)
├── tabs/
│   ├── group_update.py   ← לשונית ראשית: רישום חלוקה קבוצתית
│   ├── weekly.py         ← מי מקבל השבוע, צבעי דחיפות
│   ├── recipients.py     ← CRUD מקבלים + dialog עם שדות תאריך
│   ├── one_time.py       ← חד-פעמיים + אלגוריתם עדיפות
│   ├── tracking.py       ← היסטוריה + change log
│   ├── search.py         ← חיפוש מהיר + היסטוריית אדם
│   └── summary.py        ← דשבורד + הגדרות (סיסמא, גיבוי)
└── utils/
    ├── backup.py         ← גיבוי אוטומטי לתיקייה נבחרת
    ├── excel_utils.py    ← import/export Excel
    └── print_view.py     ← הדפסה Portrait עם QPrinter
```

## DB Schema (database.py)
- `recipients` — id, full_name, phone1/2/3, address, area, souls, frequency, start_date, last_distribution, next_distribution, status, notes
- `distributions` — id, recipient_id (FK ON DELETE SET NULL), recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes
- `change_log` — עוקב אחרי שינויי סטטוס בלבד
- `settings` — key/value (password, backup_folder)

## כללים עסקיים קריטיים
- חד-פעמיים **לא מופיעים** ברשימה השבועית — רק בלשונית "חד פעמי"
- `calculate_next_dist(last_date, frequency)` → שבועי=+7, דו-שבועי=+14, חודשי=+30 (תמיד יום רביעי הקרוב)
- מחיקת מקבל עם היסטוריה → `ValueError` (שנה סטטוס במקום)
- גיבוי אוטומטי אחרי כל שמירה → `utils/backup.py:auto_backup()`
- RTL בכל הממשק: `setLayoutDirection(Qt.LayoutDirection.RightToLeft)`

## ייבוא Excel
`import_from_excel(path)` — מחפש גיליון בשם "מקבלים", מאתר שורת כותרת לפי "שם" בתא, ממפה עמודות אוטומטית.
הקובץ המקורי: `../מערכת חלוקה.xlsx` (קיים בתיקיית האב).

## נקודות חשובות לדיבאג
- `QCoreApplication.AA_EnableHighDpiScaling` הוסר ב-PyQt6 — אל תוסיף
- encoding: כל הקבצים UTF-8; הטרמינל מציג mojibake אבל הנתונים תקינים
- `openpyxl` מוציא warning על DrawingML — לא בעיה
- `_extra_ids: set` ב-`GroupUpdateTab` — שומר חד-פעמיים שנוספו ידנית מלשונית "חד פעמי"

## מה עוד חסר (backlog)
- [ ] ייבוא נתונים מהאקסל המקורי (הסבר בתוך האפליקציה)
- [ ] hash לסיסמא (כרגע plain text ב-settings)
- [ ] אפשרות לסנן מעקב חלוקות לפי תאריך
- [ ] ייצוא PDF (כרגע רק Excel + הדפסה ישירה)

## Recent updates
- Added `settings.py` as a dedicated tab for password and backup controls.
- `settings` now tracks `last_backup_at` in addition to password and backup folder.
- Weekly list status is persisted in the database.
- Weekly list fills and saves missing `next_distribution` values.
- Recipient import now reports conflicts and file quality details.

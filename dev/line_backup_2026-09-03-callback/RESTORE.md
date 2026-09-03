# שחזור — "מי שחוזר לצינתוק שומע את ההודעה" (גרסה 3.06, 3/9/2026 אחה"צ)

## למה נבנה מחדש
המנגנון הקודם (`campaign_message_to_play` בשורש, v2.88–v3.05) לא השמיע את ההודעה בפועל
(יומן `Log/LogFolderEnterExit`: החוזרים שהו 5–8 שנ' בכניסה ולחצו 1 — גם אחרי איפוס הזיכרון
ואחרי שינוי ל-`1h`). הוא גם התנגש עם השורה שהמנהל מנהל בעצמו. הוחלף כולו.

## מה השתנה בקו (ורק זה)
1. **שורש `ext.ini`** — הוסרה הרשומה של התוכנה מהשורה של המנהל (`0-ACTIVE,17-ACTIVE-1-1h,` ← `0-ACTIVE,`)
   והוסרה `campaign_message_to_play_file_by_template=yes`. נוספו 5 שורות פילטר מתועדות (f2 post/124):
   ```
   check_template_filter=17                 ; מיקום תבנית התוכנה (1430692) ברשימת התבניות
   check_template_filter_active_go_to=/78   ; מי שברשימה → שלוחה 78
   check_template_filter_blocked_enter=yes  ; כל השאר נכנסים לתפריט הראשי כרגיל
   check_template_filter_none_enter=yes
   check_template_filter_error_enter=yes
   ```
   עותקים: `root_ext.ini.orig` (לפני), `root_ext.ini.before-apply-*`, `root_ext.ini.after-apply-*`.
   `root_ext.ini.pre-v3.05` = המצב לפני שני התיקונים של היום (`0-ACTIVE,17-ACTIVE-1-6d,`).
2. **שלוחה חדשה `/78` "הודעת החלוקה (מנהל חלוקה)"** — `type=menu`, `digits=2`, `timeout=1`, `timeout_goto=/2`.
   `M0000.wav` = הודעת הצינתוק + הודעת הפתיחה של התפריט הראשי (עותק של `M0000.wav` מהשורש).
   20 תת-שלוחות `go_to_folder` (0, 03, 1, 10, 11, 12, 13, 198, 2, 3, 4, 5, 50, 500, 555, 6, 7, 77, 8, 9)
   שמחזירות כל מקש לשלוחה המקבילה בשורש — כך אין לולאה חזרה לפילטר.
3. שום דבר אחר לא נגע: לא `Did_Go_To.ini`, לא `ivr.ini`, לא התבניות, לא שלוחה 77.

## שחזור הקו (דקה)
```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe dev\callback_line.py restore
```
מחזיר את השורש ל-`root_ext.ini.orig` ומוחק את `/78` (לסל של ימות — ניתן לשחזור בממשק).
לחזרה למצב שלפני v3.05 (בלי שום רשומה של התוכנה בשורה): להדביק בממשק ימות את `root_ext.ini.pre-v3.05`
ולהוסיף לו את 5 שורות הפילטר אם רוצים לשמור את המנגנון החדש.
⚠ אם המנהל שינה בינתיים את השורש מהממשק — `callback_line.py show` מציג; לשחזר ידנית רק את השורות שלנו.

## שחזור התוכנה
- קוד: `git checkout pre-callback-78` (= גרסה 3.05) או revert של קומיט 3.06.
- EXE: Release **v3.05** מ-GitHub (JHGJHJCD/distribution-manager). אין שינוי במסד הנתונים;
  הגדרה חדשה יחידה: `yemot_callback_ready` (מטמון — אפשר להתעלם).

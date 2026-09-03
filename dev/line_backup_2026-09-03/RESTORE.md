# שחזור — "מי שחוזר לצינתוק שומע את ההודעה פעם אחת" (3/9/2026, גרסה 3.05)

## מה השתנה (ורק זה)
- **בקו — שורש `ext.ini` בלבד, שתי שורות:**
  - `campaign_message_to_play=0-ACTIVE,17-ACTIVE-1-6d,` ← `0-ACTIVE,17-ACTIVE-1-1h,` (הרשומה של
    התוכנה מתאפסת אחרי שעה במקום 6 ימים; הרשומה `0-ACTIVE` של המנהל לא נגעה).
  - נוספה `campaign_message_to_play_file_by_template=yes` — זיכרון "כבר שמע" בקובץ נפרד לכל
    קמפיין (`CampaignMessageAmountPlay-Template-17.ini`), כדי שהתוכנה תוכל למחוק רק את שלה.
  - העתק מדויק של הקובץ לפני השינוי: `root_ext.ini.orig`. אחרי: `root_ext.ini.new`.
- **בתוכנה (3.05):** `yemot.reset_callback_memory` — בכל שליחה (עם הודעה / קלאסי / בדיקה) התוכנה
  מוחקת את קובץ הזיכרון של התבנית שלה בשורש, כך שכל מי שברשימה שומע את ההודעה פעם אחת אחרי
  כל צינתוק. נקודת-שחזור בגיט: תג `pre-callback-fix` (= גרסה 3.04).

## שחזור הקו (דקה)
```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe dev\line_backup_2026-09-03\root_ext.py restore
```
(או בממשק ימות: שלוחה ראשית ← ext.ini ← להדביק את תוכן `root_ext.ini.orig`.)
⚠ אם המנהל שינה בינתיים את `campaign_message_to_play` בממשק — לשחזר רק את שתי השורות, לא את הקובץ כולו
(`root_ext.py show` מציג את המצב הנוכחי).

## שחזור התוכנה
- קוד: `git checkout pre-callback-fix` או revert של קומיט 3.05.
- EXE: Release **v3.04** מ-GitHub (JHGJHJCD/distribution-manager). אין שינוי במסד הנתונים/הגדרות.

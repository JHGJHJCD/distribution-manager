# פורמט יומני ימות — פירוט (נצפה חי 9/9/2026)

כל היומנים ב-`ivr2:/Log/` הם טקסט, **שורה לרשומה**, בפורמט:
```
key#value%key#value%key#value%…
```
`%` מפריד בין שדות, `#` מפריד מפתח מערך. מפענחים עם `parse_line` בסקריפט
(זהה ל-`call_history.parse_enter_exit`). הזמנים בשעון ישראל.

## משיכה מהשרת (דרך `utils.yemot`, קריאה בלבד)
- תוכן קובץ: `yemot._download("ivr2:/Log/<name>")` → bytes (קובץ חסר → מתחיל ב-`{` JSON).
- רשימת קבצים + גדלים + mtime: `yemot._call("GetIVR2Dir", {"path": "ivr2:/Log"})`.
- יומן כניסות-ניהול: `yemot._call("GetLoginLog", {...})` (Management API; מבנה ה-Entry
  — זמן/מספר/IP — טרם אומת חי, לממש ולהדפיס פעם אחת מה חוזר).

## LogRouting.ymgr — ניתובי שיחות
שדות: `Folder`, `Phone`, `Date` (DD/MM/YYYY), `Time` (HH:MM:SS), `HebrewDate`, `Module`.
דוגמה: `Folder#2%Phone#0534183616%Date#09/09/2026%Time#11:07:24%HebrewDate#…%Module#routing`.
טבלה נקייה: `read_log.py routing`.

## LogFolderEnterExit-YYYY-MM.ymgr — כניסה/יציאה לשלוחות
שורה לכל כניסה/יציאה משלוחה. שדות: `CallId`, `Phone`, `EnterDate`, `EnterTime`
(ולפעמים `ExitDate`/`ExitTime`, `Folder`). חודשי מ-2020. `call_history.py` לוקח את
**השורה הראשונה של כל CallId** = שיחה נכנסת אחת, ומצבר phone→שעה→כמות (שעות אופטימליות).

## LogApi.ymgr — קריאות API לשרתים חיצוניים (הגדול, ~4MB)
שדות ראשיים: `Folder`, `Phone`, `Date`, `Time`, `HebrewDate`, `EnterId`, `IdType`,
`ApiSend` (כתובת הבקשה שיצאה), `ApiAnswer` (תשובת השרת).
- **בתוך `ApiSend`/`ApiAnswer`** המפרידים שונים: `^` בין מפתח לערך, `*` בין זוגות. למשל
  `ApiSend#https://…/phone2.php?ApiCallId^…*ApiDID^0795378810*ApiRealDID^048691834*ApiPhone^…*ApiExtension^12*…`.
- `ApiDID`=המספר הפנימי של ימות (079…), `ApiRealDID`=המספר שחויג (04…), `ApiPhone`=המתקשר.
- **מלכודת `%25`:** אם ערך בתוך ה-URL מכיל `%` מקודד (`%25`), ה-split על `%` יוצר
  מפתחות-רפאים (`25Phone`, `25Date`, `25ApiAnswer`) בחלק מהשורות. הנתונים עדיין שם.
  בלוג הזה העדף `--raw` / `--grep`; הטבלה נקייה יותר ב-routing/folder.
- על הקו הזה יש **שתי** אינטגרציות API: `shmuelsh.ovh/kupa/phone2.php` על שלוחה **/12**
  (של גורם אחר — זיהוי דיבור/סליקה) ושרת המענה שלנו על **/76**. לסנן לפי `--folder 76`
  או `--grep pai-dev-s-api-link` כדי לראות רק את שלנו.

## עקרונות לסקריפט (כדי לא להציף את השיחה)
- לפענח שורה-שורה ולהדפיס רק מסונן / `--tail N` (ברירת מחדל 30). `--tail 0` = הכל (זהירות).
- מיון/סינון לפי זמן דרך `_dt` (בונה datetime מ-Date/EnterDate + Time/EnterTime).
- `--keys` מגלה אילו שדות יש בלוג לא-מוכר לפני שבונים סינון.
- תמיד קריאה בלבד — היומנים הם עדות, לא לכתוב אליהם.

## קשור
- קוד מפענח קיים: `utils/call_history.py` (LogFolderEnterExit → שעות אופטימליות).
- תוכנית "מצלמת אבטחה לקו" (מעקב שינויי-תצורה עם GetLoginLog + mtime): `LINE_WATCH_PLAN.md`.
- שינוי תצורת הקו (לא קריאה): `tzintuk-callback-server`, `yemot-line-howto`.

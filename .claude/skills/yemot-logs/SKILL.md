---
name: yemot-logs
description: >-
  קריאה קלה וחיפוש ביומני הקו של ימות המשיח ("קופה של צדקה הר יונה") — הלוגים
  המובנים שימות שומרת על הקו: LogApi (כל קריאות ה-API לשרתים חיצוניים),
  LogRouting (ניתובי שיחות), LogFolderEnterExit-YYYY-MM (כניסה/יציאה לכל שלוחה,
  חודשי מ-2020), LogEnterID/LogCreditCard ועוד, וגם GetLoginLog (מי נכנס לניהול).
  יש להשתמש בסקיל הזה בכל בקשה בסגנון "תקרא/תראה את הלוגים", "מה קרה בקו ב-",
  "מי התקשר", "לאיזו שלוחה ניתבו", "יומן ה-API", "מי נכנס לקו", "תחקיר תקלה בקו
  לפי זמן", "מי שינה משהו בקו ומתי", או כשצריך להבין התנהגות של הקו מהיומנים
  במקום לנחש. הלוגים ענקיים (LogApi ~4MB) — הסקיל נותן סקריפט שמוריד, מפענח
  (פורמט key#value%…), מסנן (טלפון/שלוחה/שעה/grep) ומציג טבלה קריאה, בלי להציף
  את השיחה. לשינוי תצורת הקו → tzintuk-callback-server / yemot-line-howto;
  למצב החי של הקו → yemot-line-state; למפת הפאנל → pitronai-panel-guide.
---

# קריאה קלה של יומני ימות

ימות שומרת יומנים טקסטואליים על הקו עצמו (`ivr2:/Log/`) + יומן כניסות-ניהול
(Management API). הם **נותנים "מי + מתי + מה" אמיתי** — לתחקיר תקלות, לראות מי
התקשר/לאן נותב, ולעקוב אחר קריאות ה-API. הבעיה: הם ענקיים (LogApi ~4MB) — אסור
לשפוך אותם לשיחה. הסקריפט פותר זאת: מוריד, מפענח שורה-שורה, מסנן, ומדפיס טבלה קטנה.

## הכלי — בפקודה אחת

```
PY="C:/Users/יהודה/AppData/Local/Programs/Python/Python312/python.exe"
$PY .claude/skills/yemot-logs/scripts/read_log.py list                 # אילו יומנים יש + גדלים
$PY .../read_log.py routing --tail 20                                  # 20 הניתובים האחרונים
$PY .../read_log.py folder 2026-09 --phone 0556752642                  # כניסות של מספר בחודש
$PY .../read_log.py api --since 13:00 --grep 048691834                 # קריאות API מהשעה
$PY .../read_log.py api --keys                                         # אילו שדות יש (פורמט לא-מוכר)
$PY .../read_log.py file ivr2:/Log/LogEnterID.ymgr --tail 10           # כל קובץ לוג
```
מסננים: `--tail N`/`--head N` · `--phone` · `--folder` · `--module` · `--since`
(`HH:MM` / `DD/MM/YYYY` / `"DD/MM HH:MM"`) · `--grep TEXT` · `--fields a,b,c` ·
`--raw` (שורה גולמית) · `--keys` (גילוי שדות). פירוט פורמט: `references/log-formats.md`.

## הלוגים הזמינים (נצפו 9/9/2026)

| קובץ / מקור | מה יש | הערה |
|------------|-------|------|
| `Log/LogApi.ymgr` | כל קריאה לשרת API חיצוני: `Folder,Phone,Date,Time,ApiSend(URL),ApiAnswer` | ~4MB, חי. יש כאן גם /12 של שרת אחר (`shmuelsh.ovh/kupa`) וגם /76 שלנו |
| `Log/LogRouting.ymgr` | ניתובי שיחות: `Folder,Phone,Date,Time,HebrewDate,Module` | |
| `Log/LogFolderEnterExit-YYYY-MM.ymgr` | שורה לכל כניסה/יציאה משלוחה: `CallId,Phone,EnterDate,EnterTime` | חודשי מ-2020; כבר מנוצל ב-`utils/call_history.py` |
| `Log/LogEnterID.ymgr`, `LogCreditCard*.ymgr` | זיהוי/סליקה | |
| `GetLoginLog` (Management API) | מי נכנס לניהול הקו ומתי = ה"מי שינה" | דרך `yemot._call("GetLoginLog", {...})`; מבנה טרם אומת חי |

## למה זה שימושי (דוגמאות אמת)
- **תחקיר תקלה לפי זמן** — "מה קרה ב-04 ב-12:25?" → `routing --since 12:20` + `api --since 12:20`.
- **מי שינה את השורש** — `GetLoginLog` + mtime של `ivr2:/ext.ini` (ראה `LINE_WATCH_PLAN.md`).
- **האם מתקשר-חזרה הגיע ל-/76** — `api --grep 048691834 --folder 76` / `folder --phone <num>`.
- **מי מחייג ומתי** (שעות אופטימליות) — `folder YYYY-MM` (זה בדיוק מה ש-`call_history.py` מצבר).

## מלכודות פורמט (ראה references/log-formats.md)
- כל שורה = `key#value%key#value%…` (‎`%` מפריד שדות, ‎`#` מפריד מפתח מערך).
- **LogApi**: בתוך `ApiSend`/`ApiAnswer` המפרידים הם `^` (מפתח-ערך) ו-`*` (בין זוגות);
  לפעמים `%` מקודד כ-`%25` ⇒ נוצרים מפתחות-רפאים כמו `25Phone` בחלק מהשורות.
  בלוג הזה העדף `--raw`/`--grep`; הטבלה נקייה יותר ב-routing/folder.
- הלוגים מתעדכנים **באיחור** (לא בזמן-אמת מלא) — הרבע-שעה האחרונה עלולה לא להופיע.
- קובץ חסר / נטפרי-חסום מחזיר JSON (`{…}`) במקום טקסט — הסקריפט מזהה ומחזיר "אין תוכן".
- הזמנים בשעון ישראל (כפי שהשרת כותב).

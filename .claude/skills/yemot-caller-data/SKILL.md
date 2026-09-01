---
name: yemot-caller-data
description: >-
  השמעת נתונים אישיים ואיסוף מידע מהמתקשר בימות המשיח (call2all) — שהמתקשר
  ישמע מידע אישי על עצמו לפי זיהוי ("יש לך חלוקה השבוע"), הקראת סטטוס אישי
  מקובץ נתונים (id_message / id_list_message / IdListMessage.ini), סקר טלפוני
  עם תוצאות בזמן אמת (seker / seker_questions), שהמתקשר גם יקליט וגם יקיש
  נתונים בשיחה אחת (recording_and_entering_data), תמלול מה שאמר — המרת דיבור
  לטקסט (stt_dir_all_file), חלוקת קופונים (coupon), מספרי אישור
  (approval_number), חלוקת קודים (codes), השמעת מספר המתקשר ודיווח משימות
  יומי. יש להשתמש בסקיל הזה בכל בקשה בסגנון "שהמתקשר ישמע מידע אישי", "להקריא
  לו את הסטטוס שלו", "סקר טלפוני", "קופון", "מספר אישור", "תמלול", או אזכור
  של אחד המודולים הנ"ל. ממשיך את yemot-enter-id: אחרי שהמתקשר זוהה — מה
  משמיעים לו ומה אוספים ממנו. נחקר מתיעוד הפורום הרשמי (f2.freeivr) ב-01/09/2026.
---

# נתונים אישיים ואיסוף מידע מהמתקשר

שני כיוונים משלימים, שניהם רוכבים על **זיהוי המתקשר** (enter_id — סקיל
`yemot-enter-id`): (א) **החוצה** — להשמיע למתקשר מידע אישי עליו מתוך קובץ
נתונים; (ב) **פנימה** — לאסוף ממנו הצבעה / הקלטה / הקשות / תמלול.
פירוט גולמי מלא + טבלת מקורות: `references/caller-data-details.md`.

## 1. השמעת נתונים אישיים — id_message מול id_list_message (post/50)

| | `id_message` | `id_list_message` |
|---|---|---|
| מה מושמע | קובץ שמע **אחד** למזוהה | **שרשרת** תכנים: קבצים, מספרים, TTS, תאריכים… |
| מקור הנתונים | קובץ WAV ששמו = מספר הזיהוי | שורה בקובץ `IdListMessage.ini` |
| מתאים ל | הודעה מוקלטת אישית | סטטוס שנבנה אוטומטית מ-DB (הכיוון שלנו) |

בשניהם **הכניסה עם זיהוי היא חובה** (טלפון / ת"ז / קוד — לפי `enter_id_type`).

### id_message — הפשוט
```ini
type=id_message
id_message_end_goto=1/1     ; אחרי השמעה מוצלחת
id_message_error_goto=/2/1  ; בשגיאה
```
זיהוי `0548594142` → מושמע `0548594142.wav` מהשלוחה. אין קובץ → הודעת
מערכת M1099 ("אין הודעה להשמעה").

### id_list_message — החזק (המרכזי לפרויקט)
```ini
type=id_list_message
id_list_message_file=/1                   ; מיקום הקובץ/קבצי-השמע (⚠ סמנטיקה מדויקת לא אומתה)
id_list_message_no_message_goto=/1        ; אין רשומה למתקשר → לאן
id_list_message_end_goto=/1               ; בסיום → לאן
id_list_message_date_say_month_number=yes
id_list_message_save_log=yes              ; לוג השמעות
play_and_return=play_all
```

**קובץ `IdListMessage.ini`** — שורה לכל מזוהה, פריטים מופרדים ב**נקודה**:
```
מספר_זיהוי=סוג-ערך.סוג-ערך.סוג-ערך
default=t-אין הודעות עבורך      ; מי שאין לו רשומה
```
דוגמה מהתיעוד: `0533137770=f-57750730.f-57881001.a-www012@.d-5567.n-5123`

**סוגי ההקראה** (קידומת-ערך):

| קידומת | דוגמה | מושמע |
|---|---|---|
| `f-` | `f-hello` | קובץ שמע (בלי סיומת, מהשלוחה הנוכחית אא"כ הוגדר אחרת) |
| `t-` | `t-שלום עולם` | טקסט חופשי ב-TTS |
| `n-` | `n-123` | מספר ("מאה עשרים ושלוש") |
| `d-` | `d-123` | ספרות ("אחת שתיים שלוש") |
| `a-` | `a-abc` | אותיות/תווים אחד-אחד |
| `m-` | `m-1001` | הודעת מערכת |
| `date-` / `dateH-` | `dateH-01/01/2019` | תאריך לועזי / מומר לעברי |
| `z-` | `z-sunset,IL/Jerusalem,-,m20,1` | זמני היום |
| `h-` | `h-music_name,5` | מוזיקה בהמתנה (עם הגבלת דקות) |
| `g-` | `g-/1/2/3` | ניתוב לשלוחה — חייב להיות **אחרון** בשרשרת |
| `s-` | `s-123` | ⚠ "Speech" — לא אומת מה ההבדל מ-t-/n- |

### עדכון הקובץ דרך ה-API (הדרך שלנו)
בונים את השורות בקוד ומעלים ב-`UploadTextFile` — **הדפוס המלא (קרא → ערוך →
כתוב + אימות) בסקיל `yemot-line-howto`**; דוגמה זהה עם ListAllInformation.ini
בסקיל `yemot-enter-id`:
```python
from utils import yemot
rows = "default=t-אין הודעות עבורך\n0501234567=t-משפחת כהן יש לכם חלוקה השבוע\n"
yemot._call("UploadTextFile", {"what": "ivr2:7/IdListMessage.ini",
                               "contents": rows}, post=True)
```

## 2. סקרים טלפוניים

### הישן — `type=seker` (post/100): שאלה אחת, תוצאות בזמן אמת
```ini
type=seker
key_ok_1=1                  ; ... אילו מקשים פתוחים להצבעה (key_ok_0..key_ok_9)
allow_unlisted_number=yes   ; גם חסויים, ואותו מספר יכול להצביע שוב
change_selection=yes        ; המצביע יכול לשנות את בחירתו
seker_end_goto=/1
seker_email_address=aaa@aaa.aaa
seker_email_name=אברהם
```
- אחרי הצבעה המתקשר שומע **תוצאות חיות**: כמה הצביעו + אחוזים לכל אפשרות.
- דוח למנהל: התפריט הטלפוני של הניהול → 1 → מספר השלוחה + `#` → (M2733)
  הקשה 1 שולחת את הדוח למייל. עמודות: `seker.ini` (סיכום: Folder, DID,
  Selekt0–9) ו-`seker_log.ini` (פירוט: Phone, Date, Selekt).

### החדש — `seker_questions` (post/13236): רב-שאלות + דוחות מסודרים
- כל שאלה = תיקייה ממוספרת עם `Q.wav`; `seker_questions_patch=1` מצביע על
  שלוחת השאלות; `seker_questions_numbers=1.2.8` = השאלות הפעילות (בנקודות).
- דוחות: `seker_questions_log.ymgr` כללי + `Q_log.ymgr` בתיקיית כל שאלה;
  פיצול לפי זמן: `seker_questions_log_file_type=day|month`.
- `say_results=all|percentage|amount|nothing` — מה מושמע למתקשר בסיום;
  `say_q_number=no` מבטל את "שאלה מספר X".
- `seker_questions_add_record_converted_to_text=yes` — המתקשר גם מקליט
  תשובה חופשית והיא **מתומללת** (תזמון ברירת מחדל `2-2-20`: שקט-מינ'-מקס').

## 3. הקלטות + נתונים בשיחה אחת — recording_and_entering_data (post/36372)

`type=recording_and_entering_data` — המתקשר עובר מסלול משולב: מקליט **וגם**
מקיש נתונים, והכל נרשם כרשומת-אישור אחת. קבצי ההנחיה בשלוחה: **000–049 =
שלבי הקלטה, 050–099 = שלבי הקשה**; ברירת מחדל מקליטים קודם
(`start_first=data` הופך). `recording_and_entering_data_folder_to_play=/8`
משמיע פרומפטים משלוחה אחרת.

נוצרים בשלוחה: `ApprovalAll.ymgr`/`.html` (רשומות ההשלמה) · תיקיית
`Record/` (ההקלטות) · `LogRecordingAndEnteringData.html` (לוג) ·
`ApprovalNumberNow.ini` (מונה האישורים). תומך ולידציה, מניעת כפילויות,
תקרת נרשמים (`booking_max`), אישורי SMS/מייל.

**בקו שלנו:** שלוחה 11 מכילה `;type=recording_and_entering_data` **מוער** —
לא פעיל; אם רוצים להפעיל שם, חסר type פעיל (ראו `yemot-line-knowledge`).

## 4. שאר המודולים — בקצרה

| מודול | type= | מה עושה | קבצים עיקריים | מקור |
|---|---|---|---|---|
| דיבור→טקסט | `stt_dir_all_file` | ממיר את כל קובצי השמע בתיקייה לטקסט (1=אישור); ממוין ל-OK/ERROR/NO_RESULT | `LogSttDirAllFile.html`; יעד: `stt_dir_all_file_dir=/5/8` | post/134 |
| קופונים | `coupon` | כל מזוהה מקבל קוד מרשימה; M1414 כשנגמרו | `coupon.ini` (`1001=erty`), `coupon_log.ini`; `coupon_start`/`coupon_max` | post/86 |
| מספרי אישור | ⚠`approval_number` | מספר אישור רץ למזוהה; מתאפס בחצות (`approval_number_type=always` = רציף) | `ApprovalNumberNow.ini`; `email_send=yes` | post/87 |
| חלוקת קודים | `codes` | קוד מוקש או **אקראי** (הגרלות); `codes_enter_id_max` לאדם | `Codes.ini` (קוד בשורה), `CodesTaken.ymgr`/`.html` | post/78103 |
| מספר המתקשר | `say_dialing_number` | מקריא למתקשר את מספרו; חסוי → M1080 | `say_dialing_number_end_goto`/`_error_goto` | post/67226 |
| דיווח משימות | `tasks_report` | משימות לפי טלפון; המתקשר מדווח ביצוע; דוח יומי במייל | `task_desc_status_phone.ini`, `WhiteList.ini`; `reporting_folder`, `date=hebrew` | post/63 |

## 5. זרימה שלמה לדוגמה: זיהוי → סטטוס אישי

שלוחה שבה מתקשר מקיש (או מזוהה לפי טלפון) ושומע את הסטטוס שלו:
```ini
; ext.ini של שלוחת "מה הסטטוס שלי"
type=id_list_message
enter_id=yes
enter_id_type=phone_from_list_all_information  ; זיהוי אוטומטי לפי המספר המתקשר
                                               ; (חלופה: phone_or_enter_phone — חסוי מקיש ידנית)
id_list_message_no_message_goto=/2             ; לא ברשימה → למענה האנושי
id_list_message_end_goto=/                     ; בסיום → לתפריט הראשי
```
ולצידה `IdListMessage.ini` (מועלה מהקוד, ראו סעיף 1):
```
default=t-לא נמצאה עבורך הודעה
0501234567=t-משפחת כהן.t-יש לכם חלוקה השבוע ביום רביעי
0529876543=t-משפחת לוי.m-1099
```
הגדרות הזיהוי המלאות (סוגי enter_id_type, קובץ ListAllInformation) — בסקיל
`yemot-enter-id`.

## 6. מלכודות

- **תווי-בקרה בטקסט TTS:** בתוך `t-` אסור נקודה (`.`) או מקף (`-`) — שוברים
  את פרסור השרשרת (post/50). שמות משפחה עם מקף ("כהן-לוי") — להחליף לרווח.
- **`g-` תמיד אחרון** — אי אפשר לשרשר פריטים אחרי ניתוב (post/50).
- **קידוד UTF-8** לכל קובצי הנתונים בעברית (כמו ListAllInformation.ini).
- **אפסים מובילים:** מספרי טלפון בצד שמאל של `=` חייבים לשמור את ה-0 — בבנייה
  מאקסל העמודה נמחקת (topic/18728, ראו yemot-enter-id); בבנייה מקוד — לוודא
  שהמספר מטופל כמחרוזת (`yemot.normalize_phone` כבר מחזיר מחרוזת עם 0).
- **כתיבה חלקית מוחקת את הקובץ:** UploadTextFile דורס את הקובץ כולו — תמיד
  לבנות את **כל** השורות ולהעלות הכל (דפוס קרא-ערוך-כתוב ב-yemot-line-howto).
- **זיהוי הוא שער:** בכל מודולי החלוקה (קופון/אישור/קודים) מתקשר לא-מזוהה
  מקבל M1015 ולא נכנס — לתכנן מה קורה לחסויים (`phone_or_enter_phone`).
- **⚠ כלום מזה לא נוסה עדיין על הקו האמיתי** — לפני מימוש: לבדוק על שלוחת
  ניסיון, ולאמת את הפרטים המסומנים ⚠ (סמנטיקת `id_list_message_file`, סוג
  `s-`, `type=approval_number`, תפקיד seker.ini המדויק).

## 7. קשר לפרויקט מנהל חלוקה — פוטנציאל (לא ממומש, 09/2026)

**הרעיון המרכזי:** מקבל מתקשר לקו ושומע אוטומטית אם יש לו חלוקה השבוע.
- מקור הנתונים: רשימת הזכאים השבועית של `group_update` (`_rows_data`, אותו
  מקור כמו הצינתוקים ב-`tabs/tzintukim.py`).
- האפליקציה תבנה `IdListMessage.ini` — שורה לכל טלפון של זכאי
  (`t-משפחת X יש לכם חלוקה השבוע` + `default=t-אין לך חלוקה השבוע`) — ותעלה
  ב-`UploadTextFile` בכל רענון רשימה (אותו דפוס כמו טעינת רשימת התבנית).
- שלוחה עם `phone_from_list_all_information` או זיהוי-טלפון → השמעה מיידית
  בלי הקשות. משלים את הצינתוק היוצא: מי שפספס את השיחה מתקשר ושומע לבד.
- **סקר אישור הגעה:** `seker` ("הקש 1 אם תגיע") כחלופה/גיבוי להקשת-7 של
  הקמפיינים; או `seker_questions` עם הקלטה מתומללת לסיבת אי-הגעה.
- **קופונים/אישורים:** מספר אישור לאיסוף בנקודת החלוקה (`approval_number`).
- לפני מימוש: לתאם שלוחה פנויה מול `yemot-line-state`, ולזכור ששלוחות
  10/12/13/555 שייכות למערכות חיצוניות (`yemot-line-knowledge`).

## סקילים קשורים

`yemot-enter-id` (הזיהוי שבשער כל המודולים כאן) · `yemot-line-howto` (עריכת
קבצים דרך ה-API) · `yemot-line-state` (מפת השלוחות הפנויות) ·
`yemot-line-knowledge` (מלכודות הקו, שלוחה 11) · `yemot-api-module`
(חלופה דינמית: שלוחת type=api ששואלת שרת בזמן אמת במקום קובץ סטטי) ·
`anthropic-skills:yemot-hamashiach` (הידע הכללי על ימות).

## עדכון הידע

כשמאמתים בשטח פרט המסומן ⚠, או מגלים הגדרה/מלכודת חדשה באחד המודולים —
לעדכן כאן וב-`references/caller-data-details.md` באותה הזדמנות. אם הפיצ'ר
ממומש באפליקציה — לעדכן גם את CLAUDE.md של הפרויקט ואת learned-solutions
של `anthropic-skills:yemot-hamashiach`.

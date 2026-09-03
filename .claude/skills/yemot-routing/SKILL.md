---
name: yemot-routing
description: >-
  ניתוב שיחות במערכת ימות המשיח (call2all) — כל הדרכים להעביר שיחה נכנסת למספר
  טלפון אמיתי או לשלוחה אחרת: מודול ראוטינג (routing), ראוטינג לפי שעות וימים
  (routing_time), תור למענה אנושי (queue / routing_queue), ניתוב לפי המספר שחויג
  או שחייג (DID / Did_Go_To.ini), העברה בין תיקיות לפי זמן (go_to_folder_time /
  go_to_folder_date), שיחת גישור דרך ה-API (CreateBridgeCall) ו-Click To Call.
  יש להשתמש בסקיל הזה בכל בקשה בסגנון "להעביר שיחות למספר", "מענה אנושי",
  "שעות מענה", "מחוץ לשעות הפעילות", "תור", "נציגים", "מוזיקה בהמתנה", "ניתוב
  לפי מספר מחייג/מחויג", "שיחה יוצאת מהקו", "גישור", "לחייג משני צדדים", או כל
  אזכור של routing / routing_time / queue / DID — כולל שינוי מספרי המענה של
  שלוחות 2 ו-3 בקו האמיתי (הבקשה הנפוצה ביותר). נחקר מהמקורות הרשמיים
  (f2.freeivr) ב-01/09/2026. פירוט מלא: references/routing-details.md.
---

# ניתוב שיחות בימות המשיח — ראוטינג, תורים, DID וגישור

כל טענה כאן — עם מקור מהפורום הרשמי (`post/NNN` או `topic/NNN` = f2.freeivr.co.il).
מה שלא נמצא במקורות מסומן ⚠ "טרם אומת". טבלאות מלאות: `references/routing-details.md`.

## 1. מפת המודולים — במה להשתמש מתי

| צריך | מודול | עלות יחידות | מקור |
|---|---|---|---|
| להעביר כל שיחה למספר טלפון (מענה אנושי פשוט) | `type=routing` | לפי דקות (נמדד בשניות) | post/734, topic/218 |
| מענה רק בשעות/ימים מסוימים, אחרת הודעה/שלוחה | `type=routing_time` | לפי דקות | post/735 |
| העברה למערכת ימות אחרת (קו לקו) | `type=routing_yemot` | **ללא עלות** | topic/218 |
| תור עם כמה נציגים, מוזיקה בהמתנה, מיקום בתור | `type=queue` (ישן) / `type=routing_queue` (חדש) | routing_queue: ללא עלות ליעדים בישראל (ניסיוני, "עד להודעה חדשה") | post/60096, post/168201, topic/19229 |
| כניסה לשלוחה שונה לפי המספר שחויג (DID) | `check_did_and_go_to_folder` + `Did_Go_To.ini` | — | post/60 |
| מעבר בין **תיקיות** (לא לטלפון) לפי שעות/ימים | `type=go_to_folder_time` | — | post/56 |
| מעבר לתיקייה ששמה נגזר מהתאריך/שעה (גם עברי) | `type=go_to_folder_date` | — | post/57 |
| לחבר שני טלפונים חיצוניים דרך הקו (מהמחשב) | API `CreateBridgeCall` | 0.1 להפעלה + דקות שני הצדדים | post/72304 |
| לחייג מהדפדפן (תוסף כרום) | Click To Call | 0.1 הפעלה + דקות | post/99426 |

כלל אצבע: מספר יעד **אחד** → routing. שעות פעילות → routing_time. כמה נציגים
במקביל/בתור → routing_queue. בלי טלפון בכלל (רק מעבר שלוחות) → go_to_folder_time.

## 2. מודול routing (post/734)

```ini
type=routing
routing_to_phone=0501234567
```

| מפתח | תפקיד | ברירת מחדל |
|---|---|---|
| `routing_to_phone` | מספר היעד; או `by_incoming_did` (ניתוב לפי המספר שחויג, דורש קובץ `RoutingIncomingDID.ini` בשלוחה — שורות `DID=יעד`) | — |
| `routing1=`, `routing2=`… + `digits=2` | תפריט: המתקשר מקיש 1/2… ומנותב | — |
| `routing_multiple=yes` + `routing_multiple_numbers=1,3` | מחייג לכמה מספרים **ביחד** (מתוך routing1/2/3…) | לא |
| `routing_count=yes` + `routing_count_1=5` | לפי סדר עם תקרת שיחות בו-זמנית לכל נציג | לא |
| `routing_any_phone=yes` | מנתב לכל מספר שהמתקשר יקיש | לא |
| `routing_end_time=20` | כמה שניות מחכים לפני ויתור | ⚠ ברירת מחדל לא מתועדת |
| `routing_end_goto=/8` | לאן עוברים בסיום/כישלון הניתוב ("מעבר בסיום") | נשאר בשלוחה |
| `routing_your_id=did` | זיהוי יוצא = מספר המערכת; `special.05XXXXXXXX` = מספר מאושר אחר | מספר **המחייג** |
| `music_on_hold=ztomao` | מוזיקה בזמן ההמתנה לחיבור | צליל חיוג רגיל |
| `routing_record=no` | ביטול הקלטת השיחה | **מקליט** |
| `routing_email_send=yes` + `routing_email_address=` | שליחת ההקלטה למייל | לא |
| `call_no_answer=yes` | לא "עונה" למתקשר עד שהיעד ענה (חוסך יחידות על צלצול) | לא |
| `routing_answer_play=yes` | השמעת הודעה לנציג לפני חיבור | לא |
| `routing_answer_tfr=yes` | תפריט לנציג: קבל/דחה את השיחה | לא |

⚠ תפוס/אין-מענה: אין מפתח `routing_no_answer` מתועד — ההתנהגות המתועדת היא
`routing_end_time` (תום המתנה) ואז `routing_end_goto`. פירוט על תפוס אצל נציגים
(בדיקה כל ~3 שניות) קיים רק בהקשר תור (topic/21077, topic/6076).

## 3. מודול routing_time (post/735) — שעות מענה

```ini
type=routing_time
routing_time_1=0509111111.09:00-17:00.mon-fri.1-20.jun
routing_time_2=0721234567          ; בלי תנאים = תמיד זמין
close_time_goto=/2                 ; אין נציג זמין → לכאן
```

**הפורמט (מופרד בנקודות, `*` = בלי הגבלה):**
`routing_time_X=טלפון.שעות.ימים-בשבוע.ימים-בחודש.חודשים`
- שעות: `09:00-17:00` · ימים: `sun,mon,tue,wed,thu,fri,sat` (טווח: `mon-fri`)
- ימים בחודש: `1-20` · חודשים: `jan…dec`
- כמה נציגים (`routing_time_1/2/3…`) — מי שחלון-הזמן שלו פעיל מקבל את השיחה.
- אין אף נציג זמין: הודעת מערכת M1041 ("המענה סגור כעת…") ואז `close_time_goto`.
- מפתחות משותפים עם routing: `routing_end_time`, `routing_your_id`,
  `music_on_hold`; ביטול הקלטה כאן: `routing_time_record=no`.
- ⚠ הימים/חודשים **לועזיים**; לשעות לפי לוח עברי (ערבי-שבת וכו') אין תמיכה
  מתועדת במודול הזה — עוקפים עם `go_to_folder_date` (קודי תאריך עברי S/C/Y).

## 4. תור — queue (post/60096) ו-routing_queue (post/168201)

שני קבצים בשלוחה: `ext.ini` (הפעלה ומה-קורה-בסיום) + `queue.ini` (נציגים והתור).
`routing_queue` = הדור החדש, אותן הגדרות בטכנולוגיה שונה, **מומלץ לחדש** —
וכרגע בלי עלות יחידות ליעדים בישראל (topic/19229). מגבלה: עד **40 נציגים**.

```ini
;--- ext.ini ---
type=routing_queue                 ; או type=queue (ישן)
queue_timeout=600                  ; מקס' המתנה בתור (שנ'), ואז:
queue_end_timeout_goto=/5/8
queue_caller_id=customer_did       ; מה רואה הנציג: customer_did / real_did / מספר קבוע
queue_end_continue_goto=/2         ; אחרי שיחה שהסתיימה בהצלחה
queue_not_active_goto=/1           ; כשהתור סגור (queueactive=0)
queue_exit=/5/8                    ; הקשת 9 בתור = יציאה לשלוחה

;--- queue.ini ---
queueactive=1                      ; 0 = סגור (הודעה M3790)
strategy=ringall                   ; ringall / linear / roundrobin / fewestcalls
maxlen=3                           ; מקס' ממתינים; מעבר לזה → queue_end_full_goto
announce-position=yes              ; הכרזת מיקום בתור
announce-frequency=60              ; כל כמה שניות מכריזים
announce-holdtime=yes              ; הערכת זמן המתנה
musicclass=default                 ; מוזיקה בהמתנה בתור
timeout=23                         ; שניות צלצול לנציג
wrapuptime=15                      ; מנוחה לנציג בין שיחות (שנ')
retry=5                            ; המתנה לפני סבב חיוג חוזר
0501111111                         ; הנציגים — שורה למספר (גם SIP-XXX-N)
0502222222
```

עוד ב-references: התקשרות-חוזרת (`queue_call_back=yes`), דירוג שיחה
(`queue_call_rating=yes`), מיילים ודוחות (`LogQueueAll.ymgr`), `queue_url_link`
(משיכת הגדרות/נציגים מ-API חיצוני), הודעות M2780/M2782/M2783/M3790, ובאגים
ידועים של routing_queue (מיילים ריקים, זיהוי קבוע).

## 5. ניתוב לפי DID — check_did_and_go_to_folder (post/60)

בשלוחה **הראשית** (`/`):

```ini
check_did_and_go_to_folder=yes
```

וקובץ `Did_Go_To.ini` בשורש — שורה לכל מספר: `0773137770=/1`.

- לפי **מחייג**: להוסיף `did_directed_check=yes`; פורמט
  `0527666666-Directed-0773137770=/5` (המחייג-Directed-המחויג=שלוחה).
- מחייג **וגם** מחויג: `did_and_phone_check=yes`; פורמט `0501234567-0773137770=/1`.
- `check_did_and_go_to_folder_one_time=yes` = הניתוב חל רק בכניסה הראשונה לשלוחה.
- יומן ניסיונות: `Log/LogDidDirectedCheck.ini`.
- **נלמד חי 3/9/2026:** כל שורה ב-`Log/LogFolderEnterExit-YYYY-MM.ymgr` נושאת `IncomingDID#<המספר שחויג>` ⇒ מעקב "מי חזר לצינתוק" לפי DID ייעודי הוא מדויק ובלי פילטרים. `RunTzintuk`/`RunCampaign` מקבלים DID משני כ-`callerId` ⇒ **DID ייעודי + שורה ב-`Did_Go_To.ini` הוא התחליף הבטוח ל-`check_template_filter`** (שמספרו = אינדקס 0-based ב-GetTemplates ונשבר במחיקת תבנית). בקו: `0773019787` (→/50) רדום מאז אוגוסט — מועמד; הכרעה אצל המשתמש.
- **בקו האמיתי:** ל-DID משני יש שורת `<המספר>=/555` ב-Did_Go_To.ini ש**גוברת**
  על `usage=goto:/2` שרשום ב-secondary_dids של אותו מספר (המספר עצמו —
  ב-yemot-line-state; ראו yemot-line-knowledge — אל תשחרר את המספר בלי לעדכן
  גם את `tzintuk_your_id`).

## 6. מעבר תיקיות לפי זמן — בלי טלפון

**`type=go_to_folder_time`** (post/56): `go_to_folder_time_X=תיקייה.שעות.ימים.ימים-בחודש.חודשים`
(אותו פורמט זמנים כמו routing_time; `*` = הכל). אין התאמה → הודעה M1962 ואז
`go_to_folder_time_error_goto=/3`.

**`type=go_to_folder_date`** (post/57): `go_to_folder_date=` + קודי אות (רגישי-רישיות!)
שמרכיבים את **שם** תיקיית היעד: `y/m/d` לועזי · `S/C/Y` שנה/חודש/יום **עבריים** ·
`h/M/s` שעה/דקות/שניות · `U` יום-בשבוע (1=ראשון…7=שבת). למשל `go_to_folder_date=h`
→ שלוחה לפי השעה (0–23). שגיאה → `go_to_folder_date_error_goto=/5/8`.

## 7. שיחה יוצאת מהמחשב — CreateBridgeCall ו-Click To Call

**`CreateBridgeCall`** (post/72304) — ה-API מחייג ל-`Phones`, וכשעונים מגשר אל
`BridgePhones`. פרמטרים: `token`, `callerId` (ברירת מחדל = מספר המערכת),
`Phones`, `BridgePhones`, `RecordCall=0/1`, `SendMailInCall=0/1`,
`SendMailInCallTo`, ולחיוג דרך SIP: `DialSip`, `DialSipExtension`,
`AccountNumber`, `SipExtension`. עלות: 0.1 יחידה להפעלה + דקות השיחה של שני
הצדדים (זמן החיוג של הצד השני לא נספר). תשובה: `CampaignId`, `callsCount`,
`bilingPerCall`, `biling`. אצלנו: לקרוא דרך `yemot._call("CreateBridgeCall", …)`.
⚠ טרם אומת בשטח על הקו שלנו.

**Click To Call** (post/99426) — תוסף כרום רשמי; מתחבר עם **API Key** בלבד
(מגרסה 1.4.1, לא מספר+סיסמה). עלות: 0.1 הפעלה + דקות לשני הכיוונים (צד המפעיל
חינם אם הוא חשבון SIP). המפתח נשמר בדפדפן — ביטול ה-API Key מנטרל את התוסף.

## 8. מלכודות

- **עלות יחידות:** routing / routing_time עולים **לפי דקות** על השיחה היוצאת
  (topic/218). ללא עלות: `routing_yemot` (קו-לקו) ו-`routing_queue` (זמנית,
  ישראל בלבד). לפני שממליצים על מסלול — לבדוק יתרה (`GetSession`).
- **זיהוי יוצא:** ברירת המחדל מציגה לנציג את **מספר המתקשר** — טוב למענה אנושי.
  `routing_your_id=did` מציג את מספר הקו (הנציג לא יודע מי חייג); `special.` רק
  למספר שאושר במערכת (post/734).
- **הקלטה כברירת מחדל:** routing מקליט כל שיחה אלא אם `routing_record=no` —
  לזכור פרטיות ומקום אחסון.
- **`type=` אחד בלבד** פעיל בכל ext.ini (הראשון) — אי אפשר routing וגם תפריט
  באותה שלוחה; מפצלים לשתי שלוחות (ראו `;; ***DUP***` ב-yemot-line-knowledge).
- **שלוחה 3 מול 03 בקו האמיתי:** `3` = routing_time פעיל; `03` = עותק ישן שכולו
  מוער (`;`) — לא פעיל. לערוך רק את `3`; אל תסיק מ-03 כלום על ההתנהגות.
- **routing_queue ניסיוני:** מיילים על שיחות יוצאים ריקים, והיו דיווחים על
  זיהוי-קבוע ועל ניתוב-אחרי-ניתוק שלא כובד (topic/19229) — לתרחיש קריטי לבדוק
  מול queue הישן.
- ⚠ לא נמצאה תשובה מתועדת: מה משמיעים לממתין כשהיעד ב-routing רגיל **תפוס**
  (בפורום הוזכר צליל תפוס בזמן המתנה, topic/21077 — טרם אומת).

## 9. הקו האמיתי (קופה של צדקה הר יונה)

- **שלוחה `2`** — `type=routing`, `routing_to_phone=<המספר בפועל>` = **המענה
  האנושי הראשי**. הכניסה לקו מגיעה לכאן (`go_to_folder=/2` בשורש).
- **שלוחה `3`** — `type=routing_time` → מספר נוסף, א׳–ה׳ 09:00–12:00; מחוץ
  לשעות → `close_time_goto=/4` (הקלטה).
- המספרים האמיתיים לא נשמרים כאן (הקובץ ב-git ציבורי) — הם ב-**yemot-line-state**
  (`STATE.md`, מוחרג מ-git).
- **שינוי המספרים האלה = הבקשה הנפוצה ביותר.** את העריכה בפועל (GetTextFile →
  עריכה → UploadTextFile, גיבוי לפני) מבצעים לפי סקיל **yemot-line-howto**;
  את המצב העדכני בודקים קודם ב-**yemot-line-state** (`STATE.md`).
- ניתוב DID: DID משני → `/555` — ראו סעיף 5 ו-yemot-line-knowledge לפני כל נגיעה.

## סקילים קשורים

- `yemot-line-state` — צילום המצב החי של הקו (לרוץ `refresh_state.py` אחרי שינוי).
- `yemot-line-howto` — איך עורכים ext.ini דרך ה-API בפועל.
- `yemot-line-knowledge` — למה הקו בנוי כך ומה מסוכן לגעת בו.
- `anthropic-skills:yemot-hamashiach` — הידע הכללי על ימות (ענן, לא לעריכה מקומית).

## עדכון הידע

כשמגלים מפתח/התנהגות חדשים בתחום הניתוב (במיוחד: ברירת המחדל של
`routing_end_time`, התנהגות תפוס ב-routing, סוף תקופת-החינם של routing_queue) —
לעדכן כאן ואת `references/routing-details.md`, עם מקור post/NNN. שינוי בניתוב
של הקו האמיתי → לעדכן גם את yemot-line-knowledge ולהריץ refresh_state.

## ⚠ נלמד חי בקו (3/9/2026) — ריפוד ספרות בתפריט ו-`ExtensionNumbersAndAssociations.ini`
- בתפריט עם `digits=2`, הקשה של **ספרה בודדת** מגיעה לימות כשתי ספרות מרופדות באפס: "3" → **"03"**.
  בשורש של הקו זה עובד כי קיים `ExtensionNumbersAndAssociations.ini` (`00=0`, `01=1` … `09=9`) יחד עם
  `text_extensions=yes`, שממפה "03" חזרה לשלוחה `3`.
- **שיבוט תפריט (תיקייה חדשה עם אותם מקשים) חייב להעתיק גם את הקובץ הזה**, אחרת: "03" נופל לתיקייה
  בשם `03` אם קיימת (בקו שלנו — `go_to_folder_time` ריק ⇒ "ההגדרות לא הושלמו"), ו-"01"/"02"/"04" שלא
  קיימות ⇒ M1000 "אנא הקישו את מספר השלוחה" ⇒ `timeout` ⇒ `timeout_goto`.
- אומת ביומן `Log/LogFolderEnterExit`: כניסות ל-`78/menu/03` → `03` אחרי הקשת 3 בשיבוט שבנינו בשלוחה 78.
- הודעות ברירת-מחדל של תפריט לזיהוי בטלפון: M1000 = "זהו תפריט בחירה. אנא הקישו את מספר השלוחה המבוקש",
  M1001 = "המקש שהוקש שגוי". "שיחתכם מועברת" = כניסה ל-`type=routing`.

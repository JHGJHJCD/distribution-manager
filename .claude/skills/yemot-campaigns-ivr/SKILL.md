---
name: yemot-campaigns-ivr
description: >-
  ניהול קמפיינים, רשימות תפוצה וצינתוקים **מתוך ה-IVR עצמו** (מהטלפון) בימות
  המשיח — שלוחות הצטרפות והסרה עצמית ("שהמאזינים יצטרפו לרשימה", "להסיר את
  עצמי"), שלוחת ניהול למנהל (הוספת/הסרת מספרים אחרים, הקלטה ושיגור הודעה
  מהטלפון), הפעלה מהירה של קמפיין, הזמנת חבר, שמיעת כמות חברים, השמעת הודעות
  קמפיין למי שמתקשר לקו (campaign_message_to_play — "מי ששומע את ההודעה"),
  פילטרים לפי חברות ברשימה ("רק חברי הרשימה ייכנסו לשלוחה"), רשימות צינתוק
  חינמיות (admins/members), צינתוק אוטומטי בכניסה לשלוחה, ובדיקת יתרת יחידות
  מהטלפון. יש להשתמש בסקיל בכל בקשה בסגנון "שלוחת הצטרפות", "לשגר הודעה
  מהטלפון", "רשימת תפוצה מהקו", "צינתוק בכניסה", "יתרת יחידות מהטלפון", או
  אזכור של template_add_number / yemot_dialer / tzintuk / campaign_message_to_play.
  ה-API החיצוני של קמפיינים (RunCampaign, תבניות, ScheduleCampaign) מתועד בסקיל
  anthropic-skills:yemot-hamashiach — לא כאן. נחקר מהפורום הרשמי f2.freeivr
  ב-01/09/2026. פירוט מלא: references/campaigns-ivr-details.md.
---

# קמפיינים ורשימות תפוצה מתוך ה-IVR (מהטלפון)

כל מה שמתקשר או מנהל יכול לעשות עם קמפיינים ורשימות **בהקשה מהטלפון**, בלי
מחשב: להצטרף/להסיר את עצמו, לנהל רשימות, להקליט ולשגר, ולשמוע הודעות קמפיין.
מקורות: הפורום הרשמי f2.freeivr.co.il (נשלפו 01/09/2026); טענה לא-מאומתת → ⚠.
פירוט הגדרות מלא לכל מודול: `references/campaigns-ivr-details.md`.

## שני סוגי רשימות — לא להתבלבל

| | רשימות תפוצה (templates) | רשימות צינתוק (tzintuk lists) |
|---|---|---|
| מזוהות לפי | מספר תבנית (1, 2… / templateId ב-API) | **שם** (`admins`, `members`…) |
| משמשות ל | קמפיינים קוליים (עלות יחידות) | צינתוק קבוצתי **ללא עלות** |
| מודולי טלפון | `template_add_number` / `template_remove_number` / `yemot_dialer_campaign_list` | `type=tzintuk` (± `tzintuk_admin=yes`) |
| פילטר כניסה | `template_filter` / `check_template_filter` | `go_to_from_tzintuk` / `check_list_tzintuk` |

בקו שלנו יש **גם וגם**: תבנית 1430692 (האפליקציה) ותבניות הצוות = templates;
`admins`/`members` = רשימות tzintuk (שלוחות 5 ו-555).

## מפת דרכים — צורך ← מודול

| צורך | מודול / הגדרה | מקור |
|---|---|---|
| מאזין מצרף את עצמו לרשימה | `type=template_add_number` | post/78 |
| מאזין מסיר את עצמו | `type=template_remove_number` | post/68258 |
| מנהל מוסיף/מסיר/חוסם מספרים אחרים | `type=yemot_dialer_campaign_list` | post/79 |
| הזמנת חבר להצטרף (המערכת מחייגת אליו) | `type=invitation_join_campaign` | post/69219 |
| שמיעת כמות חברים בקבוצה | `type=check_template_numbers` | post/4000 |
| שיגור קמפיין בכניסה לשלוחה ("הפעלה מהירה") | `type=yemot_dialer_campaign_start` | post/65 |
| ניהול קמפיין מלא מהטלפון (הקלטה+שיגור) | `type=yemot_dialer` / `type=admin_login` | post/26188, topic/42 |
| קמפיין בהקראת טקסט (TTS) | בממשק האתר, לא ב-ext.ini | post/130 |
| השמעת הודעת הקמפיין למי שמתקשר לקו | `campaign_message_to_play` | post/62038 |
| רק חברי רשימת תפוצה ייכנסו / ניתוב לפי חברות | `template_filter` / `check_template_filter` | post/61, post/124 |
| ניתוב לפי רשימת צינתוקים (admins/members) | `go_to_from_tzintuk` / `check_list_tzintuk` | post/41323 |
| רשימת צינתוק חינמית + שלוחת הרשמה/ניהול | `type=tzintuk` + `list_tzintuk=שם` | topic/91 |
| צינתוק אוטומטי למתקשר בכניסה לשלוחה | `send_tzintuk=yes` | post/89969 |
| יתרת יחידות מהטלפון + התראות | `type=checking_unit` / `checking_units_ext=yes` | post/136, post/18757 |

## הצטרפות והסרה עצמית (post/78, post/68258)

```ini
; שלוחת הצטרפות
type=template_add_number
template_to_add=2              ; או 5,6,10,2 או all; בלי — רשימת ברירת המחדל
template_add_ask=yes           ; לבקש אישור לפני ההוספה
end_goto=/8

; שלוחת הסרה
type=template_remove_number
template_to_remove=2           ; או all
template_remove_no_ask=yes     ; בלי שאלת אימות
```

**המלכודת המרכזית:** הסרה כברירת מחדל **חוסמת** ולא מוחקת — המספר נשאר ברשימה
כ"חסום" וגם נחסם ברמת המערכת מקבלת הודעות עתידיות. מחיקה אמיתית:
`remove_and_delete=yes`. (המקבילה ברשימות tzintuk: `tzintuk_block_instead_of_remove=yes`
הופכת בכוונה הסרה לחסימה — כמו בקו שלנו ב-555/5/members.)

## ניהול ע"י מנהל מהטלפון (post/79)

```ini
type=yemot_dialer_campaign_list
yemot_dialer_campaign_list_template=1,5,2       ; או all
yemot_dialer_campaign_list_type=add_remove_block ; add / add_numbers / reset / info
```
דורש סיסמה כברירת מחדל (`yemot_dialer_campaign_list_no_password=yes` מבטל —
לא מומלץ). כל פעולה נרשמת ב-`Log/LogYemotDialerCampaignList.ymgr`.

## שיגור קמפיין מהטלפון (post/65)

```ini
type=yemot_dialer_campaign_start
template_to_start=2            ; בלי — תבנית ברירת המחדל
campaign_ask_before_start=no   ; שיגור מיידי בלי אישור
campaign_run_tzintuk=yes       ; מצב צינתוק — 0.1 יחידה למספר
campaign_run_tzintuk_timeout=5 ; משך צלצול, עד 10 שניות
```
משגר את התבנית עם ההקלטה והרשימה **השמורות בה**. ⚠ שלוחה כזו בידי מאזינים =
כל אחד משגר; לנעול בסיסמה או בפילטר. בקו שלנו: `9/44` בנוי בדיוק כך
(`template_to_start=1`), מאחורי סיסמת שלוחה 9.

הקלטת ההודעה עצמה — בשלוחת ניהול (`type=yemot_dialer` עם `admin_login_template=N`,
או `type=admin_login`; post/26188 + topic/42), או במסלול record + `folder_move`
כמו 9/2 בקו. שכפול אוטומטי של כל הקלטת-קמפיין לשלוחת השמעה:
`admin_login_campaign_message_template_default_copy=/N` (מופעל בקו בשלוחה 0).
⚠ מפת המקשים המלאה בתוך שלוחות הניהול אינה מתועדת בפורום — רק מקשים 0/3/6
של admin_login (שיחות/שידור/הרשאות).

## השמעת הודעות קמפיין למתקשרים — `campaign_message_to_play` (post/62038)

ההגדרה ששולחת "מי שמתקשר לקו ישמע את ההודעה של הקמפיין" (ההתקשרות-חוזרת של
האפליקציה עובדת דרכה). פורמט: `מספר-קהל-כמות-איפוס`, מופרד מקפים:

```ini
play_campaign_message=yes
campaign_message_to_play=17-ACTIVE-1-6d   ; קמפיין 17, רק לרשומים, פעם אחת, איפוס אחרי 6 ימים
```
- קהל: `ACTIVE` (ברשימה) / `BLOCKED` / `NONE` (לא ברשימה) / `ERROR`; ריק = כולם.
- איפוס: `thiscall` / `s`/`m`/`h`/`d`/`M` / תאריך / `none`.
- דילוג על ערך = ריק בין המקפים (`2--2`), לא מקף נוסף (post/63431).
- כמה קמפיינים בפסיקים = מושמעים בסדר; `stop_campaign_message=hash` = דילוג רק ב-#.
- ⚠ המספר הראשון: הפוסט אומר "מספר הקמפיין", ניסיון-השטח בקו שלנו הראה שזה
  **המיקום ברשימת התבניות** (17=1430692). **מלכודת קריטית — עריכת השורה מאפסת
  את זיכרון "כבר הושמע" של כל הרשומות בה**: תקרית "הודעות מאייר" והכללים
  המלאים ב-yemot-line-knowledge (אין לשכפל לכאן — לקרוא שם לפני כל עריכה).

## פילטרים — מי נכנס לשלוחה (post/61, post/124, post/41323)

```ini
; לפי רשימת תפוצה — משובץ בכל מודול
check_template_filter=1
check_template_filter_none_go_to=/3      ; לא ברשימה → החוצה
check_template_filter_blocked_go_to=/2

; לפי רשימת צינתוקים (שמות!) — משובץ בכל מודול
go_to_from_tzintuk=yes
check_list_tzintuk=members,admins        ; נבדק בסדר, עוצר בהתאמה ראשונה
go_to_from_tzintuk_not_found=/9
```
סטטוסים: found / blocked / invited / not_found; ניתוב פר-רשימה
(`check_template_filter_3_active_go_to`, `go_to_from_tzintuk_1_found`). קיימת גם
שלוחת ניתוב ייעודית `type=template_filter`. ברירת מחדל כשאין ניתוב: active נשאר,
none חוזר רמה אחת.

## רשימות צינתוק חינמיות (topic/91)

```ini
; שלוחת הרשמה למאזינים (מזוהים, מספר ישראלי בלבד)
type=tzintuk
list_tzintuk=members                     ; השם קבוע — לא ניתן לשינוי אחרי יצירה
tzintuk_block_instead_of_remove=yes      ; "הסרה" = חסימה (שלא יצטרפו שוב)

; שלוחת ניהול למנהל: שיגור צינתוק, מחיקה, איפוס, ספירה, הזמנות
type=tzintuk
list_tzintuk=members
tzintuk_admin=yes
```
`tzintuk_timeout=9` (עד 10 שנ') · `tzintuk_your_id=מספר` = הזיהוי שמוצג לנמענים
(בקו: מוגדר בשורש על DID משני — תלות קריטית, ראו yemot-line-knowledge) ·
`tzintuk_type=removing_to_list` = שלוחת הסרה-בלבד · שמות למספרים: `PhonesName.ini`.

צינתוק בודד למתקשר עצמו בכניסה לשלוחה (post/89969): `send_tzintuk=yes`
(+ `send_tzintuk_from=זיהוי-מאומת`); פעם אחת לשלוחה בשיחה; כרגע ללא עלות.

## יתרת יחידות מהטלפון (post/136, post/18757)

```ini
; שלוחה ייעודית
type=checking_unit
checking_units_amount_units_to_warning=50   ; ברירת מחדל 100
checking_units_play_status_units=yes        ; להקריא את היתרה תמיד

; התראה אוטומטית (רצה פעם בשיחה, מתריעה פעם ביום)
checking_units_ext=yes
checking_units_send_call=yes
checking_units_send_call_to=05XXXXXXXX      ; שיחת התראה ללא עלות
checking_units_mail=aaa@ccc.com
```

## מלכודות (מהמקורות)

- **הסרה מרשימת תפוצה = חסימה כברירת מחדל** (וגם חסימה כלל-מערכתית מהודעות) —
  רק `remove_and_delete=yes` מוחק. אל תבטיח למשתמש "נמחק" בלי זה.
- **שלוחות שיגור/ניהול פתוחות = כל מאזין משגר קמפיין** — תמיד `password=` או פילטר.
- **`campaign_message_to_play`: עריכה מאפסת זיכרון השמעה** — תקרית אמיתית בקו;
  הכללים ב-yemot-line-knowledge.
- **`list_tzintuk`: שם הרשימה קבוע לנצח** — לבחור נכון מראש.
- **TTS לקמפיין דורש שאין קובץ שמע בקמפיין** (השמע גובר); הקול נעול על
  `Elik_2100` — שינוי דרך ivr.ini דווח ככושל (post/130).
- **`invitation_join_campaign`: ההקלטה `invitationMessage` חייבת להיות קצרה
  מ-6 שניות**, והמוזמן יכול להקיש 3 ולחסום את המערכת מהזמנות עתידיות.
- **פילטרים עוצרים בהתאמה ראשונה** כשבודקים כמה רשימות — סדר הרשימות קובע.
- ⚠ `add_admin_to_list=yes` (בקו ב-555: הנכנס בסיסמה מתווסף ל-admins) — לא
  נמצא בתיעוד הפורום; מתועד מהתנהגות הקו בלבד.

## הקשר לקו האמיתי (קופה של צדקה הר יונה)

- **שלוחה 5** — הצטרפות/הסרה עצמית לרשימת ה-tzintuk‏ `members` (1=הוסף, 2=הסר).
- **שלוחה 555** — ניהול המתרימים (מוגנת סיסמה — ב-yemot-line-state; `add_admin_to_list=yes`): הקלטה
  ושיגור לקבוצה (555/2 → members), ניהול members ב-555/5 עם
  `tzintuk_block_instead_of_remove=yes`.
- **שלוחה 9** — מסלול ידני (מוגנת סיסמה): 9/2 הקלטה (`folder_move=/1`) → 9/4
  שיגור; **9/44** = `yemot_dialer_campaign_start` עם `template_to_start=1`.
- **שלוחה 0** — `admin_login` עם `admin_login_campaign_message_template_default_copy=/1`
  (כל הקלטת קמפיין משוכפלת לשלוחה 1). ⚠ טרם אומת בשטח על ההקלטה הבאה.
- **תבנית 1430692** = של האפליקציה: היא מנקה וטוענת את הרשימה בכל שליחה —
  **אסור לערוך את רשימתה ידנית** (יימחק) ואסור לכוון אליה מודולי ניהול-מהטלפון.
- לפני כל שינוי בשלוחות האלה — לקרוא yemot-line-knowledge (תלויות ומלכודות)
  ו-yemot-line-state (המצב הנוכחי).

## סקילים קשורים

- **anthropic-skills:yemot-hamashiach** — ה-API החיצוני: RunCampaign, RunTzintuk,
  ScheduleCampaign, תבניות, העלאת קבצים. כל מה שהאפליקציה עושה — שם.
- **yemot-line-knowledge** — מלכודות הקו האמיתי (כולל תקרית campaign_message_to_play).
- **yemot-line-state** — התצורה החיה של הקו · **yemot-line-howto** — איך מבצעים.
- **yemot-enter-id** — זיהוי בכניסה לשלוחה (משלים לפילטרים שכאן).
- **yemot-routing / yemot-api-module** — ניתוב שיחות / שלוחות API.

## עדכון הידע

כשמאמתים בשטח פרט שמסומן ⚠ (מפת המקשים של yemot_dialer, add_admin_to_list),
או מגלים הגדרה/התנהגות חדשה במודולים האלה — לעדכן כאן וב-references באותה
הזדמנות. מלכודת שהתגלתה **בקו שלנו** → להוסיף גם ל-yemot-line-knowledge.


## נלמד בשטח — 2/9/2026
- **`yemotContext=REPEAT` נדחה בקו שלנו** (0795378810): `UpdateTemplate` עם `REPEAT` מחזיר שגיאה פנימית גם דרך
  ה-MCP, בעוד `SIMPLE`/`maxDialAttempts` מתקבלים. לפי התיעוד (post/32034) REPEAT = "השמעה חוזרת ב-1 ואישור
  קבלה ב-7" — כנראה שירות שמפעילים מול שירות הלקוחות של ימות. **מנהל חלוקה עבר לסקר בשלוחה 77** במקום.
- `list_campaign_templates`/`get_campaign_template_details` (MCP) לא מחזירים `originateTimeout` — רק
  `maxDialAttempts`/`yemotContext`/`redialPolicy`.

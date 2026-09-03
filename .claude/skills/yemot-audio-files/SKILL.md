---
name: yemot-audio-files
description: >-
  קבצים ושמע בימות המשיח (call2all) — שלוחת הקלטות (record: הקלטת הודעה מהטלפון,
  folder_move, מקשי האישור), שלוחת השמעת קבצים (playfile: סדר השמעה, מספור 000/001,
  ארכיון הודעות Old), קבצי TTS והקראת טקסט (קול, מהירות, create_tts), פורמט הקבצים
  (WAV טלפוני 8kHz, המרות, convertAudio), הודעות מערכת (M0000/M1000, הודעת פתיח,
  קבצי המשך, record_system_messages), קובץ שקט תקין, הודעה יומית/לפי מועדי ישראל,
  תא קולי למייל, ודוחות ymgr (המרה לאקסל, RenderYMGRFile). יש להשתמש בסקיל הזה בכל
  בקשה בסגנון "להקליט הודעה", "להעלות קובץ לשלוחה", "שהמתקשר ישמע קובץ/הודעה",
  "הודעת פתיח", "להחליף הודעת מערכת", "הקראת טקסט / TTS", "איזה פורמט WAV",
  "שלוחת הקלטות", "ארכיון הודעות", "דוח ymgr", "תא קולי", או כל עיסוק בקבצי שמע
  על הקו. נחקר מהמקורות הרשמיים (f2.freeivr.co.il) ב-01/09/2026.
  פירוט גולמי מלא: references/audio-files-details.md.
---

# קבצים ושמע בימות המשיח — record / playfile / TTS / M / ymgr

הידע כאן מהפורום הרשמי f2.freeivr.co.il בלבד (מספרי post/topic ליד כל סעיף).
⚠ = לא אומת בשטח / תקציר שדורש אימות מול הפוסט. אין להסתמך על ידע כללי על
מערכות IVR אחרות.

## 1. שלוחת הקלטות — `type=record` (post/56973)

מקליטים הודעה מהטלפון; הקובץ נשמר כקובץ השמעה בשלוחת יעד.

| הגדרה | משמעות |
|---|---|
| `record_password=XXX` | סיסמה ייעודית לשלוחת ההקלטה |
| `folder_move=` | יעד הקובץ: `this_folder` (ברירת מחדל) / `/7` (שלוחה) / `tfr` (בחירה בשיחה) / `template` (רשימת תפוצה) |
| `option_record=3-5-10` | שקט-מינימום-מקסימום בשניות |
| `record_title=yes/tfr` | הקלטת כותרת נפרדת (חובה / תפריט) |
| `record_ok=#` | # מאשר מיד, בלי תפריט אישור |
| `record_stop_any_key=yes` | כל מקש מסיים הקלטה |
| `set_record_name=yes` | המקליט בוחר את מספר הקובץ (אחרת: המספר הגבוה הבא) |
| `hangup_insert_file=yes` | ניתוק באמצע = ההקלטה בכל זאת נשמרת |
| `say_record_number=no` / `say_record_menu=no` | דילוגים על הקראות |
| `record_end_goto=` / `record_cancel_goto=` | יעד אחרי אישור / ביטול |
| `record_end_run_tzintuk=yes` + `list_tzintuk=` | צינתוק אוטומטי בסיום |
| `email_send=yes`, `record_send_sms=yes/..._to=` | העתק למייל / התראת SMS |
| `copy_record_link=yes` / `hard_link=yes` | לינק לתיקייה נוספת |
| `record_change_pitch=0.5–1.5` | עיוות קול |

**תפריט האישור בסוף ההקלטה** (אחרי #, ברירת מחדל): **1** שמיעה · **2** אישור
ושמירה · **3** הקלטה מחדש · **4** ביטול · **5** הקלטת המשך.

מלכודת `folder_move`: הנתיב חייב להתאים **במדויק** (`07/3` ≠ `7/3`) — שגוי =
ההקלטה נעלמת בלי שגיאה (תועד בתחקיר שלוחה 1, yemot-line-knowledge).
יומן פר-שלוחה: `record_log.ymgr`.

## 2. שלוחת השמעת קבצים — `type=playfile` (post/68755)

ההגדרה החובה היחידה: `type=playfile`. זהו מודול "התוכן" המרכזי של המערכת.

- **סדר השמעה:** ברירת מחדל `start=max` — **מהקובץ הגבוה לנמוך** (החדש ביותר
  קודם; לכן הקלטה חדשה = מה שנשמע ראשון). עוד: `start=min`, `start=select`
  (תפריט), `random=1` (אקראי בלי חזרות), `last_play_auto=yes` (המשך מנקודת
  עצירה).
- **מספור:** 3 ספרות מינימום (000, 001…); שינוי: `file_amount_digits`.
- **מקשים בהשמעה (ברירת מחדל):** 1 אחורה 10 שנ' · 3 קדימה 10 שנ' · 2 קובץ
  הבא · 8 קובץ קודם · # חזרה למעלה. מערך המקשים המלא (6 קידומות
  `control_play*`) — ב-`yemot-line-knowledge/references/community/03-menu-playfile-record-confbridge.md`.
- **סוף ההשמעה:** ברירת מחדל חזרה שלב אחורה; `playfile_end_goto=/5/8` = יעד
  אחר.
- **ארכיון Old:** `playfile_move_file_to_old=yes` (קובץ שנשמע עובר גלובלית
  ל-Old — **מלכודת לקו ציבורי**, ההודעה נעלמת אחרי מאזין ראשון) ·
  `playfile_end_play_old=tfr/yes` — פירוט והשלכות על שלוחה 1 שלנו כבר מתועדים
  ב-**yemot-line-knowledge** ("זרימת ההודעה השבועית") — לא לשכפל, לקרוא שם.
- **מעקב האזנה:** `listening_mark=yes`, `check_if_listening_ok=yes`,
  `log_playback_play_stop=yes`.

**`play_and_return` — שני מובנים** (topic/78, post/2899): כ-`type=` = שלוחה
שמשמיעה הודעה אחת וחוזרת; כהגדרה `play_and_return=play_all` = הודעת הפתיח
מושמעת עד הסוף בלי דילוג.

## 3. קבצי TTS — הקראת טקסט (post/2902, topic/5646, post/89921)

- קובץ טקסט **UTF-8** בסיומת `.tts` (למשל `000.tts`); המערכת מקריאה אותו.
  עד **~1,300 תווים**. גם הודעות מערכת אפשר כך (`M0000.tts`).
- **אין ליצור WAV מקביל באותו שם** — ה-WAV גובר וה-tts מושתק.
- **קול ומהירות** — ב-`ext.ini` של השלוחה (או `ivr.ini` לכלל המערכת):
  `voice=Elik_2100` (ברירת מחדל) / `Jacob` / `Sivan` / `Osnat`;
  `rate=-10..10` (0 = רגיל). חל על כל קבצי ה-tts בשלוחה.
- **יצירת tts מהטלפון:** `type=create_tts` — הקלדה (`create_tts_type=keyboard`)
  או הקלטה שמומרת לטקסט (`record`); יעד `create_tts_in_folder=`; אישור
  `create_tts_record_ok=#`; יעדי סיום/שגיאה `create_tts_end_goto=` /
  `create_tts_error_goto=`. הודעות מלוות M3969–M3975. פירוט מלא ב-references.
- באפליקציה שלנו TTS נעשה **מקומית** (`utils/tts.py`, Gemini/Edge) ומועלה
  כקובץ שמע — לא בקבצי .tts של ימות; קבצי .tts שימושיים לטקסטים קצרים שרוצים
  לערוך דרך ה-API בלי לייצר שמע (UploadTextFile).

## 4. פורמט הקבצים (post/62514) + קובץ שקט (post/60816)

- פורמט פנימי: **WAV Windows PCM, ‏8000Hz, ‏16-bit, מונו**.
- העלאה מהאתר = המרה אוטומטית; **FTP = חובה להמיר ידנית מראש**;
  API = `UploadFile&convertAudio=1` ממיר בשרת (המסלול של האפליקציה — אומת
  בשטח; מקבל גם MP3).
- "השתקת" הודעה: לא קובץ ריק (שובר חדרי ועידה ועוד) — אלא `quiet.wav` תקין
  מהפוסט.

## 5. הודעות מערכת — קבצי M (post/3, post/4, post/2899)

- כ-150 הודעות M0000–M1148 (רשימה מלאה ב-post/3; עברית/אידיש/אנגלית).
  מפתח: **M0000** = הודעת הפתיח ("ברוכים הבאים", ראשונה בשלוחה) · **M1000** =
  הודעת התפריט · M1001/M1002 = מקש לא חוקי / אין בחירה.
- **החלפה:** מעלים קובץ בשם ההודעה (`M1000.wav` או `M1000.tts`) לשלוחה — גובר
  על ברירת המחדל באותה שלוחה. ⚠ היררכיית "שלוחה → שורש → מערכת" לא צוטטה
  במפורש בפוסטים שנבדקו; קיום רמת-שורש נרמז מ-`record_system_folder=main`.
- **קבצי המשך** (post/2899): `M0000`, `M0000-1`, `M0000-2`… — הודעה מפוצלת
  שמושמעת ברצף. `say_first_one_time=yes` = פתיח פעם אחת לשיחה.
- **הקלטת הודעות מערכת מהטלפון:** `type=record_system_messages` —
  `record_system_folder=/8/8|main`, קיבוע הודעה `record_system_messages=M1000`,
  הודעות זמניות עם תוקף, `record_system_messages_plus=yes` (כוכבית במקום מקף).

## 6. הודעות מתחלפות לפי זמן (post/33, post/32)

- **`type=daily_message`** — סדר חיפוש: `YYYY-MM-DD.wav` (עם `date=hebrew` —
  תאריך עברי) → רשומת תאריך ב-`daily_message.ini` → `N.wav` לפי יום בשבוע →
  רשומת יום ב-ini → `default.wav` → הודעת TTS. `*` מסיים, `#` יוצא,
  `skip_by_any_key=yes`; בסיום `daily_message_end_goto=`.
- **`type=toplay_time`** — הודעה לפי לוח לועזי/עברי/עומר/חנוכה, עם בקרת
  תדירות (כמה זמן לא לחזור, מקס' השמעות, `thiscall`) ויומן
  `toplay_time_log_save=yes`. ⚠ שמות השדות המדויקים — לאמת בפוסט לפני שימוש.

## 7. תא קולי עם העתק למייל — `type=voicemail_email` (post/49)

`email_address=` (+`email_address2=`), `email_name=`, `email_title=`,
`folder_move=` (העברת ההקלטות), תקרת הודעות `voicemail_email_record_max=`
(+`..._by_day=yes`), `stop_record_only_hangup=yes` (הקלטה עד ניתוק),
`record_tts_to_mail=yes` (תמלול למייל), `voicemail_email_send_telegram=yes`.

## 8. דוחות ymgr (post/78987, post/1984, topic/11197)

- `.ymgr` = קובצי יומן/דוח פנימיים; מבנה: `#` מפריד שדות, `%` בין כותרת לערך
  (כמו `Folder#1%Phone#05...`). קיימים בין השאר: `record_log.ymgr`,
  `Log/LogFolderEnterExit-YYYY-MM.ymgr`, `LogApi.ymgr`.
- **לאקסל:** (א) כפתור הייצוא בממשק — HTML/CSV (CSV לפתוח דרך אשף ייבוא
  UTF-8, לא פתיחה ישירה); (ב) ידנית: החלף `#`→פסיק, `%`→פסיק, `/`→נקודה →
  CSV; (ג) **API:**
  `RenderYMGRFile?wath=ivr2:/1/file.ymgr&convertType=csv|html|json&LoadLang=1&token=…`
  — ⚠ שם הפרמטר הוא **`wath`** (כך! לא `what`); `LoadLang=1` = כותרות
  מותאמות. באקסל: נתונים ← מהאינטרנט ← ה-URL = טבלה מתרעננת.
- התאמת תצוגה (הסתרת עמודות/שינוי כותרות) — קובצי ini היררכיים (post/78987).

## 9. העלאה/הורדה דרך ה-API החיצוני (בקצרה)

`UploadFile` (+`convertAudio=1`) · `DownloadFile` (`what=ivr2:/1/000.wav` /
`tpl:<id>`) · `UploadTextFile`/`GetTextFile` (ל-ini/tts) · `GetIVR2Dir` (תוכן
תיקייה — כך מאתרים מספר פנוי הבא). פירוט מלא בסקיל הענן
**anthropic-skills:yemot-hamashiach**; מימוש חי ב-`utils/yemot.py`
(`upload_message_wav`, `publish_to_extension`).

## 10. מלכודות (מהמקורות בלבד)

- `folder_move` עם נתיב לא-מדויק — ההקלטה נעלמת בשקט (סעיף 1).
- `playfile_move_file_to_old=yes` על קו ציבורי — הודעות נעלמות (סעיף 2).
- WAV מקביל ל-.tts באותו שם — ה-tts לא יושמע (post/2902).
- קובץ ריק במקום `quiet.wav` — חלקי מערכת (חדרי ועידה) נכשלים (post/60816).
- העלאת FTP בלי המרה מוקדמת ל-8kHz/16bit/מונו — לא יעבוד (post/62514).
- CSV של ymgr שנפתח ישירות באקסל — עברית ג'יבריש (ANSI); דרך אשף ייבוא UTF-8
  (post/78987). ב-RenderYMGRFile — הפרמטר `wath`, לא `what`.
- הקלטה קצרה ממינימום `option_record` — נפסלת (post/56973).

## 11. הקשר לקו האמיתי ולאפליקציה

- **שלוחה 1 = ארכיון ההודעות הציבורי** (`playfile`, ~525 קבצים, החדש קודם).
  מסלול המילוי הידני: שלוחה 9 (מוגנת סיסמה — הערך ב-yemot-line-state) → **9/2 `record` עם
  `folder_move=/1`** → 9/4 שיגור. תחקיר הקיפאון והתיקון
  (`admin_login_campaign_message_template_default_copy=/1`) — ב-**yemot-line-knowledge**.
- **האפליקציה** מייצרת הקלטות ב-`utils/tts.py` (Gemini `gemini:Charon`/`Aoede`
  או Edge Avri/Hila; פלט WAV/MP3) ומעלה עם `convertAudio=1` לתבנית הקמפיין
  (`tpl:` עם נפילה ל-`ivr2:`). פרסום לשלוחה 1 — **ידני בלבד**
  (`publish_to_extension`, הכרעת v2.89 — פרטיות הודעות הנזקקים).
- מאגר ההקלטות המקומי: `%APPDATA%\ManhalHaluka\recordings\` (ראו CLAUDE.md
  v2.86).

## סקילים קשורים

- **yemot-line-state** — מה יש בקו עכשיו (שלוחות, קבצים, יתרה).
- **yemot-line-knowledge** — למה הקו בנוי כך; תחקיר שלוחה 1 וארכיון Old.
- **yemot-line-howto** — איך מבצעים שינוי בקו דרך ה-API.
- **yemot-enter-id** — כניסה מזוהה ודוחות נוכחות.
- **yemot-routing / yemot-api-module / yemot-caller-data** — ניתוב, שלוחות API,
  והשמעת נתונים אישיים.
- **yemot-campaigns-ivr** — קמפיינים ורשימות מתוך הטלפון (כולל
  `record_end_run_tzintuk` בצד הקמפיינים ו-campaign_message_to_play).
- **yemot-ecosystem** — מודולים רשמיים, כלי צד-שלישי (פתרונאי, עורך אודיו בדפדפן) וספריות.
- **anthropic-skills:yemot-hamashiach** (ענן) — ה-API החיצוני המלא + learned-solutions.

## עדכון הידע

כשמתגלה הגדרה/התנהגות חדשה בתחום הקבצים והשמע (מהפורום או מאימות בשטח) —
לעדכן סקיל זה ואת `references/audio-files-details.md` באותה הזדמנות, ולסמן ⚠
שהוסר/אושר. ידע ספציפי לקו שלנו → yemot-line-knowledge; ידע API כללי →
learned-solutions של הסקיל בענן.

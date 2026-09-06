# תרחישים ומפת זרימות — מסך הצינתוקים

## א. מפת הזרימות (קרא לפי זרימה, לא לפי סדר הקובץ)

הקבצים: `tabs/tzintukim.py` (`TzintukimTab`, `_PollWorker`, `_CallbackWorker`, `_TaskWorker`, דיאלוגים),
`utils/yemot.py` (לקוח טהור), `utils/call_history.py`, `utils/tts.py`, וב-`database.py` הפונקציות
`*tzintuk*` + ops הסנכרון `tz_add`/`tz_update`. לכל זרימה עקוב מהכפתור ועד כתיבת ה-DB/הסנכרון.

| # | זרימה | נקודות כניסה |
|---|---|---|
| א | טעינת רשימה: שבוע / אצווה קודמת / עצמאית / ניקוי | `_load_week_list`, `load_batch`, `_FreeListDialog`, `_clear_batch`, `_populate`, `refresh`, `_reset_results` |
| ב | שליחה מיידית (עם הודעה / קלאסי) | `_send`, `_SendModeDialog`, `_changed_meanwhile`, `run_campaign`, `run_tzintuk`, `_start_tracking` |
| ג | מעקב חי ותוצאות | `_PollWorker`, `_on_tick`, `_on_worker_done`, `_chain_next`, `_merge_entries`, `_list_results`, `_apply_results_to_table`, `_results_belong_here` |
| ד | תזמון (רגיל + שיגור חכם) וביטול | `_schedule`, `_smart_schedule`, `schedule_smart`, `_cancel_sched`, `_pending_scheds`, `_check_scheduled`, `find_scheduled_by_template` |
| ה | חידוש אחרי הפעלה / סנכרון מהמחשב השני | `_maybe_resume_tracking`, `_is_own_campaign`, `_retire_trackers`, `_active_guid`, LWW ב-`_apply_tz_update` |
| ו | סקר 77 ותשובות | `_CallbackWorker`, `merge_survey_answers`, `answer_windows`, `_refresh_answers`, `_auto_refresh_answers`, `answers_for_date` |
| ז | הקלטה: TTS / העלאה / מאגר / בדיקה למנהל | `TtsDialog`, `LibraryDialog`, `upload_message_wav`, `run_test`, `_TestStatusDialog` |
| ח | היסטוריה, ייצוא, משיכה מהשרת, שעה אישית | `answer_stats`, `best_hour`, `personal_hour`, `_sync_history`, `export_tzintuk_history_to_excel` |
| ט | חיבור/שגיאות/רשת | `_http`, `_call`, `_DIAL_COMMANDS`, `_ERROR_HE`, `_run_blocking`, נפילה לשרת התאום |

## ב. רשימת התרחישים — "מה קורה אם…"

לכל תרחיש ענה **מהקוד**. "לא בטוח" → בדיקה מדומה שמכריעה (`test-harness.md`).

### מצב ותזמון (המקור לרוב הבאגים ההיסטוריים)
- שני workers חיים בו-זמנית (שליחה בזמן מעקב, סנכרון בזמן דיאלוג מודאלי, תזמון שהבשיל בזמן סקר).
  מי כותב ל-`_active_guid`? tick מאוחר של worker שפוטר מתעלם?
- worker שנגמר תקציבו (`timed_out`) — הרצועה מתחדשת (`_chain_next`) או קופאת על "שולח…"?
- worker שנפל על 5 כשלי-רשת (`failed`) — מתחדש אחרי דקה?
- `refresh()` מסנכרון באמצע פעולה: סימוני V (`_row_key`/`prev_checked`), `_last_final`, `_last_entries`,
  ווידג'ט בתא טבלה שנשאר "צף".
- מעבר בין רשימות (שבוע ↔ אצווה ↔ עצמאית ↔ לא-טעון) — `_batch`/`_free`/`_last_failed`/`btn_resend`
  מתאפסים? תוצאות של רשימה ישנה צובעות חדשה? שתי רשימות עצמאיות (`dist_date=""`) מובחנות לפי guid?
- דיאלוג אישור פתוח בזמן שהמחשב השני שלח/תזמן — `_changed_meanwhile` מבטל עם הסבר?
- אותה פעולה פעמיים מהר (לחיצה כפולה על שליחה/תזמון/ביטול/שיגור חכם) — הכפתורים ננעלים?
- מחשב שני רואה 'sending' של צינתוק קלאסי — **לא** מצטרף למעקב (`_is_own_campaign`).
- שליחה מיידית כשיש תזמון ממתין — חסומה (הרשימה בתבנית תידרס).

### נתונים ותאימות
- `report_json` ישן (בלי `at`/`duration`/`answer`/`redials`/`send`) נטען בלי קריסה? `.get` סלחני?
- סטטוסים `scheduled`/`sending`/`done`/`canceled`/`sched_failed` — כל צרכן מטפל בכולם
  (`tzintuk_campaign_for_date`, `_pending_scheds`, היסטוריה, ייצוא, `_list_results`)?
- LWW בסנכרון: `status_ts`=עכשיו (לעולם לא `sent_at` עתידי), ביטול מהמחשב השני, `tz_add` מהסיד עם תוצאות.
- מספר משותף לשתי משפחות (מצלצל פעם אחת, סטטוס לשתיהן), מספר בלי 0 מוביל מאקסל, `+972`, ריק/שבור,
  שני מספרים באותה שורה של רשימה עצמאית, שורה בלי אף טלפון מדווחת פסולים.
- תשובות סקר: `since_iso` בכל מסלול (poll, callback, resend, `_check_scheduled`) **וגם** חסם-עליון
  `until_by_phone` (`answer_windows`) — תשובת השבוע לא נזקפת לקמפיין של שבוע שעבר.
- כמה קמפיינים על אותה רשימה (שיגור חכם / שליחה חוזרת) — מיזוג לפי זמן שליחה, לא לפי סדר סיום.
- רשומה 'sending' בלי `campaign_id` — נסגרת 'done' אחרי שעה, לא "בתהליך" לנצח.
- תזמון בלי `schedId` שרץ — מאותר לפי תבנית+שעה, לא מסומן `sched_failed`.

### רשת ושגיאות (transport שזורק)
- timeout על פקודת חיוג → **ניסיון אחד** + "ייתכן שהשליחה כבר יצאה". timeout על קריאה → retry.
- 103/104/105/106/107–110 בכל אתר — ממופות לעברית? חוסמות / נופלות למסלול חלופי כצפוי?
  קלאסי נופל ל-RunCampaign קצר רק על שגיאת-שרת שאינה ‎-1/103/104.
- `_run_blocking` — החריגה עולה בעברית, הדיאלוג נסגר, ה-fn לא נוגע בווידג'טים מה-thread.
- מבנה חלקי מהשרת (entries ריק, `campaignId=""`, שדה חסר) — לא קורס.

### UI (RTL, פשטות)
- טקסט קטום בכפתורי primary, `QDateTimeEdit` LTR **לפני** `setDisplayFormat`, גובה טבלה מלא,
  תוויות שקר (מונה שלא תואם את הטבלה), "לא הגיב" רק כשהקמפיין נגמר.
- כפתורי שליחה/תזמון/שיגור-חכם נעולים כשאין נמענים, בזמן שליחה, וכשיש תזמון ממתין.
- שיגור חכם להיום מזהיר **לפני** האישור על שעות שכבר עברו.

### נוסף ב-3.22 (6/9/2026)
- **עצירת שליחה** (`_stop_campaign` → `yemot.stop_campaign`): מה אם המזהה ריק? (הכפתור מוסתר.) מה אם השרת דוחה
  (הקמפיין נגמר)? (הודעה; המעקב ממשיך.) הכפתור חייב להיעלם ב-`_retire_trackers` ובסיום (I31).
- **תזמונים מרובים**: שני תזמונים ⇒ שתי תבניות שונות (`_busy_templates`); תבנית שהתזמון שלה יצא חוזרת למאגר;
  תזמון מהמחשב השני על "תזמון 1" בזמן שאני מתזמן ⇒ busy מסונכרן דרך רשומות `scheduled`; תזמון **ישן** (מלפני 3.22,
  על התבנית הראשית) עדיין חוסם שליחה (`_pending_main_sched`); שיגור חכם נחסם רק כשתבניות-השעה תפוסות.
  ביטול של אחד לא נוגע באחר (`_cancel_sched(items)`).
- **צ'יפ חי**: `_apply_conn_state` על Exception ⇒ אדום; probe לא רץ כפול (`_conn_worker`); לא רץ כשלא מוגדר.
- **הקלטה במיקרופון**: אין מיקרופון / אין QtMultimedia ⇒ כפתור ההקלטה כבוי עם הסבר; הקלטה קצרה מ-0.5 שנ' נדחית;
  ביטול באמצע הקלטה עוצר את ה-`QAudioSource`.
- **נטפרי**: transport שזורק `HTTPError 418` ⇒ `YemotError(-3)` בניסיון אחד, בלי `private.` (I32).

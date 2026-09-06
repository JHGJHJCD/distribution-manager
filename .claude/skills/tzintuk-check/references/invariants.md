# אינווריאנטים — כללים שהקוד חייב לקיים תמיד

כל שורה = כלל שנלמד מבאג אמיתי (הגרסה בסוגריים). עמודת "לינט" אומרת אם `scripts/check_tzintuk.py`
בודק אותו סטטית (`LINTS`). כלל חדש שניתן לבדיקה סטטית → הוסף לינט באותה הזדמנות.

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| I1 | `CALLBACK_ENABLED = False` — שלוחה 78/פילטר שורש נעולים (תקרית 3/9) | `yemot.py` | ✓ |
| I2 | פקודות חיוג (`_DIAL_COMMANDS` = RunCampaign/RunTzintuk/ScheduleCampaign) יוצאות **פעם אחת**: `retry=False`, בלי שרת תאום (3.15) | `yemot._call`/`_http` | ✓ |
| I3 | כל התחלת מעקב (`_start_tracking` **ו**-`_start_callback_tracking`) קוראת `_retire_trackers()` (3.14/3.15) | `tzintukim.py` | ✓ |
| I4 | tick נושא את ה-worker שלו (`_on_tick(st, worker)` / `_on_cb_tick(st, worker)`); tick של worker שפוטר מתעלם (3.15) | `tzintukim.py` | ✓ |
| I5 | `_PollWorker` עם דגל `timed_out`; `_on_worker_done` מחדש דרך `_chain_next` (3.14) | `tzintukim.py` | ✓ |
| I6 | `_PollWorker.failed` (כשלי רשת) → חידוש אחרי דקה (`QTimer.singleShot`) (3.16) | `tzintukim.py` | ✓ |
| I7 | `_reset_results` מאפס גם `_last_failed`/`btn_resend`/`_last_final`/`_last_entries` (3.13/3.16) | `tzintukim.py` | ✓ |
| I8 | `_load_week_list` מאפס `_batch`/`_free` וקורא `_reset_results` (3.15) | `tzintukim.py` | ✓ |
| I9 | ביטול תזמון: מזהה ריק ⇒ `find_pending_sched_id` (3.14) | `_cancel_sched` | ✓ |
| I10 | תזמון-שהבשיל בלי schedId ⇒ `find_scheduled_by_template` (3.16) | `_check_scheduled` | ✓ |
| I11 | ציור תוצאות/נכשלים רק כש-`_results_belong_here(worker)` (3.17) | `tzintukim.py` | ✓ |
| I12 | `_maybe_resume_tracking` מדלג על צינתוק קלאסי של מחשב אחר (`_is_own_campaign`) (3.18) | `tzintukim.py` | ✓ |
| I13 | בדיקות-קדם חוזרות אחרי הדיאלוג המודאלי (`_changed_meanwhile`) (3.19) | `tzintukim.py` | ✓ |
| I14 | `_answer_campaigns` סורק ≥200 רשומות (3.19) | `tzintukim.py` | ✓ |
| I15 | `merge_survey_answers` מקבל חסם-עליון מ-`answer_windows` (3.20) | `yemot.py`/workers | ✓ |
| I16 | `status_ts` של רשומת צינתוק = עכשיו, לעולם לא `sent_at` (2.97) | `database.py` | ידני |
| I17 | שליחה מיידית חסומה כשיש תזמון ממתין **על התבנית הראשית** (`_pending_main_sched` — רשומות מלפני 3.22; תזמון 3.22 יושב על תבנית ייעודית ולא חוסם) (2.97/3.22) | `_send` | ✓ |
| I18 | `run_test` לא מנקה את רשימת התבנית (`add_template_entry`, בלי Clear) (2.94) | `yemot.py` | ✓ |
| I19 | אין פרסום אוטומטי בשלוחה 1 — `publish_to_extension` נקרא רק מהכפתור הידני (2.89) | `tzintukim.py` | ✓ |
| I20 | קריאות חוסמות לשרת דרך `_run_blocking` (המסך לא קופא) (2.98) | `tzintukim.py` | ✓ |
| I21 | `since_iso` מועבר לכל worker (3.13) | `tzintukim.py` | ✓ |
| I22 | `QDateTimeEdit` — `setLayoutDirection(LTR)` לפני `setDisplayFormat` (2.86) | `_ScheduleDialog` | ✓ |
| I23 | `test_tzintuk.py` מפנה `call_history.cache_path` לתיקייה זמנית **לפני** ייבוא `yemot` (3.11) | `test_tzintuk.py` | ✓ |
| I24 | בדיקות ה-Qt מחליפות `start` של כל 3 ה-workers ב-no-op (3.15) | `test_tzintuk.py` | ✓ |
| I25 | `test_tzintuk.py` ו-`test_sync.py` ברשימת `TESTS` של `release.py` | `release.py` | ✓ |
| I26 | כל רשומת קמפיין (שליחה/חוזרת/תזמון/קבוצת שיגור חכם) נזרעת במספרים שלה מרגע היצירה (`_seed_json`, entries `status=pending`) כדי ש-`answer_windows` יסגור את חלון הקודם גם בזמן שהחדש רץ; `_on_sched_checked` משמר `report_json` (3.21) | `tzintukim.py` | ✓ |
| I27 | סיום מעקב-חזרה של קלאסי (`_on_cb_worker_done`) מחדש מעקב שפוטר; `_resume_classic` מחזיר bool והלולאה ממשיכה על קלאסי שלא פתח מעקב (3.21) | `tzintukim.py` | ✓ |
| I28 | `_start_tracking` עם מזהה ריק לא פותח poll — הודעה ברצועה, בלי "החיבור נכשל" (3.21) | `tzintukim.py` | ✓ |
| I29 | `until_by_phone` גם ב-`_CallbackWorker`, לא רק ב-`_PollWorker` (3.21) | `tzintukim.py` | ✓ |
| I30 | תזמון רגיל יוצא על תבנית ייעודית (`schedule_campaign_dedicated`/`ensure_sched_template(busy)`), לעולם לא על הראשית — כך תזמונים לא דורסים זה את זה ושליחה מיידית לא דורסת תזמון (3.22) | `_schedule`/`yemot.py` | ✓ |
| I31 | כפתור "עצור שליחה" גלוי רק בזמן poll: נעלם ב-`_retire_trackers` ובסיום קמפיין (3.22) | `tzintukim.py` | ✓ |
| I32 | חסימת נטפרי (418 / "Blocked by NetFree") מזוהה ב-`_http`/`_upload_multipart` דרך `utils.netblock` → `YemotError(code=-3)` בלי retry ובלי שרת תאום; ‎-3 ≠ ‎-1 (חסימה מקומית — הפקודה בוודאות לא הגיעה) (3.22) | `yemot.py` | ✓ |
| I33 | `ensure_template` מאשר פעם אחת לכל tid (`SET_TEMPLATE_READY`) תיאור + 30 שנ' + 2 ניסיונות, בלי `yemotContext` (3.22) | `yemot.py` | ✓ |
| I34 | `_on_sched_checked` שומר את `report_json` (המספרים שנזרעו) בכל סגירה — `done` בלי מזהה / `sched_failed`; מחיקה איבדה את תשובות הסקר של השליחה (3.23) | `tzintukim.py` | ✓ |
| I35 | `_schedule`/`_smart_schedule` מוסרים ל-`_changed_meanwhile` את `_pending_main_sched()` — אותו דבר שהיא משווה; `_pending_sched()` (הכללי) גרם ל"נקלט תזמון ממתין" מדומה כשתזמון ישן וחדש ממתינים יחד (3.23) | `tzintukim.py` | ✓ |
| I36 | אחרי "עצור שליחה" ה-poll מסתיים לבד: `stopped_at` + `_apply_stop` + `STOP_GRACE_S` — לא סומכים על `finished` של השרת אחרי stop (3.23) | `_PollWorker` | ✓ |

כללים שאינם ניתנים ללינט סטטי (לבדוק בקריאה/בדיקה מדומה): `.get` סלחני על `report_json` ישן ·
כל סטטוס מטופל בכל צרכן · LWW עם חותמת עתידית · מיזוג קמפיינים לפי זמן שליחה · "לא הגיב" רק בסיום.

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
| I17 | שליחה מיידית חסומה כשיש תזמון ממתין (`_pending_sched`) (2.97) | `_send` | ✓ |
| I18 | `run_test` לא מנקה את רשימת התבנית (`add_template_entry`, בלי Clear) (2.94) | `yemot.py` | ✓ |
| I19 | אין פרסום אוטומטי בשלוחה 1 — `publish_to_extension` נקרא רק מהכפתור הידני (2.89) | `tzintukim.py` | ✓ |
| I20 | קריאות חוסמות לשרת דרך `_run_blocking` (המסך לא קופא) (2.98) | `tzintukim.py` | ✓ |
| I21 | `since_iso` מועבר לכל worker (3.13) | `tzintukim.py` | ✓ |
| I22 | `QDateTimeEdit` — `setLayoutDirection(LTR)` לפני `setDisplayFormat` (2.86) | `_ScheduleDialog` | ✓ |
| I23 | `test_tzintuk.py` מפנה `call_history.cache_path` לתיקייה זמנית **לפני** ייבוא `yemot` (3.11) | `test_tzintuk.py` | ✓ |
| I24 | בדיקות ה-Qt מחליפות `start` של כל 3 ה-workers ב-no-op (3.15) | `test_tzintuk.py` | ✓ |
| I25 | `test_tzintuk.py` ו-`test_sync.py` ברשימת `TESTS` של `release.py` | `release.py` | ✓ |

כללים שאינם ניתנים ללינט סטטי (לבדוק בקריאה/בדיקה מדומה): `.get` סלחני על `report_json` ישן ·
כל סטטוס מטופל בכל צרכן · LWW עם חותמת עתידית · מיזוג קמפיינים לפי זמן שליחה · "לא הגיב" רק בסיום.

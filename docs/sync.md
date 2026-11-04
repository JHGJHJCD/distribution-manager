# סנכרון בין 2 מחשבים — הנוסח המלא

> הנוסח המלא של הסעיפים כפי שהיו ב-`CLAUDE.md` עד הקיצור של 4/11/2026 (מילה במילה). ב-CLAUDE.md נשארו רק ההכרעות והאיסורים בתמצית; **כאן = הפירוט המחייב** (שמות פונקציות, מפתחות, מקרי קצה). כששינוי נוגע בנושא — לעדכן כאן.

## סנכרון בין 2 מחשבים (`utils/sync.py`)
- **דרישת המשתמש:** שני מחשבים, מקומות שונים, גם בו-זמנית. אין שרת → **תיקיית Google Drive משותפת** (`sync.SHARED_SUBFOLDER` = "מנהל-חלוקה-משותף" בתוך «Drive שלי»; "הפעל סנכרון אוטומטי" = `sync.auto_setup()`; תיקייה ב-Downloads/Desktop לא משותפת ע"י Drive!).
- כל מחשב כותב journal משלו (`journal-<device>.jsonl`); כל שינוי ב-`database.py` → `_sync_log(op, payload)`; שורות מזוהות ב-**guid** (לעולם לא ב-id מקומי — id מקומי במחשב השני = אדם אחר!). מעקב per-device ב-`sync_state.json` **ליד ה-DB**. **התנגשות = LWW לפי חותם UTC.** רקע: `_SyncWorker` כל ~10–20 שנ'. offline → `sync_outbox.jsonl`.
- **כל מידע חדש שצריך להגיע למחשב השני** = עמודה עם guid/updated_at + op + applier + seed ב-snapshot (סקיל `db-migration`). ops היום: `rec_upsert/rec_delete/rec_change/batch_add/batch_delete/dist_add/dist_delete/setting/msg_*/fb_*/tz_add/tz_update/mail_add/mail_update/mtpl_upsert/snap_req`.
- `_adopt_match`: guid לא מוכר → `external_id`, ואז שם **וגם טלפון שווה**. `_apply_rec_delete` = LWW. דחיסת יומן מעל 3MB (`compact_journal`: epoch, tombstones, snapshot, הגדרות עם ts אמיתי).
- **עמידות הסנכרון (v3.79; `test_sync_resilience.py`; פירוט בארכיון):** סקריפט/בדיקה מחוץ לאפליקציה **לא כותבים** למצב הסנכרון האמיתי ב-`%APPDATA%\ManhalHaluka` (`sync._foreign_on_real_state()`; עקיפה מכוונת = `MANHAL_ALLOW_REAL_SYNC=1`) — **תמיד להפנות `db.DB_PATH` לתיקייה זמנית** (27/9 ריצה כזו אפסה `seq` והמחשב השני זרק שינויים בשקט). `repair_seq()` — `seq` לא יורד אף פעם; נעילת מסד חולפת = ניסיון חוזר, לא בליעת רשומה; `ensure_drive_running`/`ensure_drive_autostart`/`heal_folder` מתקנים את Google Drive בזהירות (לא עותק שני, לא רישום חדש).
- **לא מסונכרן (בכוונה):** `EXCLUDED_SETTINGS` (מצב החלוקה `dist_regulars_mode` — משימה 5, סיסמה, גאומטריה, גיבוי, גודל טקסט, תיקיות ייצוא, רקע/צ'אט-רקע), משקלי הניקוד, "אפס נתונים", נכסי לוגו/רקע. **מסונכרן בכוונה:** פרטי ימות, חיבור Google, סוד שרת המענה, קריטריוני הסינון, קוד מנהל, שם השולח במייל.
- **הכרעות המשתמש (2/9/2026):** "אפס נתונים" כשהסנכרון פעיל = "התחל מחדש מהמחשב השני" (`restart_from_peer` + `snap_req`, נתונים בלבד — ההגדרות המקומיות נשמרות); `undo_incoming` על "מקבל שנוסף" מוחק בכוח כולל היסטוריה בשני המחשבים — **מכוון**.
- **מחשב מנהל** (`is_manager` פר-מחשב + קוד מנהל מסונכרן): רק בו נרשמים שינויים נכנסים (`sync_incoming`) ו-"יומן שינויים…" עם "בטל".
- בדיקות: `test_sync.py` (2 מחשבים מדומים). ⚠ `test_sync` אסור שידרוס `sync_state.json` בעותק ישן.

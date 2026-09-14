# אינווריאנטים — כללים שקוד המיילים חייב לקיים תמיד

כל שורה = כלל שנלמד מבאג אמיתי או מהכרעת המשתמש (הגרסה בסוגריים). עמודת "לינט" אומרת אם
`scripts/check_mail.py` בודק אותו סטטית (`LINTS`). כלל חדש שניתן לבדיקה סטטית → הוסף לינט באותה הזדמנות.

## שליחה — אף מייל לא "נשלח" בשקט כשלא נשלח

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M1 | `send_batch` תופס חריגה **לכל נמען בנפרד** (`except Exception` בתוך הלולאה → `status=failed`), לא מפיל את כל האצווה; `should_stop()` מסמן את השאר `skipped` (3.39) | `mailer.send_batch` | ✓ |
| M2 | SMTP: נמען שהשרת **סירב** לו = כישלון (`if refused: raise`), ואין-אינטרנט = הודעה בעברית (OSError → RuntimeError) (#ib2st) | `email_utils.send_email` | ✓ |
| M3 | Gmail API: 401 → ריענון טוקן (`force=True`) וניסיון **אחד** נוסף; חסימת נטפרי (418) מזוהה דרך `netblock` (3.39) | `google_auth.gmail_send_raw` | ✓ |
| M4 | `_validate_message` (נושא + גוף + `is_configured`) רץ לפני **כל** שליחה: `_send` ו-`_send_test` (3.39) | `mails.py` | ✓ |
| M5 | `btn_send` פעיל רק כש-`is_configured()` **וגם** יש יעד תקין **וגם** לא באמצע שליחה (3.39) | `mails._update_metrics` | ✓ |
| M6 | אין שליחה כפולה: `_send` יוצא אם `self._worker is not None`; רשומת `add_mail_campaign` נוצרת **לפני** `start()`; `_on_finished` מעדכן את הרשומה **בשני** המסלולים (הצלחה/חריגה) (3.39) | `mails._send`/`_on_finished` | ✓ |
| M7 | שליחה שנקטעה (תוכנה נסגרה) נסגרת כ-`interrupted` **רק** של המחשב הזה ו**לא** של השליחה הפעילה (`_active_guid`) (3.39) | `mails._close_stale_campaigns` | ✓ |
| M8 | "שלח שוב לנכשלים" לוקח רק `failed`/`skipped`, מסנן לפי `valid_email`, ועובר דרך `_send` (אותו אישור/רישום) (3.39) | `mails._resend_failed` | ✓ |
| M29 | **תקלה כללית עוצרת את האצווה** (3.42): חריגה עם `fatal=True` (אין אינטרנט / סיסמה / הרשאה / מכסה / נטפרי) אצל נמען אחד → השאר `skipped` עם **סיבת התקלה** (לא `STOP_MSG`), `stop_reason(rows)` מחזיר אותה. בלי זה: 500 ניסיונות × timeout, וסיכון נעילת חשבון Gmail על 500 כניסות שגויות | `mailer.send_batch`/`is_fatal`/`stop_reason` | ✓ |
| M30 | **SMTP: `SMTPException` יורשת מ-`OSError`** (3.42) — `SMTPAuthenticationError` חייבת להיתפס *לפני* `except OSError`, אחרת סיסמה שגויה מדווחת "אין חיבור לאינטרנט". `SMTPRecipientsRefused` (הנמען היחיד סורב = חריגה, לא dict) ו-`SMTPDataError` (מכסה 5.4.5) → עברית; רשת/סיסמה/מכסה = `MailFatalError` | `email_utils.send_email` | ✓ |
| M31 | `GoogleAuthError(msg, fatal=True)`: כתובת-נמען שגויה (400) ושגיאה לא-מזוהה = `fatal=False` (תלויות בנמען); כל השאר כללי (3.42) | `google_auth` | ✓ |
| M32 | **התקדמות נשמרת מקומית** (3.42): `_on_progress` → `update_mail_campaign(..., sync=False)` אחרי כל נמען (בלי יומן סנכרון), כך ששליחה שנקטעה נסגרת כ-`interrupted` **עם** מי שכבר קיבל; `_on_finished` מציג `stop_reason` כאזהרה | `mails._on_progress`/`database.update_mail_campaign` | ✓ |
| M33 | **שליחה שנקטעה זוכרת גם את מי שלא נוסה** (3.43): `_send` כותב לדוח מראש שורת `pending` לכל יעד (`mailer.pending_rows`) לפני `start()`; `_on_progress` מחליף את שורת ה-pending; `_close_stale_campaigns` ו-`_on_finished(Exception)` הופכים `pending`→`skipped` עם סיבה (`mailer.close_pending`). בלי זה "נקטע" הכיל רק את מי שכבר טופל, ו"שלח שוב לנכשלים" לא הכיר את השאר | `mails._send`/`_on_progress`/`_close_stale_campaigns` | ✓ |
| M34 | כפתור "שלח שוב לנכשלים" מופיע לפי **תוכן הדוח** (`mailer.resendable`: failed/skipped), לא רק כש-`failed>0` — עצירה ידנית/נקטע = נכשלו 0 אבל מאות "לא נשלח" (3.43) | `mails._refresh_history` | ✓ |
| M35 | `_send` מפעיל מחדש את `btn_stop` (אחרי "עצור" הוא נשאר נעול לשליחה הבאה); `_resend_failed` נחסם כשיש שליחה פעילה **לפני** שהוא דורס נושא/גוף; קובץ מצורף שלא קיים בדיסק → אזהרה, לא שליחה בלי הקובץ (3.43) | `mails.py` | ✓ |
| M36 | קובץ מצורף: `part.add_header("Content-Disposition", "attachment", filename=…)` (RFC 2231) — השמה ישירה של מחרוזת עם שם עברי עוטפת את כל הערך ב-`=?utf-8?b?…?=` ⇒ כותרת שבורה, הנמען רואה "noname" (3.43) | `email_utils.send_email` | ✓ |

## UI לא קופא — קריאות רשת ברקע

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M9 | בטאב המיילים אין קריאה **inline** ל-`send_email`/`send_batch`/`google_auth.connect` — רק בתוך `_BgWorker`/`_SendWorker` (3.41: מייל-בדיקה הקפיא את המסך) | `mails.py` | ✓ |
| M10 | בהגדרות: `google_auth.connect` ומייל-הבדיקה רצים דרך `_BgWorker` בלבד (3.39/3.41) | `settings.py` | ✓ |

## חיבור Google — OAuth

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M11 | ה-loopback עונה 404 לבקשה בלי `code`/`error` (favicon.ico) וממשיך להמתין (`_wait_for_code` בלולאה עד `got_it`) — לא בקשה אחת בלבד (3.41) | `google_auth._OneShotHandler`/`_wait_for_code` | ✓ |
| M12 | PKCE (`code_verifier`) + אימות `state == expected_state`; בלי `refresh_token` בתשובה = שגיאה בעברית (3.39) | `google_auth.connect` | ✓ |
| M13 | `invalid_grant` ("פג או בוטל") מנקה את `SET_REFRESH` — לא להשאיר "מחובר" מטעה (3.39) | `google_auth.access_token` | ✓ |
| M14 | סדר זיהוי-לקוח: `_secret.py` → settings מסונכרנות → `google_client.json` (**הכרעת המשתמש 14/9/2026: המובנה גובר** — לא לשנות את הסדר); `import_client_file` דוחה קובץ "web" ולא-גוגל בעברית (3.41) | `google_auth.client_credentials`/`import_client_file` | ✓ |
| M15 | `google_refresh_token`/`google_email`/`google_client_id` **מסונכרנים** (הכרעת המשתמש 10/9/2026: חיבור אחד לשני המחשבים) — לא ב-`EXCLUDED_SETTINGS` | `sync.py` | ✓ |
| M16 | `_secret.py` ב-`.gitignore`; אין סוד גוגל/סיסמת-אפליקציה בקוד או בבדיקות | repo | ✓ |
| M17 | `sender_email`/`is_configured`: Google **או** SMTP; כשגוגל מחובר — `send_email` הולך ל-Gmail API ולא ל-SMTP (3.39) | `email_utils` | ✓ |

## נתונים וסנכרון

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M18 | `update_mail_campaign`: `status_ts` = **עכשיו** (לא `sent_at`); `_apply_mail_update` דוחה חותמת ישנה/שווה (`>=`) (LWW, כמו tz_update) | `database.py`/`sync.py` | ✓ |
| M19 | `_apply_mail_add` idempotent לפי guid; ה-seed שולח `sent`/`failed`/`report_json` בתוך `mail_add` עצמו | `sync.py` | ✓ |
| M20 | תבניות: LWW לפי `updated_at` בשני הצדדים (`upsert_mail_template` + `_apply_mtpl_upsert`), מחיקה **רכה** (`deleted=1`), `get_mail_templates` מסנן `deleted=0` | `database.py`/`sync.py` | ✓ |
| M21 | `_APPLIERS` מכיל `mail_add`/`mail_update`/`mtpl_upsert`; `snapshot` זורע גם `mail_campaigns` וגם `mail_templates` | `sync.py` | ✓ |
| M22 | `reset_all_data` מנקה `mail_campaigns` (היסטוריה עם כתובות של מקבלים שנמחקו) | `database.py` | ✓ |
| M23 | מיילים שנשלחו מוצגים בכרטיס המקבל (`get_mails_for_recipient` ב-`search.py`) | `search.py` | ✓ |

## מנוע הטקסט

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M24 | `build_targets`: כתובת אחת לאדם, dedupe **לא-רגיש לאותיות**, סיבת-דילוג לכל מי שלא נשלח (אין/לא תקינה/כפולה) | `mailer.build_targets` | ✓ |
| M25 | `render`: `{שם פרטי}` = החלק **השני** של `full_name` (משפחה-קודם, ראה `project-name-convention`) | `mailer.render` | ✓ |
| M26 | `html_body`: כותרת = **טבלה** + `width`/`height` **אטריבוטים** על הלוגו (בלי flex / CSS height — Qt מתעלם → לוגו ענק) (3.41) | `mailer.html_body` | ✓ |

## בדיקות

| # | אינווריאנט | מקום | לינט |
|---|---|---|---|
| M27 | `test_mail.py` מזריק `google_auth._TRANSPORT` + `_CODE_PROVIDER` ורץ על DB זמני — אפס רשת | `test_mail.py` | ✓ |
| M28 | `test_mail.py` ברשימת `TESTS` של `release.py` (נמצא חסר ב-14/9/2026 — שחרור לא הריץ אותו) | `release.py` | ✓ |

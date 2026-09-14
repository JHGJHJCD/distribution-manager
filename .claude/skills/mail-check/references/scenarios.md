# מפת זרימות + רשימת תרחישים — מסך המיילים

## א. 7 הזרימות (נקודת כניסה → מה קורה → איפה נשמר)

| # | זרימה | כניסה | מסלול | תוצאה |
|---|---|---|---|---|
| 1 | **בניית קהל** | `_set_mode` / `_add_person` / `_add_address` / `_remove_target` | `_source_recs` → `mailer.build_targets` → `_fill_table` → `_update_metrics` | `self._targets` (ok/reason), מוני-צ'יפ, `btn_send` |
| 2 | **הודעה + תצוגה מקדימה** | `subject`/`body`/`chk_header` → `_schedule_preview` | `_ctx` (`mailer.default_context(_dist_iso)`) → `render` → `html_body` | תצוגה מקדימה (Qt rich-text) |
| 3 | **תבניות** | `_load_templates` / `_tpl_selected` / `_save_template` / `_delete_template` | `db.upsert_mail_template` / `delete_mail_template` (מחיקה רכה) → op `mtpl_upsert` | `mail_templates`, מסונכרן LWW `updated_at` |
| 4 | **מייל בדיקה אליי** | `btn_test` → `_send_test` | `_validate_message` → `_BgWorker(send_email)` → `_test_done` | הודעה בלבד, בלי רשומה |
| 5 | **שליחה** | `btn_send` → `_send` | `_validate_message` → אישור → `db.add_mail_campaign` (sending) → `_SendWorker(mailer.send_batch)` → `_on_progress` → `_on_finished` → `update_mail_campaign` (done/stopped/failed) | `mail_campaigns` + `report_json`, היסטוריה, כרטיס מקבל |
| 6 | **היסטוריה / שליחה חוזרת** | `_refresh_history` / `_show_details` / `_resend_failed` | `get_mail_campaigns(limit=200)` → `_HistoryDetailDialog`; נכשלים → `_send(targets, audience)` | רשומה **חדשה** לשליחה החוזרת |
| 7 | **חיבור Google** (בהגדרות) | `btn_google_load` → `_google_load_client`; `btn_google_connect` → `_google_connect`; `_google_disconnect`; `_test_mail_settings` | `import_client_file` → settings מסונכרנות; `_BgWorker(google_auth.connect)` → refresh_token ב-settings; `disconnect` (revoke) | `google_*` settings מסונכרנות לשני המחשבים |

שכבת השליחה בפועל: `email_utils.send_email` → Gmail API (`gmail_send_raw`) כשמחובר, אחרת SMTP (`_connect`).

## ב. תרחישים — "מה קורה אם…" (ענה מהקוד; לא בטוח → בדיקה מדומה)

### קהל ויעדים
- למקבל אין מייל / מייל לא תקין / אותו מייל בשני כרטיסים → מוצג עם סיבה, לא נשלח, לא נספר פעמיים.
- כתובת חיצונית שכבר קיימת בכרטיס מקבל → נשלחת פעם אחת.
- החלפת מצב-קהל אחרי שהוספתי אנשים ידנית → מה קורה לתוספות? (`_extra`/`_added`)
- מסנן שמחזיר 0 יעדים → `btn_send` כבוי, לא קורס.
- מקבל נמחק בין בניית הרשימה לשליחה (מחשב שני) → `rec_by_id` חסר → `render` עם `fallback_name`.

### הודעה
- נושא ריק / גוף ריק → אזהרה, לא נשלח (גם בבדיקה).
- `{שם פרטי}` כשאין `first_name` → החלק השני של `full_name`; שם של מילה אחת → המילה עצמה.
- `{תאריך חלוקה}` כשאין תאריך במסך "חלוקה ורישום" → מחרוזת ריקה, לא "None".
- `{פרשה}` בשבוע בלי פרשה / pyluach חסר → ריק.
- HTML בטקסט של המשתמש (`<b>`) → מוצג כטקסט (escape), לא מפורש.
- כותרת/לוגו כבויים → בלי `cid:logo`, בלי צירוף לוגו.

### שליחה
- אין חיבור מייל בכלל → `_validate_message` עוצר עם "חבר קודם חשבון מייל".
- אמצע השליחה: נמען אחד נכשל → ממשיכים, נספר `failed`, השאר נשלחים.
- "עצור" באמצע → הנוכחי מסתיים, השאר `skipped`, סטטוס `stopped`, "שלח שוב לנכשלים" כולל את ה-skipped.
- אין אינטרנט מהנמען הראשון → כל נמען `failed` עם הודעה בעברית (לא "נשלחו 0" בשקט).
- מכסת Gmail יומית (429) → הודעה בעברית; מה עם השאר? (כל אחד `failed` בנפרד — לא עוצר אוטומטית! חשד ל-UX).
- לחיצה כפולה על "שלח" → `_worker is not None` חוסם.
- התוכנה נסגרה באמצע → בהפעלה הבאה `interrupted` (רק של המחשב הזה).
- טוקן פג באמצע אצווה → 401 → ריענון שקוף, לא כישלון.
- קובץ מצורף שנמחק מהדיסק לפני השליחה → `send_email` מדלג (`os.path.exists`) — הנמען לא יודע שהיה אמור להיות קובץ (חשד UX).

### היסטוריה וסנכרון
- שליחה במחשב A → מופיעה ב-B עם `sent`/`failed` (`mail_add` ואז `mail_update`).
- B מקבל `mail_update` לפני `mail_add` (סדר יומן) → `_apply_mail_update` על רשומה חסרה = לא עושה כלום; האם ה-`mail_add` המאוחר נושא את התוצאות? (ב-seed כן; ביומן שוטף — **לא**, חשד).
- תבנית נערכה בשני המחשבים → LWW לפי `updated_at`.
- תבנית נמחקה ב-A ונערכה ב-B אחר כך → העריכה מנצחת (deleted=0) — מכוון.
- "אפס נתונים" → היסטוריית מיילים נמחקת; תבניות נשארות.
- כרטיס מקבל: מייל שנשלח אליו מופיע עם סטטוס/שגיאה.

### חיבור Google
- אין זיהוי-לקוח → כפתור נעול + הסבר וקישור; שליחה נופלת ל-SMTP.
- קובץ JSON מסוג web / לא של גוגל / לא JSON → הודעה בעברית, לא נשמר.
- המשתמש ביטל בדפדפן → "ההתחברות בוטלה".
- הדפדפן שלח favicon לפני הקוד → ממשיכים להמתין (3.41).
- גוגל לא החזירה refresh_token (חיבור חוזר בלי prompt=consent) → הודעה בעברית.
- refresh_token בוטל בצד גוגל → "פג" + ניתוק + הכפתור חוזר ל"התחבר".
- נטפרי חוסם `accounts.google.com`/`gmail.googleapis.com` → 418 → הודעת נטפרי, לא "שגיאה לא ידועה".
- התנתקות במחשב A → B מאבד את החיבור בסנכרון (מכוון: חיבור אחד).
- `_secret.py` קיים ב-EXE אבל המשתמש טען קובץ אחר בהגדרות → `_secret` מנצח (סדר M14) — האם זה מה שהמשתמש מצפה? (חשד UX).

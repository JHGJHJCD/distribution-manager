---
name: mail-check
description: >-
  Bug-hunting and scenario-verification skill for the מיילים (recipient e-mail)
  logic of the מנהל חלוקה app — tabs/mails.py, utils/mailer.py,
  utils/google_auth.py, utils/email_utils.py (send path), the Google card in
  tabs/settings.py and the mail_* DB/sync ops. Use this WHENEVER a task touches
  those files, sending / resending / test-mail flows, Google OAuth connect or
  disconnect, mail templates, the mail history, or when the user says
  "בדוק מיילים", "סקירת באגים במיילים", "check the mail logic", or asks why a
  mail send / Google connection / template behaved oddly. It carries the safety
  fences (no real sending, no real Google calls, secrets never into git), the
  invariants the screen must keep, the scenario checklist, the mocked-transport
  test recipe, and a one-command checker (`scripts/check_mail.py`) that lints the
  invariants and runs the tests. Load it BEFORE reading the code so you don't
  reintroduce a bug already fixed in v3.39–v3.41.
---

# mail-check — בדיקת לוגיקת המיילים

יהודה (המשתמש) **לא מתכנת**. עבוד ושחרר, אל תסביר צעדים טכניים; סיכום קצר בעברית פשוטה בסוף.
טען גם את `manhal-haluka` (Python 3.12, שחרור) — `references/pitfalls.md` שלו מתעד את
המלכודות ההיסטוריות. הסקיל הזה מרכז את **מה לבדוק ואיך להוכיח** במסך המיילים.
מבנה זהה לאח הגדול `tzintuk-check` — מי שמכיר אותו מכיר את זה.

## 0. הפעלה מהירה — הבודק האוטומטי

```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe .claude\skills\mail-check\scripts\check_mail.py
```

עושה שני דברים: (א) **לינט אינווריאנטים** — בדיקות סטטיות על הקוד שמוודאות שאף גדר
בטיחות/כלל-עומק לא נשבר (ראה `references/invariants.md`); (ב) מריץ `test_mail.py`
ו-`test_sync.py` ב-Python 3.12. `--lint-only` / `--tests-only` לפי הצורך. יציאה ≠ 0 = יש בעיה.
הרץ אותו **לפני** שמתחילים (baseline) ו**אחרי** כל תיקון.

## 1. 🚨 גדרות בטיחות — לפני כל דבר אחר

1. **אסור לשלוח מייל באמת.** שום בדיקה/סקריפט לא קורא ל-`email_utils.send_email` /
   `google_auth.gmail_send_raw` / `smtplib` מול שרת אמיתי. כל תרחיש רץ עם
   `google_auth._TRANSPORT` מדומה (Gmail API) או עם `email_utils._connect` מוחלף (SMTP).
   הפרה = מייל אמיתי ל-500 מקבלים מחשבון הקופה.
2. **אסור לגעת בחשבון Google האמיתי.** `connect`/`disconnect`/`access_token` רק עם
   `_CODE_PROVIDER` + `_TRANSPORT` מוזרקים. לא לפתוח דפדפן, לא לבטל את ה-refresh_token
   של המשתמש (ה-DB האמיתי ב-`%APPDATA%\ManhalHaluka` — הבדיקות על DB זמני **בלבד**).
3. **סודות לא נכנסים ל-git.** `utils/_secret.py` ב-`.gitignore`; `GOOGLE_CLIENT_SECRET`,
   `google_refresh_token`, סיסמת-אפליקציה — לעולם לא בקוד, בבדיקות, בצילומים או בסקיל.
   ערך שנראה כמו סוד בפלט/לוג → למחוק לפני commit.
4. **צילומי מסך של המסך הזה לא נקראים לצ'אט** (`Read` על PNG הרג צ'אטים דרך נטפרי; קרה
   גם בצ'אט שבנה את המסך הזה). אימות צילום רק דרך `gemini_task.py -f <png>`.
5. בדיקות על DB זמני (`use_machine` ב-`test_mail.py`); אין `init_db()` על ה-DB האמיתי.

## 2. איך עובדים (סדר קבוע)

1. **baseline:** הרץ את הבודק. אם הוא כבר אדום — זה הממצא הראשון.
2. **מפה לפי זרימות**, לא לפי סדר הקובץ — `references/scenarios.md` §א (7 זרימות עם נקודות
   הכניסה). קרא רק את הזרימה שבמיקוד.
3. **עבור על רשימת התרחישים** (`references/scenarios.md` §ב) ועל **האינווריאנטים**
   (`references/invariants.md`). לכל "מה קורה אם…" ענה **מהקוד**; "לא בטוח" → בדיקה מדומה.
4. **הוכח לפני שנוגעים:** באג = בדיקה שנכשלת ב-`test_mail.py` (סעיף ממוספר חדש, מתכון
   ב-`references/test-harness.md`). **אין בדיקה שנכשלת = אין באג** — רק חשד ל-`NEXT_TASK.md`.
5. **תקן לפי סדר:** שלמות נתונים → כללים עסקיים → יציבות → UX → איכות קוד. סיבה, לא תסמין.
   מסתבך? עצור ותכנן מחדש, אל תתקן תוך ריצה.
6. הרץ את הבודק עד ירוק, ואז `test_all.py`.
7. נגעת ב-UI → צילום לפי `visual-check` (`dev/_shot_mails.py` כתבנית), אימות רק דרך Gemini.

## 3. Definition of Done (לא אופציה)

- כל באג שנמצא → **מלכודת** ב-`manhal-haluka/references/pitfalls.md` (מה קרה, למה, הכלל)
  **וגם** שורה ב-`references/invariants.md` כאן אם הכלל ניתן לבדיקה סטטית — ואז הוסף
  את הבדיקה ל-`scripts/check_mail.py` (`LINTS`). כך הבאג לא חוזר בשקט.
- למדת משהו על Gmail API / OAuth / נטפרי מול גוגל → מקטע "מיילים" ב-`CLAUDE.md` + זיכרון
  `reference-netfree` אם זה חסימה.
- `CLAUDE.md`: שורת `vX.YZ` תחת "מיילים למקבלים"; `NEXT_TASK.md`: חשדות לא מוכחים.
- שחרור אוטומטי דרך `manhal-haluka` (`release.py ship …`) **רק אם כל הבדיקות עברו**. בלי קרדיט Claude ב-commit.

## 4. סיכום ליהודה

שורה לכל באג (מה המפעיל היה רואה ← מה קורה עכשיו) · חשדות בלי הוכחה ומה צריך כדי להכריע ·
לכל היותר **שאלה ממוקדת אחת** שדורשת הכרעה שלו (UX/כלל עסקי).

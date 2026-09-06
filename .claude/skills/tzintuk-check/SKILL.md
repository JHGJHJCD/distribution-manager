---
name: tzintuk-check
description: >-
  Bug-hunting and scenario-verification skill for the צינתוקים (Yemot voice-call)
  logic of the מנהל חלוקה app — tabs/tzintukim.py, utils/yemot.py,
  utils/call_history.py, utils/tts.py and the tzintuk_* DB/sync ops. Use this
  WHENEVER a task touches those files, sending/scheduling/tracking campaigns,
  the 77 survey, smart-hour dispatch, callback tracking, or when the user says
  "בדוק צינתוקים", "סקירת באגים בצינתוקים", "check the tzintuk logic", or asks
  why a campaign/schedule/tracking behaved oddly. It carries the safety fences
  (no real dialing, no root ext.ini writes), the list of invariants the screen
  must keep, the scenario checklist, the mocked-transport test recipe, and a
  one-command checker (`scripts/check_tzintuk.py`) that lints the invariants and
  runs the tests. Load it BEFORE reading the code so you don't reintroduce a bug
  that was already fixed in v3.13–v3.20.
---

# tzintuk-check — בדיקת לוגיקת הצינתוקים

יהודה (המשתמש) **לא מתכנת**. עבוד ושחרר, אל תסביר צעדים טכניים; סיכום קצר בעברית פשוטה בסוף.
טען גם את `manhal-haluka` (Python 3.12, שחרור) — `references/pitfalls.md` שלו מתעד את
רוב הבאגים ההיסטוריים של המסך הזה. הסקיל הזה מרכז את **מה לבדוק ואיך להוכיח**.

## 0. הפעלה מהירה — הבודק האוטומטי

```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe .claude\skills\tzintuk-check\scripts\check_tzintuk.py
```

עושה שני דברים: (א) **לינט אינווריאנטים** — בדיקות סטטיות על הקוד שמוודאות שאף גדר
בטיחות/כלל-עומק לא נשבר (ראה `references/invariants.md`); (ב) מריץ `test_tzintuk.py`
ו-`test_sync.py` ב-Python 3.12. `--lint-only` / `--tests-only` לפי הצורך. יציאה ≠ 0 = יש בעיה.
הרץ אותו **לפני** שמתחילים (baseline) ו**אחרי** כל תיקון.

## 1. 🚨 גדרות בטיחות — לפני כל דבר אחר

1. **אסור לחייג באמת.** שום בדיקה/סקריפט לא קורא ל-`RunCampaign`/`RunTzintuk`/`ScheduleCampaign`/`UploadPhoneList`
   מול השרת. כל תרחיש רץ עם `yemot._TRANSPORT` מדומה. הפרה = צלצול ל-360+ זכאים.
2. **אסור לכתוב לשורש הקו** (`ext.ini` של השורש) — לא מהקוד ולא ידנית (תקרית 3/9/2026).
   `yemot.CALLBACK_ENABLED` נשאר `False`.
3. **MCP `pitron-ivr` — קריאה בלבד** (list/get/read/download) לאימות עובדות. שום `run_*`/`schedule_*`/`upload_*`/`write_*`/`execute_*`.
4. **צילומי מסך של המסך הזה לא נקראים לצ'אט** (`Read` על PNG הרג 3 צ'אטים דרך נטפרי).
   אימות צילום רק דרך `gemini_task.py -f <png>`.
5. בדיקות על DB זמני; `call_history.cache_path` מופנה לתיקייה זמנית **בראש הקובץ**.

## 2. איך עובדים (סדר קבוע)

1. **baseline:** הרץ את הבודק. אם הוא כבר אדום — זה הממצא הראשון.
2. **מפה לפי זרימות**, לא לפי סדר הקובץ — `references/scenarios.md` §א (9 זרימות עם נקודות הכניסה).
   קרא רק את הזרימה שבמיקוד; `tzintukim.py` הוא ~3100 שורות.
3. **עבור על רשימת התרחישים** (`references/scenarios.md` §ב) ועל **האינווריאנטים**
   (`references/invariants.md`). לכל "מה קורה אם…" ענה **מהקוד**; "לא בטוח" → בדיקה מדומה.
4. **הוכח לפני שנוגעים:** באג = בדיקה שנכשלת ב-`test_tzintuk.py` (סעיף ממוספר חדש, מתכון
   ב-`references/test-harness.md`). **אין בדיקה שנכשלת = אין באג** — רק חשד ל-`NEXT_TASK.md`.
5. **תקן לפי סדר:** שלמות נתונים → כללים עסקיים → יציבות → UX → איכות קוד. סיבה, לא תסמין.
   מסתבך? עצור ותכנן מחדש, אל תתקן תוך ריצה.
6. הרץ את הבודק עד ירוק, ואז `test_all.py`.
7. נגעת ב-UI → צילום לפי `visual-check` (`dev/_shot_tzintuk.py` כתבנית), אימות רק דרך Gemini.

## 3. Definition of Done (לא אופציה)

- כל באג שנמצא → **מלכודת** ב-`manhal-haluka/references/pitfalls.md` (מה קרה, למה, הכלל)
  **וגם** שורה ב-`references/invariants.md` כאן אם הכלל ניתן לבדיקה סטטית — ואז הוסף
  את הבדיקה ל-`scripts/check_tzintuk.py` (`LINTS`). כך הבאג לא חוזר בשקט.
- למדת משהו על ה-API/הקו של ימות → הסקיל התחומי (`yemot-*`).
- `CLAUDE.md`: שורת `vX.YZ` תחת "צינתוקים"; `NEXT_TASK.md`: חשדות לא מוכחים.
- שחרור אוטומטי דרך `manhal-haluka` (`release.py ship …`) **רק אם כל הבדיקות עברו**. בלי קרדיט Claude ב-commit.

## 4. סיכום ליהודה

שורה לכל באג (מה המפעיל היה רואה ← מה קורה עכשיו) · חשדות בלי הוכחה ומה צריך כדי להכריע ·
לכל היותר **שאלה ממוקדת אחת** שדורשת הכרעה שלו (UX/כלל עסקי).

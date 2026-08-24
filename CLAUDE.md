# CLAUDE.md

הנחיות ל-Claude Code בעבודה על מאגר זה. סטטוס שוטף ("איפה עצרנו") — ב-`NEXT_TASK.md`, לא כאן.

> תחזוקה עצמית: בשינוי מבני משמעותי (לשונית/פיצ'ר גדול/שינוי בבנייה-שחרור) — עדכן קובץ זה באותה הזדמנות. סטטוס זמני → `NEXT_TASK.md`.

## עקרונות עבודה
- **המשתמש לא מתכנת** — לעבוד ולשחרר, לא להסביר צעדים טכניים. הערת-שחרור קצרה בעברית פשוטה בסוף.
- אל תשבור תאימות לאחור; אל תשנה שמות עמודות/שדות ב-DB בלי מיגרציה.
- שמור RTL מלא ופשטות למשתמש בכל שינוי UI.
- לפני מחיקת קוד — ודא שאינו בשימוש.
- כשאפשר לאמת — אמת בעצמך (בדיקה/צילום מסך אמיתי), אל תבקש מהמשתמש. **אימות = העיקרון החשוב ביותר:** אם יש דרך לסגור לולאת-משוב לבד (בדיקות/הרצה/צילום), השתמש בה עד שהתוצאה נכונה.
- **משימה מורכבת → תכנן קודם (plan mode):** השקע בתכנון לפני מימוש. אם משהו משתבש באמצע — חזור לתכנון מחדש, אל תתקן תוך כדי ריצה. במקרה גבולי או UX — שאל שאלה ממוקדת אחת לפני שמתחילים.
- **אל תסתפק בפתרון הראשון:** אחרי מימוש בינוני — שקול "לזרוק ולממש את הפתרון האלגנטי" מחדש עם מה שלמדת. אחרי שינוי — עבור על הקוד המשתנה לאיתור שכפול/סיבוך/חוסר-יעילות (`/simplify`).
- **הנדסה מצטברת:** בכל פעם שטעיתי או שהמשתמש תיקן אותי — הוסף את הכלל ל-CLAUDE.md (או למלכודות/זיכרון) כדי לא לחזור על הטעות.
- **הקשר נקי:** במשימות רחבות/סריקה — האצל לסוכני-משנה (subagents) כדי לשמור על מיקוד, במקום לגרור הכל לשיחה הראשית.

## Architecture Rules
- העדף שימוש בקוד קיים על פני כתיבת חדש; אל תשכפל לוגיקה — חלץ helper משותף.
- לוגיקה עסקית מחוץ ל-UI כשאפשר (`scoring.py`/`selection.py`/`database.py` — מודולים טהורים), הלשוניות רק מציגות.
- שמור על הפרדה קיימת: `scoring` = ניקוד, `selection` = מי-מקבל (gate/סדר/רזרבה), `database` = נתונים, `tabs/` = תצוגה, `utils/` = שירותים. **כלל בחירת-מקבלים חדש? ל-`selection.py` + טסט ב-`test_selection.py`, לא לתוך לשונית.**

## סדר עדיפויות בהתנגשות
**שלמות נתונים → כללים עסקיים → יציבות → חוויית משתמש → איכות קוד.** כששניים מתנגשים, המוקדם מנצח.

## לפני סיום משימה (Before completing a task)
- הרץ את הבדיקות הרלוונטיות (`python test_X.py` הנוגעים לשינוי).
- אם נגעת ב-UI — אמת ויזואלית (צילום מסך אמיתי / הרצה), לא רק שהקוד רץ.
- בשינוי מבני — עדכן `CLAUDE.md`; בשינוי סטטוס — עדכן `NEXT_TASK.md`.

**Definition of Done:** השינוי עובד ואומת בפועל (לא רק "לא קרס"), הבדיקות הרלוונטיות עוברות, לא נשברה תאימות/שלמות נתונים, והתיעוד עודכן אם צריך.

## ⚠️ מלכודות ידועות (Known Pitfalls)
- **Python:** בנה/בדוק רק עם `C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`. ה-`python` שב-PATH הוא 3.14 וחסר PyQt6/openpyxl/qt-material.
- **גופן:** Segoe UI בלבד. **אל** תחזיר Rubik (רונדר מטושטש) ואל תוסיף `AA_EnableHighDpiScaling` (הוסר ב-PyQt6).
- **אל תשתמש ב-`QGraphicsDropShadowEffect`** על כרטיס בתוך layout גמיש — שובר את משא-ומתן הגובה ומכווץ תוכן.
- **openpyxl:** `get_column_letter(col)` בלבד — `.column_letter` קורס על MergedCell.
- **הדפסה:** `QTextDocument` מתעלם מ-`dir` → עמודות RTL נכתבות בסדר הפוך ידנית.
- **צילומי מסך עברית:** להריץ **בלי** offscreen (offscreen מרנדר ריבועים) — עם `WA_DontShowOnScreen` + `grab()`.
- **בדיקות:** קובצי `test_*.py` קוראים `sys.exit` ברמת המודול → pytest קורס באיסוף. הרץ כל אחד `python test_X.py`.
- **דליפת הגדרות:** סקריפט שמריץ `init_db()` על DB אמיתי עלול לדלוף — נקה `DELETE FROM settings WHERE key LIKE 'need_w_%'`.

## עץ הפרויקט
```
main.py            # tab_specs, splash, single-instance, DPI, יציאה
database.py         # SQLite + re-export של scoring/selection
scoring.py          # מודול טהור: annotate_need_scores, NEED_FACTORS
selection.py        # מודול טהור: מקור-אמת יחיד ל"מי מקבל" (gate/ranking/roles/reserve)
widgets.py          # ProductsEditor ועוד
styles.py · version.py
tabs/
  group_update.py   # "חלוקה ורישום" (לשונית פתיחה, שני שלבים: הכנה/רישום)
  recipients.py     # CRUD מקבלים
  search.py         # "חיפוש מהיר" מאוחד
  distributions.py  # "חלוקות קודמות" (אצוות; באזור "אנשים" מאז v2.60)
  settings.py       # סיסמה/עדכון/משקלים/SMTP/גודל-טקסט/סף התראות
  review.py         # בדיקת כפילויות (דיאלוג בלבד)
  summary.py        # לא מחובר — אל תסתמך עליו
  (one_time.py הוסר ב-v2.60 — OneTimePickerDialog ב-group_update מחליף אותו)
utils/
  email_utils.py · excel_utils.py   # זרימת מתנדבים
  print_view.py · updater.py · backup.py · feedback.py · ui.py  (tour.py הוסר ב-v2.60)
dev/                # probe/screenshot/benchmark/stress/create_icon
test_*.py           # בשורש
```

## מה הפרויקט
אפליקציית Windows בעברית (RTL מלא) לניהול חלוקת מצרכים ל"קופה של צדקה הר יונה" (נוף הגליל), ~500 מקבלים. המנהל מפעיל **מתנדבים** שמחלקים בנקודה קבועה; המתנדבים לא נוגעים בתוכנה — מקבלים רשימה במייל, ממלאים מי הגיע, והקובץ מיובא חזרה.

## Tech Stack, הרצה ובנייה
- Python 3.12, PyQt6 6.11, SQLite, openpyxl, qt-material (theme light_teal — "ירוק רגוע" v2.60: primary ‎#0f9d78‎/#0f766e, רקע ‎#f4faf7‎, כתום ‎#f59e0b‎ לפעולה משנית). מייל דרך `smtplib`/`email.mime` (stdlib בלבד).
- אין שרת — EXE יחיד (PyInstaller, `מנהל_חלוקה.spec`), DB מקומי.
```
python main.py                                              # הפעלה (סיסמה: 1234)
python -m PyInstaller --noconfirm --clean מנהל_חלוקה.spec   # → dist/מנהל_חלוקה.exe
```
אם ה-EXE נעול (WinError 5) לפני בנייה: `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"`.

## נתונים ואבטחה
- DB + גיבויים ב-`%APPDATA%\ManhalHaluka\` (data.db, backups/) — נפרד מה-EXE, שורד עדכונים, מהגר DB ישן אוטומטית.
- סיסמה מגובבת PBKDF2 (`database.verify_password/set_password`), ברירת מחדל `1234`.
- גיבוי אוטומטי בהפעלה ולפני כל פעולה הרסנית (Online Backup API — הגיבוי הוא עותק). שחזור מאמת שהקובץ DB תקין לפני דריסה.

## לשוניות (v2.60: 3 אזורים)
מוגדרות ב-`main.py` `_build_tabs`: **חלוקה** (מסך "חלוקה ורישום" ישירות, בלי תת-לשוניות) · **אנשים** (כל המקבלים · חיפוש מהיר · חלוקות קודמות) · **הגדרות**. אזור "אנשים" הוא `QTabWidget` פנימי עם property `subtabs` (עיצוב פיל-בהיר ב-`styles.py`); כל לשונית-תוכן ("עלה") שומרת את ה-attribute וה-objectName `tab_<key>` שלה — הסיור/בדיקות/צילומים מאתרים לפי מפתח, לא לפי מיקום. ניווט בין לשוניות מקוננות: `MainWindow.navigate_to_tab(widget)`; העלה המוצג: `_current_leaf()`; רשימת כל העלים: `_leaf_tabs`. רענון-עצל לפי `_needs_refresh` על העלים (מטופל ב-`_show_leaf`). `tab_order` נשמר רק ברמת 3 האזורים.
- **`group_update.py` — "חלוקה ורישום"** (לשונית פתיחה, מיזוג weekly+group). **אין יותר עורך מוצרים** — במקומו שדות `products_spin` ("מוצרים זמינים") + `reserve_spin` ("רזרבה") שהם מקור-האמת (settings `available_products`/`reserve_count`) + הערה כללית (נשמרת פעם אחת ברמת האצווה, `what_dist`=""). חיווי חי `lbl_leftover`. **פישוט v2.58 (הכרעות המשתמש 08/2026):** חד-פעמיים הם חלק מכל חלוקה → מוצרים/רזרבה/חיווי נשארים גלויים תמיד; שני אזורים מתקפלים `_CollapsibleCard` סגורים כברירת מחדל — "מצבי חלוקה מתקדמים" (`adv_section`: mode_combo+סמן מובילים+הגדר סינון; נפתח אוטומטית בבנייה אם mode≠schedule או סינון פעיל, פתיחה-בלבד) ו"שליחה למתנדב במייל" (`vol_section`; הקליטה האוטומטית רצה ברקע גם כשסגור). הדפסה = הפעולה הראשית. **בחירת חד-פעמיים במסך:** כפתור "בחר חד-פעמיים" (`btn_pick_onetime`) → `OneTimePickerDialog` (תצוגה בלבד על הליבה הקיימת: `get_one_time_list`+`compute_suggested_n`+`assign_roles`; מומלצים מסומנים מראש) → `add_one_time_picks`. **שם אוטומטי:** `_effective_dist_name` — שם ריק בשבועי רגיל ← "חלוקה שבועית DD/MM/YYYY" (נכתב לשדה, לא נדחף להיסטוריה — `_push_name_history`, מנוקה אחרי שמירה); במצב מיוחד (`_special_active`) שם עדיין חובה. **שער `_one_time_gate_ok`:** נשאר בדיקה-טהורה (הבדיקות קוראות לו ישירות — אסור לפתוח בו דיאלוג); העוטף `_ensure_one_time_picks` (בו משתמשים הדפסה/PDF/אקסל) פותח את חלון הבחירה במקום ניווט ללשונית "חד פעמי". חיפוש מהיר מסנן את רשימת השבוע (`db.filter_recipients`). סימון ב-`_checked_ids` (שורד סינון) + `_seen_ids`. **שני שלבים מפורשים (v2.60, `_stage`/`_set_stage`/`_apply_stage`):** שלב "הכנה" בלי עמודת צ'קבוקסים בכלל; כפתור כתום "רישום מי קיבל" עובר לשלב רישום שמתחיל ריק — מסמנים מי הגיע. **בשלב הרישום, מי שלא סומן נרשם מפורשות כ"לא הגיע" (`received=0`)** — שינוי כלל v2.60 (פותר #yjcny), מזין את התראות אי-ההגעה (סף רצוף מתכוונן בהגדרות, ברירת מחדל 3; תג ברשימה + בכרטיס מקבל). מצב "לפי ניקוד" = `db.get_regulars_scored` (קבועים בלבד; חד-פעמיים רק ב-`_extra_ids`). רישום → `bulk_add_distributions(..., dist_name, general_note)`. כפתור **"שמור PDF"** (`_export_pdf`) לצד "הדפסה לחלוקה" — `print_view.export_distribution_pdf` מרנדר את אותו HTML ל-PDF בתיקיית הורדות ופותח אוטומטית (`os.startfile`), בלי מדפסת. combos עם `_style_completer` — מתקין `QListView` מעוצב כ-popup דרך `comp.setPopup()` (הקריאה ל-`popup()` בזמן build מחזירה None). זרימת מתנדבים: `_dispatch_volunteer_email`/`_import_volunteer_results`.
  עיצוב (v2.37+): כרטיסים לבנים (`_make_card`/`_field`) על רקע `#f5f7fb`, כפתורים `_BTN_PRIMARY/_SUCCESS/_DANGER/_GHOST`, אייקוני-קו (`utils.ui.line_icon`), סרגל פעולות תחתון קבוע. כרטיסי פרטים+מוצרים+מתנדב עטופים ב-`QScrollArea` פנימי (`top_scroll`) כך שרשימת המקבלים (`list_card`, stretch=1) מקבלת את רוב הגובה — ויזואלי בלבד.
- **`recipients.py`** — CRUD מקבלים + דיאלוג, סינון עדיפות. כפתור "בדיקת כפילויות" → `review.py` כדיאלוג. **שדה "תדירות" מוצג רק כשהעדיפות = "קבוע"** (`_toggle_frequency_row`, #j6czs) עם 3 אפשרויות בלבד (שבועי/דו-שבועי/חודשי, בלי ריק #fw5s2). התדירות ה**נשמרת** נגזרת מהעדיפות (`_effective_frequency`): קבוע→הלוח שנבחר · ראשונה/שנייה→`חד-פעמי` · ללא/בירור→`""`.
- **`one_time.py`** — חלוקת עדיפות לחד-פעמיים: **מציג רק מועמדים** (עדיפות 3/2, `in_distribution`). "מוצרים זמינים"/"רזרבה" **נקראים מ-`group_update`** (settings `available_products`/`reserve_count`) ומוצגים ב-`lbl_products_info` (בלי שדות עריכה משלו); `_calc_suggestion` וה-refresh מסמנים אוטומטית מהמספר המשותף. לחיצה על שם → פירוט ניקוד (`utils.ui.show_score_breakdown`, RTL). `compute_suggested_n` צורך קבועים קודם.
- **`search.py`** — "חיפוש מהיר" מאוחד. רשימה → כרטיס-פרופיל HTML + היסטוריה. `HighlightDelegate`, `BadgeDelegate`, ייצוא, `print_recipient_card`.
- **`distributions.py`** — "חלוקות": שורה לכל אצווה מ-`dist_batches`. לחיצה כפולה → `BatchDetailsDialog`, מחיקה `db.delete_batch`.
- **`settings.py`** — סיסמה, עדכון, משקלי ניקוד, גיבויים, איפוס, פאנל "מייל למתנדבים" (SMTP), פריסת 2 טורים.

## זרימת המתנדבים (`utils/email_utils.py` + `utils/excel_utils.py`)
- **שליחה:** `export_volunteer_checklist_to_excel` — אקסל מינימלי, עמודה מוסתרת `id` להתאמה, גיליון `meta` מוסתר, עמודת "הגיע?" עם DataValidation "כן,לא" וברירת מחדל "כן" (המתנדב רק מבטל מי שלא הגיע). `send_email` — multipart + לוגו inline (cid), STARTTLS.
- **ייבוא:** `import_volunteer_checklist` מתאים לפי id המוסתר (fallback לשם), `received = not (ריק/"לא")` — ייבוא ישיר להיסטוריה.
- SMTP דורש **App Password של Gmail** (myaccount.google.com/apppasswords, מצריך 2FA) שמזין המשתמש בהגדרות.
- כל ייצואי האקסל → תיקיית **הורדות** (`_downloads_dir`). לניקוי תא בטסט: `ws.cell(r,c).value = None`.

## עדיפות וניקוד צורך — `selection.py` (מקור-אמת יחיד)
כל שאלת "מי מקבל, באיזה סדר, ולמה" עוברת דרך `selection.py` (טהור, בלי DB/Qt). הלשוניות ו-`database.py` רק צורכים אותו. ארבעת הכללים העסקיים (הכריע המפעיל, 07/2026) — כל אחד ומקומו בקוד:
1. **עדיפות מול ניקוד** — עדיפות (3/2) היא **שער כניסה** בלבד (`is_one_time_candidate`). *איך* ממיינים תלוי במצב:
   - **חלוקת עדיפות חד-פעמי** (`selection.rank_one_time_priority`, דרך `db.get_one_time_list`): עדיפות **גוברת** — כל ראשונה(3) לפני כל שנייה(2), ניקוד ממיין רק **בתוך** דרגה.
   - **מצב "קבועים לפי ניקוד"** (`selection.rank_by_need`, דרך `db.get_scored_all`/`get_regulars_scored`): עדיפות רק שער; הסדר לפי **ניקוד בלבד** — שנייה עם ניקוד גבוה יכולה להקדים ראשונה נמוכה.
2. **קבועים מול חד-פעמיים** — בורר "מצב חלוקה לקבועים" עם 4 מצבים: `schedule` (קבועים קודם לפי לוח; `compute_suggested_n` מנכה מהמלאי **רק את הקבועים שבתור השבוע** = `len(get_weekly_list())`, לא כל הקבועים — דו-שבועי/חודשי שלא בתור לא גוזל מנה) / `scored` (מתחרים יחד בניקוד) / `none` / **`filter`** (סינון מותאם, ראה למטה). `compute_suggested_n` מחזיר (0,0) בכל מצב שאינו `schedule` — כלומר `filter` לא שומר מנות לחד-פעמיים.
   - **מצב `filter` (סינון רחב, #vq4fx)** — מתעלם מעדיפות/תדירות לחלוטין: בוחר מ**כל המקבלים הפעילים** את מי שעונה על ספי-מספר מתכווננים (`selection.FILTER_FIELDS`: `children_total`/`income`/`per_soul`, כל אחד עם min/max). `selection.filter_by_criteria`/`matches_criteria` (AND בין שדות; **חסר נתון בשדה מסונן = לא נכלל**, שער-קשיח, לא כמו ניקוד). `selection.to_number` מפרסר שדות-טקסט ("4,500 ₪"→4500). קריטריונים נשמרים ב-settings `dist_filter_criteria` (JSON) דרך `db.get/set_filter_criteria`; הרשימה דרך `db.get_filtered_list` (מדורגת לפי ניקוד). ב-`group_update`: כפתור "הגדר סינון" (מוצג רק במצב זה) → `FilterCriteriaDialog`; כניסה למצב בלי קריטריונים פותחת אותו אוטומטית. **אזור אינו קריטריון** (הכרעת המשתמש 08/2026).
3. **רזרבה = רשימת המתנה** — `selection.assign_roles` מסמן `_role` (main/reserve/out). רזרבה **לא נרשמת** כברירת מחדל (`recorded_by_default`→False): מגיעה ללא-סימון ב-`group_update` (`refresh` מדלג על `_reserve_ids`), אבל **כן מודפסת** כמקטע נפרד (`_get_export_rows` מוסיף רזרבה גם ללא סימון). נרשמת רק אם המפעיל מפעיל אותה במקום מי שלא הגיע.
4. **חוסר נתונים → תחתית התור** — ב-`scoring.annotate_need_scores` גורם **חסר תורם 0 נק'** (לא ניטרלי 0.5), גם ל-"high" וגם ל-"low". נתון חסר רק פוגע, לעולם לא מזכה — משפחה עם נתונים חסרים שוקעת לתחתית.
- קוד מקור (מאקסל): 4=קבוע→שבועי · 3=ראשונה · 2=שנייה (3/2 = `PRIORITY_TIERS`) · 1/0/בירור/**ריק = נתונים בלבד**. נשמר כ-`priority`+`priority_raw`. **המספרים לא מוצגים** — רק תוויות עברית (`PRIORITY_BADGES` ב-`utils/ui.py`).
- `scoring.annotate_need_scores`: 0–100 = שקלול 6 גורמים (`NEED_FACTORS`), משקלים מתכווננים (`need_w_*`, סכום 100). `_score_parts` לפירוט בלחיצה. נורמליזציה **ליניארית יחסית לרשימה** (min/max) — הכרעת המשתמש: חצי-הוצאה=חצי-ניקוד, וחריגים אמיתיים נספרים (המחיר: חריג/טעות-קלדה אחד משטח גורם לכולם — מודע, לא מתקנים בנוסחה).
- **שובר-שוויון בדירוג** (`selection.rank_by_need`/`rank_one_time_priority`): ניקוד → **ותק (הכי הרבה המתנה, `days_since`)** → שם. הכרעת המשתמש: שוויון-ניקוד מוכרע למי שממתין הכי הרבה, לא לפי אלף-בית.
- **ותק (`db.recency_days`)**: ימים מאז חלוקה אחרונה; מי שמעולם לא קיבל — מאז **הרישום** (`start_date`→`created_at`), לא אפוק-2000. תאריך עתידי מתאפס ל-0.
- `db.delete_distribution(id)` — מחיקת רישום חלוקה בודד (מלשונית "חיפוש מהיר"), לרישומים ישנים ללא `batch_id`.
- הדפסת רזרבה: `utils/print_view.py` מפצל לפי `_reserve` ל"חלוקה"/"רזרבה — לפי סדר עדיפות".

## כללים עסקיים קריטיים
- **נפשות בייבוא** = "ילדים בבית" + מבוגרים במשק הבית. מבוגרים נגזר ממצב אישי (`_adults_in_household` ב-`utils/excel_utils.py`): חד-הורי (גרוש/אלמן/רווק/פרוד — עם נרמול אותיות סופיות) = 1, נשוי/ריק/לא ידוע = 2.
- חד-פעמיים לא ברשימה השבועית. שם-חלוקה חובה לפני הדפסה/שליחה (למשל "חלוקת פסח").
- `calculate_next_dist`: שבועי≈+7, דו-שבועי≈+13, חודשי≈+29 — תמיד רביעי הקרוב. `get_weekly_list` מבטיח שרביעי הקרוב נכלל בכל יום בשבוע. **קבוע שטרם קיבל** (`last_distribution` ריק) = חייב **מיד** ברביעי הקרוב (כולל היום אם היום רביעי), לא שבוע קדימה — אחרת קבוע שנוסף ביום החלוקה נעלם מהרשימה (bug #pv59q). `get_weekly_list` גם מתקן-עצמית `next_distribution` שנשמר שבוע קדימה.
- מחיקת מקבל עם היסטוריה → `ValueError` (שנה סטטוס / מחיקה כפויה).
- הדפסה (`utils/print_view.py`): טבלה RTL (עמודות בסדר הפוך), לוגו + "קופה של צדקה הר יונה", ☐ בעמודת ביצוע, כיווץ גופן 11→6 למינימום דפים, ערכים דרך `html.escape`.

## עדכון אוטומטי (`utils/updater.py`) ושחרור
- repo `JHGJHJCD/distribution-manager`. בודק `releases/latest`, מוריד `Manhal-Haluka.exe`, מאמת שלמות, מחליף EXE רץ ומפעיל מחדש. בדיקה בהפעלה + כפתור בהגדרות.
- **משמעת שחרור:** `version.py` `APP_VERSION` → בנה → `cp dist/מנהל_חלוקה.exe dist/Manhal-Haluka.exe` (asset ASCII) → `git add/commit/push` → `gh release create vX.Y dist/Manhal-Haluka.exe --latest`.
- **שחרור אוטומטי (הכרעת המשתמש 24/08/2026):** אחרי כל שינוי קוד שאומת (בדיקות + אימות ויזואלי) — לשחרר לגיטהאב **בלי לחכות לבקשה**: bump גרסה, build, commit/push, release. לא לשחרר קוד שלא אומת.
- **`gh` לא ב-PATH:** `C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe` — הרץ `& $gh ...` מ-PowerShell (git עצמו ב-PATH). **רק Release** — לא לגעת בתיקיות/ZIP בשולחן. commit מסתיים ב-`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## יציבות והפעלה
- per-monitor-v2 DPI awareness ב-`main._set_windows_dpi_awareness`.
- מופע יחיד: `QSharedMemory` guard ב-`main._run` (משוחרר לפני self-update relaunch). חלון `showMaximized` + זוכר גאומטריה (`win_geometry`).
- יציאה: ב-frozen build `os._exit(code)` (`_hard_exit`) לדילוג על ניקוי `_MEI` בעייתי; `_cleanup_prev_mei` מנקה דליפה קודמת (`mei_last`). בטוח לנתונים.
- לוגו הקופה (`org_logo.png`): כותרת הדפסה, splash, רצועת מיתוג. אייקון EXE/taskbar נשאר `icon.ico`.
- משוב: `utils/feedback.py` → Google Form + JSONL מקומי.

## בדיקות
סקריפטים עצמאיים (לא pytest): `test_all`, `test_deep`, `test_selection` (4 הכללים העסקיים — עדיפות/ניקוד/רזרבה/חוסר-נתונים), `test_data_safety`, `test_scenarios`, `test_search`, `test_priority_import`, `test_volunteer_flow`, `test_updater`. `dev/stress_test.py [rounds]` (offscreen, `PYTHONUTF8=1`). כל הקבצים UTF-8 (טרמינל מציג mojibake אך הנתונים תקינים).

# אזורי התוכנה — הנוסח המלא (מסכים, ריענון, היסטוריית כרטיס, נתונים, שחרור, יציבות)

> הנוסח המלא של הסעיפים כפי שהיו ב-`CLAUDE.md` עד הקיצור של 4/11/2026 (מילה במילה). ב-CLAUDE.md נשארו רק ההכרעות והאיסורים בתמצית; **כאן = הפירוט המחייב** (שמות פונקציות, מפתחות, מקרי קצה). כששינוי נוגע בנושא — לעדכן כאן.

## לשוניות (6 אזורים)
מוגדרות ב-`main.py` `_build_tabs`: **חלוקה** (מסך "חלוקה ורישום" ישירות) · **אנשים** (כל המקבלים · חיפוש מהיר · חלוקות קודמות) · **הודעות** · **צינתוקים** · **מיילים** · **הגדרות**.
- כל לשונית-תוכן ("עלה") שומרת attribute + objectName `tab_<key>` — בדיקות/צילומים מאתרים לפי מפתח, לא לפי מיקום. ניווט: `MainWindow.navigate_to_tab(widget)`; `_current_leaf()`; `_leaf_tabs`; רענון-עצל `_needs_refresh` ב-`_show_leaf`.
- כל המסכים באותה שפת עיצוב (כותרת + צ'יפים חיים ב-`utils.ui.FlowLayout`, כרטיסים ממוספרים ①②, סרגל ③, תגי-שלב ✓). עזרים משותפים ב-`group_update.py` (`_step_card`/`_step_badge`/`_metric`/`_CHIP_*`/`_BADGE_QSS`) ו-`tzintukim.py` (`_set_step_done`/`_CARD_DONE_QSS`). **שינוי עיצוב שומר את כל שמות ה-attributes/slots** — הבדיקות והצילומים נשענים עליהם. תמונת-רקע: `utils/wallpaper.py` (פר-מחשב, עוצמה 45%; המשטחים שקופים רק בחלון הראשי דרך property `wallpaper=true`).
- **הכרעות UI קבועות:** אין מסך-בית ואין סיור מודרך (v2.60); לשונית "חד פעמי" הוסרה — "בחר חד-פעמיים" במסך החלוקה; בכרטיס המקבל שדה "אזור" ושורת "חלוקה אחרונה/הבאה" מוסתרים (הערכים נשמרים; הכרעות יהודה v3.56–3.57); דיאלוג העדכון בלי שמות אנשים; המילה האחידה לסיום שליחה = "הושלם"; אין מסך "כל השינויים של כולם" ואין חלון "מה חדש" (v3.75); **הגדרות = לשוניות-צד מימין** (`nav_list` + `page_stack`, 7 קטגוריות, v3.81); משקלי ניקוד ואחוזי קהילות — הקלדה חופשית, שמירה חסומה כשהסכום שגוי (בלי איזון אוטומטי).

## "חלוקה ורישום" (`tabs/group_update.py`) — מה חשוב לדעת
- **מקור-אמת למלאי:** `products_spin` ("מוצרים זמינים", השדה הכי בולט במסך — דרישת המשתמש) + `reserve_spin` (settings `available_products`/`reserve_count`; **אין ברירת מחדל לרזרבה — 0**, ו"חלוקה חדשה" מאפסת אותה; הכרעת יהודה 7/10/2026). הערה כללית נשמרת פעם אחת ברמת האצווה.
- **שני שלבים** (`_stage`): הכנה (בלי צ'קבוקסים; הדפסה/PDF רק כאן) → "רישום מי קיבל" (מתחיל ריק). **מי שלא סומן בשלב הרישום נרשם מפורשות "לא הגיע" (`received=0`)** — מזין התראות אי-הגעה (סף רצוף בהגדרות, ברירת מחדל 3). **חריג יחיד:** רשימה נעולה שנרשמת לבד ביום החלוקה (כלל 11) — שם כולם נרשמים כמי שקיבלו עד תיקון.
- **שם אוטומטי** (`_effective_dist_name`, `utils/hebdate.py`): "חלוקת פרשת נצבים — כ׳ אלול תשפ״ו" / "חלוקת פסח — …" בחג; `_is_auto_name` מזהה אותם (לא נדחפים להיסטוריית שמות).
- **`_one_time_gate_ok` נשאר בדיקה-טהורה** (הבדיקות קוראות לו — אסור לפתוח בו דיאלוג); העוטף `_ensure_one_time_picks` פותח את `OneTimePickerDialog`. השער פעיל רק במצב `schedule`.
- הערות בטבלה: `_row_notes` (dict לפי id) הוא המקור היחיד להערות שנרשמות. חד-פעמיים/רזרבה שנבחרו נשמרים כ-**guid** (`weekly_extra_ids`/`weekly_reserve_ids`) — חוצה מחשבים.
- **`_after_round_recorded()`** רץ אחרי כל רישום (שמירה, ייבוא-מתנדב, קליטה אוטומטית) — מנקה חד-פעמיים/סימונים, יוצא ממצב חג (`_leave_holiday_mode`).
- **🗑 בכל שורה (שלב ההכנה, v3.81):** `_remove_from_list` מסיר מהרשימה הנוכחית בלבד (לא מוחק מקבל, לא נרשם "לא הגיע"); נשמר בזיכרון עד "חלוקה חדשה"/רישום/הפעלה מחדש. כפתור "בחר חד-פעמיים" נעלם אחרי בחירה. אזהרות המחסור = שורה אחת קצרה, הפירוט ב-tooltip.
- "＋ הוסף מקבל" (`_ManualAddDialog`): ברירת מחדל "כולם", ממוין לפי ניקוד; מי שלא בתור מסומן "⚠ לא בתור" ונשאלים לפני הוספה.
- פלט: הדפסה (הפעולה הראשית) / PDF (`print_view.export_distribution_pdf`, שם עם תאריך+שעה) / אקסל / שליחה למתנדב.

## היסטוריית שינויים בכרטיס (v3.63)
- `change_log` (שדה, היה, הפך, מתי, מחשב, `source` edit/import/undo/auto). נרשם **רק במחשב שבו נעשה השינוי** (`_log_changes` ב-`update_recipient` ובייבוא-מיזוג) ומסונכרן ב-op **`rec_change` אחד לכל מקבל-לכל-פעולה**; `_apply_rec_upsert` **לא** רושם היסטוריה ⇒ פעם אחת בדיוק. שדות נגזרים לא נרשמים. תוויות: `db.FIELD_LABELS_HE`, `change_value_label`. מחיקה מנקה את ההיסטוריה.
- **שומר "תחיית-מתים":** `sync_deleted(guid, ts)` + `sync._deleted_after` — כרטיס/היסטוריה שחותמתם ≤ זמן המחיקה לא חוזרים.
- UI: חיפוש מהיר + כרטיס ⇒ `widgets.ChangeHistoryDialog`; גיליון באקסל של מקבל בודד. **לא מודפס בכרטיס** (ברירת מחדל; רון לא ביקש).
- **עריכה בו-זמנית:** `tabs.recipients.save_card_edit` = **הדרך היחידה** לשמור `RecipientDialog` — `updated_at` שונה ⇒ שאלה לפני דריסה (ברירת מחדל "לא").

## ריענון בין מסכים (v3.62)
- `MainWindow.refresh_all()` מרענן את המוצג ומסמן את השאר. **כל כתיבת נתונים שמשפיעה על מסך אחר חייבת `refresh_all()`**; הגדרה שמשפיעה → `settings._mark_others_stale()`.
- **רשימת השבוע למסכים אחרים = `group_tab.week_rows()` בלבד** — קריאה ישירה של `gt._rows_data` אסורה.
- רענון לא הורס עבודה: שמירת חיפוש/שורה/גלילה, `keep_id` בחיפוש מהיר, `_commit_open_editor`, `_set_text_safe` בהגדרות. בדיקות: `test_refresh.py`.

## נתונים ואבטחה
- DB + גיבויים ב-`%APPDATA%\ManhalHaluka\` (data.db, backups/) — נפרד מה-EXE, שורד עדכונים, מהגר DB ישן אוטומטית.
- סיסמה מגובבת PBKDF2 (`database.verify_password/set_password`), ברירת מחדל `1234`.
- גיבוי אוטומטי בהפעלה ולפני כל פעולה הרסנית (Online Backup API — הגיבוי הוא עותק). שחזור מאמת שהקובץ DB תקין לפני דריסה.
- (שלושה דליים routine/daily/safety; שחזור בלחיצה מ"רשימת גיבויים"; הגיבוי כולל לוגו ורקע בטבלת `assets`; `self_heal_db` — REINDEX קודם, לעולם לא מעתיק גיבוי על קובץ שלא הוזז הצידה. **אין שום מחיקת נתונים אוטומטית** — גם לא LIMIT בשאילתות היסטוריה/ייצוא.)

## עדכון אוטומטי ושחרור (`utils/updater.py`)
- repo `JHGJHJCD/distribution-manager`. בודק `releases/latest` (בהפעלה + כל 2 דקות, ETag), מוריד `Manhal-Haluka.exe`, מאמת, מחליף, מפעיל מחדש (retry + `os.startfile`, `DETACHED_PROCESS`) ונכנס **בלי סיסמה** (טוקן חד-פעמי `autologin.token`). התראת Windows על עדכון; התראות הורדה/עדכון-עמית רק במחשב המנהל.
- **הערות שחרור** מוצגות למשתמש דרך `_release_notes_html`: שורה ראשונה כותרת עם `:`, ואז פריטים בפסיקים או שורות `-`. בעברית פשוטה.
- **בנייה בענן (19/10/2026, הכרעת יהודה):** `.github/workflows/build.yml` על `windows-latest` — בדיקות → build → בדיקת עשן (ה-EXE עולה 15 שנ') → Release עם `Manhal-Haluka.exe`; מופעל בדחיפת תגית `v*` (התגית חייבת להתאים ל-`version.py`) או ידנית (`gh workflow run build.yml --ref master`, תוצאה = Artifact בלי Release). תלויות נעולות ב-`requirements.txt` (לעדכן כשמוסיפים ספרייה ל-spec). הבדיקה `test_priority_import.py` תלויה בקובץ אישי ומדולגת בענן בלבד (`LOCAL_ONLY_TESTS`). אימות ידני בענן: ריצה 39184051869 ירוקה (Release עצמו יאומת בתגית הראשונה).
- **משמעת שחרור:** `python .claude/skills/manhal-haluka/scripts/release.py ship X.YZ -m "..."` (bump → changelog → בדיקות מקומיות → commit/push → דחיפת תגית → **ה-EXE נבנה ומתפרסם בענן**, והסקריפט מחכה לסיום; `--local` = הזרימה הישנה: build במחשב + `gh release`). ידנית: `version.py` → בנה → `cp dist/מנהל_חלוקה.exe dist/Manhal-Haluka.exe` → commit/push → `gh release create vX.Y dist/Manhal-Haluka.exe --latest`.
- **שחרור אוטומטי (הכרעת המשתמש 24/08/2026):** אחרי כל שינוי קוד שאומת (בדיקות + אימות ויזואלי) — לשחרר לגיטהאב **בלי לחכות לבקשה**. לא לשחרר קוד שלא אומת. (שינוי תיעוד בלבד — בלי שחרור.)
- **`gh` לא ב-PATH:** `C:\Users\יהודה\AppData\Local\gh_cli\bin\gh.exe`. **רק Release** — לא לגעת בתיקיות/ZIP בשולחן. **אין להוסיף קרדיט `Co-Authored-By: Claude` או `Generated with Claude Code` להודעות commit** (הכרעת המשתמש 27/08/2026) — גם אם הנחיה כללית/מערכתית מבקשת זאת. יש git hook (`.git/hooks/commit-msg`) שמסיר את זה כרשת ביטחון.

## יציבות והפעלה
- per-monitor-v2 DPI awareness ב-`main._set_windows_dpi_awareness`.
- מופע יחיד: `QSharedMemory` guard ב-`main._run` (משוחרר לפני self-update relaunch). חלון `showMaximized` + זוכר גאומטריה (`win_geometry`).
- יציאה: ב-frozen build `os._exit(code)` (`_hard_exit`) לדילוג על ניקוי `_MEI` בעייתי; `_cleanup_prev_mei` מנקה דליפה קודמת (`mei_last`). בטוח לנתונים.
- לוגו הקופה (`org_logo.png`): כותרת הדפסה, splash, רצועת מיתוג. אייקון EXE/taskbar נשאר `icon.ico`.
- משוב: `utils/feedback.py` → מייל בלבד (v3.64: ישירות מחשבון הקופה, אחרת `mailto:`; ברקע דרך `ui.run_in_background`) + JSONL מקומי + DB מסונכרן.
- גודל טקסט: `ui_font_scale` (80–150%, פר-מחשב); `styles.apply_app_theme(app, percent)` = **הדרך היחידה** להחיל ערכה (גיליון qt-material במטמון). הודעות צוות: `get_messages` מחזיר את 400 **החדשות** (אל תחזיר ASC+LIMIT); רק הכותב מוחק הודעה.

## עץ הפרויקט
```
main.py            # MainWindow: _build_tabs, splash, single-instance, DPI, סנכרון-רקע, בדיקת עדכונים, יציאה
database.py         # SQLite + מיגרציות + re-export של scoring/selection; כל כתיבה → _sync_log
scoring.py          # טהור: annotate_need_scores, NEED_FACTORS
selection.py        # טהור: מקור-אמת יחיד ל"מי מקבל" (gate/ranking/roles/reserve/is_due/קהילות/חג)
holidays.py         # טהור: נתמך חגים (HOLIDAYS, supports, from_text, dist_label)
widgets.py          # WednesdayCalendar, DateEdit, ChangeHistoryDialog
styles.py · version.py · changelog.txt (נבנה מ-git log, מוצג בהגדרות)
tabs/
  group_update.py   # "חלוקה ורישום" — לשונית הפתיחה, שלבי הכנה/רישום, OneTimePickerDialog, FilterCriteriaDialog, CommunityAssignDialog
  recipients.py     # "כל המקבלים" + RecipientDialog + save_card_edit (הדרך היחידה לשמור כרטיס)
  search.py         # "חיפוש מהיר" — כרטיס-פרופיל, היסטוריה, ייצוא/הדפסת כרטיס
  distributions.py  # "חלוקות קודמות" (אצוות) + BatchDetailsDialog
  messages.py       # "הודעות" — צ'אט צוות מסונכרן
  tzintukim.py      # "צינתוקים" — ימות המשיח
  mails.py          # "מיילים" — מייל למקבלים מחשבון הקופה
  plan_lock.py      # הכנה קדימה, נעילה: PlanLockMixin של מסך החלוקה (כפתור/באנר/עריכה/השוואה) + חלון "תכנונים"
  settings.py       # "הגדרות" (+ דיאלוגי סנכרון/גיבויים/מקבלים-שנמחקו/יומן-מנהל/הודעות-שנשלחו)
  review.py         # בדיקת כפילויות (דיאלוג)
utils/
  sync.py            # סנכרון 2 מחשבים דרך Google Drive (journal-per-device, LWW)
  yemot.py · tts.py · call_history.py · callback_server.py · netblock.py   # צינתוקים/ימות
  mailer.py · google_auth.py · richtext.py · email_utils.py               # מיילים (+ SMTP/מתנדבים)
  excel_utils.py · print_view.py · backup.py · updater.py · feedback.py
  ui.py · timefmt.py · hebdate.py · wallpaper.py · effects.py · win_frameless.py
  _secret.py         # סודות מקומיים (ב-.gitignore; נכנס רק ל-EXE) — זיהוי-לקוח Google
dev/                # סקריפטי צילום (_shot_*.py), probe, stress, cloudflare/ (קוד ה-Worker), תוכניות קו
docs/               # README (מפה), היסטוריה, יומן, plans/, reviews/, raw/, archive/
.claude/            # skills/ · commands/
test_*.py           # בשורש
```

## מה הפרויקט
אפליקציית Windows בעברית (RTL מלא) לניהול חלוקת מצרכים ל"קופה של צדקה הר יונה" (נוף הגליל), ~500 מקבלים. המנהל מפעיל **מתנדבים** שמחלקים בנקודה קבועה; המתנדבים לא נוגעים בתוכנה — מקבלים רשימה במייל, ממלאים מי הגיע, והקובץ מיובא חזרה.
**אנשים:** יהודה = הבעלים (לא מתכנת — Claude מפתח); **רון** = מנהל הקופה, המפעיל בפועל (מיילים אליו רק לפי `reply-to-ron`). תמונת-המציאות התפעולית (תורם יחיד, שבועי = קבוצה קטנה) — זיכרון `project-fund-operations-reality`. שני מחשבים עובדים על אותם נתונים (סנכרון).

## Tech Stack, הרצה ובנייה
- Python 3.12, PyQt6 6.11, SQLite, openpyxl, qt-material (theme light_teal — "ירוק רגוע" v2.60: primary ‎#0f9d78‎/#0f766e, רקע ‎#f4faf7‎, כתום ‎#f59e0b‎ לפעולה משנית). מייל דרך `smtplib`/`email.mime` (stdlib בלבד).
- אין שרת — EXE יחיד (PyInstaller, `מנהל_חלוקה.spec`), DB מקומי.
```
python main.py                                              # הפעלה (סיסמה: 1234)
python -m PyInstaller --noconfirm --clean מנהל_חלוקה.spec   # → dist/מנהל_חלוקה.exe
```
אם ה-EXE נעול (WinError 5) לפני בנייה: `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"`.

## סקילים ופקודות — מתי להשתמש
| מתי | סקיל / פקודה |
|---|---|
| כל עבודה במאגר, בנייה, בדיקות, שחרור | `manhal-haluka` (מלכודות ב-`references/pitfalls.md`, `scripts/release.py`) |
| בקשת תכונה / שינוי התנהגות — **לפני הקוד** ("מה זה שובר, אילו כפתורים, מה חסר במסכים אחרים") | `feature-impact` |
| כלל "מי מקבל"/ניקוד/רזרבה/סינון/קהילות | `selection-rule` |
| עמודה/טבלה/שדה מסונכרן חדש | `db-migration` |
| כל נגיעה ב-UI — צילום אמיתי, או עץ ווידג'טים כטקסט על התוכנה הרצה דרך שרת `qtpy` (`QTPY_MCP_PROBE=1`; קריאה בלבד על נתונים אמיתיים) | `visual-check` |
| צינתוקים (`tzintukim.py`/`yemot.py`/`tts.py`/`call_history.py`) | `tzintuk-check` · `/בדוק-צינתוקים [מיקוד]` |
| מיילים (`mails.py`/`mailer.py`/`google_auth.py`/שליחה ב-`email_utils.py`) | `mail-check` · `/בדוק-מיילים [מיקוד]` |
| שרת המענה / שלוחה 76 / שורש הקו | `tzintuk-callback-server` |
| חיבור התוכנה לימות מקצה-לקצה (קריאה בלבד) | `yemot-connect` · `/בנה-חיבור` |
| תצורת הצינתוקים בקו — הצעות שיפור | `/שפר-צינתוקים` |
| ידע על ימות | סקילי `yemot-*` לפי הנושא (`yemot-ecosystem` — לבדוק לפני שכותבים משהו שאולי קיים) · `pitronai-panel-guide` · כללי: `yemot-hamashiach`. `yemot-line-state`/`-knowledge`/`-howto` פרטיים — **סודות, לא להעתיק ל-git** |
| מייל לרון | `reply-to-ron` |
| נדרים פלוס (מתוכנן) | `nedarim-plus-knowledge` |
| לנסח הנחיה למודל אחר | `prompt-translate` · `/תרגם-הנחיה` |
| דוח תקלות HTML מיהודה | `/תקן-דוח <דוח>` |
| חפירה עמוקה על נקודה אחת (הבטחה → נתיבים → ציד → בדיקה שנכשלת → תיקון → שחרור; הכרעות עסקיות בסבב שאלות אחד) | `/בודק-באגים <נקודה>` |
| שיפור מסך אוטומטי (צילום → Gemini → ביקורת → סבב שאלות אחד → מימוש; "(מומלץ)" בעברית, לא Recommended) | `/שפר-מסך <מסך>` |
| שיפור מסך דרך ראיון שיהודה מוביל | `/תשאל-מסך <מסך>` |
| ראיון על כל התוכנה → רשימה מדורגת ל-NEXT_TASK → ביצוע בסבבים | `/תשאל-תוכנה` |
| עקביות קובצי ההקשר + בריאות ה-wiki | `/בדוק-הקשר` (גלובלי: `/בדוק-ידע`) |
| הסבר בשפה פשוטה ליהודה | `/סוואנה [נושא]` |

## בדיקות
- סקריפטים עצמאיים (לא pytest) בשורש, `test_*.py`. **בדיקה אחת:** `PYTHONUTF8=1 <Python312> test_X.py`. הרשימה המלאה והמחייבת — `TESTS` ב-`release.py` (לא לשכפל אותה לכאן — היא מתיישנת).
- **סימולציה אקראית (2/11/2026):** `test_simulation.py` — Hypothesis מריצה "שנה" של פעולות אקראיות (רישום/לא-הגיע/ראשון/בונוס/חג/השהיה/שינוי תדירות) על DB אמיתי ובודקת אחרי כל צעד את כללים 6/7/9 ואת last/next בכרטיס מול מודל עצמאי שנכתב מהתיעוד. כלל חדש ב-`selection.py` ⇒ לעדכן גם את המודל שם. ארוכה (~דקות); `python test_simulation.py 10` לריצה מהירה.
- **הכל בפקודה אחת:** `python .claude/skills/manhal-haluka/scripts/release.py test` (רשימת `TESTS` שם — כל קובץ בדיקה חדש חייב להיכנס אליה; לינט M28 שומר). + הבודקים של `tzintuk-check`/`mail-check`.
- צילומים: `dev/_shot_*.py` (assert-ים + PNG ב-`dev/_shots/`; לאמת דרך Gemini). ⚠ ידוע: `dev/_shot_settings_v301.py` קורס ב-teardown (QThread) ו-`dev/_shot_mails.py` נכשל על "no client id" כשיש `_secret.py` — לא קשור לשינויים. `dev/stress_test.py [rounds]` (offscreen, `PYTHONUTF8=1`).
- כל הקבצים UTF-8 (טרמינל מציג mojibake אך הנתונים תקינים).

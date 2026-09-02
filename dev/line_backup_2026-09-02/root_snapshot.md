# צילום-מצב של שורש הקו — 2/9/2026 (לפני יצירת שלוחה /77)

קריאה בלבד דרך MCP (`pitron-ivr`), קו 0795378810 "קופה של צדקה הר יונה".
**שום קובץ מהקבצים כאן לא שונה** בעבודת הסקר — הם נשמרים רק כנקודת-ייחוס לשחזור.

## `/ext.ini` (שורש, 256 בייט)
```ini
type=menu

play_campaign_message=yes
play_campaign_message_one_time=yes
campaign_message_to_play=9-ACTIVE,17-ACTIVE-1-6d,
go_to_folder=/2

digits=2
timeout=1
text_extensions=yes

queue_timeout=1
queue_end_timeout_goto=/9999

check_did_and_go_to_folder=yes
```

## `/Did_Go_To.ini` (14 בייט)
```
033060315=/555
```

## `/ivr.ini` (256 בייט)
```ini
;הגדרת זיהוי יוצא בצנתוקים
tzintuk_your_id=033060315
tzintuk_invitation_join_to_list_caller_id=real_did

api_wait_answer_music_on_hold=yes
api_wait_answer_music_on_hold_different=ztomao
```
(4 שורות הערה בראש הקובץ בקידוד ישן — לא רלוונטיות.)

## תבניות האפליקציה (get_campaign_template_details)
| templateId | תיאור | callerId | yemotContext | maxDialAttempts | הודעה |
|---|---|---|---|---|---|
| 1430692 | מנהל חלוקה — צינתוק קלאסי | 048691834 | SIMPLE | 1 | 11.8 שנ' |
| 1430693 | מנהל חלוקה — צינתוקים | 048691834 | SIMPLE | 3 | 5.4 שנ' |

## שלוחות בשורש לפני השינוי
0, 03, 1, 10, 11, 12, 13, 198, 2, 3, 4, 5, 50, 500, 555, 6, 7, 8, 9 (+ תיקיות מערכת). **אין שלוחה 77.**

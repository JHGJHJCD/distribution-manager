# -*- coding: utf-8 -*-
"""בדיקות יצירת הקלטה מטקסט + מאגר ההקלטות (utils/tts.py, v2.86).

מאגר ההקלטות נבדק על תיקייה זמנית (בלי לגעת בנתונים אמיתיים). בסוף רצה גם
בדיקת יצירה אמיתית מול שירות ה-TTS (דורשת אינטרנט) — כישלון רשת שם הוא
אזהרה בלבד, לא מפיל את הסוויטה (שלא יחסום release במכונה בלי רשת)."""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")

from utils import tts

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


# המאגר על תיקייה זמנית — עוקפים את recordings_dir של %APPDATA%.
root = tempfile.mkdtemp(prefix="tts_test_")
tts.recordings_dir = lambda: root

# ── 1. שם מוצע ───────────────────────────────────────────────────────────────
print("— שם מוצע להקלטה —")
ok("חמש מילים ראשונות",
   tts.suggest_name("שלום, יש לך חלוקה ביום רביעי בשעה חמש") == "שלום, יש לך חלוקה ביום")
ok("טקסט קצר נשאר שלם", tts.suggest_name("בדיקה") == "בדיקה")
ok("ריק → 'הקלטה'", tts.suggest_name("") == "הקלטה")
ok("סימני פיסוק בסוף נחתכים", not tts.suggest_name("שלום.").endswith("."))

# ── 2. מאגר הקלטות ───────────────────────────────────────────────────────────
print("— מאגר הקלטות —")
ok("מאגר ריק בהתחלה", tts.library_list() == [])

src = os.path.join(root, "src.mp3")
with open(src, "wb") as f:
    f.write(b"FAKE-MP3-DATA-1" * 100)
item = tts.library_add(src, "הודעת חלוקה", text="שלום לכולם", voice="he-IL-AvriNeural",
                       source="tts")
ok("הוספה למאגר", len(tts.library_list()) == 1)
ok("שם נשמר", tts.library_list()[0]["name"] == "הודעת חלוקה")
ok("הקובץ הועתק פנימה", os.path.exists(tts.library_path(item)))
ok("הטקסט והקול נשמרו",
   item["text"] == "שלום לכולם" and item["voice"] == "he-IL-AvriNeural")

# אותו קובץ שוב — לא נוצר כפול (זיהוי לפי תוכן).
again = tts.library_add(src, "שם אחר לאותו קובץ")
ok("קובץ זהה לא משוכפל", len(tts.library_list()) == 1)
ok("שם חדש מתעדכן ברשומה הקיימת", again["id"] == item["id"]
   and tts.library_list()[0]["name"] == "שם אחר לאותו קובץ")

src2 = os.path.join(root, "src2.wav")
with open(src2, "wb") as f:
    f.write(b"OTHER-AUDIO" * 200)
item2 = tts.library_add(src2, "הקלטה שנייה", source="file")
ok("קובץ שונה נוסף", len(tts.library_list()) == 2)
ok("סיומת המקור נשמרת", tts.library_path(item2).endswith(".wav"))
ok("חדשה ראשונה ברשימה", tts.library_list()[0]["id"] == item2["id"])

tts.library_rename(item2["id"], "שם מעודכן")
ok("שינוי שם", any(it["name"] == "שם מעודכן" for it in tts.library_list()))

tts.library_delete(item2["id"])
ok("מחיקה מהמאגר", len(tts.library_list()) == 1)
ok("הקובץ נמחק מהדיסק", not os.path.exists(tts.library_path(item2)))

# רשומה שהקובץ שלה נעלם (נמחק ידנית) — מסוננת מהרשימה בלי לקרוס.
os.remove(tts.library_path(item))
ok("קובץ שנעלם מסונן מהרשימה", tts.library_list() == [])

# ── 3. שגיאות synthesize ─────────────────────────────────────────────────────
print("— שגיאות —")
try:
    tts.synthesize("", "he-IL-AvriNeural", os.path.join(root, "x.mp3"))
    ok("טקסט ריק נחסם", False)
except tts.TtsError as e:
    ok("טקסט ריק נחסם", "טקסט" in str(e))

# ── 4. יצירה אמיתית (אינטרנט; אזהרה בלבד בכישלון רשת) ────────────────────────
print("— יצירה אמיתית מול השירות —")
out = os.path.join(root, "real.mp3")
try:
    tts.synthesize("בדיקה קצרה.", "he-IL-AvriNeural", out)
    ok("נוצר MP3 אמיתי", os.path.getsize(out) > 1000, f"{os.path.getsize(out)} bytes")
except tts.TtsError as e:
    print(f"  ⚠  יצירה אמיתית דולגה (אין רשת / חסימה): {e}")

print()
if fails:
    print(f"✗ {len(fails)} בדיקות נכשלו: {fails}")
    sys.exit(1)
print("✓ כל בדיקות ה-TTS והמאגר עברו")
sys.exit(0)

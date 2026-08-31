# -*- coding: utf-8 -*-
"""צילום אימות ל-v2.86: כפתורי "צור הקלטה מטקסט"/"מאגר הקלטות" בלשונית
הצינתוקים + דיאלוג ה-TTS + דיאלוג המאגר (מאוכלס בתיקייה זמנית)."""
import os, sys, tempfile, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

app, win = shot.boot()
import database as db
from utils import tts

# מאגר על תיקייה זמנית + שתי הקלטות לדוגמה.
tmp = tempfile.mkdtemp(prefix="tts_shot_")
tts.recordings_dir = lambda: tmp
src = os.path.join(tmp, "a.mp3")
open(src, "wb").write(b"x" * 2000)
tts.library_add(src, "שלום, יש לך חלוקה ביום", text="שלום, יש לך חלוקה ביום רביעי",
                voice="he-IL-AvriNeural", source="tts")
src2 = os.path.join(tmp, "b.mp3")
open(src2, "wb").write(b"y" * 3000)
tts.library_add(src2, "הודעת חג פסח", source="file")

db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

win.navigate_to_tab(win.tzintukim_tab)
win.tzintukim_tab.refresh()
for _ in range(6):
    app.processEvents()
inner = win.tzintukim_tab.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "tts_tab.png"))

from tabs.tzintukim import TtsDialog, LibraryDialog
d = TtsDialog(win.tzintukim_tab)
d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
d.show()
app.processEvents(); app.processEvents()
d.grab().save(os.path.join(out, "tts_dialog.png"))
d.close()

l = LibraryDialog(win.tzintukim_tab)
l.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
l.listw.setCurrentRow(0)
l.show()
app.processEvents(); app.processEvents()
l.grab().save(os.path.join(out, "tts_library.png"))
l.close()
print("done")

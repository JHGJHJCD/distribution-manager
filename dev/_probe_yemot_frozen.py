# -*- coding: utf-8 -*-
"""בדיקת-אמת קפואה (PyInstaller) לחיבור ימות המשיח: האם urllib+ssl בתוך EXE
מגיעים ל-call2all מהמכונה הזו. רץ עם טוקן מזויף — תשובת 'סיסמה שגויים' מהשרת
= החיבור עצמו תקין. פלט לקונסולה, בלי GUI ובלי לגעת בנתונים אמיתיים."""
import os
import sys
import tempfile

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db

d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(d, "t.db")
db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
db.set_setting("yemot_system", "0000000000")
db.set_setting("yemot_password", "000000")

from utils import yemot

try:
    yemot.check_connection()
    print("UNEXPECTED-OK")
except yemot.YemotError as e:
    out = "YEMOT-ERR: " + str(e)
    sys.stdout.buffer.write(out.encode("utf-8"))
except Exception as e:
    print("OTHER:", type(e).__name__, e)

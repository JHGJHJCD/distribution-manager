# -*- coding: utf-8 -*-
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONUTF8"] = "1"
import database as db
_TMP = os.path.join(tempfile.gettempdir(), "search_test.db")
for e in ("", "-wal", "-shm"):
    try: os.remove(_TMP + e)
    except OSError: pass
db.DB_PATH = _TMP
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
db.init_db()

# seed known data
db.add_recipient({"full_name":"יהודה כהן","phone1":"0501112233","id_number":"123456789",
                  "spouse_id_number":"987654321","address":"הרצל 5","email":"y@a.com","area":"בעלז","status":"פעיל"})
db.add_recipient({"full_name":"יהודה לוי","phone1":"0529998877","id_number":"111222333",
                  "spouse_id_number":"444555666","address":"ויצמן 10","area":"נתיב","status":"פעיל"})
db.add_recipient({"full_name":"שרה מזרחי","phone1":"054-7778899","id_number":"222333444",
                  "spouse_id_number":"555666777","address":"בן גוריון 3","area":"בעלז","status":"מושהה"})

def names(rows): return sorted(r["full_name"] for r in rows)
ok = True
def check(label, got, expected):
    global ok
    passed = got == expected
    ok = ok and passed
    print(f"  [{'OK' if passed else 'FAIL'}] {label}: {got}" + ("" if passed else f"  expected {expected}"))

print("DB-level search_recipients:")
check("name 'יהודה' → both", names(db.search_recipients("יהודה")), ["יהודה כהן","יהודה לוי"])
check("husband id 123456789 → כהן", names(db.search_recipients("123456789")), ["יהודה כהן"])
check("wife id 444555666 → לוי", names(db.search_recipients("444555666")), ["יהודה לוי"])
check("phone 0529998877 → לוי", names(db.search_recipients("0529998877")), ["יהודה לוי"])
check("phone with dashes stored, query plain 0547778899 → מזרחי",
      names(db.search_recipients("0547778899")), ["שרה מזרחי"])
check("partial phone 999 → לוי", names(db.search_recipients("999")), ["יהודה לוי"])
check("address 'ויצמן' → לוי", names(db.search_recipients("ויצמן")), ["יהודה לוי"])
check("email 'y@a.com' → כהן", names(db.search_recipients("y@a.com")), ["יהודה כהן"])
check("empty → all 3", len(db.search_recipients("")), 3)
check("no match 'zzz' → none", len(db.search_recipients("zzz")), 0)

print("\nTab-level (results table + auto-select):")
from tabs.search import SearchTab
tab = SearchTab()
tab.refresh()   # cache rows
tab.search_input.setText("יהודה"); tab._run_search()
check("results table rows for 'יהודה'", tab.results_table.rowCount(), 2)
tab.search_input.setText("123456789"); tab._run_search()
check("results rows for husband id", tab.results_table.rowCount(), 1)
check("auto-selected profile shows name", "יהודה כהן" in tab.profile_lbl.text(), True)
check("husband id shown in profile", "123456789" in tab.profile_lbl.text(), True)
tab.search_input.setText("444555666"); tab._run_search()
check("wife id → profile shows name", "יהודה לוי" in tab.profile_lbl.text(), True)

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)

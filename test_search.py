# -*- coding: utf-8 -*-
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONUTF8"] = "1"
# Force UTF-8 console output so the ✓/→ characters in the report never crash the
# test on a legacy Windows code page (cp1255). Setting PYTHONUTF8 above is too
# late — the interpreter reads it only at startup — so reconfigure the streams.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
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
from PyQt6.QtWidgets import QLabel as _QLabel
def _details_text():
    # header (name + badge pill labels) + all detail-row values, concatenated
    parts = [lbl.text() for lbl in tab.detail_header.findChildren(_QLabel)]
    for i in range(tab._detail_lay.count()):
        w = tab._detail_lay.itemAt(i).widget()
        if w is not None:
            for lbl in w.findChildren(_QLabel):
                parts.append(lbl.text())
    return " ".join(parts)

tab.search_input.setText("יהודה"); tab._run_search()
check("results list rows for 'יהודה'", tab.results_list.count(), 2)
tab.search_input.setText("123456789"); tab._run_search()
check("results rows for husband id", tab.results_list.count(), 1)
check("auto-selected profile shows name", "יהודה כהן" in _details_text(), True)
check("husband id shown in profile", "123456789" in _details_text(), True)
tab.search_input.setText("444555666"); tab._run_search()
check("wife id → profile shows name", "יהודה לוי" in _details_text(), True)

print("\nProfile card layout (task 9: three columns, no scroll):")
from PyQt6.QtTest import QTest
db.update_recipient(db.search_recipients("123456789")[0]["id"],
                    {"souls": 6, "frequency": "שבועי", "synagogue": "בעלז"})
from PyQt6.QtCore import Qt as _Qt
tab.setLayoutDirection(_Qt.LayoutDirection.RightToLeft)     # the app runs RTL (main.py)
tab.resize(1366, 768); tab.show(); QTest.qWait(80)
def _layout_settled():
    # The details grid is laid out asynchronously; a fixed qWait was flaky on a
    # loaded machine. Wait (up to 3 s) until the card has its final geometry.
    _l = tab._detail_lay
    _x = {}
    for _i in range(_l.count()):
        _r, _c, _rs, _cs = _l.getItemPosition(_i)
        _w = _l.itemAt(_i).widget()
        if _w is not None and _cs == 1 and _r == 0:
            _x[_c] = _w.mapTo(tab.detail_card, _w.rect().topLeft()).x()
    return (len(_x) == 3 and _x[0] > _x[1] > _x[2]
            and tab.detail_scroll.verticalScrollBar().maximum() == 0)


tab.search_input.setText("123456789"); tab._run_search(); QTest.qWait(120)
for _ in range(60):
    if _layout_settled():
        break
    QTest.qWait(50)
lay = tab._detail_lay
check("details grid has 3 columns", lay.columnCount(), 3)
cols_used = set()
cap_x = {}
for i in range(lay.count()):
    r, c, rs, cs = lay.getItemPosition(i)
    w = lay.itemAt(i).widget()
    if w is not None and cs == 1:
        cols_used.add(c)
        if r == 0:
            cap_x[c] = w.mapTo(tab.detail_card, w.rect().topLeft()).x()
check("fields spread over 3 columns", sorted(cols_used), [0, 1, 2])
check("column 0 is right-most (RTL), column 2 left-most", cap_x[0] > cap_x[1] > cap_x[2], True)
check("no scrollbar needed in the details card", tab.detail_scroll.verticalScrollBar().maximum(), 0)
check("synagogue + souls shown", all(t in _details_text() for t in ("בעלז", "6")), True)

print("\nHistory row delete (task 10: a delete cell on every row):")
from PyQt6.QtWidgets import QMessageBox as _MB, QHeaderView as _HV
from datetime import timedelta as _td
_cohen = db.search_recipients("123456789")[0]
_w = db.next_wednesday()
for _i, _nm in enumerate(("חלוקה א", "חלוקה ב", "חלוקה ג")):
    db.bulk_add_distributions([db.get_recipient(_cohen["id"])], (_w - _td(days=7 * (_i + 2))).isoformat(),
                              "", "", "", dist_name=_nm, general_note="")
tab.search_input.setText("123456789"); tab._run_search(); QTest.qWait(120)
ht = tab.hist_table
check("history table has a 6th (delete) column", ht.columnCount(), 6)
check("no separate 'מחק רישום' button any more", hasattr(tab, "btn_del_hist"), False)
check("3 history rows", ht.rowCount(), 3)
check("every row has a delete cell", all("מחק" in (ht.item(r, 5).text() if ht.item(r, 5) else "")
                                          for r in range(3)), True)
check("delete column is Fixed (cell-width never measured)",
      ht.horizontalHeader().sectionResizeMode(5), _HV.ResizeMode.Fixed)
check("delete column fully visible (width > 40)", ht.columnWidth(5) > 40, True)
_ids_before = [ht.item(r, 0).data(_Qt.ItemDataRole.UserRole) for r in range(3)]
_asked = []
def _ask(answer):
    def f(parent, title, text, *a, **k):
        _asked.append(text); return answer
    return staticmethod(f)
_orig_q = _MB.question
try:
    # a click on another column of the row does nothing (no question at all)
    _MB.question = _ask(_MB.StandardButton.Yes)
    ht.cellClicked.emit(1, 1)
    check("click on a data column asks nothing, deletes nothing",
          (len(_asked), len(db.get_distributions_for_recipient(_cohen["id"]))), (0, 3))
    # answering "no" keeps the record
    _MB.question = _ask(_MB.StandardButton.No)
    ht.cellClicked.emit(1, 5)
    check("question shown once, in Hebrew, with the date",
          (len(_asked), "למחוק" in _asked[0], ht.item(1, 0).text() in _asked[0]), (1, True, True))
    check("'no' keeps all records", len(db.get_distributions_for_recipient(_cohen["id"])), 3)
    # answering "yes" removes exactly the clicked row (not the highlighted one)
    _MB.question = _ask(_MB.StandardButton.Yes)
    ht.setCurrentCell(0, 0)
    ht.cellClicked.emit(1, 5)
finally:
    _MB.question = _orig_q
_left = {d["id"] for d in db.get_distributions_for_recipient(_cohen["id"])}
check("'yes' deletes exactly the clicked row", _left, {_ids_before[0], _ids_before[2]})
check("table refreshed to 2 rows, same person still shown",
      (tab.hist_table.rowCount(), tab._current_rec_id), (2, _cohen["id"]))

print("\nReport C (ג1/ג3/ג4/ג5):")
check("ג1 search tab has no top 'חיפוש מהיר' title label",
      [l for l in tab.findChildren(_QLabel) if l.text() == "חיפוש מהיר"], [])
from tabs.distributions import BatchDetailsDialog
_bid = db.bulk_add_distributions([db.get_recipient(_cohen["id"])], _w.isoformat(), "", "", "",
                                 dist_name="חלוקת בדיקה", general_note="")
_batch = {"id": None, "dist_name": "חלוקת בדיקה", "dist_date": _w.isoformat()}
_b = [b for b in db.get_distribution_batches()]
_bd = next((b for b in _b if b.get("dist_name") == "חלוקת בדיקה"), None)
if _bd:
    _dlg = BatchDetailsDialog(_bd)
    _all = [_dlg.search_edit.parent().layout().itemAt(i).widget() for i in range(_dlg.search_edit.parent().layout().count())]
    _lbls = [w.text() for w in _all if isinstance(w, _QLabel)]
    check("ג3 dialog has search field", _dlg.search_edit.placeholderText() != "", True)
    _lst = _dlg._lists[0]
    check("ג3 list has the person", _lst.count() >= 1 and not _lst.item(0).isHidden(), True)
    _dlg.search_edit.setText("zzzz")
    check("ג3 filter hides non-matching", all(_lst.item(i).isHidden() for i in range(_lst.count())), True)
    _dlg.search_edit.setText("כהן")
    check("ג3 filter shows matching", not _lst.item(0).isHidden(), True)
    _dlg.close(); _dlg.deleteLater()
from utils.print_view import _build_html as _bh
_r1 = [{"full_name": "א"}, {"full_name": "ב"}]
check("ג5 no answers -> no תשובה column", "תשובה" in _bh(_r1, "01/01/2026"), False)
_h2 = _bh([{"full_name": "א", "_answer": "מגיע"}, {"full_name": "ב"}], "01/01/2026")
check("ג5 with an answer -> column shown", ("תשובה" in _h2, "מגיע" in _h2), (True, True))
_h3 = _bh([{"full_name": "א", "_confirmed": True}, {"full_name": "ר", "_reserve": True}], "01/01/2026")
check("ג5 confirmed + reserve section", ("תשובה" in _h3, "רזרבה" in _h3), (True, True))

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.stdout.flush()
os._exit(0 if ok else 1)   # skip Qt teardown (segfault with the dialog probe)

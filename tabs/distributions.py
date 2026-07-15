"""The 'חלוקות' tab — one row per distribution event (batch).

Each recorded distribution shows as a single line with its shared header data
(date, name, products, quantity, distributor, how many received, souls) plus the
one general note for the whole distribution. Double-click a row to see who
received and the full note."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QMessageBox, QAbstractItemView,
    QDialog, QListWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import database as db
from utils.ui import (attach_empty_state, refresh_empty_state, ALIGN_RIGHT,
                      enable_touch_scroll, apply_header_icons)

_SMALL_BTN = "font-size:11px; min-height:24px; min-width:0; padding:3px 12px;"

COLS = ["תאריך", "שם החלוקה", "מה חולק", "כמות לאדם", "מחלק",
        "קיבלו", "נפשות", "הערה כללית"]
_COL_NOTE = 7


def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""


class BatchDetailsDialog(QDialog):
    """Shows the recipients recorded under one distribution + the full note."""

    def __init__(self, batch: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("פרטי חלוקה")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(460, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        head = QLabel(
            f"<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
            f"<span style='font-size:18px;font-weight:800;color:#0d2a4a;'>"
            f"{batch.get('dist_name') or 'חלוקה'}</span><br>"
            f"<span style='color:#475569;'>{_fdate(batch.get('dist_date',''))} · "
            f"{batch.get('products') or ''} · מחלק: {batch.get('distributor') or '—'}</span></div>")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        lay.addWidget(head)

        note = (batch.get("general_note") or "").strip()
        if note:
            note_lbl = QLabel(f"📝 {note}")
            note_lbl.setWordWrap(True)
            note_lbl.setStyleSheet(
                "background:#fffbeb; border:1px solid #fde68a; border-radius:6px;"
                " color:#78350f; padding:8px 10px;")
            lay.addWidget(note_lbl)

        recs = db.get_batch_recipients(batch.get("id"))
        # received=1 → got it; received=0 → recorded no-show (#yjcny). Older rows
        # have no flag stored → treat as received (default 1).
        got = [r for r in recs if (r.get("received", 1) or 0) != 0]
        missed = [r for r in recs if (r.get("received", 1) or 0) == 0]

        lay.addWidget(QLabel(f"מקבלים שקיבלו ({len(got)}):"))
        lst = QListWidget()
        enable_touch_scroll(lst)
        for r in got:
            nm = r.get("recipient_name", "") or "—"
            pnote = (r.get("notes") or "").strip()
            lst.addItem(f"{nm}" + (f"   —   {pnote}" if pnote else ""))
        lay.addWidget(lst, 1)

        if missed:
            lbl_missed = QLabel(f"לא קיבלו ({len(missed)}):")
            lbl_missed.setStyleSheet("color:#b91c1c; font-weight:600;")
            lay.addWidget(lbl_missed)
            lst_missed = QListWidget()
            lst_missed.setStyleSheet("color:#b91c1c;")
            enable_touch_scroll(lst_missed)
            for r in missed:
                nm = r.get("recipient_name", "") or "—"
                lst_missed.addItem(nm)
            lay.addWidget(lst_missed, 1)

        btn = QPushButton("סגור")
        btn.setObjectName("neutral")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)


class DistributionsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._batches = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        title = QLabel("חלוקות")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        top.addWidget(self.count_lbl)

        # (The manual "רענן" button was removed — the tab already reloads itself
        # every time it's opened and after a delete, so it had no real use.)
        self.btn_delete = QPushButton("מחק חלוקה")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setStyleSheet(_SMALL_BTN)
        self.btn_delete.setToolTip("מחק את החלוקה הנבחרת ואת רישומי המקבלים שלה")
        self.btn_delete.clicked.connect(self._delete_selected)
        top.addWidget(self.btn_delete)
        lay.addLayout(top)

        hint = QLabel("לחיצה כפולה על שורה מציגה מי קיבל ואת ההערה המלאה")
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        lay.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        apply_header_icons(self.table)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_NOTE, QHeaderView.ResizeMode.Stretch)
        hdr.setResizeContentsPrecision(20)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._open_selected)
        enable_touch_scroll(self.table)
        lay.addWidget(self.table)
        attach_empty_state(self.table, "עדיין לא נרשמו חלוקות")

    def refresh(self):
        self._batches = db.get_distribution_batches()
        self._populate()

    def _populate(self):
        rows = self._batches
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            vals = [
                _fdate(b.get("dist_date", "")),
                b.get("dist_name", "") or "—",
                b.get("products", "") or "",
                str(b.get("quantity", "") or ""),
                b.get("distributor", "") or "",
                str(b.get("recipient_count", "") or 0),
                str(b.get("souls_total", "") or 0),
                (b.get("general_note", "") or "").replace("\n", " "),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(ALIGN_RIGHT)
                if c == 1:   # name — bold
                    f = item.font(); f.setBold(True); item.setFont(f)
                item.setData(Qt.ItemDataRole.UserRole, b.get("id"))
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        self.count_lbl.setText(f"סה\"כ חלוקות: {len(rows)}")
        refresh_empty_state(self.table)

    def _selected_batch(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._batches[row] if row < len(self._batches) else None

    def _open_selected(self, *_):
        b = self._selected_batch()
        if b:
            BatchDetailsDialog(b, self).exec()

    def _delete_selected(self):
        b = self._selected_batch()
        if not b:
            QMessageBox.information(self, "", "בחר חלוקה תחילה")
            return
        name = b.get("dist_name") or _fdate(b.get("dist_date", "")) or "חלוקה"
        reply = QMessageBox.question(
            self, "מחיקת חלוקה",
            f"למחוק את החלוקה '{name}' ואת {b.get('recipient_count', 0)} רישומי המקבלים שלה?\n"
            "פעולה זו אינה הפיכה.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        db.delete_batch(b.get("id"))
        self.refresh()
        if self.main_win:
            self.main_win.status_msg("החלוקה נמחקה")

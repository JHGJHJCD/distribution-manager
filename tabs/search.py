from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QComboBox, QAbstractItemView, QFormLayout, QFrame
)
from PyQt6.QtCore import Qt
import database as db

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""

HIST_COLS = ["תאריך", "מה חולק", "כמות", "מחלק", "הערות"]


class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._name_map: dict = {}  # display_name → recipient_id
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("חיפוש מהיר")
        title.setObjectName("title")
        lay.addWidget(title)

        # Name picker
        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("בחר שם:"))
        self.name_combo = QComboBox()
        self.name_combo.setMinimumWidth(280)
        self.name_combo.setEditable(True)
        self.name_combo.currentTextChanged.connect(self._on_name_changed)
        pick_row.addWidget(self.name_combo)
        pick_row.addStretch()
        lay.addLayout(pick_row)

        # Details frame
        frame = QFrame()
        frame.setObjectName("panel")
        frame_lay = QHBoxLayout(frame)
        frame_lay.setContentsMargins(12, 10, 12, 10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        def lbl():
            w = QLabel("")
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return w

        self.l_phone1 = lbl()
        self.l_phone2 = lbl()
        self.l_phone3 = lbl()
        self.l_address = lbl()
        self.l_area = lbl()
        self.l_souls = lbl()
        self.l_freq = lbl()
        self.l_status = lbl()
        self.l_last = lbl()
        self.l_next = lbl()
        self.l_notes = lbl()
        self.l_count = lbl()

        form.addRow("טלפון 1:", self.l_phone1)
        form.addRow("טלפון 2:", self.l_phone2)
        form.addRow("טלפון 3:", self.l_phone3)
        form.addRow("כתובת:", self.l_address)
        form.addRow("אזור:", self.l_area)
        form.addRow("נפשות:", self.l_souls)
        form.addRow("תדירות:", self.l_freq)
        form.addRow("סטטוס:", self.l_status)
        form.addRow("חלוקה אחרונה:", self.l_last)
        form.addRow("חלוקה הבאה:", self.l_next)
        form.addRow("הערות:", self.l_notes)
        form.addRow("סה\"כ חלוקות:", self.l_count)
        frame_lay.addLayout(form)
        lay.addWidget(frame)

        # History table
        hist_title = QLabel("היסטוריית חלוקות:")
        hist_title.setObjectName("subtitle")
        lay.addWidget(hist_title)

        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(len(HIST_COLS))
        self.hist_table.setHorizontalHeaderLabels(HIST_COLS)
        self.hist_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.hist_table.setAlternatingRowColors(True)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.hist_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.hist_table.verticalHeader().setVisible(False)
        lay.addWidget(self.hist_table)

    def refresh(self):
        all_recs = db.get_all_recipients()
        self._name_map = {}
        display_names = []

        for rec in sorted(all_recs, key=lambda r: r.get("full_name", "")):
            name = rec["full_name"]
            status = rec.get("status", "פעיל")
            display = name if status == "פעיל" else f"{name} ({status})"
            self._name_map[display] = rec["id"]
            display_names.append(display)

        current = self.name_combo.currentText()
        self.name_combo.blockSignals(True)
        self.name_combo.clear()
        self.name_combo.addItems([""] + display_names)
        if current in display_names:
            self.name_combo.setCurrentText(current)
        self.name_combo.blockSignals(False)
        self._on_name_changed(self.name_combo.currentText())

    def _on_name_changed(self, display_name):
        if not display_name:
            self._clear()
            return

        rec_id = self._name_map.get(display_name)
        if rec_id:
            rec = db.get_recipient(rec_id)
        else:
            # Typed input not in map — search by exact full_name
            all_recs = db.get_all_recipients()
            rec = next((r for r in all_recs if r["full_name"] == display_name), None)

        if not rec:
            self._clear()
            return

        self.l_phone1.setText(rec.get("phone1") or "")
        self.l_phone2.setText(rec.get("phone2") or "")
        self.l_phone3.setText(rec.get("phone3") or "")
        self.l_address.setText(rec.get("address") or "")
        self.l_area.setText(rec.get("area") or "")
        self.l_souls.setText(str(rec.get("souls") or ""))
        self.l_freq.setText(rec.get("frequency") or "")
        self.l_status.setText(rec.get("status") or "")
        self.l_last.setText(_fdate(rec.get("last_distribution") or ""))
        self.l_next.setText(_fdate(rec.get("next_distribution") or ""))
        self.l_notes.setText(rec.get("notes") or "")

        hist = db.get_distributions_for_recipient(rec["id"])
        self.l_count.setText(str(len(hist)))
        self.hist_table.setRowCount(len(hist))
        for r, entry in enumerate(hist):
            vals = [_fdate(entry.get("dist_date", "")), entry.get("what_dist", ""),
                    str(entry.get("quantity", "") or ""), entry.get("distributor", ""),
                    entry.get("notes", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.hist_table.setItem(r, c, item)

    def _clear(self):
        for lbl in [self.l_phone1, self.l_phone2, self.l_phone3, self.l_address,
                    self.l_area, self.l_souls, self.l_freq, self.l_status,
                    self.l_last, self.l_next, self.l_notes, self.l_count]:
            lbl.setText("")
        self.hist_table.setRowCount(0)

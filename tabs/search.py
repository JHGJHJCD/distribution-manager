from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QAbstractItemView, QFormLayout, QFrame,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
import database as db
from utils.ui import search_icon

def _fdate(s: str) -> str:
    if s and len(s) >= 10 and s[4] == '-':
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s or ""

HIST_COLS = ["תאריך", "מה חולק", "כמות", "מחלק", "הערות"]
RESULT_COLS = ["שם מלא", "טלפון", "ת״ז בעל", "ת״ז אשה", "אזור", "סטטוס"]


def _first_phone(rec: dict) -> str:
    for k in ("phone1", "phone2", "phone3"):
        v = rec.get(k)
        if v:
            return str(v)
    return ""


class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows: list = []         # cached on refresh, filtered in-memory
        self._results: list = []          # current result rows
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._run_search)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        title = QLabel("חיפוש מהיר")
        title.setObjectName("title")
        lay.addWidget(title)

        # Search box — matches across ALL fields
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("חיפוש:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("שם, טלפון, ת״ז בעל/אשה, כתובת, אימייל...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(lambda: self._filter_timer.start(200))
        search_row.addWidget(self.search_input)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        search_row.addWidget(self.count_lbl)
        lay.addLayout(search_row)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(len(RESULT_COLS))
        self.results_table.setHorizontalHeaderLabels(RESULT_COLS)
        self.results_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setMaximumHeight(220)
        rhdr = self.results_table.horizontalHeader()
        rhdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        rhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        rhdr.setResizeContentsPrecision(20)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.itemSelectionChanged.connect(self._on_result_selected)
        lay.addWidget(self.results_table)

        # Details frame
        frame = QFrame()
        frame.setObjectName("panel")
        # A VBox (not a single-child HBox) so the form spans the full card width
        # and value labels get room to grow/wrap instead of clipping.
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(12, 10, 12, 10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        form.setHorizontalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        def lbl():
            w = QLabel("")
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            w.setWordWrap(True)                    # long address/notes wrap instead of clip
            w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            return w

        self.l_name = lbl()
        _nf = self.l_name.font(); _nf.setBold(True); self.l_name.setFont(_nf)
        self.l_phone1 = lbl()
        self.l_phone2 = lbl()
        self.l_phone3 = lbl()
        self.l_address = lbl()
        self.l_area = lbl()
        self.l_souls = lbl()
        self.l_freq = lbl()
        self.l_status = lbl()
        self.l_id = lbl()
        self.l_spouse_id = lbl()
        self.l_last = lbl()
        self.l_next = lbl()
        self.l_notes = lbl()
        self.l_count = lbl()

        form.addRow("שם מלא:", self.l_name)
        form.addRow("טלפון 1:", self.l_phone1)
        form.addRow("טלפון 2:", self.l_phone2)
        form.addRow("טלפון 3:", self.l_phone3)
        form.addRow("ת״ז בעל:", self.l_id)
        form.addRow("ת״ז אשה:", self.l_spouse_id)
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
        hdr.setResizeContentsPrecision(20)  # constant-cost column sizing on big lists
        self.hist_table.verticalHeader().setVisible(False)
        lay.addWidget(self.hist_table)

    def refresh(self):
        # Cache the full recipient list once; keystrokes filter this in-memory
        # instead of re-hitting the database on every character.
        self._all_rows = db.get_all_recipients()
        self._run_search()

    def _run_search(self):
        query = self.search_input.text()
        self._results = db.filter_recipients(self._all_rows, query)
        self._populate_results()

    def _populate_results(self):
        _ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.results_table.blockSignals(True)
        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.results_table.setRowCount(len(self._results))
        for r, rec in enumerate(self._results):
            vals = [rec.get("full_name", ""), _first_phone(rec),
                    rec.get("id_number", "") or "", rec.get("spouse_id_number", "") or "",
                    rec.get("area", "") or "", rec.get("status", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v) or "")
                item.setTextAlignment(_ALIGN)
                if c == 0:   # name — bold
                    item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.results_table.setItem(r, c, item)
        self.results_table.blockSignals(False)
        self.count_lbl.setText(f"נמצאו: {len(self._results)}")

        # Auto-select the top match so its details show immediately — preserving
        # the old name-search feel where details appeared without an extra click.
        if self._results:
            self.results_table.setCurrentCell(0, 0)
        else:
            self.results_table.clearSelection()
            self._clear_details()

    def _on_result_selected(self):
        row = self.results_table.currentRow()
        if row < 0:
            self._clear_details()
            return
        item = self.results_table.item(row, 0)
        rec_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if rec_id:
            self._show_recipient(rec_id)

    def _show_recipient(self, rec_id):
        rec = db.get_recipient(rec_id)
        if not rec:
            self._clear_details()
            return

        self.l_name.setText(rec.get("full_name") or "")
        self.l_phone1.setText(rec.get("phone1") or "")
        self.l_phone2.setText(rec.get("phone2") or "")
        self.l_phone3.setText(rec.get("phone3") or "")
        self.l_id.setText(rec.get("id_number") or "")
        self.l_spouse_id.setText(rec.get("spouse_id_number") or "")
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
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)
        self.hist_table.setRowCount(len(hist))
        for r, entry in enumerate(hist):
            vals = [_fdate(entry.get("dist_date", "")), entry.get("what_dist", ""),
                    str(entry.get("quantity", "") or ""), entry.get("distributor", ""),
                    entry.get("notes", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v or "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.hist_table.setItem(r, c, item)

    def _clear_details(self):
        for lbl in [self.l_name, self.l_phone1, self.l_phone2, self.l_phone3,
                    self.l_id, self.l_spouse_id, self.l_address,
                    self.l_area, self.l_souls, self.l_freq, self.l_status,
                    self.l_last, self.l_next, self.l_notes, self.l_count]:
            lbl.setText("")
        self.hist_table.clearContents()
        self.hist_table.setRowCount(0)

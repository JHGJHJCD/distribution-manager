from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QAbstractItemView, QMessageBox,
    QDialog, QInputDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import database as db
from utils.backup import auto_backup_async
from utils.ui import (BadgeDelegate, PRIORITY_BADGES, STATUS_BADGES, ALIGN_RIGHT,
                      apply_header_icons)

COLS = ["סוג", "מפתח", "שם מלא", "טלפון 1", "טלפון 2", "אזור", "עדיפות", "סטטוס"]

# Soft alternating tints so members of the same group read as one block.
_GROUP_BG = [QColor("#fff7ed"), QColor("#eff6ff")]   # warm / cool

# Coloured pill per duplicate TYPE so the kind of problem reads at a glance
# (#ipjgd), matching the app's badge look elsewhere. Keys must equal the exact
# 'type' strings produced by db.find_duplicate_groups.
TYPE_BADGES = {
    "שם כפול":     ("#e0e7ff", "#3730a3"),   # indigo — same name
    "טלפון משותף": ("#fef3c7", "#92400e"),   # amber  — shared phone
}


def _priority_text(rec: dict) -> str:
    labels = {4: "קבוע", 3: "ראשונה", 2: "שנייה"}
    pr = rec.get("priority")
    if pr in labels:
        return labels[pr]
    return "בירור" if "בירור" in (rec.get("priority_raw") or "") else ""


class ReviewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._row_ids = []   # rec_id per table row
        self._row_groups = []   # (group type, [member ids]) per table row — for the merge button
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        title = QLabel("בדיקת נתונים — כפילויות וטלפונים סותרים")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("subtitle")
        top.addWidget(self.count_lbl)
        # No manual 'רענן' button (#yg76l) — the view refreshes automatically when
        # it opens and after every edit/delete, so the button was just clutter.
        lay.addLayout(top)

        hint = QLabel("שורות עם אותו רקע = אותה קבוצה. לחיצה כפולה לעריכה. "
                      "אפשר למחוק כפילות מיותרת, או למזג שני כרטיסים של אותו אדם "
                      "(שם כפול) לכרטיס אחד.")
        hint.setObjectName("subtitle")
        lay.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        apply_header_icons(self.table)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # 'שם מלא' — give it a real, roomy width. As a plain Stretch column it got
        # starved next to the auto-sized columns and clipped names to "וי…" (#p11zo).
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setResizeContentsPrecision(20)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(2, 220)
        self.table.setItemDelegateForColumn(0, BadgeDelegate(TYPE_BADGES, self.table))       # סוג
        self.table.setItemDelegateForColumn(6, BadgeDelegate(PRIORITY_BADGES, self.table))  # עדיפות
        self.table.setItemDelegateForColumn(7, BadgeDelegate(STATUS_BADGES, self.table))    # סטטוס
        lay.addWidget(self.table)

        bot = QHBoxLayout()
        btn_edit = QPushButton("ערוך")
        btn_edit.clicked.connect(self._edit)
        bot.addWidget(btn_edit)
        self.btn_merge = QPushButton("מזג כפילות")
        self.btn_merge.setObjectName("btn_merge_dup")
        self.btn_merge.setToolTip("אותו אדם בשני כרטיסים: שני המספרים נשמרים וההיסטוריה מתאחדת")
        self.btn_merge.clicked.connect(self._merge)
        bot.addWidget(self.btn_merge)
        btn_del = QPushButton("מחק כפילות")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._delete)
        bot.addWidget(btn_del)
        bot.addStretch()
        lay.addLayout(bot)

    def refresh(self):
        groups = db.find_duplicate_groups()
        _ALIGN = ALIGN_RIGHT
        # flatten groups → rows
        flat = []   # (group_index, type, key, rec)
        for gi, g in enumerate(groups):
            for rec in g["members"]:
                flat.append((gi, g["type"], g["key"], rec))

        self._row_ids = []
        self._row_groups = []
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(flat))
        for r, (gi, gtype, key, rec) in enumerate(flat):
            bg = _GROUP_BG[gi % 2]
            self._row_ids.append(rec.get("id"))
            self._row_groups.append((gtype, [m.get("id") for m in groups[gi]["members"]]))
            vals = [gtype, key, rec.get("full_name", ""),
                    rec.get("phone1", ""), rec.get("phone2", ""),
                    rec.get("area", ""), _priority_text(rec), rec.get("status", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v) or "")
                item.setTextAlignment(_ALIGN)
                item.setBackground(bg)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, rec.get("id"))
                if c == 2:   # name — bold
                    nf = item.font(); nf.setBold(True); item.setFont(nf)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

        n_groups = len(groups)
        n_rows = len(flat)
        if n_groups:
            self.count_lbl.setText(f"{n_groups} קבוצות לבדיקה · {n_rows} רשומות")
            self.count_lbl.setStyleSheet("color:#dc2626;")
        else:
            self.count_lbl.setText("לא נמצאו כפילויות או טלפונים סותרים ✓")
            self.count_lbl.setStyleSheet("color:#334155;")

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_ids):
            return None
        return self._row_ids[row]

    def _edit(self):
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר רשומה תחילה")
            return
        from tabs.recipients import RecipientDialog
        rec = db.get_recipient(rec_id)
        if not rec:
            return
        dlg = RecipientDialog(self, rec)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            from tabs.recipients import save_card_edit
            if not save_card_edit(self, rec_id, rec, dlg):
                return
            auto_backup_async()
            self.refresh()
            if self.main_win:
                self.main_win.status_msg("הרשומה עודכנה")
                self.main_win.refresh_all()

    def _merge(self):
        """משימה 7: מיזוג שני כרטיסים באותו שם (טלפון שונה). רק בקבוצת 'שם כפול'."""
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר רשומה תחילה")
            return
        gtype, ids = self._row_groups[self.table.currentRow()]
        if gtype != "שם כפול":
            QMessageBox.information(self, "", "אפשר למזג רק כרטיסים בעלי אותו שם — בחר שורה "
                                    "מקבוצה מסוג 'שם כפול'.")
            return
        others = [i for i in ids if i != rec_id]
        other_id = None
        if len(others) == 1:
            other_id = others[0]
        elif others:
            labels = []
            for i in others:
                r = db.get_recipient(i) or {}
                labels.append(f"טלפון: {', '.join(db.recipient_phones(r)) or 'אין'} (מס' {i})")
            pick, ok = QInputDialog.getItem(self, "מיזוג כרטיסים", "עם איזה כרטיס למזג?",
                                            labels, 0, False)
            if not ok:
                return
            other_id = others[labels.index(pick)]
        a, b = db.get_recipient(rec_id), db.get_recipient(other_id) if other_id else None
        if not a or not b:
            QMessageBox.information(self, "", "אחד הכרטיסים כבר לא קיים — הרשימה תתרענן.")
            self.refresh()
            return
        from tabs.recipients import offer_merge_two_cards
        if offer_merge_two_cards(self, a, b):
            self.refresh()
            if self.main_win:
                self.main_win.status_msg(f"הכרטיסים של {a['full_name']} מוזגו")
                self.main_win.refresh_all()

    def _delete(self):
        rec_id = self._selected_id()
        if not rec_id:
            QMessageBox.information(self, "", "בחר רשומה תחילה")
            return
        rec = db.get_recipient(rec_id)
        name = rec["full_name"] if rec else "?"
        reply = QMessageBox.question(
            self, "מחיקת כפילות", f"למחוק את הרשומה '{name}'?\nפעולה זו אינה הפיכה.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            db.delete_recipient(rec_id)
        except ValueError as e:
            force = QMessageBox.question(
                self, "מחיקה כולל היסטוריה",
                f"{e}\n\n⚠ למחוק כולל ההיסטוריה?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if force != QMessageBox.StandardButton.Yes:
                return
            db.force_delete_recipient(rec_id)
        auto_backup_async()
        self.refresh()
        if self.main_win:
            self.main_win.status_msg(f"{name} נמחק")
            self.main_win.refresh_all()

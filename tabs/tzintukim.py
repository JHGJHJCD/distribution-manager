# -*- coding: utf-8 -*-
"""לשונית 'צינתוקים' (v2.81) — הודעה קולית אוטומטית לזכאי החלוקה של השבוע
דרך ימות המשיח, מתוך התוכנה.

הזרימה (לפי מסמך ההדמיה שאישר המשתמש): רשימת הזכאים של מסך "חלוקה ורישום"
→ סינון חריגים (בלי מספר / מספר שבור / מספר כפול) → בדיקה למספר של המנהל →
אישור מפורש → שליחה עם מעקב חי (RunCampaign + GetCampaignStatus) → תוצאות
עם "שלח שוב לנכשלים" → היסטוריה מסונכרנת בין שני המחשבים.

הגנות: חסימת שעות אסורות (21:00–08:00, ערב שבת ושבת), שומר שליחה-כפולה
לאותה חלוקה (חוצה-מחשבים, דרך הסנכרון), נעילת הכפתור בזמן שליחה."""
import json
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QMessageBox, QProgressBar, QScrollArea, QDialog, QLineEdit,
    QListWidget, QListWidgetItem, QFileDialog, QInputDialog
)

import database as db
from utils import timefmt, yemot
from utils.ui import busy_cursor, section_header, enable_touch_scroll

_LBL = "background:transparent; border:none;"


class _PollWorker(QThread):
    """Polls the campaign status off the UI thread every few seconds until the
    campaign finishes (or ~15 minutes pass)."""
    tick = pyqtSignal(object)          # status dict | Exception

    def __init__(self, campaign_id: str, parent=None):
        super().__init__(parent)
        self.campaign_id = campaign_id
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        errors = 0
        for _ in range(225):
            if self._stop:
                return
            try:
                st = yemot.get_campaign_status(self.campaign_id)
            except Exception as e:
                errors += 1
                if errors >= 5:
                    self.tick.emit(e)
                    return
                time.sleep(8)
                continue
            errors = 0
            self.tick.emit(st)
            if st.get("finished"):
                return
            for _ in range(8):          # 4s in small slices → stop() is snappy
                if self._stop:
                    return
                time.sleep(0.5)


class _AddPersonDialog(QDialog):
    """Pick an active recipient who is not already on the call list."""

    def __init__(self, exclude_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("הוסף אדם לרשימת הצינתוקים")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(420, 480)
        self.picked = None
        self._all = [r for r in db.get_all_recipients("פעיל")
                     if r["id"] not in exclude_ids]
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("חיפוש לפי שם / טלפון…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(lambda _i: self._accept())
        lay.addWidget(self.listw, 1)
        btns = QHBoxLayout()
        ok = QPushButton("הוסף")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("ביטול")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        btns.addStretch()
        lay.addLayout(btns)
        self._filter()

    def _filter(self):
        text = self.search.text().strip()
        rows = db.filter_recipients(self._all, text, limit=300) if text else self._all[:300]
        self.listw.clear()
        for r in rows:
            phones = yemot.pick_phones(dict(r))
            label = r["full_name"] + ("  ·  " + phones[0] if phones else "  ·  (אין מספר)")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, dict(r))
            self.listw.addItem(it)

    def _accept(self):
        it = self.listw.currentItem()
        if it is None:
            return
        self.picked = it.data(Qt.ItemDataRole.UserRole)
        self.accept()


class TzintukimTab(QWidget):
    """מסך הצינתוקים — ראו docstring של המודול."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main = parent
        self._rows = []           # [{'rec', 'phones', 'chosen', 'checked', 'why'}]
        self._worker = None
        self._active_guid = ""    # DB guid of the campaign being tracked
        self._last_failed = []    # [{'phone','name'}] from the last finished run
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        enable_touch_scroll(scroll)
        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)
        lay.setSpacing(8)
        lay.setContentsMargins(10, 8, 10, 8)

        title = QLabel("צינתוקים — הודעה קולית לזכאי החלוקה")
        title.setObjectName("title")
        lay.addWidget(title)
        sub = QLabel("המערכת לוקחת את רשימת החלוקה הנוכחית ממסך \"חלוקה ורישום\", "
                     "מסננת מי שאין לו מספר תקין, ואחרי אישור שולחת לכולם הודעה "
                     "קולית דרך ימות המשיח. חריגים לא נשלחים.")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Not-configured banner (hidden once credentials exist).
        self.banner = QFrame()
        self.banner.setStyleSheet("QFrame{background:#fef3e2; border:1px solid #f7d9a5;"
                                  "border-radius:8px;}")
        b_lay = QHBoxLayout(self.banner)
        b_lay.setContentsMargins(10, 6, 10, 6)
        b_txt = QLabel("עוד לא הוזנו פרטי הגישה לימות המשיח — בלעדיהם אי אפשר לשלוח.")
        b_txt.setStyleSheet("color:#92600a; font-weight:600; " + _LBL)
        b_txt.setWordWrap(True)
        b_lay.addWidget(b_txt, 1)
        b_btn = QPushButton("פתח הגדרות")
        b_btn.setObjectName("neutral")
        b_btn.clicked.connect(self._goto_settings)
        b_lay.addWidget(b_btn)
        lay.addWidget(self.banner)

        # Metric chips: eligible / ready / exceptions.
        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.m_total = self._metric("זכאים השבוע", "#eaf3f0", "#0f766e")
        self.m_ready = self._metric("מוכנים לשליחה", "#e1f5ee", "#0f6e56")
        self.m_bad = self._metric("חריגים", "#fef3e2", "#92600a")
        for m in (self.m_total, self.m_ready, self.m_bad):
            metrics.addWidget(m["frame"], 1)
        lay.addLayout(metrics)

        # Recipients table.
        list_frame = QFrame()
        list_frame.setObjectName("panel")
        lf_lay = QVBoxLayout(list_frame)
        lf_lay.setContentsMargins(10, 7, 10, 7)
        lf_lay.setSpacing(6)
        lf_lay.addWidget(section_header("רשימת נמענים", "phone", "#0f766e"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "שם", "טלפון", "סטטוס"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Fixed width: ResizeToContents ignores cell widgets, so the phone
        # combo would get clipped to a few digits.
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 180)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        # Rows tall enough for the themed phone-combo (it overflows 30px rows).
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setMinimumHeight(260)
        self.table.itemChanged.connect(self._on_item_changed)
        lf_lay.addWidget(self.table)
        hint = QLabel("☑ = יקבל צינתוק. אפשר לבטל סימון למי שלא רוצים לצלצל אליו, "
                      "ולבחור מספר אחר למי שיש כמה.")
        hint.setObjectName("subtitle")
        lf_lay.addWidget(hint)
        lay.addWidget(list_frame)

        # Recording + actions row.
        act_frame = QFrame()
        act_frame.setObjectName("panel")
        a_lay = QVBoxLayout(act_frame)
        a_lay.setContentsMargins(10, 7, 10, 7)
        a_lay.setSpacing(6)
        a_lay.addWidget(section_header("הודעה ושליחה", "update", "#0f766e"))
        self.lbl_rec = QLabel("")
        self.lbl_rec.setObjectName("subtitle")
        self.lbl_rec.setWordWrap(True)
        a_lay.addWidget(self.lbl_rec)
        row = QHBoxLayout()
        btn_add = QPushButton("➕ הוסף אדם")
        btn_add.setObjectName("neutral")
        btn_add.clicked.connect(self._add_person)
        row.addWidget(btn_add)
        btn_upload = QPushButton("העלה קובץ הקלטה…")
        btn_upload.setObjectName("neutral")
        btn_upload.setToolTip("קובץ שמע (WAV/MP3) שיושמע בצינתוק — מומר אוטומטית "
                              "לפורמט הטלפוני בשרת של ימות")
        btn_upload.clicked.connect(self._upload_recording)
        row.addWidget(btn_upload)
        btn_test = QPushButton("▶ שלח בדיקה למספר שלי")
        btn_test.setObjectName("neutral")
        btn_test.setToolTip("מצלצל רק אליך, כדי לשמוע איך ההודעה נשמעת לפני "
                            "השליחה לכולם")
        btn_test.clicked.connect(self._send_test)
        row.addWidget(btn_test)
        row.addStretch()
        self.btn_send = QPushButton("")
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        a_lay.addLayout(row)

        # Live-progress strip (hidden until a campaign runs).
        self.prog_frame = QFrame()
        self.prog_frame.setStyleSheet("QFrame{background:#f3f8f6; border:1px solid #e3ede9;"
                                      "border-radius:8px;}")
        p_lay = QVBoxLayout(self.prog_frame)
        p_lay.setContentsMargins(10, 6, 10, 6)
        p_lay.setSpacing(4)
        self.lbl_prog = QLabel("")
        self.lbl_prog.setStyleSheet("font-weight:600; color:#0f766e; " + _LBL)
        p_lay.addWidget(self.lbl_prog)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(12)
        p_lay.addWidget(self.progress)
        counters = QHBoxLayout()
        self.lbl_conf = QLabel("")
        self.lbl_conf.setStyleSheet("color:#166534; font-weight:700; " + _LBL)
        self.lbl_done = QLabel("")
        self.lbl_done.setStyleSheet("color:#0f6e56; font-weight:600; " + _LBL)
        self.lbl_fail = QLabel("")
        self.lbl_fail.setStyleSheet("color:#a32d2d; font-weight:600; " + _LBL)
        self.lbl_wait = QLabel("")
        self.lbl_wait.setStyleSheet("color:#5f6d69; " + _LBL)
        for w in (self.lbl_conf, self.lbl_done, self.lbl_fail, self.lbl_wait):
            counters.addWidget(w)
        counters.addStretch()
        self.btn_resend = QPushButton("🔄 שלח שוב לנכשלים")
        self.btn_resend.setObjectName("neutral")
        self.btn_resend.clicked.connect(self._resend_failed)
        self.btn_resend.setVisible(False)
        counters.addWidget(self.btn_resend)
        p_lay.addLayout(counters)
        self.prog_frame.setVisible(False)
        a_lay.addWidget(self.prog_frame)
        lay.addWidget(act_frame)

        # History.
        hist_frame = QFrame()
        hist_frame.setObjectName("panel")
        h_lay = QVBoxLayout(hist_frame)
        h_lay.setContentsMargins(10, 7, 10, 7)
        h_lay.setSpacing(6)
        h_lay.addWidget(section_header("היסטוריית צינתוקים", "calendar", "#0f766e"))
        self.hist = QTableWidget(0, 6)
        self.hist.setHorizontalHeaderLabels(
            ["מתי", "שם", "נשלחו", "הצליחו", "אישרו הגעה", "נכשלו"])
        self.hist.verticalHeader().setVisible(False)
        self.hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh2 = self.hist.horizontalHeader()
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4, 5):
            hh2.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.hist.setMinimumHeight(140)
        h_lay.addWidget(self.hist)
        lay.addWidget(hist_frame)
        lay.addStretch()

    def _metric(self, label, bg, fg):
        frame = QFrame()
        frame.setStyleSheet(f"QFrame{{background:{bg}; border-radius:10px;}}")
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(0)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{fg}; font-size:13px; " + _LBL)
        val = QLabel("0")
        val.setStyleSheet(f"color:{fg}; font-size:24px; font-weight:700; " + _LBL)
        v.addWidget(lbl)
        v.addWidget(val)
        return {"frame": frame, "val": val}

    # ── List building ─────────────────────────────────────────────────────────

    def refresh(self):
        """Rebuild the call list from the CURRENT distribution list (the same
        rows the 'חלוקה ורישום' screen shows, minus the reserve section)."""
        self.banner.setVisible(not yemot.is_configured())
        base = self._distribution_rows()
        manual = [r for r in self._rows if r.get("manual")]
        manual_ids = {r["rec"].get("id") for r in manual}
        self._rows = []
        for rec in base:
            if rec.get("id") in manual_ids:
                manual = [m for m in manual if m["rec"].get("id") != rec.get("id")]
            self._rows.append(self._make_row(rec))
        self._rows.extend(manual)      # keep hand-added people across refreshes
        self._flag_duplicates()
        self._populate()
        self._refresh_recording_label()
        self._refresh_history()
        self._maybe_resume_tracking()

    def _distribution_rows(self):
        gt = getattr(self.main, "group_tab", None)
        if gt is None:
            return []
        try:
            if not gt._rows_data:
                gt.refresh()
        except Exception:
            pass
        reserve_ids = getattr(gt, "_reserve_ids", set()) or set()
        return [dict(r) for r in (gt._rows_data or [])
                if not r.get("_reserve") and r.get("id") not in reserve_ids]

    def _make_row(self, rec: dict, manual: bool = False) -> dict:
        phones = yemot.pick_phones(rec)
        raw_any = any((rec.get(f) or "").strip()
                      for f in ("phone1", "phone2", "phone3"))
        why = "" if phones else ("מספר לא תקין" if raw_any else "אין מספר טלפון")
        return {"rec": rec, "phones": phones, "chosen": phones[0] if phones else "",
                "checked": bool(phones), "why": why, "manual": manual}

    def _flag_duplicates(self):
        """Two list rows with the SAME chosen number: the first stays, the rest
        become unchecked exceptions (one household — one call)."""
        seen = {}
        for row in self._rows:
            if not row["chosen"]:
                continue
            first = seen.get(row["chosen"])
            if first is None:
                seen[row["chosen"]] = row
                if row["why"].startswith("אותו מספר"):
                    row["why"] = ""
            else:
                row["checked"] = False
                row["why"] = f"אותו מספר כמו {first['rec'].get('full_name', '')}"

    def _populate(self):
        self.table.blockSignals(True)
        # Full reset: clearContents also drops previous cell widgets (leftover
        # phone combos would otherwise float over the repopulated table).
        self.table.clearContents()
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            rec = row["rec"]
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if row["checked"]
                              else Qt.CheckState.Unchecked)
            if not row["phones"]:
                chk.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(i, 0, chk)
            name = QTableWidgetItem(rec.get("full_name") or "")
            if row["manual"]:
                name.setText((rec.get("full_name") or "") + "  (נוסף ידנית)")
            self.table.setItem(i, 1, name)
            if len(row["phones"]) > 1:
                combo = QComboBox()
                combo.addItems(row["phones"])
                combo.setCurrentText(row["chosen"])
                combo.setFixedHeight(40)
                combo.currentTextChanged.connect(
                    lambda text, r=row: self._choose_phone(r, text))
                self.table.setCellWidget(i, 2, combo)
            else:
                self.table.setItem(i, 2, QTableWidgetItem(row["chosen"] or "—"))
            status = QTableWidgetItem("מוכן" if row["checked"] and row["phones"]
                                      else ("⚠ " + row["why"] if row["why"] else "לא נשלח"))
            if row["why"]:
                status.setForeground(Qt.GlobalColor.darkYellow)
            self.table.setItem(i, 3, status)
        self.table.blockSignals(False)
        self._update_metrics()

    def _choose_phone(self, row, text):
        row["chosen"] = text
        self._flag_duplicates()
        # Deferred: repopulating destroys the combo that emitted this signal —
        # rebuilding it synchronously mid-emit is a crash risk.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._populate)

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        i = item.row()
        if 0 <= i < len(self._rows):
            self._rows[i]["checked"] = item.checkState() == Qt.CheckState.Checked
            self._update_metrics()

    def _update_metrics(self):
        total = len(self._rows)
        ready = len(self._ready_rows())
        bad = sum(1 for r in self._rows if r["why"])
        self.m_total["val"].setText(str(total))
        self.m_ready["val"].setText(str(ready))
        self.m_bad["val"].setText(str(bad))
        self.btn_send.setText(f"אשר ושלח ל-{ready} »" if ready else "אין למי לשלוח")
        self.btn_send.setEnabled(ready > 0 and self._worker is None)

    def _ready_rows(self):
        return [r for r in self._rows if r["checked"] and r["chosen"]]

    # ── Actions ───────────────────────────────────────────────────────────────

    def _goto_settings(self):
        if self.main and hasattr(self.main, "navigate_to_tab"):
            self.main.navigate_to_tab(self.main.settings_tab)

    def _add_person(self):
        dlg = _AddPersonDialog({r["rec"].get("id") for r in self._rows}, self)
        if dlg.exec() and dlg.picked:
            self._rows.append(self._make_row(dlg.picked, manual=True))
            self._flag_duplicates()
            self._populate()

    def _refresh_recording_label(self):
        tid = (db.get_setting(yemot.SET_TEMPLATE) or "").strip()
        confirm_tip = ("\n💡 כדאי לומר בסוף ההקלטה: \"לאישור הגעה — הקש 7, "
                       "לשמיעה חוזרת — הקש 1\". מי שיקיש 7 יסומן בתוכנה "
                       "כ\"אישר הגעה\" (המקשים קבועים ע\"י ימות המשיח).")
        if not yemot.is_configured():
            self.lbl_rec.setText("ההודעה המושמעת: תוגדר אחרי חיבור המערכת (בהגדרות).")
        elif tid:
            self.lbl_rec.setText(
                f"ההודעה המושמעת שמורה בימות המשיח (תבנית {tid}). "
                "להחלפה — העלה קובץ הקלטה, ואז \"שלח בדיקה\" כדי לשמוע אותה."
                + confirm_tip)
        else:
            self.lbl_rec.setText(
                "עוד לא הוגדרה הודעה: העלה קובץ הקלטה (או שלח בדיקה — התבנית "
                "תיווצר אוטומטית ותוכל להקליט דרך ימות)." + confirm_tip)

    def _require_config(self) -> bool:
        if yemot.is_configured():
            return True
        QMessageBox.information(
            self, "צינתוקים",
            "עוד לא הוזנו פרטי הגישה לימות המשיח.\n"
            "בהגדרות ← \"צינתוקים (ימות המשיח)\" — הזן מספר מערכת וסיסמה.")
        self._goto_settings()
        return False

    def _upload_recording(self):
        if not self._require_config():
            return
        path, _f = QFileDialog.getOpenFileName(
            self, "בחר קובץ הקלטה", "", "קובצי שמע (*.wav *.mp3);;כל הקבצים (*.*)")
        if not path:
            return
        with busy_cursor():
            try:
                yemot.upload_message_wav(path)
                ok, msg = True, ("ההקלטה הועלתה בהצלחה ✓\n"
                                 "שלח בדיקה למספר שלך כדי לשמוע אותה בטלפון.")
            except yemot.YemotError as e:
                ok, msg = False, str(e)
            except Exception as e:
                ok, msg = False, f"ההעלאה נכשלה: {e}"
        (QMessageBox.information if ok else QMessageBox.warning)(self, "העלאת הקלטה", msg)
        self._refresh_recording_label()

    def _send_test(self):
        if not self._require_config():
            return
        phone = (db.get_setting(yemot.SET_TEST_PHONE) or "").strip()
        if not yemot.normalize_phone(phone):
            phone, okd = QInputDialog.getText(
                self, "שליחת בדיקה", "לאיזה מספר לצלצל? (המספר שלך)")
            if not okd or not yemot.normalize_phone(phone):
                if okd:
                    QMessageBox.warning(self, "שליחת בדיקה", "המספר שהוזן אינו תקין.")
                return
            db.set_setting(yemot.SET_TEST_PHONE, phone.strip())
        with busy_cursor():
            try:
                yemot.run_test(phone)
                ok, msg = True, f"📞 מצלצל אליך עכשיו ({phone}) — ענה ותשמע את ההודעה."
            except yemot.YemotError as e:
                ok, msg = False, str(e)
            except Exception as e:
                ok, msg = False, f"השליחה נכשלה: {e}"
        (QMessageBox.information if ok else QMessageBox.warning)(self, "שליחת בדיקה", msg)

    def _send(self):
        if not self._require_config():
            return
        reason = yemot.send_block_reason()
        if reason:
            QMessageBox.warning(self, "צינתוקים", reason + " — נסה שוב בשעות המותרות.")
            return
        rows = self._ready_rows()
        phones = {}
        for r in rows:
            phones.setdefault(r["chosen"], r["rec"].get("full_name") or "")
        if not phones:
            QMessageBox.warning(self, "צינתוקים", "אין אף נמען מסומן עם מספר תקין.")
            return
        dist_date = db.next_wednesday().isoformat()
        prev = db.tzintuk_campaign_for_date(dist_date)
        extra = ""
        if prev:
            when = timefmt.datetime_str(prev.get("sent_at") or "")
            src = prev.get("device") or "מחשב אחר"
            extra = (f"\n\n⚠ שים לב: כבר נשלח צינתוק לחלוקה של תאריך זה "
                     f"({when}, מ{src}). שליחה נוספת תצלצל לאנשים פעם שנייה!")
        bad = sum(1 for r in self._rows if r["why"])
        ans = QMessageBox.question(
            self, "אישור שליחה",
            f"עומד לשלוח הודעה קולית ל-{len(phones)} נמענים.\n"
            f"חריגים שלא יישלחו: {bad}.\n"
            f"עלות משוערת: כ-{len(phones)} יחידות.\n"
            f"מי שיקיש 7 בשיחה יסומן בתוכנה כ\"אישר הגעה\".{extra}\n\nלשלוח עכשיו?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.btn_send.setEnabled(False)      # locked until the campaign ends
        self.btn_send.setText("שולח…")
        with busy_cursor():
            try:
                template_id = yemot.ensure_template()
                res = yemot.run_campaign(phones, template_id)
            except yemot.YemotError as e:
                QMessageBox.warning(self, "צינתוקים", str(e))
                self._update_metrics()
                return
            except Exception as e:
                QMessageBox.warning(self, "צינתוקים", f"השליחה נכשלה: {e}")
                self._update_metrics()
                return
        from utils import sync
        name = f"חלוקה של {db.next_wednesday().strftime('%d/%m/%Y')}"
        self._active_guid = db.add_tzintuk_campaign(
            name, dist_date, template_id, str(res.get("campaignId") or ""),
            int(res.get("entriesCount") or len(phones)),
            device=sync.device_name() or "")
        self._refresh_history()
        self._start_tracking(str(res.get("campaignId") or ""), len(phones))

    def _resend_failed(self):
        if not self._last_failed:
            return
        phones = {e["phone"]: e.get("name") or "" for e in self._last_failed
                  if e.get("phone")}
        if not phones:
            return
        reason = yemot.send_block_reason()
        if reason:
            QMessageBox.warning(self, "צינתוקים", reason + " — נסה שוב בשעות המותרות.")
            return
        ans = QMessageBox.question(
            self, "שליחה חוזרת",
            f"לשלוח שוב ל-{len(phones)} שנכשלו בסבב הקודם?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.btn_resend.setVisible(False)
        with busy_cursor():
            try:
                template_id = yemot.ensure_template()
                res = yemot.run_campaign(phones, template_id)
            except Exception as e:
                QMessageBox.warning(self, "צינתוקים", f"השליחה נכשלה: {e}")
                return
        from utils import sync
        dist_date = db.next_wednesday().isoformat()
        self._active_guid = db.add_tzintuk_campaign(
            f"שליחה חוזרת לנכשלים ({len(phones)})", dist_date, template_id,
            str(res.get("campaignId") or ""), len(phones),
            device=sync.device_name() or "")
        self._refresh_history()
        self._start_tracking(str(res.get("campaignId") or ""), len(phones))

    # ── Live tracking ─────────────────────────────────────────────────────────

    def _start_tracking(self, campaign_id: str, total: int):
        self.prog_frame.setVisible(True)
        self.btn_resend.setVisible(False)
        self.lbl_prog.setText("שולח בזמן אמת… אפשר להמשיך לעבוד, אל תסגור את התוכנה")
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.lbl_conf.setText("✓ אישרו הגעה 0")
        self.lbl_done.setText("הצליחו 0")
        self.lbl_fail.setText("נכשלו 0")
        self.lbl_wait.setText(f"ממתינים {total}")
        self._worker = _PollWorker(campaign_id, self)
        self._worker.tick.connect(self._on_tick)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()
        self._update_metrics()

    def _on_tick(self, st):
        if isinstance(st, Exception):
            self.lbl_prog.setText("החיבור למעקב נכשל — הקמפיין ממשיך לרוץ בימות; "
                                  "התוצאות יתעדכנו בכניסה הבאה ללשונית.")
            return
        done = st["delivered"] + st["failed"]
        self.progress.setRange(0, max(1, st["total"]))
        self.progress.setValue(min(done, st["total"]))
        self.lbl_conf.setText(f"✓ אישרו הגעה {st.get('confirmed', 0)}")
        self.lbl_done.setText(f"הצליחו {st['delivered']}")
        self.lbl_fail.setText(f"נכשלו {st['failed']}")
        self.lbl_wait.setText(f"ממתינים {st['pending']}")
        # The DB (and the sync journal) get ONE update — at the end. Journaling
        # every 4-second tick would spam the shared Drive folder for nothing;
        # the live numbers live in this strip until then.
        if st.get("finished") and self._active_guid:
            db.update_tzintuk_campaign(
                self._active_guid, st["delivered"], st["failed"], "done",
                json.dumps(st.get("entries") or [], ensure_ascii=False))
        if st.get("finished"):
            self._last_failed = [e for e in st.get("entries") or [] if e.get("failed")]
            self.lbl_prog.setText(
                f"הקמפיין הסתיים ✓ — {st['delivered']} קיבלו את ההודעה "
                f"(מתוכם {st.get('confirmed', 0)} אישרו הגעה בהקשה), "
                f"{st['failed']} נכשלו.")
            self.btn_resend.setText(f"🔄 שלח שוב ל-{len(self._last_failed)} שנכשלו")
            self.btn_resend.setVisible(bool(self._last_failed))
            self._apply_results_to_table(st.get("entries") or [])
            self._refresh_history()
            # The confirmation badges on the "חלוקה ורישום" list come from the
            # stored report — repaint it so they appear without a tab switch.
            gt = getattr(self.main, "group_tab", None)
            if gt is not None:
                try:
                    gt._populate()
                except Exception:
                    pass

    def _apply_results_to_table(self, entries):
        """Write each person's final result into the status column, so the
        operator sees WHO confirmed (pressed 7), who just got the call, and
        who failed — matched by the number that was dialed."""
        by_phone = {e.get("phone"): e for e in entries if e.get("phone")}
        self.table.blockSignals(True)
        for i, row in enumerate(self._rows):
            e = by_phone.get(row.get("chosen"))
            if e is None or i >= self.table.rowCount():
                continue
            if e.get("confirmed"):
                txt, color = "✓ אישר הגעה", QColor("#166534")
            elif e.get("ok"):
                txt, color = "קיבל את ההודעה", QColor("#0f6e56")
            elif e.get("failed"):
                txt, color = "⚠ לא נענה / נכשל", QColor("#a32d2d")
            else:
                continue
            it = QTableWidgetItem(txt)
            it.setForeground(color)
            self.table.setItem(i, 3, it)
        self.table.blockSignals(False)

    def _on_worker_done(self):
        self._worker = None
        self._update_metrics()

    def _maybe_resume_tracking(self):
        """The app (or the tab) was closed mid-campaign: the newest record is
        still 'sending'. Pick its tracking back up so the results get written —
        works also for a campaign the OTHER computer started (same account)."""
        if self._worker is not None or not yemot.is_configured():
            return
        camps = db.get_tzintuk_campaigns(limit=1)
        if (camps and camps[0].get("status") == "sending"
                and camps[0].get("campaign_id")):
            self._active_guid = camps[0]["guid"]
            self._start_tracking(camps[0]["campaign_id"],
                                 int(camps[0].get("total") or 0))

    # ── History ───────────────────────────────────────────────────────────────

    def _refresh_history(self):
        camps = db.get_tzintuk_campaigns(limit=100)
        self.hist.setRowCount(len(camps))
        status_he = {"sending": "בתהליך", "done": "הסתיים"}
        for i, c in enumerate(camps):
            when = timefmt.datetime_str(c.get("sent_at") or "")
            src = c.get("device") or ""
            self.hist.setItem(i, 0, QTableWidgetItem(when + (f"  ({src})" if src else "")))
            name = c.get("name") or ""
            st = status_he.get(c.get("status") or "", c.get("status") or "")
            self.hist.setItem(i, 1, QTableWidgetItem(f"{name} — {st}"))
            self.hist.setItem(i, 2, QTableWidgetItem(str(c.get("total") or 0)))
            self.hist.setItem(i, 3, QTableWidgetItem(str(c.get("delivered") or 0)))
            conf = QTableWidgetItem(str(self._confirmed_count(c)))
            conf.setForeground(QColor("#166534"))
            self.hist.setItem(i, 4, conf)
            self.hist.setItem(i, 5, QTableWidgetItem(str(c.get("failed") or 0)))

    @staticmethod
    def _confirmed_count(camp: dict) -> int:
        """How many pressed the confirm key — derived from the stored report
        (no DB column; the report is synced so both computers agree)."""
        try:
            entries = json.loads(camp.get("report_json") or "[]")
        except ValueError:
            return 0
        return sum(1 for e in entries or []
                   if isinstance(e, dict)
                   and (e.get("confirmed")
                        or str(e.get("status") or "").lower() == "accepted"))

# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 2: נעילת רשימות, צד המסך (docs/plans/הכנה_קדימה_נעילה.md, סעיפים 4 ו-6).

`PlanLockMixin` מצורף ל-`GroupUpdateTab`. הוא מחזיק את כל מה שקשור לנעילה — מצב, כפתור, באנר,
צ'יפים, כתיבה מיידית, השוואה לנתונים החיים ו"חלון התכנונים" — כדי שהקובץ הגדול של המסך יקבל רק
נקודות חיבור קטנות. כל הנתונים עוברים דרך הפונקציות של `database.py` (get_plan/save_plan/…),
והנעילה היא שכבת קריאה בלבד: שום קוד כאן לא כותב last/next_distribution או את ההגדרות הגלובליות
של השבוע האמיתי (`weekly_extra_ids`, `available_products`, `reserve_count`).

מצב נעילה (`self._plan` לא None): הרשימה מוצגת מהנעילה, ארבעת המכלים של המסך (`_extra_ids`,
`_reserve_ids`, `_removed_ids`, `_row_notes`) נגזרים ממנה בכל רענון, וכל עריכה נכתבת מיד לנעילה.
ההסרות וההערות של "הטיוטה" (זיכרון בלבד) נשמרות בצד (`_plan_stash`) ומוחזרות ביציאה מהמצב.
"""
import copy
from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout)

import database as db
import selection

# הגרסה הראשונה שמכבדת נעילות (S0–S3 ב-"גרסה X"). מחשב שני שמדווח על גרסה ישנה יותר לא יכבד אותן,
# ולכן הכפתור נעול עד שיתעדכן (סעיף 5.4). לעדכן אם מספר הגרסה של השחרור שונה.
PLAN_MIN_VERSION = "3.84"

_ALIGN_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_LBL = "background:transparent; border:none;"
_CHIP_LOCK = ("QLabel{background:#d3ede1; color:#064e3b; border:none; border-radius:16px;"
              " padding:6px 14px; font-size:13px; font-weight:700;}")
_CHIP_STALE = ("QLabel{background:#fde2e2; color:#991b1b; border:none; border-radius:16px;"
               " padding:6px 14px; font-size:13px; font-weight:700;}")
_BANNER = ("QFrame#plan_banner{background:#e6f4ee; border:1px solid #9bd3b7; border-radius:10px;}")
_BTN_SMALL = ("QPushButton{background:#ffffff; color:#0f766e; border:1px solid #9bd3b7;"
              " border-radius:8px; padding:5px 12px; font-size:12.5px; font-weight:700;}"
              "QPushButton:hover{background:#f0faf5;} QPushButton:disabled{color:#94a3b8;}")
_AUTO_BANNER = ("QFrame#autoreg_banner{background:#fff7e0; border:1px solid #f2c46d; border-radius:10px;}")
_BTN_LOCK = ("QPushButton{background:#0f766e; color:#ffffff; border:none; border-radius:10px;"
             " padding:8px 18px; font-size:14px; font-weight:800;}"
             "QPushButton:hover{background:#0d6d65;} QPushButton:disabled{background:#cbd5e1; color:#64748b;}")


def _ver(s):
    try:
        return tuple(int(x) for x in str(s).strip().split("."))
    except (TypeError, ValueError):
        return None


def _fmt_wed(w) -> str:
    return w.strftime("%d/%m")


def _local_hm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _local_stamp(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        return dt.strftime("%H:%M (%d/%m)")
    except (TypeError, ValueError):
        return ""


class PlanLockMixin:
    # ═══ מצב ═══════════════════════════════════════════════════════════════════
    def _plan_init(self):
        self._plan = None            # the LIVE lock on screen (dict) or None
        self._plan_stash = None      # the draft's memory-only state, put aside while a lock is shown
        self._plan_info = {}         # {'missing': n, 'inactive': n} of the loaded lock
        self._plan_cmp = None        # comparison with the live data (S4c)

    def _plan_mode(self) -> bool:
        return getattr(self, "_plan", None) is not None

    def _today(self):
        return date.today()

    def _plan_week(self):
        """The Wednesday a lock on this screen would belong to — the week of the date on
        screen — or None for a past date / retroactive entry (no locks there)."""
        try:
            chosen = date.fromisoformat(self.date_edit.get_iso())
        except (ValueError, TypeError):
            return None
        wk = selection.upcoming_wednesday(chosen)
        if wk < selection.upcoming_wednesday(self._today()):
            return None
        return wk

    def _sync_plan(self):
        """Decide (on every refresh) whether the screen's week has a LIVE lock, and swap the
        draft state in/out when that changes. Always re-reads the database, so a lock made
        or edited on the other computer shows up with the sync refresh."""
        wk = self._plan_week()
        plan = None
        if wk is not None:
            cand = db.get_plan(wk)
            if cand is not None and db.plan_states(self._today()).get(wk) in ("current", "future"):
                plan = cand
        was = self._plan
        if plan is not None and was is None:
            self._plan_stash = {"removed": set(self._removed_ids), "notes": dict(self._row_notes)}
        elif plan is None and was is not None:
            self._plan_leave(reload=False)
        self._plan = plan
        return plan

    def _plan_leave(self, reload=True):
        """Back to the draft: its memory-only removals / notes return, the picks are
        re-read from the (never touched) shared settings."""
        st = self._plan_stash
        if st is not None:
            self._removed_ids = set(st.get("removed", ()))
            self._row_notes = dict(st.get("notes", {}))
        self._plan_stash = None
        self._plan = None
        if reload:
            self._load_extras()

    def _refresh_locked(self, plan):
        """refresh() for a week that has a live lock: show the lock, not a computed list."""
        ld = self._list_date()
        rows, info = db.plan_rows(plan, on_date=ld)
        self._plan_info = info
        self._rows_data = rows
        self._extra_ids = {r["id"] for r in rows if r.get("_extra")}
        self._reserve_ids = {r["id"] for r in rows if r.get("_reserve")}
        self._row_notes = {r["id"]: r["_plan_note"] for r in rows if r.get("_plan_note")}
        removed = set()
        for g in plan.get("removed", []):
            rec = db.get_recipient_by_guid(g)
            if rec and rec.get("id") is not None:
                removed.add(rec["id"])
        self._removed_ids = removed
        for spin, value in ((self.products_spin, plan.get("products", 0)),
                            (self.reserve_spin, plan.get("reserve", 0))):
            spin.blockSignals(True)
            spin.setValue(int(value or 0))
            spin.blockSignals(False)
        self._sched_cut = None
        self._removed_due = 0
        n_res = sum(1 for r in rows if r.get("_reserve"))
        self.lbl_regulars_count.setText(f"רשימה נעולה: {len(rows) - n_res}"
                                        + (f" + {n_res} רזרבה" if n_res else ""))
        live = {r.get("id") for r in rows}
        self._seen_ids = set(live)
        if ld is None:
            self._checked_ids &= live
        self._populate()
        self._update_leftover_hint()
        self._update_mode_controls()
        self._sync_future_note()
        self._plan_compare()
        self._plan_refresh_ui()
        self._mark_dependents_stale()

    # ═══ בניית הווידג'טים (נקראת מ-_build_ui) ═══════════════════════════════════
    def _plan_make_chips(self, head):
        self.chip_plans = QLabel("")
        self.chip_plans.setObjectName("chip_plans")
        self.chip_plans.setStyleSheet(_CHIP_LOCK)
        self.chip_plans.setVisible(False)
        head.addWidget(self.chip_plans)
        self.chip_plans_stale = QLabel("")
        self.chip_plans_stale.setObjectName("chip_plans_stale")
        self.chip_plans_stale.setStyleSheet(_CHIP_STALE)
        self.chip_plans_stale.setVisible(False)
        head.addWidget(self.chip_plans_stale)
        self.btn_plans_list = QPushButton("📋 תכנונים")
        self.btn_plans_list.setObjectName("btn_plans_list")
        self.btn_plans_list.setStyleSheet(_BTN_SMALL)
        self.btn_plans_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_plans_list.setToolTip("כל הרשימות הנעולות: פתיחה, מחיקה והעתקה לנעילה חדשה")
        self.btn_plans_list.clicked.connect(self._open_plans_dialog)
        head.addWidget(self.btn_plans_list)

    def _plan_make_banner(self, lay):
        self.plan_banner_frame = QFrame()
        self.plan_banner_frame.setObjectName("plan_banner")
        self.plan_banner_frame.setStyleSheet(_BANNER)
        self.plan_banner_frame.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        outer = QVBoxLayout(self.plan_banner_frame)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        outer.addLayout(row)
        self.lbl_plan_banner = QLabel("")
        self.lbl_plan_banner.setObjectName("lbl_plan_banner")
        self.lbl_plan_banner.setWordWrap(True)
        self.lbl_plan_banner.setAlignment(_ALIGN_R)
        self.lbl_plan_banner.setStyleSheet(
            "color:#064e3b; font-size:13px; font-weight:700; " + _LBL)
        row.addWidget(self.lbl_plan_banner, 1)
        self.btn_plan_refresh = QPushButton("עדכן מהנתונים")
        self.btn_plan_refresh.setObjectName("btn_plan_refresh")
        self.btn_plan_refresh.setStyleSheet(_BTN_SMALL)
        self.btn_plan_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_plan_refresh.setToolTip("משווה לנתונים החיים ומציע להוסיף / להסיר — לעולם לא משנה לבד")
        self.btn_plan_refresh.clicked.connect(self._plan_apply_compare)
        row.addWidget(self.btn_plan_refresh)
        # RULE 11 — the per-lock switch of the automatic registration
        self.chk_plan_autoreg = QCheckBox("")
        self.chk_plan_autoreg.setObjectName("chk_plan_autoreg")
        self.chk_plan_autoreg.setStyleSheet("color:#064e3b; font-size:12.5px; font-weight:700; " + _LBL)
        self.chk_plan_autoreg.setToolTip("ביום החלוקה (חמישי בבוקר) הרשימה הנעולה נרשמת לבד כמי שקיבלו — "
                                         "מי שלא הגיע מתקנים אחר כך. לחלוקה שבוטלה: להסיר את הסימון.")
        self.chk_plan_autoreg.toggled.connect(self._on_plan_autoreg_toggled)
        outer.addWidget(self.chk_plan_autoreg)
        self.plan_banner_frame.setVisible(False)
        lay.addWidget(self.plan_banner_frame)
        # the notice that a list registered ITSELF (stays until confirmed / corrected / 21 days)
        self.autoreg_banner_frame = QFrame()
        self.autoreg_banner_frame.setObjectName("autoreg_banner")
        self.autoreg_banner_frame.setStyleSheet(_AUTO_BANNER)
        self.autoreg_banner_frame.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        arow = QHBoxLayout(self.autoreg_banner_frame)
        arow.setContentsMargins(14, 8, 14, 8)
        arow.setSpacing(10)
        self.lbl_autoreg = QLabel("")
        self.lbl_autoreg.setObjectName("lbl_autoreg")
        self.lbl_autoreg.setWordWrap(True)
        self.lbl_autoreg.setAlignment(_ALIGN_R)
        self.lbl_autoreg.setStyleSheet("color:#7c4a03; font-size:13px; font-weight:700; " + _LBL)
        arow.addWidget(self.lbl_autoreg, 1)
        self.btn_autoreg_ok = QPushButton("הכול נכון ✓")
        self.btn_autoreg_ok.setObjectName("btn_autoreg_ok")
        self.btn_autoreg_ok.setStyleSheet(_BTN_SMALL)
        self.btn_autoreg_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_autoreg_ok.setToolTip("הרישום האוטומטי נכון (כולם הגיעו) — מסתיר את ההודעה")
        self.btn_autoreg_ok.clicked.connect(self._autoreg_confirm)
        arow.addWidget(self.btn_autoreg_ok)
        self.autoreg_banner_frame.setVisible(False)
        self._autoreg_pending = []
        lay.addWidget(self.autoreg_banner_frame)

    def _plan_make_button(self, bar):
        self.btn_lock_plan = QPushButton("🔒 נעל רשימה")
        self.btn_lock_plan.setObjectName("btn_lock_plan")
        self.btn_lock_plan.setStyleSheet(_BTN_LOCK)
        self.btn_lock_plan.setMinimumHeight(46)
        self.btn_lock_plan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock_plan.clicked.connect(self._on_lock_clicked)
        bar.addWidget(self.btn_lock_plan)

    # ═══ תצוגה: כפתור, באנר, צ'יפים ═════════════════════════════════════════════
    def _plan_peer_block(self) -> str:
        """Why locking is closed: another computer reports a version that does not honour
        locks (it would list a locked family again). '' = open (also with sync off)."""
        need = _ver(PLAN_MIN_VERSION)
        for _dev, (ver, name) in db.peer_app_versions().items():
            vt = _ver(ver)
            if vt is None or vt < need:
                who = f" ({name})" if name else ""
                return (f"המחשב השני{who} עדיין בגרסה {ver or 'ישנה'} — הוא לא יכבד נעילות. "
                        "עדכן אותו קודם.")
        return ""

    def _plan_lock_block_reason(self) -> str:
        if self._plan_week() is None:
            return "נעילה אפשרית רק לחלוקה הקרובה או לשבוע עתידי"
        if self._active_holiday() or self.chk_bonus.isChecked():
            return "נעילה רק לחלוקה רגילה (לא חלוקת חג ולא בונוס)"
        if self.products_spin.value() <= 0:
            return "הקלד קודם כמה מוצרים זמינים"
        if not self._rows_data:
            return "אין מקבלים ברשימה לנעילה"
        return self._plan_peer_block()

    def _plan_refresh_ui(self):
        states = db.plan_states(self._today())
        live = sorted(w for w, s in states.items() if s in ("current", "future"))
        stale = sorted(w for w, s in states.items()
                       if s == "stale" and (self._today() - w).days <= 21)
        self.chip_plans.setVisible(bool(live))
        if live:
            self.chip_plans.setText("🔒 נעולות: " + " · ".join(_fmt_wed(w) for w in live))
            self.chip_plans.setToolTip("רשימות נעולות — מי שבהן לא ייכנס לשבוע אחר בטווח התדירות שלו")
        self.chip_plans_stale.setVisible(bool(stale))
        if stale:
            self.chip_plans_stale.setText("⚠ פגה: " + " · ".join(_fmt_wed(w) for w in stale))
            self.chip_plans_stale.setToolTip("תכנון שהשבוע שלו עבר ולא נרשמה חלוקה — הוא כבר לא תופס אנשים")

        locked = self._plan_mode()
        self.plan_banner_frame.setVisible(locked)
        if locked:
            self.lbl_plan_banner.setText(self._plan_banner_text())
            cmp_ = self._plan_cmp
            self.btn_plan_refresh.setVisible(bool(cmp_ and (cmp_["new"] or cmp_["gone"])))
            wk_ = date.fromisoformat(self._plan["week_wed"])
            self.chk_plan_autoreg.blockSignals(True)
            self.chk_plan_autoreg.setText(
                f"יירשם אוטומטית כמי שקיבלו ביום חמישי {_fmt_wed(wk_ + timedelta(days=1))} "
                f"ב-{selection.AUTO_REGISTER_HOUR:02d}:00, אם לא יירשם קודם (מי שלא הגיע — מתקנים אחר כך)")
            self.chk_plan_autoreg.setChecked(db.get_autoreg(self._plan)["enabled"])
            self.chk_plan_autoreg.blockSignals(False)
        self._autoreg_refresh_notice()
        # the button
        prep = self._stage == "prep"
        wk = self._plan_week()
        self.btn_lock_plan.setVisible(prep and wk is not None)
        if locked:
            self.btn_lock_plan.setText("🔓 בטל נעילה")
            self.btn_lock_plan.setEnabled(True)
            self.btn_lock_plan.setToolTip("מי שבנעילה יחזור להיות זמין לשבועות אחרים")
        else:
            reason = self._plan_lock_block_reason()
            self.btn_lock_plan.setText("🔒 נעל רשימה")
            self.btn_lock_plan.setEnabled(not reason)
            self.btn_lock_plan.setToolTip(reason or "שומר את הרשימה כחלוקה מתוכננת: מי שבה לא ייכנס "
                                                    "לרשימה של שבוע אחר, והרשימה לא תשתנה מעצמה")

    def _plan_prev_weeks_warning(self, wed) -> str:
        """The forecast assumes the weeks before it did not happen yet: a bi-weekly / monthly
        family on this week's list would show again. Say which week is neither locked nor
        recorded — the lock is what makes the forecast tell the truth (סעיף 6.1)."""
        weeks, w = [], selection.upcoming_wednesday(self._today())
        while w < wed:
            weeks.append(w)
            w = date.fromordinal(w.toordinal() + 7)
        if not weeks:
            return ""
        states = db.plan_states(self._today())
        done = db.weeks_executed(weeks)
        open_weeks = [w for w in weeks if w not in done and states.get(w) not in ("current", "future")]
        if not open_weeks:
            return ""
        return ("\n⚠ השבוע של " + ", ".join(_fmt_wed(w) for w in open_weeks)
                + " עדיין לא נעול ולא נרשם — דו-שבועי/חודשי שיופיע שם עלול להופיע גם כאן. נעל אותו קודם.")

    def _plan_dev_label(self, dev: str) -> str:
        if not dev:
            return ""
        try:
            from utils import sync
            st = sync._load_state()
            if dev == st.get("device_id"):
                return st.get("device_name") or "המחשב הזה"
        except Exception:                                         # noqa: BLE001
            pass
        return db.peer_app_versions().get(dev, ("", ""))[1]

    def _plan_banner_text(self) -> str:
        plan = self._plan
        wk = date.fromisoformat(plan["week_wed"])
        stamp = _local_stamp(plan.get("updated_at", ""))
        who = self._plan_dev_label(plan.get("updated_dev", ""))
        parts = [f"🔒 רשימה נעולה לרביעי {_fmt_wed(wk)} — מי שבה לא ייכנס לשבוע אחר · "
                 "הרשימה לא משתנה מעצמה · שינויים נשמרים מיד"]
        if stamp:
            parts.append("נערכה " + stamp + (f" ע״י {who}" if who else ""))
        n_main = sum(1 for r in self._rows_data if not r.get("_reserve"))
        products = int(plan.get("products") or 0)
        if products and n_main < products:
            left = products - n_main
            parts.append("נשאר מוצר אחד לא מוקצה" if left == 1 else f"נשארו {left} מוצרים לא מוקצים")
        elif products and n_main > products:
            parts.append(f"בנעילה {n_main} מקבלים ל-{products} מוצרים")
        info = self._plan_info or {}
        if info.get("inactive"):
            parts.append(f"{info['inactive']} הושהו ולא ייכללו")
        if info.get("missing"):
            parts.append(f"{info['missing']} לא נמצאו")
        cmp_ = self._plan_cmp
        if cmp_ and (cmp_["new"] or cmp_["gone"]):
            parts.append(f"⚠ {len(cmp_['new'])} חדשים בתור שלא בנעילה · {len(cmp_['gone'])} בנעילה שכבר לא בתור")
        return " · ".join(parts)

    # ═══ יצירה וביטול ═══════════════════════════════════════════════════════════
    def _on_lock_clicked(self):
        if self._plan_mode():
            self._unlock_plan()
        else:
            self._lock_plan()

    def _plan_member(self, rec, kind, reserve):
        return {"g": (rec.get("guid") or "").strip(), "role":
                selection.ROLE_RESERVE if reserve else selection.ROLE_MAIN,
                "kind": kind, "note": self._row_notes.get(rec.get("id"), ""),
                "n": rec.get("full_name", "")}

    def _plan_suggest_one_time(self, ld):
        """Forecast week: the one-timers are suggested at lock time by the fixed queue
        (the same picker the real week uses, pre-marked by the forecast's own counts).
        Returns the picks, [] when there is no room, or None when the operator cancels."""
        total, reserve = self._screen_counts()
        n, _regs = db.compute_suggested_n(total, 0, on_date=ld)
        if n <= 0:
            return []
        from tabs import group_update as gu
        dlg = gu.OneTimePickerDialog(self, manual_regulars=0, removed_regulars=0,
                                     on_date=ld, counts=(total, reserve))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.selected()

    def _lock_plan(self):
        reason = self._plan_lock_block_reason()
        if reason:
            QMessageBox.information(self, "נעילת רשימה", reason)
            return
        wk = self._plan_week()
        ld = self._list_date()
        picks = []
        if ld is not None and self._current_mode() == "schedule":
            picks = self._plan_suggest_one_time(ld)
            if picks is None:
                return
        if QMessageBox.question(
                self, "נעילת רשימה",
                f"לנעול את הרשימה לרביעי {_fmt_wed(wk)}?\n\n"
                "מי שבה לא ייכנס לרשימה של שבוע אחר בטווח התדירות שלו, והרשימה לא תשתנה מעצמה "
                "(אם יתווסף או יושהה מישהו — התוכנה רק תציג את ההבדל).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        members, seen = [], set()
        for r in self._rows_data:
            g = (r.get("guid") or "").strip()
            if not g or g in seen:
                continue
            seen.add(g)
            rid = r.get("id")
            if rid in self._extra_ids:
                kind = "one" if (r.get("frequency") or "") == "חד-פעמי" else "man"
            else:
                kind = "reg"
            members.append(self._plan_member(r, kind, bool(r.get("_reserve") or rid in self._reserve_ids)))
        for pk in picks:
            g = (pk.get("guid") or "").strip()
            if g and g not in seen:
                seen.add(g)
                members.append(self._plan_member(pk, "one", bool(pk.get("_reserve"))))
        removed = [(db.get_recipient(rid) or {}).get("guid") or "" for rid in self._removed_ids]
        name = self.name_input.currentText().strip()
        plan = {"week_wed": wk.isoformat(), "dist_date": self.date_edit.get_iso(),
                "name": "" if self._is_auto_name(name) else name,
                "products": self.products_spin.value(), "reserve": self.reserve_spin.value(),
                "mode": self._current_mode(), "note": self.note_input.text().strip(),
                "distributor": self.dist_input.currentText().strip(),
                "members": members, "removed": [g for g in removed if g]}
        try:
            db.save_plan(plan, expected_updated_at="")
        except db.PlanConflict:
            QMessageBox.information(self, "נעילת רשימה",
                                    "הרשימה כבר ננעלה בינתיים במחשב אחר — טוען אותה.")
        self._after_plan_change()
        if self.main_win:
            self.main_win.status_msg(f"הרשימה ננעלה לרביעי {_fmt_wed(wk)}")

    def _unlock_plan(self):
        wk = date.fromisoformat(self._plan["week_wed"])
        if QMessageBox.question(
                self, "ביטול נעילה",
                f"לבטל את הנעילה של רביעי {_fmt_wed(wk)}?\n\n"
                "מי שבה יחזור להיות זמין לשבועות אחרים. שינויים שנעשו ברשימה בזמן הנעילה "
                "לא יחזרו לטיוטה.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        db.delete_plan(wk)
        self._after_plan_change()
        if self.main_win:
            self.main_win.status_msg(f"הנעילה של {_fmt_wed(wk)} בוטלה")

    def _after_plan_change(self):
        """A lock appeared / changed / went away — other screens' lists depend on it too."""
        self.refresh()
        mw = getattr(self, "main_win", None)
        if mw is not None and hasattr(mw, "refresh_all"):
            try:
                mw.refresh_all()
            except Exception:                                     # noqa: BLE001
                pass

    # ═══ עריכה כותבת מיד ════════════════════════════════════════════════════════
    def _plan_update(self, mutate) -> bool:
        """Apply `mutate(plan)` to a copy of the loaded lock and store it at once, with the
        stamp it was loaded under. A stored lock that changed meanwhile (the other computer)
        asks first: reload (the edit is lost) or overwrite."""
        plan = copy.deepcopy(self._plan)
        mutate(plan)
        try:
            self._plan = db.save_plan(plan, expected_updated_at=self._plan.get("updated_at") or "")
            return True
        except db.PlanConflict:
            if QMessageBox.question(
                    self, "הרשימה הנעולה שונתה",
                    "הרשימה הנעולה שונתה במחשב אחר.\n\nלטעון מחדש את מה ששמור (העריכה שלך תאבד)?\n"
                    "לחיצה על \"לא\" תשמור את העריכה שלך על המצב החדש.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
                return False
            fresh = db.get_plan(self._plan["week_wed"])
            if fresh is None:
                return False
            plan = copy.deepcopy(fresh)
            mutate(plan)
            self._plan = db.save_plan(plan, expected_updated_at=None)
            return True

    @staticmethod
    def _guid_of(rec_or_id) -> str:
        rec = rec_or_id if isinstance(rec_or_id, dict) and rec_or_id.get("guid") else \
            db.get_recipient(rec_or_id.get("id") if isinstance(rec_or_id, dict) else rec_or_id)
        return ((rec or {}).get("guid") or "").strip()

    def _plan_remove_member(self, rec):
        g = self._guid_of(rec)
        if not g:
            return

        def mut(p):
            p["members"] = [m for m in p["members"] if m["g"] != g]
            if g not in p["removed"]:
                p["removed"].append(g)
        self._plan_update(mut)

    def _plan_add_members(self, recs, kind):
        """recs: dicts with an id (and `_reserve` for a reserve pick) — added to the lock as
        main / reserve members; coming back from the removed list on purpose."""
        add = []
        for rec in recs:
            full = db.get_recipient(rec.get("id")) if rec.get("id") is not None else None
            if full and (full.get("guid") or "").strip():
                add.append((full["guid"].strip(), full.get("full_name", ""), bool(rec.get("_reserve"))))
        if not add:
            return

        def mut(p):
            have = {m["g"]: m for m in p["members"]}
            for g, name, reserve in add:
                role = selection.ROLE_RESERVE if reserve else selection.ROLE_MAIN
                if g in have:
                    have[g]["role"] = role
                else:
                    p["members"].append({"g": g, "role": role, "kind": kind, "note": "", "n": name})
                if g in p["removed"]:
                    p["removed"].remove(g)
        self._plan_update(mut)

    def _plan_set_note(self, rid, txt):
        g = self._guid_of({"id": rid})
        if not g:
            return

        def mut(p):
            for m in p["members"]:
                if m["g"] == g:
                    m["note"] = txt
        if not self._plan_update(mut):
            self.refresh()                # the edit was dropped (reloaded) — show what is stored

    def _plan_set_count(self, idx, value):
        def mut(p):
            p["products" if idx == 0 else "reserve"] = int(value)
        self._plan_update(mut)

    # ═══ השוואה לנתונים החיים (4.5) ═════════════════════════════════════════════
    def _plan_compare(self):
        """Frozen, but not blind: who the live data would list for this week that the lock
        does not hold, and who the lock holds that is no longer due. Schedule mode only."""
        plan = self._plan
        self._plan_cmp = None
        if plan is None or (plan.get("mode") or "schedule") != "schedule":
            return
        base = db.get_weekly_list(area_filter="הכל", on_date=self._list_date())
        manual = sum(1 for m in plan["members"] if m.get("kind") == "man" and m.get("role") != "reserve")
        kept = selection.limit_due_regulars(list(base), db.get_need_weights(),
                                            int(plan.get("products") or 0), int(plan.get("reserve") or 0), manual)
        held = {r["id"] for r in self._rows_data}
        removed = set(self._removed_ids)
        due_ids = {r["id"] for r in base}
        new = [r for r in kept if r["id"] not in held and r["id"] not in removed]
        gone = [r for r in self._rows_data
                if r.get("_plan_kind") == "reg" and not r.get("_reserve") and r["id"] not in due_ids]
        self._plan_cmp = {"new": new, "gone": gone}

    def _plan_apply_compare(self):
        self._plan_compare()
        cmp_ = self._plan_cmp
        if not cmp_ or not (cmp_["new"] or cmp_["gone"]):
            QMessageBox.information(self, "עדכון מהנתונים", "הרשימה הנעולה תואמת לנתונים החיים.")
            self._plan_refresh_ui()
            return
        lines = []
        if cmp_["new"]:
            lines.append("יתווספו:\n" + "\n".join("• " + r.get("full_name", "") for r in cmp_["new"]))
        if cmp_["gone"]:
            lines.append("יוסרו:\n" + "\n".join("• " + r.get("full_name", "") for r in cmp_["gone"]))
        if QMessageBox.question(
                self, "עדכון מהנתונים", "\n\n".join(lines) + "\n\nלעדכן את הרשימה הנעולה?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        new = [(r["guid"], r.get("full_name", ""), bool(r.get("_reserve"))) for r in cmp_["new"] if r.get("guid")]
        gone = {r["guid"] for r in cmp_["gone"] if r.get("guid")}

        def mut(p):
            have = {m["g"] for m in p["members"]}
            p["members"] = [m for m in p["members"] if m["g"] not in gone]
            for g, name, reserve in new:
                if g not in have:
                    p["members"].append({"g": g, "kind": "reg", "note": "", "n": name,
                                         "role": selection.ROLE_RESERVE if reserve else selection.ROLE_MAIN})
        if self._plan_update(mut):
            self._after_plan_change()

    # ═══ רישום אוטומטי (כלל 11) ═════════════════════════════════════════════════════
    AUTOREG_INTERVAL_MS = 5 * 60 * 1000
    AUTOREG_FIRST_MS = 30 * 1000

    def _autoreg_setup(self):
        """The check runs on the UI thread (it touches the screen state afterwards): once shortly
        after launch — the sync has had time to bring the other computer's rounds — then every
        5 minutes. The database call itself decides whether anything is due."""
        self._autoreg_busy = False
        self._autoreg_timer = QTimer(self)
        self._autoreg_timer.setInterval(self.AUTOREG_INTERVAL_MS)
        self._autoreg_timer.timeout.connect(self.autoreg_tick)
        self._autoreg_timer.start()
        QTimer.singleShot(self.AUTOREG_FIRST_MS, self.autoreg_tick)

    def autoreg_tick(self, now=None):
        """Register the locks that are due (RULE 11). Never raises, never pops a dialog — the
        program is open in front of the operator. Returns the registrations made."""
        if getattr(self, "_autoreg_busy", False):
            return []
        self._autoreg_busy = True
        try:
            results = db.auto_register_due_plans(now)
        except Exception:                                         # noqa: BLE001
            results = []
        finally:
            self._autoreg_busy = False
        if results:
            self._after_auto_registration(results)
        return results

    def _after_auto_registration(self, results):
        """The same wrap-up an ordinary registration gets (the round is over: draft removals,
        notes and ticks go, the one-time picks of those who were registered were already dropped
        by the database layer) — without touching anything typed for the next round."""
        ids = {i for r in results for i in r.get("ids", ())}
        if self._plan_mode():
            self._plan_leave(reload=False)
        self._removed_ids.clear()
        self._row_notes.clear()
        self._checked_ids -= ids
        self._seen_ids -= ids
        self._record_visited = False
        self._set_stage("prep", clear=False)
        self.refresh()
        mw = getattr(self, "main_win", None)
        total = sum(r.get("n", 0) for r in results)
        if mw is not None:
            if hasattr(mw, "refresh_all"):
                try:
                    mw.refresh_all()
                except Exception:                                 # noqa: BLE001
                    pass
            week = " ו-".join(_fmt_wed(r["week_wed"]) for r in results)
            mw.status_msg(f"הרשימה הנעולה של {week} נרשמה אוטומטית ({total} מקבלים) — מי שלא הגיע: לתקן במסך החלוקה")

    def _on_plan_autoreg_toggled(self, checked):
        if not self._plan_mode():
            return
        db.set_autoreg_enabled(self._plan, bool(checked))
        if self.main_win:
            self.main_win.status_msg("הרשימה תירשם אוטומטית ביום החלוקה" if checked
                                     else "הרישום האוטומטי של הרשימה הזו כבוי")

    def _autoreg_refresh_notice(self):
        """Show the newest automatic registration that still waits for a look."""
        if not hasattr(self, "autoreg_banner_frame"):
            return
        self._autoreg_pending = db.auto_registrations_to_review(self._today())
        pend = self._autoreg_pending
        self.autoreg_banner_frame.setVisible(bool(pend))
        if not pend:
            return
        x = pend[0]
        hm = _local_hm(x["at"])
        txt = (f"✓ הרשימה הנעולה של רביעי {_fmt_wed(x['week_wed'])} נרשמה אוטומטית"
               + (f" ב-{hm}" if hm else "") + f" — {x['n']} מקבלים סומנו כמי שקיבלו. "
               "מי שלא הגיע חייב תיקון, אחרת ייחשב כמי שקיבל ותורו יזוז.")
        extra = []
        if x["inactive"]:
            extra.append(f"{x['inactive']} מושהים לא נרשמו")
        if x["missing"]:
            extra.append(f"{x['missing']} לא נמצאו")
        if extra:
            txt += " (" + " · ".join(extra) + ")"
        if len(pend) > 1:
            txt += f"  ·  ועוד {len(pend) - 1} ממתינות"
        self.lbl_autoreg.setText(txt)

    def _autoreg_confirm(self):
        if not self._autoreg_pending:
            return
        db.mark_autoreg_reviewed(self._autoreg_pending[0]["week_wed"])
        self._autoreg_refresh_notice()

    # ═══ חלון התכנונים (S4d) ════════════════════════════════════════════════════
    def _open_plans_dialog(self):
        dlg = PlansDialog(self)
        dlg.exec()
        self.refresh()


class PlansDialog(QDialog):
    """כל הנעילות: תאריך · שם · חברים/רזרבה · מצב · נערך ע״י/מתי; פתיחה, מחיקה והעתקה לנעילה חדשה."""
    _COLS = ["רביעי", "שם", "מקבלים", "רזרבה", "מצב", "רישום אוטומטי", "נערכה"]
    _STATE = {"current": "נעולה (השבוע)", "future": "נעולה (עתידית)", "executed": "בוצעה", "stale": "פגה"}

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        self.setWindowTitle("תכנונים — רשימות נעולות")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(760, 420)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self._COLS))
        self.table.setObjectName("plans_table")
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.lbl_empty = QLabel("עדיין אין רשימות נעולות.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_empty)
        row = QHBoxLayout()
        self.btn_open = QPushButton("פתח")
        self.btn_copy = QPushButton("העתק לנעילה חדשה")
        self.btn_delete = QPushButton("מחק")
        self.btn_close = QPushButton("סגור")
        for b in (self.btn_open, self.btn_copy, self.btn_delete):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.btn_close)
        lay.addLayout(row)
        self.btn_open.clicked.connect(self._open)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_close.clicked.connect(self.accept)
        self._fill()

    def _fill(self):
        states = db.plan_states(self._tab._today())
        plans = db.list_plans()
        self._plans = plans
        t = self.table
        t.setRowCount(len(plans))
        for i, p in enumerate(plans):
            wed = date.fromisoformat(p["week_wed"])
            n_res = sum(1 for m in p["members"] if m.get("role") == selection.ROLE_RESERVE)
            who = self._tab._plan_dev_label(p.get("updated_dev", ""))
            vals = [wed.strftime("%d/%m/%Y"), p.get("name", ""), str(len(p["members"]) - n_res), str(n_res),
                    self._STATE.get(states.get(wed, ""), ""), self._auto_text(p),
                    _local_stamp(p.get("updated_at", "")) + (f" · {who}" if who else "")]
            for c, v in enumerate(vals):
                t.setItem(i, c, QTableWidgetItem(v))
        t.resizeColumnsToContents()
        t.setVisible(bool(plans))
        self.lbl_empty.setVisible(not plans)
        for b in (self.btn_open, self.btn_copy, self.btn_delete):
            b.setEnabled(bool(plans))
        if plans:
            t.setCurrentCell(0, 0)

    @staticmethod
    def _auto_text(p) -> str:
        st = db.get_autoreg(p)
        if st["registered"]:
            hm = _local_hm(st["registered"].get("at", ""))
            return "נרשם אוטומטית" + (f" {hm}" if hm else "")
        return "דלוק" if st["enabled"] else "כבוי"

    def _current(self):
        r = self.table.currentRow()
        return self._plans[r] if 0 <= r < len(self._plans) else None

    def _open(self):
        p = self._current()
        if p is None:
            return
        self._tab.date_edit.set_from_iso(p.get("dist_date") or p["week_wed"])
        self.accept()

    def _delete(self):
        p = self._current()
        if p is None:
            return
        if QMessageBox.question(self, "מחיקת תכנון",
                                f"למחוק את התכנון של רביעי {_fmt_wed(date.fromisoformat(p['week_wed']))}?\n"
                                "מי שבו יחזור להיות זמין לשבועות אחרים.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        db.delete_plan(p["week_wed"])
        self._fill()

    def _copy(self):
        """Copy the members to the week on the main screen (no lock there yet) — for a lock
        that expired or was executed. Writes the new lock only; never the shared settings."""
        p = self._current()
        tab = self._tab
        target = tab._plan_week()
        if p is None or target is None:
            QMessageBox.information(self, "העתקה", "בחר במסך החלוקה תאריך של החלוקה הקרובה או של שבוע עתידי.")
            return
        if db.get_plan(target) is not None:
            QMessageBox.information(self, "העתקה", f"כבר יש נעילה לרביעי {_fmt_wed(target)}.")
            return
        if target.isoformat() == p["week_wed"]:
            return
        if QMessageBox.question(self, "העתקה לנעילה חדשה",
                                f"להעתיק את {len(p['members'])} המקבלים לנעילה חדשה של רביעי {_fmt_wed(target)}?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        new = {k: p.get(k) for k in ("name", "products", "reserve", "mode", "note", "members", "removed",
                                     "distributor")}
        new["week_wed"] = target.isoformat()
        new["dist_date"] = tab.date_edit.get_iso()
        db.save_plan(new, expected_updated_at="")
        self.accept()

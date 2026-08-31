# -*- coding: utf-8 -*-
"""לשונית 'הודעות' (#ya4f7) — צ'אט קבוצתי בין המחשבים שיש להם את התוכנה
(מנהל / מזכירה / חבר הנהלה). ההודעות נוסעות על אותו סנכרון Google Drive, כך
שאין צורך בשרת. אין וואטסאפ בקהילה — זו פלטפורמת התקשורת של הצוות.

תכונות: זמן יחסי בעברית ("לפני 5 דקות"), סימון נקרא ✓/✓✓ בסגנון וואטסאפ,
ורקע מותאם שהמשתמש מעלה. כל הזמנים בשעון ישראל. ההעברה אינה מיידית (תלויה
בסבב הסנכרון, ~10 שניות) — מקובל על המשתמש."""
import os
import shutil

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QFrame, QFileDialog,
                             QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor

import database as db
from utils.ui import line_icon
from utils import timefmt


def _chat_bg_file() -> str:
    """Path to the stored chat wallpaper, or '' if none set for this computer."""
    p = db.get_setting("chat_bg_path") or ""
    return p if p and os.path.exists(p) else ""


class _WallpaperArea(QWidget):
    """Message-stream container that paints the user's wallpaper itself.

    Painting the pixmap in code (instead of a QSS background-image url) fixes
    #uvee0 — QSS silently showed nothing for some images/paths, while QPixmap
    either loads or lets us tell the user why not. The image is scaled to
    cover the whole area (center-crop), like a phone-chat wallpaper."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = QPixmap()

    def set_wallpaper(self, pix: QPixmap):
        self._pix = pix if pix and not pix.isNull() else QPixmap()
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f4f7fb"))
        if not self._pix.isNull():
            scaled = self._pix.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            p.drawPixmap(0, 0, scaled, max(0, x), max(0, y),
                         self.width(), self.height())
        p.end()
        super().paintEvent(ev)


class _Bubble(QFrame):
    """One chat message. Own messages sit on the right (teal) and carry a read
    receipt (✓ sent / ✓✓ read); others sit on the left (white) with the author."""

    def __init__(self, msg: dict, mine: bool, read: bool = False,
                 on_delete=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 3, 6, 3)

        card = QFrame()
        card.setMaximumWidth(560)
        card.setStyleSheet(
            "QFrame{background:%s; border:1px solid %s; border-radius:12px;}" %
            (("#d7f2e8", "#b6e0d1") if mine else ("#ffffff", "#e6eaf2")))
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(2)

        _lbl = "background:transparent; border:none;"
        if not mine:
            who = QLabel(msg.get("author_name") or "משתמש")
            who.setStyleSheet("color:#0f766e; font-weight:700; font-size:12px; " + _lbl)
            cl.addWidget(who)

        body = QLabel(msg.get("body") or "")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet("color:#1f2937; font-size:14px; " + _lbl)
        cl.addWidget(body)

        # Meta line: relative Hebrew time (+ read receipt on my own messages).
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        iso = msg.get("created_at")
        tm = QLabel(timefmt.relative(iso))
        tm.setToolTip(timefmt.datetime_str(iso))       # exact Israel time on hover
        tm.setStyleSheet("color:#94a3b8; font-size:10.5px; " + _lbl)
        meta.addWidget(tm)
        if mine:
            tick = QLabel("✓✓" if read else "✓")
            tick.setToolTip("נקרא על ידי הצוות" if read else "נשלח")
            tick.setStyleSheet(
                "color:%s; font-size:11px; font-weight:700; %s" %
                ("#0f9d78" if read else "#9aa7b8", _lbl))
            meta.addWidget(tick)
            # Only the author can delete their own message; the removal syncs to
            # the other computers too.
            if on_delete is not None:
                guid = msg.get("guid") or ""
                del_btn = QPushButton("מחק")
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.setToolTip("מחק הודעה זו (אצל כל הצוות)")
                del_btn.setStyleSheet(
                    "QPushButton{color:#b45b5b; background:transparent; border:none;"
                    "font-size:10.5px; font-weight:600; padding:0 2px;}"
                    "QPushButton:hover{color:#dc2626; text-decoration:underline;}")
                del_btn.clicked.connect(lambda _=False, g=guid: on_delete(g))
                meta.addWidget(del_btn)
        meta.addStretch()
        cl.addLayout(meta)

        if mine:
            outer.addStretch()
            outer.addWidget(card)
        else:
            outer.addWidget(card)
            outer.addStretch()


class MessagesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._sig = None            # last rendered signature (skip needless rebuilds)
        self._needs_refresh = True

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        # Header row: title + wallpaper controls.
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("הודעות הצוות")
        title.setStyleSheet("font-size:19px; font-weight:800; color:#0f766e;")
        titles.addWidget(title)
        sub = QLabel("תקשורת בין המחשבים של הצוות (מנהל · מזכירה · הנהלה). "
                     "מסתנכרן אוטומטית · כל הזמנים בשעון ישראל.")
        sub.setStyleSheet("color:#64748b; font-size:12.5px;")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)

        _wall = ("QPushButton{background:#ffffff; color:#0f766e; border:1px solid #b6d8cd;"
                 "border-radius:9px; padding:6px 12px; font-size:12.5px; font-weight:600;}"
                 "QPushButton:hover{background:#eafaf3;}")
        self.btn_bg = QPushButton("רקע")
        self.btn_bg.setToolTip("בחר תמונת רקע למסך ההודעות (נשמר במחשב זה בלבד)")
        self.btn_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg.setStyleSheet(_wall)
        self.btn_bg.clicked.connect(self._choose_bg)
        head.addWidget(self.btn_bg, 0, Qt.AlignmentFlag.AlignTop)
        self.btn_bg_clear = QPushButton("הסר רקע")
        self.btn_bg_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg_clear.setStyleSheet(_wall)
        self.btn_bg_clear.clicked.connect(self._clear_bg)
        head.addWidget(self.btn_bg_clear, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        # Scrollable message stream (the wallpaper paints on this widget).
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea{border:1px solid #e6eaf2; border-radius:14px;}")
        self._stream = _WallpaperArea()
        self._vbox = QVBoxLayout(self._stream)
        self._vbox.setContentsMargins(8, 8, 8, 8)
        self._vbox.setSpacing(2)
        self._vbox.addStretch()
        self.scroll.setWidget(self._stream)
        root.addWidget(self.scroll, 1)
        self._apply_bg()

        self._empty = QLabel("אין עדיין הודעות. כתוב את הראשונה 👇")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color:#64748b; font-size:14px; padding:24px;")

        # Composer.
        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("כתוב הודעה לצוות…")
        self.input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.input.setMinimumHeight(42)
        self.input.setStyleSheet(
            "QLineEdit{background:#ffffff; border:1px solid #cbd5e1; border-radius:10px;"
            "padding:6px 12px; font-size:14px;}"
            "QLineEdit:focus{border:1px solid #0f9d78;}")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)

        self.btn_send = QPushButton("  שלח")
        self.btn_send.setIcon(QIcon(line_icon("mail", 18, "#ffffff")))
        self.btn_send.setMinimumHeight(42)
        self.btn_send.setMinimumWidth(110)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:#0f9d78; color:#ffffff; border:none; border-radius:10px;"
            "font-size:15px; font-weight:700;}"
            "QPushButton:hover{background:#0c8a69;}")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        root.addLayout(row)

    # ── wallpaper ────────────────────────────────────────────────────────────────
    def _apply_bg(self) -> bool:
        """Load and paint the stored wallpaper. Returns True if one is shown."""
        f = _chat_bg_file()
        pix = QPixmap(f) if f else QPixmap()
        ok = bool(f) and not pix.isNull()
        self._stream.set_wallpaper(pix)
        self.btn_bg_clear.setVisible(ok)
        return ok

    def _choose_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר תמונת רקע להודעות", "",
            "תמונות (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if not path:
            return
        # Validate the picked image BEFORE storing it — a silent failure here
        # was bug #uvee0 ("chose a wallpaper and nothing changed").
        if QPixmap(path).isNull():
            QMessageBox.warning(
                self, "תמונת רקע",
                "לא הצלחתי לקרוא את התמונה שנבחרה.\n"
                "נסה תמונה אחרת (JPG או PNG רגילים עובדים הכי טוב).")
            return
        try:
            ext = os.path.splitext(path)[1] or ".png"
            dest = db.CHAT_BG_PATH + ext
            # Clear any earlier wallpaper (different extension) before copying.
            self._remove_bg_files()
            shutil.copyfile(path, dest)
            db.set_setting("chat_bg_path", dest)
        except Exception as e:
            QMessageBox.warning(
                self, "תמונת רקע",
                "שמירת תמונת הרקע נכשלה:\n%s" % e)
            return
        if not self._apply_bg():
            QMessageBox.warning(
                self, "תמונת רקע",
                "התמונה נשמרה אך לא ניתן להציג אותה.\n"
                "נסה תמונה אחרת (JPG או PNG רגילים).")

    def _remove_bg_files(self):
        base = db.CHAT_BG_PATH
        d = os.path.dirname(base)
        stem = os.path.basename(base)
        try:
            for fn in os.listdir(d):
                if fn.startswith(stem):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
        except OSError:
            pass

    def _clear_bg(self):
        self._remove_bg_files()
        db.set_setting("chat_bg_path", "")
        self._apply_bg()

    # ── identity ────────────────────────────────────────────────────────────────
    def _me(self):
        try:
            from utils import sync
            return sync.device_id(), (sync.device_name() or "אני")
        except Exception:
            return "", "אני"

    def _send(self):
        body = self.input.text().strip()
        if not body:
            return
        dev, name = self._me()
        db.add_message(body, author_name=name, author_device=dev)
        self.input.clear()
        self._sig = None
        self.refresh()
        self.mark_read()

    # ── unread bookkeeping (for the tab badge) ──────────────────────────────────
    def unread_count(self) -> int:
        try:
            from utils import sync
            return len(db.messages_after(sync.messages_read_ts(),
                                         exclude_device=sync.device_id()))
        except Exception:
            return 0

    def mark_read(self):
        """Mark everything read locally AND broadcast a read-marker so the other
        computer's messages show ✓✓."""
        try:
            from utils import sync
            msgs = db.get_messages()
            if not msgs:
                return
            newest = msgs[-1].get("created_at") or ""
            sync.set_messages_read_ts(newest)
            dev, name = self._me()
            if dev:
                db.set_read_marker(dev, name, newest)
        except Exception:
            pass

    # ── rendering ───────────────────────────────────────────────────────────────
    def refresh(self):
        dev, _ = self._me()
        msgs = db.get_messages()
        other_read = db.latest_other_read_ts(exclude_device=dev)
        # Signature: rebuild only when messages or read-state actually changed.
        sig = (len(msgs), msgs[-1].get("created_at") if msgs else "", other_read)
        if sig == self._sig:
            return
        self._sig = sig

        while self._vbox.count() > 1:
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if not msgs:
            self._vbox.insertWidget(0, self._empty)
        else:
            if self._empty.parent() is not None:
                self._empty.setParent(None)
            for i, m in enumerate(msgs):
                mine = (m.get("author_device") == dev)
                read = mine and other_read and (m.get("created_at") or "") <= other_read
                self._vbox.insertWidget(
                    i, _Bubble(m, mine=mine, read=bool(read),
                               on_delete=self._delete if mine else None))

        QTimer.singleShot(30, self._scroll_bottom)

    def _delete(self, guid: str):
        """Remove one of my own messages, after confirming — the removal syncs to
        the whole team."""
        if not guid:
            return
        box = QMessageBox(self)
        box.setWindowTitle("מחיקת הודעה")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("למחוק את ההודעה?\nההודעה תיעלם גם אצל שאר חברי הצוות.")
        yes = box.addButton("מחק", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        db.delete_message(guid)
        self._sig = None
        self.refresh()

    def _scroll_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

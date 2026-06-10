from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QPushButton
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import database as db


def _card(title: str, value_lbl: QLabel, color: str = "#2563eb") -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background-color: #ffffff; border: 2px solid {color}33; "
        f"border-top: 4px solid {color}; border-radius: 8px; }}"
    )
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(6)
    t = QLabel(title)
    t.setStyleSheet(f"color: #6b7280; font-size: 12px; font-weight: 600; "
                    f"background: transparent; border: none;")
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    value_lbl.setStyleSheet(
        f"color: {color}; font-size: 32px; font-weight: 800; "
        f"background: transparent; border: none;"
    )
    lay.addWidget(t)
    lay.addWidget(value_lbl)
    return frame


class SummaryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(14, 14, 14, 14)

        title = QLabel("לוח מחוונים")
        title.setObjectName("title")
        lay.addWidget(title)

        # Top cards
        grid = QGridLayout()
        grid.setSpacing(10)

        self.v_active = QLabel("—")
        self.v_overdue = QLabel("—")
        self.v_souls = QLabel("—")
        self.v_dists_month = QLabel("—")
        self.v_dists_total = QLabel("—")
        self.v_suspended = QLabel("—")

        grid.addWidget(_card("מקבלים פעילים",  self.v_active,      "#2563eb"), 0, 0)
        grid.addWidget(_card("⏰ באיחור",        self.v_overdue,     "#dc2626"), 0, 1)
        grid.addWidget(_card("סה\"כ נפשות",      self.v_souls,       "#16a34a"), 0, 2)
        grid.addWidget(_card("חלוקות החודש",     self.v_dists_month, "#d97706"), 1, 0)
        grid.addWidget(_card("סה\"כ חלוקות",     self.v_dists_total, "#7c3aed"), 1, 1)
        grid.addWidget(_card("מושהים",           self.v_suspended,   "#64748b"), 1, 2)
        lay.addLayout(grid)

        # Breakdown tables
        bottom = QHBoxLayout()

        # By frequency
        freq_frame = QFrame()
        freq_frame.setObjectName("panel")
        freq_lay = QVBoxLayout(freq_frame)
        freq_lay.setContentsMargins(12, 10, 12, 10)
        lbl_freq_title = QLabel("פילוח לפי תדירות")
        lbl_freq_title.setObjectName("section-header")
        freq_lay.addWidget(lbl_freq_title)
        self.freq_lbl = QLabel("")
        self.freq_lbl.setTextFormat(Qt.TextFormat.RichText)
        freq_lay.addWidget(self.freq_lbl)
        freq_lay.addStretch()
        bottom.addWidget(freq_frame)

        # By area
        area_frame = QFrame()
        area_frame.setObjectName("panel")
        area_lay = QVBoxLayout(area_frame)
        area_lay.setContentsMargins(12, 10, 12, 10)
        lbl_area_title = QLabel("פילוח לפי אזור")
        lbl_area_title.setObjectName("section-header")
        area_lay.addWidget(lbl_area_title)
        self.area_lbl = QLabel("")
        self.area_lbl.setTextFormat(Qt.TextFormat.RichText)
        area_lay.addWidget(self.area_lbl)
        area_lay.addStretch()
        bottom.addWidget(area_frame)

        lay.addLayout(bottom)

        btn_refresh = QPushButton("רענן")
        btn_refresh.setObjectName("neutral")
        btn_refresh.setMaximumWidth(120)
        btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(btn_refresh, alignment=Qt.AlignmentFlag.AlignLeft)


        lay.addStretch()

    def refresh(self):
        stats = db.get_summary()
        self.v_active.setText(str(stats["active"]))
        self.v_overdue.setText(str(stats["overdue"]))
        self.v_souls.setText(str(stats["total_souls"]))
        self.v_dists_month.setText(str(stats["dists_month"]))
        self.v_dists_total.setText(str(stats["dists_total"]))
        self.v_suspended.setText(str(stats["suspended"]))

        freq_html = "<table style='width:100%'>"
        freq_html += "<tr><th>תדירות</th><th>מקבלים</th><th>נפשות</th></tr>"
        for row in stats["by_freq"]:
            freq_html += f"<tr><td>{row['frequency'] or '—'}</td><td>{row['c']}</td><td>{row['s']}</td></tr>"
        freq_html += "</table>"
        self.freq_lbl.setText(freq_html)

        area_html = "<table style='width:100%'>"
        area_html += "<tr><th>אזור</th><th>פעילים</th></tr>"
        for row in stats["by_area"]:
            area_html += f"<tr><td>{row['area'] or 'לא מוגדר'}</td><td>{row['c']}</td></tr>"
        area_html += "</table>"
        self.area_lbl.setText(area_html)


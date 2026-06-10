"""
ערכת נושא: qt-material light_blue + תוספות RTL/עברית
"""

# ── Extra stylesheet — מוסף ON TOP של qt-material ──────────────────────────
EXTRA_QSS = """
/* ════ RTL + Hebrew font ════ */
QWidget {
    direction: rtl;
    font-family: 'Segoe UI', 'Tahoma', Arial, sans-serif;
}
QDialog  { direction: rtl; }
QMessageBox { direction: rtl; }

/* ════ Label hierarchy ════ */
QLabel { background-color: transparent; }

QLabel#title {
    font-size: 17px;
    font-weight: 700;
    color: #1565c0;
    padding-bottom: 7px;
    border-bottom: 2px solid #bbdefb;
    margin-bottom: 2px;
}

QLabel#subtitle {
    font-size: 12px;
    color: #757575;
}

QLabel#section-header {
    font-size: 12px;
    font-weight: 700;
    color: #424242;
    border-bottom: 2px solid #e0e0e0;
    padding-bottom: 4px;
    margin-bottom: 2px;
}

/* ════ Frames — panel card ════ */
QFrame { background-color: transparent; border: none; }

QFrame#panel {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}

/* ════ Tab bar ════ */
QTabWidget::pane {
    border: 1px solid #bbdefb;
    border-top: none;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
}
QTabBar::tab {
    font-weight: 700;
    font-size: 13px;
    min-width: 115px;
    padding: 11px 20px;
    border-radius: 6px 6px 0 0;
    color: #5a6a7a;
    background-color: rgba(0, 0, 0, 0.04);
    margin-left: 2px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    border: 2px solid #1565c0;
    border-bottom: 2px solid #ffffff;
    border-radius: 6px 6px 0 0;
    font-weight: 800;
    font-size: 13px;
    color: #1565c0;
}
QTabBar::tab:!selected:hover {
    background-color: rgba(25, 118, 210, 0.09);
    color: #1565c0;
}

/* ════ Table improvements ════ */
QTableWidget, QTableView {
    border-radius: 6px;
    outline: none;
    show-decoration-selected: 1;
}

QTableWidget::item, QTableView::item {
    padding: 7px 10px;
    border: none;
    color: #212121;
}

QTableWidget::item:hover, QTableView::item:hover {
    background-color: #e3f2fd;
}

QTableWidget::item:selected, QTableView::item:selected {
    background-color: #bbdefb;
    color: #0d47a1;
}

QTableWidget::item:selected:hover, QTableView::item:selected:hover {
    background-color: #90caf9;
    color: #0d47a1;
}

QHeaderView::section {
    font-weight: 700;
    font-size: 12px;
    min-height: 36px;
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid #bbdefb;
    border-left: 1px solid #e3f2fd;
    background-color: #e3f2fd;
    color: #1565c0;
}
QHeaderView::section:hover { background-color: #bbdefb; }

/* ════ Buttons — all states ════ */
QPushButton {
    border-radius: 6px;
    font-weight: 700;
    min-width: 80px;
    min-height: 34px;
    padding: 7px 20px;
}
QPushButton:focus { outline: none; }
QPushButton:pressed {
    padding-top: 8px;
    padding-bottom: 6px;
}

QPushButton#danger {
    background-color: #d32f2f;
    color: #ffffff;
    border: none;
}
QPushButton#danger:hover   { background-color: #b71c1c; }
QPushButton#danger:pressed { background-color: #c62828; }
QPushButton#danger:focus   { border: 2px solid #ef9a9a; }
QPushButton#danger:disabled { background-color: #e0e0e0; color: #9e9e9e; }

QPushButton#success {
    background-color: #388e3c;
    color: #ffffff;
    border: none;
}
QPushButton#success:hover   { background-color: #2e7d32; }
QPushButton#success:pressed { background-color: #1b5e20; }
QPushButton#success:focus   { border: 2px solid #a5d6a7; }
QPushButton#success:disabled { background-color: #e0e0e0; color: #9e9e9e; }

QPushButton#neutral {
    background-color: #616161;
    color: #ffffff;
    border: none;
}
QPushButton#neutral:hover   { background-color: #424242; }
QPushButton#neutral:pressed { background-color: #212121; }
QPushButton#neutral:focus   { border: 2px solid #bdbdbd; }
QPushButton#neutral:disabled { background-color: #e0e0e0; color: #9e9e9e; }

/* ════ Inputs — focus ring + hover ════ */
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QComboBox:hover, QDateEdit:hover, QSpinBox:hover {
    border-color: #42a5f5;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #1976d2;
    background-color: #fafeff;
}

QComboBox:focus { border-color: #1976d2; }
QDateEdit:focus, QSpinBox:focus { border-color: #1976d2; }

QLineEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {
    background-color: #f5f5f5;
    color: #9e9e9e;
}

/* ════ ComboBox dropdown items ════ */
QComboBox QAbstractItemView::item { padding: 7px 10px; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover { background-color: #e3f2fd; color: #1565c0; }

/* ════ CheckBox + item-view checkboxes (tables) ════
   Styled explicitly here (border + solid fill) so the marks stay clearly
   visible even in the frozen EXE, where qt-material's indicator image
   resources are not bundled and otherwise render blank/transparent. */
QCheckBox { background-color: transparent; }

QCheckBox::indicator,
QTableView::indicator,
QTableWidget::indicator,
QAbstractItemView::indicator {
    width: 18px; height: 18px;
    border-radius: 4px;
    border: 2px solid #90a4ae;
    background-color: #ffffff;
}
QCheckBox::indicator:unchecked:hover,
QTableView::indicator:unchecked:hover,
QTableWidget::indicator:unchecked:hover,
QAbstractItemView::indicator:unchecked:hover {
    border-color: #1976d2;
}
QCheckBox::indicator:checked,
QTableView::indicator:checked,
QTableWidget::indicator:checked,
QAbstractItemView::indicator:checked {
    border: 2px solid #1565c0;
    background-color: #1976d2;
}
QCheckBox::indicator:indeterminate,
QTableView::indicator:indeterminate,
QTableWidget::indicator:indeterminate {
    border: 2px solid #1565c0;
    background-color: #90caf9;
}
QCheckBox::indicator:disabled,
QTableView::indicator:disabled,
QTableWidget::indicator:disabled,
QAbstractItemView::indicator:disabled {
    background-color: #f5f5f5;
    border-color: #e0e0e0;
}

/* ════ Scrollbars — overlay minimal ════ */
QScrollBar:vertical   { background: transparent; width: 8px;  margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #bdbdbd;
    border-radius: 4px;
    min-height: 30px;
    min-width: 30px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #9e9e9e;
}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {
    background: #757575;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none; height: 0; width: 0; border: none;
}

/* ════ Calendar RTL / Hebrew ════ */
QCalendarWidget {
    background-color: #ffffff;
    border: 1px solid #bbdefb;
    border-radius: 8px;
}
QCalendarWidget QAbstractItemView {
    color: #212121;
    selection-background-color: #1976d2;
    selection-color: #ffffff;
    gridline-color: #f5f5f5;
    outline: none;
}
/* Force a visible text color for every cell state — prevents the
   "transparent dates" effect when qt-material leaves cells with a
   near-invisible (alpha) foreground, especially in the frozen EXE. */
QCalendarWidget QAbstractItemView:enabled  { color: #212121; }
QCalendarWidget QAbstractItemView:disabled { color: #b0bec5; }
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: #1976d2;
    border-radius: 8px 8px 0 0;
    min-height: 40px;
}
QCalendarWidget QToolButton {
    color: #ffffff;
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    font-weight: 700;
}
QCalendarWidget QToolButton:hover   { background-color: rgba(255,255,255,0.18); }
QCalendarWidget QToolButton:pressed { background-color: rgba(255,255,255,0.30); }
QCalendarWidget QSpinBox {
    background-color: transparent;
    color: #ffffff;
    border: none;
    font-weight: 700;
}
QCalendarWidget QSpinBox::up-button,
QCalendarWidget QSpinBox::down-button { background-color: transparent; border: none; }

/* ════ Main window — subtle blue-tinted background ════ */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f5f8ff, stop:1 #eef2fb);
}

/* ════ Status bar ════ */
QStatusBar {
    font-size: 12px;
    min-height: 26px;
    padding: 0 10px;
}
QStatusBar::item { border: none; }

/* ════ Tooltip ════ */
QToolTip {
    background-color: #212121;
    color: #f5f5f5;
    border: none;
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ════ GroupBox ════ */
QGroupBox {
    background-color: #ffffff;
    border: 1.5px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 8px;
    color: #1976d2;
    font-size: 12px;
    font-weight: 700;
}
"""

# ── Extra config for qt-material ───────────────────────────────────────────
QT_MATERIAL_EXTRA = {
    "font_family": "Segoe UI",
    "density_scale": "0",
}

# ── Row highlight tokens (referenced directly in tab code) ──────────────────
OVERDUE_BG  = "#ffebee"
OVERDUE_FG  = "#b71c1c"
TODAY_BG    = "#fff8e1"
TODAY_FG    = "#e65100"
WEEK_BG     = "#e8f5e9"
WEEK_FG     = "#1b5e20"
SELECTED_BG = "#e3f2fd"
SELECTED_FG = "#0d47a1"

# ── Recipient status colors ──────────────────────────────────────────────────
SUSPENDED_FG = "#8b6914"
ENDED_FG     = "#94a3b8"

# ── Legacy alias (used by test_all.py) ─────────────────────────────────────
DARK_BLUE = EXTRA_QSS

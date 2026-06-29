"""
ערכת נושא: qt-material light_blue + תוספות RTL/עברית.

כל הצבעים, הגופן וסקאלת-הגופן מוגדרים פעם אחת ב-PALETTE/TOKENS, וה-QSS נבנה
מהם דרך string.Template ($token). כך יש מקור-אמת אחד לעיצוב, וגווני הכחול
מאוחדים לסולם עקבי במקום ערכים מפוזרים.
"""
from string import Template

# ── מקור-אמת אחד לצבעים ─────────────────────────────────────────────────────
PALETTE = {
    # סולם כחול אחד ועקבי (במקום ~8 כחולים אד-הוק)
    "blue_900": "#0d47a1",   # כהה ביותר — טקסט נבחר / לחיצה
    "blue_700": "#1565c0",   # מותג ראשי (PRIMARY)
    "blue_600": "#1976d2",   # אקסנט / hover
    "blue_400": "#42a5f5",   # קו אקסנט בהיר
    "blue_200": "#bbdefb",   # מסגרות
    "blue_100": "#e3f2fd",   # רקעי-גוון / כותרת טבלה
    "blue_050": "#eef4ff",   # רקע עמוד
    # ניטרליים
    "ink":      "#1f2937",   # טקסט ראשי
    "ink_soft": "#475569",   # טקסט משני
    "muted":    "#6b7280",   # כותרות-משנה
    "line":     "#e5e7eb",   # מסגרת ניטרלית
    "line_2":   "#eef1f5",
    "surface":  "#ffffff",
    "field_bg": "#f8fafc",
    # סמנטיים
    "danger":      "#d32f2f", "danger_dk": "#b71c1c", "danger_soft": "#ef9a9a",
    "success":     "#2e9e4f", "success_dk": "#1b7a37", "success_soft": "#a5d6a7",
    # כפתור משני "רפאים" (outline)
    "ghost_line":  "#cbd5e1", "ghost_ink": "#475569", "ghost_hover": "#eef2f7",
}

# ── סקאלת-גופן + מחסנית גופנים ──
# Segoe UI: גופן מערכת חד בכל DPI ותומך עברית. הגופן Rubik (variable) רונדר
# רך/מטושטש, ולכן הוחזר ל-Segoe UI.
FONT_STACK = "'Segoe UI','Tahoma',Arial,sans-serif"

TOKENS = {
    **PALETTE,
    "font":       FONT_STACK,
    "fs_title":   "20px",
    "fs_section": "13px",
    "fs_sub":     "12px",
    "fs_tab":     "13px",
    "fs_table":   "12px",
}

# ── תבנית ה-QSS (משתמשת ב-$token; ל-QSS אין '$' משלו ולכן זה בטוח) ──────────
_QSS_TEMPLATE = Template("""
/* ════ RTL + Hebrew font ════ */
QWidget {
    direction: rtl;
    font-family: $font;
    color: $ink;
}
QDialog  { direction: rtl; }
QMessageBox { direction: rtl; }

/* ════ Label hierarchy ════ */
QLabel { background-color: transparent; }

QLabel#title {
    font-size: $fs_title;
    font-weight: 800;
    color: $blue_700;
    padding-bottom: 8px;
    border-bottom: 2px solid $blue_200;
    margin-bottom: 4px;
}

QLabel#subtitle {
    font-size: $fs_sub;
    color: $muted;
}

QLabel#section-header {
    font-size: $fs_section;
    font-weight: 700;
    color: $ink_soft;
    border-bottom: 2px solid $line;
    padding-bottom: 5px;
    margin-bottom: 2px;
}

/* ════ Frames — panel card ════ */
QFrame { background-color: transparent; border: none; }

QFrame#panel {
    background-color: $surface;
    border: 1px solid $line;
    border-radius: 10px;
}

/* ════ Tab bar ════ */
QTabWidget::pane {
    border: 1px solid $blue_200;
    border-top: none;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QTabBar::tab {
    font-weight: 700;
    font-size: $fs_tab;
    min-width: 112px;
    padding: 11px 20px;
    border-radius: 8px 8px 0 0;
    color: $ink_soft;
    background-color: rgba(15, 23, 42, 0.04);
    margin-left: 3px;
}
QTabBar::tab:selected {
    background-color: $surface;
    border: 2px solid $blue_700;
    border-bottom: 2px solid $surface;
    font-weight: 800;
    color: $blue_700;
}
QTabBar::tab:!selected:hover {
    background-color: $blue_100;
    color: $blue_700;
}

/* ════ Tables — roomier rows for readability ════ */
QTableWidget, QTableView {
    border-radius: 8px;
    outline: none;
    show-decoration-selected: 1;
    gridline-color: $line_2;
    font-size: $fs_table;
    alternate-background-color: #f7faff;
    background-color: $surface;
}
QTableWidget::item, QTableView::item {
    padding: 9px 12px;
    border: none;
    color: $ink;
}
QTableWidget::item:hover, QTableView::item:hover { background-color: $blue_100; }
QTableWidget::item:selected, QTableView::item:selected {
    background-color: $blue_200;
    color: $blue_900;
}
QTableWidget::item:selected:hover, QTableView::item:selected:hover {
    background-color: #90caf9;
    color: $blue_900;
}
QHeaderView::section {
    font-weight: 700;
    font-size: $fs_table;
    min-height: 40px;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid $blue_200;
    border-left: 1px solid $blue_100;
    background-color: $blue_100;
    color: $blue_700;
}
QHeaderView::section:hover { background-color: $blue_200; }

/* ════ Buttons — hierarchy: primary / success / danger / ghost ════ */
QPushButton {
    border-radius: 8px;
    font-weight: 700;
    min-width: 84px;
    min-height: 36px;
    padding: 8px 22px;
}
QPushButton:focus { outline: none; }
QPushButton:pressed { padding-top: 9px; padding-bottom: 7px; }

/* PRIMARY — the single dominant action per screen */
QPushButton#primary {
    background-color: $blue_700;
    color: #ffffff;
    border: none;
    font-weight: 800;
}
QPushButton#primary:hover   { background-color: $blue_600; }
QPushButton#primary:pressed { background-color: $blue_900; }
QPushButton#primary:focus   { border: 2px solid $blue_200; }
QPushButton#primary:disabled { background-color: $line; color: $muted; }

QPushButton#danger {
    background-color: $danger; color: #ffffff; border: none;
}
QPushButton#danger:hover   { background-color: $danger_dk; }
QPushButton#danger:pressed { background-color: $danger_dk; }
QPushButton#danger:focus   { border: 2px solid $danger_soft; }
QPushButton#danger:disabled { background-color: $line; color: $muted; }

QPushButton#success {
    background-color: $success; color: #ffffff; border: none;
}
QPushButton#success:hover   { background-color: $success_dk; }
QPushButton#success:pressed { background-color: $success_dk; }
QPushButton#success:focus   { border: 2px solid $success_soft; }
QPushButton#success:disabled { background-color: $line; color: $muted; }

/* NEUTRAL — secondary "ghost" (outlined) so it recedes behind primary */
QPushButton#neutral {
    background-color: transparent;
    color: $ghost_ink;
    border: 1.5px solid $ghost_line;
}
QPushButton#neutral:hover   { background-color: $ghost_hover; border-color: $blue_400; color: $blue_700; }
QPushButton#neutral:pressed { background-color: $line; }
QPushButton#neutral:focus   { border: 2px solid $blue_400; }
QPushButton#neutral:disabled { color: $muted; border-color: $line; }

/* ════ Inputs — focus ring + hover ════ */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox {
    border-radius: 8px;
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QComboBox:hover, QDateEdit:hover, QSpinBox:hover {
    border-color: $blue_400;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: $blue_600;
    background-color: #fafeff;
}
QComboBox:focus, QDateEdit:focus, QSpinBox:focus { border-color: $blue_600; }
QLineEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {
    background-color: $field_bg;
    color: $muted;
}

/* ════ ComboBox dropdown items ════ */
QComboBox QAbstractItemView::item { padding: 8px 12px; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover { background-color: $blue_100; color: $blue_700; }

/* ════ CheckBox + item-view checkboxes (tables) ════ */
QCheckBox { background-color: transparent; }
QCheckBox::indicator,
QTableView::indicator, QTableWidget::indicator, QAbstractItemView::indicator {
    width: 18px; height: 18px;
    border-radius: 4px;
    border: 2px solid #90a4ae;
    background-color: $surface;
}
QCheckBox::indicator:unchecked:hover,
QTableView::indicator:unchecked:hover, QTableWidget::indicator:unchecked:hover,
QAbstractItemView::indicator:unchecked:hover { border-color: $blue_600; }
QCheckBox::indicator:checked,
QTableView::indicator:checked, QTableWidget::indicator:checked,
QAbstractItemView::indicator:checked {
    border: 2px solid $blue_700;
    background-color: $blue_600;
}
QCheckBox::indicator:indeterminate,
QTableView::indicator:indeterminate, QTableWidget::indicator:indeterminate {
    border: 2px solid $blue_700;
    background-color: #90caf9;
}
QCheckBox::indicator:disabled,
QTableView::indicator:disabled, QTableWidget::indicator:disabled,
QAbstractItemView::indicator:disabled {
    background-color: $field_bg;
    border-color: $line;
}

/* ════ Scrollbars — overlay minimal ════ */
QScrollBar:vertical   { background: transparent; width: 9px;  margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #c2cbd6; border-radius: 4px; min-height: 30px; min-width: 30px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #97a3b2; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: $ink_soft; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none; height: 0; width: 0; border: none;
}

/* ════ Calendar RTL / Hebrew ════ */
QCalendarWidget {
    background-color: $surface;
    border: 1px solid $blue_200;
    border-radius: 10px;
}
QCalendarWidget QAbstractItemView {
    color: $ink;
    selection-background-color: $blue_600;
    selection-color: #ffffff;
    gridline-color: $line_2;
    outline: none;
}
QCalendarWidget QAbstractItemView:enabled  { color: $ink; }
QCalendarWidget QAbstractItemView:disabled { color: #b0bec5; }
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: $blue_600;
    border-radius: 10px 10px 0 0;
    min-height: 40px;
}
QCalendarWidget QToolButton {
    color: #ffffff; background-color: transparent; border: none;
    border-radius: 4px; padding: 4px 10px; font-weight: 700;
}
QCalendarWidget QToolButton:hover   { background-color: rgba(255,255,255,0.18); }
QCalendarWidget QToolButton:pressed { background-color: rgba(255,255,255,0.30); }
QCalendarWidget QSpinBox {
    background-color: transparent; color: #ffffff; border: none; font-weight: 700;
}
QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button {
    background-color: transparent; border: none;
}

/* ════ Main window — subtle blue-tinted background ════ */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 $blue_050, stop:1 #eaf0fb);
}

/* ════ Status bar ════ */
QStatusBar { font-size: $fs_sub; min-height: 28px; padding: 0 12px; color: $ink_soft; }
QStatusBar::item { border: none; }

/* ════ Tooltip ════ */
QToolTip {
    background-color: $ink; color: #f5f5f5; border: none;
    border-radius: 6px; padding: 6px 10px; font-size: $fs_sub;
}

/* ════ GroupBox ════ */
QGroupBox {
    background-color: $surface;
    border: 1.5px solid $line;
    border-radius: 10px;
    margin-top: 16px;
    padding-top: 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 8px;
    color: $blue_600;
    font-size: $fs_sub;
    font-weight: 700;
}
""")

EXTRA_QSS = _QSS_TEMPLATE.substitute(TOKENS)

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
SELECTED_BG = PALETTE["blue_100"]
SELECTED_FG = PALETTE["blue_900"]

# ── Recipient status colors ──────────────────────────────────────────────────
SUSPENDED_FG = "#8b6914"
ENDED_FG     = "#94a3b8"

# ── Legacy alias (used by test_all.py) ─────────────────────────────────────
DARK_BLUE = EXTRA_QSS

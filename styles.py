"""
ערכת נושא: qt-material light_blue + תוספות RTL/עברית.

כל הצבעים, הגופן וסקאלת-הגופן מוגדרים פעם אחת ב-PALETTE/TOKENS, וה-QSS נבנה
מהם דרך string.Template ($token). כך יש מקור-אמת אחד לעיצוב, וגווני הכחול
מאוחדים לסולם עקבי במקום ערכים מפוזרים.
"""
from string import Template

# ── מקור-אמת אחד לצבעים ─────────────────────────────────────────────────────
# v2.60: זהות "ירוק רגוע" (בחירת המשתמש מתוך 3 הצעות) — ירוק-טורקיז חם.
# שמות המפתחות נשארו blue_* היסטורית כדי לא לשבור הפניות; הערכים ירוקים.
PALETTE = {
    # סולם המותג (ירוק-טורקיז)
    "blue_900": "#065f46",   # כהה ביותר — טקסט נבחר / לחיצה
    "blue_700": "#0f766e",   # מותג ראשי (PRIMARY)
    "blue_600": "#0d9488",   # אקסנט / hover
    "blue_400": "#2dd4bf",   # קו אקסנט בהיר
    "blue_200": "#a7ecd9",   # מסגרות
    "blue_100": "#ddf3ec",   # רקעי-גוון / כותרת טבלה
    "blue_050": "#eefaf5",   # רקע עמוד
    # ניטרליים — טון מודרני, אוורירי ורך יותר
    "ink":      "#1e293b",   # טקסט ראשי (slate-800)
    "ink_soft": "#475569",   # טקסט משני
    "muted":    "#7b8794",   # כותרות-משנה
    "line":     "#e4ece7",   # מסגרת ניטרלית (רכה, נוטה ירקרק)
    "line_2":   "#edf4f0",
    "surface":  "#ffffff",
    "page":     "#f4faf7",   # רקע עמוד נקי (כמעט-לבן בגוון ירקרק)
    "field_bg": "#f5faf8",
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
    "fs_title":   "22px",
    "fs_section": "14px",
    "fs_sub":     "12px",
    "fs_tab":     "13px",
    "fs_table":   "13px",
    # ── סקאלת פינות מעוגלות אחידה (מודרני, אוורירי) ──
    "r_card":     "14px",
    "r_ctl":      "10px",
    "r_btn":      "9px",
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
    padding-bottom: 10px;
    border-bottom: 2px solid $blue_200;
    margin-bottom: 6px;
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
    border: 1px solid $line_2;
    border-radius: 16px;
}

/* ════ Tab bar ════ */
QTabWidget::pane {
    border: 1px solid $blue_200;
    border-radius: $r_card;
    top: 4px;
}
QTabBar::tab {
    font-weight: 600;
    font-size: $fs_tab;
    min-width: 108px;
    padding: 10px 20px;
    border-radius: $r_ctl;
    color: $ink_soft;
    background-color: transparent;
    margin: 3px 3px 6px 3px;
}
/* Note: position-qualified selectors (:top/:bottom/...) so we match
   qt-material's more-specific `QTabBar::tab:top:selected` rule and override its
   blue text — otherwise we'd get unreadable blue-on-blue. */
QTabBar::tab:selected,
QTabBar::tab:top:selected, QTabBar::tab:bottom:selected,
QTabBar::tab:left:selected, QTabBar::tab:right:selected {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3dd6bf, stop:0.49 #16b096, stop:0.51 #109a80, stop:1 $blue_700);
    color: #ffffff;
    font-weight: 700;
}
QTabBar::tab:!selected:hover,
QTabBar::tab:top:!selected:hover, QTabBar::tab:bottom:!selected:hover,
QTabBar::tab:left:!selected:hover, QTabBar::tab:right:!selected:hover {
    background-color: $blue_100;
    color: $blue_700;
}
QTabBar::tab:selected:hover,
QTabBar::tab:top:selected:hover, QTabBar::tab:bottom:selected:hover,
QTabBar::tab:left:selected:hover, QTabBar::tab:right:selected:hover {
    color: #ffffff;
}

/* ════ Inner sub-tabs (v2.59: 3 top-level areas hold the old tabs) ════
   Lighter, smaller pills so the second row reads as sub-navigation and not as
   a duplicate of the main tab bar. */
QTabWidget[subtabs="true"]::pane {
    border: none;
    top: 0px;
}
QTabWidget[subtabs="true"] QTabBar::tab {
    font-size: 13px;
    min-width: 84px;
    padding: 6px 16px;
    margin: 2px 2px 4px 2px;
}
QTabWidget[subtabs="true"] QTabBar::tab:selected,
QTabWidget[subtabs="true"] QTabBar::tab:top:selected {
    background: #d9f2ea;
    color: #0f766e;
    font-weight: 700;
}
QTabWidget[subtabs="true"] QTabBar::tab:selected:hover,
QTabWidget[subtabs="true"] QTabBar::tab:top:selected:hover {
    color: #0f766e;
}

/* ════ Tables — roomier rows for readability ════ */
QTableWidget, QTableView {
    border-radius: 10px;
    outline: none;
    show-decoration-selected: 1;
    gridline-color: $line_2;
    font-size: $fs_table;
    alternate-background-color: #f8fafc;   /* neutral slate, not baby-blue */
    background-color: $surface;
}
QTableWidget::item, QTableView::item {
    padding: 11px 14px;
    border: none;
    color: $ink;
}
QTableWidget::item:hover, QTableView::item:hover { background-color: #eaf7f2; }
QTableWidget::item:selected, QTableView::item:selected,
QTableWidget::item:selected:focus, QTableView::item:selected:focus {
    background-color: #ccf1e6;
    color: $blue_900;
}
QTableWidget::item:selected:hover, QTableView::item:selected:hover {
    background-color: #aee9d8;
    color: $blue_900;
}
/* Premium table header: clean neutral surface with a crisp blue accent underline
   (instead of a saturated blue fill) — reads like a modern data table. */
QHeaderView::section {
    font-weight: 700;
    font-size: $fs_table;
    min-height: 44px;
    padding: 11px 14px;
    border: none;
    border-bottom: 2px solid $blue_400;
    border-left: 1px solid $line_2;
    background-color: #f2f8f5;
    color: $blue_700;
}
QHeaderView::section:hover { background-color: #e5f2ec; }

/* ════ Buttons — hierarchy: primary / success / danger / ghost ════ */
QPushButton {
    border-radius: $r_btn;
    font-weight: 700;
    min-width: 80px;
    min-height: 34px;
    padding: 8px 18px;
}
QPushButton:focus { outline: none; }
QPushButton:pressed { padding-top: 7px; padding-bottom: 5px; }

/* PRIMARY — the single dominant action per screen. Premium 4-stop glossy:
   bright top sheen → light-mid → darker-mid reflection line at 50% → deep base. */
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #45e0c8, stop:0.49 #16b096, stop:0.51 #109a80, stop:1 #0a5648);
    color: #ffffff;
    border: none;
    font-weight: 800;
}
QPushButton#primary:hover   { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5fecd6, stop:0.49 #1cc4a8, stop:0.51 #14b096, stop:1 $blue_600); }
QPushButton#primary:pressed { background: $blue_900; }
QPushButton#primary:focus   { border: 2px solid $blue_200; }
QPushButton#primary:disabled { background: $line; color: $muted; }

QPushButton#danger {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff9490, stop:0.49 #e9524d, stop:0.51 #d93a35, stop:1 #a81816);
    color: #ffffff; border: none;
}
QPushButton#danger:hover   { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffaba7, stop:0.49 #ef625d, stop:0.51 #e34741, stop:1 $danger_dk); }
QPushButton#danger:pressed { background: $danger_dk; }
QPushButton#danger:focus   { border: 2px solid $danger_soft; }
QPushButton#danger:disabled { background: $line; color: $muted; }

QPushButton#success {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #63d488, stop:0.49 #35a556, stop:0.51 #2e9e4f, stop:1 #167030);
    color: #ffffff; border: none;
}
QPushButton#success:hover   { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #78de9a, stop:0.49 #3cb060, stop:0.51 #33a656, stop:1 $success_dk); }
QPushButton#success:pressed { background: $success_dk; }
QPushButton#success:focus   { border: 2px solid $success_soft; }
QPushButton#success:disabled { background: $line; color: $muted; }

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
    border-radius: $r_ctl;
    padding: 7px 12px;
    selection-background-color: $blue_200;
    selection-color: $blue_900;
}
/* Empty fields in an RTL app still park the cursor on the LEFT (Qt follows the
   keyboard layout, not the widget direction). Force right alignment so the
   cursor and typed text start on the right, like Hebrew users expect. */
/* AlignAbsolute matters: without it Qt flips AlignRight back to visual-left
   for the placeholder text (the same RTL flip as in table cells). */
QLineEdit { qproperty-alignment: 'AlignRight|AlignAbsolute|AlignVCenter'; }
QAbstractSpinBox { qproperty-alignment: 'AlignRight|AlignAbsolute|AlignVCenter'; }
QLineEdit, QComboBox, QDateEdit, QSpinBox { min-height: 22px; }
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QComboBox:hover, QDateEdit:hover, QSpinBox:hover {
    border-color: $blue_400;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: $blue_600;
    background-color: #f7fdfb;
}
QComboBox:focus, QDateEdit:focus, QSpinBox:focus { border-color: $blue_600; }
QLineEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {
    background-color: $field_bg;
    color: $muted;
}

/* ════ ComboBox — modern field + floating popup ════ */
QComboBox {
    background-color: $surface;
    border: 1.5px solid $line;
    border-radius: $r_ctl;
    padding: 7px 14px;
    min-height: 22px;
    color: $ink;
}
QComboBox:hover { border-color: $blue_400; }
QComboBox:focus, QComboBox:on { border-color: $blue_600; }
QComboBox:on       { background-color: #f7fdfb; }
QComboBox:disabled { background-color: $field_bg; color: $muted; }

/* drop-down button — in RTL it sits on the LEFT; give it its own rounded hit area */
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: left center;
    width: 30px;
    margin: 3px;
    border: none;
    border-radius: 8px;
}
QComboBox::drop-down:hover { background-color: $blue_100; }
QComboBox::down-arrow          { width: 14px; height: 14px; }
QComboBox::down-arrow:disabled { width: 14px; height: 14px; }

/* the popup list — a floating rounded card with airy, pill-shaped rows */
QComboBox QAbstractItemView {
    border: 1px solid $line;
    border-radius: $r_ctl;
    background-color: $surface;
    padding: 6px;
    outline: none;
    selection-background-color: transparent;   /* rows draw their own highlight */
}
QComboBox QAbstractItemView::item {
    min-height: 34px;
    padding: 9px 16px;
    margin: 2px 3px;
    border-radius: 8px;
    color: $ink;
    background-color: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background-color: $blue_100;
    color: $blue_700;
}
QComboBox QAbstractItemView::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #14b8a6, stop:1 $blue_700);
    color: #ffffff;
}

/* ════ CheckBox + item-view checkboxes (tables) ════ */
QCheckBox { background-color: transparent; }
QCheckBox::indicator,
QTableView::indicator, QTableWidget::indicator, QAbstractItemView::indicator {
    width: 22px; height: 22px;
    border-radius: 5px;
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
    background-color: #7dd3c0;
}
QCheckBox::indicator:disabled,
QTableView::indicator:disabled, QTableWidget::indicator:disabled,
QAbstractItemView::indicator:disabled {
    background-color: $field_bg;
    border-color: $line;
}

/* ════ Scrollbars — overlay minimal, wide enough to grab by finger (touch) ════ */
QScrollBar:vertical   { background: transparent; width: 14px;  margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 14px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #c2cbd6; border-radius: 6px; min-height: 44px; min-width: 44px;
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

/* ════ Main window — clean near-white with a faint blue lift ════ */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fbfdfc, stop:1 $page);
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
    border-radius: $r_card;
    margin-top: 18px;
    padding-top: 14px;
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

/* ════ Branded top app-bar ════ */
QFrame#appbar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #06382e, stop:0.55 $blue_700, stop:1 #12a385);
    border: none;
    border-radius: $r_card;
}
QLabel#appbar_logo {
    background-color: #ffffff;
    border-radius: 12px;
    padding: 6px;
}
QLabel#appbar_title {
    color: #ffffff;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0.6px;
}
QLabel#appbar_sub {
    color: rgba(255,255,255,0.88);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.3px;
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
# One-time picks stay BLUE explicitly (v2.60): with the green brand palette a
# palette-derived tint would collide with the green weekly rows above.
SELECTED_BG = "#e3f0fd"
SELECTED_FG = "#0d47a1"

# ── Recipient status colors ──────────────────────────────────────────────────
SUSPENDED_FG = "#8b6914"
ENDED_FG     = "#94a3b8"

# ── Legacy alias (used by test_all.py) ─────────────────────────────────────
DARK_BLUE = EXTRA_QSS

"""v3.65 visual probe + asserts: app-wide picture background (utils/wallpaper.py)
and its Settings controls. Temp DB — never touches real data.

Asserts: the wallpaper paints (corner pixels tinted vs. 'none'), tab surfaces
inside the main window are transparent, custom picture round-trip, opacity
clamp, per-machine settings excluded from sync, standalone tab keeps its opaque
page colour."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "dev", "_shots")
os.makedirs(OUT, exist_ok=True)

d = tempfile.mkdtemp()
import database as db
db.DB_PATH = os.path.join(d, "shot.db")
db.BACKUP_DIR = os.path.join(d, "backups")
db.APP_BG_PATH = os.path.join(d, "app_bg")
db.init_db()

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QColor, QPixmap
import styles
app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
styles.apply_app_theme(app, 100)

for i in range(8):
    db.add_recipient({"full_name": f"משפחה{i} ישראל", "phone1": f"05012345{i:02d}",
                      "frequency": "שבועי", "priority": 4, "status": "פעיל", "souls": 3})
db.set_setting("available_products", "5")

from utils import wallpaper, sync
from main import MainWindow

assert os.path.exists(wallpaper.default_path()), "bg_default.png missing"
assert "app_bg_mode" in sync.EXCLUDED_SETTINGS and "app_bg_opacity" in sync.EXCLUDED_SETTINGS

win = MainWindow()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1500, 950)
win.show()
for _ in range(4):
    app.processEvents()

surfaces = [w for w in win.findChildren(QWidget) if w.objectName() in wallpaper.SURFACE_NAMES]
# group-tab is renamed to tab_dist by MainWindow._leaf (its own QSS never
# painted inside the main window anyway) → 3 flagged surfaces
assert len(surfaces) == 3, [w.objectName() for w in surfaces]
assert all(w.property("wallpaper") is True for w in surfaces)


def shot(name):
    for _ in range(4):
        app.processEvents()
    img = win.grab().toImage()
    img.save(os.path.join(OUT, name))
    return img


def corner(img):
    # a point on the page surface near the top-left corner (the green blob of
    # the default picture); the bottom-left is covered by the action bar
    return QColor(img.pixel(40, 200))


default_img = shot("wallpaper_v365_default.png")
c_default = corner(default_img)

wallpaper.use_none(); win.apply_wallpaper()
none_img = shot("wallpaper_v365_none.png")
c_none = corner(none_img)
assert (c_none.red(), c_none.green(), c_none.blue()) == (0xF5, 0xF7, 0xFB), c_none.name()
assert c_default.name() != c_none.name(), "wallpaper not painted (corner identical to plain)"
# the amber/green blobs are stronger than the flat page colour: the tint must
# visibly change the pixel, but at 45% it stays light (not the raw picture)
assert c_none.red() - c_default.red() > 40, (c_default.name(), c_none.name())   # greenish tint
assert c_default.lightness() > 150, c_default.name()

# opacity 100 → stronger than 45
wallpaper.use_default(); wallpaper.set_opacity(100); win.apply_wallpaper()
full_img = shot("wallpaper_v365_full.png")
c_full = corner(full_img)
assert c_full.red() < c_default.red(), (c_full.name(), c_default.name())
assert wallpaper.opacity() == 100
wallpaper.set_opacity(250); assert wallpaper.opacity() == 100
wallpaper.set_opacity(-5); assert wallpaper.opacity() == 0
wallpaper.set_opacity(45)

# custom picture round-trip: a solid red image → corner turns reddish
red = os.path.join(d, "red.png")
pm = QPixmap(64, 64); pm.fill(QColor("#ff0000")); pm.save(red)
assert wallpaper.set_custom(red) == ""
assert wallpaper.mode() == "custom" and os.path.exists(wallpaper.custom_path())
win.apply_wallpaper()
c_red = corner(shot("wallpaper_v365_custom.png"))
assert c_red.red() > c_red.green() + 60, c_red.name()
# bad file → Hebrew error, nothing changed
bad = os.path.join(d, "bad.png"); open(bad, "w").write("not an image")
assert wallpaper.set_custom(bad)
assert wallpaper.mode() == "custom"
# custom file vanished → falls back to default (never paints nothing)
os.remove(wallpaper.custom_path())
assert wallpaper.mode() == "default"
wallpaper.use_default(); win.apply_wallpaper()

# settings tab controls reflect state
st = win.settings_tab
win.navigate_to_tab(st)
st.refresh()
for _ in range(3):
    app.processEvents()
assert "ברירת המחדל" in st.lbl_bg_status.text(), st.lbl_bg_status.text()
assert not st.btn_bg_default.isEnabled() and st.btn_bg_none.isEnabled()
assert st.bg_opacity_spin.value() == 45
st._bg_none()
assert "בלי" in st.lbl_bg_status.text() and not st.bg_opacity_spin.isEnabled()
st._bg_default()
assert st.btn_bg_none.isEnabled()
shot("wallpaper_v365_settings.png")

# standalone tab (tests/screenshots) keeps the opaque page colour
from tabs.settings import SettingsTab
alone = SettingsTab(None)
alone.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
alone.resize(1200, 800); alone.show()
for _ in range(3):
    app.processEvents()
surf = [w for w in alone.findChildren(QWidget) if w.objectName() == "st-surface"][0]
assert surf.property("wallpaper") is None
_si = surf.grab().toImage()   # (2,2) is the scrollbar — sample the right edge
c_alone = QColor(_si.pixel(_si.width() - 3, _si.height() // 2))
assert (c_alone.red(), c_alone.green(), c_alone.blue()) == (0xF5, 0xF7, 0xFB), c_alone.name()

print("OK wallpaper: default", c_default.name(), "none", c_none.name(),
      "full", c_full.name(), "custom", c_red.name())

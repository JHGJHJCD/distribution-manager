"""Soft picture background for the whole app (v3.65, #lbxii).

The user approved a blurred green/amber wallpaper (``bg_default.png``, bundled
in the EXE) and asked that both the picture and its strength be replaceable
from Settings. Everything about it lives here:

* ``mode``     — ``default`` (bundled picture) · ``custom`` (a picture the user
                 chose; copied next to the DB as ``app_bg.<ext>``) · ``none``
                 (plain surface, exactly the pre-3.65 look).
* ``opacity``  — 0–100 %, how strongly the picture shows through (45 % default —
                 the amber corners are too loud at full strength and would
                 compete with the amber "products" panel / secondary buttons).

Both settings are **per computer** (excluded from sync in ``utils/sync.py``):
the picture file itself cannot travel through the journal, and screens differ.

``WallpaperWidget`` is the main window's central widget: it paints the base
surface colour, then the picture scaled to cover (centre-crop) with the chosen
opacity. The tab surfaces that used to paint an opaque page colour are switched
to transparent inside the main window only (``mark_surfaces``) — standalone
screenshots/tests of a single tab keep their opaque background.
"""
import os
import shutil
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QPixmap
from PyQt6.QtWidgets import QWidget

import database as db

MODE_KEY = "app_bg_mode"          # default | custom | none
OPACITY_KEY = "app_bg_opacity"    # 0..100
DEFAULT_OPACITY = 45
DEFAULT_FILE = "bg_default.png"
BASE_COLOR = "#f5f7fb"            # same as tabs.group_update._BG (the page surface)

# objectNames of the tab page-surfaces that paint an opaque page colour when
# shown standalone; inside the main window they go transparent so the
# wallpaper shows through (each tab's QSS has a matching [wallpaper="true"] rule).
SURFACE_NAMES = ("group-tab", "st-surface", "tz-surface", "mail-surface")

IMAGE_FILTER = "תמונות (*.png *.jpg *.jpeg *.bmp *.webp)"


def default_path() -> str:
    """The bundled wallpaper — next to main.py in dev, in _MEIPASS when frozen."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DEFAULT_FILE)


def custom_path() -> str:
    """The user's own picture (any extension), or '' when none is stored."""
    base = db.APP_BG_PATH
    d, stem = os.path.dirname(base), os.path.basename(base)
    try:
        for fn in sorted(os.listdir(d)):
            if fn.startswith(stem + "."):
                return os.path.join(d, fn)
    except OSError:
        pass
    return ""


def mode() -> str:
    m = (db.get_setting(MODE_KEY) or "default").strip().lower()
    if m == "custom" and not custom_path():
        m = "default"          # the file vanished — fall back, don't paint nothing
    return m if m in ("default", "custom", "none") else "default"


def opacity() -> int:
    try:
        v = int(float(db.get_setting(OPACITY_KEY) or DEFAULT_OPACITY))
    except (TypeError, ValueError):
        v = DEFAULT_OPACITY
    return max(0, min(100, v))


def picture_path() -> str:
    """Path of the picture to paint for the current mode ('' = none)."""
    m = mode()
    if m == "none":
        return ""
    if m == "custom":
        return custom_path()
    p = default_path()
    return p if os.path.exists(p) else ""


def describe() -> str:
    """Short Hebrew status for the Settings chip."""
    m = mode()
    if m == "none":
        return "בלי תמונת רקע"
    if m == "custom":
        return "תמונה מותאמת אישית ✓ · %d%%" % opacity()
    return "רקע ברירת המחדל · %d%%" % opacity()


def set_opacity(percent: int):
    db.set_setting(OPACITY_KEY, str(max(0, min(100, int(percent)))))


def use_default():
    db.set_setting(MODE_KEY, "default")


def use_none():
    db.set_setting(MODE_KEY, "none")


def _remove_custom():
    p = custom_path()
    while p:
        try:
            os.remove(p)
        except OSError:
            break
        p = custom_path()


def set_custom(src_path: str) -> str:
    """Copy the chosen picture next to the DB and switch to it.

    Returns '' on success or a Hebrew reason on failure (unreadable image /
    copy error). The picture is validated BEFORE anything is stored, so a bad
    file never leaves the user with a blank background."""
    if QPixmap(src_path).isNull():
        return ("לא הצלחתי לקרוא את התמונה שנבחרה.\n"
                "נסה תמונה אחרת (JPG או PNG רגילים עובדים הכי טוב).")
    ext = (os.path.splitext(src_path)[1] or ".png").lower()
    dest = db.APP_BG_PATH + ext
    try:
        _remove_custom()
        shutil.copyfile(src_path, dest)
    except Exception as e:                       # noqa: BLE001
        return "שמירת תמונת הרקע נכשלה:\n%s" % e
    db.set_setting(MODE_KEY, "custom")
    return ""


def mark_surfaces(root: QWidget):
    """Flag every tab page-surface under *root* as living on the wallpaper
    (their QSS turns the opaque page colour transparent for that state)."""
    for w in root.findChildren(QWidget):
        if w.objectName() in SURFACE_NAMES:
            w.setProperty("wallpaper", True)
            st = w.style()
            st.unpolish(w)
            st.polish(w)
            w.update()


class WallpaperWidget(QWidget):
    """Central widget that paints the base colour + the wallpaper behind
    everything. ``reload()`` re-reads the settings (Settings → apply live)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = QPixmap()
        self._opacity = 1.0
        self._cache = QPixmap()
        self._cache_size = None
        self.setAutoFillBackground(False)
        self.reload()

    def reload(self):
        path = picture_path()
        self._pix = QPixmap(path) if path else QPixmap()
        self._opacity = opacity() / 100.0
        self._cache = QPixmap()
        self._cache_size = None
        self.update()

    @property
    def showing_picture(self) -> bool:
        return (not self._pix.isNull()) and self._opacity > 0

    def _scaled(self) -> QPixmap:
        size = self.size()
        if self._cache_size != size or self._cache.isNull():
            self._cache = self._pix.scaled(
                size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._cache_size = size
        return self._cache

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BASE_COLOR))
        if self.showing_picture:
            scaled = self._scaled()
            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            p.setOpacity(self._opacity)
            p.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
        p.end()
        super().paintEvent(ev)

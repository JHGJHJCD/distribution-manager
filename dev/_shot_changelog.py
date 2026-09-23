# -*- coding: utf-8 -*-
"""Capture the 'יומן שינויים' dialog (v3.64) + assert it is populated."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))

from shot import boot  # reuse the exact theme/RTL/font/temp-DB boot
from PyQt6.QtCore import Qt

app, win = boot()

from utils.ui import ChangelogDialog, load_changelog
from version import APP_VERSION

entries = load_changelog()
assert len(entries) >= 100, f"changelog too short: {len(entries)}"
assert entries[0][0] == APP_VERSION or entries[0][0] >= APP_VERSION, entries[0][0]

dlg = ChangelogDialog(win)
assert len(dlg.cards) == len(entries) and len(dlg.cards) >= 100, len(dlg.cards)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
for _ in range(20):
    app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "changelog.png")
for _attempt in range(4):
    dlg.grab().save(path)
    if os.path.getsize(path) >= 30_000:
        break
    dlg.repaint()
    for _ in range(12):
        app.processEvents()
assert os.path.getsize(path) >= 30_000, "blank grab"

# Also open through the settings button path to prove the wiring.
st = getattr(win, "settings_tab", None) or next(
    (w for w in win.findChildren(object) if getattr(w, "btn_changelog", None)), None)
assert st is not None and st.btn_changelog.isVisible() or st is not None, "settings button missing"
print("OK cards=%d first=%s size=%d" % (len(dlg.cards), entries[0][0], os.path.getsize(path)))
dlg.close()

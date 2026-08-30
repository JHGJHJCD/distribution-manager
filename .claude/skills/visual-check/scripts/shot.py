#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hebrew-safe screenshot capture for מנהל חלוקה.

Boots the real app on a THROWAWAY temp DB (never touches %APPDATA% data),
applies the exact theme/RTL/font the app uses, and captures leaf tabs using the
WA_DontShowOnScreen + grab() idiom — the only way Hebrew renders correctly
(the offscreen Qt platform renders boxes; a normal on-screen grab needs focus).

Run with the pinned 3.12 interpreter:
    <py312> shot.py --all
    <py312> shot.py --tab tab_dist --tab tab_settings
    <py312> shot.py --all --out C:\\path\\to\\out --size 1360x900

Leaf objectNames (v2.76, 4 areas): tab_dist, tab_recipients, tab_search,
tab_distributions, tab_messages, tab_settings (varies by build — use --list).
"""
import argparse
import os
import sys
import tempfile

# shot.py lives at <repo>/.claude/skills/visual-check/scripts/shot.py -> 5 levels up
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, REPO)


def boot():
    """Bring the app up on a temp DB and return (app, win)."""
    import tempfile as _t
    d = _t.mkdtemp()
    import database as db
    db.DB_PATH = os.path.join(d, "shot.db")
    db.BACKUP_DIR = os.path.join(d, "backups")
    db.init_db()

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        from qt_material import apply_stylesheet
        from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
        apply_stylesheet(app, theme="light_teal.xml", invert_secondary=True, extra=QT_MATERIAL_EXTRA)
        app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
    except Exception:
        try:
            from styles import EXTRA_QSS
            app.setStyleSheet(EXTRA_QSS)
        except Exception:
            pass
    app.setFont(QFont("Segoe UI", 11))

    from main import MainWindow
    win = MainWindow()
    return app, win


def leaves(win):
    """Map objectName -> leaf widget, for whatever this build exposes."""
    out = {}
    for t in getattr(win, "_leaf_tabs", []):
        name = t.objectName()
        if name:
            out[name] = t
    return out


def main():
    p = argparse.ArgumentParser(description="Hebrew-safe app screenshots")
    p.add_argument("--tab", action="append", default=[], help="leaf objectName (repeatable)")
    p.add_argument("--all", action="store_true", help="capture every leaf tab")
    p.add_argument("--list", action="store_true", help="just print available leaf keys")
    p.add_argument("--out", default=os.path.join(REPO, "dev", "_shots"))
    p.add_argument("--size", default="1360x880")
    args = p.parse_args()

    from PyQt6.QtCore import Qt
    app, win = boot()
    keys = leaves(win)

    if args.list:
        print("available leaves:", ", ".join(sorted(keys)) or "(none)")
        return

    w, h = (int(x) for x in args.size.lower().split("x"))
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(w, h)
    win.show()
    app.processEvents(); app.processEvents()

    os.makedirs(args.out, exist_ok=True)
    want = list(keys) if args.all else [k for k in args.tab if k in keys]
    missing = [k for k in args.tab if k not in keys]
    if missing:
        print("WARNING unknown leaves:", ", ".join(missing), "| have:", ", ".join(sorted(keys)))
    if not want:
        print("nothing to capture. use --all or --tab <key>. available:", ", ".join(sorted(keys)))
        return

    for key in want:
        wdg = keys[key]
        try:
            win.navigate_to_tab(wdg)
        except Exception:
            pass
        if getattr(wdg, "refresh", None):
            try:
                wdg.refresh()
            except Exception:
                pass
        app.processEvents(); app.processEvents()
        path = os.path.join(args.out, key + ".png")
        win.grab().save(path)
        print("shot:", path)

    print("done ->", args.out)


if __name__ == "__main__":
    main()

---
name: visual-check
description: >-
  Hebrew-safe visual verification for the מנהל חלוקה PyQt6 app. Use this
  WHENEVER a change touches the UI — a tab, dialog, layout, RTL, theme, font,
  badge, or anything the user would SEE — to prove it works with a real
  screenshot instead of asking the user to check. Trigger on "צלם מסך", "verify
  the UI", "how does it look", "check the layout", "screenshot the dialog", or
  right after editing any file under tabs/, widgets.py, styles.py, or a dialog.
  It bundles the exact capture recipe that renders Hebrew correctly (the naive
  offscreen grab renders boxes), on a throwaway DB that never touches real data.
---

# Visual Check — Hebrew-safe screenshots

The top project rule: when a change is visible, **verify it yourself with a real
screenshot** — never ask the user to look. But two traps make this easy to get wrong:

1. The **offscreen Qt platform renders Hebrew as squares**. Don't use it.
2. A normal on-screen grab needs the window focused/visible and is flaky in an agent.

The working recipe (already baked into the bundled script) is
`WA_DontShowOnScreen` + `widget.grab()` after `processEvents()` — it renders
correctly without ever showing a window, and it runs on a **temp DB** so real
data in `%APPDATA%\ManhalHaluka\` is never touched.

## Capturing whole tabs

Run with the pinned 3.12 interpreter (`C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`):

```bash
python .claude/skills/visual-check/scripts/shot.py --list          # see available leaf keys
python .claude/skills/visual-check/scripts/shot.py --all            # every tab
python .claude/skills/visual-check/scripts/shot.py --tab tab_dist   # one/several tabs
```

Images land in `dev/_shots/<objectName>.png`. Leaves are addressed by `objectName`
(e.g. `tab_dist`, `tab_recipients`, `tab_search`, `tab_settings`) — position-independent,
so a reordered UI doesn't break the shot. After capture, **actually open the PNG** with the
Read tool and look at it — that's the verification; a file existing is not proof.

## Capturing a specific dialog or widget

The script covers tabs. For a dialog or a single widget, reuse the same idiom — copy
`boot()` from the script for the theme/RTL/font/temp-DB setup, then:

```python
w = MyDialog(...)                                   # build the widget under test
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.resize(900, 640)
w.show()
app.processEvents(); app.processEvents()            # twice — let layout settle
w.grab().save("dev/_shots/my_dialog.png")
```

Put such one-off probes in `dev/_shot_<thing>.py` next to the existing ones
(`dev/_shot_msgdel.py`, `dev/_shot_sync_auto.py`) — they're the canonical examples.

## Seeding data for a meaningful shot

`shot.py` boots an empty temp DB, so tabs show their empty state. When the change is only
visible with data (a populated list, a badge count, a specific recipient), add a few rows
after `boot()` via the normal `database.py` helpers (`db.add_recipient(...)`, etc.) before
navigating — mirror how `dev/_shot_msgdel.py` seeds messages. Keep it minimal: just enough
to exercise the thing you changed.

## Traps learned the hard way (v2.80)

- **Blank/garbled tab in a MainWindow grab:** the settings tab (QScrollArea content)
  can paint EMPTY or with smeared stale pixels in WA_DontShowOnScreen mode —
  especially after scrolling the scroll area before grabbing. It is a paint
  artifact, not a layout bug. Fixes: re-apply the app theme once after navigating
  (`styles.apply_app_theme(app, pct)` repolishes and wakes the content), run 4+
  `processEvents()`, and for a full-page proof grab the INNER widget directly:
  `tab.findChild(QScrollArea).widget().grab()` — that render is always clean.
- **Selecting a table row in a probe:** `table.selectRow(n)` silently does nothing
  in dialog tables here — use `table.setCurrentCell(n, 0)` (with SelectRows
  behavior it highlights the whole row and fires `itemSelectionChanged`).
- **Text-size feature (v2.80):** theme+font come from `styles.apply_app_theme(app, percent)`;
  a probe that calls `apply_stylesheet` + `EXTRA_QSS` manually still works, but the
  one-liner is now the canonical boot idiom.

## When you're done

Confirm the change visually in the PNG, then give the user a one-line plain-Hebrew note
of what now looks right. If something is off, fix the source and re-capture — don't ship
a UI change you haven't seen rendered.

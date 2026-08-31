# Known Pitfalls — מנהל חלוקה

Traps that have cost us time before. Check the relevant one before touching that area.

## Environment / build
- **Python:** build & test only with `C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe`.
  The PATH `python` is 3.14 and lacks PyQt6/openpyxl/qt-material — it fails silently.
- **EXE locked (WinError 5):** if the app is running it holds `dist/*.exe`. Delete first:
  `rm -f "dist/מנהל_חלוקה.exe" "dist/Manhal-Haluka.exe"` (the release script does this automatically).
- **`.bat` files must be CRLF** — an edit that leaves LF breaks them; normalize line endings after editing.

## UI / rendering
- **Font: Segoe UI only.** Do **not** bring back Rubik (blurry render) and do **not** add
  `AA_EnableHighDpiScaling` (removed in PyQt6).
- **Never use `QGraphicsDropShadowEffect`** on a card inside a flexible layout — it breaks
  height negotiation and squashes content.
- **Hebrew screenshots:** run **without** the offscreen platform (offscreen renders squares).
  Use `WA_DontShowOnScreen` + `grab()`.
- Keep full RTL and user-facing simplicity on every UI change.

- **App-wide text size (v2.80):** most text sizes live in the QSS, so `app.setFont` alone changes
  almost nothing. The ONLY way to change text size is `styles.apply_app_theme(app, percent)`
  (rebuilds qt-material + EXTRA_QSS with every `font-size: Npx` scaled, then sets the font).
  Setting key: `ui_font_scale` (percent, per-machine, excluded from sync).
- **`QTableWidget.selectRow()` can silently no-op** in dialog tables — use
  `setCurrentCell(row, 0)`; with SelectRows behavior it selects the row AND fires
  `itemSelectionChanged` reliably.

## Excel / printing
- **openpyxl:** use `get_column_letter(col)` only — `.column_letter` crashes on `MergedCell`.
- **Printing:** `QTextDocument` ignores `dir` → RTL columns must be written in reverse order manually
  (see `utils/print_view.py`). Values go through `html.escape`.

## Tests / data
- **Tests are standalone, not pytest:** each `test_*.py` calls `sys.exit` at module level, so
  pytest crashes on collection. Run each with the py312 interpreter directly (or `release.py test`).
- **Settings leak:** a script that runs `init_db()` on a real DB can leak. Clean with
  `DELETE FROM settings WHERE key LIKE 'need_w_%'`.
- All source files are UTF-8; the terminal shows Hebrew as mojibake but the data is fine.

## Exit / _MEI (decided — do not touch)
- The "**_MEI / Failed to remove temporary directory**" message comes from PyInstaller's
  onefile **bootloader parent process** cleaning `_MEI` after the child exits — it **cannot be
  blocked from code** (`os._exit`/`_hard_exit` run in the child). On this machine NetFree holds
  the folder for scanning so the delete fails. It does **not** harm data. The only real fix is a
  onedir build, which would break the single-EXE updater. **User's decision (27/08/2026): leave
  it as is — do not invest in blocking it again.**

## NetFree (network)
- NetFree can inject **HTTP 418 "Blocked by NetFree"** and break builds/downloads with no obvious
  cause. If something fails on the network for no reason, check whether the error body contains
  "Blocked by NetFree". Full workaround guide is in memory `reference-netfree`.

## Parallel Claude sessions on this repo (learned 30/08/2026, v2.81)
- The user sometimes opens **several chats working on the repo at once**. Before releasing,
  check `git status` — if there are modified/untracked files you didn't touch, they belong to
  another live session. **Do not** use `release.py ship` then (it runs `git add -A` and would
  sweep foreign WIP into your commit), and do not build from the main tree (the EXE would embed
  their half-done code).
- The safe recipe: commit **only your files** (`git add <paths>` + commit + push), then build
  and release from a clean detached worktree:
  `git worktree add --detach <scratchpad>/wt HEAD` → run the full test suite there → PyInstaller
  there → `gh release create v<X> <wt>/dist/Manhal-Haluka.exe --latest` → `git worktree remove`.
- Do **not** stash the other session's files even briefly — it yanks them out from under the
  live session. (Tried it; user flagged it.) Leave foreign WIP untouched in the working tree.
- Shared docs (`CLAUDE.md`, `NEXT_TASK.md`, `דיווח_תקלות.html`) may already hold the other
  session's uncommitted lines — edit them freely but leave them uncommitted for the next
  quiet commit, unless you can commit only your own file.

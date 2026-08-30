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

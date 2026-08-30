---
name: manhal-haluka
description: >-
  Workflow and guardrails for the "מנהל חלוקה" (distribution-manager) PyQt6 app.
  Use this WHENEVER working in this repo — before editing code, running tests,
  building, or releasing. It pins the correct Python 3.12 interpreter, the exact
  test/build/release sequence, and the known Windows/RTL/PyInstaller pitfalls that
  have burned us before. Trigger on any request to build, test, verify, bump the
  version, ship, release, publish a new EXE, or "שחרר" — and on any code change
  that will end in a release. If a task touches this project's UI, scoring,
  selection, sync, or release flow, consult this skill first so you don't
  reintroduce a solved bug or fat-finger a release step.
---

# מנהל חלוקה — Work & Release Skill

Guardrails and an end-to-end release script for the distribution-manager repo.
The user is **not a programmer** — work and ship, don't narrate technical steps;
end with one short plain-Hebrew release note. Verify by yourself (tests /
real screenshots), never ask the user to check manually.

## 0. The one rule that saves the most time: use the right Python

**Always** build and test with Python 3.12 — the `python` on PATH is 3.14 and is
missing PyQt6/openpyxl/qt-material, so it silently fails.

```
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe
```

The release script below already hardcodes this. When you run anything manually
(a single test, `python main.py`), use that full path.

## 1. Editing code — architecture guardrails

- Business logic lives outside the UI: `scoring.py` (need score), `selection.py`
  (who-gets-it: gate/order/reserve/balance), `database.py` (data). Tabs only display.
  **A new "who receives" rule goes in `selection.py` + a test in `test_selection.py`,
  never inside a tab.**
- Don't break backward compat; never rename DB columns/fields without a migration.
- Reuse existing code before writing new; extract a shared helper instead of duplicating.
- Priority order on conflict: **data integrity → business rules → stability → UX → code quality.**
- Read `references/pitfalls.md` before touching fonts, shadows, printing, Excel,
  screenshots, or the exit/`_MEI` flow — those are the traps that keep recurring.

## 2. Verify before you ship (Definition of Done)

A change is done only when it **actually works and was verified** — not just "didn't crash".

- Run the tests touching your change. They are standalone scripts, **not pytest**
  (each `test_*.py` calls `sys.exit` at module level, so pytest collection crashes).
  Run the whole relevant set at once:

  ```bash
  python .claude/skills/manhal-haluka/scripts/release.py test
  ```

  or one file: `<py312> test_selection.py`.
- If you touched UI, verify **visually** (real screenshot / run), not only that code runs.
  Screenshots of Hebrew must run **without** the offscreen platform (offscreen renders
  boxes) — use `WA_DontShowOnScreen` + `grab()`.
- In a structural change, update `CLAUDE.md`; status/"where we stopped" goes in `NEXT_TASK.md`.

## 3. Release — one verified command

The standing decision: **after any verified code change, release to GitHub without being
asked** (bump → build → commit/push → release). Never release code that wasn't verified.

The bundled script does the whole chain deterministically and aborts on any failure, so
no step gets skipped and nothing is fat-fingered:

```bash
python .claude/skills/manhal-haluka/scripts/release.py ship 2.79 -m "גרסה 2.79 — <תיאור קצר>"
```

`ship <version> -m <commit-msg>` runs, in order:
1. Bump `APP_VERSION` in `version.py` to the given version.
2. Run the test suite — **abort if anything fails.**
3. Build the EXE with `python -m PyInstaller --noconfirm --clean מנהל_חלוקה.spec`
   (first unlocking `dist/*.exe` if a running EXE holds it — the WinError 5 case).
4. Copy `dist/מנהל_חלוקה.exe` → `dist/Manhal-Haluka.exe` (ASCII asset name the updater expects).
5. `git add -A` + commit with your message + push. **No `Co-Authored-By: Claude` /
   `Generated with Claude Code` credit** (user's decision; a commit-msg hook also strips it).
6. `gh release create v<version> dist/Manhal-Haluka.exe --latest` on repo
   `JHGJHJCD/distribution-manager` (uses the full `gh.exe` path — gh isn't on PATH).

**Because `ship` pushes and publishes (outward-facing), confirm the version + commit
message with the user in one short line before running it** — unless they already said
"release it". Everything before the push is safe to run freely.

Subcommands for partial runs (all safe except `ship`):
- `release.py test` — run the standalone test suite, report pass/fail per file.
- `release.py build` — bump-free build + ASCII copy only (local verify, no git/gh).
- `release.py bump 2.79` — only rewrite `APP_VERSION`.

## 4. After shipping

Give one plain-Hebrew release note: what changed and what it gives the user. Update
`דיווח_תקלות.html` if the version/structure changed (see memory `reference-bug-report-file`).

## Quick reference

- Run app: `<py312> main.py` (password `1234`).
- Repo / updater: `JHGJHJCD/distribution-manager`, tag `v<APP_VERSION>`, asset `Manhal-Haluka.exe`.
- DB + backups live in `%APPDATA%\ManhalHaluka\`, separate from the EXE.
- Full pitfalls list: `references/pitfalls.md`.

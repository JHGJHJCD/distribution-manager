---
name: db-migration
description: >-
  How to change the SQLite schema of the מנהל חלוקה app safely — adding a column
  or table without breaking backward compatibility or the 2-computer sync. Use
  this WHENEVER a change needs a new column, a new table, a back-fill, or a new
  synced field. Trigger on "עמודה חדשה", "שדה חדש", "טבלה חדשה", "add a column",
  "schema change", "migration", "store X per recipient", or any edit to a CREATE
  TABLE / ALTER TABLE / the settings/recipients/distributions/messages schema.
  It enforces additive-only migrations, guid/updated_at for sync, and a matching
  sync op so the new data actually reaches the other computer.
---

# DB Migration — change the schema without breaking anything

The DB is shared across two computers via a Google-Drive journal (no server), and
old databases must keep opening. So schema changes follow three non-negotiables:

1. **Additive only, idempotent.** Never rename or drop a column, never change a
   column's meaning — the sync and old builds depend on the current names. Only
   **add**, guarded by a "does it already exist?" check so `init_db()` is safe to run
   on any-age DB, repeatedly.
2. **New data must sync.** A column no one syncs is invisible on the other computer.
   If the field is per-recipient/-distribution/-batch data, it rides an existing
   `_sync_log` op or a new one — see step 3.
3. **Verify with the sync test.** `test_sync.py` simulates two computers; it must
   still pass after any schema/sync change.

## Adding a column

`init_db()` in `database.py` migrates by checking existing columns and `ALTER`-ing
what's missing. For the **recipients** table there's a `_migrations` list of
`(col, "TYPE DEFAULT ...")` tuples in a loop — add your tuple there. For other tables
follow the `PRAGMA table_info` → `if col not in cols: ALTER TABLE ... ADD COLUMN`
pattern already used for `distributions`/`dist_batches`.

```python
# recipients: append to the _migrations list
("my_new_col", "TEXT DEFAULT ''"),     # one-line comment: what it holds / why
```

**Give every column a DEFAULT** so old rows are valid immediately. If existing rows
need a computed value, **back-fill once** — only for rows still at the default, never
re-touching a value the operator may have edited (see how `first_name`/`last_name`
back-fill from `full_name` guarded by `COALESCE(...)=''`).

## Adding a table

Add a `CREATE TABLE IF NOT EXISTS ...` in `init_db()`. Include a stable `guid TEXT`
column if rows must sync across computers (sync identifies rows by `guid`, never by
local `id`). Mirror `messages` / `dist_batches`.

## Making the field sync

Data flows out via `_sync_log(op, payload)` at each write site, and is applied on the
other side by a handler in `utils/sync.py`. Two cases:

- **Field on an already-synced row** (e.g. a new recipient attribute): include it in
  that row's existing payload builder (`_rec_sync_payload`) and its apply handler
  (`rec_upsert`). Often no new op is needed.
- **A new kind of record:** add a new op (mirror `msg_add`/`msg_delete`, or
  `fb_add`/`fb_status` from v2.80): call `_sync_log("my_op", {...})` at the write, and
  add an `_apply_my_op` handler registered in `_APPLIERS` in `utils/sync.py`. Conflicts
  resolve **last-write-wins by UTC `updated_at`** — set `updated_at` on writes so LWW
  has something to compare (a status-flag change gets its own ts field, e.g.
  `status_ts`, compared in the applier).
- **Don't forget `snapshot()`:** a new synced record kind must also be seeded there,
  or a computer that joins later never receives the existing rows (messages, reads
  and feedback all do this).

Settings that must **not** sync (secrets, local paths, geometry) go in
`EXCLUDED_SETTINGS` in `utils/sync.py`.

## Verify (in order)

```bash
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_data_safety.py
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_sync.py
C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_all.py
```

`test_sync.py` must end `ALL SYNC TESTS PASSED`. It exercises add/edit/delete
propagation, batch, LWW, offline, idempotence, and adopt-by-match — the exact things
a bad migration breaks.

## Traps

- A test script that runs `init_db()` on the **real** DB can leak settings — clean with
  `DELETE FROM settings WHERE key LIKE 'need_w_%'` (see `references/pitfalls.md` in the
  `manhal-haluka` skill). Tests should point `db.DB_PATH` at a temp file.
- Don't reorder or rename anything in `full_name` / `first_name` / `last_name` — the
  identity is **family-name-first**; changing it corrupts sync identity.

## Done means

`init_db()` migrates cleanly on an old DB, the new field syncs both directions,
`test_sync.py` + `test_data_safety.py` pass, and `CLAUDE.md` is updated if the schema
change is structural (new table / new synced op).

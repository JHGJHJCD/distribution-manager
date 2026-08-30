---
name: selection-rule
description: >-
  How to add or change a "who receives, in what order, and why" rule in the
  מנהל חלוקה app the RIGHT way. Use this WHENEVER a request touches recipient
  selection, eligibility, priority vs. need score, ordering, tie-breaks,
  reserve/waitlist, one-time-priority distribution, community balancing, or
  distribution filters. Trigger on "מי מקבל", "סדר החלוקה", "רזרבה", "לפי ניקוד",
  "עדיפות", "סינון חלוקה", "איזון קהילות", or any change to selection.py /
  scoring.py. It keeps the single-source-of-truth architecture intact so a new
  rule doesn't get buried inside a tab where it can't be tested or reused.
---

# Selection Rule — where "who gets it" logic belongs

Every question of *who receives, in what order, and why* has **one home:
`selection.py`** (a pure module — no DB, no Qt). Tabs and `database.py` only
consume it. This matters because these rules are the heart of the app's fairness,
they're subtle, and they must be unit-testable in isolation. A rule dropped into a
tab's UI code can't be tested, gets duplicated, and silently drifts.

**The rule: new/changed selection logic goes in `selection.py` + a test in
`test_selection.py`. Never inside a tab.**

## The four business rules already living there (don't relearn them the hard way)

1. **Priority vs. need score** — priority (3/2) is only an *entry gate*
   (`is_one_time_candidate`). How you *sort* depends on mode:
   - One-time priority distribution (`rank_one_time_priority`): priority **wins** —
     every tier-3 before every tier-2; score only orders *within* a tier.
   - "Regulars by score" (`rank_by_need`): priority is only the gate; order is by
     **score alone** — a high-scoring tier-2 can beat a low tier-3.
2. **Regulars vs. one-timers** — the "distribution mode" selector: `all` (default,
   everyone active ranked by score together) / `schedule` (regulars first by
   calendar) / `scored` / `none` / `filter` (custom criteria, ignores
   priority/frequency). The one-time picker gate is active **only in `schedule`**.
3. **Reserve = waitlist** — `assign_roles` tags `_role` main/reserve/out. Reserve is
   **not recorded** by default but **is printed** as its own section. It's promoted
   only when the operator swaps it in for a no-show.
4. **Missing data → bottom of the queue** — in `scoring.annotate_need_scores` a
   missing contributor scores **0 points** (not a neutral 0.5). Missing data only
   ever hurts, never helps.

## How to add a rule — the recipe

1. **Read first.** Open `selection.py` and find the closest existing function
   (`rank_by_need`, `assign_roles`, `matches_criteria`, `balance_by_community`, …).
   Extend or mirror it — don't invent a parallel path.
2. **Keep it pure.** No DB reads, no Qt, no dialogs. Inputs are plain `list[dict]`
   rows + params; output is rows (often tagged with a `_role` / `_balance_*` marker).
   `database.py` is what fetches rows and calls your function; the tab just displays.
   Pure gate/rank functions are called **directly by the tests** — so never open a
   dialog or hit the DB inside one (that's why `_one_time_gate_ok` stays pure and the
   dialog lives in the `_ensure_*` wrapper in the tab).
3. **Tie-breaks are decided:** score → **seniority (longest wait, `days_since`)** →
   name. Reuse the existing comparator; don't re-sort by name alone.
4. **Add a test in `test_selection.py`.** It's a standalone script (not pytest):
   build rows with the `rec(...)` / `crec(...)` helpers already at the top, call your
   function, and assert with the `ok(name, cond, extra)` helper. Add cases for the
   new behavior **and** its boundary (empty list, missing field, a tie).
5. **Verify:**
   ```bash
   C:\Users\יהודה\AppData\Local\Programs\Python\Python312\python.exe test_selection.py
   ```
   It must end with `ALL SELECTION SCENARIOS PASS ✓`. Also run `test_scenarios.py`
   and `test_fixes.py` if you touched shared ranking/gate code.

## Filter & community balancing (mode `filter`)

If the change is about the custom filter or cross-community balance, the surface is
larger: `FILTER_FIELDS`, `matches_criteria` (AND across fields; **missing value = out**,
a hard gate), `criteria_gap`, `community_quotas` (largest-remainder, capped at
community size), `balance_by_community`. Criteria persist in settings
`dist_filter_criteria`; quotas in `community_quotas`. "Community" = `representative`.
Mirror the existing functions and their tests rather than adding a new top-level path.

## Done means

The rule lives in `selection.py`, `test_selection.py` proves it (new + boundary
cases pass), no tab embeds the logic, and — if it changes what the operator sees —
you captured a screenshot with the `visual-check` skill. Then give the user one
plain-Hebrew line describing the new behavior.

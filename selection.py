# -*- coding: utf-8 -*-
"""Single source of truth for WHO receives a distribution, in what order, and why.

Pure business logic — NO database, NO Qt. Every screen (חד-פעמי, חלוקה ורישום)
routes its "who gets it" decision through the functions here, so the rules live
in ONE tested place instead of being re-decided in each tab. Covered end-to-end
by test_selection.py.

The four business rules (decided by the operator, 2026-07):

  1. עדיפות מול ניקוד — priority(3/2) is always the ENTRY GATE (only ראשונה/שנייה
     one-timers are candidates). How it then ranks depends on the MODE:
        • One-time priority distribution (the חד-פעמי tab) — priority DOMINATES:
          every ראשונה(3) comes before every שנייה(2); need-score only orders
          WITHIN a tier. (rank_one_time_priority)
        • Merged "קבועים לפי ניקוד" mode — priority is ONLY the gate; among the
          candidates the order is need-score ALONE, so a שנייה with a high score
          can precede a ראשונה with a low one. (rank_by_need)
  2. קבועים מול חד-פעמיים — two modes kept, chosen per distribution:
        'schedule' — regulars served first by timetable, one-timers get the rest.
        'scored'   — regulars AND one-timers compete on one need-score scale.
     This module ranks; the caller picks the mode. (See PRIORITY note in database.)
  3. רזרבה — standby only. Reserve people are handed to the distributor and
     printed as a separate section, but are NOT recorded as having received
     unless the operator activates one in place of a no-show. assign_roles marks
     them ROLE_RESERVE and `recorded_by_default(rec)` returns False for them.
  4. חוסר נתונים — a missing data point never earns a neutral score; it sinks the
     family toward the bottom of the queue. (Implemented in scoring.py — a missing
     factor contributes 0, i.e. "least needy", never 0.5.)
"""

import scoring

# ── Roles a candidate can hold in a planned distribution ──────────────────────
ROLE_MAIN = "main"        # invited to receive now (recorded when the operator saves)
ROLE_RESERVE = "reserve"  # standby — handed over, recorded ONLY if it replaces a no-show
ROLE_OUT = "out"          # not part of this distribution


def is_regular(rec: dict) -> bool:
    """A recurring recipient: a real frequency, OR tagged priority 'קבוע' (4)
    even with a blank frequency (so a קבוע without a schedule isn't lost)."""
    freq = (rec.get("frequency") or "")
    return freq != "חד-פעמי" and (freq != "" or rec.get("priority") == 4)


def is_one_time_candidate(rec: dict) -> bool:
    """RULE 1 (the gate): a one-timer is a distribution candidate only when their
    priority is a real tier — ראשונה(3) or שנייה(2). Everything else (1/0/none/
    חובת בירור) is kept as data but is NOT auto-distributed."""
    return (rec.get("frequency") or "") == "חד-פעמי" and rec.get("priority") in scoring.PRIORITY_TIERS


def manual_regular_ids(rows: list, reserve_ids=()) -> set:
    """Regulars that joined the list ONLY by a manual add (flagged `_extra` — they
    are not on this week's due list) and are real recipients, not reserve. Each
    takes a product that the one-time count must no longer promise to one-timers
    (task 13). A regular who IS due this week is on the base list and counted
    there, so he is never flagged `_extra`. Pure."""
    return {r.get("id") for r in rows
            if r.get("_extra") and is_regular(r) and not r.get("_reserve")
            and r.get("id") not in reserve_ids}


def one_time_slots(total_products: int, due_regulars: int, manual_regulars: int = 0) -> int:
    """Products left for one-timers in 'schedule' mode: the total minus the
    regulars due this week minus regulars added by hand (never below 0). Pure."""
    return max(0, total_products - due_regulars - manual_regulars)


# ── RULE 6 — frequency is a HARD gate in EVERY distribution mode (28/9/2026) ──
# יהודה, 28/9/2026: "בדרך כלל יש לנו הרבה מוצרים, הרבה מעבר לקבועים — ולכן אנחנו
# רוצים שדו-שבועי שקיבל שבוע שעבר לא יקבל, גם אם יש מספיק מוצרים. וכן חודשי
# ותלת-שבועי." Until now only the plain 'schedule' mode honoured the interval;
# scored/all/filter ranked every regular by need and pulled a bi-weekly back a
# week after his turn. Now the turn is checked ONCE, here, before any ranking,
# and database.py applies it to every mode (list AND reserve). Freed slots go to
# the next eligible people; a shorter list is left short — never back-filled
# with a not-yet-due regular. A holiday distribution (an EXTRA round, v3.75) is
# the one caller that passes ignore=True.

from datetime import date as _date, timedelta as _td

FREQUENCY_INTERVAL_DAYS = {"שבועי": 7, "דו-שבועי": 14, "תלת-שבועי": 21, "חודשי": 28}
SPACED_FREQUENCIES = frozenset({"דו-שבועי", "תלת-שבועי", "חודשי"})
FREQ_LABEL = {"דו-שבועי": "דו-שבועי", "תלת-שבועי": "תלת-שבועי", "חודשי": "חודשי"}


def next_wednesday(from_date: _date = None) -> _date:
    """The first Wednesday strictly AFTER from_date (today when omitted)."""
    d = from_date or _date.today()
    days_ahead = 2 - d.weekday()          # Wednesday = 2
    if days_ahead <= 0:
        days_ahead += 7
    return d + _td(days=days_ahead)


def cycle_wednesday(d: _date) -> _date:
    """The distribution-cycle Wednesday a date belongs to: the most recent
    Wednesday on-or-before it (Wed→Tue is one cycle). Pure."""
    return d - _td(days=(d.weekday() - 2) % 7)


def upcoming_wednesday(today: _date = None) -> _date:
    """The distribution day being prepared: today if Wednesday, else the next."""
    today = today or _date.today()
    return today if today.weekday() == 2 else next_wednesday(today)


def next_due(last_iso: str, frequency: str, today: _date = None) -> _date:
    """The Wednesday a regular is next due, from his last distribution.
    THE single interval table (database.calculate_next_dist delegates here).
    Never served → the upcoming Wednesday. A Thu–Sat date is snapped back to
    its cycle Wednesday (recorded a day or two late — normal). Pure."""
    today = today or _date.today()
    if not last_iso:
        return next_wednesday(today) if frequency == "חד-פעמי" else upcoming_wednesday(today)
    try:
        last = _date.fromisoformat(last_iso)
    except (TypeError, ValueError):
        last = today
    if last.weekday() in (3, 4, 5):
        last -= _td(days=last.weekday() - 2)
    days = FREQUENCY_INTERVAL_DAYS.get(frequency)
    if not days:                                   # חד-פעמי / blank
        return next_wednesday(today)
    if days == 7:
        # weekly = the first Wednesday after the last day (a Sun–Tue extra round
        # doesn't cancel this Wednesday — test_deep "שבועי מיום ראשון")
        return next_wednesday(last + _td(days=1))
    return next_wednesday(last + _td(days=days - 1))


def _valid_date(s) -> _date | None:
    try:
        return _date.fromisoformat(str(s)) if s else None
    except (TypeError, ValueError):
        return None


# RULE 7 — one-timers ROTATE (יהודה 28/9/2026): "אני לא רוצה שאותו חד-פעמי שהוא
# הכי נצרך יקבל כל שבוע". A non-regular who received is out of the automatic
# list for ONE_TIME_COOLDOWN_WEEKS_DEFAULT weeks (setting
# `onetime_cooldown_weeks`, synced, 0 = off) and then competes by need again.
ONE_TIME_COOLDOWN_WEEKS_DEFAULT = 3


def _one_time_turn(last: _date, cooldown_weeks: int) -> _date:
    """The first Wednesday a one-timer served on `last` is eligible again."""
    return cycle_wednesday(last) + _td(days=7 * max(0, int(cooldown_weeks)))


def is_due(rec: dict, base_wed: _date,
           cooldown_weeks: int = ONE_TIME_COOLDOWN_WEEKS_DEFAULT) -> bool:
    """RULES 6+7 — may this person be on the list of the distribution on base_wed?

    Regulars: weekly / blank frequency / never served → always due. A
    דו-שבועי/תלת-שבועי/חודשי regular is due only when his turn
    (`next_distribution`, the derived field database._recompute_recipient_dates
    writes; else computed from `last_distribution`) is on or before base_wed.
    Non-regulars (one-timers, data rows): due unless served within the last
    `cooldown_weeks` cycles (0 = no rotation).
    Either way, someone already served in THIS cycle stays due (keeps him on
    the list the moment his round is recorded, as the weekly list does). Pure."""
    last = _valid_date(rec.get("last_distribution"))
    if last is None:
        return True
    if last <= base_wed and cycle_wednesday(last) == base_wed:
        return True                                # served this very cycle
    freq = (rec.get("frequency") or "").strip()
    if is_regular(rec):
        if freq not in SPACED_FREQUENCIES:
            return True
        turn = _valid_date(rec.get("next_distribution")) or next_due(last.isoformat(), freq, base_wed)
        return turn <= base_wed
    if cooldown_weeks <= 0:
        return True
    return _one_time_turn(last, cooldown_weeks) <= base_wed


def due_filter(rows: list, base_wed: _date, ignore: bool = False,
               cooldown_weeks: int = ONE_TIME_COOLDOWN_WEEKS_DEFAULT) -> list:
    """Rows that pass RULES 6+7 (unchanged when ignore=True — holiday round). Pure."""
    if ignore:
        return list(rows)
    return [r for r in rows if is_due(r, base_wed, cooldown_weeks)]


def not_due_reason(rec: dict, base_wed: _date,
                   cooldown_weeks: int = ONE_TIME_COOLDOWN_WEEKS_DEFAULT) -> str:
    """Hebrew explanation for a person RULE 6/7 leaves out ('' when he is due):
    'דו-שבועי · קיבל ב-17/06 · התור הבא 01/07' or
    'קיבל ב-17/06 · הפסקה של 3 שבועות · חוזר ב-08/07'. For tooltips/warnings."""
    if is_due(rec, base_wed, cooldown_weeks):
        return ""
    last = _valid_date(rec.get("last_distribution"))
    freq = (rec.get("frequency") or "").strip()
    if is_regular(rec):
        turn = _valid_date(rec.get("next_distribution")) or next_due(last.isoformat(), freq, base_wed)
        return (f"{FREQ_LABEL.get(freq, freq)} · קיבל ב-{last.strftime('%d/%m')} · "
                f"התור הבא {turn.strftime('%d/%m')}")
    turn = _one_time_turn(last, cooldown_weeks)
    return (f"קיבל ב-{last.strftime('%d/%m')} · הפסקה של {int(cooldown_weeks)} שבועות · "
            f"חוזר ב-{turn.strftime('%d/%m')}")


def rank_by_need(rows: list, weights: dict) -> list:
    """Score every row (in place) and return a NEW list ordered by need — highest
    score first, tie-broken by NAME only (never by a hidden data point, so a
    factor the operator weighted 0 can't sneak back in as a tie-breaker).

    Used by the MERGED 'קבועים לפי ניקוד' mode: priority tier is deliberately NOT
    in the sort key — there it only gates who is a candidate. Once in, the order
    is pure need-score.
    Tie-break (operator's choice): equal need → whoever has WAITED LONGEST
    (days_since, desc) takes the last portion; name only as a final, stable
    fallback — so equal-need recipients aren't decided by the alphabet.
    RULE 4: families with missing data sink to the bottom, because scoring gives a
    missing factor 0 points (not a neutral half)."""
    scoring.annotate_need_scores(rows, weights)
    return sorted(rows, key=lambda r: (-(r.get("need_score") or 0),
                                       -(r.get("days_since") or 0),
                                       r.get("full_name") or ""))


def rank_one_time_priority(rows: list, weights: dict) -> list:
    """Score every row (in place) and return a NEW list ordered for the one-time
    PRIORITY distribution: RULE 1 — priority DOMINATES, so every ראשונה(3) comes
    before every שנייה(2); need-score only orders WITHIN a tier; ties by NAME.

    This is the ordering the חד-פעמי tab's 'חשב המלצה' uses, distinct from the
    merged scored mode (rank_by_need). Tie-break within a tier+score: whoever has
    WAITED LONGEST (days_since, desc), then name as a final stable fallback."""
    scoring.annotate_need_scores(rows, weights)
    return sorted(rows, key=lambda r: (-(r.get("priority") or 0),
                                       -(r.get("need_score") or 0),
                                       -(r.get("days_since") or 0),
                                       r.get("full_name") or ""))


def assign_roles(ordered: list, portions, reserve_count: int = 0) -> list:
    """Split an ALREADY-ORDERED candidate list into main / reserve / out.

    The first `portions` become ROLE_MAIN (invited now); the next `reserve_count`
    become ROLE_RESERVE (standby); the rest ROLE_OUT. `portions=None` means "no
    limit" — everyone in the list is MAIN and there is no reserve.

    Each row is annotated with rec['_role'], rec['_reserve'] (bool, for the
    existing UI tint) and rec['_plan_reason'] (a short Hebrew 'why'). Returns the
    same list for chaining."""
    for i, rec in enumerate(ordered):
        if portions is None:
            role = ROLE_MAIN
        elif i < portions:
            role = ROLE_MAIN
        elif i < portions + max(0, reserve_count):
            role = ROLE_RESERVE
        else:
            role = ROLE_OUT
        rec["_role"] = role
        rec["_reserve"] = (role == ROLE_RESERVE)
        rec["_plan_reason"] = _reason_for(rec, role, i)
    return ordered


def limit_to_products(ordered: list, portions, reserve_count: int = 0,
                      keep_ids=(), reserve_ids=()) -> list:
    """#c9k0m (user decision 2/9/2026): in the score-ranked modes the list IS
    the distribution — show (and print) only as many people as there are
    products, then `reserve_count` more as the reserve, and drop the rest.
    `portions` <= 0 / None → no limit (everyone stays, unchanged).
    `keep_ids` (manual adds / one-time picks) are always kept as MAIN and do
    not take a scored slot from anyone; `reserve_ids` (explicit reserve picks)
    are always kept as RESERVE. Source order is preserved."""
    if not portions or portions <= 0:
        return ordered
    keep = set(keep_ids or ())
    res_keep = set(reserve_ids or ())
    forced_main = [r for r in ordered if r.get("id") in keep and r.get("id") not in res_keep]
    rest = [r for r in ordered if r.get("id") not in keep and r.get("id") not in res_keep]
    assign_roles(rest, max(0, portions - len(forced_main)), reserve_count)
    for r in forced_main:
        r["_role"] = ROLE_MAIN
        r["_reserve"] = False
    for r in ordered:
        if r.get("id") in res_keep:
            r["_role"] = ROLE_RESERVE
            r["_reserve"] = True
    return [r for r in ordered if r.get("_role") != ROLE_OUT]


def recorded_by_default(rec: dict) -> bool:
    """RULE 3: whether this row should be ticked-for-recording by default when a
    distribution is saved. Main picks yes; reserve (standby) no — a reserve is
    recorded only if the operator explicitly activates them for a no-show."""
    return rec.get("_role", ROLE_MAIN) != ROLE_RESERVE


def _reason_for(rec: dict, role: str, index: int) -> str:
    score = rec.get("need_score")
    score_txt = f"ניקוד {round(score)}" if isinstance(score, (int, float)) else "ללא ניקוד"
    if role == ROLE_MAIN:
        return f"נכנס לחלוקה (מקום {index + 1}, {score_txt})"
    if role == ROLE_RESERVE:
        return f"רזרבה — ממתין למקרה שאחד המוזמנים לא יגיע ({score_txt})"
    return f"מחוץ לחלוקה הפעם ({score_txt})"


def plan_one_time(rows: list, weights: dict, portions, reserve_count: int = 0) -> list:
    """The full one-time plan from a loaded recipient list. Gates to ראשונה/שנייה
    candidates (RULE 1), ranks them priority-first then by need-score (ראשונה
    before שנייה), splits into main/reserve/out by the available portions
    (RULE 3), and appends the non-candidates (marked ROLE_OUT) after them for
    display. Pure."""
    candidates = [r for r in rows if is_one_time_candidate(r)]
    others = [r for r in rows if not is_one_time_candidate(r)]
    ranked = rank_one_time_priority(candidates, weights)
    assign_roles(ranked, portions, reserve_count)
    for r in others:
        r["_role"] = ROLE_OUT
        r["_reserve"] = False
    return ranked + others


# ── Custom broad filter (mode 'filter') ───────────────────────────────────────
# A distribution mode that ignores priority/frequency entirely and instead picks
# recipients from the FULL active list by tunable numeric thresholds (e.g. only
# families with 5+ children, or income up to X). Each field is filtered by an
# optional minimum and/or maximum; an unset bound means "no limit" on that side.
# The operator's request (2026-08): filter by number of children, monthly income,
# and disposable-per-soul. Area is intentionally NOT a criterion here.

# (data key, Hebrew label) — the fields offered in the filter dialog, in order.
FILTER_FIELDS = [
    ("children_total", "מספר ילדים"),
    ("income",         "הכנסה חודשית"),
    ("per_soul",       "פנוי לנפש"),
]


def to_number(val):
    """Best-effort numeric read of a field that may be stored as free text
    ('4,500 ₪' → 4500.0, '' → None). Returns a float, or None when no digits are
    present. Keeps a decimal point but drops thousands separators and currency."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    # Commas here are thousands separators (Israeli shekel amounts: '4,500 ₪'),
    # so drop them; keep digits, a decimal point and a leading minus, discard
    # everything else (spaces, ₪, letters). A stray extra '.' makes float() fail
    # → None, which is the safe "no usable number" answer.
    s = s.replace(",", "")
    neg = s.lstrip().startswith("-") or s.rstrip().endswith("-")   # "500-" typed RTL
    text = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    if text in ("", "."):
        return None
    if neg:
        text = "-" + text
    try:
        return float(text)
    except ValueError:
        return None


# v3.52: criteria key for a HOLIDAY distribution (kupa manager, 16/9/2026).
#   ''            → not a holiday distribution (no gate)
#   HOLIDAY_ANY   → everyone marked "נתמך חגים" (general mark)
#   '<holiday>'   → only people whose mark covers that holiday (see holidays.py)
HOLIDAY_KEY = "holiday"
HOLIDAY_ANY = "*"


def holiday_criterion(criteria: dict) -> str:
    return str((criteria or {}).get(HOLIDAY_KEY) or "").strip()


def holiday_matches(rec: dict, criteria: dict) -> bool:
    """Hard gate: does this recipient pass the holiday criterion (if any)?"""
    want = holiday_criterion(criteria)
    if not want:
        return True
    import holidays
    return holidays.supports(rec, "" if want == HOLIDAY_ANY else want)


def holiday_filter(rows: list, criteria: dict) -> list:
    """Rows that pass the holiday gate; unchanged when no holiday criterion. Pure."""
    if not holiday_criterion(criteria):
        return list(rows)
    return [r for r in rows if holiday_matches(r, criteria)]


def holiday_label(criteria: dict) -> str:
    """Hebrew text of the holiday criterion for chips/summaries ('' when off)."""
    want = holiday_criterion(criteria)
    if not want:
        return ""
    return "נתמכי חגים" if want == HOLIDAY_ANY else f"נתמכי {want}"


def criteria_is_active(criteria: dict) -> bool:
    """True if at least one field has a real (min or max) bound set, or a
    holiday criterion is chosen."""
    if holiday_criterion(criteria):
        return True
    for field, _label in FILTER_FIELDS:
        b = (criteria or {}).get(field) or {}
        if b.get("min") is not None or b.get("max") is not None:
            return True
    return False


def matches_criteria(rec: dict, criteria: dict) -> bool:
    """Does a single recipient satisfy EVERY set bound (AND across fields)?

    A recipient whose value for a CONSTRAINED field is missing/unparseable is
    EXCLUDED — we can't confirm it falls inside the requested range, and this is a
    hard eligibility filter (unlike need-scoring, where missing data only lowers
    rank). Fields with no bound set are ignored. The holiday criterion (v3.52)
    is part of the same AND."""
    if not holiday_matches(rec, criteria):
        return False
    for field, _label in FILTER_FIELDS:
        b = (criteria or {}).get(field) or {}
        lo, hi = b.get("min"), b.get("max")
        if lo is None and hi is None:
            continue
        val = to_number(rec.get(field))
        if val is None:
            return False
        if lo is not None and val < lo:
            return False
        if hi is not None and val > hi:
            return False
    return True


def filter_by_criteria(rows: list, criteria: dict) -> list:
    """Return the subset of rows matching the criteria (RULE-agnostic broad
    filter). With no active bound, returns the list unchanged. Pure."""
    if not criteria_is_active(criteria):
        return list(rows)
    return [r for r in rows if matches_criteria(r, criteria)]


def criteria_gap(rec: dict, criteria: dict) -> float:
    """How FAR a recipient is from satisfying the filter, as a WEIGHTED RELATIVE
    gap. 0.0 = already qualifies. For every CONSTRAINED field the recipient
    violates, add the relative overshoot/undershoot (gap ÷ the threshold) so
    fields on different scales stay comparable — e.g. income 1300 vs a max of 1200
    contributes 100/1200 ≈ 0.083, right next to income 1250's 50/1200 ≈ 0.042, so
    the nearer-to-qualifying family (1250) sorts first. A missing value on a
    constrained field adds a full unit (1.0) — the 'חוסר נתונים → תחתית' rule, so a
    family we can't measure never edges out one we can. Larger = farther. Pure.

    Used to order the community top-up (#lejmr): when a community's quota exceeds
    its filter-qualifiers, its NEAREST-to-qualifying members fill the rest first
    (operator's call, 2026-08), rather than the highest need-score."""
    total = 0.0
    for field, _label in FILTER_FIELDS:
        b = (criteria or {}).get(field) or {}
        lo, hi = b.get("min"), b.get("max")
        if lo is None and hi is None:
            continue
        val = to_number(rec.get(field))
        if val is None:
            total += 1.0            # missing data on a constrained field — worst
            continue
        if lo is not None and val < lo:
            total += (lo - val) / abs(lo) if lo else (lo - val)
        elif hi is not None and val > hi:
            total += (val - hi) / abs(hi) if hi else (val - hi)
    return total


def criteria_missing(rec: dict, criteria: dict) -> int:
    """How many CONSTRAINED filter fields have no usable value on this card."""
    n = 0
    for field, _label in FILTER_FIELDS:
        b = (criteria or {}).get(field) or {}
        if (b.get("min") is not None or b.get("max") is not None) \
                and to_number(rec.get(field)) is None:
            n += 1
    return n


# ── Community balance (mode 'filter', #lejmr) ─────────────────────────────────
# The operator's request (2026-08): when distributing by the broad filter, the
# products must be split FAIRLY BETWEEN COMMUNITIES ("קהילה" = everyone sharing
# the same שם נציג), so one large community can't take everything. The decided
# rules:
#   • Each community's default quota is proportional to its TOTAL size (all its
#     active members in the program), not to how many pass the filter — a
#     community of 200 gets twice the share of a community of 100.
#   • The operator may pin a manual percentage per community (settings); the
#     remaining communities split the leftover percent by size. Over-100 manual
#     totals are scaled down to 100 (normalising "at the expense of the others").
#   • Inside a community the quota is filled from its FILTER-QUALIFYING members
#     first (by need score); if the community has fewer qualifiers than quota,
#     the remainder is filled from its OTHER active members by CLOSENESS to the
#     filter (smallest weighted relative gap first — criteria_gap), so the
#     community's near-misses come in before its far-off members. Need score is
#     only a tie-break. A regular caught in this top-up is flagged for the screen
#     to highlight (operator's call, 2026-08). The share stays in the community.
#   • People without a representative form their own "ללא קהילה" group that
#     competes for a proportional share like any community.
#   • Whoever falls off because of the balance simply doesn't appear (no reserve).

NO_COMMUNITY = ""          # community key for people without a representative
NO_COMMUNITY_LABEL = "ללא קהילה"


def community_key(rec: dict) -> str:
    """The community a recipient belongs to — their נציג name, '' if none."""
    return (rec.get("representative") or "").strip()


def infer_communities(rows: list) -> dict:
    """Suggest a representative for recipients that lack one, by synagogue
    majority: if most rep-carrying members of the same בית כנסת share one נציג,
    a rep-less member of that synagogue is assumed to belong to that community.
    Returns {rec_id: suggested_rep}. Pure — the caller decides whether to save
    (the app writes it to the card marked 'שויך אוטומטית' so the operator can
    see and fix it)."""
    by_syn = {}
    for r in rows:
        syn = (r.get("synagogue") or "").strip()
        rep = community_key(r)
        if syn and rep:
            by_syn.setdefault(syn, {})
            by_syn[syn][rep] = by_syn[syn].get(rep, 0) + 1
    out = {}
    for r in rows:
        if community_key(r):
            continue
        syn = (r.get("synagogue") or "").strip()
        counts = by_syn.get(syn)
        if not counts:
            continue
        rep, n = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        total = sum(counts.values())
        # Require a strict majority of at least 2 people — a lone rep in a
        # synagogue is too thin a signal to re-assign someone's community by.
        if n >= 2 and n * 2 > total:
            out[r.get("id")] = rep
    return out


def community_quotas(n_products: int, sizes: dict, manual_pcts: dict = None) -> dict:
    """Integer product quota per community, summing to min(n, total size).

    sizes: {community: total active member count} (may include NO_COMMUNITY).
    manual_pcts: {community: percent} pinned by the operator; communities not
    pinned split the leftover percent proportionally to size. Manual totals over
    100 are scaled down to 100. Quotas are capped at the community size; capped
    leftovers are re-spread over communities with remaining capacity. Largest-
    remainder rounding keeps the total exact. Pure."""
    communities = [c for c in sizes if (sizes.get(c) or 0) > 0]
    n = max(0, int(n_products or 0))
    if not communities or n == 0:
        return {c: 0 for c in sizes}
    manual = {c: float(p) for c, p in (manual_pcts or {}).items()
              if c in sizes and p is not None and float(p) > 0}
    man_sum = sum(manual.values())
    if man_sum > 100:
        manual = {c: p * 100.0 / man_sum for c, p in manual.items()}
        man_sum = 100.0
    free = [c for c in communities if c not in manual]
    free_size = sum(sizes[c] for c in free)
    weights = {}
    for c in communities:
        if c in manual:
            weights[c] = manual[c]
        elif free_size > 0:
            weights[c] = (100.0 - man_sum) * sizes[c] / free_size
        else:
            weights[c] = 0.0
    total_w = sum(weights.values())
    if total_w <= 0:
        # degenerate (e.g. manual pins at 100% on empty communities) — by size
        weights = {c: float(sizes[c]) for c in communities}
        total_w = sum(weights.values())

    def _largest_remainder(amount: int, weight_map: dict, caps: dict) -> dict:
        wsum = sum(weight_map.values())
        if wsum <= 0 or amount <= 0:
            return {c: 0 for c in weight_map}
        exact = {c: amount * w / wsum for c, w in weight_map.items()}
        base = {c: min(int(exact[c]), caps[c]) for c in weight_map}
        left = amount - sum(base.values())
        order = sorted(weight_map,
                       key=lambda c: (-(exact[c] - int(exact[c])), -weight_map[c], c))
        while left > 0:
            gave = False
            for c in order:
                if left <= 0:
                    break
                if base[c] < caps[c]:
                    base[c] += 1
                    left -= 1
                    gave = True
            if not gave:      # everyone at cap — no more room anywhere
                break
        return base

    caps = {c: int(sizes[c]) for c in communities}
    quotas = _largest_remainder(min(n, sum(caps.values())), weights, caps)
    for c in sizes:
        quotas.setdefault(c, 0)
    return quotas


def balance_by_community(rows: list, criteria: dict, weights: dict,
                         n_products: int, manual_pcts: dict = None) -> list:
    """The community-balanced filter pick: choose ~n_products recipients from
    the ACTIVE list so each community receives its quota (proportional to size or
    operator-pinned percent). Within a community: filter-qualifiers first by
    need score, then (if the quota isn't filled) other members by need score,
    each marked rec['_balance_fill']=True. Every pick carries rec['_community'].
    Returns the picked list ordered by need score (desc). Pure."""
    if n_products is None or n_products <= 0:
        return rank_by_need(filter_by_criteria(rows, criteria), weights)
    groups = {}
    for r in rows:
        groups.setdefault(community_key(r), []).append(r)
    sizes = {c: len(members) for c, members in groups.items()}
    quotas = community_quotas(n_products, sizes, manual_pcts)
    picked = []
    for c, members in groups.items():
        q = quotas.get(c, 0)
        if q <= 0:
            continue
        qualifying = filter_by_criteria(members, criteria)
        ranked_q = rank_by_need(qualifying, weights)
        take = ranked_q[:q]
        for r in take:
            r["_balance_fill"] = False
        if len(take) < q:
            # Top-up: the community's OTHER members (not already taken). Ordered
            # by CLOSENESS to the filter — the near-misses come in first (#lejmr,
            # operator's example: income 1250 before 1300), NOT by need score.
            # Need score is only a tie-break so equal-gap picks stay sensible.
            # A regular caught in the top-up is flagged (_balance_regular) so the
            # screen can highlight it.
            others = [r for r in members if all(r is not t for t in take)]
            scoring.annotate_need_scores(others, weights)
            # Missing data first-class LAST (RULE 4): the flat 1.0 criteria_gap
            # gives "no data" can be smaller than a known far-off gap (income
            # 3000 vs max 1200 = 1.5), so count the missing fields before it.
            others.sort(key=lambda r: (criteria_missing(r, criteria),
                                       criteria_gap(r, criteria),
                                       -(r.get("need_score") or 0),
                                       -(r.get("days_since") or 0),
                                       r.get("full_name") or ""))
            fill = others[:q - len(take)]
            for r in fill:
                r["_balance_fill"] = True
                r["_balance_regular"] = is_regular(r)
            take = take + fill
        for r in take:
            r["_community"] = c or NO_COMMUNITY_LABEL
        picked.extend(take)
    # Re-score the final picked set on ONE common scale so the displayed ניקוד is
    # comparable across communities (each community was ranked on its own
    # normalization above — fine for choosing WITHIN a community, but the merged
    # list should read consistently).
    scoring.annotate_need_scores(picked, weights)
    return sorted(picked, key=lambda r: (-(r.get("need_score") or 0),
                                         -(r.get("days_since") or 0),
                                         r.get("full_name") or ""))

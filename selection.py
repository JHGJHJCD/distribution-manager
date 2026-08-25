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
    neg = s.lstrip().startswith("-")
    text = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    if text in ("", "."):
        return None
    if neg:
        text = "-" + text
    try:
        return float(text)
    except ValueError:
        return None


def criteria_is_active(criteria: dict) -> bool:
    """True if at least one field has a real (min or max) bound set."""
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
    rank). Fields with no bound set are ignored."""
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
#     the remainder is filled from its OTHER active members by need score — the
#     community's share stays inside the community (operator's explicit call).
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
            # Top-up: the community's OTHER members (not already taken), by need
            # — the community's share stays inside the community.
            others = [r for r in members if all(r is not t for t in take)]
            ranked_o = rank_by_need(others, weights)
            fill = ranked_o[:q - len(take)]
            for r in fill:
                r["_balance_fill"] = True
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

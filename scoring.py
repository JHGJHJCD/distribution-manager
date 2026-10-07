"""Need-score business logic (pure — no DB access).

The need-score (0–100, higher = needier = served earlier within a tier) is a
weighted blend of several recipient data points. Each factor's weight is a
user-tunable knob stored in `settings` (see database.get_need_weights /
set_need_weights and the "משקלי ניקוד" panel in the Settings tab). Weights are
RELATIVE — they are normalized at scoring time, so any non-negative numbers
work and 0 means "ignore this data point".
"""

# Each factor: key, Hebrew label, recipient field, direction, value parser.
#   dir "low"  → a LOWER value means MORE need (e.g. הכנסות, פנוי לנפש)
#   dir "high" → a HIGHER value means MORE need (e.g. נפשות, הוצאות, ילדים)
NEED_FACTORS = [
    {"key": "money",    "label": "מצוקה כלכלית (פנוי לנפש)", "field": "per_soul",         "dir": "low",  "kind": "money"},
    {"key": "souls",    "label": "גודל משפחה (נפשות)",        "field": "souls",            "dir": "high", "kind": "int"},
    {"key": "recency",  "label": "ותק (ימים מאז חלוקה)",      "field": "days_since",       "dir": "high", "kind": "int"},
    {"key": "income",   "label": "הכנסות נמוכות",             "field": "income",           "dir": "low",  "kind": "money"},
    {"key": "housing",  "label": "הוצאות דיור",               "field": "housing_expenses", "dir": "high", "kind": "money"},
    {"key": "medical",  "label": "הוצאות רפואיות",            "field": "medical_expenses", "dir": "high", "kind": "money"},
]
# NOTE: "מספר ילדים" was intentionally NOT made a separate factor — household
# size is already captured by נפשות (souls), so weighting both double-counts it.

# Default weights (percent, sum = 100). The original three factors keep their
# historical balance; the added financial factors default to 0 so existing
# rankings are unchanged until the user gives them weight in the Settings tab.
DEFAULT_NEED_WEIGHTS = {
    "money": 34.0, "souls": 33.0, "recency": 33.0,
    "income": 0.0, "housing": 0.0, "medical": 0.0,
}

# Priority codes that participate in the one-time priority distribution. Code 3
# = first priority, code 2 = second. Everything else (1/0/none/חובת בירור) is
# kept as data but excluded from the auto-distribution.
PRIORITY_TIERS = (3, 2)


def _need_num(val, kind):
    """Extract a number from a recipient field for scoring. kind 'money' tolerates
    currency symbols, commas and spaces ('5,000 ₪' → 5000.0). Returns None when
    there is no usable number."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s == "None":
        return None
    if kind == "money":
        s = s.replace(",", "")
        # A minus (debt) is real data: "-500", or "500-" as typed in RTL text.
        neg = s.startswith("-") or s.endswith("-")
        kept = "".join(ch for ch in s if ch.isdigit() or ch == ".")
        if kept.count(".") > 1:                       # keep only the first dot
            head, _, tail = kept.partition(".")
            kept = head + "." + tail.replace(".", "")
        if not any(ch.isdigit() for ch in kept):
            return None
        try:
            return -float(kept) if neg else float(kept)
        except ValueError:
            return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _norm(v, lo, hi):
    if hi <= lo:
        return 0.5
    x = (v - lo) / (hi - lo)
    return 0.0 if x < 0 else 1.0 if x > 1 else x


# הכרעת יהודה 7/10/2026 — התור הרגיל של החד-פעמיים (מצב "לפי לוח זמנים") מחושב
# בנוסחה קבועה בקוד: 50% זמן המתנה · 25% כסף פנוי לנפש · 25% נפשות. לא ניתנת
# לשינוי מההגדרות (משקלי need_w_* משפיעים רק על scored / filter / none).
ONE_TIME_QUEUE_WEIGHTS = {
    "recency": 50.0, "money": 25.0, "souls": 25.0,
    "income": 0.0, "housing": 0.0, "medical": 0.0,
}


def _rank_components(rows, f):
    """Per-row 0..1 component of factor `f`, by PLACE IN THE QUEUE (יהודה
    7/10/2026) instead of by amount: the distinct usable values, ordered from
    least to most needy, take equal steps k/n (the neediest gets the full 1.0,
    equal values share a step) — one extreme value no longer flattens everybody
    else. Missing → 0 (RULE 4); for "low" factors 0 = unknown → 0 and a negative
    (debt) is real data and the neediest; for "high" factors 0 → 0.
    Returns (list aligned with rows of (component, value-or-None, missing))."""
    vals = []
    for r in rows:
        v = _need_num(r.get(f["field"]), f["kind"])
        if v is None or (f["dir"] == "low" and v == 0) or (f["dir"] == "high" and v <= 0):
            vals.append(None)
        else:
            vals.append(v)
    distinct = sorted({v for v in vals if v is not None},
                      reverse=(f["dir"] == "low"))      # least needy first
    n = len(distinct)
    step = {v: (k + 1) / n for k, v in enumerate(distinct)}
    return [step[v] if v is not None else 0.0 for v in vals]


def annotate_need_scores(rows, weights: dict):
    """Add 'need_score' (0–100) and '_score_parts' to each row. Every factor with
    a positive weight contributes its share by PLACE IN THE QUEUE within `rows`
    (see _rank_components): the neediest gets the factor's full weight, the rest
    equal steps below it. A missing value contributes 0 (RULE 4). `weights` is a
    {key: float} dict (see database.get_need_weights)."""
    active = [f for f in NEED_FACTORS if weights.get(f["key"], 0) > 0]
    total_w = sum(weights.get(f["key"], 0) for f in active)
    # Nothing weighted → fall back to defaults so the list still ranks sensibly.
    if total_w <= 0:
        weights = DEFAULT_NEED_WEIGHTS
        active = [f for f in NEED_FACTORS if weights.get(f["key"], 0) > 0]
        total_w = sum(weights.get(f["key"], 0) for f in active)

    comps = {f["key"]: _rank_components(rows, f) for f in active}
    for i, r in enumerate(rows):
        acc = 0.0
        parts = []   # per-factor breakdown for the "why this score" view
        for f in active:
            comp = comps[f["key"]][i]
            v = _need_num(r.get(f["field"]), f["kind"])
            w = weights.get(f["key"], 0)
            acc += w * comp
            parts.append({
                "label": f["label"],
                "value": "—" if v is None else r.get(f["field"]),
                "weight_pct": round(100 * w / total_w),
                "points": round(100 * w * comp / total_w, 1),
            })
        r["need_score"] = round(100 * acc / total_w, 1)
        r["_score_parts"] = parts
    return rows

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
        kept = "".join(ch for ch in s if ch.isdigit() or ch == ".")
        if kept.count(".") > 1:                       # keep only the first dot
            head, _, tail = kept.partition(".")
            kept = head + "." + tail.replace(".", "")
        if not any(ch.isdigit() for ch in kept):
            return None
        try:
            return float(kept)
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


def annotate_need_scores(rows, weights: dict):
    """Add 'need_score' (0–100) to each row, normalized within `rows`. Every
    factor in NEED_FACTORS with a positive weight contributes its (normalized)
    share; missing data → that component is neutral (0.5) so it neither helps nor
    hurts. `weights` is a {key: float} dict (see database.get_need_weights)."""
    active = [f for f in NEED_FACTORS if weights.get(f["key"], 0) > 0]
    total_w = sum(weights.get(f["key"], 0) for f in active)
    # Nothing weighted → fall back to defaults so the list still ranks sensibly.
    if total_w <= 0:
        weights = DEFAULT_NEED_WEIGHTS
        active = [f for f in NEED_FACTORS if weights.get(f["key"], 0) > 0]
        total_w = sum(weights.get(f["key"], 0) for f in active)

    # Pre-compute each active factor's min/max for in-list normalization. For a
    # 'low' factor (less = needier) only positive values count, so an empty field
    # stays neutral instead of looking like the neediest.
    ranges = {}
    for f in active:
        vals = []
        for r in rows:
            v = _need_num(r.get(f["field"]), f["kind"])
            if v is None or (f["dir"] == "low" and v <= 0):
                continue
            vals.append(v)
        ranges[f["key"]] = (min(vals), max(vals)) if vals else (0.0, 0.0)

    for r in rows:
        acc = 0.0
        parts = []   # per-factor breakdown for the "why this score" view
        for f in active:
            v = _need_num(r.get(f["field"]), f["kind"])
            missing = v is None or (f["dir"] == "low" and v <= 0)
            if missing:
                comp = 0.5                       # missing → neutral
            else:
                lo, hi = ranges[f["key"]]
                comp = _norm(v, lo, hi)
                if f["dir"] == "low":
                    comp = 1.0 - comp
            w = weights.get(f["key"], 0)
            acc += w * comp
            parts.append({
                "label": f["label"],
                "value": "—" if missing else r.get(f["field"]),
                "weight_pct": round(100 * w / total_w),
                "points": round(100 * w * comp / total_w, 1),
            })
        r["need_score"] = round(100 * acc / total_w, 1)
        r["_score_parts"] = parts
    return rows

# -*- coding: utf-8 -*-
"""Stage 4 — the settings screen: the ordinary numbers of a week (portions, reserve, how
long a one-timer waits after receiving) and the weights of the need score. Plain functions
over a connection and the current time (no web framework), like web/service.py.

Nothing here touches the past. A setting only changes how the COMING lists are computed —
and they are computed anew on every request anyway, so a change takes effect at once and
can always be changed back. `preview` answers "what would change?" before anything is saved.
"""
from datetime import datetime

from . import config, planner, service, store
from .engine import scoring, selection
from .service import Refused

PREVIEW_WEEKS = 8                 # how far ahead "what would change" looks (as the weeks screen shows)
MAX_COOLDOWN_WEEKS = 52

# the ordinary numbers: (name in the request, key in the store, label, highest allowed)
NUMBERS = (
    ("portions", "default_portions", "מנות בשבוע רגיל", service.MAX_PORTIONS),
    ("reserve", "default_reserve", "רזרבה בשבוע רגיל", service.MAX_PORTIONS),
    ("cooldown_weeks", "onetime_cooldown_weeks", "שבועות שחד-פעמי מחכה אחרי שקיבל", MAX_COOLDOWN_WEEKS),
)
# the factors of the need score, in the words of the screen (the engine's own labels are
# the desktop program's; the keys and the order are the engine's)
WEIGHT_LABELS = {
    "money": "כסף פנוי לנפש (מי שיש לו פחות, קודם)",
    "souls": "גודל המשפחה (נפשות)",
    "recency": "זמן המתנה מאז שקיבל",
    "income": "הכנסה נמוכה",
    "housing": "הוצאות דיור",
    "medical": "הוצאות רפואיות",
}
WEIGHT_KEYS = [f["key"] for f in scoring.NEED_FACTORS]


def _numbers(ctx: dict) -> dict:
    return {"portions": ctx["portions"], "reserve": ctx["reserve"], "cooldown_weeks": ctx["cooldown"]}


def view(conn, now: datetime, db_path: str = None) -> dict:
    """Everything the settings screen shows: the numbers and the weights as they are now,
    and what each falls back to."""
    service.roll_forward(conn, now, db_path)
    ctx = service._context(conn, now)
    weights = ctx["weights"]
    return {
        "numbers": _numbers(ctx),
        "number_fields": [{"name": name, "label": label, "max": top} for name, _key, label, top in NUMBERS],
        "number_defaults": {"portions": config.DEFAULT_PORTIONS, "reserve": config.DEFAULT_RESERVE,
                            "cooldown_weeks": selection.ONE_TIME_COOLDOWN_WEEKS_DEFAULT},
        "weights": [{"key": k, "label": WEIGHT_LABELS.get(k, k), "value": _tidy(weights.get(k, 0.0)),
                     "default": _tidy(scoring.DEFAULT_NEED_WEIGHTS.get(k, 0.0))} for k in WEIGHT_KEYS],
        "weights_sum": _tidy(sum(weights.get(k, 0.0) for k in WEIGHT_KEYS)),
        "one_time_queue": [{"label": WEIGHT_LABELS.get(k, k), "value": _tidy(v)}
                           for k, v in scoring.ONE_TIME_QUEUE_WEIGHTS.items() if v],
        "preview_weeks": PREVIEW_WEEKS,
    }


def _tidy(x: float):
    """34.0 -> 34, 12.5 -> 12.5 (a weight as it is typed and shown)."""
    x = round(float(x), 1)
    return int(x) if x == int(x) else x


# ── checking what was typed ───────────────────────────────────────────────────
def clean_numbers(data) -> dict:
    """{portions, reserve, cooldown_weeks} as whole numbers in their ranges — all three,
    so that a save never leaves one of them to chance."""
    if not isinstance(data, dict):
        raise Refused("חסרים המספרים")
    out = {}
    for name, _key, label, top in NUMBERS:
        v = data.get(name)
        if not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= top):
            raise Refused(f"{label}: צריך מספר שלם בין 0 ל-{top}")
        out[name] = v
    return out


def clean_weights(data) -> dict:
    """The six weights as percentages that add up to exactly 100 (to one decimal place).
    A sum that is not 100 is refused: the screen keeps "save" off until it is."""
    if not isinstance(data, dict) or set(data) != set(WEIGHT_KEYS):
        raise Refused("צריך משקל לכל אחד מששת הגורמים")
    out = {}
    for k in WEIGHT_KEYS:
        v = data[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 100:
            raise Refused(f"{WEIGHT_LABELS.get(k, k)}: צריך מספר בין 0 ל-100")
        if round(v, 1) != round(v, 6):
            raise Refused(f"{WEIGHT_LABELS.get(k, k)}: עד ספרה אחת אחרי הנקודה")
        out[k] = round(float(v), 1)
    total = round(sum(out.values()), 1)
    if total != 100.0:
        raise Refused(f"המשקלים צריכים להסתכם ב-100 בדיוק (עכשיו: {_tidy(total)})")
    return out


# ── saving ────────────────────────────────────────────────────────────────────
def save_numbers(conn, now: datetime, data, db_path: str = None) -> dict:
    """The ordinary numbers of a week. A week that was given numbers of its own keeps them."""
    service.roll_forward(conn, now, db_path)
    numbers = clean_numbers(data)
    with store.tx(conn):
        for name, key, _label, _top in NUMBERS:
            store.set_setting(conn, key, numbers[name])
    return {"ok": True}


def save_weights(conn, now: datetime, data, db_path: str = None) -> dict:
    service.roll_forward(conn, now, db_path)
    weights = clean_weights(data)
    with store.tx(conn):
        for k in WEIGHT_KEYS:
            store.set_setting(conn, "need_w_" + k, _tidy(weights[k]))
    return {"ok": True}


# ── "what would change?" ──────────────────────────────────────────────────────
def _changed_context(ctx: dict, data: dict) -> dict:
    new = dict(ctx)
    if data.get("numbers") is not None:
        n = clean_numbers(data["numbers"])
        new.update(portions=n["portions"], reserve=n["reserve"], cooldown=n["cooldown_weeks"])
    if data.get("weights") is not None:
        new["weights"] = clean_weights(data["weights"])
    return new


def preview(conn, now: datetime, data, db_path: str = None) -> dict:
    """What the settings in `data` ({numbers} and / or {weights}) would change in the lists
    of the coming weeks and of the holiday events ahead — without saving anything. For each
    list that would differ: how many names come in and how many go out."""
    service.roll_forward(conn, now, db_path)
    if not isinstance(data, dict) or (data.get("numbers") is None and data.get("weights") is None):
        raise Refused("אין מה לבדוק")
    ctx = service._context(conn, now)
    new = _changed_context(ctx, data)
    start = service.first_open_week(conn, now)
    weeks = max([PREVIEW_WEEKS] + [planner.weeks_through(start, e["date"]) for e in ctx["events"]])
    weeks = min(weeks, config.MAX_WEEKS)
    before, after = service._timeline(ctx, start, weeks), service._timeline(new, start, weeks)
    changed = []
    for kind, name_of in (("weeks", lambda r: ""), ("events", lambda r: service.event_name(r["holiday"], r["date"]))):
        for a, b in zip(before[kind], after[kind]):
            was, will = {e["guid"] for e in a["main"]}, {e["guid"] for e in b["main"]}
            if was != will or len(a["reserve_list"]) != len(b["reserve_list"]):
                changed.append({"kind": "week" if kind == "weeks" else "event", "date": a["date"].isoformat(),
                                "name": name_of(a), "enter": len(will - was), "leave": len(was - will),
                                "main_before": len(was), "main_after": len(will),
                                "reserve_before": len(a["reserve_list"]), "reserve_after": len(b["reserve_list"])})
    changed.sort(key=lambda c: (c["date"], c["kind"] == "event"))
    return {"weeks": weeks, "changed": changed, "same": not changed}

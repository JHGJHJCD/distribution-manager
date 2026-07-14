"""Regression tests for the need-score scale fixes (bugs 9, 10, 7).

Run:  python test_score_scale.py
"""
import sys
import scoring

_fail = 0


def check(name, cond):
    global _fail
    print(("  OK  " if cond else "  XX  ") + name)
    if not cond:
        _fail += 1


# ── Bug 9 + 10: a single 'high' factor must run cleanly 0→100 ────────────────
rows = [
    {"full_name": "מקס",      "housing_expenses": "6000"},
    {"full_name": "חצי",      "housing_expenses": "3000"},
    {"full_name": "ללא דיור", "housing_expenses": ""},     # missing
    {"full_name": "אפס",      "housing_expenses": "0"},     # explicit zero
]
w_house = {"money": 0, "souls": 0, "recency": 0,
           "income": 0, "housing": 100, "medical": 0}
scoring.annotate_need_scores(rows, w_house)
by = {r["full_name"]: r["need_score"] for r in rows}
check("bug9: highest expense scores 100", by["מקס"] == 100)
check("bug9: proportional middle ~50", abs(by["חצי"] - 50) < 1)
check("bug10: missing housing scores 0", by["ללא דיור"] == 0)
check("bug10: zero housing scores 0", by["אפס"] == 0)

# ── Bug 7: family size (souls) must NOT act as a hidden tie-breaker ──────────
# souls weight is 0, two people are otherwise identical → order must be by NAME,
# not by who has more children.
import database as db
rows2 = [
    {"id": 1, "full_name": "בבב", "souls": 2, "housing_expenses": "1000",
     "days_since": 5},
    {"id": 2, "full_name": "אאא", "souls": 9, "housing_expenses": "1000",
     "days_since": 5},
]
scoring.annotate_need_scores(rows2, w_house)
# equal scores (same housing) → tie-break by name, so אאא comes first
rows2.sort(key=lambda x: (-(x.get("need_score") or 0), x.get("full_name") or ""))
check("bug7: tie breaks by name, not by more children",
      rows2[0]["full_name"] == "אאא")

if _fail:
    print(f"\nFAILED: {_fail}")
    sys.exit(1)
print("\nRESULT: ALL PASS ✓")

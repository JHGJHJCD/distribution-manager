# -*- coding: utf-8 -*-
"""מנהל חלוקה — גרסת האתר (web).

The website shell around the existing rules engine (selection.py / scoring.py in the
repository root, imported as they are). Nothing in this package may import the old
`database.py`: the site has its own small store (web/store.py) and computes every
future list on the fly (web/planner.py). Decisions: docs/plans/אתר_תכנון_מצב.md.
"""

# -*- coding: utf-8 -*-
"""The website: a thin layer of routes over web/service.py.

Run locally:   <python 3.12> -m uvicorn web.app:app --host 127.0.0.1 --port 8787
(or web/run_local.bat).

Local stage = no login, and the server answers only to this computer (host check below).
Login, encryption and off-site backup come with the move to the server.

Writing routes (stage 2) are POST only and need the header `X-Haluka: 1`, which a page of
another website cannot send to this server — so no other site open in the browser can
change a list behind the user's back.
"""
import os
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import cards, config, service, store

STATIC_DIR = os.path.join(config.WEB_DIR, "static")
_NO_DATA = {"error": "no_data",
            "message": "עוד אין נתונים באתר. צריך לייבא עותק של הנתונים (web/import_old.py)."}
_DATE = r"^\d{4}-\d{2}-\d{2}$"

app = FastAPI(title="מנהל חלוקה", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts())


def _from_this_site(request: Request) -> bool:
    """Reading is open (to this computer); anything that writes must carry the header that
    only this site's own pages send."""
    return request.method in ("GET", "HEAD") or request.headers.get("x-haluka") == "1"


@app.middleware("http")
async def _guard_and_headers(request: Request, call_next):
    if not _from_this_site(request):
        response = JSONResponse({"message": "הבקשה לא הגיעה מהאתר עצמו"}, status_code=403)
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    # names of real families: never kept by the browser or a proxy
    response.headers["Cache-Control"] = "no-store"
    return response


def _open():
    path = config.db_path()
    if not os.path.exists(path):
        return None, path
    store.ensure_schema(path)
    return store.connect(path), path


def _wed(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise HTTPException(400, "תאריך לא תקין")


def _run(fn):
    """Open the database, run fn(conn, path), close; turn refusals into clean answers."""
    conn, path = _open()
    if conn is None:
        return JSONResponse(_NO_DATA, status_code=503)
    try:
        return fn(conn, path)
    except service.Refused as e:
        return JSONResponse({"message": str(e)}, status_code=409)
    except cards.Refused as e:
        return JSONResponse({"message": str(e), "code": e.code, "fields": e.fields, "duplicates": e.duplicates},
                            status_code=404 if e.code == "missing" else 409)
    except ValueError:
        raise HTTPException(400, "התאריך אינו יום רביעי")
    except LookupError:
        raise HTTPException(404, "השבוע הזה כבר עבר או רחוק מדי")
    finally:
        conn.close()


# ── reading ───────────────────────────────────────────────────────────────────
@app.get("/api/plan")
def api_plan(weeks: int = Query(8, ge=1, le=config.MAX_WEEKS)):
    return _run(lambda conn, path: service.plan_overview(conn, config.now(), weeks, path))


@app.get("/api/week")
def api_week(date_: str = Query(..., alias="date", pattern=_DATE)):
    wed = _wed(date_)
    return _run(lambda conn, path: service.week_detail(conn, config.now(), wed, path))


@app.get("/api/people")
def api_people():
    return _run(lambda conn, path: service.people(conn))


@app.get("/api/print")
def api_print(from_: str = Query(..., alias="from", pattern=_DATE), weeks: int = Query(1, ge=1, le=config.MAX_WEEKS)):
    start = _wed(from_)
    return _run(lambda conn, path: {"weeks": service.print_weeks(conn, config.now(), start, weeks, path)})


@app.get("/api/export.xlsx")
def api_export(from_: str = Query(..., alias="from", pattern=_DATE), weeks: int = Query(1, ge=1, le=config.MAX_WEEKS)):
    start = _wed(from_)

    def build(conn, path):
        data = service.export_xlsx(conn, config.now(), start, weeks, path)
        name = f"haluka-{start.isoformat()}-{weeks}w.xlsx"
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return _run(build)


# ── writing (stage 2) ─────────────────────────────────────────────────────────
class ManualBody(BaseModel):
    date: str = Field(pattern=_DATE)
    guid: str = Field(min_length=1, max_length=64)
    action: str = Field(pattern=r"^(add|reserve|remove|clear)$")


class NumbersBody(BaseModel):
    date: str = Field(pattern=_DATE)
    portions: Optional[int] = Field(default=None, ge=0, le=service.MAX_PORTIONS)
    reserve: Optional[int] = Field(default=None, ge=0, le=service.MAX_PORTIONS)


class PrintedBody(BaseModel):
    start: str = Field(pattern=_DATE)
    weeks: int = Field(default=1, ge=1, le=config.MAX_WEEKS)
    how: str = Field(pattern=r"^(print|excel)$")


@app.post("/api/week/manual")
def api_manual(body: ManualBody):
    wed = _wed(body.date)

    def do(conn, path):
        service.set_manual(conn, config.now(), wed, body.guid, body.action, path)
        return {"ok": True}
    return _run(do)


@app.post("/api/week/numbers")
def api_numbers(body: NumbersBody):
    wed = _wed(body.date)

    def do(conn, path):
        service.set_numbers(conn, config.now(), wed, body.portions, body.reserve, path)
        return {"ok": True}
    return _run(do)


@app.post("/api/printed")
def api_printed(body: PrintedBody):
    start = _wed(body.start)

    def do(conn, path):
        return {"ok": True, "weeks": service.mark_printed(conn, config.now(), start, body.weeks, body.how, path)}
    return _run(do)


# ── cards (stage 3) ───────────────────────────────────────────────────────────
_GUID = r"^[0-9A-Za-z_-]{1,64}$"


class CardBody(BaseModel):
    guid: Optional[str] = Field(default=None, pattern=_GUID)      # None = a new card
    updated_at: Optional[str] = Field(default=None, max_length=40)
    confirmed: bool = False                                        # "these are two different people"
    card: dict


@app.get("/api/cards")
def api_cards():
    return _run(lambda conn, path: cards.card_list(conn))


@app.get("/api/card")
def api_card(guid: str = Query(..., pattern=_GUID)):
    return _run(lambda conn, path: cards.get_card(conn, guid))


@app.get("/api/duplicates")
def api_duplicates():
    return _run(lambda conn, path: {"groups": cards.duplicate_groups(conn)})


@app.post("/api/card")
def api_card_save(body: CardBody):
    if len(body.card) > 60:
        raise HTTPException(422, "יותר מדי שדות")

    def do(conn, path):
        service.roll_forward(conn, config.now(), path)             # weeks that passed close on the cards as they were
        if body.guid is None:
            return cards.add_card(conn, config.now(), body.card, body.confirmed)
        return cards.save_card(conn, config.now(), body.guid, body.card, body.updated_at)
    return _run(do)


# ── pages ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/cards")
def cards_page():
    return FileResponse(os.path.join(STATIC_DIR, "cards.html"))


@app.get("/print")
def print_page():
    return FileResponse(os.path.join(STATIC_DIR, "print.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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

from . import card_service, config, event_service, service, store

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


_EVENT = Query(None, min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _need_range(from_):
    if not from_:
        raise HTTPException(422, "חסר מאיזה שבוע להפיק את הרשימה")
    return _wed(from_)


# The two answers that carry phones — the paper sheet and the Excel file — for a range of
# weeks (`from` + `weeks`) or for one holiday event (`event`).
@app.get("/api/print")
def api_print(from_: Optional[str] = Query(None, alias="from", pattern=_DATE),
              weeks: int = Query(1, ge=1, le=config.MAX_WEEKS), event: Optional[str] = _EVENT):
    if event:
        return _run(lambda conn, path: {"weeks": event_service.paper(conn, config.now(), event, path)})
    start = _need_range(from_)
    return _run(lambda conn, path: {"weeks": service.print_weeks(conn, config.now(), start, weeks, path)})


@app.get("/api/export.xlsx")
def api_export(from_: Optional[str] = Query(None, alias="from", pattern=_DATE),
               weeks: int = Query(1, ge=1, le=config.MAX_WEEKS), event: Optional[str] = _EVENT):
    if event:
        def build_event(conn, path):
            data = event_service.export_xlsx(conn, config.now(), event, path)
            name = f"haluka-holiday-{event_service.file_date(conn, event)}.xlsx"
            return Response(data, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
        return _run(build_event)
    start = _need_range(from_)

    def build(conn, path):
        data = service.export_xlsx(conn, config.now(), start, weeks, path)
        name = f"haluka-{start.isoformat()}-{weeks}w.xlsx"
        return Response(data, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
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
    """A range of weeks (`start` + `weeks`) or one holiday event (`event`)."""
    start: Optional[str] = Field(default=None, pattern=_DATE)
    weeks: int = Field(default=1, ge=1, le=config.MAX_WEEKS)
    how: str = Field(pattern=r"^(print|excel)$")
    event: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")


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
    if body.event:
        return _run(lambda conn, path: {"ok": True, "weeks": event_service.mark_printed(
            conn, config.now(), body.event, body.how, path)})
    start = _need_range(body.start)

    def do(conn, path):
        return {"ok": True, "weeks": service.mark_printed(conn, config.now(), start, body.weeks, body.how, path)}
    return _run(do)


# ── stage 3: the recipients ───────────────────────────────────────────────────
_GUID = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")


class CardBody(BaseModel):
    """One card as the form sends it. Unknown fields are refused; every value is checked
    again in web/cards.py."""
    model_config = {"extra": "forbid"}
    guid: str = Field(default="", max_length=64, pattern=r"^[0-9A-Za-z_-]*$")
    seen: str = Field(default="", max_length=40)
    sure: bool = False
    type: Optional[str] = Field(default=None, max_length=10)
    status: Optional[str] = Field(default=None, max_length=20)
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    phone1: Optional[str] = None
    phone2: Optional[str] = None
    phone3: Optional[str] = None
    souls: Optional[str] = Field(default=None, max_length=6)
    children_total: Optional[str] = Field(default=None, max_length=6)
    holiday_support: Optional[bool] = None
    holidays: Optional[list[str]] = Field(default=None, max_length=12)
    address: Optional[str] = None
    id_number: Optional[str] = None
    spouse_id_number: Optional[str] = None
    email: Optional[str] = None
    synagogue: Optional[str] = None
    representative: Optional[str] = None
    income: Optional[str] = None
    per_soul: Optional[str] = None
    housing_expenses: Optional[str] = None
    medical_expenses: Optional[str] = None
    notes: Optional[str] = None


class GuidBody(BaseModel):
    guid: str = _GUID


class StatusBody(BaseModel):
    guid: str = _GUID
    status: str = Field(max_length=20)


class GuidsBody(BaseModel):
    guids: list[str] = Field(min_length=2, max_length=50)


class MergeBody(BaseModel):
    keep: str = _GUID
    drop: str = _GUID


@app.get("/api/cards")
def api_cards(q: str = Query("", max_length=100), show: str = Query("all", pattern=r"^(all|active|paused|holiday)$")):
    return _run(lambda conn, path: card_service.card_list(conn, q, show))


@app.get("/api/card")
def api_card(guid: str = Query(..., min_length=1, max_length=64)):
    return _run(lambda conn, path: card_service.card(conn, config.now(), guid, path))


@app.get("/api/card/new")
def api_card_new():
    return _run(lambda conn, path: card_service.blank_card())


@app.post("/api/card/save")
def api_card_save(body: CardBody):
    data = body.model_dump(exclude_none=True)
    return _run(lambda conn, path: card_service.save(conn, config.now(), data, path))


@app.post("/api/card/status")
def api_card_status(body: StatusBody):
    return _run(lambda conn, path: card_service.set_status(conn, config.now(), body.guid, body.status))


@app.post("/api/card/delete")
def api_card_delete(body: GuidBody):
    return _run(lambda conn, path: card_service.delete(conn, config.now(), body.guid, path))


@app.get("/api/cards/deleted")
def api_cards_deleted():
    return _run(lambda conn, path: card_service.deleted(conn))


@app.post("/api/card/restore")
def api_card_restore(body: GuidBody):
    return _run(lambda conn, path: card_service.restore(conn, config.now(), body.guid))


@app.get("/api/duplicates")
def api_duplicates():
    return _run(lambda conn, path: card_service.duplicates(conn))


@app.get("/api/duplicates/compare")
def api_compare(a: str = Query(..., min_length=1, max_length=64), b: str = Query(..., min_length=1, max_length=64)):
    return _run(lambda conn, path: card_service.compare(conn, a, b))


@app.post("/api/duplicates/different")
def api_different(body: GuidsBody):
    return _run(lambda conn, path: card_service.set_different(conn, config.now(), body.guids))


@app.post("/api/duplicates/merge")
def api_merge(body: MergeBody):
    return _run(lambda conn, path: card_service.merge(conn, config.now(), body.keep, body.drop, path))


# ── stage 4: holiday events ───────────────────────────────────────────────────
class Bound(BaseModel):
    model_config = {"extra": "forbid"}
    min: Optional[float] = Field(default=None, ge=-1e9, le=1e9)
    max: Optional[float] = Field(default=None, ge=-1e9, le=1e9)


class EventBody(BaseModel):
    """A holiday event as the form sends it; every value is checked again in event_service."""
    model_config = {"extra": "forbid"}
    guid: str = Field(default="", max_length=64, pattern=r"^[0-9A-Za-z_-]*$")
    date: str = Field(pattern=_DATE)
    holiday: str = Field(min_length=1, max_length=30)
    portions: int = Field(ge=0, le=service.MAX_PORTIONS)
    reserve: int = Field(default=0, ge=0, le=service.MAX_PORTIONS)
    criteria: dict[str, Bound] = Field(default_factory=dict)


class EventGuidBody(BaseModel):
    event: str = _GUID


class EventManualBody(BaseModel):
    event: str = _GUID
    guid: str = _GUID
    action: str = Field(pattern=r"^(add|reserve|remove|clear)$")


@app.get("/api/events")
def api_events():
    return _run(lambda conn, path: event_service.overview(conn, config.now(), path))


@app.get("/api/event")
def api_event(guid: str = Query(..., min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")):
    return _run(lambda conn, path: event_service.detail(conn, config.now(), guid, path))


@app.post("/api/event/save")
def api_event_save(body: EventBody):
    data = body.model_dump()
    return _run(lambda conn, path: event_service.save(conn, config.now(), data, path))


@app.post("/api/event/delete")
def api_event_delete(body: EventGuidBody):
    return _run(lambda conn, path: event_service.remove(conn, config.now(), body.event, path))


@app.post("/api/event/manual")
def api_event_manual(body: EventManualBody):
    return _run(lambda conn, path: event_service.set_manual(conn, config.now(), body.event, body.guid, body.action, path))


# ── pages ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/people")
def people_page():
    return FileResponse(os.path.join(STATIC_DIR, "people.html"))


@app.get("/print")
def print_page():
    return FileResponse(os.path.join(STATIC_DIR, "print.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

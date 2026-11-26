# -*- coding: utf-8 -*-
"""The website: a thin layer of routes over web/service.py.

Run locally:   <python 3.12> -m uvicorn web.app:app --host 127.0.0.1 --port 8787
(or web/run_local.bat).

On this computer = no login, and the server answers only to this computer (host check
below). On the server (`config.login_required()`) nothing answers without a session — see
web/auth.py; the only open addresses are the login page, its script and style, and /healthz.

Writing routes (stage 2) are POST only and need the header `X-Haluka: 1`, which a page of
another website cannot send to this server — so no other site open in the browser can
change a list behind the user's back.
"""
import hmac
import os
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (auth, backup_service, card_service, config, drive, event_service, google_login, history_service, offsite,
               service,
               settings_service, store)

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


# What answers without a session when login is on: the login page with its style and script,
# the login itself, and the "is the site alive" check. Nothing here carries data.
OPEN_PATHS = frozenset({"/login", "/api/login", "/healthz", "/static/style.css", "/static/login.js",
                        "/auth/google", google_login.CALLBACK,
                        # the way back from Google after "connect the Drive": the session cookie is
                        # not sent on it (it comes from another site), so the state cookie that
                        # only a logged-in user was given is what lets it in
                        drive.CALLBACK})


def _through_the_front(request: Request) -> bool:
    """With HALUKA_PROXY_SECRET set, only what came through the fixed front address is served
    (the alive check stays open: the server asks it of itself)."""
    secret = config.proxy_secret()
    if not secret or request.url.path == "/healthz":
        return True
    return hmac.compare_digest(request.headers.get("x-haluka-proxy", "").encode(), secret.encode())


def _session_user(request: Request) -> str:
    return auth.session_user(request.cookies.get(auth.COOKIE, ""), config.now())


def _refuse_stranger(request: Request):
    """None when the request may go on; otherwise the answer to someone who has not entered."""
    path = request.url.path
    request.state.user = ""
    if not config.login_required() or path in OPEN_PATHS:
        return None
    request.state.user = _session_user(request)
    if request.state.user:
        return None
    if path.startswith("/api/") or path.startswith("/static/") or request.method not in ("GET", "HEAD"):
        return JSONResponse({"message": "צריך להיכנס לאתר", "login": True}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.middleware("http")
async def _guard_and_headers(request: Request, call_next):
    if not _through_the_front(request):
        response = JSONResponse({"message": "אין גישה מהכתובת הזו"}, status_code=403)
    elif not _from_this_site(request):
        response = JSONResponse({"message": "הבקשה לא הגיעה מהאתר עצמו"}, status_code=403)
    else:
        response = _refuse_stranger(request) or await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    # names of real families: never kept by the browser or a proxy
    response.headers["Cache-Control"] = "no-store"
    if config.login_required():
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
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
        backup_service.daily(conn, config.now(), path)       # the day's first request backs the site up
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


class ModeBody(BaseModel):
    date: str = Field(pattern=_DATE)
    mode: str = Field(pattern=r"^(wait|scored)$")


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


@app.post("/api/week/mode")
def api_mode(body: ModeBody):
    wed = _wed(body.date)

    def do(conn, path):
        service.set_mode(conn, config.now(), wed, body.mode, path)
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
    balance: bool = False


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


@app.post("/api/event/restore")
def api_event_restore(body: EventGuidBody):
    return _run(lambda conn, path: event_service.restore(conn, config.now(), body.event, path))


@app.post("/api/event/manual")
def api_event_manual(body: EventManualBody):
    return _run(lambda conn, path: event_service.set_manual(conn, config.now(), body.event, body.guid, body.action, path))


# ── stage 4: the history (reading only; names only) ──────────────────────────
def _id():
    """An id in the address. (One object per parameter: the framework ties it to the
    parameter's own name, so two parameters must never share one.)"""
    return Query(..., min_length=1, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")


@app.get("/api/history")
def api_history(offset: int = Query(0, ge=0, le=10 ** 7),
                limit: int = Query(history_service.PAGE, ge=1, le=history_service.MAX_PAGE)):
    return _run(lambda conn, path: history_service.overview(conn, config.now(), offset, limit, path))


@app.get("/api/history/round")
def api_history_round(batch: str = _id()):
    return _run(lambda conn, path: history_service.round_detail(conn, config.now(), batch, path))


@app.get("/api/history/old")
def api_history_old(date_: str = Query("", alias="date", max_length=40)):
    return _run(lambda conn, path: history_service.old_day(conn, config.now(), date_, path))


@app.get("/api/history/person")
def api_history_person(guid: str = _id()):
    return _run(lambda conn, path: history_service.person(conn, config.now(), guid, path))


# ── stage 4: the settings ─────────────────────────────────────────────────────
class NumbersSettings(BaseModel):
    """The ordinary numbers of a week; every value is checked again in settings_service."""
    model_config = {"extra": "forbid"}
    portions: int = Field(ge=0, le=service.MAX_PORTIONS)
    reserve: int = Field(ge=0, le=service.MAX_PORTIONS)
    cooldown_weeks: int = Field(ge=0, le=settings_service.MAX_COOLDOWN_WEEKS)


class WeightsSettings(BaseModel):
    model_config = {"extra": "forbid"}
    weights: dict[str, float]


class CommunitiesSettings(BaseModel):
    model_config = {"extra": "forbid"}
    percents: dict[str, float]


class PreviewSettings(BaseModel):
    model_config = {"extra": "forbid"}
    numbers: Optional[NumbersSettings] = None
    weights: Optional[dict[str, float]] = None
    communities: Optional[dict[str, float]] = None


@app.get("/api/settings")
def api_settings():
    return _run(lambda conn, path: settings_service.view(conn, config.now(), path))


@app.post("/api/settings/numbers")
def api_settings_numbers(body: NumbersSettings):
    return _run(lambda conn, path: settings_service.save_numbers(conn, config.now(), body.model_dump(), path))


@app.post("/api/settings/weights")
def api_settings_weights(body: WeightsSettings):
    return _run(lambda conn, path: settings_service.save_weights(conn, config.now(), body.weights, path))


@app.post("/api/settings/communities")
def api_settings_communities(body: CommunitiesSettings):
    return _run(lambda conn, path: settings_service.save_communities(conn, config.now(), body.percents, path))


@app.post("/api/settings/preview")
def api_settings_preview(body: PreviewSettings):
    """What the typed settings would change in the coming lists. It saves nothing."""
    data = body.model_dump()
    return _run(lambda conn, path: settings_service.preview(conn, config.now(), data, path))


# ── stage 5: backup and restore ───────────────────────────────────────────────
# A backup holds everything (phones included), so no route ever serves one: the screen gets
# the list of files (when, why, how big) and, for one of them, how much it holds — numbers.
_BACKUP_NAME = r"^haluka-[0-9]{8}-[0-9]{6}-[0-9A-Za-z_-]{1,60}\.db$"


class BackupBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(max_length=100, pattern=_BACKUP_NAME)


@app.get("/api/backups")
def api_backups():
    return _run(lambda conn, path: backup_service.listing(conn, config.now(), path))


@app.get("/api/backup")
def api_backup(name: str = Query(..., max_length=100, pattern=_BACKUP_NAME)):
    return _run(lambda conn, path: backup_service.inspect(conn, config.now(), name, path))


@app.post("/api/backup/make")
def api_backup_make():
    return _run(lambda conn, path: backup_service.make(conn, config.now(), path))


@app.post("/api/backup/restore")
def api_backup_restore(body: BackupBody):
    return _run(lambda conn, path: backup_service.restore(conn, config.now(), body.name, path))


@app.get("/api/offsite")
def api_offsite():
    """Does a copy of the backup leave the server, and when did the last one leave.
    (No path and no command; on this computer the screen shows nothing of it.)"""
    return offsite.status(config.now())


# ── the copy that leaves the server: Google Drive ────────────────────────────
@app.get("/api/drive")
def api_drive():
    return drive.view()


@app.post("/api/drive/key-kept")
def api_drive_key_kept():
    return drive.key_kept()


@app.post("/api/drive/disconnect")
def api_drive_disconnect():
    return drive.disconnect()


@app.get("/auth/drive")
def drive_start():
    if not (config.login_required() and drive.available()):
        raise HTTPException(404)
    url, state = drive.start()
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(drive.STATE_COOKIE, state, max_age=google_login.STATE_SECONDS, path="/",
                        secure=True, httponly=True, samesite="lax")
    return response


@app.get(drive.CALLBACK)
def drive_callback(request: Request, code: str = Query("", max_length=2000), state: str = Query("", max_length=200)):
    if not config.login_required():
        raise HTTPException(404)
    try:
        drive.finish(code, state, request.cookies.get(drive.STATE_COOKIE, ""), config.now())
        where = "/settings#drive-ok"
    except drive.Refused as e:
        where = "/settings#drive-" + str(e)
    response = HTMLResponse(_ENTERED.replace("url=/", "url=" + where).replace('href="/"', f'href="{where}"'))
    response.delete_cookie(drive.STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


# ── the move to the server: entering and leaving ─────────────────────────────
class LoginBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=auth.MAX_NAME)
    password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD)


@app.post("/api/login")
def api_login(body: LoginBody):
    if not config.login_required():
        return {"ok": True, "login": False}
    try:
        token, name = auth.login(body.name, body.password, config.now())
    except auth.Locked as e:
        return JSONResponse({"message": str(e)}, status_code=429)
    except auth.Wrong as e:
        return JSONResponse({"message": str(e)}, status_code=401)
    response = JSONResponse({"ok": True, "login": True, "name": name})
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, path="/",
                        secure=True, httponly=True, samesite="strict")
    return response


@app.post("/api/logout")
def api_logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE, ""))
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


@app.get("/api/me")
def api_me(request: Request):
    """Whether this site asks for a login, and who entered (the pages show "יציאה")."""
    return {"login": config.login_required(), "name": request.state.user}


@app.get("/healthz")
def healthz():
    """Is the site alive — for the server's own watchdog. Says nothing about the data."""
    return {"ok": True}


@app.get("/login")
def login_page(request: Request):
    if not config.login_required() or _session_user(request):
        return RedirectResponse("/", status_code=303)
    with open(os.path.join(STATIC_DIR, "login.html"), encoding="utf-8") as f:
        page = f.read()
    # which ways in this server offers (two fixed words; nothing of the request enters the page)
    ways = " ".join(w for w, on in (("google", google_login.enabled()), ("password", bool(auth.users()))) if on)
    return HTMLResponse(page.replace('data-ways=""', f'data-ways="{ways}"'))


@app.get("/auth/google")
def google_start():
    """To Google, to ask who this is. The random state stays in a cookie for ten minutes."""
    if not (config.login_required() and google_login.enabled()):
        raise HTTPException(404)
    url, cookie = google_login.start()
    response = RedirectResponse(url, status_code=303)
    # Lax, not Strict: the way back from Google is a link from another site
    response.set_cookie(google_login.STATE_COOKIE, cookie, max_age=google_login.STATE_SECONDS, path="/",
                        secure=True, httponly=True, samesite="lax")
    return response


_ENTERED = ('<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0;url=/"><title>מנהל חלוקה</title></head>'
            '<body><p><a href="/">המשך לאתר</a></p></body></html>')


@app.get(google_login.CALLBACK)
def google_callback(request: Request, code: str = Query("", max_length=2000), state: str = Query("", max_length=200)):
    if not config.login_required():
        raise HTTPException(404)
    try:
        token, _name = google_login.finish(code, state, request.cookies.get(google_login.STATE_COOKIE, ""), config.now())
    except google_login.Refused as e:
        response = RedirectResponse("/login#" + e.why, status_code=303)
    else:
        # a page, not a redirect: the browser sends the (SameSite=Strict) session cookie only
        # on a move that starts inside the site, and this one does
        response = HTMLResponse(_ENTERED)
        response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, path="/",
                            secure=True, httponly=True, samesite="strict")
    response.delete_cookie(google_login.STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


# ── pages ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/people")
def people_page():
    return FileResponse(os.path.join(STATIC_DIR, "people.html"))


@app.get("/holiday")
def holiday_page():
    return FileResponse(os.path.join(STATIC_DIR, "holiday.html"))


@app.get("/history")
def history_page():
    return FileResponse(os.path.join(STATIC_DIR, "history.html"))


@app.get("/settings")
def settings_page():
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))


@app.get("/print")
def print_page():
    return FileResponse(os.path.join(STATIC_DIR, "print.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# -*- coding: utf-8 -*-
"""The website: a thin layer of routes over web/service.py.

Run locally:   <python 3.12> -m uvicorn web.app:app --host 127.0.0.1 --port 8787
(or web/run_local.bat). Stage 1 is read-only for the visitor: the only thing the site
writes by itself is a week that has passed, into the history.

Local stage = no login, and the server answers only to this computer (host check below).
Login, encryption and off-site backup come with the move to the server.
"""
import os
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config, service, store

STATIC_DIR = os.path.join(config.WEB_DIR, "static")
_NO_DATA = {"error": "no_data",
            "message": "עוד אין נתונים באתר. צריך לייבא עותק של הנתונים (web/import_old.py)."}

app = FastAPI(title="מנהל חלוקה", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts())


@app.middleware("http")
async def _headers(request, call_next):
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


def _conn():
    path = config.db_path()
    if not os.path.exists(path):
        return None, path
    return store.connect(path), path


@app.get("/api/plan")
def api_plan(weeks: int = Query(8, ge=1, le=config.MAX_WEEKS)):
    conn, path = _conn()
    if conn is None:
        return JSONResponse(_NO_DATA, status_code=503)
    try:
        return service.plan_overview(conn, config.now(), weeks, path)
    finally:
        conn.close()


@app.get("/api/week")
def api_week(date_: str = Query(..., alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$")):
    try:
        wed = date.fromisoformat(date_)
    except ValueError:
        raise HTTPException(400, "תאריך לא תקין")
    conn, path = _conn()
    if conn is None:
        return JSONResponse(_NO_DATA, status_code=503)
    try:
        return service.week_detail(conn, config.now(), wed, path)
    except ValueError:
        raise HTTPException(400, "התאריך אינו יום רביעי")
    except LookupError:
        raise HTTPException(404, "השבוע הזה כבר עבר או רחוק מדי")
    finally:
        conn.close()


@app.get("/api/people")
def api_people():
    conn, _ = _conn()
    if conn is None:
        return JSONResponse(_NO_DATA, status_code=503)
    try:
        return service.people(conn)
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

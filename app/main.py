import os
import json
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db as database
from app import service

DB_PATH = os.environ.get("DB_PATH", "data/schedella.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_path = DB_PATH
    database.init_db(DB_PATH)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = database.get_stats(DB_PATH)
    schedelle = database.get_all_schedelle(DB_PATH, limit=5)
    roi_data = database.get_roi_over_time(DB_PATH)
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats,
        "schedelle": schedelle,
        "roi_data": roi_data,
    })


@app.get("/nuova", response_class=HTMLResponse)
async def nuova_form(request: Request):
    return templates.TemplateResponse(request, "nuova.html", {})


@app.get("/storia", response_class=HTMLResponse)
async def storia(request: Request):
    schedelle = database.get_all_schedelle(DB_PATH, limit=100)
    for s in schedelle:
        s["picks"] = database.get_picks_for_schedella(DB_PATH, s["id"])
    return templates.TemplateResponse(request, "storia.html", {
        "schedelle": schedelle,
    })


@app.get("/analisi", response_class=HTMLResponse)
async def analisi(request: Request):
    roi_data = database.get_roi_over_time(DB_PATH)
    winrate_data = database.get_winrate_by_pronostico(DB_PATH)
    stats = database.get_stats(DB_PATH)
    return templates.TemplateResponse(request, "analisi.html", {
        "roi_data": roi_data,
        "winrate_data": winrate_data,
        "stats": stats,
    })

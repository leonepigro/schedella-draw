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


@app.post("/nuova")
async def nuova_submit(
    request: Request,
    excel_file: UploadFile = File(...),
    players: int = Form(1),
    per_player: int = Form(3),
    allow_4th: Optional[str] = Form(None),
    selection_mode: str = Form("none"),
    cos_column: Optional[str] = Form(None),
    filter_day: Optional[str] = Form(None),
    filter_time: Optional[str] = Form(None),
    use_odds: Optional[str] = Form(None),
    theodds_key: Optional[str] = Form(None),
    parlay_target: Optional[float] = Form(None),
    parlay_max: Optional[float] = Form(None),
    only_mandatory: Optional[str] = Form(None),
    seed: Optional[int] = Form(None),
    debug_odds: Optional[str] = Form(None),
):
    excel_bytes = await excel_file.read()
    params = {
        "players": players,
        "per_player": per_player,
        "allow_4th": allow_4th is not None,
        "selection_mode": selection_mode,
        "cos_column": cos_column if selection_mode == "cos" else None,
        "filter_day": filter_day if selection_mode == "datetime" else None,
        "filter_time": filter_time if selection_mode == "datetime" else None,
        "use_odds": use_odds is not None,
        "theodds_key": theodds_key or None,
        "parlay_target": parlay_target,
        "parlay_max": parlay_max,
        "only_mandatory": only_mandatory is not None,
        "seed": seed,
        "debug_odds": debug_odds is not None,
    }

    try:
        session_data = service.prepare_session(excel_bytes, excel_file.filename, params)
    except Exception as e:
        return templates.TemplateResponse(request, "nuova.html", {
            "error": str(e)
        }, status_code=400)

    session_id = database.insert_session(DB_PATH, excel_file.filename, params)
    for player in session_data["players"]:
        sched_id = database.insert_schedella(DB_PATH, session_id, player["player_num"])
        for pos, match in enumerate(player["matches"]):
            ro = match["raw_odds"]
            valid_odds = [o for o in ro if isinstance(o, float) and not (o != o) and o > 0]
            avg_odds = sum(valid_odds) / len(valid_odds) if valid_odds else None
            database.insert_pick(
                DB_PATH, sched_id,
                match["match_name"], match["match_date"],
                None,
                avg_odds,
                None,
                match["best_ev"],
                pos,
            )

    database.update_session_matches(DB_PATH, session_id, session_data)

    return RedirectResponse(f"/sorteggio/{session_id}", status_code=303)


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

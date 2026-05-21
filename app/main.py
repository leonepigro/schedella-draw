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
async def nuova_upload(request: Request, excel_file: UploadFile = File(...)):
    excel_bytes = await excel_file.read()
    session_id = database.create_upload_session(DB_PATH, excel_file.filename, excel_bytes)
    return RedirectResponse(f"/configura/{session_id}", status_code=303)


@app.get("/configura/{session_id}", response_class=HTMLResponse)
async def configura_form(request: Request, session_id: int):
    data = database.get_session_bytes(DB_PATH, session_id)
    if not data or not data.get("excel_bytes"):
        return RedirectResponse("/nuova")
    preview = service.get_excel_preview(data["excel_bytes"])
    return templates.TemplateResponse(request, "configura.html", {
        "session_id": session_id,
        "excel_filename": data["excel_filename"],
        "columns": preview["dropdown_columns"],
        "preview_cols": preview["all_columns"],
        "preview_rows": preview["rows"],
    })


@app.post("/configura/{session_id}")
async def configura_submit(
    request: Request,
    session_id: int,
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
    participant_column: Optional[str] = Form(None),
):
    data = database.get_session_bytes(DB_PATH, session_id)
    excel_bytes = data["excel_bytes"]
    excel_filename = data["excel_filename"]
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
        "participant_column": participant_column or None,
    }

    try:
        session_data = service.prepare_session(excel_bytes, excel_filename, params)
    except Exception as e:
        preview = service.get_excel_preview(excel_bytes)
        return templates.TemplateResponse(request, "configura.html", {
            "session_id": session_id,
            "excel_filename": excel_filename,
            "columns": preview["dropdown_columns"],
            "preview_cols": preview["all_columns"],
            "preview_rows": preview["rows"],
            "error": str(e),
        }, status_code=400)

    database.finalize_session(DB_PATH, session_id, params)
    for player in session_data["players"]:
        sched_id = database.insert_schedella(
            DB_PATH, session_id, player["player_num"],
            participant_name=player.get("participant_name"),
        )
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


@app.get("/sorteggio", response_class=HTMLResponse)
async def sorteggio_latest(request: Request):
    session_id = database.get_latest_session_id(DB_PATH)
    if not session_id:
        return RedirectResponse("/nuova")
    return RedirectResponse(f"/sorteggio/{session_id}")


@app.get("/sorteggio/{session_id}", response_class=HTMLResponse)
async def sorteggio(request: Request, session_id: int):
    session = database.get_session(DB_PATH, session_id)
    if not session:
        return RedirectResponse("/nuova")
    match_data = session["params"].get("_match_data", {})
    players = match_data.get("players", [])
    schedelle_ids = database.get_schedelle_for_session(DB_PATH, session_id)
    players_with_picks = []
    for i, player in enumerate(players):
        sched_id = schedelle_ids[i] if i < len(schedelle_ids) else None
        picks = database.get_picks_for_schedella(DB_PATH, sched_id) if sched_id else []
        players_with_picks.append({
            "player_num": player["player_num"],
            "participant_name": player.get("participant_name"),
            "schedella_id": sched_id,
            "matches": player["matches"],
            "picks": picks,
        })
    params = session["params"]
    return templates.TemplateResponse(request, "sorteggio.html", {
        "session_id": session_id,
        "players": players_with_picks,
        "parlay_target": params.get("parlay_target"),
    })


@app.post("/sorteggio/{session_id}/roll/{pick_idx}")
async def roll_pick_route(request: Request, session_id: int, pick_idx: int,
                          schedella_id: int = Form(...)):
    session = database.get_session(DB_PATH, session_id)
    match_data = session["params"].get("_match_data", {})
    players = match_data.get("players", [])

    all_schedelle = database.get_schedelle_for_session(DB_PATH, session_id)
    player_idx = next((i for i, sid in enumerate(all_schedelle) if sid == schedella_id), 0)
    if player_idx >= len(players):
        return HTMLResponse("Error: player not found", status_code=400)

    matches = players[player_idx]["matches"]
    if pick_idx >= len(matches):
        return HTMLResponse("Error: pick index out of range", status_code=400)

    match = matches[pick_idx]
    result = service.roll_pick(match)

    picks = database.get_picks_for_schedella(DB_PATH, schedella_id)
    if pick_idx < len(picks):
        database.update_pick_pronostico(DB_PATH, picks[pick_idx]["id"], result["pronostico"])
        database.update_pick_odds_ev(DB_PATH, picks[pick_idx]["id"],
                                     result["raw_odds"], result["ev_score"])

    return templates.TemplateResponse(request, "fragments/pick_row.html", {
        "match": match,
        "result": result,
        "pick_idx": pick_idx,
        "schedella_id": schedella_id,
        "session_id": session_id,
        "revealed": True,
    })


@app.post("/sorteggio/{session_id}/save")
async def save_schedella(session_id: int):
    return RedirectResponse("/storia", status_code=303)


@app.get("/parlay/{session_id}", response_class=HTMLResponse)
async def parlay(request: Request, session_id: int):
    from src.schedella import calculate_parlay_combinations
    session = database.get_session(DB_PATH, session_id)
    params = session["params"]
    match_data = params.get("_match_data", {})
    players = match_data.get("players", [])
    parlay_target = params.get("parlay_target", 10)
    parlay_max = params.get("parlay_max")

    combos_per_player = []
    for i, player in enumerate(players):
        combos = calculate_parlay_combinations(
            player["matches"],
            min_multiplier=parlay_target,
            max_multiplier=parlay_max,
        )
        combos_per_player.append({
            "player_num": player["player_num"],
            "combos": combos[:30],
            "matches": player["matches"],
        })

    return templates.TemplateResponse(request, "parlay.html", {
        "session_id": session_id,
        "combos_per_player": combos_per_player,
        "parlay_target": parlay_target,
        "parlay_max": parlay_max,
    })


@app.get("/storia", response_class=HTMLResponse)
async def storia(request: Request):
    schedelle = database.get_all_schedelle(DB_PATH, limit=100)
    for s in schedelle:
        s["picks"] = database.get_picks_for_schedella(DB_PATH, s["id"])
    return templates.TemplateResponse(request, "storia.html", {
        "schedelle": schedelle,
    })


@app.post("/storia/{schedella_id}/result")
async def save_result(
    request: Request,
    schedella_id: int,
    outcome: str = Form(...),
    actual_multiplier: float = Form(...),
    stake: float = Form(1.0),
):
    database.upsert_result(DB_PATH, schedella_id, outcome, actual_multiplier, stake)
    s = database.get_schedella_by_id(DB_PATH, schedella_id)
    picks = database.get_picks_for_schedella(DB_PATH, schedella_id)
    return templates.TemplateResponse(request, "fragments/result_row.html", {
        "s": s,
        "picks": picks,
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

# Schedella GUI — Design Document
**Date:** 2026-05-21  
**Status:** Approved

---

## Overview

Web application GUI for the existing `src/schedella.py` CLI tool. Adds an attractive browser-based interface, Excel import, 3D dice sorteggio animation, and historical tracking of schedelle with ROI analytics. Deployable on Railway.

---

## Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend | FastAPI + Jinja2 | Python-native, reuses schedella.py directly, async-ready |
| Dynamic UI | HTMX | No JS framework needed, server-rendered fragments |
| Styling | TailwindCSS CDN | No build step, responsive utilities |
| 3D Dice | Three.js (CDN) | Only loaded on sorteggio page |
| Database | SQLite (sqlite3) | No ORM, Railway persistent volume, zero config |
| Deploy | Railway | `Procfile` + volume mount for SQLite |

---

## Visual Design

- **Theme:** Dark Gold/Amber — background `#12100a`, surface `#1a160d`, border `#2d2410`, accent `#f59e0b`, highlight `#fde68a`
- **Layout:** Responsive — top nav on desktop (`md:`), fixed bottom nav on mobile
- **Typography:** System font stack, gold accents on labels and KPIs

---

## File Structure

```
schedella-draw/
├── src/
│   └── schedella.py              # unchanged
├── app/
│   ├── main.py                   # FastAPI app + all routes
│   ├── db.py                     # SQLite schema init + query functions
│   └── service.py                # wraps src/schedella.py functions
├── static/
│   └── dice.js                   # Three.js dice component (self-contained)
├── templates/
│   ├── base.html                 # layout, nav, Tailwind CDN, gold theme
│   ├── dashboard.html
│   ├── nuova.html
│   ├── sorteggio.html
│   ├── storia.html
│   └── analisi.html
├── data/                         # Railway volume mount point
│   └── schedella.db              # SQLite (created on first run)
├── requirements.txt              # adds: fastapi, uvicorn, jinja2, python-multipart
├── Procfile                      # web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
└── railway.toml                  # volume: /data
```

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS session (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    excel_filename TEXT NOT NULL,
    params_json TEXT NOT NULL   -- JSON of all run() parameters used
);

CREATE TABLE IF NOT EXISTS schedella (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES session(id),
    player_num  INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pick (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    schedella_id INTEGER NOT NULL REFERENCES schedella(id),
    match_name   TEXT NOT NULL,
    match_date   TEXT,
    pronostico   TEXT,           -- NULL until dice rolled for this pick
    raw_odds     REAL,
    ev_score     REAL,
    best_ev      TEXT,           -- best EV suggestion from engine
    position     INTEGER NOT NULL  -- order within schedella (0-based)
);

CREATE TABLE IF NOT EXISTS result (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schedella_id      INTEGER NOT NULL REFERENCES schedella(id),
    outcome           TEXT CHECK(outcome IN ('won','lost','void')),
    actual_multiplier REAL,
    stake             REAL,
    profit            REAL,      -- computed: stake * actual_multiplier - stake if won, -stake if lost
    resolved_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Routes

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/` | `dashboard` | KPI cards, recent schedelle, trend chart |
| GET | `/nuova` | `nuova_form` | Form with all parameters |
| POST | `/nuova` | `nuova_submit` | Upload Excel → create session+picks in DB → redirect to sorteggio |
| GET | `/sorteggio/{session_id}` | `sorteggio` | Dice page, unrevealed picks list |
| POST | `/sorteggio/{session_id}/roll/{idx}` | `roll_pick` | HTMX: sample pronostico for pick idx, save to DB, return fragment |
| POST | `/sorteggio/{session_id}/save` | `save_schedella` | Mark session complete, redirect to storia |
| GET | `/storia` | `storia` | Paginated list of past schedelle |
| POST | `/storia/{schedella_id}/result` | `save_result` | HTMX: save win/loss + multiplier |
| GET | `/analisi` | `analisi` | ROI charts, win rate, pronostico breakdown |
| GET | `/parlay/{session_id}` | `parlay` | Parlay combos table (if parlay_target set) |

---

## Page Designs

### `/nuova` — Form sezioni collassabili

Four always-visible sections + one collapsible "Avanzate":

**📁 File** — drag-and-drop Excel upload

**⚽ Partite**
- Giocatori (spinner, default 1)
- Partite per giocatore (spinner, default 3)
- Permetti 4a opzionale (toggle)

**🎯 Selezione** — mutually exclusive radio: COS Column / Giorno+Ora / Nessun filtro
- If COS: text input for column name (default "Cos")
- If Giorno+Ora: two text inputs for day and time

**📊 Quote + 🎰 Parlay** — side by side
- TheOdds API key (text, persisted in localStorage)
- Usa quote API (toggle, auto-on when key present)
- Parlay target min / max (numbers, optional)

**⚙️ Avanzate** (collapsed by default)
- Solo obbligatorie (toggle)
- Seed (number, optional)
- Debug odds (toggle)

CTA: gold button "▶ Avvia Sorteggio"

---

### `/sorteggio/{id}` — Dado 3D

**Layout (desktop):** two-column — match list left (40%), Three.js canvas right (60%)  
**Layout (mobile):** stacked — canvas top, list bottom

**Match list:** each row shows match name + date. Revealed picks show pronostico in gold. Pending picks show a pulsing dot. Future picks are dimmed.

**Dice canvas (Three.js):**
- Custom polyhedron geometry: faces = number of available pronostici for that match (4–8)
- Each face labeled with pronostico name (GOL, 1, X, UNDER, OVER, NO GOL, 2)
- Gold material (`#d97706`) with ambient + point lighting, subtle glow
- On "Lancia" click → HTMX POST `/roll/{idx}` → server returns `{pronostico, odds, ev}` → JS animates dice ~2s spin, settles on matching face → HTMX swaps the match row fragment

**After all picks revealed:** "Salva Schedella" button appears. If `parlay_target` was set, "Vedi Parlay" button also appears → loads `/parlay/{session_id}`.

---

### `/storia` — Cronologia

Tabella con: data, partite (chip per ogni pronostico), esito (badge verde/rosso/grigio), moltiplicatore, profit.

Esito inseribile inline via HTMX: click "Inserisci esito" → form appare nella riga → POST → badge aggiornato senza reload.

---

### `/analisi` — ROI

- **ROI nel tempo:** line chart (Chart.js CDN)
- **Win rate per tipo di pronostico:** bar chart (GOL, 1, X, 2, UNDER, OVER, NO GOL)
- **Distribuzione quote:** histogram degli `raw_odds` delle pick vincenti vs perdenti
- **Statistiche summary:** ROI totale, win rate, schedelle totali, profit netto

---

## CLI → UI Parameter Mapping

| CLI flag | UI element | Notes |
|----------|-----------|-------|
| `--players` | spinner | default 1 |
| `--per-player` | spinner | default 3 |
| `--allow-4th` | toggle | default off |
| `--column` / `--cos-column` | text input | visible when "COS" radio selected |
| `--filter-day` | text input | visible when "Giorno+Ora" radio selected |
| `--filter-time` | text input | visible when "Giorno+Ora" radio selected |
| `--use-odds` | toggle | auto-on when TheOdds key present |
| `--theodds-key` | text input | persisted in localStorage |
| `--parlay-target` | number input | optional |
| `--parlay-max` | number input | optional, shown next to parlay-target |
| `--only-mandatory` | toggle | in "Avanzate" |
| `--seed` | number input | in "Avanzate" |
| `--debug-odds` | toggle | in "Avanzate" |
| `--interactive` | n/a | replaced by the sorteggio page itself |
| `--dump` | n/a | not exposed (dev tool) |

---

## Service Layer (`app/service.py`)

Wraps `src/schedella.py` functions directly (no subprocess):

```python
from src.schedella import (
    read_schedule, probs_from_row, raw_odds_from_row,
    sample_pronostic, best_pronostic, best_by_ev, best_by_odds,
    filter_by_datetime, mandatory_rows, non_mandatory_rows,
    calculate_parlay_combinations, format_date, PRONOSTICI
)
```

`service.prepare_session(excel_path, params) -> dict`:
- Reads schedule, applies filters, computes probs+raw_odds for all matches
- Returns structured dict (matches list with probs, raw_odds, suggestions)
- Does NOT sample pronostico yet (that happens per-roll)

`service.roll_pick(match_data, seed=None) -> dict`:
- Calls `sample_pronostic` for one match
- Returns `{pronostico, raw_odds, ev_score, best_ev}`

---

## Three.js Dice (`static/dice.js`)

- `SchedellaDice(canvasEl, faceLabels)` — constructor, sets up scene
- `SchedellaDice.roll(targetFace, onComplete)` — animates spin, calls callback when settled
- Geometry: `THREE.IcosahedronGeometry` base for ≥5 faces, `THREE.BoxGeometry` for 4 faces, `THREE.OctahedronGeometry` for 8 faces — face labels rendered as `THREE.CanvasTexture` (2D canvas text onto texture)
- Colors: gold gradient material, ambient light white + point light gold

---

## Deployment (Railway)

`Procfile`:
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`railway.toml`:
```toml
[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"

[[volumes]]
mountPath = "/data"
```

DB path in code: `os.environ.get("DB_PATH", "data/schedella.db")`

`requirements.txt` additions:
```
fastapi
uvicorn[standard]
jinja2
python-multipart
```

---

## Error Handling

- Excel upload: validate extension + openpyxl parse attempt; return 400 with user-friendly message
- TheOddsAPI failure: fall back to uniform probs, show warning banner (existing CLI behavior preserved)
- No matches found after filter: show empty state with suggestion to change filter
- DB errors: log + return 500 with generic message (no stack traces to user)

---

## Out of Scope

- Authentication / multi-user (single shared room, no login)
- Excel file storage (only the parsed data is persisted, not the file itself)
- Real-time multiplayer sync (no WebSockets)
- `--dump` flag (developer tool, not exposed)

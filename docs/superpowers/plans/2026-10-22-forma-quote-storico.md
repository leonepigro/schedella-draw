# Forma squadre, movimento quote, schedelle caricate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Serie A team form (football-data.org) and odds movement next to each match, let the user force an odds refresh, and reopen previously uploaded Excel files.

**Architecture:** New `src/form_data.py` (football-data client + form calc, TTL cache) mirrors the TheOddsAPI block in `src/schedella.py`. `app/service.py` exposes preview functions consumed by JSON endpoints in `app/main.py`; `templates/configura.html` renders them client-side via DOM. Odds snapshots live in a new SQLite table in `app/db.py`. Uploads are already stored in `session.excel_bytes`; reopen copies them into a new session.

**Tech Stack:** Python 3.14, FastAPI, Jinja2, SQLite, requests, pytest, vanilla JS + Tailwind CDN.

**Spec:** `docs/superpowers/specs/2026-10-22-forma-quote-storico-design.md`

## Global Constraints

- Display only: dice probabilities (`probs`) must not change.
- football-data token only from env `FOOTBALLDATA_KEY`; never in code, tests or commits.
- football-data: competition `SA`, base `https://api.football-data.org/v4`, header `X-Auth-Token`, timeout 10s, cache TTL `60 * 60` s.
- Aliases: `{'como': 'como 1907', 'venezia': 'venezia fc'}`.
- Odds movement threshold `ODDS_MOVE_THRESHOLD = 0.05`.
- Snapshot inserted only if odds differ from the latest snapshot of the same `event_id`.
- Reopen creates a **new** session; the original is never modified.
- All external strings rendered with `textContent` (JS) or Jinja autoescape — no `innerHTML`.
- Tests never hit the network (mock `requests.get`).
- Run tests with `python -m pytest -q` from repo root.

## Review Focus

- Team not found in football-data (typo, renamed match, Serie B team) → that team's line says "forma non disponibile", the other team still shows. Test in Task 1 (`test_match_form_unknown_team`).
- Team with zero matches at the given venue (early season) → `gf_avg`/`gs_avg` = `None`, no crash, UI omits GF/GS. Test in Task 1 (`test_team_form_no_venue_matches`).
- `FOOTBALLDATA_KEY` missing at draw time → `prepare_session` still succeeds with `form = None`. Test in Task 2 (`test_prepare_session_without_form_key`).
- Odds unchanged between two refreshes → no duplicate snapshot, no fake arrows. Test in Task 3 (`test_snapshot_not_duplicated`).
- Old sessions saved before this change (no `form` key) still render sorteggio. Covered by existing `test_sorteggio_page_loads` plus Task 5 template guard `{% if match.form %}`.

---

### Task 1: football-data client and form calculation

**Files:**
- Create: `src/form_data.py`
- Test: `tests/test_form.py`

**Interfaces:**
- Produces:
  - `class FootballDataError(Exception)`
  - `fetch_standings(api_key: str) -> list[dict]` (TOTAL table rows)
  - `fetch_finished_matches(api_key: str) -> list[dict]` (sorted by `utcDate`)
  - `find_team(name: str, standings: list[dict]) -> int | None`
  - `team_form(team_id: int, venue: str, standings, matches) -> dict | None` with keys `name, position, points, played, last5, gf_avg, gs_avg, over25_pct, gg_pct`
  - `match_form(match_name: str, api_key: str) -> {'home': dict|None, 'away': dict|None}`
  - module dict `_CACHE` (tests clear it)

- [ ] **Step 1: Write the failing tests** — `tests/test_form.py`

```python
import pytest
from unittest.mock import patch, MagicMock

from src import form_data


def _team(tid, short, name=None, tla=None):
    return {"id": tid, "shortName": short, "name": name or short, "tla": tla or short[:3].upper()}


STANDINGS = {
    "standings": [
        {"type": "TOTAL", "table": [
            {"position": 1, "points": 19, "playedGames": 4, "team": _team(1, "Napoli", "SSC Napoli", "NAP")},
            {"position": 2, "points": 17, "playedGames": 4, "team": _team(2, "Roma", "AS Roma", "ROM")},
            {"position": 5, "points": 12, "playedGames": 4, "team": _team(3, "Como 1907", "Como 1907", "COM")},
            {"position": 9, "points": 9, "playedGames": 4, "team": _team(4, "Milan", "AC Milan", "MIL")},
            {"position": 10, "points": 8, "playedGames": 4,
             "team": _team(5, "Inter", "FC Internazionale Milano", "INT")},
        ]},
        {"type": "HOME", "table": []},
    ]
}


def _m(date, home, away, hg, ag):
    return {"utcDate": date, "homeTeam": {"id": home}, "awayTeam": {"id": away},
            "score": {"fullTime": {"home": hg, "away": ag}}}


# Napoli (id 1): H 2-1 vs 2, A 0-0 at 3, H 3-2 vs 4, A 0-1 at 5  (listed out of order on purpose)
MATCHES = {"matches": [
    _m("2026-09-20T18:00:00Z", 1, 4, 3, 2),
    _m("2026-09-01T18:00:00Z", 1, 2, 2, 1),
    _m("2026-09-10T18:00:00Z", 3, 1, 0, 0),
    _m("2026-09-30T18:00:00Z", 5, 1, 1, 0),
]}


def _resp(data, status=200):
    r = MagicMock()
    r.ok = status < 400
    r.status_code = status
    r.json.return_value = data
    r.text = str(data)
    return r


def _fake_get(url, headers=None, params=None, timeout=None):
    assert headers == {"X-Auth-Token": "k"}
    if url.endswith("/competitions/SA/standings"):
        return _resp(STANDINGS)
    if url.endswith("/competitions/SA/matches"):
        assert params == {"status": "FINISHED"}
        return _resp(MATCHES)
    raise AssertionError(url)


@pytest.fixture(autouse=True)
def clear_cache():
    form_data._CACHE.clear()
    yield
    form_data._CACHE.clear()


def test_find_team_exact_alias_and_substring():
    table = STANDINGS["standings"][0]["table"]
    assert form_data.find_team("Napoli", table) == 1
    assert form_data.find_team("como", table) == 3          # alias -> "como 1907"
    assert form_data.find_team("Milan", table) == 4         # exact beats "internazionale milano"
    assert form_data.find_team("Internazionale", table) == 5  # substring of full name
    assert form_data.find_team("Pisa", table) is None


def test_team_form_napoli_home():
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        table = form_data.fetch_standings("k")
        matches = form_data.fetch_finished_matches("k")
    f = form_data.team_form(1, "home", table, matches)
    assert f["name"] == "Napoli"
    assert (f["position"], f["points"], f["played"]) == (1, 19, 4)
    assert f["last5"] == ["V", "N", "V", "P"]          # chronological
    assert f["gf_avg"] == 2.5 and f["gs_avg"] == 1.5    # home: 2-1, 3-2
    assert f["over25_pct"] == 50                        # 2-1, 3-2 have >= 3 goals
    assert f["gg_pct"] == 50                            # 2-1, 3-2 both scored


def test_team_form_napoli_away():
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        f = form_data.team_form(1, "away", form_data.fetch_standings("k"), form_data.fetch_finished_matches("k"))
    assert f["gf_avg"] == 0.0 and f["gs_avg"] == 0.5    # away: 0-0, 0-1


def test_team_form_no_venue_matches():
    # Roma (id 2) only played away
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        f = form_data.team_form(2, "home", form_data.fetch_standings("k"), form_data.fetch_finished_matches("k"))
    assert f["gf_avg"] is None and f["gs_avg"] is None
    assert f["last5"] == ["P"]


def test_match_form_unknown_team():
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        out = form_data.match_form("Napoli - Pisa", "k")
    assert out["home"]["name"] == "Napoli"
    assert out["away"] is None


def test_match_form_without_separator():
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        assert form_data.match_form("Napoli", "k") == {"home": None, "away": None}


def test_fetch_is_cached():
    with patch.object(form_data.requests, "get", side_effect=_fake_get) as get:
        form_data.match_form("Napoli - Roma", "k")
        form_data.match_form("Como - Milan", "k")
    assert get.call_count == 2


def test_api_error_raises_with_message():
    with patch.object(form_data.requests, "get",
                      return_value=_resp({"message": "restricted resource"}, status=403)):
        with pytest.raises(form_data.FootballDataError, match="403.*restricted"):
            form_data.fetch_standings("k")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_form.py -q`
Expected: FAIL — `ImportError: cannot import name 'form_data' from 'src'`

- [ ] **Step 3: Implement** — `src/form_data.py`

```python
"""Serie A team form from football-data.org. Display only: it never changes the dice probabilities."""
import time

import requests

FOOTBALLDATA_BASE_URL = 'https://api.football-data.org/v4'
FOOTBALLDATA_COMPETITION = 'SA'
FOOTBALLDATA_TIMEOUT_SECONDS = 10
# Standings and results change at most a few times a day.
FORM_CACHE_TTL_SECONDS = 60 * 60
FORM_LAST_N = 5
OVER_25_MIN_GOALS = 3
# Excel short names whose football-data shortName differs
FOOTBALLDATA_TEAM_ALIASES = {'como': 'como 1907', 'venezia': 'venezia fc'}

_CACHE = {}


class FootballDataError(Exception):
    """football-data.org returned an error or was unreachable."""


def _get(path, api_key, **params):
    cache_key = (path, api_key, tuple(sorted(params.items())))
    hit = _CACHE.get(cache_key)
    if hit is not None and time.monotonic() - hit[0] < FORM_CACHE_TTL_SECONDS:
        return hit[1]
    try:
        resp = requests.get(f'{FOOTBALLDATA_BASE_URL}{path}', headers={'X-Auth-Token': api_key},
                            params=params or None, timeout=FOOTBALLDATA_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise FootballDataError(f'football-data non raggiungibile: {exc}') from exc
    if not resp.ok:
        try:
            message = resp.json().get('message', '')
        except ValueError:
            message = resp.text[:200]
        raise FootballDataError(f'football-data HTTP {resp.status_code}: {message}')
    data = resp.json()
    _CACHE[cache_key] = (time.monotonic(), data)
    return data


def fetch_standings(api_key):
    data = _get(f'/competitions/{FOOTBALLDATA_COMPETITION}/standings', api_key)
    for standing in data.get('standings', []):
        if standing.get('type') == 'TOTAL':
            return standing.get('table', [])
    return []


def fetch_finished_matches(api_key):
    data = _get(f'/competitions/{FOOTBALLDATA_COMPETITION}/matches', api_key, status='FINISHED')
    return sorted(data.get('matches', []), key=lambda m: m.get('utcDate', ''))


def _norm(value):
    return (value or '').strip().lower()


def find_team(name, standings):
    """Team id for an Excel team name: exact match on shortName/name/tla first, then substring of shortName/name."""
    name = _norm(name)
    name = FOOTBALLDATA_TEAM_ALIASES.get(name, name)
    candidates = [
        (row['team']['id'], [_norm(row['team'].get(k)) for k in ('shortName', 'name', 'tla')])
        for row in standings
    ]
    for team_id, names in candidates:
        if name in names:
            return team_id
    for team_id, names in candidates:
        if any(name in n for n in names[:2] if n):
            return team_id
    return None


def _avg(values):
    return round(sum(values) / len(values), 1) if values else None


def _pct(count, total):
    return round(100 * count / total) if total else None


def team_form(team_id, venue, standings, matches):
    """Form summary for one team; venue ('home'|'away') selects which matches feed the goal averages."""
    row = next((r for r in standings if r['team']['id'] == team_id), None)
    if row is None:
        return None

    played = []  # (goals_for, goals_against, at_home), chronological
    for m in matches:
        full_time = (m.get('score') or {}).get('fullTime') or {}
        home_goals, away_goals = full_time.get('home'), full_time.get('away')
        if home_goals is None or away_goals is None:
            continue
        if m['homeTeam']['id'] == team_id:
            played.append((home_goals, away_goals, True))
        elif m['awayTeam']['id'] == team_id:
            played.append((away_goals, home_goals, False))

    at_venue = [(gf, ga) for gf, ga, at_home in played if at_home == (venue == 'home')]
    return {
        'name': row['team'].get('shortName') or row['team'].get('name'),
        'position': row.get('position'),
        'points': row.get('points'),
        'played': row.get('playedGames'),
        'last5': ['V' if gf > ga else 'N' if gf == ga else 'P' for gf, ga, _ in played[-FORM_LAST_N:]],
        'gf_avg': _avg([gf for gf, _ in at_venue]),
        'gs_avg': _avg([ga for _, ga in at_venue]),
        'over25_pct': _pct(sum(1 for gf, ga, _ in played if gf + ga >= OVER_25_MIN_GOALS), len(played)),
        'gg_pct': _pct(sum(1 for gf, ga, _ in played if gf > 0 and ga > 0), len(played)),
    }


def match_form(match_name, api_key):
    """Form of both teams of a 'Home - Away' match; a team not found on football-data is None."""
    match_name = str(match_name or '')
    if ' - ' not in match_name:
        return {'home': None, 'away': None}
    home, away = [p.strip() for p in match_name.split(' - ', 1)]
    standings = fetch_standings(api_key)
    matches = fetch_finished_matches(api_key)

    def one(name, venue):
        team_id = find_team(name, standings)
        return None if team_id is None else team_form(team_id, venue, standings, matches)

    return {'home': one(home, 'home'), 'away': one(away, 'away')}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_form.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/form_data.py tests/test_form.py
git commit -m "feat: football-data client and Serie A team form calculation"
```

---

### Task 2: Form preview endpoint and form in drawn sessions

**Files:**
- Modify: `app/service.py` (imports; new `get_form_preview`; `prepare_session` match loops)
- Modify: `app/main.py` (new `POST /api/form`)
- Test: `tests/test_form.py` (append), `tests/test_routes.py` (append)

**Interfaces:**
- Consumes: `match_form`, `FootballDataError` from Task 1.
- Produces:
  - `service.get_form_preview(match_names: list[str], api_key: str | None = None) -> {"results": [{"name", "home", "away"}], "error": str | None}`
  - every match dict from `prepare_session` gets `"form": {"home", "away"} | None`
  - `POST /api/form` body `{"matches": [str]}`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_form.py`

```python
from app import service


def test_form_preview_without_key(monkeypatch):
    monkeypatch.delenv("FOOTBALLDATA_KEY", raising=False)
    out = service.get_form_preview(["Napoli - Roma"])
    assert out["results"] == [] and "FOOTBALLDATA_KEY" in out["error"]


def test_form_preview_results():
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        out = service.get_form_preview(["Napoli - Roma", "Napoli - Pisa"], "k")
    assert out["error"] is None
    assert out["results"][0]["name"] == "Napoli - Roma"
    assert out["results"][0]["away"]["name"] == "Roma"
    assert out["results"][1]["away"] is None


def test_form_preview_surfaces_error():
    with patch.object(form_data.requests, "get", return_value=_resp({"message": "bad token"}, status=400)):
        out = service.get_form_preview(["Napoli - Roma"], "k")
    assert "bad token" in out["error"]


def test_prepare_session_without_form_key(monkeypatch):
    from tests.test_service import _make_excel_bytes
    monkeypatch.delenv("FOOTBALLDATA_KEY", raising=False)
    result = service.prepare_session(_make_excel_bytes(), "t.xlsx", {"per_player": 2, "players": 1})
    assert all(m["form"] is None for m in result["players"][0]["matches"])


def test_prepare_session_with_form(monkeypatch):
    from tests.test_service import _make_excel_bytes
    monkeypatch.setenv("FOOTBALLDATA_KEY", "k")
    with patch.object(form_data.requests, "get", side_effect=_fake_get):
        result = service.prepare_session(_make_excel_bytes(), "t.xlsx", {"per_player": 3, "players": 1})
    forms = [m["form"] for m in result["players"][0]["matches"]]
    assert all(set(f) == {"home", "away"} for f in forms)
```

Append to `tests/test_routes.py`:

```python
def test_api_form_without_key(client, monkeypatch):
    monkeypatch.delenv("FOOTBALLDATA_KEY", raising=False)
    r = client.post("/api/form", json={"matches": ["Napoli - Roma"]})
    assert r.status_code == 200
    assert r.json()["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_form.py tests/test_routes.py -q`
Expected: FAIL — `AttributeError: module 'app.service' has no attribute 'get_form_preview'` and 404 on `/api/form`

- [ ] **Step 3: Implement**

`app/service.py` — add import below the `from src.schedella import (...)` block:

```python
from src.form_data import match_form, FootballDataError
```

Add after `get_odds_preview`:

```python
def get_form_preview(match_names: list, api_key: str = None) -> dict:
    """
    Team form (football-data.org) for each match name, shown on configura next to the odds.

    Returns {"results": [{"name", "home", "away"}], "error": str | None}; on an API error lookup stops.
    """
    api_key = api_key or os.environ.get("FOOTBALLDATA_KEY")
    if not api_key:
        return {"results": [], "error": "Imposta FOOTBALLDATA_KEY per vedere la forma delle squadre."}

    results = []
    for name in match_names:
        try:
            form = match_form(name, api_key)
        except FootballDataError as exc:
            return {"results": results, "error": str(exc)}
        results.append({"name": name, **form})
    return {"results": results, "error": None}


def _form_or_none(match_name: str, api_key: str):
    """Form saved with a drawn session; missing key or API failure must not block the draw."""
    if not api_key:
        return None
    try:
        return match_form(match_name, api_key)
    except FootballDataError:
        return None
```

In `prepare_session`, after `theodds_key = params.get("theodds_key")` add:

```python
    form_key = os.environ.get("FOOTBALLDATA_KEY")
```

and change both loops so each match dict gets `form`:

```python
        matches_out = []
        for _, row in selected.iterrows():
            probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
            raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
            m = _row_to_match_dict(row, probs, raw_odds)
            m["form"] = _form_or_none(m["match_name"], form_key)
            matches_out.append(m)

        if extras is not None:
            for _, row in extras.iterrows():
                probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
                raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
                m = _row_to_match_dict(row, probs, raw_odds)
                m["form"] = _form_or_none(m["match_name"], form_key)
                m["extra"] = True
                matches_out.append(m)
```

`app/main.py` — after the `/api/odds` handler:

```python
class FormPreviewRequest(BaseModel):
    matches: list[str]


@app.post("/api/form")
def form_preview(body: FormPreviewRequest):
    # Sync handler: football-data calls block, FastAPI runs this in its threadpool.
    return service.get_form_preview(body.matches)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/service.py app/main.py tests/test_form.py tests/test_routes.py
git commit -m "feat: team form preview endpoint and form saved in drawn sessions"
```

---

### Task 3: Odds snapshots, movement data and forced refresh (backend)

**Files:**
- Modify: `src/schedella.py` (`lookup_theodds_match`: `force` param, `event_id` in result)
- Modify: `app/db.py` (table + `add_odds_snapshot`, `get_first_odds_snapshot`)
- Modify: `app/service.py` (`get_odds_preview` signature and result)
- Modify: `app/main.py` (`OddsPreviewRequest.force`, pass `DB_PATH`)
- Test: `tests/test_odds.py`, `tests/test_db.py` (append)

**Interfaces:**
- Produces:
  - `lookup_theodds_match(match, api_key, debug=False, force=False) -> {'raw', 'event', 'event_id'}`
  - `db.add_odds_snapshot(path: str, event_id: str, event_name: str, odds: list) -> bool` (True if inserted)
  - `db.get_first_odds_snapshot(path: str, event_id: str) -> {"odds": list, "fetched_at": str} | None`
  - `service.get_odds_preview(match_names, api_key=None, db_path=None, force=False)`; each result also has `first_odds: list | None`, `first_at: str | None`
  - `POST /api/odds` body `{"matches", "key", "force": bool = false}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
from app.db import add_odds_snapshot, get_first_odds_snapshot


def test_snapshot_first_and_dedup(db_path):
    assert get_first_odds_snapshot(db_path, "ev1") is None
    assert add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.95, 3.4, 2.5, None, None, None, None])
    assert not add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.95, 3.4, 2.5, None, None, None, None])
    assert add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.83, 3.45, 2.56, None, None, None, None])
    first = get_first_odds_snapshot(db_path, "ev1")
    assert first["odds"][0] == 2.95 and first["fetched_at"]
```

Append to `tests/test_odds.py`:

```python
from app.db import init_db


def test_lookup_returns_event_id():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        assert schedella.lookup_theodds_match("Napoli - Roma", "k")["event_id"] == "ev1"


def test_force_bypasses_match_cache():
    with patch.object(schedella.requests, "get", side_effect=_fake_get) as get:
        schedella.lookup_theodds_match("Napoli - Roma", "k")
        calls = get.call_count
        schedella.lookup_theodds_match("Napoli - Roma", "k", force=True)
    assert get.call_count == calls + 1  # only the event odds call; sports/events stay cached


def test_odds_preview_first_odds_and_snapshot_not_duplicated(tmp_path):
    import sqlite3
    db = str(tmp_path / "t.db")
    init_db(db)
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        out1 = get_odds_preview(["Napoli - Roma"], "k", db)
        out2 = get_odds_preview(["Napoli - Roma"], "k", db, force=True)
    assert out1["results"][0]["first_odds"][0] == 2.83
    assert out2["results"][0]["first_at"]
    count = sqlite3.connect(db).execute("SELECT COUNT(*) FROM odds_snapshot").fetchone()[0]
    assert count == 1  # same odds twice -> one snapshot


def test_odds_preview_without_db_has_no_first_odds():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        out = get_odds_preview(["Napoli - Roma"], "k")
    assert out["results"][0]["first_odds"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odds.py tests/test_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'add_odds_snapshot'`, `KeyError: 'event_id'`, `TypeError: ... unexpected keyword argument 'force'`

- [ ] **Step 3: Implement**

`src/schedella.py` — replace `lookup_theodds_match` signature, docstring tail, cache check and result init:

```python
def lookup_theodds_match(match, api_key, debug=False, force=False):
    """Resolve a 'Home - Away' match on TheOddsAPI.

    Returns {'raw': np.ndarray of 7 decimal odds (NaN where missing) | None, 'event': 'Home - Away' | None,
    'event_id': str | None}. 'event' is the API's own name for the matched event, so the caller can show
    what was matched. Raises TheOddsError on API failures; results (found or not) are cached for
    ODDS_CACHE_TTL_SECONDS. force=True skips the cached result for this match (sports/events stay cached).
    """
    match = str(match or '').strip()
    cache_key = ('match', api_key, match)
    if not force:
        found, cached = _cache_get(cache_key)
        if found:
            return cached

    result = {'raw': None, 'event': None, 'event_id': None}
```

and inside `if ev is not None:` add after `result['event'] = ...`:

```python
            result['event_id'] = ev.get('id')
```

`app/db.py` — in `init_db` executescript, after the `result` table:

```sql
            CREATE TABLE IF NOT EXISTS odds_snapshot (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id    TEXT NOT NULL,
                event_name  TEXT NOT NULL,
                fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                odds_json   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_odds_snapshot_event ON odds_snapshot(event_id, id);
```

Append functions:

```python
def add_odds_snapshot(path: str, event_id: str, event_name: str, odds: list) -> bool:
    """Store odds for an event unless identical to its latest snapshot. Returns True if a row was inserted."""
    payload = json.dumps(odds)
    with get_connection(path) as con:
        last = con.execute(
            "SELECT odds_json FROM odds_snapshot WHERE event_id=? ORDER BY id DESC LIMIT 1", (event_id,)
        ).fetchone()
        if last and last["odds_json"] == payload:
            return False
        con.execute(
            "INSERT INTO odds_snapshot (event_id, event_name, odds_json) VALUES (?,?,?)",
            (event_id, event_name, payload),
        )
        return True


def get_first_odds_snapshot(path: str, event_id: str) -> Optional[dict]:
    with get_connection(path) as con:
        row = con.execute(
            "SELECT odds_json, fetched_at FROM odds_snapshot WHERE event_id=? ORDER BY id ASC LIMIT 1",
            (event_id,),
        ).fetchone()
    return {"odds": json.loads(row["odds_json"]), "fetched_at": row["fetched_at"]} if row else None
```

`app/service.py` — add import near the top:

```python
from app import db as database
```

Replace `get_odds_preview` with:

```python
def get_odds_preview(match_names: list, api_key: str = None, db_path: str = None, force: bool = False) -> dict:
    """
    Look up TheOddsAPI odds for each match name, for display right after the Excel upload.

    Returns {"results": [{"name", "event", "odds", "first_odds", "first_at"}], "remaining", "error"}.
    "odds" is a list of 7 decimal odds (None where missing) or None if the match was not found.
    With db_path, each lookup is stored as a snapshot and "first_odds"/"first_at" give the first one seen,
    so the page can show how odds moved. force=True re-reads odds from the API (costs credits).
    On an API error, lookup stops and "error" carries the message (it would be the same for every match).
    """
    api_key = api_key or os.environ.get("THEODDSAPI_KEY")
    if not api_key:
        return {"results": [], "remaining": None, "error": "Inserisci la API key TheOddsAPI per vedere le quote."}

    results = []
    for name in match_names:
        try:
            found = lookup_theodds_match(name, api_key, force=force)
        except TheOddsError as exc:
            return {"results": results, "remaining": theodds_remaining_credits(api_key), "error": str(exc)}
        raw = found["raw"]
        odds = None if raw is None else [None if math.isnan(v) else float(v) for v in raw]
        first = None
        if db_path and odds is not None and found.get("event_id"):
            database.add_odds_snapshot(db_path, found["event_id"], found["event"], odds)
            first = database.get_first_odds_snapshot(db_path, found["event_id"])
        results.append({
            "name": name,
            "event": found["event"],
            "odds": odds,
            "first_odds": first["odds"] if first else None,
            "first_at": first["fetched_at"] if first else None,
        })
    return {"results": results, "remaining": theodds_remaining_credits(api_key), "error": None}
```

`app/main.py` — update the request model and handler:

```python
class OddsPreviewRequest(BaseModel):
    matches: list[str]
    key: Optional[str] = None
    force: bool = False


@app.post("/api/odds")
def odds_preview(body: OddsPreviewRequest):
    # Sync handler: TheOddsAPI calls block, FastAPI runs this in its threadpool.
    return service.get_odds_preview(body.matches, body.key or None, DB_PATH, body.force)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/schedella.py app/db.py app/service.py app/main.py tests/test_odds.py tests/test_db.py
git commit -m "feat: odds snapshots with first-seen odds and forced refresh"
```

---

### Task 4: Reopen previously uploaded Excel files

**Files:**
- Modify: `app/db.py` (new `get_recent_uploads`)
- Modify: `app/main.py` (`/nuova` context, new `POST /nuova/riapri/{session_id}`)
- Modify: `templates/nuova.html`
- Test: `tests/test_db.py`, `tests/test_routes.py` (append)

**Interfaces:**
- Produces:
  - `db.get_recent_uploads(path: str, limit: int = 10) -> list[{"session_id": int, "excel_filename": str, "created_at": str}]` — latest session per filename, newest first
  - `POST /nuova/riapri/{session_id}` → 303 to `/configura/{new_id}`, or `/nuova` if missing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
from app.db import create_upload_session, get_recent_uploads


def test_recent_uploads_latest_per_filename(db_path):
    a1 = create_upload_session(db_path, "A.xlsx", b"1")
    b1 = create_upload_session(db_path, "B.xlsx", b"2")
    a2 = create_upload_session(db_path, "A.xlsx", b"3")
    ups = get_recent_uploads(db_path)
    assert [u["session_id"] for u in ups] == [a2, b1]
    assert ups[0]["excel_filename"] == "A.xlsx" and ups[0]["created_at"]
```

Append to `tests/test_routes.py`:

```python
def test_nuova_lists_and_reopens_uploads(client):
    data = _excel_bytes()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    r = client.post("/nuova", files={"excel_file": ("Giornata8.xlsx", data, mime)}, follow_redirects=False)
    orig_id = int(r.headers["location"].split("/")[-1])
    page = client.get("/nuova").text
    assert "Giornata8.xlsx" in page and f"/nuova/riapri/{orig_id}" in page
    r2 = client.post(f"/nuova/riapri/{orig_id}", follow_redirects=False)
    assert r2.status_code == 303
    new_id = int(r2.headers["location"].split("/")[-1])
    assert new_id != orig_id
    assert "Giornata8.xlsx" in client.get(r2.headers["location"]).text


def test_reopen_missing_session(client):
    r = client.post("/nuova/riapri/9999", follow_redirects=False)
    assert r.headers["location"] == "/nuova"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py tests/test_routes.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_recent_uploads'`, 404/405 on `/nuova/riapri/...`

- [ ] **Step 3: Implement**

`app/db.py`:

```python
def get_recent_uploads(path: str, limit: int = 10) -> list[dict]:
    """Latest uploaded session per Excel filename, newest first."""
    with get_connection(path) as con:
        rows = con.execute(
            """SELECT s.id AS session_id, s.excel_filename, s.created_at
               FROM session s
               WHERE s.excel_bytes IS NOT NULL
                 AND s.id = (SELECT MAX(s2.id) FROM session s2
                             WHERE s2.excel_filename = s.excel_filename AND s2.excel_bytes IS NOT NULL)
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
```

`app/main.py` — `nuova_form` context and new route:

```python
@app.get("/nuova", response_class=HTMLResponse)
async def nuova_form(request: Request):
    default_path = _default_excel_path()
    return templates.TemplateResponse(request, "nuova.html", {
        "default_excel": os.path.basename(default_path) if default_path else None,
        "recent_uploads": database.get_recent_uploads(DB_PATH),
    })


@app.post("/nuova/riapri/{session_id}")
async def nuova_riapri(session_id: int):
    # Copy into a new session so an already drawn session is never altered.
    data = database.get_session_bytes(DB_PATH, session_id)
    if not data or not data.get("excel_bytes"):
        return RedirectResponse("/nuova", status_code=303)
    new_id = database.create_upload_session(DB_PATH, data["excel_filename"], data["excel_bytes"])
    return RedirectResponse(f"/configura/{new_id}", status_code=303)
```

`templates/nuova.html` — after the `{% endif %}` closing the default-excel block, before the upload `<form>`:

```html
{% if recent_uploads %}
<div class="card mb-4">
  <h2 class="text-[#f59e0b] font-semibold mb-3">&#x1F5C2; Schedelle caricate</h2>
  <div class="space-y-1">
    {% for u in recent_uploads %}
    <form method="post" action="/nuova/riapri/{{ u.session_id }}">
      <button type="submit"
              class="w-full flex items-center justify-between bg-[#0f0d08] hover:bg-[#1a160d] rounded-lg px-3 py-2 text-sm">
        <span class="text-[#e5e7eb] truncate">{{ u.excel_filename }}</span>
        <span class="text-[#78716c] text-xs flex-shrink-0 ml-3">{{ u.created_at[:16] }} UTC &#x2192;</span>
      </button>
    </form>
    {% endfor %}
  </div>
</div>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/main.py templates/nuova.html tests/test_db.py tests/test_routes.py
git commit -m "feat: list and reopen previously uploaded Excel files"
```

---

### Task 5: UI — form lines, odds movement, refresh button

**Files:**
- Create: `templates/fragments/form_lines.html`
- Modify: `templates/configura.html` (match item markup, status lines, refresh button, JS)
- Modify: `templates/sorteggio.html`, `templates/fragments/pick_row.html` (include form lines)
- Test: `tests/test_routes.py` (append)

**Interfaces:**
- Consumes: `/api/odds` (`force`, `first_odds`, `first_at`) from Task 3; `/api/form` from Task 2; `match.form` from Task 2.

- [ ] **Step 1: Write the failing test** — append to `tests/test_routes.py`

```python
def test_sorteggio_shows_form_lines(client, monkeypatch):
    from unittest.mock import patch
    import app.service as svc
    fake = {"home": {"name": "Milan", "position": 4, "points": 13, "played": 7, "last5": ["V", "N"],
                     "gf_avg": 1.5, "gs_avg": 0.5, "over25_pct": 57, "gg_pct": 43},
            "away": None}
    monkeypatch.setenv("FOOTBALLDATA_KEY", "k")
    with patch.object(svc, "match_form", return_value=fake):
        sid = _create_session(client)
    page = client.get(f"/sorteggio/{sid}").text
    assert "Milan 4° 13pt" in page and "O2.5 57%" in page
    assert "forma non disponibile" in page


def test_configura_has_refresh_button(client):
    data = _excel_bytes()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    r = client.post("/nuova", files={"excel_file": ("t.xlsx", data, mime)}, follow_redirects=False)
    page = client.get(r.headers["location"]).text
    assert 'id="odds-refresh"' in page and 'class="match-form' in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routes.py -q`
Expected: FAIL — form text and refresh button missing

- [ ] **Step 3: Implement**

Create `templates/fragments/form_lines.html`:

```html
{% if match.form %}
<div class="text-[11px] text-[#a8a29e] font-mono space-y-0.5 pt-1">
  {% for f, venue in [(match.form.home, 'casa'), (match.form.away, 'trasf.')] %}
  <div>
    {% if f %}
    {{ f.name }} {{ f.position }}° {{ f.points }}pt · {{ f.last5|join(' ') or '–' }}
    {%- if f.gf_avg is not none %} · {{ venue }} GF {{ "%.1f"|format(f.gf_avg) }} GS {{ "%.1f"|format(f.gs_avg) }}{% endif %}
    {%- if f.over25_pct is not none %} · O2.5 {{ f.over25_pct }}%{% endif %}
    {%- if f.gg_pct is not none %} · GG {{ f.gg_pct }}%{% endif %}
    {% else %}
    <span class="text-[#57534e]">forma non disponibile</span>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}
```

`templates/sorteggio.html` — right after the `{% endif %}` closing `{% if match.best_prob or match.best_odds %}` block:

```html
        {% include "fragments/form_lines.html" %}
```

`templates/fragments/pick_row.html` — after the stats row `</div>` (before the final `</div>`):

```html
  {% include "fragments/form_lines.html" %}
```

`templates/configura.html`:

1. In each `.match-item`, after the `.match-odds` div:

```html
        <div class="match-form w-full pl-6 text-[11px] text-[#a8a29e] font-mono space-y-0.5"></div>
```

2. Replace `<p id="odds-status" ...></p>` with:

```html
    <div class="flex items-center justify-between gap-3 mb-1">
      <p id="odds-status" class="text-xs text-[#78716c]"></p>
      <button type="button" id="odds-refresh" onclick="loadOdds(null, true)"
              title="Rilegge le quote da TheOddsAPI (~3 crediti per partita)"
              class="text-xs text-[#f59e0b] hover:text-[#fde68a] flex-shrink-0">&#x21BB; Aggiorna quote</button>
    </div>
    <p id="form-status" class="text-xs mb-3 text-[#78716c]"></p>
```

3. In `setOddsStatus`, the class string becomes `'text-xs ' + (...)` (no `mb-3`, the wrapper handles spacing).

4. Add `const ODDS_MOVE_THRESHOLD = 0.05;` under `ODDS_LABELS`, and in `renderOdds` replace the per-label loop body with:

```js
    ODDS_LABELS.forEach((label, i) => {
      const span = document.createElement('span');
      span.className = 'mr-3';
      const v = result.odds[i];
      span.textContent = label + ' ' + (v == null ? '–' : v.toFixed(2));
      if (v != null) span.classList.add('text-[#fde68a]');
      const first = result.first_odds ? result.first_odds[i] : null;
      if (v != null && first != null && Math.abs(v - first) >= ODDS_MOVE_THRESHOLD) {
        const mv = document.createElement('span');
        mv.className = v < first ? 'text-emerald-400' : 'text-red-400';
        mv.textContent = (v < first ? ' ↓' : ' ↑') + ' (' + first.toFixed(2) + ')';
        mv.title = 'prima rilevazione: ' + result.first_at + ' UTC';
        span.appendChild(mv);
      }
      box.appendChild(span);
    });
```

5. `loadOdds(items, force)`: add the second parameter, disable the button while loading, send `force`:

```js
  async function loadOdds(items, force) {
    const list = items || [...document.querySelectorAll('#match-list .match-item')];
    if (!list.length) return;
    const btn = document.getElementById('odds-refresh');
    if (btn) btn.disabled = true;
    list.forEach(it => { it.querySelector('.match-odds').textContent = '…'; });
    setOddsStatus(force ? 'Aggiorno quote da TheOddsAPI…' : 'Carico quote da TheOddsAPI…');
    try {
      const resp = await fetch('/api/odds', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          key: document.getElementById('theodds-key')?.value.trim() || null,
          matches: list.map(it => it.querySelector('.match-name').textContent.trim()),
          force: !!force,
        }),
      });
      // ... existing response handling unchanged ...
    } catch (e) {
      // ... existing catch unchanged ...
    } finally {
      if (btn) btn.disabled = false;
    }
  }
```

6. Add form rendering and loading after `loadOdds`:

```js
  function setFormStatus(text, isError) {
    const st = document.getElementById('form-status');
    if (!st) return;
    st.textContent = text;
    st.className = 'text-xs mb-3 ' + (isError ? 'text-red-400' : 'text-[#78716c]');
  }

  function formLine(f, venue) {
    const parts = [f.name + ' ' + f.position + '° ' + f.points + 'pt', f.last5.join(' ') || '–'];
    if (f.gf_avg != null) parts.push(venue + ' GF ' + f.gf_avg.toFixed(1) + ' GS ' + f.gs_avg.toFixed(1));
    if (f.over25_pct != null) parts.push('O2.5 ' + f.over25_pct + '%');
    if (f.gg_pct != null) parts.push('GG ' + f.gg_pct + '%');
    return parts.join(' · ');
  }

  function renderForm(item, result) {
    const box = item.querySelector('.match-form');
    box.replaceChildren();
    [[result.home, 'casa'], [result.away, 'trasf.']].forEach(([f, venue]) => {
      const line = document.createElement('div');
      if (f) {
        line.textContent = formLine(f, venue);
      } else {
        line.className = 'text-[#57534e]';
        line.textContent = 'forma non disponibile';
      }
      box.appendChild(line);
    });
  }

  async function loadForm(items) {
    const list = items || [...document.querySelectorAll('#match-list .match-item')];
    if (!list.length) return;
    setFormStatus('Carico forma squadre da football-data…');
    try {
      const resp = await fetch('/api/form', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({matches: list.map(it => it.querySelector('.match-name').textContent.trim())}),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      data.results.forEach((r, i) => renderForm(list[i], r));
      list.slice(data.results.length).forEach(it => it.querySelector('.match-form').replaceChildren());
      setFormStatus(data.error || '', !!data.error);
    } catch (e) {
      setFormStatus('Errore caricamento forma: ' + e.message, true);
    }
  }
```

7. In `finalizeRename`, after `loadOdds([el.closest('.match-item')]);` add:

```js
    loadForm([el.closest('.match-item')]);
```

8. After the final `loadOdds();` call at the bottom of the script add:

```js
  loadForm();
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all passed

- [ ] **Step 5: Manual check in browser** (needs `FOOTBALLDATA_KEY` and `THEODDSAPI_KEY` in env)

Run: `python -m uvicorn app.main:app --port 8765`, open `/nuova`, click "Usa Schedella2627.xlsx":
- each match shows odds line + two form lines (or "forma non disponibile");
- "↻ Aggiorna quote" disables while loading and re-enables; credits counter decreases;
- `/nuova` lists "Schedelle caricate"; clicking one opens configura for a new session id.

- [ ] **Step 6: Commit**

```bash
git add templates/fragments/form_lines.html templates/configura.html templates/sorteggio.html templates/fragments/pick_row.html tests/test_routes.py
git commit -m "feat: show team form, odds movement and refresh button in UI"
```

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
    """Team id for an Excel team name: exact match on shortName/name/tla first, then an unambiguous
    substring of shortName/name. Empty or ambiguous names return None rather than a wrong team."""
    name = _norm(name)
    if not name:
        return None
    name = FOOTBALLDATA_TEAM_ALIASES.get(name, name)
    candidates = [
        (row['team']['id'], [_norm(row['team'].get(k)) for k in ('shortName', 'name', 'tla')])
        for row in standings
    ]
    for team_id, names in candidates:
        if name in names:
            return team_id
    partial = [team_id for team_id, names in candidates if any(name in n for n in names[:2] if n)]
    return partial[0] if len(partial) == 1 else None


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

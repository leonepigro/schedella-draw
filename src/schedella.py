import argparse
import pandas as pd
import numpy as np
import requests
import os
import time
from pathlib import Path
from tabulate import tabulate

PRONOSTICI = ['1', 'X', '2', 'under', 'over', 'gol', 'no gol']
# Index groups of PRONOSTICI that form one betting market each: 1X2, Under/Over, Gol/No gol
PRONOSTICI_MARKETS = [(0, 1, 2), (3, 4), (5, 6)]
DATE_COLUMNS = ['Data', 'Date', 'DATE']
MATCH_COLUMNS = ['Partita', 'Match', 'Home']
DEFAULT_COS_COLUMNS = ['COS', 'Cos', 'cos']
ODDS_SUFFIXES = ['_1', '_X', '_2', '_under', '_over', '_gol', '_no_gol']
PREFERRED_THEODDS_SPORT_KEYS = ['soccer_italy_serie_a', 'soccer_italy', 'soccer_italy_serie_b']
THEODDS_BASE_URL = 'https://api.the-odds-api.com/v4'
THEODDS_TIMEOUT_SECONDS = 10
THEODDS_REGIONS = 'eu'
THEODDS_MARKETS = 'h2h,totals,btts'
# Odds barely move between upload and draw; long enough to reuse preview lookups, short enough to refresh per matchday.
ODDS_CACHE_TTL_SECONDS = 30 * 60
# Excel short names whose plain substring match against TheOddsAPI names fails or is ambiguous
# (e.g. 'milan' would also match 'inter milan').
THEODDS_TEAM_ALIASES = {
    'milan': 'ac milan',
    'inter': 'inter milan',
    'roma': 'as roma',
    'atalanta': 'atalanta bc',
    'verona': 'hellas verona',
}

_THEODDS_CACHE = {}
_THEODDS_REMAINING = {}


def find_column(columns, names):
    for name in names:
        if name in columns:
            return name
    return None


def normalize_text(series):
    return series.astype(str).fillna('').str.strip()


def find_odds_prefix(columns):
    prefixes = {}
    for col in columns:
        col = str(col)
        for suffix in ODDS_SUFFIXES:
            if col.endswith(suffix):
                prefix = col[:-len(suffix)]
                prefixes.setdefault(prefix, []).append(suffix)
    best_prefix = None
    best_count = 0
    for prefix, found in prefixes.items():
        if len(found) > best_count:
            best_prefix = prefix
            best_count = len(found)
    return best_prefix if best_count > 0 else None


def parse_theodds_market(m, home, away, debug=False):
    key = str(m.get('key', '')).strip().lower()
    outcomes = m.get('outcomes') or []
    normalize = lambda value: (str(value or '').strip().lower())

    def get_price(outcome):
        return outcome.get('price') or outcome.get('odds') or outcome.get('point')

    if key == 'h2h' or (key.startswith('h2h') and 'lay' not in key):
        vals = {normalize(o.get('name')): get_price(o) for o in outcomes}
        home_key = next((k for k in vals if home in k or k in ('home', '1', 'home team', 'home_team')), None)
        away_key = next((k for k in vals if away in k or k in ('away', '2', 'away team', 'away_team')), None)
        draw_key = next((k for k in vals if 'draw' in k or k == 'x'), None)
        if home_key and away_key and draw_key:
            try:
                return 'h2h', [float(vals[home_key]), float(vals[draw_key]), float(vals[away_key])]
            except Exception:
                return None, None

    if 'total' in key or key == 'totals':
        over = None
        under = None
        for o in outcomes:
            name = normalize(o.get('name'))
            if 'over' in name:
                over = get_price(o)
            elif 'under' in name:
                under = get_price(o)
        if over is not None and under is not None:
            try:
                return 'totals', {'under': float(under), 'over': float(over)}
            except Exception:
                return None, None

    if 'btts' in key or 'both' in key or 'teams' in key or 'goal' in key:
        gol = None
        no_gol = None
        for o in outcomes:
            name = normalize(o.get('name'))
            if 'yes' in name or 'gol' in name or 'si' == name:
                gol = get_price(o)
            elif 'no' in name or 'no gol' in name or 'nogoal' in name or 'non' == name:
                no_gol = get_price(o)
        if gol is not None and no_gol is not None:
            try:
                return 'btts', {'gol': float(gol), 'no_gol': float(no_gol)}
            except Exception:
                return None, None

    # Generic fallback if the market contains yes/no outcomes
    if len(outcomes) == 2:
        yes = None
        no = None
        for o in outcomes:
            name = normalize(o.get('name'))
            if 'yes' in name or 'gol' in name or 'si' == name:
                yes = get_price(o)
            elif 'no' in name or 'no gol' in name or 'nogoal' in name or 'non' == name:
                no = get_price(o)
        if yes is not None and no is not None:
            try:
                return 'btts', {'gol': float(yes), 'no_gol': float(no)}
            except Exception:
                return None, None

    return None, None


class TheOddsError(Exception):
    """TheOddsAPI returned an error (invalid key, credits exhausted, HTTP failure)."""


def _cache_get(key):
    hit = _THEODDS_CACHE.get(key)
    if hit is not None and time.monotonic() - hit[0] < ODDS_CACHE_TTL_SECONDS:
        return True, hit[1]
    return False, None


def _cache_set(key, value):
    _THEODDS_CACHE[key] = (time.monotonic(), value)
    return value


def theodds_remaining_credits(api_key):
    """Credits left for api_key, as reported by the last TheOddsAPI response (None if unknown)."""
    return _THEODDS_REMAINING.get(api_key)


def theodds_get(path, api_key, debug=False, **params):
    try:
        resp = requests.get(f'{THEODDS_BASE_URL}{path}', params={'apiKey': api_key, **params},
                            timeout=THEODDS_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise TheOddsError(f'TheOddsAPI non raggiungibile: {exc}') from exc

    remaining = resp.headers.get('x-requests-remaining')
    if remaining is not None:
        _THEODDS_REMAINING[api_key] = remaining
    if not resp.ok:
        try:
            message = resp.json().get('message', '')
        except ValueError:
            message = resp.text[:200]
        raise TheOddsError(f'TheOddsAPI HTTP {resp.status_code}: {message}')

    data = resp.json()
    if debug:
        print(f'TheOddsAPI {path} response:')
        print(data)
    return data


def resolve_theodds_sport_keys(api_key, debug=False):
    found, cached = _cache_get(('sports', api_key))
    if found:
        return cached

    active = [s.get('key', '') for s in theodds_get('/sports', api_key, debug=debug)]
    sport_keys = [k for k in PREFERRED_THEODDS_SPORT_KEYS if k in active]
    if not sport_keys:
        sport_keys = [k for k in active if 'soccer' in k or 'football' in k][:1]
    return _cache_set(('sports', api_key), sport_keys)


def get_theodds_events(sport_key, api_key, debug=False):
    cache_key = ('events', api_key, sport_key)
    found, cached = _cache_get(cache_key)
    if found:
        return cached
    events = theodds_get(f'/sports/{sport_key}/events', api_key, debug=debug, dateFormat='iso')
    return _cache_set(cache_key, events)


def _team_matches(name, api_name):
    name = THEODDS_TEAM_ALIASES.get(name, name)
    return name == api_name or name in api_name or api_name in name


def find_theodds_event(home, away, sport_keys, api_key, debug=False):
    """Return (sport_key, event) for the first event whose teams match home/away, else (None, None)."""
    for sport_key in sport_keys:
        for ev in get_theodds_events(sport_key, api_key, debug=debug):
            h = (ev.get('home_team') or '').strip().lower()
            a = (ev.get('away_team') or '').strip().lower()
            if _team_matches(home, h) and _team_matches(away, a):
                return sport_key, ev
    return None, None


def fetch_theodds_event_odds(event_id, sport_key, api_key, debug=False):
    return theodds_get(
        f'/sports/{sport_key}/events/{event_id}/odds', api_key, debug=debug,
        regions=THEODDS_REGIONS, markets=THEODDS_MARKETS, oddsFormat='decimal', dateFormat='iso',
    )


def read_schedule(path, cos_column=None):
    df = pd.read_excel(path, engine='openpyxl', header=1)
    df.columns = [str(c).strip() for c in df.columns]
    cols = df.columns.tolist()

    match_col = find_column(cols, MATCH_COLUMNS)
    away_col = None
    if match_col:
        idx = cols.index(match_col)
        for candidate in cols[idx + 1:]:
            if candidate not in ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 3', 'Unnamed: 5']:
                if df[candidate].notna().any():
                    away_col = candidate
                    break

    if match_col and away_col:
        df['match'] = normalize_text(df[match_col]) + ' - ' + normalize_text(df[away_col])
    elif match_col:
        df['match'] = normalize_text(df[match_col])
    elif 'Home' in cols and 'Away' in cols:
        df['match'] = normalize_text(df['Home']) + ' - ' + normalize_text(df['Away'])
    elif len(cols) >= 2:
        df['match'] = normalize_text(df[cols[0]]) + ' - ' + normalize_text(df[cols[1]])
    else:
        df['match'] = normalize_text(df[cols[0]])

    date_col = find_column(cols, DATE_COLUMNS)
    if not date_col and 'Giorno/Ora' in cols:
        date_col = 'Giorno/Ora'

    if date_col:
        raw_date = df[date_col]
        try:
            _is_datetime = np.issubdtype(raw_date.dtype, np.datetime64)
        except (TypeError, AttributeError):
            _is_datetime = False
        if _is_datetime:
            df['date'] = raw_date
        elif date_col in DATE_COLUMNS:
            parsed = pd.to_datetime(raw_date, errors='coerce')
            df['date'] = parsed.where(parsed.notna(), normalize_text(raw_date))
        else:
            df['date'] = normalize_text(raw_date)
    else:
        df['date'] = pd.NaT

    cos_col = cos_column or find_column(cols, DEFAULT_COS_COLUMNS)
    if cos_col:
        df['cos'] = normalize_text(df[cos_col])
    else:
        df['cos'] = ''

    # Keep only the first 10 schedule rows; the rest of the sheet is metadata.
    df = df.head(10).copy()
    valid_match = df['match'].astype(str).str.strip().replace(r'\s*-\s*', '', regex=True).str.strip()
    df = df[valid_match.ne('')].copy()
    df.reset_index(drop=True, inplace=True)

    return df


def mandatory_rows(df):
    return df[df['cos'].str.upper() == 'X']


def non_mandatory_rows(df):
    return df[df['cos'].str.upper() != 'X']


def probs_from_row(row, use_odds=False, theodds_key=None, debug_odds=False):
    if use_odds:
        # Try three sources, in order: inline odds columns, TheOddsAPI (if configured)
        prefix = find_odds_prefix(row.index)
        if prefix:
            odds = np.full(len(PRONOSTICI), np.nan, dtype=float)
            for idx, suffix in enumerate(ODDS_SUFFIXES):
                key = prefix + suffix
                if key in row.index:
                    try:
                        odds[idx] = float(row[key])
                    except Exception:
                        odds[idx] = np.nan
            valid = np.isfinite(odds) & (odds > 0)
            if valid.any():
                inv = np.full_like(odds, 1e-6)
                inv[valid] = 1.0 / odds[valid]
                s = inv.sum()
                if s > 0:
                    return inv / s

        # Fallback: try TheOddsAPI if API key present
        key = theodds_key or os.environ.get('THEODDSAPI_KEY')
        if key:
            # Errors are surfaced by the configura odds preview; the draw falls back to uniform probs.
            try:
                p = probs_from_raw_odds(lookup_theodds_match(row.get('match', ''), key, debug=debug_odds)['raw'])
                if p is not None:
                    return p
            except TheOddsError as exc:
                if debug_odds:
                    print('TheOddsAPI exception:', exc)

    keys = ['prob_1', 'prob_X', 'prob_2', 'prob_under', 'prob_over', 'prob_gol', 'prob_no_gol']
    if all(k in row.index for k in keys):
        p = np.array([row[k] for k in keys], dtype=float)
        p = np.clip(p, 0, None)
        s = p.sum()
        return (p / s) if s > 0 else np.ones(len(PRONOSTICI)) / len(PRONOSTICI)

    return np.ones(len(PRONOSTICI)) / len(PRONOSTICI)


def raw_odds_from_row(row, use_odds=False, theodds_key=None, debug_odds=False):
    """Return actual decimal odds per pronostico (NaN where unavailable)."""
    result = np.full(len(PRONOSTICI), np.nan, dtype=float)
    if not use_odds:
        return result
    prefix = find_odds_prefix(row.index)
    if prefix:
        for idx, suffix in enumerate(ODDS_SUFFIXES):
            key = prefix + suffix
            if key in row.index:
                try:
                    v = float(row[key])
                    if v > 0:
                        result[idx] = v
                except Exception:
                    pass
        if np.any(np.isfinite(result)):
            return result
    api_key = theodds_key or os.environ.get('THEODDSAPI_KEY')
    if api_key:
        try:
            raw = lookup_theodds_match(row.get('match', ''), api_key, debug=debug_odds)['raw']
            if raw is not None:
                return raw.copy()
        except TheOddsError as exc:
            if debug_odds:
                print('TheOddsAPI exception:', exc)
    return result


def _best_bookmaker_raw_odds(bookmakers, home, away, debug=False):
    """Pick the bookmaker covering most markets and return its 7 decimal odds (NaN where missing)."""
    candidate = None
    best_score = -1
    for bm in bookmakers:
        h2h = totals = btts = None
        for m in bm.get('markets', []):
            kind, parsed = parse_theodds_market(m, home, away, debug=debug)
            if kind == 'h2h':
                h2h = parsed
            elif kind == 'totals':
                totals = parsed
            elif kind == 'btts':
                btts = parsed
        score = int(h2h is not None) * 10 + int(totals is not None) * 3 + int(btts is not None) * 2
        if score > best_score:
            best_score = score
            candidate = (bm, h2h, totals, btts)
    if candidate is None:
        return None

    bm, h2h, totals, btts = candidate
    raw = np.full(len(PRONOSTICI), np.nan)
    if h2h is not None:
        raw[0:3] = h2h
    if totals is not None:
        raw[3] = totals['under']
        raw[4] = totals['over']
    if btts is not None:
        raw[5] = btts['gol']
        raw[6] = btts['no_gol']
    if debug:
        print('Selected bookmaker:', bm.get('key'), 'raw odds:', raw)
    return raw


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
    if ' - ' in match:
        home, away = [p.strip().lower() for p in match.split(' - ', 1)]
        sport_keys = resolve_theodds_sport_keys(api_key, debug=debug)
        if debug:
            print('TheOddsAPI sport keys:', sport_keys)
        sport_key, ev = find_theodds_event(home, away, sport_keys, api_key, debug=debug)
        if ev is not None:
            ev_home = (ev.get('home_team') or '').strip()
            ev_away = (ev.get('away_team') or '').strip()
            result['event'] = f'{ev_home} - {ev_away}'
            result['event_id'] = ev.get('id')
            event_odds = fetch_theodds_event_odds(ev.get('id'), sport_key, api_key, debug=debug)
            result['raw'] = _best_bookmaker_raw_odds(
                event_odds.get('bookmakers', []), ev_home.lower(), ev_away.lower(), debug=debug,
            )
    return _cache_set(cache_key, result)


def probs_from_raw_odds(raw):
    """Turn 7 decimal odds into probabilities: 1X2 normalised, other markets added as 1/odds, then all normalised."""
    if raw is None or not np.all(np.isfinite(raw[0:3])):
        return None
    full = np.full(len(PRONOSTICI), 1e-6)
    inv_h2h = 1.0 / raw[0:3]
    full[0:3] = inv_h2h / inv_h2h.sum()
    for i in range(3, len(PRONOSTICI)):
        if np.isfinite(raw[i]) and raw[i] > 0:
            full[i] = 1.0 / raw[i]
    return full / full.sum()


def draw_matches(df, k=3, seed=None):
    rng = np.random.default_rng(seed)
    n = len(df)
    if k > n:
        raise ValueError('k larger than number of available matches')
    idx = rng.choice(n, size=k, replace=False)
    return df.iloc[idx]


def filter_by_datetime(df, day=None, time=None):
    dates = df['date'].astype(str).str.lower()
    mask = pd.Series([True] * len(df), index=df.index)
    if day:
        mask &= dates.str.contains(day.strip().lower(), na=False)
    if time:
        mask &= dates.str.contains(time.strip().lower(), na=False)
    return df[mask]


def sample_pronostic(probs, rng):
    return rng.choice(PRONOSTICI, p=probs)


def best_pronostic(probs):
    idx = int(np.nanargmax(probs))
    return PRONOSTICI[idx], float(probs[idx])


def market_probs(probs):
    """Renormalise probs within each market (1X2, U/O, GG/NG), so each reads as that market's real chance."""
    probs = np.asarray(probs, dtype=float)
    out = np.full(len(PRONOSTICI), np.nan)
    for idxs in PRONOSTICI_MARKETS:
        group = probs[list(idxs)]
        total = group.sum()
        if total > 0:
            out[list(idxs)] = group / total
    return out


def best_by_market_prob(probs):
    """Most likely pronostico by within-market probability; (None, None) when probs carry no information."""
    probs = np.asarray(probs, dtype=float)
    if np.allclose(probs, 1.0 / len(PRONOSTICI)):
        return None, None
    mp = market_probs(probs)
    idx = int(np.nanargmax(mp))
    return PRONOSTICI[idx], float(mp[idx])


def best_by_raw_odds(raw_odds):
    """Highest real bookmaker odds; (None, None) when no odds are available."""
    raw = np.asarray([np.nan if v is None else v for v in raw_odds], dtype=float)
    if not np.any(np.isfinite(raw)):
        return None, None
    idx = int(np.nanargmax(raw))
    return PRONOSTICI[idx], float(raw[idx])


def best_by_odds(probs):
    """Best by maximum odds (highest payout, lowest probability)."""
    idx = int(np.nanargmin(probs))
    odds = 1.0 / probs[idx]
    return PRONOSTICI[idx], float(odds)


def best_by_ev(probs):
    """Best by EV score: log(odds) * prob, balancing odds and probability."""
    ev_scores = np.log(1.0 / np.clip(probs, 1e-6, 1)) * probs
    idx = int(np.nanargmax(ev_scores))
    return PRONOSTICI[idx], float(ev_scores[idx])


def format_date(value):
    if pd.isna(value):
        return ''
    if isinstance(value, pd.Timestamp):
        return value.strftime('%Y-%m-%d')
    return str(value)


def interactive_selection(matches):
    """Allow user to select pronostics for each match. Returns list of (match_info, selected_pronostic) tuples."""
    selections = []
    
    print("\n" + "="*100)
    print("INTERACTIVE MODE: Seleziona il pronostico per ogni partita")
    print("="*100)
    
    for idx, m in enumerate(matches, 1):
        print(f"\n[{idx}] {m['date']} | {m['match']}")
        print(f"    Sampled: {m['sample']}")
        print(f"    Best Prob: {m['best_prob']} ({m['best_prob_value']:.2f})")
        print(f"    Best Odds: {m['best_odds']} ({m['best_odds_value']:.2f})")
        print(f"    Best EV: {m['best_ev']} ({m['best_ev_value']:.3f})")
        print(f"    Opzioni disponibili: {', '.join(PRONOSTICI)}")
        
        while True:
            choice = input(f"    Scegli il pronostico (o premi invio per Best EV '{m['best_ev']}'): ").strip()
            
            if choice == '':
                selected = m['best_ev']
                print(f"    ✓ Selezionato: {selected} (Best EV)")
                break
            elif choice in PRONOSTICI:
                selected = choice
                print(f"    ✓ Selezionato: {selected}")
                break
            else:
                print(f"    ✗ Opzione non valida. Inserisci uno di: {', '.join(PRONOSTICI)}")
        
        selections.append((m, selected))
    
    return selections


def generate_whatsapp_message(selections, player_num=1):
    """Generate a WhatsApp formatted message from selections."""
    lines = [
        f"📋 SCHEDELLA #{player_num}",
        f"{'='*40}",
        ""
    ]
    
    for match_info, pronostico in selections:
        date = match_info['date']
        match = match_info['match']
        lines.append(f"• {date} - {match}")
        lines.append(f"  → {pronostico}")
        lines.append("")
    
    lines.append(f"{'='*40}")
    lines.append(f"Generated on {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}")
    
    return "\n".join(lines)


def calculate_parlay_combinations(matches, min_multiplier=10, max_multiplier=None, limit=30):
    """Calculate parlay combinations in [min_multiplier, max_multiplier] range.

    Returns sorted list of tuples: (total_multiplier, ev_score, [pronostico1, ...])
    Primary sort: multiplier ascending (closest to target first).
    Secondary sort: ev_score descending (best EV among same-mult combos).
    """
    import itertools
    import math

    _MARKET_GROUPS = [[0, 1, 2], [0, 1, 2], [0, 1, 2], [3, 4], [3, 4], [5, 6], [5, 6]]

    def _market_prob(raw_list, pron_idx):
        group = _MARKET_GROUPS[pron_idx]
        inv = []
        for gi in group:
            ro = float(raw_list[gi]) if gi < len(raw_list) else float('nan')
            inv.append(1.0 / ro if (ro > 0 and ro == ro) else 0.0)
        s = sum(inv)
        return inv[group.index(pron_idx)] / s if s > 0 else 0.0

    match_prons, match_odds_vals, match_pidxs = [], [], []
    for m in matches:
        prons, odds, pidxs = [], [], []
        raw = m.get('raw_odds', [])
        for i, pron in enumerate(PRONOSTICI):
            raw_o = float(raw[i]) if i < len(raw) else float('nan')
            prob = m['probs'][i]
            if raw_o > 0 and raw_o == raw_o:
                prons.append(pron); odds.append(raw_o); pidxs.append(i)
            elif prob > 0:
                prons.append(pron); odds.append(1.0 / prob); pidxs.append(i)
        match_prons.append(prons)
        match_odds_vals.append(odds)
        match_pidxs.append(pidxs)

    combinations = []
    for combo_indices in itertools.product(*[range(len(m)) for m in match_prons]):
        total_mult = 1.0
        ev_score = 0.0
        pronostici = []
        for mi, ci in enumerate(combo_indices):
            quota = match_odds_vals[mi][ci]
            pron_idx = match_pidxs[mi][ci]
            raw = matches[mi].get('raw_odds', [])
            p = _market_prob(raw, pron_idx)
            total_mult *= quota
            if quota > 1 and p > 0:
                ev_score += math.log(quota) * p
            pronostici.append(match_prons[mi][ci])

        if total_mult < min_multiplier:
            continue
        if max_multiplier is not None and total_mult > max_multiplier:
            continue
        combinations.append((total_mult, ev_score, pronostici))

    # closest to target first; best EV as tiebreaker
    combinations.sort(key=lambda x: (x[0], -x[1]))
    return combinations[:limit]


def display_parlay_options(matches, min_multiplier=10, max_multiplier=None):
    """Display parlay combinations in [min_multiplier, max_multiplier] range."""
    combinations = calculate_parlay_combinations(matches, min_multiplier=min_multiplier, max_multiplier=max_multiplier)

    if not combinations:
        rng_str = f"{min_multiplier}x"
        if max_multiplier:
            rng_str += f" – {max_multiplier}x"
        print(f"\n❌ Nessuna combinazione nel range {rng_str}")
        return

    rng_label = f"{min_multiplier}x"
    if max_multiplier:
        rng_label += f" – {max_multiplier}x"

    print(f"\n{'='*100}")
    print(f"🎯 COMBINAZIONI {rng_label} (ordinate per moltiplicatore, poi EV)")
    print(f"{'='*100}")
    print(f"Trovate {len(combinations)} combinazioni (mostrate le prime 30):\n")

    match_names = [m['match'].split(' - ')[0][:10] for m in matches]
    table_data = []
    for idx, (mult, ev, pronostici) in enumerate(combinations[:30], 1):
        combo_str = ' + '.join(f"{match_names[i]}:{pronostici[i]}" for i in range(len(matches)))
        table_data.append([f"{idx}", f"{mult:.2f}x", f"{ev:.3f}", combo_str])

    headers = ['#', 'Moltiplicatore', 'EV Score', 'Combinazione']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))

    best_mult, best_ev, best_combo = combinations[0]
    print(f"\n🏆 PIÙ VICINA AL TARGET {min_multiplier}x:")
    print(f"   Moltiplicatore: {best_mult:.2f}x")
    print(f"   EV Score:       {best_ev:.3f}")
    print(f"   Pronostici:     {' + '.join(best_combo)}")
    print()


def run(file, players=1, per_player=3, allow_4th=False, only_mandatory=False, cos_column=None, seed=None, out=None, dump=False, use_odds=False, theodds_key=None, debug_odds=False, interactive=False, parlay_target=None, parlay_max=None, filter_day=None, filter_time=None):
    path = Path(file)
    if not path.exists():
        raise FileNotFoundError(f'File not found: {file}')

    if dump:
        raw = pd.read_excel(path, engine='openpyxl', header=None)
        print('Raw sheet preview:')
        print(raw.head(15).to_string(index=False, header=False))
        print('\nParsed schedule:')
        df = read_schedule(path, cos_column=cos_column)
        print(df.to_string(index=False))
        return

    if use_odds and not (theodds_key or os.environ.get('THEODDSAPI_KEY')):
        print('Warning: --use-odds è attivo, ma THEODDSAPI_KEY non è impostata e non è stata fornita --theodds-key. Verranno usate probabilità uniformi.')

    if debug_odds:
        print('Debug odds mode enabled. API responses will be printed.')

    df = read_schedule(path, cos_column=cos_column)
    rng = np.random.default_rng(seed)

    # Day/time filter mode: bypass COS logic entirely
    if filter_day or filter_time:
        filtered = filter_by_datetime(df, filter_day, filter_time)
        if filtered.empty:
            parts = [p for p in [filter_day, filter_time] if p]
            print(f"Nessuna partita trovata per il filtro: {' '.join(parts)}")
            return
        print(f"Partite filtrate ({len(filtered)}): {filter_day or ''} {filter_time or ''}".strip())
        results = []
        player_result = {'player': 1, 'matches': []}
        for _, row in filtered.iterrows():
            probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
            raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
            pron = sample_pronostic(probs, rng)
            best_pron, best_prob = best_pronostic(probs)
            odds_pron, odds_val = best_by_odds(probs)
            ev_pron, ev_val = best_by_ev(probs)
            player_result['matches'].append({
                'match': row['match'],
                'date': format_date(row['date']),
                'cos': row['cos'],
                'required': False,
                'probs': probs.tolist(),
                'raw_odds': raw_odds.tolist(),
                'sample': pron,
                'best_prob': best_pron,
                'best_prob_value': best_prob,
                'best_odds': odds_pron,
                'best_odds_value': odds_val,
                'best_ev': ev_pron,
                'best_ev_value': ev_val,
            })
        results.append(player_result)
        _display_and_interact(results, interactive=interactive, parlay_target=parlay_target, parlay_max=parlay_max, out=out)
        return

    mandatory = mandatory_rows(df)
    optional = non_mandatory_rows(df)

    if only_mandatory:
        print('Mandatory rows (COS = X):')
        results = []
        for _, row in mandatory.iterrows():
            match_info = {
                'match': row['match'],
                'date': format_date(row['date']),
                'cos': row['cos'],
            }
            results.append(match_info)
            print(f" - {match_info['date']} | {match_info['match']} | COS={match_info['cos']}")
        if out:
            import json
            Path(out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
        return

    results = []
    for p in range(players):
        if len(mandatory) > 0:
            selected = mandatory.copy()
            if per_player > len(selected):
                remaining_needed = per_player - len(selected)
                if len(optional) > 0:
                    extra = draw_matches(optional, k=min(remaining_needed, len(optional)), seed=rng.integers(0, 2**31))
                    selected = pd.concat([selected, extra], ignore_index=True)
        else:
            selected = draw_matches(df, k=per_player, seed=rng.integers(0, 2**31))

        if len(mandatory) > per_player:
            print(f'Warning: {len(mandatory)} mandatory rows found, exceeding per-player count {per_player}. All mandatory rows will be included.')

        extras = None
        if allow_4th:
            remaining_optional = optional.drop(selected.index, errors='ignore')
            if len(remaining_optional) > 0:
                extras = draw_matches(remaining_optional, k=1, seed=rng.integers(0, 2**31))

        player_result = {'player': p + 1, 'matches': []}
        for _, row in selected.iterrows():
            probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
            raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
            pron = sample_pronostic(probs, rng)
            best_pron, best_prob = best_pronostic(probs)
            odds_pron, odds_val = best_by_odds(probs)
            ev_pron, ev_val = best_by_ev(probs)
            player_result['matches'].append({
                'match': row['match'],
                'date': format_date(row['date']),
                'cos': row['cos'],
                'required': row['cos'].upper() == 'X',
                'probs': probs.tolist(),
                'raw_odds': raw_odds.tolist(),
                'sample': pron,
                'best_prob': best_pron,
                'best_prob_value': best_prob,
                'best_odds': odds_pron,
                'best_odds_value': odds_val,
                'best_ev': ev_pron,
                'best_ev_value': ev_val,
            })
        if extras is not None:
            for _, row in extras.iterrows():
                probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
                raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key, debug_odds=debug_odds)
                pron = sample_pronostic(probs, rng)
                best_pron, best_prob = best_pronostic(probs)
                odds_pron, odds_val = best_by_odds(probs)
                ev_pron, ev_val = best_by_ev(probs)
                player_result['matches'].append({
                    'match': row['match'],
                    'date': format_date(row['date']),
                    'cos': row['cos'],
                    'required': row['cos'].upper() == 'X',
                    'probs': probs.tolist(),
                    'raw_odds': raw_odds.tolist(),
                    'sample': pron,
                    'best_prob': best_pron,
                    'best_prob_value': best_prob,
                    'best_odds': odds_pron,
                    'best_odds_value': odds_val,
                    'best_ev': ev_pron,
                    'best_ev_value': ev_val,
                    'extra': True,
                })
        results.append(player_result)

    _display_and_interact(results, interactive=interactive, parlay_target=parlay_target, parlay_max=parlay_max, out=out)


def _display_and_interact(results, interactive=False, parlay_target=None, parlay_max=None, out=None):
    for pl in results:
        print(f"\n{'='*150}")
        print(f"Player {pl['player']}")
        print(f"{'='*150}")

        table_data = []
        for m in pl['matches']:
            extra = '(4th)' if m.get('extra', False) else ''
            required = '[req]' if m.get('required', False) else ''
            flags = f"{extra} {required}".strip()

            probs_line1 = ' | '.join(f"{PRONOSTICI[i]}:{m['probs'][i]:.2f}" for i in range(3))
            probs_line2 = ' | '.join(f"{PRONOSTICI[i]}:{m['probs'][i]:.2f}" for i in range(3, len(PRONOSTICI)))
            probs_str = f"{probs_line1}\n{probs_line2}"

            table_data.append([
                m['date'],
                m['match'],
                flags,
                m['sample'],
                f"{m['best_prob']}\n({m['best_prob_value']:.2f})",
                f"{m['best_odds']}\n({m['best_odds_value']:.2f})",
                f"{m['best_ev']}\n({m['best_ev_value']:.3f})",
                probs_str,
            ])

        headers = ['Date', 'Match', 'Flags', 'Sampled', 'Best Prob\n(value)', 'Best Odds\n(quota)', 'Best EV\n(score)', 'Probabilities']
        print(tabulate(table_data, headers=headers, tablefmt='grid'))
        print()

        if interactive:
            selections = interactive_selection(pl['matches'])
            whatsapp_msg = generate_whatsapp_message(selections, player_num=pl['player'])

            print("\n" + "="*100)
            print("MESSAGGIO WHATSAPP")
            print("="*100)
            print(whatsapp_msg)
            print("="*100)
            print("\n✓ Messaggio copiato negli appunti (pronto per incollare su WhatsApp)")

            try:
                import subprocess
                process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                process.communicate(whatsapp_msg.encode('utf-8'))
            except Exception:
                pass

        if parlay_target:
            display_parlay_options(pl['matches'], min_multiplier=parlay_target, max_multiplier=parlay_max)

    if out:
        import json
        Path(out).write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Schedella draw utility')
    parser.add_argument('--file', '-f', required=True, help='Excel schedule file (weekly)')
    parser.add_argument('--players', type=int, default=1)
    parser.add_argument('--per-player', type=int, default=3)
    parser.add_argument('--allow-4th', action='store_true')
    parser.add_argument('--only-mandatory', action='store_true', help='Print only rows where COS is marked with X')
    parser.add_argument('--dump', action='store_true', help='Print raw and parsed schedule data and exit')
    parser.add_argument('--use-odds', action='store_true', help='Use odds columns to derive implied probabilities')
    parser.add_argument('--cos-column', '--column', dest='cos_column', help='Column name for mandatory match selection (COS). Alias: --column')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--out', help='Optional output JSON file')
    parser.add_argument('--theodds-key', help='TheOddsAPI api key to use for odds lookup')
    parser.add_argument('--debug-odds', action='store_true', help='Print TheOddsAPI responses and matching details')
    parser.add_argument('--interactive', '-i', action='store_true', help='Interactive mode: select pronostics manually and generate WhatsApp message')
    parser.add_argument('--parlay-target', type=float, default=None, help='Minimum multiplier for parlay combinations (e.g. 10)')
    parser.add_argument('--parlay-max', type=float, default=None, help='Maximum multiplier for parlay combinations (e.g. 30)')
    parser.add_argument('--filter-day', help='Filter matches by day of week in date column (e.g. domenica)')
    parser.add_argument('--filter-time', help='Filter matches by time in date column (e.g. 20:45)')
    args = parser.parse_args()
    run(
        args.file,
        players=args.players,
        per_player=args.per_player,
        allow_4th=args.allow_4th,
        only_mandatory=args.only_mandatory,
        cos_column=args.cos_column,
        seed=args.seed,
        out=args.out,
        dump=args.dump,
        use_odds=args.use_odds,
        theodds_key=args.theodds_key,
        debug_odds=args.debug_odds,
        interactive=args.interactive,
        parlay_target=args.parlay_target,
        parlay_max=args.parlay_max,
        filter_day=args.filter_day,
        filter_time=args.filter_time,
    )

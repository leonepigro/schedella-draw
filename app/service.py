"""
Service layer wrapping src/schedella.py logic for use by the FastAPI web app.

Key functions:
  prepare_session(excel_bytes, filename, params) -> dict
  roll_pick(match_data, seed=None) -> dict
"""

import io
import math
import tempfile
import os
import numpy as np

from src.schedella import (
    PRONOSTICI,
    read_schedule,
    probs_from_row,
    raw_odds_from_row,
    sample_pronostic,
    best_pronostic,
    best_by_ev,
    best_by_odds,
    filter_by_datetime,
    mandatory_rows,
    non_mandatory_rows,
    draw_matches,
    format_date,
)


def _row_to_match_dict(row, probs, raw_odds):
    """Convert a DataFrame row + pre-computed probs/odds into the API match dict."""
    ev_pron, ev_val = best_by_ev(probs)
    prob_pron, prob_val = best_pronostic(probs)
    odds_pron, odds_val = best_by_odds(probs)

    available_pronostici = []
    for i, pron in enumerate(PRONOSTICI):
        ro = raw_odds[i]
        available_pronostici.append({
            "pron": pron,
            "idx": i,
            "odds": float(ro) if (ro == ro and not math.isnan(float(ro))) else None,
        })

    return {
        "match_name": str(row["match"]),
        "match_date": format_date(row["date"]),
        "probs": [float(p) for p in probs],
        "raw_odds": [None if (isinstance(ro, float) and ro != ro) else float(ro) for ro in raw_odds],
        "available_pronostici": available_pronostici,
        "best_ev": ev_pron,
        "best_ev_value": float(ev_val),
        "best_prob": prob_pron,
        "best_prob_value": float(prob_val),
        "best_odds": odds_pron,
        "best_odds_value": float(odds_val),
    }


def _select_matches(df, params, player_rng):
    """
    Select a subset of rows for a single player.

    Priority:
    1. If filter_day / filter_time is set: return all rows matching the filter.
    2. If cos_column is set (or the df already has COS data): mandatory first, fill with optional.
    3. Otherwise: random draw of per_player rows.

    If allow_4th is True, one extra optional match is appended (when possible).
    """
    filter_day = params.get("filter_day")
    filter_time = params.get("filter_time")
    per_player = params.get("per_player", 3)
    allow_4th = params.get("allow_4th", False)

    if filter_day or filter_time:
        selected = filter_by_datetime(df, filter_day, filter_time)
        return selected, None  # no extras in filter mode

    # COS logic only when selection_mode == "cos" is explicit
    if params.get("selection_mode") != "cos" and not params.get("cos_column"):
        df = df.copy()
        df["cos"] = ""

    mandatory = mandatory_rows(df)
    optional = non_mandatory_rows(df)

    seed_val = int(player_rng.integers(0, 2**31))

    if len(mandatory) > 0:
        selected = mandatory.copy()
        if per_player > len(selected) and len(optional) > 0:
            remaining_needed = per_player - len(selected)
            extra_opt = draw_matches(
                optional,
                k=min(remaining_needed, len(optional)),
                seed=seed_val,
            )
            import pandas as pd
            selected = pd.concat([selected, extra_opt], ignore_index=True)
    else:
        k = min(per_player, len(df))
        selected = draw_matches(df, k=k, seed=seed_val)

    # Optional 4th match
    extras = None
    if allow_4th:
        remaining_optional = optional.drop(selected.index, errors="ignore")
        if len(remaining_optional) > 0:
            extras = draw_matches(
                remaining_optional,
                k=1,
                seed=int(player_rng.integers(0, 2**31)),
            )

    return selected, extras


def prepare_session(excel_bytes: bytes, filename: str, params: dict) -> dict:
    """
    Parse the uploaded Excel schedule and return a structured session dict.

    Parameters
    ----------
    excel_bytes : bytes
        Raw content of the uploaded .xlsx file.
    filename : str
        Original filename (used for display / logging).
    params : dict
        Session parameters. Recognised keys:
          players       (int, default 1)
          per_player    (int, default 3)
          allow_4th     (bool, default False)
          cos_column    (str | None)
          seed          (int | None)
          filter_day    (str | None)
          filter_time   (str | None)
          use_odds      (bool, default False)
          theodds_key   (str | None)

    Returns
    -------
    dict with shape::

        {
            "players": [
                {
                    "player_num": 1,
                    "matches": [
                        {
                            "match_name": str,
                            "match_date": str,
                            "probs": list[float],        # length 7
                            "raw_odds": list[float],     # length 7
                            "available_pronostici": [...],
                            "best_ev": str,
                            "best_prob": str,
                            ...
                        }
                    ]
                }
            ],
            "filename": str
        }
    """
    # Write bytes to a NamedTemporaryFile so read_schedule (which takes a path) can read it
    suffix = os.path.splitext(filename)[-1] or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(excel_bytes)
        tmp_path = tmp.name

    try:
        cos_column = params.get("cos_column")
        df = read_schedule(tmp_path, cos_column=cos_column)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Participant names from column take priority over numeric players count
    participant_column = params.get("participant_column")
    participant_names = []
    if participant_column and participant_column in df.columns:
        vals = df[participant_column].dropna().astype(str).str.strip()
        participant_names = [v for v in vals.unique().tolist() if v and v.lower() not in ("nan", "")]

    num_players = len(participant_names) if participant_names else params.get("players", 1)
    seed = params.get("seed")
    use_odds = params.get("use_odds", False)
    theodds_key = params.get("theodds_key")

    rng = np.random.default_rng(seed)

    players_out = []
    for p_idx in range(num_players):
        selected, extras = _select_matches(df, params, rng)

        matches_out = []
        for _, row in selected.iterrows():
            probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
            raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
            matches_out.append(_row_to_match_dict(row, probs, raw_odds))

        if extras is not None:
            for _, row in extras.iterrows():
                probs = probs_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
                raw_odds = raw_odds_from_row(row, use_odds=use_odds, theodds_key=theodds_key)
                m = _row_to_match_dict(row, probs, raw_odds)
                m["extra"] = True
                matches_out.append(m)

        pname = participant_names[p_idx] if p_idx < len(participant_names) else None
        players_out.append({
            "player_num": p_idx + 1,
            "participant_name": pname,
            "matches": matches_out,
        })

    return {
        "players": players_out,
        "filename": filename,
    }


def roll_pick(match_data: dict, seed=None) -> dict:
    """
    Randomly pick a pronostico for a single match.

    Parameters
    ----------
    match_data : dict
        Must contain:
          probs     : list[float]  — length-7 probability array
          raw_odds  : list[float]  — length-7 raw decimal odds (NaN where unavailable)
    seed : int | None
        RNG seed for determinism.

    Returns
    -------
    dict::

        {
            "pronostico": str,
            "raw_odds": float | None,
            "ev_score": float,
            "best_ev": str,
            "face_idx": int,
        }
    """
    probs = np.array(match_data["probs"], dtype=float)
    raw_odds_arr = match_data.get("raw_odds", [float("nan")] * len(PRONOSTICI))

    rng = np.random.default_rng(seed)
    pronostico = sample_pronostic(probs, rng)
    face_idx = PRONOSTICI.index(pronostico)

    # EV score for the picked pronostico: log(1/p) * p
    p = float(probs[face_idx])
    ev_score = math.log(1.0 / max(p, 1e-6)) * p

    # Best EV recommendation
    best_ev_pron, _ = best_by_ev(probs)

    # Raw odds for the picked pronostico
    _ro_val = raw_odds_arr[face_idx] if face_idx < len(raw_odds_arr) else None
    if _ro_val is None:
        ro_out = None
    else:
        ro = float(_ro_val)
        ro_out = None if math.isnan(ro) else ro

    return {
        "pronostico": pronostico,
        "raw_odds": ro_out,
        "ev_score": ev_score,
        "best_ev": best_ev_pron,
        "face_idx": face_idx,
    }

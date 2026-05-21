import io
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from app.service import prepare_session, roll_pick


def _make_excel_bytes():
    """Create minimal valid schedule Excel in memory."""
    df = pd.DataFrame({
        "Partita": ["Milan", "Juve", "Roma"],
        "Away":    ["Inter", "Napoli", "Lazio"],
        "Giorno/Ora": ["domenica 20:45", "domenica 20:45", "sabato 18:00"],
        "Cos":     ["X", "", ""],
    })
    # schedella.py uses header=1, so we need a blank row 0
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([[""] * len(df.columns)]).to_excel(w, index=False, header=False)
        df.to_excel(w, index=False, startrow=1)
    return buf.getvalue()


def test_prepare_session_returns_matches():
    data = _make_excel_bytes()
    result = prepare_session(data, "test.xlsx", {"per_player": 3, "players": 1})
    assert "players" in result
    assert len(result["players"]) == 1
    matches = result["players"][0]["matches"]
    assert len(matches) >= 1
    match = matches[0]
    assert "match_name" in match
    assert "probs" in match
    assert "raw_odds" in match
    assert "best_ev" in match
    assert len(match["probs"]) == 7


def test_prepare_session_filter_day():
    data = _make_excel_bytes()
    result = prepare_session(data, "test.xlsx", {
        "filter_day": "domenica", "filter_time": "20:45"
    })
    matches = result["players"][0]["matches"]
    assert len(matches) == 2


def test_roll_pick_returns_valid_pronostico():
    from src.schedella import PRONOSTICI
    match_data = {
        "probs": [1/7] * 7,
        "raw_odds": [float("nan")] * 7,
    }
    result = roll_pick(match_data, seed=42)
    assert result["pronostico"] in PRONOSTICI
    assert isinstance(result["ev_score"], float)


def test_roll_pick_deterministic_with_seed():
    match_data = {"probs": [1/7] * 7, "raw_odds": [float("nan")] * 7}
    r1 = roll_pick(match_data, seed=99)
    r2 = roll_pick(match_data, seed=99)
    assert r1["pronostico"] == r2["pronostico"]

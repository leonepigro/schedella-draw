import io
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from app.service import prepare_session, roll_pick, get_excel_preview
from tests.test_routes import _excel_bytes


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
    assert "best_prob" in match and "best_odds" in match
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


def test_excel_read_once_for_preview_and_session(monkeypatch):
    import app.service as svc
    svc._RAW_EXCEL_CACHE.clear()
    calls = []
    real = svc.pd.read_excel
    monkeypatch.setattr(svc.pd, "read_excel", lambda *a, **k: calls.append(1) or real(*a, **k))
    data = _excel_bytes()
    svc.get_excel_preview(data, "t.xlsx")
    svc.prepare_session(data, "t.xlsx", {"players": 1, "per_player": 3})
    assert len(calls) == 1


def test_raw_excel_cache_not_mutated():
    import app.service as svc
    data = _excel_bytes()
    first = svc.read_raw_excel(data)
    first["match"] = "x"
    assert "match" not in svc.read_raw_excel(data).columns


def test_excel_preview_unchanged_shape():
    p = get_excel_preview(_excel_bytes(), "t.xlsx")
    assert "Partita" in p["dropdown_columns"]
    assert [m["name"] for m in p["matches"]][:2] == ["Milan - Inter", "Juve - Napoli"]


def test_raw_excel_cache_evicts_oldest():
    import app.service as svc
    svc._RAW_EXCEL_CACHE.clear()
    first = _excel_bytes()
    svc.read_raw_excel(first)
    for i in range(svc.RAW_EXCEL_CACHE_MAX):
        svc.read_raw_excel(_excel_bytes_variant(i))
    assert len(svc._RAW_EXCEL_CACHE) == svc.RAW_EXCEL_CACHE_MAX
    import hashlib
    assert hashlib.sha1(first).hexdigest() not in svc._RAW_EXCEL_CACHE
    assert not svc.read_raw_excel(_excel_bytes_variant(0)).empty


def _excel_bytes_variant(i):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([[""] * 2]).to_excel(w, index=False, header=False)
        pd.DataFrame({"Partita": [f"A{i}"], "Away": [f"B{i}"]}).to_excel(w, index=False, startrow=1)
    return buf.getvalue()

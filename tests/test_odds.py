import math
import pytest
from unittest.mock import patch, MagicMock

from src import schedella
from app.service import get_odds_preview


EVENTS = [
    {"id": "ev1", "home_team": "Napoli", "away_team": "AS Roma"},
    {"id": "ev2", "home_team": "Inter Milan", "away_team": "Cagliari"},
    {"id": "ev3", "home_team": "AC Milan", "away_team": "Cagliari"},
]

EVENT_ODDS = {
    "bookmakers": [{
        "key": "bet365",
        "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Napoli", "price": 2.83},
                {"name": "Draw", "price": 3.45},
                {"name": "AS Roma", "price": 2.56},
            ]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "price": 1.92},
                {"name": "Under", "price": 1.97},
            ]},
            {"key": "btts", "outcomes": [
                {"name": "Yes", "price": 1.69},
                {"name": "No", "price": 2.23},
            ]},
        ],
    }],
}


def _resp(data, status=200, remaining="480"):
    r = MagicMock()
    r.ok = status < 400
    r.status_code = status
    r.headers = {"x-requests-remaining": remaining}
    r.json.return_value = data
    return r


def _fake_get(url, params=None, timeout=None):
    if url.endswith("/sports"):
        return _resp([{"key": "soccer_italy_serie_a"}])
    if url.endswith("/events"):
        return _resp(EVENTS)
    if "/events/" in url and url.endswith("/odds"):
        return _resp(EVENT_ODDS)
    raise AssertionError(f"unexpected url {url}")


@pytest.fixture(autouse=True)
def clear_cache():
    schedella._THEODDS_CACHE.clear()
    schedella._THEODDS_REMAINING.clear()
    yield
    schedella._THEODDS_CACHE.clear()


def test_lookup_returns_all_seven_odds():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        found = schedella.lookup_theodds_match("Napoli - Roma", "k")
    assert found["event"] == "Napoli - AS Roma"
    assert list(found["raw"]) == [2.83, 3.45, 2.56, 1.97, 1.92, 1.69, 2.23]


def test_lookup_is_cached():
    with patch.object(schedella.requests, "get", side_effect=_fake_get) as get:
        schedella.lookup_theodds_match("Napoli - Roma", "k")
        calls = get.call_count
        schedella.lookup_theodds_match("Napoli - Roma", "k")
    assert get.call_count == calls


def test_milan_alias_does_not_match_inter():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        sport_key, ev = schedella.find_theodds_event("milan", "cagliari", ["soccer_italy_serie_a"], "k")
    assert ev["id"] == "ev3"


def test_unknown_match_returns_none():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        found = schedella.lookup_theodds_match("Bologna - Pisa", "k")
    assert found == {"raw": None, "event": None, "event_id": None}


def test_probs_from_raw_odds_not_uniform():
    raw = schedella.np.array([1.35, 5.75, 8.03, 2.03, 1.87, 1.68, 2.26])
    p = schedella.probs_from_raw_odds(raw)
    assert math.isclose(p.sum(), 1.0)
    assert p[0] > p[1] > p[2]


def test_api_error_is_raised_with_message():
    with patch.object(schedella.requests, "get",
                      return_value=_resp({"message": "API key is not valid"}, status=401)):
        with pytest.raises(schedella.TheOddsError, match="401.*not valid"):
            schedella.lookup_theodds_match("Napoli - Roma", "bad")


def test_odds_preview_reports_results_and_credits():
    with patch.object(schedella.requests, "get", side_effect=_fake_get):
        out = get_odds_preview(["Napoli - Roma", "Bologna - Pisa"], "k")
    assert out["error"] is None
    assert out["remaining"] == "480"
    assert out["results"][0]["odds"][0] == 2.83
    assert out["results"][1]["odds"] is None


def test_odds_preview_without_key(monkeypatch):
    monkeypatch.delenv("THEODDSAPI_KEY", raising=False)
    out = get_odds_preview(["Napoli - Roma"], None)
    assert out["error"] and out["results"] == []


def test_odds_preview_surfaces_api_error():
    with patch.object(schedella.requests, "get",
                      return_value=_resp({"message": "Usage quota has been reached"}, status=401, remaining="0")):
        out = get_odds_preview(["Napoli - Roma"], "k")
    assert "quota" in out["error"]
    assert out["remaining"] == "0"


def test_best_by_market_prob_uses_within_market_share():
    raw = schedella.np.array([2.83, 3.45, 2.56, 1.97, 1.92, 1.69, 2.23])
    pron, p = schedella.best_by_market_prob(schedella.probs_from_raw_odds(raw))
    assert pron == "gol"
    assert 0.55 < p < 0.58  # ~57% inside GG/NG, not ~19% across all 7


def test_best_by_market_prob_none_when_uniform():
    assert schedella.best_by_market_prob([1 / 7] * 7) == (None, None)


def test_best_by_raw_odds_returns_real_bookmaker_odds():
    assert schedella.best_by_raw_odds([2.83, 3.45, 2.56, 1.97, 1.92, 1.69, 2.23]) == ("X", 3.45)
    assert schedella.best_by_raw_odds([None] * 7) == (None, None)
    assert schedella.best_by_raw_odds([float("nan")] * 7) == (None, None)


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

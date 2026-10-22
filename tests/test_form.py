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


def test_find_team_empty_name_is_none():
    table = STANDINGS["standings"][0]["table"]
    assert form_data.find_team("", table) is None
    assert form_data.find_team("   ", table) is None


def test_find_team_ambiguous_substring_is_none():
    # "mila" is a substring of both "AC Milan"/"Milan" and "FC Internazionale Milano": refuse to guess
    table = STANDINGS["standings"][0]["table"]
    assert form_data.find_team("mila", table) is None


def test_prepare_session_stops_form_calls_after_error(monkeypatch):
    from tests.test_service import _make_excel_bytes
    monkeypatch.setenv("FOOTBALLDATA_KEY", "k")
    with patch.object(form_data.requests, "get",
                      return_value=_resp({"message": "Too many requests"}, status=429)) as get:
        result = service.prepare_session(_make_excel_bytes(), "t.xlsx", {"per_player": 3, "players": 3})
    assert all(m["form"] is None for p in result["players"] for m in p["matches"])
    assert get.call_count == 1  # first failure disables form lookups for the rest of the draw

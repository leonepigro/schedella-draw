import pytest
from app.db import (
    init_db, insert_session, insert_schedella, insert_pick,
    update_pick_pronostico, insert_result, get_session,
    get_picks_for_schedella, get_all_schedelle, get_stats,
)

def test_init_db_creates_tables(db_path):
    from app.db import get_connection
    with get_connection(db_path) as con:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert tables >= {"session", "schedella", "pick", "result"}

def test_insert_and_get_session(db_path):
    sid = insert_session(db_path, "test.xlsx", {"players": 1})
    s = get_session(db_path, sid)
    assert s["excel_filename"] == "test.xlsx"
    assert s["params"]["players"] == 1

def test_insert_schedella_and_picks(db_path):
    sid = insert_session(db_path, "test.xlsx", {})
    schid = insert_schedella(db_path, sid, player_num=1)
    insert_pick(db_path, schid, "Milan - Inter", "2026-05-25", None, 1.9, 0.45, "gol", 0)
    picks = get_picks_for_schedella(db_path, schid)
    assert len(picks) == 1
    assert picks[0]["pronostico"] is None
    assert picks[0]["match_name"] == "Milan - Inter"

def test_update_pick_pronostico(db_path):
    sid = insert_session(db_path, "test.xlsx", {})
    schid = insert_schedella(db_path, sid, 1)
    pick_id = insert_pick(db_path, schid, "Milan - Inter", "", None, 1.9, 0.45, "gol", 0)
    update_pick_pronostico(db_path, pick_id, "gol")
    picks = get_picks_for_schedella(db_path, schid)
    assert picks[0]["pronostico"] == "gol"

def test_insert_result(db_path):
    sid = insert_session(db_path, "test.xlsx", {})
    schid = insert_schedella(db_path, sid, 1)
    insert_result(db_path, schid, "won", 12.5, 5.0)
    rows = get_all_schedelle(db_path)
    assert rows[0]["outcome"] == "won"
    assert rows[0]["profit"] == pytest.approx(12.5 * 5.0 - 5.0)

def test_get_stats_empty(db_path):
    stats = get_stats(db_path)
    assert stats["total"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["roi"] == 0.0


from app.db import add_odds_snapshot, get_first_odds_snapshot


def test_snapshot_first_and_dedup(db_path):
    assert get_first_odds_snapshot(db_path, "ev1") is None
    assert add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.95, 3.4, 2.5, None, None, None, None])
    assert not add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.95, 3.4, 2.5, None, None, None, None])
    assert add_odds_snapshot(db_path, "ev1", "Napoli - AS Roma", [2.83, 3.45, 2.56, None, None, None, None])
    first = get_first_odds_snapshot(db_path, "ev1")
    assert first["odds"][0] == 2.95 and first["fetched_at"]


from app.db import create_upload_session, get_recent_uploads


def test_recent_uploads_latest_per_filename(db_path):
    a1 = create_upload_session(db_path, "A.xlsx", b"1")
    b1 = create_upload_session(db_path, "B.xlsx", b"2")
    a2 = create_upload_session(db_path, "A.xlsx", b"3")
    ups = get_recent_uploads(db_path)
    assert [u["session_id"] for u in ups] == [a2, b1]
    assert ups[0]["excel_filename"] == "A.xlsx" and ups[0]["created_at"]

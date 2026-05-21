import sqlite3
import json
import os
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "data/schedella.db")


@contextmanager
def get_connection(path: str = DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db(path: str = DB_PATH) -> None:
    with get_connection(path) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS session (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                excel_filename TEXT NOT NULL,
                params_json   TEXT NOT NULL
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
                pronostico   TEXT,
                raw_odds     REAL,
                ev_score     REAL,
                best_ev      TEXT,
                position     INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS result (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                schedella_id      INTEGER NOT NULL REFERENCES schedella(id),
                outcome           TEXT CHECK(outcome IN ('won','lost','void')),
                actual_multiplier REAL,
                stake             REAL,
                profit            REAL,
                resolved_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


def insert_session(path: str, excel_filename: str, params: dict) -> int:
    with get_connection(path) as con:
        cur = con.execute(
            "INSERT INTO session (excel_filename, params_json) VALUES (?,?)",
            (excel_filename, json.dumps(params)),
        )
        return cur.lastrowid


def insert_schedella(path: str, session_id: int, player_num: int) -> int:
    with get_connection(path) as con:
        cur = con.execute(
            "INSERT INTO schedella (session_id, player_num) VALUES (?,?)",
            (session_id, player_num),
        )
        return cur.lastrowid


def insert_pick(path: str, schedella_id: int, match_name: str,
                match_date: str, pronostico: Optional[str],
                raw_odds: Optional[float], ev_score: Optional[float],
                best_ev: Optional[str], position: int) -> int:
    with get_connection(path) as con:
        cur = con.execute(
            """INSERT INTO pick
               (schedella_id, match_name, match_date, pronostico,
                raw_odds, ev_score, best_ev, position)
               VALUES (?,?,?,?,?,?,?,?)""",
            (schedella_id, match_name, match_date, pronostico,
             raw_odds, ev_score, best_ev, position),
        )
        return cur.lastrowid


def update_pick_pronostico(path: str, pick_id: int, pronostico: str) -> None:
    with get_connection(path) as con:
        con.execute("UPDATE pick SET pronostico=? WHERE id=?", (pronostico, pick_id))


def insert_result(path: str, schedella_id: int, outcome: str,
                  actual_multiplier: float, stake: float) -> int:
    profit = (stake * actual_multiplier - stake) if outcome == "won" else (-stake if outcome == "lost" else 0.0)
    with get_connection(path) as con:
        cur = con.execute(
            """INSERT INTO result (schedella_id, outcome, actual_multiplier, stake, profit)
               VALUES (?,?,?,?,?)""",
            (schedella_id, outcome, actual_multiplier, stake, profit),
        )
        return cur.lastrowid


def get_session(path: str, session_id: int) -> dict:
    with get_connection(path) as con:
        row = con.execute("SELECT * FROM session WHERE id=?", (session_id,)).fetchone()
    if not row:
        return {}
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    return d


def get_picks_for_schedella(path: str, schedella_id: int) -> list[dict]:
    with get_connection(path) as con:
        rows = con.execute(
            "SELECT * FROM pick WHERE schedella_id=? ORDER BY position",
            (schedella_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_schedelle(path: str, limit: int = 50) -> list[dict]:
    with get_connection(path) as con:
        rows = con.execute("""
            SELECT s.id, s.created_at, s.player_num,
                   se.excel_filename,
                   r.outcome, r.actual_multiplier, r.stake, r.profit
            FROM schedella s
            JOIN session se ON se.id = s.session_id
            LEFT JOIN result r ON r.schedella_id = s.id
            ORDER BY s.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_stats(path: str) -> dict:
    with get_connection(path) as con:
        row = con.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN r.outcome='won' THEN 1 ELSE 0 END) as wins,
                SUM(r.profit) as total_profit,
                SUM(r.stake) as total_stake
            FROM schedella s
            LEFT JOIN result r ON r.schedella_id = s.id
        """).fetchone()
    total = row["total"] or 0
    wins = row["wins"] or 0
    total_profit = row["total_profit"] or 0.0
    total_stake = row["total_stake"] or 0.0
    win_rate = (wins / total * 100) if total > 0 else 0.0
    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
    return {
        "total": total,
        "wins": wins,
        "win_rate": round(win_rate, 1),
        "roi": round(roi, 1),
        "total_profit": round(total_profit, 2),
    }


def get_roi_over_time(path: str) -> list[dict]:
    with get_connection(path) as con:
        rows = con.execute("""
            SELECT s.created_at as date, r.profit
            FROM schedella s
            JOIN result r ON r.schedella_id = s.id
            WHERE r.outcome IN ('won','lost')
            ORDER BY s.created_at ASC
        """).fetchall()
    cumulative = 0.0
    result = []
    for r in rows:
        cumulative += r["profit"] or 0.0
        result.append({"date": r["date"][:10], "cumulative_profit": round(cumulative, 2)})
    return result


def get_winrate_by_pronostico(path: str) -> list[dict]:
    with get_connection(path) as con:
        rows = con.execute("""
            SELECT p.pronostico,
                   COUNT(*) as total,
                   SUM(CASE WHEN r.outcome='won' THEN 1 ELSE 0 END) as wins
            FROM pick p
            JOIN schedella s ON s.id = p.schedella_id
            JOIN result r ON r.schedella_id = s.id
            WHERE p.pronostico IS NOT NULL
            GROUP BY p.pronostico
        """).fetchall()
    return [dict(r) for r in rows]


def get_schedelle_for_session(path: str, session_id: int) -> list[int]:
    with get_connection(path) as con:
        rows = con.execute(
            "SELECT id FROM schedella WHERE session_id=? ORDER BY player_num",
            (session_id,)
        ).fetchall()
    return [r["id"] for r in rows]


def update_pick_odds_ev(path: str, pick_id: int, raw_odds: float, ev_score: float) -> None:
    with get_connection(path) as con:
        con.execute(
            "UPDATE pick SET raw_odds=?, ev_score=? WHERE id=?",
            (raw_odds, ev_score, pick_id)
        )


def update_session_matches(path: str, session_id: int, session_data: dict) -> None:
    with get_connection(path) as con:
        existing = con.execute(
            "SELECT params_json FROM session WHERE id=?", (session_id,)
        ).fetchone()
        params = json.loads(existing["params_json"])
        params["_match_data"] = session_data
        con.execute(
            "UPDATE session SET params_json=? WHERE id=?",
            (json.dumps(params), session_id)
        )
